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

#: 盲测小节（2026-09-19 脑科学建议①）：周回顾从本周新入库笔记抽 N 条，
#: 先自由回忆再给原文对照——自由回忆是最强的固化手段（回忆+生成+即时
#: 反馈三效合一），治「看着眼熟就点确认」的再认惯性（数字失忆症防线）
BLIND_RECALL_DAYS = 7
BLIND_RECALL_LIMIT = 3

#: 费曼讲稿（2026-09-19 脑科学建议②）：每月脉冲从当月 wiki 新卡挑 N 张
#: 合成讲稿骨架——能讲明白才是真懂（费曼技巧；目标二的验证标准原话
#: 就是「能向人讲清」）。LLM 起草，模板兜底，绝不影响脉冲本身
FEYNMAN_DAYS = 30
FEYNMAN_LIMIT = 3

#: 盲测候选排除：机器产物/知识层不算"本周新收的笔记"
_BLIND_EXCLUDED_DIRS = frozenset({"wiki", "distilled", "系统", "templates"})
_BLIND_EXCLUDED_SOURCES = frozenset({"digest", "highlights", "system", "todo"})
_BLIND_EXCLUDED_STEMS = frozenset({"主页", "控制台"})

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
    # 盲测小节（建议①）：本周新收的笔记先自由回忆，答完发原文对照
    for index, item in enumerate(blind_recall_items(tree), start=1):
        title = item["title"]
        if len(title) > 24:
            title = title[:24] + "…"
        questions.append(
            f"盲测{index}：本周你收了「{title}」——不看笔记，一句话说出它讲了什么？"
        )
    return questions[:_MAX_QUESTIONS]


def blind_recall_items(
    tree, days: int = BLIND_RECALL_DAYS, limit: int = BLIND_RECALL_LIMIT
) -> List[Dict[str, str]]:
    """本周新入库笔记（周回顾盲测候选）：created 在 days 天内、非日报/
    非机器容器/非待办待确认/非知识层，按新到旧取前 limit 条。

    Args:
        tree: MemoryTree。
        days: 回看窗口（天）。
        limit: 条数上限。

    Returns:
        List[Dict]: [{title, rel, created}]，created 降序。
    """
    from scripts.memory.core import DAILY_NOTE_RE

    cutoff = datetime.now().astimezone() - timedelta(days=days)
    items: List[Dict[str, str]] = []
    for path in sorted(tree.notes_dir.rglob("*.md")):
        rel = path.relative_to(tree.notes_dir)
        if any(part in _BLIND_EXCLUDED_DIRS for part in rel.parts[:-1]):
            continue
        stem = path.stem
        if stem in _BLIND_EXCLUDED_STEMS or stem.startswith("todo-"):
            continue
        if DAILY_NOTE_RE.match(path.name):
            continue
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(post.get("source") or "") in _BLIND_EXCLUDED_SOURCES:
            continue
        tags = {str(tag) for tag in (post.get("tags") or [])}
        if tags & {"待办", "待确认"}:
            continue
        try:
            created = datetime.fromisoformat(str(post.get("created") or ""))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.astimezone()
        if created < cutoff:
            continue
        items.append(
            {
                "title": str(post.get("title") or stem),
                "rel": rel.as_posix(),
                "created": created.isoformat(),
            }
        )
    items.sort(key=lambda item: item["created"], reverse=True)
    return items[:limit]


def blind_comparison(
    tree, closed: Dict[str, Any], excerpt_chars: int = 200
) -> Optional[str]:
    """盲测对照文本：读已关闭会话 blind 负载里的笔记原文开头。

    在答案提交后发送（先回忆后对照——顺序是效果本身，不可提前）。

    Args:
        tree: MemoryTree。
        closed: 已关闭会话数据（含 blind 负载时才有输出）。
        excerpt_chars: 每条原文截取长度。

    Returns:
        Optional[str]: 逐条「标题：原文开头…」；无 blind 负载为 None。
    """
    blind = closed.get("blind") if isinstance(closed, dict) else None
    if not blind:
        return None
    parts: List[str] = []
    for item in list(blind)[:BLIND_RECALL_LIMIT]:
        rel = str((item or {}).get("rel") or "")
        title = str((item or {}).get("title") or rel or "（无题）")
        try:
            post = frontmatter.loads(
                (tree.notes_dir / rel).read_text(encoding="utf-8")
            )
            body = " ".join(str(post.content).split())
        except (OSError, ValueError):
            body = ""
        parts.append(f"• 「{title}」：{body[:excerpt_chars] or '（原文读取失败）'}")
    return "\n".join(parts) if parts else None


