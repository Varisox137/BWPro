"""委托机制主题测试（三目委托，docs/rules.md 委托机制章）。

覆盖：委托条件账本（PlayerState.quest_counts 11 种 kind 的记账点与口径）、
quest_count_ge/round_ge 条件键与 [条件] 门控、多事多忙扩域（quest_enemy）、
委托整理/截稿日（quest_complete/quest_done）、增强步级条件（蜃楼观光）、
多段攻击（multi_strike）与伤害覆写（override_damage）/战斗免疫全类别
（battle_immunity kind=all，二帚流）、今日委托每日替换（gen_weekday_quest）、
线索选择生成（pick_generate 不可重复）与线索牌手监听（player_aura）、
平和猫又屋（revive_on_defeat）。
测试辅助卡使用衍生号段（51+，token=True）。
"""
from datetime import date

import pytest

from core.engine import IllegalAction
from core.model import CardInstance
from tests import factories as F
from tests.factories import battle_setup, give, move, pass_turns, play

T = F.T
SELF = T(kind="self")
ENEMY_PLAYER = T(kind="all", pool="enemy_player")

# 紧急委托模板（号段 51+；subtype=quest + urgent_quest 标记）
URGENT_COND = {"quest_count_ge": {"kind": "assault", "count": 99}}


def _quest(db, cid: int, cond=None, steps=(), **kw):
    """登记一张委托牌（subtype=quest 衍生牌）。"""
    db.cards[cid] = F.card(cid, subtype="quest", token=True,
                           tags=["urgent_quest"], keywords=["fast"],
                           play_condition=cond or URGENT_COND,
                           steps=list(steps), **kw)


# ==========================================================================
# 委托条件账本（quest_counts）
# ==========================================================================

def test_quest_ledger_counts(db, make_game):
    """账本记账点：使用牌数/形态牌/委托牌/抽牌/出击/攻击/伤害/非战斗伤害。"""
    g = make_game()
    pa, pb = battle_setup(g)
    # 出击 + 攻击（攻击每段计 1；直击敌方牌手 3 力量）
    pb.shield = 0  # 回合推进后重新清零补偿护甲
    g.apply({"op": "assault", "index": 0})
    assert pa.quest_counts["assault"] == 1
    assert pa.quest_counts["attack"] == 1
    assert pa.quest_counts["damage"] == 3
    assert pa.quest_counts.get("effect_damage", 0) == 0  # 战斗伤害不计非战斗伤害
    # 造成伤害（效果伤害 3）
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[F.dmg(3, ENEMY_PLAYER)])
    pa.orb = 9
    play(g, 0, 10010151)
    assert pa.quest_counts["play"] == 1
    assert pa.quest_counts["damage"] == 3 + 3
    assert pa.quest_counts["effect_damage"] == 3
    # 形态牌
    db.cards[10010152] = F.card(10010152, token=True, card_type="form",
                                form_power=1, form_health=1)
    play(g, 0, 10010152)
    assert pa.quest_counts["form_play"] == 1
    assert pa.quest_counts["play"] == 2
    # 委托牌（subtype=quest → quest_used 同计）
    _quest(db, 10010153, cond={"quest_count_ge": {"kind": "play", "count": 0}})
    play(g, 0, 10010153)
    assert pa.quest_counts["quest_used"] == 1
    # 抽牌：回合开始抽牌计入（绑定即计一张）
    pass_turns(g, 2)
    assert pa.quest_counts["draw"] >= 1


def test_quest_ledger_offdeck_play(db, make_game):
    """阵容套牌以外口径：使用过区域的生成牌（generated=True）才计 offdeck_play。"""
    db.cards[10010154] = F.card(10010154, token=True,
                                steps=[F.Step(op="generate", card_id=10010155)])
    db.cards[10010155] = F.card(10010155, token=True)
    g = make_game()
    pa, _ = battle_setup(g)
    play(g, 0, 10010154)  # 普通手牌：不计
    assert pa.quest_counts.get("offdeck_play", 0) == 0
    gen = pa.hand[-1]
    assert gen.generated
    g.apply({"op": "play_card", "uid": gen.uid})
    assert pa.quest_counts["offdeck_play"] == 1


