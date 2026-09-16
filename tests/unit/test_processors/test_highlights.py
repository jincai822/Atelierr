"""划重点处理器单元测试（无真实网络/真实 PDF）。

LLM 调用 monkeypatch ``httpx.post``；PDF 页提取 monkeypatch 假 ``fitz``
模块。分块、合并去重、护栏截断、字段规范化均为真实代码路径。
"""

from __future__ import annotations

import json
import sys
import types

import pytest

import scripts.processors.highlights as hl_module
from scripts.processors.base import ProcessResult
from scripts.processors.highlights import HighlightsProcessor


class _FakePixmap:
    """假渲染结果：save() 写出占位 PNG（OCR 兜底路径用）。"""

    def save(self, path):
        from pathlib import Path

        Path(path).write_bytes(b"\x89PNG fake")


class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self, _mode):
        return self._text

    def get_pixmap(self, matrix=None):
        return _FakePixmap()


class _FakeDoc:
    def __init__(self, texts, toc=None):
        self._pages = [_FakePage(t) for t in texts]
        self._toc = toc or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]

    def get_toc(self):
        return self._toc


def _install_fake_fitz(monkeypatch, page_texts, toc=None):
    """注册假 fitz 模块：open() 返回固定页文本的假文档。"""
    fake = types.SimpleNamespace(
        open=lambda _path: _FakeDoc(page_texts, toc),
        Matrix=lambda *a, **kw: None,
    )
    monkeypatch.setitem(sys.modules, "fitz", fake)


class _FakeOcrProcessor:
    """假 OCR 引擎：逐页返回固定文本；fail 置位时全部失败。"""

    calls = []
    fail = False
    text = "扫描页正文。"

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail:
            return ProcessResult(success=False, error="引擎崩溃")
        return ProcessResult(
            success=True, text=type(self).text, markdown="", confidence=0.9
        )


@pytest.fixture(autouse=True)
def _reset_fake_ocr():
    """每个用例重置假 OCR/假版面分析的调用记录与失败开关。"""
    _FakeOcrProcessor.calls = []
    _FakeOcrProcessor.fail = False
    _FakeOcrProcessor.text = "扫描页正文。"
    _FakeStructure.calls = []
    yield


class _FakeStructureResult:
    """假 PP-Structure 结果：save_to_markdown 写出固定 md + 一张裁切图。"""

    def save_to_markdown(self, out_dir):
        from pathlib import Path

        out = Path(out_dir)
        (out / "imgs").mkdir(parents=True, exist_ok=True)
        (out / "imgs" / "img_in_image_box_1_2_3_4.jpg").write_bytes(b"\xff\xd8fake")
        (out / "page.md").write_text(
            '<div style="text-align: center;">'
            '<img src="imgs/img_in_image_box_1_2_3_4.jpg" alt="Image" width="50%" />'
            "</div>\n\n"
            '<div style="text-align: center;">模型结构图</div>\n\n'
            "## 何为语言？\n\n正文段落" + "。" * 400,
            encoding="utf-8",
        )


class _FakeStructure:
    """假版面分析引擎：记录调用，返回固定结果。"""

    calls = []

    def predict(self, input):
        type(self).calls.append(input)
        return [_FakeStructureResult()]


class _FakeLLMResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _payload(items):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"candidates": items}, ensure_ascii=False)
                }
            }
        ]
    }


def _item(title="概念甲", anchor=3, recommend=True, nature="支持"):
    return {
        "title": title,
        "what": "一句话解释这个概念",
        "target": "既有认知 X",
        "nature": nature,
        "recommend": recommend,
        "reason": "承重概念",
        "anchor": anchor,
    }


def _make_pdf(tmp_path, page_texts, monkeypatch, name="book.pdf", toc=None):
    _install_fake_fitz(monkeypatch, page_texts, toc)
    path = tmp_path / name
    path.write_bytes(b"%PDF fake")
    return path


