"""卡牌机制测试：目标、等级门、爆能、瞬发、响应、结算模式、召唤、中立、区域、mods。

测试辅助卡使用衍生号段（51+，token=True）——正式卡序号 01-08 已被 base_db 占满。
"""
import pytest

from core import targets as targets_mod
from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, give, move, pass_turns, play

T = F.T


def _add_damage_card(db, cid=10010151, amount=3, **kw):
    db.cards[cid] = F.card(cid, steps=[F.dmg(amount)], target=CHOOSE_ENEMY, token=True, **kw)
    return cid


def test_targeted_damage(db, make_game):
    cid = _add_damage_card(db)
    g = make_game()
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert g.state.players[1].shikigami[0].health == 1   # 4 - 3
    assert g.state.players[0].orb == 0
    assert c in g.state.players[0].graveyard


def test_level_gate(db, make_game):
    cid = _add_damage_card(db, level=2)
    g = make_game()
    a = g.state.players[0]
    a.orb = 2
    c = give(g, 0, cid)
    with pytest.raises(IllegalAction):                   # 100101 仅 1 级
        g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    a.shikigami[0].level = 2
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert g.state.players[1].shikigami[0].health == 1


def test_defeated_shikigami_cards_unusable(db, make_game):
    cid = _add_damage_card(db)
    g = make_game()
    a = g.state.players[0]
    a.shikigami[0].health = 0
    g.check_defeated(Ref(player=0, shikigami=0))
    a.orb = 2
    c = give(g, 0, cid)
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})


def test_playable_when_defeated(db, make_game):
    """气绝时可用：与是否响应牌无关，气绝式神的此类牌仍可使用。"""
    cid = _add_damage_card(db, playable_when_defeated=True)
    g = make_game()
    a = g.state.players[0]
    a.shikigami[0].health = 0
    g.check_defeated(Ref(player=0, shikigami=0))
    a.orb = 2
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert g.state.players[1].shikigami[0].health == 1


def test_burst_method_and_level_override(db, make_game):
    """爆能{2}：加价换强化效果（核心方式 burst + 参数 2）；使用方式可覆盖等级要求。"""
    db.cards[10010151] = F.card(
        10010151, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True,
        methods=[F.method("burst", param=2, cost_delta=2, level=2, text="爆能{2}：6 伤",
                          effects=F.block(F.dmg(6), when="on_play", mode="atomic"))])
    g = make_game()
    a = g.state.players[0]
    a.orb = 3
    c = give(g, 0, 10010151)
    with pytest.raises(IllegalAction):                   # 爆能要求 2 级，当前 1 级
        g.apply({"op": "play_card", "uid": c.uid, "play_method": "burst",
                 "target": Ref(player=1, shikigami=0)})
    a.shikigami[0].level = 2
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "burst",
             "target": Ref(player=1, shikigami=0)})
    assert g.state.players[1].shikigami[0].defeated is True  # 4 - 6，气绝
    assert a.orb == 0                                        # 1 + 2（爆能）= 3 费


def test_fast_keyword(db, make_game):
    """瞬发：每（半）回合各自第一张免费，第二张起照常。"""
    cid = _add_damage_card(db, amount=1, keywords=["fast"])
    g = make_game()
    a = g.state.players[0]
    c1, c2 = give(g, 0, cid), give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c1.uid, "target": Ref(player=1, shikigami=0)})
    assert a.orb == 1                                      # 第一张免费
    g.apply({"op": "play_card", "uid": c2.uid, "target": Ref(player=1, shikigami=0)})
    assert a.orb == 0                                      # 第二张正常付费


def _add_guard(db, cid=10010251, **kw):
    """响应守护：被出击时 insert 给被击方 2 甲。"""
    defaults = dict(
        cost=1, keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"timing": "insert",
                  "condition": {"victim_side": "friendly", "victim_kind": "shikigami"},
                  "mode": "atomic"},
        steps=[F.Step(op="gain_shield", amount=2, target=T(kind="context", key="victim"))],
    )
    defaults.update(kw)
    db.cards[cid] = F.card(cid, shikigami=100102, **defaults)
    return cid


def test_trigger_fast_at_zero_orb(db, make_game):
    """响应 + 瞬发：敌方回合 0 鬼火仍可免费触发（第一张瞬发）。"""
    cid = _add_guard(db, keywords=["trigger", "fast"])
    g = make_game()
    for p in g.state.players:
        p.hand.clear()
    a = g.state.players[0]
    a.shikigami[1].level = 1                               # 响应也须满足等级要求
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})
    give(g, 0, cid)
    g.apply({"op": "end_turn"})
    a.orb = 0                                              # 0 火
    g.apply({"op": "assault", "index": 0})                 # B 3 攻撞 A 0 号（3/4）
    a0 = a.shikigami[0]
    assert a0.health == 3                                  # 3 - 2(守护甲) = 1 → 4 - 1 = 3
    assert a0.shield == 0
    assert a.orb == 0                                      # 瞬发响应免费
    assert a.fast_used is True
    i_atk = g.history.index("on_before_assault")
    assert g.history.index("on_trigger") < g.history.index("on_damage", i_atk)


def test_trigger_requires_shikigami_level(db, make_game):
    """响应其余要求照常：对应式神等级不足则不触发。"""
    cid = _add_guard(db, level=2)
    g = make_game()
    for p in g.state.players:
        p.hand.clear()
    a = g.state.players[0]
    a.shikigami[1].level = 1                               # 守护要求 2 级
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})
    give(g, 0, cid)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.shikigami[0].health == 1                      # 守护未触发：4 - 3
    assert "on_trigger" not in g.history


def test_trigger_order_and_one_per_timing(db, make_game):
    """响应牌按所属式神从左往右触发；同一时机至多成功结算一张（复查失败不占名额）。"""
    _add_guard(db, cid=10010251)                           # 右侧式神 100102 的响应（2 甲）
    db.cards[10010152] = F.card(                           # 左侧式神 100101 的响应（3 甲）
        10010152, shikigami=100101, cost=1, keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"timing": "insert",
                  "condition": {"victim_side": "friendly", "victim_kind": "shikigami"},
                  "mode": "atomic"},
        steps=[F.Step(op="gain_shield", amount=3, target=T(kind="context", key="victim"))])
    g = make_game()
    for p in g.state.players:
        p.hand.clear()
    a = g.state.players[0]
    a.shikigami[1].level = 1
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})
    give(g, 0, 10010251)                                   # 手牌顺序：右侧的先入手
    left_card = give(g, 0, 10010152)
    g.apply({"op": "end_turn"})
    a.orb = 2                                              # 两张都付得起——隔离"同时机限一张"
    g.apply({"op": "assault", "index": 0})
    a0 = a.shikigami[0]
    assert a0.health == 4 and a0.shield == 0               # 3 甲挡住 3 攻 → 左侧先触发
    assert left_card not in a.hand
    assert any(c.id == 10010251 for c in a.hand)           # 第二张未触发（同一时机限一张）
    assert a.orb == 1                                      # 未触发的那张没有支付鬼火
    assert g.history.count("on_trigger") == 1
    assert g.history.count("on_card_played") == 1          # 响应使用同样生成"卡牌的使用事件"


def test_response_different_timings_each_one(db, make_game):
    """每空闲点限一张已取消：同一指令内的不同时机可各响应一张。"""
    _add_guard(db, cid=10010251)                           # 出击宣言时（insert）：+2 甲
    db.cards[10010252] = F.card(                           # 受伤后（queue）：+2 甲
        10010252, shikigami=100102, cost=1, keywords=["trigger"], token=True,
        when="on_damage",
        block_kw={"timing": "queue",
                  "condition": {"victim_side": "friendly", "victim_kind": "shikigami"},
                  "mode": "atomic"},
        steps=[F.Step(op="gain_shield", amount=2, target=T(kind="context", key="victim"))])
    g = make_game()
    for p in g.state.players:
        p.hand.clear()
    a = g.state.players[0]
    a.shikigami[1].level = 1
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})
    give(g, 0, 10010251)
    give(g, 0, 10010252)
    g.apply({"op": "end_turn"})
    a.orb = 2
    g.apply({"op": "assault", "index": 0})                 # B 3 攻撞 A 0 号（3/4）
    a0 = a.shikigami[0]
    assert a0.health == 3                                  # 宣言时 2 甲吸收 → 4 - 1 = 3
    assert a0.shield == 2                                  # 受伤后的第二张响应同样结算
    assert a.orb == 0                                      # 两张各付 1 火
    assert g.history.count("on_trigger") == 2
    assert g.history.count("on_card_played") == 2


def test_interleaved_vs_atomic(db, make_game):
    """多段效果：interleaved 允许步骤之间插入其它结算，atomic 不允许。"""
    # 两段卡：伤害 → 抽牌；防守方响应（queue）：受击后得甲
    db.cards[10010151] = F.card(
        10010151, cost=2, steps=[F.dmg(2), F.Step(op="draw", count=1)],
        target=CHOOSE_ENEMY, token=True, block_kw={"mode": "interleaved"})
    db.cards[10010251] = F.card(
        10010251, shikigami=100102, keywords=["trigger"], token=True, when="on_damage",
        block_kw={"timing": "queue", "condition": {"victim_side": "friendly"}, "mode": "atomic"},
        steps=[F.Step(op="gain_shield", amount=2, target=T(kind="context", key="victim"))])

    def run(mode_kw):
        db.cards[10010151].effects.mode = mode_kw
        g = make_game()
        for p in g.state.players:
            p.hand.clear()
        a, b = g.state.players
        a.shikigami[0].level = 1
        b.shikigami[1].level = 1
        a.orb = 2
        b.orb = 1
        c = give(g, 0, 10010151)
        give(g, 1, 10010251)
        g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=1)})
        return g

    g = run("interleaved")
    i_dmg = g.history.index("on_damage")
    i_resp = g.history.index("on_trigger")
    i_draw = g.history.index("on_draw", i_dmg)
    assert i_dmg < i_resp < i_draw                          # 响应夹在两段之间

    g2 = run("atomic")
    i_dmg2 = g2.history.index("on_damage")
    i_resp2 = g2.history.index("on_trigger")
    i_draw2 = g2.history.index("on_draw", i_dmg2)
    assert i_dmg2 < i_draw2 < i_resp2                       # 响应推迟到整卡结算完


def _add_wall(db):
    """召唤物墙：0/3，keep_buffs。"""
    db.shikigami[10010199] = F.shiki(10010199, kind="summon", power=0, health=3, keep_buffs=True)
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[F.Step(op="summon", shikigami=10010199)])


def test_summon_enters_combat_zone(db, make_game):
    """召唤物：生成即视为移动进入战斗区（原驻留者退回准备区），进场 1 级。"""
    _add_wall(db)
    g = make_game()
    a = g.state.players[0]
    a.orb = 1
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})                    # 0 号先占战斗区
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid})
    wall = a.shikigami[4]
    assert wall.kind == "summon" and wall.in_play and wall.level == 1
    assert wall.home_slot is None                          # 召唤物无准备区编号
    assert a.combat_index == 4                             # 召唤物进入战斗区
    assert a.shikigami[0].defeated is False                # 原驻留者退回（未离场）
    with pytest.raises(IllegalAction):
        g.apply({"op": "upgrade", "index": 4})             # 召唤物不可升级


def test_combat_summon_stays_and_move_despawns(db, make_game):
    """战斗区召唤物在己方回合开始不退回（仅非召唤物移回）；被移动则直接离场（非气绝）。"""
    _add_wall(db)
    g = make_game()
    a = g.state.players[0]
    a.orb = 1
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid})
    wall = a.shikigami[4]
    assert a.combat_index == 4
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})                            # A 回合开始：召唤物不退回
    assert wall.despawned is False and a.combat_index == 4
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 4}})                    # 移动战斗区召唤物 → 直接离场
    assert wall.despawned is True
    assert a.combat_index is None
    assert wall.revive_countdown == 0                      # 非气绝：不进复活流程


