"""无状态 confidence 计算（架构 v1.2）。

conf = decay_rate ** (idle_days / ref_factor)，
幂等纯函数：任何时刻用同一元数据重算结果一致，不依赖历史值。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from scripts.utils.date_utils import parse_date


class ConfidenceCalculator:
    """无状态 confidence 计算器。

    Confidence 语义为"新鲜度/活跃度"，范围 [0.0, 1.0]：
    新笔记（idle 0 天）= 1.0；闲置越久越低；被引用越多衰减越慢。

    Attributes:
        decay_rate: 无引用时每日衰减率（默认 0.95）。
        ref_coefficient: 引用因子系数（默认 0.2）。
        ref_cap: 引用数封顶（默认 10，ref_factor 最大 3.0）。
    """

    def __init__(
        self,
        decay_rate: float = 0.95,
        ref_coefficient: float = 0.2,
        ref_cap: int = 10,
    ) -> None:
        """初始化计算器。

        Args:
            decay_rate: 每日衰减率，0 < decay_rate <= 1。
            ref_coefficient: 引用减缓系数（乘性）。
            ref_cap: 引用数封顶。
        """
        self.decay_rate = decay_rate
        self.ref_coefficient = ref_coefficient
        self.ref_cap = ref_cap

    def calculate(self, metadata: Dict, now: Optional[datetime] = None) -> float:
        """纯函数计算 confidence。

        活跃时点取最后访问与最后修改的较新者（缺失则忽略该项）；
        两者都缺时用 created；都没有则按 idle=0。references 缺省按 0。

        Args:
            metadata: 元数据字典，键可为
                accessed/modified（datetime 或 ISO 字符串，可缺省为 None）、
                created（同前）、references（int）。
            now: 计算基准时刻；缺省用当前时间。naive 视为本地时间。

        Returns:
            float: confidence，范围 [0.0, 1.0]。

        Examples:
            >>> calc = ConfidenceCalculator()
            >>> calc.calculate({"accessed": None, "modified": None})
            1.0
        """
        now = parse_date(now) if now is not None else datetime.now().astimezone()
        last_active: Optional[datetime] = None
        for key in ("accessed", "modified"):
            value = metadata.get(key)
            if value is None:
                continue
            candidate = parse_date(value)
            last_active = (
                candidate if last_active is None else max(last_active, candidate)
            )
        if last_active is None:
            created = metadata.get("created")
            if created is not None:
                last_active = parse_date(created)
        if last_active is None:
            last_active = now
        idle_days = (now - last_active).days
        return self.from_idle_days(idle_days, metadata.get("references") or 0)

    def from_idle_days(self, idle_days: int, references: int = 0) -> float:
        """由已知闲置天数直接计算（与 calculate 同一公式，单次真源）。

        供调用方在已持有 epoch 时间戳时避免 datetime 构造/减法开销
        （如搜索热路径）；``idle_days`` 负值钳到 0，``references`` 负值
        按 0、超 ref_cap 封顶。

        Args:
            idle_days: 闲置天数（整数，语义同 ``(now - last_active).days``）。
            references: 引用次数。

        Returns:
            float: confidence，范围 [0.0, 1.0]。
        """
        idle = max(int(idle_days), 0)
        refs = max(int(references), 0)
        ref_factor = 1 + self.ref_coefficient * min(refs, self.ref_cap)
        confidence = self.decay_rate ** (idle / ref_factor)
        return max(0.0, min(1.0, confidence))
