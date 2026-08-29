"""认知模块：CognitionManager 与认知条目数据模型（COGNITION-SPEC v1.0）。

认知条目（belief/question/hypothesis）以平面 Markdown 存于
ov_path/cognition/（$OV 根下的 cognition 平面目录），是批准后语义状态的
唯一源真相；<state_dir>/cognition/ 下只有派生索引（index.json，可完整
重建）与未批准的 proposal 队列（proposals.json）。

与 memory 的隔离不变量：cognition 用 certainty（确信度，不随时间衰减），
memory 用 confidence（新鲜度，无状态纯函数）；两者不同步、不比较、不互写。
cognition 语义变更必须携带显式 ApprovalRecord（人工批准）；本模块不提供
delete_entry，也没有任何自动删除路径。

布局假定（架构 v1.3 §5.1）：ov_path 为 $OV 根，memory 在 ov_path/memory，
cognition 在 ov_path/cognition，状态在 state_dir（默认 ov_path/state）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

import frontmatter

from scripts.memory.core import generate_id
from scripts.utils.config import load_config

CognitionType = Literal["belief", "question", "hypothesis"]
EvidenceRelation = Literal["supports", "challenges", "context"]
ChallengeResolution = Literal["reject", "defer", "accept"]

#: 当前锁定的 schema 主版本；未知主版本拒绝写入
SCHEMA_VERSION = 1

COGNITION_TYPES: Tuple[str, str, str] = ("belief", "question", "hypothesis")
EVIDENCE_KINDS: Tuple[str, str, str] = ("memory", "url", "manual")
EVIDENCE_RELATIONS: Tuple[str, str, str] = ("supports", "challenges", "context")
CERTAINTY_SOURCES: Tuple[str, str] = (
    "human_assessment",
    "human_approved_agent_assessment",
)

#: 按类型校验的合法状态机（COG-SCHEMA-04）
STATUS_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    "belief": ("draft", "active", "questioned", "refuted", "superseded", "archived"),
    "hypothesis": (
        "draft",
        "testing",
        "supported",
        "refuted",
        "superseded",
        "archived",
    ),
    "question": ("open", "answered", "superseded", "archived"),
}

#: 创建/继任时各类型的默认"在研"状态
DEFAULT_STATUS: Dict[str, str] = {
    "belief": "active",
    "hypothesis": "testing",
    "question": "open",
}

#: 默认列表隐藏的非活动状态（显式 --status 查询不受限）
INACTIVE_STATUSES: Tuple[str, str, str] = ("refuted", "superseded", "archived")

#: §3.2：purge 依赖警告只统计这些"在研"状态的 cognition
DEPENDENCY_STATUSES: Tuple[str, str, str] = ("active", "testing", "questioned")

#: 认知条目文件名： <slug>--<short-id>.md
_FILENAME_RE = re.compile(r"^.+--[0-9a-z]{8}\.md$")
_ABSOLUTE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

#: certainty 无变化哨兵（区别于 question 的合法 None）
_UNSET = object()


class CognitionError(ValueError):
    """认知 schema / 状态机 / 证据校验错误（拒绝写入）。"""


class RevisionConflictError(RuntimeError):
    """获批写入时磁盘 revision 与上次读取不一致（并发修改保护）。"""


def _now_iso() -> str:
    """当前本地时间的带时区 ISO 字符串（秒精度）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _aware_iso(value: object, field_name: str) -> str:
    """把 ISO 字符串/datetime 规范为带时区 ISO 字符串；naive 一律拒绝。"""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            raise CognitionError(f"{field_name} 不是合法 ISO 8601: {value!r}") from None
    else:
        raise CognitionError(f"{field_name} 类型非法: {type(value).__name__}")
    if dt.tzinfo is None:
        raise CognitionError(f"{field_name} 必须带时区: {value!r}")
    return dt.isoformat(timespec="seconds")


