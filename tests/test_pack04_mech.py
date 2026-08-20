"""04 沧海刀鸣包机制测试（人面树/樱花妖批次）。

分两层：dummy 层用合成数据验证引擎机制/op 的边界与负例；文末"真实数据端到端"
一节用 db/04_canghaidaoming 真实卡面验证数据接线。按机制归组命名，
式神/卡牌名只出现在 docstring 与注释中。
"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from core import targets as targets_mod
from db.schema import InvocationDef
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


# ---------- 灵咒实体化（keywords/倒计时 once/bonus 继承/inv_mod/inv_override） ----------

def test_invocation_keywords_grant_and_revoke(db, make_game):
    """灵咒 keywords：结附期间授予持有者、移除即按实例撤销；"stun" 特判为眩晕
    （kind="invocation" 条目），不参与回合批次过期清理。"""
    db.invocations["迟钝"] = InvocationDef(name="迟钝", keywords=["stun"])
    db.invocations["守护"] = InvocationDef(name="守护", keywords=["veil"])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("守护", player=0, target=Ref(player=0, shikigami=0))
    assert s.is_stunned and "veil" in s.keywords
    F.pass_turns(g, 2)  # 双方回合批次各过一次：灵咒眩晕不被误清
    assert s.is_stunned
    g._remove_invocation(s, s.invocations[0], reason="测试")
    assert not s.is_stunned and "veil" in s.keywords  # 迟钝移除只解除自己的眩晕
    g._remove_invocation(s, s.invocations[0], reason="测试")
    assert "veil" not in s.keywords


def test_invocation_countdown_once_removes_body(db, make_game):
    """迟钝型灵咒倒计时块（once）：结附即注册式神级倒计时、归零生效（眩晕中仍
    发起攻击——launch_attack 不查眩晕）后移除灵咒本体而非重置。"""
    db.invocations["迟钝"] = InvocationDef(
        name="迟钝", keywords=["stun"],
        abilities=[F.block(F.Step(op="launch_attack"), countdown=2, once=True)])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))
    assert (s.countdown, s.countdown_once) == (2, True) and s.is_stunned
    F.pass_turns(g, 2)  # 回到己方回合开始：2→1
    assert s.countdown == 1 and s.invocations
    F.pass_turns(g, 2)  # 再到己方回合开始：1→0 生效
    assert pb.health == 27  # 眩晕中发起攻击：3 力量打空战斗区牌手
    assert s.invocations == []  # 生效后移除本体
    assert s.countdown is None and not s.is_stunned  # 倒计时清除、眩晕随灵咒解除


def test_invocation_bonus_inherit_and_defeat_reset(db, make_game):
    """数值增强 bonus 挂灵咒条目：同源同名再结附（唯一性移除旧条目）时新条目继承
    旧 bonus；气绝移除即重置。"""
    db.invocations["玉"] = InvocationDef(name="玉", unique="unique", power=1)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    s0, s1 = pa.shikigami[0], pa.shikigami[1]  # 3/4 与 1/6
    g.attach_invocation("玉", player=0, target=Ref(player=0, shikigami=0))
    s0.invocations[0]["bonus"] = 1  # 数据通道外的测试注入："效果+1"
    assert s0.eff_power == 5  # 3 + power1 + bonus1
    g.attach_invocation("玉", player=0, target=Ref(player=0, shikigami=1))  # 同源再结附
    assert s0.invocations == [] and s0.eff_power == 3  # 旧条目唯一性移除
    assert s1.invocations[0]["bonus"] == 1  # 新条目继承旧 bonus
    assert s1.eff_power == 3  # 1 + power1 + bonus1
    _kill(g, 0, 1)
    assert s1.invocations == []  # 气绝移除：增强随之重置


def test_invocation_inv_mod(db, make_game):
    """inv_mod 修饰层（持有方牌手 ext）：eff = (快照+bonus)*mult+add，按灵咒名+
    持有者式神 id 条件命中；不限灵咒来源敌我（来源敌方的灵咒同样被持有方修饰）。"""
    db.invocations["玉"] = InvocationDef(name="玉", power=1)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    s0, s1 = pa.shikigami[0], pa.shikigami[1]  # 100101 3/4 与 100102 1/6
    g.attach_invocation("玉", player=0, target=Ref(player=0, shikigami=0))
    assert s0.eff_power == 4
    pa.ext["inv_mod"] = [{"name": "玉", "mult": 2, "add": 1}]
    g._refresh_invocation_mods(0)
    assert s0.eff_power == 6  # 3 + (1*2+1)
    pa.ext["inv_mod"] = [{"name": "玉", "shikigami": 100102, "add": 5}]  # 持有者条件不命中
    g._refresh_invocation_mods(0)
    assert s0.eff_power == 4
    pa.ext["inv_mod"] = [{"name": "玉", "add": 2}]
    g.attach_invocation("玉", player=1, target=Ref(player=0, shikigami=1))  # 来源敌方
    # 结附末尾自动重算持有方修饰：两条目（含敌方来源）同被修饰
    assert s0.eff_power == 6 and s1.eff_power == 4  # 3+(1+2) / 1+(1+2)


def test_invocation_override_unique_and_attach_all(db, make_game):
    """inv_override 覆写（祈愿之翼通道）：unique 覆写为 shikigami_unique 后同式神
    再结附才移除、他式神共存；attach_all_friendly 改为己方全体在场式神结附。"""
    db.invocations["守护"] = InvocationDef(name="守护", unique="unique", power=1)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})  # 3 号位 0 级不在场
    pa.ext["inv_override"] = {"守护": {"unique": "shikigami_unique"}}
    g.attach_invocation("守护", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("守护", player=0, target=Ref(player=0, shikigami=1))
    assert len(pa.shikigami[0].invocations) == 1  # 覆写后不再是全场唯一：共存
    assert len(pa.shikigami[1].invocations) == 1
    g.attach_invocation("守护", player=0, target=Ref(player=0, shikigami=0))
    assert len(pa.shikigami[0].invocations) == 1  # 同式神再结附：旧的被移除（不能叠加）
    pa.ext["inv_override"] = {"守护": {"unique": "shikigami_unique",
                                       "attach_all_friendly": True}}
    g.attach_invocation("守护", player=0, target=Ref(player=0, shikigami=0))
    for i in (0, 1, 2):
        assert len(pa.shikigami[i].invocations) == 1  # 全体在场式神各结附一个（不叠加）
    assert pa.shikigami[3].invocations == []  # 未在场不结附


def test_invocation_attached_event_uid(db, make_game):
    """on_invocation_attached 载荷 uid = 灵咒条目 uid（局内对象身份）。"""
    db.invocations["刀鸣"] = InvocationDef(name="刀鸣", power=1)
    g = make_game()
    pa, pb = F.battle_setup(g)
    seen: list[dict] = []
    orig_emit = g.emit

    def spy(name, **kw):
        if name == "on_invocation_attached":
            seen.append(kw)
        return orig_emit(name, **kw)

    g.emit = spy
    g.attach_invocation("刀鸣", player=0, target=Ref(player=0, shikigami=0))
    entry = pa.shikigami[0].invocations[0]
    assert seen and seen[0]["uid"] == entry["uid"]


# ---------- 出击/战斗牌替换（伪关键字 replace_action:迟钝，跳跳哥哥） ----------

def _dull_inv(db, with_countdown: bool = False):
    """合成'迟钝'灵咒：眩晕（+ 可选倒计时块）。"""
    abilities = []
    if with_countdown:
        abilities = [F.block(F.Step(op="launch_attack"), countdown=2, once=True)]
    db.invocations["迟钝"] = InvocationDef(name="迟钝", keywords=["stun"],
                                           abilities=abilities)


def test_replace_action_assault(db, make_game):
    """跳跳哥哥"出击时改为结附'迟钝'"：完全替换动作——不进战斗流程（敌方牌手
    不掉血、攻击者不进战斗区），鬼火/出击次数照常消耗，改为对自身结附迟钝；
    结附后眩晕中不能再出击（替换只在无迟钝时实际发生）。"""
    _dull_inv(db)
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["replace_action:迟钝"])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    orb0 = pa.orb
    g.apply({"op": "assault", "index": 0})
    assert pb.health == 30 and pa.combat_index is None  # 未发起攻击/未进战斗区
    assert pa.orb == orb0 - 1 and pa.assaults_left == 0  # 鬼火/出击次数照常消耗
    assert [e["name"] for e in s.invocations] == ["迟钝"] and s.is_stunned
    pa.orb = 3
    pa.assaults_left = 1
    with pytest.raises(Exception):  # 眩晕中不能出击
        g.apply({"op": "assault", "index": 0})


def test_replace_action_combat_card(db, make_game):
    """跳跳哥哥"使用战斗牌时改为结附'迟钝'"：战斗牌其余文本效果（steps）照常
    结算、仅战斗本身跳过（无战斗伤害、不进战斗区），牌入墓地。"""
    _dull_inv(db)
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["replace_action:迟钝"])
    db.cards[10010151] = F.card(  # 棺击位：战斗 +0/+0，附一个抽牌 step 验证照常结算
        10010151, card_type="combat", token=True,
        steps=[F.Step(op="draw", count=1)])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    hand0 = len(pa.hand)
    F.play(g, 0, 10010151)
    assert pb.health == 30 and pa.combat_index is None  # 战斗跳过
    assert len(pa.hand) == hand0 + 1  # 其余 steps 照常（抽 1）
    assert [e["name"] for e in s.invocations] == ["迟钝"]
    assert any(c.id == 10010151 for c in pa.graveyard)  # 牌正常入墓


def test_replace_action_awaken_rebind(db, make_game):
    """觉醒·跳跳哥哥：冒号参数伪关键字按前缀换绑（移除基础侧、授予觉醒侧，
    不重复），觉醒后替换照常生效。"""
    _dull_inv(db)
    db.shikigami[100101] = F.shiki(100101, power=3, health=4,
                                   keywords=["replace_action:迟钝"])
    db.cards[10010152] = F.card(  # 觉醒·跳跳哥哥位（+10/+10 与本机制无关，置 0）
        10010152, subtype="awaken", level=2, token=True,
        keywords=["replace_action:迟钝"])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 2})
    s = pa.shikigami[0]
    assert s.perm_keywords == ["replace_action:迟钝"]
    F.play(g, 0, 10010152)
    assert s.awakened == 10010152
    assert s.perm_keywords == ["replace_action:迟钝"]  # 换绑不重复
    g.apply({"op": "assault", "index": 0})
    assert pb.health == 30 and [e["name"] for e in s.invocations] == ["迟钝"]


def test_play_gate_shikigami_countdown_free(db, make_game):
    """觉醒·跳跳哥哥"不能在跳跳哥哥有[倒计时]时使用"：play_condition
    {shikigami_countdown_free: <式神id>}——有倒计时（含迟钝结附的倒计时2）不可用，
    无倒计时可用。"""
    _dull_inv(db, with_countdown=True)
    db.cards[10010152] = F.card(10010152, subtype="awaken", level=2, token=True,
                                play_condition={"shikigami_countdown_free": 100101})
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 2})
    F.play(g, 0, 10010152)  # 无倒计时：可用
    g2 = make_game()
    pa2, pb2 = F.battle_setup(g2, levels={0: 2})
    g2.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))  # 倒计时2
    with pytest.raises(Exception):
        F.play(g2, 0, 10010152)


# ---------- 棺材占位实体（to_coffin / coffin_revive / 气绝旗标与形态 tag） ----------

def _coffin_def(db, cid: int = 10010199, assault_ids=()):
    """合成棺材占位实体（0/3 不能攻击，倒计时1 归零复活原式神）。"""
    db.shikigami[cid] = F.shiki(
        cid, name="棺材", kind="transform", power=0, health=3,
        no_attack=True, coffin_assault=list(assault_ids),
        abilities=[F.block(F.Step(op="coffin_revive", target=T(kind="self")),
                           countdown=1, once=True)])


def test_coffin_replace_on_defeat_flag(db, make_game):
    """不弃"使一个非召唤物式神获得'本回合气绝时替换为棺材'"（ext 旗标
    coffin_on_defeat=实体 id）：气绝结算完成后落准备区替换为棺材（0/3、倒计时1、
    属原牌手）；替换期间原式神的牌不可使用（transform_owner 口径）。"""
    _coffin_def(db)
    db.cards[10010151] = F.card(  # 不弃位：授予旗标
        10010151, token=True, target=T(kind="choose", pool="any_shikigami"),
        steps=[F.Step(op="bump_ext", key="coffin_on_defeat", value=10010199)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    F.play(g, 0, 10010151, target=Ref(player=0, shikigami=1))
    s = pa.shikigami[1]  # 100102（1/6）
    _kill(g, 0, 1)
    c = pa.shikigami[1]
    assert c.id == 10010199 and not c.defeated and c.health == 3  # 替换为棺材
    assert c.countdown == 1 and c.countdown_once  # 倒计时1
    assert pa.combat_index is None  # 气绝替换落准备区
    with pytest.raises(Exception):  # 原式神的牌不可使用
        F.play(g, 0, 10010201)


def test_coffin_form_tag(db, make_game):
    """罡身阵"跳跳哥哥气绝时，改为将其替换为'棺材'"：形态 tags
    `coffin_on_defeat:<实体id>` 通道（旗标在形态消灭前捕获）。"""
    _coffin_def(db)
    db.cards[10010151] = F.card(10010151, card_type="form", form_power=7,
                                form_health=6, token=True,
                                tags=["coffin_on_defeat:10010199"])
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.play(g, 0, 10010151)
    _kill(g, 0, 0)
    c = pa.shikigami[0]
    assert c.id == 10010199 and not c.defeated and c.form is None  # 形态已消灭、入棺


def test_coffin_countdown_revive(db, make_game):
    """棺材倒计时1 在所属方回合开始 -1；归零→移除棺材、原式神按正常复活进场
    （基础身材满血、等级/永久修正保留；非跳跳家族不发动攻击）。"""
    _coffin_def(db)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    s = pa.shikigami[1]  # 100102（1/6）
    s.perm_power = 2  # 永久修正跨气绝/棺材保留
    s.ext["coffin_on_defeat"] = 10010199
    _kill(g, 0, 1)
    assert pa.shikigami[1].id == 10010199
    hp_b = pb.health
    F.pass_turns(g, 1)  # 敌方回合：棺材不倒计时
    assert pa.shikigami[1].id == 10010199
    F.pass_turns(g, 1)  # 己方回合开始：1→0 归零复活
    r = pa.shikigami[1]
    assert r.id == 100102 and not r.defeated and r.health == r.max_health == 6
    assert r.perm_power == 2 and r.level == 1  # 正常复活口径
    assert pb.health == hp_b  # 非跳跳家族：不发动攻击


def test_coffin_family_assault_unyielding(db, make_game):
    """棺材归零复活跳跳家族（coffin_assault 名单）：立刻发动攻击且本次战斗获得
    [不屈]——受致死反击留 1 血存活。"""
    _coffin_def(db, assault_ids=[100101])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pa.shikigami[0].ext["coffin_on_defeat"] = 10010199
    _kill(g, 0, 0)
    es = pb.shikigami[0]  # 敌方战斗区放一个高力量式神（反击致死）
    es.temp_power += 10
    F.pass_turns(g, 1)  # 进敌方回合（棺材不倒计时）
    F.move(g, 1, 0)  # 敌方回合内入战斗区（其回合开始移回后才放置，避免被移回）
    hp_e = es.health
    F.pass_turns(g, 1)  # 回己方回合开始：归零复活 + 立刻攻击
    r = pa.shikigami[0]
    assert r.id == 100101 and not r.defeated
    assert es.health == hp_e - 3  # 攻击造成 3（基础力量）
    assert r.health == 1  # 反击 13 致死 → [不屈] 留 1
    assert pa.combat_index == 0  # 攻击者进战斗区


def test_coffin_destroyed_keeps_original_defeated(db, make_game):
    """棺材被击杀（定案(8)）：原式神保持气绝、按正常气绝倒计时复活（棺材移除
    不复活），**会有气绝事件、计入击杀账本**（入棺时按原式神已结算过一次，
    击破棺材再结算一次）。"""
    _coffin_def(db)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    pa.shikigami[1].ext["coffin_on_defeat"] = 10010199
    kills0 = pb.kill_total
    _kill(g, 0, 1)
    assert pb.kill_total == kills0  # 无来源气绝不记击杀（对照）
    seen: list[dict] = []
    orig_emit = g.emit

    def spy(name, **kw):
        if name == "on_shikigami_defeated":
            seen.append(kw)
        return orig_emit(name, **kw)

    g.emit = spy
    c = pa.shikigami[1]
    c.health = 0
    g.check_defeated(Ref(player=0, shikigami=1), source=Ref(player=1, shikigami=0))
    r = pa.shikigami[1]
    assert r.id == 100102 and r.defeated  # 原式神保持气绝
    assert r.revive_countdown == g.config.revive_countdown  # 倒计时重置为正常值
    assert pb.kill_total == kills0 + 1  # 击破棺材计入击杀账本
    assert pb.kill_by.get(100101) == 1  # 按来源实体数据 id 分桶
    assert seen and seen[0]["victim"] == Ref(player=0, shikigami=1)  # 气绝事件照发
    g._drain_queue()


def test_coffin_mass_replace(db, make_game):
    """死而复生"将所有己方气绝的式神替换为'棺材'"（to_coffin 目标池
    friendly_defeated）：全体气绝者同时入棺。"""
    _coffin_def(db)
    db.cards[10010151] = F.card(  # 死而复生位（气绝时可用标记为数据侧，dummy 省略）
        10010151, token=True,
        steps=[F.Step(op="to_coffin", into=10010199,
                      target=T(kind="all", pool="friendly_defeated"))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    _kill(g, 0, 1)
    _kill(g, 0, 2)
    F.play(g, 0, 10010151)
    assert pa.shikigami[1].id == 10010199 and pa.shikigami[2].id == 10010199
    assert pa.shikigami[0].id == 100101  # 存活者不受影响


def test_coffin_keep_combat(db, make_game):
    """棺封"消灭一个式神。若该式神不是召唤物，将其替换为'棺材'"（destroy +
    to_coffin keep_combat）：对战斗区敌方式神，棺材进其战斗区。"""
    _coffin_def(db)
    db.cards[10010151] = F.card(  # 棺封位
        10010151, token=True, target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="destroy"),
               F.Step(op="to_coffin", into=10010199, keep_combat=True)])
    g = make_game()
    pa, pb = F.battle_setup(g)
    F.move(g, 1, 0)  # 敌方式神入战斗区
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    c = pb.shikigami[0]
    assert c.id == 10010199 and not c.defeated
    assert pb.combat_index == 0  # 棺材进其战斗区（属原牌手）


# ---------- 薰行动账本（player ext last_acted / context 目标键 last_acted） ----------

def _guardian_inv(db):
    db.invocations["鸮之守护"] = InvocationDef(name="鸮之守护", unique="unique")


def _xun_ability(db, sid: int = 100102):
    """合成薰基础能力：己方回合结束时，使本回合最后一个行动的式神结附守护。"""
    db.shikigami[sid] = F.shiki(
        sid, power=2, health=4, faction="紫岩",
        ability=F.block(
            F.Step(op="attach_invocation", name="鸮之守护",
                   target=T(kind="context", key="last_acted")),
            when="on_turn_end", condition={"active": "self"}))


def test_last_acted_ledger(db, make_game):
    """薰"己方回合结束时，使你本回合最后一个行动的式神结附'鸮之守护'"：
    主动出击/使用专属牌更新账本，最后一个行动者结附；账本空则无事。"""
    _guardian_inv(db)
    _xun_ability(db)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    F.play(g, 0, 10010101)  # 座次0 用牌
    F.play(g, 0, 10010301)  # 座次2 再用牌（最后行动者）
    F.pass_turns(g, 1)  # 己方回合结束
    assert [e["name"] for e in pa.shikigami[2].invocations] == ["鸮之守护"]
    assert pa.shikigami[0].invocations == []
    F.pass_turns(g, 1)  # 敌方回合（无行动）结束：无事
    F.play(g, 0, 10010101)  # 座次0 再用1级牌（账本回到座次0）
    g.apply({"op": "assault", "index": 2})  # 出击覆盖账本（最后行动者 = 座次2）
    F.pass_turns(g, 1)
    assert [e["name"] for e in pa.shikigami[2].invocations] == ["鸮之守护"]
    assert pa.shikigami[0].invocations == []
    # 账本空：什么都不做
    g2 = make_game()
    _guardian_inv(db)  # 同一 db：薰能力已挂
    pa2, pb2 = F.battle_setup(g2, levels={0: 1, 1: 1})
    F.pass_turns(g2, 1)  # 无行动直接结束
    assert all(not s.invocations for s in pa2.shikigami)


def test_last_acted_clear_and_revive_gate(db, make_game):
    """账本边界：己方回合开始清除（上回合行动不带入）；最后行动者已气绝/离场时
    不结附（context 目标 in_play 门控）。"""
    _guardian_inv(db)
    _xun_ability(db)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    F.play(g, 0, 10010101)
    F.pass_turns(g, 2)  # 经敌方回合回到己方：账本已清（期间座次0结附过守护）
    assert pa.ext.get("last_acted") is None
    pa.shikigami[0].invocations.clear()  # 清掉上一周期结附，便于断言本周期无新结附
    F.play(g, 0, 10010301)  # 座次2 行动后气绝
    _kill(g, 0, 2)
    F.pass_turns(g, 1)  # 己方回合结束：最后行动者不在场 → 不结附
    assert all(not s.invocations for s in pa.shikigami)


def test_act_trigger_before_action(db, make_game):
    """觉醒·薰"当你的式神行动时，结附'鸮之守护'"（定案(11)）：触发时机 =
    出击事件流程"出击前"（on_before_assault，优先级 1——结附先于战斗伤害，
    守护减伤赶上本次交战反击）与主动使用牌流程"行动前"（on_before_card_played
    ——结附先于使用事件效果，本牌自伤即被减）。"""
    db.invocations["鸮之守护"] = InvocationDef(
        name="鸮之守护", unique="unique",
        abilities=[F.block(F.Step(op="reduce_damage", amount=1,
                                  condition={"victim_shikigami": "self"}),
                           when="on_damage_start")])
    db.shikigami[100102] = F.shiki(
        100102, power=1, health=6, faction="紫岩",
        abilities=[F.block(
            F.Step(op="attach_invocation", name="鸮之守护",
                   target=T(kind="context", key="attacker")),
            when="on_before_assault", priority=1,
            condition={"attacker_side": "friendly"}), F.block(
            F.Step(op="attach_invocation", name="鸮之守护",
                   target=T(kind="context", key="actor")),
            when="on_before_card_played",
            condition={"player": "self", "shikigami_not": None})])
    db.cards[10010151] = F.card(  # 自伤牌：对来源自身 2 伤（验"行动前"结附先于效果）
        10010151, token=True,
        steps=[F.Step(op="damage", amount=2, target=T(kind="self"))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1, 2: 1})
    # 用牌侧：行动前结附 → 本牌对自身 2 伤被守护减为 1
    s0 = pa.shikigami[0]  # 100101 3/4
    F.play(g, 0, 10010151)
    assert [e["name"] for e in s0.invocations] == ["鸮之守护"]
    assert s0.health == 3  # 4 - (2-1)——结附先于本牌效果
    # 出击侧：出击前结附 → 敌方 3 力量反击被守护减为 2
    F.move(g, 1, 0)  # 敌方 100101（3/4）入战斗区
    s2 = pa.shikigami[2]  # 100103 2/6
    g.apply({"op": "assault", "index": 2})
    assert [e["name"] for e in s2.invocations] == ["鸮之守护"]
    assert s2.health == 4  # 6 - (3-1)——结附先于战斗伤害


# ---------- 干扰投掷禁伤（ext no_damage_vs_inv）与灵咒过滤/条件键 ----------

def test_no_damage_vs_invocation(db, make_game):
    """干扰投掷"使其本回合不能对结附'鸮之守护'的式神造成伤害"：debuff 持有者
    对结附者的一切伤害（战斗/效果）无效，对未结附者照常；半回合边界清除。"""
    from core.model import ExecContext
    _guardian_inv(db)
    db.cards[10010151] = F.card(  # 干扰投掷位：对敌方式神施 debuff
        10010151, token=True, target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="bump_ext", key="no_damage_vs_inv", value="鸮之守护")])
    db.cards[10010251] = F.card(  # 敌方伤害牌（干扰其效果伤害）
        10010251, shikigami=100102, token=True,
        target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="damage", amount=2)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    g.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=0))
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))  # debuff 敌方座次0
    # 效果伤害：对结附者无效、对未结附者照常
    g._resolve_block(db.cards[10010251].effects, ExecContext(
        controller=1, source=Ref(player=1, shikigami=0),
        chosen=[Ref(player=0, shikigami=0)]))
    assert pa.shikigami[0].health == 4  # 无效
    g._resolve_block(db.cards[10010251].effects, ExecContext(
        controller=1, source=Ref(player=1, shikigami=0),
        chosen=[Ref(player=0, shikigami=1)]))
    assert pa.shikigami[1].health == 4  # 6 - 2 照常
    # 战斗伤害：敌方 debuff 持有者出击打在结附者身上无效（反击照常）
    F.move(g, 0, 0)  # 结附者入战斗区
    F.pass_turns(g, 1)  # 进敌方回合（debuff 在任一回合开始清除？——见下行断言）
    es = pb.shikigami[0]
    assert es.ext.get("no_damage_vs_inv") is None  # 半回合边界已清除
    g.apply({"op": "assault", "index": 0})
    assert pa.shikigami[0].health == 1  # 清除后正常受战斗伤害 3
    assert es.health == 1  # 反击 3 照常
    # 同回合内（响应场景：敌方回合中施加，持续到他回合结束）
    g2 = make_game()
    pa2, pb2 = F.battle_setup(g2, levels={0: 1, 1: 1})
    g2.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=0))
    F.move(g2, 0, 0)
    F.pass_turns(g2, 1)  # 进敌方回合
    pb2.shikigami[0].ext["no_damage_vs_inv"] = "鸮之守护"  # 模拟响应期施加
    g2.apply({"op": "assault", "index": 0})
    assert pa2.shikigami[0].health == 4  # 战斗伤害无效
    assert pb2.shikigami[0].health == 1  # 反击照常（结附者无 debuff）


def test_has_invocation_filter(db, make_game):
    """目标过滤键 has_invocation：结附指定灵咒的式神入池；same_source 同源限定
    （决意"你结附'鸮之守护'的式神"——结附来源所属牌手须为控制者）。"""
    db.invocations["鸮之守护"] = InvocationDef(name="鸮之守护")  # 非唯一，便于多源共存
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    g.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("鸮之守护", player=1, target=Ref(player=1, shikigami=0))
    g.attach_invocation("鸮之守护", player=1,  # 敌方来源结附到我方式神（无尽剑狱类）
                        target=Ref(player=0, shikigami=1))
    spec = T(kind="choose", pool="any_shikigami", has_invocation="鸮之守护")
    refs = targets_mod.spec_pool_refs(g, spec, 0, targeted=True)
    got = sorted((r.player, r.shikigami) for r in refs)
    assert got == [(0, 0), (0, 1), (1, 0)]
    same = T(kind="choose", pool="friendly_shikigami",
             has_invocation={"name": "鸮之守护", "same_source": True})
    refs = targets_mod.spec_pool_refs(g, same, 0, targeted=True)
    assert refs == [Ref(player=0, shikigami=0)]  # 仅同源（我方结附的）


def test_invocation_on_field_condition(db, make_game):
    """条件键 invocation_on_field（麓鸣·穿/麓鸣·袭[增强]"若场上已有己方的
    '八尺琼曲玉'"）：己方式神在场结附该灵咒才通过（不限结附来源）。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", unique="unique",
                                                 power=1)
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="draw", count=1,
                      condition={"invocation_on_field": "八尺琼曲玉"})])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1})
    hand0 = len(pa.hand)
    F.play(g, 0, 10010151)  # 场上无：步骤跳过
    assert len(pa.hand) == hand0
    g.attach_invocation("八尺琼曲玉", player=0, target=Ref(player=0, shikigami=0))
    F.play(g, 0, 10010151)  # 已有：步骤执行
    assert len(pa.hand) == hand0 + 1


