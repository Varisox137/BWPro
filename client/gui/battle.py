"""桌面 GUI 本地热坐对战：标准卡组开局、场况、操作与结算播放。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from client import cli
from client.gui.cardart import card_pixmap
from client.gui.widgets import CardDetailDialog, polish_dialog_buttons
from core import targets
from core.engine import IllegalAction
from core.model import Ref
from core.setup import new_game
from db import deckstore


class DeckSelectDialog(QDialog):
    """开局卡组选择：仅列满足当前标准规则的本地卡组。"""

    def __init__(self, db, store_path: Path, player_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{player_name} 选择卡组")
        self.resize(520, 480)
        self.entries = [entry for entry in deckstore.load_decks(db, store_path)
                        if entry.get("standard")]
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{player_name}：仅显示标准卡组"))
        self.list = QListWidget()
        for entry in self.entries:
            QListWidgetItem(f"{entry['name']}（{len(deckstore.entry_deck(entry)[1])} 张）",
                            self.list)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        polish_dialog_buttons(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.entries))

    def selected_entry(self) -> dict:
        return self.entries[self.list.currentRow()]


class UsageDialog(QDialog):
    """手牌使用方式选择，保留不合法项及原因。"""

    def __init__(self, options: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择使用方式")
        self.setMinimumWidth(520)
        self.selected_id = None
        self._accepted = False
        layout = QVBoxLayout(self)
        for option in options:
            energy = f"　能量 {option['energy']}" if option["energy"] else ""
            reason = "" if option["ok"] else f"\n不可用：{option['reason']}"
            effect = f"\n{option['effect']}" if option["effect"] else ""
            button = QPushButton(
                f"{option['label']}　鬼火 {option['cost']}{energy}{effect}{reason}")
            button.setEnabled(option["ok"])
            button.clicked.connect(lambda _=False, oid=option["id"]: self._choose(oid))
            layout.addWidget(button)
        cancel = QDialogButtonBox(QDialogButtonBox.Cancel)
        polish_dialog_buttons(cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)

    def _choose(self, option_id) -> None:
        self.selected_id = option_id
        self._accepted = True
        self.accept()


class ChoiceDialog(QDialog):
    """结算中选择：卡牌 uid、卡牌/式神数据 id 与灵咒名统一作答。"""

    def __init__(self, view: "HotseatView", pending: dict):
        super().__init__(view)
        self.setWindowTitle("结算选择")
        self.setModal(False)
        self.pending = pending
        layout = QVBoxLayout(self)
        kind = pending.get("kind")
        player = view.game.state.players[pending["player"]]
        titles = {
            "deck_top_pick": "检视牌库顶，选择一张置入手牌",
            "mulligan_pick": "选择一张手牌调度，或结束调度",
            "discard_pick": "选择一张手牌弃置",
            "quest_complete_pick": "选择一张紧急委托，使其视为达成",
            "card_name": "选择敌方式神" if pending.get("stage") == "shikigami" else "选择一张牌名",
            "field_summon_pick": "选择要召唤的幻境",
            "pick_generate": "选择一张牌置入手牌",
            "invocation_pick": "选择一张灵咒牌结附",
        }
        layout.addWidget(QLabel(f"{player.name}：{titles.get(kind, '请选择一项')}"))
        for option in pending.get("options", []):
            button = QPushButton(view.choice_option_label(pending, option))
            button.clicked.connect(lambda _=False, value=option: self._answer(value))
            layout.addWidget(button)
        if kind == "mulligan_pick":
            done = QPushButton("结束调度")
            done.clicked.connect(lambda: self._answer(None))
            layout.addWidget(done)
        self.resize(560, min(700, 120 + 70 * len(pending.get("options", []))))

    def _answer(self, value) -> None:
        view = self.parent()
        view.answer_pending(value)
        self.close()

    def reject(self) -> None:
        pass


class ShikiFrame(QFrame):
    """单个式神通槽，含目标高亮与出击/升级操作。"""

    details_requested = Signal(object)
    assault_requested = Signal(int)
    upgrade_requested = Signal(int)

    def __init__(self, pi: int, index: int):
        super().__init__()
        self.pi = pi
        self.index = index
        self.ref = Ref(player=pi, shikigami=index)
        self.setObjectName("shikiSlot")
        self.setFixedSize(148, 108)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(1)
        self.name_label = QLabel()
        self.name_label.setObjectName("shikiName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        self.stats_label = QLabel()
        self.stats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stats_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        for label in (self.name_label, self.stats_label, self.status_label):
            label.setStyleSheet("background: transparent; font-size: 11px;")
        actions = QHBoxLayout()
        self.detail_button = QPushButton("详情")
        self.assault_button = QPushButton("出击")
        self.upgrade_button = QPushButton("升级")
        for button in (self.detail_button, self.assault_button, self.upgrade_button):
            button.setObjectName("battleSmall")
            actions.addWidget(button)
        self.detail_button.clicked.connect(lambda: self.details_requested.emit(self.ref))
        self.assault_button.clicked.connect(lambda: self.assault_requested.emit(self.index))
        self.upgrade_button.clicked.connect(lambda: self.upgrade_requested.emit(self.index))
        layout.addLayout(actions)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.details_requested.emit(self.ref)
        super().mouseReleaseEvent(event)


class HandCardFrame(QFrame):
    """紧凑手牌卡面：实时费用、数值、关键字和合法性徽标。"""

    play_requested = Signal(int)
    detail_requested = Signal(object)
    mulligan_requested = Signal(int)

    def __init__(self, card, db=None):
        super().__init__()
        self.card = card
        self.setObjectName("handCard")
        self.setMinimumSize(170, 180)
        self.setMaximumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        self.art_label = QLabel()
        self.art_label.setObjectName("handArt")
        self.art_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.art_label)
        self.name_label = QLabel()
        self.name_label.setObjectName("handName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        cdef = db.cards.get(card.id) if db is not None else None
        pixmap = card_pixmap(cdef, db) if cdef is not None else None
        if pixmap is not None and not pixmap.isNull():
            self.art_label.setPixmap(pixmap.scaled(
                60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.name_label.hide()
        else:
            self.art_label.hide()
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label, 1)
        self.play_button = QPushButton("使用")
        self.detail_button = QPushButton("详情")
        self.mulligan_button = QPushButton("调度")
        for button in (self.play_button, self.detail_button, self.mulligan_button):
            button.setObjectName("battleSmall")
            layout.addWidget(button)
        self.play_button.clicked.connect(lambda: self.play_requested.emit(card.uid))
        self.detail_button.clicked.connect(lambda: self.detail_requested.emit(card))
        self.mulligan_button.clicked.connect(lambda: self.mulligan_requested.emit(card.uid))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.play_requested.emit(self.card.uid)
        super().mouseReleaseEvent(event)


class HotseatView(QWidget):
    """热坐单屏视图；手牌与非公开结算仅显示当前行动/作答方。"""

    def __init__(self, db, store_path: Path = deckstore.PATH, on_back=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.store_path = Path(store_path)
        self.on_back = on_back
        self.theme = "light"
        self.colors: dict = {}
        self.game = None
        self.viewer = 0
        self.player_frames: dict[int, QFrame] = {}
        self.player_labels: dict[int, QLabel] = {}
        self.field_labels: dict[int, QLabel] = {}
        self.shiki_frames: dict[tuple[int, int], ShikiFrame] = {}
        self.hand_frames: list[HandCardFrame] = []
        self.pending_command: dict | None = None
        self.target_specs: list[tuple[str, object]] = []
        self.legal_targets: list[Ref] = []
        self.choice_dialog: ChoiceDialog | None = None
        self._choice_key = None
        self._handoff_pending = False
        self.handoff_dialog: QDialog | None = None
        self._timeline_seen = 0
        self.timeline_queue: list[tuple[int | None, str]] = []
        self.played_timeline: list[tuple[int | None, str]] = []
        self._build_ui()
        self.timeline_timer = QTimer(self)
        self.timeline_timer.setInterval(300)
        self.timeline_timer.timeout.connect(self.play_next_timeline)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.setup_page = QWidget()
        setup = QVBoxLayout(self.setup_page)
        setup.addStretch(1)
        title = QLabel("本地热坐")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignCenter)
        setup.addWidget(title)
        hint = QLabel("双方依次选择本地标准卡组，在同一设备轮流操作")
        hint.setAlignment(Qt.AlignCenter)
        setup.addWidget(hint)
        self.start_button = QPushButton("开始对战")
        self.start_button.clicked.connect(self.start_hotseat)
        setup.addWidget(self.start_button, alignment=Qt.AlignCenter)
        setup.addStretch(1)
        self.stack.addWidget(self.setup_page)
        self.battle_page = QWidget()
        self._build_battle_page()
        self.stack.addWidget(self.battle_page)

    def _build_battle_page(self) -> None:
        layout = QHBoxLayout(self.battle_page)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(3)
        layout.addLayout(main, 1)
        top = QHBoxLayout()
        self.menu_button = QPushButton("退出对局")
        self.menu_button.setObjectName("battleSmall")
        self.menu_button.clicked.connect(self.return_to_menu)
        top.addWidget(self.menu_button)
        self.phase_label = QLabel()
        self.phase_label.setObjectName("phaseLabel")
        top.addWidget(self.phase_label)
        top.addStretch(1)
        self.log_button = QPushButton("战斗记录")
        self.log_button.setObjectName("battleSmall")
        self.log_button.clicked.connect(self.show_log)
        self.log_sidebar = QWidget()
        sidebar = QVBoxLayout(self.log_sidebar)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.addStretch(1)
        sidebar.addWidget(self.log_button, 0, Qt.AlignLeft)
        sidebar.addStretch(1)
        layout.insertWidget(0, self.log_sidebar)
        self.end_turn_button = QPushButton("结束\n回合")
        self.end_turn_button.setObjectName("endTurnButton")
        self.end_turn_button.setFixedSize(104, 104)
        self.end_turn_button.clicked.connect(self.end_turn)
        self._build_right_sidebar(layout)
        main.addLayout(top)
        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle("战斗记录")
        self.log_dialog.setModal(False)
        self.log_dialog.resize(420, 560)
        log_layout = QVBoxLayout(self.log_dialog)
        self.log_list = QListWidget()
        self.log_list.setObjectName("battleLog")
        log_layout.addWidget(self.log_list)
        log_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(log_buttons)
        log_buttons.rejected.connect(self.log_dialog.reject)
        log_layout.addWidget(log_buttons, alignment=Qt.AlignRight)
        self._slot_cells = {"top": [], "bottom": []}
        self._perspective_viewer = None
        self._build_perspective_row(main, "top")
        self._build_combat_zone(main)
        self._build_perspective_row(main, "bottom")
        for pi in (0, 1):
            self._build_player_panel(pi)
            for index in range(4):
                self._build_shiki_slot(pi, index)
        self._sync_perspective()
        self.target_label = QLabel()
        self.target_label.setObjectName("targetHint")
        main.addWidget(self.target_label)
        target_actions = QHBoxLayout()
        self.cancel_target_button = QPushButton("取消目标")
        self.default_target_button = QPushButton("默认战斗区")
        for button in (self.cancel_target_button, self.default_target_button):
            button.setObjectName("battleSmall")
            target_actions.addWidget(button)
        self.cancel_target_button.clicked.connect(self.cancel_targeting)
        self.default_target_button.clicked.connect(self.confirm_default_target)
        main.addLayout(target_actions)
        self.hand_caption = QLabel()
        main.addWidget(self.hand_caption)
        hand_scroll = QScrollArea()
        hand_scroll.setWidgetResizable(True)
        hand_scroll.setMinimumHeight(0)
        hand_scroll.setMaximumHeight(230)
        self.hand_container = QWidget()
        self.hand_layout = QHBoxLayout(self.hand_container)
        hand_scroll.setWidget(self.hand_container)
        main.addWidget(hand_scroll)
        self.ready_button = QPushButton("确认调度")
        self.ready_button.clicked.connect(self.ready)
        main.addWidget(self.ready_button, alignment=Qt.AlignRight)
        self.error_label = QLabel()
        self.error_label.setObjectName("battleError")
        self.error_label.setWordWrap(True)
        main.addWidget(self.error_label)
        self.result_banner = QLabel()
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setAlignment(Qt.AlignCenter)
        self.result_banner.hide()
        main.addWidget(self.result_banner)
        self.result_back = QPushButton("返回主菜单")
        self.result_back.clicked.connect(self.return_to_menu)
        self.result_back.hide()
        main.addWidget(self.result_back, alignment=Qt.AlignCenter)

    def _build_right_sidebar(self, parent_layout) -> None:
        self.right_sidebar = QWidget()
        self.right_sidebar.setFixedWidth(128)
        sidebar = QVBoxLayout(self.right_sidebar)
        self.enemy_hand_label = QLabel()
        self.enemy_hand_label.setObjectName("enemyHandBack")
        self.enemy_deck_label = QLabel()
        self.own_deck_label = QLabel()
        for label in (self.enemy_deck_label, self.own_deck_label):
            label.setObjectName("deckCount")
        for label in (self.enemy_hand_label, self.enemy_deck_label, self.own_deck_label):
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(104, 64)
        sidebar.addWidget(self.enemy_hand_label, 0, Qt.AlignHCenter)
        sidebar.addWidget(self.enemy_deck_label, 0, Qt.AlignHCenter)
        sidebar.addStretch(1)
        sidebar.addWidget(self.end_turn_button, 0, Qt.AlignHCenter)
        sidebar.addStretch(1)
        sidebar.addWidget(self.own_deck_label, 0, Qt.AlignHCenter)
        parent_layout.addWidget(self.right_sidebar)

    def _build_combat_zone(self, parent_layout) -> None:
        self.combat_zone = QFrame()
        self.combat_zone.setObjectName("combatZone")
        self.combat_zone.setFixedSize(320, 224)
        zone_layout = QVBoxLayout(self.combat_zone)
        zone_layout.setContentsMargins(20, 4, 20, 4)
        self._combat_cells = {}
        for position in ("top", "bottom"):
            cell_widget = QWidget()
            cell = QVBoxLayout(cell_widget)
            cell.setContentsMargins(0, 0, 0, 0)
            zone_layout.addWidget(cell_widget, 1)
            self._combat_cells[position] = cell
            if position == "top":
                self.combat_label = QLabel("战斗区\n空")
                self.combat_label.setAlignment(Qt.AlignCenter)
                self.combat_label.setStyleSheet("background: transparent;")
                zone_layout.addWidget(self.combat_label)
        parent_layout.addWidget(self.combat_zone, 0, Qt.AlignHCenter)

    def _build_perspective_row(self, parent_layout, position: str) -> None:
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addStretch(1)
        for index in range(4):
            cell_widget = QWidget()
            cell_widget.setFixedWidth(148)
            cell = QVBoxLayout(cell_widget)
            cell.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(cell_widget)
            if index == 1:
                row_layout.addSpacing(64)
            self._slot_cells[position].append(cell)
        row_layout.addStretch(1)
        setattr(self, f"{position}_row", row)
        parent_layout.addWidget(row)

    def _build_player_panel(self, pi: int) -> None:
        frame = QFrame()
        frame.setObjectName("playerPanel")
        frame.setMinimumWidth(190)
        frame.setMaximumWidth(240)
        column = QVBoxLayout(frame)
        column.setContentsMargins(4, 2, 4, 2)
        column.setSpacing(1)
        avatar = QLabel("头像")
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedHeight(16)
        column.addWidget(avatar)
        label = QLabel()
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 11px;")
        column.addWidget(label)
        fields = QLabel("幻境：无")
        fields.setWordWrap(True)
        fields.setStyleSheet("font-size: 11px;")
        column.addWidget(fields)
        detail = QPushButton("牌手详情")
        detail.setObjectName("battleSmall")
        detail.setFixedHeight(24)
        detail.clicked.connect(lambda _=False, side=pi: self.show_player_detail(side))
        column.addWidget(detail)
        frame.mouseReleaseEvent = lambda event, side=pi: self._player_click(event, side)
        self.player_frames[pi] = frame
        self.player_labels[pi] = label
        self.field_labels[pi] = fields

    def _build_shiki_slot(self, pi: int, index: int) -> None:
        slot = ShikiFrame(pi, index)
        slot.details_requested.connect(self._shiki_clicked)
        slot.assault_requested.connect(self.assault)
        slot.upgrade_requested.connect(self.upgrade)
        self.shiki_frames[(pi, index)] = slot

    def _sync_perspective(self) -> None:
        if self._perspective_viewer == self.viewer:
            return
        arc = (24, 0, 0, 24)
        for position, pi in (("top", 1 - self.viewer), ("bottom", self.viewer)):
            row = getattr(self, f"{position}_row")
            player_frame = self.player_frames[pi]
            if player_frame.parentWidget() is not None:
                player_frame.parentWidget().layout().removeWidget(player_frame)
            row.layout().insertWidget(0, player_frame)
            for index, cell in enumerate(self._slot_cells[position]):
                frame = self.shiki_frames[(pi, index)]
                if frame.parentWidget() is not None:
                    frame.parentWidget().layout().removeWidget(frame)
                cell.addWidget(frame)
                margin = arc[index]
                if position == "top":
                    cell.setContentsMargins(0, 0, 0, margin)
                else:
                    cell.setContentsMargins(0, margin, 0, 0)
        self._perspective_viewer = self.viewer

    def _sync_combat_slots(self) -> None:
        for position, pi in (("top", 1 - self.viewer), ("bottom", self.viewer)):
            player = self.game.state.players[pi]
            for index in range(4):
                frame = self.shiki_frames[(pi, index)]
                if player.combat_index == index:
                    cell = self._combat_cells[position]
                else:
                    cell = self._slot_cells[position][index]
                if frame.parentWidget() is not cell.parentWidget():
                    if frame.parentWidget() is not None:
                        frame.parentWidget().layout().removeWidget(frame)
                    cell.addWidget(frame)
        self.combat_label.setVisible(
            all(player.combat_index is None for player in self.game.state.players))

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.colors = colors
        self.setStyleSheet(f"""
            QLabel#viewTitle, QLabel#phaseLabel {{ color: {colors['gold']}; font-size: 24px; }}
            QFrame#playerPanel, QFrame#shikiSlot, QFrame#handCard {{
                background: {colors['panel']}; border: 2px solid {colors['line']};
                border-radius: 8px;
            }}
            QFrame#shikiSlot[targetable="true"], QFrame#playerPanel[targetable="true"] {{
                border: 4px solid {colors['gold2']}; background: {colors['panel2']};
            }}
            QLabel#shikiName, QLabel#handName {{ color: {colors['gold']}; font-weight: bold; }}
            QFrame#combatZone {{
                background: {colors['panel2']}; border: 2px solid {colors['line']};
                border-radius: 112px;
            }}
            QLabel#enemyHandBack, QLabel#deckCount {{
                background: {colors['panel']}; border: 2px solid {colors['line']};
                border-radius: 8px;
            }}
            QPushButton#endTurnButton {{
                background: {colors['panel2']}; border: 3px solid {colors['gold2']};
                border-radius: 52px; font-size: 18px;
            }}
            QLabel#targetHint {{ color: {colors['blue']}; }}
            QLabel#battleError {{ color: #c44; }}
            QLabel#resultBanner {{ color: {colors['gold']}; font-size: 34px; padding: 16px; }}
            QListWidget#battleLog {{ background: {colors['panel']}; color: {colors['text']}; }}
            QPushButton#battleSmall {{ padding: 4px; font-size: 12px; text-align: center; }}
        """)
        self._render_seats()

    def start_hotseat(self) -> bool:
        first = DeckSelectDialog(self.db, self.store_path, "玩家A", self)
        if first.exec() != QDialog.Accepted:
            return False
        second = DeckSelectDialog(self.db, self.store_path, "玩家B", self)
        if second.exec() != QDialog.Accepted:
            return False
        return self._start_entries(first.selected_entry(), second.selected_entry(), seed=42)

    def start_from_decks(self, first_index: int, second_index: int, **kwargs) -> bool:
        entries = [entry for entry in deckstore.load_decks(self.db, self.store_path)
                   if entry.get("standard")]
        return self._start_entries(entries[first_index], entries[second_index], **kwargs)

    def _start_entries(self, entry_a: dict, entry_b: dict, **kwargs) -> bool:
        ids_a, cards_a = deckstore.entry_deck(entry_a)
        ids_b, cards_b = deckstore.entry_deck(entry_b)
        self.start_game(("玩家A", ids_a, cards_a), ("玩家B", ids_b, cards_b), **kwargs)
        return True

    def start_game(self, p1: tuple, p2: tuple, seed: int = 42, **kwargs) -> None:
        self.timeline_timer.stop()
        self._close_handoff()
        self.close_log()
        self.game = new_game(self.db, p1, p2, seed=seed, **kwargs)
        self.viewer = self._current_viewer()
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self._timeline_seen = 0
        self.timeline_queue.clear()
        self.played_timeline.clear()
        self.log_list.clear()
        self.result_banner.hide()
        self.result_back.hide()
        self._choice_key = None
        self.stack.setCurrentWidget(self.battle_page)
        self.refresh()

    def _current_viewer(self) -> int:
        if self.game is None:
            return 0
        state = self.game.state
        if state.pending_choice is not None:
            return state.pending_choice["player"]
        if state.phase == "mulligan":
            return next((pi for pi, player in enumerate(state.players)
                         if not player.mulligan_done), state.active)
        return state.active

    def refresh(self) -> None:
        if self.game is None:
            return
        previous_viewer = self.viewer
        self.viewer = self._current_viewer()
        if previous_viewer != self.viewer and self.game.state.winner is None:
            self._begin_handoff()
        if self._handoff_pending:
            self._enqueue_timeline()
            return
        self._sync_perspective()
        if previous_viewer != self.viewer:
            self._render_log()
        self._render_state()
        self._enqueue_timeline()
        self._sync_pending_choice()

    def _clear_hand(self) -> None:
        while self.hand_layout.count():
            item = self.hand_layout.takeAt(0)
            if item.widget() is not None:
                widget = item.widget()
                widget.hide()
                widget.deleteLater()
        self.hand_frames = []
        self.hand_caption.clear()

    def _begin_handoff(self) -> None:
        self.timeline_timer.stop()
        self._handoff_pending = True
        self._clear_hand()
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        if self.choice_dialog is not None:
            self.choice_dialog.close()
            self.choice_dialog = None
        self._choice_key = None
        self.close_log()
        if self.handoff_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("交接设备")
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(f"请将设备交给 {self.game.state.players[self.viewer].name}"))
            buttons = QDialogButtonBox(QDialogButtonBox.Ok)
            polish_dialog_buttons(buttons)
            buttons.accepted.connect(self.confirm_handoff)
            dialog.rejected.connect(dialog.show)
            layout.addWidget(buttons, alignment=Qt.AlignRight)
            self.handoff_dialog = dialog
        self.handoff_dialog.show()
        self._update_input_widgets()

    def confirm_handoff(self) -> None:
        if not self._handoff_pending:
            return
        self._handoff_pending = False
        if self.handoff_dialog is not None:
            dialog = self.handoff_dialog
            dialog.hide()
            dialog.deleteLater()
            self.handoff_dialog = None
        self._sync_perspective()
        self._render_log()
        self._render_state()
        self._enqueue_timeline()
        self._sync_pending_choice()

    def _close_handoff(self) -> None:
        self._handoff_pending = False
        if self.handoff_dialog is not None:
            dialog = self.handoff_dialog
            dialog.hide()
            dialog.deleteLater()
            self.handoff_dialog = None

    def _render_state(self) -> None:
        if self._handoff_pending:
            return
        game = self.game
        state = game.state
        phase_names = {"mulligan": "调度阶段", "upgrade": "升级阶段", "battle": "对战阶段"}
        self.phase_label.setText(f"{phase_names.get(state.phase, state.phase)}　回合 {state.turn}")
        for pi, player in enumerate(state.players):
            boosts = player.assault_boosts
            power = sum(item.get("power", 0) for item in boosts)
            shield = sum(item.get("shield", 0) for item in boosts)
            self.player_labels[pi].setText(
                f"{player.name}{'（当前）' if pi == self.viewer else ''}\n"
                f"生命 {player.health}/{player.max_health}　护甲/破甲 {player.shield}\n"
                f"鬼火 {player.orb}　出击 {player.assaults_left}　鼓舞 +{power}/+{shield}\n"
                f"手牌 {len(player.hand)}　牌库 {len(player.deck)}　墓地 {len(player.graveyard)}")
            field_text = " → ".join(
                f"{self.db.cards[field.card_id].name}(耐久{field.intensity})"
                for field in player.fields)
            self.field_labels[pi].setText(f"幻境：{field_text or '无'}")
            self.player_frames[pi].setProperty("targetable", Ref(player=pi) in self.legal_targets)
            self._polish(self.player_frames[pi])
            for index, shiki in enumerate(player.shikigami):
                frame = self.shiki_frames[(pi, index)]
                definition = self.db.shikigami[shiki.id]
                awaken = "觉醒·" if shiki.awakened is not None else ""
                frame.name_label.setText(f"{awaken}{definition.name}　Lv.{shiki.level}")
                frame.stats_label.setText(f"力量 {shiki.eff_power}　生命 {shiki.health}/{shiki.max_health}")
                statuses = [f"护甲/破甲 {shiki.shield}"]
                if shiki.countdown is not None:
                    statuses.append(f"倒计时 {shiki.countdown}")
                frame.status_label.setText("　".join(statuses))
                own_turn = pi == state.active
                frame.assault_button.setVisible(own_turn and state.phase == "battle")
                frame.upgrade_button.setVisible(own_turn and state.phase == "upgrade")
                frame.assault_button.setEnabled(self._inputs_open())
                frame.upgrade_button.setEnabled(
                    self._inputs_open() and index in game.legal_upgrade_indices(pi))
                frame.setProperty("targetable", frame.ref in self.legal_targets)
                self._polish(frame)
                if self.colors and index < len(self.colors["seat"]):
                    frame.setStyleSheet(
                        f"QFrame#shikiSlot {{ border-color: {self.colors['seat'][index]}; }}")
        self._sync_combat_slots()
        enemy = state.players[1 - self.viewer]
        own = state.players[self.viewer]
        self.enemy_hand_label.setText(f"敌方手牌\n{len(enemy.hand)} 张")
        self.enemy_deck_label.setText(f"敌方牌库\n{len(enemy.deck)} 张")
        self.own_deck_label.setText(f"己方牌库\n{len(own.deck)} 张")
        self._render_hand()
        inputs = self._inputs_open()
        self.end_turn_button.setEnabled(inputs and state.phase == "battle")
        self.ready_button.setVisible(state.phase == "mulligan")
        self.ready_button.setEnabled(inputs and state.phase == "mulligan")
        targeting = self.pending_command is not None
        self.cancel_target_button.setVisible(targeting)
        self.default_target_button.setVisible(targeting and self.pending_command.get("op") == "assault")
        self.target_label.setText("请选择高亮目标" if targeting else "")
        if state.winner is not None and not self.timeline_queue:
            self._show_result()

    def hand_info(self) -> dict[int, dict]:
        return cli.hand_cards_info(self.game, self.viewer)

    def _render_hand(self) -> None:
        self._clear_hand()
        player = self.game.state.players[self.viewer]
        mulligan = self.game.state.phase == "mulligan"
        cards = list(player.hand) if mulligan else cli.hand_sorted(self.game, player)
        info = {} if self.game.state.pending_choice else self.hand_info()
        self.hand_caption.setText(f"{player.name} 的手牌（{len(cards)} 张）")
        for card in cards:
            definition = self.db.cards[card.id]
            frame = HandCardFrame(card, self.db)
            detail = info.get(card.uid, {})
            frame.name_label.setText(definition.name)
            usage = detail.get("usage", [])
            legal = any(option["ok"] for option in usage)
            badges = list(detail.get("keywords", []))
            if detail.get("enhance"):
                badges.append(f"增强 {detail['enhance']}")
            if detail.get("quest"):
                badges.append(detail["quest"])
            if usage and not legal:
                badges.append("不可用")
            frame.info_label.setText(
                f"费用 {detail.get('cost', definition.cost)}　等级 {definition.level}\n"
                f"{detail.get('stats', '')}\n{' / '.join(badges)}")
            frame.play_button.setVisible(not mulligan)
            frame.play_button.setEnabled(self._inputs_open() and legal
                                         and self.game.state.phase == "battle")
            frame.mulligan_button.setVisible(mulligan)
            frame.mulligan_button.setEnabled(self._inputs_open())
            frame.play_requested.connect(self.play_card)
            frame.detail_requested.connect(self.show_card_detail)
            frame.mulligan_requested.connect(self.mulligan)
            self.hand_layout.addWidget(frame)
            self.hand_frames.append(frame)
        self.hand_layout.addStretch(1)

    def _render_seats(self) -> None:
        if self.game is None:
            return
        for (pi, index), frame in self.shiki_frames.items():
            if self.colors and index < len(self.colors["seat"]):
                frame.setStyleSheet(
                    f"QFrame#shikiSlot {{ border-color: {self.colors['seat'][index]}; }}")

    @staticmethod
    def _polish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _inputs_open(self) -> bool:
        return (self.game is not None and not self._handoff_pending
                and not self.timeline_queue and self.game.state.winner is None
                and self.game.state.pending_choice is None
                and self.pending_command is None)

    def apply_command(self, command: dict) -> bool:
        if self.game is None or self._handoff_pending or self.timeline_queue:
            return False
        try:
            self.game.apply(command)
        except IllegalAction as error:
            self.error_label.setText(f"无效操作：{error}")
            self._render_state()
            return False
        self.error_label.clear()
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self.refresh()
        return True

    def mulligan(self, uid: int) -> bool:
        return self.apply_command({"op": "mulligan", "player": self.viewer, "uid": uid})

    def ready(self) -> bool:
        return self.apply_command({"op": "ready", "player": self.viewer})

    def upgrade(self, index: int) -> bool:
        return self.apply_command({"op": "upgrade", "index": index})

    def end_turn(self) -> bool:
        return self.apply_command({"op": "end_turn"})

    def assault(self, index: int) -> bool:
        if not self._inputs_open() or self.game.state.phase != "battle":
            return False
        command = {"op": "assault", "index": index}
        shiki = self.game.current.shikigami[index]
        keywords = shiki.keywords + shiki.one_shot_keywords + shiki.perm_keywords
        if "hunt" in keywords:
            legal = targets.pool_refs(self.game, "enemy_shikigami",
                                      self.game.state.active, targeted=True)
            if legal:
                self.pending_command = command
                self.target_specs = []
                self.legal_targets = legal
                self.target_label.setText("追猎：选择敌方目标，或使用默认战斗区")
                self._render_state()
                return True
        return self.apply_command(command)

    def play_card(self, uid: int, usage_id=...) -> bool:
        if not self._inputs_open() or self.game.state.phase != "battle":
            return False
        card = next((card for card in self.game.current.hand if card.uid == uid), None)
        if card is None:
            return False
        options = self.game.usage_options(self.game.state.active, card)
        if usage_id is ...:
            if len(options) == 1:
                usage_id = options[0]["id"]
            else:
                dialog = UsageDialog(options, self)
                if dialog.exec() != QDialog.Accepted:
                    return False
                usage_id = dialog.selected_id
        option = next((item for item in options if item["id"] == usage_id), None)
        if option is None or not option["ok"]:
            self.error_label.setText("该使用方式当前不可用")
            return False
        command = {"op": "play_card", "uid": uid}
        definition = self.db.cards[card.id]
        effective = definition
        if isinstance(usage_id, str) and usage_id.startswith("choice:"):
            choice = int(usage_id.split(":", 1)[1])
            command["choice"] = choice
            effective = self.db.cards[definition.options[choice]]
        elif usage_id is not None:
            command["play_method"] = usage_id
        specs = []
        if effective.target.kind == "choose":
            specs.append(("target", effective.target))
        if definition.target2 is not None and definition.target2.kind == "choose":
            specs.append(("target2", definition.target2))
        if specs:
            self.pending_command = command
            self.target_specs = specs
            self._update_legal_targets()
            self._render_state()
            return True
        return self.apply_command(command)

    def _update_legal_targets(self) -> None:
        if not self.target_specs:
            self.legal_targets = []
            return
        _key, spec = self.target_specs[0]
        self.legal_targets = targets.spec_pool_refs(
            self.game, spec, self.game.state.active, targeted=True)

    def choose_target(self, ref: Ref) -> bool:
        if self.pending_command is None or ref not in self.legal_targets:
            return False
        command = dict(self.pending_command)
        command[self.target_specs[0][0]] = ref
        self.target_specs.pop(0)
        if self.target_specs:
            self.pending_command = command
            self._update_legal_targets()
            self._render_state()
            return True
        return self.apply_command(command)

    def cancel_targeting(self) -> None:
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self._render_state()

    def confirm_default_target(self) -> None:
        if self.pending_command is not None and self.pending_command.get("op") == "assault":
            command = self.pending_command
            self.apply_command(command)

    def _shiki_clicked(self, ref: Ref) -> None:
        if ref in self.legal_targets:
            self.choose_target(ref)
        else:
            self.show_shiki_detail(ref)

    def _player_click(self, event, pi: int) -> None:
        if event.button() != Qt.LeftButton:
            return
        ref = Ref(player=pi)
        if ref in self.legal_targets:
            self.choose_target(ref)
        else:
            self.show_player_detail(pi)

    def show_shiki_detail(self, ref: Ref) -> None:
        shiki = self.game.state.players[ref.player].shikigami[ref.shikigami]
        definition = self.db.shikigami[shiki.id]

        def ref_label(value) -> str | None:
            if value is None:
                return None
            pi = value.get("player") if isinstance(value, dict) else value.player
            si = value.get("shikigami") if isinstance(value, dict) else value.shikigami
            if pi is None or not 0 <= pi < len(self.game.state.players):
                return None
            player = self.game.state.players[pi]
            if si is None:
                return player.name
            if not 0 <= si < len(player.shikigami):
                return None
            source = player.shikigami[si]
            return f"{player.name}·{self.db.shikigami[source.id].name}"

        def mods(label, power, health=None) -> str:
            parts = [f"力量 {power:+d}"]
            if health is not None:
                parts.append(f"生命 {health:+d}")
            return f"{label} {'　'.join(parts)}"

        dialog = QDialog(self)
        dialog.setWindowTitle(definition.name)
        dialog.setMinimumSize(520, 600)
        layout = QVBoxLayout(dialog)
        text = [
            f"等级 {shiki.level}　力量 {shiki.eff_power}　生命 {shiki.health}/{shiki.max_health}",
            f"护甲/破甲 {shiki.shield}　能量 {shiki.energy}　派系 {shiki.faction}",
            mods("永久修正", shiki.perm_power, shiki.perm_health),
            mods("临时修正", shiki.temp_power, shiki.temp_health),
            mods("战斗修正", shiki.combat_power),
        ]
        dyn_power = int(shiki.ext.get("dyn_power", 0))
        dyn_health = int(shiki.ext.get("dyn_health", 0))
        if dyn_power or dyn_health:
            text.append(mods("动态光环合计", dyn_power, dyn_health))
        if shiki.ext.get("power_zero"):
            text.append("力量覆写：0（动态光环与灵咒仍合计）")
        keywords = cli._kw_labels(
            shiki.keywords + shiki.one_shot_keywords + shiki.perm_keywords)
        if keywords:
            text.append(f"关键字：{'、'.join(keywords)}")
        for index, buff in enumerate(shiki.attack_buffs, 1):
            parts = [f"攻击后到期强化 {index}：力量 {buff.get('power', 0):+d}"]
            labels = cli._kw_labels(kw for kw, _cls in buff.get("keywords", []))
            if labels:
                parts.append(f"关键字 {'、'.join(labels)}")
            text.append("　".join(parts))
        if shiki.keep_shield:
            text.append("保留护甲")
        if shiki.keep_fragile:
            text.append("保留破甲")
        for index, immunity in enumerate(shiki.immunities, 1):
            text.append(f"免疫 {index}：{immunity.get('kind', '未标明类型')}")
        if shiki.stuns:
            kinds = "、".join(str(entry.get("kind", "未标明类型")) for entry in shiki.stuns)
            text.append(f"眩晕：{kinds}")
        if shiki.dying:
            text.append("濒死")
        if shiki.despawned:
            text.append("已离场")
        if shiki.defeated:
            text.append(f"气绝：复活倒计时 {shiki.revive_countdown}")
        if shiki.countdown is not None:
            countdown = [f"倒计时 {shiki.countdown}"]
            if shiki.countdown_initial is not None:
                countdown.append(f"初始 {shiki.countdown_initial}")
            countdown.append("一次型" if shiki.countdown_once else "循环型")
            source = shiki.countdown_source
            if source in self.db.cards:
                countdown.append(f"来源 {self.db.cards[source].name}")
            elif source in self.db.shikigami:
                countdown.append(f"来源 {self.db.shikigami[source].name}")
            text.append("　".join(countdown))
        text.append(definition.text or "（无基础能力文本）")
        if shiki.awakened is not None:
            awaken = self.db.cards[shiki.awakened]
            text.extend([f"觉醒：{awaken.name}", awaken.text or ""])
        if shiki.form is not None:
            form = self.db.cards[shiki.form.id]
            text.extend([f"形态：{form.name}", form.text or ""])
        for index, delayed in enumerate(shiki.delayed, 1):
            block = delayed.get("block") or {}
            when = block.get("when") if isinstance(block, dict) else block.when
            parts = [f"延迟能力 {index}：类型 {when}", f"次数 {delayed.get('uses', 1)}"]
            origin = delayed.get("origin")
            if origin in self.db.cards:
                parts.append(f"来源 {self.db.cards[origin].name}")
            chosen = None
            if not delayed.get("secret") or ref.player == self.viewer:
                chosen = ref_label(delayed.get("chosen"))
            if chosen:
                parts.append(f"目标 {chosen}")
            text.append("　".join(parts))
        for index, invocation in enumerate(shiki.invocations, 1):
            name = invocation.get("name", "")
            parts = [f"灵咒 {index}：{name}"]
            source = ref_label(invocation.get("source"))
            if source:
                parts.append(f"来源 {source}")
            elif invocation.get("player") is not None:
                pi = invocation["player"]
                if 0 <= pi < len(self.game.state.players):
                    parts.append(f"来源 {self.game.state.players[pi].name}")
            text.append("　".join(parts))
            if invocation.get("power") or invocation.get("health"):
                text.append(mods("基础", invocation.get("power", 0),
                                 invocation.get("health", 0)))
            if invocation.get("bonus"):
                text.append(f"增强 {invocation['bonus']:+d}")
            if invocation.get("mod_power") or invocation.get("mod_health"):
                text.append(mods("修饰", invocation.get("mod_power", 0),
                                 invocation.get("mod_health", 0)))
            idef = self.db.invocations.get(name)
            if idef is not None and idef.text:
                text.append(idef.text)
        label = QLabel("\n\n".join(text))
        label.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        dialog.exec()

    def show_player_detail(self, pi: int) -> None:
        player = self.game.state.players[pi]
        fields = "\n".join(
            f"{index + 1}. {self.db.cards[field.card_id].name}　耐久 {field.intensity}"
            for index, field in enumerate(player.fields)) or "无幻境"
        dialog = QDialog(self)
        dialog.setWindowTitle(player.name)
        layout = QVBoxLayout(dialog)
        label = QLabel(
            f"生命 {player.health}/{player.max_health}　护甲 {player.shield}\n"
            f"鬼火 {player.orb}　出击次数 {player.assaults_left}\n{fields}")
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        dialog.exec()

    def show_card_detail(self, card) -> None:
        info = self.hand_info()
        runtime = info[card.uid] if card.uid in info else None
        CardDetailDialog(self.db.cards[card.id], self.db, self, runtime=runtime).exec()

    def choice_option_label(self, pending: dict, option) -> str:
        kind = pending.get("kind")
        player = self.game.state.players[pending["player"]]
        if kind in ("deck_top_pick", "mulligan_pick", "discard_pick", "quest_complete_pick"):
            zones = [player.deck] if kind == "deck_top_pick" else [player.hand]
            card = next((card for zone in zones for card in zone if card.uid == option), None)
            if card is not None:
                definition = self.db.cards[card.id]
                return f"{definition.name}\n{definition.text or ''}"
        if kind == "card_name" and pending.get("stage") == "shikigami":
            return self.db.shikigami[option].name
        if kind in ("card_name", "field_summon_pick", "pick_generate"):
            definition = self.db.cards[option]
            return f"{definition.name}\n{definition.text or ''}"
        if kind == "invocation_pick":
            definition = self.db.invocations.get(option)
            return f"{option}\n{definition.text if definition is not None else ''}"
        return str(option)

    def _sync_pending_choice(self) -> None:
        if self._handoff_pending:
            return
        pending = self.game.state.pending_choice
        if pending is None:
            if self.choice_dialog is not None:
                self.choice_dialog.close()
                self.choice_dialog = None
            self._choice_key = None
            return
        key = (pending.get("kind"), pending.get("stage"), tuple(pending.get("options", [])))
        if key == self._choice_key and self.choice_dialog is not None:
            return
        if self.choice_dialog is not None:
            self.choice_dialog.close()
        self.choice_dialog = ChoiceDialog(self, pending)
        self._choice_key = key
        self.choice_dialog.show()

    def answer_pending(self, value) -> bool:
        pending = self.game.state.pending_choice
        if pending is None:
            return False
        command = {"op": "choose", "player": pending["player"]}
        if pending.get("kind") in ("deck_top_pick", "mulligan_pick", "discard_pick",
                                   "quest_complete_pick"):
            if value is not None:
                command["uid"] = value
        else:
            command["choice"] = value
        return self.apply_command(command)

    def _enqueue_timeline(self) -> None:
        entries = self.game.state.timeline[self._timeline_seen:]
        self._timeline_seen = len(self.game.state.timeline)
        for entry in entries:
            self.timeline_queue.append((entry.get("o"), entry.get("m", "")))
        if (self.timeline_queue and not self._handoff_pending
                and not self.timeline_timer.isActive()):
            self.timeline_timer.start()
        self._update_input_widgets()

    def _render_log(self) -> None:
        self.log_list.clear()
        mulligan_phase = False
        opponent_prefix = f"{self.game.state.players[1 - self.viewer].name} "
        for owner, message in self.played_timeline:
            if message.startswith("对局开始：调度阶段"):
                mulligan_phase = True
            elif message == "对局开始":
                mulligan_phase = False
            hidden_mulligan = (mulligan_phase and message.startswith(opponent_prefix)
                               and "调度了一张手牌" in message)
            if (owner is None or owner == self.viewer) and not hidden_mulligan:
                self.log_list.addItem(message)
        self.log_list.scrollToBottom()

    def show_log(self) -> None:
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()
        self.log_list.scrollToBottom()

    def close_log(self) -> None:
        self.log_dialog.hide()

    def play_next_timeline(self) -> None:
        if self._handoff_pending:
            self.timeline_timer.stop()
            return
        if not self.timeline_queue:
            self.timeline_timer.stop()
            self._update_input_widgets()
            return
        entry = self.timeline_queue.pop(0)
        self.played_timeline.append(entry)
        self._render_log()
        if not self.timeline_queue:
            self.timeline_timer.stop()
        self._update_input_widgets()
        if not self.timeline_queue:
            self._render_state()

    def _update_input_widgets(self) -> None:
        if self.game is None:
            return
        enabled = self._inputs_open()
        state = self.game.state
        self.end_turn_button.setEnabled(enabled and state.phase == "battle")
        self.ready_button.setEnabled(enabled and state.phase == "mulligan")
        for (pi, index), frame in self.shiki_frames.items():
            frame.assault_button.setEnabled(enabled and pi == state.active)
            frame.upgrade_button.setEnabled(enabled and pi == state.active
                                            and index in self.game.legal_upgrade_indices(pi))
        for frame in self.hand_frames:
            frame.play_button.setEnabled(enabled)
            frame.mulligan_button.setEnabled(enabled)

    def _show_result(self) -> None:
        self.result_banner.setText(cli.result_text(
            self.game.state.winner, [player.name for player in self.game.state.players]))
        self.result_banner.show()
        self.result_back.show()

    def return_to_menu(self) -> None:
        self.timeline_timer.stop()
        self._close_handoff()
        self.close_log()
        if self.choice_dialog is not None:
            self.choice_dialog.close()
            self.choice_dialog = None
        if self.on_back is not None:
            self.on_back()
