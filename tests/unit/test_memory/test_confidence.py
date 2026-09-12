"""ConfidenceCalculator 单元测试（验收 1.2 全部 5 条 + 扩展）。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from scripts.memory.confidence import ConfidenceCalculator


def test_new_note_confidence():
    """新笔记（三个时间都是 now）confidence == 1.0。"""
    calc = ConfidenceCalculator()
    conf = calc.calculate(
        metadata={
            "created": datetime.now(),
            "accessed": datetime.now(),
            "modified": datetime.now(),
        }
    )
    assert conf == 1.0


def test_old_note_confidence():
    """100 天前的笔记：0.0 <= conf < 0.5。"""
    calc = ConfidenceCalculator()
    old_date = datetime.now() - timedelta(days=100)
    conf = calc.calculate(
        metadata={
            "created": old_date,
            "accessed": old_date,
            "modified": old_date,
        }
    )
    assert 0.0 <= conf < 0.5


def test_referenced_note_decays_slower():
    """同龄笔记：references=10 的衰减更慢且 conf > 0.4。"""
    calc = ConfidenceCalculator()
    old_date = datetime.now() - timedelta(days=50)
    base = {"created": old_date, "accessed": old_date, "modified": old_date}
    conf_plain = calc.calculate(metadata=base)
    conf_referenced = calc.calculate(metadata={**base, "references": 10})
    assert conf_referenced > conf_plain
    # ref_factor=3 ⇒ 等效闲置 50/3 天，应仍在 mid-term 以上
    assert conf_referenced > 0.4


def test_idempotent():
    """纯函数：同一元数据重复计算结果一致。"""
    calc = ConfidenceCalculator()
    meta = {
        "created": datetime.now() - timedelta(days=10),
        "accessed": datetime.now() - timedelta(days=10),
        "modified": datetime.now() - timedelta(days=10),
    }
    assert calc.calculate(metadata=meta) == calc.calculate(metadata=meta)


def test_confidence_range():
    """100 次随机 metadata（0-365 天、0-20 引用）结果都在 [0, 1]。"""
    calc = ConfidenceCalculator()
    rng = random.Random(42)
    now = datetime.now()
    for _ in range(100):
        days = rng.randint(0, 365)
        references = rng.randint(0, 20)
        base = now - timedelta(days=days)
        conf = calc.calculate(
            metadata={
                "created": base,
                "accessed": base,
                "modified": base,
                "references": references,
            }
        )
        assert 0.0 <= conf <= 1.0


def test_uses_modified_when_accessed_missing():
    """accessed 缺失/None 时用 modified。"""
    calc = ConfidenceCalculator()
    old = datetime.now() - timedelta(days=30)
    conf = calc.calculate(metadata={"accessed": None, "modified": old})
    assert 0.0 < conf < 1.0
    # 与两者相同的场景一致
    conf_both = calc.calculate(metadata={"accessed": old, "modified": old})
    assert conf == conf_both


def test_uses_created_when_no_activity():
    """accessed/modified 都缺时用 created。"""
    calc = ConfidenceCalculator()
    old = datetime.now() - timedelta(days=20)
    conf = calc.calculate(metadata={"created": old})
    assert 0.0 < conf < 1.0


def test_accepts_iso_strings():
    """ISO 字符串输入（naive 视为本地时间）。"""
    calc = ConfidenceCalculator()
    conf = calc.calculate(
        metadata={
            "accessed": "2026-08-01T12:00:00",
            "modified": "2026-08-01T12:00:00",
            "references": 3,
        },
        now=datetime(2026, 8, 29, 12, 0, 0),
    )
    assert 0.0 <= conf <= 1.0
    # 28 天闲置、ref_factor=1.6 → 中间值
    assert 0.3 < conf < 0.6


def test_future_time_clamped_to_one():
    """未来时间 → idle 钳 0 → confidence == 1.0。"""
    calc = ConfidenceCalculator()
    future = datetime.now() + timedelta(days=5)
    conf = calc.calculate(metadata={"accessed": future, "modified": future})
    assert conf == 1.0


def test_references_capped():
    """references 超 cap（10）后封顶，与 cap 值结果一致。"""
    calc = ConfidenceCalculator()
    old = datetime.now() - timedelta(days=50)
    base = {"created": old, "accessed": old, "modified": old}
    assert calc.calculate(metadata={**base, "references": 10}) == calc.calculate(
        metadata={**base, "references": 100}
    )
    assert calc.calculate(metadata={**base, "references": 100}) == calc.calculate(
        metadata={**base, "references": 10}
    )


def test_custom_parameters():
    """decay_rate / ref_coefficient / ref_cap 可配置。"""
    calc = ConfidenceCalculator(decay_rate=0.9, ref_coefficient=0.5, ref_cap=4)
    old = datetime.now() - timedelta(days=10)
    conf = calc.calculate(metadata={"modified": old, "references": 4})
    assert conf == pytest.approx(0.9 ** (10 / 3.0))


def test_source_factor_accelerates_decay():
    """方案 C（v1.4）：命中 source_factors 的来源时间轴乘因子——
    机器转写 15 天 ≈ 人写 45 天（均触及 0.1 待删线）。"""
    calc = ConfidenceCalculator(source_factors={"link": 3.0, "media": 3.0})
    machine = calc.from_idle_days(15, source="link")
    human = calc.from_idle_days(45, source="manual")
    assert machine == pytest.approx(human)
    assert machine < 0.1  # 触及待删线
    # media 同样加速；未登记来源不受影响
    assert calc.from_idle_days(15, source="media") == pytest.approx(machine)
    assert calc.from_idle_days(15, source="webclip") > 0.4


def test_source_factor_via_calculate_metadata():
    """calculate 的 metadata.source 键生效；缺省/空串按 1.0（v1.2 行为）。"""
    calc = ConfidenceCalculator(source_factors={"link": 3.0})
    old = datetime.now() - timedelta(days=20)
    base = {"created": old, "accessed": old, "modified": old}
    accelerated = calc.calculate(metadata={**base, "source": "link"})
    standard = calc.calculate(metadata=base)
    assert accelerated == pytest.approx(0.95 ** 60)
    assert standard == pytest.approx(0.95 ** 20)
    assert accelerated < standard


def test_source_factor_default_unchanged():
    """无 source_factors 构造（默认）：带 source 调用结果与 v1.2 完全一致。"""
    calc = ConfidenceCalculator()
    assert calc.from_idle_days(30, source="link") == pytest.approx(0.95 ** 30)
    old = datetime.now() - timedelta(days=30)
    assert calc.calculate(
        metadata={"modified": old, "source": "link"}
    ) == pytest.approx(0.95 ** 30)


def test_source_factor_negative_clamped():
    """负因子钳 0（永不衰减），空串/未知来源按 1.0。"""
    calc = ConfidenceCalculator(source_factors={"link": -2.0})
    assert calc.from_idle_days(100, source="link") == 1.0
    assert calc.from_idle_days(100, source="") == pytest.approx(0.95 ** 100)
