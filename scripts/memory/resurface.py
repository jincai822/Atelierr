"""复习队列「回响」（三回路之一）：decay 的反面。

decay 把 confidence 跌破 delete_threshold 的笔记推向 pending_delete
（遗忘通道）；本模块把 confidence 跌入"遗忘临界区"（默认
[0.15, 0.5)，无引用笔记约闲置 2~4 周）的笔记挑出来，由晨间摘要
（dispatch_cli digest）以"今日复习"一节送回用户面前：

- 用户点开看一眼 → on_note_accessed 重置时钟，笔记自然离开队列；
- 用户确认无价值 → 任其继续衰减进 pending_delete，走 review→purge。

纪律（与 decay 同源）：
- 只读笔记与 sidecar 索引，绝不改写笔记文件；
- 推送冷却时钟只写 ``<state_dir>/resurface.json``；
- 幂等：同一笔记间隔期内不重复推送；
- 机器搬运全文（MACHINE_SOURCES）未确认归档前不推，被 [[引用]] ≥1 次
  除外（2026-09-12 信噪比治理）；**已确认归档出 inbox/ 的机器笔记
  恢复复习资格**（2026-09-16 用户裁决：点 ✅ = 人认可要吸收的内容，
  与人写笔记同权——确认→复习→淘汰闭环；实测此前复习队列因此恒空）。

间隔重复（2026-09-13 升级）：复习卡带「想起来了/没想起来」反馈按钮，
每篇笔记有独立间隔（想起来 ×2、没想起来 ÷2、上限 60 天）——常想起的
少打扰，想不起来的多见面。反馈只写复习调度状态（resurface.json），
不进 confidence 公式（无状态契约不破）；「想起来了」顺带记一次
on_note_accessed（访问=使用信号，合法重置闲置时钟）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from scripts.memory.core import LAYERS, MACHINE_SOURCES, MemoryTree
from scripts.memory.decay import DecayManager
from scripts.utils.date_utils import local_timezone, parse_date

DEFAULT_WINDOW_LOW = 0.15  # 低于此值交给 decay 的待删除通道
DEFAULT_WINDOW_HIGH = 0.5  # 高于此值说明还"热"，不必推送
DEFAULT_DAILY_COUNT = 3  # 每日晨报最多推送条数
DEFAULT_COOLDOWN_DAYS = 3  # 同一笔记几天内不重复推送


class ResurfaceManager:
    """复习队列管理器：筛选遗忘临界区内的笔记并记录推送冷却。

    Attributes:
        tree: MemoryTree 实例。
        window_low: 复习窗口下限（含）。
        window_high: 复习窗口上限（不含）。
        daily_count: 每日默认推送条数。
        cooldown_days: 同一笔记重复推送的最小间隔天数。
    """

    def __init__(
        self,
        memory_tree: MemoryTree,
        *,
        window_low: float = DEFAULT_WINDOW_LOW,
        window_high: float = DEFAULT_WINDOW_HIGH,
        daily_count: int = DEFAULT_DAILY_COUNT,
        cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    ) -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
            window_low: 复习窗口下限（含），应对齐 delete_threshold 之上。
            window_high: 复习窗口上限（不含）。
            daily_count: 每日默认推送条数。
            cooldown_days: 同一笔记重复推送的最小间隔天数。

        Raises:
            ValueError: 窗口不是 0 <= low < high <= 1。
        """
        if not 0.0 <= window_low < window_high <= 1.0:
            raise ValueError(
                f"复习窗口需满足 0 <= low < high <= 1: [{window_low}, {window_high})"
            )
        self.tree = memory_tree
        self.window_low = float(window_low)
        self.window_high = float(window_high)
        self.daily_count = int(daily_count)
        self.cooldown_days = int(cooldown_days)
        self.state_path = self.tree.state_dir / "resurface.json"

    @classmethod
    def from_config(
        cls, config_path: str, tree: Optional[MemoryTree] = None
    ) -> "ResurfaceManager":
        """从 memory.yaml 构造（读 memory.resurface 节，缺失字段用默认值）。

        Args:
            config_path: 配置文件路径。
            tree: 复用已有 MemoryTree；None 时按同一配置新建。
        """
        from scripts.utils.config import deep_get, load_config

        cfg = load_config(str(config_path))
        return cls(
            tree or MemoryTree.from_config(str(config_path)),
            window_low=float(
                deep_get(cfg, "memory.resurface.window_low", DEFAULT_WINDOW_LOW)
            ),
            window_high=float(
                deep_get(cfg, "memory.resurface.window_high", DEFAULT_WINDOW_HIGH)
            ),
            daily_count=int(
                deep_get(cfg, "memory.resurface.daily_count", DEFAULT_DAILY_COUNT)
            ),
            cooldown_days=int(
                deep_get(
                    cfg, "memory.resurface.cooldown_days", DEFAULT_COOLDOWN_DAYS
                )
            ),
        )

    def candidates(
        self, limit: Optional[int] = None, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """返回今日复习队列（按 confidence 升序，最该复习的在前）。

        只纳入：已登记且文件存在、非 pending_delete、非机器摘要/基础设施
        （source=digest/system）、非滞留中转站的机器搬运全文（inbox/ 内
        的 MACHINE_SOURCES——复习位是稀缺资源；例外：被 [[引用]] ≥1 次
        恢复资格，反链统计与每日衰减同源；**已确认归档出 inbox/ 的机器
        笔记与人写笔记同权**，2026-09-16 用户裁决）、live confidence
        落在 [window_low, window_high)、且距上次推送已满 cooldown_days
        的笔记。

        Args:
            limit: 条数上限；None 时用 daily_count；<= 0 返回空。
            now: 计算基准时刻（测试用）；缺省当前时间。

        Returns:
            List[Dict]: id/title/filename/confidence/idle_days/layer。
        """
        limit = self.daily_count if limit is None else int(limit)
        if limit <= 0:
            return []
        now = now or datetime.now().astimezone()
        pushed = self._load_state()
        picked: List[Dict[str, Any]] = []
        backlinks: Optional[Dict[Any, int]] = None  # 惰性：有机器笔记才扫描
        for layer in LAYERS:
            for path in self.tree.list_notes(layer):
                try:
                    info = self.tree.note_info(path)
                except (OSError, ValueError):
                    continue
                if info["pending_delete"]:
                    continue
                source = str(info.get("source") or "")
                if source in ("digest", "system"):
                    continue  # 机器摘要/基础设施笔记（控制台等）不需复习
                if source in MACHINE_SOURCES:
                    if str(self.tree._rel_key(path)).startswith("inbox/"):
                        # 未确认归档的机器搬运（2026-09-12 信噪比治理）：
                        # 不占复习位，除非被 [[引用]] ≥1 次
                        if backlinks is None:
                            backlinks = {
                                p.stem: count
                                for p, count in DecayManager(self.tree)
                                .backlink_counts()
                                .items()
                            }
                        if backlinks.get(path.stem, 0) < 1:
                            continue
                    # else：已确认归档出中转站（2026-09-16 用户裁决）——
                    # 人点过 ✅ 的机器笔记恢复复习资格，与人写笔记同权；
                confidence = info["confidence"]
                if not (self.window_low <= confidence < self.window_high):
                    continue
                note_id = str(info.get("id") or path.stem)
                stamp = pushed.get(note_id)
                if isinstance(stamp, dict) and stamp.get("exiled"):
                    continue  # 流放（🚫 不再推 / 连续没想起来的水蛭卡）
                if stamp and self._in_cooldown(stamp, now):
                    continue
                picked.append(
                    {
                        "id": note_id,
                        "title": info.get("title") or path.stem,
                        "filename": path.name,
                        "relpath": self.tree._rel_key(path),
                        "confidence": confidence,
                        "idle_days": self._idle_days(info, path, now),
                        "layer": info["layer"],
                    }
                )
        picked.sort(key=lambda item: (item["confidence"], item["filename"]))
        return picked[:limit]

    def mark_pushed(
        self, note_ids: List[str], now: Optional[datetime] = None
    ) -> None:
        """记录一批笔记已推送（该篇间隔时钟起点）；空列表直接返回。

        只写 ``<state_dir>/resurface.json``（原子写），绝不触碰笔记文件。

        Args:
            note_ids: 已推送笔记的 id 列表。
            now: 推送时刻（测试用）；缺省当前时间。
        """
        ids = [str(note_id) for note_id in note_ids]
        if not ids:
            return
        now = now or datetime.now().astimezone()
        state = self._load_state()
        stamp = now.isoformat(timespec="seconds")
        for note_id in ids:
            entry = state.get(note_id)
            interval = (
                float(entry.get("interval", self.cooldown_days))
                if isinstance(entry, dict)
                else self.cooldown_days
            )
            state[note_id] = {"pushed": stamp, "interval": interval, "streak": 0}
        self._save_state(state)

    def record_outcome(
        self, note_id: str, remembered: bool, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """记录复习反馈（简化 SM-2）：想起来 → 间隔 ×2（封顶 60 天）且记一次
        访问（合法重置闲置时钟）；没想起来 → 间隔 ÷2（下限 1 天）。

        只写复习调度状态（resurface.json），不进 confidence 公式——
        无状态契约不破。返回该笔记的新调度状态。

        Args:
            note_id: 笔记 id（sidecar 键）。
            remembered: True=想起来了；False=没想起来。
            now: 反馈时刻（测试用）。

        Returns:
            Dict[str, Any]: {"interval", "streak", "pushed"}。
        """
        now = now or datetime.now().astimezone()
        state = self._load_state()
        entry = state.get(note_id)
        interval = (
            float(entry.get("interval", self.cooldown_days))
            if isinstance(entry, dict)
            else self.cooldown_days
        )
        streak = int(entry.get("streak", 0)) if isinstance(entry, dict) else 0
        fail_streak = int(entry.get("fail_streak", 0)) if isinstance(entry, dict) else 0
        if remembered:
            interval = min(interval * 2, 60.0)
            streak += 1
            fail_streak = 0
        else:
            interval = max(1.0, interval / 2)
            streak = 0
            fail_streak += 1
        entry_out = {
            "pushed": now.isoformat(timespec="seconds"),
            "interval": interval,
            "streak": streak,
            "fail_streak": fail_streak,
        }
        # 水蛭处理（2026-09-18 脑科学评审 C3）：连续 2 次「没想起来」
        # 自动流放——SRS 里这叫 leech suspend，再推只是骚扰，不是复习
        if fail_streak >= 2:
            entry_out["exiled"] = True
        state[note_id] = entry_out
        self._save_state(state)
        return dict(state[note_id])

    def exile(self, note_id: str, now: Optional[datetime] = None) -> None:
        """流放一条笔记（🚫 不再推）：candidates 永久跳过。

        只写 resurface.json，不碰笔记本身（内容去留交给 review→purge，
        与「不想被推」是两回事）。
        """
        now = now or datetime.now().astimezone()
        state = self._load_state()
        entry = state.get(note_id)
        if not isinstance(entry, dict):
            entry = {"interval": self.cooldown_days, "streak": 0}
        entry["exiled"] = True
        entry["pushed"] = now.isoformat(timespec="seconds")
        state[note_id] = entry
        self._save_state(state)

    def _in_cooldown(self, stamp: Any, now: datetime) -> bool:
        """距上次推送不足该篇间隔（缺省 cooldown_days）返回 True；
        旧格式（纯时间戳）/损坏视为 cooldown_days 间隔。"""
        if isinstance(stamp, dict):
            interval = float(stamp.get("interval", self.cooldown_days))
            stamp = stamp.get("pushed")
        else:
            interval = self.cooldown_days
        try:
            return (now - parse_date(str(stamp))).days < interval
        except ValueError:
            return False

    @staticmethod
    def _idle_days(info: Dict[str, Any], path, now: datetime) -> int:
        """展示用闲置天数：与 confidence 同源（最后访问/修改的较新者）。"""
        stamps = [
            datetime.fromtimestamp(path.stat().st_mtime, tz=local_timezone())
        ]
        if info.get("last_accessed"):
            stamps.append(parse_date(info["last_accessed"]))
        return max((now - max(stamps)).days, 0)

    def _load_state(self) -> Dict[str, str]:
        """读取冷却状态；缺失/损坏返回空表（冷却状态丢了最多重推一次）。"""
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, str]) -> None:
        """原子写冷却状态：先写临时文件再 rename。"""
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.state_path)
