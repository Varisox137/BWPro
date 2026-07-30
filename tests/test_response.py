"""响应机制主题测试：响应插入使用/延迟触发/伤害上限/激怒与尘缚之阵/进场时形态效果
（原 test_response_forms.py）+ 使用手牌前时机与无效化/transform/动态费用（原 test_before_card_play.py）。

对应 thoughts.txt 第五批卡牌（会、援护、尘刀、古尘之盾、不动如山、森罗之阵、
古尘之壁、尘缚之阵、见切、风符·瞬响应）、rules.md:52 响应战斗牌锚点、
docs/rules.md 卡牌使用事件流程与 thoughts.txt 答复 (4)(6)(8)。
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
from tests.factories import give, move, pass_turns, play

T = F.T

BAI, BAI_IDX = 100101, 0     # 白狼位 3/4
BING, BING_IDX = 100102, 1   # 兵俑位 1/6
YAO, YAO_IDX = 100103, 2     # 妖刀姬位 2/6
LIAN, LIAN_IDX = 100104, 3   # 一目连位 2/5

JIE_QIE = 10010351   # 见切：响应战斗牌 +1 力量 + 免疫战斗伤害
SHUN = 10010451      # 风符·瞬：响应形态 6/9
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


# ==========================================================================
# 响应插入使用 / 形态进场效果（原 test_response_forms.py）
# ==========================================================================

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
        steps=[F.Step(op="buff_health", amount={"shield_of": "source"},
                      target=T(kind="all", pool="friendly_others"))])
    return cid


def _fu(db, cid=FU):
    db.cards[cid] = F.card(
        cid, shikigami=BING, card_type="form", level=3,
        form_power=5, form_health=9, tags=["combat_lock", "destroy_immune"], token=True,
        target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="grant_keyword", keyword="enraged")])
    return cid


def _summon_card(db):
    db.shikigami[SUMMON_DEF] = F.shiki(SUMMON_DEF, kind="summon", power=0, health=3)
    db.cards[SUMMON] = F.card(SUMMON, shikigami=BAI, token=True,
                              steps=[F.Step(op="summon", shikigami=SUMMON_DEF)])


# ---------- 通用辅助 ----------

def _set_shield(g, pi, idx, value):
    g.apply({"op": "debug_set_stat",
             "args": {"target": {"player": pi, "shikigami": idx}, "key": "shield", "value": value}})


# ---------- 1/2. 见切（响应战斗牌插入使用） ----------

def test_jieqie_response_insert(db, make_game):
    """见切响应：妖刀姬被出击时自动使用——+1 战力、免疫战斗伤害、反击照常；
    加成持续到被插入的战斗结束后核销；牌入墓地；只占一张响应名额。"""
    _jie_qie(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[YAO_IDX].level = 1
    move(g, 0, YAO_IDX)                 # 妖刀姬 2/6 进战斗区
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
    play(g, 0, JIE_QIE)
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
    move(g, 0, LIAN_IDX)                # 一目连 2/5 进战斗区
    give(g, 0, SHUN)
    g.apply({"op": "end_turn"})
    a.orb = 0                            # 瞬发：本半回合第一张免费
    g.apply({"op": "assault", "index": 0})
    assert s.form is not None and s.form.id == SHUN
    assert s.health == 6                 # 9 - 3
    assert b.shikigami[0].defeated       # 反击 6
    assert not any(c.id == SHUN for c in a.hand)


# ---------- 4. 古尘之盾（choose 自动选目标） ----------

def test_dun_response_shield_before_damage(db, make_game):
    """古尘之盾响应：兵俑被攻击时 +5 护甲先于伤害结算；choose 自动选择被攻击者。"""
    _dun(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 1
    move(g, 0, BING_IDX)                # 兵俑 1/6 进战斗区
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
    move(g, 0, BING_IDX)                # 兵俑进战斗区，白狼留准备区
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
    move(g, 0, BING_IDX)
    give(g, 0, YUAN_HU)
    g.apply({"op": "end_turn"})
    atk = b.shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 1, "shikigami": 0}, "key": "health", "value": 2}})
    g.apply({"op": "assault", "index": 0})
    assert atk.defeated                  # 援护 3 直接击杀
    assert a.shikigami[BING_IDX].health == 6   # 战斗中止，未受攻击


def test_response_victim_not_shikigami_filter(db, make_game):
    """白狼自己被攻击时不触发（victim_not_shikigami）。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    move(g, 0, BAI_IDX)                 # 白狼自己进战斗区
    give(g, 0, YUAN_HU)
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.shikigami[BAI_IDX].health == 1    # 4 - 3，援护未触发
    assert b.shikigami[0].health == 1          # 反击 3
    assert "on_trigger" not in g.history
    assert any(c.id == YUAN_HU for c in a.hand)


