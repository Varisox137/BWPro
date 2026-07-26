"""组卡规则校验测试：4 式神、派系 ≤2（不计无相）、同源互斥、中立/衍生/召唤物禁入、8 种 ×2。"""
from db.deck import validate_deck
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
    assert any("超过限" in e for e in errors)


def test_reinforce_deck_rules(db):
    """协战牌：所属式神任一出战即可编入（占其 8 张名额）；同名仍限 2；均未出战则不可编。"""
    base = F.deck_of(*F.TEAM)
    # 换入 2 张协战牌（替换 100101 的两张牌，保持恰好 8 张）
    db.cards[10010121] = F.card(10010121, card_type="reinforce", shikigami2=100102)
    deck = [c for c in base if c != 10010104] + [10010121] * 2
    assert validate_deck(db, F.TEAM, deck) == []
    errors = validate_deck(db, F.TEAM, deck + [10010121])
    assert any("协战牌同名仍限" in e for e in errors)
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
    """对局模式参数：DeckRules 可放宽/收紧各限制（为将来新模式预留）。"""
    from db.deck import DeckRules
    deck = F.deck_of(*F.TEAM)
    # 每名式神各去掉一张（恰好 7 张/人）
    short = deck.copy()
    for sid in F.TEAM:
        short.remove(sid * 100 + 4)
    # 默认规则下 7 张不合法；cards_per_shikigami=7 的模式下合法
    errors = validate_deck(db, F.TEAM, short)
    assert errors
    assert validate_deck(db, F.TEAM, short,
                         DeckRules(cards_per_shikigami=7)) == []
    # 同名限 3 的模式
    errors = validate_deck(db, F.TEAM, [10010101] * 3)
    assert any("超过限" in e for e in errors)
    errors = validate_deck(db, F.TEAM, [10010101] * 3,
                           DeckRules(max_copies_per_name=3))
    assert not any("超过限" in e for e in errors)


def test_card_of_benched_shikigami(db):
    db.shikigami[100105] = F.shiki(100105)
    db.cards[10010501] = F.card(10010501, shikigami=100105)
    errors = validate_deck(db, F.TEAM, F.deck_of(*F.TEAM) + [10010501])
    assert any("未出战" in e for e in errors)
