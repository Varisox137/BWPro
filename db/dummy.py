"""占位测试数据：真实卡牌数据按维护者要求暂不放入（见 thoughts.txt）。

生成 4 个无效果式神（派系 红莲/红莲/紫岩/无相，恰好满足组卡派系规则）
+ 每式神 8 种不同名、无效果的空白法术牌（等级 1-3 交错），
用于测试卡组构筑与对战流程。维护者后续给出真实数据后，本模块可删除。
"""
from __future__ import annotations

from db.loader import CardDatabase
from db.schema import CardDef, EffectBlock, ShikigamiDef

VER = 20260720

DUMMY_SHIKIGAMI: list[tuple[int, str, str, int, int]] = [
    # (id, 名称, 派系, 力量, 生命)
    (100101, "占位式神·壹", "红莲", 3, 4),
    (100102, "占位式神·贰", "红莲", 4, 6),
    (100103, "占位式神·叁", "紫岩", 2, 5),
    (100104, "占位式神·肆", "无相", 3, 3),
]

DUMMY_IDS = [s[0] for s in DUMMY_SHIKIGAMI]


def make_dummy_db() -> CardDatabase:
    shikigami = {
        sid: ShikigamiDef(id=sid, version=VER, name=name, faction=faction,
                          power=atk, health=hp, text="占位式神（无效果）")
        for sid, name, faction, atk, hp in DUMMY_SHIKIGAMI
    }
    cards: dict[int, CardDef] = {}
    for sid, *_ in DUMMY_SHIKIGAMI:
        for n in range(1, 9):  # 每式神 8 种不同名卡，等级 1-3 交错
            cid = sid * 100 + n
            cards[cid] = CardDef(
                id=cid, version=VER, name=f"空白法术{sid % 100:02d}-{n}",
                shikigami=sid, card_type="spell", level=(n - 1) % 3 + 1, cost=1,
                effects=EffectBlock(steps=[]), text="（空白占位卡，无效果）")
    return CardDatabase(cards, shikigami, set())


def dummy_deck(shikigami_ids: list[int] | None = None) -> list[int]:
    """合法占位卡组：每式神取前 4 种卡各 ×2（共 32 张）。"""
    ids = shikigami_ids or DUMMY_IDS
    return [sid * 100 + n for sid in ids for n in range(1, 5) for _ in range(2)]
