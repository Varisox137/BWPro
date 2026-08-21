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


# ==========================================================================
# 倒计时事件（月夜幻响批次：on_countdown_proc / on_countdown_reduced）
# ==========================================================================

CD3 = 100103    # 第三式神位（2 号位）
IDX3 = 2


def _attack_countdown(db, initial=2, sid=CD, extra_steps=()):
    """倒计时归零 = 发起一次攻击的能力块（山风型；extra_steps 在攻击前执行）。"""
    db.shikigami[sid].ability = F.EffectBlock(
        countdown=initial,
        steps=[*extra_steps, F.Step(op="launch_attack")])


def _register(make_game_game, pi, si):
    """手动升级后补注册倒计时能力（测试直接改 level 不经 level_up 通道）。"""
    make_game_game._register_ability_countdown(pi, si)


def test_countdown_proc_buffs_before_launched_attack(db, make_game):
    """on_countdown_proc（烈/刚型"当触发[倒计时]能力时"）：即时时机先于归零块结算——
    形态能力授予的永久 +1/+1 与护甲赶上归零块发起的攻击。"""
    _attack_countdown(db, initial=2)
    cid = 10010171
    db.cards[cid] = F.card(
        cid, shikigami=CD, card_type="form", level=1, token=True,
        form_power=3, form_health=4,
        abilities=[F.block(
            F.Step(op="buff_power", amount=1, perm=True, target=T(kind="self")),
            F.Step(op="buff_health", amount=1, perm=True, target=T(kind="self")),
            F.Step(op="gain_shield", amount=4, target=T(kind="self")),
            when="on_countdown_proc", condition={"shikigami_shikigami": "self"})])
    g, pa = _game(make_game)
    pb = g.state.players[1]
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    pass_turns(g, 2)                     # A 第 2 回合开始：倒计时归零 → 先授予再攻击
    assert s.perm_power == 1 and s.perm_health == 1
    assert pb.health == 26               # 攻击 3+1=4（若授予晚于攻击则为 3）
    assert s.shield == 4                 # 敌方战斗区为空无反击：护甲保留


def test_countdown_proc_next_battle_keyword(db, make_game):
    """on_countdown_proc + grant_keyword scope="next_battle"（斩型"本次攻击获得[必杀]"）：
    战斗外授予挂账，绑定下一次作为攻击者发起的战斗（该次倒计时发起的战斗本身），
    战斗终止点核销（维护者定案(6)）。"""
    _attack_countdown(db, initial=2)
    cid = 10010172
    db.cards[cid] = F.card(
        cid, shikigami=CD, card_type="form", level=1, token=True,
        form_power=3, form_health=4,
        abilities=[F.block(
            F.Step(op="grant_keyword", keyword="lethal", scope="next_battle",
                   target=T(kind="self")),
            when="on_countdown_proc", condition={"shikigami_shikigami": "self"})])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    pb = g.state.players[1]
    pb.shikigami[0].level = 1
    play(g, 0, cid)
    pass_turns(g, 1)
    move(g, 1, 0)                        # B0（3/4）驻战斗区
    pass_turns(g, 1)                     # A 第 2 回合开始：归零 → 必杀攻击 B0
    assert pb.shikigami[0].defeated      # 3 伤未致死，[必杀]令其气绝
    assert not any("lethal" in lst for lst in
                   (s.keywords, s.one_shot_keywords, s.perm_keywords))  # 战斗后核销
    assert "next_battle_keywords" not in s.ext


def test_next_battle_immunity_full_battle(db, make_game):
    """grant_immunity scope="next_battle"（觉醒·山风型"本次战斗免疫战斗伤害"）：
    该次战斗全程免疫战斗伤害（反击也免疫）；战斗结束后不再免疫（维护者定案(8)）。"""
    _attack_countdown(db, initial=2, extra_steps=[
        F.Step(op="grant_immunity", scope="next_battle", target=T(kind="self"))])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]                # 3/4
    pb = g.state.players[1]
    pb.shikigami[0].level = 1
    pass_turns(g, 1)
    move(g, 1, 0)                        # B0（3/4）驻战斗区
    pass_turns(g, 1)                     # 归零：免疫授予 → 攻击（反击被免疫）
    b0 = pb.shikigami[0]
    assert b0.health == 1                # 攻击 3 照常
    assert s.health == 4                 # 反击 3 被免疫
    assert not s.immunities              # 战斗终止点清除
    assert "next_battle_immunities" not in s.ext
    g.apply({"op": "assault", "index": IDX})  # 同回合再次攻击：免疫已过期
    assert s.health == 1                 # 反击 3 正常命中


