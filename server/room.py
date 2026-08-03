"""Room：一间对局房间 = 一个 authoritative Game + 两名玩家连接 + 计时器。

- 座位（seat）固定：创建者 0、加入者 1；seat→players 下标映射在开局时按随机先手确定。
- 计时器权威在服务端：并行调度全阶段共用 mulligan_timeout 秒（自调度阶段开始计，
  一方 ready/超时不重置另一方倒计时），每回合 turn_timeout 秒
  （含升级阶段）。游戏逻辑在事件循环内同步执行，计时器回调只能排在当前 apply
  返回后运行——天然满足"回合超时等结算完后立即结束回合"。
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import time
import uuid

from core.engine import Game, IllegalAction
from core.model import GameConfig
from core.setup import new_game
from db import deckcode
from server import protocol

ROOM_ID_ALPHABET = string.ascii_uppercase.replace("I", "").replace("O", "") + "23456789"


def new_room_id(rng: random.Random, length: int = 6) -> str:
    return "".join(rng.choices(ROOM_ID_ALPHABET, k=length))


# 占位卡：脱敏后用于替换对手手牌/牌库内容（数量公开，内容保密）
_HIDDEN_CARD = {"uid": 0, "id": 0, "mods": {}, "hand_seq": 0}


def sanitize_state(payload: dict, viewer: int) -> dict:
    """按视角脱敏完整状态：对手的手牌与牌库以占位卡替换（张数公开、内容保密），
    对手式神标记 secret 的延迟能力（会）抹除选择目标，防止修改客户端窥探。
    对手的剩余调度次数一并抹除（调度阶段信息隐藏；mulligan_done 状态保留）。
    墓地/计数器等在本游戏中为公开信息，保留。"""
    import copy

    payload = copy.deepcopy(payload)
    opponent = payload["players"][1 - viewer]
    zones = opponent.get("zones", {})
    for zone in ("hand", "deck"):
        if zone in zones:
            zones[zone] = [dict(_HIDDEN_CARD) for _ in zones[zone]]
    opponent["mulligans_left"] = 0  # 调度次数对对手隐藏
    for s in opponent.get("shikigami", []):
        for entry in s.get("delayed", []):
            if entry.get("secret"):
                entry["chosen"] = None
    pending = payload.get("pending_choice")
    if pending is not None and pending.get("player") != viewer:
        # 结算中交互选择（青灯夜谈）：可检视牌内容仅选择方可见，其余视角以占位 uid 抹除
        pending["options"] = [0] * len(pending.get("options", []))
    return payload


def _hide_mulligan_log(lines: list[str], st, viewer: int) -> list[str]:
    """调度阶段信息隐藏（协议层过滤，引擎/state 不动）：对方的调度行为行
    （"X 调度了一张手牌（剩余 N 次）"泄露调度次数）不发给 viewer；
    "X 完成调度"为无信息状态，保留。"""
    prefix = f"{st.players[1 - viewer].name} "
    return [l for l in lines
            if not (l.startswith(prefix) and "调度了一张手牌" in l)]


def _hide_mulligan_timeline(entries: list[dict], st, viewer: int) -> list[dict]:
    """合并时间线的调度信息隐藏：与 _hide_mulligan_log 同一谓词，只过滤叙事行
    （k="l"），结算行（k="s"）不含调度行为内容、全保留。"""
    prefix = f"{st.players[1 - viewer].name} "
    return [e for e in entries
            if not (e.get("k") == "l" and e.get("m", "").startswith(prefix)
                    and "调度了一张手牌" in e["m"])]


class Connection:
    """一名玩家的连接槽位（seat 固定，断线只换 ws 不换槽）。"""

    def __init__(self, seat: int, name: str, token: str | None = None) -> None:
        self.seat = seat
        self.name = name
        self.token = token or uuid.uuid4().hex
        self.ws = None  # 当前 WebSocket；断线时为 None

    @property
    def connected(self) -> bool:
        return self.ws is not None

    async def send(self, msg: dict) -> None:
        if self.ws is not None:
            try:
                await self.ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception:
                self.ws = None  # 发送失败视为断线


class Room:
    def __init__(self, room_id: str, db, *, debug: bool = False,
                 turn_timeout: float = 120.0, mulligan_timeout: float = 30.0,
                 ready_timeout: float = 15.0, starting_timeout: float = 3.0,
                 env_date: int | None = None,
                 rng: random.Random | None = None) -> None:
        self.id = room_id
        self.db = db
        self.env_date = env_date  # 对局环境（平衡性版本日期；None = 最新数据）
        self.env_db = db.at_date(env_date)  # 环境下解析后的数据库（构筑校验/开局/渲染用）
        self.debug = debug
        self.turn_timeout = turn_timeout
        self.mulligan_timeout = mulligan_timeout
        self.ready_timeout = ready_timeout  # 一方准备后，另一方自动准备的时长
        self.starting_timeout = starting_timeout  # 双方准备后到正式开局的倒计时
        self.rng = rng or random.Random()
        self.conns: list[Connection | None] = [None, None]
        self.ready_seats: set[int] = set()  # 准备阶段已确认准备的座位
        self._lobby_timer: asyncio.Task | None = None
        self._lobby_deadline: float | None = None
        # lobby 阶段状态机：idle（无人准备、不计时）→ countdown（一方准备，
        # 对未准备方计 ready_timeout 秒）→ starting（双方准备，starting_timeout 秒后开局）
        self._lobby_phase = "idle"
        self.game: Game | None = None
        self.seat_to_player = [0, 1]
        self._timer: asyncio.Task | None = None
        self._timer_key: tuple | None = None  # ("mulligan",)（并行共用）/ ("turn", 总回合数)
        self._timer_deadline: float | None = None  # 当前计时器的 unix 截止时刻（随 state 下发）
        self._sent_log = 0
        self._sent_settle = 0
        self._sent_timeline = 0
        self._over_sent = False

    # ---------- 加入 / 重连 / 断线 ----------

    @property
    def full(self) -> bool:
        return all(c is not None for c in self.conns)

    def seat_of_token(self, token: str) -> int | None:
        for c in self.conns:
            if c is not None and c.token == token:
                return c.seat
        return None

    def _parse_deck(self, deck_code: str | None) -> tuple[list[int], list[int]]:
        """解析卡组码（必须提供，无默认卡组；按房间环境 env_db 校验）；非法抛 ValueError。"""
        if not deck_code:
            raise ValueError("必须提供卡组码（无默认卡组）")
        try:
            return deckcode.deck_from_code(self.env_db, deck_code)
        except ValueError as e:
            if self.env_date is not None:
                raise ValueError(
                    f"卡组在当前环境（{self.env_date}）不可用：{e}") from e
            raise

    async def join(self, seat: int, name: str, ws, deck_code: str | None) -> Connection:
        """新玩家入座。卡组码非法时抛 ValueError（房间保留，可重新入座）。"""
        if self.game is not None:
            raise ValueError("对局已开始，不能加入")
        if self.conns[seat] is not None:
            raise ValueError("该座位已被占用")
        ids, cards = self._parse_deck(deck_code)  # 先校验再入座
        conn = Connection(seat, name)
        conn.ws = ws
        conn.deck = (ids, cards)
        self.conns[seat] = conn
        return conn

    async def reconnect(self, token: str, ws) -> Connection | None:
        seat = self.seat_of_token(token)
        if seat is None:
            return None
        conn = self.conns[seat]
        conn.ws = ws
        return conn

    def disconnect(self, conn: Connection) -> None:
        if conn.ws is not None:
            conn.ws = None  # 仅标记断线；对局与计时器继续

    @property
    def abandoned(self) -> bool:
        """可回收：两名玩家都曾入座且均已断线。"""
        return self.full and not any(c.connected for c in self.conns)

    # ---------- 开局前：准备阶段 ----------

    def _log(self, msg: str) -> None:
        print(f"[房间 {self.id}] {msg}", flush=True)

    def lobby_msg(self) -> dict:
        """当前 lobby 状态消息（广播与重连补发共用）：IDLE/STARTING 不带 deadline。"""
        ready = [self.conns[s].name for s in sorted(self.ready_seats) if self.conns[s]]
        deadline = self._lobby_deadline if self._lobby_phase == "countdown" else None
        return protocol.lobby(ready, deadline, env_date=self.env_date)

    async def set_env(self, seat: int, date: int | None) -> None:
        """更改对局环境（平衡性版本日期，None = 最新）：仅房主（seat 0）在双方
        均未准备时可用；更改后重新校验双方已入座卡组，任一不可用则拒绝。"""
        if self.game is not None or not self.full:
            return
        if seat != 0:
            await self.conns[seat].send(protocol.error("只有房主可以更改对局环境"))
            return
        if self.ready_seats:
            await self.conns[seat].send(
                protocol.error("双方均未准备时才能更改环境（请先取消准备）"))
            return
        from db.deck import validate_deck
        new_db = self.db.at_date(date)
        for c in self.conns:
            ids, cards = c.deck
            errors = validate_deck(new_db, ids, cards)
            if errors:
                await self.conns[seat].send(protocol.error(
                    f"{c.name} 的卡组在环境（{date}）下不可用：{'；'.join(errors)}"))
                return
        self.env_date = date
        self.env_db = new_db
        self._log(f"对局环境已更改为 {date or '最新'}")
        await self._broadcast(protocol.notice(
            f"对局环境已更改为 {date or '最新'}"))
        await self._broadcast(self.lobby_msg())

    async def on_seat_filled(self) -> None:
        """双方都位后进入准备阶段（不计时）：广播 lobby 状态，等待玩家准备。"""
        if self.game is not None or not self.full:
            return
        await self._broadcast(self.lobby_msg())
        self._log(f"双方都位（{self.conns[0].name} / {self.conns[1].name}），等待准备")

    async def _run_lobby_timer(self, phase: str, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        if self.game is not None or not self.full or self._lobby_phase != phase:
            return
        if phase == "countdown":
            # 未准备方超时 → 自动准备 → 进入开始倒计时（不直接开局）
            for seat in (0, 1):
                if seat not in self.ready_seats:
                    self.ready_seats.add(seat)
                    name = self.conns[seat].name
                    self._log(f"{name} 准备超时，自动准备")
                    await self._broadcast(protocol.notice(f"{name} 准备超时，自动准备"))
            await self._enter_starting()
        else:  # starting 倒计时结束，正式开局
            await self.start_game()

    def _start_lobby_timer(self, phase: str, seconds: float) -> None:
        self._cancel_lobby_timer()
        self._lobby_phase = phase
        self._lobby_deadline = time.time() + seconds
        self._lobby_timer = asyncio.ensure_future(self._run_lobby_timer(phase, seconds))

    def _cancel_lobby_timer(self) -> None:
        if self._lobby_timer is not None:
            self._lobby_timer.cancel()
            self._lobby_timer = None
        self._lobby_deadline = None
        self._lobby_phase = "idle"

    async def _enter_starting(self) -> None:
        """双方均已准备：进入开始倒计时（starting_timeout 秒后开局）。"""
        self._start_lobby_timer("starting", self.starting_timeout)
        self._log(f"双方已准备，{self.starting_timeout:.0f}s 后开局")
        await self._broadcast(protocol.starting(self._lobby_deadline))

    async def lobby_ready(self, seat: int) -> None:
        """准备/取消准备切换：
        - 未准备 → 准备：另一方也未准备则对其启动自动准备计时；双方均准备则进入开始倒计时。
        - 已准备 → 取消准备：回到双方未准备的无计时状态（开始倒计时中不可取消）。"""
        if self.game is not None or not self.full:
            return
        name = self.conns[seat].name
        if seat in self.ready_seats:
            if self._lobby_phase == "starting":
                await self.conns[seat].send(protocol.error("对局即将开始，不能取消准备"))
                return
            self.ready_seats.discard(seat)
            self._cancel_lobby_timer()
            self._log(f"{name} 取消准备")
            await self._broadcast(protocol.notice(f"{name} 取消准备"))
            await self._broadcast(self.lobby_msg())
            return
        self.ready_seats.add(seat)
        self._log(f"{name} 已准备（{len(self.ready_seats)}/2）")
        await self._broadcast(protocol.notice(
            f"{name} 已准备（{len(self.ready_seats)}/2）"))
        if len(self.ready_seats) == 2:
            await self._enter_starting()
        else:
            other = self.conns[1 - seat].name
            self._start_lobby_timer("countdown", self.ready_timeout)
            await self._broadcast(protocol.notice(
                f"{other} 请在 {self.ready_timeout:.0f}s 内准备，超时将自动准备"))
            await self._broadcast(self.lobby_msg())

    async def lobby_leave(self, seat: int) -> bool:
        """准备阶段主动离开或断线（任意 lobby 阶段均可，含开始倒计时）：
        清出座位并通知对手，房间回到等人状态。
        对局已开始则不允许（断线走断线重连通道）。"""
        if self.game is not None:
            return False
        conn = self.conns[seat]
        if conn is None:
            return False
        self.conns[seat] = None
        self.ready_seats.discard(seat)
        self._cancel_lobby_timer()
        self._log(f"{conn.name} 离开房间")
        peer = self.conns[1 - seat]
        if peer is not None:
            await peer.send(protocol.peer_left(conn.name))
        return True

    # ---------- 开局 ----------

    async def start_game(self) -> None:
        if self.game is not None or not self.full:
            return
        self._cancel_lobby_timer()
        first = self.rng.randint(0, 1)  # players[0] 恒为先手
        self.seat_to_player = [0, 1] if first == 0 else [1, 0]
        by_player = sorted(self.conns, key=lambda c: self.seat_to_player[c.seat])
        config = GameConfig(enable_debug_commands=self.debug)
        self.game = new_game(
            self.env_db,
            (by_player[0].name, *by_player[0].deck),
            (by_player[1].name, *by_player[1].deck),
            seed=self.rng.randrange(2**32),
            config=config,
            first=0,  # by_player 已按先手排序，无需 new_game 再换
        )
        env_note = f"，环境 {self.env_date}" if self.env_date else ""
        self._log(f"对战开始{env_note}：{by_player[0].name}（先手） vs {by_player[1].name}")
        for c in self.conns:
            await c.send(protocol.start(
                self.seat_to_player[c.seat],
                self.conns[1 - c.seat].name,
                self.seat_to_player[c.seat] == 0,
                env_date=self.env_date))
        self.reschedule_timer()
        await self.broadcast_state()

    # ---------- 指令 ----------

    async def handle_cmd(self, seat: int, cmd: dict) -> None:
        """处理一名玩家的游戏指令。cmd 中的 player 字段被强制改写为该座位对应的
        players 下标（mulligan/ready/debug 指令统一以此为准）。"""
        if self.game is None:
            await self.conns[seat].send(protocol.error("对局尚未开始"))
            return
        # 回合内操作只能由当前行动方发出（热坐共用终端无此问题，联机必须校验）
        if cmd.get("op") in ("play_card", "assault", "upgrade", "end_turn"):
            if self.game.state.active != self.seat_to_player[seat]:
                await self.conns[seat].send(protocol.error("还没到你的回合"))
                return
        cmd = dict(cmd)
        cmd["player"] = self.seat_to_player[seat]
        await self._apply_and_broadcast(seat, cmd)

    async def debug_apply(self, cmd: dict) -> None:
        """服务端控制台 debug 指令（不经座位改写，player 由指令自带/当前回合方）。"""
        if self.game is None:
            return
        await self._apply_and_broadcast(None, cmd)

    async def _apply_and_broadcast(self, seat: int | None, cmd: dict) -> None:
        try:
            self.game.apply(cmd)
        except IllegalAction as e:
            if seat is not None:
                await self.conns[seat].send(protocol.error(str(e)))
            return
        except Exception as e:  # 引擎异常：终止对局，避免房间卡死
            self._log(f"引擎异常，对局终止（{e}）")
            await self._broadcast(protocol.error(f"引擎异常，对局终止（{e}）"))
            await self._broadcast(protocol.game_over(None, "engine_error"))
            self._over_sent = True
            self._cancel_timer()
            return
        self.reschedule_timer()
        await self.broadcast_state()

    # ---------- 广播 ----------

    async def _broadcast(self, msg: dict) -> None:
        for c in self.conns:
            if c is not None:
                await c.send(msg)

    def _current_timer(self) -> dict | None:
        """当前有效计时器（kind/deadline），随 state 下发；无或已过期切换时为 None。"""
        key = self._timer_key
        if key is not None and self._timer_deadline is not None \
                and key == self.current_timer_key():
            return {"kind": key[0], "deadline": self._timer_deadline}
        return None

    async def broadcast_state(self) -> None:
        """向双方下发完整状态（按各自视角脱敏）+ 新增日志；对局结束时补发 game_over。
        附带当前计时器的 timer（kind/deadline），客户端状态栏倒计时显示用。"""
        st = self.game.state
        log = st.log[self._sent_log:]
        self._sent_log = len(st.log)
        settle = st.settle_log[self._sent_settle:]
        self._sent_settle = len(st.settle_log)
        timeline = st.timeline[self._sent_timeline:]
        self._sent_timeline = len(st.timeline)
        base = st.model_dump(mode="json")
        timer = self._current_timer()
        for c in self.conns:
            viewer = self.seat_to_player[c.seat]
            vlog = _hide_mulligan_log(log, st, viewer)  # 对方调度行为行不发给 viewer
            vtimeline = _hide_mulligan_timeline(timeline, st, viewer)  # 合流同样过滤
            await c.send(protocol.state(sanitize_state(base, viewer), vlog,
                                        timer=timer, settle=settle,
                                        timeline=vtimeline))
        if st.winner is not None and not self._over_sent:
            self._over_sent = True
            self._log(f"对战结束：{st.players[st.winner].name} 获胜")
            await self._broadcast(protocol.game_over(st.winner, "player_defeated"))
            self._cancel_timer()

    async def resync(self, conn: Connection) -> None:
        """断线重连后的全量补发（仅发给该连接，不动广播游标）：
        断线期间的广播游标照常前进，重连者错过的日志按全量 state.log 补发；
        结算明细历史不补（回放节奏打扰），以最新完整 state 场况为准。
        payload 全量含 pending_choice——重连者若正待检视选牌，客户端按状态提示作答；
        计时器一并补发（状态栏倒计时不断档）。"""
        st = self.game.state
        base = st.model_dump(mode="json")
        viewer = self.seat_to_player[conn.seat]
        await conn.send(protocol.state(
            sanitize_state(base, viewer),
            _hide_mulligan_log(list(st.log), st, viewer),  # 全量补发同样隐藏对方调度明细
            timer=self._current_timer()))

    # ---------- 计时器 ----------

    def current_timer_key(self) -> tuple | None:
        """当前应当计时的对象：("mulligan", 玩家下标) 或 ("turn", 总回合数)。"""
        if self.game is None:
            return None
        st = self.game.state
        if st.winner is not None or st.pending_end:
            return None
        if st.phase == "mulligan":
            # 并行调度：双方自阶段开始共用同一个截止时刻，不按玩家轮流计时
            # （否则一方 ready/超时后会给另一方重启一个完整的调度时长）
            if any(not p.mulligan_done for p in st.players):
                return ("mulligan",)
            return None
        return ("turn", st.turn)

    def reschedule_timer(self) -> None:
        """计时对象变化时重启计时器（同一对象不重置，保证 120s 覆盖整个回合）。
        deadline 随 state 消息下发（客户端状态栏倒计时显示用，裁决仍在服务端）。"""
        key = self.current_timer_key()
        if key == self._timer_key:
            return
        self._cancel_timer()
        self._timer_key = key
        if key is not None:
            seconds = self.mulligan_timeout if key[0] == "mulligan" else self.turn_timeout
            self._timer_deadline = time.time() + seconds
            self._timer = asyncio.ensure_future(self._run_timer(key, seconds))

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._timer_key = None
        self._timer_deadline = None

    async def _run_timer(self, key: tuple, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        if self._timer_key != key or self.game is None:
            return
        await self._on_timeout(key)

    async def _on_timeout(self, key: tuple) -> None:
        st = self.game.state
        try:
            if key[0] == "mulligan":
                names = [st.players[pi].name for pi in (0, 1)
                         if not st.players[pi].mulligan_done]
                await self._broadcast(protocol.notice(
                    f"{'、'.join(names)} 调度超时，自动结束调度"))
                for pi in (0, 1):  # 超时统一收尾所有未完成调度的玩家
                    if not st.players[pi].mulligan_done:
                        self.game.apply({"op": "ready", "player": pi})
            else:  # 回合超时：先收尾结算中交互选择，升级阶段先随机升级，再结束回合
                if st.pending_choice is not None:
                    # 检视选牌（青灯夜谈）挂起时随机作答到底——否则 apply 拒绝 choose
                    # 以外的指令，回合无法超时收尾、计时器 key 不变也不会重启（死局）
                    chooser = st.players[st.pending_choice["player"]].name
                    while st.pending_choice is not None:
                        pend = st.pending_choice
                        self.game.apply({"op": "choose",
                                         "uid": self.rng.choice(pend["options"]),
                                         "player": pend["player"]})
                    await self._broadcast(protocol.notice(
                        f"{chooser} 的检视选牌超时，已随机选择"))
                p = st.players[st.active]
                if st.phase == "upgrade":
                    while st.phase == "upgrade" and p.upgrades > 0:
                        idxs = self.game.legal_upgrade_indices(st.active)
                        if not idxs:
                            break
                        self.game.apply({"op": "upgrade", "index": self.rng.choice(idxs)})
                    await self._broadcast(protocol.notice(
                        f"{p.name} 回合超时：已随机完成升级"))
                if st.winner is None and not st.pending_end:
                    await self._broadcast(protocol.notice(
                        f"{p.name} 回合超时，自动结束回合"))
                    self.game.apply({"op": "end_turn"})
        except IllegalAction:
            pass
        self.reschedule_timer()
        await self.broadcast_state()
