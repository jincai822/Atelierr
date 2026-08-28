"""privacy_check --json carries an `action` verdict so callers stop re-deriving it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(env_ov: str | None, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "OV"}
    if env_ov is not None:
        env["OV"] = env_ov
    return subprocess.run(
        [sys.executable, "scripts/atelier/privacy_check.py", "--json", *argv],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


class PrivacyActionTest(unittest.TestCase):
    def test_missing_vault_soft_skips(self) -> None:
        proc = _run("/nonexistent/atelier-test-vault")
        out = json.loads(proc.stdout)
        self.assertEqual(out["action"], "soft_skip")
        self.assertTrue(out["zk_missing"])

    def test_vacuous_vault_soft_skips(self) -> None:
        # The repo's gitignored profile sidecars defeat vacuousness on a real
        # machine, so patch the module to a bare environment in-process.
        import contextlib
        import io
        import sys as _sys

        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "atelier"))
        import privacy_check as pc

        with tempfile.TemporaryDirectory(prefix="atelier-priv-") as tmp:
            missing = Path(tmp) / "absent.txt"
            saved = (pc.PRIVATE_SLUGS, pc.PRIVATE_TERMS, os.environ.get("OV"))
            try:
                pc.PRIVATE_SLUGS = missing
                pc.PRIVATE_TERMS = missing
                os.environ["OV"] = tmp
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = pc.main(["--json"])
                out = json.loads(buf.getvalue())
            finally:
                pc.PRIVATE_SLUGS, pc.PRIVATE_TERMS = saved[0], saved[1]
                if saved[2] is None:
                    os.environ.pop("OV", None)
                else:
                    os.environ["OV"] = saved[2]
        self.assertEqual(rc, 2)
        self.assertEqual(out["action"], "soft_skip")
        self.assertTrue(out["vacuous_gate"])


if __name__ == "__main__":
    unittest.main()
