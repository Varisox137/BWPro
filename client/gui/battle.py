"""桌面 GUI 本地热坐对战：标准卡组开局、场况、操作与结算播放。"""
from __future__ import annotations

import html
import secrets
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from client import cli
from client.gui.battle_scene import DRAG_Z, BattleScene, BattleView, card_owner_seat, usage_target
from client.gui.cardart import seat_level_color
from client.gui.details import ShikigamiDetailDialog
from client.gui.widgets import CardChoiceView, CardDetailDialog, ask_confirmation, polish_dialog_buttons
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


class ChoiceDialog(QDialog):
    """结算中选择：卡牌 uid、卡牌/式神数据 id 与灵咒名统一作答。"""

    def __init__(self, view: "HotseatView", pending: dict):
        super().__init__(view)
        self.setWindowTitle("结算选择")
        self.setModal(False)
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
        options = [(option, view.choice_option_def(pending, option),
                    view.choice_option_label(pending, option))
                   for option in pending.get("options", [])]
        self.option_view = CardChoiceView(options, db=view.db)
        self.option_view.chosen.connect(self._answer)
        layout.addWidget(self.option_view, 1)
        if kind == "mulligan_pick":
            done = QPushButton("结束调度")
            done.clicked.connect(lambda: self._answer(None))
            layout.addWidget(done)
        self.resize(720, 500)

    def _answer(self, value) -> None:
        if not self.isEnabled():
            return
        self.setEnabled(False)
        view = self.parent()
        if view.answer_pending(value):
            view._close_choice_dialog(self)
        else:
            self.setEnabled(True)

    def reject(self) -> None:
        pass


class BattleErrorLabel(QLabel):
    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.setText("")


