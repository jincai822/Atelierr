# Local Semantic Search (`scripts/atelier/semantic.py`)

Teaching doc for the `semantic.py` CLI. Agents and command files call this script to find notes by meaning rather than exact string match.

**This doc describes the contract, not the implementation.** The backend swaps across three stages (stub, BGE-M3, corpus-tuned local model) without changing anything below.

## Modes

**Stub mode** (lexical fallback): active when `~/.cache/atelier/lance/` does not exist. Uses the same corpus policy and scopes as real mode, but ranks with lexical token matching. Prints a warning to stderr on every invocation so callers never mistake "empty result" for "no conceptual neighbor exists."

**Real mode** (embedding-backed): active when `~/.cache/atelier/lance/` exists (sentinel). Current stack: dense embedder (BGE-M3 default, Qwen3-Embedding-0.6B / 4B / 8B opt-in via `SEMANTIC_EMBEDDER`) + LanceDB (embedded columnar store, cosine distance) + BM25 sparse retrieval fused via Reciprocal Rank Fusion + optional BGE-reranker-v2-m3 cross-encoder rerank. Documents are chunked at markdown heading boundaries (~2K chars per chunk). Index is machine-local per embedder (`~/.cache/atelier/lance/`, `~/.cache/atelier/lance-qwen3-0.6b/`, ...); rebuild with `uv run scripts/atelier/semantic.py index` (~10 min on MPS for 5K-file vault with BGE-M3 / Qwen3-0.6B, ~60 min for Qwen3-4B). No caller code changes across the swap.

Model loading is cache-first. When the Hugging Face cache contains a snapshot
with both the model config and Sentence Transformers modules manifest, the
backend passes that local snapshot directory directly to Sentence Transformers
with `local_files_only=True`. This avoids remote metadata and background model
conversion requests. An uncached model may still download during interactive
setup. `HF_HUB_OFFLINE=1` or `TRANSFORMERS_OFFLINE=1` forces local-only loading
even when no complete snapshot can be resolved.

## CLI

```
scripts/atelier/semantic.py query "<text>" [OPTIONS]
scripts/atelier/semantic.py status [--format text|json]
scripts/atelier/semantic.py corpus [--format text|json]
scripts/atelier/semantic.py index [--rebuild | --if-stale]
scripts/atelier/semantic.py --help
```

### `query` options

| Flag | Meaning | Default |
|---|---|---|
| `--path DIR` | Restrict to a subdirectory (repeatable). | `$OV/` |
| `--after YYYY-MM-DD` | Files with mtime >= date. | none |
| `--before YYYY-MM-DD` | Files with mtime <= date. | none |
| `--top N` | Max results. | 10 |
| `--lang {zh,en,auto}` | Query language hint. No-op in stub mode. | `auto` |
| `--format {tsv,json}` | Output format. | `tsv` |
| `--scope {active,raw,archive,inbox,process,all}` | Select the indexed knowledge zone. `active` includes compact raw locator cards, not raw file contents. | `active` |
| `--context` | With JSON output, return bounded section capsules with heading, snippet, tier, scope, and representation. | off |
| `--sources LIST` | Comma-separated sources: `local`, `readwise`. Readwise is opt-in and uses its CLI in real mode; stub mode remains local-only. | `local` |

`--context` requires `--format json`. It keeps only the best chunk per file,
caps raw locators at two in the default scope, and limits each snippet to 600
characters. Without `--context`, a single-source query preserves the legacy
chunk-ranked output. Multi-source queries deduplicate paths after merging.
In real mode, default `active` and explicit `raw` queries also search the
small raw-locator view lexically. This recovers exact filename and cluster
terms without materializing full-corpus BM25 on every query. `--hybrid`
remains the opt-in full dense plus BM25 path. A strong lexical locator match
is a one-slot tail backfill, not a relevance competitor: authored results and
any configured reranker keep their order ahead of the generated navigation
card. The same backfill remains enabled with `--hybrid`, so exact raw filename
lookup does not regress when full BM25 is selected.

### Corpus policy

`scripts/atelier/semantic_corpus.py` is the single policy used by stub search, real
indexing, freshness checks, audits, and smoke tests.

| Scope | Contents |
|---|---|
| `active` | Current authored Markdown plus compact generated raw locator cards. This is the default. |
| `raw` | Readable text under a `raw/` path plus the raw locator cards. |
| `archive` | Parked authored notes under `archive/`. |
| `inbox` | Pending captures under `inbox/`. |
| `process` | Session-process records under `sessions/`. |
| `all` | Union of the indexed scopes. |

The corpus always excludes any nested `cache/`, `_meta/`, `_routine_prompts/`,
`.trash/`, or `_tools/` directory; `archive/orphan-stubs/`; hidden operational
directories; dependency trees such as `node_modules/`; and empty or
whitespace-only files. Any non-archived, non-process directory segment named
`inbox` maps to explicit `inbox` scope rather than default `active`.

