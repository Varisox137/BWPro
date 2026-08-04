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
YC_FORM_A, YC_FORM_B = 10012752, 10012753  # 测试库注册的萤草形态牌（衍生号段）


def _yc_form(cid: int, name: str, steps=()) -> CardDef:
    return CardDef(id=cid, version=20260728, name=name, shikigami=YC,
                   card_type="form", rarity="R", level=1, cost=1,
                   form_power=2, form_health=3,
                   effects=EffectBlock(steps=list(steps)), text="")


@pytest.fixture
def gdb():
    """真实 db + 测试库临时注册：萤草测试形态牌 A（空白进场）/B（进场 +2 护甲，
    衍生号段 52/53——萤草 01-08 已于第十四阶段补齐真卡）；
    姑获鸟（卡牌未设计，10010601-04 全空白）与青行灯（仅明灯 01 为真卡，
    10011202-04 空白）同样补足 01-04。
    本覆盖原属 test_yingcao.py，合并后萤草基础能力测试（本文件）与灵矢贯虹测试
    （test_reinforce.py）各持一份。"""
    db = CardDatabase.load()
    db.cards[YC_FORM_A] = _yc_form(YC_FORM_A, "测试形态·花")
    db.cards[YC_FORM_B] = _yc_form(YC_FORM_B, "测试形态·叶", steps=[
        Step(op="gain_shield", amount=2, target=TargetSpec(kind="self"))])
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
KAZAMI = 10010402     # 风神一扇
SEIGI = 10010408      # 吾即正义
SHIELD = 10010403     # 暴风之盾
KUROBA = 10010401     # 黑羽之刃
LORD = 10010404       # 暴风之主
FUURAN = 10010405     # 天狗风乱
HA = 10010406         # 羽刃暴风
DT_AWAKEN = 10010407  # 觉醒·大天狗

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


# ---------- 02 风神一扇 ----------

def test_projectile_retreats_damaged_to_bench(real_game):
    """投射命中战斗区式神：受伤者移回准备区（last_damage_victims 引用上一步受伤者）。"""
    g, pa, pb = _game(real_game, DT_TEAM)
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    assert pb.combat_index == 1
    play(g, 0, KAZAMI)
    wolf = pb.shikigami[1]
    assert wolf.health == 2                   # 2 伤
    assert pb.combat_index is None            # 被移回准备区
    assert wolf.in_play                       # 非气绝/离场


# ---------- 08 吾即正义 ----------

def test_transform_after_ten_spells(real_game):
    """本局使用 10 张法术后增强生效：打出消灭所有敌方式神（计数含吾即正义之外的法术）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    for _ in range(10):
        play(g, 0, KAZAMI)
        pa.orb = 9
    store = pa.card_mods[SEIGI]
    assert store["spell_count"] == 10
    assert store["transformed"] == 1
    play(g, 0, SEIGI)                         # 第 11 张法术：打出装配读取已置位的 transformed
    assert all(s.defeated for s in pb.shikigami)
    assert store["spell_count"] == 11         # 吾即正义自身也计数


def test_no_effect_before_transform_threshold(real_game):
    """9 张法术时增强未生效：打出无效果（开服版吾即正义无基础效果、无[瞬发]）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    for _ in range(9):
        play(g, 0, KAZAMI)
        pa.orb = 9
    assert pa.card_mods[SEIGI]["spell_count"] == 9
    assert "transformed" not in pa.card_mods[SEIGI]
    play(g, 0, SEIGI)
    assert all(not s.defeated for s in pb.shikigami)


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


# ---------- 01 黑羽之刃 ----------

def test_kuroba_fast_projectile(real_game):
    """黑羽之刃：[瞬发]（回合内首张免费）投射 2 伤；战斗区无人则落空至牌手。"""
    g, pa, pb = _game(real_game, DT_TEAM)
    move(g, 1, 0)                             # B 大天狗（3/4）入战斗区
    orb_before = pa.orb
    play(g, 0, KUROBA)
    assert pb.shikigami[0].health == 2        # 4 - 2
    assert pa.orb == orb_before               # 首张瞬发 0 费
    g2, pa2, pb2 = _game(real_game, DT_TEAM)
    play(g2, 0, KUROBA)
    assert pb2.health == 28                   # 投射落空 → 牌手 2 伤


# ---------- 04 暴风之主 ----------

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


# ---------- 05 天狗风乱 / 06 羽刃暴风 ----------

def test_distribute_damage_all_enemies(real_game):
    """天狗风乱：合计 6 点伤害随机分配给所有敌方角色（含牌手；生命≤0 退出分配）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 2})
    total_before = pb.health + sum(s.health for s in pb.shikigami)
    play(g, 0, FUURAN)
    total_after = pb.health + sum(max(s.health, 0) for s in pb.shikigami)
    assert total_before - total_after == 6


def test_damage_each_enemy_shikigami(real_game):
    """羽刃暴风：所有敌方式神各 3 伤（牌手不受）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    play(g, 0, HA)
    assert pb.health == 30
    assert [s.health for s in pb.shikigami] == [1, 1, 3, 1]  # 4/4/6/4 - 3


