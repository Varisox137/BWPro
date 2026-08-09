"""RoomManager：内存房间表（创建/加入/查询/回收）。无持久化，无登录态。"""
from __future__ import annotations

import asyncio
import random
import re
import time

from server.room import Room, new_room_id

# 自建房间代码格式：6 位大小写字母/数字（随机分配的房间代码沿用 ROOM_ID_ALPHABET
# 子集，自建代码允许全字符集，大小写敏感）
ROOM_ID_RE = re.compile(r"^[A-Za-z0-9]{6}$")

LOBBY_IDLE_TIMEOUT = 600.0  # 未开局房间无人员变动（进房/重连/退房）的自动解散时限（秒）
WATCHDOG_INTERVAL = 30.0  # 看门狗扫描间隔（秒）


class RoomManager:
    def __init__(self, db, *, turn_timeout: float = 120.0,
                 mulligan_timeout: float = 30.0, starting_timeout: float = 3.0,
                 max_rooms: int = 1000,
                 lobby_idle_timeout: float = LOBBY_IDLE_TIMEOUT) -> None:
        self.db = db
        self.turn_timeout = turn_timeout
        self.mulligan_timeout = mulligan_timeout
        self.starting_timeout = starting_timeout
        self.max_rooms = max_rooms
        self.lobby_idle_timeout = lobby_idle_timeout
        self.rooms: dict[str, Room] = {}
        self._rng = random.Random()

    def create(self, *, debug: bool = False, room_id: str | None = None,
               env_date: int | None = None, mode: str = "standard") -> Room:
        """创建房间：room_id 为空随机分配；指定时须满足 6 位字母数字且不冲突。
        mode ∈ {standard, free}：standard=固定标准环境（最新数据，env_date 强制
        None 且不可更改）；free=自由模式，env_date 指定初始环境（None = 最新）。"""
        if mode not in ("standard", "free"):
            raise ValueError(f"未知对局模式 {mode!r}（须为 standard/free）")
        if mode == "standard":
            env_date = None
        if len(self.rooms) >= self.max_rooms:
            raise ValueError("服务器房间数已达上限，请稍后再试")
        if room_id:
            if not ROOM_ID_RE.match(room_id):
                raise ValueError("房间代码须为 6 位大小写字母或数字")
            if room_id in self.rooms:
                raise ValueError(f"房间代码 {room_id} 已被占用")
        else:
            room_id = new_room_id(self._rng)
            while room_id in self.rooms:
                room_id = new_room_id(self._rng)
        room = Room(room_id, self.db, debug=debug,
                    turn_timeout=self.turn_timeout,
                    mulligan_timeout=self.mulligan_timeout,
                    starting_timeout=self.starting_timeout,
                    env_date=env_date, mode=mode)
        self.rooms[room_id] = room
        return room

    def get(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def remove(self, room_id: str) -> None:
        self.rooms.pop(room_id, None)

    def sweep(self) -> None:
        """回收已被遗弃（双方断线）的房间。"""
        for room_id in [rid for rid, r in self.rooms.items() if r.abandoned]:
            self.remove(room_id)

    async def dissolve_idle(self) -> list[str]:
        """看门狗扫描：解散超过 lobby_idle_timeout 秒无人员变动的房间，返回被解散的
        房间 id 列表。人员变动 = 玩家进房/重连回房/主动退房（Room.last_activity）。
        适用范围仅限未开局房间（lobby/starting 等未进入对局的状态）：已开局对局
        超 10 分钟是常态，不适用本规则，其清理由 abandoned（双方断线）等既有
        机制负责。"""
        now = time.time()
        doomed = [rid for rid, r in self.rooms.items()
                  if r.game is None and now - r.last_activity > self.lobby_idle_timeout]
        for rid in doomed:
            await self.rooms[rid].dissolve()
            self.remove(rid)
        return doomed

    async def watchdog_loop(self, interval: float = WATCHDOG_INTERVAL) -> None:
        """看门狗后台任务：按 interval 周期扫描解散长期无人员变动的未开局房间
        （应用启动时挂载为 asyncio 任务，关停时取消）。"""
        while True:
            await asyncio.sleep(interval)
            await self.dissolve_idle()
