"""归档目录推导：飞书卡片「📁 确认并归档」按钮与通知「建议归档」行共用。

规则（与用户在 Obsidian 的手动归档约定一致）：
- 一级目录 = 平台：source=lark → 飞书；source=media → 媒体；
  source=link 或其它 → 取 frontmatter tags 里第一个平台标签
  （排除「待确认」与中图法类目标签，如 抖音/小红书）；取不到 → None
  （调用方自行 fallback：归档按钮落 媒体/，建议归档行省略）；
- 二级目录（可选）= 中图法分类标签：tags 里第一个匹配
  ``^[A-Z]{1,3}\\d*-`` 的标签（如 B84-心理学），没有就只进一级目录。

只读推导，不碰文件系统；两边消费同一份逻辑，避免规则漂移。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

#: 中图法分类标签（如 B84-心理学 / TP311.5-软件测试）→ 归档二级目录名
CCLASS_RE = re.compile(r"^[A-Z]{1,3}\d*-")

#: 待确认标签（与 dispatch/links.py、dispatch/media.py 的 REVIEW_TAG、
#: dispatch/feishu.py 的 CONFIRM_TAG 同值）；推导平台时不算平台标签
REVIEW_TAG = "待确认"

#: source → 归档一级目录（平台）名
PLATFORM_BY_SOURCE = {"lark": "飞书", "media": "媒体"}


def derive_archive_dir(post) -> Tuple[Optional[str], Optional[str]]:
    """从一篇笔记的 frontmatter Post 推导归档目录 (平台, 分类标签)。

    Args:
        post: python-frontmatter 的 Post 对象（metadata 含 source/tags）。

    Returns:
        Tuple[Optional[str], Optional[str]]: (平台目录名, 中图法分类
        标签)；平台推不出为 None，分类没有为 None。目录相对串 =
        ``平台 + ("/" + 分类 if 分类)``。
    """
    metadata = post.metadata
    source = str(metadata.get("source") or "")
    tags = [str(tag) for tag in (metadata.get("tags") or [])]
    if source in PLATFORM_BY_SOURCE:
        platform = PLATFORM_BY_SOURCE[source]
    else:
        platform = next(
            (
                tag
                for tag in tags
                if tag != REVIEW_TAG and not CCLASS_RE.match(tag)
            ),
            None,
        )
    category = next((tag for tag in tags if CCLASS_RE.match(tag)), None)
    return platform, category
