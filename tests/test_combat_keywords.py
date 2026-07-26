"""战斗关键字测试：连击/先攻/贯通/穿刺/远程/不屈/迅捷/屏障/作用域免疫/多重集/伤害管线批次。

对应 docs/rules.md 第四章（战斗流程）与第五章（伤害事件完整流程）。
测试辅助卡使用衍生号段（51+，token=True）。
"""
from core.actions import ACTIONS
from core.model import Ref
from tests import factories as F
from tests.factories import give

T = F.T
CHOOSE_ENEMY = T(kind="choose", pool="enemy_shikigami")


def _move(game, player: int, index: int) -> None:
    """把式神移入战斗区（调试指令）。"""
    game.apply({"op": "debug_move", "args": {"player": player, "index": index}})


# ---------- 连击 / 先攻 ----------

def test_combo_kill_no_counter(db, make_game):
    """连击：先攻阶段消灭被攻击者，不吃反击；无贯通则战斗终止。"""
    g = make_game()
    _move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    b.health = 1
    a = g.state.players[0].shikigami[0]
    a.keywords.append("combo")
    g.apply({"op": "assault", "index": 0})
    assert b.defeated
    assert a.health == 4  # 未吃反击


def test_combo_piercing_retarget_player(db, make_game):
    """连击+贯通：先攻阶段消灭被攻击者后，交战阶段被攻击者改为敌方牌手。"""
    g = make_game()
    _move(g, 1, 0)
    pl = g.state.players[1]
    pl.shield = 0
    b = pl.shikigami[0]
    b.health = 1
    a = g.state.players[0].shikigami[0]
    a.keywords.extend(["combo", "piercing"])
    g.apply({"op": "assault", "index": 0})
    assert b.defeated
    assert pl.health == 25  # 先攻贯通溢出 2（3 - 当前生命 1）+ 交战阶段打敌方牌手 3
    assert a.health == 4


def test_combo_hits_player_twice(db, make_game):
    """连击对牌手：先攻与交战阶段各造成一次伤害。"""
    g = make_game()
    pl = g.state.players[1]
    pl.shield = 0
    a = g.state.players[0].shikigami[0]
    a.keywords.append("combo")
    g.apply({"op": "assault", "index": 0})
    assert pl.health == 24  # 两击各 3


def test_initiative_skips_clash(db, make_game):
    """先攻 initiative：先攻阶段造成伤害，交战阶段不再造成（仍吃反击）。"""
    g = make_game()
    _move(g, 1, 0)
    a = g.state.players[0].shikigami[0]
    b = g.state.players[1].shikigami[0]
    a.keywords.append("initiative")
    g.apply({"op": "assault", "index": 0})
    assert b.health == 1  # 先攻阶段 3
    assert a.health == 1  # 交战阶段反击 3，先攻方不再攻击


# ---------- 贯通 / 穿刺 / 远程 ----------

def test_piercing_overflow(db, make_game):
    """贯通：伤害超过当前生命的部分改对敌方牌手造成（同队列新事件）。"""
    g = make_game()
    _move(g, 1, 0)
    pl = g.state.players[1]
    pl.shield = 0
    b = pl.shikigami[0]
    b.health = 2
    a = g.state.players[0].shikigami[0]
    a.temp_power = 2  # 有效力量 5
    a.keywords.append("piercing")
    g.apply({"op": "assault", "index": 0})
    assert b.defeated      # 吃 2
    assert pl.health == 27  # 溢出 3


def test_piercing_ability_damage_overflow(db, make_game):
    """贯通（伤害原因）：式神持有的贯通传导至其基础/觉醒/形态能力伤害——能力伤害溢出。"""
    db.shikigami[100101].ability = F.block(
        F.dmg(5, F.T(kind="all", pool="enemy_shikigami")),
        when="on_turn_end", condition={"player": "self"}, timing="queue", mode="atomic")
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.keywords.append("piercing")
    pl = g.state.players[1]
    pl.shield = 0
    b = pl.shikigami[0]
    b.health = 2
    g.apply({"op": "end_turn"})
    assert b.defeated
    assert pl.health == 27  # 溢出 3