def test_summon_and_keep_buffs(db, make_game):
    """keep_buffs：同名召唤物再召时保留永久增减益。"""
    _add_wall(db)
    db.cards[10010152] = F.card(
        10010152, token=True, steps=[F.Step(op="buff_power", amount=2, perm=True,
                                            target=T(kind="all", pool="friendly_shikigami"))])
    _add_damage_card(db, cid=10010153, amount=3)
    g = make_game()
    a = g.state.players[0]
    a.orb = 3
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid})
    wall = a.shikigami[4]
    g.apply({"op": "play_card", "uid": give(g, 0, 10010152).uid})
    assert wall.perm_power == 2 and wall.eff_power == 2
    # 击杀：离场并留下 legacy
    g.apply({"op": "end_turn"})
    b = g.state.players[1]
    b.orb = 2
    g.apply({"op": "play_card", "uid": give(g, 1, 10010153).uid,
             "target": Ref(player=0, shikigami=4)})
    assert wall.despawned is True and wall.revive_countdown == 0
    assert a.summon_legacy[10010199]["perm_power"] == 2
    # 再召：保留永久增减益
    g.apply({"op": "end_turn"})
    a.orb = 2
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid})
    wall2 = a.shikigami[5]
    assert wall2.perm_power == 2 and wall2.eff_power == 2


def test_zero_damage_aborts_resolution(db, make_game):
    """伤害值 ≤0：终止结算——不扣血、不触发受伤后时机；护甲正常抵扣消耗。"""
    _add_damage_card(db, cid=10010154, amount=0)
    g = make_game()
    b = g.state.players[1]
    g.apply({"op": "play_card", "uid": give(g, 0, 10010154).uid,
             "target": Ref(player=1, shikigami=0)})
    assert b.shikigami[0].health == 4
    assert "on_damage" not in g.history                    # 0 伤害不产生伤害事件
    _add_damage_card(db, cid=10010155, amount=2)
    b.shikigami[0].shield = 3
    g.state.players[0].orb = 1
    g.apply({"op": "play_card", "uid": give(g, 0, 10010155).uid,
             "target": Ref(player=1, shikigami=0)})
    assert b.shikigami[0].shield == 1                      # 护甲正常抵扣 2 点
    assert b.shikigami[0].health == 4
    assert "on_damage" not in g.history                    # 完全吸收：不触发受伤后时机


def test_neutral_card(db, make_game):
    """中立牌：无从属式神、无等级，可正常使用。"""
    db.cards[99990001] = F.card(99990001, shikigami=None, steps=[F.Step(op="draw", count=1)])
    g = make_game()
    a = g.state.players[0]
    c = give(g, 0, 99990001)
    before = len(a.hand)
    g.apply({"op": "play_card", "uid": c.uid})
    assert len(a.hand) == before                           # 用 1 抽 1
    assert a.orb == 0


def test_cost_delta_mod(db, make_game):
    """实例修饰：同名卡可因 mods 而不同（此例降费）。"""
    cid = _add_damage_card(db, cost=2)
    g = make_game()
    a = g.state.players[0]
    a.orb = 1
    c = give(g, 0, cid)
    c.mods["cost_delta"] = -1
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert a.orb == 0


def test_temp_buff_cleared_on_defeat_not_turn_end(db, make_game):
    """临时/永久的区分 = 气绝后复活能否保留：临时修正回合结束不清除，气绝时清除。"""
    db.cards[10010151] = F.card(
        10010151, token=True, steps=[F.Step(op="buff_power", amount=2, perm=True, target=T(kind="self"))])
    db.cards[10010152] = F.card(
        10010152, token=True, steps=[F.Step(op="buff_power", amount=2, target=T(kind="self"))])
    g = make_game()
    a = g.state.players[0]
    a.orb = 2
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid})
    g.apply({"op": "play_card", "uid": give(g, 0, 10010152).uid})
    s = a.shikigami[0]
    assert s.eff_power == 7                                # 3 + 2永 + 2临
    g.apply({"op": "end_turn"})                            # 回合结束：临时修正保留
    assert s.eff_power == 7
    s.health = 0
    g.check_defeated(Ref(player=0, shikigami=0))           # 气绝：临时修正清除
    assert s.temp_power == 0 and s.perm_power == 2
    assert s.eff_power == 5                                # 复活后为 3 + 2永


def test_game_config_override(db, make_game):
    """玩家级 config 可覆盖对局级 GameConfig：此处测试 orb_per_turn 覆盖。"""
    g = make_game()
    a = g.state.players[0]
    a.config["orb_per_turn"] = 3
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})                            # A 第 2 回合开始
    assert a.orb == 3


def test_move_card_to_custom_zone(db, make_game):
    """move_card 支持任意区域：把牌从放逐区 exiled 打回战场。"""
    cid = _add_damage_card(db)
    g = make_game()
    a = g.state.players[0]
    c = give(g, 0, cid)
    g.move_card(a, c, "exiled")
    assert c not in a.hand
    g.apply({"op": "play_card", "uid": c.uid, "play_from": "exiled",
             "target": Ref(player=1, shikigami=0)})
    assert g.state.players[1].shikigami[0].health == 1


def test_form_changes_base_stats(db, make_game):
    """形态牌结附后替换式神基础身材，当前生命重置为新的生命上限；该牌离开手牌/区域。"""
    db.cards[10010151] = F.card(10010151, card_type="form", level=1,
                                form_power=5, form_health=7, token=True)
    g = make_game()
    a = g.state.players[0]
    s = a.shikigami[0]
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid})
    assert s.base_power == 5 and s.base_health == 7
    assert s.health == 7 and s.max_health == 7
    assert s.form is c
    assert c not in a.hand
    assert c not in a.graveyard


def test_form_replaces_old_form(db, make_game):
    """重复结附形态：先消灭旧形态（进墓地），再结附新形态并更新身材。"""
    db.cards[10010151] = F.card(10010151, card_type="form", level=1,
                                form_power=5, form_health=7, token=True)
    db.cards[10010152] = F.card(10010152, card_type="form", level=1,
                                form_power=1, form_health=10, token=True)
    g = make_game()
    a = g.state.players[0]
    s = a.shikigami[0]
    c1 = give(g, 0, 10010151)
    c2 = give(g, 0, 10010152)
    g.apply({"op": "play_card", "uid": c1.uid})
    a.orb = 1
    g.apply({"op": "play_card", "uid": c2.uid})
    assert s.base_power == 1 and s.base_health == 10
    assert s.form is c2
    assert c1 in a.graveyard  # 旧形态被消灭后进入墓地


def test_form_destroyed_on_defeat(db, make_game):
    """式神气绝时，当前结附的形态牌被消灭并恢复基础身材。"""
    db.cards[10010151] = F.card(10010151, card_type="form", level=1,
                                form_power=5, form_health=3, token=True)
    db.cards[10010152] = F.card(10010152, steps=[F.dmg(4)],
                                target=T(kind="choose", pool="friendly_shikigami"), token=True)
    g = make_game()
    a = g.state.players[0]
    s = a.shikigami[0]
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid})
    c2 = give(g, 0, 10010152)
    a.orb = 1
    g.apply({"op": "play_card", "uid": c2.uid, "target": Ref(player=0, shikigami=0)})
    assert s.defeated is True
    assert c in a.graveyard
    assert s.base_power == 3 and s.base_health == 4  # 恢复为式神原本身材


def test_form_level_requirement(db, make_game):
    """形态牌同样受所属式神等级限制。"""
    db.cards[10010151] = F.card(10010151, card_type="form", level=2,
                                form_power=5, form_health=7, token=True)
    g = make_game()
    a = g.state.players[0]
    c = give(g, 0, 10010151)
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": c.uid})
    a.shikigami[0].level = 2
    g.apply({"op": "play_card", "uid": c.uid})
    assert a.shikigami[0].base_power == 5


def test_zero_cost_card_playable_at_zero_orb(db, make_game):
    """不消耗鬼火：cost=0 的卡牌可在 0 鬼火时使用。"""
    db.cards[10010151] = F.card(10010151, cost=0, token=True)
    g = make_game()
    a = g.state.players[0]
    a.orb = 0
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid})
    assert a.orb == 0
    assert c in a.graveyard


def test_play_events_and_zones(db, make_game):
    """各类型卡牌打出后均发出 on_card_played，并进入正确区域/状态。"""
    db.cards[10010151] = F.card(10010151, token=True)                                    # 法术
    db.cards[10010152] = F.card(10010152, card_type="combat", steps=[], token=True)      # 战斗牌
    db.cards[10010153] = F.card(10010153, card_type="form", form_power=3, form_health=5,
                                token=True)                                              # 形态
    db.cards[10010154] = F.card(10010154, level=3, subtype="awaken", steps=[], token=True)  # 觉醒
    g = make_game()
    a = g.state.players[0]
    s = a.shikigami[0]
    s.level = 3                            # 满足觉醒牌等级
    a.orb = 10

    spell = give(g, 0, 10010151)
    combat = give(g, 0, 10010152)
    form = give(g, 0, 10010153)
    awaken = give(g, 0, 10010154)

    for card, in_graveyard, attached_form in (
        (spell, True, None),
        (combat, True, None),
        (form, False, form),
        (awaken, True, form),   # 觉醒是法术，不会替换已结附的形态
    ):
        before = len(g.history)
        g.apply({"op": "play_card", "uid": card.uid})
        assert "on_card_played" in g.history[before:]
        assert (card in a.graveyard) is in_graveyard
        assert s.form is attached_form


# ==========================================================================
# 凤凰火/山童底层：orb_ge 条件 / on_card_played 使用位置 payload /
# enemy_bench 池 / perm_power 快照 / power_override 力量覆写
# ==========================================================================

