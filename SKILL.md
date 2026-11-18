---
name: gitsy
description: Universal GitHub publishing, repository engineering, security auditing, visual presentation, and release automation skill. Takes any local software project and publishes or updates its GitHub repository as a professional, trustworthy, security-verified presentation of the actual software. Covers discovery, secret scanning, surgical gitignore hardening, AI watermark audit, documentation engineering, real UI/CLI & SVG architecture cards, GitHub Actions CI, conventional releases with SHA-256 checksums, and formal G1-G8 quality gates. Operates via multi-agent swarm coordination or single-agent sequential execution.
license: MIT
allowed-tools: execute_bash view_file write_to_file invoke_subagent
allowedTools:
  - execute_bash
  - run_shell_command
  - bash
  - view_file
  - read_file
  - write_to_file
  - write_file
compatibility: OpenCode, Claude Code, Gemini CLI, Qwen Code, Kilo Code, Antigravity, Cursor, Codex CLI, and any Agent Skills (.agents/skills) compatible agent.
metadata:
  version: 1.0.0
  command: /gitsy <project-location>
  category: github-publishing
---

# GITSY: Universal GitHub Publishing & Repository Engineering Skill

GITSY takes any local software project and turns its GitHub repository into an honest, well-presented, security-verified piece of software: real screenshots and SVG architecture cards, a README that matches the code, zero leaked credentials, surgical `.gitignore` rules, correct checksummed releases, and rigorous verification that the remote repository matches local HEAD.

```text
/gitsy ~/Developer/MyProject
```

The project is the client. Publish what it actually does, never what it could have done.

---

## The Core Rule That Outranks Everything

**Never state a fact about the software that you did not verify.**

Every claim in a README, badge, release note, architecture diagram, or commit message must be backed by inspected source code or executed verification: a test that passed, a command whose output you saw, a file you opened, or an API response you fetched. If you could not verify it, write that down in the final report and in the README's limitations — do not smooth it over with confident marketing prose.

- **No invented features, platforms, benchmarks, download counts, contributors, or "production ready" claims.**
- **No badge that is not backed by a real file or a workflow that has really run.**
- **No screenshot that is not a capture of the real application.**
- **No release artifact you did not build and verify the size and checksum of.**
- **"I could not verify this" is a complete, acceptable, and required sentence when unverified.**

---

## Safety & Authorization Boundaries

Proceed autonomously for all local inspection, static analysis, secret scanning, `.gitignore` hardening, documentation drafting, visual diagram generation, local staging, and local commits. **Pause and obtain explicit user authorization before:**

1. **Publishing a brand-new public repository** when public/private visibility has not been specified (default to Private until confirmed).
2. **Changing an existing repository's visibility** (especially private to public).
3. **Force-pushing** (`git push --force` or `--force-with-lease`) or rewriting published Git history. The tool contains zero force-push paths by design.
4. **Deleting existing branches, tags, releases, or user data.**
5. **Modifying an existing software license.**
6. **Uploading or pushing any file flagged with high-severity secrets or private keys.**
7. **Executing paid cloud or third-party operations.**

---

## Script Execution Engine & JSON Interface

All scripts in `scripts/` are written in standard Python 3 (stdlib only, no external dependencies). They can be run via the sandboxed launcher so nothing is written into the skill folder:

```bash
python3 scripts/run.py <script>.py --project /path/to/project [options]
```

### Standard Output & Exit Code Contract
Every script prints structured JSON on **stdout** — for success, findings, and failures alike:
- `0` — Clean / success.
- `1` — Actionable findings (e.g., links to fix, watermarks to review).
- `2` — Blocked or usage error (e.g., live credential detected, required argument missing).

A failure object always carries `"error"`. Usage errors carry `"code": "usage"`. `--help` is the deliberate exception: prints human-readable text and exits `0`.

---

## Multi-Agent Swarm Coordination

When running on platforms that support subagents (`invoke_subagent`, Claude Code subagents, Qwen Code subagents, or Kilo Code `subtask: true`), delegate non-conflicting phases in parallel using strict file-ownership boundaries (`references/swarm-orchestration.md`):