def test_countdown_reduced_original_attack_buff(db, make_game):
    """on_countdown_reduced + attack_buff 动态力量 {event: original}（势型"当倒计时
    减少时获得等量力量直到下次攻击后"）：按原始减少量授予（定案(5)），timing: insert
    赶在归零块攻击前生效，攻击后核销。"""
    _attack_countdown(db, initial=5)     # 开局后倒计时 4
    cid = 10010173
    db.cards[cid] = F.card(
        cid, shikigami=CD, card_type="form", level=1, token=True,
        form_power=3, form_health=6,
        abilities=[F.block(
            F.Step(op="attack_buff", power={"event": "original"},
                   target=T(kind="self")),
            when="on_countdown_reduced", timing="insert",
            condition={"shikigami_shikigami": "self"})])
    _delta_card(db, 10010174, -7)        # 减少 7（实际只能减 4）
    g, pa = _game(make_game)
    pb = g.state.players[1]
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    play(g, 0, 10010174)                 # 倒计时 4 → 归零（original=7, actual=4）
    assert pb.health == 20               # 攻击 3+7=10（按原始值 7 而非实际值 4）
    assert s.temp_power == 0             # 攻击后到期强化已核销
    assert s.countdown == 5              # 循环型重置


def test_countdown_overkill_memo_and_holders_enhance(db, make_game):
    """突型：countdown_delta 动态减少量 {base: 2, countdown_holders: friendly_others,
    negate}（[增强]按山风以外持倒计时能力的未气绝式神像数）；过量部分
    （original - actual）经 ctx.memo["countdown_overkill"] 转化为等量临时力量/生命
    （定案(3)：非永久持续性增益）。"""
    _cd_ability(db, initial=5)           # 开局后倒计时 4；归零块 = 打敌方牌手 2
    _cd_ability(db, initial=3, sid=CD2)
    cid = 10010175
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="countdown_delta",
                      amount={"base": 2, "countdown_holders": "friendly_others",
                              "negate": True},
                      target=T(kind="self")),
               F.Step(op="buff_power", amount={"memo": "countdown_overkill"},
                      target=T(kind="self")),
               F.Step(op="buff_health", amount={"memo": "countdown_overkill"},
                      target=T(kind="self"))])
    g, pa = _game(make_game)
    pb = g.state.players[1]
    s = pa.shikigami[IDX]
    pa.shikigami[IDX2].level = 1
    _register(g, 0, IDX2)                # CD2 成为倒计时持有者（增强计数 1）
    s.countdown = 2                      # 减少 3 > 剩余 2：过量 1
    play(g, 0, cid)
    assert pb.health == 28               # 倒计时归零效果 2 伤
    assert s.temp_power == 1 and s.temp_health == 1   # 过量 1 → +1/+1（临时非永久）
    assert s.countdown == 5              # 循环型重置


def test_countdown_sum_repeat(db, make_game):
    """岚型：repeat count={"countdown_sum": true} = 己方所有式神当前倒计时总和
    （含目标自身，结算时一次性取值），每次重复是一次独立减少动作（各发一次
    on_countdown_reduced）。"""
    _cd_ability(db, initial=5)           # 开局后倒计时 4
    _cd_ability(db, initial=3, sid=CD2)
    cid = 10010176
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="repeat", count={"countdown_sum": True},
                      steps=[{"op": "countdown_delta", "amount": -1,
                              "target": {"kind": "self"}}])])
    g, pa = _game(make_game)
    pb = g.state.players[1]
    s = pa.shikigami[IDX]
    pa.shikigami[IDX2].level = 1
    _register(g, 0, IDX2)                # CD2 倒计时 3：总和 4+3=7
    n = len(g.history)
    play(g, 0, cid)                      # 4→0（第 4 次归零：打 2、重置 5）→ 5→2
    assert pb.health == 28
    assert s.countdown == 2
    assert g.history[n:].count("on_countdown_reduced") == 7