def test_orb_ge_condition(db, make_game):
    """{orb_ge: n}：控制者当前鬼火 ≥ n 才执行该步（step 级条件）。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="damage", amount=3, target=T(kind="all", pool="enemy_player"),
               condition={"orb_ge": 2})])
    g = make_game()                       # A 先手第 1 回合：鬼火 1，付费后 0
    g.state.players[1].shield = 0
    F.play(g, 0, cid)
    assert g.state.players[1].health == 30  # 条件不满足：空操作
    g = make_game()
    g.state.players[0].orb = 5
    g.state.players[1].shield = 0
    F.play(g, 0, cid)                     # 付费后 4 ≥ 2
    assert g.state.players[1].health == 27


def _played_payloads(g):
    """on_card_played 事件 payload 采集（spy 包装 emit）。"""
    seen = []
    orig = g.emit

    def spy(name, **kw):
        if name == "on_card_played":
            seen.append(kw)
        return orig(name, **kw)
    g.emit = spy
    return seen


def test_on_card_played_play_from_payload(db, make_game):
    """on_card_played 携带 play_from/play_method/triggered（主动使用：hand/active）。"""
    cid = _add_damage_card(db, 10010156)
    g = make_game()
    seen = _played_payloads(g)
    F.play(g, 0, cid, target=Ref(player=1, shikigami=0))
    assert seen[-1]["play_from"] == "hand"
    assert seen[-1]["play_method"] is None
    assert seen[-1]["triggered"] == "active"


def test_on_card_played_play_method_payload(db, make_game):
    """使用方式 id 随 on_card_played payload 发出。"""
    cid = 10010157
    db.cards[cid] = F.card(cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True,
                           methods=[F.method("burst", param=2)])
    g = make_game()
    seen = _played_payloads(g)
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "burst",
             "target": Ref(player=1, shikigami=0)})
    assert seen[-1]["play_method"] == "burst"
    assert seen[-1]["triggered"] == "active"


def test_on_card_played_response_payload(db, make_game):
    """响应使用：triggered=response（play_from 仍为 hand）。"""
    cid = 10010158
    db.cards[cid] = F.card(cid, keywords=["trigger"], token=True, cost=0,
                           when="on_before_assault",
                           steps=[F.dmg(1, T(kind="all", pool="enemy_player"))])
    g = make_game()
    seen = _played_payloads(g)
    give(g, 1, cid)
    g.state.players[0].orb = 1
    g.apply({"op": "assault", "index": 0})
    assert seen[-1]["triggered"] == "response"
    assert seen[-1]["play_from"] == "hand"


def test_enemy_bench_pool(db, make_game):
    """enemy_bench：敌方在场且不在战斗区的式神（战斗区驻留者被排除）。"""
    g = make_game()
    for s in g.state.players[1].shikigami:
        s.level = 1
    refs = targets_mod.pool_refs(g, "enemy_bench", 0)
    assert [r.shikigami for r in refs] == [0, 1, 2, 3]   # 战斗区为空：全部在场式神
    move(g, 1, 0)
    refs = targets_mod.pool_refs(g, "enemy_bench", 0)
    assert [r.shikigami for r in refs] == [1, 2, 3]      # 战斗区驻留者除外


def test_perm_power_snapshot(db, make_game):
    """{perm_power: "self"}：按来源式神当前永久力量修正快照增伤（崩山两步各自加）。"""
    BUFF = 10010159
    db.cards[BUFF] = F.card(BUFF, token=True, steps=[
        F.Step(op="buff_power", amount=2, perm=True, target=T(kind="self"))])
    db.cards[10010160] = F.card(10010160, token=True, steps=[
        F.Step(op="damage", amount={"perm_power": "self", "base": 4},
               target=T(kind="all", pool="enemy_player")),
        F.Step(op="damage", amount={"perm_power": "self", "base": 1},
               target=T(kind="all", pool="enemy_player"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    F.play(g, 0, BUFF)                    # 永久力量 +2
    F.play(g, 0, 10010160)
    assert pb.health == 21                # (4+2) + (1+2) = 9
    g = make_game()                       # 负面对照：无永久力量修正仅基础值
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    F.play(g, 0, 10010160)
    assert pb.health == 25                # 4 + 1 = 5


def test_power_override_zeroes_attack(db, make_game):
    """power_override：力量视为 0（覆盖基础+永久+临时+战力全部）；攻击造成 0 伤害。"""
    db.cards[10010161] = F.card(10010161, token=True, steps=[
        F.Step(op="power_override", target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    s = pa.shikigami[0]
    s.perm_power = 3
    F.play(g, 0, 10010161)
    assert s.eff_power == 0               # 永久 +3 也被覆写
    move(g, 1, 0)
    pa.orb = 1
    g.apply({"op": "assault", "index": 0})
    assert pb.shikigami[0].health == 4    # 0 力量攻击无伤害
    assert s.health == 1                  # 反击照常（4-3）


def test_power_override_off_and_defeat_clear(db, make_game):
    """power_override(on=False) 解除；气绝时自动清除。"""
    db.cards[10010161] = F.card(10010161, token=True, steps=[
        F.Step(op="power_override", target=T(kind="self"))])
    db.cards[10010162] = F.card(10010162, token=True, steps=[
        F.Step(op="power_override", on=False, target=T(kind="self"))])
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    s = pa.shikigami[0]
    F.play(g, 0, 10010161)
    assert s.eff_power == 0
    F.play(g, 0, 10010162)
    assert s.eff_power == 3               # on=False 解除覆写
    F.play(g, 0, 10010161)
    s.health = 0
    g.check_defeated(Ref(player=0, shikigami=0), source=None, reason="伤害")
    assert s.defeated
    assert not s.ext.get("power_zero")    # 气绝时清除


def test_power_override_cleared_on_form_destroy(db, make_game):
    """形态离场时力量覆写自动清除（基础身材恢复）。"""
    db.cards[10010161] = F.card(10010161, token=True, steps=[
        F.Step(op="power_override", target=T(kind="self"))])
    db.cards[10010163] = F.card(10010163, card_type="form", form_power=5,
                                form_health=6, token=True)
    db.cards[10010164] = F.card(10010164, token=True, steps=[
        F.Step(op="destroy_form", target=T(kind="self"))])
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    s = pa.shikigami[0]
    F.play(g, 0, 10010163)                # 结附形态：基础力量 5
    assert s.eff_power == 5
    F.play(g, 0, 10010161)
    assert s.eff_power == 0
    F.play(g, 0, 10010164)                # 消灭形态
    assert s.form is None
    assert s.eff_power == 3               # 覆写随形态离场清除


# ==========================================================================
# 力量历史峰值 / 牌手级持久监听
# ==========================================================================

def _power_cards(db):
    """合成力量增益卡：临时 +2 / 攻击后到期强化 +3 / 永久 +1。"""
    c1, c2, c3 = 10010171, 10010172, 10010173
    db.cards[c1] = F.card(c1, shikigami=100101, token=True,
                          steps=[F.Step(op="buff_power", amount=2, target=F.T(kind="self"))])
    db.cards[c2] = F.card(c2, shikigami=100101, token=True,
                          steps=[F.Step(op="attack_buff", power=3, target=F.T(kind="self"))])
    db.cards[c3] = F.card(c3, shikigami=100101, token=True,
                          steps=[F.Step(op="buff_power", amount=1, perm=True,
                                        target=F.T(kind="self"))])
    return c1, c2, c3


def test_max_power_peak_record(db, make_game):
    """力量历史峰值 ext["max_power"]：临时/永久力量增减与攻击强化施加处更新（只增），
    跨气绝保留不重置。"""
    buff_cid, atk_cid, perm_cid = _power_cards(db)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    a = pa.shikigami[0]
    assert a.ext["max_power"] == 3  # 初始 = 基础力量
    play(g, 0, buff_cid)  # 临时 +2
    assert a.ext["max_power"] == 5
    play(g, 0, atk_cid)  # 攻击后到期强化 +3
    assert a.ext["max_power"] == 8
    play(g, 0, perm_cid)  # 永久 +1
    assert a.ext["max_power"] == 9
    a.health = 0
    g.check_defeated(Ref(player=0, shikigami=0))  # 气绝清除临时修正
    assert a.eff_power == 4
    assert a.ext["max_power"] == 9  # 峰值跨气绝保留
    a.revive_countdown = 1
    pass_turns(g, 2)
    assert not a.defeated
    assert a.ext["max_power"] == 9  # 复活后仍保留


def _aura_cards(db):
    """合成牌手级监听登记卡（player_aura：用牌后 ext 计数 +1，once_key 防叠加）。"""
    cid = 10010174
    db.cards[cid] = F.card(cid, shikigami=100101, token=True, steps=[F.Step(
        op="player_aura", when="on_card_played", once_key="test_aura",
        steps=[{"op": "bump_ext", "key": "aura_proc",
                "target": {"kind": "all", "pool": "self_player"}}])])
    return cid, 10010201  # 空白卡（1 级，属 100102）


def test_player_aura_game_scope(db, make_game):
    """牌手级"本局游戏"持久监听（player_aura）：事件触发即结算、不限次数、
    once_key 防重复登记、跨气绝保留、回合开始不清除。"""
    aura_cid, blank_cid = _aura_cards(db)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    pa.shikigami[1].level = 1
    play(g, 0, aura_cid)  # 登记；本次使用的 on_card_played 也触发
    assert pa.ext.get("aura_proc") == 1
    play(g, 0, aura_cid)  # once_key：不重复登记，仍只触发一次
    assert pa.ext.get("aura_proc") == 2
    play(g, 0, blank_cid)
    assert pa.ext.get("aura_proc") == 3
    a0 = pa.shikigami[0]
    a0.health = 0
    g.check_defeated(Ref(player=0, shikigami=0))  # 来源式神气绝
    play(g, 0, blank_cid)  # 跨气绝保留：牌手级监听不受影响
    assert pa.ext.get("aura_proc") == 4
    pass_turns(g, 2)
    pa.orb = 9
    play(g, 0, blank_cid)  # 跨回合不清除
    assert pa.ext.get("aura_proc") == 5


# ==========================================================================
# 真实数据：本回合通道（武士之笛/鼓舞）/ 峰值差值（断臂）/ 豪焰牌手光环
# 队伍派系均 ≤2；0 号位开局自动 1 级（茨木对局开始批次基础能力已 perm+1）。
# ==========================================================================

ZR_TEAM = [100001, 100103, 100002, 100105]   # 纸人武士主力
CM_TEAM2 = [100103, 100001, 100002, 100105]  # 茨木童子主力
TX_TEAM = [100002, 100103, 100001, 100105]   # 天邪鬼军团主力


def test_turn_scoped_buff_expires(real_game):
    """武士之笛：己方全体本回合 +1 力量（scope=turn），己方回合开始时清除；
    历史峰值 max_power 只增不回落。"""
    g = real_game(ZR_TEAM)
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]                        # 纸人武士 3/4
    play(g, 0, 10000102)                       # 武士之笛（瞬发，全队本回合 +1）
    assert s.temp_power == 1
    assert s.ext["max_power"] == 4
    pass_turns(g, 2)                           # 己方下回合开始：回合通道清除
    assert s.temp_power == 0
    assert s.ext["max_power"] == 4             # 峰值记账保留


def test_inspire_aura_boosts_effect_damage_this_turn(real_game):
    """鼓舞：牌手级监听（scope=turn 可叠加）使天邪鬼军团本回合非战斗伤害 +1。"""
    g = real_game(TX_TEAM)
    pa, pb = F.battle_setup(g)
    play(g, 0, 10000202)                       # 鼓舞（瞬发）
    assert len(pa.auras) == 1
    play(g, 0, 10000201)                       # 燃烧：敌方全体 1 + 1 = 2 伤
    assert [s.health for s in pb.shikigami] == [3, 2, 2, 2]
    pass_turns(g, 2)
    assert pa.auras == []                      # 回合开始清除
    play(g, 0, 10000201)                       # 无鼓舞：回到 1 伤
    assert [s.health for s in pb.shikigami] == [2, 1, 1, 1]


def test_max_power_gap_restores_peak(real_game):
    """断臂：力量变为本局游戏最大值 = 补峰值差值（max_power - eff_power）。"""
    g = real_game(CM_TEAM2)
    pa, pb = F.battle_setup(g, {0: 2, 1: 1})   # 纸人 1 级（武士之笛使用条件）
    s = pa.shikigami[0]                        # 茨木 eff 4（perm 1）
    play(g, 0, 10000102)                       # 武士之笛 +1（turn 通道）
    play(g, 0, 10010302)                       # 豪拳 +3 → temp 4, eff 8, max 8
    assert s.eff_power == 8 and s.ext["max_power"] == 8
    pass_turns(g, 2)                           # perm+1（=2），turn 通道清除 → temp 3
    assert s.eff_power == 8                    # 3 + 2 + 3，与峰值持平
    s.temp_power = 0                           # 模拟临时增益流失（气绝清除等价路径）
    play(g, 0, 10010306)                       # 断臂：补差值 8 - 5 = 3
    assert s.temp_power == 3
    assert s.eff_power == 8
    assert s.ext["max_power"] == 8             # 峰值不突破


def test_on_kill_random_aura_fixed_once_key(real_game):
    """地狱豪焰：本次战斗击杀式神后登记固定项（haoyan_base，不可叠加）与
    一项随机豪焰监听；之后茨木使用战斗牌时固定项 +1 力量/+1 护甲。"""
    g = real_game(CM_TEAM2)
    pa, pb = F.battle_setup(g, {0: 2})         # 茨木 2 级（豪拳使用条件）
    play(g, 0, 10010302)                       # 豪拳 +3 → eff 7
    move(g, 1, 3)                              # B 凤凰火（4 命）驻守战斗区
    play(g, 0, 10010351)                       # 地狱豪焰：战斗击杀 → 触发
    assert pb.shikigami[3].defeated
    keys = {a.get("once_key") for a in pa.auras}
    assert "haoyan_base" in keys
    assert len(keys) == 2                      # 固定项 + 一项随机豪焰
    assert keys & {"haoyan_cd", "haoyan_pow", "haoyan_heal", "haoyan_burn"}
    pass_turns(g, 2)
    s = pa.shikigami[0]
    temp_before = s.temp_power
    play(g, 0, 10010301)                       # 鬼之手（战斗牌）→ 固定项触发
    assert s.temp_power == temp_before + 1     # +1 力量
    assert s.shield >= 1                       # +1 护甲（战斗结算后保留）


def test_bond_self_damage_triggers_ally_ability(gdb):
    """地狱豪焰[羁绊]：酒吞童子在场时对自己造成 1 伤（触发其受伤能力 +1 力量），
    茨木获得 2 护甲。"""
    from core.model import GameConfig
    from core.setup import new_game
    team = [100103, 100109, 100001, 100002]
    deck = F.deck_of(100103, 100001, 100002, 100105)  # 酒吞无卡：借凤凰火卡位凑组
    g = new_game(gdb, ("A", list(team), list(deck)), ("B", list(team), list(deck)),
                 seed=1, first=0, shuffle_team=False, mulligan=False, check_deck=False,
                 config=GameConfig(auto_skip_upgrade=True))
    pa, pb = F.battle_setup(g)
    pa.shikigami[1].level = 1                  # 酒吞在场（未气绝）
    play(g, 0, 10010351)                       # 地狱豪焰（token 直接发牌打出）
    jt = pa.shikigami[1]
    assert jt.health == 4                      # 5 - 1 自伤
    assert jt.temp_power == 1                  # 酒吞能力：受伤 +1 力量
    assert pa.shikigami[0].shield == 2         # 茨木 +2 护甲


# ---- 真实数据：酒吞童子（百闻牌原型）----

JT_TEAM = [100109, 100103, 100001, 100002]  # 酒吞童子、茨木童子、纸人武士、天邪鬼军团（红莲×3+青岚）


def _set_health(g, player, index, value):
    g.apply({"op": "debug_set_stat",
             "args": {"target": {"player": player, "shikigami": index},
                      "key": "health", "value": value}})


def test_min_health_clamp_turn_scope(real_game):
    """狂啸（10010908）主动使用：本回合酒吞童子生命不会降到 1 以下——超额伤害
    钳制为 0（不触发受伤能力）；半回合作用域，回合开始清除。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g, {0: 3})
    jt = pa.shikigami[0]
    play(g, 0, 10010908)                       # 狂啸：min_health_turn 置位
    _set_health(g, 0, 0, 2)
    play(g, 0, 10010901)                       # 醉里乾坤：-1 → 1（触发能力 +1）
    assert jt.health == 1 and jt.temp_power == 1
    play(g, 0, 10010901)                       # 再醉里乾坤：钳制为 0 伤害
    assert jt.health == 1 and jt.temp_power == 1   # 0 伤不再触发受伤能力
    pass_turns(g, 1)
    assert not jt.ext.get("min_health_turn")   # 回合开始清除（半回合作用域）


