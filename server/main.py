"""authoritative 联机服务端（FastAPI + WebSocket）。

运行：uv run python -m server.main [--host 0.0.0.0] [--port 1037]
      [--turn-timeout 120] [--mulligan-timeout 30] [--debug-console]

- 客户端只提交指令（与 client/cli.py 完全相同的 cmd dict 协议），服务端用
  core.engine.Game 校验、执行并广播新状态（server/room.py、server/manager.py）。
- 心跳使用 WS 协议层 ping/pong（uvicorn ws_ping_interval=10s）。
- --debug-console：服务端 stdin 接受 `list` 与 `<房间id> <debug 子命令> [参数...]`，
  直接进入指定对局执行 debug 指令（解析复用 client/cli.py 的 run_debug）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from db.loader import CardDatabase
from server import protocol
from server.manager import RoomManager

# 输入字段长度上限（基本防护：拒绝超长/异常输入）
MAX_NAME = 32
MAX_ROOM_ID = 16
MAX_TOKEN = 64
MAX_DECK_CODE = 1024


class RateLimiter:
    """每连接每秒最多 rate 条消息（令牌窗：每秒重置计数）。"""

    def __init__(self, rate: int = 10) -> None:
        self.rate = rate
        self.count = 0
        self.window = 0.0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self.window >= 1.0:
            self.window = now
            self.count = 0
        self.count += 1
        return self.count <= self.rate


def _text(msg: dict, key: str, maxlen: int) -> str | None:
    """取字符串字段并限制长度；非字符串或超长抛 ValueError。"""
    v = msg.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > maxlen:
        raise ValueError(f"字段 {key} 非法")
    return v


CLIENT_UA = "BWPro-CLI"  # 客户端握手 User-Agent 前缀（软门槛：挡浏览器/扫描器，非访问凭证）


def create_app(manager: RoomManager, *, rate_limit: int = 10,
               require_client_ua: bool = True) -> FastAPI:
    app = FastAPI(title="BWPro 联机服务端")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # 软门槛：User-Agent 不以 BWPro-CLI 开头的连接在握手阶段直接拒绝（403）。
        # 注意这只是噪声过滤，header 可伪造，真正的访问控制要靠访问口令。
        if require_client_ua and not ws.headers.get("user-agent", "").startswith(CLIENT_UA):
            await ws.close(code=1008)
            return
        await ws.accept()
        limiter = RateLimiter(rate_limit)
        room = None
        conn = None

        async def reject(reason: str) -> None:
            await ws.send_text(json.dumps(protocol.error(reason), ensure_ascii=False))

        try:
            while True:
                raw = await ws.receive_text()
                if not limiter.allow():
                    await reject("消息过于频繁，请稍候")
                    continue
                try:
                    msg = protocol.parse_client_message(raw)
                except ValueError as e:
                    await reject(str(e))
                    continue
                t = msg["type"]
                if t == "pong":
                    continue
                if t == "create":
                    try:
                        name = _text(msg, "name", MAX_NAME) or "玩家A"
                        deck_code = _text(msg, "deck_code", MAX_DECK_CODE)
                        room = manager.create(debug=bool(msg.get("debug")))
                        conn = await room.join(0, name, ws, deck_code)
                    except ValueError as e:
                        if room is not None:
                            manager.remove(room.id)
                            room = None
                        await reject(str(e))
                        continue
                    await conn.send(protocol.joined(room.id, conn.token, 0,
                                                    debug=room.debug))
                    await room.start_if_ready()
                elif t == "join":
                    try:
                        room_id = _text(msg, "room_id", MAX_ROOM_ID) or ""
                        token = _text(msg, "token", MAX_TOKEN)
                        name = _text(msg, "name", MAX_NAME) or "玩家B"
                        deck_code = _text(msg, "deck_code", MAX_DECK_CODE)
                    except ValueError as e:
                        await reject(str(e))
                        continue
                    room = manager.get(room_id)
                    if room is None:
                        await reject("房间不存在")
                        continue
                    if token:  # 断线重连
                        conn = await room.reconnect(token, ws)
                        if conn is None:
                            await reject("重连令牌无效")
                            continue
                        await conn.send(protocol.joined(
                            room.id, conn.token, conn.seat,
                            player_index=room.seat_to_player[conn.seat],
                            debug=room.debug))
                        if room.game is not None:
                            await room.resync(conn)  # 全量补发（不动广播游标）
                        continue
                    try:
                        conn = await room.join(1, name, ws, deck_code)
                    except ValueError as e:
                        await reject(str(e))
                        continue
                    await conn.send(protocol.joined(room.id, conn.token, 1,
                                                    debug=room.debug))
                    await room.start_if_ready()
                elif t == "cmd":
                    if room is None or conn is None:
                        await reject("尚未加入房间")
                        continue
                    await room.handle_cmd(conn.seat, msg["cmd"])
        except WebSocketDisconnect:
            pass
        finally:
            if room is not None and conn is not None:
                room.disconnect(conn)
                manager.sweep()

    return app


def _debug_console(manager: RoomManager, loop: asyncio.AbstractEventLoop) -> None:
    """stdin 线程：list 列出房间；<房间id> <debug 子命令> [参数...] 进入对局 debug。"""
    from client.cli import run_debug  # 延迟导入：解析复用 CLI 的 debug 指令解析

    print("[debug-console] 输入 list 查看房间；<房间id> <debug 子命令> 执行调试")
    while True:
        try:
            line = input()
        except EOFError:
            return
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "list":
            for rid, r in manager.rooms.items():
                st = r.game.state if r.game else None
                phase = st.phase if st else "等待玩家"
                print(f"  {rid}: {phase}"
                      f"（{'/'.join(c.name for c in r.conns if c)}）")
            continue
        room = manager.get(parts[0])
        if room is None or room.game is None:
            print("房间不存在或对局未开始")
            continue
        try:
            dcmd = run_debug(room.game, parts[1:])
        except ValueError as e:
            print(f"指令有误: {e}")
            continue
        if dcmd:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(room.debug_apply(dcmd)))


def main() -> None:
    parser = argparse.ArgumentParser(description="BWPro 联机服务端")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址；对外服务（含内网穿透）用 0.0.0.0")
    parser.add_argument("--port", type=int, default=1037)
    parser.add_argument("--turn-timeout", type=float, default=120.0,
                        help="回合限时（秒，含升级阶段）")
    parser.add_argument("--mulligan-timeout", type=float, default=30.0,
                        help="起始手牌调度限时（秒，每人）")
    parser.add_argument("--rate-limit", type=int, default=10,
                        help="每连接每秒最大消息数")
    parser.add_argument("--max-rooms", type=int, default=1000,
                        help="同时存在的最大房间数")
    parser.add_argument("--ssl-certfile", default=None,
                        help="TLS 证书路径（配置后对外为 wss://）")
    parser.add_argument("--ssl-keyfile", default=None, help="TLS 私钥路径")
    parser.add_argument("--debug-console", action="store_true",
                        help="开启服务端 debug 控制台（stdin）")
    parser.add_argument("--no-require-ua", action="store_true",
                        help="关闭 User-Agent 软门槛（默认要求 BWPro-CLI 前缀）")
    args = parser.parse_args()

    import uvicorn

    db = CardDatabase.load()
    manager = RoomManager(db, turn_timeout=args.turn_timeout,
                          mulligan_timeout=args.mulligan_timeout,
                          max_rooms=args.max_rooms)
    app = create_app(manager, rate_limit=args.rate_limit,
                     require_client_ua=not args.no_require_ua)
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            ws_ping_interval=10, ws_ping_timeout=5,
                            ws_max_size=1024 * 1024,  # 单条消息最大 1MB
                            ssl_certfile=args.ssl_certfile,
                            ssl_keyfile=args.ssl_keyfile)
    server = uvicorn.Server(config)
    if args.debug_console:
        loop = asyncio.new_event_loop()

        async def _serve() -> None:
            await server.serve()

        threading.Thread(target=_debug_console, args=(manager, loop),
                         daemon=True).start()
        loop.run_until_complete(_serve())
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
