"""链接自动分发：扫描笔记中的抖音/小红书链接 → 抓取转写 → 建"待确认"笔记。

定位：独立顶层组合模块（composition root），是 memory 与 processors
之间唯一的接线点（两者互不 import）。触发由 systemd 定时器驱动
（docker/systemd/atelierr-links.*，每 15 分钟一次）；**人工确认在
产出端**：自动创建的笔记带 ``tags=["待确认"]``，人在 Obsidian 阅读
转写内容后自行移除标签，系统不做进一步状态机。

纪律（与 DEVELOPMENT-PLAN-3MVP.md backlog 约定一致）：
- 只新增笔记与附件，绝不改写/移动/删除既有笔记（源笔记原样保留；
  唯一例外：处理成功后在源**日记**行尾追加 `` → [[卡]]`` 回链——
  2026-09-12 用户裁决，仅限 YYYY-MM-DD.md，原子写并还原 mtime）；
- 原视频保存（2026-09-10 用户裁决 G2）：处理器转写后压 480p 经
  metadata 交回 bytes，本模块原子写入 ``attachments/<平台>/``（抖音/
  小红书/），笔记内嵌可播；下载原件由处理器随临时目录删除，压缩失败
  时 bytes 为原件保底；同名已存在跳过（幂等），落盘失败只记日志不
  阻断建笔记；
- 幂等：URL 处理状态记录于 ``<state_dir>/processed_links.json``，
  同一链接只成功处理一次；自动产出笔记（source: link）不回收，
  其来源行链接（落地页 URL 与短链字符串不同）不会自我循环；
- 失败最多重试 3 次，超限标记 failed 不再重试——避免 Whisper 模型
  每 15 分钟为空转反复加载；
- pending_delete 笔记跳过；
- 扫描前先 process_pending() 登记新同步来的裸笔记（与每日 sync 同源）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import frontmatter

from scripts.memory.core import LAYERS, MemoryTree
from scripts.utils.file_utils import write_text_skip_existing
from scripts.utils.state_store import read_json, write_json
from scripts.memory.watcher import MemoryWatcher
from scripts.processors.link import LinkProcessor, URL_RE, detect_platform

logger = logging.getLogger(__name__)

#: 单个 URL 的最大处理尝试次数（超限标记 failed）
MAX_ATTEMPTS = 3

#: 自动产出笔记的标签（人工确认后由人移除）
REVIEW_TAG = "待确认"

#: 分发支持的平台 → 产出笔记的平台标签
_PLATFORM_TAGS = {"douyin": "抖音", "xhs": "小红书", "bilibili": "B站"}

#: 自动产出笔记的 source 值；这类笔记是"产出"不是"输入"，其中的来源行
#: 链接不再回收（短链与落地页 URL 字符串不同，仅靠状态去重挡不住自我循环，
#: 2026-09-02 小红书真实样本踩坑）
_AUTO_NOTE_SOURCE = "link"

#: 分享文本样板行（整行视为平台样板，不算用户评论）：抖音「复制打开抖音」、
#: 小红书「【小红书】里的笔记已备好/复制本条信息」等真实样本（2026-09-10）
_BOILERPLATE_RE = re.compile(r"复制打开抖音|【小红书】|复制后快来|复制本条信息")

#: 剥掉 URL 后只剩这类"指路词"的行不算评论（「链接」「看看这个」之类；
#: 精确匹配的白名单式启发——宁可漏掉一句短评论，不把样板当评论）
_POINTER_WORDS = frozenset(
    {
        "链接", "视频", "笔记", "这个", "看看", "看一看", "看看这个",
        "看这个", "🔗", "分享一下", "分享", "mark", "Mark", "MARK",
        "马住", "收藏", "存档",
    }
)

#: 用户评论展示上限（卡片正文里截断）
_COMMENT_MAX_CHARS = 200

#: 日记列表行的时间戳前缀（``- HH:MM ``）：剥掉它再判断用户评论
#: （2026-09-12 碎片治理：飞书文字并入当天日记后，链接所在行必然带
#: 时间前缀；纯时间行剥完为空自然跳过，同行带人话的取出干净评论）
_TIME_PREFIX_RE = re.compile(r"^[-*\s]*\d{1,2}:\d{2}(?::\d{2})?\s+")

#: 日记文件名（2026-09-12.md）：链接回链只追加在日记行尾——其他笔记
#: 机器绝不改写（红线），日记追加已有用户批准先例（飞书文字并入）
_DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def extract_comment(body: str, url: str) -> str:
    """从含链接的源笔记正文提取用户随手评论（裁决 C2：确认卡上展示意图）。

    规则：整行命中平台分享样板的丢弃；其余行剥掉 URL 后保留非空片段
    （只剩「链接」「看看」这类指路词的不算）。全无用户文字（纯分享文本）
    返回空串——确认卡就不带评论行，绝不硬凑。

    Args:
        body: 源笔记正文。
        url: 被处理的链接（从文本中剥除）。

    Returns:
        str: 用户评论（≤200 字）；无则空串。
    """
    fragments: List[str] = []
    for line in body.splitlines():
        if _BOILERPLATE_RE.search(line):
            continue
        text = URL_RE.sub("", line)
        text = _TIME_PREFIX_RE.sub("", text).strip(" \t，。：:;；")
        if len(text) >= 2 and text not in _POINTER_WORDS:
            fragments.append(text)
    comment = "；".join(fragments).strip()
    return comment[:_COMMENT_MAX_CHARS]


class LinkDispatcher:
    """扫描全部笔记，把未处理的抖音链接分发给 LinkProcessor。

    Attributes:
        tree: MemoryTree 实例。
        state_path: URL 处理状态文件（processed_links.json）。
    """

    def __init__(
        self,
        tree: MemoryTree,
        processor_factory: Optional[Callable[[], LinkProcessor]] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            processor_factory: 处理器工厂（测试注入假处理器用），
            缺省为 LinkProcessor。
        """
        self.tree = tree
        self._factory = processor_factory or LinkProcessor
        self._sources: Dict[str, Path] = {}
        self.state_path = Path(tree.state_dir) / "processed_links.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与分发。

        Args:
            dry_run: 只报告不处理（不建笔记、不写状态）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/found/created/failed/
            skipped/comments）。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "found": 0,
            "created": [],
            "failed": [],
            "skipped": 0,
            "comments": {},
        }
        for url in self._collect_urls(report):
            entry = state.get(url)
            if entry and entry.get("status") in ("done", "failed"):
                report["skipped"] += 1
                continue
            report["found"] += 1
            if dry_run:
                continue
            self._process_one(url, state, report)
        if not dry_run:
            self._save_state(state)
        return report

    def _collect_urls(self, report: Dict[str, Any]) -> List[str]:
        """扫描全部已登记笔记正文，收集去重后的支持平台链接（保持出现顺序）。

        跳过 pending_delete 笔记与自动产出笔记（source: link）——后者是
        产出而非输入，其来源行里的链接（落地页 URL 与原短链字符串不同）
        不回收，杜绝自我循环。顺带记录每个 URL 首次出现的源笔记路径
        （``self._sources``，供提取用户评论用）。
        """
        urls: List[str] = []
        seen = set()
        self._sources: Dict[str, Path] = {}
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                if self.tree.is_pending_delete(note_path):
                    continue
                if self._is_auto_note(note_path):
                    continue
                report["scanned"] += 1
                body = self.tree.read_note(note_path)
                for match in URL_RE.finditer(body):
                    url = match.group(0)
                    if detect_platform(url) in _PLATFORM_TAGS and url not in seen:
                        seen.add(url)
                        urls.append(url)
                        self._sources[url] = note_path
        return urls

    @staticmethod
    def _is_auto_note(note_path: Path) -> bool:
        """是否自动产出笔记（frontmatter source 为 link）；损坏按人工笔记处理。"""
        try:
            post = frontmatter.loads(Path(note_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏不误跳过
            return False
        return str(post.get("source") or "") == _AUTO_NOTE_SOURCE

    def _process_one(
        self, url: str, state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """处理单个链接：成功建笔记，失败计次数（3 次熔断）。"""
        entry = state.setdefault(url, {"attempts": 0})
        entry["attempts"] += 1
        result = self._factory().process(url)
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if result.success:
            platform = detect_platform(url) or "link"
            doc_id = str(
                result.metadata.get("video_id") or result.metadata.get("note_id") or ""
            )
            title = str(result.metadata.get("title") or "")
            # 原视频（480p，含原件保底）落盘 attachments/<平台>/——processors
            # 不感知存储，bytes 经 metadata 交回，由本层写入；落盘失败只
            # 记日志，不阻断笔记创建（笔记仍带来源行 URL 可回溯）
            video_blob = result.metadata.pop("video_blob", None)
            video_rel = result.metadata.get("video_rel")
            if video_blob and video_rel:
                self._save_video(str(video_rel), video_blob)
            # 全文外置（2026-09-12 方案 B 用户裁决）：>INLINE_BODY_MAX 的
            # 正文由处理器经 metadata 交回，卡上只留「## 全文」链接节；
            # 落盘失败只记日志，不阻断建卡
            transcript_rel = result.metadata.pop("transcript_rel", None)
            transcript_text = result.metadata.pop("transcript_text", None)
            if transcript_rel and transcript_text:
                self._save_transcript(str(transcript_rel), str(transcript_text))
            filename = self._note_filename(url, platform, doc_id, title)
            try:
                self.tree.create_note(
                    filename,
                    result.markdown,
                    source="link",
                    tags=[REVIEW_TAG, _PLATFORM_TAGS.get(platform, "链接")],
                )
            except FileExistsError:
                # 同名不同源（标题撞车）：追加内容 id 短码再试一次；
                # 仍冲突视为同内容重跑（状态丢失后的重放），不再建
                if doc_id:
                    filename = self._note_filename(
                        url, platform, doc_id, f"{title}-{doc_id[:6]}" if title else ""
                    )
                try:
                    self.tree.create_note(
                        filename,
                        result.markdown,
                        source="link",
                        tags=[REVIEW_TAG, _PLATFORM_TAGS.get(platform, "链接")],
                    )
                except (ValueError, FileExistsError):
                    pass
            except ValueError:
                pass
            entry["status"] = "done"
            entry["note"] = filename
            comment = self._comment_for(url)
            if comment:
                entry["comment"] = comment
                report["comments"][filename] = comment
            self._annotate_source(url, filename)
            report["created"].append(filename)
            return
        entry["last_error"] = (result.error or "")[:300]
        if entry["attempts"] >= MAX_ATTEMPTS:
            entry["status"] = "failed"
        report["failed"].append({"url": url, "error": result.error})

    def _annotate_source(self, url: str, filename: str) -> None:
        """在源日记行的链接后补 `` → [[产出卡]]`` 回链（2026-09-12 用户
        裁决：日记里的分享原文是死胡同，处理完应能一键跳到卡）。

        只在日记（YYYY-MM-DD.md）行尾追加——其他笔记机器绝不改写；
        原子写入并还原 mtime（回链不进 confidence 时钟）；行内已含回链
        跳过（幂等，重跑不重复追加）。任何失败只记日志，不影响主流程。

        Args:
            url: 被处理的链接（定位行）。
            filename: 产出笔记文件名（取 stem 做 wikilink）。
        """
        src = self._sources.get(url)
        if src is None or not _DAILY_NOTE_RE.match(Path(src).name):
            return
        stem = Path(filename).stem
        try:
            path = Path(src)
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            for i, line in enumerate(lines):
                if url in line and f"[[{stem}]]" not in line:
                    lines[i] = line.rstrip("\n") + f" → [[{stem}]]\n"
                    break
            else:
                return
            stat = path.stat()
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(lines), encoding="utf-8")
            os.replace(tmp, path)
            os.utime(path, (stat.st_atime, stat.st_mtime))
        except OSError as exc:
            logger.warning("日记回链写入失败 %s: %s", src, exc)

    def _comment_for(self, url: str) -> str:
        """提取该 URL 源笔记里的用户随手评论（无源笔记或无评论返回空串）。"""
        src = self._sources.get(url)
        if src is None:
            return ""
        try:
            return extract_comment(self.tree.read_note(src), url)
        except Exception:  # noqa: BLE001 - 评论提取失败不影响主流程
            return ""

    def _save_video(self, rel: str, blob: bytes) -> None:
        """原视频原子写入 attachments 平台目录；同名已存在跳过（同内容重跑幂等）。

        rel 由处理器按 ``attachments/<平台>/<名>.mp4`` 约定给出（笔记
        markdown 里的 ``![[...]]`` 内嵌与之为同一字符串）；绝不覆盖既有
        文件（同路径=同内容，跳过即幂等）。
        """
        target = self.tree.notes_dir / rel
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_bytes(blob)
            os.replace(tmp, target)
        except OSError as exc:
            logger.warning("保存原视频失败 %s: %s", target, exc)
            try:
                tmp.unlink()
            except OSError:
                pass

    def _save_transcript(self, rel: str, text: str) -> None:
        """全文原子写入 attachments 平台目录；同名已存在跳过（同内容重跑幂等）。

        与 _save_video 同规：rel 由处理器按 ``attachments/<平台>/<名>.md``
        约定给出（卡 markdown 里的 ``[[...]]`` 链接与之为同一字符串）；
        绝不覆盖既有文件。实现收敛在
        :func:`scripts.utils.file_utils.write_text_skip_existing`（与
        media 管线共用唯一实现）。
        """
        write_text_skip_existing(self.tree.notes_dir / rel, text)

    @staticmethod
    def _note_filename(url: str, platform: str, doc_id: str, title: str = "") -> str:
        """产出笔记文件名：<平台中文>-<标题>.md（人读优先）。

        标题做文件系统净化（半框非法字符转 -、压缩空白、截 60 字）；
        无标题回退 <平台>-<内容id>.md；两者皆无回退 URL 短哈希。
        """
        label = _PLATFORM_TAGS.get(platform, platform)
        if title:
            safe = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", title)
            # “#”在 wikilink 里是标题引用符，出现在文件名会断晨报/摘要的
            # [[...]] 链接（2026-09-12 实测：抖音通用标题带 #id），剔除
            safe = safe.replace("#", "")
            safe = re.sub(r"\s+", " ", safe).strip().strip(".")
            if len(safe) > 60:
                safe = safe[:60].rstrip()
            if safe:
                return f"{label}-{safe}.md"
        if doc_id:
            return f"{platform}-{doc_id}.md"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        return f"{platform}-{digest}.md"

    def _load_state(self) -> Dict[str, Any]:
        """加载 URL 处理状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