# ---------- 条件光环（stat_aura kind=friendly_invocation，薰形态系列） ----------

def test_friendly_invocation_aura(db, make_game):
    """鸮之利爪/鸮之警惕型条件光环：己方在场且结附'鸮之守护'（不限结附来源）的
    式神 +2 力量并获得[帷幕]；灵咒移除或形态离场后自动撤销（身材读取时求值，
    关键字由 reconcile 差额授予/撤销）。"""
    _guardian_inv(db)
    db.cards[10010151] = F.card(  # 薰形态位：结附'鸮之守护'的己方式神 +2 力量、[帷幕]
        10010151, card_type="form", form_power=1, form_health=5, token=True,
        steps=[F.Step(op="stat_aura", kind="friendly_invocation",
                      name="鸮之守护", power=2, keywords=["veil"])])
    db.cards[10010153] = F.card(  # 顶掉形态用
        10010153, card_type="form", form_power=2, form_health=4, token=True)
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    s0, s1 = pa.shikigami[0], pa.shikigami[1]  # 3/4 与 1/6
    F.play(g, 0, 10010151)  # 形态结附 s0
    assert s0.eff_power == 1 and "veil" not in s0.keywords  # 未结附灵咒：光环不生效
    g.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=1))
    assert s1.eff_power == 3 and "veil" in s1.keywords  # 1+2
    assert s0.eff_power == 1 and "veil" not in s0.keywords  # 持有者自身未结附不生效
    g.attach_invocation("鸮之守护", player=1,  # 来源敌方也算（不限结附来源）
                        target=Ref(player=0, shikigami=0))
    assert s0.eff_power == 3 and "veil" in s0.keywords
    # 灵咒移除：光环与关键字撤销（reconcile 挂在读取刷新点；直移除后手动刷新模拟）
    g._remove_invocation(s1, s1.invocations[0], reason="测试")
    g._refresh_stat_auras()
    assert s1.eff_power == 1 and "veil" not in s1.keywords
    # 形态离场：scope=form 光环移除，s0 上的加攻与[帷幕]同步撤销（出牌发事件刷新）
    F.play(g, 0, 10010153)
    assert s0.eff_power == 2 and "veil" not in s0.keywords


