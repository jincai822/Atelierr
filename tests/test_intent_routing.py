"""Routing regression: the shared evalset must route as declared.

The fixture is the deterministic core of the eval harness (`eval_run.py`);
running it in the unit suite means a registry edit that silently re-routes a
common phrase fails CI-style instead of surfacing as a user-facing miss.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "routing_evalset.json"


class RoutingEvalsetTest(unittest.TestCase):
    def test_every_case_routes_to_its_expected_intent(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 20)
        snippet = (
            "import sys, json\n"
            "sys.path.insert(0, 'scripts')\n"
            "import intent_coverage as ic\n"
            "intents = ic.load_intents()\n"
            "out = []\n"
            f"for case in json.loads(open({str(FIXTURE)!r}, encoding='utf-8').read())['cases']:\n"
            "    matches = ic.match_intents(case['input'], intents)\n"
            "    out.append(matches[0]['name'] if matches else None)\n"
            "print(json.dumps(out))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", snippet], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout.strip().splitlines()[-1])
        failures = [
            f"{case['input']!r}: expected {case['expected']}, got {actual}"
            for case, actual in zip(cases, got)
            if actual != case["expected"]
        ]
        self.assertFalse(failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