def test_response_card_active_play(db, make_game):
    """援护主动使用：对敌方战斗区式神造成白狼力量值伤害。"""
    _yuan_hu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    move(g, 1, 0)                       # A 回合内敌方战斗区驻留
    play(g, 0, YUAN_HU)
    assert b.shikigami[0].health == 1    # 4 - 3


# ---------- 7. 会（延迟触发） ----------

def test_delay_grant_turn_start_damage(db, make_game):
    """会：指定敌方式神，下个己方回合开始造成 8 点；触发后条目移除不二次触发。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    assert len(a.shikigami[BAI_IDX].delayed) == 1
    pass_turns(g, 2)                          # B 回合 → A 第 2 回合开始触发
    assert b.shikigami[0].defeated       # 8 伤击杀 4 血
    assert a.shikigami[BAI_IDX].delayed == []
    pass_turns(g, 2)                          # 再过一轮：不二次触发（无异常）


def test_delay_grant_cleared_on_defeat(db, make_game):
    """白狼先气绝：延迟能力消失，不触发。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    g.deal_to_shikigami(Ref(player=0, shikigami=BAI_IDX), 99, None)
    g._drain_queue()
    assert a.shikigami[BAI_IDX].defeated
    assert a.shikigami[BAI_IDX].delayed == []
    pass_turns(g, 2)
    assert b.shikigami[0].health == 4    # 无伤


def test_hui_target_already_defeated_no_error(db, make_game):
    """目标已气绝：触发时无伤且不报错；条目照常消耗。"""
    _hui(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BAI_IDX].level = 2
    play(g, 0, HUI, target=Ref(player=1, shikigami=0))
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99, None)
    g._drain_queue()
    assert b.shikigami[0].defeated
    pass_turns(g, 2)                          # 触发但目标气绝：无伤不报错
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
    play(g, 0, CHEN_DAO)
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
    play(g, 0, SEN_LUO)
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
    play(g, 0, BU_DONG)
    bing = a.shikigami[BING_IDX]
    assert a.combat_index == BING_IDX    # 进场移入战斗区
    assert bing.eff_power == 1           # 形态 1/9
    pass_turns(g, 2)                          # A 第 2 回合开始：仍在战斗区 → +3
    assert bing.eff_power == 4
    assert a.combat_index is None        # 同回合开始阶段晚些时候退回
    pass_turns(g, 2)                          # A 第 3 回合开始：不在战斗区 → 不加
    assert bing.eff_power == 4
    move(g, 0, BING_IDX)                # 再进战斗区
    pass_turns(g, 2)                          # A 第 4 回合开始：再 +3（累加）
    assert bing.eff_power == 7


# ---------- 11. 古尘之壁（friendly_others / shield_of） ----------

def test_buff_health_amount_shield_of_source(db, make_game):
    """古尘之壁：进场时按兵俑护甲使其余己方式神 +生命/生命上限，兵俑自身不变。"""
    _bi(db)
    g = make_game()
    a = g.state.players[0]
    for i in (YAO_IDX, LIAN_IDX):
        a.shikigami[i].level = 1         # 0 号位开局自动 1 级
    a.shikigami[BING_IDX].level = 3
    _set_shield(g, 0, BING_IDX, 3)
    play(g, 0, BI)
    bing = a.shikigami[BING_IDX]
    assert a.shikigami[BAI_IDX].max_health == 7 and a.shikigami[BAI_IDX].health == 7   # 4+3
    assert a.shikigami[YAO_IDX].max_health == 9 and a.shikigami[YAO_IDX].health == 9   # 6+3
    assert a.shikigami[LIAN_IDX].max_health == 8 and a.shikigami[LIAN_IDX].health == 8  # 5+3
    assert bing.max_health == 10         # 兵俑自身不变（形态 5/10）


