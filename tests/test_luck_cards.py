"""运势批次（青蛙瓷器/山兔/座敷童子/妖狐）真实数据卡牌级端到端测试。

真实 db YAML 端到端（gdb fixture，风格同 test_data.py）。
- 骰点控制：运势判定掷 1d6 走 game.rng（契约 §0），`_force_dice` 用 monkeypatch
  把 game.rng 的 (1, 6) randint 替换为固定序列；序列耗尽回退真实 rng（过回合时
  其他随机消费不依赖其值）。
- 敌方默认 VS_TEAM（无运势能力的填充队伍），避免镜像队伍里敌方山兔/座敷的
  判定消费强制骰点序列。

注意：用例依赖引擎侧运势管线与新 op（契约 §3.5），引擎落地前预期失败。
"""
from __future__ import annotations

import pytest

from core.engine import IllegalAction
from core.model import CardInstance, GameConfig, Ref
from core.setup import new_game
from tests import factories as F
from tests.factories import move, pass_turns, play

IDX = 0

# 无运势能力的填充队伍（敌方默认）：大天狗/白狼/兵俑/妖刀姬
VS_TEAM = [100104, 100101, 100102, 100123]


def _force_dice(monkeypatch, g, values):
    """把 game.rng 的 1d6 替换为固定骰点序列；耗尽后回退真实 rng。"""
    real = g.rng
    pending = list(values)

    class _Rng:
        def __getattr__(self, name):
            return getattr(real, name)

        def randint(self, a, b):
            if (a, b) == (1, 6) and pending:
                return pending.pop(0)
            return real.randint(a, b)

    monkeypatch.setattr(g, "rng", _Rng())


def _game(gdb, team, enemy=VS_TEAM, levels=None, seed=1):
    """非镜像真实库对局 + 常用状态（同 test_data._game 的 battle_setup）。"""
    g = new_game(gdb, ("A", list(team), F.deck_of(*team)),
                 ("B", list(enemy), F.deck_of(*enemy)),
                 seed=seed, first=0, shuffle_team=False, mulligan=False,
                 config=GameConfig(auto_skip_upgrade=True))
    pa, pb = F.battle_setup(g, levels)
    return g, pa, pb


def _enemy_total(pb) -> int:
    return pb.health + sum(max(s.health, 0) for s in pb.shikigami)


# ==========================================================================
# 青蛙瓷器（100113）
# ==========================================================================

QWQC = 100113
CHUQIAN = 10011301      # 出千
LINGSHANG = 10011302    # 岭上开花
JIULIAN = 10011303      # 九莲宝灯
LIZHI = 10011304        # 立直
MENQIAN = 10011305      # 门前清
TOUZI_ZHADAN = 10011306  # 骰子炸弹
ZHUANYUN = 10011307     # 转运
QWQC_AWAKEN = 10011308  # 觉醒·青蛙瓷器

QWQC_TEAM = [100113, 100101, 100102, 100123]


def test_luck_roll_success_then_steps(gdb, monkeypatch):
    """出千（步骤级 luck_roll）：骰点 >= 4 判定成功——将一张'出千'置入手牌；
    骰子历史记最终有效骰点。"""
    g, pa, pb = _game(gdb, QWQC_TEAM)
    _force_dice(monkeypatch, g, [4])
    before = sum(1 for c in pa.hand if c.id == CHUQIAN)
    play(g, 0, CHUQIAN)
    assert sum(1 for c in pa.hand if c.id == CHUQIAN) == before + 1  # 生成 1（give+打出抵消）
    assert pa.ext["dice_history"] == [4]


def test_luck_roll_failure_no_steps(gdb, monkeypatch):
    """出千：骰点 < 4 判定失败——无生成、无失败效果（失败无效果，规则要点）。"""
    g, pa, pb = _game(gdb, QWQC_TEAM)
    _force_dice(monkeypatch, g, [3])
    before = sum(1 for c in pa.hand if c.id == CHUQIAN)
    play(g, 0, CHUQIAN)
    assert sum(1 for c in pa.hand if c.id == CHUQIAN) == before  # 无生成（开局手牌可能含出千）


