"""记忆搜索：全文/标签/日期/层级过滤，按 confidence×来源权重 降序。

覆盖顶层与用户手动归档的子目录（wiki/、attachments/、trash/ 等
机器专用目录与隐藏目录除外）。性能关键路径：os.scandir 递归枚举
（DirEntry.stat 无 Path 构造开销）；query 过滤用缓存的小写副本做
子串匹配（不解析 frontmatter）；confidence 用 live 重算（epoch
浮点快速路径）；只对前 limit 个结果物化 Memory 对象。增量索引按
(mtime_ns, size) 缓存原始文本（key 为相对 notes_dir 的路径），
物化结果按 (相对路径, mtime_ns, size) 缓存。

信噪比治理（2026-09-12 用户裁决）：机器搬运来源（MACHINE_SOURCES：
转写/OCR/剪藏全文）排序分 = confidence × MACHINE_SOURCE_WEIGHT，
人写笔记同热度下排在前；机器全文仍可被搜到（拉取不消失），
Memory.confidence 展示的仍是真实 confidence（不含权重）。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
from scripts.memory.core import (
    MACHINE_DECAY_SOURCES,
    MACHINE_SOURCES,
    NOTE_EXCLUDED_DIRS,
    SYNC_CONFLICT_RE,
)
from scripts.utils.date_utils import parse_date

#: 机器搬运来源的排序权重（<1 = 降权）；frontmatter source 行只从
#: 文本头部 400 字符内提取（frontmatter 必在文首，热路径不解析全文）
MACHINE_SOURCE_WEIGHT = 0.85
_SOURCE_RE = re.compile(r"^source:\s*['\"]?([^\s'\"]+)", re.M)

#: 资料全文组（attachments/**/*.md）每次搜索最多返回条数
_REFERENCE_LIMIT = 5

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
    group: str = "notes"  # "notes"=笔记组 / "reference"=资料全文组（方案 B）


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
            source_factors={
                source: settings.machine_decay_factor
                for source in MACHINE_DECAY_SOURCES
            },
        )
        #: 相对路径（notes_dir 下，POSIX / 分隔）-> (mtime_ns, size, raw_text, raw_text_lower)
        self._raw_cache: Dict[str, Tuple[int, int, str, str]] = {}
        #: 相对路径 -> (mtime_ns, size, 静态物化字段 dict)
        self._object_cache: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _scan_candidates(self) -> Dict[str, Any]:
        """递归枚举候选 .md 文件：返回 相对路径 -> stat 结果。

        DirEntry.stat() 比 pathlib 轻量（避免逐文件构造 Path 对象）。
        跳过 wiki/attachments/trash 等特殊目录与隐藏目录/文件；不
        跟随符号链接目录（防环）。已消失文件的缓存条目在此处清理
        （仅当数量不一致时扫描缓存）。
        """

        def _walk(directory: Path, prefix: str) -> None:
            try:
                with os.scandir(directory) as entries:
                    for dent in entries:
                        if dent.name.startswith("."):
                            continue
                        try:
                            if dent.is_dir(follow_symlinks=False):
                                if dent.name not in NOTE_EXCLUDED_DIRS:
                                    _walk(Path(dent.path), prefix + dent.name + "/")
                            elif dent.name.endswith(".md") and not SYNC_CONFLICT_RE.search(
                                dent.name
                            ):
                                found[prefix + dent.name] = dent.stat()
                        except OSError:  # 枚举期间文件被删
                            continue
            except OSError:  # 目录不可读
                pass

        found: Dict[str, Any] = {}
        _walk(self.tree.notes_dir, "")
        # 双根（2026-09-13 拆分）：inbox/ 中转站的卡同样可搜，
        # 键带 inbox/ 前缀（与 sidecar path 编码一致）
        _walk(self.tree.inbox_dir, "inbox/")
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
            text = self.tree._abs(name).read_text(encoding="utf-8")
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
        source: str = "",
    ) -> float:
        """live 重算 confidence（epoch 浮点快速路径，纯浮点运算）。

        idle_days 语义与 ConfidenceCalculator.calculate 完全一致：
        ``floor((now - max(mtime, accessed)) / 86400)``，负值经
        from_idle_days 钳 0；只是不逐文件构造 datetime（热路径优化）。
        source 命中 MACHINE_DECAY_SOURCES 时与 decay 同因子加速
        （方案 C v1.4）——展示值与 sidecar 真值不分叉。
        """
        accessed_ts = 0.0
        if entry is not None and entry.get("last_accessed"):
            try:
                accessed_ts = parse_date(entry["last_accessed"]).timestamp()
            except ValueError:
                accessed_ts = 0.0
        last_active = max(stat.st_mtime, accessed_ts)
        idle_days = int((time.time() - last_active) // 86400)
        return self.calculator.from_idle_days(idle_days, references, source=source)

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
        path = self.tree._abs(name)
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
            List[Memory]: 笔记组在前（confidence×来源权重 降序，机器搬运
            来源降权，Memory.confidence 为真实值不含权重）；query 非空时
            末尾追加资料全文组（group="reference"，attachments/**/*.md
            命中，最多 _REFERENCE_LIMIT 条）。
        """
        if limit < 1:
            return []
        query_lower = query.lower().strip() if query else ""
        entry_map = self._entry_map()
        scanned = self._scan_candidates()
        need_frontmatter = bool(tags) or bool(date_from) or bool(date_to)

        scored: List[Tuple[float, float, str, str, str]] = []
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
            source_match = _SOURCE_RE.search(text[:400])
            source = source_match.group(1) if source_match else ""
            confidence = self._live_confidence(entry, references, stat, source=source)
            if source in MACHINE_SOURCES:
                score = confidence * MACHINE_SOURCE_WEIGHT
            else:
                score = confidence
            scored.append((score, confidence, name, text, note_layer))

        # 排序分降序（同分按相对路径：同目录内按文件名，目录间按目录名）
        scored.sort(key=lambda item: (-item[0], item[2]))
        results: List[Memory] = []
        for score, confidence, name, text, note_layer in scored[:limit]:
            memory = self._materialize(
                name, confidence, note_layer, text, scanned[name]
            )
            if memory is not None:
                results.append(memory)
        results.extend(self._search_reference(query_lower))
        return results

    # ------------------------------------------------------------------
    # 资料全文组（方案 B：attachments/**/*.md 的外置全文）
    # ------------------------------------------------------------------

    def _search_reference(self, query_lower: str) -> List[Memory]:
        """资料全文组：attachments/**/*.md 的子串命中（2026-09-12 方案 B）。

        只在用户显式搜索（query 非空）时触发，不进任何定时班次；
        不算 confidence、不按来源加权——全文文件是资料不是笔记，
        按相对路径排序稳定输出，最多 _REFERENCE_LIMIT 条。
        """
        if not query_lower:
            return []
        attach = self.tree.attachments_dir
        if not attach.is_dir():
            return []
        results: List[Memory] = []
        for path in sorted(attach.rglob("*.md")):
            if any(part.startswith(".") for part in path.parts):
                continue
            if SYNC_CONFLICT_RE.search(path.name):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if query_lower not in text.lower():
                continue
            results.append(
                Memory(
                    path=path,
                    title=path.stem,
                    content=text.strip(),
                    layer="reference",
                    group="reference",
                )
            )
            if len(results) >= _REFERENCE_LIMIT:
                break
        return results