def test_process_success(tmp_path, monkeypatch):
    """两页一块：产出勾选清单，复选框行/详情行/metadata 齐全。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    path = _make_pdf(tmp_path, ["第一页正文。" * 60, "第二页正文。" * 60], monkeypatch)

    result = HighlightsProcessor().process(path)

    assert result.success
    assert "- [ ] **概念甲**（第 3 页）" in result.markdown
    assert "  - 内容：" in result.markdown
    assert "  - 性质：支持" in result.markdown
    assert "  - 建议：推荐勾" in result.markdown
    assert result.markdown.startswith("# 划重点清单：book")
    assert result.metadata["pages"] == 2
    assert result.metadata["chunks"] == 1
    assert result.metadata["candidates"] == 1


def test_no_api_key_fails(tmp_path, monkeypatch):
    """未配置 key：处理失败且报错指明环境变量（划重点无降级）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)

    result = HighlightsProcessor().process(path)

    assert not result.success
    assert "DEEPSEEK_API_KEY" in result.error


def test_too_little_text_fails(tmp_path, monkeypatch):
    """OCR 兜底关闭时：总字数低于阈值判疑似纯扫描件，失败并提示先 OCR。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    path = _make_pdf(tmp_path, ["只有一点点字"], monkeypatch)

    result = HighlightsProcessor({"ocr_fallback": False}).process(path)

    assert not result.success
    assert "OCR" in result.error


def test_scanned_pdf_ocr_fallback(tmp_path, monkeypatch):
    """无文字层扫描件：逐页渲染走 OCR 重建正文，正常代读（2026-09-16 裁决 C）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    _FakeOcrProcessor.text = "扫描页正文。" * 60
    path = _make_pdf(tmp_path, ["", "", ""], monkeypatch)  # 三页全无文字

    result = HighlightsProcessor(
        {"ocr_structured": False}, ocr_factory=_FakeOcrProcessor
    ).process(path)

    assert result.success
    assert result.metadata["ocr"] is True
    assert result.metadata["pages"] == 3
    assert len(_FakeOcrProcessor.calls) == 3
    assert "- [ ] **概念甲**（第 3 页）" in result.markdown


def test_scanned_pdf_ocr_all_failed(tmp_path, monkeypatch):
    """OCR 全部失败：明确报错（不静默产出空清单）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _FakeOcrProcessor.fail = True
    path = _make_pdf(tmp_path, ["", ""], monkeypatch)

    result = HighlightsProcessor(
        {"ocr_structured": False}, ocr_factory=_FakeOcrProcessor
    ).process(path)

    assert not result.success
    assert "OCR 全部失败" in result.error


def test_scanned_pdf_ocr_page_cap(tmp_path, monkeypatch):
    """超过 ocr_max_pages 只 OCR 前 N 页，warnings 注明截断（成本护栏）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([])),
    )
    _FakeOcrProcessor.text = "扫描页正文。" * 60
    path = _make_pdf(tmp_path, ["", "", "", ""], monkeypatch)

    result = HighlightsProcessor(
        {"ocr_max_pages": 2, "ocr_structured": False}, ocr_factory=_FakeOcrProcessor
    ).process(path)

    assert result.success
    assert len(_FakeOcrProcessor.calls) == 2
    assert result.metadata["pages"] == 2
    assert any("OCR 上限" in w for w in result.metadata["warnings"])


def test_scanned_pdf_structured_rebuild(tmp_path, monkeypatch):
    """结构化重建（2026-09-16 裁决）：书版式 markdown + 插图裁切 + 页锚。"""
    from pathlib import Path

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    path = _make_pdf(tmp_path, ["", ""], monkeypatch)

    result = HighlightsProcessor(structure_factory=_FakeStructure).process(path)

    assert result.success
    assert result.metadata["ocr"] is True
    assert len(_FakeStructure.calls) == 2
    assert _FakeOcrProcessor.calls == []  # 结构化接管，纯文本 OCR 未用
    text = result.text
    assert "<!-- p1 -->" in text
    assert "![[图片/p0001-img_in_image_box_1_2_3_4.jpg]]" in text
    assert "*模型结构图*" in text
    assert "## 何为语言？" in text
    assets = result.metadata["ocr_assets"]
    assert assets and len(list(Path(assets).iterdir())) == 2


