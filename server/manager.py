"""RoomManager：内存房间表（创建/加入/查询/回收）。无持久化，无登录态。"""
from __future__ import annotations

import random
import re

from server.room import Room, new_room_id

# 自建房间代码格式：6 位大小写字母/数字（随机分配的房间代码沿用 ROOM_ID_ALPHABET
# 子集，自建代码允许全字符集，大小写敏感）
ROOM_ID_RE = re.compile(r"^[A-Za-z0-9]{6}$")


class RoomManager:
    def __init__(self, db, *, turn_timeout: float = 120.0,
                 mulligan_timeout: float = 30.0, starting_timeout: float = 3.0,
                 max_rooms: int = 1000) -> None:
        self.db = db
        self.turn_timeout = turn_timeout
        self.mulligan_timeout = mulligan_timeout
        self.starting_timeout = starting_timeout
        self.max_rooms = max_rooms
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
