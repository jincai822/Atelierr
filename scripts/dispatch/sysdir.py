"""机器产物目录（``memory/系统/``）写入助手：dispatch 各模块共用。

``系统/`` 是 NOTE_EXCLUDED_DIRS 成员——摘要、控制台、划重点清单等
Agent 产物放在这里：Obsidian 里照常可见可读（Dataview 全库查询不
受影响），但记忆机制（搜索/衰减/watcher/确认回调）不扫描，避免
机器输出污染 references 引用信号与搜索排名（自我指涉回路）。

写入语义与 MemoryTree.create_note 对齐（frontmatter 默认字段同源），
但有两点刻意不同：
- 不登记 sidecar 索引（该目录不在扫描域，无需登记）；
- 允许子目录前缀（create_note 只收纯文件名——平面约定只管记忆区，
  机器产物区由本模块自管）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import frontmatter

from scripts.memory.core import SYSTEM_DIRNAME, _now_iso, generate_id

__all__ = ["SYSTEM_DIRNAME", "write_machine_note"]


def write_machine_note(
    notes_dir: Path,
    filename: str,
    markdown: str,
    source: str,
    tags: Optional[List[str]] = None,
) -> str:
    """把一篇机器产物笔记写进 ``系统/``（原子写，绝不覆盖）。

    frontmatter 必需字段（id/title/created/source/tags）按
    MemoryTree.create_note 同款默认值补齐；markdown 自带的
    frontmatter 字段（如摘要的 undistilled）原样保留。

    Args:
        notes_dir: 笔记根目录（MemoryTree.notes_dir）。
        filename: 纯文件名（.md 结尾，不含目录分量）。
        markdown: 正文（可含 frontmatter）。
        source: 来源标记（digest/highlights 等）。
        tags: 标签列表。

    Returns:
        str: 相对 notes_dir 的 POSIX 路径（``系统/<filename>``）。

    Raises:
        ValueError: 文件名含目录分量或非 .md。
        FileExistsError: 同名文件已存在（调用方按幂等重跑处理）。
    """
    if Path(filename).name != filename:
        raise ValueError(f"文件名不能包含目录分量: {filename!r}")
    if not filename.endswith(".md"):
        raise ValueError(f"文件名必须以 .md 结尾: {filename!r}")
    target = Path(notes_dir) / SYSTEM_DIRNAME / filename
    if target.exists():
        raise FileExistsError(f"机器产物已存在: {target}")

    try:
        post = frontmatter.loads(markdown)
    except Exception:  # noqa: BLE001 - 非法 frontmatter 按纯正文处理
        post = frontmatter.Post(markdown)
    defaults = {
        "id": generate_id(),
        "title": Path(filename).stem,
        "created": _now_iso(),
        "source": source,
        "tags": list(tags or []),
    }
    for key, value in defaults.items():
        post.metadata.setdefault(key, value)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(frontmatter.dumps(post), encoding="utf-8")
    os.replace(tmp, target)
    return f"{SYSTEM_DIRNAME}/{filename}"
