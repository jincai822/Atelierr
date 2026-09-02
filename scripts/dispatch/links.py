"""链接自动分发：扫描笔记中的抖音/小红书链接 → 抓取转写 → 建"待确认"笔记。

定位：独立顶层组合模块（composition root），是 memory 与 processors
之间唯一的接线点（两者互不 import）。触发由 systemd 定时器驱动
（docker/systemd/atelierr-links.*，每 15 分钟一次）；**人工确认在
产出端**：自动创建的笔记带 ``tags=["待确认"]``，人在 Obsidian 阅读
转写内容后自行移除标签，系统不做进一步状态机。

纪律（与 DEVELOPMENT-PLAN-3MVP.md backlog 约定一致）：
- 只新增笔记，绝不改写/移动/删除既有笔记（源笔记原样保留）；
- 幂等：URL 处理状态记录于 ``<state_dir>/processed_links.json``，
  同一链接只成功处理一次；自动产出笔记（source: link）不回收，
  其来源行链接（落地页 URL 与短链字符串不同）不会自我循环；
- 失败最多重试 3 次，超限标记 failed 不再重试——避免 Whisper 模型
  每 15 分钟为空转反复加载；
- pending_delete 笔记跳过；
- 扫描前先 process_pending() 登记新同步来的裸笔记（与每日 sync 同源）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import frontmatter

from scripts.memory.core import LAYERS, MemoryTree
from scripts.memory.watcher import MemoryWatcher
from scripts.processors.link import LinkProcessor, URL_RE, detect_platform

#: 单个 URL 的最大处理尝试次数（超限标记 failed）
MAX_ATTEMPTS = 3

#: 自动产出笔记的标签（人工确认后由人移除）
REVIEW_TAG = "待确认"

#: 分发支持的平台 → 产出笔记的平台标签
_PLATFORM_TAGS = {"douyin": "抖音", "xhs": "小红书"}

#: 自动产出笔记的 source 值；这类笔记是"产出"不是"输入"，其中的来源行
#: 链接不再回收（短链与落地页 URL 字符串不同，仅靠状态去重挡不住自我循环，
#: 2026-09-02 小红书真实样本踩坑）
_AUTO_NOTE_SOURCE = "link"


class LinkDispatcher:
    """扫描全部笔记，把未处理的抖音链接分发给 LinkProcessor。

    Attributes:
        tree: MemoryTree 实例。
        state_path: URL 处理状态文件（processed_links.json）。
    """

    def __init__(
        self,
        tree: MemoryTree,
        processor_factory: Optional[Callable[[], LinkProcessor]] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            processor_factory: 处理器工厂（测试注入假处理器用），
            缺省为 LinkProcessor。
        """
        self.tree = tree
        self._factory = processor_factory or LinkProcessor
        self.state_path = Path(tree.state_dir) / "processed_links.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与分发。

        Args:
            dry_run: 只报告不处理（不建笔记、不写状态）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/found/created/failed/skipped）。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "found": 0,
            "created": [],
            "failed": [],
            "skipped": 0,
        }
        for url in self._collect_urls(report):
            entry = state.get(url)
            if entry and entry.get("status") in ("done", "failed"):
                report["skipped"] += 1
                continue
            report["found"] += 1
            if dry_run:
                continue
            self._process_one(url, state, report)
        if not dry_run:
            self._save_state(state)
        return report

    def _collect_urls(self, report: Dict[str, Any]) -> List[str]:
        """扫描全部已登记笔记正文，收集去重后的支持平台链接（保持出现顺序）。

        跳过 pending_delete 笔记与自动产出笔记（source: link）——后者是
        产出而非输入，其来源行里的链接（落地页 URL 与原短链字符串不同）
        不回收，杜绝自我循环。
        """
        urls: List[str] = []
        seen = set()
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                if self.tree.is_pending_delete(note_path):
                    continue
                if self._is_auto_note(note_path):
                    continue
                report["scanned"] += 1
                body = self.tree.read_note(note_path)
                for match in URL_RE.finditer(body):
                    url = match.group(0)
                    if detect_platform(url) in _PLATFORM_TAGS and url not in seen:
                        seen.add(url)
                        urls.append(url)
        return urls

    @staticmethod
    def _is_auto_note(note_path: Path) -> bool:
        """是否自动产出笔记（frontmatter source 为 link）；损坏按人工笔记处理。"""
        try:
            post = frontmatter.loads(Path(note_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏不误跳过
            return False
        return str(post.get("source") or "") == _AUTO_NOTE_SOURCE

    def _process_one(
        self, url: str, state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """处理单个链接：成功建笔记，失败计次数（3 次熔断）。"""
        entry = state.setdefault(url, {"attempts": 0})
        entry["attempts"] += 1
        result = self._factory().process(url)
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if result.success:
            platform = detect_platform(url) or "link"
            doc_id = str(
                result.metadata.get("video_id") or result.metadata.get("note_id") or ""
            )
            title = str(result.metadata.get("title") or "")
            filename = self._note_filename(url, platform, doc_id, title)
            try:
                self.tree.create_note(
                    filename,
                    result.markdown,
                    source="link",
                    tags=[REVIEW_TAG, _PLATFORM_TAGS.get(platform, "链接")],
                )
            except FileExistsError:
                # 同名不同源（标题撞车）：追加内容 id 短码再试一次；
                # 仍冲突视为同内容重跑（状态丢失后的重放），不再建
                if doc_id:
                    filename = self._note_filename(
                        url, platform, doc_id, f"{title}-{doc_id[:6]}" if title else ""
                    )
                try:
                    self.tree.create_note(
                        filename,
                        result.markdown,
                        source="link",
                        tags=[REVIEW_TAG, _PLATFORM_TAGS.get(platform, "链接")],
                    )
                except (ValueError, FileExistsError):
                    pass
            except ValueError:
                pass
            entry["status"] = "done"
            entry["note"] = filename
            report["created"].append(filename)
            return
        entry["last_error"] = (result.error or "")[:300]
        if entry["attempts"] >= MAX_ATTEMPTS:
            entry["status"] = "failed"
        report["failed"].append({"url": url, "error": result.error})

    @staticmethod
    def _note_filename(url: str, platform: str, doc_id: str, title: str = "") -> str:
        """产出笔记文件名：<平台中文>-<标题>.md（人读优先）。

        标题做文件系统净化（半框非法字符转 -、压缩空白、截 60 字）；
        无标题回退 <平台>-<内容id>.md；两者皆无回退 URL 短哈希。
        """
        label = _PLATFORM_TAGS.get(platform, platform)
        if title:
            safe = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", title)
            safe = re.sub(r"\s+", " ", safe).strip().strip(".")
            if len(safe) > 60:
                safe = safe[:60].rstrip()
            if safe:
                return f"{label}-{safe}.md"
        if doc_id:
            return f"{platform}-{doc_id}.md"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        return f"{platform}-{digest}.md"

    def _load_state(self) -> Dict[str, Any]:
        """加载 URL 处理状态；文件缺失/损坏返回空表（不抛异常）。"""
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
