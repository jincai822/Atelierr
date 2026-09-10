"""晨间摘要：每天定时创建一条"今日摘要"笔记（只新建，不改写）。

摘要写入 ``memory/系统/`` 子目录（NOTE_EXCLUDED_DIRS 成员）：
摘要是 Agent 的输出而非记忆——留在扫描域内会污染搜索排名、并用
摘要链接给 references 引用信号"刷票"（自我指涉回路）。Obsidian
里照常可见可读（Dataview 全库查询不受影响），仅记忆机制不扫描。

内容五节（wikilink 列表，点开即达）：
- 待我确认：当前带"待确认"标签的笔记（摘除标签后次日自然消失）；
- 提炼候选：从未提炼进 wiki/ 且值得动笔的笔记，两路汇合——
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
  确认无价值的留给 review→purge，值得留存的提炼进 wiki/）；
- 昨日新入库：frontmatter created 日期为昨天的笔记；
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
from scripts.dispatch.sysdir import SYSTEM_DIRNAME, write_machine_note
from scripts.memory.core import LAYERS, SYNC_CONFLICT_RE, MemoryTree
from scripts.memory.resurface import ResurfaceManager
from scripts.memory.watcher import MemoryWatcher
from scripts.wiki.manager import WikiManager

MIN_PUSH_COUNT = 2  # 推送达到此次数仍未提炼，进"提炼候选"节
DISTILL_MIN_AGE_DAYS = 3  # 已确认笔记创建满此天数即可提炼（沉一沉再动笔）
MAX_DISTILL_CANDIDATES = 5  # 候选节最多列几条（防长列表制造压力）

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
        review = self.resurface.candidates()
        review_stems = [Path(item["filename"]).stem for item in review]
        wiki = WikiManager(self.tree)
        undistilled = self._distill_candidates(wiki, today)
        wiki_issues = wiki.validate()
        health, health_stale = _health_lines(Path(self.tree.state_dir))
        markdown = self._build(
            today, pending, todos, review_stems, yesterday_new,
            undistilled, wiki_issues, health, health_stale,
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
            },
            "review": review,
            "markdown": markdown,
        }

    def _distill_candidates(self, wiki: WikiManager, today: str) -> List[str]:
        """提炼候选：从未进 wiki 且值得动笔的笔记 stem（截断到上限）。

        两路汇合，去重后推送多的在前、其次最旧的在前：
        - 反复推送：ResponseProbe 累计推送 ≥MIN_PUSH_COUNT 次；
        - 沉一沉：已确认且 created 满 DISTILL_MIN_AGE_DAYS 天。
        文件已消失（purge 也是加工）自然不计；日报/控制台/摘要/
        划重点清单/待确认/待办不候选（见 _excluded_from_distill）。
        """
        counts = {
            str(slot.get("filename") or ""): int(slot.get("count") or 0)
            for slot in self.probe.push_counts().values()
        }
        distilled = wiki.distilled_stems()
        cutoff = (
            datetime.strptime(today, "%Y-%m-%d")
            - timedelta(days=DISTILL_MIN_AGE_DAYS)
        ).strftime("%Y-%m-%d")
        pushed: List[Tuple[int, str]] = []  # (-count, stem)
        settled: List[Tuple[str, str]] = []  # (created, stem)
        for note_path in sorted(Path(self.tree.notes_dir).glob("*.md")):
            if SYNC_CONFLICT_RE.search(note_path.name):
                continue  # Syncthing 冲突副本不是笔记
            stem = note_path.stem
            if stem in distilled:
                continue
            try:
                post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if self._excluded_from_distill(stem, post):
                continue
            push_count = counts.get(note_path.name, 0)
            if push_count >= MIN_PUSH_COUNT:
                pushed.append((-push_count, stem))
                continue
            created = str(post.get("created") or "")[:10]
            if created and created <= cutoff:
                settled.append((created, stem))
        picked = [stem for _, stem in sorted(pushed)]
        picked += [stem for _, stem in sorted(settled)]
        return picked[:MAX_DISTILL_CANDIDATES]

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
    ) -> str:
        """组装摘要 Markdown（空节显示"无"）。

        undistilled 同时写进 frontmatter（控制台 Dataview 桥接——
        sidecar 里的推送观测数据 Dataview 看不见）。
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
        sections += [f"## 🧠 提炼候选（{len(undistilled)}）", ""]
        if undistilled:
            sections += [
                "> 每周日周回顾前，从这儿挑 1 条提炼进 wiki：",
                "> 点开笔记 → QuickAdd「提炼为 Wiki」，五分钟够了。",
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
        sections += [""]
        sections += [f"## ✅ 待办进行中（{len(todos)}）", "", *_lines(todos), ""]
        sections += [f"## 🔁 今日复习（{len(review)}）", ""]
        if review:
            sections += [
                "> 检索练习：看着标题先想「它讲了什么」，再点开核对；",
                "> 想不起来的，值得就提炼进 wiki/，不值得就留给 review→purge。",
                "",
            ]
        sections += [*_lines(review), ""]
        sections += [
            f"## 📥 昨日新入库（{len(yesterday_new)}）",
            "",
            *_lines(yesterday_new),
            "",
        ]
        header = (
            f"## 🩺 系统自检（{health_stale} 项异常）"
            if health_stale
            else "## 🩺 系统自检"
        )
        sections += [header, "", *health]
        return fm + "\n".join(sections) + "\n"
