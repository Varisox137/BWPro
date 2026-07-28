"""鸩（100128）数据测试：真实 db YAML 端到端（阶段 B-2，验证 A3/A4 破甲管线）。

覆盖：基础/觉醒倒计时给破甲、x（zhen_proc）计数与跨气绝保留、破甲增伤实卡路径、
鸩羽/致命诱惑的战斗条件授予（defender_has_fragile）、毒蚀伤害→破甲转化（主动/响应）、
碧羽散华获得破甲→伤害转化、毒之华半血破甲、寂寥心象每回合合计一次二选一、吸血实卡。
队伍固定 [鸩, 白狼, 兵俑, 妖刀姬]，鸩 0 号位开局自动 1 级（静态倒计时开局注册 2、
对局开始的回合开始批次已 -1，故开局 countdown == 1；B 鸩同理，其破甲给 A 牌手，
不影响本组断言）。
"""
import pytest

from core.model import Ref
from tests import factories as F
from tests.factories import give, move, pass_turns, play

ZHEN = 100128     # 鸩（双方 0 号位）
IDX = 0
ZY = 10012801     # 鸩羽
ZYS = 10012802    # 鸩羽苏生
JLXX = 10012803   # 寂寥心象
DS = 10012804     # 毒蚀
AWAKEN = 10012805  # 觉醒·鸩
ZMYH = 10012806   # 致命诱惑
BYSH = 10012807   # 碧羽散华
DZH = 10012808    # 毒之华

TEAM = [100128, 100101, 100102, 100123]


@pytest.fixture
def make_game(real_game):
    def _make(seed: int = 1, **kw):
        return real_game(TEAM, seed=seed, **kw)

    return _make


def _game(make_game, zhen_level: int = 1):
    g = make_game()
    pa, pb = F.battle_setup(g, {IDX: zhen_level})
    return g, pa, pb


# ---------- 基础能力：倒计时给破甲 / x 计数 ----------

def test_base_countdown_gives_fragile(make_game):
    """静态倒计时能力开局注册（2 → 对局开始批次 -1 = 1）；归零：敌方牌手 2 破甲、
    循环重置、zhen_proc +1、history 记式神 id。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    assert s.countdown == 1
    assert s.countdown_source == ZHEN
    pass_turns(g, 2)                          # A 第 2 回合开始：1→0 归零
    assert pb.shield == -2                    # 敌方牌手获得 2 破甲
    assert s.countdown == 2                   # 循环型重置
    assert s.ext["zhen_proc"] == 1            # x：基础+觉醒生效合计
    assert pa.ext["countdown_history"] == [ZHEN]


def test_fragile_boosts_damage(make_game):
    """破甲增伤实卡路径：每点破甲使受伤 +1（伤害管线护甲计算）。"""
    g, pa, pb = _game(make_game)
    pass_turns(g, 2)                          # pb.shield == -2
    g.deal_to_player(1, 3, None)
    assert pb.health == 25                    # 3 + 2（破甲）


def test_zhenyu_susheng(make_game):
    """鸩羽苏生：鸩倒计时 -2（1→0 立即归零结算）+ 抽 1。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    hand_before = len(pa.hand)
    play(g, 0, ZYS)
    assert pb.shield == -2                    # 倒计时被减到归零：破甲生效
    assert s.countdown == 2                   # 归零后循环重置
    assert s.ext["zhen_proc"] == 1
    assert len(pa.hand) == hand_before + 1    # give+打出抵消，抽 1


def test_x_survives_defeat(make_game):
    """x 跨气绝保留：气绝清除倒计时能力，ext["zhen_proc"] 不清；复活重注册倒计时。"""
    g, pa, pb = _game(make_game)
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

def test_zhenyu_immunity_vs_fragile(make_game):
    """攻击有破甲的角色：免疫战斗伤害（反击不扣血）。"""
    g, pa, pb = _game(make_game)
    pb.shikigami[2].shield = -1               # B 兵俑（1/6）持 1 破甲
    move(g, 1, 2)
    play(g, 0, ZY)                            # 鸩 2+2=4 攻 → 兵俑 4+1=5 伤
    assert pb.shikigami[2].health == 1
    assert pa.shikigami[IDX].health == 5      # 反击 1 被免疫


def test_zhenyu_no_immunity_without_fragile(make_game):
    """被攻击者无破甲：不免疫（正常吃反击）。"""
    g, pa, pb = _game(make_game)
    move(g, 1, 2)                             # B 兵俑无破甲
    play(g, 0, ZY)
    assert pb.shikigami[2].health == 2        # 4 伤
    assert pa.shikigami[IDX].health == 4      # 反击 1 正常扣血


# ---------- 04 毒蚀：伤害→破甲转化 ----------

def test_dushi_active_converts_both_sides(make_game):
    """主动使用：本次战斗中双方造成的伤害转化为等量破甲；战斗结束后转化清除。"""
    g, pa, pb = _game(make_game, zhen_level=2)
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    play(g, 0, DS)                            # 鸩 2+4=6 攻
    wolf = pb.shikigami[1]
    zhen = pa.shikigami[IDX]
    assert wolf.health == 4 and wolf.shield == -6    # 6 伤 → 6 破甲
    assert zhen.health == 5 and zhen.shield == -3    # 反击 3 → 3 破甲
    g.deal_to_player(1, 2, None)              # 战斗结束后：伤害不再转化
    assert pb.health == 28


