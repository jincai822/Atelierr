"""wiki 沉淀层管理器：只读盘点与纪律校验，绝不改写任何笔记。

条目即 ``<库根>/wiki/*.md``（平面，无子目录）。与 memory 的关系：
单向引用——wiki 条目用 frontmatter ``from`` 指向它提炼自的 memory
笔记（wikilink 或纯 stem）；memory 机制完全不知道 wiki 的存在。

校验规则（validate，只报告）：
- frontmatter 可解析且含 created / source / from（from 归一化后非空）；
- 正文至少一条指向其他已存在 wiki 条目的 wikilink；
- from 指向的 memory 笔记仍存在（缺失只提示，可能是已被 purge）。

还提供 orphans()（wiki 内零入链条目）与 distilled_stems()（已被
提炼过的 memory 笔记 stem 集合，供晨间摘要算"反复推送未提炼"）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import frontmatter

from scripts.memory.core import MemoryTree

WIKI_DIRNAME = "wiki"  # 库根下的沉淀层子目录名（memory.yaml 可覆盖）

REQUIRED_FRONTMATTER = ("created", "source", "from")

WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:[#|][^\[\]]*)?\]\]")


def _normalize_ref(value: Any) -> str:
    """把 from 字段归一化为笔记 stem：去 [[]]、去别名/锚点、去空白。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = str(value or "").strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = re.split(r"[|#]", text, maxsplit=1)[0].strip()
    return text


class WikiManager:
    """wiki 沉淀层的只读盘点器。

    Attributes:
        tree: MemoryTree 实例（只借它的 notes_dir 定位库根与 memory 笔记）。
        wiki_dir: wiki/ 目录路径（库根子目录）。
    """

    def __init__(self, memory_tree: MemoryTree, dirname: str = WIKI_DIRNAME) -> None:
        """初始化（不创建目录；ensure_dir 是唯一写动作）。

        Args:
            memory_tree: MemoryTree 实例。
            dirname: 库根下的子目录名，默认 ``wiki``。
        """
        self.tree = memory_tree
        self.wiki_dir = Path(memory_tree.notes_dir) / dirname

    @classmethod
    def from_config(
        cls, config_path: str, tree: Optional[MemoryTree] = None
    ) -> "WikiManager":
        """从 memory.yaml 构造（读 memory.wiki_dirname，缺省 ``wiki``）。

        Args:
            config_path: 配置文件路径。
            tree: 复用已有 MemoryTree；None 时按同一配置新建。
        """
        from scripts.utils.config import deep_get, load_config

        cfg = load_config(str(config_path))
        return cls(
            tree or MemoryTree.from_config(str(config_path)),
            dirname=str(deep_get(cfg, "memory.wiki_dirname", WIKI_DIRNAME)),
        )

    def ensure_dir(self) -> Path:
        """一次性创建 wiki/ 目录（已存在则无副作用）。"""
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        return self.wiki_dir

    def entries(self) -> List[Dict[str, Any]]:
        """盘点全部 wiki 条目（按文件名排序；目录缺失返回空）。

        Returns:
            List[Dict]: stem/path/metadata/from/links/broken_frontmatter；
                links 为正文 wikilink 目标 stem 列表（已去别名/锚点）；
                from 为归一化后的 memory 笔记 stem（空串表示未填）。
        """
        return [self._entry(path) for path in sorted(self.wiki_dir.glob("*.md"))]

    def validate(self) -> List[Dict[str, Any]]:
        """纪律校验：返回有问题的条目及原因（无问题返回空）。

        Returns:
            List[Dict]: [{"stem": ..., "issues": [...]}]，只报告不改写。
        """
        entries = self.entries()
        wiki_stems = {entry["stem"] for entry in entries}
        memory_stems = {
            path.stem for path in Path(self.tree.notes_dir).glob("*.md")
        }
        problems: List[Dict[str, Any]] = []
        for entry in entries:
            issues: List[str] = []
            if entry["broken_frontmatter"]:
                issues.append("frontmatter 损坏")
            else:
                for key in REQUIRED_FRONTMATTER:
                    if not entry["metadata"].get(key):
                        issues.append(f"缺 frontmatter 字段 {key}")
            if not entry["from"]:
                issues.append("from 未填（提炼自哪条 memory 笔记）")
            elif entry["from"] not in memory_stems:
                issues.append(f"from 指向的 memory 笔记不存在: {entry['from']}")
            if not any(
                link in wiki_stems and link != entry["stem"]
                for link in entry["links"]
            ):
                issues.append("缺指向已有 wiki 条目的 wikilink")
            if issues:
                problems.append({"stem": entry["stem"], "issues": issues})
        return problems

    def orphans(self) -> List[str]:
        """wiki 内部零入链的条目 stem（按名称排序）。"""
        entries = self.entries()
        stems = {entry["stem"] for entry in entries}
        linked: Set[str] = set()
        for entry in entries:
            for link in entry["links"]:
                if link in stems and link != entry["stem"]:
                    linked.add(link)
        return sorted(stems - linked)

    def distilled_stems(self) -> Set[str]:
        """已被提炼过的 memory 笔记 stem 集合（所有条目的 from 并集）。"""
        return {entry["from"] for entry in self.entries() if entry["from"]}

    def stats(self) -> Dict[str, int]:
        """总条目数 / 孤儿数 / 待修数 / 已提炼来源数。"""
        entries = self.entries()
        return {
            "total": len(entries),
            "orphans": len(self.orphans()),
            "invalid": len(self.validate()),
            "distilled_sources": len(
                {entry["from"] for entry in entries if entry["from"]}
            ),
        }

    @staticmethod
    def _entry(path: Path) -> Dict[str, Any]:
        """解析单条 wiki 条目；frontmatter 损坏时按纯正文降级。"""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        try:
            post = frontmatter.loads(text)
            metadata, body, broken = dict(post.metadata), post.content, False
        except Exception:  # noqa: BLE001 - 损坏 frontmatter 按纯正文降级
            metadata, body, broken = {}, text, True
        links = [match.group(1).strip() for match in WIKILINK_RE.finditer(body)]
        return {
            "stem": path.stem,
            "path": path,
            "metadata": metadata,
            "from": _normalize_ref(metadata.get("from")),
            "links": links,
            "broken_frontmatter": broken,
        }
