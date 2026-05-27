Remote Routines
===============

How scheduled remote agents (cron-style) integrate with the atelier without leaking private content into the public harness.

## Layered architecture

Three layers, each owning a different concern.

| Layer | What lives here | Provides | Boundary |
|---|---|---|---|
| **atelier** (public, portable git repo) | `scripts/cues.py`, `.claude/commands/`, `.claude/agents/`, `protocols/` | mechanism (generic, vault-agnostic) | knows the **shape** of routine outputs (config schema + ack schema), never the **content** |
| **$OV/_meta/** (user-private vault metadata) | `routine_watch.toml`, `routine_acks.json` | policy + state (which routines, what paths, what's been read) | private; never committed to atelier |
| **claude.ai cloud** (Anthropic-managed) | routine definitions (cron expression + prompt + MCP connections) | execution (the cron itself runs here, writes back to $OV via Drive MCP) | lifecycle managed via `/schedule` skill or routines UI |

The atelier never names a specific routine, output path, or domain (career, finance, health). All of that is in `$OV/_meta/routine_watch.toml`. The atelier just declares the contract.

## Contract: routine_watch.toml

User-private config at `$OV/_meta/routine_watch.toml`. Each routine declares where it writes:

```toml
[[routine]]
name = "<routine-name>"              # human label
trigger_id = "trig_<...>"            # claude.ai routine ID
cron = "<cron expr UTC + local note>"
output_dir = "<relative path under $OV>"
file_pattern = "<glob>"              # e.g. "*.md", "*-weekly.md"
label = "<short human label>"
drive_write_enforced = true          # see Policy below — set true when Drive write is wired
# needs_drive_write_update = true    # alternative: ack migration debt (legacy routine, Drive write not yet wired). Migration debt; clear within a sprint by adding Drive write to the prompt and flipping to drive_write_enforced = true.
```

Exactly one of `drive_write_enforced` or `needs_drive_write_update` MUST be `true` for the policy cue to stay silent. The two flags are mutually exclusive in intent: the first declares compliance, the second declares migration debt being tracked.

`scripts/cues.py check_routine_outputs` reads this generically. It does NOT know what any specific routine does; it only walks the declared `output_dir` looking for files matching `file_pattern` that are newer (by filename sort) than the corresponding ack in `routine_acks.json`.

## Contract: routine_acks.json

User-private state at `$OV/_meta/routine_acks.json`:

```json
{
  "<output_dir>": "<latest_acked_filename>",
  ...
}
```

After the user reads a routine output, they update the corresponding entry. The cue stops firing once `latest_acked_filename >= latest_file_in_dir.name`.

**First run.** The file need not exist initially. `scripts/cues.py` defaults a missing `routine_acks.json` to `{}` and treats every routine as unacked (the cue will list every existing output until the user reads them). When the user acks their first routine, create `$OV/_meta/routine_acks.json` with `{"<output_dir>": "<filename>"}`. Subsequent acks add or update entries.

## Policy: all routines persist to $OV

Every cron-style remote routine MUST write its canonical output to a declared path inside $OV. Cloud-only delivery (Gmail draft, email, ephemeral session output) is allowed as a **secondary** channel for notification, but the SOT lives in $OV.

Rationale:
- **Discoverability**: cues.py can surface unreviewed routine outputs at session start. Gmail-only outputs are invisible to the harness.
- **Persistence**: routine sessions are ephemeral. Without Drive write, weekly state is lost across runs.
- **Auditability**: a per-run markdown file is grep-able, linkable from notes, and survives the routine being deleted.

Routine prompts implement this by calling Google Drive MCP `create_file` with a path under `$OV/<declared output_dir>/`. If the create_file fails, the prompt MUST print the full content as routine return value so the user can paste manually.

**Conflict-resolution rule (multi-channel routines).** When a routine uses more than one output channel (any combination of Drive, email, Calendar, or future MCP backends), the Drive file is the canonical output. Every secondary channel MUST point at the Drive file (`see $OV/<path>/<file>.md`) and cap its own content at 5 lines of summary. The user reads one source of truth, not parallel summaries.

**Enforcement.** Three cues in `scripts/cues.py`:

1. `check_routine_policy`: fires a soft cue listing routines that declare neither `drive_write_enforced = true` nor `needs_drive_write_update = true`. Surfaces non-compliance at session start.
2. `check_routine_staleness`: fires a hard cue when a routine's latest output file is older than its expected cadence + tolerance. Catches total outages: the routine fires on claude.ai but produces no file in `$OV`. Cadence is estimated from the `cron` field in the TOML entry. Tolerance = `max(2, cadence_days)`.
3. `check_routine_hitrate`: fires a soft cue when a routine's output count over a lookback window falls below 70% of expected. Catches intermittent failures (e.g., daily routine succeeding every other day). Only evaluates routines with cadence <= 7 days; longer-cadence routines rely on staleness detection. Lookback capped to oldest file date so new routines aren't penalized.

## Halt conditions

Routines execute on the cloud side; the harness only observes their outputs (the Drive-written file). The atelier cannot see a routine looping, OOMing, or burning quota mid-run. The harness-side cues above (`check_routine_staleness`, `check_routine_hitrate`) detect total outages and degraded hit rates *after the fact*; they cannot stop a misbehaving in-progress routine. The only effective halt signal the atelier can emit for a remote routine is a **per-routine prompt contract** the routine itself must respect.

### Per-routine prompt contract

The harness cannot enforce these declarations; they are policy, not mechanism. A routine that violates them will not be detected by the atelier. The contract is honored by the routine author at prompt-write time, not by the harness at runtime.

Every routine prompt MUST declare the following at the top of its instructions, before any data fetch or analysis step:

1. **Single-pass scope.** One pass over the source data per cron fire. No retry loop on partial fetches. If a source is unavailable, write a Drive output that names the missing input and exit; do not retry.

2. **Cost ceiling declared in plain text.** Expected token budget for one fire (typically 5K to 50K depending on scope). The plain-text declaration lets a reviewer detect overrun in the cloud session log.

3. **External-blocker behavior.** If a required MCP connection is unreachable (Drive write fails, Gmail unreachable for a source fetch), the prompt:
   - Records the failure in the routine's session output.
   - Skips the Drive write rather than retry.
   - Does NOT silently degrade to an empty Drive file. An empty file would tombstone the missed run for `check_routine_staleness` as if it succeeded.

4. **Idempotent re-fire.** If the same routine fires twice in the same UTC day (rare cron skew, manual rerun), the second fire detects the existing Drive file and either appends or refuses. It does not overwrite a successful prior output.

## Local execution layer

Some routines need local-only tools (semantic.py, git, lint.py) that remote cloud agents cannot access. These run locally via `launchd` + `claude -p`, coordinated across multiple machines via DynamoDB.

### Architecture

| Concern | Mechanism |
|---|---|
| Scheduler | macOS `launchd` plist per routine, fires at configured time |
| Wrapper | `scripts/routine_runner.sh` handles env, stagger, lock, claim, execution |
| Cross-machine lock | DynamoDB conditional put (`attribute_not_exists(pk)`) via `scripts/routine_lock.py` |
| Local audit trail | `$OV/_meta/routine_runs/<routine>/<cycle_id>.toml` claim files |
| Missed-run detection | `check_local_routine_missed` cue in `scripts/cues.py` |

### routine_watch.toml: local routine entry

```toml
[[routine]]
name = "<routine-name>"
execution = "local"                     # "remote" (default) | "local"
cron = "<cron expr (local time)>"
output_dir = "<relative path under $OV>"
file_pattern = "<glob>"
label = "<short human label>"
# No trigger_id (local routines have no claude.ai trigger)
# No drive_write_enforced (local routines write to $OV directly)
```

### Coordination config

Optional `[coordination]` table in `routine_watch.toml`:

```toml
[coordination]
backend = "dynamodb"    # "dynamodb" | "none" (default)
```

When `backend = "none"` (or absent), `routine_lock.py` is a no-op: all lock operations return success. Single-machine setups work without AWS.

Override per-session: `export ATELIER_COORDINATION=none` (or `dynamodb`).

### DynamoDB table

Table `atelier-routine-locks`, provisioned 1 WCU / 1 RCU (always-free tier):

| Field | Type | Purpose |
|---|---|---|
| `pk` (hash key) | String | `<routine>#<cycle_id>` |
| `machine` | String | hostname of claiming machine |
| `status` | String | `running` / `completed` / `failed` |
| `ttl` | Number | Unix epoch; DynamoDB TTL auto-deletes stale locks |

Setup: `aws-vault exec atelier -- python3 scripts/routine_lock.py setup-table`

### Claim files

Written by `routine_runner.sh` to `$OV/_meta/routine_runs/<routine>/<cycle_id>.toml`:

```toml
routine = "autoevo-nightly"
cycle_id = "2026-05-26"
machine = "atelier-mbp"
claimed_at = "2026-05-26T05:01:23-07:00"
status = "completed"
completed_at = "2026-05-26T05:08:45-07:00"
duration_seconds = 445
```

These are gitignored; they sync across machines via Drive's filesystem sync. The cue system reads them locally.

### Execution flow

```
launchd fires at scheduled time
  -> routine_runner.sh <routine> <command>
     -> sleep hash(hostname) % 120 (stagger)
     -> routine_lock.py acquire (DynamoDB conditional put)
        -> if held: exit 0 (skip)
        -> if error: warn + proceed (single-machine fallback)
     -> write claim file (status=running)
     -> claude -p "/<command>"
     -> update claim file (status=completed|failed)
     -> routine_lock.py release
```

### Failure modes

| Scenario | Behavior |
|---|---|
| Two machines race | DynamoDB atomic lock: exactly one wins. Loser skips. |
| No machine awake | `check_local_routine_missed` cue fires at next session start |
| Machine crashes mid-run | DynamoDB TTL (1h default) auto-expires the lock; claim file stays `status=running` |
| AWS credentials missing | `routine_lock.py` returns success (no-op); single-machine mode |
| DynamoDB unreachable | Warning logged; routine proceeds (availability over coordination) |

### Vendor lock-in

This section presumes Anthropic Routines remains available. Routines launched in 2026 with no published SLA. If Routines becomes unavailable or substantially changes its contract, every declared routine stops firing and the user must migrate to an alternative scheduler (macOS launchd, GitHub Actions, etc.). The atelier's only commitment is the per-routine prompt contract above; the underlying cron is the user's choice.

A second vendor risk: **routine prompts live on claude.ai, not in this repository.** A prompt edited via the routines UI is not version-controlled by atelier and Anthropic does not currently expose an export API for routine prompt history. If the claude.ai routines surface changes its storage or auth model, the prompts can become unreadable without manual re-fetch.

Mitigation: after each `/schedule update <routine>`, copy the current prompt text into a private archive note (e.g. `<paths.personal>/_routine_prompts/<name>.md` or equivalent under the user's structural conventions). The atelier does not run a periodic prompt-archive cue; the user maintains the cadence manually (a calendar reminder is sufficient; no harness mechanism is required).

## How the cues fire

```
SessionStart hook → uv run scripts/cues.py --hook
                       → check_routine_outputs:
                           reads $OV/_meta/routine_watch.toml
                           for each routine entry:
                               glob output_dir for file_pattern
                               compare latest filename vs acks[output_dir]
                               if newer: collect for cue message
                       → emit cue line if any new files found
                       → check_routine_staleness:
                           for each routine entry:
                               estimate cadence from cron field
                               extract date from latest output filename
                               if age > cadence + tolerance: flag as stale
                       → emit hard cue if any routines stale/missing output
                       → check_routine_hitrate:
                           for each routine with cadence <= 7d:
                               count files in lookback window (capped to oldest file date)
                               compare actual vs expected (lookback / cadence)
                               if rate < 70%: flag as degraded
                       → emit soft cue if any routines degraded
```

When `check_routine_outputs` fires:

```
Remote cron routines 有新 output 待 review: <label1> (<filename1>); <label2> (...). 读完后 update `_meta/routine_acks.json` ({<output_dir>: <latest filename>}) 来 mute.
```

When `check_routine_staleness` fires:

```
N routine(s) with missing/stale output: <label> (<reason>). Check routine session logs on claude.ai for silent Drive-write failures or missing MCP connections.
```

## Privacy boundary

Atelier-side code MUST NOT:
- Name a specific routine (`name` field is in $OV).
- Hardcode an `output_dir` value.
- Reference a domain-specific filename pattern.
- Embed trigger IDs.

The single touchpoint is `check_routine_outputs` reading `$OV/_meta/routine_watch.toml`. If you need to add a new routine, append to that file under `$OV/_meta/`, not to atelier source.

## Adding a new routine

1. **Create the remote routine** via `/schedule` skill or the routines UI on claude.ai.
   - Under "MCP connections": attach Google-Drive (required for `$OV` persistence) and any other MCPs the routine needs (e.g., Gmail for email delivery).
   - After saving, re-open the routine and confirm `mcp_connections` is non-empty. A routine with empty MCP connections will fire on schedule but cannot write to `$OV`, and `check_routine_staleness` will eventually flag the missing output.
2. **Routine prompt must include** a Drive-write step: `create_file` under `$OV/<your output_dir>/<filename pattern>.md` as the canonical archive. Other channels (email, draft) are optional notification.
3. **Append to `$OV/_meta/routine_watch.toml`**:
   ```toml
   [[routine]]
   name = "<short-name>"
   trigger_id = "trig_<...>"
   cron = "<expression UTC + local note>"
   output_dir = "<relative path under $OV>"
   file_pattern = "<glob>"
   label = "<human label>"
   drive_write_enforced = true
   ```
4. **Test the cue** locally: `uv run scripts/cues.py --verbose` should show the routine in the debug line. After first cron fire, the cue will fire on next `/hi`.

## Migration: legacy email-only routines

If a routine pre-dates this policy (only delivers via email/Gmail draft, no Drive write step):

1. Edit its prompt (via `/schedule update` or the UI) to add a Drive write step before the email step.
2. Add `Google-Drive` to its MCP connections.
3. Add an entry in `$OV/_meta/routine_watch.toml` with `drive_write_enforced = true`.

The policy is "all NEW routines and all UPDATED routines"; existing routines should be migrated when convenient, not all at once.

## Retiring a routine

When a routine is no longer wanted:

1. Disable or delete the cron in claude.ai (`/schedule` or the routines UI).
2. Remove its `[[routine]]` block from `$OV/_meta/routine_watch.toml`. The cue stops firing.
3. Decide what to do with the existing output files in `$OV/<output_dir>/`:
   - Keep as historical archive: no action.
   - Move to `<paths.archive>/routines/<name>/`: preserves provenance, removes from active surface.
   - Delete: only if the outputs are truly disposable.
4. Drop the matching entry from `$OV/_meta/routine_acks.json` if present.

The output directory itself is left in place (rmdir manually if empty and unwanted).

## Debugging

| Symptom | Likely cause |
|---|---|
| Cue never fires | `$OV/_meta/routine_watch.toml` missing or unparseable. Run `uv run scripts/cues.py --verbose` and look at the `routine_outputs` debug line. |
| Cue fires for already-read files | `routine_acks.json` not updated. Update `{<output_dir>: <latest filename>}`. |
| Cue fires for routine that doesn't exist anymore | Remove the `[[routine]]` block from `routine_watch.toml`. |
| Routine fires but no file appears in $OV | `check_routine_staleness` cue fires after `cadence + tolerance` days. Root cause: Drive MCP `create_file` failed silently (missing MCP connection, auth expired, or target dir not creatable). Check routine session log on claude.ai. The prompt should print full content as fallback. |
| Filename sort gives wrong "latest" | Use `YYYY-MM-DD-...` filename prefix so lexicographic sort matches chronological sort. |

## Related

- `local-first-architecture.md` — vault tier model + aggregation/detail boundary (this doc extends it with the routine layer)
- `repo-conventions.md` — atelier vs $OV separation
- `harness-assumptions.md` — track when the routine layer assumes specific MCP behaviors
- CLAUDE.md § Tooling layout — script placement rules
