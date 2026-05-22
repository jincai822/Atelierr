# Backend Taxonomy

Single registry of every external system the atelier depends on, classified against the SOT principle, with per-backend contract (role, write-direction, authority, failure mode, identifier-leakage rule).

This doc exists because the architectural commitment in `local-first-architecture.md` ("`$OV/` is canonical SOT") is conditional, not absolute. Some backends violate it deliberately (Readwise as L1 SOT); others are transit pipes that occasionally hold provisional state (claude.ai routine sessions before Drive MCP write confirms). Without a single map, each protocol invents its own framing and the seams rot silently.

Companion docs: `local-first-architecture.md` (vault tier model), `remote-routines.md` (cron routine contract), `drive-zk-ingestion.md` (raw landing), `repo-conventions.md` (vault git conventions).

## Backend Roles

Five role categories. Every external system the atelier touches belongs to exactly one.

| Role | Definition | Example |
|---|---|---|
| **substrate** | Hosts `$OV` itself. SOT lives here on disk. | Google Drive (sync), iCloud, local-only folder |
| **inbound-transit** | Carries content from outside into `$OV`. Authority is one-way (cloud → `$OV`). | `~/Downloads/`, Drive top-level domain folders, claude.ai routine + Drive MCP write |
| **outbound-transit** | Carries content from `$OV` outward. Authority is one-way (`$OV` → cloud). | GitHub private remote (push), Gmail MCP draft (notification), Calendar MCP event creation |
| **derived-cache** | Local cache built from `$OV`. Rebuildable; never the SOT. | `~/.cache/atelier/lance/` (LanceDB embedding index) |
| **sot-exception** | Holds canonical state the system does NOT mirror to `$OV`. Declared violation of the SOT principle. | Readwise inbox (L1 cloud-only) |

## Backend Registry

| Backend | Role | Write-direction | Authority over $OV | Failure mode (when unavailable) | Identifier-leakage rule |
|---|---|---|---|---|---|
| **Google Drive (substrate)** | substrate | n/a (hosts) | none (it IS $OV) | $OV reads/writes fail at filesystem layer; Level 3 in `error-handling.md` | Drive account name MUST NOT appear in committed atelier files |
| **Google Drive (raw landing)** | inbound-transit | cloud → $OV | none until ingested | Ingestion blocked; raw files accumulate in landing zone | Generic public aliases (e.g., `Medical/` → `health/`) may live in `drive-zk-ingestion.md`. Taxonomy-specific personal mappings (employer codes, project names) MUST live in `$OV/_meta/drive_aliases.toml`. Migration of the current public aliases to `$OV/_meta/` is deferred (no privacy benefit; tracked in Open Items). |
| **Google Drive MCP (routine write)** | inbound-transit | claude.ai routine → $OV | provisional until file appears on disk | Routine output trapped in claude.ai session log at `claude.ai/code/routines/<trigger_id>`; recover via session log read + manual paste | Routine `output_dir` and `name` MUST live in `$OV/_meta/routine_watch.toml`, not in committed atelier code |
| **claude.ai cron routines** | execution + inbound-transit (paired with Drive MCP write) | claude.ai → Drive MCP → $OV | ephemeral; SOT lives in $OV after Drive write confirms | Cron stops firing; cue layer cannot detect (no expected output to check against). Heartbeat check is deferred work. | `trigger_id` MUST live in `$OV/_meta/routine_watch.toml`; routine prompts on claude.ai may reference $OV paths but MUST NOT embed private slugs |
| **Readwise inbox** | sot-exception | cloud-only (no local mirror) | none (it is NOT $OV) | `/curate` blocked; all other commands unaffected (per `error-handling.md` Level 2) | Account credentials live in CLI config, not in atelier; document IDs accessed via CLI are ephemeral |
| **GitHub private remote ($OV)** | outbound-transit | $OV → cloud (user-driven push) | none (cloud copy is backup; $OV on disk is SOT) | Push fails; local $OV unaffected; remote falls behind. No cue surfaces this. | Remote URL lives in `$OV/.git/config`, not in atelier |
| **Gmail MCP (notification)** | outbound-transit | $OV / routine → email | none | Email not delivered; canonical output still in $OV per routine policy | Subject/body authored by routine prompt. No formal identifier policy yet; see Open Items → "Cloud-prompt hygiene". |
| **Google Calendar MCP** | outbound-transit | session/routine → calendar event | none | Event not created; user reschedules manually | Event content. No formal identifier policy yet; see Open Items → "Cloud-prompt hygiene". |
| **Semantic index (LanceDB)** | derived-cache | $OV → cache (built by `semantic.py index`) | none (rebuildable) | Semantic queries return junk silently; falls back to grep on Researcher's discretion | Index lives at `~/.cache/atelier/lance/`; never committed |
| **Shadow logs (LLM call provenance)** | derived-cache | machine→$OV mirror (skeleton only) | none (rebuildable from machine-local source-of-record) | Missing entries silently skip; report flags stale cost catalog + char_approx rows + missing-leg witnesses + witness-absent groups | `$OV/_meta/shadow_logs/<date>.jsonl` carries correlation skeleton (~500B/entry: model, leg, usage, latency, verdict, response preview SHA-256 + first 200 chars). Full prompts/responses stay at `~/.cache/atelier/llm_calls/<date>.jsonl`. Recommend adding `_meta/shadow_logs/` to `$OV/.gitignore` if vault is pushed to a remote (skeleton fields still carry signal). |

