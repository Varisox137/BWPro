"""卡组码：卡组构筑 ↔ 简短纯文本编码（JSON → zlib → urlsafe base64，去填充）。

编码结构：[[shiki_id, [card_id, ...]], ...] —— 4 名出战式神及其各自卡牌（顺序保留）。
"""
from __future__ import annotations

import base64
import json
import zlib

from db.deck import validate_deck


def default_deck(db) -> tuple[list[int], list[int]]:
    """默认卡组：前 4 名可构筑式神 + 其全部可构筑（非衍生）卡牌各 1 张。

    即当前的"4 式神各 8 种不同名卡"（32 张）。
    """
    ids = sorted(sid for sid, d in db.shikigami.items()
                 if d.kind == "shikigami")[:4]
    owned = set(ids)
    cards = sorted(cid for cid, c in db.cards.items()
                   if not c.token and c.shikigami in owned)
    return ids, cards


def group_deck(db, shikigami_ids: list[int],
               card_ids: list[int]) -> list[tuple[int, list[int]]]:
    """把 (式神列表, 卡牌列表) 按所属式神分组为 [(shiki_id, [card_id, ...]), ...]。

    卡牌顺序保留；协战牌挂在第一所属式神名下（仅编码/展示归属，与校验器的
    种类数挂载规则无关）。无法归属的卡牌静默忽略（编码前请先校验卡组）。
    """
    groups: dict[int, list[int]] = {sid: [] for sid in shikigami_ids}
    for cid in card_ids:
        c = db.cards.get(cid)
        if c is None:
            continue
        if c.shikigami in groups:
            groups[c.shikigami].append(cid)
        elif getattr(c, "shikigami2", None) in groups:
            groups[c.shikigami2].append(cid)
    return [(sid, groups[sid]) for sid in shikigami_ids]


def encode_deck(deck: list[tuple[int, list[int]]]) -> str:
    """[(shiki_id, [card_id, ...]), ...] → 卡组码。"""
    payload = json.dumps([[sid, cards] for sid, cards in deck],
                         separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(payload)).decode("ascii").rstrip("=")


def decode_deck(code: str) -> list[tuple[int, list[int]]]:
    """卡组码 → [(shiki_id, [card_id, ...]), ...]；格式非法抛 ValueError。"""
    s = code.strip()
    s += "=" * (-len(s) % 4)
    try:
        data = json.loads(zlib.decompress(
            base64.urlsafe_b64decode(s.encode("ascii"))).decode("utf-8"))
    except Exception as e:
        raise ValueError(f"卡组码无法解析（{e}）") from e
    if not isinstance(data, list) or not data:
        raise ValueError("卡组码结构非法")
    deck: list[tuple[int, list[int]]] = []
    for item in data:
        if (not isinstance(item, list) or len(item) != 2
                or not isinstance(item[0], int)
                or not isinstance(item[1], list)
                or not all(isinstance(x, int) for x in item[1])):
            raise ValueError("卡组码结构非法")
        deck.append((item[0], list(item[1])))
    return deck


def deck_from_code(db, code: str) -> tuple[list[int], list[int]]:
    """解码并按组卡规则校验，返回 (式神 id 列表, 卡牌 id 列表)；不合法抛 ValueError。"""
    deck = decode_deck(code)
    shikigami_ids = [sid for sid, _ in deck]
    card_ids = [cid for _, cards in deck for cid in cards]
    errors = validate_deck(db, shikigami_ids, card_ids)
    if errors:
        raise ValueError("卡组不合法：" + "；".join(errors))
    return shikigami_ids, card_ids