def test_storm_lord_enemy_shikigami_only(real_game):
    """维护者答复(7)：受影响列表只计敌方式神（去重）——构造性验证出牌伤害帧内
    波及的己方式神不进列表（羽刃暴风开服版已不再伤牌手）。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    play(g, 0, LORD)
    play(g, 0, HA)                            # 羽刃暴风：敌方式神各 3
    assert pb.health == 30                    # 牌手不受
    assert [s.health for s in pb.shikigami] == [0, 0, 2, 0]  # 4/4/6/4 - 3 - 1
    # 构造：己方式神被波及不进 affected_refs
    g._affected_stack.append({"controller": 0, "refs": []})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 2, None)
    g.deal_to_shikigami(Ref(player=1, shikigami=2), 2, None)
    rec = g._affected_stack.pop()
    assert rec["refs"] == [Ref(player=1, shikigami=2)]


# ---------- 07 觉醒·大天狗 ----------

def test_awaken_replace_and_initial_one(real_game):
    """觉醒（维护者答复(10)+法术觉醒流程）：替换在法术效果之前——继承原能力记录的
    动态倒计时并变为倒计时 1，[倒计时]-1 随之归零 → 自动使用记录的法术；
    记录不随替换丢失（气绝才清）；+1/+1 随"觉醒后"延时时机授予。"""
    g, pa, pb = _game(real_game, DT_TEAM, {IDX: 3})
    s = pa.shikigami[IDX]
    play(g, 0, KAZAMI)
    assert s.countdown == 2                   # 基础能力的一次型倒计时
    assert pb.health == 28
    play(g, 0, DT_AWAKEN)
    assert s.awakened == DT_AWAKEN
    assert g.history.index("on_before_awaken") < g.history.index("on_awakened")
    assert s.perm_power == 1 and s.perm_health == 1
    assert s.max_health == 5 and s.health == 5
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
# 覆盖：基础倒计时治疗、三觉醒替换+"觉醒前"旧能力倒计时 -3 再完成替换（on_before_awaken，
# 第十阶段维护者答复）、大合奏按 countdown_history 首次出现顺序重放（replay_countdown +
# _countdown_block_for）、魔音扰心无效化（主动 delay_grant / 响应 response 覆盖块两路径）、
# 惊弦/疯魔琴心/余音的 countdown_delta（含无倒计时修正 -0）、镇魂歌抽牌+鬼火。
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


# ---------- 法术觉醒："觉醒前"旧能力倒计时 -3，再完成替换（三张不同卡牌用例） ----------

def test_awaken_countdown_minus_before_replacement(real_game):
    """法术觉醒牌共用流程（觉醒·入阵歌/神乐歌/镇魂歌；第十阶段维护者答复）：
    永久身材修正 + 觉醒替换注册倒计时 3（来源=觉醒牌 id）；同名触发挂"觉醒前"
    （on_before_awaken，能力替换前）——对被替换掉的旧能力倒计时 -3，归零则先结算
    旧倒计时效果，再完成替换（新注册倒计时不受本次 -3 影响）。"""
    # 入阵歌：+0/+1 永久；旧能力（基础）倒计时 -3 → 归零治疗（不触发入阵歌的 5 伤）
    g, pa, pb = _game(real_game, YQS_TEAM)
    s = pa.shikigami[IDX]
    pa.health = 20
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, RUZHENG)
    assert pa.health == 23                    # 旧能力（基础）归零：治疗 3
    assert s.awakened == RUZHENG
    assert s.perm_health == 1
    assert s.countdown == 3 and s.countdown_source == RUZHENG   # 新倒计时注册 3，不受 -3
    assert enemy_total == sum(x.health for x in pb.shikigami) + pb.health  # 无 5 伤
    assert pa.ext["countdown_history"] == [YQS]
    # 神乐歌：+1/+0 永久；旧能力归零治疗，己方其他式神倒计时/增益不变（神乐歌不归零）
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 2})
    _register_allied_countdowns(g)            # 鸩/以津真天倒计时均为 2
    s = pa.shikigami[IDX]
    play(g, 0, SHENYUE)
    assert s.awakened == SHENYUE and s.perm_power == 1
    zhen, yjzt = pa.shikigami[1], pa.shikigami[2]
    assert zhen.countdown == 2 and yjzt.countdown == 2          # 不变（神乐歌未归零）
    assert zhen.temp_power == 0 and zhen.temp_health == 0
    assert s.countdown == 3 and s.countdown_source == SHENYUE
    assert pa.ext["countdown_history"] == [YQS]
    # 镇魂歌：+1/+1 永久；旧能力归零治疗，不抽牌不得火（镇魂歌未归零）
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    s = pa.shikigami[IDX]
    hand_before = len(pa.hand)
    play(g, 0, ZHENHUN)                       # 1 火
    assert s.awakened == ZHENHUN
    assert s.perm_power == 1 and s.perm_health == 1
    assert pa.orb == 8                        # 9 - 1（镇魂歌未归零，无 +1 火）
    assert len(pa.hand) == hand_before        # 不抽牌
    assert s.countdown == 3 and s.countdown_source == ZHENHUN
    assert pa.ext["countdown_history"] == [YQS]
    # 二次觉醒：旧能力 = 上一个觉醒能力——入阵歌先觉醒，再打镇魂歌时入阵歌倒计时
    # -3 归零（5 伤生效）后才替换为镇魂歌
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    s = pa.shikigami[IDX]
    play(g, 0, RUZHENG)                       # 基础归零治疗，替换为入阵歌
    assert pa.ext["countdown_history"] == [YQS]
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, ZHENHUN)                       # 觉醒前：入阵歌倒计时 -3 → 归零 5 伤
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 5
    assert s.awakened == ZHENHUN
    assert s.countdown == 3 and s.countdown_source == ZHENHUN
    assert pa.ext["countdown_history"] == [YQS, RUZHENG]


# ---------- 03 大合奏：按 history 首次出现顺序重放 ----------

def test_replay_countdown_history_order(real_game):
    """大合奏：按 history 首次出现顺序依次重放，每种至多一次（第十阶段新语义：
    觉醒前旧能力 -3——入阵歌在镇魂歌觉醒前被归零计入 history，镇魂歌自身未归零）。"""
    g, pa, pb = _game(real_game, YQS_TEAM, {IDX: 3})
    pa.health = 20
    pass_turns(g, 4)                          # 基础归零：pa 20→23，history [100124]
    assert pa.ext["countdown_history"] == [YQS]
    pa.orb = 9                                # 回合开始已重置鬼火：重设便于核算
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, RUZHENG)                       # 觉醒前：基础归零治疗 23→26（history 追加 YQS）
    play(g, 0, ZHENHUN)                       # 觉醒前：入阵歌归零 5 伤（history 追加 RUZHENG）
    assert pa.ext["countdown_history"] == [YQS, YQS, RUZHENG]
    assert pa.health == 26
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 5
    assert pa.orb == 7                        # 9 - 2（镇魂歌未归零，无 +1 火）
    log_before = len(g.state.log)
    play(g, 0, DAHEZOU)                       # 瞬发免费
    # 依次重放：基础治疗（26→29）、入阵歌（敌方再 -5）；镇魂歌不在 history 不重放
    assert pa.health == 29
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 10
    assert pa.orb == 7
    replay_logs = [m for m in g.state.log[log_before:] if "重放" in m]
    ids = [next(sid for sid in (YQS, RUZHENG, ZHENHUN) if f"来源 {sid}）" in m)
           for m in replay_logs]
    assert ids == [YQS, RUZHENG]              # 按 history 首次出现顺序，每种至多一次


def test_replay_countdown_skips_form_sources(real_game, gdb):
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

def test_nullify_next_enemy_card(real_game):
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


def test_nullify_current_card_response(real_game):
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

def test_countdown_delta_immediate_trigger_and_noop(real_game):
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


def test_countdown_delta_both_sides(real_game):
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


def test_countdown_delta_allies_minus(real_game):
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

def test_free_cost_after_tag_accounting(real_game):
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
    # turn 级条目在下一半回合开始由状态层清理（显示残留修复：对手回合场况不再显示"免疫"）
    pass_turns(g, 1)
    assert not [e for e in pa.shikigami[IDX].immunities if "turn" in e]


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


def test_ext_counter_survives_defeat(real_game):
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

def test_convert_damage_both_sides_active(real_game):
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


def test_convert_damage_response(real_game):
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


def test_convert_damage_net_effect(real_game):
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

def test_awaken_ext_scaling_countdown(real_game):
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

def test_lifesteal_granted_vs_fragile(real_game):
    """攻击有破甲的角色：获得[吸血]（实卡路径：伤害后为牌手恢复等量生命）。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    pa.health = 20
    pb.shikigami[1].shield = -1               # B 白狼持 1 破甲
    move(g, 1, 1)
    play(g, 0, ZMYH)                          # 鸩 2+2=4 攻 → 白狼 4+1=5 伤气绝
    assert pb.shikigami[1].defeated
    assert pa.health == 25                    # 吸血：恢复 5（伤害值）