# ---------- inv_mod 能力登记/离场（大岳丸"八尺琼曲玉结附于大岳丸时效果+1"） ----------

def test_inv_mod_ability_scope(db, make_game):
    """on_ability_enter 登记 scope="ability" 灵咒修饰（大岳丸基础/觉醒型）：
    能力进场注册、按持有者式神 id 过滤修饰、气绝随能力离场清除、复活重新进场
    恢复。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", power=1)
    db.shikigami[100101] = F.shiki(100101, abilities=[F.block(
        F.Step(op="inv_mod", name="八尺琼曲玉", shikigami=100102, add=1),
        when="on_ability_enter", condition={"target_shikigami": "self"})])
    g = make_game()  # 开局最左升 1 级：100101 能力进场即登记（双方座次0同 id，互不影响）
    pa, pb = F.battle_setup(g, levels={1: 1})
    s0, s1 = pa.shikigami[0], pa.shikigami[1]  # 100101 3/4 与 100102 1/6
    g.attach_invocation("八尺琼曲玉", player=0, target=Ref(player=0, shikigami=0))
    assert s0.eff_power == 4  # 持有者过滤（100102）不命中：3+1 不修饰
    g.attach_invocation("八尺琼曲玉", player=0, target=Ref(player=0, shikigami=1))
    assert s1.eff_power == 3  # 1+(1+1)
    _kill(g, 0, 0, countdown=1)  # 能力持有者气绝：scope="ability" 条目清除并重算
    assert s1.eff_power == 2
    F.pass_turns(g, 2)  # 回到己方回合开始：复活 → 能力重新进场登记
    assert not s0.defeated and s1.eff_power == 3


# ---------- 结附灵咒击杀加成（inv_bonus_on_kill，觉醒·大岳丸） ----------

def test_inv_bonus_on_kill(db, make_game):
    """觉醒·大岳丸"当结附'八尺琼曲玉'的己方式神击杀敌方式神时，'八尺琼曲玉'
    效果+1"：使用时赋予牌手规则表（不随气绝失效）；击杀后击杀者身上该灵咒
    bonus += add 并重算修饰层；未结附灵咒的击杀不加。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", unique="unique",
                                                 power=1)
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="inv_bonus_on_kill", inv="八尺琼曲玉", add=1)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    F.play(g, 0, 10010151)
    s0 = pa.shikigami[0]
    g.attach_invocation("八尺琼曲玉", player=0, target=Ref(player=0, shikigami=0))
    assert s0.eff_power == 4  # 3+1
    t = pb.shikigami[0]  # 敌方座次0 3/4
    t.health = 0
    g.check_defeated(Ref(player=1, shikigami=0), source=Ref(player=0, shikigami=1))
    assert s0.invocations[0]["bonus"] == 0  # 击杀者未结附该灵咒：不加
    t2 = pb.shikigami[1]  # 敌方座次1 1/6
    t2.health = 0
    g.check_defeated(Ref(player=1, shikigami=1), source=Ref(player=0, shikigami=0))
    assert s0.invocations[0]["bonus"] == 1  # 结附者击杀：+1
    assert s0.eff_power == 5  # 3+(1+bonus1)


