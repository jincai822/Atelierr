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

内容级查重（2026-09-16 用户裁决 A）：同名靠状态键幂等，**不同名靠
字节 sha1**——同一文件换名重发命中已处理条目即标记 ``duplicate``
跳过（不重复建卡、不计次数），由 CLI 层推飞书回执；多图图集批次
不走此查重（图集合并本身是另一层去重）。

典型路径：手机截图/录音 → Obsidian 附件目录 → Syncthing 同步到电脑
→ 本模块识别 → 建笔记（内嵌原附件 ``![[attachments/媒体/xxx]]``，
Obsidian 里图片直接显示、录音/视频直接可播）→ 正文同时进入 todos
分发的扫描范围（截图里有行动意图时自动抽取待办）。

原资料归位（2026-09-10 用户裁决 G1）：附件按来源平台分子目录——
``媒体/``（截图/图片/语音/**直发视频**）、``书籍/``（PDF）、``抖音/``
``小红书/`` ``B站/``（链接视频，由 links 管线写入）；与笔记归档目录
同一套名字。扫描覆盖 attachments/ 顶层与一层子目录。PDF 处理成功后
再收一层专夹（2026-09-16 裁决 KM 规格）：``<平台>/<书名或净化主名>/``
下收原件 + ``全文.md``（二层深度天然不再入扫描，防重跑）；清单与
档案卡都带全文链接。

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

图集合并（2026-09-15 用户裁决 A）：到达间隔 ≤_IMAGE_BATCH_SECONDS 的
连续图片粘为一张图集卡（逐张内嵌 + 分页 OCR 汇总）——连发的文章
分页是一条内容，一页一卡会打散（实测 7 页散成 7 卡）。每张图片的
状态仍逐文件登记，幂等粒度不变。

直发视频/录音/截图总结（2026-09-15 用户裁决 B 及其当日扩展）：与链接
视频同待遇——复用 LinkProcessor 的总结能力产出观点总结/分观点/中图法
标签（追加进 frontmatter tags），同一道 max_transcript_chars 护栏；
截图/图集以 OCR 全文为内容本体参与总结。跳过/失败卡面标注，不静默
降级。

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
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.archive import auto_archive
from scripts.dispatch.highlights import CHECKLIST_SOURCE, ITEM_TAG
from scripts.dispatch.links import (
    _BACKLINK_RE,
    _BOILERPLATE_RE,
    _POINTER_WORDS,
    _TIME_PREFIX_RE,
)
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
from scripts.processors.link import (
    URL_RE,
    LinkProcessor,
    _llm_skip_note,
    _sanitize_title,
)
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

#: 图集粘合窗口（2026-09-15 用户裁决 A）：相邻图片到达间隔 ≤ 该秒数
#: 视为同一条内容（连发的文章分页/一组现场照，实测一页几秒），合并为
#: 一个图集卡；超过则各成单卡。定为 60s 而非更宽：实测两篇文章先后
#: 相隔 100s 连发，宽窗口会把不同内容粘错。仍可能粘住窗口内的不相关
#: 连发——概率低，确认环节人工可拆（purge 后分批重投）
_IMAGE_BATCH_SECONDS = 60

#: 飞书入站附件的文件名时间戳（feishu-YYYYMMDD-HHMMSS-<hash>.<ext>，UTC）
_FEISHU_NAME_RE = re.compile(r"^feishu-(\d{8}-\d{6})-")

#: 媒体卡的评论附着窗口（2026-09-15 评审 P1）：到达时刻前后该秒数内的
#: 日记文字行视为对这条媒体的评论（人常先发媒体再补一句人话；含链接的
#: 行跳过——那是链接管线的评论，各有各的家）
_COMMENT_WINDOW_SECONDS = 180


def _semantic_h1(
    kind: str, stamp: str, summary: Optional[Dict[str, Any]]
) -> Tuple[str, str]:
    """有总结时给语义 H1（kind-主题）与 frontmatter title 块；无则旧形态
    （kind + 时间戳）与空块。2026-09-15 评审 P1：哈希名一个月后认不出
    是什么；文件名保持不动（幂等锚点），显示层语义化。"""
    sem = _sanitize_title(str(summary.get("title") or "")) if summary else ""
    if not sem:
        return f"{kind} {stamp}", ""
    h1 = f"{kind}-{sem}"
    return h1, f"---\ntitle: {json.dumps(h1, ensure_ascii=False)}\n---\n\n"


def _summary_sections(summary: Optional[Dict[str, Any]]) -> str:
    """摘要各节 Markdown（观点总结/分观点/金句/实体，与链接管线同序）；
    None 返回空串。单卡与图集卡共用。"""
    if not summary:
        return ""
    parts = ["## 观点总结", "", str(summary["summary"])]
    if summary.get("points"):
        parts += ["", "## 分观点论述", ""]
        parts += [
            f"{i}. {point}" for i, point in enumerate(summary["points"], 1)
        ]
    if summary.get("insights"):
        parts += ["", "## 金句摘录", ""]
        parts += [f"> {item}" for item in summary["insights"]]
    if summary.get("insights_dropped"):
        parts += [
            "",
            f"> （{summary['insights_dropped']} 条候选金句未通过"
            "原文回溯校验，已剔除——摘录必须逐字出自原文）",
        ]
    if summary.get("entities"):
        parts += ["", "## 提到的人·书·概念", ""]
        parts += [f"- {item}" for item in summary["entities"]]
    return "\n".join(parts) + "\n\n"


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
        summarize_fn: Optional[
            Callable[[str], Tuple[Optional[Dict[str, Any]], str]]
        ] = None,
        format_fn: Optional[Callable[[str], Tuple[Optional[str], str]]] = None,
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
            summarize_fn: 总结函数（测试注入）；缺省为 None，运行时惰性
            构造 LinkProcessor 复用其总结能力与护栏（2026-09-15 裁决 B：
            直发视频/录音与链接视频同待遇）。
            format_fn: 正文整理函数（测试注入）；缺省为 None，运行时惰性
            构造 LinkProcessor 复用其整理能力与护栏（2026-09-17 裁决：
            直发视频/录音的正文与链接同待遇——分段、补标点、逐字不改写）。
        """
        self.tree = tree
        self._image_factory = image_factory or ImageProcessor
        self._audio_factory = audio_factory or AudioProcessor
        self._highlights_factory = highlights_factory or (
            # 书籍筛查的「对着什么」素材：读者真实目标/待办（2026-09-14 裁决）
            lambda: HighlightsProcessor(context_provider=self._reader_context)
        )
        self._video_factory = video_factory or VideoProcessor
        self._summarize_fn = summarize_fn
        self._format_fn = format_fn
        self._link: Optional[LinkProcessor] = None
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
            skipped/imported/duplicates）。
        """
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "found": 0,
            "created": [],
            "failed": [],
            "skipped": 0,
            "imported": 0,
            "duplicates": [],
            "archived": {},
        }
        self._import_inbox(report, dry_run)
        pending: List[Path] = []
        for path in self._collect_files(report):
            key = self._key(path)
            entry = state.get(key)
            if entry and entry.get("status") in ("done", "failed"):
                report["skipped"] += 1
                continue
            report["found"] += 1
            pending.append(path)
        if not dry_run:
            for item in self._group_work(pending):
                if isinstance(item, list):
                    self._process_image_batch(item, state, report)
                else:
                    self._process_one(item, state, report)
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

    def _group_work(self, files: List[Path]) -> List[Any]:
        """把工作项按图集规则粘合：连续到达的图片合并为一个批次项。

        2026-09-15 用户裁决 A：手机连发的多图（一篇文章的连续页、一组
        现场照片）是同一条内容，一页一卡会把内容打散（实测 7 页文章
        散成 7 张卡）。规则：按到达时间排序后，相邻图片间隔
        ≤_IMAGE_BATCH_SECONDS 粘为一批（滚动窗口，以与上一张的间隔
        为准）；**不跨目录粘合**（目录即语境，不同子目录的同名附件
        仍各自成卡）；非图片与孤立图片保持单项。
        """
        items: List[Any] = []
        batch: List[Path] = []
        batch_ts = 0.0
        batch_parent: Optional[Path] = None

        def _flush() -> None:
            nonlocal batch, batch_parent
            if batch:
                items.append(batch[0] if len(batch) == 1 else list(batch))
                batch = []
                batch_parent = None

        for path in files:
            if path.suffix.lower() not in IMAGE_EXTS:
                _flush()
                items.append(path)
                continue
            ts = self._arrival_ts(path)
            if (
                batch
                and path.parent == batch_parent
                and ts - batch_ts <= _IMAGE_BATCH_SECONDS
            ):
                batch.append(path)
                batch_ts = ts
            else:
                _flush()
                batch = [path]
                batch_ts = ts
                batch_parent = path.parent
        _flush()
        return items

    @staticmethod
    def _file_sha1(path: Path) -> Optional[str]:
        """文件字节 sha1（分块读；读取失败返回 None——放弃查重，照常处理）。"""
        try:
            digest = hashlib.sha1()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _duplicate_of(
        state: Dict[str, Any], key: str, file_hash: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """查已有条目里同内容的已处理件（自身除外）；无哈希或未命中返回 None。"""
        if not file_hash:
            return None
        for other_key, other in state.items():
            if other_key == key or not isinstance(other, dict):
                continue
            if other.get("status") == "done" and other.get("file_hash") == file_hash:
                return other
        return None

    @staticmethod
    def _arrival_ts(path: Path) -> float:
        """到达时间（epoch 秒）：飞书文件名时间戳（UTC）优先，回退 mtime。"""
        match = _FEISHU_NAME_RE.match(path.name)
        if match:
            try:
                return (
                    datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
            except ValueError:
                pass
        return path.stat().st_mtime

    def _process_image_batch(
        self, paths: List[Path], state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """图集批次：逐张 OCR，合并建一张图集卡。

        ≥1 张 OCR 成功即建卡：全部图片内嵌（图是原件必须保藏），成功页
        附分页 OCR 全文；OCR 失败的页仍标 done 并记 ocr=failed——图已
        进卡，重试只会再造一张重复卡。全部失败不建卡，逐张计次数
        （3 次熔断，与单图同规）。
        """
        processor = self._get_processor(paths[0])
        ocr_parts: List[Tuple[int, str]] = []
        for idx, path in enumerate(paths, 1):
            result = processor.process(path)
            if result.success and (result.text or "").strip():
                ocr_parts.append((idx, result.text.strip()))
        now_iso = datetime.now(timezone.utc).isoformat()
        entries = []
        for path in paths:
            entry = state.setdefault(self._key(path), {"attempts": 0})
            entry["attempts"] += 1
            entry["last_attempt"] = now_iso
            entries.append(entry)
        if not ocr_parts:
            final = any(e["attempts"] >= MAX_ATTEMPTS for e in entries)
            for entry in entries:
                if entry["attempts"] >= MAX_ATTEMPTS:
                    entry["status"] = "failed"
            report["failed"].append(
                {
                    "file": f"图集 {len(paths)} 张",
                    "error": "OCR 全部失败",
                    "attempts": entries[0]["attempts"],
                    "final": final,
                }
            )
            return
        filename = self._batch_note_filename(paths)
        ocr_text = "\n\n".join(
            f"—— 第 {idx} 页 ——\n\n{text}" for idx, text in ocr_parts
        )
        # 图集同权总结（2026-09-15 裁决 B 扩展：OCR 汇总即内容本体）；
        # 评论附着用末张图的到达时刻（人常发完图再补一句人话）
        summary, llm_status, llm_limit = self._summarize_transcript(ocr_text)
        llm_note = _llm_skip_note(llm_status, len(ocr_text), llm_limit)
        body = self._build_batch_note(
            paths,
            ocr_parts,
            Path(filename).stem,
            summary=summary,
            llm_note=llm_note,
            comment=self._diary_comment_near(self._arrival_ts(paths[-1])),
        )
        tags = [REVIEW_TAG, "截图"]
        if summary:
            category = str(summary.get("category") or "").strip()
            topics = [
                str(t).strip()
                for t in (summary.get("topics") or [])
                if str(t).strip()
            ]
            tags += ([category] if category else []) + topics
        try:
            # 图集是多张截图的合并形态，沿用「截图」标签（归档映射不变）
            self.tree.create_note(
                filename, body, source="media", tags=tags, inbox=True
            )
        except (ValueError, FileExistsError):
            # 同名图集卡已存在（状态丢失后的重跑）：视为已处理
            pass
        ok_paths = {paths[idx - 1] for idx, _text in ocr_parts}
        for path, entry in zip(paths, entries):
            entry["status"] = "done"
            entry["note"] = filename
            if path not in ok_paths:
                entry["ocr"] = "failed"  # 图已进卡，OCR 不再重试
        report["created"].append(filename)
        # 放权自动归档（2026-09-21 裁决：产出即归档，失败留 inbox 人工兜底）
        domain = auto_archive(self.tree, filename)
        if domain:
            report["archived"][filename] = domain

    def _batch_note_filename(self, paths: List[Path]) -> str:
        """图集卡文件名：media-<首张日期>-<全部相对路径哈希前6>.md。"""
        date = datetime.fromtimestamp(paths[0].stat().st_mtime).strftime("%Y%m%d")
        digest = hashlib.sha1(
            "\n".join(self._key(p) for p in paths).encode("utf-8")
        ).hexdigest()[:6]
        return f"media-{date}-{digest}.md"

    def _build_batch_note(
        self,
        paths: List[Path],
        ocr_parts: List[Tuple[int, str]],
        note_stem: str,
        summary: Optional[Dict[str, Any]] = None,
        llm_note: Optional[str] = None,
        comment: str = "",
    ) -> str:
        """图集卡正文：语义标题（有总结时）+ 评论行 + 逐张内嵌原件
        （Obsidian 可翻看）+ （可选）摘要各节 + 分页 OCR 全文。

        与单图卡同规（方案 B）：OCR 汇总 >INLINE_BODY_MAX 时外置
        ``attachments/媒体/<同名>.md``，卡上只留「## 全文」链接节；
        写入失败降级内联保底——卡绝不丢内容。
        """
        stamp = datetime.fromtimestamp(paths[0].stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        embeds = "\n".join(f"![[{self._key(p)}]]" for p in paths)
        ocr_text = "\n\n".join(
            f"—— 第 {idx} 页 ——\n\n{text}" for idx, text in ocr_parts
        )
        warn = f"> {llm_note}\n\n" if llm_note else ""
        h1, fm = _semantic_h1("图集", stamp, summary)
        comment_md = f"> 💬 我的评论：{comment}\n\n" if comment else ""
        head = (
            f"{fm}# {h1}（{len(paths)} 张）\n\n{comment_md}{embeds}\n\n"
            f"{warn}{_summary_sections(summary)}"
        )
        if len(ocr_text) > INLINE_BODY_MAX:
            rel = f"{ATTACHMENTS_DIR}/{MEDIA_SUBDIR}/{note_stem}.md"
            target = self.tree.attachments_dir.parent / rel
            wrote = write_text_skip_existing(target, ocr_text)
            if wrote or target.exists():
                return f"{head}## 全文\n\n[[{rel}|查看OCR 全文]]\n"
            logger.warning("图集 OCR 落盘失败，降级为卡内联: %s", target)
        return f"{head}## OCR 全文\n\n{ocr_text}\n"

    def _summarize_transcript(
        self, text: str
    ) -> Tuple[Optional[Dict[str, Any]], str, int]:
        """直发视频/录音的总结：复用链接管线 LinkProcessor 的能力与护栏。

        Returns:
            Tuple[Optional[Dict[str, Any]], str, int]: (summary 或 None,
            状态串, 生效的字数护栏——注入 summarize_fn 时为 0）。
        """
        if self._summarize_fn is not None:
            summary, status = self._summarize_fn(text)
            return summary, status, 0
        if self._link is None:
            self._link = LinkProcessor()
        summary, status = self._link.summarize_transcript(text)
        return summary, status, self._link.llm_max_chars

    def _format_transcript(self, text: str) -> Tuple[Optional[str], str]:
        """直发视频/录音的正文整理：复用链接管线 LinkProcessor 的护栏。

        Returns:
            Tuple[Optional[str], str]: (整理后正文 或 None, 状态串)；
            失败/跳过返回 (None, 状态)，调用方降级为 Whisper 原稿。
        """
        if self._format_fn is not None:
            return self._format_fn(text)
        if self._link is None:
            self._link = LinkProcessor()
        return self._link.format_transcript(text)

    def _diary_comment_near(self, ts: float) -> str:
        """取到达时刻前后窗口内的日记人话，作媒体卡的评论（无则空串）。

        2026-09-15 评审 P1：发图/发视频配的文字说明此前进不了卡（评论
        注入只在链接管线）。只读日记绝不改写；含链接的行跳过（链接管线
        的评论各有各的家）；时间前缀/机器回链/平台样板照常剥掉。
        窗口内多条人话的取舍：媒体之后的行优先（评论通常先发媒体再补
        一句），同分钟日记序即到达序、后来居上（2026-09-15 实测：媒体
        与意图行同分钟到达，取早者把"明天把X看完"粘成了评论，真正的
        评论在其后一行）；媒体之前的取最近一条兜底。误粘风险接受并
        人工可见。
        """
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        diary = Path(self.tree.notes_dir) / f"{day}.md"
        if not diary.is_file():
            return ""
        try:
            body = diary.read_text(encoding="utf-8")
        except OSError:
            return ""
        media_minute = datetime.fromtimestamp(ts).replace(second=0, microsecond=0)
        after_text = ""
        before_text = ""
        before_diff = float("inf")
        for line in body.splitlines():
            match = re.match(r"^[-*\s]*(\d{1,2}):(\d{2})", line)
            if not match:
                continue
            hh, mm = int(match.group(1)), int(match.group(2))
            line_dt = datetime.fromtimestamp(ts).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            diff = abs(line_dt.timestamp() - ts)
            if diff > _COMMENT_WINDOW_SECONDS:
                continue
            if URL_RE.search(line) or _BOILERPLATE_RE.search(line):
                continue
            text = _BACKLINK_RE.sub("", URL_RE.sub("", line))
            text = _TIME_PREFIX_RE.sub("", text).strip(" \t，。：:;；")
            if len(text) < 2 or text in _POINTER_WORDS:
                continue
            if line_dt >= media_minute:
                after_text = text  # 同分钟后发制人：后来的覆盖先前的
            elif diff < before_diff:
                before_text, before_diff = text, diff
        return after_text or before_text

    def _process_one(
        self, path: Path, state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """处理单个附件：成功建笔记，失败计次数（3 次熔断）。"""
        key = self._key(path)
        entry = state.setdefault(key, {"attempts": 0})
        # 内容级查重（2026-09-16 用户裁决 A）：同名靠 key 幂等、不同名靠
        # 内容——同一文件换名重发，字节 sha1 命中已处理条目即跳过（CLI 层
        # 按 report["duplicates"] 推飞书回执），不重复建卡、不计次数。
        # 多图批次不走这里（图集合并本身是另一层去重），单图/录音/视频/
        # PDF 全覆盖。
        file_hash = self._file_sha1(path)
        dup_of = self._duplicate_of(state, key, file_hash)
        if dup_of is not None:
            entry["status"] = "done"
            entry["duplicate"] = True
            entry["note"] = dup_of.get("note")
            entry["file_hash"] = file_hash
            report["duplicates"].append({"file": key, "note": dup_of.get("note")})
            return
        entry["attempts"] += 1
        is_pdf = path.suffix.lower() in _PDF_EXTS
        # 评论附着以"到达时刻"为准：直发视频压缩会刷新 mtime，须先取样
        arrival_ts = self._arrival_ts(path)
        processor = self._get_processor(path)
        result = processor.process(path)
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if result.success:
            if is_pdf:
                # 原件收进专夹 + 全文落盘（2026-09-16 用户裁决 KM 规格，
                # 对齐链接管线"一条内容一个文件夹"）：全文是可检索/可再
                # 加工的资产，清单只是它的视图；OCR 重建的全文尤其贵
                #（GPU ~1.3s/页），绝不一次性用完就扔
                book_meta = (result.metadata or {}).get("book") or {}
                fulltext_rel, shelved = self._shelve_pdf(
                    path,
                    result.text or "",
                    book_meta,
                    ocr_assets=(result.metadata or {}).get("ocr_assets"),
                )
                path = shelved or path
                markdown = result.markdown
                if fulltext_rel:
                    how = (
                        "OCR 重建"
                        if (result.metadata or {}).get("ocr")
                        else "文字层提取"
                    )
                    markdown += (
                        f"\n> 全文：[[{fulltext_rel}]]（{how}，供检索与再加工）\n"
                    )
                # PDF → 划重点清单，写进 系统/ 机器产物区（不占记忆扫描域；
                # 清单本身无需确认，确认动作在"勾中条目转 wiki 摘录卡"的
                # 人工勾选上；dispatch/highlights 直接读目录，不走索引）
                filename = self._pdf_note_filename(path)
                try:
                    rel = write_machine_note(
                        Path(self.tree.notes_dir), filename, markdown,
                        source=CHECKLIST_SOURCE, tags=[ITEM_TAG],
                    )
                except (ValueError, FileExistsError):
                    # 同名清单已存在（状态丢失后的重跑）：视为已处理
                    rel = f"{SYSTEM_DIRNAME}/{filename}"
                entry["status"] = "done"
                entry["note"] = rel
                if file_hash:
                    entry["file_hash"] = file_hash
                report["created"].append(rel)
                # 书籍模式（2026-09-14 裁决，对齐 Cognitive OS 准入协议）：
                # 档案卡产出即自动归档进领域目录（2026-09-21 放权裁决，
                # 取代原"待确认 → ✅ 一步归档进 memory/书籍/[中图法/]"）
                book = (result.metadata or {}).get("book")
                if book:
                    card = self._create_book_card(
                        path, book, Path(filename).stem, report, fulltext_rel
                    )
                    if card:
                        report["created"].append(card)
                        domain = auto_archive(self.tree, card)
                        if domain:
                            report["archived"][card] = domain
                return
            suffix = path.suffix.lower()
            kind = "视频" if suffix in _VIDEO_EXTS else _KIND_BY_EXT[suffix]
            if kind == "视频":
                # 2026-09-11 裁决 B：直发视频压 480p 替换原件（先转写后
                # 压缩——用原音质抽音轨；替换后 mtime 刷新，下方笔记
                # 文件名/时间戳读取的即处理当下）
                self._compress_in_place(path)
            filename = self._note_filename(path)
            summary = None
            llm_note = None
            # 2026-09-17 裁决：直发视频/录音的正文同权过 LLM 整理（分段、
            # 补标点、逐字不改写；此前只有链接管线过，直发的是 Whisper
            # 原稿）。整理失败/跳过降级为 Whisper 原稿，不阻塞管线。
            # OCR 文本本身是书面语不过整理。
            note_text = result.text or ""
            if kind in ("视频", "录音") and note_text:
                formatted, _fmt_status = self._format_transcript(note_text)
                if formatted is not None:
                    note_text = formatted
            # 2026-09-15 裁决 B（当日扩展：截图同权——OCR 全文即内容本体，
            # 与转写同待遇）：全部非 PDF 附件都过总结，同一道字数护栏；
            # 跳过/失败卡面标注，不静默降级
            text_len = len(note_text)
            summary, llm_status, llm_limit = self._summarize_transcript(note_text)
            llm_note = _llm_skip_note(llm_status, text_len, llm_limit)
            body = self._build_note(
                path,
                kind,
                note_text,
                Path(filename).stem,
                getattr(result, "confidence", 0.0),
                summary=summary,
                llm_note=llm_note,
                comment=self._diary_comment_near(arrival_ts),
            )
            source, tags = "media", [REVIEW_TAG, kind]
            if summary:
                category = str(summary.get("category") or "").strip()
                topics = [
                    str(t).strip()
                    for t in (summary.get("topics") or [])
                    if str(t).strip()
                ]
                tags += ([category] if category else []) + topics
            try:
                self.tree.create_note(filename, body, source=source, tags=tags, inbox=True)
            except (ValueError, FileExistsError):
                # 同名笔记已存在（状态丢失后的重跑）：视为已处理
                pass
            entry["status"] = "done"
            entry["note"] = filename
            if file_hash:
                entry["file_hash"] = file_hash
            report["created"].append(filename)
            # 放权自动归档（2026-09-21 裁决）
            domain = auto_archive(self.tree, filename)
            if domain:
                report["archived"][filename] = domain
            return
        entry["last_error"] = (result.error or "")[:300]
        final = entry["attempts"] >= MAX_ATTEMPTS
        if final:
            entry["status"] = "failed"
        # attempts/final 供 CLI 层决定推送节奏（首次与熔断才推，中间不刷屏）
        report["failed"].append(
            {
                "file": key,
                "error": result.error,
                "attempts": entry["attempts"],
                "final": final,
            }
        )

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

    def _shelve_pdf(
        self,
        path: Path,
        text: str,
        book: Dict[str, Any],
        ocr_assets: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[Path]]:
        """PDF 原件收进专夹 + 全文落盘（2026-09-16 用户裁决 KM 规格，
        对齐链接管线"一条内容一个文件夹"）：
        ``attachments/<原目录>/<书名或净化主名>/`` 下收原件 PDF 与
        ``全文.md``，清单与档案卡都带全文链接。

        全文是可检索/可再加工的资产，清单只是它的视图——OCR 重建的
        全文尤其贵（GPU ~1.3s/页），绝不一次性用完就扔。专夹里已有同
        名原件时原件原地不动（同名不同版共存）；全文已存在时改写
        ``全文-<哈希6>``.md，绝不覆盖旧版。

        Args:
            path: PDF 当前路径（到达位置，专夹建在其父目录下）。
            text: 全文（文字层提取或 OCR 重建）；空文本直接跳过。
            book: 书籍档案元数据（有题名时专夹按题名命名）。
            ocr_assets: 结构化重建的插图裁切临时目录（highlights
                ``metadata["ocr_assets"]``）；给定时搬进专夹 ``图片/``
                并把全文里的 ``![[图片/…]]`` 引用改写为库内全路径。

        Returns:
            Tuple[Optional[str], Optional[Path]]: (全文相对数据根路径,
            原件现路径)；失败返回 (None, None)，原件原地不动、不阻塞主流程。
        """
        if not (text or "").strip():
            return None, None
        try:
            title = str(book.get("title") or "").strip()
            base = title or path.stem
            cleaned = _PDF_ILLEGAL_RE.sub("-", base).strip(". ")[:40] or "未命名"
            folder = path.parent / cleaned
            folder.mkdir(parents=True, exist_ok=True)
            new_path = folder / path.name
            if not new_path.exists():
                shutil.move(str(path), str(new_path))
            else:
                # 专夹已有同名原件（同名不同版重投）：原件留在原地
                new_path = path
            if ocr_assets:
                # 结构化重建的插图裁切收编进专夹 图片/，引用改写为库内全路径
                assets_src = Path(ocr_assets)
                if assets_src.is_dir():
                    img_dir = folder / "图片"
                    img_dir.mkdir(exist_ok=True)
                    for img in sorted(assets_src.iterdir()):
                        shutil.move(str(img), str(img_dir / img.name))
                    folder_rel = folder.relative_to(
                        self.tree.attachments_dir.parent
                    ).as_posix()
                    text = text.replace("![[图片/", f"![[{folder_rel}/图片/")
                    shutil.rmtree(assets_src, ignore_errors=True)
            fulltext = folder / "全文.md"
            if fulltext.exists():
                digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:6]
                fulltext = folder / f"全文-{digest}.md"
            header = (
                "---\n"
                f"created: '{datetime.now(timezone.utc).isoformat()}'\n"
                "source: pdf-fulltext\n"
                "---\n\n"
                f"# {cleaned} 全文\n\n> 原件：[[{new_path.name}]]\n\n"
            )
            fulltext.write_text(header + text.strip() + "\n", encoding="utf-8")
            rel = fulltext.relative_to(self.tree.attachments_dir.parent).as_posix()
            return rel, new_path
        except OSError as exc:
            logger.warning("PDF 全文落盘失败 %s: %s", path, exc)
            return None, None

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
        fulltext_rel: Optional[str] = None,
    ) -> Optional[str]:
        """书籍档案卡（2026-09-14 用户裁决：对齐 Cognitive OS 准入协议）。

        落 inbox 带「待确认/书籍/(中图法)」标签 → 走确认卡推送，✅ 一步
        归档进 ``memory/书籍/[中图法/]``。查重按 书名+作者+版次 哈希
        （book_key）：同一份不建卡并记 report["deduped"]（US-001 §3.4
        "报人工一句"，由 dispatch_cli 推送）；同名不同版建卡但正文加
        警示行，交人工定夺。fulltext_rel 给定（全文已落盘）时正文带
        全文链接。
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
        ]
        if fulltext_rel:
            lines.append(f"- 全文：[[{fulltext_rel}]]（供检索与再加工）")
        lines += [
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
        """书籍档案查重：全树扫既有档案卡（inbox + 各领域目录）。

        2026-09-21 放权后档案卡产出即归档进领域目录（health/career/…），
        不再固定落 书籍/，查重必须全树扫（iter_all_note_files 已排除
        wiki/attachments 等机器目录）。

        Returns:
            (book_key, stem) 完全同一份；("", stem) 同名不同版本；
            None 无重复。
        """
        for card in sorted(self.tree.iter_all_note_files()):
            if not card.name.startswith("书籍-"):
                continue
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
        summary: Optional[Dict[str, Any]] = None,
        llm_note: Optional[str] = None,
        comment: str = "",
    ) -> str:
        """组装卡正文：语义标题（有总结时）+ 评论行 + 内嵌原附件 +
        （可选）摘要各节 + 提取全文（短内联，长外置留链接节）。

        方案 B（2026-09-12 用户裁决）：全文 >INLINE_BODY_MAX 时原子写入
        ``attachments/媒体/<笔记同名>.md``（同名跳过幂等；实现与链接
        管线共用 write_text_skip_existing），卡上只留「## 全文」链接节；
        写入失败降级为内联保底——卡绝不丢内容。
        转写置信度偏低（>0 且 <0.70）时卡面加警告行（2026-09-14 KM
        评审裁决：同音错字靠这层信号 + 人工回放兜底）。
        摘要节与链接管线同序（观点总结/分观点/金句/实体，2026-09-15
        裁决 B）；总结被跳过/失败时 llm_note 警示行不缺席。
        2026-09-15 评审 P1：有总结时 H1/frontmatter title 用语义标题
        （kind-主题；文件名保持哈希不动——幂等锚点），评论附着见
        _diary_comment_near。
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
        if llm_note:
            warn += f"> {llm_note}\n\n"
        summary_md = _summary_sections(summary)
        h1, fm = _semantic_h1(kind, stamp, summary)
        comment_md = f"> 💬 我的评论：{comment}\n\n" if comment else ""
        head = (
            f"{fm}# {h1}\n\n{comment_md}![[{self._key(path)}]]\n\n"
            f"{warn}{summary_md}"
        )
        if len(body) > INLINE_BODY_MAX:
            rel = f"{ATTACHMENTS_DIR}/{MEDIA_SUBDIR}/{note_stem}.md"
            target = self.tree.attachments_dir.parent / rel
            wrote = write_text_skip_existing(target, body)
            if wrote or target.exists():
                return f"{head}## 全文\n\n[[{rel}|查看{section}]]\n"
            logger.warning("全文落盘失败，降级为卡内联: %s", target)
        return f"{head}## {section}\n\n{body}\n"

    def _load_state(self) -> Dict[str, Any]:
        """加载附件处理状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
