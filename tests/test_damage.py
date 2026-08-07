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


def test_heal_zero_fires_on_heal_not_after(db, make_game):
    """满血治疗（实际恢复 0）：治疗前照常发出，治疗时 on_heal 仍触发，治疗后 on_after_heal 不触发。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="heal", amount=5, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    assert s.health == 4
    assert "on_before_heal" in g.history
    assert "on_heal" in g.history            # 治疗时：0 量也触发
    assert "on_after_heal" not in g.history  # 治疗后：仅实际恢复 > 0
    # 结算明细：0 量治疗也明示一行（过量转化类配合可读）
    assert any("【治疗】" in l and "恢复 0 点生命" in l for l in g.state.settle_log)


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


# ---------- 必杀 ----------

def test_lethal_delayed_defeat(db, make_game):
    """必杀：造成伤害后受伤者延时结算气绝（不提前标濒死——剩余生命 >0 也气绝）；
    与伤害本身导致的气绝并行结算（幂等，气绝事件只结算一次）。"""
    g = make_game()
    pa, pb = g.state.players
    a, b = pa.shikigami[0], pb.shikigami[0]
    move(g, 1, 0)
    a.keywords.append("lethal")
    a.temp_power = -1  # 2 攻：伤害本身不致死（4 血 → 剩 2）
    g.apply({"op": "assault", "index": 0})
    assert b.defeated and b.health == 0  # 必杀延时气绝（伤害未致死仍气绝）
    assert g.history.count("on_shikigami_defeated") == 1
    # 伤害致死与必杀并行结算：气绝事件仍只结算一次
    g2 = make_game()
    a2, b2 = g2.state.players[0].shikigami[0], g2.state.players[1].shikigami[0]
    move(g2, 1, 0)
    a2.keywords.append("lethal")
    a2.temp_power = 1  # 4 攻：伤害本身击杀 4 血
    g2.apply({"op": "assault", "index": 0})
    assert b2.defeated
    assert g2.history.count("on_shikigami_defeated") == 1


def test_lethal_not_damage_property(db, make_game):
    """必杀不是伤害属性：伤害被免疫（未造成）则不触发；与伤害免疫/屏障等无关。"""
    g = make_game()
    pa, pb = g.state.players
    a, b = pa.shikigami[0], pb.shikigami[0]
    move(g, 1, 0)
    a.keywords.append("lethal")
    b.immunities.append({"kind": "combat_damage", "turn": g.state.turn})
    g.apply({"op": "assault", "index": 0})
    assert b.health == 4 and not b.defeated  # 未造成伤害：必杀不触发


# ==========================================================================
# 治疗管线扩展（过量治疗转化 / 反转 / 恢复触发 / 伤害合计 memo / 治疗目标池）
# ==========================================================================

def test_overheal_converts_on_friendly_heal(db, make_game):
    """过量治疗转化（海坊主）：on_heal payload 带 overheal = 治疗量-实际治疗量；
    己方目标获得等量护甲（觉醒另加等量力量）。满血治疗（实际恢复 0）on_heal 仍触发，
    overheal = 全额 → 全额转护甲。"""
    overheal_block = lambda extra: F.block(   # noqa: E731
        F.Step(op="gain_shield", amount={"event": "overheal"},
               target=T(kind="context", key="target")),
        *extra,
        when="on_heal",
        condition={"source_shikigami": "self", "target_side": "friendly",
                   "overheal_ge": 1})
    heal_spell = lambda: F.card(   # noqa: E731
        10010155, shikigami=SID, level=1, token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        steps=[F.Step(op="heal", amount=5)])
    # 基础：过量部分转护甲
    db.shikigami[SID].ability = overheal_block([])
    db.cards[10010155] = heal_spell()
    g, pa, pb = _game(make_game)
    s2 = pa.shikigami[1]
    s2.level = 1
    s2.health = 4                    # 已损失 2
    play(g, 0, 10010155, target=Ref(player=0, shikigami=1))
    assert s2.health == 6            # 实际恢复 2
    assert s2.shield == 3            # 过量 3 转护甲
    # 满血治疗：on_heal 0 量仍触发，overheal=5 全额转护甲
    play(g, 0, 10010155, target=Ref(player=0, shikigami=1))
    assert s2.health == 6
    assert s2.shield == 8
    # 觉醒：过量部分转护甲 + 力量
    db.shikigami[SID].ability = overheal_block(
        [F.Step(op="buff_power", amount={"event": "overheal"},
                target=T(kind="context", key="target"))])
    db.cards[10010156] = heal_spell()
    g2, pa2, _ = _game(make_game)
    t2 = pa2.shikigami[1]
    t2.level = 1
    t2.health = 4
    play(g2, 0, 10010156, target=Ref(player=0, shikigami=1))
    assert t2.shield == 3 and t2.eff_power == t2.base_power + 3


def test_heal_reversal_to_enemy(db, make_game):
    """治疗反转（法界唯心 heal_reversal 标记形态在场）：控制者对敌方的恢复生命
    效果改为等额伤害（不发出任何治疗事件，伤害事件照常）；对己方的恢复不受影响。"""
    db.cards[10010157] = F.card(
        10010157, shikigami=SID, card_type="form", level=1,
        form_power=5, form_health=6, tags=["heal_reversal"], token=True)
    db.cards[10010158] = F.card(
        10010158, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="heal", amount=4, target=T(kind="all", pool="enemy_player"))])
    db.cards[10010159] = F.card(
        10010159, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="heal", amount=4, target=T(kind="all", pool="self_player"))])
    g, pa, pb = _game(make_game)
    play(g, 0, 10010157)             # 结附反转形态
    pa.health = 25
    n = len(g.history)
    play(g, 0, 10010158)             # 对敌方牌手的"恢复"→ 等额伤害
    assert pb.health == 30 - 4
    assert "on_heal" not in g.history[n:]
    assert "on_player_damaged" in g.history[n:]
    play(g, 0, 10010159)             # 对己方的恢复不受影响
    assert pa.health == 29


def test_heal_trigger_abilities_once_per_turn(db, make_game):
    """恢复触发型能力（青坊主/禅心）：挂治疗后 on_after_heal——己方任意角色实际恢复
    即触发（含式神与牌手），0 量治疗（on_heal 触发但 after 不触发）不触发；
    turn_mark 门控每回合合计一次、任一回合开始清除；觉醒版无门控每次触发。"""
    db.shikigami[100102].ability = F.block(
        F.Step(op="turn_mark", key="qfz"),
        F.Step(op="random_damage", amount=1, pool="enemy_character", count=2),
        when="on_after_heal",
        condition={"target_side": "friendly", "turn_mark_not": "qfz"})
    db.cards[10010155] = F.card(
        10010155, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="heal", amount=2, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    pa.shikigami[IDX].health = 1
    pa.shikigami[1].level = 1        # 青坊主位在场
    pb.shikigami[0].level = 1        # 敌方角色池 = 式神0 + 牌手
    play(g, 0, 10010155)
    hurt = (30 - pb.health) + sum(s.max_health - s.health for s in pb.shikigami)
    assert hurt == 2                 # 随机两个敌方角色各 1
    play(g, 0, 10010155)             # 本回合第二次恢复：不再触发
    hurt2 = (30 - pb.health) + sum(s.max_health - s.health for s in pb.shikigami)
    assert hurt2 == 2
    pass_turns(g, 2)                 # 任一回合开始清除标记 → 下轮可再触发
    pa.shikigami[IDX].health = 1
    play(g, 0, 10010155)
    hurt3 = (30 - pb.health) + sum(s.max_health - s.health for s in pb.shikigami)
    assert hurt3 == 4
    # 0 量治疗（满血）：on_heal 触发但 on_after_heal 不触发 → 不触发
    pass_turns(g, 2)
    pa.shikigami[IDX].health = pa.shikigami[IDX].max_health
    n = len(g.history)
    play(g, 0, 10010155)             # 满血目标：实际恢复 0
    assert "on_heal" in g.history[n:]
    assert "on_after_heal" not in g.history[n:]
    hurt4 = (30 - pb.health) + sum(s.max_health - s.health for s in pb.shikigami)
    assert hurt4 == 4
    # 觉醒版（无 turn_mark 门控）：每次恢复都对所有敌人造成 1 伤
    db.shikigami[100102].ability = F.block(
        F.Step(op="damage", amount=1, target=T(kind="all", pool="enemy_character")),
        when="on_after_heal", condition={"target_side": "friendly"})
    g2, pa2, pb2 = _game(make_game)
    pa2.shikigami[IDX].health = 1
    pa2.shikigami[1].level = 1
    pb2.shikigami[0].level = 1
    play(g2, 0, 10010155)
    play(g2, 0, 10010155)
    assert pb2.health == 30 - 2      # 两次恢复各 1
    assert pb2.shikigami[0].health == pb2.shikigami[0].max_health - 2


def test_heal_trigger_draw_once_per_turn(db, make_game):
    """恢复抽牌（禅心）：每回合一次，恢复时抽 1。"""
    db.shikigami[100102].ability = F.block(
        F.Step(op="turn_mark", key="zx"),
        F.Step(op="draw", count=1),
        when="on_after_heal",
        condition={"target_side": "friendly", "turn_mark_not": "zx"})
    db.cards[10010155] = F.card(
        10010155, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="heal", amount=2, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    pa.shikigami[IDX].health = 1
    pa.shikigami[1].level = 1
    n0 = len(pa.hand)
    play(g, 0, 10010155)
    assert len(pa.hand) == n0 + 1    # 抽 1
    play(g, 0, 10010155)
    assert len(pa.hand) == n0 + 1    # 本回合不再触发


def test_damage_total_memo_heal(db, make_game):
    """伤害合计 memo（巨浪）：damage 记录 last_damage_total（扣减生命口径，护甲吸收
    部分不计），后续 step 以 {memo: ...} 动态数值引用恢复来源式神。"""
    db.cards[10010155] = F.card(
        10010155, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="all", pool="enemy_shikigami")),
               F.Step(op="heal", amount={"memo": "last_damage_total"},
                      target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.health = 1                     # 已损失 3
    pb.shikigami[0].level = 1
    pb.shikigami[1].level = 1
    pb.shikigami[0].shield = 1       # 吸收 1：实际造成 1 + 2 = 3
    play(g, 0, 10010155)
    assert pb.shikigami[0].health == pb.shikigami[0].max_health - 1
    assert pb.shikigami[1].health == pb.shikigami[1].max_health - 2
    assert s.health == 4             # 按实际总点数恢复 3


def test_side_of_last_heal_pool(db, make_game):
    """side_of_last_heal 池（佛光）：为上一步治疗目标所属方的所有角色恢复。"""
    db.cards[10010155] = F.card(
        10010155, shikigami=SID, level=1, token=True,
        target=T(kind="choose", pool="any_character"),
        steps=[F.Step(op="heal", amount=4),
               F.Step(op="heal", amount=3, target=T(kind="all", pool="side_of_last_heal"))])
    g, pa, pb = _game(make_game)
    pb.health = 24
    pb.shikigami[0].level = 1
    pb.shikigami[0].health = 1
    play(g, 0, 10010155, target=Ref(player=1))   # 目标 = 敌方牌手
    assert pb.health == 30                       # 24 +4 +3（满 30 封顶）
    assert pb.shikigami[0].health == 4           # 其操控者所有角色：1 +3
    assert pa.health == 30                       # 己方不受影响


def test_heal_player_triggers_self_heal(db, make_game):
    """灵能：来源式神为牌手恢复生命时，自身恢复等量（按实际治疗量）。"""
    db.shikigami[SID].ability = F.block(
        F.Step(op="heal", amount={"event": "amount"}, target=T(kind="self")),
        when="on_heal",
        condition={"source_shikigami": "self", "target_kind": "player"})
    db.cards[10010155] = F.card(
        10010155, shikigami=SID, level=1, token=True,
        steps=[F.Step(op="heal", amount=4, target=T(kind="all", pool="self_player"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.health = 1                     # 已损失 3
    pa.health = 25
    play(g, 0, 10010155)
    assert pa.health == 29           # 牌手实际恢复 4
    assert s.health == 4             # 灵能恢复等量 3（ capped by 已损失）


# ---------- 清姬伤害转化 / 庇佑 / 生命钳制 / 破甲保留 ----------

def test_damage_to_fragile_conversion(db, make_game):
    """清姬型伤害转化（伪关键字 damage_to_fragile）：来源持标记且受伤者无破甲 →
    伤害事件生成点全额转化为等量破甲（无扣减/无 on_damage）；受伤者已有破甲
    或来源无标记则正常结算；牌手同样适用（获得破甲先抵消已有护甲）。"""
    g, pa, pb = _game(make_game)
    src = pa.shikigami[IDX]
    src.keywords.append("damage_to_fragile")
    sref = Ref(player=0, shikigami=IDX)
    b0 = pb.shikigami[0]
    bref = Ref(player=1, shikigami=0)
    g.deal_to_shikigami(bref, 3, sref)
    assert b0.shield == -3 and b0.health == 4        # 转化：不产生伤害
    assert "on_damage" not in g.history
    b0.health = 20
    g.deal_to_shikigami(bref, 2, sref)             # 已有破甲：正常伤害并消耗破甲
    assert b0.health == 15 and b0.shield == 0        # 20 - (2+3)
    pb.shield = 5
    g.deal_to_player(1, 4, sref)                     # 牌手无破甲：转化（先抵消护甲）
    assert pb.shield == 1 and pb.health == 30
    # 其他来源的伤害不转化
    g.deal_to_shikigami(bref, 2, Ref(player=0, shikigami=1))
    assert b0.health == 13


def test_blessing_negates_enemy_spell_damage(db, make_game):
    """庇佑（消耗型关键字）：抵消一次敌方造成的法术伤害（法术牌效果伤害，spell=True）
    并失去；战斗伤害、式神能力伤害（非法术的非战斗伤害——答复(7)）、己方来源伤害
    不触发；被护甲完全吸收的伤害不消耗。"""
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]
    b.health = 20
    bref = Ref(player=1, shikigami=0)
    enemy = Ref(player=0, shikigami=IDX)
    b.one_shot_keywords.append("blessing")
    g.deal_to_shikigami(bref, 3, enemy, spell=True)
    assert b.health == 20 and "blessing" not in b.one_shot_keywords  # 法术伤害：抵消并失去
    b.one_shot_keywords.append("blessing")
    g.deal_to_shikigami(bref, 2, enemy, kind="combat")             # 战斗伤害不触发
    assert b.health == 18 and "blessing" in b.one_shot_keywords
    g.deal_to_shikigami(bref, 1, enemy)                            # 能力伤害（非法术）不触发
    assert b.health == 17 and "blessing" in b.one_shot_keywords
    g.deal_to_shikigami(bref, 1, Ref(player=1, shikigami=1), spell=True)  # 己方法术不触发
    assert b.health == 16 and "blessing" in b.one_shot_keywords
    b.shield = 5
    g.deal_to_shikigami(bref, 2, enemy, spell=True)                # 护甲全吸收不消耗
    assert b.health == 16 and b.shield == 3 and "blessing" in b.one_shot_keywords
    g.deal_to_shikigami(bref, 4, enemy, spell=True)                # 穿透护甲部分被抵消
    assert b.health == 16 and b.shield == 0
    assert "blessing" not in b.one_shot_keywords


def test_buff_health_negative_clamps_current(db, make_game):
    """墨笔夺魂型"降低生命"：上限下调同步钳当前生命；上限降至不大于 0 目标气绝。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, steps=[
        F.Step(op="buff_health", amount=-1),
        F.Step(op="buff_power", amount=-2)], target=CHOOSE_ENEMY_DMG, token=True)
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]                              # 3/4
    b.level = 1
    tgt = Ref(player=1, shikigami=0)
    play(g, 0, cid, target=tgt)
    assert b.max_health == 3 and b.health == 3 and b.eff_power == 1
    play(g, 0, cid, target=tgt)
    play(g, 0, cid, target=tgt)
    assert b.max_health == 1 and b.health == 1
    play(g, 0, cid, target=tgt)                      # 上限 1 → 0
    assert b.defeated


