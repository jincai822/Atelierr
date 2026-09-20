# Local-First Architecture

The user's knowledge layer is plain-text Markdown files under `$OV/`. `$OV` is an environment variable that each user sets to their own vault root. The system reads and writes these files directly; there is no remote note-store mirror.

This is the prerequisite for everything in `wiki-schema.md` and `epistemic-hygiene.md`. Trust propagation, claim-level granularity, bi-temporal anchors, and structural-integrity linting all require deterministic Python access to plain-text files, which this layout provides.

## The Layers

The model has **five layers (L1–L5), numbered by depth of crystallization.** Higher number = higher trust. The axis is not provenance (human vs AI) but storage/certification depth: how much structural work, anchoring, and peer verification a note has accumulated by virtue of where it lives.

(Note: "Layer" here refers to the L1–L5 knowledge-storage axis. A separate orthogonal axis — the **validation-depth taxonomy** in `epistemic-hygiene.md` — uses the names *alloy* / *wiki entry* / `#solo-flight` for what a note *is*. Do not conflate the two: L1–L5 is *where*, alloy/wiki/solo-flight is *what*.)

```
    L5 — Foundation                   (reserved — textbook-level, universally certified)
    ────────────────────────────
    L4 — Locally certified            <paths.wiki>/
          authoritative knowledge     anchored, schema-validated, TrustRank-scored
    ────────────────────────────
    L3 — External receipts            <paths.cache>/
          fetched or imported evidence kept as derived cache
    ────────────────────────────
    L2 — Working / half-baked         <paths.memory>/, <paths.reflections>/,
          alloy by default            <paths.inbox>/
    ────────────────────────────
    L1: Raw capture                  Readwise, <paths.inbox>/, <paths.cache>/
          fast, sloppy, ephemeral
```

Promotion is **opportunistic and upward:** L1 capture crystallizes into a memory note or reflection; a recurring working thought earns an L4 wiki entry once it has anchors and claims; external receipts remain in the cache until cited. There is no demotion workflow — invalidation is additive (bi-temporal markers in wiki entries), not destructive.

### L1 — Raw capture

The fast, sloppy, ephemeral layer. Readwise's inbox (cloud-only, accessed via the `readwise` CLI; no local mirror) holds external content. `<paths.inbox>/` holds pending local captures and todos, while `<paths.cache>/` holds disposable fetches and derived files. No guarantees about structure across this layer. Promotion upward is opportunistic.

### L2 — Working / half-baked

The alloy layer. Most of the user's active thinking lives here: application memory notes (`<paths.memory>/`), session reflections (`<paths.reflections>/`), and pending captures or tasks (`<paths.inbox>/`). Alloy by default; the validation-depth taxonomy lives in `protocols/epistemic-hygiene.md`. Fully searchable, citable, but not certified. The substrate from which wiki entries are distilled.

Older topic material carried over from earlier knowledge systems is parked in `<paths.archive>/` and stays there until individual notes are surfaced upward.

**Capture and task inbox.** `<paths.inbox>/` is the active landing area for short-lived self-authored content and todos. Scribe records user-dictated material there; accepted notes are filed into `<paths.memory>/` or `<paths.reflections>/`, while source-derived artifacts remain in `<paths.cache>/` until they are no longer needed.

### L3 — External receipts

External papers, articles, and other source extracts are fetched through the active web or Readwise flows and kept under `<paths.cache>/` as rebuildable receipts. The canonical identifiers remain `url:`, `doi:`, `arxiv:`, or a Readwise document ID. Wiki claims cite a cache receipt or the external identifier; there is no separate local paper tier.

### L4 — Locally certified (wiki)

The slow, structured, authoritative layer. Lives in plain Markdown files under `<paths.wiki>/`. Each file follows `wiki-schema.md`. Each file is parseable by `scripts/atelier/trust.py` and produces a per-note trust score. Cross-references between wiki entries are `@cite` markers, which become edges in the trust graph.

**Directory is the certification.** A note is a wiki entry by virtue of living under `<paths.wiki>/`. There is no `#compiled-truth` or `#wiki` tag; the trust engine walks the directory and treats every file inside it as a wiki entry. The rest of `$OV/` stays alloy by default — the trust engine does not touch it. This gives the trust engine a single, fast directory traversal as its working set and avoids tag-collision with the user's existing tagging conventions.

L4 is the only tier where:

- Trust propagation runs.
- Bi-temporal anchors are tracked.
- Structural-integrity lint applies.

### L5 — Foundation (reserved)

Universally certified knowledge — textbook-level material that the user considers settled. No folder yet; the tier exists for future use when there is enough material to warrant one.

## Project Layout

Two roots:

