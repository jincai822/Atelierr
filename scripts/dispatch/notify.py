"""ntfy 推送：只在"用户不知道的事"发生时提醒（通知只报数量，不含笔记内容）。

推送规则（dispatch_cli 接线）：
- 链接抓取失败 → "Atelierr 抓取失败"（不推用户无从知晓）；
- 晨间摘要创建成功 → "Atelierr 今日摘要"（附三节计数）；
- 常规处理成功不推送（用户自己贴的链接，无需马后炮）。

配置节 ``dispatch.notify``（config/processors.yaml 或 .example）：

    dispatch:
      notify:
        ntfy_url: https://ntfy.sh     # 或自托管实例
        topic: <随机长串>              # 主题名即口令，勿用可猜名字

未配置（topic 缺失）时静默跳过；推送失败只记日志式返回 False，
绝不影响分发主流程。
"""

from __future__ import annotations

from email.header import Header
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import yaml

from scripts.processors.base import CONFIG_FILES


def load_notify_config() -> Dict[str, Any]:
    """读取配置文件 ``dispatch.notify`` 节（缺失/损坏返回空表）。"""
    for config_file in CONFIG_FILES:
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            section = data.get("dispatch")
            if isinstance(section, dict) and isinstance(section.get("notify"), dict):
                return dict(section["notify"])
    return {}


def send_ntfy(
    title: str, message: str, config: Optional[dict] = None
) -> bool:
    """发一条 ntfy 推送；未配置或失败返回 False（绝不抛异常）。

    Args:
        title: 通知标题。
        message: 通知正文（只放数量等非敏感信息）。
        config: dispatch.notify 配置节；缺省按配置文件加载。

    Returns:
        bool: 推送成功且服务端 2xx 返回 True。
    """
    cfg = config if config is not None else load_notify_config()
    ntfy_url = str(cfg.get("ntfy_url") or "").strip()
    topic = str(cfg.get("topic") or "").strip()
    if not ntfy_url or not topic:
        return False
    try:
        # HTTP 头只支持 latin-1，中文标题按 RFC 2047 编码（ntfy 官方约定）
        encoded_title = Header(title, "utf-8").encode()
        response = httpx.post(
            f"{ntfy_url.rstrip('/')}/{topic}",
            content=message.encode("utf-8"),
            headers={"Title": encoded_title, "Tags": "memo"},
            timeout=10,
        )
        return response.status_code < 300
    except Exception:  # noqa: BLE001 - 推送失败不影响主流程
        return False
