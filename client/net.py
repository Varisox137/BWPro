"""联机客户端：连接 server/main.py 的 WebSocket 服务端进行双人对战。

运行：uv run python -m client.net [--server ws://127.0.0.1:1037/ws] [--debug] [--name 名字]

- 创建房间（随机分配房间 id）或按 id 加入；开局前从本地卡组文件
  （~/.bwp.decks.json）选择卡组（client/deckbuilder.choose_deck）。
- 服务端权威：指令与热坐 CLI 同一 cmd dict 协议；客户端只渲染服务端下发的
  GameState（本地 CardDatabase + Game 包装，不开局），"己方"视角为自己的座位。
- --debug：创建 debug 对局（房间内允许 debug 指令，解析复用 client/cli.py）。
- 断线重连：重进后选择"加入房间"并输入房间 id + 令牌（joined 消息中显示）。
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time

from client import cli, deckbuilder, tui
from client.settle import SettlePrinter
from core.engine import Game
from core.model import GameState
from db.loader import CardDatabase


class NetClient:
    def __init__(self, db, ws, name: str, printer: SettlePrinter | None = None) -> None:
        self.db = db
        self.ws = ws
        self.name = name
        self.printer = printer  # 结算打印队列（边播边操作）；None = 不入队（测试）
        self.room_id: str | None = None
        self.token: str | None = None
        self.me: int | None = None  # 自己在 state.players 中的下标
        self.room_debug = False
        self.payload: dict | None = None  # 最近一次 state 的 payload
        self.timer: dict | None = None    # 最近一次 state 附带的计时器（kind/deadline）
        self._seq = 0  # 服务端回推计数（state/error 各 +1）：发指令后等待回推用
        self._seats_shown = False  # 调度前先后手/座次行只打印一次（start 时重置）
        self.result_text: str | None = None  # 终局结果文本（按视角；run() 收尾等待播完用）
        self.over = threading.Event()

    # ---------- 接收 ----------

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
            self.room_debug = bool(msg.get("debug"))
            print(f"已加入房间 {self.room_id}（重连令牌：{self.token}）"
                  f"{'【debug 对局】' if self.room_debug else ''}，等待对手……")
        elif t == "start":
            self.me = msg["player_index"]
            self._seats_shown = False  # 新对局：调度前重新展示座次行
            print(f"对局开始：你是{'先手' if msg['you_first'] else '后手'}"
                  f"，对手：{msg['opponent']}")
            tui.start_ticker(1.0)  # 驱动状态栏倒计时逐秒重绘
        elif t == "state":
            self._seq += 1
            self.payload = msg["payload"]
            self.timer = msg.get("timer")
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
            print(f"无效操作: {msg.get('reason')}")
        elif t == "notice":
            print(f"** {msg.get('text')}")
        elif t == "game_over":
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
                if not self._seats_shown:  # 调度前先展示己方先后手与四座次（仅一次）
                    print("\n" + cli.format_seat_line(game, self.me))
                    self._seats_shown = True
                print(f"\n—— 调度阶段（剩 {p.mulligans_left} 次）："
                      "输入手牌序号调度，done 结束 ——")
                for line in cli.format_hand_lines(game, p, p.hand):
                    print(line)
            return
        if self.printer is not None:
            cli.show_field(game, self.printer, viewer=self.me)  # 场况入队尾：结算播完再显示
        else:
            print(cli.render(game, viewer=self.me))

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
                game = self.wrapper()
                if game is not None and not self._can_act(game.state):
                    # 对手回合/等待期：不显示输入提示符，轮询状态直到可行动
                    try:
                        time.sleep(0.1)
                    except KeyboardInterrupt:
                        break
                    continue
                prompt = f"[{self.name}]"
                if game is not None:
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
        cmd = cli.COMMAND_ALIASES.get(cmd, cmd)
        if cmd in ("quit", "exit"):
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
            # 结算中交互选择（青灯夜谈）：choose <序号> 作答；对方的选择只提示等待
            pend = st.pending_choice
            if pend.get("player") != self.me:
                print("等待对方完成检视选牌")
                return
            p = st.players[self.me]
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
                # 协战牌：先选择子选项（显示两选项卡名与文本），目标/等级按子卡
                options = [self.db.cards[o] for o in cdef.options]
                if rest:
                    pick = int(rest.pop(0))
                else:
                    for i, o in enumerate(options):
                        print(f"  [{i}]【{o.name}】 {o.text}")
                    pick = int(tui.prompt("子选项 > "))
                cmd_dict["choice"] = pick
                eff = options[pick]
            if eff.target.kind == "choose":
                from core import targets as _targets
                legal = _targets.pool_refs(game, eff.target.pool, self.me)
                if rest:
                    code = rest.pop(0)
                else:
                    print("可选目标: " + " ".join(
                        cli.ref_code(r, self.me) for r in legal))
                    code = tui.prompt("目标 > ")
                cmd_dict["target"] = cli.parse_ref(code, self.me).model_dump()
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
    未开局时为两段（房间提示）。"""
    game = client.wrapper()
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


def run(db, server_url: str, name: str, debug: bool) -> None:
    """联机入口：创建/加入房间 → 收发线程 + 输入循环。"""
    from websockets.sync.client import connect

    choice = _input("[1] 创建房间 [2] 加入房间（含重连）> ")
    if choice == "1":
        picked = deckbuilder.choose_deck(db, name)
        if picked is None:
            print("未选择卡组，返回主菜单")
            return
        _, _, deck_code = picked
        hello = {"type": "create", "name": name, "deck_code": deck_code,
                 "debug": debug}
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
                 "deck_code": deck_code, "token": token}
    else:
        print("已取消")
        return
    try:
        ws = connect(server_url)
    except Exception as e:
        print(f"无法连接服务器 {server_url}（{e}）")
        return
    with ws:
        printer = SettlePrinter(cli.SETTLE_INTERVAL)
        client = NetClient(db, ws, name, printer)
        client.send(hello)
        printer.start()
        tui.set_status(lambda: _net_status(client))
        try:
            def recv_loop() -> None:
                try:
                    for raw in ws:
                        try:
                            client.handle(json.loads(raw))
                        except (ValueError, KeyError) as e:
                            print(f"无法解析服务端消息（{e}）")
                except Exception:
                    pass
                finally:
                    client.over.set()

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
    parser.add_argument("--server", default="ws://127.0.0.1:1037/ws")
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
