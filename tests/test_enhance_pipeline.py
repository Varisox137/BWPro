"""增强装配管线测试：击杀标记（persistent store）、手牌累积（to=hand）、
卡牌光环（card_auras）、战斗绑定一次性触发（temp_grants）、打出装配快照。

对应 docs/enhance-design.md 即时装配模型与 thoughts.txt 妖刀姬/兵俑卡面。
测试辅助卡使用衍生号段（61+，token=True）；0 号位式神（100101）充当妖刀姬、
1 号位（100102）充当兵俑。
"""
from core.model import Ref
from tests import factories as F
from tests.factories import give, move

T = F.T
SELF = T(kind="self")
SELF_PLAYER = T(kind="all", pool="self_player")


def _jingu_card(db, cid: int = 10010161, sid: int = 100101) -> int:
    """禁锢之刀型战斗牌：enhance 战力 + 本局击杀计数触发器（persistent）。"""
    db.cards[cid] = F.card(
        cid, shikigami=sid, card_type="combat",
        steps=[F.Step(op="buff_power", amount={"enhance": True, "base": 0}, target=SELF),
               F.Step(op="gain_shield", amount=2, target=SELF)],
        triggers=[F.EffectBlock(
            when="on_shikigami_defeated",
            condition={"victim_kind": "shikigami",
                       "source_side": "friendly", "source_shikigami": sid},
            steps=[F.Step(op="add_mod", to="persistent", key="enhance", amount=2)],
        )],
        token=True)
    return cid


def _buxiang_card(db, cid: int = 10010162, sid: int = 100101) -> int:
    """不祥之刃型战斗牌：战斗中击杀敌方式神 → 抽 1（temp_grants）。"""
    db.cards[cid] = F.card(
        cid, shikigami=sid, card_type="combat",
        steps=[F.Step(op="gain_shield", amount=1, target=SELF)],
        temp_grants=[F.EffectBlock(
            when="on_shikigami_defeated",
            condition={"victim_side": "enemy", "victim_kind": "shikigami",
                       "source_shikigami": "self"},
            steps=[F.Step(op="draw", count=1, target=SELF_PLAYER)],
        )],
        token=True)
    return cid


def _chongzhuang_card(db, cid: int = 10010263) -> int:
    """冲撞型战斗牌：己方回合开始兵俑在战斗区 → 手牌实例 +1/+1（to=hand）。"""
    db.cards[cid] = F.card(
        cid, shikigami=100102, card_type="combat", level=2,
        steps=[F.Step(op="buff_power", amount={"enhance": True, "base": 2}, target=SELF),
               F.Step(op="gain_shield", amount={"enhance": True, "base": 2}, target=SELF)],
        triggers=[F.EffectBlock(
            when="on_turn_start",
            condition={"player": "self", "shikigami_in_combat": 100102},
            steps=[F.Step(op="add_mod", to="hand", key="enhance", amount=1)],
        )],
        token=True)
    return cid


def _yaodao_base_ability(db) -> None:
    """妖刀姬基础能力（原版）：对敌方牌手造成任意伤害 → 本回合她的战斗牌具有[瞬发]。"""
    db.shikigami[100101].ability = F.EffectBlock(
        when="on_player_damaged",
        condition={"source_shikigami": "self"},
        steps=[F.Step(op="card_aura", shikigami="self", card_type="combat",
                      keywords=["fast"])],
    )


def _awaken_yaodao(db, cid: int = 10010166) -> int:
    """觉醒·妖刀姬：+1/+1 永久；进场/复活授一次性迅捷；伤害牌手 → 战斗牌不耗鬼火。"""
    db.cards[cid] = F.card(
        cid, level=3, subtype="awaken",
        steps=[F.Step(op="buff_power", amount=1, perm=True, target=SELF),
               F.Step(op="buff_health", amount=1, perm=True, target=SELF)],
        abilities=[
            F.EffectBlock(
                when="on_awakened", condition={"target_shikigami": "self"},
                steps=[F.Step(op="grant_keyword", keyword="haste", target=SELF)]),
            F.EffectBlock(
                when="on_shikigami_revived", condition={"shikigami_shikigami": "self"},
                steps=[F.Step(op="grant_keyword", keyword="haste", target=SELF)]),
            F.EffectBlock(
                when="on_player_damaged",
                condition={"source_shikigami": "self"},
                steps=[F.Step(op="card_aura", shikigami="self", card_type="combat",
                              cost_zero=True)]),
        ],
        token=True)
    return cid


# ---------- 禁锢之刀：击杀标记 + persistent store + 打出装配 ----------

