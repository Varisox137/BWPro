"""倒计时系统 / 形态能力 / 投射 / 鼓舞 / 随机生成测试。

对应 thoughts.txt 一目连（倒计时形态）、杀念（随机生成）卡面与 rules.md ch12 锚点版倒计时。
测试辅助卡使用衍生号段（51+）；3 号位（100104）充当一目连，0 号位（100101）充当妖刀姬。

注意：敌方战斗区式神会在其己方回合开始退回准备区，因此"倒计时命中战斗区"的用例
须在敌方回合内（两次 end_turn 之间）用 debug_move 补位。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import ichimokuren, move, pass_turns, play, po_form

T = F.T
SID = 100104   # 一目连位
IDX = 3
YAO = 100101   # 妖刀姬位

PO = 10010451       # 风符·破型：倒计时2，投射3
GALE = 10010457     # 罡风型法术


def _form(db, cid, *, countdown=None, cd_steps=(), abilities=None,
          keywords=(), token=True, level=1):
    db.cards[cid] = F.card(
        cid, shikigami=SID, card_type="form", level=level,
        form_power=3, form_health=6, countdown=countdown,
        countdown_effects=(F.block(*cd_steps) if cd_steps else None),
        abilities=list(abilities or []), keywords=list(keywords), token=token)
    return cid


def _setup(db, make_game, level=3):
    """一目连位就位（基础能力 + 手动升级 + 充足鬼火）。"""
    ichimokuren(db)
    g = make_game()
    pa = g.state.players[0]
    s = pa.shikigami[IDX]
    s.level = level
    pa.orb = 9
    return g, pa, s


# ---------- 倒计时循环与投射 ----------

def test_po_countdown_cycle_projectile(db, make_game):
    """风符·破：己方回合开始 -1，归零先重置再触发；投射优先命中战斗区式神。"""
    cid = po_form(db)
    g, pa, s = _setup(db, make_game, level=1)
    b = g.state.players[1].shikigami[0]  # 3/4
    play(g, 0, cid)
    assert s.countdown == 2
    g.apply({"op": "end_turn"})  # B 回合开始
    move(g, 1, 0)               # B 式神驻留战斗区（其回合开始才会退回）
    g.apply({"op": "end_turn"})  # A 第 2 回合开始：2→1
    assert s.countdown == 1
    assert b.health == 4
    g.apply({"op": "end_turn"})
    move(g, 1, 0)
    g.apply({"op": "end_turn"})  # A 第 3 回合开始：1→0，重置为 2 后触发
    assert s.countdown == 2
    assert b.health == 1         # 投射 3 命中战斗区式神
    g.apply({"op": "end_turn"})
    move(g, 1, 0)
    g.apply({"op": "end_turn"})  # A 第 4 回合开始：2→1
    assert s.countdown == 1
    g.apply({"op": "end_turn"})
    move(g, 1, 0)
    g.apply({"op": "end_turn"})  # A 第 5 回合开始：再次触发
    assert b.defeated            # 第二次投射击杀
    assert s.countdown == 2      # 循环继续


def test_po_projectile_falls_back_to_player(db, make_game):
    """风符·破：敌方战斗区为空时，投射退回敌方牌手。"""
    cid = po_form(db)
    g, pa, s = _setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0  # 后手补偿 5 甲清零
    play(g, 0, cid)
    s.countdown = 1  # 快进倒计时
    pass_turns(g, 2)      # A 第 2 回合开始触发
    assert pl.health == 27
    assert s.countdown == 2


def test_hu_grants_player_shield(db, make_game):
    """风符·护：倒计时触发，己方牌手获得 5 护甲（回合开始清甲之后）。"""
    cid = _form(db, 10010452, countdown=2, cd_steps=[
        F.Step(op="gain_shield", amount=5, target=T(kind="all", pool="self_player"))])
    g, pa, s = _setup(db, make_game, level=1)
    play(g, 0, cid)
    s.countdown = 1
    pass_turns(g, 2)
    assert pa.shield == 5


# ---------- 鼓舞（出击加成） ----------

def test_shi_boost_consumed_by_assault_only(db, make_game):
    """风符·势：鼓舞登记出击加成；战斗牌不消耗；出击时力量本次生效、护甲保留。"""
    cid = _form(db, 10010453, countdown=2, cd_steps=[
        F.Step(op="basic_boost", power=3, shield=3)])
    combat_cid = 10010454
    db.cards[combat_cid] = F.card(combat_cid, shikigami=SID, card_type="combat",
                                  steps=[], token=True)
    g, pa, s = _setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0
    play(g, 0, cid)
    s.countdown = 1
    pass_turns(g, 2)
    assert pa.assault_boosts == [{"power": 3, "shield": 3}]
    play(g, 0, combat_cid)      # 战斗牌直击牌手：不消耗出击加成
    assert pa.assault_boosts == [{"power": 3, "shield": 3}]
    assert pl.health == 27       # 未获加成：形态身材 3 力量直击
    g.apply({"op": "assault", "index": IDX})
    assert pa.assault_boosts == []
    assert pl.health == 21       # 27 - (3+3)：力量加成生效
    assert s.shield == 3         # 护甲保留
    assert s.eff_power == 3      # 力量加成战后核销（保留形态身材）


# ---------- 离场/消灭触发（一目连基础能力） ----------

def test_galewind_destroy_form_triggers_and_draws(db, make_game):
    """罡风：消灭一目连的形态触发其倒计时（破投射 3），并抽两张牌。"""
    po_form(db)
    db.cards[GALE] = F.card(
        GALE, shikigami=SID, card_type="spell", level=2, keywords=["fast"],
        steps=[F.Step(op="destroy_form", target=T(kind="self")),
               F.Step(op="draw", count=2, target=T(kind="all", pool="self_player"))],
        token=True)
    g, pa, s = _setup(db, make_game, level=2)
    b = g.state.players[1].shikigami[0]
    play(g, 0, PO)
    move(g, 1, 0)               # A 回合内敌方战斗区驻留
    n0 = len(pa.hand)
    play(g, 0, GALE)
    assert s.form is None
    assert b.health == 1         # 离场触发破的投射
    assert len(pa.hand) == n0 + 2  # give+1、play-1、draw+2


def test_replace_form_triggers_countdown(db, make_game):
    """形态替换：旧形态（破）离场同样触发倒计时效果。"""
    po_form(db)
    plain = _form(db, 10010458)  # 无倒计时形态
    g, pa, s = _setup(db, make_game, level=1)
    b = g.state.players[1].shikigami[0]
    play(g, 0, PO)
    move(g, 1, 0)
    play(g, 0, plain)
    assert s.form.id == plain
    assert s.countdown is None   # 新形态无倒计时
    assert b.health == 1         # 破离场时投射 3


def test_defeat_form_destruction_still_triggers(db, make_game):
    """一目连气绝：形态随之消灭并清除倒计时；消灭形态早于能力离场（rules.md ch7 step 3/6），
    倒计时效果仍触发。"""
    po_form(db)
    g, pa, s = _setup(db, make_game, level=1)
    b = g.state.players[1].shikigami[0]
    play(g, 0, PO)
    move(g, 1, 0)               # 敌方战斗区驻留（A 回合内不移除）
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()  # 直调伤害管线后手动排空（on_form_destroyed/on_shikigami_defeated 为延时时机）
    assert s.defeated
    assert s.form is None
    assert s.countdown is None
    assert b.health == 1         # 形态被气绝消灭仍触发投射 3


# ---------- 湮 / 龙 / 瞬 ----------

def test_yan_destroys_enemy_combat(db, make_game):
    """风符·湮：倒计时触发，直接消灭敌方战斗区式神。"""
    cid = _form(db, 10010455, countdown=2, level=3, cd_steps=[
        F.Step(op="destroy", target=T(kind="all", pool="enemy_combat"))])
    g, pa, s = _setup(db, make_game, level=3)
    pb = g.state.players[1]
    b = pb.shikigami[0]
    play(g, 0, cid)
    s.countdown = 1
    g.apply({"op": "end_turn"})  # B 回合
    move(g, 1, 0)
    g.apply({"op": "end_turn"})  # A 回合开始：湮触发
    assert b.defeated
    assert pb.combat_index is None


def test_long_target_count_scales(db, make_game):
    """风符·龙：实例计数器——每次触发后目标数 +1（1 → 2 个随机敌方角色）。"""
    cid = _form(db, 10010456, countdown=2, level=3, cd_steps=[
        F.Step(op="random_damage", amount=6, pool="enemy_character",
               count={"mod": "count", "base": 1}),
        F.Step(op="add_mod", to="instance", key="count", amount=1)])

    def total_damage(pb) -> int:
        return sum(20 - es.health for es in pb.shikigami) + (40 - pb.health)

    g, pa, s = _setup(db, make_game, level=3)
    pb = g.state.players[1]
    pb.shield = 0
    pb.health = 40
    for es in pb.shikigami:
        es.level = 1
        es.health = 20
    play(g, 0, cid)
    s.countdown = 1
    pass_turns(g, 2)                  # 第 1 次触发：1 目标 6 点
    assert s.form.mods["count"] == 1
    assert total_damage(pb) == 6
    s.countdown = 1
    pass_turns(g, 2)                  # 第 2 次触发：2 目标各 6 点（无放回）
    assert s.form.mods["count"] == 2
    assert total_damage(pb) == 18


def test_shun_self_destruct_at_turn_end(db, make_game):
    """风符·瞬：回合结束自毁（形态能力块）；无倒计时效果，离场为空操作。"""
    cid = _form(db, 10010459, level=2, keywords=["fast"], abilities=[
        F.EffectBlock(when="on_turn_end",
                      steps=[F.Step(op="destroy_form", target=T(kind="self"))])])
    g, pa, s = _setup(db, make_game, level=2)
    pl = g.state.players[1]
    pl.shield = 0
    play(g, 0, cid)
    assert s.form is not None
    g.apply({"op": "end_turn"})  # A 回合结束：自毁
    assert s.form is None
    assert pl.health == 30       # 瞬无倒计时效果：一目连能力空操作不报错


# ---------- 觉醒·一目连 / 杀念（随机生成） ----------

def test_awaken_ichimokuren_generate_and_attach_trigger(db, make_game):
    """觉醒·一目连：+2 永久力量、生成 1 张形态牌；觉醒后形态进场也触发倒计时。"""
    po_form(db, token=False)  # 生成池只取非衍生卡
    awk = 10010460
    db.cards[awk] = F.card(
        awk, shikigami=SID, card_type="spell", level=2, subtype="awaken",
        steps=[F.Step(op="buff_power", amount=2, perm=True, target=T(kind="self")),
               F.Step(op="generate", shikigami="self", card_type="form", count=1)],
        abilities=[
            F.EffectBlock(when="on_form_attached", condition={"target_shikigami": "self"},
                          steps=[F.Step(op="trigger_form_countdown")]),
            F.EffectBlock(when="on_form_destroyed", condition={"target_shikigami": "self"},
                          steps=[F.Step(op="trigger_form_countdown")]),
        ],
        token=True)
    g, pa, s = _setup(db, make_game, level=2)
    b = g.state.players[1].shikigami[0]
    play(g, 0, awk)
    assert s.awakened == awk
    assert s.eff_power == 4      # 2 基础 + 2 永久
    gen = [c for c in pa.hand if c.id == PO]
    assert len(gen) == 1         # 生成 1 张一目连形态牌
    move(g, 1, 0)
    g.apply({"op": "play_card", "uid": gen[0].uid})
    assert s.form is gen[0]
    assert s.countdown == 2
    assert b.health == 1         # 进场即触发破的投射


def test_sanen_generates_three_combat_cards(db, make_game):
    """杀念：随机生成 3 张妖刀姬的战斗牌置入手牌（可重复）。"""
    c1, c2 = 10010152, 10010153
    for c in (c1, c2):
        db.cards[c] = F.card(c, shikigami=YAO, card_type="combat", steps=[], token=False)
    sanen = 10010154
    db.cards[sanen] = F.card(
        sanen, shikigami=YAO, card_type="spell", level=3,
        steps=[F.Step(op="generate", shikigami="self", card_type="combat", count=3)],
        token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.shikigami[0].level = 3
    pa.orb = 3
    n0 = len(pa.hand)
    play(g, 0, sanen)
    assert len(pa.hand) == n0 + 3  # give+1、play-1、生成+3
    gen = pa.hand[-3:]
    assert {c.id for c in gen} <= {c1, c2}
    assert all(db.cards[c.id].card_type == "combat" for c in gen)
