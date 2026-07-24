"""引擎核心流程：开局结构、出击经济、升级规则、回合开始阶段、气绝/复活、护甲清除。"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.conftest import give


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


def test_level_zero_not_in_play(make_game):
    g = make_game()
    a = g.state.players[0]
    assert a.shikigami[1].in_play is False
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 1})    # 0 级未在场，不能出击
    # 移动（move）已不再是玩家主动操作，故不再在此测试


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
    """先手第 7 / 后手第 4 个己方回合各 +1 升级机会。"""
    g = make_game(auto_skip_upgrade=False)
    a, b = g.state.players
    for _ in range(7):                            # 推进到 B 的第 4 回合
        if g.state.phase == "upgrade":
            g.apply({"op": "debug_skip_upgrade"})
        g.apply({"op": "end_turn"})
    assert b.turn_count == 4 and b.upgrades == 2
    for _ in range(5):                            # 推进到 A 的第 7 回合
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
    g.apply({"op": "assault", "index": 0})        # B 0 号撞 A 战斗区 0 号：3 ↔ 3
    a0 = g.state.players[0].shikigami[0]
    b0 = g.state.players[1].shikigami[0]
    assert a0.health == 1 and b0.health == 1      # 4 - 3，同时结算


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
