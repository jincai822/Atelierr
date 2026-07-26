# Intent Coverage

Feedback loop for the shared hi intent router, invoked as `/hi` in Claude Code
and `$hi` in Codex. It captures inputs the router was uncertain about so we can
extend `harness/intents.toml` based on real usage instead of guesswork.

## Live route projection

For every explicit contextual `/hi`, `/reflect`, `$hi`, or `$reflect`
invocation, the shared `UserPromptSubmit` hook runs the deterministic matcher
once and injects its result as:

```text
ATELIER_INTENT_ROUTE {"schema":1,"source":"harness/intents.toml",...}
```

The packet projects only fields needed by the live command: `name`, `mode`,
`agents`, `profile_reads`, `priority`, `matched_pattern`, `parallel`,
`fallback`, and `ambiguous`. An ambiguous result also carries
`tied_candidates` with the same route fields. It contains registry data only:
never the raw user input, session ID, transcript path, or resolved filesystem
paths.

`harness/intents.toml` remains canonical. The packet is computed from the live
file at prompt-submit time and is bounded by
`INTENT_ROUTE_MAX_CONTEXT_BYTES` (currently 1 KiB). If matching fails or the
packet would exceed that bound, the hook emits nothing and the command reads
the full registry. Shape-based and low-confidence overrides remain model
judgment; `.claude/commands/hi.md` defines when they require the full file.

This reuses work the hook already performs. The normal route adds no model or
tool call and replaces an unconditional full-registry read with at most 1 KiB
of projected context on each contextual invocation.

## What gets logged

A miss is any Claude `/hi <text>` or Codex `$hi <text>` invocation where the
orchestrator could not classify the intent with high confidence. Three kinds:

| Kind | Trigger |
|---|---|
| `fallback` | No `patterns` matched; `intents.reflection` (priority 0, empty patterns) won by default. |
| `ambiguous` | 2+ non-fallback intents tied at the top priority; orchestrator used `AskUserQuestion` to disambiguate. |
| `low_confidence` | A short generic substring matched inside a longer message whose primary intent looked different (see the heuristic table in `.claude/commands/hi.md` § Clarify before dispatching). Orchestrator used `AskUserQuestion` to confirm. |

The happy path (high-confidence single winner) is NOT logged. The log is a coverage feedback channel, not a session history.

## Where the log lives

`$OV/_meta/intent_misses/YYYY-MM-DD.jsonl` — one JSON object per line, one line per miss. Falls back to `~/.cache/atelier/intent_misses/` when `$OV` is unset (test / fresh-checkout environments).

The filename's date is `date.today()` at write time (calendar-naive local). This deliberately diverges from the `<effective-date>` late-sleep rule (`CLAUDE.md`: before 03:00 local, "today" = previous calendar day) used by daily notes and reflections. Rationale: the miss log is a fire-time audit trail, not a user-authored work surface; aligning bucket timestamps with wall-clock simplifies sort, dedup, and `--since` aggregation. The orchestrator MUST NOT pass an effective-date timestamp here.

Schema:

```json
{
  "timestamp": "2026-05-22T00:02:38",
  "runtime": "claude-code",
  "raw_input": "improve the repo, so when I use /hi ...",
  "match_kind": "fallback",
  "initial_match": {
    "name": "reflection",
    "priority": 0,
    "matched_pattern": "<fallback: no patterns matched>"
  },
  "ambiguity_candidates": [{"name": "...", "priority": 35, "matched_pattern": "..."}],
  "ambiguity_candidates_raw": "(raw string when --candidates failed JSON parse; mutually exclusive with the parsed array above)",
  "clarified_to": "reading",
  "final_dispatch": "reading",
  "notes": "user typed URL inline; clarification needed because 'should I' also matched"
}
```

Field key for `ambiguity_candidates[].matched_pattern` deliberately matches the key produced by `scripts/intent_coverage.py intent --json` (the matcher returns `matched_pattern`, never `pattern`); the orchestrator passes candidates straight through without renaming. `ambiguity_candidates`, `ambiguity_candidates_raw`, `clarified_to`, `final_dispatch`, and `notes` are all optional. `initial_match.name/priority/matched_pattern` may be null when the orchestrator didn't have a clean initial match to attribute (rare; usually present even for fallback). `priority` is dropped to null silently when `--initial-priority` fails to parse as int.

## Producer side: route plus dual-path logging

Two producers feed the same JSONL, partitioned by `match_kind`:

| Producer | Surface | Captures | Token cost into orchestrator |
|---|---|---|---|
| `intent-hook` | `UserPromptSubmit` hook (`.claude/settings.json` and `.codex/hooks.json`) | Compact route for every contextual invocation; logs `fallback` and `ambiguous` via `match_intents()` | At most 1 KiB of high-signal route context; no extra model or tool call |
| `intent-log` | In-band `Bash:` call by the orchestrator | `low_confidence` — heuristic LLM judgment over message shape (see `.claude/commands/hi.md` § Clarify before dispatching) | ~200-300 tokens per call (Bash command + result) |

