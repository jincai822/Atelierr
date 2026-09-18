"""外部写入归一化门面（原 Flatnotes 集成门面，架构 v1.2）。

2026-09-18 用户裁决：Flatnotes 网页版退役（入口收敛为 Obsidian + 飞书，
docker 容器已移除）；本门面**保留**——任何外部写入者（Obsidian、
Syncthing 同步落盘、历史网页端）在共享平面目录（$OV/memory）写下的
裸 markdown，都需要同一份归一化：补写一次性 frontmatter 并登记
sidecar，把外部删除从 sidecar 注销。

所有操作都是纯文件系统操作，不依赖任何 Web 服务在线。
"""

from __future__ import annotations

from typing import Dict

from scripts.memory.core import MemoryTree
from scripts.memory.watcher import MemoryWatcher


class WebIntegration:
    """外部写入与记忆模块的集成门面：共享平面目录 + 归一化。

    薄组合层：所有归一化逻辑都委托给 MemoryWatcher，本类只负责
    装配（tree + watcher）与暴露统一入口。

    Attributes:
        tree: 共享的 MemoryTree（notes_dir 即外部写入者落盘的数据目录）。
        watcher: 归一化用的 MemoryWatcher（source="web"）。
    """

    def __init__(self, memory_tree: MemoryTree, source: str = "web") -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例（notes_dir 必须与外部写入者的
                数据目录一致，即共享同一平面目录）。
            source: 新文件归一化时写入 frontmatter 的默认来源。
        """
        self.tree = memory_tree
        self.watcher = MemoryWatcher(memory_tree, source=source)

    @classmethod
    def from_config(
        cls, config_path: str, source: str = "web"
    ) -> "WebIntegration":
        """从 YAML 配置构造集成门面。

        Args:
            config_path: YAML 配置文件路径（memory.root / memory.state_dir
                等，格式同 MemoryTree.from_config）。
            source: 新文件归一化时写入 frontmatter 的默认来源。

        Returns:
            WebIntegration: 装配好 tree 与 watcher 的实例。
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
