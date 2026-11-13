"""server 层测试：联机协议消息构造/解析（原 test_protocol.py）
+ 服务端入口限流与输入上限（原 test_server_main.py）
+ 联机房间单元测试：假 WebSocket + asyncio（原 test_room.py）
+ 联机端到端：线程内 uvicorn + 两个 websockets.sync 客户端全流程（原 test_net.py，
端口不可用时跳过）。
"""
import asyncio
import json
import logging
import random
import threading
import time

import pytest

from core.logging_config import configure_logging, restore_output
from server import protocol
from server.log_admin import LogAdminService
from server.main import RateLimiter, _text, create_app
from server.manager import RoomManager
from server.room import Room, sanitize_trace

from tests import factories as F


# ==========================================================================
# 联机协议（原 test_protocol.py，server/protocol.py）
# ==========================================================================

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
    s = protocol.start(1, "乙", False, reconnect_code="abcd1234")
    assert (s["player_index"], s["opponent"], s["you_first"]) == (1, "乙", False)
    assert s["reconnect_code"] == "abcd1234"
    st = protocol.state({"turn": 3}, ["x", "y"])
    assert st["payload"]["turn"] == 3 and st["log"] == ["x", "y"]
    assert "timer" not in st  # 缺省不带计时器字段（旧客户端兼容）
    assert "trace" not in st
    assert "trace" not in protocol.state({"turn": 3}, [], trace=[])
    st2 = protocol.state({"turn": 3}, [], timer={"kind": "turn", "deadline": 1.0})
    assert st2["timer"] == {"kind": "turn", "deadline": 1.0}
    st3 = protocol.state({"turn": 3}, [], trace=[{"kind": "event"}])
    assert st3["trace"] == [{"kind": "event"}]
    assert protocol.error("r") == {"type": "error", "reason": "r"}
    assert protocol.notice("t") == {"type": "notice", "text": "t"}
    assert protocol.game_over(0, "player_defeated")["winner"] == 0
    assert protocol.dissolved("r") == {"type": "dissolved", "reason": "r"}
    assert "opponent_cardback" not in st
    assert protocol.state({"turn": 3}, [], opponent_cardback="三途花境")[
        "opponent_cardback"] == "三途花境"


# ==========================================================================
# 服务端入口限流与输入上限（原 test_server_main.py，server/main.py）
# ==========================================================================

def test_rate_limiter():
    rl = RateLimiter(3)
    assert all(rl.allow() for _ in range(3))
    assert not rl.allow()
    rl.window -= 1.1  # 模拟进入下一秒
    assert rl.allow()


def test_text_field_caps():
    assert _text({"name": "甲"}, "name", 32) == "甲"
    assert _text({}, "name", 32) is None
    with pytest.raises(ValueError):
        _text({"name": "x" * 33}, "name", 32)
    with pytest.raises(ValueError):
        _text({"name": 123}, "name", 32)


# ==========================================================================
# 联机房间（原 test_room.py，server/room.py + server/manager.py）
# ==========================================================================

class FakeWS:
    """收集 send_text 内容的假 WebSocket。"""

    def __init__(self):
        self.messages: list[dict] = []
        self.closed = False

    async def send_text(self, text: str):
        self.messages.append(json.loads(text))

    async def close(self, code: int = 1000):
        self.closed = True

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


def run(coro):
    return asyncio.run(coro)


def _deck_code(db) -> str:
    """测试用合法卡组码（TEAM 全员满编）。"""
    from db import deckcode
    return deckcode.encode_deck(
        deckcode.group_deck(db, list(F.TEAM), F.deck_of(*F.TEAM)))


def mk_room(db, **kw) -> Room:
    kw.setdefault("rng", random.Random(1))
    return Room("TEST01", db, **kw)


async def _started_room(db, **kw):
    """两名玩家就位、双方准备并经开始倒计时后开局的 (room, ws0, ws1)。"""
    kw.setdefault("starting_timeout", 0.01)
    room = mk_room(db, **kw)
    ws0, ws1 = FakeWS(), FakeWS()
    await room.join(0, "甲", ws0, _deck_code(db))
    await room.join(1, "乙", ws1, _deck_code(db))
    await room.on_seat_filled()
    await room.lobby_ready(0)
    await room.lobby_ready(1)
    await asyncio.sleep(0.05)  # 开始倒计时（测试 0.01s）结束后开局
    assert room.game is not None
    return room, ws0, ws1


def test_trace_sanitized_for_viewer():
    private = {"kind": "op", "message": "私密伤害牌", "owner": 0}
    public = {"kind": "event", "message": "完整私有载荷",
              "summary": "on_damage", "owner": None, "seq": 8}
    assert sanitize_trace(private, 1) is None
    assert sanitize_trace(private, 0)["message"] == "私密伤害牌"
    visible = sanitize_trace(public, 1)
    assert visible["message"] == "on_damage" and visible["seq"] == 8


