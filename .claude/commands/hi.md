---
description: Universal entry point — intent router for reflection, planning, action, reading, learning, capture, and more.
---
# Reflect

Your reflection system. Uses a two-step decision tree with `AskUserQuestion` for native scroll-and-select UI.

## Routing & Dispatch

### Intent Routing (when user types `/hi <context>`)

Routing rules live in `harness/intents.toml` (canonical). Read that file at session start to know the dispatch shape per intent: trigger phrases (`patterns`), the dispatch sub-mode (`mode`), the agents the orchestrator is expected to dispatch (`agents`), and the matching priority. Do not duplicate those fields here; when adding or changing a routing rule, edit the TOML and let this file reference it.

Each intent's `mode` field maps to a procedure: see the "Sub-mode procedures" table below for the canonical mapping (inline section names + paths to external command files). Detect the intent from `<context>`, skip the Step 1 menu, and route directly into the matching sub-mode. If no `<context>` is given, fall through to the Session-Start Cue Check, then the Step 1 menu.

### Always-on Routing Announcement

Before any agent dispatch under `/hi`, surface a one-line acknowledgment of the routing decision so the user can see the matched intent and the dispatch chain. This is in-band observability: the orchestrator never opts in or out, the user never has to ask. Drift becomes visible because the user reads the announcement on every turn.

Format: `Routing as intents.<name> → <comma-separated agent list>` (use the `agents` list from the matched row in `harness/intents.toml`).

Fallback case. The `intents.reflection` row (priority 0, empty `patterns`) is the catch-all. When it matches because nothing more specific did, mark that explicitly so a "deliberate reflection" (the user said "let's reflect") and a "nothing matched, falling back to reflection" look different to the user:

`No specific intent matched; routing as default reflection → <agents from intents.reflection>`

(Read the agent list from `intents.reflection.agents` — never hardcode it here, or this file drifts from the canonical TOML.)

When the user explicitly invoked the reflection mode (e.g., chose Reflect from the Step 1 menu, or said "let's reflect"), use the standard form (`Routing as intents.reflection → ...`) instead. The fallback marker is only for the implicit-match case.

Semantic match. Some intents fire on user input shape rather than literal phrase — e.g., a date-prefixed factual narrative without analytical question (`/hi 5/4 早上去了 X, 中午吃了 Y`) routes to `intents.capture` even though no literal pattern matches. When the orchestrator decides on shape rather than phrase, the announcement still uses the matched intent name; the matching logic is documented in the per-intent sub-mode section below.

### Clarify before dispatching when intent is uncertain

Substring matching can produce **low-confidence wins** that the user did not intend. Before dispatching, judge confidence:

| Signal | Confidence | Action |
|---|---|---|
| A high-priority intent matched on a multi-word phrase that clearly states the goal (`"weekly review"`, `"should I take this job"`, `"记一下"`) | high | Dispatch immediately. Routing announcement is enough. |
| The only match comes from a short generic substring inside a longer message whose primary intent looks different (e.g., `"should I"` matched in `"I'm not sure what I should I focus on this week"` falsely routing to decision) | low | Use `AskUserQuestion` with the matched intent + one or two plausible alternates + Reflect as the safe default. Phrase: `"I read this as <intent.A>. Did you mean <intent.A>, <intent.B>, or just reflect?"` |
| Fallback case (no patterns matched, defaulted to `intents.reflection`) AND the input has an action signal (URL, imperative verb, date-prefixed narrative) | low | Use `AskUserQuestion` with the most likely 2-3 intents the input hints at, plus Reflect. |
| Fallback case AND the input reads as open prose / question / mood | high | Dispatch reflection. That's the design. |

The bar: **never silently route to a sub-mode that opens a file, calls an external API, or starts a multi-agent chain when the user's input could have meant something materially different.** Capture (single Scribe write), Read (Reader+Researcher), Decision (Researcher+Thinker), and the big chains (Sync, Weekly, Review, Promote) all qualify. Reflection-as-default does NOT qualify; it's the safe degradation.

The Codex orchestrator runs the same logic via `python3 scripts/atelier.py intent "<text>" --json` and inspects `fallback` + the heuristic above. The Codex side then offers the choice in-line as a numbered prompt rather than `AskUserQuestion` (Codex has no equivalent UI).

### Miss Logging

Dual-path. The mechanically-derivable branches are captured out-of-band by a `UserPromptSubmit` hook (`scripts/atelier.py intent-hook`, registered in `.claude/settings.json`); the orchestrator covers only the LLM-judgment branch in-band.

