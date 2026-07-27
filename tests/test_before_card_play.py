"""使用手牌前时机与无效化（A6 魔音扰心机制）+ 吾即正义 transform /
金风流羽动态费用 / 黄金羽计数（A7）测试。

对应 docs/rules.md 卡牌使用事件流程与 thoughts.txt 答复 (4)(6)(8)：
- 出牌流程在合法性检查与支付之后、效果结算之前 emit on_before_card_play
  （即时时机，payload 含可变 nullified 标记）；
- 无效化：跳过效果块、牌照常离手进墓地、费用/瞬发名额已付不退；
- 一次性"下一次敌方用牌前无效化"能力用 delay_grant(scope="turn") 表达，
  响应牌则直接把 effects.when 挂在 on_before_card_play。
0 号位（100101）为己方主体，1 号位（100102）为响应/对方用牌所属。
"""
from tests import factories as F
from tests.factories import give, pass_turns, play

T = F.T
MAYIN = 10010151      # 魔音扰心（主动使用：登记一次性无效化延迟能力）
NULL_SPELL = 10010251  # 对方将被无效化的瞬发伤害牌
PLAIN_SPELL = 10010252  # 对方普通伤害牌
RESP = 10010253        # 魔音扰心（响应牌形态）
ALT = 10010154         # 吾即正义（transform）
ALT2 = 10010155        # 吾即正义（triggers + add_mod 路径）
DYN = 10010156         # 金风流羽（动态费用）
FEATHER = 10010157     # 黄金羽（tags 计数）


def _game(make_game):
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shikigami[1].level = 1        # 对方 100102 可用牌/响应
    return g, pa, pb


def _mayin(db):
    """魔音扰心·主动使用：登记一次性"下一次敌方用牌的使用手牌前无效化"（本回合）。"""
    db.cards[MAYIN] = F.card(
        MAYIN, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="delay_grant", when="on_before_card_play",
                      condition={"player": "opponent"}, scope="turn",
                      steps=[{"op": "nullify_card_play"}])])


