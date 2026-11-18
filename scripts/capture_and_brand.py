#!/usr/bin/env python3
"""
GITU Section 5: Visual Presentation Engine & Repository Branding
Generates clean, lightweight SVG architecture diagrams, social preview cards,
project icons, and CLI terminal output SVG snapshots grounded in the project's
real discovered metadata and CLI output. Never fabricates UI screens.
"""

import argparse
import html
import json
import subprocess
from pathlib import Path


def generate_project_icon_svg(project_name: str, primary_lang: str) -> str:
    initials = "".join([w[0].upper() for w in project_name.replace("-", " ").replace("_", " ").split() if w])[:2] or "GT"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120" role="img" aria-label="{html.escape(project_name)} Logo">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e293b"/>
    </linearGradient>
  </defs>
  <rect width="120" height="120" rx="24" fill="url(#bgGrad)" stroke="#334155" stroke-width="2"/>
  <circle cx="96" cy="24" r="6" fill="#38bdf8"/>
  <text x="60" y="68" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="42" font-weight="700" fill="#f8fafc" text-anchor="middle">{html.escape(initials)}</text>
  <text x="60" y="98" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600" fill="#94a3b8" text-anchor="middle" letter-spacing="1">{html.escape(primary_lang.upper()[:12])}</text>
</svg>
"""


def generate_social_preview_svg(project_name: str, description: str, app_types: list, languages: list, version: str) -> str:
    desc_clean = (description or f"Open-source {', '.join(app_types[:2])}").strip()
    if len(desc_clean) > 110:
        desc_clean = desc_clean[:107] + "..."
    lang_str = " • ".join(languages[:4]) if languages else "Software Repository"
    type_str = " / ".join(app_types[:2]) if app_types else "Application"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640" role="img" aria-label="{html.escape(project_name)} Social Preview">
  <defs>
    <linearGradient id="cardBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#090d16"/>
      <stop offset="100%" stop-color="#111827"/>
    </linearGradient>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1f2937" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="1280" height="640" fill="url(#cardBg)"/>
  <rect width="1280" height="640" fill="url(#grid)" opacity="0.55"/>
  <rect x="64" y="64" width="1152" height="512" rx="24" fill="#0f172a" stroke="#334155" stroke-width="2" opacity="0.92"/>
  <rect x="112" y="116" width="160" height="36" rx="18" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>
  <text x="192" y="140" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="15" font-weight="600" fill="#38bdf8" text-anchor="middle">v{html.escape(version)}</text>
  <text x="112" y="250" font-family="system-ui, -apple-system, BlinkMacSystemFont, sans-serif" font-size="72" font-weight="800" fill="#f8fafc">{html.escape(project_name)}</text>
  <text x="112" y="325" font-family="system-ui, -apple-system, BlinkMacSystemFont, sans-serif" font-size="28" font-weight="400" fill="#cbd5e1">{html.escape(desc_clean)}</text>
  <line x1="112" y1="430" x2="1168" y2="430" stroke="#1e293b" stroke-width="2"/>
  <text x="112" y="490" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="22" font-weight="600" fill="#38bdf8">{html.escape(type_str)}</text>
  <text x="1168" y="490" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="22" font-weight="500" fill="#94a3b8" text-anchor="end">{html.escape(lang_str)}</text>
</svg>
"""


def _command_strings(raw) -> list[str]:
    """Flatten a command report to plain command strings.

    ``project_scan.py`` emits ``{"test": [{"cmd": "...", "source": "..."}]}``;
    ``discover_and_audit.py`` emitted ``{"test": "..."}``.
    """
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("cmd"):
            out.append(str(item["cmd"]))
    return out


def generate_architecture_svg(project_name: str, entry_points: list, pkg_managers: list, commands: dict) -> str:
    entries_label = ", ".join(str(e) for e in entry_points[:2]) if entry_points else "Source Modules"
    pkg_label = ", ".join(str(p) for p in pkg_managers[:2]) if pkg_managers else "Standard Runtime"
    test_label = ", ".join(_command_strings(commands.get("test")) or ["Verification Suite"])[:32]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 260" width="900" height="260" role="img" aria-label="{html.escape(project_name)} Architecture Overview">
  <rect width="900" height="260" rx="16" fill="#0f172a" stroke="#334155" stroke-width="1.5"/>
  <text x="40" y="42" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="700" fill="#94a3b8" letter-spacing="1">ARCHITECTURE OVERVIEW (CONCEPTUAL MODULE FLOW)</text>

  <!-- Box 1: Entry Points -->
  <rect x="40" y="75" width="240" height="135" rx="12" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>
  <text x="60" y="110" font-family="system-ui, sans-serif" font-size="16" font-weight="700" fill="#f8fafc">1. Entry Points</text>
  <text x="60" y="140" font-family="ui-monospace, monospace" font-size="13" fill="#38bdf8">{html.escape(entries_label[:28])}</text>
  <text x="60" y="170" font-family="system-ui, sans-serif" font-size="12" fill="#94a3b8">CLI / API / App Interface</text>

  <!-- Arrow 1 -->
  <line x1="280" y1="142" x2="325" y2="142" stroke="#64748b" stroke-width="2"/>
  <polygon points="325,137 335,142 325,147" fill="#64748b"/>

  <!-- Box 2: Core Engine & Dependencies -->
  <rect x="335" y="75" width="240" height="135" rx="12" fill="#1e293b" stroke="#818cf8" stroke-width="1.5"/>
  <text x="355" y="110" font-family="system-ui, sans-serif" font-size="16" font-weight="700" fill="#f8fafc">2. Core Runtime</text>
  <text x="355" y="140" font-family="ui-monospace, monospace" font-size="13" fill="#818cf8">{html.escape(pkg_label[:28])}</text>
  <text x="355" y="170" font-family="system-ui, sans-serif" font-size="12" fill="#94a3b8">Domain Logic &amp; Processing</text>

  <!-- Arrow 2 -->
  <line x1="575" y1="142" x2="620" y2="142" stroke="#64748b" stroke-width="2"/>
  <polygon points="620,137 630,142 620,147" fill="#64748b"/>

  <!-- Box 3: Verification & Build -->
  <rect x="630" y="75" width="230" height="135" rx="12" fill="#1e293b" stroke="#34d399" stroke-width="1.5"/>
  <text x="650" y="110" font-family="system-ui, sans-serif" font-size="16" font-weight="700" fill="#f8fafc">3. Quality &amp; Output</text>
  <text x="650" y="140" font-family="ui-monospace, monospace" font-size="13" fill="#34d399">{html.escape(test_label)}</text>
  <text x="650" y="170" font-family="system-ui, sans-serif" font-size="12" fill="#94a3b8">Verified Build &amp; Artifacts</text>
