"""协战机制（reinforce）与风之乐章/致命之羽数据测试：真实 db YAML 端到端（阶段 C）。

覆盖：构筑归属（协战牌计入所属式神 8 张、同名限 2、双归属任一出战可编、均未出战拒绝）、
打出流程（choice 选择子选项、费用/等级/目标按子卡、生成 token 视作从手牌使用走完整
使用事件流程、主牌离手进 removed 不进墓地、非法选项/未出战/气绝归属拒绝）、
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
JLFY = 10012603   # 金风流羽

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

def test_play_choice_full_flow_and_main_removed(make_game):
    """选择子选项：费用按子卡（1 火）、生成 token 视作从手牌使用（效果完整结算）、
    主牌离手进 removed（不进墓地）。"""
    g, pa, pb = _game(make_game)
    hand_before = len(pa.hand)
    _play_reinforce(g, 0, FYZ, 0)             # 风之乐章 → 幻音绝弦
    assert pa.orb == 8                        # 子选项正常 1 火
    assert not any(c.id == FYZ for c in pa.hand)
    assert not any(c.id == FYZ for c in pa.graveyard)     # 主牌不入墓地
    assert any(c.id == FYZ for c in pa.zones["removed"])  # 离手移除
    assert not any(c.id == HYJX for c in pa.hand)         # token 已使用离手
    assert any(c.id == HYJX for c in pa.graveyard)
    assert len(pa.shikigami[YQS].delayed) == 1            # 延迟能力已登记
    forms = {10012501, 10012502, 10012504, 10012506, 10012507, 10012508}
    assert any(c.id in forms for c in pa.hand)            # 羁绊：一目连形态牌入手
    assert len(pa.hand) == hand_before + 1  # give 主牌+生成 token+打出=抵消，羁绊 +1


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
    assert any(c.id == FYZ for c in pa.zones["removed"])


def test_play_owner_defeated_rejects_only_that_side(make_game):
    """子选项所属式神气绝：仅该侧不可用；另一侧（一目连）照常。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 2})
    g.deal_to_shikigami(Ref(player=0, shikigami=YQS), 99, None)   # 妖琴师气绝
    g._drain_queue()
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, FYZ, 0)
    _play_reinforce(g, 0, FYZ, 1)             # 一目连侧正常
    assert any(c.id == FYZ for c in pa.zones["removed"])


def test_play_no_owner_deployed_rejected(make_game):
    """两位所属式神均未出战：拒绝（等级/费用检查之前）。"""
    g, pa, pb = _game(make_game, team=TEAM_WOLF)
    with pytest.raises(IllegalAction):
        _play_reinforce(g, 0, ZMZY, 0)


# ---------- 幻音绝弦：延迟倒计时 / 气绝倒计时 ----------

def test_huanyin_delayed_countdown_and_revive(make_game):
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

def test_fengyun_replays_ichimokuren_countdowns(make_game):
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
    awakens = {10012401, 10012404, 10012407}
    assert any(c.id in awakens for c in pa.hand)              # 羁绊：妖琴师觉醒牌入手
    assert any("重放" in m for m in g.state.log[log_before:])


# ---------- 鎏金幻羽：手牌修饰 ----------

def test_liujin_mods_real_feathers_and_bond(make_game):
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


def test_liujin_gilded_feather_effects(make_game):
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


def test_gilded_feather_defeated_awakened_no_snipe(make_game):
    """维护者答复(11)联动：已觉醒的以津真天气绝后，经鎏金幻羽修饰的黄金羽只能打
    敌方牌手（气绝时觉醒能力不在场，snipe 使用方式门控拒绝、无需选择目标）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    play(g, 0, 10012606)                      # 觉醒·以津真天
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

def test_shiren_doubles_fragile_and_bond(make_game):
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


def test_shiren_no_fragile_no_double(make_game):
    """被攻击者无破甲：不触发翻倍（正常战斗）。"""
    g, pa, pb = _game(make_game, levels={YQS: 2, YML: 1, YJZT: 2, ZHEN: 2})
    move(g, 1, YML)                           # B 一目连无破甲
    _play_reinforce(g, 0, ZMZY, 1)
    assert pb.shikigami[YML].health == 2      # 4 伤
    assert pb.shikigami[YML].shield == 0


# ---------- 灵矢贯虹：鼓舞消耗转化 ----------

def test_lingshi_consumes_assault_boosts(make_game):
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
