"""终端文本工具：CJK 显示宽度计算、按宽度补齐、TTY 颜色（client 各模块共用）。"""
from __future__ import annotations

import os
import sys
import unicodedata


def display_width(s: str) -> int:
    """计算字符串在等宽终端中的显示宽度（CJK 字符计为 2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in s)


def pad(s: str, width: int) -> str:
    """按显示宽度补齐到指定宽度。"""
    return s + " " * max(0, width - display_width(s))


# ---------- 颜色 ----------

USE_COLOR: bool | None = None  # None=惰性自动判定；测试可显式置 True/False


def use_color() -> bool:
    """颜色仅在 TTY 下启用；管道输出或 NO_COLOR 环境变量时关闭。"""
    global USE_COLOR
    if USE_COLOR is None:
        USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    return USE_COLOR


def colored(text: str, code: int | None) -> str:
    """按 ANSI 色号包裹文本（须在 pad 之后调用，以免破坏列对齐）。"""
    if code is None or not use_color():
        return text
    return f"\033[{code}m{text}\033[0m"
