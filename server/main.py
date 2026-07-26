"""authoritative 联机服务端（FastAPI + WebSocket）。

运行：uv run python -m server.main [--host 0.0.0.0] [--port 8000]
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from db.loader import CardDatabase
from server import protocol
from server.manager import RoomManager


def create_app(manager: RoomManager) -> FastAPI:
    app = FastAPI(title="BWPro 联机服务端")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        room = None
        conn = None
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = protocol.parse_client_message(raw)
                except ValueError as e:
                    await ws.send_text(json.dumps(
                        protocol.error(str(e)), ensure_ascii=False))
                    continue
                t = msg["type"]
                if t == "pong":
                    continue
                if t == "create":
                    room = manager.create(debug=bool(msg.get("debug")))
                    try:
                        conn = await room.join(0, msg.get("name") or "玩家A", ws,
                                               msg.get("deck_code"))
                    except ValueError as e:
                        manager.remove(room.id)
                        room = None
                        await ws.send_text(json.dumps(
                            protocol.error(str(e)), ensure_ascii=False))
                        continue
                    await conn.send(protocol.joined(room.id, conn.token, 0,
                                                    debug=room.debug))
                    await room.start_if_ready()
                elif t == "join":
                    room = manager.get(msg.get("room_id") or "")
                    if room is None:
                        await ws.send_text(json.dumps(
                            protocol.error("房间不存在"), ensure_ascii=False))
                        continue
                    token = msg.get("token")
                    if token:  # 断线重连
                        conn = await room.reconnect(token, ws)
                        if conn is None:
                            await ws.send_text(json.dumps(
                                protocol.error("重连令牌无效"), ensure_ascii=False))
                            continue
                        await conn.send(protocol.joined(
                            room.id, conn.token, conn.seat,
                            player_index=room.seat_to_player[conn.seat],
                            debug=room.debug))
                        if room.game is not None:
                            await room.broadcast_state()
                        continue
                    try:
                        conn = await room.join(1, msg.get("name") or "玩家B", ws,
                                               msg.get("deck_code"))
                    except ValueError as e:
                        await ws.send_text(json.dumps(
                            protocol.error(str(e)), ensure_ascii=False))
                        continue
                    await conn.send(protocol.joined(room.id, conn.token, 1,
                                                    debug=room.debug))
                    await room.start_if_ready()
                elif t == "cmd":
                    if room is None or conn is None:
                        await ws.send_text(json.dumps(
                            protocol.error("尚未加入房间"), ensure_ascii=False))
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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--turn-timeout", type=float, default=120.0,
                        help="回合限时（秒，含升级阶段）")
    parser.add_argument("--mulligan-timeout", type=float, default=30.0,
                        help="起始手牌调度限时（秒，每人）")
    parser.add_argument("--debug-console", action="store_true",
                        help="开启服务端 debug 控制台（stdin）")
    args = parser.parse_args()

    import uvicorn

    db = CardDatabase.load()
    manager = RoomManager(db, turn_timeout=args.turn_timeout,
                          mulligan_timeout=args.mulligan_timeout)
    app = create_app(manager)
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            ws_ping_interval=10, ws_ping_timeout=5)
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