def _enemy_spells(db):
    db.cards[NULL_SPELL] = F.card(
        NULL_SPELL, shikigami=100102, level=1, token=True, keywords=["fast"],
        steps=[F.Step(op="damage", amount=3, target=T(kind="all", pool="enemy_player"))])
    db.cards[PLAIN_SPELL] = F.card(
        PLAIN_SPELL, shikigami=100102, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_player"))])


def _response(db, cid):
    """魔音扰心·响应牌：敌方用牌的使用手牌前必发，无效化之。"""
    db.cards[cid] = F.card(
        cid, shikigami=100102, level=1, cost=1, token=True,
        keywords=["trigger"], when="on_before_card_play",
        block_kw={"condition": {"player": "opponent"}},
        steps=[F.Step(op="nullify_card_play")])


# ---------- 主动使用 → 一次性无效化 ----------

def test_nullify_proactive_delay_grant(db, make_game):
    """主动使用魔音扰心：下一次敌方用牌被无效化——费用/瞬发名额已付、牌离手进墓地、
    效果不结算、不产生该牌的 on_card_played；一次性延迟能力触发后移除。"""
    _mayin(db)
    _enemy_spells(db)
    g, pa, pb = _game(make_game)
    s = pa.shikigami[0]
    play(g, 0, MAYIN)
    assert len(s.delayed) == 1
    pass_turns(g, 1)                          # B 第 1 回合（鬼火 2）
    n_played = g.history.count("on_card_played")
    play(g, 1, NULL_SPELL)                    # 敌方瞬发牌 → 被无效化
    assert s.delayed == []                    # 一次性：触发即移除
    assert pa.health == 30                    # 效果不结算
    assert pb.fast_used                       # 瞬发名额已付不退
    assert pb.orb == 2                        # 瞬发免费
    assert any(c.id == NULL_SPELL for c in pb.graveyard)  # 离手进墓地
    assert g.history.count("on_card_played") == n_played  # 该次使用事件终止结算
    play(g, 1, PLAIN_SPELL)                   # 第二张：不再无效化
    assert pa.health == 28
    assert pb.orb == 1


def test_turn_scope_grant_expires(db, make_game):
    """"本回合"无效化能力：未消耗时于己方回合开始清除；之后敌方用牌照常。"""
    _mayin(db)
    _enemy_spells(db)
    g, pa, pb = _game(make_game)
    s = pa.shikigami[0]
    play(g, 0, MAYIN)
    pass_turns(g, 2)                          # B 第 1 回合（未用牌）→ A 第 2 回合开始
    assert s.delayed == []                    # scope="turn" 清除
    pass_turns(g, 1)                          # B 第 2 回合
    play(g, 1, PLAIN_SPELL)
    assert pa.health == 28                    # 不再无效化


# ---------- 响应牌路径 ----------

def test_nullify_response_card(db, make_game):
    """响应牌魔音扰心：敌方回合用牌的使用手牌前必发——付响应费、牌进墓地、
    无效化该次使用（效果不结算）。"""
    _response(db, RESP)
    vic = 10010152
    db.cards[vic] = F.card(
        vic, shikigami=100101, level=1, token=True,
        steps=[F.Step(op="damage", amount=3, target=T(kind="all", pool="enemy_player"))])
    g, pa, pb = _game(make_game)
    pb.orb = 2                                # 留火响应
    give(g, 1, RESP)
    play(g, 0, vic)                           # A 用牌 → B 响应无效化
    assert pb.orb == 1                        # 响应费用照付
    assert any(c.id == RESP for c in pb.graveyard)
    assert "on_trigger" in g.history
    assert pb.health == 30 and pb.shield == 5  # A 的牌效果不结算（后手护甲也在）
    assert pa.orb == 8                        # A 的费用已付不退
    assert any(c.id == vic for c in pa.graveyard)


def test_response_quota_one_per_timing(db, make_game):
    """同一时机（一次用牌）至多成功结算一张响应牌；未结算者留在手牌。"""
    _response(db, RESP)
    _response(db, 10010254)
    vic = 10010152
    db.cards[vic] = F.card(vic, shikigami=100101, level=1, token=True, steps=[])
    g, pa, pb = _game(make_game)
    pb.orb = 2
    give(g, 1, RESP)
    give(g, 1, 10010254)
    play(g, 0, vic)
    assert g.history.count("on_trigger") == 1  # 只结算一张
    left = [c.id for c in pb.hand if c.id in (RESP, 10010254)]
    assert len(left) == 1                      # 另一张留手（复查不占名额）


# ---------- 吾即正义 transform ----------

def _justice(db, cid, **kw):
    kw.setdefault("keywords", ["fast"])
    db.cards[cid] = F.card(
        cid, shikigami=100101, level=1, cost=1, token=True,
        alt_remove_keywords=["fast"],
        steps=[F.Step(op="damage", amount=1, target=T(kind="all", pool="enemy_player"))],
        alt_effects=F.block(F.Step(op="damage", amount=5,
                                   target=T(kind="all", pool="enemy_player"))), **kw)


def test_transform_switches_to_alt_effects(db, make_game):
    """transformed 置位后：本局同名卡全部改用 alt_effects（含新生成的）、失去瞬发。"""
    _justice(db, ALT)
    g, pa, pb = _game(make_game)
    pb.shield = 0
    cdef = db.cards[ALT]
    inst = give(g, 0, ALT)
    assert g._effective_cost(pa, cdef, card=inst) == 0   # 瞬发免费
    pa.card_mods[ALT] = {"transformed": 1}               # 模拟 add_mod(to=persistent) 置位
    assert g._effective_cost(pa, cdef, card=inst) == 1   # 变为后失去瞬发
    g.apply({"op": "play_card", "uid": inst.uid})
    assert pb.health == 25                               # alt_effects 5 伤
    assert pa.orb == 8                                   # 费用照付
    inst2 = give(g, 0, ALT)                              # 新生成的同名卡同样变为
    g.apply({"op": "play_card", "uid": inst2.uid})
    assert pb.health == 20
    assert pa.orb == 7


def test_transform_via_triggers_add_mod(db, make_game):
    """计数触发用现有 triggers + add_mod(to=persistent) 表达：置位后改用 alt。"""
    _justice(db, ALT2, keywords=[])
    db.cards[ALT2].triggers = [F.EffectBlock(
        when="on_card_played",
        steps=[F.Step(op="add_mod", to="persistent", key="transformed",
                      amount=1, cap=1)])]
    g, pa, pb = _game(make_game)
    pb.shield = 0
    play(g, 0, ALT2)                           # 未变为：1 伤；触发器置位
    assert pb.health == 29
    assert pa.card_mods[ALT2]["transformed"] == 1
    play(g, 0, ALT2)                           # 已变为：5 伤
    assert pb.health == 24


# ---------- 金风流羽动态费用 / 黄金羽计数 ----------

def test_cost_zero_if_ext(db, make_game):
    """cost_zero_if: 对应 ext 键非 0 时费用为 0（本回合使用过黄金羽）。"""
    db.cards[DYN] = F.card(DYN, shikigami=100101, level=1, cost=1, token=True,
                           cost_zero_if={"ext": "feather_used_turn"}, steps=[])
    g, pa, pb = _game(make_game)
    play(g, 0, DYN)
    assert pa.orb == 8                          # 未使用过黄金羽：照付 1 费
    pa.ext["feather_used_turn"] = 1
    play(g, 0, DYN)
    assert pa.orb == 8                          # 动态费用：0 费


def test_golden_feather_accounting(db, make_game):
    """使用 tags 含 golden_feather 的牌：game/turn 两级计数；turn 键回合开始清除。"""
    db.cards[FEATHER] = F.card(FEATHER, shikigami=100101, level=1, cost=1,
                               token=True, tags=["golden_feather"], steps=[])
    g, pa, pb = _game(make_game)
    play(g, 0, FEATHER)
    play(g, 0, FEATHER)
    assert pa.ext["feather_used_game"] == 2
    assert pa.ext["feather_used_turn"] == 2
    pass_turns(g, 2)                            # A 第 2 回合开始
    assert "feather_used_turn" not in pa.ext    # turn 级键清除
    assert pa.ext["feather_used_game"] == 2     # game 级不清
