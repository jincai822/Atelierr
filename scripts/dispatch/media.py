"""附件自动路由：attachments/ 里的截图/录音 → OCR/Whisper → 建"待确认"笔记。

定位：与 links/todos 同源的 dispatch 顶层组合模块（memory 与 processors
之间唯一的接线点）。触发由 systemd 定时器驱动
（docker/systemd/atelierr-links.*，每 15 分钟一次）；人工确认在产出端：
自动创建的笔记带 ``tags=["待确认"]``，人在 Obsidian 阅读后自行移除标签。

典型路径：手机截图/录音 → Obsidian 附件目录 → Syncthing 同步到电脑
→ 本模块识别 → 建笔记（内嵌原附件 ``![[attachments/xxx]]``，Obsidian
里图片直接显示、录音直接可播）→ 正文同时进入 todos 分发的扫描范围
（截图里有行动意图时自动抽取待办）。

纪律（与 links.py 一致）：
- 只新增笔记，绝不改写/移动/删除既有笔记与附件本身；
- 幂等：附件处理状态记录于 ``<state_dir>/processed_media.json``，
  以附件相对路径为键，同一文件只成功处理一次（文件内容变化不重新
  处理——手机附件一旦同步即不可变）；
- 失败最多重试 3 次，超限标记 failed 不再重试——避免 PaddleOCR/Whisper
  模型每 15 分钟为空转反复加载；
- mtime 距今不足 30 秒的文件跳过（防人工拷贝中途读到半个文件；
  Syncthing 本身是临时文件+改名，天然原子）；
- 引擎实例每轮运行只构造一次（PaddleOCR/Whisper 模型加载昂贵）。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.memory.core import MemoryTree
from scripts.processors.audio import SUPPORTED_EXTENSIONS as AUDIO_EXTS
from scripts.processors.audio import AudioProcessor
from scripts.processors.image import SUPPORTED_EXTENSIONS as IMAGE_EXTS
from scripts.processors.image import ImageProcessor

#: 单个附件的最大处理尝试次数（超限标记 failed）
MAX_ATTEMPTS = 3

#: 自动产出笔记的标签（人工确认后由人移除）
REVIEW_TAG = "待确认"

#: 附件目录名（相对笔记根目录）
ATTACHMENTS_DIR = "attachments"

#: 跳过 mtime 距今不足该秒数的文件（防读到仍在写入的文件）
MIN_AGE_SECONDS = 30

_KIND_BY_EXT = {ext: "截图" for ext in IMAGE_EXTS}
_KIND_BY_EXT.update({ext: "录音" for ext in AUDIO_EXTS})


class MediaDispatcher:
    """扫描 attachments/ 目录，把新截图/录音分发给 OCR/Whisper 处理器。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 附件处理状态文件（processed_media.json）。
    """

    def __init__(
        self,
        tree: MemoryTree,
        image_factory: Optional[Callable[[], ImageProcessor]] = None,
        audio_factory: Optional[Callable[[], AudioProcessor]] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            image_factory: 图片处理器工厂（测试注入假处理器用），
            缺省为 ImageProcessor；每轮运行最多构造一次。
            audio_factory: 音频处理器工厂，缺省为 AudioProcessor。
        """
        self.tree = tree
        self._image_factory = image_factory or ImageProcessor
        self._audio_factory = audio_factory or AudioProcessor
        self._image: Optional[ImageProcessor] = None
        self._audio: Optional[AudioProcessor] = None
        self.state_path = Path(tree.state_dir) / "processed_media.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与分发。

        Args:
            dry_run: 只报告不处理（不建笔记、不写状态、不加载引擎）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/found/created/failed/skipped）。
        """
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "found": 0,
            "created": [],
            "failed": [],
            "skipped": 0,
        }
        for path in self._collect_files(report):
            key = self._key(path)
            entry = state.get(key)
            if entry and entry.get("status") in ("done", "failed"):
                report["skipped"] += 1
                continue
            report["found"] += 1
            if dry_run:
                continue
            self._process_one(path, state, report)
        if not dry_run:
            self._save_state(state)
        return report

    def _collect_files(self, report: Dict[str, Any]) -> List[Path]:
        """列出 attachments/ 下全部可处理附件（按修改时间升序）。"""
        attach_dir = Path(self.tree.notes_dir) / ATTACHMENTS_DIR
        if not attach_dir.is_dir():
            return []
        now = time.time()
        files: List[Path] = []
        for path in sorted(attach_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in _KIND_BY_EXT:
                continue
            report["scanned"] += 1
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime < MIN_AGE_SECONDS:
                continue  # 太新：可能仍在写入，下轮再处理（不计 found）
            files.append(path)
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    def _process_one(
        self, path: Path, state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """处理单个附件：成功建笔记，失败计次数（3 次熔断）。"""
        key = self._key(path)
        entry = state.setdefault(key, {"attempts": 0})
        entry["attempts"] += 1
        kind = _KIND_BY_EXT[path.suffix.lower()]
        processor = self._get_processor(path)
        result = processor.process(path)
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if result.success:
            filename = self._note_filename(path)
            try:
                self.tree.create_note(
                    filename,
                    self._build_note(path, kind, result.text),
                    source="media",
                    tags=[REVIEW_TAG, kind],
                )
            except (ValueError, FileExistsError):
                # 同名笔记已存在（状态丢失后的重跑）：视为已处理
                pass
            entry["status"] = "done"
            entry["note"] = filename
            report["created"].append(filename)
            return
        entry["last_error"] = (result.error or "")[:300]
        if entry["attempts"] >= MAX_ATTEMPTS:
            entry["status"] = "failed"
        report["failed"].append({"file": key, "error": result.error})

    def _get_processor(self, path: Path):
        """按扩展名取处理器实例（每轮每类只构造一次，引擎加载昂贵）。"""
        if path.suffix.lower() in IMAGE_EXTS:
            if self._image is None:
                self._image = self._image_factory()
            return self._image
        if self._audio is None:
            self._audio = self._audio_factory()
        return self._audio

    @staticmethod
    def _key(path: Path) -> str:
        """状态键：附件相对笔记根目录的路径（如 attachments/IMG_001.jpg）。"""
        return f"{ATTACHMENTS_DIR}/{path.name}"

    @staticmethod
    def _note_filename(path: Path) -> str:
        """产出笔记文件名：media-<文件日期>-<路径哈希前6>.md。"""
        date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
        digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:6]
        return f"media-{date}-{digest}.md"

    @staticmethod
    def _build_note(path: Path, kind: str, text: str) -> str:
        """组装笔记正文：内嵌原附件 + 提取全文（录音带书名号标点）。"""
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        section = "OCR 全文" if kind == "截图" else "转写全文"
        return (
            f"# {kind} {stamp}\n\n"
            f"![[{ATTACHMENTS_DIR}/{path.name}]]\n\n"
            f"## {section}\n\n"
            f"{(text or '').strip()}\n"
        )

    def _load_state(self) -> Dict[str, Any]:
        """加载附件处理状态；文件缺失/损坏返回空表（不抛异常）。"""
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
