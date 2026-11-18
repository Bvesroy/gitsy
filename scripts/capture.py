#!/usr/bin/env python3
"""gitup capture.py - screenshot a real application, or say why it cannot.

Presentation quality comes from showing the actual product. This script:

  1. detects the project's app type and picks a capture strategy;
  2. checks whether the required tool is actually installed;
  3. runs the capture and verifies the output is a real, non-blank image;
  4. reports honestly, including "could not capture" with the reason.

Strategies
  web-local     serve/point at a local dev URL, screenshot with Playwright CLI
  web-built     open the built index.html directly, screenshot with Playwright
  macOS-window  launch the .app and use `screencapture -l <windowid>`
  cli-output    render real terminal output into an SVG card (no fake UI)
  manual        no automatable path: returns a precise shot list instead

Never fabricates a screenshot. A conceptual mockup must be labelled as such by
whoever writes it; capture.py only produces evidence.

Usage:
  python3 capture.py --project . --kind web-local --url http://localhost:3000 \
      --out docs/assets/screenshots [--name main] [--checks]
  python3 capture.py --project . --probe          # what could we capture, and how
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

from gitup_common import die, emit, run, which, parser

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_dimensions(path: Path):
    try:
        data = path.read_bytes()[:32]
    except OSError:
        return None
    if not data.startswith(PNG_SIG) or len(data) < 24:
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def is_blank(path: Path) -> bool:
    """A real screenshot has more than one colour; a failed capture does not."""
    try:
        import zlib
        raw = path.read_bytes()
    except OSError:
        return True
    if len(raw) < 512:
        return True
    # crude but dependency-free: a screenshot compresses far worse than a
    # flat-colour frame, so compare the compressed ratio against the size.
    dims = png_dimensions(path)
    if not dims:
        return True
    w, h = dims
    pixels = max(w * h, 1)
    return (len(raw) / pixels) < 0.02


def probe(root: Path) -> dict:
    from project_scan import scan
    info = scan(root)
    app_type = info["project"]["app_type"]
    tools = {"playwright": bool(which("playwright") or which("npx")),
             "screencapture": bool(which("screencapture")),
             "sips": bool(which("sips")),
             "ffmpeg": bool(which("ffmpeg")),
             "open": bool(which("open")),
             "osascript": bool(which("osascript"))}
    apps = sorted(str(p) for p in root.glob("**/*.app") if "DerivedData" not in str(p))[:5]
    build_dirs = sorted(str(p) for p in root.glob("build/*.app"))[:3]
    playwright_browser = _playwright_browser_available()

    strategies = []
    if "web" in app_type:
        strategies.append({"kind": "web-local", "ready": tools["playwright"] and playwright_browser,
                           "why": "serve the app, screenshot the running UI",
                           "blocked_by": "" if playwright_browser else
                           "playwright browser is not installed: run `npx playwright install chromium`"})
    if "macos" in app_type or "desktop" in app_type:
        strategies.append({"kind": "macos-window",
                           "ready": tools["screencapture"] and bool(apps or build_dirs),
                           "why": "launch the built .app and capture its window",
                           "blocked_by": "" if (apps or build_dirs) else
                           "no built .app found: build first (xcodebuild / cargo tauri build)"})
    if "cli" in app_type or "service" in app_type or (root / "Makefile").exists():
        strategies.append({"kind": "cli-output", "ready": True,
                           "why": "render real command output as an SVG card"})
    strategies.append({"kind": "manual", "ready": True,
                       "why": "produce a shot list for a human with the app open"})
    return {
        "project": str(root),
        "app_type": app_type,
        "tools": tools,
        "playwright_browser": playwright_browser,
        "built_apps": apps + build_dirs,
        "strategies": strategies,
        "recommended": next((s["kind"] for s in strategies if s["ready"]), "manual"),
    }


def _playwright_browser_available() -> bool:
    if not which("npx"):
        return False
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    alt = Path.home() / ".cache" / "ms-playwright"
    for base in (cache, alt):
        if base.exists() and any(base.iterdir()):
            return True
    return False


def capture_web(root: Path, url: str, out_dir: Path, name: str,
                viewport: str = "1440,900", full_page: bool = False,
                wait_ms: int = 1200) -> dict:
    if not which("npx"):
        return {"ok": False, "strategy": "web-local",
                "error": "npx not found; install Node.js or capture manually"}
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.png"
    argv = ["npx", "--yes", "playwright", "screenshot",
            f"--viewport-size={viewport}", "--wait-for-timeout", str(wait_ms)]
    if full_page:
        argv.append("--full-page")
    argv += [url, str(target)]
    res = run(argv, cwd=root, timeout=240)
    return _finish_capture(target, "web-local", res)


def capture_macos_window(root: Path, app_path: str, out_dir: Path, name: str,
                         wait: int = 6) -> dict:
    if not which("screencapture"):
        return {"ok": False, "strategy": "macos-window",
                "error": "screencapture only exists on macOS"}
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.png"
    app = Path(app_path)
    if not app.exists():
        return {"ok": False, "strategy": "macos-window", "error": f"no app at {app}"}
    opened = run(["open", "-a", str(app)], timeout=60)
    time.sleep(wait)
    window_id = _front_window_id()
    if window_id:
        res = run(["screencapture", "-x", "-o", "-l", window_id, str(target)], timeout=90)
    else:
        res = run(["screencapture", "-x", "-o", str(target)], timeout=90)
    return _finish_capture(target, "macos-window", res,
                           extra={"opened": opened.ok, "window_id": window_id})


def _front_window_id() -> str:
    if not which("osascript"):
        return ""
    script = ('tell application "System Events" to get id of first window of '
              '(first application process whose frontmost is true)')
    res = run(["osascript", "-e", script], timeout=30)
    return res.stdout.strip() if res.ok and res.stdout.strip().isdigit() else ""


def _finish_capture(target: Path, strategy: str, res, extra: dict | None = None) -> dict:
    result = {"strategy": strategy, "path": str(target), **(extra or {})}
    if not res.ok:
        result.update({"ok": False, "error": (res.stderr or res.stdout).strip()[:400]})
        return result
    if not target.exists():
        result.update({"ok": False, "error": "tool reported success but wrote no file"})
        return result
    dims = png_dimensions(target)
    blank = is_blank(target)
    result.update({"ok": bool(dims) and not blank, "dimensions": dims,
                   "bytes": target.stat().st_size, "blank": blank})
    if blank:
        result["error"] = ("capture produced a blank/solid frame; the app probably had not "
                           "rendered yet or the window was not front-most")
    return result


def cli_card(root: Path, command: str, out_dir: Path, name: str = "cli") -> dict:
    """Render real command output as an SVG. It is a transcript, not a mockup."""
    from gitup_common import redact
    res = run(["/bin/sh", "-c", command], cwd=root, timeout=120)
    output = redact((res.stdout or "") + (res.stderr or "")).strip().splitlines()[:28]
    if not output:
        return {"ok": False, "strategy": "cli-output",
                "error": f"`{command}` produced no output (exit {res.code})"}
    width, line_h, pad = 880, 22, 24
    height = pad * 2 + line_h * (len(output) + 1)
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))  # noqa: E731
    rows = [f'<text x="{pad}" y="{pad + line_h}" class="p">{esc("$ " + command)}</text>']
    for i, line in enumerate(output, start=2):
        rows.append(f'<text x="{pad}" y="{pad + line_h * i}" class="o">{esc(line)}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Terminal output of {esc(command)}">
  <rect width="{width}" height="{height}" rx="10" fill="#0d1117"/>
  <circle cx="26" cy="18" r="6" fill="#ff5f57"/><circle cx="48" cy="18" r="6" fill="#febc2e"/><circle cx="70" cy="18" r="6" fill="#28c840"/>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="14" xml:space="preserve">
    <style>.p{{fill:#7ee787;font-weight:600}}.o{{fill:#c9d1d9}}</style>
{chr(10).join("    " + r for r in rows)}
  </g>
</svg>
'''
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.svg"
    target.write_text(svg, encoding="utf-8")
    return {"ok": True, "strategy": "cli-output", "path": str(target),
            "bytes": len(svg), "lines": len(output), "exit_code": res.code,
            "note": "Real command output, not a mockup."}


def shot_list(info: dict) -> list[dict]:
    """What a human should capture, phrased as concrete shots."""
    app_type = info.get("app_type", "unknown")
    base = [
        {"shot": "main", "what": "The primary screen at its normal size, real data",
         "why": "This is the screenshot that appears right under the title"},
        {"shot": "core-action", "what": "The main thing the app does, mid-use",
         "why": "Shows the value, not just the shell"},
        {"shot": "settings", "what": "Configuration or preferences",
         "why": "Signals that real workflows were considered"},
    ]
    if "mobile" in app_type:
        base.append({"shot": "device", "what": "One phone-sized frame in a device shell",
                     "why": "Mobile expectations are set by the frame"})
    if "cli" in app_type:
        base.append({"shot": "terminal", "what": "A real invocation and its output",
                     "why": "CLI users judge by the transcript"})
    if "library" in app_type:
        base = [{"shot": "usage", "what": "A short, correct code sample in its editor",
                 "why": "Libraries sell on the first snippet"}]
    return base


def main(argv=None):
    ap = parser(description="capture real application screenshots")
    ap.add_argument("--project", required=True)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--kind", choices=["web-local", "macos-window", "cli-output", "manual"],
                    default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--app", default="")
    ap.add_argument("--command", default="")
    ap.add_argument("--out", default="docs/assets/screenshots")
    ap.add_argument("--name", default="main")
    ap.add_argument("--viewport", default="1440,900")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--out-json", default="")
    args = ap.parse_args(argv)

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    info = probe(root)
    out_dir = (root / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    kind = args.kind or ("probe" if args.probe else info["recommended"])
    if kind == "probe" or args.probe:
        info["shot_list"] = shot_list(info)
        emit(info, args.out_json or None)
        return 0
    if kind == "web-local":
        if not args.url:
            die("web capture needs --url (e.g. http://localhost:3000)")
        result = capture_web(root, args.url, out_dir, args.name, args.viewport, args.full_page)
    elif kind == "macos-window":
        if not args.app:
            die("macos capture needs --app path/to/App.app")
        result = capture_macos_window(root, args.app, out_dir, args.name)
    elif kind == "cli-output":
        if not args.command:
            die("cli capture needs --command \"your-cli --help\"")
        result = cli_card(root, args.command, out_dir, args.name)
    else:
        result = {"ok": False, "strategy": "manual", "shot_list": shot_list(info),
                  "error": "no automatable capture path for this project"}
    result["probe"] = {"app_type": info["app_type"], "recommended": info["recommended"]}
    result["shot_list"] = shot_list(info)
    emit(result, args.out_json or None)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