def test_luck_success_aura_power_same_turn(gdb, monkeypatch):
    """青蛙瓷器光环（stat_aura luck_success_power）：判定成功过的回合 +2 力量，
    不叠加；跨回合消失（luck_success_turn 记账）。"""
    g, pa, pb = _game(gdb, QWQC_TEAM)
    s = pa.shikigami[IDX]
    base = s.eff_power
    _force_dice(monkeypatch, g, [6, 5])
    play(g, 0, CHUQIAN)                        # 成功 1 次
    assert pa.ext["luck_success_turn"] == g.state.turn
    assert s.eff_power == base + 2
    play(g, 0, CHUQIAN)                        # 同回合再成功：不叠加
    assert s.eff_power == base + 2
    pass_turns(g, 2)                           # 下个己方回合：光环消失
    assert s.eff_power == base


def test_luck_success_trigger_buff(gdb, monkeypatch):
    """岭上开花（on_luck_success 延时挂点）：判定者=己方的判定成功后青蛙瓷器 +1 力量。"""
    g, pa, pb = _game(gdb, QWQC_TEAM)
    s = pa.shikigami[IDX]
    play(g, 0, LINGSHANG)                      # 形态 2/7
    _force_dice(monkeypatch, g, [4])
    play(g, 0, CHUQIAN)
    assert s.temp_power == 1


def test_force_x1_if_form_guarantees_success(gdb, monkeypatch):
    """立直（force_x1_if）：青蛙瓷器有形态时阈值视为 1——骰点 1（照投照计）也成功。"""
    g, pa, pb = _game(gdb, QWQC_TEAM)
    s = pa.shikigami[IDX]
    play(g, 0, LINGSHANG)                      # 先结附形态
    _force_dice(monkeypatch, g, [1])
    play(g, 0, LIZHI)                          # 战斗 +0/+0
    assert pa.ext["dice_history"][-1] == 1     # 骰子照投照计
    assert any(e.get("kind") == "combat_damage" for e in s.immunities)


def test_luck_block_gates_form_ability(gdb, monkeypatch):
    """门前清（EffectBlock.luck 触发式门控）：出击时运势4 成功获得 2 护甲，失败不得。"""
    g, pa, pb = _game(gdb, QWQC_TEAM, levels={IDX: 2})
    play(g, 0, MENQIAN)                        # 形态 2/9
    s = pa.shikigami[IDX]
    move(g, 1, 1)                              # B 白狼（3/4）入战斗区
    _force_dice(monkeypatch, g, [4])
    g.apply({"op": "assault", "index": IDX})
    assert s.shield == 0 and s.health == 8     # 2 护甲被反击 3 消耗，扣 1
    g2, pa2, pb2 = _game(gdb, QWQC_TEAM, levels={IDX: 2})
    play(g2, 0, MENQIAN)
    s2 = pa2.shikigami[IDX]
    move(g2, 1, 1)
    _force_dice(monkeypatch, g2, [1])
    g2.apply({"op": "assault", "index": IDX})
    assert s2.shield == 0 and s2.health == 6   # 失败：无护甲，吃满反击 3


def test_luck_dice_ctx_amount(gdb, monkeypatch):
    """骰子炸弹（amount_ctx: luck_dice）：运势1 必定成功，造成等同于骰子点数的伤害。"""
    g, pa, pb = _game(gdb, QWQC_TEAM, levels={IDX: 2})
    move(g, 1, 1)                              # B 白狼（3/4）入战斗区
    _force_dice(monkeypatch, g, [3])
    play(g, 0, TOUZI_ZHADAN, target=Ref(player=1, shikigami=1))
    assert pb.shikigami[1].health == 1         # 4 - 3（骰点）
    assert pa.ext["dice_history"] == [3]


# ==========================================================================
# 山兔（100117）
# ==========================================================================

ST = 100117
SHUIHAI = 10011701      # 谁还不听话
SONGZHUFU = 10011702    # 送祝福
KUILAI = 10011703       # 快来保护我
ST_AWAKEN = 10011704    # 觉醒·山兔
ZBSWY = 10011705        # 这把算我赢
XIEXUE = 10011706       # 戏谑套索
LAIDA = 10011707        # 来打我呀
MENGJI = 10011708       # 萌即正义
FUXING = 10011721       # 福星高照（协战）
XINGYUN = 10011751      # 幸运兔兔
ZHIREN = 10011799       # 纸人
XIAOZHIREN = 10011798   # 小纸人

ST_TEAM = [100117, 100129, 100102, 100123]   # 座敷童子同队（幸运兔兔羁绊）


