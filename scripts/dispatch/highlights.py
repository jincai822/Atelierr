"""划重点勾中转笔记：清单里被人工勾中的候选 → 正式笔记（带"待确认"）。

与 links/media/todos 同源的 dispatch 顶层组合模块，是「划重点」机制的
人工侧（机器侧见 :mod:`scripts.processors.highlights`）：

1. processors/highlights 产出的清单笔记（``source: highlights``，
   标签"划重点"）里，每条候选是一个 ``- [ ]`` 复选框；
2. 人在 Obsidian 里把想要的勾成 ``- [x]``；
3. 本模块下一轮扫描发现新勾项，为其建一条正式笔记（标签"待确认" +
   "划重点"，``source: highlight`` 单数），内容含候选详情与来源双链。

纪律（与 dispatch 各模块一致）：
- 只新增笔记，绝不改写/移动/删除既有笔记与清单本身；
- 幂等：已转记的勾项登记在 ``<state_dir>/processed_highlights.json``
  （键 = 清单文件名 + 条目标题 + 页码），同一条只建一次；
- 勾了又取消：笔记已建不追回（机器绝不删除），不要可在 review 时标
  pending_delete；
- 清单笔记本身 ``source: highlights`` 会被 todos 分发跳过（候选项不是
  行动意图，防整清单进待办）；转出的正式笔记按普通笔记对待。

触发：systemd 定时器（docker/systemd/atelierr-links.*，接在 todos 之后）
或人工 ``dispatch_cli highlights``。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from scripts.memory.core import MemoryTree

#: 清单笔记的 source 值（复数；todos 分发按此跳过）
CHECKLIST_SOURCE = "highlights"
#: 转出正式笔记的 source 值（单数；按普通笔记对待）
PROMOTED_SOURCE = "highlight"

#: 转出正式笔记的标签（人工确认后由人移除"待确认"）
REVIEW_TAG = "待确认"
ITEM_TAG = "划重点"

#: 勾中行：- [x] **标题**（第 N 页）——与处理器产出的复选框行严格对应
_TICKED_RE = re.compile(
    r"^- \[x\]\s+\*\*(?P<title>.+?)\*\*(?:（第\s*(?P<page>\d+)\s*页）)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: 文件名非法字符（半角）转 -
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')

_LAYERS = ("short-term", "mid-term", "long-term")


class HighlightsDispatcher:
    """扫描划重点清单笔记，把新勾中的候选转为正式笔记。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 勾项转记状态文件（processed_highlights.json）。
    """

    def __init__(self, tree: MemoryTree) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
        """
        self.tree = tree
        self.state_path = Path(tree.state_dir) / "processed_highlights.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与转记。

        Args:
            dry_run: 只报告不处理（不建笔记、不写状态）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/ticked/created/skipped）。
        """
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "ticked": 0,
            "created": [],
            "skipped": 0,
        }
        for layer in _LAYERS:
            for note_path in self.tree.list_notes(layer):
                post = self._load_post(note_path)
                if post is None or post.get("source") != CHECKLIST_SOURCE:
                    continue
                report["scanned"] += 1
                self._process_checklist(note_path, post, state, report, dry_run)
        if not dry_run:
            self._save_state(state)
        return report

    def _process_checklist(
        self,
        note_path: Path,
        post: Any,
        state: Dict[str, Any],
        report: Dict[str, Any],
        dry_run: bool,
    ) -> None:
        """处理单份清单：找出新勾中的条目并逐一转记。"""
        key = note_path.name
        entry = state.setdefault(key, {"promoted": {}})
        promoted: Dict[str, str] = entry.setdefault("promoted", {})
        for match in _TICKED_RE.finditer(post.content):
            title = match.group("title").strip()
            page = int(match.group("page") or 0)
            item_key = f"{title}#{page}"
            report["ticked"] += 1
            if item_key in promoted:
                report["skipped"] += 1
                continue
            if dry_run:
                continue
            filename = self._note_filename(key, title)
            body = self._build_note(note_path.stem, post.content, match, title, page)
            try:
                self.tree.create_note(
                    filename,
                    body,
                    source=PROMOTED_SOURCE,
                    tags=[REVIEW_TAG, ITEM_TAG],
                )
            except (ValueError, FileExistsError):
                # 同名笔记已存在（状态丢失后的重跑）：视为已转记
                pass
            promoted[item_key] = filename
            entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
            report["created"].append(filename)

    @staticmethod
    def _build_note(
        checklist_stem: str, body: str, match: re.Match, title: str, page: int
    ) -> str:
        """组装转出笔记正文：候选详情块 + 来源双链。"""
        details: List[str] = []
        for line in body[match.end():].splitlines():
            stripped = line.strip()
            if stripped.startswith("- ["):
                break
            if stripped.startswith("- "):
                details.append(stripped)
        anchor = f"，第 {page} 页" if page else ""
        lines = [
            f"# {title}",
            "",
            f"> 来源：[[{checklist_stem}]]（划重点清单{anchor}，人工勾选转入）",
            "",
        ]
        lines += details or ["（清单中未附详情行）"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _note_filename(checklist_name: str, title: str) -> str:
        """转出笔记文件名：hl-<净化标题>-<清单哈希前6>.md（跨清单防撞名）。"""
        cleaned = _ILLEGAL_RE.sub("-", title).strip(". ")[:40] or "未命名"
        digest = hashlib.sha1(checklist_name.encode("utf-8")).hexdigest()[:6]
        return f"hl-{cleaned}-{digest}.md"

    @staticmethod
    def _load_post(note_path: Path) -> Optional[Any]:
        """读取笔记 frontmatter；损坏/不可读返回 None（跳过不阻塞）。"""
        try:
            return frontmatter.loads(note_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _load_state(self) -> Dict[str, Any]:
        """加载转记状态；文件缺失/损坏返回空表（不抛异常）。"""
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（临时文件 + rename）。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
