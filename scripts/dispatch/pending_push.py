"""确认卡分级队列（2026-09-13 用户裁决，捕获评审毛病 1：确认端减负）。

规则：发链接/剪藏时**写了评论/备注**的（意图信号最强）→ 即时单卡推送；
**没写评论**的 → 不单独推，入队攒到晚间「今日待确认清单」一张卡批量
处理（atelierr-pending.timer 21:17 触发 ``dispatch_cli pending``）。

队列是 sidecar 里的一个 JSON 文件（pending_push.json），文件级解耦：
入队方（dispatch_cli links / clips）与出队方（dispatch_cli pending）
互不知晓。出队时过滤已不在库/已确认的条目（用户可能已在 Obsidian
处理过），只推仍待确认的；卡片每条带「✅ 确认并归档」按钮（复用
FeishuBridge 的 archive_note 回调）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import frontmatter

from scripts.dispatch.feishu_cards import send_pending_digest_feishu

#: 清单卡单卡最多条目（防超长卡；超出留到下轮）
MAX_ITEMS = 20


def _queue_path(state_dir: Path) -> Path:
    return Path(state_dir) / "pending_push.json"


def _load(state_dir: Path) -> List[Dict[str, Any]]:
    import json

    path = _queue_path(state_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("file")]


def _save(state_dir: Path, items: List[Dict[str, Any]]) -> None:
    import json
    import os

    path = _queue_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def enqueue(state_dir: Path, rel: str, kind: str = "link") -> None:
    """入队（幂等：同 rel 不重复）。

    Args:
        state_dir: sidecar 目录（tree.state_dir）。
        rel: 笔记相对 memory/ 的路径。
        kind: 来源类型（link/clip），仅作记录。
    """
    items = _load(state_dir)
    if any(item["file"] == rel for item in items):
        return
    items.append(
        {
            "file": rel,
            "kind": kind,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save(state_dir, items)


def _still_pending(notes_dir: Path, rel: str) -> bool:
    """文件在且仍带「待确认」标签才推（用户可能已在 Obsidian 处理过）。"""
    path = Path(notes_dir) / rel
    if not path.exists():
        return False
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 损坏文件不推，但也不留着占队
        return False
    tags = [str(tag) for tag in (post.get("tags") or [])]
    return "待确认" in tags


def flush(tree, send_card=None) -> Dict[str, Any]:
    """出队推晚间清单卡：过滤已解决条目，组卡发送，成功才出队。

    Args:
        tree: MemoryTree 实例。
        send_card: 推送回调（缺省 send_pending_digest_feishu；测试注入）。

    Returns:
        Dict[str, Any]: {"queued", "pending", "resolved", "sent"}。
    """
    items = _load(tree.state_dir)
    report = {"queued": len(items), "pending": 0, "resolved": 0, "sent": False}
    if not items:
        return report
    still = [
        item["file"]
        for item in items
        if _still_pending(tree.notes_dir, item["file"])
    ]
    pending = still[:MAX_ITEMS]
    overflow = still[MAX_ITEMS:]
    report["resolved"] = len(items) - len(still)
    report["pending"] = len(pending)
    if not pending:
        _save(tree.state_dir, [])
        return report
    sender = send_card or send_pending_digest_feishu
    try:
        ok = bool(sender(pending))
    except Exception:  # noqa: BLE001 - 推送失败留队下轮再试
        ok = False
    report["sent"] = ok
    # 已解决条目永远出队；已推送条目成功才出队；超出单卡上限的留队
    if ok:
        _save(tree.state_dir, [item for item in items if item["file"] in overflow])
    else:
        _save(tree.state_dir, [item for item in items if item["file"] in still])
    return report
