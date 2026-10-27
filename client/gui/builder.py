"""桌面 GUI 卡组构筑：本地卡组管理、卡组码与增量编辑。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from client.deckbuilder import available_shikigami, buildable_cards
from client.gui.loading import LoadingIndicator
from client.gui.portrait import shikigami_portrait
from client.gui.widgets import (
    CardDetailDialog, CardWidget, ask_confirmation, polish_dialog_buttons,
    show_warning,
)
from db import deckcode, deckstore
from db.deck import STANDARD_RULES, rules_summary, validate_deck
from db.envs import ENV_ALIASES, env_label, parse_env_input
from db.packs import PACK_NAMES, PACKS

CARD_PAGE_SIZE = 5
DECK_PAGE_SIZE = 4


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class SwipeFrame(QFrame):
    """记录横向拖动；短距离移动仍保留子控件的点击行为。"""

    swiped = Signal(int)

    def mousePressEvent(self, event):
        self._drag_x = event.position().x() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        start = getattr(self, "_drag_x", None)
        if start is not None and event.button() == Qt.LeftButton:
            distance = event.position().x() - start
            if abs(distance) >= 70:
                self.swiped.emit(-1 if distance < 0 else 1)
            self._drag_x = None
        super().mouseReleaseEvent(event)


class DeckCodeDialog(QDialog):
    """卡组码导入/导出对话框。"""

    def __init__(self, code: str = "", *, editable: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入卡组码" if editable else "卡组码")
        self.setMinimumSize(620, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("粘贴卡组码：" if editable else "选中复制，或点击“复制卡组码”："))
        self.code_edit = QTextEdit()
        self.code_edit.setPlainText(code)
        self.code_edit.setReadOnly(not editable)
        layout.addWidget(self.code_edit)
        buttons = QDialogButtonBox()
        copy_button = buttons.addButton("复制卡组码", QDialogButtonBox.ActionRole)
        copy_button.clicked.connect(self.copy_code)
        buttons.addButton(QDialogButtonBox.Cancel if editable else QDialogButtonBox.Close)
        if editable:
            buttons.addButton(QDialogButtonBox.Ok)
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def code(self) -> str:
        return self.code_edit.toPlainText().strip()

    def copy_code(self) -> None:
        QApplication.clipboard().setText(self.code)


class ShikigamiDialog(QDialog):
    """按版本包分组的式神选择器，支持全名搜索。"""

    def __init__(self, db, exclude: set[int] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择式神")
        self.resize(720, 600)
        self.selected_id: int | None = None
        self.pool = [d for d in available_shikigami(db)
                     if not exclude or d.id not in exclude]
        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索式神全名")
        self.search_edit.textChanged.connect(self.populate)
        layout.addWidget(self.search_edit)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["式神名", "派系", "力量/生命"])
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 120)
        self.tree.setIndentation(12)
        self.tree.itemDoubleClicked.connect(lambda _item, _col: self.accept())
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.populate()

    def populate(self) -> None:
        self.tree.clear()
        query = self.search_edit.text().strip()
        for number, pack in PACKS.items():
            members = [d for d in self.pool if str(d.id)[2:4] == number
                       and (not query or query == d.name)]
            if not members:
                continue
            group = QTreeWidgetItem([PACK_NAMES.get(number, number), "", ""])
            self.tree.addTopLevelItem(group)
            for definition in members:
                item = QTreeWidgetItem(group, [definition.name, definition.faction,
                                               f"{definition.power}/{definition.health}"])
                item.setData(0, Qt.UserRole, definition.id)
        self.tree.expandAll()

    def accept(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.selected_id = item.data(0, Qt.UserRole)
        if self.selected_id is not None:
            super().accept()


class DeckBuilderView(QWidget):
    """卡组管理列表与编辑器；store_path 可注入以隔离测试数据。"""

    def __init__(self, db, store_path: Path = deckstore.PATH, parent=None):
        super().__init__(parent)
        self.db = db
        self.store_path = Path(store_path)
        self.theme = "light"
        self.decks: list[dict] = []
        self.deck_frames: list[QFrame] = []
        self.deck_page_index = 0
        self.card_widgets: list[CardWidget] = []
        self.page_index = 0
        self.page_count = 0
        self.current_index: int | None = None
        self.team: list[int] = []
        self.picks: dict[int, Counter] = {}
        self.selected_sid: int | None = None
        self.dirty = False
        self.loading_label = QLabel(self)
        self.loading_label.setObjectName("loadingLabel")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setFixedSize(400, 80)
        self.loading_label.hide()
        self.loading = LoadingIndicator("正在加载卡组", self._set_loading_text, self)
        self._build_ui()
        self.reload_decks()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.list_page = QWidget()
        self.editor_page = QWidget()
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.editor_page)
        self._build_list_page()
        self._build_editor_page()

    def _build_list_page(self) -> None:
        layout = QVBoxLayout(self.list_page)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        title = QLabel("卡组构筑")
        title.setObjectName("viewTitle")
        top.addWidget(title)
        top.addStretch(1)
        new_button = QPushButton("＋ 新建卡组")
        new_button.setObjectName("small")
        new_button.clicked.connect(self.new_deck)
        top.addWidget(new_button)
        import_button = QPushButton("导入卡组码")
        import_button.setObjectName("small")
        import_button.clicked.connect(self.show_import_dialog)
        top.addWidget(import_button)
        layout.addLayout(top)
        self.deck_area = SwipeFrame()
        self.deck_area.swiped.connect(self.turn_deck_page)
        self.deck_layout = QHBoxLayout(self.deck_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.deck_area)
        layout.addWidget(scroll, 1)
        pager = QHBoxLayout()
        self.deck_previous = QPushButton("‹")
        self.deck_next = QPushButton("›")
        for button in (self.deck_previous, self.deck_next):
            button.setObjectName("small")
            button.setFixedWidth(52)
        self.deck_previous.clicked.connect(lambda: self.turn_deck_page(-1))
        self.deck_next.clicked.connect(lambda: self.turn_deck_page(1))
        self.deck_page_label = QLabel()
        pager.addStretch(1)
        pager.addWidget(self.deck_previous)
        pager.addWidget(self.deck_page_label)
        pager.addWidget(self.deck_next)
        pager.addStretch(1)
        layout.addLayout(pager)

    def _build_editor_page(self) -> None:
        layout = QVBoxLayout(self.editor_page)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.editor_back = QPushButton("← 卡组列表")
        self.editor_back.setObjectName("small")
        self.editor_back.clicked.connect(self.leave_to_menu)
        top.addWidget(self.editor_back)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("卡组名称")
        self.name_edit.setMaximumWidth(280)
        self.name_edit.textChanged.connect(self._mark_dirty)
        top.addWidget(self.name_edit)
        self.code_button = QPushButton("卡组码")
        self.code_button.setObjectName("small")
        self.code_button.clicked.connect(self.show_current_code)
        top.addWidget(self.code_button)
        self.env_combo = QComboBox()
        self.env_combo.setEditable(True)
        self.env_combo.addItem(env_label(None), None)
        for date in dict.fromkeys(ENV_ALIASES.values()):
            self.env_combo.addItem(env_label(date), date)
        self.env_combo.setMinimumWidth(190)
        self.env_combo.activated.connect(self.change_environment)
        self.env_combo.lineEdit().editingFinished.connect(self.change_environment)
        top.addWidget(self.env_combo)
        save_button = QPushButton("保存")
        save_button.setObjectName("small")
        save_button.clicked.connect(self.save_editor)
        top.addWidget(save_button)
        layout.addLayout(top)
        self.standard_label = QLabel()
        self.standard_label.setObjectName("standardStatus")
        self.standard_label.setWordWrap(True)
        layout.addWidget(self.standard_label)
        body = QHBoxLayout()
        self.shiki_list = QListWidget()
        self.shiki_list.setFixedWidth(180)
        self.shiki_list.currentRowChanged.connect(self._select_shiki_row)
        self.shiki_list.itemDoubleClicked.connect(self._replace_shiki_item)
        body.addWidget(self.shiki_list)
        center = QVBoxLayout()
        self.card_area = SwipeFrame()
        self.card_area.swiped.connect(self.turn_card_page)
        self.card_layout = QHBoxLayout(self.card_area)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(4)
        center.addWidget(self.card_area, 1)
        pager = QHBoxLayout()
        self.card_previous = QPushButton("‹")
        self.card_next = QPushButton("›")
        for button in (self.card_previous, self.card_next):
            button.setObjectName("small")
            button.setFixedWidth(52)
        self.card_previous.clicked.connect(self.previous_card_page)
        self.card_next.clicked.connect(self.next_card_page)
        self.card_page_label = QLabel()
        pager.addStretch(1)
        pager.addWidget(self.card_previous)
        pager.addWidget(self.card_page_label)
        pager.addWidget(self.card_next)
        pager.addStretch(1)
        center.addLayout(pager)
        self.selected_bar = QLabel("尚未选择式神")
        self.selected_bar.setObjectName("selectedCards")
        self.selected_bar.setWordWrap(True)
        center.addWidget(self.selected_bar)
        body.addLayout(center, 1)
        layout.addLayout(body, 1)
        rules = QLabel("标准规则：" + "；".join(rules_summary(STANDARD_RULES))
                       + "（超限仅提示，不阻止保存）")
        rules.setObjectName("rulesHint")
        rules.setWordWrap(True)
        layout.addWidget(rules)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QFrame#deckFrame {{
                background: {colors['panel']}; border: 2px solid {colors['line']};
                border-radius: 10px;
            }}
            QFrame#card {{ background: transparent; border: none; }}
            QFrame#deckFrame[standard="true"] {{ border: 3px solid {colors['blue']}; }}
            QWidget#deckShikiRow, QFrame#deckFrame QLabel {{ background: transparent; border: none; }}
            QLabel#cardName {{ color: {colors['gold']}; font-size: 20px; font-weight: bold; }}
            QLabel#cardLevel, QLabel#cardStats, QLabel#standardStatus {{ color: {colors['blue']}; }}
            QLabel#cardMeta, QLabel#cardCount, QLabel#rulesHint {{ color: {colors['dim']}; }}
            QLabel#selectedCards {{ background: {colors['panel2']}; padding: 10px; }}
            QLineEdit, QTextEdit, QComboBox, QListWidget, QTreeWidget {{
                background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['line']}; padding: 5px;
            }}
            QListWidget::item:selected {{ background: {colors['gold2']}; color: {colors['text']}; }}
            QPushButton#cardStep {{ padding: 1px; font-size: 16px; text-align: center; }}
        """)

    def reload_decks(self) -> None:
        self.decks = deckstore.load_decks(self.db, self.store_path)
        self.show_list()

    def show_list(self) -> None:
        self.stack.setCurrentWidget(self.list_page)
        self._render_decks()

    def _mark_dirty(self, *_args) -> None:
        self.dirty = True

    def leave_to_menu(self) -> bool:
        if self.stack.currentWidget() is self.editor_page and self.dirty:
            box = QMessageBox(self)
            box.setWindowTitle("卡组未保存")
            box.setText("当前卡组有未保存的修改。")
            box.setInformativeText("保存修改后返回卡组列表，或放弃本次修改。")
            box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            polish_dialog_buttons(box)
            answer = box.exec()
            if answer == QMessageBox.Cancel:
                return False
            if answer == QMessageBox.Save and not self.save_editor():
                return False
        self.dirty = False
        self.reload_decks()
        return True

    def _render_decks(self) -> None:
        _clear_layout(self.deck_layout)
        self.deck_frames = []
        pages = max(1, (len(self.decks) + DECK_PAGE_SIZE - 1) // DECK_PAGE_SIZE)
        self.deck_page_index = max(0, min(self.deck_page_index, pages - 1))
        shown = self.decks[self.deck_page_index * DECK_PAGE_SIZE:
                           (self.deck_page_index + 1) * DECK_PAGE_SIZE]
        self.deck_layout.addStretch(1)
        for offset, entry in enumerate(shown):
            index = self.deck_page_index * DECK_PAGE_SIZE + offset
            frame = QFrame()
            frame.setObjectName("deckFrame")
            frame.setProperty("standard", bool(entry.get("standard")))
            frame.setMinimumWidth(250)
            frame.setMaximumWidth(290)
            column = QVBoxLayout(frame)
            name = QLabel(entry["name"])
            name.setObjectName("cardName")
            name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            name.setWordWrap(True)
            name.setFixedHeight(name.fontMetrics().lineSpacing() * 2)
            name.setToolTip(entry["name"])
            column.addWidget(name)
            env = QLabel(env_label(entry.get("env")))
            env.setObjectName("cardMeta")
            env.setAlignment(Qt.AlignCenter)
            column.addWidget(env)
            ids, _cards = deckstore.entry_deck(entry)
            for sid in ids:
                definition = self.db.shikigami.get(sid)
                row = QWidget()
                row.setObjectName("deckShikiRow")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 0, 4, 0)
                row_layout.setSpacing(10)
                avatar = QLabel()
                avatar.setObjectName("shikiPortrait")
                avatar.setFixedSize(96, 96)
                if definition is not None:
                    avatar.setPixmap(shikigami_portrait(definition))
                else:
                    avatar.setText("◆")
                    avatar.setAlignment(Qt.AlignCenter)
                row_layout.addWidget(avatar)
                label = QLabel(definition.name if definition is not None else str(sid))
                label.setObjectName("deckShikiName")
                label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                row_layout.addWidget(label, 1)
                column.addWidget(row)
            column.addStretch(1)
            edit = QPushButton("编辑")
            code = QPushButton("查看卡组码")
            rename = QPushButton("重命名")
            delete = QPushButton("删除")
            for button in (edit, code, rename, delete):
                button.setObjectName("small")
            edit.clicked.connect(lambda _=False, i=index: self.open_deck(i))
            code.clicked.connect(lambda _=False, i=index: self.show_export_dialog(i))
            rename.clicked.connect(lambda _=False, i=index: self.ask_rename(i))
            delete.clicked.connect(lambda _=False, i=index: self.delete_deck(i))
            column.addWidget(edit)
            actions = QHBoxLayout()
            for button in (code, rename, delete):
                actions.addWidget(button)
            column.addLayout(actions)
            self.deck_layout.addWidget(frame)
            self.deck_frames.append(frame)
        self.deck_layout.addStretch(1)
        self.deck_page_label.setText(f"第 {self.deck_page_index + 1}/{pages} 页")
        self.deck_previous.setEnabled(self.deck_page_index > 0)
        self.deck_next.setEnabled(self.deck_page_index < pages - 1)

    def turn_deck_page(self, direction: int) -> None:
        pages = max(1, (len(self.decks) + DECK_PAGE_SIZE - 1) // DECK_PAGE_SIZE)
        new_page = max(0, min(self.deck_page_index + direction, pages - 1))
        if new_page != self.deck_page_index:
            self.deck_page_index = new_page
            self._render_decks()

    def open_deck(self, index: int) -> None:
        self.edit_deck(index)

    def edit_deck(self, index: int) -> None:
        entry = self.decks[index]
        env = entry.get("env")
        edb = self.db.at_date(env)
        ids, cards = deckstore.entry_deck(entry)
        deckcode.available_deck_from_code(edb, deckstore.entry_code(entry))
        self.current_index = index
        self.team = list(ids)
        self.picks = {sid: Counter() for sid in ids}
        for cid in cards:
            cdef = edb.cards[cid]
            owner = cdef.shikigami if cdef.shikigami in ids else cdef.shikigami2
            self.picks[owner][cid] += 1
        self.name_edit.setText(entry["name"])
        self._set_env(env)
        self._enter_editor()

    def new_deck(self) -> None:
        self.current_index = None
        self.team = []
        self.picks = {}
        self.name_edit.clear()
        self._set_env(None)
        self._enter_editor()

    def _enter_editor(self) -> None:
        self.selected_sid = self.team[0] if self.team else None
        self.page_index = 0
        self.stack.setCurrentWidget(self.editor_page)
        self.dirty = False
        self._render_shiki_list()
        self._render_cards()
        self._update_validation()

    def _set_env(self, env: int | None) -> None:
        self.env_combo.setEditText(env_label(env))

    def current_env(self) -> int | None:
        text = self.env_combo.currentText().split("(", 1)[0].strip()
        return None if text == "标准" else parse_env_input(text)

    def change_environment(self, *_args) -> None:
        try:
            env = self.current_env()
        except ValueError as error:
            show_warning(self, "环境无效", str(error))
            return
        edb = self.db.at_date(env)
        self.team = [sid for sid in self.team if sid in edb.shikigami]
        self.picks = {sid: Counter({cid: n for cid, n in self.picks.get(sid, {}).items()
                                    if cid in edb.cards}) for sid in self.team}
        if self.selected_sid not in self.team:
            self.selected_sid = self.team[0] if self.team else None
        self._set_env(env)
        self._render_shiki_list()
        self._render_cards()
        self._update_validation()
        self._mark_dirty()

    def add_shikigami(self, sid: int) -> bool:
        if len(self.team) >= 4 or sid in self.team or sid not in self.db.at_date(self.current_env()).shikigami:
            return False
        self.team.append(sid)
        self.picks[sid] = Counter()
        self.selected_sid = sid
        self.page_index = 0
        self._render_shiki_list()
        self._render_cards()
        self._update_validation()
        self._mark_dirty()
        return True

    def choose_shikigami(self, replace_slot: int | None = None) -> None:
        edb = self.db.at_date(self.current_env())
        dialog = ShikigamiDialog(edb, set(self.team), self)
        if dialog.exec() != QDialog.Accepted:
            self._render_shiki_list()  # 取消后清除“添加式神”行的残留选中态
            return
        if replace_slot is None:
            self.add_shikigami(dialog.selected_id)
        else:
            self.replace_shikigami(replace_slot, dialog.selected_id)

    def replace_shikigami(self, slot: int, sid: int) -> bool:
        if sid in self.team or sid not in self.db.at_date(self.current_env()).shikigami:
            return False
        old = self.team[slot]
        self.team[slot] = sid
        self.picks.pop(old, None)
        self.picks[sid] = Counter()
        self.selected_sid = sid
        self.page_index = 0
        self._render_shiki_list()
        self._render_cards()
        self._update_validation()
        self._mark_dirty()
        return True

    def _render_shiki_list(self) -> None:
        self.shiki_list.blockSignals(True)
        self.shiki_list.clear()
        edb = self.db.at_date(self.current_env())
        for sid in self.team:
            definition = edb.shikigami[sid]
            count = sum(self.picks.get(sid, {}).values())
            item = QListWidgetItem(self.shiki_list)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(definition.name), 1)
            count_label = QLabel(f"{count}/8")
            count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_layout.addWidget(count_label)
            item.setSizeHint(row_widget.sizeHint())
            self.shiki_list.setItemWidget(item, row_widget)
        if len(self.team) < 4:
            QListWidgetItem("＋ 添加式神", self.shiki_list)
        row = self.team.index(self.selected_sid) if self.selected_sid in self.team else -1
        self.shiki_list.setCurrentRow(row)
        self.shiki_list.blockSignals(False)

    def _select_shiki_row(self, row: int) -> None:
        if row == len(self.team) and len(self.team) < 4:
            self.choose_shikigami()
        elif 0 <= row < len(self.team):
            self.select_shikigami(self.team[row])

    def _replace_shiki_item(self, item) -> None:
        row = self.shiki_list.row(item)
        if 0 <= row < len(self.team):
            self.choose_shikigami(row)

    def select_shikigami(self, sid: int) -> None:
        self.selected_sid = sid
        self.page_index = 0
        self._render_shiki_list()
        self._render_cards()

    def _current_cards(self) -> list:
        if self.selected_sid is None:
            return []
        edb = self.db.at_date(self.current_env())
        return [edb.shikigami[self.selected_sid]] + buildable_cards(edb, self.selected_sid)

    def _set_loading_text(self, text: str) -> None:
        self.loading_label.setText(text)
        self.loading_label.setGeometry(0, 0, self.width(), self.height())

    def _start_loading(self) -> None:
        self._set_loading_text("正在加载卡组 0.0s")
        self.stack.hide()
        self.loading_label.show()
        self.loading_label.raise_()
        self.loading.start()

    def _loading_tick(self) -> None:
        self.loading.tick()

    def _finish_loading(self) -> None:
        self.loading.stop()
        self.loading_label.hide()
        self.stack.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.loading_label.isVisible():
            self._set_loading_text(self.loading_label.text())

    def _render_cards(self) -> None:
        self._start_loading()
        try:
            _clear_layout(self.card_layout)
            self.card_widgets = []
            cards = self._current_cards()
            self.page_count = max(1, (len(cards) + CARD_PAGE_SIZE - 1) // CARD_PAGE_SIZE)
            self.page_index = max(0, min(self.page_index, self.page_count - 1))
            shown = cards[self.page_index * CARD_PAGE_SIZE:(self.page_index + 1) * CARD_PAGE_SIZE]
            art_context = {}
            for cdef in shown:
                base_shiki = getattr(cdef, "card_type", None) is None
                copies = self.picks.get(self.selected_sid, {}).get(cdef.id, 0)
                widget = CardWidget(cdef, copies, editable=not base_shiki, db=self.db,
                                    art_context=art_context)
                if base_shiki:
                    widget.count_label.setText(" ")
                else:
                    widget.plus_button.clicked.connect(
                        lambda _=False, cid=cdef.id: self.change_card(cid, 1))
                    widget.minus_button.clicked.connect(
                        lambda _=False, cid=cdef.id: self.change_card(cid, -1))
                widget.clicked.connect(self.show_card_detail)
                self.card_layout.addWidget(widget, 1)
                self.card_widgets.append(widget)
                self._loading_tick()
            self.card_layout.addStretch(1)
            self.card_page_label.setText(f"第 {self.page_index + 1}/{self.page_count} 页")
            self.card_previous.setEnabled(self.page_index > 0)
            self.card_next.setEnabled(self.page_index < self.page_count - 1)
            self._render_selected_bar()
        finally:
            self._finish_loading()

    def _render_selected_bar(self) -> None:
        if self.selected_sid is None:
            self.selected_bar.setText("尚未选择式神")
            return
        edb = self.db.at_date(self.current_env())
        picks = self.picks.get(self.selected_sid, {})
        text = "　".join(f"{edb.cards[cid].name}×{count}" for cid, count in sorted(picks.items()) if count)
        self.selected_bar.setText(f"已选卡（{sum(picks.values())}/8）：{text or '无'}")

    def turn_card_page(self, direction: int) -> None:
        new_page = max(0, min(self.page_index + direction, self.page_count - 1))
        if new_page != self.page_index:
            self.page_index = new_page
            self._render_cards()

    def next_card_page(self) -> None:
        self.turn_card_page(1)

    def previous_card_page(self) -> None:
        self.turn_card_page(-1)

    def change_card(self, cid: int, delta: int) -> None:
        if self.selected_sid is None or cid not in {c.id for c in self._current_cards()}:
            return
        picks = self.picks.setdefault(self.selected_sid, Counter())
        picks[cid] = max(0, picks[cid] + delta)
        if not picks[cid]:
            del picks[cid]
        self._render_cards()
        self._render_shiki_list()
        self._update_validation()
        self._mark_dirty()

    def _editor_groups(self):
        edb = self.db.at_date(self.current_env())
        card_ids = [cid for sid in self.team for cid, n in self.picks.get(sid, {}).items()
                    for _ in range(n)]
        return deckcode.group_deck(edb, self.team, card_ids)

    def _update_validation(self) -> None:
        if not hasattr(self, "standard_label"):
            return
        edb = self.db.at_date(self.current_env())
        card_ids = [cid for sid in self.team for cid, n in self.picks.get(sid, {}).items()
                    for _ in range(n)]
        errors = validate_deck(edb, self.team, card_ids, STANDARD_RULES)
        self.standard_label.setText("✓ 标准卡组" if not errors else "非标准卡组：" + "；".join(errors))
        self.standard_label.setProperty("standard", not errors)

    def save_editor(self) -> bool:
        if not self.team:
            show_warning(self, "无法保存", "请至少选择一名式神；空卡组不能写入本地存储。")
            return False
        try:
            env = self.current_env()
            groups = self._editor_groups()
            name = self.name_edit.text().strip()
            if not name:
                name = "/".join(self.db.shikigami[sid].name for sid in self.team)
            entry = {"name": name, "groups": groups, "env": env}
            if self.current_index is None:
                self.decks.append(entry)
            else:
                self.decks[self.current_index] = entry
            deckstore.save_decks(self.db, self.decks, self.store_path)
        except (ValueError, OSError) as error:
            show_warning(self, "保存失败", str(error))
            return False
        self.dirty = False
        self.reload_decks()
        return True

    def rename_deck(self, index: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("卡组名称不能为空")
        self.decks[index]["name"] = name
        deckstore.save_decks(self.db, self.decks, self.store_path)
        self.reload_decks()

    def ask_rename(self, index: int) -> None:
        dialog = QInputDialog(self)
        dialog.setWindowTitle("重命名卡组")
        dialog.setLabelText("卡组名称：")
        dialog.setTextValue(self.decks[index]["name"])
        dialog.show()  # QInputDialog 的标准按钮在首次显示时才创建
        polish_dialog_buttons(dialog)
        if dialog.exec() == QDialog.Accepted and dialog.textValue().strip():
            self.rename_deck(index, dialog.textValue())

    def delete_deck(self, index: int, confirmed: bool = False) -> bool:
        if not confirmed:
            answer = ask_confirmation(self, "删除卡组",
                                      f"确认删除卡组「{self.decks[index]['name']}」？")
            if answer != QMessageBox.Yes:
                return False
        self.decks.pop(index)
        deckstore.save_decks(self.db, self.decks, self.store_path)
        self.reload_decks()
        return True

    def export_code(self, index: int) -> str:
        return deckstore.entry_code(self.decks[index])

    def show_export_dialog(self, index: int) -> None:
        DeckCodeDialog(self.export_code(index), parent=self).exec()

    def show_current_code(self) -> None:
        if self.team:
            DeckCodeDialog(deckcode.encode_deck(self._editor_groups()), parent=self).exec()

    def import_code(self, code: str, name: str = "", env: int | None = None) -> None:
        edb = self.db.at_date(env)
        ids, cards = deckcode.available_deck_from_code(edb, code)
        groups = deckcode.group_deck(edb, ids, cards)
        if not name:
            name = "/".join(edb.shikigami[sid].name for sid in ids)
        self.decks.append({"name": name, "groups": groups, "env": env})
        deckstore.save_decks(self.db, self.decks, self.store_path)
        self.reload_decks()

    def show_import_dialog(self) -> None:
        dialog = DeckCodeDialog(editable=True, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.import_code(dialog.code)
        except ValueError as error:
            show_warning(self, "导入失败", str(error))

    def show_card_detail(self, cdef) -> None:
        CardDetailDialog(cdef, self.db, self).exec()