- **Fallback** (no patterns matched) — **HOOK-LOGGED**. The hook runs the same matcher at prompt-submit time. Do NOT call `intent-log` from the orchestrator.
- **Ambiguous** (2+ non-fallback intents tied at top priority) — **HOOK-LOGGED**. Same hook path; ambiguity candidates captured deterministically.
- **Low-confidence** (heuristic-table judgment row 2 of "Clarify before dispatching") — **ORCHESTRATOR LOGS in-band** after the routing announcement, since the hook cannot run the LLM judgment that flags this case.

The happy path (high-confidence single winner with no clarification) is not logged by either path.

For the low-confidence case only:

```
Bash: uv run scripts/atelier.py intent-log \
  --input "<raw /hi text the user typed>" \
  --match-kind low_confidence \
  --runtime claude-code \
  --initial-name <intent name> \
  --initial-priority <int> \
  --initial-pattern "<matched pattern>" \
  [--clarified-to <intent name user picked>] \
  [--final-dispatch <intent name or label like 'engineering-task'>] \
  [--notes "<one-liner about why this was a miss>"]
```

The script is best-effort and always returns exit code 0 — malformed args and filesystem errors each degrade silently. The orchestrator can dispatch the Bash call without `|| true` or other exit-code guards.

Codex parity: Codex has no `UserPromptSubmit` hook surface. The Codex orchestrator runs the FULL `intent-log` Bash call for all three match-kinds (`--runtime codex`), accepting the in-band token cost as the cost of having no hook layer cross-runtime.

The log file lands at `$OV/_meta/intent_misses/YYYY-MM-DD.jsonl` (one line per miss, regardless of producer). Hook-produced rows carry `"logged_by": "user_prompt_submit_hook"` for attribution; orchestrator-produced rows omit that field. Batch review: `uv run scripts/atelier.py intent-misses [--since YYYY-MM-DD] [--match-kind <kind>]`. Recurrence threshold = `INTENT_MISS_DISTINCT_DAYS_THRESHOLD` (currently 3) distinct file-dates. Full workflow + dual-path producer contract: `protocols/intent-coverage.md`.

### Parallel-dispatch guarantee

When `harness/intents.toml` declares `parallel = true` for a matched intent, the orchestrator MUST dispatch the listed agents in a **single message containing multiple tool calls** (Claude Code) or **a single batch invocation** (Codex). Sequential dispatch (one agent per turn) for a parallel-marked intent is a latency regression and a contract violation.

This applies to:
- `intents.reading` (Reader + Researcher)
- `intents.talk` (Reader + Researcher)
- `intents.decision` (Researcher + Thinker)
- `intents.introspect` (Reviewer + Challenger quality-gate pair)
- `intents.reflection` (Researcher + Challenger + Scout + Synthesizer + Reviewer)
- Any inline parallel step within a sub-mode procedure (e.g., Multi-Lens Read's Phase 1 fan-out; Deep Dive's 4-agent fan-out; Reviewer + Challenger write-back gate)

The same rule applies inside sub-mode procedures whenever the procedure says "in parallel" or "fire X and Y in parallel": single message, multiple Agent / Bash tool calls, never one-per-turn. The `parallel` field in `intents.toml` is informational at the registry level; this section makes the contract operational at dispatch time.

Verification: in the routing announcement, suffix `(parallel)` after the agent list when the matched intent's `parallel = true`. The user can see the contract and call it out if the orchestrator turns into sequential dispatches anyway.

### Sub-mode procedures

<!-- sub-mode-procedures-map -->

Once an intent matches, the orchestrator's next step is to read and follow the procedure mapped from the intent's `mode` field. This is what makes the dual path real (`/<name>` direct OR `/hi <natural-language>` both execute the same procedure). For modes pointing at an external procedure file, read the file and execute it as if the user had typed `/<name>` directly. The procedure file's prose is the authority on dispatch shape, write-back, and any approval gates. For inline modes, follow the named section below in this file.

| `mode` | Procedure |
|---|---|
| `capture-fast-path` | inline: "Capture Fast Path" section below |
| `read-and-discuss` | `.claude/commands/read.md` |
| `transcript-read` | `.claude/commands/read.md` (Reader auto-preprocesses transcripts) |
| `meeting-process` | inline: "If Act" / "Process Meeting" section below |
| `daily-reflection` | `.claude/commands/daily-reflection.md` |
| `decay-scan` | dispatch the Forgetter agent (`.claude/agents/forgetter.md`) with the user-specified `scope_path`; default scope is `<paths.wip>/`. Forgetter returns findings inline via the `---begin-result---` / `---end-result---` envelope; the orchestrator persists them to `<paths.agent_findings>/decay-<RUN_TS>-<scope-slug>.md`. |
| `weekly-review` | `.claude/commands/weekly.md` |
| `goal-review` | `.claude/commands/review.md` |
| `decision-journal` | `.claude/commands/decision.md` |
| `energy-audit` | `.claude/commands/energy-audit.md` |
| `open-exploration` | `.claude/commands/explore.md` |
| `curate-inbox` | `.claude/commands/curate.md` |
| `promote` | `.claude/commands/promote.md` |
| `lint` | `.claude/commands/lint.md` (script-driven; no agent dispatch) |
| `introspect` | `.claude/commands/introspect.md` |
| `sync` | `.claude/commands/sync.md` |