def test_room_broadcasts_server_trace(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        viewer = room.seat_to_player[0]
        room.game._trace("op", "服务端原子动作", owner=viewer)
        room.game._trace("event", "完整私有载荷", summary="on_damage")
        await room.broadcast_state()
        msg = [m for m in ws0.messages if m["type"] == "state"][-1]
        peer_msg = [m for m in ws1.messages if m["type"] == "state"][-1]
        assert [e["message"] for e in msg["trace"]] == ["服务端原子动作", "on_damage"]
        assert [e["message"] for e in peer_msg["trace"]] == ["on_damage"]
        await room.broadcast_state()
        msg = [m for m in ws0.messages if m["type"] == "state"][-1]
        assert "trace" not in msg
        await room.resync(room.conns[0])
        msg = [m for m in ws0.messages if m["type"] == "state"][-1]
        assert "trace" not in msg
    run(go())


def test_rejected_command_does_not_accumulate_trace_or_log_padding(db, caplog):
    room, _ws0, _ws1 = run(_started_room(db))
    with caplog.at_level(logging.INFO, logger="bwpro.battle"):
        for _ in range(100):
            run(room.handle_cmd(0, {"op": "unknown", "padding": "x" * 10000}))
    room._cancel_timer()
    assert room._trace_pending == []
    assert "x" * 100 not in caplog.text


@pytest.mark.parametrize("error", [ValueError("bad data"), RuntimeError("engine failure")])
def test_failed_apply_rolls_back_only_new_trace(db, monkeypatch, error):
    room, _ws0, _ws1 = run(_started_room(db))
    previous = {"kind": "event", "message": "此前正常动画", "owner": None}
    room._trace_pending.append(previous)

    def fail_after_trace(_cmd):
        room.game._trace("op", "失败前产生的部分动画")
        raise error

    monkeypatch.setattr(room.game, "apply", fail_after_trace)
    run(room.handle_cmd(0, {"op": "ready"}))
    room._cancel_timer()
    assert room._trace_pending == [previous]


def test_accepted_command_trace_filters_fields_and_preserves_animation_trace(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        seat = 0
        player = room.seat_to_player[seat]
        ws = ws0
        before = len(ws.messages)
        await room.handle_cmd(seat, {
            "op": "ready", "padding": "x" * 10000, "unexpected": {"secret": "y"},
        })
        room.game._trace("op", "正常后续动画", owner=player)
        await room.broadcast_state()
        messages = [m for m in ws.messages[before:] if m["type"] == "state"]
        traces = [entry for msg in messages for entry in msg.get("trace", [])]
        command = next((entry for entry in traces if entry["kind"] == "cmd"), None)
        assert command is not None, ws.messages[before:]
        payload = json.loads(command["message"])
        assert payload == {"op": "ready", "player": player}
        assert all(len(entry["message"]) <= 4096 for entry in traces)
        assert any(entry["kind"] != "cmd" for entry in traces)
        assert "x" * 100 not in json.dumps(traces)
        room._cancel_timer()
    run(go())


def test_trace_message_bounded_and_normal_pending_never_capped(db):
    room, _ws0, _ws1 = run(_started_room(db))
    room.game._trace("event", "x" * 5000)
    assert len(room._trace_pending[-1]["message"]) == 4096
    for index in range(1500):
        room.game._trace("event", f"event-{index}")
    room._cancel_timer()
    assert len(room._trace_pending) == 1501
    assert room._trace_pending[-1]["message"] == "event-1499"


def test_rejection_log_truncates_attacker_controlled_fields(db, caplog):
    room, _ws0, _ws1 = run(_started_room(db))
    attack = "x" * (1024 * 1024)
    with caplog.at_level(logging.INFO, logger="bwpro.room"):
        room._log_rejection(0, {"op": attack, "padding": "y" * 10000},
                            "未知指令: " + attack)
    room._cancel_timer()
    records = [record for record in caplog.records if record.name == "bwpro.room"]
    assert len(records) == 1
    assert attack not in caplog.text
    assert "x" * 65 not in caplog.text
    assert "y" * 100 not in caplog.text
    assert len(records[0].getMessage()) <= 256


# ---------- 房间管理 ----------

def test_room_id_unique(db):
    mgr = RoomManager(db)
    rooms = [mgr.create() for _ in range(50)]
    assert len({r.id for r in rooms}) == 50
    assert all(len(r.id) == 6 for r in rooms)


def test_join_full_room_rejected(db):
    async def go():
        room, _, _ = await _started_room(db)
        with pytest.raises(ValueError, match="对局已开始"):
            await room.join(0, "丙", FakeWS(), None)
    run(go())


def test_invalid_deck_code_rejected(db):
    async def go():
        room = mk_room(db)
        with pytest.raises(ValueError, match="卡组"):
            await room.join(0, "甲", FakeWS(), "not-a-code")
        assert room.conns[0] is None  # 校验失败不占座，房间保留
        with pytest.raises(ValueError, match="卡组"):
            await room.join(0, "甲", FakeWS(), None)  # 无默认卡组：必须提供卡组码
        assert room.conns[0] is None
    run(go())


# ---------- 准备阶段（lobby）与自建房码 ----------

def test_custom_room_id(db):
    """自建房间代码：6 位大小写字母/数字；格式非法或冲突均拒绝。"""
    mgr = RoomManager(db)
    mgr.create(room_id="Ab12cd")
    assert mgr.get("Ab12cd") is not None
    with pytest.raises(ValueError, match="已被占用"):
        mgr.create(room_id="Ab12cd")
    for bad in ("abc", "abcdefg", "ab cd!", "中文房间码"):
        with pytest.raises(ValueError, match="6 位"):
            mgr.create(room_id=bad)


def test_lobby_manual_ready_and_leave(db):
    """准备阶段状态机：双方都位后不计时（IDLE）；一方准备对另一方计 15s
    （COUNTDOWN）；双方准备进入 3s 开始倒计时（STARTING）后开局；
    开局后不允许 lobby 离开（断线走重连通道）。"""
    async def go():
        room = mk_room(db, starting_timeout=0.01)
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        assert room.game is None
        await room.on_seat_filled()
        lobby = [m for m in ws0.messages if m["type"] == "lobby"][-1]
        assert lobby["ready"] == [] and lobby["deadline"] is None  # IDLE：不计时
        assert room._lobby_timer is None
        await room.lobby_ready(0)
        assert room.game is None  # 仅一方准备不开局
        lobby = [m for m in ws1.messages if m["type"] == "lobby"][-1]
        assert lobby["ready"] == ["甲"]
        assert lobby["deadline"] > time.time()  # 对未准备方（乙）计自动准备
        await room.lobby_ready(1)
        assert room.game is None and "starting" in ws0.types()  # 开始倒计时，尚未开局
        await asyncio.sleep(0.05)
        assert room.game is not None
        assert not await room.lobby_leave(0)  # 已开局：不可从 lobby 离开
    run(go())


def test_lobby_unready_cancels_countdown(db):
    """取消准备：COUNTDOWN 中已准备方取消 → 回 IDLE（计时取消、名单清空）；
    STARTING 中不可取消。"""
    async def go():
        room = mk_room(db, starting_timeout=0.01)
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        await room.on_seat_filled()
        await room.lobby_ready(0)
        assert room._lobby_phase == "countdown"
        await room.lobby_ready(0)  # 取消准备
        assert room._lobby_phase == "idle" and not room.ready_seats
        assert room._lobby_timer is None
        lobby = [m for m in ws1.messages if m["type"] == "lobby"][-1]
        assert lobby["ready"] == [] and lobby["deadline"] is None
        await room.lobby_ready(0)
        await room.lobby_ready(1)  # 进入 STARTING
        assert room._lobby_phase == "starting"
        await room.lobby_ready(0)  # 开始倒计时中不可取消
        assert room._lobby_phase == "starting" and room.ready_seats == {0, 1}
        assert any(m["type"] == "error" for m in ws0.messages)
        await asyncio.sleep(0.05)
        assert room.game is not None
    run(go())


def test_lobby_auto_ready(db):
    """无人准备不计时；一方准备后另一方超时（15s，测试 0.05s）自动准备，
    进入开始倒计时后开局（不直接开局）。"""
    async def go():
        room = mk_room(db, ready_timeout=0.05, starting_timeout=0.01)
        ws0, _ = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", FakeWS(), _deck_code(db))
        await room.on_seat_filled()
        await asyncio.sleep(0.1)
        assert room.game is None and not room.ready_seats  # 无人准备：不计时不开局
        await room.lobby_ready(0)
        await asyncio.sleep(0.15)  # 乙超时自动准备 → 开始倒计时 → 开局
        assert room.ready_seats == {0, 1}
        assert room.game is not None
        assert "start" in ws0.types()
    run(go())


def test_lobby_leave_frees_seat(db):
    """准备阶段离开/断线（含开始倒计时中）：座位释放、对手收到 peer_left、
    不开局，新玩家可再入座。"""
    async def go():
        room = mk_room(db, starting_timeout=0.01)
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        await room.on_seat_filled()
        assert await room.lobby_leave(1)
        assert room.conns[1] is None and room._lobby_timer is None
        assert any(m["type"] == "peer_left" and m["name"] == "乙"
                   for m in ws0.messages)
        await room.join(1, "丙", FakeWS(), _deck_code(db))  # 座位可再入座
        await room.on_seat_filled()
        # 开始倒计时中离开：终止倒计时、不开局
        await room.lobby_ready(0)
        await room.lobby_ready(1)
        assert room._lobby_phase == "starting"
        assert await room.lobby_leave(1)
        assert room._lobby_phase == "idle" and room._lobby_timer is None
        await asyncio.sleep(0.05)
        assert room.game is None
    run(go())


# ---------- 开局与座位映射 ----------

def test_start_maps_seats_to_players(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        assert room.game is not None
        # 双方都收到 start，player_index 与 seat_to_player 一致
        for ws, seat in ((ws0, 0), (ws1, 1)):
            start = next(m for m in ws.messages if m["type"] == "start")
            assert start["player_index"] == room.seat_to_player[seat]
        # players[0] 恒为先手：其名字对应 seat_to_player 映射为 0 的座位
        first_seat = room.seat_to_player.index(0)
        first_name = ("甲", "乙")[first_seat]
        assert room.game.state.players[0].name == first_name
        # 双方各收到一份完整 state
        assert all("state" in ws.types() for ws in (ws0, ws1))
    run(go())


def test_cmd_player_field_rewritten(db):
    """mulligan/ready 的 player 字段由服务端按座位改写，不能冒充对方调度。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        g = room.game
        p0, p1 = g.state.players
        # 座位 1 的玩家试图调度：player 被改写为自己的 players 下标
        seat1_player = room.seat_to_player[1]
        uid = g.state.players[seat1_player].hand[0].uid
        await room.handle_cmd(1, {"op": "mulligan", "uid": uid, "player": 0})
        assert g.state.players[seat1_player].mulligans_left == 2
        # 另一方不受影响
        other = 1 - seat1_player
        assert g.state.players[other].mulligans_left == 3
    run(go())


def test_illegal_cmd_returns_error(db, caplog):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        n = len(ws0.messages)
        n1 = len(ws1.messages)
        with caplog.at_level(logging.INFO, logger="bwpro.room"):
            await room.handle_cmd(0, {"op": "end_turn"})  # 调度阶段不可用
        reply = ws0.messages[-1]
        assert reply["type"] == "error"
        assert reply["reason"] != "还没到你的回合"  # 确保覆盖引擎 IllegalAction 分支
        assert room.id in caplog.text and "座位=0" in caplog.text
        assert "指令=end_turn" in caplog.text
        assert f"被拒绝：{reply['reason']}" in caplog.text
        assert len(ws1.messages) == n1  # 未向另一连接广播
        assert any(m["type"] == "error" for m in ws0.messages[n:])
    run(go())


def test_debug_room_flag(db):
    async def go():
        room, ws0, _ = await _started_room(db, debug=True)
        await room.handle_cmd(0, {"op": "debug_draw", "args": {"player": 0, "count": 1}})
        assert not any(m.get("type") == "error" for m in ws0.messages)
        room2, ws0b, _ = await _started_room(db)
        await room2.handle_cmd(0, {"op": "debug_draw", "args": {"player": 0, "count": 1}})
        assert ws0b.messages[-1]["type"] == "error"
    run(go())


# ---------- 排障日志 ----------

def test_rejected_command_logs_room_context(db, caplog):
    room, _ws0, _ws1 = run(_started_room(db))
    seat = next(s for s in (0, 1)
                if room.seat_to_player[s] != room.game.state.active)
    with caplog.at_level(logging.INFO, logger="bwpro.room"):
        run(room.handle_cmd(seat, {"op": "end_turn"}))
    room._cancel_timer()
    assert room.id in caplog.text
    assert f"座位={seat}" in caplog.text
    assert "end_turn" in caplog.text
    assert "还没到你的回合" in caplog.text


def test_engine_exception_logs_room_context_and_traceback(db, caplog):
    room, _ws0, _ws1 = run(_started_room(db))

    def raise_engine_error(_cmd):
        raise RuntimeError("注入引擎故障")

    room.game.apply = raise_engine_error
    with caplog.at_level(logging.ERROR, logger="bwpro.room"):
        run(room.handle_cmd(0, {"op": "ready"}))
    assert f"房间 {room.id} 引擎异常，对局终止" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert "RuntimeError: 注入引擎故障" in caplog.text


def test_log_admin_token_not_captured(tmp_path, monkeypatch):
    path = configure_logging("test", log_dir=tmp_path)
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    monkeypatch.setattr("server.log_admin.restrict_private_permissions", lambda path: None)
    try:
        service = LogAdminService(tmp_path, path)
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert service.token not in path.read_text(encoding="utf-8")
    finally:
        restore_output()


# ---------- 断线重连 ----------

def test_reconnect_token_is_short_copyable_hex(db):
    import re

    room = mk_room(db)
    conn = run(room.join(0, "甲", FakeWS(), _deck_code(db)))
    assert re.fullmatch(r"[0-9a-f]{8}", conn.token)


def test_reconnect_by_token(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        conn0 = room.conns[0]
        room.disconnect(conn0)
        assert not conn0.connected
        ws_new = FakeWS()
        back = await room.reconnect(conn0.token, ws_new)
        assert back is conn0 and conn0.connected
        await room.broadcast_state()
        assert "state" in ws_new.types()
        assert await room.reconnect("wrong-token", FakeWS()) is None
        # 双方断线 → 房间可遗弃
        room.disconnect(conn0)
        room.disconnect(room.conns[1])
        assert room.abandoned
    run(go())


def test_reconnect_resync_full_log(db):
    """断线期间的日志不被广播游标吞掉：重连后 resync 向重连者全量补发
    state.log（不动广播游标，在线玩家不会收到重复日志）。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        conn0 = room.conns[0]
        room.disconnect(conn0)
        await room.handle_cmd(1, {"op": "ready"})  # 断线期间产生新日志并广播
        ws_new = FakeWS()
        await room.reconnect(conn0.token, ws_new)
        await room.resync(conn0)
        msg = [m for m in ws_new.messages if m["type"] == "state"][-1]
        assert len(msg["log"]) == len(room.game.state.log)  # 全量补发
        await room.broadcast_state()
        assert ws1.messages[-1]["log"] == []  # 游标未动：在线方无重复
    run(go())


# ---------- 计时器 ----------

def test_mulligan_timeout_forces_ready(db):
    """并行调度超时：全阶段共用一个截止时刻，超时统一将所有未完成调度的玩家
    自动 ready（旧行为按玩家轮流计时，一方超时后另一方会重置一整个调度时长）。"""
    async def go():
        room, _, _ = await _started_room(db, mulligan_timeout=0.1)
        g = room.game
        assert g.state.phase == "mulligan"
        assert room.current_timer_key() == ("mulligan",)
        await asyncio.sleep(0.15)
        assert all(p.mulligan_done for p in g.state.players)
        assert g.state.phase != "mulligan"  # 已进入对战
    run(go())


def test_mulligan_shared_deadline_not_reset(db):
    """一方提前完成调度：双方共用的截止时刻不重置、计时 key 不变（客户端状态栏
    倒计时连续，另一方不会获得额外调度时间）。"""
    async def go():
        room, _, ws1 = await _started_room(db, mulligan_timeout=30)
        dl = [m for m in ws1.messages if m["type"] == "state"][-1]["timer"]["deadline"]
        await room.handle_cmd(0, {"op": "ready"})  # seat0 完成调度
        timer = [m for m in ws1.messages if m["type"] == "state"][-1]["timer"]
        assert timer["kind"] == "mulligan" and timer["deadline"] == dl
        assert room.current_timer_key() == ("mulligan",)
        room._cancel_timer()  # 收掉 30s 计时任务，防事件循环退出告警
    run(go())


def test_turn_timeout_random_upgrade_then_end(db):
    """回合超时：升级阶段先随机升级，再立即结束回合（换手）。"""
    async def go():
        room, _, _ = await _started_room(db, turn_timeout=0.05)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        assert g.state.phase == "upgrade"  # 先手第 1 回合从升级阶段开始
        room.reschedule_timer()
        assert room.current_timer_key() == ("turn", g.state.turn)
        turn = g.state.turn
        await asyncio.sleep(0.2)
        # 已换手（对手回合），且先手方有一名 0 级式神被随机升到 1 级
        assert g.state.active == 1
        assert g.state.turn > turn
        assert sum(s.level == 1 for s in g.state.players[0].shikigami) >= 2
    run(go())


def test_turn_timeout_pending_choice_random_choose(db):
    """回合超时遇结算中交互选择（检视选牌）挂起：先随机作答到底，再走常规超时
    流程（升级/结束回合）——否则 apply 拒绝 choose 以外的指令，计时器 key
    不变也不会重启，房间死局。"""
    async def go():
        room, ws0, _ = await _started_room(db, turn_timeout=0.05)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        while g.state.phase == "upgrade":  # 检视选牌只会在战斗阶段出现
            idx = g.legal_upgrade_indices(0)[0]
            g.apply({"op": "upgrade", "player": 0, "index": idx})
        p0 = g.state.players[0]
        hand_n = len(p0.hand)
        assert g._open_deck_top_pick(0, 2, 1)  # 青灯夜谈式挂起（无续块）
        assert g.state.pending_choice is not None
        turn = g.state.turn
        room.reschedule_timer()  # 调度→回合切换后刷新计时 key，走真实超时路径
        for _ in range(50):  # 等首次超时完整收尾（换手即回调结束）
            if g.state.active == 1:
                break
            await asyncio.sleep(0.02)
        room._cancel_timer()  # 防 0.05s 计时器二次超时循环换手干扰断言
        assert g.state.pending_choice is None
        assert len(p0.hand) == hand_n + 1  # 随机作答：检视牌已入手
        assert g.state.active == 1 and g.state.turn > turn  # 常规超时收尾完成
        assert any(m.get("type") == "notice" and "随机选择" in m.get("text", "")
                   for m in ws0.messages)
    run(go())


def test_discard_pick_sanitized_and_timeout_random_choose(db):
    """交互弃牌限类型候选：联机仅作答方可见合法 uid；超时随机作答也只弃
    合法幻境牌，随后续跑抽牌并走常规回合超时收尾。"""
    async def go():
        room, ws0, _ = await _started_room(db, turn_timeout=0.05)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        while g.state.phase == "upgrade":
            idx = g.legal_upgrade_indices(0)[0]
            g.apply({"op": "upgrade", "player": 0, "index": idx})
        p0 = g.state.players[0]
        db.cards[10010151] = F.card(10010151, card_type="field", intensity=3)
        cid = 10010195
        db.cards[cid] = F.card(cid, token=True, steps=[
            F.Step(op="discard_pick", card_type="field"),
            F.Step(op="draw", count=3)])
        other = p0.hand[0]
        fld = F.give(g, 0, 10010151)
        hand_before = len(p0.hand)
        F.play(g, 0, cid)
        pend = g.state.pending_choice
        assert pend is not None and pend["options"] == [fld.uid]
        from server.room import sanitize_state
        payload = g.state.model_dump(mode="json")
        assert sanitize_state(payload, 0)["pending_choice"]["options"] == [fld.uid]
        assert sanitize_state(payload, 1)["pending_choice"]["options"] == [0]
        turn = g.state.turn
        room.reschedule_timer()
        for _ in range(50):
            if g.state.active == 1:
                break
            await asyncio.sleep(0.02)
        room._cancel_timer()
        assert g.state.pending_choice is None
        assert fld in p0.graveyard
        assert other in p0.hand
        assert len(p0.hand) == hand_before + 2
        assert g.state.active == 1 and g.state.turn > turn
        assert any(m.get("type") == "notice" and "随机选择" in m.get("text", "")
                   for m in ws0.messages)
    run(go())


def test_turn_timeout_field_summon_pick_random_choose(db):
    """回合内主动选择（选择召唤幻境，kind="field_summon_pick"）超时：系统自动
    随机选择（随机召唤对应幻境）并结束回合（定案(2)）。"""
    async def go():
        room, ws0, _ = await _started_room(db, turn_timeout=0.05)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        while g.state.phase == "upgrade":
            idx = g.legal_upgrade_indices(0)[0]
            g.apply({"op": "upgrade", "player": 0, "index": idx})
        p0 = g.state.players[0]
        # 残阳无影式挂起（无续块）：选项 = 两张 dummy 幻境牌（base_db 无实装幻境牌）
        from tests import factories as F
        for cid in (10010161, 10010162):
            db.cards[cid] = F.card(cid, shikigami=100101, card_type="field",
                                   intensity=2)
        assert g._open_field_summon_pick(0, [10010161, 10010162])
        assert g.state.pending_choice is not None
        turn = g.state.turn
        room.reschedule_timer()  # 刷新计时 key，走真实超时路径
        for _ in range(50):  # 等首次超时完整收尾（换手即回调结束）
            if g.state.active == 1:
                break
            await asyncio.sleep(0.02)
        room._cancel_timer()  # 防 0.05s 计时器二次超时循环换手干扰断言
        assert g.state.pending_choice is None
        assert len(p0.fields) == 1  # 随机选择：对应幻境已直接召唤
        assert p0.fields[0].card_id in (10010161, 10010162)
        assert g.state.active == 1 and g.state.turn > turn  # 常规超时收尾完成
        assert any(m.get("type") == "notice" and "随机选择" in m.get("text", "")
                   for m in ws0.messages)
    run(go())


def test_turn_timeout_invocation_pick_random_choose(db):
    """回合内主动选择（选择灵咒结附，kind="invocation_pick"，鬼切选鬼斩）超时：
    系统自动随机选择（作答键 choice=灵咒名）并对目标结附，再结束回合（同定案(2)）。"""
    async def go():
        room, ws0, _ = await _started_room(db, turn_timeout=0.05)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        while g.state.phase == "upgrade":
            idx = g.legal_upgrade_indices(0)[0]
            g.apply({"op": "upgrade", "player": 0, "index": idx})
        # 鬼切式挂起（无续块）：选项 = 两个 dummy 灵咒名
        from db.schema import InvocationDef
        from core.model import Ref
        for name in ("髭切", "友切"):
            db.invocations[name] = InvocationDef(name=name)
        assert g._open_invocation_pick(
            0, ["髭切", "友切"], Ref(player=0, shikigami=0), None)
        assert g.state.pending_choice is not None
        turn = g.state.turn
        room.reschedule_timer()  # 刷新计时 key，走真实超时路径
        for _ in range(50):  # 等首次超时完整收尾（换手即回调结束）
            if g.state.active == 1:
                break
            await asyncio.sleep(0.02)
        room._cancel_timer()  # 防 0.05s 计时器二次超时循环干扰断言
        assert g.state.pending_choice is None
        names = [e["name"] for e in g.state.players[0].shikigami[0].invocations]
        assert len(names) == 1 and names[0] in ("髭切", "友切")  # 随机结附其一
        assert g.state.active == 1 and g.state.turn > turn  # 常规超时收尾完成
        assert any(m.get("type") == "notice" and "随机选择" in m.get("text", "")
                   for m in ws0.messages)
    run(go())


def test_reconnect_resync_pending_choice(db):
    """结算中交互选择期间断线重连：resync 全量 state 的 pending_choice 对选择方
    保留真实 options（客户端据此提示作答），并附带当前计时器。"""
    async def go():
        room, _, _ = await _started_room(db, turn_timeout=60)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        assert g._open_deck_top_pick(0, 2, 1)
        real_opts = list(g.state.pending_choice["options"])
        room.reschedule_timer()  # 调度→回合切换后刷新计时 key
        seat0 = room.seat_to_player.index(0)
        conn = room.conns[seat0]
        room.disconnect(conn)
        ws_new = FakeWS()
        await room.reconnect(conn.token, ws_new)
        await room.resync(conn)
        msg = [m for m in ws_new.messages if m["type"] == "state"][-1]
        assert msg["payload"]["pending_choice"]["options"] == real_opts  # 选择方视角不脱敏
        assert msg.get("timer", {}).get("kind") == "turn"
    run(go())


def test_timer_not_reset_by_actions_within_turn(db):
    """同一回合内的操作不重置回合计时器（120s 覆盖整个回合）。"""
    async def go():
        room, ws0, _ = await _started_room(db, turn_timeout=0.15)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        room.reschedule_timer()
        key = room.current_timer_key()
        assert key[0] == "turn"
        # 回合内升级（合法操作）后计时 key 不变
        idx = g.legal_upgrade_indices(g.state.active)[0]
        await room.handle_cmd(room.seat_to_player.index(g.state.active),
                              {"op": "upgrade", "index": idx})
        assert room.current_timer_key() == key
    run(go())


def test_state_carries_timer_deadline(db):
    """state 消息附带当前计时器（kind/deadline）：调度阶段 kind=mulligan，
    双方 ready 后切换为 turn；deadline 约为 now + 对应超时时长。"""
    async def go():
        room, ws0, _ = await _started_room(db)
        timer = [m for m in ws0.messages if m["type"] == "state"][-1]["timer"]
        assert timer["kind"] == "mulligan"
        assert 0 < timer["deadline"] - time.time() <= room.mulligan_timeout
        for pi in (0, 1):
            await room.handle_cmd(room.seat_to_player.index(pi), {"op": "ready"})
        timer = [m for m in ws0.messages if m["type"] == "state"][-1]["timer"]
        assert timer["kind"] == "turn"
        assert 0 < timer["deadline"] - time.time() <= room.turn_timeout
    run(go())


# ---------- 安全 ----------

def test_state_sanitized_per_viewer(db):
    """对手的手牌/牌库内容脱敏为占位卡（张数公开），己方不受影响。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        for ws, seat in ((ws0, 0), (ws1, 1)):
            viewer = room.seat_to_player[seat]
            payload = [m for m in ws.messages if m["type"] == "state"][-1]["payload"]
            opp = payload["players"][1 - viewer]["zones"]
            assert all(c["id"] == 0 for c in opp["hand"])
            assert all(c["id"] == 0 for c in opp["deck"])
            assert len(opp["hand"]) == 5  # 张数公开
            own = payload["players"][viewer]["zones"]
            assert all(c["id"] != 0 for c in own["hand"])
    run(go())


def test_state_sanitizes_private_quest_clues_per_viewer():
    """今日委托线索账本仅所属方可见，原有私密日志仍按 viewer 过滤。"""
    from server.room import sanitize_state

    payload = {
        "players": [
            {"name": "甲", "zones": {}, "ext": {"quest_clues_seen": ["线索甲"]}},
            {"name": "乙", "zones": {}, "ext": {"quest_clues_seen": ["线索乙"]}},
        ],
        "log": ["公开行", "甲方私密行"],
        "log_vis": [None, 0],
    }
    own = sanitize_state(payload, 0)
    peer = sanitize_state(payload, 1)
    assert own["players"][0]["ext"]["quest_clues_seen"] == ["线索甲"]
    assert own["players"][1]["ext"]["quest_clues_seen"] == []
    assert peer["players"][1]["ext"]["quest_clues_seen"] == ["线索乙"]
    assert peer["players"][0]["ext"]["quest_clues_seen"] == []
    assert own["log"] == ["公开行", "甲方私密行"]
    assert peer["log"] == ["公开行"]


def test_mulligan_hidden_from_opponent(db):
    """调度阶段信息隐藏：对方调度行为行（泄露次数）不广播给另一方，
    对方 payload 中剩余调度次数抹除为 0；"完成调度"为无信息状态保留；
    resync 全量补发同样过滤。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        g = room.game
        p0 = room.seat_to_player[0]
        uid = g.state.players[p0].hand[0].uid
        await room.handle_cmd(0, {"op": "mulligan", "uid": uid})
        log0 = ws0.messages[-1]["log"]
        log1 = ws1.messages[-1]["log"]
        assert any("调度了一张手牌" in l for l in log0)      # 自己可见
        assert not any("调度了一张手牌" in l for l in log1)  # 对方不可见
        # 对方 payload 中的剩余调度次数被抹除
        assert ws1.messages[-1]["payload"]["players"][p0]["mulligans_left"] == 0
        # 完成调度行保留（无信息状态）
        await room.handle_cmd(0, {"op": "ready"})
        assert any("完成调度" in l for l in ws1.messages[-1]["log"])
        # resync 全量补发同样过滤（仅 p0 调度过）
        room.disconnect(room.conns[1])
        ws_new = FakeWS()
        await room.reconnect(room.conns[1].token, ws_new)
        await room.resync(room.conns[1])
        full = [m for m in ws_new.messages if m["type"] == "state"][-1]["log"]
        assert not any("调度了一张手牌" in l for l in full)
    run(go())


def test_private_log_visible_only_to_owner(db):
    """非公开信息行（维护者改进②）：引擎打 owner 标的日志行仅所属方可见——
    增量广播（log/timeline 双通道）、resync 全量补发与 state 负载内嵌的完整
    log/timeline 均按 viewer 过滤；无标行双方照常可见。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        g = room.game
        p0 = room.seat_to_player[0]
        g._log("【私密】仅己方可见行", owner=p0)
        g._log("双方可见行")
        await room.broadcast_state()
        log0, log1 = ws0.messages[-1]["log"], ws1.messages[-1]["log"]
        assert any("仅己方可见行" in l for l in log0)       # 所属方可见
        assert not any("仅己方可见行" in l for l in log1)   # 对方不可见
        assert any("双方可见行" in l for l in log1)         # 公开行照常
        tl0 = ws0.messages[-1].get("timeline", [])
        tl1 = ws1.messages[-1].get("timeline", [])
        assert any("仅己方可见行" in e.get("m", "") for e in tl0)
        assert not any("仅己方可见行" in e.get("m", "") for e in tl1)
        # state 负载内嵌的完整 log/timeline 同样脱敏（防改端窥探）
        assert not any("仅己方可见行" in l
                       for l in ws1.messages[-1]["payload"]["log"])
        assert not any("仅己方可见行" in e.get("m", "")
                       for e in ws1.messages[-1]["payload"]["timeline"])
        assert any("仅己方可见行" in l
                   for l in ws0.messages[-1]["payload"]["log"])
        # resync 全量补发同样过滤
        room.disconnect(room.conns[1])
        ws_new = FakeWS()
        await room.reconnect(room.conns[1].token, ws_new)
        await room.resync(room.conns[1])
        full = [m for m in ws_new.messages if m["type"] == "state"][-1]["log"]
        assert not any("仅己方可见行" in l for l in full)
    run(go())


def test_hand_privacy_visual_event_has_no_card_identity_for_opponent(db):
    """入手动画按 uid 关联公开图元，增量与完整状态都不得泄露卡牌 id。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        player = room.seat_to_player[0]
        card = room.game.state.players[player].deck[0]
        room.game.draw_cards(player, 1)
        await room.broadcast_state()
        expected = {"k": "v", "v": "hand", "p": player, "u": card.uid,
                    "from": "deck", "reason": "draw"}
        for ws in (ws0, ws1):
            message = ws.messages[-1]
            incremental = [entry for entry in message["timeline"]
                           if entry.get("v") == "hand"]
            complete = [entry for entry in message["payload"]["timeline"]
                        if entry.get("v") == "hand"]
            assert incremental[-1] == expected
            assert complete[-1] == expected
            assert not ({"c", "card", "id"} & incremental[-1].keys())
            assert not ({"c", "card", "id"} & complete[-1].keys())
    run(go())


def test_pending_choice_sanitized_for_opponent():
    """联机信息隐藏：pending_choice 的可检视牌仅选择方可见，其余视角抹除为占位。"""
    from server.room import sanitize_state
    payload = {"players": [{"zones": {}}, {"zones": {}}],
               "pending_choice": {"kind": "deck_top_pick", "player": 0,
                                  "options": [11, 12, 13]}}
    assert sanitize_state(payload, 0)["pending_choice"]["options"] == [11, 12, 13]
    assert sanitize_state(payload, 1)["pending_choice"]["options"] == [0, 0, 0]


def test_sanitize_hides_secret_delayed_chosen():
    """会（secret 延迟能力）：对手视角抹除选择目标；非 secret 条目与原始状态不受影响。"""
    from server.room import sanitize_state
    payload = {"players": [
        {"zones": {"hand": [], "deck": []},
         "shikigami": [{"delayed": [
             {"chosen": {"player": 1, "shikigami": 2}, "secret": True, "uses": 1},
             {"chosen": {"player": 1, "shikigami": 1}, "uses": 1}]}]},
        {"zones": {"hand": [], "deck": []}, "shikigami": []},
    ]}
    view = sanitize_state(payload, 1)  # viewer=1 → 对手为 players[0]
    delayed = view["players"][0]["shikigami"][0]["delayed"]
    assert delayed[0]["chosen"] is None                       # secret：抹除
    assert delayed[1]["chosen"] == {"player": 1, "shikigami": 1}  # 非 secret：保留
    # 原始状态不被修改
    assert payload["players"][0]["shikigami"][0]["delayed"][0]["chosen"] is not None


def test_max_rooms_cap(db):
    mgr = RoomManager(db, max_rooms=1)
    mgr.create()
    with pytest.raises(ValueError, match="上限"):
        mgr.create()


# ---------- 看门狗：未开局房间无人员变动自动解散 ----------

def test_watchdog_dissolves_idle_lobby_room(db):
    """未开局房间超过 600s（测试注入超时时间戳）无人员变动：看门狗扫描解散——
    房内连接收到 dissolved 通知、连接关闭、房间从管理器移除。"""
    async def go():
        mgr = RoomManager(db)
        room = mgr.create()
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        await room.on_seat_filled()
        room.last_activity = time.time() - 700  # 注入：10 分钟无人员变动
        doomed = await mgr.dissolve_idle()
        assert doomed == [room.id]
        assert mgr.get(room.id) is None
        for ws in (ws0, ws1):
            assert any(m["type"] == "dissolved" for m in ws.messages)
            assert ws.closed
    run(go())


def test_watchdog_activity_refresh_keeps_room(db):
    """人员变动刷新计时：join/lobby_leave 刷新 last_activity，未超时的房间不解散；
    纯断线 disconnect 不算人员变动、不刷新。"""
    async def go():
        mgr = RoomManager(db)
        room = mgr.create()
        ws0 = FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        room.last_activity = time.time() - 700
        await room.join(1, "乙", FakeWS(), _deck_code(db))  # 进房刷新
        assert time.time() - room.last_activity < 5
        assert await mgr.dissolve_idle() == []
        assert mgr.get(room.id) is room
        ts = room.last_activity
        room.disconnect(room.conns[0])  # 纯断线：不刷新
        assert room.last_activity == ts
        room.last_activity = time.time() - 700
        await room.lobby_leave(1)  # 退房也刷新
        assert time.time() - room.last_activity < 5
        assert await mgr.dissolve_idle() == []
        assert mgr.get(room.id) is room
    run(go())


def test_watchdog_skips_started_room(db):
    """已开局房间不适用看门狗（对局超 10 分钟是常态）：即使人员变动时刻超过
    时限也不解散，其清理由 abandoned（双方断线）等既有机制负责。"""
    async def go():
        mgr = RoomManager(db)
        room, ws0, _ = await _started_room(db)
        mgr.rooms[room.id] = room
        room.last_activity = time.time() - 700
        assert await mgr.dissolve_idle() == []
        assert mgr.get(room.id) is room
        assert not any(m["type"] == "dissolved" for m in ws0.messages)
        room._cancel_timer()  # 收尾：防计时任务悬置
    run(go())


# ==========================================================================
# 联机端到端（原 test_net.py）：线程内起 uvicorn + 两个 websockets.sync 客户端，
# 跑完 创建/加入/调度/升级/出牌回合 全流程。端口不可用时跳过。
# ==========================================================================

PORT = 8377
URL = f"ws://127.0.0.1:{PORT}/ws"


class WsClient:
    def __init__(self, headers: dict | None = None):
        from websockets.sync.client import connect
        hdrs = {"User-Agent": "BWPro-CLI/1.0"} if headers is None else headers
        self.ws = connect(URL, additional_headers=hdrs)

    def send(self, msg: dict):
        if msg.get("type") in ("create", "join"):
            msg.setdefault("client", "BWPro-CLI/1.0")  # 应用层客户端标识软门槛
        self.ws.send(json.dumps(msg))

    def recv_until(self, *types: str, limit: int = 50) -> dict:
        for _ in range(limit):
            msg = json.loads(self.ws.recv(timeout=10))
            if msg.get("type") in types:
                return msg
        raise AssertionError(f"未等到消息类型 {types}")


@pytest.fixture(scope="module")
def server():
    import uvicorn
    db = F.base_db()
    app = create_app(RoomManager(db, starting_timeout=0.05))
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error",
                            server_header=False)  # 与生产启动参数一致（不暴露指纹）
    srv = uvicorn.Server(config)
    t = threading.Thread(target=lambda: asyncio.run(srv.serve()), daemon=True)
    t.start()
    for _ in range(50):  # 等服务就绪
        if srv.started:
            break
        time.sleep(0.1)
    if not srv.started:
        pytest.skip("无法启动本地测试服务端")
    yield srv
    srv.should_exit = True


def test_websocket_disconnect_logs_code(server, caplog):
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        client = WsClient()
        client.ws.close(code=1000)
        for _ in range(50):
            if "关闭码=1000" in caplog.text:
                break
            time.sleep(0.02)
    assert "关闭码=1000" in caplog.text


def test_websocket_invalid_client_close_logs_code_and_reason(server, db, caplog):
    client = WsClient()
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        client.send({"type": "create", "deck_code": _deck_code(db),
                     "client": "Mozilla/5.0"})
        assert "客户端标识" in client.recv_until("error")["reason"]
        for _ in range(50):
            if "关闭码=1008" in caplog.text:
                break
            time.sleep(0.02)
    client.ws.close()
    assert "房间=-" in caplog.text
    assert "关闭码=1008" in caplog.text
    assert "原因=客户端标识无效" in caplog.text


def test_websocket_disconnect_logs_room_context_and_reason(server, db, caplog):
    client, joined = _ws_create_room(db, "日志")
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        client.ws.close(code=1001, reason="客户端离开")
        for _ in range(50):
            if "原因=客户端离开" in caplog.text:
                break
            time.sleep(0.02)
    assert joined["room_id"] in caplog.text
    assert "来源=127.0.0.1" in caplog.text
    assert "关闭码=1001" in caplog.text
    assert "原因=客户端离开" in caplog.text
    assert joined["token"] not in caplog.text


def test_websocket_normal_leave_logs_code_and_room(server, db, caplog):
    first, second, joined = _ws_room(db)
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        first.send({"type": "leave"})
        assert first.recv_until("left")["type"] == "left"
        for _ in range(50):
            if "关闭码=1000" in caplog.text:
                break
            time.sleep(0.02)
    second.ws.close()
    assert joined["room_id"] in caplog.text
    assert "关闭码=1000" in caplog.text


def test_websocket_leave_keeps_socket_for_create_and_join(server, db):
    client, _joined = _ws_create_room(db, "甲")
    client.send({"type": "leave"})
    assert client.recv_until("left")["type"] == "left"

    client.send({"type": "create", "name": "乙", "deck_code": _deck_code(db)})
    assert client.recv_until("joined", "error")["type"] == "joined"
    client.send({"type": "leave"})
    assert client.recv_until("left")["type"] == "left"

    other, other_joined = _ws_create_room(db, "丙")
    client.send({"type": "join", "room_id": other_joined["room_id"],
                 "name": "丁", "deck_code": _deck_code(db)})
    assert client.recv_until("joined", "error")["type"] == "joined"
    client.ws.close()
    other.ws.close()


def test_full_match_flow(server, db):
    a = WsClient()
    a.send({"type": "create", "name": "甲", "deck_code": _deck_code(db),
            "client_ip": "8.8.8.8"})
    ja = a.recv_until("joined", "error")
    assert ja["type"] == "joined"
    room_id = ja["room_id"]

    b = WsClient()
    b.send({"type": "join", "room_id": room_id, "name": "乙",
            "deck_code": _deck_code(db), "client_ip": "8.8.4.4"})
    jb = b.recv_until("joined")
    assert jb["type"] == "joined"

    # 准备阶段：双方收到 lobby（无人准备、不计时）后手动确认准备
    la = a.recv_until("lobby")
    assert la["ready"] == [] and la["deadline"] is None
    b.recv_until("lobby")
    a.send({"type": "ready"})
    b.send({"type": "ready"})

    sa = a.recv_until("start")
    sb = b.recv_until("start")
    assert sa["player_index"] != sb["player_index"]
    assert (sa["you_first"], sb["you_first"]) in ((True, False), (False, True))
    assert len(sa["reconnect_code"]) == len(sb["reconnect_code"]) == 8
    assert sa["reconnect_code"] != sb["reconnect_code"]

    # 双方都收到初始 state（调度阶段）
    st_a = a.recv_until("state")["payload"]
    assert st_a["phase"] == "mulligan"
    b.recv_until("state")

    # 调度：双方直接 ready（两个客户端都要排干各次广播）
    a.send({"type": "cmd", "cmd": {"op": "ready"}})
    b.send({"type": "cmd", "cmd": {"op": "ready"}})
    st = None
    for c in (a, b):
        st = c.recv_until("state")["payload"]
        while st["phase"] == "mulligan":
            st = c.recv_until("state")["payload"]
    assert st["phase"] == "upgrade"
    # 行动方是 players[0]（先手）
    first = a if sa["you_first"] else b
    second = b if sa["you_first"] else a

    # 升级阶段：升一名合法式神（0 级者之一）
    me = st["active"]
    upgradable = [i for i, s in enumerate(st["players"][me]["shikigami"])
                  if s["kind"] == "shikigami" and not s["despawned"]
                  and s["level"] == min(x["level"] for x in st["players"][me]["shikigami"]
                                        if x["kind"] == "shikigami" and not x["despawned"])]
    first.send({"type": "cmd", "cmd": {"op": "upgrade", "index": upgradable[0]}})
    st = first.recv_until("state")["payload"]
    assert st["phase"] == "battle"
    assert st["players"][me]["shikigami"][upgradable[0]]["level"] == 1

    # 非回合方指令被拒绝（error 只回发送者；先排干升级广播）
    second.recv_until("state")
    second.send({"type": "cmd", "cmd": {"op": "end_turn"}})
    err = second.recv_until("error", "state")
    assert err["type"] == "error"

    # 结束回合 → 换手
    first.send({"type": "cmd", "cmd": {"op": "end_turn"}})
    st = second.recv_until("state")["payload"]
    assert st["active"] == 1 - me

    # 对局中断线：公网 IP 必须与入座记录匹配，识别码只在 start 后下发
    a.ws.close()
    wrong_ip = WsClient()
    wrong_ip.send({"type": "join", "room_id": room_id,
                   "reconnect_code": sa["reconnect_code"], "client_ip": "1.1.1.1"})
    assert wrong_ip.recv_until("error")["type"] == "error"
    wrong_ip.ws.close()

    a2 = WsClient()
    a2.send({"type": "join", "room_id": room_id,
             "reconnect_code": sa["reconnect_code"], "client_ip": "8.8.8.8"})
    ja2 = a2.recv_until("joined", "error")
    assert ja2["type"] == "joined"
    st2 = a2.recv_until("state")["payload"]
    assert st2["turn"] == st["turn"]
    a2.ws.close()
    b.ws.close()


def _ws_create_room(db, name: str, **extra):
    client = WsClient()
    client.send({"type": "create", "name": name,
                 "deck_code": _deck_code(db), **extra})
    joined = client.recv_until("joined", "error")
    assert joined["type"] == "joined"
    return client, joined


def _ws_room(db, *, started: bool = False, mode: str = "standard"):
    first, joined = _ws_create_room(db, "甲", mode=mode)
    second = WsClient()
    second.send({"type": "join", "room_id": joined["room_id"], "name": "乙",
                 "deck_code": _deck_code(db)})
    assert second.recv_until("joined", "error")["type"] == "joined"
    first.recv_until("lobby")
    if started:
        first.send({"type": "ready"})
        second.send({"type": "ready"})
        first.recv_until("start")
        second.recv_until("start")
        first.recv_until("state")
        second.recv_until("state")
    return first, second, joined


@pytest.mark.parametrize("op", [[], None, {}, ""])
def test_parse_rejects_invalid_cmd_op(op):
    raw = json.dumps({"type": "cmd", "cmd": {"op": op}})
    with pytest.raises(ValueError, match="cmd.op"):
        protocol.parse_client_message(raw)


@pytest.mark.parametrize("op", [[], None, {}, ""])
def test_malformed_cmd_op_returns_error_and_match_continues(server, db, op):
    """畸形 op 只回普通 error，不进入 engine_error，之后仍可完成调度。"""
    first, second, _ = _ws_room(db, started=True)
    first.send({"type": "cmd", "cmd": {"op": op}})
    reply = first.recv_until("error", "game_over")
    assert reply["type"] == "error" and "引擎异常" not in reply["reason"]
    first.send({"type": "cmd", "cmd": {"op": "ready"}})
    assert first.recv_until("state", "game_over")["type"] == "state"
    first.ws.close()
    second.ws.close()


@pytest.mark.parametrize("hello", ["create", "join"])
@pytest.mark.parametrize("name", ["甲\n乙", "甲\x1b乙", "甲\x85乙"])
def test_player_name_rejects_unicode_control_characters(server, db, hello, name):
    """create/join 名称拒绝 C0/C1 控制字符；正常中文由房间建立流程持续覆盖。"""
    clients = []
    if hello == "create":
        client = WsClient()
        clients.append(client)
        client.send({"type": "create", "name": name, "deck_code": _deck_code(db)})
    else:
        owner, joined = _ws_create_room(db, "甲")
        clients.append(owner)
        client = WsClient()
        clients.append(client)
        client.send({"type": "join", "room_id": joined["room_id"],
                     "name": name, "deck_code": _deck_code(db)})
    assert client.recv_until("joined", "error")["type"] == "error"
    for item in clients:
        item.ws.close()


@pytest.mark.parametrize("exc_type", [TypeError, ValueError, AttributeError, KeyError])
def test_command_data_errors_return_generic_error_and_match_continues(db, exc_type, caplog):
    """指令数据异常不得泄露内部细节或终止对局，恢复原指令处理后可继续。"""
    async def go():
        room, ws0, ws1 = await _started_room(db)
        original_apply = room.game.apply

        def raise_data_error(_cmd):
            raise exc_type("内部细节")

        room.game.apply = raise_data_error
        with caplog.at_level(logging.INFO, logger="bwpro.room"):
            await room.handle_cmd(0, {"op": "ready"})
        reply = ws0.messages[-1]
        assert reply["type"] == "error"
        assert "内部细节" not in reply["reason"] and "引擎异常" not in reply["reason"]
        assert room.id in caplog.text and "座位=0" in caplog.text
        assert "指令=ready" in caplog.text
        assert "被拒绝：指令格式或参数非法" in caplog.text
        assert "内部细节" not in caplog.text
        assert not any(m["type"] == "game_over" for m in ws0.messages + ws1.messages)

        room.game.apply = original_apply
        await room.handle_cmd(0, {"op": "ready"})
        assert ws0.messages[-1]["type"] == "state"
        room._cancel_timer()
    run(go())


@pytest.mark.parametrize("hello", ["create", "join"])
def test_room_binding_rejects_second_hello(server, db, hello):
    """同一 socket 第二次成功 create/join 不得抢占新的房间身份。"""
    first, second, joined = _ws_room(db)
    clients = [first, second]
    caller = first if hello == "create" else second
    peer = second if hello == "create" else first
    if hello == "create":
        caller.send({"type": "create", "name": "丙", "deck_code": _deck_code(db)})
    else:
        other, other_joined = _ws_create_room(db, "丙")
        clients.append(other)
        caller.send({"type": "join", "room_id": other_joined["room_id"],
                     "name": "丁", "deck_code": _deck_code(db)})
    reply = caller.recv_until("joined", "error")
    assert reply["type"] == "error"
    caller.send({"type": "ready"})
    notice = peer.recv_until("notice")
    assert "已准备" in notice["text"]
    for client in clients:
        client.ws.close()


def test_room_binding_failed_reconnect_preserves_lobby_binding(server, db):
    """无效 token 不得把已入座 socket 绑到另一房间操作 ready/env/leave。"""
    first, second, _ = _ws_room(db, mode="free")
    other, other_peer, other_joined = _ws_room(db, mode="free")
    first.send({"type": "join", "room_id": other_joined["room_id"], "token": "bad"})
    assert first.recv_until("error")["type"] == "error"

    first.send({"type": "env", "date": 20991231})
    assert "环境" in second.recv_until("notice")["text"]
    first.send({"type": "ready"})
    assert "已准备" in second.recv_until("notice")["text"]
    first.send({"type": "leave"})
    assert second.recv_until("peer_left")["name"] == "甲"
    other.send({"type": "ready"})
    assert "已准备" in other_peer.recv_until("notice")["text"]
    for client in (second, other, other_peer):
        client.ws.close()


def test_room_binding_failed_reconnect_preserves_started_binding(server, db):
    """已开局房间的无效重连失败后，cmd 仍只作用于原房间。"""
    first, second, _ = _ws_room(db, started=True)
    other, other_peer, other_joined = _ws_room(db, started=True)
    first.send({"type": "join", "room_id": other_joined["room_id"], "token": "bad"})
    assert first.recv_until("error")["type"] == "error"
    first.send({"type": "cmd", "cmd": {"op": "ready"}})
    assert second.recv_until("state")["type"] == "state"
    for client in (first, second, other, other_peer):
        client.ws.close()


def test_reconnect_socket_closes_replaced_socket(db):
    """重连换绑新 socket 后必须关闭旧 socket，阻断旧指令入口。"""
    async def go():
        room, old, _ = await _started_room(db)
        new = FakeWS()
        conn = await room.reconnect(room.conns[0].token, new)
        assert conn.ws is new
        assert old.closed
        room._cancel_timer()
    run(go())


def test_reconnect_socket_stale_send_failure_preserves_new_socket(db):
    """旧发送挂起期间完成重连，随后旧发送失败不得清掉新 socket。"""
    async def go():
        class PendingFailWS(FakeWS):
            def __init__(self):
                super().__init__()
                self.send_started = asyncio.Event()
                self.send_release = asyncio.Event()

            async def send_text(self, text: str):
                self.send_started.set()
                await self.send_release.wait()
                raise RuntimeError("旧连接发送失败")

        room = mk_room(db)
        old = PendingFailWS()
        conn = await room.join(0, "甲", old, _deck_code(db))
        pending_send = asyncio.create_task(conn.send(protocol.notice("旧消息")))
        await old.send_started.wait()
        new = FakeWS()
        assert await room.reconnect(conn.token, new) is conn
        old.send_release.set()
        await pending_send
        assert conn.ws is new and conn.connected
        await conn.send(protocol.notice("新消息"))
        assert new.messages[-1]["text"] == "新消息"
    run(go())


def test_reconnect_socket_old_command_cannot_act(server, db):
    """旧 socket 在重连后发送 cmd 只能发现连接已关闭或收到 error。"""
    import websockets.exceptions

    old, peer, joined = _ws_room(db, started=True)
    new = WsClient()
    new.send({"type": "join", "room_id": joined["room_id"], "token": joined["token"]})
    assert new.recv_until("joined", "error")["type"] == "joined"
    try:
        old.send({"type": "cmd", "cmd": {"op": "ready"}})
        reply = old.recv_until("error", "state")
    except websockets.exceptions.ConnectionClosed:
        reply = {"type": "closed"}
    assert reply["type"] in ("error", "closed")
    for client in (old, new, peer):
        client.ws.close()


@pytest.mark.parametrize("started", [False, True])
def test_reconnect_socket_stale_disconnect_preserves_new_socket(server, db, started):
    """旧 socket 断开不得清理新连接；大厅 ready 与开局 cmd 均继续可用。"""
    old, peer, joined = _ws_room(db, started=started)
    new = WsClient()
    new.send({"type": "join", "room_id": joined["room_id"], "token": joined["token"]})
    assert new.recv_until("joined", "error")["type"] == "joined"
    if started:
        new.recv_until("state")  # 排干重连补发，后续 state 必须来自新指令
    old.ws.close()
    time.sleep(0.1)  # 等旧 socket 的断线收尾完成，再验证新连接未被误清理
    if started:
        new.send({"type": "cmd", "cmd": {"op": "ready"}})
        assert new.recv_until("state", "error")["type"] == "state"
    else:
        new.send({"type": "ready"})
        assert "已准备" in peer.recv_until("notice")["text"]
    for client in (new, peer):
        client.ws.close()


def test_http_probe_gets_403_no_server_header(server):
    """非 WS 的 HTTP 探针（无 UA 可直达服务端的场景）：任意路径一律 403 空体，
    不用框架默认 404；且不下发 server 响应头（不暴露 uvicorn 指纹）。"""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    for path in ("/", "/ws", "/admin", "/gui", "/gui/api/catalog"):
        conn.request("GET", path)
        r = conn.getresponse()
        assert r.status == 403
        assert r.read() == b""
        assert r.getheader("server") is None
    conn.close()


def test_client_id_soft_gate(server, db):
    """客户端标识软门槛（应用层）：握手一律放行（穿透代理可能改写 HTTP 头）；
    create/join 不带合法 client 标识则拒绝并断联，携带正确前缀的正常建房。"""
    import websockets.exceptions
    c = WsClient(headers={"User-Agent": "Mozilla/5.0"})  # 握手不再看 UA：可连接
    c.send({"type": "create", "name": "甲", "deck_code": _deck_code(db),
            "client": "Mozilla/5.0"})
    e = c.recv_until("error")
    assert "客户端标识" in e["reason"]
    with pytest.raises(websockets.exceptions.ConnectionClosed):
        c.recv_until("state", limit=3)  # 服务端随后断联
    d = WsClient()
    d.send({"type": "create", "name": "乙", "deck_code": _deck_code(db)})
    assert d.recv_until("joined", "error")["type"] == "joined"  # 默认合法标识：正常
    d.ws.close()


def test_connected_lobby_has_no_auth_timeout(server, db):
    """已连接但尚未创建/加入房间的大厅不因旧版 5 秒认证看门狗被 1008 关闭。"""
    import time
    c = WsClient()
    time.sleep(5.1)  # 越过旧看门狗期限后仍应能正常创建房间
    c.send({"type": "create", "name": "甲", "deck_code": _deck_code(db)})
    assert c.recv_until("joined", "error")["type"] == "joined"
    c.ws.close()


def test_unentered_connection_times_out_after_five_minutes(server, db, monkeypatch):
    """连接后连续 5 分钟未入房才关闭；测试仅压缩时间，不改变期限口径。"""
    import websockets.exceptions
    assert server_main_timeout() == 300.0
    monkeypatch.setattr("server.main.AUTH_TIMEOUT", 0.05)
    c = WsClient()
    with pytest.raises(websockets.exceptions.ConnectionClosedError):
        c.ws.recv(timeout=1)
    c.ws.close()


def server_main_timeout() -> float:
    from server.main import AUTH_TIMEOUT
    return AUTH_TIMEOUT


def test_debug_room_rejected_by_default(server, db):
    """debug 建房门控：服务端未开 --allow-debug-rooms 时，create 带 debug=true 被拒。"""
    a = WsClient()
    a.send({"type": "create", "name": "甲", "deck_code": _deck_code(db),
            "debug": True})
    e = a.recv_until("error")
    assert "debug" in e["reason"]
    a.ws.close()


# ---------- 对局环境（平衡性版本日期）----------

def test_room_env_date_restricts_decks(db):
    """房间环境早于数据版本：入座卡组校验失败（错误带环境日期）；最新环境正常。"""
    async def go():
        room = mk_room(db, env_date=20200101)  # 测试数据 version=20260720
        with pytest.raises(ValueError, match="环境"):
            await room.join(0, "甲", FakeWS(), _deck_code(db))
        assert room.conns[0] is None
        room2 = mk_room(db, env_date=20991231)
        await room2.join(0, "甲", FakeWS(), _deck_code(db))
        assert room2.conns[0] is not None
    run(go())


def test_room_set_env(db):
    """自由模式房间：房主在双方均未准备时可更改环境（广播 lobby 携带 env_date）；
    非房主/已准备/使已入座卡组失效均拒绝。"""
    async def go():
        room = mk_room(db, mode="free")
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        await room.on_seat_filled()
        await room.set_env(1, 20991231)  # 非房主
        assert any(m["type"] == "error" and "房主" in m["reason"]
                   for m in ws1.messages)
        assert room.env_date is None
        await room.lobby_ready(0)
        await room.set_env(0, 20991231)  # 已准备状态：须先取消准备
        assert any(m["type"] == "error" and "取消准备" in m["reason"]
                   for m in ws0.messages)
        assert room.env_date is None
        await room.lobby_ready(0)  # 取消准备回 IDLE
        await room.set_env(0, 20200101)  # 使双方已入座卡组失效：拒绝并保持原环境
        assert room.env_date is None
        assert any(m["type"] == "error" and "不可用" in m["reason"]
                   for m in ws0.messages)
        await room.set_env(0, 20991231)  # 合法更改：广播 lobby 携带 env_date
        assert room.env_date == 20991231
        lobby = [m for m in ws1.messages if m["type"] == "lobby"][-1]
        assert lobby["env_date"] == 20991231
        room._cancel_lobby_timer()  # 收尾：防计时任务悬置
    run(go())


def test_room_mode_standard_gates_env(db):
    """标准模式（默认）：create 忽略所带 env_date、set_env 一律拒绝；
    lobby/start 消息携带 mode；非法 mode 报错。"""
    from server.manager import RoomManager
    mgr = RoomManager(db)
    room = mgr.create(env_date=20200101)  # standard 默认：env_date 被强制为 None
    assert room.mode == "standard" and room.env_date is None
    free = mgr.create(mode="free", env_date=20991231)
    assert free.mode == "free" and free.env_date == 20991231
    with pytest.raises(ValueError, match="模式"):
        mgr.create(mode="ranked")

    async def go():
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db))
        await room.join(1, "乙", ws1, _deck_code(db))
        await room.on_seat_filled()
        lobby = [m for m in ws1.messages if m["type"] == "lobby"][-1]
        assert lobby["mode"] == "standard"
        await room.set_env(0, 20991231)
        assert room.env_date is None
        assert any(m["type"] == "error" and "标准模式" in m["reason"]
                   for m in ws0.messages)
    run(go())


