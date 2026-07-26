"""RoomManager：内存房间表（创建/加入/查询/回收）。无持久化，无登录态。"""
from __future__ import annotations

import random

from server.room import Room, new_room_id


class RoomManager:
    def __init__(self, db, *, turn_timeout: float = 120.0,
                 mulligan_timeout: float = 30.0) -> None:
        self.db = db
        self.turn_timeout = turn_timeout
        self.mulligan_timeout = mulligan_timeout
        self.rooms: dict[str, Room] = {}
        self._rng = random.Random()

    def create(self, *, debug: bool = False) -> Room:
        room_id = new_room_id(self._rng)
        while room_id in self.rooms:
            room_id = new_room_id(self._rng)
        room = Room(room_id, self.db, debug=debug,
                    turn_timeout=self.turn_timeout,
                    mulligan_timeout=self.mulligan_timeout)
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
