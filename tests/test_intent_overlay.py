"""The gitignored intents overlay extends patterns without inventing intents."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class IntentOverlayTest(unittest.TestCase):
    def test_overlay_pattern_routes_and_new_intents_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-overlay-") as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "harness", root / "harness")
            (root / "harness" / "intents.local.toml").write_text(
                textwrap.dedent(
                    """
                    [intents.weekly]
                    patterns = ["zzz weekly probe phrase"]

                    [intents.invented]
                    patterns = ["should never match"]
                    """
                ),
                encoding="utf-8",
            )
            snippet = (
                "import sys, json\n"
                "sys.path.insert(0, 'scripts/atelier')\n"
                "import intent_coverage as ic\n"
                f"ic.ROOT = __import__('pathlib').Path({str(root)!r})\n"
                "intents = ic.load_intents()\n"
                "hit = ic.match_intents('zzz weekly probe phrase please', intents)\n"
                "ghost = ic.match_intents('should never match', intents)\n"
                "print(json.dumps({'hit': hit[0]['name'] if hit else None,\n"
                "                  'ghost': [m['name'] for m in ghost],\n"
                "                  'invented': 'invented' in intents}))\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=REPO_ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(out["hit"], "weekly")
            self.assertFalse(out["invented"])
            self.assertEqual(out["ghost"], ["general"])

    def test_broken_overlay_never_breaks_routing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-overlay-") as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "harness", root / "harness")
            (root / "harness" / "intents.local.toml").write_text("[broken", encoding="utf-8")
            snippet = (
                "import sys\n"
                "sys.path.insert(0, 'scripts/atelier')\n"
                "import intent_coverage as ic\n"
                f"ic.ROOT = __import__('pathlib').Path({str(root)!r})\n"
                "print(len(ic.load_intents()))\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=REPO_ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertGreater(int(proc.stdout.strip()), 10)


if __name__ == "__main__":
    unittest.main()
