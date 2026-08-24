"""Regression tests for structured Atelier session logs."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "session_log.py"


class SessionLogTests(unittest.TestCase):
    def test_prm_is_a_supported_session_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            env = os.environ.copy()
            env["OV"] = str(vault)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--type",
                    "prm",
                    "--duration",
                    "1",
                    "--model",
                    "fixture",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            session_path = vault / "sessions" / Path(result.stdout.strip()).name
            self.assertTrue(session_path.is_file())
            content = session_path.read_text(encoding="utf-8")
            self.assertIn("type: prm", content)
            self.assertIn("duration_estimate: 1", content)
            self.assertIn("model: fixture", content)
            self.assertIn("| Query | Tool | Hits | Top Result | Useful |", content)

    def test_collision_overflow_never_overwrites_an_existing_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            sessions = vault / "sessions"
            sessions.mkdir(parents=True)
            now = datetime.now()
            effective_date = (
                (now - timedelta(days=1)).date() if now.hour < 3 else now.date()
            )
            base_id = f"{effective_date.isoformat()}-prm"
            existing = sessions / f"{base_id}-99.md"
            for sequence in range(1, 100):
                suffix = "" if sequence == 1 else f"-{sequence}"
                sessions.joinpath(f"{base_id}{suffix}.md").write_text(
                    f"sentinel-{sequence}", encoding="utf-8"
                )

            env = os.environ.copy()
            env["OV"] = str(vault)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--type", "prm"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "sentinel-99")
            self.assertTrue(sessions.joinpath(f"{base_id}-100.md").is_file())
            self.assertEqual(len(list(sessions.glob(f"{base_id}*.md"))), 100)


if __name__ == "__main__":
    unittest.main()
