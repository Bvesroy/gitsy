# Compatibility

Two separate questions, answered separately: what the *skill format* supports, and
what has actually been *run*.

Honesty rule: a row says `Tested` only if someone executed it and recorded the
result. Everything else is `Expected` (spec-compliant, unverified) or `Unknown`.

## What the skill needs to work

| Requirement | Needed for | Notes |
|---|---|---|
| `git` | everything | any version from the last decade |
| `python3` ≥ 3.9 | all bundled scripts | stdlib only, no `pip install` |
| `gh` (authenticated) | create repo, push verification, releases | `gh auth login` |
| `gh` scopes | private/public repo create, releases | `repo`, `workflow` |
| Node + `npx` | web screenshots only | optional |
| Playwright browser | web screenshots only | `npx playwright install chromium` |
| `screencapture` | macOS app screenshots | macOS only, optional |
| `ffmpeg` | GIF/video demos | optional |

Without `gh`, everything except GitHub-side operations still works: discovery,
audit, security, documentation, gate. The scripts report what is unavailable
rather than failing opaquely.

Without `python3`, the skill can still be followed manually — the scripts automate
checks, they are not the only path.

## Skill format support

`SKILL.md` follows the Agent Skills open specification: `name` (must match the
directory), `description` (≤1024 chars), plus optional `license`, `compatibility`,
`metadata`, `allowed-tools`. No agent-specific frontmatter, no XML in the body.

| Agent | Discovers skills from | Invocation | Status |
|---|---|---|---|
| OpenCode | `~/.agents/skills/`, `~/.config/opencode/skills/`, `~/.claude/skills/`, project equivalents | native `skill` tool; the model loads it when the description matches | **Tested** — this skill lives at `~/.agents/skills/gitup/` and is listed in the agent's available skills |
| Claude Code | `~/.claude/skills/`, `.claude/skills/` | `/gitup` (folder name becomes the command) | Expected — spec-compliant; `install/claude-code/` symlinks it |
| OpenAI Codex CLI | `~/.agents/skills/`, `.agents/skills/` | skill picked up from the description | Expected — same folder already in place |
| Cursor | `~/.agents/skills/`, `~/.cursor/skills/`, `~/.claude/skills/` | model-loaded | Expected |
| Gemini CLI | `~/.gemini/skills/`, `~/.agents/skills/` | model-loaded or `/skills` | Expected |
| GitHub Copilot (CLI/cloud) | `~/.agents/skills/`, `~/.copilot/skills/` | model-loaded | Expected |
| Qwen Code / Kilo Code | `~/.agents/skills/` or their own dir + an adapter file | adapter command | Expected — `adapters/` provides the wrapper |
| Anything else | any of the above paths | copy `adapters/generic/gitup.md` into its prompt/command directory | Unknown by design |

"Expected" means: the file follows the documented format and sits in a directory
the vendor documents. It has not been executed in that agent on this machine.
Treat it as likely, not proven.

## What "Tested" covers here

Executed during development on macOS 26 (arm64), Python 3.15, git 2.56, gh 2.102:

- `project_scan.py` on real projects (a Tauri skill folder, a Python service, a CLI)
- `secret_scan.py` against a fixture with a live-shaped key, a `.env`, a private
  key, a database URL and a commit history leak — all detected, all redacted
- `ignorefix.py` merge into an existing `.gitignore`
- `gh_repo.py create` — created a real private repository on GitHub
- `git_sync.py` init → stage → commit → push → verify against that repository,
  with the remote head confirmed by `ls-remote` and a fresh clone
- the visibility guard refusing a `public` expectation on a private repo
- the secret-scan guard refusing a push with a committed AWS key
- `quality_gate.py` failing a messy repo and passing the prepared one (8/8 gates)
- `link_check.py` catching a missing image, a broken anchor and a case mismatch
- `render_template.py` refusing to leave placeholders
- `release.py` plan/notes/package/publish dry runs, and the "release exists" refusal
- `ci_plan.py` writing a valid workflow, refusing test/release workflows with no
  command to run
- `capture.py` producing a real CLI transcript SVG, and reporting `ok: false` for a
  web capture with no Playwright browser installed

**Not tested here:**

- web screenshots end to end (Playwright browser binaries are not installed;
  the failure path is tested, the success path is not)
- macOS window capture (no built `.app` was available to launch)
- Windows or Linux behaviour of the scripts
- any agent other than OpenCode loading the skill
- a real public release publication (deliberately not performed — publishing a
  public release needs the owner's authorization)

## Known environment limits

- **Windows**: the scripts are standard-library Python and avoid POSIX-only calls,
  but path handling and `run.py`'s temp-cache logic have not been exercised there.
  Use `python3 scripts\<script>.py` directly if `run.py` misbehaves.
- **No `write` access to the skill directory**: `run.py` prevents bytecode writes,
  but agents that import the scripts directly may still create `__pycache__`.
- **Rate limits**: `gh` and raw GitHub API calls can hit unauthenticated limits on
  shared CI runners. Authenticate with a token.
- **Network**: `link_check.py --remote` and remote repo inspection fail offline;
  the scripts report the failure instead of pretending success.
