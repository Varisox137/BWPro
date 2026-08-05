"""server 层测试：联机协议消息构造/解析（原 test_protocol.py）
+ 服务端入口限流与输入上限（原 test_server_main.py）
+ 联机房间单元测试：假 WebSocket + asyncio（原 test_room.py）
+ 联机端到端：线程内 uvicorn + 两个 websockets.sync 客户端全流程（原 test_net.py，
端口不可用时跳过）。
"""
import asyncio
import json
import random
import threading
import time

import pytest

from server import protocol
from server.main import RateLimiter, _text, create_app
from server.manager import RoomManager
from server.room import Room

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

    async def send_text(self, text: str):
        self.messages.append(json.loads(text))

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
        assert g._open_deck_top_pick(0, 2, 1, False)  # 青灯夜谈式挂起（无续块）
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


def test_reconnect_resync_pending_choice(db):
    """结算中交互选择期间断线重连：resync 全量 state 的 pending_choice 对选择方
    保留真实 options（客户端据此提示作答），并附带当前计时器。"""
    async def go():
        room, _, _ = await _started_room(db, turn_timeout=60)
        g = room.game
        for pi in (0, 1):
            g.apply({"op": "ready", "player": pi})
        assert g._open_deck_top_pick(0, 2, 1, False)
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


def test_full_match_flow(server, db):
    a = WsClient()
    a.send({"type": "create", "name": "甲", "deck_code": _deck_code(db)})
    ja = a.recv_until("joined", "error")
    assert ja["type"] == "joined"
    room_id, token_a = ja["room_id"], ja["token"]

    b = WsClient()
    b.send({"type": "join", "room_id": room_id, "name": "乙",
            "deck_code": _deck_code(db)})
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

    # 断线重连：凭房间 id + 令牌恢复
    a.ws.close()
    a2 = WsClient()
    a2.send({"type": "join", "room_id": room_id, "token": token_a})
    ja2 = a2.recv_until("joined", "error")
    assert ja2["type"] == "joined"
    st2 = a2.recv_until("state")["payload"]
    assert st2["turn"] == st["turn"]
    a2.ws.close()
    b.ws.close()


def test_http_probe_gets_403_no_server_header(server):
    """非 WS 的 HTTP 探针（无 UA 可直达服务端的场景）：任意路径一律 403 空体，
    不用框架默认 404；且不下发 server 响应头（不暴露 uvicorn 指纹）。"""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    for path in ("/", "/ws", "/admin"):
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
    """已展示脱敏例外（第十七阶段）：对手手牌中 mods.revealed 的卡保留真实内容，
    未展示手牌与牌库仍占位隐藏；原始 payload 不被修改。"""
    from server.room import _HIDDEN_CARD, sanitize_state
    payload = {"players": [
        {"zones": {"hand": [
            {"uid": 1, "id": 10010101, "mods": {"revealed": True}, "hand_seq": 1},
            {"uid": 2, "id": 10010102, "mods": {}, "hand_seq": 2},
        ], "deck": [{"uid": 3, "id": 10010103, "mods": {}, "hand_seq": 0}]}},
        {"zones": {"hand": [], "deck": []}},
    ]}
    view = sanitize_state(payload, 1)  # viewer=1 → 对手为 players[0]
    hand = view["players"][0]["zones"]["hand"]
    assert hand[0]["id"] == 10010101 and hand[0]["uid"] == 1   # 已展示：保留真实内容
    assert hand[1] == _HIDDEN_CARD                             # 未展示：占位隐藏
    assert view["players"][0]["zones"]["deck"] == [dict(_HIDDEN_CARD)]
    assert payload["players"][0]["zones"]["hand"][1]["id"] == 10010102  # 原状态不变
