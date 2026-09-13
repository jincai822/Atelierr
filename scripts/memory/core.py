"""记忆模块核心：MemoryTree 与 MemorySettings（架构 v1.2）。

笔记存储：memory/ 根层 + 用户手动归档子目录（一级平台目录如
抖音/，二级中图法分类如 抖音/B84-心理学/）。机器创建/改写的文件
一律在根层；用户可在 Obsidian 里手动移动（机器永不移动笔记）。
特殊子目录 wiki/、attachments/、trash/、templates/、系统/ 与隐藏
目录（. 开头）是机器专用资产，永不参与笔记扫描/搜索/衰减/确认
回调（系统/ 放摘要、控制台等机器产物：它们是 Agent 的输出而非
记忆，扫进来会污染搜索排名与 references 引用信号）。
Syncthing 冲突副本（*.sync-conflict-*）同样一律跳过。sidecar
索引（<state_dir>/index.json）里的 path 是相对 notes_dir 的
POSIX 路径（含子目录前缀，如 ``抖音/x.md``）。动态状态
（confidence/layer/last_accessed/references/pending_delete）只写
sidecar；笔记文件创建后机器绝不改写。id 为 26 字符 ULID。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Tuple

import frontmatter

from scripts.memory.confidence import ConfidenceCalculator
from scripts.utils.config import load_config
from scripts.utils.date_utils import local_timezone

if TYPE_CHECKING:
    from scripts.memory.search import Memory, MemorySearcher

#: 合法逻辑层级（存于 sidecar，不是物理目录）
LAYERS: Tuple[str, str, str] = ("short-term", "mid-term", "long-term")

#: 永不参与笔记扫描的特殊子目录名（机器专用资产 + Obsidian 模板目录）
#: 机器产物目录名（摘要/控制台/划重点清单；NOTE_EXCLUDED_DIRS 成员）
SYSTEM_DIRNAME = "系统"

NOTE_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"wiki", "attachments", "trash", "templates", SYSTEM_DIRNAME}
)

#: Syncthing 冲突副本文件名模式（name.sync-conflict-YYYYMMDD-HHMMSS-XXX.md）：
#: 双端同改一篇笔记时生成的旁路副本，不是新笔记，扫描/登记/搜索一律跳过
SYNC_CONFLICT_RE = re.compile(r"\.sync-conflict-\d{8}-\d{6}")

#: 机器搬运来源（链接转写/截图 OCR/剪藏全文/划重点清单）：信噪比治理
#: （2026-09-12 用户裁决）——搜索降权（search.py）、复习不推（resurface.py，
#: 被 [[引用]] ≥1 次的除外）；人写笔记（web/manual/sync/lark 等）不受影响
MACHINE_SOURCES: frozenset[str] = frozenset(
    {"link", "media", "webclip", "highlights"}
)

#: 方案 C 差异化衰减（2026-09-12 用户特批修订锁定契约 v1.3→v1.4）：
#: 自动管线转写（link/media）的闲置时间轴乘 MACHINE_DECAY_FACTOR——
#: 无人碰的转写约 15 天触及 pending_delete（人写笔记 45 天），
#: 工作记忆自我清洁；webclip 是人主动剪藏、highlights 是周日人工
#: 清单，均按原速（不在此表）。公式同形仍是无状态纯函数，
#: 只是 idle 按来源乘因子。被 [[引用]] 照旧经 ref_factor 减缓，
#: 访问照旧重置闲置时钟——有人用的卡不会消失。
MACHINE_DECAY_SOURCES: frozenset[str] = frozenset({"link", "media"})
MACHINE_DECAY_FACTOR: float = 3.0

#: 日记判定（2026-09-13 用户裁决）：YYYY-MM-DD.md 文件名或位于 日记/
#: 子目录——日记是时间档案，性质是"保存"不是"复习"，豁免 decay 分层
#: 与待删标记（不进待删清单、不进复习队列；照常登记、照常可搜）
DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
DAILY_NOTE_DIR = "日记"


def is_daily_note(note_path: Path) -> bool:
    """是否日记（时间档案）：文件名是 YYYY-MM-DD.md 或在 日记/ 子目录下。"""
    path = Path(note_path)
    return bool(DAILY_NOTE_RE.match(path.name)) or path.parent.name == DAILY_NOTE_DIR


#: Crockford base32 字母表（ULID 用，去除 I/L/O/U）
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_id() -> str:
    """生成 26 字符 ULID：48bit 毫秒时间戳 + 80bit 随机（stdlib 实现）。

    Returns:
        str: 26 字符 Crockford base32 编码的 ULID。
    """
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    value = (timestamp_ms << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> (5 * i)) & 0x1F] for i in range(25, -1, -1))


def _now_iso() -> str:
    """当前本地时间的 ISO 字符串（秒精度）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _str_list(value: object) -> List[str]:
    """把 frontmatter 元数据值规范为字符串列表（非列表/元组返回空）。"""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def iter_note_files(notes_dir: Path) -> Iterator[Path]:
    """递归列出笔记 .md 文件（search/decay/watcher/确认回调共用）。

    排除：NOTE_EXCLUDED_DIRS 机器专用目录（wiki/attachments/trash/
    templates/系统/）与隐藏目录（. 开头）、隐藏文件（. 开头）、
    Syncthing 冲突副本（*.sync-conflict-*）；不跟随符号链接目录
    （防环与目录逃逸）。产出按目录/文件名排序，稳定可复现。

    Args:
        notes_dir: 笔记根目录。

    Returns:
        Iterator[Path]: 每个 .md 笔记的绝对路径。
    """
    for dirpath, dirnames, filenames in os.walk(notes_dir):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and name not in NOTE_EXCLUDED_DIRS
        )
        for filename in sorted(filenames):
            if (
                filename.startswith(".")
                or not filename.endswith(".md")
                or SYNC_CONFLICT_RE.search(filename)
            ):
                continue
            yield Path(dirpath) / filename


