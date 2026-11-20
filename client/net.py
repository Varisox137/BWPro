"""桌面联机客户端共用的网络工具，不包含终端交互客户端。"""
from __future__ import annotations

import ipaddress
import re
import secrets
import time
from pathlib import Path
from urllib.request import Request, urlopen

CLIENT_ID = "BWPro-CLI/1.0"  # 服务端应用层客户端标识前缀（兼容既有协议）


def machine_id(path: Path | None = None) -> str:
    """返回本机持久的 32 位十六进制机器码，仅用于配合令牌和公网 IP 重连。"""
    path = path or Path.home() / ".bwpro" / "machine_id"
    try:
        stored = path.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[0-9a-f]{32}", stored):
            return stored
    except (OSError, UnicodeError):
        pass
    value = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(value + "\n", encoding="ascii")
        temporary.replace(path)
    except OSError:
        pass  # 无法落盘时仍可用于本次进程，不阻断联机
    return value


def display_server_url(raw: str) -> str:
    """联机地址输入框只显示 host[:port]，不显示协议与默认 /ws 路径。"""
    value = re.sub(r"^(?:wss?|https?)://", "", raw.strip())
    return value[:-3] if value.endswith("/ws") else value


def normalize_server_url(raw: str) -> str:
    """把用户输入规范化为 ws(s)://host[:port]/ws；已带路径时保留。"""
    s = raw.strip()
    if s.startswith("https://"):
        s = "wss://" + s[len("https://"):]
    elif s.startswith("http://"):
        s = "ws://" + s[len("http://"):]
    if not s.startswith(("ws://", "wss://")):
        host = s.split("/", 1)[0]
        if host in ("127.0.0.1", "localhost"):
            s = "ws://" + s + ":1037"
        else:
            s = ("ws://" if ":" in host else "wss://") + s
    if "/" not in s.split("://", 1)[1]:
        s = s + "/ws"
    return s


def public_ip(timeout: float = 3.0) -> str:
    """查询客户端公网 IP；拒绝内网地址，主服务失败时切换备用服务。"""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            request = Request(url, headers={"User-Agent": "BWPro/0.3"})
            with urlopen(request, timeout=timeout) as response:
                text = response.read(65).decode("ascii").strip()
            address = ipaddress.ip_address(text)
            if address.is_global:
                return str(address)
        except (OSError, ValueError, UnicodeError):
            pass
    return ""


def _open_ws(server_url: str, retries: int = 3, open_timeout: float = 5.0):
    """建立带客户端标识的 WS 连接；穿透提示页按 1s 间隔重试。"""
    from websockets.sync.client import connect
    for attempt in range(retries):
        try:
            return connect(server_url, open_timeout=open_timeout,
                           additional_headers={"User-Agent": CLIENT_ID})
        except Exception:
            if attempt + 1 >= retries:
                raise
            time.sleep(1.0)


def probe_connection(server_url: str, retries: int = 3) -> str | None:
    """试连服务器（仅握手）：成功返回 None，失败返回错误信息。"""
    try:
        with _open_ws(server_url, retries=retries):
            return None
    except Exception as e:
        msg = str(e)
        if "HTTP 200" in msg:
            msg += "；对端以普通网页应答，可能被穿透服务拦截/映射未生效"
        return msg


def hello_metadata(client_ip: str | None = None, machine: str | None = None) -> dict:
    metadata = {"client": CLIENT_ID}
    if client_ip:
        metadata["client_ip"] = client_ip
    if machine:
        metadata["machine_id"] = machine
    return metadata
