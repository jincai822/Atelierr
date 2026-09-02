"""沉淀层 wiki（五层规划第④层）：只增不改的常青知识库。

与 memory/（缓冲区耗材，会衰减、会被 purge）相对：wiki/ 条目由人工
提炼、人工撰写，机器绝不改写/移动/删除，无 decay、无 purge。

布局：wiki/ 是库根（$OV/memory，即 Obsidian vault）下的子目录。
memory 机制（watcher/decay/search/digest）只扫根层 ``*.md``，与子目录
互不干扰；Obsidian/Syncthing 天然递归覆盖子目录。

入口（低摩擦，60 秒内完成）：Obsidian QuickAdd「提炼为 Wiki」
（模板 ``templates/wiki条目.md``），或电脑端直接新建。纪律由
WikiManager.validate() 把关（只报告、绝不改写）：

- 必需 frontmatter：created / source / from（提炼自哪条 memory 笔记）；
- 正文至少一条指向已有 wiki 条目的 wikilink（防散装、防孤岛）。

机器唯一的写动作：ensure_dir() 一次性创建 wiki/ 目录。
"""

from scripts.wiki.manager import WIKI_DIRNAME, WikiManager

__all__ = ["WIKI_DIRNAME", "WikiManager"]
