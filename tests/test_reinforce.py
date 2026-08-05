"""协战机制（reinforce）与风之乐章/致命之羽数据测试：真实 db YAML 端到端（阶段 C）。

覆盖：构筑归属（协战牌计入所属式神 8 张、同名限 2、双归属任一出战可编、均未出战拒绝）、
打出流程（choice 选择子选项、费用/等级/目标按子卡、生成 token 视作从手牌使用走完整
使用事件流程、主牌离手进 exiled 不进墓地、非法选项/未出战/气绝归属拒绝）、
各子卡效果（幻音绝弦延迟倒计时与气绝倒计时-2 立即复活、风韵雅乐 history 重放+获得
觉醒牌、鎏金幻羽手牌修饰与不可叠加+修饰三读取点、蚀刃毒羽条件破甲翻倍+羁绊、
灵矢贯虹鼓舞消耗转化）。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from db.deck import validate_deck
from tests import factories as F
from tests.factories import give, move, pass_turns, play

FYZ = 10012421    # 风之乐章
HYJX = 10012451   # 幻音绝弦（妖琴师侧子卡）
FYYL = 10012551   # 风韵雅乐（一目连侧子卡）
ZMZY = 10012621   # 致命之羽
LJHY = 10012652   # 鎏金幻羽（以津真天侧子卡）
SBDY = 10012851   # 蚀刃毒羽（鸩侧子卡）
LSGH = 10010151   # 灵矢贯虹（白狼侧子卡）
FEATHER = 10012651  # 黄金羽 token
JLFY = 10012605   # 金风流羽

TEAM = [100124, 100125, 100126, 100128]        # 妖琴师/一目连/以津真天/鸩（全苍叶）
TEAM_WOLF = [100101, 100102, 100123, 100104]   # 白狼/兵俑/妖刀姬/大天狗

YQS, YML, YJZT, ZHEN = 0, 1, 2, 3              # TEAM 内序号


@pytest.fixture
def make_game(real_game):
    def _make(seed: int = 1, team=None, **kw):
        return real_game(team or TEAM, seed=seed, **kw)

    return _make


def _game(make_game, levels: dict[int, int] | None = None, team=None):
    g = make_game(team=team)
    pa, pb = F.battle_setup(g, levels or {0: 2})
    return g, pa, pb


def _play_reinforce(g, player: int, main_id: int, choice: int, target: Ref | None = None):
    """发一张协战主牌到手牌并以 choice 子选项打出。"""
    card = give(g, player, main_id)
    cmd = {"op": "play_card", "uid": card.uid, "choice": choice}
    if target is not None:
        cmd["target"] = target
    g.apply(cmd)


# ---------- 构筑归属 ----------

def test_deck_reinforce_counts_toward_owner(gdb):
    """协战牌计入所属式神 8 张（挂到种类数较少的在队所属式神名下）：风之乐章×2 补足
    妖琴师 6 张、致命之羽×2 补足以津真天 6 张——整组 32 张合法。"""
    cards = ([10012401, 10012402, 10012403] * 2 + [FYZ, FYZ]
             + [10012501, 10012502, 10012503, 10012504] * 2
             + [10012601, 10012602, 10012603] * 2 + [ZMZY, ZMZY]
             + [10012801, 10012802, 10012803, 10012804] * 2)
    assert validate_deck(gdb, TEAM, cards) == []


def test_deck_reinforce_single_owner_and_limit(gdb):
    """双归属任一出战即可编入（队无一目连时风之乐章仍合法）；同名限 2。"""
    team = [100124, 100126, 100128, 100101]
    cards = ([10012401, 10012402, 10012403] * 2 + [FYZ, FYZ]
             + [10012601, 10012602, 10012603, 10012604] * 2
             + [10012801, 10012802, 10012803, 10012804] * 2
             + [10010101, 10010102, 10010103, 10010104] * 2)
    assert validate_deck(gdb, team, cards) == []
    over = ([10012401, 10012402] * 2 + [FYZ, FYZ, FYZ] + [10012403]
            + [10012601, 10012602, 10012603, 10012604] * 2
            + [10012801, 10012802, 10012803, 10012804] * 2
            + [10010101, 10010102, 10010103, 10010104] * 2)
    errors = validate_deck(gdb, team, over)
    assert any("风之乐章" in e and "限 2" in e for e in errors)


def test_deck_reinforce_no_owner_rejected(gdb):
    """两位所属式神均未出战：不可编入。"""
    cards = ([10010101, 10010102, 10010103, 10010104] * 2
             + [10010201, 10010202, 10010203, 10010204] * 2
             + [10012301, 10012302, 10012303, 10012304] * 2
             + [10010401, 10010402, 10010403] * 2 + [FYZ, FYZ])
    errors = validate_deck(gdb, TEAM_WOLF, cards)
    assert any("均未出战" in e for e in errors)


# ---------- 打出流程 ----------

def test_play_choice_full_flow_and_main_exiled(make_game):
    """选择子选项：费用按子卡（1 火）、生成 token 视作从手牌使用（效果完整结算）、
    主牌离手进 exiled（不进墓地）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1})
    hand_before = len(pa.hand)
    _play_reinforce(g, 0, FYZ, 0)             # 风之乐章 → 幻音绝弦
    assert pa.orb == 8                        # 子选项正常 1 火
    assert not any(c.id == FYZ for c in pa.hand)
    assert not any(c.id == FYZ for c in pa.graveyard)     # 主牌不入墓地
    assert any(c.id == FYZ for c in pa.zones["exiled"])  # 离手放逐
    assert not any(c.id == HYJX for c in pa.hand)         # token 已使用离手
    assert any(c.id == HYJX for c in pa.graveyard)
    assert len(pa.shikigami[YQS].delayed) == 1            # 延迟能力已登记
    forms = {10012501, 10012502, 10012503, 10012504, 10012507, 10012508}
    assert any(c.id in forms for c in pa.hand)            # 羁绊：一目连形态牌入手
    assert len(pa.hand) == hand_before + 1  # give 主牌+生成 token+打出=抵消，羁绊 +1


