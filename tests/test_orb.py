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


# ==========================================================================
# 能量 / [爆能] / 日和坊（不夜之火批次）
# ==========================================================================

RIHEFANG = 100205          # 日和坊（引擎直读 id：觉醒免单 / 基础能力生命代偿）
RF_AWAKEN = 10020551       # 假觉醒·日和坊（token 空白，仅提供觉醒标记）
BURST_SPELL = 10010171     # 假爆能牌：定值爆能 2（追加投射 3）
BURST_X_SPELL = 10010172   # 假爆能 X 牌（energy_cost="all"）


def _charge_game(make_game, db):
    """0 号位带[充能]的对局。"""
    db.shikigami[SID].keywords = ["charge"]
    g, pa, pb = _game(make_game)
    return g, pa, pb


# ---------- 充能（charge 关键字） ----------

def test_charge_gain_cap_and_defeated_retain(make_game, db):
    """[充能]：己方回合开始获得 1 点能量（上限 10，对局开始的回合开始阶段已充 1 点）；
    气绝时能量保留但不充能（维护者定案：气绝无能力）；刚复活的式神当回合立即 +1
    （复活批次 _turn_start_revive 先于充能批次）。"""
    g, pa, pb = _charge_game(make_game, db)
    s = pa.shikigami[IDX]
    assert s.energy == 1                   # 对局开始（A 第 1 回合开始）已充能
    pass_turns(g, 2)                       # A 第 2 回合开始：+1
    assert s.energy == 2
    s.energy = 10
    pass_turns(g, 2)
    assert s.energy == 10                  # 上限 10
    s.energy = 5
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated and s.energy == 5    # 气绝保留
    pass_turns(g, 2)                       # 气绝不充能（复活倒计时 3→2，仍气绝）
    assert s.defeated and s.energy == 5
    pass_turns(g, 4)                       # A 第 4 回合开始：倒计时 1→0 复活，同批次充能
    assert not s.defeated and s.energy == 6


def test_on_energy_gained_trigger_no_recursion(make_game, db):
    """on_energy_gained 触发器（烟烟罗觉醒"获得能量时改为两倍"模式）：监听 old:0
    （首次获得）追加获得，追加用 emit_event=False 不再发事件（防递归）。"""
    db.shikigami[SID].ability = F.block(
        F.Step(op="gain_energy", amount=1, emit_event=False,
               target=T(kind="self")),
        when="on_energy_gained", condition={"player": "self", "old": 0})
    g, pa, pb = _charge_game(make_game, db)
    s = pa.shikigami[IDX]
    # 对局开始的回合开始充能 0→1（old=0 命中）→ 追加 +1
    assert s.energy == 2
    pass_turns(g, 2)                       # old=2 不命中条件：只 +1（无连锁）
    assert s.energy == 3
    pass_turns(g, 2)
    assert s.energy == 4


# ---------- [爆能]（PlayMethod.energy_cost） ----------

def _burst_card(db):
    db.cards[BURST_SPELL] = F.card(
        BURST_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="projectile"))],
        methods=[F.method("burst", energy_cost=2, effects=F.block(
            F.Step(op="damage", amount=3, target=T(kind="all", pool="projectile"))))])
    return BURST_SPELL


def test_burst_fixed_cost_pay_and_append_effects(make_game, db):
    """[爆能]定值：方式 effects 追加在基础 effects 之后（非覆盖）；能量足够则支付，
    不足则该方式不可用；不带方式使用不耗能量。"""
    cid = _burst_card(db)
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.energy = 1
    with pytest.raises(IllegalAction):     # 能量不足：爆能方式不可选
        g.apply({"op": "play_card", "uid": give(g, 0, cid).uid, "play_method": "burst"})
    s.energy = 2
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid, "play_method": "burst"})
    assert s.energy == 0                   # 支付 2 能量
    assert pb.health == 30 - (2 + 3)       # 基础 2 + 爆能追加 3（投射→敌方牌手）
    s.energy = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert s.energy == 3                   # 不带方式：不耗能量
    assert pb.health == 30 - (2 + 3) - 2


