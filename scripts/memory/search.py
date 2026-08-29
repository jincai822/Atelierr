"""记忆搜索：全文/标签/日期/层级过滤，按 confidence 降序。

性能关键路径：query 过滤用原始文本大小写不敏感子串匹配（不解析
frontmatter）；confidence 用 live 重算（stat mtime + sidecar）；
只对前 limit 个结果物化 Memory 对象。增量索引按 (mtime_ns, size)
缓存原始文本，物化结果按 (path, mtime_ns) 缓存。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
from scripts.utils.date_utils import local_timezone, parse_date


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

    def __init__(self, memory_tree: "MemoryTree") -> None:  # noqa: F821
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
        #: path -> (mtime_ns, size, raw_text)
        self._raw_cache: Dict[Path, Tuple[int, int, str]] = {}
        #: path -> (mtime_ns, size, 静态物化字段 dict)
        self._object_cache: Dict[Path, Tuple[int, int, Dict[str, Any]]] = {}
        #: 本地时区（避免热路径反复取当前时区）
        self._tz = local_timezone()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _candidate_files(self) -> List[Path]:
        """列出候选笔记文件，并清理已消失文件的缓存。

        缓存只按当前 glob 结果查询，已消失文件的条目不会被访问；
        仅在文件数与缓存数不一致时才做一次清理，避免每次全量扫描。
        """
        files = [
            path
            for path in sorted(self.tree.notes_dir.glob("*.md"))
            if not path.name.startswith(".")
        ]
        if len(files) != len(self._raw_cache):
            current = set(files)
            for path in list(self._raw_cache):
                if path not in current:
                    self._raw_cache.pop(path, None)
                    self._object_cache.pop(path, None)
        return files

    @staticmethod
    def _safe_stat(path: Path):
        """stat；文件消失返回 None。"""
        try:
            return path.stat()
        except OSError:
            return None

    def _entry_map(self) -> Dict[str, dict]:
        """按文件名建立 sidecar 条目查询表（每次搜索构建一次，O(n)）。

        Returns:
            Dict[str, dict]: 文件名 → sidecar 条目。
        """
        return {
            entry.get("path"): entry
            for entry in self.tree._load_index().values()
            if entry.get("path")
        }

    def _raw_text(self, path: Path, stat) -> Optional[str]:
        """按 (mtime_ns, size) 增量读取原始文本；mtime 未变不重读。"""
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._raw_cache.get(path)
        if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
            return cached[2]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        self._raw_cache[path] = (key[0], key[1], text)
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
        path: Path,
        entry: Optional[dict],
        references: int,
        stat,
    ) -> float:
        """live 重算 confidence（复用候选的 stat，纯浮点运算）。"""
        modified = datetime.fromtimestamp(stat.st_mtime, tz=self._tz)
        accessed = None
        if entry is not None and entry.get("last_accessed"):
            try:
                accessed = parse_date(entry["last_accessed"])
            except ValueError:
                accessed = None
        return self.calculator.calculate(
            {"accessed": accessed, "modified": modified, "references": references}
        )

    def _materialize(
        self,
        path: Path,
        confidence: float,
        layer: str,
        text: str,
    ) -> Optional[Memory]:
        """物化 Memory 对象；静态字段按 (path, mtime_ns, size) 缓存。

        size 作为次级信号：粗粒度 mtime 的文件系统上，同一秒内的改写
        不会改变 mtime_ns，但仍会改变文件大小，据此让缓存失效。
        """
        try:
            stat = path.stat()
        except OSError:
            return None
        cache_key = (stat.st_mtime_ns, stat.st_size)
        cached = self._object_cache.get(path)
        if cached is not None and cached[0] == cache_key[0] and cached[1] == cache_key[1]:
            static = cached[2]
        else:
            post = self._parse_post(text)
            if post is None:
                return None
            created = post.metadata.get("created")
            static = {
                "title": str(post.metadata.get("title") or path.stem),
                "content": post.content.strip(),
                "tags": [str(tag) for tag in (post.metadata.get("tags") or [])],
                "created": parse_date(created) if created is not None else None,
                "id": str(post.metadata["id"]) if post.metadata.get("id") is not None else None,
            }
            self._object_cache[path] = (cache_key[0], cache_key[1], static)
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

        texts: Dict[Path, str] = {}
        stats: Dict[Path, Any] = {}
        for path in self._candidate_files():
            stat = self._safe_stat(path)
            if stat is None:
                continue
            text = self._raw_text(path, stat)
            if text is None:
                continue
            if query_lower and query_lower not in text.lower():
                continue
            texts[path] = text
            stats[path] = stat

        need_frontmatter = bool(tags) or bool(date_from) or bool(date_to)
        scored: List[Tuple[float, Path, str, str]] = []
        for path, text in texts.items():
            entry = entry_map.get(path.name)
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
            confidence = self._live_confidence(path, entry, references, stats[path])
            scored.append((confidence, path, text, note_layer))

        scored.sort(key=lambda item: (-item[0], str(item[1])))
        results: List[Memory] = []
        for confidence, path, text, note_layer in scored[:limit]:
            memory = self._materialize(path, confidence, note_layer, text)
            if memory is not None:
                results.append(memory)
        return results
