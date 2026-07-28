"""真实数据层端到端测试：大天狗 / 妖琴师 / 以津真天 / 鸩 / 萤草基础能力。

合并自原 test_datianguo.py、test_yaqinshi.py、test_yijinzhentian.py、test_zhen.py
与 test_yingcao.py 的萤草基础能力测试（灵矢贯虹 3 个测试在 test_reinforce.py）。
真实 db YAML 端到端；各文件同构的 make_game fixture 与 _game 样板已上收为
文件级 helper：`_game(real_game, team, levels)`（team 作参数，内部 F.battle_setup）。
注意本文件的 gdb fixture 覆盖（注册萤草测试形态牌 + 凑卡组空白卡）对全文件生效，
原为萤草测试引入——真实库每次加载为全新对象，不影响其他式神测试断言。

主力式神 0 号位开局自动 1 级；静态倒计时开局注册、对局开始批次已 -1。
手动 level=1 不注册倒计时（仅升级指令/开局 0 号位/复活注册）——需要友方其他
倒计时能力的用例显式调用 g._register_ability_countdown。
"""
from collections import Counter

import pytest

from core.engine import IllegalAction
from core.model import Ref
from db.loader import CardDatabase
from db.schema import CardDef, EffectBlock, Step, TargetSpec
from tests import factories as F
from tests.factories import give, move, pass_turns, play

IDX = 0


def _game(real_game, team, levels=None):
    """对局 + 常用状态：A 9 鬼火、B 无补偿护甲、B 全员 1 级在场、A 主力式神指定等级
    （默认 {0: 1}；手动升级不注册倒计时，B 侧手动 1 级无倒计时干扰）。"""
    g = real_game(team)
    pa, pb = F.battle_setup(g, levels)
    return g, pa, pb


# ---------- 萤草测试库注册（gdb 覆盖；供萤草基础能力测试） ----------

YC = 100127       # 萤草（双方 0 号位）
YC_TEAM = [100127, 100101, 100102, 100123]
YC_FORM_A, YC_FORM_B = 10012701, 10012702  # 测试库注册的萤草形态牌


def _yc_form(cid: int, name: str, steps=()) -> CardDef:
    return CardDef(id=cid, version=20260728, name=name, shikigami=YC,
                   card_type="form", rarity="R", level=1, cost=1,
                   form_power=2, form_health=3,
                   effects=EffectBlock(steps=list(steps)), text="")


@pytest.fixture
def gdb():
    """真实 db + 测试库临时注册：萤草形态牌 A（空白进场）/B（进场 +2 护甲）
    与凑卡组的空白法术 03/04（萤草 8 卡未加入，mk_game 卡组构造需要 01-04）；
    姑获鸟（卡牌未设计，10010601-04 全空白）与青行灯（仅明灯 01 为真卡，
    10011202-04 空白）同样补足 01-04。
    本覆盖原属 test_yingcao.py，合并后萤草基础能力测试（本文件）与灵矢贯虹测试
    （test_reinforce.py）各持一份。"""
    db = CardDatabase.load()
    db.cards[YC_FORM_A] = _yc_form(YC_FORM_A, "测试形态·花")
    db.cards[YC_FORM_B] = _yc_form(YC_FORM_B, "测试形态·叶", steps=[
        Step(op="gain_shield", amount=2, target=TargetSpec(kind="self"))])
    for n in (3, 4):
        cid = YC * 100 + n
        db.cards[cid] = CardDef(id=cid, version=20260728, name=f"萤草空白卡{n}",
                                shikigami=YC, card_type="spell", level=1, cost=1,
                                effects=EffectBlock(), text="")
    for sid, nums in ((100106, (1, 2, 3, 4)), (100112, (2, 3, 4))):
        for n in nums:
            cid = sid * 100 + n
            db.cards[cid] = CardDef(id=cid, version=20260729,
                                    name=f"{db.shikigami[sid].name}空白卡{n}",
                                    shikigami=sid, card_type="spell", level=1, cost=1,
                                    effects=EffectBlock(), text="")
    return db


# ==========================================================================
# 大天狗（100104）（原 test_datianguo.py）
#
# 覆盖：基础能力倒计时全流程（用法术→记录→归零→凭空免费复用→气绝丢失）、
# 觉醒替换（initial 1 / countdown_delta -1 / +2/+2）、8 张卡各核心路径。
# 队伍固定 [大天狗, 白狼, 兵俑, 妖刀姬]，大天狗 0 号位开局自动 1 级。
# ==========================================================================

DT = 100104      # 大天狗（双方 0 号位）
KAZAMI = 10010401     # 风神一扇
SEIGI = 10010402      # 吾即正义
SHIELD = 10010403     # 暴风之盾
KUROBA = 10010404     # 黑羽之刃
LORD = 10010405       # 暴风之主
FUURAN = 10010406     # 天狗风乱
HA = 10010407         # 羽刃暴风
DT_AWAKEN = 10010408  # 觉醒·大天狗

DT_TEAM = [100104, 100101, 100102, 100123]


# ---------- 基础能力：倒计时全流程 ----------

def test_base_ability_full_cycle(real_game):
    """用法术→记录+一次型[倒计时2]→归零凭空免费复用同名牌（不耗火、非从手牌）
    →自动使用再次触发记录（循环）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
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


def test_record_lost_on_defeat(real_game):
    """气绝丢失：倒计时能力与 recorded_card 随气绝清除；复活后不再具有，
    再次使用法术才重新记录。"""
    g, pa, pb = _game(real_game, DT_TEAM)
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

def test_kazami_retreats_damaged_shikigami(real_game):
    """投射命中战斗区式神：受伤者移回准备区（last_damage_victims 引用上一步受伤者）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    assert pb.combat_index == 1
    play(g, 0, KAZAMI)
    wolf = pb.shikigami[1]
    assert wolf.health == 2                   # 2 伤
    assert pb.combat_index is None            # 被移回准备区
    assert wolf.in_play                       # 非气绝/离场


# ---------- 02 吾即正义 ----------

def test_seigi_generate_pool(real_game):
    """随机获得：大天狗等级 1 时池 = 等级≤1 的其他法术（风神一扇/暴风之盾），不含自身。"""
    g, pa, pb = _game(real_game, DT_TEAM)
    before = Counter(c.id for c in pa.hand)
    play(g, 0, SEIGI)
    new = Counter(c.id for c in pa.hand) - before
    assert sum(new.values()) == 1
    cid = next(iter(new))
    assert cid in {KAZAMI, SHIELD}            # 等级≤1 的法术，且排除吾即正义/形态牌


def test_seigi_transform_destroys_all(real_game):
    """本局使用 10 张法术后变为：消灭所有敌方式神（计数含吾即正义之外的法术）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
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


def test_seigi_before_transform_generates(real_game):
    """9 张法术时未变为：仍是随机获得效果。"""
    g, pa, pb = _game(real_game, DT_TEAM)
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

def test_shield_active_and_delayed(real_game):
    """主动使用：目标 +2 护甲；下个己方回合开始再 +2（回合开始先清护甲，延迟能力后结算）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
    s = pa.shikigami[IDX]
    play(g, 0, SHIELD, target=Ref(player=0, shikigami=IDX))
    assert s.shield == 2
    assert len(s.delayed) == 1                # 延迟能力已登记（选择目标随条目存储）
    pass_turns(g, 2)                          # A 下回合开始：清护甲 → 延迟 +2
    assert s.shield == 2
    assert s.delayed == []                    # 一次性，已消耗


