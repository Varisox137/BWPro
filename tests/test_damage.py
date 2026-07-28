"""破甲（负 shield）/ 治疗管线 / 吸血 / 濒死与气绝前 1 测试（A3/A4/A5）。

对应 docs/rules.md 第五章（伤害流程批次 4 破甲计算、批次 10① 吸血）、
第六章（护甲/破甲变化事件流程）、第七章（气绝前/消灭前 1）与
thoughts.txt（治疗流程、濒死/已气绝定义、答复 (3)(5)）。
0 号位（100101）为测试主体式神；破甲以 shield 负值表示。
"""
from core import targets
from core.engine import _DamageEvent
from core.model import Ref
from tests import factories as F
from tests.factories import give, move, pass_turns, play

T = F.T
SID = 100101
IDX = 0


def _game(make_game):
    g = make_game()
    pa, pb = g.state.players
    pa.orb = 9
    pb.shield = 0  # 清掉后手补偿护甲，便于观察数值
    return g, pa, pb


def _shield_spell(db, cid, amount, kind="shield", pool="self_player"):
    """一张改变自身（或目标池）护甲/破甲的法术。"""
    target = T(kind="self") if pool == "self" else T(kind="all", pool=pool)
    db.cards[cid] = F.card(
        cid, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="gain_shield", amount=amount, kind=kind, target=target)])
    return cid


def _dying(g, pi=0, si=IDX):
    """通过延时气绝的伤害队列让目标进入自然濒死窗口（生命 ≤0、气绝事件未结算）。"""
    deferred = []
    g._run_damage_queue([_DamageEvent(source=None, victim=Ref(player=pi, shikigami=si),
                                      amount=99)], defer_defeats=deferred)
    return deferred


# ---------- 破甲：变化四组合与反向抵消（rules.md ch6） ----------

def test_shield_gain_loss_clamped(db, make_game):
    """获得/失去护甲：失去只能扣已有的同向值（不能减到反向、不持有则终止）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    g._change_shield(Ref(player=0, shikigami=IDX), 3, "test")
    assert s.shield == 3
    g._change_shield(Ref(player=0, shikigami=IDX), -2, "test")
    assert s.shield == 1
    g._change_shield(Ref(player=0, shikigami=IDX), -5, "test")
    assert s.shield == 0            # 扣至 0 为止，不变负
    g._change_shield(Ref(player=0, shikigami=IDX), -1, "test")
    assert s.shield == 0            # 不持有护甲：终止结算


def test_fragile_gain_loss_clamped(db, make_game):
    """获得/失去破甲：破甲为负值；失去破甲只能扣已有的破甲。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    ref = Ref(player=0, shikigami=IDX)
    g._change_shield(ref, 3, "test", kind="fragile")
    assert s.shield == -3
    g._change_shield(ref, -1, "test", kind="fragile")
    assert s.shield == -2
    g._change_shield(ref, -5, "test", kind="fragile")
    assert s.shield == 0            # 扣至 0 为止，不变正
    g._change_shield(ref, -1, "test", kind="fragile")
    assert s.shield == 0            # 不持有破甲：终止结算