Binary raw assets are discoverable without OCR. The policy groups files by raw
cluster and generates an in-memory locator card containing safe path terms,
file-type counts, date range, asset count, and nearby digest paths. Locator
cards are indexed but never written into the vault. Readable
Markdown/text/CSV/HTML raw files are additionally available in `raw` scope.

### Freshness and indexing

| Call | Meaning |
|---|---|
| `semantic.py status --format json` | Compare the current corpus manifest, policy version, raw-locator fingerprints, and index schema with the stored index without loading the embedding model. |
| `semantic.py corpus --format json` | Audit scope classification, hard exclusions, raw locator coverage, exact duplicates, and estimated chunks without loading an embedding model. |
| `semantic.py index` | Incrementally update changed records and remove deleted records. A schema or corpus-policy migration forces one derived-cache rebuild. |
| `semantic.py index --if-stale` | Run the lightweight freshness check first; load the embedding model only when drift exists. Used by scheduled maintenance. |
| `semantic.py index --rebuild` | Clear and rebuild the complete index. Keep this manual. |

Every invocation that actually changes the index emits one JSON object on
stdout under `search_efficiency`. It reports update counts and duration, total
chunks, default-scope corpus reduction, raw coverage, three representative
query latencies, result deduplication, and average capsule bytes. A fresh
`index --if-stale` no-op does not rerun probes or emit a report.

### Output

TSV (default): one result per line. Column 3 differs by mode:

```
<path>\t<score>\t<matched_tokens>   # stub mode
<path>\t<score>\t<source>           # real mode
```

- `path` is relative to the vault root (`$OV`) for local results; readwise results use a `readwise://<document_id>` URI.
- `score` is in `[0.0, 1.0]`. Higher is better. Stable sort direction across stub and real modes.
  - **Stub:** `min(total_token_hits, 10) / 10`.
  - **Real:** cosine similarity between query embedding and file embedding.
- `matched_tokens` (stub only) is a comma-separated token list. `source` (real only) is the source label: `local` or `readwise`.

JSON (`--format json`): real mode returns objects with `path`, `score`,
`source`, and `matched_tokens`; stub mode preserves its legacy `path`,
`score`, and `matched_tokens` shape. Add `--context` for bounded capsules with
`heading`, `snippet`, `tier`, `scope`, `representation`, and truncation state.
Default local queries preserve chunk-ranked results. Context and multi-source
queries collapse to the best chunk per path. Every active-scope result set caps
raw locator cards so provenance does not crowd out authored notes.

### Exit codes

- `0` — success (including zero results).
- `0` — `status` completed, whether the index is fresh or stale.
- `0` — `corpus` completed its read-only audit.
- `2` — usage error (bad flag, unparseable date).
- `2` — `status` could not inspect an existing index.

### Streams

- **stdout:** query results or command-specific reports. Query output remains parseable by `xargs`, `awk`, etc. A real index update returns `{"search_efficiency": {...}}`.
- **stderr:** mode banner, warnings, diagnostics. Always emitted; callers should not silence stderr.

## When to call this script

| Situation | Call |
|---|---|
| Searching for a specific keyword or title | Use `Grep`, not this script. |
| Searching for a concept that might be phrased many ways | `semantic.py query "<concept>" --context --format json` |
| Locating receipts, exports, or other raw provenance | Start in `active`; use `--scope raw` when full readable raw text is needed. |
| Inspecting parked history or process traces | Use explicit `--scope archive` or `--scope process`. |
| Auditing what can enter the index | `semantic.py corpus --format json` |
| `/explore` — surfacing forgotten connections | `semantic.py query` with a broad concept from today's context |
| `/introspect` — finding curiosity vectors that aren't named as goals | `semantic.py query` after lexical grep passes |
| `/hi` forgotten-connection step | `semantic.py query` with a concept from the current conversation |
| `/energy-audit` — searching for affective states | `semantic.py query "tired exhausted drained"` |
| `/decision` — adjacent prior thinking | `semantic.py query` alongside lexical grep |

## Stub-mode caveats

- **Lexical-only.** Queries that require understanding paraphrase, synonymy, or conceptual adjacency will underperform. A query for "what am I avoiding?" returns nothing useful in stub mode.
- **Case-insensitive.** Matching is lowercased.
- **CJK-tolerant.** Chinese characters are preserved through tokenization, so queries like `"目标 精力"` work for exact-phrase matches but not conceptual ones.
- **No ranking beyond token frequency.** A daily note that mentions the query word five times in passing will outrank a wiki entry that discusses the concept in depth using different words. Real mode fixes this.

To exit stub mode, run `uv run python scripts/atelier/semantic.py index` to build the lance index.

## Examples

Basic query:
```
scripts/atelier/semantic.py query "curiosity vectors"
```

