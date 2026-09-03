"""划重点清单处理器（书籍/长文 PDF → 可勾选候选清单）。

思想来源 Cognitive OS 准入协议「划重点人工勾选」：机器先代读并交出
候选清单（每条：内容是什么 / 对着什么认知 / 性质预判 / 是否推荐勾），
**机器只标建议、不代勾**；人工在 Obsidian 里逐条勾选，勾中的才值得
深加工。

本处理器负责"机器代读"这一半：PDF 逐页提取 → 按页分块 → LLM 每块挑
承重候选 → 合并去重排序（推荐优先、页码升序）→ 输出勾选清单
Markdown（``- [ ]`` 复选框，Obsidian 里直接可勾）。另一半"勾中转
笔记"由 :mod:`scripts.dispatch.highlights` 完成。

纪律（与 links 处理器一致）：
- 无 LLM key 返回失败——本处理器的产品就是候选清单，降级无意义；
- 单块 LLM 失败只记 warning 继续下一块（部分结果可用，不阻塞整本书）；
- 成本护栏：``max_chunks`` 限制片段数（默认 80 ≈ 48 万字），超出截断
  并记 warning；候选总数上限 ``max_candidates``（默认 20，防确认疲劳）。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from scripts.processors.base import BaseProcessor, ProcessResult

#: 单块正文过少（疑似空白页/图片页）时跳过 LLM 的阈值
MIN_CHUNK_CHARS = 100

#: 提取总字数低于该值视为"文字过少"（纯扫描件需先 OCR）
MIN_TOTAL_CHARS = 500

_NATURES = ("支持", "挑战", "待验")


class HighlightsProcessor(BaseProcessor):
    """书籍/长文 PDF → 划重点候选清单。

    Examples:
        >>> result = HighlightsProcessor().process("book.pdf")
        >>> result.markdown.startswith("# 划重点清单")
        True
    """

    name = "highlights"
    supported_extensions: Tuple[str, ...] = (".pdf",)

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: processors.highlights 配置节；缺省按配置文件加载。
        """
        super().__init__(config)
        self.chunk_chars = int(self.config.get("chunk_chars", 6000))
        self.max_chunks = int(self.config.get("max_chunks", 80))
        self.max_candidates = int(self.config.get("max_candidates", 20))
        llm = self.config.get("llm") or {}
        self.llm_base_url = str(llm.get("base_url", "https://api.deepseek.com"))
        self.llm_model = str(llm.get("model", "deepseek-v4-flash"))
        self.llm_api_key_env = str(llm.get("api_key_env", "DEEPSEEK_API_KEY"))
        self.llm_timeout = int(llm.get("timeout", 120))
        self.llm_max_tokens = int(llm.get("max_tokens", 4000))

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """处理 PDF：逐页提取 → 分块 → LLM 挑候选 → 勾选清单 Markdown。

        Args:
            input_path: PDF 文件路径。

        Returns:
            ProcessResult: markdown 为勾选清单；metadata 含
            pages/chunks/candidates/warnings/elapsed。
        """
        started = time.time()
        bad = self._check_input(input_path)
        if bad:
            return bad
        if not os.environ.get(self.llm_api_key_env, "").strip():
            return self._fail(f"未设置 {self.llm_api_key_env}（划重点依赖 LLM 代读）")

        path = Path(input_path)
        pages, error = self._extract_pages(path)
        if error:
            return self._fail(error)
        total_chars = sum(len(text) for _, text in pages)
        if total_chars < MIN_TOTAL_CHARS:
            return self._fail(
                f"提取文字过少（{total_chars} 字）：疑似纯扫描件，请先 OCR 再投喂"
            )

        chunks = self._chunk_pages(pages)
        warnings: List[str] = []
        if len(chunks) > self.max_chunks:
            warnings.append(
                f"片段数 {len(chunks)} 超过护栏 {self.max_chunks}，已截断（成本保护）"
            )
            chunks = chunks[: self.max_chunks]

        candidates: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks, 1):
            try:
                candidates.extend(self._extract_candidates(chunk))
            except Exception as exc:  # noqa: BLE001 - 单块失败不阻塞整本书
                warnings.append(f"片段 {index} 失败: {type(exc).__name__}")
        merged = self._merge_candidates(candidates)

        markdown = self._build_markdown(path, pages, merged, warnings)
        return ProcessResult(
            success=True,
            text="\n\n".join(text for _, text in pages),
            markdown=markdown,
            metadata={
                "engine": self.llm_model,
                "pages": len(pages),
                "chunks": len(chunks),
                "candidates": len(merged),
                "warnings": warnings,
                "elapsed": round(time.time() - started, 2),
            },
        )

    @staticmethod
    def _extract_pages(path: Path) -> Tuple[List[Tuple[int, str]], Optional[str]]:
        """逐页提取文字（流式，不整文件读入内存）。"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return [], "未安装 PyMuPDF（pip install pymupdf）"
        pages: List[Tuple[int, str]] = []
        try:
            with fitz.open(str(path)) as document:
                for index in range(len(document)):
                    text = document[index].get_text("text").strip()
                    if text:
                        pages.append((index + 1, text))
        except Exception as exc:  # noqa: BLE001 - 损坏 PDF 按失败处理
            return [], f"PDF 读取失败: {type(exc).__name__}: {exc}"
        if not pages:
            return [], "PDF 无可提取文字（疑似纯扫描件，请先 OCR 再投喂）"
        return pages, None

    def _chunk_pages(self, pages: List[Tuple[int, str]]) -> List[List[Tuple[int, str]]]:
        """按页聚合成不超过 chunk_chars 的片段（不切断单页）。"""
        chunks: List[List[Tuple[int, str]]] = []
        current: List[Tuple[int, str]] = []
        current_len = 0
        for page_no, text in pages:
            if current and current_len + len(text) > self.chunk_chars:
                chunks.append(current)
                current, current_len = [], 0
            current.append((page_no, text))
            current_len += len(text)
        if current:
            chunks.append(current)
        return chunks

    def _extract_candidates(self, chunk: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
        """对单个片段调 LLM 挑候选，返回规范化的候选列表。"""
        body = "\n\n".join(f"【第 {page_no} 页】\n{text}" for page_no, text in chunk)
        if len(body) < MIN_CHUNK_CHARS:
            return []
        prompt = (
            "你是「划重点」助手，读者是一位用个人知识系统管理认知的人。"
            "阅读以下书稿片段，挑出 3-8 条值得深加工的候选，只输出 JSON："
            '{"candidates": [{"title": "...", "what": "...", "target": "...", '
            '"nature": "支持|挑战|待验", "recommend": true, "reason": "...", '
            '"anchor": 页码数字}]}。'
            "字段要求：title 候选概念名（≤15 字）；what 内容是什么（一句 ≤40 字）；"
            "target 它对着读者的哪类活决策或既有认知（无法判断就写「待读者判断」）；"
            "nature 三选一（对该认知是支持/挑战/待验，拿不准写待验）；"
            "recommend 是否推荐勾选（只给真正承重的候选 true）；"
            "reason 一句推荐理由（≤30 字）；anchor 所在页码（按片段中的【第 N 页】）。"
            "挑选标准（概念三问）：可一两句说清是什么；有机制/原理可讲、"
            "可能被误解；别的内容靠它才讲得明白。事实罗列、例子、空话不挑。"
            "不要输出 JSON 以外的任何内容。\n\n书稿片段：\n" + body
        )
        content = self._llm_chat(prompt)
        data = json.loads(content)
        raw = data.get("candidates") or []
        return [self._normalize(item) for item in raw if isinstance(item, dict)]

    def _llm_chat(self, prompt: str) -> str:
        """调 LLM chat 接口返回 content 文本；任何失败抛异常（调用方处理）。"""
        api_key = os.environ.get(self.llm_api_key_env, "").strip()
        payload: Dict[str, Any] = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.llm_max_tokens,
            "temperature": 0.3,
            # 机械任务禁用思考链：deepseek-v4-flash 默认开推理，长输出会
            # 把 max_tokens 全耗在 reasoning 上导致 content 为空（09-02 实测）
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        response = httpx.post(
            f"{self.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=self.llm_timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
        """规范化单条候选字段（长度截断、nature 兜底、anchor 转 int）。"""
        nature = str(item.get("nature") or "").strip()
        if nature not in _NATURES:
            nature = "待验"
        try:
            anchor = int(item.get("anchor") or 0)
        except (TypeError, ValueError):
            anchor = 0
        return {
            "title": str(item.get("title") or "").strip()[:15],
            "what": str(item.get("what") or "").strip()[:60],
            "target": str(item.get("target") or "").strip()[:40] or "待读者判断",
            "nature": nature,
            "recommend": bool(item.get("recommend")),
            "reason": str(item.get("reason") or "").strip()[:40],
            "anchor": anchor,
        }

    def _merge_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并去重（按规范化标题），排序：推荐优先、页码升序；截到上限。"""
        seen: Dict[str, Dict[str, Any]] = {}
        for item in candidates:
            if not item["title"]:
                continue
            key = re.sub(r"[\s·・，。,.、/／-]", "", item["title"]).lower()
            if key not in seen:
                seen[key] = item
                continue
            old = seen[key]
            # 重复候选：推荐标记取或，锚点取较小页码（首次出现处）
            old["recommend"] = old["recommend"] or item["recommend"]
            if item["anchor"] and (not old["anchor"] or item["anchor"] < old["anchor"]):
                old["anchor"] = item["anchor"]
        ordered = sorted(
            seen.values(),
            key=lambda c: (not c["recommend"], c["anchor"] or 10**9),
        )
        return ordered[: self.max_candidates]

    def _build_markdown(
        self,
        path: Path,
        pages: List[Tuple[int, str]],
        candidates: List[Dict[str, Any]],
        warnings: List[str],
    ) -> str:
        """组装勾选清单 Markdown（复选框行是勾中转笔记的稳定锚）。"""
        title = path.stem
        lines = [
            f"# 划重点清单：{title}",
            "",
            f"> 来源：[[{path.name}]]（{len(pages)} 页有文字，LLM 代读生成）",
            "> 机器只标建议、不代勾：勾中的条目会在下一轮同步自动转为正式笔记"
            "（带「待确认」）；未勾条目留在清单里，零成本，随时可回勾。",
            "",
            "## 候选清单",
            "",
        ]
        if not candidates:
            lines.append("（LLM 未挑出承重候选：内容过薄或各片段调用均失败）")
        for item in candidates:
            anchor = f"（第 {item['anchor']} 页）" if item["anchor"] else ""
            advice = "推荐勾" if item["recommend"] else "可不勾"
            lines.append(f"- [ ] **{item['title']}**{anchor}")
            lines.append(f"  - 内容：{item['what']}")
            lines.append(f"  - 对着：{item['target']}")
            lines.append(f"  - 性质：{item['nature']}")
            lines.append(f"  - 建议：{advice}——{item['reason']}")
        if warnings:
            lines += ["", "## 加工警告", ""]
            lines += [f"- {warning}" for warning in warnings]
        return "\n".join(lines) + "\n"