def test_lifesteal_denied_without_fragile(real_game):
    """被攻击者无破甲：不获得吸血。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 2})
    pa.health = 20
    move(g, 1, 2)                             # B 兵俑（1/6）无破甲
    play(g, 0, ZMYH)
    assert pb.shikigami[2].health == 2        # 4 伤
    assert pa.health == 20                    # 无吸血
    assert pa.shikigami[IDX].health == 5      # +2 护甲吸收反击 1


# ---------- 07 碧羽散华：获得破甲→伤害 ----------

def test_fragile_gain_converts_to_damage(real_game):
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

def test_half_health_fragile(real_game):
    """对敌方角色造成战斗伤害后：目标获得等同于其当前生命一半（向下取整）的破甲。"""
    g, pa, pb = _game(real_game, ZHEN_TEAM, {IDX: 3})
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    play(g, 0, DZH)                           # 鸩 2 攻 → 兵俑 6→4 → 破甲 4//2=2
    soldier = pb.shikigami[2]
    assert soldier.health == 4 and soldier.shield == -2
    assert pa.shikigami[IDX].health == 4      # 反击 1（+0/+0 无护甲）


# ---------- 03 寂寥心象：每回合合计一次 ----------

def test_fragile_countdown_once_per_turn_gate(real_game):
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


def test_player_fragile_mirror_combat(real_game):
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


def test_projectile_on_own_spell(real_game):
    """基础能力：凤凰火使用专属法术（凤鸣）→ [投射]1（B 战斗区空 → 打脸）。"""
    g, pa, pb = _game(real_game, FHH_TEAM)
    play(g, 0, FM)                            # 凤鸣 3 + 投射 1
    assert pb.health == 26


def test_kill_pings_enemy_player(real_game):
    """引燃消灭敌方式神：再对它的牌手造成 2（victim_player 语境目标）。"""
    g, pa, pb = _game(real_game, FHH_TEAM)
    pb.shikigami[0].health = 2
    play(g, 0, YR, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].defeated
    assert pb.health == 27                    # 消灭追加 2 + 投射 1


def test_kill_pings_own_player(real_game):
    """引燃可对己方式神使用（维护者确认）：消灭己方式神 → 对己方牌手造成 2。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 1, 1: 1})
    pa.shikigami[1].health = 2
    play(g, 0, YR, target=Ref(player=0, shikigami=1))
    assert pa.shikigami[1].defeated
    assert pa.health == 28
    assert pb.health == 29                    # 投射 1


def test_boost_effect_damage(real_game):
    """焚羽：凤凰火造成的非战斗伤害 +1——凤鸣直击与基础投射均吃增幅。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 2})
    play(g, 0, FY)
    play(g, 0, FM)                            # (3+1) + 投射 (1+1)
    assert pb.health == 24


def test_awaken_projectile_any_spell(real_game):
    """觉醒·凤凰火：己方式神使用任意专属法术均投射 1（觉醒牌本身已触发一次）；
    凤凰火自己的法术只触发一次（基础能力已被觉醒能力替换）。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 2, 1: 1})
    play(g, 0, FHH_AWAKEN)
    assert pa.shikigami[IDX].awakened == FHH_AWAKEN
    assert pb.health == 29                    # 觉醒牌自身的使用事件已触发觉醒能力
    play(g, 0, 10011603)                      # 山童怒吼（其他式神的专属法术）→ 投射 1
    assert pb.health == 28
    play(g, 0, FM)                            # 凤鸣 3 + 投射 1（只触发一次）
    assert pb.health == 24
    assert pa.shikigami[IDX].perm_power == 1  # 觉醒 +1/+1


def test_enhance_per_player_damage(real_game):
    """炎舞增强：凤凰火每对敌方牌手造成 1 次伤害 +1——凤鸣直击与投射各计 1 次。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    play(g, 0, FM)                            # 直击 3 + 投射 1 = 2 次
    assert pa.card_mods[YW]["enhance"] == 2
    play(g, 0, YW)                            # (5+2) 贯通投射打脸；炎舞本身再触发基础投射 1
    assert pb.health == 30 - 4 - 7 - 1


def test_piercing_projectile_overflow(real_game):
    """炎舞贯通：投射命中战斗区式神，溢出给牌手；随后基础投射再打脸。"""
    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    move(g, 1, 0)
    pb.shikigami[0].health = 3
    play(g, 0, YW)                            # 5 → B0(3) 亡，溢出 2 打脸
    assert pb.shikigami[0].defeated
    assert pb.health == 27                    # 溢出 2 + 基础投射 1


def test_generate_on_spell_play(real_game):
    """出云：凤凰火使用法术牌时，[运势4]成功才将一张'凤火'置入手牌。"""
    class _Rng:  # 确定性骰桩：randint 固定返回指定点
        def __init__(self, roll):
            self.roll = roll

        def randint(self, a, b):
            return self.roll

        def choice(self, seq):
            return seq[0]

        def sample(self, seq, n):
            return list(seq)[:n]

        def shuffle(self, seq):
            pass

    g, pa, pb = _game(real_game, FHH_TEAM, {IDX: 3})
    g.rng = _Rng(6)                           # 运势4 成功
    play(g, 0, CY)
    play(g, 0, FM)
    assert any(c.id == FH for c in pa.hand)
    g2, pa2, pb2 = _game(real_game, FHH_TEAM, {IDX: 3})
    g2.rng = _Rng(1)                          # 运势4 失败：不生成
    play(g2, 0, CY)
    play(g2, 0, FM)
    assert not any(c.id == FH for c in pa2.hand)


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


def test_innate_piercing_overflow(real_game):
    """先天[贯通]：出击击杀战斗区式神，溢出伤害给牌手。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    move(g, 1, 0)                             # B0 山童入战斗区
    pb.shikigami[0].health = 2
    g.apply({"op": "assault", "index": 0})    # 山童 3 贯通 → B0 亡，溢出 1
    assert pb.shikigami[0].defeated
    assert pb.health == 29
    assert pa.shikigami[IDX].health == 1      # 气绝在战斗结束后结算：反击 3 照常


def test_auto_attack_turn_start(real_game):
    """鲁莽：己方回合开始山童自动发起攻击（不耗鬼火/出击次数）。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    play(g, 0, LM)                            # 形态 3/5
    pass_turns(g, 2)                          # 回到 A 回合开始：自动攻击打脸 3
    assert pb.health == 27
    assert pa.combat_index == IDX             # 攻击后留在战斗区


def test_perm_power_not_battle_power(real_game):
    """怪力：永久 +1 力量按常规效果步执行（不提取为本次战斗战力）；当次战斗已生效。"""
    g, pa, pb = _game(real_game, ST_TEAM)
    play(g, 0, GL)
    s = pa.shikigami[IDX]
    assert s.perm_power == 1
    assert s.combat_power == 0                # 无战力通道
    assert pb.health == 26                    # 3+1=4 直击
    assert pa.combat_index == IDX


def test_perm_self_temp_allies(real_game):
    """怒吼：山童永久 +1 力量；其他己方式神临时 +1（气绝清除层）。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 1, 1: 1})
    play(g, 0, NH)
    assert pa.shikigami[IDX].perm_power == 1
    assert pa.shikigami[1].temp_power == 1
    assert pa.shikigami[1].perm_power == 0


def test_power_zero_enemy_turn(real_game):
    """笨拙：敌方回合力量覆写为 0，己方回合开始解除。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 2})
    play(g, 0, BN)                            # 形态 6/9
    s = pa.shikigami[IDX]
    assert s.eff_power == 6
    pass_turns(g, 1)                          # B 回合开始：覆写
    assert s.eff_power == 0
    pass_turns(g, 1)                          # A 回合开始：解除
    assert s.eff_power == 6


def test_pierce_strips_shield_before_damage(real_game):
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


def test_awaken_enemy_effect_immunity(real_game):
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


def test_counter_piercing_response(real_game):
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


def test_perm_power_enhance_snapshot(real_game):
    """崩山增强：山童每永久 1 力量，战斗区/准备区伤害各自 +1（先怒吼：5/2）。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 3, 1: 1})
    move(g, 1, 0)
    play(g, 0, NH)                            # 山童永久 +1
    play(g, 0, BS)
    assert pb.shikigami[0].defeated           # 战斗区 4+1=5 > 4
    assert [s.health for s in pb.shikigami[1:]] == [2, 2, 2]   # 准备区 1+1=2


