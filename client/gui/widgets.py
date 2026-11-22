"""桌面 GUI 共用卡牌控件与详情弹窗。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from client import cardfmt
from client.gui.card_options import CardOption
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
        widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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
                 description_suffix: str | None = None, burst: int | None = None,
                 art_options: dict | None = None):
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
        suffix = (description_suffix if description_suffix is not None
                  else (art_options or {}).get("description_suffix"))
        text = (cdef.text or "（无效果文本）") + (suffix or "")
        self.text_label = QLabel(text)
        self.text_label.setObjectName("cardText")
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.text_label, 1)
        self._art_db = db
        self._art_height = art_height
        self._art_options = dict(art_options or {})
        if display is not None:
            self._art_options["display"] = display
        if level_color is not None:
            self._art_options["level_color"] = level_color
        if burst is not None:
            self._art_options["burst"] = burst
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


_NO_SELECTION = object()


class CardChoiceView(QScrollArea):
    """统一消费 CardOption；旧 (answer, cdef, label) 三元组仍可直接传入。"""

    chosen = Signal(object)
    detail_clicked = Signal(object)

    def __init__(self, options, db=None, parent=None, *,
                 frame_variant: str | None = None, frame_variants: dict | None = None,
                 button_text: str = "选择"):
        super().__init__(parent)
        self._syncing_height = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("choiceContent")
        row = QHBoxLayout(content)
        row.setContentsMargins(12, 4, 12, 8)
        self.options: list[CardOption] = []
        self.option_widgets = []
        self.option_buttons = {}
        self.reason_labels = {}
        self._wrappers = {}
        self._option_by_answer = {}
        self.selected = _NO_SELECTION
        for raw in options:
            if isinstance(raw, CardOption):
                option = raw
            else:
                value, cdef, label = raw
                option = CardOption(value, cdef, label=label)
            variant = (frame_variants or {}).get(option.answer, frame_variant)
            if variant is not None:
                option.art_options.setdefault("frame_variant", variant)
            self.options.append(option)
            self._option_by_answer[option.answer] = option
            if option.cdef is None:
                card = QPushButton(option.label if option.label is not None else str(option.answer))
                card.setMinimumSize(180, 60)
                card.setEnabled(option.enabled)
            else:
                card = CardWidget(option.cdef, db=db, art_options=option.art_options)
                card.count_label.hide()
                card.setFixedSize(180, 390)
                card.setFrameShape(QFrame.NoFrame)
                card.setStyleSheet("background: transparent; border: none;")
                card.detail_clicked.connect(
                    lambda _cdef, selected=option: self.detail_clicked.emit(selected))
            if option.reason:
                card.setToolTip(option.reason)
            button = QPushButton(button_text)
            button.setObjectName("dialogButton")
            button.setFixedSize(96, 28)
            button.hide()
            reason = QLabel("" if option.enabled else f"不可用：{option.reason or '当前不可用'}")
            reason.setObjectName("choiceReason")
            reason.setWordWrap(True)
            reason.setFixedWidth(180)
            reason.setVisible(not option.enabled)
            wrapper = QWidget()
            wrapper.setObjectName("choiceContent")
            wrapper.setMinimumWidth(194)
            column = QVBoxLayout(wrapper)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addWidget(card, 0, Qt.AlignCenter)
            column.addWidget(button, alignment=Qt.AlignCenter)
            column.addWidget(reason, alignment=Qt.AlignCenter)
            if not option.enabled:
                dim = QGraphicsOpacityEffect(wrapper)
                dim.setOpacity(0.45)
                wrapper.setGraphicsEffect(dim)
            card.clicked.connect(lambda _=None, value=option.answer: self.select(value))
            button.clicked.connect(lambda _checked=False, value=option.answer: self.confirm(value))
            self.option_widgets.append(card)
            self.option_buttons[option.answer] = button
            self.reason_labels[option.answer] = reason
            self._wrappers[option.answer] = wrapper
            row.addWidget(wrapper)
        row.addStretch(1)
        self.setWidget(content)
        self._sync_minimum_height()

    def _sync_minimum_height(self) -> None:
        if self._syncing_height or self.widget() is None:
            return
        content_height = 0
        for index, option in enumerate(self.options):
            wrapper = self._wrappers[option.answer]
            column = wrapper.layout()
            margins = column.contentsMargins()
            button = self.option_buttons[option.answer]
            reason = self.reason_labels[option.answer]
            button_height = 0 if button.isHidden() else button.height() + column.spacing()
            reason_height = 0 if reason.isHidden() else reason.sizeHint().height() + column.spacing()
            content_height = max(
                content_height,
                self.option_widgets[index].height() + button_height + reason_height
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
        option = self._option_by_answer.get(value)
        if option is None or not option.enabled:
            return
        if self.selected is not _NO_SELECTION and self.selected == value:
            self.confirm(value)
            return
        self.selected = value
        for current in self.options:
            answer = current.answer
            wrapper = self._wrappers[answer]
            selected = answer == value
            if selected:
                wrapper.setGraphicsEffect(None)
            else:
                dim = QGraphicsOpacityEffect(wrapper)
                dim.setOpacity(0.45)
                wrapper.setGraphicsEffect(dim)
            card = self.option_widgets[self.options.index(current)]
            if isinstance(card, CardWidget):
                card.setFixedSize(194 if selected else 180, 421 if selected else 390)
            self.option_buttons[answer].setVisible(selected)
        self._sync_minimum_height()

    def confirm(self, value=_NO_SELECTION) -> None:
        value = self.selected if value is _NO_SELECTION else value
        if self.selected is _NO_SELECTION or value != self.selected:
            return
        option = self._option_by_answer.get(value)
        if option is not None and option.enabled:
            self.chosen.emit(value)


DETAIL_COLUMN_SPACING = 12


class CardDetailDialog(QDialog):
    """左侧大卡图、右侧独立滚动机制栏的单卡详情。"""

    def __init__(self, cdef, db=None, parent=None, runtime: dict | None = None,
                 level_color=None, art_options: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(cdef.name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.detail_top = QHBoxLayout()
        self.detail_top.setSpacing(DETAIL_COLUMN_SPACING)
        detail_art_options = dict(art_options or {})
        if runtime is not None and runtime.get("render") is not None:
            detail_art_options["display"] = runtime["render"]
        if runtime is not None and runtime.get("description_suffix") is not None:
            detail_art_options["description_suffix"] = runtime["description_suffix"]
        if level_color is not None:
            detail_art_options["level_color"] = level_color
        self.card_widget = CardWidget(
            cdef, db=db, art_height=512, art_options=detail_art_options)
        self.card_widget.count_label.hide()
        art_width = self.card_widget.art_width or 396
        panel_width = art_width + 24
        self.card_widget.setFixedWidth(panel_width)
        self.card_widget.setMinimumHeight(560)
        self.detail_top.addWidget(self.card_widget)
        self.mechanism_panel, self.mechanism_labels = mechanism_panel(
            card_mechanisms(cdef, runtime), self, chars_per_line=12, font_scale=1.0,
            max_height=512, width=panel_width)
        if self.mechanism_panel is not None:
            self.mechanism_panel.setMinimumHeight(self.card_widget.minimumHeight())
            self.mechanism_panel.setMaximumHeight(16777215)
            self.detail_top.addWidget(self.mechanism_panel)
        self.detail_top.addStretch(1)
        layout.addLayout(self.detail_top, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
