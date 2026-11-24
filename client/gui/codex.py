"""式神录：可筛选总览、单式主页、五卡浏览与单卡详情。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from client.deckbuilder import available_shikigami, buildable_cards
from client.gui.appearance import CardAppearanceDialog
from client.gui.loading import LoadingIndicator
from client.gui.widgets import CardDetailDialog, CardWidget
from db.envs import available_env_dates, env_label, parse_env_input
from db.packs import pack_names_for

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
        self._all_card_widgets: list[CardWidget] = []
        self._card_pages: list[list[CardWidget]] = []
        self._derived_start = 0
        self.overview_card = None
        self.loading_label = QLabel(self)
        self.loading_label.setObjectName("loadingLabel")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setMinimumSize(0, 0)
        self.loading_label.hide()
        self.loading = LoadingIndicator("正在加载卡牌", self._set_loading_text, self)
        self._build_ui()
        self._render_shiki_list()

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
        filters.addWidget(QLabel("数据环境"))
        self.env_combo = QComboBox()
        self.env_combo.setEditable(True)
        self.env_combo.addItem(env_label(None), None)
        for date in available_env_dates(self.db):
            self.env_combo.addItem(env_label(date), date)
        self.env_combo.activated.connect(self.change_environment)
        self.env_combo.lineEdit().editingFinished.connect(self.change_environment)
        filters.addWidget(self.env_combo)
        self.pack_combo = QComboBox()
        self.pack_combo.addItem("全部版本包", None)
        for number, name in pack_names_for(self.db).items():
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
        browser = QHBoxLayout()
        tree_column = QVBoxLayout()
        self.shiki_list = QTreeWidget()
        self.shiki_list.setHeaderHidden(True)
        self.shiki_list.setIndentation(10)
        self.shiki_list.setAutoScroll(False)  # 首次绘制不得抢滚动、改变点击目标
        self.shiki_list.currentItemChanged.connect(self._select_shiki_item)
        tree_column.addWidget(self.shiki_list, 1)
        self.empty_label = QLabel("没有符合筛选条件的式神")
        self.empty_label.setAlignment(Qt.AlignCenter)
        tree_column.addWidget(self.empty_label)
        browser.addLayout(tree_column, 1)
        self.overview_card_container = QWidget()
        self.overview_card_layout = QVBoxLayout(self.overview_card_container)
        self.overview_card_layout.setContentsMargins(0, 0, 0, 0)
        browser.addWidget(self.overview_card_container, 2)
        overview.addLayout(browser, 1)

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
        self.card_area = QWidget()
        self.card_area.installEventFilter(self)
        home.addWidget(self.card_area, 1)
        pager = QHBoxLayout()
        self.card_primary = QPushButton("查看主要卡牌")
        self.card_previous = QPushButton("‹")
        self.card_next = QPushButton("›")
        self.card_derived = QPushButton("查看衍生卡牌")
        for button in (self.card_primary, self.card_previous, self.card_next, self.card_derived):
            button.setObjectName("small")
        for button in (self.card_previous, self.card_next):
            button.setFixedWidth(52)
        for button in (self.card_primary, self.card_derived):
            button.setFixedWidth(112)
            button.hide()
        self.card_primary.clicked.connect(lambda: self.jump_to_card_group("primary"))
        self.card_previous.clicked.connect(lambda: self.turn_card_page(-1))
        self.card_next.clicked.connect(lambda: self.turn_card_page(1))
        self.card_derived.clicked.connect(lambda: self.jump_to_card_group("derived"))
        self.card_page_label = QLabel()
        pager.addStretch(1)
        pager.addWidget(self.card_primary)
        pager.addWidget(self.card_previous)
        pager.addWidget(self.card_page_label)
        pager.addWidget(self.card_next)
        pager.addWidget(self.card_derived)
        pager.addStretch(1)
        home.addLayout(pager)

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.theme = theme
        selection_bg = "#cfe5f7" if theme == "light" else "#294c68"
        selection_text = "#17344d" if theme == "light" else colors["text"]
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QLineEdit, QComboBox, QTreeWidget {{
                background: {colors['panel']}; color: {colors['text']};
                border: 1px solid {colors['line']}; padding: 5px;
            }}
            QTreeWidget {{ outline: none; }}
            QTreeWidget::item:selected, QTreeWidget::branch:selected {{
                background: {selection_bg}; color: {selection_text}; border: none;
            }}
            QLabel#loadingLabel {{ color: {colors['gold']}; font-size: 28px; }}
        """)

    def set_database(self, db) -> None:
        """刷新导入/下载内容，并保留数据环境与当前查看位置。"""
        self.db = db
        self.edb = db.at_date(self.current_env())
        self.pool = available_shikigami(self.edb)
        if self.selected_sid not in self.edb.shikigami:
            self.selected_sid = self.pool[0].id if self.pool else None
        pack = self.pack_combo.currentData()
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        self.pack_combo.addItem("全部版本包", None)
        for number, name in pack_names_for(db).items():
            self.pack_combo.addItem(name, number)
        self.pack_combo.setCurrentIndex(max(0, self.pack_combo.findData(pack)))
        self.pack_combo.blockSignals(False)
        faction = self.faction_combo.currentText()
        self.faction_combo.blockSignals(True)
        self.faction_combo.clear()
        self.faction_combo.addItem("全部派系")
        for name in sorted({definition.faction for definition in self.pool}):
            self.faction_combo.addItem(name)
        self.faction_combo.setCurrentText(faction)
        self.faction_combo.blockSignals(False)
        self._render_shiki_list()
        if self.stack.currentWidget() is self.home_page and self.selected_sid is not None:
            self.show_shikigami_cards()

    def current_env(self) -> int | None:
        text = self.env_combo.currentText().split("(", 1)[0].strip()
        return None if text == "标准" else parse_env_input(text)

    def change_environment(self, *_args) -> None:
        try:
            env = self.current_env()
        except ValueError:
            return
        show_cards = self.stack.currentWidget() is self.home_page
        self.edb = self.db.at_date(env)
        self.pool = available_shikigami(self.edb)
        if self.selected_sid not in self.edb.shikigami:
            self.selected_sid = self.pool[0].id if self.pool else None
        self._render_shiki_list()
        if show_cards and self.selected_sid is not None:
            self.show_shikigami_cards()

    def _render_shiki_list(self, *_args) -> None:
        pack = self.pack_combo.currentData()
        faction = self.faction_combo.currentText()
        query = self.search_edit.text().strip()
        self.shiki_list.blockSignals(True)
        self.shiki_list.clear()
        groups = {}
        pack_names = pack_names_for(self.db)
        selected_item = None
        for definition in self.pool:
            pack_number = str(definition.id)[1:4]
            if pack is not None and pack_number != pack:
                continue
            if faction != "全部派系" and definition.faction != faction:
                continue
            if query and definition.name != query:
                continue
            if pack_number not in groups:
                group = QTreeWidgetItem([pack_names.get(pack_number, pack_number)])
                self.shiki_list.addTopLevelItem(group)
                groups[pack_number] = group
            item = QTreeWidgetItem([definition.name])
            item.setData(0, Qt.UserRole, definition.id)
            groups[pack_number].addChild(item)
            if definition.id == self.selected_sid:
                selected_item = item
        self.empty_label.setVisible(not groups)
        if selected_item is None and groups:
            selected_item = next(iter(groups.values())).child(0)
        self.shiki_list.expandAll()
        self.shiki_list.setCurrentItem(selected_item)
        self.shiki_list.blockSignals(False)
        if selected_item is not None:
            self.select_shikigami(selected_item.data(0, Qt.UserRole))

    def _select_shiki_item(self, current, _previous=None) -> None:
        if current is not None:
            sid = current.data(0, Qt.UserRole)
            if sid is not None:
                self.select_shikigami(sid)

    def leave_to_menu(self) -> bool:
        """返回主菜单后清除筛选与浏览位置，下次从默认总览进入。"""
        for combo in (self.env_combo, self.pack_combo, self.faction_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.edb = self.db
        self.pool = available_shikigami(self.edb)
        self.selected_sid = self.pool[0].id if self.pool else None
        self.page_index = 0
        self.stack.setCurrentWidget(self.overview_page)
        self._render_shiki_list()
        return True

    def show_overview(self) -> None:
        self.stack.setCurrentWidget(self.overview_page)

    def show_shikigami_cards(self) -> None:
        if self.selected_sid not in self.edb.shikigami:
            return
        self.stack.setCurrentWidget(self.home_page)
        self.page_index = 0
        self._render_cards()

    def select_shikigami(self, sid: int) -> None:
        if sid not in self.edb.shikigami:
            return
        self.selected_sid = sid
        definition = self.edb.shikigami[sid]
        self.name_label.setText(definition.name)
        while self.overview_card_layout.count():
            item = self.overview_card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.overview_card = CardWidget(definition, editable=False, db=self.edb)
        self.overview_card.setMinimumSize(420, 560)
        self.overview_card.count_label.hide()
        self.overview_card.clicked.connect(lambda _cdef: self.show_shikigami_cards())
        self.overview_card.detail_clicked.connect(self.show_card_appearance)
        self.overview_card_layout.addWidget(self.overview_card, 1, Qt.AlignCenter)

    def _current_card_groups(self) -> tuple[list, list]:
        if self.selected_sid not in self.edb.shikigami:
            return [], []
        sid = self.selected_sid
        primary = [self.edb.shikigami[sid]] + buildable_cards(self.edb, sid)
        derived = sorted([
            *[card for card in self.edb.cards.values()
              if card.token and not card.unreleased and card.shikigami == sid],
            *[entity for entity in self.edb.shikigami.values()
              if entity.kind != "shikigami" and not entity.unreleased
              and entity.id // 100 == sid],
        ], key=lambda definition: definition.id)
        return primary, derived

    def _current_cards(self) -> list:
        return [card for group in self._current_card_groups() for card in group]

    def _clear_cards(self) -> None:
        for widget in self._all_card_widgets:
            widget.deleteLater()
        self._all_card_widgets = []
        self._card_pages = []
        self._derived_start = 0
        self.card_widgets = []

    def _render_cards(self) -> None:
        try:
            self._clear_cards()
            primary, derived = self._current_card_groups()
            self._derived_start = (len(primary) + CARD_PAGE_SIZE - 1) // CARD_PAGE_SIZE
            self._start_loading(len(primary) + len(derived))
            art_context = {}
            for group in (primary, derived):
                group_widgets = []
                for cdef in group:
                    widget = CardWidget(
                        cdef, editable=False, db=self.edb, art_context=art_context)
                    widget.setMinimumSize(0, 0)
                    widget.count_label.hide()
                    widget.clicked.connect(self.show_card_detail)
                    widget.detail_clicked.connect(self.show_card_appearance)
                    group_widgets.append(widget)
                    self._all_card_widgets.append(widget)
                    self._loading_tick()
                for start in range(0, len(group_widgets), CARD_PAGE_SIZE):
                    self._card_pages.append(group_widgets[start:start + CARD_PAGE_SIZE])
            self.page_count = len(self._card_pages)
            self.page_index = max(0, min(self.page_index, self.page_count - 1))
            self._show_card_page()
        finally:
            self._finish_loading()

    def _show_card_page(self) -> None:
        for widget in self._all_card_widgets:
            widget.hide()
        self.card_widgets = (self._card_pages[self.page_index]
                             if self._card_pages else [])
        for widget in self.card_widgets:
            widget.setParent(self.card_area)
            widget.show()
        self._layout_card_page()
        self.card_page_label.setText(f"第 {self.page_index + 1}/{self.page_count} 页")
        self.card_previous.setEnabled(self.page_index > 0)
        self.card_next.setEnabled(self.page_index < self.page_count - 1)
        has_derived = self._derived_start < self.page_count
        self.card_primary.setVisible(has_derived)
        self.card_derived.setVisible(has_derived)
        self.card_primary.setEnabled(has_derived and self.page_index >= self._derived_start)
        self.card_derived.setEnabled(has_derived and self.page_index < self._derived_start)

    def _layout_card_page(self) -> None:
        """卡图等高，卡框中线对齐五个等距槽位；末页保持相同位置。"""
        if not self.card_widgets:
            return
        width, height = self.card_area.width(), self.card_area.height()
        if width <= 0 or height <= 0:
            return
        slot_width = width / CARD_PAGE_SIZE
        specs = []
        target_height = float(height)
        for widget in self.card_widgets:
            source = widget._display_art
            aspect = (source.width() / source.height()
                      if source is not None and source.height() else 5 / 7)
            axis = widget.frame_axis_ratio
            margins = widget.layout().contentsMargins()
            target_height = min(target_height, height - margins.top() - margins.bottom())
            horizontal_extent = max(axis, 1 - axis)
            if aspect > 0 and horizontal_extent > 0:
                side_room = slot_width / 2 - max(margins.left(), margins.right())
                target_height = min(target_height, side_room / (aspect * horizontal_extent))
            specs.append((widget, aspect, axis, margins))
        target_height = int(target_height)
        if target_height < 1:
            return
        for index, (widget, aspect, axis, margins) in enumerate(specs):
            art_width = max(1, round(target_height * aspect))
            widget_width = art_width + margins.left() + margins.right()
            widget_height = target_height + margins.top() + margins.bottom()
            axis_x = (index + 0.5) * slot_width
            x = round(axis_x - margins.left() - art_width * axis)
            y = (height - widget_height) // 2
            widget.setFixedSize(widget_width, widget_height)
            widget.move(x, y)

    def turn_card_page(self, direction: int) -> None:
        page = max(0, min(self.page_index + direction, self.page_count - 1))
        if page != self.page_index:
            self.page_index = page
            self._show_card_page()

    def jump_to_card_group(self, group: str) -> None:
        target = 0 if group == "primary" else self._derived_start
        if 0 <= target < self.page_count:
            self.page_index = target
            self._show_card_page()

    def show_card_appearance(self, cdef) -> None:
        if CardAppearanceDialog(cdef, self.edb, self).exec():
            self.select_shikigami(self.selected_sid)
            if self.stack.currentWidget() is self.home_page:
                self._render_cards()

    def show_card_detail(self, cdef) -> None:
        CardDetailDialog(cdef, self.edb, self).exec()

    def _set_loading_text(self, text: str) -> None:
        self.loading_label.setText(text)
        self.loading_label.setGeometry(self.card_area.geometry())

    def _start_loading(self, total: int) -> None:
        self._loading_done = 0
        self._loading_total = total
        self._set_loading_text("正在加载卡牌 0.0s")
        self.loading_label.show()
        self.loading_label.raise_()
        self.loading.start(total=total)

    def _loading_tick(self) -> None:
        self._loading_done += 1
        self.loading.set_progress(self._loading_done, self._loading_total)
        self.loading.tick()

    def _finish_loading(self) -> None:
        self.loading.stop()
        self.loading_label.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.card_area and event.type() == QEvent.Resize:
            self._layout_card_page()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_card_page()
        if self.loading_label.isVisible():
            self._set_loading_text(self.loading_label.text())
