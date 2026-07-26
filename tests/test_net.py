"""联机端到端测试：线程内起 uvicorn + 两个 websockets.sync 客户端，
跑完 创建/加入/调度/升级/出牌回合 全流程。端口不可用时跳过。"""
import asyncio
import json
import threading

import pytest

from server.main import create_app
from server.manager import RoomManager

from tests import factories as F

PORT = 8377
URL = f"ws://127.0.0.1:{PORT}/ws"


class WsClient:
    def __init__(self):
        from websockets.sync.client import connect
        self.ws = connect(URL)

    def send(self, msg: dict):
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
    app = create_app(RoomManager(db))
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=lambda: asyncio.run(srv.serve()), daemon=True)
    t.start()
    for _ in range(50):  # 等服务就绪
        if srv.started:
            break
        import time
        time.sleep(0.1)
    if not srv.started:
        pytest.skip("无法启动本地测试服务端")
    yield srv
    srv.should_exit = True


def test_full_match_flow(server):
    a = WsClient()
    a.send({"type": "create", "name": "甲", "deck_code": None})
    ja = a.recv_until("joined", "error")
    assert ja["type"] == "joined"
    room_id, token_a = ja["room_id"], ja["token"]

    b = WsClient()
    b.send({"type": "join", "room_id": room_id, "name": "乙", "deck_code": None})
    jb = b.recv_until("joined")
    assert jb["type"] == "joined"

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
