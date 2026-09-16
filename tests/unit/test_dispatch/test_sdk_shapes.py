"""lark_oapi SDK 形状离线烟测（不联网）。

我们调用飞书 API 全靠 SDK builder 链；SDK 升级一旦改名/换签名，
运行时异常会被各处的 except 吞掉，功能静默失效。本文件用**真实的**
lark_oapi 把代码里用到的每条 builder 链实例化一遍——升级 SDK 后
跑测试即可立即暴露形状漂移。只构造对象，不发任何网络请求。
"""

from __future__ import annotations

import pytest

lark = pytest.importorskip("lark_oapi", reason="lark-oapi 未安装")


def test_event_dispatch_and_ws_shapes():
    """长连接：事件分发器注册五个处理器 + ws.Client 可构造（不 start）。"""
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(lambda data: None)
        .register_p2_im_message_message_read_v1(lambda data: None)
        .register_p2_im_message_reaction_created_v1(lambda data: None)
        .register_p2_im_message_reaction_deleted_v1(lambda data: None)
        .register_p2_card_action_trigger(lambda data: {})
        .build()
    )
    assert handler is not None
    client = lark.ws.Client(
        "cli_x", "secret", event_handler=handler, log_level=lark.LogLevel.WARNING
    )
    assert client is not None


def test_im_message_send_shape():
    """发消息（interactive/text 共用一个形状）。"""
    body = (
        lark.api.im.v1.CreateMessageRequestBody.builder()
        .receive_id("oc_chat")
        .msg_type("interactive")
        .content("{}")
        .build()
    )
    request = (
        lark.api.im.v1.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(body)
        .build()
    )
    assert request is not None


def test_im_reaction_pin_resource_shapes():
    """表情回执 / 置顶摘取 / 附件下载。"""
    reaction_body = (
        lark.api.im.v1.CreateMessageReactionRequestBody.builder()
        .reaction_type(
            lark.api.im.v1.Emoji.builder().emoji_type("DONE").build()
        )
        .build()
    )
    assert (
        lark.api.im.v1.CreateMessageReactionRequest.builder()
        .message_id("om_1")
        .request_body(reaction_body)
        .build()
        is not None
    )
    pin_body = (
        lark.api.im.v1.CreatePinRequestBody.builder().message_id("om_1").build()
    )
    assert (
        lark.api.im.v1.CreatePinRequest.builder().request_body(pin_body).build()
        is not None
    )
    assert (
        lark.api.im.v1.DeletePinRequest.builder().message_id("om_1").build()
        is not None
    )
    assert (
        lark.api.im.v1.GetMessageResourceRequest.builder()
        .message_id("om_1")
        .file_key("fk")
        .type("image")
        .build()
        is not None
    )


def test_task_v2_shapes():
    """任务：建（summary/members/due）与完成回写（completed_at patch）。"""
    task = (
        lark.api.task.v2.InputTask.builder()
        .summary("测试")
        .members(
            [
                lark.api.task.v2.Member.builder()
                .id("ou_1")
                .type("user")
                .role("assignee")
                .build()
            ]
        )
        .due(
            lark.api.task.v2.Due.builder()
            .timestamp(1814400000)
            .is_all_day(True)
            .build()
        )
        .build()
    )
    assert (
        lark.api.task.v2.CreateTaskRequest.builder()
        .user_id_type("open_id")
        .request_body(task)
        .build()
        is not None
    )
    patch_body = (
        lark.api.task.v2.PatchTaskRequestBody.builder()
        .task(
            lark.api.task.v2.InputTask.builder().completed_at(1789000000).build()
        )
        .update_fields(["completed_at"])
        .build()
    )
    assert (
        lark.api.task.v2.PatchTaskRequest.builder()
        .task_guid("guid-1")
        .user_id_type("open_id")
        .request_body(patch_body)
        .build()
        is not None
    )


