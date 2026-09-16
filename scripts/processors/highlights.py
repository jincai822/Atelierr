"""划重点清单处理器（书籍/长文 PDF → 导读 + 可勾选筛查清单）。

思想来源 Cognitive OS 准入协议（US-001 §7.9）：书首先是 Source——
原件入库、查重（书名+作者+版次）、分级建议待人工确认；代读产物是
"导读 + 筛查清单"，清单每条四件事（内容是什么 / 对着什么 / 性质
预判 / 推荐动作），**机器只标建议、不代勾**；人工勾选后勾中条目
才升级（本系统轻路径：转 wiki 摘录卡，见 dispatch/highlights.py）。

本处理器负责"机器代读"这一半：PDF 逐页提取 → 按页分块 → LLM 每块挑
承重候选 → 合并去重排序（推荐优先、页码升序）→ 输出勾选清单
Markdown（``- [ ]`` 复选框，Obsidian 里直接可勾）。**书籍模式**
（页数 ≥ ``book_min_pages``，默认 60）额外产出：档案元数据
（书名/作者/版次/ISBN/中图法/级别建议，进 ``metadata["book"]``，
档案卡由 dispatch/media.py 创建）与导读节（主线/章节地图/值得细读）。

「对着什么」落地（2026-09-14 用户裁决）：构造时注入
``context_provider``（返回读者真实目标/待办标题列表），候选的
target 优先对着这些真实条目；未注入时退回 LLM 泛判「待读者判断」。

纪律（与 links 处理器一致）：
- 无 LLM key 返回失败——本处理器的产品就是候选清单，降级无意义；
- 单块 LLM 失败只记 warning 继续下一块（部分结果可用，不阻塞整本书）；
- 成本护栏：``max_chunks`` 限制片段数（默认 80 ≈ 48 万字），超出截断
  并记 warning；候选总数上限 ``max_candidates``（默认 20，防确认疲劳）；
- 导读/档案是书籍模式的附加一次调用，失败只记 warning，不阻塞清单；
- 扫描件兜底（2026-09-16 裁决 C）：无文字层/文字过少时逐页渲染成图
  走图片 OCR 重建正文（``ocr_fallback`` 默认开，页数上限
  ``ocr_max_pages`` 防整本巨著堵死分发循环），引擎复用
  ``processors.image`` 配置（use_gpu 一把开关）；
- 结构化重建（同日裁决）：``ocr_structured`` 默认开——有 PP-StructureV3
  可用时按版面分析重建**书版式**全文（标题层级、段落、插图裁切落
  assets 目录、页锚 ``<!-- pN -->``），供 media 管线落盘为
  "像一本书"的 全文.md；整篇拼装后统一过
  ``_polish_structured_markdown``（代码段围栏、In/Out 提示符清除、
  伪表格去竖线、空行压缩、被拆块的章节名合并）；引擎缺失/初始化
  失败自动退回逐页纯文本 OCR（polish 同样适用）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from scripts.processors.base import (
    BaseProcessor,
    ProcessResult,
    load_processor_config,
)

#: 单块正文过少（疑似空白页/图片页）时跳过 LLM 的阈值
MIN_CHUNK_CHARS = 100

#: 提取总字数低于该值视为"文字过少"（纯扫描件需先 OCR）
MIN_TOTAL_CHARS = 500

_NATURES = ("支持", "挑战", "待验")

#: 准入分级建议的合法取值（Cognitive OS US-001：书一般落 L1/L2；
#: L3 定级必须人工确认，机器永不建议 L3；L0 由人丢弃，机器不碰）
_LEVELS = ("L1", "L2")

#: 中图法分类标签形状（与 dispatch/archive.py CCLASS_RE 同源：
#: B84-心理学 / B-哲学；不符则丢弃，不参与归档推导）
_CLC_RE = re.compile(r"^[A-Z]{1,3}\d*-.{1,10}$")

#: PP-Structure 输出的居中 div 包裹图片（src 已改写成 图片/ 前缀后匹配）
_STRUCT_IMG_DIV_RE = re.compile(
    r'<div[^>]*>\s*<img\s+src="图片/([^"]+)"[^>]*/>\s*</div>', re.S
)
#: 残留的裸 img 标签（同上，src 已改写后匹配）
_STRUCT_IMG_RE = re.compile(r'<img\s+src="图片/([^"]+)"[^>]*/?>')
#: PP-Structure 输出的居中图注 div → 斜体行
_STRUCT_CAPTION_RE = re.compile(r'<div\s+style="text-align:\s*center;?"[^>]*>([^<]+)</div>')

# --- 结构化全文 polish（2026-09-16 排版修复）---
# PP-StructureV3 的通用版面模型没有 code 标签：书里所有代码被当正文
# 段落吐出（缩进丢失、一句一段、全角符号混入），Jupyter 提示符被误判
# 成标题（## In / ## Out），表格标题退化成 |作者简介| 伪表格，段落间
# 空行成对出现。以下规则在整篇拼装后统一 polish，重建成可读版式。

#: Jupyter 输入/输出提示符被误判的标题（## In / ## Out [3]: 等变体）
_POLISH_INOUT_RE = re.compile(r"^##\s+(?:In|Out)(?:\s*\[\s*\d*\s*\])?\s*:?\s*$")

#: 伪表格标记：整行仅 |文字|（真实表格行内至少再含一个 | ）
_POLISH_PSEUDO_TABLE_RE = re.compile(r"^\|([^|\n]+)\|\s*$")

#: 短标题 + 紧随的一级标题 = 被拆成两块的章节名（## 第4课 ⏎ # 柳暗花明…）
_POLISH_SHORT_HEAD_RE = re.compile(r"^(#{2,6})\s+(.{1,15}?)\s*$")

#: 代码行强信号（OCR 粘连容忍：for/while 等不要求词边界，中文书正文
#: 不会以这些英文关键字开头；`#注释` 单井号无空格是代码注释，
#: `## 标题`、`# 标题` 是 markdown 标题，靠「# 后不能再是 # 或空格」
#: 区分）
_POLISH_CODE_STRONG_RE = re.compile(
    r"^(?:import|from|def|class|print\s*\(|return|yield|raise|"
    r"assert\s|global\s|for|while|if|elif|else|try|except|finally|with|"
    r"break|continue|pass|@[a-zA-Z_]|#(?![#\s]))"
)

#: 代码延续弱信号：标识符开头的赋值/调用/下标（OCR 全角括号也认）
_POLISH_CODE_CONT_RE = re.compile(r"^[a-zA-Z_][\w.\[\]'\"]*\s*[=:(\[]")

#: 代码围栏内的全角符号修复（注释里的中文逗号/句号不动）
_POLISH_FULLWIDTH = str.maketrans(
    {"（": "(", "）": ")", "【": "[", "】": "]", "：": ":", "；": ";",
     "＝": "=", "，": ",", "‘": "'", "’": "'", "“": '"', "”": '"'}
)

_CJK_RE = re.compile(r"^[一-鿿]")


def _looks_like_code(line: str) -> bool:
    """行级代码判定：强信号直接命中；否则要求近纯 ASCII 且含代码标点。"""
    if _POLISH_CODE_STRONG_RE.match(line):
        return True
    if _POLISH_CODE_CONT_RE.match(line):
        return True
    if line.startswith(("!", "<", ">", "-", "*", "|")):
        return False
    if _CJK_RE.match(line):
        return False
    asciiish = sum(ch.isascii() for ch in line)
    return (
        bool(line)
        and asciiish >= len(line) * 0.8
        # 只认代码特征标点（目录页行「1.1N-Gram模型026」只有 . 结尾数字，
        # 不能误判成代码）
        and re.search(r"[=()\[\]{}]|:$", line) is not None
    )


def _polish_structured_markdown(text: str) -> str:
    """结构化 OCR 全文的版式后处理（幂等）。

    规则：已有 ``` 围栏内容原样保留（python 围栏内仅修全角符号）；
    代码行段包 ```python 围栏并修全角符号；删除 ## In/## Out 提示符
    标题；|文字| 伪表格去竖线；被拆成「短标题 + 一级标题」两块的
    章节名合并；围栏外连续空行压成一个；仅隔空行的相邻 python 围栏
    合并。页锚、图片内嵌、真实表格、frontmatter 均不受影响。
    """
    prefix = ""
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            close = text.find("\n", end + 1)
            if close != -1:
                prefix, body = text[: close + 1], text[close + 1 :]

    lines = body.split("\n")
    out: List[str] = []
    i = 0
    in_fence = False
    fence_python = False
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                in_fence = False
                fence_python = False
            else:
                in_fence = True
                fence_python = stripped[3:].strip() == "python"
            out.append(line)
            i += 1
            continue
        if in_fence:
            # 已有 python 围栏内同样修全角符号（幂等：半角行不受影响），
            # 其余规则（In/Out、空行压缩等）不进围栏
            if fence_python:
                line = line.translate(_POLISH_FULLWIDTH)
            out.append(line)
            i += 1
            continue
        if _POLISH_INOUT_RE.match(stripped):
            i += 1
            continue
        m = _POLISH_PSEUDO_TABLE_RE.match(stripped)
        if m:
            out.append(m.group(1).strip())
            i += 1
            continue
        m = _POLISH_SHORT_HEAD_RE.match(stripped)
        if m:
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].strip().startswith("# "):
                out.append(f"{m.group(1)} {m.group(2)} {lines[j].strip()[2:].strip()}")
                i = j + 1
                continue
        if _looks_like_code(stripped):
            block: List[str] = []
            while i < n:
                cur = lines[i].strip()
                if cur:
                    if _looks_like_code(cur) and not cur.startswith("# "):
                        block.append(cur.translate(_POLISH_FULLWIDTH))
                        i += 1
                        continue
                    break
                # 空行：向后看，下一个非空行仍是代码则段继续（丢空行）
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _looks_like_code(lines[j].strip()) and block:
                    i = j
                    continue
                break
            if block and (
                len(block) >= 2 or _POLISH_CODE_STRONG_RE.match(block[0])
            ):
                # 单行弱信号不围栏（防正文里「术语: 解释」式行被误伤）；
                # 强信号单行（如 OCR 粘连的整行注释+代码）照常围栏
                out.append("```python")
                out.extend(block)
                out.append("```")
            else:
                out.extend(block)
            continue
        out.append(line)
        i += 1

    collapsed = "\n".join(out)
    # 相邻 python 围栏（之间只有空行）合并成一个：分段识别/分批
    # polish 可能把同一段代码切成几个小围栏，合并后渲染更连贯
    collapsed = re.sub(r"```\n\n+```python\n", "", collapsed)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return prefix + collapsed.strip("\n") + "\n" if prefix else collapsed.strip("\n") + "\n"


class HighlightsProcessor(BaseProcessor):
    """书籍/长文 PDF → 划重点候选清单。

    Examples:
        >>> result = HighlightsProcessor().process("book.pdf")
        >>> result.markdown.startswith("# 划重点清单")
        True
    """

    name = "highlights"
    supported_extensions: Tuple[str, ...] = (".pdf",)

    def __init__(
        self,
        config: Optional[dict] = None,
        context_provider: Optional[Any] = None,
        ocr_factory: Optional[Any] = None,
        structure_factory: Optional[Any] = None,
    ) -> None:
        """初始化。

        Args:
            config: processors.highlights 配置节；缺省按配置文件加载。
            context_provider: 「对着什么」素材提供者（可调用，返回读者
                真实目标/待办标题列表；2026-09-14 裁决：书籍筛查对照
                读者真实目标与待办）。None 时 target 退回 LLM 泛判
                （「待读者判断」）。
            ocr_factory: 扫描件兜底的 OCR 处理器工厂（可调用，返回带
                ``process(path)`` 的处理器）；None 时懒加载图片处理器
                （复用 processors.image 配置）。测试注入假实现。
            structure_factory: PP-StructureV3 版面分析工厂（结构化重建
                用）；None 时懒加载真实引擎，不可用自动退回纯文本 OCR。
                测试注入假实现。
        """
        super().__init__(config)
        self.chunk_chars = int(self.config.get("chunk_chars", 6000))
        self.max_chunks = int(self.config.get("max_chunks", 80))
        self.max_candidates = int(self.config.get("max_candidates", 20))
        self.book_min_pages = int(self.config.get("book_min_pages", 60))
        self.context_provider = context_provider
        self.ocr_fallback = bool(self.config.get("ocr_fallback", True))
        self.ocr_max_pages = int(self.config.get("ocr_max_pages", 200))
        self.ocr_dpi = int(self.config.get("ocr_dpi", 150))
        self.ocr_structured = bool(self.config.get("ocr_structured", True))
        self.ocr_factory = ocr_factory
        self.structure_factory = structure_factory
        self._ocr: Optional[Any] = None
        self._structure: Optional[Any] = None
        self._structure_tried = False
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
        warnings: List[str] = []
        pages, toc, error = self._extract_pages(path)
        ocr_used = False
        ocr_assets: Optional[str] = None
        if error and "无可提取文字" not in error:
            return self._fail(error)
        total_chars = sum(len(text) for _, text in pages)
        if error or total_chars < MIN_TOTAL_CHARS:
            # 扫描件信号（无文字层或文字过少）：OCR 兜底重建正文（裁决 C）
            if not self.ocr_fallback:
                return self._fail(
                    error
                    or f"提取文字过少（{total_chars} 字）：疑似纯扫描件，请先 OCR 再投喂"
                )
            pages, toc, ocr_warnings, ocr_error, ocr_assets = self._ocr_pages(path)
            warnings.extend(ocr_warnings)
            if ocr_error:
                return self._fail(ocr_error)
            ocr_used = True
            total_chars = sum(len(text) for _, text in pages)
            if total_chars < MIN_TOTAL_CHARS:
                return self._fail(
                    f"扫描件 OCR 后文字仍过少（{total_chars} 字）：无法代读"
                )

        chunks = self._chunk_pages(pages)
        if len(chunks) > self.max_chunks:
            warnings.append(
                f"片段数 {len(chunks)} 超过护栏 {self.max_chunks}，已截断（成本保护）"
            )
            chunks = chunks[: self.max_chunks]

        # 书籍模式（2026-09-14 裁决，对齐 Cognitive OS 准入协议）：
        # 页数达标的书籍额外产出档案元数据 + 导读节；失败只记 warning
        profile: Optional[Dict[str, Any]] = None
        if len(pages) >= self.book_min_pages:
            try:
                profile = self._book_profile(path, pages, toc)
            except Exception as exc:  # noqa: BLE001 - 导读失败不阻塞清单
                warnings.append(f"导读/档案生成失败: {type(exc).__name__}")

        context_lines = self._reader_context_lines()
        candidates: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks, 1):
            try:
                candidates.extend(self._extract_candidates(chunk, context_lines))
            except Exception as exc:  # noqa: BLE001 - 单块失败不阻塞整本书
                warnings.append(f"片段 {index} 失败: {type(exc).__name__}")
        merged = self._merge_candidates(candidates)

        markdown = self._build_markdown(path, pages, merged, warnings, profile, toc)
        full_text = "\n\n".join(text for _, text in pages)
        if ocr_used:
            # OCR 全文统一过版式 polish（代码围栏/In-Out 标记/伪表格/
            # 空行压缩/章节名合并），LLM 分块仍用原始页文本
            full_text = _polish_structured_markdown(full_text)
        return ProcessResult(
            success=True,
            text=full_text,
            markdown=markdown,
            metadata={
                "engine": self.llm_model,
                "pages": len(pages),
                "chunks": len(chunks),
                "candidates": len(merged),
                "book": profile,
                "ocr": ocr_used,
                "ocr_assets": ocr_assets,
                "warnings": warnings,
                "elapsed": round(time.time() - started, 2),
            },
        )

    def _get_ocr(self) -> Any:
        """取 OCR 处理器（懒加载，引擎构造昂贵；默认复用 processors.image 配置）。"""
        if self._ocr is None:
            if self.ocr_factory is not None:
                self._ocr = self.ocr_factory()
            else:
                from scripts.processors.image import ImageProcessor

                self._ocr = ImageProcessor(load_processor_config("image"))
        return self._ocr

    def _get_structure(self) -> Optional[Any]:
        """取 PP-StructureV3 版面分析引擎（懒加载；不可用/初始化失败返回
        None，调用方退回逐页纯文本 OCR）。"""
        if not self.ocr_structured:
            return None
        if self._structure_tried:
            return self._structure
        self._structure_tried = True
        try:
            if self.structure_factory is not None:
                self._structure = self.structure_factory()
            else:
                from paddleocr import PPStructureV3

                use_gpu = bool(load_processor_config("image").get("use_gpu"))
                # 只留 版面检测+OCR+阅读顺序；表格/公式/印章等子模型全关
                #（书稿场景用不上，省下加载时间与显存）
                self._structure = PPStructureV3(
                    device="gpu:0" if use_gpu else "cpu",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    use_table_recognition=False,
                    use_formula_recognition=False,
                    use_chart_recognition=False,
                    use_seal_recognition=False,
                )
        except Exception:  # noqa: BLE001 - 引擎不可用退回纯文本路径
            self._structure = None
        return self._structure

    @staticmethod
    def _ocr_page_structured(
        pipe: Any,
        image_path: Path,
        page_no: int,
        tmp: Path,
        assets_dir: Path,
        warnings: List[str],
    ) -> Optional[str]:
        """单页结构化重建：版面分析 → 书版式 markdown（标题/段落/插图）。

        插图裁切从 PP-Structure 输出目录搬入 assets_dir（页码前缀命名），
        引用改写为 Obsidian 内嵌 ``![[图片/pNNNN-xxx.jpg]]``（落夹后由
        media 管线替换为库内全路径）；居中图注降级为斜体行；页首插
        ``<!-- pN -->`` 锚点（阅读视图不可见，供 agent 按页定位）。
        失败记 warning 返回 None（该页缺失，不阻塞整本）。
        """
        try:
            results = pipe.predict(input=str(image_path))
            out_dir = tmp / f"out-{page_no}"
            for res in results:
                res.save_to_markdown(str(out_dir))
            mds = sorted(out_dir.glob("*.md"))
            if not mds:
                warnings.append(f"第 {page_no} 页结构化失败，已跳过")
                return None
            text = mds[0].read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - 单页失败不阻塞整本
            warnings.append(f"第 {page_no} 页结构化失败: {type(exc).__name__}")
            return None
        imgs_dir = out_dir / "imgs"
        if imgs_dir.is_dir():
            for img in sorted(imgs_dir.iterdir()):
                named = f"p{page_no:04d}-{img.name}"
                shutil.move(str(img), str(assets_dir / named))
                text = text.replace(f"imgs/{img.name}", f"图片/{named}")
        text = _STRUCT_IMG_DIV_RE.sub(r"![[图片/\1]]", text)
        text = _STRUCT_IMG_RE.sub(r"![[图片/\1]]", text)
        text = _STRUCT_CAPTION_RE.sub(r"*\1*", text)
        return f"<!-- p{page_no} -->\n\n" + text.strip()

    def _ocr_pages(
        self, path: Path
    ) -> Tuple[
        List[Tuple[int, str]],
        List[Tuple[int, str, int]],
        List[str],
        Optional[str],
        Optional[str],
    ]:
        """扫描件 OCR 兜底：逐页渲染成图 → 识别 → 重建页文本。

        结构化模式（``ocr_structured`` 开且引擎可用）：PP-StructureV3
        版面分析直接产出书版式 markdown（标题层级/段落/插图裁切），插图
        落 ``metadata`` 带回的 assets 目录（调用方负责收编落夹）；
        否则退回逐页纯文本 OCR。页数超过 ``ocr_max_pages`` 时只处理前
        N 页并记 warning（成本护栏，防整本巨著堵死 15 分钟一轮的分发
        循环）；单页失败跳过记 warning，全部失败才返回错误。书签目录
        照常提取（扫描件也常带）。

        Returns:
            Tuple: (pages, toc, warnings, error, assets_dir)；
            error 非 None 即失败；assets_dir 为插图裁切临时目录
            （仅结构化模式有值，调用方负责搬走或清理）。
        """
        warnings: List[str] = []
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return [], [], warnings, "未安装 PyMuPDF（pip install pymupdf）", None
        pages: List[Tuple[int, str]] = []
        toc: List[Tuple[int, str, int]] = []
        assets_dir: Optional[Path] = None
        try:
            with fitz.open(str(path)) as document:
                get_toc = getattr(document, "get_toc", None)
                if callable(get_toc):
                    # 扫描件也可能带书签目录（实测 268 页书 112 条），照常利用
                    toc = [
                        (int(level), str(title).strip(), int(page))
                        for level, title, page in (get_toc() or [])[:120]
                    ]
                total = len(document)
                limit = min(total, self.ocr_max_pages)
                if total > self.ocr_max_pages:
                    warnings.append(
                        f"扫描件共 {total} 页，超过 OCR 上限 "
                        f"{self.ocr_max_pages}，仅处理前 {limit} 页"
                    )
                zoom = self.ocr_dpi / 72.0
                matrix = fitz.Matrix(zoom, zoom)
                structure = self._get_structure()
                if self.ocr_structured and structure is None:
                    warnings.append("结构化引擎不可用，退回纯文本 OCR")
                if structure is not None:
                    assets_dir = Path(
                        tempfile.mkdtemp(prefix="atelierr-bookimgs-")
                    )
                with tempfile.TemporaryDirectory(prefix="atelierr-ocr-") as tmp:
                    if structure is not None:
                        for index in range(limit):
                            image_path = Path(tmp) / f"page-{index + 1}.png"
                            document[index].get_pixmap(matrix=matrix).save(
                                str(image_path)
                            )
                            md = self._ocr_page_structured(
                                structure, image_path, index + 1,
                                Path(tmp), assets_dir, warnings,
                            )
                            if md:
                                pages.append((index + 1, md))
                    else:
                        ocr = self._get_ocr()
                        for index in range(limit):
                            image_path = Path(tmp) / f"page-{index + 1}.png"
                            document[index].get_pixmap(matrix=matrix).save(
                                str(image_path)
                            )
                            result = ocr.process(image_path)
                            if result.success and (result.text or "").strip():
                                pages.append((index + 1, result.text.strip()))
                            else:
                                warnings.append(f"第 {index + 1} 页 OCR 失败，已跳过")
        except Exception as exc:  # noqa: BLE001 - 损坏 PDF 按失败处理
            if assets_dir is not None:
                shutil.rmtree(assets_dir, ignore_errors=True)
            return [], [], warnings, f"扫描件 OCR 失败: {type(exc).__name__}: {exc}", None
        if not pages:
            if assets_dir is not None:
                shutil.rmtree(assets_dir, ignore_errors=True)
            return [], [], warnings, "扫描件 OCR 全部失败：无法代读", None
        return pages, toc, warnings, None, (
            str(assets_dir) if assets_dir is not None else None
        )

    @staticmethod
    def _extract_pages(
        path: Path,
    ) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str, int]], Optional[str]]:
        """逐页提取文字 + 目录（流式，不整文件读入内存）。

        目录（fitz get_toc）供书籍模式的导读节使用；无目录/读取失败
        返回空表，不阻塞正文提取。
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return [], [], "未安装 PyMuPDF（pip install pymupdf）"
        pages: List[Tuple[int, str]] = []
        toc: List[Tuple[int, str, int]] = []
        try:
            with fitz.open(str(path)) as document:
                get_toc = getattr(document, "get_toc", None)
                if callable(get_toc):
                    toc = [
                        (int(level), str(title).strip(), int(page))
                        for level, title, page in (get_toc() or [])[:120]
                    ]
                for index in range(len(document)):
                    text = document[index].get_text("text").strip()
                    if text:
                        pages.append((index + 1, text))
        except Exception as exc:  # noqa: BLE001 - 损坏 PDF 按失败处理
            return [], [], f"PDF 读取失败: {type(exc).__name__}: {exc}"
        if not pages:
            return [], [], "PDF 无可提取文字（疑似纯扫描件，请先 OCR 再投喂）"
        return pages, toc, None

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

    def _extract_candidates(
        self, chunk: List[Tuple[int, str]], context_lines: List[str]
    ) -> List[Dict[str, Any]]:
        """对单个片段调 LLM 挑候选，返回规范化的候选列表。"""
        body = "\n\n".join(f"【第 {page_no} 页】\n{text}" for page_no, text in chunk)
        if len(body) < MIN_CHUNK_CHARS:
            return []
        context_block = ""
        if context_lines:
            context_block = (
                "读者的真实目标与待办（target 优先对着这些真实条目写；"
                "确实对不上才写「待读者判断」）：\n"
                + "\n".join(context_lines)
                + "\n\n"
            )
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
            "不要输出 JSON 以外的任何内容。\n\n" + context_block + "书稿片段：\n" + body
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

    def _reader_context_lines(self) -> List[str]:
        """「对着什么」素材行（目标/待办标题）；提供者缺失或失败返回空表。"""
        if self.context_provider is None:
            return []
        try:
            lines = self.context_provider()
        except Exception:  # noqa: BLE001 - 素材拿不到不阻塞代读
            return []
        return [str(line) for line in (lines or []) if str(line).strip()][:20]

    def _book_profile(
        self,
        path: Path,
        pages: List[Tuple[int, str]],
        toc: List[Tuple[int, str, int]],
    ) -> Dict[str, Any]:
        """书籍模式：目录 + 开头片段 → 档案元数据与导读（一次 LLM 调用）。

        只输出 JSON 档案；字段缺失时规范化兜底（书名回退文件名、
        级别回退 L1、中图法不合形状即丢弃）。导读书节由
        ``_build_markdown`` 依此档案与目录组装。
        """
        opening = "\n\n".join(text for _, text in pages[:2])[:4000]
        toc_text = "\n".join(
            f"{'  ' * (level - 1)}{title}（第 {page} 页）"
            for level, title, page in toc[:80]
        ) or "（无目录）"
        context_lines = self._reader_context_lines()
        context_block = ""
        if context_lines:
            context_block = (
                "读者的真实目标与待办（推荐细读章节优先对着这些）：\n"
                + "\n".join(context_lines)
                + "\n\n"
            )
        prompt = (
            "你是「书籍建档与导读」助手。根据书籍的目录与开头片段，"
            "只输出 JSON：{\"book\": {\"title\": \"...\", \"author\": \"...\", "
            "\"edition\": \"...\", \"isbn\": \"...\", \"clc\": \"...\", "
            "\"level\": \"L1|L2\", \"level_reason\": \"...\", "
            "\"mainline\": \"...\", "
            "\"chapter_advice\": [{\"chapter\": \"...\", \"why\": \"...\"}]}}。"
            "字段要求：title 书名（据版权页/封面页，不带书名号）；author 作者；"
            "edition 版次（如 第2版；看不到就留空）；isbn（看不到留空）；"
            "clc 中图法分类标签（形如 B84-心理学 / TP311.5-软件测试，"
            "字母大类+可选数字+短横+≤10字类名；拿不准留空）；"
            "level 准入分级建议：L1=只存原件未来参考 / L2=有长期知识价值值得"
            "提取（只许二选一，机器永不建议 L3——L3 定级是人工权力）；"
            "level_reason 一句分级理由（≤30 字）；"
            "mainline 全书主线一句话（≤40 字）；"
            "chapter_advice 挑 1-3 个最值得读者细读的章节（chapter 照抄目录"
            "章节名，why 一句理由 ≤30 字）。"
            "不要输出 JSON 以外的任何内容。\n\n"
            + context_block
            + f"文件名：{path.name}\n\n目录：\n{toc_text}\n\n开头片段：\n{opening}"
        )
        data = json.loads(self._llm_chat(prompt))
        book = data.get("book")
        return self._normalize_profile(book if isinstance(book, dict) else {}, path)

    @staticmethod
    def _normalize_profile(book: Dict[str, Any], path: Path) -> Dict[str, Any]:
        """规范化书籍档案字段（长度截断、级别/中图法兜底）。"""
        clc = str(book.get("clc") or "").strip()
        if not _CLC_RE.match(clc):
            clc = ""
        level = str(book.get("level") or "").strip()
        if level not in _LEVELS:
            level = "L1"
        advice: List[Dict[str, str]] = []
        for item in (book.get("chapter_advice") or [])[:3]:
            if not isinstance(item, dict):
                continue
            chapter = str(item.get("chapter") or "").strip()[:40]
            if chapter:
                advice.append({"chapter": chapter, "why": str(item.get("why") or "").strip()[:40]})
        return {
            "title": str(book.get("title") or "").strip()[:40] or path.stem[:40],
            "author": str(book.get("author") or "").strip()[:30],
            "edition": str(book.get("edition") or "").strip()[:20],
            "isbn": str(book.get("isbn") or "").strip()[:20],
            "clc": clc,
            "level": level,
            "level_reason": str(book.get("level_reason") or "").strip()[:40],
            "mainline": str(book.get("mainline") or "").strip()[:60],
            "chapter_advice": advice,
        }

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
            # 推荐优先；推荐项里「挑战」排最前（US-001 §7.9：对着待决策
            # 事项、挑战已有认知的排最前）；同档内页码升序
            key=lambda c: (not c["recommend"], c["nature"] != "挑战", c["anchor"] or 10**9),
        )
        return ordered[: self.max_candidates]

    def _build_markdown(
        self,
        path: Path,
        pages: List[Tuple[int, str]],
        candidates: List[Dict[str, Any]],
        warnings: List[str],
        profile: Optional[Dict[str, Any]] = None,
        toc: Optional[List[Tuple[int, str, int]]] = None,
    ) -> str:
        """组装 Markdown（复选框行是勾中转笔记的稳定锚）。

        书籍模式（profile 非空）：标题升级为「导读与筛查清单」，正文
        在候选清单前加导读节（主线/档案行/章节地图/值得细读）——
        导读是地图不是摘要，筛查清单才是勾选对象（Cognitive OS
        US-001 §7.9：清单只是候选，不产生任何认知条目）。
        """
        title = path.stem
        if profile:
            heading = f"# 《{profile['title']}》导读与筛查清单"
        else:
            heading = f"# 划重点清单：{title}"
        lines = [
            heading,
            "",
            f"> 来源：[[{path.name}]]（{len(pages)} 页有文字，LLM 代读生成）",
            "> 机器只标建议、不代勾：勾中的条目会在下一轮同步自动转为正式笔记"
            "（带「待确认」）；未勾条目留在清单里，零成本，随时可回勾。",
            "",
        ]
        if profile:
            lines += self._guide_lines(profile, toc or [])
        lines += [
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

    @staticmethod
    def _guide_lines(
        profile: Dict[str, Any], toc: List[Tuple[int, str, int]]
    ) -> List[str]:
        """书籍模式导读节：主线 / 档案行 / 章节地图（目录）/ 值得细读。"""
        lines = ["## 导读（机器代读）", ""]
        if profile["mainline"]:
            lines.append(f"- 主线：{profile['mainline']}")
        archive_bits = [bit for bit in (profile["author"], profile["edition"]) if bit]
        archive = " / ".join(archive_bits) or "（作者/版次未识别）"
        if profile["isbn"]:
            archive += f" / ISBN {profile['isbn']}"
        lines.append(
            f"- 档案：{archive}；级别建议 {profile['level']}"
            f"（{profile['level_reason'] or '机器建议'}，待人工确认）"
        )
        if toc:
            lines += ["", "### 章节地图", ""]
            lines += [
                f"{'  ' * (level - 1)}- {title}（第 {page} 页）"
                for level, title, page in toc[:40]
            ]
        if profile["chapter_advice"]:
            lines += ["", "### 值得细读", ""]
            lines += [
                f"- {item['chapter']}——{item['why']}"
                for item in profile["chapter_advice"]
            ]
        lines.append("")
        return lines