def test_shield_response_on_assault(real_game):
    """响应：己方战斗区式神被攻击时自动对其使用（付 1 火；+2 护甲先于战斗伤害）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
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

def test_kuroba_kill_draws(real_game):
    """投射 4 伤消灭战斗区敌方式神 → 抽 1；一次性窗口消耗。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    move(g, 1, 0)                             # B 大天狗（3/4）入战斗区
    hand_before = len(pa.hand)
    play(g, 0, KUROBA)
    assert pb.shikigami[0].defeated
    assert len(pa.hand) == hand_before + 1    # give+打出抵消，消灭抽 1
    assert pa.shikigami[IDX].delayed == []


def test_kuroba_no_kill_no_draw(real_game):
    """未消灭（投射落空战斗区 → 牌手）：不抽；scope=play 窗口随出牌结束清除，不留存。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    hand_before = len(pa.hand)
    play(g, 0, KUROBA)
    assert pb.health == 26
    assert len(pa.hand) == hand_before        # give+打出抵消，未抽
    assert pa.shikigami[IDX].delayed == []    # 未消灭的延迟能力不遗留到后续


# ---------- 05 暴风之主 ----------

def test_storm_lord_pings_affected(real_game):
    """形态能力：使用法术后，对该次效果伤害过的敌方式神各造成 1 伤（affected_refs）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    play(g, 0, LORD)                          # 结附形态（形态牌本身不触发形态能力）
    s = pa.shikigami[IDX]
    assert s.form is not None and s.form.id == LORD
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    play(g, 0, KAZAMI)                        # 投射 2 伤命中白狼
    wolf = pb.shikigami[1]
    assert wolf.health == 1                   # 2（法术）+ 1（暴风之主）
    assert pb.shikigami[0].health == 4        # 未受影响者不受伤
    assert pb.health == 30                    # 牌手未被暴风之主伤害（仅式神）


def test_storm_lord_no_damage_no_ping(real_game):
    """法术未伤害敌方式神（暴风之盾）：affected_refs 为空，形态能力空结算。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    play(g, 0, LORD)
    play(g, 0, SHIELD, target=Ref(player=0, shikigami=IDX))
    assert all(s.health == s.max_health for s in pb.shikigami)
    assert pb.health == 30


# ---------- 06 天狗风乱 / 07 羽刃暴风 ----------

def test_fuuran_distributes_six(real_game):
    """天狗风乱：合计 6 点伤害随机分配给所有敌方角色（含牌手；生命≤0 退出分配）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    total_before = pb.health + sum(s.health for s in pb.shikigami)
    play(g, 0, FUURAN)
    total_after = pb.health + sum(max(s.health, 0) for s in pb.shikigami)
    assert total_before - total_after == 6


def test_ha_arashi_three_to_all(real_game):
    """羽刃暴风：所有敌方角色各 3 伤（4 名式神 + 牌手）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    play(g, 0, HA)
    assert pb.health == 27
    assert [s.health for s in pb.shikigami] == [1, 1, 3, 1]  # 4/4/6/4 - 3


def test_storm_lord_enemy_shikigami_only(real_game):
    """维护者答复(7)：受影响列表只计敌方式神（去重）——羽刃暴风伤及的敌方牌手无
    暴风之主追加；构造性验证出牌伤害帧内波及的己方式神不进列表。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
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

def test_awaken_replace_and_initial_one(real_game):
    """觉醒（维护者答复(10)+法术觉醒流程）：替换在法术效果之前——继承原能力记录的
    动态倒计时并变为倒计时 1，[倒计时]-1 随之归零 → 自动使用记录的法术；
    记录不随替换丢失（气绝才清）；+2/+2 随"觉醒后"延时时机授予。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    s = pa.shikigami[IDX]
    play(g, 0, KAZAMI)
    assert s.countdown == 2                   # 基础能力的一次型倒计时
    assert pb.health == 28
    play(g, 0, DT_AWAKEN)
    assert s.awakened == DT_AWAKEN
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


# ==========================================================================
# 妖琴师（100124）（原 test_yaqinshi.py）
#
# 覆盖：基础倒计时治疗、三觉醒替换+同次出牌 -3 立即归零（A2 路径）、大合奏按
# countdown_history 首次出现顺序重放（replay_countdown + _countdown_block_for）、
# 魔音扰心无效化（主动 delay_grant / 响应 response 覆盖块两路径）、惊弦/疯魔琴心/余音
# 的 countdown_delta（含无倒计时修正 -0）、镇魂歌抽牌+鬼火。
# 队伍固定 [妖琴师, 鸩, 以津真天, 妖刀姬]，妖琴师 0 号位开局自动 1 级（静态倒计时开局
# 注册 3、对局开始批次已 -1，故开局 countdown == 2）。
# ==========================================================================

YQS = 100124      # 妖琴师（双方 0 号位）
RUZHENG = 10012401   # 觉醒·入阵歌
JINGXIAN = 10012402  # 惊弦
DAHEZOU = 10012403   # 大合奏
SHENYUE = 10012404   # 觉醒·神乐歌
FENGMO = 10012405    # 疯魔琴心
MOYIN = 10012406     # 魔音扰心
ZHENHUN = 10012407   # 觉醒·镇魂歌
YUYIN = 10012408     # 余音

YQS_TEAM = [100124, 100128, 100126, 100123]


def _register_allied_countdowns(g):
    """让 A 鸩（1 号位）/以津真天（2 号位）在场并注册其静态倒计时能力。"""
    pa = g.state.players[0]
    for i in (1, 2):
        pa.shikigami[i].level = 1
        g._register_ability_countdown(0, i)


# ---------- 基础能力：倒计时治疗 ----------

def test_base_countdown_heals(real_game):
    """静态倒计时（initial 3 → 开局批次 -1 = 2）；归零：己方所有角色恢复 3 生命、
    循环重置、history 记式神 id。"""
    g, pa, pb = _game(real_game, YQS_TEAM)
    s = pa.shikigami[IDX]
    assert s.countdown == 2
    assert s.countdown_source == YQS
    pa.health = 20
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, None)   # 妖琴师 4→2
    pass_turns(g, 4)                          # A 第 3 回合开始：1→0 归零
    assert pa.health == 23                    # 己方牌手恢复 3
    assert s.health == 4                      # 妖琴师 2+3（上限 4）
    assert s.countdown == 3                   # 循环型重置
    assert pa.ext["countdown_history"] == [YQS]


# ---------- 法术觉醒：替换 + 同次 -3 立即归零（三张不同卡牌用例） ----------

def test_awaken_spell_immediate_countdown_zero(real_game):
    """法术觉醒牌共用流程（觉醒·入阵歌/神乐歌/镇魂歌）：永久身材修正 + 觉醒替换注册
    倒计时 3（来源=觉醒牌 id）→ 同次出牌触发 -3 至 0 立即归零执行归零效果并循环重置。"""
    # 入阵歌：+0/+1 永久；归零 5 伤随机分配给所有敌方角色
    g, pa, pb = _game(real_game, YQS_TEAM)
    s = pa.shikigami[IDX]
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, RUZHENG)
    assert s.awakened == RUZHENG
    assert s.perm_health == 1
    assert s.countdown == 3 and s.countdown_source == RUZHENG   # 归零后循环重置
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 5
    assert pa.ext["countdown_history"] == [RUZHENG]
    # 神乐歌：+1/+0 永久；归零己方其他在场式神倒计时 -1 并获得 1 力量与 1 生命（临时）
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 2})
    _register_allied_countdowns(g)            # 鸩/以津真天倒计时均为 2
    s = pa.shikigami[IDX]
    play(g, 0, SHENYUE)
    assert s.awakened == SHENYUE and s.perm_power == 1
    zhen, yjzt = pa.shikigami[1], pa.shikigami[2]
    assert zhen.countdown == 1 and yjzt.countdown == 1          # 倒计时 -1
    assert zhen.temp_power == 1 and zhen.temp_health == 1
    assert zhen.health == 6                   # 5 + 1（临时上限同步增加）
    assert yjzt.temp_power == 1 and yjzt.health == 6
    assert s.countdown == 3 and s.countdown_source == SHENYUE
    assert pa.ext["countdown_history"] == [SHENYUE]
    # 镇魂歌：+1/+1 永久；归零抽一张牌、获得 1 点鬼火
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    s = pa.shikigami[IDX]
    hand_before = len(pa.hand)
    play(g, 0, ZHENHUN)                       # 1 火；归零 +1 火
    assert s.awakened == ZHENHUN
    assert s.perm_power == 1 and s.perm_health == 1
    assert pa.orb == 9                        # 9 - 1 + 1
    assert len(pa.hand) == hand_before + 1    # give+打出抵消，归零抽 1
    assert s.countdown == 3 and s.countdown_source == ZHENHUN
    assert pa.ext["countdown_history"] == [ZHENHUN]


# ---------- 03 大合奏：按 history 首次出现顺序重放 ----------

def test_dahezou_replays_in_history_order(real_game):
    """大合奏：基础（先归零）→ 入阵歌 → 镇魂歌的生效顺序依次重放，每种至多一次。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    pa.health = 20
    pass_turns(g, 4)                          # 基础归零：pa 20→23，history [100124]
    assert pa.ext["countdown_history"] == [YQS]
    pa.orb = 9                                # 回合开始已重置鬼火：重设便于核算
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, RUZHENG)                       # 立即归零：敌方合计 -5
    play(g, 0, ZHENHUN)                       # 立即归零：抽 1 + 1 火（orb 9-2+1=8）
    assert pa.ext["countdown_history"] == [YQS, RUZHENG, ZHENHUN]
    log_before = len(g.state.log)
    play(g, 0, DAHEZOU)                       # 瞬发免费
    # 依次重放：基础治疗（23→26）、入阵歌（敌方再 -5）、镇魂歌（抽 1、+1 火）
    assert pa.health == 26
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 10
    assert pa.orb == 9                        # 8 + 1（重放镇魂歌）
    replay_logs = [m for m in g.state.log[log_before:] if "重放" in m]
    ids = [next(sid for sid in (YQS, RUZHENG, ZHENHUN) if f"来源 {sid}）" in m)
           for m in replay_logs]
    assert ids == [YQS, RUZHENG, ZHENHUN]     # 按 history 首次出现顺序，每种至多一次


