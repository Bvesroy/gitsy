#!/usr/bin/env python3
"""
GITU Phase A & Phase B: Project Discovery and Deep Project Audit
Inspects a local software project directory, detects languages, frameworks,
application type, entry points, dependencies, build/test commands, documentation links,
accidental artifacts, and monorepo subprojects.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    "target", ".next", ".nuxt", ".svelte-kit", "vendor", "Pods",
    "DerivedData", ".gradle", ".idea", ".vscode"
}

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".zsh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
}

OS_JUNK_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100", ".Trashes"
}

TEMP_EXTS = {".pyc", ".pyo", ".swp", ".swo", ".bak", ".tmp", ".orig", ".log"}


def run_cmd(cmd, cwd, timeout=15):
    try:
        res = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return False, "", str(exc)


def _python_test_roots(root: Path, all_files):
    """Directories that hold Python test modules, relative to the project root."""
    roots = []
    for rel in all_files:
        if not rel.endswith(".py"):
            continue
        name = Path(rel).name
        parent = str(Path(rel).parent)
        if name.startswith("test_") or name.endswith("_test.py"):
            if parent not in roots:
                roots.append(parent if parent != "." else "")
    return roots


def run_python_tests(root: Path, all_files):
    """Run the Python test suite, handling non-package test directories.

    `python -m unittest discover` from the project root only descends into a
    directory when it is an importable package (i.e. has __init__.py), so the
    very common `tests/test_x.py` layout reports zero tests and a false
    failure. Try the plain command first, then discover each test directory
    explicitly with the project root as top-level dir.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    attempts = [f"{sys.executable} -m unittest discover"]
    extra = [
        f"{sys.executable} -m unittest discover -s {d or '.'} -t {d or '.'}"
        for d in _python_test_roots(root, all_files)
    ]
    attempts.extend(dict.fromkeys(extra))

    last_out, last_err, last_cmd = "", "", attempts[0]
    for cmd in attempts:
        try:
            res = subprocess.run(
                cmd.split(), cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=30, env=env
            )
        except Exception as exc:
            last_out, last_err, last_cmd = "", str(exc), cmd
            continue
        out, err = res.stdout.strip(), res.stderr.strip()
        ran_something = "Ran 0 tests" not in out
        if res.returncode == 0 and ran_something:
            return True, cmd, out, err
        last_out, last_err, last_cmd = out, err, cmd

    return False, last_cmd, last_out, last_err


def parse_package_json(pkg_path: Path):
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"error": f"Malformed package.json: {exc}"}

    deps = list((data.get("dependencies") or {}).keys())
    dev_deps = list((data.get("devDependencies") or {}).keys())
    scripts = data.get("scripts") or {}
    return {
        "name": data.get("name"),
        "version": data.get("version"),
        "description": data.get("description"),
        "license": data.get("license"),
        "main": data.get("main") or data.get("module"),
        "bin": data.get("bin"),
        "workspaces": data.get("workspaces"),
        "dependencies": deps,
        "dev_dependencies": dev_deps,
        "scripts": scripts,
    }


def parse_pyproject_toml(toml_path: Path):
    text = toml_path.read_text(encoding="utf-8", errors="replace")
    info = {}
    for key in ("name", "version", "description", "readme", "requires-python"):
        m = re.search(rf'^\s*{re.escape(key)}\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if m:
            info[key] = m.group(1)
    deps_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if deps_match:
        info["dependencies"] = re.findall(r'["\']([^"\']+)["\']', deps_match.group(1))
    return info


def parse_cargo_toml(cargo_path: Path):
    text = cargo_path.read_text(encoding="utf-8", errors="replace")
    info = {}
    for key in ("name", "version", "edition", "description", "license"):
        m = re.search(rf'^\s*{re.escape(key)}\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if m:
            info[key] = m.group(1)
    if "[workspace]" in text:
        info["is_workspace"] = True
    return info


def parse_swift_package(swift_path: Path):
    text = swift_path.read_text(encoding="utf-8", errors="replace")
    info = {"manifest": "Package.swift"}
    name_m = re.search(r'name:\s*"([^"]+)"', text)
    if name_m:
        info["name"] = name_m.group(1)
    platforms = re.findall(r'\.(macOS|iOS|tvOS|watchOS|visionOS)\([^)]*\)', text)
    if platforms:
        info["platforms"] = sorted(set(platforms))
    return info


def inspect_git_state(root: Path):
    if not (root / ".git").exists():
        ok, _, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=root)
        if not ok:
            return {"initialized": False}

    _, branch, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)
    _, remotes_raw, _ = run_cmd(["git", "remote", "-v"], cwd=root)
    _, tags_raw, _ = run_cmd(["git", "tag", "--list"], cwd=root)
    _, status_raw, _ = run_cmd(["git", "status", "--porcelain"], cwd=root)
    _, commits_raw, _ = run_cmd(["git", "log", "-n", "10", "--oneline"], cwd=root)

    remotes = {}
    for line in remotes_raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]

    return {
        "initialized": True,
        "current_branch": branch or "HEAD",
        "remotes": remotes,
        "tags": [t for t in tags_raw.splitlines() if t.strip()],
        "dirty_files_count": len(status_raw.splitlines()),
        "recent_commits": commits_raw.splitlines(),
    }