def test_calendar_v4_shapes():
    """日历：建日历 / ACL 共享 / 全天事件。"""
    calendar = (
        lark.api.calendar.v4.Calendar.builder()
        .summary("Atelierr")
        .description("d")
        .permissions("private")
        .build()
    )
    assert (
        lark.api.calendar.v4.CreateCalendarRequest.builder()
        .request_body(calendar)
        .build()
        is not None
    )
    acl = (
        lark.api.calendar.v4.CalendarAcl.builder()
        .role("writer")
        .scope(
            lark.api.calendar.v4.AclScope.builder()
            .type("user")
            .user_id("ou_1")
            .build()
        )
        .build()
    )
    assert (
        lark.api.calendar.v4.CreateCalendarAclRequest.builder()
        .calendar_id("cal-1")
        .user_id_type("open_id")
        .request_body(acl)
        .build()
        is not None
    )
    event = (
        lark.api.calendar.v4.CalendarEvent.builder()
        .summary("s")
        .description("d")
        .start_time(
            lark.api.calendar.v4.TimeInfo.builder().date("2026-09-12").build()
        )
        .end_time(
            lark.api.calendar.v4.TimeInfo.builder().date("2026-09-12").build()
        )
        .build()
    )
    assert (
        lark.api.calendar.v4.CreateCalendarEventRequest.builder()
        .calendar_id("cal-1")
        .user_id_type("open_id")
        .request_body(event)
        .build()
        is not None
    )


def test_bitable_v1_shapes():
    """多维表格：建应用 / 建表（字段头）/ 批量新增 / 批量更新。"""
    assert (
        lark.api.bitable.v1.CreateAppRequest.builder()
        .request_body(
            lark.api.bitable.v1.ReqApp.builder().name("看板").build()
        )
        .build()
        is not None
    )
    table_body = (
        lark.api.bitable.v1.CreateAppTableRequestBody.builder()
        .table(
            lark.api.bitable.v1.ReqTable.builder()
            .name("notes")
            .default_view_name("全部")
            .fields(
                [
                    lark.api.bitable.v1.AppTableCreateHeader.builder()
                    .field_name("标题")
                    .type(1)
                    .build()
                ]
            )
            .build()
        )
        .build()
    )
    assert (
        lark.api.bitable.v1.CreateAppTableRequest.builder()
        .app_token("app-1")
        .request_body(table_body)
        .build()
        is not None
    )
    create_body = (
        lark.api.bitable.v1.BatchCreateAppTableRecordRequestBody.builder()
        .records(
            [
                lark.api.bitable.v1.AppTableRecord.builder()
                .fields({"标题": "x"})
                .build()
            ]
        )
        .build()
    )
    assert (
        lark.api.bitable.v1.BatchCreateAppTableRecordRequest.builder()
        .app_token("app-1")
        .table_id("tbl-1")
        .request_body(create_body)
        .build()
        is not None
    )
    update_body = (
        lark.api.bitable.v1.BatchUpdateAppTableRecordRequestBody.builder()
        .records(
            [
                lark.api.bitable.v1.AppTableRecord.builder()
                .record_id("rec-1")
                .fields({"标题": "y"})
                .build()
            ]
        )
        .build()
    )
    assert (
        lark.api.bitable.v1.BatchUpdateAppTableRecordRequest.builder()
        .app_token("app-1")
        .table_id("tbl-1")
        .request_body(update_body)
        .build()
        is not None
    )


def test_drive_permission_member_shape():
    """云文档权限：把你加成看板协作者。"""
    member = (
        lark.api.drive.v1.BaseMember.builder()
        .member_type("openid")
        .member_id("ou_1")
        .perm("full_access")
        .build()
    )
    assert (
        lark.api.drive.v1.CreatePermissionMemberRequest.builder()
        .token("app-1")
        .type("bitable")
        .need_notification(False)
        .request_body(member)
        .build()
        is not None
    )