def test_awakened_countdown_share(db, make_game):
    """觉醒·山风型共享：任何己方减少倒计时效果（含在场能力来源）对山风以外
    未气绝己方式神的倒计时减少，对山风造成等量效果——按"每次减少动作"延迟结算
    （源效果块完毕后，定案(8)）；无倒计时能力的式神被减少也发事件（actual=0）
    照样共享；山风气绝时减少其气绝倒计时；回合开始批次自然减少（natural）不共享。"""
    _cd_ability(db, initial=5)           # 山风位：开局后倒计时 4
    _cd_ability(db, initial=3, sid=CD3)
    AW = 10010199
    db.cards[AW] = F.card(AW, shikigami=CD, level=3, token=True, abilities=[F.block(
        F.Step(op="countdown_delta", amount={"event": "original", "negate": True},
               target=T(kind="self"), condition={"holder_defeated": False}),
        F.Step(op="countdown_delta", revive=True,
               amount={"event": "original", "negate": True},
               target=T(kind="self"), condition={"holder_defeated": True}),
        when="on_countdown_reduced", trigger_when_defeated=True,
        condition={"natural_not": True, "shikigami_side": "friendly",
                   "shikigami_not_shikigami": CD})])
    # 余音型减少牌（属 CD2，只减 CD3 的倒计时，避开源式神与山风）
    cid = 10010252
    db.cards[cid] = F.card(
        cid, shikigami=CD2, level=1, token=True,
        steps=[F.Step(op="countdown_delta", amount=-1,
                      target=T(kind="all", pool="friendly_shikigami",
                               shikigami=CD3))])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    s.awakened = AW                      # 直接置觉醒态（不经觉醒牌使用流程）
    pa.shikigami[IDX2].level = 1
    pa.shikigami[IDX3].level = 1
    _register(g, 0, IDX3)                # CD3 倒计时 3
    n = len(g.history)
    play(g, 0, cid)                      # CD3 3→2：一次减少动作 → 共享山风 4→3
    play(g, 0, cid)                      # CD3 2→1 → 共享山风 3→2
    assert s.countdown == 2
    assert g.history[n:].count("on_countdown_reduced") == 4   # 余音 2 次 + 共享应用 2 次
    # 能力来源（在场块，ctx.card 为空）也共享：任何己方减少倒计时效果（定案扩域）
    from core.model import ExecContext
    blk = F.block(F.Step(op="countdown_delta", amount=-1, target=T(kind="self")))
    g._resolve_block(blk, ExecContext(controller=0, source=Ref(player=0, shikigami=IDX3),
                                      is_ability=True))
    g._drain_queue()
    assert pa.shikigami[IDX3].countdown == 3  # 能力减少本身生效（归零：打 2 敌方牌手后重置）
    assert g.state.players[1].health == 28
    assert s.countdown == 1                   # 山风共享 2→1
    # 无倒计时能力的未气绝式神被减少也发事件（actual=0、original=减少量、状态不变），照样共享
    pa.shikigami[3].level = 1
    seen = []
    orig_emit = g.emit
    def _emit_spy(name, **payload):
        if name == "on_countdown_reduced":
            seen.append(payload)
        return orig_emit(name, **payload)
    g.emit = _emit_spy
    blk2 = F.block(F.Step(op="countdown_delta", amount=-1,
                          target=T(kind="all", pool="friendly_shikigami", shikigami=100104)))
    g._resolve_block(blk2, ExecContext(controller=0, source=Ref(player=0, shikigami=IDX3),
                                       is_ability=True))
    g._drain_queue()
    g.emit = orig_emit
    assert pa.shikigami[3].countdown is None  # 无倒计时式神状态不变
    ev = next(p for p in seen if p["shikigami"].shikigami == 3)
    assert ev["original"] == 1 and ev["actual"] == 0
    assert s.countdown == 5  # 共享 1→0 归零：山风能力生效（打 2）后重置初值 5
    assert g.state.players[1].health == 26
    # 山风气绝时：共享减少其气绝倒计时（复活倒计时）
    s.countdown = None
    s.countdown_block = None
    s.defeated = True
    s.revive_countdown = 3
    pa.shikigami[IDX3].countdown = 2
    play(g, 0, cid)                      # CD3 2→1 → 共享：复活倒计时 3→2
    assert s.revive_countdown == 2
    assert s.defeated


