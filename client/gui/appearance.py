"""式神录卡牌外观：四牌框预览，异画选择预留。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton,
    QStyle, QVBoxLayout,
)

from client.gui.card_appearance import (
    FRAME_VARIANTS, card_appearance, save_card_appearance,
)
from client.gui.widgets import CardChoiceView, polish_dialog_buttons, show_warning


class CardAppearanceDialog(QDialog):
    """顶部切牌框，点击原画放大后再确认；确认前不写本机配置。"""

    def __init__(self, cdef, db, parent=None):
        super().__init__(parent)
        self.cdef = cdef
        self.db = db
        self.selected_frame = card_appearance(cdef.id)["frame_variant"]
        self.setWindowTitle(f"{cdef.name} · 更换牌框")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        frame_row = QHBoxLayout()
        self.frame_buttons = {}
        self.frame_group = QButtonGroup(self)
        self.frame_group.setExclusive(True)
        for variant, label in FRAME_VARIANTS.items():
            button = QPushButton(label)
            button.setObjectName("small")
            button.setCheckable(True)
            button.setFixedSize(76, 30)
            button.clicked.connect(
                lambda _checked=False, selected=variant: self.select_frame(selected))
            self.frame_group.addButton(button)
            self.frame_buttons[variant] = button
            frame_row.addWidget(button)
        layout.addLayout(frame_row)
        self.choice_slot = QVBoxLayout()
        layout.addLayout(self.choice_slot)
        self.choice_view = None
        self.select_frame(self.selected_frame)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        self._fit_dialog()

    def select_frame(self, variant: str) -> None:
        if variant not in FRAME_VARIANTS:
            return
        selected = self.choice_view.selected if self.choice_view is not None else None
        self.selected_frame = variant
        self.frame_buttons[variant].setChecked(True)
        if self.choice_view is not None:
            self.choice_slot.removeWidget(self.choice_view)
            self.choice_view.deleteLater()
        self.choice_view = CardChoiceView(
            [(0, self.cdef, "原画")], db=self.db,
            frame_variant=variant, button_text="确认")
        self.choice_view.setMinimumSize(218, 475)
        self.choice_view.chosen.connect(self._save)
        self.choice_slot.addWidget(self.choice_view)
        if selected is not None:
            self.choice_view.select(selected)
        self._fit_dialog()

    def _save(self, _value) -> None:
        try:
            save_card_appearance(self.cdef.id, self.selected_frame)
        except (OSError, ValueError) as error:
            show_warning(self, "无法保存外观", str(error))
            return
        self.accept()

    def _fit_dialog(self) -> None:
        self.adjustSize()
        QTimer.singleShot(0, self._center_on_screen)

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is not None:
            self.setGeometry(QStyle.alignedRect(
                Qt.LeftToRight, Qt.AlignCenter, self.size(), screen.availableGeometry()))
