"""引擎核心流程：开局结构、出击经济、升级规则、回合开始阶段、气绝/复活、护甲清除、
抽牌事件管线、牌移动事件、灵咒框架。"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from db.schema import InvocationDef
from tests import factories as F
from tests.factories import give, pass_turns, play


def test_game_start_setup(make_game):
    g = make_game()
    a, b = g.state.players
    assert len(b.hand) == 5                        # 双方起始手牌均 5 张
    assert len(a.hand) == 6                        # 先手回合开始再抽 1 → 6 张
    assert b.shield == 5                           # 后手补偿 5 点牌手护甲
    assert a.shield == 0
    assert a.shikigami[0].level == 1               # 最左侧式神自动升至 1 级
    assert all(s.level == 0 for s in a.shikigami[1:])
    assert [s.home_slot for s in a.shikigami] == [1, 2, 3, 4]  # 准备区编号
    assert a.turn_count == 1 and b.turn_count == 0


def test_first_turn_economy(make_game):
    g = make_game(auto_skip_upgrade=False)
    a, b = g.state.players
    assert a.orb == 1                 # 先手第 1 回合 1 鬼火
    assert a.upgrades == 1            # 每个己方回合均有 1 次升级机会（含第 1 回合）
    assert a.assaults_left == 1
    g.apply({"op": "debug_skip_upgrade"})   # 调试跳过升级阶段进入主要阶段
    g.apply({"op": "end_turn"})
    assert b.orb == 2 and b.upgrades == 1 and b.turn_count == 1


def test_upgrade_phase_gating(make_game):
    """升级阶段：只能执行 upgrade；升级耗尽或无目标后进入主要阶段。"""
    g = make_game(auto_skip_upgrade=False)
    a = g.state.players[0]
    assert g.state.phase == "upgrade"
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    with pytest.raises(IllegalAction):
        g.apply({"op": "end_turn"})
    g.apply({"op": "upgrade", "index": 1})      # 0 级里升 1 级
    assert g.state.phase == "battle"
    assert a.upgrades == 0
    # 主要阶段才能使用非升级指令
    g.apply({"op": "end_turn"})


def test_mulligan_flow(db, make_game):
    """游戏开始阶段：调度 → 双方确认 → 入场升级 → 先手抽 1；换入牌继承换出牌的 hand_seq。"""
    g = make_game(mulligan=True)
    assert g.state.phase == "mulligan"
    with pytest.raises(IllegalAction):
        g.apply({"op": "end_turn"})   # 调度阶段不能用对战指令
    a, b = g.state.players
    assert len(a.hand) == 5 and a.mulligans_left == 3
    old_seq = a.hand[0].hand_seq
    g.apply({"op": "mulligan", "player": 0, "uid": a.hand[0].uid})
    assert len(a.hand) == 5 and a.mulligans_left == 2   # 返回 1 张再随机抽 1
    assert a.hand[0].hand_seq == old_seq                # 新牌继承原位置顺序编号
    g.apply({"op": "ready", "player": 0})
    assert g.state.phase == "mulligan"                  # B 未确认
    g.apply({"op": "ready", "player": 1})
    assert g.state.phase == "battle"
    assert len(a.hand) == 6                             # 先手抽 1
    assert a.shikigami[0].level == 1                    # 入场后最左升 1 级


def test_hand_seq_compacts_on_leave(make_game):
    """手牌顺序编号始终 1..N；卡牌离开手牌后大于它的编号均 -1。"""
    g = make_game()
    a = g.state.players[0]
    # 找一张当前可打出的手牌（所属式神已 1 级且费用足够）
    starter_id = a.shikigami[0].id
    card = next(c for c in a.hand if g.db.cards[c.id].shikigami == starter_id)
    old_seq = card.hand_seq
    g.apply({"op": "play_card", "uid": card.uid})
    assert card not in a.hand
    assert all(c.hand_seq != old_seq for c in a.hand)
    # 剩余编号连续
    seqs = sorted(c.hand_seq for c in a.hand)
    assert seqs == list(range(1, len(a.hand) + 1))


def test_assault_costs_orb_and_action(make_game):
    g = make_game()
    a, b = g.state.players
    g.apply({"op": "assault", "index": 0})        # 3 攻打脸：后手 5 甲先吸收
    assert a.orb == 0 and a.assaults_left == 0    # 出击耗 1 火 + 每回合唯一出击次数
    assert b.shield == 2 and b.health == 30       # 5 甲 - 3 = 2
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})


def test_upgrade_lowest_rule(make_game):
    g = make_game(auto_skip_upgrade=False)
    g.apply({"op": "debug_skip_upgrade"})
    g.apply({"op": "end_turn"})                  # B 第 1 回合
    g.apply({"op": "debug_skip_upgrade"})
    g.apply({"op": "end_turn"})                  # A 第 2 回合，1 次升级机会
    a = g.state.players[0]
    with pytest.raises(IllegalAction):
        g.apply({"op": "upgrade", "index": 0})    # 已 1 级，不是己方最低
    g.apply({"op": "upgrade", "index": 2})        # 0 级里任选其一
    assert a.shikigami[2].level == 1
    with pytest.raises(IllegalAction):
        g.apply({"op": "upgrade", "index": 1})    # 机会已用完


def test_extra_upgrade_turns(make_game):
    """先手第 7 / 后手第 3 个己方回合各 +1 升级机会。"""
    g = make_game(auto_skip_upgrade=False)
    a, b = g.state.players
    for _ in range(5):                            # 推进到 B 的第 3 回合
        if g.state.phase == "upgrade":
            g.apply({"op": "debug_skip_upgrade"})
        g.apply({"op": "end_turn"})
    assert b.turn_count == 3 and b.upgrades == 2
    for _ in range(7):                            # 推进到 A 的第 7 回合
        if g.state.phase == "upgrade":
            g.apply({"op": "debug_skip_upgrade"})
        g.apply({"op": "end_turn"})
    assert a.turn_count == 7 and a.upgrades == 2


def test_draw_after_turn_start_effects(db, make_game):
    """回合开始抽牌在回合开始触发的效果结算完之后。"""
    db.shikigami[100101].ability = F.block(
        F.Step(op="damage", amount=1, target=F.T(kind="all", pool="enemy_player")),
        when="on_turn_start", condition={"player": "self"}, timing="queue", mode="atomic")
    g = make_game()
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})                   # A 第 2 回合开始
    i_end = g.history.index("on_turn_end")
    i_start = g.history.index("on_turn_start", i_end)
    i_dmg = g.history.index("on_player_damaged", i_start)
    i_draw = g.history.index("on_draw", i_start)
    assert i_start < i_dmg < i_draw


def test_shield_clears_at_turn_start(make_game):
    """己方护甲（式神及牌手）在回合开始阶段清除。"""
    g = make_game()
    a, b = g.state.players
    a.shikigami[0].shield = 3
    a.shield = 2
    g.apply({"op": "end_turn"})                   # B 回合开始：B 的 5 甲被清除
    assert b.shield == 0
    g.apply({"op": "end_turn"})                   # A 回合开始
    assert a.shield == 0 and a.shikigami[0].shield == 0


def test_combat_zone_retreats_at_turn_start(make_game):
    """回合开始阶段：己方战斗区式神退回准备区（不视为出击/移动指令）。"""
    g = make_game()
    a = g.state.players[0]
    g.apply({"op": "assault", "index": 0})        # 出击后驻留战斗区
    assert a.combat_index == 0
    g.apply({"op": "end_turn"})                   # B 回合：A 的墙仍在战斗区
    assert a.combat_index == 0
    g.apply({"op": "end_turn"})                   # A 回合开始：退回准备区
    assert a.combat_index is None
    assert a.shikigami[0].in_play                 # 退回不是离场


def test_zero_level_ability_flag(db, make_game):
    """trigger_when_not_in_play：书翁/三尾狐类能力在 0 级（未升级）也可触发；未标记则不触发。"""
    db.shikigami[100101].ability = F.block(
        F.Step(op="draw", count=1),
        when="on_game_start", trigger_when_not_in_play=True)
    db.shikigami[100102].ability = F.block(
        F.Step(op="damage", amount=1, target=F.T(kind="all", pool="enemy_player")),
        when="on_game_start")                              # 未标记：0 级不触发
    g = make_game()
    a, b = g.state.players
    assert len(a.hand) == 7                                # 5 起始 + 1 游戏开始能力 + 1 先手抽
    assert len(b.hand) == 6                                # 5 起始 + 1 游戏开始能力
    assert a.health == 30 and b.health == 30               # 未标记的 0 级能力未触发


def test_defeated_and_revive(db, make_game):
    db.cards[10010151] = F.card(10010151, steps=[F.dmg(3)], token=True,
                                target=F.T(kind="choose", pool="enemy_shikigami"))
    g = make_game()
    b = g.state.players[1]
    b.shikigami[0].health = 3
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert b.shikigami[0].defeated is True
    assert b.shikigami[0].revive_countdown == 3
    for _ in range(6):                            # B 的 3 个回合开始递减后复活
        g.apply({"op": "end_turn"})
    assert b.shikigami[0].defeated is False
    assert b.shikigami[0].health == b.shikigami[0].max_health


def test_zero_level_cannot_revive(make_game):
    """0 级（未在场）式神不能复活（倒计时不递减）。"""
    g = make_game()
    s = g.state.players[0].shikigami[1]
    s.defeated = True
    s.revive_countdown = 1
    for _ in range(2):                                     # 推进到 A 的下个回合开始
        g.apply({"op": "end_turn"})
    assert s.defeated is True and s.revive_countdown == 1


def test_deck_out_loss(make_game):
    g = make_game()
    g.state.players[0].deck.clear()
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})                   # A 回合开始抽牌时牌库为空 → 判负
    assert g.state.winner == 1


def test_move_swap_and_combat_trade(make_game):
    g = make_game()
    g.apply({"op": "debug_move", "args": {"player": 0, "index": 0}})
    g.apply({"op": "assault", "index": 0})        # A 0 号出击打脸并驻留
    g.apply({"op": "end_turn"})
    seen = []
    orig_emit = g.emit

    def spy(name, **kw):
        if name == "on_damage":
            seen.append(kw["victim"])
        orig_emit(name, **kw)

    g.emit = spy
    g.apply({"op": "assault", "index": 0})        # B 0 号撞 A 战斗区 0 号：3 ↔ 3
    a0 = g.state.players[0].shikigami[0]
    b0 = g.state.players[1].shikigami[0]
    assert a0.health == 1 and b0.health == 1      # 4 - 3，同时结算
    assert seen[0] == Ref(player=1, shikigami=0)  # 反击：攻击者先受伤
    assert seen[1] == Ref(player=0, shikigami=0)  # 攻击：被攻击者后受伤


def test_passive_only_in_play_and_own_turn(db, make_game):
    """被动只在式神情在场时触发，且只打在场目标（0 级不可被指定）。"""
    for sid in (100101, 100102):
        db.shikigami[sid].ability = F.block(
            F.Step(op="damage", amount=1, target=F.T(kind="all", pool="enemy_shikigami")),
            when="on_turn_end", condition={"player": "self"}, timing="queue", mode="atomic")
    g = make_game()
    g.apply({"op": "end_turn"})                   # A 结束：仅 100101（1 级在场）触发
    b = g.state.players[1]
    assert b.shikigami[0].health == 3             # 4 - 1（唯一在场目标）
    assert b.shikigami[1].health == 6             # 0 级未在场，不掉血
    g.apply({"op": "end_turn"})                   # B 结束：B 的 100101 触发
    assert g.state.players[0].shikigami[0].health == 3


def test_player_defeat_pending_end(db, make_game):
    """牌手气绝 → 待结束：已入队的触发能力不再执行；后续伤害/治疗对气绝牌手不再生效。"""
    # B 的式神能力：己方牌手受伤后抽 1（延时时机）——牌手致死后不应执行
    db.shikigami[100101].ability = F.block(
        F.Step(op="draw", count=1),
        when="on_player_damaged", condition={"player": "self"}, timing="queue", mode="atomic")
    db.cards[10010151] = F.card(
        10010151, token=True,
        target=F.T(kind="choose", pool="enemy_player"),
        steps=[F.dmg(40), F.Step(op="heal", amount=10)], block_kw={"mode": "atomic"})
    g = make_game()
    b = g.state.players[1]
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1)})
    assert b.defeated is True and g.state.winner == 0
    assert b.health == -5                         # 5 甲吸收后 35 点致死；后续治疗 10 不再生效
    assert len(b.hand) == 5                       # 已入队的"受伤后抽 1"被清除，不再执行


def test_pending_end_blocks_insert_abilities(db, make_game):
    """待结束：牌手气绝后，同一结算链内后续事件不再触发 insert 时机能力。"""
    # B 的式神能力：任意式神受伤后立即抽 1（即时时机）——牌手已气绝则不应执行
    db.shikigami[100101].ability = F.block(
        F.Step(op="draw", count=1),
        when="on_damage", timing="insert", mode="atomic")
    db.cards[10010151] = F.card(
        10010151, token=True,
        target=F.T(kind="choose", pool="enemy_player"),
        steps=[F.dmg(40),
               F.Step(op="damage", amount=1, target=F.T(kind="all", pool="enemy_shikigami"))],
        block_kw={"mode": "atomic"})
    g = make_game()
    b = g.state.players[1]
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1)})
    assert b.defeated is True and g.state.winner == 0
    assert len(b.hand) == 5  # 气绝后的 on_damage 事件不再触发 insert 能力


def test_defeat_event_has_source_and_reason(db, make_game):
    """气绝事件要素：来源、气绝者、原因（载荷供能力条件匹配）。"""
    db.cards[10010151] = F.card(10010151, steps=[F.dmg(3)], token=True,
                                target=F.T(kind="choose", pool="enemy_shikigami"))
    g = make_game()
    b = g.state.players[1]
    b.shikigami[0].health = 3
    seen = []
    orig_emit = g.emit
    def spy(name, **kw):
        if name == "on_shikigami_defeated":
            seen.append(kw)
        return orig_emit(name, **kw)
    g.emit = spy
    c = give(g, 0, 10010151)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert len(seen) == 1
    assert seen[0]["victim"] == Ref(player=1, shikigami=0)
    assert seen[0]["source"] == Ref(player=0, shikigami=0)   # 伤害来源 = 出牌式神的所属
    assert seen[0]["reason"] == "伤害"


# ==========================================================================
# 爆牌 / 空库替换 / 战中调度 / 抽牌替换
# ==========================================================================

def test_hand_cap_burns_excess(db, make_game):
    """爆牌（hand_cap=12）：移入手牌超上限的牌转而置入墓地——抽牌与
    生成置入手牌共用 move_card 同一条路径。"""
    gen, token_cid = 10010167, 10010166
    db.cards[token_cid] = F.card(token_cid, token=True)
    db.cards[gen] = F.card(
        gen, steps=[F.Step(op="generate", card_id=token_cid, count=2)], token=True)
    g = make_game()
    pa = g.state.players[0]
    for _ in range(12 - len(pa.hand)):
        give(g, 0, token_cid)
    assert len(pa.hand) == 12
    grave_before = len(pa.zones.get("graveyard", []))
    g.draw_cards(0, 1)                            # 抽牌爆牌：牌库顶牌转墓地
    assert len(pa.hand) == 12
    assert len(pa.zones["graveyard"]) == grave_before + 1
    # 生成置入手牌同路径：腾 1 格后打出生成 2 张 → 1 张入手、1 张爆掉
    g.move_card(pa, pa.hand[0], "graveyard")
    pa.orb = 9
    play(g, 0, gen)
    assert len(pa.hand) == 12
    burned = [c for c in pa.zones["graveyard"] if c.id == token_cid]
    assert len(burned) >= 1


def test_empty_deck_burn_replaces_loss(db, make_game):
    """觉醒·书翁型空库替换（觉醒牌 tags 含 deck_out_burn）：牌库为空时抽牌改为
    对敌方牌手造成 10 点伤害（每张空抽各触发一次），伤害致死走正常牌手气绝判负。"""
    awaken_cid = 10010168
    db.cards[awaken_cid] = F.card(awaken_cid, subtype="awaken",
                                  tags=["deck_out_burn"], token=True)
    g = make_game()
    pa, pb = g.state.players
    pb.shield = 0
    pa.shikigami[0].awakened = awaken_cid         # 在场（1 级）且已觉醒
    pa.deck.clear()
    for expected in (20, 10):
        pass_turns(g, 2)                          # A 回合开始空抽 → 烧 10
        assert pb.health == expected and g.state.winner is None
    pass_turns(g, 2)                              # 再空抽 → 30→0，敌方牌手气绝
    assert pb.defeated and g.state.winner == 0
    # 对照：无该标记的空库抽牌照常判负
    g2 = make_game()
    g2.state.players[0].deck.clear()
    pass_turns(g2, 2)
    assert g2.state.winner == 1


def test_battle_mulligan_flow(db, make_game):
    """战中调度（云游，mulligan_hand）：出牌挂起 pending mulligan_pick——choose 带
    uid 换 1 张（返回牌库随机位置再随机抽 1），choose 不带 uid 提前结束并洗牌库，
    随后续跑挂起块的剩余步骤。"""
    cid = 10010169
    db.cards[cid] = F.card(
        cid, steps=[F.Step(op="mulligan_hand", times=3, shuffle=True),
                    F.Step(op="draw", count=1)], token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    hand_before = len(pa.hand)                    # 打出后净手牌（不含本牌）
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid})
    pend = g.state.pending_choice
    assert pend and pend["kind"] == "mulligan_pick" and pend["remaining"] == 3
    uid = pa.hand[0].uid
    g.apply({"op": "choose", "uid": uid, "player": 0})       # 换 1 张
    assert g.state.pending_choice["remaining"] == 2
    assert uid not in [c.uid for c in pa.hand]
    g.apply({"op": "choose", "player": 0})                   # 提前结束 → 洗牌续块
    assert g.state.pending_choice is None
    assert len(pa.hand) == hand_before + 1        # 续块的 draw 1 已结算


def test_draw_to_pick_replaces_turn_draw(db, make_game):
    """明心型抽牌替换（在场形态 tags 含 draw_to_pick）：回合开始的抽牌改为检视牌库顶
    3 张选 1 置入手牌（然后洗牌库）；牌库不足 3 张全检视；牌库为空走空库分支（判负）。"""
    cid = 10010170
    db.cards[cid] = F.card(cid, card_type="form", form_power=4, form_health=5,
                           tags=["draw_to_pick"], token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    play(g, 0, cid)
    hand_before = len(pa.hand)
    pass_turns(g, 2)                              # → A 第 2 回合开始：挂起检视
    pend = g.state.pending_choice
    assert pend and pend["kind"] == "deck_top_pick" and len(pend["options"]) == 3
    g.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    assert g.state.pending_choice is None
    assert len(pa.hand) == hand_before + 1
    # 牌库不足 3 张：全部检视（截断到 2）
    del pa.deck[2:]
    pass_turns(g, 2)
    pend = g.state.pending_choice
    assert len(pend["options"]) == 2
    g.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    # 牌库为空：走空库抽牌分支（无 deck_out_burn → 判负）
    pa.deck.clear()
    pass_turns(g, 2)
    assert g.state.winner == 1


# ==================== 抽牌事件管线 / 牌移动事件 ====================


def test_draw_pipeline_per_card_events(make_game):
    """抽牌管线：抽多张逐张发 on_before_draw（即时）与移动双锚点（on_card_move 即时 /
    on_card_moved 延时），整次动作结束发单次 on_draw。"""
    g = make_game()
    g.history.clear()
    g.draw_cards(0, 2)
    per_card = ["on_before_draw", "on_card_enter_hand", "on_card_move", "on_card_moved"]
    assert g.history == per_card * 2 + ["on_draw"]


def test_before_draw_count_is_remaining(db, make_game):
    """on_before_draw 的 count = 剩余抽取数（"抽X张"= 抽牌前插入结算"抽X-1张"的递归语义）。"""
    db.shikigami[100101].abilities = [
        F.block(F.dmg(1, F.T(kind="all", pool="enemy_player")),
                when="on_before_draw", condition={"count": 2}),
        F.block(F.dmg(2, F.T(kind="all", pool="enemy_player")),
                when="on_before_draw", condition={"count": 1}),
    ]
    g = make_game()
    b = g.state.players[1]
    b.shield = 0
    g.draw_cards(0, 2)
    g._drain_queue()  # on_before_draw 为即时时机——其实 emit 内已结算；drain 兜底
    assert b.health == 30 - 1 - 2          # 第 1 张 count=2、第 2 张 count=1


def test_card_move_event_payload(db, make_game):
    """牌移动事件载荷贯通：抽牌 = deck→hand/reason="draw"（条件匹配触发）；
    用牌入墓地 reason=None（不匹配，不触发）。"""
    db.shikigami[100101].ability = F.block(
        F.dmg(1, F.T(kind="all", pool="enemy_player")),
        when="on_card_moved",
        condition={"from_zone": "deck", "to_zone": "hand", "reason": "draw"})
    g = make_game()
    b = g.state.players[1]
    b.shield = 0
    play(g, 0, 10010101)                   # 用牌：hand→graveyard（reason=None）→ 不触发
    assert b.health == 30
    g.draw_cards(0, 1)
    assert b.health == 30                  # on_card_moved 为延时时机：尚未结算
    g._drain_queue()
    assert b.health == 29


# ==================== 灵咒框架 ====================


def test_invocation_draw_trigger_on_draw(db, make_game):
    """卡牌灵咒"抽到触发"：抽牌入手时触发块延时结算（控制者=来源所属牌手），随后移除。"""
    db.invocations["引魂"] = InvocationDef(
        name="引魂",
        draw_trigger=F.block(F.dmg(2, F.T(kind="all", pool="enemy_player"))))
    g = make_game()
    a, b = g.state.players
    b.shield = 0
    card = a.deck[0]
    g.attach_invocation("引魂", player=0, card=card)
    assert [e["name"] for e in card.invocations] == ["引魂"]
    g.draw_cards(0, 1)
    assert card.invocations == []          # 入手处理点即移除
    assert b.health == 30                  # 触发块延时结算：未 drain 前未生效
    g._drain_queue()
    assert b.health == 28


def test_invocation_removed_silently_on_non_draw_to_hand(db, make_game):
    """卡牌灵咒：检索等非抽牌入手静默移除（不触发"抽到触发"块）。"""
    db.invocations["引魂"] = InvocationDef(
        name="引魂",
        draw_trigger=F.block(F.dmg(2, F.T(kind="all", pool="enemy_player"))))
    g = make_game()
    a, b = g.state.players
    b.shield = 0
    card = a.deck[0]
    g.attach_invocation("引魂", player=0, card=card)
    g.move_card(a, card, "hand", reason="search")   # 检索入手
    assert card.invocations == []
    g._drain_queue()
    assert b.health == 30                  # 未触发


def test_invocation_draw_trigger_on_hand_cap_burst(db, make_game):
    """卡牌灵咒：爆牌仍触发并移除——先发 deck→hand（reason="draw"）移动事件，
    上限检查在"牌移动后"时机之后，再经 hand_cap 递归转墓地。"""
    db.invocations["引魂"] = InvocationDef(
        name="引魂",
        draw_trigger=F.block(F.dmg(2, F.T(kind="all", pool="enemy_player"))))
    g = make_game()
    a, b = g.state.players
    b.shield = 0
    card = a.deck[0]
    g.attach_invocation("引魂", player=0, card=card)
    while len(a.hand) < 12:                # 填满至手牌上限（hand_cap=12）
        give(g, 0, 10010201)
    g.draw_cards(0, 1)
    assert card in a.graveyard             # 爆牌：转墓地
    assert card.invocations == []
    g._drain_queue()
    assert b.health == 28                  # 已触发


def test_invocation_shikigami_buff_ability_and_defeat(db, make_game):
    """式神灵咒：效果类增减益结附期间生效（临时修正通道）；能力类参与收集（进场序号=
    结附时刻）；气绝时全部移除。"""
    db.invocations["刀鸣"] = InvocationDef(
        name="刀鸣", power=1, health=2,
        abilities=[F.block(F.dmg(1, F.T(kind="all", pool="enemy_player")),
                          when="on_turn_end")])
    g = make_game()
    a, b = g.state.players
    b.shield = 0
    s = a.shikigami[0]
    base_pow, base_max = s.eff_power, s.max_health
    g.attach_invocation("刀鸣", player=0, target=Ref(player=0, shikigami=0))
    assert s.eff_power == base_pow + 1 and s.max_health == base_max + 2
    assert s.invocations[0]["ability_seq"] > 0
    g.apply({"op": "end_turn"})            # on_turn_end（即时时机）：灵咒能力触发
    assert b.health == 29
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    g._drain_queue()
    assert s.defeated
    assert s.invocations == []             # 气绝移除（效果类临时修正气绝本清，等效减回）
    assert s.temp_power == 0 and s.temp_health == 0


def test_invocation_unique_removes_same_source_only(db, make_game):
    """[唯一]：结附后移除双方全场同源同名灵咒（移除在结附之后；新结附自身保留；
    异源同名保留）；被移除的效果类临时修正减回。"""
    db.invocations["庇护"] = InvocationDef(name="庇护", unique="unique", power=1)
    g = make_game()
    a, b = g.state.players
    g.attach_invocation("庇护", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("庇护", player=1, target=Ref(player=1, shikigami=0))  # 异源同名
    g.attach_invocation("庇护", player=0, target=Ref(player=0, shikigami=1))  # 同源新结附
    assert a.shikigami[0].invocations == []            # 同源旧者移除
    assert a.shikigami[0].temp_power == 0              # 临时修正已减回
    assert len(a.shikigami[1].invocations) == 1        # 新结附保留
    assert a.shikigami[1].temp_power == 1
    assert len(b.shikigami[0].invocations) == 1        # 异源同名保留
    # 卡牌上的同源同名一并移除（全场 = 式神 + 手牌/牌库中的卡牌）
    c1, c2 = a.deck[0], a.deck[1]
    g.attach_invocation("庇护", player=0, card=c1)
    assert a.shikigami[1].invocations == []            # 式神上的同源同名被移除
    assert len(c1.invocations) == 1                    # 新结附保留
    g.attach_invocation("庇护", player=0, card=c2)
    assert c1.invocations == []                        # 卡牌上的同源旧者移除
    assert len(c2.invocations) == 1


def test_invocation_shikigami_unique_per_shikigami(db, make_game):
    """[式神唯一]：仅移除该式神上同源同名灵咒；其他式神上的同名保留。"""
    db.invocations["影"] = InvocationDef(name="影", unique="shikigami_unique", power=1)
    g = make_game()
    a = g.state.players[0]
    g.attach_invocation("影", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("影", player=0, target=Ref(player=0, shikigami=1))
    g.attach_invocation("影", player=0, target=Ref(player=0, shikigami=0))  # 再结附 shiki0
    assert len(a.shikigami[0].invocations) == 1        # 旧的被移除，新结附保留
    assert (a.shikigami[0].invocations[0]["ability_seq"]
            > a.shikigami[1].invocations[0]["ability_seq"])
    assert len(a.shikigami[1].invocations) == 1        # 其他式神同名保留
    assert a.shikigami[0].temp_power == 1 and a.shikigami[1].temp_power == 1


def test_attach_invocation_op_and_event(db, make_game):
    """attach_invocation op：式神结附走 targets、卡牌结附走 uid；结附后
    发 on_invocation_attached（延时时机）。"""
    db.invocations["契"] = InvocationDef(name="契", power=1)
    db.cards[10010151] = F.card(
        10010151, token=True,
        target=F.T(kind="choose", pool="friendly_shikigami"),
        steps=[F.Step(op="attach_invocation", name="契")])
    g = make_game()
    a = g.state.players[0]
    a.orb = 9
    play(g, 0, 10010151, target=Ref(player=0, shikigami=0))   # 式神结附（targets）
    assert [e["name"] for e in a.shikigami[0].invocations] == ["契"]
    assert a.shikigami[0].temp_power == 1
    assert "on_invocation_attached" in g.history
    # 卡牌结附（uid 路径；targets 忽略）
    host = give(g, 0, 10010201)
    db.cards[10010152] = F.card(
        10010152, token=True,
        steps=[F.Step(op="attach_invocation", name="契", uid=host.uid)])
    play(g, 0, 10010152)
    assert [e["name"] for e in host.invocations] == ["契"]
