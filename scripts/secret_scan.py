#!/usr/bin/env python3
"""gitup secret_scan.py - Phase C: never publish a credential.

Scans the working tree, the git index, and (optionally) git history for
credentials, private keys, database dumps, bulky personal files and dangerous
ignore gaps. Every hit is redacted before it leaves the process: the report
carries a 4-character prefix, the length, and the file:line, never the secret.

Exit codes:
  0  clean, or only low/info findings
  1  high-severity findings (review before publishing)
  2  blocker-severity findings (do not publish until resolved)

Usage:
  python3 secret_scan.py --project ~/Developer/MyProject [--out security.json]
                         [--history] [--history-depth 200] [--staged-only]
                         [--include-tests]
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import fnmatch
import re
import sys
from pathlib import Path

from gitup_common import (
    Finding,
    die,
    emit,
    git,
    is_git_repo,
    looks_binary,
    redact,
    parser,
    read_text,
    rel,
    run,
    sha256_file,
    sort_findings,
    summarize,
    walk,
    which,
)

# --------------------------------------------------------------------------- #
# rule tables
# --------------------------------------------------------------------------- #

# (id, severity, title, regex, extensions-or-None, fix)
CONTENT_RULES = [
    ("secret.private-key", "blocker", "Private key material in the repository",
     re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"), None,
     "Delete the key, rotate it, and keep it outside the repo. A committed key is compromised even if deleted later."),
    ("secret.github-token", "blocker", "GitHub token in a tracked file",
     re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"), None,
     "Revoke the token at https://github.com/settings/tokens, then purge it from the file and the history."),
    ("secret.aws-key", "blocker", "AWS access key id in a tracked file",
     re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None,
     "Deactivate the key in IAM, rotate, and load credentials from the environment instead."),
    ("secret.provider-key", "blocker", "Third-party API key in a tracked file",
     re.compile(r"\bsk-(?:live|proj|ant)?[-_A-Za-z0-9]{20,}|sk_live_[A-Za-z0-9]{16,}|rk_live_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z\-_]{30,}|glpat-[A-Za-z0-9\-_]{18,}|npm_[A-Za-z0-9]{30,}|SG\.[A-Za-z0-9\-_]{16,}\.[A-Za-z0-9\-_]{16,}"), None,
     "Revoke and rotate the key with the provider; store it in a secret manager or an untracked .env file."),
    ("secret.connection-string", "blocker", "Database/service URL with embedded password",
     re.compile(r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp|amqps)://[^\s\"'<>]*:[^\s\"'<>@]+@"), None,
     "Rotate the database password and build the URL from environment variables at runtime."),
    ("secret.jwt-or-bearer", "high", "Hardcoded bearer token or JWT",
     re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), None,
     "Move the token into configuration/secret storage; rotate it if it can still authenticate."),
    ("secret.pem-inline", "blocker", "Certificate/key block in a tracked file",
     re.compile(r"-----BEGIN (?:CERTIFICATE|EC PARAMETERS|OPENSSH PRIVATE KEY)-----"), None,
     "Review whether the material is a public certificate (fine) or a private credential (rotate it)."),
]

# key=value style assignments, judged by key name and value shape
ASSIGN_RE = re.compile(
    r"""(?ix)
    (?P<key>[A-Za-z0-9_.\-]{2,40})
    \s*[:=]\s*
    (?P<q>["']?)
    (?P<val>[^\s"'#,;]{8,200})
    """
)
SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[._\-])(?:pass(?:word|wd)?|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token|credentials?|session[_-]?key|"
    r"signing[_-]?key|encryption[_-]?key|db[_-]?pass)(?:$|[._\-])"
)
PLACEHOLDER_RE = re.compile(
    r"(?i)^(?:x+|\*+|\.+|changeme|change_me|placeholder|example|sample|test|dummy|fake|"
    r"your[_-].*|todo|null|none|true|false|0+|1234.*|<.*>|\$\{.*\}|\$\(.*\)|%\(.*\)s|"
    r"""redacted|removed|n/a|undefined|"{2}|'{2}|\[.*\])$"""
)

# file-level rules
SENSITIVE_FILE_PATTERNS = [
    ("file.env", "blocker", ".env file would be published",
     re.compile(r"^(?:\.env(?:\..+)?|env\.(?:local|dev|prod|production|staging))$", re.I),
     ".env files hold live credentials. Add the file to .gitignore and ship a .env.example with keys only."),
    ("file.private-key", "blocker", "Private key file in the tree",
     re.compile(r".*\.(?:pem|key|p12|pfx|jks|keystore|ppk)$", re.I),
     "Keep signing keys out of the repository (or in CI secrets); rotate anything that was committed."),
    ("file.ssh-key", "blocker", "SSH key file in the tree",
     re.compile(r"^(?:id_rsa|id_dsa|id_ecdsa|id_ed25519)(?:\.pub)?$", re.I),
     "SSH private keys must never enter a repository. Rotate the key."),
    ("file.credentials", "high", "Credential store file in the tree",
     re.compile(r"^(?:credentials|secrets?|\.netrc|\.pgpass|\.npmrc|\.pypirc|\.dockercfg|auth\.json|tokens?\.json|service[-_]?account.*\.json|.*\.kdbx)$", re.I),
     "Keep credential files untracked and document the variables your app needs instead."),
    ("file.db-dump", "high", "Database dump or data file in the tree",
     re.compile(r".*\.(?:sql|sqlite|sqlite3|db|dump|bak|mdb|bson)$", re.I),
     "Dumps usually contain personal data. Remove them, and generate fixtures instead."),
    ("file.archive-large", "medium", "Large archive in the tree",
     re.compile(r".*\.(?:zip|tar|tgz|tar\.gz|7z|rar|iso|dmg)$", re.I),
     "Commit source, not build output. Delete the archive and attach it to a GitHub release instead."),
    ("file.os-junk", "low", "OS metadata file",
     re.compile(r"^(?:\.DS_Store|Thumbs\.db|desktop\.ini|\.Spotlight-V100|\.Trashes|\.fseventsd|Icon\r)$", re.I),
     "Ignore these (see reference gitignore presets)."),
    ("file.ide-junk", "low", "Editor/project state file",
     re.compile(r"^(?:\.idea|\.vscode/.*|.*\.swp|.*\.swo|\.project|\.classpath|xcuserdata/.*|.*\.xcuserstate)$", re.I),
     "Ignore per-user editor state; commit only shared settings you intend to support."),
    ("file.build-output", "medium", "Build output committed to source control",
     re.compile(r"^(?:dist|build|out|target|DerivedData|node_modules|\.next|\.nuxt|vendor)/", re.I),
     "Build output does not belong in git; produce it in CI or a release."),
    ("file.cache-junk", "medium", "Cache or bytecode in the repository",
     re.compile(r"(?:^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|"
                r"\.gradle|\.idea|\.vscode/.*|\.next|\.nuxt|\.turbo|\.cache)(?:/|$)"
                r"|.*\.(?:pyc|pyo|class|o|obj|pdb)$", re.I),
     "Bytecode and tool caches are generated: ignore them and `git rm -r --cached` them."),
    ("file.dependency-dir", "high", "Installed dependencies committed to the repository",
     re.compile(r"(?:^|/)(?:node_modules|vendor/bundle|site-packages|Pods|bower_components)/", re.I),
     "Dependencies belong in a lockfile, not in the tree. Remove them from the index."),
    ("file.personal", "medium", "Possibly personal file",
     re.compile(r"^(?:.*\.(?:pages|numbers|key|sketch|psd|ai|heic|mov)$|Desktop/.*|Downloads/.*)", re.I),
     "Confirm this file is meant to be public; personal documents usually are not."),
]

# Gitignore gaps worth naming explicitly.
GITIGNORE_EXPECTATIONS = [
    (".DS_Store", ".DS_Store"),
    (".env", ".env"),
    (".venv/", "venv/|.venv/|env/"),
    ("node_modules/", "node_modules/"),
    ("__pycache__/", "__pycache__/"),
    ("dist/", "dist/|build/"),
]

ALLOWLIST_NAMES = {
    ".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults",
    "sample.env", "example.env", "env.example",
}
ALLOWLIST_PATH_PARTS = {
    "test", "tests", "__tests__", "spec", "specs", "fixtures", "testdata",
    "test_data", "examples", "example", "samples", "docs", "mocks", "__mocks__",
    "vendor", "third_party", "third-party", "node_modules",
}
# Files whose whole job is to describe secrets.
SECRET_DETECTOR_NAMES = re.compile(
    r"(?i)(?:secret|credential|scanner|detector|leak|redact|sanitiz|audit|"
    r"checks?|patterns?|rules?|globals?|_test|test_|conftest)"
)


def is_allowlisted(relpath: str, value: str = "") -> str:
    """Return a reason string when a hit is plausibly safe, else ''."""
    p = Path(relpath)
    if p.name.lower() in ALLOWLIST_NAMES:
        return "example/template file"
    if p.name.lower().endswith((".md", ".mdx", ".rst", ".txt", ".adoc")):
        return "documentation"
    parts = {part.lower() for part in p.parts}
    if parts & ALLOWLIST_PATH_PARTS:
        return "test/fixture/vendor path"
    if SECRET_DETECTOR_NAMES.search(p.stem):
        return "file implements a secret detector"
    if value and PLACEHOLDER_RE.match(value.strip().strip("\"'")):
        return "placeholder value"
    if value and ("${" in value or "$(" in value or "%(" in value or "{{" in value):
        return "runtime-interpolated value"
    return ""


def _gitignore_covers(entries: list[str], target: str) -> bool:
    """Does any .gitignore line actually cover `target`?

    Substring search produced false positives ("dist/" matched "dist-Mac/"),
    so rules are matched with git's own semantics: leading slash anchors to the
    repo root, a trailing slash means directory-only, and a bare directory name
    covers everything beneath it at any depth.
    """
    target = target.strip("/")
    base = target.rsplit("/", 1)[-1]
    for raw in entries:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        line = line.rstrip("/")
        anchored = line.startswith("/")
        line = line.lstrip("/")
        if not line:
            continue
        if "/" in line or anchored:
            if fnmatch.fnmatch(target, line) or target == line or target.startswith(line + "/"):
                return True
        else:
            if fnmatch.fnmatch(base, line) or any(
                    fnmatch.fnmatch(part, line) for part in target.split("/")):
                return True
    return False


def scan_gitignore(root: Path) -> dict:
    path = root / ".gitignore"
    text = read_text(path)
    entries = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    missing = [label for label, target in GITIGNORE_EXPECTATIONS
               if not _gitignore_covers(entries, target)]
    return {"exists": path.exists(), "entries": len(entries), "missing_common": missing}


def tracked_files(root: Path) -> list[Path]:
    if not is_git_repo(root):
        return []
    res = git(root, "ls-files", "-z")
    if not res.ok:
        return []
    return [root / p for p in res.stdout.split("\x00") if p]


def staged_files(root: Path) -> list[Path]:
    if not is_git_repo(root):
        return []
    res = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [root / p for p in res.stdout.split("\x00") if p]


def untracked_files(root: Path) -> list[Path]:
    if not is_git_repo(root):
        return []
    res = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return [root / p for p in res.stdout.split("\x00") if p]


def scan_file(root: Path, path: Path, findings: list, source: str = "worktree") -> None:
    rp = rel(root, path)
    name = path.name

    for rule_id, sev, title, pattern, fix in SENSITIVE_FILE_PATTERNS:
        if pattern.search(rp.replace("\\", "/")):
            if rule_id in ("file.os-junk", "file.ide-junk", "file.build-output"):
                # only a problem when actually tracked
                if source == "tracked":
                    findings.append(Finding("security", rule_id, sev, f"{title}: {rp}",
                                            f"Tracked file matches {rule_id}.", [f"{rp}:1"], fix))
                continue
            if is_allowlisted(rp):
                continue
            findings.append(Finding("security", rule_id, sev, f"{title}: {rp}",
                                    f"{name} is publishable and matches {rule_id}.",
                                    [f"{rp}:1"], fix))

    if looks_binary(path):
        return
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return
    except OSError:
        return
    text = read_text(path)
    if not text:
        return
    if LITERAL_TOKEN_RE.search(text) and SECRET_DETECTOR_NAMES.search(path.stem):
        # The file is a detector with example patterns embedded; still scan
        # assignments, but skip literal-token rules for readability.
        skip_literal_rules = True
    else:
        skip_literal_rules = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > 4000:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "<!--")) and "-----BEGIN" not in stripped:
            # comments still matter for keys/passwords pasted by accident
            if not SENSITIVE_KEY_RE.search(stripped):
                continue
        if not skip_literal_rules:
            for rule_id, sev, title, pattern, _exts, fix in CONTENT_RULES:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    reason = is_allowlisted(rp, value)
                    findings.append(Finding(
                        "security", rule_id, sev if not reason else "info",
                        f"{title} in {rp}:{lineno}",
                        ("Possible false positive: " + reason) if reason else
                        f"{value[:6]}…[{len(value)} chars, redacted]",
                        [f"{rp}:{lineno}"], fix))
        for match in ASSIGN_RE.finditer(line):
            key, value = match.group("key"), match.group("val")
            if not SENSITIVE_KEY_RE.search(key):
                continue
            if key.lower().startswith(("import", "from", "require", "export")):
                continue
            # A name like SECRET_RE / TOKEN_PATTERN holds a regex or a symbol,
            # not a credential. Likewise anything assigned by calling a builder.
            if _NAME_IS_CODE_RE.search(key):
                continue
            if re.match(r"\s*(?:re\.|regex|Regex|Pattern|Path|urlparse|"
                        r"\w+\.[A-Za-z_]+\()", value):
                continue
            if not _value_looks_secret(value, key):
                continue
            reason = is_allowlisted(rp, value)
            findings.append(Finding(
                "security", "secret.assignment",
                "info" if reason else "high",
                f"Hardcoded value for '{key}' in {rp}:{lineno}",
                ("Possible false positive: " + reason) if reason else
                f"{value[:4]}…[{len(value)} chars, redacted]",
                [f"{rp}:{lineno}"],
                "Read this value from the environment or a secret manager; rotate it if it was ever real."))


# Identifiers that name a piece of code rather than a credential value.
_NAME_IS_CODE_RE = re.compile(
    r"(?i)(?:_RE|_REGEX|_PATTERN|_RE_|_CLASS|_TYPE|_HINT|_LIST|_NAMES|_HINTS|"
    r"_ENV|_URL_RE|_FIELD|_KEY_NAME|_HEADER)$")


# Literal tokens that strongly suggest the file already *documents* secrets.
LITERAL_TOKEN_RE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}")


