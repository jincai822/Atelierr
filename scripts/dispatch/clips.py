"""网页剪藏确认卡：新剪藏 → LLM 摘要 → 飞书确认卡；同 url 重复剪藏检测。

定位：Obsidian Web Clipper 经 Syncthing 落地的笔记（source: webclip、
tags 含「剪藏」「待确认」）原本要等次日晨报才进入视野。本模块挂在
links 定时班次（每 15 分钟）里扫出新剪藏，复用链接处理器的 LLM 摘要
管道（processors/link.py 的 ``_summarize``，DeepSeek）生成观点摘要，
推送带「✅ 确认」按钮的飞书卡片——确认/归档回调与链接笔记完全同路
（dispatch/feishu.py）。**摘要只进卡片，不落笔记**（机器不改写剪藏
笔记，卡片是系统外视图；想要摘要进正文请到 Obsidian 人工誊写）。

纪律（与 dispatch/links.py 同源）：
- 机器绝不改写/移动剪藏笔记；
- 幂等：已处理笔记按 frontmatter id 登记
  ``<state_dir>/clip_cards.json``（改名/移动/重启不重复推卡、不重复
  摘要）；推送失败视为已处理（与链接笔记同一语义：丢卡不补，晨报
  「待确认」清单兜底），LLM 摘要每篇最多调一次（API 成本护栏）；
- 重复剪藏（frontmatter ``url`` 相同，含与历史上已处理/已确认的
  剪藏撞车）：较新的一篇在 sidecar 标 pending_delete——这是唯一受
  批准的机器删除路径，人工 review → purge 收尾——并推无按钮信息卡
  告知；重复篇不做 LLM 摘要；
- pending_delete / 无「待确认」标签 / 非 webclip 来源的笔记不处理；
  frontmatter 损坏跳过并记日志，不中断班次。

触发：dispatch_cli links 子命令内（与链接分发同一把 dispatch.lock、
同一个 15 分钟班次）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import frontmatter

from scripts.dispatch.archive import derive_archive_dir
from scripts.memory.core import LAYERS, MemoryTree
from scripts.memory.watcher import MemoryWatcher
from scripts.processors.link import _SUMMARIZE_CLIP_PROMPT, LinkProcessor
from scripts.utils.state_store import read_json, write_json

logger = logging.getLogger(__name__)

#: 与 dispatch/links.py REVIEW_TAG 同值：人工确认门标签
REVIEW_TAG = "待确认"

#: 剪藏笔记的来源标识（Obsidian Web Clipper 模板写入 frontmatter）
CLIP_SOURCE = "webclip"

#: 确认卡正文最多列出的 LLM 要点条数（其余要点请打开原文）
_CARD_POINTS_MAX = 3


class ClipDispatcher:
    """扫出待确认剪藏笔记：LLM 摘要 + 飞书确认卡；检测同 url 重复剪藏。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 已处理剪藏登记表（clip_cards.json）。
    """

    def __init__(
        self,
        tree: MemoryTree,
        summarizer_factory: Optional[Callable[[], Any]] = None,
        notify: Optional[Callable[..., Any]] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            summarizer_factory: 摘要器工厂（对象须提供
                ``_summarize(text, prompt=...)`` 与 ``llm_max_chars``；
                缺省 LinkProcessor）。测试注入假实现用。
            notify: 推送回调，签名同 dispatch.notify.send_dispatch_notice
                （``(title, message, confirm_note=None)``）；None 不推送
                （状态照写，保证摘要只做一次）。
        """
        self.tree = tree
        self._factory = summarizer_factory or LinkProcessor
        self._notify = notify
        self.state_path = Path(tree.state_dir) / "clip_cards.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮剪藏扫描：登记新同步来的笔记，处理未处理的待确认剪藏。

        Args:
            dry_run: 只报告不处理（不推卡、不摘要、不标重复、不写状态）。

        Returns:
            Dict[str, Any]: scanned / new / cards / duplicates / skipped。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "new": 0,
            "cards": [],
            "duplicates": [],
            "skipped": 0,
        }
        clips = self._collect_clips(report)
        # 已被本功能处理过（在 state 且非重复标记）且文件还在的剪藏，
        # 其 url 视为"已占用"：后来者撞 url 即重复。只用 live 文件播种——
        # 原篇若已被用户 purge/删除，同 url 再剪不再误判。
        taken_urls = {
            clip["url"]
            for clip in clips
            if clip["url"]
            and clip["id"] in state
            and not state[clip["id"]].get("duplicate")
        }
        winners: Dict[str, str] = {}  # 同批去重：url -> 先到的 clip id
        for clip in clips:
            if clip["id"] in state or not clip["review"]:
                continue
            report["new"] += 1
            if dry_run:
                continue
            self._process_one(clip, taken_urls, winners, state, report)
        if not dry_run:
            self._save_state(state)
        return report

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------

    def _collect_clips(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """收集全部 webclip 笔记（不含 pending_delete），按 created 排序。

        无「待确认」标签的也收集（提供重复检测的 url 底账）；frontmatter
        损坏或缺 id 的跳过计数。排序键 (created, rel)：同 url 撞车时
        "较新的一篇"有确定定义。
        """
        clips: List[Dict[str, Any]] = []
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                if self.tree.is_pending_delete(note_path):
                    continue
                report["scanned"] += 1
                try:
                    post = frontmatter.loads(
                        Path(note_path).read_text(encoding="utf-8")
                    )
                except Exception as exc:  # noqa: BLE001 - 损坏跳过不中断
                    logger.warning("跳过无法解析的文件 %s: %s", note_path, exc)
                    report["skipped"] += 1
                    continue
                if str(post.get("source") or "") != CLIP_SOURCE:
                    continue
                note_id = post.get("id")
                if note_id is None:
                    report["skipped"] += 1
                    continue
                tags = [str(tag) for tag in (post.get("tags") or [])]
                clips.append(
                    {
                        "rel": self.tree._rel_key(Path(note_path)),
                        "id": str(note_id),
                        "title": str(post.get("title") or Path(note_path).stem),
                        "url": str(post.get("url") or "").strip(),
                        "created": str(post.get("created") or ""),
                        "review": REVIEW_TAG in tags,
                        "body": post.content or "",
                        "post": post,
                    }
                )
        clips.sort(key=lambda clip: (clip["created"], clip["rel"]))
        return clips

    # ------------------------------------------------------------------
    # 处理
    # ------------------------------------------------------------------

    def _process_one(
        self,
        clip: Dict[str, Any],
        taken_urls: set,
        winners: Dict[str, str],
        state: Dict[str, Any],
        report: Dict[str, Any],
    ) -> None:
        """处理一篇新剪藏：重复检测 → （非重复）摘要 + 确认卡。"""
        url = clip["url"]
        if url and (url in taken_urls or url in winners):
            self._mark_duplicate(clip, state, report)
            return
        summary, status = self._summarize(clip)
        self._send(
            "Atelierr 剪藏待确认",
            self._card_body(clip, summary),
            confirm_note=clip["rel"],
        )
        state[clip["id"]] = {
            "path": clip["rel"],
            "url": url,
            "summary_status": status,
            "notified": datetime.now(timezone.utc).isoformat(),
        }
        if url:
            winners[url] = clip["id"]
        report["cards"].append(clip["rel"])

    def _mark_duplicate(
        self, clip: Dict[str, Any], state: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """同 url 重复剪藏：sidecar 标 pending_delete（不动文件）+ 信息卡。"""
        entry = self.tree._entry(self.tree.notes_dir / clip["rel"])
        if entry is not None:
            entry["pending_delete"] = True
            self.tree._save_index()
        state[clip["id"]] = {
            "path": clip["rel"],
            "url": clip["url"],
            "duplicate": True,
            "notified": datetime.now(timezone.utc).isoformat(),
        }
        self._send(
            "Atelierr 重复剪藏",
            f"《{clip['title']}》与已有剪藏重复（同一链接），较新的这篇已列入"
            f"清理审查（review → purge），原篇不受影响：{clip['rel']}",
        )
        report["duplicates"].append(clip["rel"])

    def _summarize(self, clip: Dict[str, Any]) -> tuple:
        """调链接处理器的 LLM 摘要管道（文章全文截到 llm_max_chars）。

        截断与链接处理器的成本护栏同源：摘要只需开头主体，长文不整篇
        送 API；任何失败/跳过返回 (None, 状态)，卡片降级为无摘要形态。
        """
        try:
            summarizer = self._factory()
            max_chars = int(getattr(summarizer, "llm_max_chars", 6000))
            return summarizer._summarize(
                clip["body"][:max_chars], prompt=_SUMMARIZE_CLIP_PROMPT
            )
        except Exception as exc:  # noqa: BLE001 - 摘要失败不阻塞推卡
            return None, f"failed:{type(exc).__name__}"

    def _card_body(self, clip: Dict[str, Any], summary: Optional[Dict]) -> str:
        """确认卡正文：标题 +（可选）观点总结与至多 3 条要点 + 建议归档。"""
        lines = [f"《{clip['title']}》已剪藏入库"]
        if summary:
            lines += ["", str(summary.get("summary") or "").strip()]
            points = [
                str(point).strip()
                for point in (summary.get("points") or [])
                if str(point).strip()
            ][:_CARD_POINTS_MAX]
            if points:
                lines += ["", "要点："]
                lines += [f"{i}. {p}" for i, p in enumerate(points, 1)]
        hint = self._archive_hint(clip)
        if hint:
            lines += ["", hint]
        return "\n".join(lines)

    @staticmethod
    def _archive_hint(clip: Dict[str, Any]) -> Optional[str]:
        """「建议归档：<平台>/[<中图法标签>/]」；规则与链接卡片同源。"""
        platform, category = derive_archive_dir(clip["post"])
        if not platform:
            return None
        hint = f"建议归档：{platform}/"
        if category:
            hint += f"{category}/"
        return hint

    def _send(self, title: str, message: str, confirm_note: Optional[str] = None) -> None:
        """推送（注入回调）；失败静默——丢卡不补，晨报待确认兜底。"""
        if self._notify is None:
            return
        try:
            if confirm_note:
                self._notify(title, message, confirm_note=confirm_note)
            else:
                self._notify(title, message)
        except Exception as exc:  # noqa: BLE001 - 推送失败不影响主流程
            logger.warning("剪藏卡片推送失败 %s: %s", title, exc)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        """加载剪藏登记状态；文件缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（scripts/utils/state_store 统一实现）。"""
        write_json(self.state_path, state, indent=2)