def test_gain_cancels_opposite(db, make_game):
    """获得先抵消反向值再盈余同向：3 破甲获得 5 护甲 → 2 护甲（反之亦然）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    ref = Ref(player=0, shikigami=IDX)
    s.shield = -3
    g._change_shield(ref, 5, "test")
    assert s.shield == 2            # -3 + 5
    s.shield = 3
    g._change_shield(ref, 5, "test", kind="fragile")
    assert s.shield == -2           # 3 - 5


def test_shield_changed_event_carries_kind(db, make_game):
    """on_shield_changed payload 带 kind 区分方向（获得护甲/获得破甲属不同事件）。"""
    g, pa, pb = _game(make_game)
    events = []
    orig = g.emit

    def spy(name, **kw):
        if name == "on_shield_changed":
            events.append(kw)
        orig(name, **kw)
    g.emit = spy
    g._change_shield(Ref(player=0, shikigami=IDX), 2, "test")
    g._change_shield(Ref(player=0, shikigami=IDX), 2, "test", kind="fragile")
    assert [e["kind"] for e in events] == ["shield", "fragile"]


# ---------- 破甲：伤害流程（rules.md ch5 批次 4 / 贯通 / 穿刺 / 回合开始） ----------

def test_fragile_boosts_damage_then_zeroed(db, make_game):
    """伤害批次 4：受伤者持有破甲 → 伤害 += 破甲值，破甲归零。"""
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]              # 4 血
    b.health = 20                    # 避免气绝流程把生命归零，便于观察伤害值
    b.shield = -3
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 4, None)
    assert b.health == 13            # 4 + 3 = 7 伤害
    assert b.shield == 0             # 破甲被移除


def test_piercing_skips_fragile(db, make_game):
    """贯通修正跳过破甲计算（只吸收正护甲）：破甲不消耗、伤害不增加。"""
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]
    b.shield = -3
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, Ref(player=0, shikigami=IDX),
                        piercing=True)
    assert b.health == 2             # 破甲不生效
    assert b.shield == -3            # 破甲保留


def test_pierce_removes_armor_only(db, make_game):
    """穿刺（造成伤害前）：只移除正护甲/屏障，不动破甲；破甲仍加成后续伤害。"""
    g, pa, pb = _game(make_game)
    src = pa.shikigami[IDX]
    src.keywords.append("pierce")
    b = pb.shikigami[0]
    b.health = 20                    # 避免气绝流程把生命归零，便于观察伤害值
    b.shield = -3
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, Ref(player=0, shikigami=IDX))
    assert b.health == 15            # 2 + 3（破甲加成）
    assert b.shield == 0             # 破甲于批次 4 消耗（非穿刺移除）
    b2 = pb.shikigami[1]             # 6 血
    b2.shield = 5
    g.deal_to_shikigami(Ref(player=1, shikigami=1), 3, Ref(player=0, shikigami=IDX))
    assert b2.shield == 0            # 正护甲被穿刺移除
    assert b2.health == 3            # 全额 3 伤害


def test_turn_start_clears_both_directions(db, make_game):
    """回合开始双向清除护甲/破甲；keep_shield 仅保留正值部分。"""
    g, pa, pb = _game(make_game)
    s0, s1 = pa.shikigami[0], pa.shikigami[1]
    s0.shield = -3                   # 破甲：清除
    s1.shield = 4
    s1.keep_shield = True            # 正护甲：保留
    pa.shikigami[2].shield = -2
    pa.shikigami[2].keep_shield = True  # 破甲不受 keep_shield 保护
    pa.shield = -5
    pass_turns(g, 2)                 # A 第 2 回合开始
    assert s0.shield == 0
    assert s1.shield == 4
    assert pa.shikigami[2].shield == 0
    assert pa.shield == 0


def test_fragile_to_damage_anchor(db, make_game):
    """碧羽散华锚点：ext 持 fragile_to_damage 标记的式神获得破甲改为受到等量伤害。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.ext["fragile_to_damage"] = True
    g._change_shield(Ref(player=0, shikigami=IDX), 3, "test", kind="fragile")
    assert s.shield == 0             # 未获得破甲
    assert s.health == 1             # 4 - 3 等量伤害


# ---------- 治疗管线（thoughts.txt 治疗流程） ----------

def test_heal_capped_by_lost_health(db, make_game):
    """治疗量 = min(治疗量, 已损失生命）。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="heal", amount=10, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.health = 1                     # 已损失 3
    play(g, 0, cid)
    assert s.health == 4             # 只回 3，不超过上限


def test_heal_zero_terminates(db, make_game):
    """满血治疗：治疗前（即时）照常发出，治疗量为 0 终止——无治疗时/治疗后。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="heal", amount=5, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    assert s.health == 4
    assert "on_before_heal" in g.history
    assert "on_heal" not in g.history
    assert "on_after_heal" not in g.history