def _round_certainty(value: object) -> float:
    """范围校验 [0.0, 1.0] 后按十进制定点四舍五入到最多四位（§2.4）。"""
    if isinstance(value, bool):
        raise CognitionError(f"certainty 必须是数值: {value!r}")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise CognitionError(f"certainty 必须是数值: {value!r}") from None
    if dec.is_nan() or dec.is_infinite():
        raise CognitionError(f"certainty 必须是有限数值: {value!r}")
    if dec < Decimal("0") or dec > Decimal("1"):
        raise CognitionError(f"certainty 必须在 [0.0, 1.0] 内: {value!r}")
    return float(dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _require_str(value: object, field_name: str) -> str:
    """非空字符串校验。"""
    if not isinstance(value, str) or not value.strip():
        raise CognitionError(f"{field_name} 必须是非空字符串: {value!r}")
    return value


def _str_tuple(value: object, field_name: str) -> Tuple[str, ...]:
    """字符串列表校验（缺省/None 视为空）。"""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise CognitionError(f"{field_name} 必须是字符串列表: {value!r}")
    return tuple(_require_str(item, field_name) for item in value)


def _slug_filename(title: str, entry_id: str) -> str:
    """生成 <slug>--<short-id>.md 文件名（保留中英文，其余折成 -）。"""
    text = re.sub(r"[^0-9a-z一-鿿]+", "-", title.lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")[:48].strip("-")
    if not text:
        text = "entry"
    return f"{text}--{entry_id[-8:].lower()}.md"


@dataclass(frozen=True)
class EvidenceRef:
    """带稳定来源 ID、关系、路径快照和摘要的证据引用。

    字段规则（COG-SCHEMA-05）：
    - memory: 必填 id/path；禁止 url/accessed_at
    - url: 必填绝对 http/https url 与 accessed_at；禁止 id/path
    - manual: 必填非空 note；禁止 id/path/url/accessed_at
    所有 kind 必须有 relation；added_at 缺省时由写入方补当前时间。
    """

    kind: str
    relation: str
    note: Optional[str] = None
    id: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    accessed_at: Optional[str] = None
    added_at: Optional[str] = None

    def validate(self) -> "EvidenceRef":
        """按 kind 规则校验；合法返回自身，非法抛 CognitionError。"""
        if self.kind not in EVIDENCE_KINDS:
            raise CognitionError(f"非法 evidence kind: {self.kind!r}")
        if self.relation not in EVIDENCE_RELATIONS:
            raise CognitionError(f"非法 evidence relation: {self.relation!r}")
        if self.kind == "memory":
            _require_str(self.id, "evidence.id")
            _require_str(self.path, "evidence.path")
            if self.url is not None or self.accessed_at is not None:
                raise CognitionError("memory evidence 禁止 url/accessed_at")
        elif self.kind == "url":
            url = _require_str(self.url, "evidence.url")
            if not _ABSOLUTE_URL_RE.match(url):
                raise CognitionError(f"evidence.url 必须是绝对 http/https: {url!r}")
            _aware_iso(
                _require_str(self.accessed_at, "evidence.accessed_at"),
                "evidence.accessed_at",
            )
            if self.id is not None or self.path is not None:
                raise CognitionError("url evidence 禁止 id/path")
        else:  # manual
            _require_str(self.note, "evidence.note")
            forbidden = (self.id, self.path, self.url, self.accessed_at)
            if any(item is not None for item in forbidden):
                raise CognitionError("manual evidence 禁止 id/path/url/accessed_at")
        if self.added_at is not None:
            _aware_iso(self.added_at, "evidence.added_at")
        return self

    def to_dict(self) -> dict:
        """序列化为 frontmatter 字典（只含已设置字段）。"""
        data: Dict[str, object] = {"kind": self.kind, "relation": self.relation}
        for key in ("id", "path", "url", "accessed_at", "note", "added_at"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: object) -> "EvidenceRef":
        """从 frontmatter 字典构造并校验。"""
        if not isinstance(data, dict):
            raise CognitionError(f"evidence 项必须是映射: {data!r}")
        if "kind" not in data or "relation" not in data:
            raise CognitionError(f"evidence 缺少 kind/relation: {data!r}")
        return cls(
            kind=str(data["kind"]),
            relation=str(data["relation"]),
            note=data.get("note"),
            id=data.get("id"),
            path=data.get("path"),
            url=data.get("url"),
            accessed_at=data.get("accessed_at"),
            added_at=data.get("added_at"),
        ).validate()


@dataclass(frozen=True)
class ApprovalRecord:
    """由直接用户确认产生的时间、动作、理由记录。

    source 即写入 cognition 的 certainty_source：
    human_assessment（用户直接给出）或 human_approved_agent_assessment
    （Agent 提议、用户批准）。
    """

    action: str
    reason: str
    source: str = "human_assessment"
    approved_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        _require_str(self.action, "approval.action")
        _require_str(self.reason, "approval.reason")
        if self.source not in CERTAINTY_SOURCES:
            raise CognitionError(f"非法 certainty_source: {self.source!r}")


@dataclass(frozen=True)
class CognitionEntry:
    """一个已批准、通过 schema 校验的认知条目只读视图。"""

    id: str
    path: Path
    title: str
    entry_type: str
    statement: str
    status: str
    certainty: Optional[float]
    certainty_updated_at: Optional[str]
    certainty_source: Optional[str]
    created: str
    updated: str
    revision: int
    tags: Tuple[str, ...]
    origin: Dict[str, object]
    evidence: Tuple[EvidenceRef, ...]
    related: Tuple[str, ...]
    supersedes: Optional[str]
    content: str

    @property
    def type(self) -> str:
        """entry_type 的规格命名别名。"""
        return self.entry_type


@dataclass
class PromotionProposal:
    """尚未改变认知源真相的 memory → cognition 提名。"""

    id: str
    memory_id: str
    memory_path: str
    entry_type: str
    title: str
    statement: str
    rationale: str
    proposed_status: str
    proposed_certainty: Optional[float]
    status: str = "pending"
    created: str = field(default_factory=_now_iso)
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    kind: str = "promotion"


@dataclass
class ChallengeProposal:
    """尚未改变认知源真相的挑战提案。"""

    id: str
    entry_id: str
    evidence: Tuple[EvidenceRef, ...]
    rationale: str
    proposed_certainty: Optional[float] = None
    proposed_status: Optional[str] = None
    status: str = "pending"
    resolution: Optional[str] = None
    created: str = field(default_factory=_now_iso)
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None
    kind: str = "challenge"


@dataclass(frozen=True)
class ValidationReport:
    """逐文件 schema、引用和状态机校验结果。"""

    checked: int
    errors: Tuple[str, ...]
    index_drift: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """无 schema/引用错误即为 True（index 漂移只是提示）。"""
        return not self.errors


@dataclass(frozen=True)
class IndexReport:
    """派生索引重建或 dry-run 的统计与错误报告。"""

    scanned: int
    rebuilt: int
    errors: Tuple[str, ...]
    dry_run: bool = False


@dataclass(frozen=True)
class WritePlan:
    """一次待人工确认的写入计划：完整 diff 预览 + commit 执行。

    plan_* 方法只计算不写盘；commit() 才落盘（原子替换）。
    CLI 用它实现"先展示 diff、确认后写入"与 --dry-run。
    """

    action: str
    diffs: Tuple[Tuple[str, str, str], ...]  # (标签, before, after)
    summary: str
    _commit: Callable[[], CognitionEntry] = field(repr=False, compare=False)
    #: 计划新建条目的 id/path（更新类计划为 None）
    planned_id: Optional[str] = None
    planned_path: Optional[Path] = None

    def commit(self) -> CognitionEntry:
        """执行计划内的全部写入并返回结果条目。"""
        return self._commit()


class CognitionManager:
    """管理 cognition Markdown、派生索引与人工审批工作流。

    Markdown 是唯一源真相；index.json 只镜像可重建字段；proposals.json
    只保存未批准的 promotion/challenge 工作流状态。读取方法不写任何文件。
    """

    def __init__(
        self, ov_path: "str | Path", state_dir: "str | Path | None" = None
    ) -> None:
        """初始化 $OV 布局下的 cognition 存储（不存在则创建目录）。

        Args:
            ov_path: $OV 根目录（memory/ 与 cognition/ 的公共父目录）。
            state_dir: 状态目录；默认 ov_path/state，与 memory sidecar 同级。
        """
        self.ov_path = Path(ov_path).expanduser()
        self.memory_dir = self.ov_path / "memory"
        self.cognition_dir = self.ov_path / "cognition"
        self.state_dir = (
            Path(state_dir).expanduser() if state_dir else self.ov_path / "state"
        )
        self.cog_state_dir = self.state_dir / "cognition"
        self.cognition_dir.mkdir(parents=True, exist_ok=True)
        self.cog_state_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cog_state_dir / "index.json"
        self.proposals_path = self.cog_state_dir / "proposals.json"
        self._index: Optional[Dict[str, dict]] = None
        #: 本进程各条目最近读到的 revision，用于并发修改检测
        self._seen: Dict[str, int] = {}

    @classmethod
    def from_config(cls, config_path: str) -> "CognitionManager":
        """从 YAML 配置构造（读 memory.root/state_dir 推导 $OV 布局）。

        memory.root 以 "memory" 结尾时取其父目录为 $OV；否则把 root 当 $OV
        （假定标准布局）。缺失字段沿用 ~/atelierr-data 默认。

        Args:
            config_path: YAML 配置文件路径。

        Returns:
            CognitionManager: 配置好的实例。

        Raises:
            FileNotFoundError: 配置文件不存在。
        """
        config = load_config(config_path)
        memory = (config or {}).get("memory", {}) or {}
        root = Path(memory.get("root", "~/atelierr-data/memory")).expanduser()
        ov = root.parent if root.name == "memory" else root
        state_dir = memory.get("state_dir", "~/atelierr-data/state")
        return cls(ov, state_dir=state_dir)

    # ------------------------------------------------------------------
    # sidecar：派生索引与 proposal 队列（原子写；损坏隔离不猜测修复）
    # ------------------------------------------------------------------

    def _load_index(self) -> Dict[str, dict]:
        """读取派生索引（内存缓存，惰性加载）。"""
        if self._index is None:
            self._index = self._read_json(self.index_path)
        return self._index

    def _save_index(self) -> None:
        """原子写索引。"""
        self._write_json(self.index_path, self._load_index())

    def _load_proposals(self) -> Dict[str, dict]:
        """读取 proposal 队列：每次从磁盘读（队列很小，不缓存）。

        提案队列是跨进程共享的工作流状态（CLI 每次调用都是新进程），
        缓存会让长寿命实例读到或覆盖其他写入方的终态。
        """
        return self._read_json(self.proposals_path)

    def _save_proposals(self, proposals: Dict[str, dict]) -> None:
        """原子写 proposal 队列。"""
        self._write_json(self.proposals_path, proposals)

    @staticmethod
    def _read_json(path: Path) -> Dict[str, dict]:
        """读 JSON sidecar；损坏时改名 .bak 隔离并返回空（不猜测修复）。"""
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            try:
                os.replace(path, path.with_name(path.name + ".bak"))
            except OSError:
                pass
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write_json(path: Path, data: Dict[str, dict]) -> None:
        """原子写 JSON sidecar：先写临时文件再 rename。"""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _index_upsert(self, entry: CognitionEntry) -> None:
        """把条目镜像进派生索引（只含 §5.2 允许的可重建字段）。

        写前从磁盘重读：索引是可重建派生数据，长寿命实例不得用缓存
        覆盖其他写入方刚写入的镜像。
        """
        origin = entry.origin if isinstance(entry.origin, dict) else {}
        self._index = self._read_json(self.index_path)
        self._index[entry.id] = {
            "path": entry.path.name,
            "type": entry.entry_type,
            "status": entry.status,
            "certainty": entry.certainty,
            "updated": entry.updated,
            "memory_id": origin.get("memory_id"),
            "related": list(entry.related),
            "supersedes": entry.supersedes,
        }
        self._save_index()

    # ------------------------------------------------------------------
    # 条目文件读写（Markdown 是源真相；获批更新用原子替换）
    # ------------------------------------------------------------------

    def _write_entry_file(self, path: Path, text: str) -> None:
        """原子写 cognition 文件（获批更新允许原地覆写 cognition）。"""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _locate(self, entry_id: str) -> Path:
        """按 id 定位条目文件：先查索引，索引缺失/失效时扫描目录。"""
        indexed = self._load_index().get(entry_id)
        if indexed:
            candidate = self.cognition_dir / indexed.get("path", "")
            if candidate.exists():
                return candidate
        for path in sorted(self.cognition_dir.glob("*.md")):
            try:
                post = frontmatter.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 损坏文件跳过，validate 负责报告
                continue
            if str(post.metadata.get("id")) == entry_id:
                return path
        raise KeyError(f"cognition 不存在: {entry_id}")

    def _parse_entry(self, path: Path) -> CognitionEntry:
        """解析并按 schema 校验单个 cognition 文件。"""
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 统一转成明确错误
            raise CognitionError(f"无法解析 {path.name}: {exc}") from None
        meta = dict(post.metadata or {})
        return self._entry_from_meta(meta, path, post.content)

    def _entry_from_meta(self, meta: dict, path: Path, content: str) -> CognitionEntry:
        """把 frontmatter 元数据校验并规范为 CognitionEntry。"""
        if "confidence" in meta:
            raise CognitionError(
                f"{path.name}: cognition 禁止 confidence 字段（请用 certainty）"
            )
        version = meta.get("schema_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise CognitionError(f"{path.name}: schema_version 必须是正整数")
        if version != SCHEMA_VERSION:
            raise CognitionError(
                f"{path.name}: 未知 schema_version {version}（当前支持 {SCHEMA_VERSION}）"
            )
        entry_id = _require_str(meta.get("id"), "id")
        title = _require_str(meta.get("title"), "title")
        statement = _require_str(meta.get("statement"), "statement")
        entry_type = meta.get("type")
        if entry_type not in COGNITION_TYPES:
            raise CognitionError(f"{path.name}: 非法 type: {entry_type!r}")
        status = meta.get("status")
        if status not in STATUS_BY_TYPE[entry_type]:
            raise CognitionError(f"{path.name}: {entry_type} 不允许 status {status!r}")

        certainty_raw = meta.get("certainty")
        certainty_updated_at = meta.get("certainty_updated_at")
        certainty_source = meta.get("certainty_source")
        if entry_type == "question":
            present = [
                name
                for name, value in (
                    ("certainty", certainty_raw),
                    ("certainty_updated_at", certainty_updated_at),
                    ("certainty_source", certainty_source),
                )
                if value is not None
            ]
            if present:
                raise CognitionError(
                    f"{path.name}: question 必须省略 {', '.join(present)}"
                )
            certainty = None
        else:
            if certainty_raw is None:
                raise CognitionError(f"{path.name}: {entry_type} 必须有 certainty")
            certainty = _round_certainty(certainty_raw)
            certainty_updated_at = _aware_iso(
                certainty_updated_at, "certainty_updated_at"
            )
            if certainty_source not in CERTAINTY_SOURCES:
                raise CognitionError(
                    f"{path.name}: 非法 certainty_source: {certainty_source!r}"
                )

        revision = meta.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise CognitionError(f"{path.name}: revision 必须是正整数")

        origin = meta.get("origin") or {}
        if not isinstance(origin, dict):
            raise CognitionError(f"{path.name}: origin 必须是映射")
        origin_kind = origin.get("kind")
        if origin_kind not in ("memory", "manual"):
            raise CognitionError(f"{path.name}: 非法 origin.kind: {origin_kind!r}")
        if origin_kind == "memory":
            _require_str(origin.get("memory_id"), "origin.memory_id")

        evidence = tuple(
            EvidenceRef.from_dict(item) for item in (meta.get("evidence") or [])
        )
        supersedes = meta.get("supersedes")
        if supersedes is not None:
            supersedes = _require_str(supersedes, "supersedes")

        return CognitionEntry(
            id=entry_id,
            path=path,
            title=title,
            entry_type=entry_type,
            statement=statement,
            status=status,
            certainty=certainty,
            certainty_updated_at=certainty_updated_at,
            certainty_source=certainty_source,
            created=_aware_iso(meta.get("created"), "created"),
            updated=_aware_iso(meta.get("updated"), "updated"),
            revision=revision,
            tags=_str_tuple(meta.get("tags"), "tags"),
            origin=origin,
            evidence=evidence,
            related=_str_tuple(meta.get("related"), "related"),
            supersedes=supersedes,
            content=content,
        )

    # ------------------------------------------------------------------
    # revision 并发保护
    # ------------------------------------------------------------------

    def _check_revision(self, entry: CognitionEntry) -> None:
        """磁盘 revision 与本进程上次读取不一致时拒绝（防丢失更新）。"""
        seen = self._seen.get(entry.id)
        if seen is not None and seen != entry.revision:
            raise RevisionConflictError(
                f"{entry.id}: 磁盘 revision={entry.revision}，"
                f"本进程上次读到 r{seen}；请重新读取后再批准写入"
            )
        self._seen[entry.id] = entry.revision

    # ------------------------------------------------------------------
    # 读取 API（不得改变文件、mtime 或 proposal 状态）
    # ------------------------------------------------------------------

    def get_entry(self, entry_id: str) -> CognitionEntry:
        """按 id 读取条目（Markdown 为准，索引仅用于定位）。

        Args:
            entry_id: cognition id。

        Returns:
            CognitionEntry: 通过校验的只读视图。

        Raises:
            KeyError: 条目不存在。
            CognitionError: 文件损坏或 schema 非法（不自动修复）。
        """
        entry = self._parse_entry(self._locate(entry_id))
        self._seen[entry.id] = entry.revision
        return entry

    def list_entries(
        self,
        *,
        entry_type: "CognitionType | None" = None,
        status: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[CognitionEntry]:
        """列出条目；默认隐藏 refuted/superseded/archived（显式可查）。

        Args:
            entry_type: 类型过滤。
            status: 状态过滤（显式给出时不做活动性隐藏）。
            include_inactive: True 时包含非活动条目。

        Returns:
            List[CognitionEntry]: 按 id 排序；损坏文件跳过（validate 报告）。
        """
        if entry_type is not None and entry_type not in COGNITION_TYPES:
            raise CognitionError(f"非法 type: {entry_type!r}")
        entries = []
        for path in sorted(self.cognition_dir.glob("*.md")):
            try:
                entry = self._parse_entry(path)
            except CognitionError:
                continue
            if entry_type is not None and entry.entry_type != entry_type:
                continue
            if status is not None:
                if entry.status != status:
                    continue
            elif not include_inactive and entry.status in INACTIVE_STATUSES:
                continue
            self._seen[entry.id] = entry.revision
            entries.append(entry)
        return entries

    def validate(self) -> ValidationReport:
        """逐文件校验 schema、状态机、重复 id 与 supersedes 引用/环。

        只读：损坏文件被报告，绝不覆写或猜测性修复。
        附带报告派生索引与 Markdown 的漂移（仅提示，Markdown 胜出）。
        """
        errors: List[str] = []
        entries: List[CognitionEntry] = []
        paths = sorted(self.cognition_dir.glob("*.md"))
        for path in paths:
            try:
                entries.append(self._parse_entry(path))
            except CognitionError as exc:
                errors.append(str(exc))

        by_id: Dict[str, CognitionEntry] = {}
        for entry in entries:
            if entry.id in by_id:
                errors.append(
                    f"{entry.path.name}: 重复 id {entry.id}"
                    f"（与 {by_id[entry.id].path.name} 冲突）"
                )
            else:
                by_id[entry.id] = entry
        for entry in entries:
            target = entry.supersedes
            if target is not None and target not in by_id:
                errors.append(f"{entry.path.name}: supersedes 指向不存在的 id {target}")
        for entry in entries:
            if self._has_supersedes_cycle(entry, by_id):
                errors.append(f"{entry.path.name}: supersedes 形成环")
        errors = sorted(set(errors))

        drift: List[str] = []
        index = self._load_index()
        for entry in entries:
            mirrored = index.get(entry.id)
            if mirrored is None:
                drift.append(f"{entry.id}: 索引缺失")
            elif (
                mirrored.get("status") != entry.status
                or mirrored.get("certainty") != entry.certainty
                or mirrored.get("updated") != entry.updated
            ):
                drift.append(f"{entry.id}: 索引与 Markdown 不一致（以 Markdown 为准）")
        return ValidationReport(
            checked=len(paths), errors=tuple(errors), index_drift=tuple(drift)
        )

    @staticmethod
    def _has_supersedes_cycle(
        entry: CognitionEntry, by_id: Dict[str, CognitionEntry]
    ) -> bool:
        """沿 supersedes 链检测环。"""
        seen = {entry.id}
        current = entry
        while current.supersedes is not None:
            target = by_id.get(current.supersedes)
            if target is None:
                return False
            if target.id in seen:
                return True
            seen.add(target.id)
            current = target
        return False

    def rebuild_index(self, dry_run: bool = False) -> IndexReport:
        """从 Markdown 完整重建派生索引（可 dry-run）。

        Args:
            dry_run: True 时只统计不写盘。

        Returns:
            IndexReport: 扫描/重建计数与逐文件错误。
        """
        scanned = 0
        rebuilt = 0
        errors: List[str] = []
        new_index: Dict[str, dict] = {}
        for path in sorted(self.cognition_dir.glob("*.md")):
            scanned += 1
            try:
                entry = self._parse_entry(path)
            except CognitionError as exc:
                errors.append(str(exc))
                continue
            origin = entry.origin if isinstance(entry.origin, dict) else {}
            new_index[entry.id] = {
                "path": entry.path.name,
                "type": entry.entry_type,
                "status": entry.status,
                "certainty": entry.certainty,
                "updated": entry.updated,
                "memory_id": origin.get("memory_id"),
                "related": list(entry.related),
                "supersedes": entry.supersedes,
            }
            rebuilt += 1
        if not dry_run:
            self._index = new_index
            self._save_index()
        return IndexReport(
            scanned=scanned, rebuilt=rebuilt, errors=tuple(errors), dry_run=dry_run
        )

    # ------------------------------------------------------------------
    # memory 来源解析（只读 memory；绝不写入）
    # ------------------------------------------------------------------

    def _find_memory(self, memory_id: str) -> Tuple[Path, Optional[dict]]:
        """按稳定 id 在 $OV/memory 根层找笔记。

        Returns:
            Tuple[Path, Optional[dict]]: (笔记路径, memory sidecar 条目或 None)。

        Raises:
            CognitionError: 来源在回收站（必须先恢复）。
            KeyError: 找不到该 memory。
        """
        if self.memory_dir.is_dir():
            for path in sorted(self.memory_dir.glob("*.md")):
                try:
                    post = frontmatter.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001 - 损坏文件跳过
                    continue
                if str(post.metadata.get("id")) == memory_id:
                    return path, self._memory_sidecar_entry(memory_id)
        trash_dir = self.state_dir / "trash"
        if trash_dir.is_dir():
            for path in sorted(trash_dir.glob("*.md")):
                try:
                    post = frontmatter.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                if str(post.metadata.get("id")) == memory_id:
                    raise CognitionError(
                        f"来源 memory 在回收站（{path.name}），必须先恢复再升级"
                    )
        raise KeyError(f"memory 不存在: {memory_id}")

    def _memory_sidecar_entry(self, memory_id: str) -> Optional[dict]:
        """读取 memory sidecar（<state_dir>/index.json）中该 id 的条目。"""
        sidecar = self._read_json(self.state_dir / "index.json")
        entry = sidecar.get(memory_id)
        return entry if isinstance(entry, dict) else None

    def memory_dependencies(self, memory_id: str) -> List[CognitionEntry]:
        """列出 origin/evidence 引用该 memory 的在研（active/testing/questioned）条目。

        供 memory_cli review/purge 显示依赖警告；只读，不阻止任何操作。
        """
        dependents = []
        for path in sorted(self.cognition_dir.glob("*.md")):
            try:
                entry = self._parse_entry(path)
            except CognitionError:
                continue
            if entry.status not in DEPENDENCY_STATUSES:
                continue
            if entry.origin.get("memory_id") == memory_id:
                dependents.append(entry)
                continue
            if any(
                ref.kind == "memory" and ref.id == memory_id for ref in entry.evidence
            ):
                dependents.append(entry)
        return dependents

    # ------------------------------------------------------------------
    # 写入计划（plan_* 只计算；commit 才落盘）
    # ------------------------------------------------------------------

    @staticmethod
    def _render_body(
        title: str,
        statement: str,
        entry_type: str,
        rationale: str = "",
        history: Sequence[str] = (),
    ) -> str:
        """渲染统一骨架正文；hypothesis 含验证/证伪条件节。"""
        parts = [
            f"# {title}",
            "",
            "## 认知陈述",
            "",
            statement,
            "",
            "## 理由与适用边界",
            "",
            rationale or "（待补充）",
            "",
            "## 支持证据",
            "",
            "（见 frontmatter evidence）",
            "",
            "## 挑战证据",
            "",
            "（见 frontmatter evidence）",
            "",
        ]
        if entry_type == "hypothesis":
            parts += ["## 验证 / 证伪条件", "", "（待补充）", ""]
        parts += ["## 修订历史", ""]
        parts += history or ["（无）"]
        return "\n".join(parts).rstrip() + "\n"

    @staticmethod
    def _append_history(content: str, line: str) -> str:
        """在正文末尾（修订历史节）追加一条审计记录。"""
        body = content.rstrip()
        if "## 修订历史" not in body:
            body += "\n\n## 修订历史"
        return body + "\n\n" + line + "\n"

    @staticmethod
    def _render_file(meta: dict, content: str) -> str:
        """渲染完整 cognition 文件（frontmatter + 正文）。"""
        return frontmatter.dumps(frontmatter.Post(content, **meta))

    def _entry_meta(self, entry: CognitionEntry) -> dict:
        """把条目视图还原为 frontmatter 元数据（用于覆写）。"""
        meta: Dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "id": entry.id,
            "title": entry.title,
            "type": entry.entry_type,
            "statement": entry.statement,
            "status": entry.status,
            "created": entry.created,
            "updated": entry.updated,
            "revision": entry.revision,
            "tags": list(entry.tags),
            "origin": dict(entry.origin),
            "evidence": [ref.to_dict() for ref in entry.evidence],
            "related": list(entry.related),
            "supersedes": entry.supersedes,
        }
        if entry.certainty is not None:
            meta["certainty"] = entry.certainty
            meta["certainty_updated_at"] = entry.certainty_updated_at
            meta["certainty_source"] = entry.certainty_source
        return meta

    def _validate_type_status_certainty(
        self,
        entry_type: str,
        status: str,
        certainty: Optional[float],
    ) -> Optional[float]:
        """类型/状态/certainty 联合校验；返回四舍五入后的 certainty。"""
        if entry_type not in COGNITION_TYPES:
            raise CognitionError(f"非法 type: {entry_type!r}")
        if status not in STATUS_BY_TYPE[entry_type]:
            raise CognitionError(f"{entry_type} 不允许 status {status!r}")
        if entry_type == "question":
            if certainty is not None:
                raise CognitionError("question 必须省略 certainty")
            return None
        if certainty is None:
            raise CognitionError(f"{entry_type} 必须有 certainty")
        return _round_certainty(certainty)

    def _plan_create(
        self,
        *,
        entry_type: str,
        title: str,
        statement: str,
        status: str,
        certainty: Optional[float],
        tags: Sequence[str],
        evidence: Sequence[EvidenceRef],
        origin: dict,
        rationale: str,
        history_action: str,
        approval: ApprovalRecord,
        supersedes: Optional[str] = None,
    ) -> WritePlan:
        """create/approve/supersede 共用的创建计划（只计算不写盘）。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        certainty_value = self._validate_type_status_certainty(
            entry_type, status, certainty
        )
        refs = tuple(ref.validate() for ref in evidence)
        now = _now_iso()
        entry_id = f"cog_{generate_id()}"
        filename = _slug_filename(title, entry_id)
        path = self.cognition_dir / filename
        if path.exists():
            raise FileExistsError(f"cognition 文件已存在: {path}")

        meta: Dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "id": entry_id,
            "title": _require_str(title, "title"),
            "type": entry_type,
            "statement": _require_str(statement, "statement"),
            "status": status,
            "created": now,
            "updated": now,
            "revision": 1,
            "tags": [str(tag) for tag in tags],
            "origin": origin,
            "evidence": [
                {**ref.to_dict(), "added_at": ref.added_at or now} for ref in refs
            ],
            "related": [],
            "supersedes": supersedes,
        }
        if certainty_value is not None:
            meta["certainty"] = certainty_value
            meta["certainty_updated_at"] = now
            meta["certainty_source"] = approval.source
        history_line = (
            f"- {now} | r1 | {history_action} | ∅ → {status}"
            + (
                f"（确信度 {certainty_value:.4f}）"
                if certainty_value is not None
                else ""
            )
            + f" | {approval.reason}"
        )
        content = self._render_body(
            title, statement, entry_type, rationale, [history_line]
        )
        text = self._render_file(meta, content)

        def commit() -> CognitionEntry:
            self._write_entry_file(path, text)
            entry = self._parse_entry(path)
            self._index_upsert(entry)
            self._seen[entry.id] = entry.revision
            return entry

        summary = f"新建 {entry_type} {entry_id}（status={status}）"
        return WritePlan(
            action=history_action,
            diffs=((filename, "", text),),
            summary=summary,
            _commit=commit,
            planned_id=entry_id,
            planned_path=path,
        )

    def _plan_update(
        self,
        entry: CognitionEntry,
        *,
        action: str,
        approval: ApprovalRecord,
        new_status: Optional[str] = None,
        new_certainty: object = _UNSET,
        add_evidence: Sequence[EvidenceRef] = (),
        add_related: Sequence[str] = (),
        body_append: Optional[str] = None,
        history_note: str = "",
    ) -> WritePlan:
        """获批小变更的通用原地更新计划（revision+1、刷新 updated、追加历史）。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        self._check_revision(entry)
        status = entry.status if new_status is None else new_status
        if status not in STATUS_BY_TYPE[entry.entry_type]:
            raise CognitionError(f"{entry.entry_type} 不允许 status {status!r}")
        if new_certainty is _UNSET:
            certainty = entry.certainty
        elif new_certainty is None:
            if entry.entry_type != "question":
                raise CognitionError(f"{entry.entry_type} 必须有 certainty")
            certainty = None
        else:
            if entry.entry_type == "question":
                raise CognitionError("question 必须省略 certainty")
            certainty = _round_certainty(new_certainty)
        refs = tuple(ref.validate() for ref in add_evidence)

        now = _now_iso()
        changes: List[str] = []
        if status != entry.status:
            changes.append(f"status: {entry.status} → {status}")
        if certainty != entry.certainty:
            old = "∅" if entry.certainty is None else f"{entry.certainty:.4f}"
            new = "∅" if certainty is None else f"{certainty:.4f}"
            changes.append(f"确信度: {old} → {new}")
        if refs:
            changes.append(f"证据 +{len(refs)}")
        if add_related:
            changes.append(f"关联 +{len(add_related)}")

        meta = self._entry_meta(entry)
        meta["status"] = status
        meta["revision"] = entry.revision + 1
        meta["updated"] = now
        if certainty is not None:
            meta["certainty"] = certainty
            if certainty != entry.certainty:
                meta["certainty_updated_at"] = now
                meta["certainty_source"] = approval.source
        if refs:
            meta["evidence"] = meta["evidence"] + [  # type: ignore[operator]
                {**ref.to_dict(), "added_at": ref.added_at or now} for ref in refs
            ]
        if add_related:
            merged = list(entry.related)
            for rid in add_related:
                if rid not in merged:
                    merged.append(rid)
            meta["related"] = merged

        revision = entry.revision + 1
        detail = "; ".join(changes) if changes else "（无语义字段变化）"
        history_line = (
            f"- {now} | r{revision} | {action} | {detail}"
            + (f" | {history_note}" if history_note else "")
            + f" | {approval.reason}"
        )
        content = entry.content
        if body_append:
            content = content.rstrip() + "\n\n" + body_append
        content = self._append_history(content, history_line)
        text = self._render_file(meta, content)
        before = self._render_file(self._entry_meta(entry), entry.content)

        def commit() -> CognitionEntry:
            fresh = self._parse_entry(entry.path)
            self._check_revision(fresh)
            self._write_entry_file(entry.path, text)
            updated = self._parse_entry(entry.path)
            self._index_upsert(updated)
            self._seen[updated.id] = updated.revision
            return updated

        summary = f"更新 {entry.id}（{detail}）"
        return WritePlan(
            action=action,
            diffs=((entry.path.name, before, text),),
            summary=summary,
            _commit=commit,
        )

    # ------------------------------------------------------------------
    # 公共写入 API（全部 = plan + commit；必须携带 ApprovalRecord）
    # ------------------------------------------------------------------

    def plan_create_entry(
        self,
        *,
        entry_type: "CognitionType",
        title: str,
        statement: str,
        status: str,
        certainty: Optional[float],
        tags: Sequence[str] = (),
        evidence: Sequence[EvidenceRef] = (),
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划一次手工创建（origin.kind=manual）；不写盘。"""
        return self._plan_create(
            entry_type=entry_type,
            title=title,
            statement=statement,
            status=status,
            certainty=certainty,
            tags=tags,
            evidence=evidence,
            origin={"kind": "manual"},
            rationale="",
            history_action="create",
            approval=approval,
        )

    def create_entry(
        self,
        *,
        entry_type: "CognitionType",
        title: str,
        statement: str,
        status: str,
        certainty: Optional[float],
        tags: Sequence[str] = (),
        evidence: Sequence[EvidenceRef] = (),
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """手工创建认知条目（cognition 平面目录根层，一次性写入）。"""
        return self.plan_create_entry(
            entry_type=entry_type,
            title=title,
            statement=statement,
            status=status,
            certainty=certainty,
            tags=tags,
            evidence=evidence,
            approval=approval,
        ).commit()

    # ---------------- memory → cognition 升级 ----------------

    def nominate_memory(
        self,
        memory_id: str,
        *,
        entry_type: "CognitionType",
        title: str,
        statement: str,
        rationale: str,
        proposed_status: str,
        proposed_certainty: Optional[float] = None,
    ) -> PromotionProposal:
        """提名 memory 升级为 cognition：只写 proposal，不创建 cognition。

        重复 statement 与 pending_delete 来源记入 warnings（不自行合并、
        不阻止）；回收站来源拒绝提名。proposed_certainty 只是建议值：
        belief/hypothesis 在提名阶段允许缺省（批准时必须给定终值），
        question 传入非 None 仍拒绝。
        """
        if entry_type not in COGNITION_TYPES:
            raise CognitionError(f"非法 type: {entry_type!r}")
        if proposed_status not in STATUS_BY_TYPE[entry_type]:
            raise CognitionError(f"{entry_type} 不允许 status {proposed_status!r}")
        if entry_type == "question" and proposed_certainty is not None:
            raise CognitionError("question 必须省略 certainty")
        if proposed_certainty is not None:
            proposed_certainty = _round_certainty(proposed_certainty)
        source_path, sidecar = self._find_memory(memory_id)

        warnings: List[str] = []
        if sidecar and sidecar.get("pending_delete"):
            warnings.append(
                f"来源 {source_path.name} 已标记 pending_delete，"
                "存在 purge 风险；批准后 cognition 保留证据快照"
            )
        normalized = re.sub(r"\s+", "", statement).lower()
        for entry in self.list_entries(include_inactive=True):
            if re.sub(r"\s+", "", entry.statement).lower() == normalized:
                warnings.append(
                    f"疑似重复 statement：{entry.id}（{entry.path.name}）；"
                    "是否继续由用户决定"
                )

        proposal = PromotionProposal(
            id=f"prop_{generate_id()}",
            memory_id=memory_id,
            memory_path=source_path.name,
            entry_type=entry_type,
            title=title,
            statement=statement,
            rationale=rationale,
            proposed_status=proposed_status,
            proposed_certainty=proposed_certainty,
            warnings=warnings,
        )
        proposals = self._load_proposals()
        proposals[proposal.id] = self._proposal_to_dict(proposal)
        self._save_proposals(proposals)
        return proposal

    def list_promotion_proposals(
        self, *, status: str = "pending"
    ) -> List[PromotionProposal]:
        """按状态列出 promotion proposal。"""
        return [
            self._promotion_from_dict(data)
            for data in self._load_proposals().values()
            if data.get("kind") == "promotion" and data.get("status") == status
        ]

    def _list_proposals(self, kind: str, status: str = "pending") -> List[dict]:
        """按 kind/status 列出原始 proposal 字典（CLI 展示用）。"""
        return [
            data
            for data in self._load_proposals().values()
            if data.get("kind") == kind and data.get("status") == status
        ]

    def _require_proposal(self, proposal_id: str, kind: str) -> dict:
        """返回必存在的 pending proposal（读磁盘现值）。"""
        data = self._load_proposals().get(proposal_id)
        if data is None:
            raise KeyError(f"proposal 不存在: {proposal_id}")
        if data.get("kind") != kind:
            raise CognitionError(f"{proposal_id} 不是 {kind} proposal")
        if data.get("status") != "pending":
            raise CognitionError(
                f"proposal {proposal_id} 已处理（{data.get('status')}）"
            )
        return data

    def _decide_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        reason: str,
        resolution: Optional[str] = None,
    ) -> None:
        """把 proposal 置为终态并原子写盘（读现值后整体替换）。"""
        proposals = self._load_proposals()
        data = proposals[proposal_id]
        data["status"] = status
        data["decided_at"] = _now_iso()
        data["decision_reason"] = reason
        if resolution is not None:
            data["resolution"] = resolution
        self._save_proposals(proposals)

    def plan_approve_promotion(
        self,
        proposal_id: str,
        *,
        status: str,
        certainty: Optional[float],
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划批准提名：创建恰好一个 cognition（来源 memory 不动）。"""
        data = self._require_proposal(proposal_id, "promotion")
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        memory_id = str(data["memory_id"])
        # 批准前重新核验来源仍存在（回收站/消失则拒绝）
        source_path, _ = self._find_memory(memory_id)
        evidence = (
            EvidenceRef(
                kind="memory",
                relation="supports",
                id=memory_id,
                path=str(data["memory_path"]),
                note="升级来源记忆",
            ),
        )
        origin = {
            "kind": "memory",
            "memory_id": memory_id,
            "memory_path": str(data["memory_path"]),
            "promoted_at": _now_iso(),
        }
        plan = self._plan_create(
            entry_type=str(data["entry_type"]),
            title=str(data["title"]),
            statement=str(data["statement"]),
            status=status,
            certainty=certainty,
            tags=(),
            evidence=evidence,
            origin=origin,
            rationale=str(data.get("rationale") or ""),
            history_action=f"promote（来源 {source_path.name}）",
            approval=approval,
        )

        def commit() -> CognitionEntry:
            entry = plan.commit()
            self._decide_proposal(
                proposal_id, status="approved", reason=approval.reason
            )
            return entry

        return WritePlan(
            action="promote",
            diffs=plan.diffs,
            summary=f"批准 {proposal_id} → {plan.summary}（来源 memory 不变）",
            _commit=commit,
        )

    def approve_promotion(
        self,
        proposal_id: str,
        *,
        status: str,
        certainty: Optional[float],
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """批准提名：创建恰好一个 cognition 并把 proposal 置为 approved。"""
        return self.plan_approve_promotion(
            proposal_id, status=status, certainty=certainty, approval=approval
        ).commit()

    def reject_promotion(
        self,
        proposal_id: str,
        *,
        reason: str,
        approval: ApprovalRecord,
    ) -> None:
        """拒绝提名：记录理由；不修改 memory 或 cognition。"""
        self._require_proposal(proposal_id, "promotion")
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        self._decide_proposal(proposal_id, status="rejected", reason=reason)

    # ---------------- 挑战与演进 ----------------

    def propose_challenge(
        self,
        entry_id: str,
        *,
        evidence: Sequence[EvidenceRef],
        rationale: str,
        proposed_certainty: Optional[float] = None,
        proposed_status: Optional[str] = None,
    ) -> ChallengeProposal:
        """创建挑战提案：只写 proposal，批准前不改变 cognition。"""
        entry = self.get_entry(entry_id)
        refs = tuple(ref.validate() for ref in evidence)
        if not refs:
            raise CognitionError("挑战必须附至少一条证据")
        if entry.entry_type == "question" and proposed_certainty is not None:
            raise CognitionError("question 必须省略 certainty")
        if proposed_certainty is not None:
            proposed_certainty = _round_certainty(proposed_certainty)
        if proposed_status is not None and (
            proposed_status not in STATUS_BY_TYPE[entry.entry_type]
        ):
            raise CognitionError(
                f"{entry.entry_type} 不允许 status {proposed_status!r}"
            )
        proposal = ChallengeProposal(
            id=f"ch_{generate_id()}",
            entry_id=entry.id,
            evidence=refs,
            rationale=rationale,
            proposed_certainty=proposed_certainty,
            proposed_status=proposed_status,
        )
        proposals = self._load_proposals()
        proposals[proposal.id] = self._proposal_to_dict(proposal)
        self._save_proposals(proposals)
        return proposal

    def plan_resolve_challenge(
        self,
        proposal_id: str,
        *,
        resolution: "ChallengeResolution",
        certainty: Optional[float],
        status: Optional[str],
        rationale: str,
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划处理挑战：reject 不动条目；defer 可置 questioned；accept 附加证据。"""
        data = self._require_proposal(proposal_id, "challenge")
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        if resolution not in ("reject", "defer", "accept"):
            raise CognitionError(f"非法 resolution: {resolution!r}")
        entry = self._parse_entry(self._locate(str(data["entry_id"])))
        evidence = tuple(
            EvidenceRef.from_dict(item) for item in data.get("evidence", [])
        )

        if resolution == "reject":
            if certainty is not None or status is not None:
                raise CognitionError("reject 不修改 cognition，不得给 certainty/status")

            def commit_reject() -> CognitionEntry:
                self._decide_proposal(
                    proposal_id,
                    status="resolved",
                    reason=rationale,
                    resolution="reject",
                )
                return entry

            return WritePlan(
                action="challenge-reject",
                diffs=(),
                summary=f"拒绝挑战 {proposal_id}（cognition 不变）",
                _commit=commit_reject,
            )

        if resolution == "defer":
            if certainty is not None:
                raise CognitionError("defer 不修改 certainty（仅可置 questioned）")
            if status is not None and status != "questioned":
                raise CognitionError("defer 只能置 questioned 或保持原状态")
            if status is None:

                def commit_defer() -> CognitionEntry:
                    self._decide_proposal(
                        proposal_id,
                        status="resolved",
                        reason=rationale,
                        resolution="defer",
                    )
                    return entry

                return WritePlan(
                    action="challenge-defer",
                    diffs=(),
                    summary=f"暂缓挑战 {proposal_id}（cognition 不变）",
                    _commit=commit_defer,
                )
            plan = self._plan_update(
                entry,
                action="challenge-defer",
                approval=approval,
                new_status=status,
                history_note=f"挑战 {proposal_id} 暂缓",
            )
        else:  # accept
            if entry.entry_type != "question" and certainty is None:
                raise CognitionError("accept 挑战必须由用户指定新 certainty")
            plan = self._plan_update(
                entry,
                action="challenge-accept",
                approval=approval,
                new_status=status,
                new_certainty=certainty if certainty is not None else _UNSET,
                add_evidence=evidence,
                history_note=f"挑战 {proposal_id}：{data.get('rationale', '')}",
            )

        def commit() -> CognitionEntry:
            updated = plan.commit()
            self._decide_proposal(
                proposal_id,
                status="resolved",
                reason=rationale,
                resolution=resolution,
            )
            return updated

        return WritePlan(
            action=plan.action,
            diffs=plan.diffs,
            summary=plan.summary,
            _commit=commit,
        )

    def resolve_challenge(
        self,
        proposal_id: str,
        *,
        resolution: "ChallengeResolution",
        certainty: Optional[float],
        status: Optional[str],
        rationale: str,
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """处理挑战提案（reject/defer/accept），记录理由。"""
        return self.plan_resolve_challenge(
            proposal_id,
            resolution=resolution,
            certainty=certainty,
            status=status,
            rationale=rationale,
            approval=approval,
        ).commit()

    def plan_reassess_entry(
        self,
        entry_id: str,
        *,
        evidence: Sequence[EvidenceRef],
        certainty: Optional[float],
        status: str,
        rationale: str,
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划复核：附加证据并由用户指定新 certainty/status。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        entry = self._parse_entry(self._locate(entry_id))
        return self._plan_update(
            entry,
            action="reassess",
            approval=approval,
            new_status=status,
            new_certainty=certainty if certainty is not None else _UNSET,
            add_evidence=evidence,
            history_note=rationale,
        )

    def reassess_entry(
        self,
        entry_id: str,
        *,
        evidence: Sequence[EvidenceRef],
        certainty: Optional[float],
        status: str,
        rationale: str,
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """复核条目：获批附加证据、更新 certainty/status 并记录历史。"""
        return self.plan_reassess_entry(
            entry_id,
            evidence=evidence,
            certainty=certainty,
            status=status,
            rationale=rationale,
            approval=approval,
        ).commit()

    def plan_answer_question(
        self,
        entry_id: str,
        *,
        answer: str,
        related_entries: Sequence[str] = (),
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划回答问题：必须记录答案摘要或关联 cognition id。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        entry = self._parse_entry(self._locate(entry_id))
        if entry.entry_type != "question":
            raise CognitionError(f"{entry_id} 不是 question")
        if entry.status != "open":
            raise CognitionError(f"question {entry_id} 当前状态为 {entry.status}")
        related = tuple(related_entries)
        if not answer.strip() and not related:
            raise CognitionError("answered 必须记录答案摘要或关联 cognition id")
        for rid in related:
            self.get_entry(rid)  # 关联条目必须存在
        body_append = f"## 答案\n\n{answer.strip()}" if answer.strip() else None
        return self._plan_update(
            entry,
            action="answer",
            approval=approval,
            new_status="answered",
            add_related=related,
            body_append=body_append,
            history_note=answer.strip()[:80] if answer.strip() else "关联条目回答",
        )

    def answer_question(
        self,
        entry_id: str,
        *,
        answer: str,
        related_entries: Sequence[str] = (),
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """回答 question：置 answered 并记录答案/关联（人工批准）。"""
        return self.plan_answer_question(
            entry_id, answer=answer, related_entries=related_entries, approval=approval
        ).commit()

    def plan_supersede_entry(
        self,
        entry_id: str,
        *,
        replacement_statement: str,
        replacement_certainty: Optional[float],
        rationale: str,
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划实质修订：创建 successor（supersedes 旧 id），旧条目标 superseded。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        old = self._parse_entry(self._locate(entry_id))
        if old.status in ("superseded", "archived"):
            raise CognitionError(f"{entry_id} 已 {old.status}，不能再继任")
        create_plan = self._plan_create(
            entry_type=old.entry_type,
            title=old.title,
            statement=replacement_statement,
            status=DEFAULT_STATUS[old.entry_type],
            certainty=replacement_certainty,
            tags=old.tags,
            evidence=old.evidence,
            origin=dict(old.origin),
            rationale=rationale,
            history_action=f"supersede（继任 {old.id}）",
            approval=approval,
            supersedes=old.id,
        )
        new_id = str(create_plan.planned_id)
        old_plan = self._plan_update(
            old,
            action="superseded",
            approval=approval,
            new_status="superseded",
            history_note=f"被 {new_id} 继任；理由：{rationale}",
        )

        def commit() -> CognitionEntry:
            new_entry = create_plan.commit()
            old_plan.commit()
            return new_entry

        return WritePlan(
            action="supersede",
            diffs=create_plan.diffs + old_plan.diffs,
            summary=f"{old.id} 由新条目 {new_id} 继任，旧条目标 superseded",
            _commit=commit,
            planned_id=new_id,
            planned_path=create_plan.planned_path,
        )

    def supersede_entry(
        self,
        entry_id: str,
        *,
        replacement_statement: str,
        replacement_certainty: Optional[float],
        rationale: str,
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """实质修订：创建 successor 并建立 supersedes 关系。"""
        return self.plan_supersede_entry(
            entry_id,
            replacement_statement=replacement_statement,
            replacement_certainty=replacement_certainty,
            rationale=rationale,
            approval=approval,
        ).commit()

    def plan_archive_entry(
        self,
        entry_id: str,
        *,
        reason: str,
        approval: ApprovalRecord,
    ) -> WritePlan:
        """计划归档：置 archived（文件保留原路径）。"""
        if approval is None:
            raise CognitionError("语义变更必须携带显式 ApprovalRecord")
        entry = self._parse_entry(self._locate(entry_id))
        if entry.status == "archived":
            raise CognitionError(f"{entry_id} 已归档")
        return self._plan_update(
            entry,
            action="archive",
            approval=approval,
            new_status="archived",
            history_note=reason,
        )

    def archive_entry(
        self,
        entry_id: str,
        *,
        reason: str,
        approval: ApprovalRecord,
    ) -> CognitionEntry:
        """归档条目：status → archived，保留原路径与全部历史。"""
        return self.plan_archive_entry(
            entry_id, reason=reason, approval=approval
        ).commit()

    # ------------------------------------------------------------------
    # proposal 序列化
    # ------------------------------------------------------------------

    @staticmethod
    def _proposal_to_dict(
        proposal: "PromotionProposal | ChallengeProposal",
    ) -> dict:
        """序列化 proposal 为 JSON 字典。"""
        data: Dict[str, object] = {
            "kind": proposal.kind,
            "id": proposal.id,
            "status": proposal.status,
            "created": proposal.created,
            "decided_at": proposal.decided_at,
            "decision_reason": proposal.decision_reason,
        }
        if isinstance(proposal, PromotionProposal):
            data.update(
                {
                    "memory_id": proposal.memory_id,
                    "memory_path": proposal.memory_path,
                    "entry_type": proposal.entry_type,
                    "title": proposal.title,
                    "statement": proposal.statement,
                    "rationale": proposal.rationale,
                    "proposed_status": proposal.proposed_status,
                    "proposed_certainty": proposal.proposed_certainty,
                    "warnings": list(proposal.warnings),
                }
            )
        else:
            data.update(
                {
                    "entry_id": proposal.entry_id,
                    "evidence": [ref.to_dict() for ref in proposal.evidence],
                    "rationale": proposal.rationale,
                    "proposed_certainty": proposal.proposed_certainty,
                    "proposed_status": proposal.proposed_status,
                    "resolution": proposal.resolution,
                }
            )
        return data

    @staticmethod
    def _promotion_from_dict(data: dict) -> PromotionProposal:
        """从 JSON 字典还原 promotion proposal。"""
        return PromotionProposal(
            id=str(data["id"]),
            memory_id=str(data["memory_id"]),
            memory_path=str(data["memory_path"]),
            entry_type=str(data["entry_type"]),
            title=str(data["title"]),
            statement=str(data["statement"]),
            rationale=str(data.get("rationale") or ""),
            proposed_status=str(data["proposed_status"]),
            proposed_certainty=data.get("proposed_certainty"),
            status=str(data.get("status", "pending")),
            created=str(data.get("created") or ""),
            decided_at=data.get("decided_at"),
            decision_reason=data.get("decision_reason"),
            warnings=list(data.get("warnings") or []),
        )
