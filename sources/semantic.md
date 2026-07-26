# Local Semantic Search (`scripts/semantic.py`)

Teaching doc for the `semantic.py` CLI. Agents and command files call this script to find notes by meaning rather than exact string match.

**This doc describes the contract, not the implementation.** The backend swaps across three stages (stub, BGE-M3, corpus-tuned local model) without changing anything below.

## Modes

**Stub mode** (lexical fallback): active when `~/.cache/atelier/lance/` does not exist. Uses lexical token matching (substring `count`) over the Markdown corpus under `$OV/`. Prints a warning to stderr on every invocation so callers never mistake "empty result" for "no conceptual neighbor exists."

**Real mode** (embedding-backed): active when `~/.cache/atelier/lance/` exists (sentinel). Current stack: dense embedder (BGE-M3 default, Qwen3-Embedding-0.6B / 4B / 8B opt-in via `SEMANTIC_EMBEDDER`) + LanceDB (embedded columnar store, cosine distance) + BM25 sparse retrieval fused via Reciprocal Rank Fusion + optional BGE-reranker-v2-m3 cross-encoder rerank. Documents are chunked at markdown heading boundaries (~2K chars per chunk). Index is machine-local per embedder (`~/.cache/atelier/lance/`, `~/.cache/atelier/lance-qwen3-0.6b/`, ...); rebuild with `uv run scripts/semantic.py index` (~10 min on MPS for 5K-file vault with BGE-M3 / Qwen3-0.6B, ~60 min for Qwen3-4B). No caller code changes across the swap.

Model loading is cache-first. When the Hugging Face cache contains a snapshot
with both the model config and Sentence Transformers modules manifest, the
backend passes that local snapshot directory directly to Sentence Transformers
with `local_files_only=True`. This avoids remote metadata and background model
conversion requests. An uncached model may still download during interactive
setup. `HF_HUB_OFFLINE=1` or `TRANSFORMERS_OFFLINE=1` forces local-only loading
even when no complete snapshot can be resolved.

## CLI

```
scripts/semantic.py query "<text>" [OPTIONS]
scripts/semantic.py status [--format text|json]
scripts/semantic.py corpus [--format text|json]
scripts/semantic.py index [--rebuild | --if-stale]
scripts/semantic.py --help
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

### Freshness and indexing

| Call | Meaning |
|---|---|
| `semantic.py status --format json` | Compare current nonempty Markdown paths and mtimes with the stored index without loading the embedding model. |
| `semantic.py corpus --format json` | Audit scope classification, hard exclusions, raw locator coverage, exact duplicates, and estimated chunks without loading an embedding model. |
| `semantic.py index` | Incrementally update changed paths and remove deleted paths. |
| `semantic.py index --if-stale` | Run the lightweight freshness check first; load the embedding model only when drift exists. Used by scheduled maintenance. |
| `semantic.py index --rebuild` | Clear and rebuild the complete index. Keep this manual. |

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

JSON (`--format json`): a list of objects with `path`, `score`, `source`, and
`matched_tokens`. Add `--context` for bounded capsules with `heading`,
`snippet`, `tier`, `scope`, `representation`, and truncation state.

### Exit codes

- `0` — success (including zero results).
- `0` — `status` completed, whether the index is fresh or stale.
- `0` — `corpus` completed its read-only audit.
- `2` — usage error (bad flag, unparseable date).
- `2` — `status` could not inspect an existing index.

### Streams

- **stdout:** query results or command-specific reports. Query output remains parseable by `xargs`, `awk`, etc.
- **stderr:** mode banner, warnings, diagnostics. Always emitted; callers should not silence stderr.

## When to call this script

| Situation | Call |
|---|---|
| Searching for a specific keyword or title | Use `Grep`, not this script. |
| Searching for a concept that might be phrased many ways | `semantic.py query "<concept>"` |
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

To exit stub mode, run `uv run python scripts/semantic.py index` to build the lance index.

## Examples

Basic query:
```
scripts/semantic.py query "curiosity vectors"
```

Restricted to reflections in the last 30 days, JSON output:
```
scripts/semantic.py query "energy drain" \
    --path "$OV"/reflections \
    --after 2026-03-07 \
    --scope active \
    --context \
    --format json
```

Multiple paths, top 20 hits:
```
scripts/semantic.py query "研究 方向" \
    --path "$OV"/daily-notes \
    --path "$OV"/reflections \
    --top 20
```

Piping into `Read` (for an agent workflow):
```
scripts/semantic.py query "contradiction" --top 5 | \
    cut -f1 | \
    while read path; do echo "--- $path ---"; cat "$path"; done
```

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
uv run python scripts/semantic.py index    # build index (~5K files, ~10 min on MPS)
uv run python scripts/semantic.py query "curiosity vectors"  # search
```

On the active local-routine owner, `com.atelier.semantic-index` runs at 07:30
and 19:30 local time plus `RunAtLoad`. Its deterministic runner is
owner-gated, offline, and invokes `index --if-stale`; no model is loaded when
the corpus is already current. A writer lock prevents overlapping refreshes,
and `caffeinate` plus an epoch timeout bound a real rebuild across macOS sleep.
The index remains a machine-local derived cache.

## Quality stack

`semantic.py` exposes three orthogonal quality knobs on top of the dense retrieval base. They can be combined; the eval harness (`scripts/semantic_eval.py`) measures Recall@5/10, MRR@10, nDCG@10 against a link-graph-derived gold set.

| Layer | Flag / env | When it helps | Cost |
|---|---|---|---|
| Dense embedder | `SEMANTIC_EMBEDDER=bge-m3` (default), `qwen3-0.6b`, `qwen3-4b`, `qwen3-8b` | Qwen3 narrowly beats BGE-M3 on multilingual link-graph queries; 0.6B is the sweet spot | Each variant gets its own lance dir; rebuild needed when switching |
| BM25 hybrid | `--hybrid` (CLI) | Named-entity / partial-title queries that the dense vector under-ranks | Adds ~5-10s/query for first-call BM25 build; negligible thereafter |
| Cross-encoder rerank | `--rerank ce` or env `SEMANTIC_RERANK_CE=1` | Biggest single nDCG lift across stacks; biggest cost too | ~5-10s/query on MPS; first call downloads ~568M-param model |
| Tier+recency rerank | on by default in `_build_retriever` | UX heuristic: prefers wiki and fresh notes. Hurts pure retrieval metrics by ~3-5pt nDCG when the gold set spans older L2/L3 content | Free |

The eval harness lives at `scripts/semantic_eval.py`:

```bash
uv run scripts/semantic_eval.py build                  # rebuild gold set from vault wikilinks/md-links
uv run scripts/semantic_eval.py run                    # current default stack
uv run scripts/semantic_eval.py run --hybrid           # +BM25 RRF
uv run scripts/semantic_eval.py run --cross-encoder    # +BGE-reranker-v2-m3
uv run scripts/semantic_eval.py run --no-rerank        # disable TierRecency
SEMANTIC_EMBEDDER=qwen3-0.6b uv run scripts/semantic_eval.py run --hybrid --cross-encoder
```

## References

- Backend implementations: `scripts/semantic_backends.py`
- Local-first architecture: `protocols/local-first-architecture.md`
- Sibling teaching docs: `sources/scholar.md`, `sources/local-papers.md`, `sources/readwise.md`
