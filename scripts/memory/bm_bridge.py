"""Basic Memory 桥接层（方案三 P2，2026-09-19 用户裁决）：记忆系统的
存储/检索统一委托给 basic-memory，本模块是唯一接触它的入口。

设计要点：
- **一律走官方 CLI 子进程**（``basic-memory tool ...``），不在本进程内
  调它的异步 API——2026-09-19 实证：进程内 ``run_with_cleanup`` 每次
  调用泄漏一个 anyio 工作线程（非守护、停在 queue.get），单次调用无碍，
  第二次起进程退出时永久挂死（pytest 全绿但进程不退；oneshot 定时器
  服务会挂住不退）。子进程把泄漏隔离在短命子进程里，父进程（飞书桥/
  pytest/定时器）永远干净；
- **不需要永久映射表**：permalink 与笔记相对路径是确定性换算
  （``atelierr/<relpath 去 .md>``），sidecar id 仍是本系统对外主键
  （飞书卡/wiki 链接不动），permalink 只在桥内使用；
- 写入走它的工具（distill/划重点落卡），实体与关系即时进索引；
  外部写入（Obsidian/飞书）由每日 03:20 reindex 定时器兜底；
- 一切失败抛 RuntimeError，由调用方决定降级（搜索退回全文匹配）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 本系统 vault 在 basic-memory 里的项目名（basic-memory project add 时登记）
BM_PROJECT = "atelierr"

#: 子进程超时（秒）：fastembed 模型加载约 4–8s，留足余量
_SEARCH_TIMEOUT = 180
_WRITE_TIMEOUT = 300


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


def _cli() -> str:
    """basic-memory CLI 可执行路径（与当前解释器同 venv）。"""
    return str(Path(sys.executable).parent / "basic-memory")


def _run_cli(args: List[str], *, input_text: Optional[str] = None, timeout: int) -> str:
    """执行 basic-memory CLI 并返回 stdout；非零退出抛 RuntimeError。"""
    proc = subprocess.run(
        [_cli(), *args],
        capture_output=True,
        text=True,
        input=input_text,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"basic-memory CLI failed: {proc.stderr.strip()[-200:]}")
    return proc.stdout


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
        RuntimeError: 搜索失败（调用方可降级全文搜索）。
    """
    args = [
        "tool", "search-notes", query,
        "--json", "--local",
        "--project", BM_PROJECT,
        "--page-size", str(int(limit)),
    ]
    for note_type in note_types or []:
        args += ["--type", note_type]
    for tag in tags or []:
        args += ["--tag", tag]
    out = _run_cli(args, timeout=_SEARCH_TIMEOUT)
    try:
        result = json.loads(out)
    except ValueError as exc:
        raise RuntimeError(f"basic-memory search returned non-JSON: {out[:200]}") from exc
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

    CLI 没有任意 metadata 选项，但**正文自带 frontmatter 时字段全保留**
    （2026-09-19 实测：status/verified/stale_after 均落盘）——metadata
    由本桥合并进正文 frontmatter 再经 stdin 传给 CLI。

    Args:
        rel_path: 相对 vault 根的路径（含 .md）。
        title: 标题。
        content: 正文（markdown）。
        note_type: frontmatter type（如 Excerpt/Topic）。
        tags: 标签。
        metadata: 追加的 frontmatter 字段（OKF 字段走这里）。
        overwrite: 同名覆盖（幂等重写用）。

    Returns:
        str: 新实体的 permalink（按 CLI 返回的实际落盘 file_path 推导，
        与请求 rel_path 可能不同——bm 按标题命名文件）。

    Raises:
        RuntimeError: 写入失败。
    """
    body = content
    if metadata:
        import frontmatter

        body = frontmatter.dumps(frontmatter.Post(content, **metadata))
    directory = str(Path(rel_path).parent).replace("\\", "/")
    if directory in ("", "."):
        directory = "."
    args = [
        "tool", "write-note",
        "--title", title,
        "--folder", directory,
        "--type", note_type or "note",
        "--project", BM_PROJECT,
        "--local",
    ]
    if tags:
        args += ["--tags", ",".join(tags)]
    if overwrite:
        args.append("--overwrite")
    out = _run_cli(args, input_text=body, timeout=_WRITE_TIMEOUT)
    head = out.strip()[:20].lower()
    if "error" in head or "traceback" in head:
        raise RuntimeError(f"basic-memory write failed: {out[:200]}")
    # 实际落盘位置以 CLI 返回的 file_path 为准（bm 按标题起名，title 与
    # rel_path 词干不一致时会漂移）；bm 写入时的实体 permalink 是标题
    # slug（可能与文件路径不合），本桥只暴露**路径推导** permalink——
    # 与 reindex 从磁盘重建的 permalink 约定一致，slug 漂移由每晚
    # 03:20 reindex 归一（2026-09-19 实测「桥接测试3」→ slug 桥接测试-3）
    try:
        file_path = str(json.loads(out).get("file_path") or "").strip()
    except ValueError:
        file_path = ""
    if not file_path:
        file_path = rel_path.replace("\\", "/")
    return rel_to_permalink(file_path)


def reindex() -> None:
    """全量重建索引（批量外部变更后调用；日常由 03:20 定时器兜底）。"""
    _run_cli(["reindex"], timeout=600)
