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
drive_write_enforced = true          # see policy below
```

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

## Policy: all routines persist to $OV

Every cron-style remote routine MUST write its canonical output to a declared path inside $OV. Cloud-only delivery (Gmail draft, email, ephemeral session output) is allowed as a **secondary** channel for notification, but the SOT lives in $OV.

Rationale:
- **Discoverability**: cues.py can surface unreviewed routine outputs at session start. Gmail-only outputs are invisible to the harness.
- **Persistence**: routine sessions are ephemeral. Without Drive write, weekly state is lost across runs.
- **Auditability**: a per-run markdown file is grep-able, linkable from notes, and survives the routine being deleted.

Routine prompts implement this by calling Google Drive MCP `create_file` with a path under `$OV/<declared output_dir>/`. If the create_file fails, the prompt MUST print the full content as routine return value so the user can paste manually.

## How the cue fires

```
SessionStart hook → uv run scripts/cues.py --hook
                       → check_routine_outputs:
                           reads $OV/_meta/routine_watch.toml
                           for each routine entry:
                               glob output_dir for file_pattern
                               compare latest filename vs acks[output_dir]
                               if newer: collect for cue message
                       → emit cue line if any new files found
```

When the cue fires, the user sees one line at session start:

```
Remote cron routines 有新 output 待 review: <label1> (<filename1>); <label2> (...). 读完后 update `_meta/routine_acks.json` ({<output_dir>: <latest filename>}) 来 mute.
```

## Privacy boundary

Atelier-side code MUST NOT:
- Name a specific routine (`name` field is in $OV).
- Hardcode an `output_dir` value.
- Reference a domain-specific filename pattern.
- Embed trigger IDs.

The single touchpoint is `check_routine_outputs` reading `$OV/_meta/routine_watch.toml`. If you need to add a new routine, append to that file under `$OV/_meta/`, not to atelier source.

## Adding a new routine

1. **Create the remote routine** via `/schedule` skill or the routines UI on claude.ai. Attach the MCP connections it needs (typically Gmail + Google-Drive).
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

If a routine was created before the 2026-05-22 policy and only delivers via email/Gmail draft:

1. Edit its prompt (via `/schedule update` or the UI) to add a Drive write step before the email step.
2. Add `Google-Drive` to its MCP connections.
3. Add an entry in `$OV/_meta/routine_watch.toml` with `drive_write_enforced = true`.

The policy is "all NEW routines and all UPDATED routines"; existing routines should be migrated when convenient, not all at once.

## Debugging

| Symptom | Likely cause |
|---|---|
| Cue never fires | `$OV/_meta/routine_watch.toml` missing or unparseable. Run `uv run scripts/cues.py --verbose` and look at the `routine_outputs` debug line. |
| Cue fires for already-read files | `routine_acks.json` not updated. Update `{<output_dir>: <latest filename>}`. |
| Cue fires for routine that doesn't exist anymore | Remove the `[[routine]]` block from `routine_watch.toml`. |
| Routine fires but no file appears in $OV | Drive MCP `create_file` may have failed silently. Check routine session log on claude.ai/code/routines/`<trigger_id>`. The prompt should print full content as fallback. |
| Filename sort gives wrong "latest" | Use `YYYY-MM-DD-...` filename prefix so lexicographic sort matches chronological sort. |

## Related

- `local-first-architecture.md` — vault tier model + aggregation/detail boundary (this doc extends it with the routine layer)
- `repo-conventions.md` — atelier vs $OV separation
- `harness-assumptions.md` — track when the routine layer assumes specific MCP behaviors
- CLAUDE.md § Tooling layout — script placement rules