def test_piercing_spell_damage_no_overflow(db, make_game):
    """贯通（伤害原因）：式神持有的贯通不传导至其法术牌伤害——无溢出；
    牌面步骤显式声明 piercing 的法术伤害才溢出。"""
    db.cards[10010151] = F.card(10010151, steps=[F.dmg(5)], token=True,
                                target=CHOOSE_ENEMY)
    db.cards[10010152] = F.card(
        10010152, token=True, target=CHOOSE_ENEMY,
        steps=[F.Step(op="damage", amount=5, piercing=True)])
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.keywords.append("piercing")
    pl = g.state.players[1]
    pl.shield = 0
    b = pl.shikigami[0]
    b.health = 2
    g.apply({"op": "play_card", "uid": give(g, 0, 10010151).uid,
             "target": Ref(player=1, shikigami=0)})
    assert b.defeated
    assert pl.health == 30  # 法术伤害不继承贯通：无溢出
    # 显式声明贯通的法术：同一情形溢出
    g2 = make_game()
    g2.state.players[0].shikigami[0].keywords.append("piercing")
    pl2 = g2.state.players[1]
    pl2.shield = 0
    b2 = pl2.shikigami[0]
    b2.health = 2
    g2.apply({"op": "play_card", "uid": give(g2, 0, 10010152).uid,
              "target": Ref(player=1, shikigami=0)})
    assert b2.defeated
    assert pl2.health == 27  # 溢出 3


def test_piercing_combat_card_overflow(db, make_game):
    """贯通（伤害原因）：战斗牌本身的效果伤害不继承贯通，但其发起的战斗继承。"""
    db.cards[10010153] = F.card(10010153, card_type="combat", token=True, steps=[])
    g = make_game()
    _move(g, 1, 0)
    pl = g.state.players[1]
    pl.shield = 0
    b = pl.shikigami[0]
    b.health = 2
    a = g.state.players[0].shikigami[0]
    a.keywords.append("piercing")
    g.apply({"op": "play_card", "uid": give(g, 0, 10010153).uid})
    assert b.defeated       # 战斗伤害 3 吃 2
    assert pl.health == 29  # 溢出 1


def test_distribute_damage_flow(db, make_game):
    """随机分配伤害：总计 x 点逐 1 点随机分配；已标记气绝（生命≤0）目标不再是合法
    目标（无合法目标则后续重复落空）；气绝事件延后到效果结束后统一结算。"""
    db.cards[10010154] = F.card(
        10010154, token=True,
        steps=[F.Step(op="distribute_damage", amount=5, pool="enemy_shikigami")])
    # 单一目标 2 血：吃 2 点标记气绝后退出分配，第 3 点起落空
    g = make_game()
    pl = g.state.players[1]
    b = pl.shikigami[0]
    b.health = 2
    g.apply({"op": "play_card", "uid": give(g, 0, 10010154).uid})
    assert b.health == 0   # 不会被打成负数（标记气绝后不再是合法目标）
    assert b.defeated      # 效果结束后气绝事件已统一结算
    # 双目标分配：总伤害 5 全部分配完毕、无目标生命被打成负数
    g2 = make_game()
    pl2 = g2.state.players[1]
    pl2.shikigami[1].level = 1
    h0, h1 = pl2.shikigami[0].health, pl2.shikigami[1].health
    g2.apply({"op": "play_card", "uid": give(g2, 0, 10010154).uid})
    lost = (h0 - pl2.shikigami[0].health) + (h1 - pl2.shikigami[1].health)
    assert lost == 5       # 5 点全部分配（两目标总生命足够）
    assert pl2.shikigami[0].health >= 0 and pl2.shikigami[1].health >= 0


def test_pierce_strips_shield(db, make_game):
    """穿刺：造成伤害前移除受伤者所有护甲（经护甲变化事件）。"""
    g = make_game()
    _move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    b.shield = 3
    a = g.state.players[0].shikigami[0]
    a.keywords.append("pierce")
    g.apply({"op": "assault", "index": 0})
    assert b.shield == 0
    assert b.health == 1  # 护甲被移除后吃满 3
    assert a.health == 1  # 反击照常


