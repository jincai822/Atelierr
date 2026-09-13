"""回顾仪式（方案 A 改 1，2026-09-13 用户批准）：周日周回顾 + 月末月回顾轻脉冲。

问题由当期数据生成（捕获统计/滞留待确认/待删清单——防固定四问的
仪式疲劳）；飞书表单卡推送（schema 2.0，2026-09-13 真机验证过的
技术）；答案**机械落盘** memory/wiki/reflections/（paths.toml 注册的
回顾目录；零自动 LLM——综合成文发生在用户下次会话，Atelier 车间）。

触发：atelierr-review.timer（周日 09:13）、atelierr-review-monthly.timer
（每月 1 日 09:21 回顾上月）。会话关闭（表单提交或回「完成」）时
FeishuBridge 自动把答案落盘（kind 以 review- 开头）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from scripts.dispatch.feishu_cards import prompt_form_card
from scripts.dispatch.feishu_io import send_feishu_card
from scripts.dispatch.prompt import PromptStore
from scripts.dispatch.stats import capture_stats

#: 会话类型前缀（与 Codex $weekly 的会话区分；桥按此前缀识别落盘）
KIND_WEEKLY = "review-weekly"
KIND_MONTHLY = "review-monthly"

#: 滞留判定：待确认卡超过 7 天未处理
_STALE_DAYS = 7

#: 表单问题数上限（卡片长度护栏；与 PROMPT_FORM_MAX_QUESTIONS 同纪律）
_MAX_QUESTIONS = 6


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


def build_questions(tree, kind: str) -> List[str]:
    """由当期数据生成回顾问题（每周/每月内容不同，防仪式疲劳）。

    Args:
        tree: MemoryTree 实例。
        kind: KIND_WEEKLY / KIND_MONTHLY。

    Returns:
        List[str]: 问题列表（至多 _MAX_QUESTIONS 条）。
    """
    if kind == KIND_MONTHLY:
        stats = capture_stats(tree, days=30)
        rate = (
            f"{stats['confirm_rate'] * 100:.0f}%"
            if stats["confirm_rate"] is not None
            else "—"
        )
        return [
            f"本月捕获 {stats['total']} 条、确认率 {rate}、"
            f"沉淀进 wiki {stats['wiki_new']} 张、遗忘 {stats['purged']} 条。"
            "这个节奏健康吗？",
            "本月最有价值的一条收获是什么？",
            "下个月想多收点什么、少收点什么？",
        ]
    stats = capture_stats(tree, days=7)
    stale = _stale_pending_count(tree)
    pending_delete = len(tree.list_pending_delete())
    rate = (
        f"{stats['confirm_rate'] * 100:.0f}%"
        if stats["confirm_rate"] is not None
        else "—"
    )
    questions = [
        f"本周捕获 {stats['total']} 条（确认率 {rate}）。"
        "哪一条最值得留？为什么？",
    ]
    if stale:
        questions.append(
            f"有 {stale} 条待确认滞留超 7 天：留还是扔？"
            "（值得留的去清单卡确认归档，不值得的留给 decay）"
        )
    if pending_delete:
        questions.append(
            f"待删清单有 {pending_delete} 条在等你过目，有没有误判？"
            "（回「待删」两个字可让它们在清单里再躺一周）"
        )
    questions += [
        "本周有什么反复出现的主题或念头？",
        "下周想重点关注什么？",
    ]
    return questions[:_MAX_QUESTIONS]


def open_ritual(tree, kind: str, send: bool = True) -> Dict[str, Any]:
    """开启回顾会话并推表单卡；已有会话在跑时跳过（不覆盖）。

    Args:
        tree: MemoryTree 实例。
        kind: KIND_WEEKLY / KIND_MONTHLY。
        send: 是否推飞书表单卡（测试关）。

    Returns:
        Dict[str, Any]: {"opened", "questions"}；已有会话时 opened=False。
    """
    store = PromptStore(tree.state_dir)
    if store.is_open():
        return {"opened": False, "questions": []}
    questions = build_questions(tree, kind)
    store.open(kind, questions)
    if send:
        title = "🌿 周回顾" if kind == KIND_WEEKLY else "🌙 月度回顾（轻）"
        intro = "问题由你这周/月的数据生成。不想答的可留空，点提交即可。"
        send_feishu_card(prompt_form_card(title, intro, questions))
    return {"opened": True, "questions": questions}


def write_answers(tree, data: Dict[str, Any]) -> Optional[Path]:
    """把已关闭会话的答案机械落盘到 reflections/（同名跳过，幂等）。

    Args:
        tree: MemoryTree 实例。
        data: PromptStore.close() 返回的会话状态（含 questions/answers）。

    Returns:
        Optional[Path]: 写入的文件路径；无答案/已写过返回 None。
    """
    answers = [a for a in (data.get("answers") or []) if str(a.get("text") or "").strip()]
    if not answers:
        return None
    kind = str(data.get("kind") or KIND_WEEKLY)
    asked = str(data.get("asked_at") or "")[:10]
    today = asked or datetime.now().strftime("%Y-%m-%d")
    refl_dir = Path(tree.notes_dir) / "wiki" / "reflections"
    refl_dir.mkdir(parents=True, exist_ok=True)
    target = refl_dir / f"{today}-{kind.replace('review-', '')}.md"
    if target.exists():
        return None
    questions = [str(q) for q in (data.get("questions") or [])]
    lines = [
        "---",
        f"created: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "source: reflection",
        f"tags: [回顾, {'周回顾' if 'weekly' in kind else '月回顾'}]",
        f"title: '{today} {'周回顾' if 'weekly' in kind else '月回顾'}（原始回答）'",
        "---",
        "",
        f"# {today} {'周回顾' if 'weekly' in kind else '月回顾'}（原始回答）",
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
