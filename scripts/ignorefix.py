#!/usr/bin/env python3
"""gitup ignorefix.py - write a stack-appropriate, minimal .gitignore.

Merges missing patterns into an existing .gitignore instead of replacing it, so
hand-written rules survive. Prints what changed as JSON.

Usage:
  python3 ignorefix.py --project ~/Developer/MyProject [--dry-run] [--out result.json]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import sys
from pathlib import Path

from gitup_common import die, emit, read_text, parser

# Ordered blocks; each block is only added when the stack is detected.
BLOCKS = {
    "core": [
        "# OS and editor noise",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".Spotlight-V100",
        ".Trashes",
        "*.swp",
        "*.swo",
        "*~",
        ".idea/",
        "",
        "# Secrets and local configuration",
        ".env",
        ".env.local",
        ".env.*.local",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "secrets.json",
        "credentials.json",
    ],
    "node": [
        "", "# Node",
        "node_modules/",
        "npm-debug.log*",
        "yarn-error.log*",
        "pnpm-debug.log*",
        ".pnpm-store/",
        "coverage/",
        ".next/",
        ".nuxt/",
        ".svelte-kit/",
        ".turbo/",
        ".vercel/",
        ".netlify/",
        "dist/",
        "build/",
        "out/",
        "*.tsbuildinfo",
    ],
    "python": [
        "", "# Python",
        "__pycache__/",
        "*.py[cod]",
        "*.egg-info/",
        ".venv/",
        "venv/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".coverage",
        "htmlcov/",
        "dist/",
        "build/",
        "*.whl",
    ],
    "rust": ["", "# Rust", "target/", "**/*.rs.bk", "Cargo.lock"],
    "go": ["", "# Go", "bin/", "*.test", "*.out", "vendor/"],
    "swift": [
        "", "# Swift / Xcode",
        ".build/",
        "DerivedData/",
        "*.xcuserstate",
        "xcuserdata/",
        "*.xcscmblueprint",
        "*.xccheckout",
        ".swiftpm/",
        "Packages/",
    ],
    "java": ["", "# Java / Kotlin", "build/", "target/", ".gradle/", "*.class", "*.jar", "!gradle/wrapper/gradle-wrapper.jar"],
    "ruby": ["", "# Ruby", ".bundle/", "vendor/bundle/", "*.gem"],
    "php": ["", "# PHP", "vendor/", "composer.lock"],
    "dotnet": ["", "# .NET", "bin/", "obj/", "*.user", "*.suo"],
    "macos": ["", "# macOS app packaging", "*.dmg", "*.app.zip", "*.pkg", "*.xcarchive"],
}


def detect_stacks(root: Path) -> list[str]:
    stacks = ["core"]
    checks = {
        "node": ["package.json"],
        "python": ["pyproject.toml", "setup.py", "requirements.txt"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
        "swift": ["Package.swift", "project.pbxproj"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "ruby": ["Gemfile"],
        "php": ["composer.json"],
        "dotnet": ["global.json"],
    }
    for stack, files in checks.items():
        if any((root / f).exists() for f in files) or any(root.glob(f"**/{files[0]}")) and stack == "swift":
            stacks.append(stack)
    if "swift" in stacks:
        stacks.append("macos")
    return stacks


def apply_gitignore(root: Path, dry_run: bool = False) -> dict:
    path = root / ".gitignore"
    existing = read_text(path)
    have = {ln.strip() for ln in existing.splitlines() if ln.strip() and not ln.strip().startswith("#")}
    stacks = detect_stacks(root)
    added, blocks_used = [], []
    body = existing.rstrip("\n")
    for stack in stacks:
        lines = BLOCKS.get(stack, [])
        new_lines = []
        for line in lines:
            if not line:
                new_lines.append("")
                continue
            if line.strip() in have:
                continue
            new_lines.append(line)
            have.add(line.strip())
            added.append(line.strip())
        if new_lines:
            body += ("\n\n" if body else "") + "\n".join(new_lines).lstrip("\n") + "\n"
            blocks_used.append(stack)
    if not added:
        return {"gitignore": str(path), "changed": False, "added": [], "stacks": stacks,
                "note": "already covers every pattern gitup expects"}
    if not dry_run:
        path.write_text(body.lstrip("\n") + "\n", encoding="utf-8")
    return {"gitignore": str(path), "changed": True, "dry_run": dry_run,
            "added": len(added), "patterns": added[:80], "stacks": blocks_used or stacks,
            "note": "merged into the existing file, nothing removed"}


def main(argv=None):
    ap = parser(description="write/merge a .gitignore for this stack")
    ap.add_argument("--project", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    emit(apply_gitignore(root, args.dry_run), args.out or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
