"""战斗主题测试：战斗关键字（原 test_combat_keywords.py）+ 攻击后到期强化与觉醒（原 test_attack_buffs_awaken.py）。

对应 docs/rules.md 第四章（战斗流程）、第五章（伤害事件完整流程）、
"直到攻击后"（起弓/离/无我）与第十三章（觉醒替换）；
残心的 keep_attack_buffs、觉醒·兵俑的 keep_shield 同为第二批落地机制。
测试辅助卡使用衍生号段（51+，token=True）。
"""
from core.actions import ACTIONS
from core.model import Ref
from tests import factories as F
from tests.factories import CHOOSE_ENEMY, give, move

T = F.T
SELF = T(kind="self")
ENEMY_PLAYER = T(kind="all", pool="enemy_player")


# ==========================================================================
# 战斗关键字（原 test_combat_keywords.py）
# ==========================================================================

# ---------- 连击 / 先攻 ----------

def test_combo_kill_no_counter(db, make_game):
    """连击：先攻阶段消灭被攻击者，不吃反击；无贯通则战斗终止。"""
    g = make_game()
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 0)
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
    move(g, 1, 1)
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


# ==========================================================================
# 攻击后到期强化（attack_buff）与觉醒（原 test_attack_buffs_awaken.py）
# ==========================================================================

def _attack_buff_card(db, cid: int, power: int = 0, keywords=()) -> None:
    """起弓/离/无我型法术牌：[瞬发] + 攻击后到期强化。"""
    db.cards[cid] = F.card(
        cid, keywords=["fast"],
        steps=[F.Step(op="attack_buff", power=power, keywords=list(keywords), target=SELF)],
        token=True)


def _bailang_base_ability(db) -> None:
    """白狼基础能力：己方回合战斗伤害 → 敌方牌手 -2（即时时机）。"""
    db.shikigami[100101].ability = F.EffectBlock(
        when="on_damage", timing="insert",
        condition={"source_shikigami": "self", "victim_side": "enemy",
                   "victim_kind": "shikigami", "kind": "combat", "active": "self"},
        steps=[F.Step(op="damage", amount=2, target=ENEMY_PLAYER)],
    )


def _awaken_bailang(db, cid: int = 10010157) -> int:
    """觉醒·白狼：+2/+2 永久修正 + 任意伤害版白狼能力（-4）。"""
    db.cards[cid] = F.card(
        cid, level=3, subtype="awaken",
        steps=[F.Step(op="buff_power", amount=2, perm=True, target=SELF),
               F.Step(op="buff_health", amount=2, perm=True, target=SELF)],
        abilities=[F.EffectBlock(
            when="on_damage", timing="insert",
            condition={"source_shikigami": "self", "victim_side": "enemy",
                       "victim_kind": "shikigami", "active": "self"},
            steps=[F.Step(op="damage", amount=4, target=ENEMY_PLAYER)],
        )],
        token=True)
    return cid


# ---------- 攻击后到期强化 ----------

def test_attack_buff_consumed_after_own_attack(db, make_game):
    """起弓型强化：自身出击的战斗终止点核销力量与授予的关键字。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=1, keywords=["pierce"])
    g = make_game()
    move(g, 1, 0)
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert a.temp_power == 1
    assert "pierce" in a.keywords
    assert len(a.attack_buffs) == 1
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 0
    assert "pierce" not in a.keywords
    assert a.attack_buffs == []


def test_attack_buff_kept_when_attacked(db, make_game):
    """作为被攻击者的战斗不核销：强化保留到自身下一次攻击后。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=1)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    move(g, 0, 0)  # 驻留战斗区，成为敌方出击的被攻击者
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 1
    assert len(a.attack_buffs) == 1


