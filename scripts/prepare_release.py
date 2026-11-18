#!/usr/bin/env python3
"""
GITU Section 6: Release Management System
Categorizes actual Git commits into structured release notes, creates annotated
semantic version tags, packages clean source distributions (excluding .git and secrets),
and generates SHA256SUMS.txt checksum manifests.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", "dist"}
EXCLUDE_FILES = {".DS_Store", ".env", ".env.local", ".env.production"}


def run_cmd(cmd, cwd):
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode == 0, res.stdout.strip(), res.stderr.strip()


def sha256_file(fpath: Path) -> str:
    h = hashlib.sha256()
    with fpath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_commits_since_last_tag(root: Path):
    ok_t, last_tag, _ = run_cmd(["git", "describe", "--tags", "--abbrev=0"], cwd=root)
    rev_range = f"{last_tag}..HEAD" if (ok_t and last_tag) else "HEAD"
    ok_l, log_out, _ = run_cmd(["git", "log", rev_range, "--pretty=format:%h|%s"], cwd=root)
    commits = []
    if ok_l and log_out:
        for line in log_out.splitlines():
            if "|" in line:
                sha, subj = line.split("|", 1)
                commits.append({"sha": sha.strip(), "subject": subj.strip()})
    return last_tag if ok_t else None, commits


def generate_release_notes(project_name: str, version: str, last_tag: str, commits: list) -> str:
    features, fixes, docs, others = [], [], [], []
    for c in commits:
        subj = c["subject"]
        entry = f"- {subj} (`{c['sha']}`)"
        low = subj.lower()
        if low.startswith(("feat:", "feat(", "feature:")):
            features.append(entry)
        elif low.startswith(("fix:", "fix(", "bugfix:")):
            fixes.append(entry)
        elif low.startswith(("docs:", "doc:")):
            docs.append(entry)
        else:
            others.append(entry)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sections = [
        f"# {project_name} {version} ({date_str})",
        "",
        f"Release `{version}` generated from verified repository history"
        + (f" (changes since `{last_tag}`)." if last_tag else "."),
        "",
    ]
    if features:
        sections.extend(["## Features", *features, ""])
    if fixes:
        sections.extend(["## Bug Fixes", *fixes, ""])
    if docs:
        sections.extend(["## Documentation", *docs, ""])
    if others:
        sections.extend(["## Maintenance & Engineering", *others, ""])
    if not commits:
        sections.extend(["## Summary", "- Initial tagged release snapshot.", ""])

    sections.extend([
        "## Verification & Checksums",
        "All release archives in this release are accompanied by `SHA256SUMS.txt`. Verify integrity with:",
        "```bash",
        "shasum -a 256 -c SHA256SUMS.txt",
        "```",
        "",
    ])
    return "\n".join(sections)


def build_source_archives(root: Path, project_name: str, version: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_ver = version.lstrip("v")
    base_name = f"{project_name}-{clean_ver}"
    tar_path = out_dir / f"{base_name}-src.tar.gz"
    zip_path = out_dir / f"{base_name}-src.zip"

    files_to_pack = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if fname in EXCLUDE_FILES or fname.startswith(".env"):
                continue
            fpath = Path(dirpath) / fname
            if out_dir in fpath.parents:
                continue
            files_to_pack.append(fpath)

    with tarfile.open(tar_path, "w:gz") as tf:
        for fpath in files_to_pack:
            rel = fpath.relative_to(root)
            tf.add(fpath, arcname=str(Path(base_name) / rel))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in files_to_pack:
            rel = fpath.relative_to(root)
            zf.write(fpath, arcname=str(Path(base_name) / rel))

    return [tar_path, zip_path]


def main():
    parser = argparse.ArgumentParser(description="GITU Section 6: Release Artifact & Notes Builder")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--version", default="v0.1.0", help="Release version tag (e.g. v0.1.0)")
    parser.add_argument("--output-dir", help="Directory for release archives and notes")
    parser.add_argument("--create-tag", action="store_true", help="Create annotated Git tag if not present")
    args = parser.parse_args()

    root = Path(args.project_path).resolve()
    version = args.version if args.version.startswith("v") else f"v{args.version}"
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (root / "dist")
    project_name = root.name

    last_tag, commits = collect_commits_since_last_tag(root)
    notes = generate_release_notes(project_name, version, last_tag, commits)

    archives = build_source_archives(root, project_name, version, out_dir)
    notes_path = out_dir / f"RELEASE_NOTES_{version}.md"
    notes_path.write_text(notes, encoding="utf-8")

    checksum_lines = []
    artifact_meta = []
    for arch in archives:
        digest = sha256_file(arch)
        checksum_lines.append(f"{digest}  {arch.name}")
        artifact_meta.append({
            "filename": arch.name,
            "path": str(arch),
            "size_bytes": arch.stat().st_size,
            "sha256": digest,
            "type": "source-distribution",
        })

    sums_path = out_dir / "SHA256SUMS.txt"
    sums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    tag_created = False
    if args.create_tag and (root / ".git").exists():
        ok_existing, existing_tags, _ = run_cmd(["git", "tag", "--list", version], cwd=root)
        if not existing_tags.strip():
            ok_tag, _, _ = run_cmd(["git", "tag", "-a", version, "-m", f"Release {version}"], cwd=root)
            tag_created = ok_tag

    print(json.dumps({
        "project_name": project_name,
        "version": version,
        "tag_created": tag_created,
        "release_notes_path": str(notes_path),
        "checksums_path": str(sums_path),
        "artifacts": artifact_meta,
    }, indent=2))


if __name__ == "__main__":
    main()
