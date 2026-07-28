"""db 层测试：schema 与校验器（id 号段、version、未知字段保留、加载即校验）
+ db.scaffold 脚手架（生成骨架 → loader 校验通过；tmp_path 隔离）（原 test_scaffold.py）。
"""
import pytest
import yaml
from pydantic import ValidationError

from db.loader import CardDatabase
from db.scaffold import scaffold_card, scaffold_shikigami
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
    """中立牌 id 须为 9avvvvvv（9 + 1 位异画位 + 6 位数字，自 999999 递减）。"""
    db.cards[10010196] = F.card(10010196, shikigami=None)       # 中立但首位不是 9
    errors = db.validate()
    assert any("9avvvvvv" in e for e in errors)
    del db.cards[10010196]
    db.cards[90999999] = F.card(90999999, shikigami=None)       # 默认异画首个中立 id
    assert not db.validate()


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


# ==========================================================================
# db.scaffold 脚手架（原 test_scaffold.py）
# ==========================================================================

def _load(root):
    db = CardDatabase.load(root, strict=False)
    assert db.validate() == []
    return db


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "shikigami").mkdir()
    (tmp_path / "cards").mkdir()
    return tmp_path


def _make_shikigami(root, sid=100127, name="测试式神", faction="苍叶"):
    written = scaffold_shikigami(root, id=sid, name=name, faction=faction,
                                 power=2, health=5)
    return written[0]


def test_scaffold_shikigami_validates(root):
    path = _make_shikigami(root)
    assert path == root / "shikigami" / "100127.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["id"] == 100127 and data["faction"] == "苍叶"
    assert data["power"] == 2 and data["health"] == 5
    db = _load(root)
    assert 100127 in db.shikigami


def test_scaffold_shikigami_with_cards(root):
    written = scaffold_shikigami(root, id=100127, name="测试式神", faction="苍叶",
                                 power=2, health=5, with_cards=True)
    assert len(written) == 9  # 1 式神 + 8 卡
    db = _load(root)
    levels = [db.cards[10012700 + seq].level for seq in range(1, 9)]
    assert levels == [1, 1, 1, 2, 2, 2, 3, 3]


def test_scaffold_card_validates_and_faction_inherited(root):
    _make_shikigami(root)
    path = scaffold_card(root, shikigami=100127, seq=1, name="测试卡",
                         card_type="spell", level=2, cost=1, rarity="SR")
    assert path == root / "cards" / "10012701.yaml"
    text = path.read_text(encoding="utf-8")
    assert "派系：苍叶" in text  # faction 从所属式神 yaml 继承（注释展示）
    data = yaml.safe_load(text)
    assert data["id"] == 10012701 and data["effects"]["steps"] == []
    db = _load(root)
    assert db.cards[10012701].rarity == "SR"


def test_scaffold_card_requires_existing_shikigami(root):
    with pytest.raises(ValueError, match="不存在"):
        scaffold_card(root, shikigami=100127, seq=1, name="x", card_type="spell")


def test_scaffold_token_id_rules(root):
    _make_shikigami(root)
    scaffold_card(root, shikigami=100127, seq=51, name="衍生卡",
                  card_type="spell", token=True)
    db = _load(root)
    assert db.cards[10012751].token is True
    with pytest.raises(ValueError, match="51-99"):
        scaffold_card(root, shikigami=100127, seq=9, name="x",
                      card_type="spell", token=True)
    with pytest.raises(ValueError, match="01-08"):
        scaffold_card(root, shikigami=100127, seq=9, name="x", card_type="spell")


def test_scaffold_reinforce_dual_owner(root):
    _make_shikigami(root, sid=100127, name="甲")
    _make_shikigami(root, sid=100101, name="乙", faction="红莲")
    # id 前六位 = 两位所属中较小者（100101），序号从 21 开始
    path = scaffold_card(root, shikigami=100127, seq=21, name="协战卡",
                         card_type="reinforce", shikigami2=100101)
    assert path == root / "cards" / "10010121.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["shikigami"] == 100101 and data["shikigami2"] == 100127
    db = _load(root)
    c = db.cards[10010121]
    assert {c.shikigami, c.shikigami2} == {100101, 100127}
    with pytest.raises(ValueError, match="--shikigami2"):
        scaffold_card(root, shikigami=100127, seq=21, name="x", card_type="reinforce")
    with pytest.raises(ValueError, match="仅协战牌"):
        scaffold_card(root, shikigami=100127, seq=1, name="x",
                      card_type="spell", shikigami2=100101)


def test_scaffold_form_and_awaken_skeleton(root):
    _make_shikigami(root)
    scaffold_card(root, shikigami=100127, seq=3, name="形态卡", card_type="form")
    scaffold_card(root, shikigami=100127, seq=7, name="觉醒卡",
                  card_type="spell", awaken=True)
    db = _load(root)
    assert db.cards[10012703].form_power == 3
    assert db.cards[10012707].subtype == "awaken"


def test_refuse_overwrite_and_force(root):
    path = _make_shikigami(root)
    with pytest.raises(FileExistsError):
        _make_shikigami(root)
    scaffold_shikigami(root, id=100127, name="改名", faction="苍叶",
                       power=3, health=6, force=True)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "改名" and data["power"] == 3