def test_zone_base_damage(real_game):
    """崩山无永久力量时：战斗区 4、准备区 1。"""
    g, pa, pb = _game(real_game, ST_TEAM, {IDX: 3})
    move(g, 1, 0)
    play(g, 0, BS)
    assert pb.shikigami[0].defeated           # 4 = 4
    assert [s.health for s in pb.shikigami[1:]] == [3, 3, 3]


# ==========================================================================
# 青行灯（100112）基础能力与明灯（其余卡牌未设计）
# ==========================================================================

QXD_TEAM = [100112, 100101, 100123, 100127]
MD = 10011201                                 # 明灯


def test_token_on_enemy_turn_with_orb(real_game):
    """敌方回合开始时若你有剩余鬼火 → 获得一张'明灯'（手牌明灯数 +1；
    卡组本身含明灯 01×2，以计数差判定而非有无）。"""
    g, pa, pb = _game(real_game, QXD_TEAM)    # pa.orb = 9
    n = sum(1 for c in pa.hand if c.id == MD)
    pass_turns(g, 1)                          # B 回合开始
    assert sum(1 for c in pa.hand if c.id == MD) == n + 1


def test_no_token_without_orb(real_game):
    """无剩余鬼火：不获得明灯。"""
    g, pa, pb = _game(real_game, QXD_TEAM)
    pa.orb = 0
    n = sum(1 for c in pa.hand if c.id == MD)
    pass_turns(g, 1)
    assert sum(1 for c in pa.hand if c.id == MD) == n


def test_token_fast_gains_orb(real_game):
    """明灯：[瞬发] 获得 1 点鬼火（本回合首张瞬发免费 → 净 +1）。"""
    g, pa, pb = _game(real_game, QXD_TEAM)
    pass_turns(g, 2)                          # B 回合开始已生成明灯；回到 A 回合鬼火重置
    assert any(c.id == MD for c in pa.hand)
    orb = pa.orb
    play(g, 0, MD)
    assert pa.orb == orb + 1


# ==========================================================================
# 犬神（100115）
#
# 覆盖：升级生成'心身炼磨'（指令升级与 level_up op 两来源）、心身炼磨动态
# 瞬发/费用、心技一体计数光环（scope=form 随形态离场）、心剑乱舞瞬发光环、
# 守护响应换人改目标（追猎类定向战斗可响应但不转移目标）、心即归处气绝
# 可用+气绝限定门控、觉醒·犬神仅气绝触发。
# 队伍固定 [犬神, 白狼, 妖刀姬, 山童]，犬神 0 号位。
# ==========================================================================

QS = 100115      # 犬神（双方 0 号位）
XINZHAN = 10011502        # 心斩
XINGUI = 10011503         # 心即归处
XINJI = 10011505          # 心技一体
SHOUHU = 10011506         # 守护
XINJIAN = 10011507        # 心剑乱舞
QS_AWAKEN = 10011508      # 觉醒·犬神
LIANMO = 10011551         # 心身炼磨（衍生）

QS_TEAM = [100115, 100101, 100123, 100116]


def test_upgrade_generates_token(real_game):
    """升级生成衍生牌：犬神升级时'心身炼磨'置入手牌——指令升级与 level_up op
    （百闻一得类效果升级）两来源均触发。"""
    from core.model import ExecContext
    g = real_game(QS_TEAM, auto_skip_upgrade=False)
    pa, pb = F.battle_setup(g, {1: 1, 2: 1, 3: 1})   # 全员 1 级（0 号位开局自动 1 级）
    g.apply({"op": "upgrade", "index": 0})    # 指令升级 1→2
    assert sum(1 for c in pa.hand if c.id == LIANMO) == 1
    g._resolve_block(EffectBlock(steps=[Step(op="level_up", target=TargetSpec(kind="self"))]),
                     ExecContext(controller=0, source=Ref(player=0, shikigami=IDX)))
    assert pa.shikigami[IDX].level == 3
    assert sum(1 for c in pa.hand if c.id == LIANMO) == 2


def test_conditional_keyword_and_cost_by_level(real_game):
    """动态关键字/费用（心身炼磨）：犬神 2 级获得[瞬发]、3 级不消耗鬼火；1 级均无。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 1})
    cdef = g.db.cards[LIANMO]
    card = give(g, 0, LIANMO)
    assert "fast" not in g._card_keywords(pa, cdef, card)
    assert g._effective_cost(pa, cdef, card) == 1
    pa.shikigami[IDX].level = 2
    assert "fast" in g._card_keywords(pa, cdef, card)
    assert g._effective_cost(pa, cdef, card) == 0   # 2 级：[瞬发]首张免费
    pa.fast_used = True
    assert g._effective_cost(pa, cdef, card) == 1   # 瞬发名额已用：照常付 1 火
    pa.shikigami[IDX].level = 3
    assert g._effective_cost(pa, cdef, card) == 0   # 3 级：不消耗鬼火


def test_tag_count_aura(real_game):
    """计数光环（心技一体）：本局每使用过一张'心身炼磨'（tags lianmo 记账），犬神
    战斗牌额外 +1/+1（读取时求值）；形态离场光环移除（scope=form）。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 2})
    play(g, 0, XINJI)
    cdef = g.db.cards[XINZHAN]
    card = give(g, 0, XINZHAN)
    stats = lambda: g.combat_card_stats(cdef.effects, card, pa.shikigami[IDX], pa)
    assert stats() == (0, 2)                        # 心斩 +0/+2
    play(g, 0, LIANMO)                              # 第 1 张（2 级瞬发免费）
    play(g, 0, LIANMO)                              # 第 2 张（付 1 火）
    assert stats() == (2, 4)
    g._destroy_form(pa, IDX, "effect")
    assert stats() == (0, 2)


def test_form_aura_grants_fast(real_game):
    """关键字光环（心剑乱舞）：犬神的牌获得[瞬发]；形态离场失去（scope=form）。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 3})
    cdef = g.db.cards[XINZHAN]
    card = give(g, 0, XINZHAN)
    assert "fast" not in g._card_keywords(pa, cdef, card)
    play(g, 0, XINJIAN)
    assert "fast" in g._card_keywords(pa, cdef, card)
    g._destroy_form(pa, IDX, "effect")
    assert "fast" not in g._card_keywords(pa, cdef, card)


def test_response_combat_swaps_target(real_game):
    """守护：其他式神被攻击时响应插入使用——犬神移入战斗区、攻击目标改为犬神，
    +4 护甲吸收本次伤害。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 1, 1: 1})
    pb.shikigami[0].level = 2                 # 守护为 2 级牌
    pb.orb = 1                                # 响应付 1 火
    give(g, 1, SHOUHU)
    move(g, 1, 1)                             # B1 白狼入战斗区（A 回合内）
    g.apply({"op": "assault", "index": 0})    # A0 犬神 2 出击 → B 响应守护
    b0 = pb.shikigami[0]
    assert pb.combat_index == 0               # 犬神被移入战斗区（目标改为犬神）
    assert pb.shikigami[1].health == 4        # 白狼未受伤
    assert (b0.health, b0.shield) == (5, 2)   # 2 攻 vs 守护 4 护甲
    assert pa.shikigami[IDX].health == 3      # 犬神反击 2
    assert any(c.id == SHOUHU for c in pb.graveyard)


