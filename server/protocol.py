"""联机协议：WebSocket JSON 消息信封。

客户端 → 服务端：create / join / ready / leave / env / cmd / pong（create/join 需带
client 标识字段，服务端软门槛校验前缀 BWPro-CLI，见 server.main.CLIENT_UA；ready
为准备/取消准备切换，leave 离开房间——开局前准备阶段：双方都位后不计时，任一方
准备后对未准备方计 15s，双方准备后 3s 开始倒计时开局，期间可离开；env 为房主
在双方均未准备时更改对局环境（平衡性版本日期，date 缺省 = 最新；标准模式房间
不可更改），create 可带 env_date 指定初始环境与 mode 指定模式
（standard=固定标准环境，默认 / free=自由环境））
服务端 → 客户端：joined / lobby / starting / left / state / log / error / game_over /
notice / dissolved / ping

所有消息均为 JSON object，必带 "type" 字段。游戏指令复用 core.engine.Game.apply
的 cmd dict 协议（{"op": ...}），原样嵌在 {"type": "cmd", "cmd": {...}} 中。
心跳使用 WS 协议层 ping/pong（uvicorn ws_ping_interval=10s），应用层不另发。
"""
from __future__ import annotations

import json
from typing import Any

# 客户端消息类型
CLIENT_TYPES = {"create", "join", "ready", "leave", "env", "cmd", "pong"}


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


def lobby(ready: list[str], deadline: float | None,
          env_date: int | None = None, mode: str = "standard") -> dict:
    """双方都位、进入准备阶段：ready 为已准备玩家名列表（空 = 无人准备、不计时）；
    deadline 为未准备方自动准备的 unix 时刻（15s，仅一方已准备时非空）；
    env_date 为对局环境（平衡性版本日期；None = 最新数据，字段省略）；
    mode 为房间模式（standard=固定标准环境 / free=自由环境，房主可更换）。"""
    msg = {"type": "lobby", "ready": ready, "deadline": deadline, "mode": mode}
    if env_date is not None:
        msg["env_date"] = env_date
    return msg


def starting(deadline: float) -> dict:
    """双方均已准备：deadline 为对局正式开始的 unix 时刻（3s 倒计时）。"""
    return {"type": "starting", "deadline": deadline}


def left() -> dict:
    """确认离开房间（准备阶段主动 leave 的应答，服务端随后关闭连接）。"""
    return {"type": "left"}


def peer_left(name: str) -> dict:
    """准备阶段对手离开房间：客户端据此退回"等待对手加入"状态。"""
    return {"type": "peer_left", "name": name}


def start(player_index: int, opponent: str, you_first: bool,
          env_date: int | None = None, mode: str = "standard") -> dict:
    """两人就位、随机先手已确定：告知客户端自己的 players 下标与对局环境/模式。"""
    msg = {"type": "start", "player_index": player_index,
           "opponent": opponent, "you_first": you_first, "mode": mode}
    if env_date is not None:
        msg["env_date"] = env_date
    return msg


def state(payload: dict, log: list[str], timer: dict | None = None,
          settle: list[str] | None = None,
          timeline: list[dict] | None = None) -> dict:
    """完整对局状态 + 自上次以来的新增日志。
    timer 非空时附带 {"kind", "deadline"}（客户端倒计时显示用，旧客户端忽略该字段）。
    settle 非空时附带结算明细增量（旧客户端忽略）。
    timeline 非空时附带合并时间线增量（[{"k": "s"|"l", "m"}]，结算/叙事按真实发生
    顺序合流；客户端结算播放以此为准，log/settle 字段保留兼容）。"""
    msg = {"type": "state", "payload": payload, "log": log}
    if timer is not None:
        msg["timer"] = timer
    if settle:
        msg["settle"] = settle
    if timeline:
        msg["timeline"] = timeline
    return msg


def error(reason: str) -> dict:
    return {"type": "error", "reason": reason}


def notice(text: str) -> dict:
    return {"type": "notice", "text": text}


def game_over(winner: int | None, reason: str = "") -> dict:
    return {"type": "game_over", "winner": winner, "reason": reason}


def dissolved(reason: str) -> dict:
    """看门狗解散未开局房间（长时间无人员变动）：通知后服务端随即关闭连接。"""
    return {"type": "dissolved", "reason": reason}
