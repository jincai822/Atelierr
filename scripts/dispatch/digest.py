"""晨间摘要：每天定时创建一条"今日摘要"笔记（只新建，不改写）。

内容四节（wikilink 列表，点开即达）：
- 待我确认：当前带"待确认"标签的笔记（摘除标签后次日自然消失）；
- 待办进行中：当前带"待办"标签的笔记；
- 今日复习：遗忘临界区内的笔记（ResurfaceManager，decay 的反面；
  检索式推送——只列标题，提示"先回忆再点开"，点开看一眼即重置时钟，
  确认无价值的留给 review→purge，值得留存的提炼进 wiki/）；
- 昨日新入库：frontmatter created 日期为昨天的笔记。

纪律（与 dispatch 模块同源）：
- 幂等：文件名 ``今日摘要-YYYY-MM-DD.md``，当天已存在则跳过；
- 摘要笔记 ``source="digest"``，todos 分发跳过它（防把摘要里的
  待办文本再喂给 LLM 空转）；
- 只读全部笔记的 frontmatter/正文，绝不改写；
- 复习推送冷却时钟只写 ``<state_dir>/resurface.json``，且仅在摘要
  笔记真正创建成功后记录（dry-run/跳过不烧冷却）；
- 推送响应观测（实验 0）只写 ``<state_dir>/response_probe.json``，
  同样仅在真实运行时执行。

触发：systemd 每日定时器（docker/systemd/atelierr-digest.*）或
人工 ``dispatch_cli digest``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.response_probe import ResponseProbe
from scripts.memory.core import LAYERS, MemoryTree
from scripts.memory.resurface import ResurfaceManager
from scripts.memory.watcher import MemoryWatcher


class DigestDispatcher:
    """每日晨间摘要笔记生成器。

    Attributes:
        tree: MemoryTree 实例。
        resurface: 复习队列管理器（默认按内置窗口构造）。
        probe: 推送响应观测器（实验 0，随摘要每日执行一次）。
    """

    def __init__(
        self, tree: MemoryTree, resurface: Optional[ResurfaceManager] = None
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            resurface: 复习队列管理器；None 时用默认窗口构造。
        """
        self.tree = tree
        self.resurface = resurface or ResurfaceManager(tree)
        self.probe = ResponseProbe(tree)

    def run(
        self, dry_run: bool = False, today: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成当日摘要；当天已存在则跳过。

        Args:
            dry_run: 只返回将写入的内容，不建笔记。
            today: 覆盖"今天"（YYYY-MM-DD，测试用）。

        Returns:
            Dict[str, Any]: {created, skipped, counts, markdown}；
                counts 含 pending/todos/resurface/yesterday_new。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        today = today or datetime.now().strftime("%Y-%m-%d")
        filename = f"今日摘要-{today}.md"
        if (Path(self.tree.notes_dir) / filename).exists():
            return {"created": None, "skipped": True, "counts": {}, "markdown": ""}
        pending, todos, yesterday_new = self._collect(today)
        review = self.resurface.candidates()
        review_stems = [Path(item["filename"]).stem for item in review]
        markdown = self._build(today, pending, todos, review_stems, yesterday_new)
        created = None
        if not dry_run:
            self.tree.create_note(filename, markdown, source="digest", tags=["摘要"])
            self.resurface.mark_pushed([item["id"] for item in review])
            self.probe.register(review)
            self.probe.check_pending()
            created = filename
        return {
            "created": created,
            "skipped": False,
            "counts": {
                "pending": len(pending),
                "todos": len(todos),
                "resurface": len(review),
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
        review: List[str],
        yesterday_new: List[str],
    ) -> str:
        """组装摘要 Markdown（空节显示"无"）。"""

        def _lines(items: List[str]) -> List[str]:
            return [f"- [[{stem}]]" for stem in items] or ["- 无"]

        sections = [f"# 今日摘要 {today}", ""]
        sections += [f"## ⏳ 待我确认（{len(pending)}）", "", *_lines(pending), ""]
        sections += [f"## ✅ 待办进行中（{len(todos)}）", "", *_lines(todos), ""]
        sections += [f"## 🔁 今日复习（{len(review)}）", ""]
        if review:
            sections += [
                "> 检索练习：看着标题先想「它讲了什么」，再点开核对；",
                "> 想不起来的，值得就提炼进 wiki/，不值得就留给 review→purge。",
                "",
            ]
        sections += [*_lines(review), ""]
        sections += [
            f"## 📥 昨日新入库（{len(yesterday_new)}）",
            "",
            *_lines(yesterday_new),
        ]
        return "\n".join(sections) + "\n"