- **System layer** — the `atelier/` repo (this directory). Orchestrator config, agents, protocols, scripts, source-handling teaching docs, and `sources/cite.py`. Version-controlled; no personal data.
- **Vault layer:** the user's note root, addressed as `$OV`. Active surfaces are `<paths.memory>/` for application notes, `<paths.wiki>/` for certified knowledge, `<paths.reflections>/` for session records, `<paths.inbox>/` for captures and todos, `<paths.cache>/` for derived receipts, `<paths.sessions>/` for process logs, `<paths.archive>/` for parked notes, and `<paths.meta>/`, `<paths.routine_prompts>/`, and `<paths.private_features>/` for framework state and extensions. Readwise inbox is external and is queried explicitly.

Vault paths use `$OV/` (e.g., `<paths.wiki>/`, `<paths.memory>/`, `<paths.inbox>/`); each user sets `$OV` to their note root (typical: `export OV="$HOME/notes"`). Repo-internal paths (`scripts/`, `protocols/`, `frameworks/`) stay project-relative and require no env var. The vault may live anywhere on disk (Google Drive, iCloud, a plain local folder); the system only needs `$OV` to point at it.

## Directory Layout (canonical)

```
atelier/                           (system root — the agent code)
├── CLAUDE.md                       # orchestrator instructions
├── .claude/agents/                 # team definitions
├── .claude/commands/               # slash commands
├── protocols/                      # system protocols (this directory)
├── frameworks/                     # thinking frameworks
├── profile/                        # gitignored config: self-model + private preferences (identity, directions, expertise, diet, reader_persona, credentials-index, private_slugs, examples, research-profile)
├── scripts/                        # Python tooling (trust.py, lint.py, semantic.py, ...)
└── sources/                        # source-handling teaching docs and helpers
    ├── cite.py                     # academic citation helper
    ├── readwise.md                 # Readwise CLI teaching doc
    ├── scholar.md                  # Semantic Scholar teaching doc
    └── semantic.md                 # local search and cache teaching doc

$OV/                                (vault root — set via env var)
├── memory/                         # application notes and the wiki library
│   ├── <category>/                  # working notes / raw material
│   └── wiki/                        # L4 — locally certified knowledge
│       ├── reflections/             # session reflection records
│       └── cognition/               # read-only cognition surface
├── inbox/                           # L1 — captures and todos awaiting filing
├── cache/                           # L1/L3 — derived receipts and fetches
├── sessions/                        # framework process logs
├── archive/                         # parked notes (surfaced opportunistically)
├── _meta/                           # operational state
├── _routine_prompts/                # archived routine prompts
└── _tools/features/                 # private feature sources
```

The trust engine and the wiki schema only see the `<paths.wiki>/` subtree. Everything else is alloy or receipts and the trust engine does not touch it.

## Search Projections

Storage layers and search scopes are related but not identical. The physical
vault remains the source of truth; the semantic index is a machine-local
projection with deliberate visibility boundaries:

- `active` is the default. It includes current authored knowledge and compact
  locator cards for pending captures and source clusters.
- `raw`, `archive`, `inbox`, and `process` are explicit deep-search scopes.
  `raw` includes readable raw text; `process` maps to `<paths.sessions>/`.
- `all` is an audit or recall-maximizing union, not the agent default.
- Any nested `cache/`, `_meta/`, `_routine_prompts/`, `.trash/`, or `_tools/`
  directory never enters semantic retrieval.
- Readwise remains external and opt-in through `--sources local,readwise`.

`scripts/atelier/semantic_corpus.py` owns classification, hard exclusions, locator
generation, and duplicate accounting. Stub search, real indexing, audits, and
tests must consume that policy rather than recreate directory rules. The CLI and
operational details live in `sources/semantic.md`.

## Source of Truth

`$OV/` is the canonical copy of the user's knowledge layer **for memory, wiki, reflection, and archive content that has been durably written and confirmed present on disk**. Pending captures in `<paths.inbox>/` and derived receipts in `<paths.cache>/` remain provisional. Two external carve-outs apply (Readwise as the source of unpromoted captures; in-flight routine outputs as provisional state in the claude.ai session log). Full SOT scope, carve-out rationale, and recovery paths: `backend-taxonomy.md` § SOT Scope.

Persistence has three concerns, each handled by a different mechanism:

- **Device sync**: handled by whatever filesystem $OV lives on (Google Drive, iCloud, plain folder). Outside the system's concern.
- **Version control**: $OV may be a git repo with an optional remote (typical: a private GitHub repo); see `protocols/repo-conventions.md` for the on-disk conventions that make `$OV` render correctly through GitHub. The system does NOT auto-commit or auto-push; commits remain user-driven.
- **Framework state**: operational records live under `<paths.meta>/`, routine prompt archives under `<paths.routine_prompts>/`, and private feature sources under `<paths.private_features>/`. These surfaces are not knowledge SOT.

There is no two-way sync between $OV and any other layer, and no idempotency ledger. The system reads/writes $OV directly; whatever the user has configured for backup happens transparently underneath.