def test_fragile_kept_by_enemy_awaken(db, make_game):
    """觉醒·清姬型破甲保留（keep_enemy_fragile 标记觉醒牌在场）：己方回合开始时
    破甲不被清除；护甲照常清除。"""
    awaken_cid = 10010160
    db.cards[awaken_cid] = F.card(awaken_cid, subtype="awaken",
                                  tags=["keep_enemy_fragile"], token=True)
    g, pa, pb = _game(make_game)
    pa.shikigami[IDX].awakened = awaken_cid          # A 侧已觉醒（B 的"对方"）
    b0, b1 = pb.shikigami[0], pb.shikigami[1]
    b0.shield = -3
    b1.shield = 4
    pb.shield = -2
    g.apply({"op": "end_turn"})                      # → B 回合开始：破甲保留、护甲清除
    assert b0.shield == -3 and pb.shield == -2
    assert b1.shield == 0


# ----------破甲转移 / 破甲保留 / 破甲量战力 / 光环伤害加成 / 伤害来源条件 ----------

def test_transfer_fragile(db, make_game):
    """腐坏直拳型破甲转移：来源破甲等量转移给每个目标（多名各获全量、非分配）后
    来源清零；来源无破甲为空操作。"""
    single = 10010161
    db.cards[single] = F.card(single, token=True, target=CHOOSE_ENEMY_DMG, steps=[
        F.Step(op="transfer_fragile", target=CHOOSE_ENEMY_DMG)])
    aoe = 10010162
    db.cards[aoe] = F.card(aoe, token=True, steps=[
        F.Step(op="transfer_fragile", target=T(kind="all", pool="enemy_shikigami"))])
    g, pa, pb = _game(make_game)
    me = Ref(player=0, shikigami=IDX)
    # 单体：-5 转移给敌 1 号位，来源清零
    pb.shikigami[1].level = 1
    g._change_shield(me, 5, "test", kind="fragile")
    play(g, 0, single, target=Ref(player=1, shikigami=1))
    assert pa.shikigami[IDX].shield == 0
    assert pb.shikigami[1].shield == -5
    # 全体：每名敌方各获全量 -3（1 号位在已有 -5 上叠加）
    g._change_shield(me, 3, "test", kind="fragile")
    play(g, 0, aoe)
    assert pa.shikigami[IDX].shield == 0
    assert pb.shikigami[0].shield == -3
    assert pb.shikigami[1].shield == -8
    # 无破甲：空操作
    play(g, 0, aoe)
    assert pb.shikigami[0].shield == -3 and pb.shikigami[1].shield == -8


