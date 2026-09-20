# Agent Collaboration Matrix

Split from `orchestrator.md` (2026-08-24). Canonical for sequential chains,
parallel dispatch shapes, cross-validation pairs, Review Tiers, and the
orchestrator's collaboration duties.

## Agent Collaboration Matrix

The orchestrator should actively look for collaboration opportunities during sessions. When one agent's output creates a natural opening for another, chain them.

### Sequential Chains (output of A feeds into B)

| Chain | Trigger | Flow | Value |
|-------|---------|------|-------|
| **Research → Synthesize → Review** | Every session | Researcher → Synthesizer → Reviewer | Core quality pipeline |
| **Synthesizer → Orchestrator write-back** | Synthesizer returns output and a session asks for a write-back | Synthesizer produces the draft; the orchestrator catches it, runs the Reviewer+Challenger gate, and writes the reflection file under `<paths.reflections>/` (or another tier) after user approval. Synthesizer has no Write tool — write-back is always orchestrator-side. | Keeps the write-back decision and approval gate in one place |
| **Scout → Challenger** | Scout finds something that contradicts user's notes | Scout → Challenger surfaces the contradiction | External evidence challenges internal beliefs |
| **Scout → Librarian** | Scout finds a key resource worth deep reading | Scout flags → Librarian adds to curated list | Scout finds, Librarian curates |
| **Challenge → Curate** | Challenger surfaces outdated belief or contradiction | Challenger → ask user "want to update that note?" → Curator rewrites | Turns insight into note hygiene |
| **Review → Librarian** | Reviewer flags weak grounding in a topic area | Reviewer → Librarian recommends resources to fill the gap | Closes knowledge gaps |
| **Thinker → Challenger** | Thinker applies a framework | Challenger questions whether the framework fits | Prevents lazy framework application |
| **Librarian → Researcher** | Librarian recommends a resource | Researcher checks if user already has notes on it | Avoids recommending what user already knows |
| **Researcher → Curator** (focused-session default) | Researcher finds many overlapping notes during a focused session about ONE topic; user wants a quick compaction suggestion ("compact my notes on X") | Researcher flags → Curator proposes compaction on the specific overlap set | Proactive note hygiene with low ceremony — the right call when the user is already mid-flow on the topic |
| **Researcher → Forgetter** (corpus-sweep escalation) | User is doing a corpus cleanup / sweep session and wants systematic decay analysis on a broader scope ("find what I should forget", "scan my drafts for decay"), OR Researcher finds 3+ overlapping notes and the user explicitly asks to widen the lens beyond the current topic | Researcher's overlap signal (or the user's sweep intent) → orchestrator dispatches Forgetter with `scope_path` set to the topic or working directory → Forgetter returns findings inline citing all four categories with evidence → orchestrator persists the decay report and surfaces its path → user decides on per-item Curator compaction or other action | Bounded, evidence-cited sweep across categories beyond redundancy; the right call when the user wants thoroughness over speed |
| **Forgetter → Curator** | Forgetter's decay report flags Redundant items | Orchestrator surfaces report → user approves redundant set → Curator drafts compaction → orchestrator writes after approval | Decay analysis becomes note hygiene; verbatim claim preservation enforced at Curator gate |
| **Forgetter → Challenger** | Forgetter's decay report flags Contradicted items in `<paths.wiki>/` | Orchestrator surfaces report → Challenger probes whether contradiction is genuine → if confirmed, Curator rewrites the wiki entry (claim update + Revision Log row) | Wiki entries get a verifier pair before mutation; Forgetter detects, Challenger probes, Curator rewrites |
| **Meeting → Curator** | User approves meeting notes for saving | Meeting output → Curator drafts local note → orchestrator writes after approval | Turns transcript into permanent note |
| **Reader → Synthesizer** | Multiple Reader lenses complete | Synthesizer combines all lens briefs into unified report | Multi-dimensional reading analysis |
| **Reader → Challenger** | Reader surfaces a claim worth questioning | Challenger probes the claim against user's existing beliefs | Deepens engagement with the text |
| **Reviewer + Challenger → Write-back** | Reading discussion ready for write-back | Reviewer checks grounding, Challenger checks completeness | Quality gate before an approved reading reflection |
| **Evolver → Orchestrator → Review → Commit** | Evolver proposes a system change | Evolver makes changes (no commit) → returns `review_tier` to orchestrator → orchestrator dispatches reviewers → fixes issues → commits | Quality gate on system evolution (see Review Tiers) |
| **Batch Compaction** | User asks to compact a topic area | Researcher finds all notes in `$OV/` → Orchestrator snapshots each source to `<paths.cache>/compact-<slug>.md` at dispatch time → Curator drafts one output note at a time → orchestrator writes each after approval | Sequential: all snapshots must exist on disk before Curator starts |
| **Pre-Output Raw Capture** | Reflection / coaching session about to write its reflection file, and the user dictated raw capture content during the session | Orchestrator collects raw user content per Capture surface (daily note, dining row, GTD, people stub, generic) → dispatches one Scribe per surface in parallel → all Scribe writes complete before the orchestrator writes the reflection file | Cost-partitioned: cheap-tier captures (Scribe), deep-cognition voices do not transcribe |