def check_markdown_links(md_path: Path, root: Path):
    broken = []
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return broken

    text_no_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for match in re.finditer(r"!?\[([^\]]*)\]\(([^)]+)\)", text_no_code):
        label, target = match.group(1), match.group(2).strip()
        if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
            continue
        clean_target = target.split("#")[0].split("?")[0]
        if not clean_target:
            continue
        resolved = (md_path.parent / clean_target).resolve()
        resolved_root = (root / clean_target.lstrip("/")).resolve()
        if not resolved.exists() and not resolved_root.exists():
            broken.append({"file": str(md_path.relative_to(root)), "label": label, "target": target})
    return broken


def verify_python_syntax_and_imports(py_files, root: Path):
    syntax_errors = []
    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            compile(source, str(py_file), "exec")
        except SyntaxError as exc:
            syntax_errors.append({
                "file": str(py_file.relative_to(root)),
                "line": exc.lineno,
                "error": exc.msg,
            })
    return syntax_errors


def infer_application_type(languages, manifests, file_paths):
    types = set()
    if "Swift" in languages or "Objective-C" in languages or any(p.endswith(".xcodeproj") or p == "Package.swift" for p in file_paths):
        types.add("macOS / Apple Platform Application")
    if "package.json" in manifests:
        pkg = manifests["package.json"]
        deps = set((pkg.get("dependencies") or []) + (pkg.get("dev_dependencies") or []))
        if {"react", "vue", "svelte", "next", "nuxt", "vite", "astro"} & deps:
            types.add("Web Application")
        if "electron" in deps or "@tauri-apps/api" in deps:
            types.add("Desktop Application")
        if pkg.get("bin"):
            types.add("CLI Tool")
    if any(p.startswith(("bin/", "cli/")) or p in ("cli.py", "__main__.py", "main.py", "main.go", "src/main.rs") for p in file_paths):
        types.add("CLI / Executable Application")
    if any(p.startswith("src/") or p.endswith(("__init__.py", "lib.rs", "index.ts", "index.js")) for p in file_paths):
        types.add("Library / SDK")
    if not types:
        if "HTML" in languages:
            types.add("Static Web Application")
        else:
            types.add("Software Project")
    return sorted(types)


