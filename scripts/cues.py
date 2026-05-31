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

Snooze:
    cues.py snooze <key> [--days N]    suppress a cue until N days from today

Snooze state lives at `$OV/_meta/cue_snooze.json`. Useful for soft cues
where the user has reviewed the state and accepted the lag (e.g.,
aggregate_freshness when the underlying aggregate update is queued).

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
from typing import Literal

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
    # Note: this count is local-only. The remote may have more files
    # that haven't been pulled yet. /sync pulls before scanning.
    local_hint = " (本地; remote 可能更多)"
    if hard:
        return (
            Cue(
                key="zettelm",
                severity="hard",
                command_path=".claude/commands/sync.md",
                message=(
                    f"zettelm 有 {n} 条待 digest{local_hint} (最老 {oldest_age_days} 天). "
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
            message=f"提示: zettelm 有 {n} 条待 digest{local_hint}. 想现在跑 `/sync`?",
        ),
        f"n={n} oldest_age={oldest_age_days}; soft cue",
    )


def check_recurring(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Recurring obligations cue.

    Fires when one or more recurring items in $OV/gtd/recurring.md are overdue
    (today > last-done + every) or due-soon (within 7 days). Severity escalates
    to `hard` when any item is overdue by more than 30 days — a 100-day-overdue
    health/maintenance task should not register softer than a 7-day-old
    zettelm capture.
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
    worst_days = 0
    if overdue:
        overdue.sort(key=lambda i: i.days_until_due(today))
        top = overdue[0]
        worst_days = -top.days_until_due(today)
        parts.append(f"{len(overdue)} overdue (worst: {top.slug} -{worst_days}d)")
    if due_soon:
        parts.append(f"{len(due_soon)} due ≤7d")
    listing = "; ".join(parts)
    severity: Literal["hard", "soft"] = "hard" if worst_days > 30 else "soft"
    mute_hint = "Run `uv run scripts/recurring.py done <slug>` when complete."
    return (
        Cue(
            key="recurring",
            severity=severity,
            command_path="scripts/recurring.py",
            message=(
                f"Recurring obligations: {listing}. "
                f"`uv run scripts/recurring.py list` to see. {mute_hint}"
            ),
        ),
        f"overdue={len(overdue)} due_soon={len(due_soon)} worst={worst_days}d; {severity} cue",
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


def check_routine_policy(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Policy compliance for remote-routine $OV-persistence.

    Per `protocols/remote-routines.md` § Policy, every routine MUST persist
    canonical output to $OV. Each routine entry in
    `$OV/_meta/routine_watch.toml` should declare either:
      - `drive_write_enforced = true`  (compliant), OR
      - `needs_drive_write_update = true`  (acknowledged migration debt)
    A routine missing both flags violates the policy without acknowledgment.
    Surfaces the count of non-compliant routines as a soft cue.
    """
    import tomllib

    config_path = ov / "_meta" / "routine_watch.toml"
    if not config_path.is_file():
        return None, "no routine_watch.toml; skip"
    try:
        config = tomllib.loads(config_path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return None, f"toml parse failed: {exc!r}"
    routines = config.get("routine", [])
    if not routines:
        return None, "no routines declared"
    violators: list[str] = []
    for r in routines:
        # Local routines write to $OV directly via the filesystem; the Drive-write
        # policy applies only to remote (claude.ai) routines that persist over MCP.
        # Per protocols/remote-routines.md § routine_watch.toml: local entries
        # carry no drive_write_enforced flag.
        if r.get("execution") == "local":
            continue
        if r.get("drive_write_enforced") is True:
            continue
        if r.get("needs_drive_write_update") is True:
            continue
        violators.append(str(r.get("name", "?")))
    if not violators:
        return None, f"all {len(routines)} routines compliant"
    listing = ", ".join(violators[:3])
    if len(violators) > 3:
        listing += f", +{len(violators) - 3} more"
    return (
        Cue(
            key="routine_policy",
            severity="soft",
            command_path="protocols/remote-routines.md",
            message=(
                f"{len(violators)} routine(s) without policy ack "
                f"(neither `drive_write_enforced` nor `needs_drive_write_update` set): "
                f"{listing}. Per `protocols/remote-routines.md` § Policy: every "
                f"routine MUST persist to $OV. Set the appropriate flag in "
                f"`$OV/_meta/routine_watch.toml`."
            ),
        ),
        f"violators={len(violators)}/{len(routines)}; soft cue",
    )


def check_routine_staleness(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Detect routines that fire but produce no output.

    For each routine in routine_watch.toml, estimates expected cadence from
    the cron field, then checks whether the latest output file is older than
    cadence + tolerance. Catches silent Drive-write failures that
    check_routine_outputs (which only reports *new* files) cannot see.
    """
    import re
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
        return None, "no routines declared"

    stale: list[str] = []
    debug_parts: list[str] = []

    for r in routines:
        label = r.get("label", r.get("name", "?"))
        output_dir = r.get("output_dir")
        pattern = r.get("file_pattern", "*")
        cron = r.get("cron", "")
        if not output_dir or not cron:
            debug_parts.append(f"{label}: missing output_dir or cron")
            continue

        cadence_days = _estimate_cadence_days(cron)
        if cadence_days is None:
            debug_parts.append(f"{label}: unparseable cron")
            continue

        tolerance = max(2, cadence_days)
        threshold = cadence_days + tolerance

        d = ov / output_dir
        if not d.is_dir():
            stale.append(f"{label} (output dir missing)")
            debug_parts.append(f"{label}: dir missing; cadence={cadence_days}d")
            continue

        files = sorted(d.glob(pattern), key=lambda p: p.name)
        if not files:
            stale.append(f"{label} (no output files)")
            debug_parts.append(f"{label}: no files; cadence={cadence_days}d")
            continue

        latest_name = files[-1].name
        latest_date = _extract_date_from_filename(latest_name)
        if latest_date is None:
            debug_parts.append(f"{label}: can't parse date from {latest_name}")
            continue

        age = (today - latest_date).days
        if age > threshold:
            stale.append(f"{label} (last output {age}d ago, expected every {cadence_days}d)")
            debug_parts.append(f"{label}: age={age}d > threshold={threshold}d")
        else:
            debug_parts.append(f"{label}: age={age}d <= threshold={threshold}d; ok")

    debug = "; ".join(debug_parts)
    if not stale:
        return None, debug

    listing = "; ".join(stale[:3])
    if len(stale) > 3:
        listing += f", +{len(stale) - 3} more"

    return (
        Cue(
            key="routine_staleness",
            severity="hard",
            command_path="_meta/routine_watch.toml",
            message=(
                f"{len(stale)} routine(s) with missing/stale output: {listing}. "
                f"Check routine session logs on claude.ai for silent Drive-write failures "
                f"or missing MCP connections."
            ),
        ),
        f"stale={len(stale)}; {debug}",
    )


def check_routine_hitrate(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Detect routines with intermittent output failures.

    Complements check_routine_staleness (which catches total outages) by
    counting actual vs expected output files over a lookback window. A daily
    routine that succeeds every other day never triggers staleness, but its
    hit rate is 50% and should surface.

    Lookback window: max(14, 3 * cadence) days. This gives enough samples
    for statistical signal while staying recent enough to reflect current
    reliability. Fires when hit rate drops below 70%.

    Only evaluates routines with cadence <= 7 days; longer-cadence routines
    (monthly, quarterly) don't accumulate enough samples for hit-rate math
    and are adequately covered by check_routine_staleness.
    """
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
        return None, "no routines declared"

    degraded: list[str] = []
    debug_parts: list[str] = []

    for r in routines:
        label = r.get("label", r.get("name", "?"))
        output_dir = r.get("output_dir")
        pattern = r.get("file_pattern", "*")
        cron = r.get("cron", "")
        if not output_dir or not cron:
            continue

        cadence_days = _estimate_cadence_days(cron)
        if cadence_days is None or cadence_days > 7:
            debug_parts.append(f"{label}: cadence={cadence_days}d; skip hitrate")
            continue

        d = ov / output_dir
        if not d.is_dir():
            continue  # staleness cue handles this

        max_lookback = max(14, 3 * cadence_days)
        cutoff = today - __import__("datetime").timedelta(days=max_lookback)

        files = sorted(d.glob(pattern), key=lambda p: p.name)
        dated_files: list[date] = []
        for f in files:
            fd = _extract_date_from_filename(f.name)
            if fd is not None:
                dated_files.append(fd)

        if not dated_files:
            continue  # staleness cue handles this

        # Cap lookback to oldest file date so new routines aren't penalized
        # for not existing before their first output.
        oldest_file = min(dated_files)
        effective_start = max(cutoff, oldest_file)
        effective_lookback = (today - effective_start).days
        if effective_lookback < 1:
            effective_lookback = 1

        recent = [fd for fd in dated_files if fd >= effective_start]
        expected = effective_lookback // cadence_days
        if expected < 3:
            debug_parts.append(
                f"{label}: expected={expected} in {effective_lookback}d; too few samples"
            )
            continue

        actual = len(recent)
        rate = actual / expected if expected > 0 else 1.0

        if rate < 0.70:
            pct = int(rate * 100)
            degraded.append(f"{label} ({actual}/{expected} runs, {pct}%)")
            debug_parts.append(
                f"{label}: {actual}/{expected} in {effective_lookback}d = {pct}%; degraded"
            )
        else:
            pct = int(rate * 100)
            debug_parts.append(
                f"{label}: {actual}/{expected} in {effective_lookback}d = {pct}%; ok"
            )

    debug = "; ".join(debug_parts)
    if not degraded:
        return None, debug

    listing = "; ".join(degraded[:3])
    if len(degraded) > 3:
        listing += f", +{len(degraded) - 3} more"

    return (
        Cue(
            key="routine_hitrate",
            severity="soft",
            command_path="_meta/routine_watch.toml",
            message=(
                f"{len(degraded)} routine(s) with degraded output rate: {listing}. "
                f"Routines are firing but Drive writes fail intermittently. "
                f"Check routine session logs on claude.ai."
            ),
        ),
        f"degraded={len(degraded)}; {debug}",
    )


def _estimate_cadence_days(cron: str) -> int | None:
    """Estimate cadence in days from a cron-like expression.

    Handles common patterns from routine_watch.toml cron fields:
      "0 13 * * *"       -> daily (1)
      "0 10 * * 3"       -> weekly (7)
      "0 12 */3 * *"     -> every 3 days (3)
      "0 9 15 2,5,8,11 *" -> quarterly (~90)
    """
    # Strip annotations like "UTC (5 AM PT every 3 days)"
    import re as _re

    cron_clean = _re.split(r"\s+UTC\b", cron)[0].strip()
    parts = cron_clean.split()
    if len(parts) < 5:
        return None

    _minute, _hour, dom, month, dow = parts[:5]

    if month != "*":
        # Monthly subset: count the months listed
        months = month.split(",")
        if len(months) >= 2:
            return 365 // len(months)
        return 30

    if dom.startswith("*/"):
        try:
            return int(dom[2:])
        except ValueError:
            return None

    if dom == "*" and dow == "*":
        return 1

    if dom == "*" and dow != "*":
        return 7

    return 30


def _extract_date_from_filename(name: str) -> date | None:
    """Extract YYYY-MM-DD from a filename prefix or embedded pattern."""
    import re as _re

    m = _re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def check_autoevo_pending(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Pending autoevo decisions awaiting human triage.

    `/autoevo-nightly` writes uncertain Forgetter findings to
    `$OV/_meta/autoevo_pending.toml` (status = "pending"). This cue
    surfaces them at session start with a per-category breakdown so the
    user can run `/autoevo-review` to triage. Per `protocols/autoevo.md`.

    Severity is `soft` by default. Escalates to `hard` when any of:
    - any entry's `proposed_at` is more than 14 days ago
    - any entry's `proposed_at` failed to parse (corrupt_dates > 0); a
      queue with bad timestamps can hide arbitrarily old entries
    - any entry's `surface_count >= 3` (the auto-dismiss threshold from
      `/autoevo-review`; surface before the entry is silently swept)

    Stays silent when the queue file is missing, empty, or all entries
    are already resolved (status != "pending").
    """
    import tomllib

    config_path = ov / "_meta" / "autoevo_pending.toml"
    if not config_path.is_file():
        return None, "_meta/autoevo_pending.toml missing; skip"

    try:
        config = tomllib.loads(config_path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        # A queue file that exists but cannot be parsed is the worst-of-both:
        # /autoevo-review will refuse to operate, /autoevo-nightly's queue
        # append will likely also fail, and silent return here would leave
        # the user with no signal at all. Fire a hard cue routing the user
        # to repair the file by hand.
        return (
            Cue(
                key="autoevo_pending",
                severity="hard",
                command_path="_meta/autoevo_pending.toml",
                message=(
                    f"Autoevo pending queue file is corrupted "
                    f"(`_meta/autoevo_pending.toml`): {type(exc).__name__}. "
                    f"`/autoevo-review` and `/autoevo-nightly` queue ops cannot proceed. "
                    f"Repair by hand (TOML syntax), or back up + restart with an empty file."
                ),
            ),
            f"autoevo_pending.toml parse failed: {exc!r}; hard cue",
        )

    entries = config.get("pending", [])
    if not entries:
        return None, "no pending entries declared"

    # Filter to actually-pending entries.
    pending = [e for e in entries if e.get("status", "pending") == "pending"]
    if not pending:
        return None, f"all {len(entries)} entries resolved"

    # Group by category, track oldest age, count entries with unparseable dates,
    # count entries the user has repeatedly skipped (auto-dismiss threshold).
    counts: dict[str, int] = {}
    oldest_age = 0
    corrupt_dates = 0
    repeat_skips = 0
    for e in pending:
        cat = str(e.get("category", "unknown"))
        counts[cat] = counts.get(cat, 0) + 1
        proposed = e.get("proposed_at", "")
        try:
            proposed_date = date.fromisoformat(str(proposed))
            age = (today - proposed_date).days
            if age > oldest_age:
                oldest_age = age
        except (ValueError, TypeError):
            corrupt_dates += 1
        # surface_count >= 3 is the auto-dismiss threshold per
        # protocols/autoevo.md § Pending queue. If any entry has been
        # repeatedly skipped, escalate so the user sees them before /autoevo-review
        # auto-dismisses them on its next run.
        try:
            if int(e.get("surface_count", 0)) >= 3:
                repeat_skips += 1
        except (ValueError, TypeError):
            continue

    listing = ", ".join(
        f"{cat}: {n}" for cat, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    # Escalate to `hard` on age (>14d), corrupt dates (parsability lost), OR
    # repeat-skip entries (3+ skips reach auto-dismiss next /autoevo-review).
    severity: Literal["hard", "soft"] = (
        "hard"
        if (oldest_age > 14 or corrupt_dates > 0 or repeat_skips > 0)
        else "soft"
    )
    age_note = f"oldest {oldest_age}d" if oldest_age > 0 else "fresh"
    corrupt_note = f"; {corrupt_dates} corrupt dates" if corrupt_dates > 0 else ""
    skip_note = f"; {repeat_skips} ≥3 skips" if repeat_skips > 0 else ""
    return (
        Cue(
            key="autoevo_pending",
            severity=severity,
            command_path=".claude/commands/autoevo-review.md",
            message=(
                f"{len(pending)} pending autoevo decisions ({listing}; {age_note}{corrupt_note}{skip_note}). "
                f"`/autoevo-review` to triage."
            ),
        ),
        f"pending={len(pending)} oldest_age={oldest_age} corrupt={corrupt_dates} skips={repeat_skips}; {severity} cue",
    )


def check_autoevo_ran(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Catches silent nightly-bot failures AND surfaces skipped runs.

    `/autoevo-nightly` writes `<paths.agent_findings>/autoevo-applied-<RUN_DATE>.md`
    on every run — even when a pre-flight gate aborts (the Skipped section
    is populated). The bot fires at 05:00 local, so RUN_DATE is today, and
    this cue (gated to fire after 06:00) inspects today's audit file. Two
    failure modes to surface:

    1. **Audit file missing.** The bot did not run at all (launchd auth
       failed, $OV unset, claude CLI missing, etc.). Soft cue pointing at
       the launchd README.
    2. **Audit file exists with non-empty Skipped / Errors section.** The
       bot ran but a pre-flight gate aborted, OR an error occurred during
       a step. Soft cue pointing at the file so the user can read details.

    Stays silent when:
    - The agent-findings dir doesn't exist yet (fresh vault, bot never ran).
    - Today's audit file exists AND its Skipped/Errors sections are
      empty or contain only "(none)".
    - It is earlier than 06:00 local today (the 5am bot might still be running).

    Soft cue by default.
    """
    from datetime import datetime

    # Don't fire before 06:00 local — bot is given a full hour to complete.
    if datetime.now().hour < 6:
        return None, "before 06:00 local; skip"

    findings_dir = tier("agent_findings")
    if not findings_dir.is_dir():
        return None, "agent_findings dir missing; bot never installed"

    # The bot runs at 05:00 local and writes its audit log with today's
    # RUN_DATE. After 06:00 today, today's audit file should exist.
    expected_name = f"autoevo-applied-{today.isoformat()}.md"
    expected_path = findings_dir / expected_name

    # Branch 1: audit file missing entirely.
    if not expected_path.is_file():
        # If NO audit log exists at all under the dir, the bot was probably
        # never installed yet — stay silent rather than nag a user who hasn't
        # set it up.
        any_audit = list(findings_dir.glob("autoevo-applied-*.md"))
        if not any_audit:
            return None, "no audit logs ever; bot not installed yet"
        return (
            Cue(
                key="autoevo_ran",
                severity="soft",
                command_path="scripts/launchd/README.md",
                message=(
                    f"Nightly autoevo did not run today ({today.isoformat()}). "
                    f"Check `/tmp/com.atelier.autoevo-nightly.err` and "
                    f"`~/Library/LaunchAgents/com.atelier.autoevo-nightly.plist`. "
                    f"Common causes: $OV unset in launchd shell, expired Claude Code credentials, "
                    f"machine asleep at 05:00."
                ),
            ),
            f"expected {expected_name} missing",
        )

    # Branch 2: audit file exists — inspect Skipped/Errors sections for
    # content. A populated Skipped section means a pre-flight gate fired;
    # a populated Errors section means a mid-run failure happened.
    try:
        body = expected_path.read_text()
    except OSError as exc:
        return None, f"audit file unreadable: {exc!r}"

    # Parse "### Skipped (reason)" and "### Errors" sections. The audit log
    # may contain MULTIPLE `## Run` sections in the same day (manual re-runs),
    # each with its own Skipped / Errors subsections. A single populated
    # section in any run is enough to fire the cue, so scan all matches.
    # Stop at the NEXT heading of any level (### or ##) so a Skipped section
    # body does not accidentally include the immediately-following ### Errors
    # heading and produce a false "populated" verdict on clean runs.
    def section_populated(text: str, heading: str) -> bool:
        import re
        pat = rf"^###\s+{re.escape(heading)}.*?\n(.*?)(?=^###|^##|\Z)"
        for m in re.finditer(pat, text, re.MULTILINE | re.DOTALL):
            for raw in m.group(1).splitlines():
                line = raw.strip()
                if not line or line in ("(none)", "- (none)"):
                    continue
                return True
        return False

    skipped = section_populated(body, "Skipped")
    errored = section_populated(body, "Errors")

    if not skipped and not errored:
        return None, f"today's audit log clean ({expected_name})"

    parts: list[str] = []
    if skipped:
        parts.append("Skipped section populated")
    if errored:
        parts.append("Errors section populated")
    listing = " and ".join(parts)
    return (
        Cue(
            key="autoevo_ran",
            severity="soft",
            command_path=str(expected_path.relative_to(ov)),
            message=(
                f"Today's nightly autoevo ran with issues: {listing}. "
                f"Read `{expected_path.relative_to(ov)}` for the audit details."
            ),
        ),
        f"audit log present but {listing}",
    )


def _recap_local_runs(ov: Path, today: date, verbose: bool = False) -> list[str]:
    """One-liner recaps of recent local routine runs (informational, not cues).

    Reads claim files from `$OV/_meta/routine_runs/*/` for today and yesterday.
    For completed runs, peeks at the corresponding audit log (if any) to extract
    counts. Returns a list of human-readable recap lines.
    """
    import re
    import tomllib

    runs_dir = ov / "_meta" / "routine_runs"
    if not runs_dir.is_dir():
        return []

    recaps: list[str] = []
    yesterday = today - __import__("datetime").timedelta(days=1)

    for routine_dir in sorted(runs_dir.iterdir()):
        if not routine_dir.is_dir():
            continue
        routine_name = routine_dir.name

        for check_date in [today, yesterday]:
            claim = routine_dir / f"{check_date.isoformat()}.toml"
            if not claim.is_file():
                continue
            try:
                data = tomllib.loads(claim.read_text())
            except Exception:
                continue

            status = data.get("status", "unknown")
            machine = data.get("machine", "?")
            duration = data.get("duration_seconds")

            if status != "completed":
                continue

            summary = data.get("result_summary", "")
            if not summary:
                summary = _extract_audit_summary(ov, routine_name, check_date)

            dur_str = f" ({duration}s)" if duration else ""
            date_str = "today" if check_date == today else "yesterday"
            recap = f"{routine_name} ran {date_str} on {machine}{dur_str}"
            if summary:
                recap += f": {summary}"
            recaps.append(recap)
            break  # only show the most recent per routine

    if verbose and recaps:
        for r in recaps:
            print(f"# debug: recap: {r}", file=sys.stderr)

    return recaps


def _extract_audit_summary(ov: Path, routine_name: str, run_date: date) -> str:
    """Extract a short summary from an autoevo audit log."""
    import re

    if routine_name != "autoevo-nightly":
        return ""

    findings_dir = ov / "agent-findings"
    if not findings_dir.is_dir():
        return ""

    audit = findings_dir / f"autoevo-applied-{run_date.isoformat()}.md"
    if not audit.is_file():
        return ""

    try:
        body = audit.read_text(errors="replace")
    except OSError:
        return ""

    counts: dict[str, int] = {}
    for heading in ("Auto-applied", "Logged to pending queue", "Skipped", "Errors"):
        pat = rf"^###\s+{re.escape(heading)}\s*\((\d+)\)"
        m = re.search(pat, body, re.MULTILINE)
        if m:
            counts[heading.split()[0].lower()] = int(m.group(1))
            continue
        # Count bullet lines under the heading.
        sect_pat = rf"^###\s+{re.escape(heading)}.*?\n(.*?)(?=^###|^##|\Z)"
        sect_m = re.search(sect_pat, body, re.MULTILINE | re.DOTALL)
        if sect_m:
            bullets = [
                ln
                for ln in sect_m.group(1).splitlines()
                if ln.strip().startswith("- ") and ln.strip() not in ("- (none)",)
            ]
            if bullets:
                counts[heading.split()[0].lower()] = len(bullets)

    if not counts:
        return ""

    parts = [f"{k}={v}" for k, v in counts.items()]
    return ", ".join(parts)


def check_local_routine_missed(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Detect local routines that missed their scheduled run.

    Reads `$OV/_meta/routine_watch.toml` for routines with `execution = "local"`.
    For each, checks `$OV/_meta/routine_runs/<name>/<cycle_id>.toml` for a
    claim file with `status = "completed"`. Fires when today's (or yesterday's,
    for early-morning sessions) claim is missing or failed.

    Gated to fire after 06:00 local so the routine has time to complete.
    Stays silent when no local routines are declared or `routine_runs/` is absent
    (bot never installed).
    """
    import tomllib

    if datetime.now().hour < 6:
        return None, "before 06:00 local; skip"

    config_path = ov / "_meta" / "routine_watch.toml"
    if not config_path.is_file():
        return None, "_meta/routine_watch.toml missing; skip"

    try:
        config = tomllib.loads(config_path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return None, f"routine_watch.toml parse failed: {exc!r}"

    routines = [r for r in config.get("routine", []) if r.get("execution") == "local"]
    if not routines:
        return None, "no local routines declared"

    runs_dir = ov / "_meta" / "routine_runs"
    if not runs_dir.is_dir():
        # Never installed on any machine; stay silent until first run.
        any_local_ever = any(
            (runs_dir / r.get("name", "")).is_dir() for r in routines
        )
        if not any_local_ever:
            return None, "routine_runs/ absent; never installed"

    missed: list[str] = []
    debug_parts: list[str] = []

    for r in routines:
        name = r.get("name", "?")
        label = r.get("label", name)
        routine_dir = runs_dir / name

        if not routine_dir.is_dir():
            # Check if this routine has ever run on any machine.
            # If not, skip (not installed yet).
            debug_parts.append(f"{label}: no runs dir")
            continue

        # Check today's claim, fall back to yesterday for early-morning edge.
        claim_found = False
        for check_date in [today, today - __import__("datetime").timedelta(days=1)]:
            claim = routine_dir / f"{check_date.isoformat()}.toml"
            if claim.is_file():
                try:
                    claim_data = tomllib.loads(claim.read_text())
                    status = claim_data.get("status", "unknown")
                    if status == "completed":
                        claim_found = True
                        debug_parts.append(f"{label}: {check_date} completed")
                        break
                    elif status == "running":
                        claim_found = True
                        debug_parts.append(f"{label}: {check_date} still running")
                        break
                    elif status == "failed":
                        missed.append(f"{label} (failed on {check_date})")
                        debug_parts.append(f"{label}: {check_date} failed")
                        claim_found = True
                        break
                except (tomllib.TOMLDecodeError, OSError):
                    debug_parts.append(f"{label}: {check_date} claim unreadable")
                    continue

        if not claim_found:
            # Check if this routine has EVER run (any .toml in the dir).
            any_past = list(routine_dir.glob("*.toml"))
            if any_past:
                missed.append(f"{label} (no run today)")
                debug_parts.append(f"{label}: missed today; {len(any_past)} past runs exist")
            else:
                debug_parts.append(f"{label}: never ran; skip")

    debug = "; ".join(debug_parts)
    if not missed:
        return None, debug

    listing = "; ".join(missed[:3])
    if len(missed) > 3:
        listing += f", +{len(missed) - 3} more"

    return (
        Cue(
            key="local_routine_missed",
            severity="soft",
            command_path="scripts/launchd/README.md",
            message=(
                f"{len(missed)} local routine(s) missed: {listing}. "
                f"Common causes: machine asleep, launchd not loaded, expired credentials. "
                f"Run the routine manually or check `scripts/launchd/README.md`."
            ),
        ),
        f"missed={len(missed)}; {debug}",
    )


def check_career_growth(ov: Path, today: date) -> tuple[Cue | None, str]:
    """Sunday weekly growth review toward "最懂 research 的 infra engineer".

    Standing user request (2026-05-31): every Sunday, in any conversation,
    review the past week's growth (papers read, engineering output, foresight
    RFCs, OSS) against `career/career-plan-2026.md` and flag forgotten / drift
    / adjust on the route.

    Fires (soft) when:
      - today is Sunday (weekday 6) AND the last growth-review is >=6 days old
        (or none exists yet), OR
      - it's been >9 days since the last growth-review (catches a missed Sunday
        on whatever weekday the next session lands).

    Goes silent once a `reflections/YYYY-MM-DD-growth-review.md` exists for the
    current week. Stays silent entirely if the plan file is absent (goal not set
    up). Snooze: `cues.py snooze career_growth [--days N]`.
    """
    plan_path = ov / "career" / "career-plan-2026.md"
    if not plan_path.is_file():
        return None, "career/career-plan-2026.md missing; goal not set up"

    refl = tier("reflections")
    if not refl.is_dir():
        return None, "reflections dir missing; skip"

    reviews = sorted(refl.glob("*-growth-review.md"))
    days_since: int | None = None
    if reviews:
        try:
            latest_date = datetime.strptime(reviews[-1].name[:10], "%Y-%m-%d").date()
            days_since = (today - latest_date).days
        except ValueError:
            days_since = None

    is_sunday = today.weekday() == 6  # Mon=0 .. Sun=6

    if days_since is None:
        fire = is_sunday
        reason = f"no prior growth-review; sunday={is_sunday}"
    elif is_sunday and days_since >= 6:
        fire = True
        reason = f"sunday, days_since={days_since}"
    elif days_since > 9:
        fire = True
        reason = f"missed sunday, days_since={days_since}"
    else:
        fire = False
        reason = f"days_since={days_since}, weekday={today.weekday()}; fresh"

    if not fire:
        return None, reason

    return (
        Cue(
            key="career_growth",
            severity="soft",
            command_path="career/career-plan-2026.md",
            message=(
                "周日 growth review: 过去一周朝「最懂 research 的 infra engineer」"
                "的成长 (论文阅读 / 工程产出 / foresight RFC / OSS),对照 "
                "`career/career-plan-2026.md` 的 cadence,看有没有忘记 / 偏离 / "
                "要调整路线。现在过一下吗?"
            ),
        ),
        reason,
    )


# Registry. To add a new cue, append a `check_*` function above and
# register it here.
CHECKS = [
    ("weekly", check_weekly),
    ("zettelm", check_zettelm),
    ("recurring", check_recurring),
    ("aggregate_freshness", check_aggregate_freshness),
    ("routine_outputs", check_routine_outputs),
    ("routine_staleness", check_routine_staleness),
    ("routine_hitrate", check_routine_hitrate),
    ("routine_policy", check_routine_policy),
    ("autoevo_pending", check_autoevo_pending),
    ("autoevo_ran", check_autoevo_ran),
    ("local_routine_missed", check_local_routine_missed),
    ("career_growth", check_career_growth),
]


# --- snooze: per-key, per-day suppression ---------------------------------


def _snooze_path(ov: Path) -> Path:
    return ov / "_meta" / "cue_snooze.json"


def _load_snoozes(ov: Path) -> dict[str, str]:
    p = _snooze_path(ov)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except (json.JSONDecodeError, OSError):
        return {}


def _is_snoozed(snoozes: dict[str, str], key: str, today: date) -> bool:
    val = snoozes.get(key)
    if not val:
        return False
    try:
        return date.fromisoformat(val) >= today
    except ValueError:
        return False


def snooze_cue(ov: Path, key: str, until: date) -> None:
    p = _snooze_path(ov)
    p.parent.mkdir(parents=True, exist_ok=True)
    snoozes = _load_snoozes(ov)
    snoozes[key] = until.isoformat()
    p.write_text(json.dumps(snoozes, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


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
    parser.add_argument(
        "--touch-lock",
        action="store_true",
        help="Refresh the session-active lock and exit. No cue checks run; "
        "the lock path is resolved via the registry. Used by the "
        "UserPromptSubmit hook so long-running sessions keep the lock fresh "
        "without paying for a full sweep on every prompt.",
    )
    # Snooze subcommand: `cues.py snooze <key> [--days N]` writes a
    # per-key snooze entry to $OV/_meta/cue_snooze.json. The next session
    # skips fired cues whose key matches until the snooze expires.
    if argv is None:
        argv_list = sys.argv[1:]
    else:
        argv_list = list(argv)
    if argv_list and argv_list[0] == "snooze":
        if not os.environ.get("OV"):
            print("ERROR: $OV not set; cannot snooze.", file=sys.stderr)
            return 2
        if len(argv_list) < 2:
            print("ERROR: snooze requires <key> argument", file=sys.stderr)
            return 2
        key = argv_list[1]
        if key not in {name for name, _ in CHECKS}:
            print(f"ERROR: unknown cue `{key}`; valid: {sorted({n for n,_ in CHECKS})}", file=sys.stderr)
            return 2
        days = 1
        if "--days" in argv_list:
            try:
                days = int(argv_list[argv_list.index("--days") + 1])
            except (ValueError, IndexError):
                print("ERROR: --days requires an integer", file=sys.stderr)
                return 2
        ov = vault_root()
        until = date.today().fromordinal(date.today().toordinal() + days)
        snooze_cue(ov, key, until)
        print(f"snoozed `{key}` until {until.isoformat()}")
        return 0

    args = parser.parse_args(argv)

    if not os.environ.get("OV"):
        return 0
    ov = vault_root()
    today = date.today()

    # --touch-lock: lightweight per-prompt refresh path used by the
    # UserPromptSubmit hook. Touches the lock and exits without running
    # any cue check. The lock path is resolved via the registry so a
    # rename of the `cache` segment in harness/paths.toml propagates
    # to this hook automatically.
    #
    # Critical: the scheduled `claude -p "/autoevo-nightly"` invocation is
    # itself a UserPromptSubmit event — without the env-var guard below,
    # the hook would touch the lock right before /autoevo-nightly's
    # pre-flight gate checks the lock, causing the bot to abort every
    # night with "session-active lock fresh." The launchd plist exports
    # ATELIER_SKIP_LOCK_TOUCH=1 in its ProgramArguments shell wrapper
    # so the scheduled run bypasses the refresh.
    if args.touch_lock:
        if os.environ.get("ATELIER_SKIP_LOCK_TOUCH"):
            if args.verbose:
                print("# debug: lock touch skipped (ATELIER_SKIP_LOCK_TOUCH set)", file=sys.stderr)
            return 0
        try:
            cache_dir = tier("cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "atelier-session-lock").touch()
        except Exception as exc:
            if args.verbose:
                print(f"# debug: session-lock touch failed: {exc!r}", file=sys.stderr)
        return 0

    snoozes = _load_snoozes(ov)

    # Session-active lock: when invoked as a SessionStart hook, touch a
    # marker file so the 5am `/autoevo-nightly` bot can detect a recent
    # session and bail out per `protocols/autoevo.md` § Pre-flight gates.
    # SessionStart catches the start of a fresh session; the dedicated
    # `--touch-lock` path (above) handles the UserPromptSubmit per-prompt
    # refresh so long-running sessions stay protected past the 6h bail window.
    #
    # Skip-flag honor: same logic as --touch-lock. The launchd-invoked
    # `claude -p "/autoevo-nightly"` triggers SessionStart as well as
    # UserPromptSubmit; without this guard, the bot would touch the lock
    # right before its own pre-flight gate reads it, aborting every run.
    if args.hook:
        if os.environ.get("ATELIER_SKIP_LOCK_TOUCH"):
            if args.verbose:
                print("# debug: SessionStart lock touch skipped (ATELIER_SKIP_LOCK_TOUCH set)", file=sys.stderr)
        else:
            try:
                cache_dir = tier("cache")
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / "atelier-session-lock").touch()
            except Exception as exc:
                if args.verbose:
                    print(f"# debug: session-lock touch failed: {exc!r}", file=sys.stderr)

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
        if cue and _is_snoozed(snoozes, name, today):
            if args.verbose:
                print(f"# debug: {name} SNOOZED until {snoozes[name]}", file=sys.stderr)
            continue
        if args.verbose:
            tag = "FIRED" if cue else "silent"
            print(f"# debug: {name} {tag}: {reason}", file=sys.stderr)
        if cue:
            fired.append(cue)

    if args.hook:
        # Claude Code SessionStart hook protocol. Injects fired cues + recent
        # run recaps as a system reminder on the next model call.
        recaps = _recap_local_runs(ov, today, verbose=args.verbose)
        if not fired and not recaps:
            return 0
        sections: list[str] = []
        if fired:
            lines = [f"- {c.message} (route: `{c.command_path}`)" for c in fired]
            sections.append("Session-start cues (atelier):\n" + "\n".join(lines))
        if recaps:
            recap_lines = [f"- {r}" for r in recaps]
            sections.append("Recent local routine runs:\n" + "\n".join(recap_lines))
        context = "\n".join(sections)
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
