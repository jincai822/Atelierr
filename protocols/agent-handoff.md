# Agent Handoff Protocol

Defines structured contracts for agent-to-agent communication. Every handoff includes a typed envelope so the receiving agent can parse without guessing.

## Envelope Format

Every agent output that feeds another agent MUST include a metadata block:

```
---handoff---
from: <agent name>
to: <agent name>
type: research-brief | reader-brief | scout-brief | synthesis | review-check | system-review-request | challenge-set | perspective | recommendation | note-operation | meeting-notes | evolution-report | decay-report
confidence: high | medium | low
completion_status: complete | partial | aborted
remaining_work: <required when partial|aborted; comma-separated list of tasks not attempted>
gaps: <comma-separated list of what's missing>
context_tokens: <approximate token count of payload>
---end-handoff---
```

`completion_status: complete` means every task in the dispatch prompt was attempted to a returnable result. If any task was skipped, deferred, or hit a degraded fallback, status MUST be `partial` and `remaining_work` MUST enumerate the items. `aborted` means the agent stopped before finishing the first task (e.g., on `drift_check: N` from a midpoint checkpoint). `gaps` describes what was searched for but not found; `remaining_work` describes what was not attempted: they are distinct and both may apply.

**Backwards compatibility.** Agents that omit `completion_status` and `remaining_work` are interpreted as `completion_status: complete` with empty `remaining_work`. This lets the contract roll out without simultaneously rewriting every agent definition. Agents updated after this contract MUST emit the fields explicitly; the orchestrator treats absent fields as `complete` only as a transition aid. Similarly, the midpoint-checkpoint and Runtime-Conflict-Surfacing protocols below are obligations on the orchestrator's interpretation: when an agent provides the relevant signal, the orchestrator honors it; agents that haven't been updated to emit the signal simply skip the path. Neither protocol blocks a fresh dispatch.

The envelope above is universal — every contract below carries every envelope field. The per-contract `Required fields` lists below are **type-specific additions on top of the envelope**, not a replacement for it. Aborted briefs (`completion_status: aborted`) are never passed unchanged to the Synthesizer: the orchestrator surfaces the checkpoint or remaining-work payload to the user and decides whether to redispatch or accept the partial result.

## Contract: Researcher → Synthesizer

**Type:** `research-brief`

Required fields:
- `query`: What was searched for
- `sources`: Array of `{title, id, edited, relevance_sentence}`
- `excerpts`: Array of `{source_title, quote, language}`
- `gaps`: What was searched for but not found
- `search_strategy`: Which queries were run (text/vector, languages)
- `confidence`: How complete the coverage feels

The Synthesizer MUST NOT re-search. If gaps are critical, escalate to orchestrator.

## Contract: Reader → Synthesizer

**Type:** `reader-brief`

Required fields:
- `lens`: Which reading lens was applied (Critical | Structural | Practical | Dialectical)
- `source`: Article/note title being analyzed
- `findings`: Array of `{finding, supporting_quote, commentary}`
- `cross_signals`: Array of observations for other lenses to investigate
- `verdict`: One-sentence judgment through this lens
- `confidence`: How well the lens fit this content

When the Synthesizer receives multiple `reader-brief` handoffs (from parallel Reader instances), it should:
1. Look for convergence across lenses (multiple lenses reaching the same conclusion)
2. Surface divergence (lenses disagreeing — this is the most interesting output)
3. Combine with Researcher/Scout/Thinker outputs into a unified reading report

## Contract: Synthesizer → Reviewer

**Type:** `synthesis`

Required fields:
- `output_type`: reflection | review | exploration | reading-report
- `claims`: Array of `{claim, source_title, source_quote}`
- `unsourced_claims`: Array of claims made without direct source (should be empty)
- `goals_referenced`: Which goal categories were covered
- `goals_missing`: Which goal categories were not addressed
- `language_distribution`: % English vs Chinese content

## Contract: Reviewer → Orchestrator

**Type:** `review-check`

Required fields (envelope shape only; numeric thresholds are canonical in `.claude/agents/reviewer.md` → Scoring, do not duplicate here):