def test_heal_event_order(db, make_game):
    """治疗事件顺序：on_before_heal（即时）→ on_heal → on_after_heal（均延时）。"""
    from core.events import EVENT_TIMING
    assert EVENT_TIMING["on_before_heal"] == "insert"
    assert "on_heal" not in EVENT_TIMING       # 缺省 = 延时（queue）
    assert "on_after_heal" not in EVENT_TIMING
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="heal", amount=2, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    pa.shikigami[IDX].health = 1
    play(g, 0, cid)
    seq = [g.history.index(e) for e in ("on_before_heal", "on_heal", "on_after_heal")]
    assert seq == sorted(seq)


def test_defeated_and_dying_no_heal(db, make_game):
    """气绝/濒死者不受治疗（管线早退，不产生事件）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated
    n = len(g.history)
    g.heal(Ref(player=0, shikigami=IDX), 5, None)
    assert s.health == 0
    assert len(g.history) == n       # 无任何治疗事件
    # 濒死者同样不受治疗
    pa.shikigami[1].level = 1
    s2 = pa.shikigami[1]
    _dying(g, 0, 1)
    assert s2.dying and not s2.defeated
    n = len(g.history)
    g.heal(Ref(player=0, shikigami=1), 5, None)
    assert s2.health <= 0
    assert len(g.history) == n


# ---------- 吸血（rules.md ch5 批次 10①；thoughts.txt 答复 5） ----------

def test_lifesteal_heals_player_after_damage(db, make_game):
    """吸血：来源式神造成伤害后（延时、优先级 1 锚点）为控制者牌手恢复等量生命。"""
    g, pa, pb = _game(make_game)
    src = pa.shikigami[IDX]          # 3 力量
    src.keywords.append("lifesteal")
    pa.health = 20
    g.apply({"op": "assault", "index": IDX})   # 直击 B 牌手 3 点
    assert pb.health == 27
    assert pa.health == 23           # 吸血恢复 3（走 heal 管线）
    assert "on_heal" in g.history
    # 效果伤害同样触发吸血
    cid = 10010156
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="damage", amount=2,
                                         target=T(kind="all", pool="enemy_player"))])
    play(g, 0, cid)
    assert pb.health == 25
    assert pa.health == 25           # 再恢复 2


# ---------- 濒死（thoughts.txt 濒死定义）与气绝前 1 ----------

def test_dying_marked_before_defeat_event(db, make_game):
    """伤害扣减生命至 ≤0 → 先标 dying，气绝事件延时；check_defeated 清除 dying。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    deferred = _dying(g)
    assert s.dying and not s.defeated
    assert s.in_play                 # 濒死仍在场：能力照常
    for ref, source, reason in deferred:
        g.check_defeated(ref, source=source, reason=reason)
    assert s.defeated and not s.dying


def test_dying_no_damage_not_targetable_not_destroyed(db, make_game):
    """濒死者：不受伤害、不进随机/选择目标池、不能再次被消灭。"""
    g, pa, pb = _game(make_game)
    pa.shikigami[1].level = 1        # 对照组：另一名在场式神
    s = pa.shikigami[IDX]
    _dying(g)
    assert s.health <= 0
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 3, None)
    assert s.health <= 0 and not s.defeated          # 伤害早退
    pool = targets.pool_refs(g, "enemy_shikigami", 1)
    assert Ref(player=0, shikigami=IDX) not in pool  # 不进目标池
    assert Ref(player=0, shikigami=1) in pool        # 其他在场式神照常
    # 不能再次被消灭（destroy 早退；debug 出牌绕过目标池合法性直指濒死者）
    cid = 10010157
    db.cards[cid] = F.card(cid, shikigami=100101, level=1, token=True,
                           target=T(kind="choose", pool="enemy_shikigami"),
                           steps=[F.Step(op="destroy")])
    c = give(g, 1, cid)
    g.apply({"op": "debug_play_card", "args": {
        "player": 1, "uid": c.uid, "target": {"player": 0, "shikigami": IDX}}})
    assert not s.defeated            # 未被再次消灭


def test_dying_can_assault(db, make_game):
    """濒死者可以攻击（气绝事件延时的窗口内仍可发起战斗）。"""
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    _dying(g)
    assert s.dying and s.in_play
    g.apply({"op": "assault", "index": IDX})  # 不报错：直击 B 牌手
    assert pb.health == 27


