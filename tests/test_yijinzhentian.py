"""以津真天（100126）数据测试：真实 db YAML 端到端（阶段 B-3）。

覆盖：基础/觉醒倒计时生成黄金羽（generate card_id 指定 token）、黄金羽瞬发打牌手与
觉醒后狙击敌方式神（PlayMethod requires_awaken 门控）、黄金羽记账（feather_used_game/
turn 与 on_card_played 的 golden_feather payload）、风之舞增强计数、金风流羽视为黄金羽
与条件免费（cost_zero_if）、不可饶恕回合级战斗免疫（grant_immunity）、射怪鸟事气绝前
响应弃抽（discard→memo 计数 + draw {"memo": key}）、千羽风之舞战斗牌其它效果步、
流浪之羽形态触发随机伤害。
队伍固定 [以津真天, 白狼, 兵俑, 妖刀姬]，以津真天 0 号位开局自动 1 级（静态倒计时开局
注册 2、对局开始的回合开始批次已 -1，故开局 countdown == 1；B 以津真天同理，其倒计时
会往 B 手牌塞黄金羽，不影响本组断言）。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from db.loader import CardDatabase
from tests import factories as F
from tests.factories import give, move, pass_turns, play

YJZT = 100126     # 以津真天（双方 0 号位）
IDX = 0
JYHS = 10012601   # 金羽焕生
FZW = 10012602    # 风之舞
JLFY = 10012603   # 金风流羽
BKRS = 10012604   # 不可饶恕
SGNS = 10012605   # 射怪鸟事
AWAKEN = 10012606  # 觉醒·以津真天
QYFW = 10012607   # 千羽风之舞
LLZY = 10012608   # 流浪之羽
FEATHER = 10012651  # 黄金羽（token）

TEAM = [100126, 100101, 100102, 100123]


@pytest.fixture
def gdb():
    """真实卡牌数据库（db/ 目录 YAML，strict 校验加载）。"""
    return CardDatabase.load()


@pytest.fixture
def make_game(gdb):
    def _make(seed: int = 1, **kw):
        return F.mk_game(gdb, seed=seed, team=TEAM, **kw)

    return _make


def _game(make_game, ft_level: int = 1):
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    for s in pb.shikigami:
        s.level = 1
    pa.shikigami[IDX].level = ft_level
    return g, pa, pb


def _play_method(g, player: int, defn_id: int, method: str, target: Ref) -> None:
    """发一张牌到手上并以指定使用方式打出（play_method + 选择目标）。"""
    card = give(g, player, defn_id)
    g.apply({"op": "play_card", "uid": card.uid, "play_method": method, "target": target})


# ---------- 基础能力：倒计时生成黄金羽 ----------

def test_base_countdown_generates_feather(make_game):
    """静态倒计时能力开局注册（2 → 对局开始批次 -1 = 1）；归零：黄金羽入手、
    循环重置、history 记式神 id。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    assert s.countdown == 1
    assert s.countdown_source == YJZT
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert any(c.id == FEATHER for c in pa.hand)
    assert s.countdown == 2                   # 循环型重置
    assert pa.ext["countdown_history"] == [YJZT]


# ---------- 01 金羽焕生 ----------

def test_jinyu_huansheng_two_feathers(make_game):
    """金羽焕生：将两张黄金羽置入手牌（指定 id 生成，token 不入随机池）。"""
    g, pa, pb = _game(make_game)
    play(g, 0, JYHS)
    assert sum(1 for c in pa.hand if c.id == FEATHER) == 2


# ---------- 51 黄金羽：瞬发打牌手 / 记账 ----------

def test_feather_fast_hits_player_and_accounts(make_game):
    """黄金羽：瞬发（本回合首张瞬发免费，鬼火不变）对敌方牌手 2 伤；
    记账 feather_used_game/turn。"""
    g, pa, pb = _game(make_game)
    play(g, 0, FEATHER)
    assert pb.health == 28
    assert pa.orb == 9                        # 瞬发免费
    assert pa.ext["feather_used_game"] == 1
    assert pa.ext["feather_used_turn"] == 1


# ---------- 02 风之舞：黄金羽增强 ----------

def test_wind_dance_enhance(make_game):
    """每用过一张黄金羽 +1/+1（持久计数，打出装配快照）：用 2 张后 +2/+2。"""
    g, pa, pb = _game(make_game)
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