### Parallel Dispatches (A and B run simultaneously)

| Pattern | Agents | When | Value |
|---------|--------|------|-------|
| **Deep Dive** | Researcher + 2-5× Scout + Librarian + Thinker | User picks Deep Dive | Full briefing: notes + multi-angle web intel + resources + framework |
| **Reading Hub** | 2-4× Reader + Researcher + Scout + Thinker | User picks Read or says "let's read" | Multi-lens analysis: lenses + notes + external + framework |
| **Multi-topic Triage** | Multiple Researcher dispatches | User picks Note Triage | Scan several topic areas simultaneously |

**Scout multi-dispatch rule:** Dispatch 2-5 Scout instances based on topic complexity. Simple topics: 2 (e.g., Mainstream + Contrarian). Complex or high-stakes topics: 3-5 (cover more directions). Each instance gets a different direction assignment from `.claude/agents/scout.md`. Use `AskUserQuestion` to let the user choose breadth if unclear.

### Cross-Validation Pairs (two perspectives on the same question)

| Pair | Purpose | When to use |
|------|---------|-------------|
| **Thinker + Challenger** | Framework says X, but does it actually fit? | After any framework application |
| **Researcher + Scout** | Internal notes vs. external world | Deep Dive, decision sessions, or when user needs outside context |
| **Scout + Librarian** | Raw web intelligence vs. curated recommendations | After Scout gathers findings, Librarian curates the best for deep reading |
| **Synthesizer + External Reviewer** | Internal synthesis vs. external review | Monthly system review, or when session quality is declining |
| **Reader + Reader** | Same text, different lenses — do they converge or diverge? | Multi-lens reading sessions |
| **Reader + Thinker** | Lens analysis vs. framework application on same content | Reading hub — when text triggers a framework |
| **Reviewer + Challenger** | Is the output grounded? + Is it asking the right questions? | Quality gate for important sessions |

### Review Tiers

Four reviewer types, scaled by change complexity. The orchestrator selects the right tier based on the scope and risk of changes.

#### The 4 Reviewers

| # | Reviewer | What it reads | What it catches | Invocation |
|---|----------|--------------|-----------------|------------|
| 1 | **Internal Holistic** | Full file state (not the diff) | Global inconsistency, local optimum traps, architectural drift | Reviewer agent reading all changed files end-to-end |
| 2 | **Internal Diff** | Incremental changes only | Broken contracts, missing wiring, introduced bugs | Reviewer agent reading the diff |
| 3 | **External Diff (Codex)** | `git diff` | Blind spots from a different model's perspective | `/codex review` |
| 4 | **External Diff (Gemini)** | `git diff` | Second external perspective, different biases | `git diff <base>..HEAD \| gemini -p "Review this diff..." -y` |

**Why both internal review types matter:** The diff reviewer catches what you just broke. The holistic reviewer catches what was already broken — or what looks fine incrementally but creates a system-level inconsistency. Without holistic review, the system drifts toward local optima: each change is locally correct but globally incoherent.

#### Tier Selection

| Tier | Reviewers | When to use | Examples |
|------|-----------|-------------|---------|
| **Tier 1** (routine) | Internal Diff only | Small targeted fixes, typos, single-file edits | Fix a typo in a protocol, adjust a search query |
| **Tier 2** (moderate) | Internal Diff + 1 External | Multi-file changes within existing patterns | Add a collaboration trigger, update a rubric |
| **Tier 3** (significant) | Internal Holistic + Internal Diff + 1 External | New capabilities, new workflows, cross-cutting changes | Add a new agent, create a new workflow, modify handoff contracts |
| **Tier 4** (high-stakes) | All 4 in parallel | Architectural changes, rewrites, anything touching 5+ files | Rewrite a protocol, add a new session type, restructure the team |

