"""回顾仪式（方案 A 改 1，2026-09-13 用户批准）：周日周回顾 + 月末月回顾轻脉冲；
每日三问（2026-09-18 用户批准：推送式复盘——系统到点来问，零命令启动）。

问题由当期数据生成（捕获统计/滞留待确认/待删清单——防固定四问的
仪式疲劳）；飞书表单卡推送（schema 2.0，2026-09-13 真机验证过的
技术）；答案**机械落盘** memory/wiki/reflections/（paths.toml 注册的
回顾目录；零自动 LLM——综合成文发生在用户下次会话，Atelier 车间）。

触发：atelierr-review.timer（周日 09:13）、atelierr-review-monthly.timer
（每月 1 日 09:21 回顾上月）、atelierr-review-daily.timer（每天 21:30
今日三问）。会话关闭（表单提交或回「完成」）时
FeishuBridge 自动把答案落盘（kind 以 review- 开头）。

每日三问护栏（2026-09-18 批准，防推送疲劳）：
- 连续 3 天没答自动暂停（状态记在 <state_dir>/review_daily.json）；
- 飞书回「复盘」随时手动恢复并立刻发当日三问；
- 前一天没答的会话不覆盖：收尸时答案照落盘、无答才记一天未答；
- 周/月回顾会话在跑时，每日三问让位（不打扰、不计未答）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.feishu_cards import prompt_form_card
from scripts.dispatch.feishu_io import send_feishu_card
from scripts.dispatch.prompt import PromptStore
from scripts.dispatch.stats import capture_stats
from scripts.utils.state_store import read_json, write_json
from scripts.wiki.curation import DISTILLED_DIRNAME

#: 会话类型前缀（与 Codex $weekly 的会话区分；桥按此前缀识别落盘）
KIND_WEEKLY = "review-weekly"
KIND_MONTHLY = "review-monthly"
#: 每日三问（推送式复盘，2026-09-18 用户批准）
KIND_DAILY = "review-daily"

#: 滞留判定：待确认卡超过 7 天未处理
_STALE_DAYS = 7

#: 表单问题数上限（卡片长度护栏；与 PROMPT_FORM_MAX_QUESTIONS 同纪律）
_MAX_QUESTIONS = 6

#: 连续未答天数上限：达到即自动暂停推送（防推送疲劳护栏）
_DAILY_MAX_UNANSWERED = 3

#: 每日三问状态文件（<state_dir> 下；只记暂停/连续未答，不碰笔记）
_DAILY_STATE_FILENAME = "review_daily.json"


def _load_daily_state(tree) -> Dict[str, Any]:
    """读每日三问状态；文件不存在/损坏按全新（未暂停、零未答）处理。"""
    data = read_json(Path(tree.state_dir) / _DAILY_STATE_FILENAME, None)
    return data if isinstance(data, dict) else {}


def _save_daily_state(tree, state: Dict[str, Any]) -> None:
    write_json(Path(tree.state_dir) / _DAILY_STATE_FILENAME, state, indent=2)


def _bump_daily_unanswered(tree) -> None:
    """记一天未答；连续达上限即置暂停（不再推送，直到回「复盘」）。"""
    state = _load_daily_state(tree)
    streak = int(state.get("unanswered_streak") or 0) + 1
    _save_daily_state(
        tree,
        {
            "unanswered_streak": streak,
            "paused": state.get("paused") or streak >= _DAILY_MAX_UNANSWERED,
        },
    )


def _reset_daily_streak(tree) -> None:
    """有任何回顾答案落盘（周/月/日都算参与）就清零连续未答、解除暂停。"""
    state = _load_daily_state(tree)
    if state.get("unanswered_streak") or state.get("paused"):
        _save_daily_state(tree, {"unanswered_streak": 0, "paused": False})


def unpause_daily(tree) -> None:
    """手动恢复（飞书回「复盘」）：清暂停、清零连续未答。"""
    _save_daily_state(tree, {"unanswered_streak": 0, "paused": False})


def _stale_pending_count(tree) -> int:
    """滞留待确认数：inbox/ 与 memory/ 里待确认且 created 超 7 天的笔记。"""
    from datetime import timedelta

    cutoff = datetime.now().astimezone() - timedelta(days=_STALE_DAYS)
    count = 0
    for path in tree.iter_all_note_files():
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏跳过
            continue
        tags = [str(tag) for tag in (post.get("tags") or [])]
        if "待确认" not in tags:
            continue
        created = str(post.get("created") or "")
        try:
            created_dt = datetime.fromisoformat(created)
        except ValueError:
            continue
        if created_dt < cutoff:
            count += 1
    return count


def _new_excerpt_cards(tree, days: int) -> Tuple[int, List[str]]:
    """当期新增压缩层摘录卡（按 frontmatter created 判），返回 (总数, 前5标题)。

    2026-09-14 KM 评审 P1①：摘录卡勾中即沉底（不进任何回顾回路）是
    收藏谬误温床——回顾仪式点名提醒"提炼成自己话的概念卡"。
    """
    distilled_dir = Path(tree.notes_dir) / DISTILLED_DIRNAME
    if not distilled_dir.is_dir():
        return 0, []
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    seen: List[Tuple[str, str]] = []
    for path in distilled_dir.glob("摘录-*.md"):
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(post.get("created") or ""))
        except Exception:  # noqa: BLE001 - 损坏/无日期跳过
            continue
        if created >= cutoff:
            seen.append((created.isoformat(), str(post.get("title") or path.stem)))
    seen.sort(reverse=True)
    return len(seen), [title for _, title in seen[:5]]


def build_intro(tree, kind: str) -> str:
    """卡片正文的数据摘要（Markdown）：数字放正文，问题才能保持短句
    （2026-09-13 用户反馈：数据塞问题里当输入框标签，手机上没法看——
    人机交互红线）。
    """
    if kind == KIND_DAILY:
        # 每日三问正文保持极简（每晚都见的卡，字越少越好）
        stats = capture_stats(tree, days=1)
        lines = [f"📊 今天捕获 {stats['total']} 条"]
        lines.append("💡 想到什么判断？回复「判断：xxx」直收进登记处（不计入回答）")
        lines += [
            "",
            "不想答的留空，点提交即可。连续 3 天没答会自动暂停，"
            "回「复盘」随时重新开始。",
        ]
        return "\n".join(lines)
    days = 30 if kind == KIND_MONTHLY else 7
    stats = capture_stats(tree, days=days)
    rate = (
        f"{stats['confirm_rate'] * 100:.0f}%"
        if stats["confirm_rate"] is not None
        else "—"
    )
    span = "本月" if kind == KIND_MONTHLY else "本周"
    lines = [
        f"📊 {span}数据：捕获 {stats['total']} 条（确认率 {rate}）"
        f"｜沉淀 wiki {stats['wiki_new']} 张｜遗忘 {stats['purged']} 条",
    ]
    stale = _stale_pending_count(tree)
    if stale:
        lines.append(f"🗂 有 {stale} 张旧卡还没确认——方便时扫一眼就好")
    excerpt_total, excerpt_titles = _new_excerpt_cards(tree, days)
    if excerpt_total:
        # KM 评审 P1①：点名本期新勾的摘录卡，提醒提炼（防收藏谬误）
        lines.append(
            f"📚 {span}新勾摘录卡 {excerpt_total} 张——记得提炼成自己话的概念卡："
        )
        lines += [f"　· {title}" for title in excerpt_titles]
    pending_delete = len(tree.list_pending_delete())
    if pending_delete:
        lines.append(f"🗑 待删清单等你过目：{pending_delete} 条")
    # 判断登记处入口提示（2026-09-16 回路三启用）：不进表单不占问题位，
    # 回顾时刻正是产生判断的时刻，顺手一句即直收
    lines.append("💡 想到什么判断？回复「判断：xxx」直收进登记处（不计入回答）")
    lines += ["", "不想答的留空，点提交即可。"]
    return "\n".join(lines)


def build_questions(tree, kind: str) -> List[str]:
    """由当期数据生成回顾问题（每周/每月内容不同，防仪式疲劳）。

    Args:
        tree: MemoryTree 实例。
        kind: KIND_WEEKLY / KIND_MONTHLY。

    Returns:
        List[str]: 问题列表（至多 _MAX_QUESTIONS 条）。
    """
    if kind == KIND_DAILY:
        # 固定四问（2026-09-18 脑科学评审处方 P0）：睡眠仪表（认知表现的
        # 第一预测因子）+ 小胜记录（胜任感供给，对抗内耗）+ 注意力账簿
        # （自述注意力偏移）+ 内耗留痕（情绪标签化）。
        return [
            "今天睡了几小时？（大概就行）",
            "今天做成的一件小事？（再小也算）",
            "今天注意力最好的一段时间在干什么？",
            "今天有内耗的时刻吗？因为什么？",
        ]
    if kind == KIND_MONTHLY:
        return [
            "这个节奏健康吗？（数据见上方摘要）",
            "本月最有价值的一条收获是什么？",
            "下个月想多收点什么、少收点什么？",
        ]
    # 周回顾：问题保持短句（数据在卡片正文摘要里，2026-09-13 交互修正——
    # 长句当输入框标签在手机上没法看）
    questions = ["本周最值得留的是哪条？为什么？"]
    if _stale_pending_count(tree):
        questions.append("没确认的旧卡：哪些值得留、哪些可以扔？")
    if tree.list_pending_delete():
        questions.append("待删清单有没有误判？")
    questions += [
        "本周有什么反复出现的主题或念头？",
        "下周想重点关注什么？",
    ]
    return questions[:_MAX_QUESTIONS]


def open_ritual(tree, kind: str, send: bool = True, respect_quiet: bool = True) -> Dict[str, Any]:
    """开启回顾会话并推表单卡。

    周/月回顾：已有会话在跑时跳过（不覆盖）。
    每日三问：前一天没答的会话先收尸（有答落盘清零、无答记一天未答）；
    当天已开过幂等跳过；周/月回顾在跑时让位；连续 3 天未答自动暂停。

    Args:
        tree: MemoryTree 实例。
        kind: KIND_WEEKLY / KIND_MONTHLY / KIND_DAILY。
        send: 是否推飞书表单卡（测试关）。

    Returns:
        Dict[str, Any]: {"opened", "questions"}；已有会话时 opened=False；
        每日三问被自动暂停拦住时带 paused=True。
    """
    store = PromptStore(tree.state_dir)
    if store.is_open():
        if kind != KIND_DAILY:
            return {"opened": False, "questions": []}
        existing = store.load() or {}
        if str(existing.get("kind") or "") != KIND_DAILY:
            return {"opened": False, "questions": []}  # 周/月回顾在跑，让位
        # 幂等/收尸都按本地日期判（2026-09-19 修：asked_at 是 UTC 存储，
        # 直接 [:10] 会在每天 00:00-08:00 本地时段把当天误判成昨天）
        asked_raw = str(existing.get("asked_at") or "")
        try:
            asked = datetime.fromisoformat(asked_raw).astimezone().strftime("%Y-%m-%d")
        except ValueError:
            asked = asked_raw[:10]
        if asked == datetime.now().strftime("%Y-%m-%d"):
            return {"opened": False, "questions": []}  # 当天幂等
        closed = store.close()  # 前一天的会话收尸
        if closed and [
            a
            for a in (closed.get("answers") or [])
            if str(a.get("text") or "").strip()
        ]:
            write_answers(tree, closed)  # 有答：落盘（内部清零未答计数）
        else:
            _bump_daily_unanswered(tree)  # 无答：记一天未答
    if kind == KIND_DAILY and _load_daily_state(tree).get("paused"):
        return {"opened": False, "questions": [], "paused": True}
    questions = build_questions(tree, kind)
    store.open(kind, questions)
    if send:
        title = {
            KIND_WEEKLY: "🌿 周回顾",
            KIND_MONTHLY: "🌙 月度回顾（轻）",
            KIND_DAILY: "🌛 今日四问",
        }[kind]
        intro = build_intro(tree, kind)
        send_feishu_card(
            prompt_form_card(title, intro, questions), respect_quiet=respect_quiet
        )
    return {"opened": True, "questions": questions}


def write_answers(tree, data: Dict[str, Any]) -> Optional[Path]:
    """把已关闭会话的答案机械落盘到 reflections/。

    当天文件已存在则**追加**新答案（同一话题分次作答不丢——
    2026-09-13 实测：验证卡先收了一条真答案，正式卡的补充回答
    必须能续上），不写重复答案（幂等：完全相同的回答文本不重复落）。

    Args:
        tree: MemoryTree 实例。
        data: PromptStore.close() 返回的会话状态（含 questions/answers）。

    Returns:
        Optional[Path]: 写入的文件路径；无答案/无新答案返回 None。
    """
    answers = [a for a in (data.get("answers") or []) if str(a.get("text") or "").strip()]
    if not answers:
        return None
    kind = str(data.get("kind") or KIND_WEEKLY)
    # 落盘日期按会话提问时的本地日期（同 open_ritual 的 UTC→本地修复）
    asked_raw = str(data.get("asked_at") or "")
    try:
        asked = datetime.fromisoformat(asked_raw).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        asked = asked_raw[:10]
    today = asked or datetime.now().strftime("%Y-%m-%d")
    refl_dir = Path(tree.notes_dir) / "wiki" / "reflections"
    refl_dir.mkdir(parents=True, exist_ok=True)
    # 文件名后缀：daily 用 reflection——与 Atelier /weekly 的缺日检测
    # glob（`<date>-reflection*.md`）对齐，每日三问落盘即被车间认成日报
    suffix = {
        KIND_WEEKLY: "weekly",
        KIND_MONTHLY: "monthly",
        KIND_DAILY: "reflection",
    }.get(kind, kind.replace("review-", ""))
    label = {
        KIND_WEEKLY: "周回顾",
        KIND_MONTHLY: "月回顾",
        KIND_DAILY: "每日四问",
    }.get(kind, "月回顾")
    target = refl_dir / f"{today}-{suffix}.md"
    questions = [str(q) for q in (data.get("questions") or [])]
    new_blocks: List[str] = []
    for index, answer in enumerate(answers):
        question = questions[index] if index < len(questions) else ""
        block = ""
        if question:
            block += f"## 问：{question}\n\n"
        block += str(answer["text"]).strip() + "\n"
        new_blocks.append(block)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        fresh = [block for block in new_blocks if block.strip() not in existing]
        if not fresh:
            return None
        with target.open("a", encoding="utf-8") as fh:
            fh.write("\n---\n\n" + "\n".join(fresh))
        _reset_daily_streak(tree)  # 有答案落盘 = 有参与
        return target
    lines = [
        "---",
        f"created: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "source: reflection",
        f"tags: [回顾, {label}]",
        f"title: '{today} {label}（原始回答）'",
        "---",
        "",
        f"# {today} {label}（原始回答）",
        "",
        "> 机械落盘：答案原样记录（零自动 LLM）；综合成文在你下次会话（车间）。",
        "",
    ]
    for index, answer in enumerate(answers):
        question = questions[index] if index < len(questions) else ""
        if question:
            lines += [f"## 问：{question}", ""]
        lines += [str(answer["text"]).strip(), ""]
    target.write_text("\n".join(lines), encoding="utf-8")
    _reset_daily_streak(tree)  # 有答案落盘 = 有参与
    return target


def collect_ritual(tree, send: bool = True) -> Dict[str, Any]:
    """关闭会话并把答案机械落盘；无会话/无答案静默。

    Returns:
        Dict[str, Any]: {"collected", "path"}。
    """
    store = PromptStore(tree.state_dir)
    data = store.load()
    if not data or data.get("status") != "open":
        return {"collected": False, "path": None}
    data = store.close()
    path = write_answers(tree, data) if data else None
    return {"collected": path is not None, "path": path}