<!-- /sub-mode-procedures-map -->

The `<!-- sub-mode-procedures-map -->` markers above bound the table that `scripts/harness_lint.py` uses to verify every intent's `mode` is reachable. Adding a new intent row to `harness/intents.toml` requires adding the corresponding row inside these markers; the lint flags drift.

### Capture Fast Path

When the user's input is "just write this down" (factual, no reflection sought), do not run the coaching flow. Dispatch the Scribe directly with the right operation:

| Content shape | Scribe operation | Target tier |
|---|---|---|
| Date-stamped narrative for a day | `daily_note` | under `<paths.daily_notes>/` |
| Restaurant + score / 必点 | `dining_row` | the user's dining-log file under `<paths.travel>/` |
| New person mentioned with bio context, file does not exist | `people_stub` | under `<paths.people>/` |
| Action item with deadline / area | `gtd_entry` (`add`) | most recently modified file under `<paths.gtd>/` |
| Anything else "just save this" | `generic` | orchestrator picks an appropriate path under `<paths.wip>/` |

Resolve the exact target file path at dispatch time by inspecting the target directory for the user's existing structural conventions (subdirectory tree, filename style). Do not assume a layout; the user owns these conventions and they are private to `$OV/`. Confirm with the user once when multiple plausible targets exist; if the path is obvious from a quick directory listing, just dispatch.

### Effective Date

Resolve inline before dispatch:
- `<effective-date>`: if local time < 03:00, use yesterday's calendar date; else today.

Daily notes are user-authored under `<paths.daily_notes>/`. The system reads them as-is; nothing pulls or mirrors them from anywhere else. The exact subdirectory layout and filename pattern are user-private; resolve them at runtime by listing the target directory. **Exception (cloud-native mode):** when the user provides daily-note-style narrative through `/hi <args>` or chat, the orchestrator dispatches the `scribe` agent to record it verbatim before writing the reflection file. See "Pre-Output: Raw Capture" below. The user is still the author; the scribe is the typewriter.

### Session-Start Cues

Session-start cues (overdue weekly, pending zettelm captures, etc.) are surfaced out-of-band by a `SessionStart` hook in `.claude/settings.json` that runs `uv run scripts/cues.py --hook`. The script is silent in the common case and injects a system-reminder containing fired cues only when one or more thresholds trip. The orchestrator therefore does NOT need to run the cue check inline on every `/hi`; if a cue is relevant, it's already in context by the time the user types anything.

If a cue is present in the session reminder, the orchestrator MAY offer to route the user into the matching command (`/weekly`, `/sync`, etc.) before falling through to the Step 1 menu. Otherwise, proceed straight to Step 1.

Active cues: `weekly` (overdue weekly review), `zettelm` (mobile-capture inbox pending digest), `recurring` (overdue recurring obligations; escalates to hard when worst-overdue > 30d), `aggregate_freshness` (self-declared aggregates lagging their subject SOT), `routine_outputs` (unreviewed cron-routine reports in `$OV/_meta/routine_watch.toml`-declared dirs), `routine_policy` (routine entries without `drive_write_enforced` / `needs_drive_write_update` ack — `protocols/remote-routines.md` policy gate). The aggregate-freshness, routine_outputs, and routine_policy cues are informational, not routing prompts. Per-key snooze: `uv run scripts/cues.py snooze <key> [--days N]` writes to `$OV/_meta/cue_snooze.json` to suppress until expiry.

To **add** a new cue, append a `check_<name>(ov, today)` function in `scripts/cues.py` and register it in `CHECKS`. No edit to this file is needed; the hook picks it up automatically next session. To **debug** locally: `uv run scripts/cues.py --verbose` (per-check reasoning on stderr) or `uv run scripts/cues.py --hook` (dry-run the hook output).

## Step 1: Choose Mode

Use `AskUserQuestion` with these options:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Reflect** | Think about what's happening — daily reflection, weekly review, or explore connections |
| 2 | **Plan** | Make decisions and set direction — goal review, decision journal, or energy audit |
| 3 | **Act** | Do something with your notes — compact, deep dive, or triage |
| 4 | **Read** | Read and discuss an article or note with structured reading lenses |
| 5 | **Learn** | Get recommendations or introspect to rebuild your self-model |

