"""调试指令测试。"""
import pytest

from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.conftest import give


def test_debug_give_card_to_hand(db, make_game):
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "count": 2}})
    assert len(a.hand) == before + 2
    assert all(c.id == 10010101 for c in a.hand[-2:])


def test_debug_give_card_to_graveyard(db, make_game):
    g = make_game()
    a = g.state.players[0]
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "zone": "graveyard"}})
    assert a.graveyard[-1].id == 10010101


def test_debug_set_stat_shikigami(db, make_game):
    g = make_game()
    s = g.state.players[0].shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "health", "value": 1}})
    assert s.health == 1
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "level", "value": 3}})
    assert s.level == 3


def test_debug_set_stat_player(db, make_game):
    g = make_game()
    a = g.state.players[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0}, "key": "orb", "value": 9}})
    assert a.orb == 9


def test_debug_set_stat_bool(db, make_game):
    g = make_game()
    s = g.state.players[0].shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "defeated", "value": True}})
    assert s.defeated is True


def test_debug_play_card_bypass_cost_and_level(db, make_game):
    """debug_play_card 跳过费用、等级、目标合法性检查。"""
    cid = 10010152
    db.cards[cid] = F.card(cid, steps=[F.dmg(5)], target=F.T(kind="choose", pool="enemy_shikigami"), token=True)
    g = make_game()
    a = g.state.players[0]
    a.orb = 0
    c = give(g, 0, cid)
    # 正常打出会因鬼火不足失败
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    # 调试指令强制打出
    g.apply({"op": "debug_play_card", "args": {"player": 0, "uid": c.uid, "target": {"player": 1, "shikigami": 0}}})
    assert g.state.players[1].shikigami[0].defeated is True  # 5 点伤害超过 4 血
    assert g.state.players[1].shikigami[0].health == 0       # 气绝后 health 被置 0
    assert c in a.graveyard


def test_debug_assault_bypass_checks(db, make_game):
    g = make_game()
    a = g.state.players[0]
    a.orb = 0
    a.assaults_left = 0
    # 正常出击因 0 火/0 次数失败
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    # 调试强制出击打脸
    g.apply({"op": "debug_assault", "args": {"player": 0, "index": 0}})
    assert g.state.players[1].shield == 2  # 5 - 3


def test_debug_draw(db, make_game):
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    deck_before = len(a.deck)
    g.apply({"op": "debug_draw", "args": {"player": 0, "count": 2}})
    assert len(a.hand) == before + 2
    assert len(a.deck) == deck_before - 2


def test_debug_set_turn(db, make_game):
    g = make_game()
    g.apply({"op": "debug_set_turn", "args": {"active": 1, "turn": 10}})
    assert g.state.active == 1
    assert g.state.turn == 10


def test_debug_unknown_command(db, make_game):
    g = make_game()
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_foobar", "args": {}})


def test_debug_disabled(db, make_game):
    g = make_game()
    g.state.config.enable_debug_commands = False
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_draw", "args": {"player": 0, "count": 1}})
