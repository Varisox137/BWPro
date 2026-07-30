"""鬼火主题测试：储存（觉醒 orb_store 标记）/ 回合结束得火 / 消耗（consume_orb）/
清空重复（repeat）/ 结算中交互选择（pending_choice 检视选牌续结算）/
形态返场（consume_orb + revive + reattach_form）/ 精确弃牌与等级提升（百闻一得）/
鬼火变化事件与响应通道（on_orb_changed old→new，月食类合成卡）。

对应维护者答复（第十阶段）：「每有1点鬼火便重复一次」总次数 = 1 + 效果结算时
剩余鬼火（0 火仍执行基础 1 次），随后一次性清空（2→0 不经过 1）；鬼火变化逐个
发事件（old→new），付费点先于效果结算。返场同一实例不生成新牌；鬼火储存封顶 4 点；
百闻一得并列由使用者选择。0 号位（100101）为持卡式神。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import give, pass_turns

T = F.T
SID, IDX = 100101, 0

ORB_STORE_AWAKEN = 10010161   # 假觉醒牌：tags 含 orb_store（鬼火储存）
TURN_END_ORB_FORM = 10010162  # 假形态：己方回合结束得 1 火（百物语之火）
REPEAT_SPELL = 10010163       # 假吸魂灯：repeat + clear_orb
PICK_SPELL = 10010164         # 假青灯夜谈：deck_top_pick
RETURN_FORM = 10010165        # 假不灭之火：on_form_destroyed 返场
MINGDENG = 10010151           # 假明灯（token）
LEVEL_SPELL = 10010166        # 假百闻一得


def _game(make_game):
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    return g, pa, pb


# ---------- 鬼火储存（觉醒·青行灯 orb_store） ----------

def test_orb_store_awakened_keeps_and_caps(make_game, db):
    """鬼火储存：带 orb_store 标记觉醒牌的已觉醒式神在场时，回合开始鬼火不清零、
    储存累加并封顶 4（超出清除）；未觉醒时维持清零旧行为。"""
    db.cards[ORB_STORE_AWAKEN] = F.card(
        ORB_STORE_AWAKEN, shikigami=SID, subtype="awaken",
        tags=["awaken", "orb_store"], token=True)
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.awakened = ORB_STORE_AWAKEN
    pa.orb = 1
    pass_turns(g, 2)
    assert pa.orb == 3          # 1 留存 + 2 回合开始鬼火（不清零）
    pa.orb = 3
    pass_turns(g, 2)
    assert pa.orb == 4          # 3 + 2 封顶 4（超出清除）
    # 未觉醒：回合开始清零再获得（旧行为不变）
    g2, pa2, _ = _game(make_game)
    pa2.orb = 1
    pass_turns(g2, 2)
    assert pa2.orb == 2


# ---------- 回合结束得火（百物语之火） ----------

def test_orb_gain_on_turn_end_form(make_game, db):
    """己方回合结束得火：on_turn_end（即时时机）{player: self} → gain_orb 1，
    鬼火留到敌方回合（留火响应/配合觉醒储存）。"""
    db.cards[TURN_END_ORB_FORM] = F.card(
        TURN_END_ORB_FORM, shikigami=SID, card_type="form", level=1,
        form_power=4, form_health=5, token=True,
        abilities=[F.block(
            F.Step(op="gain_orb", amount=1),
            when="on_turn_end", condition={"player": "self"})])
    g, pa, pb = _game(make_game)
    pa.orb = 1
    g.apply({"op": "play_card", "uid": give(g, 0, TURN_END_ORB_FORM).uid})
    assert pa.orb == 0
    g.apply({"op": "end_turn"})
    assert pa.orb == 1          # 回合结束 +1（B 回合开始不影响 A 留火）


# ---------- 清空重复（吸魂灯 repeat） ----------

def test_repeat_per_orb_and_clear(make_game, db):
    """按鬼火重复并清空（吸魂灯）：重复次数 = 1 + 付费后剩余鬼火（基础 1 次 + 每点
    剩余鬼火重复 1 次）；投射目标每次独立求值；结束后一次性清空鬼火。"""
    db.cards[REPEAT_SPELL] = F.card(
        REPEAT_SPELL, shikigami=SID, level=3, token=True,
        steps=[F.Step(op="repeat", count={"orb": True}, clear_orb=True,
                      steps=[{"op": "damage", "amount": 5,
                              "target": {"kind": "all", "pool": "projectile"}}])])
    g, pa, pb = _game(make_game)
    pa.shikigami[IDX].level = 3
    pa.orb = 3
    g.apply({"op": "play_card", "uid": give(g, 0, REPEAT_SPELL).uid})
    assert pb.health == 30 - 3 * 5   # 付费后 2 火 → 1+2=3 次（战斗区空 → 敌方牌手）
    assert pa.orb == 0               # 清空
    # 0 剩余鬼火：仍执行基础 1 次，清空仍执行
    g2, pa2, pb2 = _game(make_game)
    pa2.shikigami[IDX].level = 3
    pa2.orb = 1
    g2.apply({"op": "play_card", "uid": give(g2, 0, REPEAT_SPELL).uid})
    assert pb2.health == 30 - 5      # 1+0=1 次
    assert pa2.orb == 0


# ---------- 结算中交互选择（青灯夜谈 pending_choice） ----------

def test_deck_top_pick_suspend_resume(make_game, db):
    """检视选牌（青灯夜谈）：pending_choice 挂起期间只接受 choose 指令；每次选择
    置入手牌后洗牌库，重复次数（1 + 付费后剩余鬼火）耗尽后清空鬼火并续跑挂起块。"""
    db.cards[PICK_SPELL] = F.card(
        PICK_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="deck_top_pick", count=3, times={"orb": True},
                      clear_orb=True)])
    g, pa, pb = _game(make_game)
    pa.orb = 3
    hand_before = len(pa.hand)
    g.apply({"op": "play_card", "uid": give(g, 0, PICK_SPELL).uid})
    pend = g.state.pending_choice
    assert pend is not None and pend["kind"] == "deck_top_pick"
    assert pend["player"] == 0 and pend["remaining"] == 3   # 付费后 2 火 → 1+2=3 次
    assert pend["options"] == [c.uid for c in pa.deck[:3]]  # 牌库顶 3 张
    with pytest.raises(IllegalAction):
        g.apply({"op": "end_turn"})                          # 挂起期间非 choose 指令拒绝
    for left in (2, 1, 0):
        pend = g.state.pending_choice
        assert pend is not None and pend["remaining"] == left + 1
        uid = pend["options"][0]
        g.apply({"op": "choose", "uid": uid, "player": 0})
        assert any(c.uid == uid for c in pa.hand)            # 入手
    assert g.state.pending_choice is None                    # 次数耗尽 → 续块完毕
    assert len(pa.hand) == hand_before + 3
    assert pa.orb == 0                                       # 清空鬼火
    # 0 剩余鬼火：仍执行基础 1 次（挂起一次），选择后清空
    g2, pa2, _ = _game(make_game)
    pa2.orb = 1
    hand2 = len(pa2.hand)
    g2.apply({"op": "play_card", "uid": give(g2, 0, PICK_SPELL).uid})
    pend = g2.state.pending_choice
    assert pend is not None and pend["remaining"] == 1
    g2.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    assert g2.state.pending_choice is None
    assert len(pa2.hand) == hand2 + 1
    assert pa2.orb == 0


# ---------- 形态返场（不灭之火 consume_orb + revive + reattach_form） ----------

def _return_form(db):
    db.cards[RETURN_FORM] = F.card(
        RETURN_FORM, shikigami=SID, card_type="form", level=1,
        form_power=4, form_health=5, token=True,
        abilities=[F.block(
            F.Step(op="consume_orb", amount=1),
            F.Step(op="revive", target=T(kind="self")),
            F.Step(op="reattach_form"),
            when="on_form_destroyed",
            condition={"target_shikigami": "self", "orb_ge": 1})])
    return RETURN_FORM


def test_form_returns_on_defeat_with_orb(make_game, db):
    """形态返场（不灭之火）：形态随式神气绝离场时，消耗 1 点鬼火 → 复活 → 墓地中
    同一实例重新结附（不生成新牌）；无鬼火则不返场。"""
    _return_form(db)
    g, pa, pb = _game(make_game)
    pa.orb = 3
    inst = give(g, 0, RETURN_FORM)
    g.apply({"op": "play_card", "uid": inst.uid})   # 付费后 2 火
    s = pa.shikigami[IDX]
    assert s.form is inst
    s.health = 0
    g.check_defeated(Ref(player=0, shikigami=IDX))
    g._drain_queue()
    assert not s.defeated                            # 先复活
    assert s.form is inst                            # 同一实例重新结附
    assert s.health == s.max_health                  # 复活生命回满
    assert pa.orb == 1                               # 消耗 1 点鬼火
    # 无鬼火：不返场
    g2, pa2, _ = _game(make_game)
    pa2.orb = 1
    inst2 = give(g2, 0, RETURN_FORM)
    g2.apply({"op": "play_card", "uid": inst2.uid})  # 付费后 0 火
    s2 = pa2.shikigami[IDX]
    s2.health = 0
    g2.check_defeated(Ref(player=0, shikigami=IDX))
    g2._drain_queue()
    assert s2.defeated and s2.form is None
    assert inst2 in pa2.graveyard


# ---------- 精确弃牌与等级提升（百闻一得） ----------

def test_level_up_lowest_pool_and_overflow(make_game, db):
    """百闻一得：friendly_lowest_level 池 = 己方最低等级在场式神（并列全入池由
    使用者选择）；弃掉一张'明灯'（按数据 id 精确弃牌）；已为 3 级改为抽一张牌；
    手牌无明灯时不弃、升级仍执行。"""
    db.cards[MINGDENG] = F.card(MINGDENG, shikigami=SID, token=True)
    db.cards[LEVEL_SPELL] = F.card(
        LEVEL_SPELL, shikigami=SID, level=1, token=True,
        target=T(kind="choose", pool="friendly_lowest_level"),
        steps=[F.Step(op="discard", card_id=MINGDENG, count=1),
               F.Step(op="level_up", amount=1, overflow_draw=True)])
    from core import targets as targets_mod
    g, pa, pb = _game(make_game)
    for i, lv in enumerate([1, 1, 2, 3]):
        pa.shikigami[i].level = lv
    pool = targets_mod.pool_refs(g, "friendly_lowest_level", 0)
    assert pool == [Ref(player=0, shikigami=0), Ref(player=0, shikigami=1)]  # 并列
    give(g, 0, MINGDENG)
    g.apply({"op": "play_card", "uid": give(g, 0, LEVEL_SPELL).uid,
             "target": Ref(player=0, shikigami=1).model_dump()})
    assert pa.shikigami[1].level == 2                  # 等级 +1（不走升级次数）
    assert any(c.id == MINGDENG for c in pa.graveyard)  # 明灯被精确弃掉
    # 已为 3 级：改为抽一张牌
    for s in pa.shikigami:
        s.level = 3
    hand_before = len(pa.hand)
    g.apply({"op": "play_card", "uid": give(g, 0, LEVEL_SPELL).uid,
             "target": Ref(player=0, shikigami=3).model_dump()})
    assert pa.shikigami[3].level == 3
    assert len(pa.hand) == hand_before + 1             # 抽 1
    # 无明灯：不弃牌，升级仍执行
    pa.shikigami[2].level = 2
    g.apply({"op": "play_card", "uid": give(g, 0, LEVEL_SPELL).uid,
             "target": Ref(player=0, shikigami=2).model_dump()})
    assert pa.shikigami[2].level == 3


# ---------- 鬼火变化事件与响应通道（月食类合成卡；月食本身不入数据） ----------

ECLIPSE = 10010167            # 假月食：敌方鬼火变为 1 时响应清空敌方鬼火


def _eclipse(db):
    db.cards[ECLIPSE] = F.card(
        ECLIPSE, shikigami=100102, cost=0, level=1, keywords=["trigger"], token=True,
        when="on_orb_changed",
        block_kw={"condition": {"player": "opponent", "new": 1}},
        steps=[F.Step(op="clear_orb", side="opponent")])
    return ECLIPSE


def test_orb_becomes_one_response_clears_before_effect(make_game, db):
    """鬼火变为 1 响应（维护者示例 1）：2 火用青灯夜谈 → 付费 1 火后鬼火 2→1 →
    敌方响应插入清空为 0 → 效果按结算时剩余鬼火执行 1+0=1 次。"""
    db.cards[PICK_SPELL] = F.card(
        PICK_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="deck_top_pick", count=3, times={"orb": True},
                      clear_orb=True)])
    _eclipse(db)
    g, pa, pb = _game(make_game)
    pa.orb = 2
    pb.shikigami[1].level = 1
    give(g, 1, ECLIPSE)                  # pb 持响应；pa 为回合方
    g.apply({"op": "play_card", "uid": give(g, 0, PICK_SPELL).uid})
    assert pa.orb == 0                   # 响应已清空（付费后效果前）
    assert any(c.id == ECLIPSE for c in pb.graveyard)   # 响应牌已用掉
    pend = g.state.pending_choice
    assert pend is not None and pend["remaining"] == 1  # 1+0=1 次
    g.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    assert g.state.pending_choice is None


def test_orb_clear_is_single_change_skips_one(make_game, db):
    """清空是一次性变化（维护者示例 2）：3 火用青灯夜谈 → 付费后 2 火（3→2 不触发
    变为 1 响应）→ 效果执行 1+2=3 次 → 清空 2→0 不经过 1、仍不触发——响应留手。"""
    db.cards[PICK_SPELL] = F.card(
        PICK_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="deck_top_pick", count=3, times={"orb": True},
                      clear_orb=True)])
    _eclipse(db)
    g, pa, pb = _game(make_game)
    pa.orb = 3
    pb.shikigami[1].level = 1
    give(g, 1, ECLIPSE)
    hand_before = len(pa.hand)
    g.apply({"op": "play_card", "uid": give(g, 0, PICK_SPELL).uid})
    for _ in range(3):                   # 1+2=3 次检视选择
        pend = g.state.pending_choice
        assert pend is not None
        g.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    assert g.state.pending_choice is None
    assert len(pa.hand) == hand_before + 3
    assert pa.orb == 0                   # 已清空（2→0 一次性）
    assert any(c.id == ECLIPSE for c in pb.hand)        # 全程未触发，留手


def test_orb_payment_emits_change_event(make_game, db):
    """鬼火变化逐个发事件：使用牌付费（2→1）与出击付费均 emit on_orb_changed。"""
    db.cards[PICK_SPELL] = F.card(
        PICK_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="deck_top_pick", count=3, times=1)])
    g, pa, pb = _game(make_game)
    pa.orb = 2
    n = len(g.history)
    g.apply({"op": "play_card", "uid": give(g, 0, PICK_SPELL).uid})
    assert "on_orb_changed" in g.history[n:]
    g.apply({"op": "choose", "uid": g.state.pending_choice["options"][0], "player": 0})
    n = len(g.history)
    pa.orb = 1
    pa.shikigami[IDX].level = 1
    g.apply({"op": "assault", "index": IDX})
    assert "on_orb_changed" in g.history[n:]