def test_burst_all_snapshot_and_zero_gate(make_game, db):
    """[爆能]X（energy_cost="all"）：支付全部能量（至少 1 点），X = 支付时快照
    （{"burst_x": true} 读 card.mods["burst_x"]，结算后清除不残留）。"""
    db.cards[BURST_X_SPELL] = F.card(
        BURST_X_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="damage", amount=1, target=T(kind="all", pool="projectile"))],
        methods=[F.method("burst_x", energy_cost="all", effects=F.block(
            F.Step(op="damage", amount={"burst_x": True},
                   target=T(kind="all", pool="projectile"))))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    with pytest.raises(IllegalAction):     # 0 能量：爆能 X 不可选
        g.apply({"op": "play_card", "uid": give(g, 0, BURST_X_SPELL).uid,
                 "play_method": "burst_x"})
    s.energy = 3
    inst = give(g, 0, BURST_X_SPELL)
    g.apply({"op": "play_card", "uid": inst.uid, "play_method": "burst_x"})
    assert s.energy == 0                   # 全部支付
    assert pb.health == 30 - (1 + 3)       # 基础 1 + X=3
    assert "burst_x" not in inst.mods      # 快照结算后清除


# ---------- 日和坊（觉醒免单 / 基础能力生命代偿） ----------

def _rihefang_game(make_game, db, awakened=False):
    """1 号位日和坊（在场）+ 0 号位持定值爆能牌的对局。"""
    db.shikigami[RIHEFANG] = F.shiki(RIHEFANG, name="日和坊")
    for n in range(1, 9):                  # 凑卡组空白卡
        db.cards[RIHEFANG * 100 + n] = F.card(RIHEFANG * 100 + n, shikigami=RIHEFANG,
                                              level=(n - 1) % 3 + 1)
    db.cards[RF_AWAKEN] = F.card(RF_AWAKEN, shikigami=RIHEFANG, subtype="awaken",
                                 tags=["awaken"], token=True)
    _burst_card(db)
    g = make_game(team=[SID, RIHEFANG, 100103, 100104])
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    rf = pa.shikigami[1]
    rf.level = 1
    if awakened:
        rf.awakened = RF_AWAKEN
    return g, pa, pb


def test_energy_free_once_and_turn_reset(make_game, db):
    """觉醒·日和坊免单：每回合一次，消耗能量时改为不消耗（名额每半回合重置）。"""
    g, pa, pb = _rihefang_game(make_game, db, awakened=True)
    s = pa.shikigami[IDX]
    s.energy = 6
    g.apply({"op": "play_card", "uid": give(g, 0, BURST_SPELL).uid,
             "play_method": "burst"})
    assert s.energy == 6                   # 免单：不消耗
    assert pa.ext["energy_free_turn"] is False
    g.apply({"op": "play_card", "uid": give(g, 0, BURST_SPELL).uid,
             "play_method": "burst"})
    assert s.energy == 4                   # 名额已耗：正常支付 2
    pass_turns(g, 2)                       # 半回合重置名额
    assert pa.ext["energy_free_turn"] is True
    g.apply({"op": "play_card", "uid": give(g, 0, BURST_SPELL).uid,
             "play_method": "burst"})
    assert s.energy == 4                   # 再次免单


def test_energy_life_substitute(make_game, db):
    """日和坊生命代偿：能量不足的差额由在场日和坊以生命代偿（直扣生命、非伤害、
    代偿后生命不能降到 0——会降到 0 则支付失败、方式不可用）。"""
    g, pa, pb = _rihefang_game(make_game, db)
    s = pa.shikigami[IDX]
    rf = pa.shikigami[1]
    s.energy = 1
    g.apply({"op": "play_card", "uid": give(g, 0, BURST_SPELL).uid,
             "play_method": "burst"})
    assert s.energy == 0                   # 能量清零
    assert rf.health == rf.max_health - 1  # 差额 1 由生命代偿
    s.energy = 0
    rf.health = 2                          # 爆能 2 需全额代偿 2 → 生命会降到 0
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": give(g, 0, BURST_SPELL).uid,
                 "play_method": "burst"})
    assert rf.health == 2                  # 未支付、未扣血