def test_dahezou_skips_form_sources(real_game, gdb):
    """维护者答复(8)：大合奏只计入基础/觉醒能力，形态来源跳过——妖琴师当前无形态牌，
    构造性改写一张形态卡的归属并注入 history 验证。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 1})
    gdb.cards[10012608].shikigami = YQS       # 构造：归属妖琴师的形态来源（流浪之羽）
    pa.ext["countdown_history"] = [10012608, YQS]
    pa.health = 20
    log_before = len(g.state.log)
    play(g, 0, DAHEZOU)
    assert pa.health == 23                    # 仅重放基础治疗（形态来源被跳过）
    replay_logs = [m for m in g.state.log[log_before:] if "重放" in m]
    assert len(replay_logs) == 1 and f"来源 {YQS}）" in replay_logs[0]


# ---------- 06 魔音扰心：无效化（主动 / 响应） ----------

def test_moyin_proactive_nullifies_next_enemy_card(real_game):
    """主动使用：登记一次性延迟能力——敌方本回合下一张牌的使用手牌前无效化
    （费用已付不退、牌离手进墓地、效果跳过）。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 2})
    s = pa.shikigami[IDX]
    play(g, 0, MOYIN)
    assert len(s.delayed) == 1
    cd_before = s.countdown
    pass_turns(g, 1)                          # B 回合
    pb.orb = 9
    play(g, 1, JINGXIAN, target=Ref(player=0, shikigami=IDX))  # B 惊弦点妖琴师
    assert s.countdown == cd_before           # 被无效化：倒计时未 -2
    assert any(c.id == JINGXIAN for c in pb.graveyard)         # 牌照常进墓地
    assert pb.orb == 8                        # 费用已付不退
    assert not s.delayed                      # 一次性：收集即消耗


def test_moyin_response_nullifies_current_card(real_game):
    """响应：敌方牌手将使用牌时自动使用（response 覆盖块）——直接无效化该次使用。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 2})
    s = pa.shikigami[IDX]
    give(g, 0, MOYIN)
    cd_before = s.countdown
    pass_turns(g, 1)                          # B 回合
    pa.orb = 9
    pb.orb = 9
    play(g, 1, JINGXIAN, target=Ref(player=0, shikigami=IDX))
    assert s.countdown == cd_before           # 当前用牌被无效化
    assert any(c.id == JINGXIAN for c in pb.graveyard)
    assert any(c.id == MOYIN for c in pa.graveyard)            # 响应牌离手
    assert pa.orb == 8                        # 响应支付 1 鬼火（无瞬发）


# ---------- 02 惊弦 / 05 疯魔琴心 / 08 余音：倒计时增减 ----------

def test_jingxian_triggers_zero_and_noop_without_countdown(real_game):
    """惊弦：使一个式神倒计时 -2——点妖琴师自己立即归零结算；点无倒计时能力者
    修正 -0（空操作）。"""
    g, pa, pb = _game(real_game, YQS_TEAM)
    s = pa.shikigami[IDX]
    pa.health = 20
    play(g, 0, JINGXIAN, target=Ref(player=0, shikigami=IDX))   # 2-2=0：归零
    assert pa.health == 23                    # 归零治疗生效
    assert s.countdown == 3                   # 循环重置
    assert pa.ext["countdown_history"] == [YQS]
    play(g, 0, JINGXIAN, target=Ref(player=1, shikigami=3))     # B 妖刀姬无倒计时：-0
    assert pb.shikigami[3].countdown is None


def test_fengmo_enemy_plus2_self_minus2(real_game):
    """疯魔琴心：敌方式神 +2（无倒计时能力者 -0），妖琴师 -2（可立即归零）。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 2})
    pb.shikigami[1].level = 1
    g._register_ability_countdown(1, 1)       # B 鸩倒计时 2
    s = pa.shikigami[IDX]
    pa.health = 20
    play(g, 0, FENGMO, target=Ref(player=1, shikigami=1))
    assert pb.shikigami[1].countdown == 4     # 2 + 2
    assert pa.health == 23                    # 自身 2-2=0：归零治疗
    assert s.countdown == 3
    play(g, 0, FENGMO, target=Ref(player=1, shikigami=3))       # B 妖刀姬无倒计时：+2 修正 -0
    assert pb.shikigami[3].countdown is None


