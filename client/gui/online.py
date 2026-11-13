"""桌面 GUI 联机模式：连接、大厅、NetBridge 与只读联机对局。"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from client import net
from client.gui.battle import HotseatView
from client.gui.ui_assets import load_gui_settings
from client.gui.widgets import show_warning
from core.engine import Game
from core.model import GameState, Ref
from db import deckstore
from db.envs import parse_env_input
from diy import runtime as diy_runtime
from diy import store as diy_store
from diy import sync as diy_sync


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

    exit_confirmation = False

    def __init__(self, db, send_command, on_back=None, parent=None):
        self.send_command = send_command
        self.me = 0
        self.payload: dict | None = None
        self.server_timer: dict | None = None
        self._awaiting_state = False
        self._game_over = False
        self._state_rendering = False
        self._deferred_state: tuple | None = None
        self.playback_allowed = True
        super().__init__(db, on_back=on_back, parent=parent)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_timer.start()

    def receive_trace(self, entries) -> None:
        for entry in entries:
            logging.getLogger("bwpro.battle").info(
                "服务端 trace %s seq=%s：%s",
                entry.get("kind"), entry.get("seq"), entry.get("message", ""))

    def reset_session(self) -> None:
        self._choice_generation += 1
        self.timeline_timer.stop()
        self._clear_usage()
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
        self._game_over = False
        self._deferred_state = None
        self._choice_key = None
        self._last_turn_key = None
        self._opening_banner_pending = True
        self.battle_scene.reset_animations()
        self.battle_scene.game_over = False
        self.battle_scene.hide_banner()
        self._close_choice_dialog()
        if self.playback_allowed and not self.countdown_timer.isActive():
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
        self._render_state()
        self._sync_pending_choice()

    def set_state(self, payload: dict, timer: dict | None = None,
                  log: list[str] | None = None,
                  timeline: list[dict] | None = None) -> None:
        self._choice_generation += 1
        if self._state_rendering:
            self._deferred_state = (payload, timer, log, timeline)
            return
        self._state_rendering = True
        self.timeline_timer.stop()
        loading = self.game is None
        if loading:
            self.battle_scene.show_loading("正在准备对局")
        try:
            self.payload = payload
            self.server_timer = timer
            self.game = Game(GameState.model_validate(payload), self.db)
            self.viewer = self.me
            self._clear_usage()
            self.pending_command = None
            self.target_specs = []
            self.legal_targets = []
            self._awaiting_state = False
            self._timeline_seen = len(self.game.state.timeline)
            self.stack.setCurrentWidget(self.battle_page)
            if timeline:
                for entry in timeline:
                    if entry.get("k") == "v":
                        continue  # 视觉事件由 BattleScene.sync_state 的增量路径播放
                    self.timeline_queue.append((entry.get("o"), entry.get("m", "")))
            elif log:
                self.played_timeline.extend((None, line) for line in log)
                self._render_log()
            self.refresh()
            self._update_countdown()
        finally:
            if loading:
                self.battle_scene.hide_loading()
            if (self.playback_allowed and self.timeline_queue
                    and not self.timeline_timer.isActive()):
                self.timeline_timer.start()
            self._state_rendering = False
            if self._deferred_state is not None:
                deferred = self._deferred_state
                self._deferred_state = None
                self.set_state(*deferred)

    def _can_send(self, command: dict) -> bool:
        if (self.game is None or self._awaiting_state or self._game_over
                or self.game.state.winner is not None):
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
        try:
            accepted = self.send_command(_json_command(command))
        except Exception as error:
            self.receive_error(f"指令发送失败：{error}")
            return False
        if accepted is False:
            self.receive_error("指令发送失败：连接已断开")
            return False
        self._awaiting_state = True
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self.error_label.clear()
        self._update_input_widgets()
        return True

    def _inputs_open(self) -> bool:
        if self._awaiting_state or self._game_over or self.game is None:
            return False
        state = self.game.state
        if state.phase == "mulligan":
            own_context = not state.players[self.me].mulligan_done
        else:
            own_context = state.active == self.me
        return own_context and super()._inputs_open()

    def _sync_pending_choice(self) -> None:
        if self._awaiting_state:
            self._close_choice_dialog()
            return
        pending = self.game.state.pending_choice if self.game is not None else None
        if pending is not None and pending.get("player") != self.me:
            self._close_choice_dialog()
            return
        super()._sync_pending_choice()

    def _render_state(self, play_pending=True) -> None:
        super()._render_state(play_pending=play_pending)
        self.battle_scene.game_over = self.battle_scene.game_over or self._game_over
        self._update_countdown()

    def _update_countdown(self) -> None:
        if self.game is None:
            return
        if not self.server_timer:
            return
        left = max(0, int(self.server_timer.get("deadline", 0) - time.time()))
        minutes, seconds = divmod(left, 60)
        prefix = "调度" if self.server_timer.get("kind") == "mulligan" else "回合"
        self._update_phase_label(f"{prefix} {minutes}:{seconds:02d}")

    def receive_error(self, reason: str) -> None:
        self._awaiting_state = False
        self.error_label.setText(f"服务器：{reason}")
        self._render_state()
        self._sync_pending_choice()

    def show_game_over(self, winner: int | None, reason: str = "") -> None:
        self._choice_generation += 1
        self._game_over = True
        self.battle_scene.game_over = True
        self.cancel_targeting()
        if self.choice_dialog is not None:
            self.choice_dialog.hide()
            self.choice_dialog = None
        self._choice_key = None
        if winner is None:
            self.result_banner.setText(f"对局终止（{reason}）")
            self.result_banner.show()
            self.result_back.show()
        elif self.result_banner.isHidden():
            self._show_result()

    def return_to_menu(self) -> None:
        self.countdown_timer.stop()
        super().return_to_menu()


class OnlineView(QWidget):
    """联机连接页、大厅与联机对局容器。"""

    connection_succeeded = Signal(object, str)
    connection_failed = Signal(str, str)
    connection_changed = Signal()

    def __init__(self, db, store_path: Path = deckstore.PATH, on_back=None,
                 bridge_factory=NetBridge, official_db=None, parent=None):
        super().__init__(parent)
        self.official_db = official_db if official_db is not None else db
        self.diy_db = db
        self.base_db = self.official_db
        self.db = self.base_db
        self.store_path = Path(store_path)
        self.on_back = on_back
        self.bridge_factory = bridge_factory
        self.bridge = None
        self.opener = net._open_ws
        self._connecting = False
        self._connect_thread: threading.Thread | None = None
        self._client_ip = ""
        self._pending_join = False
        self._pending_reconnect = False
        self.server_url = ""
        self.player_name = load_gui_settings()["player_name"]
        self.deck_name = ""
        self.deck_code: str | None = None
        self.room_id: str | None = None
        self.token: str | None = None
        self.reconnect_code: str | None = None
        self.seat: int | None = None
        self.me: int | None = None
        self.mode = "standard"
        self.env_date: int | None = None
        self.room_diy = False
        self._diy_local: dict[int, dict] = {}
        self._diy_required: dict[int, str] | None = None
        self._diy_done_key = None
        self._diy_syncing = False
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
        self.connection_succeeded.connect(self._connection_succeeded)
        self.connection_failed.connect(self._connection_failed)
        self.reload_decks()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.connect_page = QWidget()
        connect = QFormLayout(self.connect_page)
        self.server_edit = QLineEdit("bwpro.varisox137.top")
        connect.addRow("服务器地址", self.server_edit)
        self.connect_button = QPushButton("连接并进入大厅")
        self.connect_button.setFixedSize(200, 36)
        self.connect_button.clicked.connect(self.connect_server)
        connect.addRow(self.connect_button)
        self.stack.addWidget(self.connect_page)

        self.lobby_page = QWidget()
        lobby = QVBoxLayout(self.lobby_page)
        self.room_label = QLabel("房间大厅")
        self.room_label.setObjectName("viewTitle")
        lobby.addWidget(self.room_label)
        self.deck_combo = QComboBox()
        self.deck_combo.currentIndexChanged.connect(self._select_deck)
        deck_row = QHBoxLayout()
        self.deck_label = QLabel("选择卡组")
        deck_row.addWidget(self.deck_label)
        deck_row.addWidget(self.deck_combo, 1)
        lobby.addLayout(deck_row)
        create_row = QHBoxLayout()
        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("自定义 6 位房码（留空随机）")
        self.room_edit.setMaxLength(6)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("标准模式", "standard")
        self.mode_combo.addItem("自由模式", "free")
        self.mode_combo.currentIndexChanged.connect(self._render_lobby)
        self.env_edit = QLineEdit()
        self.env_edit.setPlaceholderText("环境别名或 6/8 位日期")
        self.create_button = QPushButton("创建房间")
        self.create_button.setFixedSize(140, 36)
        self.create_button.clicked.connect(self.create_room)
        for widget in (self.room_edit, self.mode_combo, self.env_edit, self.create_button):
            create_row.addWidget(widget)
        lobby.addLayout(create_row)
        self.diy_checkbox = QCheckBox("启用 DIY 内容")
        self.diy_checkbox.setChecked(False)
        self.diy_checkbox.toggled.connect(self._change_diy)
        lobby.addWidget(self.diy_checkbox)
        join_row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Normal)
        self.token_edit.setReadOnly(True)
        self.token_edit.setPlaceholderText("重连令牌（首次加入留空）")
        self.join_button = QPushButton("加入 / 重连")
        self.join_button.setFixedSize(160, 36)
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
        for widget, width in ((self.ready_button, 110),
                              (self.env_button, 150), (self.leave_button, 120)):
            widget.setFixedSize(width, 36)
            actions.addWidget(widget)
        actions.addStretch(1)
        self.leave_button.setEnabled(False)
        lobby.addLayout(actions)
        self.lobby_error = QLabel()
        self.lobby_error.setWordWrap(True)
        lobby.addWidget(self.lobby_error)
        lobby.addStretch(1)
        for button in (self.connect_button, self.create_button, self.join_button,
                       self.ready_button, self.env_button, self.leave_button):
            button.setObjectName("small")
        self.stack.addWidget(self.lobby_page)
        self._render_lobby()

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QLineEdit, QComboBox {{ background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['line']}; padding: 6px; }}
        """)
        if hasattr(self, "battle"):
            self.battle.apply_theme(theme, colors)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.battle.playback_allowed = True
        if not self.clock.isActive():
            self.clock.start()
        if not self.battle.countdown_timer.isActive():
            self.battle.countdown_timer.start()
        if self.battle.timeline_queue and not self.battle.timeline_timer.isActive():
            self.battle.timeline_timer.start()

    def _change_diy(self) -> None:
        if self.room_id is not None:
            return
        self._set_base_db(self.diy_db if self.diy_checkbox.isChecked() else self.official_db)
        self.reload_decks()

    def reload_decks(self) -> None:
        self.entries = [entry for entry in deckstore.load_decks(self.base_db, self.store_path)
                        if entry.get("standard")]
        self.deck_combo.clear()
        for entry in self.entries:
            self.deck_combo.addItem(entry["name"])
        self._select_deck(self.deck_combo.currentIndex())

    def _select_deck(self, index: int) -> None:
        if 0 <= index < len(self.entries):
            entry = self.entries[index]
            self.deck_name = entry["name"]
            self.deck_code = deckstore.entry_code(entry)
        else:
            self.deck_name = ""
            self.deck_code = None
        deck_text = f"　卡组：{self.deck_name}" if self.deck_name else ""
        self.self_label.setText(f"你：{self.player_name}{deck_text}")

    def _require_deck(self) -> bool:
        if self.deck_code:
            return True
        self.lobby_error.setText("请先选择标准卡组")
        return False

    def connect_server(self, *, refresh_identity: bool = True,
                       reconnect: bool = False) -> bool:
        if self._connecting:
            return False
        self._pending_join = False
        self._pending_reconnect = reconnect
        url = net.normalize_server_url(self.server_edit.text())
        self.server_url = url
        if refresh_identity:
            self.player_name = load_gui_settings()["player_name"]
        self._select_deck(self.deck_combo.currentIndex())
        self._client_ip = ""
        self._expect_close = False
        self._connecting = True
        self.connect_button.setEnabled(False)
        self.connect_button.setText("正在连接……")

        def connect():
            try:
                ws = self.opener(url)
            except Exception as error:
                self.connection_failed.emit(url, str(error))
            else:
                self._client_ip = net.public_ip()
                self.connection_succeeded.emit(ws, url)

        self._connect_thread = threading.Thread(target=connect, daemon=True)
        self._connect_thread.start()
        return True

    def _reset_connect_button(self) -> None:
        self._connecting = False
        self._connect_thread = None
        self.connect_button.setEnabled(True)
        self.connect_button.setText("连接并进入大厅")

    def _connection_failed(self, url: str, reason: str) -> None:
        if not self._connecting:
            return
        self._pending_join = False
        self._reset_connect_button()
        if not self._expect_close:
            show_warning(self, "连接失败", f"无法连接 {url}：{reason}，请修改后重试")

    def _connection_succeeded(self, ws, url: str) -> None:
        pending_join = self._pending_join
        pending_reconnect = self._pending_reconnect
        self._pending_join = self._pending_reconnect = False
        if not self._connecting:
            ws.close()
            return
        self._reset_connect_button()
        if self._expect_close:
            ws.close()
            return
        self.server_url = url
        if self._open_bridge(ws):
            self.stack.setCurrentWidget(self.lobby_page)
            self._render_lobby()
            self.connection_changed.emit()
            if pending_reconnect:
                self._send_auto_reconnect()
            elif pending_join:
                self.join_room()

    def _send_auto_reconnect(self) -> None:
        if not self.room_id or not self.reconnect_code or not self._client_ip:
            self.battle.error_label.setText("无法获取公网 IP，自动重连未完成")
            return
        self.bridge.send({
            "type": "join", "room_id": self.room_id,
            "reconnect_code": self.reconnect_code,
            "name": self.player_name, "deck_code": None,
            **net.hello_metadata(self._client_ip),
        })

    def _open_bridge(self, ws=None) -> bool:
        if ws is None:
            try:
                ws = self.opener(self.server_url)
            except Exception as error:
                show_warning(self, "连接失败", str(error))
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
        if not self._require_deck():
            return False
        room_id = self.room_edit.text().strip()
        if room_id and not re.fullmatch(r"[A-Za-z0-9]{6}", room_id):
            self.lobby_error.setText("房间代码须为 6 位大小写字母或数字")
            return False
        mode = self.mode_combo.currentData()
        if mode == "free" and not self.env_edit.text().strip():
            self.lobby_error.setText("自由模式必须输入环境别名或日期")
            return False
        try:
            env = parse_env_input(self.env_edit.text()) if mode == "free" else None
        except ValueError as error:
            self.lobby_error.setText(str(error))
            return False
        msg = {"type": "create", "name": self.player_name, "deck_code": self.deck_code,
               "debug": False, "mode": mode,
               "cardback": load_gui_settings()["own_cardback"],
               **net.hello_metadata(self._client_ip)}
        if room_id:
            msg["room_id"] = room_id
        if env is not None:
            msg["env_date"] = env
        if self.diy_checkbox.isChecked():
            msg["diy"] = True
        self.bridge.send(msg)
        self.lobby_error.clear()
        return True

    def join_room(self) -> bool:
        room_id = self.room_edit.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9]{6}", room_id):
            self.lobby_error.setText("请输入 6 位房间代码")
            return False
        token = self.token_edit.text().strip() or None
        if token is None and not self._require_deck():
            return False
        if self.bridge is None:
            if self._connecting:
                return False
            if self.server_url:
                self.server_edit.setText(self.server_url)
            if not self.connect_server(refresh_identity=token is None):
                return False
            self._pending_join = True
            return True
        msg = {"type": "join", "room_id": room_id, "name": self.player_name,
               "deck_code": None if token else self.deck_code,
               "token": token, "cardback": load_gui_settings()["own_cardback"],
               **net.hello_metadata(self._client_ip)}
        if self.diy_checkbox.isChecked():
            msg["diy"] = True
        self.bridge.send(msg)
        self.lobby_error.clear()
        return True

    def toggle_ready(self) -> None:
        if self.bridge is not None:
            self.bridge.send({"type": "ready"})

    def leave_room(self) -> None:
        if self.bridge is not None and self.room_id is not None:
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

    def send_game_command(self, command: dict) -> bool:
        if self.bridge is None:
            return False
        try:
            self.bridge.send_cmd(command)
        except Exception as error:
            self.lobby_error.setText(f"指令发送失败：{error}")
            return False
        return True

    def _apply_env(self, date: int | None) -> None:
        if date == self.env_date:
            return
        self.env_date = date
        self.db = self.base_db.at_date(date)
        self.battle.db = self.db
        self.battle.battle_scene.db = self.db

    def _set_base_db(self, db) -> None:
        self.base_db = db
        self.db = db.at_date(self.env_date)
        self.battle.db = self.db
        self.battle.battle_scene.db = self.db

    def _reset_diy_client(self) -> None:
        self._diy_local = {}
        self._diy_required = None
        self._diy_done_key = None
        self._diy_syncing = False

    def _collect_diy_packages(self) -> dict[int, dict]:
        packages = diy_sync.collect_packages([diy_runtime.BUILTIN_CONTENT_ROOT])
        for path in diy_store.downloaded_versions():
            package = diy_sync.read_package(path)
            pack_id = package["pack_id"]
            previous = packages.get(pack_id)
            if previous is not None:
                if previous["content_hash"] != package["content_hash"]:
                    raise ValueError(f"DIY 包 {pack_id} 的自有与下载版本冲突")
                continue
            packages[pack_id] = package
        return packages

    def _report_diy_manifest(self) -> None:
        try:
            self._diy_local = self._collect_diy_packages()
            packs = diy_sync.package_manifest(self._diy_local)
        except (OSError, ValueError, RuntimeError) as error:
            self._diy_client_error(str(error))
            return
        self._diy_syncing = True
        self._diy_required = None
        self._diy_done_key = None
        self.lobby_status.setText("正在同步 DIY 内容：已上报本地包清单")
        self.bridge.send({"type": "diy_manifest", "packs": packs})

    def _send_diy_package(self, pack_id: int, digest: str) -> None:
        package = self._diy_local.get(pack_id)
        if package is None or package["content_hash"] != digest:
            self._diy_client_error(f"本地找不到服务器请求的 DIY 包 {pack_id}（{digest}）")
            return
        self.bridge.send({"type": "diy_pack", "package": package})

    def _receive_diy_package(self, package: dict) -> None:
        try:
            validated = diy_sync.validate_package(package)
            pack_id, digest = validated["pack_id"], validated["content_hash"]
            if self._diy_required is None \
                    or self._diy_required.get(pack_id) != digest:
                raise ValueError("收到未在当前同步清单中的 DIY 包")
            diy_store.save_download(validated)
            self._diy_local[pack_id] = validated
            self._set_base_db(diy_runtime.load_database(
                download_versions=dict(self._diy_required)))
        except (OSError, ValueError, RuntimeError) as error:
            self._diy_client_error(f"DIY 包下载或加载失败：{error}")
            return
        self.lobby_status.setText(f"已下载并校验 DIY 包 {pack_id}")
        self._maybe_finish_diy_sync()

    def _maybe_finish_diy_sync(self) -> None:
        if not self._diy_syncing or self._diy_required is None:
            return
        key = tuple(sorted(self._diy_required.items()))
        if key == self._diy_done_key:
            return
        if any(self._diy_local.get(pack_id, {}).get("content_hash") != digest
               for pack_id, digest in key):
            return
        self._diy_done_key = key
        self.bridge.send({"type": "diy_sync_done"})

    def _diy_client_error(self, reason: str) -> None:
        self.lobby_error.setText(f"DIY 同步失败：{reason}")
        if self.bridge is not None:
            self.bridge.send({"type": "diy_sync_error", "reason": reason})

    def active_downloads(self) -> set[tuple[int, str]]:
        if self.room_id is None or not self.room_diy:
            return set()
        selected = self._diy_required
        return {(int(path.parent.name), path.name)
                for path in diy_store.downloaded_versions(selected=selected)}

    def refresh_downloaded_database(self) -> None:
        self.diy_db = diy_runtime.load_database()
        self._set_base_db(self.diy_db if self.diy_checkbox.isChecked() else self.official_db)
        self._reset_diy_client()
        self.reload_decks()

    def handle_message(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "joined":
            if "player_index" not in msg:
                self.reconnect_code = None
            self.room_id = msg["room_id"]
            self.token = msg["token"]
            self.seat = msg["seat"]
            self.room_diy = bool(msg.get("diy"))
            self.diy_checkbox.setChecked(self.room_diy)
            self._reset_diy_client()
            if self.room_diy and "diy_required" in msg:
                self._diy_required = diy_sync.validate_manifest(msg["diy_required"])
            self.room_edit.setText(self.room_id)
            self.token_edit.setText(self.token)
            self.battle.reset_session()
            if "player_index" in msg:
                self.me = msg["player_index"]
                self.battle.me = self.me
            self.room_label.setText(f"房间 {self.room_id}")
            self.self_label.setText(f"你：{self.player_name}　卡组：{self.deck_name}")
            self.lobby_status.setText("已加入，等待对手……")
            self._render_lobby()
        elif kind == "lobby":
            self.in_lobby = True
            self.mode = msg.get("mode", "standard")
            self.room_diy = bool(msg.get("diy"))
            self._apply_env(msg.get("env_date"))
            if self.mode == "free" and self.env_date is not None:
                self.env_edit.setText(str(self.env_date))
            self.lobby_ready = list(msg.get("ready") or [])
            self.lobby_deadline = msg.get("deadline")
            self.starting_deadline = None
            self.peer_label.setText("对手：已就位（卡组由服务端校验）")
            self.stack.setCurrentWidget(self.lobby_page)
            self._render_lobby()
        elif kind == "diy_sync_request":
            self._report_diy_manifest()
        elif kind == "diy_upload_request":
            self._send_diy_package(msg.get("pack_id"), msg.get("content_hash"))
        elif kind == "diy_sync_state":
            try:
                self._diy_required = diy_sync.validate_manifest(msg.get("required"))
            except ValueError as error:
                self._diy_client_error(str(error))
            else:
                self._maybe_finish_diy_sync()
        elif kind == "diy_package":
            self._receive_diy_package(msg.get("package"))
        elif kind == "diy_sync_failed":
            self._diy_syncing = False
            self.lobby_error.setText(f"DIY 同步失败：{msg.get('reason', '未知错误')}")
            self.leave_room()
        elif kind == "starting":
            self._diy_syncing = False
            self.starting_deadline = msg.get("deadline")
            self.lobby_deadline = None
            self._render_lobby()
        elif kind == "start":
            self.in_lobby = False
            self.reconnect_code = msg.get("reconnect_code")
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
            self.battle.receive_trace(msg.get("trace") or [])
            self.battle.battle_scene.set_enemy_cardback(msg.get("opponent_cardback"))
            self.battle.set_state(msg["payload"], timer=msg.get("timer"),
                                  log=msg.get("log") or [], timeline=msg.get("timeline") or [])
            self.stack.setCurrentWidget(self.battle)
        elif kind == "peer_left":
            self.in_lobby = False
            self.lobby_ready = []
            self.lobby_deadline = None
            self.starting_deadline = None
            self._reset_diy_client()
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
            self.reconnect_code = None
            self.stack.setCurrentWidget(self.battle)
            self.battle.show_game_over(msg.get("winner"), msg.get("reason", ""))
        elif kind == "dissolved":
            self.reconnect_code = None
            self.lobby_error.setText(f"房间已解散：{msg.get('reason', '')}")
            self.leave_to_menu()
        elif kind == "left":
            self._room_left()

    def _room_left(self) -> None:
        """离开当前房间但保持服务器连接，停留在可创建/加入的大厅。"""
        self.in_lobby = False
        self.room_id = self.token = self.seat = self.me = None
        self.reconnect_code = None
        self.room_diy = False
        self._reset_diy_client()
        self.token_edit.clear()
        self.lobby_ready = []
        self.lobby_deadline = self.starting_deadline = None
        self.room_label.setText("房间大厅")
        self.peer_label.setText("对手：等待加入")
        self.lobby_status.setText("已离开房间，可创建或加入其他房间")
        self.stack.setCurrentWidget(self.lobby_page)
        self._render_lobby()

    def _render_lobby(self) -> None:
        in_room = self.room_id is not None
        for widget in (self.room_label, self.self_label, self.peer_label,
                       self.ready_label, self.ready_button, self.leave_button):
            widget.setVisible(in_room)
        self.env_button.setVisible(in_room and self.mode == "free")
        self.diy_checkbox.setEnabled(not in_room)
        ready = "、".join(self.lobby_ready) or "无"
        self.ready_label.setText(f"已准备（{len(self.lobby_ready)}/2）：{ready}")
        own_ready = self.player_name in self.lobby_ready
        self.ready_button.setText("取消准备" if own_ready else "准备")
        self.ready_button.setEnabled(self.in_lobby and not self._diy_syncing)
        self.leave_button.setEnabled(in_room)
        self.env_button.setEnabled(self.in_lobby and self.seat == 0
                                   and self.mode == "free" and not self.lobby_ready)
        creating_free = (self.room_id is None and self.bridge is not None
                         and self.mode_combo.currentData() == "free")
        owner_can_edit = (self.seat == 0 and self.mode == "free"
                          and not self.lobby_ready)
        self.env_edit.setEnabled(creating_free or owner_can_edit)
        deadline = self.starting_deadline or self.lobby_deadline
        if deadline:
            left = max(0, round(deadline - time.time()))
            prefix = "对局开始" if self.starting_deadline else "自动准备"
            self.lobby_status.setText(f"{prefix}倒计时：{left} 秒")
        elif self._diy_syncing:
            self.lobby_status.setText("正在同步并校验 DIY 内容，完成后进入开始倒计时")
        elif self.in_lobby:
            self.lobby_status.setText("双方已就位，请准备；一方准备后另一方 15 秒自动准备")

    def on_disconnected(self, reason: str) -> None:
        self.bridge = None
        self.battle.countdown_timer.stop()
        if self._expect_close:
            return
        self.in_lobby = False
        if self.room_id and self.reconnect_code:
            self.battle.error_label.setText(f"连接已断开：{reason}；正在自动重连")
            self.server_edit.setText(self.server_url)
            self.connect_server(refresh_identity=False, reconnect=True)
            self.connection_changed.emit()
            return
        self.stack.setCurrentWidget(self.lobby_page)
        if self.room_id and self.token:
            self.room_edit.setText(self.room_id)
            self.token_edit.setText(self.token)
            self.lobby_status.setText(f"连接已断开：{reason}。请用原房码和令牌点击“加入 / 重连”")
        else:
            self.lobby_status.setText(f"连接已断开：{reason}")
        self.connection_changed.emit()

    def back_to_previous(self) -> bool:
        """联机页分层返回：大厅 → 未连接页 → 主菜单。"""
        self._pending_join = False
        if self.stack.currentWidget() is not self.lobby_page:
            self.leave_to_menu()
            return True
        self._expect_close = True
        if self.bridge is not None:
            self.bridge.close()
            self.bridge = None
        self.in_lobby = False
        self.room_id = self.token = self.seat = self.me = None
        self.reconnect_code = None
        self.room_diy = False
        self._reset_diy_client()
        self.token_edit.clear()
        self.lobby_ready = []
        self.lobby_deadline = self.starting_deadline = None
        self._render_lobby()
        self.stack.setCurrentWidget(self.connect_page)
        self._reset_connect_button()
        self.connection_changed.emit()
        return False

    def leave_to_menu(self) -> None:
        self._pending_join = False
        self.battle.playback_allowed = False
        self.battle.timeline_timer.stop()
        self.battle.countdown_timer.stop()
        self.clock.stop()
        if self.on_back is not None:
            self.on_back()