def test_buff_health_temp_cleared_on_defeat(db, make_game):
    """古尘之壁"获得x生命"非永久：上限增益气绝时清除（维护者答复(1)）。"""
    _bi(db)
    g = make_game()
    a = g.state.players[0]
    a.shikigami[BING_IDX].level = 3
    _set_shield(g, 0, BING_IDX, 3)
    play(g, 0, BI)
    bai = a.shikigami[BAI_IDX]
    assert bai.max_health == 7 and bai.temp_health == 3
    bai.health = 0
    g.check_defeated(Ref(player=0, shikigami=BAI_IDX))   # 气绝：临时上限清除
    assert bai.temp_health == 0 and bai.max_health == 4


def test_buff_health_not_a_heal_event(db, make_game):
    """古尘之壁"获得x生命"不算治疗：不走 heal 事件、不触发"恢复生命时"能力。"""
    _bi(db)
    db.cards[10010154] = F.card(           # 监听形态：任何治疗事件计数
        10010154, shikigami=BAI, card_type="form", level=1,
        form_power=3, form_health=4, token=True,
        abilities=[F.block(F.Step(op="bump_ext", key="heals", target=T(kind="self")),
                           when="on_heal")])
    db.cards[10010155] = F.card(           # 普通治疗牌（对照组）
        10010155, shikigami=BAI, token=True,
        steps=[F.Step(op="heal", amount=1, target=T(kind="self"))])
    g = make_game()
    a = g.state.players[0]
    a.orb = 9
    a.shikigami[BING_IDX].level = 3
    _set_shield(g, 0, BING_IDX, 3)
    play(g, 0, 10010154)                   # 白狼位结附监听形态
    play(g, 0, BI)                         # 上限增益伴随的生命上调不触发 on_heal
    bai = a.shikigami[BAI_IDX]
    assert bai.ext.get("heals", 0) == 0
    bai.health -= 2
    play(g, 0, 10010155)                   # 真实治疗触发 on_heal
    assert bai.ext["heals"] == 1


# ---------- 12. 尘缚之阵（激怒 + 战斗区锁定） ----------

def test_enraged_assault_restriction(db, make_game):
    """激怒：被激怒者可出击时其他式神不能出击；被激怒者出击后激怒移除、限制解除。"""
    _fu(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1
    play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    assert g._has_keyword(b.shikigami[BING_IDX], "enraged")
    g.apply({"op": "end_turn"})
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})      # B0 无激怒：不能出击
    g.apply({"op": "assault", "index": BING_IDX})   # 被激怒者可以
    assert not g._has_keyword(b.shikigami[BING_IDX], "enraged")  # 战斗流程中移除
    assert a.health == 29                            # B1 1 力量直击
    pass_turns(g, 2)
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
    play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    # 移除激怒，隔离尘缚锁定效果单独测试
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 1, "shikigami": BING_IDX}, "keyword": "enraged", "remove": True}})
    move(g, 0, BING_IDX)                # 兵俑进战斗区
    g.apply({"op": "end_turn"})
    move(g, 1, 0)                       # B 战斗区驻留 → 锁定成立
    assert g._combat_zone_locked(1)
    # 召唤召唤物的效果无效
    b.orb = 3
    n = len(b.shikigami)
    play(g, 1, SUMMON)
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
    play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 1, "shikigami": BING_IDX}, "keyword": "enraged", "remove": True}})
    # 兵俑留在准备区
    g.apply({"op": "end_turn"})
    move(g, 1, 0)                       # B 战斗区有人但兵俑不在战斗区
    assert not g._combat_zone_locked(1)
    g.apply({"op": "assault", "index": BING_IDX})   # 不报错
    assert a.health == 29


