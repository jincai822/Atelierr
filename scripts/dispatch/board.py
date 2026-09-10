"""知识库看板：笔记元数据单向同步进飞书多维表格（Bitable）。

定位：
- 把 memory/ 全部笔记的元数据（标题/目录/标签/层级/confidence/创建
  日期）同步进一张多维表格，手机上用飞书表格/看板/日历视图翻库，
  相当于轻量"控制中台"；**单向**（Obsidian → 飞书），在表格里改
  不回写笔记（Obsidian 库仍是唯一事实源）；
- 首次同步自动建应用「Atelierr 知识库看板」+ 表「notes」，并把你
  加成协作者（full_access，open_id 识别与 task_sync 同源）；
  app_token/table_id 与 路径→record_id 映射登记在
  ``<state_dir>/feishu_board.json``，重复同步幂等（新增 batch_create、
  已有 batch_update）；已删笔记的记录**保留**不删（表格侧你可手动
  清理；机器不做删除动作，与笔记红线同源）；
- 仪表盘/图表在多维表格 UI 里手工配一次即可（API 建不了仪表盘）；
- 任何 API 失败只 log 并返回 None，绝不影响主流程。

权限：``bitable:app``（建表/记录）与 ``drive:drive``（把你加成协作
者；缺了只是你看不到看板，同步本身照常），后台开通后需发布新版本。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.feishu import _import_lark
from scripts.dispatch.task_sync import _client, load_user_open_id

BOARD_FILENAME = "feishu_board.json"
BOARD_APP_NAME = "Atelierr 知识库看板"
BOARD_TABLE_NAME = "notes"
#: 批量接口单批上限（API 限 500，留余量）
_BATCH = 400

#: 表结构（字段名, bitable 类型码）：1=文本 2=数字 5=日期
_FIELDS: List[Tuple[str, int]] = [
    ("标题", 1),
    ("路径", 1),
    ("目录", 1),
    ("标签", 1),
    ("层级", 1),
    ("confidence", 2),
    ("创建", 5),
]


class BoardSync:
    """memory/ → 多维表格的单向同步器。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 同步状态文件（feishu_board.json）。
    """

    def __init__(self, tree: Any) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例（读索引与笔记 frontmatter）。
        """
        self.tree = tree
        self.state_path = Path(tree.state_dir) / BOARD_FILENAME

    # ---- 状态 ------------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def board_url(app_token: str) -> str:
        """看板链接（feishu.cn/base 会按租户跳转到实际域名）。"""
        return f"https://feishu.cn/base/{app_token}"

    # ---- 主流程 ------------------------------------------------------------

    def sync(self) -> Optional[Dict[str, Any]]:
        """全量同步一轮；返回报告 dict，凭证缺失/失败返回 None。

        Returns:
            Optional[Dict[str, Any]]: {"created", "updated", "total",
            "url"}；失败 None。
        """
        try:
            lark = _import_lark()
            client = _client()
        except Exception as exc:  # noqa: BLE001 - 凭证缺失静默
            print(f"[board] client fail: {exc}", flush=True)
            return None
        state = self._load_state()
        app_token = state.get("app_token") or self._ensure_app(lark, client, state)
        if not app_token:
            return None
        if not state.get("shared"):
            # 建应用时没认出你（未共享）；现在认出就补共享，不用手工重建
            if self._share_app(lark, client, str(app_token)):
                state["shared"] = True
                self._save_state(state)
        table_id = state.get("table_id") or self._ensure_table(
            lark, client, state, app_token
        )
        if not table_id:
            return None
        rows = self._collect_rows()
        records = dict(state.get("records") or {})
        to_create = [row for row in rows if row["路径"] not in records]
        to_update = [row for row in rows if row["路径"] in records]
        created_ids = self._batch_create(lark, client, app_token, table_id, to_create)
        if created_ids is None:
            return None
        records.update(created_ids)
        if not self._batch_update(lark, client, app_token, table_id, to_update, records):
            return None
        state["records"] = records
        self._save_state(state)
        report = {
            "created": len(to_create),
            "updated": len(to_update),
            "total": len(rows),
            "url": self.board_url(app_token),
        }
        print(f"[board] synced: {report}", flush=True)
        return report

    # ---- 应用 / 表 ---------------------------------------------------------

    def _ensure_app(self, lark: Any, client: Any, state: Dict[str, Any]) -> Optional[str]:
        """建看板应用并登记 app_token；随后尝试把你加成协作者。"""
        try:
            request = (
                lark.api.bitable.v1.CreateAppRequest.builder()
                .request_body(
                    lark.api.bitable.v1.ReqApp.builder().name(BOARD_APP_NAME).build()
                )
                .build()
            )
            response = client.bitable.v1.app.create(request)
            if not response.success():
                print("[board] app create fail（权限 bitable:app 未开？）", flush=True)
                return None
            app_token = getattr(
                getattr(getattr(response, "data", None), "app", None), "app_token", None
            )
            if not app_token:
                return None
            state["app_token"] = str(app_token)
            state["shared"] = self._share_app(lark, client, str(app_token))
            self._save_state(state)
            print(f"[board] app created: {app_token}", flush=True)
            return str(app_token)
        except Exception as exc:  # noqa: BLE001 - 建应用失败只 log
            print(f"[board] app create fail: {exc}", flush=True)
            return None

    def _share_app(self, lark: Any, client: Any, app_token: str) -> bool:
        """把你的 open_id 加成看板协作者；身份未知或失败返回 False。"""
        open_id = load_user_open_id(self.tree.state_dir)
        if not open_id:
            print(
                "[board] 未识别你的 open_id，看板暂未共享"
                "（发条消息给机器人，下次同步自动补共享）",
                flush=True,
            )
            return False
        try:
            member = (
                lark.api.drive.v1.BaseMember.builder()
                .member_type("openid")
                .member_id(open_id)
                .perm("full_access")
                .build()
            )
            request = (
                lark.api.drive.v1.CreatePermissionMemberRequest.builder()
                .token(app_token)
                .type("bitable")
                .need_notification(False)
                .request_body(member)
                .build()
            )
            if not client.drive.v1.permission_member.create(request).success():
                print("[board] share fail（权限 drive:drive 未开？）", flush=True)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - 共享失败不阻塞同步
            print(f"[board] share fail: {exc}", flush=True)
            return False

    def _ensure_table(
        self, lark: Any, client: Any, state: Dict[str, Any], app_token: str
    ) -> Optional[str]:
        """建 notes 表（字段见 _FIELDS）并登记 table_id。"""
        try:
            headers = [
                lark.api.bitable.v1.AppTableCreateHeader.builder()
                .field_name(name)
                .type(type_code)
                .build()
                for name, type_code in _FIELDS
            ]
            body = (
                lark.api.bitable.v1.CreateAppTableRequestBody.builder()
                .table(
                    lark.api.bitable.v1.ReqTable.builder()
                    .name(BOARD_TABLE_NAME)
                    .default_view_name("全部")
                    .fields(headers)
                    .build()
                )
                .build()
            )
            request = (
                lark.api.bitable.v1.CreateAppTableRequest.builder()
                .app_token(app_token)
                .request_body(body)
                .build()
            )
            response = client.bitable.v1.app_table.create(request)
            if not response.success():
                print("[board] table create fail", flush=True)
                return None
            table_id = getattr(getattr(response, "data", None), "table_id", None)
            if not table_id:
                return None
            state["table_id"] = str(table_id)
            self._save_state(state)
            print(f"[board] table created: {table_id}", flush=True)
            return str(table_id)
        except Exception as exc:  # noqa: BLE001 - 建表失败只 log
            print(f"[board] table create fail: {exc}", flush=True)
            return None

    # ---- 行收集与批量写 ------------------------------------------------------

    def _collect_rows(self) -> List[Dict[str, Any]]:
        """从 sidecar 索引 + 笔记 frontmatter 收集行（跳过待删与 trash/）。"""
        rows: List[Dict[str, Any]] = []
        for entry in self.tree._load_index().values():
            relpath = str(entry.get("path") or "")
            if not relpath or relpath.startswith("trash/"):
                continue
            if entry.get("pending_delete"):
                continue
            rows.append(self._row(relpath, entry))
        return rows

    def _row(self, relpath: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        """单条索引 → 表格行（frontmatter 取不到就用文件名兜底）。"""
        path = Path(self.tree.notes_dir) / relpath
        title = path.stem
        tags: List[str] = []
        created_ms: Optional[int] = None
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            title = str(post.metadata.get("title") or title)
            tags = [str(tag) for tag in (post.metadata.get("tags") or [])]
            created_ms = _to_ms(post.metadata.get("created"))
        except Exception:  # noqa: BLE001 - 单篇读失败用兜底值
            pass
        top_dir = relpath.split("/", 1)[0] if "/" in relpath else "（根）"
        return {
            "标题": title,
            "路径": relpath,
            "目录": top_dir,
            "标签": ", ".join(tags),
            "层级": str(entry.get("layer") or ""),
            "confidence": round(float(entry.get("confidence") or 0.0), 2),
            "创建": created_ms,
        }

    def _batch_create(
        self,
        lark: Any,
        client: Any,
        app_token: str,
        table_id: str,
        rows: List[Dict[str, Any]],
    ) -> Optional[Dict[str, str]]:
        """批量新增；返回 路径→record_id 映射，失败 None。"""
        mapping: Dict[str, str] = {}
        for chunk in _chunks(rows, _BATCH):
            try:
                body = (
                    lark.api.bitable.v1.BatchCreateAppTableRecordRequestBody.builder()
                    .records(
                        [
                            lark.api.bitable.v1.AppTableRecord.builder()
                            .fields(row)
                            .build()
                            for row in chunk
                        ]
                    )
                    .build()
                )
                request = (
                    lark.api.bitable.v1.BatchCreateAppTableRecordRequest.builder()
                    .app_token(app_token)
                    .table_id(table_id)
                    .request_body(body)
                    .build()
                )
                response = client.bitable.v1.app_table_record.batch_create(request)
                if not response.success():
                    print("[board] batch create fail", flush=True)
                    return None
                items = getattr(getattr(response, "data", None), "records", None) or []
                for row, record in zip(chunk, items):
                    record_id = getattr(record, "record_id", None)
                    if record_id:
                        mapping[row["路径"]] = str(record_id)
            except Exception as exc:  # noqa: BLE001 - 单批失败整体中止
                print(f"[board] batch create fail: {exc}", flush=True)
                return None
        return mapping

    def _batch_update(
        self,
        lark: Any,
        client: Any,
        app_token: str,
        table_id: str,
        rows: List[Dict[str, Any]],
        records: Dict[str, str],
    ) -> bool:
        """批量更新已有记录；失败返回 False。"""
        for chunk in _chunks(rows, _BATCH):
            try:
                body = (
                    lark.api.bitable.v1.BatchUpdateAppTableRecordRequestBody.builder()
                    .records(
                        [
                            lark.api.bitable.v1.AppTableRecord.builder()
                            .record_id(records[row["路径"]])
                            .fields(row)
                            .build()
                            for row in chunk
                            if row["路径"] in records
                        ]
                    )
                    .build()
                )
                request = (
                    lark.api.bitable.v1.BatchUpdateAppTableRecordRequest.builder()
                    .app_token(app_token)
                    .table_id(table_id)
                    .request_body(body)
                    .build()
                )
                response = client.bitable.v1.app_table_record.batch_update(request)
                if not response.success():
                    print("[board] batch update fail", flush=True)
                    return False
            except Exception as exc:  # noqa: BLE001
                print(f"[board] batch update fail: {exc}", flush=True)
                return False
        return True


def _to_ms(value: Any) -> Optional[int]:
    """created 元数据（datetime / ISO 字符串）→ 毫秒时间戳；取不到 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    try:
        from scripts.utils.date_utils import parse_date

        return int(parse_date(str(value)).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _chunks(rows: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    """按批大小切分（空输入返回空表）。"""
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def sync_board(tree: Any) -> Optional[Dict[str, Any]]:
    """同步一轮知识库看板；便捷入口（dispatch_cli 与飞书菜单共用）。"""
    return BoardSync(tree).sync()
