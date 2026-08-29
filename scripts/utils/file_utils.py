"""文件系统小工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Union


def ensure_dir(path: Union[str, Path]) -> Path:
    """确保目录存在并返回其 Path（不存在则递归创建）。

    Args:
        path: 目录路径（可含 ~ 展开）。

    Returns:
        Path: 展开后的目录路径。

    Examples:
        >>> ensure_dir("/tmp/atelierr/state")
        PosixPath('/tmp/atelierr/state')
    """
    directory = Path(path).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
