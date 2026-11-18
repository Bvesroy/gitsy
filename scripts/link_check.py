#!/usr/bin/env python3
"""gitup link_check.py - verify every link and image in the project's Markdown.

A README with a broken screenshot is worse than a README without one: it looks
abandoned. This checks relative paths, anchor targets, case sensitivity (GitHub
runs on a case-sensitive filesystem even if yours is not), and optionally remote
URLs over the network.

Network checks are off by default so the script is safe to run offline and in CI
without surprises.

Exit codes: 0 clean, 1 broken links found, 2 usage error.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from gitup_common import die, emit, rel, summarize, Finding, sort_findings, walk, parser

INLINE_LINK_RE = re.compile(r"!?\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
REF_LINK_RE = re.compile(r"^\s*\[(?P<id>[^\]]+)\]:\s*(?P<target>\S+)", re.M)
HTML_LINK_RE = re.compile(r"(?:href|src)=\"(?P<target>[^\"]+)\"")
BARE_URL_RE = re.compile(r"(?<![(\[<])\bhttps?://[^\s)\]>\"']+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def slugify(text: str) -> str:
    """GitHub's heading-anchor algorithm, close enough to matter."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text)
    return text


def strip_code_blocks(text: str) -> str:
    out, in_fence = [], False
    for line in text.splitlines():
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def headings_of(text: str) -> set:
    slugs = set()
    for line in strip_code_blocks(text).splitlines():
        m = HEADING_RE.match(line)
        if m:
            slugs.add(slugify(m.group(2)))
    return slugs


def collect_targets(text: str):
    clean = strip_code_blocks(text)
    found = []
    for m in INLINE_LINK_RE.finditer(clean):
        found.append((m.group("target"), m.group("text") or ""))
    for m in REF_LINK_RE.finditer(clean):
        found.append((m.group("target"), "^" + m.group("id")))
    for m in HTML_LINK_RE.finditer(clean):
        found.append((m.group("target"), "<html>"))
    return found


def check_remote(url: str, timeout: int = 10) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "gitup-link-check/1.0 (+https://github.com)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return (200 <= resp.status < 400), f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405):  # HEAD blocked; try GET once
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "gitup-link-check/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return (200 <= resp.status < 400), f"HTTP {resp.status}"
            except Exception as exc2:  # noqa: BLE001 - report, never raise
                return False, f"{type(exc2).__name__}: {exc2}"
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - network is best-effort
        return False, f"{type(exc).__name__}: {exc}"


