---
description: Read-only perks and trip status dashboard over local trackers.
---
# Perks & Trip Status

Read-only dashboard. Surfaces open decisions, upcoming deadlines, and data gaps from existing trackers in `<paths.finance>/` and `<paths.travel>/`. Use on revisit to avoid re-reading multiple files.

## Pre-step: aggregate freshness check

Run BEFORE loading any tracker. Detail files under each aggregate's declared `subjects:` dir are the source of truth; the aggregates themselves are hand-mirrored views and can lag. Quoting a stale aggregate as authoritative is the bug this guard prevents.

```bash
uv run scripts/aggregate_freshness.py --discover --json
```

Discovery walks `$OV` for files that opt in via YAML frontmatter (`subjects:` + `freshness: required`); convention documented in `protocols/local-first-architecture.md` § Aggregation vs. Detail. New aggregates surface automatically once they add the marker — no edit to this file needed.

If any aggregate (across any group) reports `"stale": true`, prepend a **Divergence Warning** section to the output:
- Name each stale aggregate and the lag in days.
- Name the newest subject file (the likely cause).
- Tell the user: aggregate values may be out-of-date; cross-check the subject file before acting on any item from the stale aggregate.

If `discovered == 0`, no group has any `subject_count`, or every aggregate in every group reports `"note": ...` (no Last-updated line), skip the warning silently — the guard has no signal to act on, but the user should not see noise.

## Load

Discover and read markdown trackers under:
- `<paths.finance>/*.md`
- `<paths.travel>/*.md`

Today: `date +%Y-%m-%d`. If a folder is empty, skip it.

## Output

Sections in this order. Omit any section with zero items.

**Divergence Warning** (only if pre-step flagged stale aggregates)

**Urgent (< 14 days)**
- Any dated item within 14 days: renewal, expiration, conditional trigger resolution, booking deadline
- Each line: item + days-to-deadline + tracker recommendation if any

**This quarter**
- Period-bound credits unclaimed before quarter-end
- Yearly uses remaining with no allocation
- Skip monthly auto credits unless an anomaly is visible in logs

**Pending decisions**
For each open decision across trackers:
- Subject
- Recommendation from tracker (else `TBD`)
- One-line reason

**Data gaps**
Fields still marked `TBD` or `☐` that likely have a user-side answer.

## Close

End with one line: pick the highest-leverage urgent item as the next action, or invite the user to supply a data-gap answer.

## Rules

- Read-only. Do not write any file (the freshness pre-step writes nothing).
- Do not propose new plans or optimizations; use a separate command for that.
- Do not re-derive tracker logic; surface what is there.
- When a Divergence Warning fires, items sourced from the stale aggregate(s) MUST carry an inline `[stale: cross-check <subject-file>]` marker. Do not silently quote them.
- Keep output under ~150 lines. If a section exceeds 5 items, show top 3 and add a pointer.
- Match user's language convention per `CLAUDE.md`.