def test_pierce_strips_barrier(db, make_game):
    """穿刺：造成伤害前同时移除受伤者的所有屏障实例，此后正常受伤。"""
    g = make_game()
    _move(g, 1, 0)
    b = g.state.players[1].shikigami[0]
    b.shield = 3
    b.one_shot_keywords.append("barrier")
    a = g.state.players[0].shikigami[0]
    a.keywords.append("pierce")
    g.apply({"op": "assault", "index": 0})
    assert b.shield == 0
    assert "barrier" not in b.one_shot_keywords
    assert b.health == 1  # 屏障已被剥离，不再经伤害管线批次 3 抵消


def test_pierce_applies_to_effect_damage(db, make_game):
    """穿刺：适用于任意来源伤害（含非战斗）——效果伤害同样在造成伤害前移除护甲/屏障。"""
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.keywords.append("pierce")
    b = g.state.players[1].shikigami[0]
    b.shield = 3
    b.one_shot_keywords.append("barrier")
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, Ref(player=0, shikigami=0))
    assert b.shield == 0
    assert "barrier" not in b.one_shot_keywords
    assert b.health == 2  # 护甲/屏障被剥离，2 点全吃


def test_pierce_strips_despite_immunity(db, make_game):
    """穿刺：即使受伤者免疫此次伤害，护甲/屏障仍被移除（与伤害是否生效无关）。"""
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.keywords.append("pierce")
    b = g.state.players[1].shikigami[0]
    b.shield = 3
    b.one_shot_keywords.append("barrier")
    g._battle_stack.append(1)
    b.immunities.append({"kind": "combat_damage", "battle": 1, "nested": False})
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 5, Ref(player=0, shikigami=0),
                        kind="combat")
    assert b.shield == 0
    assert "barrier" not in b.one_shot_keywords
    assert b.health == 4  # 免疫：未受伤


def test_remote_no_counter_no_move(db, make_game):
    """远程：不受反击伤害，且不进入战斗区。"""
    g = make_game()
    _move(g, 1, 0)
    pa = g.state.players[0]
    a = pa.shikigami[0]
    a.keywords.append("remote")
    g.apply({"op": "assault", "index": 0})
    b = g.state.players[1].shikigami[0]
    assert b.health == 1           # 攻击生效
    assert a.health == 4           # 不吃反击
    assert pa.combat_index is None  # 远程不移动


# ---------- 不屈 / 迅捷 / 屏障 ----------

def test_unyielding_one_shot_consumed(db, make_game):
    """不屈（一次性）：生命>1 受致命伤害保留 1 点生命，全部一次性不屈一并消耗。"""
    g = make_game()
    b = g.state.players[1].shikigami[0]
    b.health = 3
    b.one_shot_keywords.extend(["unyielding", "unyielding"])  # 复数不屈同时触发
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 5, None)
    assert b.health == 1 and not b.defeated
    assert "unyielding" not in b.one_shot_keywords


def test_unyielding_continuous_retrigger(db, make_game):
    """不屈（持续性）：触发后不移除，回血后可再次触发。"""
    g = make_game()
    b = g.state.players[1].shikigami[0]
    b.health = 3
    b.keywords.append("unyielding")
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 5, None)
    assert b.health == 1
    assert "unyielding" in b.keywords  # 持续不屈不移除
    b.health = 3  # 效果恢复了剩余生命
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 5, None)
    assert b.health == 1  # 再次触发
    assert "unyielding" in b.keywords


def test_unyielding_ignored_at_1_hp(db, make_game):
    """不屈：生命 = 1 时不触发，致命伤害照常气绝（不屈随气绝清除）。"""
    g = make_game()
    b = g.state.players[1].shikigami[0]
    b.health = 1
    b.one_shot_keywords.append("unyielding")
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 3, None)
    assert b.defeated
    assert "unyielding" not in b.one_shot_keywords  # 气绝清除，非触发消耗


def test_haste_free_assault(db, make_game):
    """迅捷：出击不消耗鬼火、移除一个一次性迅捷；出击次数照扣。"""
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 0  # 无鬼火也可出击
    a = pa.shikigami[0]
    a.one_shot_keywords.append("haste")
    g.apply({"op": "assault", "index": 0})
    assert pa.orb == 0
    assert pa.assaults_left == 0
    assert "haste" not in a.one_shot_keywords