def test_countdown_power_boost_atomic(gdb, monkeypatch):
    """山兔基础能力（countdown_power_boost 原子语义）：运势6 成功——其他己方式神
    倒计时 -1 并 +1 力量；气绝者只减复活倒计时，被本次 -1 归零复活者不追加力量。"""
    g, pa, pb = _game(gdb, ST_TEAM)
    zuofu = pa.shikigami[1]
    zuofu.level = 1
    zuofu.countdown = 2                        # 手动注入倒计时数值（仅测 -1）
    dead = pa.shikigami[2]
    dead.level = 1
    g.deal_to_shikigami(Ref(player=0, shikigami=2), 99, None)
    g._drain_queue()
    dead.revive_countdown = 2                  # A 回合开始自然 -1 余 1，由山兔本次 -1 归零
    _force_dice(monkeypatch, g, [6])
    zuofu_power = zuofu.eff_power
    pass_turns(g, 2)                           # A 下回合开始：运势6 成功
    assert zuofu.countdown == 1                # 2 - 1
    assert zuofu.eff_power == zuofu_power + 1  # 存活者 +1 力量
    assert not dead.defeated                   # 被本次 -1 归零复活
    assert dead.temp_power == 0 and dead.perm_power == 0  # 归零复活者不追加力量


def test_awaken_double_independent_luck(gdb, monkeypatch):
    """觉醒·山兔：己方回合开始两次独立 [运势6] 判定（两个独立 block）——各成各败。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 2})
    s = pa.shikigami[IDX]
    play(g, 0, ST_AWAKEN)
    assert s.awakened == ST_AWAKEN
    assert s.perm_power == 1 and s.perm_health == 1
    observer = pa.shikigami[2]                 # 兵俑（无能力，不干扰判定）
    observer.level = 1
    base_power = observer.eff_power
    _force_dice(monkeypatch, g, [6, 1])        # 第一次成功、第二次失败
    pass_turns(g, 2)                           # A 下回合开始
    assert observer.eff_power == base_power + 2  # 仅第一次 +2
    assert len(pa.ext["dice_history"]) >= 2    # 两次独立判定各记一骰


def test_dice_six_ge_enhance_merges_buff(gdb):
    """送祝福增强（dice_six_ge:3）：合并为一次性 +3/+3+[迅捷] + 抽 1；不足为 +1/+1。"""
    g, pa, pb = _game(gdb, ST_TEAM)
    pa.ext["dice_six_count"] = 3
    s = pa.shikigami[IDX]
    hand_before = len(pa.hand)
    play(g, 0, SONGZHUFU, target=Ref(player=0, shikigami=IDX))
    assert s.temp_power == 3 and s.temp_health == 3
    assert "haste" in s.keywords or "haste" in s.one_shot_keywords
    assert len(pa.hand) == hand_before + 1     # give+打出抵消，抽 1
    g2, pa2, pb2 = _game(gdb, ST_TEAM)
    s2 = pa2.shikigami[IDX]
    play(g2, 0, SONGZHUFU, target=Ref(player=0, shikigami=IDX))
    assert s2.temp_power == 1 and s2.temp_health == 1


def test_transform_enemy_combat_and_enhance(gdb):
    """戏谑套索：敌方战斗区式神变形为'纸人'并抽 1；增强（三次6）改为'小纸人'
    （连续变形，transform_origin 还原到最初原式神）。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 2})
    move(g, 1, 1)                              # B 白狼入战斗区
    hand_before = len(pa.hand)
    play(g, 0, XIEXUE)
    doll = pb.shikigami[1]
    assert doll.id == ZHIREN                   # 变成纸人 3/3
    assert doll.transform_origin is not None
    assert len(pa.hand) == hand_before + 1     # 抽 1
    g2, pa2, pb2 = _game(gdb, ST_TEAM, levels={IDX: 2})
    pa2.ext["dice_six_count"] = 3
    move(g2, 1, 1)
    play(g2, 0, XIEXUE)
    assert pb2.shikigami[1].id == XIAOZHIREN   # 增强：小纸人 0/1