# Words that make a lowercase value read as prose rather than as a password.
_PROSE_WORDS = re.compile(
    r"(?i)^(?:the|a|an|true|false|none|default|empty|auto|enabled|disabled|"
    r"utf-?8|ascii|localhost|127\.0\.0\.1|read-?only|read-?write)$")

# Identifiers a bare word legitimately holds when it is assigned to a
# secret-sounding name. Anything else that is long and unquoted-suspicious is
# reported as low confidence rather than ignored.
_PROSEY_VALUE = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")


def _value_looks_secret(value: str, key: str = "") -> bool:
    """Heuristic: does this assigned literal look like a real credential?

    Two paths:
      * mixed character classes (the classic shape of a key or token), or
      * a long lowercase run assigned to a sensitive key name - which is how
        people actually write passwords ("hunter2", "correcthorsebattery").
    Placeholders, environment lookups, paths and prose are excluded on both.
    """
    v = value.strip().strip("\"'`")
    if len(v) < 8 or PLACEHOLDER_RE.match(v):
        return False
    if any(tok in v for tok in ("${", "$(", "%(", "{{", "os.environ", "process.env",
                                "getenv", "System.getenv", "settings.", "config[")):
        return False
    if v.startswith(("http://", "https://", "/", "./", "../")) and ":@" not in v:
        return False
    classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes >= 2 and not _PROSEY_VALUE.match(v):
        return True
    # Single-class value: only interesting when the key name says it is a secret,
    # the value is long enough to not be a flag, and it is not obviously prose.
    if SENSITIVE_KEY_RE.search(key or "") and len(v) >= 12:
        return not _PROSE_WORDS.match(v)
    return False


