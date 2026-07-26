"""卡组构筑（交互式）：选择 4 名出战式神 → 各选至多 8 种卡牌并设定张数 → 导出卡组码。

主菜单入口见 client/cli.py；卡组码格式见 db/deckcode.py。
"""
from __future__ import annotations

from db import deckcode
from db.deck import MAX_COPIES_PER_NAME, MAX_KINDS_PER_SHIKIGAMI, validate_deck
from db.loader import CardDatabase

_CTYPES = {"spell": "法术", "combat": "战斗", "form": "形态",
           "field": "幻境", "reinforce": "协战"}


def available_shikigami(db: CardDatabase) -> list:
    """全部可构筑式神（kind=shikigami，按 id 排序）。"""
    return sorted((d for d in db.shikigami.values() if d.kind == "shikigami"),
                  key=lambda d: d.id)


def buildable_cards(db: CardDatabase, sid: int) -> list:
    """某式神全部可构筑（非衍生）卡牌，按 id 排序。"""
    return sorted((c for c in db.cards.values()
                   if not c.token and c.shikigami == sid), key=lambda c: c.id)


def _input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def run_deckbuilder(db: CardDatabase) -> None:
    """交互式卡组构筑；成功时打印卡组码（可在热坐对战开局前导入）。"""
    pool = available_shikigami(db)
    print("—— 卡组构筑：选择 4 名出战式神 ——")
    for i, d in enumerate(pool):
        print(f"  [{i + 1}] {d.name}（{d.faction}）")
    try:
        chosen = [pool[int(x) - 1] for x in _input("式神序号（空格分隔）> ").split()]
    except (ValueError, IndexError):
        print("序号有误，已取消构筑")
        return
    ids = [d.id for d in chosen]
    card_ids: list[int] = []
    for d in chosen:
        cards = buildable_cards(db, d.id)
        print(f"—— {d.name} 的卡牌（至多 {MAX_KINDS_PER_SHIKIGAMI} 种，"
              f"每种至多 {MAX_COPIES_PER_NAME} 张）——")
        for i, c in enumerate(cards):
            ctype = _CTYPES.get(c.card_type, c.card_type)
            print(f"  [{i + 1}] {c.name}｜{ctype}｜等级{c.level}｜费用{c.cost}")
        line = _input("卡牌种类序号（空格分隔；回车 = 全部）> ")
        try:
            picked = cards if not line else [cards[int(x) - 1] for x in line.split()]
        except (ValueError, IndexError):
            print("序号有误，已取消构筑")
            return
        copies = {i + 1: 1 for i in range(len(picked))}
        tune = _input(f"张数调整（如 1=2 3=2；回车 = 每种 1 张）> ")
        for item in tune.split():
            try:
                k, v = item.split("=")
                copies[int(k)] = int(v)
            except ValueError:
                print(f"无法解析 {item!r}，已忽略")
        for i, c in enumerate(picked):
            n = max(0, min(MAX_COPIES_PER_NAME, copies.get(i + 1, 1)))
            card_ids.extend([c.id] * n)
        print(f"当前共 {len(card_ids)} 张（每名式神须恰好 "
              f"{MAX_KINDS_PER_SHIKIGAMI} 张）")
    errors = validate_deck(db, ids, card_ids)
    if errors:
        print("卡组不合法：")
        print("\n".join(errors))
        return
    code = deckcode.encode_deck(deckcode.group_deck(db, ids, card_ids))
    print(f"卡组完成（共 {len(card_ids)} 张），卡组码（热坐对战开局前粘贴导入）：")
    print(code)