def test_untransform_on_controller_turn_end(gdb):
    """纸人（kind=transform 变形物）：控制者己方回合结束时变回原式神。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 2})
    move(g, 1, 1)                              # B 白狼入战斗区
    play(g, 0, XIEXUE)
    assert pb.shikigami[1].id == ZHIREN
    pass_turns(g, 2)                           # B 回合结束批次：解除变形
    assert pb.shikigami[1].id == 100101        # 还原为白狼
    assert pb.shikigami[1].in_play


def test_dice_force_six_aura(gdb):
    """萌即正义（set_dice_modifier mode=six）：结附期间投骰子总是 6
    （牌手 ext dice_force_six）；形态被替换离场后解除。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 3})
    play(g, 0, MENGJI)                         # 形态 6/6
    assert pa.ext.get("dice_force_six")
    pass_turns(g, 2)                           # A 下回合开始：山兔判定必 6
    assert pa.ext["dice_history"][-1] == 6
    assert pa.ext["dice_six_count"] >= 1
    pa.orb = 9
    play(g, 0, KUILAI)                         # 替换形态：必6 光环离场解除
    assert not pa.ext.get("dice_force_six")


def test_alt_win_game_after_ten_six(gdb, monkeypatch):
    """这把算我赢增强（十次 6）：变为"获得本局游戏胜利"且失去[瞬发]
    （alt_effects + win_game，吾即正义先例）。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 2})
    pa.ext["dice_six_count"] = 9
    _force_dice(monkeypatch, g, [6])
    pass_turns(g, 2)                           # A 下回合开始：山兔基础能力投出第 10 个 6
    assert pa.ext["dice_six_count"] >= 10
    assert pa.card_mods[ZBSWY].get("transformed")
    assert "fast" not in g._card_keywords(pa, g.db.cards[ZBSWY])
    pa.orb = 9
    play(g, 0, ZBSWY)
    assert g.state.winner == 0                 # win_game：控制者胜


def test_cost_delta_player_next_turn(gdb):
    """幸运兔兔增强（三次6，cost_delta_player scope=next_turn）：敌方下回合从手牌
    使用的卡牌鬼火消耗 +1；回合内首张[瞬发]仍免费；修正随回合号过期。"""
    g, pa, pb = _game(gdb, ST_TEAM, levels={IDX: 3})
    pa.ext["dice_six_count"] = 3
    play(g, 0, XINGYUN)                        # token 直接 give 打出（瞬发免费）
    pass_turns(g, 1)                           # B 回合
    pb.orb = 9
    play(g, 1, 10010101)                       # B 起弓[瞬发]：回合内首张瞬发仍 0 费
    assert pb.orb == 9
    play(g, 1, 10010401)                       # B 风神一扇（1 火 → 修正后 2 火；无鬼火增减效果）
    assert pb.orb == 7
    pass_turns(g, 2)                           # 再回到 B 回合：修正已随回合号过期
    pb.orb = 9
    play(g, 1, 10010401)
    assert pb.orb == 8


# ==========================================================================
# 座敷童子（100129）
# ==========================================================================

ZFTZ = 100129
JINYUN = 10012901       # 金运大吉
WUGU = 10012902         # 五谷丰壤
FUSHOU = 10012903       # 福寿双全
JIANEI = 10012904       # 家内安全
FUYUN = 10012905        # 福运昌隆
ZFTZ_AWAKEN = 10012906  # 觉醒·座敷童子
HEQI = 10012907         # 和气满满
FUMAN = 10012908        # 福满乾坤
HONGYUN = 10012951      # 鸿运当头

ZFTZ_TEAM = [100129, 100117, 100102, 100123]  # 山兔同队（鸿运当头羁绊）


def test_luck_reroll_on_dice_one(gdb, monkeypatch):
    """座敷童子基础能力（on_luck_judge 即时挂点 + luck_reroll）：判定者=己方投出 1
    时重投一次；骰子历史只记最终有效骰点。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 2})
    _force_dice(monkeypatch, g, [1, 5])        # 首投 1 → 重投 5
    play(g, 0, FUYUN)                          # 福运昌隆：抽 1；运势4 → +2 鬼火
    assert pa.ext["dice_history"] == [5]       # 被重投覆盖的首投不计入
    assert pa.orb == 9 - 1 + 2                 # 判定成功：获得 2 鬼火


