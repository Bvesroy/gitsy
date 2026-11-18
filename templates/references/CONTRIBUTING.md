# Contributing to {{PROJECT_NAME}}

Thanks for taking the time to contribute.

## Before you start

- For anything larger than a bug fix, open an issue first so we can agree on the
  approach before you spend an evening on it.
- Search existing issues and pull requests; someone may already be on it.

## Development setup

```bash
{{SETUP_COMMANDS}}
```

{{DEV_NOTES}}

## Running the checks

```bash
{{CHECK_COMMANDS}}
```

A pull request should keep the build, the tests and the linters green. If a
check cannot run on your machine, say so in the pull request instead of
silently skipping it.

## Pull requests

- One logical change per pull request.
- Describe what changed and why; include screenshots for UI changes.
- Reference the issue it closes (`Closes #123`).
- Keep the diff focused. Reformatting an unrelated file makes review harder.
- New behaviour needs a test that fails without your change.

## Commit messages

{{COMMIT_CONVENTION}}

## Reporting bugs

Include the version or commit, your OS and runtime version, the exact command
you ran, and what you expected versus what happened. A minimal reproduction is
worth more than a long description.

## Security

Please do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
