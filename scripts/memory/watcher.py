"""笔记目录 watcher：新文件归一化登记、移动迁移、外部删除清理、损坏跳过。

归一化（一次性补写 frontmatter）后用 os.utime 还原 mtime，避免污染
衰减的 modified 信号。机器绝不删除/移动笔记文件；用户在 Obsidian
手动把笔记拖进归档子目录（如 抖音/）后，watcher 靠 frontmatter id
认出"老文件的新位置"，把 sidecar 条目迁移到新相对路径——动态状态
（created/last_accessed/confidence/references 等）原样保留，不当作
新文件重登记。wiki/attachments/trash 等特殊目录不参与扫描。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import frontmatter

from scripts.memory.core import generate_id, iter_note_files
from scripts.utils.date_utils import local_timezone

if TYPE_CHECKING:
    from scripts.memory.core import MemoryTree

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

    def __init__(self, memory_tree: "MemoryTree", source: str = "web") -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
            source: 新文件归一化的默认 source。
        """
        self.tree = memory_tree
        self.source = source
        # watchdog 的 Observer 是平台相关别名（Linux 上 = InotifyObserver），
        # mypy 将其视为变量而非类型，故注解用 Any
        self._observer: Optional[Any] = None

    # ------------------------------------------------------------------
    # 对齐逻辑
    # ------------------------------------------------------------------

    def process_pending(self) -> Dict:
        """全量对齐 notes_dir（含归档子目录）与 sidecar 索引。

        递归扫描所有笔记 .md（排除 wiki/attachments/trash 与隐藏
        目录）。对每个未登记相对路径的文件：

        - frontmatter id 已存在于索引（用户把笔记移/复制到新路径）
          → 迁移：仅更新该条目的 path 为新相对路径，动态状态原样
          保留（created/last_accessed/confidence/references 不丢，
          不当作新文件重登记），计入 migrated；
        - 缺 frontmatter 或缺 id 的新文件 → 一次性归一化（补写
          id/title/created/source/tags，os.utime 还原 mtime）后登记；
        - 已有合法 frontmatter+id 的新文件 → 只登记、文件一字节不动。

        sidecar 中 path 对应的文件已消失的移除条目。frontmatter YAML
        损坏的文件跳过并记录日志，不中断。

        Returns:
            Dict: normalized / registered / migrated / deregistered /
                skipped 各为路径列表。
        """
        result: Dict[str, List] = {
            "normalized": [],
            "registered": [],
            "migrated": [],
            "deregistered": [],
            "skipped": [],
        }
        index = self.tree._load_index()
        indexed = {str(entry.get("path")) for entry in index.values()}
        for path in iter_note_files(self.tree.notes_dir):
            rel = self.tree._rel_key(path)
            if rel in indexed:
                continue
            self._process_new_file(path, rel, index, result)
        # 注销：sidecar 有条目但文件已消失（迁移过的旧路径在此清理）
        for note_id, entry in list(index.items()):
            if not (self.tree.notes_dir / entry["path"]).exists():
                del index[note_id]
                result["deregistered"].append(entry["path"])
        self.tree._save_index()
        return result

    def _process_new_file(
        self, path: Path, rel: str, index: Dict, result: Dict
    ) -> None:
        """处理单个未登记文件：迁移 / 归一化 / 仅登记。"""
        try:
            mtime_ns = path.stat().st_mtime_ns
            text = path.read_text(encoding="utf-8")
            post = frontmatter.loads(text)
        except Exception as exc:  # noqa: BLE001 - 损坏 frontmatter 跳过
            logger.warning("跳过无法解析的文件 %s: %s", path, exc)
            result["skipped"].append(path)
            return
        note_id = post.metadata.get("id")
        if note_id is not None:
            existing = index.get(str(note_id))
            if existing is not None and existing.get("path") != rel:
                # 用户手动移动/复制：条目迁移到新路径，动态状态原样保留
                logger.info("迁移索引条目 %s -> %s", existing.get("path"), rel)
                existing["path"] = rel
                result["migrated"].append(path)
                return
            result["registered"].append(path)
        else:
            note_id = self._normalize(path, post, mtime_ns)
            result["normalized"].append(path)
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

        递归监听整个 notes_dir（含归档子目录）：事件
        （created/moved/deleted）统一转发到 process_pending()（幂等
        全量对齐，特殊目录里的事件也会触发，无副作用）。
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
        observer.schedule(_Handler(self), str(self.tree.notes_dir), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        """停止监听并等待 observer 线程退出。"""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
