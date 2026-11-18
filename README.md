# GITSY (`/gitsy`)

> Universal GitHub publishing, repository engineering, security auditing, visual presentation, and release automation agent skill.

GITSY takes any local software project and turns its GitHub repository into an honest, well-presented, security-verified open-source or private repository. It merges the multi-agent swarm orchestration and visual branding engine of `/gitu` with the atomic Unix-style tooling, sandboxed execution, and formal G1–G8 quality gates of `/gitup`.

```bash
/gitsy ~/Developer/MyProject
```

---

## Key Capabilities

1. **Project Discovery & Deep Inspection**
   - Automatically detects application types, languages, entry points, package managers, and executable build, test, and lint commands.
   - Executes real verification suites rather than hallucinating pass statuses.

2. **Security & Hygiene Hardening**
   - Redacts and detects exposed credentials, API keys, tokens, `.env` files, and database dumps in working trees and Git history.
   - Surgically merges stack-specific `.gitignore` rules without wiping existing custom patterns.
   - Audits and removes self-introduced AI generator watermarks (*"Created by Gemini"*, *"Powered by Claude"*) while strictly safeguarding legal copyright notices and license headers.

3. **Fact-Driven Documentation & Visual Branding**
   - Crafts human-written `README.md` documents grounded in verified facts, refusing unpopulated `{{PLACEHOLDER}}` tokens.
   - Generates production-ready SVG project logos, 1200x630 social preview cards, and module architecture diagrams into `docs/assets/`.
   - Probes and captures real UI or CLI output transcripts without substituting deceptive mockups.

4. **Multi-Agent Swarm Orchestration**
   - Coordinates 6 specialized subagents running concurrently across strict, disjoint file-ownership boundaries (Project Auditor, Security Auditor, Documentation Engineer, Visual Designer, GitHub Engineer, Quality Gate Auditor).
   - Gracefully falls back to a deterministic sequential loop when subagents are not supported.

5. **Safe GitHub Synchronization & Release Engineering**
   - Integrates with GitHub CLI (`gh`) with explicit visibility guards (private by default).
   - Contains zero force-push code paths; re-scans for secrets immediately before every push.
   - Cuts versioned releases with conventional release notes, `.tar.gz` and `.zip` distribution archives, and `SHA256SUMS.txt` checksum manifests.

6. **Formal G1–G8 Quality Gates**
   - **G1**: No secrets or credentials.
   - **G2**: Substantive README content.
   - **G3**: Zero leftover template placeholders.
   - **G4**: Zero broken relative links, anchors, or missing image assets.
   - **G5**: Claims backed by verified code evidence.
   - **G6**: Remote HEAD matches local branch and tag HEAD.
   - **G7**: Valid, consistent license.
   - **G8**: Zero agent branding in public documentation.

---

## Directory Architecture

```text
gitsy/
├── SKILL.md                                   # Open Agent Skill specification
├── README.md                                  # Comprehensive architecture & usage guide
├── LICENSE                                    # MIT License
├── install/                                   # Universal cross-agent installers
│   ├── install.sh                             # Multi-platform installer
│   ├── claude-code/install.sh
│   ├── gemini-cli/install.sh
│   ├── opencode/install.sh
│   ├── qwen-code/install.sh
│   ├── kilo-code/install.sh
│   └── generic/install.sh
├── adapters/                                  # Platform slash-command adapters
│   ├── claude-code/gitsy.md
│   ├── gemini-cli/gitsy.toml
│   ├── opencode/gitsy.md
│   ├── qwen-code/gitsy.md
│   ├── kilo-code/gitsy.md
│   └── generic/gitsy-runner.sh                # Standalone shell runner
├── scripts/                                   # Zero-dependency Python 3 tools
│   ├── run.py                                 # Sandboxed runner (prevents .pyc pollution)
│   ├── _bootstrap.py                          # Cache redirection & import shim
│   ├── lib/gitsy_common.py                    # Process, security & FS primitives
│   ├── detect_environment.py                  # CLI & toolchain environment detector
│   ├── project_scan.py                        # Deep manifest and command discovery
│   ├── prepare.py                             # One-pass read-only audit runner
│   ├── secret_scan.py                         # Secret scanner & redaction engine
│   ├── branding_scan.py                       # Watermark auditor & stripper
│   ├── ignorefix.py                           # Surgical .gitignore merger
│   ├── link_check.py                          # Dead link, anchor, and image validator
│   ├── license.py                             # SPDX license detector & applier
│   ├── render_template.py                     # Fact-driven template renderer
│   ├── capture.py                             # Real UI screenshot & CLI probe
│   ├── capture_and_brand.py                   # SVG architecture & visual branding generator
│   ├── gh_repo.py                             # GitHub CLI repository manager
│   ├── git_sync.py                            # Safe Git tracking, commit & push engine
│   ├── ci_plan.py                             # Verified GitHub Actions workflow generator
│   ├── release.py                             # Conventional release packager & checksums
│   └── quality_gate.py                        # G1–G8 quality gate evaluator
├── templates/                                 # Grounded templates & community health files
│   ├── README.template.md
│   ├── CHANGELOG.md
│   ├── CONTRIBUTING.md
│   ├── SECURITY.md
│   ├── FINAL_REPORT.template.md
│   └── github/
│       ├── PULL_REQUEST_TEMPLATE.md
│       └── ISSUE_TEMPLATE/
│           ├── bug_report.yml
│           └── feature_request.yml
├── references/                                # Architectural guides & checklists
│   ├── compatibility-matrix.md
│   ├── github-workflows.md
│   ├── presentation-guidelines.md
│   ├── release-guidelines.md
│   ├── security-checklist.md
│   ├── swarm-orchestration.md
│   └── workflow.md
└── tests/                                     # Automated test suites
    ├── selftest.py                            # 37 safety property regression tests
    └── test_gitsy_e2e.py                      # Full end-to-end integration lifecycle test
```

---

## Installation

Install globally across all supported AI coding agents:

```bash
bash install/install.sh --target all --scope global
```

Or for a specific platform:

```bash
bash install/claude-code/install.sh --scope global
bash install/gemini-cli/install.sh --scope global
bash install/opencode/install.sh --scope global
bash install/qwen-code/install.sh --scope global
bash install/kilo-code/install.sh --scope global
```

---

## Usage

Inside any supported AI coding agent:

```text
/gitsy ~/Developer/MyProject
```

Or run the standalone pipeline from terminal:

```bash
bash adapters/generic/gitsy-runner.sh ~/Developer/MyProject --version v1.0.0
```

---

## Running the Test Suites

GITSY ships with two complementary test suites:

1. **Safety Properties & Unit Regressions (37 tests)**:
   ```bash
   python3 tests/selftest.py
   ```

2. **Full Lifecycle End-to-End Integration**:
   ```bash
   python3 tests/test_gitsy_e2e.py
   ```

---

## License

Released under the [MIT License](LICENSE). Standard library Python 3 only; no external package dependencies required.