def test_fu_lock_blocks_response_combat_swap(db, make_game):
    """尘缚之阵：响应战斗牌插入使用会替换被锁定的战斗区式神 → 该响应不可用
    （不支付费用、不占响应名额、不触发）；若所属式神本就在战斗区则不受限。"""
    _fu(db)
    # 响应战斗牌：一目连被攻击时妖刀姬插入使用（移入战斗区会替换一目连）
    db.cards[10010352] = F.card(
        10010352, shikigami=YAO, card_type="combat", cost=1, level=1,
        keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"victim_shikigami": LIAN}},
        steps=[F.Step(op="buff_power", amount=1, target=T(kind="self"))])
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1
    b.shikigami[YAO_IDX].level = 1
    b.shikigami[LIAN_IDX].level = 1
    play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    g.apply({"op": "end_turn"})
    move(g, 1, LIAN_IDX)                # B 战斗区驻留一目连
    card = give(g, 1, 10010352)
    b.orb = 3
    g.apply({"op": "end_turn"})          # 回到 A 回合（兵俑已退回准备区）
    g.apply({"op": "assault", "index": BING_IDX})  # 兵俑出击重进战斗区 → 锁定时成立
    assert card in b.hand                # 响应受锁定不可用，未触发
    assert b.orb == 3                    # 未支付费用
    assert b.shikigami[LIAN_IDX].defeated  # 战斗仍命中原驻留者一目连（5 攻 vs 5 血）


# ---------- 13. 尘缚之阵：免疫直接消灭 ----------

DESTROY_SPELL = 10010154  # 直接消灭法术（测试用）


def _destroy_spell(db):
    db.cards[DESTROY_SPELL] = F.card(
        DESTROY_SPELL, shikigami=BAI, level=1, token=True,
        target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="destroy")])


def test_fu_destroy_immune_in_combat(db, make_game):
    """尘缚之阵：兵俑在战斗区时免疫直接消灭效果；退回准备区后不再免疫。"""
    _fu(db)
    _destroy_spell(db)
    g = make_game()
    a, b = g.state.players
    a.shikigami[BING_IDX].level = 3
    b.shikigami[BING_IDX].level = 1      # 激怒目标须在场（等级 >= 1）
    b.shikigami[BAI_IDX].level = 1
    play(g, 0, FU, target=Ref(player=1, shikigami=BING_IDX))
    bing = a.shikigami[BING_IDX]
    move(g, 0, BING_IDX)                # 兵俑进战斗区
    g.apply({"op": "end_turn"})
    b.orb = 3
    play(g, 1, DESTROY_SPELL, target=Ref(player=0, shikigami=BING_IDX))
    assert not bing.defeated and bing.health == 9   # 免疫直接消灭（形态 5/9）
    g.apply({"op": "end_turn"})
    move(g, 0, YAO_IDX)                 # 换人：兵俑退回准备区
    g.apply({"op": "end_turn"})
    b.orb = 3
    play(g, 1, DESTROY_SPELL, target=Ref(player=0, shikigami=BING_IDX))
    assert bing.defeated                 # 不在战斗区：不再免疫


# ==========================================================================
# 使用手牌前时机与无效化 / transform / 动态费用（原 test_before_card_play.py）
# ==========================================================================
#
# 出牌流程在合法性检查与支付之后、效果结算之前 emit on_before_card_play
# （即时时机，payload 含可变 nullified 标记）；
# 无效化：跳过效果块、牌照常离手进墓地、费用/瞬发名额已付不退；
# 一次性"下一次敌方用牌前无效化"能力用 delay_grant(scope="turn") 表达，
# 响应牌则直接把 effects.when 挂在 on_before_card_play。
# 0 号位（100101）为己方主体，1 号位（100102）为响应/对方用牌所属。