def test_jinfeng_liuyu_cost_and_accounting(make_game):
    """未用过黄金羽：正常 1 火，且自身视为黄金羽记账；用过之后：不耗火。"""
    g, pa, pb = _game(make_game, ft_level=2)
    play(g, 0, JLFY)                          # 1 火（费用先于记账计算，自身不免自身）
    assert pa.orb == 8
    assert pa.ext["feather_used_turn"] == 1   # tags golden_feather：视为黄金羽
    play(g, 0, JLFY)                          # 本回合已用过黄金羽：0 火
    assert pa.orb == 8
    assert pa.ext["feather_used_turn"] == 2


# ---------- 04 不可饶恕：回合级战斗免疫 ----------

def test_unforgivable_immunity(make_game):
    """结附后本回合用过黄金羽：免疫战斗伤害（反击不扣血；回合号记账）。"""
    g, pa, pb = _game(make_game, ft_level=2)
    play(g, 0, BKRS)                          # 形态 4/6
    play(g, 0, FEATHER)                       # 触发形态能力：本回合免疫战斗伤害
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    g.apply({"op": "assault", "index": IDX})  # 以津真天 4 攻 → 兵俑 6→2
    assert pb.shikigami[2].health == 2
    assert pa.shikigami[IDX].health == 6      # 反击 1 被免疫


# ---------- 05 射怪鸟事：气绝前响应弃抽 ----------

def test_shagua_niaoshi_response(make_game):
    """响应：以津真天将气绝时自动使用——弃掉所有她的专属牌并抽等量（瞬发免费）。"""
    g, pa, pb = _game(make_game, ft_level=2)
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

def test_awaken_countdown_one(make_game):
    """觉醒：永久 +1/+1；觉醒倒计时（initial 1，来源=觉醒牌 id）归零黄金羽入手。"""
    g, pa, pb = _game(make_game, ft_level=2)
    s = pa.shikigami[IDX]
    play(g, 0, AWAKEN)
    assert s.awakened == AWAKEN
    assert s.perm_power == 1 and s.perm_health == 1
    assert s.countdown == 1 and s.countdown_source == AWAKEN
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert any(c.id == FEATHER for c in pa.hand)
    assert s.countdown == 1                   # 循环重置为 1
    assert pa.ext["countdown_history"] == [AWAKEN]


def test_feather_snipe_requires_awaken(make_game):
    """黄金羽以敌方式神为目标：未觉醒门控 IllegalAction；觉醒后可狙击 2 伤。"""
    g, pa, pb = _game(make_game, ft_level=2)
    wolf = Ref(player=1, shikigami=1)
    with pytest.raises(IllegalAction):
        _play_method(g, 0, FEATHER, "snipe", wolf)   # 未觉醒：门控拒绝
    play(g, 0, AWAKEN)
    _play_method(g, 0, FEATHER, "snipe", wolf)       # 觉醒后：瞬发免费狙击
    assert pb.shikigami[1].health == 2
    assert pa.orb == 8                        # 仅觉醒牌 1 火


# ---------- 07 千羽风之舞：战斗牌其它效果步 ----------

def test_qianyu_no_feather_no_generate(make_game):
    """本回合未用过黄金羽：仅 +3/+3，不生成金风流羽。"""
    g, pa, pb = _game(make_game, ft_level=3)
    play(g, 0, QYFW)
    assert not any(c.id == JLFY for c in pa.hand)


def test_qianyu_after_feather_generates(make_game):
    """本回合用过黄金羽：战斗流程执行其它效果步——金风流羽置入手牌。"""
    g, pa, pb = _game(make_game, ft_level=3)
    play(g, 0, FEATHER)
    play(g, 0, QYFW)
    assert any(c.id == JLFY for c in pa.hand)


# ---------- 08 流浪之羽：形态触发随机伤害 ----------

def test_wandering_feather_random_damage(make_game):
    """结附期间使用黄金羽：随机对两个敌方式神各造成 2 点伤害（合计 4）。"""
    g, pa, pb = _game(make_game, ft_level=3)
    play(g, 0, LLZY)
    before = sum(s.health for s in pb.shikigami)
    play(g, 0, FEATHER)
    after = sum(s.health for s in pb.shikigami)
    assert before - after == 4
