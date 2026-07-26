"""维护者给出的初期测试数据（4 式神 × 8 卡，数据源 thoughts.txt）。

数据格式（来自 thoughts.txt）：
- 式神：6位id 名称 派系 基础力量/基础生命
- 卡牌：2位id 稀有度 名称 等级 类型 [数值] [关键字]

约定：
- 已落地的机制在此同步（供 CLI 热座试玩）：4 式神 32 卡全录——白狼/兵俑/妖刀姬/一目连的基础能力、
  文射/妖刀万华的[连击]、起弓/离/无我（攻击后到期强化）、残心、觉醒·白狼/觉醒·兵俑、
  不祥之刃/禁锢之刀/冲撞（击杀标记与增强装配）、觉醒·妖刀姬、杀念（随机生成）、
  风符系列倒计时形态（破/护/势/湮/龙）、罡风、觉醒·一目连、风符·瞬（含响应）、
  会（延迟触发）、援护/古尘之盾（响应法术）、见切（响应战斗牌插入使用）、
  尘刀（护甲快照战力）、不动如山/古尘之壁/森罗之阵（进场时效果与形态能力）、尘缚之阵（激怒与战斗区锁定）；
  正式数据以 db/cards、db/shikigami 的 YAML 为准，本文件与其保持一致的部分逐步移交。
- 未落地的机制仅以数值/瞬发/cost=0 占位：战斗牌简化为力量/护甲修正，
  形态牌按给定数值覆盖基础身材，觉醒牌为永久修正 + awaken tag。
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
    # 已落地的式神能力（与 db/shikigami YAML 一致）
    shikigami[100101].ability = EffectBlock(
        when="on_damage", timing="insert",
        condition={"source_shikigami": "self", "victim_side": "enemy",
                   "victim_kind": "shikigami", "kind": "combat", "active": "self"},
        steps=[Step(op="damage", amount=2, target=TargetSpec(kind="all", pool="enemy_player"))],
    )
    shikigami[100101].text = "己方回合，每当白狼对敌方式神造成战斗伤害时（即时时机），对敌方牌手造成2点伤害"
    shikigami[100102].ability = EffectBlock(
        when="on_turn_start",
        condition={"player": "self"},
        steps=[Step(op="gain_shield", amount=2, target=_self_target())],
    )
    shikigami[100102].text = "己方回合开始时，兵俑获得2护甲"
    shikigami[100123].ability = EffectBlock(
        when="on_player_damaged",
        condition={"source_shikigami": "self", "kind": "combat"},
        steps=[Step(op="card_aura", shikigami="self", card_type="combat",
                    keywords=["fast"])],
    )
    shikigami[100123].text = "当妖刀姬对敌方牌手造成战斗伤害时，本回合她的所有战斗牌具有[瞬发]"
    shikigami[100125].ability = EffectBlock(
        when="on_form_destroyed",
        condition={"target_shikigami": "self"},
        steps=[Step(op="trigger_form_countdown")],
    )
    shikigami[100125].text = "一目连的形态牌离场或被消灭时，触发其[倒计时]效果"
    cards: dict[int, CardDef] = {}

    def add(sid: int, no: int, rarity: str, name: str, level: int, ctype: str,
            *, cost: int = 1, keywords: list[str] | None = None,
            power: int = 0, shield: int = 0,
            form_power: int | None = None, form_health: int | None = None,
            perm_power: int = 0, perm_health: int = 0,
            subtype: str | None = None, text: str = "") -> None:
        cid = sid * 100 + no
        kw = keywords or []
        effects = EffectBlock(steps=[])
        if ctype == "combat":
            effects = _stat_steps(power=power, shield=shield)
        elif ctype == "spell" and (perm_power or perm_health):
            subtype = "awaken"
            effects = _perm_steps(power=perm_power, health=perm_health)
        elif ctype == "spell" and (power or shield):
            effects = _stat_steps(power=power, shield=shield)
        # form 的身材由 form_power/form_health 提供，不通过 effects
        cards[cid] = CardDef(
            id=cid, version=VER, name=name, shikigami=sid,
            card_type=ctype, subtype=subtype, level=level, cost=cost, keywords=kw,
            form_power=form_power, form_health=form_health,
            effects=effects, text=text,
        )

    # 100101 白狼
    add(100101, 1, "R", "起弓", 1, "spell", keywords=["fast"],
        text="[瞬发]。抽一张牌，白狼获得+1力量以及[穿刺]，直到白狼的下一次攻击后")
    cards[10010101].effects = EffectBlock(steps=[
        Step(op="draw", count=1, target=TargetSpec(kind="all", pool="self_player")),
        Step(op="attack_buff", power=1, keywords=["pierce"], target=_self_target()),
    ])
    add(100101, 2, "R", "文射", 1, "combat", keywords=["combo"], power=-2, shield=2,
        text="-2力量/+2护甲，[连击]")
    add(100101, 3, "SR", "残心", 1, "form", form_power=3, form_health=5,
        keywords=["remote", "keep_attack_buffs"],
        text="[远程]。白狼的法术强化效果不会在攻击后移除")
    add(100101, 4, "R", "离", 2, "spell", keywords=["fast"],
        text="[瞬发]。白狼获得+3力量，直到白狼的下一次攻击后")
    cards[10010104].effects = EffectBlock(steps=[
        Step(op="attack_buff", power=3, target=_self_target()),
    ])
    add(100101, 5, "R", "会", 2, "spell",
        text="选择一名敌方式神，你的下个回合开始时，白狼对其造成8点伤害")
    cards[10010105].target = TargetSpec(kind="choose", pool="enemy_shikigami")
    cards[10010105].effects = EffectBlock(steps=[
        Step(op="delay_grant", when="on_turn_start", condition={"player": "self"},
             steps=[{"op": "damage", "amount": 8}]),
    ])
    add(100101, 6, "SR", "援护", 2, "spell", keywords=["trigger"],
        text="对敌方战斗区式神造成等同于白狼力量值的伤害。"
             "[响应]：{当己方其他式神被攻击时，自动使用此牌}")
    cards[10010106].effects = EffectBlock(
        when="on_before_assault",
        condition={"victim_side": "friendly", "victim_kind": "shikigami",
                   "victim_not_shikigami": 100101},
        steps=[Step(op="damage", amount={"power_of": "source"},
                    target=TargetSpec(kind="all", pool="enemy_combat"))],
    )
    add(100101, 7, "SR", "觉醒·白狼", 3, "spell",
        perm_power=2, perm_health=2,
        text="[觉醒]：{己方回合，每当白狼对敌方式神造成伤害时，对敌方牌手造成4点伤害}")
    cards[10010107].abilities = [EffectBlock(
        when="on_damage", timing="insert",
        condition={"source_shikigami": "self", "victim_side": "enemy",
                   "victim_kind": "shikigami", "active": "self"},
        steps=[Step(op="damage", amount=4, target=TargetSpec(kind="all", pool="enemy_player"))],
    )]
    add(100101, 8, "SSR", "无我", 3, "spell", keywords=["fast"],
        text="[瞬发]。白狼获得+3力量、[不屈]、[贯通]、[迅捷]，直到白狼的下一次攻击后")
    cards[10010108].effects = EffectBlock(steps=[
        Step(op="attack_buff", power=3, keywords=["unyielding", "piercing", "haste"],
             target=_self_target()),
    ])

    # 100102 兵俑
    add(100102, 1, "R", "尘刀", 1, "combat",
        text="兵俑每具有1点护甲，本次战斗中兵俑就获得+1力量")
    cards[10010201].effects = EffectBlock(steps=[
        Step(op="buff_power", amount={"shield_of": "self"}, target=_self_target()),
    ])
    add(100102, 2, "R", "古尘之盾", 1, "spell", keywords=["trigger"],
        text="使一名己方式神获得5护甲。[响应]：{当兵俑被攻击时，对其自动使用此牌}")
    cards[10010202].target = TargetSpec(kind="choose", pool="friendly_shikigami")
    cards[10010202].effects = EffectBlock(
        when="on_before_assault",
        condition={"victim_shikigami": 100102},
        steps=[Step(op="gain_shield", amount=5)],
    )
    add(100102, 3, "R", "不动如山", 2, "form", form_power=1, form_health=9,
        text="进场时，将兵俑移入战斗区。己方回合开始时，若兵俑在战斗区，兵俑获得3力量")
    cards[10010203].effects = EffectBlock(steps=[
        Step(op="enter_combat", target=_self_target()),
    ])
    cards[10010203].abilities = [EffectBlock(
        when="on_turn_start",
        condition={"player": "self", "shikigami_in_combat": 100102},
        steps=[Step(op="buff_power", amount=3, perm=True, target=_self_target())],
    )]
    add(100102, 4, "SR", "冲撞", 2, "combat",
        text="[增强]：{己方回合开始时，若兵俑在战斗区，此牌获得+1力量/+1护甲}")
    cards[10010204].effects = EffectBlock(steps=[
        Step(op="buff_power", amount={"enhance": True, "base": 2}, target=_self_target()),
        Step(op="gain_shield", amount={"enhance": True, "base": 2}, target=_self_target()),
    ])
    cards[10010204].triggers = [EffectBlock(
        when="on_turn_start",
        condition={"player": "self", "shikigami_in_combat": 100102},
        steps=[Step(op="add_mod", to="hand", key="enhance", amount=1)],
    )]
    add(100102, 5, "SR", "森罗之阵", 2, "form", form_power=4, form_health=7,
        text="进场时，兵俑获得2护甲。只要兵俑具有护甲，他至多只会受到等于护甲值的伤害")
    cards[10010205].effects = EffectBlock(steps=[
        Step(op="gain_shield", amount=2, target=_self_target()),
    ])
    cards[10010205].abilities = [EffectBlock(
        when="on_damage_start",
        condition={"victim_shikigami": "self"},
        steps=[Step(op="cap_damage", to="shield")],
    )]
    add(100102, 6, "SSR", "觉醒·兵俑", 2, "spell", subtype="awaken",
        text="兵俑获得3护甲。[觉醒]：{己方回合开始时，兵俑获得3护甲。"
             "他的护甲不会在己方回合开始时移除。}")
    cards[10010206].effects = EffectBlock(steps=[
        Step(op="gain_shield", amount=3, target=_self_target()),
        Step(op="keep_shield", target=_self_target()),
    ])
    cards[10010206].abilities = [EffectBlock(
        when="on_turn_start",
        condition={"player": "self"},
        steps=[Step(op="gain_shield", amount=3, target=_self_target())],
    )]
    add(100102, 7, "SR", "古尘之壁", 3, "form", form_power=5, form_health=10,
        text="进场时，兵俑每具有1护甲，使己方所有其他式神获得+1生命/生命上限")
    cards[10010207].effects = EffectBlock(steps=[
        Step(op="buff_health", amount={"shield_of": "source"}, perm=True,
             target=TargetSpec(kind="all", pool="friendly_others")),
    ])
    add(100102, 8, "R", "尘缚之阵", 3, "form", form_power=5, form_health=9,
        text="进场时，选择一名敌方式神，使其获得[激怒]。只要兵俑在战斗区且敌方战斗区有式神，"
             "为敌方召唤召唤物的效果无效、敌方准备区式神不能发起不具有[远程]的战斗")
    cards[10010208].tags = ["combat_lock"]
    cards[10010208].target = TargetSpec(kind="choose", pool="enemy_shikigami")
    cards[10010208].effects = EffectBlock(steps=[
        Step(op="grant_keyword", keyword="enraged"),
    ])

    # 100123 妖刀姬
    add(100123, 1, "R", "不祥之刃", 1, "combat", power=0, shield=1,
        text="若妖刀姬于此战斗牌所发起的战斗中消灭了敌方式神，抽一张牌")
    cards[10012301].temp_grants = [EffectBlock(
        when="on_shikigami_defeated",
        condition={"victim_side": "enemy", "victim_kind": "shikigami",
                   "source_shikigami": "self"},
        steps=[Step(op="draw", count=1, target=TargetSpec(kind="all", pool="self_player"))],
    )]
    add(100123, 2, "SR", "见切", 1, "combat", keywords=["trigger"],
        text="+1力量，免疫战斗伤害。[响应]：{当妖刀姬被攻击时，自动使用此牌}")
    cards[10012302].effects = EffectBlock(
        when="on_before_assault",
        condition={"victim_shikigami": 100123},
        steps=[Step(op="buff_power", amount=1, target=_self_target()),
               Step(op="battle_immunity", target=_self_target())],
    )
    add(100123, 3, "R", "战意", 2, "combat", power=2, shield=2, text="+2力量/+2护甲")
    add(100123, 4, "R", "一闪", 2, "combat", cost=0, power=0, shield=0, text="+0力量/+0护甲，不消耗鬼火")
    add(100123, 5, "SR", "禁锢之刀", 2, "combat",
        text="[增强]：{本局游戏中，妖刀姬每消灭过一名敌方式神，此牌便获得+2力量}")
    cards[10012305].effects = EffectBlock(steps=[
        Step(op="buff_power", amount={"enhance": True, "base": 0}, target=_self_target()),
        Step(op="gain_shield", amount=2, target=_self_target()),
    ])
    cards[10012305].triggers = [EffectBlock(
        when="on_shikigami_defeated",
        condition={"victim_side": "enemy", "victim_kind": "shikigami",
                   "source_side": "friendly", "source_shikigami": 100123},
        steps=[Step(op="add_mod", to="persistent", key="enhance", amount=2)],
    )]
    add(100123, 6, "R", "妖刀万华", 3, "form", keywords=["combo"],
        form_power=3, form_health=8, text="3力量/8生命，[连击]")
    add(100123, 7, "SR", "杀念", 3, "spell",
        text="随机生成3张妖刀姬的战斗牌并置入手牌")
    cards[10012307].effects = EffectBlock(steps=[
        Step(op="generate", shikigami="self", card_type="combat", count=3),
    ])
    add(100123, 8, "SSR", "觉醒·妖刀姬", 3, "spell",
        perm_power=1, perm_health=1,
        text="[觉醒]：{[迅捷]。当妖刀姬对敌方牌手造成战斗伤害时，本回合她的所有战斗牌不消耗鬼火。}")
    cards[10012308].abilities = [
        EffectBlock(
            when="on_awakened", condition={"target_shikigami": "self"},
            steps=[Step(op="grant_keyword", keyword="haste", target=_self_target())],
        ),
        EffectBlock(
            when="on_shikigami_revived", condition={"shikigami_shikigami": "self"},
            steps=[Step(op="grant_keyword", keyword="haste", target=_self_target())],
        ),
        EffectBlock(
            when="on_player_damaged",
            condition={"source_shikigami": "self", "kind": "combat"},
            steps=[Step(op="card_aura", shikigami="self", card_type="combat",
                        cost_zero=True)],
        ),
    ]

    # 100125 一目连
    add(100125, 1, "R", "风符·破", 1, "form", form_power=3, form_health=6,
        text="[倒计时2]：{[投射]：{造成3点伤害}}")
    cards[10012501].countdown = 2
    cards[10012501].countdown_effects = EffectBlock(steps=[
        Step(op="damage", amount=3, target=TargetSpec(kind="all", pool="projectile")),
    ])
    add(100125, 2, "R", "风符·护", 1, "form", form_power=2, form_health=7,
        text="[倒计时2]：{己方牌手获得5护甲}")
    cards[10012502].countdown = 2
    cards[10012502].countdown_effects = EffectBlock(steps=[
        Step(op="gain_shield", amount=5, target=TargetSpec(kind="all", pool="self_player")),
    ])
    add(100125, 3, "R", "罡风", 2, "spell", keywords=["fast"],
        text="[瞬发]。消灭一目连的形态，抽两张牌。")
    cards[10012503].effects = EffectBlock(steps=[
        Step(op="destroy_form", target=_self_target()),
        Step(op="draw", count=2, target=TargetSpec(kind="all", pool="self_player")),
    ])
    add(100125, 4, "R", "风符·势", 2, "form", form_power=3, form_health=8,
        text="[倒计时2]：{[鼓舞]：{获得+3战力/+3护甲}}")
    cards[10012504].countdown = 2
    cards[10012504].countdown_effects = EffectBlock(steps=[
        Step(op="basic_boost", power=3, shield=3),
    ])
    add(100125, 5, "SR", "觉醒·一目连", 2, "spell", subtype="awaken",
        text="随机生成一张一目连的形态牌并置入手牌。"
             "[觉醒]：{一目连的形态牌进场、离场、被消灭时，触发其[倒计时]效果。}")
    cards[10012505].effects = EffectBlock(steps=[
        Step(op="buff_power", amount=2, perm=True, target=_self_target()),
        Step(op="generate", shikigami="self", card_type="form", count=1),
    ])
    cards[10012505].abilities = [
        EffectBlock(when="on_form_attached", condition={"target_shikigami": "self"},
                    steps=[Step(op="trigger_form_countdown")]),
        EffectBlock(when="on_form_destroyed", condition={"target_shikigami": "self"},
                    steps=[Step(op="trigger_form_countdown")]),
    ]
    add(100125, 6, "SR", "风符·瞬", 2, "form", keywords=["fast", "trigger"],
        form_power=6, form_health=9,
        text="[瞬发]。回合结束时此牌自毁。[响应]：{当一目连被攻击时，自动使用此牌。}")
    cards[10012506].effects = EffectBlock(
        when="on_before_assault",
        condition={"victim_shikigami": 100125},
        steps=[],
    )
    cards[10012506].abilities = [EffectBlock(
        when="on_turn_end",
        steps=[Step(op="destroy_form", target=_self_target())],
    )]
    add(100125, 7, "SR", "风符·湮", 3, "form", form_power=4, form_health=6,
        text="[倒计时2]：{消灭敌方战斗区式神}")
    cards[10012507].countdown = 2
    cards[10012507].countdown_effects = EffectBlock(steps=[
        Step(op="destroy", target=TargetSpec(kind="all", pool="enemy_combat")),
    ])
    add(100125, 8, "SSR", "风符·龙", 3, "form", form_power=5, form_health=8,
        text="[倒计时2]：{随机对1名敌方角色造成6点伤害（并行结算）。下一次此能力的作用目标+1。}")
    cards[10012508].countdown = 2
    cards[10012508].countdown_effects = EffectBlock(steps=[
        Step(op="random_damage", amount=6, pool="enemy_character",
             count={"mod": "count", "base": 1}),
        Step(op="add_mod", to="instance", key="count", amount=1),
    ])

    return CardDatabase(cards, shikigami, set())


def make_test_deck(shikigami_ids: list[int] | None = None) -> list[int]:
    """合法测试卡组：4 位式神各 8 种不同名卡牌各带 1（共 32 张）。"""
    ids = shikigami_ids or TEST_IDS
    return [sid * 100 + n for sid in ids for n in range(1, 9)]
