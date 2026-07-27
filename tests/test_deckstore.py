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
                       "", "", "", ""])    # 张数各回车（每种 1 张）
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
