#!/usr/bin/env python3
"""cues.py: Unified, quiet-by-default cue checker for /hi session start.

Why this exists: `/hi` (no args) needs to surface "you forgot to run X"
nudges (weekly review overdue, mobile-capture inbox pending). The old
pattern was inline Bash blocks in `.claude/commands/hi.md` that printed
debug lines (`days_since=4 latest=...`, `zettelm_pending=0`) into the
main conversation context on every invocation. That pollutes the model's
context window with state that means nothing to the user 90% of the time.

This script collapses every session-start cue into one call. It emits
NOTHING to stdout when no cue should fire. When a cue fires, it prints
one tab-separated line per cue:

    <key>\\t<severity>\\t<command_path>\\t<user-facing message>

The orchestrator parses each line and routes via the standard yes/no UI.
In the no-cue case the orchestrator sees zero output and proceeds
silently to the Step 1 menu — main context cost is bounded by the
command invocation itself, not the state of the vault.

Add new cues by appending a `check_*` function and registering it in
`CHECKS`. Each function returns either `None` (silent) or a `Cue`.

Output formats:
    default            tab-separated lines (one per fired cue)
    --json             JSON array of objects (for hook consumption)
    --verbose          add a `# debug: ...` line per check explaining the decision

Exits 0 always. Failing to find the vault still exits 0 with no output
so an unconfigured environment never blocks `/hi`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

# Allow running as `uv run scripts/cues.py` from atelier root.
sys.path.insert(0, str(Path(__file__).parent))
from _paths import tier, vault_root  # type: ignore[import-not-found]  # noqa: E402


@dataclass
class Cue:
    key: str
    severity: str  # "hard" | "soft"
    command_path: str  # relative path to the command file to route into on Yes
    message: str  # user-facing Chinese prompt


# --- individual checks ----------------------------------------------------


def check_weekly(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Weekly review cadence cue.

    Hard floor: >10 days since last weekly, or no weekly ever.
    Soft cue: >6 days since last weekly AND today is Sunday or Monday.
    """
    weekly_dir = tier("reflections")
    if not weekly_dir.is_dir():
        return None, "reflections dir missing; skip weekly cue"

    weeklies = sorted(weekly_dir.glob("*-weekly.md"))
    if not weeklies:
        return (
            Cue(
                key="weekly",
                severity="hard",
                command_path=".claude/commands/weekly.md",
                message=(
                    "还没跑过 weekly. 这周已经积累了 Apple Health / 信号 / "
                    "健康 cadence checks 没补齐. 建议先跑 `/weekly`. 现在跑吗?"
                ),
            ),
            "no weekly found; hard floor",
        )

    latest = weeklies[-1]
    try:
        latest_date = datetime.strptime(latest.name[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, f"could not parse date from {latest.name}; skip"

    days_since = (today - latest_date).days

    if days_since > 10:
        return (
            Cue(
                key="weekly",
                severity="hard",
                command_path=".claude/commands/weekly.md",
                message=(
                    f"上次 weekly 是 {days_since} 天前. 这周已经积累了 Apple Health / "
                    f"信号 / 健康 cadence checks 没补齐. 建议先跑 `/weekly`. 现在跑吗?"
                ),
            ),
            f"days_since={days_since} > 10; hard floor",
        )

    weekday = today.weekday()  # Mon=0, Sun=6
    if days_since > 6 and weekday in (6, 0):  # Sun or Mon
        return (
            Cue(
                key="weekly",
                severity="soft",
                command_path=".claude/commands/weekly.md",
                message=(
                    f"提示: 上次 weekly 是 {days_since} 天前. "
                    f"想现在跑 `/weekly` 把这周补齐吗?"
                ),
            ),
            f"days_since={days_since}, weekday={weekday}; soft cue",
        )

    return None, f"days_since={days_since}, weekday={weekday}; fresh"


def check_zettelm(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Zettelm (mobile capture submodule) pending-digest cue.

    Hard floor: >=3 pending files, or oldest file is >7 days old.
    Soft cue: >=1 pending file.
    Silent: empty.
    """
    zm = tier("zettelm")
    if not zm.is_dir():
        return None, "zettelm/ missing; skip"

    exts = (".md", ".pdf", ".jpg", ".jpeg", ".png", ".heic", ".m4a", ".mp3")
    ignored = {"README.md", ".gitignore", ".gitattributes"}

    pending = [
        p
        for p in zm.iterdir()
        if p.is_file() and p.suffix.lower() in exts and p.name not in ignored
    ]

    if not pending:
        return None, "zettelm empty; fresh"

    n = len(pending)
    oldest_mtime = min(p.stat().st_mtime for p in pending)
    oldest_age_days = (today - date.fromtimestamp(oldest_mtime)).days

    hard = n >= 3 or oldest_age_days > 7
    if hard:
        return (
            Cue(
                key="zettelm",
                severity="hard",
                command_path=".claude/commands/sync.md",
                message=(
                    f"zettelm 有 {n} 条待 digest (最老 {oldest_age_days} 天). "
                    f"建议先跑 `/sync` 把内容归位再继续. 现在跑吗?"
                ),
            ),
            f"n={n} oldest_age={oldest_age_days}; hard floor",
        )

    return (
        Cue(
            key="zettelm",
            severity="soft",
            command_path=".claude/commands/sync.md",
            message=f"提示: zettelm 有 {n} 条待 digest. 想现在跑 `/sync`?",
        ),
        f"n={n} oldest_age={oldest_age_days}; soft cue",
    )


def check_recurring(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Recurring obligations cue.

    Fires when one or more recurring items in $OV/gtd/recurring.md are overdue
    (today > last-done + every) or due-soon (within 7 days). Soft cue: advisory,
    surfaces the count and the most-overdue slug for context.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from recurring import parse_file  # type: ignore[import-not-found]
    except ImportError as exc:
        return None, f"recurring import failed: {exc!r}"

    items = parse_file()
    if not items:
        return None, "no recurring items defined"

    overdue = [i for i in items if i.status(today) == "overdue"]
    due_soon = [i for i in items if i.status(today) == "due-soon"]
    if not overdue and not due_soon:
        return None, f"all {len(items)} recurring items satisfied"

    parts = []
    if overdue:
        overdue.sort(key=lambda i: i.days_until_due(today))
        top = overdue[0]
        days = -top.days_until_due(today)
        parts.append(f"{len(overdue)} overdue (worst: {top.slug} -{days}d)")
    if due_soon:
        parts.append(f"{len(due_soon)} due ≤7d")
    listing = "; ".join(parts)
    return (
        Cue(
            key="recurring",
            severity="soft",
            command_path="scripts/recurring.py",
            message=(
                f"Recurring obligations: {listing}. "
                f"`uv run scripts/recurring.py list` to see."
            ),
        ),
        f"overdue={len(overdue)} due_soon={len(due_soon)}; soft cue",
    )


def check_aggregate_freshness(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Self-declared aggregate trackers lagging their subject SOT.

    Fires when `aggregate_freshness.py --discover --stale-only` reports one
    or more stale aggregates. Soft cue: the divergence is advisory, the
    user may still want to read the aggregate, but should know it's stale
    before quoting it.
    """
    # Import lazily so cues.py doesn't take an import-time dep on the script.
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from aggregate_freshness import discover  # type: ignore[import-not-found]
    except ImportError as exc:
        return None, f"aggregate_freshness import failed: {exc!r}"

    payload = discover(stale_only=True)
    stale = payload.get("stale_count", 0)
    if stale == 0:
        return None, f"discovered={payload.get('discovered', 0)} stale=0; fresh"

    names = []
    for g in payload["groups"]:
        for a in g["aggregates"]:
            p = a["path"].rsplit("/", 1)[-1]
            names.append(f"{p} (-{a['days_behind']}d)")
    listing = ", ".join(names[:3])
    if len(names) > 3:
        listing += f", +{len(names) - 3} more"
    return (
        Cue(
            key="aggregate_freshness",
            severity="soft",
            command_path="protocols/local-first-architecture.md",
            message=(
                f"{stale} aggregates stale: {listing}. "
                f"Cross-check subject SOT before quoting."
            ),
        ),
        f"stale={stale}; soft cue",
    )


def check_routine_outputs(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Unreviewed outputs from remote cron routines.

    Vault-agnostic mechanism: reads `$OV/_meta/routine_watch.toml` to learn
    which output directories belong to which routine. Each routine entry
    declares its `output_dir`, `file_pattern`, and human `label`. User policy
    lives in the TOML; this function is the engine.

    Ack mechanism: `$OV/_meta/routine_acks.json` stores `{output_dir: last_acked_filename}`.
    Cue fires when a directory's latest file (sorted by filename) > acked filename.
    User mutes by updating that JSON after reading a report.
    """
    import json
    import tomllib

    config_path = ov / "_meta" / "routine_watch.toml"
    if not config_path.is_file():
        return None, "_meta/routine_watch.toml missing; skip"

    try:
        config = tomllib.loads(config_path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return None, f"routine_watch.toml parse failed: {exc!r}"

    routines = config.get("routine", [])
    if not routines:
        return None, "no routines declared in routine_watch.toml"

    ack_path = ov / "_meta" / "routine_acks.json"
    acks: dict[str, str] = {}
    if ack_path.is_file():
        try:
            acks = json.loads(ack_path.read_text())
        except (json.JSONDecodeError, OSError):
            acks = {}

    new_findings: list[str] = []
    debug_parts: list[str] = []
    for r in routines:
        output_dir = r.get("output_dir")
        pattern = r.get("file_pattern", "*")
        label = r.get("label", r.get("name", "?"))
        if not output_dir:
            debug_parts.append(f"{label}: missing output_dir")
            continue
        d = ov / output_dir
        if not d.is_dir():
            debug_parts.append(f"{label}: dir missing")
            continue
        files = sorted(d.glob(pattern), key=lambda p: p.name)
        if not files:
            debug_parts.append(f"{label}: no files yet")
            continue
        latest = files[-1]
        last_ack = acks.get(output_dir, "")
        if latest.name > last_ack:
            new_findings.append(f"{label} ({latest.name})")
            debug_parts.append(f"{label}: new={latest.name} > ack={last_ack or '∅'}")
        else:
            debug_parts.append(f"{label}: acked")

    debug = "; ".join(debug_parts)
    if not new_findings:
        return None, debug

    listing = "; ".join(new_findings[:3])
    if len(new_findings) > 3:
        listing += f", +{len(new_findings) - 3} more"

    return (
        Cue(
            key="routine_outputs",
            severity="soft",
            command_path="_meta/routine_acks.json",
            message=(
                f"Remote cron routines 有新 output 待 review: {listing}. "
                f"读完后 update `_meta/routine_acks.json` "
                f"({{<output_dir>: <latest filename>}}) 来 mute."
            ),
        ),
        f"new={len(new_findings)}; {debug}",
    )


# Registry. To add a new cue, append a `check_*` function above and
# register it here.
CHECKS = [
    ("weekly", check_weekly),
    ("zettelm", check_zettelm),
    ("recurring", check_recurring),
    ("aggregate_freshness", check_aggregate_freshness),
    ("routine_outputs", check_routine_outputs),
]


# --- main -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Quiet-by-default cue checks for /hi session start."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON array instead of tab-separated lines.",
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Emit Claude Code SessionStart hook output: when cues fire, "
        "print a `hookSpecificOutput.additionalContext` JSON; when silent, "
        "print nothing. Exit 0 always.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-check reasoning to stderr.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Run only the named cue (debug aid).",
    )
    args = parser.parse_args(argv)

    if not os.environ.get("OV"):
        return 0
    ov = vault_root()
    today = date.today()

    fired: list[Cue] = []
    for name, fn in CHECKS:
        if args.only and name != args.only:
            continue
        try:
            cue, reason = fn(ov, today)
        except Exception as exc:  # never let a cue check break /hi
            if args.verbose:
                print(f"# debug: {name} raised {exc!r}", file=sys.stderr)
            continue
        if args.verbose:
            tag = "FIRED" if cue else "silent"
            print(f"# debug: {name} {tag}: {reason}", file=sys.stderr)
        if cue:
            fired.append(cue)

    if args.hook:
        # Claude Code SessionStart hook protocol. Silent when no cue fires;
        # injects fired cues as a system reminder on the next model call.
        if not fired:
            return 0
        lines = [f"- {c.message} (route: `{c.command_path}`)" for c in fired]
        context = "Session-start cues (atelier):\n" + "\n".join(lines)
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(payload, ensure_ascii=False))
    elif args.json:
        print(json.dumps([asdict(c) for c in fired], ensure_ascii=False))
    else:
        for c in fired:
            print(f"{c.key}\t{c.severity}\t{c.command_path}\t{c.message}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
