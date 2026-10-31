"""牌手幻境队列与牌手级能力详情。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from client.gui.details import player_ability_mechanisms
from client.gui.mechanisms import mechanism_panel
from client.gui.widgets import CardDetailDialog, CardWidget, polish_dialog_buttons


class PlayerDetailDialog(QDialog):
    """以整体横向滚动展示有序幻境及全部可见牌手能力。"""

    def __init__(self, game, player: int, viewer: int, parent=None):
        super().__init__(parent)
        state = game.state.players[player]
        self.setWindowTitle(state.name)
        self.setMinimumSize(520, 600)
        layout = QVBoxLayout(self)
        self.summary_label = QLabel(
            f"生命 {state.health}/{state.max_health}　护甲 {state.shield}\n"
            f"鬼火 {state.orb}　出击次数 {state.assaults_left}\n"
            f"墓地 {len(state.graveyard)}"
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.content_layout = QHBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.field_widgets = []
        art_width = 396
        for field in state.fields:
            cdef = game.db.cards[field.card_id]
            widget = CardWidget(
                cdef, db=game.db, display={"durability": field.intensity}, art_height=512)
            widget.count_label.hide()
            if widget._display_art is not None:
                art_width = widget._display_art.width()
            widget.setFixedWidth(art_width + 24)
            widget.setMinimumHeight(560)
            widget.clicked.connect(
                lambda selected: CardDetailDialog(selected, game.db, self).exec())
            self.content_layout.addWidget(widget)
            self.field_widgets.append(widget)

        self.ability_mechanisms = player_ability_mechanisms(state, player, viewer)
        self.ability_panel, self.ability_labels = mechanism_panel(
            self.ability_mechanisms, self, chars_per_line=12, font_scale=1.0,
            max_height=560, width=art_width)
        if self.ability_panel is not None:
            self.content_layout.addWidget(self.ability_panel)
        self.scroll_area.setWidget(content)
        layout.addWidget(self.scroll_area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
