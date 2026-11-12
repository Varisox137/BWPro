"""authoritative 联机服务端（FastAPI + WebSocket）。

运行：uv run python -m server.main [--host 0.0.0.0] [--port 1037]
      [--turn-timeout 120] [--mulligan-timeout 30] [--debug-console]
      [--allow-debug-rooms] [--no-require-ua]

- 客户端只提交指令（与 client/cli.py 完全相同的 cmd dict 协议），服务端用
  core.engine.Game 校验、执行并广播新状态（server/room.py、server/manager.py）。
- 心跳使用 WS 协议层 ping/pong（uvicorn ws_ping_interval=10s）。
- --debug-console：服务端 stdin 接受 `list` 与 `<房间id> <debug 子命令> [参数...]`，
  直接进入指定对局执行 debug 指令（解析复用 client/cli.py 的 run_debug）。
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, StreamingResponse

from db.loader import CardDatabase
from server import protocol
from server.log_admin import LogAdminService
from server.manager import RoomManager

logger = logging.getLogger("bwpro.server")

# 输入字段长度上限（基本防护：拒绝超长/异常输入）
MAX_NAME = 32
MAX_ROOM_ID = 16
MAX_TOKEN = 64
MAX_DECK_CODE = 1024
MAX_CLIENT_IP = 64
MAX_CARDBACK = 64


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


def _player_name(msg: dict) -> str | None:
    name = _text(msg, "name", MAX_NAME)
    if name is not None and any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in name):
        raise ValueError("字段 name 非法")
    return name


def _reported_client_ip(msg: dict) -> str | None:
    value = _text(msg, "client_ip", MAX_CLIENT_IP)
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ValueError("字段 client_ip 非法") from None


CLIENT_UA = "BWPro-CLI"  # 客户端标识前缀（软门槛：挡浏览器/扫描器，非访问凭证）
AUTH_TIMEOUT = 300.0  # 连接后连续 5 分钟未创建/加入房间则断联

def _env_date(msg: dict, key: str) -> int | None:
    """解析 create/env 消息中的环境日期字段：缺省 None（最新）；
    非 int 或非法 8 位日期抛 ValueError。"""
    from db.schema import check_version_date
    v = msg.get(key)
    if v is None:
        return None
    if not isinstance(v, int):
        raise ValueError("环境日期须为 8 位数字日期（YYYYMMDD）")
    try:
        return check_version_date(v)
    except ValueError:
        raise ValueError("环境日期须为合法的 8 位日期（YYYYMMDD）") from None


def _client_ip(connection: WebSocket | Request) -> str:
    """提取真实来源 IP：穿透/反代边缘做 L7 代理时，TCP 对端永远是本机回环
    （客户端回连 127.0.0.1），真实 IP 只能由边缘透传在 X-Forwarded-For /
    X-Real-IP 头中；取 XFF 首项（原始客户端）。该值由边缘写入、可被伪造，
    仅作日志参考，不可作访问控制依据。"""
    xff = connection.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = connection.headers.get("x-real-ip")
    if real:
        return real.strip()
    return connection.client.host if connection.client else "unknown"


def create_app(manager: RoomManager, *, rate_limit: int = 10,
               require_client_ua: bool = True, allow_debug_rooms: bool = False,
               log_admin: LogAdminService | None = None) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        tasks = [asyncio.create_task(manager.watchdog_loop())]
        if log_admin is not None:
            tasks.append(asyncio.create_task(log_admin.rotation_loop()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="BWPro 联机服务端", lifespan=_lifespan)

    if log_admin is not None:
        service = log_admin

        async def require_log_admin_auth(request: Request) -> None:
            header = request.headers.get("Authorization")
            client = request.client.host if request.client else "unknown"
            if not service.authenticate(header, client):
                raise HTTPException(status_code=401)

        @app.exception_handler(401)
        async def log_admin_unauthorized(request: Request, exc: HTTPException):
            return PlainTextResponse("", status_code=401)

        @app.exception_handler(404)
        async def log_admin_not_found(request: Request, exc: HTTPException):
            return PlainTextResponse("", status_code=404)

        @app.get("/api/log-admin/logs", dependencies=[Depends(require_log_admin_auth)])
        async def list_log_admin_logs():
            return {"logs": service.list_logs()}

        @app.get("/api/log-admin/logs/{name}/preview",
                 dependencies=[Depends(require_log_admin_auth)])
        async def preview_log_admin_log(name: str):
            try:
                text, truncated = service.preview(name)
            except (ValueError, FileNotFoundError):
                raise HTTPException(status_code=404) from None
            return {"text": text, "truncated": truncated}

        @app.get("/api/log-admin/logs/{name}/download",
                 dependencies=[Depends(require_log_admin_auth)])
        async def download_log_admin_log(name: str):
            try:
                path = service.log_path(name)
                source = path.open("rb")
            except (ValueError, FileNotFoundError):
                raise HTTPException(status_code=404) from None

            def chunks():
                with source:
                    while chunk := source.read(64 * 1024):
                        yield chunk

            disposition = f"attachment; filename*=utf-8''{quote(path.name, safe='')}"
            return StreamingResponse(chunks(), headers={"Content-Disposition": disposition})

        @app.get("/api/log-admin/{path:path}",
                 dependencies=[Depends(require_log_admin_auth)])
        async def unknown_log_admin_path(path: str):
            raise HTTPException(status_code=404)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # 软门槛在应用层（不用握手 User-Agent header）：内网穿透等中间代理可能
        # 改写 HTTP 头，握手一律放行；create/join 消息必须带 client 字段且以
        # BWPro-CLI 开头，否则拒绝并断联；超时未完成合法 hello 的连接也会被关闭。
        await ws.accept()
        client_ip = _client_ip(ws)
        print(f"[连接] 来源 {client_ip}")
        limiter = RateLimiter(rate_limit)
        room = None
        conn = None

        async def reject(reason: str) -> None:
            logger.info("请求被拒绝：房间=%s 座位=%s 原因=%s",
                        room.id if room is not None else "-",
                        conn.seat if conn is not None else "-", reason)
            await ws.send_text(json.dumps(protocol.error(reason), ensure_ascii=False))

        async def _auth_watchdog() -> None:
            await asyncio.sleep(AUTH_TIMEOUT)
            if conn is None:
                await ws.close(code=1008)

        watchdog = asyncio.create_task(_auth_watchdog())

        def client_ok(msg: dict) -> bool:
            return not require_client_ua \
                or str(msg.get("client", "")).startswith(CLIENT_UA)

        def binding_valid() -> bool:
            return room is not None and conn is not None \
                and room.conns[conn.seat] is conn and conn.ws is ws

        def log_close(code: int, reason: str | None) -> None:
            logger.info("连接关闭：来源=%s 房间=%s 座位=%s 关闭码=%s 原因=%s",
                        client_ip, room.id if room is not None else "-",
                        conn.seat if conn is not None else "-", code, reason or "")

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
                if t in ("create", "join"):
                    if conn is not None:
                        await reject("当前连接已加入房间")
                        continue
                    if not client_ok(msg):
                        await reject("客户端标识无效，请使用 BWPro CLI 联机")
                        await ws.close(code=1008)
                        log_close(1008, "客户端标识无效")
                        return
                if t == "create":
                    if msg.get("debug") and not allow_debug_rooms:
                        await reject("服务器未开放 debug 对局")
                        continue
                    target_room = None
                    try:
                        name = _player_name(msg) or "玩家A"
                        deck_code = _text(msg, "deck_code", MAX_DECK_CODE)
                        want_id = _text(msg, "room_id", MAX_ROOM_ID) or None
                        env_date = _env_date(msg, "env_date")
                        mode = _text(msg, "mode", 10) or "standard"
                        reported_ip = _reported_client_ip(msg)
                        cardback = _text(msg, "cardback", MAX_CARDBACK)
                        target_room = manager.create(debug=bool(msg.get("debug")),
                                                     room_id=want_id, env_date=env_date,
                                                     mode=mode)
                        target_conn = await target_room.join(
                            0, name, ws, deck_code, cardback=cardback)
                    except ValueError as e:
                        if target_room is not None:
                            manager.remove(target_room.id)
                        await reject(str(e))
                        continue
                    room, conn = target_room, target_conn
                    source = client_ip + (f"，自报 {reported_ip}" if reported_ip else "")
                    print(f"[房间 {room.id}] {name}（{source}）创建房间"
                          f"{'（自建房码）' if want_id else ''}"
                          f"{'（debug 对局）' if room.debug else ''}"
                          f"（{room.mode} 模式"
                          f"{f'，环境 {env_date}' if env_date else ''}）", flush=True)
                    await conn.send(protocol.joined(room.id, conn.token, 0,
                                                    debug=room.debug))
                    await room.on_seat_filled()
                elif t == "join":
                    try:
                        room_id = _text(msg, "room_id", MAX_ROOM_ID) or ""
                        token = _text(msg, "token", MAX_TOKEN)
                        name = _player_name(msg) or "玩家B"
                        deck_code = _text(msg, "deck_code", MAX_DECK_CODE)
                        reported_ip = _reported_client_ip(msg)
                        cardback = _text(msg, "cardback", MAX_CARDBACK)
                    except ValueError as e:
                        await reject(str(e))
                        continue
                    target_room = manager.get(room_id)
                    if target_room is None:
                        await reject("房间不存在")
                        continue
                    if token:  # 断线重连
                        target_conn = await target_room.reconnect(token, ws)
                        if target_conn is None:
                            await reject("重连令牌无效")
                            continue
                        room, conn = target_room, target_conn
                        logger.info("重连成功：房间=%s 座位=%s", room.id, conn.seat)
                        await conn.send(protocol.joined(
                            room.id, conn.token, conn.seat,
                            player_index=room.seat_to_player[conn.seat],
                            debug=room.debug))
                        if room.game is not None:
                            await room.resync(conn)  # 全量补发（不动广播游标）
                        elif room.full:
                            # 准备阶段重连：补发当前 lobby 状态（准备名单/倒计时）
                            await conn.send(room.lobby_msg())
                        continue
                    try:
                        target_conn = await target_room.join(
                            1, name, ws, deck_code, cardback=cardback)
                    except ValueError as e:
                        await reject(str(e))
                        continue
                    room, conn = target_room, target_conn
                    source = client_ip + (f"，自报 {reported_ip}" if reported_ip else "")
                    print(f"[房间 {room.id}] {name}（{source}）加入房间", flush=True)
                    await conn.send(protocol.joined(room.id, conn.token, 1,
                                                    debug=room.debug))
                    await room.on_seat_filled()
                elif t == "ready":  # 准备阶段确认准备（双方都位后有效）
                    if not binding_valid():
                        await reject("尚未加入房间或连接已失效")
                        continue
                    await room.lobby_ready(conn.seat)
                elif t == "leave":  # 准备阶段主动离开：释放座位并断连
                    if binding_valid() and room.game is None:
                        await conn.send(protocol.left())
                        await room.lobby_leave(conn.seat)
                        if not any(room.conns):
                            manager.remove(room.id)
                        log_close(1000, "主动离开")
                        return
                    await reject("当前不能离开房间")
                    continue
                elif t == "env":  # 房主更改对局环境（仅双方均未准备时）
                    if not binding_valid():
                        await reject("尚未加入房间或连接已失效")
                        continue
                    try:
                        await room.set_env(conn.seat, _env_date(msg, "date"))
                    except ValueError as e:
                        await reject(str(e))
                        continue
                elif t == "cmd":
                    if not binding_valid():
                        await reject("尚未加入房间或连接已失效")
                        continue
                    await room.handle_cmd(conn.seat, msg["cmd"])
        except WebSocketDisconnect as error:
            log_close(error.code, error.reason)
        finally:
            watchdog.cancel()
            if binding_valid():
                if room.game is None:
                    # 准备阶段断线 = 离开房间：释放座位（无对局可重连）；
                    # 房间空无一人时直接回收
                    await room.lobby_leave(conn.seat)
                    if not any(room.conns):
                        print(f"[房间 {room.id}] 房间已空，回收", flush=True)
                        manager.remove(room.id)
                else:
                    room.disconnect(conn)
                    manager.sweep()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE",
                                            "PATCH", "HEAD", "OPTIONS"])
    async def http_catch_all() -> PlainTextResponse:
        # 非 WebSocket 的 HTTP 流量（浏览器/扫描器探针，含对 /ws 的普通 GET）：
        # 一律 403 空体——不用框架默认 404，避免暴露应用结构与框架指纹
        # （uvicorn 的 server 响应头在启动处一并关闭）
        return PlainTextResponse("", status_code=403)

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
    from core.logging_config import configure_logging
    log_path = configure_logging("server")
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
                        help="关闭客户端标识软门槛（默认要求 create/join 消息带 "
                             "BWPro-CLI 前缀的 client 字段）")
    parser.add_argument("--allow-debug-rooms", action="store_true",
                        help="允许客户端创建 debug 对局（公网部署勿开）")
    args = parser.parse_args()

    import uvicorn

    db = CardDatabase.load()
    manager = RoomManager(db, turn_timeout=args.turn_timeout,
                          mulligan_timeout=args.mulligan_timeout,
                          max_rooms=args.max_rooms)
    log_admin = LogAdminService(log_path.parent, log_path)
    app = create_app(manager, rate_limit=args.rate_limit,
                     require_client_ua=not args.no_require_ua,
                     allow_debug_rooms=args.allow_debug_rooms,
                     log_admin=log_admin)
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            log_config=None,  # 复用项目日志，避免 tee stdout 无 isatty
                            proxy_headers=False,  # 鉴权限流只认 socket 对端地址
                            ws_ping_interval=10, ws_ping_timeout=5,
                            ws_max_size=1024 * 1024,  # 单条消息最大 1MB
                            server_header=False,  # 不下发 server: uvicorn 响应头
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