def test_structured_unavailable_falls_back(tmp_path, monkeypatch):
    """结构化引擎不可用（工厂返回 None）：退回纯文本 OCR 并记 warning。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    _FakeOcrProcessor.text = "扫描页正文。" * 60
    path = _make_pdf(tmp_path, ["", ""], monkeypatch)

    result = HighlightsProcessor(
        structure_factory=lambda: None, ocr_factory=_FakeOcrProcessor
    ).process(path)

    assert result.success
    assert len(_FakeOcrProcessor.calls) == 2
    assert result.metadata["ocr_assets"] is None
    assert any("结构化引擎不可用" in w for w in result.metadata["warnings"])


def test_chunking_respects_page_boundary(tmp_path, monkeypatch):
    """小 chunk_chars：按页聚合不切断单页；页数=片段数（每页超上限）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    seen_bodies = []

    def _post(url, **kwargs):
        seen_bodies.append(kwargs["json"]["messages"][0]["content"])
        return _FakeLLMResponse(_payload([]))

    monkeypatch.setattr(hl_module.httpx, "post", _post)
    pages = ["甲" * 200, "乙" * 200, "丙" * 200]
    path = _make_pdf(tmp_path, pages, monkeypatch)
    processor = HighlightsProcessor({"chunk_chars": 250})

    result = processor.process(path)

    assert result.success
    assert result.metadata["chunks"] == 3
    for index, body in enumerate(seen_bodies, 1):
        assert f"【第 {index} 页】" in body


def test_max_chunks_guard(tmp_path, monkeypatch):
    """片段数超护栏：截断并记 warning。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([])),
    )
    pages = ["字" * 200] * 5
    path = _make_pdf(tmp_path, pages, monkeypatch)
    processor = HighlightsProcessor({"chunk_chars": 250, "max_chunks": 2})

    result = processor.process(path)

    assert result.success
    assert result.metadata["chunks"] == 2
    assert any("护栏" in warning for warning in result.metadata["warnings"])


def test_merge_dedupes_and_prefers_recommend(tmp_path, monkeypatch):
    """同名候选跨块合并：推荐标记取或，锚点取首次出现页码。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    responses = iter(
        [
            _payload([_item(anchor=8, recommend=False)]),
            _payload([_item(anchor=3, recommend=True)]),
        ]
    )
    monkeypatch.setattr(
        hl_module.httpx, "post", lambda *a, **kw: _FakeLLMResponse(next(responses))
    )
    pages = ["甲" * 300, "乙" * 300]
    path = _make_pdf(tmp_path, pages, monkeypatch)
    processor = HighlightsProcessor({"chunk_chars": 250})

    result = processor.process(path)

    assert result.metadata["candidates"] == 1
    assert "（第 3 页）" in result.markdown
    assert "推荐勾" in result.markdown


