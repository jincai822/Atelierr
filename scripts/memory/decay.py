"""记忆衰减：反链扫描、无状态重算 confidence、分层与待删标记、报告。

只写 sidecar 与报告文件，绝不改动笔记文件（内容与 mtime 均不变）。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
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
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _list_md_files(self) -> List[Path]:
        """列出笔记目录根层的 .md 文件（跳过点开头的隐藏文件）。"""
        return [
            path
            for path in sorted(self.tree.notes_dir.glob("*.md"))
            if not path.name.startswith(".")
        ]

    def _recompute(
        self,
        path: Path,
        entry: Optional[dict],
        references: int = 0,
    ) -> Tuple[float, str, bool]:
        """无状态重算单个笔记的 confidence / layer / pending。"""
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
            }
        )
        layer = self.tree.settings.assign_layer(confidence)
        pending = confidence < self.tree.settings.delete_threshold
        return confidence, layer, pending

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
            path = self.tree.notes_dir / entry["path"]
            if not path.exists():
                continue
            _, layer, pending = self._recompute(
                path, entry, references=entry.get("references", 0)
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
        counts = {"short_term": 0, "mid_term": 0, "long_term": 0}
        total = 0

        for path in self._list_md_files():
            note_id = self.tree._read_note_id(path)
            if note_id is None:
                skipped.append(path)
                continue
            entry = self.tree._entry(path)
            refs = references.get(path, 0)
            confidence, layer, pending = self._recompute(path, entry, references=refs)
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
                    self.tree._register(
                        path,
                        note_id,
                        confidence=confidence,
                        layer=layer,
                        references=refs,
                        pending_delete=pending,
                    )
                else:
                    entry.update(
                        confidence=confidence,
                        layer=layer,
                        references=refs,
                        pending_delete=pending,
                    )

        report_path: Optional[Path] = None
        if not dry_run:
            self.tree._save_index()
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
            "dry_run": dry_run,
        }
        if report_path is not None:
            result["report_path"] = str(report_path)
        return result

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
                f"- {Path(item['path']).name}: {item['from_layer']} → {item['to_layer']}"
                for item in transitions
            )
        else:
            lines.append("- （无迁移）")
        lines += ["", "## 待删除（pending_delete）"]
        if pending_paths:
            lines.extend(f"- {path.name}" for path in pending_paths)
        else:
            lines.append("- （无）")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