def test_min_health_clamp_response(real_game):
    """狂啸[响应]：酒吞童子将受到伤害时自动使用——4 伤钳制到 2（停 1），
    本回合后续伤害继续被钳制为 0。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g)
    pb.shikigami[0].level = 3                  # 响应等级要求（狂啸 3 级）
    give(g, 1, 10010908)
    pb.orb = 1                                 # 响应需支付 1 鬼火
    _set_health(g, 1, 0, 3)
    jb = pb.shikigami[0]
    pa.shikigami[3].level = 2                  # 鸢击 2 级
    play(g, 0, 10000203, target=Ref(player=1, shikigami=0))  # 鸢击 4 → 钳制 2
    assert jb.health == 1
    assert any(c.id == 10010908 for c in pb.graveyard)
    play(g, 0, 10000203, target=Ref(player=1, shikigami=0))  # 第二次：钳制 0
    assert jb.health == 1


def test_fury_first_self_damage_aura(real_game):
    """无尽愤怒（10010904）：本回合酒吞受过己方伤害后此牌 +2 力量
    （卡牌光环数值通道）；对照组无自伤则只有牌面 +2 战力。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g, {0: 2})
    jt = pa.shikigami[0]
    play(g, 0, 10010901)                       # 醉里乾坤：自伤 1（能力 +1）
    play(g, 0, 10010904)                       # 无尽愤怒：2+1 攻 + 战力 2+2=4 → 7
    assert pb.health == 30 - 7
    assert jt.shield == 0                      # 光环只加力量，无护甲
    # 对照：无自伤 → 无光环
    g2 = real_game(JT_TEAM)
    pa2, pb2 = F.battle_setup(g2, {0: 2})
    play(g2, 0, 10010904)                      # 2 攻 + 战力 2 → 4
    assert pb2.health == 30 - 4
    assert pa2.shikigami[0].shield == 0


def test_awaken_equal_power_per_point(real_game):
    """觉醒·酒吞童子（10010906）：+1/+3；受伤改为每受 1 点伤害获得 1 力量
    （鬼王进场自伤 4 → +4）。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g, {0: 3})
    jt = pa.shikigami[0]
    play(g, 0, 10010906)                       # 觉醒：+1/+3 → 3/8
    assert (jt.eff_power, jt.max_health) == (3, 8)
    play(g, 0, 10010903)                       # 鬼王（形态 5/10）：进场回满新上限后自伤 4
    assert jt.max_health == 13                 # 形态 10 + 觉醒永久 +3
    assert jt.health == 9                      # 13 - 4
    assert jt.temp_power == 4                  # 觉醒能力：获得等量力量（非 +1）


def test_ext_damage_taken_turn_aoe(real_game):
    """百鬼夜行（10010907）：X = 本回合酒吞所受伤害之和，对双方所有其他式神
    各造成 X（friendly_others + enemy_shikigami 两段，酒吞自身除外）。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g, {0: 3, 1: 1, 2: 1, 3: 1})  # A 全员在场才进 friendly_others 池
    jt = pa.shikigami[0]
    play(g, 0, 10010901)                       # 醉里乾坤：自伤 1 → X=1
    play(g, 0, 10010901)                       # 再自伤 1 → X=2
    play(g, 0, 10010907)                       # 百鬼夜行：全体其他 -2
    assert jt.health == 3                      # 5 - 1 - 1，百鬼不打自己
    assert [s.health for s in pa.shikigami[1:]] == [2, 2, 3]   # 茨木4/纸人4/天邪鬼5
    assert [s.health for s in pb.shikigami] == [3, 2, 2, 3]    # 全员 -2


def test_bond_generate_exact_level(real_game):
    """醉酒当歌（10010951，协战主牌）：自伤 3 + 等量护甲 3；[羁绊]获得一张茨木
    当前等级的战斗牌（茨木 1 级 → 1 级战斗牌鬼之手/黑焰之手之一）。"""
    g = real_game(JT_TEAM)
    pa, pb = F.battle_setup(g, {0: 1, 1: 1})
    jt = pa.shikigami[0]
    play(g, 0, 10010951)                       # 醉酒当歌（战斗牌，自伤 3 → 能力 +1）
    assert jt.health == 2
    assert jt.shield == 3
    assert jt.temp_power == 1                  # 基础能力：受伤 +1
    assert any(c.id in (10010301, 10010304) for c in pa.hand)   # 鬼之手/黑焰之手


# ---------- 弹回 / 本回合力量覆写 / 目标池过滤 ----------

def test_rebound_returns_to_hand(db, make_game):
    """弹回（蛇行击型）：使用后回手而非入墓；再次打出时持久修饰快照按实例去重
    （_materialize 只补差值，不重复合并）。"""
    cid = 10010156
    db.cards[cid] = F.card(
        cid, keywords=["rebound"], steps=[F.dmg(1)], target=CHOOSE_ENEMY, token=True,
        triggers=[F.EffectBlock(
            when="on_shikigami_defeated",
            condition={"victim_kind": "shikigami", "source_side": "friendly"},
            steps=[F.Step(op="add_mod", to="persistent", key="enhance", amount=2)],
        )])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99,
                        Ref(player=0, shikigami=0), kind="combat")
    g._drain_queue()
    assert pa.card_mods[cid]["enhance"] == 2     # 本局击杀计数已入持久 store
    move(g, 1, 1)
    pb.shikigami[1].level = 1                    # 0 级不在场，须先入场才可被指定
    c = give(g, 0, cid)
    tgt = Ref(player=1, shikigami=1)
    g.apply({"op": "play_card", "uid": c.uid, "target": tgt})
    assert c in pa.hand                          # 回手而非入墓
    assert c.mods["enhance"] == 2                # 首次打出快照
    g.apply({"op": "play_card", "uid": c.uid, "target": tgt})
    assert c in pa.hand
    assert c.mods["enhance"] == 2                # 再次打出不重复合并


def test_conditional_bounce_and_fragile_bonus(db, make_game):
    """条件回手 + 条件加伤（蛇行击 2019 型：bounce_self + chosen_has_fragile Step 级
    条件）——目标有破甲：伤害+1 且此牌移回手牌（不入墓）；无破甲：1 伤进墓地。
    破甲受伤即消耗，读破甲的条件步须排在伤害步之前；瞬发免费照常。"""
    cid = 10010166
    db.cards[cid] = F.card(
        cid, keywords=["fast"], token=True,
        target=T(kind="choose", pool="any_shikigami"),
        steps=[F.Step(op="bounce_self", condition={"chosen_has_fragile": True}),
               F.Step(op="damage", amount=1, condition={"chosen_has_fragile": True}),
               F.dmg(1)])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    # 无破甲：1 伤、进墓地
    play(g, 0, cid, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 3           # 4-1
    assert pa.orb == 9                           # 瞬发免费
    assert not any(c.id == cid for c in pa.hand)
    assert sum(c.id == cid for c in pa.graveyard) == 1
    # 有破甲 2：回手 + 伤害 (1+2 破甲加成)+1 = 4，破甲消耗
    pb.shikigami[1].shield = -2
    play(g, 0, cid, target=Ref(player=1, shikigami=1))
    assert pb.shikigami[1].health == 2           # 6 - (1+2) - 1
    assert pb.shikigami[1].shield == 0           # 破甲受伤即消耗
    assert pa.orb == 8                           # 第二张非瞬发免费：照付 1 火
    assert sum(c.id == cid for c in pa.hand) == 1        # 条件回手：回手而非入墓
    assert sum(c.id == cid for c in pa.graveyard) == 1   # 墓地仍只有第一张


def test_power_override_turn_scope(db, make_game):
    """闪烁型"本回合力量变为 0"：scope=turn 的力量覆写在任一回合开始时解除
    （半回合作用域，min_health_turn 先例）。"""
    cid = 10010157
    db.cards[cid] = F.card(
        cid, steps=[F.Step(op="power_override", scope="turn",
                           target=T(kind="all", pool="enemy_combat"))], token=True)
    g = make_game()
    move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    play(g, 0, cid)
    assert b.eff_power == 0
    assert b.ext.get("power_zero_turn")
    pass_turns(g, 1)                             # → B 回合开始：覆写到期解除
    assert b.eff_power == 3
    assert not b.ext.get("power_zero")


def test_choose_pool_power_le_filter(db, make_game):
    """勾诀型目标过滤：choose 池 power_le —— 力量超标者不可被指定（合法性校验拒绝），
    达标者可指定并消灭。"""
    cid = 10010158
    db.cards[cid] = F.card(
        cid, target=T(kind="choose", pool="enemy_shikigami", power_le=2),
        steps=[F.Step(op="destroy")], token=True)
    g = make_game()
    pb = g.state.players[1]
    pb.shikigami[0].level = 1                    # 3 力量（超标）
    pb.shikigami[2].level = 1                    # 100103 2 力量（达标）
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": give(g, 0, cid).uid,
                 "target": Ref(player=1, shikigami=0)})
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid,
             "target": Ref(player=1, shikigami=2)})
    assert pb.shikigami[2].defeated


