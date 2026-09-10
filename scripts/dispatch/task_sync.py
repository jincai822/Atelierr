"""待办 → 飞书任务单向同步（创建 / 完成回写）。

定位：
- 待办笔记（dispatch/todos.py 产出）入库后，同步建一条飞书任务
  （assignee = 你），带截止日期的到点由飞书原生提醒——待办不再只是
  Obsidian 里的标签；点待办卡「✅ 已完成」时回写任务完成；
- 单向（Obsidian → 飞书）：在飞书任务面板里完成/删除**不**回写笔记
  （笔记侧的完成语义仍是「待办」标签，由 ✅ 按钮或手工摘除）；
- 身份识别：你的 open_id 来自你给机器人发消息/点按钮时事件里的
  sender/operator（零额外权限），缓存在
  ``<state_dir>/feishu_account.json``；也可用环境变量
  ``FEISHU_USER_ID`` 直接指定（优先级更高）；两者都没有则跳过建任务
  （没有 assignee 的任务对你不可见，不如不建，日志会提示）；
- 任务 guid 登记 ``<state_dir>/feishu_tasks.json``（文件名 → guid），
  供完成回写定位；任何 API 失败只 log，绝不影响待办主流程。

权限：``task:task:write``（后台开通后需发布新版本生效，见
docs/FEISHU-BOT.md）。凭证走环境变量（FEISHU_APP_ID/SECRET）。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from scripts.dispatch.feishu import ENV_APP_ID, ENV_APP_SECRET, _import_lark
from scripts.utils.state_store import read_json, write_json

#: 环境变量：直接指定用户 open_id（免事件捕获）
ENV_USER_ID = "FEISHU_USER_ID"

ACCOUNT_FILENAME = "feishu_account.json"
TASKS_FILENAME = "feishu_tasks.json"


# ---- 用户身份（open_id） --------------------------------------------------


def record_user_open_id(state_dir: Path, open_id: str) -> None:
    """缓存用户 open_id（事件 sender/operator 里带来，零额外权限）。

    **先到先得**：已有缓存值时不覆盖——单租户个人机器人，第一个互动者
    即主人；之后的异常身份（群聊混入、误发）改不动主人归属。换绑只能
    手工删 state 文件或配 ``FEISHU_USER_ID``（环境变量读取优先级更高）。
    失败只 log。
    """
    open_id = str(open_id or "").strip()
    if not open_id:
        return
    path = Path(state_dir) / ACCOUNT_FILENAME
    if load_user_open_id(state_dir, use_env=False) is not None:
        return
    try:
        write_json(path, {"user_open_id": open_id})
    except OSError as exc:
        print(f"[feishu] record open_id fail: {exc}", flush=True)


def load_user_open_id(state_dir: Path, use_env: bool = True) -> Optional[str]:
    """读取用户 open_id：``FEISHU_USER_ID`` 环境变量优先，其次缓存。"""
    if use_env:
        env_value = os.environ.get(ENV_USER_ID, "").strip()
        if env_value:
            return env_value
    path = Path(state_dir) / ACCOUNT_FILENAME
    data = read_json(path, None)
    value = data.get("user_open_id") if isinstance(data, dict) else None
    return str(value) if value else None


def sender_open_id(sender: Any) -> Optional[str]:
    """从消息事件 sender / 卡片回调 operator 里取 open_id（鸭子类型）。

    消息事件：``sender.sender_id.open_id``；卡片回调 operator 直接带
    ``open_id``。兼容 dict 负载；取不到返回 None。
    """
    if sender is None:
        return None
    if isinstance(sender, dict):
        nested = sender.get("sender_id")
        if isinstance(nested, dict) and nested.get("open_id"):
            return str(nested["open_id"])
        value = sender.get("open_id")
        return str(value) if value else None
    sender_id = getattr(sender, "sender_id", None)
    value = getattr(sender_id, "open_id", None) or getattr(sender, "open_id", None)
    return str(value) if value else None


# ---- 任务登记表 ------------------------------------------------------------


def _load_tasks(state_dir: Path) -> Dict[str, str]:
    """读取 文件名 → task_guid 映射；缺失/损坏返回空表。"""
    data = read_json(Path(state_dir) / TASKS_FILENAME, {})
    tasks = data.get("tasks") if isinstance(data, dict) else None
    return dict(tasks) if isinstance(tasks, dict) else {}


def _save_tasks(state_dir: Path, tasks: Dict[str, str]) -> None:
    """原子写登记表（scripts/utils/state_store 统一实现）。"""
    write_json(Path(state_dir) / TASKS_FILENAME, {"tasks": tasks}, indent=2)


def _client() -> Any:
    """按环境变量构造 lark client（凭证缺失抛 RuntimeError）。"""
    app_id = os.environ.get(ENV_APP_ID, "").strip()
    app_secret = os.environ.get(ENV_APP_SECRET, "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("缺少飞书凭证")
    lark = _import_lark()
    return lark.Client.builder().app_id(app_id).app_secret(app_secret).build()


# ---- 创建 / 完成 ------------------------------------------------------------


def create_task_for_todo(
    state_dir: Path,
    filename: str,
    title: str,
    due: Optional[str] = None,
) -> bool:
    """为一条待办建飞书任务（assignee=你）；已建过跳过（幂等）。

    Args:
        state_dir: 机器状态目录。
        filename: 待办笔记文件名（登记表键）。
        title: 任务标题（待办文本）。
        due: 截止日 ``YYYY-MM-DD``（全天任务；None 不设截止）。

    Returns:
        bool: 建成（或已建）返回 True；凭证/身份缺失或 API 失败 False。
    """
    if not str(title or "").strip():
        return False
    tasks = _load_tasks(state_dir)
    if filename in tasks:
        return True
    open_id = load_user_open_id(Path(state_dir))
    if not open_id:
        print(
            "[feishu] 未识别你的 open_id，跳过建任务"
            "（先在飞书里给机器人发条消息，或配置 FEISHU_USER_ID）",
            flush=True,
        )
        return False
    try:
        lark = _import_lark()
        client = _client()
        builder = (
            lark.api.task.v2.InputTask.builder()
            .summary(str(title).strip())
            .members(
                [
                    lark.api.task.v2.Member.builder()
                    .id(open_id)
                    .type("user")
                    .role("assignee")
                    .build()
                ]
            )
        )
        if due:
            midnight = datetime.strptime(due, "%Y-%m-%d").timestamp()
            builder = builder.due(
                lark.api.task.v2.Due.builder()
                .timestamp(int(midnight))
                .is_all_day(True)
                .build()
            )
        request = (
            lark.api.task.v2.CreateTaskRequest.builder()
            .user_id_type("open_id")
            .request_body(builder.build())
            .build()
        )
        response = client.task.v2.task.create(request)
        if not response.success():
            print(f"[feishu] task create fail: {filename}", flush=True)
            return False
        guid = getattr(getattr(response, "data", None), "task", None)
        guid = getattr(guid, "guid", None)
        if not guid:
            return False
        tasks[filename] = str(guid)
        _save_tasks(Path(state_dir), tasks)
        print(f"[feishu] task created: {filename} -> {guid}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - 建任务失败绝不影响待办主流程
        print(f"[feishu] task create fail: {exc}", flush=True)
        return False


def complete_task_for_todo(state_dir: Path, filename: str) -> bool:
    """回写飞书任务完成（点「✅ 已完成」时）；无登记静默 False。"""
    tasks = _load_tasks(state_dir)
    guid = tasks.get(filename)
    if not guid:
        return False
    try:
        lark = _import_lark()
        client = _client()
        body = (
            lark.api.task.v2.PatchTaskRequestBody.builder()
            .task(
                lark.api.task.v2.InputTask.builder()
                .completed_at(int(time.time()))
                .build()
            )
            .update_fields(["completed_at"])
            .build()
        )
        request = (
            lark.api.task.v2.PatchTaskRequest.builder()
            .task_guid(guid)
            .user_id_type("open_id")
            .request_body(body)
            .build()
        )
        response = client.task.v2.task.patch(request)
        if not response.success():
            print(f"[feishu] task complete fail: {filename}", flush=True)
            return False
        print(f"[feishu] task completed: {filename}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - 回写失败只 log
        print(f"[feishu] task complete fail: {exc}", flush=True)
        return False
