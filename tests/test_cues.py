"""Regression tests for the autoevo cue in scripts/atelier/cues.py.

Glitches (2026-08-22): the nightly bot was blocked 73 of 103 attempts by the
same gate while the cue stayed soft; and when the runner crashed before the
audit step the cue said "did not run" with a generic cause list although the
claim file held the real error. Both lookups must also work once
`agent-findings/` is bucketed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PRELUDE = """
import json, sys
sys.path.insert(0, 'scripts/atelier')
import cues
from datetime import date, datetime
from pathlib import Path
vault = Path(__import__('os').environ['OV'])
"""


def _run_py(vault: Path, body: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", PRELUDE + textwrap.dedent(body)],
        cwd=REPO_ROOT,
        env={**os.environ, "OV": str(vault), "ATELIER_SKIP_LOCK_TOUCH": "1"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _audit(vault: Path, day: str, gate: str | None, bucket: bool) -> None:
    folder = vault / "agent-findings" / (day[:7] if bucket else "")
    folder.mkdir(parents=True, exist_ok=True)
    skipped = f"- {gate}: detail\n" if gate else "- (none)\n"
    (folder / f"autoevo-applied-{day}.md").write_text(
        f"## Autoevo Run: {day} 05:00\n\n### Skipped (reason)\n{skipped}\n### Errors\n- (none)\n",
        encoding="utf-8",
    )


class AutoevoCueTest(unittest.TestCase):
    def test_same_gate_three_days_escalates_to_hard_on_bucketed_tier(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-cues-") as tmp:
            vault = Path(tmp)
            for day in ("2099-01-03", "2099-01-04", "2099-01-05"):
                _audit(vault, day, "dirty_vault_worktree", bucket=True)
            out = _run_py(
                vault,
                """
                cue, debug = cues.check_autoevo_ran(vault, date(2099, 1, 5), now=datetime(2099, 1, 5, 12, 0))
                print(json.dumps({"severity": cue.severity if cue else None, "message": cue.message if cue else "", "debug": debug}))
                """,
            )
            self.assertEqual(out["severity"], "hard", out)
            self.assertIn("3 consecutive days", out["message"])
            self.assertIn("--dirty-scope", out["message"])

    def test_specific_fix_text_for_each_gate(self) -> None:
        """privacy/semantic gates must get their specific fix, not the generic one."""
        for gate, expect in (
            ("privacy_hits", "privacy_check.py"),
            ("semantic_unavailable", "semantic index"),
        ):
            with tempfile.TemporaryDirectory(prefix="atelier-cues-") as tmp:
                vault = Path(tmp)
                for day in ("2099-01-03", "2099-01-04", "2099-01-05"):
                    _audit(vault, day, gate, bucket=False)
                out = _run_py(
                    vault,
                    """
                    cue, debug = cues.check_autoevo_ran(vault, date(2099, 1, 5), now=datetime(2099, 1, 5, 12, 0))
                    print(json.dumps({"severity": cue.severity if cue else None, "message": cue.message if cue else ""}))
                    """,
                )
                self.assertEqual(out["severity"], "hard", (gate, out))
                self.assertIn(expect, out["message"], (gate, out))
                self.assertNotIn("see the audit file", out["message"], (gate, out))

    def test_gate_fix_keys_match_preflight_gate_strings(self) -> None:
        """Producer/consumer pin: every gate_fixes key must exist in autoevo_preflight.py."""
        import re
        cues_src = (REPO_ROOT / "scripts" / "atelier" / "cues.py").read_text(encoding="utf-8")
        block = cues_src.split("gate_fixes = {", 1)[1].split("}", 1)[0]
        keys = re.findall(r'^\s*"([a-z_]+)":', block, re.MULTILINE)
        self.assertGreaterEqual(len(keys), 8, keys)
        preflight_src = (REPO_ROOT / "scripts" / "atelier" / "autoevo_preflight.py").read_text(encoding="utf-8")
        for key in keys:
            self.assertIn(f'"{key}"', preflight_src, f"gate_fixes key {key!r} not emitted by autoevo_preflight.py")

    def test_every_emitted_gate_has_a_fix_entry(self) -> None:
        """Reverse pin: a NEW preflight gate must not fall back to generic text."""
        import re
        preflight_src = (REPO_ROOT / "scripts" / "atelier" / "autoevo_preflight.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'"gate": "([a-z_]+)"', preflight_src))
        # dynamic result["gate"] assignments too
        emitted |= set(re.findall(r'result\["gate"\] = "([a-z_]+)"', preflight_src))
        self.assertGreaterEqual(len(emitted), 9, emitted)
        cues_src = (REPO_ROOT / "scripts" / "atelier" / "cues.py").read_text(encoding="utf-8")
        block = cues_src.split("gate_fixes = {", 1)[1].split("}", 1)[0]
        keys = set(re.findall(r'"([a-z_]+)":', block))
        missing = emitted - keys - {"unknown"}
        self.assertFalse(missing, f"preflight gates without a fix entry: {sorted(missing)}")

    def test_two_days_stays_soft(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-cues-") as tmp:
            vault = Path(tmp)
            _audit(vault, "2099-01-04", "dirty_vault_worktree", bucket=False)
            _audit(vault, "2099-01-05", "dirty_vault_worktree", bucket=False)
            out = _run_py(
                vault,
                """
                cue, debug = cues.check_autoevo_ran(vault, date(2099, 1, 5), now=datetime(2099, 1, 5, 12, 0))
                print(json.dumps({"severity": cue.severity if cue else None}))
                """,
            )
            self.assertEqual(out["severity"], "soft")

    def test_missing_audit_surfaces_claim_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-cues-") as tmp:
            vault = Path(tmp)
            _audit(vault, "2099-01-04", None, bucket=True)  # bot installed; yesterday clean
            claim = vault / "_meta" / "routine_runs" / "autoevo-nightly" / "2099-01-05.toml"
            claim.parent.mkdir(parents=True)
            claim.write_text('status = "failed"\nerror = "runner-exited-unexpectedly"\n', encoding="utf-8")
            out = _run_py(
                vault,
                """
                cue, debug = cues.check_autoevo_ran(vault, date(2099, 1, 5), now=datetime(2099, 1, 5, 12, 0))
                print(json.dumps({"message": cue.message if cue else ""}))
                """,
            )
            self.assertIn("runner-exited-unexpectedly", out["message"])
            self.assertIn("failed", out["message"])


if __name__ == "__main__":
    unittest.main()
