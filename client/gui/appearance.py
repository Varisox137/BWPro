"""式神录卡牌外观：异画入口预留，牌框按当前异画预览并确认。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QStyle, QVBoxLayout,
)

from client.gui.card_appearance import (
    FRAME_VARIANTS, definition_appearance, save_card_appearance,
    save_shikigami_appearance,
)
from client.gui.widgets import CardChoiceView, polish_dialog_buttons, show_warning


class CardAppearanceDialog(QDialog):
    """先选外观类别，再预览当前异画的四种牌框；确认前不写本机配置。"""

    def __init__(self, cdef, db, parent=None):
        super().__init__(parent)
        self.cdef = cdef
        self.db = db
        self.selected_frame = definition_appearance(cdef)["frame_variant"]
        self.choice_view = None
        self.setWindowTitle(f"{cdef.name} · 更换异画 / 牌框")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.mode_button = QPushButton("异画")
        self.mode_button.setObjectName("small")
        self.mode_button.clicked.connect(self.show_menu)
        self.frame_button = QPushButton("牌框")
        self.frame_button.setObjectName("small")
        self.frame_button.clicked.connect(self.show_frame_choices)
        top.addWidget(self.mode_button, alignment=Qt.AlignLeft)
        top.addStretch(1)
        top.addWidget(self.frame_button, alignment=Qt.AlignRight)
        layout.addLayout(top)
        self.choice_slot = QVBoxLayout()
        layout.addLayout(self.choice_slot)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
        self.show_menu()

    def _clear_choice(self) -> None:
        if self.choice_view is not None:
            self.choice_slot.removeWidget(self.choice_view)
            self.choice_view.deleteLater()
            self.choice_view = None

    def show_menu(self) -> None:
        """返回类别菜单；异画功能尚未开放，仅保留入口。"""
        self._clear_choice()
        self.mode_button.setText("异画")
        self.mode_button.setEnabled(False)
        self.frame_button.show()
        self._fit_dialog()

    def show_frame_choices(self) -> None:
        """显示当前异画在常规/墨染/琉璃/百炼牌框下的渲染卡图。"""
        self._clear_choice()
        self.mode_button.setText("返回")
        self.mode_button.setEnabled(True)
        self.frame_button.hide()
        self.choice_view = CardChoiceView(
            [(variant, self.cdef, "原画") for variant in FRAME_VARIANTS],
            db=self.db, frame_variants={variant: variant for variant in FRAME_VARIANTS},
            button_text="选择")
        content_width = self.choice_view.widget().sizeHint().width()
        self.choice_view.setMinimumSize(
            content_width + 2 * self.choice_view.frameWidth(), 475)
        self.choice_view.chosen.connect(self._save)
        self.choice_slot.addWidget(self.choice_view)
        self._fit_dialog()

    def _save(self, variant: str) -> None:
        try:
            save = (save_card_appearance if getattr(self.cdef, "card_type", None) is not None
                    else save_shikigami_appearance)
            save(self.cdef.id, variant)
        except (OSError, ValueError) as error:
            show_warning(self, "无法保存外观", str(error))
            return
        self.selected_frame = variant
        self.accept()

    def _fit_dialog(self) -> None:
        self.adjustSize()
        QTimer.singleShot(0, self._center_on_screen)

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is not None:
            self.setGeometry(QStyle.alignedRect(
                Qt.LeftToRight, Qt.AlignCenter, self.size(), screen.availableGeometry()))