def test_bond_gated_by_shikigami_active(make_game, gdb):
    """羁绊触发条件（维护者确认）：使用此牌时对应式神在场（等级 ≥1 且未气绝）。
    幻音绝弦（一目连 0 级/气绝不生成形态牌）、风韵雅乐（妖琴师气绝不生成觉醒牌）、
    涅槃业火（青行灯不在队不生成明灯；在场则生成）。"""
    forms = {10012501, 10012502, 10012503, 10012504, 10012507, 10012508}

    def _form_count(pa):
        return sum(1 for c in pa.hand if c.id in forms)

    g, pa, pb = _game(make_game)                    # {0: 2}：一目连 0 级
    before = _form_count(pa)
    _play_reinforce(g, 0, FYZ, 0)
    assert _form_count(pa) == before
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1})
    pa.shikigami[YML].health = 0
    g.check_defeated(Ref(player=0, shikigami=YML))  # 一目连气绝
    before = _form_count(pa)
    _play_reinforce(g, 0, FYZ, 0)
    assert _form_count(pa) == before
    # 妖琴师气绝：风韵雅乐不生成觉醒牌
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 2})
    pa.shikigami[YQS].health = 0
    g.check_defeated(Ref(player=0, shikigami=YQS))
    awakens = {10012401, 10012406, 10012407}
    before = sum(1 for c in pa.hand if c.id in awakens)   # 起手可能已含可构筑觉醒牌
    _play_reinforce(g, 0, FYZ, 1)
    assert sum(1 for c in pa.hand if c.id in awakens) == before
    # 青行灯不在队：涅槃业火不生成明灯（回响测试队伍不含青行灯，见下）
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1, 2: 1}, team=NPYH_TEAM)
    play(g, 0, NPYH)
    assert not any(c.id == MD for c in pa.hand)
    # 青行灯在队且在场：明灯生成（无可构筑卡，跳过卡组校验；避开明灯 id 混入起手）
    from core.setup import new_game
    team = [100105, 100116, 100101, 100112]
    deck = F.deck_of(100105, 100116, 100101, 100116)
    g = new_game(gdb, ("A", list(team), deck), ("B", list(team), deck),
                 seed=1, first=0, shuffle_team=False, mulligan=False, check_deck=False,
                 config=F.GameConfig(auto_skip_upgrade=True))
    pa, pb = F.battle_setup(g, {0: 2, 3: 1})
    play(g, 0, NPYH)
    assert any(c.id == MD for c in pa.hand)


def test_play_invalid_choice_rejected(make_game):
    """缺 choice / 非法 choice：拒绝且主牌留在手中。"""
    g, pa, pb = _game(make_game)
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": give(g, 0, FYZ).uid})   # 缺 choice
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, FYZ, 5)                              # 非法 choice
    assert sum(1 for c in pa.hand if c.id == FYZ) == 2    # 两次尝试的主牌都在手


