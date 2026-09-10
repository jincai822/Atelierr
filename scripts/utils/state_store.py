"""JSON 状态文件的原子读写（dispatch 各模块共用的唯一实现）。

纪律（与 dispatch 同源）：
- 读：文件缺失/损坏/类型不符一律返回 default，绝不抛异常（状态文件
  损坏按无状态处理，绝不中断守护）；
- 写：临时文件 + rename 原子落盘（防 Syncthing/读者抢到半成品）；
  写失败清理临时文件后照常抛 OSError（调用方自己决定吞不吞）。

迁移约定：状态文件都是无版本 schemaless JSON；加键向后兼容，
改键含义时在对应模块 docstring 记一笔日期与原因。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional


def read_json(path: Path, default: Optional[Any] = None) -> Any:
    """读取 JSON 文件；缺失/损坏返回 default（不抛异常）。

    Args:
        path: 状态文件路径。
        default: 读取失败时的返回值（常用 {} 或 []）。

    Returns:
        Any: 解析结果；失败返回 default。
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def write_json(path: Path, data: Any, *, indent: Optional[int] = None) -> None:
    """原子写 JSON（临时文件 + rename）；失败清理临时文件后抛 OSError。

    Args:
        path: 目标路径（父目录自动创建）。
        data: 可 JSON 序列化的数据。
        indent: 缩进（None 为紧凑单行；状态文件给人看时传 2）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