def test_yuyin_self_and_allied_minus(real_game):
    """余音：妖琴师 -3（立即归零），己方其他未气绝式神 -1。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    _register_allied_countdowns(g)            # 鸩/以津真天倒计时均为 2
    s = pa.shikigami[IDX]
    pa.health = 20
    play(g, 0, YUYIN)
    assert pa.health == 23                    # 自身 2-3：归零治疗
    assert s.countdown == 3
    assert pa.shikigami[1].countdown == 1
    assert pa.shikigami[2].countdown == 1
    assert pa.ext["countdown_history"] == [YQS]


# ==========================================================================
# 以津真天（100126）（原 test_yijinzhentian.py）
#
# 覆盖：基础/觉醒倒计时生成黄金羽（generate card_id 指定 token）、黄金羽瞬发打牌手与
# 觉醒后狙击敌方式神（PlayMethod requires_awaken 门控）、黄金羽记账（feather_used_game/
# turn 与 on_card_played 的 golden_feather payload）、风之舞增强计数、金风流羽视为黄金羽
# 与条件免费（cost_zero_if）、不可饶恕回合级战斗免疫（grant_immunity）、射怪鸟事气绝前
# 响应弃抽（discard→memo 计数 + draw {"memo": key}）、千羽风之舞战斗牌其它效果步、
# 流浪之羽形态触发随机伤害。
# 队伍固定 [以津真天, 白狼, 兵俑, 妖刀姬]，以津真天 0 号位开局自动 1 级（静态倒计时开局
# 注册 2、对局开始的回合开始批次已 -1，故开局 countdown == 1；B 以津真天同理，其倒计时
# 会往 B 手牌塞黄金羽，不影响本组断言）。
# ==========================================================================

YJZT = 100126     # 以津真天（双方 0 号位）
JYHS = 10012601   # 金羽焕生
FZW = 10012602    # 风之舞
JLFY = 10012603   # 金风流羽
BKRS = 10012604   # 不可饶恕
SGNS = 10012605   # 射怪鸟事
YJZT_AWAKEN = 10012606  # 觉醒·以津真天
QYFW = 10012607   # 千羽风之舞
LLZY = 10012608   # 流浪之羽
FEATHER = 10012651  # 黄金羽（token）

YJZT_TEAM = [100126, 100101, 100102, 100123]


def _play_method(g, player: int, defn_id: int, method: str, target: Ref) -> None:
    """发一张牌到手上并以指定使用方式打出（play_method + 选择目标）。"""
    card = give(g, player, defn_id)
    g.apply({"op": "play_card", "uid": card.uid, "play_method": method, "target": target})


# ---------- 基础能力：倒计时生成黄金羽 ----------

def test_base_countdown_generates_feather(real_game):
    """静态倒计时能力开局注册（2 → 对局开始批次 -1 = 1）；归零：黄金羽入手、
    循环重置、history 记式神 id。"""
    g, pa, pb = _game(real_game, YJZT_TEAM)
    s = pa.shikigami[IDX]
    assert s.countdown == 1
    assert s.countdown_source == YJZT
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert any(c.id == FEATHER for c in pa.hand)
    assert s.countdown == 2                   # 循环型重置
    assert pa.ext["countdown_history"] == [YJZT]


# ---------- 01 金羽焕生 ----------

def test_generate_two_by_card_id(real_game):
    """金羽焕生：将两张黄金羽置入手牌（指定 id 生成，token 不入随机池）。"""
    g, pa, pb = _game(real_game, YJZT_TEAM)
    play(g, 0, JYHS)
    assert sum(1 for c in pa.hand if c.id == FEATHER) == 2


# ---------- 51 黄金羽：瞬发打牌手 / 记账 ----------

def test_fast_free_and_tag_accounting(real_game):
    """黄金羽：瞬发（本回合首张瞬发免费，鬼火不变）对敌方牌手 2 伤；
    记账 feather_used_game/turn。"""
    g, pa, pb = _game(real_game, YJZT_TEAM)
    play(g, 0, FEATHER)
    assert pb.health == 28
    assert pa.orb == 9                        # 瞬发免费
    assert pa.ext["feather_used_game"] == 1
    assert pa.ext["feather_used_turn"] == 1


# ---------- 02 风之舞：黄金羽增强 ----------

def test_wind_dance_enhance(real_game):
    """每用过一张黄金羽 +1/+1（持久计数，打出装配快照）：用 2 张后 +2/+2。"""
    g, pa, pb = _game(real_game, YJZT_TEAM)
    play(g, 0, FEATHER)                       # 瞬发免费
    play(g, 0, FEATHER)                       # 第二张瞬发名额已用，1 火
    assert pa.card_mods[FZW]["enhance"] == 2
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    play(g, 0, FZW)                           # 以津真天 2+2=4 攻 → 兵俑 6→2
    assert pb.shikigami[2].health == 2
    s = pa.shikigami[IDX]
    assert s.shield == 1                      # +2 护甲吃反击 1
    assert s.health == 5


# ---------- 03 金风流羽：视为黄金羽 / 条件免费 ----------

def test_jinfeng_liuyu_cost_and_accounting(real_game):
    """未用过黄金羽：正常 1 火，且自身视为黄金羽记账；用过之后：不耗火。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    play(g, 0, JLFY)                          # 1 火（费用先于记账计算，自身不免自身）
    assert pa.orb == 8
    assert pa.ext["feather_used_turn"] == 1   # tags golden_feather：视为黄金羽
    play(g, 0, JLFY)                          # 本回合已用过黄金羽：0 火
    assert pa.orb == 8
    assert pa.ext["feather_used_turn"] == 2


# ---------- 04 不可饶恕：回合级战斗免疫 ----------

def test_turn_scoped_immunity_grant(real_game):
    """grant_immunity(scope=turn)：结附后本回合用过黄金羽则免疫战斗伤害（反击不扣血，
    回合号记账）；unique 去重——多次使用黄金羽不重复授予（维护者答复(3)）。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    play(g, 0, BKRS)                          # 形态 4/6
    play(g, 0, FEATHER)                       # 触发形态能力：本回合免疫战斗伤害
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    g.apply({"op": "assault", "index": IDX})  # 以津真天 4 攻 → 兵俑 6→2
    assert pb.shikigami[2].health == 2
    assert pa.shikigami[IDX].health == 6      # 反击 1 被免疫
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    play(g, 0, BKRS)
    play(g, 0, FEATHER)
    play(g, 0, FEATHER)                       # 第二次：unique 命中不再授予
    entries = [e for e in pa.shikigami[IDX].immunities
               if e.get("kind") == "combat_damage"]
    assert len(entries) == 1


# ---------- 05 射怪鸟事：气绝前响应弃抽 ----------

def test_before_defeat_response_discard_draw(real_game):
    """响应：以津真天将气绝时自动使用——弃掉所有她的专属牌并抽等量（瞬发免费）。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    give(g, 0, SGNS)
    give(g, 0, JYHS)                          # 两张她的专属牌陪弃
    give(g, 0, QYFW)
    before = len(pa.hand)
    pass_turns(g, 1)                          # B 回合
    pa.orb = 9
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    s = pa.shikigami[IDX]
    assert s.defeated                         # 响应不救命：弃抽后照常气绝
    assert pa.orb == 9                        # 瞬发免费
    assert len(pa.hand) == before - 1         # 响应牌离手；弃 d 张抽 d 张
    for cid in (SGNS, JYHS, QYFW):
        assert any(c.id == cid for c in pa.graveyard)


