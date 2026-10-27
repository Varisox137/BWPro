"""式神录：可筛选总览、单式主页、五卡浏览与单卡详情。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from client.deckbuilder import available_shikigami, buildable_cards
from client.gui.cardart import card_pixmap
from client.gui.loading import LoadingIndicator
from client.gui.widgets import CardDetailDialog, CardWidget
from db.envs import ENV_ALIASES, env_label, parse_env_input
from db.packs import PACK_NAMES, PACKS

CARD_PAGE_SIZE = 5


class ShikigamiCodexView(QWidget):
    """不包含收藏统计的式神与卡牌浏览器。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.edb = db
        self.theme = "light"
        self.pool = available_shikigami(self.edb)
        self.selected_sid = self.pool[0].id if self.pool else None
        self.page_index = 0
        self.page_count = 0
        self.card_widgets: list[CardWidget] = []
        self.loading_label = QLabel(self)
        self.loading_label.setObjectName("loadingLabel")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setFixedSize(400, 80)
        self.loading_label.hide()
        self.loading = LoadingIndicator("正在加载卡牌", self._set_loading_text, self)
        self._build_ui()
        self._render_shiki_list()
        if self.selected_sid is not None:
            self.select_shikigami(self.selected_sid)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)
        self.overview_page = QWidget()
        self.home_page = QWidget()
        self.stack.addWidget(self.overview_page)
        self.stack.addWidget(self.home_page)

        overview = QVBoxLayout(self.overview_page)
        overview.setContentsMargins(12, 12, 12, 12)
        title = QLabel("式神录")
        title.setObjectName("viewTitle")
        overview.addWidget(title)
        filters = QHBoxLayout()
        self.env_combo = QComboBox()
        self.env_combo.setEditable(True)
        self.env_combo.addItem(env_label(None), None)
        for date in dict.fromkeys(ENV_ALIASES.values()):
            self.env_combo.addItem(env_label(date), date)
        self.env_combo.activated.connect(self.change_environment)
        self.env_combo.lineEdit().editingFinished.connect(self.change_environment)
        filters.addWidget(self.env_combo)
        self.pack_combo = QComboBox()
        self.pack_combo.addItem("全部版本包", None)
        for number, name in PACKS.items():
            self.pack_combo.addItem(name, number)
        self.pack_combo.currentIndexChanged.connect(self._render_shiki_list)
        filters.addWidget(self.pack_combo)
        self.faction_combo = QComboBox()
        self.faction_combo.addItem("全部派系")
        for faction in sorted({definition.faction for definition in self.pool}):
            self.faction_combo.addItem(faction)
        self.faction_combo.currentTextChanged.connect(self._render_shiki_list)
        filters.addWidget(self.faction_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索式神全名")
        self.search_edit.textChanged.connect(self._render_shiki_list)
        filters.addWidget(self.search_edit, 1)
        overview.addLayout(filters)
        self.shiki_list = QListWidget()
        self.shiki_list.currentRowChanged.connect(self._select_shiki_row)
        overview.addWidget(self.shiki_list, 1)
        self.empty_label = QLabel("没有符合筛选条件的式神")
        self.empty_label.setAlignment(Qt.AlignCenter)
        overview.addWidget(self.empty_label)

        home = QVBoxLayout(self.home_page)
        home.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        self.back_button = QPushButton("← 式神总览")
        self.back_button.setObjectName("small")
        self.back_button.clicked.connect(self.show_overview)
        top.addWidget(self.back_button)
        self.name_label = QLabel()
        self.name_label.setObjectName("viewTitle")
        top.addWidget(self.name_label, 1)
        home.addLayout(top)
        self.home_body = QHBoxLayout()
        self.portrait_label = QLabel()
        self.portrait_label.setAlignment(Qt.AlignCenter)
        self.home_body.addWidget(self.portrait_label)
        info = QVBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setObjectName("shikiStats")
        info.addWidget(self.stats_label)
        self.ability_label = QLabel()
        self.ability_label.setObjectName("shikiAbility")
        self.ability_label.setWordWrap(True)
        info.addWidget(self.ability_label, 1)
        self.home_body.addLayout(info, 1)
        home.addLayout(self.home_body, 1)
        self.card_area = QWidget()
        self.card_layout = QHBoxLayout(self.card_area)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(4)
        home.addWidget(self.card_area)
        pager = QHBoxLayout()
        self.card_previous = QPushButton("‹")
        self.card_next = QPushButton("›")
        for button in (self.card_previous, self.card_next):
            button.setObjectName("small")
            button.setFixedWidth(52)
        self.card_previous.clicked.connect(lambda: self.turn_card_page(-1))
        self.card_next.clicked.connect(lambda: self.turn_card_page(1))
        self.card_page_label = QLabel()
        pager.addStretch(1)
        pager.addWidget(self.card_previous)
        pager.addWidget(self.card_page_label)
        pager.addWidget(self.card_next)
        pager.addStretch(1)
        home.addLayout(pager)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QLabel#shikiStats {{ color: {colors['blue']}; font-size: 18px; }}
            QLabel#shikiAbility {{ color: {colors['text']}; font-size: 16px; }}
            QLineEdit, QComboBox, QListWidget {{
                background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['line']}; padding: 5px;
            }}
            QListWidget::item:selected {{ background: {colors['gold2']}; color: {colors['text']}; }}
            QLabel#loadingLabel {{ color: {colors['gold']}; font-size: 28px; }}
        """)

    def current_env(self) -> int | None:
        text = self.env_combo.currentText().split("(", 1)[0].strip()
        return None if text == "标准" else parse_env_input(text)

    def change_environment(self, *_args) -> None:
        try:
            env = self.current_env()
        except ValueError:
            return
        self.edb = self.db.at_date(env)
        self.pool = available_shikigami(self.edb)
        if self.selected_sid not in self.edb.shikigami:
            self.selected_sid = self.pool[0].id if self.pool else None
        self._render_shiki_list()
        if self.selected_sid is not None:
            self.select_shikigami(self.selected_sid)

    def _render_shiki_list(self, *_args) -> None:
        pack = self.pack_combo.currentData()
        faction = self.faction_combo.currentText()
        query = self.search_edit.text().strip()
        self.shiki_list.blockSignals(True)
        self.shiki_list.clear()
        shown = []
        for definition in self.pool:
            if pack is not None and str(definition.id)[2:4] != pack:
                continue
            if faction != "全部派系" and definition.faction != faction:
                continue
            if query and definition.name != query:
                continue
            shown.append(definition)
            item = QListWidgetItem(definition.name, self.shiki_list)
            item.setData(Qt.UserRole, definition.id)
        self.empty_label.setVisible(not shown)
        if shown:
            row = next((index for index, definition in enumerate(shown)
                        if definition.id == self.selected_sid), 0)
            self.shiki_list.setCurrentRow(row)
        self.shiki_list.blockSignals(False)

    def _select_shiki_row(self, row: int) -> None:
        item = self.shiki_list.item(row)
        if item is not None:
            self.select_shikigami(item.data(Qt.UserRole))

    def show_overview(self) -> None:
        self.stack.setCurrentWidget(self.overview_page)

    def select_shikigami(self, sid: int) -> None:
        if sid not in self.edb.shikigami:
            return
        self.selected_sid = sid
        definition = self.edb.shikigami[sid]
        self.stack.setCurrentWidget(self.home_page)
        self.name_label.setText(definition.name)
        self.stats_label.setText(
            f"{definition.faction}　力量 {definition.power}　生命 {definition.health}")
        self.ability_label.setText(definition.text or "（无基础能力文本）")
        pixmap = card_pixmap(definition, self.db, height=336)
        if pixmap is not None and not pixmap.isNull():
            self.portrait_label.setPixmap(pixmap)
            self.portrait_label.setFixedSize(pixmap.size())
        else:
            self.portrait_label.setText(f"{definition.name}\n{definition.faction}")
        self.page_index = 0
        self._render_cards()

    def _current_cards(self) -> list:
        if self.selected_sid is None:
            return []
        return [self.edb.shikigami[self.selected_sid]] + buildable_cards(
            self.edb, self.selected_sid)

    def _clear_cards(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_cards(self) -> None:
        self._start_loading()
        try:
            self._clear_cards()
            self.card_widgets = []
            cards = self._current_cards()
            self.page_count = max(1, (len(cards) + CARD_PAGE_SIZE - 1) // CARD_PAGE_SIZE)
            self.page_index = max(0, min(self.page_index, self.page_count - 1))
            shown = cards[self.page_index * CARD_PAGE_SIZE:
                          (self.page_index + 1) * CARD_PAGE_SIZE]
            art_context = {}
            for cdef in shown:
                widget = CardWidget(cdef, editable=False, db=self.db, art_context=art_context)
                widget.count_label.hide()
                widget.clicked.connect(self.show_card_detail)
                self.card_layout.addWidget(widget, 1)
                self.card_widgets.append(widget)
                self._loading_tick()
            self.card_layout.addStretch(1)
            self.card_page_label.setText(f"第 {self.page_index + 1}/{self.page_count} 页")
            self.card_previous.setEnabled(self.page_index > 0)
            self.card_next.setEnabled(self.page_index < self.page_count - 1)
        finally:
            self._finish_loading()

    def turn_card_page(self, direction: int) -> None:
        page = max(0, min(self.page_index + direction, self.page_count - 1))
        if page != self.page_index:
            self.page_index = page
            self._render_cards()

    def show_card_detail(self, cdef) -> None:
        CardDetailDialog(cdef, self.db, self).exec()

    def _set_loading_text(self, text: str) -> None:
        self.loading_label.setText(text)
        self.loading_label.setGeometry(0, 0, self.width(), self.height())

    def _start_loading(self) -> None:
        self._set_loading_text("正在加载卡牌 0.0s")
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