def test_quest_ledger_enemy_defeat_and_revive(db, make_game):
    """敌式神气绝/己方复活账本：按归属方记账（shareable=False 不吃多事多忙扩域）。"""
    db.cards[10010156] = F.card(10010156, token=True,
                                steps=[F.dmg(99, T(kind="choose", pool="enemy_shikigami"))],
                                target=F.CHOOSE_ENEMY)
    g = make_game()
    pa, pb = battle_setup(g)
    play(g, 0, 10010156, target={"player": 1, "shikigami": 0})
    assert pb.shikigami[0].defeated
    assert pa.quest_counts["enemy_defeat"] == 1  # 对方式神气绝计入己方账本
    # 复活（含复活 op；倒计时自然复活同通道 _revive）
    db.cards[10010251] = F.card(10010251, shikigami=100102, token=True,
                                steps=[F.Step(op="revive",
                                              target=T(kind="all", pool="friendly_defeated"))])
    pass_turns(g, 1)
    pb.orb = 3
    play(g, 1, 10010251)
    assert not pb.shikigami[0].defeated
    assert pb.quest_counts["revive"] == 1


def test_quest_ledger_shared_by_quest_enemy_form(db, make_game):
    """多事多忙（quest_enemy）：对方有在场形态含该标记时，己方行为同时计入对方账本。"""
    db.cards[10010252] = F.card(10010252, shikigami=100102, token=True,
                                card_type="form", form_power=1, form_health=1,
                                tags=["quest_enemy"])
    g = make_game()
    pa, pb = battle_setup(g)
    st = g.state
    pb.shikigami[1].form = CardInstance(uid=st.next_uid, id=10010252)  # 直接结附
    st.next_uid += 1
    play(g, 0, 10010101)  # 己方行为
    assert pa.quest_counts["play"] == 1
    assert pb.quest_counts["play"] == 1  # 多事多忙：同计对方账本
    # 形态离场后不再扩域
    pb.shikigami[1].form = None
    play(g, 0, 10010101)
    assert pa.quest_counts["play"] == 2
    assert pb.quest_counts["play"] == 1


# ==========================================================================
# [条件] 门控（quest_count_ge / round_ge / quest_done）
# ==========================================================================

def test_quest_play_condition_gate(db, make_game):
    """quest_count_ge 使用前提：未达不可用、达成可用、quest_done 视为达成。"""
    _quest(db, 10010157, steps=[F.Step(op="draw", count=1)])
    g = make_game()
    pa, _ = battle_setup(g)
    q = give(g, 0, 10010157)
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": q.uid})
    pa.quest_counts["assault"] = 99
    g.apply({"op": "play_card", "uid": q.uid})
    assert q not in pa.hand
    # quest_done 置位（委托整理"视为达成"）：条件不满足也可用
    q2 = give(g, 0, 10010157)
    pa.quest_counts["assault"] = 0
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": q2.uid})
    q2.mods["quest_done"] = True
    g.apply({"op": "play_card", "uid": q2.uid})
    assert q2 not in pa.hand


def test_quest_round_ge_gate(db, make_game):
    """round_ge：对局轮数 (turn+1)//2 ≥ n（双方各一回合为一轮）。"""
    _quest(db, 10010158, cond={"round_ge": 5}, steps=[F.Step(op="draw", count=1)])
    g = make_game()
    pa, _ = battle_setup(g)
    q = give(g, 0, 10010158)
    g.state.turn = 8  # 第 4 轮：不可用
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": q.uid})
    g.state.turn = 9  # 第 5 轮：可用
    g.apply({"op": "play_card", "uid": q.uid})
    assert q not in pa.hand


def test_quest_step_condition(db, make_game):
    """增强步级条件（蜃楼观光口径）：quest_count_ge 不满足则跳过该步。"""
    db.cards[10010159] = F.card(10010159, token=True, steps=[
        F.Step(op="buff_power", amount=2, target=T(kind="all", pool="friendly_shikigami")),
        F.Step(op="buff_power", amount=3,
               condition={"quest_count_ge": {"kind": "quest_used", "count": 4}},
               target=T(kind="all", pool="friendly_shikigami")),
    ])
    g = make_game()
    pa, _ = battle_setup(g)
    play(g, 0, 10010159)
    assert pa.shikigami[0].temp_power == 2
    pa.quest_counts["quest_used"] = 4
    play(g, 0, 10010159)
    assert pa.shikigami[0].temp_power == 2 + 5


