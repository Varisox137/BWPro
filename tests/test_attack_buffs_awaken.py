"""攻击后到期强化（attack_buff）与觉醒机制测试。

对应 docs/rules.md"直到攻击后"（起弓/离/无我）与第十三章（觉醒替换）；
残心的 keep_attack_buffs、觉醒·兵俑的 keep_shield 同为第二批落地机制。
测试辅助卡使用衍生号段（51+，token=True）。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, give, move

T = F.T
SELF = T(kind="self")
ENEMY_PLAYER = T(kind="all", pool="enemy_player")


def _attack_buff_card(db, cid: int, power: int = 0, keywords=()) -> None:
    """起弓/离/无我型法术牌：[瞬发] + 攻击后到期强化。"""
    db.cards[cid] = F.card(
        cid, keywords=["fast"],
        steps=[F.Step(op="attack_buff", power=power, keywords=list(keywords), target=SELF)],
        token=True)


def _bailang_base_ability(db) -> None:
    """白狼基础能力：己方回合战斗伤害 → 敌方牌手 -2（即时时机）。"""
    db.shikigami[100101].ability = F.EffectBlock(
        when="on_damage", timing="insert",
        condition={"source_shikigami": "self", "victim_side": "enemy",
                   "victim_kind": "shikigami", "kind": "combat", "active": "self"},
        steps=[F.Step(op="damage", amount=2, target=ENEMY_PLAYER)],
    )


def _awaken_bailang(db, cid: int = 10010157) -> int:
    """觉醒·白狼：+2/+2 永久修正 + 任意伤害版白狼能力（-4）。"""
    db.cards[cid] = F.card(
        cid, level=3, subtype="awaken",
        steps=[F.Step(op="buff_power", amount=2, perm=True, target=SELF),
               F.Step(op="buff_health", amount=2, perm=True, target=SELF)],
        abilities=[F.EffectBlock(
            when="on_damage", timing="insert",
            condition={"source_shikigami": "self", "victim_side": "enemy",
                       "victim_kind": "shikigami", "active": "self"},
            steps=[F.Step(op="damage", amount=4, target=ENEMY_PLAYER)],
        )],
        token=True)
    return cid


# ---------- 攻击后到期强化 ----------

def test_attack_buff_consumed_after_own_attack(db, make_game):
    """起弓型强化：自身出击的战斗终止点核销力量与授予的关键字。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=1, keywords=["pierce"])
    g = make_game()
    move(g, 1, 0)
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert a.temp_power == 1
    assert "pierce" in a.keywords
    assert len(a.attack_buffs) == 1
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 0
    assert "pierce" not in a.keywords
    assert a.attack_buffs == []


def test_attack_buff_kept_when_attacked(db, make_game):
    """作为被攻击者的战斗不核销：强化保留到自身下一次攻击后。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=1)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    move(g, 0, 0)  # 驻留战斗区，成为敌方出击的被攻击者
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 1
    assert len(a.attack_buffs) == 1


def test_attack_buff_haste_free_assault_full_consume(db, make_game):
    """无我型强化：迅捷免鬼火出击（次数照扣），战斗后全部强化一并核销。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=3, keywords=["unyielding", "piercing", "haste"])
    g = make_game()
    pa = g.state.players[0]
    a = pa.shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    pa.orb = 0  # 迅捷：无鬼火也可出击
    g.apply({"op": "assault", "index": 0})
    assert pa.assaults_left == 0
    assert a.temp_power == 0
    assert "haste" not in a.one_shot_keywords
    assert "unyielding" not in a.one_shot_keywords
    assert "piercing" not in a.keywords
    assert a.attack_buffs == []


def test_keep_attack_buffs_survives_until_form_replaced(db, make_game):
    """残心：持有 keep_attack_buffs 时攻击后不核销；形态替换失去后，下一次攻击核销。"""
    buff_cid, form_cid, plain_cid = 10010151, 10010152, 10010153
    _attack_buff_card(db, buff_cid, power=1, keywords=["pierce"])
    db.cards[form_cid] = F.card(form_cid, card_type="form", keywords=["keep_attack_buffs"],
                                form_power=3, form_health=5, token=True)
    db.cards[plain_cid] = F.card(plain_cid, card_type="form",
                                 form_power=2, form_health=4, token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 4
    a = pa.shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, form_cid).uid})
    g.apply({"op": "play_card", "uid": give(g, 0, buff_cid).uid})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 1
    assert len(a.attack_buffs) == 1
    assert "pierce" in a.keywords
    g.apply({"op": "play_card", "uid": give(g, 0, plain_cid).uid})  # 替换形态，失去残心
    assert "keep_attack_buffs" not in a.keywords
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 0
    assert a.attack_buffs == []
    assert "pierce" not in a.keywords


