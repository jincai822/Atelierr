"""group-start --agent derives expected legs from the canonical voice bindings."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import shadow  # noqa: E402


class ExpectedForAgentTest(unittest.TestCase):
    def test_dual_voice_agent_yields_both_legs(self) -> None:
        expected = shadow._expected_for_agent("privacy-reviewer", "claude")
        legs = {e["leg"] for e in expected}
        self.assertEqual(legs, {"native", "direct"})
        native = next(e for e in expected if e["leg"] == "native")
        self.assertEqual(native["subagent_type"], "privacy-reviewer")
        direct = next(e for e in expected if e["leg"] == "direct")
        self.assertEqual(direct["model"], shadow._agent_direct_model("privacy-reviewer"))
        self.assertTrue(direct["model"])

    def test_unknown_agent_yields_nothing(self) -> None:
        self.assertEqual(shadow._expected_for_agent("no-such-agent", "claude"), [])

    def test_cli_requires_exactly_one_mode(self) -> None:
        both = subprocess.run(
            [sys.executable, "scripts/shadow.py", "group-start",
             "--task", "t", "--agent", "thinker", "--expected", "[]"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(both.returncode, 2)
        neither = subprocess.run(
            [sys.executable, "scripts/shadow.py", "group-start", "--task", "t"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(neither.returncode, 2)


if __name__ == "__main__":
    unittest.main()
