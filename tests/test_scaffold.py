"""db.scaffold 脚手架测试：生成骨架 → loader 校验通过；tmp_path 隔离。"""
import pytest
import yaml

from db.loader import CardDatabase
from db.scaffold import scaffold_card, scaffold_shikigami


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
