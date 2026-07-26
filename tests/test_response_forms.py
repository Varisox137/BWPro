"""响应插入使用 / 延迟触发 / 伤害上限 / 激怒与尘缚之阵 / 进场时形态效果测试。

对应 thoughts.txt 第五批卡牌（会、援护、尘刀、古尘之盾、不动如山、森罗之阵、
古尘之壁、尘缚之阵、见切、风符·瞬响应）与 rules.md:52 响应战斗牌锚点。
测试辅助卡使用衍生号段（51+）；角色位约定：
0=白狼位（100101 3/4）、1=兵俑位（100102 1/6）、2=妖刀姬位（100103 2/6）、3=一目连位（100104 2/5）。

响应测试通用结构：A 回合内 debug_move 己方式神进战斗区 + give 响应牌，
end_turn 到 B 回合后 B 出击（3/4 攻击者）→ on_before_assault（即时时机）插入结算 A 的响应。
注意：敌方战斗区式神会在其己方回合开始退回，需"敌方战斗区有人"的场景在敌方回合内 debug_move。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import give

T = F.T

BAI, BAI_IDX = 100101, 0     # 白狼位 3/4
BING, BING_IDX = 100102, 1   # 兵俑位 1/6
YAO, YAO_IDX = 100103, 2     # 妖刀姬位 2/6
LIAN, LIAN_IDX = 100104, 3   # 一目连位 2/5

JIE_QIE = 10010351   # 见切：响应战斗牌 +1 力量 + 免疫战斗伤害
SHUN = 10010451      # 风符·瞬：响应形态 6/9
PO = 10010452        # 破型：倒计时形态，投射 3
DUN = 10010251       # 古尘之盾：响应 +5 甲
YUAN_HU = 10010151   # 援护：响应打白狼力量值
HUI = 10010152       # 会：延迟 8 伤
CHEN_DAO = 10010252  # 尘刀：护甲快照战力
SEN_LUO = 10010253   # 森罗之阵：伤害上限
BU_DONG = 10010254   # 不动如山：进场进战斗区 + 回合开始加攻
BI = 10010255        # 古尘之壁：按护甲强化其他式神生命
FU = 10010256        # 尘缚之阵：激怒 + 战斗区锁定
CC = 10010257        # 兵俑战斗牌（锁定测试用）
SUMMON_DEF = 10010399  # 召唤物定义
SUMMON = 10010153    # 召唤法术（锁定测试用）


# ---------- 卡牌构造 ----------

def _jie_qie(db, cid=JIE_QIE):
    db.cards[cid] = F.card(
        cid, shikigami=YAO, card_type="combat", cost=1, level=1,
        keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"victim_shikigami": YAO}},
        steps=[F.Step(op="buff_power", amount=1, target=T(kind="self")),
               F.Step(op="battle_immunity", target=T(kind="self"))])
    return cid


def _shun(db, cid=SHUN):
    db.cards[cid] = F.card(
        cid, shikigami=LIAN, card_type="form", level=2,
        form_power=6, form_health=9, keywords=["fast", "trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"victim_shikigami": LIAN}})
    return cid


def _po(db, cid=PO):
    """破型：倒计时 2，投射 3。"""
    db.cards[cid] = F.card(
        cid, shikigami=LIAN, card_type="form", level=1,
        form_power=3, form_health=6, countdown=2, token=True,
        countdown_effects=F.block(
            F.Step(op="damage", amount=3, target=T(kind="all", pool="projectile"))))
    return cid


def _ichimokuren(db):
    """一目连基础能力：形态离场/被消灭时触发其倒计时效果。"""
    db.shikigami[LIAN].ability = F.EffectBlock(
        when="on_form_destroyed", condition={"target_shikigami": "self"},
        steps=[F.Step(op="trigger_form_countdown")])


def _dun(db, cid=DUN):
    db.cards[cid] = F.card(
        cid, shikigami=BING, cost=1, level=1, keywords=["trigger"], token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        when="on_before_assault",
        block_kw={"condition": {"victim_shikigami": BING}},
        steps=[F.Step(op="gain_shield", amount=5)])
    return cid


def _yuan_hu(db, cid=YUAN_HU):
    db.cards[cid] = F.card(
        cid, shikigami=BAI, cost=1, level=2, keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"victim_side": "friendly", "victim_kind": "shikigami",
                                "victim_not_shikigami": BAI}},
        steps=[F.Step(op="damage", amount={"power_of": "source"},
                      target=T(kind="all", pool="enemy_combat"))])
    return cid


def _hui(db, cid=HUI):
    db.cards[cid] = F.card(
        cid, shikigami=BAI, cost=1, level=2, token=True,
        target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="delay_grant", when="on_turn_start",
                      condition={"player": "self"},
                      steps=[{"op": "damage", "amount": 8}])])
    return cid


def _chen_dao(db, cid=CHEN_DAO):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="combat", cost=1, level=1, token=True,
        steps=[F.Step(op="buff_power", amount={"shield_of": "self"}, target=T(kind="self"))])
    return cid


def _sen_luo(db, cid=SEN_LUO):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="form", level=2,
        form_power=4, form_health=7, token=True,
        steps=[F.Step(op="gain_shield", amount=2, target=T(kind="self"))],
        abilities=[F.EffectBlock(
            when="on_damage_start", condition={"victim_shikigami": "self"},
            steps=[F.Step(op="cap_damage", to="shield")])])
    return cid


def _bu_dong(db, cid=BU_DONG):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="form", level=2,
        form_power=1, form_health=9, token=True,
        steps=[F.Step(op="enter_combat", target=T(kind="self"))],
        abilities=[F.EffectBlock(
            when="on_turn_start",
            condition={"player": "self", "shikigami_in_combat": BING},
            steps=[F.Step(op="buff_power", amount=3, perm=True, target=T(kind="self"))])])
    return cid


def _bi(db, cid=BI):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="form", level=3,
        form_power=5, form_health=10, token=True,
        steps=[F.Step(op="buff_health", amount={"shield_of": "source"}, perm=True,
                      target=T(kind="all", pool="friendly_others"))])
    return cid


def _fu(db, cid=FU):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="form", level=3,
        form_power=5, form_health=9, tags=["combat_lock"], token=True,
        target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="grant_keyword", keyword="enraged")])
    return cid


def _summon_card(db):
    db.shikigami[SUMMON_DEF] = F.shiki(SUMMON_DEF, kind="summon", power=0, health=3)
    db.cards[SUMMON] = F.card(SUMMON, shikigami=BAI, token=True,
                              steps=[F.Step(op="summon", shikigami=SUMMON_DEF)])


# ---------- 通用辅助 ----------

def _play(g, pi, cid, target=None):
    cmd = {"op": "play_card", "uid": give(g, pi, cid).uid}
    if target is not None:
        cmd["target"] = target
    g.apply(cmd)


def _move(g, pi, idx):
    g.apply({"op": "debug_move", "args": {"player": pi, "index": idx}})


def _set_shield(g, pi, idx, value):
    g.apply({"op": "debug_set_stat",
             "args": {"target": {"player": pi, "shikigami": idx}, "key": "shield", "value": value}})


def _pass(g, n=1):
    for _ in range(n):
        g.apply({"op": "end_turn"})


# ---------- 1/2. 见切（响应战斗牌插入使用） ----------

def test_jieqie_response_insert(db, make_game):
    """见切响应：妖刀姬被出击时自动使用——+1 战力、免疫战斗伤害、反击照常；
    加成持续到被插入的战斗结束后核销；牌入墓地；只占一张响应名额。"""
    _jie_qie(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[YAO_IDX].level = 1
    _move(g, 0, YAO_IDX)                 # 妖刀姬 2/6 进战斗区
    give(g, 0, JIE_QIE)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})   # B0 3/4 出击
    yao, atk = a.shikigami[YAO_IDX], b.shikigami[0]
    assert yao.health == 6               # 免疫战斗伤害
    assert atk.health == 1               # 反击 2+1=3
    assert yao.eff_power == 2            # 战力随被插入的战斗结束核销
    assert a.orb == 0                    # 响应付 1 火（A 首回合留 1 火）
    assert not any(c.id == JIE_QIE for c in a.hand)
    assert any(c.id == JIE_QIE for c in a.graveyard)
    assert g.history.count("on_trigger") == 1
    assert g.history.count("on_card_played") == 1


def test_jieqie_active_play(db, make_game):
    """见切主动使用：正常战斗牌流程（回归防呆）。"""
    _jie_qie(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[YAO_IDX].level = 1
    b.shield = 0
    _play(g, 0, JIE_QIE)
    yao = a.shikigami[YAO_IDX]
    assert b.health == 27                # 2+1=3 直击牌手
    assert a.combat_index == YAO_IDX
    assert yao.eff_power == 2            # 战力战后清除
    assert any(c.id == JIE_QIE for c in a.graveyard)


# ---------- 3. 风符·瞬（响应形态牌插入使用） ----------

def test_shun_response_attach(db, make_game):
    """风符·瞬响应：一目连被攻击时立即结附 6/9——受 3 余 6，反击 6 击杀攻击者；
    瞬发响应免费（0 火可触发）。"""
    _shun(db)
    g = make_game()
    a, b = g.state.players
    s = a.shikigami[LIAN_IDX]
    s.level = 2
    _move(g, 0, LIAN_IDX)                # 一目连 2/5 进战斗区
    give(g, 0, SHUN)
    g.apply({"op": "end_turn"})
    a.orb = 0                            # 瞬发：本半回合第一张免费
    g.apply({"op": "assault", "index": 0})
    assert s.form is not None and s.form.id == SHUN
    assert s.health == 6                 # 9 - 3
    assert b.shikigami[0].defeated       # 反击 6
    assert not any(c.id == SHUN for c in a.hand)


def test_shun_response_replaces_po_triggers_countdown(db, make_game):
    """先结附破再响应瞬：旧形态（破）被替换离场时触发一目连能力，投射 3 命中攻击者。"""
    _shun(db)
    _po(db)
    _ichimokuren(db)
    g = make_game()
    a, b = g.state.players
    s = a.shikigami[LIAN_IDX]
    s.level = 2
    _play(g, 0, PO)                      # A 回合：结附破（1 火）
    _move(g, 0, LIAN_IDX)
    give(g, 0, SHUN)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})   # B0 3/4 出击
    atk = b.shikigami[0]
    assert s.form is not None and s.form.id == SHUN   # 破已被瞬替换
    assert "on_form_destroyed" in g.history
    assert s.health == 6                 # 攻击 3：9 - 3
    assert atk.defeated                  # 投射 3 + 反击 6


# ---------- 4. 古尘之盾（choose 自动选目标） ----------

def test_dun_response_shield_before_damage(db, make_game):
    """古尘之盾响应：兵俑被攻击时 +5 护甲先于伤害结算；choose 自动选择被攻击者。"""
    _dun(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 1
    _move(g, 0, BING_IDX)                # 兵俑 1/6 进战斗区
    give(g, 0, DUN)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    bing, atk = a.shikigami[BING_IDX], b.shikigami[0]
    assert bing.shield == 2              # 5 - 3
    assert bing.health == 6              # 护甲全吸收
    assert atk.health == 3               # 反击 1
    assert any(c.id == DUN for c in a.graveyard)


# ---------- 5. 援护（_not_shikigami / power_of 动态数值） ----------

def test_yuanhu_response_hits_attacker(db, make_game):
    """援护响应：己方其他式神被攻击时，对攻击者造成白狼力量值伤害（战斗继续）。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    a.shikigami[BING_IDX].level = 1
    _move(g, 0, BING_IDX)                # 兵俑进战斗区，白狼留准备区
    give(g, 0, YUAN_HU)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    atk, bing = b.shikigami[0], a.shikigami[BING_IDX]
    assert atk.defeated                  # 援护 3 + 反击 1
    assert bing.health == 3              # 受攻击 3
    assert any(c.id == YUAN_HU for c in a.graveyard)


