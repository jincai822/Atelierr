"""Basic Memory 桥接层（方案三 P2，2026-09-19 用户裁决）：记忆系统的
存储/检索统一委托给 basic-memory，本模块是唯一接触它的入口。

设计要点：
- 调用模式与 basic-memory 官方 CLI 同源（``basic_memory.mcp.tools`` +
  ``run_with_cleanup``），版本升级时行为一致；
- **不需要永久映射表**：permalink 与笔记相对路径是确定性换算
  （``atelierr/<relpath 去 .md>``），sidecar id 仍是本系统对外主键
  （飞书卡/wiki 链接不动），permalink 只在桥内使用；
- 写入走它的工具（distill/划重点落卡），实体与关系即时进索引；
  外部写入（Obsidian/飞书）由每日 03:20 reindex 定时器兜底；
- 一切失败抛 RuntimeError，由调用方决定降级（搜索退回全文匹配）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

#: 本系统 vault 在 basic-memory 里的项目名（basic-memory project add 时登记）
BM_PROJECT = "atelierr"


def rel_to_permalink(rel_path: str) -> str:
    """笔记相对路径 → basic-memory permalink（确定性换算，无映射表）。"""
    rel = rel_path.replace("\\", "/")
    if rel.endswith(".md"):
        rel = rel[:-3]
    return f"{BM_PROJECT}/{rel}"


def permalink_to_rel(permalink: str) -> str:
    """permalink → 笔记相对路径（含 .md；非本项目前缀原样返回）。"""
    rel = permalink
    prefix = f"{BM_PROJECT}/"
    if rel.startswith(prefix):
        rel = rel[len(prefix):]
    return rel if rel.endswith(".md") else rel + ".md"


def _run(coro: Any) -> Any:
    """同步执行 basic-memory 的异步工具（与官方 CLI 同款 run_with_cleanup）。"""
    from basic_memory.cli.commands.command_utils import run_with_cleanup

    return run_with_cleanup(coro)


def search(
    query: str,
    *,
    limit: int = 10,
    note_types: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """语义搜索全库，返回归一化命中列表。

    Args:
        query: 查询文本。
        limit: 条数上限。
        note_types: frontmatter type 过滤（如 ["Excerpt"]）。
        tags: 标签过滤。

    Returns:
        List[Dict]: [{title, permalink, rel_path, score, snippet}]，按相关度降序。

    Raises:
        RuntimeError: 搜索失败或返回错误文本（调用方可降级全文搜索）。
    """
    from basic_memory.mcp.tools import search_notes

    result = _run(
        search_notes(
            query=query,
            project=BM_PROJECT,
            output_format="json",
            page=1,
            page_size=int(limit),
            note_types=note_types,
            tags=tags,
        )
    )
    if isinstance(result, str):
        raise RuntimeError(f"basic-memory search failed: {result}")
    hits: List[Dict[str, Any]] = []
    for item in (result or {}).get("results", []):
        permalink = str(item.get("permalink") or "")
        hits.append(
            {
                "title": str(item.get("title") or ""),
                "permalink": permalink,
                "rel_path": permalink_to_rel(permalink) if permalink else "",
                "score": float(item.get("score") or 0.0),
                "snippet": str(item.get("matched_chunk") or item.get("content") or "")[:300],
            }
        )
    return hits


def write_note(
    rel_path: str,
    title: str,
    content: str,
    *,
    note_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    overwrite: bool = True,
) -> str:
    """经 basic-memory 写一条笔记（实体与关系即时进索引）。

    Args:
        rel_path: 相对 vault 根的路径（含 .md）。
        title: 标题。
        content: 正文（markdown）。
        note_type: frontmatter type（如 Excerpt/Topic）。
        tags: 标签。
        metadata: 追加的 frontmatter 字段（bm 合并落盘，OKF 字段走这里）。
        overwrite: 同名覆盖（幂等重写用）。

    Returns:
        str: 新实体的 permalink。

    Raises:
        RuntimeError: 写入失败。
    """
    from basic_memory.mcp.tools import write_note as bm_write_note

    directory = str(Path(rel_path).parent).replace("\\", "/")
    if directory == ".":
        directory = ""
    result = _run(
        bm_write_note(
            title=title,
            content=content,
            directory=directory,
            project=BM_PROJECT,
            note_type=note_type or "note",
            tags=tags,
            metadata=metadata,
            overwrite=overwrite,
        )
    )
    text = str(result)
    if "error" in text.lower()[:20]:
        raise RuntimeError(f"basic-memory write failed: {text[:200]}")
    return rel_to_permalink(rel_path)


def reindex() -> None:
    """全量重建索引（批量外部变更后调用；日常由 03:20 定时器兜底）。"""
    from basic_memory.cli.commands.command_utils import run_with_cleanup  # noqa: F401
    import subprocess
    import sys

    proc = subprocess.run(
        [str(Path(sys.executable).parent / "basic-memory"), "reindex"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"basic-memory reindex failed: {proc.stderr.strip()[-200:]}")
