from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NoResidueTests(unittest.TestCase):
    def test_user_facing_demo_and_uploaded_portfolio_artifacts_are_not_bundled(self):
        removed_paths = [
            "fixtures/sample_portfolio.csv",
            "fixtures/portfolio_2026-05-11.csv",
            "scripts/demo_core_flow.py",
            "backend/sentinel_core/demo_data.py",
        ]

        for path in removed_paths:
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists(), "%s should not be bundled" % path)

    def test_http_api_exposes_no_demo_or_fixture_routes(self):
        source = (ROOT / "backend" / "sentinel_core" / "http_api.py").read_text()
        forbidden = [
            "/dev/uploaded-portfolio-csv",
            "/backfill-demo",
            "/backfill-generated",
            "/load-chart-scenario",
            "Generated placeholder bars",
            "Local demo bars",
            "Local AAPL chart scenario",
            "demo_data",
        ]

        for text in forbidden:
            with self.subTest(text=text):
                self.assertNotIn(text, source)

    def test_readme_does_not_direct_users_to_demo_or_sample_data(self):
        readme = (ROOT / "README.md").read_text()
        forbidden = [
            "Run Core Demo",
            "demo_core_flow.py",
            "sample_portfolio.csv",
            "Load Uploaded Portfolio",
            "portfolio_2026-05-11.csv",
            "demo UI",
        ]

        for text in forbidden:
            with self.subTest(text=text):
                self.assertNotIn(text, readme)

    def test_upload_package_validator_passes_and_excludes_runtime_files(self):
        script = ROOT / "scripts" / "validate_upload_package.py"
        self.assertTrue(script.exists())

        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Upload package validation passed", completed.stdout)
        self.assertIn("README.md", completed.stdout)
        self.assertNotIn("sentinel_dev.sqlite3", completed.stdout)
        self.assertNotIn(".sentinel_dev_server.pid", completed.stdout)


if __name__ == "__main__":
    unittest.main()