def test_on_before_defeat_insert(db, make_game):
    """气绝前/消灭前 1：即时时机，先于形态消灭与气绝后事件。"""
    from core.events import EVENT_TIMING
    assert EVENT_TIMING["on_before_defeat"] == "insert"
    db.shikigami[100102].ability = F.EffectBlock(
        when="on_before_defeat", condition={"victim_side": "friendly"},
        steps=[F.Step(op="draw", count=1)])
    g, pa, pb = _game(make_game)
    pa.shikigami[1].level = 1        # 能力持有者须在场
    n0 = len(pa.hand)
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert pa.shikigami[IDX].defeated
    assert len(pa.hand) == n0 + 1    # 即时时机：气绝事件结算中已插入执行
    assert g.history.index("on_before_defeat") < g.history.index("on_shikigami_defeated")


def test_on_before_defeat_fires_for_destroy(db, make_game):
    """直接消灭（非伤害）同样经过气绝前 1。"""
    cid = 10010158
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="destroy", target=T(kind="all", pool="enemy_shikigami"))])
    g, pa, pb = _game(make_game)
    pb.shikigami[0].level = 1
    play(g, 0, cid)
    assert pb.shikigami[0].defeated
    assert "on_before_defeat" in g.history


# ---------- 已气绝状态的增益限制（thoughts.txt 已气绝定义） ----------

def test_defeated_only_perm_buffs_apply(db, make_game):
    """已气绝式神：非永久 buff 不生效，perm 照常（perm 生命不上调当前生命）。"""
    cid = 10010159
    db.cards[cid] = F.card(
        cid, shikigami=SID, level=1, token=True, playable_when_defeated=True,
        steps=[
            F.Step(op="buff_power", amount=2, target=T(kind="self")),
            F.Step(op="buff_power", amount=3, perm=True, target=T(kind="self")),
            F.Step(op="buff_health", amount=2, target=T(kind="self")),
            F.Step(op="buff_health", amount=3, perm=True, target=T(kind="self")),
        ])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 99, None)
    g._drain_queue()
    assert s.defeated
    play(g, 0, cid)                  # 气绝时可用：仅 perm 部分生效
    assert s.perm_power == 3
    assert s.perm_health == 3
    assert s.temp_power == 0
    assert s.temp_health == 0
    assert s.health == 0             # perm 生命不上调气绝者当前生命
    # 复活后按新上限回满
    s.revive_countdown = 1
    pass_turns(g, 2)
    assert not s.defeated
    assert s.health == 7             # 4 + 3 perm
    assert s.eff_power == 6          # 3 + 3 perm


# ==========================================================================
# boost_damage（伤害时点增幅）/ victim_player（受伤者牌手派生，引燃底层）
# ==========================================================================

def _boost_ability(db, amount=1, sid=SID):
    """测试能力：on_damage_start 时来源=自身、kind=effect 的伤害 +amount。"""
    db.shikigami[sid].ability = F.EffectBlock(
        when="on_damage_start", condition={"source_shikigami": "self", "kind": "effect"},
        steps=[F.Step(op="boost_damage", amount=amount)])


def _dmg_spell(db, cid, sid=SID, amount=3):
    db.cards[cid] = F.card(cid, shikigami=sid, token=True,
                           steps=[F.dmg(amount)], target=CHOOSE_ENEMY_DMG)
    return cid


CHOOSE_ENEMY_DMG = T(kind="choose", pool="enemy_shikigami")


def test_boost_damage_ability(db, make_game):
    """boost_damage：伤害开始时点改写事件中伤害 +1（只增）。"""
    _boost_ability(db)
    _dmg_spell(db, 10010155)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010155, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 0    # 3 + 1 = 4