def test_attack_buff_cleared_on_defeat(db, make_game):
    """气绝清账：临时力量与挂账随气绝一并清空。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=3, keywords=["piercing"])
    g = make_game()
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert a.defeated
    assert a.temp_power == 0
    assert a.attack_buffs == []


# ---------- 白狼基础能力 ----------

def test_bailang_ability_combat_damage(db, make_game):
    """白狼基础能力：己方回合对敌方式神造成战斗伤害，即时对敌方牌手造成 2。"""
    _bailang_base_ability(db)
    g = make_game()
    move(g, 1, 0)
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "assault", "index": 0})
    assert pl.shikigami[0].health == 1  # 吃 3 战斗伤害
    assert pl.health == 28              # 能力 -2（反击伤害来源非白狼，不再触发）


def test_bailang_ability_effect_damage_no_trigger(db, make_game):
    """白狼基础能力：法术（effect 伤害）不触发。"""
    _bailang_base_ability(db)
    cid = 10010154
    db.cards[cid] = F.card(cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True)
    g = make_game()
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid,
             "target": Ref(player=1, shikigami=0)})
    assert pl.shikigami[0].health == 1
    assert pl.health == 30  # 未触发


def test_bailang_ability_opponent_turn_no_trigger(db, make_game):
    """白狼基础能力：非己方回合不触发（active: self 限定）。"""
    _bailang_base_ability(db)
    g = make_game()
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "end_turn"})  # 进入 B 的回合
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 3, Ref(player=0, shikigami=0), kind="combat")
    assert pl.shikigami[0].health == 1
    assert pl.health == 30  # 未触发


# ---------- 觉醒 ----------

def test_awaken_bailang_stats_and_replaced_ability(db, make_game):
    """觉醒·白狼：+2/+2 永久修正；能力替换为任意伤害版（法术伤害也触发，伤害 4）。"""
    _bailang_base_ability(db)
    cid = _awaken_bailang(db)
    dmg_cid = 10010154
    db.cards[dmg_cid] = F.card(dmg_cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 3
    a = pa.shikigami[0]
    a.level = 3
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert a.perm_power == 2 and a.perm_health == 2
    assert a.health == 6
    assert a.awakened == cid
    assert "on_awakened" in g.history
    # 法术伤害也触发觉醒能力（无 kind 限定）
    g.apply({"op": "play_card", "uid": give(g, 0, dmg_cid).uid,
             "target": Ref(player=1, shikigami=0)})
    assert pl.health == 26  # 觉醒能力 -4
    # 战斗伤害触发的是 -4 的觉醒版，而非 -2 的基础版
    move(g, 1, 0)
    g.apply({"op": "assault", "index": 0})
    assert pl.health == 22


def test_awaken_bailang_persists_through_revive(db, make_game):
    """觉醒状态气绝/复活保留：永久修正与觉醒能力在复活后仍生效。"""
    cid = _awaken_bailang(db)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.level = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert a.defeated
    assert a.awakened == cid  # 气绝不清觉醒状态
    a.revive_countdown = 0
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 回合开始：复活
    assert not a.defeated
    assert a.health == 6  # 永久生命修正保留（4 + 2）
    pl = g.state.players[1]
    pl.shield = 0
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, Ref(player=0, shikigami=0), kind="combat")
    assert pl.health == 26  # 觉醒能力仍触发（-4）


def test_awaken_hyottoko_shield_kept_and_stacked(db, make_game):
    """觉醒·兵俑：打出 +3 护甲且不再于己方回合开始移除；之后每己方回合开始 +3（替换基础 +2）。"""
    db.shikigami[100102].ability = F.EffectBlock(  # 基础能力（应被觉醒替换）
        when="on_turn_start", condition={"player": "self"},
        steps=[F.Step(op="gain_shield", amount=2, target=SELF)],
    )
    cid = 10010256
    db.cards[cid] = F.card(
        cid, shikigami=100102, level=2, subtype="awaken",
        steps=[F.Step(op="gain_shield", amount=3, target=SELF),
               F.Step(op="keep_shield", target=SELF)],
        abilities=[F.EffectBlock(
            when="on_turn_start", condition={"player": "self"},
            steps=[F.Step(op="gain_shield", amount=3, target=SELF)],
        )],
        token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 2
    s = pa.shikigami[1]
    s.level = 2
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert s.shield == 3
    assert s.keep_shield
    assert s.awakened == cid
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 2 回合开始：护甲不清除且 +3（若基础能力仍在只 +2）
    assert s.shield == 6
