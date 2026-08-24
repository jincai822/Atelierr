#!/usr/bin/env python3
"""Run the harness eval suite and record a scored snapshot.

The architecture review's core evolvability finding: nothing measured whether
the system got better, so neither a protocol edit nor a model upgrade could
be shown to help. This runner produces a comparable JSON per (date, git
SHA), written to `$OV/_meta/evals/`, so `/system-review` and the
`eval_regression` cue can diff consecutive runs.

Components (each skips cleanly when its substrate is unavailable):
  routing    deterministic: tests/fixtures/routing_evalset.json through the
             registry matcher; score = fraction routed as declared.
  semantic   delegates to scripts/semantic_eval.py when the gold set and a
             Lance index exist; records Recall@5/MRR@10 style metrics.
  judged     reserved: model-judged tasks (reviewer/forgetter fixtures) via
             chat_completion direct legs; not yet implemented, recorded as
             skipped so the report is honest about coverage.

Usage: uv run scripts/eval_run.py [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tier_segments, vault_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "routing_evalset.json"


def eval_routing() -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import intent_coverage as ic

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    intents = ic.load_intents()
    misses = []
    for case in cases:
        matches = ic.match_intents(case["input"], intents)
        actual = matches[0]["name"] if matches else None
        if actual != case["expected"]:
            misses.append({"expected": case["expected"], "got": actual})
    return {
        "cases": len(cases),
        "passed": len(cases) - len(misses),
        "score": round((len(cases) - len(misses)) / len(cases), 3),
        "misses": misses,
    }


def eval_semantic() -> dict:
    gold = ROOT / "scripts" / "_evalset.json"
    if not gold.is_file():
        return {"skipped": "no gold set"}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "semantic_eval.py"), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if result.returncode != 0:
        return {"skipped": f"semantic_eval exit {result.returncode}: {result.stderr.strip()[:160]}"}
    try:
        return {"metrics": json.loads(result.stdout)}
    except json.JSONDecodeError:
        return {"skipped": "semantic_eval emitted non-JSON"}


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    return result.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-semantic", action="store_true", help="Skip the (slow) retrieval eval.")
    args = parser.parse_args(argv)

    snapshot = {
        "date": date.today().isoformat(),
        "git_sha": _git_sha(),
        "routing": eval_routing(),
        "semantic": {"skipped": "--no-semantic"} if args.no_semantic else eval_semantic(),
        "judged": {"skipped": "not implemented"},
    }

    out_dir = vault_root() / tier_segments().get("meta", "_meta") / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{snapshot['date']}-{snapshot['git_sha']}.json"
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    else:
        r = snapshot["routing"]
        print(f"routing: {r['passed']}/{r['cases']} ({r['score']:.0%})")
        sem = snapshot["semantic"]
        print(f"semantic: {'skipped: ' + sem['skipped'] if 'skipped' in sem else 'recorded'}")
        print(f"snapshot: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
