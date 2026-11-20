"""卡组主题测试：组卡规则校验（4 式神、派系 ≤2（不计无相）、同源互斥、中立/衍生/
召唤物禁入、8 种 ×2）+ 卡组码（编码/解码往返、结构校验）（原 test_deckcode.py）
+ 本地卡组存储与 GUI 可构筑数据池（原 test_deckstore.py）。
"""
import pytest

from client import deckbuilder
from db import deckcode, deckstore
from db.deck import validate_deck
from db.test_data import TEST_IDS, make_test_db, make_test_deck
from tests import factories as F


def test_valid_deck(db):
    assert validate_deck(db, F.TEAM, F.deck_of(*F.TEAM)) == []


def test_requires_four_shikigami(db):
    errors = validate_deck(db, [100101, 100102], F.deck_of(100101, 100102))
    assert any("4 名" in e for e in errors)


def test_faction_limit_excluding_wuxiang(db):
    s = [F.shiki(100101, faction="红莲"), F.shiki(100102, faction="紫岩"),
         F.shiki(100103, faction="青岚"), F.shiki(100104, faction="苍叶")]
    cards = [F.card(sid * 100 + n, shikigami=sid) for sid in F.TEAM for n in range(1, 9)]
    db2 = F.db_of(s, cards)
    errors = validate_deck(db2, F.TEAM, F.deck_of(*F.TEAM))
    assert any("派系" in e for e in errors)
    # 把其中一个换成无相：派系数降为 3 仍超；再换一个为红莲：红莲/紫岩/无相 → 合法
    db2.shikigami[100103].faction = "无相"
    db2.shikigami[100104].faction = "红莲"
    assert validate_deck(db2, F.TEAM, F.deck_of(*F.TEAM)) == []


def test_origin_conflict(db):
    s = [F.shiki(100101, name="般若", origin="般若"),
         F.shiki(100102, name="SP般若", origin="般若"),
         F.shiki(100103), F.shiki(100104)]
    db2 = F.db_of(s, [])
    errors = validate_deck(db2, F.TEAM, F.deck_of(*F.TEAM))
    assert any("同源" in e for e in errors)


def test_neutral_banned(db):
    db.cards[19990001] = F.card(19990001, shikigami=None)
    errors = validate_deck(db, F.TEAM, F.deck_of(*F.TEAM) + [19990001])
    assert any("中立牌" in e for e in errors)


def test_token_banned(db):
    db.cards[10010195] = F.card(10010195, token=True)
    errors = validate_deck(db, F.TEAM, F.deck_of(*F.TEAM) + [10010195])
    assert any("衍生卡" in e for e in errors)


def test_summon_banned_in_team(db):
    db.shikigami[10010190] = F.shiki(10010190, kind="summon")
    errors = validate_deck(db, [100101, 100102, 100103, 10010190], [])
    assert any("召唤物" in e for e in errors)


# 注：每式神 ≤8 种的上限已由 id 号段结构性保证（可构筑卡序号仅 01-08），
# validate_deck 中的 MAX_KINDS_PER_SHIKIGAMI 检查作为防御性保留，不再单测触发。


def test_too_many_copies(db):
    errors = validate_deck(db, F.TEAM, [10010101] * 3)
    assert any("超过同式神限" in e for e in errors)
    assert any("超过全卡组限" in e for e in errors)


def test_reinforce_deck_rules(db):
    """协战牌：所属式神任一出战即可编入（占其 8 张名额）；同名仍限 2；均未出战则不可编。"""
    base = F.deck_of(*F.TEAM)
    # 换入 2 张协战牌（替换 100101 的两张牌，保持恰好 8 张）
    db.cards[10010121] = F.card(10010121, card_type="reinforce", shikigami2=100102)
    deck = [c for c in base if c != 10010104] + [10010121] * 2
    assert validate_deck(db, F.TEAM, deck) == []
    errors = validate_deck(db, F.TEAM, deck + [10010121])
    assert any("超过全卡组限" in e for e in errors)  # 协战牌同名 3 张（全局计数）
    # 只有第一所属在队（第二所属未出战）也可以编
    db.shikigami[100105] = F.shiki(100105)
    db.cards[10010321] = F.card(10010321, shikigami=100103,
                                card_type="reinforce", shikigami2=100105)
    deck2 = base.copy()
    deck2.remove(10010304)  # 只替换一张，保持恰好 8 张
    deck2.append(10010321)
    assert validate_deck(db, F.TEAM, deck2) == []
    # 两位所属式神均未出战：不可编
    db.shikigami[100106] = F.shiki(100106)
    db.cards[10010521] = F.card(10010521, shikigami=100105, card_type="reinforce", shikigami2=100106)
    errors = validate_deck(db, F.TEAM, deck2 + [10010521])
    assert any("均未出战" in e for e in errors)