MAYIN = 10010151      # 魔音扰心（主动使用：登记一次性无效化延迟能力）
NULL_SPELL = 10010251  # 对方将被无效化的瞬发伤害牌
PLAIN_SPELL = 10010252  # 对方普通伤害牌
RESP = 10010253        # 魔音扰心（响应牌形态）
ALT = 10010154         # 吾即正义（transform）
ALT2 = 10010155        # 吾即正义（triggers + add_mod 路径）
DYN = 10010156         # 金风流羽（动态费用）
FEATHER = 10010157     # 黄金羽（tags 计数）


def _bcp_game(make_game):
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
    g, pa, pb = _bcp_game(make_game)
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
    g, pa, pb = _bcp_game(make_game)
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
    g, pa, pb = _bcp_game(make_game)
    pb.orb = 2                                # 留火响应
    give(g, 1, RESP)
    play(g, 0, vic)                           # A 用牌 → B 响应无效化
    assert pb.orb == 1                        # 响应费用照付
    assert any(c.id == RESP for c in pb.graveyard)
    assert "on_trigger" in g.history
    assert pb.health == 30 and pb.shield == 5  # A 的牌效果不结算（后手护甲也在）
    assert pa.orb == 8                        # A 的费用已付不退
    assert any(c.id == vic for c in pa.graveyard)


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
    g, pa, pb = _bcp_game(make_game)
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
    g, pa, pb = _bcp_game(make_game)
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
    g, pa, pb = _bcp_game(make_game)
    play(g, 0, DYN)
    assert pa.orb == 8                          # 未使用过黄金羽：照付 1 费
    pa.ext["feather_used_turn"] = 1
    play(g, 0, DYN)
    assert pa.orb == 8                          # 动态费用：0 费


def test_tag_play_accounting_game_turn(db, make_game):
    """使用 tags 含 golden_feather 的牌：game/turn 两级计数；turn 键回合开始清除。"""
    db.cards[FEATHER] = F.card(FEATHER, shikigami=100101, level=1, cost=1,
                               token=True, tags=["golden_feather"], steps=[])
    g, pa, pb = _bcp_game(make_game)
    play(g, 0, FEATHER)
    play(g, 0, FEATHER)
    assert pa.ext["feather_used_game"] == 2
    assert pa.ext["feather_used_turn"] == 2
    pass_turns(g, 2)                            # A 第 2 回合开始
    assert "feather_used_turn" not in pa.ext    # turn 级键清除
    assert pa.ext["feather_used_game"] == 2     # game 级不清


# ==========================================================================
# 法术回响序列（spell_echo/spell_echo_recast，涅槃业火底层）
# ==========================================================================

ECHO_GRANT = 10010158  # 回响授予法术：sequence=[ECHO1, ECHO2]，once_key="nirvana"
ECHO1 = 10010159       # 回响序列第 1 张：打敌方牌手 2
ECHO2 = 10010160       # 回响序列第 2 张：打敌方牌手 3
TRIG_SPELL = 10010258  # 触发用空白法术（100102 的牌）


def _echo_setup(db):
    """回响测试数据：授予卡 + 序列两张打牌手法术 + 触发用空白法术。"""
    db.cards[ECHO1] = F.card(ECHO1, token=True,
                             steps=[F.dmg(2, T(kind="all", pool="enemy_player"))])
    db.cards[ECHO2] = F.card(ECHO2, token=True,
                             steps=[F.dmg(3, T(kind="all", pool="enemy_player"))])
    db.cards[ECHO_GRANT] = F.card(ECHO_GRANT, token=True, steps=[
        F.Step(op="spell_echo", sequence=[ECHO1, ECHO2], once_key="nirvana")])
    db.cards[TRIG_SPELL] = F.card(TRIG_SPELL, shikigami=100102, token=True, steps=[])


