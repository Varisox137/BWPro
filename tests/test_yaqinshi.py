"""妖琴师（100124）数据测试：真实 db YAML 端到端（阶段 B-4，阶段 B 收尾）。

覆盖：基础倒计时治疗、三觉醒替换+同次出牌 -3 立即归零（A2 路径）、大合奏按
countdown_history 首次出现顺序重放（replay_countdown + _countdown_block_for）、
魔音扰心无效化（主动 delay_grant / 响应 response 覆盖块两路径）、惊弦/疯魔琴心/余音
的 countdown_delta（含无倒计时修正 -0）、镇魂歌抽牌+鬼火。
队伍固定 [妖琴师, 鸩, 以津真天, 妖刀姬]，妖琴师 0 号位开局自动 1 级（静态倒计时开局
注册 3、对局开始批次已 -1，故开局 countdown == 2）。手动 level=1 不注册倒计时
（仅升级指令/开局 0 号位/复活注册）——需要友方其他倒计时能力的用例显式调用
g._register_ability_countdown。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import give, move, pass_turns, play

YQS = 100124      # 妖琴师（双方 0 号位）
IDX = 0
RUZHENG = 10012401   # 觉醒·入阵歌
JINGXIAN = 10012402  # 惊弦
DAHEZOU = 10012403   # 大合奏
SHENYUE = 10012404   # 觉醒·神乐歌
FENGMO = 10012405    # 疯魔琴心
MOYIN = 10012406     # 魔音扰心
ZHENHUN = 10012407   # 觉醒·镇魂歌
YUYIN = 10012408     # 余音

TEAM = [100124, 100128, 100126, 100123]


@pytest.fixture
def make_game(real_game):
    def _make(seed: int = 1, **kw):
        return real_game(TEAM, seed=seed, **kw)

    return _make


def _game(make_game, ft_level: int = 1):
    g = make_game()
    # 手动升级不注册倒计时：B 侧手动 1 级无倒计时干扰
    pa, pb = F.battle_setup(g, {IDX: ft_level})
    return g, pa, pb


def _register_allied_countdowns(g):
    """让 A 鸩（1 号位）/以津真天（2 号位）在场并注册其静态倒计时能力。"""
    pa = g.state.players[0]
    for i in (1, 2):
        pa.shikigami[i].level = 1
        g._register_ability_countdown(0, i)


# ---------- 基础能力：倒计时治疗 ----------

def test_base_countdown_heals(make_game):
    """静态倒计时（initial 3 → 开局批次 -1 = 2）；归零：己方所有角色恢复 3 生命、
    循环重置、history 记式神 id。"""
    g, pa, pb = _game(make_game)
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


# ---------- 觉醒三张：替换 + 同次 -3 立即归零 ----------

def test_awaken_ruzheng_immediate(make_game):
    """觉醒·入阵歌：+0/+1 永久；觉醒替换注册倒计时 3（来源=觉醒牌 id）→ 同次出牌
    触发 -3 至 0 立即归零：5 伤随机分配给所有敌方角色。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    enemy_total = sum(x.health for x in pb.shikigami) + pb.health
    play(g, 0, RUZHENG)
    assert s.awakened == RUZHENG
    assert s.perm_health == 1
    assert s.countdown == 3 and s.countdown_source == RUZHENG   # 归零后循环重置
    assert enemy_total - (sum(x.health for x in pb.shikigami) + pb.health) == 5
    assert pa.ext["countdown_history"] == [RUZHENG]


def test_awaken_shenyue_immediate(make_game):
    """觉醒·神乐歌：+1/+0 永久；同次 -3 立即归零：己方其他在场式神倒计时 -1
    并获得 1 力量与 1 生命（临时修正）。"""
    g, pa, pb = _game(make_game, ft_level=2)
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


def test_awaken_zhenhun_immediate(make_game):
    """觉醒·镇魂歌：+1/+1 永久；同次 -3 立即归零：抽一张牌、获得 1 点鬼火。"""
    g, pa, pb = _game(make_game, ft_level=3)
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

def test_dahezou_replays_in_history_order(make_game):
    """大合奏：基础（先归零）→ 入阵歌 → 镇魂歌的生效顺序依次重放，每种至多一次。"""
    g, pa, pb = _game(make_game, ft_level=3)
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


def test_dahezou_skips_form_sources(make_game, gdb):
    """维护者答复(8)：大合奏只计入基础/觉醒能力，形态来源跳过——妖琴师当前无形态牌，
    构造性改写一张形态卡的归属并注入 history 验证。"""
    g, pa, pb = _game(make_game, ft_level=1)
    gdb.cards[10012608].shikigami = YQS       # 构造：归属妖琴师的形态来源（流浪之羽）
    pa.ext["countdown_history"] = [10012608, YQS]
    pa.health = 20
    log_before = len(g.state.log)
    play(g, 0, DAHEZOU)
    assert pa.health == 23                    # 仅重放基础治疗（形态来源被跳过）
    replay_logs = [m for m in g.state.log[log_before:] if "重放" in m]
    assert len(replay_logs) == 1 and f"来源 {YQS}）" in replay_logs[0]


# ---------- 06 魔音扰心：无效化（主动 / 响应） ----------

def test_moyin_proactive_nullifies_next_enemy_card(make_game):
    """主动使用：登记一次性延迟能力——敌方本回合下一张牌的使用手牌前无效化
    （费用已付不退、牌离手进墓地、效果跳过）。"""
    g, pa, pb = _game(make_game, ft_level=2)
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


def test_moyin_response_nullifies_current_card(make_game):
    """响应：敌方牌手将使用牌时自动使用（response 覆盖块）——直接无效化该次使用。"""
    g, pa, pb = _game(make_game, ft_level=2)
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

def test_jingxian_triggers_zero_and_noop_without_countdown(make_game):
    """惊弦：使一个式神倒计时 -2——点妖琴师自己立即归零结算；点无倒计时能力者
    修正 -0（空操作）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    pa.health = 20
    play(g, 0, JINGXIAN, target=Ref(player=0, shikigami=IDX))   # 2-2=0：归零
    assert pa.health == 23                    # 归零治疗生效
    assert s.countdown == 3                   # 循环重置
    assert pa.ext["countdown_history"] == [YQS]
    play(g, 0, JINGXIAN, target=Ref(player=1, shikigami=3))     # B 妖刀姬无倒计时：-0
    assert pb.shikigami[3].countdown is None


def test_fengmo_enemy_plus2_self_minus2(make_game):
    """疯魔琴心：敌方式神 +2（无倒计时能力者 -0），妖琴师 -2（可立即归零）。"""
    g, pa, pb = _game(make_game, ft_level=2)
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


def test_yuyin_self_and_allied_minus(make_game):
    """余音：妖琴师 -3（立即归零），己方其他未气绝式神 -1。"""
    g, pa, pb = _game(make_game, ft_level=3)
    _register_allied_countdowns(g)            # 鸩/以津真天倒计时均为 2
    s = pa.shikigami[IDX]
    pa.health = 20
    play(g, 0, YUYIN)
    assert pa.health == 23                    # 自身 2-3：归零治疗
    assert s.countdown == 3
    assert pa.shikigami[1].countdown == 1
    assert pa.shikigami[2].countdown == 1
    assert pa.ext["countdown_history"] == [YQS]