def test_max_candidates_cap(tmp_path, monkeypatch):
    """候选超过上限：截断到 2 条，且推荐项排最前。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    items = [_item(title=f"概念{ch}", recommend=(ch == "丁")) for ch in "甲乙丙丁"]
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload(items)),
    )
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)
    processor = HighlightsProcessor({"max_candidates": 2})

    result = processor.process(path)

    assert result.metadata["candidates"] == 2
    checkboxes = [
        line for line in result.markdown.splitlines() if line.startswith("- [ ]")
    ]
    assert len(checkboxes) == 2
    assert "**概念丁**" in checkboxes[0]  # 唯一推荐项必须排第一


def test_chunk_failure_does_not_block_others(tmp_path, monkeypatch):
    """单块 LLM 失败：记 warning 继续，其他块候选照常入清单。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []

    def _flaky(url, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("api down")
        return _FakeLLMResponse(_payload([_item()]))

    monkeypatch.setattr(hl_module.httpx, "post", _flaky)
    pages = ["甲" * 300, "乙" * 300]
    path = _make_pdf(tmp_path, pages, monkeypatch)
    processor = HighlightsProcessor({"chunk_chars": 250})

    result = processor.process(path)

    assert result.success
    assert result.metadata["candidates"] == 1
    assert any("片段 1 失败" in warning for warning in result.metadata["warnings"])
    assert "## 加工警告" in result.markdown


def test_normalize_bad_fields(tmp_path, monkeypatch):
    """LLM 返回脏字段：nature 兜底待验、anchor 兜底 0、target 兜底。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    dirty = [{"title": "脏概念", "nature": "未知", "anchor": "abc", "recommend": 1}]
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload(dirty)),
    )
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)

    result = HighlightsProcessor().process(path)

    assert result.success
    assert "  - 对着：待读者判断" in result.markdown
    assert "  - 性质：待验" in result.markdown
    assert "（第" not in result.markdown.split("**脏概念**")[1].split("\n")[0]
    assert "推荐勾" in result.markdown  # 真值性转换：1 → True


def test_unsupported_extension_fails(tmp_path, monkeypatch):
    """非 PDF 输入：按不支持扩展名失败。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    path = tmp_path / "note.txt"
    path.write_text("正文", encoding="utf-8")

    result = HighlightsProcessor().process(path)

    assert not result.success
    assert "扩展名" in result.error


# ----------------------------------------------------------------------
# 书籍模式（2026-09-14 裁决，对齐 Cognitive OS 准入协议：建档+导读+筛查）
# ----------------------------------------------------------------------


def _book_payload(book):
    return {
        "choices": [
            {"message": {"content": json.dumps({"book": book}, ensure_ascii=False)}}
        ]
    }


def _book(title="认知觉醒", clc="B84-心理学", level="L2"):
    return {
        "title": title,
        "author": "周岭",
        "edition": "第1版",
        "isbn": "",
        "clc": clc,
        "level": level,
        "level_reason": "方法论可复用",
        "mainline": "用认知科学解释成长",
        "chapter_advice": [{"chapter": "第三章 专注力", "why": "对着你的目标"}],
    }


def _post_book_mode(book, candidates, calls=None):
    """按提示词路由假 LLM 应答：建档/导读 vs 挑候选。"""
    def _post(url, **kwargs):
        prompt = kwargs["json"]["messages"][0]["content"]
        if calls is not None:
            calls.append(prompt)
        if "书籍建档与导读" in prompt:
            return _FakeLLMResponse(_book_payload(book))
        return _FakeLLMResponse(_payload(candidates))
    return _post


def test_book_mode_profile_and_guide(tmp_path, monkeypatch):
    """页数达标：进书籍模式——标题升级、导读节齐全、档案进 metadata。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post", _post_book_mode(_book(), [_item()])
    )
    toc = [(1, "第一章 大脑", 1), (1, "第三章 专注力", 40)]
    path = _make_pdf(tmp_path, ["甲" * 300, "乙" * 300], monkeypatch, toc=toc)

    result = HighlightsProcessor({"book_min_pages": 2}).process(path)

    assert result.success
    assert result.markdown.startswith("# 《认知觉醒》导读与筛查清单")
    assert "## 导读（机器代读）" in result.markdown
    assert "主线：用认知科学解释成长" in result.markdown
    assert "第一章 大脑（第 1 页）" in result.markdown  # 章节地图
    assert "第三章 专注力——对着你的目标" in result.markdown  # 值得细读
    assert "级别建议 L2" in result.markdown
    assert "- [ ] **概念甲**（第 3 页）" in result.markdown  # 复选框格式不变
    book = result.metadata["book"]
    assert book["title"] == "认知觉醒"
    assert book["author"] == "周岭"
    assert book["clc"] == "B84-心理学"


def test_short_doc_skips_book_mode(tmp_path, monkeypatch):
    """页数不达门槛：无导读、无档案，且不多花一次建档 LLM 调用。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []
    monkeypatch.setattr(
        hl_module.httpx, "post", _post_book_mode(_book(), [_item()], calls)
    )
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)

    result = HighlightsProcessor().process(path)

    assert result.success
    assert result.markdown.startswith("# 划重点清单：book")
    assert "## 导读" not in result.markdown
    assert result.metadata["book"] is None
    assert all("书籍建档与导读" not in prompt for prompt in calls)


