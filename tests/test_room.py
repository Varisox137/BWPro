"""联机房间（server/room.py + server/manager.py）单元测试：假 WebSocket + asyncio。"""
import asyncio
import json
import random
import time

import pytest

from server.manager import RoomManager
from server.room import Room

from tests import factories as F


class FakeWS:
    """收集 send_text 内容的假 WebSocket。"""

    def __init__(self):
        self.messages: list[dict] = []

    async def send_text(self, text: str):
        self.messages.append(json.loads(text))

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


def run(coro):
    return asyncio.run(coro)


def mk_room(db, **kw) -> Room:
    kw.setdefault("rng", random.Random(1))
    return Room("TEST01", db, **kw)


async def _started_room(db, **kw):
    """两名玩家就位并已开局的 (room, ws0, ws1)。"""
    room = mk_room(db, **kw)
    ws0, ws1 = FakeWS(), FakeWS()
    await room.join(0, "甲", ws0, None)
    await room.join(1, "乙", ws1, None)
    await room.start_if_ready()
    return room, ws0, ws1


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


def test_illegal_cmd_returns_error(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        n = len(ws0.messages)
        n1 = len(ws1.messages)
        await room.handle_cmd(0, {"op": "end_turn"})  # 调度阶段不可用
        assert ws0.messages[-1]["type"] == "error"
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


# ---------- 断线重连 ----------

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


# ---------- 计时器 ----------

def test_mulligan_timeout_forces_ready(db):
    async def go():
        room, _, _ = await _started_room(db, mulligan_timeout=0.1)
        g = room.game
        assert g.state.phase == "mulligan"
        assert room.current_timer_key() == ("mulligan", 0)
        await asyncio.sleep(0.15)
        assert g.state.players[0].mulligan_done
        assert not g.state.players[1].mulligan_done
        assert room.current_timer_key() == ("mulligan", 1)
        await asyncio.sleep(0.15)
        assert g.state.players[1].mulligan_done
        assert g.state.phase != "mulligan"  # 已进入对战
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
