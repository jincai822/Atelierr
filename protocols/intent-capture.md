## Capture intent

Outcome: record user-authored factual material without turning it into a
reflection or silently choosing an ambiguous destination.

Select one Scribe operation from the content shape:

| Content shape | Operation | Target |
|---|---|---|
| Date-stamped narrative | `daily_note` | `<paths.daily_notes>/` |
| Trip-associated restaurant + score / 必点 | delegate to `/dine` Intent C | meal log and confirmed trip note |
| Other restaurant + score / 必点 | `dining_row` | configured meal-history tracker |
| New person with bio context | `people_stub` | `<paths.people>/` |
| Action item with deadline or area | `gtd_entry` (`add`) | active GTD file |
| Other factual capture | `generic` | suitable path under `<paths.wip>/` |

Resolve the exact target from the user's existing private layout. Ask once
when multiple destinations are plausible. Never infer trip association from
city, address, or date alone; the user must name the trip or establish the
current trip explicitly.

Use the local effective date: before 03:00, use the previous calendar day.
Daily notes remain user-authored. The Scribe `daily_note` operation is the only
system path allowed to record the user's verbatim daily-note content.

Dispatch Scribe with the raw user text and resolved operation fields. Do not
pre-summarize or add facts.
