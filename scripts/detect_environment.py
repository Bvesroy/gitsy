#!/usr/bin/env python3
"""
GITU Environment & Tool Detector
Detects the active AI coding agent environment, OS platform, available CLI tools,
Git configuration, and GitHub authentication status without assuming any preset stack.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, timeout=5):
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return False, "", str(exc)


def detect_agent_runtime():
    env = os.environ
    detected = []
    if env.get("CLAUDE_CODE") or env.get("CLAUDE_PROJECT_DIR") or Path.home().joinpath(".claude").exists():
        detected.append("claude-code")
    if env.get("GEMINI_CLI") or env.get("QWEN_SKILL_ROOT") is None and Path.home().joinpath(".gemini").exists():
        detected.append("gemini-cli")
    if env.get("OPENCODE") or Path.home().joinpath(".opencode").exists():
        detected.append("opencode")
    if env.get("QWEN_SKILL_ROOT") or Path.home().joinpath(".qwen").exists():
        detected.append("qwen-code")
    if env.get("KILO_DISABLE_SKILL_SHELL") is not None or Path.home().joinpath(".kilo").exists():
        detected.append("kilo-code")
    if Path.home().joinpath(".agents/skills").exists():
        detected.append("agent-skills-standard")
    return detected or ["generic-cli-agent"]


def detect_tools():
    binaries = [
        "git", "gh", "python3", "node", "npm", "pnpm", "yarn", "bun",
        "cargo", "rustc", "go", "swift", "xcodebuild", "cmake", "make",
        "mvn", "gradle", "dotnet", "docker", "ffmpeg", "convert",
        "playwright", "chromium", "google-chrome", "pytest", "ruff", "flake8", "shellcheck"
    ]
    found = {}
    for b in binaries:
        path = shutil.which(b)
        if path:
            ok, out, err = run_cmd([b, "--version"])
            version_line = (out or err).splitlines()[0] if (out or err) else "installed"
            found[b] = {"installed": True, "path": path, "version": version_line[:120]}
        else:
            found[b] = {"installed": False, "path": None, "version": None}
    return found


def detect_github_auth(tools):
    gh_status = {"authenticated": False, "user": None, "method": None, "details": ""}
    if tools.get("gh", {}).get("installed"):
        ok, out, err = run_cmd(["gh", "auth", "status"])
        combined = f"{out}\n{err}".strip()
        if ok:
            gh_status["authenticated"] = True
            gh_status["method"] = "gh-cli"
            gh_status["details"] = combined[:300]
            ok_u, user_out, _ = run_cmd(["gh", "api", "user", "--jq", ".login"])
            if ok_u and user_out:
                gh_status["user"] = user_out.strip()
        else:
            gh_status["details"] = combined[:300]
    if not gh_status["authenticated"]:
        for token_var in ("GH_TOKEN", "GITHUB_TOKEN"):
            if os.environ.get(token_var):
                gh_status["authenticated"] = True
                gh_status["method"] = f"env:{token_var}"
                break
    return gh_status


def detect_git_identity():
    _, name, _ = run_cmd(["git", "config", "--get", "user.name"])
    _, email, _ = run_cmd(["git", "config", "--get", "user.email"])
    return {"user_name": name or None, "user_email": email or None}


def main():
    parser = argparse.ArgumentParser(description="Detect GITU execution environment and tools.")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--output", help="Write JSON report to file path")
    args = parser.parse_args()

    tools = detect_tools()
    report = {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "detected_agent_platforms": detect_agent_runtime(),
        "git_identity": detect_git_identity(),
        "github_auth": detect_github_auth(tools),
        "tools": tools,
    }

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json or not args.output:
        print(json.dumps(report, indent=2))
    else:
        print(f"Environment report written to {args.output}")


if __name__ == "__main__":
    main()
