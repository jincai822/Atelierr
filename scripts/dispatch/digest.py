"""晨间摘要：每天定时创建一条"今日摘要"笔记（只新建，不改写）。

内容三节（wikilink 列表，点开即达）：
- 待我确认：当前带"待确认"标签的笔记（摘除标签后次日自然消失）；
- 待办进行中：当前带"待办"标签的笔记；
- 昨日新入库：frontmatter created 日期为昨天的笔记。

纪律（与 dispatch 模块同源）：
- 幂等：文件名 ``今日摘要-YYYY-MM-DD.md``，当天已存在则跳过；
- 摘要笔记 ``source="digest"``，todos 分发跳过它（防把摘要里的
  待办文本再喂给 LLM 空转）；
- 只读全部笔记的 frontmatter/正文，绝不改写。

触发：systemd 每日定时器（docker/systemd/atelierr-digest.*）或
人工 ``dispatch_cli digest``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.memory.core import LAYERS, MemoryTree
from scripts.memory.watcher import MemoryWatcher


class DigestDispatcher:
    """每日晨间摘要笔记生成器。

    Attributes:
        tree: MemoryTree 实例。
    """

    def __init__(self, tree: MemoryTree) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
        """
        self.tree = tree

    def run(
        self, dry_run: bool = False, today: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成当日摘要；当天已存在则跳过。

        Args:
            dry_run: 只返回将写入的内容，不建笔记。
            today: 覆盖"今天"（YYYY-MM-DD，测试用）。

        Returns:
            Dict[str, Any]: {created, skipped, counts, markdown}。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        today = today or datetime.now().strftime("%Y-%m-%d")
        filename = f"今日摘要-{today}.md"
        if (Path(self.tree.notes_dir) / filename).exists():
            return {"created": None, "skipped": True, "counts": {}, "markdown": ""}
        pending, todos, yesterday_new = self._collect(today)
        markdown = self._build(today, pending, todos, yesterday_new)
        created = None
        if not dry_run:
            self.tree.create_note(filename, markdown, source="digest", tags=["摘要"])
            created = filename
        return {
            "created": created,
            "skipped": False,
            "counts": {
                "pending": len(pending),
                "todos": len(todos),
                "yesterday_new": len(yesterday_new),
            },
            "markdown": markdown,
        }

    def _collect(
        self, today: str
    ) -> Tuple[List[str], List[str], List[str]]:
        """扫描全部笔记，分出三节各自的 wikilink 目标（按文件名排序）。"""
        yesterday = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        pending: List[str] = []
        todos: List[str] = []
        yesterday_new: List[str] = []
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                stem = note_path.stem
                if stem.startswith("今日摘要-"):  # 历史摘要不进摘要
                    continue
                try:
                    post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                tags = post.get("tags") or []
                if "待确认" in tags:
                    pending.append(stem)
                if "待办" in tags:
                    todos.append(stem)
                created = str(post.get("created") or "")
                if created[:10] == yesterday:
                    yesterday_new.append(stem)
        return sorted(pending), sorted(todos), sorted(yesterday_new)

    @staticmethod
    def _build(
        today: str,
        pending: List[str],
        todos: List[str],
        yesterday_new: List[str],
    ) -> str:
        """组装摘要 Markdown（空节显示"无"）。"""

        def _lines(items: List[str]) -> List[str]:
            return [f"- [[{stem}]]" for stem in items] or ["- 无"]

        sections = [f"# 今日摘要 {today}", ""]
        sections += [f"## ⏳ 待我确认（{len(pending)}）", "", *_lines(pending), ""]
        sections += [f"## ✅ 待办进行中（{len(todos)}）", "", *_lines(todos), ""]
        sections += [f"## 📥 昨日新入库（{len(yesterday_new)}）", "", *_lines(yesterday_new)]
        return "\n".join(sections) + "\n"