def test_all_pool_has_fragile_filter(db, make_game):
    """焚身之火型全体伤害：all 池 has_fragile 过滤 —— 仅命中持有破甲的角色
    （式神与牌手均按 shield<0 判定；破甲受伤即消耗）。"""
    cid = 10010159
    db.cards[cid] = F.card(
        cid, steps=[F.Step(op="damage", amount=3,
                           target=T(kind="all", pool="enemy_character",
                                    has_fragile=True))], token=True)
    g = make_game()
    pb = g.state.players[1]
    pb.shield = -1
    for s in pb.shikigami:
        s.level = 1
    pb.shikigami[1].shield = -2                  # 100102 6 血持 2 破甲
    play(g, 0, cid)
    assert pb.shikigami[1].health == 1           # 6 - (3+2)
    assert pb.health == 26                       # 30 - (3+1)
    assert pb.shikigami[0].health == 4           # 无破甲者不受伤害
    assert pb.shikigami[1].shield == 0           # 破甲受伤即消耗


# ----------no_attack / 额外鬼火 / 气绝可用战斗牌 / 计数条件回退 / ids 光环 ----------

SID = 100101


def test_summon_no_attack(db, make_game):
    """不能发动攻击（no_attack 召唤物）：出击指令拒绝；效果发起的攻击为空操作。"""
    tom = 10012199
    db.shikigami[tom] = F.shiki(tom, kind="summon", name="番茄", power=3, health=3,
                                no_attack=True)
    cid = 10010171
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="summon", shikigami=tom)])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    play(g, 0, cid)
    idx = len(pa.shikigami) - 1
    assert pa.shikigami[idx].id == tom and pa.combat_index == idx
    with pytest.raises(IllegalAction, match="不能发动攻击"):
        g.apply({"op": "assault", "index": idx})
    launcher = 10010172
    db.cards[launcher] = F.card(launcher, token=True, steps=[
        F.Step(op="launch_attack", shikigami=tom)])
    pb.shikigami[0].health = 20
    play(g, 0, launcher)
    assert pb.shikigami[0].health == 20 and pb.health == 30  # 效果发起同样不攻击


def test_extra_orb_cost(db, make_game):
    """跳跳妹妹型额外鬼火（extra_orb_cost 先天伪关键字）：出击 2 火、战斗牌 +1 火；
    [迅捷]出击/[瞬发]战斗牌全免（含额外的 1 火）。"""
    db.shikigami[SID] = F.shiki(SID, keywords=["extra_orb_cost"])
    combat = 10010173
    db.cards[combat] = F.card(combat, card_type="combat", token=True)
    fast_combat = 10010174
    db.cards[fast_combat] = F.card(fast_combat, card_type="combat",
                                   keywords=["fast"], token=True)
    # 出击需 2 火：先手首回合 1 火时拒绝
    g = make_game()
    pa = g.state.players[0]
    assert pa.orb == 1
    with pytest.raises(IllegalAction, match="2 点鬼火"):
        g.apply({"op": "assault", "index": 0})
    # 战斗牌 +1 火（1 费牌实收 2 火）
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 2
    play(g, 0, combat)
    assert pa.orb == 0
    # 瞬发战斗牌全免
    g = make_game()
    pa = g.state.players[0]
    play(g, 0, fast_combat)
    assert pa.orb == 1
    # 迅捷出击全免（消耗一次性迅捷）
    g = make_game()
    pa = g.state.players[0]
    pa.shikigami[0].one_shot_keywords.append("haste")
    g.apply({"op": "assault", "index": 0})
    assert pa.orb == 1 and "haste" not in pa.shikigami[0].one_shot_keywords


def test_defeated_playable_combat_revives_then_fights(db, make_game):
    """不玩了啦型：气绝可用的战斗牌——先结算卡面效果；结算完已复活则补齐战力/护甲
    并正常发起战斗，仍未复活则牌入墓地、不发起战斗（不崩守卫）。"""
    cid = 10010175
    db.cards[cid] = F.card(cid, card_type="combat", playable_when_defeated=True,
                           token=True, steps=[
        F.Step(op="buff_power", amount=2, target=T(kind="self")),
        F.Step(op="revive", target=T(kind="self"))])
    bare = 10010176
    db.cards[bare] = F.card(bare, card_type="combat", playable_when_defeated=True,
                            token=True)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    b.health = 20
    b.base_power = 0                               # 免反击干扰
    move(g, 1, 0)
    s = pa.shikigami[0]
    s.defeated = True
    s.health = 0
    s.revive_countdown = 3
    play(g, 0, cid)
    assert not s.defeated and s.in_play            # 卡面复活效果先生效
    assert b.health == 15                          # 补齐战力 3+2=5 后发起战斗
    # 无复活效果：不发起战斗、不崩
    s.defeated = True
    s.health = 0
    play(g, 0, bare)
    assert s.defeated and b.health == 15
    assert any(c.id == bare for c in pa.graveyard)


def test_generic_count_ge_falls_back_to_ext(db, make_game):
    """通用 {字段_ge} 回退：事件无该数值字段时回退读控制者 PlayerState.ext
    （狂风刃卷 yaohu_damage_count_ge 型计数条件）。"""
    cid = 10010177
    db.cards[cid] = F.card(cid, token=True, target=CHOOSE_ENEMY, steps=[
        F.Step(op="damage", amount=2, target=CHOOSE_ENEMY,
               condition={"yaohu_damage_count_ge": 2})])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    tgt = Ref(player=1, shikigami=0)
    play(g, 0, cid, target=tgt)
    assert b.health == 4                           # ext 无计数：步骤跳过
    pa.ext["yaohu_damage_count"] = 2
    play(g, 0, cid, target=tgt)
    assert b.health == 2                           # 计数达标：生效


def test_stat_aura_ids_power(db, make_game):
    """坐下/出击·番茄型 ids_power 光环：按数据 id 给在场实体 +力量（本局游戏、可叠加、
    跨召唤保留，召唤物与变形体同享）。"""
    tom, tom2 = 10013199, 10013198
    db.shikigami[tom] = F.shiki(tom, kind="summon", name="番茄", power=3, health=3)
    db.shikigami[tom2] = F.shiki(tom2, kind="transform", name="番茄·觉醒",
                                 power=4, health=4)
    summon_card = 10010178
    db.cards[summon_card] = F.card(summon_card, token=True, steps=[
        F.Step(op="summon", shikigami=tom)])
    aura = 10010179
    db.cards[aura] = F.card(aura, token=True, steps=[
        F.Step(op="stat_aura", kind="ids_power", ids=[tom, tom2], power=1,
               scope="game", target=T(kind="self"))])
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    play(g, 0, summon_card)
    s = pa.shikigami[-1]
    assert s.eff_power == 3
    play(g, 0, aura)
    assert s.eff_power == 4
    play(g, 0, aura)
    assert s.eff_power == 5                        # 可叠加
    s.health = 0                                   # 离场后再召仍生效
    g.check_defeated(Ref(player=0, shikigami=len(pa.shikigami) - 1))
    assert s.despawned
    play(g, 0, summon_card)
    assert pa.shikigami[-1].eff_power == 5
    # 变形体（id ∈ ids）同享
    trans = 10010180
    db.cards[trans] = F.card(trans, token=True, steps=[
        F.Step(op="transform", into=tom2, permanent=True, target=T(kind="self"))])
    play(g, 0, trans)
    assert pa.shikigami[0].id == tom2
    assert pa.shikigami[0].eff_power == 6          # 4 基础 + 2 光环


def test_summon_orb_cost(db, make_game):
    """坐下 20200227 型 summon orb_cost：效果内嵌费用——剩余鬼火不足则召唤失败
    （其余步骤照常），足够则先付 1 火再召唤。"""
    tom = 10013199
    db.shikigami[tom] = F.shiki(tom, kind="summon", name="番茄", power=3, health=4)
    cid = 10010183
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="summon", shikigami=tom, orb_cost=1)])
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 1
    n = len(pa.shikigami)
    play(g, 0, cid)                                # 付牌费后 0 火：召唤失败
    assert len(pa.shikigami) == n
    pa.orb = 2
    play(g, 0, cid)                                # 付牌费后 1 火：先付再召
    assert pa.orb == 0
    assert pa.shikigami[-1].id == tom
    assert pa.shikigami[-1].in_play


