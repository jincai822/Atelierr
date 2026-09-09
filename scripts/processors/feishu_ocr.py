"""飞书云端 OCR（image 处理器的可选引擎 ``feishu``）。

- 接口：``basic_recognize``（按区域返回文本列表，无逐行置信度——
  调用方统一按 1.0 计）；单租户 20 QPS；
- **隐私代价**：图片会上传到飞书云端识别。敏感截图请用本地引擎
  （paddleocr / rapidocr，默认）；本引擎适合快速、不占本机 CPU/GPU
  的非敏感图片；
- 凭证走环境变量 ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET``
  （与飞书桥同源；tenant_access_token 模块内缓存，提前 5 分钟换）；
- 任何失败抛 RuntimeError（由 ImageProcessor 转成 success=False）。

单元测试 monkeypatch ``httpx.post``，无真实网络。
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import List, Union

import httpx

_BASE = "https://open.feishu.cn/open-apis"
_TOKEN_URL = f"{_BASE}/auth/v3/tenant_access_token/internal"
_OCR_URL = f"{_BASE}/optical_char_recognition/v1/images/basic_recognize"

#: tenant_access_token 模块内缓存（有效期约 2h，提前 5 分钟换）
_TOKEN_CACHE = {"token": "", "expires_at": 0.0}


def _tenant_token(timeout: float) -> str:
    """取 tenant_access_token（带缓存）；凭证缺失/请求失败抛 RuntimeError。"""
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"]:
        return _TOKEN_CACHE["token"]
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("缺少飞书凭证 FEISHU_APP_ID / FEISHU_APP_SECRET")
    response = httpx.post(
        _TOKEN_URL,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    data = response.json()
    token = data.get("tenant_access_token")
    if response.status_code != 200 or not token:
        raise RuntimeError(f"飞书 token 获取失败: {data.get('msg') or response.status_code}")
    expire = float(data.get("expire") or 7200)
    _TOKEN_CACHE["token"] = str(token)
    _TOKEN_CACHE["expires_at"] = now + max(expire - 300, 60)
    return _TOKEN_CACHE["token"]


def recognize_texts(
    image_path: Union[str, Path], timeout: float = 30.0
) -> List[str]:
    """识别图片文字，返回文本行列表（无置信度）；失败抛 RuntimeError。

    Args:
        image_path: 图片路径（jpg/png/webp 等飞书支持格式）。
        timeout: 单次 HTTP 超时秒数。

    Returns:
        List[str]: 识别文本行（可能为空表）。

    Raises:
        RuntimeError: 凭证缺失、网络失败或飞书返回错误码。
    """
    token = _tenant_token(timeout)
    blob = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    response = httpx.post(
        _OCR_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"image": blob},
        timeout=timeout,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"飞书 OCR 响应非 JSON: {response.status_code}") from exc
    if response.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"飞书 OCR 失败: {data.get('msg') or response.status_code}")
    texts = (data.get("data") or {}).get("text_list") or []
    return [str(text) for text in texts if str(text).strip()]
