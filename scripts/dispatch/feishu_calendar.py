"""飞书日历事件（月度清理日 / 待办截止上日历）。

定位：
- 应用自建日历「Atelierr」：首次用时创建并把 calendar_id 登记在
  ``<state_dir>/feishu_calendar.json``；创建后把你的 open_id 加进
  ACL（writer），日历才会出现在你的飞书日历列表（open_id 识别与
  task_sync 同源：事件捕获缓存 / ``FEISHU_USER_ID`` 环境变量）；
- 只建全天事件（TimeInfo.date，起止同日）；任何失败只 log 返回
  False，绝不影响主流程（清理提醒卡、待办卡片照常）。

权限：``calendar:calendar``（后台开通后需发布新版本生效，见
docs/FEISHU-BOT.md）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from scripts.dispatch.feishu import _import_lark
from scripts.dispatch.task_sync import _client, load_user_open_id

CALENDAR_FILENAME = "feishu_calendar.json"
CALENDAR_SUMMARY = "Atelierr"


def _state_path(state_dir: Path) -> Path:
    return Path(state_dir) / CALENDAR_FILENAME


def _load_calendar_id(state_dir: Path) -> Optional[str]:
    """读取登记的 calendar_id；缺失/损坏返回 None。"""
    try:
        data = json.loads(_state_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("calendar_id") if isinstance(data, dict) else None
    return str(value) if value else None


def _save_calendar_id(state_dir: Path, calendar_id: str) -> None:
    path = _state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"calendar_id": calendar_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def ensure_calendar(state_dir: Path) -> Optional[str]:
    """确保「Atelierr」日历存在并对你可见；返回 calendar_id 或 None。

    已登记直接返回；否则创建 → 把你的 open_id 加进 ACL（不知道你的
    open_id 时日历只存在于应用侧，对你不可见——ACL 失败只 log，
    calendar_id 仍登记，补上身份后删 state 文件重建即可）。
    """
    existing = _load_calendar_id(state_dir)
    if existing:
        return existing
    try:
        lark = _import_lark()
        client = _client()
        request = (
            lark.api.calendar.v4.CreateCalendarRequest.builder()
            .request_body(
                lark.api.calendar.v4.Calendar.builder()
                .summary(CALENDAR_SUMMARY)
                .description("Atelierr 系统事件（月度清理日 / 待办截止）")
                .permissions("private")
                .build()
            )
            .build()
        )
        response = client.calendar.v4.calendar.create(request)
        if not response.success():
            print("[feishu] calendar create fail", flush=True)
            return None
        calendar_id = getattr(
            getattr(getattr(response, "data", None), "calendar", None),
            "calendar_id",
            None,
        )
        if not calendar_id:
            return None
        calendar_id = str(calendar_id)
        _save_calendar_id(state_dir, calendar_id)
        _share_calendar(lark, client, state_dir, calendar_id)
        print(f"[feishu] calendar created: {calendar_id}", flush=True)
        return calendar_id
    except Exception as exc:  # noqa: BLE001 - 日历失败绝不影响主流程
        print(f"[feishu] calendar create fail: {exc}", flush=True)
        return None


def _share_calendar(lark: Any, client: Any, state_dir: Path, calendar_id: str) -> None:
    """把你的 open_id 加进日历 ACL（writer）；身份未知或失败只 log。"""
    open_id = load_user_open_id(Path(state_dir))
    if not open_id:
        print(
            "[feishu] 未识别你的 open_id，日历未共享（发条消息给机器人后"
            "删除 state/feishu_calendar.json 重建即可）",
            flush=True,
        )
        return
    try:
        acl = (
            lark.api.calendar.v4.CalendarAcl.builder()
            .role("writer")
            .scope(
                lark.api.calendar.v4.AclScope.builder()
                .type("user")
                .user_id(open_id)
                .build()
            )
            .build()
        )
        request = (
            lark.api.calendar.v4.CreateCalendarAclRequest.builder()
            .calendar_id(calendar_id)
            .user_id_type("open_id")
            .request_body(acl)
            .build()
        )
        if not client.calendar.v4.calendar_acl.create(request).success():
            print(f"[feishu] calendar acl fail: {calendar_id}", flush=True)
    except Exception as exc:  # noqa: BLE001 - 共享失败不阻塞日历使用
        print(f"[feishu] calendar acl fail: {exc}", flush=True)


def create_all_day_event(
    state_dir: Path,
    summary: str,
    date_str: str,
    description: str = "",
) -> bool:
    """在「Atelierr」日历建一个全天事件；失败只 log 返回 False。

    Args:
        state_dir: 机器状态目录。
        summary: 事件标题。
        date_str: 日期 ``YYYY-MM-DD``（全天事件起止同日）。
        description: 事件描述（可空）。

    Returns:
        bool: 建成返回 True。
    """
    if not summary or not date_str:
        return False
    try:
        lark = _import_lark()
        calendar_id = ensure_calendar(Path(state_dir))
        if not calendar_id:
            return False
        client = _client()
        event = (
            lark.api.calendar.v4.CalendarEvent.builder()
            .summary(summary)
            .description(description)
            .start_time(lark.api.calendar.v4.TimeInfo.builder().date(date_str).build())
            .end_time(lark.api.calendar.v4.TimeInfo.builder().date(date_str).build())
            .build()
        )
        request = (
            lark.api.calendar.v4.CreateCalendarEventRequest.builder()
            .calendar_id(calendar_id)
            .user_id_type("open_id")
            .request_body(event)
            .build()
        )
        response = client.calendar.v4.calendar_event.create(request)
        if not response.success():
            print(f"[feishu] event create fail: {summary}", flush=True)
            return False
        print(f"[feishu] event created: {summary} @ {date_str}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - 建事件失败绝不影响主流程
        print(f"[feishu] event create fail: {exc}", flush=True)
        return False