def test_response_vs_hunt_no_retarget(real_game):
    """守护 vs 追猎：响应有目标的战斗（追猎类）时守护者照常移入战斗区并获得
    +0/+4，但攻击目标不转移——仍打原定目标（维护者定案第十三阶段）。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 1, 1: 1})
    pb.shikigami[0].level = 2                 # 守护为 2 级牌
    pb.orb = 1                                # 响应付 1 火
    give(g, 1, SHOUHU)                        # B1 白狼留准备区
    g._resolve_combat(Ref(player=0, shikigami=IDX), pa.shikigami[IDX],
                      target=Ref(player=1, shikigami=1), origin="card")
    b0 = pb.shikigami[0]
    assert any(c.id == SHOUHU for c in pb.graveyard)
    assert pb.orb == 0                        # 响应鬼火已付
    assert pb.combat_index == 0               # 犬神被移入战斗区
    assert (b0.health, b0.shield) == (5, 4)   # +0/+4 生效但未挨打
    assert pb.shikigami[1].health == 2        # 目标未转移：白狼 4-2
    assert pa.shikigami[IDX].health == 2      # 白狼反击 3


def test_revive_self_playable_when_defeated(real_game):
    """气绝时可用（心即归处）：[瞬发]复活犬神。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 2})
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    play(g, 0, XINGUI)
    assert not pa.shikigami[IDX].defeated


def test_only_when_defeated_gate(real_game):
    """气绝限定（心即归处）：only_when_defeated 硬门控——犬神存活时既不能主动
    使用，也不会被响应结算（维护者定案第十三阶段）。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 2})
    with pytest.raises(IllegalAction, match="气绝时可用"):
        play(g, 0, XINGUI)                        # 存活时主动使用被拒
    # 响应侧：挂上触发关键字后，犬神存活仍不结算（响应收集即被门控跳过）
    cdef = g.db.cards[XINGUI]
    cdef.keywords.append("trigger")
    cdef.effects.when = "on_before_assault"
    cdef.effects.condition = {}
    give(g, 0, XINGUI)
    move(g, 0, 0)                                 # A0 犬神入战斗区
    pass_turns(g, 1)                              # → B 回合，A 成非回合方
    orb = pa.orb
    g.apply({"op": "assault", "index": 0})        # B0 出击 → 不响应
    assert any(c.id == XINGUI for c in pa.hand)
    assert not any(c.id == XINGUI for c in pa.graveyard)
    assert pa.orb == orb


def test_awaken_trigger_only_when_defeated(real_game):
    """觉醒·犬神：己方回合结束时仅气绝才触发——复活并永久 +1/+1；存活不触发。"""
    g, pa, pb = _game(real_game, QS_TEAM, {IDX: 3})
    play(g, 0, QS_AWAKEN)
    s = pa.shikigami[IDX]
    assert (s.perm_power, s.perm_health) == (1, 1)    # 觉醒 +1/+1
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    pass_turns(g, 1)                          # A 回合结束：复活 +1/+1
    assert not s.defeated
    assert (s.perm_power, s.perm_health) == (2, 2)
    pass_turns(g, 2)                          # 再过一轮 A 回合结束：存活不触发
    assert (s.perm_power, s.perm_health) == (2, 2)


# ==========================================================================
# 桃花妖（100119）
#
# 覆盖：治疗/复活赋益（基础临时 +1、觉醒永久 +2/+2、倒计时复活不触发）、
# 桃红簇簇进出战斗区治疗连锁赋益、致命免疫一次+移除形态、桃华灼灼群体复活
# 迅捷+气绝可用+动态瞬发、花信风检索（命中才洗牌）、丰实/盛开随机受伤治疗、桃之夭夭鼓舞。
# 队伍固定 [桃花妖, 白狼, 妖刀姬, 山童]，桃花妖 0 号位。
# ==========================================================================

THY = 100119     # 桃花妖（双方 0 号位）
XINXI = 10011901          # 桃之馨息
HUAXIN = 10011902         # 花信风
YAOYAO = 10011903         # 桃之夭夭
FENGSHI = 10011904        # 丰实
CHUNFENG = 10011905       # 桃语春风
SHENGKAI = 10011906       # 盛开
ZHUOZHUO = 10011907       # 桃华灼灼
THY_AWAKEN = 10011908     # 觉醒·桃花妖
TAOHONG = 10011951        # 桃红簇簇（衍生）

THY_TEAM = [100119, 100101, 100123, 100116]


def test_heal_revive_buff(real_game):
    """治疗/复活赋益（桃花妖基础能力）：治疗或复活己方式神时该式神 +1 力量（临时）；
    倒计时复活（来源为空）不触发。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 2, 1: 1, 2: 1})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 2, None)   # 白狼 4→2
    play(g, 0, XINXI, target=Ref(player=0, shikigami=1))       # 桃之馨息
    s1 = pa.shikigami[1]
    assert s1.health == 4 and s1.temp_power == 1
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, None)
    play(g, 0, CHUNFENG, target=Ref(player=0, shikigami=1))    # 桃语春风
    assert not s1.defeated and s1.temp_power == 1              # 复活赋益（临时气绝已清）
    assert "haste" in s1.one_shot_keywords                     # 获得[迅捷]（一次性）
    g.deal_to_shikigami(Ref(player=0, shikigami=2), 99, None)
    pass_turns(g, 6)                          # 3 个 A 回合开始：倒计时归零复活
    s2 = pa.shikigami[2]
    assert not s2.defeated and s2.temp_power == 0


def test_enter_leave_combat_heal(real_game):
    """进出战斗区治疗（桃红簇簇）：己方式神进入/离开战斗区时恢复 2 生命，
    治疗来源=桃花妖→连锁基础赋益 +1 力量。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 2, 1: 1})
    play(g, 0, TAOHONG)
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 3, None)   # 白狼 4→1
    s1 = pa.shikigami[1]
    move(g, 0, 1)                             # 进入战斗区：+2 → 3，赋益 +1
    assert s1.health == 3 and s1.temp_power == 1
    g._retreat(pa, 1)                         # 离开战斗区：+2（封顶 4），赋益再 +1
    g._drain_queue()                          # 引擎内直接调用需手动排空延时队列
    assert s1.health == 4 and s1.temp_power == 2


def test_lethal_immunity_once_then_form_removed(real_game):
    """致命免疫（桃红簇簇）：己方准备区式神受到致命伤害时免疫一次并移除此形态；
    形态不再后第二次致命伤害正常气绝。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 2, 1: 1})
    play(g, 0, TAOHONG)
    s1 = pa.shikigami[1]
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, Ref(player=1, shikigami=0))
    assert s1.health == 4 and not s1.defeated   # 免疫此次伤害（一次消耗）
    assert pa.shikigami[IDX].form is None       # 然后移除此形态
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, Ref(player=1, shikigami=0))
    assert s1.defeated


