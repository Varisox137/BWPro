"""维护者给出的 Phase 1 初期测试数据。

数据格式（来自 thoughts.txt）：
- 式神：6位id 名称 派系 基础力量/基础生命
- 卡牌：2位id 稀有度 名称 等级 类型 [数值] [关键字]

Phase 1 测试约定：
- 式神无能力。
- 卡牌仅含数值修正、【瞬发】关键字、cost=0 表示【不消耗鬼火】。
- 战斗牌简化为给使用者临时力量/护甲修正，不展开完整战斗流程。
- 形态牌按给定数值覆盖基础身材。
- 觉醒牌按给定数值施加永久力量/生命修正，并标记 awaken tag。
"""
from __future__ import annotations

from db.loader import CardDatabase
from db.schema import CardDef, EffectBlock, ShikigamiDef, Step, TargetSpec

VER = 20260724

TEST_SHIKIGAMI: list[tuple[int, str, str, int, int]] = [
    # (id, 名称, 派系, 力量, 生命)
    (100101, "白狼", "苍叶", 3, 4),
    (100102, "兵俑", "紫岩", 1, 6),
    (100123, "妖刀姬", "苍叶", 3, 4),
    (100125, "一目连", "苍叶", 2, 6),
]

TEST_IDS = [s[0] for s in TEST_SHIKIGAMI]


def _self_target() -> TargetSpec:
    """效果目标为卡牌所属式神。"""
    return TargetSpec(kind="self")


def _stat_steps(power: int = 0, shield: int = 0) -> EffectBlock:
    """战斗牌/法术牌的数值修正：力量（临时）与护甲。"""
    steps: list[Step] = []
    if power != 0:
        steps.append(Step(op="buff_power", target=_self_target(), amount=power))
    if shield != 0:
        steps.append(Step(op="gain_shield", target=_self_target(), amount=shield))
    return EffectBlock(steps=steps)


def _perm_steps(power: int = 0, health: int = 0) -> EffectBlock:
    """觉醒牌的永久修正。"""
    steps: list[Step] = []
    if power != 0:
        steps.append(Step(op="buff_power", target=_self_target(), amount=power, perm=True))
    if health != 0:
        steps.append(Step(op="buff_health", target=_self_target(), amount=health, perm=True))
    return EffectBlock(steps=steps)