def test_awaken_reroll_on_would_fail(gdb, monkeypatch):
    """觉醒·座敷童子：判定将失败时重投一次（不限于骰点 1）。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 3})
    s = pa.shikigami[IDX]
    play(g, 0, ZFTZ_AWAKEN)
    assert s.awakened == ZFTZ_AWAKEN
    assert s.perm_power == 1 and s.perm_health == 3
    _force_dice(monkeypatch, g, [2, 6])        # 运势4 首投 2（将失败）→ 重投 6
    play(g, 0, FUYUN)
    assert pa.ext["dice_history"][-1] == 6
    assert pa.orb == 9 - 1 - 1 + 2             # 觉醒 1 火 + 福运 1 火，成功 +2


def test_judge_both_each_draw(gdb, monkeypatch):
    """金运大吉（luck_roll judge=both）：进场时双方牌手各做运势4 判定，
    判定者各自抽 1；单边失败则该方不抽（当前回合玩家先）。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM)
    _force_dice(monkeypatch, g, [4, 4])
    ha, hb = len(pa.hand), len(pb.hand)
    play(g, 0, JINYUN)                         # 形态 3/6 进场
    assert len(pa.hand) == ha + 1              # give+打出抵消，己方判定成功抽 1
    assert len(pb.hand) == hb + 1              # 敌方判定成功也抽 1
    g2, pa2, pb2 = _game(gdb, ZFTZ_TEAM)
    _force_dice(monkeypatch, g2, [4, 2])       # 当前回合玩家先：A 成功、B 失败
    ha2, hb2 = len(pa2.hand), len(pb2.hand)
    play(g2, 0, JINYUN)
    assert len(pa2.hand) == ha2 + 1
    assert len(pb2.hand) == hb2                # 单边失败：不抽
    assert pa2.ext["dice_history"] == [4] and pb2.ext["dice_history"] == [2]


def test_luck_fail_branch_stuns_attacker(gdb, monkeypatch):
    """家内安全（luck {x:4, on:fail}）：式神攻击后判定失败则攻击者被[眩晕]（stun）。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 2})
    play(g, 0, JIANEI)                         # 形态 3/7
    pass_turns(g, 1)                           # B 回合
    _force_dice(monkeypatch, g, [1, 2])        # 首投 1 → 座敷基础能力重投 2（仍失败）
    g.apply({"op": "assault", "index": 0})     # B 大天狗出击
    assert pb.shikigami[0].stuns               # 普通眩晕条目


def test_luck_fail_branch_power_zero(gdb, monkeypatch):
    """和气满满（luck on:fail + power_override scope=battle）：式神攻击时判定失败——
    攻击者本次战斗力量变为 0。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 3})
    play(g, 0, HEQI)                           # 形态 0/7
    move(g, 0, IDX)                            # A 座敷驻战斗区
    pass_turns(g, 1)                           # B 回合
    _force_dice(monkeypatch, g, [2])           # 运势4 失败
    g.apply({"op": "assault", "index": 1})     # B 白狼（3 攻）出击
    assert pa.shikigami[IDX].health == 7       # 攻击力量 0：无战斗伤害


def test_form_leave_orb_only_on_replace(gdb):
    """福寿双全：进场双方各 +1 鬼火；仅形态被替换离场时再各 +1（气绝消灭不触发）。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM)
    pa.orb = 8
    pb.orb = 0
    play(g, 0, FUSHOU)                         # 1 火，进场双方 +1
    assert pa.orb == 8 and pb.orb == 1
    play(g, 0, JINYUN)                         # 替换形态：离场双方再 +1
    assert pa.orb == 8 and pb.orb == 2


def test_play_condition_gates_fumanqiankun(gdb):
    """福满乾坤[条件]（play_condition luck_success_total_ge:12）：不满足任何方式不能用
    （双方合计口径，单方 6 次不够）；满足后依次双方生命变 30、抽手牌至 10 张、各 +3 鬼火。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 3})
    with pytest.raises(IllegalAction):
        play(g, 0, FUMAN)
    pa.ext["luck_success_game"] = 6
    with pytest.raises(IllegalAction):         # 单方 6 次不够：双方合计口径
        play(g, 0, FUMAN)
    pb.ext["luck_success_game"] = 6            # 合计 12 → 可用
    pa.health = 10
    pb.orb = 0
    play(g, 0, FUMAN)
    assert pa.health == 30 and pb.health == 30
    assert len(pa.hand) == 10 and len(pb.hand) == 10
    assert pa.orb == 9 - 1 + 3
    assert pb.orb == 3


