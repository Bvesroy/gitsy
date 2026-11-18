#!/usr/bin/env python3
"""gitup self-tests - prove the tooling does what the docs claim.

Each test builds a throwaway fixture in a temp dir and asserts on the JSON a
script emits. No network, no GitHub, no writes outside the temp dir. Run from the
skill directory:

    python3 tests/selftest.py            # all tests
    python3 tests/selftest.py -v         # with names
    python3 tests/selftest.py secret     # only tests whose name matches

The point of these tests is the *safety properties*: that a secret blocks a push,
that a visibility mismatch blocks a push, that a template placeholder is refused,
that an existing license is not replaced. Those are the behaviours that must not
regress.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
RUN = SKILL / "scripts" / "run.py"

# Synthetic, non-functional credentials assembled at runtime. Written as one
# contiguous literal they trip static scanners and GitHub push protection, so the
# prefix is split; the scanners under test still see the full value at runtime.
FAKE_CARD_KEY = "sk_" + "live_" + "51H8xQ2eZvKYlo2C9abcdefghijklmnop"
FAKE_CARD_KEY_ALT = "sk_" + "live_" + "SUPERSECRETVALUEDONOTPRINT1234567890"
sys.pycache_prefix = os.path.join(tempfile.gettempdir(), "gitup-selftest-pyc")


def run_script(script: str, *args, expect=None, cwd=None):
    """Invoke a gitup script and return (exit_code, parsed_json_or_text)."""
    argv = [sys.executable, "-B", str(RUN), script, *args]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300, env=env,
                          cwd=cwd or str(SKILL))
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out.startswith(("{", "[")) else out
    except json.JSONDecodeError:
        data = out
    if expect is not None and proc.returncode not in (expect if isinstance(expect, tuple) else (expect,)):
        raise AssertionError(
            f"{script} exit {proc.returncode}, expected {expect}\n"
            f"stdout: {out[:800]}\nstderr: {proc.stderr[:800]}")
    return proc.returncode, data


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

class Fixture:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="gitup-test-"))

    def write(self, relpath: str, content: str) -> Path:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git_init(self):
        git(["init", "-q", "-b", "main"], self.root)
        git(["-c", "user.email=t@example.com", "-c", "user.name=Test", "add", "-A"], self.root)
        git(["-c", "user.email=t@example.com", "-c", "user.name=Test",
             "commit", "-qm", "init"], self.root)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #

@test
def test_discovery_python_cli():
    f = Fixture()
    try:
        f.write("tinytool.py", '#!/usr/bin/env python3\n"""A tool."""\n'
                               'import argparse\n\nif __name__ == "__main__":\n    argparse.ArgumentParser().parse_args()\n')
        f.write("test_tinytool.py", "def test_ok():\n    assert True\n")
        _, data = run_script("project_scan.py", "--project", str(f.root), expect=0)
        assert data["project"]["name"] == f.root.name
        assert "cli" in data["project"]["app_type"], data["project"]["app_type"]
        assert any(c["cmd"].endswith("pytest") for c in data["commands"]["test"]), \
            data["commands"]["test"]
        assert data["entry_points"], "entry point not detected"
        assert data["git"]["is_repo"] is False
    finally:
        f.close()


@test
def test_discovery_does_not_invent_manifests():
    """A bare Python dir must not be reported as having a Gemfile or composer.json."""
    f = Fixture()
    try:
        f.write("main.py", "print('hi')\n")
        _, data = run_script("project_scan.py", "--project", str(f.root), expect=0)
        install = " ".join(c["cmd"] for c in data["commands"]["install"])
        assert "bundle install" not in install, "invented a Gemfile install"
        assert "composer install" not in install, "invented a composer install"
        assert data["manifests"] == [], data["manifests"]
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# security - the properties that must never regress
# --------------------------------------------------------------------------- #

@test
def test_secret_scan_blocks_live_shaped_key():
    f = Fixture()
    try:
        f.write("app.py", f'API_KEY = "{FAKE_CARD_KEY}"\n')
        f.write("README.md", "# hi\n")
        code, data = run_script("secret_scan.py", "--project", str(f.root), expect=2)
        ids = {x["id"] for x in data["findings"]}
        assert "secret.provider-key" in ids, ids
        assert data["verdict"] == "BLOCK"
    finally:
        f.close()


@test
def test_secret_scan_never_prints_the_secret():
    f = Fixture()
    secret = FAKE_CARD_KEY_ALT
    try:
        f.write("app.py", f'KEY = "{secret}"\n')
        _, data = run_script("secret_scan.py", "--project", str(f.root))
        blob = json.dumps(data)
        assert secret not in blob, "the scanner printed the credential"
        assert "redacted" in blob.lower(), "expected a redaction marker"
        assert secret[:10] not in blob, "the scanner printed most of the credential"
    finally:
        f.close()


@test
def test_secret_scan_allows_placeholders_and_examples():
    f = Fixture()
    try:
        f.write(".env.example", "API_KEY=your-key-here\nDB_PASSWORD=changeme\n")
        f.write("config.py", 'api_key = os.environ["API_KEY"]\nsecret = "${SECRET}"\n')
        _, data = run_script("secret_scan.py", "--project", str(f.root))
        blockers = [x for x in data["findings"] if x["severity"] == "blocker"
                    and x["id"].startswith(("secret.", "file."))]
        assert not blockers, f"placeholder values flagged as secrets: {blockers}"
    finally:
        f.close()


@test
def test_secret_scan_flags_tracked_bytecode():
    """Build junk that is already committed must be reported, not skipped."""
    if not shutil.which("git"):
        return
    f = Fixture()
    try:
        f.write("app.py", "print(1)\n")
        f.write("__pycache__/app.cpython-311.pyc", "not really bytecode")
        f.git_init()
        _, data = run_script("secret_scan.py", "--project", str(f.root))
        ids = {x["id"] for x in data["findings"]}
        assert "file.cache-junk" in ids, ids
    finally:
        f.close()


@test
def test_gitignore_matching_has_no_substring_false_positive():
    sys.path.insert(0, str(SKILL / "scripts"))
    sys.path.insert(0, str(SKILL / "scripts" / "lib"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("ss", SKILL / "scripts" / "secret_scan.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    entries = ["dist-Mac/", ".DS_Store", "node_modules/"]
    assert m._gitignore_covers(entries, ".DS_Store")
    assert m._gitignore_covers(entries, "node_modules/")
    assert not m._gitignore_covers(entries, "dist/"), "dist/ wrongly matched dist-Mac/"
    assert not m._gitignore_covers(entries, "build/")


@test
def test_ignorefix_merges_and_never_replaces():
    f = Fixture()
    try:
        f.write(".gitignore", "# my hand-written rules\nmy-local-file.txt\n")
        _, data = run_script("ignorefix.py", "--project", str(f.root), expect=0)
        assert data["changed"]
        text = (f.root / ".gitignore").read_text()
        assert "my-local-file.txt" in text, "ignorefix destroyed existing rules"
        assert ".DS_Store" in text and ".env" in text
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# git sync guards
# --------------------------------------------------------------------------- #

@test
def test_push_has_no_force_flag():
    code, data = run_script("git_sync.py", "push", "--project", str(SKILL), "--force")
    assert code != 0, "push accepted a --force flag"


@test
def test_push_fails_without_remote():
    f = Fixture()
    try:
        f.write("a.txt", "x")
        f.git_init()
        code, data = run_script("git_sync.py", "push", "--project", str(f.root))
        assert code == 1
        assert "no origin remote" in json.dumps(data)
    finally:
        f.close()


@test
def test_push_blocks_on_secret():
    f = Fixture()
    try:
        f.write("app.py", 'AWS = "AKIAIOSFODNN7EXAMPLE"\n')
        f.git_init()
        git(["remote", "add", "origin", "https://github.com/example/nonexistent.git"], f.root)
        code, data = run_script("git_sync.py", "push", "--project", str(f.root))
        assert code == 1
        assert data.get("blocked") == "secret scan blockers", data
    finally:
        f.close()


@test
def test_stage_rejects_paths_outside_project():
    f = Fixture()
    try:
        f.write("a.txt", "x")
        f.git_init()
        _, data = run_script("git_sync.py", "stage", "--project", str(f.root),
                             "--paths", "/etc/passwd")
        rejected = data.get("rejected", [])
        assert any("outside" in r["why"] for r in rejected), data
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# docs and templates
# --------------------------------------------------------------------------- #

@test
def test_render_template_refuses_missing_facts():
    f = Fixture()
    try:
        values = f.write("values.json", json.dumps({"PROJECT_NAME": "X"}))
        out = f.root / "README.md"
        code, data = run_script("render_template.py",
                                "--template", str(SKILL / "templates/references/README.md"),
                                "--values", str(values), "--out", str(out))
        assert code == 2, f"renderer accepted unfilled placeholders: {data}"
        assert not out.exists(), "renderer wrote an incomplete file"
    finally:
        f.close()


@test
def test_render_template_drops_empty_sections():
    f = Fixture()
    try:
        facts = {k: "filled" for k in
                 ("PROJECT_NAME", "TAGLINE", "STATUS_LINE", "WHAT_IT_IS", "WHAT_IT_IS_NOT",
                  "FEATURE_LIST", "REQUIREMENTS", "INSTALL", "USAGE", "CONFIGURATION",
                  "ARCHITECTURE", "TREE", "DEVELOPMENT", "TROUBLESHOOTING", "LIMITATIONS",
                  "ROADMAP", "CONTRIBUTING", "LICENSE", "ACKNOWLEDGEMENTS")}
        facts["CONFIGURATION"] = ""
        facts["ROADMAP"] = ""
        values = f.write("v.json", json.dumps(facts))
        out = f.root / "README.md"
        run_script("render_template.py",
                   "--template", str(SKILL / "templates/references/README.md"),
                   "--values", str(values), "--out", str(out), expect=0)
        text = out.read_text()
        assert "{{" not in text
        assert "## Configuration" not in text, "empty section was left in"
        assert "## Roadmap" not in text
        assert "## Install" in text
    finally:
        f.close()


@test
def test_link_check_catches_missing_image_and_anchor():
    f = Fixture()
    try:
        f.write("README.md", "# T\n\n![x](docs/nope.png)\n[a](#missing-heading)\n\n## Present\n")
        code, data = run_script("link_check.py", "--project", str(f.root))
        ids = {x["id"] for x in data["findings"]}
        assert "link.file-missing" in ids, ids
        assert "link.anchor-missing" in ids, ids
        assert code == 1
    finally:
        f.close()


@test
def test_link_check_accepts_valid_tree():
    f = Fixture()
    try:
        f.write("README.md", "# T\n\n![x](docs/ok.png)\n[a](#usage)\n\n## Usage\n")
        f.write("docs/ok.png", "png-bytes")
        _, data = run_script("link_check.py", "--project", str(f.root), expect=0)
        assert not data["findings"], data["findings"]
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# license
# --------------------------------------------------------------------------- #

@test
def test_license_requires_holder_and_never_replaces():
    f = Fixture()
    try:
        code, data = run_script("license.py", "write", "--project", str(f.root),
                                "--spdx", "MIT", "--holder", "   ")
        assert code == 1 and "holder" in data.get("blocked", "")
        run_script("license.py", "write", "--project", str(f.root), "--spdx", "MIT",
                   "--holder", "Test Holder", "--year", "2026", expect=0)
        text = (f.root / "LICENSE").read_text()
        assert "Test Holder" in text and "2026" in text
        code, data = run_script("license.py", "write", "--project", str(f.root),
                                "--spdx", "Apache-2.0", "--holder", "Other")
        assert code == 1 and "already exists" in data.get("blocked", "")
        assert "Test Holder" in (f.root / "LICENSE").read_text(), "license was replaced"
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# quality gate
# --------------------------------------------------------------------------- #

@test
def test_gate_fails_messy_repo():
    f = Fixture()
    try:
        f.write("app.py", f'API_KEY = "{FAKE_CARD_KEY}"\n')
        code, data = run_script("quality_gate.py", "--project", str(f.root))
        assert code == 1
        assert data["verdict"] == "FAIL"
        failed = {g["id"] for g in data["gates"] if not g["passed"]}
        assert "G1" in failed, f"gate did not fail on a blocker secret: {failed}"
        assert "G2" in failed, f"gate accepted a repo with no README: {failed}"
    finally:
        f.close()


@test
def test_gate_flags_unverifiable_badge():
    f = Fixture()
    try:
        body = "# T\n\n![stars](https://img.shields.io/badge/stars-9999-blue)\n\n" + \
               "## Install\n\n```bash\npip install x\n```\n\n## Usage\n\n```bash\nx --help\n```\n" + \
               ("filler text to pass the size check. " * 30)
        f.write("README.md", body)
        _, data = run_script("quality_gate.py", "--project", str(f.root), "--soft")
        g5 = next(g for g in data["gates"] if g["id"] == "G5")
        assert not g5["passed"], "an unverifiable star badge passed the claim gate"
    finally:
        f.close()


@test
def test_gate_ignores_placeholders_in_templates_and_quoted_prose():
    """A template is supposed to contain placeholders; a README is not."""
    f = Fixture()
    try:
        body = "# T\n\n## Install\n\n```bash\nx\n```\n\n## Usage\n\n```bash\ny\n```\n" + \
               ("substance. " * 60)
        f.write("README.md", body)
        f.write("templates/README.md", "# {{PROJECT_NAME}}\n\n{{INSTALL}}\n")
        f.write("references/notes.md",
                "The renderer refuses to leave `{{PLACEHOLDER}}` in a file.\n")
        _, data = run_script("quality_gate.py", "--project", str(f.root), "--soft")
        g3 = next(g for g in data["gates"] if g["id"] == "G3")
        assert g3["passed"], g3["evidence"]
    finally:
        f.close()


@test
def test_gate_flags_a_placeholder_left_in_the_real_readme():
    f = Fixture()
    try:
        body = "# {{PROJECT_NAME}}\n\n## Install\n\n```bash\nx\n```\n" + ("filler. " * 60)
        f.write("README.md", body)
        _, data = run_script("quality_gate.py", "--project", str(f.root), "--soft")
        g3 = next(g for g in data["gates"] if g["id"] == "G3")
        assert not g3["passed"], "an unfilled placeholder in the README passed"
    finally:
        f.close()


@test
def test_gate_does_not_flag_disclaimed_superlatives():
    """"Will not: claim production ready" is honesty, not a claim."""
    f = Fixture()
    try:
        body = ("# T\n\n## Install\n\n```bash\nx\n```\n\n## Usage\n\n```bash\ny\n```\n\n"
                "## What it will not do\n\n"
                "- Invent a benchmark or a \"production ready\".\n"
                "- Claim it is battle tested.\n" + ("substance. " * 60))
        f.write("README.md", body)
        _, data = run_script("quality_gate.py", "--project", str(f.root), "--soft")
        g5 = next(g for g in data["gates"] if g["id"] == "G5")
        assert g5["passed"], f"disclaimers were read as claims: {g5['evidence']}"
    finally:
        f.close()


@test
def test_gate_still_flags_a_real_superlative_in_prose():
    f = Fixture()
    try:
        body = ("# T\n\n## Install\n\n```bash\nx\n```\n\n## Features\n\n"
                "This tool is production ready and battle tested.\n" + ("substance. " * 60))
        f.write("README.md", body)
        _, data = run_script("quality_gate.py", "--project", str(f.root), "--soft")
        g5 = next(g for g in data["gates"] if g["id"] == "G5")
        assert not g5["passed"], "a real superlative passed the claim gate"
    finally:
        f.close()


@test
def test_branding_ignores_headings_and_fenced_commands():
    """A section titled after an agent documents an integration, it does not
    sign the file."""
    f = Fixture()
    try:
        f.write("README.md",
                "### Claude Code\n\n```bash\nln -s x ~/.agents/skills/gitup\n```\n"
                "### OpenCode\n\n```bash\nmkdir -p ~/.agents/skills\n```\n")
        _, data = run_script("branding_scan.py", "--project", str(f.root), expect=0)
        hits = [x for x in data["findings"] if "README.md" in str(x["evidence"])]
        assert not hits, f"documentation mistaken for branding: {hits}"
    finally:
        f.close()


@test
def test_branding_still_catches_a_real_signature():
    f = Fixture()
    try:
        f.write("README.md", "# T\n\nSome prose.\n\nClaude Code\n")
        _, data = run_script("branding_scan.py", "--project", str(f.root), expect=0)
        assert any("Claude Code" in x["detail"] for x in data["findings"]), data["findings"]
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# branding
# --------------------------------------------------------------------------- #

@test
def test_branding_found_but_copyright_protected():
    f = Fixture()
    try:
        f.write("main.py", "# Generated by Claude Code\n"
                           "# Copyright (c) 2026 Example Corp. SPDX-License-Identifier: MIT\n"
                           "print(1)\n")
        f.write("LICENSE", "Generated by OpenCode\nCopyright 2026 X\n")
        _, data = run_script("branding_scan.py", "--project", str(f.root), expect=0)
        titles = [x["title"] for x in data["findings"]]
        assert any("main.py" in t for t in titles), titles
        assert not any("LICENSE" in t for t in titles), "LICENSE was scanned"
        main_finding = next(x for x in data["findings"] if "main.py:1" in str(x["evidence"]))
        assert main_finding["autofix"] == "", \
            "offered to strip a line from a file with an SPDX header"
    finally:
        f.close()


@test
def test_branding_does_not_flag_skill_docs():
    f = Fixture()
    try:
        f.write("SKILL.md", "---\nname: x\n---\nThis file explains how agents behave.\n")
        _, data = run_script("branding_scan.py", "--project", str(f.root), expect=0)
        assert not [x for x in data["findings"] if "SKILL.md" in str(x["evidence"])]
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# release and CI
# --------------------------------------------------------------------------- #

@test
def test_release_plan_and_tag_guard():
    f = Fixture()
    try:
        f.write("pyproject.toml", '[project]\nname = "x"\nversion = "1.4.2"\n')
        f.git_init()
        _, data = run_script("release.py", "plan", "--project", str(f.root), expect=0)
        assert data["proposed_version"] == "1.4.2", data["proposed_version"]
        git(["tag", "v1.4.2"], f.root)
        code, data = run_script("release.py", "plan", "--project", str(f.root), expect=1)
        assert data["tag_already_exists"] is True
        assert data["blocked"], "clashing tag was not flagged"
        assert "never moved" in data["blocked"]
    finally:
        f.close()


@test
def test_release_notes_come_from_commits():
    f = Fixture()
    try:
        f.write("a.txt", "1")
        f.git_init()
        git(["-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-q",
             "--allow-empty", "-m", "feat: add frobnication"], f.root)
        _, data = run_script("release.py", "notes", "--project", str(f.root),
                             "--version", "0.2.0", expect=0)
        assert "frobnication" in data["markdown"]
        assert "Features" in data["markdown"]
    finally:
        f.close()


@test
def test_ci_admits_when_it_has_nothing_to_run():
    f = Fixture()
    try:
        f.write("main.py", "print(1)\n")
        _, data = run_script("ci_plan.py", "write", "--project", str(f.root),
                             "--dry-run", expect=0)
        written = [w["file"] for w in data["written"]]
        assert "test.yml" not in written, "wrote a test workflow with no test command"
        skipped = {s["file"]: s["why"] for s in data["skipped"]}
        assert "no test command" in skipped.get("test.yml", "")
    finally:
        f.close()


@test
def test_ci_never_overwrites_existing_workflow():
    f = Fixture()
    try:
        f.write("pyproject.toml", '[project]\nname = "x"\nversion = "1.0.0"\n')
        f.write("test_x.py", "def test_a():\n    assert 1\n")
        f.write(".github/workflows/test.yml", "name: mine\n")
        _, data = run_script("ci_plan.py", "write", "--project", str(f.root),
                             "--dry-run", expect=0)
        skipped = {s["file"]: s["why"] for s in data["skipped"]}
        assert "already exists" in skipped.get("test.yml", ""), skipped
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #

@test
def test_prepare_is_read_only_and_lists_limits():
    f = Fixture()
    try:
        f.write("app.py", "print('hi')\n")
        before = sorted(p.name for p in f.root.iterdir())
        _, data = run_script("prepare.py", "--project", str(f.root), expect=0)
        after = sorted(p.name for p in f.root.iterdir())
        assert before == after, f"prepare modified the project: {set(after) - set(before)}"
        assert data["limitations"], "prepare claimed no limitations"
        assert "gate" in data and "findings" in data
    finally:
        f.close()


@test
def test_running_every_script_leaves_no_bytecode_in_the_skill():
    """The launcher must not write __pycache__ into the skill directory.

    Skill directories are often symlinked or read-only, and a stray .pyc in one
    shows up in the user's dotfiles repo. This asserts the invariant rather than
    trusting it.
    """
    skill = SKILL
    stray = [p for p in skill.rglob("*.pyc")] + [p for p in skill.rglob("__pycache__")]
    assert not stray, f"bytecode already present before the run: {stray[:5]}"

    script = skill / "scripts" / "project_scan.py"
    probe = tempfile.mkdtemp(prefix="gitup-probe-")
    try:
        (Path(probe) / "main.py").write_text("print(1)\n")
        run_script("project_scan.py", "--project", probe, expect=0)
        stray = [p for p in skill.rglob("*.pyc")] + [p for p in skill.rglob("__pycache__")]
        assert not stray, f"the launcher wrote bytecode: {stray[:5]}"
    finally:
        shutil.rmtree(probe, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the machine-readable contract
# --------------------------------------------------------------------------- #

ALL_SCRIPTS = ["branding_scan.py", "capture.py", "ci_plan.py", "gh_repo.py",
               "git_sync.py", "ignorefix.py", "license.py", "link_check.py",
               "prepare.py", "project_scan.py", "quality_gate.py", "release.py",
               "render_template.py", "secret_scan.py"]


@test
def test_every_script_emits_json_on_misuse():
    """An agent parses stdout/stderr as JSON. No script may answer with argparse
    usage text on a failure path - that is a shape an agent cannot branch on."""
    offenders = []
    for name in ALL_SCRIPTS:
        code, data = run_script(name)  # no arguments at all: always misuse
        if not isinstance(data, dict) or "error" not in data:
            offenders.append((name, type(data).__name__, str(data)[:60]))
            continue
        if code != 2:
            offenders.append((name, "exit", code))
    assert not offenders, f"non-JSON or wrong exit on misuse: {offenders}"


@test
def test_every_script_help_succeeds_with_readable_text():
    for name in ALL_SCRIPTS:
        code, data = run_script(name, "--help")
        assert code == 0, f"{name} --help exited {code}"
        assert isinstance(data, str) and "usage" in data.lower(), \
            f"{name} --help did not print usage"


@test
def test_launcher_distinguishes_help_from_misuse():
    """A bare invocation is misuse (agent checks $?); --help is success."""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    bare = subprocess.run([sys.executable, "-B", str(RUN)], capture_output=True,
                          text=True, timeout=60, env=env)
    assert bare.returncode == 2, f"bare run.py exited {bare.returncode}, expected 2"
    assert "usage" in (bare.stderr + bare.stdout).lower()
    helped = subprocess.run([sys.executable, "-B", str(RUN), "--help"],
                            capture_output=True, text=True, timeout=60, env=env)
    assert helped.returncode == 0, f"--help exited {helped.returncode}"


@test
def test_required_argument_failure_is_json_with_exit_2():
    """The specific cases that used to leak argparse text."""
    code, data = run_script("release.py", "notes", "--project", str(SKILL))
    assert code == 2, f"expected exit 2, got {code}"
    assert isinstance(data, dict), f"not JSON: {data!r}"
    assert "error" in data and "--version" in data["error"], data
    assert data.get("code") == "usage", data


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #

def main(argv):
    verbose = "-v" in argv
    pattern = next((a for a in argv if not a.startswith("-")), "")
    selected = [t for t in TESTS if pattern in t.__name__] if pattern else TESTS
    if not selected:
        print(f"no tests match {pattern!r}")
        return 2
    failures = []
    for fn in selected:
        try:
            fn()
            if verbose:
                print(f"  PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            failures.append((fn.__name__, exc, traceback.format_exc()))
            print(f"  FAIL  {fn.__name__}: {exc}")
    total = len(selected)
    print(f"\n{total - len(failures)}/{total} passed")
    if failures:
        print("\nfailures:")
        for name, exc, tb in failures:
            print(f"\n--- {name} ---\n{tb}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))