def test_spell_echo_sequence(db, make_game):
    """法术回响：持有者以外的式神从手牌使用法术 → 按序列依次凭空免费使用。"""
    _echo_setup(db)
    db.cards[10010358] = F.card(10010358, shikigami=100103, token=True, steps=[])
    db.cards[10010458] = F.card(10010458, shikigami=100104, token=True, steps=[])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    for i in (1, 2, 3):
        pa.shikigami[i].level = 1
    play(g, 0, ECHO_GRANT)
    play(g, 0, TRIG_SPELL)                # 100102 的法术 → 触发序列第 1 张
    assert pb.health == 28                # ECHO1 的 2 伤
    assert any(c.id == ECHO1 for c in pa.graveyard)  # 凭空生成，用后进墓地
    assert pa.orb == 7                    # 回响不耗鬼火（只付两张手牌费用）
    play(g, 0, TRIG_SPELL)                # 同 id 法术每回合至多触发一次
    assert pb.health == 28
    play(g, 0, 10010358)                  # 另一 id 法术 → 触发序列第 2 张
    assert pb.health == 25
    play(g, 0, 10010458)                  # 序列已走完：空操作
    assert pb.health == 25


def test_spell_echo_excludes_holder(db, make_game):
    """持有者自己的法术不触发；敌方从手牌使用法术同样触发（打敌方的牌手=己方）。"""
    _echo_setup(db)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    pa.shield = 0
    play(g, 0, ECHO_GRANT)
    play(g, 0, 10010101)                  # 持有者（100101）自己的法术 → 不触发
    assert pb.health == 30
    pass_turns(g, 1)                      # → B 回合
    pb.shikigami[1].level = 1
    pb.orb = 9
    play(g, 1, TRIG_SPELL)                # 敌方使用法术 → 触发序列第 1 张
    assert pb.health == 28                # 回响牌属持有者："敌方牌手"= 出牌方 B


def test_spell_echo_once_key_and_turn_clear(db, make_game):
    """once_key 不可叠加（同键再授予不覆盖）；己方回合开始清除（"本回合"）。"""
    _echo_setup(db)
    db.cards[10010161] = F.card(10010161, token=True, steps=[
        F.Step(op="spell_echo", sequence=[ECHO2], once_key="nirvana")])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    pa.shikigami[1].level = 1
    play(g, 0, ECHO_GRANT)
    play(g, 0, 10010161)                  # 同 once_key：不覆盖已登记序列
    s = pa.shikigami[0]
    assert s.ext["spell_echo"]["sequence"] == [ECHO1, ECHO2]
    pass_turns(g, 2)                      # → A 的下一回合开始：回响清除
    assert "spell_echo" not in s.ext
    pa.orb = 9
    play(g, 0, TRIG_SPELL)                # 回响已清除：不再触发
    assert pb.health == 30


def test_spell_echo_void_auto_payload(db, make_game):
    """回响的自动使用照常 emit on_card_played：play_from=void、triggered=auto。"""
    _echo_setup(db)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    g.state.players[1].shield = 0
    pa.shikigami[1].level = 1
    seen = []
    orig = g.emit

    def spy(name, **kw):
        if name == "on_card_played":
            seen.append(kw)
        return orig(name, **kw)
    g.emit = spy
    play(g, 0, ECHO_GRANT)
    play(g, 0, TRIG_SPELL)
    auto = [p for p in seen if p.get("triggered") == "auto"]
    assert len(auto) == 1
    assert auto[0]["play_from"] == "void"


def test_spell_echo_random_choose_target(db, make_game):
    """有目标的回响牌：自动使用在合法目标中随机选择（池中仅 1 个时确定）。"""
    ECHOT = 10010162
    db.cards[ECHOT] = F.card(ECHOT, token=True, steps=[F.dmg(2)],
                             target=T(kind="choose", pool="enemy_shikigami"))
    db.cards[ECHO_GRANT] = F.card(ECHO_GRANT, token=True, steps=[
        F.Step(op="spell_echo", sequence=[ECHOT])])
    db.cards[TRIG_SPELL] = F.card(TRIG_SPELL, shikigami=100102, token=True, steps=[])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pa.shikigami[1].level = 1
    play(g, 0, ECHO_GRANT)
    play(g, 0, TRIG_SPELL)
    assert pb.shikigami[0].health == 2    # 合法池中仅 B0（4 - 2）


# ==========================================================================
# 致命响应（舍生 victim_lethal）/ 带目标响应（沧海之盾 victim_in_combat + bind=chosen）
# ==========================================================================

