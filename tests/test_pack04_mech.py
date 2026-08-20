"""04 沧海刀鸣包机制测试（人面树/樱花妖批次）。

分两层：dummy 层用合成数据验证引擎机制/op 的边界与负例；文末"真实数据端到端"
一节用 db/04_canghaidaoming 真实卡面验证数据接线。按机制归组命名，
式神/卡牌名只出现在 docstring 与注释中。
"""
import pytest

from core.model import Ref
from core import targets as targets_mod
from tests import factories as F

T = F.T


def _kill(game, pi: int, i: int, countdown: int | None = None) -> None:
    """测试辅助：令式神气绝（走 check_defeated 流程），可覆写气绝倒计时。"""
    s = game.state.players[pi].shikigami[i]
    s.health = 0
    game.check_defeated(Ref(player=pi, shikigami=i))
    assert s.defeated
    if countdown is not None:
        s.revive_countdown = countdown


# ---------- 扎根（形态 tags no_retreat）：己方回合开始不移回 ----------

def test_form_no_retreat(db, make_game):
    """扎根"己方回合开始时不会从战斗区移回准备区"。"""
    db.cards[10010151] = F.card(10010151, card_type="form", form_power=2,
                                form_health=7, tags=["no_retreat"], token=True)
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)
    g.apply({"op": "assault", "index": 0})  # 敌方战斗区空：打牌手，攻击者存活
    assert pa.combat_index == 0
    F.pass_turns(g, 2)  # 经敌方回合回到己方回合开始
    assert pa.combat_index == 0  # 扎根：不移回
    assert pa.shikigami[0].form is not None and pa.shikigami[0].form.id == 10010151


def test_form_retreat_default_unchanged(db, make_game):
    """对照：无 no_retreat 标记的形态照常移回。"""
    db.cards[10010151] = F.card(10010151, card_type="form", form_power=2,
                                form_health=7, token=True)
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)
    g.apply({"op": "assault", "index": 0})
    assert pa.combat_index == 0
    F.pass_turns(g, 2)
    assert pa.combat_index is None


# ---------- 形态切换（switch_form op）与结附期临时派系覆写 ----------

def _curse_forms(db):
    db.cards[10010151] = F.card(10010151, card_type="form", form_power=2,
                                form_health=7, token=True)
    db.cards[10010152] = F.card(10010152, card_type="form", form_power=1,
                                form_health=6, token=True,
                                tags=["faction_override:紫岩"])
    db.cards[10010153] = F.card(  # 神木诅咒位：使一个形态变成 51 号形态
        10010153, token=True, steps=[F.Step(
            op="switch_form", into=10010152,
            target=T(kind="all", pool="any_shikigami", has_form=True))])


def test_switch_form(db, make_game):
    """神木诅咒"使一个形态变成'诅咒之木'"：旧形态消灭入墓、新形态结附、
    身材覆盖、生命回满；无形态目标为空操作（has_form 过滤）。"""
    _curse_forms(db)
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)  # 结附 2/7 形态
    s = pa.shikigami[0]
    s.health = 3  # 受伤，验证切换后回满
    F.play(g, 0, 10010153)
    assert s.form is not None and s.form.id == 10010152
    assert (s.base_power, s.base_health) == (1, 6)
    assert s.health == 6  # 结附流程生命回满
    assert any(c.id == 10010151 for c in pa.graveyard)  # 旧形态入墓


