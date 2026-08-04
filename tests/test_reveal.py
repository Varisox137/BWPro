"""「已展示」机制族（第十七阶段）测试。

覆盖：reveal 三档（含协战归属）/ 调度展示传递（rules.md:528-533）/ 强索自动调度 /
on_card_played card_revealed 条件 / dealt_damage_turn 过滤 / enemy_hand_all_revealed
条件关键字 / enemy_revealed_count 三口径 / cost_delta_player 已展示耗火 /
入手钩子被动展示 / 能力伤害吸血传导。按机制命名，不用式神/卡牌名命名。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, T, give, pass_turns, play


def test_reveal_modes(db, make_game):
    """reveal 三档：random（随机一张未展示，全展示则无效果）/ shikigami（指定式神
    专属牌全部，协战牌视为同时属于两式神；chosen = 选择目标所指式神）/ all（全部）。"""
    RID = 10010151  # 协战牌：100101 × 100103
    db.cards[RID] = F.card(RID, shikigami=100101, shikigami2=100103, token=True,
                           card_type="reinforce", options=[10010152, 10010352])
    C_ALL, C_SHI, C_RND, C_CHS = 10010161, 10010162, 10010163, 10010164
    db.cards[C_ALL] = F.card(C_ALL, token=True, steps=[F.Step(op="reveal", mode="all")])
    db.cards[C_SHI] = F.card(C_SHI, token=True,
                             steps=[F.Step(op="reveal", mode="shikigami", shikigami=100103)])
    db.cards[C_RND] = F.card(C_RND, token=True, steps=[F.Step(op="reveal", mode="random")])
    db.cards[C_CHS] = F.card(C_CHS, token=True, target=CHOOSE_ENEMY,
                             steps=[F.Step(op="reveal", mode="shikigami", shikigami="chosen")])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    pb.hand.clear()
    c1 = give(g, 1, 10010101)                    # 100101 专属
    c2 = give(g, 1, 10010201)                    # 100102 专属
    c3 = give(g, 1, RID)                         # 协战 100101×100103
    # shikigami=<id>：该式神专属 + 其参与的协战牌
    play(g, 0, C_SHI)
    assert not c1.mods.get("revealed")
    assert not c2.mods.get("revealed")
    assert c3.mods.get("revealed")               # 协战归属：视为同时属于两式神
    # shikigami=chosen：选择目标所指式神（100101）→ 其专属 + 协战
    play(g, 0, C_CHS, target=Ref(player=1, shikigami=0))
    assert c1.mods.get("revealed")
    assert not c2.mods.get("revealed")
    # random：随机一张未展示（此时仅剩 c2 未展示）
    play(g, 0, C_RND)
    assert c2.mods.get("revealed")
    play(g, 0, C_RND)                            # 全部已展示：无效果（不报错）
    # all：敌方全部手牌（幂等）
    give(g, 1, 10010401)
    play(g, 0, C_ALL)
    assert all(c.mods.get("revealed") for c in pb.hand)


def test_mulligan_reveal_transfer(db, make_game):
    """调度展示传递（rules.md:528-533）：换入牌（返回牌库的手牌）具有已展示则失去；
    换入牌原本已展示 → 换出牌（牌库抽上的新牌）获得已展示；未展示手牌调度则换出牌
    不获得已展示。"""
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    old = give(g, 0, 10010101)
    old.mods["revealed"] = True
    idx = pa.hand.index(old)
    g._swap_hand_card(pa, old)
    assert "revealed" not in old.mods            # 换入牌失去已展示
    assert old in pa.deck
    new = pa.hand[idx]
    assert new is not old and new.mods.get("revealed")  # 换出牌获得已展示
    # 未展示手牌调度：换出牌不获得已展示
    plain = next(c for c in pa.hand if not c.mods.get("revealed"))
    idx2 = pa.hand.index(plain)
    g._swap_hand_card(pa, plain)
    assert not pa.hand[idx2].mods.get("revealed")


def test_mulligan_hand_auto_opponent_revealed(db, make_game):
    """强索通道（mulligan_hand auto）：敌方手牌中已展示牌按入手顺序（hand_seq）前
    times 张自动调度（无 pending_choice 交互）；有实际调度才洗牌库，无候选不洗。"""
    CID = 10010165
    db.cards[CID] = F.card(CID, token=True, steps=[F.Step(
        op="mulligan_hand", target_side="opponent", only_revealed=True,
        auto=True, times=3)])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    pb.hand.clear()
    cs = [give(g, 1, 10010100 + n) for n in (1, 2, 3, 4, 5)]  # hand_seq 1..5
    for c in (cs[0], cs[2], cs[3], cs[4]):
        c.mods["revealed"] = True                # 4 张已展示（seq 1/3/4/5）
    log_mark = len(g.state.log)
    play(g, 0, CID)
    assert g.state.pending_choice is None        # auto：无交互作答
    assert cs[1] in pb.hand                      # 未展示：不动
    assert cs[4] in pb.hand                      # 第 4 张已展示（超出前 3 张）：不动
    for c in (cs[0], cs[2], cs[3]):              # 前 3 张已展示：回库并失去已展示
        assert c in pb.deck and "revealed" not in c.mods
    assert len(pb.hand) == 5                     # 换 3 补 3
    new_cards = [c for c in pb.hand if c not in (cs[1], cs[4])]
    assert len(new_cards) == 3
    # 换入牌原本已展示 → 换出牌获得已展示（rules.md:530）
    assert all(c.mods.get("revealed") for c in new_cards)
    assert any("洗了牌库" in l for l in g.state.log[log_mark:])  # 有实际调度：洗牌
    # 无已展示候选：无调度、不洗牌
    g2 = make_game()
    F.battle_setup(g2, {0: 1})
    hand_before = list(g2.state.players[1].hand)
    log_mark2 = len(g2.state.log)
    play(g2, 0, CID)
    assert g2.state.players[1].hand == hand_before
    assert g2.state.pending_choice is None
    assert not any("洗了牌库" in l for l in g2.state.log[log_mark2:])


def test_on_card_played_card_revealed_condition(db, make_game):
    """on_card_played 载荷 card_revealed：{card_revealed: true} 条件仅命中使用
    已展示手牌（读使用点实例 mods）。"""
    db.shikigami[100101].ability = F.EffectBlock(
        when="on_card_played",
        condition={"player": "opponent", "card_revealed": True},
        steps=[F.dmg(2, T(kind="all", pool="enemy_player"))])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    pb.orb = 9
    rev = give(g, 1, 10010201)
    rev.mods["revealed"] = True
    plain = give(g, 1, 10010204)
    pass_turns(g, 1)                             # 换 B 行动
    g.apply({"op": "play_card", "uid": rev.uid})
    assert pb.health == 28                       # 使用已展示牌：触发
    g.apply({"op": "play_card", "uid": plain.uid})
    assert pb.health == 28                       # 使用未展示牌：不触发


def test_dealt_damage_turn_filter(db, make_game):
    """TargetSpec 过滤键 dealt_damage_turn：本回合造成过伤害（任意类型/受伤者）的
    式神才命中——记仇"伤害来源式神"口径；回合开始清除。"""
    CID = 10010166
    db.cards[CID] = F.card(CID, token=True, steps=[F.dmg(
        3, T(kind="all", pool="enemy_shikigami", dealt_damage_turn=True))])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    g.deal_to_player(0, 1, Ref(player=1, shikigami=0))   # B0 本回合造成过伤害
    play(g, 0, CID)
    assert pb.shikigami[0].health == 4 - 3       # 伤害来源式神：命中
    assert pb.shikigami[1].health == 6           # 未造成过伤害：不命中
    assert pb.shikigami[2].health == 6
    pass_turns(g, 2)                             # 回合开始清除（半回合作用域）
    play(g, 0, CID)
    assert pb.shikigami[0].health == 1           # 标记已清：不再命中


def test_enemy_hand_all_revealed_keyword(db, make_game):
    """conditional_keywords 算子 enemy_hand_all_revealed：敌方有手牌且全部已展示
    才授予（空手牌不成立；有未展示不成立）。"""
    CID = 10010167
    db.cards[CID] = F.card(CID, token=True, conditional_keywords=[
        {"keyword": "fast", "enemy_hand_all_revealed": True}])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    inst = give(g, 0, CID)
    cdef = db.cards[CID]
    pb.hand.clear()                              # 空手牌：不成立
    assert "fast" not in g._card_keywords(pa, cdef, inst)
    c1 = give(g, 1, 10010201)
    c2 = give(g, 1, 10010202)
    c1.mods["revealed"] = True                   # 部分已展示：不成立
    assert "fast" not in g._card_keywords(pa, cdef, inst)
    c2.mods["revealed"] = True                   # 全部已展示：成立
    assert "fast" in g._card_keywords(pa, cdef, inst)


def test_enemy_revealed_count(db, make_game):
    """_step_amount {"enemy_revealed_count": 口径}：敌方手牌已展示牌按 spell（法术）/
    other（非法术）/ shikigami_of_chosen（属于被选择式神，含协战）三口径计数。"""
    RID = 10010251  # 协战牌：100102 × 100103
    db.cards[RID] = F.card(RID, shikigami=100102, shikigami2=100103, token=True,
                           card_type="reinforce", options=[10010252, 10010352])
    CBT = 10010253
    db.cards[CBT] = F.card(CBT, shikigami=100102, token=True, card_type="combat")
    C_SPELL, C_CHS = 10010168, 10010169
    db.cards[C_SPELL] = F.card(C_SPELL, token=True, steps=[F.Step(
        op="damage", amount={"enemy_revealed_count": "spell"},
        target=T(kind="all", pool="enemy_player"))])
    db.cards[C_CHS] = F.card(C_CHS, token=True, target=CHOOSE_ENEMY, steps=[F.Step(
        op="damage", amount={"enemy_revealed_count": "shikigami_of_chosen"},
        target=T(kind="all", pool="enemy_player"))])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    pb.hand.clear()
    for cid in (10010101, CBT, RID):             # 已展示：法术 1 + 非法术 2
        give(g, 1, cid).mods["revealed"] = True
    give(g, 1, 10010102)                         # 未展示法术：不计
    assert g._enemy_revealed_count(0, "spell") == 1
    assert g._enemy_revealed_count(0, "other") == 2
    # 选择目标 = 100102（pb 座次 1）：其专属战斗牌 + 参与的协战牌 = 2
    assert g._enemy_revealed_count(0, "shikigami_of_chosen",
                                   [Ref(player=1, shikigami=1)]) == 2
    # 选择目标 = 100101（pb 座次 0）：仅其专属法术 = 1；无选择目标 = 0
    assert g._enemy_revealed_count(0, "shikigami_of_chosen",
                                   [Ref(player=1, shikigami=0)]) == 1
    assert g._enemy_revealed_count(0, "shikigami_of_chosen") == 0
    # 结算接线（_step_amount 动态数值）
    play(g, 0, C_SPELL)
    assert pb.health == 29                       # spell 口径 = 1
    play(g, 0, C_CHS, target=Ref(player=1, shikigami=1))
    assert pb.health == 27                       # shikigami_of_chosen 口径 = 2


def test_cost_delta_revealed_hand(db, make_game):
    """cost_delta_player(side=opponent, card_flag=revealed)：敌方下回合使用已展示
    手牌额外耗火；未展示手牌不受影响；瞬发（已归零）全免（沿跳跳妹妹定案通道）。"""
    CID = 10010170
    db.cards[CID] = F.card(CID, token=True, steps=[F.Step(
        op="cost_delta_player", amount=1, side="opponent", card_flag="revealed")])
    FAST = 10010254
    db.cards[FAST] = F.card(FAST, shikigami=100102, token=True, keywords=["fast"])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    rev = give(g, 1, 10010201)                   # 费用 1
    rev.mods["revealed"] = True
    plain = give(g, 1, 10010202)
    fast = give(g, 1, FAST)
    fast.mods["revealed"] = True
    play(g, 0, CID)
    pass_turns(g, 1)                             # B 的回合：修正生效
    assert g._effective_cost(pb, db.cards[rev.id], rev) == 2      # 已展示 +1
    assert g._effective_cost(pb, db.cards[plain.id], plain) == 1  # 未展示不变
    assert g._effective_cost(pb, db.cards[FAST], fast) == 0       # 瞬发全免
    pass_turns(g, 1)                             # 过期：回合号作用域
    assert g._effective_cost(pb, db.cards[rev.id], rev) == 1


def test_enter_hand_reveal_passive(db, make_game):
    """入手统一钩子（on_card_enter_hand）：「每当一张牌进入敌方手牌时将其展示」
    被动覆盖抽牌与生成牌（不分回合）；己方入手不触发。"""
    db.shikigami[100102].ability = F.EffectBlock(
        when="on_card_enter_hand", condition={"player": "opponent"},
        steps=[F.Step(op="reveal", mode="event")])
    C_DRAW, C_GEN = 10010171, 10010172
    db.cards[C_DRAW] = F.card(C_DRAW, token=True, steps=[F.Step(op="draw", count=1)])
    db.cards[C_GEN] = F.card(C_GEN, token=True,
                             steps=[F.Step(op="generate", card_id=10010351)])
    db.cards[10010351] = F.card(10010351, shikigami=100103, token=True)
    db.cards[10010271] = F.card(10010271, shikigami=100102, token=True,
                                steps=[F.Step(op="draw", count=1)])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    assert not any(c.mods.get("revealed") for c in pa.hand)  # 起始手牌静默发放
    play(g, 0, C_DRAW)                           # A 抽牌 → 进入敌方手牌：展示
    play(g, 0, C_GEN)                            # A 生成牌入手：同样展示
    revealed = [c for c in pa.hand if c.mods.get("revealed")]
    assert len(revealed) == 2
    pb.orb = 9
    pass_turns(g, 1)                             # 换 B 行动
    play(g, 1, 10010271)                         # B 自己抽牌（己方入手）：不展示
    assert not any(c.mods.get("revealed") for c in pb.hand)


def test_lifesteal_ability_damage(db, make_game):
    """吸血传导（灵视形态 [吸血]）：能力伤害（on_card_played → damage 敌方牌手）
    经统一伤害队列结算，伤害来源式神持 lifesteal 时治疗其牌手（伤害后延时）。"""
    db.shikigami[100101].keywords = ["lifesteal"]  # 形态授予同通道（进场入永久类别）
    db.shikigami[100101].ability = F.EffectBlock(
        when="on_card_played", condition={"player": "opponent"},
        steps=[F.dmg(2, T(kind="all", pool="enemy_player"))])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 1})
    pa.health = 25
    pb.orb = 9
    pass_turns(g, 1)                             # 换 B 行动
    play(g, 1, 10010201)                         # 触发 A0 能力伤害 2 → 吸血治疗 2
    assert pb.health == 28
    assert pa.health == 27


def test_cost_delta_form_scope(db, make_game):
    """cost_delta_player(scope="form")：形态结附期间持续（不按回合号过期），
    形态离场移除（心灵迷宫"敌方使用已展示的手牌时需额外消耗一点鬼火"）。"""
    CID = 10010173
    db.cards[CID] = F.card(CID, card_type="form", level=2, steps=[F.Step(
        op="cost_delta_player", amount=1, side="opponent",
        card_flag="revealed", scope="form")])
    g = make_game()
    pa, pb = F.battle_setup(g, {0: 2})
    rev = give(g, 1, 10010201)
    rev.mods["revealed"] = True
    play(g, 0, CID)                              # 结附形态 → 敌方登记费用修正
    assert g._effective_cost(pb, db.cards[rev.id], rev) == 2
    pass_turns(g, 2)                             # 跨回合不过期
    assert g._effective_cost(pb, db.cards[rev.id], rev) == 2
    g._destroy_form(pa, 0, "effect")             # 形态离场：修正移除
    assert g._effective_cost(pb, db.cards[rev.id], rev) == 1


def test_forced_mulligan_shuffles_deck(gdb):
    """强索（10010804 数据端对端）：调度对手已展示的手牌（前 3 张）后洗牌库——
    调度与非抽牌的牌库拿牌隐含检索（shuffle 为 true）。"""
    g = F.mk_game(gdb, team=[100108, 100112, 100114, 100102])  # 青岚+紫岩
    pa, pb = F.battle_setup(g, {0: 2})          # 觉 2 级（强索 level 2）
    pb.hand.clear()
    cs = [give(g, 1, 10010100 + n) for n in (1, 2, 3)]
    for c in cs:
        c.mods["revealed"] = True
    log_mark = len(g.state.log)
    play(g, 0, 10010804)
    assert all(c in pb.deck for c in cs)        # 3 张已展示手牌被强制调度回库
    assert any("洗了牌库" in l for l in g.state.log[log_mark:])