def test_barrier_zeroes_damage(db, make_game):
    """屏障（一次性）：护甲计算前将伤害值改为 0 并移除一个屏障实例。"""
    cid = 10010152
    db.cards[cid] = F.card(cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True)
    g = make_game()
    b = g.state.players[1].shikigami[0]
    b.one_shot_keywords.append("barrier")
    pa = g.state.players[0]
    pa.orb = 2
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    assert b.health == 4
    assert "barrier" not in b.one_shot_keywords
    assert "on_damage" not in g.history  # 伤害值 0：终止结算
    c2 = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c2.uid, "target": Ref(player=1, shikigami=0)})
    assert b.health == 1  # 屏障已消耗，正常受伤


# ---------- 关键字多重集 / 授予通路 ----------

def test_keyword_multiset_grant(db, make_game):
    """多重集：战斗后只移除战斗牌授予的那个实例，式神原有同名关键字保留。"""
    cid = 10010153
    db.cards[cid] = F.card(cid, card_type="combat", keywords=["piercing"], steps=[], token=True)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.keywords.append("piercing")  # 式神原本就具有贯通
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid})
    assert a.keywords.count("piercing") == 1


def test_scoped_combat_immunity(db, make_game):
    """作用域战斗伤害免疫：免疫本战斗的反击；effect 伤害不免疫；战后条目清除。"""
    cid = 10010154
    db.cards[cid] = F.card(
        cid, card_type="combat",
        steps=[F.Step(op="battle_immunity", target=T(kind="self"), nested=True)],
        token=True)
    # B 1 号（100102）能力：（被）攻击时对攻击者造成 1 点效果伤害——不应被免疫
    db.shikigami[100102].ability = F.EffectBlock(
        when="on_before_assault",
        steps=[F.Step(op="damage", amount=1, target=T(kind="context", key="attacker"))],
    )
    g = make_game()
    pb = g.state.players[1]
    pb.shikigami[1].level = 1  # 能力持有者在场
    _move(g, 1, 1)
    a = g.state.players[0].shikigami[0]
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid})
    b = pb.shikigami[1]  # 1/6
    assert b.health == 3   # 吃攻击 3
    assert a.health == 3   # effect 伤害 1 不免疫；反击（1 攻）被免疫
    assert a.immunities == []  # 战斗结束条目清除


def test_form_keyword_grant(db, make_game):
    """形态授予：结附期间持有形态牌关键字，形态离场按实例移除。"""
    cid, cid2 = 10010155, 10010156
    db.cards[cid] = F.card(cid, card_type="form", keywords=["combo"],
                           form_power=3, form_health=5, token=True)
    db.cards[cid2] = F.card(cid2, card_type="form", form_power=2, form_health=4, token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 2
    a = pa.shikigami[0]
    c = give(g, 0, cid)
    g.apply({"op": "play_card", "uid": c.uid})
    assert "combo" in a.keywords
    c2 = give(g, 0, cid2)
    g.apply({"op": "play_card", "uid": c2.uid})  # 替换形态
    assert "combo" not in a.keywords


# ---------- 伤害管线时点批次 ----------

def test_damage_pipeline_batches(db, make_game):
    """伤害批次顺序与监听者改伤害值：on_before_shield 的监听者可改写 damage.amount。"""

    def _set_damage(game, ctx, *, targets, value):
        ctx.event["damage"].amount = value

    ACTIONS["test_set_damage"] = _set_damage
    db.shikigami[100102].ability = F.EffectBlock(
        when="on_before_shield",
        steps=[F.Step(op="test_set_damage", value=1)],
    )
    g = make_game()
    pb = g.state.players[1]
    pb.shikigami[1].level = 1  # 能力持有者在场（1/6）
    g.deal_to_shikigami(Ref(player=1, shikigami=1), 3, None)
    assert pb.shikigami[1].health == 5  # 伤害被监听者改为 1
    batches = ["on_damage_start", "on_before_shield", "on_after_shield",
               "on_before_health", "on_damage"]
    seen = [e for e in g.history if e in batches]
    assert seen == batches