def test_book_profile_failure_degrades(tmp_path, monkeypatch):
    """建档/导读调用失败：只记 warning，清单与候选照常产出。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _post(url, **kwargs):
        prompt = kwargs["json"]["messages"][0]["content"]
        if "书籍建档与导读" in prompt:
            raise RuntimeError("api down")
        return _FakeLLMResponse(_payload([_item()]))

    monkeypatch.setattr(hl_module.httpx, "post", _post)
    path = _make_pdf(tmp_path, ["甲" * 300, "乙" * 300], monkeypatch)

    result = HighlightsProcessor({"book_min_pages": 2}).process(path)

    assert result.success
    assert result.metadata["book"] is None
    assert any("导读/档案生成失败" in w for w in result.metadata["warnings"])
    assert "- [ ] **概念甲**（第 3 页）" in result.markdown


def test_book_profile_normalization(tmp_path, monkeypatch):
    """档案脏字段：clc 不合中图法形状丢弃、level 非 L1/L2 兜底 L1、书名兜底文件名。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    dirty = _book(title="", clc="心理学", level="L3")  # L3 非法（机器永不建议）
    monkeypatch.setattr(
        hl_module.httpx, "post", _post_book_mode(dirty, [_item()])
    )
    path = _make_pdf(tmp_path, ["甲" * 300, "乙" * 300], monkeypatch)

    result = HighlightsProcessor({"book_min_pages": 2}).process(path)

    book = result.metadata["book"]
    assert book["title"] == "book"  # 回退文件名
    assert book["clc"] == ""
    assert book["level"] == "L1"


def test_context_provider_injected_into_prompt(tmp_path, monkeypatch):
    """读者上下文（目标/待办）注入挑候选提示词；无提供者时不出现。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []
    monkeypatch.setattr(
        hl_module.httpx, "post", _post_book_mode(_book(), [], calls)
    )
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)

    processor = HighlightsProcessor(
        context_provider=lambda: ["目标：减脂", "待办：写月报"]
    )
    result = processor.process(path)

    assert result.success
    assert any(
        "目标：减脂" in prompt and "待办：写月报" in prompt for prompt in calls
    )

    calls.clear()
    HighlightsProcessor().process(path)
    assert all("目标：减脂" not in prompt for prompt in calls)


def test_merge_orders_challenge_first_among_recommended(tmp_path, monkeypatch):
    """推荐项内「挑战」排最前（US-001 §7.9：对着待决策、挑战认知的优先）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    items = [
        _item(title="支持项", nature="支持", recommend=True, anchor=2),
        _item(title="挑战项", nature="挑战", recommend=True, anchor=9),
        _item(title="路人项", nature="待验", recommend=False, anchor=1),
    ]
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload(items)),
    )
    path = _make_pdf(tmp_path, ["正文。" * 300], monkeypatch)

    result = HighlightsProcessor().process(path)

    checkboxes = [
        line for line in result.markdown.splitlines() if line.startswith("- [ ]")
    ]
    assert "**挑战项**" in checkboxes[0]
    assert "**支持项**" in checkboxes[1]
    assert "**路人项**" in checkboxes[2]


# --- 结构化全文 polish（2026-09-16 排版修复）---


def test_polish_wraps_code_lines_in_fence():
    """散装代码段落 → ```python 围栏，全角符号在围栏内修复。"""
    raw = (
        "<!-- p45 -->\n\n"
        "## 第2步 分词\n\n"
        "定义一个分词函数，用它将文本分割成单个汉字字符。\n\n"
        "#定义一个分词函数，将文本转换为单个字符的列表\n\n"
        "def tokenize(text):\n\n"
        "return[char for char in text]#将文本拆分为字符列表\n\n"
        "正文继续。\n"
    )
    out = hl_module._polish_structured_markdown(raw)
    assert "```python\n#定义一个分词函数,将文本转换为单个字符的列表\ndef tokenize(text):\nreturn[char for char in text]#将文本拆分为字符列表\n```" in out
    assert "正文继续。" in out
    # 围栏外正文不受影响
    assert "定义一个分词函数，用它将文本分割成单个汉字字符。" in out