# ---------- 结附追加关键字（attach_invocation grant_keywords，无尽剑狱持续眩晕） ----------

def test_attach_invocation_grant_keywords(db, make_game):
    """无尽剑狱"并于结附期间使其持续[眩晕]"：attach_invocation 的 grant_keywords
    参数经 op 透传——stun 走灵咒眩晕条目通道（不随回合批次过期、灵咒移除即解），
    灵咒本体不带关键字。"""
    db.invocations["剑狱"] = InvocationDef(name="剑狱")
    db.cards[10010151] = F.card(
        10010151, token=True, target=T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="attach_invocation", name="剑狱",
                      grant_keywords=["stun"])])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1})
    es = pb.shikigami[0]
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))
    assert es.is_stunned
    F.pass_turns(g, 2)  # 跨双方回合开始：不过期
    assert es.is_stunned
    g._remove_invocation(es, es.invocations[0], reason="测试")
    assert not es.is_stunned  # 灵咒移除即解


# ---------- 持有者灵咒门控（holder_has_invocation，棺击降级口径） ----------

def test_holder_has_invocation_condition(db, make_game):
    """棺击"持有'迟钝'期间"降级门控：delay_grant（uses=99）延迟能力仅在持有者
    结附'迟钝'期间触发；未结附不触发、移除后不再触发。"""
    _dull_inv(db)
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="delay_grant", when="on_turn_start",
                      condition={"player": "self", "holder_has_invocation": "迟钝"},
                      uses=99,
                      steps=[{"op": "damage", "amount": 1,
                              "target": {"kind": "all", "pool": "enemy_player"}}])])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1})
    pb.shield = 0
    hp0 = pb.health
    F.play(g, 0, 10010151)  # 跳跳哥哥位登记延迟能力
    F.pass_turns(g, 2)  # 己方回合开始一次：无'迟钝'不触发
    assert pb.health == hp0
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))
    F.pass_turns(g, 2)  # 触发 1 次
    assert pb.health == hp0 - 1
    F.pass_turns(g, 2)  # uses=99：再次触发
    assert pb.health == hp0 - 2
    s0 = pa.shikigami[0]
    g._remove_invocation(s0, s0.invocations[0], reason="测试")
    F.pass_turns(g, 2)  # '迟钝'移除后不再触发
    assert pb.health == hp0 - 2


