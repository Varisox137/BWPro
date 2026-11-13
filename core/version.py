"""应用运行版本与严格的 Release 标签比较。"""
from __future__ import annotations

import re

VERSION = "0.3.4"
_VERSION_PATTERN = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def parse_version(tag: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"非法版本标签：{tag!r}")
    return tuple(int(part) for part in match.groups())
