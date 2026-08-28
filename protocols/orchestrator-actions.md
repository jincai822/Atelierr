# Dispatchable Actions

Split from `orchestrator.md` (2026-08-24). Canonical for what each role
can be dispatched to do, including write boundaries and envelopes.

## Dispatchable Actions

The user can request these actions during or after any session:

### Note Operations (→ Curator)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Compact my notes on X" | Researcher finds notes in `$OV/` → orchestrator snapshots each source to `<paths.cache>/compact-<slug>.md` at dispatch time (local `cp`) → Curator drafts compaction → orchestrator writes after approval | Researcher → Curator |
| "Merge these notes" | Curator drafts merged note from snapshot files; orchestrator writes after approval | Curator |
| "Summarize [[Note]]" | Produce a concise summary | Synthesizer |
| "Write this insight as a new note" | Curator drafts a local note under the appropriate tier; orchestrator writes after approval | Curator |
| "Replace [[Old Note]] with this" | Curator drafts the rewrite; orchestrator applies via `Edit`/`Write` after approval | Curator |

### Research Operations (→ Researcher)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Find notes about X" | `Bash: uv run scripts/atelier/semantic.py query "X" --top 10 --context --format json` (bounded local `active` search) then `Grep` for exact-string follow-ups | Researcher |
| "What did I write about X last year?" | Filename-date filter on `<paths.daily_notes>/` + `Grep`. Report the gap if a date range is missing locally. | Researcher |
| "Are there related notes I'm forgetting?" | `Bash: uv run scripts/atelier/semantic.py query "<concept>" --top 10 --context --format json`; reframe once if thin, then select a deeper scope only when the intent requires it. | Researcher |
| "Show me everything tagged #X" | `Grep "#X"` over `$OV/` | Researcher |

### Meeting Operations (→ Meeting)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Process this meeting transcript" | Extract action items and decisions | Meeting |
| "Here are my meeting notes" | Structure into takeaways + action items | Meeting |
| "Summarize this research talk" | Read & discuss with lens analysis (transcript preprocessed) | Reader |

### Reading Operations (→ Reader + Hub)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Read [[Article]]" or "let's read this" | Multi-lens reading hub | Reader (3-5 instances) + Researcher + Scout + Thinker |
| "Read with [lens] lens" | Focused single-lens read | Reader (1 instance with specified lens) |
| "What does this article really say?" | Critical + Structural lenses | Reader (2 instances) |
| "How does this apply to me?" | Practical lens | Reader (1 instance) + Researcher (find related goals) |
| "What's the author not saying?" | Dialectical lens | Reader (1 instance) |

### Thinking Operations (→ Thinker / Challenger)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Apply [framework] to this" | Read framework, apply specifically | Thinker |
| "Challenge my assumption about X" | Find evidence for and against | Challenger |
| "What's the contrarian view?" | Independent perspective | Thinker |
| "What questions should I be asking?" | Generate question set | Challenger |

### Recommendation Operations (→ Librarian / Thinker)
| User Says | Action | Agent |
|-----------|--------|-------|
| "What should I read about X?" | Multi-format resource recommendations | Librarian |
| "Recommend books/papers/articles on X" | Curated recommendations with Chinese summaries | Librarian |
| "Who else has thought about this?" | Research thinkers/researchers | Librarian |
| "What framework fits this situation?" | Framework selection from library | Thinker |

### Review Operations (→ Reviewer)
| User Says | Action | Agent |
|-----------|--------|-------|
| "Check if this is grounded" | Verify citations and claims | Reviewer |
| "Review the quality of this output" | Score card generation | Reviewer |

### System Operations (→ Evolver)
| User Says | Action | Agent |
|-----------|--------|-------|
| "This session wasn't helpful because..." | Record feedback, evolve | Evolver |
| "Add a new framework for X" | Create framework file | Evolver |
| "Change how [command] works" | Modify command | Evolver |

### Decay Operations (→ Forgetter)
Bounded decay sweeps over `$OV/`. Forgetter never deletes and has no Write tool; it returns categorized findings inline via the `---forgetter-result---` / `---end-result---` envelope, and the orchestrator persists them as a decay report at `<paths.agent_findings>/decay-<RUN_TS>-<scope-slug>.md`, then surfaces the report path; the user reads it and decides. Every dispatch must specify `scope_path` (one directory under `$OV/`); `max_candidates` defaults to 15 and `time_budget_s` defaults to 300. The role spec is `.claude/agents/forgetter.md`.

| User Says | Action | Agent |
|-----------|--------|-------|
| "Scan my drafts for decay" / "Scan my wip" | Dispatch Forgetter with `scope_path: <paths.wip>/`. Surface the decay report path. | Forgetter |
| "What can I prune in my notes about X?" | Dispatch Forgetter with `scope_path` set to the topic-relevant directory (typically `<paths.wip>/` or `<paths.research>/`). Surface report. | Forgetter |
| "Are any of my wiki entries contradicted by newer notes?" | Dispatch Forgetter with `scope_path: <paths.wiki>/`. Forgetter only flags Contradicted on L4; report routes Contradicted items to Challenger to probe before any rewrite. | Forgetter → Challenger |
| "Find redundant notes I should compact" | Dispatch Forgetter with the user's `scope_path` of choice (or ask). Redundant items in the report route to Curator after user approval. | Forgetter → Curator |

### Capture Operations
Cheap-tier verbatim recording defaults to Scribe. Scribe voices and operation contracts live in `harness/agents.toml` and `.claude/agents/scribe.md`. The sole exception is an explicitly trip-associated meal capture, including Daily Reflection's Dining Pulse, which follows `/dine` Intent C's confirmation-gated structured-write flow. The orchestrator MUST NOT transcribe raw user content itself — that burns deep-cognition tokens on mechanical I/O.

| User dictates | Operation | Target tier |
|---|---|---|
| Date-stamped narrative for a day | `daily_note` | under `<paths.daily_notes>/` |
| Restaurant + score / 必点 explicitly associated with a named/current trip | `/dine` Intent C confirmation-gated structured write | the meal-history tracker plus one resolved compatible trip-note location |
| Restaurant + score / 必点 | `dining_row` | the user's dining-log file under `<paths.travel>/` |
| Action item with deadline / area, or close-out toggle on an existing item | `gtd_entry` (`add` / `toggle_done` / `toggle_killed`) | most recently modified file under `<paths.gtd>/` |
| Person mentioned with bio context, no person note exists yet | `people_stub` | under `<paths.people>/` |
| "Save this somewhere" — no typed slot fits | `generic` | orchestrator picks an `<paths.wip>/` path |

The Scribe is the only writer for its listed operations; the orchestrator does not duplicate the work after dispatch returns. The explicitly trip-associated meal exception is owned by `/dine` Intent C and is confirmation-gated. Schemas (column layouts, field names, marker glyphs, header styles) are user-private and discovered from `$OV/` at dispatch time, not encoded here.

**Zero-files recovery (orchestrator side, before dispatch):**
- `gtd_entry` — if `<paths.gtd>/` is empty, ask the user once for a default GTD filename and create the file in the dispatch context (or skip the dispatch and surface the question). Do not pass an empty `target_file` to the Scribe.
- `generic` — if no `<paths.wip>/` path is obvious from content, propose `<paths.wip>/<short-slug>.md` and confirm with the user before dispatch.
- `dining_row` / `daily_note` — if the canonical target file or directory does not exist, the Scribe will return a clarification request; route it back to the user to supply the path or filename rather than retrying with a guess.

