"""本地卡组存储：~/.bwp.decks.json。

格式：{"version": 1, "decks": [{"name": str, "code": str}, ...]}，
code 为 db/deckcode.py 的卡组码。进入卡组构筑/对战前读取；
每次校验通过的卡组自动写回（原子写入）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path.home() / ".bwp.decks.json"


def load_decks(path: Path = PATH) -> list[dict]:
    """读取全部本地卡组；文件不存在返回 []，损坏时打印警告并返回 []。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        print(f"警告：卡组文件 {path} 无法读取（{e}），视为空")
        return []
    decks = data.get("decks") if isinstance(data, dict) else None
    if not isinstance(decks, list):
        return []
    return [d for d in decks
            if isinstance(d, dict) and isinstance(d.get("name"), str)
            and isinstance(d.get("code"), str)]


def save_decks(decks: list[dict], path: Path = PATH) -> None:
    """原子写入本地卡组文件（先写临时文件再替换）；文件/目录不存在时自动创建。"""
    payload = json.dumps({"version": 1, "decks": decks}, ensure_ascii=False, indent=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
