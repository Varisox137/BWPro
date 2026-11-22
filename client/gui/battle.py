"""桌面 GUI 本地热坐对战：标准卡组开局、场况、操作与结算播放。"""
from __future__ import annotations

import html
import secrets
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from client import presentation as cli
from client.gui.battle_scene import (
    DRAG_Z, END_TURN_SIZE, BattleScene, BattleView, card_owner_seat, usage_target,
)
from client.gui.cardart import seat_level_color
from client.gui.card_options import resolve_card_option, runtime_art_options, usage_card_option
from client.gui.details import ShikigamiDetailDialog, player_ability_mechanisms
from client.gui.player_details import PlayerDetailDialog
from client.gui.ui_assets import end_turn_button_pixmap, ui_pixmap
from client.gui.widgets import CardChoiceView, CardDetailDialog, ask_confirmation, polish_dialog_buttons
from core import targets
from core.engine import IllegalAction
from core.model import Ref
from core.setup import new_game
from db import deckstore
from db.deck import STANDARD_RULES
from db.envs import available_env_dates, env_label


class DeckSelectDialog(QDialog):
    """开局卡组选择：仅列符合当前数据环境与卡组规则的本地卡组。"""

    def __init__(self, db, store_path: Path, player_name: str, parent=None,
                 rules=STANDARD_RULES):
        super().__init__(parent)
        self.setWindowTitle(f"{player_name} 选择卡组")
        self.resize(520, 480)
        self.entries = [entry for entry in deckstore.load_decks(db, store_path, rules=rules)
                        if entry.get("standard")]
        layout = QVBoxLayout(self)
        rule_text = "标准卡组" if rules is not None else "当前可用的卡组"
        layout.addWidget(QLabel(f"{player_name}：仅显示{rule_text}"))
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
    """结算与主动使用共用 CardChoiceView，作答值始终独立于展示。"""

    def __init__(self, view: "HotseatView", pending: dict, *, options=None,
                 title: str | None = None, on_answer=None, on_cancel=None):
        super().__init__(view)
        self._game = view.game
        self._pending = pending
        self._on_answer = on_answer
        self._on_cancel = on_cancel
        self._custom_options = options
        self._title = title
        self.setModal(False)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 12)
        self.title_label = QLabel()
        self._layout.addWidget(self.title_label)
        self.option_view = None
        self.done_button = None
        self.cancel_button = None
        self.update_pending(pending)
        kind = pending.get("kind")
        if kind in ("mulligan", "mulligan_pick") or on_cancel is not None:
            footer = QHBoxLayout()
            footer.addStretch(1)
            if on_cancel is not None:
                self.cancel_button = QPushButton("取消")
                self.cancel_button.setObjectName("dialogButton")
                self.cancel_button.setFixedSize(96, 30)
                self.cancel_button.clicked.connect(self.reject)
                footer.addWidget(self.cancel_button)
            else:
                self.done_button = QPushButton("结束调度")
                self.done_button.setObjectName("dialogButton")
                self.done_button.setFixedSize(96, 30)
                self.done_button.clicked.connect(lambda: self._answer(None))
                footer.addWidget(self.done_button)
            self._layout.addLayout(footer)
        self.resize(self.sizeHint())

    def update_pending(self, pending: dict) -> None:
        view = self.parent()
        self._game = view.game
        self._pending = pending
        self.setEnabled(True)
        kind = pending.get("kind")
        self.setWindowTitle("选择使用方式" if self._on_answer is not None else
                            "初始调度" if kind == "mulligan" else "结算选择")
        player = view.game.state.players[pending["player"]]
        titles = {
            "deck_top_pick": "检视牌库顶，选择一张置入手牌",
            "mulligan": "选择一张起始手牌调度，或结束调度",
            "mulligan_pick": "选择一张手牌调度，或结束调度",
            "discard_pick": "选择一张手牌弃置",
            "search_deck_pick": "从牌库选择一张牌置入手牌",
            "quest_complete_pick": "选择一张紧急委托，使其视为达成",
            "card_name": "选择敌方式神" if pending.get("stage") == "shikigami" else "选择一张牌名",
            "field_summon_pick": "选择要召唤的幻境",
            "pick_generate": "选择一张牌置入手牌",
            "invocation_pick": "选择一张灵咒牌结附",
        }
        title = self._title or titles.get(kind, "请选择一项")
        self.title_label.setText(f"{player.name}：{title}")
        if self._custom_options is not None:
            options = list(self._custom_options)
        else:
            previews = pending.get("previews") or []
            options = []
            runtime_info = None
            for index, answer in enumerate(pending.get("options", [])):
                preview = previews[index] if index < len(previews) else None
                option = resolve_card_option(view.game, view.viewer, pending, answer, preview)
                if option.instance is not None and any(
                        owned.uid == option.instance.uid
                        for owned in view.game.state.players[view.viewer].hand):
                    if runtime_info is None:
                        runtime_info = view.hand_info()
                    option.art_options = {
                        **runtime_art_options(runtime_info.get(option.instance.uid)),
                        **option.art_options,
                    }
                options.append(option)
        previous = self.option_view
        self.option_view = CardChoiceView(options, db=view.db)
        self.option_view.widget().layout().setSpacing(4)
        self.option_view.chosen.connect(self._answer)
        self.option_view.detail_clicked.connect(view.show_card_option_detail)
        self._layout.insertWidget(1, self.option_view, 1)
        if previous is not None:
            self._layout.removeWidget(previous)
            previous.hide()
            previous.deleteLater()
        visible = max(1, min(len(options), 5))
        width = 24 + visible * 194 + max(0, visible - 1) * 4 + 2 * self.option_view.frameWidth()
        self.option_view.setFixedWidth(width)
        self.resize(self.sizeHint())

    def _answer(self, value) -> None:
        if not self.isEnabled():
            return
        self.setEnabled(False)
        view = self.parent()
        game = self._game
        pending = self._pending
        kind = pending.get("kind")
        generation = view._choice_generation
        if self._on_answer is None and kind not in ("mulligan", "mulligan_pick"):
            view._close_choice_dialog(self)

        def context_open() -> bool:
            if (view._choice_generation != generation or view.game is not game
                    or game.state.winner is not None or getattr(view, "_game_over", False)):
                return False
            if self._on_answer is not None:
                return view.usage_dialog is self and view._usage_pending is not None
            if kind == "mulligan":
                player = pending["player"]
                return (game.state.phase == "mulligan" and view.viewer == player
                        and not game.state.players[player].mulligan_done)
            return game.state.pending_choice is pending

        def answer() -> None:
            if not context_open():
                return
            if self._on_answer is not None:
                answered = self._on_answer(value)
            elif kind == "mulligan":
                answered = view.ready() if value is None else view.mulligan(value)
            else:
                answered = view.answer_pending(value)
            if not answered and context_open():
                self.setEnabled(True)
                if self._on_answer is None:
                    view._sync_pending_choice()

        QTimer.singleShot(0, view, answer)

    def reject(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()


class DeckInvocationDialog(QDialog):
    """牌库中结附灵咒的种类与数量，不显示具体卡牌。"""

    def __init__(self, player_name: str, counts: dict[str, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{player_name}的牌库灵咒")
        layout = QVBoxLayout(self)
        for name, count in sorted(counts.items()):
            layout.addWidget(QLabel(f"{name} × {count}"))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BattleErrorLabel(QLabel):
    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.setText("")


class HotseatView(QWidget):
    """热坐单屏视图；手牌与非公开结算仅显示当前行动/作答方。"""

    state_changed = Signal()
    exit_confirmation = True

    def __init__(self, db, store_path: Path = deckstore.PATH, on_back=None,
                 official_db=None, parent=None):
        super().__init__(parent)
        self.official_db = official_db if official_db is not None else db
        self.diy_db = db
        self.base_db = self.official_db
        self.db = self.base_db
        self.store_path = Path(store_path)
        self.on_back = on_back
        self.theme = "light"
        self.game = None
        self.viewer = 0
        self._last_turn_key = None
        self._opening_banner_pending = True
        self.pending_command: dict | None = None
        self._usage_pending: tuple[int, Ref | None] | None = None
        self.target_specs: list[tuple[str, object]] = []
        self.legal_targets: list[Ref] = []
        self.choice_dialog: ChoiceDialog | None = None
        self.usage_dialog: ChoiceDialog | None = None
        self._choice_key = None
        self._choice_generation = 0
        self._handoff_pending = False
        self._handoff_stage = None
        self._handoff_waiting = False
        self._handoff_boundary_seen = False
        self.handoff_dialog = None  # 兼容外部检查；热坐交接已改为场景内按钮
        self._timeline_seen = 0
        self._deferred_visuals: list[dict] = []
        self.timeline_queue: list[tuple[int | None, str]] = []
        self.played_timeline: list[tuple[int | None, str]] = []
        self._build_ui()
        self.timeline_timer = QTimer(self)
        self.timeline_timer.setInterval(200)
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
        hint = QLabel("双方依次选择本地卡组，在同一设备轮流操作")
        hint.setAlignment(Qt.AlignCenter)
        setup.addWidget(hint)
        options = QHBoxLayout()
        options.addStretch(1)
        options.addWidget(QLabel("数据环境"))
        self.env_combo = QComboBox()
        self.env_combo.setMinimumWidth(190)
        options.addWidget(self.env_combo)
        options.addWidget(QLabel("卡组规则"))
        self.rules_combo = QComboBox()
        self.rules_combo.addItem("标准", "standard")
        self.rules_combo.addItem("自由", "free")
        options.addWidget(self.rules_combo)
        self.diy_checkbox = QCheckBox("DIY")
        self.diy_checkbox.setChecked(False)
        self.diy_checkbox.toggled.connect(self._change_content)
        options.addWidget(self.diy_checkbox)
        options.addStretch(1)
        setup.addLayout(options)
        self._reload_environments()
        self.start_button = QPushButton("开始对战")
        self.start_button.clicked.connect(self.start_hotseat)
        setup.addWidget(self.start_button, alignment=Qt.AlignCenter)
        setup.addStretch(1)
        self.stack.addWidget(self.setup_page)
        self.battle_page = QWidget()
        self._build_battle_page()
        self.stack.addWidget(self.battle_page)

    def _reload_environments(self) -> None:
        previous = self.env_combo.currentData()
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        self.env_combo.addItem(env_label(None), None)
        for date in available_env_dates(self.base_db):
            self.env_combo.addItem(env_label(date), date)
        index = self.env_combo.findData(previous)
        self.env_combo.setCurrentIndex(max(0, index))
        self.env_combo.blockSignals(False)

    def _game_database(self):
        return self.base_db.at_date(self.env_combo.currentData())

    def current_rules(self):
        return STANDARD_RULES if self.rules_combo.currentData() == "standard" else None

    def set_databases(self, diy_db, official_db) -> None:
        self.diy_db = diy_db
        self.official_db = official_db
        self._change_content()

    def _change_content(self) -> None:
        self.base_db = self.diy_db if self.diy_checkbox.isChecked() else self.official_db
        self.db = self.base_db
        self.battle_scene.db = self.base_db
        self._reload_environments()

    def _build_battle_page(self) -> None:
        layout = QVBoxLayout(self.battle_page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.battle_scene = BattleScene(self.db)
        self.battle_scene.animations_settled.connect(self._render_state)
        self.battle_view = BattleView(self.battle_scene)
        layout.addWidget(self.battle_view)

        self.menu_button = QPushButton("游戏设置")
        self.menu_button.setObjectName("battleSmall")
        self.menu_button.clicked.connect(self.open_settings)
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
        self.end_turn_button = QPushButton()
        self.end_turn_button.setFlat(True)
        self.end_turn_button.setObjectName("endTurnButton")
        self.end_turn_button.clicked.connect(self.end_turn)
        self.battle_scene.end_turn_item = self.battle_scene.add_control(
            self.end_turn_button, ("end_turn",), (END_TURN_SIZE, END_TURN_SIZE))

        self.enemy_hand_label = QLabel()
        self.enemy_hand_label.setObjectName("enemyHandBack")
        self.enemy_deck_label = QLabel()
        self.own_deck_label = QLabel()
        for key, label in (("enemy_hand_label", self.enemy_hand_label),
                           ("enemy_deck", self.enemy_deck_label),
                           ("own_deck", self.own_deck_label)):
            label.setAlignment(Qt.AlignCenter)
            self.battle_scene.add_control(label, (key,), (68, 64))
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
        self.own_hand_label = QLabel()
        self.own_hand_label.setAlignment(Qt.AlignCenter)
        self.battle_scene.add_control(self.own_hand_label, ("own_hand_label",), (68, 64))
        self.handoff_button = QPushButton("切换玩家")
        self.handoff_button.setObjectName("battleSmall")
        self.handoff_button.clicked.connect(self.confirm_handoff)
        self.battle_scene.handoff_item = self.battle_scene.add_control(
            self.handoff_button, ("handoff",), (104, 34))
        self.battle_scene.handoff_item.hide()
        self.order_label = QLabel()
        self.order_label.setObjectName("turnOrderLabel")
        self.order_label.setAlignment(Qt.AlignCenter)
        self.battle_scene.add_control(self.order_label, ("turn_order",), (300, 90))
        self.error_label = BattleErrorLabel()
        self.error_label.setObjectName("battleError")
        self.error_label.setWordWrap(True)
        self.battle_scene.add_control(self.error_label, ("error",), (400, 64))
        self.result_banner = QLabel()
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setAlignment(Qt.AlignCenter)
        self.battle_scene.result_item = self.battle_scene.add_control(
            self.result_banner, ("result_banner",), (560, 400))
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
        self.battle_scene.target_requested.connect(self._scene_target)
        self.battle_scene.read_detail_requested.connect(self._scene_read_detail)

    def _scene_read_detail(self, kind: str, payload) -> None:
        if kind == "shiki":
            self.show_shiki_detail(payload)
        elif kind == "player":
            self.show_player_detail(payload.player)
        elif kind == "hand":
            self.show_card_detail(payload)
        elif kind == "deck_back":
            self.show_deck_invocations(payload[1])

    def deck_invocation_counts(self, pi: int) -> dict[str, int]:
        return cli.deck_invocation_counts(self.game, pi)

    def show_deck_invocations(self, pi: int) -> None:
        counts = self.deck_invocation_counts(pi)
        if not counts:
            return
        player = self.game.state.players[pi]
        DeckInvocationDialog(player.name, counts, self).exec()

    def _scene_action(self, command: dict) -> bool:
        op = command.get("op")
        if op == "upgrade":
            return self.upgrade(command["index"])
        if op == "assault":
            return self.assault(command["index"], target=command.get("target"))
        if op == "play_card":
            return self.play_card(command["uid"], target=command.get("target"),
                                  from_drag=True)
        return False

    def _scene_target(self, _kind: str, payload) -> None:
        if payload in self.legal_targets:
            self.choose_target(payload)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.battle_scene.set_text_color(colors["text"], theme)
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
                background: transparent; border: none; border-radius: 104px; padding: 0;
            }}
            QLabel#targetHint, QLabel#battleError, QLabel#resultBanner {{
                color: {colors['text']}; background: transparent; font-weight: 600;
            }}
            QLabel#resultBanner {{ font-size: 34px; padding: 0; }}
            QListWidget#battleLog {{ background: {colors['panel']}; color: {colors['text']}; }}
            QPushButton#battleSmall {{ padding: 4px; font-size: 12px; text-align: center; }}
        """)
        for label in (self.enemy_hand_label, self.enemy_deck_label,
                      self.own_deck_label, self.own_hand_label,
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
            "font-size: 34px; font-weight: 600; padding: 0;")
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
        self.end_turn_button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 104px; padding: 0; }")
        self._sync_end_turn_art()

    def start_hotseat(self) -> bool:
        game_db = self._game_database()
        rules = self.current_rules()
        first = DeckSelectDialog(game_db, self.store_path, "玩家A", self, rules=rules)
        if first.exec() != QDialog.Accepted:
            return False
        second = DeckSelectDialog(game_db, self.store_path, "玩家B", self, rules=rules)
        if second.exec() != QDialog.Accepted:
            return False
        return self._start_entries(first.selected_entry(), second.selected_entry())

    def start_from_decks(self, first_index: int, second_index: int, **kwargs) -> bool:
        entries = [entry for entry in deckstore.load_decks(
            self._game_database(), self.store_path, rules=self.current_rules())
                   if entry.get("standard")]
        return self._start_entries(entries[first_index], entries[second_index], **kwargs)

    def _start_entries(self, entry_a: dict, entry_b: dict, **kwargs) -> bool:
        self.db = self._game_database()
        self.battle_scene.db = self.db
        ids_a, cards_a = deckstore.entry_deck(entry_a)
        ids_b, cards_b = deckstore.entry_deck(entry_b)
        self.start_game(("玩家A", ids_a, cards_a), ("玩家B", ids_b, cards_b), **kwargs)
        return True

    def start_game(self, p1: tuple, p2: tuple, seed: int | None = None, **kwargs) -> None:
        kwargs.setdefault("check_deck", self.current_rules() is not None)
        self._choice_generation += 1
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
            self._last_turn_key = None
            self._opening_banner_pending = True
            self.battle_scene.hide_banner()
            self.pending_command = None
            self.target_specs = []
            self.legal_targets = []
            self._timeline_seen = 0
            self._deferred_visuals.clear()
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
        entries = self.game.state.timeline[self._timeline_seen:]
        turn_key = (self.game.state.turn, self.game.state.active)
        if (self.game.state.winner is None
                and self._last_turn_key is not None and turn_key != self._last_turn_key
                and any(entry.get("v") == "turn_start" for entry in entries)):
            self._render_state(show_turn=False, preserve_phase=True)
            self.viewer = next_viewer
            self._handoff_waiting = True
            self._handoff_boundary_seen = False
            self._enqueue_timeline()
            pending = self.game.state.pending_choice
            if pending is not None and pending["player"] == self.battle_scene.viewer:
                self._sync_pending_choice()
            elif not self.battle_scene.visual_busy:
                self._begin_handoff()
            return
        if previous_viewer != next_viewer and self.game.state.winner is None:
            self.viewer = next_viewer
            if not self._handoff_waiting:
                self._begin_handoff()
        else:
            self.viewer = next_viewer
        if self._handoff_waiting:
            self._enqueue_timeline()
            pending = self.game.state.pending_choice
            if pending is not None and pending["player"] == self.battle_scene.viewer:
                self._sync_pending_choice()
            elif not self.battle_scene.visual_busy:
                self._begin_handoff()
            return
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
        self.own_hand_label.clear()

    def _begin_handoff(self) -> None:
        self.timeline_timer.stop()
        self._clear_usage()
        self.battle_scene.reset_animations()
        self._handoff_waiting = False
        self._handoff_boundary_seen = False
        self._handoff_pending = True
        self._handoff_stage = "transfer"
        self._clear_hand()
        self.pending_command = None
        self.target_specs = []
        self.legal_targets = []
        self._close_choice_dialog()
        self.close_log()
        next_name = self.game.state.players[self.viewer].name
        self.handoff_button.setToolTip(f"确认后交给 {next_name}")
        offset_y = (self.battle_scene.end_turn_item.size().height()
                    - self.battle_scene.handoff_item.size().height()) / 2
        position = self.battle_scene.end_turn_item.pos() + QPointF(-112, offset_y)
        self.battle_scene.handoff_item.setPos(position)
        self.battle_scene.handoff_item.show()
        self._update_input_widgets()

    def confirm_handoff(self) -> None:
        if not self._handoff_pending:
            return
        self._handoff_pending = False
        self._handoff_stage = None
        self.battle_scene.handoff_item.hide()
        self._clear_hand()
        self._render_log()
        self._render_state()
        self._enqueue_timeline()
        deferred = self._deferred_visuals
        self._deferred_visuals = []
        for entry in deferred:
            self._dispatch_timeline_entry(entry)
        self._update_input_widgets()
        self._sync_pending_choice()

    def _close_handoff(self) -> None:
        self._handoff_pending = False
        self._handoff_stage = None
        self._handoff_waiting = False
        self._handoff_boundary_seen = False
        self.battle_scene.handoff_item.hide()

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

    def _sync_end_turn_art(self) -> None:
        opponent = bool(self.game is not None
                        and self.game.state.active != self.viewer)
        name = "opponent_turn_button" if opponent else "end_turn_button"
        self.end_turn_button.setProperty("assetName", name)
        self.end_turn_button.setIcon(QIcon(end_turn_button_pixmap(
            self.end_turn_button.width(), opponent=opponent)))
        self.end_turn_button.setIconSize(self.end_turn_button.size())

    def _render_state(self, play_pending=False, show_turn=True, preserve_phase=False) -> None:
        if self._handoff_waiting:
            pending = self.game.state.pending_choice
            if pending is not None and pending["player"] == self.battle_scene.viewer:
                self._sync_pending_choice()
            elif not self.battle_scene.visual_busy:
                self._begin_handoff()
            return
        if self._handoff_pending:
            return
        game = self.game
        state = game.state
        self.timeline_queue[:] = [entry for entry in self.timeline_queue if entry[1]]
        if not preserve_phase:
            self._update_phase_label()
        self.order_label.setText("己方先手" if self.viewer == state.active else "己方后手")
        self.order_label.hide()
        enemy = state.players[1 - self.viewer]
        own = state.players[self.viewer]
        self.enemy_hand_label.setText(f"敌方手牌\n{len(enemy.hand)} 张")
        self.enemy_deck_label.setText(f"敌方牌库\n{len(enemy.deck)} 张")
        self.own_deck_label.setText(f"己方牌库\n{len(own.deck)} 张")
        self.own_hand_label.setText(f"己方手牌\n{len(own.hand)}/12 张")
        inputs = self._inputs_open()
        self.battle_scene.legal_targets = list(self.legal_targets)
        info = {} if state.pending_choice else self.hand_info()
        pending_entries = (list(self._deferred_visuals)
                           + state.timeline[self._timeline_seen:])
        self.battle_scene.sync_state(
            game, self.viewer, info, inputs, pending_entries=pending_entries or None,
            play_pending=play_pending)
        turn_key = (state.turn, state.active)
        track_turn = show_turn and (state.pending_choice is None or state.active == self.viewer)
        if (track_turn and self._last_turn_key is not None and turn_key != self._last_turn_key
                and state.phase != "mulligan"):
            self.battle_scene.show_turn_banner(state.active == self.viewer)
        if track_turn:
            self._last_turn_key = turn_key
        if self._opening_banner_pending:
            self.battle_scene.show_opening_sequence(self.game, self.viewer)
            self._opening_banner_pending = False
        self.end_turn_button.setEnabled(inputs and state.phase == "battle")
        self._sync_end_turn_art()
        targeting = self.pending_command is not None
        self.cancel_target_button.setVisible(targeting or self._usage_pending is not None)
        default_assault = False
        if targeting and self.pending_command.get("op") == "assault":
            attacker = own.shikigami[self.pending_command["index"]]
            keywords = attacker.keywords + attacker.one_shot_keywords + attacker.perm_keywords
            default_assault = "assault_any_target" not in keywords
        self.default_target_button.setVisible(default_assault)
        self.target_label.setText("请选择高亮目标" if targeting else "")
        self.target_label.setVisible(targeting)
        self.error_label.setVisible(bool(self.error_label.text()))
        if state.winner is not None:
            self._show_result()
        self.state_changed.emit()

    def hand_info(self) -> dict[int, dict]:
        return cli.hand_cards_info(self.game, self.viewer)

    def _inputs_open(self) -> bool:
        return (self.game is not None and not self._handoff_pending
                and not self._handoff_waiting
                and self.game.state.winner is None
                and self.game.state.pending_choice is None
                and self.pending_command is None and self._usage_pending is None
                and not (self.game.state.phase == "upgrade"
                         and self.battle_scene.visual_busy))

    def apply_command(self, command: dict) -> bool:
        if self.game is None or self._handoff_pending:
            return False
        if self._handoff_waiting:
            pending = self.game.state.pending_choice
            if (command.get("op") != "choose" or pending is None
                    or command.get("player") != pending["player"]):
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
        if not self._inputs_open():
            return False
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
        legal = []
        label = ""
        if "assault_any_target" in keywords:
            legal = targets.pool_refs(self.game, "any_character",
                                      self.game.state.active, targeted=True)
            legal += targets.gated_defeated_refs(self.game, "any_character",
                                                 self.game.state.active)
            legal = [ref for ref in legal if ref != Ref(player=self.game.state.active,
                                                        shikigami=index)]
            label = "选择任一其他角色，或使用默认战斗区"
        elif "hunt" in keywords:
            legal = targets.pool_refs(self.game, "enemy_shikigami",
                                      self.game.state.active, targeted=True)
            label = "追猎：选择敌方目标，或使用默认战斗区"
        if legal:
            self.pending_command = command
            self.target_specs = []
            self.legal_targets = legal
            self.target_label.setText(label)
            self._render_state()
            return True
        return self.apply_command(command)

    def _clear_usage(self) -> None:
        self._usage_pending = None
        dialog = self.usage_dialog
        self.usage_dialog = None
        if dialog is not None:
            dialog._on_answer = None
            dialog._on_cancel = None
            dialog.hide()
            dialog.deleteLater()

    def _select_usage(self, usage_id) -> bool:
        if self._usage_pending is None:
            return False
        uid, target = self._usage_pending
        self._clear_usage()
        return self.play_card(uid, usage_id=usage_id, target=target)

    def _usage_options(self, card, runtime: dict):
        options = runtime.get("usage")
        if options is not None:
            return options
        return self.game.usage_options(self.game.state.active, card)

    def play_card(self, uid: int, usage_id=..., target=None, from_drag=False) -> bool:
        if not self._inputs_open() or self.game.state.phase != "battle":
            return False
        card = next((card for card in self.game.current.hand if card.uid == uid), None)
        if card is None:
            return False
        definition = self.db.cards[card.id]
        runtime = self.hand_info().get(uid, {})
        options = self._usage_options(card, runtime)
        if not options:
            return False
        if usage_id is ...:
            if len(options) == 1:
                usage_id = options[0]["id"]
            else:
                self._usage_pending = (uid, target)
                self._render_state()
                card_options = [usage_card_option(
                    self.game, self.game.state.active, card, option, runtime)
                                for option in options]
                self.usage_dialog = ChoiceDialog(
                    self, {"kind": "usage_options", "player": self.game.state.active},
                    options=card_options, title=f"选择【{definition.name}】的使用方式",
                    on_answer=self._select_usage, on_cancel=self.cancel_targeting)
                self.usage_dialog.show()
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
        if not self.target_specs and command.get("op") == "assault":
            command["target"] = ref
            return self.apply_command(command)
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

    def show_shiki_detail(self, ref: Ref) -> None:
        ShikigamiDetailDialog(self.game, ref, self.viewer, self).exec()

    def show_player_detail(self, pi: int) -> None:
        state = self.game.state.players[pi]
        if not state.fields and not player_ability_mechanisms(state, pi, self.viewer):
            return
        PlayerDetailDialog(self.game, pi, self.viewer, self).exec()

    def show_card_detail(self, card, art_options: dict | None = None) -> None:
        viewer_hand = self.game.state.players[self.viewer].hand
        runtime = None
        if any(owned.uid == card.uid for owned in viewer_hand):
            runtime = self.hand_info().get(card.uid)
        cdef = self.db.cards[card.id]
        owner = next((player for player in self.game.state.players
                      if any(owned.uid == card.uid for owned in player.hand)
                      or any(shikigami.form is not None and shikigami.form.uid == card.uid
                             for shikigami in player.shikigami)
                      or any(field.card.uid == card.uid for field in player.fields)),
                     self.game.state.players[self.viewer])
        seat = card_owner_seat(self.game, owner, cdef)
        detail_art_options = dict(art_options or {})
        source_id = card.appearance_source or card.origin_id
        if source_id is not None:
            detail_art_options.setdefault("appearance_source", source_id)
        CardDetailDialog(cdef, self.db, self, runtime=runtime,
                         level_color=seat_level_color(seat),
                         art_options=detail_art_options).exec()

    def show_card_option_detail(self, option) -> None:
        if option.instance is not None:
            self.show_card_detail(option.instance, art_options=option.art_options)
        elif option.cdef is not None:
            CardDetailDialog(option.cdef, self.db, self,
                             art_options=option.art_options).exec()

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
        if pending is None and self.game.state.phase == "mulligan":
            player = self.game.state.players[self.viewer]
            if not player.mulligan_done:
                pending = {"kind": "mulligan", "player": self.viewer,
                           "options": [card.uid for card in player.hand]}
        if pending is None:
            self._close_choice_dialog()
            return
        key = (pending.get("kind"), pending.get("player"), pending.get("stage"),
               tuple(pending.get("options", [])), repr(pending.get("previews")))
        if key == self._choice_key and self.choice_dialog is not None:
            return
        if (self.choice_dialog is not None and pending.get("kind") in ("mulligan", "mulligan_pick")
                and self.choice_dialog._pending.get("kind") == pending.get("kind")):
            self.choice_dialog.update_pending(pending)
        else:
            self._close_choice_dialog()
            self.choice_dialog = ChoiceDialog(self, pending)
        self._choice_key = key
        self.choice_dialog.show()

    def answer_pending(self, value) -> bool:
        pending = self.game.state.pending_choice
        if pending is None:
            return False
        command = {"op": "choose", "player": pending["player"]}
        if pending.get("kind") in ("deck_top_pick", "search_deck_pick", "mulligan_pick",
                                   "discard_pick", "quest_complete_pick"):
            if value is not None:
                command["uid"] = value
        else:
            command["choice"] = value
        return self.apply_command(command)

    def _dispatch_timeline_entry(self, entry: dict) -> None:
        if entry.get("k") == "a":
            self.battle_scene.animate_card_use(
                entry["u"], entry["c"], entry["p"], response=bool(entry.get("r")),
                timeline_index=entry.get("_t"))
        elif entry.get("k") == "v":
            self.battle_scene.play_visual_event(entry)
        else:
            self.timeline_queue.append((entry.get("o"), entry.get("m", "")))

    def _enqueue_timeline(self) -> None:
        start = self._timeline_seen
        entries = self.battle_scene.order_visual_entries([
            dict(entry, _t=start + index)
            for index, entry in enumerate(self.game.state.timeline[start:])])
        self._timeline_seen = len(self.game.state.timeline)
        for entry in entries:
            if self._handoff_waiting and entry.get("v") == "turn_start":
                self._handoff_boundary_seen = True
            deferred = (self._handoff_pending
                        or (self._handoff_waiting and self._handoff_boundary_seen))
            if deferred and entry.get("k") in ("a", "v"):
                self._deferred_visuals.append(entry)
            else:
                self._dispatch_timeline_entry(entry)
        if (self.timeline_queue and not self._handoff_pending
                and not self._handoff_waiting and not self.timeline_timer.isActive()):
            self.timeline_timer.start()
        self._update_input_widgets()
        if self.game.state.winner is not None and self.battle_scene.visual_busy:
            self.result_banner.hide()
            self.result_back.hide()

    def _render_log(self) -> None:
        self.log_list.clear()
        for owner, message in self.played_timeline:
            if owner is None or owner == self.viewer:
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
        if self._handoff_pending or self._handoff_waiting:
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
        self.battle_scene.inputs_open = enabled
        if not enabled:
            self.battle_scene.drag_controller.cancel()
            for item in self.battle_scene.cards.values():
                item.playable = False
                item.update()
        self.battle_scene._sync_focus()

    def _show_result(self) -> None:
        if self.battle_scene.visual_busy:
            return
        winner = self.game.state.winner
        if winner in (0, 1):
            name = "won" if winner == self.viewer else "lost"
            self.result_banner.setText("")
            self.result_banner.setPixmap(ui_pixmap(f"animations/{name}.png").scaled(
                520, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.result_banner.setText(cli.result_text(
                winner, [player.name for player in self.game.state.players]))
        self.result_banner.show()
        self.result_back.show()

    def _refresh_game_settings(self) -> None:
        self.battle_scene.refresh_cardbacks()
        self._sync_end_turn_art()

    def open_settings(self) -> None:
        from client.gui.settings import SettingsView

        dialog = QDialog(self)
        dialog.setWindowTitle("游戏设置")
        layout = QVBoxLayout(dialog)
        settings = SettingsView(self.db, dialog, on_change=self._refresh_game_settings)
        layout.addWidget(settings, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        dialog.resize(680, 520)
        dialog.exec()

    def return_to_menu(self) -> bool:
        if (self.exit_confirmation and self.game is not None
                and self.stack.currentWidget() is self.battle_page
                and self.game.state.winner is None):
            answer = ask_confirmation(self, "终止对局", "确定结束当前对局并返回主菜单？")
            if answer != QMessageBox.Yes:
                return False
        self._choice_generation += 1
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
        self.game = None
        self.timeline_queue.clear()
        self.played_timeline.clear()
        self._deferred_visuals.clear()
        self.result_banner.hide()
        self.result_back.hide()
        self.stack.setCurrentWidget(self.setup_page)
        if self.on_back is not None:
            self.on_back()
        return True