def test_yuanhu_response_kill_aborts_battle(db, make_game):
    """援护直接击杀攻击者：战斗中止，被攻击者无伤。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    a.shikigami[BING_IDX].level = 1
    _move(g, 0, BING_IDX)
    give(g, 0, YUAN_HU)
    g.apply({"op": "end_turn"})
    atk = b.shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 1, "shikigami": 0}, "key": "health", "value": 2}})
    g.apply({"op": "assault", "index": 0})
    assert atk.defeated                  # 援护 3 直接击杀
    assert a.shikigami[BING_IDX].health == 6   # 战斗中止，未受攻击


def test_yuanhu_not_triggered_when_bailang_attacked(db, make_game):
    """白狼自己被攻击时不触发（victim_not_shikigami）。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    _move(g, 0, BAI_IDX)                 # 白狼自己进战斗区
    give(g, 0, YUAN_HU)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.shikigami[BAI_IDX].health == 1    # 4 - 3，援护未触发
    assert b.shikigami[0].health == 1          # 反击 3
    assert "on_trigger" not in g.history
    assert any(c.id == YUAN_HU for c in a.hand)


def test_yuanhu_active_play_hits_enemy_combat(db, make_game):
    """援护主动使用：对敌方战斗区式神造成白狼力量值伤害。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    _move(g, 1, 0)                       # A 回合内敌方战斗区驻留
    _play(g, 0, YUAN_HU)
    assert b.shikigami[0].health == 1    # 4 - 3


# ---------- 6. 同时机两张响应牌只结算第一张 ----------

def test_one_response_per_timing(db, make_game):
    """同一时机两张古尘之盾：只结算第一张，第二张留在手牌、不付费。"""
    _dun(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 1
    _move(g, 0, BING_IDX)
    give(g, 0, DUN)
    give(g, 0, DUN)
    g.apply({"op": "end_turn"})
    a.orb = 2                            # 两张都付得起——隔离"同时机限一张"
    g.apply({"op": "assault", "index": 0})
    bing = a.shikigami[BING_IDX]
    assert bing.shield == 2              # 只 +5 一次（5 - 3）
    assert g.history.count("on_trigger") == 1
    assert a.orb == 1                    # 第二张未付费
    assert len([c for c in a.hand if c.id == DUN]) == 1
    assert len([c for c in a.graveyard if c.id == DUN]) == 1


# ---------- 7. 会（延迟触发） ----------

def test_hui_delayed_damage(db, make_game):
    """会：指定敌方式神，下个己方回合开始造成 8 点；触发后条目移除不二次触发。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    _play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    assert len(a.shikigami[BAI_IDX].delayed) == 1
    _pass(g, 2)                          # B 回合 → A 第 2 回合开始触发
    assert b.shikigami[0].defeated       # 8 伤击杀 4 血
    assert a.shikigami[BAI_IDX].delayed == []
    _pass(g, 2)                          # 再过一轮：不二次触发（无异常）


