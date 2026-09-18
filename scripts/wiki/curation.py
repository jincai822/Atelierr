"""wiki 机器自留地（OKF v0.2 约定）：index.md / log.md / 主题页 / 时效复查。

OKF 分工「人类策展，LLM 维护」里机器被允许写的一面（2026-09-18 用户
裁决，OKF 全量采纳）：

- ``update_index``：wiki/index.md 导航——「## 摘录卡」节逐卡一行
  （创建时写入 okf_version 声明，与 OKF 同构）；
- ``append_log``：wiki/log.md 变更日志——最新日期节在最上，同日追加；
- ``update_topic_page``：wiki/topics/<主题>.md 主题页——新卡落地时
  追加收录行（幂等），并请 LLM 刷新一句话导读（**失败保留旧导读，
  追加永远成功**——LLM 只是导读的增强工序）；主题取自中图法标签
  （如 ``C93-管理·领导``），取不到归「未分类」；
- ``list_stale_cards``：扫描 ``stale_after`` 到期的 stable 卡（只读，
  供晨报「到期复查」节点名；复查与改日期是人的动作，机器不动卡）。

纪律（与 wiki/manager 同源）：除上述约定文件外绝不改写任何笔记；
一切写入幂等；索引/日志/主题页之外的状态一律不碰。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter
import httpx
import yaml

#: LLM 默认接入点（与 dispatch.distill 同规格；配置节 wiki.curation.llm）
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_KEY_ENV = "DEEPSEEK_API_KEY"

#: 主题页目录（wiki/ 下）
TOPICS_DIRNAME = "topics"

#: 中图法分类标签（C93-管理·领导 / B2-中国哲学 / TP391-… 形态）
_CLC_TAG_RE = re.compile(r"^[A-Z]+\d")

#: 文件名非法字符（与 distill 同源纪律）
_ILLEGAL_NAME_RE = re.compile(r'[\\/:*?"<>|]')

#: 主题导读提示词：2-3 句话，供人和 AI 快速判断这个主题在攒什么
_BRIEF_PROMPT = (
    "以下是个人 wiki 主题「{topic}」目前收录的知识卡片（标题——一句话简介）：\n"
    "{items}\n\n请用 2-3 句话（80 字以内）写这个主题的导读：这个主题在积累"
    "什么知识、目前覆盖了哪些方面。只说事实，不评价、不展望。"
    "不要输出导读以外的任何内容。"
)


def _load_llm_config() -> Dict[str, Any]:
    """读取配置 ``wiki.curation.llm`` 节（缺失/损坏返回空表）。"""
    for config_file in ("config/processors.yaml", "config/processors.yaml.example"):
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            section = data.get("wiki")
            if isinstance(section, dict) and isinstance(section.get("curation"), dict):
                llm = section["curation"].get("llm")
                if isinstance(llm, dict):
                    return dict(llm)
    return {}


def update_index(wiki_dir: Path, filename: str, title: str, description: str) -> None:
    """维护 wiki/index.md（OKF 导航页）：在「## 摘录卡」节追加一行（幂等）。"""
    path = Path(wiki_dir) / "index.md"
    entry = f"* [{title}]({filename}) - {description}"
    if not path.exists():
        path.write_text(
            "---\nokf_version: \"0.2\"\n---\n\n# 知识库导航\n\n"
            f"## 摘录卡\n\n{entry}\n",
            encoding="utf-8",
        )
        return
    text = path.read_text(encoding="utf-8")
    if entry in text:
        return
    match = re.search(r"^## 摘录卡\s*$", text, re.M)
    if match:
        # 插到该节末尾（下一个二级标题或文末之前）
        tail = text[match.end():]
        next_h = re.search(r"^## ", tail, re.M)
        insert_at = match.end() + (next_h.start() if next_h else len(tail))
        body = text[:insert_at].rstrip("\n") + "\n" + entry + "\n"
        text = body + text[insert_at:].lstrip("\n")
    else:
        text = text.rstrip("\n") + f"\n\n## 摘录卡\n\n{entry}\n"
    path.write_text(text, encoding="utf-8")


def update_index_topic(wiki_dir: Path, topic: str, topic_filename: str, count: int) -> None:
    """维护 index.md 的「## 主题页」节：每个主题一行（已存在则替换计数）。"""
    path = Path(wiki_dir) / "index.md"
    entry = f"* [{topic}]({TOPICS_DIRNAME}/{topic_filename}) - {count} 张卡"
    if not path.exists():
        path.write_text(
            "---\nokf_version: \"0.2\"\n---\n\n# 知识库导航\n\n"
            f"## 主题页\n\n{entry}\n",
            encoding="utf-8",
        )
        return
    text = path.read_text(encoding="utf-8")
    line_re = re.compile(rf"^\* \[{re.escape(topic)}\]\({TOPICS_DIRNAME}/[^\)]*\).*$", re.M)
    if line_re.search(text):
        text = line_re.sub(entry, text, count=1)
        path.write_text(text, encoding="utf-8")
        return
    match = re.search(r"^## 主题页\s*$", text, re.M)
    if match:
        tail = text[match.end():]
        next_h = re.search(r"^## ", tail, re.M)
        insert_at = match.end() + (next_h.start() if next_h else len(tail))
        body = text[:insert_at].rstrip("\n") + "\n" + entry + "\n"
        text = body + text[insert_at:].lstrip("\n")
    else:
        text = text.rstrip("\n") + f"\n\n## 主题页\n\n{entry}\n"
    path.write_text(text, encoding="utf-8")


