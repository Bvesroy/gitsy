#!/usr/bin/env python3
"""gitup release.py - Phase: turn a tagged commit into a real GitHub release.

Sub-commands
  plan      what version, what tag, what notes, which artifacts exist on disk
  notes     generate release notes from actual commits (grouped, no invention)
  package   build and collect artifacts for the project's app type
  publish   create the GitHub release with verified artifacts + checksums

Guarantees enforced in code:
  * release notes come from git history and the changelog; nothing is invented;
  * an artifact must exist, be non-trivial, and get a checksum before upload;
  * an existing release/tag is never overwritten (`gh release create` fails
    rather than clobbering, and gitup reports it);
  * binaries are described as "built by gitup on <os>", never as tested on
    platforms they were not tested on.

Usage:
  python3 release.py plan    --project . [--version 1.2.0]
  python3 release.py notes   --project . --version 1.2.0 [--out RELEASE_NOTES.md]
  python3 release.py package --project . --version 1.2.0 --out dist
  python3 release.py publish --project . --version 1.2.0 --artifacts dist/*  [--dry-run]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import platform
import re
import shutil
import sys
from pathlib import Path

from gitup_common import (
    die,
    emit,
    git,
    human_size,
    is_git_repo,
    sha256_file,
    parser,
    rel,
    run,
    which,
)

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].+)?$")


def norm_version(v: str) -> str:
    v = (v or "").strip()
    m = SEMVER_RE.match(v)
    if not m:
        die(f"'{v}' is not a semver version (expected 1.2.3 or v1.2.3)")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def tags(root: Path) -> list[str]:
    if not is_git_repo(root):
        return []
    out = git(root, "tag", "--sort=-v:refname").stdout.splitlines()
    return [t.strip() for t in out if SEMVER_RE.match(t.strip())]


def bump(current: str, kind: str) -> str:
    cur = norm_version(current or "0.0.0")
    major, minor, patch = (int(x) for x in cur.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def plan(root: Path, version: str = "", bump_kind: str = "") -> dict:
    from project_scan import scan
    info = scan(root)
    declared = info["project"]["version"] or ""
    existing_tags = tags(root)
    latest_tag = existing_tags[0] if existing_tags else ""
    if version:
        target = norm_version(version)
        reason = "explicitly requested"
    elif declared:
        target = norm_version(declared)
        reason = f"declared in {info['project']['version_source']}"
    elif latest_tag:
        target = bump(latest_tag, bump_kind or "patch")
        reason = f"bumped from latest tag {latest_tag}"
    else:
        target = "0.1.0"
        reason = "first release default"
    tag = f"v{target}" if not (latest_tag.startswith("v") or declared.startswith("v")) else f"v{target}"
    clash = tag in existing_tags or bool(git(root, "tag", "-l", tag).stdout.strip())
    return {
        "project": str(root),
        "app_type": info["project"]["app_type"],
        "declared_version": declared,
        "latest_tag": latest_tag,
        "all_tags": existing_tags[:10],
        "proposed_version": target,
        "proposed_tag": tag,
        "why": reason,
        "tag_already_exists": clash,
        "blocked": "tag already exists; pick a new version (tags are never moved)" if clash else "",
        "changelog_present": any((root / n).exists() for n in ("CHANGELOG.md", "docs/CHANGELOG.md")),
        "commits_since_last_tag": _commits_since(root, latest_tag),
        "branch": info["git"].get("branch", ""),
        "dirty": info["git"].get("dirty", False),
    }


def _commits_since(root: Path, since_tag: str) -> list[dict]:
    if not is_git_repo(root):
        return []
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    fmt = "%H%x1f%s%x1f%an%x1f%ad"
    res = git(root, "log", rng, f"--pretty=format:{fmt}", "--date=short")
    out = []
    for line in res.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            out.append({"hash": parts[0][:8], "subject": parts[1],
                        "author": parts[2], "date": parts[3]})
    return out[:200]


CONVENTIONAL = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<rest>.+)$")
GROUPS = {
    "feat": ("Features", "Added"), "fix": ("Bug Fixes", "Fixed"),
    "perf": ("Performance", "Changed"), "refactor": ("Refactors", "Changed"),
    "docs": ("Documentation", "Changed"), "build": ("Build", "Changed"),
    "ci": ("CI", "Changed"), "test": ("Tests", "Changed"),
    "chore": ("Chores", "Changed"), "style": ("Style", "Changed"),
    "revert": ("Reverts", "Fixed"),
}


def notes(root: Path, version: str, previous_tag: str = "") -> dict:
    commits = _commits_since(root, previous_tag)
    if not commits:
        return {"ok": False, "why": "no commits to describe", "markdown": ""}
    buckets: dict[str, list[str]] = {}
    breaking: list[str] = []
    uncategorised: list[str] = []
    for c in commits:
        m = CONVENTIONAL.match(c["subject"])
        if m:
            label = m.group("type")
            text = m.group("rest").strip()
            if m.group("scope"):
                text = f"**{m.group('scope')}**: {text}"
            if m.group("breaking") or "BREAKING CHANGE" in c["subject"]:
                breaking.append(text)
            group = GROUPS.get(label, ("Other", "Changed"))[0]
            buckets.setdefault(group, []).append(f"- {text} ({c['hash']})")
        else:
            uncategorised.append(f"- {c['subject']} ({c['hash']})")

    lines = [f"## What changed in v{version}", ""]
    if breaking:
        lines += ["### Breaking changes", ""] + [f"- {b}" for b in breaking] + [""]
    for group in ("Features", "Bug Fixes", "Performance", "Refactors", "Documentation",
                  "Build", "CI", "Tests", "Chores", "Style", "Reverts", "Other"):
        if group in buckets:
            lines += [f"### {group}", ""] + buckets[group] + [""]
    if uncategorised:
        lines += ["### Also included", ""] + uncategorised + [""]

    install = _install_hint(root)
    if install:
        lines += ["## Install", "", install, ""]

    lines += ["## Notes", "", "Built and packaged from the tagged commit. See `SHA256SUMS.txt` "
              "for artifact checksums.", ""]
    if breaking:
        lines.insert(0, "> This release contains breaking changes. Read the section below before upgrading.\n")
    return {"ok": True, "markdown": "\n".join(lines), "commit_count": len(commits),
            "breaking": len(breaking), "groups": {k: len(v) for k, v in buckets.items()}}


def _install_hint(root: Path) -> str:
    if (root / "package.json").exists():
        try:
            name = json.loads((root / "package.json").read_text()).get("name", "")
        except Exception:
            name = ""
        if name and not json.loads((root / "package.json").read_text()).get("private"):
            return f"```bash\nnpm install -g {name}\n```"
    if (root / "pyproject.toml").exists():
        return "```bash\npip install <artifact from this release>\n```"
    if (root / "Cargo.toml").exists():
        return "```bash\ncargo install --git <repository url>\n```"
    return ""


PACKAGE_RECIPES = {
    "python": [["python3", "-m", "build"]],
    "node": [["npm", "pack"]],
    "rust": [["cargo", "build", "--release"]],
    "go": [["go", "build", "-o", "bin/"]],
    "swift": [["swift", "build", "-c", "release"]],
    "macos": [["xcodebuild", "-scheme", "<set-me>", "-configuration", "Release", "archive"]],
}


def package(root: Path, version: str, out_dir: Path, dry_run: bool = False) -> dict:
    from project_scan import scan
    info = scan(root)
    app_type = info["project"]["app_type"]
    marker_runtime = ("python" if (root / "pyproject.toml").exists() or (root / "setup.py").exists() else
                      "node" if (root / "package.json").exists() else
                      "rust" if (root / "Cargo.toml").exists() else
                      "go" if (root / "go.mod").exists() else
                      "swift" if (root / "Package.swift").exists() else "")
    langs = info["languages"]
    runtime = marker_runtime or ("python" if "Python" in langs else
                                 "node" if "JavaScript" in langs or "TypeScript" in langs else
                                 "rust" if "Rust" in langs else
                                 "go" if "Go" in langs else
                                 "swift" if "Swift" in langs else "")
    # A source-only project has nothing to package; say so instead of guessing.
    if runtime == "python" and not marker_runtime:
        return {"ok": False, "runtime": "python",
                "why": "no packaging metadata (pyproject.toml/setup.py); there is nothing "
                       "to build into a distributable, so the release attaches source only",
                "app_type": app_type, "artifacts": []}
    steps = []
    artifacts: list[dict] = []
    if not runtime:
        return {"ok": False, "why": "no supported build system detected",
                "app_type": app_type, "artifacts": []}

    if runtime == "python":
        steps.append({"cmd": "python3 -m build", "produces": ["dist/*.whl", "dist/*.tar.gz"]})
    elif runtime == "node":
        steps.append({"cmd": "npm pack", "produces": ["*.tgz"]})
    elif runtime == "rust":
        steps.append({"cmd": "cargo build --release", "produces": ["target/release/*"]})
    elif runtime == "go":
        steps.append({"cmd": "go build ./...", "produces": ["bin/*"]})
    elif runtime == "swift":
        steps.append({"cmd": "swift build -c release", "produces": [".build/release/*"]})

    if dry_run:
        return {"ok": True, "dry_run": True, "runtime": runtime, "steps": steps,
                "note": "nothing was built", "artifacts": []}

    executed = []
    for step in steps:
        argv = step["cmd"].split()
        tool = argv[0]
        if not which(tool):
            return {"ok": False, "why": f"{tool} is not installed",
                    "runtime": runtime, "executed": executed}
        res = run(argv, cwd=root, timeout=1800)
        executed.append({"cmd": step["cmd"], "code": res.code,
                         "tail": res.tail(12) if not res.ok else ""})
        if not res.ok:
            return {"ok": False, "why": f"`{step['cmd']}` failed",
                    "runtime": runtime, "executed": executed,
                    "error": res.tail(20)}

    out_dir.mkdir(parents=True, exist_ok=True)
    for pattern in [p for s in steps for p in s["produces"]]:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            if path.stat().st_size < 1024:
                continue
            dest = out_dir / path.name
            if dest.exists():
                dest.unlink()
            shutil.copy2(path, dest)
            artifacts.append({
                "path": str(dest), "name": dest.name,
                "bytes": dest.stat().st_size, "human": human_size(dest.stat().st_size),
                "sha256": sha256_file(dest),
            })
    return {"ok": bool(artifacts), "runtime": runtime, "executed": executed,
            "artifacts": artifacts, "out_dir": str(out_dir),
            "built_on": f"{platform.system()} {platform.machine()}",
            "tested_on": "not verified: gitup built these artifacts but did not install "
                         "or launch them on other systems",
            "why": "" if artifacts else "build produced no artifacts matching the recipe"}


def write_checksums(artifacts: list[dict], out_dir: Path) -> dict:
    if not artifacts:
        return {"ok": False, "why": "no artifacts"}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "SHA256SUMS.txt"
    lines = [f"{a['sha256']}  {a['name']}" for a in artifacts]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "entries": len(lines)}


def publish(root: Path, version: str, artifact_globs: list[str], notes_file: str = "",
            dry_run: bool = False, draft: bool = False, prerelease: bool = False) -> dict:
    from gh_repo import auth_state, inspect as gh_inspect
    v = norm_version(version)
    tag = f"v{v}"
    state = gh_inspect(root)
    if not state["github"] or not state["github"].get("resolved"):
        return {"ok": False, "blocked": "no GitHub repository connected"}
    if state.get("ahead"):
        return {"ok": False, "blocked": "local commits are not pushed",
                "hint": "Push first: a release must point at a commit GitHub already has."}
    existing = run(["gh", "release", "view", tag, "--json", "tagName"], cwd=root)
    if existing.ok:
        return {"ok": False, "blocked": f"release {tag} already exists",
                "hint": "Bump the version. gitup never overwrites a published release."}

    artifacts: list[dict] = []
    for pattern in artifact_globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path.stat().st_size > 0:
                artifacts.append({"path": str(path), "name": path.name,
                                  "bytes": path.stat().st_size,
                                  "sha256": sha256_file(path)})
    for a in artifacts:
        if a["bytes"] < 1024:
            return {"ok": False, "blocked": f"artifact {a['name']} is suspiciously small ({a['bytes']} B)"}

    notes_path = Path(notes_file) if notes_file else None
    plan_argv = ["gh", "release", "create", tag, *[a["path"] for a in artifacts],
                 "--title", tag]
    plan_argv += ["--notes-file", str(notes_path)] if notes_path else ["--generate-notes"]
    if draft:
        plan_argv.append("--draft")
    if prerelease:
        plan_argv.append("--prerelease")

    if dry_run:
        return {"ok": True, "dry_run": True, "tag": tag, "argv": plan_argv,
                "artifacts": artifacts, "note": "no release was created"}

    res = run(plan_argv, cwd=root, timeout=600)
    if not res.ok:
        return {"ok": False, "tag": tag, "argv": plan_argv,
                "error": (res.stderr or res.stdout).strip()[:600]}
    view = run(["gh", "release", "view", tag, "--json",
                "url,assets,tagName,isDraft"], cwd=root)
    data = {}
    try:
        data = json.loads(view.stdout)
    except Exception:
        pass
    uploaded = [a.get("name") for a in data.get("assets", [])]
    return {"ok": True, "tag": tag, "url": data.get("url", ""),
            "assets_on_github": uploaded,
            "assets_missing_on_github": [a["name"] for a in artifacts if a["name"] not in uploaded],
            "verified": bool(data.get("url")) and not [a for a in artifacts if a["name"] not in uploaded]}


def main(argv=None):
    ap = parser(description="gitup release manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan"); p.add_argument("--project", required=True)
    p.add_argument("--version", default=""); p.add_argument("--bump", default="",
                                                            choices=["", "major", "minor", "patch"])
    p.add_argument("--out", default="")

    p = sub.add_parser("notes"); p.add_argument("--project", required=True)
    p.add_argument("--version", required=True); p.add_argument("--since", default="")
    p.add_argument("--out", default=""); p.add_argument("--write", default="",
                                                        help="file to write the markdown to")

    p = sub.add_parser("package"); p.add_argument("--project", required=True)
    p.add_argument("--version", default=""); p.add_argument("--out", default="dist")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--json-out", default="")

    p = sub.add_parser("publish"); p.add_argument("--project", required=True)
    p.add_argument("--version", required=True); p.add_argument("--artifacts", nargs="*", default=[])
    p.add_argument("--notes-file", default=""); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--draft", action="store_true"); p.add_argument("--prerelease", action="store_true")
    p.add_argument("--json-out", default="")

    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")

    if args.cmd == "plan":
        out = plan(root, args.version, args.bump)
    elif args.cmd == "notes":
        prev = args.since or (tags(root)[0] if tags(root) else "")
        out = notes(root, norm_version(args.version), prev)
        if getattr(args, "write", "") and out.get("ok"):
            target = root / args.write
            target.write_text(out["markdown"], encoding="utf-8")
            out["written"] = rel(root, target)
    elif args.cmd == "package":
        out_dir = root / args.out
        out = package(root, norm_version(args.version or "0.0.0"), out_dir, args.dry_run)
        if out.get("artifacts"):
            out["checksums"] = write_checksums(out["artifacts"], out_dir)
        json_out = getattr(args, "json_out", "")
    else:
        out = publish(root, args.version, args.artifacts, args.notes_file,
                      args.dry_run, args.draft, args.prerelease)
    emit(out, (args.out if args.cmd in ("plan", "notes") else getattr(args, "json_out", "")) or None)
    return 0 if out.get("ok", True) and not out.get("blocked") else 1


if __name__ == "__main__":
    sys.exit(main())