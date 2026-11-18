#!/usr/bin/env python3
"""
GITU Phase D: GitHub Repository Creation and Synchronization
Safely manages Git initialization, branch creation, staging, Conventional Commits,
remote configuration, and synchronization without force-pushing or altering
repository visibility without authorization.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, cwd, timeout=30):
    try:
        res = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return False, "", str(exc)


def get_sync_plan(root: Path):
    root = root.resolve()
    git_exists = (root / ".git").exists()
    if not git_exists:
        ok, _, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=root)
        git_exists = ok

    branch = None
    remotes = {}
    status_lines = []
    ahead_behind = None

    if git_exists:
        _, branch, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)
        _, rem_out, _ = run_cmd(["git", "remote", "-v"], cwd=root)
        for line in rem_out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                remotes[parts[0]] = parts[1]
        _, st_out, _ = run_cmd(["git", "status", "--porcelain"], cwd=root)
        status_lines = [l for l in st_out.splitlines() if l.strip()]
        _, ab_out, _ = run_cmd(["git", "status", "-sb"], cwd=root)
        if ab_out:
            ahead_behind = ab_out.splitlines()[0]

    return {
        "project_root": str(root),
        "git_initialized": git_exists,
        "current_branch": branch or "main",
        "remotes": remotes,
        "pending_changes_count": len(status_lines),
        "pending_changes_preview": status_lines[:25],
        "branch_tracking_summary": ahead_behind,
    }


def execute_sync(
    root: Path,
    commit_message: str,
    branch: str = "main",
    remote_url: str = None,
    create_gh_repo: str = None,
    visibility: str = None,
    push: bool = False,
):
    root = root.resolve()
    actions = []
    errors = []

    # 1. Initialize Git if needed
    if not (root / ".git").exists():
        ok, out, err = run_cmd(["git", "init", "-b", branch], cwd=root)
        if not ok:
            ok, out, err = run_cmd(["git", "init"], cwd=root)
            run_cmd(["git", "checkout", "-b", branch], cwd=root)
        actions.append(f"Initialized Git repository on branch '{branch}'")

    # Ensure Git user identity is configured locally if global config is empty
    ok_n, name_val, _ = run_cmd(["git", "config", "--get", "user.name"], cwd=root)
    if not ok_n or not name_val:
        run_cmd(["git", "config", "user.name", "Project Maintainer"], cwd=root)
    ok_e, email_val, _ = run_cmd(["git", "config", "--get", "user.email"], cwd=root)
    if not ok_e or not email_val:
        run_cmd(["git", "config", "user.email", "maintainer@users.noreply.github.com"], cwd=root)

    # 2. Configure remote if provided
    if remote_url:
        ok_r, existing_origin, _ = run_cmd(["git", "remote", "get-url", "origin"], cwd=root)
        if not ok_r:
            ok_add, _, err_add = run_cmd(["git", "remote", "add", "origin", remote_url], cwd=root)
            if ok_add:
                actions.append(f"Added remote 'origin' -> {remote_url}")
            else:
                errors.append(f"Failed to add remote origin: {err_add}")
        elif existing_origin != remote_url:
            ok_set, _, err_set = run_cmd(["git", "remote", "set-url", "origin", remote_url], cwd=root)
            if ok_set:
                actions.append(f"Updated remote 'origin' -> {remote_url}")
            else:
                errors.append(f"Failed to update remote origin: {err_set}")

    # 3. Stage and commit changes if dirty
    _, st_out, _ = run_cmd(["git", "status", "--porcelain"], cwd=root)
    if st_out.strip():
        ok_add, _, err_add = run_cmd(["git", "add", "-A"], cwd=root)
        if not ok_add:
            errors.append(f"git add failed: {err_add}")
        else:
            ok_c, out_c, err_c = run_cmd(["git", "commit", "-m", commit_message], cwd=root)
            if ok_c:
                actions.append(f"Created commit: {commit_message}")
            else:
                errors.append(f"git commit failed: {err_c or out_c}")
    else:
        actions.append("Working tree already clean; no new commit required")

    # 4. Create GitHub repository via `gh` if requested (requires explicit visibility)
    if create_gh_repo:
        if visibility not in ("public", "private", "internal"):
            errors.append("Refusing to create GitHub repository without explicit --visibility (public|private|internal)")
        else:
            ok_gh, out_gh, err_gh = run_cmd(
                ["gh", "repo", "create", create_gh_repo, f"--{visibility}", "--source=.", "--remote=origin"],
                cwd=root,
            )
            if ok_gh:
                actions.append(f"Created GitHub repository '{create_gh_repo}' ({visibility})")
            else:
                errors.append(f"gh repo create failed: {err_gh or out_gh}")

    # 5. Push to origin if requested (never force-push)
    if push:
        _, cur_branch, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)
        target_branch = cur_branch or branch
        ok_p, out_p, err_p = run_cmd(["git", "push", "-u", "origin", target_branch], cwd=root)
        if ok_p:
            actions.append(f"Pushed branch '{target_branch}' to origin")
            ok_t, tags_out, _ = run_cmd(["git", "tag", "--list"], cwd=root)
            if ok_t and tags_out.strip():
                ok_pt, _, err_pt = run_cmd(["git", "push", "origin", "--tags"], cwd=root)
                if ok_pt:
                    actions.append("Pushed tags to origin")
                else:
                    errors.append(f"Tag push warning: {err_pt}")
        else:
            errors.append(f"git push failed: {err_p or out_p}")

    final_state = get_sync_plan(root)
    return {
        "status": "SUCCESS" if not errors else "PARTIAL_OR_FAILED",
        "actions_taken": actions,
        "errors": errors,
        "final_state": final_state,
    }


def main():
    parser = argparse.ArgumentParser(description="GITU Phase D: GitHub Repository Sync")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--plan", action="store_true", help="Inspect and output sync plan only")
    parser.add_argument("--execute", action="store_true", help="Stage, commit, and optionally sync")
    parser.add_argument("--commit-message", default="chore: prepare repository for publication", help="Commit message")
    parser.add_argument("--branch", default="main", help="Default branch name")
    parser.add_argument("--remote-url", help="Remote origin URL to connect")
    parser.add_argument("--create-gh-repo", help="GitHub repo name/slug to create via gh CLI")
    parser.add_argument("--visibility", choices=["public", "private", "internal"], help="Explicit visibility for new repo")
    parser.add_argument("--push", action="store_true", help="Push commits and tags to origin")
    parser.add_argument("--output", help="Write JSON result to file")
    args = parser.parse_args()

    root = Path(args.project_path)
    if args.execute:
        result = execute_sync(
            root=root,
            commit_message=args.commit_message,
            branch=args.branch,
            remote_url=args.remote_url,
            create_gh_repo=args.create_gh_repo,
            visibility=args.visibility,
            push=args.push,
        )
    else:
        result = get_sync_plan(root)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
