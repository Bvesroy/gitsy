# Cross-Agent Compatibility Matrix

GITUP distinguishes between **Tested & Verified Compatibility** (validated via automated test harness and official specification conformance) and **Theoretical / Standard Compatibility** (supported via the open `.agents/skills` standard).

| Agent / Platform | Skill Discovery Path | Slash Command Adapter | Subagent Support | Compatibility Status |
| :--- | :--- | :--- | :--- | :--- |
| **Gemini / Antigravity Workspace** | `skills/gitu/SKILL.md` (`skills:save_skill`) | `/gitu` via skill description & `adapters/gemini-cli/gitu.toml` | Yes (`invoke_subagent`) | **Tested & Verified** (Registered & executed in VM sandbox) |
| **Claude Code** ([Docs](https://code.claude.com/docs/en/skills)) | `~/.claude/skills/gitu/SKILL.md` & `.claude/skills/gitu/SKILL.md` | `.claude/commands/gitu.md` (`/gitu <path>`) | Yes (`.claude/agents/`) | **Tested Structure & Official Spec Conformance** |
| **Gemini CLI** ([Docs](https://geminicli.com/docs/cli/custom-commands/)) | `~/.gemini/skills/gitu/SKILL.md` & `.agents/skills/gitu/SKILL.md` | `~/.gemini/commands/gitu.toml` (`{{args}}`) | Yes (Subagents) | **Tested Structure & Official Spec Conformance** |
| **OpenCode** ([Docs](https://skills-hub.ai/opencode-skills)) | `~/.opencode/skills/gitu/SKILL.md` & `.opencode/skills/gitu/SKILL.md` | `.opencode/commands/gitu.md` (`/gitu <path>`) | Yes (OpenCode Agents) | **Tested Structure & Official Spec Conformance** |
| **Qwen Code** ([Docs](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/)) | `~/.qwen/skills/gitu/SKILL.md` & `.agents/skills/gitu/SKILL.md` | `~/.qwen/commands/gitu.md` & `/gitu` skill slash invocation | Yes (SubAgents) | **Tested Structure & Official Spec Conformance** |
| **Kilo Code** ([Docs](https://kilo.ai/docs/customize/skills)) | `~/.kilo/skills/gitu/SKILL.md` & `~/.agents/skills/gitu/SKILL.md` | `.kilo/commands/gitu.md` & `~/.config/kilo/commands/gitu.md` | Yes (`subtask: true`) | **Tested Structure & Official Spec Conformance** |
| **Cursor / Windsurf / Codex CLI / Cline** | `.agents/skills/gitu/SKILL.md` | `adapters/generic/gitu-runner.sh` | Varies by host | **Theoretical / Standard Compatibility** via Agent Skills spec |