def test_hui_cleared_when_bailang_defeated(db, make_game):
    """白狼先气绝：延迟能力消失，不触发。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    _play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    g.deal_to_shikigami(Ref(player=0, shikigami=BAI_IDX), 99, None)
    g._drain_queue()
    assert a.shikigami[BAI_IDX].defeated
    assert a.shikigami[BAI_IDX].delayed == []
    _pass(g, 2)
    assert b.shikigami[0].health == 4    # 无伤


def test_hui_target_already_defeated_no_error(db, make_game):
    """目标已气绝：触发时无伤且不报错；条目照常消耗。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    _play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99, None)
    g._drain_queue()
    assert b.shikigami[0].defeated
    _pass(g, 2)                          # 触发但目标气绝：无伤不报错
    assert a.shikigami[BAI_IDX].delayed == []


# ---------- 8. 尘刀（护甲快照战力） ----------

def test_chendao_power_snapshot(db, make_game):
    """尘刀：按打出瞬间护甲获得战力（3 甲 → 战力 +3，总 4 力量直击）。"""
    _chen_dao(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 1
    b.shield = 0
    _set_shield(g, 0, BING_IDX, 3)
    _play(g, 0, CHEN_DAO)
    bing = a.shikigami[BING_IDX]
    assert b.health == 26                # 1+3=4 直击牌手
    assert bing.combat_power == 0        # 战力战后清除
    assert bing.shield == 3              # 护甲保留


# ---------- 9. 森罗之阵（伤害上限） ----------

def test_senluo_damage_cap(db, make_game):
    """森罗之阵：进场 +2 甲；有护甲时至多受到等于护甲值的伤害。"""
    _sen_luo(db)
    g = make_game()
    a = g.state.players[0]
    a.shikigami[BING_IDX].level = 2
    _play(g, 0, SEN_LUO)
    bing = a.shikigami[BING_IDX]
    assert bing.shield == 2              # 进场 +2 甲
    assert bing.health == 7              # 形态 4/7
    _set_shield(g, 0, BING_IDX, 5)
    g.deal_to_shikigami(Ref(player=0, shikigami=BING_IDX), 8, None)
    g._drain_queue()
    assert bing.shield == 0              # 8 → 截为 5，护甲全吸收
    assert bing.health == 7
    g.deal_to_shikigami(Ref(player=0, shikigami=BING_IDX), 4, None)
    g._drain_queue()
    assert bing.health == 3              # 0 甲：全额
    _set_shield(g, 0, BING_IDX, 5)
    g.deal_to_shikigami(Ref(player=0, shikigami=BING_IDX), 3, None)
    g._drain_queue()
    assert bing.shield == 2              # 3 < 5 不截
    assert bing.health == 3


# ---------- 10. 不动如山（进场进战斗区 + 回合开始加攻） ----------

def test_budong_enter_combat_and_power_gain(db, make_game):
    """不动如山：进场移入战斗区；己方回合开始（on_turn_start 早于延时移回执行）
    在战斗区则 +3 永久力量；退回后不加；再进战斗区下轮再 +3（累加）。"""
    _bu_dong(db)
    g = make_game()
    a = g.state.players[0]
    a.shikigami[BING_IDX].level = 2
    _play(g, 0, BU_DONG)
    bing = a.shikigami[BING_IDX]
    assert a.combat_index == BING_IDX    # 进场移入战斗区
    assert bing.eff_power == 1           # 形态 1/9
    _pass(g, 2)                          # A 第 2 回合开始：仍在战斗区 → +3
    assert bing.eff_power == 4
    assert a.combat_index is None        # 同回合开始阶段晚些时候退回
    _pass(g, 2)                          # A 第 3 回合开始：不在战斗区 → 不加
    assert bing.eff_power == 4
    _move(g, 0, BING_IDX)                # 再进战斗区
    _pass(g, 2)                          # A 第 4 回合开始：再 +3（累加）
    assert bing.eff_power == 7


# ---------- 11. 古尘之壁（friendly_others / shield_of） ----------

def test_bi_buffs_others_by_shield(db, make_game):
    """古尘之壁：进场时按兵俑护甲使其余己方式神 +生命/生命上限，兵俑自身不变。"""
    _bi(db)
    g = make_game()
    a = g.state.players[0]
    for i in (YAO_IDX, LIAN_IDX):
        a.shikigami[i].level = 1         # 0 号位开局自动 1 级
    a.shikigami[BING_IDX].level = 3
    _set_shield(g, 0, BING_IDX, 3)
    _play(g, 0, BI)
    bing = a.shikigami[BING_IDX]
    assert a.shikigami[BAI_IDX].max_health == 7 and a.shikigami[BAI_IDX].health == 7   # 4+3
    assert a.shikigami[YAO_IDX].max_health == 9 and a.shikigami[YAO_IDX].health == 9   # 6+3
    assert a.shikigami[LIAN_IDX].max_health == 8 and a.shikigami[LIAN_IDX].health == 8  # 5+3
    assert bing.max_health == 10         # 兵俑自身不变（形态 5/10）


# ---------- 12. 尘缚之阵（激怒 + 战斗区锁定） ----------

def test_enraged_assault_restriction(db, make_game):
    """激怒：被激怒者可出击时其他式神不能出击；被激怒者出击后激怒移除、限制解除。"""
    _fu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1
    _play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    assert g._has_keyword(b.shikigami[BING_IDX], "enraged")
    g.apply({"op": "end_turn"})
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})      # B0 无激怒：不能出击
    g.apply({"op": "assault", "index": BING_IDX})   # 被激怒者可以
    assert not g._has_keyword(b.shikigami[BING_IDX], "enraged")  # 战斗流程中移除
    assert a.health == 29                            # B1 1 力量直击
    _pass(g, 2)
    g.apply({"op": "assault", "index": 0})          # 激怒移除后 B0 可出击
    assert a.health == 26