class HotseatView(QWidget):
    """热坐单屏视图；手牌与非公开结算仅显示当前行动/作答方。"""

    exit_confirmation = True

    def __init__(self, db, store_path: Path = deckstore.PATH, on_back=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.store_path = Path(store_path)
        self.on_back = on_back
        self.theme = "light"
        self.game = None
        self.viewer = 0
        self._review_mulligan = False
        self._last_turn_key = None
        self._opening_banner_pending = True
        self.pending_command: dict | None = None
        self._usage_pending: tuple[int, Ref | None] | None = None
        self.target_specs: list[tuple[str, object]] = []
        self.legal_targets: list[Ref] = []
        self.choice_dialog: ChoiceDialog | None = None
        self._choice_key = None
        self._handoff_pending = False
        self._handoff_stage = None
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
        outer.setContentsMargins(0, 0, 0, 0)
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
        layout = QVBoxLayout(self.battle_page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.battle_scene = BattleScene(self.db)
        self.battle_view = BattleView(self.battle_scene)
        layout.addWidget(self.battle_view)

        self.menu_button = QPushButton("退出对局")
        self.menu_button.setObjectName("battleSmall")
        self.menu_button.clicked.connect(self.return_to_menu)
        self.battle_scene.menu_item = self.battle_scene.add_control(
            self.menu_button, ("menu",), (120, 34))
        self.battle_scene.menu_item.hide()
        self.phase_label = QLabel()
        self.phase_label.setObjectName("phaseLabel")
        self.phase_label.setAlignment(Qt.AlignCenter)
        self.phase_label.setTextFormat(Qt.RichText)
        self.upgrade_label = self.phase_label
        self.battle_scene.phase_item = self.battle_scene.add_control(
            self.phase_label, ("phase",), (340, 56))
        self.log_button = QPushButton("对局\n记录")
        self.log_button.setObjectName("battleRound")
        self.log_button.clicked.connect(self.show_log)
        self.battle_scene.log_item = self.battle_scene.add_control(
            self.log_button, ("log",), (40, 40))
        self.end_turn_button = QPushButton("结束\n回合")
        self.end_turn_button.setObjectName("endTurnButton")
        self.end_turn_button.clicked.connect(self.end_turn)
        self.battle_scene.end_turn_item = self.battle_scene.add_control(
            self.end_turn_button, ("end_turn",), (104, 104))

        self.enemy_hand_label = QLabel()
        self.enemy_hand_label.setObjectName("enemyHandBack")
        self.enemy_deck_label = QLabel()
        self.own_deck_label = QLabel()
        for key, label in (("enemy_hand_label", self.enemy_hand_label),
                           ("enemy_deck", self.enemy_deck_label),
                           ("own_deck", self.own_deck_label)):
            label.setAlignment(Qt.AlignCenter)
            size = (130, 64) if key == "enemy_hand_label" else (68, 64)
            self.battle_scene.add_control(label, (key,), size)
        for label in (self.enemy_deck_label, self.own_deck_label):
            label.setObjectName("deckCount")

        self.target_label = QLabel()
        self.target_label.setObjectName("targetHint")
        self.battle_scene.add_control(self.target_label, ("target_label",), (300, 30))
        self.cancel_target_button = QPushButton("取消目标")
        self.default_target_button = QPushButton("默认战斗区")
        for key, button in (("cancel_target", self.cancel_target_button),
                            ("default_target", self.default_target_button)):
            button.setObjectName("battleSmall")
            self.battle_scene.add_control(button, (key,), (120, 32))
        self.cancel_target_button.clicked.connect(self.cancel_targeting)
        self.default_target_button.clicked.connect(self.confirm_default_target)
        self.hand_caption = QLabel()
        self.hand_caption.setAlignment(Qt.AlignCenter)
        self.battle_scene.add_control(self.hand_caption, ("hand_caption",), (130, 64))
        self.ready_button = QPushButton("确认调度")
        self.ready_button.setObjectName("battleSmall")
        self.ready_button.clicked.connect(self.ready)
        self.battle_scene.ready_item = self.battle_scene.add_control(
            self.ready_button, ("ready",), (140, 34))
        self.mulligan_button = QPushButton("替换")
        self.mulligan_button.setObjectName("battleSmall")
        self.mulligan_button.clicked.connect(self.replace_mulligan)
        self.battle_scene.mulligan_item = self.battle_scene.add_control(
            self.mulligan_button, ("mulligan",), (140, 44))
        self.order_label = QLabel()
        self.order_label.setObjectName("turnOrderLabel")
        self.order_label.setAlignment(Qt.AlignCenter)
        self.battle_scene.add_control(self.order_label, ("turn_order",), (300, 90))
        self.battle_scene.mulligan_selected.connect(self._sync_mulligan_button)
        self.error_label = BattleErrorLabel()
        self.error_label.setObjectName("battleError")
        self.error_label.setWordWrap(True)
        self.battle_scene.add_control(self.error_label, ("error",), (400, 64))
        self.result_banner = QLabel()
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setAlignment(Qt.AlignCenter)
        self.battle_scene.result_item = self.battle_scene.add_control(
            self.result_banner, ("result_banner",), (600, 90))
        self.battle_scene.result_item.setZValue(DRAG_Z + 20)
        self.result_banner.hide()
        self.result_back = QPushButton("返回主菜单")
        self.result_back.setObjectName("battleSmall")
        self.result_back.clicked.connect(self.return_to_menu)
        self.battle_scene.result_back_item = self.battle_scene.add_control(
            self.result_back, ("result_back",), (140, 38))
        self.battle_scene.result_back_item.setZValue(DRAG_Z + 20)
        self.result_back.hide()

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
        self.battle_scene.action_requested.connect(self._scene_action)
        self.battle_scene.detail_requested.connect(self._scene_detail)
        self.battle_scene.usage_selected.connect(self._select_usage)

    def _scene_action(self, command: dict) -> bool:
        op = command.get("op")
        if op == "mulligan":
            return self.mulligan(command["uid"])
        if op == "upgrade":
            return self.upgrade(command["index"])
        if op == "assault":
            return self.assault(command["index"], target=command.get("target"))
        if op == "play_card":
            return self.play_card(command["uid"], target=command.get("target"),
                                  from_drag=True)
        return False

    def _scene_detail(self, kind: str, payload) -> None:
        if kind == "shiki":
            self._shiki_clicked(payload)
        elif kind == "player":
            if payload in self.legal_targets:
                self.choose_target(payload)
            else:
                self.show_player_detail(payload.player)
        elif kind == "hand":
            self.show_card_detail(payload)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.battle_scene.set_text_color(colors["text"])
        self.battle_scene.loading_background.setBrush(QColor(colors["bg"]))
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 24px; }}
            QLabel#phaseLabel {{
                color: {colors['text']}; font-size: 24px; font-weight: 600;
                background: transparent;
            }}
            QLabel#turnOrderLabel {{
                color: {colors['text']}; font-size: 34px; font-weight: 600;
                background: transparent;
            }}
            QLabel#enemyHandBack, QLabel#deckCount {{
                background: transparent; border: none;
            }}
            QPushButton#endTurnButton {{
                background: {colors['panel2']}; border: 3px solid {colors['gold2']};
                border-radius: 52px; font-size: 18px; text-align: center; padding: 0;
            }}
            QPushButton#endTurnButton:disabled {{
                background: {colors['bg']}; border-color: {colors['line']};
                color: {colors['dim']};
            }}
            QLabel#targetHint, QLabel#battleError, QLabel#resultBanner {{
                color: {colors['text']}; background: transparent; font-weight: 600;
            }}
            QLabel#resultBanner {{ font-size: 34px; padding: 16px; }}
            QListWidget#battleLog {{ background: {colors['panel']}; color: {colors['text']}; }}
            QPushButton#battleSmall {{ padding: 4px; font-size: 12px; text-align: center; }}
        """)
        for label in (self.enemy_hand_label, self.enemy_deck_label,
                      self.own_deck_label, self.hand_caption,
                      self.target_label, self.error_label):
            label.setStyleSheet(
                f"background: transparent; color: {colors['text']}; font-weight: 600;")
        self.phase_label.setStyleSheet(
            f"background: transparent; color: {colors['text']}; "
            "font-size: 24px; font-weight: 600;")
        self.order_label.setStyleSheet(
            f"background: transparent; color: {colors['text']}; "
            "font-size: 34px; font-weight: 600;")
        self.result_banner.setStyleSheet(
            f"background: transparent; color: {colors['text']}; "
            "font-size: 34px; font-weight: 600; padding: 16px;")
        for item in self.battle_scene.items():
            button = item.widget() if hasattr(item, "widget") else None
            if isinstance(button, QPushButton) and button.objectName() == "battleSmall":
                button.setStyleSheet(f"""
                    QPushButton {{ background: {colors['panel']}; color: {colors['text']};
                        border: 1px solid {colors['gold']}; border-radius: 6px;
                        padding: 4px; font-size: 12px; text-align: center; }}
                    QPushButton:hover {{ background: {colors['panel2']}; }}
                """)
        self.log_button.setStyleSheet(f"""
            QPushButton {{ background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['gold']}; border-radius: 20px;
                padding: 0; font-size: 12px; text-align: center; }}
            QPushButton:hover {{ background: {colors['panel2']}; }}
        """)
        self.end_turn_button.setStyleSheet(f"""
            QPushButton {{ background: {colors['panel2']}; color: {colors['text']};
                border: 3px solid {colors['gold2']}; border-radius: 52px;
                font-size: 18px; text-align: center; padding: 0; }}
            QPushButton:disabled {{ background: {colors['bg']}; color: {colors['dim']};
                border-color: {colors['line']}; }}
        """)

    def start_hotseat(self) -> bool:
        first = DeckSelectDialog(self.db, self.store_path, "玩家A", self)
        if first.exec() != QDialog.Accepted:
            return False
        second = DeckSelectDialog(self.db, self.store_path, "玩家B", self)
        if second.exec() != QDialog.Accepted:
            return False
        return self._start_entries(first.selected_entry(), second.selected_entry())

    def start_from_decks(self, first_index: int, second_index: int, **kwargs) -> bool:
        entries = [entry for entry in deckstore.load_decks(self.db, self.store_path)
                   if entry.get("standard")]
        return self._start_entries(entries[first_index], entries[second_index], **kwargs)

    def _start_entries(self, entry_a: dict, entry_b: dict, **kwargs) -> bool:
        ids_a, cards_a = deckstore.entry_deck(entry_a)
        ids_b, cards_b = deckstore.entry_deck(entry_b)
        self.start_game(("玩家A", ids_a, cards_a), ("玩家B", ids_b, cards_b), **kwargs)
        return True

    def start_game(self, p1: tuple, p2: tuple, seed: int | None = None, **kwargs) -> None:
        if seed is None:
            seed = secrets.randbits(32)
        self._clear_usage()
        self.battle_scene.reset_animations()
        self.battle_scene.show_loading("正在准备对局")
        try:
            self.timeline_timer.stop()
            self._close_handoff()
            self.close_log()
            self.game = new_game(self.db, p1, p2, seed=seed, **kwargs)
            self.viewer = self._current_viewer()
            self._review_mulligan = False
            self._last_turn_key = None
            self._opening_banner_pending = True
            self.battle_scene.hide_banner()
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
        finally:
            self.battle_scene.hide_loading()

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
        next_viewer = self._current_viewer()
        if previous_viewer != next_viewer and self.game.state.winner is None:
            if self._review_mulligan:
                self.viewer = previous_viewer
                self._render_state()  # 先展示第三次换牌后的结果，再遮挡操作并交接
            self.viewer = next_viewer
            self._begin_handoff(preserve_hand=self._review_mulligan)
        else:
            self.viewer = next_viewer
        if self._handoff_pending:
            self._enqueue_timeline()
            return
        if previous_viewer != self.viewer:
            self._render_log()
        self._render_state()
        self._enqueue_timeline()
        self._sync_pending_choice()

    def _clear_hand(self) -> None:
        self.battle_scene.clear_hands()
        self.hand_caption.clear()

    def _begin_handoff(self, preserve_hand: bool = False) -> None:
        self.timeline_timer.stop()
        self._clear_usage()
        self.battle_scene.reset_animations()
        self._handoff_pending = True
        self._handoff_stage = "review" if preserve_hand else "transfer"
        if not preserve_hand:
            self._clear_hand()
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        if self.choice_dialog is not None:
            self.choice_dialog.close()
            self.choice_dialog = None
        self._choice_key = None
        self.close_log()
        message = (f"调度次数已用完\n请确认本次调度结果，然后交给 "
                   f"{self.game.state.players[self.viewer].name}" if preserve_hand else
                   f"请将设备交给 {self.game.state.players[self.viewer].name}")
        title = "调度完毕请确认" if preserve_hand else "准备移交"
        if self.handoff_dialog is None:
            dialog = QDialog(self)
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(message))
            buttons = QDialogButtonBox(QDialogButtonBox.Ok)
            polish_dialog_buttons(buttons)
            buttons.accepted.connect(self.confirm_handoff)
            dialog.rejected.connect(dialog.show)
            layout.addWidget(buttons, alignment=Qt.AlignRight)
            self.handoff_dialog = dialog
        else:
            self.handoff_dialog.findChild(QLabel).setText(message)
        self.handoff_dialog.setWindowTitle(title)
        self.handoff_dialog.show()
        self._update_input_widgets()

    def confirm_handoff(self) -> None:
        if not self._handoff_pending:
            return
        if self._handoff_stage == "review":
            self._clear_hand()
            self._handoff_stage = "transfer"
            self.handoff_dialog.setWindowTitle("准备移交")
            self.handoff_dialog.findChild(QLabel).setText(
                f"请将设备交给 {self.game.state.players[self.viewer].name}")
            return
        self._handoff_pending = False
        self._handoff_stage = None
        if self.handoff_dialog is not None:
            dialog = self.handoff_dialog
            dialog.hide()
            dialog.deleteLater()
            self.handoff_dialog = None
        self._clear_hand()
        self._render_log()
        self._render_state()
        self._enqueue_timeline()
        self._sync_pending_choice()

    def _close_handoff(self) -> None:
        self._handoff_pending = False
        self._handoff_stage = None
        if self.handoff_dialog is not None:
            dialog = self.handoff_dialog
            dialog.hide()
            dialog.deleteLater()
            self.handoff_dialog = None

    def _phase_lines(self, countdown="") -> tuple[str, str]:
        state = self.game.state
        active = state.players[state.active]
        phase = {"mulligan": "调度阶段", "upgrade": "升级阶段", "battle": "主要阶段"}.get(
            state.phase, "")
        if state.phase == "upgrade":
            phase += f"·剩余 {active.upgrades} 次"
        if countdown:
            phase += f"　⏱ {countdown}"
        return f"{active.name} 回合{active.turn_count}", phase

    def _update_phase_label(self, countdown="") -> None:
        turn, phase = self._phase_lines(countdown)
        self.phase_label.setText(
            f'<div>{html.escape(turn)}</div><div style="font-size:20px">'
            f'{html.escape(phase)}</div>')

    def _render_state(self) -> None:
        if self._handoff_pending:
            return
        game = self.game
        state = game.state
        self.timeline_queue[:] = [entry for entry in self.timeline_queue if entry[1]]
        self._update_phase_label()
        self.order_label.setText("己方先手" if self.viewer == state.active else "己方后手")
        self.order_label.hide()
        enemy = state.players[1 - self.viewer]
        own = state.players[self.viewer]
        self.enemy_hand_label.setText(f"敌方手牌\n{len(enemy.hand)} 张")
        self.enemy_deck_label.setText(f"敌方牌库\n{len(enemy.deck)} 张")
        self.own_deck_label.setText(f"己方牌库\n{len(own.deck)} 张")
        self.hand_caption.setText(f"己方手牌\n{len(own.hand)}/12 张")
        inputs = self._inputs_open()
        self.battle_scene.legal_targets = list(self.legal_targets)
        info = {} if state.pending_choice else self.hand_info()
        self.battle_scene.sync_state(game, self.viewer, info, inputs)
        turn_key = (state.turn, state.active)
        if (self._last_turn_key is not None and turn_key != self._last_turn_key
                and state.phase != "mulligan"):
            self.battle_scene.show_banner("回合开始")
        self._last_turn_key = turn_key
        if self._opening_banner_pending:
            order_text = "己方先手" if self.viewer == state.active else "己方后手"
            self.battle_scene.show_banner(order_text, 1200)
            self._opening_banner_pending = False
        self.end_turn_button.setEnabled(inputs and state.phase == "battle")
        self.ready_button.setVisible(state.phase == "mulligan")
        self.ready_button.setEnabled(inputs and state.phase == "mulligan")
        targeting = self.pending_command is not None
        self.cancel_target_button.setVisible(targeting or self._usage_pending is not None)
        self.default_target_button.setVisible(targeting and self.pending_command.get("op") == "assault")
        self.target_label.setText("请选择高亮目标" if targeting else "")
        self.target_label.setVisible(targeting)
        self.error_label.setVisible(bool(self.error_label.text()))
        if state.winner is not None:
            self._show_result()

    def hand_info(self) -> dict[int, dict]:
        return cli.hand_cards_info(self.game, self.viewer)

    def _inputs_open(self) -> bool:
        return (self.game is not None and not self._handoff_pending
                and self.game.state.winner is None
                and self.game.state.pending_choice is None
                and self.pending_command is None and self._usage_pending is None)

    def apply_command(self, command: dict) -> bool:
        if self.game is None or self._handoff_pending:
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
        player = self.game.state.players[self.viewer]
        self._review_mulligan = (command.get("op") == "mulligan"
                                 and player.mulligan_done and player.mulligans_left == 0)
        self.refresh()
        self._review_mulligan = False
        return True

    def mulligan(self, uid: int) -> bool:
        return self.apply_command({"op": "mulligan", "player": self.viewer, "uid": uid})

    def replace_mulligan(self) -> bool:
        uid = self.battle_scene.mulligan_uid
        return False if uid is None else self.mulligan(uid)

    def _sync_mulligan_button(self, _uid=None) -> None:
        uid = self.battle_scene.mulligan_uid
        visible = bool(self.game is not None and self.game.state.phase == "mulligan"
                       and uid is not None and self._inputs_open())
        if visible:
            card = self.battle_scene.cards.get(("hand", uid))
            if card is not None:
                rect = card.sceneBoundingRect()
                self.battle_scene.mulligan_item.setPos(
                    rect.center().x() - self.battle_scene.mulligan_item.boundingRect().width() / 2,
                    rect.bottom() + 8)
        self.mulligan_button.setVisible(visible)

    def ready(self) -> bool:
        return self.apply_command({"op": "ready", "player": self.viewer})

    def upgrade(self, index: int) -> bool:
        return self.apply_command({"op": "upgrade", "index": index})

    def end_turn(self) -> bool:
        return self.apply_command({"op": "end_turn"})

    def assault(self, index: int, target=None) -> bool:
        if not self._inputs_open() or self.game.state.phase != "battle":
            return False
        command = {"op": "assault", "index": index}
        if target is not None:
            command["target"] = target
            return self.apply_command(command)
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

    def _clear_usage(self) -> None:
        self._usage_pending = None
        self.battle_scene.clear_usage_options()

    def _select_usage(self, usage_id) -> bool:
        if self._usage_pending is None:
            return False
        uid, target = self._usage_pending
        self._clear_usage()
        return self.play_card(uid, usage_id=usage_id, target=target)

    def play_card(self, uid: int, usage_id=..., target=None, from_drag=False) -> bool:
        if not self._inputs_open() or self.game.state.phase != "battle":
            return False
        card = next((card for card in self.game.current.hand if card.uid == uid), None)
        if card is None:
            return False
        definition = self.db.cards[card.id]
        options = self.game.usage_options(self.game.state.active, card)
        if not options:
            return False
        if usage_id is ...:
            if len(options) == 1:
                usage_id = options[0]["id"]
            else:
                self._usage_pending = (uid, target)
                self._render_state()
                card_defs = ([self.db.cards[cid] for cid in definition.options]
                             if definition.card_type == "reinforce"
                             else [definition] * len(options))
                self.battle_scene.show_usage_options(options, card_defs)
                return True
        option = next((item for item in options if item["id"] == usage_id), None)
        if option is None or not option["ok"]:
            self.error_label.setText("该使用方式当前不可用")
            return False
        command = {"op": "play_card", "uid": uid}
        if isinstance(usage_id, str) and usage_id.startswith("choice:"):
            choice = int(usage_id.split(":", 1)[1])
            command["choice"] = choice
        elif usage_id is not None:
            command["play_method"] = usage_id
        effective_target = usage_target(self.game, self.game.state.active,
                                        definition, usage_id)
        if target is not None:
            legal = (targets.spec_pool_refs(
                self.game, effective_target, self.game.state.active, targeted=True)
                if effective_target.kind == "choose" else [])
            if target not in legal:
                self.error_label.setText("出牌目标不合法")
                return False
            command["target"] = target
        elif from_drag and effective_target.kind == "choose":
            self.error_label.setText("该使用方式需要选择目标")
            return False
        specs = []
        if effective_target.kind == "choose" and target is None:
            specs.append(("target", effective_target))
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
        self._clear_usage()
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

    def show_shiki_detail(self, ref: Ref) -> None:
        ShikigamiDetailDialog(self.game, ref, self.viewer, self).exec()

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
            f"鬼火 {player.orb}　出击次数 {player.assaults_left}\n"
            f"墓地 {len(player.graveyard)}\n{fields}")
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        dialog.exec()

    def show_card_detail(self, card) -> None:
        viewer_hand = self.game.state.players[self.viewer].hand
        runtime = None
        if any(owned.uid == card.uid for owned in viewer_hand):
            runtime = self.hand_info().get(card.uid)
        cdef = self.db.cards[card.id]
        owner = next((player for player in self.game.state.players
                      if any(owned.uid == card.uid for owned in player.hand)),
                     self.game.state.players[self.viewer])
        seat = card_owner_seat(self.game, owner, cdef)
        CardDetailDialog(cdef, self.db, self, runtime=runtime,
                         level_color=seat_level_color(seat)).exec()

    def choice_option_def(self, pending: dict, option):
        kind = pending.get("kind")
        player = self.game.state.players[pending["player"]]
        if kind in ("deck_top_pick", "mulligan_pick", "discard_pick", "quest_complete_pick"):
            zones = [player.deck] if kind == "deck_top_pick" else [player.hand]
            card = next((card for zone in zones for card in zone if card.uid == option), None)
            return self.db.cards[card.id] if card is not None else None
        if kind in ("field_summon_pick", "pick_generate") or (
                kind == "card_name" and pending.get("stage") != "shikigami"):
            return self.db.cards[option]
        return None

    def choice_option_label(self, pending: dict, option) -> str:
        kind = pending.get("kind")
        definition = self.choice_option_def(pending, option)
        if definition is not None:
            return f"{definition.name}\n{definition.text or ''}"
        if kind == "card_name" and pending.get("stage") == "shikigami":
            return self.db.shikigami[option].name
        if kind == "invocation_pick":
            definition = self.db.invocations.get(option)
            return f"{option}\n{definition.text if definition is not None else ''}"
        return str(option)

    def _close_choice_dialog(self, dialog=None) -> None:
        target = dialog or self.choice_dialog
        if target is None:
            self._choice_key = None
            return
        if self.choice_dialog is target:
            self.choice_dialog = None
            self._choice_key = None
        target.hide()
        target.deleteLater()

    def _sync_pending_choice(self) -> None:
        if self._handoff_pending:
            return
        pending = self.game.state.pending_choice
        if pending is None:
            self._close_choice_dialog()
            return
        key = (pending.get("kind"), pending.get("stage"), tuple(pending.get("options", [])))
        if key == self._choice_key and self.choice_dialog is not None:
            return
        self._close_choice_dialog()
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
            if entry.get("k") == "a":
                if not self._handoff_pending:
                    self.battle_scene.animate_card_use(entry["u"], entry["c"], entry["p"])
            else:
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
        self._sync_mulligan_button()
        self.battle_scene.inputs_open = enabled
        if not enabled:
            self.battle_scene.drag_controller.cancel()
            for item in self.battle_scene.cards.values():
                item.playable = False
                item.update()

    def _show_result(self) -> None:
        self.result_banner.setText(cli.result_text(
            self.game.state.winner, [player.name for player in self.game.state.players]))
        self.result_banner.show()
        self.result_back.show()

    def return_to_menu(self) -> bool:
        if (self.exit_confirmation and self.game is not None
                and self.stack.currentWidget() is self.battle_page
                and self.game.state.winner is None):
            answer = ask_confirmation(self, "终止对局", "确定结束当前对局并返回主菜单？")
            if answer != QMessageBox.Yes:
                return False
        self.timeline_timer.stop()
        self._clear_usage()
        self.battle_scene.reset_animations()
        self.battle_scene.hide_banner()
        self.battle_scene.hide_loading()
        self._close_handoff()
        self.close_log()
        if self.choice_dialog is not None:
            self.choice_dialog.close()
            self.choice_dialog = None
        if self.on_back is not None:
            self.on_back()
        return True
