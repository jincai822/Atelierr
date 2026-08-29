"""笔记目录 watcher：新文件归一化登记、外部删除清理、损坏跳过。

归一化（一次性补写 frontmatter）后用 os.utime 还原 mtime，避免污染
衰减的 modified 信号。机器绝不删除笔记文件。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import frontmatter

from scripts.memory.core import generate_id
from scripts.utils.date_utils import local_timezone

logger = logging.getLogger(__name__)


def _iso_from_mtime(mtime_ns: int) -> str:
    """把 mtime 纳秒值转成本地时区 ISO 字符串（秒精度）。"""
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=local_timezone()).isoformat(
        timespec="seconds"
    )


class MemoryWatcher:
    """对齐笔记目录与 sidecar 索引；可常驻监听文件系统事件。

    Attributes:
        tree: 关联的 MemoryTree。
        source: 归一化时写入 frontmatter 的默认来源（默认 "web"）。
    """

    def __init__(self, memory_tree: "MemoryTree", source: str = "web") -> None:  # noqa: F821
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
            source: 新文件归一化的默认 source。
        """
        self.tree = memory_tree
        self.source = source
        self._observer: Optional[object] = None

    # ------------------------------------------------------------------
    # 对齐逻辑
    # ------------------------------------------------------------------

    def process_pending(self) -> Dict:
        """全量对齐 notes_dir 与 sidecar 索引。

        新 .md 文件（未登记）：缺 frontmatter 或缺 id 的一次性归一化
        （补写 id/title/created/source/tags，os.utime 还原 mtime）后登记；
        已有合法 frontmatter+id 的只登记、文件一字节不动。sidecar 中
        path 对应的文件已消失的移除条目。frontmatter YAML 损坏的文件
        跳过并记录日志，不中断。

        Returns:
            Dict: normalized / registered / deregistered / skipped 各为
                路径列表。
        """
        result: Dict[str, List] = {
            "normalized": [],
            "registered": [],
            "deregistered": [],
            "skipped": [],
        }
        index = self.tree._load_index()
        indexed_names = {entry.get("path") for entry in index.values()}
        for path in sorted(self.tree.notes_dir.glob("*.md")):
            if path.name.startswith("."):
                continue
            if path.name in indexed_names:
                continue
            self._process_new_file(path, index, result)
        # 注销：sidecar 有条目但文件已消失
        for note_id, entry in list(index.items()):
            if not (self.tree.notes_dir / entry["path"]).exists():
                del index[note_id]
                result["deregistered"].append(entry["path"])
        self.tree._save_index()
        return result

    def _process_new_file(self, path: Path, index: Dict, result: Dict) -> None:
        """处理单个未登记文件：归一化或仅登记。"""
        try:
            mtime_ns = path.stat().st_mtime_ns
            text = path.read_text(encoding="utf-8")
            post = frontmatter.loads(text)
        except Exception as exc:  # noqa: BLE001 - 损坏 frontmatter 跳过
            logger.warning("跳过无法解析的文件 %s: %s", path, exc)
            result["skipped"].append(path)
            return
        note_id = post.metadata.get("id")
        if note_id is None:
            note_id = self._normalize(path, post, mtime_ns)
            result["normalized"].append(path)
        else:
            result["registered"].append(path)
        self.tree._register(path, str(note_id))

    def _normalize(self, path: Path, post, mtime_ns: int) -> str:
        """一次性补写 frontmatter（id/title/created/source/tags）并还原 mtime。"""
        post.metadata["id"] = generate_id()
        post.metadata.setdefault("title", path.stem)
        post.metadata.setdefault("created", _iso_from_mtime(mtime_ns))
        post.metadata.setdefault("source", self.source)
        post.metadata.setdefault("tags", [])
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        os.utime(path, ns=(mtime_ns, mtime_ns))
        return str(post.metadata["id"])

    # ------------------------------------------------------------------
    # 常驻监听
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动基于 watchdog Observer 的常驻文件系统监听。

        事件（created/moved/deleted）统一转发到 process_pending()。
        """
        if self._observer is not None:
            return
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class _Handler(FileSystemEventHandler):
            def __init__(self, watcher: "MemoryWatcher") -> None:
                self.watcher = watcher

            def on_created(self, event) -> None:
                self.watcher.process_pending()

            def on_moved(self, event) -> None:
                self.watcher.process_pending()

            def on_deleted(self, event) -> None:
                self.watcher.process_pending()

        observer = Observer()
        observer.schedule(_Handler(self), str(self.tree.notes_dir), recursive=False)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        """停止监听并等待 observer 线程退出。"""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
