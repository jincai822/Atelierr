"""晨间摘要：每天定时创建一条"今日摘要"笔记（只新建，不改写）。

摘要写入 ``memory/系统/`` 子目录（NOTE_EXCLUDED_DIRS 成员）：
摘要是 Agent 的输出而非记忆——留在扫描域内会污染搜索排名、并用
摘要链接给 references 引用信号"刷票"（自我指涉回路）。Obsidian
里照常可见可读（Dataview 全库查询不受影响），仅记忆机制不扫描。

内容五节（wikilink 列表，点开即达）：
- 待我确认：当前带"待确认"标签的笔记（摘除标签后次日自然消失）；
- 提炼候选：从未提炼（进压缩层 distilled/）且值得动笔的笔记，两路汇合——
  ①被反复推送（≥2 次，ResponseProbe 推算）仍未提炼；
  ②已确认且创建满 DISTILL_MIN_AGE_DAYS 天（"沉一沉再提炼"）。
  日报/控制台/摘要/划重点清单/待确认/待办不算候选；最多列
  MAX_DISTILL_CANDIDATES 条（推送多的在前，其次最旧的在前）。
  同时把 stem 写进摘要 frontmatter 的 undistilled 字段，供控制台
  Dataview 桥接——sidecar 数据它看不见；并附 wiki 体检（validate
  出的缺字段/缺互链条目）；
- 待办进行中：当前带"待办"标签的笔记；
- 今日复习：遗忘临界区内的笔记（ResurfaceManager，decay 的反面；
  检索式推送——只列标题，提示"先回忆再点开"，点开看一眼即重置时钟，
  确认无价值的留给 review→purge，值得留存的提炼进压缩层）；
- 昨日新入库：frontmatter created 日期为昨天的笔记（附入口分布一行，
  捕获统计见 scripts/dispatch/stats.py）；
- 本周捕获统计（仅周日）：近 7 天各入口捕获条数、确认率、wiki 沉淀数
  （2026-09-10 用户裁决 D1「都放」；只读聚合，不新增写入面）；
- 系统自检：各定时器活性——它们全是"跑了就写 state"的模型，
  状态文件 mtime 新鲜 = 班次活着；沉默超阈值 = 定时器疑似停了
  （systemd 不会主动来告诉你），异常项数同步进推送文案。

纪律（与 dispatch 模块同源）：
- 幂等：文件名 ``系统/今日摘要-YYYY-MM-DD.md``，当天已存在则跳过；
- 摘要笔记 ``source="digest"``，todos 分发跳过它（防把摘要里的
  待办文本再喂给 LLM 空转）；
- 只读全部笔记的 frontmatter/正文，绝不改写；
- 复习推送冷却时钟只写 ``<state_dir>/resurface.json``，且仅在摘要
  笔记真正创建成功后记录（dry-run/跳过不烧冷却）；
- 推送响应观测（实验 0）只写 ``<state_dir>/response_probe.json``，
  同样仅在真实运行时执行。

触发：systemd 每日定时器（docker/systemd/atelierr-digest.*）或
人工 ``dispatch_cli digest``。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.response_probe import ResponseProbe
from scripts.dispatch.stats import (
    capture_stats,
    failure_stats,
    render_capture_line,
    render_failure_line,
    render_weekly_stats,
)
from scripts.dispatch.sysdir import SYSTEM_DIRNAME, write_machine_note
from scripts.utils.state_store import read_json
from scripts.memory.core import LAYERS, SYNC_CONFLICT_RE, MemoryTree
from scripts.memory.decay import DecayManager
from scripts.memory.resurface import ResurfaceManager
from scripts.memory.watcher import MemoryWatcher
from scripts.wiki.manager import WikiManager

MIN_PUSH_COUNT = 2  # 推送达到此次数仍未提炼，进"提炼候选"节
DISTILL_MIN_AGE_DAYS = 3  # 已确认笔记创建满此天数即可提炼（沉一沉再动笔）
MAX_DISTILL_CANDIDATES = 5  # 候选节最多列几条（防长列表制造压力）
STALE_PENDING_DAYS = 7  # 根目录待确认滞留超此天数，晨报「滞留提醒」点名
STALE_HUMAN_DAYS = 14  # 根目录人写/已确认笔记滞留超此天数，同节点名（入口收敛裁决⑤）
#: 「你的笔记」组排除的机器来源（摘要/清单/系统容器不算人写）
STALE_HUMAN_EXCLUDED_SOURCES = frozenset({"digest", "highlights", "system"})

#: 系统自检探测点（名称, state_dir 内相对路径, 允许的最大沉默秒数）：
#: 15 分钟班次给 2 小时余量；decay 每日 03:00 给 30 小时
_HEALTH_PROBES = (
    ("links 分发", "processed_links.json", 2 * 3600),
    ("media 分发", "processed_media.json", 2 * 3600),
    ("todos 分发", "processed_todos.json", 2 * 3600),
    ("highlights 分发", "processed_highlights.json", 2 * 3600),
    ("decay 分层", "reports", 30 * 3600),
)

#: 摘要落盘目录（NOTE_EXCLUDED_DIRS 成员，记忆机制不扫描的机器产物区）
DIGEST_DIRNAME = SYSTEM_DIRNAME

DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # 日记不算知识候选
DASHBOARD_STEMS = frozenset({"主页", "控制台"})  # 门面文件不算候选
DISTILL_EXCLUDED_SOURCES = frozenset({"digest", "highlights"})  # 摘要/清单容器


def _health_lines(state_dir: Path, now: Optional[datetime] = None) -> Tuple[List[str], int]:
    """系统自检行（定时器活性）与异常项数。

    定时器全是"跑了就写 state"的模型：状态文件 mtime 新鲜 = 班次
    活着；沉默超阈值或文件缺失 = 疑似停了（systemd 不会来告诉你）。
    decay 探测的是 reports/ 目录里最新一份 decay-*.md。

    Args:
        state_dir: 机器状态目录。
        now: 判定基准（测试注入用；缺省当前时间）。

    Returns:
        Tuple[List[str], int]: (自检行列表, 异常项数)。
    """
    now = now or datetime.now()
    lines: List[str] = []
    stale = 0
    for name, rel, max_silence in _HEALTH_PROBES:
        path = Path(state_dir) / rel
        if path.is_dir():
            reports = sorted(path.glob("decay-*.md"))
            probe = reports[-1] if reports else None
        else:
            probe = path if path.exists() else None
        if probe is None:
            lines.append(f"- {name}：⚠️ 无状态文件（从未运行或被清理）")
            stale += 1
            continue
        age_s = max(int(now.timestamp() - probe.stat().st_mtime), 0)
        age = _age_text(age_s)
        if age_s > max_silence:
            lines.append(
                f"- {name}：⚠️ 沉默 {age}（定时器疑似停了："
                "systemctl --user list-timers 查一下）"
            )
            stale += 1
        else:
            lines.append(f"- {name}：{age} ✅")
    return lines, stale


def _age_text(age_s: int) -> str:
    """沉默时长的人性化文本（分钟/小时/天）。"""
    if age_s < 3600:
        return f"{age_s // 60} 分钟前"
    if age_s < 48 * 3600:
        return f"{age_s // 3600} 小时前"
    return f"{age_s // 86400} 天前"


class DigestDispatcher:
    """每日晨间摘要笔记生成器。

    Attributes:
        tree: MemoryTree 实例。
        resurface: 复习队列管理器（默认按内置窗口构造）。
        probe: 推送响应观测器（实验 0，随摘要每日执行一次）。
    """

    def __init__(
        self, tree: MemoryTree, resurface: Optional[ResurfaceManager] = None
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            resurface: 复习队列管理器；None 时用默认窗口构造。
        """
        self.tree = tree
        self.resurface = resurface or ResurfaceManager(tree)
        self.probe = ResponseProbe(tree)

    def run(
        self, dry_run: bool = False, today: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成当日摘要；当天已存在则跳过。

        Args:
            dry_run: 只返回将写入的内容，不建笔记。
            today: 覆盖"今天"（YYYY-MM-DD，测试用）。

        Returns:
            Dict[str, Any]: {created, skipped, counts, review, markdown}；
                counts 含 pending/todos/resurface/undistilled/yesterday_new；
                review 是今日复习候选（含 title/relpath，供复习卡按钮定位）。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        today = today or datetime.now().strftime("%Y-%m-%d")
        filename = f"今日摘要-{today}.md"
        digest_dir = Path(self.tree.notes_dir) / DIGEST_DIRNAME
        target = digest_dir / filename
        if target.exists():
            return {
                "created": None,
                "skipped": True,
                "counts": {},
                "review": [],
                "markdown": "",
            }
        pending, todos, yesterday_new = self._collect(today)
        stale_pending, stale_human = self._stale_pending(today)
        review = self.resurface.candidates()
        review_stems = [Path(item["filename"]).stem for item in review]
        wiki = WikiManager(self.tree)
        undistilled = self._distill_candidates(wiki, today)
        wiki_issues = wiki.validate()
        health, health_stale = _health_lines(Path(self.tree.state_dir))
        # 捕获统计（裁决 D1）：昨日入口分布一行；周日加本周详细节
        yesterday = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        capture_line = render_capture_line(
            capture_stats(self.tree, days=1, today=yesterday)
        )
        # 熔断失败可见（2026-09-13 评审毛病 3）：静默熔断进晨报点名
        failure_line = render_failure_line(failure_stats(Path(self.tree.state_dir)))
        # 昨日 decay 账（2026-09-13 参数校准可见性）：decay-last.json 的
        # 日期是昨天才显示（更早的已过时不误导）
        decay_line = None
        decay_last = read_json(Path(self.tree.state_dir) / "decay-last.json", None)
        if isinstance(decay_last, dict) and decay_last.get("date") == yesterday:
            decay_line = (
                f"昨日 decay：在库 {decay_last.get('total', '?')} 篇 · "
                f"分层迁移 {decay_last.get('relayered', 0)} · "
                f"新进待删 {decay_last.get('pending', 0)} · "
                f"日记豁免 {decay_last.get('daily_exempt', 0)}"
            )
        # 判断直收账（2026-09-16 回路三启用）：昨日新收判断计数，
        # 0 条不出现该行（安静小节，不带按钮不打断）
        from scripts.dispatch.judgments import pending_proposals, registered_since

        judgments_new = registered_since(self.tree, yesterday)
        judgment_line = (
            f"昨日新收判断 {judgments_new} 条 → memory/wiki/cognition/ 登记处"
            if judgments_new
            else None
        )
        # 机器提名待批候选（安静小节：列在摘要里，飞书回复「批 N/略 N」审批）
        judgment_proposals = pending_proposals(self.tree)
        # 提炼草稿待审计数（2026-09-18 深加工链路：「提 N/弃 N」审批）
        from scripts.dispatch.distill import pending_drafts

        distill_drafts = pending_drafts(self.tree)
        # OKF Freshness 到期复查（2026-09-18 全量采纳）：stale_after 到期
        # 的 stable 卡点名——复查与顺延是人的动作，机器只点名不改卡
        from scripts.wiki import curation

        stale_wiki = curation.list_stale_cards(
            Path(self.tree.notes_dir) / curation.DISTILLED_DIRNAME, today
        )
        stale_wiki_lines = [
            f"- [[{stem}]]（{date} 到期）：还准就把 stale_after 往后改半年"
            for stem, _title, date in stale_wiki
        ] or None
        is_sunday = datetime.strptime(today, "%Y-%m-%d").weekday() == 6
        weekly_lines = (
            render_weekly_stats(capture_stats(self.tree, days=7, today=today))
            if is_sunday
            else None
        )
        markdown = self._build(
            today, pending, todos, review_stems, yesterday_new,
            undistilled, wiki_issues, health, health_stale,
            capture_line=capture_line, weekly_lines=weekly_lines,
            failure_line=failure_line, decay_line=decay_line,
            stale_pending_lines=stale_pending, stale_human_lines=stale_human,
            judgment_line=judgment_line,
            judgment_proposals=judgment_proposals,
            distill_draft_count=len(distill_drafts),
            stale_wiki_lines=stale_wiki_lines,
        )
        created = None
        if not dry_run:
            write_machine_note(
                Path(self.tree.notes_dir), filename, markdown,
                source="digest", tags=["摘要"],
            )
            self.resurface.mark_pushed([item["id"] for item in review])
            self.probe.register(review)
            self.probe.check_pending()
            created = f"{DIGEST_DIRNAME}/{filename}"
        return {
            "created": created,
            "skipped": False,
            "counts": {
                "pending": len(pending),
                "todos": len(todos),
                "resurface": len(review),
                "undistilled": len(undistilled),
                "yesterday_new": len(yesterday_new),
                "health_stale": health_stale,
                "stale": len(stale_pending) + len(stale_human),
                "judgment_proposals": len(judgment_proposals),
            },
            "review": review,
            "markdown": markdown,
        }

    def _distill_candidates(self, wiki: WikiManager, today: str) -> List[str]:
        """提炼候选（薄封装）：逻辑已提升为模块级
        :func:`compute_distill_candidates`，供本类与 dispatch/distill.py
        共用（2026-09-18 深加工链路：候选口径全库只此一份）。"""
        return compute_distill_candidates(self.tree, self.probe, wiki, today)

    @staticmethod
    def _excluded_from_distill(stem: str, post: Any) -> bool:
        """提炼候选排除规则：日报/门面/摘要/清单容器/待确认/待办。"""
        if stem.startswith("今日摘要-") or DAILY_NOTE_RE.match(stem):
            return True
        if stem in DASHBOARD_STEMS:
            return True
        tags = post.get("tags") or []
        if "待确认" in tags or "待办" in tags:
            return True
        return str(post.get("source") or "") in DISTILL_EXCLUDED_SOURCES

    def _collect(
        self, today: str
    ) -> Tuple[List[str], List[str], List[str]]:
        """扫描全部笔记，分出三节各自的 wikilink 目标（按文件名排序）。"""
        yesterday = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        pending: List[str] = []
        todos: List[str] = []
        yesterday_new: List[str] = []
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                stem = note_path.stem
                if stem.startswith("今日摘要-"):  # 历史摘要不进摘要
                    continue
                try:
                    post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                tags = post.get("tags") or []
                if "待确认" in tags:
                    pending.append(stem)
                if "待办" in tags:
                    todos.append(stem)
                created = str(post.get("created") or "")
                if created[:10] == yesterday:
                    yesterday_new.append(stem)
        return sorted(pending), sorted(todos), sorted(yesterday_new)

    def _stale_pending(self, today: str) -> Tuple[List[str], List[str]]:
        """根目录滞留点名（2026-09-12 裁决：归档默认化的兜底提醒）。

        只看收件箱顶层 *.md（不进子目录——已归档的不算滞留），分两组，
        返回 (待确认行, 你的笔记行)，各自按滞留天数降序（久的在前）：

        - 待确认：带「待确认」且 created 满 STALE_PENDING_DAYS 天。引导
          点「✅ 确认并归档」收编，不值得留的等 decay 到期走 review→purge；
        - 你的笔记：无「待确认」的人写/已确认笔记（排除日记/门面/机器
          容器来源）满 STALE_HUMAN_DAYS 天——收件箱不该长住，归类或
          留着由人定（2026-09-12 入口收敛裁决⑤）。
        """
        today_date = datetime.strptime(today, "%Y-%m-%d")
        pending_cutoff = today_date - timedelta(days=STALE_PENDING_DAYS)
        human_cutoff = today_date - timedelta(days=STALE_HUMAN_DAYS)
        pending_rows: List[Tuple[int, str]] = []  # (-滞留天数, 行文本)
        human_rows: List[Tuple[int, str]] = []
        for note_path in sorted(Path(self.tree.notes_dir).glob("*.md")):
            if SYNC_CONFLICT_RE.search(note_path.name):
                continue
            try:
                post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            created = str(post.get("created") or "")[:10]
            if not created:
                continue
            try:
                created_date = datetime.strptime(created, "%Y-%m-%d")
            except ValueError:
                continue
            days = (today_date - created_date).days
            if "待确认" in (post.get("tags") or []):
                if created_date <= pending_cutoff:
                    pending_rows.append(
                        (-days, f"- [[{note_path.stem}]]（滞留 {days} 天）")
                    )
                continue
            stem = note_path.stem
            if DAILY_NOTE_RE.match(stem) or stem in DASHBOARD_STEMS:
                continue
            if str(post.get("source") or "") in STALE_HUMAN_EXCLUDED_SOURCES:
                continue
            if created_date <= human_cutoff:
                human_rows.append(
                    (-days, f"- [[{stem}]]（你的笔记 · 滞留 {days} 天）")
                )
        return (
            [line for _, line in sorted(pending_rows)],
            [line for _, line in sorted(human_rows)],
        )

    @staticmethod
    def _build(
        today: str,
        pending: List[str],
        todos: List[str],
        review: List[str],
        yesterday_new: List[str],
        undistilled: List[str],
        wiki_issues: List[Dict[str, Any]],
        health: List[str],
        health_stale: int,
        capture_line: Optional[str] = None,
        weekly_lines: Optional[List[str]] = None,
        failure_line: Optional[str] = None,
        decay_line: Optional[str] = None,
        judgment_line: Optional[str] = None,
        judgment_proposals: Optional[List[Dict[str, Any]]] = None,
        distill_draft_count: int = 0,
        stale_pending_lines: Optional[List[str]] = None,
        stale_human_lines: Optional[List[str]] = None,
        stale_wiki_lines: Optional[List[str]] = None,
    ) -> str:
        """组装摘要 Markdown（空节显示"无"）。

        undistilled 同时写进 frontmatter（控制台 Dataview 桥接——
        sidecar 里的推送观测数据 Dataview 看不见）。capture_line 是昨日
        捕获入口分布一行；weekly_lines 仅周日传入（本周捕获统计详细节）；
        stale_pending_lines / stale_human_lines 是根目录滞留点名（待确认
        组与你的笔记组，都无滞留时不出现该节）。failure_line 是分发熔断
        点名（无失败不出现）。
        """

        def _lines(items: List[str]) -> List[str]:
            return [f"- [[{stem}]]" for stem in items] or ["- 无"]

        if undistilled:
            fm = "---\nundistilled:\n"
            fm += "\n".join(f'- "[[{stem}]]"' for stem in undistilled)
            fm += "\n---\n\n"
        else:
            fm = "---\nundistilled: []\n---\n\n"

        sections = [f"# 今日摘要 {today}", ""]
        sections += [f"## ⏳ 待我确认（{len(pending)}）", "", *_lines(pending), ""]
        pending_stale = stale_pending_lines or []
        human_stale = stale_human_lines or []
        if pending_stale or human_stale:
            sections += [
                f"## ⏰ 滞留提醒（{len(pending_stale) + len(human_stale)}）",
                "",
                "> 待确认超 7 天：飞书确认卡点「✅ 确认并归档」一键收编；",
                "> 不值得留的不用管，decay 到期后走 review→purge。",
                "> 你的笔记在收件箱超 14 天：归个子目录，或留着——你定。",
                "",
            ]
            if pending_stale:
                sections += [
                    f"### 待确认（{len(pending_stale)}）",
                    "",
                    *pending_stale,
                    "",
                ]
            if human_stale:
                sections += [
                    f"### 你的笔记（{len(human_stale)}）",
                    "",
                    *human_stale,
                    "",
                ]
        sections += [f"## 🧠 提炼候选（{len(undistilled)}）", ""]
        if distill_draft_count:
            # 深加工草稿待审（2026-09-18）：机器已起草，人「提/弃」即可，
            # 不用自己动手写——安静一行，无草稿不出现
            sections += [
                f"> ✍️ 机器已备好 {distill_draft_count} 张摘录卡草稿："
                "回复「提 1」收进压缩层、「弃 1」跳过。",
                "",
            ]
        if undistilled:
            sections += [
                "> 不用自己动手写：机器每天从候选里挑 1 条起草，",
                "> 飞书回「提 N」收进压缩层、「弃 N」跳过。",
                "> 提炼后自动从本栏消失；不值得留的，留给 review→purge。",
                "",
            ]
        sections += [*_lines(undistilled)]
        if wiki_issues:
            sections += ["", f"wiki 体检（{len(wiki_issues)} 条待修）："]
            sections += [
                f"- [[{item['stem']}]]：{'、'.join(item['issues'])}"
                for item in wiki_issues
            ]
        if stale_wiki_lines:
            # OKF Freshness（2026-09-18 全量采纳）：到期卡点名，复查/顺延是人的动作
            sections += ["", f"⏰ wiki 到期复查（{len(stale_wiki_lines)}）：", *stale_wiki_lines]
        sections += [""]
        sections += [f"## ✅ 待办进行中（{len(todos)}）", "", *_lines(todos), ""]
        sections += [f"## 🔁 今日复习（{len(review)}）", ""]
        if review:
            sections += [
                "> 检索练习：看着标题先想「它讲了什么」，再点开核对；",
                "> 想不起来的，值得就提炼进压缩层，不值得就留给 review→purge。",
                "",
            ]
        sections += [*_lines(review), ""]
        proposals = judgment_proposals or []
        if proposals:
            # 判断候选安静小节（2026-09-16 回路三）：机器从你确认过的
            # 内容里摘的原子断言，只提名不批准；序号与飞书「批 N/略 N」
            # 指令同源同序
            sections += [f"## 🧭 判断候选（{len(proposals)}）", ""]
            sections += [
                "> 机器从你确认过的内容里摘的判断候选，只提名不批准；",
                "> 飞书回复「批 1」收第 1 条进登记处、「略 1」拒掉、"
                "「批 1 2」一次批多条；不理就一直候着。",
                "",
            ]
            sections += [
                f"{idx}. {item['statement']}"
                for idx, item in enumerate(proposals, 1)
            ]
            sections += [""]
        sections += [
            f"## 📥 昨日新入库（{len(yesterday_new)}）",
            "",
        ]
        if capture_line:
            sections += [f"> {capture_line}", ""]
        if failure_line:
            sections += [f"> {failure_line}", ""]
        if decay_line:
            sections += [f"> {decay_line}", ""]
        if judgment_line:
            sections += [f"> {judgment_line}", ""]
        sections += [
            *_lines(yesterday_new),
            "",
        ]
        if weekly_lines:
            sections += ["## 📊 本周捕获统计", ""]
            sections += weekly_lines
            sections += [""]
        header = (
            f"## 🩺 系统自检（{health_stale} 项异常）"
            if health_stale
            else "## 🩺 系统自检"
        )
        sections += [header, "", *health]
        return fm + "\n".join(sections) + "\n"


def compute_distill_candidates(
    tree: MemoryTree,
    probe: ResponseProbe,
    wiki: WikiManager,
    today: str,
    limit: int = MAX_DISTILL_CANDIDATES,
) -> List[str]:
    """提炼候选：从未进压缩层且值得动笔的笔记 stem（截断到上限）。

    三路汇合，去重后推送多的在前、其次被引用多的、最后最旧的在前：
    - 反复推送：ResponseProbe 累计推送 ≥MIN_PUSH_COUNT 次；
    - 被引用：别的笔记 [[wikilink]] 引用 ≥1 次（2026-09-12 裁决②：
      沉淀从"自己的笔记长出来"——被引用的已是枢纽，与每日衰减同源
      的反链统计，DecayManager.backlink_counts）；
    - 沉一沉：已确认且 created 满 DISTILL_MIN_AGE_DAYS 天。
    文件已消失（purge 也是加工）自然不计；日报/控制台/摘要/
    划重点清单/待确认/待办不候选。候选口径全库只此一份：晨报
    （DigestDispatcher._distill_candidates）与深加工起草器
    （dispatch/distill.py）都从这里取（2026-09-18 提升为模块级）。

    Args:
        tree: MemoryTree。
        probe: ResponseProbe（推送计数来源）。
        wiki: WikiManager（distilled_stems 来源）。
        today: YYYY-MM-DD。
        limit: 返回条数上限。

    Returns:
        List[str]: 候选笔记 stem 列表（优先级序）。
    """
    counts = {
        str(slot.get("filename") or ""): int(slot.get("count") or 0)
        for slot in probe.push_counts().values()
    }
    backlink_by_stem = {
        path.stem: count
        for path, count in DecayManager(tree).backlink_counts().items()
        if count >= 1
    }
    distilled = wiki.distilled_stems()
    cutoff = (
        datetime.strptime(today, "%Y-%m-%d") - timedelta(days=DISTILL_MIN_AGE_DAYS)
    ).strftime("%Y-%m-%d")
    pushed: List[Tuple[int, str]] = []  # (-count, stem)
    linked: List[Tuple[int, str]] = []  # (-引用数, stem)
    settled: List[Tuple[str, str]] = []  # (created, stem)
    # 全库扫描（含已归档子目录）：归档后的笔记被引用多了照样该提炼
    all_paths = [path for layer in LAYERS for path in tree.list_notes(layer)]
    for note_path in sorted(all_paths):
        if SYNC_CONFLICT_RE.search(note_path.name):
            continue  # Syncthing 冲突副本不是笔记
        stem = note_path.stem
        if stem in distilled:
            continue
        try:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if DigestDispatcher._excluded_from_distill(stem, post):
            continue
        push_count = counts.get(note_path.name, 0)
        if push_count >= MIN_PUSH_COUNT:
            pushed.append((-push_count, stem))
            continue
        ref_count = backlink_by_stem.get(stem, 0)
        if ref_count >= 1:
            linked.append((-ref_count, stem))
            continue
        created = str(post.get("created") or "")[:10]
        if created and created <= cutoff:
            settled.append((created, stem))
    picked = [stem for _, stem in sorted(pushed)]
    picked += [stem for _, stem in sorted(linked)]
    picked += [stem for _, stem in sorted(settled)]
    return picked[:limit]
