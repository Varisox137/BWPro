"""式神级倒计时框架测试（A2）+ 新 op（countdown_delta/set_countdown/recast_recorded/
retreat/discard/gain_orb）+ Step.condition 跳过行为。

对应 docs/rules.md ch12 倒计时增减事件流程（修订版归零顺序：先即时插入结算、
再重置/移除）与 thoughts.txt 答复 (1)（一名式神至多 1 个倒计时能力、替换制）。
0 号位（100101）充当倒计时能力式神（开局自动 1 级；对局开始的回合开始阶段已
为其倒计时 -1 一次，故 initial=2 的能力开局后 countdown == 1）。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import give, move, pass_turns, play

T = F.T
CD = 100101     # 倒计时能力式神位（0 号位）
IDX = 0
CD2 = 100102    # 副式神位（1 号位）
IDX2 = 1


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


def _form(db, cid, *, sid=CD, countdown=None, cd_steps=(), level=1):
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


# ---------- countdown_delta：修正 -0 / 立即归零 ----------

def test_countdown_delta_noop_without_countdown(db, make_game):
    """无倒计时能力的式神：countdown_delta 修正为 -0（空操作，不报错）。"""
    cid = _delta_card(db, 10010351, -1, sid=100103)
    g, pa = _game(make_game)
    s = pa.shikigami[2]
    s.level = 1
    play(g, 0, cid)
    assert s.countdown is None


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
    fm = _form(db, 10010154, countdown=3)
    plain = _form(db, 10010155)            # 无倒计时形态
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
    fm = _form(db, 10010154, countdown=1, cd_steps=[
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


def test_recast_recorded_no_record_is_noop(db, make_game):
    """无记录时 recast_recorded 为空操作。"""
    cid = 10010157
    db.cards[cid] = F.card(
        cid, shikigami=CD, level=1, token=True,
        steps=[F.Step(op="recast_recorded")])
    g, pa = _game(make_game)
    pb = g.state.players[1]
    play(g, 0, cid)                        # 不报错、无效果
    assert pb.health == 30


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