def test_attack_buff_haste_free_assault_full_consume(db, make_game):
    """无我型强化：迅捷免鬼火出击（次数照扣），战斗后全部强化一并核销。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=3, keywords=["unyielding", "piercing", "haste"])
    g = make_game()
    pa = g.state.players[0]
    a = pa.shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    pa.orb = 0  # 迅捷：无鬼火也可出击
    g.apply({"op": "assault", "index": 0})
    assert pa.assaults_left == 0
    assert a.temp_power == 0
    assert "haste" not in a.one_shot_keywords
    assert "unyielding" not in a.one_shot_keywords
    assert "piercing" not in a.keywords
    assert a.attack_buffs == []


def test_keep_attack_buffs_survives_until_form_replaced(db, make_game):
    """残心：持有 keep_attack_buffs 时攻击后不核销；形态替换失去后，下一次攻击核销。"""
    buff_cid, form_cid, plain_cid = 10010151, 10010152, 10010153
    _attack_buff_card(db, buff_cid, power=1, keywords=["pierce"])
    db.cards[form_cid] = F.card(form_cid, card_type="form", keywords=["keep_attack_buffs"],
                                form_power=3, form_health=5, token=True)
    db.cards[plain_cid] = F.card(plain_cid, card_type="form",
                                 form_power=2, form_health=4, token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 4
    a = pa.shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, form_cid).uid})
    g.apply({"op": "play_card", "uid": give(g, 0, buff_cid).uid})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 1
    assert len(a.attack_buffs) == 1
    assert "pierce" in a.keywords
    g.apply({"op": "play_card", "uid": give(g, 0, plain_cid).uid})  # 替换形态，失去残心
    assert "keep_attack_buffs" not in a.keywords
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})
    g.apply({"op": "assault", "index": 0})
    assert a.temp_power == 0
    assert a.attack_buffs == []
    assert "pierce" not in a.keywords


def test_attack_buff_cleared_on_defeat(db, make_game):
    """气绝清账：临时力量与挂账随气绝一并清空。"""
    cid = 10010151
    _attack_buff_card(db, cid, power=3, keywords=["piercing"])
    g = make_game()
    a = g.state.players[0].shikigami[0]
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert a.defeated
    assert a.temp_power == 0
    assert a.attack_buffs == []


# ---------- 白狼基础能力 ----------

def test_base_ability_on_combat_damage(db, make_game):
    """白狼基础能力：己方回合对敌方式神造成战斗伤害，即时对敌方牌手造成 2。"""
    _bailang_base_ability(db)
    g = make_game()
    move(g, 1, 0)
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "assault", "index": 0})
    assert pl.shikigami[0].health == 1  # 吃 3 战斗伤害
    assert pl.health == 28              # 能力 -2（反击伤害来源非白狼，不再触发）


def test_base_ability_ignores_effect_damage(db, make_game):
    """白狼基础能力：法术（effect 伤害）不触发。"""
    _bailang_base_ability(db)
    cid = 10010154
    db.cards[cid] = F.card(cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True)
    g = make_game()
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid,
             "target": Ref(player=1, shikigami=0)})
    assert pl.shikigami[0].health == 1
    assert pl.health == 30  # 未触发


def test_base_ability_active_self_only(db, make_game):
    """白狼基础能力：非己方回合不触发（active: self 限定）。"""
    _bailang_base_ability(db)
    g = make_game()
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "end_turn"})  # 进入 B 的回合
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 3, Ref(player=0, shikigami=0), kind="combat")
    assert pl.shikigami[0].health == 1
    assert pl.health == 30  # 未触发


# ---------- 觉醒 ----------

def test_awaken_replaces_ability_and_perm_stats(db, make_game):
    """觉醒·白狼：+2/+2 永久修正；能力替换为任意伤害版（法术伤害也触发，伤害 4）。"""
    _bailang_base_ability(db)
    cid = _awaken_bailang(db)
    dmg_cid = 10010154
    db.cards[dmg_cid] = F.card(dmg_cid, steps=[F.dmg(3)], target=CHOOSE_ENEMY, token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 3
    a = pa.shikigami[0]
    a.level = 3
    pl = g.state.players[1]
    pl.shield = 0
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert a.perm_power == 2 and a.perm_health == 2
    assert a.health == 6
    assert a.awakened == cid
    assert "on_awakened" in g.history
    # 法术伤害也触发觉醒能力（无 kind 限定）
    g.apply({"op": "play_card", "uid": give(g, 0, dmg_cid).uid,
             "target": Ref(player=1, shikigami=0)})
    assert pl.health == 26  # 觉醒能力 -4
    # 战斗伤害触发的是 -4 的觉醒版，而非 -2 的基础版
    move(g, 1, 0)
    g.apply({"op": "assault", "index": 0})
    assert pl.health == 22


def test_awaken_persists_through_revive(db, make_game):
    """觉醒状态气绝/复活保留：永久修正与觉醒能力在复活后仍生效。"""
    cid = _awaken_bailang(db)
    g = make_game()
    a = g.state.players[0].shikigami[0]
    a.level = 3
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert a.defeated
    assert a.awakened == cid  # 气绝不清觉醒状态
    a.revive_countdown = 0
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 回合开始：复活
    assert not a.defeated
    assert a.health == 6  # 永久生命修正保留（4 + 2）
    pl = g.state.players[1]
    pl.shield = 0
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, Ref(player=0, shikigami=0), kind="combat")
    assert pl.health == 26  # 觉醒能力仍触发（-4）


def test_awaken_hyottoko_shield_kept_and_stacked(db, make_game):
    """觉醒·兵俑：打出 +3 护甲且不再于己方回合开始移除；之后每己方回合开始 +3（替换基础 +2）。"""
    db.shikigami[100102].ability = F.EffectBlock(  # 基础能力（应被觉醒替换）
        when="on_turn_start", condition={"player": "self"},
        steps=[F.Step(op="gain_shield", amount=2, target=SELF)],
    )
    cid = 10010256
    db.cards[cid] = F.card(
        cid, shikigami=100102, level=2, subtype="awaken",
        steps=[F.Step(op="gain_shield", amount=3, target=SELF),
               F.Step(op="keep_shield", target=SELF)],
        abilities=[F.EffectBlock(
            when="on_turn_start", condition={"player": "self"},
            steps=[F.Step(op="gain_shield", amount=3, target=SELF)],
        )],
        token=True)
    g = make_game()
    pa = g.state.players[0]
    pa.orb = 2
    s = pa.shikigami[1]
    s.level = 2
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    assert s.shield == 3
    assert s.keep_shield
    assert s.awakened == cid
    g.apply({"op": "end_turn"})
    g.apply({"op": "end_turn"})  # A 第 2 回合开始：护甲不清除且 +3（若基础能力仍在只 +2）
    assert s.shield == 6


# ==========================================================================
# 额外攻击 launch_attack / 反击贯通 counter_piercing（凤凰火/山童底层）
# ==========================================================================

def _launch_spell(db, cid=10010155, sid=100101, **kw):
    """额外攻击法术：令来源（或按 id 指定）式神发起一次攻击。"""
    db.cards[cid] = F.card(cid, shikigami=sid, token=True,
                           steps=[F.Step(op="launch_attack", **kw)])
    return cid


def test_launch_attack_basic(db, make_game):
    """launch_attack：不耗鬼火/出击次数，准备区自动进战斗区，空战斗区时攻击牌手。"""
    _launch_spell(db)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0                         # 清掉后手补偿护甲，便于观察数值
    F.play(g, 0, 10010155)
    assert pa.orb == 8                    # 只付卡牌费用，攻击本身不耗鬼火
    assert pa.assaults_left == 1          # 出击次数未消耗
    assert pa.combat_index == 0           # 准备区自动进战斗区
    assert pb.health == 27                # 3 力量攻击牌手


def test_launch_attack_with_counter(db, make_game):
    """launch_attack 走正常战斗流程：敌方战斗区有式神时照常吃反击。"""
    _launch_spell(db)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    move(g, 1, 0)
    F.play(g, 0, 10010155)
    assert pb.shikigami[0].health == 1    # 4 - 3
    assert pa.shikigami[0].health == 1    # 4 - 3（反击）


def test_launch_attack_by_id(db, make_game):
    """launch_attack(shikigami=int)：按数据 id 定位控制者的式神（协战羁绊式）。"""
    _launch_spell(db, cid=10010156, shikigami=100102)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0
    pa.shikigami[1].level = 1
    F.play(g, 0, 10010156)
    assert pa.combat_index == 1           # 100102（1/6）发起攻击并进战斗区
    assert pb.health == 29                # 1 力量攻击牌手


def test_launch_attack_noop(db, make_game):
    """launch_attack 空操作路径：气绝/未出战（id 不在队）不发起攻击。"""
    _launch_spell(db, cid=10010156, shikigami=100102)
    _launch_spell(db, cid=10010157, shikigami=100199)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    s = pa.shikigami[1]
    s.level = 1
    s.defeated = True
    F.play(g, 0, 10010156)                # 目标式神气绝：空操作
    F.play(g, 0, 10010157)                # 目标式神未出战：空操作
    assert pa.combat_index is None
    assert pb.health == 30


def _cp_combat_card(db, cid=10010157, steps=()):
    """测试用战斗牌（0 战力/护甲），steps 可带 counter_piercing。"""
    db.cards[cid] = F.card(cid, shikigami=100101, card_type="combat",
                           token=True, steps=list(steps))
    return cid


def test_counter_piercing_overflow_to_player(db, make_game):
    """反击贯通：本战斗反击伤害具有贯通，击杀攻击者后溢出传导至攻击方牌手。"""
    _cp_combat_card(db, steps=[F.Step(op="counter_piercing")])
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    move(g, 1, 0)
    pb.shikigami[0].perm_power = 5        # 反击 8 伤 > 攻击者 4 生命
    F.play(g, 0, 10010157)
    assert pa.shikigami[0].defeated       # 贯通修正：反击伤害锁为当前生命 4
    assert pa.health == 26                # 溢出 4 传导牌手


def test_counter_no_piercing_default(db, make_game):
    """负面对照：未登记 counter_piercing 时反击不贯通（rules.md:201 默认排除）。"""
    _cp_combat_card(db)
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    move(g, 1, 0)
    pb.shikigami[0].perm_power = 5
    F.play(g, 0, 10010157)
    assert pa.shikigami[0].defeated       # 反击 8 伤击杀（无贯通修正）
    assert pa.health == 30                # 溢出归零，不传导牌手


def test_counter_piercing_outside_battle_noop(db, make_game):
    """counter_piercing 无战斗上下文时为空操作（非战斗牌主动使用）。"""
    db.cards[10010158] = F.card(10010158, token=True,
                                steps=[F.Step(op="counter_piercing")])
    g = make_game()
    F.play(g, 0, 10010158)
    assert not g._battle_counter_piercing


def test_counter_piercing_response_insert(db, make_game):
    """响应插入使用的战斗牌：counter_piercing 作为普通动作登记到被插入的战斗。"""
    db.cards[10010159] = F.card(
        10010159, shikigami=100101, card_type="combat", keywords=["trigger"],
        token=True, when="on_before_assault",
        steps=[F.Step(op="counter_piercing")])
    g = make_game()
    pa, pb = g.state.players
    F.pass_turns(g, 1)                    # → B 第 1 回合
    move(g, 1, 0)                         # B0（100101 3/4）驻留战斗区到 A 回合
    pb.shikigami[0].perm_power = 5        # 反击 8 伤 > 攻击者 4 生命
    pb.orb = 1
    give(g, 1, 10010159)                  # 响应牌属于 B0：插入使用不把战斗区换人
    F.pass_turns(g, 1)                    # → A 第 2 回合
    g.apply({"op": "assault", "index": 0})
    assert g.state.players[1].graveyard[-1].id == 10010159  # 响应牌已使用
    assert pa.shikigami[0].defeated       # 反击击杀攻击者
    assert pa.health == 26                # 反击贯通：溢出 4 传导牌手
