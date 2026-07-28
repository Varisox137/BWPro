"""大天狗（100104）数据测试：真实 db YAML 端到端（阶段 B 第一式神）。

覆盖：基础能力倒计时全流程（用法术→记录→归零→凭空免费复用→气绝丢失）、
觉醒替换（initial 1 / countdown_delta -1 / +2/+2）、8 张卡各核心路径。
队伍固定 [大天狗, 白狼, 兵俑, 妖刀姬]，大天狗 0 号位开局自动 1 级。
"""
from collections import Counter

import pytest

from core.model import Ref
from tests import factories as F
from tests.factories import give, move, pass_turns, play

DT = 100104      # 大天狗（双方 0 号位）
IDX = 0
KAZAMI = 10010401     # 风神一扇
SEIGI = 10010402      # 吾即正义
SHIELD = 10010403     # 暴风之盾
KUROBA = 10010404     # 黑羽之刃
LORD = 10010405       # 暴风之主
FUURAN = 10010406     # 天狗风乱
HA = 10010407         # 羽刃暴风
AWAKEN = 10010408     # 觉醒·大天狗

TEAM = [100104, 100101, 100102, 100123]


@pytest.fixture
def make_game(real_game):
    def _make(seed: int = 1, **kw):
        return real_game(TEAM, seed=seed, **kw)

    return _make


def _game(make_game, dt_level: int = 1):
    """对局 + 常用状态：A 9 鬼火、B 无补偿护甲、B 全员 1 级在场、A 大天狗指定等级。"""
    g = make_game()
    pa, pb = F.battle_setup(g, {IDX: dt_level})
    return g, pa, pb


# ---------- 基础能力：倒计时全流程 ----------

def test_base_ability_full_cycle(make_game):
    """用法术→记录+一次型[倒计时2]→归零凭空免费复用同名牌（不耗火、非从手牌）
    →自动使用再次触发记录（循环）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, KAZAMI)                        # 投射：B 战斗区空 → 牌手 2 伤
    assert pb.health == 28
    assert s.countdown == 2
    assert s.countdown_once is True
    assert s.countdown_source == DT
    assert s.ext["recorded_card"] == KAZAMI
    orb_after_play = pa.orb
    pass_turns(g, 2)                          # A 第 2 回合开始：2→1
    assert s.countdown == 1
    assert pb.health == 28
    pass_turns(g, 2)                          # A 第 3 回合开始：1→0，凭空自动使用
    assert pb.health == 26                    # 自动使用的 2 伤
    assert pa.orb >= orb_after_play - 9       # 自动使用不耗鬼火（回合开始鬼火已重置，粗查）
    assert pa.ext["countdown_history"] == [DT]
    assert s.countdown == 2                   # 自动使用再次触发基础能力：重新记录
    assert s.ext["recorded_card"] == KAZAMI


def test_record_lost_on_defeat(make_game):
    """气绝丢失：倒计时能力与 recorded_card 随气绝清除；复活后不再具有，
    再次使用法术才重新记录。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, KAZAMI)
    assert s.ext["recorded_card"] == KAZAMI
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated
    assert s.countdown is None
    assert "recorded_card" not in s.ext
    s.revive_countdown = 1
    pass_turns(g, 2)                          # A 回合开始：复活（基础能力无静态倒计时块）
    assert not s.defeated
    assert s.countdown is None
    pass_turns(g, 2)                          # 再过一整轮：无复用发生（记录已丢失）
    assert pb.health == 28
    play(g, 0, KAZAMI)                        # 重新使用法术 → 重新记录
    assert s.countdown == 2
    assert s.ext["recorded_card"] == KAZAMI


# ---------- 01 风神一扇 ----------

def test_kazami_retreats_damaged_shikigami(make_game):
    """投射命中战斗区式神：受伤者移回准备区（last_damage_victims 引用上一步受伤者）。"""
    g, pa, pb = _game(make_game)
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    assert pb.combat_index == 1
    play(g, 0, KAZAMI)
    wolf = pb.shikigami[1]
    assert wolf.health == 2                   # 2 伤
    assert pb.combat_index is None            # 被移回准备区
    assert wolf.in_play                       # 非气绝/离场


# ---------- 02 吾即正义 ----------

def test_seigi_generate_pool(make_game):
    """随机获得：大天狗等级 1 时池 = 等级≤1 的其他法术（风神一扇/暴风之盾），不含自身。"""
    g, pa, pb = _game(make_game)
    before = Counter(c.id for c in pa.hand)
    play(g, 0, SEIGI)
    new = Counter(c.id for c in pa.hand) - before
    assert sum(new.values()) == 1
    cid = next(iter(new))
    assert cid in {KAZAMI, SHIELD}            # 等级≤1 的法术，且排除吾即正义/形态牌