## Step 2: Choose Action

Based on Step 1, use a second `AskUserQuestion`:

### If Reflect:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Daily Reflection** | Reflect on today's notes and recent thinking |
| 2 | **Weekly Review** | Energy + attention audit for the past week |
| 3 | **Explore** | Surface forgotten connections and open threads |

- **Daily Reflection:** Read and follow `.claude/commands/daily-reflection.md`
- **Weekly Review:** Read and follow `.claude/commands/weekly.md`
- **Explore:** Read and follow `.claude/commands/explore.md`

### If Plan:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Goal Review** | Check progress on goals — progressing, neglected, or shifted |
| 2 | **Decision Journal** | Structured decision-making with framework cross-validation |
| 3 | **Energy Audit** | Four-dimension energy assessment (physical, mental, emotional, social) |
| 4 | **PRM Audit** | Audit relationship health and support system robustness (monthly) |

- **Goal Review:** Read and follow `.claude/commands/review.md`
- **Decision Journal:** Read and follow `.claude/commands/decision.md`
- **Energy Audit:** Read and follow `.claude/commands/energy-audit.md`
- **PRM Audit:** Read and follow `.claude/commands/prm.md`

### If Act:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Curate Inbox** | Goal-aware triage of your Readwise inbox — score, route, and tag |
| 2 | **Compact Notes** | Find and merge redundant or overlapping notes |
| 3 | **Deep Dive** | Full briefing on a topic — notes + web research + resources + framework, 4 agents in parallel |
| 4 | **Note Triage** | Scan for compaction candidates across your notes |
| 5 | **Process Meeting** | Turn a work meeting transcript into structured notes with action items |

- **Curate Inbox:** Read and follow `.claude/commands/curate.md`
- **Compact Notes:** Ask the user what topic or notes to compact. Then run the snapshot-first flow (see `protocols/orchestrator.md` → Note Operations → Compact Notes):
  1. **Researcher** identifies related notes in `$OV/` (semantic.py primary, Grep for structural).
  2. **Orchestrator snapshots each source** to `<paths.cache>/compact-<slug>-<n>.md` (local `cp`).
  3. Dispatch to **Curator** with `snapshot_paths: [...]` in the handoff. The Curator works exclusively from the snapshot files, runs the Content Preservation Checklist, and returns a draft.
  4. User approves each output note individually; the orchestrator writes the file after approval.
- **Deep Dive:** Ask the user for a topic, then dispatch **four agents in parallel**:
  1. **Researcher** — search all notes related to this topic (what you've already thought/written)
  2. **Scout** — search the web for recent articles, research, and developments on this topic
  3. **Librarian** — find curated resources to deepen understanding (books, papers, courses)
  4. **Thinker** — select and apply a relevant framework from `frameworks/`
  Once all four return, **Synthesizer** combines their outputs into a unified briefing: your existing thinking, external intelligence, curated resources, and a framework lens — all in one view. Present in Chinese for reading-intensive output. Before write-back (if any), dispatch **Reviewer** + **Challenger** in parallel to verify citation accuracy and Scout-sourced claims.
- **Note Triage:** Ask the user for 3-5 topic areas (or pull from `profile/identity.md` themes). Dispatch the **Researcher** to search each topic area in parallel. For each area, identify notes with overlapping content. Present a prioritized compaction plan: which notes to merge, estimated redundancy, and impact. The user picks which to compact, then dispatch to **Curator** for each approved merge.
- **Process Meeting:** Ask the user to paste or provide the meeting transcript. Dispatch the **Meeting** agent (Executive mode — action items, decisions, next steps). Present the structured output. Before saving, dispatch **Challenger** to check: are action items attributed correctly? Are any decisions ambiguous or missing owners? Ask the user if they want to save as a local note — if yes, dispatch **Curator** to draft it and the orchestrator writes after approval. For research talks or presentations, use Read instead — Reader handles transcript format with real analytical lenses.

### If Read:

Read and follow `.claude/commands/read.md` — it owns the Read menu and the three flows (Read & Discuss, Focused Read, Multi-Lens Read), plus the Reader/Scholar selection, Readwise prefetch, and source-backup sub-procedures.

### If Learn:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Recommend Resources** | Get reading/learning recommendations on a topic (Chinese summaries) |
| 2 | **Introspect** | Rebuild your self-model — discover identity, taste, curiosity, and directions from your notes |

- **Recommend Resources:** Dispatch to the **Librarian** agent. Ask the user what topic they want recommendations for. The Librarian searches existing notes for context, then recommends books, papers, articles, and other resources with Chinese summaries.
- **Introspect:** Read and follow `.claude/commands/introspect.md`