# ---------- 动态能量光环（stat_aura：人多势众 / 烟雾缭绕） ----------

ENERGY_AURA_FORM = 10010173    # 假人多势众：进场登记 energy_power 光环（divisor=2）
SUMMON_SPELL = 10010174        # 假召唤分身牌
IDS_AURA_FORM = 10010175       # 假烟雾缭绕：进场登记 ids_energy_power 光环
FENSHEN = 10020499             # 假"烟烟罗的分身"召唤物 id


def test_energy_power_aura_scales_with_energy(make_game, db):
    """人多势众（stat_aura kind="energy_power"）：持有者每有 divisor(2) 点能量 +1 力量
    ——读取时求值（_gain_energy/_spend_energy 变化点触发刷新）；形态离场光环移除。"""
    db.cards[ENERGY_AURA_FORM] = F.card(
        ENERGY_AURA_FORM, shikigami=SID, card_type="form", level=1,
        form_power=3, form_health=5, token=True,
        steps=[F.Step(op="stat_aura", kind="energy_power", divisor=2)])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    g.apply({"op": "play_card", "uid": give(g, 0, ENERGY_AURA_FORM).uid})
    base = s.eff_power                     # 形态 3 力量
    g._gain_energy(pa, IDX, 5)             # 5//2=2
    assert s.eff_power == base + 2
    g._spend_energy(pa, IDX, 4)            # 1//2=0：消耗点同步刷新
    assert s.eff_power == base
    g._destroy_form(pa, IDX, "test")       # 形态离场：光环移除
    g._gain_energy(pa, IDX, 4)
    assert s.eff_power == 3                # 回基础身材


def test_ids_energy_power_scales_with_summon_energy(make_game, db):
    """烟雾缭绕（stat_aura kind="ids_energy_power" ids=[分身] scope="form"）：匹配实体
    每有 divisor(1) 点能量 +1 力量（读实体自身能量）；形态离场光环移除。"""
    db.shikigami[FENSHEN] = F.shiki(FENSHEN, name="烟烟罗的分身", kind="summon",
                                    power=2, health=3)
    db.cards[SUMMON_SPELL] = F.card(
        SUMMON_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="summon", shikigami=FENSHEN)])
    db.cards[IDS_AURA_FORM] = F.card(
        IDS_AURA_FORM, shikigami=SID, card_type="form", level=1,
        form_power=2, form_health=5, token=True,
        steps=[F.Step(op="stat_aura", kind="ids_energy_power", ids=[FENSHEN],
                      scope="form")])
    g, pa, pb = _game(make_game)
    g.apply({"op": "play_card", "uid": give(g, 0, SUMMON_SPELL).uid})
    fen = pa.shikigami[-1]                 # 召唤物（最末座次，召唤即进战斗区）
    assert fen.id == FENSHEN and fen.eff_power == 2
    g.apply({"op": "play_card", "uid": give(g, 0, IDS_AURA_FORM).uid})
    g._gain_energy(pa, len(pa.shikigami) - 1, 3)
    assert fen.eff_power == 2 + 3          # 每有 1 能量 +1 力量
    g._destroy_form(pa, IDX, "test")       # 形态离场：光环移除
    g._refresh_stat_auras()
    assert fen.eff_power == 2


# ---------- 召唤复制身材/能量 + 分身复制法术 + 额外使用复制（不夜之火末轮） ----------

