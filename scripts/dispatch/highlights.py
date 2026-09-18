"""划重点勾中转摘录卡：清单里被人工勾中的候选 → wiki/ 根层摘录卡。

与 links/media/todos 同源的 dispatch 顶层组合模块，是「划重点」机制的
人工侧（机器侧见 :mod:`scripts.processors.highlights`）：

1. processors/highlights 产出的清单笔记（``source: highlights``，
   标签"划重点"）里，每条候选是一个 ``- [ ]`` 复选框；
2. 人在 Obsidian 里把想要的勾成 ``- [x]``；
3. 本模块下一轮扫描发现新勾项，为其在 wiki/ 根层建一张摘录卡
   （``type: Excerpt``，``from`` 指回清单 + 页码，``source: highlight``
   单数），内容含候选详情与来源双链——勾选即沉淀，不再经 memory/
   待确认笔记中转（2026-09-06 方案③：摘录卡 = Zettelkasten 文献笔记，
   日后周日提炼仪式把它改写为自己的 concept 卡并与它互链）。

纪律（与 dispatch 各模块一致）：
- 只新增卡片，绝不改写/移动/删除既有笔记、卡片与清单本身；
- 幂等：已转记的勾项登记在 ``<state_dir>/processed_highlights.json``
  （键 = 清单文件名 + 条目标题 + 页码），同一条只建一次；
- 勾了又取消：摘录卡已建不追回（机器绝不删除；wiki 无 purge，
  不要了由人手动删）；
- 清单笔记本身 ``source: highlights`` 落在 ``系统/`` 机器产物区
  （NOTE_EXCLUDED_DIRS 成员，记忆机制不扫描、不衰减；本模块直接
  读目录定位清单，不走 sidecar 索引）；根层遗留清单仍兼容扫描。
  若清单日后被人手动删除，WikiManager.validate 会报摘录卡 from
  悬空（只报告，不阻止）。

触发：systemd 定时器（docker/systemd/atelierr-links.*，接在 todos 之后）
或人工 ``dispatch_cli highlights``。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import frontmatter

from scripts.dispatch.sysdir import SYSTEM_DIRNAME
from scripts.utils.state_store import read_json, write_json
from scripts.memory.core import MemoryTree
from scripts.wiki import curation
from scripts.wiki.manager import EXCERPT_TYPE, WIKI_DIRNAME

#: 清单笔记的 source 值（复数；todos 分发按此跳过）
CHECKLIST_SOURCE = "highlights"
#: 摘录卡的 source 值（单数）
PROMOTED_SOURCE = "highlight"

#: 摘录卡的标签（不再有"待确认"——勾选即沉淀，无需二次确认）
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
    """扫描划重点清单笔记，把新勾中的候选转为 wiki/ 摘录卡。

    Attributes:
        tree: MemoryTree 实例（只借它定位库根与清单笔记）。
        wiki_dirname: 库根下的 wiki 子目录名（默认 ``wiki``）。
        state_path: 勾项转记状态文件（processed_highlights.json）。
    """

    def __init__(self, tree: MemoryTree, wiki_dirname: str = WIKI_DIRNAME) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            wiki_dirname: 库根下的 wiki 子目录名。
        """
        self.tree = tree
        self.wiki_dirname = wiki_dirname
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
        for note_path in self._checklist_paths():
            post = self._load_post(note_path)
            if post is None or post.get("source") != CHECKLIST_SOURCE:
                continue
            report["scanned"] += 1
            self._process_checklist(note_path, post, state, report, dry_run)
        if not dry_run:
            self._save_state(state)
        return report

    def _checklist_paths(self) -> List[Path]:
        """定位全部清单笔记：系统/ 目录直读 + 根层遗留（走索引）。"""
        seen: Set[Path] = set()
        paths: List[Path] = []
        system_dir = Path(self.tree.notes_dir) / SYSTEM_DIRNAME
        if system_dir.is_dir():
            for path in sorted(system_dir.glob("*.md")):
                seen.add(path)
                paths.append(path)
        for layer in _LAYERS:
            for note_path in self.tree.list_notes(layer):
                if note_path not in seen:
                    seen.add(note_path)
                    paths.append(note_path)
        return paths

    def _process_checklist(
        self,
        note_path: Path,
        post: Any,
        state: Dict[str, Any],
        report: Dict[str, Any],
        dry_run: bool,
    ) -> None:
        """处理单份清单：找出新勾中的条目并逐一转记为摘录卡。"""
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
            filename = self._card_filename(key, title)
            body = self._build_card_body(note_path.stem, post.content, match, title, page)
            try:
                self._write_excerpt_card(
                    filename, title, note_path, page, body
                )
            except FileExistsError:
                # 同名卡片已存在（状态丢失后的重跑）：视为已转记
                pass
            try:
                # OKF 机器自留地（2026-09-18 全量采纳，与 distill 同源）：
                # index.md 导航 / log.md 日志 / topics 主题页——全部幂等
                book = post.metadata.get("book") or {}
                curation.update_index(
                    Path(self.tree.notes_dir) / self.wiki_dirname,
                    filename,
                    title,
                    f"划重点勾选自 {note_path.stem}",
                )
                curation.append_log(
                    Path(self.tree.notes_dir) / self.wiki_dirname, filename, title
                )
                curation.update_topic_page(
                    Path(self.tree.notes_dir) / self.wiki_dirname,
                    card_stem=Path(filename).stem,
                    card_title=title,
                    description=f"划重点勾选自 {note_path.stem}",
                    topic_hint=str(book.get("clc") or ""),
                )
            except Exception as exc:  # noqa: BLE001 - 自留地维护不阻塞转记
                print(f"[highlights] curation fail: {exc}", flush=True)
            promoted[item_key] = filename
            entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
            report["created"].append(filename)

    def _write_excerpt_card(
        self, filename: str, title: str, checklist_path: Path, page: int, body: str
    ) -> None:
        """在 wiki/ 根层原子创建摘录卡（撞名抛 FileExistsError，绝不覆盖）。

        卡片不进 sidecar 索引、不参与 decay——勾选即沉淀为永久资产。
        frontmatter 与 distill 的 OKF v0.2 轻量层对齐（2026-09-18 格式
        统一裁决）：勾选 = 人工批准，故建卡即 status: stable + verified。
        """
        checklist_stem = checklist_path.stem
        try:
            checklist_rel = str(checklist_path.relative_to(self.tree.notes_dir))
        except ValueError:
            checklist_rel = checklist_path.name
        now = datetime.now(timezone.utc).isoformat()
        wiki_dir = Path(self.tree.notes_dir) / self.wiki_dirname
        wiki_dir.mkdir(parents=True, exist_ok=True)
        target = wiki_dir / filename
        if target.exists():
            raise FileExistsError(f"摘录卡已存在: {target}")
        metadata: Dict[str, Any] = {
            "type": EXCERPT_TYPE,
            "title": title,
            "from": f"[[{checklist_stem}]]",
            "created": now,
            "source": PROMOTED_SOURCE,
            "tags": [ITEM_TAG],
            "status": "stable",  # 勾选即批准（draft 态只属于 distill 送审流）
            # OKF Freshness（2026-09-18 全量采纳）：半年后到期复查
            "stale_after": (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d"),
            "generated": {"by": "atelierr-highlights/1.0", "at": now},
            "verified": [{"by": "human:cj1024", "at": now}],
            "sources": [
                {
                    "id": checklist_stem,
                    "resource": checklist_rel,
                    "title": checklist_stem,
                }
            ],
        }
        if page:
            metadata["page"] = page
        text = frontmatter.dumps(frontmatter.Post(body, **metadata))
        fd, tmp_path = tempfile.mkstemp(dir=str(wiki_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_path, target)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _build_card_body(
        checklist_stem: str, body: str, match: re.Match, title: str, page: int
    ) -> str:
        """组装摘录卡正文：候选详情块 + 来源双链。"""
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
            f"> 来源：[[{checklist_stem}]]（划重点清单{anchor}，人工勾选）",
            "",
            # 勾的瞬间想法最新鲜（2026-09-14 KM 评审 P2）：引导顺手写一句
            "> 我的想法：",
            "",
        ]
        lines += details or ["（清单中未附详情行）"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _card_filename(checklist_name: str, title: str) -> str:
        """摘录卡文件名：摘录-<净化标题>-<清单哈希前6>.md（跨清单防撞名）。"""
        cleaned = _ILLEGAL_RE.sub("-", title).strip(". ")[:40] or "未命名"
        digest = hashlib.sha1(checklist_name.encode("utf-8")).hexdigest()[:6]
        return f"摘录-{cleaned}-{digest}.md"

    @staticmethod
    def _load_post(note_path: Path) -> Optional[Any]:
        """读取笔记 frontmatter；损坏/不可读返回 None（跳过不阻塞）。"""
        try:
            return frontmatter.loads(note_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _load_state(self) -> Dict[str, Any]:
        """加载转记状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
