import logging

from core.model import ExecContext, Ref
from tests import factories as F


def test_command_event_and_actual_op_trace(make_game, caplog):
    game = make_game(auto_skip_upgrade=False)
    with caplog.at_level(logging.INFO, logger="bwpro.battle"):
        game.apply({"op": "upgrade", "index": 1})
        game.emit("on_turn_start", player=0)
        ctx = ExecContext(controller=0, source=Ref(player=0, shikigami=0))
        game._run_step(F.Step(op="damage", amount=1,
                              target=F.T(kind="all", pool="enemy_player")), ctx)
        game._run_step(F.Step(op="damage", amount=1, condition={"orb_ge": 99},
                              target=F.T(kind="all", pool="enemy_player")), ctx)
    text = caplog.text
    assert '"op": "upgrade"' in text
    assert "on_turn_start" in text and "player" in text
    assert '"op": "damage"' in text and '"amount": 1' in text
    assert text.count('"op": "damage"') == 1


def test_trace_sink_receives_structured_entries(make_game):
    entries = []
    game = make_game(auto_skip_upgrade=False, trace_sink=entries.append)
    entries.clear()
    game.apply({"op": "upgrade", "index": 1})
    assert entries[0]["kind"] == "cmd"
    assert entries[0]["owner"] == 0
    assert "upgrade" in entries[0]["message"]