def test_polish_fixes_fullwidth_inside_code_only():
    """全角括号/冒号只在代码围栏内修复，正文里的全角不动。"""
    raw = (
        "ngrams_count=defaultdict（Counter）#创建一个字典\n\n"
        "fromcollections importdefaultdict,Counter#导入所需库\n\n"
        "for text in corpus：\n\n"
        "bigram_counts=count_ngrams(corpus，2)#计算词频\n\n"
        "正文（这里）的括号：不动，逗号也不动。\n"
    )
    out = hl_module._polish_structured_markdown(raw)
    assert "ngrams_count=defaultdict(Counter)#创建一个字典" in out
    assert "fromcollections importdefaultdict,Counter#导入所需库" in out
    assert "for text in corpus:" in out
    assert "bigram_counts=count_ngrams(corpus,2)#计算词频" in out
    assert "正文（这里）的括号：不动，逗号也不动。" in out


def test_polish_removes_in_out_markers():
    """Jupyter 提示符被误判的 ## In / ## Out 标题删除。"""
    raw = "## In \n\nimport numpy as np \n\n## Out \n\n正文。\n"
    out = hl_module._polish_structured_markdown(raw)
    assert "## In" not in out
    assert "## Out" not in out
    assert "import numpy as np" in out


def test_polish_strips_pseudo_table_but_keeps_real_table():
    """|作者简介| 伪表格去竖线；真实表格（分隔行）原样保留。"""
    raw = (
        "|作者简介|\n\n"
        "| 列甲 | 列乙 |\n| --- | --- |\n| 1 | 2 |\n"
    )
    out = hl_module._polish_structured_markdown(raw)
    assert "|作者简介|" not in out
    assert "作者简介" in out
    assert "| 列甲 | 列乙 |\n| --- | --- |\n| 1 | 2 |" in out


def test_polish_merges_split_chapter_heading():
    """被拆成两块的章节名（## 第4课 + # 标题）合并成一行二级标题。"""
    raw = "## 第4课\n\n# 柳暗花明又一村：Seq2Seq架构 \n\n正文。\n"
    out = hl_module._polish_structured_markdown(raw)
    assert "## 第4课 柳暗花明又一村：Seq2Seq架构" in out
    assert "\n# 柳暗花明" not in out


def test_polish_collapses_blank_runs():
    """连续空行压成一个（围栏内不动）。"""
    raw = "第一段。\n\n\n\n第二段。\n"
    out = hl_module._polish_structured_markdown(raw)
    assert "\n\n\n" not in out
    assert "第一段。\n\n第二段。" in out


def test_polish_keeps_anchors_images_and_frontmatter():
    """页锚、图片内嵌、frontmatter 原样保留。"""
    raw = (
        "---\ncreated: '2026-09-16T13:35:00+08:00'\n---\n\n"
        "# 书名 全文\n\n<!-- p30 -->\n\n"
        "![[attachments/书籍/x/图片/p0030-img.jpg]]\n\n*图注*\n"
    )
    out = hl_module._polish_structured_markdown(raw)
    assert out.startswith("---\ncreated: '2026-09-16T13:35:00+08:00'\n---\n")
    assert "<!-- p30 -->" in out
    assert "![[attachments/书籍/x/图片/p0030-img.jpg]]" in out


def test_polish_toc_line_not_fenced():
    """目录页行（1.1N-Gram模型026）不是代码，不进围栏。"""
    raw = "1.1N-Gram模型026\n\n1.2“词”是什么030\n"
    out = hl_module._polish_structured_markdown(raw)
    assert "```" not in out


def test_polish_is_idempotent():
    """二次 polish 不再改动（已有围栏跳过、空行已压缩）。"""
    raw = (
        "---\ncreated: 'x'\n---\n\n|作者简介|\n\n## In \n\n"
        "import numpy as np \n\nnp.zeros((2,2))\n\n\n正文（保留）。\n"
    )
    once = hl_module._polish_structured_markdown(raw)
    twice = hl_module._polish_structured_markdown(once)
    assert once == twice


def test_polish_merges_adjacent_python_fences():
    """仅隔空行的相邻 python 围栏合并（分批/分段识别产生的碎片）。"""
    raw = "```python\nimport numpy as np\n```\n\n\n```python\nnp.zeros((2,2))\n```\n\n正文。\n"
    out = hl_module._polish_structured_markdown(raw)
    assert out.count("```python") == 1
    assert "```python\nimport numpy as np\nnp.zeros((2,2))\n```" in out


# --- 文字层 PDF 插图提取（2026-09-16 backlog 落地）---