def test_dushi_response_on_attacked(make_game):
    """响应：当鸩被攻击时自动使用——插入的战斗同样全程转化。"""
    g, pa, pb = _game(make_game, zhen_level=2)
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


def test_dushi_with_biyu_net_effect(make_game):
    """维护者答复(5)净效果：碧羽散华形态的鸩使用毒蚀——敌方式神正常受伤（伤害事件
    生成点→破甲→碧羽嵌套转回伤害，嵌套不再触发毒蚀），鸩自身被反击获得破甲而不受伤。"""
    g, pa, pb = _game(make_game, zhen_level=3)
    play(g, 0, BYSH)                          # 碧羽散华结附（鸩 5/7，标记敌方）
    move(g, 1, 1)                             # B 白狼（3/4）入战斗区
    wolf = pb.shikigami[1]
    wolf.base_health = wolf.health = 20       # 撑住攻击便于观察净效果
    play(g, 0, DS)                            # 毒蚀：鸩 5+4=9 攻
    zhen = pa.shikigami[IDX]
    assert wolf.health == 11 and wolf.shield == 0   # 9 伤→9 破甲→碧羽转回 9 伤
    assert zhen.health == 7 and zhen.shield == -3   # 反击 3 → 3 破甲，不受伤


# ---------- 05 觉醒·鸩：x 累加 ----------

def test_awaken_x_scaling(make_game):
    """觉醒：效果 2 破甲 + 永久 +1 力量；觉醒倒计时（initial 2，来源=觉醒牌 id）给
    2+x 破甲（x=基础+觉醒生效合计，觉醒后继续累加）。"""
    g, pa, pb = _game(make_game, zhen_level=2)
    s = pa.shikigami[IDX]
    pass_turns(g, 2)                          # 基础归零：pb -2，zhen_proc 1，重置 2
    assert pb.shield == -2
    play(g, 0, AWAKEN)                        # 效果：pb 再 -2
    assert pb.shield == -4
    assert s.awakened == AWAKEN
    assert s.perm_power == 1
    assert s.countdown == 2 and s.countdown_source == AWAKEN
    pass_turns(g, 4)                          # A 第 4 回合开始觉醒归零（期间 B 回合开始清过 pb 破甲）
    assert pb.shield == -3                    # 2 + x(1) = 3
    assert s.ext["zhen_proc"] == 2            # 觉醒生效继续累加
    assert pa.ext["countdown_history"] == [ZHEN, AWAKEN]


# ---------- 06 致命诱惑：条件吸血 ----------

def test_zhiming_lifesteal_vs_fragile(make_game):
    """攻击有破甲的角色：获得[吸血]（实卡路径：伤害后为牌手恢复等量生命）。"""
    g, pa, pb = _game(make_game, zhen_level=2)
    pa.health = 20
    pb.shikigami[1].shield = -1               # B 白狼持 1 破甲
    move(g, 1, 1)
    play(g, 0, ZMYH)                          # 鸩 2+2=4 攻 → 白狼 4+1=5 伤气绝
    assert pb.shikigami[1].defeated
    assert pa.health == 25                    # 吸血：恢复 5（伤害值）


def test_zhiming_no_lifesteal_without_fragile(make_game):
    """被攻击者无破甲：不获得吸血。"""
    g, pa, pb = _game(make_game, zhen_level=2)
    pa.health = 20
    move(g, 1, 2)                             # B 兵俑（1/6）无破甲
    play(g, 0, ZMYH)
    assert pb.shikigami[2].health == 2        # 4 伤
    assert pa.health == 20                    # 无吸血
    assert pa.shikigami[IDX].health == 5      # +2 护甲吸收反击 1


# ---------- 07 碧羽散华：获得破甲→伤害 ----------

def test_biyu_sanhua_converts_and_clears(make_game):
    """结附期间：敌方式神获得破甲转化为等量伤害；形态离场（替换）后标记清除。"""
    g, pa, pb = _game(make_game, zhen_level=3)
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

def test_duzhihua_half_health_fragile(make_game):
    """对敌方角色造成战斗伤害后：目标获得等同于其当前生命一半（向下取整）的破甲。"""
    g, pa, pb = _game(make_game, zhen_level=3)
    move(g, 1, 2)                             # B 兵俑（1/6）入战斗区
    play(g, 0, DZH)                           # 鸩 2 攻 → 兵俑 6→4 → 破甲 4//2=2
    soldier = pb.shikigami[2]
    assert soldier.health == 4 and soldier.shield == -2
    assert pa.shikigami[IDX].health == 4      # 反击 1（+0/+0 无护甲）


# ---------- 03 寂寥心象：每回合合计一次 ----------

def test_jiliao_shikigami_branch_and_gate(make_game):
    """敌方式神获得破甲 → 鸩倒计时 -2（可立即归零）；同回合后续事件被门控（合计一次）。"""
    g, pa, pb = _game(make_game, zhen_level=2)
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


def test_jiliao_player_branch_and_next_turn(make_game):
    """敌方牌手获得破甲 → 敌方战斗区式神获得等量破甲；次回合门控清除可再触发。"""
    g, pa, pb = _game(make_game, zhen_level=2)
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
