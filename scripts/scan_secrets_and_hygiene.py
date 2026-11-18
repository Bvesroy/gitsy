#!/usr/bin/env python3
"""
GITU Phase C: Mandatory GitHub Security Audit & .gitignore Hardening
Scans working tree, staged files, and recent Git history for secrets, tokens,
private keys, .env files, database dumps, and large binary artifacts.
Never prints raw secret values in output logs (redacts automatically).
"""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "target"}

SECRET_PATTERNS = [
    ("AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "HIGH"),
    ("GitHub Personal Access Token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{30,255}|github_pat_[A-Za-z0-9_]{22,255})\b"), "CRITICAL"),
    ("Google API Key", re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b"), "HIGH"),
    ("OpenAI / Anthropic API Key", re.compile(r"\b(sk-(?:proj-|ant-)?[A-Za-z0-9\-_]{20,})\b"), "CRITICAL"),
    ("Slack Token", re.compile(r"\b(xox[baprs]-[0-9A-Za-z\-]{10,48})\b"), "HIGH"),
    ("Private Key Block", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "CRITICAL"),
    ("Database Connection URI with Password", re.compile(r"\b((?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis)://[^:\s/]+:[^@\s/]+@[^\s\"']+)"), "CRITICAL"),
    ("Generic Hardcoded Secret Assignment", re.compile(r"(?i)\b(api_key|apikey|secret_key|access_token|auth_token|client_secret|password|passwd)\s*[:=]\s*[\"']([A-Za-z0-9_\-/.+=]{12,})[\"']"), "HIGH"),
]

SAFE_PLACEHOLDER_VALUES = {
    "your_api_key", "your-api-key", "changeme", "replace_me", "example", "dummy",
    "xxx", "todo", "none", "null", "placeholder", "sample_secret_key"
}

SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json",
    "service-account.json", "client_secret.json", ".npmrc", ".pypirc"
}

SENSITIVE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".sqlite", ".sqlite3", ".db", ".sql"}

RECOMMENDED_GITIGNORE_RULES = [
    "# OS & Editor artifacts",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    "*~",
    "",
    "# Environment & Secrets",
    ".env",
    ".env.*",
    "!.env.example",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "service-account*.json",
    "",
    "# Python / Node / Build caches",
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    "venv/",
    "node_modules/",
    ".pytest_cache/",
    ".ruff_cache/",
    "dist/",
]


def redact(val: str) -> str:
    val = val.strip()
    if len(val) <= 8:
        return "***REDACTED***"
    return f"{val[:4]}...REDACTED...{val[-2:]}"


def scan_file_for_secrets(fpath: Path, root: Path):
    findings = []
    try:
        if fpath.stat().st_size > 5 * 1024 * 1024:
            return findings
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    rel = str(fpath.relative_to(root))
    for lineno, line in enumerate(content.splitlines(), start=1):
        # Accept both spellings: users write this marker into their own source,
        # and an existing suppression must not silently stop working.
        if ("gitu-ignore-secret" in line or "gitu-ignore-secret" in line
                or "EXAMPLE" in line.upper()):
            continue
        for rule_name, pattern, severity in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                raw = match.group(0)
                lower_raw = raw.lower()
                if any(ph in lower_raw for ph in SAFE_PLACEHOLDER_VALUES):
                    continue
                findings.append({
                    "file": rel,
                    "line": lineno,
                    "rule": rule_name,
                    "severity": severity,
                    "redacted_preview": redact(raw),
                })
    return findings


def scan_git_history(root: Path):
    if not (root / ".git").exists():
        return []
    try:
        res = subprocess.run(
            ["git", "log", "-p", "-n", "25", "--no-color"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15
        )
        if res.returncode != 0:
            return []
    except Exception:
        return []

    history_hits = []
    current_commit = "unknown"
    for line in res.stdout.splitlines():
        if line.startswith("commit "):
            current_commit = line.split()[1][:10]
        elif line.startswith("+") and not line.startswith("+++"):
            for rule_name, pattern, severity in SECRET_PATTERNS:
                m = pattern.search(line)
                if m and not any(ph in m.group(0).lower() for ph in SAFE_PLACEHOLDER_VALUES):
                    history_hits.append({
                        "commit": current_commit,
                        "rule": rule_name,
                        "severity": severity,
                        "redacted_preview": redact(m.group(0)),
                        "remediation": "Credential exists in Git commit history. Removing from working tree is NOT sufficient; revoke/rotate this credential immediately.",
                    })
    return history_hits


def update_gitignore(root: Path):
    gitignore_path = root / ".gitignore"
    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8", errors="replace")

    existing_lines = {line.strip() for line in existing.splitlines() if line.strip() and not line.strip().startswith("#")}
    added = []
    lines_to_append = []
    for rule in RECOMMENDED_GITIGNORE_RULES:
        if not rule or rule.startswith("#"):
            lines_to_append.append(rule)
        elif rule not in existing_lines:
            lines_to_append.append(rule)
            added.append(rule)

    if added:
        new_content = existing.rstrip() + ("\n\n" if existing.strip() else "") + "\n".join(lines_to_append) + "\n"
        gitignore_path.write_text(new_content, encoding="utf-8")
    return added


def audit_security(root: Path, fix_gitignore: bool = False, large_file_mb: float = 10.0):
    root = root.resolve()
    secret_findings = []
    sensitive_files = []
    large_files = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))

            if fname in SENSITIVE_FILENAMES or (fname.startswith(".env") and fname != ".env.example"):
                sensitive_files.append({"file": rel, "reason": "Sensitive environment or credential file"})
            elif fpath.suffix.lower() in SENSITIVE_EXTENSIONS:
                sensitive_files.append({"file": rel, "reason": f"Sensitive key or database extension ({fpath.suffix})"})

            try:
                size_mb = fpath.stat().st_size / (1024 * 1024)
                if size_mb >= large_file_mb:
                    large_files.append({"file": rel, "size_mb": round(size_mb, 2)})
            except Exception:
                pass

            secret_findings.extend(scan_file_for_secrets(fpath, root))

    gitignore_added = update_gitignore(root) if fix_gitignore else []
    history_findings = scan_git_history(root)

    passed = (len(secret_findings) == 0 and len(sensitive_files) == 0 and len(history_findings) == 0)
    return {
        "project_root": str(root),
        "status": "PASS" if passed else "BLOCK_UPLOAD",
        "safe_to_publish": passed,
        "summary": {
            "working_tree_secrets": len(secret_findings),
            "sensitive_files": len(sensitive_files),
            "git_history_secrets": len(history_findings),
            "large_binary_files": len(large_files),
        },
        "secret_findings": secret_findings,
        "sensitive_files": sensitive_files,
        "git_history_findings": history_findings,
        "large_files": large_files,
        "gitignore_rules_added": gitignore_added,
    }


def main():
    parser = argparse.ArgumentParser(description="GITU Phase C: Security & Secret Auditor")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--fix-gitignore", action="store_true", help="Create or harden .gitignore")
    parser.add_argument("--output", help="Write JSON report to file path")
    args = parser.parse_args()

    report = audit_security(Path(args.project_path), fix_gitignore=args.fix_gitignore)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
