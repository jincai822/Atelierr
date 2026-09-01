"""推送响应率观测（三回路·实验 0）：复习推送有没有被加工。

"响应"定义：笔记被推送后 48 小时内 mtime 变化（任何端的编辑都会经
Syncthing/Flatnotes 反映为服务器上的 mtime），或被用户 purge（文件
消失，视为"已处理"）。纯浏览（尤其手机端阅读）不可观测，因此响应率
是真实互动的下限，只看趋势、不看绝对值。

判据（实验 0 的事先约定）：两周后响应率 <20% → 问题在推送本身
（时机/渠道/数量），先修推送；≥40% → 回路是活的，再加注意力精排。

纪律：
- 状态只写 ``<state_dir>/response_probe.json``（原子写，损坏重来）；
- 绝不触碰笔记文件（只读 mtime）；
- 观测随晨间摘要（DigestDispatcher）每日执行一次，不新增定时器。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from scripts.memory.core import MemoryTree
from scripts.utils.date_utils import parse_date

RESPONSE_WINDOW = timedelta(hours=48)  # 推送后的响应观察窗
MAX_RESOLVED = 500  # 已结案观测的保留上限（FIFO）


class ResponseProbe:
    """复习推送的响应率观测器。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 观测状态文件（<state_dir>/response_probe.json）。
    """

    def __init__(self, memory_tree: MemoryTree) -> None:
        """初始化。

        Args:
            memory_tree: MemoryTree 实例。
        """
        self.tree = memory_tree
        self.state_path = self.tree.state_dir / "response_probe.json"

    def register(
        self, items: List[Dict[str, Any]], now: Optional[datetime] = None
    ) -> None:
        """为刚推送的笔记建立观测（base_mtime 此刻快照）。

        同一笔记在旧观测未结案时被再次推送：旧观测按"未响应"结案
        （superseded），以新推送重新计时。

        Args:
            items: ResurfaceManager.candidates() 返回的条目（需含
                id/filename 键）。
            now: 推送时刻（测试用）；缺省当前时间。
        """
        if not items:
            return
        now = now or datetime.now().astimezone()
        state = self._load_state()
        for item in items:
            note_id = str(item["id"])
            old = state["pending"].pop(note_id, None)
            if old is not None:
                self._resolve(
                    state, old, note_id, False, now, reason="superseded"
                )
            path = self.tree.notes_dir / item["filename"]
            try:
                base_mtime = path.stat().st_mtime
            except OSError:
                continue  # 推送瞬间文件消失：无可观测对象，跳过
            state["pending"][note_id] = {
                "filename": item["filename"],
                "pushed_at": now.isoformat(timespec="seconds"),
                "base_mtime": base_mtime,
            }
        self._save_state(state)

    def check_pending(self, now: Optional[datetime] = None) -> Dict[str, int]:
        """检查观察中的笔记并结案到期观测（每日随晨报执行一次）。

        结案规则：mtime 变化 → 响应（edited）；文件消失 → 响应
        （removed，用户 purge 也是加工）；满 48h 无变化 → 未响应
        （expired）。

        Args:
            now: 检查时刻（测试用）；缺省当前时间。

        Returns:
            Dict[str, int]: {"resolved": 本轮结案数, "responded": 响应数}。
        """
        now = now or datetime.now().astimezone()
        state = self._load_state()
        resolved_count = 0
        responded_count = 0
        for note_id, obs in list(state["pending"].items()):
            path = self.tree.notes_dir / obs["filename"]
            pushed_at = parse_date(obs["pushed_at"])
            if not path.exists():
                self._resolve(state, obs, note_id, True, now, reason="removed")
                state["pending"].pop(note_id)
                resolved_count += 1
                responded_count += 1
                continue
            mtime = path.stat().st_mtime
            if mtime > obs["base_mtime"] + 1.0:
                delay_hours = round(
                    max(mtime - pushed_at.timestamp(), 0.0) / 3600, 1
                )
                self._resolve(
                    state, obs, note_id, True, now,
                    reason="edited", delay_hours=delay_hours,
                )
                state["pending"].pop(note_id)
                resolved_count += 1
                responded_count += 1
            elif now - pushed_at >= RESPONSE_WINDOW:
                self._resolve(state, obs, note_id, False, now, reason="expired")
                state["pending"].pop(note_id)
                resolved_count += 1
        if resolved_count:
            self._save_state(state)
        return {"resolved": resolved_count, "responded": responded_count}

    def summary(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """响应率统计（累计 + 近 7 天）。

        Returns:
            Dict: total/responded/rate/last7_total/last7_responded/
                last7_rate/pending；无结案数据时 rate 为 None。
        """
        now = now or datetime.now().astimezone()
        state = self._load_state()
        resolved = state["resolved"]
        total = len(resolved)
        responded = sum(1 for item in resolved if item["responded"])
        week_ago = now - timedelta(days=7)
        last7 = [
            item
            for item in resolved
            if parse_date(item["resolved_at"]) >= week_ago
        ]
        last7_responded = sum(1 for item in last7 if item["responded"])
        return {
            "total": total,
            "responded": responded,
            "rate": (responded / total) if total else None,
            "last7_total": len(last7),
            "last7_responded": last7_responded,
            "last7_rate": (last7_responded / len(last7)) if last7 else None,
            "pending": len(state["pending"]),
        }

    @staticmethod
    def _resolve(
        state: Dict[str, Any],
        obs: Dict[str, Any],
        note_id: str,
        responded: bool,
        now: datetime,
        *,
        reason: str,
        delay_hours: Optional[float] = None,
    ) -> None:
        """把一条观测追加进已结案列表（FIFO 截断到 MAX_RESOLVED）。"""
        state["resolved"].append(
            {
                "note_id": note_id,
                "filename": obs.get("filename"),
                "pushed_at": obs.get("pushed_at"),
                "resolved_at": now.isoformat(timespec="seconds"),
                "responded": responded,
                "reason": reason,
                "delay_hours": delay_hours,
            }
        )
        del state["resolved"][:-MAX_RESOLVED]

    def _load_state(self) -> Dict[str, Any]:
        """读取观测状态；缺失/损坏返回空态（观测丢了只影响统计）。"""
        empty: Dict[str, Any] = {"pending": {}, "resolved": []}
        if not self.state_path.exists():
            return dict(empty)
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return dict(empty)
        if not isinstance(data, dict):
            return dict(empty)
        data.setdefault("pending", {})
        data.setdefault("resolved", [])
        return data

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写观测状态：先写临时文件再 rename。"""
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.state_path)
