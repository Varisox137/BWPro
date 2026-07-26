"""卡组码测试：编码/解码往返、结构校验、组卡规则校验（db/deckcode.py）。"""
import pytest

from db import deckcode
from db.test_data import TEST_IDS, make_test_db, make_test_deck


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
