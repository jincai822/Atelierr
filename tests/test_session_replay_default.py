"""The out-of-the-box session-replay state: no env override, no local config.

Review finding (2026-08-23): every hook test set the env override
explicitly, so the path every fresh machine actually takes, `(False,
"default")`, had no coverage. Capture is privacy-sensitive and off by
default; that default must be pinned.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class DefaultActivationTest(unittest.TestCase):
    def test_no_env_and_no_local_config_is_disabled_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-replay-") as tmp:
            env = {k: v for k, v in os.environ.items() if "SESSION_REPLAY" not in k}
            env["XDG_CONFIG_HOME"] = str(Path(tmp) / "xdg")  # no atelier config inside
            env["HOME"] = str(Path(tmp) / "home")
            snippet = (
                "import os, sys, json\n"
                "sys.path.insert(0, 'scripts')\n"
                "import session_replay as sr\n"
                "os.environ.pop(sr.ENABLED_ENV, None)\n"
                "enabled, source = sr.replay_activation()\n"
                "print(json.dumps({'enabled': enabled, 'source': source, 'path': str(sr.LOCAL_CONFIG_PATH)}))\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertFalse(out["enabled"], out)
            self.assertEqual(out["source"], "default", out)
            self.assertTrue(out["path"].startswith(str(Path(tmp))), out)


if __name__ == "__main__":
    unittest.main()
