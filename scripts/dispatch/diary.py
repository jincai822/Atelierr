"""日记追加的唯一入口（2026-09-21 第 7 条前置抽取）。

机器往日记里写东西是"笔记创建后绝不改写"红线的用户批准例外，
批准的路径有四条：

- 飞书消息/附件说明（2026-09-12 裁决，feishu.py）；
- 晨间摘要指路行（2026-09-21 方案 A 拍板，digest.py）；
- 实体反链包裹（2026-09-21 第 9 条①，entitylink.py——行文出生
  那一刻包，不回头改既有行）；
- 晚间 enrichment（2026-09-21 第 9 条②③，enrich.py——今日三问块
  追加 + 错别字批改，还原 mtime；批改一项是用户驳回"机器不动你的字"
  建议后的明确选择）。

前两条走本模块的追加机制；后两条各有自己的写入纪律（见各自模块
docstring）。路径解析（daily-notes/YYYY/MM/ + 根目录旧位置兼容期）
只此一份。追加不碰 frontmatter（id/created 不变）；既有日记 bump
last_accessed（新内容算活跃）；日期按本地时区自然日。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.memory.core import MemoryTree, daily_note_path
from scripts.utils.date_utils import local_timezone


def resolve_diary_path(notes_dir: Path, day: str) -> Path:
    """解析指定日期的日记路径：新结构优先，根目录旧位置兼容。

    迁址兼容期（2026-09-21）：QuickAdd 速记若仍写根目录旧位置
    （``<day>.md``），续写/读取同一本，不分裂成两本日记。两边都
    不存在时返回新结构路径（调用方决定是否创建）。

    Args:
        notes_dir: 笔记根目录（memory/）。
        day: 日期（YYYY-MM-DD）。

    Returns:
        Path: 日记文件路径（不保证存在）。
    """
    diary = daily_note_path(notes_dir, day)
    legacy = Path(notes_dir) / f"{day}.md"
    if legacy.is_file() and not diary.exists():
        return legacy
    return diary


def append_diary_line(
    tree: MemoryTree,
    text: str,
    *,
    day: Optional[str] = None,
    now: Optional[datetime] = None,
    source: str = "lark",
) -> Path:
    """往指定日期的日记追加一行 ``- HH:MM 内容``（多行后续行缩进两格）。

    日记不存在则创建：create_note 只建根/inbox，故先建根再迁入
    daily-notes/YYYY/MM/（同进程连贯操作，relocate_entry 随迁
    sidecar）；已存在则纯追加并 bump last_accessed。

    Args:
        tree: MemoryTree 实例。
        text: 行内容（首行接在时间前缀后；多行消息后续行缩进两格）。
        day: 目标日期（YYYY-MM-DD；缺省取 now 的自然日——测试注入用，
            真实调用不要传，避免跨午夜的时序漂移）。
        now: 时刻（测试注入用；缺省当前本地时间）。
        source: 新建日记时写入的 frontmatter source（既有日记不动）。

    Returns:
        Path: 日记文件路径。
    """
    now = now or datetime.now(local_timezone())
    day = day or now.strftime("%Y-%m-%d")
    diary = resolve_diary_path(Path(tree.notes_dir), day)
    diary.parent.mkdir(parents=True, exist_ok=True)
    lines = text.splitlines()
    entry = f"- {now.strftime('%H:%M')} {lines[0]}"
    entry += "".join(f"\n  {line}" for line in lines[1:])
    if not diary.exists():
        created = tree.create_note(diary.name, f"{entry}\n", source=source)
        created.rename(diary)
        note_id = tree._read_note_id(diary)
        if note_id is not None:
            tree.relocate_entry(note_id, tree._rel_key(diary))
        return diary
    content = diary.read_text(encoding="utf-8")
    sep = "" if content.endswith("\n") else "\n"
    with diary.open("a", encoding="utf-8") as fh:
        fh.write(f"{sep}{entry}\n")
    tree.on_note_accessed(diary)
    return diary
