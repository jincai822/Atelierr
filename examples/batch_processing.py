#!/usr/bin/env python3
"""批量登记示例：MemoryWatcher 把目录里的裸 .md 批量归一化登记。

运行: python examples/batch_processing.py [笔记目录]
不传目录时用临时目录自动生成 3 个示例笔记。
零外部服务依赖，不触碰 ~/atelierr-data。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import List, Optional

# 把仓库根加入 sys.path，保证从任意位置运行都能导入 scripts 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.memory.core import MemoryTree  # noqa: E402
from scripts.memory.watcher import MemoryWatcher  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or []
    tmp_ctx = None
    if argv:
        notes_dir = Path(argv[0])
        notes_dir.mkdir(parents=True, exist_ok=True)
        state_dir = notes_dir.parent / "state"
    else:
        tmp_ctx = tempfile.TemporaryDirectory()
        base = Path(tmp_ctx.name)
        notes_dir = base / "memory"
        notes_dir.mkdir(parents=True)
        state_dir = base / "state"
        for i in range(1, 4):
            (notes_dir / f"note-{i}.md").write_text(
                f"批量笔记 {i} 的正文内容。", encoding="utf-8"
            )
    try:
        tree = MemoryTree(str(notes_dir), state_dir=str(state_dir))
        result = MemoryWatcher(tree, source="web").process_pending()
        print(
            f"归一化: {len(result['normalized'])} 条 -> {[p.name for p in result['normalized']]}"
        )
        print(f"新登记: {len(result['registered'])} 条")
        print(f"注销: {len(result['deregistered'])} 条")
        print(f"跳过: {len(result['skipped'])} 条")
        print(f"当前索引总数: {tree.get_stats()['total']}")
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
    print("batch_processing 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