def append_log(wiki_dir: Path, filename: str, title: str) -> None:
    """维护 wiki/log.md（OKF 变更日志）：最新日期节在最上，同日追加。"""
    path = Path(wiki_dir) / "log.md"
    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"* **Creation**: 新增 [{title}]({filename})。"
    header = "# Knowledge Update Log\n"
    if not path.exists():
        path.write_text(f"{header}\n## {today}\n\n{entry}\n", encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(today)}\s*$", text, re.M):
        text = re.sub(
            rf"(^## {re.escape(today)}\s*\n)",
            rf"\1\n{entry}\n",
            text,
            count=1,
            flags=re.M,
        )
    else:
        text = text.rstrip("\n") + "\n"
        # 新日期节插在头部之后（最新在最上）
        if text.startswith(header):
            text = header + f"\n## {today}\n\n{entry}\n" + text[len(header):].lstrip("\n")
        else:
            text = f"{header}\n## {today}\n\n{entry}\n\n" + text
    path.write_text(text, encoding="utf-8")


def _derive_topic(tags: List[str], topic_hint: str = "") -> str:
    """定主题：优先显式 hint，其次首个中图法形态标签，兜底「未分类」。"""
    if topic_hint.strip():
        return topic_hint.strip()
    for tag in tags:
        if _CLC_TAG_RE.match(str(tag)):
            return str(tag)
    return "未分类"


def _llm_brief(topic: str, items: List[str]) -> Optional[str]:
    """请 LLM 写主题导读；不可用/失败返回 None（保留旧导读）。"""
    api_key = os.environ.get(_LLM_KEY_ENV, "").strip()
    if not api_key or not items:
        return None
    cfg = _load_llm_config()
    base_url = str(cfg.get("base_url", _LLM_DEFAULT_BASE_URL)).rstrip("/")
    prompt = _BRIEF_PROMPT.format(
        topic=topic,
        items="\n".join(f"- {item}" for item in items[:30]),
    )
    payload = {
        "model": str(cfg.get("model", _LLM_DEFAULT_MODEL)),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": int(cfg.get("max_tokens", 300)),
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
    }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=float(cfg.get("timeout", 60)),
        )
        response.raise_for_status()
        brief = str(response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001 - 导读是增强工序，失败保留旧文
        return None
    brief = brief.strip('"').replace("\n", " ")
    return brief or None


def update_topic_page(
    wiki_dir: Path,
    *,
    card_stem: str,
    card_title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    topic_hint: str = "",
    llm: bool = True,
) -> Path:
    """把一张新卡收录进主题页（不存在则创建），并维护 index 主题节。

    收录行幂等（同 stem 不重复收）；收录后请 LLM 刷新导读（失败保留
    旧导读）。主题页是机器自留地（OKF「LLM 维护」面），允许创建/更新。

    Args:
        wiki_dir: wiki/ 目录。
        card_stem: 卡片文件名（去 .md）。
        card_title: 卡片标题。
        description: 一句话简介（缺省用标题）。
        tags: 卡片标签（定主题用）。
        topic_hint: 显式主题（如书籍档案里的中图法），优先于标签推导。
        llm: 是否刷新导读（测试关）。

    Returns:
        Path: 主题页路径。
    """
    wiki_dir = Path(wiki_dir)
    topic = _derive_topic([str(t) for t in (tags or [])], topic_hint)
    safe_topic = _ILLEGAL_NAME_RE.sub("", topic).strip() or "未分类"
    topics_dir = wiki_dir / TOPICS_DIRNAME
    topics_dir.mkdir(parents=True, exist_ok=True)
    path = topics_dir / f"{safe_topic}.md"
    desc = description.strip() or card_title
    if not path.exists():
        metadata = {
            "type": "Topic",
            "title": topic,
            "status": "stable",
            "generated": {
                "by": "atelierr-wiki/1.0",
                "at": datetime.now(timezone.utc).isoformat(),
            },
            "tags": ["主题页"],
        }
        body = f"# {topic}\n\n> （导读维护中）\n\n## 收录卡片\n"
        path.write_text(
            frontmatter.dumps(frontmatter.Post(body, **metadata)), encoding="utf-8"
        )
    text = path.read_text(encoding="utf-8")
    entry = f"- [[{card_stem}]] — {desc}"
    if f"[[{card_stem}]]" not in text:
        text = text.rstrip("\n") + "\n" + entry + "\n"
    # LLM 刷新导读（增强工序：失败/无 key 保留旧行）
    if llm:
        items = re.findall(r"^- \[\[(.+?)\]\] — (.+)$", text, re.M)
        brief = _llm_brief(topic, [f"{stem} — {d}" for stem, d in items])
        if brief:
            text = re.sub(r"^> .*$", f"> {brief}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")
    count = len(re.findall(r"^- \[\[", text, re.M))
    update_index_topic(wiki_dir, topic, path.name, count)
    return path


def list_stale_cards(wiki_dir: Path, today: str) -> List[Tuple[str, str, str]]:
    """扫描 stale_after 到期的 stable 卡（只读；供晨报「到期复查」节）。

    Args:
        wiki_dir: wiki/ 目录（含 topics/ 子目录一并扫描）。
        today: YYYY-MM-DD。

    Returns:
        List[Tuple[str, str, str]]: (stem, title, stale_after) 按到期日升序。
    """
    wiki_dir = Path(wiki_dir)
    found: List[Tuple[str, str, str]] = []
    if not wiki_dir.is_dir():
        return found
    paths = list(wiki_dir.glob("*.md")) + list((wiki_dir / TOPICS_DIRNAME).glob("*.md"))
    for path in sorted(paths):
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏跳过
            continue
        stale_after = str(post.get("stale_after") or "")[:10]
        if not stale_after or stale_after > today:
            continue
        if str(post.get("status") or "stable") == "deprecated":
            continue
        found.append((path.stem, str(post.get("title") or path.stem), stale_after))
    found.sort(key=lambda item: item[2])
    return found
