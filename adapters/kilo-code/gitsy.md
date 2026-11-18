---
description: Prepare, audit, document, brand, and publish a local software project to GitHub with GITSY.
agent: code
subtask: false
---

# /gitsy — Kilo Code Workflow Adapter

Execute the GITSY Universal GitHub Publishing skill on the user-supplied `<project-location>` (or `.` if none was provided).

1. Read `~/.kilo/skills/gitsy/SKILL.md` (or `~/.agents/skills/gitsy/SKILL.md`).
2. Run `scripts/project-audit/detect_environment.py` and `scripts/project-audit/discover_and_audit.py`.
3. Run `scripts/security-audit/scan_secrets_and_hygiene.py` and `scripts/security-audit/watermark_audit.py`.
4. Generate human-written documentation and visual SVG assets via `scripts/screenshots/capture_and_brand.py`.
5. Run `scripts/github-sync/sync_repository.py`, `scripts/release/prepare_release.py`, and `scripts/verification/verify_publication.py`, then present the Final User Report.