def test_sanitize_keeps_revealed_hand_cards():
    """已展示脱敏例外：对手手牌中 mods.revealed 的卡保留真实内容；
    暗牌保留非秘密的稳定身份与顺序，牌库仍完全匿名；原始 payload 不被修改。"""
    from server.room import _HIDDEN_CARD, sanitize_state
    payload = {"players": [
        {"zones": {"hand": [
            {"uid": 1, "id": 10010101, "mods": {"revealed": True}, "hand_seq": 7},
            {"uid": 2, "id": 10010102, "mods": {"enhance": 3}, "hand_seq": 9},
        ], "deck": [{"uid": 3, "id": 10010103, "mods": {}, "hand_seq": 0}]}},
        {"zones": {"hand": [], "deck": []}},
    ]}
    view = sanitize_state(payload, 1)  # viewer=1 → 对手为 players[0]
    hand = view["players"][0]["zones"]["hand"]
    assert hand[0]["id"] == 10010101 and hand[0]["uid"] == 1   # 已展示：保留真实内容
    assert hand[1] == {"uid": 2, "id": 0, "mods": {}, "hand_seq": 9}
    assert view["players"][0]["zones"]["deck"] == [dict(_HIDDEN_CARD)]
    assert payload["players"][0]["zones"]["hand"][1]["id"] == 10010102  # 原状态不变


