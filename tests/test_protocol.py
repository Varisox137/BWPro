"""联机协议（server/protocol.py）消息构造/解析测试。"""
import json

import pytest

from server import protocol


def test_parse_client_messages():
    assert protocol.parse_client_message('{"type": "create", "name": "甲"}')["type"] == "create"
    msg = protocol.parse_client_message(json.dumps(
        {"type": "cmd", "cmd": {"op": "end_turn"}}))
    assert msg["cmd"]["op"] == "end_turn"
    assert protocol.parse_client_message('{"type": "pong"}')["type"] == "pong"


def test_parse_rejects_bad_messages():
    for raw in ("not json", "[1,2]", '{"type": "hack"}',
                '{"type": "cmd"}', '{"cmd": {}}'):
        with pytest.raises(ValueError):
            protocol.parse_client_message(raw)


def test_server_message_builders():
    j = protocol.joined("ABC123", "tok", 0, debug=True)
    assert (j["type"], j["room_id"], j["token"], j["seat"], j["debug"]) == \
        ("joined", "ABC123", "tok", 0, True)
    s = protocol.start(1, "乙", False)
    assert (s["player_index"], s["opponent"], s["you_first"]) == (1, "乙", False)
    st = protocol.state({"turn": 3}, ["x", "y"])
    assert st["payload"]["turn"] == 3 and st["log"] == ["x", "y"]
    assert "timer" not in st  # 缺省不带计时器字段（旧客户端兼容）
    st2 = protocol.state({"turn": 3}, [], timer={"kind": "turn", "deadline": 1.0})
    assert st2["timer"] == {"kind": "turn", "deadline": 1.0}
    assert protocol.error("r") == {"type": "error", "reason": "r"}
    assert protocol.notice("t") == {"type": "notice", "text": "t"}
    assert protocol.game_over(0, "player_defeated")["winner"] == 0