## SOT Scope

The "`$OV/` is SOT" rule applies to **L2-L4** content that the system has durably written and confirmed present on disk. The carve-outs:

- **Readwise inbox is split-SOT for unpromoted L1 captures.** Rationale: L1 is ephemeral by tier definition; loss of unpromoted highlights is equivalent to loss of browser history. Accepted trade-off. Revisit if Readwise deprecates or user moves >20 hrs/yr through it.
- **In-flight routine outputs hold provisional SOT in the claude.ai session log** until `scripts/cues.py check_routine_outputs` confirms the file on disk. Confirmation latency window: next session start (when the cue runs). If the Drive MCP write fails silently, the session log is the only recovery surface; the routine prompt MUST print the full output as fallback per `remote-routines.md` § Policy.
- **Substrate-layer corruption** (Google Drive sync conflict, filesystem damage) breaks the SOT guarantee at a lower layer than the atelier addresses. Recovery is filesystem-level (Drive web UI version history, Time Machine, etc.).

## Per-Backend Contract Requirements

Every backend added to this registry MUST declare:

1. **Role** from the table above. If none fits, propose a new category before adding.
2. **Write-direction** (one of: cloud→$OV, $OV→cloud, bidirectional, n/a).
3. **Authority over $OV** when this backend's state conflicts with $OV state.
4. **Failure mode** when the backend is unavailable: which command/workflow degrades, what cue (if any) surfaces it, what manual recovery exists.
5. **Identifier-leakage rule**: which strings (account names, paths, IDs) MUST stay out of committed atelier files and where they live instead (typically `$OV/_meta/<backend>.toml`).
6. **Deprecation escape hatch**: one-command rollback or migration recipe when the backend deprecates. Existing backends without one are tracked under Open Items → "Deprecation playbooks".

**Enforcement.** This registry is currently a reference, not a machine-enforced contract. `/system-review`'s Reviewer pass applies antipattern scans (#3 Happy-path-only, #4 Implicit contracts) to new rows, which catches missing fields by inspection but not by schema. The honest framing: a contributor adding a backend uses this list as a checklist; nothing fails the build if a row is malformed. If row-shape drift becomes a real problem (rule of two: at least two malformed rows land before someone notices), promote to a `scripts/backend_lint.py` schema validator. Until then, "MUST declare" reads as "should declare on pain of being flagged in next review."

