"""联机客户端：连接 server/main.py 的 WebSocket 服务端进行双人对战。

运行：uv run python -m client.net [--server ws://127.0.0.1:1037/ws] [--debug] [--name 名字]

- 创建房间（可自建 6 位字母数字房码，缺省随机）或按房码加入；开局前从本地卡组文件
  （~/.bwp.decks.json）选择卡组（client/deckbuilder.choose_deck）。
- 准备阶段：双方都位后 r 准备 / q 离开，15s 自动开始。
- 服务端权威：指令与热坐 CLI 同一 cmd dict 协议；客户端只渲染服务端下发的
  GameState（本地 CardDatabase + Game 包装，不开局），"己方"视角为自己的座位。
- --debug：创建 debug 对局（房间内允许 debug 指令，解析复用 client/cli.py）。
- 断线重连：重进后选择"加入房间"并输入房间 id + 令牌（joined 消息中显示）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time

from client import cli, deckbuilder, tui
from client.settle import SettlePrinter
from core.engine import Game
from core.model import GameState
from db.envs import env_label, parse_env_input
from db.loader import CardDatabase

CLIENT_ID = "BWPro-CLI/1.0"  # 客户端标识：服务端软门槛（server.main.CLIENT_UA 前缀）


class NetClient:
    def __init__(self, db, ws, name: str, printer: SettlePrinter | None = None) -> None:
        self._base_db = db      # 完整库（最新数据）；环境切换时 db = _base_db.at_date(env)
        self.db = db
        self.ws = ws
        self.name = name
        self.printer = printer  # 结算打印队列（边播边操作）；None = 不入队（测试）
        self.room_id: str | None = None
        self.token: str | None = None
        self.seat: int | None = None  # 房间座位（0=房主，可改环境）
        self.me: int | None = None  # 自己在 state.players 中的下标
        self.env_date: int | None = None  # 对局环境（lobby/start 消息下发）
        self.mode = "standard"  # 对局模式（lobby/start 消息下发；标准=最新环境不可改）
        self.join_hello: dict | None = None  # 加入房间的 hello（环境拒绝后换卡组重发用）
        self.env_rejected = False  # 入座卡组被房间环境拒绝：输入循环重选卡组重发 join
        self.room_debug = False
        self.in_lobby = False            # 准备阶段（双方都位、等待准备/开始倒计时）
        self.lobby_ready: list[str] = []  # 已准备玩家名列表（lobby 消息维护）
        self.lobby_deadline: float | None = None  # 自动准备 unix 截止（None = 无人准备不计时）
        self.starting_deadline: float | None = None  # 对局开始 3s 倒计时的 unix 截止
        self.payload: dict | None = None  # 最近一次 state 的 payload
        self.timer: dict | None = None    # 最近一次 state 附带的计时器（kind/deadline）
        self._seq = 0  # 服务端回推计数（state/error 各 +1）：发指令后等待回推用
        self._seats_shown = False  # 调度前先后手/座次行只打印一次（start 时重置）
        self.result_text: str | None = None  # 终局结果文本（按视角；run() 收尾等待播完用）
        self.over = threading.Event()
        self.ended_normally = False  # game_over/用户主动退出：断线提示据此抑制
        self.disconnect_reason: str | None = None  # 接收循环异常退出原因
        self._mulligan_fp: tuple | None = None  # 己方调度数据指纹（对手并行广播不重印）
        self._ctx_seen: tuple | None = None  # 输入上下文指纹：变化时作废陈旧输入提示符

    def _ctx_key(self, pl: dict) -> tuple | None:
        """输入上下文指纹（原始 payload 直读，避免解析整份 GameState）：
        与 _can_act/input_loop 的提示符分支一一对应；指纹变化 = 当前阻塞中的
        提示符已陈旧（如调度超时自动 ready、回合超时自动结束、双方就绪开局）。"""
        if self.me is None:
            return None
        if pl["phase"] == "mulligan":
            return ("mulligan", pl["players"][self.me]["mulligan_done"])
        pend = pl.get("pending_choice")
        if pend is not None:
            return ("choice", pend.get("player") == self.me)
        return ("turn", pl["phase"], pl["active"] == self.me)

    # ---------- 接收 ----------

    def _apply_env(self, env_date: int | None) -> None:
        """对局环境切换（lobby/start 消息下发）：本地渲染库解析为环境版本。"""
        if env_date == self.env_date:
            return
        self.env_date = env_date
        self.db = self._base_db.at_date(env_date)

    def _mode_label(self) -> str:
        """对局模式+环境显示文本：标准模式固定最新环境；自由模式附环境标签。"""
        if self.mode == "standard":
            return "标准"
        return f"自由·{env_label(self.env_date)}"

    def wrapper(self) -> Game | None:
        """由最新 state payload 构造只读渲染包装（不调用 start）。"""
        if self.payload is None:
            return None
        return Game(GameState.model_validate(self.payload), self.db)

    def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "joined":
            self.room_id = msg["room_id"]
            self.token = msg["token"]
            self.seat = msg["seat"]
            self.room_debug = bool(msg.get("debug"))
            print(f"已加入房间 {self.room_id}（重连令牌：{self.token}）"
                  f"{'【debug 对局】' if self.room_debug else ''}，等待对手……")
        elif t == "lobby":
            # 准备阶段状态更新：ready 为已准备名单（空 = 无人准备、不计时）；
            # deadline 非空 = 一方已准备，未准备方超时将自动准备
            self.in_lobby = True
            self.mode = msg.get("mode", "standard")
            self._apply_env(msg.get("env_date"))
            self.lobby_ready = list(msg.get("ready") or [])
            self.lobby_deadline = msg.get("deadline")
            self.starting_deadline = None
            if self.name in self.lobby_ready:
                hint = "你已准备，等待对手"
            elif self.lobby_deadline:
                left_s = round(max(0.0, self.lobby_deadline - time.time()))
                hint = f"对手已准备：r 准备（{left_s}s 后自动准备），q 离开房间"
            else:
                hint = "r 准备，q 离开房间"
                if self.seat == 0 and self.mode == "free":
                    hint += "；e <环境> 更改对局环境"
            env_note = f"（{self._mode_label()}）"
            print(f"\n双方已就位，进入准备阶段{env_note}：{hint}")
            tui.start_ticker(1.0)  # 状态栏准备倒计时
            tui.cancel_prompt()    # 输入上下文切换：作废陈旧提示符
            tui.invalidate()
        elif t == "starting":
            # 双方均已准备：3s 开始倒计时（期间仍可 q 离开）
            self.starting_deadline = msg.get("deadline")
            self.lobby_deadline = None
            left_s = round(max(0.0, (self.starting_deadline or 0) - time.time()))
            print(f"双方已准备，对局将在 {left_s}s 后开始")
            tui.cancel_prompt()
            tui.invalidate()
        elif t == "peer_left":
            self.in_lobby = False
            self.lobby_ready = []
            self.lobby_deadline = None
            self.starting_deadline = None
            print(f"** {msg.get('name')} 已离开房间，等待新对手加入")
            tui.cancel_prompt()
            tui.invalidate()
        elif t == "left":
            self.ended_normally = True  # 主动离开房间：不当作断线
            self.over.set()
            tui.cancel_prompt()
        elif t == "dissolved":
            # 看门狗解散未开局房间：服务端随后关闭连接，按正常结束处理
            # （不提示断线重连），回主菜单
            self.ended_normally = True
            print(f"** 房间已被解散（{msg.get('reason', '')}）")
            tui.cancel_prompt()
            self.over.set()
        elif t == "start":
            self.in_lobby = False
            self.lobby_ready = []
            self.lobby_deadline = None
            self.starting_deadline = None
            self.mode = msg.get("mode", "standard")
            self._apply_env(msg.get("env_date"))
            self._ctx_seen = None
            tui.cancel_prompt()  # 准备阶段提示符 → 调度阶段提示符
            self.me = msg["player_index"]
            self._seats_shown = False  # 新对局：调度前重新展示座次行
            self._mulligan_fp = None
            print(f"对局开始：你是{'先手' if msg['you_first'] else '后手'}"
                  f"，对手：{msg['opponent']}")
            tui.start_ticker(1.0)  # 驱动状态栏倒计时逐秒重绘
        elif t == "state":
            self._seq += 1
            self.payload = msg["payload"]
            self.timer = msg.get("timer")
            key = self._ctx_key(self.payload)
            if self._ctx_seen is not None and key != self._ctx_seen:
                # 输入上下文被服务端推送切换（超时自动 ready/结束回合、双方就绪
                # 进入首回合等）：作废阻塞中的陈旧提示符，输入循环按最新状态重算
                tui.cancel_prompt()
            self._ctx_seen = key
            # 结算播放入打印队列（入队即返回，播放不阻塞接收/输入；播放中到达的
            # 新 state 块排入队尾，当前块播完再播）：合并时间线（结算/叙事按真实
            # 发生顺序合流）优先，旧字段 settle+log 兜底
            if self.printer is not None:
                if msg.get("timeline"):
                    block = cli.format_timeline_lines(msg["timeline"])
                else:
                    block = cli.format_settle_lines(msg.get("settle") or [])
                    block += [f"  | {line}" for line in msg.get("log", [])]
                self.printer.enqueue(block)
            self._show()
            tui.invalidate()  # 状态栏（阶段/回合归属/倒计时）立即按新状态重绘
        elif t == "error":
            self._seq += 1  # 指令的否定回推：解除 send_cmd 的等待
            reason = msg.get("reason", "")
            print(f"无效操作: {reason}")
            if "环境" in reason and self.join_hello is not None and self.me is None:
                # 入座卡组被房间环境拒绝：输入循环重选卡组并重发 join（连接保持）
                self.env_rejected = True
                tui.cancel_prompt()
        elif t == "notice":
            print(f"** {msg.get('text')}")
        elif t == "game_over":
            self.ended_normally = True
            tui.cancel_prompt()  # 解除阻塞中的输入提示符，输入循环随即按 over 退出
            winner = msg.get("winner")
            if winner is None:
                print(f"对局终止（{msg.get('reason')}）")
            elif self.payload is not None:
                # thoughts(1)：按视角打印结果（不固定哪方获胜）；作为末块入队——
                # 剩余结算按固定速度播完后才显示，不重复打印、不附场况
                names = [p["name"] for p in self.payload["players"]]
                text = cli.result_text(winner, names, viewer=self.me)
                self.result_text = text
                if self.printer is not None:
                    self.printer.enqueue([f"***** {text} *****"])
                else:
                    print(f"***** {text} *****")
            self.over.set()

    def _show(self) -> None:
        game = self.wrapper()
        if game is None or self.me is None:
            return
        st = game.state
        if st.phase == "mulligan":
            p = st.players[self.me]
            if not p.mulligan_done:
                # 并行调度：对手动作同样触发广播，己方调度数据未变时不重印整块
                fp = (p.mulligans_left, tuple(c.uid for c in p.hand))
                if fp == self._mulligan_fp:
                    return
                self._mulligan_fp = fp
                if not self._seats_shown:  # 调度前先展示双方先后手与四座次（仅一次）
                    print("")
                    for pi in (0, 1):
                        print(cli.format_seat_line(game, pi))
                    self._seats_shown = True
                print(f"\n—— 调度阶段（剩 {p.mulligans_left} 次）："
                      "输入手牌序号调度，done 结束 ——")
                for line in cli.format_hand_lines(game, p, p.hand, with_usage=False):
                    print(line)
            return
        if self.printer is not None:
            cli.show_field(game, self.printer, viewer=self.me,
                           env_date=self.env_date)  # 场况入队尾：结算播完再显示
        else:
            print(cli.render(game, viewer=self.me, env_date=self.env_date))

    # ---------- 发送 ----------

    def send(self, msg: dict) -> None:
        self.ws.send(json.dumps(msg, ensure_ascii=False))

    def send_cmd(self, cmd: dict) -> None:
        """发指令并等服务端回推（state/error，最长 2s）再返回——随后的输入提示
        （升级阶段/回合归属等）始终基于最新已应用状态，不会慢一个阶段。"""
        seq = self._seq
        self.send({"type": "cmd", "cmd": cmd})
        deadline = time.monotonic() + 2.0
        while self._seq == seq and not self.over.is_set() \
                and time.monotonic() < deadline:
            time.sleep(0.02)

    # ---------- 输入循环 ----------

    def _can_act(self, st) -> bool:
        """当前是否有合法输入场景（thoughts(1)）：自己调度未完成 / 待自己作答的
        结算中选择（pending_choice）/ 自己的回合。其余（对手回合、已完成调度等待）
        不显示输入提示符、不接受操作指令。"""
        if st.phase == "mulligan":
            return not st.players[self.me].mulligan_done
        if st.pending_choice is not None:
            return st.pending_choice.get("player") == self.me
        return st.active == self.me

    def input_loop(self) -> None:
        with tui.activate():
            while not self.over.is_set():
                if self.env_rejected:
                    # 入座卡组被房间环境拒绝：重选卡组并重发 join（连接保持）
                    self.env_rejected = False
                    picked = deckbuilder.choose_deck(self._base_db, self.name)
                    if picked is None:
                        self.ended_normally = True
                        self.over.set()
                        break
                    _, _, deck_code = picked
                    hello = dict(self.join_hello)
                    hello["deck_code"] = deck_code
                    self.send(hello)
                    continue
                game = self.wrapper()
                if game is not None and not self._can_act(game.state):
                    # 对手回合/等待期：不显示输入提示符，轮询状态直到可行动
                    try:
                        time.sleep(0.1)
                    except KeyboardInterrupt:
                        break
                    continue
                prompt = f"[{self.name}]"
                if self.in_lobby:
                    state = "已准备" if self.name in self.lobby_ready else "准备阶段"
                    prompt = f"[{self.name} {state}]"
                elif game is not None:
                    st = game.state
                    if st.phase == "mulligan":
                        p = st.players[self.me]
                        prompt = f"[{self.name} 调度（剩 {p.mulligans_left} 次）]"
                    elif st.phase == "upgrade" and st.active == self.me:
                        prompt = f"[{self.name} 升级阶段（剩 {st.players[self.me].upgrades} 次）]"
                    elif st.pending_choice is not None:
                        prompt = f"[{self.name} 检视选牌]"
                try:
                    line = tui.prompt(f"{prompt} > ").strip()
                except (EOFError, KeyboardInterrupt):
                    self.ended_normally = True  # 用户主动中断，不当作断线
                    break
                if not line:
                    continue
                try:
                    self.handle_line(line)
                except (ValueError, IndexError):
                    print("参数有误，输入 help 查看帮助")

    def handle_line(self, line: str) -> None:
        game = self.wrapper()
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        if self.in_lobby:
            # 准备阶段：r 准备/取消准备（服务端切换语义）、q 离开（left 应答后断连）；
            # 自由模式房主（seat 0）在双方均未准备时可 e <环境> 更改对局环境
            # （别名 alias 或 8/6 位日期；e 无参 = 最新）。
            # lobby 指令在 COMMAND_ALIASES 解析之前处理（否则 e 会被映射为 end）
            if cmd in ("ready", "r"):
                self.send({"type": "ready"})
            elif cmd in ("leave", "q", "quit", "exit"):
                self.send({"type": "leave"})
            elif cmd in ("env", "e"):
                if self.seat != 0:
                    print("只有房主可以更改对局环境")
                elif self.mode == "standard":
                    print("标准模式使用最新平衡性环境，不可更改")
                elif self.lobby_ready:
                    print("双方均未准备时才能更改环境（请先取消准备）")
                else:
                    try:
                        date = parse_env_input(args[0]) if args else None
                    except ValueError as e:
                        print(str(e))
                        return
                    self.send({"type": "env", "date": date})
            else:
                hint = ("已准备（r 取消准备）" if self.name in self.lobby_ready
                        else "r 准备")
                print(f"准备阶段：{hint}，q 离开房间")
            return
        cmd = cli.COMMAND_ALIASES.get(cmd, cmd)
        if cmd in ("quit", "exit"):
            self.ended_normally = True
            self.over.set()
            return
        if cmd == "help":
            print(cli.HELP)
            return
        if game is None or self.me is None:
            print("对局尚未开始")
            return
        st = game.state
        if cmd == "state":
            self._show()
            return
        if cmd == "log":
            n = int(args[0]) if args else 10
            print("\n".join(st.log[-n:]))
            return
        if cmd == "debug":
            if not self.room_debug:
                print("本房间未开启 debug（创建时用 --debug）")
                return
            dcmd = cli.run_debug(game, args)
            if dcmd:
                self.send_cmd(dcmd)
            return
        if st.phase == "mulligan":
            p = st.players[self.me]
            if p.mulligan_done:
                print("你已完成调度，等待对手")
                return
            if cmd in ("done", "ready", "end"):
                self.send_cmd({"op": "ready"})
                return
            card = p.hand[int(cmd) - 1]  # 调度直接输入手牌序号
            self.send_cmd({"op": "mulligan", "uid": card.uid})
            return
        if st.pending_choice is not None:
            # 结算中交互选择：choose <序号> 作答；对方的选择只提示等待
            pend = st.pending_choice
            if pend.get("player") != self.me:
                print("等待对方完成交互选择")
                return
            p = st.players[self.me]
            kind = pend.get("kind")
            if kind == "discard_pick":
                # 交互弃牌（意外之喜）：从手牌选一张弃置
                opts = [c for u in pend["options"]
                        for c in [next((x for x in p.hand if x.uid == u), None)] if c]
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose", "uid": opts[int(args[0]) - 1].uid})
                    return
                print("—— 弃置手牌：输入 choose <序号> 弃置一张 ——")
                for i, c in enumerate(opts):
                    cd = self.db.cards[c.id]
                    print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
                return
            if kind == "card_name":
                # 忘忧的旋律（两级）：先选敌方式神，再选其一张牌名（作答键 choice）
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose",
                                   "choice": pend["options"][int(args[0]) - 1]})
                    return
                if pend.get("stage") == "shikigami":
                    print("—— 选择敌方式神：输入 choose <序号> ——")
                    for i, sid in enumerate(pend["options"]):
                        print(f"  [{i + 1}] {self.db.shikigami[sid].name}")
                else:
                    print("—— 选择一张牌名：输入 choose <序号> ——")
                    for i, cid in enumerate(pend["options"]):
                        cd = self.db.cards[cid]
                        print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
                return
            if kind == "field_summon_pick":
                # 选择召唤幻境（残阳无影）：从可召唤的幻境牌中选一张直接召唤（作答键 choice）
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose",
                                   "choice": pend["options"][int(args[0]) - 1]})
                    return
                print("—— 选择要召唤的幻境：输入 choose <序号> ——")
                for i, cid in enumerate(pend["options"]):
                    cd = self.db.cards[cid]
                    print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
                return
            if kind == "pick_generate":
                # 选择生成入手（三目线索/觉醒·鬼切战斗牌）：作答键 choice（数据 id）
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose",
                                   "choice": pend["options"][int(args[0]) - 1]})
                    return
                print("—— 选择一张牌置入手牌：输入 choose <序号> ——")
                for i, cid in enumerate(pend["options"]):
                    cd = self.db.cards[cid]
                    print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
                return
            if kind == "quest_complete_pick":
                # 委托整理：从手牌紧急委托中选一张使其视为达成（作答键 uid）
                opts = [c for u in pend["options"]
                        for c in [next((x for x in p.hand if x.uid == u), None)] if c]
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose", "uid": opts[int(args[0]) - 1].uid})
                    return
                print("—— 选择一张紧急委托使其视为达成：输入 choose <序号> ——")
                for i, c in enumerate(opts):
                    cd = self.db.cards[c.id]
                    print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
                return
            if kind == "invocation_pick":
                # 选择灵咒结附（鬼切"选择一张鬼斩结附"）：作答键 choice（灵咒名）
                if cmd == "choose" and args:
                    self.send_cmd({"op": "choose",
                                   "choice": pend["options"][int(args[0]) - 1]})
                    return
                print("—— 选择一张灵咒牌结附：输入 choose <序号> ——")
                for i, name in enumerate(pend["options"]):
                    idef = self.db.invocations.get(name)
                    text = f" {idef.text}" if idef is not None and idef.text else ""
                    print(f"  [{i + 1}]【{name}】{text}")
                return
            # 检视牌库顶（青灯夜谈/明心）
            opts = [c for u in pend["options"]
                    for c in [next((x for x in p.deck if x.uid == u), None)] if c]
            if cmd == "choose" and args:
                self.send_cmd({"op": "choose", "uid": opts[int(args[0]) - 1].uid})
                return
            print("—— 检视牌库顶：输入 choose <序号> 选择一张置入手牌 ——")
            for i, c in enumerate(opts):
                cd = self.db.cards[c.id]
                print(f"  [{i + 1}]【{cd.name}】 {cd.text}")
            return
        if st.active != self.me:
            print("还没到你的回合")
            return
        if cmd == "play":
            hand = cli.hand_sorted(game, st.players[self.me])
            card = hand[int(args[0]) - 1]
            cdef = self.db.cards[card.id]
            cmd_dict: dict = {"op": "play_card", "uid": card.uid}
            rest = args[1:]
            eff = cdef
            if cdef.card_type == "reinforce":
                # 协战牌子选项（裁决(16) 多择引导）：列出全部子选项（含当前不合法者，
                # 标注原因）；选不合法要求重选，不能回退不使用该牌
                options = [self.db.cards[o] for o in cdef.options]
                while True:
                    if rest:
                        pick = int(rest.pop(0))
                    else:
                        for i, o in enumerate(options):
                            err = game.reinforce_sub_option_error(
                                self.me, cdef, i)
                            mark = f"（不可选：{err}）" if err else ""
                            print(f"  [{i}]【{o.name}】 {o.text}{mark}")
                        pick = int(tui.prompt("子选项 > "))
                    err = game.reinforce_sub_option_error(self.me, cdef, pick)
                    if err is None:
                        break
                    print(f"  子选项不可选：{err}——请重选（不能取消使用）")
                cmd_dict["choice"] = pick
                eff = options[pick]
            if eff.target.kind == "choose":
                ref = cli.prompt_target(game, eff.target, self.me, rest)
                cmd_dict["target"] = ref.model_dump()
            t2 = cdef.target2
            if t2 is not None and t2.kind == "choose":
                # 第二选择目标（麓鸣·灭型双 choose 卡）：本地提示，服务端校验
                ref2 = cli.prompt_target(game, t2, self.me, rest, label="第二目标")
                cmd_dict["target2"] = ref2.model_dump()
            if rest:
                cmd_dict["play_method"] = rest.pop(0)
            self.send_cmd(cmd_dict)
        elif cmd in ("assault", "upgrade"):
            self.send_cmd({"op": cmd, "index": int(args[0]) - 1})
        elif cmd == "end":
            self.send_cmd({"op": "end_turn"})
        else:
            print("未知指令，输入 help 查看帮助")


def _fmt_timer(timer: dict, now: float) -> str:
    """倒计时文本：`⏱ m:ss`（调度阶段加"调度 "前缀）；超时封顶 0:00。"""
    remaining = max(0.0, timer.get("deadline", now) - now)
    m, s = divmod(int(remaining), 60)
    text = f"⏱ {m}:{s:02d}"
    if timer.get("kind") == "mulligan":
        text = f"调度 {text}"
    return text


def _net_status(client: NetClient) -> tuple[str, ...]:
    """底部状态栏三段：左=己方牌手、中=阶段提示+回合+倒计时（居中）、右=敌方牌手。
    未开局时为两段（房间提示）；准备阶段中段显示自动开始倒计时。"""
    game = client.wrapper()
    if client.in_lobby:
        ready = "、".join(client.lobby_ready) or "无"
        left = f"房间 {client.room_id}（{client._mode_label()} · 已准备 {len(client.lobby_ready)}/2：{ready}）"
        if client.starting_deadline:
            mid = "即将开始 " + _fmt_timer(
                {"deadline": client.starting_deadline}, time.time())
        elif client.lobby_deadline:
            mid = ("等待准备 " if client.name in client.lobby_ready else "请准备 ")
            mid += _fmt_timer({"deadline": client.lobby_deadline}, time.time())
        else:
            mid = "等待准备"
        return left, mid
    if game is None or client.me is None:
        left = f"房间 {client.room_id}，等待对手……" if client.room_id else "联机"
        return left, ""
    left, right = cli.player_segments(game, viewer=client.me)
    st = game.state
    if st.phase == "mulligan":
        mid = _fmt_timer(client.timer, time.time()) if client.timer else "调度阶段"
    else:
        active = st.players[st.active]
        if st.active == client.me:
            hint = ("你的回合" if st.phase != "upgrade"
                    else f"升级阶段（剩 {st.players[client.me].upgrades} 次）")
        else:
            hint = "对手行动中"
        mid = f"{hint} · 总第 {st.turn - 1} 回合 · {active.name} 第 {active.turn_count} 回合"
        if client.timer:
            mid += " " + _fmt_timer(client.timer, time.time())
    return left, mid, right


def _input(prompt: str) -> str:
    try:
        return tui.prompt(prompt).strip()
    except EOFError:
        return ""


def normalize_server_url(raw: str) -> str:
    """把用户输入的服务器地址规范化为 ws(s)://host[:port]/ws。

    接受 ws://、wss://、http(s)://（内网穿透/反代给出的网址）以及裸
    host[:port]；无路径时自动补 /ws。裸地址省略协议时：带端口默认 ws
    （本机/局域网，如 127.0.0.1:1037），不带端口默认 wss（公网域名经
    HTTPS 穿透/反代，TLS 在 443 终止）。
    """
    s = raw.strip()
    if s.startswith("https://"):
        s = "wss://" + s[len("https://"):]
    elif s.startswith("http://"):
        s = "ws://" + s[len("http://"):]
    if not s.startswith(("ws://", "wss://")):
        host = s.split("/", 1)[0]
        s = ("ws://" if ":" in host else "wss://") + s
    if "/" not in s.split("://", 1)[1]:
        s = s + "/ws"
    return s


def _open_ws(server_url: str, retries: int = 3, open_timeout: float = 5.0):
    """建立 WS 连接（带客户端标识 UA）；穿透服务对来源 IP 首次请求的间歇
    拦截（提示页等）按 1s 间隔重试。"""
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


def run(db, server_url: str, name: str, debug: bool) -> None:
    """联机入口：创建/加入房间 → 收发线程 + 输入循环。"""
    server_url = normalize_server_url(server_url)
    choice = _input("[1] 创建房间 [2] 加入房间（含重连）> ")
    if choice == "1":
        room_id = _input("房间代码（6 位字母或数字，Enter 随机分配）> ") or None
        if room_id is not None and not re.fullmatch(r"[A-Za-z0-9]{6}", room_id):
            print("房间代码须为 6 位大小写字母或数字")
            return
        mode_pick = _input("[1] 标准模式（最新环境） [2] 自由模式（可选环境，Enter=1）> ")
        env_date = None
        mode = "standard"
        if mode_pick == "2":
            mode = "free"
            try:
                env_date = parse_env_input(
                    _input("对局环境（alias 或日期，Enter = 标准）> "))
            except ValueError as e:
                print(str(e))
                return
        picked = deckbuilder.choose_deck(db, name)
        if picked is None:
            print("未选择卡组，返回主菜单")
            return
        _, _, deck_code = picked
        hello = {"type": "create", "name": name, "deck_code": deck_code,
                 "debug": debug, "client": CLIENT_ID, "mode": mode}
        if room_id:
            hello["room_id"] = room_id
        if env_date:
            hello["env_date"] = env_date
    elif choice == "2":
        room_id = _input("房间 id > ")
        token = _input("重连令牌（首次加入 Enter 跳过）> ") or None
        deck_code = None
        if not token:
            picked = deckbuilder.choose_deck(db, name)
            if picked is None:
                print("未选择卡组，返回主菜单")
                return
            _, _, deck_code = picked
        hello = {"type": "join", "room_id": room_id, "name": name,
                 "deck_code": deck_code, "token": token, "client": CLIENT_ID}
    else:
        print("已取消")
        return
    try:
        # 客户端标识软门槛：create/join 需带 client 字段（server.main.CLIENT_UA 前缀）
        ws = _open_ws(server_url, open_timeout=10.0)
    except Exception as e:
        print(f"无法连接服务器 {server_url}（{e}）")
        return
    with ws:
        printer = SettlePrinter(cli.SETTLE_INTERVAL)
        client = NetClient(db, ws, name, printer)
        if choice == "2" and not token:
            client.join_hello = hello  # 环境拒绝入座时换卡组重发
        client.send(hello)
        printer.start()
        tui.set_status(lambda: _net_status(client))
        try:
            def recv_loop() -> None:
                try:
                    for raw in ws:
                        try:
                            client.handle(json.loads(raw))
                        except Exception as e:  # 单条坏消息不杀死接收循环
                            print(f"无法处理服务端消息（{e}）")
                except Exception as e:
                    client.disconnect_reason = str(e)
                finally:
                    client.over.set()
                    if not client.ended_normally:
                        # 非对局结束/主动退出：明确告知断线原因与重连方式，
                        # 不再静默回退主菜单
                        hint = (f"（{client.disconnect_reason}）"
                                if client.disconnect_reason else "")
                        print(f"\n** 与服务器的连接已断开{hint}")
                        if client.room_id and client.token:
                            print(f"** 可从主菜单进入 联机对战 → 加入房间，"
                                  f"输入房间 {client.room_id} 与重连令牌 "
                                  f"{client.token} 恢复对局")

            threading.Thread(target=recv_loop, daemon=True).start()
            client.input_loop()
        finally:
            tui.stop_ticker()
            tui.set_status(None)
            if client.result_text is not None:
                # 对局正常结束：剩余结算按固定速度播完（结果块已入队尾）再收尾
                printer.wait_idle(timeout=60)
            printer.stop(flush=True)  # 终局/退出：剩余明细快速播完，线程不泄漏
    # 对局结束（含 quit/断线）：等待确认后回主菜单；服务端负责房间清理
    try:
        tui.prompt("按 Enter 返回主菜单 > ")
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="BWPro 联机客户端")
    parser.add_argument("--server", default=os.environ.get(
        "BWP_SERVER", "ws://127.0.0.1:1037/ws"),
        help="服务器地址（默认环境变量 BWP_SERVER 或本机；"
             "ws(s)://、http(s)://、裸 host[:port] 均可；裸地址省略协议时"
             "无端口默认 wss、带端口默认 ws）")
    parser.add_argument("--name", default=None, help="玩家名（默认交互输入）")
    parser.add_argument("--debug", action="store_true",
                        help="创建 debug 对局（房间内允许 debug 指令）")
    args = parser.parse_args()
    if os.name == "nt":
        os.system("")  # 启用 Windows 控制台 ANSI 颜色
    db = CardDatabase.load()
    name = args.name or (_input("玩家名 > ") or "玩家")
    run(db, args.server, name, args.debug)


if __name__ == "__main__":
    main()