# ==========================================================================
# 委托整理 / 截稿日（quest_complete）
# ==========================================================================

def test_quest_complete_single_marks_directly(db, make_game):
    """quest_complete（委托整理）：手牌唯一未完成的紧急委托直接标记，不挂起交互。"""
    _quest(db, 10010160, steps=[F.Step(op="draw", count=1)])
    db.cards[10010161] = F.card(10010161, token=True, steps=[F.Step(op="quest_complete")])
    g = make_game()
    pa, _ = battle_setup(g)
    q = give(g, 0, 10010160)
    play(g, 0, 10010161)
    assert g.state.pending_choice is None
    assert q.mods.get("quest_done") is True


def test_quest_complete_pick_choice(db, make_game):
    """quest_complete 多候选：挂起 quest_complete_pick，choose uid 作答标记并续跑。"""
    _quest(db, 10010160, steps=[F.Step(op="draw", count=1)])
    db.cards[10010161] = F.card(10010161, token=True,
                                steps=[F.Step(op="quest_complete"),
                                       F.Step(op="draw", count=1)])
    g = make_game()
    pa, _ = battle_setup(g)
    q1 = give(g, 0, 10010160)
    q2 = give(g, 0, 10010160)
    play(g, 0, 10010161)
    pend = g.state.pending_choice
    assert pend is not None and pend["kind"] == "quest_complete_pick"
    assert set(pend["options"]) == {q1.uid, q2.uid}
    hand_before = len(pa.hand)
    g.apply({"op": "choose", "uid": q2.uid, "player": 0})
    assert q2.mods.get("quest_done") is True
    assert not q1.mods.get("quest_done")
    assert g.state.pending_choice is None
    assert len(pa.hand) == hand_before + 1  # 续跑剩余步骤（draw 1）


def test_quest_deadline_aura(db, make_game):
    """截稿日口径：己方回合结束时复活（friendly_defeated 限定式神）+ 随机完成紧急委托。"""
    _quest(db, 10010160, steps=[F.Step(op="draw", count=1)])
    db.cards[10010162] = F.card(10010162, shikigami=100102, token=True, steps=[
        F.Step(op="player_aura", when="on_turn_end", condition={"active": "self"},
               steps=[F.Step(op="revive", target=T(kind="all", pool="friendly_defeated",
                                                   shikigami=100101)),
                      F.Step(op="quest_complete", mode="random")])])
    g = make_game()
    pa, pb = battle_setup(g)
    pa.shikigami[1].level = 1  # 监听牌绑定 100102（0 号位将被造气绝）
    db.cards[10010156] = F.card(10010156, token=True,
                                steps=[F.dmg(99, T(kind="choose", pool="any_shikigami"))],
                                target=T(kind="choose", pool="any_shikigami"))
    play(g, 0, 10010156, target={"player": 0, "shikigami": 0})
    assert pa.shikigami[0].defeated
    q = give(g, 0, 10010160)
    play(g, 0, 10010162)  # 登记监听
    pass_turns(g, 1)  # 己方回合结束：复活 + 随机完成
    assert not pa.shikigami[0].defeated
    assert q.mods.get("quest_done") is True


# ==========================================================================
# 多段攻击 / 伤害覆写 / 战斗免疫全类别（二帚流）
# ==========================================================================

def _niji(db, cid: int, times: int):
    """二帚流型战斗牌：免疫所有伤害 + 伤害改为 1 + 攻击 times 次。"""
    db.cards[cid] = F.card(cid, token=True, card_type="combat", steps=[
        F.Step(op="battle_immunity", kind="all", target=SELF),
        F.Step(op="multi_strike", times=times),
    ], temp_grants=[F.block(
        F.Step(op="override_damage", to=1),
        when="on_damage_start", uses=5,
        condition={"source_shikigami": "self"})])


