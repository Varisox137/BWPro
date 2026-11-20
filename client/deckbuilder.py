"""GUI 卡组构筑与式神录共用的可构筑数据池。"""
from __future__ import annotations

from db.loader import CardDatabase
from db.packs import pack_names_for


def available_shikigami(db: CardDatabase) -> list:
    """全部可构筑式神（普通式神、非 WIP、非未发布，按 id 排序）。"""
    return sorted((d for d in db.shikigami.values()
                   if d.kind == "shikigami" and not d.wip and not d.unreleased),
                  key=lambda d: d.id)


def buildable_cards(db: CardDatabase, sid: int) -> list:
    """某式神全部可构筑卡牌：本家卡在前，第二所属式神的协战牌列最后。"""
    cards = [c for c in db.cards.values()
             if not c.token and not c.unreleased
             and (c.shikigami == sid
                  or (c.card_type == "reinforce" and c.shikigami2 == sid))]
    return sorted(cards, key=lambda c: (0 if c.shikigami == sid else 1, c.id))


def _pack_groups(db: CardDatabase, pool: list) -> list[tuple[str, list]]:
    """可构筑式神按版本包分组（官方登记序，DIY 按包号补入；空包不列出）。"""
    names = pack_names_for(db)
    groups = []
    for num in sorted(names):
        members = [d for d in pool if str(d.id)[1:4] == num]
        if members:
            groups.append((names[num], members))
    return groups