def test_player_aura_random_other_enemy_character(db, make_game):
    """出击·番茄型牌手光环：番茄造成战斗伤害时对另一个随机敌方角色造成伤害
    （{source_shikigami: [ids]} 列表匹配 + random_damage exclude_victim；光环可叠加）。"""
    tom = 10013199
    db.shikigami[tom] = F.shiki(tom, kind="summon", name="番茄", power=3, health=3)
    summon_card = 10010181
    db.cards[summon_card] = F.card(summon_card, token=True, steps=[
        F.Step(op="summon", shikigami=tom)])
    aura = 10010182
    db.cards[aura] = F.card(aura, token=True, steps=[
        F.Step(op="player_aura", when="on_damage",
               condition={"kind": "combat", "source_shikigami": [tom]},
               steps=[{"op": "random_damage", "amount": 2, "pool": "enemy_character",
                       "exclude_victim": True}],
               target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0                                # 清掉后手补偿护甲，便于观察数值
    pb.shikigami[0].base_power = 0                 # 免反击干扰
    move(g, 1, 0)
    play(g, 0, summon_card)
    play(g, 0, aura)
    b = pb.shikigami[0]
    b.health = 20
    idx = len(pa.shikigami) - 1
    g.apply({"op": "assault", "index": idx})
    assert b.health == 17                          # 番茄 3 战斗伤害
    assert pb.health == 28                         # 另一个敌方角色（牌手）受 2
    # 光环叠加：第二份后额外各打 2（共 4）
    play(g, 0, aura)
    pa.assaults_left = 1
    g.apply({"op": "assault", "index": idx})
    assert b.health == 14
    assert pb.health == 24


def test_launch_attack_at_chosen(db, make_game):
    """冰封[羁绊]型：效果发起有目标的攻击（at="chosen"，战斗目标取卡牌选择目标，
    反击照常）。"""
    cid = 10010183
    db.cards[cid] = F.card(cid, token=True, target=CHOOSE_ENEMY, steps=[
        F.Step(op="launch_attack", shikigami="self", at="chosen",
               target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[1]                            # 100102：1/6
    b.level = 1
    play(g, 0, cid, target=Ref(player=1, shikigami=1))
    assert b.health == 3                           # 受 A0（3 力量）攻击
    assert pa.shikigami[0].health == 3             # 反击 1 照受


def test_target_spec_stunned_filter(db, make_game):
    """目标池 stunned 过滤键：全体目标只保留眩晕角色（式神与牌手均可判定）。"""
    cid = 10010184
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.dmg(2, T(kind="all", pool="enemy_shikigami", stunned=True))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    for s in pb.shikigami:
        s.level = 1
        s.health = 10
    pb.shikigami[1].stuns.append({"kind": "normal", "turn": 0})
    play(g, 0, cid)
    assert pb.shikigami[1].health == 8
    assert pb.shikigami[0].health == 10 and pb.shikigami[2].health == 10


# ==========================================================================
# 不夜之火批次：[移动] / 持续眩晕 until_event / 杂项 op（reset_assaults /
# clear_boosts / reset_stats / energy_assault）
# ==========================================================================

MOVE_SPELL = 10010181        # 假追风：移动来源式神
SOFT_MOVE = 10010182         # 非强制移动（敌方目标静默跳过）
FORCE_MOVE = 10010183        # 假羽迹：将敌方目标移入战斗区
LOCK_FORM = 10010284         # 假尘缚形态（tags=combat_lock）
STUN_SPELL = 10010185        # 假英雄无畏：持续眩晕直到来源用牌/攻击/气绝
RESET_ASSAULTS_SPELL = 10010186   # 假真意之歌
CLEAR_BOOSTS_SPELL = 10010187     # 假日出有曜 B 选项
RESET_STATS_SPELL = 10010188      # 假日出有曜 A 选项
ENERGY_ASSAULT_SPELL = 10010189   # 假觉醒·镰鼬能量出击


def _mech_game(make_game):
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    return g, pa, pb


# ---------- [移动]（move op） ----------

def test_move_toggle_between_zones(db, make_game):
    """[移动]：准备区↔战斗区切换；进/出各计一次移动（ext move_count_turn）并发
    on_enter_combat/on_leave_combat；计数半回合作用域（回合开始清零）。"""
    db.cards[MOVE_SPELL] = F.card(
        MOVE_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="move", target=T(kind="self"))])
    g, pa, pb = _mech_game(make_game)
    s = pa.shikigami[0]
    n = len(g.history)
    play(g, 0, MOVE_SPELL)                   # 准备区 → 战斗区
    assert pa.combat_index == 0
    assert s.ext["move_count_turn"] == 1
    assert "on_enter_combat" in g.history[n:]
    n = len(g.history)
    play(g, 0, MOVE_SPELL)                   # 战斗区 → 准备区
    assert pa.combat_index is None
    assert s.ext["move_count_turn"] == 2
    assert "on_leave_combat" in g.history[n:]
    pass_turns(g, 2)                         # 半回合作用域：计数清零
    assert "move_count_turn" not in s.ext


def test_move_force_enemy_and_combat_lock(db, make_game):
    """羽迹（move force=True）：将敌方式神拉入其战斗区（非强制对敌方目标静默跳过）；
    己方战斗区有式神时，移入会替换被尘缚之阵锁定的战斗区式神的移动无效。"""
    db.cards[SOFT_MOVE] = F.card(
        SOFT_MOVE, shikigami=100101, level=1, token=True, target=CHOOSE_ENEMY,
        steps=[F.Step(op="move")])
    db.cards[FORCE_MOVE] = F.card(
        FORCE_MOVE, shikigami=100101, level=1, token=True, target=CHOOSE_ENEMY,
        steps=[F.Step(op="move", force=True)])
    db.cards[LOCK_FORM] = F.card(
        LOCK_FORM, shikigami=100102, card_type="form", level=1,
        form_power=3, form_health=5, tags=["combat_lock"], token=True)
    db.cards[MOVE_SPELL] = F.card(
        MOVE_SPELL, shikigami=100103, level=1, token=True,
        steps=[F.Step(op="move", target=T(kind="self"))])
    g, pa, pb = _mech_game(make_game)
    pb.shikigami[0].level = 1
    play(g, 0, SOFT_MOVE, target=Ref(player=1, shikigami=0))
    assert pb.combat_index is None           # 非强制：敌方目标跳过
    play(g, 0, FORCE_MOVE, target=Ref(player=1, shikigami=0))
    assert pb.combat_index == 0              # 强制：拉入敌方战斗区
    assert pb.shikigami[0].ext["move_count_turn"] == 1
    # 尘缚锁定：敌方战斗区式神结附 combat_lock 形态、己方战斗区有式神时移动无效
    inst = F.CardInstance(uid=g.state.next_uid, id=LOCK_FORM)
    g.state.next_uid += 1
    pb.shikigami[0].form = inst
    pa.combat_index = 0
    pa.shikigami[2].level = 1
    play(g, 0, MOVE_SPELL)                   # 100103 位试图进战斗区 → 无效
    assert pa.combat_index == 0
    assert "move_count_turn" not in pa.shikigami[2].ext


# ---------- 持续眩晕 until_event（英雄无畏） ----------

def _stun_game(db, make_game):
    """0 号位对敌方 0 号位施加持续眩晕（直到来源用牌/攻击/气绝）的对局。"""
    db.cards[STUN_SPELL] = F.card(
        STUN_SPELL, shikigami=100101, level=1, token=True, target=CHOOSE_ENEMY,
        steps=[F.Step(op="stun", lasting=True,
                      until_event=["on_card_played", "on_before_assault",
                                   "on_shikigami_defeated"])])
    g, pa, pb = _mech_game(make_game)
    pb.shikigami[0].level = 1
    play(g, 0, STUN_SPELL, target=Ref(player=1, shikigami=0))
    b0 = pb.shikigami[0]
    assert b0.stuns and b0.stuns[0]["kind"] == "lasting"
    return g, pa, pb


def test_lasting_stun_blocks_and_releases_on_card_played(db, make_game):
    """英雄无畏：持续眩晕不随回合解除（被眩晕者不能出击）；来源式神用牌时解除。"""
    g, pa, pb = _stun_game(db, make_game)
    b0 = pb.shikigami[0]
    pass_turns(g, 1)                         # B 回合：持续眩晕不随回合解除
    assert b0.stuns
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    pass_turns(g, 1)                         # 回 A 回合
    assert b0.stuns
    play(g, 0, 10010101)                     # 来源式神用牌 → 解除
    assert b0.stuns == []


def test_lasting_stun_releases_on_assault_and_defeat(db, make_game):
    """英雄无畏：来源式神攻击（on_before_assault）或气绝（on_shikigami_defeated）
    同样解除；被眩晕者自身气绝走现有气绝清理。"""
    g, pa, pb = _stun_game(db, make_game)
    g.apply({"op": "assault", "index": 0})   # 来源攻击 → 解除
    assert pb.shikigami[0].stuns == []
    g2, pa2, pb2 = _stun_game(db, make_game)
    g2.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    g2._drain_queue()
    assert pa2.shikigami[0].defeated
    assert pb2.shikigami[0].stuns == []      # 来源气绝 → 解除
    g3, pa3, pb3 = _stun_game(db, make_game)
    g3.deal_to_shikigami(Ref(player=1, shikigami=0), 99, None)
    g3._drain_queue()
    assert pb3.shikigami[0].defeated
    assert pb3.shikigami[0].stuns == []      # 被眩晕者气绝：现有清理


# ---------- 杂项 op（reset_assaults / clear_boosts / reset_stats / energy_assault） ----------

def test_reset_assaults_grants_extra_assault(db, make_game):
    """真意之歌（reset_assaults）：出击次数恢复为 1，本回合可再次出击。"""
    db.cards[RESET_ASSAULTS_SPELL] = F.card(
        RESET_ASSAULTS_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="reset_assaults")])
    g, pa, pb = _mech_game(make_game)
    g.apply({"op": "assault", "index": 0})   # 3 攻打牌手
    assert pa.assaults_left == 0
    play(g, 0, RESET_ASSAULTS_SPELL)
    assert pa.assaults_left == 1
    g.apply({"op": "assault", "index": 0})   # 再次出击
    assert pb.health == 30 - 3 - 3


def test_clear_boosts_empties_assault_boosts(db, make_game):
    """日出有曜 B 选项（clear_boosts）：清除目标牌手全部出击加成；无牌手目标默认控制者。"""
    db.cards[CLEAR_BOOSTS_SPELL] = F.card(
        CLEAR_BOOSTS_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="clear_boosts")])
    db.cards[CLEAR_BOOSTS_SPELL + 1] = F.card(
        CLEAR_BOOSTS_SPELL + 1, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="clear_boosts", target=T(kind="all", pool="enemy_player"))])
    g, pa, pb = _mech_game(make_game)
    pa.assault_boosts = [{"power": 2, "shield": 2}]
    play(g, 0, CLEAR_BOOSTS_SPELL)
    assert pa.assault_boosts == []
    pb.assault_boosts = [{"power": 1, "shield": 0}]
    play(g, 0, CLEAR_BOOSTS_SPELL + 1)
    assert pb.assault_boosts == []


def test_reset_stats_restores_base_and_clears_shield(db, make_game):
    """日出有曜 A 选项（reset_stats）：力量/生命变回基础值、护甲与破甲清除——
    直改非事件（不触发伤害/治疗时机）。"""
    db.cards[RESET_STATS_SPELL] = F.card(
        RESET_STATS_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="reset_stats", target=T(kind="self"))])
    g, pa, pb = _mech_game(make_game)
    s = pa.shikigami[0]
    s.temp_power = 3
    s.shield = 2
    s.health = 1
    play(g, 0, RESET_STATS_SPELL)
    assert s.temp_power == 0 and s.eff_power == 3
    assert s.shield == 0
    assert s.health == s.max_health == 4


def test_energy_assault_pays_energy_when_no_orb(db, make_game):
    """觉醒·镰鼬（energy_assault）：鬼火与出击次数都为 0 时，旗标持有者可耗 3 能量
    出击（不耗出击次数）；非持有者或有鬼火时不可用。"""
    db.cards[ENERGY_ASSAULT_SPELL] = F.card(
        ENERGY_ASSAULT_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="energy_assault")])
    g, pa, pb = _mech_game(make_game)
    pa.shikigami[1].level = 1
    play(g, 0, ENERGY_ASSAULT_SPELL)         # 登记旗标（holder=0 号位）
    s = pa.shikigami[0]
    s.energy = 3
    pa.orb = 0
    pa.assaults_left = 0
    g.apply({"op": "assault", "index": 0})   # 耗 3 能量出击
    assert s.energy == 0
    assert pa.assaults_left == 0             # 不耗出击次数
    assert pb.health == 30 - 3
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 1})   # 非持有者：不可用
    s.energy = 3
    pa.orb = 1
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})   # 有鬼火：能量出击分支不生效


# ---------- 气绝形态使用（form_death_play，觉醒·小鹿男）与方式授予关键字（森之力） ----------

FAWN_FLAG = 10010190         # 假觉醒·小鹿男旗标牌
FAWN_FORM = 10010191         # 假小鹿男形态牌
BURST_KW_SPELL = 10010192    # 假森之力：爆能方式授予[瞬发]


def _fawn_cards(db):
    db.cards[FAWN_FLAG] = F.card(
        FAWN_FLAG, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="form_death_play")])
    db.cards[FAWN_FORM] = F.card(
        FAWN_FORM, shikigami=100101, card_type="form", level=1,
        form_power=4, form_health=6, token=True)


