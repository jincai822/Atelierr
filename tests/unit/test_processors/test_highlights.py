"""划重点处理器单元测试（无真实网络/真实 PDF）。

LLM 调用 monkeypatch ``httpx.post``；PDF 页提取 monkeypatch 假 ``fitz``
模块。分块、合并去重、护栏截断、字段规范化均为真实代码路径。
"""

from __future__ import annotations

import json
import sys
import types

import scripts.processors.highlights as hl_module
from scripts.processors.highlights import HighlightsProcessor


class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self, _mode):
        return self._text


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
    fake = types.SimpleNamespace(open=lambda _path: _FakeDoc(page_texts, toc))
    monkeypatch.setitem(sys.modules, "fitz", fake)


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
    """总字数低于阈值：判为疑似纯扫描件，失败并提示先 OCR。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    path = _make_pdf(tmp_path, ["只有一点点字"], monkeypatch)

    result = HighlightsProcessor().process(path)

    assert not result.success
    assert "OCR" in result.error


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
