"""卡组主题测试：组卡规则校验（4 式神、派系 ≤2（不计无相）、同源互斥、中立/衍生/
召唤物禁入、8 种 ×2）+ 卡组码（编码/解码往返、结构校验）（原 test_deckcode.py）
+ 本地卡组存储 v2 与卡组构筑/战前选卡流程（原 test_deckstore.py）。
"""
import pytest

from client import deckbuilder
from db import deckcode, deckstore
from db.deck import validate_deck
from db.test_data import TEST_IDS, make_test_db, make_test_deck
from tests import factories as F
from tests.conftest import feed


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
    db.cards[99990001] = F.card(99990001, shikigami=None)
    errors = validate_deck(db, F.TEAM, F.deck_of(*F.TEAM) + [99990001])
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


# ---------- 战前选卡 ----------

def test_choose_deck_from_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "我的卡组")], p)
    feed(monkeypatch, ["1"])
    ids, cards, got = deckbuilder.choose_deck(db, "玩家A", p)
    assert got == mk_code(db) and ids == list(F.TEAM) and cards == F.deck_of(*F.TEAM)


def test_choose_deck_rejects_non_standard(db, tmp_path, monkeypatch, capsys):
    """所选卡组不满足对战模式规则：提示并重新选择。"""
    p = tmp_path / "decks.json"
    bad = {"name": "三人队", "groups": mk_groups(db, F.TEAM[:3])}
    deckstore.save_decks(db, [bad, mk_entry(db, "合法")], p)
    feed(monkeypatch, ["1", "2"])  # 先选不合法者 → 重选
    ids, cards, got = deckbuilder.choose_deck(db, "玩家A", p)
    assert "不满足当前对战模式" in capsys.readouterr().out
    assert got == mk_code(db)


def test_choose_deck_custom_rules(db, tmp_path, monkeypatch):
    """对战模式参数：自定义 DeckRules 下原"不合法"卡组可被接受。"""
    from db.deck import DeckRules
    p = tmp_path / "decks.json"
    deck = F.deck_of(*F.TEAM)
    for sid in F.TEAM:
        deck.remove(sid * 100 + 4)  # 每名式神 7 张
    short = {"name": "少牌队",
             "groups": deckcode.group_deck(db, list(F.TEAM), deck)}
    # 每人 7 张：天梯不合法（选择会要求重选），各式神带卡 [7,7,7,7] 模式下合法
    deckstore.save_decks(db, [short], p)
    feed(monkeypatch, ["1"])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p,
                                            DeckRules(cards_per_shikigami=[7, 7, 7, 7]))
    assert len(cards) == 28


def test_choose_deck_invalid_slot_falls_back(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db)], p)
    feed(monkeypatch, ["9"])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert (ids, cards) == deckcode.default_deck(db)


def test_choose_deck_empty_store(db, tmp_path, monkeypatch):
    """卡组文件为空：回退到卡组码输入（回车 = 默认卡组）。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, [mk_code(db)])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert ids == list(F.TEAM) and cards == F.deck_of(*F.TEAM)
    feed(monkeypatch, [""])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert (ids, cards) == deckcode.default_deck(db)


# ---------- 构筑（槽位管理） ----------

def test_deckbuilder_new_via_code(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    code = mk_code(db)
    feed(monkeypatch, ["", "快攻队", code])  # 新建 → 命名 → 卡组码导入
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "快攻队" and decks[0]["standard"]
    assert deckstore.entry_code(decks[0]) == code


def test_deckbuilder_edit_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    new = mk_code(db)
    feed(monkeypatch, ["1", "新名", new])
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "新名" and deckstore.entry_code(decks[0]) == new


def test_deckbuilder_edit_keep_name(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    feed(monkeypatch, ["1", "", mk_code(db)])  # 名称回车 = 沿用
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(db, p)[0]["name"] == "旧名"


def test_deckbuilder_new_interactive(db, tmp_path, monkeypatch):
    """交互式构筑：严格输入 4 名式神 + 每人恰好 8 个卡牌序号 → 自动保存。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",        # 新建 → 名称回车（自动命名）→ 交互式
                       "1 2 3 4",          # 4 名式神
                       "1 2 3 4 5 6 7 8",  # 1 号式神 8 张（8 种各 1 张）
                       "1 1 2 2 3 3 4 4",  # 2 号式神 8 张（4 种各 2 张）
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])                # 编辑循环：回车完成
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert len(decks) == 1 and decks[0]["standard"]
    ids, cards = deckstore.entry_deck(decks[0])
    assert ids == list(F.TEAM) and len(cards) == 32