def test_seigi_transform_destroys_all(make_game):
    """本局使用 10 张法术后变为：消灭所有敌方式神（计数含吾即正义之外的法术）。"""
    g, pa, pb = _game(make_game)
    for _ in range(10):
        play(g, 0, KAZAMI)
        pa.orb = 9
    store = pa.card_mods[SEIGI]
    assert store["spell_count"] == 10
    assert store["transformed"] == 1
    assert "fast" not in g._card_keywords(pa, g.db.cards[SEIGI])  # 变为后失去[瞬发]
    play(g, 0, SEIGI)                         # 第 11 张法术：打出装配读取已置位的 transformed
    assert all(s.defeated for s in pb.shikigami)
    assert store["spell_count"] == 11         # 吾即正义自身也计数


def test_seigi_before_transform_generates(make_game):
    """9 张法术时未变为：仍是随机获得效果。"""
    g, pa, pb = _game(make_game)
    for _ in range(9):
        play(g, 0, KAZAMI)
        pa.orb = 9
    assert pa.card_mods[SEIGI]["spell_count"] == 9
    assert "transformed" not in pa.card_mods[SEIGI]
    before = Counter(c.id for c in pa.hand)
    play(g, 0, SEIGI)
    assert all(not s.defeated for s in pb.shikigami)
    assert sum((Counter(c.id for c in pa.hand) - before).values()) == 1


# ---------- 03 暴风之盾 ----------

