"""运势批次机制测试：引擎层纯机制分支覆盖——觉醒翻倍（含翻倍提供者
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



# ----------眩晕条件 / on_stun 事件 / 永续变形 / 生成替换 / 自动使用 ----------

SID = 100101


def test_chosen_stunned_two_branch(db, make_game):
    """崩雪型两段分支：{chosen_stunned} 按选择目标是否眩晕分流（已眩晕→伤害，否则→眩晕）。"""
    cid = 10010161
    db.cards[cid] = F.card(cid, token=True, target=CHOOSE_ENEMY, steps=[
        Step(op="damage", amount=2, target=CHOOSE_ENEMY,
             condition={"chosen_stunned": True}),
        Step(op="stun", target=CHOOSE_ENEMY,
             condition={"chosen_stunned": False}),
    ])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    tgt = Ref(player=1, shikigami=0)
    play(g, 0, cid, target=tgt)
    assert b.is_stunned and b.health == 4          # 未眩晕 → 眩晕分支
    play(g, 0, cid, target=tgt)
    assert b.health == 2 and len(b.stuns) == 1     # 已眩晕 → 伤害分支（不重复眩晕）


def test_combat_opponent_stunned_battle_grants(db, make_game):
    """雪走型战斗条件授予：{defender_stunned} 满足时获得[连击]与战斗免疫（战斗终止点
    移除）；{combat_opponent_stunned} 在 on_before_assault 载荷上双向判定。"""
    cid = 10010162
    db.cards[cid] = F.card(cid, card_type="combat", token=True, steps=[
        Step(op="grant_keyword", keyword="combo", target=T(kind="self"),
             condition={"defender_stunned": True}),
        Step(op="battle_immunity", target=T(kind="self"),
             condition={"defender_stunned": True}),
    ])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    b.health = 20
    b.stuns.append({"kind": "normal", "turn": 0})
    move(g, 1, 0)
    play(g, 0, cid)                                # 对眩晕者：连击两段 + 免疫反击
    a = pa.shikigami[0]
    assert b.health == 14                          # 3 × 2 段
    assert a.health == 4                           # 免疫战斗/反击伤害
    assert "combo" not in a.keywords and not a.immunities  # 终止点移除
    # combat_opponent_stunned 双向：持有者作为被攻击方、攻击者眩晕时亦命中
    vic = Ref(player=0, shikigami=0)
    assert g._match({"combat_opponent_stunned": True},
                    {"attacker": Ref(player=1, shikigami=0), "victim": vic},
                    0, holder=vic)
    assert not g._match({"combat_opponent_stunned": True},
                        {"attacker": vic, "victim": Ref(player=1, shikigami=1)},
                        0, holder=vic)             # 交战对方未眩晕：不命中
    # 对非眩晕者：无授予
    b2 = pb.shikigami[1]
    b2.level = 1
    b2.health = 20
    pass_turns(g, 2)
    move(g, 1, 1)
    play(g, 0, cid)
    assert b2.health == 17                         # 仅一段
    assert a.health == 3                           # 反击（100102 力量 1）照受


def test_on_stun_event_per_turn_gate(db, make_game):
    """雪国之子型：on_stun 事件（眩晕实际施加后按即时时机发出）+ turn_mark 回合门——
    每回合首次眩晕敌方式神时生成一张牌，跨回合重置。"""
    token = 10010163
    db.cards[token] = F.card(token, token=True)
    db.shikigami[SID] = F.shiki(SID, ability=F.block(
        Step(op="turn_mark", key="yukiguni", target=T(kind="self")),
        Step(op="generate", card_id=token, target=T(kind="self")),
        when="on_stun", condition={"turn_mark_not": "yukiguni"}))
    stun_card = 10010164
    db.cards[stun_card] = F.card(stun_card, token=True, target=CHOOSE_ENEMY,
                                 steps=[Step(op="stun", target=CHOOSE_ENEMY)])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shikigami[1].level = 1
    n0 = len(pa.hand)
    play(g, 0, stun_card, target=Ref(player=1, shikigami=0))
    assert len(pa.hand) == n0 + 1
    assert any(c.id == token for c in pa.hand)
    play(g, 0, stun_card, target=Ref(player=1, shikigami=1))
    assert len(pa.hand) == n0 + 1                  # 同回合第二次：回合门拦截
    pass_turns(g, 2)
    n1 = len(pa.hand)                          # 己方回合开始抽牌后
    play(g, 0, stun_card, target=Ref(player=1, shikigami=0))
    assert len(pa.hand) == n1 + 1              # 跨回合重置后可再触发


def test_replace_keeps_seat_level_and_original_cards(db, make_game):
    """式神替换（觉醒·番茄型 replace op）：替换物继承座次与原式神当前等级、无快照
    不还原（untransform 空操作、气绝前2 跳过）；可使用原式神的全部卡牌（法术牌与
    战斗牌均可，以替换物座次为来源）——与变形"不能使用原式神卡牌"相区别；
    派系 = 替换物 def 自身 faction。"""
    tom = 10010198
    db.shikigami[tom] = F.shiki(tom, kind="replace", name="番茄", power=3, health=3,
                                faction="紫岩")
    rep = 10010165
    db.cards[rep] = F.card(rep, token=True, steps=[
        Step(op="replace", into=tom, target=T(kind="self"))])
    combat = 10010166
    db.cards[combat] = F.card(combat, card_type="combat", token=True)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pa.shikigami[0].level = 2                        # 原式神当前等级
    play(g, 0, rep)
    s = pa.shikigami[0]
    assert s.id == tom and s.kind == "replace"
    assert s.level == 2                              # 继承原式神当前等级
    assert s.transform_origin is None                # 无快照/不还原
    assert s.ext["replace_owner"] == SID
    assert s.faction == "紫岩"                        # 派系 = 替换物 def 自身（非原式神）
    g._untransform(0, 0)
    assert pa.shikigami[0].id == tom                 # 替换不是变形：不还原
    # 原式神的法术牌可用（等级门控按替换物继承的等级；不再仅限战斗牌）
    play(g, 0, SID * 100 + 2)
    assert any(c.id == SID * 100 + 2 for c in pa.graveyard)
    # 原式神的战斗牌可用（以替换物座次为来源）
    pb.shikigami[0].health = 20
    pb.shikigami[0].base_power = 0                   # 免反击干扰
    move(g, 1, 0)
    play(g, 0, combat)
    assert pb.shikigami[0].health == 17              # 替换物 3 战力
    # 气绝不还原（气绝前2 无快照跳过）：替换物气绝即气绝，复活仍为替换物
    s = pa.shikigami[0]
    s.health = 0
    g.check_defeated(Ref(player=0, shikigami=0))
    assert pa.shikigami[0].defeated and pa.shikigami[0].id == tom
    assert pa.shikigami[0].revive_countdown > 0


def test_replace_coexists_with_summon_and_awaken_stats(db, make_game):
    """觉醒·番茄型觉醒增益时序与同名共存：替换在效果块第①步发生，觉醒后结算的
    awaken_power/health 永久增益落到同座次替换物上；觉醒番茄（替换物）与召唤番茄
    （召唤物同名）可同时在场。"""
    tom_t, tom_s = 10010198, 10010199
    db.shikigami[tom_t] = F.shiki(tom_t, kind="replace", name="番茄", power=3, health=3)
    db.shikigami[tom_s] = F.shiki(tom_s, kind="summon", name="番茄", power=3, health=3)
    aw = 10010167
    db.cards[aw] = F.card(aw, token=True, subtype="awaken", level=3,
                          awaken_power=3, awaken_health=3, steps=[
        Step(op="replace", into=tom_t, target=T(kind="self"))])
    sumc = 10010168
    db.cards[sumc] = F.card(sumc, token=True, steps=[
        Step(op="summon", shikigami=tom_s)])
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 9
    pa.shikigami[0].level = 3
    play(g, 0, aw)
    s = pa.shikigami[0]
    assert s.id == tom_t
    assert s.perm_power == 3 and s.perm_health == 3  # +3/+3 落到替换物
    assert s.health == 6                             # 上限上调同步当前生命（3+3）
    play(g, 0, sumc)                                 # 召唤同名番茄：独立实体同时在场
    idx = len(pa.shikigami) - 1
    assert pa.shikigami[idx].id == tom_s and pa.shikigami[idx].kind == "summon"
    assert pa.shikigami[0].id == tom_t and pa.shikigami[0].in_play


def test_gen_replace_and_replace_cards(db, make_game):
    """觉醒·番茄型生成替换与一次性换牌：generate 经钩子把该式神非战斗牌
    改出战斗牌；手牌/牌库中的非战斗牌一次性随机替换为战斗牌。"""
    for n in (9, 10, 11):
        db.cards[SID * 100 + n] = F.card(SID * 100 + n, card_type="combat", level=1)
    awaken = 10010167
    db.cards[awaken] = F.card(awaken, token=True, steps=[
        Step(op="gen_replace", target=T(kind="self")),
        Step(op="replace_cards", target=T(kind="self"))])
    gen_card = 10010168
    db.cards[gen_card] = F.card(gen_card, token=True, steps=[
        Step(op="generate", shikigami=SID, card_type="spell", target=T(kind="self"))])
    g = make_game()
    g.rng = StubRng()                              # choice 取首元素 = 10010109
    pa = g.state.players[0]
    pa.orb = 9
    pa.hand.clear()
    pa.deck.clear()
    give(g, 0, SID * 100 + 1)                      # 手牌两张法术
    give(g, 0, SID * 100 + 5)
    d1 = give(g, 0, SID * 100 + 6)
    g.move_card(pa, d1, "deck")                    # 牌库一张法术
    play(g, 0, awaken)
    assert [c.id for c in pa.hand] == [SID * 100 + 9, SID * 100 + 9]
    assert [c.id for c in pa.deck] == [SID * 100 + 9]
    # 生成替换钩子：之后 generate 该式神法术牌改出战斗牌
    pa.hand.clear()
    play(g, 0, gen_card)
    assert pa.hand[-1].id == SID * 100 + 9


def test_auto_use_inherit_target_and_snowball_count(db, make_game):
    """流霰型：repeat {"ext": snowball_used_game, "base": 1} 重复自动使用——
    继承本牌选择目标、不耗鬼火、凭空使用不经手牌记账。"""
    snow = 10010169
    db.cards[snow] = F.card(snow, tags=["snowball"], token=True,
                            target=CHOOSE_ENEMY, steps=[F.dmg(1, CHOOSE_ENEMY)])
    liuxian = 10010170
    db.cards[liuxian] = F.card(liuxian, token=True, target=CHOOSE_ENEMY, steps=[
        Step(op="repeat", count={"ext": "snowball_used_game", "base": 1}, steps=[
            {"op": "auto_use", "card_id": snow, "inherit_target": True,
             "target": {"kind": "self"}}], target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    b.health = 30
    tgt = Ref(player=1, shikigami=0)
    play(g, 0, liuxian, target=tgt)
    assert b.health == 29                          # 基础 1 次（继承目标）
    play(g, 0, snow, target=tgt)                   # 手牌使用雪球：记账
    assert pa.ext["snowball_used_game"] == 1
    assert b.health == 28
    play(g, 0, liuxian, target=tgt)
    assert b.health == 26                          # base 1 + 已用 1 = 2 次
    assert pa.ext["snowball_used_game"] == 1       # 凭空自动使用不计账


def test_auto_use_from_hand_all_copies(db, make_game):
    """流霰 20191212 型（auto_use from_hand）：手牌全部同名牌逐张免费自动使用——
    目标强制继承本牌选择目标（可为牌手/己方角色，无视该牌自身限制）、离开手牌
    进墓地、计入从手牌使用记账、不耗鬼火；无同名牌时空操作（定案(1)）。"""
    snow = 10010169
    db.cards[snow] = F.card(snow, tags=["snowball"], token=True,
                            target=CHOOSE_ENEMY, steps=[F.dmg(1, CHOOSE_ENEMY)])
    liuxian = 10010170
    db.cards[liuxian] = F.card(liuxian, token=True,
                               target=T(kind="choose", pool="any_character"), steps=[
        Step(op="auto_use", card_id=snow, from_hand=True, inherit_target=True,
             target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 3
    s1, s2 = give(g, 0, snow), give(g, 0, snow)
    play(g, 0, liuxian, target=Ref(player=1))      # 目标为敌方牌手
    assert pb.shield == 3 and pb.health == 30      # 两张雪球各 1 点（强制命中牌手，护甲吸收）
    assert pa.ext["snowball_used_game"] == 2       # 从手牌使用：计入记账
    assert s1 in pa.graveyard and s2 in pa.graveyard
    assert all(c.id != snow for c in pa.hand)
    assert pa.orb == 2                             # 仅流霰本身耗 1 火
    give(g, 0, snow)
    own = Ref(player=0, shikigami=0)
    hp = pa.shikigami[0].health
    play(g, 0, liuxian, target=own)                # 目标为己方式神（无视雪球敌方限制）
    assert pa.shikigami[0].health == hp - 1
    assert pa.ext["snowball_used_game"] == 3
    play(g, 0, liuxian, target=Ref(player=1))      # 手牌无雪球：空操作（仍需目标）
    assert pb.shield == 3 and pb.health == 30



# ----------眩晕存在性/计数通道（雪童子批次） ----------

def test_conditional_keyword_enemy_stunned_nonempty(db, make_game):
    """霜舞型条件瞬发：场上有[眩晕]的敌方角色时此牌获得[瞬发]（活局面判定，
    眩晕的敌方牌手也算"角色"）。"""
    cid = 10010185
    db.cards[cid] = F.card(cid, card_type="combat", token=True,
                           conditional_keywords=[{"keyword": "fast",
                                                  "enemy_stunned_nonempty": True}])
    g = make_game()                              # 无眩晕：不获得瞬发，正常耗火
    pa, pb = g.state.players
    pa.orb = 2
    pb.shikigami[0].base_power = 0
    move(g, 1, 0)
    play(g, 0, cid)
    assert pa.orb == 1
    g = make_game()                              # 敌方式神眩晕：瞬发免费
    pa, pb = g.state.players
    pa.orb = 1
    pb.shikigami[0].base_power = 0
    pb.shikigami[0].stuns.append({"kind": "normal", "turn": 0})
    move(g, 1, 0)
    play(g, 0, cid)
    assert pa.orb == 1 and pa.fast_used
    g = make_game()                              # 敌方牌手眩晕：同样满足
    pa, pb = g.state.players
    pa.orb = 1
    pb.shikigami[0].base_power = 0
    pb.ext["stuns"] = [{"kind": "normal", "turn": 0}]
    move(g, 1, 0)
    play(g, 0, cid)
    assert pa.orb == 1


def test_stat_aura_enemy_stunned_exists(db, make_game):
    """雪国之子型条件身材光环：形态在场且场上有[眩晕]的敌方角色时 +2/+2
    （活局面——全部解除即失去；形态离场光环移除）。"""
    cid = 10010186
    db.cards[cid] = F.card(cid, card_type="form", form_power=5, form_health=5,
                           token=True, steps=[
        Step(op="stat_aura", kind="enemy_stunned_exists", power=2, health=2,
             target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    s = pa.shikigami[0]
    play(g, 0, cid)
    assert s.eff_power == 5 and s.max_health == 5  # 无眩晕：无加成
    pb.shikigami[0].stuns.append({"kind": "normal", "turn": 0})
    g._refresh_stat_auras()
    assert s.eff_power == 7 and s.max_health == 7  # 有眩晕：+2/+2
    pb.shikigami[0].stuns.clear()
    g._refresh_stat_auras()
    assert s.eff_power == 5 and s.max_health == 5  # 眩晕解除即失去
    pb.shikigami[0].stuns.append({"kind": "normal", "turn": 0})
    g._destroy_form(pa, 0, reason="test")
    g._refresh_stat_auras()
    assert s.eff_power == 3                        # 形态离场光环移除（基础 3）


def test_step_amount_enemy_stunned_count(db, make_game):
    """霜天之织型活局增强：战力 = base + 场上眩晕的敌方角色数
    （{"enemy_stunned_count": true}，战力提取同源求值，解除即减）。"""
    cid = 10010187
    db.cards[cid] = F.card(cid, card_type="combat", token=True, steps=[
        Step(op="buff_power", amount={"base": 2, "enemy_stunned_count": True},
             target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b = pb.shikigami[0]
    b.health = 30
    b.base_power = 0                               # 免反击干扰
    pb.shikigami[1].level = 1
    move(g, 1, 0)
    play(g, 0, cid)                                # 无眩晕：3+2=5
    assert b.health == 25
    b.stuns.append({"kind": "normal", "turn": pb.turn_count})
    pb.shikigami[1].stuns.append({"kind": "normal", "turn": pb.turn_count})
    play(g, 0, cid)                                # 2 名眩晕：3+2+2=7
    assert b.health == 18
    pb.shikigami[1].stuns.clear()
    play(g, 0, cid)                                # 解除 1 名：3+2+1=6
    assert b.health == 12


def test_combat_temp_grant_splash_stunned_exclude_victim(db, make_game):
    """胧月雪华斩型溅射：造成战斗伤害时对所有其他[眩晕]的敌方角色造成等量伤害
    （全体眩晕池 exclude_victim 排除受伤者；溅射为效果伤害不自链；
    [连击]第二段同样溅射——temp_grants uses 覆盖）。"""
    cid = 10010188
    tg = F.block(
        Step(op="damage", amount={"event": "amount"},
             target=T(kind="all", pool="enemy_character", stunned=True,
                      exclude_victim=True)),
        when="on_damage", condition={"source_shikigami": "self", "kind": "combat"},
        uses=99)
    db.cards[cid] = F.card(cid, card_type="combat", token=True, temp_grants=[tg],
                           steps=[Step(op="buff_power", amount=3, target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    b0, b1, b2 = pb.shikigami[0], pb.shikigami[1], pb.shikigami[2]
    b0.base_power = 0                              # 免反击干扰
    b0.health = 30
    for s in (b1, b2):
        s.level = 1
        s.health = 20
        s.stuns.append({"kind": "normal", "turn": pb.turn_count})
    move(g, 1, 0)
    play(g, 0, cid)                                # 战力 6 打 b0；溅射 b1/b2 各 6
    assert b0.health == 24
    assert b1.health == 14 and b2.health == 14
    b0.stuns.append({"kind": "normal", "turn": pb.turn_count})
    play(g, 0, cid)                                # 受伤者眩晕：exclude_victim 排除
    assert b0.health == 18                         # 仅战斗伤害（不受二次溅射）
    assert b1.health == 8 and b2.health == 8
    pa.shikigami[0].keywords.append("combo")
    b1.health = b2.health = 20
    play(g, 0, cid)                                # [连击]两段：每段各溅射一次（uses 覆盖）
    assert b0.health == 6
    assert b1.health == 8 and b2.health == 8       # 两段各溅射 6


def test_form_power_enemy_stun_game_counter(db, make_game):
    """雪融之时型累计增强：敌方角色被[眩晕]引擎记账（ext enemy_stunned_game，
    不分来源），形态光环 ext_power 读取时求值——进场前眩晕计入、己侧被眩晕
    记到对方、形态离场光环移除。"""
    stun_card = 10010189
    db.cards[stun_card] = F.card(stun_card, token=True, target=CHOOSE_ENEMY,
                                 steps=[Step(op="stun", target=CHOOSE_ENEMY)])
    form = 10010190
    db.cards[form] = F.card(form, card_type="form", form_power=5, form_health=7,
                            token=True, steps=[
        Step(op="stat_aura", kind="ext_power", ext="enemy_stunned_game", power=1,
             target=T(kind="self"))])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shikigami[1].level = 1
    play(g, 0, stun_card, target=Ref(player=1, shikigami=0))
    play(g, 0, stun_card, target=Ref(player=1, shikigami=1))
    assert pa.ext["enemy_stunned_game"] == 2       # 打出前已累计
    play(g, 0, form)
    s = pa.shikigami[0]
    assert s.eff_power == 7                        # 5 + 2（进场前的眩晕计入）
    play(g, 0, stun_card, target=Ref(player=1, shikigami=0))
    g._refresh_stat_auras()
    assert s.eff_power == 8                        # 进场后再眩晕：+1
    own_stun = 10010191
    db.cards[own_stun] = F.card(
        own_stun, token=True, target=T(kind="choose", pool="friendly_shikigami"),
        steps=[Step(op="stun", target=T(kind="choose", pool="friendly_shikigami"))])
    pa.shikigami[1].level = 1
    play(g, 0, own_stun, target=Ref(player=0, shikigami=1))
    g._refresh_stat_auras()
    assert s.eff_power == 8                        # 己侧被眩晕不计入
    assert pb.ext["enemy_stunned_game"] == 1       # 记到对方
    g._destroy_form(pa, 0, reason="test")
    g._refresh_stat_auras()
    assert s.eff_power == 3                        # 形态离场光环移除（基础 3）
