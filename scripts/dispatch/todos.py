"""待办自动分发：扫描新笔记 → 显式标记直转 / LLM 判定 → 建待办笔记。

定位与纪律（与 dispatch/links.py 同源，dispatch 是唯一接线点）：
- 只新增待办笔记，绝不改写/移动/删除既有笔记（源笔记原样保留）；
- 两类通道（并行，不互斥）：
  1. 显式：笔记含 ``- [ ]`` 任务行或 ``#todo``/``#待办`` 行内标记 →
     直接转待办，不过 LLM，产出**不带**"待确认"（人已显式表达意图）；
  2. 自动：LLM 补充判定同篇笔记的其余内容，保守原则（纯观点/摘抄/
     感慨不建；意愿词如"想看/打算"算行动意图，由"待确认"人工兜底），
     产出带"待确认"标签，人工在产出端确认；对链接产出笔记
     （source=link）只把"观点总结 + 分观点论述"两节喂给分类器
     （省 token、信号干净）；两通道文本重叠时由待办笔记的
     文件名哈希去重，不会重复建；
- 幂等：``<state_dir>/processed_todos.json`` 按笔记记内容哈希；内容未变
  不重判，变化后重判（日记会追加新内容），重复行动项由待办笔记的
  文件名哈希去重拦截，不会重复建；失败最多重试 3 次熔断；
  key 缺失时不记状态（补 key 后自动补判）；
- 防自循环：带"待办"标签的笔记（含本模块产出）跳过扫描；
- 待办 = 普通笔记 + "待办"标签，层级由 confidence 自动决定——三层是
  置信度保鲜层而非语义分类，不开新层。

LLM 配置：可选配置文件节 ``dispatch.todos.llm``（config/processors.yaml
或 .example），缺省用模块内置默认；API key 只从环境变量读取（默认
DEEPSEEK_API_KEY），任何 LLM 失败不阻塞其他笔记。

单元测试 monkeypatch ``httpx.post`` 与环境变量，无真实网络。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter
import httpx
import yaml

from scripts.memory.core import LAYERS, MemoryTree
from scripts.memory.watcher import MemoryWatcher
from scripts.processors.base import CONFIG_FILES
from scripts.processors.link import URL_RE, URL_TRAILING, detect_platform

#: 单条笔记的最大处理尝试次数（超限标记 failed）
MAX_ATTEMPTS = 3

#: 待办笔记标签 / LLM 产出的待确认标签
TODO_TAG = "待办"
REVIEW_TAG = "待确认"

#: 显式通道：未勾选任务行 / 行内标记
_TASK_LINE_RE = re.compile(r"^\s*- \[ \] (?P<text>.+?)\s*$", re.M)
#: 行内标记（前面不能是 "tag:"——那是 Obsidian 查询语法，2026-09-01 实测
#: 主页笔记的 ```query tag:#待办``` 被误抽成待办 "tag:"）
_INLINE_TAG_RE = re.compile(r"(?<!tag:)#(?:todo|待办)(?=\s|$)")
#: 围栏代码块（query 等）内容不算显式标记
_FENCED_BLOCK_RE = re.compile(r"^```.*?^```\s*", re.M | re.S)

#: LLM 默认接入点（OpenAI 兼容）与限额
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_MAX_BODY_CHARS = 2000

#: 截止日格式（Tasks 插件 📅 后使用）
_DUE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _load_todos_config() -> Dict[str, Any]:
    """读取配置文件 ``dispatch.todos`` 节（缺失/损坏返回空表）。"""
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
            if isinstance(section, dict) and isinstance(section.get("todos"), dict):
                return dict(section["todos"])
    return {}


def _extract_explicit(body: str) -> List[Dict[str, Any]]:
    """显式通道抽取：``- [ ]`` 任务行优先，其次行内 #todo/#待办 标记。

    先剥掉围栏代码块（Obsidian ```query 等），块内内容不算标记。

    Args:
        body: 笔记正文（不含 frontmatter）。

    Returns:
        List[Dict[str, Any]]: [{"text", "due": None}]；无显式标记为空表。
    """
    body = _FENCED_BLOCK_RE.sub("", body)
    items = [
        {"text": match.group("text").strip(), "due": None}
        for match in _TASK_LINE_RE.finditer(body)
        if match.group("text").strip()
    ]
    if items:
        return items
    for line in body.splitlines():
        if _INLINE_TAG_RE.search(line):
            text = _INLINE_TAG_RE.sub("", line).strip(" -")
            if text:
                items.append({"text": text, "due": None})
    return items


def _summary_sections(body: str) -> str:
    """取"观点总结 + 分观点论述"两节（无则空串）。

    Args:
        body: 笔记正文。

    Returns:
        str: 两节拼接文本。
    """
    sections = re.split(r"^## ", body, flags=re.M)
    picked = [s for s in sections if s.startswith(("观点总结", "分观点论述"))]
    return "\n\n".join(picked)


def _llm_input(body: str, source: str) -> str:
    """构造喂给分类器的文本：链接产出笔记只取摘要两节，其余取全文。

    Args:
        body: 笔记正文。
        source: 笔记 frontmatter 的 source 字段。

    Returns:
        str: 截断到 _LLM_MAX_BODY_CHARS 的输入文本。
    """
    if source == "link":
        picked = _summary_sections(body)
        if picked:
            return picked[:_LLM_MAX_BODY_CHARS]
    return body[:_LLM_MAX_BODY_CHARS]


class TodoDispatcher:
    """扫描全部笔记，把含行动意图的内容分发为待办笔记。

    Attributes:
        tree: MemoryTree 实例。
        state_path: 处理状态文件（processed_todos.json）。
    """

    def __init__(self, tree: MemoryTree, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            config: dispatch.todos 配置节（llm 子节覆盖默认值）；
            缺省按配置文件加载。
        """
        self.tree = tree
        cfg = config if config is not None else _load_todos_config()
        llm_cfg = cfg.get("llm") or {}
        self.llm_base_url = str(llm_cfg.get("base_url", _LLM_DEFAULT_BASE_URL))
        self.llm_model = str(llm_cfg.get("model", _LLM_DEFAULT_MODEL))
        self.llm_api_key_env = str(llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY"))
        self.llm_max_tokens = int(llm_cfg.get("max_tokens", 800))
        self.llm_timeout = float(llm_cfg.get("timeout", 60))
        self.state_path = Path(tree.state_dir) / "processed_todos.json"

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """执行一轮扫描与分发。

        Args:
            dry_run: 只报告不处理（不建笔记、不写状态）。

        Returns:
            Dict[str, Any]: 运行报告（scanned/candidates/created/skipped/failed）。
        """
        MemoryWatcher(self.tree, source="sync").process_pending()
        state = self._load_state()
        report: Dict[str, Any] = {
            "scanned": 0,
            "candidates": 0,
            "created": [],
            "created_review": [],
            "skipped": 0,
            "failed": [],
        }
        for layer in LAYERS:
            for note_path in self.tree.list_notes(layer):
                report["scanned"] += 1
                self._process_note(note_path, state, report, dry_run)
        if not dry_run:
            self._save_state(state)
        return report

    def _process_note(
        self,
        note_path: Path,
        state: Dict[str, Any],
        report: Dict[str, Any],
        dry_run: bool,
    ) -> None:
        """处理单篇笔记：跳过规则 → 显式抽取 → LLM 判定 → 建待办。"""
        if self.tree.is_pending_delete(note_path):
            report["skipped"] += 1
            return
        try:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report["skipped"] += 1
            return
        tags = post.get("tags") or []
        # 防自循环（含本模块产出）；摘要笔记不再喂 LLM（内容全是既有待办）
        if TODO_TAG in tags or "todo" in tags or post.get("source") == "digest":
            report["skipped"] += 1
            return
        body = post.content
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
        key = note_path.name
        api_key = os.environ.get(self.llm_api_key_env, "").strip()
        entry = state.get(key)
        if entry and entry.get("hash") == digest and (
            entry.get("llm_done") or not api_key
        ):
            report["skipped"] += 1  # 内容未变，且 LLM 已判过或本轮无 key
            return

        # 显式通道：每轮都可跑（文件名去重兜底，无调用成本）
        created: List[str] = []
        explicit_items = _extract_explicit(body)
        if dry_run:
            report["candidates"] += len(explicit_items)
        else:
            for item in explicit_items:
                filename = self._create_todo_note(
                    item, note_path, review=False, dry_run=False
                )
                if filename:
                    created.append(filename)
        # LLM 通道：有 key 且未熔断才判定
        llm_done = False
        llm_items: List[Dict[str, Any]] = []
        llm_blocked = bool(
            entry
            and entry.get("status") == "failed"
            and entry.get("attempts", 0) >= MAX_ATTEMPTS
        )
        if api_key and not llm_blocked:
            if dry_run:
                report["candidates"] += 1
                return
            work = state.setdefault(key, {})
            work["attempts"] = int(work.get("attempts", 0)) + 1
            work["last_attempt"] = datetime.now(timezone.utc).isoformat()
            try:
                llm_text = _llm_input(body, str(post.get("source") or ""))
                extra = self._linked_summaries(body)
                if extra:
                    llm_text = (
                        llm_text + "\n\n链接内容摘要：\n" + extra
                    )[: _LLM_MAX_BODY_CHARS * 2]
                llm_items = self._chat_todos(llm_text, api_key)
            except Exception as exc:  # noqa: BLE001 - 单篇失败不阻塞整轮
                work["last_error"] = type(exc).__name__[:100]
                if work["attempts"] >= MAX_ATTEMPTS:
                    work["status"] = "failed"
                report["failed"].append({"note": key, "error": type(exc).__name__})
            else:
                llm_done = True
                for item in llm_items:
                    filename = self._create_todo_note(
                        item, note_path, review=True, dry_run=False
                    )
                    if filename:
                        created.append(filename)
                        report["created_review"].append(filename)
        if dry_run:
            return
        if key in state or explicit_items or llm_done:
            work = state.setdefault(key, {})
            work.setdefault("attempts", 0)
            if work.get("status") != "failed":
                work["status"] = "done" if created else "no-todo"
            work.update({"hash": digest, "created": created, "llm_done": llm_done})
        report["candidates"] += len(explicit_items) + len(llm_items)
        report["created"].extend(created)

    def _create_todo_note(
        self, item: Dict[str, Any], source_path: Path, review: bool, dry_run: bool
    ) -> Optional[str]:
        """建一条待办笔记（单行动作 + 来源双链）；重名视为已创建。

        Args:
            item: {"text", "due"}。
            source_path: 来源笔记路径。
            review: True 时加"待确认"标签（LLM 通道）。
            dry_run: 只返回文件名不落盘。

        Returns:
            Optional[str]: 笔记文件名；空文本/重名返回 None。
        """
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        due = item.get("due")
        due = due if isinstance(due, str) and _DUE_RE.fullmatch(due) else None
        date_str = datetime.now().strftime("%Y%m%d")
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
        filename = f"todo-{date_str}-{digest}.md"
        task_line = f"- [ ] {text}" + (f" 📅 {due}" if due else "")
        markdown = (
            f"# {text[:30]}\n\n{task_line}\n\n> 来源：[[{source_path.stem}]]\n"
        )
        if dry_run:
            return filename
        tags = [TODO_TAG] + ([REVIEW_TAG] if review else [])
        try:
            self.tree.create_note(filename, markdown, source="todo", tags=tags)
        except (ValueError, FileExistsError):
            return None
        return filename

    def _linked_summaries(self, body: str) -> str:
        """正文中已处理抖音链接的产出笔记摘要（给分类器补全指代上下文）。

        分享文本在日记里常被截断（"其中之一是《作为意…"），对象全名
        只存在于链接产出笔记的摘要里（2026-09-01 真实样本教训）。

        Args:
            body: 笔记正文。

        Returns:
            str: 各链接产出笔记的摘要两节拼接；无链接/未处理为空串。
        """
        links_state_path = self.state_path.parent / "processed_links.json"
        try:
            links_state = json.loads(links_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        parts: List[str] = []
        for match in URL_RE.finditer(body):
            url = match.group(0).strip(URL_TRAILING)
            if detect_platform(url) != "douyin":
                continue
            link_entry = links_state.get(url)
            if not link_entry or link_entry.get("status") != "done":
                continue
            note = Path(self.tree.notes_dir) / str(link_entry.get("note") or "")
            if not note.is_file():
                continue
            try:
                post = frontmatter.loads(note.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            summary = _summary_sections(post.content)
            if summary:
                parts.append(summary)
        return "\n\n".join(parts)

    def _chat_todos(self, text: str, api_key: str) -> List[Dict[str, Any]]:
        """LLM 判定并抽取行动项；失败抛异常（由调用方降级计数）。

        Args:
            text: 待判定文本（链接笔记已裁剪为摘要两节）。
            api_key: API key。

        Returns:
            List[Dict[str, Any]]: [{"text", "due"}]，最多 5 条；
            无行动项为空表。
        """
        prompt = (
            "判断以下笔记是否含有作者想执行的行动项，只输出 JSON："
            '{"todos": [{"text": "...", "due": "YYYY-MM-DD 或 null"}]}。'
            "规则：含行动意图即抽取——时间词（明天/周五前/下周）、义务动词"
            "（记得/要去/需要/得）、意愿词（想看/想买/想学/打算/准备）、"
            "祈使句都算；纯观点、摘抄、感慨、已完成事项的流水记录不算；"
            "没有行动项输出空表；最多 5 条；text 不超过 40 字。"
            "text 必须脱离原文也能看懂：把'里面的书/那个/这篇'等指代替换为"
            "笔记中提到的具体对象（如《作为意志和表象的世界》），"
            "说清对象的主体归属（谁的什么作品），并列对象要列全"
            "（提到两本就写两本）；若正文附有'链接内容摘要'，用它补全"
            "被截断的分享文本。去掉'我想/我要'等主语前缀，直接写动作"
            "（如：读叔本华《作为意志和表象的世界》）。"
            "不要输出 JSON 以外的任何内容。\n\n笔记内容：\n"
            + text
        )
        response = httpx.post(
            f"{self.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "max_tokens": self.llm_max_tokens,
                "temperature": 0.1,
            },
            timeout=self.llm_timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # 容错：模型偶发用 ```json 围栏包裹（2026-09-01 实测遇到）
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        data = json.loads(content)
        todos = data.get("todos") or []
        items: List[Dict[str, Any]] = []
        for todo in todos[:5]:
            if not isinstance(todo, dict):
                continue
            item_text = str(todo.get("text") or "").strip()
            if item_text:
                items.append({"text": item_text, "due": todo.get("due")})
        return items

    def _load_state(self) -> Dict[str, Any]:
        """加载处理状态；文件缺失/损坏返回空表（不抛异常）。"""
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（临时文件 + rename）。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
