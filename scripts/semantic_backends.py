"""
semantic_backends.py: Abstraction layer for semantic search components.

Three Protocol interfaces define the seams:
  - Embedder: text -> vector
  - Store: upsert / search / delete over indexed documents
  - Reranker: reorder candidates (optional, future)

Concrete implementations live in this file alongside the protocols.
Swapping a component (new model, new DB, new ranker) means writing a new
class that satisfies the Protocol, not touching the CLI or other components.

Current stack: BGE-M3 dense + (BM25 sparse fused via RRF) + cross-encoder
rerank (BGE-reranker-v2-m3) + tier/recency/trust adjustments. Each layer
is a Protocol implementation and can be swapped independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Data types shared across all backends
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """A unit of indexable content."""

    id: str  # "{path}:{chunk_id}"
    path: str  # relative to repo root
    chunk_id: int  # 0 = whole file, 1..N for chunks
    chunk_text: str  # the actual text (stored for re-embedding)
    tier: str  # L1-L5, derived from path prefix
    mtime: float  # file mtime at index time


@dataclass
class SearchResult:
    """A single search hit."""

    path: str
    score: float  # higher is better, [0.0, 1.0] for cosine
    chunk_id: int = 0
    chunk_text: str = ""
    tier: str = ""
    mtime: float = 0.0
    source: str = "local"  # "local" or "readwise"


@dataclass
class IndexStats:
    """Summary of what's in the index."""

    total_documents: int
    total_chunks: int
    embedding_dimension: int
    model_name: str
    index_path: str


# ---------------------------------------------------------------------------
# Protocol: Embedder
# ---------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. Swappable independently of Store."""

    def encode(self, texts: List[str]) -> NDArray[np.float32]:
        """Encode a batch of texts. Returns (N, D) array."""
        ...

    def dimension(self) -> int:
        """Embedding dimensionality."""
        ...

    def model_name(self) -> str:
        """Human-readable model identifier for index metadata."""
        ...


# ---------------------------------------------------------------------------
# Protocol: Store
# ---------------------------------------------------------------------------