def test_play_level_checked_by_sub(make_game):
    """等级检测按子选项：风韵雅乐需要一目连 2 级（1 级拒绝），幻音绝弦看妖琴师。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1})
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, FYZ, 1)         # 一目连仅 1 级：副侧子卡不可用
    _play_reinforce(g, 0, FYZ, 0)             # 妖琴师 2 级：主侧子卡可用
    assert any(c.id == FYZ for c in pa.zones["exiled"])


def test_play_owner_defeated_rejects_only_that_side(make_game):
    """子选项所属式神气绝：仅该侧不可用；另一侧（一目连）照常。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 2})
    g.deal_to_shikigami(Ref(player=0, shikigami=YQS), 99, None)   # 妖琴师气绝
    g._drain_queue()
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, FYZ, 0)
    _play_reinforce(g, 0, FYZ, 1)             # 一目连侧正常
    assert any(c.id == FYZ for c in pa.zones["exiled"])


def test_play_no_owner_deployed_rejected(make_game):
    """两位所属式神均未出战：拒绝（等级/费用检查之前）。"""
    g, pa, pb = _game(make_game, team=TEAM_WOLF)
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, ZMZY, 0)


# ---------- 幻音绝弦：延迟倒计时 / 气绝倒计时 ----------

def test_delay_grant_countdown_and_revive(make_game):
    """下一个己方回合开始：己方式神倒计时 -1（妖琴师 1→0 归零治疗）；已气绝者改为
    气绝倒计时 -2（一目连 2→0 立即复活）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1})
    pa.health = 20
    g.deal_to_shikigami(Ref(player=0, shikigami=YML), 99, None)  # 一目连气绝（3 回合复活）
    g._drain_queue()
    assert pa.shikigami[YML].revive_countdown == 3
    _play_reinforce(g, 0, FYZ, 0)
    pass_turns(g, 2)                          # 到 A 下个回合开始触发
    yqs = pa.shikigami[YQS]
    assert pa.health == 23        # 妖琴师：回合批次 2→1、延迟 -1 → 0 归零治疗并重置
    assert yqs.countdown == 3
    assert pa.ext["countdown_history"] == [100124]
    yml = pa.shikigami[YML]
    assert not yml.defeated       # 气绝倒计时：批次 3→2、延迟 -2 → 0 立即复活
    assert yml.health == yml.max_health
    assert not yqs.delayed        # 一次性：触发即消耗


# ---------- 风韵雅乐：重放 + 获得觉醒牌 ----------

def test_replay_countdown_history(make_game):
    """触发本局生效过的一目连倒计时（风符·破投射 3）+ 随机获得一张妖琴师觉醒牌。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 2})
    play(g, 0, 10012501)                      # 一目连结附风符·破（倒计时 2）
    pass_turns(g, 4)                          # A 第 3 回合开始：妖琴师基础（治疗）与
    assert pb.health == 27                    # 风符·破（投射 3 → 敌方牌手）同批归零
    assert pa.ext["countdown_history"] == [100124, 10012501]
    pa.orb = 9
    log_before = len(g.state.log)
    _play_reinforce(g, 0, FYZ, 1)             # 风韵雅乐（战斗牌：一目连出击）
    assert pb.health == 21                    # 重放投射 3（→24）+ 一目连 3 攻（→21）
    awakens = {10012401, 10012406, 10012407}
    assert any(c.id in awakens for c in pa.hand)              # 羁绊：妖琴师觉醒牌入手
    assert any("重放" in m for m in g.state.log[log_before:])


# ---------- 鎏金幻羽：手牌修饰 ----------

def test_mod_hand_tag_token_filter(make_game):
    """修饰手牌真黄金羽（金风流羽不修饰）：气绝时可用/伤害+1/复活倒计时-1；
    羁绊：鸩倒计时 -2（立即归零给破甲）。不可叠加。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    g._register_ability_countdown(0, ZHEN)    # 鸩静态倒计时 2
    f1, f2 = give(g, 0, FEATHER), give(g, 0, FEATHER)
    jinfeng = give(g, 0, JLFY)
    _play_reinforce(g, 0, ZMZY, 0)            # 鎏金幻羽（0 火）
    assert pa.orb == 9
    for f in (f1, f2):
        assert f.mods["gilded"] and f.mods["playable_when_defeated"]
        assert f.mods["damage_boost"] == 1 and f.mods["revive_haste"] == [100126, 100128]
    assert not jinfeng.mods                   # 金风流羽不被修饰（维护者答复 8）
    assert pb.shield == -2                    # 鸩 2-2 归零：敌方牌手 2 破甲
    assert pa.shikigami[ZHEN].countdown == 2  # 归零后循环重置
    _play_reinforce(g, 0, ZMZY, 0)            # 第二张鎏金幻羽：不可叠加
    assert f1.mods["damage_boost"] == 1


def test_mod_hand_read_points(make_game):
    """修饰后的黄金羽：伤害+1（3 伤）；以津真天气绝时可用；使用后双方气绝倒计时 -1。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    f1, f2 = give(g, 0, FEATHER), give(g, 0, FEATHER)
    _play_reinforce(g, 0, ZMZY, 0)
    g.deal_to_shikigami(Ref(player=0, shikigami=ZHEN), 99, None)   # 鸩气绝（3）
    g.deal_to_shikigami(Ref(player=0, shikigami=YJZT), 99, None)   # 以津真天气绝（3）
    g._drain_queue()
    g.apply({"op": "play_card", "uid": f1.uid})   # 气绝时可用（修饰）；伤害+1
    assert pb.health == 27                        # 2 + 1 = 3 伤
    assert pa.shikigami[ZHEN].revive_countdown == 2
    assert pa.shikigami[YJZT].revive_countdown == 2
    g.apply({"op": "play_card", "uid": f2.uid})
    assert pa.shikigami[ZHEN].revive_countdown == 1
    assert pa.shikigami[YJZT].revive_countdown == 1