def discover_project(root: Path, run_tests: bool = False):
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {root}")

    lang_counts = {}
    all_files = []
    py_files = []
    md_files = []
    assets = []
    junk_files = []
    empty_dirs = []
    nested_projects = []

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if not dirnames and not filenames and rel_dir != Path(".") and ".git" not in rel_dir.parts:
            empty_dirs.append(str(rel_dir))

        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        if rel_dir != Path("."):
            if any(f in filenames for f in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Package.swift")):
                nested_projects.append(str(rel_dir))

        for fname in filenames:
            fpath = Path(dirpath) / fname
            rel_path = str(fpath.relative_to(root))
            all_files.append(rel_path)

            if fname in OS_JUNK_FILES or fpath.suffix.lower() in TEMP_EXTS:
                junk_files.append(rel_path)

            ext = fpath.suffix.lower()
            if ext in LANGUAGE_EXTENSIONS:
                lang = LANGUAGE_EXTENSIONS[ext]
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
            if ext == ".py":
                py_files.append(fpath)
            elif ext in (".md", ".markdown"):
                md_files.append(fpath)
            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".icns", ".ico"):
                assets.append(rel_path)

    manifests = {}
    pkg_managers = []
    build_commands = []
    test_commands = []
    lint_commands = []

    if (root / "package.json").exists():
        pkg_info = parse_package_json(root / "package.json")
        manifests["package.json"] = pkg_info
        if (root / "pnpm-lock.yaml").exists():
            pkg_managers.append("pnpm")
            runner = "pnpm"
        elif (root / "yarn.lock").exists():
            pkg_managers.append("yarn")
            runner = "yarn"
        elif (root / "bun.lockb").exists():
            pkg_managers.append("bun")
            runner = "bun"
        else:
            pkg_managers.append("npm")
            runner = "npm run"
        scripts = pkg_info.get("scripts") or {}
        if "build" in scripts:
            build_commands.append(f"{runner} build")
        if "test" in scripts:
            test_commands.append("npm test" if runner == "npm run" else f"{runner} test")
        if "lint" in scripts:
            lint_commands.append(f"{runner} lint")

    if (root / "pyproject.toml").exists():
        manifests["pyproject.toml"] = parse_pyproject_toml(root / "pyproject.toml")
        pkg_managers.append("pip / pyproject")
        test_commands.append("pytest")
    elif (root / "requirements.txt").exists():
        deps = [
            line.strip()
            for line in (root / "requirements.txt").read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        manifests["requirements.txt"] = {"dependencies": deps}
        pkg_managers.append("pip")
        if any("pytest" in d.lower() for d in deps) or any(p.startswith("tests/") or p.startswith("test_") for p in all_files):
            test_commands.append("pytest")

    if (root / "Cargo.toml").exists():
        manifests["Cargo.toml"] = parse_cargo_toml(root / "Cargo.toml")
        pkg_managers.append("cargo")
        build_commands.append("cargo build")
        test_commands.append("cargo test")
        lint_commands.append("cargo clippy")

    if (root / "go.mod").exists():
        manifests["go.mod"] = {"present": True}
        pkg_managers.append("go modules")
        build_commands.append("go build ./...")
        test_commands.append("go test ./...")

    if (root / "Package.swift").exists():
        manifests["Package.swift"] = parse_swift_package(root / "Package.swift")
        pkg_managers.append("Swift Package Manager")
        build_commands.append("swift build")
        test_commands.append("swift test")

    if (root / "Makefile").exists():
        manifests["Makefile"] = {"present": True}
        build_commands.append("make")

    candidate_entries = [
        "src/main.py", "main.py", "app.py", "cli.py", "src/index.ts", "src/index.js",
        "index.ts", "index.js", "src/main.rs", "src/lib.rs", "main.go", "Sources/main.swift",
        "SKILL.md"
    ]
    entry_points = [e for e in candidate_entries if e in all_files]
    if not entry_points:
        entry_points = [f for f in all_files if Path(f).name in ("main.py", "index.js", "index.ts", "main.rs", "main.go", "App.swift")][:10]

    project_name = root.name
    version = None
    description = None
    for m_name in ("package.json", "pyproject.toml", "Cargo.toml", "Package.swift"):
        if m_name in manifests and isinstance(manifests[m_name], dict):
            m_data = manifests[m_name]
            project_name = m_data.get("name") or project_name
            version = version or m_data.get("version")
            description = description or m_data.get("description")

    readme_files = [f for f in all_files if f.lower() in ("readme.md", "readme.rst", "readme.txt")]
    readme_audit = {"exists": bool(readme_files), "path": readme_files[0] if readme_files else None, "issues": []}
    if readme_files:
        r_text = (root / readme_files[0]).read_text(encoding="utf-8", errors="replace")
        if len(r_text.strip()) < 120:
            readme_audit["issues"].append("README is stub-length (<120 chars) and lacks substantive documentation.")
        for section in ("install", "usage"):
            if section not in r_text.lower():
                readme_audit["issues"].append(f"README does not appear to cover '{section}' instructions.")
    else:
        readme_audit["issues"].append("Missing README.md at repository root.")

    broken_links = []
    for md in md_files:
        broken_links.extend(check_markdown_links(md, root))

    py_syntax_errors = verify_python_syntax_and_imports(py_files, root) if py_files else []
    license_files = [f for f in all_files if Path(f).name.upper().startswith(("LICENSE", "COPYING"))]

    test_execution = {"executed": False, "command": None, "passed": None, "output": None}
    if run_tests and py_files and any(p.startswith("tests/") or Path(p).name.startswith("test_") for p in all_files):
        ok, cmd_used, out, err = run_python_tests(root, all_files)
        test_execution = {
            "executed": True,
            "command": cmd_used,
            "passed": ok,
            "output": (out + "\n" + err).strip()[:1000],
        }

    return {
        "project_name": project_name,
        "project_root": str(root),
        "inferred_version": version or "0.1.0",
        "inferred_description": description,
        "application_types": infer_application_type(lang_counts, manifests, all_files),
        "is_monorepo": bool(nested_projects),
        "nested_projects": nested_projects,
        "languages": dict(sorted(lang_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "package_managers": pkg_managers,
        "manifests": manifests,
        "entry_points": entry_points,
        "commands": {
            "build": build_commands,
            "test": test_commands,
            "lint": lint_commands,
        },
        "git": inspect_git_state(root),
        "documentation": {
            "readme": readme_audit,
            "markdown_files": [str(m.relative_to(root)) for m in md_files],
            "broken_relative_links": broken_links,
            "license_files": license_files,
        },
        "assets": assets,
        "audit_findings": {
            "python_syntax_errors": py_syntax_errors,
            "os_and_temp_junk_files": junk_files,
            "empty_directories": empty_dirs,
            "missing_gitignore": ".gitignore" not in all_files,
            "missing_license": not bool(license_files),
        },
        "test_execution": test_execution,
        "total_files_scanned": len(all_files),
    }


def main():
    parser = argparse.ArgumentParser(description="GITU Phase A & B: Project Discovery and Audit")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--run-tests", action="store_true", help="Run detected Python unittest suite")
    parser.add_argument("--output", help="Write JSON report to file path")
    args = parser.parse_args()

    report = discover_project(Path(args.project_path), run_tests=args.run_tests)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