@runtime_checkable
class Store(Protocol):
    """Persists and searches document embeddings. Swappable independently."""

    def add(self, docs: List[Document], vectors: NDArray[np.float32]) -> int:
        """Append-only insert (fast path for initial builds). Returns count."""
        ...

    def upsert(self, docs: List[Document], vectors: NDArray[np.float32]) -> int:
        """Insert or update documents. Returns count of upserted rows."""
        ...

    def search(
        self,
        vector: NDArray[np.float32],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Find nearest neighbors. filters keys: path_prefix, tier, mtime_after, mtime_before."""
        ...

    def delete(self, ids: List[str]) -> int:
        """Delete documents by id. Returns count deleted."""
        ...

    def count(self) -> int:
        """Total indexed rows."""
        ...

    def stats(self) -> IndexStats:
        """Index summary."""
        ...

    def clear(self) -> None:
        """Drop all data (for --rebuild)."""
        ...


# ---------------------------------------------------------------------------
# Protocol: Reranker (future seam, not implemented day-one)
# ---------------------------------------------------------------------------


@runtime_checkable
class Reranker(Protocol):
    """Reorders search candidates. Optional pipeline stage."""

    def rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_k: int = 10,
    ) -> List[SearchResult]: ...


# ---------------------------------------------------------------------------
# Concrete: TierRecencyReranker
# ---------------------------------------------------------------------------

# Tier boosts: a gentle preference for higher-certified tiers when a tie or
# near-tie occurs after cosine retrieval. Earlier versions used 1.20/0.70
# multipliers which crushed L2 results (most of the vault) on link-graph
# eval queries; the magnitudes here are calibrated so the boost acts as a
# tie-breaker, not a dominant ranking signal.
TIER_BOOST = {
    "L4": 1.08,  # wiki: certified knowledge
    "L3": 1.04,  # papers / readwise: externally certified
    "L2": 1.00,  # working notes: baseline
    "L1": 0.92,  # raw capture / cache: low signal but still searchable
}

# Recency half-life in days, by tier. None = no decay (knowledge is durable).
# L2 used to decay on a 90-day half-life which severely demoted older but
# still-valid notes (reflections, research) — disabled by default.
TIER_HALF_LIFE = {
    "L4": None,
    "L3": None,
    "L2": None,  # working notes do not decay; user controls staleness via /forget
    "L1": 180,  # raw capture decays slowly
}


class TierRecencyReranker:
    """
    Reranks search results by combining cosine similarity with:
    1. Tier boost (L4 > L3 > L2 > L1)
    2. Recency decay (exponential half-life, L2/L1 only)
    3. TrustRank score (wiki entries, loaded lazily from trust.py)

    Final score = cosine * tier_boost * recency_factor + trust_bonus
    """

    def __init__(self, trust_scores: Optional[Dict[str, float]] = None) -> None:
        self._trust_scores = trust_scores or {}

    @staticmethod
    def _recency_factor(mtime: float, tier: str) -> float:
        """Exponential decay based on tier-specific half-life."""
        import time as _time
        import math

        half_life = TIER_HALF_LIFE.get(tier)
        if half_life is None:
            return 1.0

        age_days = (_time.time() - mtime) / 86400
        if age_days <= 0:
            return 1.0

        return math.pow(0.5, age_days / half_life)

    def rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_k: int = 10,
    ) -> List[SearchResult]:
        scored = []
        for r in candidates:
            tier = r.tier or "L2"
            boost = TIER_BOOST.get(tier, 1.0)
            recency = self._recency_factor(r.mtime, tier)
            trust_bonus = (
                self._trust_scores.get(r.path, 0.0) * 0.1
            )  # scale trust to ~0-0.1
            final = r.score * boost * recency + trust_bonus
            scored.append((final, r))

        scored.sort(key=lambda x: -x[0])
        # replace() keeps every other field (mtime, source, ...) intact;
        # rebuilding by hand silently dropped fields as the dataclass grew.
        return [
            replace(r, score=round(final_score, 4)) for final_score, r in scored[:top_k]
        ]


# ---------------------------------------------------------------------------
# Retriever: orchestrates the pipeline
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,4})\s", re.MULTILINE)
CHUNK_TARGET = (
    2000  # chars; BGE-M3 handles up to ~8K tokens but shorter chunks retrieve better
)
CHUNK_MAX = 4000  # hard cap; chunks above this are split on paragraph boundaries
CHUNK_MIN = 200  # don't create tiny fragments


def _split_long(text: str, limit: int) -> List[str]:
    """Split text that exceeds limit on double-newline (paragraph) boundaries.
    Falls back to single-newline, then hard truncation."""
    # Try double-newline first
    paragraphs = re.split(r"\n\n+", text)
    if len(paragraphs) == 1:
        # No double newlines; try single newlines
        paragraphs = text.split("\n")

    chunks: List[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > limit:
            chunks.append(buf)
            buf = para
        else:
            buf = buf + "\n\n" + para if buf else para
    if buf:
        chunks.append(buf)

    # Hard truncation: split any still-oversized chunks by character
    final: List[str] = []
    for chunk in chunks or [text]:
        while len(chunk) > limit:
            final.append(chunk[:limit])
            chunk = chunk[limit:]
        if chunk:
            final.append(chunk)
    return final


def chunk_markdown(text: str) -> List[str]:
    """
    Split markdown into chunks on heading boundaries.

    Strategy: split at ## / ### / #### headings, then merge small sections
    until each chunk is near CHUNK_TARGET chars. Chunks that still exceed
    CHUNK_MAX are further split on paragraph boundaries. Files under
    CHUNK_TARGET are returned as a single chunk.
    """
    if len(text) <= CHUNK_TARGET:
        return [text]

    splits: List[str] = []
    last = 0
    for m in _HEADING_RE.finditer(text):
        if m.start() > last:
            splits.append(text[last : m.start()])
        last = m.start()
    if last < len(text):
        splits.append(text[last:])

    merged: List[str] = []
    buf = ""
    for section in splits:
        if buf and len(buf) + len(section) > CHUNK_TARGET:
            merged.append(buf)
            buf = section
        else:
            buf += section
    if buf:
        merged.append(buf)

    if len(merged) >= 2 and len(merged[-1]) < CHUNK_MIN:
        merged[-2] = merged[-2] + merged[-1]
        merged.pop()

    capped: List[str] = []
    for chunk in merged:
        if len(chunk) > CHUNK_MAX:
            capped.extend(_split_long(chunk, CHUNK_MAX))
        else:
            capped.append(chunk)
    return capped


# ---------------------------------------------------------------------------
# Tier derivation
# ---------------------------------------------------------------------------


def _derive_tier(path: str) -> str:
    """Derive knowledge tier from path prefix.

    Indexed paths are stored vault-relative (e.g., `wiki/Foo.md`). Pre-rename
    indexes used to store them with a `zk/` prefix (e.g., `zk/wiki/Foo.md`);
    we still see those for installs that have not rebuilt the index since
    the rename. Strip a leading `zk/` if present, then look up the tier by
    the next path component. After every legacy index has been rebuilt
    against vault-relative paths, the `zk` special-case can be removed.
    """
    parts = path.split("/")
    if len(parts) < 2:
        return "L2"
    subdir = parts[1] if parts[0] == "zk" else parts[0]
    return _segment_tier_map().get(subdir, "L2")


# Knowledge level by registry *logical name* (stable; CLAUDE.md § Knowledge
# Layers). Segments come from harness/paths.toml at runtime so a tier rename
# (e.g. drafts -> wip) propagates here automatically. Unlisted names are L2.
_TIER_LEVEL_BY_NAME = {
    "wiki": "L4",
    "papers": "L3",
    "preprints": "L3",
    "cache": "L1",
}

_segment_tier_cache: Optional[Dict[str, str]] = None


def _segment_tier_map() -> Dict[str, str]:
    """Return {top-level segment: knowledge level} derived from the path
    registry. Falls back to a minimal static map if _paths is unavailable
    (e.g. this module imported outside the repo)."""
    global _segment_tier_cache
    if _segment_tier_cache is not None:
        return _segment_tier_cache
    # Readwise is an indexed L1 surface but cloud-only, not a registry tier.
    mapping: Dict[str, str] = {"readwise": "L1"}
    try:
        from _paths import tier_segments, vault_root, wiki_dirs

        for name, seg in tier_segments().items():
            top = seg.split("/")[0]
            level = _TIER_LEVEL_BY_NAME.get(name, "L2")
            if level != "L2" or top not in mapping:
                mapping[top] = level
        root = vault_root()
        for wd in wiki_dirs():
            try:
                mapping[wd.relative_to(root).parts[0]] = "L4"
            except ValueError:
                pass
    except Exception:
        mapping.update({"wiki": "L4", "papers": "L3", "preprints": "L3", "cache": "L1"})
    _segment_tier_cache = mapping
    return mapping


class Retriever:
    """
    Orchestrates Embedder + Store + optional Reranker.

    This is the single entry point that semantic.py calls. The retriever
    does NOT know which embedder, store, or reranker it's using. It just
    calls their Protocol methods.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: Store,
        reranker: Optional[Reranker] = None,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.reranker = reranker

    def index_files(
        self,
        files: Sequence[Path],
        repo_root: Path,
        batch_size: int = 64,
        show_progress: bool = True,
        append_only: bool = False,
    ) -> int:
        """
        Chunk, embed, and index a sequence of markdown files.
        Returns total chunks indexed.

        append_only=True uses fast add() instead of merge_insert upsert.
        Use after clear() for full rebuilds.
        """
        import sys

        write_fn = self.store.add if append_only else self.store.upsert
        total = 0
        batch_docs: List[Document] = []
        batch_texts: List[str] = []
        file_list = list(files)
        n_files = len(file_list)

        for i, fpath in enumerate(file_list):
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if not text.strip():
                continue

            try:
                rel = str(fpath.relative_to(repo_root))
            except ValueError:
                rel = str(fpath)

            tier = _derive_tier(rel)
            mtime = fpath.stat().st_mtime
            chunks = chunk_markdown(text)

            for ci, chunk_text in enumerate(chunks):
                doc = Document(
                    id=f"{rel}:{ci}",
                    path=rel,
                    chunk_id=ci,
                    chunk_text=chunk_text,
                    tier=tier,
                    mtime=mtime,
                )
                batch_docs.append(doc)
                batch_texts.append(chunk_text)

            if len(batch_docs) >= batch_size:
                vectors = self.embedder.encode(batch_texts)
                total += write_fn(batch_docs, vectors)
                if show_progress:
                    print(
                        f"\r  [{i + 1}/{n_files}] indexed {total} chunks",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                batch_docs.clear()
                batch_texts.clear()

        # flush remaining
        if batch_docs:
            vectors = self.embedder.encode(batch_texts)
            total += write_fn(batch_docs, vectors)

        if show_progress:
            print(
                f"\r  [{n_files}/{n_files}] indexed {total} chunks",
                file=sys.stderr,
            )

        return total

    def index_incremental(
        self,
        files: Sequence[Path],
        repo_root: Path,
        batch_size: int = 64,
        show_progress: bool = True,
    ) -> tuple[int, int, int]:
        """
        Incremental index: only process files whose mtime changed.
        Removes stale entries for deleted files.
        Returns (added, skipped, removed).
        """
        import sys

        indexed = self.store.get_indexed_mtimes()
        file_list = list(files)

        # Determine which files need re-indexing
        current_paths = set()
        to_index: List[Path] = []
        to_index_rel: List[str] = []
        for fpath in file_list:
            try:
                rel = str(fpath.relative_to(repo_root))
            except ValueError:
                rel = str(fpath)
            current_paths.add(rel)
            current_mtime = fpath.stat().st_mtime
            indexed_mtime = indexed.get(rel, 0.0)
            # Epsilon of 1s avoids false positives from Drive sync touching mtimes
            if current_mtime - indexed_mtime > 1.0:
                to_index.append(fpath)
                to_index_rel.append(rel)

        # Remove entries for deleted files
        stale = [p for p in indexed if p not in current_paths]
        removed = 0
        if stale:
            removed = self.store.delete_by_path(stale)
            if show_progress:
                print(f"  removed {removed} stale entries", file=sys.stderr)

        skipped = len(file_list) - len(to_index)
        if not to_index:
            if show_progress:
                print(
                    f"  index is up to date ({skipped} files unchanged)",
                    file=sys.stderr,
                )
            return 0, skipped, removed

        if show_progress:
            print(
                f"  {len(to_index)} files changed, {skipped} unchanged",
                file=sys.stderr,
            )

        # A changed file may now chunk to fewer pieces than its indexed copy;
        # upsert alone would leave the old trailing chunks searchable. Drop the
        # file's old chunks first.
        prior = [rel for rel in to_index_rel if rel in indexed]
        if prior:
            self.store.delete_by_path(prior)

        added = self.index_files(to_index, repo_root, batch_size, show_progress)
        return added, skipped, removed

    def query(
        self,
        text: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Embed query, search store, optionally rerank.

        Embedders that expose `encode_query` (e.g. instruction-tuned Qwen3)
        get the query-side prompt; symmetric encoders fall through to
        `encode` which is what the corpus side used at index time.
        """
        encode_query = getattr(self.embedder, "encode_query", None)
        encoder = encode_query if callable(encode_query) else self.embedder.encode
        vector = encoder([text])[0]
        candidate_k = top_k * 4 if self.reranker else top_k
        results = self.store.search(vector, top_k=candidate_k, filters=filters)

        if self.reranker:
            results = self.reranker.rerank(text, results, top_k=top_k)

        return results[:top_k]

    def stats(self) -> IndexStats:
        return self.store.stats()


# ---------------------------------------------------------------------------
# Hybrid retrieval: BM25 (sparse) fused with dense via Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

# BM25 over indexed chunk_text. The sparse index is built lazily once per
# process from the LanceStore contents (so it stays consistent with the dense
# index without a separate persisted file). RRF combines the two ranked
# lists; it's parameter-light and robust to score scale differences.

RRF_K = 60  # Reciprocal Rank Fusion constant; 60 is the standard default.


class _BM25Index:
    """Lightweight BM25Okapi index built from a Store's stored chunks.

    Tokenization is intentionally simple (regex word/CJK split, lowercased).
    The goal is not search-engine-grade BM25 but a complementary signal to
    the dense embedder for keyword-heavy and named-entity queries that the
    embedder sometimes ranks below paraphrastic neighbors.
    """

    _TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]+")

    def __init__(self) -> None:
        self._bm25 = None
        self._meta: List[Dict[str, Any]] = []
        self._built = False

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """Tokenize a string into BM25 tokens.

        For Latin words / numbers: lowercased word forms.
        For CJK runs: emit overlapping bigrams plus each character. Bigrams
        capture short-phrase semantics ("强化 → 强化学/化学习" for "强化学习")
        while unigrams keep recall for one-char terms. This is a lightweight
        substitute for a full Chinese segmenter (jieba) which would add an
        extra dependency.
        """
        out: List[str] = []
        for tok in cls._TOKEN_RE.findall(text or ""):
            if "一" <= tok[0] <= "鿿":
                if len(tok) == 1:
                    out.append(tok)
                else:
                    for i in range(len(tok)):
                        out.append(tok[i])
                        if i + 1 < len(tok):
                            out.append(tok[i : i + 2])
            else:
                out.append(tok.lower())
        return out

    def build(self, store: "LanceStore") -> None:
        from rank_bm25 import BM25Okapi

        df = store._table.to_pandas()  # noqa: SLF001 (BM25 needs full corpus)
        corpus_tokens: List[List[str]] = []
        meta: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            tokens = self._tokenize(row.get("chunk_text", ""))
            if not tokens:
                continue
            corpus_tokens.append(tokens)
            meta.append(
                {
                    "path": row.get("path", ""),
                    "chunk_id": int(row.get("chunk_id", 0)),
                    "chunk_text": row.get("chunk_text", ""),
                    "tier": row.get("tier", ""),
                    "mtime": float(row.get("mtime", 0.0)),
                }
            )
        self._bm25 = BM25Okapi(corpus_tokens)
        self._meta = meta
        self._built = True

    def search(self, query: str, top_k: int = 50) -> List[SearchResult]:
        if not self._built or self._bm25 is None:
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        # Partial top-k via argpartition
        n = min(top_k, len(scores))
        if n == 0:
            return []
        idx = np.argpartition(-scores, n - 1)[:n]
        idx = idx[np.argsort(-scores[idx])]
        results: List[SearchResult] = []
        for i in idx:
            s = float(scores[i])
            if s <= 0:
                continue
            m = self._meta[i]
            results.append(
                SearchResult(
                    path=m["path"],
                    score=s,
                    chunk_id=m["chunk_id"],
                    chunk_text=m["chunk_text"],
                    tier=m["tier"],
                    mtime=m["mtime"],
                    source="local",
                )
            )
        return results


_BM25_SINGLETON: Optional[_BM25Index] = None


def _get_bm25(store: "LanceStore") -> _BM25Index:
    global _BM25_SINGLETON
    if _BM25_SINGLETON is None:
        idx = _BM25Index()
        idx.build(store)
        _BM25_SINGLETON = idx
    return _BM25_SINGLETON


def _rrf_fuse(
    dense: List[SearchResult],
    sparse: List[SearchResult],
    *,
    k: int = RRF_K,
) -> List[SearchResult]:
    """Reciprocal Rank Fusion over two ranked lists keyed by document id.

    fused_score(d) = sum over each list L containing d of 1/(k + rank_L(d))
    """
    fused: Dict[Tuple[str, int], float] = {}
    keep: Dict[Tuple[str, int], SearchResult] = {}
    for rank, r in enumerate(dense):
        key = (r.path, r.chunk_id)
        fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
        keep[key] = r
    for rank, r in enumerate(sparse):
        key = (r.path, r.chunk_id)
        fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
        keep.setdefault(key, r)
    ordered = sorted(fused.items(), key=lambda kv: -kv[1])
    out: List[SearchResult] = []
    for key, score in ordered:
        r = keep[key]
        out.append(
            SearchResult(
                path=r.path,
                score=round(score, 6),
                chunk_id=r.chunk_id,
                chunk_text=r.chunk_text,
                tier=r.tier,
                mtime=r.mtime,
                source=r.source,
            )
        )
    return out


class HybridRetriever:
    """
    Wraps a dense Retriever and fuses results with BM25 via RRF.

    The dense retriever's reranker (if any) is bypassed for the candidate
    pool: we want unranked dense top-N, fuse with sparse top-N, then let
    the dense retriever's reranker (or a downstream cross-encoder) reorder
    the fused list.
    """

    def __init__(
        self,
        base: Retriever,
        *,
        candidate_k: int = 50,
        rrf_k: int = RRF_K,
    ) -> None:
        self._base = base
        self._candidate_k = candidate_k
        self._rrf_k = rrf_k

    @property
    def store(self) -> Any:
        return self._base.store

    @property
    def embedder(self) -> Any:
        return self._base.embedder

    def query(
        self,
        text: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        # Dense candidates (skip the base reranker; we'll rerank after fusion)
        encode_query = getattr(self._base.embedder, "encode_query", None)
        encoder = encode_query if callable(encode_query) else self._base.embedder.encode
        vector = encoder([text])[0]
        dense = self._base.store.search(
            vector, top_k=self._candidate_k, filters=filters
        )
        # Sparse candidates (BM25 doesn't support `filters` yet — applies to whole corpus)
        sparse = _get_bm25(self._base.store).search(text, top_k=self._candidate_k)
        # Filter sparse hits through the same filter set if filters are present
        if filters:
            sparse = [r for r in sparse if _passes_filters(r, filters)]
        fused = _rrf_fuse(dense, sparse, k=self._rrf_k)
        if self._base.reranker:
            fused = self._base.reranker.rerank(text, fused, top_k=top_k)
        return fused[:top_k]

    def stats(self) -> IndexStats:
        return self._base.stats()


def _passes_filters(r: SearchResult, filters: Dict[str, Any]) -> bool:
    if "path_prefix" in filters:
        prefix = filters["path_prefix"]
        prefixes = prefix if isinstance(prefix, list) else [prefix]
        # Directory-boundary match: a "wiki" filter must not also match the
        # sibling "wiki-cn/" localized shadow. Match the path exactly or as a
        # "<prefix>/" directory child.
        if not any(r.path == p or r.path.startswith(p + "/") for p in prefixes):
            return False
    if "tier" in filters and r.tier != filters["tier"]:
        return False
    if "mtime_after" in filters and r.mtime < filters["mtime_after"]:
        return False
    if "mtime_before" in filters and r.mtime > filters["mtime_before"]:
        return False
    return True


# ---------------------------------------------------------------------------
# Cross-encoder reranker (BGE-reranker-v2-m3)
# ---------------------------------------------------------------------------


class CrossEncoderReranker:
    """
    Reranks candidates by scoring each (query, chunk_text) pair with a
    cross-encoder. Cross-encoders are slower than bi-encoder retrieval but
    consistently lift nDCG / MRR when applied to a top-N candidate set.

    Default model: BAAI/bge-reranker-v2-m3 (~568M params, multilingual,
    MPS-friendly). Loaded lazily and cached at module scope so repeated
    queries in the same process don't re-pay model load cost.
    """

    MODEL_ID = "BAAI/bge-reranker-v2-m3"

    _cached_model: Optional[Any] = None
    _cached_device: Optional[str] = None

    def __init__(
        self, model_id: Optional[str] = None, device: Optional[str] = None
    ) -> None:
        from config import resolve_device

        self._model_id = model_id or self.MODEL_ID
        self._device = device or resolve_device("auto")
        self._max_length = 1024

    def _model(self) -> Any:
        if (
            CrossEncoderReranker._cached_model is not None
            and CrossEncoderReranker._cached_device == self._device
        ):
            return CrossEncoderReranker._cached_model
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(
            self._model_id, max_length=self._max_length, device=self._device
        )
        CrossEncoderReranker._cached_model = model
        CrossEncoderReranker._cached_device = self._device
        return model

    def rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_k: int = 10,
    ) -> List[SearchResult]:
        if not candidates:
            return candidates
        model = self._model()
        pairs = [(query, c.chunk_text or c.path) for c in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: -float(x[1]))
        out: List[SearchResult] = []
        for c, s in scored[:top_k]:
            out.append(
                SearchResult(
                    path=c.path,
                    score=float(s),
                    chunk_id=c.chunk_id,
                    chunk_text=c.chunk_text,
                    tier=c.tier,
                    mtime=c.mtime,
                    source=c.source,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Concrete: BGE-M3 Embedder
# ---------------------------------------------------------------------------


def _local_model_snapshot(model_id: str) -> Optional[str]:
    """Resolve a complete Hugging Face snapshot without importing hub code."""
    import os
    from pathlib import Path

    direct = Path(model_id).expanduser()
    if direct.is_dir():
        return str(direct.resolve())
    cache_override = os.environ.get("HF_HUB_CACHE")
    if cache_override:
        hub = Path(cache_override).expanduser()
    else:
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            hub = Path(hf_home).expanduser() / "hub"
        else:
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            cache_root = (
                Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
            )
            hub = cache_root / "huggingface" / "hub"
    repository = hub / f"models--{model_id.replace('/', '--')}"
    snapshots = repository / "snapshots"
    candidates: list[Path] = []
    main_ref = repository / "refs" / "main"
    try:
        revision = main_ref.read_text(encoding="utf-8").strip()
    except OSError:
        revision = ""
    if revision and "/" not in revision and ".." not in revision:
        candidates.append(snapshots / revision)
    if snapshots.is_dir():
        try:
            discovered = sorted(
                (path for path in snapshots.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            discovered = []
        candidates.extend(path for path in discovered if path not in candidates)
    required = ("config.json", "modules.json")
    for snapshot in candidates:
        if all((snapshot / filename).is_file() for filename in required):
            return str(snapshot.resolve())
    return None


def _sentence_transformer_source(model_id: str) -> tuple[str, bool]:
    """Return a local snapshot when available, else the download-capable ID."""
    import os

    snapshot = _local_model_snapshot(model_id)
    if snapshot is not None:
        return snapshot, True
    offline = (
        os.environ.get("HF_HUB_OFFLINE") == "1"
        or os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    )
    return model_id, offline


class BGEM3Embedder:
    """
    Embedder backed by BAAI/bge-m3 via sentence-transformers.

    BGE-M3 is multilingual (100+ languages including Chinese and English),
    produces 1024-dim dense vectors, and supports up to 8192 tokens.

    Device-dependent parameters (max_tokens, encode_batch_size, device)
    are loaded from semantic.toml. See scripts/config.py for defaults.
    """

    MODEL_ID = "BAAI/bge-m3"
    DIMENSION = 1024

    def __init__(
        self,
        device: Optional[str] = None,
        max_tokens: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer
        from config import load, resolve_device

        cfg = load()
        resolved_device = device or resolve_device(cfg["device"])
        self._max_tokens = max_tokens or cfg["max_tokens"]
        self._batch_size = batch_size or cfg["encode_batch_size"]
        self._device = resolved_device
        model_source, local_only = _sentence_transformer_source(self.MODEL_ID)
        self._model = SentenceTransformer(
            model_source,
            device=resolved_device,
            local_files_only=local_only,
        )
        self._model.max_seq_length = self._max_tokens

    def encode(self, texts: List[str]) -> NDArray[np.float32]:
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=self._batch_size,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def dimension(self) -> int:
        return self.DIMENSION

    def model_name(self) -> str:
        return self.MODEL_ID


class Qwen3Embedder:
    """
    Embedder backed by Qwen3-Embedding via sentence-transformers.

    Qwen3-Embedding is instruction-tuned: query-side inputs are prefixed with
    a task description ("Instruct: Given a web search query, retrieve relevant
    passages that answer the query\\nQuery:"), document-side inputs are bare.
    Sentence-Transformers exposes this via `prompts={query, document}`;
    `encode_query` applies the query prompt, `encode` (used at indexing time)
    treats input as documents.

    Variants:
        Qwen/Qwen3-Embedding-0.6B  (1024 dim)
        Qwen/Qwen3-Embedding-4B    (2560 dim)
        Qwen/Qwen3-Embedding-8B    (4096 dim)
    """

    _DIM = {
        "Qwen/Qwen3-Embedding-0.6B": 1024,
        "Qwen/Qwen3-Embedding-4B": 2560,
        "Qwen/Qwen3-Embedding-8B": 4096,
    }

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-Embedding-0.6B",
        device: Optional[str] = None,
        max_tokens: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer
        from config import load, resolve_device

        cfg = load()
        resolved_device = device or resolve_device(cfg["device"])
        self._model_id = model_id
        self._dimension = self._DIM.get(model_id, 1024)
        self._max_tokens = max_tokens or cfg["max_tokens"]
        self._batch_size = batch_size or cfg["encode_batch_size"]
        self._device = resolved_device
        model_source, local_only = _sentence_transformer_source(model_id)
        self._model = SentenceTransformer(
            model_source,
            device=resolved_device,
            local_files_only=local_only,
        )
        self._model.max_seq_length = self._max_tokens

    def encode(self, texts: List[str]) -> NDArray[np.float32]:
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=self._batch_size,
            prompt_name="document",
        )
        return np.asarray(embeddings, dtype=np.float32)

    def encode_query(self, texts: List[str]) -> NDArray[np.float32]:
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=self._batch_size,
            prompt_name="query",
        )
        return np.asarray(embeddings, dtype=np.float32)

    def dimension(self) -> int:
        return self._dimension

    def model_name(self) -> str:
        return self._model_id


def make_embedder(name: Optional[str] = None):
    """Factory: pick an Embedder by short name or env var.

    Resolves in priority order: explicit `name`, SEMANTIC_EMBEDDER env var,
    default 'bge-m3'.
    """
    import os

    sel = (name or os.environ.get("SEMANTIC_EMBEDDER") or "bge-m3").lower()
    if sel in ("bge-m3", "bgem3", ""):
        return BGEM3Embedder()
    if sel in ("qwen3-0.6b", "qwen3", "qwen-0.6b"):
        return Qwen3Embedder("Qwen/Qwen3-Embedding-0.6B")
    if sel in ("qwen3-4b", "qwen-4b"):
        return Qwen3Embedder("Qwen/Qwen3-Embedding-4B")
    if sel in ("qwen3-8b", "qwen-8b"):
        return Qwen3Embedder("Qwen/Qwen3-Embedding-8B")
    raise ValueError(f"unknown embedder: {sel}")


# ---------------------------------------------------------------------------
# Concrete: LanceDB Store
# ---------------------------------------------------------------------------


def read_lance_index_mtimes(
    db_path: str,
    table_name: str = "semantic_index",
) -> Optional[Dict[str, float]]:
    """Read indexed path mtimes without constructing an embedding model.

    Returns ``None`` when the database exists but the semantic table does not.
    Other read failures are raised so callers can distinguish an unavailable or
    corrupt index from a legitimately empty table.
    """
    import lancedb

    db = lancedb.connect(db_path)
    if table_name not in db.table_names():
        return None
    table = db.open_table(table_name)
    row_count = table.count_rows()
    if row_count == 0:
        return {}
    frame = table.search().select(["path", "mtime"]).limit(row_count).to_pandas()
    grouped = frame.groupby("path")["mtime"].max()
    return {str(path): float(mtime) for path, mtime in grouped.items()}


class LanceStore:
    """
    Store backed by LanceDB (embedded, Lance columnar format).

    Index lives at a directory path (e.g., ~/.cache/atelier/lance/).
    No server process. Files on disk.
    """

    TABLE_NAME = "semantic_index"

    def __init__(self, db_path: str, embedding_dim: int, model_name: str = "") -> None:
        import lancedb

        self._db_path = db_path
        self._embedding_dim = embedding_dim
        self._model_name = model_name
        self._db = lancedb.connect(db_path)

        # Ensure table exists
        self._table = self._ensure_table()

    def _ensure_table(self) -> Any:
        """Create table if it doesn't exist, or open it."""
        import pyarrow as pa

        existing = self._db.table_names()
        if self.TABLE_NAME in existing:
            return self._db.open_table(self.TABLE_NAME)

        schema = pa.schema(
            [
                pa.field("id", pa.utf8()),
                pa.field("path", pa.utf8()),
                pa.field("chunk_id", pa.int32()),
                pa.field("chunk_text", pa.utf8()),
                pa.field("tier", pa.utf8()),
                pa.field("mtime", pa.float64()),
                pa.field("vector", pa.list_(pa.float32(), self._embedding_dim)),
            ]
        )
        return self._db.create_table(self.TABLE_NAME, schema=schema)

    def _to_rows(
        self, docs: List[Document], vectors: NDArray[np.float32]
    ) -> List[Dict[str, Any]]:
        return [
            {
                "id": doc.id,
                "path": doc.path,
                "chunk_id": doc.chunk_id,
                "chunk_text": doc.chunk_text,
                "tier": doc.tier,
                "mtime": doc.mtime,
                "vector": vec.tolist(),
            }
            for doc, vec in zip(docs, vectors)
        ]

    def add(self, docs: List[Document], vectors: NDArray[np.float32]) -> int:
        """Append-only insert (fast path for initial builds)."""
        if not docs:
            return 0
        self._table.add(self._to_rows(docs, vectors))
        return len(docs)

    def upsert(self, docs: List[Document], vectors: NDArray[np.float32]) -> int:
        """Insert or update documents using LanceDB's native merge_insert."""
        if not docs:
            return 0
        (
            self._table.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(self._to_rows(docs, vectors))
        )
        return len(docs)

    @staticmethod
    def _q(value: str) -> str:
        """Escape a value for embedding in a double-quoted filter literal."""
        return str(value).replace('"', '""')

    @staticmethod
    def _warn(op: str, exc: Exception) -> None:
        """A failed index operation must be visible: silently returning the
        degraded value ([] / 0) reads as 'no results', which violates the
        'if search returns nothing, say so' contract.

        The catch-all `except Exception` at the call sites is deliberate:
        lancedb's exception taxonomy is not stable across versions, so the
        contract here is visibility (warn + degrade), not type narrowing."""
        import sys

        print(
            f"  warning: lance {op} failed ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )

    def search(
        self,
        vector: NDArray[np.float32],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        query = self._table.search(vector.tolist()).metric("cosine").limit(top_k)

        # Build filter string for LanceDB
        where_clauses = []
        if filters:
            if "path_prefix" in filters:
                prefix = filters["path_prefix"]
                # Directory-boundary match (exact or "<prefix>/" child) so a
                # "wiki" filter does not also match the sibling "wiki-cn/"
                # localized shadow. See _passes_filters for the in-memory twin.
                if isinstance(prefix, list):
                    parts = [
                        f'(path = "{self._q(p)}" OR path LIKE "{self._q(p)}/%")'
                        for p in prefix
                    ]
                    where_clauses.append(f"({' OR '.join(parts)})")
                else:
                    where_clauses.append(
                        f'(path = "{self._q(prefix)}" OR path LIKE "{self._q(prefix)}/%")'
                    )
            if "tier" in filters:
                where_clauses.append(f'tier = "{self._q(filters["tier"])}"')
            if "mtime_after" in filters:
                where_clauses.append(f"mtime >= {filters['mtime_after']}")
            if "mtime_before" in filters:
                where_clauses.append(f"mtime <= {filters['mtime_before']}")

        if where_clauses:
            query = query.where(" AND ".join(where_clauses))

        try:
            results_df = query.to_pandas()
        except Exception as exc:
            self._warn("search", exc)
            return []

        results = []
        for _, row in results_df.iterrows():
            # cosine _distance: 0.0 = identical, 1.0 = orthogonal
            distance = row.get("_distance", 0.0)
            score = max(0.0, 1.0 - distance)
            results.append(
                SearchResult(
                    path=row["path"],
                    score=round(score, 4),
                    chunk_id=int(row.get("chunk_id", 0)),
                    chunk_text=row.get("chunk_text", ""),
                    tier=row.get("tier", ""),
                    mtime=float(row.get("mtime", 0.0)),
                )
            )

        return results

    def delete(self, ids: List[str]) -> int:
        if not ids:
            return 0
        id_filter = " OR ".join(f'id = "{self._q(doc_id)}"' for doc_id in ids)
        try:
            self._table.delete(id_filter)
            return len(ids)
        except Exception as exc:
            self._warn("delete", exc)
            return 0

    def get_indexed_mtimes(self) -> Dict[str, float]:
        """Return {path: max_mtime} for all indexed documents."""
        import sys

        try:
            return (
                read_lance_index_mtimes(
                    self._db_path,
                    self.TABLE_NAME,
                )
                or {}
            )
        except Exception as exc:
            print(
                f"  warning: could not read indexed mtimes "
                f"({type(exc).__name__}: {exc}); treating index as empty — "
                "every file will be re-embedded and deleted-file cleanup is skipped",
                file=sys.stderr,
            )
            return {}

    def delete_by_path(self, paths: List[str]) -> int:
        """Delete all chunks for the given file paths."""
        if not paths:
            return 0
        path_filter = " OR ".join(f'path = "{self._q(p)}"' for p in paths)
        try:
            self._table.delete(path_filter)
            return len(paths)
        except Exception as exc:
            self._warn("delete_by_path", exc)
            return 0

    def count(self) -> int:
        try:
            return self._table.count_rows()
        except Exception as exc:
            self._warn("count", exc)
            return 0

    def stats(self) -> IndexStats:
        return IndexStats(
            total_documents=self.count(),
            total_chunks=self.count(),
            embedding_dimension=self._embedding_dim,
            model_name=self._model_name,
            index_path=self._db_path,
        )

    def clear(self) -> None:
        """Drop and recreate the table."""
        try:
            self._db.drop_table(self.TABLE_NAME)
        except Exception:
            pass
        self._table = self._ensure_table()


# ---------------------------------------------------------------------------
# Concrete: Readwise Searcher (federated query source)
# ---------------------------------------------------------------------------


class ReadwiseSearcher:
    """
    Searches the user's Readwise library via CLI.

    Not an Embedder or Store; this is a standalone search source that
    the Retriever merges with local results during federated queries.
    """

    @staticmethod
    def available() -> bool:
        """Check if the readwise CLI is installed."""
        import shutil

        return shutil.which("readwise") is not None

    @staticmethod
    def search(query: str, top_k: int = 10) -> List[SearchResult]:
        """Search Readwise and return normalized SearchResults."""
        import json
        import subprocess

        try:
            proc = subprocess.run(
                ["readwise", "reader-search-documents", "--query", query, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return []
            docs = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

        results: List[SearchResult] = []
        for rank, doc in enumerate(docs[:top_k]):
            # Rank-based scoring calibrated to local cosine range (~0.3-0.6).
            # Top result gets 0.6, decays to ~0.3 over 10 results.
            score = max(0.25, 0.6 - rank * 0.035)

            # Use first match chunk as the representative text
            chunk_text = ""
            if doc.get("matches"):
                chunk_text = doc["matches"][0].get("plaintext", "")[:500]

            title = doc.get("title", "")
            path = f"readwise://{doc.get('document_id', '')}"

            results.append(
                SearchResult(
                    path=path,
                    score=round(score, 4),
                    chunk_id=0,
                    chunk_text=f"[{title}] {chunk_text}" if title else chunk_text,
                    tier="L3",
                    source="readwise",
                )
            )

        return results
