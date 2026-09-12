"""文件系统小工具。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


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


def write_text_skip_existing(target: Union[str, Path], text: str) -> bool:
    """原子写入文本；目标已存在跳过（同内容重跑幂等，绝不覆盖）。

    供 dispatch 层落盘 attachments 全文文件（links/media 两管线共用，
    2026-09-12 方案 B）：父目录自动创建，tmp+os.replace 原子替换；
    写入失败只记日志返回 False（调用方决定流程，绝不抛异常阻断建卡）。

    Args:
        target: 目标文件路径。
        text: 文本内容（UTF-8）。

    Returns:
        bool: True=本次写入，False=已存在跳过或写入失败。
    """
    path = Path(target)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        logger.warning("原子写入失败 %s: %s", path, exc)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
