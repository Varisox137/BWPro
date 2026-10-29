import json
import logging

import pytest

from core.engine import IllegalAction
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
    assert entries[0]["kind"] == "event"
    assert entries[0]["summary"] == "on_game_start"
    assert entries[0]["seq"] == 1

    entries.clear()
    cmd = {"op": "upgrade", "index": 1}
    game.apply(cmd)
    assert entries[0]["kind"] == "cmd"
    assert entries[0]["owner"] == 0
    assert json.loads(entries[0]["message"]) == cmd

    entries.clear()
    expected_seq = game.state.emit_seq + 1
    game.emit("on_turn_start", player=0)
    event = entries[-1]
    assert event["kind"] == "event"
    assert event["owner"] == 0
    assert event["seq"] == expected_seq
    assert event["summary"] == "on_turn_start"
    assert json.loads(event["message"]) == {
        "name": "on_turn_start", "payload": {"player": 0}}

    entries.clear()
    ctx = ExecContext(controller=0, source=Ref(player=0, shikigami=0),
                      event={"amount": 3})
    game._run_step(F.Step(op="damage", amount={"event": "amount"},
                          target=F.T(kind="all", pool="enemy_player")), ctx)
    op = entries[0]
    assert op["kind"] == "op"
    assert op["owner"] == 0
    op_message = json.loads(op["message"])
    assert op_message["params"]["amount"] == 3
    assert op_message["refs"] == ["player=1 shikigami=None"]

    entries.clear()
    game.state.winner = 0
    expected_seq = game.state.emit_seq
    game.emit("on_turn_start", player=1)
    terminal_event = entries[-1]
    assert terminal_event["kind"] == "event"
    assert terminal_event["summary"] == "on_turn_start"
    assert "seq" not in terminal_event
    assert game.state.emit_seq == expected_seq


@pytest.mark.parametrize(("cmd", "terminal"), [
    ({"op": "unknown", "payload": {"uid": 7}}, False),
    ({"op": "end_turn", "reason": "wrong_phase"}, False),
    ({"op": "end_turn", "reason": "terminal"}, True),
], ids=["unknown", "wrong_phase", "terminal"])
def test_command_trace_precedes_validation(make_game, cmd, terminal):
    entries = []
    game = make_game(auto_skip_upgrade=False, trace_sink=entries.append)
    if terminal:
        game.state.winner = 0
    entries.clear()
    with pytest.raises(IllegalAction):
        game.apply(cmd)
    assert len(entries) == 1
    assert entries[0]["kind"] == "cmd"
    assert entries[0]["owner"] == 0
    assert json.loads(entries[0]["message"]) == cmd