- `mode`: `"session"` | `"system"` (selects which dimension set + verdict enum applies)
- `overall`: `{score: 0-10, verdict: <see mode>, summary: ""}`
  - `mode: "session"` verdicts: `"APPROVED" | "APPROVED_WITH_NOTES" | "NEEDS_REVISION" | "REJECTED"`
  - `mode: "system"` verdicts: `"APPROVED" | "NEEDS_REVISION" | "REJECTED"` (no notes-only verdict; the artifact-presence floor in reviewer.md routes single-dim flaws into the fix path instead)

Dimension fields by mode:

- **Session mode** (4 dims): `citations`, `goal_coverage`, `honesty`, `staleness`. Each `{score: 0-10, issues: []}` (or `missing_categories` / `flags` / `warnings` respectively).
- **System mode** (4 dims, replacing the session set): `contract_integrity`, `wiring_correctness`, `bug_absence`, `claim_fidelity`. Each `{score: 0-10, issues: []}`.

Score-to-verdict mapping and the artifact-presence floor are defined in `.claude/agents/reviewer.md` § Scoring. Privacy-gate precedence and revision-round policy live in `protocols/quality-gates.md` § Gate 3.

## Contract: Challenger → User

**Type:** `challenge-set`

Required fields:
- `grounding`: What the user seems to be thinking/feeling (evidence-based)
- `affirming`: Question that validates a strength
- `probing`: Question about an assumption
- `challenging`: The uncomfortable question
- `the_one_question`: Single most important question
- `framework_used`: Which framework informed the challenge (if any)
- `emotional_register`: detected mood (excited | neutral | anxious | uncertain | overwhelmed)

## Contract: Thinker → Orchestrator

**Type:** `perspective`

Required fields:
- `reframe`: The situation stripped of the user's framing
- `frameworks_applied`: Array of `{name, insight, applicability: 0-10}`
- `cross_validation`: Where frameworks agree/disagree
- `contrarian_take`: The perspective against the grain
- `external_sources`: Any web research cited

## Contract: Scout → Orchestrator

**Type:** `scout-brief`

Required fields:
- `topic`: What was researched
- `direction`: Which search direction was assigned (Mainstream, Contrarian, Adjacent, etc.)
- `findings`: Array of `{finding, source_url, date, relevance}`
- `contrarian_signal`: At least one perspective challenging the user's view
- `knowledge_gap`: What the user's notes don't cover that the web suggests is important
- `confidence`: How reliable the sources are

## Contract: Librarian → Orchestrator

**Type:** `recommendation`

Required fields:
- `topic`: What recommendations are for
- `resources`: Array of `{title, author, type, core_insight, relevance_to_user}`
- `already_read`: Resources the user already has notes on (excluded from recommendations)
- `contrarian_pick`: At least one recommendation that challenges current thinking

## Contract: Orchestrator → Curator (Compact/Merge Dispatch)

When dispatching the Curator for compact or merge operations, the orchestrator MUST take a **snapshot of each source note at dispatch time** under `<paths.cache>/<operation>-<slug>.md`. The snapshot protects against mid-session mutation: the user may edit a note in their editor while the Curator is drafting. The Curator then works exclusively from those snapshots.

To produce each snapshot: copy the local source file under `$OV/` to `<paths.cache>/<operation>-<slug>.md`. Use the relative path slug (e.g., `compact-daily-notes-2026-04-05.md`) so the origin is obvious.

Dispatch prompt MUST include:
- `snapshot_paths`: array of `<paths.cache>/<operation>-<slug>.md` paths the orchestrator just created

The Curator works exclusively from `snapshot_paths` — it never re-reads the originals. This preserves the "content recoverable even if the user deletes mid-session" property that makes the cache step load-bearing.

**Auto-apply mode (autoevo nightly only).** When the orchestrator dispatches Curator from `/autoevo-nightly`, three additional fields are required:

