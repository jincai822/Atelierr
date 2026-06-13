# scripts/

Executable tooling for the Atelier knowledge layer. All scripts are stdlib-only (or stdlib + one documented dependency), deterministic, and runnable from the repo root with project-relative paths.

## Inventory

| Script | Purpose | Phase | Deps |
|---|---|---|---|
| `semantic.py` | Local semantic search over `$OV/` — BGE-M3 embeddings + LanceDB with tier-aware reranking; lexical fallback when index is absent | B.5 | `lancedb`, `sentence-transformers` (optional; falls back to lexical) |
| `semantic_backends.py` | Backend implementations for semantic.py (LanceDB embedding backend, lexical fallback) | B.5 | `lancedb`, `sentence-transformers` (optional) |
| `semantic_eval.py` | Offline evaluation harness for semantic.py — builds a wikilink-derived gold set from the vault and computes retrieval metrics | B.5 | `lancedb`, `sentence-transformers` |
| `config.py` | Loads device-dependent semantic-index parameters from gitignored `semantic.toml`; safe defaults when the file is missing | B.5 | stdlib |
| `_paths.py` | Shared path-resolution helpers — fail-loud `$OV` resolution plus logical-tier → physical-segment mapping from `harness/paths.toml` (+ gitignored local layer) | ops | stdlib |
| `trust.py` | TrustRank for `$OV/wiki/` — Personalized PageRank with external anchor seeds, claim-level granularity, bi-temporal filtering, floor trust | B | stdlib |
| `snapshot_anchors.py` | Saves `url:` / `gist:` wiki anchors to Readwise and backfills the `readwise:` document ID so anchor evidence stays durable | B | `readwise` CLI |
| `lint.py` | Structural + corpus-level lint over `$OV/wiki/` — parse errors, duplicate titles, slug drift, orphan entries, graph topology | D | stdlib |
| `harness_lint.py` | Claude Code and Codex portability lint — root instructions, model profiles, capability mappings, command and agent registries | ops | stdlib |
| `harness_smoke.py` | Smoke test for the portable harness helper and lint JSON surfaces | ops | stdlib |
| `atelier.py` | Portable command/agent discovery and Codex prompt generation from `harness/*.toml` | ops | stdlib |
| `privacy_check.py` | Scans tracked files for private-vault filename-stem leaks; opt-outs live in `privacy_allowlist.txt`; wired into `/lint` Phase 0c | ops | stdlib |
| `zk_audit.py` | Post-ingestion hygiene audit for `$OV/`: missing READMEs, raw-without-digest, archive↔working overlap, root orphans, suspicious dirs; wired into `/lint` Phase 0b | ops | stdlib |
| `staleness.py` | L2 staleness scoring — surfaces dormant, stale, and promotion-candidate notes | D | stdlib |
| `aggregate_freshness.py` | Aggregate-vs-detail staleness guard — flags aggregate trackers whose `Last updated:` is older than their newest subject file; `--discover` walks `freshness: required` frontmatter | ops | stdlib |
| `auto_memory_audit.py` | Audit pass over Claude Code auto-memory — surfaces stale, orphaned, dead-linked, or self-flagged provisional entries for human invalidation | ops | stdlib |
| `people.py` | Canonical person-note lookup by name fragment — pathlib walk (no xargs word-splitting); opt-in body-field matching via env var | ops | stdlib |
| `cues.py` | Unified quiet-by-default cue checker for `/hi` session start — silent when nothing fires, one tab-separated line per due cue | ops | stdlib |
| `recurring.py` | Manages recurring obligations in `$OV/gtd/recurring.md` — re-emerging tasks with `every:` / `last-done:` due computation, distinct from one-shot GTD items | ops | stdlib |
| `todos.py` | Aggregate open TODOs from `$OV/gtd/` and reflection Next Action sections; computes priority from `due:` / `priority:` / age; flags closure candidates from daily-note language; subcommands `list`, `stale`, `closure-candidates`, `digest` — `digest` powers `/daily-reflection` Step 0 (reached via `/hi`) | ops | stdlib |
| `session_log.py` | Session event log skeleton generator — handles late-sleep date rule and collision auto-increment | E | stdlib |
| `shadow.py` | Cross-provider shadow-log correlation + reporting — `group-start` / `group-close` witnesses for multi-leg call sites, `report` over the JSONL call logs | ops | stdlib |
| `routine_lock.py` | Distributed lock for scheduled routines via DynamoDB conditional put — one machine executes per cycle; stale locks taken over at acquire time once their TTL passes | ops | `boto3` (skipped when coordination is "none") |
| `routine_runner.sh` | launchd wrapper for scheduled routines — env setup, hostname stagger, lock acquire, claim file, `claude -p` execution, lock release | ops | `claude` CLI, `routine_lock.py` |
| `rewrite_paths.py` | Mechanical half of a tier rename — rewrites `$OV/<old>` to `$OV/<new>` across committed docs after editing `harness/paths.toml` | ops | stdlib |
| `relink.py` | Fixes broken markdown links after file moves — rewrites refs to each filename stem's current location (`--dry-run` / `--apply`) | ops | stdlib |
| `fission.py` | Generic directory fission per the 32-entry rule — splits a directory's .md children into bucket subdirs (first-letter, year-month, year/month); pair with `relink.py` | ops | stdlib |
| `wikilink_to_md.py` | Converts Obsidian wikilinks to standard markdown links — aliases, headings, date links, image embeds; unresolved links become semantic tags | ops | stdlib |
| `log_backlinks.py` | Retrofits `[[YYYY-MM-DD]]` wikilinks into markdown-table date cells so rows backlink the daily note for that date | ops | stdlib |
| `review.sh` | External reviewer wrapper (codex + direct-api leg in parallel; `gemini` kept as a legacy mode) for system-evolution diffs | ops | `codex` CLI, direct-api binding (`chat_completion.py`); `gemini` CLI optional |
| `chat_completion.py` | Stdlib-only OpenAI-compatible chat completion invoker. Stateless (one-shot) by default; `--session FILE` for multi-turn (history replayed each call). Selects the model via `--model <identity>` (schema in `harness/models.toml`, bindings in gitignored `profile/models.toml`) or direct flags. Backs the direct-api leg of every dual-voice role; switching providers is a binding edit, not a script change. `--max-tokens 0` omits the cap entirely (system-review path uses this). Every call (success and error) logs one JSONL line to `~/.cache/atelier/llm_calls/<date>.jsonl` for after-the-fact quality / latency / reasoning audit; pass `--no-log` to skip on sensitive prompts | ops | stdlib |
| `pricing.py` | Provider pricing catalog reader + cost calculator. Reads `scripts/pricing.toml` (flagship + standard per provider, USD per 1M tokens). Subcommands: `list` (sorted blended-cost table), `blended <provider> <class>`, `cost <provider> <class> --input N --output N`, `cost-from-log` (retrospective cost from `~/.cache/atelier/llm_calls/`). Used to drive future Pareto-optimal model selection (perf/cost) | ops | stdlib |

