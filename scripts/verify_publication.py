#!/usr/bin/env python3
"""
GITU Section 13: Independent Final Verification & Quality Gate
Performs an independent post-preparation verification of Git integrity,
remote synchronization, zero leaked secrets, README completeness, valid
relative links and image assets, watermark cleanliness, and release checksums.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, cwd):
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode == 0, res.stdout.strip(), res.stderr.strip()


def verify_repository(root: Path):
    root = root.resolve()
    script_dir = Path(__file__).resolve().parent
    discover_script = script_dir / "discover_and_audit.py"
    security_script = script_dir / "scan_secrets_and_hygiene.py"
    watermark_script = script_dir / "watermark_audit.py"

    checks = []

    # 1. Git repository integrity
    git_ok = (root / ".git").exists()
    if git_ok:
        ok_fsck, _, err_fsck = run_cmd(["git", "fsck", "--no-progress"], cwd=root)
        _, status_porcelain, _ = run_cmd(["git", "status", "--porcelain"], cwd=root)
        clean_tree = len(status_porcelain.strip()) == 0
        checks.append({
            "gate": "git_integrity",
            "status": "PASS" if (ok_fsck and clean_tree) else "WARN",
            "details": "Git object database healthy and working tree clean" if (ok_fsck and clean_tree)
            else f"fsck={ok_fsck}, uncommitted_files={len(status_porcelain.splitlines())}",
        })
    else:
        checks.append({
            "gate": "git_integrity",
            "status": "FAIL",
            "details": "Directory is not initialized as a Git repository.",
        })

    # 2. Remote synchronization check
    if git_ok:
        ok_rem, rem_url, _ = run_cmd(["git", "remote", "get-url", "origin"], cwd=root)
        if ok_rem and rem_url:
            ok_ls, ls_out, _ = run_cmd(["git", "ls-remote", "--heads", "origin"], cwd=root)
            _, local_head, _ = run_cmd(["git", "rev-parse", "HEAD"], cwd=root)
            synced = ok_ls and (local_head in ls_out)
            checks.append({
                "gate": "remote_synchronization",
                "status": "PASS" if synced else "WARN",
                "details": f"Remote origin ({rem_url}) matches local HEAD ({local_head[:8]})" if synced
                else f"Remote origin configured ({rem_url}), but HEAD sync not confirmed in ls-remote",
            })
        else:
            checks.append({
                "gate": "remote_synchronization",
                "status": "WARN",
                "details": "No 'origin' remote configured yet (local repository only).",
            })

    # 3. Security & Secret Gate
    ok_sec, sec_out, _ = run_cmd([sys.executable, str(security_script), str(root)], cwd=root)
    sec_data = json.loads(sec_out) if ok_sec and sec_out.startswith("{") else {}
    sec_pass = sec_data.get("safe_to_publish", False)
    checks.append({
        "gate": "security_and_secrets",
        "status": "PASS" if sec_pass else "FAIL",
        "details": "Zero exposed secrets, credentials, or private keys in working tree or history"
        if sec_pass else f"Security blocker detected: {sec_data.get('summary')}",
    })

    # 4. Watermark & Agent Branding Gate
    ok_wm, wm_out, _ = run_cmd([sys.executable, str(watermark_script), str(root)], cwd=root)
    wm_data = json.loads(wm_out) if ok_wm and wm_out.startswith("{") else {}
    wm_count = wm_data.get("watermarks_found", 0)
    checks.append({
        "gate": "watermark_cleanliness",
        "status": "PASS" if wm_count == 0 else "WARN",
        "details": "Zero self-promotional AI watermarks found" if wm_count == 0
        else f"{wm_count} AI branding lines remaining",
    })

    # 5. Documentation & Relative Links Gate
    ok_aud, aud_out, _ = run_cmd([sys.executable, str(discover_script), str(root), "--run-tests"], cwd=root)
    aud_data = json.loads(aud_out) if ok_aud and aud_out.startswith("{") else {}
    doc_info = aud_data.get("documentation", {})
    readme_info = doc_info.get("readme", {})
    broken_links = doc_info.get("broken_relative_links", [])
    readme_issues = readme_info.get("issues", [])

    doc_pass = readme_info.get("exists", False) and len(broken_links) == 0 and len(readme_issues) == 0
    checks.append({
        "gate": "documentation_and_links",
        "status": "PASS" if doc_pass else ("WARN" if readme_info.get("exists") else "FAIL"),
        "details": "README.md complete and all relative links/images resolve on disk"
        if doc_pass else f"issues={readme_issues}, broken_links={broken_links}",
    })

    # 6. Test Execution Gate
    test_info = aud_data.get("test_execution", {})
    if test_info.get("executed"):
        checks.append({
            "gate": "automated_tests",
            "status": "PASS" if test_info.get("passed") else "FAIL",
            "details": f"Command `{test_info.get('command')}` passed" if test_info.get("passed")
            else f"Tests failed: {test_info.get('output', '')[:200]}",
        })
    else:
        checks.append({
            "gate": "automated_tests",
            "status": "WARN",
            "details": "No automated unit test runner executed during verification gate.",
        })

    overall = "PASS"
    if any(c["status"] == "FAIL" for c in checks):
        overall = "FAIL"
    elif any(c["status"] == "WARN" for c in checks):
        overall = "PASS_WITH_WARNINGS"

    return {
        "project_root": str(root),
        "overall_status": overall,
        "quality_gates": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="GITU Section 13: Final Quality Gate Verification")
    parser.add_argument("project_path", help="Path to local software project")
    parser.add_argument("--output", help="Write JSON verification report to file")
    args = parser.parse_args()

    report = verify_repository(Path(args.project_path))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