# ---------- 06 觉醒·以津真天：倒计时1 / 黄金羽狙击 ----------

def test_awaken_countdown_one(real_game):
    """觉醒：永久 +1/+1；觉醒倒计时（initial 1，来源=觉醒牌 id）归零黄金羽入手。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    s = pa.shikigami[IDX]
    play(g, 0, YJZT_AWAKEN)
    assert s.awakened == YJZT_AWAKEN
    assert s.perm_power == 1 and s.perm_health == 1
    assert s.countdown == 1 and s.countdown_source == YJZT_AWAKEN
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert any(c.id == FEATHER for c in pa.hand)
    assert s.countdown == 1                   # 循环重置为 1
    assert pa.ext["countdown_history"] == [YJZT_AWAKEN]


def test_method_requires_awaken_gating(real_game):
    """黄金羽以敌方角色为目标（答复(11)）：未觉醒门控 IllegalAction；觉醒后可狙击
    式神或牌手 2 伤。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 2})
    wolf = Ref(player=1, shikigami=1)
    with pytest.raises(IllegalAction):
        _play_method(g, 0, FEATHER, "snipe", wolf)   # 未觉醒：门控拒绝
    play(g, 0, YJZT_AWAKEN)
    _play_method(g, 0, FEATHER, "snipe", wolf)       # 觉醒后：瞬发免费狙击式神
    assert pb.shikigami[1].health == 2
    _play_method(g, 0, FEATHER, "snipe", Ref(player=1))  # 也可狙击敌方牌手
    assert pb.health == 28
    assert pa.orb == 7                        # 觉醒牌 1 火 + 第二张黄金羽 1 火（瞬发名额已用）


# ---------- 07 千羽风之舞：战斗牌其它效果步 ----------

def test_conditional_step_by_player_ext(real_game):
    """战斗牌其它效果步的 step 级条件（player_ext=feather_used_turn）：本回合未用过
    黄金羽仅 +3/+3 不生成金风流羽；用过则战斗流程执行其它效果步置入手牌。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 3})
    play(g, 0, QYFW)
    assert not any(c.id == JLFY for c in pa.hand)
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 3})
    play(g, 0, FEATHER)
    play(g, 0, QYFW)
    assert any(c.id == JLFY for c in pa.hand)


# ---------- 08 流浪之羽：形态触发随机伤害 ----------

def test_random_damage_on_tagged_play(real_game):
    """结附期间使用黄金羽：随机对两个敌方式神各造成 2 点伤害（合计 4）。"""
    g, pa, pb = _game(real_game, YJZT_TEAM, {IDX: 3})
    play(g, 0, LLZY)
    before = sum(s.health for s in pb.shikigami)
    play(g, 0, FEATHER)
    after = sum(s.health for s in pb.shikigami)
    assert before - after == 4


# ==========================================================================
# 鸩（100128）（原 test_zhen.py；验证 A3/A4 破甲管线）
#
# 覆盖：基础/觉醒倒计时给破甲、x（zhen_proc）计数与跨气绝保留、
# 鸩羽/致命诱惑的战斗条件授予（defender_has_fragile）、毒蚀伤害→破甲转化（主动/响应）、
# 碧羽散华获得破甲→伤害转化、毒之华半血破甲、寂寥心象每回合合计一次二选一、吸血实卡。
# 队伍固定 [鸩, 白狼, 兵俑, 妖刀姬]，鸩 0 号位开局自动 1 级（静态倒计时开局注册 2、
# 对局开始的回合开始批次已 -1，故开局 countdown == 1；B 鸩同理，其破甲给 A 牌手，
# 不影响本组断言）。
# ==========================================================================

ZHEN = 100128     # 鸩（双方 0 号位）
ZY = 10012801     # 鸩羽
ZYS = 10012802    # 鸩羽苏生
JLXX = 10012803   # 寂寥心象
DS = 10012804     # 毒蚀
ZHEN_AWAKEN = 10012805  # 觉醒·鸩
ZMYH = 10012806   # 致命诱惑
BYSH = 10012807   # 碧羽散华
DZH = 10012808    # 毒之华

ZHEN_TEAM = [100128, 100101, 100102, 100123]


# ---------- 基础能力：倒计时给破甲 / x 计数 ----------

def test_base_countdown_gives_fragile(real_game):
    """静态倒计时能力开局注册（2 → 对局开始批次 -1 = 1）；归零：敌方牌手 2 破甲、
    循环重置、zhen_proc +1、history 记式神 id。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM)
    s = pa.shikigami[IDX]
    assert s.countdown == 1
    assert s.countdown_source == ZHEN
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert pb.shield == -2                    # 敌方牌手获得 2 破甲
    assert s.countdown == 2                   # 循环型重置
    assert s.ext["zhen_proc"] == 1            # x：基础+觉醒生效合计
    assert pa.ext["countdown_history"] == [ZHEN]


def test_countdown_delta_immediate_zero(real_game):
    """鸩羽苏生：鸩倒计时 -2（1→0 立即归零结算）+ 抽 1。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM)
    s = pa.shikigami[IDX]
    hand_before = len(pa.hand)
    play(g, 0, ZYS)
    assert pb.shield == -2                    # 倒计时被减到归零：破甲生效
    assert s.countdown == 2                   # 归零后循环重置
    assert s.ext["zhen_proc"] == 1
    assert len(pa.hand) == hand_before + 1    # give+打出抵消，抽 1


def test_x_survives_defeat(real_game):
    """x 跨气绝保留：气绝清除倒计时能力，ext["zhen_proc"] 不清；复活重注册倒计时。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM)
    s = pa.shikigami[IDX]
    pass_turns(g, 2)                          # 基础归零一次：zhen_proc == 1
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated and s.countdown is None
    assert s.ext["zhen_proc"] == 1            # 气绝不清 ext
    s.revive_countdown = 1
    pass_turns(g, 2)                          # A 回合开始：复活重注册（2）→ 同批 -1
    assert not s.defeated
    assert s.countdown == 1
    assert s.ext["zhen_proc"] == 1


# ---------- 01 鸩羽：条件免疫 ----------

def test_battle_immunity_conditioned_on_victim_fragile(real_game):
    """战斗牌条件免疫（victim_has_fragile）：攻击有破甲的角色免疫反击；无破甲正常扣血。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM)
    pb.shikigami[2].shield = -1               # B 兵俑（1/6）持 1 破甲
    move(g, 1, 2)
    play(g, 0, ZY)                            # 鸩 2+2=4 攻 → 兵俑 4+1=5 伤
    assert pb.shikigami[2].health == 1
    assert pa.shikigami[IDX].health == 5      # 反击 1 被免疫
    g, pa, pb = _game(real_game, ZHEN_TEAM)
    move(g, 1, 2)                             # B 兵俑无破甲
    play(g, 0, ZY)
    assert pb.shikigami[2].health == 2        # 4 伤
    assert pa.shikigami[IDX].health == 4      # 反击 1 正常扣血


# ---------- 04 毒蚀：伤害→破甲转化 ----------

def test_dushi_active_converts_both_sides(real_game):
    """主动使用：本次战斗中双方造成的伤害转化为等量破甲；战斗结束后转化清除。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    play(g, 0, DS)                            # 鸩 2+4=6 攻
    wolf = pb.shikigami[1]
    zhen = pa.shikigami[IDX]
    assert wolf.health == 4 and wolf.shield == -6    # 6 伤 → 6 破甲
    assert zhen.health == 5 and zhen.shield == -3    # 反击 3 → 3 破甲
    g.deal_to_player(1, 2, None)              # 战斗结束后：伤害不再转化
    assert pb.health == 28


