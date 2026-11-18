#!/usr/bin/env python3
"""gitup prepare.py - run the read-only half of the GITUP workflow in one pass.

This is the "look before you touch" stage. It performs Phase A (discovery),
Phase B (project audit), Phase C (security), the documentation and presentation
audits, then the quality gate - and writes a single machine-readable run record
plus a human summary. It changes nothing in the project.

Everything it cannot check is listed as a limitation rather than skipped
silently.

Usage:
  python3 prepare.py --project ~/Developer/MyProject [--out .gitup/prepare.json]
                     [--history] [--remote-links]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import datetime
import json
import sys
from pathlib import Path

from gitup_common import (
    die,
    emit,
    human_size,
    is_git_repo,
    which,
    parser,
    rel,
    run,
    summarize,
)


def audit_project(root: Path) -> dict:
    """Phase B: things that are wrong with the project itself, not its packaging."""
    from project_scan import scan
    info = scan(root, deep=True)
    findings: list[dict] = []

    def add(sev, ident, title, detail="", evidence=None, fix=""):
        findings.append({"checklist": "project", "id": ident, "severity": sev,
                         "title": title, "detail": detail,
                         "evidence": evidence or [], "fix": fix})

    if not info["project"]["version"]:
        add("low", "project.no-version", "No version declared anywhere",
            "Releases need a version to tag against.",
            [info["project"]["version_source"] or "(no manifest)"],
            "Add a version to your manifest, or accept the tag-driven default.")
    if not info["documentation"]:
        add("high", "project.no-docs", "No README or documentation files",
            "A repository without a README looks abandoned on arrival.",
            [], "Write a README (gitup renders one from measured facts).")
    if info["totals"]["files"] == 0:
        add("blocker", "project.empty", "The directory has no files",
            "Nothing to publish.", [], "Point gitup at the real project directory.")
    for big in info["big_files"]:
        add("medium", "project.large-file", f"Large file in the tree: {big['path']}",
            f"{human_size(big['bytes'])}; slows clones and may be a build artifact.",
            [big["path"]], "Attach it to a release instead of committing it.")
    if not info["ci"]["workflows"]:
        add("low", "project.no-ci", "No continuous integration",
            "Nothing runs the tests automatically on push or pull request.",
            [], "Add a test workflow (gitup can generate one).")

    # Commands that look real but cannot be run here.
    unverified = []
    for kind, items in info["commands"].items():
        for item in items:
            if isinstance(item, dict) and item.get("cmd"):
                tool = item["cmd"].split()[0]
                if not which(tool):
                    unverified.append({"command": item["cmd"], "missing_tool": tool})
    if unverified:
        add("info", "project.missing-tools",
            f"{len(unverified)} documented command(s) reference a tool that is not installed",
            "Build/test instructions in the README cannot be verified on this machine.",
            [u["command"] for u in unverified[:8]],
            "Install the toolchain or mark those instructions as untested.")
    return {"scan": info, "findings": findings, "unverified_commands": unverified}


def audit_docs(root: Path, remote: bool) -> dict:
    from link_check import check_links
    links = check_links(root, remote=remote)
    docs_present = [n for n in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md",
                                "SECURITY.md", "LICENSE", ".gitignore",
                                "CODE_OF_CONDUCT.md", "SUPPORT.md")
                    if (root / n).exists()]
    findings = list(links["findings"])
    if not (root / "README.md").exists() and (root / "README.rst").exists():
        findings.append({"checklist": "docs", "id": "docs.rst-readme", "severity": "low",
                         "title": "README is reStructuredText",
                         "detail": "GitHub renders it, but .md is what most readers expect.",
                         "evidence": ["README.rst"], "fix": "Optional: convert to Markdown."})
    return {"present": docs_present, "links": links, "findings": findings}


def audit_presentation(root: Path) -> dict:
    from branding_scan import scan_branding
    from capture import probe, shot_list
    branding = scan_branding(root)
    shots = probe(root)
    assets_dir = root / "docs" / "assets"
    images = []
    for pattern in ("**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif", "**/*.webp"):
        for p in root.glob(pattern):
            if any(part in p.parts for part in ("node_modules", ".git", "vendor")):
                continue
            images.append({"path": rel(root, p), "bytes": p.stat().st_size})
    findings = list(branding["findings"])
    if not images:
        findings.append({"checklist": "presentation", "id": "presentation.no-images",
                         "severity": "medium",
                         "title": "No images in the repository",
                         "detail": "A README without a single screenshot asks readers to take "
                                   "the project on faith.",
                         "evidence": [], "fix": "Capture at least one real screenshot "
                                                "(scripts/capture.py can help)."})
    return {"branding": branding, "capture": shots, "shot_list": shot_list(shots),
            "images": images[:30], "assets_dir_exists": assets_dir.exists(),
            "findings": findings}


def build(root: Path, history: bool = False, remote_links: bool = False) -> dict:
    started = datetime.datetime.now(datetime.timezone.utc)
    project = audit_project(root)
    docs = audit_docs(root, remote_links)
    pres = audit_presentation(root)

    from secret_scan import scan_secrets
    security = scan_secrets(root, history=history)

    from quality_gate import run_gate
    gate = run_gate(root)

    findings = (project["findings"] + security["findings"] + docs["findings"] +
                pres["findings"])
    counts = summarize([type("F", (), f)() for f in findings]) if False else {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    info = project["scan"]
    limitations = []
    if not info["git"]["is_repo"]:
        limitations.append("Not a git repository yet; history analysis was skipped.")
    if not history:
        limitations.append("Git history was not scanned for secrets (pass --history).")
    if not remote_links:
        limitations.append("Remote links were not fetched (pass --remote-links).")
    if project["unverified_commands"]:
        limitations.append(
            f"{len(project['unverified_commands'])} build/test command(s) reference tools that "
            "are not installed here, so they were not executed.")
    if not info["tools_available"].get("gh"):
        limitations.append("gh CLI is not installed; GitHub operations are unavailable.")
    if not pres["capture"]["playwright_browser"]:
        limitations.append("Playwright browser binaries are not installed, so web screenshots "
                           "cannot be captured automatically.")

    return {
        "gitup_version": "0.1.0",
        "run_at": started.isoformat(timespec="seconds"),
        "project_root": str(root),
        "project": {k: info["project"][k] for k in
                    ("name", "app_type", "version", "monorepo", "private")},
        "languages": info["languages"],
        "commands": info["commands"],
        "package_manager": info["package_manager"],
        "git": info["git"],
        "documentation": {"present": docs["present"],
                          "links_checked": docs["links"]["links_checked"]},
        "presentation": {"images": len(pres["images"]),
                         "branding_findings": pres["branding"]["branding_found"],
                         "recommended_capture": pres["capture"]["recommended"],
                         "shot_list": pres["shot_list"]},
        "security": {"verdict": security["verdict"], "summary": security["summary"],
                     "publishable_secret_count": security["publishable_secret_count"]},
        "gate": {"verdict": gate["verdict"], "passes": gate["required_passes"],
                 "gates": gate["gates"]},
        "findings_summary": counts,
        "findings": findings,
        "limitations": limitations,
        "next_actions": gate["next_actions"] + [
            f"Install {u['missing_tool']} to verify: {u['command']}"
            for u in project["unverified_commands"][:3]],
        "note": "This stage is read-only. Nothing in the project was modified.",
    }


def main(argv=None):
    ap = parser(description="gitup read-only preparation stage")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--remote-links", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    out = build(root, args.history, args.remote_links)
    emit(out, args.out or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())