**Default:** When uncertain, use Tier 3. Over-reviewing is cheaper than under-reviewing.

#### Holistic Review Checklist

The Internal Holistic reviewer reads all changed files in full (not just the diff). The list of global-consistency invariants checked is canonical in `.claude/agents/reviewer.md` → System Holistic Review Mode. The orchestrator does not redefine those checks here; it dispatches and verifies completion.

#### External Reviewer Invocation

Always use the strongest available model for review depth.

| Reviewer | Command | Model |
|----------|---------|-------|
| **Codex** | `/codex review` | Best available |
| **Codex** (adversarial) | `/codex challenge` | Best available |
| **Gemini** | `git diff <base>..HEAD \| gemini -m gemini-3.1-pro-preview -p "Review this diff for a reflection system. Check for: consistency, missing integration, overclaims, design issues. Be direct." -y` | Gemini 3.1 Pro |

#### Graceful Degradation

External tools are optional but the tier system enforces consequences when they're missing:

| Requested Tier | Tools missing | Downgrade to | Action |
|---------------|--------------|-------------|--------|
| Tier 1 | (no external needed) | — | Run as normal |
| Tier 2 | 1 external missing | Tier 1 | Warn: "External reviewer unavailable — downgraded to Tier 1 (internal diff only)" |
| Tier 3 | Both externals missing | Tier 2 (holistic + diff, no external) | Warn and flag as under-reviewed |
| Tier 4 | 1 external missing | Tier 3 | Run with the available external reviewer |
| Tier 4 | Both externals missing | Tier 2 | Warn: "No external reviewers — downgraded to Tier 2. Consider installing codex or gemini." |

**Never silently skip a required reviewer.** Always warn and explicitly downgrade the tier.

### Orchestrator's Collaboration Duties

During any session, actively look for these signals and chain agents:

| Signal | Action |
|--------|--------|
| Challenger surfaces a contradiction with an old note | Offer: "Want to update [[Note]]?" → Curator |
| Reviewer scores < 7 on a dimension | Flag to Evolver for system improvement |
| Researcher finds 3+ notes on same topic | **Default (focused session):** suggest "These could be compacted" → Curator on the overlap set. **Escalation (sweep intent):** if the user is doing corpus cleanup or asks for a thorough sweep beyond the current topic, dispatch Forgetter with `scope_path` set to the topic directory; surface the resulting decay report path to the user. The default is the focused, low-ceremony Curator path; Forgetter is the systematic-sweep path. |
| Thinker applies a framework | Route to Challenger for cross-validation |
| Librarian recommends resources | Route to Researcher to check existing notes |
| Any session scores low on surprise | Next session: Researcher should search older/deeper notes |
| Researcher flags a Moment | Surface it to user, suggest `#moment` tag via Curator, note which direction it feeds |
| Energy audit shows a life area below amenity floor | Flag it: "[Area] is below amenity floor." Amenity-floor definition lives in `protocols/session-scoring.md`. |
| User tries to change focus mid-session | Enforce Focus Lock — redirect to a full `/review` session first |
| User says "this was great" or "this wasn't helpful" | Route feedback to Evolver |
| User refines a strategic/directional claim 2+ times in one session | Treat as refinement-arc. Label the latest version as "working hypothesis (refinement N)", not "refined position." Auto-dispatch Challenger against the latest version with the previous version(s) as comparison set, before any write-back. Do not frame later iterations as monotonically better than earlier ones; apply equal rigor. The "Refinement-arc hygiene" semantic basis lives in `protocols/epistemic-hygiene.md`. |
| Curator proposes a note (compact/merge) | **Verify Gate 4**: check media count match, size < 15KB, verbatim preservation. Block if any check fails. |
| **Evolver returns with `review_tier`** | **Mandatory: dispatch reviewers for that tier. Never skip.** The Evolver does NOT commit — the orchestrator reviews the diff, dispatches reviewers, fixes issues, then commits. The orchestrator owns this gate. See Review Tiers above for which reviewers to dispatch per tier. |