def _kagura3_like(db, sid=CD):
    """觉醒神乐歌类倒计时能力（initial=3）：归零使其他己方式神 +1/+1（永久）并倒计时 -1。"""
    db.shikigami[sid].ability = F.EffectBlock(
        countdown=3,
        steps=[F.Step(op="buff_power", amount=1, perm=True,
                      target=T(kind="all", pool="friendly_others")),
               F.Step(op="buff_health", amount=1, perm=True,
                      target=T(kind="all", pool="friendly_others")),
               F.Step(op="countdown_delta", amount=-1,
                      target=T(kind="all", pool="friendly_others"))])


def test_awakened_countdown_share_delay_horizon(db, make_game):
    """觉醒·山风复制延时界 = 引起该次减少的结算单元（定案）：在场能力块引起的减少
    在该能力块结算完即复制；卡牌直接效果引起的减少在整张牌结算完才复制
    （能力块 drain 不冲刷卡牌级延时项）。

    验收流程（thoughts.txt）：余音型牌（妖琴师位 -3 → 归零插入觉醒神乐歌块；
    然后其他己方 -1）。复制结算前 (山风, 大天狗) 快照应为
    [(3,1),(2,1),(3,2),(3,2),(2,2)]——前两个大天狗=1（能力块界）、后三个=2
    （卡牌界）；最终山风 countdown == 1。
    """
    YAO, DTG, REN, SF = 100101, 100102, 100103, 100104  # 座 0-3：妖琴师/大天狗/一目连位/山风
    _kagura3_like(db, sid=YAO)                          # 觉醒神乐歌型（初值 3）
    _cd_ability(db, initial=2, sid=DTG)                 # 大天狗位（初值 2）
    _cd_ability(db, initial=2, sid=REN)                 # 一目连位（初值 2）
    AW = 10010499
    db.cards[AW] = F.card(AW, shikigami=SF, level=3, token=True, abilities=[F.block(
        F.Step(op="countdown_delta", amount={"event": "original", "negate": True},
               target=T(kind="self")),
        when="on_countdown_reduced", timing="queue",
        condition={"natural_not": True, "shikigami_side": "friendly",
                   "shikigami_not_shikigami": SF})])
    cid = 10010152  # 余音型：自身 -3，然后其他己方 -1
    db.cards[cid] = F.card(
        cid, shikigami=YAO, level=1, token=True,
        steps=[F.Step(op="countdown_delta", amount=-3, target=T(kind="self")),
               F.Step(op="countdown_delta", amount=-1,
                      target=T(kind="all", pool="friendly_others"))])
    g, pa = _game(make_game)
    yao, dtg, ren, sf = (pa.shikigami[i] for i in range(4))
    for i in (1, 2, 3):
        pa.shikigami[i].level = 1
    _register(g, 0, 1)                       # 大天狗倒计时 2
    _register(g, 0, 2)                       # 一目连倒计时 2
    g._register_countdown(sf, initial=3, once=False, source=SF,
                          block=F.EffectBlock(steps=[F.Step(op="launch_attack")]))
    yao.countdown, ren.countdown, sf.countdown = 1, 1, 1   # cd=1（初值 3/2/3）
    sf.awakened = AW
    snaps = []
    aw_block = db.cards[AW].abilities[0]
    orig = g._resolve_pending
    def _spy(pend):
        if pend.block is aw_block:
            snaps.append((sf.countdown, dtg.countdown))
        return orig(pend)
    g._resolve_pending = _spy
    play(g, 0, cid)
    assert snaps == [(3, 1), (2, 1), (3, 2), (3, 2), (2, 2)]
    assert sf.countdown == 1


class _ImmunitySpy(list):
    """捕获 append 的免疫条目（next_battle 消费默认键断言用）。"""

    def __init__(self, seen: list) -> None:
        self._seen = seen

    def append(self, entry) -> None:
        self._seen.append(dict(entry))
        super().append(entry)