def test_boost_damage_source_mismatch_noop(db, make_game):
    """负面对照：来源不是持有者（source_shikigami:self 不满足）不增幅。"""
    _boost_ability(db)
    _dmg_spell(db, 10010255, sid=100102)
    g, pa, pb = _game(make_game)
    pa.shikigami[1].level = 1
    play(g, 0, 10010255, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 1    # 无增幅：4 - 3


def test_boost_damage_kind_filter(db, make_game):
    """负面对照：战斗伤害（kind=combat/counter）不匹配条件，不增幅。"""
    _boost_ability(db)
    g, pa, pb = _game(make_game)
    move(g, 1, 0)
    pa.orb = 1
    g.apply({"op": "assault", "index": 0})
    assert pb.shikigami[0].health == 1    # 4 - 3（战斗伤害不增幅）
    assert pa.shikigami[0].health == 1    # 反击同样不增幅


def test_boost_damage_zero_noop(db, make_game):
    """boost_damage amount=0：空操作（伤害值不变）。"""
    _boost_ability(db, amount=0)
    _dmg_spell(db, 10010155)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010155, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 1    # 4 - 3


def _ignite_card(db, cid=10010156):
    """引燃式：登记一次性延迟能力——消灭（来源=自身）时对受伤者的牌手造成 2 伤。"""
    db.cards[cid] = F.card(cid, shikigami=SID, token=True, steps=[F.Step(
        op="delay_grant", when="on_shikigami_defeated",
        condition={"source_shikigami": "self"},
        steps=[F.Step(op="damage", amount=2,
                      target=T(kind="context", key="victim_player"))])])
    return cid


def test_victim_player_enemy(db, make_game):
    """victim_player：消灭敌方式神后对其牌手造成 2 伤。"""
    _ignite_card(db)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010156)
    move(g, 1, 0)
    pb.shikigami[0].health = 1
    pa.orb = 1
    g.apply({"op": "assault", "index": 0})
    assert pb.shikigami[0].defeated
    assert pb.health == 28                # 受伤者（敌方式神）的牌手受 2 伤


def test_victim_player_friendly(db, make_game):
    """victim_player：消灭己方式神则对己方牌手造成伤害。"""
    _ignite_card(db)
    db.cards[10010157] = F.card(10010157, shikigami=SID, token=True,
                                steps=[F.dmg(99)],
                                target=T(kind="choose", pool="any_shikigami"))
    g, pa, pb = _game(make_game)
    pa.shikigami[1].level = 1
    play(g, 0, 10010156)
    play(g, 0, 10010157, target=Ref(player=0, shikigami=1))
    assert pa.shikigami[1].defeated
    assert pa.health == 28                # 受伤者（己方式神）的牌手 = 己方牌手


# ==========================================================================
# 免疫敌方非战斗伤害（grant_immunity kind=effect from_side=enemy，觉醒山童底层）
# ==========================================================================

def _effect_immunity_spell(db, cid=10010158):
    """授予来源式神"免疫敌方非战斗伤害"（perm）的法术。"""
    db.cards[cid] = F.card(cid, shikigami=SID, token=True, steps=[F.Step(
        op="grant_immunity", scope="perm", kind="effect", from_side="enemy",
        target=T(kind="self"))])
    return cid


def test_effect_immunity_enemy_source(db, make_game):
    """免疫敌方非战斗伤害：敌方来源的 effect 伤害被免疫。"""
    _effect_immunity_spell(db)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010158)
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 3, Ref(player=1, shikigami=0))
    assert pa.shikigami[IDX].health == 4     # 免疫


def test_effect_immunity_friendly_or_none_source_not(db, make_game):
    """from=enemy 限定：己方来源与无来源的 effect 伤害不免疫。"""
    _effect_immunity_spell(db)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010158)
    ref = Ref(player=0, shikigami=IDX)
    g.deal_to_shikigami(ref, 3, Ref(player=0, shikigami=1))
    assert pa.shikigami[IDX].health == 1     # 己方来源：不免疫
    g.deal_to_shikigami(ref, 1, None)
    assert pa.shikigami[IDX].health == 0     # 无来源：不免疫


def test_effect_immunity_not_combat(db, make_game):
    """kind=effect 免疫不覆盖战斗伤害（combat/counter 属 combat_damage 免疫）。"""
    _effect_immunity_spell(db)
    g, pa, pb = _game(make_game)
    play(g, 0, 10010158)
    ref = Ref(player=0, shikigami=IDX)
    g.deal_to_shikigami(ref, 2, Ref(player=1, shikigami=0), kind="combat")
    assert pa.shikigami[IDX].health == 2     # 战斗伤害照常
