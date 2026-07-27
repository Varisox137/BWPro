"""本地卡组存储（db/deckstore.py）与卡组构筑/战前选卡流程（client/deckbuilder.py）测试。"""
import pytest

from client import deckbuilder
from db import deckcode, deckstore
from tests import factories as F


def mk_code(db, sids=None) -> str:
    sids = list(sids or F.TEAM)
    return deckcode.encode_deck(
        deckcode.group_deck(db, sids, F.deck_of(*sids)))


def feed(monkeypatch, lines):
    it = iter(lines)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# ---------- deckstore 读写 ----------

def test_store_roundtrip(tmp_path):
    p = tmp_path / "decks.json"
    decks = [{"name": "快攻", "code": "abc"}, {"name": "控制", "code": "def"}]
    deckstore.save_decks(decks, p)
    assert deckstore.load_decks(p) == decks


def test_store_missing_and_corrupted(tmp_path, capsys):
    p = tmp_path / "decks.json"
    assert deckstore.load_decks(p) == []          # 不存在
    p.write_text("not json", encoding="utf-8")
    assert deckstore.load_decks(p) == []          # 损坏 → 警告 + 空
    assert "警告" in capsys.readouterr().out
    p.write_text('{"decks": [{"name": 1}, {"name": "x", "code": "y"}]}',
                 encoding="utf-8")
    assert deckstore.load_decks(p) == [{"name": "x", "code": "y"}]  # 过滤非法条目


# ---------- 战前选卡 ----------

def test_choose_deck_from_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    code = mk_code(db)
    deckstore.save_decks([{"name": "我的卡组", "code": code}], p)
    feed(monkeypatch, ["1"])
    ids, cards, got = deckbuilder.choose_deck(db, "玩家A", p)
    assert got == code and ids == list(F.TEAM) and cards == F.deck_of(*F.TEAM)


def test_choose_deck_invalid_slot_falls_back(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks([{"name": "x", "code": mk_code(db)}], p)
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
    assert deckstore.load_decks(p) == [{"name": "快攻队", "code": code}]


def test_deckbuilder_edit_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    old = mk_code(db)
    deckstore.save_decks([{"name": "旧名", "code": old}], p)
    new = mk_code(db)  # 同数据不同码也无妨：校验通过即覆盖
    feed(monkeypatch, ["1", "新名", new])
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(p) == [{"name": "新名", "code": new}]


def test_deckbuilder_edit_keep_name(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    old = mk_code(db)
    deckstore.save_decks([{"name": "旧名", "code": old}], p)
    feed(monkeypatch, ["1", "", old])  # 名称回车 = 沿用
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(p) == [{"name": "旧名", "code": old}]


def test_deckbuilder_new_interactive(db, tmp_path, monkeypatch):
    """交互式构筑：4 名式神各选全部卡牌、每种 1 张（恰好 8 张/人）→ 自动保存。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",        # 新建 → 名称回车（自动命名）→ 交互式
                       "1 2 3 4",          # 4 名式神
                       "", "", "", "",     # 各选全部种类
                       "", "", "", "",     # 张数各回车（每种 1 张）
                       ""])                # 编辑循环：回车完成
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(p)
    assert len(decks) == 1
    ids, cards = deckcode.deck_from_code(db, decks[0]["code"])
    assert ids == list(F.TEAM) and len(cards) == 32


def test_deckbuilder_bad_code_not_saved(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "x", "garbage-code"])
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(p) == []


# ---------- 增量编辑 ----------

def test_edit_single_shikigami_cards(db, tmp_path, monkeypatch):
    """编辑现有卡组：只改 1 号式神的卡牌（改为 8 种各 1 张），其余不动。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks([{"name": "旧", "code": mk_code(db)}], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1 → 沿用名 → 交互式编辑
                       "1",               # 编辑 1 号式神卡牌
                       "1 2 3 4 5 6 7 8",  # 改选全部 8 种
                       "1=1 2=1 3=1 4=1",  # 原 4 种由 ×2 调为 ×1（5-8 默认 1 张）
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckcode.deck_from_code(db, deckstore.load_decks(p)[0]["code"])
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
    deckstore.save_decks([{"name": "旧", "code": mk_code(db)}], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1
                       "换 1",            # 更换 1 号式神
                       "1",               # 备选池只有 100105
                       "1 2 3 4 5 6 7 8",  # 新式神选全部 8 种
                       "",                # 每种 1 张
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckcode.deck_from_code(db, deckstore.load_decks(p)[0]["code"])
    assert 100105 in ids and 100101 not in ids
    assert sorted(c for c in cards if c // 100 == 100105) == \
        [10010500 + n for n in range(1, 9)]


def test_edit_invalid_keeps_editing(db, tmp_path, monkeypatch, capsys):
    """完成时校验不通过：打印错误并留在编辑循环，修正后可保存。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks([{"name": "旧", "code": mk_code(db)}], p)
    feed(monkeypatch, ["1", "", "",
                       "1", "1 2 3", "",  # 1 号式神只留 3 种各 1 张（3 张，不合法）
                       "",                # 完成 → 校验失败，继续编辑
                       "1", "1 2 3 4", "1=2 2=2 3=2 4=2",  # 修回 4 种 ×2
                       ""])               # 完成 → 通过
    deckbuilder.run_deckbuilder(db, p)
    assert "卡组暂不合法" in capsys.readouterr().out
    ids, cards = deckcode.deck_from_code(db, deckstore.load_decks(p)[0]["code"])
    assert sorted(c for c in cards if c // 100 == 100101) == F.deck_of(100101)