def test_next_battle_immunity_nested_default(db, make_game):
    """next_battle 免疫消费时 nested 缺省 True（维护者答复(10) 定案：默认覆盖本战斗内
    的嵌套战斗；挂账可显式 nested: false 收窄为仅本战斗）——grant_immunity 挂账本身
    不写 nested 键，消费（_resolve_combat）写入缺省 True。"""
    _attack_countdown(db, initial=2, extra_steps=[
        F.Step(op="grant_immunity", scope="next_battle", target=T(kind="self"))])
    g, pa = _game(make_game)
    s = pa.shikigami[IDX]
    seen = []
    s.immunities = _ImmunitySpy(seen)
    pass_turns(g, 2)                     # 归零：免疫授予挂账 → 归零块攻击消费
    consumed = [e for e in seen if e.get("battle") is not None]
    assert consumed and all(e.get("nested") is True for e in consumed)
    assert not s.immunities              # 战斗终止点清除（消费条目随战斗结束移除）


def test_next_battle_lethal_nested_effective(db, make_game):
    """斩型"本次攻击获得[必杀]"（维护者改判：范围与觉醒·山风免疫一致——持续到该次
    战斗事件结束后，含期间插入的嵌套战斗）：next_battle 授予回归统一关键字通道
    （战斗开始授予实例、外层战斗终止点核销），嵌套战斗内同来源伤害同样触发必杀。"""
    g, pa = _game(make_game)
    src = Ref(player=0, shikigami=0)
    b0 = g.state.players[1].shikigami[0]
    b1 = g.state.players[1].shikigami[1]
    s0 = pa.shikigami[0]
    cls = g._grant_keyword(s0, "lethal")   # 战斗开始消费 next_battle 挂账（统一通道）
    g._battle_stack.append(1)                        # 外层战斗
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 1, src, kind="combat")
    assert b0.defeated                               # 1 伤未致死，必杀令气绝
    g._battle_stack.append(2)                        # 嵌套战斗
    g.deal_to_shikigami(Ref(player=1, shikigami=1), 1, src, kind="combat")
    assert b1.defeated                               # 嵌套战斗内必杀同样生效（改判）
    g._remove_keyword(s0, "lethal", cls)             # 外层战斗终止点核销
    assert not any("lethal" in lst for lst in
                   (s0.keywords, s0.one_shot_keywords, s0.perm_keywords))


# ==========================================================================
# 进场顺序（entry_order）：再进场排本队最后、回合开始倒计时批次按进场顺序
# ==========================================================================

PAPER_DUMMY = 100199  # 纸人式变形物 dummy id


def _kagura_like(db, sid=CD2):
    """神乐歌类倒计时能力（initial=2）：归零使其他己方式神 +1/+1（永久）并倒计时 -1。"""
    db.shikigami[sid].ability = F.EffectBlock(
        countdown=2,
        steps=[F.Step(op="buff_power", amount=1, perm=True,
                      target=T(kind="all", pool="friendly_others")),
               F.Step(op="buff_health", amount=1, perm=True,
                      target=T(kind="all", pool="friendly_others")),
               F.Step(op="countdown_delta", amount=-1,
                      target=T(kind="all", pool="friendly_others"))])


def _once_attack_countdown(g, pi=0, si=IDX):
    """山风类"倒计时1发起一次攻击"：手动注册一次型（once 生效后移除，避免归零重置
    后在同批次被二次处理），初值 1。"""
    g._register_countdown(
        g.state.players[pi].shikigami[si], initial=1, once=True, source=CD,
        block=F.EffectBlock(steps=[F.Step(op="launch_attack")]))


def test_turn_start_countdown_entry_order_after_transform(db, make_game):
    """进场顺序规则（维护者定案）：再进场（变形为变形物、解除变形还原）排到本队最后，
    回合开始倒计时批次按进场顺序处理——山风类（倒计时1，座位在前）被变形再还原后，
    神乐歌类（倒计时2，座位在后）先归零：+1/+1 与倒计时 -1 先于山风本次攻击结算
    （攻击按增益后力量造成 4 伤而非 3 伤）。"""
    _kagura_like(db)
    db.shikigami[PAPER_DUMMY] = F.shiki(PAPER_DUMMY, kind="transform",
                                        name="纸人", power=1, health=1)
    g, pa = _game(make_game)
    pb = g.state.players[1]
    pa.shikigami[IDX2].level = 1
    _register(g, 0, IDX2)                # 神乐歌类倒计时 2（未经开局批次减少）
    _once_attack_countdown(g)            # 山风类倒计时 1（一次型）
    g._transform_shikigami(pa, IDX, PAPER_DUMMY)   # 戏谑套索式变形
    assert pa.shikigami[IDX].entry_order == 5      # 再进场：排本队最后（初始 1-4）
    pass_turns(g, 2)                     # A 第 2 回合开始：山风变形中跳过；神乐歌 2→1
    assert pa.shikigami[IDX2].countdown == 1
    g._untransform(0, IDX)               # 回合结束还原（直接调用模拟）
    s0 = pa.shikigami[IDX]
    assert s0.id == CD and s0.countdown == 1       # 快照还原（倒计时保留）
    assert s0.entry_order == 6                     # 还原进场再排最后
    assert s0.entry_order > pa.shikigami[IDX2].entry_order
    pass_turns(g, 2)                     # A 第 3 回合开始：神乐歌先归零 → 山风吃 +1/+1 再攻击
    assert pb.health == 26               # 攻击 3+1=4（顺序未变则为 3 → 27）
    assert s0.perm_power == 1            # +1/+1 已结算
    assert s0.countdown is None          # 一次型生效后移除（未被批次二次处理）


