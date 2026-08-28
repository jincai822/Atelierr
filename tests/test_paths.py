"""Regression tests for bucket-aware tier readers.

Glitch (2026-08-22): `reflections/` was split into `YYYY-MM/` buckets by
`scripts/atelier/fission.py`, but several readers still used non-recursive
`tier("reflections").glob(...)`. `cues.py` then raised a hard "never ran
weekly" cue every session although weekly files existed, and
`todos.py digest` found no prior reflection. `harness_smoke.py` did not catch
it because its fixture wrote reflections at the tier root.

Guard: every reader must go through `_paths.tier_files` (or `rglob`), and
the fixtures here place files inside buckets so a regression to a flat glob
fails loudly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts" / "atelier"


def _make_vault(root: Path, weekly_date: str) -> Path:
    vault = root / "vault"
    (vault / "reflections" / weekly_date[:7]).mkdir(parents=True)
    (vault / "reflections" / weekly_date[:7] / f"{weekly_date}-weekly.md").write_text(
        "## Energy\nfine\n", encoding="utf-8"
    )
    (vault / "reflections" / weekly_date[:7] / f"{weekly_date}-reflection.md").write_text(
        "## Theme\nt\n\n## Next Action\n- [ ] do the thing\n", encoding="utf-8"
    )
    # Directories the cue runner expects to be able to probe.
    for rel in ("daily-notes", "gtd", "wiki", "cache", "_meta", "sessions"):
        (vault / rel).mkdir(parents=True, exist_ok=True)
    return vault


class TierFilesTest(unittest.TestCase):
    def test_tier_files_recurses_into_buckets(self) -> None:
        # Run in a subprocess: `_paths` caches $OV process-wide and importing
        # it in-process would leak the fixture vault into later test modules.
        snippet = (
            "import sys; sys.path.insert(0, 'scripts/atelier'); import _paths, json; "
            "print(json.dumps({"
            "'weekly': [p.name for p in _paths.tier_files('reflections', '*-weekly.md')], "
            "'last': _paths.tier_files('reflections', '*.md')[-1].name, "
            "'empty': [p.name for p in _paths.tier_files('sessions', '*.md')]}))"
        )
        with tempfile.TemporaryDirectory(prefix="atelier-paths-") as tmp:
            vault = _make_vault(Path(tmp), "2099-01-05")
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=REPO_ROOT,
                env={**os.environ, "OV": str(vault)},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["weekly"], ["2099-01-05-weekly.md"])
            self.assertEqual(out["last"], "2099-01-05-weekly.md")
            self.assertEqual(out["empty"], [])


class StalenessBucketedScanTest(unittest.TestCase):
    """staleness.py was the third reader to go flat-glob blind (2026-08-23)."""

    def test_staleness_scores_bucketed_notes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-staleness-") as tmp:
            vault = Path(tmp) / "vault"
            (vault / "reflections" / "2099-01").mkdir(parents=True)
            (vault / "reflections" / "2099-01" / "2099-01-05-reflection.md").write_text(
                "# Old Thought\nbody\n", encoding="utf-8"
            )
            for rel in ("wiki", "daily-notes", "wip", "gtd", "preprints", "agent-findings"):
                (vault / rel).mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [sys.executable, "scripts/atelier/staleness.py", "--json"],
                cwd=REPO_ROOT,
                env={**os.environ, "OV": str(vault)},
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("2099-01-05-reflection.md", proc.stdout)


class BucketedReadersTest(unittest.TestCase):
    """Drive the real CLIs against a bucketed fixture vault."""

    def _run(self, vault: Path, *argv: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "OV": str(vault), "ATELIER_SKIP_LOCK_TOUCH": "1"}
        return subprocess.run(
            [sys.executable, *argv],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_weekly_cue_sees_bucketed_weekly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-cues-") as tmp:
            today = date.today().isoformat()
            vault = _make_vault(Path(tmp), today)
            proc = self._run(vault, "scripts/atelier/cues.py", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout or "{}")
            cues = payload.get("cues", payload) if isinstance(payload, dict) else payload
            keys = [c.get("key") for c in cues] if isinstance(cues, list) else list(cues)
            self.assertNotIn("weekly", keys, f"weekly cue fired despite bucketed weekly file: {proc.stdout}")

    def test_todos_digest_finds_bucketed_reflection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-todos-") as tmp:
            vault = _make_vault(Path(tmp), "2099-01-05")
            proc = self._run(vault, "scripts/atelier/todos.py", "digest")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("No prior reflection", proc.stdout)
            self.assertIn("do the thing", proc.stdout)


if __name__ == "__main__":
    unittest.main()
