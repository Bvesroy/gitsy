#!/usr/bin/env python3
"""gitup ci_plan.py - propose (and optionally write) GitHub Actions workflows.

A workflow that fails on its first run is worse than no workflow: it advertises
a broken project. So this script only generates a workflow it can justify from
the project's own files, and marks anything unverified as such.

Sub-commands:
  plan    what CI would be useful here, what it would run, and why
  write   render the workflows into .github/workflows/ (never overwrites)

Both are side-effect free unless `write` is asked for, and `write` refuses to
replace an existing file.

Usage:
  python3 ci_plan.py plan  --project . [--out ci.json]
  python3 ci_plan.py write --project . [--force-detected] [--dry-run]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
from pathlib import Path

from gitup_common import die, emit, rel, run, which, parser

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "workflows"

# runtime name -> (setup action, setup args, matrix default)
SETUPS = {
    "python": ("actions/setup-python@v5",
               '        python-version: ["{{VERSIONS}}"]',
               '["3.11", "3.12", "3.13"]', "3.12"),
    "node": ("actions/setup-node@v4",
             '        node-version: ["{{VERSIONS}}"]\n        cache: "{{PM}}"',
             '["20", "22"]', "22"),
    "rust": ("dtolnay/rust-toolchain@stable", '        toolchain: stable', '["stable"]', "stable"),
    "go": ("actions/setup-go@v5",
           '        go-version: ["{{VERSIONS}}"]', '["1.22", "1.23"]', "1.23"),
    "swift": ("swift-actions/setup-swift@v2", '        swift-version: "6.0"', '["6.0"]', "6.0"),
    "java": ("actions/setup-java@v4",
             '        distribution: "temurin"\n        java-version: ["{{VERSIONS}}"]',
             '["21"]', "21"),
    "dotnet": ("actions/setup-dotnet@v4", '        dotnet-version: "8.0.x"', '["8.0.x"]', "8.0"),
}


def detect_stack(root: Path) -> dict:
    from project_scan import scan
    info = scan(root)
    langs = [l["name"] for l in info["languages"]]
    cmds = info["commands"]
    pm = info["package_manager"]
    runtime = ""
    for candidate in ("python", "node", "rust", "go", "swift", "java", "dotnet"):
        marker = {"python": ["pyproject.toml", "setup.py", "requirements.txt"],
                  "node": ["package.json"],
                  "rust": ["Cargo.toml"],
                  "go": ["go.mod"],
                  "swift": ["Package.swift"],
                  "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
                  "dotnet": ["global.json", "Directory.Build.props"]}[candidate]
        if any((root / m).exists() for m in marker):
            runtime = candidate
            break
    if not runtime and "Python" in langs:
        runtime = "python"
    first = lambda key: (cmds[key][0]["cmd"] if cmds.get(key) else "")  # noqa: E731
    return {
        "runtime": runtime,
        "languages": langs,
        "package_manager": pm,
        "app_type": info["project"]["app_type"],
        "private": info["project"]["private"],
        "install": first("install"),
        "build": first("build"),
        "test": first("test"),
        "lint": first("lint"),
        "package": first("package"),
        "has_workflows": bool(info["ci"]["workflows"]),
        "existing_workflows": info["ci"]["workflows"],
        "version": info["project"]["version"],
        "default_branch": (info["git"].get("branch") or "main") if info["git"].get("is_repo") else "main",
        "platforms": _platforms(info),
    }


def _platforms(info: dict) -> list[str]:
    app_type = info["project"]["app_type"]
    if "macos" in app_type:
        return ["macos-latest"]
    if "desktop" in app_type:
        return ["macos-latest", "ubuntu-latest", "windows-latest"]
    if "mobile" in app_type:
        return ["ubuntu-latest"]
    return ["ubuntu-latest", "macos-latest", "windows-latest"]


def plan(root: Path) -> dict:
    stack = detect_stack(root)
    workflows = []
    notes = []

    if not stack["test"]:
        notes.append("No test command was detected, so no test workflow is proposed. "
                     "Add a test runner first; a workflow that runs nothing is noise.")
    else:
        workflows.append({
            "file": "test.yml",
            "purpose": "Run the project's own tests on every push and pull request",
            "runs": stack["test"],
            "verified": False,
            "matrix": {"os": stack["platforms"] if len(stack["platforms"]) <= 3 else stack["platforms"][:2],
                       "runtime": [SETUPS[stack["runtime"]][2] if stack["runtime"] in SETUPS else '"latest"']},
            "why": "A green test badge only means something when it reflects a real suite.",
        })
    if stack["package"] or stack["build"]:
        workflows.append({
            "file": "release.yml",
            "purpose": "Build artifacts on a v* tag and publish them with checksums",
            "runs": stack["build"] or stack["package"],
            "verified": False,
            "why": "Release automation keeps tags and downloadable assets in sync.",
        })
    workflows.append({
        "file": "security.yml",
        "purpose": "Scan every push and pull request for committed credentials",
        "runs": "gitleaks-action",
        "verified": False,
        "why": "Cheap, fast, and catches the one mistake that cannot be undone.",
    })
    if stack["private"] and any(w["file"] == "release.yml" for w in workflows):
        notes.append("package.json is private, so npm publishing is not proposed; "
                     "the release workflow only attaches build artifacts.")
    if stack["has_workflows"]:
        notes.append(f"Workflows already exist ({', '.join(stack['existing_workflows'][:4])}); "
                     "gitup proposes additions instead of rewriting them.")
    return {
        "project": str(root),
        "stack": stack,
        "proposed": workflows,
        "notes": notes,
        "writes": "nothing yet; run `ci_plan.py write` to render these files",
    }


def render_test(stack: dict) -> dict:
    runtime = stack["runtime"]
    if runtime not in SETUPS:
        return {"ok": False, "why": f"no workflow template for runtime '{runtime}'"}
    action, args_template, _matrix, default_version = SETUPS[runtime]
    matrix_os = stack["platforms"][:3]
    values = {
        "DEFAULT_BRANCH": stack["default_branch"],
        "MATRIX_OS": json.dumps(matrix_os),
        "MATRIX_RUNTIME": json.dumps([default_version]),
        "SETUP_ACTION": action,
        "SETUP_ARGS": args_template.replace("{{VERSIONS}}", default_version)
                                   .replace("{{PM}}", stack["package_manager"] or "npm"),
        "INSTALL_CMD": stack["install"] or "echo 'no install step detected'",
        "BUILD_CMD": stack["build"] or "echo 'no build step detected'",
        "TEST_CMD": stack["test"] or "echo 'no test step detected'",
        "LINT_STEP": ("      - name: Lint\n        run: " + stack["lint"]) if stack["lint"] else "",
    }
    return {"ok": True, "values": values, "template": TEMPLATES / "test.yml",
            "blocked_by": [k for k, v in values.items() if not str(v).strip()]}


def render_release(stack: dict) -> dict:
    runtime = stack["runtime"]
    action, args_template, _m, default_version = SETUPS.get(
        runtime, ("actions/setup-python@v5", '        python-version: "{{VERSIONS}}"', [], "3.12"))
    artifact = {"python": "dist/*", "node": "*.tgz", "rust": "target/release/*",
                "go": "bin/*", "swift": "*.zip", "java": "build/libs/*.jar",
                "dotnet": "**/*.nupkg"}.get(runtime, "*")
    values = {
        "RELEASE_OS": "ubuntu-latest",
        "SETUP_ACTION": action,
        "SETUP_ARGS": args_template.replace("{{VERSIONS}}", default_version)
                                   .replace("{{PM}}", stack["package_manager"] or "npm"),
        "INSTALL_CMD": stack["install"] or "echo 'no install step detected'",
        "BUILD_CMD": stack["build"] or stack["package"] or "echo 'no build step detected'",
        "TEST_CMD": stack["test"] or "echo 'no test step detected'",
        "PACKAGE_STEP": ("      - name: Package\n        run: " + stack["package"]) if stack["package"] else "",
        "ARTIFACT_GLOB": artifact,
    }
    return {"ok": True, "values": values, "template": TEMPLATES / "release.yml"}


def render_security(stack: dict) -> dict:
    dependency_job = ""
    if stack["runtime"] == "node":
        dependency_job = ("\n  audit:\n    name: Dependency audit\n    runs-on: ubuntu-latest\n"
                          "    steps:\n      - uses: actions/checkout@v4\n"
                          "      - uses: actions/setup-node@v4\n        with:\n"
                          f"          node-version: \"22\"\n          cache: \"{stack['package_manager'] or 'npm'}\"\n"
                          "      - run: npm audit --audit-level=high || true\n")
    elif stack["runtime"] == "python":
        dependency_job = ("\n  audit:\n    name: Dependency audit\n    runs-on: ubuntu-latest\n"
                          "    steps:\n      - uses: actions/checkout@v4\n"
                          "      - uses: actions/setup-python@v5\n        with:\n"
                          "          python-version: \"3.12\"\n"
                          "      - run: pip install pip-audit && pip-audit || true\n")
    return {"ok": True, "values": {"DEFAULT_BRANCH": stack["default_branch"],
                                   "DEPENDENCY_JOB": dependency_job},
            "template": TEMPLATES / "security.yml"}


def write(root: Path, force: bool = False, dry_run: bool = False) -> dict:
    stack = detect_stack(root)
    outdir = root / ".github" / "workflows"
    results = []
    for name, renderer in (("test.yml", render_test), ("release.yml", render_release),
                           ("security.yml", render_security)):
        if name == "test.yml" and not stack["test"]:
            results.append({"file": name, "written": False,
                            "why": "no test command detected"})
            continue
        if name == "release.yml" and not (stack["build"] or stack["package"]):
            results.append({"file": name, "written": False,
                            "why": "no build/package command detected"})
            continue
        rendered = renderer(stack)
        if not rendered.get("ok"):
            results.append({"file": name, "written": False, "why": rendered.get("why")})
            continue
        target = outdir / name
        if target.exists() and not force:
            results.append({"file": name, "written": False,
                            "why": "already exists; gitup does not overwrite workflows",
                            "existing": True})
            continue
        try:
            text = rendered["template"].read_text(encoding="utf-8")
        except OSError as exc:
            results.append({"file": name, "written": False, "why": f"template missing: {exc}"})
            continue
        for key, value in rendered["values"].items():
            text = text.replace("{{" + key + "}}", str(value))
        # Only gitup's own UPPER_CASE placeholders are errors. GitHub's own
        # ${{ ... }} expressions are syntax and must survive untouched.
        leftover = sorted(set(re.findall(r"\{\{([A-Z][A-Z_]+)\}\}", text)))
        if leftover:
            results.append({"file": name, "written": False,
                            "why": f"unfilled template keys: {leftover}"})
            continue
        if not dry_run:
            outdir.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        results.append({"file": name, "written": True, "dry_run": dry_run,
                        "path": rel(root, target), "bytes": len(text)})
    return {"project": str(root), "stack_runtime": stack["runtime"],
            "written": [r for r in results if r.get("written")],
            "skipped": [r for r in results if not r.get("written")],
            "verified": False,
            "note": "Workflows are untested until the first Actions run. gitup never "
                    "claims a CI badge is green before that run happens."}


def main(argv=None):
    ap = parser(description="plan or write GitHub Actions workflows")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "write"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True)
        p.add_argument("--out", default="")
        if name == "write":
            p.add_argument("--force", action="store_true")
            p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    out = plan(root) if args.cmd == "plan" else write(root, args.force, args.dry_run)
    emit(out, args.out or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())