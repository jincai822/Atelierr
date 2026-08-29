"""文本清洗小工具。"""

from __future__ import annotations


def clean_text(text: str) -> str:
    """压缩多余空白：去除每行首尾空白，连续空行折叠为单个空行。

    Args:
        text: 原始文本。

    Returns:
        str: 清洗后的文本（首尾无空行）。

    Examples:
        >>> clean_text("  a \\n\\n\\n b  ")
        'a\\n\\nb'
    """
    lines = text.splitlines()
    cleaned: list = []
    prev_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        cleaned.append(stripped)
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)