def test_state_hand_info_shape(db):
    """state 推送附带己方手牌实时信息（hand_info，键 = 手牌 uid 字符串）：
    使用方式枚举/费用/关键字/数值段/使用条件等引擎求值字段形状；
    仅含己方手牌，对手暗牌只保留稳定身份与顺序。"""
    async def go():
        _, ws0, ws1 = await _started_room(db)
        for ws in (ws0, ws1):
            states = [m for m in ws.messages if m["type"] == "state"]
            assert states
            pl = states[-1]["payload"]
            info = pl["hand_info"]
            assert info  # 起始手牌非空
            own = next(p for p in pl["players"]
                       if {str(c["uid"]) for c in p["zones"]["hand"]} == set(info))
            other = pl["players"][1 - pl["players"].index(own)]
            hidden = other["zones"]["hand"]
            assert len({c["uid"] for c in hidden}) == len(hidden)
            assert all(c["uid"] > 0 and c["id"] == 0 and c["mods"] == {} for c in hidden)
            for uid, entry in info.items():
                assert int(uid) > 0
                assert {"cost", "keywords", "stats", "enhance", "quest",
                        "playable", "usage"} <= set(entry)
                assert entry["usage"], "每张手牌至少有一个使用方式条目"
                assert {"id", "label", "cost", "energy", "ok",
                        "reason", "effect"} <= set(entry["usage"][0])
    run(go())