def test_playable_when_defeated_gates_methods(make_game):
    """维护者答复(11)联动：已觉醒的以津真天气绝后，经鎏金幻羽修饰的黄金羽只能打
    敌方牌手（气绝时觉醒能力不在场，snipe 使用方式门控拒绝、无需选择目标）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    play(g, 0, 10012603)                      # 觉醒·以津真天
    f1 = give(g, 0, FEATHER)
    _play_reinforce(g, 0, ZMZY, 0)            # 鎏金幻羽修饰（气绝时可用）
    g.deal_to_shikigami(Ref(player=0, shikigami=YJZT), 99, None)
    g._drain_queue()
    s = pa.shikigami[YJZT]
    assert s.defeated and s.awakened          # 觉醒标记跨气绝保留，但能力不在场
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": f1.uid, "play_method": "snipe",
                 "target": Ref(player=1, shikigami=YML)})
    g.apply({"op": "play_card", "uid": f1.uid})   # 基础效果：无需选择目标打敌方牌手
    assert pb.health == 27                    # 2 + 1（修饰伤害+1）


# ---------- 蚀刃毒羽：条件破甲翻倍 + 羁绊 ----------

def test_fragile_echo_grants_equal_amount(make_game):
    """攻击有破甲的角色：攻击后使其获得相同数量的破甲；羁绊：以津真天倒计时 -2
    （立即归零：黄金羽入手）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    g._register_ability_countdown(0, YJZT)    # 以津真天静态倒计时 2
    g._change_shield(Ref(player=1, shikigami=YML), 1, "test", kind="fragile")
    move(g, 1, YML)                           # B 一目连（2/6）持 1 破甲入战斗区
    _play_reinforce(g, 0, ZMZY, 1)            # 蚀刃毒羽：鸩 2+2=4 攻 +1 破甲 = 5 伤
    yml_b = pb.shikigami[YML]
    assert yml_b.health == 1                  # 6 - 5
    assert yml_b.shield == -1                 # 原 1 破甲被伤害消耗，攻击后再获得相同数量（1）
    assert any(c.id == FEATHER for c in pa.hand)   # 以津真天 2-2 归零：黄金羽入手
    assert pa.shikigami[YJZT].countdown == 2  # 归零后循环重置
    zhen = pa.shikigami[ZHEN]
    assert zhen.health == 5 and zhen.shield == 0   # +2 护甲吃反击 2


