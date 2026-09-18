"""MinerU 4.0 CLI 共享封装（2026-09-19 用户裁决：OCR 全面换 MinerU）。

图片（截图）与 PDF（含纯扫描件）统一走本机 mineru server 的
``mineru parse``；服务未运行/解析失败抛 RuntimeError，由调用方转成
success=False 的 ProcessResult。模型与档位由 mineru server 管理
（``mineru config set parse_server.local.mode managed`` 已就位）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union


def parse_document(
    path: Union[str, Path],
    *,
    tier: str = "basic",
    wait_s: int = 300,
    timeout_s: float = 320,
    pages: Optional[str] = None,
) -> str:
    """调 ``mineru parse`` 解析文档，返回 markdown 文本（含结构标记）。

    Args:
        path: 图片/PDF 路径。
        tier: 解析档位（flash/basic/standard/advanced）。
        wait_s: 服务侧等待解析完成的秒数上限。
        timeout_s: 进程级超时（应略大于 wait_s）。
        pages: PDF 页码（如 "1-5,8" 或 "all"）；None 用服务端默认。

    Returns:
        str: MinerU 的 markdown 输出。

    Raises:
        RuntimeError: 未安装 / 超时 / 解析失败。
    """
    mineru_bin = Path(sys.executable).parent / "mineru"
    cmd = [
        str(mineru_bin),
        "parse",
        str(path),
        "--tier",
        str(tier),
        "--wait",
        str(int(wait_s)),
    ]
    if pages:
        cmd += ["--pages", str(pages)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout_s))
    except FileNotFoundError as exc:
        raise RuntimeError("MinerU 未安装（venv 内无 mineru 可执行文件）") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"MinerU 解析超时（{timeout_s}s）") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"MinerU 解析失败: {proc.stderr.strip()[-200:]}")
    return proc.stdout


def strip_markers(stdout: str) -> List[str]:
    """把 MinerU parse 的 stdout 收成纯文本行：剥 HTML 注释与标题 # 号。"""
    texts: List[str] = []
    for ln in stdout.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("<!--"):
            continue
        ln = ln.lstrip("# ").strip()
        if ln:
            texts.append(ln)
    return texts