def feynman_candidates(
    tree, days: int = FEYNMAN_DAYS, limit: int = FEYNMAN_LIMIT
) -> List[Dict[str, str]]:
    """当月 wiki 新卡（费曼讲稿候选）：created 在 days 天内的 concept/
    摘录卡（cognition/ 与 reflections/ 排除——判断与反思不是讲授素材），
    按新到旧取前 limit 条。

    Returns:
        List[Dict]: [{title, rel, body}]，body 为正文（截 800 字）。
    """
    wiki_dir = Path(tree.notes_dir) / "wiki"
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    items: List[Dict[str, str]] = []
    if not wiki_dir.is_dir():
        return items
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(tree.notes_dir)
        if any(part in ("cognition", "reflections") for part in rel.parts[:-1]):
            continue
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            created = datetime.fromisoformat(str(post.get("created") or ""))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.astimezone()
        if created < cutoff:
            continue
        items.append(
            {
                "title": str(post.get("title") or path.stem),
                "rel": rel.as_posix(),
                "created": created.isoformat(),
                "body": " ".join(str(post.content).split())[:800],
            }
        )
    items.sort(key=lambda item: item["created"], reverse=True)
    return items[:limit]


def _feynman_template(candidates: List[Dict[str, str]]) -> str:
    """纯模板骨架（LLM 不可用时的兜底；填空本就是用户的事）。"""
    parts = [
        "🎤 本月费曼讲稿（能讲明白才是真懂——填不填零压力）",
        "每张卡三空：",
    ]
    for item in candidates:
        parts.append(
            f"• 「{item['title']}」\n"
            "  ① 核心概念：____（一句话，说给完全不懂的人）\n"
            "  ② 类比：它像生活中的什么？\n"
            "  ③ 应用：下周哪个场景用一次？"
        )
    return "\n".join(parts)


def _feynman_llm(candidates: List[Dict[str, str]]) -> Optional[str]:
    """LLM 起草讲稿骨架（DeepSeek 一次调用）；任何失败返回 None（模板兜底）。"""
    import os

    from scripts.dispatch.judgments import _load_llm_config

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    cfg = _load_llm_config()
    base_url = str(cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    model = str(cfg.get("model") or "deepseek-v4-flash")
    cards_text = "\n\n".join(
        f"卡{i}「{item['title']}」：{item['body'][:400]}"
        for i, item in enumerate(candidates, 1)
    )
    prompt = (
        "你是费曼技巧教练。给下面每张知识卡写一份讲稿骨架，格式严格为：\n"
        "• 「标题」\n  ① 核心概念：一句通俗话\n  ② 类比：一个生活类比\n"
        "  ③ 应用：一个本周可试的具体场景\n"
        "只输出骨架本身，不要任何前后缀。\n\n" + cards_text
    )
    try:
        import httpx

        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 900,
            },
            timeout=30,
        )
        response.raise_for_status()
        text = str(
            response.json()["choices"][0]["message"]["content"] or ""
        ).strip()
    except Exception:  # noqa: BLE001 - LLM 失败退回模板
        return None
    return text or None


def feynman_brief(
    tree, days: int = FEYNMAN_DAYS, limit: int = FEYNMAN_LIMIT
) -> Optional[str]:
    """本月费曼讲稿（月度脉冲随附）：LLM 起草，模板兜底；当月无新卡返回 None。

    Args:
        tree: MemoryTree。
        days: 回看窗口（天）。
        limit: 卡片上限。

    Returns:
        Optional[str]: 讲稿文本；无候选为 None。
    """
    candidates = feynman_candidates(tree, days=days, limit=limit)
    if not candidates:
        return None
    return _feynman_llm(candidates) or _feynman_template(candidates)


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
    if kind == KIND_WEEKLY:
        # 盲测负载随会话存档（答案提交后发原文对照，见 blind_comparison）
        blind = blind_recall_items(tree)
        if blind:
            store.set_extra(
                "blind", [{"title": b["title"], "rel": b["rel"]} for b in blind]
            )
    if send:
        title = {
            KIND_WEEKLY: "🌿 周回顾",
            KIND_MONTHLY: "🌙 月度回顾（轻）",
            KIND_DAILY: "🌛 今日四问",
        }[kind]
        intro = build_intro(tree, kind)
        # 默认路径保持原调用形（既有测试以 lambda card 单参 mock 本函数）；
        # 仅交互旁路（用户手动「复盘」）才显式传 respect_quiet=False
        card = prompt_form_card(title, intro, questions)
        if respect_quiet:
            send_feishu_card(card)
        else:
            send_feishu_card(card, respect_quiet=False)
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
