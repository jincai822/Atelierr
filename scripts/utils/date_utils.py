"""日期解析工具：统一把各种输入规范为本地时区 aware datetime。"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime, time as _time, tzinfo
from typing import Union


def local_timezone() -> tzinfo:
    """返回当前本地时区。

    Returns:
        tzinfo: 本地时区对象。
    """
    return datetime.now().astimezone().tzinfo


def parse_date(value: Union[datetime, _date, str]) -> datetime:
    """把 datetime / ISO 字符串 / "YYYY-MM-DD" 解析为本地时区 aware datetime。

    输入的 naive datetime 视为本地时间；带时区偏移的 ISO 字符串保持原时区
    （aware 比较基于 UTC，语义不变）。

    Args:
        value: datetime 对象、ISO 8601 字符串（如 "2026-08-29T10:30:00"、
            "2026-08-29T10:30:00+08:00"）或日期字符串（"2026-08-29"）。

    Returns:
        datetime: 本地时区 aware 的 datetime；纯日期输入按本地 00:00:00。

    Raises:
        ValueError: 无法解析的输入。

    Examples:
        >>> parse_date("2026-08-29").date()
        datetime.date(2026, 8, 29)
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=local_timezone())
        return value
    if isinstance(value, _date):
        return datetime.combine(value, _time.min).replace(tzinfo=local_timezone())
    if isinstance(value, str):
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                day = _date.fromisoformat(text)
            except ValueError:
                raise ValueError(f"无法解析日期: {value!r}") from None
            return datetime.combine(day, _time.min).replace(tzinfo=local_timezone())
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_timezone())
        return dt
    raise ValueError(f"无法解析日期: {value!r}")
