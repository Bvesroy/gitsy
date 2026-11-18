# Multi-Agent Swarm Orchestration & Scoped Ownership

When running GITUP on an agent platform with subagent support (`invoke_subagent`, Claude Code subagents, Qwen Code SubAgents, or Kilo Code `subtask: true`), coordinate parallel workers using strict file-ownership boundaries so two agents never write to the same file concurrently:

| Role | Responsibility | Read Scope | Exclusive Write Scope |
| :--- | :--- | :--- | :--- |
| **Agent 1: Project Auditor** | Runs `discover_and_audit.py`, executes build/test checks | Entire project (read-only) | `/tmp/gitu_audit.json` |
| **Agent 2: Security Auditor** | Runs `scan_secrets_and_hygiene.py` & `watermark_audit.py` | Entire project + `.git` | `.gitignore`, `/tmp/gitu_security.json`, `/tmp/gitu_watermarks.json` |
| **Agent 3: Documentation Engineer** | Authors `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` | `/tmp/gitu_audit.json`, source files | `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.github/` |
| **Agent 4: Visual Designer** | Runs `capture_and_brand.py` and captures real CLI/UI screens | `/tmp/gitu_audit.json` | `docs/assets/*` |
| **Agent 5: GitHub & Release Engineer** | Runs `sync_repository.py` and `prepare_release.py` | All verified project files | `.git/*`, `dist/*` (runs after Agents 2, 3, 4 finish) |
| **Agent 6: Quality Assurance Gate** | Runs `verify_publication.py` and compiles Final Report | Entire project + `/tmp/gitu_*.json` | `/tmp/gitu_verification.json` |

## Sequential Fallback
If subagents are unavailable in the active runtime, execute Role 1 -> Role 2 -> Role 4 -> Role 3 -> Role 5 -> Role 6 sequentially in a single agent loop.