def test_multi_strike_extra_strikes(db, make_game):
    """multi_strike：交战阶段后追加段数依次单独结算；反击只一段且被全类别免疫；
    override_damage 把每段伤害改写为 1。"""
    _niji(db, 10010163, times=3)
    g = make_game()
    pa, pb = battle_setup(g)
    move(g, 1, 0)  # 被攻击者 3/4
    b = pb.shikigami[0]
    a = pa.shikigami[0]
    play(g, 0, 10010163)  # 战斗牌发起战斗
    assert b.health == 4 - 3  # 3 段 × 1 伤害
    assert a.health == 4      # 反击被 kind=all 战斗免疫挡下
    assert pa.quest_counts["attack"] == 3


def test_multi_strike_stops_without_piercing(db, make_game):
    """multi_strike：被攻击者气绝且无贯通时后续段终止。"""
    _niji(db, 10010163, times=5)
    g = make_game()
    pa, pb = battle_setup(g)
    move(g, 1, 0)
    pb.shikigami[0].health = 2  # 首段 1 伤 + 追加段 1 伤即气绝
    play(g, 0, 10010163)
    assert pb.shikigami[0].defeated
    assert pa.quest_counts["attack"] == 2  # 第 3 段起不再攻击


def test_battle_immunity_all_not_outside_battle(db, make_game):
    """battle_immunity kind=all：仅战斗作用域——战斗外的效果伤害不免疫。"""
    _niji(db, 10010163, times=1)
    db.cards[10010253] = F.card(10010253, shikigami=100102, token=True,
                                steps=[F.dmg(2, T(kind="choose", pool="enemy_shikigami"))],
                                target=F.CHOOSE_ENEMY)
    g = make_game()
    pa, pb = battle_setup(g)
    play(g, 0, 10010163)  # 直击牌手（敌方战斗区空）
    pass_turns(g, 1)
    pb.orb = 3
    play(g, 1, 10010253, target={"player": 0, "shikigami": 0})
    assert pa.shikigami[0].health == 4 - 2  # 战斗已结束：免疫条目随终止点移除


# ==========================================================================
# 今日委托每日替换（gen_weekday_quest）
# ==========================================================================

def test_weekday_quest_replaced_in_deck(gdb):
    """日常委托每日替换：构筑进牌库时按当日星期替换为对应'今日委托'（生成口径）。"""
    from db.schema import WEEKDAY_GEN_REPLACE
    expect = WEEKDAY_GEN_REPLACE[10040402][date.today().weekday()]
    team = [100404, 100101, 100102, 100103]
    g = F.mk_game(gdb, team=team, check_deck=False)  # 混合派系测试队，跳过组卡校验
    zones = (g.state.players[0].deck + g.state.players[0].hand
             + g.state.players[1].deck + g.state.players[1].hand)
    assert 10040402 not in [c.id for c in zones]  # 本体不进入对局
    replaced = [c for c in zones if c.id == expect]
    assert len(replaced) == 4  # 双方卡组各 2 张 10040402
    assert all(c.generated for c in replaced)


def test_weekday_quest_replaced_on_generate(gdb):
    """日常委托每日替换：对局中经 generate 生成时同样按当日星期替换。"""
    from db.schema import WEEKDAY_GEN_REPLACE
    expect = WEEKDAY_GEN_REPLACE[10040402][date.today().weekday()]
    gdb.cards[10010151] = F.card(10010151, token=True,
                                 steps=[F.Step(op="generate", card_id=10040402)])
    g = F.mk_game(gdb, team=[100101, 100102, 100103, 100104], check_deck=False)
    pa, _ = battle_setup(g)
    play(g, 0, 10010151)
    assert pa.hand[-1].id == expect
    assert pa.hand[-1].generated


# ==========================================================================
# 线索（pick_generate 不可重复 / player_aura）
# ==========================================================================