def test_dushi_response_on_attacked(real_game):
    """响应：当鸩被攻击时自动使用——插入的战斗同样全程转化。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    give(g, 0, DS)
    move(g, 0, IDX)                           # A 鸩驻战斗区
    pass_turns(g, 1)                          # B 回合
    pa.orb = 9
    g.apply({"op": "assault", "index": 0})    # B 鸩（2 攻）出击 → 毒蚀响应
    zhen_a, zhen_b = pa.shikigami[IDX], pb.shikigami[IDX]
    assert pa.orb == 8                        # 响应支付 1 鬼火
    assert any(c.id == DS for c in pa.graveyard)
    assert zhen_a.health == 5 and zhen_a.shield == -2   # B 鸩 2 攻 → 2 破甲
    assert zhen_b.health == 5 and zhen_b.shield == -6   # A 鸩反击 2+4=6 → 6 破甲


def test_dushi_with_biyu_net_effect(real_game):
    """维护者答复(5)净效果：碧羽散华形态的鸩使用毒蚀——敌方式神正常受伤（伤害事件
    生成点→破甲→碧羽嵌套转回伤害，嵌套不再触发毒蚀），鸩自身被反击获得破甲而不受伤。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 3})
    play(g, 0, BYSH)                          # 碧羽散华结附（鸩 5/7，标记敌方）
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    wolf = pb.shikigami[1]
    wolf.base_health = wolf.health = 20       # 撑住攻击便于观察净效果
    play(g, 0, DS)                            # 毒蚀：鸩 5+4=9 攻
    zhen = pa.shikigami[IDX]
    assert wolf.health == 11 and wolf.shield == 0   # 9 伤→9 破甲→碧羽转回 9 伤
    assert zhen.health == 7 and zhen.shield == -3   # 反击 3 → 3 破甲，不受伤


# ---------- 05 觉醒·鸩：x 累加 ----------

def test_awaken_x_scaling(real_game):
    """觉醒：效果 2 破甲 + 永久 +1 力量；觉醒倒计时（initial 2，来源=觉醒牌 id）给
    2+x 破甲（x=基础+觉醒生效合计，觉醒后继续累加）。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    s = pa.shikigami[IDX]
    pass_turns(g, 2)                          # 基础归零：pb -2，zhen_proc 1，重置 2
    assert pb.shield == -2
    play(g, 0, ZHEN_AWAKEN)                   # 效果：pb 再 -2
    assert pb.shield == -4
    assert s.awakened == ZHEN_AWAKEN
    assert s.perm_power == 1
    assert s.countdown == 2 and s.countdown_source == ZHEN_AWAKEN
    pass_turns(g, 4)                          # A 第 4 回合开始觉醒归零（期间 B 回合开始清过 pb 破甲）
    assert pb.shield == -3                    # 2 + x(1) = 3
    assert s.ext["zhen_proc"] == 2            # 觉醒生效继续累加
    assert pa.ext["countdown_history"] == [ZHEN, ZHEN_AWAKEN]


# ---------- 06 致命诱惑：条件吸血 ----------

def test_zhiming_lifesteal_vs_fragile(real_game):
    """攻击有破甲的角色：获得[吸血]（实卡路径：伤害后为牌手恢复等量生命）。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    pa.health = 20
    pb.shikigami[1].shield = -1               # B 白狼持 1 破甲
    move(g, 1, 1)
    play(g, 0, ZMYH)                          # 鸩 2+2=4 攻 → 白狼 4+1=5 伤气绝
    assert pb.shikigami[1].defeated
    assert pa.health == 25                    # 吸血：恢复 5（伤害值）


def test_zhiming_no_lifesteal_without_fragile(real_game):
    """被攻击者无破甲：不获得吸血。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    pa.health = 20
    move(g, 1, 2)                             # B 兵俑（1/6）无破甲
    play(g, 0, ZMYH)
    assert pb.shikigami[2].health == 2        # 4 伤
    assert pa.health == 20                    # 无吸血
    assert pa.shikigami[IDX].health == 5      # +2 护甲吸收反击 1


# ---------- 07 碧羽散华：获得破甲→伤害 ----------

def test_biyu_sanhua_converts_and_clears(real_game):
    """结附期间：敌方式神获得破甲转化为等量伤害；形态离场（替换）后标记清除。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 3})
    play(g, 0, BYSH)
    wolf = pb.shikigami[1]
    g._change_shield(Ref(player=1, shikigami=1), 3, "test", kind="fragile")
    assert wolf.health == 1 and wolf.shield == 0      # 3 破甲 → 3 伤害
    g._change_shield(Ref(player=1), 2, "test", kind="fragile")
    assert pb.shield == 0 and pb.health == 28          # 牌手同样转化（维护者答复(1)）
    play(g, 0, JLXX)                                   # 替换形态 → 旧形态离场清除标记
    g._change_shield(Ref(player=1, shikigami=1), 2, "test", kind="fragile")
    assert wolf.shield == -2 and wolf.health == 1      # 不再转化
    h, sh = pb.health, pb.shield
    g._change_shield(Ref(player=1), 2, "test", kind="fragile")
    assert pb.health == h and pb.shield == sh - 2      # 牌手也不再转化


# ---------- 08 毒之华：半血破甲 ----------

def test_duzhihua_half_health_fragile(real_game):
    """对敌方角色造成战斗伤害后：目标获得等同于其当前生命一半（向下取整）的破甲。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 3})
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    play(g, 0, DZH)                           # 鸩 2 攻 → 兵俑 6→4 → 破甲 4//2=2
    soldier = pb.shikigami[2]
    assert soldier.health == 4 and soldier.shield == -2
    assert pa.shikigami[IDX].health == 4      # 反击 1（+0/+0 无护甲）


# ---------- 03 寂寥心象：每回合合计一次 ----------

def test_jiliao_shikigami_branch_and_gate(real_game):
    """敌方式神获得破甲 → 鸩倒计时 -2（可立即归零）；同回合后续事件被门控（合计一次）。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    play(g, 0, JLXX)
    s = pa.shikigami[IDX]
    assert s.countdown == 1
    g._change_shield(Ref(player=1, shikigami=1), 3, "test", kind="fragile")
    wolf = pb.shikigami[1]
    assert wolf.shield == -3                  # 事件本身的 3 破甲
    assert pb.shield == -2                    # 倒计时 1-2 归零：牌手 2 破甲
    assert s.countdown == 2                   # 归零后循环重置
    assert s.ext["zhen_proc"] == 1
    # 门控：同回合敌方式神再获破甲（妖刀姬）与牌手归零破甲均不再触发
    g._change_shield(Ref(player=1, shikigami=2), 2, "test", kind="fragile")
    assert s.countdown == 2
    assert pb.shikigami[2].shield == -2