The hook projects every deterministic route and captures the bulk of misses
(fallback is purely "no patterns matched"; ambiguous is purely "2+ tied at
top priority" — both deterministic). The orchestrator's in-band call covers
only the LLM-judged `low_confidence` branch plus any clarification-time
enrichment that the hook cannot observe.

Codex uses its native `UserPromptSubmit` hook for explicit `$hi` and `$reflect`
skill invocations. Both runtimes therefore receive the same route packet and
hook-log `fallback` and `ambiguous`; only `low_confidence` remains an in-band
orchestrator call. Hook-produced rows carry
`"logged_by": "user_prompt_submit_hook"`; orchestrator-produced rows omit that
field, which preserves producer attribution in the report.

The shape of the in-band call is documented in `.claude/commands/hi.md` § Miss Logging. The shared hook entry is wired with the runtime label appropriate to each edge:

```
{"type": "command",
 "command": "uv run scripts/intent_coverage.py intent-hook --runtime claude-code",
 "timeout": 5}

{"type": "command",
 "command": "uv run scripts/intent_coverage.py intent-hook --runtime codex",
 "timeout": 5}
```

The first lives in `.claude/settings.json`; the second lives in `.codex/hooks.json`.

Route injection and miss-log writes fail independently. The write is best-effort — `scripts/intent_coverage.py intent-log` always returns exit code 0 (orchestrator Bash calls can ignore the exit code with confidence):

- An empty `--input`, a malformed `--candidates` JSON, or a non-int `--initial-priority` each degrade silently (warning to stderr) without aborting the call. Malformed candidates are preserved verbatim under `ambiguity_candidates_raw` so a later batch-review can still see the orchestrator's intent.
- The script silently no-ops on OSError so a slow or unmounted `$OV` never blocks a live hi invocation.
- One `f.write(json.dumps(...) + "\n")` per entry. On POSIX with `O_APPEND`, this is atomic up to `PIPE_BUF` (4 KiB on Linux, 512 B on macOS for some filesystems). The expected entry size (≤1 KB) keeps every write safely under that ceiling. Larger payloads may interleave; the consumer's per-line `json.JSONDecodeError` handler drops any malformed lines so a torn write degrades to lost data, never corrupted reports.
- No locking; concurrent writers from parallel Codex sessions are rare in practice and an occasional interleave doesn't matter for batch aggregation.

## Consumer side — batch review

```
uv run scripts/intent_coverage.py intent-misses [--since YYYY-MM-DD] [--match-kind <kind>] [--runtime claude-code|codex] [--top N] [--json]
```

`--since` filters at **file-date** granularity (the log file's `YYYY-MM-DD` stem), not at event-timestamp granularity. A TZ-skewed event near midnight is grouped with its file's date, so `--since 2026-05-15` reads the whole `2026-05-15.jsonl` file even when only late-evening events are wanted.

Output:

- Counts by `match_kind` (how often we fall back vs disambiguate).
- Top distinct phrases (lowercased, ≤200 chars) with count, distinct days, and which kinds they hit.
- Coverage signal: phrases recurring across at least the distinct-days threshold defined in `scripts/intent_coverage.py` as `INTENT_MISS_DISTINCT_DAYS_THRESHOLD` (currently 3) are flagged as candidate triggers — strong enough that user is hitting the gap repeatedly, not just once.
- A note line `(N event(s) had empty raw_input — counted in by-kind totals, omitted from the phrase table)` appears when applicable; `kind_counts` and `phrase_stats` deliberately disagree by N in that case so a fire-time logging glitch is visible in the audit, not silently dropped.

Run cadence: opportunistic. No automated cue yet; check during `/system-review` or before sprints of harness work. This is a deliberate v1 scope choice — the cue template would mirror `check_routine_outputs` (directory existence + recent entry count + ack-state in `$OV/_meta/`), and adding it is tracked as the natural v2 step. Without the cue, the user discovers the backlog by remembering to run `intent-misses`; this is acceptable while traffic is low.

## Acting on the report

Three outcomes per recurring phrase:

1. **Add a pattern to an existing intent.** The user's phrasing is a synonym for an intent that already exists, just not enumerated. Edit the matching `patterns = [...]` list in `harness/intents.toml`. Cheap, low-risk; the substring matcher handles it immediately.
2. **Add a new intent.** The phrase describes a workflow `hi` doesn't model yet (e.g., a recurring engineering directive pattern). Decide whether Claude `/hi` and Codex `$hi` are the right surfaces, or whether the workflow belongs as a direct registered command with both native edges, or as a semantic Claude entry hint in `.claude/skills/`.
3. **Confirm it stays a miss.** Some misses are correct. Claude `/hi` and Codex `$hi` are reflection entry points, and an engineering directive typed into either may genuinely be out of scope. Reflection-as-fallback is the safe degradation. Document the call by leaving the entry in the log; the recurring count itself is the audit trail.

Do NOT add patterns that would steal from another intent's substring space. The TOML header has cautionary notes (`"read"` would snag `"curate readwise"`, etc.); the lesson generalizes — prefer phrase-shaped patterns (`"improve the repo"`) over single-token patterns (`"improve"`).

## Lifecycle

The log accumulates indefinitely. There is no rotation / compaction policy yet — the file sizes are small (each entry ≤1KB; 100 misses per day = <100KB/day) and the JSONL format reads incrementally. If the log ever grows large enough to matter, move yearly logs into a `archive/` subdirectory; the `intent-misses` report only globs `*.jsonl` at the top level and will ignore them.

## Related

- `harness/intents.toml` — canonical intent registry; misses feed pattern additions here.
- `.claude/commands/hi.md` § Clarify before dispatching — heuristic for when to flag as `low_confidence`.
- `.claude/commands/hi.md` § Miss Logging — exact Bash shape orchestrator runs.
- `scripts/intent_coverage.py` — `intent-log` and `intent-misses` subcommands; source of truth for the path and the distinct-days threshold.
- `protocols/shadow-log.md` — sibling JSONL-append + report system. Different write target (canonical to `$OV/` here, redacted mirror skeleton there) but a useful precedent if this log ever grows multi-leg / verdict-aggregation needs.
