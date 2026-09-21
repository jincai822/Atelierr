"""日记行的实体反链（2026-09-21 第 9 条①，车间 $sync Researcher 的确定性版）。

车间 $sync 用 LLM Researcher 找实体再建链；我们这里实体目标明确
（wiki/ 知识卡 + people/ 人物），直接拿现有笔记标题做精确子串匹配，
零 LLM 成本、零幻觉。规则与车间同一条铁律：**显示文字必须与目标
笔记标题逐字一致**——只包裹完全等于标题的原文片段，绝不造别名链接。

纪律：
- 只在行文出生那一刻包裹（飞书消息进日记时），不回头改既有行
  （"笔记创建后机器不改写"红线——日记追加是批准例外，回改不是）；
- 含 URL 的行整行不包（链接管线的行各有各的家）；
- 已在 ``[[...]]`` 内的片段不重复包；
- 目标层是 wiki/（cognition/ 判断登记处与 reflections/ 反思库除外）、
  distilled/ 与 people/——知识卡与人物才是实体；领域/平台
  笔记不链（标题撞词风险高）；
- 子串误包接受（中文无词边界，如「叔本华主义」会包成
  [[叔本华]]主义）——目标层是人工精选的实体名，概率低、可见可改。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import frontmatter

#: 实体目标层（扫这些目录下的笔记标题；wiki/ 下的 cognition/ 判断
#: 登记处与 reflections/ 反思库除外——判断与反思不是实体，且判断
#: 登记与写日记同进程，不收会引发"刚登记的判断把自己链起来"的自链）
LINKABLE_DIRNAMES = ("wiki", "people", "distilled")

#: wiki/ 下排除的子库名
EXCLUDED_SUBDIRS = frozenset({"cognition", "reflections"})

#: 标题最短长度（单字标题撞词太狠，不链）
MIN_TITLE_LEN = 2

_URL_RE = re.compile(r"https?://")
_LINKED_RE = re.compile(r"\[\[[^\]]*\]\]")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_linkable_titles(tree) -> List[str]:
    """可链接的实体标题清单（长标题在前，防短标题先占位切碎长标题）。

    Args:
        tree: MemoryTree 实例。

    Returns:
        List[str]: wiki/ 与 people/ 下全部笔记的 frontmatter title
        （缺失用 stem），去重、按长度降序。
    """
    root = Path(tree.notes_dir)
    titles = set()
    for dirname in LINKABLE_DIRNAMES:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if set(path.relative_to(base).parts[:-1]) & EXCLUDED_SUBDIRS:
                continue  # cognition/ 与 reflections/ 不是实体目标
            try:
                post = frontmatter.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            title = str(post.get("title") or path.stem).strip()
            if len(title) >= MIN_TITLE_LEN and not _DATE_RE.match(title):
                titles.add(title)
    return sorted(titles, key=len, reverse=True)


def wrap_entities(text: str, titles: List[str]) -> str:
    """把 text 中与标题逐字一致的片段包成 ``[[标题]]``（其余一字不动）。

    Args:
        text: 原始文本（通常是一条日记行的内容）。
        titles: 候选标题（顺序随意，内部按长度降序，防短标题先占位
            切碎长标题）。

    Returns:
        str: 包裹后的文本；无命中或含 URL 时原样返回。
    """
    if not titles or _URL_RE.search(text):
        return text
    occupied: List[Tuple[int, int]] = [m.span() for m in _LINKED_RE.finditer(text)]
    spans: List[Tuple[int, int]] = []
    for title in sorted(titles, key=len, reverse=True):
        start = 0
        while True:
            idx = text.find(title, start)
            if idx < 0:
                break
            end = idx + len(title)
            start = end
            if any(idx < occ_end and end > occ_start for occ_start, occ_end in occupied):
                continue  # 与已链接/已占位片段重叠，跳过
            spans.append((idx, end))
            occupied.append((idx, end))
    if not spans:
        return text
    spans.sort()
    out = []
    cursor = 0
    for idx, end in spans:
        out.append(text[cursor:idx])
        out.append(f"[[{text[idx:end]}]]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)
