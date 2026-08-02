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
from db.loader import CardDatabase

CLIENT_ID = "BWPro-CLI/1.0"  # 客户端标识：服务端软门槛（server.main.CLIENT_UA 前缀）


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
        self.in_lobby = False            # 准备阶段（双方都位、等待准备确认/自动开始）
        self.lobby_deadline: float | None = None  # 自动准备的 unix 截止时刻
        self.payload: dict | None = None  # 最近一次 state 的 payload
        self.timer: dict | None = None    # 最近一次 state 附带的计时器（kind/deadline）
        self._seq = 0  # 服务端回推计数（state/error 各 +1）：发指令后等待回推用
        self._seats_shown = False  # 调度前先后手/座次行只打印一次（start 时重置）
        self.result_text: str | None = None  # 终局结果文本（按视角；run() 收尾等待播完用）
        self.over = threading.Event()
        self.ended_normally = False  # game_over/用户主动退出：断线提示据此抑制
        self.disconnect_reason: str | None = None  # 接收循环异常退出原因
        self._mulligan_fp: tuple | None = None  # 己方调度数据指纹（对手并行广播不重印）

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
        elif t == "lobby":
            # 双方都位进入准备阶段：r 准备 / q 离开；deadline 到期自动开始
            self.in_lobby = True
            self.lobby_deadline = msg.get("deadline")
            print("\n双方已就位，进入准备阶段：r 准备，q 离开房间"
                  f"（{round(max(0.0, (self.lobby_deadline or 0) - time.time()))}s 后自动开始）")
            tui.start_ticker(1.0)  # 状态栏准备倒计时
            tui.invalidate()
        elif t == "peer_left":
            self.in_lobby = False
            self.lobby_deadline = None
            print(f"** {msg.get('name')} 已离开房间，等待新对手加入")
            tui.invalidate()
        elif t == "left":
            self.ended_normally = True  # 主动离开房间：不当作断线
            self.over.set()
        elif t == "start":
            self.in_lobby = False
            self.lobby_deadline = None
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
            self.ended_normally = True
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
                if self.in_lobby:
                    prompt = f"[{self.name} 准备阶段]"
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
        cmd = cli.COMMAND_ALIASES.get(cmd, cmd)
        if self.in_lobby:
            # 准备阶段：r 准备 / q 离开（服务端确认 left 后断连，由 recv 循环收尾）
            if cmd in ("ready", "r"):
                self.send({"type": "ready"})
            elif cmd in ("leave", "q", "quit", "exit"):
                self.send({"type": "leave"})
            else:
                print("准备阶段：r 准备，q 离开房间")
            return
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
    未开局时为两段（房间提示）；准备阶段中段显示自动开始倒计时。"""
    game = client.wrapper()
    if client.in_lobby:
        left = f"房间 {client.room_id}，双方已就位"
        mid = ("准备中 " + _fmt_timer({"deadline": client.lobby_deadline}, time.time())
               if client.lobby_deadline else "准备中")
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
        picked = deckbuilder.choose_deck(db, name)
        if picked is None:
            print("未选择卡组，返回主菜单")
            return
        _, _, deck_code = picked
        hello = {"type": "create", "name": name, "deck_code": deck_code,
                 "debug": debug, "client": CLIENT_ID}
        if room_id:
            hello["room_id"] = room_id
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