@dataclass
class MemorySettings:
    """分层阈值与衰减参数配置。

    Attributes:
        short_term_min: confidence >= 该值 → short-term（默认 0.7）。
        mid_term_min: confidence >= 该值 → mid-term，否则 long-term（默认 0.4）。
        decay_rate: 无引用每日衰减率（默认 0.95）。
        ref_coefficient: 引用减缓系数（默认 0.2）。
        ref_cap: 引用数封顶（默认 10）。
        delete_threshold: confidence 低于该值置 pending_delete（默认 0.1）。
        machine_decay_factor: MACHINE_DECAY_SOURCES 来源的闲置时间轴
            因子（默认 MACHINE_DECAY_FACTOR=3.0，方案 C v1.4）。
    """

    short_term_min: float = 0.7
    mid_term_min: float = 0.4
    decay_rate: float = 0.95
    ref_coefficient: float = 0.2
    ref_cap: int = 10
    delete_threshold: float = 0.1
    machine_decay_factor: float = MACHINE_DECAY_FACTOR

    def assign_layer(self, confidence: float) -> str:
        """按 confidence 分配逻辑层级。

        Args:
            confidence: [0, 1] 的 confidence 值。

        Returns:
            str: "short-term" / "mid-term" / "long-term"。
        """
        if confidence >= self.short_term_min:
            return "short-term"
        if confidence >= self.mid_term_min:
            return "mid-term"
        return "long-term"


