"""桌面 GUI 共用卡牌控件与详情弹窗。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

from client import cardfmt


class CardWidget(QFrame):
    """文字卡面：构筑与后续式神录、对局详情共用。"""

    clicked = Signal(object)

    def __init__(self, cdef, copies: int = 0, editable: bool = False, parent=None):
        super().__init__(parent)
        self.cdef = cdef
        self.copies = copies
        self.setObjectName("card")
        self.setMinimumSize(190, 330)
        self.setMaximumWidth(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        self.level_label = QLabel(f"等级 {cdef.level}")
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
        footer = QHBoxLayout()
        self.count_label = QLabel(f"已选 {copies}/2")
        self.count_label.setObjectName("cardCount")
        footer.addWidget(self.count_label)
        if editable:
            self.minus_button = QPushButton("−")
            self.plus_button = QPushButton("＋")
            for button in (self.minus_button, self.plus_button):
                button.setObjectName("cardStep")
                button.setFixedSize(32, 30)
                footer.addWidget(button)
        else:
            self.minus_button = self.plus_button = None
        layout.addLayout(footer)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)

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


class CardDetailDialog(QDialog):
    """完整单卡详情：名称、类型、等级、身材、子类型与效果文本。"""

    def __init__(self, cdef, db=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(cdef.name)
        self.setMinimumSize(480, 600)
        layout = QVBoxLayout(self)
        card = CardWidget(cdef)
        card.setMaximumWidth(420)
        layout.addWidget(card, 1, Qt.AlignCenter)
        details = []
        if cdef.subtype:
            details.append(f"子类型：{cdef.subtype}")
        if db is not None and cdef.shikigami in db.shikigami:
            details.append(f"所属式神：{db.shikigami[cdef.shikigami].name}")
        if details:
            label = QLabel("　".join(details))
            label.setObjectName("cardMeta")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