# ---------- 响应条件（victim_has_invocation，干扰投掷端到端） ----------

def test_response_victim_has_invocation(db, make_game):
    """干扰投掷响应端到端：on_before_assault + victim_has_invocation——敌方攻击
    结附'鸮之守护'的式神时自动响应，对攻击者施禁伤 debuff（本次攻击伤害无效、
    反击照常）；攻击未结附者不触发。"""
    _guardian_inv(db)
    db.cards[10010151] = F.card(
        10010151, cost=1, keywords=["trigger"], token=True,
        when="on_before_assault",
        block_kw={"condition": {"attacker_side": "enemy",
                                "victim_has_invocation": "鸮之守护"}},
        steps=[F.Step(op="bump_ext", key="no_damage_vs_inv", value="鸮之守护",
                      target=T(kind="context", key="attacker"))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1})
    g.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=0))
    F.move(g, 0, 0)  # 结附者入战斗区
    F.give(g, 0, 10010151)
    F.pass_turns(g, 1)  # 进敌方回合
    g.apply({"op": "assault", "index": 0})  # B0 3/4 出击结附者
    assert pa.shikigami[0].health == 4  # 响应生效：禁伤
    assert pb.shikigami[0].health == 1  # 反击 3 照常
    assert any(c.id == 10010151 for c in pa.graveyard)  # 响应牌已使用
    # 负例：被攻击者未结附'鸮之守护'——不触发
    g2 = make_game()
    pa2, pb2 = F.battle_setup(g2, levels={0: 1})
    F.move(g2, 0, 0)
    F.give(g2, 0, 10010151)
    F.pass_turns(g2, 1)
    g2.apply({"op": "assault", "index": 0})
    assert pa2.shikigami[0].health == 1  # 正常受 3 伤
    assert any(c.id == 10010151 for c in pa2.hand)  # 未响应：牌仍在手


