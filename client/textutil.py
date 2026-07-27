"""终端文本工具：CJK 显示宽度计算与按宽度补齐（client/cli.py 与 deckbuilder 共用）。"""
from __future__ import annotations

import unicodedata


def display_width(s: str) -> int:
    """计算字符串在等宽终端中的显示宽度（CJK 字符计为 2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in s)


def pad(s: str, width: int) -> str:
    """按显示宽度补齐到指定宽度。"""
    return s + " " * max(0, width - display_width(s))
