# Presentation guidelines

A repository is judged in about eight seconds: title, one line, one image. Everything
else is read only if those three earn it. This file is about earning it honestly.

## The README

### Above the fold

```
# ProjectName

One sentence that says what it does and for whom.

Optional second line: the honest status.
```

Then a real visual, or nothing at all. A title, a clear sentence, and one true
screenshot beat six sections of prose.

### Section order that works

| Section | When it earns its place |
|---|---|
| What it is | always — 2–4 sentences, no marketing |
| Screenshot / demo | whenever one exists |
| Features | when the list is specific ("converts CSV to Markdown tables", not "powerful") |
| Requirements | whenever there is a minimum runtime or platform limit |
| Install | always — a real command that worked |
| Usage | always — with real output |
| Configuration | only when options exist |
| How it works | only for projects with non-obvious internals |
| Limitations | whenever there are any, which is always |
| Roadmap | only with real intent behind each item |
| Contributing / License | short pointers, not essays |

Drop any section you would have to pad. An absent "Architecture" heading costs
nothing; an empty one costs credibility.

### Voice

Write the way a competent developer explains their own tool to a colleague:
specific, direct, unimpressed with itself.

```markdown
# good
Reads a CSV file and prints a Markdown table. No dependencies, one file, works offline.

# bad
A revolutionary, blazing-fast, enterprise-grade solution that seamlessly
empowers you to transform your data workflows. 
```

Specific details create trust: "runs in about 4 ms on a 10k-row file" is credible
precisely because it is checkable. "Blazing fast" is a claim with nothing behind
it.

Dry humour is welcome in exactly two places: a limitations section and
troubleshooting. Never in install instructions, never in a security notice.

### Claims that need evidence

| Don't write | Unless |
|---|---|
| a CI badge | a workflow exists and has run green |
| a version badge | a real tag/release exists |
| "production ready" | you can point at the evidence |
| a platform list | you ran it there |
| download counts, user counts | never — you cannot know |
| "100% test coverage" | you generated the report this run |

`quality_gate.py` G5 checks the machine-detectable subset of this: unverifiable
badges, unqualified superlatives, and CI badges pointing at workflows that do not
exist.

## Screenshots

**A real screenshot of the real application.** Not a mockup, not a stock photo, not
an HTML page styled to look like the product.

Checklist before adding one:

- it shows the actual UI with plausible data
- no personal data, real names, email addresses, API keys, or account IDs
- text is legible at 50% scale (most readers are on a laptop)
- width ≥ 1200 px, file under ~500 KB
- consistent naming: `docs/assets/screenshots/main.png`, `settings.png`, `result.png`
- descriptive alt text — it is read by screen readers and search engines

For a CLI or a service, a rendered terminal transcript (`capture.py --kind
cli-output`) is a genuine screenshot: it is real output, styled. Say what it is in
the alt text.

Label anything conceptual as conceptual, in the alt text and in a caption. A
diagram of a planned architecture presented as the current one is a lie with nice
typography.

## Repository anatomy

```text
Project/
├── src/                    code
├── tests/                  tests, mirroring the source layout
├── docs/
│   ├── assets/screenshots/ images referenced by the README
│   └── *.md                longer guides
├── .github/
│   ├── workflows/          CI
│   ├── ISSUE_TEMPLATE/     issue forms
│   └── PULL_REQUEST_TEMPLATE.md
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CHANGELOG.md
├── SECURITY.md
└── .gitignore
```

Adapt to the project, don't impose. A 200-line Python script does not need
`docs/`, three issue templates, and a code of conduct. Empty structure reads as
template residue, which is exactly what it is.

## Files worth adding

| File | Add when |
|---|---|
| `LICENSE` | always, once the owner has chosen — never guess a license |
| `.gitignore` | always |
| `CONTRIBUTING.md` | you want outside pull requests, or the setup is non-obvious |
| `CHANGELOG.md` | there is a versioning scheme worth tracking |
| `SECURITY.md` | the project handles data, auth, or anything networked |
| `CODE_OF_CONDUCT.md` | there is a community; boilerplate without one is noise |
| `CITATION.cff` | it is research software |
| `.github/FUNDING.yml` | the owner has a real funding account |
| Issue templates | the project gets enough reports to need structure |

Never invent contact addresses, funding links, maintainer names, or response-time
promises. An unfilled `{{EMAIL}}` is a bug; a made-up address is a worse one.

## The repository's front door

Beyond the README, these are what a visitor sees:

- **Description** — one sentence, no emoji, no "🚀"
- **Topics** — up to 20 real ones; they drive discovery
- **Social preview image** — 1280×640, real product identity
- **Pinned release** — the current version with real assets
- **Default branch name** — `main`, unless the project already uses something else

## Anti-patterns

- The badge wall: eleven badges and no explanation of what the project does.
- The feature list of aspirations.
- Screenshots of an empty state.
- A "Demo" section linking to a dead deployment.
- Emoji section headers on a systems tool.
- The word "seamless" anywhere.
- A README that describes a different version than the code next to it.