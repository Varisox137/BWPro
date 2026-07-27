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

from client import cli, deckbuilder
from core.engine import Game
from core.model import GameState
from db.loader import CardDatabase


class NetClient:
    def __init__(self, db, ws, name: str) -> None:
        self.db = db
        self.ws = ws
        self.name = name
        self.room_id: str | None = None
        self.token: str | None = None
        self.me: int | None = None  # 自己在 state.players 中的下标
        self.room_debug = False
        self.payload: dict | None = None  # 最近一次 state 的 payload
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
            print(f"对局开始：你是{'先手' if msg['you_first'] else '后手'}"
                  f"，对手：{msg['opponent']}")
        elif t == "state":
            self.payload = msg["payload"]
            for line in msg.get("log", []):
                print(f"  | {line}")
            self._show()
        elif t == "error":
            print(f"无效操作: {msg.get('reason')}")
        elif t == "notice":
            print(f"** {msg.get('text')}")
        elif t == "game_over":
            winner = msg.get("winner")
            if winner is None:
                print(f"对局终止（{msg.get('reason')}）")
            elif self.payload is not None:
                wname = self.payload["players"][winner]["name"]
                print(f"***** {wname} 获胜！*****")
            self.over.set()

    def _show(self) -> None:
        game = self.wrapper()
        if game is None or self.me is None:
            return
        st = game.state
        if st.phase == "mulligan":
            p = st.players[self.me]
            if not p.mulligan_done:
                print(f"\n—— 调度阶段（剩 {p.mulligans_left} 次）："
                      "输入手牌序号调度，done 结束 ——")
                for line in cli.format_hand_lines(game, p, p.hand):
                    print(line)
            return
        print(cli.render(game, viewer=self.me))

    # ---------- 发送 ----------

    def send(self, msg: dict) -> None:
        self.ws.send(json.dumps(msg, ensure_ascii=False))

    def send_cmd(self, cmd: dict) -> None:
        self.send({"type": "cmd", "cmd": cmd})

    # ---------- 输入循环 ----------

    def input_loop(self) -> None:
        while not self.over.is_set():
            game = self.wrapper()
            prompt = f"[{self.name}]"
            if game is not None:
                st = game.state
                if st.phase == "mulligan":
                    p = st.players[self.me]
                    prompt = f"[{self.name} 调度（剩 {p.mulligans_left} 次）]"
                elif st.phase == "upgrade" and st.active == self.me:
                    prompt = f"[{self.name} 升级阶段（剩 {st.players[self.me].upgrades} 次）]"
            try:
                line = input(f"{prompt} > ").strip()
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
        if st.active != self.me:
            print("还没到你的回合")
            return
        if cmd == "play":
            hand = cli.hand_sorted(game, st.players[self.me])
            card = hand[int(args[0]) - 1]
            cdef = self.db.cards[card.id]
            cmd_dict: dict = {"op": "play_card", "uid": card.uid}
            rest = args[1:]
            if cdef.target.kind == "choose":
                legal = game.legal_targets(self.me, card)
                if rest:
                    code = rest.pop(0)
                else:
                    print("可选目标: " + " ".join(
                        cli.ref_code(r, self.me) for r in legal))
                    code = input("目标 > ")
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


def _input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def run(db, server_url: str, name: str, debug: bool) -> None:
    """联机入口：创建/加入房间 → 收发线程 + 输入循环。"""
    from websockets.sync.client import connect

    choice = _input("[1] 创建房间 [2] 加入房间（含重连）> ")
    if choice == "1":
        _, _, deck_code = deckbuilder.choose_deck(db, name)
        hello = {"type": "create", "name": name, "deck_code": deck_code,
                 "debug": debug}
    elif choice == "2":
        room_id = _input("房间 id > ")
        token = _input("重连令牌（首次加入回车跳过）> ") or None
        deck_code = None
        if not token:
            _, _, deck_code = deckbuilder.choose_deck(db, name)
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
        client = NetClient(db, ws, name)
        client.send(hello)

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