## Policy: $OV/_meta/ as the generic backend-config home

The pattern established by `$OV/_meta/routine_watch.toml` (remote-routines.md) is the canonical home for per-backend user-private config. Any new backend with user-private state MUST declare a file under `$OV/_meta/<backend>.toml` (or document why it doesn't). This keeps atelier-side code generic (reads the TOML, knows the schema, not the data) and concentrates user-private state in one observable directory.

Current `$OV/_meta/` inhabitants:
- `routine_watch.toml`, `routine_acks.json` — claude.ai cron routine state
- `shadow_logs/<date>.jsonl` — correlation-skeleton mirror of LLM call provenance for multi-leg shadow dispatches (see `protocols/shadow-log.md`)
- (planned migration) `drive_aliases.toml` — Drive top-level → $OV domain mapping (currently hardcoded in `drive-zk-ingestion.md` lines 73-76)
- (planned) `mcp_grants.toml` — enumeration of MCPs authorized and what private data each may send

## Open Items

These are SHOULD-FIX or DEFER from peer-review rounds. Tracked here as the keystone; resolve in subsequent rounds.

- **Bootstrap runbook** missing for fresh-clone OSS users (no `BOOTSTRAP.md`). Until written, the "OSS-portable" framing in `runtime-adapters.md` is aspirational. Tracked as the next material gap.
- **Heartbeat checks** (liveness): no backend has a periodic verification that it still satisfies its declared behavior. Drive MCP could change `create_file` semantics; routine cron could shift; Readwise CLI could change auth flow. A `scripts/backend_heartbeat.py` (deferred) would write a no-op probe per backend on a known cadence and fire a hard cue if any probe fails. Separate concern from deprecation playbooks below.
- **Deprecation playbooks** (migration): no registry row currently declares a deprecation escape hatch (per-backend contract field 6). When a backend deprecates, the recovery is ad-hoc. Add one per row when the work is worth doing; until then, treat the field as aspirational.
- **MUST + soft-cue alignment**: `remote-routines.md` declares "every routine MUST persist to $OV" but enforces with a soft cue. The `needs_drive_write_update` flag is migration debt acknowledgment, not a permanent escape hatch. Hardening path: replace the bool with an expiry date (`needs_drive_write_update = "YYYY-MM-DD"`) and have `/lint` fail after the date. Implementation deferred; schema documentation tightened.
- **Cloud-prompt hygiene**: routine prompts and MCP-authorized backends accept private content from $OV and send it to provider clouds (Anthropic, Google). No policy governs what identifier classes are permitted to cross. Add `protocols/cloud-prompt-hygiene.md` (deferred). Until then, the registry rows for Gmail MCP and Calendar MCP carry no formal identifier policy.

**Resolved in earlier rounds (kept here for trace):**
- profile cleavage: documented as gitignored per-user config in `CLAUDE.md` § Profile; intentionally excluded from `harness/paths.toml`.
- Vault git push policy: documented in `repo-conventions.md` § $OV git push policy.
- Conflict resolution between overlapping backends: promoted to `remote-routines.md` § Policy (Drive file canonical; email/calendar bodies are pointers capped at 5 lines).
- Drive aliases (generic public ones): kept in `drive-zk-ingestion.md` as transitional default; taxonomy-private mappings still go to `$OV/_meta/drive_aliases.toml`.

## Cross-References

- `local-first-architecture.md` — vault tier model. SOT scope above amends its § Source of Truth.
- `remote-routines.md` — claude.ai routine layer. This doc generalizes the pattern.
- `drive-zk-ingestion.md` — raw landing zone. Drive aliases migration noted above.
- `repo-conventions.md` — vault markdown conventions. Push policy documented in § $OV git push policy.
- `harness-assumptions.md` — cloud backend assumptions registered in § Cloud Backend Assumptions.
- `runtime-adapters.md` — workflow/role/capability/runtime separation. Backend taxonomy adds a fifth axis (external state holders).