def check_links(root: Path, remote: bool = False, offline: bool = False) -> dict:
    findings: list[Finding] = []
    md_files = [p for p in walk(root) if p.suffix.lower() in (".md", ".markdown", ".mdown")]
    cache: dict[str, tuple[bool, str]] = {}
    checked = 0
    remote_checked = 0

    for path in md_files:
        rp = rel(root, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        doc_slugs = headings_of(text)
        for target, label in collect_targets(text):
            if not target or target.startswith(("mailto:", "tel:", "data:")):
                continue
            source_line = _line_of(text, target)
            parsed = urlparse(target)
            if parsed.scheme in ("http", "https"):
                checked += 1
                if remote and not offline:
                    if target not in cache:
                        cache[target] = check_remote(target)
                    ok, detail = cache[target]
                    remote_checked += 1
                    if not ok:
                        findings.append(Finding("docs", "link.remote-broken", "medium",
                                                f"Unreachable link in {rp}: {target}",
                                                detail, [f"{rp}:{source_line}"],
                                                "Fix or remove the link."))
                continue
            if parsed.scheme and parsed.scheme not in ("", "file"):
                continue
            checked += 1
            bare = unquote(parsed.path)
            anchor = unquote(parsed.fragment)
            if bare in ("", ".") and anchor:
                if anchor.lower() not in doc_slugs:
                    findings.append(Finding("docs", "link.anchor-missing", "medium",
                                            f"Anchor '#{anchor}' not found in {rp}",
                                            "Heading may have been renamed.",
                                            [f"{rp}:{source_line}"],
                                            "Update the anchor to the current heading slug."))
                continue
            candidate = (root / bare.lstrip("/")) if bare.startswith("/") else (path.parent / bare)
            # Case-insensitive resolution: a link that works on macOS/Windows
            # but 404s on GitHub's case-sensitive filesystem. Resolution is
            # relative to the document, exactly like a browser or GitHub.
            search_base = path.parent if not bare.startswith("/") else root
            matched = candidate if candidate.exists() else _case_insensitive_find(
                search_base, bare if not bare.startswith("/") else bare.lstrip("/"))
            if matched is None:
                hint = ""
                findings.append(Finding(
                    "docs", "link.file-missing", "high",
                    f"Missing file for link in {rp}: {bare}",
                    f"Target does not exist{hint}. GitHub is case-sensitive.",
                    [f"{rp}:{source_line}"],
                    "Fix the path or add the missing asset."))
                continue
            if matched != candidate:
                findings.append(Finding(
                    "docs", "link.case-mismatch", "high",
                    f"Case mismatch in link from {rp}: {bare}",
                    f"The link works on a case-insensitive disk but breaks on GitHub. "
                    f"File on disk: {rel(root, matched)}",
                    [f"{rp}:{source_line}"],
                    "Rename the link target to match the file's exact casing."))
            candidate = matched
            if anchor and candidate.is_file() and candidate.suffix.lower() in (".md", ".markdown"):
                if anchor.lower() not in headings_of(candidate.read_text(encoding="utf-8", errors="replace")):
                    findings.append(Finding("docs", "link.anchor-missing", "low",
                                            f"Anchor '#{anchor}' not found in {rel(root, candidate)}",
                                            f"Linked from {rp}.", [f"{rp}:{source_line}"],
                                            "Update the anchor."))
            if label.startswith("!") or candidate.suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                try:
                    size = candidate.stat().st_size
                except OSError:
                    size = 0
                if size > 5 * 1024 * 1024:
                    findings.append(Finding("presentation", "asset.heavy", "low",
                                            f"Large image linked from {rp}: {bare}",
                                            f"{size / 1048576:.1f} MB; GitHub renders it slowly on mobile.",
                                            [f"{rp}:{source_line}"],
                                            "Resize to <=1600px wide and re-encode as PNG/WebP."))
                elif size == 0:
                    findings.append(Finding("presentation", "asset.empty", "high",
                                            f"Zero-byte image linked from {rp}: {bare}",
                                            "A broken image box is visible to every visitor.",
                                            [f"{rp}:{source_line}"], "Replace or remove it."))

    findings = sort_findings(findings)
    return {
        "checklist": "docs",
        "project": str(root),
        "markdown_files": len(md_files),
        "links_checked": checked,
        "remote_checked": remote_checked,
        "summary": summarize(findings),
        "findings": [f.as_dict() for f in findings],
        "note": "Remote links are only verified with --remote.",
    }


def _case_insensitive_find(base: Path, bare: str):
    """Resolve a relative path whose letter case differs from disk.

    `base` is the directory the link is relative to (the linking document's
    directory). Handles ".", ".." and leading "/" explicitly instead of asking
    the filesystem to do it, because the filesystem refuses a path that only
    exists with different casing.
    """
    parts = [p for p in bare.replace("\\", "/").split("/") if p not in ("", ".")]
    current = base
    for part in parts:
        if part == "..":
            current = current.parent
            continue
        if not current.is_dir():
            return None
        exact = current / part
        if exact.exists():
            current = exact
            continue
        lower = part.lower()
        found = None
        for entry in current.iterdir():
            if entry.name.lower() == lower:
                found = entry
                break
        if found is None:
            return None
        current = found
    return current


def _line_of(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    return 1


def main(argv=None):
    ap = parser(description="check Markdown links and images")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--remote", action="store_true", help="also fetch http(s) URLs")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    report = check_links(root, remote=args.remote, offline=args.offline)
    emit(report, args.out or None)
    return 1 if report["summary"]["high"] or report["summary"]["blocker"] else 0


if __name__ == "__main__":
    sys.exit(main())