def test_fu_combat_zone_lock(db, make_game):
    """尘缚之阵锁定（兵俑在战斗区且敌方战斗区有式神）：召唤无效；
    敌方准备区式神不能发起无远程的战斗（出击/战斗牌）；远程可出击。"""
    _fu(db)
    _summon_card(db)
    db.cards[CC] = F.card(CC, shikigami=BING, card_type="combat", steps=[], token=True)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1
    _play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    # 移除激怒，隔离尘缚锁定效果单独测试
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 1, "shikigami": BING_IDX}, "keyword": "enraged", "remove": True}})
    _move(g, 0, BING_IDX)                # 兵俑进战斗区
    g.apply({"op": "end_turn"})
    _move(g, 1, 0)                       # B 战斗区驻留 → 锁定成立
    assert g._combat_zone_locked(1)
    # 召唤召唤物的效果无效
    b.orb = 3
    n = len(b.shikigami)
    _play(g, 1, SUMMON)
    assert len(b.shikigami) == n         # 未召唤
    assert b.combat_index == 0           # 驻留不变
    # 准备区式神不能发起无远程的战斗
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": BING_IDX})
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": give(g, 1, CC).uid})
    # 具有远程则可以出击
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 1, "shikigami": BING_IDX}, "keyword": "remote"}})
    g.apply({"op": "assault", "index": BING_IDX})
    assert a.shikigami[BING_IDX].health == 8   # 5/9 受 1（远程不受反击）


def test_fu_lock_inactive_when_bing_not_in_combat(db, make_game):
    """兵俑不在战斗区：锁定不生效，敌方准备区式神可正常出击。"""
    _fu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1
    _play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 1, "shikigami": BING_IDX}, "keyword": "enraged", "remove": True}})
    # 兵俑留在准备区
    g.apply({"op": "end_turn"})
    _move(g, 1, 0)                       # B 战斗区有人但兵俑不在战斗区
    assert not g._combat_zone_locked(1)
    g.apply({"op": "assault", "index": BING_IDX})   # 不报错
    assert a.health == 29