def scan_history(root: Path, depth: int, findings: list) -> dict:
    if not is_git_repo(root):
        return {"scanned": False, "reason": "not a git repository"}
    revs = git(root, "rev-list", f"--max-count={depth}", "HEAD")
    if not revs.ok:
        return {"scanned": False, "reason": "no commits"}
    rev_list = revs.stdout.split()
    grep = git(root, "grep", "-I", "-n", "-E",
               r"gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk_live_[A-Za-z0-9]{16,}",
               *rev_list, timeout=180)
    added = 0
    for line in grep.stdout.splitlines():
        if added >= 50:
            break
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        commit, path, lineno, text = parts
        findings.append(Finding(
            "security", "secret.history", "high",
            f"Secret-like string in git history at {path}:{lineno}",
            f"Commit {commit[:10]}: {redact(text.strip())[:80]}",
            [f"{path}:{lineno}"],
            "History is public once pushed. Rotate the credential; purging history needs "
            "git-filter-repo and force-push authorization."))
        added += 1
    return {"scanned": True, "commits_checked": len(rev_list), "hits": added}


def scan_secrets(root: Path, history: bool = False, history_depth: int = 200,
                 staged_only: bool = False, include_tests: bool = True) -> dict:
    findings: list[Finding] = []
    tracked = set(tracked_files(root))
    targets = staged_files(root) if staged_only else [p for p in walk(root)]
    if staged_only and not targets:
        targets = []

    seen = set()
    for path in targets:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        source = "tracked" if path in tracked else "worktree"
        scan_file(root, path, findings, source)

    # Files git already tracks are publishable even when walk() skips their
    # directory (build output, caches, vendored trees). Judge them explicitly,
    # otherwise "tracked-but-ignored" build junk is reported as clean.
    for path in tracked:
        if not path.exists() or str(path) in seen:
            continue
        relpath = rel(root, path).replace("\\", "/")
        matched_rule = None
        for rule_id, sev, title, pattern, fix in SENSITIVE_FILE_PATTERNS:
            if pattern.search(relpath):
                matched_rule = (rule_id, sev, title, fix)
                break
        if matched_rule:
            rule_id, sev, title, fix = matched_rule
            if is_allowlisted(relpath):
                continue
            findings.append(Finding("security", rule_id, sev, f"{title}: {relpath}",
                                    f"Tracked file matches {rule_id}.", [f"{relpath}:1"], fix))
        else:
            scan_file(root, path, findings, "tracked")

    # publishable-overlap check: files that would be pushed but are ignored
    ignored_but_tracked = []
    if is_git_repo(root):
        ign = git(root, "ls-files", "-i", "-c", "--exclude-standard", "-z")
        ignored_but_tracked = [p for p in ign.stdout.split("\x00") if p][:40]
        if ignored_but_tracked:
            findings.append(Finding(
                "security", "repo.tracked-but-ignored", "medium",
                f"{len(ignored_but_tracked)} tracked file(s) are also matched by .gitignore",
                "Ignored files that are already committed keep syncing and bloat every clone.",
                ignored_but_tracked[:10],
                "`git rm -r --cached <path>` for generated output."))

    gitignore = scan_gitignore(root)
    if not gitignore["exists"]:
        findings.append(Finding("security", "repo.no-gitignore", "high",
                                "No .gitignore",
                                "Without one, .env files, build output and OS junk enter the next commit.",
                                [".gitignore"], "Create a .gitignore for your stack (see references/gitignore/).",
                                autofix="write_gitignore"))
    else:
        cleanup = [m for m in gitignore["missing_common"] if m in (".DS_Store", ".env")]
        if cleanup:
            findings.append(Finding("security", "repo.gitignore-gaps", "medium",
                                    f".gitignore does not cover: {', '.join(cleanup)}",
                                    "Common credential/junk patterns are unignored.",
                                    [".gitignore"], "Add the missing patterns.",
                                    autofix="write_gitignore"))
    if ignored_but_tracked:
        findings.append(Finding("security", "repo.tracked-but-ignored", "medium",
                                f"{len(ignored_but_tracked)} tracked file(s) also match .gitignore",
                                "These are committed despite being ignored; they will keep syncing.",
                                ignored_but_tracked[:10],
                                "Decide per file: `git rm --cached <path>` for output, or fix the ignore rule."))

    hist = {"scanned": False}
    if history:
        hist = scan_history(root, history_depth, findings)

    # surface the top-level shape of the risk
    publishable_secrets = [f for f in findings
                           if f.checklist == "security" and f.severity in ("blocker", "high")
                           and f.id.startswith(("secret.", "file."))]
    findings = sort_findings(findings)
    counts = summarize(findings)
    return {
        "checklist": "security",
        "project": str(root),
        "summary": counts,
        "verdict": "BLOCK" if counts["blocker"] else ("REVIEW" if counts["high"] else "PASS"),
        "publishable_secret_count": len(publishable_secrets),
        "files_scanned": len(seen),
        "tracked_files": len(tracked),
        "gitignore": gitignore,
        "ignored_but_tracked": ignored_but_tracked,
        "history": hist,
        "findings": [f.as_dict() for f in findings],
        "tools": {"gitleaks": bool(which("gitleaks")), "trufflehog": bool(which("trufflehog"))},
        "notes": [
            "Findings are redacted by design; open the cited file:line yourself.",
            "Removing a secret from the working tree does not un-leak it. Rotate first.",
        ],
    }


def main(argv=None):
    ap = parser(description="gitup Phase C secret and hygiene scan")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--history", action="store_true", help="also grep git history")
    ap.add_argument("--history-depth", type=int, default=200)
    ap.add_argument("--staged-only", action="store_true",
                    help="scan only what the next commit would include")
    ap.add_argument("--ensure-ignore", action="store_true",
                    help="write a stack-appropriate .gitignore if none is adequate")
    args = ap.parse_args(argv)

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")
    report = scan_secrets(root, args.history, args.history_depth, args.staged_only)
    if args.ensure_ignore:
        from ignorefix import apply_gitignore  # merged into .gitignore, never replaced
        report["gitignore_result"] = apply_gitignore(root)
    emit(report, args.out or None)
    return 2 if report["summary"]["blocker"] else (1 if report["summary"]["high"] else 0)


if __name__ == "__main__":
    sys.exit(main())