def test_mass_revive_haste(real_game):
    """群体复活（桃华灼灼）：复活己方所有式神并全员获得[迅捷]；桃花妖未气绝时
    [瞬发]、气绝时可用。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 3, 1: 1, 2: 1})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, None)
    g.deal_to_shikigami(Ref(player=0, shikigami=2), 99, None)
    orb = pa.orb
    play(g, 0, ZHUOZHUO)                      # 桃花妖未气绝：[瞬发]首张免费
    assert pa.orb == orb
    assert not pa.shikigami[1].defeated and not pa.shikigami[2].defeated
    assert all("haste" in s.one_shot_keywords for s in pa.shikigami if s.in_play)
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, None)
    play(g, 0, ZHUOZHUO)                      # 气绝时可用：桃花妖自身一并复活
    assert not pa.shikigami[IDX].defeated and not pa.shikigami[1].defeated


def test_awaken_heal_revive_buff_perm(real_game):
    """觉醒·桃花妖：赋益改为永久 +2/+2（替换基础能力）；满血治疗（实际恢复 0）
    仍触发；复活赋益与既有永久增益累加。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 3, 1: 1})
    s1 = pa.shikigami[1]
    play(g, 0, THY_AWAKEN, target=Ref(player=0, shikigami=1))   # 进场治疗 5（满血）
    assert (s1.perm_power, s1.perm_health) == (2, 2)
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 99, None)
    play(g, 0, CHUNFENG, target=Ref(player=0, shikigami=1))     # 复活再赋益
    assert (s1.perm_power, s1.perm_health) == (4, 4)


def test_search_deck(real_game):
    """检索（花信风）：[瞬发]选择己方式神，牌库随机一张该式神的牌置入手牌并洗牌
    （命中才洗牌：牌库内容多重集不变，仅重排）。"""
    g, pa, pb = _game(real_game, THY_TEAM)
    deck0, orb = len(pa.deck), pa.orb
    hand0 = {c.uid for c in pa.hand}
    before = sorted(c.uid for c in pa.deck)
    play(g, 0, HUAXIN, target=Ref(player=0, shikigami=IDX))
    assert pa.orb == orb                      # 瞬发首张免费
    assert len(pa.deck) == deck0 - 1          # 检索自牌库（非凭空生成）
    drawn = [c for c in pa.hand if c.uid not in hand0]
    assert len(drawn) == 1 and drawn[0].id // 100 == THY   # 该式神的牌（含花信风自身）
    assert sorted([c.uid for c in pa.deck] + [drawn[0].uid]) == before   # 只重排不增删