def test_jingu_kill_counter_and_snapshot(db, make_game):
    """禁锢之刀：每次击杀 +2 累积；打出时装配快照——结算中的新击杀不回溯本次战力。"""
    cid = _jingu_card(db)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 3
    a_ref = Ref(player=0, shikigami=0)
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99, a_ref, kind="combat")
    g._drain_queue()  # 直调伤害管线后手动排空（on_shikigami_defeated 为延时时机）
    assert pa.card_mods[cid]["enhance"] == 2
    g.deal_to_shikigami(Ref(player=1, shikigami=1), 99, a_ref, kind="combat")
    g._drain_queue()
    assert pa.card_mods[cid]["enhance"] == 4
    # 打出：战力 = 基础 3 + 快照 4 = 7；被攻击者 8 血 → 剩 1（若回溯新击杀会是 9 伤害）
    move(g, 1, 2)
    b = g.state.players[1].shikigami[2]  # 2/6
    b.health = 8
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert b.health == 1


def test_jingu_counter_scoping(db, make_game):
    """禁锢之刀计数归属（原版）：消灭己方式神（如伤害转移）也计数；
    敌方同名式神的击杀只进敌方 store。"""
    cid = _jingu_card(db)
    g = make_game()
    pa = g.state.players[0]
    pb = g.state.players[1]
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, Ref(player=0, shikigami=0))
    g._drain_queue()  # 直调伤害管线后手动排空（on_shikigami_defeated 为延时时机）
    assert pa.card_mods[cid]["enhance"] == 2  # 消灭己方式神也计数（原版）
    g.deal_to_shikigami(Ref(player=0, shikigami=2), 99, Ref(player=1, shikigami=0), kind="combat")
    g._drain_queue()
    assert pa.card_mods[cid]["enhance"] == 2   # 敌方妖刀姬的击杀不进我方 store
    assert pb.card_mods[cid]["enhance"] == 2   # 计入敌方自己的 store


# ---------- 不祥之刃：战斗绑定一次性触发 ----------

def test_buxiang_kill_draw(db, make_game):
    """不祥之刃：此战斗中消灭敌方式神 → 抽 1；触发后注册表清空。"""
    cid = _buxiang_card(db)
    g = make_game()
    move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    b.health = 2  # 攻击 3 击杀
    pa = g.state.players[0]
    n0 = len(pa.hand)
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert b.defeated
    assert len(pa.hand) == n0 + 1  # give+1、play-1、draw+1
    assert g.state.temp_grants == []


def test_buxiang_no_kill_grant_expires(db, make_game):
    """不祥之刃：未消灭则不抽；战斗终止点移除未使用的临时触发。"""
    cid = _buxiang_card(db)
    g = make_game()
    move(g, 1, 0)
    b = g.state.players[1].shikigami[0]  # 3/4，攻击 3 杀不死
    pa = g.state.players[0]
    n0 = len(pa.hand)
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert not b.defeated
    assert len(pa.hand) == n0  # give+1、play-1，无抽牌
    assert g.state.temp_grants == []


# ---------- 冲撞：手牌实例累积（to=hand） ----------

def test_chongzhuang_accumulate_and_play(db, make_game):
    """冲撞：兵俑在战斗区的己方回合开始 +1/+1（按手牌实例）；打出战力/护甲各含 enhance。"""
    cid = _chongzhuang_card(db)
    g = make_game()
    pa = g.state.players[0]
    s = pa.shikigami[1]  # 兵俑 1/6
    s.level = 2
    c = give(g, 0, cid)
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 2 回合开始：兵俑不在战斗区
    assert c.mods.get("enhance", 0) == 0
    move(g, 0, 1)
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 3 回合开始：+1（随后兵俑退回准备区）
    assert c.mods["enhance"] == 1
    move(g, 0, 1)
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 4 回合开始：再 +1
    assert c.mods["enhance"] == 2
    # 打出：战力 2+2=4（总力量 1+4=5 击杀 3/4）；护甲 2+2=4，吃反击 3 后剩 1
    pa.orb = 2
    move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    g.apply({"op": "play_card", "uid": c.uid})
    assert b.defeated
    assert s.shield == 1
    assert s.health == 6


# ---------- 妖刀姬基础能力：卡牌光环（[瞬发]） ----------