def test_exactly_eight_cards_per_shikigami(db):
    """天梯规则：每名式神恰好 8 张牌（多/少均不合法）。"""
    deck = F.deck_of(*F.TEAM)
    assert validate_deck(db, F.TEAM, deck) == []
    errors = validate_deck(db, F.TEAM, deck[:-1])          # 7 张
    assert any("恰好 8 张" in e for e in errors)
    errors = validate_deck(db, F.TEAM, deck + [10010105])  # 9 张
    assert any("恰好 8 张" in e for e in errors)


def test_buildable_suffix_range(db):
    """专属牌构筑序号仅 01-08；协战牌暂只开放 21。"""
    db.cards[10010109] = F.card(10010109)
    deck = F.deck_of(*F.TEAM)[:-1] + [10010109]
    errors = validate_deck(db, F.TEAM, deck)
    assert any("未开放构筑" in e for e in errors)
    db.cards[10010122] = F.card(10010122, card_type="reinforce", shikigami2=100102)
    errors = validate_deck(db, F.TEAM, deck[:-1] + [10010122])
    assert any("协战牌序号 22 未开放构筑" in e for e in errors)


def test_custom_deck_rules(db):
    """对局模式卡组约束：DeckRules 各配置项可放宽/收紧；rules=None 无约束。"""
    from db.deck import DeckRules
    deck = F.deck_of(*F.TEAM)
    # 每名式神各去掉一张（恰好 7 张/人）
    short = deck.copy()
    for sid in F.TEAM:
        short.remove(sid * 100 + 4)
    # 默认规则下 7 张不合法；各式神带卡 [7,7,7,7] 的模式下合法
    errors = validate_deck(db, F.TEAM, short)
    assert errors
    assert validate_deck(db, F.TEAM, short,
                         DeckRules(cards_per_shikigami=[7, 7, 7, 7])) == []
    # 各式神带卡数量按队伍顺序一一对应：仅末位 7 张时，4 号位 7 张合法、1 号位 7 张不合法
    last_short = deck.copy()
    last_short.remove(F.TEAM[3] * 100 + 4)
    assert validate_deck(db, F.TEAM, last_short,
                         DeckRules(cards_per_shikigami=[8, 8, 8, 7])) == []
    assert validate_deck(db, F.TEAM, last_short,
                         DeckRules(cards_per_shikigami=[7, 8, 8, 8]))
    # 同名限 3 的模式（同式神与全卡组两个配置项独立）
    errors = validate_deck(db, F.TEAM, [10010101] * 3,
                           DeckRules(max_copies_per_name=3))
    assert any("超过全卡组限" in e for e in errors)      # 全卡组仍限 2
    errors = validate_deck(db, F.TEAM, [10010101] * 3,
                           DeckRules(max_copies_per_name=3, max_copies_deck=3))
    assert not any("超过" in e for e in errors)
    # 出战 3 名模式
    three = F.TEAM[:3]
    assert validate_deck(db, three, F.deck_of(*three),
                         DeckRules(required_shikigami=3,
                                   cards_per_shikigami=[8, 8, 8])) == []
    assert validate_deck(db, F.TEAM, deck,
                         DeckRules(required_shikigami=3,
                                   cards_per_shikigami=[8, 8, 8]))
    # rules=None：无约束，直接判合法
    assert validate_deck(db, [100101], [], None) == []


def test_deck_rules_config_validation(db):
    """DeckRules 配置自校验：数量越界/列表长度不符/非正带卡数均拒绝。"""
    from db.deck import DeckRules
    import pytest
    with pytest.raises(ValueError):
        DeckRules(required_shikigami=5)
    with pytest.raises(ValueError):
        DeckRules(required_shikigami=3, cards_per_shikigami=[8, 8, 8, 8])
    with pytest.raises(ValueError):
        DeckRules(cards_per_shikigami=[8, 8, 8, 0])