def test_search_deck_miss_no_shuffle(real_game):
    """检索未命中（花信风）：牌库中没有该式神的牌时检索落空——不补牌也不洗牌
    （维护者定案第十三阶段）。"""
    g, pa, pb = _game(real_game, THY_TEAM)
    pa.deck[:] = [c for c in pa.deck if c.id // 100 != THY]   # 清空牌库中桃花妖的牌
    before = [c.uid for c in pa.deck]
    hand0 = len(pa.hand)
    play(g, 0, HUAXIN, target=Ref(player=0, shikigami=IDX))
    assert [c.uid for c in pa.deck] == before                 # 未命中不洗牌
    assert len(pa.hand) == hand0                              # 未补牌（give 补的已打出）


def test_random_injured_heal(real_game):
    """随机受伤治疗（丰实/盛开）：进场与己方回合开始时随机为受伤己方式神恢复
    （丰实 3×1；盛开 2×3 可集中于同一目标）。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 3, 1: 1, 2: 1})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 3, None)   # 白狼 4→1
    g.deal_to_shikigami(Ref(player=0, shikigami=2), 3, None)   # 山童 4→1
    total = sum(s.health for s in pa.shikigami[1:])   # 排除桃花妖（结附形态身材变化）
    play(g, 0, FENGSHI)
    assert sum(s.health for s in pa.shikigami[1:]) == total + 3    # 进场随机一个 +3
    pass_turns(g, 2)
    assert sum(s.health for s in pa.shikigami[1:]) == total + 6    # 己方回合开始再 +3
    g2, pa2, pb2 = _game(real_game, THY_TEAM, {IDX: 3, 1: 1})
    g2.deal_to_shikigami(Ref(player=0, shikigami=1), 3, None)  # 白狼 4→1（唯一受伤）
    play(g2, 0, SHENGKAI)
    assert pa2.shikigami[1].health == 4        # 2×3 集中于唯一受伤者：回满


def test_inspire_assault_boost(real_game):
    """鼓舞（桃之夭夭）：不消耗鬼火；+2战力/+2护甲出击加成下一次出击全部消耗。"""
    g, pa, pb = _game(real_game, THY_TEAM, {IDX: 2})
    move(g, 1, 0)                             # B0 桃花妖入战斗区（1/6）
    orb = pa.orb
    play(g, 0, YAOYAO)
    assert pa.orb == orb                      # 不消耗鬼火
    hp = pb.shikigami[0].health
    g.apply({"op": "assault", "index": 0})    # A0 桃花妖 1+2=3 战力出击
    assert pb.shikigami[0].health == hp - 3
    assert not pa.assault_boosts              # 出击后全部消耗


# ==========================================================================
# 判官（100110）（第十四阶段）
#
# 覆盖：基础能力（消灭→敌方牌手 1 伤+己方恢复 1）、墨笔夺魂/勾诀连招（降身材+
# 力量过滤消灭）、生死无常（战斗区双清）、无情（敌方气绝倒计时+1）、觉醒替换
# （消灭来源放宽至己方任意式神）、死之宣告（任意式神直接消灭）、断罪（击杀计数
# form_power_delta 快照）。夺命"变为"路径由机制同构测试覆盖
# （tests/test_combat.py::test_destroy_on_combat_damage_transformed）。
# 队伍固定 [判官, 白狼, 姑获鸟, 妖刀姬]（派系 ≤2），判官 0 号位。
# ==========================================================================

PG = 100110
PG_TEAM = [100110, 100101, 100106, 100123]  # 青岚+苍叶（派系 ≤2）


def test_kill_trigger_pings_enemy_player_and_heals(real_game):
    """基础能力：判官消灭一个式神 → 对敌方牌手造成 1 点伤害且你恢复 1 生命。"""
    g, pa, pb = _game(real_game, PG_TEAM)
    pa.health = 25
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99,
                        Ref(player=0, shikigami=0), kind="combat")
    g._drain_queue()
    assert pb.health == 29 and pa.health == 26


def test_negative_buff_health_then_power_le_destroy(real_game):
    """墨笔夺魂（-2力量/-1生命，非永久，上限下调同步钳当前生命）接勾诀
    （力量<=2 才可被指定）连招。"""
    g, pa, pb = _game(real_game, PG_TEAM)
    b1 = pb.shikigami[1]                      # 白狼 3/4
    with pytest.raises(IllegalAction):
        play(g, 0, 10011002, target=Ref(player=1, shikigami=1))   # 3 力量超标
    play(g, 0, 10011001, target=Ref(player=1, shikigami=1))
    assert b1.eff_power == 1 and b1.max_health == 3 and b1.health == 3
    play(g, 0, 10011002, target=Ref(player=1, shikigami=1))
    assert b1.defeated


def test_response_destroy_both_combat_zones(real_game):
    """生死无常（主动使用）：消灭己方战斗区的式神，然后消灭敌方战斗区的式神。"""
    g, pa, pb = _game(real_game, PG_TEAM, {0: 2})
    move(g, 0, 0)
    move(g, 1, 0)
    play(g, 0, 10011003)
    assert pa.shikigami[0].defeated and pb.shikigami[0].defeated
    assert pa.combat_index is None and pb.combat_index is None


def test_enemy_revive_countdown_plus(real_game):
    """无情：敌方式神进入气绝的[倒计时]+1（基础 3 → 4）。"""
    g, pa, pb = _game(real_game, PG_TEAM, {0: 2})
    play(g, 0, 10011004)
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99,
                        Ref(player=0, shikigami=1), kind="combat")
    g._drain_queue()
    assert pb.shikigami[0].revive_countdown == 4


def test_awaken_kill_trigger_any_friendly_source(real_game):
    """觉醒·判官：+1/+1 永久；进场使一个敌方式神 -2力量/-1生命；[觉醒]能力——
    己方任意式神消灭式神即触发（来源不限判官，比基础能力宽）。"""
    g, pa, pb = _game(real_game, PG_TEAM, {0: 2})
    a = pa.shikigami[IDX]
    pa.health = 25
    play(g, 0, 10011005, target=Ref(player=1, shikigami=0))
    assert (a.perm_power, a.perm_health) == (1, 1) and a.awakened == 10011005
    assert pb.shikigami[0].eff_power == 1 and pb.shikigami[0].max_health == 3
    g.deal_to_shikigami(Ref(player=1, shikigami=1), 99,
                        Ref(player=0, shikigami=1), kind="combat")   # 白狼消灭
    g._drain_queue()
    assert pb.health == 29 and pa.health == 26


def test_destroy_any_shikigami_including_friendly(real_game):
    """死之宣告：消灭一个式神（任意方——可指定己方式神）。"""
    g, pa, pb = _game(real_game, PG_TEAM, {0: 3, 1: 1})
    play(g, 0, 10011007, target=Ref(player=0, shikigami=1))
    assert pa.shikigami[1].defeated


def test_kill_count_grants_form_power_delta(real_game):
    """断罪：本局你每消灭过一个式神（己方来源）此牌 +1 力量（结附时快照 4+击杀数）。"""
    g, pa, pb = _game(real_game, PG_TEAM, {0: 3})
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 99,
                        Ref(player=0, shikigami=1), kind="combat")
    g._drain_queue()
    play(g, 0, 10011008)
    a = pa.shikigami[IDX]
    assert a.eff_power == 5 and a.max_health == 8


# ==========================================================================
# 清姬（100114）（第十四阶段）
#
# 覆盖：先天伤害转化（无破甲→等量破甲）、蛇行击（弹回+破甲加伤）、焚身之火
# （指定破甲+有破甲者全体伤害）、无名之毒（瞬发投射）、觉醒（破甲保留）、
# 火吻之蛇（敌方回合开始破甲 + 破甲降力量光环）。
# 队伍固定 [清姬, 茨木童子, 山童, 犬神]（派系 ≤2），清姬 0 号位。
# ==========================================================================

QJ = 100114
QJ_TEAM = [100114, 100103, 100116, 100115]  # 紫岩+红莲（派系 ≤2）


def test_damage_to_fragile_on_all_enemy_characters(real_game):
    """清姬伤害转化（先天 damage_to_fragile）：淬毒对无破甲角色不扣血、改为等量
    破甲；蛇行击命中有破甲者按破甲加伤（破甲受伤即消耗），使用后弹回回手。"""
    g, pa, pb = _game(real_game, QJ_TEAM)
    b0 = pb.shikigami[0]                      # 清姬 4/4
    play(g, 0, 10011402)                      # 淬毒：敌方全体 2 伤 → 全转 2 破甲
    assert b0.health == 4 and b0.shield == -2
    assert pb.health == 30 and pb.shield == -2
    play(g, 0, 10011401, target=Ref(player=1, shikigami=0))  # 蛇行击
    assert b0.defeated and b0.shield == 0     # 4 - (2+2)，破甲消耗
    assert any(c.id == 10011401 for c in pa.hand)            # 弹回回手


def test_grant_fragile_then_aoe_has_fragile_filter(real_game):
    """焚身之火：使一个角色获得 2 破甲，然后对所有有破甲的敌方角色造成 3 点伤害
    （无破甲者不受影响；刚被赋予破甲的选择目标被命中）。"""
    g, pa, pb = _game(real_game, QJ_TEAM, {0: 3})
    b1 = pb.shikigami[1]                      # 茨木童子 3/4
    play(g, 0, 10011406, target=Ref(player=1, shikigami=1))
    assert b1.defeated and b1.shield == 0     # 4 - (3+2)，破甲消耗
    assert pb.health == 30 and pb.shikigami[0].health == 4


def test_fast_projectile_converts_to_fragile(real_game):
    """无名之毒：[瞬发]投射 4（战斗区为空打敌方牌手；牌手无破甲 → 伤害转化
    为等量破甲，不扣生命）。"""
    g, pa, pb = _game(real_game, QJ_TEAM, {0: 2})
    orb = pa.orb
    play(g, 0, 10011405)
    assert pb.health == 30 and pb.shield == -4
    assert pa.orb == orb                      # 瞬发首张免费


def test_keep_enemy_fragile_skips_turn_start_clear(real_game):
    """觉醒·清姬：+3/+3 永久；所有敌方角色获得 1 破甲；在场已觉醒期间
    敌方角色的破甲在回合开始不清除（keep_enemy_fragile）。"""
    g, pa, pb = _game(real_game, QJ_TEAM, {0: 3})
    a = pa.shikigami[IDX]
    play(g, 0, 10011407)
    assert (a.perm_power, a.perm_health) == (3, 3) and a.awakened == 10011407
    assert pb.shikigami[0].shield == -1 and pb.shield == -1
    pass_turns(g, 1)                          # B 回合开始：破甲保留
    assert pb.shikigami[0].shield == -1 and pb.shield == -1


def test_enemy_fragile_power_aura_and_halfturn_reset(real_game):
    """火吻之蛇：敌方回合开始时使所有敌方角色获得 1 破甲（回合开始的破甲清除
    先于触发，故每半回合重置为 -1）；敌方有破甲的式神降低等于其破甲的力量。"""
    g, pa, pb = _game(real_game, QJ_TEAM, {0: 3})
    b0 = pb.shikigami[0]                      # 清姬 4/4
    b0.shield = -2
    play(g, 0, 10011408)
    assert b0.eff_power == 2                  # 4 - 2 破甲
    pass_turns(g, 1)                          # B 回合开始：清破甲后全体 +1 破甲
    assert b0.shield == -1 and b0.eff_power == 3
    assert pb.shikigami[1].shield == -1 and pb.shield == -1


# ==========================================================================
# 书翁（100118）（第十四阶段）
#
# 覆盖：基础能力（起始手牌+1）、开卷/墨染（抽牌+手牌半数伤害）、纪行（伤害牌手抽牌）、
# 明心（回合抽牌改检视三选一）、万象之书（其他己方式神各一张）、觉醒（空库燃烧替换）。
# 队伍固定 [书翁, 白狼, 姑获鸟, 妖刀姬]（派系 ≤2），书翁 0 号位。
# ==========================================================================

SW = 100118
SW_TEAM = [100118, 100101, 100106, 100123]  # 青岚+苍叶（派系 ≤2）


def test_game_start_draw_extra_card(real_game):
    """基础能力（起始手牌数量+1）：游戏开始时抽一张牌——先手 7 张、后手 6 张。"""
    g = real_game(SW_TEAM)
    pa, pb = g.state.players
    assert len(pa.hand) == 7 and len(pb.hand) == 6


def test_draw_two_and_hand_count_half_damage(real_game):
    """开卷抽两张牌；墨染先抽 1 再按当前手牌数一半（向下取整）造成伤害。"""
    g, pa, pb = _game(real_game, SW_TEAM, {0: 2})
    play(g, 0, 10011803)                      # 开卷：7 → 8-1+2 = 9
    assert len(pa.hand) == 9
    b0 = pb.shikigami[0]                      # 书翁 1/5
    play(g, 0, 10011804, target=Ref(player=1, shikigami=0))  # 9+1=10 → 5 伤
    assert len(pa.hand) == 10 and b0.defeated


def test_draw_when_dealing_player_damage(real_game):
    """纪行（[迅捷]形态 2/5）：当书翁对敌方牌手造成伤害时抽一张牌。"""
    g, pa, pb = _game(real_game, SW_TEAM)
    play(g, 0, 10011801)
    hand = len(pa.hand)
    g.apply({"op": "assault", "index": 0})    # 迅捷出击，空战斗区打牌手
    assert pb.health == 28
    assert len(pa.hand) == hand + 1


def test_generate_each_friendly_other_shikigami(real_game):
    """万象之书：[瞬发]随机将其他己方式神的各一张牌置入手牌。"""
    g, pa, pb = _game(real_game, SW_TEAM, {0: 3})
    hand0 = {c.uid for c in pa.hand}
    play(g, 0, 10011807)
    new = [c for c in pa.hand if c.uid not in hand0]
    assert len(new) == 3
    assert {c.id // 100 for c in new} == {100101, 100106, 100123}


def test_turn_draw_replaced_by_deck_top_pick(real_game):
    """明心：回合开始的抽牌改为检视牌库顶三张牌选一张置入手牌。"""
    g, pa, pb = _game(real_game, SW_TEAM, {0: 2})
    play(g, 0, 10011805)
    hand = len(pa.hand)
    pass_turns(g, 2)
    pend = g.state.pending_choice
    assert pend and pend["kind"] == "deck_top_pick" and len(pend["options"]) == 3
    g.apply({"op": "choose", "uid": pend["options"][0], "player": 0})
    assert len(pa.hand) == hand + 1


def test_deck_out_burn_instead_of_loss(real_game):
    """觉醒·书翁：+2/+2 永久；牌库为空时抽牌改为对敌方牌手造成 10 点伤害，
    自己不因此落败。"""
    g, pa, pb = _game(real_game, SW_TEAM, {0: 3})
    a = pa.shikigami[IDX]
    play(g, 0, 10011808)
    assert (a.perm_power, a.perm_health) == (2, 2) and a.awakened == 10011808
    pa.deck.clear()
    pass_turns(g, 2)
    assert pb.health == 20 and g.state.winner is None


# ==========================================================================
# 萤草（100127）卡牌（第十四阶段；基础能力测试见前段）
#
# 覆盖：吸取（选目标伤害+鼓舞）、治愈之光/勇气之光/安魂之光（进场+回合开始循环）、
# 萤火点点（双择+有形态增强）、闪烁（本回合力量覆写+条件瞬发）、觉醒（形态进场
# 效果再触发）、虹彩（三形态置入手牌）。测试形态 A/B 为 gdb 覆盖的衍生号段卡。
# ==========================================================================

def test_choose_target_damage_with_boost_shield(real_game):
    """吸取：使用时主动选择目标造成 2 点伤害（维护者答复(4)）+ [鼓舞] 获得 2 护甲。"""
    g, pa, pb = _game(real_game, YC_TEAM)
    play(g, 0, 10012701, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 3         # 萤草 5→3
    assert pb.health == 30                     # 不再走投射打玩家
    assert pa.assault_boosts == [{"power": 0, "shield": 2}]


def test_form_enter_turn_start_heal_all_shikigami(real_game):
    """治愈之光：[瞬发]进场与己方回合开始时为己方所有式神恢复 2 点生命。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 1, 1: 1})
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 3, None)   # 白狼 4→1
    orb = pa.orb
    play(g, 0, 10012702)
    assert pa.orb == orb                       # 瞬发首张免费
    assert pa.shikigami[1].health == 3         # 进场 +2
    pass_turns(g, 2)
    assert pa.shikigami[1].health == 4         # 己方回合开始再 +2（封顶 4）