# ---------- 条件瞬发算子（conditional_keywords invocation_on_field，麓鸣·穿） ----------

def test_conditional_keyword_invocation_on_field(db, make_game):
    """麓鸣·穿"[增强]：若场上已有己方的'八尺琼曲玉'，此牌获得[瞬发]"：
    conditional_keywords 通道在付费时点生效——场上无结附者照付鬼火，有则免鬼火
    占瞬发名额；不限结附来源；灵咒移除后即恢复付费。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", power=1)
    db.cards[10010151] = F.card(
        10010151, token=True,
        conditional_keywords=[{"invocation_on_field": "八尺琼曲玉",
                               "keyword": "fast"}])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    F.play(g, 0, 10010151)  # 场上无'八尺琼曲玉'：无瞬发，照付 1 火
    assert pa.orb == 8 and not pa.fast_used
    g.attach_invocation("八尺琼曲玉", player=1,  # 来源敌方也算（不限结附来源）
                        target=Ref(player=0, shikigami=1))
    F.play(g, 0, 10010151)  # 有结附者：瞬发免费、占名额
    assert pa.orb == 8 and pa.fast_used
    s1 = pa.shikigami[1]
    g._remove_invocation(s1, s1.invocations[0], reason="测试")
    pa.fast_used = False  # 清名额变量，隔离验证条件失效
    F.play(g, 0, 10010151)  # 结附移除：恢复付费
    assert pa.orb == 7 and not pa.fast_used


# ---------- 双选择目标（CardDef.target2 + chosen_index，麓鸣·灭） ----------

def test_dual_choose_target(db, make_game):
    """麓鸣·灭"使结附'八尺琼曲玉'的己方式神获得2护甲并攻击一个敌方式神"：
    双 choose——主目标（has_invocation 过滤的己方式神）得护甲并发起额外攻击，
    第二目标（敌方式神）为战斗目标（launch_attack at=chosen + at_index=1）。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", power=1)
    db.cards[10010151] = F.card(  # 麓鸣·灭同构合成卡
        10010151, token=True,
        target=T(kind="choose", pool="friendly_shikigami",
                 has_invocation="八尺琼曲玉"),
        target2=T(kind="choose", pool="enemy_shikigami"),
        steps=[
            F.Step(op="gain_shield", amount=2,
                   target=T(kind="choose", chosen_index=0)),
            F.Step(op="launch_attack", shikigami="target", at="chosen", at_index=1,
                   target=T(kind="choose", chosen_index=0)),
        ])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    g.attach_invocation("八尺琼曲玉", player=0, target=Ref(player=0, shikigami=1))
    s1, e0 = pa.shikigami[1], pb.shikigami[0]  # 1/6+1攻 与 3/4
    c = F.give(g, 0, 10010151)
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": c.uid,
                 "target": Ref(player=0, shikigami=1)})  # 缺第二目标
    g.apply({"op": "play_card", "uid": c.uid,
             "target": Ref(player=0, shikigami=1),
             "target2": Ref(player=1, shikigami=0)})
    assert s1.shield == 0 and s1.health == 5  # 2 护甲被反击 3 打穿（余 1 伤）
    assert e0.health == 2  # 被定向攻击：4 - (1+1)
    assert pb.health == 30  # 定向战斗不打牌手


