# Security audit checklist

Run: `python3 scripts/run.py secret_scan.py --project "$P" --history`

## Why this phase is not optional

A repository is public forever. GitHub archives, forks, and package mirrors keep
copies. Pushing a credential for thirty seconds is enough for it to be scraped and
used. This is the one phase where a mistake cannot be cleaned up afterwards.

## What is checked

### 1. Credential material in publishable files

| Rule | Example | Severity |
|---|---|---|
| `secret.private-key` | `-----BEGIN RSA PRIVATE KEY-----` | blocker |
| `file.private-key` | `signing.pem`, `cert.p12`, `keystore` | blocker |
| `file.ssh-key` | `id_rsa`, `id_ed25519` | blocker |
| `file.env` | `.env`, `.env.production` | blocker |
| `secret.github-token` | `ghp_…`, `github_pat_…` | blocker |
| `secret.aws-key` | `AKIA…` | blocker |
| `secret.provider-key` | `sk-…`, `xoxb-…`, `AIza…`, `glpat-…`, `npm_…` | blocker |
| `secret.connection-string` | `postgres://user:pass@host/db` | blocker |
| `secret.assignment` | `password = "hunter2"`, `API_KEY: "…"` | high |
| `secret.jwt-or-bearer` | a live JWT | high |
| `file.credentials` | `credentials.json`, `.npmrc`, `service-account.json` | high |
| `file.db-dump` | `*.sql`, `*.sqlite`, `*.dump` | high |

Allowlisted by design, and reported as `info` with the reason: example/template
files (`.env.example`), documentation, test/fixture/vendor paths, placeholder
values (`changeme`, `${VAR}`, `<token>`), and files that implement a secret
detector.

### 2. Repository hygiene

| Rule | Meaning | Fix |
|---|---|---|
| `repo.no-gitignore` | nothing excluded | `ignorefix.py` |
| `repo.gitignore-gaps` | `.env` or `.DS_Store` unexcluded | merge patterns |
| `repo.tracked-but-ignored` | committed files that match an ignore rule | `git rm -r --cached` |
| `file.build-output` | `dist/`, `target/`, `node_modules/` tracked | remove from index |
| `file.cache-junk` | `__pycache__`, `.pyc`, tool caches tracked | remove from index |
| `file.dependency-dir` | vendored installed packages | remove; use a lockfile |
| `file.os-junk`, `file.ide-junk` | `.DS_Store`, `.idea/`, `xcuserdata/` | ignore |
| `file.archive-large` | committed `.zip`/`.dmg` | attach to a release |

### 3. History

`--history` greps every commit for high-confidence token shapes. A hit means the
secret was pushed at some point and must be treated as compromised even if the
current file is clean.

Purging history is destructive and needs authorization. `git filter-repo` rewrites
every hash, invalidating clones and forks. Rotation is mandatory either way; the
purge is damage control, not a fix.

## After a secret is found

1. **Rotate first.** Revoke the key with the provider. Assume it is already used.
2. Remove it from the working tree and add the file to `.gitignore`.
3. Re-scan: `secret_scan.py --history` should no longer show the working tree.
4. Tell the user, in plain terms: what it was, that it must be rotated (or has
   been), and that history still contains it if it was ever pushed.
5. Offer the history purge as a separate, explicitly authorized step.

## What never happens

- Credentials are never printed. Findings carry a 4-character prefix and a length.
- `.git` internals are never rewritten.
- Nothing is deleted without authorization.
- A "clean" verdict never claims the project is secure — only that these checks
  found nothing at this commit.

## Beyond credentials

Worth flagging when you notice it, from code you actually read:

- authentication that trusts a client-supplied role or user id
- `eval`/`exec`/`pickle.loads` on untrusted input
- string-built SQL
- secrets written to logs
- TLS verification disabled (`verify=False`, `InsecureSkipVerify`)

Report these as observations with `file:line`. Do not silently patch
security-sensitive logic as part of a publishing task — that needs its own review.