MIRROR_DMG = 10010176        # 假投射 2 法术（被分身复制）
MIRROR_AWAKEN = 10010177     # 假觉醒法术（不触发复制）
COPY_PROJ = 10010178         # 假投射 2（use_card_copy 目标）
COPY_COMBAT = 10010179       # 假战斗牌（use_card_copy 目标）
COPY_SRC = 10010180          # 假"额外使用"源牌（链式两 step）
COPY_SRC_COMBAT = 10010181   # 假"额外使用战斗牌"源牌


def test_summon_inherit_stats_and_energy_ratio(make_game, db):
    """summon inherit_stats/energy_ratio（烟烟罗的分身"召唤时具有与烟烟罗相同的力量和
    生命以及一半的能量"）：快照来源当前全部身材（维护者定案——当前力量含临时/光环、
    当前生命上限、当前生命值含受伤不满），以永久修正落地（不进 dyn 缓存，光环重算
    不丢失）；能量按比例向下取整；召唤进场也算移动（ext move_count_turn，前置修正）。"""
    db.shikigami[FENSHEN] = F.shiki(FENSHEN, name="烟烟罗的分身", kind="summon",
                                    power=2, health=4)
    db.cards[SUMMON_SPELL] = F.card(
        SUMMON_SPELL, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="summon", shikigami=FENSHEN, inherit_stats=True,
                      energy_ratio=0.5)])
    g, pa, pb = _game(make_game)
    src = pa.shikigami[IDX]                  # 3/4
    src.perm_power = 2
    src.perm_health = 1
    src.temp_power = 5                       # 临时增益也复制（定案）
    src.health = 3                           # 当前生命值含受伤不满（上限 4+1=5）
    src.energy = 5
    g.apply({"op": "play_card", "uid": give(g, 0, SUMMON_SPELL).uid})
    fen = pa.shikigami[-1]
    assert fen.eff_power == 3 + 2 + 5        # 当前力量含永久+临时
    assert fen.max_health == 5               # 当前生命上限
    assert fen.health == 3                   # 当前生命值（不满照抄）
    assert fen.energy == 2                   # floor(5 × 0.5)
    assert fen.ext["move_count_turn"] == 1   # 召唤进场也算移动
    g._refresh_stat_auras()
    assert fen.eff_power == 10               # 继承部分为静态基值，光环重算不丢失


def test_mirror_spell_copies_active_spell_play(make_game, db):
    """mirror_spell（烟烟罗的分身"会复制她使用的法术牌"）：在场分身监听 on_card_played
    （card_type=spell、shikigami=烟烟罗、player=self、subtype_not=awaken）——主动使用
    与自动使用（维护者定案放开）的法术都被凭空复制再结算一次；复制自身的事件带
    mirror_copy 标记不再触发（防递归）；觉醒牌不触发。"""
    db.shikigami[FENSHEN] = F.shiki(
        FENSHEN, name="烟烟罗的分身", kind="summon", power=2, health=4,
        ability=F.block(
            F.Step(op="mirror_spell"),
            when="on_card_played",
            condition={"card_type": "spell", "shikigami": SID, "player": "self",
                       "subtype_not": "awaken"}))
    db.cards[SUMMON_SPELL] = F.card(
        SUMMON_SPELL, shikigami=100103, level=1, token=True,
        steps=[F.Step(op="summon", shikigami=FENSHEN)])
    db.cards[MIRROR_DMG] = F.card(
        MIRROR_DMG, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="projectile"))])
    db.cards[MIRROR_AWAKEN] = F.card(
        MIRROR_AWAKEN, shikigami=SID, subtype="awaken", tags=["awaken"], level=1,
        token=True)
    db.cards[COPY_SRC] = F.card(
        COPY_SRC, shikigami=100103, level=1, token=True, steps=[
            F.Step(op="use_card_copy", card_id=MIRROR_DMG)])
    g, pa, pb = _game(make_game)
    pa.shikigami[2].level = 1                # 召唤牌属 100103（2 号位默认 0 级）
    g.apply({"op": "play_card", "uid": give(g, 0, SUMMON_SPELL).uid})
    assert pa.shikigami[-1].id == FENSHEN    # 召唤牌属 100103：不被分身复制
    g.apply({"op": "play_card", "uid": give(g, 0, MIRROR_DMG).uid})
    assert pb.health == 30 - 4               # 原牌 2 + 分身复制 2
    g.apply({"op": "play_card", "uid": give(g, 0, MIRROR_AWAKEN).uid})
    assert pb.health == 30 - 4               # 觉醒牌不触发复制
    # 自动使用也触发（定案放开）：use_card_copy 凭空使用 → 分身再复制一次；
    # 分身复制自身带 mirror_copy 标记不连锁（否则无限递归）
    g.apply({"op": "play_card", "uid": give(g, 0, COPY_SRC).uid})
    assert pb.health == 30 - 4 - 2 - 2       # 自动使用 2 + 分身复制 2，无连锁


