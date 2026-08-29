"""Flatnotes 与记忆模块的集成门面（架构 v1.2）。

Flatnotes 与记忆模块共享同一平面目录（$OV/memory），因此**不存在同步**
这一环节：集成的职责是"归一化"——把外部（Flatnotes/Obsidian 等）写入的
新文件补写一次性 frontmatter 并登记 sidecar，把外部删除从 sidecar 注销。

所有操作都是纯文件系统操作，Flatnotes 是否启动不影响归一化。
"""

from __future__ import annotations

from typing import Dict

from scripts.memory.core import MemoryTree
from scripts.memory.watcher import MemoryWatcher


class FlatnotesIntegration:
    """Flatnotes 与记忆模块的集成门面：共享平面目录 + 归一化。

    薄组合层：所有归一化逻辑都委托给 MemoryWatcher，本类只负责
    装配（tree + watcher）与暴露统一入口。

    Attributes:
        tree: 共享的 MemoryTree（notes_dir 即 Flatnotes 挂载的数据目录）。
        watcher: 归一化用的 MemoryWatcher（source="web"）。
    """

    def __init__(self, memory_tree: MemoryTree, source: str = "web") -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例（notes_dir 必须与 Flatnotes
                数据目录一致，即共享同一平面目录）。
            source: 新文件归一化时写入 frontmatter 的默认来源。
        """
        self.tree = memory_tree
        self.watcher = MemoryWatcher(memory_tree, source=source)

    @classmethod
    def from_config(
        cls, config_path: str, source: str = "web"
    ) -> "FlatnotesIntegration":
        """从 YAML 配置构造集成门面。

        Args:
            config_path: YAML 配置文件路径（memory.root / memory.state_dir
                等，格式同 MemoryTree.from_config）。
            source: 新文件归一化时写入 frontmatter 的默认来源。

        Returns:
            FlatnotesIntegration: 装配好 tree 与 watcher 的实例。
        """
        tree = MemoryTree.from_config(config_path)
        return cls(tree, source=source)

    def process_pending(self) -> Dict:
        """对齐 notes_dir 与 sidecar 索引（委托 watcher）。

        Returns:
            Dict: normalized / registered / deregistered / skipped 各为
                路径列表。
        """
        return self.watcher.process_pending()

    def start(self) -> None:
        """启动常驻文件系统监听（委托 watcher）。"""
        self.watcher.start()

    def stop(self) -> None:
        """停止常驻文件系统监听（委托 watcher）。"""
        self.watcher.stop()
