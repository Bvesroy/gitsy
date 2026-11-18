---
description: Prepare, audit, document, brand, and publish a local software project to GitHub with GITSY.
argument-hint: <project-location>
---

# /gitsy — Universal GitHub Publishing Workflow (Claude Code Adapter)

Target project location: `$ARGUMENTS` (if empty, use the current working directory `.`).

Locate the installed GITSY skill directory (`SKILL_ROOT`, typically `~/.claude/skills/gitsy`, `.claude/skills/gitsy`, or `~/.agents/skills/gitsy`) and read `$SKILL_ROOT/SKILL.md` in full before executing any step.

1. Run environment detection:
   `python3 "$SKILL_ROOT/scripts/project-audit/detect_environment.py" --json`
2. Run Phase A & B project discovery and deep audit on the target directory:
   `python3 "$SKILL_ROOT/scripts/project-audit/discover_and_audit.py" "${ARGUMENTS:-.}" --run-tests --output /tmp/gitsy_audit.json`
3. Run Phase C mandatory security scan and AI watermark audit:
   `python3 "$SKILL_ROOT/scripts/security-audit/scan_secrets_and_hygiene.py" "${ARGUMENTS:-.}" --fix-gitignore --output /tmp/gitsy_security.json`
   `python3 "$SKILL_ROOT/scripts/security-audit/watermark_audit.py" "${ARGUMENTS:-.}" --output /tmp/gitsy_watermarks.json`
4. Follow `$SKILL_ROOT/SKILL.md` to engineer human-written documentation (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`), generate SVG architecture and social preview assets (`scripts/screenshots/capture_and_brand.py`), configure lightweight CI if appropriate, synchronize with GitHub (`scripts/github-sync/sync_repository.py`), prepare release artifacts (`scripts/release/prepare_release.py`), and run the final quality gate (`scripts/verification/verify_publication.py`).
