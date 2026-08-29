#!/usr/bin/env python3
"""Atelierr 最小用法示例：MemoryTree 创建/搜索/统计 + 衰减 dry-run 预览。

运行: python examples/basic_usage.py
零外部服务依赖：全部在临时目录里完成，不触碰 ~/atelierr-data。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 把仓库根加入 sys.path，保证从任意位置运行都能导入 scripts 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.memory.core import MemoryTree  # noqa: E402
from scripts.memory.decay import DecayManager  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tree = MemoryTree(f"{tmp}/memory", state_dir=f"{tmp}/state")

        note_a = tree.create_note(
            "meeting.md", "今天讨论了 Atelierr 的发布计划。", source="agent", tags=["工作"]
        )
        note_b = tree.create_note(
            "idea.md", "想到一个记忆衰减的优化思路。", source="agent", tags=["灵感"]
        )
        print(f"创建笔记: {note_a.name} / {note_b.name}")

        hits = tree.search("Atelierr")
        print(f"搜索 'Atelierr' 命中 {len(hits)} 条: {[m.path.name for m in hits]}")

        stats = tree.get_stats()
        print(f"统计: 总数={stats['total']} 分层={stats['layers']}")

        report = DecayManager(tree).run(dry_run=True)
        print(
            f"衰减预览(dry-run): 总数={report['total_notes']} "
            f"short-term={report['short_term']} 将迁移={report['would_relayer']}"
        )
    print("basic_usage 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