def test_yaodao_aura_grants_fast(db, make_game):
    """妖刀姬能力：对牌手战斗伤害后，她的战斗牌获得[瞬发]（0 费），法术牌不受影响。"""
    _yaodao_base_ability(db)
    combat_cid, spell_cid = 10010164, 10010165
    db.cards[combat_cid] = F.card(combat_cid, card_type="combat", steps=[], token=True)
    db.cards[spell_cid] = F.card(spell_cid, card_type="spell", steps=[], token=True)
    g = make_game()
    pa = g.state.players[0]
    pl = g.state.players[1]
    pl.shield = 0
    pa.orb = 3
    g.apply({"op": "assault", "index": 0})  # 费 1 鬼火直击牌手 → 光环登记
    assert pl.health == 27
    assert pa.orb == 2
    assert len(pa.card_auras) == 1
    g.apply({"op": "play_card", "uid": give(g, 0, combat_cid).uid})
    assert pa.orb == 2  # 战斗牌瞬发：0 费
    g.apply({"op": "play_card", "uid": give(g, 0, spell_cid).uid})
    assert pa.orb == 1  # 法术牌不受光环影响：照付 1 费


def test_yaodao_aura_expires_at_own_turn_start(db, make_game):
    """妖刀姬能力的光环（scope="turn"）：己方回合开始清除，战斗牌恢复原价。"""
    _yaodao_base_ability(db)
    combat_cid = 10010164
    db.cards[combat_cid] = F.card(combat_cid, card_type="combat", steps=[], token=True)
    g = make_game()
    pa = g.state.players[0]
    g.state.players[1].shield = 0
    g.apply({"op": "assault", "index": 0})
    assert len(pa.card_auras) == 1
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 2 回合开始：光环清除
    assert pa.card_auras == []
    orb0 = pa.orb
    g.apply({"op": "play_card", "uid": give(g, 0, combat_cid).uid})
    assert pa.orb == orb0 - 1  # 恢复 1 费


# ---------- 觉醒·妖刀姬 ----------

def test_awaken_yaodao_haste_and_cost_zero(db, make_game):
    """觉醒·妖刀姬：打出授一次性迅捷；伤害牌手后战斗牌不耗鬼火（连续多张、不占瞬发名额）。"""
    cid = _awaken_yaodao(db)
    c1, c2 = 10010167, 10010168
    for c in (c1, c2):
        db.cards[c] = F.card(c, card_type="combat", steps=[], token=True)
    g = make_game()
    pa = g.state.players[0]
    a = pa.shikigami[0]
    a.level = 3
    pl = g.state.players[1]
    pl.shield = 0
    pa.orb = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})  # 费 1 → 剩 2
    assert a.awakened == cid
    assert "haste" in a.one_shot_keywords  # 觉醒替换进场：授一次性迅捷
    g.apply({"op": "assault", "index": 0})  # 迅捷免鬼火直击牌手 → cost_zero 光环
    assert pa.orb == 2
    assert "haste" not in a.one_shot_keywords  # 一次性迅捷已消耗
    assert any(x.get("cost_zero") for x in pa.card_auras)
    g.apply({"op": "play_card", "uid": give(g, 0, c1).uid})
    g.apply({"op": "play_card", "uid": give(g, 0, c2).uid})
    assert pa.orb == 2       # 两张战斗牌均 0 费
    assert not pa.fast_used  # 不耗鬼火 ≠ 瞬发，不占瞬发名额


def test_fast_card_under_cost_zero_aura_keeps_slot(db, make_game):
    """瞬发卡命中 cost_zero 光环：免费由光环提供，不占用瞬发名额。"""
    cid = _awaken_yaodao(db)
    c1 = 10010169
    db.cards[c1] = F.card(c1, card_type="combat", keywords=["fast"], steps=[], token=True)
    g = make_game()
    pa = g.state.players[0]
    a = pa.shikigami[0]
    a.level = 3
    g.state.players[1].shield = 0
    pa.orb = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    g.apply({"op": "assault", "index": 0})  # 迅捷免鬼火直击牌手 → cost_zero 光环
    assert any(x.get("cost_zero") for x in pa.card_auras)
    g.apply({"op": "play_card", "uid": give(g, 0, c1).uid})  # 瞬发卡，但本次免费来自光环
    assert pa.orb == 2       # 光环免费
    assert not pa.fast_used  # 不占用瞬发名额


def test_awaken_yaodao_revive_grants_haste(db, make_game):
    """觉醒·妖刀姬：复活时觉醒能力再次进场 → 重新获得一次性迅捷。"""
    cid = _awaken_yaodao(db)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.level = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert "haste" in a.one_shot_keywords
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert a.defeated
    assert "haste" not in a.one_shot_keywords  # 气绝清除一次性关键字
    a.revive_countdown = 0
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 回合开始：复活
    assert not a.defeated
    assert "haste" in a.one_shot_keywords  # 复活再次获得