# ---------- 战斗牌效果步携带选择目标（_resolve_combat_card ctx.chosen，麓鸣·轰） ----------

def test_combat_card_effect_chosen(db, make_game):
    """麓鸣·轰"选择一个己方式神，本次攻击后将'八尺琼曲玉'结附于该式神并使其发起
    攻击"：战斗牌效果步的 ctx 携带 chosen——delay_grant bind=chosen 登记到所选
    式神，本次攻击后（on_after_assault）对其结附灵咒并令其发起一次无指定目标
    的额外攻击。"""
    db.invocations["八尺琼曲玉"] = InvocationDef(name="八尺琼曲玉", unique="unique",
                                                 power=1)
    db.cards[10010151] = F.card(  # 麓鸣·轰同构合成卡（所属 100101）
        10010151, card_type="combat", token=True,
        target=T(kind="choose", pool="friendly_shikigami"),
        steps=[
            F.Step(op="delay_grant", when="on_after_assault",
                   condition={"attacker_shikigami": 100101}, bind="chosen",
                   steps=[{"op": "attach_invocation", "name": "八尺琼曲玉"},
                          {"op": "launch_attack", "shikigami": "target"}]),
        ])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    s1 = pa.shikigami[1]  # 1/6
    F.play(g, 0, 10010151, target=Ref(player=0, shikigami=1))
    # 攻击后时机在本次出牌内串联结算完毕：本体攻击 3 + 所选式神额外攻击 1+1=2
    assert pb.health == 25
    assert [e["name"] for e in s1.invocations] == ["八尺琼曲玉"]  # 攻击后结附
    assert pa.combat_index == 1  # 额外攻击者进入战斗区


# ---------- 来源个体排除（exclude_self，樱吹雪"其他所有式神"定案(0)） ----------

def test_exclude_self_source_entity(db, make_game):
    """目标键 exclude_self："其他所有式神"= 除效果来源个体外的双方式神——镜像
    对局敌方同名式神照常入池（按来源实体排除，非数据 id）。"""
    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="damage", amount=1,
                      target=T(kind="all", pool="any_shikigami",
                               exclude_self=True))])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    F.play(g, 0, 10010151)  # 来源 = 己方座次0（100101）
    assert pa.shikigami[0].health == 4  # 来源个体被排除
    assert pb.shikigami[0].health == 3  # 敌方同名（100101）照常受伤
    assert pa.shikigami[1].health == 5  # 其余在场双方各 -1
    assert pb.shikigami[1].health == 5


# ---------- 迟钝归零结算次序与灵咒倒计时批次（定案(1)(6)(9)） ----------

def test_invocation_proc_removes_before_attack(db, make_game):
    """迟钝归零：先移除灵咒（含解除眩晕）再发起攻击；多条同名迟钝并存时移除
    全部同名条目（倒计时槽唯一、由后者覆盖——现状保持）。"""
    db.invocations["迟钝"] = InvocationDef(
        name="迟钝", keywords=["stun"],
        abilities=[F.block(F.Step(op="launch_attack"), countdown=2, once=True)])
    g = make_game()
    pa, pb = F.battle_setup(g)
    s = pa.shikigami[0]
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))  # 同名并存
    assert len(s.invocations) == 2 and s.is_stunned and s.countdown == 2
    calls: list[str] = []
    orig_rm = g._remove_invocation
    orig_cb = g._resolve_combat

    def spy_rm(*a, **kw):
        calls.append("remove")
        return orig_rm(*a, **kw)

    def spy_cb(*a, **kw):
        calls.append("combat")
        return orig_cb(*a, **kw)

    g._remove_invocation = spy_rm
    g._resolve_combat = spy_cb
    F.pass_turns(g, 2)  # 回到己方回合开始：2→1
    F.pass_turns(g, 2)  # 归零生效
    assert calls[:2] == ["remove", "remove"]  # 两条同名均移除
    assert "combat" in calls and calls.index("combat") > 1  # 移除早于攻击
    assert s.invocations == [] and not s.is_stunned  # 眩晕随灵咒解除
    assert s.countdown is None
    assert pb.health == 27  # 攻击照常发起（3 力量打空战斗区牌手）