| Role | Responsibility | Read Scope | Exclusive Write Scope |
| :--- | :--- | :--- | :--- |
| **Agent 1: Project Auditor** | Runs `detect_environment.py`, `project_scan.py`, executes build/test checks | Entire project (read-only) | `/tmp/gitsy_audit.json` |
| **Agent 2: Security & Hygiene Auditor** | Runs `secret_scan.py`, `ignorefix.py`, and `branding_scan.py` | Entire project + `.git` | `.gitignore`, `/tmp/gitsy_security.json`, `/tmp/gitsy_watermarks.json` |
| **Agent 3: Documentation Engineer** | Authors `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, and issue/PR templates | `/tmp/gitsy_audit.json`, source files | `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.github/` |
| **Agent 4: Visual Designer** | Runs `capture.py` and `capture_and_brand.py` to produce SVG architecture, logo, social cards, or real UI shots | `/tmp/gitsy_audit.json` | `docs/assets/*` |
| **Agent 5: GitHub & Release Engineer** | Runs `gh_repo.py`, `git_sync.py`, `ci_plan.py`, and `release.py` | All verified project files | `.git/*`, `dist/*` (runs after Agents 2, 3, 4 finish) |
| **Agent 6: Quality Assurance Gate** | Runs `quality_gate.py` (evaluates G1-G8), verifies remote clone, compiles Final Report | Entire project + `/tmp/gitsy_*.json` | `/tmp/gitsy_verification.json` |

### Sequential Fallback
If subagents are unavailable in the host runtime, execute the phases sequentially in your main loop: Role 1 → Role 2 → Role 4 → Role 3 → Role 5 → Role 6.

---

## Complete End-to-End Workflow

### Phase A: Environment & Project Discovery
Inspect available CLIs and discover the target project's languages, frameworks, entry points, package managers, and build/test commands:

```bash
python3 scripts/run.py detect_environment.py --json
python3 scripts/run.py project_scan.py --project "$P" --deep
```

Execute discovered build, lint, and test commands if the required toolchain is installed. Record pre-existing test/build limitations honestly.

### Phase B: One-Pass Read-Only Audit
Before modifying any files, execute the read-only preview:

```bash
python3 scripts/run.py prepare.py --project "$P" --history --out .gitsy/prepare.json
```

This aggregates project discovery, secret audit, presentation checks, and quality gates into one inspection report without changing a single byte.

### Phase C: Security Hygiene & AI Watermark Cleanup
1. **Secret Scanning**:
   ```bash
   python3 scripts/run.py secret_scan.py --project "$P" --history
   python3 scripts/run.py ignorefix.py --project "$P" --write
   ```
   If `secret_scan.py` reports blocker credentials (live tokens, AWS/Stripe keys, `.env`, private keys), halt upload of those files immediately. Never commit secrets. Ensure `.gitignore` excludes sensitive files without broad matching bugs.

2. **AI Watermark & Branding Audit**:
   ```bash
   python3 scripts/run.py branding_scan.py --project "$P" --strip --write
   ```
   Strips self-introduced agent signatures ("Created by Gemini", "Generated by OpenCode", "Built with Claude") while strictly preserving legal copyrights, open-source licenses, and implementation comments. Never insert "100% human-written" claims.

### Phase D: Repository & Remote Synchronization
Verify GitHub CLI authentication and inspect or create the repository:

```bash
python3 scripts/run.py gh_repo.py inspect --project "$P"
python3 scripts/run.py git_sync.py init --project "$P"
python3 scripts/run.py gh_repo.py create --project "$P" --name NAME --visibility private --description "..." --add-remote
```

**Visibility is an explicit decision.** If visibility was not specified, default to `private` or prompt the user.

Stage verified files and commit with Conventional Commits:

```bash
python3 scripts/run.py git_sync.py stage --project "$P" --paths README.md docs/ .gitignore
python3 scripts/run.py git_sync.py commit --project "$P" --message "docs: prepare verified documentation and repository assets"
python3 scripts/run.py git_sync.py push --project "$P" --expect-visibility private
```

`git_sync.py push` automatically re-runs secret scanning before pushing, refuses visibility mismatches, and has no force-push option.

### Phase E: Professional Documentation
Author an accurate, human-sounding `README.md` grounded in inspected code facts:
- Open with what the project does and who it is for in plain language.
- Show working examples and verified commands.
- State limitations plainly.
- Eliminate AI marketing cliches (*"revolutionary"*, *"seamless"*, *"delve"*, *"tapestry"*).

Render template safely without leftover skeleton placeholders:

```bash
python3 scripts/run.py render_template.py --template ./templates/references/README.md --values .gitsy/readme-facts.json --out "$P/README.md" --if-exists skip
python3 scripts/run.py link_check.py --project "$P"
```

Also add `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.editorconfig`, and `.github/` templates where appropriate.

### Phase F: Visual Presentation & Architecture Assets
Capture real application UI or render SVG architecture cards into `docs/assets/`:

```bash
# Generate clean SVG architecture diagrams, social cards, and logos grounded in code:
python3 scripts/run.py capture_and_brand.py --project "$P" --audit-json /tmp/gitsy_audit.json

# Or probe and capture real running UI / terminal output:
python3 scripts/run.py capture.py --project "$P" --probe
```

If a screenshot tool (e.g. Playwright) is unavailable, report that screenshots are missing and provide the shot list — never substitute stock images or fake mockups.

### Phase G: CI Workflows & Release Packaging
1. **GitHub Actions CI**:
   ```bash
   python3 scripts/run.py ci_plan.py plan --project "$P"
   python3 scripts/run.py ci_plan.py write --project "$P"
   ```
   Only generates workflows for commands that actually exist. Workflows use minimal read-only permissions (`permissions: contents: read`).

2. **Release Management**:
   ```bash
   python3 scripts/run.py release.py plan --project "$P"
   python3 scripts/run.py release.py notes --project "$P" --version 1.0.0 --write RELEASE_NOTES.md
   python3 scripts/run.py release.py package --project "$P" --version 1.0.0 --out dist
   python3 scripts/run.py release.py publish --project "$P" --version 1.0.0 --artifacts "dist/*"
   ```
   Computes `SHA256SUMS.txt`, groups notes by Conventional Commit types, and attaches distribution archives.

### Phase H: Formal G1–G8 Quality Gates & Final Report
Run the quality gate engine:

```bash
python3 scripts/run.py quality_gate.py --project "$P" --require-license --require-remote
python3 scripts/run.py git_sync.py verify --project "$P"
```

The 8 Formal Quality Gates:
- **G1 (No Secrets)**: 0 credentials in working tree or history.
- **G2 (Substantive README)**: Substantive overview, installation, and usage (not a stub).
- **G3 (No Placeholders)**: 0 unrendered `{{...}}` tokens.
- **G4 (No Broken Links)**: All local relative links, images, and anchors resolve.
- **G5 (Verified Claims)**: Every feature/command verified against real files.
- **G6 (Remote Match)**: Remote branch and tag refs match local HEAD.
- **G7 (License Consistent)**: License text and manifests agree.
- **G8 (No Agent Signatures)**: Zero AI branding or watermark signatures in public docs.

Compile the final user report following `templates/FINAL_REPORT.template.md` with explicit `PASS`, `WARN`, or `FAIL` statuses.