def test_turn_start_countdown_entry_order_seat_default(db, make_game):
    """对照：未变形时进场顺序 = 座位顺序——山风类（座位在前）倒计时先处理：
    本次攻击吃不到神乐歌的 +1/+1（3 伤）；神乐歌次回合才归零。"""
    _kagura_like(db)
    g, pa = _game(make_game)
    pb = g.state.players[1]
    pa.shikigami[IDX2].level = 1
    _register(g, 0, IDX2)
    _once_attack_countdown(g)
    pass_turns(g, 2)                     # A 第 2 回合开始：山风（座位前）先归零攻击
    assert pb.health == 27               # 攻击 3（无增益）
    assert pa.shikigami[IDX].perm_power == 0
    assert pa.shikigami[IDX2].countdown == 1
    pass_turns(g, 2)                     # A 第 3 回合开始：神乐歌归零 → +1/+1（已无倒计时可减）
    assert pa.shikigami[IDX].perm_power == 1
    assert pb.health == 27               # 无第二次攻击（一次型已移除）


# ---------- 进场顺序关联点（维护者答复 (1)(2)(3)(4)(5)动态/(6)） ----------

def test_revive_keeps_entry_order(db, make_game):
    """答复(1)：气绝复活不改变实体进场顺序（entry_order 保持原值）。"""
    g, pa = _game(make_game)
    orders = [s.entry_order for s in pa.shikigami]
    pa.shikigami[IDX].health = 0
    g.check_defeated(Ref(player=0, shikigami=IDX))
    assert pa.shikigami[IDX].defeated
    g._revive(pa, 0, IDX)
    assert [s.entry_order for s in pa.shikigami] == orders


def test_summon_entry_order_newest(db, make_game):
    """答复(2)：召唤物 = 新进场者，entry_order 排本队最后。"""
    tom = 100199
    db.shikigami[tom] = F.shiki(tom, kind="summon", name="番茄", power=1, health=1)
    cid = 10010151
    db.cards[cid] = F.card(cid, token=True, steps=[F.Step(op="summon", shikigami=tom)])
    g, pa = _game(make_game)
    play(g, 0, cid)
    s = pa.shikigami[-1]
    assert s.id == tom and s.kind == "summon"
    assert s.entry_order == max(x.entry_order for x in pa.shikigami[:-1]) + 1


def test_replace_entry_order_newest(db, make_game):
    """答复(3)：式神替换（replace）的替换物 = 新进场者，entry_order 排本队最后。"""
    into = 100198
    db.shikigami[into] = F.shiki(into, kind="replace", name="替身", power=2, health=2)
    cid = 10010151
    db.cards[cid] = F.card(
        cid, token=True, steps=[F.Step(op="replace", into=into, target=T(kind="self"))])
    g, pa = _game(make_game)
    old_ability_seq = pa.shikigami[IDX].ability_entry["ability"]
    play(g, 0, cid)
    s = pa.shikigami[IDX]
    assert s.id == into
    assert s.entry_order == max(x.entry_order for x in pa.shikigami if x is not s) + 1
    # 答复(6) 精神延伸：替换物的能力同样重新进场（经 _register_ability_countdown
    # 记新能力进场序号——替换物无能力块时也记录）
    assert s.ability_entry["ability"] > old_ability_seq


