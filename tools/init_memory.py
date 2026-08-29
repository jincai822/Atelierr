#!/usr/bin/env python3
"""Atelierr 记忆目录初始化工具（幂等）。

读取 config/memory.yaml（可用 --config 覆盖；文件不存在时回退到
~/atelierr-data 默认路径），按 MemoryTree 的配置语义取
memory.root / memory.state_dir，创建：

- 平面笔记目录（memory.root，Flatnotes 挂载点）
- 状态目录（memory.state_dir，含 reports/ 与 trash/ 子目录）
- inbox 目录（notes_dir 的同级兄弟，待处理输入入口）

已存在的目录打印"已存在"，新建的打印"创建"；退出码 0。

用法:
    python tools/init_memory.py
    python tools/init_memory.py --config /path/to/memory.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# 直接运行（python tools/init_memory.py）时保证 scripts 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.utils.config import load_config  # noqa: E402

#: 默认配置文件（与 memory_cli 的配置链一致）
DEFAULT_CONFIG = "config/memory.yaml"
#: 无配置时的默认笔记目录（与 MemoryTree.from_config 缺省一致）
DEFAULT_ROOT = "~/atelierr-data/memory"
#: 无配置时的默认状态目录
DEFAULT_STATE_DIR = "~/atelierr-data/state"


def _resolve_paths(config_path: Optional[str]) -> Tuple[Path, Path]:
    """按配置解析笔记目录与状态目录。

    与 MemoryTree 相同语义：读取 ``memory.root`` / ``memory.state_dir``，
    缺失字段回退到 ~/atelierr-data 默认值。

    Args:
        config_path: YAML 配置文件路径；None 时直接用默认路径。

    Returns:
        Tuple[Path, Path]: (笔记目录, 状态目录)。
    """
    if config_path is None:
        return Path(DEFAULT_ROOT).expanduser(), Path(DEFAULT_STATE_DIR).expanduser()
    memory = load_config(config_path).get("memory", {}) or {}
    root = Path(memory.get("root", DEFAULT_ROOT)).expanduser()
    state_dir = Path(memory.get("state_dir", DEFAULT_STATE_DIR)).expanduser()
    return root, state_dir


def _ensure_dir(path: Path) -> str:
    """幂等创建目录。

    Args:
        path: 目标目录路径。

    Returns:
        str: "创建"（本次新建）或 "已存在"（此前已有）。
    """
    if path.is_dir():
        return "已存在"
    path.mkdir(parents=True, exist_ok=True)
    return "创建"


def main(argv: Optional[List[str]] = None) -> int:
    """解析参数并幂等创建目录结构。

    Args:
        argv: 命令行参数列表；None 时用 sys.argv[1:]。

    Returns:
        int: 退出码（0 成功）。
    """
    parser = argparse.ArgumentParser(description="初始化 Atelierr 记忆目录结构")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"配置文件路径（默认 {DEFAULT_CONFIG}；不存在时回退默认路径）",
    )
    args = parser.parse_args(argv)

    # 配置文件缺失不是错误：按 MemoryTree 语义回退默认路径
    config_path: Optional[str] = args.config
    if config_path is not None and not Path(config_path).is_file():
        config_path = None

    root, state_dir = _resolve_paths(config_path)
    targets: List[Tuple[Path, str]] = [
        (root, "平面笔记目录"),
        (state_dir, "状态目录（sidecar 索引 / 报告 / 回收站）"),
        (state_dir / "reports", "衰减报告目录"),
        (state_dir / "trash", "回收站目录"),
        (root.parent / "inbox", "待处理输入目录"),
    ]
    for path, _purpose in targets:
        print(f"✅ {_ensure_dir(path)}目录: {path}")

    print("✅ 初始化完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