def test_new_build_shikigami_strict(db, tmp_path, monkeypatch, capsys):
    """新建选式神：数量不符/重复/不存在都会被拒绝并要求重新输入。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",
                       "1 2 3",        # 数量不足
                       "1 1 2 3",      # 重复
                       "1 2 3 99",     # 序号不存在
                       "1 2 3 4",      # 合法
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])
    deckbuilder.run_deckbuilder(db, p)
    out = capsys.readouterr().out
    assert "须恰好输入 4 个序号" in out
    assert "式神不能重复" in out
    assert "序号不存在" in out
    assert deckstore.load_decks(db, p)[0]["standard"]


def test_new_build_cards_strict(db, tmp_path, monkeypatch, capsys):
    """新建选牌：数量不符/序号不存在被拒并重问；同种卡超 2 张不强制——
    仅一次性提示标准规则，卡组仍保存但不标记为标准。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",
                       "1 2 3 4",
                       "1 2 3",              # 数量不足
                       "1 2 3 4 5 6 7 99",   # 序号不存在
                       "1 1 1 2 3 4 5 6",    # 同种卡 3 张 → 接受（仅提示）
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])
    deckbuilder.run_deckbuilder(db, p)
    out = capsys.readouterr().out
    assert out.count("须恰好输入 8 个序号") == 1
    assert "序号不存在" in out
    assert "同名卡全卡组限 2" in out
    assert "不满足标准规则" in out
    decks = deckstore.load_decks(db, p)
    assert len(decks) == 1 and not decks[0]["standard"]  # 超限卡组可保存、非标准


def test_buildable_cards_reinforce_listed_under_both_owners(gdb):
    """协战牌同时列入两位所属式神的可选卡牌（风之乐章 = 妖琴师 & 一目连）。"""
    assert any(c.id == 10012421 for c in deckbuilder.buildable_cards(gdb, 100124))
    assert any(c.id == 10012421 for c in deckbuilder.buildable_cards(gdb, 100125))


def test_deckbuilder_rename(db, tmp_path, monkeypatch):
    """槽位重命名：r <序号> <新名称>。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    feed(monkeypatch, ["r 1 新名字"])
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "新名字" and decks[0]["standard"]


def test_deckbuilder_bad_code_not_saved(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "x", "garbage-code"])
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(db, p) == []


# ---------- 增量编辑 ----------

def test_edit_single_shikigami_cards(db, tmp_path, monkeypatch):
    """编辑现有卡组：只改 1 号式神的卡牌（改为 8 种各 1 张），其余不动。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1 → 沿用名 → 交互式编辑
                       "1",               # 编辑 1 号式神卡牌
                       "1 2 3 4 5 6 7 8",  # 严格选满 8 张（8 种各 1 张）
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert ids == list(F.TEAM)
    own = sorted(c for c in cards if c // 100 == 100101)
    assert own == [10010100 + n for n in range(1, 9)]
    # 其余式神仍是 4 种 ×2
    assert sorted(c for c in cards if c // 100 == 100102) == F.deck_of(100102)


def test_edit_change_shikigami_clears_cards(db, tmp_path, monkeypatch):
    """更换式神：清空其已选卡牌并立即重新选牌；其余式神不动。"""
    db.shikigami[100105] = F.shiki(100105)
    for n in range(1, 9):
        db.cards[10010500 + n] = F.card(10010500 + n, shikigami=100105)
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1
                       "h 1",            # 更换 1 号式神
                       "1",               # 备选池只有 100105
                       "1 2 3 4 5 6 7 8",  # 新式神严格选满 8 张（8 种各 1 张）
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert 100105 in ids and 100101 not in ids
    assert sorted(c for c in cards if c // 100 == 100105) == \
        [10010500 + n for n in range(1, 9)]


def test_edit_cards_strict_input(db, tmp_path, monkeypatch, capsys):
    """编辑单式神卡牌：与新建一致的严格输入——非恰好 8 个序号时重问，直到合法。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",
                       "1",
                       "1 2 3",            # 不足 8 个 → 重问
                       "1 2 3 4 5 6 7 8",  # 8 种各 1 张
                       ""])
    deckbuilder.run_deckbuilder(db, p)
    assert "须恰好输入 8 个序号" in capsys.readouterr().out
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert sorted(c for c in cards if c // 100 == 100101) == \
        [10010100 + n for n in range(1, 9)]


def test_available_shikigami_excludes_wip(gdb):
    """构筑可选池：可构筑卡不足 8 种的 WIP 式神（姑获鸟 0 卡/青行灯 1 卡）不可选。"""
    ids = [d.id for d in deckbuilder.available_shikigami(gdb)]
    assert 100106 not in ids                 # 姑获鸟（卡牌暂未加入）
    assert 100112 not in ids                 # 青行灯（仅明灯 1 张）
    assert 100105 in ids and 100116 in ids   # 凤凰火/山童（8 卡齐）可选