def test_use_card_copy_spell_chain_and_combat(make_game, db):
    """use_card_copy（爆能"{额外使用'X'}"类）：凭空复制指定牌自动使用——法术牌基础方式
    结算，链式"再额外使用"= 并列 step（两次投射复制共 4）；战斗牌走基础方式战斗流程
    （来源式神进战斗区发起战斗，不耗鬼火/出击次数）。"""
    db.cards[COPY_PROJ] = F.card(
        COPY_PROJ, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="projectile"))])
    db.cards[COPY_COMBAT] = F.card(
        COPY_COMBAT, shikigami=SID, level=1, token=True, card_type="combat")
    db.cards[COPY_SRC] = F.card(
        COPY_SRC, shikigami=SID, level=1, token=True, steps=[
            F.Step(op="use_card_copy", card_id=COPY_PROJ),
            F.Step(op="use_card_copy", card_id=COPY_PROJ)])
    db.cards[COPY_SRC_COMBAT] = F.card(
        COPY_SRC_COMBAT, shikigami=SID, level=1, token=True, steps=[
            F.Step(op="use_card_copy", card_id=COPY_COMBAT)])
    g, pa, pb = _game(make_game)
    g.apply({"op": "play_card", "uid": give(g, 0, COPY_SRC).uid})
    assert pb.health == 30 - 4               # 两次投射复制
    pa.orb = 9
    assaults_before = pa.assaults_left
    g.apply({"op": "play_card", "uid": give(g, 0, COPY_SRC_COMBAT).uid})
    assert pb.health == 30 - 4 - 3           # 战斗牌复制：来源 3 力量打空战斗区牌手
    assert pa.combat_index == IDX            # 来源式神已进战斗区
    assert pa.orb == 8                       # 复制不耗鬼火（仅源牌费 1）
    assert pa.assaults_left == assaults_before   # 不耗出击次数


def test_energy_gain_at_cap_emits_zero_amount(make_game, db):
    """满上限仍发"时"时机（维护者定案，对照满生命治疗）：能量 10 时再获得，
    on_energy_gained 照常发出（amount=0、old==new），能量不变；emit_event=False
    通道（烟烟罗类追加）与 n=0 调用不发事件；体系内只有"时"没有"后"
    （无 on_after_energy_gained，对照 on_heal/on_after_heal 双时机）。"""
    g, pa, pb = _charge_game(make_game, db)
    s = pa.shikigami[IDX]
    s.energy = 10
    n = len(g.history)
    assert g._gain_energy(pa, IDX, 3) == 0 and s.energy == 10
    assert "on_energy_gained" in g.history[n:]         # 满上限仍发"时"（amount=0）
    n = len(g.history)
    assert g._gain_energy(pa, IDX, 1, emit_event=False) == 0
    assert "on_energy_gained" not in g.history[n:]     # 追加通道不发（防递归）
    n = len(g.history)
    assert g._gain_energy(pa, IDX, 0) == 0
    assert "on_energy_gained" not in g.history[n:]     # n=0 非获得尝试：不发
