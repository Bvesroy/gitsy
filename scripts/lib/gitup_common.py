"""Shared helpers for the gitup scripts.

Standard library only. Imported by every gitup script through _bootstrap.py, which
forces sys.pycache_prefix into a temp dir so running gitup never writes
__pycache__ into the skill directory (skills are usually shared or read-only).

Design rules that apply to every module here:
  * no third-party imports, so the tool works on a bare macOS/Linux/Windows box;
  * no writes outside the project (except an explicit --out path);
  * every subprocess runs with a timeout and never inherits a shell;
  * secrets are never printed, only redacted previews.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Directories that are never part of "the project" for scanning purposes.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "Pods",
    ".venv", "venv", "env", ".tox", ".nox", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".gradle", ".idea", ".vs", ".vscode-test",
    "dist", "build", "target", "out", "DerivedData", ".next", ".nuxt", ".turbo",
    ".cache", ".parcel-cache", "coverage", "htmlcov", ".terraform", ".dart_tool",
    ".build", ".swiftpm", "zig-cache", "zig-out", ".stack-work", "elm-stuff",
    ".angular", ".svelte-kit", ".vercel", ".netlify", "site-packages",
    ".DS_Store", "$RECYCLE.BIN", "System Volume Information",
}

# Text-ish extensions we are willing to read for scanning.
TEXT_EXTS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc", ".json", ".jsonc", ".json5",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".xml", ".plist", ".entitlements", ".gradle", ".cmake", ".mk", ".lock",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".astro", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".m", ".mm", ".swift", ".kt", ".kts", ".java", ".scala", ".clj", ".cs",
    ".fs", ".rb", ".php", ".pl", ".lua", ".r", ".jl", ".dart", ".zig", ".nim",
    ".ex", ".exs", ".erl", ".hs", ".ml", ".sql", ".graphql", ".gql", ".proto",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".styl", ".svg",
    ".gitignore", ".gitattributes", ".npmrc", ".nvmrc", ".python-version",
    ".dockerignore", ".editorconfig", ".tool-versions", "Dockerfile", "Makefile",
    ".cff", ".txt", ".csv", ".tpl", ".tmpl", ".gotmpl", ".liquid",
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".icns", ".tiff",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".mp3", ".wav", ".flac", ".ogg",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".dmg", ".pkg", ".exe",
    ".msi", ".appimage", ".deb", ".rpm", ".whl", ".so", ".dylib", ".dll", ".a",
    ".o", ".obj", ".class", ".jar", ".pyc", ".pyo", ".woff", ".woff2", ".ttf",
    ".otf", ".eot", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".bin", ".dat", ".wasm", ".node",
}

MAX_SCAN_BYTES = 2 * 1024 * 1024  # never read more than 2 MiB of one file


# --------------------------------------------------------------------------- #
# process helpers
# --------------------------------------------------------------------------- #

@dataclass
class RunResult:
    argv: list[str]
    code: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def tail(self, n: int = 40) -> str:
        text = (self.stdout or "") + ("\n" + self.stderr if self.stderr else "")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[-n:])


def run(argv, cwd=None, timeout=120, env=None, stdin_text=None) -> RunResult:
    """Run a command without a shell. Never raises on failure."""
    started = time.time()
    merged_env = os.environ.copy()
    # Keep tool output stable and machine-parsable.
    merged_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    merged_env.setdefault("GIT_PAGER", "cat")
    merged_env.setdefault("GH_PAGER", "cat")
    merged_env.setdefault("NO_COLOR", "1")
    merged_env.setdefault("LC_ALL", "C")
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd else None,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
            shell=False,
        )
        return RunResult(list(argv), proc.returncode, proc.stdout or "",
                         proc.stderr or "", time.time() - started)
    except subprocess.TimeoutExpired:
        return RunResult(list(argv), 124, "", f"timed out after {timeout}s",
                         time.time() - started, timed_out=True)
    except FileNotFoundError:
        return RunResult(list(argv), 127, "", f"command not found: {argv[0]}",
                         time.time() - started)
    except OSError as exc:  # permission denied, exec format error, ...
        return RunResult(list(argv), 126, "", f"{type(exc).__name__}: {exc}",
                         time.time() - started)


def which(tool: str):
    return shutil.which(tool)


def tool_version(tool: str, *args) -> str:
    path = which(tool)
    if not path:
        return ""
    res = run([tool, *(args or ("--version",))], timeout=20)
    first = (res.stdout or res.stderr).strip().splitlines()
    return first[0].strip() if first else ""


# --------------------------------------------------------------------------- #
# filesystem helpers
# --------------------------------------------------------------------------- #

def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def is_binary_name(name: str) -> bool:
    return Path(name).suffix.lower() in BINARY_EXTS


def looks_binary(path: Path) -> bool:
    if is_binary_name(path.name):
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return True
    return b"\x00" in chunk


def read_text(path: Path, limit: int = MAX_SCAN_BYTES) -> str:
    try:
        with path.open("rb") as fh:
            data = fh.read(limit)
    except OSError:
        return ""
    if b"\x00" in data[:4096]:
        return ""
    return data.decode("utf-8", errors="replace")


def walk(root: Path, include_git: bool = False, max_files: int = 200000):
    """Yield files under root, skipping dependency/VCS/cache directories."""
    root = Path(root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS and not (include_git and d == ".git"):
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if name == ".DS_Store":
                continue
            yield Path(dirpath) / name
            count += 1
            if count >= max_files:
                return


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def ensure_within(target: Path, allowed: Path) -> bool:
    """True when target resolves inside allowed (guards against path escape)."""
    try:
        target = Path(target).resolve()
        allowed = Path(allowed).resolve()
    except OSError:
        return False
    return target == allowed or allowed in target.parents


# --------------------------------------------------------------------------- #
# redaction
# --------------------------------------------------------------------------- #

_SECRET_PATTERNS = [
    # provider tokens
    r"gh[pousr]_[A-Za-z0-9]{20,}",                      # GitHub
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"gho_[A-Za-z0-9]{20,}",
    r"sk-[A-Za-z0-9\-_]{20,}",                          # OpenAI/Anthropic-style
    r"sk_live_[A-Za-z0-9]{16,}",                        # Stripe live
    r"rk_live_[A-Za-z0-9]{16,}",
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",                   # Slack
    r"AKIA[0-9A-Z]{16}",                                # AWS access key id
    r"ASIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z\-_]{30,}",                         # Google API key
    r"ya29\.[0-9A-Za-z\-_]{20,}",                       # Google OAuth
    r"glpat-[A-Za-z0-9\-_]{18,}",                       # GitLab
    r"npm_[A-Za-z0-9]{30,}",                            # npm
    r"pypi-[A-Za-z0-9\-_]{30,}",
    r"SG\.[A-Za-z0-9\-_]{16,}\.[A-Za-z0-9\-_]{16,}",    # SendGrid
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp)://[^\s\"'<>]*:[^\s\"'<>@]+@",
    r"\b[Bb]earer\s+[A-Za-z0-9\-_\.=]{20,}",
]

# No inline (?i) flags: a global flag is only legal at the very start of a
# pattern, so alternatives spell out their own case as needed.
SECRET_RE = re.compile("|".join(_SECRET_PATTERNS))

ENTROPY_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                 "access_key", "private_key", "auth", "credential", "bearer")


def redact(text: str, keep: int = 4) -> str:
    def _sub(match):
        value = match.group(0)
        if value.lower().startswith("bearer"):
            return "Bearer [REDACTED]"
        head = value[:keep]
        return f"{head}…[REDACTED:{len(value)}ch]"
    return SECRET_RE.sub(_sub, text)


def redact_in_line(line: str) -> str:
    return redact(line)


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #

def git(root, *args, timeout=120) -> RunResult:
    return run(["git", *args], cwd=root, timeout=timeout)


def is_git_repo(root) -> bool:
    res = git(root, "rev-parse", "--is-inside-work-tree")
    return res.ok and res.stdout.strip() == "true"


def git_root(path) -> Path | None:
    res = git(path, "rev-parse", "--show-toplevel")
    if res.ok and res.stdout.strip():
        return Path(res.stdout.strip())
    return None


def default_branch(root) -> str:
    res = git(root, "symbolic-ref", "--short", "HEAD")
    if res.ok and res.stdout.strip():
        return res.stdout.strip()
    res = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return res.stdout.strip() or "main"


def dirty_paths(root) -> list[str]:
    res = git(root, "status", "--porcelain=v1", "-z")
    if not res.ok:
        return []
    out = res.stdout.split("\x00")
    paths = []
    for entry in out:
        if len(entry) > 3:
            paths.append(entry[3:])
    return paths


# --------------------------------------------------------------------------- #
# json / report helpers
# --------------------------------------------------------------------------- #

CHECKLISTS = ("project", "security", "docs", "presentation", "release", "verify")


@dataclass
class Finding:
    checklist: str
    id: str
    severity: str          # blocker | high | medium | low | info
    title: str
    detail: str = ""
    evidence: list = field(default_factory=list)   # ["path:line", ...]
    fix: str = ""
    autofix: str = ""      # stays empty unless gitup can repair it safely

    def as_dict(self):
        return asdict(self)


SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def sort_findings(findings):
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.checklist, f.id))


def summarize(findings) -> dict:
    counts = {k: 0 for k in SEVERITY_ORDER}
    for f in findings:
        counts[f.severity if f.severity in counts else "info"] += 1
    return counts


def emit(obj, out_path: str | None = None, indent: int = 2) -> str:
    """Write JSON to stdout and/or a file. Stdout stays parseable (no noise)."""
    text = json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=False)
    if out_path:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")
    return text


def die(message: str, code: int = 2):
    """Fail with a machine-readable object on stdout, then exit.

    stdout carries the contract: an agent captures one stream and parses it,
    whether the run succeeded or failed. stderr stays for human diagnostics.
    """
    sys.stdout.write(json.dumps({"error": message}) + "\n")
    sys.exit(code)


class JsonArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that reports misuse as JSON, like every other failure.

    An agent branches on exit codes and parses stdout/stderr as JSON. If a
    missing required argument produced argparse's human usage text, that agent
    would hit a non-JSON string and have to special-case it. Every failure path
    in this toolchain speaks the same shape, so this one does too.
    """

    def error(self, message):
        sys.stdout.write(json.dumps({
            "error": message,
            "code": "usage",
            "usage": self.format_usage().strip(),
            "hint": "Run with --help for the full option list.",
        }) + "\n")
        sys.exit(2)

    def exit(self, status=0, message=None):
        # --help is a human asking on purpose: keep it readable on stdout.
        # Only failures are forced into JSON.
        if status == 0:
            if message:
                sys.stdout.write(message)
            sys.exit(0)
        super().exit(status, message)


def parser(*args, **kwargs) -> JsonArgumentParser:
    """Build an ArgumentParser that honours the JSON error contract."""
    kwargs.setdefault("add_help", True)
    return JsonArgumentParser(*args, **kwargs)


def load_json(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def glob_any(patterns, name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)