def test_shield_active_and_delayed(make_game):
    """主动使用：目标 +2 护甲；下个己方回合开始再 +2（回合开始先清护甲，延迟能力后结算）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, SHIELD, target=Ref(player=0, shikigami=IDX))
    assert s.shield == 2
    assert len(s.delayed) == 1                # 延迟能力已登记（选择目标随条目存储）
    pass_turns(g, 2)                          # A 下回合开始：清护甲 → 延迟 +2
    assert s.shield == 2
    assert s.delayed == []                    # 一次性，已消耗


def test_shield_response_on_assault(make_game):
    """响应：己方战斗区式神被攻击时自动对其使用（付 1 火；+2 护甲先于战斗伤害）。"""
    g, pa, pb = _game(make_game)
    give(g, 0, SHIELD)
    move(g, 0, IDX)                           # A 大天狗入战斗区
    pass_turns(g, 1)                          # B 回合
    pa.orb = 9
    g.apply({"op": "assault", "index": 0})    # B 大天狗（3 攻）出击
    s = pa.shikigami[IDX]
    assert pa.orb == 8                        # 响应支付 1 鬼火
    assert any(c.id == SHIELD for c in pa.graveyard)
    assert s.health == 3                      # 3 伤 - 2 护甲 = 1 点扣减
    assert s.shield == 0                      # 护甲被战斗伤害消耗
    pass_turns(g, 1)                          # A 回合开始：延迟 +2
    assert s.shield == 2


# ---------- 04 黑羽之刃 ----------

def test_kuroba_kill_draws(make_game):
    """投射 4 伤消灭战斗区敌方式神 → 抽 1；一次性窗口消耗。"""
    g, pa, pb = _game(make_game, dt_level=2)
    move(g, 1, 0)                             # B 大天狗（3/4）入战斗区
    hand_before = len(pa.hand)
    play(g, 0, KUROBA)
    assert pb.shikigami[0].defeated
    assert len(pa.hand) == hand_before + 1    # give+打出抵消，消灭抽 1
    assert pa.shikigami[IDX].delayed == []


def test_kuroba_no_kill_no_draw(make_game):
    """未消灭（投射落空战斗区 → 牌手）：不抽；scope=play 窗口随出牌结束清除，不留存。"""
    g, pa, pb = _game(make_game, dt_level=2)
    hand_before = len(pa.hand)
    play(g, 0, KUROBA)
    assert pb.health == 26
    assert len(pa.hand) == hand_before        # give+打出抵消，未抽
    assert pa.shikigami[IDX].delayed == []    # 未消灭的延迟能力不遗留到后续


# ---------- 05 暴风之主 ----------

def test_storm_lord_pings_affected(make_game):
    """形态能力：使用法术后，对该次效果伤害过的敌方式神各造成 1 伤（affected_refs）。"""
    g, pa, pb = _game(make_game, dt_level=2)
    play(g, 0, LORD)                          # 结附形态（形态牌本身不触发形态能力）
    s = pa.shikigami[IDX]
    assert s.form is not None and s.form.id == LORD
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    play(g, 0, KAZAMI)                        # 投射 2 伤命中白狼
    wolf = pb.shikigami[1]
    assert wolf.health == 1                   # 2（法术）+ 1（暴风之主）
    assert pb.shikigami[0].health == 4        # 未受影响者不受伤
    assert pb.health == 30                    # 牌手未被暴风之主伤害（仅式神）


def test_storm_lord_no_damage_no_ping(make_game):
    """法术未伤害敌方式神（暴风之盾）：affected_refs 为空，形态能力空结算。"""
    g, pa, pb = _game(make_game, dt_level=2)
    play(g, 0, LORD)
    play(g, 0, SHIELD, target=Ref(player=0, shikigami=IDX))
    assert all(s.health == s.max_health for s in pb.shikigami)
    assert pb.health == 30


# ---------- 06 天狗风乱 / 07 羽刃暴风 ----------

def test_fuuran_distributes_six(make_game):
    """天狗风乱：合计 6 点伤害随机分配给所有敌方角色（含牌手；生命≤0 退出分配）。"""
    g, pa, pb = _game(make_game, dt_level=2)
    total_before = pb.health + sum(s.health for s in pb.shikigami)
    play(g, 0, FUURAN)
    total_after = pb.health + sum(max(s.health, 0) for s in pb.shikigami)
    assert total_before - total_after == 6


def test_ha_arashi_three_to_all(make_game):
    """羽刃暴风：所有敌方角色各 3 伤（4 名式神 + 牌手）。"""
    g, pa, pb = _game(make_game, dt_level=3)
    play(g, 0, HA)
    assert pb.health == 27
    assert [s.health for s in pb.shikigami] == [1, 1, 3, 1]  # 4/4/6/4 - 3


def test_storm_lord_enemy_shikigami_only(make_game):
    """维护者答复(7)：受影响列表只计敌方式神（去重）——羽刃暴风伤及的敌方牌手无
    暴风之主追加；构造性验证出牌伤害帧内波及的己方式神不进列表。"""
    g, pa, pb = _game(make_game, dt_level=3)
    play(g, 0, LORD)
    play(g, 0, HA)                            # 羽刃暴风：敌方全体各 3
    assert pb.health == 27                    # 牌手只吃 3（不进列表，无追加 1）
    assert [s.health for s in pb.shikigami] == [0, 0, 2, 0]  # 4/4/6/4 - 3 - 1
    # 构造：己方式神被波及不进 affected_refs
    g._affected_stack.append({"controller": 0, "refs": []})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 2, None)
    g.deal_to_shikigami(Ref(player=1, shikigami=2), 2, None)
    rec = g._affected_stack.pop()
    assert rec["refs"] == [Ref(player=1, shikigami=2)]


# ---------- 08 觉醒·大天狗 ----------

def test_awaken_replace_and_initial_one(make_game):
    """觉醒（维护者答复(10)+法术觉醒流程）：替换在法术效果之前——继承原能力记录的
    动态倒计时并变为倒计时 1，[倒计时]-1 随之归零 → 自动使用记录的法术；
    记录不随替换丢失（气绝才清）；+2/+2 随"觉醒后"延时时机授予。"""
    g, pa, pb = _game(make_game, dt_level=3)
    s = pa.shikigami[IDX]
    play(g, 0, KAZAMI)
    assert s.countdown == 2                   # 基础能力的一次型倒计时
    assert pb.health == 28
    play(g, 0, AWAKEN)
    assert s.awakened == AWAKEN
    assert g.history.index("on_before_awaken") < g.history.index("on_awakened")
    assert s.perm_power == 2 and s.perm_health == 2
    assert s.max_health == 6 and s.health == 6
    assert pb.health == 26                    # 继承的倒计时 1 → -1 归零：自动复用风神一扇
    assert s.ext["recorded_card"] == KAZAMI   # 觉醒继承原能力记录的法术
    assert s.countdown == 1                   # 自动使用再次触发觉醒能力[倒计时1]
    assert s.countdown_source == DT           # set_countdown 来源按 A2 决策 = 式神 id
    assert pa.ext["countdown_history"] == [DT]
    play(g, 0, KAZAMI)                        # 觉醒能力：[倒计时1]
    assert pb.health == 24
    assert s.countdown == 1
    pass_turns(g, 2)                          # A 下回合开始：1→0，自动使用
    assert pb.health == 22
    assert pa.ext["countdown_history"] == [DT, DT]
    assert s.countdown == 1                   # 自动使用再次触发觉醒能力
