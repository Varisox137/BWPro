"""萤草（100127）基础数据与灵矢贯虹完善（维护者答复(3)）测试：真实 db YAML 端到端。

覆盖：萤草基础能力（使用与当前形态不同的形态牌时抽 1——当前无萤草形态牌，
测试库临时注册两张验证机制对任意形态牌生效）；灵矢贯虹"获得当前自身法术牌强化
效果的力量加成"（起弓/离 attack_buff 挂账的力量部分镜像，仅力量）；羁绊 1
"攻击前触发萤草当前形态进场效果"（含未结附形态空操作）。
队伍固定 [萤草, 白狼, 兵俑, 妖刀姬]。
"""
import pytest

from db.loader import CardDatabase
from db.schema import CardDef, EffectBlock, Step, TargetSpec
from tests import factories as F
from tests.factories import give, move, pass_turns, play

YC = 100127       # 萤草（双方 0 号位）
IDX = 0
LSGH = 10010151   # 灵矢贯虹
QIGONG = 10010101  # 起弓（+1 力量 & 穿刺）
LI = 10010104      # 离（+3 力量）

FORM_A, FORM_B = 10012701, 10012702  # 测试库注册的萤草形态牌

TEAM = [100127, 100101, 100102, 100123]


def _form(cid: int, name: str, steps=()) -> CardDef:
    return CardDef(id=cid, version=20260728, name=name, shikigami=YC,
                   card_type="form", rarity="R", level=1, cost=1,
                   form_power=2, form_health=3,
                   effects=EffectBlock(steps=list(steps)), text="")


@pytest.fixture
def gdb():
    """真实 db + 测试库临时注册：萤草形态牌 A（空白进场）/B（进场 +2 护甲）
    与凑卡组的空白法术 03/04（萤草 8 卡未加入，mk_game 卡组构造需要 01-04）。"""
    db = CardDatabase.load()
    db.cards[FORM_A] = _form(FORM_A, "测试形态·花")
    db.cards[FORM_B] = _form(FORM_B, "测试形态·叶", steps=[
        Step(op="gain_shield", amount=2, target=TargetSpec(kind="self"))])
    for n in (3, 4):
        cid = YC * 100 + n
        db.cards[cid] = CardDef(id=cid, version=20260728, name=f"萤草空白卡{n}",
                                shikigami=YC, card_type="spell", level=1, cost=1,
                                effects=EffectBlock(), text="")
    return db


@pytest.fixture
def make_game(real_game):                    # real_game 经 fixture 覆盖拿到本文件的 gdb
    def _make(seed: int = 1, **kw):
        return real_game(TEAM, seed=seed, **kw)

    return _make


def _game(make_game, wolf_level: int = 1):
    g = make_game()
    pa, pb = F.battle_setup(g, {IDX: 1, 1: wolf_level})
    return g, pa, pb


# ---------- 萤草基础能力：形态不同则抽牌 ----------

def test_yingcao_draws_on_different_form(make_game):
    """使用与当前形态不同的形态牌 → 抽 1；同形态再结附不触发。"""
    g, pa, pb = _game(make_game)
    hand = len(pa.hand)
    play(g, 0, FORM_A)                        # 无当前形态 → 不同 → 抽 1
    assert len(pa.hand) == hand + 1
    play(g, 0, FORM_A)                        # 同形态（id 相同）→ 不抽
    assert len(pa.hand) == hand + 1
    play(g, 0, FORM_B)                        # 不同形态 → 抽 1
    assert len(pa.hand) == hand + 2


# ---------- 灵矢贯虹：法术强化镜像 + 羁绊 1 ----------

def test_lingshi_mirrors_spell_buff_power(make_game):
    """起弓（+1）与离（+3）挂账中：灵矢贯虹使白狼再次临时获得合计 4 力量
    （仅力量部分；三条 attack_buffs 挂账 [1, 3, 4]），本次攻击一并生效。"""
    g, pa, pb = _game(make_game, wolf_level=3)
    play(g, 0, QIGONG)                        # 起弓：+1 力量 & 穿刺（瞬发免费）
    play(g, 0, LI)                            # 离：+3 力量（瞬发名额已用，1 火）
    wolf = pa.shikigami[1]
    assert [e["power"] for e in wolf.attack_buffs] == [1, 3]
    play(g, 0, LSGH)                          # 灵矢贯虹：+2/+2 + 镜像 +4 → 攻 3+4+2+4=13
    assert pb.health == 17                    # 敌方空战斗区：13 攻打牌手
    assert wolf.attack_buffs == []            # 攻击后到期强化（含镜像）战斗后核销


def test_lingshi_bond1_replays_form_enter(make_game):
    """羁绊 1：攻击前触发萤草当前形态进场效果（形态 B 进场 +2 护甲再执行一次）。"""
    g, pa, pb = _game(make_game, wolf_level=2)
    play(g, 0, FORM_B)                        # 结附形态 B：进场 +2 护甲
    assert pa.shikigami[IDX].shield == 2
    play(g, 0, LSGH)
    assert pa.shikigami[IDX].shield == 4      # 羁绊 1：进场效果再触发 +2


def test_lingshi_bond1_no_form_noop(make_game):
    """萤草未结附形态（当前正式数据永远如此）：羁绊 1 空操作，战斗照常。"""
    g, pa, pb = _game(make_game, wolf_level=2)
    play(g, 0, LSGH)                          # 白狼 3+2=5 攻打牌手
    assert pb.health == 25
    assert pa.shikigami[IDX].form is None