def test_form_death_play_revives_then_attaches(db, make_game):
    """觉醒·小鹿男（form_death_play 旗标）：持有者气绝时其形态牌可用——消耗 3 能量
    （_spend_energy 统一入口，免单/代偿同通道），使用效果前先复活持有者再正常结附；
    能量不足不可用；无旗标不可用（既有行为）。"""
    _fawn_cards(db)
    g, pa, pb = _mech_game(make_game)
    s = pa.shikigami[0]
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    g._drain_queue()
    assert s.defeated
    s.energy = 3
    with pytest.raises(IllegalAction):     # 无旗标：气绝中不可用
        g.apply({"op": "play_card", "uid": give(g, 0, FAWN_FORM).uid})
    # 第二盘：先登记旗标再气绝
    g2, pa2, pb2 = _mech_game(make_game)
    s2 = pa2.shikigami[0]
    play(g2, 0, FAWN_FLAG)                 # 登记旗标（holder=0 号位）
    g2.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    g2._drain_queue()
    assert s2.defeated
    with pytest.raises(IllegalAction):     # 能量不足（0<3）：不可用
        g2.apply({"op": "play_card", "uid": give(g2, 0, FAWN_FORM).uid})
    assert s2.defeated
    s2.energy = 3
    g2.apply({"op": "play_card", "uid": give(g2, 0, FAWN_FORM).uid})
    assert s2.energy == 0                  # 消耗 3 能量
    assert not s2.defeated                 # 先复活
    assert s2.form is not None and s2.form.id == FAWN_FORM  # 再正常结附
    assert s2.health == s2.max_health      # 复活生命回满（形态上限 6）


def test_method_keywords_grant_fast_for_this_play(db, make_game):
    """森之力（PlayMethod.keywords）：爆能方式本次使用临时授予[瞬发]——装配在
    瞬发/费用判定之前（首张瞬发免费），结算后移除；不带方式使用不具瞬发。"""
    db.cards[BURST_KW_SPELL] = F.card(
        BURST_KW_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="damage", amount=1, target=T(kind="all", pool="projectile"))],
        methods=[F.method("burst", energy_cost=1, keywords=["fast"],
                          effects=F.block(F.Step(
                              op="damage", amount=1,
                              target=T(kind="all", pool="projectile"))))])
    g, pa, pb = _mech_game(make_game)
    pa.orb = 1
    s = pa.shikigami[0]
    s.energy = 1
    inst = give(g, 0, BURST_KW_SPELL)
    g.apply({"op": "play_card", "uid": inst.uid, "play_method": "burst"})
    assert pa.orb == 1                     # 方式授予[瞬发]：首张免费
    assert pa.fast_used                    # 占用瞬发名额
    assert s.energy == 0                   # 爆能 1 已付
    assert pb.health == 30 - (1 + 1)       # 基础 1 + 爆能追加 1
    assert "keywords_add" not in inst.mods  # 结算后移除（不残留实例）
    s.energy = 1
    pa.orb = 1
    g.apply({"op": "play_card", "uid": give(g, 0, BURST_KW_SPELL).uid})
    assert pa.orb == 0                     # 不带方式：不具瞬发，正常收 1 火
    assert s.energy == 1                   # 无爆能消耗


# ---------- TargetSpec keyword 过滤 / heal full / cancel_attack / attack_replace ----------

KW_BUFF = 10010193           # 假"使有[充能]的式神获得力量"
HEAL_FULL_SPELL = 10010194   # 假沐浴阳光（恢复所有生命）
CANCEL_SPELL = 10010195      # 假鸦羽疾走（响应取消本次攻击）


def test_target_spec_keyword_filter(db, make_game):
    """TargetSpec 额外过滤键 keyword（日和坊"有[充能]的式神"类）：三列表
    （keywords/one_shot/perm）任一含即保留，不具备者被滤除。"""
    db.cards[KW_BUFF] = F.card(KW_BUFF, token=True, steps=[
        F.Step(op="buff_power", amount=1, perm=True,
               target=T(kind="all", pool="friendly_shikigami", keyword="charge"))])
    db.shikigami[100102].keywords = ["charge"]             # 先天关键字入 perm 列表
    g, pa, pb = _mech_game(make_game)
    pa.shikigami[1].level = 1
    pa.shikigami[2].level = 1
    pa.shikigami[2].one_shot_keywords.append("charge")     # one_shot 列表
    play(g, 0, KW_BUFF)
    assert pa.shikigami[0].perm_power == 0
    assert pa.shikigami[1].perm_power == 1                 # perm 关键字命中
    assert pa.shikigami[2].perm_power == 1                 # one_shot 关键字命中
    assert pa.shikigami[3].perm_power == 0


def test_heal_full_restores_missing_health(db, make_game):
    """heal full（沐浴阳光"恢复所有生命"）：逐目标按其缺失生命恢复（式神与牌手同理），
    不带 amount（缺省 0）。"""
    db.cards[HEAL_FULL_SPELL] = F.card(HEAL_FULL_SPELL, token=True, steps=[
        F.Step(op="heal", full=True, target=T(kind="all", pool="friendly_shikigami")),
        F.Step(op="heal", full=True, target=T(kind="all", pool="self_player"))])
    g, pa, pb = _mech_game(make_game)
    pa.shikigami[1].level = 1
    pa.shikigami[0].health = 1
    pa.shikigami[1].health = 3
    pa.health = 20
    play(g, 0, HEAL_FULL_SPELL)
    assert pa.shikigami[0].health == pa.shikigami[0].max_health
    assert pa.shikigami[1].health == 6
    assert pa.health == 30


def test_cancel_attack_response_cancels_battle(db, make_game):
    """cancel_attack（鸦羽疾走"自动使用并取消本次攻击"）：响应 on_before_assault 置
    取消旗标，战斗终止——双方无伤害；已付的出击鬼火不退，响应牌正常进墓地。"""
    db.cards[CANCEL_SPELL] = F.card(
        CANCEL_SPELL, shikigami=SID, level=1, token=True, keywords=["trigger"],
        when="on_before_assault", block_kw={"condition": {"victim_shikigami": SID}},
        steps=[F.Step(op="cancel_attack")])
    g, pa, pb = _mech_game(make_game)
    pass_turns(g, 1)                           # → B 第 1 回合
    move(g, 1, 0)                              # B0 驻留战斗区到 A 回合
    pb.orb = 2
    give(g, 1, CANCEL_SPELL)
    pass_turns(g, 1)                           # → A 第 2 回合
    pa.orb = 9
    g.apply({"op": "assault", "index": 0})
    a, b = pa.shikigami[0], pb.shikigami[0]
    assert a.health == 4 and b.health == 4     # 双方无伤害：攻击被取消
    assert pa.orb == 8                         # 出击鬼火已扣不退
    assert pb.orb == 1                         # 响应付费
    assert pb.graveyard[-1].id == CANCEL_SPELL


def test_attack_replace_two_random_enemy_characters(db, make_game):
    """attack_replace（烬染不夜"攻击时改为对两个随机敌方角色造成等同于自身力量与战力
    之和的伤害"）：先攻/交战阶段被替换为对两个随机敌方角色的效果伤害——无交战、
    不受反击；替换伤害为非战斗伤害（维护者定案：能力造成，贯通/吸血等战斗伤害
    监听不生效）；on_after_assault 照常发出。"""
    db.shikigami[100102].ability = F.block(
        F.Step(op="attack_replace"),
        when="on_before_assault", condition={"attacker_shikigami": "self"})
    g, pa, pb = _mech_game(make_game)
    move(g, 1, 0)                              # B0（3 力量）驻战斗区：检验不受反击
    a = pa.shikigami[1]                        # 100102（1/6）
    a.level = 1
    a.keywords.append("lifesteal")
    a.health = 2                               # 吸血若生效会回到 3（战斗伤害才会）
    n = len(g.history)
    g.apply({"op": "assault", "index": 1})
    assert a.health == 2                       # 不受反击 + 非战斗伤害吸血不生效
    total = (sum(s.max_health - s.health for s in pb.shikigami)
             + (30 - pb.health))
    assert total == 2                          # X=1，两个随机敌方角色各 1
    assert "on_after_assault" in g.history[n:]


# ---------- 维护者定案批：generate 随机入库 / clear_boosts·reset_stats 显式目标 ----------

def test_generate_deck_random_position(db, make_game):
    """generate zone=deck position=random（同心协力 20200423 定案："置入牌库"= 随机
    插入不洗牌）：缺省 bottom 保持库底，random 按 randrange 落位。"""
    gen = 10010196
    db.cards[gen] = F.card(gen, token=True, steps=[
        F.Step(op="generate", card_id=10010101, zone="deck")])
    db.cards[gen + 1] = F.card(gen + 1, token=True, steps=[
        F.Step(op="generate", card_id=10010101, zone="deck", position="random")])
    g, pa, pb = _mech_game(make_game)
    play(g, 0, gen)
    assert pa.deck[-1].id == 10010101                  # 缺省：库底
    g.rng.randrange = lambda n: 0                      # 固定落位验证随机通道接线
    play(g, 0, gen + 1)
    assert pa.deck[0].id == 10010101                   # random：插入 randrange 指定位置


def test_clear_boosts_reset_stats_explicit_target_semantics(db, make_game):
    """日出有曜单目标双效果定案：clear_boosts 显式选择牌手目标→对其生效；显式选择
    式神目标→空操作（不回退控制者）；reset_stats 对牌手目标空操作。"""
    db.cards[CLEAR_BOOSTS_SPELL] = F.card(
        CLEAR_BOOSTS_SPELL, shikigami=100101, level=1, token=True, target=CHOOSE_ENEMY,
        steps=[F.Step(op="clear_boosts")])
    db.cards[10010198] = F.card(
        10010198, shikigami=100101, level=1, token=True,
        target=T(kind="choose", pool="enemy_player"),
        steps=[F.Step(op="clear_boosts")])
    db.cards[RESET_STATS_SPELL] = F.card(
        RESET_STATS_SPELL, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="reset_stats", target=T(kind="all", pool="enemy_player"))])
    g, pa, pb = _mech_game(make_game)
    pb.shikigami[0].level = 1
    pa.assault_boosts = [{"power": 2, "shield": 2}]
    pb.assault_boosts = [{"power": 1, "shield": 0}]
    play(g, 0, CLEAR_BOOSTS_SPELL, target=Ref(player=1, shikigami=0))  # 显式式神目标
    assert pa.assault_boosts and pb.assault_boosts     # 空操作：双方加成都在
    play(g, 0, 10010198, target=Ref(player=1))         # 显式牌手目标
    assert pb.assault_boosts == []                     # 只对目标牌手生效
    assert pa.assault_boosts                           # 不回退控制者
    pb.shikigami[0].temp_power = 3
    play(g, 0, RESET_STATS_SPELL)                      # 牌手目标：空操作
    assert pb.shikigami[0].temp_power == 3


# ==========================================================================
# 铃鹿御前批次：霸主破甲来源免疫 / enemy_fragile_ge2 / enemy_fragile_or_combat /
# event amount cap
# ==========================================================================

def _fragile_source_immunity_spell(db, cid=10010184):
    """霸主型：授予来源式神"免疫破甲敌方式神的伤害"（grant_immunity
    kind=fragile_source / scope=form）。"""
    db.cards[cid] = F.card(cid, token=True, steps=[F.Step(
        op="grant_immunity", scope="form", kind="fragile_source",
        target=T(kind="self"))])
    return cid


def test_fragile_source_immunity(db, make_game):
    """破甲来源免疫：伤害来源为当前持有破甲的敌方式神时免疫（伤害类别不限）；
    来源破甲消失后不再免疫；己方来源（即使持破甲）不免疫。"""
    _fragile_source_immunity_spell(db)
    g, pa, pb = _mech_game(make_game)
    play(g, 0, 10010184)
    ref = Ref(player=0, shikigami=0)
    src = Ref(player=1, shikigami=0)
    pb.shikigami[0].shield = -2                    # 来源持破甲：免疫
    g.deal_to_shikigami(ref, 3, src)
    assert pa.shikigami[0].health == 4
    pb.shikigami[0].shield = 0                     # 破甲消失：不免疫
    g.deal_to_shikigami(ref, 3, src)
    assert pa.shikigami[0].health == 1
    pa.shikigami[1].level = 1
    pa.shikigami[1].shield = -1                    # 己方来源持破甲：不免疫
    g.deal_to_shikigami(ref, 1, Ref(player=0, shikigami=1))
    assert pa.shikigami[0].health == 0


