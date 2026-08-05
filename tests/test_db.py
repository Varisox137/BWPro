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
    return tmp_path


def _make_shikigami(root, sid=100127, name="测试式神", faction="苍叶", slug="ceshi"):
    written = scaffold_shikigami(root, id=sid, name=name, faction=faction,
                                 power=2, health=5, slug=slug)
    return written[0]


def test_scaffold_shikigami_validates(root):
    path = _make_shikigami(root)
    assert path == root / "01_jingdian" / "27_ceshi" / "100127.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    snap = data["versions"]["history"][0]  # 顶层仅 id/name/versions，数据在快照中
    assert data["id"] == 100127 and snap["faction"] == "苍叶"
    assert snap["power"] == 2 and snap["health"] == 5
    assert data["versions"]["best"] == snap["date"]
    db = _load(root)
    assert 100127 in db.shikigami


def test_scaffold_shikigami_with_cards(root):
    written = scaffold_shikigami(root, id=100127, name="测试式神", faction="苍叶",
                                 power=2, health=5, slug="ceshi", with_cards=True)
    assert len(written) == 9  # 1 式神 + 8 卡
    db = _load(root)
    levels = [db.cards[10012700 + seq].level for seq in range(1, 9)]
    assert levels == [1, 1, 1, 2, 2, 2, 3, 3]


def test_scaffold_card_validates(root):
    _make_shikigami(root)
    path = scaffold_card(root, shikigami=100127, seq=1, name="测试卡",
                         card_type="spell", level=2, cost=1, rarity="SR")
    assert path == root / "01_jingdian" / "27_ceshi" / "10012701.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    snap = data["versions"]["history"][0]
    assert data["id"] == 10012701 and snap["effects"]["steps"] == []
    assert "shikigami" not in snap  # 所属由 id 前六位推导，不入数据
    assert "cost" not in snap       # cost 默认 1，不写入
    db = _load(root)
    assert db.cards[10012701].rarity == "SR"
    assert db.cards[10012701].shikigami == 100127  # 加载时推导注入


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
    _make_shikigami(root, sid=100101, name="乙", faction="红莲", slug="yi")
    # id 前六位 = 两位所属中较小者（100101），序号从 21 开始；本体归主式神目录
    path = scaffold_card(root, shikigami=100127, seq=21, name="协战卡",
                         card_type="reinforce", shikigami2=100101)
    assert path == root / "01_jingdian" / "01_yi" / "10010121.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    snap = data["versions"]["history"][0]
    assert "shikigami" not in snap and snap["shikigami2"] == 100127
    db = _load(root)
    c = db.cards[10010121]
    assert {c.shikigami, c.shikigami2} == {100101, 100127}  # 主归属由 id 推导注入
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
                       power=3, health=6, slug="ceshi", force=True)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "改名" and data["versions"]["history"][0]["power"] == 3


# ==========================================================================
# 平衡性多版本（db/versioning.py + CardDatabase.at_date）
# ==========================================================================

def _versioned_db():
    """含版本时间线的最小库（顶层仅 id/name/versions，history 每条为完整快照）：
    式神 100101 与其卡 10010101（发布 20260101、20260301 调整、最新 20260501，
    式神 best=20260301）；单快照卡 10010102（发布 20260201）。"""
    shiki_raw = {
        "id": 100101, "name": "测试",
        "versions": {"best": 20260301, "history": [
            {"date": 20260101, "faction": "红莲", "power": 2, "health": 3},
            {"date": 20260301, "faction": "红莲", "power": 4, "health": 3},
            {"date": 20260501, "faction": "红莲", "power": 3, "health": 4},
        ]},
    }

    def _snap(date, **kw):
        return {"date": date, "card_type": "spell", "level": 1,
                "effects": {"when": "on_play", "steps": []}, **kw}

    card_raw = {
        "id": 10010101, "name": "测试卡",
        "versions": {"history": [
            _snap(20260101, cost=1, text="旧"),
            _snap(20260301, cost=2, text="旧"),
            _snap(20260501, cost=2, text="新"),
        ]},
    }
    plain_raw = {"id": 10010102, "name": "无史卡",
                 "versions": {"history": [_snap(20260201)]}}
    raw_cards = {c["id"]: c for c in (card_raw, plain_raw)}
    raw_shiki = {shiki_raw["id"]: shiki_raw}
    from db.loader import _inject_derived
    from db.versioning import resolve_latest
    cards = {i: CardDef.model_validate(_inject_derived(resolve_latest(r)))
             for i, r in raw_cards.items()}
    shiki = {i: ShikigamiDef.model_validate(resolve_latest(r))
             for i, r in raw_shiki.items()}
    return CardDatabase(cards, shiki, set(), raw_cards, raw_shiki)


