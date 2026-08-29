"""配置加载工具：YAML 配置文件读取与深层取值。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(path: str) -> dict:
    """加载 YAML 配置文件。

    Args:
        path: 配置文件路径。

    Returns:
        dict: 解析后的配置字典；空文件返回 {}。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
        yaml.YAMLError: 文件内容不是合法 YAML 时抛出。

    Examples:
        >>> load_config("config/memory.yaml")
        {'memory': {'root': '~/atelierr-data/memory'}}
    """
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    text = config_path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def deep_get(data: Dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """按点分路径从嵌套字典取值。

    Args:
        data: 嵌套字典。
        dotted_key: 点分路径，如 "memory.decay.rate"。
        default: 路径不存在时返回的默认值。

    Returns:
        Any: 路径对应的值，或 default。

    Examples:
        >>> deep_get({"a": {"b": {"c": 1}}}, "a.b.c")
        1
        >>> deep_get({"a": {}}, "a.b", default=5)
        5
    """
    current: Any = data
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