class _FakeImgPage:
    """带嵌入插图的假页（文字层 + get_images）。"""

    def __init__(self, text, images=()):
        self._text = text
        self._images = images

    def get_text(self, _mode):
        return self._text

    def get_images(self, full=True):
        return self._images


class _FakeImgDoc:
    """带 extract_image 的假文档。"""

    def __init__(self, pages, store):
        self._pages = pages
        self._store = store  # {xref: (bytes, ext)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]

    def get_toc(self):
        return []

    def extract_image(self, xref):
        data, ext = self._store[xref]
        return {"image": data, "ext": ext}


def _install_fake_fitz_images(monkeypatch, pages, store):
    import sys
    import types

    fake = types.SimpleNamespace(
        open=lambda _path: _FakeImgDoc(pages, store),
        Matrix=lambda *a, **kw: None,
    )
    monkeypatch.setitem(sys.modules, "fitz", fake)


def _big_png(tag=b"A"):
    return b"\x89PNG" + tag * 5000  # >4KB，过字节下限


def test_textlayer_images_extracted(tmp_path, monkeypatch):
    """文字层 PDF：嵌入插图按页抽出、引用追加进对应页文本末尾、
    assets 目录经 metadata 交给 media 收编。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    store = {7: (_big_png(), "png"), 9: (_big_png(b"B"), "jpeg")}
    pages = [
        _FakeImgPage("第一页正文。" * 60, images=[(7, 0, 800, 600, 8, "", "", "", 0, 0)]),
        _FakeImgPage("第二页正文。" * 60, images=[(9, 0, 900, 700, 8, "", "", "", 0, 0)]),
    ]
    _install_fake_fitz_images(monkeypatch, pages, store)
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF fake")

    result = HighlightsProcessor().process(path)

    assert result.success
    assert "![[图片/p0001-img7.png]]" in result.text
    assert "![[图片/p0002-img9.jpeg]]" in result.text
    assets = result.metadata.get("ocr_assets")
    assert assets
    from pathlib import Path as _P

    names = sorted(p.name for p in _P(assets).iterdir())
    assert names == ["p0001-img7.png", "p0002-img9.jpeg"]


def test_textlayer_images_skip_small_and_duplicates(tmp_path, monkeypatch):
    """小图（<120px 或 <4KB）与跨页重复 xref（社标）只抽一次。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    store = {
        3: (b"\x89PNG" + b"C" * 100, "png"),      # <4KB 跳过
        5: (_big_png(b"D"), "png"),                # 合格，但两页重复 → 只抽一次
        6: (_big_png(b"E"), "png"),                # 尺寸 20x20 跳过
    }
    logo = (5, 0, 800, 600, 8, "", "", "", 0, 0)
    pages = [
        _FakeImgPage("第一页。" * 80, images=[(3, 0, 800, 600, 8, "", "", "", 0, 0), logo, (6, 0, 20, 20, 8, "", "", "", 0, 0)]),
        _FakeImgPage("第二页。" * 80, images=[logo]),
    ]
    _install_fake_fitz_images(monkeypatch, pages, store)
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF fake")

    result = HighlightsProcessor().process(path)

    assert result.success
    assert result.text.count("![[图片/p") == 1
    assert "![[图片/p0001-img5.png]]" in result.text
    from pathlib import Path as _P

    assets = _P(result.metadata["ocr_assets"])
    assert [p.name for p in assets.iterdir()] == ["p0001-img5.png"]


def test_textlayer_extract_images_disabled(tmp_path, monkeypatch):
    """extract_images=False：全文保持纯文字，metadata 无 assets。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        hl_module.httpx, "post",
        lambda *a, **kw: _FakeLLMResponse(_payload([_item()])),
    )
    store = {7: (_big_png(), "png")}
    pages = [_FakeImgPage("正文。" * 250, images=[(7, 0, 800, 600, 8, "", "", "", 0, 0)])]
    _install_fake_fitz_images(monkeypatch, pages, store)
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF fake")

    result = HighlightsProcessor(config={"extract_images": False}).process(path)

    assert result.success
    assert "![[图片/" not in result.text
    assert result.metadata.get("ocr_assets") is None