Restricted to reflections in the last 30 days, JSON output:
```
scripts/atelier/semantic.py query "energy drain" \
    --path "$OV"/reflections \
    --after 2026-03-07 \
    --scope active \
    --context \
    --format json
```

Multiple paths, top 20 hits:
```
scripts/atelier/semantic.py query "研究 方向" \
    --path "$OV"/daily-notes \
    --path "$OV"/reflections \
    --top 20
```

Reading only authored files returned by a bounded agent query:
```
scripts/atelier/semantic.py query "contradiction" --top 5 --context --format json | \
    jq -r '.[] | select(.source == "local" and .representation == "authored") | .path' | \
    while read path; do sed -n '1,220p' "$OV/$path"; done
```

Raw locator paths begin with `@raw-locator/`; they are generated records, not
filesystem paths. Use the locator's cluster terms to narrow an explicit
`--scope raw` query before reading a source file.

## Design principles (frozen)

1. **Contract-first.** The CLI flags and output schema will not change when the backend swaps.
2. **Transparent degradation.** Stub mode always warns on stderr. Callers treat the stream as authoritative.
3. **Unix-composable.** stdout for data, stderr for meta, exit codes for control flow.
4. **Sentinel mode detection.** `~/.cache/atelier/lance/` present → real mode. Absent → stub. Nothing else.
5. **Encoder-agnostic interface.** BGE, local model encoder, or any future backend all produce `(path, score)` pairs with the same semantics.
6. **Stdlib-only in stub mode.** No dependencies shipped with the interface commit. Real mode deps managed via `pyproject.toml` + `uv`.

## Setup

```bash
uv sync                                    # install deps (venv at ~/.cache/atelier/.venv)
uv run python scripts/atelier/semantic.py index    # build index (~5K files, ~10 min on MPS)
uv run python scripts/atelier/semantic.py query "curiosity vectors"  # search
```

On the active local-routine owner, `com.atelier.semantic-index` runs at 07:30
and 19:30 local time plus `RunAtLoad`. Its deterministic runner is
owner-gated, offline, and invokes `index --if-stale`; no model is loaded when
the corpus is already current. A writer lock prevents overlapping refreshes,
and `caffeinate` plus an epoch timeout bound a real rebuild across macOS sleep.
The index remains a machine-local derived cache.

When a scheduled run updates the index, its `search_efficiency` JSON is
retained in `/tmp/com.atelier.semantic-index.out`. Diagnostics go to the
matching `.err` file.

## Quality stack

`semantic.py` exposes three orthogonal quality knobs on top of the dense retrieval base. They can be combined; the eval harness (`scripts/atelier/semantic_eval.py`) measures Recall@5/10, MRR@10, nDCG@10 against a link-graph-derived gold set.

| Layer | Flag / env | When it helps | Cost |
|---|---|---|---|
| Dense embedder | `SEMANTIC_EMBEDDER=bge-m3` (default), `qwen3-0.6b`, `qwen3-4b`, `qwen3-8b` | Qwen3 narrowly beats BGE-M3 on multilingual link-graph queries; 0.6B is the sweet spot | Each variant gets its own lance dir; rebuild needed when switching |
| BM25 hybrid | `--hybrid` (CLI) | Named-entity / partial-title queries that the dense vector under-ranks | Adds ~5-10s/query for first-call BM25 build; negligible thereafter |
| Cross-encoder rerank | `--rerank ce` or env `SEMANTIC_RERANK_CE=1` | Biggest single nDCG lift across stacks; biggest cost too | ~5-10s/query on MPS; first call downloads ~568M-param model |
| Tier+recency rerank | on by default in `_build_retriever` | UX heuristic: prefers wiki and fresh notes. Hurts pure retrieval metrics by ~3-5pt nDCG when the gold set spans older L2/L3 content | Free |

The eval harness lives at `scripts/atelier/semantic_eval.py`:

```bash
uv run scripts/atelier/semantic_eval.py build                  # rebuild gold set from vault wikilinks/md-links
uv run scripts/atelier/semantic_eval.py run                    # current default active scope
uv run scripts/atelier/semantic_eval.py run --scope all        # historical all-scope comparison
uv run scripts/atelier/semantic_eval.py run --hybrid           # +BM25 RRF
uv run scripts/atelier/semantic_eval.py run --cross-encoder    # +BGE-reranker-v2-m3
uv run scripts/atelier/semantic_eval.py run --no-rerank        # disable TierRecency
SEMANTIC_EMBEDDER=qwen3-0.6b uv run scripts/atelier/semantic_eval.py run --hybrid --cross-encoder
```

The gold set is built only from active authored notes. Evaluation therefore
supports `active` and `all`; deeper single scopes need their own gold-set
contract before they can produce meaningful metrics.

## References

- Backend implementations: `scripts/atelier/semantic_backends.py`
- Local-first architecture: `protocols/local-first-architecture.md`
- Sibling teaching docs: `sources/scholar.md`, `sources/local-papers.md`, `sources/readwise.md`
