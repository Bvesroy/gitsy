#!/usr/bin/env python3
"""gitup license.py - handle licensing without guessing on the user's behalf.

A license is a legal choice, not a cosmetic one. So this script:

  * detects what license (if any) the project already has, and where the
    manifest disagrees with the LICENSE file;
  * explains the real trade-offs of the shortlisted options;
  * only writes a LICENSE when one is named explicitly (--spdx), never by
    inference;
  * never changes a project's existing license (that needs authorization);
  * records the year and copyright holder exactly as given.

Usage:
  python3 license.py inspect --project . [--out license.json]
  python3 license.py options --project .
  python3 license.py write   --project . --spdx MIT --holder "Jane Doe" [--year 2026] [--dry-run]
  python3 license.py write   --project . --spdx Apache-2.0 --holder "..." --from-url
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from gitup_common import die, emit, read_text, rel, run, which, parser

LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE")

SPDX_PATTERNS = {
    "MIT": r"\bMIT License\b|\bPermission is hereby granted, free of charge\b",
    "Apache-2.0": r"\bApache License\b[\s\S]{0,80}2\.0",
    "BSD-3-Clause": r"\bRedistribution and use in source and binary forms\b[\s\S]{0,400}Neither the name\b",
    "BSD-2-Clause": r"\bRedistribution and use in source and binary forms\b",
    "GPL-3.0": r"\bGNU GENERAL PUBLIC LICENSE\b[\s\S]{0,80}Version 3",
    "GPL-2.0": r"\bGNU GENERAL PUBLIC LICENSE\b[\s\S]{0,80}Version 2",
    "AGPL-3.0": r"\bGNU AFFERO GENERAL PUBLIC LICENSE\b",
    "LGPL-3.0": r"\bGNU LESSER GENERAL PUBLIC LICENSE\b[\s\S]{0,80}Version 3",
    "MPL-2.0": r"\bMozilla Public License\b[\s\S]{0,40}2\.0",
    "Unlicense": r"\bThis is free and unencumbered software\b",
    "ISC": r"\bISC License\b|\bPermission to use, copy, modify, and/or distribute\b",
    "BSL-1.0": r"\bBoost Software License\b",
}

CHOICES = {
    "MIT": {
        "grants": "Anyone may use, modify and sell your code, keeping your copyright notice.",
        "obliges": "They must include your license and copyright text. No warranty.",
        "best_for": "Libraries and tools where you want maximum adoption with no friction.",
        "risk": "A competitor can ship a closed product built on your code.",
    },
    "Apache-2.0": {
        "grants": "Same permisssiveness as MIT, plus an explicit patent grant.",
        "obliges": "Keep notices, state changes, include the license and NOTICE file.",
        "best_for": "Anything used by companies, or where patents are a real risk.",
        "risk": "Slightly more paperwork; NOTICE handling trips people up.",
    },
    "GPL-3.0": {
        "grants": "Use, modify and redistribute, including commercially.",
        "obliges": "Distributed derivatives must be GPL too and ship source.",
        "best_for": "Projects that must stay open, including in forks and appliances.",
        "risk": "Companies with closed products will not adopt it.",
    },
    "AGPL-3.0": {
        "grants": "As GPL, and the network-use clause closes the SaaS loophole.",
        "obliges": "Running a modified version as a service also requires sharing source.",
        "best_for": "Server software you do not want re-hosted privately.",
        "risk": "The most avoided license in commercial procurement.",
    },
    "MPL-2.0": {
        "grants": "File-level copyleft: you may combine with closed code.",
        "obliges": "Modified MPL files stay MPL and must be published.",
        "best_for": "Projects that want openness without infecting large closed codebases.",
        "risk": "Less familiar to contributors than MIT or Apache.",
    },
    "Unlicense": {
        "grants": "Everything, into the public domain as far as law allows.",
        "obliges": "Nothing.",
        "best_for": "Snippets and reference code you truly do not want to control.",
        "risk": "Some jurisdictions cannot disclaim all rights; companies avoid it.",
    },
}


def find_license(root: Path):
    for name in LICENSE_NAMES:
        if (root / name).exists():
            return root / name
    return None


def declared_in_manifest(root: Path) -> tuple[str, str]:
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            value = data.get("license") or (data.get("licenses") or [{}])
            if isinstance(value, str):
                return value, "package.json"
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return str(value[0].get("type", "")), "package.json"
        except Exception:
            pass
    for name in ("pyproject.toml", "Cargo.toml"):
        path = root / name
        if path.exists():
            m = re.search(r'(?m)^\s*license\s*=\s*[{"]?\s*(?:text\s*=\s*)?"?([A-Za-z0-9.\-+]+)',
                          read_text(path))
            if m:
                return m.group(1), name
    gem = list(root.glob("*.gemspec"))
    if gem:
        m = re.search(r"license\s*=\s*['\"]([^'\"]+)", read_text(gem[0]))
        if m:
            return m.group(1), gem[0].name
    return "", ""


def inspect(root: Path) -> dict:
    lic = find_license(root)
    detected, text = "", ""
    if lic:
        text = read_text(lic)
        norm = re.sub(r"\s+", " ", text)
        for spdx, pattern in SPDX_PATTERNS.items():
            if re.search(pattern, norm, re.I):
                detected = spdx
                break
        if not detected and "AGPL" in text.upper():
            detected = "AGPL-3.0"
    declared, declared_src = declared_in_manifest(root)
    holder = ""
    year = ""
    if text:
        m = re.search(r"Copyright\s*(?:\(c\)|©)?\s*(\d{4})(?:[-,]\s*(\d{4}))?\s+(.+)", text)
        if m:
            year = m.group(2) or m.group(1)
            holder = m.group(3).strip().splitlines()[0][:80]
    consistent = True
    problem = ""
    if declared and detected and declared.upper() != detected.upper():
        consistent = False
        problem = f"{declared_src} declares '{declared}' but the LICENSE text looks like {detected}"
    if declared and not lic:
        consistent = False
        problem = f"{declared_src} declares '{declared}' but there is no LICENSE file"
    return {
        "project": str(root),
        "license_file": rel(root, lic) if lic else None,
        "detected_spdx": detected or None,
        "declared_in_manifest": declared or None,
        "declared_in": declared_src or None,
        "consistent": consistent,
        "problem": problem,
        "copyright_holder": holder or None,
        "copyright_year": year or None,
        "options": {k: CHOICES[k]["best_for"] for k in ("MIT", "Apache-2.0", "AGPL-3.0", "Unlicense")},
        "note": "License choice is the owner's decision; gitup only reports and, on request, writes.",
    }


MIT_TEMPLATE = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

RAW_URLS = {
    "MIT": "https://raw.githubusercontent.com/licenses/license-templates/master/templates/mit.txt",
    "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    "BSD-3-Clause": "https://raw.githubusercontent.com/licenses/license-templates/master/templates/bsd3.txt",
    "GPL-3.0": "https://www.gnu.org/licenses/gpl-3.0.txt",
    "AGPL-3.0": "https://www.gnu.org/licenses/agpl-3.0.txt",
    "LGPL-3.0": "https://www.gnu.org/licenses/lgpl-3.0.txt",
    "MPL-2.0": "https://www.mozilla.org/media/MPL/2.0/index.815ca599c9df.txt",
    "Unlicense": "https://unlicense.org/UNLICENSE",
}


def fetch_license_text(spdx: str) -> tuple[str, str]:
    import urllib.request
    url = RAW_URLS.get(spdx)
    if not url:
        return "", f"no canonical text source configured for {spdx}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gitup-license/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace"), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"could not fetch official text ({type(exc).__name__}: {exc})"


def write_license(root: Path, spdx: str, holder: str, year: str = "",
                  from_url: bool = False, dry_run: bool = False) -> dict:
    existing = find_license(root)
    if existing:
        return {"ok": False,
                "blocked": "a license already exists and gitup never replaces one",
                "existing": rel(root, existing),
                "hint": "If the project's license must change, that is the owner's call; "
                        "edit the file deliberately and update the manifest."}
    if not holder.strip():
        return {"ok": False, "blocked": "copyright holder is required (--holder)",
                "hint": "Use the person or organization that actually holds the rights."}
    year = year or str(datetime.date.today().year)
    body = ""
    source = "built-in template"
    if spdx == "MIT" and not from_url:
        body = MIT_TEMPLATE.format(year=year, holder=holder.strip())
    else:
        body, err = fetch_license_text(spdx)
        if err:
            return {"ok": False, "blocked": err,
                    "hint": "Run with --from-url on a machine with network access, or paste the "
                            "official text yourself."}
        source = "official text"
        if spdx in ("MIT", "BSD-3-Clause", "ISC") and "Copyright" not in body:
            body = f"Copyright (c) {year} {holder.strip()}\n\n" + body
    target = root / "LICENSE"
    if not dry_run:
        target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return {"ok": True, "dry_run": dry_run, "path": rel(root, target), "spdx": spdx,
            "holder": holder.strip(), "year": year, "source": source,
            "bytes": len(body.encode()),
            "reminder": "Update the manifest's license field to match, if it has one."}


def main(argv=None):
    ap = parser(description="gitup license handling")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--project", required=True); p.add_argument("--out", default="")
    p = sub.add_parser("options"); p.add_argument("--project", required=True); p.add_argument("--out", default="")
    p = sub.add_parser("write"); p.add_argument("--project", required=True)
    p.add_argument("--spdx", required=True); p.add_argument("--holder", required=True)
    p.add_argument("--year", default=""); p.add_argument("--from-url", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--out", default="")
    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    if args.cmd == "inspect":
        out = inspect(root)
    elif args.cmd == "options":
        out = {"project": str(root), "options": CHOICES,
               "current": inspect(root)["detected_spdx"],
               "note": "Pick the one whose obligations you are willing to live with."}
    else:
        out = write_license(root, args.spdx, args.holder, args.year, args.from_url, args.dry_run)
    emit(out, args.out or None)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())