def test_rules_summary_renders_rules(db):
    """规则提示文本与 DeckRules 取值同步（构筑界面打印的标准规则细节）。"""
    from db.deck import DeckRules, rules_summary
    text = "\n".join(rules_summary())
    assert "4 名" in text and "8 张" in text and "限 2" in text
    custom = "\n".join(rules_summary(DeckRules(
        required_shikigami=3, cards_per_shikigami=[7, 7, 7], max_copies_deck=3)))
    assert "3 名" in custom and "7 张" in custom and "全卡组限 3" in custom


def test_card_of_benched_shikigami(db):
    db.shikigami[100105] = F.shiki(100105)
    db.cards[10010501] = F.card(10010501, shikigami=100105)
    errors = validate_deck(db, F.TEAM, F.deck_of(*F.TEAM) + [10010501])
    assert any("未出战" in e for e in errors)


# ==========================================================================
# 卡组码（原 test_deckcode.py，db/deckcode.py）
# ==========================================================================

def test_deck_code_roundtrip():
    """默认测试卡组：分组 → 编码 → 解码一致；deck_from_code 还原式神与卡牌列表。"""
    db = make_test_db()
    ids, cards = list(TEST_IDS), list(make_test_deck())
    groups = deckcode.group_deck(db, ids, cards)
    assert sum(len(c) for _, c in groups) == len(cards)  # 全卡可归组
    code = deckcode.encode_deck(groups)
    assert deckcode.decode_deck(code) == groups
    ids2, cards2 = deckcode.deck_from_code(db, code)
    assert ids2 == ids and cards2 == cards


def test_deck_code_compact_and_urlsafe():
    """卡组码为简短的 urlsafe 纯文本（无 + / = 字符）。"""
    db = make_test_db()
    code = deckcode.encode_deck(
        deckcode.group_deck(db, list(TEST_IDS), list(make_test_deck())))
    assert len(code) < 200
    assert all(ch not in code for ch in "+/=")


def test_group_deck_sorts_cards_within_shikigami():
    """组内卡牌按 id 升序规范化（落盘/导出即有序）；式神顺序保留输入顺序。"""
    db = make_test_db()
    ids = list(TEST_IDS)
    cards = list(make_test_deck())
    shuffled = list(reversed(cards))                  # 乱序输入
    groups = deckcode.group_deck(db, ids, shuffled)
    assert [sid for sid, _ in groups] == ids          # 式神顺序不变
    for _, cs in groups:
        assert cs == sorted(cs)                       # 组内升序
    assert sorted(cid for _, cs in groups for cid in cs) == sorted(cards)
    # 与正序输入结果一致：已有卡组码语义不变（仅组内顺序规范化）
    assert groups == deckcode.group_deck(db, ids, cards)


def test_decode_rejects_garbage():
    """非卡组码输入：抛 ValueError。"""
    with pytest.raises(ValueError):
        deckcode.decode_deck("not-a-deck-code")
    with pytest.raises(ValueError):
        deckcode.decode_deck("")


def test_deck_from_code_rejects_illegal_deck():
    """结构合法但违反组卡规则（仅 3 名式神）：抛 ValueError。"""
    db = make_test_db()
    code = deckcode.encode_deck([(sid, []) for sid in TEST_IDS[:3]])
    with pytest.raises(ValueError, match="卡组不合法"):
        deckcode.deck_from_code(db, code)


def test_available_deck_from_code_skips_rule_validation():
    """available_deck_from_code（构筑编辑/导入用）：仅校验可用性——违反组卡规则的
    非标准卡组可解析（仅不标 is_standard）；id 不存在/卡牌不属于出战式神仍拒绝。"""
    db = make_test_db()
    code = deckcode.encode_deck([(sid, []) for sid in TEST_IDS[:3]])
    ids, cards = deckcode.available_deck_from_code(db, code)  # 3 式神：非标准但可用
    assert ids == list(TEST_IDS[:3]) and cards == []
    bad = deckcode.encode_deck([(TEST_IDS[0], [99999999])])
    with pytest.raises(ValueError, match="不存在"):
        deckcode.available_deck_from_code(db, bad)
    stray = deckcode.encode_deck([(sid, []) for sid in TEST_IDS])
    stray_cards = [[sid, cs + ([10000101] if i == 0 else cs)]
                   for i, (sid, cs) in enumerate(deckcode.decode_deck(stray))]
    with pytest.raises(ValueError, match="不属于出战式神"):
        deckcode.available_deck_from_code(db, deckcode.encode_deck(stray_cards))