def test_keep_fragile_form_scoped(db, make_game):
    """肿胀体质型破甲保留（keep_fragile）：形态在场时破甲不随己方回合开始清除；
    形态离场即解除，之后恢复清除。"""
    cid = 10010163
    db.cards[cid] = F.card(cid, card_type="form", form_power=1, form_health=5,
                           token=True, steps=[
        F.Step(op="keep_fragile", target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    play(g, 0, cid)
    assert s.keep_fragile
    g._change_shield(Ref(player=0, shikigami=IDX), 4, "test", kind="fragile")
    assert s.shield == -4
    pass_turns(g, 2)                         # 己方回合开始：破甲保留
    assert s.shield == -4
    g._destroy_form(pa, IDX, reason="test")
    assert not s.keep_fragile                # 形态离场即解除（"形态在场时"语义）
    pass_turns(g, 2)
    assert s.shield == 0                     # 恢复回合开始清除


def test_fragile_of_as_combat_power(db, make_game):
    """僵硬扑击型：战斗牌获得等同于自身破甲量的战力（amount {"fragile_of": "self"}，
    战斗牌战力提取读取点同源）。"""
    cid = 10010164
    db.cards[cid] = F.card(cid, card_type="combat", token=True, steps=[
        F.Step(op="buff_power", amount={"fragile_of": "self"}, target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]
    b.health = 20
    b.base_power = 0                         # 免反击干扰
    move(g, 1, 0)
    g._change_shield(Ref(player=0, shikigami=IDX), 3, "test", kind="fragile")
    play(g, 0, cid)                          # 战力 = 3 基础 + 3 破甲量
    assert b.health == 14
    assert pa.shikigami[IDX].shield == -3    # 破甲本身保留


def test_card_aura_damage_boost(db, make_game):
    """寒冬之心型卡牌光环伤害加成（tag 通道 + damage_boost + scope="game"）：
    命中标记的牌效果伤害 +1，可叠加。"""
    snow = 10010165
    db.cards[snow] = F.card(snow, tags=["snowball"], token=True,
                            target=CHOOSE_ENEMY_DMG, steps=[F.dmg(1, CHOOSE_ENEMY_DMG)])
    aura = 10010166
    db.cards[aura] = F.card(aura, token=True, steps=[
        F.Step(op="card_aura", tag="snowball", damage_boost=1, scope="game",
               target=T(kind="self"))])
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]
    b.health = 20
    tgt = Ref(player=1, shikigami=0)
    play(g, 0, snow, target=tgt)
    assert b.health == 19                    # 无光环：1
    play(g, 0, aura)
    play(g, 0, snow, target=tgt)
    assert b.health == 17                    # 一层光环：2
    play(g, 0, aura)
    play(g, 0, snow, target=tgt)
    assert b.health == 14                    # 两层叠加：3


def test_on_damage_source_condition_any_kind(db, make_game):
    """原初能力型：on_damage 以来源匹配（{source_shikigami: self}），不分伤害种类——
    效果伤害与战斗伤害都触发。"""
    db.shikigami[SID] = F.shiki(SID, ability=F.block(
        F.Step(op="stun", target=T(kind="context", key="victim")),
        when="on_damage", condition={"source_shikigami": "self"}))
    g, pa, pb = _game(make_game)
    b = pb.shikigami[0]
    b.health = 20
    src = Ref(player=0, shikigami=IDX)
    g.deal_to_shikigami(Ref(player=1, shikigami=0), 2, src)   # 效果伤害触发
    g._drain_queue()
    assert b.is_stunned
    b.stuns.clear()
    move(g, 1, 0)
    g.apply({"op": "assault", "index": IDX})                  # 战斗伤害同样触发
    assert b.is_stunned



def test_cap_damage_fixed_value(db, make_game):
    """雪融之时型受伤上限：cap_damage to=<int> 将本次伤害面板值封顶定值——
    超过封顶才截断、低于封顶不变、封顶后再走护甲吸收。"""
    cid = 10010167
    db.cards[cid] = F.card(
        cid, shikigami=SID, card_type="form", level=1,
        form_power=5, form_health=7, token=True,
        abilities=[F.block(F.Step(op="cap_damage", to=3), when="on_damage_start",
                           condition={"victim_shikigami": "self"})])
    g, pa, pb = _game(make_game)
    play(g, 0, cid)
    s = pa.shikigami[IDX]
    assert s.health == 7
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 5, None)
    assert s.health == 4             # 5 封顶为 3
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, None)
    assert s.health == 2             # 2 低于封顶：不变
    s.shield = 2
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 5, None)
    assert s.shield == 0             # 封顶 3 后护甲吸收 2
    assert s.health == 1


# ---------- 治疗时牌手条件 / 0 治疗触发（吸血姬批次：on_heal 条件键组合） ----------

def test_on_heal_player_side_condition(db, make_game):
    """on_heal 牌手条件组合 {target_kind: player, target_side: friendly|enemy}：
    治疗目标是己方/敌方牌手（基础能力=+1力量+1护甲；力量为一次性持续性增益非永久，
    护甲回合开始正常移除——均走既有通道）。"""
    db.shikigami[SID].ability = F.block(
        F.Step(op="buff_power", amount=1, target=T(kind="self")),
        F.Step(op="gain_shield", amount=1, target=T(kind="self")),
        when="on_heal", condition={"target_kind": "player", "target_side": "friendly"})
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    pa.health = 20
    g.heal(Ref(player=0, shikigami=IDX), 2, None)   # 治疗己方式神：不触发
    g._drain_queue()
    assert s.temp_power == 0 and s.shield == 0
    pb.health = 20
    g.heal(Ref(player=1), 2, None)                  # 治疗敌方牌手：不触发
    g._drain_queue()
    assert s.temp_power == 0 and s.shield == 0
    g.heal(Ref(player=0), 3, None)                  # 治疗己方牌手：+1 力量 +1 护甲
    g._drain_queue()
    assert pa.health == 23
    assert s.temp_power == 1 and s.shield == 1


def test_on_heal_zero_amount_still_triggers(db, make_game):
    """恢复量为 0 也触发"治疗时"（on_heal）；觉醒型等量增益 {event: amount, cap: 5}
    按实际治疗量取、上限 5。"""
    db.shikigami[SID].ability = F.block(
        F.Step(op="buff_power", amount={"event": "amount", "cap": 5},
               target=T(kind="self")),
        F.Step(op="gain_shield", amount={"event": "amount", "cap": 5},
               target=T(kind="self")),
        when="on_heal", condition={"target_kind": "player", "target_side": "friendly"})
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    pa.health = 22
    g.heal(Ref(player=0), 8, None)                  # 实际恢复 8：cap 5 → +5/+5
    g._drain_queue()
    assert pa.health == 30
    assert s.temp_power == 5 and s.shield == 5
    g.heal(Ref(player=0), 3, None)                  # 满血：恢复量为 0 仍触发（+0）
    g._drain_queue()
    assert s.temp_power == 5 and s.shield == 5
    assert "on_heal" in g.history
    assert "on_after_heal" not in g.history[-2:]    # 0 治疗不触发"治疗后"


# ---------- 延迟吸血授予（初拥型：可叠加、与[吸血]关键字叠加） ----------

def test_delayed_lifesteal_grant_stacks(db, make_game):
    """初拥型"本回合获得造成战斗伤害时为其牌手恢复等量生命"（delay_grant bind=chosen
    scope=turn）：多次授予各触发一次、与[吸血]关键字叠加；[吸血]自身不叠加——
    两张授予 + 吸血，3 点战斗伤害依次 3 次恢复 3（维护者定案）。
    授予挂 on_damage（式神受伤）与 on_player_damaged（牌手受伤）两个事件各一层；
    与引擎吸血通道一致不限伤害类别（效果伤害同样触发，见 test_lifesteal_heals_player_after_damage）。"""
    cid = 10010168
    grant_steps = [{"op": "heal", "amount": {"event": "amount"},
                    "target": {"kind": "all", "pool": "self_player"}}]
    db.cards[cid] = F.card(
        cid, shikigami=SID, level=1, token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        steps=[F.Step(op="delay_grant", bind="chosen", when="on_damage",
                      condition={"source_shikigami": "self"}, scope="turn", uses=99,
                      steps=grant_steps),
               F.Step(op="delay_grant", bind="chosen", when="on_player_damaged",
                      condition={"source_shikigami": "self"}, scope="turn", uses=99,
                      steps=grant_steps)])
    g, pa, pb = _game(make_game)
    pa.shikigami[1].level = 1
    a = pa.shikigami[1]                              # 1/6（100102）
    a.keywords.append("lifesteal")
    a.keywords.append("lifesteal")                   # [吸血]自身不叠加（多重集也只恢复一次）
    tgt = Ref(player=0, shikigami=1)
    play(g, 0, cid, target=tgt)                      # 初拥 ×1
    play(g, 0, cid, target=tgt)                      # 初拥 ×2
    pa.health = 10
    g.apply({"op": "assault", "index": 1})           # 直击 B 牌手 1 点战斗伤害
    assert pb.health == 29
    assert pa.health == 13                           # 吸血 1 次 + 初拥 2 次 = 3 次恢复 1
    # 式神受伤分支（on_damage）：效果伤害同样触发（引擎吸血通道语义，伤害类别不限）
    cid2 = 10010251
    db.cards[cid2] = F.card(cid2, shikigami=100102, level=1, token=True,
                            steps=[F.Step(op="damage", amount=2,
                                          target=T(kind="all", pool="enemy_shikigami"))])
    pb.shikigami[0].level = 1
    play(g, 0, cid2)
    assert pa.health == 19                           # 吸血 2 + 初拥 2×2 = 3 次恢复 2
    pass_turns(g, 2)
    pa.health = 10
    g.apply({"op": "assault", "index": 1})           # 次回合：授予已过期，只剩吸血 1 次
    assert pa.health == 11


# ---------- 法术牌吸血光环（猩红之月型：吸血判定读来源卡牌实例关键字） ----------

def test_card_aura_lifesteal_on_spell_damage(db, make_game):
    """猩红之月型"你的法术牌获得[吸血]"：card_aura(keywords=["lifesteal"],
    card_type="spell") 后，法术牌效果伤害触发吸血（来源式神无 lifesteal 也生效，
    吸血判定扩展读来源卡牌实例关键字）；两处命中只恢复一次（[吸血]不叠加）。"""
    g, pa, pb = _game(make_game)
    src = pa.shikigami[IDX]                          # 3 力量，无 lifesteal
    cid = 10010169
    db.cards[cid] = F.card(cid, shikigami=SID, level=1, token=True,
                           steps=[F.Step(op="damage", amount=2,
                                         target=T(kind="all", pool="enemy_player"))])
    pa.health = 20
    play(g, 0, cid)                                  # 无光环：不恢复
    assert pb.health == 28
    assert pa.health == 20
    pa.card_auras.append({"shikigami": None, "card_type": "spell", "card_id": None,
                          "tag": None, "keywords": ["lifesteal"], "cost_zero": False,
                          "power": 0, "shield": 0, "turn": None, "scope": "game"})
    play(g, 0, cid)                                  # 法术牌获得[吸血]：恢复 2
    assert pb.health == 26
    assert pa.health == 22
    src.keywords.append("lifesteal")                 # 式神关键字 + 卡牌光环双命中：仍只恢复一次
    play(g, 0, cid)
    assert pb.health == 24
    assert pa.health == 24


# ---------- 伤害转移（血蝠之盾型：下一次伤害改由牌手承受） ----------

def test_damage_redirect_to_player(db, make_game):
    """血蝠之盾型伤害转移（grant_redirect）：下一次将受到的伤害以其牌手为受伤者重新
    结算——牌手护甲照常吸收、牌手免疫照常生效；一次性消耗；式神自身屏障不随转移
    消耗；伤害类别不限。"""
    cid = 10010170
    db.cards[cid] = F.card(
        cid, shikigami=SID, level=1, token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        steps=[F.Step(op="grant_redirect")])
    g, pa, pb = _game(make_game)
    s = pa.shikigami[IDX]
    s.one_shot_keywords.append("barrier")
    pa.shield = 2
    play(g, 0, cid, target=Ref(player=0, shikigami=IDX))
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 5, Ref(player=1, shikigami=0),
                        kind="combat")
    assert pa.shield == 0                            # 牌手护甲吸收 2
    assert pa.health == 27                           # 牌手承受剩余 3
    assert s.health == 4                             # 式神无伤
    assert "barrier" in s.one_shot_keywords          # 屏障不随转移消耗
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 2, Ref(player=1, shikigami=0))
    assert "barrier" not in s.one_shot_keywords      # 一次性：第二次正常结算（屏障抵消）
    assert pa.health == 27 and s.health == 4
    # 牌手免疫照常参与转移后的结算
    play(g, 0, cid, target=Ref(player=0, shikigami=IDX))
    pa.immunities.append({"kind": "all", "turn": g.state.turn})
    g.deal_to_shikigami(Ref(player=0, shikigami=IDX), 3, Ref(player=1, shikigami=0))
    assert pa.health == 27 and s.health == 4         # 转移后被牌手免疫
    assert not s.ext.get("damage_redirects")         # 挂账已消耗
