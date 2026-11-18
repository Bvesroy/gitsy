# Mandatory Pre-Publish Security & Hygiene Checklist

Before running `git push` or `gh repo create`, verify every item below:

- [ ] **No API Keys or Tokens**: Scanned working tree and staged diff with `scripts/security-audit/scan_secrets_and_hygiene.py`.
- [ ] **No Private Keys or Certificates**: Confirmed zero `.pem`, `.key`, `.p12`, `.pfx`, `id_rsa`, or `id_ed25519` files are tracked.
- [ ] **No Environment Files**: Confirmed `.env`, `.env.local`, and `.env.production` are untracked and listed in `.gitignore` (while `.env.example` with safe dummy values is allowed).
- [ ] **No Accidental Databases or Dumps**: Confirmed zero `.sqlite`, `.sqlite3`, `.db`, or `.sql` dumps containing user data are staged.
- [ ] **Git History Checked**: Scanned recent commit diffs for accidentally committed credentials that were later deleted in the working tree. (If found, warn the user to rotate immediately.)
- [ ] **AI Watermarks Audited**: Scanned via `scripts/security-audit/watermark_audit.py` to remove self-inserted agent promo banners while preserving all third-party licenses and copyrights.
- [ ] **Visibility Confirmed**: Verified that private repositories remain private unless the user explicitly authorized public publication.