def test_switch_form_faction_override(db, make_game):
    """诅咒之木"被变为此形态的式神会临时变为紫岩派系"：结附期间覆写
    faction（perm_faction 不动），形态离场还原。"""
    _curse_forms(db)
    db.cards[10010154] = F.card(  # 消灭形态（验证离场还原）
        10010154, token=True,
        steps=[F.Step(op="destroy_form", target=T(kind="self"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    assert s.faction == "红莲" and s.perm_faction == "红莲"
    F.play(g, 0, 10010151)
    F.play(g, 0, 10010153)
    assert s.faction == "紫岩" and s.perm_faction == "红莲"  # 临时覆写
    F.play(g, 0, 10010154)  # 消灭当前形态
    assert s.form is None and s.faction == "红莲"  # 离场还原


def test_has_form_filter(db, make_game):
    """TargetSpec has_form 过滤键：仅结附着形态的式神入池。"""
    _curse_forms(db)
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)
    spec = T(kind="choose", pool="any_shikigami", has_form=True)
    refs = targets_mod.spec_pool_refs(g, spec, 0, targeted=True)
    assert refs == [Ref(player=0, shikigami=0)]


# ---------- 神木庇佑（伪关键字 combat_base_health）：以生命造成战斗伤害 ----------

def test_combat_base_health(db, make_game):
    """神木庇佑"获得'以其自身的生命造成战斗伤害'"：攻击与反击同口径。"""
    db.cards[10010151] = F.card(  # 授予自身伪关键字（神木庇佑位）
        10010151, token=True,
        steps=[F.Step(op="grant_keyword", keyword="combat_base_health",
                      target=T(kind="self"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]  # 3/4
    F.play(g, 0, 10010151)
    s.health = 2
    g.apply({"op": "assault", "index": 0})  # 打敌方牌手：伤害 = 当前生命 2
    assert pb.health == 28
    # 反击侧：该式神留在战斗区，敌方出击受到其生命（2）而非力量（3）的反击
    F.pass_turns(g, 1)
    es = pb.shikigami[0]  # 3/4
    g.apply({"op": "assault", "index": 0})
    assert es.health == 2  # 反击 2（= 守方当前生命）


# ---------- 觉醒·人面树（伪关键字 power_eq_health）：力量等于生命 ----------

def test_power_eq_health(db, make_game):
    """觉醒·人面树"人面树的力量等于其生命"：覆写口径（基础/永久/临时修正不计），
    随当前生命浮动。"""
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["power_eq_health"])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    g._refresh_stat_auras()
    assert s.eff_power == 4  # 满生命 4
    s.temp_power += 5  # 临时修正被覆写
    g._refresh_stat_auras()
    assert s.eff_power == 4
    s.health = 2
    g._refresh_stat_auras()
    assert s.eff_power == 2


# ---------- 动态数值：health_of（灾厄之花）/ orb（汲取养分） ----------

def test_health_of_amount(db, make_game):
    """灾厄之花的伤害数值 = 来源式神当前生命（{"health_of": "self"}）。"""
    db.cards[10010151] = F.card(
        10010151, token=True, target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="damage", amount={"health_of": "self"})])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pa.shikigami[0].health = 2
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    assert pb.shikigami[0].health == 2  # 4 - 2（来源当前生命）


def test_delayed_health_of_self(db, make_game):
    """灾厄之花全链：delay_grant bind=chosen + 持有者下个己方回合结束时触发，
    对自己造成等同于其生命的伤害（无护甲即致死）。"""
    db.cards[10010151] = F.card(
        10010151, token=True, target=T(kind="choose", pool="any_shikigami"),
        steps=[F.Step(op="delay_grant", bind="chosen", when="on_turn_end",
                      condition={"active": "self"},
                      steps=[{"op": "damage", "amount": {"health_of": "self"},
                              "target": {"kind": "self"}}])])
    g = make_game()
    pa, pb = F.battle_setup(g)
    es = pb.shikigami[0]
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    F.pass_turns(g, 1)  # 己方回合结束：不该触发（"他下个回合"）
    assert not es.defeated
    F.pass_turns(g, 1)  # 目标方回合结束：触发，对自己造成 4（满生命）
    assert es.defeated


def test_orb_amount(db, make_game):
    """汲取养分数值 = 控制者当前鬼火（{"orb": true} 的 amount 通道）。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="buff_health", amount={"orb": True}, perm=True,
                      target=T(kind="self"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pa.orb = 4  # 打出耗 1 火，结算时剩余 3
    F.play(g, 0, 10010151)
    s = pa.shikigami[0]
    assert s.perm_health == 3 and s.max_health == 7 and s.health == 7


# ---------- 凋零之森：active_character 池 + 逐目标动态数值 ----------

def test_active_character_half_health(db, make_game):
    """凋零之森"当每个牌手的回合开始时，对他所有角色造成等同于他自身一半生命
    的伤害"：目标侧 = 回合方所有角色（含牌手），逐目标按其自身当前生命一半
    （向下取整）。"""
    db.shikigami[100102] = F.shiki(  # 能力挂在 100102（1/6）上
        100102, power=1, health=6,
        ability=F.block(
            F.Step(op="damage", amount={"half_health_of": "target"},
                   target=T(kind="all", pool="active_character")),
            when="on_turn_start"))
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    pb.shikigami[1].level = 0  # 对方的能力持有者不在场：不触发
    pb.shikigami[2].health = 5  # 奇数生命验证向下取整（5//2=2）
    F.pass_turns(g, 1)  # 对方回合开始
    assert pb.shikigami[0].health == 2   # 4 → 4-2
    assert pb.shikigami[2].health == 3   # 5 → 5-2
    assert pb.shikigami[1].health == 6   # 0 级未在场不受伤害
    assert pb.health == 15               # 牌手 30 → 30-15
    assert pa.shikigami[0].health == 4 and pa.health == 30  # 非回合方不受影响


# ---------- 樱花妖：气绝式神的恢复/伤害转化（倒计时 ∓1） ----------

def _defeated_pool_card(db, cid, sid, op, **step_kw):
    db.cards[cid] = F.card(
        cid, shikigami=sid, token=True,
        target=T(kind="choose", pool=("friendly_shikigami" if op == "heal"
                                      else "enemy_shikigami"),
                 include_defeated=True),
        steps=[F.Step(op=op, amount=6 if op == "heal" else 3, **step_kw)])


def test_heal_defeated_countdown(db, make_game):
    """樱花妖"可以为己方气绝式神恢复生命，若如此做改为使其倒计时-1"：
    伪关键字通道（def keywords）与 op 参数通道（弥生之舞/樱吹雪"无论是否气绝"）
    同语义；倒计时减到 0 立即复活；无授权来源对气绝目标恢复为空操作。"""
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["heal_defeated_countdown"])
    _defeated_pool_card(db, 10010151, 100101, "heal")                      # 伪关键字
    _defeated_pool_card(db, 10010351, 100103, "heal", allow_defeated=True)  # op 参数
    _defeated_pool_card(db, 10010251, 100102, "heal")                      # 无授权
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1, 3: 1})
    _kill(g, 0, 3)  # 己方式神气绝，倒计时 3
    s = pa.shikigami[3]
    F.play(g, 0, 10010151, target=Ref(player=0, shikigami=3))
    assert s.defeated and s.revive_countdown == 2  # 转化：-1 而非回血
    s.revive_countdown = 1
    F.play(g, 0, 10010151, target=Ref(player=0, shikigami=3))
    assert not s.defeated and s.health == s.max_health  # 减到 0 复活
    _kill(g, 0, 3)
    F.play(g, 0, 10010251, target=Ref(player=0, shikigami=3))
    assert s.defeated and s.revive_countdown == 3  # 无授权：空操作
    F.play(g, 0, 10010351, target=Ref(player=0, shikigami=3))
    assert s.defeated and s.revive_countdown == 2  # op 参数通道生效


def test_damage_defeated_countdown(db, make_game):
    """觉醒·樱花妖"可以对敌方气绝式神造成伤害，若如此做改为使其倒计时+1"：
    伪关键字与 op 参数（绚烂之舞"无论是否气绝"）两通道；无授权则管线拦截。"""
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["damage_defeated_countdown"])
    _defeated_pool_card(db, 10010151, 100101, "damage")
    _defeated_pool_card(db, 10010351, 100103, "damage", allow_defeated=True)
    _defeated_pool_card(db, 10010251, 100102, "damage")
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    _kill(g, 1, 0)
    es = pb.shikigami[0]
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    assert es.defeated and es.revive_countdown == 4  # +1
    F.play(g, 0, 10010251, target=Ref(player=1, shikigami=0))
    assert es.revive_countdown == 4  # 无授权：管线拦截不变
    F.play(g, 0, 10010351, target=Ref(player=1, shikigami=0))
    assert es.revive_countdown == 5  # op 参数通道


# ---------- 绽放（mass_revive op）与樱吹雪（repeat_on_kill/repeat_on_revive） ----------

def test_mass_revive_countdown_damage(db, make_game):
    """绽放"复活所有式神，每个式神对其牌手造成等同于其气绝倒计时的伤害"：
    双方气绝者全部复活（快照复活前倒计时），随后各自对其牌手造伤。"""
    db.cards[10010151] = F.card(10010151, token=True,
                                steps=[F.Step(op="mass_revive",
                                              countdown_damage=True)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    _kill(g, 0, 1, countdown=2)
    _kill(g, 1, 0)  # 倒计时 3
    F.play(g, 0, 10010151)
    assert not pa.shikigami[1].defeated and not pb.shikigami[0].defeated
    assert pa.health == 28  # 己方式神倒计时 2 → 对己方牌手 2
    assert pb.health == 27  # 敌方式神倒计时 3 → 对敌方牌手 3


def test_repeat_on_kill(db, make_game):
    """樱吹雪伤害侧"若击杀式神则重复此效果"：造成新气绝即对原目标列表重复，
    已气绝者被管线拦截，无新气绝即停。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="damage", amount=5, repeat_on_kill=True,
                      target=T(kind="all", pool="enemy_shikigami"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pb.shikigami[1].health = 9  # 超上限直改（测试惯例）：两轮 5 才致死
    F.play(g, 0, 10010151)
    assert pb.shikigami[0].defeated      # 4 HP：第一轮死
    assert pb.shikigami[1].defeated      # 9 HP：第二轮死（触发第三轮无新击杀收束）
    assert pb.shikigami[2].defeated      # 6 HP：第二轮死
    assert pb.shikigami[3].defeated      # 5 HP：第一轮死


def test_repeat_on_kill_off(db, make_game):
    """对照：无 repeat_on_kill 不重复。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="damage", amount=5,
                      target=T(kind="all", pool="enemy_shikigami"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pb.shikigami[1].health = 9
    F.play(g, 0, 10010151)
    assert pb.shikigami[0].defeated and pb.shikigami[1].health == 4


def test_repeat_on_revive(db, make_game):
    """樱吹雪治疗侧"若复活式神则重复此效果"：转化复活即对原目标列表重复
    （链式把更高倒计时者也减到复活），无新复活即停。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="heal", amount=3, allow_defeated=True,
                      repeat_on_revive=True,
                      target=T(kind="all", pool="friendly_shikigami",
                               include_defeated=True))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    _kill(g, 0, 1, countdown=1)
    _kill(g, 0, 2, countdown=2)
    pa.shikigami[0].health = 1
    F.play(g, 0, 10010151)
    assert not pa.shikigami[1].defeated  # 第一轮倒计时 1→0 复活
    assert not pa.shikigami[2].defeated  # 第二轮 1→0 复活（重复链）
    assert pa.shikigami[0].health == 4   # 存活目标正常受治疗


def test_defeated_convert_keyword_scope(db, make_game):
    """气绝转化伪关键字通道的侧向与在场判定（维护者答复(3)）：
    heal_defeated_countdown 仅转化己方气绝目标（气绝敌方不转）、
    damage_defeated_countdown 仅转化敌方气绝目标（气绝己方不转）；
    结算时来源式神气绝则伪关键字通道不转化（allow_defeated 参数通道不受限）。"""
    from core.model import ExecContext
    db.shikigami[100101] = F.shiki(  # 持有者双通道（3/4）
        100101, power=3, health=4,
        keywords=["heal_defeated_countdown", "damage_defeated_countdown"])
    db.cards[10010151] = F.card(  # 双侧波治疗（无 allow_defeated——纯能力通道）
        10010151, token=True,
        steps=[F.Step(op="heal", amount=3,
                      target=T(kind="all", pool="any_shikigami",
                               include_defeated=True))])
    db.cards[10010152] = F.card(  # 双侧波伤害
        10010152, token=True,
        steps=[F.Step(op="damage", amount=3,
                      target=T(kind="all", pool="any_shikigami",
                               include_defeated=True))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    _kill(g, 0, 1)  # 己方气绝 cd3
    _kill(g, 1, 1)  # 敌方气绝 cd3
    F.play(g, 0, 10010151)
    assert pa.shikigami[1].revive_countdown == 2  # 己方转化 -1
    assert pb.shikigami[1].revive_countdown == 3  # 气绝敌方不受治疗转化
    F.play(g, 0, 10010152)
    assert pb.shikigami[1].revive_countdown == 4  # 敌方转化 +1
    assert pa.shikigami[1].revive_countdown == 2  # 气绝己方不受伤害转化
    # 在场判定：来源气绝后伪关键字通道失效（_resolve_block 直调绕过出牌在场校验，
    # 模拟"确定使用此牌后、结算前能力离场"——test_countdown.py 直调先例）
    _kill(g, 0, 0)
    g._resolve_block(db.cards[10010151].effects,
                     ExecContext(controller=0, source=Ref(player=0, shikigami=0)))
    assert pa.shikigami[1].revive_countdown == 2  # 能力离场：不转化
    g._drain_queue()  # 直调结算后兜底排空


def test_pool_include_extensions(db, make_game):
    """目标池扩展键：include_defeated 扩 any_shikigami 池（双侧未离场气绝者入池）；
    include_player（friendly_injured 池追加受伤的己方牌手——"己方受伤角色"含牌手，
    维护者答复(4)）。"""
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    _kill(g, 0, 2)
    _kill(g, 1, 2)
    spec = T(kind="choose", pool="any_shikigami", include_defeated=True)
    refs = targets_mod.spec_pool_refs(g, spec, 0, targeted=True)
    assert Ref(player=0, shikigami=2) in refs  # 己方气绝者入池
    assert Ref(player=1, shikigami=2) in refs  # 敌方气绝者入池
    spec = T(kind="choose", pool="friendly_injured", include_player=True)
    pa.shikigami[0].health = 1  # 受伤式神对照
    refs = targets_mod.spec_pool_refs(g, spec, 0, targeted=True)
    assert Ref(player=0) not in refs  # 牌手满血不入池
    assert Ref(player=0, shikigami=0) in refs
    pa.health = 27  # 牌手受伤
    refs = targets_mod.spec_pool_refs(g, spec, 0, targeted=True)
    assert Ref(player=0) in refs  # 受伤牌手入池


# ---------- 飘零之舞：assault_any_target / friendly_combat_heal / 攻击式神连击 ----------

def test_assault_any_target(db, make_game):
    """飘零之舞"出击时可以指定攻击任何其他角色"：可指定己方式神/敌方准备区
    式神（攻击己方式神无反击）；不能指定攻击者本人；无伪关键字带目标出击照旧
    拒绝。"""
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["assault_any_target"])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    own = pa.shikigami[1]  # 1/6
    g.apply({"op": "assault", "index": 0,
             "target": Ref(player=0, shikigami=1)})
    assert own.health == 3            # 受到 3 战斗伤害
    assert pa.shikigami[0].health == 4  # 己方被攻击者不反击
    g2 = make_game()
    pa2, pb2 = F.battle_setup(g2, levels={0: 1, 1: 1})
    g2.apply({"op": "assault", "index": 0,
              "target": Ref(player=1, shikigami=1)})  # 敌方准备区式神
    assert pb2.shikigami[1].health == 3
    pa2.assaults_left = 1  # 腾出第二次出击次数（目标校验在次数检查之后到达）
    with pytest.raises(Exception):  # 不能指定攻击者本人
        g2.apply({"op": "assault", "index": 0,
                  "target": Ref(player=0, shikigami=0)})


def test_assault_target_without_keyword_rejected(db, make_game):
    """对照：无 assault_any_target/追猎的式神出击不能选择目标。"""
    g = make_game()
    F.battle_setup(g)
    with pytest.raises(Exception):
        g.apply({"op": "assault", "index": 0,
                 "target": Ref(player=1, shikigami=1)})


def test_friendly_combat_heal(db, make_game):
    """飘零之舞"攻击其他己方角色时改为其恢复等量于伤害的生命"。"""
    db.shikigami[100101] = F.shiki(
        100101, power=3, health=4,
        keywords=["assault_any_target", "friendly_combat_heal"])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    own = pa.shikigami[1]  # 1/6
    own.health = 2
    g.apply({"op": "assault", "index": 0,
             "target": Ref(player=0, shikigami=1)})
    assert own.health == 5               # 恢复 3（= 攻击者力量）而非受伤
    assert pa.shikigami[0].health == 4   # 无反击
    assert pb.health == 30


def test_combo_grant_on_attacking_shikigami(db, make_game):
    """飘零之舞"攻击式神时获得[连击]"：纯数据路径（形态能力挂 on_before_assault +
    attacker_shikigami/victim_kind 条件 + grant_keyword scope=battle）。"""
    db.cards[10010151] = F.card(
        10010151, card_type="form", form_power=3, form_health=7, token=True,
        abilities=[F.block(
            F.Step(op="grant_keyword", keyword="combo", scope="battle",
                   target=T(kind="self")),
            when="on_before_assault",
            condition={"attacker_shikigami": "self", "victim_kind": "shikigami"})])
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)
    g.apply({"op": "assault", "index": 0})  # 无目标：被攻击者=牌手 → 不获连击
    assert pb.health == 27
    F.pass_turns(g, 2)  # 回到己方回合（攻击者已退回准备区）
    F.move(g, 1, 0)  # 敌方式神入战斗区
    es = pb.shikigami[0]
    es.health = 10
    g.apply({"op": "assault", "index": 0})  # 攻击式神：连击两段 3
    assert es.health == 4


# ---------- 落英缤纷/晚樱之意：event_base_power 次数与 prefer_wounded 过滤 ----------

def test_event_base_power_repeat(db, make_game):
    """落英缤纷"重复该式神基础力量的次数"：repeat count={"event_base_power": key}
    读触发事件 Ref 所指式神的当前基础力量。"""
    db.shikigami[100102] = F.shiki(  # 持有者（1/6）
        100102, power=1, health=6,
        ability=F.block(
            F.Step(op="repeat", count={"event_base_power": "shikigami"},
                   steps=[{"op": "buff_power", "amount": 1, "perm": True,
                           "target": {"kind": "self"}}]),
            when="on_shikigami_revived",
            condition={"shikigami_side": "friendly"}))
    db.cards[10010251] = F.card(  # 复活己方式神（触发器）
        10010251, shikigami=100102, token=True,
        steps=[F.Step(op="revive", target=T(kind="all", pool="friendly_defeated"))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    _kill(g, 0, 0)  # 气绝的己方式神基础力量 3
    F.play(g, 0, 10010251)
    assert not pa.shikigami[0].defeated
    assert pa.shikigami[1].perm_power == 3  # 重复 3 次 +1


def test_prefer_wounded(db, make_game):
    """晚樱之意"优先受伤或气绝式神"：候选中存在受伤/气绝者时收窄到该子集再随机
    （子集唯一时确定命中）；气绝者入池需 include_defeated。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="heal", amount=2,
                      target=T(kind="all", pool="friendly_shikigami",
                               random=1, prefer_wounded=True))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    pa.shikigami[1].health = 2  # 唯一受伤者
    F.play(g, 0, 10010151)
    assert pa.shikigami[1].health == 4 and pa.shikigami[0].health == 4
    # 气绝者优先（配合 include_defeated + allow_defeated 转化通道）
    db.cards[10010152] = F.card(
        10010152, token=True,
        steps=[F.Step(op="heal", amount=2, allow_defeated=True,
                      target=T(kind="all", pool="friendly_shikigami",
                               include_defeated=True, random=1,
                               prefer_wounded=True))])
    g2 = make_game()
    pa2, pb2 = F.battle_setup(g2, levels={0: 1, 1: 1, 2: 1})
    _kill(g2, 0, 2)  # 唯一气绝者（其余满血）
    F.play(g2, 0, 10010152)
    assert pa2.shikigami[2].revive_countdown == 2  # 确定命中气绝者


# ==========================================================================
# 真实数据端到端（人面树 100401 / 樱花妖 100403，db/04_canghaidaoming）
#
# 机制边界与负例已在上方 dummy 层覆盖；本节只验真实卡面数据接线（数值、
# 目标池、关键字、形态切换链）。双方同队，A 9 鬼火（battle_setup）。
# ==========================================================================

RMS_TEAM = [100401, 100101, 100102, 100125]  # 人面树/白狼/兵俑/一目连
YHY_TEAM = [100403, 100101, 100102, 100125]  # 樱花妖/白狼/兵俑/一目连


def _rg(real_game, team, levels=None):
    g = real_game(team)
    pa, pb = F.battle_setup(g, levels)
    return g, pa, pb


def test_real_form_no_retreat(real_game):
    """扎根（10040101）：no_retreat 形态出击后己方回合开始不移回准备区。"""
    g, pa, pb = _rg(real_game, RMS_TEAM)
    F.play(g, 0, 10040101)
    s = pa.shikigami[0]
    assert s.form is not None and s.form.id == 10040101
    assert (s.base_power, s.base_health) == (2, 7)  # 形态身材覆盖
    g.apply({"op": "assault", "index": 0})  # 敌方战斗区空：打牌手
    assert pa.combat_index == 0
    F.pass_turns(g, 2)  # 经敌方回合回到己方回合开始
    assert pa.combat_index == 0 and s.form.id == 10040101  # 不移回


def test_real_switch_form_faction(real_game):
    """神木诅咒（10040102）：一目连结附风符·破 → 变诅咒之木（1/6 满血、紫岩覆写、
    旧形态入墓），气绝后派系还原苍叶。"""
    g, pa, pb = _rg(real_game, RMS_TEAM, levels={0: 1, 3: 1})
    F.play(g, 0, 10012501)  # 风符·破结附一目连（index 3）
    s = pa.shikigami[3]
    assert s.form is not None and s.form.id == 10012501
    assert s.faction == "苍叶"
    s.health = 3  # 受伤，验证切换后回满
    F.play(g, 0, 10040102, target=Ref(player=0, shikigami=3))
    assert s.form is not None and s.form.id == 10040151
    assert (s.base_power, s.base_health) == (1, 6) and s.health == 6
    assert s.faction == "紫岩" and s.perm_faction == "苍叶"  # 临时覆写
    assert any(c.id == 10012501 for c in pa.graveyard)  # 旧形态入墓
    _kill(g, 0, 3)
    assert s.form is None and s.faction == "苍叶"  # 形态随气绝离场，派系还原


def test_real_combat_base_health(real_game):
    """神木庇佑（10040104）：白狼获得 combat_base_health，出击以当前生命造伤。"""
    g, pa, pb = _rg(real_game, RMS_TEAM, levels={0: 2, 1: 1})
    F.play(g, 0, 10040104, target=Ref(player=0, shikigami=1))
    s = pa.shikigami[1]  # 白狼 3/4
    s.health = 2
    F.move(g, 1, 2)  # 敌方兵俑（1/6）入战斗区
    g.apply({"op": "assault", "index": 1})
    assert pb.shikigami[2].health == 4  # 受 2（=白狼当前生命）而非 3（力量）
    assert s.health == 1  # 受兵俑反击 1，存活


def test_real_delayed_health_of(real_game):
    """灾厄之花（10040105）：被选式神在其下个回合结束时受等同于自身生命的伤害。"""
    g, pa, pb = _rg(real_game, RMS_TEAM, levels={0: 2})
    F.play(g, 0, 10040105, target=Ref(player=1, shikigami=1))  # 点敌方白狼
    F.pass_turns(g, 1)  # 进入敌方回合：不触发
    assert not pb.shikigami[1].defeated
    F.pass_turns(g, 1)  # 敌方回合结束：白狼受等同于其生命（4）的伤害
    assert pb.shikigami[1].defeated


def test_real_field_half_health(real_game):
    """凋零之森（10040107）：每个牌手回合开始时对其所有角色造成等同于其一半生命
    （向下取整）的伤害。"""
    g, pa, pb = _rg(real_game, RMS_TEAM, levels={0: 3, 1: 1})  # 白狼 lv1 在场才吃幻境伤害
    pb.shikigami[1].health = 5  # 奇数生命验证向下取整
    F.play(g, 0, 10040107)
    F.pass_turns(g, 1)  # 敌方回合开始
    assert pb.shikigami[1].health == 3  # 白狼 5 → 5-floor(5/2)=3
    assert pb.shikigami[0].health == 3  # 人面树 6→3
    assert pb.health == 15  # 牌手 30→15
    F.pass_turns(g, 1)  # 己方回合开始（对己方同样生效）
    assert pa.shikigami[1].health == 2  # 白狼 4→2
    assert pa.health == 15


def test_real_power_eq_health(real_game):
    """觉醒·人面树（10040108）：力量等于当前生命（6+2=8），随生命浮动。"""
    g, pa, pb = _rg(real_game, RMS_TEAM, levels={0: 3})
    F.play(g, 0, 10040108)
    s = pa.shikigami[0]
    assert s.max_health == 8 and s.awakened == 10040108
    g._refresh_stat_auras()
    assert s.eff_power == 8
    s.health = 5
    g._refresh_stat_auras()
    assert s.eff_power == 5


def test_real_spell_methods(real_game):
    """樱落（10040301）双择：damage 对敌方式神 3 伤 / heal 为己方式神恢复 6（封顶）。"""
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 1, 1: 1})  # 白狼 lv1 在场才入目标池
    c = F.give(g, 0, 10040301)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "damage",
             "target": Ref(player=1, shikigami=1)})
    assert pb.shikigami[1].health == 1  # 敌方白狼 4→1
    pa.shikigami[1].health = 2
    c = F.give(g, 0, 10040301)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "heal",
             "target": Ref(player=0, shikigami=1)})
    assert pa.shikigami[1].health == 4  # 2+6 封顶 max 4


def test_real_heal_defeated_countdown(real_game):
    """樱落 heal 法对气绝己方式神：转化倒计时-1（heal_defeated_countdown 基础能力），
    减到 0 立即复活满血。"""
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 1, 2: 1})  # 兵俑 lv1 在场
    _kill(g, 0, 2)  # 己方兵俑气绝，倒计时 3
    s = pa.shikigami[2]
    c = F.give(g, 0, 10040301)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "heal",
             "target": Ref(player=0, shikigami=2)})
    assert s.defeated and s.revive_countdown == 2  # 转化 -1 而非回血
    s.revive_countdown = 1
    c = F.give(g, 0, 10040301)
    g.apply({"op": "play_card", "uid": c.uid, "play_method": "heal",
             "target": Ref(player=0, shikigami=2)})
    assert not s.defeated and s.health == s.max_health == 6  # 减到 0 复活满血


def test_real_awaken_keyword_rebind(real_game):
    """觉醒·樱花妖（10040305）：能力伪关键字换绑为 heal+damage 双转化通道。"""
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 2})
    s = pa.shikigami[0]
    assert s.perm_keywords == ["heal_defeated_countdown"]  # 基础能力伪关键字
    F.play(g, 0, 10040305)
    assert s.awakened == 10040305
    assert set(s.perm_keywords) == {"heal_defeated_countdown",
                                    "damage_defeated_countdown"}


def test_real_after_assault_convert(real_game):
    """绚烂之舞（10040304）：敌方式神攻击后对其 2 伤；攻击者已气绝时转化倒计时+1。"""
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 2})
    F.play(g, 0, 10040304)  # 樱花妖结附绚烂之舞
    F.move(g, 0, 1)  # 己方白狼（3/4）入战斗区
    F.pass_turns(g, 1)  # 敌方回合
    es = pb.shikigami[1]  # 敌方白狼
    es.health = 3
    g.apply({"op": "assault", "index": 1})  # 撞己方白狼：受反击 3 → 气绝（cd3）
    assert es.defeated and es.revive_countdown == 4  # 绚烂之舞转化 +1


def test_real_mass_revive(real_game):
    """绽放（10040303）：复活双方气绝式神，每个被复活者按其复活前倒计时对各自
    牌手造伤。"""
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 2, 2: 1})  # 兵俑 lv1 才可被复活
    _kill(g, 0, 2, countdown=2)  # 己方兵俑 cd2
    _kill(g, 1, 1)  # 敌方白狼 cd3
    F.play(g, 0, 10040303)
    assert not pa.shikigami[2].defeated and not pb.shikigami[1].defeated
    assert pa.health == 28  # 兵俑倒计时 2 → 己方牌手 2
    assert pb.health == 27  # 白狼倒计时 3 → 敌方牌手 3


def test_real_wave_repeat(real_game):
    """樱吹雪（10040307，thoughts 答复(2)(3) 定案）：伤害/治疗各为敌我同池的单一
    并行波次（any_shikigami + include_defeated + 按 id 排除樱花妖），击杀→伤害整波
    重复、复活→治疗整波重复，伤害段全部重复完才进治疗段；气绝目标按结算时能力
    转化——未觉醒气绝敌方不受伤害转化、气绝己方治疗 -1（复活触发治疗整波重复）、
    气绝敌方不受治疗转化；觉醒后气绝敌方伤害转化 +1。"""
    # 局 1（未觉醒）：伤害波击杀敌方白狼 → 整波重复；治疗波复活己方兵俑 → 整波重复
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 3, 2: 1})
    pb.shikigami[1].health = 2  # 敌方白狼 2 血（首波致死）
    _kill(g, 0, 2, countdown=1)  # 己方兵俑气绝 cd1（治疗波转化复活）
    F.play(g, 0, 10040307)
    w = pb.shikigami[1]
    assert w.defeated and w.revive_countdown == 3  # 未觉醒：气绝敌方伤害拦截（cd 不变）
    assert pb.shikigami[2].health == 6  # 敌方兵俑 6→4→2（伤害两波），治疗两波 2→5→6
    assert pb.shikigami[3].health == 6  # 敌方一目连同理
    assert not pa.shikigami[2].defeated and pa.shikigami[2].health == 6  # 治疗波复活满血
    # 局 2（觉醒）：气绝敌方目标伤害转化 +1；无复活则治疗波不重复
    g, pa, pb = _rg(real_game, YHY_TEAM, levels={0: 3})
    F.play(g, 0, 10040305)  # 觉醒·樱花妖（换绑双通道）
    pb.shikigami[1].health = 2
    F.play(g, 0, 10040307)
    w = pb.shikigami[1]
    assert w.defeated and w.revive_countdown == 4  # 波1 击杀 cd3 → 波2 转化 +1
    assert pb.shikigami[2].health == 5  # 敌方兵俑 6→4→2，治疗单波 2→5（无复活不重复）
    assert pb.shikigami[0].health == 5  # 镜像同名樱花妖按数据 id 排除，不受波及


def test_real_switch_form_chain(real_game):
    """落英缤纷⇄晚樱之意（10040351/52）：己方式神复活→按复活者基础力量次数打敌方
    后切晚樱；敌方式神气绝→按气绝者基础力量次数奶己方（优先受伤）后切回；
    落英缤纷进场羁绊奶（桃花妖在场）。"""
    team = [100403, 100119, 100102, 100103]  # 樱花妖/桃花妖/兵俑/茨木（紫岩+红莲两派系）
    g, pa, pb = _rg(real_game, team, levels={0: 2, 1: 1, 2: 1, 3: 1})
    pa.shikigami[2].health = 3  # 己方兵俑受伤（羁绊唯一目标）
    F.play(g, 0, 10040351)  # 结附落英缤纷（协战衍生牌直接发手打出）
    s = pa.shikigami[0]
    assert s.form is not None and s.form.id == 10040351
    assert pa.shikigami[2].health == 6  # 羁绊：桃花妖奶受伤兵俑 3
    _kill(g, 0, 3, countdown=1)  # 己方茨木气绝 cd1
    b_total = sum(x.health for x in pb.shikigami)  # 5+6+6+4=21
    F.play(g, 0, 10040303)  # 绽放复活茨木 → 落英缤纷触发
    assert not pa.shikigami[3].defeated
    assert pa.health == 29  # 复活者倒计时 1 → 对己方牌手 1
    # 茨木基础力量 3 → 随机对敌方式神 1 伤 ×3（总量断言规避随机）
    assert sum(x.health for x in pb.shikigami) == b_total - 3
    assert s.form.id == 10040352  # 切晚樱之意
    pa.shikigami[2].health = 4  # 兵俑再受伤（晚樱唯一受伤目标）
    _kill(g, 1, 0)  # 敌方樱花妖气绝 → 晚樱之意触发
    g._drain_queue()  # 直调 check_defeated 后手动排空（on_shikigami_defeated 为延时时机）
    assert pa.shikigami[2].health == 6  # 樱花妖基础力量 2 → 奶 2×2 全落兵俑
    assert s.form.id == 10040351  # 切回落英缤纷


def test_real_bond_include_player(real_game):
    """落英缤纷（10040351）羁绊"己方受伤角色"含牌手（thoughts 答复(4)）：
    仅己方牌手受伤时必奶牌手。"""
    team = [100403, 100119, 100102, 100103]  # 樱花妖/桃花妖/兵俑/茨木
    g, pa, pb = _rg(real_game, team, levels={0: 2, 1: 1})
    pa.health = 27  # 己方牌手受伤（式神全满血，池内唯一目标）
    F.play(g, 0, 10040351)  # 结附落英缤纷 → 羁绊：桃花妖奶己方受伤角色 3
    assert pa.health == 30
