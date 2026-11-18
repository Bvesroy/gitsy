#!/usr/bin/env python3
"""gitup project_scan.py - Phase A: discover what a project actually is.

Reads a directory and reports languages, stack, app type, entry points, package
managers, build/test/lint commands, existing git state, documentation, assets,
versions and monorepo layout.

Everything reported here comes from files on disk. Nothing is invented: a field
stays null/empty when the project does not provide the evidence for it.

Usage:
  python3 project_scan.py --project ~/Developer/MyProject [--out scan.json]
                          [--deep] [--max-files N]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import plistlib
import re
import sys
from collections import Counter
from pathlib import Path

from gitup_common import (
    dirty_paths,
    emit,
    git,
    human_size,
    is_git_repo,
    looks_binary,
    default_branch,
    parser,
    read_text,
    rel,
    run,
    walk,
    which,
)

# ---------------------------------------------------------------- manifests ---
MANIFESTS = {
    "package.json": "node",
    "pnpm-workspace.yaml": "node",
    "yarn.lock": "node",
    "package-lock.json": "node",
    "pnpm-lock.yaml": "node",
    "bun.lockb": "node",
    "deno.json": "deno",
    "deno.jsonc": "deno",
    "tsconfig.json": "typescript",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "requirements-dev.txt": "python",
    "Pipfile": "python",
    "tox.ini": "python",
    "poetry.lock": "python",
    "uv.lock": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "go.sum": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "settings.gradle": "java",
    "settings.gradle.kts": "kotlin",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Package.swift": "swift",
    "project.pbxproj": "swift",
    "CMakeLists.txt": "cmake",
    "meson.build": "meson",
    "Makefile": "make",
    "Justfile": "just",
    "mix.exs": "elixir",
    "pubspec.yaml": "dart",
    "build.zig": "zig",
    "stack.yaml": "haskell",
    "cabal.project": "haskell",
    "dune-project": "ocaml",
    "shard.yml": "crystal",
    "Project.toml": "julia",
    "DESCRIPTION": "r",
    "flake.nix": "nix",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "compose.yaml": "docker",
    "Dockerfile": "docker",
    "Chart.yaml": "helm",
    "action.yml": "actions",
    "action.yaml": "actions",
    "tauri.conf.json": "tauri",
    "electron-builder.yml": "electron",
    "forge.config.js": "electron",
    "wails.json": "wails",
    "Info.plist": "macos",
    ".python-version": "python",
    "rust-toolchain.toml": "rust",
}

LANG_BY_EXT = {
    ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C++",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cxx": "C++",
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".fs": "F#", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".ml": "OCaml",
    ".clj": "Clojure", ".scala": "Scala", ".dart": "Dart", ".zig": "Zig",
    ".lua": "Lua", ".pl": "Perl", ".r": "R", ".jl": "Julia", ".nim": "Nim",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "SCSS",
    ".less": "LESS", ".sol": "Solidity", ".proto": "Protobuf", ".graphql": "GraphQL",
    ".tf": "HCL", ".nix": "Nix", ".groovy": "Groovy", ".v": "V", ".cr": "Crystal",
}

APP_TYPE_HINTS = [
    # (predicate on names/deps, app type)
    ("tauri", "desktop"),
    ("electron", "desktop"),
    ("wails", "desktop"),
    ("expo", "mobile"),
    ("react-native", "mobile"),
    ("flutter", "mobile"),
    ("android", "mobile"),
    ("ios", "mobile"),
    ("vscode", "extension"),
    ("obsidian", "extension"),
    ("chrome-extension", "browser-extension"),
]

DOC_NAMES = ["README.md", "README.rst", "README.txt", "README", "CONTRIBUTING.md",
             "CHANGELOG.md", "CHANGELOG", "CHANGES.md", "HISTORY.md", "LICENSE",
             "LICENSE.md", "LICENSE.txt", "COPYING", "SECURITY.md", "CODE_OF_CONDUCT.md",
             "SUPPORT.md", "CITATION.cff", "AUTHORS", "NOTICE", "AGENTS.md",
             "CODEOWNERS", ".all-contributorsrc"]

ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".mov",
              ".webm", ".icns", ".ico", ".appiconset"}

VERSION_FILES = ["package.json", "Cargo.toml", "pyproject.toml", "setup.py",
                 "setup.cfg", "VERSION", "version.txt", "gradle.properties",
                 "pubspec.yaml", "Project.toml", "*.gemspec", "mix.exs",
                 "CMakeLists.txt", "tauri.conf.json", "Info.plist", "Package.swift"]


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def toml_version(path: Path) -> str:
    text = read_text(path)
    # only the first (project/package) version wins, not dependency versions
    for pattern in (r'(?m)^\s*version\s*=\s*"([^"]+)"',
                    r'(?m)^\s*version\s*=\s*\'([^\']+)\''):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def node_version(pkg: dict) -> str:
    v = pkg.get("version")
    if isinstance(v, str):
        return v
    return ""


def read_makefile_targets(path: Path) -> list[str]:
    text = read_text(path)
    targets = []
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+):(?!=)", line)
        if m and not m.group(1).startswith("."):
            targets.append(m.group(1))
    return sorted(set(targets))


def classify_app_type(ctx: dict) -> str:
    names = set(ctx["manifest_names"])
    deps = set(ctx["dependencies"])
    exts = set(ctx["extensions"])
    blob = " ".join(sorted(deps | names)).lower()

    if {"tauri.conf.json"} & names:
        return "desktop (Tauri)"
    if {"Info.plist"} & names and {"project.pbxproj", "Package.swift"} & names:
        return "macos (Swift)"
    if {"electron-builder.yml", "forge.config.js"} & names or "electron" in deps:
        return "desktop (Electron)"
    if "expo" in deps or "react-native" in deps:
        return "mobile (React Native)"
    if {"pubspec.yaml"} & names and "flutter" in read_text(Path(ctx["root"]) / "pubspec.yaml").lower():
        return "mobile (Flutter)"
    if {"AndroidManifest.xml"} & names or {"build.gradle", "build.gradle.kts"} & names and {"android"} <= exts | names:
        return "mobile (Android)"
    if "next" in deps or "nuxt" in deps or "astro" in deps or "vite" in deps or "svelte" in deps:
        if ".tsx" in exts or ".jsx" in exts or ".vue" in exts or ".svelte" in exts:
            return "web app"
    if {"package.json"} & names and ({"react", "vue", "svelte", "solid-js"} & deps):
        return "web app" if ctx.get("has_public_html") else "web library/app"
    if {"Package.swift"} & names:
        if ctx.get("has_executable_target"):
            return "cli (Swift)"
        return "library (Swift)"
    if {"Cargo.toml"} & names:
        return "cli (Rust)" if ctx.get("rust_binary") else "library (Rust)"
    if {"pyproject.toml", "setup.py", "setup.cfg"} & names:
        return "cli (Python)" if ctx.get("py_console_scripts") else "library (Python)"
    if "Python" in ctx["languages"]:
        # A bare Python project with no packaging metadata is either a script
        # collection or a small service; --help/argparse/http.server are the
        # honest tells we can read from source.
        hints = ctx.get("py_source_hints", set())
        if "http.server" in hints or "fastapi" in hints or "flask" in hints or "uvicorn" in hints:
            return "service (Python)"
        if "argparse" in hints or "__main__" in hints:
            return "cli (Python)"
        return "python scripts"
    if {"go.mod"} & names:
        return "cli (Go)" if ctx.get("go_main") else "library (Go)"
    if "docker-compose.yml" in names or "compose.yaml" in names:
        return "service"
    if ".swift" in exts and not {"Package.swift"} & names:
        return "macos (Swift)"
    if "Makefile" in names and ("C" in ctx["languages"] or "C++" in ctx["languages"]):
        return "native"
    return "unknown"


def detect_commands(root: Path, ctx: dict) -> dict:
    cmds = {"install": [], "build": [], "test": [], "lint": [], "format": [], "run": [], "package": [], "release": []}
    names = set(ctx["manifest_names"])
    pkg = load_json(root / "package.json") if "package.json" in names else {}
    scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}

    if names & {"pnpm-lock.yaml"}:
        pm = "pnpm"
    elif names & {"yarn.lock"}:
        pm = "yarn"
    elif names & {"bun.lockb"}:
        pm = "bun"
    else:
        pm = "npm"

    if scripts:
        cmds["install"].append({"cmd": f"{pm} install", "source": "package.json", "verified": False})
        for key in ("build", "test", "lint", "format", "dev", "start"):
            if key in scripts:
                target = "run" if key in ("dev", "start") else key
                cmds[target].append({"cmd": f"{pm} run {key}", "raw": scripts[key],
                                     "source": "package.json", "verified": False})
        if "prepublishOnly" in scripts or "release" in scripts:
            cmds["release"].append({"cmd": f"{pm} run {'release' if 'release' in scripts else 'prepublishOnly'}",
                                    "source": "package.json", "verified": False})
        if (root / "package.json").exists():
            data = load_json(root / "package.json")
            if data.get("private") is not True:
                cmds["package"].append({"cmd": f"{pm} pack", "source": "package.json", "verified": False})
    if "Cargo.toml" in names:
        cmds["build"].append({"cmd": "cargo build --release", "source": "Cargo.toml", "verified": False})
        cmds["test"].append({"cmd": "cargo test", "source": "Cargo.toml", "verified": False})
        cmds["lint"].append({"cmd": "cargo clippy --all-targets -- -D warnings", "source": "Cargo.toml", "verified": False})
        cmds["format"].append({"cmd": "cargo fmt --check", "source": "Cargo.toml", "verified": False})
        cmds["package"].append({"cmd": "cargo package --allow-dirty", "source": "Cargo.toml", "verified": False})
    if "go.mod" in names:
        cmds["build"].append({"cmd": "go build ./...", "source": "go.mod", "verified": False})
        cmds["test"].append({"cmd": "go test ./...", "source": "go.mod", "verified": False})
        if which("golangci-lint"):
            cmds["lint"].append({"cmd": "golangci-lint run", "source": "go.mod", "verified": False})
        cmds["format"].append({"cmd": "gofmt -l .", "source": "go.mod", "verified": False})
    if names & {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"}:
        has_uv = (root / "uv.lock").exists()
        has_poetry = (root / "poetry.lock").exists()
        if has_uv:
            cmds["install"].append({"cmd": "uv sync", "source": "uv.lock", "verified": False})
            cmds["test"].append({"cmd": "uv run pytest", "source": "uv.lock", "verified": False})
        elif has_poetry:
            cmds["install"].append({"cmd": "poetry install", "source": "poetry.lock", "verified": False})
            cmds["test"].append({"cmd": "poetry run pytest", "source": "poetry.lock", "verified": False})
        else:
            cmds["install"].append({"cmd": "python3 -m pip install -e .",
                                    "source": "pyproject.toml", "verified": False})
            cmds["test"].append({"cmd": "python3 -m pytest", "source": "pyproject.toml", "verified": False})
        if (root / "ruff.toml").exists() or "ruff" in read_text(root / "pyproject.toml"):
            cmds["lint"].append({"cmd": "ruff check .", "source": "pyproject.toml", "verified": False})
            cmds["format"].append({"cmd": "ruff format --check .", "source": "pyproject.toml", "verified": False})
        cmds["package"].append({"cmd": "python3 -m build", "source": "pyproject.toml", "verified": False})
    if "Package.swift" in names:
        cmds["build"].append({"cmd": "swift build -c release", "source": "Package.swift", "verified": False})
        cmds["test"].append({"cmd": "swift test", "source": "Package.swift", "verified": False})
    if "project.pbxproj" in names:
        cmds["build"].append({"cmd": "xcodebuild -list", "source": "xcodeproj", "verified": False,
                              "note": "expand to a real scheme before building"})
    if ctx.get("has_py_tests") and not any(c["cmd"].endswith("pytest") for c in cmds["test"]):
        cmds["test"].append({"cmd": "python3 -m pytest", "source": "tests", "verified": False})
    if "Makefile" in names:
        targets = read_makefile_targets(root / "Makefile")
        for t, key in (("test", "test"), ("build", "build"), ("lint", "lint"), ("fmt", "format"), ("install", "install")):
            if t in targets:
                cmds[key].insert(0, {"cmd": f"make {t}", "source": "Makefile", "verified": False})
        ctx["make_targets"] = targets
    if "Justfile" in names:
        for key in ("test", "build", "lint"):
            cmds[key].append({"cmd": f"just {key}", "source": "Justfile", "verified": False})
    if "Gemfile" in names:
        cmds["install"].append({"cmd": "bundle install", "source": "Gemfile", "verified": False})
        cmds["test"].append({"cmd": "bundle exec rspec", "source": "Gemfile", "verified": False})
    if "composer.json" in names:
        cmds["install"].append({"cmd": "composer install", "source": "composer.json", "verified": False})
    if "mix.exs" in names:
        cmds["test"].append({"cmd": "mix test", "source": "mix.exs", "verified": False})
    if "pubspec.yaml" in names:
        cmds["install"].append({"cmd": "flutter pub get", "source": "pubspec.yaml", "verified": False})
        cmds["test"].append({"cmd": "flutter test", "source": "pubspec.yaml", "verified": False})
    if "CMakeLists.txt" in names:
        cmds["build"].append({"cmd": "cmake -S . -B build && cmake --build build", "source": "CMakeLists.txt", "verified": False})
        cmds["test"].append({"cmd": "ctest --test-dir build", "source": "CMakeLists.txt", "verified": False})

    # Only keep commands whose declaration file is actually present.
    present = set(ctx["manifest_names"])
    for key, items in cmds.items():
        if isinstance(items, list):
            cmds[key] = [i for i in items if i["source"] in present or i["source"] in
                         ("package.json", "Makefile", "Justfile", "xcodeproj", "Info.plist",
                          # "tests" is a detected directory, not a manifest file
                          "tests")]

    # de-duplicate by command string, first wins
    for key, items in cmds.items():
        seen, uniq = set(), []
        for item in items:
            if item["cmd"] in seen:
                continue
            seen.add(item["cmd"])
            uniq.append(item)
        cmds[key] = uniq
    cmds["_package_manager"] = pm
    return cmds


def scan(root: Path, deep: bool = False, max_files: int = 200000) -> dict:
    files = list(walk(root, include_git=False, max_files=max_files))
    ext_counter = Counter()
    sizes = Counter()
    manifests, docs, assets, workflows, tests, ci = [], [], [], [], [], []
    big_files = []
    total = 0

    for path in files:
        r = rel(root, path)
        name = path.name
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total += size
        suffix = path.suffix.lower()
        if suffix in LANG_BY_EXT:
            ext_counter[LANG_BY_EXT[suffix]] += 1
            sizes[LANG_BY_EXT[suffix]] += size
        if name in MANIFESTS or name.endswith(".pbxproj") or name.endswith(".xcodeproj") or name.endswith(".xcworkspace"):
            manifests.append({"path": r, "type": MANIFESTS.get(name, "project")})
        if name in DOC_NAMES or (name.lower().startswith("readme")):
            docs.append(r)
        if suffix in ASSET_EXTS:
            assets.append({"path": r, "bytes": size})
        if r.startswith(".github/workflows/") and suffix in (".yml", ".yaml"):
            workflows.append(r)
        if r.startswith(".github/"):
            ci.append(r)
        lowered = r.lower()
        if ("test" in lowered or "spec" in lowered) and suffix in LANG_BY_EXT and "/." not in lowered:
            tests.append(r)
        if size > 10 * 1024 * 1024:
            big_files.append({"path": r, "bytes": size})

    lang_total = sum(ext_counter.values()) or 1
    languages = [{"name": k, "files": v, "bytes": sizes[k],
                  "share": round(100.0 * v / lang_total, 1)}
                 for k, v in ext_counter.most_common(12)]

    dep_names = set()
    pkg = load_json(root / "package.json") if (root / "package.json").exists() else {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(pkg.get(key), dict):
            dep_names |= set(pkg[key])

    has_public_html = any((root / d / "index.html").exists() for d in ("public", "www", "static", "web"))
    swift_manifest = read_text(root / "Package.swift")
    has_executable_target = ".executableTarget" in swift_manifest or ".executable(" in swift_manifest
    cargo_toml = read_text(root / "Cargo.toml")
    py_text = read_text(root / "pyproject.toml") + read_text(root / "setup.py") + read_text(root / "setup.cfg")
    go_main = any(p.name == "main.go" for p in files)

    py_files = [p for p in files if p.suffix == ".py"]
    py_hints = set()
    for path in py_files[:40]:
        text = read_text(path, limit=20000)
        for token in ("argparse", "click", "typer", "__main__", "http.server",
                      "fastapi", "flask", "uvicorn", "django", "pytest"):
            if token in text:
                py_hints.add(token)

    has_py_tests = any(p.name.startswith("test_") or p.name.endswith("_test.py")
                       or p.name == "test.py" for p in files) or (root / "tests").is_dir()

    ctx = {
        "root": str(root),
        "py_source_hints": py_hints,
        "has_py_tests": has_py_tests,
        # names of manifests that ACTUALLY exist (never the whole known list,
        # or every project would look like it ships a Gemfile)
        "manifest_names": {Path(m["path"]).name for m in manifests},
        "dependencies": dep_names,
        "extensions": set(f".{s}" for s in [p.suffix.lower().lstrip('.') for p in files] if s),
        "languages": [l["name"] for l in languages],
        "has_public_html": has_public_html,
        "has_executable_target": has_executable_target,
        "rust_binary": "[[bin]]" in cargo_toml or (root / "src" / "main.rs").exists(),
        "py_console_scripts": "console_scripts" in py_text or "scripts" in py_text and "setup.py" in py_text,
        "go_main": go_main,
    }
    app_type = classify_app_type(ctx)

    # ---- version ------------------------------------------------------------
    version, version_source = "", ""
    for candidate in VERSION_FILES:
        for path in sorted(root.glob(candidate)):
            v = ""
            if path.name == "package.json" or path.name == "tauri.conf.json":
                data = load_json(path)
                v = node_version(data) if path.name == "package.json" else str(data.get("version", ""))
            elif path.name in ("Cargo.toml", "pyproject.toml", "Project.toml"):
                v = toml_version(path)
            elif path.name == "pubspec.yaml":
                m = re.search(r"(?m)^version:\s*([^\s+]+)", read_text(path))
                v = m.group(1) if m else ""
            elif path.name in ("VERSION", "version.txt"):
                v = read_text(path).strip().splitlines()[0] if read_text(path).strip() else ""
            elif path.name == "Info.plist":
                try:
                    v = str(plistlib.loads(path.read_bytes()).get("CFBundleShortVersionString", ""))
                except Exception:
                    v = ""
            elif path.name == "gradle.properties":
                m = re.search(r"(?m)^version=(.+)$", read_text(path))
                v = m.group(1).strip() if m else ""
            if v:
                version, version_source = v, rel(root, path)
                break
        if version:
            break

    # ---- git ----------------------------------------------------------------
    git_info = {"is_repo": False}
    if is_git_repo(root):
        g_root = root
        remotes = git(g_root, "remote", "-v").stdout.strip().splitlines()
        remote_urls = sorted({ln.split()[1] for ln in remotes if len(ln.split()) > 1})
        tags = [t for t in git(g_root, "tag", "--sort=-creatordate").stdout.splitlines() if t]
        branches = [b.lstrip("* ").strip() for b in git(g_root, "branch", "--format=%(refname:short)").stdout.splitlines() if b.strip()]
        commit_count = git(g_root, "rev-list", "--count", "HEAD").stdout.strip()
        last_commit = git(g_root, "log", "-1", "--format=%h %ad %s", "--date=short").stdout.strip()
        first_commit = git(g_root, "log", "--reverse", "--format=%ad", "--date=short").stdout.splitlines()
        authors = git(g_root, "shortlog", "-sne", "HEAD").stdout.strip().splitlines()
        git_info = {
            "is_repo": True,
            "root": str(g_root),
            "branch": default_branch(g_root),
            "branches": branches[:25],
            "remotes": remote_urls,
            "tags": tags[:20],
            "commit_count": int(commit_count) if commit_count.isdigit() else 0,
            "last_commit": last_commit,
            "first_commit_date": first_commit[0] if first_commit else "",
            "authors": authors[:10],
            "dirty": bool(dirty_paths(g_root)),
            "unpushed": _unpushed(g_root),
        }
    else:
        git_info = {"is_repo": False, "root": None, "branch": "", "remotes": [],
                    "tags": [], "commit_count": 0, "dirty": False}

    # ---- monorepo -----------------------------------------------------------
    nested = []
    workspace_globs = []
    ws_file = root / "pnpm-workspace.yaml"
    if ws_file.exists():
        workspace_globs = re.findall(r"-\s*['\"]?([^'\"\n]+)", read_text(ws_file))
    for path in files:
        if path.name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod") and path.parent != root:
            depth = len(path.relative_to(root).parts)
            if depth <= 3:
                nested.append(rel(root, path.parent))
    monorepo = bool(workspace_globs) or (len({n for n in nested}) > 1 and len(nested) >= 2)

    # ---- entry points -------------------------------------------------------
    entry_points = []
    for pattern, label in (
        ("src/main.rs", "Rust binary"), ("main.go", "Go main"), ("cmd/*/main.go", "Go command"),
        ("src/main.ts", "TS entry"), ("src/index.ts", "TS index"), ("src/index.js", "JS index"),
        ("src/App.tsx", "React app"), ("src/App.vue", "Vue app"), ("src/app/page.tsx", "Next.js page"),
        ("app/page.tsx", "Next.js page"), ("index.html", "Web page"), ("main.py", "Python main"),
        ("__main__.py", "Python module entry"), ("src/__main__.py", "Python module entry"),
        ("src/App.swift", "SwiftUI app"), ("Sources/*/main.swift", "Swift main"),
        ("main.swift", "Swift main"), ("lib/main.dart", "Flutter main"),
        ("src-tauri/src/main.rs", "Tauri backend"), ("electron/main.js", "Electron main"),
    ):
        for found in sorted(root.glob(pattern))[:3]:
            entry_points.append({"path": rel(root, found), "kind": label})

    if not entry_points:
        for path in files:
            if path.parent != root or path.suffix not in (".py", ".js", ".mjs", ".sh", ".rb", ".go", ".rs"):
                continue
            head = read_text(path, limit=6000)
            if '__name__ == "__main__"' in head or 'require.main === module' in head:
                entry_points.append({"path": rel(root, path), "kind": "script entry"})

    commands = detect_commands(root, ctx)

    result = {
        "project": {
            "path": str(root),
            "name": _project_name(root, pkg),
            "app_type": app_type,
            "monorepo": monorepo,
            "workspace_globs": workspace_globs,
            "nested_projects": sorted(set(nested))[:20],
            "version": version,
            "version_source": version_source,
            "description": pkg.get("description", "") if isinstance(pkg.get("description"), str) else "",
            "license_field": (pkg.get("license") if isinstance(pkg.get("license"), str) else ""),
            "homepage": pkg.get("homepage", "") if isinstance(pkg.get("homepage"), str) else "",
            "repository_field": pkg.get("repository") if isinstance(pkg.get("repository"), (str, dict)) else "",
            "keywords": pkg.get("keywords", []) if isinstance(pkg.get("keywords"), list) else [],
            "author": pkg.get("author") if isinstance(pkg.get("author"), (str, dict)) else "",
            "private": bool(pkg.get("private", False)),
        },
        "languages": languages,
        "manifests": manifests[:60],
        "package_manager": commands["_package_manager"],
        "commands": {k: v for k, v in commands.items() if k != "_package_manager"},
        "entry_points": entry_points,
        "documentation": sorted(docs),
        "assets": sorted(assets, key=lambda a: -a["bytes"])[:40],
        "asset_count": len(assets),
        "ci": {"workflows": workflows, "github_files": ci},
        "tests": {"count": len(tests), "samples": tests[:15]},
        "big_files": big_files[:15],
        "totals": {"files": len(files), "bytes": total, "human_bytes": human_size(total)},
        "git": git_info,
        "tools_available": {t: bool(which(t)) for t in
                            ("git", "gh", "node", "npm", "pnpm", "python3", "uv",
                             "cargo", "go", "swift", "xcodebuild", "jq", "ffmpeg",
                             "magick", "convert", "playwright", "npx", "sips", "zip")},
    }
    if deep:
        result["deep"] = _deep_probe(root, result)
    return result


def _unpushed(root: Path) -> int:
    res = git(root, "rev-list", "--count", "@{u}..HEAD")
    if res.ok and res.stdout.strip().isdigit():
        return int(res.stdout.strip())
    return 0


def _project_name(root: Path, pkg: dict) -> str:
    if isinstance(pkg.get("name"), str) and pkg["name"].strip():
        return pkg["name"].strip()
    cargo = read_text(root / "Cargo.toml")
    m = re.search(r'(?m)^name\s*=\s*"([^"]+)"', cargo)
    if m:
        return m.group(1)
    return root.name


def _deep_probe(root: Path, base: dict) -> dict:
    """Non-destructive probes: does the toolchain actually respond?"""
    probes = {}
    for tool, args in (("git", ["--version"]), ("gh", ["--version"]), ("node", ["--version"]),
                       ("python3", ["--version"]), ("cargo", ["--version"]), ("go", ["version"]),
                       ("swift", ["--version"])):
        if which(tool):
            res = run([tool, *args], timeout=20)
            probes[tool] = (res.stdout or res.stderr).strip().splitlines()[:1]
    gh_auth = run(["gh", "auth", "status"], timeout=30) if which("gh") else None
    return {
        "tool_versions": probes,
        "gh_authenticated": bool(gh_auth and gh_auth.ok),
        "has_readme": any((root / n).exists() for n in ("README.md", "README.rst", "README.txt", "README")),
        "has_license": any((root / n).exists() for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")),
        "has_gitignore": (root / ".gitignore").exists(),
        "has_workflows": bool(base["ci"]["workflows"]),
    }


def main(argv=None):
    ap = parser(description="gitup Phase A project discovery")
    ap.add_argument("--project", required=True, help="path to the project directory")
    ap.add_argument("--out", default="", help="write JSON here as well as stdout")
    ap.add_argument("--deep", action="store_true", help="also probe toolchain availability")
    ap.add_argument("--max-files", type=int, default=200000)
    args = ap.parse_args(argv)

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        from gitup_common import die
        die(f"project directory not found: {root}")
    data = scan(root, deep=args.deep, max_files=args.max_files)
    emit(data, args.out or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
