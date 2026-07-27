"""本地卡组存储：~/.bwp.decks.json。

格式（v2）：
    {"version": 2,
     "decks": [[is_standard, {"name": str, "groups": groups}], ...]}
其中 groups 为 db/deckcode.py 的分组结构 [[shiki_id, [card_id, ...]], ...]；
is_standard 是"是否满足天梯组卡规则"的缓存标记——每次加载与保存时都按当前
规则与卡牌数据库重新校验（规则/数据变更后标记自动刷新）。

文件数据不符合应有格式：提示"本地卡组文件异常"并删除该文件（返回空列表）。
保存为原子写入；文件/目录不存在时自动创建。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from db import deckcode
from db.deck import STANDARD_RULES, DeckRules, validate_deck

PATH = Path.home() / ".bwp.decks.json"


def _valid_groups(g) -> bool:
    return (isinstance(g, list) and bool(g) and all(
        isinstance(item, list) and len(item) == 2
        and isinstance(item[0], int)
        and isinstance(item[1], list)
        and all(isinstance(x, int) for x in item[1])
        for item in g))


def check_deck(db, groups: list, rules: DeckRules = STANDARD_RULES) -> bool:
    """该分组卡组是否满足给定组卡规则。"""
    ids = [sid for sid, _ in groups]
    cards = [cid for _, cs in groups for cid in cs]
    return not validate_deck(db, ids, cards, rules)


def entry_deck(entry: dict) -> tuple[list[int], list[int]]:
    """条目 → (式神 ids, 卡牌 ids)。"""
    groups = entry["groups"]
    return [sid for sid, _ in groups], [cid for _, cs in groups for cid in cs]


def entry_code(entry: dict) -> str:
    """条目 → 卡组码（导出/分享/联机提交用）。"""
    return deckcode.encode_deck(entry["groups"])


def load_decks(db, path: Path = PATH,
               rules: DeckRules = STANDARD_RULES) -> list[dict]:
    """读取全部本地卡组并按当前规则重新校验 is_standard。

    文件不存在返回 []；数据格式不符：提示"本地卡组文件异常"并删除该文件。
    返回条目：{"name": str, "groups": [...], "standard": bool}。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as e:
        print(f"本地卡组文件异常（{e}），已删除：{path}")
        _delete(path)
        return []
    try:
        decks_raw = json.loads(raw)["decks"]
        if not isinstance(decks_raw, list):
            raise TypeError("decks 不是列表")
        entries = []
        for item in decks_raw:
            standard_flag, d = item
            if not isinstance(standard_flag, bool) or not isinstance(d, dict):
                raise TypeError("条目结构非法")
            name, groups = d["name"], d["groups"]
            if not isinstance(name, str) or not _valid_groups(groups):
                raise TypeError("条目结构非法")
            entries.append({"name": name, "groups": groups,
                            "standard": check_deck(db, groups, rules)})
    except Exception:
        print(f"本地卡组文件异常，已删除：{path}")
        _delete(path)
        return []
    return entries


def save_decks(db, decks: list[dict], path: Path = PATH,
               rules: DeckRules = STANDARD_RULES) -> None:
    """保存全部本地卡组：写入前按当前规则重新校验每个卡组的 is_standard；
    原子写入（先写临时文件再替换）；文件/目录不存在时自动创建。"""
    payload = json.dumps({
        "version": 2,
        "decks": [[check_deck(db, e["groups"], rules),
                   {"name": e["name"], "groups": e["groups"]}] for e in decks],
    }, ensure_ascii=False, indent=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _delete(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
