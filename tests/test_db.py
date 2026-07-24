"""schema 与校验器测试：id 号段、version、未知字段保留、加载即校验。"""
import pytest
from pydantic import ValidationError

from db.schema import CardDef, ShikigamiDef
from tests import factories as F


def _card(**over):
    base = {
        "id": 10010199,
        "version": 20260720,
        "name": "测试卡",
        "shikigami": 100101,
        "card_type": "spell",
        "level": 1,
        "cost": 1,
        "effects": {"when": "on_play", "steps": []},
    }
    base.update(over)
    return base


def test_card_id_must_be_8_digits():
    with pytest.raises(ValidationError):
        CardDef.model_validate(_card(id=100101))       # 6 位
    with pytest.raises(ValidationError):
        CardDef.model_validate(_card(id=100101999))    # 9 位
    CardDef.model_validate(_card(id=10010101))
    CardDef.model_validate(_card(id=99999999))


def test_shikigami_id_6_or_8_digits():
    def _shiki(**over):
        base = {"id": 100101, "version": 20260720, "name": "测试", "power": 1, "health": 1}
        base.update(over)
        return base

    with pytest.raises(ValidationError):
        ShikigamiDef.model_validate(_shiki(id=1001))        # 4 位
    ShikigamiDef.model_validate(_shiki(id=100101))          # 6 位式神
    ShikigamiDef.model_validate(_shiki(id=10010190))        # 8 位召唤物


def test_version_must_be_8_digit_date():
    with pytest.raises(ValidationError):
        CardDef.model_validate(_card(version=2026072))
    with pytest.raises(ValidationError):
        CardDef.model_validate(_card(version=20260229))   # 2026 非闰年
    CardDef.model_validate(_card(version=20240229))       # 2024 闰年 ok


def test_unknown_fields_preserved():
    c = CardDef.model_validate(_card(balance_note="待调整", ext={"foo": 1}))
    assert c.model_extra["balance_note"] == "待调整"
    assert c.model_extra["ext"] == {"foo": 1}


def test_validate_catches_id_prefix_mismatch(db):
    """卡牌 id 前缀必须与所属式神一致。"""
    db.cards[10010205] = F.card(10010205, shikigami=100101)  # 前缀 100102 ≠ 100101
    errors = db.validate()
    assert any("不一致" in e for e in errors)


def test_validate_catches_bad_faction(db):
    db.shikigami[100101].faction = "黄金"
    errors = db.validate()
    assert any("派系" in e for e in errors)


def test_validate_summon_rules(db):
    """召唤物：8 位 id、90-99 号段（从 99 递减）、从属式神必须存在。"""
    db.shikigami[10010150] = F.shiki(10010150, kind="summon")   # 序号 50，不在 90-99
    errors = db.validate()
    assert any("90-99" in e for e in errors)
    db2 = F.db_of([F.shiki(10010199, kind="summon")], [])       # 从属 100101 不存在
    errors2 = db2.validate()
    assert any("从属" in e for e in errors2)


def test_validate_neutral_format(db):
    db.cards[10010196] = F.card(10010196, shikigami=None)       # 中立但前缀不是 9999
    errors = db.validate()
    assert any("9999zzzz" in e for e in errors)


def test_validate_token_suffix(db):
    """衍生卡序号须在 51-99（从 51 递增）；可构筑卡牌序号须在 01-08。"""
    db.cards[10010110] = F.card(10010110, token=True)           # 衍生卡序号 < 51
    errors = db.validate()
    assert any("51-99" in e for e in errors)
    db.cards[10010120] = F.card(10010120)                       # 构筑卡序号 > 08
    errors = db.validate()
    assert any("01-08" in e for e in errors)


def test_awaken_is_subtype_not_card_type(db):
    """觉醒牌 = 任意主类型 + subtype=awaken；card_type 不再接受 awaken。"""
    db.cards[10010196] = F.card(10010196, card_type="form", subtype="awaken", token=True)
    assert db.validate() == []
    db.cards[10010197] = F.card(10010197, card_type="awaken", token=True)
    assert any("主类型" in e for e in db.validate())


def test_field_and_reinforce_card_types_reserved(db):
    """幻境牌 field / 协战牌 reinforce：预留主类型，校验放行。"""
    db.cards[10010196] = F.card(10010196, card_type="field", token=True)
    db.cards[10010121] = F.card(10010121, card_type="reinforce", shikigami2=100102)
    assert db.validate() == []


def test_rarity_reserved(db):
    """稀有度 R/SR/SSR 预留（抽卡/账号系统用），仅做取值校验。"""
    db.cards[10010196] = F.card(10010196, rarity="SSR", token=True)
    assert db.validate() == []
    db.cards[10010197] = F.card(10010197, rarity="UR", token=True)
    assert any("稀有度" in e for e in db.validate())


def test_reinforce_card_rules(db):
    """协战牌：须记录两位所属式神；id 前六位为两者中较小者；序号从 21 递增。"""
    db.cards[10010121] = F.card(10010121, card_type="reinforce", shikigami2=100102)
    assert db.validate() == []
    db.cards[10010221] = F.card(10010221, card_type="reinforce",
                                shikigami=100102, shikigami2=100101)   # 前缀应为较小者 100101
    assert any("较小者" in e for e in db.validate())
    db.cards[10010105] = F.card(10010105, card_type="reinforce", shikigami2=100102)
    assert any("21" in e for e in db.validate())                       # 序号须从 21 起
    db.cards[10010122] = F.card(10010122, card_type="reinforce")
    assert any("两位所属式神" in e for e in db.validate())             # 缺 shikigami2


def test_dummy_db_is_valid():
    from db.dummy import make_dummy_db
    assert make_dummy_db().validate() == []