Capture and todo entries under `<paths.inbox>/` are user-authored. By default the system reads them; Scribe is the only writer for user-dictated capture operations and records the content verbatim. Session reflections under `<paths.reflections>/` follow the same user-authored rule. The orchestrator does not transcribe or rewrite either surface directly.

The orchestrator can write approved proposals to `<paths.memory>/`, `<paths.reflections>/`, or `<paths.wiki>/` outside the read-only `<paths.cognition>/` subtree. The Curator drafts proposals; the orchestrator owns `Write` and `Edit` and applies them to a `target_path` under `$OV/`.

## Migration Strategy: Opportunistic, Not Big-Bang

There is no bulk migration of existing notes into the wiki layer. Older topic directories that are no longer active sit in `<paths.archive>/`. The wiki layer grows organically:

- New wiki entries are written to `<paths.wiki>/` directly (Curator drafts; orchestrator writes after approval).
- Existing notes (`<paths.archive>/` or anywhere else in L1/L2) are surfaced to L4 **only when they are about to become anchors for a new wiki claim** — at that point the user (or Curator) extracts the relevant claims, structures them per the schema, writes the wiki entry, and the original note remains in place as an L1/L2 capture record (untouched).
- There is no goal to hoist the entire vault into the wiki layer. `<paths.inbox>/`, `<paths.memory>/`, and `<paths.reflections>/` remain the home for captures, working notes, and most thinking. Most notes will never be in L4 — that is correct, not a failure.

The expected steady-state ratio is roughly: hundreds of L1/L2 notes for every L4 wiki entry. L4 is the slow, careful, anchored kernel. L1 and L2 are the fast surface.

## Indexes, detail notes, and todos

`<paths.inbox>/` is the active capture and todo surface. An action item stays
there until the user closes it or files it into `<paths.memory>/` or
`<paths.reflections>/`. An index or summary under `<paths.memory>/` is a view;
the detail note remains the source of truth, so readers verify the detail before
quoting the summary. This protocol defines no automatic index maintenance or
write-back.

See also: Planner vs Executor (below) for the upstream link between a todo and
the file that carries its execution detail.

## Planner vs. Executor (orthogonal to L1-L5)

A second asymmetry, also within the working layer: a *planner file* in
`<paths.inbox>/` enumerates intent, and one or more *executor files* in
`<paths.memory>/` or `<paths.reflections>/` carry out individual items in
depth. The planner is the source of truth for "what's outstanding"; the
executor owns the working detail and final receipts.

The convention is to make the upstream link bidirectional at creation time and to require backfill at closure time:

- **Downstream declares upstream** — every executor project's frontmatter carries `upstream: <path>#<anchor>` pointing at the row/line in the planner that spawned it. This is set when the executor file is created, not retrofitted.
- **Closure form is a backfill receipt** — when the executor completes an item, the corresponding planner row is rewritten as `- [x] <task> → backfilled <upstream-path>#<row> @YYYY-MM-DD`. Status (done) and provenance (where the work landed) travel together.
- **Backfill happens in the same turn/commit as the close.** Closing the executor item without touching the planner is the bug; the two edits are a single atomic transaction.

This convention is forward-looking; existing planner/executor pairs are not
retrofitted. Closure and the planner update should remain one user-reviewed
operation.

## Per-Agent Contract

| Agent | Active working surfaces | L4 wiki (`<paths.wiki>/`) |
|---|---|---|
| **Researcher** | Local `active` semantic search first, using context JSON with at most 10 capsules; selects `raw`, `archive`, `inbox`, or `process` only when required, then reads relevant sections from 3-5 files. `Grep` + `Read` remain structural. | Reads `<paths.wiki>/` directly when certified scope is required. |
| **Curator** | Drafts note proposals (compactions, merges, new notes, rewrites); the orchestrator writes to `<paths.memory>/` or `<paths.reflections>/` after user approval (Curator has no `Write` tool). | Drafts wiki entries with `target_path: <paths.wiki>/<slug>.md`. The orchestrator writes the file after approval, then runs `scripts/atelier/trust.py --note <path>` to verify structural integrity and report initial scores. |
| **Synthesizer** | Reads capture-layer briefs from Researcher; produces drafts the orchestrator writes to `<paths.reflections>/`. | Reads wiki trust scores when available to weight evidence. |
| **Reviewer** | Continues to gate write-backs. Gates wiki writes as well. A `@pass: reviewer | status: verified` marker is added to a claim only after Reviewer signs off. | Unchanged. |
| **Scout** | Reads and writes source receipts under `<paths.cache>/`; hands findings to the orchestrator for filing in `<paths.inbox>/` or `<paths.memory>/`. | Unchanged. |

## Cross-References

- Tag taxonomy and validation-depth principle: `epistemic-hygiene.md`
- Wiki entry format and trust propagation rule: `wiki-schema.md`
- Trust engine implementation: `scripts/atelier/trust.py`
- Lint integration: `.claude/commands/lint.md`
- Backend taxonomy and SOT carve-outs: `backend-taxonomy.md`
