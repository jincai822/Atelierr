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
| "What did I write about X last year?" | Filename-date filter on `<paths.reflections>/` + `Grep`. Report the gap if a date range is missing locally. | Researcher |
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

### Decay Operations (retired)
The former Forgetter sweep is frozen. Do not dispatch it or infer a decay
target from user prose. Memory lifecycle behavior belongs to the application
memory module (`scripts/memory/decay.py`); any historical report remains a
rollback artifact and requires an explicit user request.

### Capture Operations
Cheap-tier verbatim recording defaults to Scribe. Scribe voices and operation contracts live in `harness/agents.toml` and `.claude/agents/scribe.md`. The sole exception is an explicitly trip-associated meal capture, including Daily Reflection's Dining Pulse, which follows `/dine` Intent C's confirmation-gated structured-write flow. The orchestrator MUST NOT transcribe raw user content itself — that burns deep-cognition tokens on mechanical I/O.

| User dictates | Operation | Target tier |
|---|---|---|
| Date-stamped narrative for a day | `daily_note` | under `<paths.reflections>/` |
| Restaurant + score / 必点 explicitly associated with a named/current trip | `/dine` Intent C confirmation-gated structured write | the meal-history tracker plus one resolved compatible trip-note location |
| Restaurant + score / 必点 | `dining_row` | the user's capture file under `<paths.inbox>/` |
| Action item with deadline / area, or close-out toggle on an existing item | `gtd_entry` (`add` / `toggle_done` / `toggle_killed`) | the active capture file under `<paths.inbox>/` |
| Person mentioned with bio context, no person note exists yet | `people_stub` | under `<paths.inbox>/` pending user filing |
| "Save this somewhere" — no typed slot fits | `generic` | orchestrator picks an `<paths.inbox>/` path |

The Scribe is the only writer for its listed operations; the orchestrator does not duplicate the work after dispatch returns. The explicitly trip-associated meal exception is owned by `/dine` Intent C and is confirmation-gated. Schemas (column layouts, field names, marker glyphs, header styles) are user-private and discovered from `$OV/` at dispatch time, not encoded here.

**Zero-files recovery (orchestrator side, before dispatch):**
- `gtd_entry` — if `<paths.inbox>/` is empty, ask the user once for a default capture filename and create the file in the dispatch context (or skip the dispatch and surface the question). Do not pass an empty `target_file` to the Scribe.
- `generic` — if no `<paths.inbox>/` path is obvious from content, propose `<paths.inbox>/<short-slug>.md` and confirm with the user before dispatch.
- `dining_row` / `daily_note` — if the canonical target file or directory does not exist, the Scribe will return a clarification request; route it back to the user to supply the path or filename rather than retrying with a guess.