def test_fragile_echo_requires_fragile(make_game):
    """被攻击者无破甲：不触发翻倍（正常战斗）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    move(g, 1, YML)                           # B 一目连无破甲
    _play_reinforce(g, 0, ZMZY, 1)
    assert pb.shikigami[YML].health == 2      # 4 伤
    assert pb.shikigami[YML].shield == 0


# ---------- 灵矢贯虹：鼓舞消耗转化 ----------

def test_consume_assault_boosts_as_combat_bonus(make_game):
    """羁绊 2：己方全部鼓舞（战力/护甲）作为此战斗牌加成赋予白狼并消耗。"""
    g, pa, pb = _game(make_game, levels={0: 2}, team=TEAM_WOLF)
    pa.assault_boosts.append({"power": 1, "shield": 1})
    pa.assault_boosts.append({"power": 2, "shield": 0})
    play(g, 0, LSGH)                          # 白狼 3+2+3=8 攻 → 敌方牌手（空战斗区）
    assert pb.health == 22
    assert pa.assault_boosts == []            # 鼓舞被消耗
    wolf = pa.shikigami[0]
    assert wolf.shield == 3                   # +2（牌）+1（鼓舞）护甲
    assert wolf.combat_power == 0             # 战力已在战斗后清除


# ==========================================================================
# 灵矢贯虹：法术强化镜像 + 羁绊 1（原 test_yingcao.py 灵矢贯虹部分）
#
# 队伍固定 [萤草, 白狼, 兵俑, 妖刀姬]（萤草 0 号位 1 级、白狼 1 号位）。
# 萤草基础能力测试在同区合并的 test_data.py；两处各持一份相同的 gdb 覆盖。
# ==========================================================================

YC = 100127       # 萤草（双方 0 号位）
YC_IDX, WOLF_IDX = 0, 1
YC_TEAM = [100127, 100101, 100102, 100123]
QIGONG = 10010101  # 起弓（[远程] 强化）
LI = 10010102      # 离（+3 力量）
WUWO = 10010108    # 无我（+3 力量）
YC_FORM_A, YC_FORM_B = 10012752, 10012753  # 测试库注册的萤草形态牌（衍生号段）


def _yc_form(cid: int, name: str, steps=()):
    from db.schema import CardDef, EffectBlock
    return CardDef(id=cid, version=20260728, name=name, shikigami=YC,
                   card_type="form", rarity="R", level=1, cost=1,
                   form_power=2, form_health=3,
                   effects=EffectBlock(steps=list(steps)), text="")


@pytest.fixture
def gdb():
    """真实 db + 测试库临时注册：萤草测试形态牌 A（空白进场）/B（进场 +2 护甲，
    衍生号段 52/53——萤草 01-08 已于第十四阶段补齐真卡）。

    覆盖链：本文件 gdb 覆盖 conftest gdb → real_game(gdb) → make_game(real_game)，
    灵矢贯虹羁绊 1 测试需要萤草形态牌；只新增卡牌定义，不影响本文件其他测试。"""
    from db.loader import CardDatabase
    from db.schema import CardDef, EffectBlock, Step, TargetSpec
    db = CardDatabase.load()
    db.cards[YC_FORM_A] = _yc_form(YC_FORM_A, "测试形态·花")
    db.cards[YC_FORM_B] = _yc_form(YC_FORM_B, "测试形态·叶", steps=[
        Step(op="gain_shield", amount=2, target=TargetSpec(kind="self"))])
    # 姑获鸟（卡牌未设计，10010601-04 全空白）与青行灯（仅明灯 01 为真卡，
    # 10011202-04 空白）补足 01-04：刃影叠岚/涅槃业火节的队伍需要
    for sid, nums in ((100106, (1, 2, 3, 4)), (100112, (2, 3, 4))):
        for n in nums:
            cid = sid * 100 + n
            db.cards[cid] = CardDef(id=cid, version=20260729,
                                    name=f"{db.shikigami[sid].name}空白卡{n}",
                                    shikigami=sid, card_type="spell", level=1, cost=1,
                                    effects=EffectBlock(), text="")
    return db


def test_reapply_attack_buff_power_only_power(make_game):
    """离（+3）与无我（+3）挂账中：灵矢贯虹使白狼再次临时获得合计 6 力量
    （仅力量部分；attack_buffs 挂账 [3, 3] + 镜像 6），本次攻击一并生效。"""
    g, pa, pb = _game(make_game, levels={YC_IDX: 1, WOLF_IDX: 3}, team=YC_TEAM)
    play(g, 0, LI)                            # 离：+3 力量（瞬发免费）
    play(g, 0, WUWO)                          # 无我：+3 力量（瞬发名额已用，1 火）
    wolf = pa.shikigami[WOLF_IDX]
    assert [e["power"] for e in wolf.attack_buffs] == [3, 3]
    play(g, 0, LSGH)                          # 灵矢贯虹：+2/+2 + 镜像 +6 → 攻 3+6+2+6=17
    assert pb.health == 13                    # 敌方空战斗区：17 攻打牌手
    assert wolf.attack_buffs == []            # 攻击后到期强化（含镜像）战斗后核销


def test_trigger_form_enter_replays_effect(make_game):
    """羁绊 1：攻击前触发萤草当前形态进场效果（形态 B 进场 +2 护甲再执行一次）。"""
    g, pa, pb = _game(make_game, levels={YC_IDX: 1, WOLF_IDX: 2}, team=YC_TEAM)
    play(g, 0, YC_FORM_B)                     # 结附形态 B：进场 +2 护甲
    assert pa.shikigami[YC_IDX].shield == 2
    play(g, 0, LSGH)
    assert pa.shikigami[YC_IDX].shield == 4   # 羁绊 1：进场效果再触发 +2


def test_trigger_form_enter_no_form_noop(make_game):
    """萤草未结附形态（当前正式数据永远如此）：羁绊 1 空操作，战斗照常。"""
    g, pa, pb = _game(make_game, levels={YC_IDX: 1, WOLF_IDX: 2}, team=YC_TEAM)
    play(g, 0, LSGH)                          # 白狼 3+2=5 攻打牌手
    assert pb.health == 25
    assert pa.shikigami[YC_IDX].form is None


# ==========================================================================
# 涅槃业火（10010551，协战子卡 token；主牌"烛火重燃"未加入，直接发牌测试）
#
# 法术回响：本回合其他式神（含敌方）从手牌使用法术时（同式神法术至多一次），
# 凤凰火按序列凭空免费使用 凤鸣→引燃→瑞翔（每张至多一次，once_key 不可叠加）；
# 回响自动使用照常 emit on_card_played（触发凤凰火基础投射）但不自连锁。
# 队伍 [凤凰火, 山童, 青行灯, 妖刀姬]；凤凰火 2 级（涅槃业火 2 级牌）。
# ==========================================================================

NPYH = 10010551      # 涅槃业火
NH = 10011603        # 怒吼（山童法术，回响触发用）
QG = 10010101        # 起弓（白狼法术，回响触发用）
MD = 10011201        # 明灯（涅槃业火羁绊产物；需青行灯在场才生成，不在队不可用）
FM_E, YR_E = 10010501, 10010503   # 回响序列前两张：凤鸣/引燃（第三张瑞翔 10010502）

# 红莲×2 + 苍叶×2（构筑派系 ≤2；触发牌须来自队内式神，青行灯无法入队故用起弓）
NPYH_TEAM = [100105, 100116, 100101, 100123]


def _echo(pa):
    return pa.shikigami[0].ext.get("spell_echo")


def test_spell_echo_sequence_single_trigger(make_game):
    """回响序列：怒吼触发凤鸣（墓地次序可验证）、同式神法术不重复触发、
    起弓触发引燃；自动使用的回响牌触发凤凰火基础投射。"""
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1, 2: 1}, team=NPYH_TEAM)
    play(g, 0, NPYH)
    assert pb.health == 29                    # 涅槃业火本身触发基础投射 1
    assert not any(c.id == MD for c in pa.hand)  # 青行灯不在队：羁绊不触发
    assert _echo(pa)["cursor"] == 0
    play(g, 0, NH)                            # 山童怒吼 → 回响凤鸣
    assert [c.id for c in pa.graveyard] == [NPYH, NH, FM_E]
    assert pb.health == 26                    # 凤鸣 2 + 基础投射 1（默认环境 20200227）
    assert _echo(pa)["cursor"] == 1           # 自动使用不自连锁（只推进一次）
    play(g, 0, NH)                            # 同式神法术：不重复触发
    assert [c.id for c in pa.graveyard] == [NPYH, NH, FM_E, NH]
    assert pb.health == 26
    assert _echo(pa)["cursor"] == 1
    play(g, 0, QG)                            # 白狼起弓 → 回响引燃
    assert [c.id for c in pa.graveyard] == [NPYH, NH, FM_E, NH, QG, YR_E]
    assert _echo(pa)["cursor"] == 2
    assert pb.health == 25                    # 引燃随机打式神（打不死），基础投射 1 必中


   # 羁绊触发：明灯入手


def test_spell_echo_enemy_spell_triggers(make_game):
    """敌方式神在敌方回合从手牌使用法术同样触发（回响存活到己方下回合开始）。"""
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1, 2: 1}, team=NPYH_TEAM)
    play(g, 0, NPYH)
    play(g, 0, NH)                            # A 怒吼 → 回响凤鸣（cursor 1）
    pass_turns(g, 1)                          # B 回合（回响仍在）
    play(g, 1, QG)                            # B 白狼起弓 → A 凤凰火回响引燃
    assert _echo(pa)["cursor"] == 2
    assert any(c.id == YR_E for c in pa.graveyard)
    # 引燃随机打式神（全员 ≥3 血打不死）；回响牌均触发基础投射（必中牌手）
    assert pb.health == 30 - 1 - 2 - 1 - 1    # 涅槃投射 + 凤鸣 + 两次投射


def test_spell_echo_once_key_not_stackable(make_game):
    """不可叠加：已登记同键回响时第二次涅槃业火不重置序列（游标/已触发保留）。"""
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1, 2: 1}, team=NPYH_TEAM)
    play(g, 0, NPYH)
    play(g, 0, NH)                            # 推进回响：cursor 1、triggered [100116]
    play(g, 0, NPYH)                          # 第二次：once_key 命中 → 跳过登记
    assert _echo(pa)["cursor"] == 1
    assert _echo(pa)["triggered"] == [100116]
    pass_turns(g, 2)                          # 己方回合开始：回响清除
    assert _echo(pa) is None


# ==========================================================================
# 刃影叠岚（10012351，协战子卡 token；主牌未加入，直接发牌测试）
#
# [觉醒]：妖刀姬对敌方牌手造成伤害时，她的战斗牌本回合获得[瞬发]及 +1/+1
# （数值通道可叠加）；[羁绊]：姑获鸟发起一次攻击（联动其攻击后退回能力）。
# 队伍 [妖刀姬, 姑获鸟, 白狼, 兵俑]；妖刀姬 2 级、姑获鸟 1 级。
# ==========================================================================

RYDL = 10012351      # 刃影叠岚
ZY = 10012303        # 战意（+2/+2 战斗牌）

RY_TEAM = [100123, 100106, 100101, 100102]


def _die_lan_auras(pa):
    return [a for a in pa.card_auras
            if a.get("power") == 1 and a.get("shield") == 1 and "fast" in a["keywords"]]


def test_launch_attack_and_retreat_linkage(make_game):
    """羁绊：姑获鸟发起一次攻击（不耗火/出击次数），并联动其基础能力攻击后退回。"""
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1}, team=RY_TEAM)
    play(g, 0, RYDL)
    assert pa.shikigami[0].awakened == RYDL
    assert pa.shikigami[0].health == 5        # 觉醒 +0/+1
    assert pb.health == 27                    # 姑获鸟 3 攻打脸
    assert pa.combat_index is None            # 姑获鸟攻击后已退回准备区


def test_card_aura_stacks_and_stats(make_game):
    """觉醒：打脸登记战斗牌[瞬发]+1/+1 光环（可叠加）；战意吃满光环数值且瞬发免费。"""
    g, pa, pb = _game(make_game, levels={0: 2, 1: 1}, team=RY_TEAM)
    play(g, 0, RYDL)                          # 姑获鸟羁绊攻击：pb 27
    g.apply({"op": "assault", "index": 0})    # 妖刀姬 3 攻打脸 → 光环①
    assert pb.health == 24
    assert len(_die_lan_auras(pa)) == 1
    orb = pa.orb
    play(g, 0, ZY)                            # 战力 2+1、护甲 2+1；光环瞬发免费
    assert pa.orb == orb
    assert pb.health == 18                    # 3+3=6 打脸 → 光环②（数值可叠加）
    assert len(_die_lan_auras(pa)) == 2
    assert pa.shikigami[0].shield == 3        # 一次性护甲 2+1（无反击保留）


# ---------- 姑获鸟/酒吞童子协战主牌 ----------

RYHL = 10010621   # 刃影鹤唳（姑获鸟/妖刀姬）
KGHQ = 10010321   # 狂歌豪情（茨木童子/酒吞童子）
HHHF = 10010651   # 鹤唳回风（姑获鸟侧子卡）
ZJDG = 10010951   # 醉酒当歌（酒吞侧子卡）

KG_TEAM = [100103, 100109, 100001, 100002]  # 茨木/酒吞/纸人武士/天邪鬼军团


def test_reinforce_main_cards_dual_ownership(gdb):
    """刃影鹤唳/狂歌豪情：options 登记与构筑池双归属（同时列入两位所属式神）。"""
    from client.deckbuilder import buildable_cards
    assert gdb.cards[RYHL].options == [HHHF, 10012351]
    assert gdb.cards[KGHQ].options == [10010351, ZJDG]
    assert RYHL in {c.id for c in buildable_cards(gdb, 100106)}
    assert RYHL in {c.id for c in buildable_cards(gdb, 100123)}
    assert KGHQ in {c.id for c in buildable_cards(gdb, 100103)}
    assert KGHQ in {c.id for c in buildable_cards(gdb, 100109)}


def test_play_sub_side_bond_generate(make_game):
    """狂歌豪情选副侧醉酒当歌：主牌离手放逐；酒吞自伤 3（触发基础能力）+ 等量
    护甲 3；[羁绊]获得茨木当前等级（1 级）的战斗牌——唯一为鬼之手。"""
    g, pa, pb = _game(make_game, levels={0: 1, 1: 1}, team=KG_TEAM)
    _play_reinforce(g, 0, KGHQ, 1)            # 狂歌豪情 → 醉酒当歌
    assert not any(c.id == KGHQ for c in pa.hand)
    assert any(c.id == KGHQ for c in pa.zones["exiled"])
    jt = pa.shikigami[1]
    assert jt.health == 2                     # 5 - 3 自伤
    assert jt.shield == 3                     # 等量护甲（自伤后获得，不被消耗）
    assert jt.temp_power == 1                 # 基础能力：受伤 +1 力量
    assert any(c.id == 10010301 for c in pa.hand)   # 鬼之手（茨木 1 级唯一战斗牌）


# ==========================================================================
# 森佑灵矢（10010121，协战：白狼×萤草；第十四阶段）
#
# 子卡：灵矢贯虹（白狼侧，10010151）/ 森佑灵引（萤草侧，10012751）。
# 森佑灵引：从牌库抽取 1 张不高于目标式神等级的形态牌（命中后洗牌库——答复(5)）；
# 目标力量>=4且存活改为直接使用（从牌库直接结附）；[羁绊]白狼获得[庇佑]。
# 队伍固定 [萤草, 白狼, 兵俑, 妖刀姬]。
# ==========================================================================

SYLS = 10010121   # 森佑灵矢
SYLY = 10012751   # 森佑灵引（萤草侧子卡）


def test_reinforce_main_dual_ownership(gdb):
    """森佑灵矢：options 登记与构筑池双归属（白狼/萤草两侧均可编入）。"""
    from client.deckbuilder import buildable_cards
    assert gdb.cards[SYLS].options == [LSGH, SYLY]
    assert SYLS in {c.id for c in buildable_cards(gdb, 100101)}
    assert SYLS in {c.id for c in buildable_cards(gdb, 100127)}


def test_search_deck_form_filtered_by_target_level(make_game):
    """森佑灵引（目标力量<4）：从牌库抽取 1 张不高于目标等级的形态牌置入手牌
    并洗牌库（检索命中即洗——维护者答复(5)）；[羁绊]白狼获得[庇佑]。"""
    g, pa, pb = _game(make_game, levels={YC_IDX: 2, WOLF_IDX: 1}, team=YC_TEAM)
    for c in [c for c in pa.hand if c.id == 10012702]:
        g.move_card(pa, c, "deck")            # 保证牌库内有可检索的 1 级形态
    before = [c.uid for c in pa.deck]
    hand0 = {c.uid for c in pa.hand}
    _play_reinforce(g, 0, SYLS, 1, target=Ref(player=0, shikigami=YC_IDX))
    assert not any(c.id == SYLS for c in pa.hand)
    assert any(c.id == SYLS for c in pa.zones["exiled"])      # 主牌离手放逐
    new = [c for c in pa.hand if c.uid not in hand0]
    # 目标萤草 1 级……（levels 给 2 以满足子卡等级，检索按目标当前等级 ≤2：
    # 牌库内 ≤1 级形态仅治愈之光——上面已确保其在库）
    assert len(new) == 1 and g.db.cards[new[0].id].card_type == "form"
    assert new[0].id // 100 == YC
    rest = [c.uid for c in pa.deck]
    assert sorted(rest) == sorted(u for u in before if u != new[0].uid)  # 牌集合一致
    assert any("洗了牌库" in l for l in g.state.log)          # 命中后洗牌（答复(5)）
    assert "blessing" in pa.shikigami[WOLF_IDX].one_shot_keywords


def test_search_deck_direct_play_form(make_game):
    """森佑灵引（20191212 环境；目标力量>=4且存活）：形态牌改为直接使用——从牌库
    直接结附给目标式神，不入手牌（萤草旧版基础能力使用形态牌抽 1）。"""
    from db.loader import CardDatabase
    db = CardDatabase.load()
    # 萤草钉 20191212 版基础能力（20200327 起打出前无形态不抽牌）；
    # 协战主牌发布晚于 20191212，整库 at_date 会丢卡，只替换式神定义
    db.shikigami[YC] = CardDatabase.load().at_date(20191212).shikigami[YC]
    g = F.mk_game(db, team=YC_TEAM)
    pa, pb = F.battle_setup(g, {YC_IDX: 2, WOLF_IDX: 1})
    yc = pa.shikigami[YC_IDX]
    yc.perm_power = 2                         # 萤草 2+2=4 力量（≥4 且存活）
    for c in [c for c in pa.hand if c.id in (10012702, 10012704)]:
        g.move_card(pa, c, "deck")            # 保证牌库内有 ≤2 级形态可检索
    deck0 = len(pa.deck)
    hand0 = len(pa.hand)
    _play_reinforce(g, 0, SYLS, 1, target=Ref(player=0, shikigami=YC_IDX))
    assert yc.form is not None and yc.form.id in (10012702, 10012704)
    # 牌库 -2：直接使用的形态 + 萤草基础能力（使用形态牌抽 1）；
    # 手牌 +1：发主牌（hand0 快照在发牌前）后打出离手，基础能力抽 1
    assert len(pa.deck) == deck0 - 2
    assert len(pa.hand) == hand0 + 1
    assert "blessing" in pa.shikigami[WOLF_IDX].one_shot_keywords
