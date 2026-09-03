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
    def __init__(self, texts):
        self._pages = [_FakePage(t) for t in texts]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]


def _install_fake_fitz(monkeypatch, page_texts):
    """注册假 fitz 模块：open() 返回固定页文本的假文档。"""
    fake = types.SimpleNamespace(open=lambda _path: _FakeDoc(page_texts))
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


def _make_pdf(tmp_path, page_texts, monkeypatch, name="book.pdf"):
    _install_fake_fitz(monkeypatch, page_texts)
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
