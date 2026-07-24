"""维护者给出的测试数据（db/test_data.py）可用性验证。

确保战斗牌、形态牌、觉醒牌、cost=0、瞬发等简化效果在本地热座中可正常结算。
"""
import pytest

from core.model import CardInstance, GameConfig
from core.setup import new_game
from db.test_data import TEST_IDS, make_test_db, make_test_deck


def _give(game, player_index: int, defn_id: int) -> CardInstance:
    """直接发一张牌到玩家手牌，并分配连续的 hand_seq。"""
    st = game.state
    card = CardInstance(uid=st.next_uid, id=defn_id)
    st.next_uid += 1
    p = st.players[player_index]
    p.hand.append(card)
    max_seq = max((c.hand_seq for c in p.hand if c is not card), default=0)
    card.hand_seq = max_seq + 1
    return card


def _make_game(seed: int = 42, **kw):
    db = make_test_db()
    deck = make_test_deck()
    config = GameConfig(auto_skip_upgrade=kw.pop("auto_skip_upgrade", True))
    return new_game(
        db,
        ("A", list(TEST_IDS), list(deck)),
        ("B", list(TEST_IDS), list(deck)),
        seed=seed,
        first=0,
        shuffle_team=False,
        mulligan=False,
        config=config,
        **kw,
    )


def test_combat_card_buffs_power_and_shield():
    """战斗牌：按完整战斗事件流程结算；战力战斗后清除，护甲保留。"""
    g = _make_game()
    a, b = g.state.players
    # 文射：10010102，1 费，-2 力量 / +2 护甲
    card = _give(g, 0, 10010102)
    a.orb = 1
    s = a.shikigami[0]
    g.apply({"op": "play_card", "uid": card.uid})
    assert a.combat_index == 0                      # 使用战斗牌会移入战斗区
    assert s.combat_power == 0                      # 战力战斗后清除
    assert s.shield == 2                            # 战斗牌给予的护甲保留
    assert card in a.graveyard
    assert b.shield == 4                            # 3 - 2 = 1 战力打脸，后手 5 甲剩 4
    assert b.health == 30


def test_form_card_attaches_with_base_stats():
    """形态牌：结附后按卡牌数值覆盖基础身材。"""
    g = _make_game()
    a = g.state.players[0]
    # 残心：10010103，1 费，形态 3/5
    card = _give(g, 0, 10010103)
    a.orb = 1
    s = a.shikigami[0]
    g.apply({"op": "play_card", "uid": card.uid})
    assert s.base_power == 3
    assert s.base_health == 5
    assert s.health == 5
    assert s.form is card


def test_awaken_card_perm_buff():
    """觉醒牌：给使用者永久力量与生命修正，并标记 awaken tag。"""
    g = _make_game()
    a = g.state.players[0]
    # 觉醒·白狼：10010107，3 费，+2 永久力量 / +2 永久生命上限
    a.shikigami[0].level = 3
    card = _give(g, 0, 10010107)
    a.orb = 3
    s = a.shikigami[0]
    g.apply({"op": "play_card", "uid": card.uid})
    assert s.perm_power == 2
    assert s.perm_health == 2
    assert s.health == s.max_health  # 当前生命同步增加
    assert g.db.cards[card.id].subtype == "awaken"


def test_zero_cost_card_playable_at_zero_orb():
    """不消耗鬼火：cost=0 的卡牌可在 0 鬼火时使用。"""
    g = _make_game()
    a = g.state.players[0]
    # 一闪：10012304，0 费战斗牌，需要妖刀姬 2 级
    a.shikigami[2].level = 2  # 妖刀姬
    card = _give(g, 0, 10012304)
    a.orb = 0
    g.apply({"op": "play_card", "uid": card.uid})
    assert a.orb == 0
    assert card in a.graveyard


def test_fast_keyword_first_free():
    """瞬发：每半回合第一张瞬发卡免费。"""
    g = _make_game()
    a = g.state.players[0]
    # 起弓：10010101，1 费法术瞬发
    card = _give(g, 0, 10010101)
    a.orb = 1
    g.apply({"op": "play_card", "uid": card.uid})
    assert a.orb == 1  # 第一张免费，鬼火不变
    assert a.fast_used is True


def test_form_with_fast_keyword():
    """带瞬发的形态牌：第一张免费结附。"""
    g = _make_game()
    a = g.state.players[0]
    # 风符·瞬：10012506，1 费形态 6/9 瞬发
    card = _give(g, 0, 10012506)
    a.orb = 1
    s = a.shikigami[3]  # 一目连
    s.level = 2
    g.apply({"op": "play_card", "uid": card.uid})
    assert a.orb == 1  # 第一张瞬发免费
    assert s.base_power == 6
    assert s.base_health == 9