def test_pick_generate_unique(db, make_game):
    """pick_generate：多候选挂起交互选择；unique_ext 记账剔除本局已获得者。"""
    for cid in (10010164, 10010165):
        db.cards[cid] = F.card(cid, token=True)
    db.cards[10010166] = F.card(10010166, token=True, steps=[
        F.Step(op="pick_generate", pool=[10010164, 10010165],
               unique_ext="quest_clues_seen")])
    g = make_game()
    pa, _ = battle_setup(g)
    play(g, 0, 10010166)
    pend = g.state.pending_choice
    assert pend is not None and pend["kind"] == "pick_generate"
    assert set(pend["options"]) == {10010164, 10010165}
    g.apply({"op": "choose", "choice": 10010164, "player": 0})
    assert any(c.id == 10010164 and c.generated for c in pa.hand)
    assert pa.ext["quest_clues_seen"] == [10010164]
    assert g.state.pending_choice is None
    # 第二次：仅剩一张候选，直接生成不挂起
    play(g, 0, 10010166)
    assert g.state.pending_choice is None
    assert any(c.id == 10010165 for c in pa.hand)
    # 第三次：候选空 → 空操作（只消耗打出的牌，净手牌数不变）
    hand_n = len(pa.hand)
    play(g, 0, 10010166)
    assert len(pa.hand) == hand_n


def test_quest_clue_player_aura(db, make_game):
    """线索·休憩口径：本局游戏中当控制者使用委托牌时触发（player_aura，可叠加）。"""
    _quest(db, 10010167, cond={"quest_count_ge": {"kind": "play", "count": 0}})
    db.cards[10010168] = F.card(10010168, token=True, steps=[
        F.Step(op="player_aura", when="on_card_played",
               condition={"player": "self", "subtype": "quest"},
               steps=[F.Step(op="heal", amount=3,
                             target=T(kind="all", pool="self_player"))])])
    g = make_game()
    pa, _ = battle_setup(g)
    pa.health = 10
    play(g, 0, 10010168)  # 登记监听（非委托牌，自身不触发）
    assert pa.health == 10
    play(g, 0, 10010167)  # 委托牌使用触发
    assert pa.health == 13
    play(g, 0, 10010101)  # 非委托牌不触发
    assert pa.health == 13


# ==========================================================================
# 平和猫又屋（revive_on_defeat）
# ==========================================================================

def test_revive_on_defeat_form(db, make_game):
    """revive_on_defeat：结附该形态的式神气绝结算完成后复活（形态已消灭）。"""
    db.cards[10010169] = F.card(10010169, token=True, card_type="form",
                                form_power=3, form_health=6, tags=["revive_on_defeat"])
    g = make_game()
    pa, pb = battle_setup(g)
    play(g, 0, 10010169)
    s = pa.shikigami[0]
    assert s.form is not None
    # 敌方出击打死（战斗区有形态式神 3/4+3/6 → 生命 10，敌方 3 力量打不死，
    # 改借伤害牌造气绝）
    db.cards[10010254] = F.card(10010254, shikigami=100102, token=True,
                                steps=[F.dmg(99, T(kind="choose", pool="enemy_shikigami"))],
                                target=F.CHOOSE_ENEMY)
    pass_turns(g, 1)
    pb.orb = 3
    play(g, 1, 10010254, target={"player": 0, "shikigami": 0})
    assert not s.defeated          # 气绝后已复活
    assert s.form is None          # 形态已正常消灭
    assert s.health == s.max_health
    assert pa.quest_counts["revive"] == 1  # 复活账本同计


# ==========================================================================
# CLI 进度显示
# ==========================================================================

def test_quest_progress_label(db, make_game):
    """CLI 手牌委托条件进度标签（format_hand_lines 数据段）：未达成显示计数，达成带 ✓。"""
    from client.cli import format_hand_lines
    _quest(db, 10010171, cond={"quest_count_ge": {"kind": "assault", "count": 2}})
    g = make_game()
    pa, _ = battle_setup(g)
    give(g, 0, 10010171)
    line = next(l for l in format_hand_lines(g, pa, pa.hand) if "委托" in l)
    assert "委托:出击0/2" in line
    pa.quest_counts["assault"] = 2
    line = next(l for l in format_hand_lines(g, pa, pa.hand) if "委托" in l)
    assert "委托:出击2/2 ✓" in line
