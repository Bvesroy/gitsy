#!/usr/bin/env python3
"""
GITSY Comprehensive End-to-End Test & Validation Suite
Tests:
1. Environment and tool detection (`detect_environment.py`).
2. Project discovery and audit on a synthetic multi-file project (`discover_and_audit.py`).
3. Secret detection, redaction, and `.gitignore` hardening (`scan_secrets_and_hygiene.py`).
4. AI watermark detection and safe removal while preserving legal copyrights (`watermark_audit.py`).
5. Visual SVG asset generation (`capture_and_brand.py`).
6. Safe Git synchronization against a local bare remote (`sync_repository.py`).
7. Release packaging, annotated Git tag creation, and SHA-256 checksum generation (`prepare_release.py`).
8. Final independent verification gate (`verify_publication.py`).
9. Cross-agent installation verification across OpenCode, Claude Code, Gemini CLI, Qwen Code, Kilo Code, and Generic `.agents/skills` (`install/install.sh`).
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(cmd, cwd=None):
    res = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30
    )
    return res.returncode, res.stdout.strip(), res.stderr.strip()


class TestGitsySkillEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gitsy_e2e_test_"))
        self.project_dir = self.temp_dir / "sample-app"
        self.remote_bare_dir = self.temp_dir / "remote-origin.git"
        self.install_sandbox = self.temp_dir / "install-root"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.install_sandbox.mkdir(parents=True, exist_ok=True)

        # Create bare remote repository for safe Git sync testing
        subprocess.run(["git", "init", "--bare", str(self.remote_bare_dir)], check=True, stdout=subprocess.PIPE)

        # Populate synthetic project with source code, tests, watermarks, and a test secret
        (self.project_dir / "pyproject.toml").write_text(
            '[project]\nname = "pulse-metrics"\nversion = "0.2.0"\ndescription = "Lightweight system telemetry CLI utility"\n',
            encoding="utf-8",
        )
        src_dir = self.project_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text(
            '#!/usr/bin/env python3\n'
            '# Copyright (c) 2026 Pulse Metrics Contributors. MIT License.\n'
            '# Created by Gemini\n'
            '# Powered by Kilo Code\n'
            'import sys\n\n'
            'def compute_load(values):\n'
            '    return round(sum(values) / max(len(values), 1), 2)\n\n'
            'if __name__ == "__main__":\n'
            '    print("Pulse Metrics v0.2.0 — Avg Load:", compute_load([1.2, 2.4, 3.0]))\n',
            encoding="utf-8",
        )
        tests_dir = self.project_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text(
            'import unittest\n'
            'from src.main import compute_load\n\n'
            'class TestLoad(unittest.TestCase):\n'
            '    def test_avg(self):\n'
            '        self.assertEqual(compute_load([2.0, 4.0]), 3.0)\n\n'
            'if __name__ == "__main__":\n'
            '    unittest.main()\n',
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_gitsy_lifecycle_and_installers(self):
        # 1. Test Environment Detection
        code, out, err = run_cmd([sys.executable, str(SKILL_ROOT / "scripts/detect_environment.py"), "--json"])
        self.assertEqual(code, 0, msg=err)
        env_data = json.loads(out)
        self.assertIn("os", env_data)
        self.assertTrue(env_data["tools"]["git"]["installed"])
        self.assertTrue(env_data["tools"]["python3"]["installed"])

        # 2. Test Secret Detection (plant a temporary .env file and verify blocker triggers)
        env_secret_file = self.project_dir / ".env"
        fake_gh_token = "ghp_" + ("A1b2C3d4E5f6" * 3)
        env_secret_file.write_text(f"GITHUB_TOKEN={fake_gh_token}\n", encoding="utf-8")

        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/scan_secrets_and_hygiene.py"),
            str(self.project_dir),
            "--fix-gitignore",
        ])
        self.assertEqual(code, 0, msg=err)
        sec_initial = json.loads(out)
        self.assertEqual(sec_initial["status"], "BLOCK_UPLOAD")
        self.assertFalse(sec_initial["safe_to_publish"])
        self.assertGreaterEqual(sec_initial["summary"]["working_tree_secrets"], 1)
        self.assertNotIn(fake_gh_token, out)
        self.assertTrue((self.project_dir / ".gitignore").exists())

        # Remove the .env file to resolve the security blocker before publishing
        env_secret_file.unlink()
        code, out, _ = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/scan_secrets_and_hygiene.py"),
            str(self.project_dir),
        ])
        sec_clean = json.loads(out)
        self.assertEqual(sec_clean["status"], "PASS")
        self.assertTrue(sec_clean["safe_to_publish"])

        # 3. Test AI Watermark Audit & Cleanup
        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/watermark_audit.py"),
            str(self.project_dir),
            "--apply",
        ])
        self.assertEqual(code, 0, msg=err)
        wm_data = json.loads(out)
        self.assertEqual(wm_data["watermarks_found"], 2)
        cleaned_main = (self.project_dir / "src/main.py").read_text(encoding="utf-8")
        self.assertNotIn("Created by Gemini", cleaned_main)
        self.assertNotIn("Powered by Kilo Code", cleaned_main)
        self.assertIn("Copyright (c) 2026 Pulse Metrics Contributors", cleaned_main)

        # 4. Test Discovery & Audit + Visual Branding Generation
        audit_json_path = self.temp_dir / "audit.json"
        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/discover_and_audit.py"),
            str(self.project_dir),
            "--run-tests",
            "--output",
            str(audit_json_path),
        ])
        self.assertEqual(code, 0, msg=err)
        audit_data = json.loads(out)
        self.assertEqual(audit_data["project_name"], "pulse-metrics")
        self.assertEqual(audit_data["inferred_version"], "0.2.0")
        self.assertTrue(audit_data["test_execution"]["passed"])

        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/capture_and_brand.py"),
            str(self.project_dir),
            "--audit-json",
            str(audit_json_path),
            "--cli-cmd",
            f"{sys.executable} src/main.py",
        ])
        self.assertEqual(code, 0, msg=err)
        vis_data = json.loads(out)
        self.assertIn("docs/assets/logo.svg", vis_data["assets_created"])
        self.assertIn("docs/assets/social-preview.svg", vis_data["assets_created"])
        self.assertIn("docs/assets/architecture.svg", vis_data["assets_created"])
        self.assertIn("docs/assets/cli-demo.svg", vis_data["assets_created"])

        # Add complete README.md and LICENSE so documentation verification gate passes
        (self.project_dir / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.project_dir / "README.md").write_text(
            "# pulse-metrics\n\n"
            "Lightweight system telemetry CLI utility.\n\n"
            "![Logo](docs/assets/logo.svg)\n"
            "![Social Preview](docs/assets/social-preview.svg)\n"
            "![Architecture](docs/assets/architecture.svg)\n"
            "![CLI Output](docs/assets/cli-demo.svg)\n\n"
            "## Installation\n\n"
            "```bash\npip install -e .\n```\n\n"
            "## Usage\n\n"
            "```bash\npython3 src/main.py\n```\n",
            encoding="utf-8",
        )

        # 5. Test Git Synchronization with Safe Local Bare Remote
        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/sync_repository.py"),
            str(self.project_dir),
            "--execute",
            "--branch",
            "main",
            "--remote-url",
            str(self.remote_bare_dir),
            "--commit-message",
            "feat: initial verified publication of pulse-metrics",
            "--push",
        ])
        self.assertEqual(code, 0, msg=err)
        sync_data = json.loads(out)
        self.assertEqual(sync_data["status"], "SUCCESS")

        # 6. Test Release Management System (Archives + Checksums + Tag)
        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/prepare_release.py"),
            str(self.project_dir),
            "--version",
            "v0.2.0",
            "--create-tag",
        ])
        self.assertEqual(code, 0, msg=err)
        rel_data = json.loads(out)
        self.assertTrue(rel_data["tag_created"])
        self.assertEqual(len(rel_data["artifacts"]), 2)
        self.assertTrue(Path(rel_data["checksums_path"]).exists())

        # 7. Test Final Independent Quality Gate
        code, out, err = run_cmd([
            sys.executable,
            str(SKILL_ROOT / "scripts/verify_publication.py"),
            str(self.project_dir),
        ])
        self.assertEqual(code, 0, msg=err)
        ver_data = json.loads(out)
        self.assertEqual(ver_data["overall_status"], "PASS")
        for gate in ver_data["quality_gates"]:
            self.assertEqual(gate["status"], "PASS", msg=f"Gate failed: {gate}")

        # 8. Test Cross-Platform Installers in Sandbox Root
        code, out, err = run_cmd([
            "bash",
            str(SKILL_ROOT / "install/install.sh"),
            "--target",
            "all",
            "--scope",
            "global",
            "--dest-root",
            str(self.install_sandbox),
        ])
        self.assertEqual(code, 0, msg=err)
        expected_paths = [
            ".agents/skills/gitsy/SKILL.md",
            ".claude/skills/gitsy/SKILL.md",
            ".claude/commands/gitsy.md",
            ".gemini/skills/gitsy/SKILL.md",
            ".gemini/commands/gitsy.toml",
            ".opencode/skills/gitsy/SKILL.md",
            ".opencode/commands/gitsy.md",
            ".qwen/skills/gitsy/SKILL.md",
            ".qwen/commands/gitsy.md",
            ".kilo/skills/gitsy/SKILL.md",
            ".kilo/commands/gitsy.md",
            ".config/kilo/commands/gitsy.md",
        ]
        for rel in expected_paths:
            self.assertTrue(
                (self.install_sandbox / rel).exists(),
                msg=f"Expected installed file missing: {rel}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