def make_test_db() -> CardDatabase:
    """根据 thoughts.txt 初始化测试数据库。"""
    shikigami = {
        sid: ShikigamiDef(id=sid, version=VER, name=name, faction=faction,
                          power=atk, health=hp, text="")
        for sid, name, faction, atk, hp in TEST_SHIKIGAMI
    }
    cards: dict[int, CardDef] = {}

    def add(sid: int, no: int, rarity: str, name: str, level: int, ctype: str,
            *, cost: int = 1, keywords: list[str] | None = None,
            power: int = 0, shield: int = 0,
            form_power: int | None = None, form_health: int | None = None,
            perm_power: int = 0, perm_health: int = 0,
            text: str = "") -> None:
        cid = sid * 100 + no
        kw = keywords or []
        tags: list[str] = []
        effects = EffectBlock(steps=[])
        if ctype == "combat":
            effects = _stat_steps(power=power, shield=shield)
        elif ctype == "spell" and (perm_power or perm_health):
            tags.append("awaken")
            effects = _perm_steps(power=perm_power, health=perm_health)
        elif ctype == "spell" and (power or shield):
            effects = _stat_steps(power=power, shield=shield)
        # form 的身材由 form_power/form_health 提供，不通过 effects
        cards[cid] = CardDef(
            id=cid, version=VER, name=name, shikigami=sid,
            card_type=ctype, level=level, cost=cost, keywords=kw,
            tags=tags, form_power=form_power, form_health=form_health,
            effects=effects, text=text,
        )

    # 100101 白狼
    add(100101, 1, "R", "起弓", 1, "spell", keywords=["fast"], text="瞬发")
    add(100101, 2, "R", "文射", 1, "combat", power=-2, shield=2, text="-2力量/+2护甲")
    add(100101, 3, "SR", "残心", 1, "form", form_power=3, form_health=5, text="3力量/5生命")
    add(100101, 4, "R", "离", 2, "spell", keywords=["fast"], text="瞬发")
    add(100101, 5, "R", "会", 2, "spell", text="")
    add(100101, 6, "SR", "援护", 2, "spell", text="")
    add(100101, 7, "SR", "觉醒·白狼", 3, "spell",
        perm_power=2, perm_health=2, text="觉醒：+2永久力量/+2永久生命上限")
    add(100101, 8, "SSR", "无我", 3, "spell", keywords=["fast"], text="瞬发")

    # 100102 兵俑
    add(100102, 1, "R", "尘刀", 1, "combat", text="")
    add(100102, 2, "R", "古尘之盾", 1, "spell", text="")
    add(100102, 3, "R", "不动如山", 2, "form", form_power=1, form_health=9, text="1力量/9生命")
    add(100102, 4, "SR", "冲撞", 2, "combat", power=2, shield=2, text="+2力量/+2护甲")
    add(100102, 5, "SR", "森罗之阵", 2, "form", form_power=4, form_health=7, text="4力量/7生命")
    add(100102, 6, "SSR", "觉醒·兵俑", 2, "spell",
        perm_power=0, perm_health=0, text="觉醒")
    add(100102, 7, "SR", "古尘之壁", 3, "form", form_power=5, form_health=10, text="5力量/10生命")
    add(100102, 8, "R", "尘缚之阵", 3, "form", form_power=5, form_health=9, text="5力量/9生命")

    # 100123 妖刀姬
    add(100123, 1, "R", "不祥之刃", 1, "combat", power=0, shield=1, text="+0力量/+1护甲")
    add(100123, 2, "SR", "见切", 1, "combat", power=1, shield=0, text="+1力量/+0护甲")
    add(100123, 3, "R", "战意", 2, "combat", power=2, shield=2, text="+2力量/+2护甲")
    add(100123, 4, "R", "一闪", 2, "combat", cost=0, power=0, shield=0, text="+0力量/+0护甲，不消耗鬼火")
    add(100123, 5, "SR", "禁锢之刀", 2, "combat", power=0, shield=2, text="+0力量/+2护甲")
    add(100123, 6, "R", "妖刀万华", 3, "form", form_power=3, form_health=8, text="3力量/8生命")
    add(100123, 7, "SR", "杀念", 3, "spell", text="")
    add(100123, 8, "SSR", "觉醒·妖刀姬", 3, "spell",
        perm_power=1, perm_health=1, text="觉醒：+1永久力量/+1永久生命上限")

    # 100125 一目连
    add(100125, 1, "R", "风符·破", 1, "form", form_power=3, form_health=6, text="3力量/6生命")
    add(100125, 2, "R", "风符·护", 1, "form", form_power=2, form_health=7, text="2力量/7生命")
    add(100125, 3, "R", "罡风", 2, "spell", keywords=["fast"], text="瞬发")
    add(100125, 4, "R", "风符·势", 2, "form", form_power=3, form_health=8, text="3力量/8生命")
    add(100125, 5, "SR", "觉醒·一目连", 2, "spell",
        perm_power=2, perm_health=0, text="觉醒：+2永久力量/+0永久生命上限")
    add(100125, 6, "SR", "风符·瞬", 2, "form", keywords=["fast"],
        form_power=6, form_health=9, text="6力量/9生命，瞬发")
    add(100125, 7, "SR", "风符·湮", 3, "form", form_power=4, form_health=6, text="4力量/6生命")
    add(100125, 8, "SSR", "风符·龙", 3, "form", form_power=5, form_health=8, text="5力量/8生命")

    return CardDatabase(cards, shikigami, set())


def make_test_deck(shikigami_ids: list[int] | None = None) -> list[int]:
    """合法测试卡组：每式神取前 4 种卡各 ×2（共 32 张）。"""
    ids = shikigami_ids or TEST_IDS
    return [sid * 100 + n for sid in ids for n in range(1, 5) for _ in range(2)]