# ==========================================================================
# 本地卡组存储 v2 与卡组构筑/战前选卡（原 test_deckstore.py，
# db/deckstore.py 与 client/deckbuilder.py）
# ==========================================================================

def mk_groups(db, sids=None):
    sids = list(sids or F.TEAM)
    return deckcode.group_deck(db, sids, F.deck_of(*sids))


def mk_code(db, sids=None) -> str:
    return deckcode.encode_deck(mk_groups(db, sids))


def mk_entry(db, name="x", sids=None) -> dict:
    return {"name": name, "groups": mk_groups(db, sids)}


# ---------- deckstore 读写 ----------

def test_store_roundtrip(db, tmp_path):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "快攻"), mk_entry(db, "控制")], p)
    decks = deckstore.load_decks(db, p)
    assert [d["name"] for d in decks] == ["快攻", "控制"]
    assert all(d["standard"] for d in decks)  # 加载时重新校验
    assert decks[0]["groups"] == [[sid, cs] for sid, cs in mk_groups(db)]


def test_store_missing_file(db, tmp_path):
    assert deckstore.load_decks(db, tmp_path / "decks.json") == []


def test_store_legacy_migration(db, tmp_path, monkeypatch):
    """旧路径 ~/.bwp.decks.json：新文件不存在时自动迁移（复制后删旧）。"""
    new = tmp_path / ".bwpro" / "decks.json"
    legacy = tmp_path / ".bwp.decks.json"
    monkeypatch.setattr(deckstore, "PATH", new)
    monkeypatch.setattr(deckstore, "LEGACY_PATH", legacy)
    deckstore.save_decks(db, [mk_entry(db, "旧卡组")], legacy)
    decks = deckstore.load_decks(db, new)
    assert [d["name"] for d in decks] == ["旧卡组"]
    assert new.exists() and not legacy.exists()


def test_store_legacy_kept_when_new_exists(db, tmp_path, monkeypatch):
    """新文件已存在时不迁移不覆盖，旧文件原样保留。"""
    new = tmp_path / ".bwpro" / "decks.json"
    legacy = tmp_path / ".bwp.decks.json"
    monkeypatch.setattr(deckstore, "PATH", new)
    monkeypatch.setattr(deckstore, "LEGACY_PATH", legacy)
    deckstore.save_decks(db, [mk_entry(db, "旧")], legacy)
    deckstore.save_decks(db, [mk_entry(db, "新")], new)
    assert [d["name"] for d in deckstore.load_decks(db, new)] == ["新"]
    assert legacy.exists()


def test_store_legacy_malformed_deleted(db, tmp_path, monkeypatch, capsys):
    """旧文件格式异常：迁移后按惯例提示并删除（作用于新路径）。"""
    new = tmp_path / ".bwpro" / "decks.json"
    legacy = tmp_path / ".bwp.decks.json"
    monkeypatch.setattr(deckstore, "PATH", new)
    monkeypatch.setattr(deckstore, "LEGACY_PATH", legacy)
    legacy.write_text("not json", encoding="utf-8")
    assert deckstore.load_decks(db, new) == []
    assert not new.exists() and not legacy.exists()
    assert "本地卡组文件异常" in capsys.readouterr().out


def test_store_malformed_file_deleted(db, tmp_path, capsys):
    """文件数据不符合应有格式：提示异常并删除文件。"""
    for raw in ("not json",
                '{"version": 1, "decks": [{"name": "x", "code": "y"}]}',  # 旧格式
                '{"version": 2, "decks": [["yes", {"name": "x", "groups": []}]]}',
                '{"version": 2, "decks": [[true, {"name": 1, "groups": []}]]}'):
        p = tmp_path / "decks.json"
        p.write_text(raw, encoding="utf-8")
        assert deckstore.load_decks(db, p) == []
        assert not p.exists()
        assert "本地卡组文件异常" in capsys.readouterr().out


