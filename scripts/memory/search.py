"""记忆搜索：全文/标签/日期/层级过滤，按 confidence 降序。

性能关键路径：os.scandir 枚举（DirEntry.stat 无 Path 构造开销）；
query 过滤用缓存的小写副本做子串匹配（不解析 frontmatter）；
confidence 用 live 重算（epoch 浮点快速路径）；只对前 limit 个
结果物化 Memory 对象。增量索引按 (mtime_ns, size) 缓存原始文本，
物化结果按 (文件名, mtime_ns, size) 缓存。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
from scripts.utils.date_utils import parse_date

if TYPE_CHECKING:
    from scripts.memory.core import MemoryTree


@dataclass
class Memory:
    """单条搜索结果的物化视图。

    Attributes:
        path: 笔记文件路径。
        title: frontmatter 标题（缺省为文件名 stem）。
        content: 笔记正文（不含 frontmatter）。
        tags: 标签列表。
        created: frontmatter created（解析为 datetime，可为 None）。
        confidence: live 重算的 confidence。
        layer: sidecar 层级（未登记视为 short-term）。
        id: frontmatter id（可为 None）。
    """

    path: Path
    title: str = ""
    content: str = ""
    tags: List[str] = field(default_factory=list)
    created: Optional[datetime] = None
    confidence: float = 0.0
    layer: str = "short-term"
    id: Optional[str] = None


class MemorySearcher:
    """搜索器：增量读缓存 + live confidence 重算 + 惰性物化。"""

    def __init__(self, memory_tree: "MemoryTree") -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
        """
        self.tree = memory_tree
        settings = memory_tree.settings
        self.calculator = ConfidenceCalculator(
            decay_rate=settings.decay_rate,
            ref_coefficient=settings.ref_coefficient,
            ref_cap=settings.ref_cap,
        )
        #: 文件名 -> (mtime_ns, size, raw_text, raw_text_lower)
        self._raw_cache: Dict[str, Tuple[int, int, str, str]] = {}
        #: 文件名 -> (mtime_ns, size, 静态物化字段 dict)
        self._object_cache: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _scan_candidates(self) -> Dict[str, Any]:
        """os.scandir 枚举候选 .md 文件：返回 文件名 -> stat 结果。

        DirEntry.stat() 比 pathlib 轻量（避免逐文件构造 Path 对象）。
        已消失文件的缓存条目在此处清理（仅当数量不一致时扫描缓存）。
        """
        found: Dict[str, Any] = {}
        try:
            with os.scandir(self.tree.notes_dir) as entries:
                for dent in entries:
                    name = dent.name
                    if name.startswith(".") or not name.endswith(".md"):
                        continue
                    try:
                        if not dent.is_file():
                            continue
                        found[name] = dent.stat()
                    except OSError:  # 枚举期间文件被删
                        continue
        except OSError:  # 笔记目录不可读
            return {}
        if len(found) != len(self._raw_cache):
            for name in list(self._raw_cache):
                if name not in found:
                    self._raw_cache.pop(name, None)
                    self._object_cache.pop(name, None)
        return found

    def _entry_map(self) -> Dict[str, dict]:
        """按文件名建立 sidecar 条目查询表（每次搜索构建一次，O(n)）。

        Returns:
            Dict[str, dict]: 文件名 → sidecar 条目。
        """
        result: Dict[str, dict] = {}
        for entry in self.tree._load_index().values():
            name = entry.get("path")
            if name:
                result[str(name)] = entry
        return result

    def _raw_text(self, name: str, stat) -> Optional[str]:
        """按 (mtime_ns, size) 增量读取原始文本；mtime 未变不重读。

        缓存同时存原文与小写副本，热路径子串匹配不再重复 lower()。
        """
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._raw_cache.get(name)
        if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
            return cached[2]
        try:
            text = (self.tree.notes_dir / name).read_text(encoding="utf-8")
        except OSError:
            return None
        self._raw_cache[name] = (key[0], key[1], text, text.lower())
        return text

    def _parse_post(self, text: str) -> Optional[Any]:
        """解析 frontmatter；损坏返回 None。"""
        try:
            return frontmatter.loads(text)
        except Exception:  # noqa: BLE001 - 损坏 frontmatter 跳过
            return None

    def _match_tags(self, meta_tags: Any, wanted: List[str]) -> bool:
        """标签过滤：任一命中即算（OR 语义）。"""
        if not meta_tags:
            return False
        current = {str(tag) for tag in meta_tags}
        return any(tag in current for tag in wanted)

    def _match_dates(
        self,
        created: Any,
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> bool:
        """日期过滤：created 的日期部分在 [date_from, date_to] 闭区间。"""
        if created is None:
            return False
        try:
            created_date = parse_date(created).date()
        except ValueError:
            return False
        try:
            if date_from and created_date < _date.fromisoformat(date_from):
                return False
            if date_to and created_date > _date.fromisoformat(date_to):
                return False
        except ValueError:
            return False
        return True

    def _live_confidence(
        self,
        entry: Optional[dict],
        references: int,
        stat,
    ) -> float:
        """live 重算 confidence（epoch 浮点快速路径，纯浮点运算）。

        idle_days 语义与 ConfidenceCalculator.calculate 完全一致：
        ``floor((now - max(mtime, accessed)) / 86400)``，负值经
        from_idle_days 钳 0；只是不逐文件构造 datetime（热路径优化）。
        """
        accessed_ts = 0.0
        if entry is not None and entry.get("last_accessed"):
            try:
                accessed_ts = parse_date(entry["last_accessed"]).timestamp()
            except ValueError:
                accessed_ts = 0.0
        last_active = max(stat.st_mtime, accessed_ts)
        idle_days = int((time.time() - last_active) // 86400)
        return self.calculator.from_idle_days(idle_days, references)

    def _materialize(
        self,
        name: str,
        confidence: float,
        layer: str,
        text: str,
        stat,
    ) -> Optional[Memory]:
        """物化 Memory 对象；静态字段按 (文件名, mtime_ns, size) 缓存。

        size 作为次级信号：粗粒度 mtime 的文件系统上，同一秒内的改写
        不会改变 mtime_ns，但仍会改变文件大小，据此让缓存失效。
        """
        cache_key = (stat.st_mtime_ns, stat.st_size)
        cached = self._object_cache.get(name)
        if (
            cached is not None
            and cached[0] == cache_key[0]
            and cached[1] == cache_key[1]
        ):
            static = cached[2]
        else:
            post = self._parse_post(text)
            if post is None:
                return None
            created = post.metadata.get("created")
            static = {
                "title": str(post.metadata.get("title") or Path(name).stem),
                "content": post.content.strip(),
                "tags": [str(tag) for tag in (post.metadata.get("tags") or [])],
                "created": parse_date(created) if created is not None else None,
                "id": (
                    str(post.metadata["id"])
                    if post.metadata.get("id") is not None
                    else None
                ),
            }
            self._object_cache[name] = (cache_key[0], cache_key[1], static)
        path = self.tree.notes_dir / name
        return Memory(path=path, confidence=confidence, layer=layer, **static)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        layer: Optional[str] = None,
        limit: int = 10,
    ) -> List[Memory]:
        """搜索记忆。

        过滤顺序：原始文本子串（不解析 frontmatter）→ 层级（sidecar）
        → 需 frontmatter 的标签/日期 → 排序取前 limit 后物化。

        Args:
            query: 全文关键词（大小写不敏感子串，覆盖 title+body）。
            tags: 标签列表（OR 语义）。
            date_from: 起始日期 "YYYY-MM-DD"。
            date_to: 结束日期 "YYYY-MM-DD"。
            layer: 逻辑层级过滤。
            limit: 返回条数上限（<= 0 返回空列表）。

        Returns:
            List[Memory]: 按 confidence 降序的结果。
        """
        if limit < 1:
            return []
        query_lower = query.lower().strip() if query else ""
        entry_map = self._entry_map()
        scanned = self._scan_candidates()
        need_frontmatter = bool(tags) or bool(date_from) or bool(date_to)

        scored: List[Tuple[float, str, str, str]] = []
        for name, stat in scanned.items():
            text = self._raw_text(name, stat)
            if text is None:
                continue
            if query_lower and query_lower not in self._raw_cache[name][3]:
                continue
            entry = entry_map.get(name)
            note_layer = entry["layer"] if entry is not None else "short-term"
            if layer and note_layer != layer:
                continue
            if need_frontmatter:
                post = self._parse_post(text)
                if post is None:
                    continue
                if tags and not self._match_tags(post.metadata.get("tags"), tags):
                    continue
                if (date_from or date_to) and not self._match_dates(
                    post.metadata.get("created"), date_from, date_to
                ):
                    continue
            references = entry.get("references", 0) if entry is not None else 0
            confidence = self._live_confidence(entry, references, stat)
            scored.append((confidence, name, text, note_layer))

        # 平面目录下文件名排序等价于完整路径排序（同一前缀）
        scored.sort(key=lambda item: (-item[0], item[1]))
        results: List[Memory] = []
        for confidence, name, text, note_layer in scored[:limit]:
            memory = self._materialize(
                name, confidence, note_layer, text, scanned[name]
            )
            if memory is not None:
                results.append(memory)
        return results
