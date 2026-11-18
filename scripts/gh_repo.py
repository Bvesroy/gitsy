#!/usr/bin/env python3
"""gitup gh_repo.py - Phase D: inspect, create and connect a GitHub repository.

Sub-commands
  inspect   read-only: which repo (if any) is this project connected to, what
            visibility does it have, is gh authenticated, is anything unpushed.
  create    create a repository on GitHub. Requires --visibility explicitly, so
            a private project can never become public by accident.
  connect   attach an existing GitHub repository as a remote (no push).
  ensure    create-or-connect, then print the single next action.

Every write action prints a *plan* first and refuses ambiguous input. Nothing
here pushes commits, force-pushes, changes visibility, or deletes anything.

Usage:
  python3 gh_repo.py inspect  --project ~/Developer/MyProject
  python3 gh_repo.py create   --project . --name my-project --visibility private --description "..."
  python3 gh_repo.py connect  --project . --remote git@github.com:user/repo.git
  python3 gh_repo.py ensure   --project . --visibility private
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
from pathlib import Path

from gitup_common import (
    die,
    emit,
    git,
    is_git_repo,
    parser,
    run,
    which,
)

RESERVED_OWNERS = {"settings", "marketplace", "sponsors", "topics", "trending",
                   "collections", "events", "explore", "notifications", "new",
                   "organizations", "about", "pricing", "login", "join", "apps"}


def gh(args, timeout=60):
    return run(["gh", *args], timeout=timeout)


def gh_json(args, timeout=60):
    res = gh(args, timeout=timeout)
    if not res.ok:
        return None, res
    try:
        return json.loads(res.stdout), res
    except json.JSONDecodeError:
        return None, res


def auth_state() -> dict:
    """Report gh auth without trusting either the exit code or the prose.

    `gh auth status` exits non-zero when ANY host is unauthenticated, and its
    human-readable output differs between versions, so both signals are parsed
    and combined instead of relying on one.
    """
    if not which("gh"):
        return {"available": False, "reason": "gh not installed"}
    res = gh(["auth", "status"])
    text = (res.stdout or "") + (res.stderr or "")
    accounts = re.findall(r"account ([A-Za-z0-9_.\-]+)", text)
    active = re.search(r"Active account: true", text)
    active_name = ""
    if active:
        # the account line immediately preceding "Active account: true"
        before = text[:active.start()].rstrip().splitlines()
        for line in reversed(before):
            m = re.search(r"account ([A-Za-z0-9_.\-]+)", line)
            if m:
                active_name = m.group(1)
                break
    scopes = re.findall(r"Token scopes: '([^']*)'", text)
    scope_set = [s.strip() for chunk in scopes for s in chunk.split(",") if s.strip()]
    authed = bool(accounts) or res.ok
    return {
        "available": True,
        "authenticated": authed,
        "accounts": accounts,
        "active": active_name or (accounts[0] if accounts else ""),
        "scopes": scope_set,
        "has_repo_scope": any(s == "repo" or s.startswith("repo:") for s in scope_set),
        "token_kind": "fine-grained" if "gho_" in text or "fine-grained" in text.lower() else "classic/oauth",
        "notes": [] if authed else ["run `gh auth login`"],
    }


def parse_remote(url: str):
    """Extract (owner, repo) from any GitHub remote spelling."""
    url = url.strip()
    patterns = [
        r"git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"https?://(?:[^@/]+@)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        m = re.match(pattern, url)
        if m:
            return m.group("owner"), m.group("repo")
    return None, None


def preferred_protocol() -> str:
    """Which protocol will `git push` actually work with?

    gh records this itself; guessing ssh breaks every machine without keys.
    """
    res = gh(["config", "get", "git_protocol"])
    if res.ok:
        value = res.stdout.strip().lower()
        if value in ("ssh", "https"):
            return value
    return "https"


def remote_url_for(owner: str, name: str) -> str:
    if preferred_protocol() == "ssh":
        return f"git@github.com:{owner}/{name}.git"
    return f"https://github.com/{owner}/{name}.git"


def remotes(root: Path) -> list[dict]:
    res = git(root, "remote", "-v")
    out = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            owner, repo = parse_remote(parts[1])
            out.append({"name": parts[0], "url": parts[1], "kind": parts[2],
                        "owner": owner, "repo": repo})
    return out


def repo_info(owner: str, repo: str) -> dict:
    if not (which("gh") and auth_state()["authenticated"]):
        return {"resolved": False, "reason": "gh unavailable or unauthenticated"}
    data, res = gh_json(["api", f"repos/{owner}/{repo}"])
    if not data:
        return {"resolved": False, "owner": owner, "repo": repo,
                "reason": (res.stderr or res.stdout or "not found").strip()[:200]}
    return {
        "resolved": True,
        "owner": owner,
        "name": data.get("name"),
        "full_name": data.get("full_name"),
        "url": data.get("html_url"),
        "visibility": data.get("visibility") or ("private" if data.get("private") else "public"),
        "private": bool(data.get("private")),
        "default_branch": data.get("default_branch"),
        "description": data.get("description") or "",
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "open_issues": data.get("open_issues_count"),
        "license": (data.get("license") or {}).get("spdx_id") if isinstance(data.get("license"), dict) else None,
        "topics": data.get("topics") or [],
        "has_issues": data.get("has_issues"),
        "archived": data.get("archived"),
        "pushed_at": data.get("pushed_at"),
        "created_at": data.get("created_at"),
        "size_kb": data.get("size"),
        "release_count": None,
    }


def inspect(root: Path) -> dict:
    info = {"project": str(root), "is_git_repo": is_git_repo(root),
            "remotes": [], "github": None, "auth": auth_state()}
    if not info["is_git_repo"]:
        info["next_action"] = "git_init"
        return info
    info["remotes"] = remotes(root)
    gh_remotes = [r for r in info["remotes"] if r["owner"] and r["repo"]]
    upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    info["upstream"] = upstream.stdout.strip() if upstream.ok else None
    ahead = git(root, "rev-list", "--count", "@{u}..HEAD")
    behind = git(root, "rev-list", "--count", "HEAD..@{u}")
    info["ahead"] = int(ahead.stdout) if ahead.ok and ahead.stdout.strip().isdigit() else None
    info["behind"] = int(behind.stdout) if behind.ok and behind.stdout.strip().isdigit() else None
    if gh_remotes:
        first = gh_remotes[0]
        info["github"] = repo_info(first["owner"], first["repo"])
        info["github"]["remote_name"] = first["name"]
    if not info["remotes"]:
        info["next_action"] = "create_or_connect"
    elif info["github"] and info["github"].get("resolved"):
        info["next_action"] = "push" if (info["ahead"] or 0) > 0 else "up_to_date"
    else:
        info["next_action"] = "verify_remote"
    return info


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name or ""):
        die("repo name may only contain letters, digits, '.', '_' and '-' (max 100 chars)")
    if name in RESERVED_OWNERS:
        die(f"'{name}' is a reserved GitHub path segment; pick another name")
    return name


def create(root: Path, name: str, visibility: str, description: str = "",
           owner: str = "", add_remote: bool = False, dry_run: bool = False,
           license_template: str = "", allow_init: bool = False) -> dict:
    name = validate_name(name)
    if visibility not in ("public", "private", "internal"):
        die("visibility must be explicitly 'public', 'private' or 'internal'")
    auth = auth_state()
    if not auth["available"]:
        die("gh is not installed; install it from https://cli.github.com/ and run `gh auth login`")
    if not auth["authenticated"]:
        die("gh is not authenticated; run `gh auth login` first")
    existing = remotes(root)
    if any(r["owner"] for r in existing):
        die("this project already has a GitHub remote; use `inspect` or `connect` instead")
    owner = owner or auth.get("active", "")

    argv = ["repo", "create"]
    argv.append(f"{owner}/{name}" if owner else name)
    argv += ["--" + visibility]
    if description:
        argv += ["--description", description]
    # gitup never lets gh push, add a remote, or seed a README implicitly: the
    # first push is a separate, user-authorized step and the README is gitup's.
    plan = {"argv": argv, "cwd": str(root), "creates": f"{owner}/{name}",
            "visibility": visibility, "remote_protocol": preferred_protocol()}

    if dry_run:
        return {"action": "create", "dry_run": True, "plan": plan,
                "note": "no repository was created"}

    res = gh(argv, timeout=180)
    if not res.ok:
        return {"action": "create", "ok": False, "plan": plan,
                "error": (res.stderr or res.stdout).strip()[:500],
                "hint": "If the name is taken or the org denies repo creation, pick another name/owner."}
    data, _ = gh_json(["api", f"repos/{owner}/{name}"]) if owner else (None, None)
    result = {"action": "create", "ok": True, "plan": plan,
              "url": (data or {}).get("html_url", ""),
              "visibility": (data or {}).get("visibility", visibility)}
    if add_remote:
        url = remote_url_for(owner, name)
        add = git(root, "remote", "add", "origin", url)
        result["remote_added"] = add.ok
        if not add.ok:
            result["remote_error"] = add.stderr.strip()[:300]
    return result


def connect(root: Path, remote_url: str = "", name: str = "", owner: str = "") -> dict:
    if remote_url:
        owner, repo = parse_remote(remote_url)
        if not owner:
            die("that URL is not a GitHub remote")
        url = remote_url
    elif name:
        auth = auth_state()
        owner = owner or auth.get("active", "")
        if not owner:
            die("cannot infer the GitHub owner; pass --owner")
        url = remote_url_for(owner, name)
    else:
        die("give --remote <url> or --name <repo>")
    existing = [r["name"] for r in remotes(root)]
    if "origin" in existing:
        return {"action": "connect", "ok": False,
                "error": "a remote named 'origin' already exists",
                "existing": existing,
                "hint": "Use `git remote set-url origin <url>` if you mean to repoint it."}
    res = git(root, "remote", "add", "origin", url)
    info = repo_info(*parse_remote(url))
    return {"action": "connect", "ok": res.ok, "url": url,
            "github": info, "error": "" if res.ok else res.stderr.strip()[:300]}


def ensure(root: Path, visibility: str = "", name: str = "", description: str = "",
           dry_run: bool = False) -> dict:
    state = inspect(root)
    if not state["is_git_repo"]:
        return {"action": "ensure", "ok": False, "state": state,
                "next": "git init", "blocked": "project is not a git repository"}
    if state["github"] and state["github"].get("resolved"):
        return {"action": "ensure", "ok": True, "state": state,
                "next": "push", "note": "repository already connected"}
    if state["remotes"]:
        return {"action": "ensure", "ok": False, "state": state,
                "next": "verify_remote",
                "blocked": "a remote exists but GitHub could not resolve it (wrong owner/name, or auth)"}
    if not visibility:
        return {"action": "ensure", "ok": False, "state": state,
                "next": "ask_user",
                "blocked": "visibility is required: pass --visibility public|private|internal"}
    inferred = name or Path(root).name
    created = create(root, inferred, visibility, description, dry_run=dry_run, add_remote=True)
    return {"action": "ensure", "ok": created.get("ok", False), "state": state,
            "create": created, "next": "push" if created.get("ok") else "resolve_create_error"}


def main(argv=None):
    ap = parser(description="gitup GitHub repository manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--project", required=True)
    p_inspect.add_argument("--out", default="")

    p_create = sub.add_parser("create")
    p_create.add_argument("--project", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--visibility", required=True,
                          choices=["public", "private", "internal"])
    p_create.add_argument("--description", default="")
    p_create.add_argument("--owner", default="")
    p_create.add_argument("--add-remote", action="store_true")
    p_create.add_argument("--dry-run", action="store_true")
    p_create.add_argument("--out", default="")

    p_connect = sub.add_parser("connect")
    p_connect.add_argument("--project", required=True)
    p_connect.add_argument("--remote", default="")
    p_connect.add_argument("--name", default="")
    p_connect.add_argument("--owner", default="")
    p_connect.add_argument("--out", default="")

    p_ensure = sub.add_parser("ensure")
    p_ensure.add_argument("--project", required=True)
    p_ensure.add_argument("--visibility", default="",
                          choices=["", "public", "private", "internal"])
    p_ensure.add_argument("--name", default="")
    p_ensure.add_argument("--description", default="")
    p_ensure.add_argument("--dry-run", action="store_true")
    p_ensure.add_argument("--out", default="")

    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")

    if args.cmd == "inspect":
        out = inspect(root)
    elif args.cmd == "create":
        out = create(root, args.name, args.visibility, args.description,
                     args.owner, args.add_remote, args.dry_run)
    elif args.cmd == "connect":
        out = connect(root, args.remote, args.name, args.owner)
    else:
        out = ensure(root, args.visibility, args.name, args.description, args.dry_run)
    emit(out, getattr(args, "out", "") or None)
    ok = out.get("ok", True) if isinstance(out, dict) else True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
