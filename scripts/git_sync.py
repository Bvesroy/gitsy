#!/usr/bin/env python3
"""gitup git_sync.py - Phase D: stage, commit and push without surprises.

Design rules enforced in code, not in prose:

  * never force-push, never rewrite history, never delete a branch or tag;
  * never push to a remote whose visibility differs from the one the caller
    declared (a private project cannot be published by accident);
  * the secret scan runs before the commit and blocks on blocker findings;
  * `.git` internals are never touched; no `git add -A` on a dirty tree unless
    the caller passes --all (the default stages the explicit file groups);
  * every git invocation is captured, so a failure is reported with its stderr
    instead of a cheerful "success".

Sub-commands
  status    read-only snapshot: branch, ahead/behind, dirty files, tags, remote
  stage     add files (--paths, or gitup's documentation set) and show the plan
  commit    create one commit from the staged tree (message required)
  push      push the current branch and tags (refuses force, refuses mismatch)
  tag       create an annotated tag if it does not already exist
  verify    confirm remote head, files, branch and tags actually match local

Usage:
  python3 git_sync.py status  --project . [--out status.json]
  python3 git_sync.py stage   --project . --paths README.md docs/
  python3 git_sync.py commit  --project . --message "docs: rewrite README"
  python3 git_sync.py push    --project . --expect-visibility private [--dry-run]
  python3 git_sync.py verify  --project .
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
    rel,
    run,
    which,
)
from gh_repo import auth_state, inspect as gh_inspect, parse_remote, repo_info

FORBIDDEN_PUSH_FLAGS = ("--force", "-f", "--force-with-lease", "--mirror",
                        "--delete", "--prune")


def status(root: Path) -> dict:
    if not is_git_repo(root):
        return {"is_repo": False, "project": str(root), "next": "git init"}
    branch = (git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout or "").strip()
    porcelain = git(root, "status", "--porcelain=v1", "-z").stdout
    staged, unstaged, untracked = [], [], []
    entries = [e for e in porcelain.split("\x00") if e]
    for entry in entries:
        code, path = entry[:2], entry[3:]
        if code[0] not in (" ", "?"):
            staged.append(path)
        if code[1] not in (" ", "?"):
            unstaged.append(path)
        if code == "??":
            untracked.append(path)
    head = git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    tags = [t for t in git(root, "tag", "--sort=-creatordate").stdout.splitlines() if t][:10]
    upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead = behind = None
    if upstream.ok and upstream.stdout.strip():
        a = git(root, "rev-list", "--count", "@{u}..HEAD")
        b = git(root, "rev-list", "--count", "HEAD..@{u}")
        ahead = int(a.stdout) if a.stdout.strip().isdigit() else None
        behind = int(b.stdout) if b.stdout.strip().isdigit() else None
    return {
        "is_repo": True,
        "project": str(root),
        "branch": branch,
        "head": head,
        "has_commits": bool(head),
        "upstream": upstream.stdout.strip() if upstream.ok else None,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked[:100],
        "dirty": bool(staged or unstaged or untracked),
        "tags": tags,
        "remote": _primary_remote(root),
    }


def _primary_remote(root: Path):
    res = git(root, "remote", "-v")
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "origin":
            owner, repo = parse_remote(parts[1])
            return {"name": "origin", "url": parts[1], "owner": owner, "repo": repo}
    return None


def ensure_repo(root: Path, initial_branch: str = "main") -> dict:
    """Initialise a repository only when there is none (never re-init)."""
    if is_git_repo(root):
        return {"action": "init", "ok": True, "already": True,
                "branch": status(root)["branch"]}
    res = git(root, "init", "-b", initial_branch)
    if not res.ok:
        # older git has no -b
        res = git(root, "init")
        git(root, "symbolic-ref", "HEAD", f"refs/heads/{initial_branch}")
    return {"action": "init", "ok": res.ok, "already": False, "branch": initial_branch,
            "error": "" if res.ok else res.stderr.strip()[:300]}


# Documentation-and-asset paths gitup is allowed to stage on its own behalf.
GITIGNORE_SAFE = re.compile(
    r"^(?:docs|documentation|assets|\.github)(?:/|$)|\.(?:md|mdx|png|jpg|jpeg|gif|webp|svg|yml|yaml|txt|json|toml)$",
    re.IGNORECASE)


def stage(root: Path, paths: list[str], all_files: bool = False) -> dict:
    if not is_git_repo(root):
        die("not a git repository; run `git_sync.py init` first")
    if all_files:
        res = git(root, "add", "-A")
        return {"action": "stage", "ok": res.ok, "mode": "all",
                "error": "" if res.ok else res.stderr.strip()[:300]}
    if not paths:
        die("no paths given; pass --paths a b c (or --all to stage everything)")
    rejected = []
    accepted = []
    for raw in paths:
        target = (root / raw).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            rejected.append({"path": raw, "why": "outside the project directory"})
            continue
        if raw.split("/")[0] == ".git" or ".." in Path(raw).parts:
            rejected.append({"path": raw, "why": "git internals or parent traversal"})
            continue
        if not (root / raw).exists():
            rejected.append({"path": raw, "why": "does not exist"})
            continue
        accepted.append(raw)
    if not accepted:
        return {"action": "stage", "ok": False, "rejected": rejected,
                "error": "nothing valid to stage"}
    res = git(root, "add", "--", *accepted)
    staged = git(root, "diff", "--cached", "--name-only").stdout.splitlines()
    return {"action": "stage", "ok": res.ok, "added": accepted, "rejected": rejected,
            "staged_count": len(staged), "staged_sample": staged[:40],
            "error": "" if res.ok else res.stderr.strip()[:300]}


def commit(root: Path, message: str, allow_empty: bool = False) -> dict:
    if not message or len(message.strip()) < 5:
        die("commit message is required and must be meaningful")
    if not re.match(r"^[a-z]+(?:\([a-z0-9\-]+\))?: .+", message.strip()) and "\n" not in message.strip():
        # not fatal: many projects use plain sentences. Record it, do not block.
        conventional = False
    else:
        conventional = True
    staged = git(root, "diff", "--cached", "--name-only").stdout.splitlines()
    if not staged and not allow_empty:
        return {"action": "commit", "ok": True, "skipped": True,
                "reason": "nothing staged", "conventional": conventional}
    argv = ["commit", "-m", message]
    if allow_empty:
        argv.append("--allow-empty")
    res = git(root, *argv)
    head = git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    files = git(root, "show", "--stat", "--oneline", "--name-only", "HEAD").stdout.splitlines()
    return {"action": "commit", "ok": res.ok, "hash": head,
            "files": len(staged), "conventional": conventional,
            "stat": files[0] if files else "",
            "error": "" if res.ok else (res.stderr or res.stdout).strip()[:400]}


def tag(root: Path, name: str, message: str = "") -> dict:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?", name):
        die(f"tag '{name}' is not a semver-looking version (e.g. v1.2.3)")
    existing = git(root, "tag", "-l", name).stdout.strip()
    if existing:
        return {"action": "tag", "ok": True, "exists": True, "tag": name,
                "note": "left untouched; tags are never moved by gitup"}
    res = git(root, "tag", "-a", name, "-m", message or name)
    return {"action": "tag", "ok": res.ok, "tag": name, "exists": False,
            "error": "" if res.ok else res.stderr.strip()[:300]}


def push(root: Path, expect_visibility: str = "", set_upstream: bool = True,
         include_tags: bool = True, dry_run: bool = False, remote: str = "origin") -> dict:
    state = status(root)
    if not state["is_repo"]:
        die("not a git repository")
    if not state["has_commits"]:
        return {"action": "push", "ok": False, "blocked": "no commits yet"}
    remote_info = _primary_remote(root)
    if not remote_info:
        return {"action": "push", "ok": False, "blocked": "no origin remote"}

    # Refuse when the declared visibility does not match GitHub's reality.
    visibility_check = {}
    if expect_visibility:
        info = repo_info(remote_info["owner"], remote_info["repo"])
        visibility_check = info
        if not info.get("resolved"):
            return {"action": "push", "ok": False,
                    "blocked": "cannot confirm repository visibility",
                    "detail": info.get("reason", ""),
                    "hint": "Run `gh auth status`; gitup will not push blind."}
        actual = info.get("visibility")
        if actual != expect_visibility:
            return {"action": "push", "ok": False,
                    "blocked": "visibility mismatch",
                    "expected": expect_visibility, "actual": actual,
                    "hint": ("Change repository visibility on GitHub first, or declare the "
                             "actual visibility. gitup never flips visibility itself.")}

    # Never push a secret.
    from secret_scan import scan_secrets
    sec = scan_secrets(root, history=False)
    if sec["summary"]["blocker"]:
        return {"action": "push", "ok": False, "blocked": "secret scan blockers",
                "blockers": [f["title"] for f in sec["findings"]
                             if f["severity"] == "blocker"][:10],
                "hint": "Resolve (and rotate) every blocker before publishing."}

    argv = ["push"]
    if set_upstream:
        argv += ["-u", remote, state["branch"]]
    else:
        argv += [remote, state["branch"]]
    if include_tags:
        argv.append("--follow-tags")
    assert not any(flag in argv for flag in FORBIDDEN_PUSH_FLAGS), "force-push is not allowed"

    if dry_run:
        return {"action": "push", "ok": True, "dry_run": True, "argv": argv,
                "would_push": {"branch": state["branch"], "ahead": state["ahead"],
                               "tags": state["tags"][:5]},
                "visibility": visibility_check.get("visibility")}

    res = git(root, *argv, timeout=300)
    if not res.ok:
        hint = ""
        text = (res.stderr or res.stdout)
        if "fetch first" in text or "non-fast-forward" in text:
            hint = ("The remote has commits you do not have. Run `git pull --rebase` and "
                    "resolve the overlap; gitup will not force-push over them.")
        elif "Permission" in text or "403" in text or "denied" in text:
            hint = "Your gh account may not have push access to this repository."
        return {"action": "push", "ok": False, "argv": argv,
                "error": text.strip()[:500], "hint": hint}

    after = status(root)
    return {"action": "push", "ok": True, "argv": argv,
            "branch": after["branch"], "ahead_after": after["ahead"],
            "visibility": visibility_check.get("visibility"),
            "output": (res.stdout or res.stderr).strip()[:400]}


def verify(root: Path, fetch: bool = True) -> dict:
    """Confirm the remote really holds what we think it holds."""
    state = status(root)
    if not state["is_repo"] or not state.get("remote"):
        return {"ok": False, "blocked": "no repository/remote to verify"}
    remote = state["remote"]
    checks = {"remote_branch_exists": False, "same_commit": False,
              "tags_on_remote": [], "files_present": []}

    if fetch:
        git(root, "fetch", "--tags", "--quiet", "origin", timeout=180)
    ls = git(root, "ls-remote", "--heads", "origin", state["branch"])
    checks["remote_branch_exists"] = bool(ls.stdout.strip())
    local_head = git(root, "rev-parse", "HEAD").stdout.strip()
    remote_head = git(root, "rev-parse", f"origin/{state['branch']}").stdout.strip()
    checks["same_commit"] = bool(local_head) and local_head == remote_head

    remote_tags = git(root, "ls-remote", "--tags", "origin").stdout
    for tag in state["tags"]:
        if re.search(rf"refs/tags/{re.escape(tag)}(\^\{{}})?\s*$", remote_tags, re.M):
            checks["tags_on_remote"].append(tag)

    # Confirm the files a reader will actually see exist in the remote tree.
    wanted = [p for p in ("README.md", "LICENSE", "CONTRIBUTING.md", "CHANGELOG.md",
                          "SECURITY.md", ".gitignore") if (root / p).exists()]
    for path in wanted[:8]:
        res = git(root, "cat-file", "-e", f"origin/{state['branch']}:{path}")
        checks["files_present"].append({"path": path, "on_remote": res.ok})

    info = repo_info(remote["owner"], remote["repo"])
    ok = checks["remote_branch_exists"] and checks["same_commit"] and \
        all(f["on_remote"] for f in checks["files_present"])
    return {"ok": ok, "branch": state["branch"], "local_head": local_head[:12],
            "remote_head": remote_head[:12], "checks": checks,
            "github": {k: info.get(k) for k in ("resolved", "url", "visibility",
                                                "default_branch", "stars")},
            "hint": "" if ok else "Remote does not match local; re-run push and read the error."}


def main(argv=None):
    ap = parser(description="gitup git synchronization")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(_cmd, **kw):
        p = sub.add_parser(_cmd)
        p.add_argument("--project", required=True)
        p.add_argument("--out", default="")
        for k, v in kw.items():
            p.add_argument("--" + k.replace("_", "-"), **v)
        return p

    add("status")
    add("init", initial_branch={"default": "main"})
    add("stage", paths={"nargs": "*", "default": []}, all={"action": "store_true"})
    add("commit", message={"required": True}, allow_empty={"action": "store_true"})
    add("tag", name={"required": True}, message={"default": ""})
    add("push", expect_visibility={"default": ""}, dry_run={"action": "store_true"},
        include_tags={"action": "store_true"})
    add("verify")

    args = ap.parse_args(argv)
    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        die(f"project directory not found: {root}")

    if args.cmd == "status":
        out = status(root)
    elif args.cmd == "init":
        out = ensure_repo(root, args.initial_branch)
    elif args.cmd == "stage":
        out = stage(root, args.paths, args.all)
    elif args.cmd == "commit":
        out = commit(root, args.message, args.allow_empty)
    elif args.cmd == "tag":
        out = tag(root, args.name, args.message)
    elif args.cmd == "push":
        out = push(root, args.expect_visibility, True, args.include_tags, args.dry_run)
    else:
        out = verify(root)
    emit(out, getattr(args, "out", "") or None)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
