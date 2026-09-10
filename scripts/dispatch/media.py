"""附件自动路由：attachments/ 里的截图/录音 → OCR/Whisper → 建"待确认"笔记；
PDF（书籍/长文）→ 划重点清单笔记（机器代读出可勾选候选，勾中条目由
:mod:`scripts.dispatch.highlights` 转为 wiki 摘录卡）。

定位：与 links/todos 同源的 dispatch 顶层组合模块（memory 与 processors
之间唯一的接线点）。触发由 systemd 定时器驱动
（docker/systemd/atelierr-links.*，每 15 分钟一次）；人工确认在产出端：
自动创建的笔记带 ``tags=["待确认"]``，人在 Obsidian 阅读后自行移除标签。

典型路径：手机截图/录音 → Obsidian 附件目录 → Syncthing 同步到电脑
→ 本模块识别 → 建笔记（内嵌原附件 ``![[attachments/媒体/xxx]]``，
Obsidian 里图片直接显示、录音直接可播）→ 正文同时进入 todos 分发的
扫描范围（截图里有行动意图时自动抽取待办）。

原资料归位（2026-09-10 用户裁决 G1）：附件按来源平台分子目录——
``媒体/``（截图/图片/语音）、``书籍/``（PDF）、``抖音/`` ``小红书/``
``B站/``（链接视频，由 links 管线写入，本模块不处理视频）；与笔记归档
目录同一套名字。扫描覆盖 attachments/ 顶层与一层子目录（视频 .mp4 不在
可处理扩展名内，天然跳过）。原件只增不减：本模块绝不删除/移动附件。

纪律（与 links.py 一致）：
- 只新增笔记，绝不改写/移动/删除既有笔记与附件本身；
- 幂等：附件处理状态记录于 ``<state_dir>/processed_media.json``，
  以附件相对笔记根目录路径为键（如 ``attachments/媒体/IMG_001.jpg``），
  同一文件只成功处理一次（文件内容变化不重新处理——手机附件一旦同步
  即不可变）；
- 失败最多重试 3 次，超限标记 failed 不再重试——避免 PaddleOCR/Whisper
  模型每 15 分钟为空转反复加载；
- mtime 距今不足 30 秒的文件跳过（防人工拷贝中途读到半个文件；
  Syncthing 本身是临时文件+改名，天然原子）；
- 引擎实例每轮运行只构造一次（PaddleOCR/Whisper 模型加载昂贵）。
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.dispatch.highlights import CHECKLIST_SOURCE, ITEM_TAG
from scripts.utils.state_store import read_json, write_json
from scripts.dispatch.sysdir import SYSTEM_DIRNAME, write_machine_note
from scripts.memory.core import MemoryTree
from scripts.processors.audio import SUPPORTED_EXTENSIONS as AUDIO_EXTS
from scripts.processors.audio import AudioProcessor
from scripts.processors.highlights import HighlightsProcessor
from scripts.processors.image import SUPPORTED_EXTENSIONS as IMAGE_EXTS
from scripts.processors.image import ImageProcessor

#: 单个附件的最大处理尝试次数（超限标记 failed）
MAX_ATTEMPTS = 3

#: 自动产出笔记的标签（人工确认后由人移除）
REVIEW_TAG = "待确认"

#: 附件目录名（相对笔记根目录）
ATTACHMENTS_DIR = "attachments"

#: 原资料平台子目录（2026-09-10 用户裁决 G1：与笔记归档同一套名字）。
#: 截图/图片/语音原件的归位；feishu.py 收附件、截图专用夹导入按此写入
MEDIA_SUBDIR = "媒体"

#: PDF 原件的归位（书籍/长文，走划重点通道）
BOOK_SUBDIR = "书籍"

#: 跳过 mtime 距今不足该秒数的文件（防读到仍在写入的文件）
MIN_AGE_SECONDS = 30

#: PDF 附件路由到划重点清单（书籍/长文：机器代读 → 可勾选候选清单，
#: 人工勾中的条目由 dispatch/highlights.py 转为正式笔记）
_PDF_EXTS = {".pdf"}

_KIND_BY_EXT = {ext: "截图" for ext in IMAGE_EXTS}
_KIND_BY_EXT.update({ext: "录音" for ext in AUDIO_EXTS})

_PDF_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


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
        highlights_factory: Optional[Callable[[], HighlightsProcessor]] = None,
        screenshot_inbox: Optional[str] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            image_factory: 图片处理器工厂（测试注入假处理器用），
            缺省为 ImageProcessor；每轮运行最多构造一次。
            audio_factory: 音频处理器工厂，缺省为 AudioProcessor。
            highlights_factory: PDF 划重点处理器工厂，缺省为
            HighlightsProcessor；每轮运行最多构造一次。
            screenshot_inbox: 截图专用文件夹（2026-09-10 用户裁决 E4：
            只把该文件夹里的图片**复制**进 attachments/媒体/，复制不
            移动、其他截图一概不碰）；None 不启用（配置
            ``processors.media.screenshot_inbox``，由 dispatch_cli 注入）。
        """
        self.tree = tree
        self._image_factory = image_factory or ImageProcessor
        self._audio_factory = audio_factory or AudioProcessor
        self._highlights_factory = highlights_factory or HighlightsProcessor
        self._inbox = screenshot_inbox
        self._image: Optional[ImageProcessor] = None
        self._audio: Optional[AudioProcessor] = None
        self._highlights: Optional[HighlightsProcessor] = None
        self.state_path = Path(tree.state_dir) / "processed_media.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与分发（先导入截图专用夹，再扫 attachments/）。

        Args:
            dry_run: 只报告不处理（不复制、不建笔记、不写状态、不加载引擎）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/found/created/failed/
            skipped/imported）。
        """
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "found": 0,
            "created": [],
            "failed": [],
            "skipped": 0,
            "imported": 0,
        }
        self._import_inbox(report, dry_run)
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
        """列出 attachments/ 顶层与一层子目录下全部可处理附件（按 mtime 升序）。

        只认图片/录音/PDF 扩展名——``抖音/`` 等视频目录里的 .mp4 不在
        可处理扩展名内（那是 links 管线保存的原视频，不是待 OCR/转写
        的输入），天然跳过。
        """
        attach_dir = Path(self.tree.notes_dir) / ATTACHMENTS_DIR
        if not attach_dir.is_dir():
            return []
        now = time.time()
        candidates = [path for path in attach_dir.iterdir() if path.is_file()]
        for subdir in sorted(attach_dir.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("."):
                candidates.extend(path for path in subdir.iterdir() if path.is_file())
        files: List[Path] = []
        for path in sorted(candidates):
            if path.name.startswith("."):
                continue
            if path.suffix.lower() not in _KIND_BY_EXT and path.suffix.lower() not in _PDF_EXTS:
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
        is_pdf = path.suffix.lower() in _PDF_EXTS
        processor = self._get_processor(path)
        result = processor.process(path)
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if result.success:
            if is_pdf:
                # PDF → 划重点清单，写进 系统/ 机器产物区（不占记忆扫描域；
                # 清单本身无需确认，确认动作在"勾中条目转 wiki 摘录卡"的
                # 人工勾选上；dispatch/highlights 直接读目录，不走索引）
                filename = self._pdf_note_filename(path)
                try:
                    rel = write_machine_note(
                        Path(self.tree.notes_dir), filename, result.markdown,
                        source=CHECKLIST_SOURCE, tags=[ITEM_TAG],
                    )
                except (ValueError, FileExistsError):
                    # 同名清单已存在（状态丢失后的重跑）：视为已处理
                    rel = f"{SYSTEM_DIRNAME}/{filename}"
                entry["status"] = "done"
                entry["note"] = rel
                report["created"].append(rel)
                return
            kind = _KIND_BY_EXT[path.suffix.lower()]
            filename = self._note_filename(path)
            body = self._build_note(path, kind, result.text)
            source, tags = "media", [REVIEW_TAG, kind]
            try:
                self.tree.create_note(filename, body, source=source, tags=tags)
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
        suffix = path.suffix.lower()
        if suffix in _PDF_EXTS:
            if self._highlights is None:
                self._highlights = self._highlights_factory()
            return self._highlights
        if suffix in IMAGE_EXTS:
            if self._image is None:
                self._image = self._image_factory()
            return self._image
        if self._audio is None:
            self._audio = self._audio_factory()
        return self._audio

    @staticmethod
    def _pdf_note_filename(path: Path) -> str:
        """PDF 产出清单文件名：划重点-<净化主名>-<哈希前6>.md。"""
        cleaned = _PDF_ILLEGAL_RE.sub("-", path.stem).strip(". ")[:40] or "未命名"
        digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:6]
        return f"划重点-{cleaned}-{digest}.md"

    def _key(self, path: Path) -> str:
        """状态键：附件相对笔记根目录的路径（如 attachments/媒体/IMG_001.jpg）。"""
        return self.tree._rel_key(path)

    def _note_filename(self, path: Path) -> str:
        """产出笔记文件名：media-<文件日期>-<相对路径哈希前6>.md。

        哈希输入用相对路径（含子目录）：不同子目录下的同名附件不会
        撞出同一个笔记文件名。
        """
        date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
        digest = hashlib.sha1(self._key(path).encode("utf-8")).hexdigest()[:6]
        return f"media-{date}-{digest}.md"

    def _build_note(self, path: Path, kind: str, text: str) -> str:
        """组装笔记正文：内嵌原附件（相对路径）+ 提取全文（录音带书名号标点）。"""
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        section = "OCR 全文" if kind == "截图" else "转写全文"
        return (
            f"# {kind} {stamp}\n\n"
            f"![[{self._key(path)}]]\n\n"
            f"## {section}\n\n"
            f"{(text or '').strip()}\n"
        )

    def _load_state(self) -> Dict[str, Any]:
        """加载附件处理状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
