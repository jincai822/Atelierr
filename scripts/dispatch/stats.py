"""捕获统计：各入口捕获量、确认率、沉淀数（只读聚合，不写任何状态）。

用途（2026-09-10 用户裁决 D1「都放」）：
- 晨报：推送文案已带「昨日新入库 N」（简数）；摘要笔记昨日节附入口
  分布一行；
- 周报：周日摘要笔记加「本周捕获统计」节（各入口条数/确认率/沉淀数）；
  ``dispatch_cli stats`` 子命令输出同一段文本（周回顾流程可引用）。

口径：
- 捕获量：frontmatter ``created`` 落在窗口内的笔记条数，按 source 分桶
  （lark→飞书、link→链接转写、media→截图/录音、webclip→剪藏，
  sync/obsidian/web→速记直写，未知→其他）；机器产物（digest/
  highlights/system）不算捕获；
- 确认率：窗口内机器产出（link/media/webclip——带「待确认」门的来源）
  中，当前已摘除「待确认」标签的比例（确认是后验动作，以当前标签
  状态回看）；
- 沉淀数：wiki/ 中 frontmatter ``created`` 落在窗口内的卡片数。

纪律：全部数据来自 frontmatter 只读聚合——不新增任何写入面（裁决 D2）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from scripts.memory.core import LAYERS, MemoryTree

#: source → 入口显示名（未列出的 source 计入「其他」）
_SOURCE_LABELS = {
    "lark": "飞书",
    "link": "链接转写",
    "media": "截图/录音",
    "webclip": "剪藏",
    "sync": "速记直写",
    "obsidian": "速记直写",
    "web": "速记直写",
}

#: 机器产物来源（不算用户捕获，不计入捕获量）
_MACHINE_SOURCES = frozenset({"digest", "highlights", "system"})

#: 带「待确认」门的机器产出来源（确认率的分母）
_AUTO_SOURCES = frozenset({"link", "media", "webclip"})


def capture_stats(
    tree: MemoryTree, days: int = 7, today: Optional[str] = None
) -> Dict[str, Any]:
    """聚合窗口内的捕获统计（只读）。

    Args:
        tree: MemoryTree 实例。
        days: 窗口天数（含基准日；days=1 即只算基准日当天——晨报传
            「昨天」作基准日）。
        today: 基准日（YYYY-MM-DD，测试注入用；缺省今天）。

    Returns:
        Dict[str, Any]: days / total / by_source（显示名→条数）/
        auto_total（机器产出数）/ confirmed（已确认数）/
        confirm_rate（0-1 或 None=无机器产出）/ wiki_new（沉淀数）。
    """
    end = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now()
    start = (end - timedelta(days=days)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    by_source: Dict[str, int] = {}
    total = 0
    auto_total = 0
    confirmed = 0
    for layer in LAYERS:
        for note_path in tree.list_notes(layer):
            try:
                post = frontmatter.loads(
                    Path(note_path).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            created = str(post.get("created") or "")[:10]
            if not created or created <= start or created > end_str:
                continue
            source = str(post.get("source") or "")
            if source in _MACHINE_SOURCES:
                continue
            total += 1
            label = _SOURCE_LABELS.get(source, "其他")
            by_source[label] = by_source.get(label, 0) + 1
            if source in _AUTO_SOURCES:
                auto_total += 1
                tags = post.get("tags") or []
                if "待确认" not in tags:
                    confirmed += 1
    wiki_new = _wiki_new_count(tree, start, end_str)
    return {
        "days": days,
        "total": total,
        "by_source": by_source,
        "auto_total": auto_total,
        "confirmed": confirmed,
        "confirm_rate": (confirmed / auto_total) if auto_total else None,
        "wiki_new": wiki_new,
    }


def _wiki_new_count(tree: MemoryTree, start: str, end_str: str) -> int:
    """wiki/ 中 created 落在 (start, end] 的卡片数（沉淀数）。"""
    wiki_dir = Path(tree.notes_dir) / "wiki"
    if not wiki_dir.is_dir():
        return 0
    count = 0
    for path in wiki_dir.glob("*.md"):
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        created = str(post.get("created") or "")[:10]
        if created and start < created <= end_str:
            count += 1
    return count


def render_capture_line(stats: Dict[str, Any]) -> str:
    """一行简数（晨报昨日节用）：昨日捕获 3 条：飞书 2、剪藏 1。"""
    parts = "、".join(
        f"{label} {count}"
        for label, count in sorted(
            stats["by_source"].items(), key=lambda kv: -kv[1]
        )
    )
    return f"昨日捕获 {stats['total']} 条" + (f"：{parts}" if parts else "")


def render_weekly_stats(stats: Dict[str, Any]) -> List[str]:
    """周报详细行（周日摘要节用）：入口分条 + 确认率 + 沉淀数。"""
    lines = [
        f"- 窗口：近 {stats['days']} 天，共捕获 {stats['total']} 条",
    ]
    for label, count in sorted(
        stats["by_source"].items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"- {label}：{count} 条")
    if stats["confirm_rate"] is not None:
        rate = f"{stats['confirm_rate'] * 100:.0f}%"
        lines.append(
            f"- 确认率：{rate}（机器产出 {stats['auto_total']} 条，"
            f"已确认 {stats['confirmed']} 条）"
        )
    else:
        lines.append("- 确认率：—（窗口内无机器产出）")
    lines.append(f"- 沉淀进 wiki：{stats['wiki_new']} 张卡")
    return lines