def test_non_standard_deck_flag(db, tmp_path):
    """结构合法但不满足天梯规则的卡组：保留但 is_standard=False。"""
    p = tmp_path / "decks.json"
    bad = {"name": "三人队", "groups": mk_groups(db, F.TEAM[:3])}
    deckstore.save_decks(db, [bad, mk_entry(db, "好")], p)
    decks = deckstore.load_decks(db, p)
    assert [d["standard"] for d in decks] == [False, True]


# ---------- 可构筑数据池 ----------

def test_buildable_cards_reinforce_listed_under_both_owners(gdb):
    """协战牌同时列入两位所属式神的可选卡牌（海国共主 = 铃鹿御前 & 大岳丸）；
    unreleased 协战牌（风之乐章 10012421，哨兵日期占位）不列入。"""
    # 正向双归属测试使用测试内可用副本；实际海国共主仍为未加入。
    gdb.cards[10020721] = gdb.cards[10020721].model_copy(update={"unreleased": False})
    assert any(c.id == 10020721 for c in deckbuilder.buildable_cards(gdb, 100207))
    assert any(c.id == 10020721 for c in deckbuilder.buildable_cards(gdb, 100408))
    assert not any(c.id == 10012421 for c in deckbuilder.buildable_cards(gdb, 100124))
    assert not any(c.id == 10012421 for c in deckbuilder.buildable_cards(gdb, 100125))


def test_buildable_cards_main_first_reinforce_last(gdb):
    """可携带卡牌排序：本家 8 张（01-08）按 id 升序在前，协战牌列最后——
    协战第二所属式神（鸮羽共鸣主式神 id 更小）的列表中协战牌不再排最前。"""
    gdb.cards[10030721] = gdb.cards[10030721].model_copy(update={"unreleased": False})
    shanfeng = deckbuilder.buildable_cards(gdb, 100307)
    assert [c.id for c in shanfeng[:8]] == [10030700 + n for n in range(1, 9)]
    assert shanfeng[-1].id == 10030721           # 鸮羽共鸣列最后
    xun = deckbuilder.buildable_cards(gdb, 100405)
    assert [c.id for c in xun[:8]] == [10040500 + n for n in range(1, 9)]
    assert xun[-1].id == 10030721


def test_available_shikigami_excludes_wip_and_unreleased(gdb):
    """构筑可选池：wip=true 的半成品式神不可选（当前 wip 已清零——04 沧海刀鸣包
    10 式神全部落地去标）；unreleased=true 的未加入游戏式神（纸人武士/天邪鬼军团，
    哨兵日期 20201224 占位）同样排除。"""
    ids = [d.id for d in deckbuilder.available_shikigami(gdb)]
    wip_ids = {d.id for d in gdb.shikigami.values() if d.wip}
    assert wip_ids == set()  # 04 包完结，wip 清零
    assert not (wip_ids & set(ids))  # wip 全部排除在构筑可选池外
    assert 100401 in ids                 # 人面树（已落地去 wip）可选
    assert 100402 in ids                 # 跳跳哥哥（已落地去 wip）可选
    assert 100403 in ids                 # 樱花妖（已落地去 wip）可选
    assert 100404 in ids                 # 三目（委托机制落地，已去 wip）可选
    assert 100405 in ids                 # 薰（已落地去 wip）可选
    assert 100406 in ids                 # 食梦貘（牌库灵咒落地，已去 wip）可选
    assert 100407 in ids                 # 御馔津（已落地去 wip）可选
    assert 100408 in ids                 # 大岳丸（已落地去 wip）可选
    assert 100409 in ids                 # 鬼切（鬼斩落地，已去 wip）可选
    assert 100410 in ids                 # 巫蛊师（已落地去 wip）可选
    assert 100112 in ids                 # 青行灯（8 卡齐，已去 wip）可选
    assert 100106 in ids and 100109 in ids   # 姑获鸟/酒吞童子（8 卡齐，已去 wip）可选
    assert 100001 not in ids and 100002 not in ids  # 纸人武士/天邪鬼军团（unreleased）排除
    assert 100105 in ids and 100116 in ids   # 凤凰火/山童（8 卡齐）可选
