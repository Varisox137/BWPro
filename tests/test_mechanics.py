"""卡牌机制测试：目标、等级门、爆能、瞬发、响应、结算模式、召唤、中立、区域、mods。

测试辅助卡使用衍生号段（51+，token=True）——正式卡序号 01-08 已被 base_db 占满。
"""
import pytest

from core import targets as targets_mod
from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, give, move

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
