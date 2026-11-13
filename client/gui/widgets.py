"""桌面 GUI 共用卡牌控件与详情弹窗。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from client import cardfmt
from client.gui.cardart import card_pixmap
from client.gui.mechanisms import card_mechanisms, mechanism_panel


_DIALOG_BUTTON_TEXT = {
    "Ok": "确定", "Cancel": "取消", "Close": "关闭", "Yes": "是", "No": "否",
    "Apply": "应用", "Open": "打开", "Save": "保存", "Discard": "不保存",
    "Reset": "重置", "Retry": "重试", "Ignore": "忽略", "Help": "帮助",
}


def polish_dialog_buttons(owner) -> None:
    """统一标准按钮中文与紧凑样式；也适用于输入框和 QMessageBox。"""
    targets = [owner] if isinstance(owner, (QDialogButtonBox, QMessageBox)) \
        else owner.findChildren(QDialogButtonBox)
    for target in targets:
        for name, text in _DIALOG_BUTTON_TEXT.items():
            enum_type = QDialogButtonBox if isinstance(target, QDialogButtonBox) else QMessageBox
            button = target.button(getattr(enum_type, name))
            if button is not None:
                button.setText(text)
        for button in target.buttons():
            button.setObjectName("dialogButton")
            button.setStyleSheet(
                "QPushButton { padding: 4px 12px; font-size: 14px; text-align: center; }")
            button.style().unpolish(button)
            button.style().polish(button)
            width = max(76, button.fontMetrics().horizontalAdvance(button.text()) + 26)
            button.setFixedSize(width, 30)


def show_message(parent, title: str, text: str, icon=QMessageBox.Information,
                 buttons=QMessageBox.Ok) -> int:
    """静态 QMessageBox 的中文按钮替代入口。"""
    box = QMessageBox(icon, title, text, buttons, parent)
    polish_dialog_buttons(box)
    return box.exec()


def show_warning(parent, title: str, text: str) -> int:
    return show_message(parent, title, text, QMessageBox.Warning)


def ask_confirmation(parent, title: str, text: str) -> int:
    return show_message(parent, title, text, QMessageBox.Question,
                        QMessageBox.Yes | QMessageBox.No)


def fill_card_row(layout, widgets: list["CardWidget"], page_size: int = 5) -> None:
    """按固定列数等宽排卡；不足页用空列保持相同列宽并左对齐。"""
    for widget in widgets:
        layout.addWidget(widget, 1)
    for _ in range(page_size - len(widgets)):
        layout.addWidget(QWidget(), 1)


class CardWidget(QFrame):
    """静态卡面：有本地卡图时显示全卡，否则回退文字卡。"""

    clicked = Signal(object)
    detail_clicked = Signal(object)

    def __init__(self, cdef, copies: int = 0, editable: bool = False, parent=None, db=None,
                 display=None, level_color=None, art_context: dict | None = None,
                 art_height: int | None = None, frame_variant: str | None = None,
                 description_suffix: str | None = None):
        super().__init__(parent)
        self.cdef = cdef
        self.copies = copies
        self.setObjectName("card")
        self.setMinimumSize(0, 330)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        self.art_label = QLabel()
        self.art_label.setObjectName("cardArt")
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.art_label.installEventFilter(self)
        layout.addWidget(self.art_label, 1)
        level = getattr(cdef, "level", None)
        self.level_label = QLabel(f"等级 {level}" if level is not None else " ")
        self.level_label.setObjectName("cardLevel")
        layout.addWidget(self.level_label)
        self.name_label = QLabel(cdef.name)
        self.name_label.setObjectName("cardName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        type_text = cardfmt.ctype_label(cdef)
        self.type_label = QLabel(type_text)
        self.type_label.setObjectName("cardMeta")
        self.type_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.type_label)
        stats = cardfmt.static_stats(cdef)
        self.stats_label = QLabel(stats or " ")
        self.stats_label.setObjectName("cardStats")
        self.stats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stats_label)
        text = (cdef.text or "（无效果文本）") + (description_suffix or "")
        self.text_label = QLabel(text)
        self.text_label.setObjectName("cardText")
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.text_label, 1)
        self._art_db = db
        self._art_height = art_height
        self._art_options = {"display": display, "level_color": level_color}
        if description_suffix is not None:
            self._art_options["description_suffix"] = description_suffix
        if frame_variant is not None:
            self._art_options["frame_variant"] = frame_variant
        if art_context is not None:
            self._art_options["cache_context"] = art_context
        pixmap = self._request_art()
        if pixmap is not None and not pixmap.isNull():
            self._display_art = pixmap
            self.art_label.setPixmap(self._display_art)
            for label in (self.level_label, self.name_label, self.type_label,
                          self.stats_label, self.text_label):
                label.hide()
        else:
            self._display_art = None
            self.art_label.hide()
        footer = QHBoxLayout()
        self.count_label = QLabel(f"已选 {copies}/2")
        self.count_label.setObjectName("cardCount")
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setFixedHeight(30)
        footer.addStretch(1)
        if editable:
            self.minus_button = QPushButton("−")
            self.plus_button = QPushButton("＋")
            for button in (self.minus_button, self.plus_button):
                button.setObjectName("cardStep")
                button.setFixedSize(32, 30)
            footer.addWidget(self.minus_button)
            footer.addStretch(1)
            footer.addWidget(self.count_label)
            footer.addStretch(1)
            footer.addWidget(self.plus_button)
        else:
            self.minus_button = self.plus_button = None
            footer.addWidget(self.count_label)
        footer.addStretch(1)
        layout.addLayout(footer)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)

    @property
    def art_width(self) -> int | None:
        return self._display_art.width() if self._display_art is not None else None

    def _request_art(self):
        if self._art_db is None:
            return None
        return card_pixmap(self.cdef, self._art_db, height=self._art_height,
                           **self._art_options)

    def _fit_art(self) -> None:
        source = self._display_art
        if source is None or self.art_label.width() <= 0 or self.art_label.height() <= 0:
            return
        self.art_label.setPixmap(source.scaled(
            self.art_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.art_label and event.type() == QEvent.Resize:
            self._fit_art()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_art()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.cdef)
        elif event.button() == Qt.RightButton:
            self.detail_clicked.emit(self.cdef)
        super().mouseReleaseEvent(event)


class CardChoiceView(QScrollArea):
    """调度式候选列表：选中卡片后，再点其下方“选择”按钮确认。"""

    chosen = Signal(object)
    detail_clicked = Signal(object)

    def __init__(self, options, db=None, parent=None, *,
                 frame_variant: str | None = None, button_text: str = "选择"):
        super().__init__(parent)
        self._syncing_height = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("choiceContent")
        row = QHBoxLayout(content)
        row.setContentsMargins(12, 4, 12, 8)
        self.option_widgets = []
        self.option_buttons = {}
        self._wrappers = {}
        self._values = {}
        self.selected = None
        for value, cdef, label in options:
            if cdef is None:
                card = QPushButton(label)
                card.setMinimumSize(180, 60)
            else:
                card = CardWidget(cdef, db=db, frame_variant=frame_variant)
                card.count_label.hide()
                card.setFixedSize(180, 390)
                card.setFrameShape(QFrame.NoFrame)
                card.setStyleSheet("background: transparent; border: none;")
                card.detail_clicked.connect(self.detail_clicked.emit)
            button = QPushButton(button_text)
            button.setObjectName("battleSmall")
            button.setFixedSize(96, 28)
            button.hide()
            wrapper = QWidget()
            wrapper.setObjectName("choiceContent")
            wrapper.setMinimumWidth(194)
            column = QVBoxLayout(wrapper)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addWidget(card, 0, Qt.AlignCenter)
            column.addWidget(button, alignment=Qt.AlignCenter)
            card.clicked.connect(lambda _=None, option=value: self.select(option))
            button.clicked.connect(lambda _checked=False, option=value: self.confirm(option))
            self.option_widgets.append(card)
            self.option_buttons[value] = button
            self._wrappers[value] = wrapper
            self._values[card] = value
            row.addWidget(wrapper)
        row.addStretch(1)
        self.setWidget(content)
        self._sync_minimum_height()

    def _sync_minimum_height(self) -> None:
        if self._syncing_height or self.widget() is None:
            return
        content_height = 0
        for index, wrapper in enumerate(self._wrappers.values()):
            column = wrapper.layout()
            margins = column.contentsMargins()
            button = self.option_buttons[list(self._wrappers)[index]]
            button_height = 0 if button.isHidden() else button.height() + column.spacing()
            content_height = max(
                content_height,
                self.option_widgets[index].height() + button_height
                + margins.top() + margins.bottom(),
            )
        margins = self.widget().layout().contentsMargins()
        height = content_height + margins.top() + margins.bottom() + 2 * self.frameWidth()
        scrollbar = self.horizontalScrollBar()
        if not scrollbar.isHidden():
            height += scrollbar.sizeHint().height()
        self._syncing_height = True
        self.setMinimumHeight(max(475, height))
        self._syncing_height = False
        self.updateGeometry()
        self.window().updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_minimum_height()

    def select(self, value) -> None:
        if self.selected == value:
            self.confirm(value)
            return
        self.selected = value
        for option, wrapper in self._wrappers.items():
            selected = option == value
            if selected:
                wrapper.setGraphicsEffect(None)
            elif option is not None:
                dim = QGraphicsOpacityEffect(wrapper)
                dim.setOpacity(0.45)
                wrapper.setGraphicsEffect(dim)
            card = self.option_widgets[list(self._wrappers).index(option)]
            if isinstance(card, CardWidget):
                card.setFixedSize(194 if selected else 180, 421 if selected else 390)
            self.option_buttons[option].setVisible(selected)
        self._sync_minimum_height()

    def confirm(self, value=None) -> None:
        value = self.selected if value is None else value
        if value is not None and value == self.selected:
            self.chosen.emit(value)


DETAIL_COLUMN_SPACING = 12


class CardDetailDialog(QDialog):
    """左侧大卡图、右侧独立滚动机制栏的单卡详情。"""

    def __init__(self, cdef, db=None, parent=None, runtime: dict | None = None,
                 level_color=None):
        super().__init__(parent)
        self.setWindowTitle(cdef.name)
        self.setMinimumSize(480, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.detail_top = QHBoxLayout()
        self.detail_top.setSpacing(DETAIL_COLUMN_SPACING)
        self.card_widget = CardWidget(
            cdef, db=db, display=(runtime or {}).get("render"),
            level_color=level_color, art_height=512,
            description_suffix=(runtime or {}).get("description_suffix"))
        self.card_widget.count_label.hide()
        art_width = self.card_widget.art_width or 396
        panel_width = art_width + 24
        self.card_widget.setFixedWidth(panel_width)
        self.card_widget.setMinimumHeight(560)
        self.detail_top.addWidget(self.card_widget, 0, Qt.AlignLeft | Qt.AlignTop)
        self.mechanism_panel, self.mechanism_labels = mechanism_panel(
            card_mechanisms(cdef, runtime), self, chars_per_line=12, font_scale=1.0,
            max_height=512, width=panel_width)
        if self.mechanism_panel is not None:
            self.detail_top.addWidget(
                self.mechanism_panel, 0, Qt.AlignLeft | Qt.AlignTop)
        self.detail_top.addStretch(1)
        layout.addLayout(self.detail_top, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        self._sync_mechanism_height()

    def _sync_mechanism_height(self) -> None:
        if self.mechanism_panel is not None:
            self.mechanism_panel.setMaximumHeight(
                min(512, max(160, round(self.card_widget.height() * 1.1))))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_mechanism_height()