class MemoryTree:
    """记忆模块核心：管理平面笔记目录与 sidecar 状态索引。

    笔记文件永不被机器移动/改写；一切动态状态存于 sidecar。
    """

    def __init__(
        self,
        ov_path: str,
        state_dir: Optional[str] = None,
        inbox_dir: Optional[str] = None,
        attachments_dir: Optional[str] = None,
    ) -> None:
        """初始化平面笔记目录、中转站目录与 sidecar 状态目录（不存在则创建）。

        Args:
            ov_path: 平面笔记目录（即 $OV/memory，真记忆：你写的+你确认
                归档的）。
            state_dir: 状态目录（sidecar/报告/回收站）；未给时默认
                notes_dir.parent / "state"（仅为便利默认值）。
            inbox_dir: 中转站目录（机器产出卡的落点：待确认→确认归档后
                移进 memory/ 平台目录）；未给时默认 notes_dir.parent /
                "inbox"（2026-09-13 用户裁决：memory/ 只存真记忆，
                中转与源文件拆出）。
            attachments_dir: 源文件区目录；未给时默认 notes_dir.parent /
                "attachments"。
        """
        self.notes_dir = Path(ov_path).expanduser()
        self.state_dir = (
            Path(state_dir).expanduser()
            if state_dir
            else self.notes_dir.parent / "state"
        )
        self.inbox_dir = (
            Path(inbox_dir).expanduser()
            if inbox_dir
            else self.notes_dir.parent / "inbox"
        )
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        # 源文件区（attachments/）2026-09-13 起挪到数据根平级：
        # memory/ 只存真记忆；Obsidian 库根在数据根，链接后缀匹配不断
        self.attachments_dir = (
            Path(attachments_dir).expanduser()
            if attachments_dir
            else self.notes_dir.parent / "attachments"
        )
        self.settings = MemorySettings()
        self.index_path = self.state_dir / "index.json"
        self._index: Optional[Dict[str, dict]] = None
        self._searcher: Optional["MemorySearcher"] = None

    # ------------------------------------------------------------------
    # sidecar 索引（原子写；损坏时备份并从空索引重建）
    # ------------------------------------------------------------------

    def _load_index(self) -> Dict[str, dict]:
        """读取 sidecar 索引（内存缓存，惰性加载）。"""
        if self._index is None:
            self._index = self._read_index()
        return self._index

    def _read_index(self) -> Dict[str, dict]:
        """从磁盘读索引；损坏时重命名为 .bak 并从空索引重建。"""
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self._backup_corrupt_index()
            return {}
        return data if isinstance(data, dict) else {}

    def _backup_corrupt_index(self) -> None:
        """把损坏的 index.json 改名为 index.json.bak。"""
        try:
            os.replace(
                self.index_path,
                self.index_path.with_name(self.index_path.name + ".bak"),
            )
        except OSError:
            pass

    def _write_index(self, index: Dict[str, dict]) -> None:
        """原子写指定索引内容：先写临时文件再 rename。"""
        tmp = self.index_path.with_name(self.index_path.name + ".tmp")
        tmp.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.index_path)

    def _save_index(self) -> None:
        """把本进程缓存的索引原子写盘（读路径兼容保留；改索引请走
        ``_index_transaction``——缓存回写在多进程交叠时会丢更新）。"""
        self._write_index(self._load_index())

    @contextmanager
    def _index_transaction(self) -> Iterator[Dict[str, dict]]:
        """flock 保护的「读最新 → 改 → 原子写」事务（多进程写者防丢更新）。

        sidecar 的写者不止一个：常驻飞书守护（卡片回调）、15 分钟分发
        班次、decay/晨报 CLI 都会改 index.json。「缓存 + 无条件回写」
        在写者交叠时会丢更新（2026-09-13 实证：守护刚写下的
        pending_delete 标记被并发班次的旧缓存回写冲掉）。事务内读
        磁盘最新版，提交时原子写并刷新本进程缓存。**同进程不得嵌套**
        （flock 换 fd 会自锁）——嵌套场景（如 watcher 全量对齐）在
        事务内直接改传入的 index 字典。
        """
        lock_path = self.index_path.with_name(self.index_path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                index = self._read_index()
                yield index
                self._write_index(index)
                self._index = index
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    def _rel_key(self, note_path: Path) -> str:
        """笔记绝对路径 → 索引相对 key（POSIX / 分隔，含子目录前缀）。

        双根（2026-09-13 用户裁决拆分）：memory/ 内是相对 notes_dir
        的原样路径；inbox/ 内（中转站）加 ``inbox/`` 虚拟前缀；
        两根之外的路径退回纯文件名（维持旧顶层行为）。索引里存的
        path 一律由此产生，``_abs(entry["path"])`` 可还原出原文件。
        """
        path = Path(note_path)
        try:
            return path.relative_to(self.notes_dir).as_posix()
        except ValueError:
            pass
        try:
            return "inbox/" + path.relative_to(self.inbox_dir).as_posix()
        except ValueError:
            return path.name

    def _abs(self, rel: str) -> Path:
        """索引相对 key → 绝对路径。

        - ``inbox/`` 前缀解析到中转站目录；若该文件不在中转站、却在
          memory/inbox/ 真实子目录里存在（用户误建了保留名子目录），
          回退到 memory/ 侧（契约保留名：memory/ 下禁止建 inbox/ 子目录，
          此回退仅为不丢数据的兜底）；
        - 无前缀的纯文件名（如分发报告的 created 列表）按存在性探测：
          memory/ 优先，其次 inbox/；都不存在时返回 memory/ 侧路径
          （让调用方得到一致的"不存在"语义）。
        """
        rel = str(rel)
        if rel.startswith("inbox/"):
            primary = self.inbox_dir / rel[len("inbox/"):]
            if primary.exists():
                return primary
            alt = self.notes_dir / rel
            if alt.exists():
                return alt
            return primary
        candidate = self.notes_dir / rel
        if candidate.exists() or "/" in rel:
            return candidate
        inbox_candidate = self.inbox_dir / rel
        if inbox_candidate.exists():
            return inbox_candidate
        return candidate

    def _entry(self, note_path: Path) -> Optional[dict]:
        """按相对路径反查 sidecar 条目，未登记返回 None。"""
        key = self._rel_key(note_path)
        for entry in self._load_index().values():
            if entry.get("path") == key:
                return entry
        return None

    def _find_entry_id(self, note_path: Path) -> Optional[str]:
        """按相对路径反查 sidecar 条目 id。"""
        key = self._rel_key(note_path)
        for nid, entry in self._load_index().items():
            if entry.get("path") == key:
                return nid
        return None

    def _require_entry(self, note_path: Path) -> dict:
        """返回必存在条目；文件缺失或未登记均抛 FileNotFoundError。"""
        path = Path(note_path)
        if not path.exists():
            raise FileNotFoundError(f"笔记不存在: {path}")
        entry = self._entry(path)
        if entry is None:
            raise FileNotFoundError(f"笔记未登记在索引中: {path}")
        return entry

    def _register(
        self,
        note_path: Path,
        note_id: str,
        *,
        confidence: float = 1.0,
        layer: str = "short-term",
        last_accessed: Optional[str] = None,
        references: int = 0,
        pending_delete: bool = False,
    ) -> None:
        """登记/更新一条 sidecar 条目并原子写盘（flock 事务）。"""
        with self._index_transaction() as index:
            index[str(note_id)] = {
                "path": self._rel_key(note_path),
                "confidence": confidence,
                "layer": layer,
                "last_accessed": last_accessed,
                "references": references,
                "pending_delete": pending_delete,
            }

    def _remove_entry(self, note_path: Path) -> None:
        """按相对路径移除 sidecar 条目（flock 事务）。"""
        key = self._rel_key(note_path)
        with self._index_transaction() as index:
            for nid, entry in list(index.items()):
                if entry.get("path") == key:
                    del index[nid]
                    return

    def _read_note_id(self, path: Path) -> Optional[str]:
        """读取文件 frontmatter 中的 id；无 frontmatter 或损坏返回 None。"""
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏 frontmatter 视为无 id
            return None
        note_id = post.metadata.get("id")
        return str(note_id) if note_id is not None else None

    def _ensure_registered(self, path: Path) -> dict:
        """文件存在但未登记时，用 frontmatter id（缺失则生成）登记默认条目。"""
        note_id = self._read_note_id(path) or generate_id()
        self._register(path, note_id)
        entry = self._entry(path)
        assert entry is not None
        return entry

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def create_note(
        self,
        filename: str,
        content: str,
        source: str = "unknown",
        tags: Optional[List[str]] = None,
        inbox: bool = False,
    ) -> Path:
        """创建新笔记，写一次性 frontmatter，登记 sidecar。

        content 自带合法 frontmatter 时复用其元数据，缺失的
        id/title/created/source/tags 补默认值。

        Args:
            filename: 纯文件名（不含目录分量），必须以 .md 结尾。
            content: 笔记正文（可含合法 frontmatter）。
            source: 来源（web/obsidian/lark/agent/reflection 等）。
            tags: 标签列表。
            inbox: True 时落中转站（inbox/）：机器产出卡的落点
                （2026-09-13 用户裁决拆分：memory/ 只存真记忆，
                中转卡确认归档后才移进 memory/ 平台目录）；缺省 False
                落 memory/ 根。

        Returns:
            Path: 新笔记的绝对路径。

        Raises:
            ValueError: 文件名含目录分量或非 .md。
            FileExistsError: 同名笔记已存在（绝不覆盖）。
        """
        if Path(filename).name != filename:
            raise ValueError(f"文件名不能包含目录分量: {filename!r}")
        if not filename.endswith(".md"):
            raise ValueError(f"文件名必须以 .md 结尾: {filename!r}")
        target = (self.inbox_dir if inbox else self.notes_dir) / filename
        # 同名检查跨双根（2026-09-13 拆分）：中转卡名撞上 memory/ 里的
        # 既有笔记同样拒绝——两个同名文件散在两个目录比报错更糟
        other = (self.notes_dir if inbox else self.inbox_dir) / filename
        if target.exists() or other.exists():
            raise FileExistsError(f"笔记已存在: {filename}")

        post = self._parse_or_build_post(content, filename, source, tags)
        target.write_text(frontmatter.dumps(post), encoding="utf-8")
        note_id = str(post.metadata.get("id") or generate_id())
        self._register(target, note_id)
        return target

    def _parse_or_build_post(
        self,
        content: str,
        filename: str,
        source: str,
        tags: Optional[List[str]],
    ):
        """解析 content，复用合法 frontmatter 元数据并补齐必需字段。"""
        try:
            post = frontmatter.loads(content)
        except Exception:  # noqa: BLE001 - 非法 frontmatter 按纯正文处理
            post = frontmatter.Post(content)
        defaults = {
            "id": generate_id(),
            "title": Path(filename).stem,
            "created": _now_iso(),
            "source": source,
            "tags": list(tags or []),
        }
        for key, value in defaults.items():
            post.metadata.setdefault(key, value)
        return post

    def iter_all_note_files(self) -> Iterator[Path]:
        """双根扫描：memory/（真记忆）+ inbox/（中转站）的全部笔记 .md。

        2026-09-13 用户裁决拆分后，watcher/decay/search/确认回调一律
        走这里（单根的 iter_note_files 仅保留给明确的单域场景）。
        """
        yield from iter_note_files(self.notes_dir)
        yield from iter_note_files(self.inbox_dir)

    def read_note(self, note_path: Path) -> str:
        """读取笔记正文（去掉 frontmatter，.strip()）。

        Args:
            note_path: 笔记文件路径。

        Returns:
            str: 正文内容。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        path = Path(note_path)
        if not path.exists():
            raise FileNotFoundError(f"笔记不存在: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            post = frontmatter.loads(text)
            return post.content.strip()
        except Exception:  # noqa: BLE001 - 损坏 frontmatter 返回全文
            return text.strip()

    def move_note(self, note_path: Path, layer: str) -> Path:
        """手动覆写逻辑层级（只写 sidecar，文件不动）。

        Args:
            note_path: 笔记文件路径。
            layer: 目标层级（short-term/mid-term/long-term）。

        Returns:
            Path: 原笔记路径（不变）。

        Raises:
            ValueError: layer 非法。
            FileNotFoundError: 文件不存在。
        """
        if layer not in LAYERS:
            raise ValueError(f"非法层级: {layer!r}，可选 {', '.join(LAYERS)}")
        path = Path(note_path)
        if not path.exists():
            raise FileNotFoundError(f"笔记不存在: {path}")
        entry = self._entry(path)
        if entry is None:
            entry = self._ensure_registered(path)
        entry["layer"] = layer
        self._save_index()
        return path

    def relocate_entry(self, note_id: str, new_rel: str) -> bool:
        """按 id 迁移 sidecar 条目 path（笔记文件移动后立即调用）。

        用于飞书卡片归档等"移动后即时迁移"路径：只改 path 字段，
        其余动态状态（last_accessed/confidence/references 等）原样
        保留；与 watcher 全量对齐的迁移逻辑同源（都是"id 不变 →
        条目跟着文件走"）。

        Args:
            note_id: frontmatter id（或已登记的索引 key）。
            new_rel: 新相对 notes_dir 的 POSIX 路径（含子目录前缀）。

        Returns:
            bool: 找到并迁移返回 True；索引里没有该 id 返回 False
                （调用方可忽略——watcher 下一班全量对齐会补登记）。
        """
        entry = self._load_index().get(str(note_id))
        if entry is None:
            return False
        with self._index_transaction() as index:
            fresh = index.get(str(note_id))
            if fresh is None:
                return False
            fresh["path"] = new_rel
        return True

    def list_notes(self, layer: str) -> List[Path]:
        """按 sidecar 中的 layer 列出笔记（仅返回仍存在的文件）。

        Args:
            layer: 逻辑层级。

        Returns:
            List[Path]: 该层级的笔记路径列表（按文件名排序）。

        Raises:
            ValueError: layer 非法。
        """
        if layer not in LAYERS:
            raise ValueError(f"非法层级: {layer!r}，可选 {', '.join(LAYERS)}")
        result = []
        for entry in self._load_index().values():
            if entry.get("layer") == layer:
                path = self._abs(entry["path"])
                if path.exists():
                    result.append(path)
        return sorted(result)

    def layer_of(self, note_path: Path) -> str:
        """从 sidecar 查询笔记的逻辑层级（按 path 反查 id）。

        Args:
            note_path: 笔记文件路径。

        Returns:
            str: 逻辑层级。

        Raises:
            FileNotFoundError: 文件不存在或未登记。
        """
        return self._require_entry(note_path)["layer"]

    def is_pending_delete(self, note_path: Path) -> bool:
        """查询笔记是否被标记待删除。

        Args:
            note_path: 笔记文件路径。

        Returns:
            bool: 是否 pending_delete；未登记返回 False。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        path = Path(note_path)
        if not path.exists():
            raise FileNotFoundError(f"笔记不存在: {path}")
        entry = self._entry(path)
        return bool(entry["pending_delete"]) if entry else False

    def set_pending_delete(self, note_path: Path, flag: bool = True) -> bool:
        """标/摘 pending_delete（多进程安全的公共 API，flock 事务）。

        直改条目字典再 _save_index 的旧写法（缓存回写）在守护进程与
        分发班次交叠时会丢更新（2026-09-13 实证），统一走这里。

        Args:
            note_path: 笔记文件路径。
            flag: True 标记待删，False 摘除标记。

        Returns:
            bool: 条目存在并更新返回 True；未登记返回 False。
        """
        key = self._rel_key(note_path)
        with self._index_transaction() as index:
            for entry in index.values():
                if entry.get("path") == key:
                    entry["pending_delete"] = flag
                    return True
        return False

    def on_note_accessed(self, note_path: Path) -> None:
        """记录访问：更新 sidecar 的 last_accessed（闲置时钟归零）。

        只写 sidecar；文件未登记但存在时先按默认值登记再更新。

        Args:
            note_path: 笔记文件路径。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        path = Path(note_path)
        if not path.exists():
            raise FileNotFoundError(f"笔记不存在: {path}")
        key = self._rel_key(path)
        with self._index_transaction() as index:
            entry = next(
                (item for item in index.values() if item.get("path") == key), None
            )
            if entry is None:
                note_id = self._read_note_id(path) or generate_id()
                entry = {
                    "path": key,
                    "confidence": 1.0,
                    "layer": "short-term",
                    "last_accessed": None,
                    "references": 0,
                    "pending_delete": False,
                }
                index[str(note_id)] = entry
            entry["last_accessed"] = _now_iso()

    def list_pending_delete(self) -> List[Path]:
        """列出标记 pending_delete 且文件仍存在的笔记（供 review/purge）。

        Returns:
            List[Path]: 待删除笔记路径列表。
        """
        result = []
        for entry in self._load_index().values():
            if entry.get("pending_delete"):
                path = self._abs(entry["path"])
                if path.exists():
                    result.append(path)
        return sorted(result)

    def note_info(self, note_path: Path) -> Dict:
        """汇总单个笔记的静态元数据与动态状态（含 live confidence）。

        Args:
            note_path: 笔记文件路径。

        Returns:
            Dict: path/id/title/created/source/tags/layer/confidence/
                references/last_accessed/pending_delete。

        Raises:
            FileNotFoundError: 文件不存在或未登记。
        """
        path = Path(note_path)
        entry = self._require_entry(path)
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        calculator = ConfidenceCalculator(
            decay_rate=self.settings.decay_rate,
            ref_coefficient=self.settings.ref_coefficient,
            ref_cap=self.settings.ref_cap,
            source_factors={
                source: self.settings.machine_decay_factor
                for source in MACHINE_DECAY_SOURCES
            },
        )
        confidence = calculator.calculate(
            {
                "accessed": entry.get("last_accessed"),
                "modified": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=local_timezone()
                ),
                "references": entry.get("references", 0),
                "source": str(post.metadata.get("source") or ""),
            }
        )
        return {
            "path": path,
            "id": post.metadata.get("id"),
            "title": post.metadata.get("title"),
            "created": post.metadata.get("created"),
            "source": post.metadata.get("source"),
            "tags": _str_list(post.metadata.get("tags")),
            "layer": entry["layer"],
            "confidence": confidence,
            "references": entry.get("references", 0),
            "last_accessed": entry.get("last_accessed"),
            "pending_delete": bool(entry.get("pending_delete")),
        }

    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        layer: Optional[str] = None,
        limit: int = 10,
    ) -> List["Memory"]:
        """搜索记忆（委托 MemorySearcher，结果按 confidence 降序）。

        Args:
            query: 全文关键词（大小写不敏感子串匹配）。
            tags: 标签过滤（任一命中即算，OR 语义）。
            date_from: 起始日期 "YYYY-MM-DD"（闭区间）。
            date_to: 结束日期 "YYYY-MM-DD"（闭区间）。
            layer: 逻辑层级过滤。
            limit: 返回条数上限。

        Returns:
            List[Memory]: 搜索结果。
        """
        from scripts.memory.search import MemorySearcher

        if self._searcher is None:
            self._searcher = MemorySearcher(self)
        return self._searcher.search(
            query=query,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
            layer=layer,
            limit=limit,
        )

    def get_stats(self) -> Dict:
        """获取记忆统计信息（仅统计文件仍存在的条目）。

        Returns:
            Dict: total / layers（分层计数）/ pending_delete /
                avg_confidence / notes_dir / state_dir。
        """
        layer_counts = {layer: 0 for layer in LAYERS}
        pending = 0
        total = 0
        confidence_sum = 0.0
        for entry in self._load_index().values():
            path = self._abs(entry["path"])
            if not path.exists():
                continue
            total += 1
            layer = entry.get("layer", "short-term")
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
            if entry.get("pending_delete"):
                pending += 1
            confidence_sum += entry.get("confidence", 0.0)
        return {
            "total": total,
            "layers": layer_counts,
            "pending_delete": pending,
            "avg_confidence": confidence_sum / total if total else 0.0,
            "notes_dir": str(self.notes_dir),
            "state_dir": str(self.state_dir),
        }

    @classmethod
    def from_config(cls, config_path: str) -> "MemoryTree":
        """从 YAML 配置构造 MemoryTree 并装载阈值配置。

        读取 memory.root / memory.state_dir / memory.layers.* /
        memory.decay.*；缺失字段沿用 MemorySettings 默认值。

        Args:
            config_path: YAML 配置文件路径。

        Returns:
            MemoryTree: 配置好的实例。

        Raises:
            FileNotFoundError: 配置文件不存在。
        """
        config = load_config(config_path)
        memory = (config or {}).get("memory", {}) or {}
        # inbox_dir 缺省不显式给生产路径：None 时由 __init__ 取
        # root.parent/"inbox"（测试的临时 root 不会扫到生产 inbox——
        # 2026-09-13 实证：硬编码默认值让测试 watcher 把生产库登记进来）
        tree = cls(
            memory.get("root", "~/atelierr-data/memory"),
            state_dir=memory.get("state_dir", "~/atelierr-data/state"),
            inbox_dir=memory.get("inbox_dir"),
            attachments_dir=memory.get("attachments_dir"),
        )
        layers = memory.get("layers", {}) or {}
        decay = memory.get("decay", {}) or {}
        tree.settings = MemorySettings(
            short_term_min=float(
                layers.get("short_term_min", tree.settings.short_term_min)
            ),
            mid_term_min=float(layers.get("mid_term_min", tree.settings.mid_term_min)),
            decay_rate=float(decay.get("rate", tree.settings.decay_rate)),
            ref_coefficient=float(
                decay.get("ref_coefficient", tree.settings.ref_coefficient)
            ),
            ref_cap=int(decay.get("ref_cap", tree.settings.ref_cap)),
            delete_threshold=float(
                decay.get("delete_threshold", tree.settings.delete_threshold)
            ),
            machine_decay_factor=float(
                decay.get(
                    "machine_factor", tree.settings.machine_decay_factor
                )
            ),
        )
        return tree
