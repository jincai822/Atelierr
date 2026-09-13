"""记忆衰减：反链扫描、无状态重算 confidence、分层与待删标记、报告。

只写 sidecar 与报告文件，绝不改动笔记文件（内容与 mtime 均不变）。
"""

from __future__ import annotations

from contextlib import nullcontext as _nullcontext

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
from scripts.memory.core import MACHINE_DECAY_SOURCES
from scripts.utils.date_utils import local_timezone, parse_date

if TYPE_CHECKING:
    from scripts.memory.core import MemoryTree

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

#: layer 名 → 报告键名
_LAYER_KEY = {
    "short-term": "short_term",
    "mid-term": "mid_term",
    "long-term": "long_term",
}


class DecayManager:
    """衰减管理器。

    每日任务：全量 [[wikilink]] 反链统计 → 无状态重算 confidence →
    分层/待删标记（只写 sidecar）→ 生成报告。支持 dry-run。
    """

    def __init__(self, memory_tree: "MemoryTree") -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例（calculator 用其 settings 构造）。
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

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _list_md_files(self) -> List[Path]:
        """递归列出全部笔记 .md（排除 wiki/attachments/trash 与隐藏项）。"""
        return list(self.tree.iter_all_note_files())

    @staticmethod
    def _note_source(path: Path) -> Optional[str]:
        """读取 frontmatter 的 source；损坏返回 None。"""
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏 frontmatter 视为无 source
            return None
        source = post.metadata.get("source")
        return str(source) if source is not None else None

    def _recompute(
        self,
        path: Path,
        entry: Optional[dict],
        references: int = 0,
        source: str = "",
    ) -> Tuple[float, str, bool]:
        """无状态重算单个笔记的 confidence / layer / pending。

        source（frontmatter）命中 MACHINE_DECAY_SOURCES 时按方案 C
        因子加速衰减（v1.4）；缺省空串按原速。
        """
        accessed = None
        if entry is not None and entry.get("last_accessed"):
            try:
                accessed = parse_date(entry["last_accessed"])
            except ValueError:
                accessed = None
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=local_timezone())
        confidence = self.calculator.calculate(
            {
                "accessed": accessed,
                "modified": modified,
                "references": references,
                "source": source,
            }
        )
        layer = self.tree.settings.assign_layer(confidence)
        pending = confidence < self.tree.settings.delete_threshold
        return confidence, layer, pending

    def backlink_counts(self) -> Dict[Path, int]:
        """公开的反链统计（只读）：每日衰减的同一份扫描，供 digest
        「沉淀候选」等统计复用——反链逻辑只此一处，禁止另写扫描。

        Returns:
            Dict[Path, int]: 每个笔记文件 → 被不同笔记引用的次数。
        """
        return self._scan_backlinks()

    def _scan_backlinks(self) -> Dict[Path, int]:
        """全量扫描所有 .md 笔记正文的 [[wikilink]] 反链。

        支持 [[target|alias]] 与 [[target#heading]]；按文件名 stem 或
        frontmatter title 精确匹配；统计"有多少个不同笔记引用它"
        （自引用不计）。

        Returns:
            Dict[Path, int]: 每个笔记文件 → 被不同笔记引用的次数。
        """
        files = self._list_md_files()
        keys: Dict[str, Set[Path]] = {}
        texts: Dict[Path, str] = {}
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            texts[path] = text
            match_keys = {path.stem}
            try:
                post = frontmatter.loads(text)
                title = post.metadata.get("title")
                if title:
                    match_keys.add(str(title))
            except Exception:  # noqa: BLE001 - 损坏 frontmatter 仅用 stem 匹配
                pass
            for key in match_keys:
                keys.setdefault(key, set()).add(path)

        referencing: Dict[Path, Set[Path]] = {}
        for path, text in texts.items():
            for match in _WIKILINK_RE.finditer(text):
                target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
                if not target:
                    continue
                for ref_file in keys.get(target, ()):
                    if ref_file is not path:
                        referencing.setdefault(ref_file, set()).add(path)
        return {path: len(referencing.get(path, ())) for path in files}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def scan(self) -> Dict:
        """全量重算已登记笔记并返回分层统计（不写任何状态）。

        Returns:
            Dict: total_notes / short_term / mid_term / long_term /
                pending_delete 计数。
        """
        counts = {
            "total_notes": 0,
            "short_term": 0,
            "mid_term": 0,
            "long_term": 0,
            "pending_delete": 0,
        }
        for entry in self.tree._load_index().values():
            path = self.tree._abs(entry["path"])
            if not path.exists():
                continue
            source = self._note_source(path) or ""
            if source == "system":
                continue  # 与 run() 一致：基础设施笔记不计入衰减统计
            _, layer, pending = self._recompute(
                path, entry, references=entry.get("references", 0), source=source
            )
            counts["total_notes"] += 1
            counts[_LAYER_KEY[layer]] += 1
            if pending:
                counts["pending_delete"] += 1
        return counts

    def run(self, dry_run: bool = False) -> Dict:
        """每日衰减任务。

        步骤：反链统计 → 对每个 .md 笔记无状态重算 confidence →
        定 layer、pending_delete → （非 dry_run）写 sidecar 与报告。
        只写 sidecar/报告，绝不改动笔记文件；无 frontmatter 的裸
        文件跳过计入 skipped；有 frontmatter+id 但未登记的允许纯
        sidecar 登记后处理。

        Args:
            dry_run: True 时不写任何文件（sidecar 与报告都不写）。

        Returns:
            Dict: total_notes / short_term / mid_term / long_term /
                transitions（[{path, from_layer, to_layer}]）/ relayered
                或 would_relayer（计数）/ pending（待删路径列表）/
                skipped / dry_run；非 dry_run 时含 report_path。
        """
        references = self._scan_backlinks()
        transitions: List[Dict] = []
        pending_paths: List[Path] = []
        skipped: List[Path] = []
        system_notes: List[Path] = []
        counts = {"short_term": 0, "mid_term": 0, "long_term": 0}
        total = 0

        # flock 事务内跑整个重算循环（2026-09-13 竞态实证：守护进程与
        # 分发班次的旧缓存回写会丢更新）；dry_run 不锁不写，只读缓存。
        index_ctx = (
            self.tree._index_transaction()
            if not dry_run
            else _nullcontext(self.tree._load_index())
        )

        with index_ctx as index:
         for path in self._list_md_files():
            note_id = self.tree._read_note_id(path)
            if note_id is None:
                skipped.append(path)
                continue
            source = self._note_source(path) or ""
            if source == "system":
                # 基础设施笔记（控制台等）：不衰减、不计数、不置待删
                system_notes.append(path)
                continue
            rel = self.tree._rel_key(path)
            entry = next(
                (item for item in index.values() if item.get("path") == rel), None
            )
            if entry is None:
                # 文件可能已被用户手动移进归档子目录而 watcher 尚未跑：
                # 按 frontmatter id 找回旧条目（避免当新文件重登记——
                # 重登记会重置 last_accessed 等动态状态）
                entry = next(
                    (
                        candidate
                        for nid, candidate in index.items()
                        if nid == str(note_id)
                    ),
                    None,
                )
                if (
                    entry is not None
                    and entry.get("path") != self.tree._rel_key(path)
                    and not dry_run
                ):
                    entry["path"] = self.tree._rel_key(path)  # 顺带迁移
            refs = references.get(path, 0)
            confidence, layer, pending = self._recompute(
                path, entry, references=refs, source=source
            )
            total += 1
            counts[_LAYER_KEY[layer]] += 1
            if pending:
                pending_paths.append(path)
            old_layer = entry["layer"] if entry is not None else None
            if old_layer is not None and old_layer != layer:
                transitions.append(
                    {"path": str(path), "from_layer": old_layer, "to_layer": layer}
                )
            if not dry_run:
                if entry is None:
                    # 直接写事务内 index（不调 tree._register——flock
                    # 事务不可嵌套）
                    index[str(note_id)] = {
                        "path": rel,
                        "confidence": confidence,
                        "layer": layer,
                        "last_accessed": None,
                        "references": refs,
                        "pending_delete": pending,
                    }
                else:
                    entry.update(
                        confidence=confidence,
                        layer=layer,
                        references=refs,
                        pending_delete=pending,
                    )

        report_path: Optional[Path] = None
        if not dry_run:
            report_path = self._write_report(counts, transitions, pending_paths, total)

        result: Dict = {
            "total_notes": total,
            "short_term": counts["short_term"],
            "mid_term": counts["mid_term"],
            "long_term": counts["long_term"],
            "transitions": transitions,
            "relayered": len(transitions) if not dry_run else 0,
            "would_relayer": len(transitions) if dry_run else 0,
            "pending": [str(path) for path in pending_paths],
            "skipped": [str(path) for path in skipped],
            "system": [str(path) for path in system_notes],
            "dry_run": dry_run,
        }
        if report_path is not None:
            result["report_path"] = str(report_path)
        return result

    def _short(self, path: Path) -> str:
        """报告用短路径：notes_dir 内显示相对路径（含子目录前缀）。"""
        try:
            return str(Path(path).relative_to(self.tree.notes_dir))
        except ValueError:
            return Path(path).name

    def _write_report(
        self,
        counts: Dict[str, int],
        transitions: List[Dict],
        pending_paths: List[Path],
        total: int,
    ) -> Path:
        """写衰减报告到 state_dir/reports/decay-YYYY-MM-DD.md。"""
        reports_dir = self.tree.state_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        report_path = reports_dir / f"decay-{today}.md"

        lines = [
            f"# 记忆衰减报告 {today}",
            "",
            f"- 笔记总数: {total}；short-term: {counts['short_term']}；"
            f"mid-term: {counts['mid_term']}；long-term: {counts['long_term']}；"
            f"待删除: {len(pending_paths)}",
            "",
            "## 层级迁移",
        ]
        if transitions:
            lines.extend(
                f"- {self._short(Path(item['path']))}: {item['from_layer']} → {item['to_layer']}"
                for item in transitions
            )
        else:
            lines.append("- （无迁移）")
        lines += ["", "## 待删除（pending_delete）"]
        if pending_paths:
            lines.extend(f"- {self._short(path)}" for path in pending_paths)
        else:
            lines.append("- （无）")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
