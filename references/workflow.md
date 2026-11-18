# GITU workflow reference

Phase-by-phase detail: what to run, what to decide, and what to do when it fails.

---

## Phase A — Discover

```bash
python3 scripts/run.py project_scan.py --project "$P" --deep
```

Reads the project and reports, from files on disk only:

| Field | Use |
|---|---|
| `project.app_type` | drives capture strategy, release recipe, CI matrix |
| `languages` | drives toolchain and badge choices |
| `entry_points` | tells you what the program actually starts doing |
| `commands.*` | the exact install/build/test/lint commands to publish |
| `git` | whether it is a repo, remote, branch, tags, dirty state |
| `documentation` | what already exists and must be respected |
| `assets` | images you may reuse instead of capturing |
| `big_files` | candidates to move to a release instead of the tree |

**Read the source.** For a project under a few dozen files, open the main module
and the tests. You need to know what the program does before you can describe it
honestly. Filenames lie; `utils.py` is not a feature.

Monorepos: `monorepo: true` means several projects share one repository. Pick the
one the user pointed at, and say in the README which package the docs describe.

---

## Phase B — Project audit

Included in `prepare.py`. What it looks for:

- no version anywhere (releases need one)
- no documentation at all
- empty project
- large files that belong in a release
- no CI
- documented commands whose tool is not installed here (reported, not "fixed")

**Never claim to have fixed what you only identified.** If `cargo build` fails
because cargo is missing, the report says "could not verify the build: cargo is
not installed" — it does not say "build passes".

---

## Phase C — Security

```bash
python3 scripts/run.py secret_scan.py --project "$P" --history
```

Findings are redacted by design: you get `sk_liv…[41 chars, redacted]` and a
`file:line`. Open the file yourself if you need to understand the context — but
never copy the value into a commit message, an issue, or your report.

Severity handling:

| Severity | Meaning | Action |
|---|---|---|
| `blocker` | publishable secret, private key, `.env` | stop; rotate, remove, re-scan |
| `high` | hardcoded credential, history leak | resolve before publishing |
| `medium` | tracked junk, gitignore gaps, dumps | fix or justify |
| `low`/`info` | OS junk, possible false positives | mention only |

Fixing the gitignore is safe and automatic (`ignorefix.py` merges, never
replaces). Removing already-tracked files needs `git rm --cached` and a commit —
do it, it is reversible.

**A leaked secret needs rotation, not deletion.** Say this plainly. Purging
history (`git filter-repo`) rewrites every commit hash, breaks forks and clones,
and needs explicit authorization — recommend it, do not do it unasked.

---

## Phase D — Repository

Order matters:

1. `gh_repo.py inspect` — is there already a repo, and what is its visibility?
2. `git_sync.py init` — only when there is no repository. Never re-init.
3. `ignorefix.py` — before the first commit, so junk never enters the index.
4. `gh_repo.py create --visibility X` or `gh_repo.py connect` — one or the other.
5. `git_sync.py stage`/`commit` — meaningfully, in logical units.
6. `git_sync.py push --expect-visibility X`.

`create` requires an explicit `--visibility`. `push` compares that expectation
against GitHub's actual visibility and refuses on a mismatch. There is no
force-push code path.

Non-fast-forward on push means the remote has commits you do not: pull and
reconcile. Force-pushing over someone's work is not a synchronization strategy.

Commit messages:

```
feat: add CSV export
fix: handle empty input without crashing
docs: rewrite README from measured behaviour
chore: stop tracking Python bytecode
```

Not `update`, not `changes`, not `wip final v2`.

---

## Phase E — Documentation

Render the template, then rewrite what does not fit. The template's job is to stop
you forgetting a section, not to dictate voice.

Facts you must have before writing:

- the exact install command, run successfully
- the exact usage example, output pasted from a real run
- the runtime requirement (check the actual minimum, don't guess `3.8+`)
- which platforms you actually tested on
- what the project genuinely does not do

Sections that can be dropped when the project does not warrant them:
architecture, configuration, roadmap, acknowledgements, support. An empty section
is worse than an absent one.

---

## Phase F — Presentation

`capture.py --probe` tells you which strategy is possible and why not, when none
is. Strategies in preference order:

1. **web-local** — real running UI via Playwright. Needs `npx playwright install chromium`.
2. **macos-window** — real window via `screencapture -l <id>`. Needs a built `.app`.
3. **cli-output** — real terminal transcript as SVG. Always available, always honest.
4. **manual** — a precise shot list for the user.

What is never acceptable as a substitute for a screenshot:

- a stock photo
- a hand-written HTML mockup presented as the app
- an invented dashboard
- a screenshot from a different version dressed up as current

A conceptual diagram is fine when labelled conceptual, in alt text and caption
both.

---

## Phase G — Releases and CI

Version: follow whatever the project already does. No versioning at all → semver,
starting `0.1.0`, and say so in the notes.

Notes: generated from commits since the last tag, grouped. Then **read them
against the diff**. A commit subject that says "fix crash" may be a typo fix.

Artifacts: only formats the project really produces. Verify each exists and has a
plausible size before `gh release create`; give a checksum for anything
downloadable. Distinguish "source archive (generated by GitHub)" from "prebuilt
binary (built here)".

Never overwrite a published release. `release.py publish` refuses when the tag
exists.

CI: propose only workflows whose commands you found in the project. Mark them
unverified until Actions has run. Do not add a CI badge to the README before the
first green run — a red badge on day one is worse than no badge.

---

## Phase H — Verification

```bash
python3 scripts/run.py quality_gate.py --project "$P" --require-license --require-remote
python3 scripts/run.py git_sync.py verify --project "$P"
git clone <url> /tmp/check && cd /tmp/check && python3 -m pytest -q
```

The clone test is the one that matters: it is what a stranger experiences. If the
clone does not run, the repository is not done, regardless of what the gate says.

Report every gate. `FAIL` is a legitimate outcome that still ships value — the
user now knows exactly what to fix.