def test_balance_version_resolve():
    """环境解析：取不晚于环境日期的最晚完整快照；生效日期写入 version。"""
    db = _versioned_db()
    d1 = db.at_date(20260201)  # 发布版本
    assert d1.shikigami[100101].power == 2
    assert d1.shikigami[100101].version == 20260101
    assert d1.cards[10010101].cost == 1 and d1.cards[10010101].text == "旧"
    assert d1.cards[10010101].shikigami == 100101  # 所属由 id 前六位推导注入
    d2 = db.at_date(20260301)  # 调整当日边界：含当条
    assert d2.shikigami[100101].power == 4
    assert d2.shikigami[100101].health == 3
    assert d2.cards[10010101].cost == 2 and d2.cards[10010101].text == "旧"
    d3 = db.at_date(20260501)  # 最新
    assert d3.shikigami[100101].power == 3 and d3.shikigami[100101].health == 4
    assert d3.cards[10010101].text == "新"
    assert db.at_date(None) is db  # 无环境 = 最新（快速路径）


def test_balance_version_availability():
    """环境日期早于发布日期 → 该 id 在环境库中不存在；单快照卡按发布日期判定。"""
    db = _versioned_db()
    early = db.at_date(20251231)
    assert 100101 not in early.shikigami and 10010101 not in early.cards
    mid = db.at_date(20260115)
    assert 100101 in mid.shikigami and 10010101 in mid.cards
    assert 10010102 not in mid.cards  # 发布 20260201 尚未到
    assert 10010102 in db.at_date(20260201).cards


def test_balance_version_malformed():
    """versions 结构校验：顶层多余字段/缺 versions/空 history/日期非法/乱序/
    身份字段/推导字段 shikigami/best 不在快照日期中均报错。"""
    from db.versioning import validate_versions
    assert validate_versions({}) != []  # 缺 versions 块
    extra = {"id": 1, "name": "x", "power": 3,
             "versions": {"history": [{"date": 20260101, "power": 3}]}}
    assert any("顶层" in e for e in validate_versions(extra))
    empty = {"id": 1, "name": "x", "versions": {"history": []}}
    assert any("不能为空" in e for e in validate_versions(empty))
    bad_date = {"id": 1, "name": "x",
                "versions": {"history": [{"date": 20261301, "cost": 0}]}}
    assert any("8 位" in e for e in validate_versions(bad_date))
    unordered = {"id": 1, "name": "x", "versions": {"history": [
        {"date": 20260301, "cost": 0}, {"date": 20260101, "cost": 0}]}}
    assert any("递增" in e for e in validate_versions(unordered))
    identity = {"id": 1, "name": "x",
                "versions": {"history": [{"date": 20260101, "name": "改"}]}}
    assert any("身份字段" in e for e in validate_versions(identity))
    derived = {"id": 1, "name": "x",
               "versions": {"history": [{"date": 20260101, "shikigami": 100101}]}}
    assert any("推导" in e for e in validate_versions(derived))
    bad_best = {"id": 1, "name": "x", "versions": {
        "best": 20260202, "history": [{"date": 20260101, "cost": 0}]}}
    assert any("best" in e for e in validate_versions(bad_best))


def test_balance_version_factory_db_at_date(db):
    """测试工厂库（无原始 dict）：at_date 退化为按 version 判可用。"""
    ver = next(iter(db.cards.values())).version
    assert db.at_date(ver).cards
    assert not db.at_date(20200101).cards


def test_balance_version_real_db(gdb):
    """真实库：at_date 按 versions 日期判可用（白狼/兵俑/茨木童子发布于 20191212）。"""
    assert gdb.at_date(None) is gdb
    assert not gdb.at_date(20190101).cards
    early = gdb.at_date(20200101)
    assert {100101, 100102, 100103} <= set(early.shikigami)
    latest = gdb.at_date(20991231)
    assert set(latest.cards) == set(gdb.cards)
    assert set(latest.shikigami) == set(gdb.shikigami)


def test_env_alias_parse_and_label():
    """环境别名注册表（db/envs.py）：别名大小写不敏感、8/6 位日期校验、显示名。"""
    from db.envs import env_label, parse_env_input

    assert parse_env_input("") is None
    assert parse_env_input("  ") is None
    assert parse_env_input("经典") == 20191212
    assert parse_env_input("公测") == 20191212   # 同一日期的多个别名
    assert parse_env_input("不夜之火") == 20200327
    assert parse_env_input("20191212") == 20191212
    assert parse_env_input("191212") == 20191212   # 6 位日期按 20YY 展开
    assert parse_env_input("200423") == 20200423
    with pytest.raises(ValueError):
        parse_env_input("S9")
    with pytest.raises(ValueError):
        parse_env_input("20191301")
    with pytest.raises(ValueError):
        parse_env_input("991312")              # 6 位展开后非法
    with pytest.raises(ValueError):
        parse_env_input("abc")
    assert env_label(None) == "标准(最新)"
    assert env_label(20191212) == "经典(20191212)"   # 同一日期取先登记别名
    assert env_label(20200327) == "不夜之火(20200327)"
    assert env_label(20251212) == "20251212"