def test_jiliao_player_branch_and_next_turn(real_game):
    """敌方牌手获得破甲 → 敌方战斗区式神获得等量破甲；次回合门控清除可再触发。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    play(g, 0, JLXX)
    move(g, 1, 1)                             # B 白狼入战斗区
    s = pa.shikigami[IDX]
    g._change_shield(Ref(player=1), 2, "test", kind="fragile")
    assert pb.shikigami[1].shield == -2       # 等量（2）破甲
    assert s.countdown == 1                   # 牌手分支不动倒计时
    pass_turns(g, 1)                          # B 回合开始：双方门控清除（B 方破甲/护甲也清除）
    move(g, 1, 1)                             # B 回合开始白狼已被延时移回，重新入战斗区
    g._change_shield(Ref(player=1), 2, "test", kind="fragile")
    assert pb.shikigami[1].shield == -2       # 再次触发（被清除后重新 -2）


# ==========================================================================
# 萤草（100127）基础能力（原 test_yingcao.py 基础能力部分）
#
# 覆盖：萤草基础能力（使用与当前形态不同的形态牌时抽 1——当前无萤草形态牌，
# 测试库临时注册两张验证机制对任意形态牌生效，见文件头 gdb 覆盖）。
# 队伍固定 [萤草, 白狼, 兵俑, 妖刀姬]。
# ==========================================================================

def test_draw_on_different_form_attach(real_game):
    """使用与当前形态不同的形态牌 → 抽 1；同形态再结附不触发。"""
    g, pa, pb = _game(real_game, YC_TEAM, {IDX: 1, 1: 1})
    hand = len(pa.hand)
    play(g, 0, YC_FORM_A)                     # 无当前形态 → 不同 → 抽 1
    assert len(pa.hand) == hand + 1
    play(g, 0, YC_FORM_A)                     # 同形态（id 相同）→ 不抽
    assert len(pa.hand) == hand + 1
    play(g, 0, YC_FORM_B)                     # 不同形态 → 抽 1
    assert len(pa.hand) == hand + 2


# ==========================================================================
# 凤凰火（100105）
#
# 覆盖：基础能力投射（专属法术→投射 1）、引燃消灭追加（敌/己两向）、焚羽非战斗
# 伤害 +1、觉醒替换投射（己方式神任意专属法术触发、自身法术只触发一次）、
# 炎舞增强计数与贯通溢出、出云生成凤火。队伍 [凤凰火, 山童, 白狼, 妖刀姬]。
# ==========================================================================

FM, RX, YR = 10010501, 10010502, 10010503      # 凤鸣/瑞翔/引燃
FY, FH = 10010504, 10010505                    # 焚羽/凤火
FHH_AWAKEN, YW, CY = 10010506, 10010507, 10010508

FHH_TEAM = [100105, 100116, 100101, 100123]


def test_fhh_base_projectile(real_game):
    """基础能力：凤凰火使用专属法术（凤鸣）→ [投射]1（B 战斗区空 → 打脸）。"""
    g, pa, pb = _game(real_game, FHH_TEAM)
    play(g, 0, FM)                            # 凤鸣 2 + 投射 1
    assert pb.health == 27


def test_fhh_yinran_kill_enemy(real_game):
    """引燃消灭敌方式神：再对它的牌手造成 2（victim_player 语境目标）。"""
    g, pa, pb = _game(real_game, FHH_TEAM)
    pb.shikigami[0].health = 2
    play(g, 0, YR, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].defeated
    assert pb.health == 27                    # 消灭追加 2 + 投射 1


def test_fhh_yinran_kill_friendly(real_game):
    """引燃可对己方式神使用（维护者确认）：消灭己方式神 → 对己方牌手造成 2。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 1, 1: 1})
    pa.shikigami[1].health = 2
    play(g, 0, YR, target=Ref(player=0, shikigami=1))
    assert pa.shikigami[1].defeated
    assert pa.health == 28
    assert pb.health == 29                    # 投射 1


def test_fhh_fenyu_boosts_effect_damage(real_game):
    """焚羽：凤凰火造成的非战斗伤害 +1——凤鸣直击与基础投射均吃增幅。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 2})
    play(g, 0, FY)
    play(g, 0, FM)                            # (2+1) + 投射 (1+1)
    assert pb.health == 25


def test_fhh_awaken_any_shikigami_spell(real_game):
    """觉醒·凤凰火：己方式神使用任意专属法术均投射 1（觉醒牌本身已触发一次）；
    凤凰火自己的法术只触发一次（基础能力已被觉醒能力替换）。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 2, 1: 1})
    play(g, 0, FHH_AWAKEN)
    assert pa.shikigami[IDX].awakened == FHH_AWAKEN
    assert pb.health == 29                    # 觉醒牌自身的使用事件已触发觉醒能力
    play(g, 0, 10011603)                      # 山童怒吼（其他式神的专属法术）→ 投射 1
    assert pb.health == 28
    play(g, 0, FM)                            # 凤鸣 2 + 投射 1（只触发一次）
    assert pb.health == 25
    assert pa.shikigami[IDX].perm_power == 1  # 觉醒 +1/+1


def test_fhh_yanwu_enhance_counts_player_damage(real_game):
    """炎舞增强：凤凰火每对敌方牌手造成 1 次伤害 +1——凤鸣直击与投射各计 1 次。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    play(g, 0, FM)                            # 直击 2 + 投射 1 = 2 次
    assert pa.card_mods[YW]["enhance"] == 2
    play(g, 0, YW)                            # (5+2) 贯通投射打脸；炎舞本身再触发基础投射 1
    assert pb.health == 30 - 3 - 7 - 1


def test_fhh_yanwu_piercing_overflow(real_game):
    """炎舞贯通：投射命中战斗区式神，溢出给牌手；随后基础投射再打脸。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    move(g, 1, 0)
    pb.shikigami[0].health = 3
    play(g, 0, YW)                            # 5 → B0(3) 亡，溢出 2 打脸
    assert pb.shikigami[0].defeated
    assert pb.health == 27                    # 溢出 2 + 基础投射 1


def test_fhh_chuyun_generates_fenghuo(real_game):
    """出云：凤凰火使用法术牌时，将一张'凤火'置入手牌。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    play(g, 0, CY)
    play(g, 0, FM)
    assert any(c.id == FH for c in pa.hand)


# ==========================================================================
# 山童（100116）
#
# 覆盖：先天[贯通]（ShikigamiDef.keywords）、鲁莽回合开始自动攻击、怪力永久力量
# （非战力提取）、怒吼永久/临时分层、笨拙敌方回合力量覆写、碎岩穿刺、
# 觉醒免疫敌方非战斗伤害、伺机响应（敌方回合光环 + 反击贯通）、崩山增强。
# 队伍 [山童, 凤凰火, 白狼, 妖刀姬]。
# ==========================================================================

LM, GL, NH, BN = 10011601, 10011602, 10011603, 10011604   # 鲁莽/怪力/怒吼/笨拙
SY, ST_AWAKEN, SJI, BS = 10011605, 10011606, 10011607, 10011608

ST_TEAM = [100116, 100105, 100101, 100123]


def test_st_innate_piercing_overflow(real_game):
    """先天[贯通]：出击击杀战斗区式神，溢出伤害给牌手。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    move(g, 1, 0)                             # B0 山童入战斗区
    pb.shikigami[0].health = 2
    g.apply({"op": "assault", "index": 0})    # 山童 3 贯通 → B0 亡，溢出 1
    assert pb.shikigami[0].defeated
    assert pb.health == 29
    assert pa.shikigami[IDX].health == 1      # 气绝在战斗结束后结算：反击 3 照常


