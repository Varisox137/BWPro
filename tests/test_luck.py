"""运势批次机制测试（第十五阶段）：引擎层纯机制分支覆盖——觉醒翻倍（含翻倍提供者
自身除外/气绝不翻倍）、骰子修饰（six_once 消耗）、眩晕门控与解除、变形快照还原与
气绝前2、伤害数值扩展、逐次随机伤害 stop_on_defeat、再次使用。

跨层约定：与真实数据层（test_luck_cards.py）同语义的用例只保留真实数据层——
块级/步骤级门控与重投、judge=both、青蛙光环、countdown_power_boost 原子语义、
cost_delta_player、[条件] play_condition、win_game 均见 test_luck_cards.py。

骰点控制：mk_game 后把 game.rng 换成确定性桩（randint 按队列返回）。
测试辅助卡使用衍生号段（51+，token=True）——正式卡序号 01-08 已被 base_db 占满。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, give, move, pass_turns, play

T = F.T
Step = F.Step

FROG = 100113          # 青蛙瓷器（翻倍用例，引擎直读 id）
PAPER = 10010199       # 纸人式变形物
ENEMY_PLAYER = T(kind="all", pool="enemy_player")
FRIENDLY = T(kind="all", pool="friendly_shikigami")
ENEMY_SHIKI = T(kind="all", pool="enemy_shikigami")


class StubRng:
    """确定性随机桩：randint 按队列返回（耗尽返回下限 a）；choice 取首元素；
    sample 取前 n；shuffle 空操作。"""

    def __init__(self, rolls=()):
        self.rolls = list(rolls)

    def randint(self, a, b):
        return self.rolls.pop(0) if self.rolls else a

    def choice(self, seq):
        return seq[0]

    def sample(self, seq, n):
        return list(seq)[:n]

    def shuffle(self, seq):
        pass


def _luck_block_card(db, cid, luck, steps, **kw):
    """块级运势门控测试卡（EffectBlock.luck）。"""
    db.cards[cid] = F.card(cid, steps=steps, block_kw={"luck": luck}, token=True, **kw)
    return cid


def _frog_team_db(db, sid=FROG):
    """登记青蛙瓷器（含构筑用 01-04 空白卡），返回以其为 0 号位的队伍。"""
    db.shikigami[sid] = F.shiki(sid, power=3, health=6, faction="紫岩")
    for n in range(1, 5):
        db.cards[sid * 100 + n] = F.card(sid * 100 + n, shikigami=sid,
                                         level=(n - 1) % 3 + 1)
    return [sid, 100102, 100103, 100104]


def _paper(db, sid=PAPER, power=3, health=3):
    """纸人式变形物：己方回合结束解除自身变形。"""
    db.shikigami[sid] = F.shiki(
        sid, kind="transform", faction="无相", power=power, health=health,
        ability=F.block(
            Step(op="untransform", target=T(kind="self")),
            when="on_turn_end", condition={"player": "self"}))
    return sid


# ==========================================================================
# 运势管线
# ==========================================================================

def test_luck_doubling_awakened_frog(db, make_game):
    """觉醒青蛙瓷器翻倍：判定成功的运势效果执行两次；on_luck_success 延时
    handler 追加执行一次（翻倍提供者自身能力除外）；未觉醒/气绝不翻倍。"""
    team = _frog_team_db(db)
    db.cards[FROG * 100 + 8] = F.card(FROG * 100 + 8, shikigami=FROG,
                                      tags=["awaken"], token=True)  # 觉醒牌本体
    db.shikigami[100102].ability = F.block(  # 岭上开花式 on_luck_success 监听
        Step(op="draw", count=1), when="on_luck_success")
    db.cards[10010251] = F.card(
        10010251, shikigami=100102, token=True,
        steps=[Step(op="luck_roll", x=1, then=[{"op": "draw", "count": 1}])])
    g = make_game(team=team)
    g.rng = StubRng()               # 骰 1：x=1 恒成功
    a = g.state.players[0]
    a.orb = 9
    a.shikigami[1].level = 1        # 100102 在场才能监听
    h = len(a.hand)
    play(g, 0, 10010251)
    assert len(a.hand) == h + 2     # 未觉醒：then 1 次 + 监听 1 次
    a.shikigami[0].awakened = FROG * 100 + 8  # 觉醒青蛙瓷器（觉醒牌须已登记）
    h = len(a.hand)
    play(g, 0, 10010251)
    assert len(a.hand) == h + 4     # 觉醒翻倍：then 2 次 + 监听 2 次
    a.shikigami[0].health = 0       # 青蛙气绝后不再翻倍
    g.check_defeated(Ref(player=0, shikigami=0))
    a.hand.clear()                  # 避开手牌上限
    h = len(a.hand)
    play(g, 0, 10010251)
    assert len(a.hand) == h + 2


def test_set_dice_modifier(db, make_game):
    """骰子修饰：six=判定者级光环必 6（萌即正义式进场/离场开关）；
    six_once=来源级——下次以其为来源的判定首投必 6 并消耗（这把算我赢）。"""
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[Step(op="set_dice_modifier", mode="six")])
    db.cards[10010152] = F.card(10010152, token=True,
                                steps=[Step(op="set_dice_modifier", mode="six",
                                            value=False)])
    db.cards[10010153] = F.card(10010153, token=True,
                                steps=[Step(op="set_dice_modifier", mode="six_once")])
    _luck_block_card(db, 10010154, 6, [F.dmg(2, ENEMY_PLAYER)])
    g = make_game()
    g.rng = StubRng()               # 无修饰时骰 1：luck:6 恒失败
    a, b = g.state.players
    a.orb = 9
    b.shield = 0
    hp = b.health
    play(g, 0, 10010154)            # 对照：骰 1 失败
    assert b.health == hp
    play(g, 0, 10010151)            # six 生效：判定必 6
    play(g, 0, 10010154)
    assert b.health == hp - 2
    play(g, 0, 10010152)            # six 解除：恢复随机
    play(g, 0, 10010154)
    assert b.health == hp - 2
    play(g, 0, 10010153)            # six_once：同来源下次判定首投必 6
    play(g, 0, 10010154)
    assert b.health == hp - 4
    play(g, 0, 10010154)            # 已消耗：骰 1 失败
    assert b.health == hp - 4


# ==========================================================================
# 眩晕
# ==========================================================================

def test_stun_gates_and_expiry(db, make_game):
    """眩晕门控与解除时机：式神眩晕禁出牌/出击、牌手眩晕全体禁出击；
    普通眩晕在控制者下个回合结束批次解除（当回合施加的不解除）。"""
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[Step(op="stun", target=ENEMY_SHIKI)])
    db.cards[10010152] = F.card(10010152, token=True,
                                steps=[Step(op="stun", target=ENEMY_PLAYER)])
    g = make_game()
    a, b = g.state.players
    a.orb = 9
    play(g, 0, 10010151)            # A 回合眩晕 B 的 0 号位
    bs = b.shikigami[0]
    assert bs.is_stunned
    pass_turns(g, 1)                # B 回合：仍眩晕
    assert bs.is_stunned
    b.orb = 9
    with pytest.raises(IllegalAction):      # 眩晕式神不能出击
        g.apply({"op": "assault", "index": 0})
    with pytest.raises(IllegalAction):      # 眩晕式神的牌不能使用
        play(g, 1, 10010101)
    pass_turns(g, 1)                # B 回合结束：眩晕解除
    assert not bs.is_stunned
    a.orb = 9                       # 牌手眩晕：全体禁出击
    play(g, 0, 10010152)
    assert b.is_stunned
    pass_turns(g, 1)
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    pass_turns(g, 1)                # B 下个回合结束：解除
    assert not b.is_stunned


def test_stun_blocks_response(db, make_game):
    """眩晕式神不能响应使用其卡牌（响应收集与结算复查同路径）。"""
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[Step(op="stun", target=FRIENDLY)])
    db.cards[10010152] = F.card(    # 响应牌：100101 被攻击时自动使用
        10010152, card_type="combat", cost=1, keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"victim_shikigami": 100101}},
        steps=[Step(op="buff_power", amount=2, perm=True, target=T(kind="self"))])
    g = make_game()
    a, b = g.state.players
    pass_turns(g, 1)                # B 回合
    b.orb = 9
    play(g, 1, 10010151)            # B 眩晕自己的 0 号位
    give(g, 1, 10010152)            # 响应牌在手
    move(g, 1, 0)                   # B 的 0 号位入战斗区
    pass_turns(g, 1)                # A 回合
    g.apply({"op": "assault", "index": 0})  # 攻击 B 战斗区式神
    assert b.shikigami[0].perm_power == 0   # 眩晕 → 响应未触发


# ==========================================================================
# 变形
# ==========================================================================

def test_transform_and_untransform(db, make_game):
    """变形与还原：目标替换为变形物（新鲜身材、不继承增减益、继承等级）；
    变形物保留"所属式神"——原式神的牌不能使用；解除变形按快照还原。"""
    _paper(db)
    db.cards[10010151] = F.card(
        10010151, token=True, target=CHOOSE_ENEMY,
        steps=[Step(op="transform", into=PAPER)])
    g = make_game()
    a, b = g.state.players
    a.orb = 9
    bs = b.shikigami[0]
    bs.perm_power += 2              # 原式神持有增益
    bs.health = 2                   # 与伤势
    play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    paper = b.shikigami[0]
    assert paper.id == PAPER and paper.kind == "transform"
    assert paper.transform_owner == 100101          # 保留所属式神
    assert paper.perm_power == 0 and paper.health == 3  # 增减益/伤势不继承
    assert paper.level == 1                         # 等级继承
    pass_turns(g, 1)                # B 回合：原式神被变形中，其牌不能用
    b.orb = 9
    with pytest.raises(IllegalAction, match="被变形中"):
        play(g, 1, 10010101)
    pass_turns(g, 1)                # B 回合结束：纸人能力解除变形
    restored = b.shikigami[0]
    assert restored.id == 100101
    assert restored.perm_power == 2 and restored.health == 2  # 快照还原


def test_transformed_defeat_restores_origin(db, make_game):
    """变形物气绝（气绝前2）：解除变形、原式神以已气绝状态进场。"""
    _paper(db)
    db.cards[10010151] = F.card(
        10010151, token=True, target=CHOOSE_ENEMY,
        steps=[Step(op="transform", into=PAPER)])
    db.cards[10010152] = F.card(10010152, token=True, target=CHOOSE_ENEMY,
                                steps=[F.dmg(10)])
    g = make_game()
    a, b = g.state.players
    a.orb = 9
    play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    play(g, 0, 10010152, target=Ref(player=1, shikigami=0))  # 击杀纸人
    s = b.shikigami[0]
    assert s.id == 100101 and s.defeated
    assert s.transform_origin is None and s.revive_countdown > 0


# ==========================================================================
# 数值扩展与新 op
# ==========================================================================

def test_amount_ext_sources(db, make_game):
    """伤害数值扩展：amount_ext 默认读来源所属牌手 ext（谁还不听话
    dice_six_count）；amount_ext_source=shikigami 改读来源式神 ext（聚气）。"""
    db.cards[10010151] = F.card(10010151, token=True, steps=[
        Step(op="damage", amount=1, amount_ext="dice_six_count", target=ENEMY_PLAYER)])
    db.cards[10010152] = F.card(10010152, token=True, steps=[
        Step(op="damage", amount=1, amount_ext="yaohu_dmg_bonus",
             amount_ext_source="shikigami", target=ENEMY_PLAYER)])
    g = make_game()
    a, b = g.state.players
    a.orb = 9
    b.shield = 0
    a.ext["dice_six_count"] = 3
    a.shikigami[0].ext["yaohu_dmg_bonus"] = 2
    hp = b.health
    play(g, 0, 10010151)            # 1 + 3（牌手 ext）
    assert b.health == hp - 4
    play(g, 0, 10010152)            # 1 + 2（来源式神 ext）
    assert b.health == hp - 7


def test_repeat_random_damage_stop_on_defeat(db, make_game):
    """无羁风弹：逐次插入结算（每次重新求值目标池）；stop_on_defeat 时任一
    式神气绝即停；否则满 max 次即停。"""
    db.cards[10010151] = F.card(10010151, token=True, steps=[
        Step(op="repeat_random_damage", amount=1, pool="all_other_shikigami",
             max=10, stop_on_defeat=True)])
    db.cards[10010152] = F.card(10010152, token=True, steps=[
        Step(op="repeat_random_damage", amount=1, pool="all_other_shikigami",
             max=5)])
    g = make_game()
    g.rng = StubRng()               # choice 恒取首元素（来源除外的 1 号位）
    a, b = g.state.players
    a.orb = 9
    own = a.shikigami[1]
    own.level = 1
    own.health = 1                  # 一击即气绝
    hp_enemy = b.shikigami[0].health
    play(g, 0, 10010151)
    assert own.defeated             # 首次命中即气绝 → 停止
    assert b.shikigami[0].health == hp_enemy  # 未继续结算
    g2 = make_game()                # 无 stop_on_defeat：满 max 次
    g2.rng = StubRng()
    a2 = g2.state.players[0]
    a2.orb = 9
    own2 = a2.shikigami[1]
    own2.level = 1
    own2.health = 50
    play(g2, 0, 10010152)
    assert own2.health == 45        # 恰好 5 次（每次均命中序列首位）


def test_reuse_card_spell_twice(db, make_game):
    """再次使用本牌（法术）：凭空自动使用管线同目标重结算，恰好两次
    （实例标记 _reused 防自循环）；再次使用不耗鬼火。"""
    db.cards[10010151] = F.card(10010151, token=True, steps=[
        F.dmg(2, ENEMY_PLAYER), Step(op="reuse_card")])
    g = make_game()
    a, b = g.state.players
    a.orb = 9
    b.shield = 0
    hp = b.health
    play(g, 0, 10010151)
    assert b.health == hp - 4       # 首次 + 再次，恰好两次
    assert a.orb == 8               # 再次使用不耗鬼火