def test_fragile_source_immunity_form_scope_cleanup(db, make_game):
    """scope=form：形态离场经 _destroy_form 清除形态作用域免疫条目（霸主为形态牌）。"""
    _fragile_source_immunity_spell(db)
    db.cards[10010185] = F.card(10010185, card_type="form", level=1, token=True)
    g, pa, pb = _mech_game(make_game)
    play(g, 0, 10010184)
    s = pa.shikigami[0]
    assert any(e.get("kind") == "fragile_source" for e in s.immunities)
    play(g, 0, 10010185)                           # 结附形态
    g._destroy_form(pa, 0, "test")
    assert not any(e.get("kind") == "fragile_source" for e in s.immunities)


def test_enemy_fragile_ge2_keyword(db, make_game):
    """conditional_keywords 算子 enemy_fragile_ge2：敌方场上存在破甲 ≧2 的角色
    （在场式神或牌手）才授予关键字（铃鹿御前型条件瞬发）。"""
    cid = 10010186
    db.cards[cid] = F.card(cid, token=True, conditional_keywords=[
        {"keyword": "fast", "enemy_fragile_ge2": True}])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    inst = give(g, 0, cid)
    cdef = db.cards[cid]
    assert "fast" not in g._card_keywords(pa, cdef, inst)
    pb.shikigami[0].shield = -1                    # 破甲 1：不成立
    assert "fast" not in g._card_keywords(pa, cdef, inst)
    pb.shikigami[0].shield = -2                    # 式神气破甲 2：成立
    assert "fast" in g._card_keywords(pa, cdef, inst)
    pb.shikigami[0].shield = 0
    pb.shield = -2                                 # 牌手破甲 2：成立
    assert "fast" in g._card_keywords(pa, cdef, inst)


def test_pool_enemy_fragile_or_combat(db, make_game):
    """无往型目标池 enemy_fragile_or_combat：敌方有破甲的在场式神或敌方战斗区式神
    （或关系；含持破甲的敌方牌手）。"""
    cid = 10010197
    db.cards[cid] = F.card(cid, token=True, steps=[F.dmg(1)],
                           target=T(kind="choose", pool="enemy_fragile_or_combat"))
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    inst = give(g, 0, cid)
    assert g.legal_targets(0, inst) == []          # 无破甲且战斗区空：空池
    move(g, 1, 0)                                  # 战斗区式神入池（无破甲也算）
    pb.shikigami[1].level = 1
    pb.shikigami[1].shield = -1                    # 破甲准备区式神入池
    got = g.legal_targets(0, inst)
    assert sorted((r.player, r.shikigami) for r in got) == [(1, 0), (1, 1)]
    pb.shield = -2                                 # 牌手持破甲：牌手入池
    assert Ref(player=1) in g.legal_targets(0, inst)


def test_event_amount_cap(db, make_game):
    """_step_amount {"event": key, "cap": n}：事件引用值经上限截断（觉醒·铃鹿御前
    "至多获得3点破甲"型）；不超过上限时取原值。"""
    cid = 10010183
    db.cards[cid] = F.card(
        cid, card_type="form", level=1, token=True,
        abilities=[F.EffectBlock(
            when="on_player_damaged", condition={"player": "self"},
            steps=[F.Step(op="gain_shield",
                          amount={"event": "amount", "cap": 3}, kind="fragile",
                          target=T(kind="context", key="damaged_player"))])])
    g, pa, pb = _mech_game(make_game)
    play(g, 0, cid)
    g.deal_to_player(0, 5, Ref(player=1, shikigami=0))
    g._drain_queue()
    assert pa.shield == -3                         # min(5, 3)：上限截断
    # 不破上限取原值（开新局：避免既有破甲加伤抬高事件值干扰读数）
    g2 = make_game()
    pa2, pb2 = g2.state.players
    pa2.orb = 9
    play(g2, 0, cid)
    g2.deal_to_player(0, 2, Ref(player=1, shikigami=0))
    g2._drain_queue()
    assert pa2.shield == -2                        # min(2, 3) = 2


# ==========================================================================
# 惊鸿之舞批次：random_branch / 分支条件键 / 鼓舞随机关键字槽 /
# highest_power 过滤 / grant_keyword scope="turn"
# ==========================================================================

def test_random_branch_condition_filter(db, make_game):
    """random_branch：只从条件通过的分支中均等随机（不满足的分支永不入选）；
    无满足分支时空操作。"""
    cid = 10010160
    db.cards[cid] = F.card(cid, token=True, steps=[F.Step(
        op="random_branch",
        branches=[
            {"condition": {"player_health_le": 0},            # 永不满足
             "steps": [{"op": "draw", "count": 1}]},
            {"condition": {"player_missing_health_ge": 99},   # 永不满足
             "steps": [{"op": "gain_orb", "amount": 1}]},
            {"condition": None,                               # 恒真：唯一入选
             "steps": [{"op": "gain_shield", "amount": 5,
                        "target": {"kind": "all", "pool": "self_player"}}]},
        ])])
    cid2 = 10010161
    db.cards[cid2] = F.card(cid2, token=True, steps=[F.Step(
        op="random_branch",
        branches=[{"condition": {"player_health_le": 0},
                   "steps": [{"op": "draw", "count": 1}]}])])
    g, pa, pb = _mech_game(make_game)
    pa.orb = 2
    deck0 = len(pa.zones["deck"])
    play(g, 0, cid)
    assert pa.shield == 5                    # 唯一满足分支执行
    assert len(pa.zones["deck"]) == deck0    # draw 分支未执行
    assert pa.orb == 1                       # gain_orb 分支未执行
    play(g, 0, cid2)                         # 无满足分支：空操作不报错
    assert len(pa.zones["deck"]) == deck0


def test_kanko_branch_condition_keys(db, make_game):
    """惊鸿分支条件键：friendly_defeated_exists / player_health_le /
    player_missing_health_ge / combat_occupied。"""
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    ev = {}
    assert not g._match({"friendly_defeated_exists": True}, ev, 0)
    assert not g._match({"combat_occupied": "friendly"}, ev, 0)
    assert g._match({"player_health_le": 30}, ev, 0)
    assert not g._match({"player_health_le": 29}, ev, 0)
    assert not g._match({"player_missing_health_ge": 6}, ev, 0)
    pa.health = 24
    assert g._match({"player_missing_health_ge": 6}, ev, 0)
    move(g, 0, 0)
    assert g._match({"combat_occupied": "friendly"}, ev, 0)
    s = pa.shikigami[1]
    s.level = 1
    s.defeated = True
    assert g._match({"friendly_defeated_exists": True}, ev, 0)


def test_basic_boost_keyword_random_slot(db, make_game):
    """鼓舞随机关键字（basic_boost keyword_random）：玩家级槽至多一个、后授予替换
    已有；消耗加成的攻击中临时授予攻击者、随加成消耗清除。"""
    ca, cb = 10010162, 10010163
    db.cards[ca] = F.card(ca, token=True, steps=[F.Step(
        op="basic_boost", power=2, shield=2, keyword_random=["combo"])])
    db.cards[cb] = F.card(cb, token=True, steps=[F.Step(
        op="basic_boost", power=2, shield=2, keyword_random=["remote"])])
    g, pa, pb = _mech_game(make_game)
    pb.shield = 0
    play(g, 0, ca)
    assert pa.ext.get("boost_keyword") == "combo"
    play(g, 0, cb)                           # 后授予替换已有
    assert pa.ext.get("boost_keyword") == "remote"
    hp0 = pb.health
    g.apply({"op": "assault", "index": 0})
    assert pb.health == hp0 - 7              # 一段 3 + 两笔战力叠加 4（remote——非 combo 两段）
    assert "boost_keyword" not in pa.ext     # 随加成消耗清除
    # 槽中关键字在攻击中临时授予：combo 两段各 5，战斗后经 attack_buffs 移除
    g2, pa2, pb2 = _mech_game(make_game)
    pb2.shield = 0
    play(g2, 0, ca)
    hp1 = pb2.health
    a2 = pa2.shikigami[0]
    g2.apply({"op": "assault", "index": 0})
    assert pb2.health == hp1 - 10            # combo：(3+2) × 2 段
    assert "combo" not in a2.keywords        # 战斗结束移除
    assert "boost_keyword" not in pa2.ext


def test_grant_keyword_scope_turn(db, make_game):
    """grant_keyword scope="turn"：当回合结束移除——敌方回合授予的也在该敌方回合
    结束移除；[不屈]被触发后正常消耗（不到回合结束）。"""
    sid = 10010164
    db.cards[sid] = F.card(sid, token=True, steps=[F.Step(
        op="grant_keyword", keyword="veil", scope="turn", target=T(kind="self"))])
    # 己方回合授予 → 己方回合结束移除
    g, pa, pb = _mech_game(make_game)
    play(g, 0, sid)
    s = pa.shikigami[0]
    assert "veil" in s.keywords
    pass_turns(g, 1)
    assert "veil" not in s.keywords
    # 敌方回合开始触发授予 → 该敌方回合结束移除
    fid = 10010166
    db.cards[fid] = F.card(
        fid, card_type="form", level=1, token=True,
        abilities=[F.EffectBlock(
            when="on_turn_start",
            steps=[F.Step(op="grant_keyword", keyword="veil", scope="turn",
                          target=T(kind="self"))])])
    g2, pa2, pb2 = _mech_game(make_game)
    play(g2, 0, fid)
    s2 = pa2.shikigami[0]
    assert "veil" not in s2.keywords         # 己方回合开始已过，未授予
    pass_turns(g2, 1)                        # B 回合开始：触发授予
    assert "veil" in s2.keywords
    g2._destroy_form(pa2, 0, "test")         # 防止下回合开始重复授予干扰断言
    pass_turns(g2, 1)                        # B 回合结束：移除
    assert "veil" not in s2.keywords
    # 不屈一次性消耗语义不变：触发保留 1 血后即移除，不到回合结束
    g3, pa3, pb3 = _mech_game(make_game)
    s3 = pa3.shikigami[0]
    s3.one_shot_keywords.append("unyielding")
    g3.deal_to_shikigami(Ref(player=0, shikigami=0), 99, Ref(player=1, shikigami=0))
    assert s3.health == 1
    assert "unyielding" not in s3.one_shot_keywords


def test_highest_power_filter(db, make_game):
    """TargetSpec highest_power：先按力量最高过滤（并列全保留），再经 random 键均等取
    （惊鸿之舞"力量最高"项；读 eff_power）。"""
    cid = 10010165
    db.cards[cid] = F.card(cid, token=True, steps=[F.dmg(
        1, target=T(kind="all", pool="enemy_shikigami",
                    highest_power=True, random=1))])
    g, pa, pb = _mech_game(make_game)
    pb.shikigami[1].level = 1
    pb.shikigami[2].level = 1
    pb.shikigami[1].temp_power = 2           # 5 力（并列最高）
    pb.shikigami[2].temp_power = 2           # 5 力（并列最高）
    play(g, 0, cid)
    hurt = [i for i, s in enumerate(pb.shikigami) if s.health < s.max_health]
    assert len(hurt) == 1
    assert hurt[0] in (1, 2)                 # 只打并列最高之一（3 力 0 号位不入选）
