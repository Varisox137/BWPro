"""倒计时主题测试：式神级倒计时框架与新 op（原 test_shikigami_countdown.py）
+ 倒计时形态/投射/鼓舞/随机生成（原 test_countdown_forms.py）。

对应 docs/rules.md ch12 倒计时增减事件流程（修订版归零顺序：先即时插入结算、
再重置/移除）与 thoughts.txt 答复 (1)（一名式神至多 1 个倒计时能力、替换制）、
一目连（倒计时形态）与杀念（随机生成）卡面。
0 号位（100101）充当倒计时能力式神（开局自动 1 级；对局开始的回合开始阶段已
为其倒计时 -1 一次，故 initial=2 的能力开局后 countdown == 1）；
倒计时形态部分 3 号位（100104）充当一目连，0 号位（100101）充当妖刀姬。

注意：敌方战斗区式神会在其己方回合开始退回准备区，因此"倒计时命中战斗区"的用例
须在敌方回合内（两次 end_turn 之间）用 debug_move 补位。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import give, ichimokuren, move, pass_turns, play, po_form

T = F.T
CD = 100101     # 倒计时能力式神位（0 号位）
IDX = 0
CD2 = 100102    # 副式神位（1 号位）
IDX2 = 1


# ==========================================================================
# 式神级倒计时框架 + 新 op（原 test_shikigami_countdown.py）
# ==========================================================================

def _cd_ability(db, initial=2, steps=None, sid=CD):
    """给式神设置倒计时能力块（EffectBlock.countdown 非 None = 倒计时能力块）。"""
    db.shikigami[sid].ability = F.EffectBlock(
        countdown=initial,
        steps=steps if steps is not None else [
            F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player"))])


def _game(make_game):
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    g.state.players[1].shield = 0  # 清掉后手补偿护甲，便于观察伤害
    return g, pa


def _cd_form(db, cid, *, sid=CD, countdown=None, cd_steps=(), level=1):
    db.cards[cid] = F.card(
        cid, shikigami=sid, card_type="form", level=level,
        form_power=3, form_health=6, countdown=countdown,
        countdown_effects=(F.block(*cd_steps) if cd_steps else None), token=True)
    return cid


def _delta_card(db, cid, amount, *, sid=CD):
    db.cards[cid] = F.card(
        cid, shikigami=sid, card_type="spell", level=1, token=True,
        steps=[F.Step(op="countdown_delta", amount=amount, target=T(kind="self"))])
    return cid


# ---------- 注册 / 替换 ----------

def test_ability_countdown_registered_at_game_start(db, make_game):
    """能力进场（对局开始）：基础能力的倒计时块注册三要素；首个回合开始已 -1。"""
    _cd_ability(db, initial=2)
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    assert s.countdown == 1                # 2 - 1（对局开始的回合开始阶段）
    assert s.countdown_initial == 2
    assert s.countdown_block is db.shikigami[CD].ability
    assert s.countdown_once is False
    assert s.countdown_source == CD        # 基础能力来源 = 式神 id


def test_set_countdown_replaces_ability(db, make_game):
    """set_countdown：替换当前倒计时能力（initial/once 按参数，来源 = 式神 id）。"""
    _cd_ability(db, initial=2)
    cid = 10010151
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="set_countdown", target=T(kind="self"), initial=3, once=True,
                      steps=[{"op": "draw", "count": 1}])])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    assert s.countdown == 3
    assert s.countdown_initial == 3
    assert s.countdown_once is True
    assert s.countdown_source == CD


# ---------- 归零流程：先结算后重置 / once 移除 / history ----------

def test_zero_resolves_before_reset(db, make_game):
    """归零先即时插入结算（此时倒计时仍为 0，块内对自身 countdown_delta 修正为 -0）、
    再重置为初值；生效后向 countdown_history 追加来源 id。"""
    _cd_ability(db, initial=2, steps=[
        F.Step(op="countdown_delta", amount=-1, target=T(kind="self")),  # 结算中：-0 空操作
        F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player")),
    ])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    pass_turns(g, 2)                       # A 第 2 回合开始：1→0，先结算后重置
    assert pb.health == 28                 # 倒计时效果 2 伤生效
    assert s.countdown == 2                # 循环型重置为初值（若先重置再结算，块内 -1 会留下 1）
    assert pa.ext["countdown_history"] == [CD]


def test_once_countdown_removed_after_trigger(db, make_game):
    """一次型（once）倒计时：生效后移除而非重置。"""
    cid = 10010151
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="set_countdown", target=T(kind="self"), initial=1, once=True,
                      steps=[{"op": "damage", "amount": 3,
                              "target": {"kind": "all", "pool": "enemy_player"}}])])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    play(g, 0, cid)
    assert s.countdown == 1
    pass_turns(g, 2)                       # A 第 2 回合开始：1→0，生效后移除
    assert pb.health == 27
    assert s.countdown is None
    assert s.countdown_block is None
    assert s.countdown_source is None
    assert pa.ext["countdown_history"] == [CD]


def test_countdown_replaced_during_zero_not_reset(db, make_game):
    """归零结算期间能力被替换（块内 set_countdown）：旧能力不再重置。"""
    _cd_ability(db, initial=2, steps=[
        F.Step(op="set_countdown", target=T(kind="self"), initial=5, steps=[]),
    ])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pass_turns(g, 2)                       # 归零结算中替换为 initial=5 的新倒计时
    assert s.countdown == 5                # 旧能力（initial 2）未重置
    assert s.countdown_initial == 5
    assert pa.ext["countdown_history"] == [CD]  # 生效的是旧能力，记账其来源


# ---------- countdown_delta：立即归零 / 增加 ----------

def test_countdown_delta_immediate_zero_and_increase(db, make_game):
    """countdown_delta 减到 ≤0 立即走归零流程（与回合开始批次同路径）；增加则延长。"""
    _cd_ability(db, initial=2)
    dec = _delta_card(db, 10010152, -1)
    inc = _delta_card(db, 10010153, 2)
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    assert s.countdown == 1
    play(g, 0, dec)                        # 1→0：立即结算并重置
    assert pb.health == 28
    assert s.countdown == 2
    play(g, 0, inc)                        # 2→4：增加不触发
    assert s.countdown == 4
    assert pb.health == 28


# ---------- 形态倒计时：注册替换 / 离场清除 / history ----------

def test_form_replaces_ability_countdown(db, make_game):
    """形态结附授予的倒计时替换能力倒计时；形态离场仅清除形态授予的倒计时——
    期间被 set_countdown 替换过的倒计时不受形态离场影响。"""
    _cd_ability(db, initial=2)
    fm = _cd_form(db, 10010154, countdown=3)
    plain = _cd_form(db, 10010155)            # 无倒计时形态
    sc = 10010156
    db.cards[sc] = F.card(
        sc, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="set_countdown", target=T(kind="self"), initial=5, steps=[])])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, fm)
    assert s.countdown == 3                # 形态倒计时替换能力倒计时
    assert s.countdown_source == fm
    play(g, 0, sc)                         # 再被 set_countdown 替换（来源变为式神 id）
    assert s.countdown == 5
    assert s.countdown_source == CD
    play(g, 0, plain)                      # 旧形态离场：不清除非形态授予的倒计时
    assert s.form.id == plain
    assert s.countdown == 5


def test_form_countdown_zero_records_history(db, make_game):
    """形态倒计时归零：来源记账为形态牌 id；离场后倒计时清除。"""
    fm = _cd_form(db, 10010154, countdown=1, cd_steps=[
        F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player"))])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    play(g, 0, fm)
    pass_turns(g, 2)                       # A 第 2 回合开始：1→0
    assert pb.health == 28
    assert s.countdown == 1                # 循环型重置
    assert pa.ext["countdown_history"] == [fm]


# ---------- 气绝清除 / 复活与升级重新注册 / 觉醒替换 ----------

def test_defeat_clears_and_revive_reregisters(db, make_game):
    """气绝清除倒计时能力；复活时能力进场重新注册（复活当回合的回合开始批次仍会 -1）。"""
    _cd_ability(db, initial=2)
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated
    assert s.countdown is None
    assert s.countdown_block is None
    s.revive_countdown = 1
    pass_turns(g, 2)                       # A 回合开始：复活（重新注册 2）→ 同批倒计时 -1
    assert not s.defeated
    assert s.countdown == 1
    assert s.countdown_source == CD


def test_upgrade_to_level1_registers(db, make_game):
    """升 1 级在场：0 级式神的能力进场，注册其倒计时能力块。"""
    _cd_ability(db, initial=3, sid=CD2)
    g = make_game(auto_skip_upgrade=False)
    pa = g.state.players[0]
    s = pa.shikigami[IDX2]
    assert s.level == 0 and s.countdown is None
    g.apply({"op": "upgrade", "index": IDX2})
    assert s.level == 1
    assert s.countdown == 3
    assert s.countdown_source == CD2


def test_awaken_replaces_countdown(db, make_game):
    """觉醒替换：注册觉醒牌的倒计时能力块（来源 = 觉醒牌 id），替换基础能力倒计时。"""
    _cd_ability(db, initial=2)
    awk = 10010160
    db.cards[awk] = F.card(
        awk, shikigami=CD, card_type="spell", level=2, subtype="awaken",
        steps=[], token=True,
        abilities=[F.EffectBlock(countdown=1, steps=[
            F.Step(op="damage", amount=1, target=T(kind="all", pool="enemy_player"))])])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    s.level = 2
    play(g, 0, awk)
    assert s.awakened == awk
    assert s.countdown == 1                # 觉醒倒计时（initial 1）替换基础倒计时（initial 2）
    assert s.countdown_source == awk
    pass_turns(g, 2)                       # A 第 2 回合开始：1→0，觉醒倒计时生效
    assert pb.health == 29
    assert s.countdown == 1                # 循环型重置
    assert pa.ext["countdown_history"] == [awk]


# ---------- recast_recorded（大天狗记录法术模式，端到端） ----------

def test_recast_recorded_spell(db, make_game):
    """使用法术→记录并注册 once 倒计时；归零凭空生成同名牌免费自动使用（非从手牌）。

    自动使用照常发出 on_card_played，可再次触发记录能力重新注册（大天狗循环）。
    """
    spell = 10010251
    db.cards[spell] = F.card(
        spell, shikigami=CD2, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player"))])
    db.shikigami[CD2].ability = F.EffectBlock(
        when="on_card_played", condition={"player": "self"},
        steps=[F.Step(op="set_countdown", target=T(kind="self"), initial=1,
                      once=True, record=True,
                      steps=[{"op": "recast_recorded"}])])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX2]
    pb = g.state.players[1]
    s.level = 1
    play(g, 0, spell)
    assert pb.health == 28                 # 主动使用的 2 伤
    assert s.countdown == 1                # 记录并注册 once 倒计时
    assert s.countdown_once is True
    assert s.ext["recorded_card"] == spell
    pass_turns(g, 2)                       # A 第 2 回合开始：归零 → 凭空自动使用
    assert pb.health == 26                 # 自动使用的 2 伤（不耗鬼火、不从手牌）
    assert pa.ext["countdown_history"] == [CD2]
    assert s.countdown == 1                # 自动使用再次触发记录能力：重新注册
    assert s.ext["recorded_card"] == spell


# ---------- retreat / discard / gain_orb ----------

def test_retreat_moves_back_to_bench(db, make_game):
    """retreat：战斗区式神移回准备区（准备区式神为空操作）。"""
    cid = 10010158
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="retreat", target=T(kind="self"))])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    move(g, 0, IDX)
    assert pa.combat_index == IDX
    play(g, 0, cid)
    assert pa.combat_index is None
    assert s.in_play                       # 退回准备区，非气绝/离场
    play(g, 0, cid)                        # 准备区中为空操作（不报错）
    assert s.in_play


def test_discard_by_shikigami(db, make_game):
    """discard：弃掉手牌中来源式神所属的牌，其他式神的牌保留。"""
    cid = 10010159
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="discard", shikigami="self")])
    g, pa = _game(make_game)
    kept = give(g, 0, 10010201)            # 100102 的牌：应保留
    play(g, 0, cid)
    assert kept in pa.hand
    assert all(db.cards[c.id].shikigami != CD for c in pa.hand)
    assert any(c.id == cid for c in pa.graveyard)


def test_gain_orb(db, make_game):
    """gain_orb：控制者获得鬼火，发出 on_orb_changed。"""
    cid = 10010161
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="gain_orb", amount=2)])
    g, pa = _game(make_game)
    pa.orb = 1
    play(g, 0, cid)                        # 1 - 1（费用）+ 2 = 2
    assert pa.orb == 2


# ---------- Step.condition：不满足跳过该步 ----------

def test_step_condition_skips_step(db, make_game):
    """Step 级条件：结算时求值，不满足则跳过该 step（其余步骤照常）。"""
    cid = 10010162
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[
            F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player"),
                   condition={"active": "self"}),       # 己方回合：满足，执行
            F.Step(op="damage", amount=5, target=T(kind="all", pool="enemy_player"),
                   condition={"active": "opponent"}),   # 不满足：跳过
        ])
    g, pa = _game(make_game)
    pb = g.state.players[1]
    play(g, 0, cid)
    assert pb.health == 28                 # 仅第一步生效（30 - 2，第二步被跳过）


# ==========================================================================
# 倒计时形态 / 投射 / 鼓舞 / 随机生成（原 test_countdown_forms.py）
# ==========================================================================

LSID = 100104   # 一目连位
LIDX = 3
YAO = 100101   # 妖刀姬位

PO = 10010451       # 风符·破型：倒计时2，投射3
GALE = 10010457     # 罡风型法术


def _lk_form(db, cid, *, countdown=None, cd_steps=(), abilities=None,
             keywords=(), token=True, level=1):
    db.cards[cid] = F.card(
        cid, shikigami=LSID, card_type="form", level=level,
        form_power=3, form_health=6, countdown=countdown,
        countdown_effects=(F.block(*cd_steps) if cd_steps else None),
        abilities=list(abilities or []), keywords=list(keywords), token=token)
    return cid


def _lk_setup(db, make_game, level=3):
    """一目连位就位（基础能力 + 手动升级 + 充足鬼火）。"""
    ichimokuren(db)
    g = make_game()
    pa = g.state.players[0]
    s = pa.shikigami[LIDX]
    s.level = level
    pa.orb = 9
    return g, pa, s


# ---------- 倒计时循环与投射 ----------

def test_countdown_cycle_projectile(db, make_game):
    """风符·破：己方回合开始 -1，归零先重置再触发；投射优先命中战斗区式神。"""
    cid = po_form(db)
    g, pa, s = _lk_setup(db, make_game, level=1)
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


def test_projectile_falls_back_to_player(db, make_game):
    """风符·破：敌方战斗区为空时，投射退回敌方牌手。"""
    cid = po_form(db)
    g, pa, s = _lk_setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0  # 后手补偿 5 甲清零
    play(g, 0, cid)
    s.countdown = 1  # 快进倒计时
    pass_turns(g, 2)      # A 第 2 回合开始触发
    assert pl.health == 27
    assert s.countdown == 2


def test_player_shield_on_countdown(db, make_game):
    """风符·护：倒计时触发，己方牌手获得 5 护甲（回合开始清甲之后）。"""
    cid = _lk_form(db, 10010452, countdown=2, cd_steps=[
        F.Step(op="gain_shield", amount=5, target=T(kind="all", pool="self_player"))])
    g, pa, s = _lk_setup(db, make_game, level=1)
    play(g, 0, cid)
    s.countdown = 1
    pass_turns(g, 2)
    assert pa.shield == 5


# ---------- 鼓舞（出击加成） ----------

def test_assault_boost_assault_only(db, make_game):
    """风符·势：鼓舞登记出击加成；战斗牌不消耗；出击时力量本次生效、护甲保留。"""
    cid = _lk_form(db, 10010453, countdown=2, cd_steps=[
        F.Step(op="basic_boost", power=3, shield=3)])
    combat_cid = 10010454
    db.cards[combat_cid] = F.card(combat_cid, shikigami=LSID, card_type="combat",
                                  steps=[], token=True)
    g, pa, s = _lk_setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0
    play(g, 0, cid)
    s.countdown = 1
    pass_turns(g, 2)
    assert pa.assault_boosts == [{"power": 3, "shield": 3}]
    play(g, 0, combat_cid)      # 战斗牌直击牌手：不消耗出击加成
    assert pa.assault_boosts == [{"power": 3, "shield": 3}]
    assert pl.health == 27       # 未获加成：形态身材 3 力量直击
    g.apply({"op": "assault", "index": LIDX})
    assert pa.assault_boosts == []
    assert pl.health == 21       # 27 - (3+3)：力量加成生效
    assert s.shield == 3         # 护甲保留
    assert s.eff_power == 3      # 力量加成战后核销（保留形态身材）


# ---------- 鼓舞扩展旗标（不夜之火批次：不知火三 op） ----------

def test_boost_on_combat_card_consumes_boost(db, make_game):
    """不夜之舞（boost_on_combat_card 旗标）：战斗牌发起的攻击也获得并消耗出击加成；
    无旗标时战斗牌不消耗（既有行为）。"""
    flag_cid = 10010455
    db.cards[flag_cid] = F.card(flag_cid, shikigami=LSID, token=True,
                                steps=[F.Step(op="boost_on_combat_card")])
    combat_cid = 10010454
    db.cards[combat_cid] = F.card(combat_cid, shikigami=LSID, card_type="combat",
                                  steps=[], token=True)
    g, pa, s = _lk_setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0
    pa.assault_boosts = [{"power": 2, "shield": 0}]
    play(g, 0, combat_cid)                   # 无旗标：不消耗（2 力量直击）
    assert pl.health == 28
    assert pa.assault_boosts == [{"power": 2, "shield": 0}]
    play(g, 0, flag_cid)                     # 登记旗标
    play(g, 0, combat_cid)                   # 战斗牌消耗鼓舞：2+2 力量直击
    assert pl.health == 28 - 4
    assert pa.assault_boosts == []


def test_boost_no_consume_keeps_boosts(db, make_game):
    """离殇之舞（boost_no_consume 旗标）：出击照常获得出击加成，但加成不清空——
    下次出击仍生效。"""
    flag_cid = 10010456
    db.cards[flag_cid] = F.card(flag_cid, shikigami=LSID, token=True,
                                steps=[F.Step(op="boost_no_consume")])
    g, pa, s = _lk_setup(db, make_game, level=1)
    pl = g.state.players[1]
    pl.shield = 0
    pa.assault_boosts = [{"power": 2, "shield": 0}]
    play(g, 0, flag_cid)
    g.apply({"op": "assault", "index": LIDX})   # 2+2 力量直击
    assert pl.health == 26
    assert pa.assault_boosts == [{"power": 2, "shield": 0}]  # 未消耗
    pass_turns(g, 2)
    g.apply({"op": "assault", "index": LIDX})   # 下回合出击仍生效
    assert pl.health == 22
    assert pa.assault_boosts == [{"power": 2, "shield": 0}]


def test_inspire_bonus_adds_to_basic_boost(db, make_game):
    """觉醒·不知火（inspire_bonus 旗标）：[鼓舞]（basic_boost）数值额外 +1/+1；
    旗标可叠加。"""
    flag_cid = 10010458
    db.cards[flag_cid] = F.card(flag_cid, shikigami=LSID, token=True,
                                steps=[F.Step(op="inspire_bonus", power=1, shield=1)])
    boost_cid = 10010459
    db.cards[boost_cid] = F.card(boost_cid, shikigami=LSID, token=True,
                                 steps=[F.Step(op="basic_boost", power=2, shield=0)])
    g, pa, s = _lk_setup(db, make_game, level=1)
    play(g, 0, flag_cid)
    play(g, 0, boost_cid)
    assert pa.assault_boosts == [{"power": 3, "shield": 1}]  # 2+1 / 0+1
    play(g, 0, flag_cid)                     # 旗标叠加：再 +1/+1
    play(g, 0, boost_cid)
    assert pa.assault_boosts[-1] == {"power": 4, "shield": 2}


# ---------- 离场/消灭触发（一目连基础能力） ----------

def test_destroy_form_triggers_countdown_and_draw(db, make_game):
    """罡风：消灭一目连的形态触发其倒计时（破投射 3），并抽两张牌。"""
    po_form(db)
    db.cards[GALE] = F.card(
        GALE, shikigami=LSID, card_type="spell", level=2, keywords=["fast"],
        steps=[F.Step(op="destroy_form", target=T(kind="self")),
               F.Step(op="draw", count=2, target=T(kind="all", pool="self_player"))],
        token=True)
    g, pa, s = _lk_setup(db, make_game, level=2)
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
    plain = _lk_form(db, 10010458)  # 无倒计时形态
    g, pa, s = _lk_setup(db, make_game, level=1)
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
    g, pa, s = _lk_setup(db, make_game, level=1)
    b = g.state.players[1].shikigami[0]
    play(g, 0, PO)
    move(g, 1, 0)               # 敌方战斗区驻留（A 回合内不移除）
    g.deal_to_shikigami(Ref(player=0, shikigami=LIDX), 99, None)
    g._drain_queue()  # 直调伤害管线后手动排空（on_form_destroyed/on_shikigami_defeated 为延时时机）
    assert s.defeated
    assert s.form is None
    assert s.countdown is None
    assert b.health == 1         # 形态被气绝消灭仍触发投射 3


# ---------- 湮 / 龙 / 瞬 ----------

def test_destroy_enemy_combat(db, make_game):
    """风符·湮：倒计时触发，直接消灭敌方战斗区式神。"""
    cid = _lk_form(db, 10010455, countdown=2, level=3, cd_steps=[
        F.Step(op="destroy", target=T(kind="all", pool="enemy_combat"))])
    g, pa, s = _lk_setup(db, make_game, level=3)
    pb = g.state.players[1]
    b = pb.shikigami[0]
    play(g, 0, cid)
    s.countdown = 1
    g.apply({"op": "end_turn"})  # B 回合
    move(g, 1, 0)
    g.apply({"op": "end_turn"})  # A 回合开始：湮触发
    assert b.defeated
    assert pb.combat_index is None


def test_instance_counter_target_scaling(db, make_game):
    """风符·龙：实例计数器——每次触发后目标数 +1（1 → 2 个随机敌方角色）。"""
    cid = _lk_form(db, 10010456, countdown=2, level=3, cd_steps=[
        F.Step(op="random_damage", amount=6, pool="enemy_character",
               count={"mod": "count", "base": 1}),
        F.Step(op="add_mod", to="instance", key="count", amount=1)])

    def total_damage(pb) -> int:
        return sum(20 - es.health for es in pb.shikigami) + (40 - pb.health)

    g, pa, s = _lk_setup(db, make_game, level=3)
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


def test_form_self_destruct_turn_end(db, make_game):
    """风符·瞬：回合结束自毁（形态能力块）；无倒计时效果，离场为空操作。"""
    cid = _lk_form(db, 10010459, level=2, keywords=["fast"], abilities=[
        F.EffectBlock(when="on_turn_end",
                      steps=[F.Step(op="destroy_form", target=T(kind="self"))])])
    g, pa, s = _lk_setup(db, make_game, level=2)
    pl = g.state.players[1]
    pl.shield = 0
    play(g, 0, cid)
    assert s.form is not None
    g.apply({"op": "end_turn"})  # A 回合结束：自毁
    assert s.form is None
    assert pl.health == 30       # 瞬无倒计时效果：一目连能力空操作不报错


# ---------- 觉醒·一目连 / 杀念（随机生成） ----------

def test_awaken_generate_and_attach_trigger_countdown(db, make_game):
    """觉醒·一目连：+2 永久力量、生成 1 张形态牌；觉醒后形态进场也触发倒计时。"""
    po_form(db, token=False)  # 生成池只取非衍生卡
    awk = 10010460
    db.cards[awk] = F.card(
        awk, shikigami=LSID, card_type="spell", level=2, subtype="awaken",
        steps=[F.Step(op="buff_power", amount=2, perm=True, target=T(kind="self")),
               F.Step(op="generate", shikigami="self", card_type="form", count=1)],
        abilities=[
            F.EffectBlock(when="on_form_attached", condition={"target_shikigami": "self"},
                          steps=[F.Step(op="trigger_form_countdown")]),
            F.EffectBlock(when="on_form_destroyed", condition={"target_shikigami": "self"},
                          steps=[F.Step(op="trigger_form_countdown")]),
        ],
        token=True)
    g, pa, s = _lk_setup(db, make_game, level=2)
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


def test_generate_three_combat_cards(db, make_game):
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
