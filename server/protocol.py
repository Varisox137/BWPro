"""联机协议：WebSocket JSON 消息信封。

客户端 → 服务端：create / join / cmd / pong
服务端 → 客户端：joined / state / log / error / game_over / notice / ping

所有消息均为 JSON object，必带 "type" 字段。游戏指令复用 core.engine.Game.apply
的 cmd dict 协议（{"op": ...}），原样嵌在 {"type": "cmd", "cmd": {...}} 中。
心跳使用 WS 协议层 ping/pong（uvicorn ws_ping_interval=10s），应用层不另发。
"""
from __future__ import annotations

import json
from typing import Any

# 客户端消息类型
CLIENT_TYPES = {"create", "join", "cmd", "pong"}


def parse_client_message(raw: str | bytes) -> dict[str, Any]:
    """解析并粗校验一条客户端消息；非法时抛 ValueError。"""
    try:
        msg = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"消息不是合法 JSON（{e}）") from e
    if not isinstance(msg, dict) or msg.get("type") not in CLIENT_TYPES:
        raise ValueError("未知消息类型")
    if msg["type"] == "cmd" and not isinstance(msg.get("cmd"), dict):
        raise ValueError("cmd 消息缺少 cmd 对象")
    return msg


# ---------- 服务端消息构造 ----------

def joined(room_id: str, token: str, seat: int, **extra) -> dict:
    return {"type": "joined", "room_id": room_id, "token": token, "seat": seat, **extra}


def start(player_index: int, opponent: str, you_first: bool) -> dict:
    """两人就位、随机先手已确定：告知客户端自己的 players 下标。"""
    return {"type": "start", "player_index": player_index,
            "opponent": opponent, "you_first": you_first}


def state(payload: dict, log: list[str]) -> dict:
    """完整对局状态 + 自上次以来的新增日志。"""
    return {"type": "state", "payload": payload, "log": log}


def error(reason: str) -> dict:
    return {"type": "error", "reason": reason}


def notice(text: str) -> dict:
    return {"type": "notice", "text": text}


def game_over(winner: int | None, reason: str = "") -> dict:
    return {"type": "game_over", "winner": winner, "reason": reason}
