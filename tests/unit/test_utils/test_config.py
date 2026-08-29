"""utils 工具函数单元测试。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from scripts.utils.config import deep_get, load_config
from scripts.utils.date_utils import parse_date
from scripts.utils.file_utils import ensure_dir
from scripts.utils.text_utils import clean_text


def test_load_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("memory:\n  root: /x\n", encoding="utf-8")
    assert load_config(p) == {"memory": {"root": "/x"}}


def test_load_config_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_empty_returns_empty(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("", encoding="utf-8")
    assert load_config(p) == {}


def test_load_config_tilde_expands(tmp_path, monkeypatch):
    p = tmp_path / "c.yaml"
    p.write_text("a: 1\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_config("~/c.yaml") == {"a": 1}


def test_deep_get():
    data = {"memory": {"decay": {"rate": 0.95}}}
    assert deep_get(data, "memory.decay.rate") == 0.95
    assert deep_get(data, "memory.missing") is None
    assert deep_get(data, "memory.decay.rate", default=9) == 0.95
    assert deep_get({}, "a.b.c", default=5) == 5
    assert deep_get({"a": 1}, "a.b") is None


def test_ensure_dir(tmp_path):
    p = ensure_dir(tmp_path / "a" / "b")
    assert p.exists()
    assert p.is_dir()
    # 已存在时幂等
    assert ensure_dir(p) == p


def test_clean_text():
    assert clean_text("  a \n\n\n b \n  ") == "a\n\nb"
    assert clean_text("a\n\n\n\nb\n\n") == "a\n\nb"
    assert clean_text("   ") == ""
    assert clean_text("单行") == "单行"


def test_parse_date_datetime_naive_localized():
    dt = datetime(2026, 8, 29, 10, 30)
    parsed = parse_date(dt)
    assert parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None) == dt


def test_parse_date_iso_string():
    parsed = parse_date("2026-08-29T10:30:00")
    assert parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None) == datetime(2026, 8, 29, 10, 30)


def test_parse_date_iso_with_offset_preserved():
    parsed = parse_date("2026-08-29T10:30:00+08:00")
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 8 * 3600


def test_parse_date_date_only():
    parsed = parse_date("2026-08-29")
    assert parsed.tzinfo is not None
    assert parsed.date() == datetime(2026, 8, 29).date()
    assert parsed.hour == 0


def test_parse_date_invalid_raises():
    with pytest.raises(ValueError):
        parse_date("not-a-date")
    with pytest.raises(ValueError):
        parse_date(42)
