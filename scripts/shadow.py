#!/usr/bin/env python3
"""
shadow.py: cross-provider shadow-log correlation + reporting.

Companion to `scripts/chat_completion.py`. Mechanism:

  - A multi-leg call site (e.g., /system-review Step 1c, /decision,
    scripts/review.sh) opens a shadow group via `shadow.py group-start`,
    which writes a witness file under `~/.cache/atelier/shadow_groups/`
    and emits a UUID + env-export line to stdout.
  - Direct-API legs auto-log via chat_completion.py reading env vars
    (ATELIER_SHADOW_GROUP, ATELIER_TASK_TYPE).
  - Native legs (Claude Code Agent tool) log via `shadow.py log`, which
    writes a synthetic JSONL entry with char_approx token estimates
    (Agent tool doesn't surface usage to parents).
  - `shadow.py report` aggregates all logs, deduplicates, groups by UUID,
    extracts verdict tokens per task type, computes cost retroactively
    from the current `harness/model_costs.toml`, and emits per-task-type
    cost / latency / verdict-agreement comparisons.

Subcommands:
    group-start --task <name> --expected '[{"model":"X","leg":"Y"}, ...]'
        Open a shadow group; print UUID and shell-eval-able env exports.

    log --group <uuid> --task <name> --model <id> --leg <native|direct|codex>
        --prompt-file <path> --response-file <path> [--prompt-stdin]
        [--response-stdin]
        Append a synthetic native/codex leg entry to the same JSONL files
        chat_completion.py writes to. Char_approx usage estimate; report
        flags it.

    report [--since YYYY-MM-DD] [--task-type X] [--accept-stale-costs] [--json]
        Aggregate logs and emit cost/verdict-agreement comparison.

See `protocols/backend-taxonomy.md` for the SOT/role/failure-mode contract
and `protocols/orchestrator.md` § Voice Dispatch for when multi-leg call
sites use this. Stdlib-only by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
COSTS_TOML = REPO_ROOT / "harness" / "model_costs.toml"
SHADOW_TASKS_TOML = REPO_ROOT / "harness" / "shadow_tasks.toml"
DEFAULT_LOG_DIR = Path.home() / ".cache" / "atelier" / "llm_calls"
DEFAULT_WITNESS_DIR = Path.home() / ".cache" / "atelier" / "shadow_groups"

SCOPE_BANNER = (
    "SCOPE: shadow logs cover multi-leg verification workloads (~10-20% of LLM spend).\n"
    "       Single-leg generative routing (Researcher, Synthesizer, Reader, Scout, Curator)\n"
    "       is not instrumented. For routing questions on those, run manual A/B\n"
    "       (see protocols/shadow-log.md § M2 for the 30-minute procedure)."
)


# ---------- group-start ----------


def cmd_group_start(args: argparse.Namespace) -> int:
    try:
        expected = json.loads(args.expected)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"shadow: --expected is not valid JSON: {e}\n")
        return 2
    if not isinstance(expected, list) or not all(
        isinstance(e, dict) and "model" in e and "leg" in e for e in expected
    ):
        sys.stderr.write(
            "shadow: --expected must be a JSON array of {\"model\": ..., \"leg\": ...} objects\n"
        )
        return 2
    group_id = str(uuid.uuid4())
    DEFAULT_WITNESS_DIR.mkdir(parents=True, exist_ok=True)
    witness_path = DEFAULT_WITNESS_DIR / f"{group_id}.json"
    witness_path.write_text(json.dumps({
        "group_id": group_id,
        "task_type": args.task,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "expected_dispatches": expected,
    }, indent=2), encoding="utf-8")
    # Emit shell-eval-able exports so the caller can: eval "$(shadow.py group-start ...)"
    print(f'export ATELIER_SHADOW_GROUP="{group_id}"')
    print(f'export ATELIER_TASK_TYPE="{args.task}"')
    sys.stderr.write(f"shadow: opened group {group_id} (task={args.task}, expected_legs={len(expected)})\n")
    return 0


# ---------- log (native / codex synthetic shim) ----------


def _read_payload(path: str | None, stdin_flag: bool, field: str) -> str:
    if stdin_flag:
        return sys.stdin.read()
    if path:
        return Path(path).read_text(encoding="utf-8")
    sys.stderr.write(f"shadow: provide --{field}-file or --{field}-stdin\n")
    raise SystemExit(2)


def cmd_log(args: argparse.Namespace) -> int:
    prompt = _read_payload(args.prompt_file, args.prompt_stdin, "prompt")
    response = _read_payload(args.response_file, args.response_stdin, "response")
    # Char approx: every 4 chars ≈ 1 token. Honest fallback; report annotates.
    input_tokens_approx = max(1, len(prompt) // 4)
    output_tokens_approx = max(1, len(response) // 4)
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "shadow_group_id": args.group,
        "task_type": args.task,
        "task_dispatch_kind": args.leg,
        "model": args.model,
        "api_model": None,
        "endpoint": None,
        "session": None,
        "system": None,
        "user_prompt": prompt,
        "status": "ok",
        "response_content": response,
        "reasoning_content": None,
        "finish_reason": "stop",
        "usage": None,
        "usage_estimate": {
            "input_tokens": input_tokens_approx,
            "output_tokens": output_tokens_approx,
            "method": "char_approx",
        },
        "cost_estimate_method": "char_approx",
        "latency_s": None,
    }
    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    # Mirror skeleton to $OV/_meta/shadow_logs/ when OV is set.
    _mirror_skeleton(event)
    return 0


def _mirror_skeleton(event: dict[str, Any]) -> None:
    ov = os.environ.get("OV")
    if not ov:
        return
    skeleton_fields = (
        "timestamp", "shadow_group_id", "task_type", "task_dispatch_kind",
        "model", "api_model", "usage", "usage_estimate",
        "cost_estimate_method", "latency_s", "finish_reason", "status",
    )
    try:
        sk: dict[str, Any] = {k: event.get(k) for k in skeleton_fields}
        resp = event.get("response_content")
        if isinstance(resp, str):
            sk["response_first_200"] = resp[:200]
            sk["response_sha256"] = hashlib.sha256(resp.encode("utf-8")).hexdigest()
        mirror_dir = Path(ov) / "_meta" / "shadow_logs"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        mirror_file = mirror_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with mirror_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sk, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError):
        pass


# ---------- report ----------


def _load_costs() -> dict[str, dict[str, Any]]:
    if not COSTS_TOML.exists():
        return {}
    data = tomllib.loads(COSTS_TOML.read_text(encoding="utf-8"))
    return data.get("costs", {}) or {}


def _load_shadow_tasks() -> dict[str, dict[str, Any]]:
    if not SHADOW_TASKS_TOML.exists():
        return {}
    data = tomllib.loads(SHADOW_TASKS_TOML.read_text(encoding="utf-8"))
    return data.get("tasks", {}) or {}


def _iter_log_files(since: date | None) -> list[Path]:
    out: list[Path] = []
    for d in (DEFAULT_LOG_DIR,):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jsonl")):
            try:
                file_date = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if since and file_date < since:
                continue
            out.append(p)
    return out


def _load_events(since: date | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for p in _iter_log_files(since):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                events.append(ev)
        except OSError:
            continue
    return events


def _stale_cost_days(costs: dict[str, dict[str, Any]], today: date) -> dict[str, int]:
    stale: dict[str, int] = {}
    for name, row in costs.items():
        lv = row.get("last_verified")
        if not isinstance(lv, str):
            stale[name] = -1  # unknown / unset
            continue
        try:
            d = date.fromisoformat(lv)
        except ValueError:
            stale[name] = -1
            continue
        days = (today - d).days
        if days > 90:
            stale[name] = days
    return stale


def _compute_cost_usd(usage: dict[str, Any] | None, usage_est: dict[str, Any] | None,
                      cost_row: dict[str, Any] | None) -> tuple[float | None, str]:
    """Return (cost_usd, method) where method is 'usage'|'char_approx'|'unknown'."""
    if not cost_row:
        return None, "unknown"
    inp_per_m = cost_row.get("input_per_1m_usd")
    out_per_m = cost_row.get("output_per_1m_usd")
    if inp_per_m is None or out_per_m is None:
        return None, "unknown"
    if usage and isinstance(usage, dict):
        in_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out_tok = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        method = "usage"
    elif usage_est and isinstance(usage_est, dict):
        in_tok = usage_est.get("input_tokens", 0)
        out_tok = usage_est.get("output_tokens", 0)
        method = usage_est.get("method", "char_approx")
    else:
        return None, "unknown"
    cost = (float(in_tok) * float(inp_per_m) + float(out_tok) * float(out_per_m)) / 1_000_000.0
    return cost, method


def _extract_verdict(response: str | None, task_row: dict[str, Any]) -> str | None:
    if not response or not isinstance(response, str):
        return None
    pattern = task_row.get("verdict_pattern")
    if not isinstance(pattern, str):
        return None
    flags = re.IGNORECASE if task_row.get("case_insensitive") else 0
    matches = re.findall(pattern, response, flags=flags)
    if not matches:
        return None
    chosen = matches[-1] if task_row.get("last_match_wins") else matches[0]
    if isinstance(chosen, tuple):
        chosen = next((c for c in chosen if c), "")
    return chosen.lower() if task_row.get("case_insensitive") else chosen


def _load_witnesses() -> dict[str, dict[str, Any]]:
    """Read all witness files indexed by group_id."""
    witnesses: dict[str, dict[str, Any]] = {}
    if not DEFAULT_WITNESS_DIR.is_dir():
        return witnesses
    for p in DEFAULT_WITNESS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("group_id"):
                witnesses[data["group_id"]] = data
        except (OSError, json.JSONDecodeError):
            continue
    return witnesses


def cmd_report(args: argparse.Namespace) -> int:
    since = date.fromisoformat(args.since) if args.since else None
    costs = _load_costs()
    tasks = _load_shadow_tasks()
    today = date.today()

    # Stale-cost fail-closed: refuse to emit absolute cost columns if any
    # known-aggregated model is >90d stale, unless --accept-stale-costs.
    stale = _stale_cost_days(costs, today)
    stale_aggregated = {m: d for m, d in stale.items() if d > 90}
    if stale_aggregated and not args.accept_stale_costs:
        sys.stderr.write("ERROR: cost catalog has stale entries:\n")
        for m, d in sorted(stale_aggregated.items()):
            sys.stderr.write(f"  - {m}: {d}d since last_verified\n")
        sys.stderr.write(
            "Refresh harness/model_costs.toml or pass --accept-stale-costs to "
            "see annotated values.\n"
        )
        return 2

    events = _load_events(since)
    events = [e for e in events if e.get("shadow_group_id")]
    if args.task_type:
        events = [e for e in events if e.get("task_type") == args.task_type]

    witnesses = _load_witnesses()

    # Group events by shadow_group_id.
    by_group: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        by_group.setdefault(ev["shadow_group_id"], []).append(ev)

    # Per-group enrichment.
    group_summaries: list[dict[str, Any]] = []
    witness_absent_count = 0
    for gid, legs in by_group.items():
        witness = witnesses.get(gid)
        if witness is None:
            witness_absent_count += 1
        task_type = legs[0].get("task_type", "unknown")
        task_row = tasks.get(task_type, {})
        leg_records: list[dict[str, Any]] = []
        for leg in legs:
            model = leg.get("model") or "(unknown)"
            cost_row = costs.get(model)
            cost_usd, cost_method = _compute_cost_usd(
                leg.get("usage"), leg.get("usage_estimate"), cost_row
            )
            verdict = _extract_verdict(leg.get("response_content"), task_row) if task_row else None
            leg_records.append({
                "model": model,
                "leg": leg.get("task_dispatch_kind", "unknown"),
                "cost_usd": cost_usd,
                "cost_method": cost_method,
                "latency_s": leg.get("latency_s"),
                "verdict": verdict,
                "finish_reason": leg.get("finish_reason"),
                "stale_days": stale.get(model, 0) if model in stale else 0,
            })
        # Missing-leg check against witness.
        missing: list[dict[str, Any]] = []
        if witness:
            seen = {(r["model"], r["leg"]) for r in leg_records}
            for exp in witness.get("expected_dispatches", []):
                key = (exp.get("model"), exp.get("leg"))
                if key not in seen:
                    missing.append({"model": exp.get("model"), "leg": exp.get("leg")})
        group_summaries.append({
            "group_id": gid,
            "task_type": task_type,
            "witness_present": witness is not None,
            "legs": leg_records,
            "missing_legs": missing,
        })

    # Aggregate per task_type per leg-pair. Witness-absent groups are skipped
    # from pair aggregation: without the witness, the report has no ground
    # truth for "what legs were expected," and a single-logged-leg group
    # would contribute vacuous pair stats (per the Reviewer's SHOULD-FIX).
    per_task: dict[str, dict[str, Any]] = {}
    for gs in group_summaries:
        if not gs.get("witness_present"):
            gs["excluded_from_pair_stats"] = True
            continue
        tt = gs["task_type"]
        d = per_task.setdefault(tt, {"groups": [], "by_pair": {}})
        d["groups"].append(gs["group_id"])
        verdicts = {(r["model"], r["leg"]): r["verdict"] for r in gs["legs"]}
        costs_per_leg = {(r["model"], r["leg"]): r["cost_usd"] for r in gs["legs"]}
        latencies = {(r["model"], r["leg"]): r["latency_s"] for r in gs["legs"]}
        keys = sorted(verdicts.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                pair = (keys[i], keys[j])
                pair_str = f"{pair[0][0]}[{pair[0][1]}] vs {pair[1][0]}[{pair[1][1]}]"
                pd = d["by_pair"].setdefault(pair_str, {
                    "groups": 0, "agreements": 0,
                    "cost_left": [], "cost_right": [],
                    "lat_left": [], "lat_right": [],
                })
                pd["groups"] += 1
                v_l, v_r = verdicts[pair[0]], verdicts[pair[1]]
                if v_l is not None and v_r is not None and v_l == v_r:
                    pd["agreements"] += 1
                if costs_per_leg[pair[0]] is not None:
                    pd["cost_left"].append(costs_per_leg[pair[0]])
                if costs_per_leg[pair[1]] is not None:
                    pd["cost_right"].append(costs_per_leg[pair[1]])
                if latencies[pair[0]] is not None:
                    pd["lat_left"].append(latencies[pair[0]])
                if latencies[pair[1]] is not None:
                    pd["lat_right"].append(latencies[pair[1]])

    if args.json:
        payload = {
            "scope_banner": SCOPE_BANNER,
            "since": since.isoformat() if since else None,
            "groups": group_summaries,
            "per_task": per_task,
            "warnings": {
                "stale_costs_days": stale_aggregated,
                "witness_absent_count": witness_absent_count,
            },
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    # Human report.
    print(SCOPE_BANNER)
    print()
    if not per_task:
        print(f"No shadow-correlated groups found (since={since or 'all-time'}, task={args.task_type or 'any'}).")
        print(f"Total ungrouped events: {len(events)}")
        return 0

    for tt, d in sorted(per_task.items()):
        print(f"task={tt}  groups={len(d['groups'])}")
        for pair_str, pd in sorted(d["by_pair"].items()):
            agree = f"{pd['agreements']}/{pd['groups']}" if pd["groups"] else "0/0"
            agree_pct = (
                f"{100.0 * pd['agreements'] / pd['groups']:.1f}%" if pd["groups"] else "N/A"
            )

            def _avg(xs: list[float]) -> str:
                return f"${sum(xs) / len(xs):.4f}" if xs else "n/a"

            def _lat(xs: list[float]) -> str:
                return f"{sum(xs) / len(xs):.1f}s" if xs else "n/a"

            print(f"  {pair_str}")
            print(f"    verdict agreement: {agree} = {agree_pct}")
            print(f"    avg cost: left {_avg(pd['cost_left'])}, right {_avg(pd['cost_right'])}")
            print(f"    avg latency: left {_lat(pd['lat_left'])}, right {_lat(pd['lat_right'])}")
        print()

    if stale_aggregated:
        print("WARNINGS:")
        for m, d in sorted(stale_aggregated.items()):
            print(f"  - {m}: cost price is {d}d stale (>90d); report run with --accept-stale-costs")
    if witness_absent_count:
        print(f"  - {witness_absent_count} logged group(s) have no witness file "
              f"(group-start was skipped or witness file deleted); treated as single-leg, not aggregated into leg-pair stats above.")
    # char_approx flag
    approx_count = sum(
        1 for gs in group_summaries for r in gs["legs"] if r["cost_method"] == "char_approx"
    )
    if approx_count:
        print(f"  - {approx_count} leg row(s) computed via char_approx (±25% true cost); see report fields cost_method=char_approx in --json output")
    return 0


# ---------- CLI ----------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="scripts/shadow.py",
        description="Cross-provider shadow-log correlation + reporting.",
    )
    sub = ap.add_subparsers(dest="subcommand", required=True)

    gs = sub.add_parser("group-start", help="Open a shadow group; print env exports + write witness file.")
    gs.add_argument("--task", required=True, help="Task type (e.g., system-review, decision, privacy-review).")
    gs.add_argument(
        "--expected", required=True,
        help='JSON list of expected dispatches, e.g. \'[{"model":"opus","leg":"native"},{"model":"deepseek_pro_max","leg":"direct"}]\'',
    )
    gs.set_defaults(func=cmd_group_start)

    lg = sub.add_parser("log", help="Append a synthetic native/codex-leg log entry.")
    lg.add_argument("--group", required=True, help="Shadow group UUID.")
    lg.add_argument("--task", required=True, help="Task type.")
    lg.add_argument("--model", required=True, help="Model identity from harness/models.toml.")
    lg.add_argument("--leg", required=True, choices=("native", "codex"), help="Dispatch kind (direct is auto-logged by chat_completion.py).")
    pf = lg.add_mutually_exclusive_group(required=True)
    pf.add_argument("--prompt-file", help="Path to prompt text.")
    pf.add_argument("--prompt-stdin", action="store_true", help="Read prompt from stdin (response must be --response-file).")
    rf = lg.add_mutually_exclusive_group(required=True)
    rf.add_argument("--response-file", help="Path to response text.")
    rf.add_argument("--response-stdin", action="store_true", help="Read response from stdin (prompt must be --prompt-file).")
    lg.add_argument("--log-dir", default=None, help="Override default log dir.")
    lg.set_defaults(func=cmd_log)

    rp = sub.add_parser("report", help="Aggregate logs and emit cost/verdict-agreement comparison.")
    rp.add_argument("--since", help="YYYY-MM-DD; only include events from this date forward.")
    rp.add_argument("--task-type", help="Filter to one task type.")
    rp.add_argument("--accept-stale-costs", action="store_true", help="Allow report when cost catalog is >90d stale.")
    rp.add_argument("--json", action="store_true", help="Emit JSON.")
    rp.set_defaults(func=cmd_report)

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