def test_server_base_dependencies_exclude_gui_and_standard_extras():
    """服务端部署仅安装网络/数据依赖，不拉取桌面 GUI 或非必需扩展。"""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    dependencies = project["project"]["dependencies"]
    assert dependencies == [
        "pydantic>=2.13", "pyyaml>=6.0", "fastapi>=0.115",
        "uvicorn>=0.30", "websockets>=12.0",
    ]
    extras = project["project"]["optional-dependencies"]
    assert extras["gui"] == ["pyside6>=6.12.0", "pillow>=13.0.0"]
    assert extras["cli"] == ["prompt-toolkit>=3.0.53"]
    dev = project["dependency-groups"]["dev"]
    assert "pyside6>=6.12.0" in dev and "pillow>=13.0.0" in dev
    assert "prompt-toolkit>=3.0.53" in dev


@pytest.mark.parametrize("remote", ["origin", "main"])
def test_termux_launcher_syntax_and_dirty_tree_guard(tmp_path, remote):
    """Termux 启动脚本语法有效，本地改动存在时不执行拉取或覆盖。"""
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).parents[1] / "scripts" / "termux_server.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    text = script.read_text(encoding="utf-8")
    for required in ("git pull --ff-only", "--locked", "--managed-python",
                     "--python 3.14", "--no-dev", ".venv/bin/python", "启动服务端"):
        assert required in text
    assert "uv run" not in text
    assert 'UV_LINK_MODE="${UV_LINK_MODE:-copy}"' in text
    assert "export UV_LINK_MODE" in text

    subprocess.run(["git", "init", "-b", "master", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
                   check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"],
                   check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", remote,
                    "https://github.com/Varisox137/BWPro.git"], check=True)
    (tmp_path / "dirty.txt").write_text("local", encoding="utf-8")
    result = subprocess.run(["bash", str(script)],
                            env={**os.environ, "BWP_REPO_DIR": str(tmp_path)},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "未提交" in result.stderr
    assert not (tmp_path / ".git" / "FETCH_HEAD").exists()


@pytest.mark.parametrize("remote_url", [
    "https://github.com/Varisox137/BWPro",
    "https://github.com/Varisox137/BWPro/",
    "https://github.com/Varisox137/BWPro.git",
    "git@github.com:Varisox137/BWPro.git",
    "ssh://git@github.com/Varisox137/BWPro.git",
])
def test_termux_launcher_accepts_equivalent_remote_urls(tmp_path, remote_url):
    """GitHub 无 .git、尾斜杠与 SSH 地址均属于同一预期仓库。"""
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).parents[1] / "scripts" / "termux_server.sh"
    subprocess.run(["git", "init", "-b", "master", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", remote_url],
                   check=True)
    (tmp_path / "dirty.txt").write_text("local", encoding="utf-8")
    result = subprocess.run(["bash", str(script)],
                            env={**os.environ, "BWP_REPO_DIR": str(tmp_path)},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "未提交" in result.stderr
    assert "远端地址不符合预期" not in result.stderr


def test_reconnect_failure_budget_spans_websockets_and_blocks_valid_token(server, db):
    first, second, joined = _ws_room(db, started=True)
    first.ws.close()
    clients = [second]
    try:
        for attempt in range(5):
            client = WsClient()
            clients.append(client)
            client.send({"type": "join", "room_id": joined["room_id"],
                         "token": f"invalid-{attempt}"})
            assert client.recv_until("error")["reason"] == "重连令牌无效"

        sixth = WsClient()
        clients.append(sixth)
        sixth.send({"type": "join", "room_id": joined["room_id"], "token": "invalid-sixth"})
        assert sixth.recv_until("error")["reason"] == "重连尝试过于频繁，请稍后"

        valid = WsClient()
        clients.append(valid)
        valid.send({"type": "join", "room_id": joined["room_id"],
                    "token": joined["token"]})
        assert valid.recv_until("error")["reason"] == "重连尝试过于频繁，请稍后"
    finally:
        for client in clients:
            client.ws.close()


def test_reconnect_failure_budget_expires_and_success_preserves_window(db, monkeypatch):
    room = mk_room(db)
    conn = run(room.join(0, "甲", FakeWS(), _deck_code(db)))
    now = [1000.0]
    monkeypatch.setattr("server.room.time.monotonic", lambda: now[0])

    for _ in range(5):
        room.record_reconnect_failure()
    assert room.reconnect_throttled()
    now[0] += 60
    assert not room.reconnect_throttled()
    assert run(room.reconnect(conn.token, FakeWS())) is conn

    for _ in range(4):
        room.record_reconnect_failure()
    assert not room.reconnect_throttled()
    assert run(room.reconnect(conn.token, FakeWS())) is conn
    assert len(room._reconnect_failures) == 4
    room.record_reconnect_failure()
    assert room.reconnect_throttled()


def test_termux_chmod_failure_warns_and_continues(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).parents[1] / "scripts" / "termux_server.sh"
    subprocess.run(["git", "init", "-b", "master", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "https://github.com/Varisox137/BWPro.git"], check=True)
    wrapper = r'''
chmod() { return 1; }
git() {
    if [[ "$1" == "pull" ]]; then
        printf 'pull reached\n'
        return 1
    fi
    command git "$@"
}
export -f chmod git
exec bash "$1"
'''
    result = subprocess.run(
        ["bash", "-c", wrapper, "bash", str(script)],
        env={**os.environ, "BWP_REPO_DIR": str(tmp_path)},
        capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "警告：无法设置日志目录权限" in result.stderr
    assert "警告：无法设置 launcher 日志权限" in result.stderr
    assert "pull reached" in result.stdout


def test_uvicorn_uses_project_logging_without_tty_probe():
    """uvicorn 不再覆盖项目日志配置，避免 tee stdout 缺少 isatty。"""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "server" / "main.py").read_text(encoding="utf-8")
    assert "log_config=None" in source


def test_room_trace_logs_are_correlated_by_room_id_without_duplicates(db, caplog):
    async def go():
        room_a, _, _ = await _started_room(db)
        room_b, _, _ = await _started_room(db)
        room_a.id = "ROOM_A"
        room_b.id = "ROOM_B"
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="bwpro.battle"):
            room_a.game._trace("event", "房间甲事件", seq=11)
            room_b.game._trace("event", "房间乙事件", seq=22)
        records = [record for record in caplog.records
                   if record.name == "bwpro.battle" and "房间" in record.getMessage()
                   and ("房间甲事件" in record.getMessage()
                        or "房间乙事件" in record.getMessage())]
        assert len(records) == 2
        assert any("房间 ROOM_A" in record.getMessage()
                   and "房间甲事件" in record.getMessage() for record in records)
        assert any("房间 ROOM_B" in record.getMessage()
                   and "房间乙事件" in record.getMessage() for record in records)
        assert [entry["message"] for entry in room_a._trace_pending[-1:]] == ["房间甲事件"]
        assert [entry["message"] for entry in room_b._trace_pending[-1:]] == ["房间乙事件"]
        room_a._cancel_timer()
        room_b._cancel_timer()
    run(go())


def test_websocket_reconnect_and_reject_log_context_without_tokens(server, db, caplog):
    first, second, joined = _ws_room(db, started=True)
    first.ws.close()
    replacement = None
    invalid = None
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        invalid = WsClient()
        invalid.send({"type": "join", "room_id": joined["room_id"],
                      "token": "invalid-secret-token"})
        assert invalid.recv_until("error")["reason"] == "重连令牌无效"
        assert "房间=- 座位=- 原因=重连令牌无效" in caplog.text
        assert "invalid-secret-token" not in caplog.text

        replacement = WsClient()
        replacement.send({"type": "join", "room_id": joined["room_id"],
                          "token": joined["token"]})
        assert replacement.recv_until("joined")["seat"] == 0
        assert f"重连成功：房间={joined['room_id']} 座位=0" in caplog.text
        assert joined["token"] not in caplog.text

        replacement.send({"type": "ready"})
        replacement.send({"type": "create", "deck_code": _deck_code(db)})
        assert replacement.recv_until("error")["reason"] == "当前连接已加入房间"
        assert (f"房间={joined['room_id']} 座位=0 "
                "原因=当前连接已加入房间") in caplog.text
    for client in (invalid, replacement, second):
        client.ws.close()


def test_room_sends_opponent_cardback_on_broadcast_and_resync(db):
    async def go():
        room = mk_room(db)
        ws0, ws1 = FakeWS(), FakeWS()
        await room.join(0, "甲", ws0, _deck_code(db), cardback="月明风清")
        await room.join(1, "乙", ws1, _deck_code(db), cardback="三途花境")
        await room.start_game()
        first0 = next(msg for msg in ws0.messages if msg["type"] == "state")
        first1 = next(msg for msg in ws1.messages if msg["type"] == "state")
        assert first0["opponent_cardback"] == "三途花境"
        assert first1["opponent_cardback"] == "月明风清"
        await room.resync(room.conns[0])
        assert ws0.messages[-1]["opponent_cardback"] == "三途花境"
        room._cancel_timer()
    run(go())


def test_cardback_snapshot_ignores_reconnect_and_updates_on_new_join(db):
    async def go():
        room = mk_room(db)
        ws0, ws1 = FakeWS(), FakeWS()
        conn = await room.join(0, "甲", ws0, _deck_code(db), cardback="月明风清")
        await room.join(1, "乙", ws1, _deck_code(db), cardback="三途花境")
        await room.start_game()

        await room.reconnect(conn.token, FakeWS())
        await room.resync(room.conns[1])
        assert ws1.messages[-1]["opponent_cardback"] == "月明风清"
        room._cancel_timer()

        next_room = Room("NEXT01", db, rng=random.Random(1))
        next_ws0, next_ws1 = FakeWS(), FakeWS()
        await next_room.join(0, "甲", next_ws0, _deck_code(db), cardback="金鱼姬")
        await next_room.join(1, "乙", next_ws1, _deck_code(db), cardback="三途花境")
        await next_room.start_game()
        state = next(msg for msg in next_ws1.messages if msg["type"] == "state")
        assert state["opponent_cardback"] == "金鱼姬"
        next_room._cancel_timer()
    run(go())


def test_websocket_hello_logs_validated_client_ip(server, db, capsys):
    first, joined = _ws_create_room(db, "甲", client_ip="192.0.2.8")
    second = WsClient()
    second.send({"type": "join", "room_id": joined["room_id"], "name": "乙",
                 "deck_code": _deck_code(db), "client_ip": "2001:db8::8"})
    assert second.recv_until("joined")["type"] == "joined"
    output = capsys.readouterr().out
    assert f"{joined['room_id']}] 甲（127.0.0.1，自报 192.0.2.8）创建房间" in output
    assert f"{joined['room_id']}] 乙（127.0.0.1，自报 2001:db8::8）加入房间" in output
    first.ws.close()
    second.ws.close()


@pytest.mark.parametrize("value", ["not-an-ip", "1" * 65, 123])
def test_websocket_rejects_invalid_client_ip(server, db, value):
    client = WsClient()
    client.send({"type": "create", "name": "甲", "deck_code": _deck_code(db),
                 "client_ip": value})
    reply = client.recv_until("joined", "error")
    assert reply["type"] == "error" and "client_ip" in reply["reason"]
    client.ws.close()