- `mode`: `auto-apply` (vs. the default `normal` mode used by all human-in-loop flows)
- `band`: `redundant-high` | `low-signal-high` — which trust band fired; no other values trigger auto-apply
- `evidence`: the Forgetter row dict that triggered the dispatch, including `confidence: high`; Curator's scope guards (curator.md § Auto-apply hard refusal conditions) verify this before returning `auto_apply_safe: true`

Snapshot creation remains mandatory in auto-apply mode — Curator refuses with `auto_apply_safe: false` and `refusal_reason: "missing or empty snapshot"` if `snapshot_paths` is absent.

## Contract: Orchestrator → Challenger (Probe Contradiction)

Used by `/autoevo-nightly` step 3 to filter rhetorical contradictions from genuine ones before queueing wiki rewrites for human review. Read-only by contract; Challenger does not write any file.

Dispatch prompt MUST include:
- `task`: `probe-contradiction`
- `wiki_claim`: full text of the L4 wiki claim Forgetter flagged
- `contradicting_peer`: relative path under `$OV/` of the L2 note containing the apparent contradiction
- `contradiction_signal`: the exact phrase from the peer that Forgetter flagged as correction-language

Response envelope:
- `from`: `challenger`
- `to`: `orchestrator`
- `type`: `contradiction-probe`
- `verdict`: `genuine` (the peer really overturns the wiki claim) | `rhetorical` (the "actually" / "wrong" / "事实上" is rhetorical or refers to a different referent)
- `rationale`: one short sentence; the orchestrator includes this in the pending-queue entry for `genuine` verdicts and in the audit log § "Contradicted rhetorical dismissals" for `rhetorical` verdicts

## Contract: Curator → Orchestrator

**Type:** `note-operation`

