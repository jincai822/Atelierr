"""附件自动路由：attachments/ 里的截图/录音/直发视频 → OCR/Whisper →
建"待确认"笔记；PDF（书籍/长文）→ 划重点清单笔记（机器代读出可勾选
候选，勾中条目由 :mod:`scripts.dispatch.highlights` 转为 wiki 摘录卡）。
页数达标的书籍另产「书籍档案卡」进 inbox 待确认（2026-09-14 裁决，
对齐 Cognitive OS 准入协议：建档 + 查重 + 分级建议；✅ 一步归档进
``memory/书籍/[中图法/]``）。

定位：与 links/todos 同源的 dispatch 顶层组合模块（memory 与 processors
之间唯一的接线点）。触发由 systemd 定时器驱动
（docker/systemd/atelierr-links.*，每 15 分钟一次）；人工确认在产出端：
自动创建的笔记带 ``tags=["待确认"]``，人在 Obsidian 阅读后自行移除标签。

典型路径：手机截图/录音 → Obsidian 附件目录 → Syncthing 同步到电脑
→ 本模块识别 → 建笔记（内嵌原附件 ``![[attachments/媒体/xxx]]``，
Obsidian 里图片直接显示、录音/视频直接可播）→ 正文同时进入 todos
分发的扫描范围（截图里有行动意图时自动抽取待办）。

原资料归位（2026-09-10 用户裁决 G1）：附件按来源平台分子目录——
``媒体/``（截图/图片/语音/**直发视频**）、``书籍/``（PDF）、``抖音/``
``小红书/`` ``B站/``（链接视频，由 links 管线写入）；与笔记归档目录
同一套名字。扫描覆盖 attachments/ 顶层与一层子目录。

直发视频（2026-09-11 用户裁决：飞书直接发视频文件，不用链接）：
2026-09-13 起改为**全 attachments/ 认视频**（评审架构账 5：此前只认
``媒体/`` 子目录，"视频必须投对目录"是用户身上唯一的目录负担）；
防"自产自吃"改用**引用判定**——平台目录（抖音/小红书/B站）里的 mp4
已被链接产出卡内嵌引用（``![[attachments/…]]``），被引用的附件是
"产物"不是"输入"，跳过；未被引用的视频投在哪个子目录都认得。
时序安全：links 管线先写视频、紧接建卡引用（秒级窗口），而 links 与
media 在同一 service 内串行（flock 互斥），不会插队。转写成功后
压 480p **替换原件**（2026-09-11 用户裁决 B：与链接视频同一存储规格，
这是"原件只增不减"的唯一例外，仅限本通道直发视频；压缩失败保留
原件保底，绝不压坏了还丢原件）。其余附件原件只增不减：本模块绝不
删除/移动附件。

纪律（与 links.py 一致）：
- 只新增笔记，绝不改写/移动/删除既有笔记与附件本身（直发视频的
  480p 替换是唯一例外，见上）；
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
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.highlights import CHECKLIST_SOURCE, ITEM_TAG
from scripts.utils.file_utils import write_text_skip_existing
from scripts.utils.state_store import read_json, write_json
from scripts.dispatch.sysdir import SYSTEM_DIRNAME, write_machine_note
from scripts.memory.core import LAYERS, MemoryTree
from scripts.processors.audio import SUPPORTED_EXTENSIONS as AUDIO_EXTS
from scripts.processors.audio import AudioProcessor
from scripts.processors.base import INLINE_BODY_MAX
from scripts.processors.highlights import HighlightsProcessor
from scripts.processors.image import SUPPORTED_EXTENSIONS as IMAGE_EXTS
from scripts.processors.image import ImageProcessor
from scripts.processors.video import SUPPORTED_EXTENSIONS as VIDEO_EXTS
from scripts.processors.video import VideoProcessor, compress_to_480p

logger = logging.getLogger(__name__)

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

#: 直发视频扩展名（2026-09-11 裁决）——全 attachments/ 目录都认，
#: 已被笔记引用的跳过（2026-09-13 起，见 _collect_files）
_VIDEO_EXTS = set(VIDEO_EXTS)

#: 笔记内嵌/链接附件的写法：``![[attachments/xx]]`` 或
#: ``[[attachments/xx|别名]]``（只取路径段，别名丢弃）
_ATTACH_REF_RE = re.compile(r"\[\[\s*(attachments/[^\]|]+?)(?:\|[^\]]*)?\s*\]\]")

_KIND_BY_EXT = {ext: "截图" for ext in IMAGE_EXTS}
_KIND_BY_EXT.update({ext: "录音" for ext in AUDIO_EXTS})

_PDF_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')

#: 转写置信度警告阈值（与 processors/link.py _LOW_CONFIDENCE 同值）
_LOW_CONFIDENCE = 0.70


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
        video_factory: Optional[Callable[[], VideoProcessor]] = None,
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
            video_factory: 视频处理器工厂（2026-09-11 裁决：直发视频走
            Whisper 转写），缺省为 VideoProcessor；每轮运行最多构造一次。
        """
        self.tree = tree
        self._image_factory = image_factory or ImageProcessor
        self._audio_factory = audio_factory or AudioProcessor
        self._highlights_factory = highlights_factory or (
            # 书籍筛查的「对着什么」素材：读者真实目标/待办（2026-09-14 裁决）
            lambda: HighlightsProcessor(context_provider=self._reader_context)
        )
        self._video_factory = video_factory or VideoProcessor
        self._inbox = screenshot_inbox
        self._image: Optional[ImageProcessor] = None
        self._audio: Optional[AudioProcessor] = None
        self._highlights: Optional[HighlightsProcessor] = None
        self._video: Optional[VideoProcessor] = None
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

    def _import_inbox(self, report: Dict[str, Any], dry_run: bool) -> None:
        """截图专用文件夹导入：把里面的图片**复制**进 attachments/媒体/。

        用户裁决 E4（2026-09-10）：系统只认这个专用文件夹——用户拖进来
        （或 flameshot 直接存进来）的截图才进系统，其他截图一概不碰。
        复制不移动（原图留原地）；copy2 保留 mtime（刚截的图 mtime 太新
        会被 30s 防半文件守卫推到下一轮，与同步来的文件同一语义）；
        同名已存在跳过（绝不覆盖原件）；只认图片扩展名。
        """
        if not self._inbox:
            return
        inbox = Path(self._inbox).expanduser()
        if not inbox.is_dir():
            return
        dest_dir = self.tree.attachments_dir / MEDIA_SUBDIR
        for path in sorted(inbox.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            dest = dest_dir / path.name
            if dest.exists():
                continue
            report["imported"] += 1
            if dry_run:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, dest)
            except OSError as exc:
                logger.warning("截图导入失败 %s: %s", path, exc)
                report["imported"] -= 1

    def _collect_files(self, report: Dict[str, Any]) -> List[Path]:
        """列出 attachments/ 顶层与一层子目录下全部可处理附件（按 mtime 升序）。

        只认图片/录音/PDF 扩展名，外加视频扩展名（2026-09-13 起全目录认，
        不再限定 媒体/）——**已被笔记引用的视频除外**（链接管线保存的
        480p 原视频会被产出卡内嵌引用，是"产物"不是"输入"，跳过即防
        "自产自吃"循环；见 _referenced_attachments）。
        """
        attach_dir = self.tree.attachments_dir
        if not attach_dir.is_dir():
            return []
        now = time.time()
        referenced = self._referenced_attachments()
        candidates = [path for path in attach_dir.iterdir() if path.is_file()]
        for subdir in sorted(attach_dir.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("."):
                candidates.extend(path for path in subdir.iterdir() if path.is_file())
        files: List[Path] = []
        for path in sorted(candidates):
            if path.name.startswith("."):
                continue
            suffix = path.suffix.lower()
            if suffix in _VIDEO_EXTS:
                # attachments/ 在数据根平级：相对数据根取 "attachments/…" 形式
                rel = path.relative_to(self.tree.attachments_dir.parent).as_posix()
                if rel in referenced:
                    continue
            elif suffix not in _KIND_BY_EXT and suffix not in _PDF_EXTS:
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

    def _referenced_attachments(self) -> set:
        """全部笔记里被引用的附件相对路径集合（``[[attachments/…]]``）。

        链接产出卡内嵌 ``![[attachments/抖音/xxx.mp4]]``、外置全文用
        ``[[attachments/媒体/xxx.md|别名]]``——两种写法都抓，只取路径段。
        任何读取失败跳过该篇（不中断扫描）。
        """
        refs: set = set()
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                try:
                    text = Path(note_path).read_text(encoding="utf-8")
                except OSError:
                    continue
                for match in _ATTACH_REF_RE.finditer(text):
                    refs.add(match.group(1))
        return refs

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
                # 书籍模式（2026-09-14 裁决，对齐 Cognitive OS 准入协议）：
                # 档案卡进 inbox 待确认，✅ 一步归档进 memory/书籍/[中图法/]
                book = (result.metadata or {}).get("book")
                if book:
                    card = self._create_book_card(
                        path, book, Path(filename).stem, report
                    )
                    if card:
                        report["created"].append(card)
                return
            suffix = path.suffix.lower()
            kind = "视频" if suffix in _VIDEO_EXTS else _KIND_BY_EXT[suffix]
            if kind == "视频":
                # 2026-09-11 裁决 B：直发视频压 480p 替换原件（先转写后
                # 压缩——用原音质抽音轨；替换后 mtime 刷新，下方笔记
                # 文件名/时间戳读取的即处理当下）
                self._compress_in_place(path)
            filename = self._note_filename(path)
            body = self._build_note(
                path,
                kind,
                result.text,
                Path(filename).stem,
                getattr(result, "confidence", 0.0),
            )
            source, tags = "media", [REVIEW_TAG, kind]
            try:
                self.tree.create_note(filename, body, source=source, tags=tags, inbox=True)
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
        if suffix in _VIDEO_EXTS:
            if self._video is None:
                self._video = self._video_factory()
            return self._video
        if self._audio is None:
            self._audio = self._audio_factory()
        return self._audio

    def _compress_in_place(self, path: Path) -> None:
        """直发视频压 480p 并原子替换原件（2026-09-11 用户裁决 B）。

        与链接视频同一规格，共用
        :func:`scripts.processors.video.compress_to_480p` 唯一实现；
        压缩/替换失败保留原件保底（绝不压坏了还丢原件），笔记照常创建。
        临时文件用同目录隐藏名（``.`` 前缀），扫描天然跳过。
        """
        tmp = path.with_name(f".{path.stem}.480p.tmp.mp4")
        try:
            if not compress_to_480p(path, tmp):
                tmp.unlink(missing_ok=True)
                logger.warning("视频压 480p 失败，保留原件: %s", path)
                return
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("视频替换原件失败 %s: %s", path, exc)
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _pdf_note_filename(path: Path) -> str:
        """PDF 产出清单文件名：划重点-<净化主名>-<哈希前6>.md。"""
        cleaned = _PDF_ILLEGAL_RE.sub("-", path.stem).strip(". ")[:40] or "未命名"
        digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:6]
        return f"划重点-{cleaned}-{digest}.md"

    def _reader_context(self) -> List[str]:
        """书籍筛查的「对着什么」素材：目标/待办笔记标题（每目录至多 10 条）。

        直读人工目录（量小），不走 sidecar 索引；读取失败静默跳过——
        素材缺失不阻塞代读（target 退回「待读者判断」）。
        """
        lines: List[str] = []
        for dirname, label in (("目标", "目标"), ("待办", "待办")):
            dirpath = Path(self.tree.notes_dir) / dirname
            if not dirpath.is_dir():
                continue
            for path in sorted(dirpath.glob("*.md"))[:10]:
                title = path.stem
                try:
                    post = frontmatter.loads(path.read_text(encoding="utf-8"))
                    title = str(post.get("title") or path.stem)
                except (OSError, ValueError):
                    pass
                lines.append(f"{label}：{title}")
        return lines

    def _create_book_card(
        self,
        path: Path,
        book: Dict[str, Any],
        checklist_stem: str,
        report: Dict[str, Any],
    ) -> Optional[str]:
        """书籍档案卡（2026-09-14 用户裁决：对齐 Cognitive OS 准入协议）。

        落 inbox 带「待确认/书籍/(中图法)」标签 → 走确认卡推送，✅ 一步
        归档进 ``memory/书籍/[中图法/]``。查重按 书名+作者+版次 哈希
        （book_key）：同一份不建卡并记 report["deduped"]（US-001 §3.4
        "报人工一句"，由 dispatch_cli 推送）；同名不同版建卡但正文加
        警示行，交人工定夺。
        """
        key_src = f"{book['title']}|{book['author']}|{book['edition']}"
        book_key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:6]
        dup = self._find_book_card(book_key, book["title"])
        if dup and dup[0] == book_key:
            logger.info("书籍档案卡已存在，查重跳过: %s", book["title"])
            report.setdefault("deduped", []).append(book["title"])
            return None
        tags = [REVIEW_TAG, BOOK_SUBDIR] + ([book["clc"]] if book["clc"] else [])
        lines = [
            f"# 《{book['title']}》档案",
            "",
            f"- 作者：{book['author'] or '（未识别）'}　版次：{book['edition'] or '（未识别）'}"
            f"　ISBN：{book['isbn'] or '（未识别）'}",
            f"- 原件：[[{self._key(path)}]]",
            f"- 筛查清单：[[{checklist_stem}]]（勾中条目转 wiki 摘录卡）",
            f"- 级别建议：{book['level']}——{book['level_reason'] or '机器建议'}"
            "（机器只能建议 L1/L2；L3 定级永远是人工权力）",
            "- 阅读状态：想读（读完手动改 在读/读完）",
        ]
        if dup:
            lines += [
                "",
                f"⚠️ 已有同名书的不同版本档案：[[{dup[1]}]]——请人工定夺是否合并。",
            ]
        metadata = {
            "type": "Book",
            "title": f"《{book['title']}》",
            "book_key": book_key,
            "book_author": book["author"],
            "book_edition": book["edition"],
            "book_isbn": book["isbn"],
            "level_suggestion": book["level"],
            "reading_status": "想读",
            "source": "book",
            "tags": tags,
        }
        content = frontmatter.dumps(frontmatter.Post("\n".join(lines) + "\n", **metadata))
        cleaned = _PDF_ILLEGAL_RE.sub("-", book["title"]).strip(". ")[:40] or "未命名"
        filename = f"书籍-{cleaned}-{book_key}.md"
        try:
            self.tree.create_note(filename, content, inbox=True)
        except (ValueError, FileExistsError):
            # 同名档案卡已存在（状态丢失后的重跑）：视为已建
            return None
        return f"inbox/{filename}"

    def _find_book_card(self, book_key: str, title: str) -> Optional[Tuple[str, str]]:
        """书籍档案查重：扫 inbox/ 与 memory/书籍/ 的既有档案卡。

        Returns:
            (book_key, stem) 完全同一份；("", stem) 同名不同版本；
            None 无重复。
        """
        dirs = [Path(self.tree.inbox_dir), Path(self.tree.notes_dir) / BOOK_SUBDIR]
        for dirpath in dirs:
            if not dirpath.is_dir():
                continue
            # 书籍目录递归扫：确认归档后卡在中图法子目录（书籍/B84-心理学/）
            pattern = "书籍-*.md" if dirpath.name != BOOK_SUBDIR else "**/书籍-*.md"
            for card in sorted(dirpath.glob(pattern)):
                try:
                    post = frontmatter.loads(card.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if str(post.get("book_key") or "") == book_key:
                    return book_key, card.stem
                card_title = str(post.get("title") or "").strip("《》")
                if card_title and card_title == title:
                    return "", card.stem
        return None

    def _key(self, path: Path) -> str:
        """状态键：附件相对数据根的路径（如 attachments/媒体/IMG_001.jpg）。

        2026-09-13 拆分后 attachments/ 在数据根平级（与 notes_dir 平级），
        键格式不变（相对 attachments_dir 的父目录）——历史
        processed_media.json 记录在迁移后照常有效，不重处理。
        """
        return path.relative_to(self.tree.attachments_dir.parent).as_posix()

    def _note_filename(self, path: Path) -> str:
        """产出笔记文件名：media-<文件日期>-<相对路径哈希前6>.md。

        哈希输入用相对路径（含子目录）：不同子目录下的同名附件不会
        撞出同一个笔记文件名。
        """
        date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
        digest = hashlib.sha1(self._key(path).encode("utf-8")).hexdigest()[:6]
        return f"media-{date}-{digest}.md"

    def _build_note(
        self,
        path: Path,
        kind: str,
        text: str,
        note_stem: str,
        confidence: float = 0.0,
    ) -> str:
        """组装卡正文：内嵌原附件 + 提取全文（短内联，长外置留链接节）。

        方案 B（2026-09-12 用户裁决）：全文 >INLINE_BODY_MAX 时原子写入
        ``attachments/媒体/<笔记同名>.md``（同名跳过幂等；实现与链接
        管线共用 write_text_skip_existing），卡上只留「## 全文」链接节；
        写入失败降级为内联保底——卡绝不丢内容。
        转写置信度偏低（>0 且 <0.70）时卡面加警告行（2026-09-14 KM
        评审裁决：同音错字靠这层信号 + 人工回放兜底）。
        """
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        section = "OCR 全文" if kind == "截图" else "转写全文"
        body = (text or "").strip()
        warn = ""
        if kind in ("视频", "录音") and 0.0 < confidence < _LOW_CONFIDENCE:
            warn = (
                f"> ⚠️ 转写置信度 {confidence:.0%} 偏低，"
                "关键处建议回放原件核对。\n\n"
            )
        if len(body) > INLINE_BODY_MAX:
            rel = f"{ATTACHMENTS_DIR}/{MEDIA_SUBDIR}/{note_stem}.md"
            target = self.tree.attachments_dir.parent / rel
            wrote = write_text_skip_existing(target, body)
            if wrote or target.exists():
                return (
                    f"# {kind} {stamp}\n\n"
                    f"![[{self._key(path)}]]\n\n"
                    f"{warn}"
                    f"## 全文\n\n"
                    f"[[{rel}|查看{section}]]\n"
                )
            logger.warning("全文落盘失败，降级为卡内联: %s", target)
        return (
            f"# {kind} {stamp}\n\n"
            f"![[{self._key(path)}]]\n\n"
            f"{warn}"
            f"## {section}\n\n"
            f"{body}\n"
        )

    def _load_state(self) -> Dict[str, Any]:
        """加载附件处理状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