SHE = 10010261   # 舍生：致命响应，消灭所属式神位 + 牌手免疫所有伤害
DUN2 = 10010262  # 沧海之盾：战斗区式神被攻击响应，+2 甲 + 延迟恢复


def _she(db, cid=SHE):
    db.cards[cid] = F.card(
        cid, shikigami=BING, cost=1, level=2, keywords=["fast", "trigger"], token=True,
        when="on_damage_start",
        block_kw={"condition": {"victim_side": "friendly", "victim_kind": "player",
                                "victim_lethal": True}},
        steps=[F.Step(op="destroy",
                      target=T(kind="all", pool="friendly_shikigami", shikigami=BING)),
               F.Step(op="grant_immunity", kind="all", scope="turn",
                      target=T(kind="all", pool="self_player"))])
    return cid


def test_lethal_response_player_immunity(db, make_game):
    """致命响应（舍生）：你（牌手）将受到致命伤害（面板伤害 ≥ 当前生命）时自动使用——
    消灭所属式神位，本回合牌手免疫所有伤害；非致命伤害不响应。"""
    _she(db)
    g = make_game()
    pa, pb = g.state.players
    pb.shield = 0
    pa.shikigami[BING_IDX].level = 2
    pb.shikigami[0].level = 1
    pa.health = 3                     # 3/4 攻击者 → 3 伤 = 致命
    give(g, 0, SHE)
    pass_turns(g, 1)
    g.apply({"op": "assault", "index": 0})
    assert pa.shikigami[BING_IDX].defeated      # 消灭青坊主位
    assert pa.health == 3                       # 免疫了本次伤害
    assert any("免疫了本次伤害" in l for l in g.state.log)
    # 非致命：不响应
    g2 = make_game()
    pa2, pb2 = g2.state.players
    pb2.shield = 0
    pa2.shikigami[BING_IDX].level = 2
    pb2.shikigami[0].level = 1
    give(g2, 0, SHE)
    pass_turns(g2, 1)
    g2.apply({"op": "assault", "index": 0})     # 30 血吃 3 伤，非致命
    assert pa2.health == 27
    assert not pa2.shikigami[BING_IDX].defeated
    assert any(c.id == SHE for c in pa2.hand)   # 响应牌留在手牌


def _dun2(db, cid=DUN2):
    db.cards[cid] = F.card(
        cid, shikigami=BING, cost=1, level=1, keywords=["trigger"], token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        when="on_before_assault",
        block_kw={"condition": {"victim_side": "friendly", "victim_kind": "shikigami",
                                "victim_in_combat": True}},
        steps=[F.Step(op="gain_shield", amount=2),
               F.Step(op="delay_grant", bind="chosen", scope="turn", when="on_damage",
                      condition={"source_shikigami": "self", "kind_not": "effect"},
                      steps=[{"op": "heal", "amount": 2,
                              "target": {"kind": "all", "pool": "self_player"}}])])
    return cid


def test_combat_victim_response_with_delayed_heal(db, make_game):
    """战斗区式神被攻击响应（沧海之盾）：自动对被攻击者使用（choose 取事件 victim）
    +2 护甲；延迟能力绑定被选式神（bind=chosen）——其造成战斗伤害（含反击）时为
    牌手恢复 2。"""
    _dun2(db)
    g = make_game()
    pa, pb = g.state.players
    pb.shield = 0
    pa.shikigami[BING_IDX].level = 1
    pb.shikigami[0].level = 1
    pa.health = 25
    move(g, 0, BING_IDX)              # 兵俑位（1/6）进战斗区
    give(g, 0, DUN2)
    pass_turns(g, 1)
    g.apply({"op": "assault", "index": 0})   # 3/4 出击被战斗区兵俑拦下 → 响应
    s = pa.shikigami[BING_IDX]
    assert s.shield == 0              # 2 护甲被 3 伤消耗
    assert s.health == 5              # 6 - 1
    assert pa.health == 27            # 反击（kind=counter 战斗伤害）触发延迟恢复 2