def test_bond_search_deck_by_card_id(gdb):
    """鸿运当头[羁绊]：山兔在场未气绝时从牌库检索'这把算我赢'置手
    （search_deck card_id 精确过滤）。"""
    g, pa, pb = _game(gdb, ZFTZ_TEAM, levels={IDX: 3})
    pa.shikigami[1].level = 1                  # 山兔在场未气绝
    inst = CardInstance(uid=g.state.next_uid, id=ZBSWY)  # 注入牌库供检索
    g.state.next_uid += 1
    pa.deck.append(inst)
    play(g, 0, HONGYUN)                        # token 直接 give 打出
    assert any(c.id == ZBSWY for c in pa.hand)


# ==========================================================================
# 妖狐（100130）
# ==========================================================================

YH = 100130
FENGREN = 10013001      # 风刃
JUQI = 10013002         # 聚气
AIYI = 10013003         # 爱意绵绵
MINGYUN = 10013004      # 命运之人
WUJI = 10013005         # 无羁风弹
DIEFENG = 10013006      # 叠风斩
KUANGFENG = 10013007    # 狂风刃卷
YH_AWAKEN = 10013008    # 觉醒·妖狐

YH_TEAM = [100130, 100101, 100102, 100123]


def test_spell_play_luck_random_damage(gdb, monkeypatch):
    """妖狐基础能力：妖狐使用法术牌时运势4——成功随机对一敌方角色打 2；
    伤害计数 yaohu_damage_count 每次伤害事件 +1。"""
    g, pa, pb = _game(gdb, YH_TEAM)
    _force_dice(monkeypatch, g, [4])
    before = _enemy_total(pb)
    play(g, 0, FENGREN, target=Ref(player=1, shikigami=1))
    assert before - _enemy_total(pb) == 4      # 风刃 2 + 能力 2
    assert pa.ext["yaohu_damage_count"] == 2   # 两次伤害事件（来源=妖狐）


def test_juqi_perm_bonus_via_shikigami_ext(gdb, monkeypatch):
    """聚气（bump_ext yaohu_dmg_bonus，式神 ext 通道）：基础能力伤害永久 +1，
    跨气绝保留、可累计。"""
    g, pa, pb = _game(gdb, YH_TEAM)
    s = pa.shikigami[IDX]
    play(g, 0, JUQI)                           # 瞬发：+1 并抽 1
    assert s.ext["yaohu_dmg_bonus"] == 1
    _force_dice(monkeypatch, g, [4])
    before = _enemy_total(pb)
    play(g, 0, FENGREN, target=Ref(player=1, shikigami=1))
    assert before - _enemy_total(pb) == 5      # 风刃 2 + 能力 (2+1)


def test_repeat_random_damage_stop_on_defeat(gdb, monkeypatch):
    """无羁风弹（repeat_random_damage）：双方其他未气绝式神逐次随机打 2（插入结算），
    任一式神气绝即停；无人气绝打满 10 次（合计 20 伤、池不含妖狐自身）。"""
    g, pa, pb = _game(gdb, YH_TEAM, levels={IDX: 2})
    for p in (pa, pb):
        for s in p.shikigami:
            s.level = max(s.level, 1)
            s.base_health = s.health = 50      # 撑住保证打满 10 次
    _force_dice(monkeypatch, g, [1])           # 妖狐基础能力判定失败（不干扰计数）
    yaohu_hp = pa.shikigami[IDX].health
    total_before = sum(s.health for p in (pa, pb) for s in p.shikigami)
    play(g, 0, WUJI)
    total_after = sum(max(s.health, 0) for p in (pa, pb) for s in p.shikigami)
    assert total_before - total_after == 20    # 10 次 × 2
    assert pa.shikigami[IDX].health == yaohu_hp


def test_awaken_triggers_on_spell_and_luck_success(gdb, monkeypatch):
    """觉醒·妖狐：你使用法术牌或运势判定成功时随机打一敌方角色 2
    （使用法术牌分支不依赖判定结果）。"""
    g, pa, pb = _game(gdb, YH_TEAM, levels={IDX: 3})
    s = pa.shikigami[IDX]
    play(g, 0, YH_AWAKEN)
    assert s.awakened == YH_AWAKEN
    assert s.perm_power == 2 and s.perm_health == 2
    _force_dice(monkeypatch, g, [1])           # 无判定消费（觉醒两段均无运势门控）
    before = _enemy_total(pb)
    play(g, 0, FENGREN, target=Ref(player=1, shikigami=1))
    assert before - _enemy_total(pb) == 4      # 风刃 2 + 觉醒能力 2
