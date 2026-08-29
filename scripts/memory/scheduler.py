"""定时衰减调度器：按固定间隔执行 DecayManager.run()。"""
from __future__ import annotations

import threading
from typing import Dict, Optional

from scripts.memory.decay import DecayManager


class DecayScheduler:
    """周期性执行记忆衰减的调度器。

    Attributes:
        tree: 关联的 MemoryTree。
        interval_hours: 两次衰减的间隔小时数（默认 24）。
        manager: 内部的 DecayManager。
    """

    def __init__(self, memory_tree: "MemoryTree", interval_hours: int = 24) -> None:  # noqa: F821
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
            interval_hours: 衰减间隔小时数。
        """
        self.tree = memory_tree
        self.interval_hours = interval_hours
        self.manager = DecayManager(memory_tree)

    def run_once(self) -> Dict:
        """执行一次衰减并返回报告。

        Returns:
            Dict: DecayManager.run() 的报告。
        """
        return self.manager.run()

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        """循环执行衰减直到 stop_event 置位。

        Args:
            stop_event: 置位即退出循环；缺省内部新建（永不置位）。
        """
        stop = stop_event if stop_event is not None else threading.Event()
        while not stop.is_set():
            self.run_once()
            stop.wait(self.interval_hours * 3600)