## Portable Harness

`scripts/atelier.py status` summarizes the Claude/Codex registry state.
Use `commands`, `agents`, `prompt`, and `agent-prompt` subcommands to discover
portable workflows without scraping `harness/*.toml` directly.
Run `scripts/harness_smoke.py` after harness edits to verify the helper and JSON
surfaces end to end without touching `$OV/`.

## `trust.py` — quick reference

Walks `$OV/wiki/*.md`, parses each wiki entry into claims and markers, builds a directed trust graph, runs Personalized PageRank, applies the claim-level floor trust of 0.1, and reports per-claim and per-note scores.

```
scripts/trust.py                                   # default table over $OV/wiki/
scripts/trust.py --note "$OV"/wiki/<file>.md       # per-claim breakdown
scripts/trust.py --as-of 2025-06-01                # bi-temporal snapshot
scripts/trust.py --json                            # structured output for /lint
```

**Model.** External `@anchor` markers are the only seeds of trust. `@cite` edges propagate trust from cited claims to citing claims. `@pass` markers never accumulate trust; a reviewer-verified pass only enables the claim-level floor of 0.1 on a structurally-valid note.

**Determinism.** Pure Python, stdlib-only. PageRank is a direct power-iteration implementation matching `networkx.pagerank(G, personalization=anchor_dict)` semantics (dangling mass redistributes to the personalization vector, damping 0.85, tolerance 1e-9, max 200 iterations). Zero new dependencies.

**Bi-temporal.** Every marker has `valid_at` (required); optional `invalid_at`. `--as-of` filters markers by the active window. With no active anchors in the snapshot, all claim scores are 0 by design: TrustRank with an empty seed set means no trust has entered the graph.

**Structural integrity.** `trust.py` enforces items 1 to 10 of `protocols/wiki-schema.md` § Structural Integrity Check. A note that fails parse contributes no seeds and no propagation edges, but its claims still appear in the report with score 0 and a `fail` status. Corpus-level lint (items 11 to 15) is implemented by `scripts/lint.py`, surfaced through `/lint`.

**Exit codes.** `0` on success. `2` on usage error (missing file, invalid date, note outside `$OV/wiki/`).

See `protocols/wiki-schema.md` for the schema and the trust-model rationale.