def test_dual_play_methods_and_turn_start_enhance(real_game):
    """萤火点点：双择（己方式神+1生命 / 敌方式神 1 伤害）；[增强]己方回合开始时
    若萤草上有形态，此牌效果+1。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 1, 1: 1})
    b0 = pb.shikigami[0]                      # 萤草 2/5
    c = give(g, 0, 10012703)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "damage",
             "target": Ref(player=1, shikigami=0)})
    assert b0.health == 4                     # 基础 1 伤
    play(g, 0, YC_FORM_A)                     # 结附测试形态
    pass_turns(g, 2)                          # 己方回合开始：有形态 → enhance+1
    assert pa.card_mods[10012703]["enhance"] == 1
    c = give(g, 0, 10012703)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "heal",
             "target": Ref(player=0, shikigami=1)})
    s1 = pa.shikigami[1]                      # 白狼 4/4
    assert s1.max_health == 6 and s1.health == 6   # +1生命 + enhance 1 = +2


def test_form_basic_boost_power_and_shield(real_game):
    """勇气之光：[瞬发]进场与己方回合开始 [鼓舞]+1战力/+2护甲。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 2})
    play(g, 0, 10012704)
    assert pa.assault_boosts == [{"power": 1, "shield": 2}]
    pass_turns(g, 2)
    assert pa.assault_boosts == [{"power": 1, "shield": 2}] * 2


def test_power_zero_turn_via_response(real_game):
    """闪烁（主动使用）：敌方战斗区的式神本回合力量变为 0（任一回合开始解除）；
    己方战斗区无人时无[瞬发]、正常收费。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 2})
    move(g, 1, 0)
    b0 = pb.shikigami[0]                      # 萤草 2/5
    orb = pa.orb
    play(g, 0, 10012705)
    assert pa.orb == orb - 1                  # 己方战斗区无人：条件瞬发不生效
    assert b0.eff_power == 0
    pass_turns(g, 1)                          # B 回合开始：覆写解除
    assert b0.eff_power == 2


def test_awaken_retriggers_form_enter_on_form_play(real_game):
    """觉醒·萤草：+1/+1 永久；进场触发当前形态的进场效果；[觉醒]当萤草使用形态牌时
    触发其进场效果并抽一张牌。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 2})
    s = pa.shikigami[IDX]
    play(g, 0, YC_FORM_B)                     # 结附测试形态 B：进场 +2 护甲
    assert s.shield == 2
    play(g, 0, 10012706)                      # 觉醒进场：形态 B 进场效果再触发
    assert s.shield == 4
    assert (s.perm_power, s.perm_health) == (1, 1) and s.awakened == 10012706
    hand = len(pa.hand)
    play(g, 0, YC_FORM_A)                     # 换形态：触发进场（空白）+ 抽 1
    assert len(pa.hand) == hand + 1


def test_form_gain_orb_and_generate_three_forms(real_game):
    """安魂之光：[瞬发]进场获得 1 鬼火并为牌手恢复 2；虹彩：三种形态牌置入手牌。"""
    g, pa, pb = _game(real_game, YC_TEAM, {0: 3})
    pa.health = 25
    orb = pa.orb
    play(g, 0, 10012707)                      # 瞬发首张免费 + 1 鬼火
    assert pa.orb == orb + 1 and pa.health == 27
    play(g, 0, 10012708)                      # 瞬发名额已用，1 火
    assert pa.orb == orb
    ids = {c.id for c in pa.hand}
    assert {10012702, 10012704, 10012707} <= ids
