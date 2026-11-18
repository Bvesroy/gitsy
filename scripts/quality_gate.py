#!/usr/bin/env python3
"""gitup quality_gate.py - Phase: refuse to call a repository finished too early.

Runs every checklist and applies hard gates. A gate is a property, not a score:
the repository either satisfies it or it does not.

Gates
  G1 no blocker-severity security finding          (secrets, keys, .env)
  G2 a README exists and is substantive            (>= 900 bytes, has install/usage)
  G3 no unresolved template placeholder            ({{...}} left in published docs)
  G4 no broken local link or image                 (checked by link_check)
  G5 README claims match reality                   (badges/claims with no evidence)
  G6 repository is connected and pushed            (when --require-remote)
  G7 license file exists and matches the manifest  (when --require-license)
  G8 no self-introduced agent branding in README   (branding_scan)

Exit codes: 0 all required gates pass, 1 a required gate failed.
`--soft` reports the same result but always exits 0 (for CI smoke checks).

Usage:
  python3 quality_gate.py --project ~/Developer/MyProject [--out gate.json]
                          [--require-remote] [--require-license] [--soft]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
from pathlib import Path

from gitup_common import (
    die,
    emit,
    is_git_repo,
    parser,
    read_text,
    rel,
)

README_NAMES = ("README.md", "README.rst", "README.txt", "README")
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE")
SPDX_HINTS = {
    "MIT": r"\bMIT License\b|\bPermission is hereby granted, free of charge\b",
    "Apache-2.0": r"\bApache License\b[^\n]*2\.0",
    "GPL-3.0": r"\bGNU GENERAL PUBLIC LICENSE\b[^\n]*Version 3",
    "GPL-2.0": r"\bGNU GENERAL PUBLIC LICENSE\b[^\n]*Version 2",
    "BSD-3-Clause": r"\bRedistribution and use in source and binary forms\b",
    "MPL-2.0": r"\bMozilla Public License\b[^\n]*2\.0",
    "AGPL-3.0": r"\bGNU AFFERO GENERAL PUBLIC LICENSE\b",
    "Unlicense": r"\bThis is free and unencumbered software\b",
}


def find_readme(root: Path):
    for name in README_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def find_license(root: Path):
    for name in LICENSE_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def gate_g1(security: dict) -> dict:
    blockers = [f for f in security.get("findings", []) if f["severity"] == "blocker"]
    return {"id": "G1", "name": "No publishable secrets or keys",
            "passed": not blockers,
            "detail": "clean" if not blockers else f"{len(blockers)} blocker(s)",
            "evidence": [b["title"] for b in blockers[:10]]}


def gate_g2(root: Path, readme) -> dict:
    if not readme:
        return {"id": "G2", "name": "README exists and is substantive", "passed": False,
                "detail": "no README found", "evidence": []}
    text = read_text(readme)
    size = len(text.encode())
    has_install = bool(re.search(r"(?i)^#{1,4}\s*(install|installation|getting started|setup)", text, re.M))
    has_usage = bool(re.search(r"(?i)^#{1,4}\s*(usage|quick ?start|example)", text, re.M))
    placeholders = re.findall(r"\{\{[A-Z_]+\}\}", text)
    todo_markers = re.findall(r"(?i)\b(TODO|TBD|FIXME|lorem ipsum|PLACEHOLDER)\b", text)
    passed = size >= 900 and has_install and has_usage and not placeholders and len(todo_markers) <= 2
    return {"id": "G2", "name": "README exists and is substantive", "passed": passed,
            "detail": f"{size} bytes; install section: {has_install}; usage section: {has_usage}",
            "evidence": [f"{rel(root, readme)}"] +
                        ([f"{len(placeholders)} placeholder(s)"] if placeholders else []) +
                        ([f"{len(todo_markers)} TODO/TBD marker(s)"] if todo_markers else [])}


# A template legitimately contains placeholders - that is what a template is.
# So does documentation that *describes* placeholders. A published README does not.
TEMPLATE_DIR_NAMES = {"templates", "template", "fixtures", "testdata", "examples",
                      "tests", "adapters"}
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


def _is_template_like(path: Path, root: Path) -> bool:
    parts = set(path.relative_to(root).parts[:-1])
    return bool(parts & TEMPLATE_DIR_NAMES)


def _placeholders_are_illustrative(text: str) -> bool:
    """True when every placeholder appears inside a fenced block or is quoted.

    Documentation explaining "the renderer refuses {{PLACEHOLDER}}" is not an
    unfinished template; an unfinished template is one where a placeholder sits
    in prose that a reader would see as a real value.
    """
    lines = text.splitlines()
    in_fence = False
    prose_hits = []
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if stripped.startswith((">", "    ")):
            continue
        # A placeholder immediately inside backticks or quotes is being named.
        if re.search(r"[`'\"]\{\{[A-Z_]+\}\}[`'\"]", line):
            continue
        if PLACEHOLDER_RE.search(line):
            prose_hits.append(stripped[:80])
    return not prose_hits


def gate_g3(root: Path) -> dict:
    offenders = []
    for path in root.rglob("*.md"):
        if any(part in str(path) for part in (".git/", "node_modules/", "vendor/")):
            continue
        if _is_template_like(path, root):
            continue
        text = read_text(path)
        if not PLACEHOLDER_RE.search(text):
            continue
        if _placeholders_are_illustrative(text):
            continue
        hits = PLACEHOLDER_RE.findall(text)
        offenders.append(f"{rel(root, path)}: {sorted(set(hits))[:4]}")
    return {"id": "G3", "name": "No unresolved template placeholders", "passed": not offenders,
            "detail": "clean" if not offenders else f"{len(offenders)} file(s)",
            "evidence": offenders[:10]}


def gate_g4(root: Path) -> dict:
    from link_check import check_links
    report = check_links(root, remote=False)
    broken = [f for f in report["findings"] if f["severity"] in ("blocker", "high")]
    # A link in a template is a template variable, and a link in an example is
    # an illustration; neither can resolve. Only real docs are held to this.
    broken = [f for f in broken
              if not any(_is_template_like(root / ev.split(":")[0], root)
                         for ev in f.get("evidence", []) if ":" in ev)]
    return {"id": "G4", "name": "No broken local links or images", "passed": not broken,
            "detail": f"{report['links_checked']} links checked",
            "evidence": [f["title"] for f in broken[:10]]}


FAKE_BADGE_RE = re.compile(
    r"(?i)(?:badge/(?:stars|downloads|users|uptime|performance|coverage)[^)\s]*"
    r"|shields\.io/badge/(?:stars|downloads|users|uptime|build-passing%20instantly))")
CLAIM_RE = re.compile(
    r"(?i)\b(?:production[- ]ready|battle[- ]tested|enterprise[- ]grade|"
    r"100% (?:secure|tested|reliable)|military[- ]grade|blazing(?:ly)? fast)\b")


# Sentences that disclaim rather than assert. A README saying "no fabricated
# benchmarks, no production ready claims" is doing exactly what gitup asks for;
# flagging it would train the agent to avoid describing its own honesty.
_NEGATION_CUES = re.compile(
    r"(?i)\b(?:no|not|never|without|refuse[sd]?|cannot|can't|won't|avoid|"
    r"instead of|rather than|do not|does not|don't|doesn't|isn't|aren't)\b")


def _unqualified_claims(text: str) -> set:
    """Superlatives asserted about this project, excluding disclaimed ones."""
    found = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        matches = [m.group(0) for m in CLAIM_RE.finditer(stripped)]
        if not matches:
            continue
        # Split on sentence-ish boundaries; check the clause holding the claim.
        for clause in re.split(r"(?<=[.!?;:])\s+|\s+(?:but|however|yet|except)\s+", stripped):
            if not CLAIM_RE.search(clause):
                continue
            if _NEGATION_CUES.search(clause):
                continue
            if stripped.startswith(("-", "*", "|")):
                # A list item or table row that disclaims is equally fine.
                if _NEGATION_CUES.search(stripped):
                    continue
                if _under_negative_heading(text, line):
                    continue
            found.update(m.group(0) for m in CLAIM_RE.finditer(clause))
    return found


# One leading (?i) only: a global flag anywhere else in the pattern is a
# PatternError in Python 3.11+. This is the mistake gitup tells agents not to make.
_NEGATIVE_HEADING_RE = re.compile(
    r"""(?ix)^
    \s*\#*\s*
    (?:(?:what|this|it|we|gitup|the\ tool)\s+)*
    (?:will\ not|does\ not|doesn't|never|refus\w*|not\ do|won't|
       limitations|non-goals|not\ supported)
    \b.*$""")


def _under_negative_heading(text: str, line: str) -> bool:
    """True when the nearest preceding heading or lead-in disclaims."""
    lines = text.splitlines()
    try:
        idx = lines.index(line)
    except ValueError:
        return False
    for prev in reversed(lines[:idx]):
        s = prev.strip()
        if not s:
            continue
        if s.startswith("#") or s.endswith(":"):
            return bool(_NEGATIVE_HEADING_RE.match(s))
        if s.startswith(("-", "*")) and prev is not line:
            continue
        break
    return False


def gate_g5(root: Path, readme) -> dict:
    if not readme:
        return {"id": "G5", "name": "README claims are backed by evidence",
                "passed": True, "detail": "no README to inspect", "evidence": []}
    text = read_text(readme)
    problems = []
    for badge in set(FAKE_BADGE_RE.findall(text)):
        problems.append(f"unverifiable badge: {badge}")
    for claim in _unqualified_claims(text):
        problems.append(f"unqualified claim: '{claim}'")
    # A CI badge is only honest when a workflow actually exists.
    if re.search(r"(?i)actions/workflows/([^/)]+)", text):
        for wf in set(re.findall(r"actions/workflows/([^/)]+)", text)):
            if not (root / ".github" / "workflows" / wf).exists():
                problems.append(f"CI badge points at missing workflow: {wf}")
    return {"id": "G5", "name": "README claims are backed by evidence",
            "passed": not problems, "detail": "clean" if not problems else f"{len(problems)} issue(s)",
            "evidence": problems[:10]}


def gate_g6(root: Path) -> dict:
    from git_sync import verify
    res = verify(root, fetch=False)
    return {"id": "G6", "name": "Repository connected and pushed", "passed": bool(res.get("ok")),
            "detail": f"local {res.get('local_head')} / remote {res.get('remote_head')}",
            "evidence": [] if res.get("ok") else [res.get("blocked") or res.get("hint", "")]}


def gate_g7(root: Path) -> dict:
    lic = find_license(root)
    if not lic:
        return {"id": "G7", "name": "License present and consistent", "passed": False,
                "detail": "no LICENSE file", "evidence": []}
    text = read_text(lic)
    detected = [name for name, pattern in SPDX_HINTS.items() if re.search(pattern, text, re.I)]
    declared = ""
    pkg = root / "package.json"
    if pkg.exists():
        try:
            declared = (json.loads(pkg.read_text()).get("license") or "")
        except Exception:
            declared = ""
    consistent = True
    detail = f"detected: {detected[0] if detected else 'unknown'}"
    if declared and detected and declared not in detected and declared.upper() not in [d.upper() for d in detected]:
        consistent = False
        detail += f"; package.json says '{declared}'"
    return {"id": "G7", "name": "License present and consistent",
            "passed": bool(detected) and consistent, "detail": detail,
            "evidence": [rel(root, lic)] + ([f"package.json license: {declared}"] if declared else [])}


def gate_g8(root: Path, readme) -> dict:
    from branding_scan import scan_branding
    report = scan_branding(root)
    in_readme = [f for f in report["findings"]
                 if f["checklist"] == "presentation"
                 and f["severity"] in ("medium", "high", "blocker")
                 and any((readme and Path(e.split(":")[0]).name == readme.name)
                         for e in f["evidence"])]
    return {"id": "G8", "name": "No development-agent branding in the README",
            "passed": not in_readme,
            "detail": "clean" if not in_readme else f"{len(in_readme)} line(s)",
            "evidence": [f["title"] for f in in_readme[:6]]}


def run_gate(root: Path, require_remote: bool = False,
             require_license: bool = False) -> dict:
    from secret_scan import scan_secrets
    security = scan_secrets(root, history=False)
    readme = find_readme(root)
    gates = [gate_g1(security), gate_g2(root, readme), gate_g3(root), gate_g4(root),
             gate_g5(root, readme), gate_g8(root, readme)]
    optional = {"G6": require_remote, "G7": require_license}
    if require_remote:
        gates.append(gate_g6(root))
    if require_license:
        gates.append(gate_g7(root))

    required_failed = [g for g in gates if not g["passed"]]
    verdict = "PASS" if not required_failed else "FAIL"
    next_actions = []
    for g in required_failed:
        if g["id"] == "G1":
            next_actions.append("Rotate every exposed credential, then remove it from the files "
                                "and (with authorization) from history.")
        elif g["id"] == "G2":
            next_actions.append("Write the README: what it is, install, usage, limitations.")
        elif g["id"] == "G3":
            next_actions.append("Fill or delete the remaining template placeholders.")
        elif g["id"] == "G4":
            next_actions.append("Fix or remove the broken links and images.")
        elif g["id"] == "G5":
            next_actions.append("Delete badges/claims you cannot back with evidence.")
        elif g["id"] == "G6":
            next_actions.append("Push the current branch so the remote matches local.")
        elif g["id"] == "G7":
            next_actions.append("Add the license you actually intend and keep manifests consistent.")
        elif g["id"] == "G8":
            next_actions.append("Delete development-agent branding from the README.")
    return {
        "project": str(root),
        "verdict": verdict,
        "gates": gates,
        "required_passes": f"{len(gates) - len(required_failed)}/{len(gates)}",
        "next_actions": next_actions,
        "security_summary": security["summary"],
        "readme": rel(root, readme) if readme else None,
        "note": "A PASS means the gates ran clean. It is not a general claim that the "
                "software is bug-free or production ready.",
    }


def main(argv=None):
    ap = parser(description="gitup quality gate")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--require-remote", action="store_true")
    ap.add_argument("--require-license", action="store_true")
    ap.add_argument("--soft", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    report = run_gate(root, args.require_remote, args.require_license)
    emit(report, args.out or None)
    if args.soft:
        return 0
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())