"""桌面 GUI 共用卡牌控件与详情弹窗。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
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


def show_information(parent, title: str, text: str) -> int:
    return show_message(parent, title, text, QMessageBox.Information)


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

    def __init__(self, cdef, copies: int = 0, editable: bool = False, parent=None, db=None,
                 display=None, level_color=None, art_context: dict | None = None,
                 art_height: int | None = None):
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
        self.text_label = QLabel(cdef.text or "（无效果文本）")
        self.text_label.setObjectName("cardText")
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.text_label, 1)
        self._art_db = db
        self._art_height = art_height
        self._art_options = {"display": display, "level_color": level_color}
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

    def set_copies(self, copies: int) -> None:
        self.copies = copies
        self.count_label.setText(f"已选 {copies}/2")
        self.setProperty("selected", copies > 0)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.cdef)
        super().mouseReleaseEvent(event)


class CardChoiceView(QScrollArea):
    """横向候选列表：卡牌显示卡图，其他值保留文字按钮。"""

    chosen = Signal(object)

    def __init__(self, options, db=None, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        row = QHBoxLayout(content)
        self.option_widgets = []
        for value, cdef, label in options:
            if cdef is None:
                widget = QPushButton(label)
                widget.setMinimumSize(180, 60)
            else:
                widget = CardWidget(cdef, db=db)
                widget.count_label.hide()
                widget.setFixedSize(180, 390)
            widget.clicked.connect(lambda _=None, option=value: self.chosen.emit(option))
            self.option_widgets.append(widget)
            row.addWidget(widget)
        row.addStretch(1)
        self.setWidget(content)


class CardDetailDialog(QDialog):
    """左侧大卡图、右侧独立滚动机制栏的单卡详情。"""

    def __init__(self, cdef, db=None, parent=None, runtime: dict | None = None,
                 level_color=None):
        super().__init__(parent)
        self.setWindowTitle(cdef.name)
        self.setMinimumSize(480, 600)
        layout = QVBoxLayout(self)
        self.detail_top = QHBoxLayout()
        self.card_widget = CardWidget(cdef, db=db, display=(runtime or {}).get("render"),
                                      level_color=level_color, art_height=512)
        self.card_widget.count_label.hide()
        art_width = (self.card_widget._display_art.width()
                     if self.card_widget._display_art is not None else 396)
        self.card_widget.setFixedWidth(art_width + 24)
        self.card_widget.setMinimumHeight(560)
        self.detail_top.addWidget(self.card_widget, 0, Qt.AlignLeft | Qt.AlignTop)
        self.mechanism_panel, self.mechanism_labels = mechanism_panel(
            card_mechanisms(cdef, runtime), self, chars_per_line=12, font_scale=1.0,
            width=art_width)
        if self.mechanism_panel is not None:
            self.detail_top.addWidget(self.mechanism_panel, 1)
            self.setMinimumWidth(900)
        else:
            self.detail_top.addStretch(1)
        layout.addLayout(self.detail_top, 1)
        if runtime is not None:
            current = ["当前状态"]
            if "cost" in runtime:
                current.append(f"费用 {runtime['cost']}")
            if runtime.get("stats"):
                current.append(f"数值 {runtime['stats']}")
            if "enhance" in runtime:
                current.append(f"增强 {runtime['enhance']}")
            if runtime.get("keywords"):
                current.append(f"关键字 {'、'.join(runtime['keywords'])}")
            if runtime.get("quest"):
                quest = str(runtime["quest"])
                current.append(quest if quest.startswith("委托") else f"委托 {quest}")
            if "playable" in runtime:
                current.append(f"条件：{'满足' if runtime['playable'] else '不满足'}")
            for option in runtime.get("usage", []):
                usage = f"使用方式 {option.get('label', option.get('id', ''))}"
                if option.get("ok"):
                    current.append(f"{usage}：可用")
                else:
                    reason = option.get("reason") or "不可用"
                    current.append(f"{usage}：{reason}")
            self.runtime_label = QLabel("\n".join(current))
            self.runtime_label.setObjectName("cardRuntime")
            self.runtime_label.setWordWrap(True)
            layout.addWidget(self.runtime_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        self._sync_mechanism_height()

    def _sync_mechanism_height(self) -> None:
        if self.mechanism_panel is not None:
            self.mechanism_panel.setMaximumHeight(
                max(160, round(self.card_widget.height() * 1.1)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_mechanism_height()