Required fields:
- `operation`: compact | merge | create | replace | wiki-entry | archive
- `mode`: `normal` (default; user-approval gate applies) | `auto-apply` (only valid for compact/merge/archive ops dispatched by `/autoevo-nightly`)
- `band`: required iff `mode = auto-apply`; one of `redundant-high` | `low-signal-high`. Omitted otherwise.
- `auto_apply_safe`: required iff `mode = auto-apply`; `true` when Curator's scope guards pass and the content-preservation checklist succeeded, `false` otherwise.
- `refusal_reason`: required iff `auto_apply_safe = false`; one short sentence explaining which guard tripped. Orchestrator surfaces this to the pending queue.
- `target_path`: (required for `wiki-entry` and `archive`, optional otherwise) Local file path under `$OV/` where the orchestrator will write the draft after user approval. Curator cannot Write — it only proposes the path and body.
- `notes_affected`: Array of note titles involved
- `snapshot_paths`: (required for compact/merge/archive in any mode) Array of `<paths.cache>/<operation>-<slug>.md` snapshot file paths used as source. Orchestrator verifies these exist before accepting the proposal.
- `media_inventory`: (required for compact/merge, omit for create/replace/archive) `{images: count, tables: count, structured_blocks: count, embeds: count}` — counts from source notes. The orchestrator verifies these counts match the output.
- `media_output_count`: (required for compact/merge) `{images: count, tables: count, structured_blocks: count, embeds: count}` — counts in the proposed output. Must match `media_inventory` or differences must be listed in `changes_summary`.
- `external_content_flagged`: (required for compact/merge, omit for create/replace/archive) boolean — true if any source notes contain content from external sources (forum quotes, others' experiences). If true, those sections must be clearly attributed in `proposed_content`.
- `proposed_content`: The new/merged content (for user approval). For `operation: archive`, this is the snapshot content being archived (Curator does not modify it).
- `estimated_size`: Approximate byte size of `proposed_content`. If >15KB, must include a split plan.
- `content_integrity`: (required for compact/merge, omit for create/replace/archive) `{verbatim_preserved: boolean, structures_preserved: boolean, images_preserved: boolean, checklist_passed: boolean}` — self-assessment that the Content Preservation Checklist was run
- `rationale`: Why this operation was recommended

## Contract: Forgetter → Orchestrator

**Type:** `decay-report`

Forgetter is read-only (no `Write` tool); it returns the categorized findings inline. The orchestrator persists the report to disk at `<paths.agent_findings>/decay-<RUN_TS>-<scope-slug>.md` using the inline content verbatim. This single-mode envelope eliminates the prior "filesystem-output is the contract" assumption, which was broken at runtime by Claude Code's subagent system-prompt directive blocking report-shaped file writes.

Required fields:
- `from`: `forgetter`
- `to`: `orchestrator`
- `type`: `decay-report`
- `mode`: `full` (sweep ran to completion) | `partial` (sweep early-terminated on `max_candidates`, `time_budget_s`, or self-stop at 80% of maxTurns)
- `summary`: `{redundant: N, time_stale: N, contradicted: N, low_signal: N}` — counts per category
- `findings_inline`: full categorized findings keyed by category (`redundant`, `time_stale`, `contradicted`, `low_signal`), each entry carrying the schema defined in `.claude/agents/forgetter.md` § Output

`findings_inline` is required on every successful return (whether `mode: full` or `mode: partial`). The orchestrator writes the report file post-receipt.

The envelope markers are exactly `---forgetter-result---` and
`---end-result---`. No other opening marker is valid.

**No-envelope case (out-of-band).** If Forgetter is interrupted by the runtime and never emits the closing `---end-result---` marker, no envelope reaches the orchestrator. The orchestrator detects this absence and routes the scope to audit § Errors as `forgetter_no_envelope` with `scope`, `tool_calls_observed`, `duration_s`. The next-/hi cue (`scripts/cues.py check_autoevo_ran`) surfaces this via the Errors-section read.

**Per-finding `confidence` field.** Every row in `findings_inline` carries `confidence: high | medium | low` derived per category by the rules in `.claude/agents/forgetter.md` § Confidence Field. The orchestrator (specifically `/autoevo-nightly`) reads this field to decide whether a finding is auto-apply-eligible or routes to the pending queue. Findings without `confidence` (older Forgetter runs, partial reports) default to `medium` and never auto-apply.

**Cross-reference:** the agent-side spec is `.claude/agents/forgetter.md` → "Operating Principle", "Confidence Field", "Return Value".

## Contract: Meeting → Orchestrator

**Type:** `meeting-notes`

Required fields:
- `mode`: Executive
- `source`: Description of the meeting (name, date, participants if known)
- `structured_notes`: The formatted output (markdown)
- `action_items`: Array of `{owner, task, deadline}`
- `unclear_items`: Array of items flagged as ambiguous from the transcript
- `confidence`: How clean/complete the transcript was

The orchestrator presents the structured notes to the user and asks whether to create a local note via Curator.

## Contract: Evolver → Orchestrator (System Review Request)

**Type:** `system-review-request`

The orchestrator receives this and dispatches the Reviewer at the specified tier.

Required fields:
- `review_tier`: 1-4 (determines which reviewers the orchestrator dispatches)
- `review_mode`: holistic | diff | both
- `change_scope`: description of what changed
- `files_changed`: Array of file paths
- `status`: uncommitted (Evolver does not commit — orchestrator commits after review)
- `staged_files`: list of files with staged changes

## Escalation Protocol

If any agent encounters:
- **Empty search results**: Try alternative queries (synonym, other language, broader terms) before reporting gap
- **Contradictory evidence**: Flag explicitly — don't resolve silently
- **Token budget exceeded**: Summarize and note truncation
- **Long chain (turn 10 of a 15+ turn budget)**: Emit a midpoint checkpoint with `{verified: [...], remaining: [...], drift_check: <one line: still on original criterion? Y/N>}`. If `drift_check: N`, set `completion_status: aborted`, return the checkpoint as the envelope payload, and stop. The orchestrator decides whether to redispatch with a tighter criterion or accept the partial result. The 10-of-15 threshold is a tracked harness assumption (see `protocols/harness-assumptions.md` § Turn Budgets).

## Revision Loop

When Reviewer returns `NEEDS_REVISION`:
1. Reviewer specifies which checks failed and what would fix them
2. Synthesizer receives revision request with specific issues
3. Synthesizer revises (max 2 revision rounds)
4. If still failing after 2 rounds, deliver with caveats noted