def test_invocation_countdown_lane_after_normal(db, make_game):
    """灵咒倒计时归入"式神灵咒倒计时"批次、晚于非灵咒倒计时扣减：非灵咒车道
    归零效果先击杀灵咒持有者，则同回合灵咒车道不再处理（持有者已气绝）——
    灵咒持有者进场顺序更靠前也不提前（单车道旧口径下会先归零发起攻击）。"""
    db.invocations["迟钝"] = InvocationDef(
        name="迟钝", keywords=["stun"],
        abilities=[F.block(F.Step(op="launch_attack"), countdown=2, once=True)])
    db.shikigami[100102] = F.shiki(  # 座次1：非灵咒倒计时1 一次型，归零点杀迟钝持有者
        100102, abilities=[F.block(
            F.Step(op="damage", amount=30,
                   target=T(kind="all", pool="friendly_shikigami",
                            has_invocation="迟钝")),
            countdown=1, once=True)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    g._register_ability_countdown(0, 1)  # battle_setup 直设等级不走能力进场，补注册
    assert pa.shikigami[1].countdown == 1
    s0 = pa.shikigami[0]
    g.attach_invocation("迟钝", player=0, target=Ref(player=0, shikigami=0))
    s0.countdown = 1  # 测试注入：本回合开始即归零
    F.pass_turns(g, 2)  # 回到己方回合开始：非灵咒车道先结算
    assert s0.defeated and s0.invocations == []  # 先被点杀（灵咒随气绝移除）
    assert pb.health == 30  # 灵咒车道不再处理：迟钝未发起攻击


# ---------- 非召唤物目标过滤（not_summon，不弃定案(12)） ----------

def test_not_summon_target_filter(db, make_game):
    """目标过滤键 not_summon（不弃"使一个非召唤物式神"）：选择目标合法性即排除
    召唤物；any_shikigami 池默认不含气绝者，敌我未气绝的非召唤物式神均可选。"""
    db.shikigami[10010199] = F.shiki(10010199, kind="summon", power=0, health=3)
    db.cards[10010152] = F.card(  # 召唤墙（生成即进战斗区，落座次4）
        10010152, token=True, steps=[F.Step(op="summon", shikigami=10010199)])
    db.cards[10010151] = F.card(  # 不弃位：旗标授予（消费端语义已由棺材节覆盖）
        10010151, token=True,
        target=T(kind="choose", pool="any_shikigami", not_summon=True),
        steps=[F.Step(op="bump_ext", key="coffin_on_defeat", value=10010199)])
    g = make_game()
    pa, pb = F.battle_setup(g, levels={0: 1, 1: 1})
    F.play(g, 0, 10010152)
    assert pa.shikigami[4].kind == "summon"
    with pytest.raises(IllegalAction):  # 召唤物不是合法目标
        F.play(g, 0, 10010151, target=Ref(player=0, shikigami=4))
    F.play(g, 0, 10010151, target=Ref(player=1, shikigami=0))  # 敌方式神可选
    assert pb.shikigami[0].ext.get("coffin_on_defeat") == 10010199
    F.play(g, 0, 10010151, target=Ref(player=0, shikigami=1))  # 己方式神可选
    assert pa.shikigami[1].ext.get("coffin_on_defeat") == 10010199


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
    assert pb.shikigami[0].health == 4  # 镜像同名樱花妖照常受波及（定案(0)：仅排除
    # 效果来源个体）——伤害两波 5→1，治疗单波 1→4


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


# ---------- 灵咒真实数据（迟钝 100402 / 鸮之守护 100405 / 八尺琼曲玉 100408） ----------

def test_real_invocations_loaded(gdb):
    """三张灵咒定义入库：字段与 text（逐字 = card_data_raw.md）校验；环境解析
    at_date 在发布日期前不可用、当日可用。"""
    d = gdb.invocations["迟钝"]
    assert d.keywords == ["stun"]
    assert d.abilities[0].countdown == 2 and d.abilities[0].once
    assert d.text == "[倒计时2]：{发起一次攻击}。生效后移除。[眩晕]。"
    x = gdb.invocations["鸮之守护"]
    assert x.unique == "unique" and x.abilities[0].when == "on_damage_start"
    assert x.text == "[唯一]。受到伤害时减少1点。"
    y = gdb.invocations["八尺琼曲玉"]
    assert y.unique == "unique" and y.power == 1
    assert y.text == "[唯一]。结附的式神获得1力量。"
    old = gdb.at_date(20200624)  # 03 月夜幻响环境：04 包灵咒尚未发布
    assert "迟钝" not in old.invocations and "鸮之守护" not in old.invocations
    assert "迟钝" in gdb.at_date(20200928).invocations


def test_real_invocation_damage_reduce(real_game):
    """鸮之守护"受到伤害时减少1点"：结附式神受伤 -1（on_damage_start 批次
    reduce_damage，条件 victim_shikigami=self），其他式神不受影响。"""
    g, pa, pb = _rg(real_game, [100405, 100101, 100102, 100125], levels={0: 1, 1: 1})
    s0, s1 = pa.shikigami[0], pa.shikigami[1]
    g.attach_invocation("鸮之守护", player=0, target=Ref(player=0, shikigami=0))
    hp0, hp1 = s0.health, s1.health
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 3, None)
    g.deal_to_shikigami(Ref(player=0, shikigami=1), 3, None)
    assert s0.health == hp0 - 2  # 减少 1 点
    assert s1.health == hp1 - 3  # 未结附者全额


def test_real_coffin_entity_loaded(gdb):
    """棺材占位实体（10040299）入库：kind=transform 不能攻击 0/3、coffin_assault
    跳跳家族名单、倒计时1 一次型能力块（归零=coffin_revive），text 逐字。"""
    d = gdb.shikigami[10040299]
    assert d.kind == "transform" and d.no_attack
    assert (d.power, d.health) == (0, 3)
    assert d.coffin_assault == [100402, 100131, 100120]
    ab = d.abilities[0]
    assert ab.countdown == 1 and ab.once
    assert ab.steps[0].op == "coffin_revive" and ab.steps[0].target.kind == "self"
    assert d.text == ("不能攻击。[倒计时1]：{移除此牌，复活原式神。"
                      "若该式神是跳跳哥哥、跳跳妹妹或跳跳弟弟，使其立刻发动攻击，"
                      "本次战斗获得[不屈]。}")
    assert 10040299 not in gdb.at_date(20200624).shikigami  # 发布前环境不可用