def test_ability_entry_order_drives_trigger(db, make_game):
    """答复(4)：同时机能力按"能力进场序号"排序而非座位——后登记者后触发；
    气绝复活 = 能力重新进场（序号排到最后），触发顺序随之反转。"""
    db.shikigami[CD].ability = F.block(when="on_draw")
    db.shikigami[CD2].ability = F.block(when="on_draw")
    g, pa = _game(make_game)
    pa.shikigami[IDX2].level = 1
    _register(g, 0, IDX)                   # A 能力先登记（序号小）
    _register(g, 0, IDX2)                  # B 能力后登记（序号大）
    g.emit("on_draw", player=0, count=1)
    assert [(p.ctx.controller, p.ctx.source.shikigami) for p in g.queue
            if p.ctx.controller == 0] == [(0, IDX), (0, IDX2)]
    g._drain_queue()
    pa.shikigami[IDX].health = 0
    g.check_defeated(Ref(player=0, shikigami=IDX))
    g._revive(pa, 0, IDX)                  # 复活：A 能力重新进场，序号排到 B 之后
    g.emit("on_draw", player=0, count=1)
    assert [(p.ctx.controller, p.ctx.source.shikigami) for p in g.queue
            if p.ctx.controller == 0] == [(0, IDX2), (0, IDX)]


def test_countdown_batch_dynamic_new_entrant(db, make_game):
    """答复(5)：回合开始倒计时批次动态取序——批次结算中被复活（倒计时重新进场）
    的式神当轮即被处理（静态快照式批次则不会）。"""
    db.shikigami[100103].ability = F.EffectBlock(
        countdown=1, steps=[F.Step(op="launch_attack")])   # C：倒计时1 发起攻击
    g, pa = _game(make_game)
    pb = g.state.players[1]
    pa.shikigami[IDX2].level = 1
    pa.shikigami[2].level = 1
    # A（座位 0，倒计时1 一次型）：复活 C
    g._register_countdown(
        pa.shikigami[IDX], initial=1, once=True, source=CD,
        block=F.EffectBlock(steps=[F.Step(
            op="revive", target=T(kind="all", pool="friendly_defeated"))]))
    # B（座位 1，倒计时1 一次型）：打敌方牌手 5
    g._register_countdown(
        pa.shikigami[IDX2], initial=1, once=True, source=CD2,
        block=F.EffectBlock(steps=[F.Step(
            op="damage", amount=5, target=T(kind="all", pool="enemy_player"))]))
    # C 批次开始前气绝（复活倒计时拉高，排除自然复活干扰）
    pa.shikigami[2].health = 0
    g.check_defeated(Ref(player=0, shikigami=2))
    pa.shikigami[2].revive_countdown = 99
    pass_turns(g, 2)                     # A 第 2 回合开始：A 复活 C → B 打 5 → C 当轮攻击 2
    assert pa.shikigami[2].defeated is False
    assert pb.health == 23               # 30 - 5 - 2（快照式批次 C 不处理 → 25）


def test_untransform_ability_reentry_sequence(db, make_game):
    """答复(6)：解除变形还原时，基础/觉醒能力 → 形态能力 → 卡牌赋予的延迟能力
    依次重新进场（各自记录新的递增能力进场序号）。"""
    db.shikigami[PAPER_DUMMY] = F.shiki(PAPER_DUMMY, kind="transform",
                                        name="纸人", power=1, health=1)
    form_cid = 10010153
    db.cards[form_cid] = F.card(form_cid, shikigami=CD, card_type="form", level=1,
                                form_power=3, form_health=6, token=True)
    delay_cid = 10010154
    db.cards[delay_cid] = F.card(
        delay_cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="delay_grant", when="on_draw")])
    g, pa = _game(make_game)
    play(g, 0, form_cid)
    play(g, 0, delay_cid)
    s0 = pa.shikigami[IDX]
    old_form = s0.ability_entry["form"]
    old_delay = s0.delayed[0]["seq"]
    g._transform_shikigami(pa, IDX, PAPER_DUMMY)
    g._untransform(0, IDX)
    s0 = pa.shikigami[IDX]
    new_ability = s0.ability_entry["ability"]
    assert new_ability > old_delay                        # 各能力全部重新进场（新序号）
    assert s0.ability_entry["form"] > new_ability         # 形态能力在基础能力之后进场
    assert s0.delayed[0]["seq"] > s0.ability_entry["form"]  # 延迟能力最后进场