def test_st_lumang_auto_attack(real_game):
    """鲁莽：己方回合开始山童自动发起攻击（不耗鬼火/出击次数）。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    play(g, 0, LM)                            # 形态 3/5
    pass_turns(g, 2)                          # 回到 A 回合开始：自动攻击打脸 3
    assert pb.health == 27
    assert pa.combat_index == IDX             # 攻击后留在战斗区


def test_st_guaili_perm_power_not_battle_power(real_game):
    """怪力：永久 +1 力量按常规效果步执行（不提取为本次战斗战力）；当次战斗已生效。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    play(g, 0, GL)
    s = pa.shikigami[IDX]
    assert s.perm_power == 1
    assert s.combat_power == 0                # 无战力通道
    assert pb.health == 26                    # 3+1=4 直击
    assert pa.combat_index == IDX


def test_st_nuhou_perm_self_temp_others(real_game):
    """怒吼：山童永久 +1 力量；其他己方式神临时 +1（气绝清除层）。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 1, 1: 1})
    play(g, 0, NH)
    assert pa.shikigami[IDX].perm_power == 1
    assert pa.shikigami[1].temp_power == 1
    assert pa.shikigami[1].perm_power == 0


def test_st_benzhuo_power_zero_on_enemy_turn(real_game):
    """笨拙：敌方回合力量覆写为 0，己方回合开始解除。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 2})
    play(g, 0, BN)                            # 形态 6/9
    s = pa.shikigami[IDX]
    assert s.eff_power == 6
    pass_turns(g, 1)                          # B 回合开始：覆写
    assert s.eff_power == 0
    pass_turns(g, 1)                          # A 回合开始：解除
    assert s.eff_power == 6


def test_st_suiyan_pierce_strips_shield(real_game):
    """碎岩：[穿刺] 先移除目标全部护甲再结算伤害；+2 战力/+2 一次性护甲。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 2})
    move(g, 1, 0)
    b0 = pb.shikigami[0]
    g.apply({"op": "debug_set_stat",
             "args": {"target": {"player": 1, "shikigami": 0}, "key": "shield", "value": 2}})
    play(g, 0, SY)                            # 3+2=5，穿刺移除 2 护甲
    assert b0.defeated and b0.shield == 0
    assert pb.health == 29                    # 先天贯通：溢出 1
    s = pa.shikigami[IDX]
    assert s.shield == 0 and s.health == 3    # 反击 3：一次性护甲吸收 2 后扣 1


def test_st_awaken_effect_immunity(real_game):
    """觉醒·山童：免疫敌方非战斗伤害——己方来源与战斗伤害不免疫。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 2, 1: 1})
    play(g, 0, ST_AWAKEN)
    s = pa.shikigami[IDX]
    assert s.health == 5                      # 觉醒 +1/+1
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, Ref(player=1, shikigami=0))
    assert s.health == 5                      # 敌方非战斗伤害：免疫
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, Ref(player=0, shikigami=1))
    assert s.health == 3                      # 己方来源：不免疫
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, Ref(player=1, shikigami=0),
                        kind="combat")
    assert s.health == 1                      # 战斗伤害：不免疫


def test_st_siji_response_counter_piercing(real_game):
    """伺机：敌方回合开始登记"此牌 +2 力量"光环（card_id 谓词）；山童被攻击时响应
    插入使用——反击 3+2 战力+2 光环=7 且贯通，击杀攻击者并溢出。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 1, 1: 1})
    pb.shikigami[0].level = 2                 # 伺机为 2 级牌
    give(g, 1, SJI)
    pass_turns(g, 2)                          # A 第 2 回合开始：B 的光环触发登记
    move(g, 1, 0)                             # B0 山童入战斗区（A 回合内）
    orb = pb.orb
    g.apply({"op": "assault", "index": 0})    # A0 山童 3 出击 → B 响应伺机
    b0 = pb.shikigami[0]
    assert b0.health == 2                     # 3 - 伺机 1 护甲 = 2
    assert pa.shikigami[IDX].defeated         # 反击 7 > 4
    assert pa.health == 27                    # 反击贯通：溢出 3
    assert any(c.id == SJI for c in pb.graveyard)
    assert pb.orb == orb - 1                  # 响应付 1 火


def test_st_bengshan_perm_power_enhance(real_game):
    """崩山增强：山童每永久 1 力量，战斗区/准备区伤害各自 +1（先怒吼：5/2）。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 3, 1: 1})
    move(g, 1, 0)
    play(g, 0, NH)                            # 山童永久 +1
    play(g, 0, BS)
    assert pb.shikigami[0].defeated           # 战斗区 4+1=5 > 4
    assert [s.health for s in pb.shikigami[1:]] == [2, 2, 2]   # 准备区 1+1=2


def test_st_bengshan_base_damage(real_game):
    """崩山无永久力量时：战斗区 4、准备区 1。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 3})
    move(g, 1, 0)
    play(g, 0, BS)
    assert pb.shikigami[0].defeated           # 4 = 4
    assert [s.health for s in pb.shikigami[1:]] == [3, 3, 3]


# ==========================================================================
# 姑获鸟（100106）基础能力（卡牌未设计，构筑池过滤见 test_deck.py）
# ==========================================================================

GHN_TEAM = [100106, 100101, 100102, 100123]


def test_ghn_retreat_after_assault(real_game):
    """姑获鸟攻击后移回准备区。"""
    g, pa, pb = _game(real_game, GHN_TEAM)
    g.apply({"op": "assault", "index": 0})    # 3 攻打脸
    assert pb.health == 27
    assert pa.combat_index is None            # 攻击后自动退回准备区


# ==========================================================================
# 青行灯（100112）基础能力与明灯（其余卡牌未设计）
# ==========================================================================

QXD_TEAM = [100112, 100101, 100123, 100127]
MD = 10011201                                 # 明灯


def test_qxd_generates_mingdeng_on_enemy_turn(real_game):
    """敌方回合开始时若你有剩余鬼火 → 获得一张'明灯'（手牌明灯数 +1；
    卡组本身含明灯 01×2，以计数差判定而非有无）。"""
    g, pa, pb = _game(real_game, QXD_TEAM)    # pa.orb = 9
    n = sum(1 for c in pa.hand if c.id == MD)
    pass_turns(g, 1)                          # B 回合开始
    assert sum(1 for c in pa.hand if c.id == MD) == n + 1


def test_qxd_no_mingdeng_without_orb(real_game):
    """无剩余鬼火：不获得明灯。"""
    g, pa, pb = _game(real_game, QXD_TEAM)
    pa.orb = 0
    n = sum(1 for c in pa.hand if c.id == MD)
    pass_turns(g, 1)
    assert sum(1 for c in pa.hand if c.id == MD) == n


def test_qxd_mingdeng_gains_orb(real_game):
    """明灯：[瞬发] 获得 1 点鬼火（本回合首张瞬发免费 → 净 +1）。"""
    g, pa, pb = _game(real_game, QXD_TEAM)
    pass_turns(g, 2)                          # B 回合开始已生成明灯；回到 A 回合鬼火重置
    assert any(c.id == MD for c in pa.hand)
    orb = pa.orb
    play(g, 0, MD)
    assert pa.orb == orb + 1
