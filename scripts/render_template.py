#!/usr/bin/env python3
"""gitup render_template.py - fill a gitup template from a JSON map of facts.

Templates use {{PLACEHOLDER}} markers. This renderer refuses to leave a
placeholder behind unless --allow-missing is given, and it drops any section
whose placeholders all resolve to empty, so a published README never contains
"{{USAGE}}" or an empty "## Configuration" heading with nothing under it.

Usage:
  python3 render_template.py --template templates/references/README.md \
      --values facts.json --out /path/project/README.md [--allow-missing]
      [--if-exists skip|overwrite|append] [--dry-run]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
from pathlib import Path

from gitup_common import die, emit, parser

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def load_values(path: str) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"cannot read values file: {exc}")
    except json.JSONDecodeError as exc:
        die(f"values file is not valid JSON: {exc}")
    return {}


def stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {item}" for item in value if str(item).strip())
    if isinstance(value, dict):
        return "\n".join(f"- **{k}**: {v}" for k, v in value.items())
    return str(value).strip()


def drop_empty_sections(text: str) -> str:
    """Remove headings whose body is empty after rendering."""
    lines = text.splitlines()
    out, block, heading = [], [], None
    blocks = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            if heading is not None:
                blocks.append((heading, block))
            heading, block = line, []
        else:
            block.append(line)
    if heading is not None:
        blocks.append((heading, block))

    kept = []
    for heading_line, body in blocks:
        meaningful = [ln for ln in body if ln.strip() not in ("", "---", "***")]
        if not meaningful:
            continue
        kept.append(heading_line)
        kept.extend(body)
        kept.append("")
    result = "\n".join(kept)
    result = re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"
    return result


def render(template_text: str, values: dict, allow_missing: bool = False):
    missing = []

    def sub(match):
        key = match.group(1)
        if key in values:
            return stringify(values[key])
        missing.append(key)
        return "" if allow_missing else match.group(0)

    rendered = PLACEHOLDER_RE.sub(sub, template_text)
    if not allow_missing:
        rendered = drop_empty_sections(rendered)
    else:
        rendered = drop_empty_sections(rendered)
    return rendered, sorted(set(missing))


def main(argv=None):
    ap = parser(description="render a gitup documentation template")
    ap.add_argument("--template", required=True)
    ap.add_argument("--values", default="", help="JSON file mapping PLACEHOLDER -> text")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--if-exists", choices=("skip", "overwrite", "append"), default="skip")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    tpl = Path(args.template).expanduser()
    if not tpl.exists():
        die(f"template not found: {tpl}")
    out = Path(args.out).expanduser()
    template_text = tpl.read_text(encoding="utf-8")
    values = load_values(args.values)
    rendered, missing = render(template_text, values, args.allow_missing)

    if PLACEHOLDER_RE.search(rendered):
        die("unfilled placeholders remain: " + ", ".join(missing))

    action = "create"
    if out.exists():
        action = args.if_exists
        if action == "skip":
            emit({"out": str(out), "action": "skipped", "missing": missing})
            return 0
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        if action == "append":
            with out.open("a", encoding="utf-8") as fh:
                fh.write("\n" + rendered)
        else:
            out.write_text(rendered, encoding="utf-8")
    emit({"out": str(out), "action": action, "dry_run": args.dry_run,
          "bytes": len(rendered.encode()), "missing": missing,
          "lines": rendered.count("\n")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
