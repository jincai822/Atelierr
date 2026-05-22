#!/usr/bin/env python3
"""
semantic_eval.py: Offline evaluation harness for `semantic.py`.

Builds a gold set from the vault itself by harvesting wikilinks
(`[[Target]]` / `[[Target|Display]]`) and GitHub-style links
(`[Display](<relative.md>)`) whose targets resolve to a file under `$OV/`.
For each link we record:

    query    = the sentence containing the link, with the link text removed
    target   = relative path of the linked file (vault-relative)
    anchor   = the display/anchor text (alternate single-token query)

Metrics computed over the gold set:

    Recall@5 / Recall@10
    MRR@10
    nDCG@10

Run:
    uv run scripts/semantic_eval.py build     # write gold set to scripts/_evalset.json
    uv run scripts/semantic_eval.py run       # evaluate current Retriever against gold set
    uv run scripts/semantic_eval.py run --no-rerank   # disable TierRecencyReranker
    uv run scripts/semantic_eval.py run --hybrid      # turn hybrid retrieval on
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _paths import vault_root  # type: ignore[import-not-found]  # noqa: E402

GOLD_PATH = REPO_ROOT / "scripts" / "_evalset.json"

# Wikilinks of the form [[Target]] or [[Target|Display]] or [[Target#Section]]
_WIKILINK = re.compile(r"\[\[([^\]\|#\n]+)(?:#[^\]\|\n]+)?(?:\|([^\]\n]+))?\]\]")
# GitHub-style links: [Display](path) where path is a .md (angle-bracket form too)
_MDLINK = re.compile(r"\[([^\]\n]+)\]\(<?([^()\s<>]+\.md)>?\)")
# Sentence segmentation: split on . ! ? 。 ！ ？ followed by space or newline.
_SENT_SPLIT = re.compile(r"(?<=[\.\!\?。！？])[\s\n]+")
# Strip leading frontmatter block (--- ... ---) so its key/value lines don't become queries
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
# Patterns that indicate a "query" is really markup / metadata, not a sentence
_REJECT_PREFIXES = (
    "date:", "type:", "source notes:", "id:", "subject:", "cached:",
    "tags:", "status:", "freshness:", "last built:", "---",
)
# Pattern: line is mostly bullet/checkbox/dash markup
_MOSTLY_MARKUP = re.compile(r"^[\s\-\*\+\d\.\)\(\[\]]+$")

# Anchor titles we treat as templates / not a real semantic target
_PLACEHOLDER_TITLES = {
    "note title", "note title 1", "title", "source note", "backlinks",
    "template", "your name", "concept", "x", "y",
}

# Limit gold-set size for quick eval cycles
DEFAULT_MAX_QUERIES = 200
RANDOM_SEED = 42


@dataclass
class GoldQuery:
    query: str        # the masked sentence containing the link
    anchor: str       # the anchor / display text alone (alt query)
    target: str       # vault-relative path of the linked file
    source: str       # vault-relative path of the file the link was found in


@dataclass
class EvalRun:
    config: Dict
    n_queries: int
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    elapsed_s: float
    per_query: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gold-set construction
# ---------------------------------------------------------------------------

def _title_to_path_map(vault: Path) -> Dict[str, str]:
    """Map note title (filename stem, lowercased) -> vault-relative path.

    Wikilinks reference titles, not paths. We pick the first match if the
    title is ambiguous (rare for wiki/, common across daily-notes which we
    skip below since they have date stems, not title stems).
    """
    out: Dict[str, str] = {}
    for md in vault.rglob("*.md"):
        try:
            rel = str(md.relative_to(vault))
        except ValueError:
            continue
        stem = md.stem.strip().lower()
        out.setdefault(stem, rel)
    return out


def _sentence_around(text: str, span: Tuple[int, int]) -> str:
    """Return the sentence (or 240-char window) containing [start, end)."""
    s, e = span
    # Walk backward to nearest sentence terminator or paragraph break
    start = max(0, s - 240)
    end = min(len(text), e + 240)
    window = text[start:end]
    # Soft-split window into sentences and keep the one containing the link
    rel_s = s - start
    sentences = _SENT_SPLIT.split(window)
    cursor = 0
    for sent in sentences:
        nxt = cursor + len(sent)
        if cursor <= rel_s <= nxt + 1:
            return sent.strip()
        cursor = nxt + 1
    return window.strip()


_ORPHAN_LINKS = [
    re.compile(r"\[\[\s*[#^][^\]]*\]\]"),       # [[#^c1]] / [[#section]] residue
    re.compile(r"\[\[\s*\]\]"),                  # [[]] after anchor removal
    re.compile(r"\[\s*\]\(<?[^)>]*\.md>?\)"),    # [ ](path.md) residue
    re.compile(r"`\s*\[\[\s*[^\]]*\]\]\s*`"),    # `[[...]]` quoted skeletons
]


def _mask(sentence: str, anchor: str) -> str:
    """Remove the anchor text plus the empty link skeleton it leaves behind."""
    if not anchor:
        return sentence
    out = re.sub(re.escape(anchor), " ", sentence, flags=re.IGNORECASE)
    for pat in _ORPHAN_LINKS:
        out = pat.sub(" ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _is_useful(query: str, anchor: str, target: str) -> bool:
    q = query.strip()
    if len(q) < 40 or len(q) > 400:
        return False
    if anchor.lower().strip() in _PLACEHOLDER_TITLES or len(anchor) < 2:
        return False
    first = q.split("\n", 1)[0].strip().lower()
    if first.startswith(_REJECT_PREFIXES):
        return False
    if _MOSTLY_MARKUP.match(q):
        return False
    # Reject markup-heavy / link-heavy windows
    if q.count("](") > 1 or q.count("](<") > 0:
        return False
    if q.count("/") > 5:
        return False
    if q.count("- ") > 4 or q.count(":") > 6:
        return False
    if q.lstrip().startswith(("#", ">", "|", "```")):
        return False
    if "{{" in q or "}}" in q:  # template placeholders
        return False
    # Query must contain enough substantive content besides the masked anchor
    stripped_alpha = re.sub(r"[^A-Za-z一-鿿 ]+", " ", q)
    words = [w for w in stripped_alpha.lower().split() if len(w) >= 3]
    if len(words) + sum(1 for ch in q if "一" <= ch <= "鿿") // 2 < 5:
        return False
    # Skip "anonymous" template targets that aren't a useful target
    if target.endswith("README.md") or target.endswith("_prompt.md"):
        return False
    if "/templates/" in target.lower() or target.startswith("templates/"):
        return False
    # Need enough alphabetic/CJK content
    alpha = sum(1 for ch in q if ch.isalpha() or "一" <= ch <= "鿿")
    if alpha < 25:
        return False
    return True


def build_gold(
    max_queries: int = DEFAULT_MAX_QUERIES,
    seed: int = RANDOM_SEED,
) -> List[GoldQuery]:
    vault = vault_root()
    title_map = _title_to_path_map(vault)
    pool: List[GoldQuery] = []

    for md in vault.rglob("*.md"):
        # Skip caches / template / archive folders to keep the gold set focused
        rel = str(md.relative_to(vault))
        if rel.startswith(("cache/", "archive/", "templates/")):
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Drop frontmatter so its keys aren't mistaken for sentences
        text = _FRONTMATTER.sub("", text)

        for m in _WIKILINK.finditer(text):
            target_title = m.group(1).strip()
            display = (m.group(2) or target_title).strip()
            target_path = title_map.get(target_title.lower())
            if not target_path:
                continue
            if target_path == rel:
                continue  # self-link
            sent = _sentence_around(text, m.span())
            query = _mask(sent, display)
            if not _is_useful(query, target_title, target_path):
                continue
            pool.append(GoldQuery(
                query=query[:400],
                anchor=target_title,
                target=target_path,
                source=rel,
            ))

        for m in _MDLINK.finditer(text):
            display = m.group(1).strip()
            href = m.group(2).strip()
            # Resolve href relative to source file's directory, then to vault
            try:
                tgt = (md.parent / href).resolve()
                target_path = str(tgt.relative_to(vault))
            except (ValueError, OSError):
                continue
            if not (vault / target_path).exists():
                continue
            if target_path == rel:
                continue
            sent = _sentence_around(text, m.span())
            query = _mask(sent, display)
            if not _is_useful(query, display, target_path):
                continue
            pool.append(GoldQuery(
                query=query[:400],
                anchor=display,
                target=target_path,
                source=rel,
            ))

    # Deduplicate by (query, target)
    seen = set()
    deduped: List[GoldQuery] = []
    for g in pool:
        key = (g.query, g.target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)

    # Diversity: limit to <=3 queries per target to avoid heavy-link bias
    by_target: Dict[str, List[GoldQuery]] = {}
    for g in deduped:
        by_target.setdefault(g.target, []).append(g)
    capped: List[GoldQuery] = []
    rng = random.Random(seed)
    for tgt, qs in by_target.items():
        rng.shuffle(qs)
        capped.extend(qs[:3])

    rng.shuffle(capped)
    return capped[:max_queries]


# ---------------------------------------------------------------------------
# Eval execution
# ---------------------------------------------------------------------------

def _dcg(rels: List[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg_at_k(found_paths: List[str], target: str, k: int) -> float:
    rels = [1 if p == target else 0 for p in found_paths[:k]]
    ideal = sorted(rels, reverse=True)
    denom = _dcg(ideal)
    return _dcg(rels) / denom if denom > 0 else 0.0


def evaluate(
    gold: List[GoldQuery],
    *,
    hybrid: bool,
    rerank: bool,
    cross_encoder: bool,
    top_k_retrieve: int = 50,
) -> EvalRun:
    from semantic_backends import LanceStore, Retriever, TierRecencyReranker, make_embedder
    from semantic import _resolve_lance_dir  # type: ignore

    # _resolve_lance_dir already encapsulates the per-embedder path + legacy
    # ~/.cache/reflectl/ fallback (bge-m3 only); don't reimplement here.
    lance_dir = _resolve_lance_dir()

    embedder = make_embedder()
    store = LanceStore(
        db_path=str(lance_dir),
        embedding_dim=embedder.dimension(),
        model_name=embedder.model_name(),
    )

    reranker = None
    if rerank:
        trust: Dict[str, float] = {}
        try:
            from semantic import _load_trust_scores as _lt
            trust = _lt()
        except Exception:
            pass
        reranker = TierRecencyReranker(trust_scores=trust)

    ce = None
    if cross_encoder:
        from semantic_backends import CrossEncoderReranker  # added later
        ce = CrossEncoderReranker()

    retriever = Retriever(embedder=embedder, store=store, reranker=reranker)

    if hybrid:
        from semantic_backends import HybridRetriever
        retriever = HybridRetriever(base=retriever)

    rec5 = 0
    rec10 = 0
    rr_sum = 0.0
    ndcg_sum = 0.0
    per_query = []

    t0 = time.time()
    for g in gold:
        hits = retriever.query(g.query, top_k=top_k_retrieve)
        if ce:
            hits = ce.rerank(g.query, hits, top_k=10)
        paths = [r.path for r in hits]
        in5 = g.target in paths[:5]
        in10 = g.target in paths[:10]
        if in5:
            rec5 += 1
        if in10:
            rec10 += 1
        if g.target in paths[:10]:
            rank = paths[:10].index(g.target) + 1
            rr_sum += 1.0 / rank
        ndcg_sum += _ndcg_at_k(paths, g.target, 10)
        per_query.append({
            "query": g.query[:80],
            "target": g.target,
            "top1": paths[0] if paths else "",
            "rank": (paths[:10].index(g.target) + 1) if g.target in paths[:10] else None,
        })

    elapsed = time.time() - t0
    n = max(1, len(gold))
    return EvalRun(
        config={"hybrid": hybrid, "rerank": rerank, "cross_encoder": cross_encoder, "top_k_retrieve": top_k_retrieve},
        n_queries=len(gold),
        recall_at_5=rec5 / n,
        recall_at_10=rec10 / n,
        mrr_at_10=rr_sum / n,
        ndcg_at_10=ndcg_sum / n,
        elapsed_s=elapsed,
        per_query=per_query,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> int:
    gold = build_gold(max_queries=args.max_queries, seed=args.seed)
    GOLD_PATH.write_text(json.dumps([asdict(g) for g in gold], ensure_ascii=False, indent=2))
    print(f"wrote {len(gold)} queries to {GOLD_PATH}", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not GOLD_PATH.exists():
        print(f"gold set not found at {GOLD_PATH}; run `build` first", file=sys.stderr)
        return 2
    raw = json.loads(GOLD_PATH.read_text())
    gold = [GoldQuery(**g) for g in raw]
    if args.limit:
        gold = gold[: args.limit]
    run = evaluate(
        gold,
        hybrid=args.hybrid,
        rerank=not args.no_rerank,
        cross_encoder=args.cross_encoder,
        top_k_retrieve=args.top_k_retrieve,
    )
    summary = {
        "config": run.config,
        "n_queries": run.n_queries,
        "recall@5": round(run.recall_at_5, 4),
        "recall@10": round(run.recall_at_10, 4),
        "MRR@10": round(run.mrr_at_10, 4),
        "nDCG@10": round(run.ndcg_at_10, 4),
        "elapsed_s": round(run.elapsed_s, 2),
        "qps": round(run.n_queries / max(0.001, run.elapsed_s), 2),
    }
    print(json.dumps(summary, indent=2))
    if args.misses:
        miss_count = 0
        print("\n-- top misses (target not in top-10) --", file=sys.stderr)
        for q in run.per_query:
            if q["rank"] is None:
                print(json.dumps(q, ensure_ascii=False), file=sys.stderr)
                miss_count += 1
                if miss_count >= args.misses:
                    break
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="semantic_eval.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build gold set from vault wikilinks/md-links")
    b.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES)
    b.add_argument("--seed", type=int, default=RANDOM_SEED)
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("run", help="Evaluate current retriever against the gold set")
    r.add_argument("--hybrid", action="store_true", help="Enable BM25+dense hybrid")
    r.add_argument("--cross-encoder", action="store_true", help="Enable cross-encoder reranker")
    r.add_argument("--no-rerank", action="store_true", help="Disable TierRecencyReranker")
    r.add_argument("--top-k-retrieve", type=int, default=50)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--misses", type=int, default=0, help="Print first N misses to stderr")
    r.set_defaults(func=cmd_run)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
