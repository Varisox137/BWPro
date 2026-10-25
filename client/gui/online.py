"""桌面 GUI 联机模式：连接、大厅、NetBridge 与只读联机对局。"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from client import cli, net
from client.gui.battle import HotseatView
from core.engine import Game
from core.model import GameState, Ref
from db import deckstore
from db.envs import parse_env_input


class NetBridge(QObject):
    """同步 WebSocket 收包线程通过 Qt 信号投递到 GUI 主线程。"""

    message = Signal(dict)
    disconnected = Signal(str)

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self) -> None:
        reason = "连接已断开"
        try:
            for raw in self.ws:
                if not self._running:
                    return
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict):
                        self.message.emit(msg)
                except (TypeError, json.JSONDecodeError) as error:
                    self.message.emit({"type": "error", "reason": f"消息解析失败：{error}"})
        except Exception as error:
            reason = str(error) or reason
        finally:
            if self._running:
                self._running = False
                self.disconnected.emit(reason)

    def send(self, msg: dict) -> None:
        self.ws.send(json.dumps(msg, ensure_ascii=False))

    def send_cmd(self, cmd: dict) -> None:
        self.send({"type": "cmd", "cmd": cmd})

    def close(self) -> None:
        self._running = False
        try:
            self.ws.close()
        except Exception:
            pass


def _json_command(value):
    if isinstance(value, Ref):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _json_command(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_command(item) for item in value]
    return value


class OnlineBattleView(HotseatView):
    """复用热坐场况与操作流程；本地 Game 仅为服务端 state 的只读包装。"""

    def __init__(self, db, send_command, on_back=None, parent=None):
        self.send_command = send_command
        self.me = 0
        self.payload: dict | None = None
        self.server_timer: dict | None = None
        self._awaiting_state = False
        self._pending_game_over: tuple[int | None, str] | None = None
        super().__init__(db, on_back=on_back, parent=parent)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_timer.start()

    def reset_session(self) -> None:
        self.timeline_timer.stop()
        self.timeline_queue.clear()
        self.played_timeline.clear()
        self.log_list.clear()
        self.close_log()
        self.result_banner.hide()
        self.result_back.hide()
        self.game = None
        self.payload = None
        self.server_timer = None
        self._awaiting_state = False
        self._pending_game_over = None
        self._choice_key = None
        if self.choice_dialog is not None:
            self.choice_dialog.close()
            self.choice_dialog = None
        if not self.countdown_timer.isActive():
            self.countdown_timer.start()

    def _current_viewer(self) -> int:
        return self.me

    def hand_info(self) -> dict[int, dict]:
        info = (self.payload or {}).get("hand_info", {})
        return {int(uid): detail for uid, detail in info.items()}

    def refresh(self) -> None:
        if self.game is None:
            return
        self.viewer = self.me
        self._sync_perspective()
        self._render_state()
        self._sync_pending_choice()

    def set_state(self, payload: dict, timer: dict | None = None,
                  log: list[str] | None = None,
                  timeline: list[dict] | None = None) -> None:
        self.payload = payload
        self.server_timer = timer
        self.game = Game(GameState.model_validate(payload), self.db)
        self.viewer = self.me
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self._awaiting_state = False
        self._timeline_seen = len(self.game.state.timeline)
        self.stack.setCurrentWidget(self.battle_page)
        if timeline:
            for entry in timeline:
                self.timeline_queue.append((entry.get("o"), entry.get("m", "")))
            if not self.timeline_timer.isActive():
                self.timeline_timer.start()
        elif log:
            self.played_timeline.extend((None, line) for line in log)
            self._render_log()
        self.refresh()
        self._update_countdown()

    def _can_send(self, command: dict) -> bool:
        if self.game is None or self._awaiting_state or self.timeline_queue:
            return False
        state = self.game.state
        op = command.get("op")
        if op == "choose":
            return (state.pending_choice is not None
                    and state.pending_choice.get("player") == self.me)
        if state.pending_choice is not None:
            return False
        if state.phase == "mulligan":
            return (op in ("mulligan", "ready")
                    and not state.players[self.me].mulligan_done)
        return state.active == self.me

    def apply_command(self, command: dict) -> bool:
        if not self._can_send(command):
            return False
        self.send_command(_json_command(command))
        self._awaiting_state = True
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self.error_label.clear()
        self._update_input_widgets()
        return True

    def _inputs_open(self) -> bool:
        if self._awaiting_state or self.game is None:
            return False
        state = self.game.state
        if state.phase == "mulligan":
            own_context = not state.players[self.me].mulligan_done
        else:
            own_context = state.active == self.me
        return own_context and super()._inputs_open()

    def _sync_pending_choice(self) -> None:
        pending = self.game.state.pending_choice if self.game is not None else None
        if pending is not None and pending.get("player") != self.me:
            if self.choice_dialog is not None:
                self.choice_dialog.close()
                self.choice_dialog = None
            self._choice_key = None
            return
        super()._sync_pending_choice()

    def _render_state(self) -> None:
        super()._render_state()
        self._update_countdown()

    def _update_countdown(self) -> None:
        if self.game is None:
            return
        if not self.server_timer:
            return
        left = max(0, int(self.server_timer.get("deadline", 0) - time.time()))
        minutes, seconds = divmod(left, 60)
        prefix = "调度" if self.server_timer.get("kind") == "mulligan" else "回合"
        base = self.phase_label.text().split("　⏱", 1)[0]
        self.phase_label.setText(f"{base}　⏱ {prefix} {minutes}:{seconds:02d}")

    def receive_error(self, reason: str) -> None:
        self._awaiting_state = False
        self.error_label.setText(f"服务器：{reason}")
        self._render_state()

    def _show_result(self) -> None:
        names = [player.name for player in self.game.state.players]
        self.result_banner.setText(cli.result_text(self.game.state.winner, names, viewer=self.me))
        self.result_banner.show()
        self.result_back.show()

    def show_game_over(self, winner: int | None, reason: str = "") -> None:
        if self.timeline_queue:
            self._pending_game_over = (winner, reason)
            return
        if winner is None:
            self.result_banner.setText(f"对局终止（{reason}）")
            self.result_banner.show()
            self.result_back.show()
        else:
            self._show_result()

    def play_next_timeline(self) -> None:
        super().play_next_timeline()
        if not self.timeline_queue and self._pending_game_over is not None:
            winner, reason = self._pending_game_over
            self._pending_game_over = None
            self.show_game_over(winner, reason)

    def return_to_menu(self) -> None:
        self.countdown_timer.stop()
        super().return_to_menu()


class OnlineView(QWidget):
    """联机连接页、大厅与联机对局容器。"""

    def __init__(self, db, store_path: Path = deckstore.PATH, on_back=None,
                 bridge_factory=NetBridge, parent=None):
        super().__init__(parent)
        self.base_db = db
        self.db = db
        self.store_path = Path(store_path)
        self.on_back = on_back
        self.bridge_factory = bridge_factory
        self.bridge = None
        self.probe = net.probe_connection
        self.opener = net._open_ws
        self.server_url = ""
        self.player_name = "玩家"
        self.deck_name = ""
        self.deck_code: str | None = None
        self.room_id: str | None = None
        self.token: str | None = None
        self.seat: int | None = None
        self.me: int | None = None
        self.mode = "standard"
        self.env_date: int | None = None
        self.lobby_ready: list[str] = []
        self.lobby_deadline: float | None = None
        self.starting_deadline: float | None = None
        self.in_lobby = False
        self._expect_close = False
        self.theme = "light"
        self.entries: list[dict] = []
        self._build_ui()
        self.battle = OnlineBattleView(db, self.send_game_command,
                                       on_back=self.leave_to_menu, parent=self)
        self.stack.addWidget(self.battle)
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self._render_lobby)
        self.clock.start()
        self.reload_decks()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.connect_page = QWidget()
        connect = QFormLayout(self.connect_page)
        self.server_edit = QLineEdit("ws://127.0.0.1:1037/ws")
        self.name_edit = QLineEdit("玩家")
        self.deck_combo = QComboBox()
        connect.addRow("服务器地址", self.server_edit)
        connect.addRow("玩家名", self.name_edit)
        connect.addRow("标准卡组", self.deck_combo)
        self.connect_button = QPushButton("连接并进入大厅")
        self.connect_button.clicked.connect(self.connect_server)
        connect.addRow(self.connect_button)
        self.connect_error = QLabel()
        self.connect_error.setWordWrap(True)
        connect.addRow(self.connect_error)
        self.stack.addWidget(self.connect_page)

        self.lobby_page = QWidget()
        lobby = QVBoxLayout(self.lobby_page)
        self.room_label = QLabel("房间大厅")
        self.room_label.setObjectName("viewTitle")
        lobby.addWidget(self.room_label)
        create_row = QHBoxLayout()
        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("自定义 6 位房码（留空随机）")
        self.room_edit.setMaxLength(6)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("标准模式", "standard")
        self.mode_combo.addItem("自由模式", "free")
        self.env_edit = QLineEdit()
        self.env_edit.setPlaceholderText("环境别名或 6/8 位日期")
        self.create_button = QPushButton("创建房间")
        self.create_button.clicked.connect(self.create_room)
        for widget in (self.room_edit, self.mode_combo, self.env_edit, self.create_button):
            create_row.addWidget(widget)
        lobby.addLayout(create_row)
        join_row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("重连令牌（首次加入留空）")
        self.join_button = QPushButton("加入 / 重连")
        self.join_button.clicked.connect(self.join_room)
        join_row.addWidget(self.token_edit)
        join_row.addWidget(self.join_button)
        lobby.addLayout(join_row)
        self.self_label = QLabel()
        self.peer_label = QLabel("对手：等待加入")
        self.ready_label = QLabel("已准备：无")
        lobby.addWidget(self.self_label)
        lobby.addWidget(self.peer_label)
        lobby.addWidget(self.ready_label)
        self.lobby_status = QLabel("请创建或加入房间")
        self.lobby_status.setWordWrap(True)
        lobby.addWidget(self.lobby_status)
        actions = QHBoxLayout()
        self.ready_button = QPushButton("准备")
        self.ready_button.clicked.connect(self.toggle_ready)
        self.leave_button = QPushButton("离开房间")
        self.leave_button.clicked.connect(self.leave_room)
        self.env_button = QPushButton("房主修改环境")
        self.env_button.clicked.connect(self.change_environment)
        for widget in (self.ready_button, self.env_button, self.leave_button):
            actions.addWidget(widget)
        lobby.addLayout(actions)
        self.lobby_error = QLabel()
        self.lobby_error.setWordWrap(True)
        lobby.addWidget(self.lobby_error)
        lobby.addStretch(1)
        self.stack.addWidget(self.lobby_page)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QLineEdit, QComboBox {{ background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['line']}; padding: 6px; }}
        """)
        if hasattr(self, "battle"):
            self.battle.apply_theme(theme, colors)

    def reload_decks(self) -> None:
        self.entries = [entry for entry in deckstore.load_decks(self.base_db, self.store_path)
                        if entry.get("standard")]
        self.deck_combo.clear()
        for entry in self.entries:
            self.deck_combo.addItem(entry["name"])

    def connect_server(self) -> bool:
        if self.deck_combo.currentIndex() < 0:
            self.connect_error.setText("请先在卡组构筑中创建标准卡组")
            return False
        self.server_url = net.normalize_server_url(self.server_edit.text())
        error = self.probe(self.server_url)
        if error is not None:
            self.connect_error.setText(f"无法连接 {self.server_url}：{error}，请修改后重试")
            return False
        entry = self.entries[self.deck_combo.currentIndex()]
        self.player_name = self.name_edit.text().strip() or "玩家"
        self.deck_name = entry["name"]
        self.deck_code = deckstore.entry_code(entry)
        self.self_label.setText(f"你：{self.player_name}　卡组：{self.deck_name}")
        if not self._open_bridge():
            self.connect_error.setText("连接失败，请修改地址后重试")
            return False
        self.connect_error.clear()
        self.stack.setCurrentWidget(self.lobby_page)
        return True

    def _open_bridge(self) -> bool:
        try:
            ws = self.opener(self.server_url)
        except Exception as error:
            self.lobby_error.setText(f"连接失败：{error}")
            return False
        self.bridge = self.bridge_factory(ws)
        self.bridge.message.connect(self.handle_message)
        self.bridge.disconnected.connect(self.on_disconnected)
        self._expect_close = False
        self.bridge.start()
        return True

    def create_room(self) -> bool:
        if self.bridge is None:
            self.lobby_error.setText("请先连接服务器")
            return False
        room_id = self.room_edit.text().strip()
        if room_id and not re.fullmatch(r"[A-Za-z0-9]{6}", room_id):
            self.lobby_error.setText("房间代码须为 6 位大小写字母或数字")
            return False
        mode = self.mode_combo.currentData()
        try:
            env = parse_env_input(self.env_edit.text()) if mode == "free" else None
        except ValueError as error:
            self.lobby_error.setText(str(error))
            return False
        msg = {"type": "create", "name": self.player_name, "deck_code": self.deck_code,
               "debug": False, "client": net.CLIENT_ID, "mode": mode}
        if room_id:
            msg["room_id"] = room_id
        if env is not None:
            msg["env_date"] = env
        self.bridge.send(msg)
        self.lobby_error.clear()
        return True

    def join_room(self) -> bool:
        room_id = self.room_edit.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9]{6}", room_id):
            self.lobby_error.setText("请输入 6 位房间代码")
            return False
        if self.bridge is None and not self._open_bridge():
            return False
        token = self.token_edit.text().strip() or None
        self.bridge.send({"type": "join", "room_id": room_id, "name": self.player_name,
                          "deck_code": None if token else self.deck_code,
                          "token": token, "client": net.CLIENT_ID})
        self.lobby_error.clear()
        return True

    def toggle_ready(self) -> None:
        if self.bridge is not None:
            self.bridge.send({"type": "ready"})

    def leave_room(self) -> None:
        if self.bridge is not None and self.in_lobby:
            self.bridge.send({"type": "leave"})
        else:
            self.leave_to_menu()

    def change_environment(self) -> None:
        if self.bridge is None:
            return
        try:
            date = parse_env_input(self.env_edit.text())
        except ValueError as error:
            self.lobby_error.setText(str(error))
            return
        self.bridge.send({"type": "env", "date": date})

    def send_game_command(self, command: dict) -> None:
        if self.bridge is not None:
            self.bridge.send_cmd(command)

    def _apply_env(self, date: int | None) -> None:
        if date == self.env_date:
            return
        self.env_date = date
        self.db = self.base_db.at_date(date)
        self.battle.db = self.db

    def handle_message(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "joined":
            self.room_id = msg["room_id"]
            self.token = msg["token"]
            self.seat = msg["seat"]
            self.room_edit.setText(self.room_id)
            self.token_edit.setText(self.token)
            if "player_index" in msg:
                self.me = msg["player_index"]
                self.battle.me = self.me
                self.battle.reset_session()
            self.room_label.setText(f"房间 {self.room_id}")
            self.self_label.setText(f"你：{self.player_name}　卡组：{self.deck_name}")
            self.lobby_status.setText("已加入，等待对手……")
        elif kind == "lobby":
            self.in_lobby = True
            self.mode = msg.get("mode", "standard")
            self._apply_env(msg.get("env_date"))
            if self.mode == "free" and self.env_date is not None:
                self.env_edit.setText(str(self.env_date))
            self.lobby_ready = list(msg.get("ready") or [])
            self.lobby_deadline = msg.get("deadline")
            self.starting_deadline = None
            self.peer_label.setText("对手：已就位（卡组由服务端校验）")
            self.stack.setCurrentWidget(self.lobby_page)
            self._render_lobby()
        elif kind == "starting":
            self.starting_deadline = msg.get("deadline")
            self.lobby_deadline = None
            self._render_lobby()
        elif kind == "start":
            self.in_lobby = False
            self.me = msg["player_index"]
            self.battle.me = self.me
            self.battle.reset_session()
            self.mode = msg.get("mode", "standard")
            self._apply_env(msg.get("env_date"))
            self.battle.server_timer = None
            self.stack.setCurrentWidget(self.battle)
            self.lobby_status.setText(f"对局开始，对手：{msg.get('opponent', '')}")
        elif kind == "state":
            if self.me is None:
                return
            self._apply_env(self.env_date)
            self.battle.set_state(msg["payload"], timer=msg.get("timer"),
                                  log=msg.get("log") or [], timeline=msg.get("timeline") or [])
            self.stack.setCurrentWidget(self.battle)
        elif kind == "peer_left":
            self.in_lobby = False
            self.lobby_ready = []
            self.lobby_deadline = None
            self.starting_deadline = None
            self.peer_label.setText("对手：等待加入")
            self.lobby_status.setText(f"{msg.get('name', '对手')} 已离开，等待新对手")
            self._render_lobby()
        elif kind == "error":
            reason = msg.get("reason", "")
            if self.stack.currentWidget() is self.battle:
                self.battle.receive_error(reason)
            else:
                self.lobby_error.setText(f"服务器：{reason}")
        elif kind == "notice":
            text = f"公告：{msg.get('text', '')}"
            if self.stack.currentWidget() is self.battle:
                self.battle.error_label.setText(text)
            else:
                self.lobby_error.setText(text)
        elif kind == "game_over":
            self.stack.setCurrentWidget(self.battle)
            self.battle.show_game_over(msg.get("winner"), msg.get("reason", ""))
        elif kind == "dissolved":
            self.lobby_error.setText(f"房间已解散：{msg.get('reason', '')}")
            self.leave_to_menu()
        elif kind == "left":
            self.leave_to_menu()

    def _render_lobby(self) -> None:
        ready = "、".join(self.lobby_ready) or "无"
        self.ready_label.setText(f"已准备（{len(self.lobby_ready)}/2）：{ready}")
        own_ready = self.player_name in self.lobby_ready
        self.ready_button.setText("取消准备" if own_ready else "准备")
        self.ready_button.setEnabled(self.in_lobby)
        self.env_button.setEnabled(self.in_lobby and self.seat == 0
                                   and self.mode == "free" and not self.lobby_ready)
        self.env_edit.setEnabled(self.seat == 0 and self.mode == "free" and not self.lobby_ready)
        deadline = self.starting_deadline or self.lobby_deadline
        if deadline:
            left = max(0, round(deadline - time.time()))
            prefix = "对局开始" if self.starting_deadline else "自动准备"
            self.lobby_status.setText(f"{prefix}倒计时：{left} 秒")
        elif self.in_lobby:
            self.lobby_status.setText("双方已就位，请准备；一方准备后另一方 15 秒自动准备")

    def on_disconnected(self, reason: str) -> None:
        self.bridge = None
        self.battle.countdown_timer.stop()
        if self._expect_close:
            return
        self.in_lobby = False
        self.stack.setCurrentWidget(self.lobby_page)
        if self.room_id and self.token:
            self.room_edit.setText(self.room_id)
            self.token_edit.setText(self.token)
            self.lobby_status.setText(f"连接已断开：{reason}。请用原房码和令牌点击“加入 / 重连”")
        else:
            self.lobby_status.setText(f"连接已断开：{reason}")

    def leave_to_menu(self) -> None:
        self._expect_close = True
        if self.bridge is not None:
            self.bridge.close()
            self.bridge = None
        self.battle.timeline_timer.stop()
        self.battle.countdown_timer.stop()
        self.clock.stop()
        if self.on_back is not None:
            self.on_back()
