"""飞书交互式问答：待答问题会话（pending prompt）。

周回顾等反思流程的交互环节在 CLI 里体验差——改为在飞书里提问、
用户用日常聊天直接回答。本模块是一个轻量状态机：

- ``dispatch_cli prompt open <kind> <问题文本>``：把问题推到飞书并
  在 ``<state_dir>/pending_prompt.json`` 登记 open 会话
  （kind/questions/asked_at/answers）；
- 会话 open 期间，飞书桥把收到的**文本**消息当回答追加进状态
  （不再捕获为笔记），并回执「已收到（第 N 条）」；图片/文件
  消息不受影响，照常进 attachments/；
- 用户回「跳过」/「完成」即关闭会话；``dispatch_cli prompt collect``
  汇总打印答案（JSON）并关闭，供调用方（如周回顾流程）落盘。

纪律（与 dispatch 模块同源）：
- 只写 ``<state_dir>/pending_prompt.json``，绝不碰笔记文件；
- 同一时间最多一个 open 会话（周回顾是低频仪式，无需并发）；
- 状态文件损坏按无会话处理（绝不中断飞书守护）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 关闭会话的关键词（用户回复其一即结束问答，不计入答案）
CLOSE_WORDS = frozenset({"跳过", "完成", "skip", "done"})

STATE_FILENAME = "pending_prompt.json"


class PromptStore:
    """待答问题会话存储（单会话，JSON 文件）。

    Attributes:
        state_path: 状态文件路径（``<state_dir>/pending_prompt.json``）。
    """

    def __init__(self, state_dir: Path) -> None:
        """初始化。

        Args:
            state_dir: 机器状态目录（MemoryTree.state_dir）。
        """
        self.state_path = Path(state_dir) / STATE_FILENAME

    def load(self) -> Optional[Dict[str, Any]]:
        """读状态；文件不存在或损坏返回 None（按无会话处理）。"""
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def is_open(self) -> bool:
        """是否有 open 会话。"""
        data = self.load()
        return bool(data) and data.get("status") == "open"

    def open(self, kind: str, questions: List[str]) -> None:
        """开启新会话（覆盖任何残留状态——同时只会有一个仪式在跑）。

        Args:
            kind: 会话类型标记（weekly/daily 等，供 collect 方识别）。
            questions: 问题列表（原文，仅存档展示用）。
        """
        self._save(
            {
                "status": "open",
                "kind": kind,
                "questions": list(questions),
                "asked_at": datetime.now(timezone.utc).isoformat(),
                "answers": [],
            }
        )

    def append(self, text: str) -> int:
        """追加一条回答，返回累计条数；无 open 会话时返回 0（不写盘）。"""
        data = self.load()
        if not data or data.get("status") != "open":
            return 0
        answers = data.setdefault("answers", [])
        answers.append(
            {
                "text": text,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save(data)
        return len(answers)

    def close(self) -> Optional[Dict[str, Any]]:
        """关闭会话并返回最终状态（含全部答案）；无会话返回 None。"""
        data = self.load()
        if not data:
            return None
        data["status"] = "closed"
        data["closed_at"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        """原子写状态文件。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.state_path)