</svg>
"""


def _language_names(raw) -> list[str]:
    """Normalise a language report to a list of names.

    Accepts the legacy ``{"Python": 78}`` mapping and the shape
    ``project_scan.py`` emits, ``[{"name": "Python", "share": 77.8}]``.
    """
    names: list[str] = []
    if isinstance(raw, dict):
        names = [str(k) for k in raw]
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("language")
                if name:
                    names.append(str(name))
    return names or ["Software"]


def generate_cli_snapshot_svg(command_str: str, output_text: str) -> str:
    lines = output_text.strip().splitlines()[:14]
    height = max(180, 90 + len(lines) * 22)
    rendered_lines = []
    y = 82
    for line in lines:
        rendered_lines.append(
            f'  <text x="28" y="{y}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13" fill="#e2e8f0">{html.escape(line[:95])}</text>'
        )
        y += 22
    lines_block = "\n".join(rendered_lines)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 {height}" width="820" height="{height}" role="img" aria-label="CLI Execution Snapshot">
  <rect width="820" height="{height}" rx="12" fill="#090d16" stroke="#334155" stroke-width="1.5"/>
  <circle cx="24" cy="22" r="6" fill="#ef4444"/>
  <circle cx="44" cy="22" r="6" fill="#f59e0b"/>
  <circle cx="64" cy="22" r="6" fill="#10b981"/>
  <text x="410" y="26" font-family="ui-monospace, monospace" font-size="12" fill="#64748b" text-anchor="middle">real-cli-output — bash</text>
  <line x1="0" y1="42" x2="820" y2="42" stroke="#1e293b" stroke-width="1"/>
  <text x="28" y="62" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13" font-weight="700" fill="#38bdf8">$ {html.escape(command_str)}</text>
{lines_block}
</svg>
"""


def main():
    parser = argparse.ArgumentParser(description="GITU Section 5: Visual Branding & CLI Snapshot Generator")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--audit-json", help="Path to JSON output from discover_and_audit.py")
    parser.add_argument("--cli-cmd", help="Optional safe CLI command to capture real terminal output SVG")
    args = parser.parse_args()

    root = Path(args.project_path).resolve()
    assets_dir = root / "docs" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    audit = {}
    if args.audit_json and Path(args.audit_json).exists():
        audit = json.loads(Path(args.audit_json).read_text(encoding="utf-8"))

    project_name = audit.get("project_name") or (audit.get("project") or {}).get("name") or root.name
    version = (audit.get("inferred_version") or (audit.get("project") or {}).get("version")
               or "0.1.0")
    description = (audit.get("inferred_description")
                   or (audit.get("project") or {}).get("description") or "")
    languages = _language_names(audit.get("languages"))
    app_types = (audit.get("application_types")
                 or [t for t in [(audit.get("project") or {}).get("app_type")] if t]
                 or ["Software Project"])
    entry_points = audit.get("entry_points") or []
    pkg_managers = (audit.get("package_managers")
                    or [p for p in [(audit.get("project") or {}).get("package_manager")] if p])
    commands = audit.get("commands") or {}

    created_files = []

    icon_path = assets_dir / "logo.svg"
    icon_path.write_text(generate_project_icon_svg(project_name, languages[0] if languages else "CODE"), encoding="utf-8")
    created_files.append(str(icon_path.relative_to(root)))

    social_path = assets_dir / "social-preview.svg"
    social_path.write_text(
        generate_social_preview_svg(project_name, description, app_types, languages, version),
        encoding="utf-8",
    )
    created_files.append(str(social_path.relative_to(root)))

    arch_path = assets_dir / "architecture.svg"
    arch_path.write_text(
        generate_architecture_svg(project_name, entry_points, pkg_managers, commands),
        encoding="utf-8",
    )
    created_files.append(str(arch_path.relative_to(root)))

    if args.cli_cmd:
        try:
            res = subprocess.run(
                args.cli_cmd, shell=True, cwd=root,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10
            )
            cli_svg = generate_cli_snapshot_svg(args.cli_cmd, res.stdout or "(command completed with no stdout)")
            cli_path = assets_dir / "cli-demo.svg"
            cli_path.write_text(cli_svg, encoding="utf-8")
            created_files.append(str(cli_path.relative_to(root)))
        except Exception as exc:
            print(f"Warning: could not capture CLI command output: {exc}")

    print(json.dumps({"project_root": str(root), "assets_created": created_files}, indent=2))


if __name__ == "__main__":
    main()
