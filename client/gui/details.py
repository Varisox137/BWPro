"""对局内式神详情、额外状态与机制说明。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout,
)

from client.gui.cardart import seat_level_color, shikigami_pixmap
from client.gui.mechanisms import mechanism_panel, shikigami_mechanisms
from client.gui.widgets import DETAIL_COLUMN_SPACING, CardWidget, polish_dialog_buttons


def player_ability_mechanisms(player, player_index: int, viewer: int) -> list[dict]:
    entries = list(player.auras) + [
        entry for entry in player.delayed
        if not entry.get("secret") or player_index == viewer
    ]
    entries.extend({"source_name": "眩晕", "text": str(entry.get("kind", "未标明类型"))}
                   for entry in player.ext.get("stuns", []))
    return [
        {
            "name": entry.get("source_name") or "牌手能力",
            "frame": "skill",
            "text": entry.get("text") or "（无能力文本）",
        }
        for entry in entries
    ]


def shiki_status_lines(game, ref, viewer) -> list[str]:
    """仅展示卡牌赋予的延迟能力与灵咒，不展开内部数值状态。"""
    shiki = game.state.players[ref.player].shikigami[ref.shikigami]
    db = game.db

    def ref_label(value) -> str | None:
        if value is None:
            return None
        pi = value.get("player") if isinstance(value, dict) else value.player
        si = value.get("shikigami") if isinstance(value, dict) else value.shikigami
        if pi is None or not 0 <= pi < len(game.state.players):
            return None
        player = game.state.players[pi]
        if si is None:
            return player.name
        if not 0 <= si < len(player.shikigami):
            return None
        source = player.shikigami[si]
        return f"{player.name}·{db.shikigami[source.id].name}"

    text = []
    for index, delayed in enumerate(shiki.delayed, 1):
        block = delayed.get("block") or {}
        when = block.get("when") if isinstance(block, dict) else block.when
        parts = [f"延迟能力 {index}：类型 {when}", f"次数 {delayed.get('uses', 1)}"]
        origin = delayed.get("origin")
        if origin in db.cards:
            parts.append(f"来源 {db.cards[origin].name}")
        chosen = None
        if not delayed.get("secret") or ref.player == viewer:
            chosen = ref_label(delayed.get("chosen"))
        if chosen:
            parts.append(f"目标 {chosen}")
        text.append("　".join(parts))
    if shiki.stuns:
        kinds = "、".join(str(entry.get("kind", "未标明类型")) for entry in shiki.stuns)
        text.append(f"眩晕：{kinds}")
    for index, invocation in enumerate(shiki.invocations, 1):
        name = invocation.get("name", "")
        parts = [f"灵咒 {index}：{name}"]
        source = ref_label(invocation.get("source"))
        if source:
            parts.append(f"来源 {source}")
        elif invocation.get("player") is not None:
            pi = invocation["player"]
            if 0 <= pi < len(game.state.players):
                parts.append(f"来源 {game.state.players[pi].name}")
        text.append("　".join(parts))
        idef = db.invocations.get(name)
        if idef is not None and idef.text:
            text.append(idef.text)
    return text


def shiki_detail_suffix(game, ref) -> str:
    player = game.state.players[ref.player]
    shiki = player.shikigami[ref.shikigami]
    if shiki.id == 100117:
        return f"（本局游戏已投出{player.ext.get('dice_six_count', 0)}次6点）"
    if shiki.id == 100404:
        return f"（本局游戏已完成{player.quest_counts.get('quest_used', 0)}次委托）"
    return ""


class ShikigamiDetailDialog(QDialog):
    """基础/觉醒主卡、同尺寸形态、额外状态与机制说明。"""

    def __init__(self, game, ref, viewer, parent=None):
        super().__init__(parent)
        shiki = game.state.players[ref.player].shikigami[ref.shikigami]
        definition = game.db.shikigami[shiki.id]
        awakened = shiki.awakened is not None
        main_def = game.db.cards[shiki.awakened] if awakened else definition
        power = definition.power + shiki.perm_power if awakened else definition.power
        health = definition.health + shiki.perm_health if awakened else definition.health
        name = main_def.name
        kind = "觉醒\n" if awakened else ""
        ability_text = main_def.text or (
            "（无觉醒能力文本）" if awakened else "（无基础能力文本）")
        self.main_card_text = (
            f"{kind}{name}\n等级 {shiki.level}\n"
            f"力量 {power}　生命 {health}\n{ability_text}"
        )
        self.setWindowTitle(definition.name)
        self.setMinimumSize(720 if shiki.form is not None else 520, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        cards = QHBoxLayout()
        cards.setSpacing(DETAIL_COLUMN_SPACING)
        self.detail_top = cards
        self.column_names = ["main"]

        suffix = shiki_detail_suffix(game, ref)
        art_kwargs = {"seat": ref.shikigami, "height": 512}
        if suffix:
            art_kwargs["description_suffix"] = suffix
        self.main_art_pixmap = shikigami_pixmap(shiki, game.db, **art_kwargs)
        self.main_art_label = QLabel()
        self.main_art_label.setAlignment(Qt.AlignCenter)
        if self.main_art_pixmap is not None and not self.main_art_pixmap.isNull():
            self.main_art_label.setPixmap(self.main_art_pixmap)
            self.main_art_label.setFixedSize(self.main_art_pixmap.size())
            cards.addWidget(self.main_art_label, 0, Qt.AlignLeft | Qt.AlignTop)
        else:
            main_card = QFrame()
            main_card.setObjectName("shikigamiMainCard")
            main_card.setFixedSize(240, 512)
            self.main_art_label.setFixedSize(main_card.size())
            main_card.setStyleSheet(
                "QFrame#shikigamiMainCard {"
                f"background-color: {'#56466f' if awakened else '#35566b'};"
                "border: 2px solid #d9b96a; border-radius: 8px; }"
            )
            main_layout = QVBoxLayout(main_card)
            main_label = QLabel(self.main_card_text)
            main_label.setWordWrap(True)
            main_label.setAlignment(Qt.AlignCenter)
            main_label.setStyleSheet("color: #f7f0dc; border: none; background: transparent;")
            main_layout.addWidget(main_label)
            cards.addWidget(main_card, 0, Qt.AlignLeft | Qt.AlignTop)

        self.form_card = None
        if shiki.form is not None:
            form_def = game.db.cards[shiki.form.id]
            self.form_card = CardWidget(form_def, db=game.db,
                                        level_color=seat_level_color(ref.shikigami))
            self.form_card.count_label.hide()
            self.form_card.setFixedSize(self.main_art_label.size())
            cards.addWidget(self.form_card, 0, Qt.AlignLeft | Qt.AlignTop)
            self.column_names.append("form")

        panel_width = self.main_art_label.width()
        status_texts = shiki_status_lines(game, ref, viewer)
        self.status_mechanisms = [
            {"name": "额外状态", "frame": "skill", "text": line}
            for line in status_texts
        ]
        self.status_panel, self.status_labels = mechanism_panel(
            self.status_mechanisms, self, max_height=512, width=panel_width)
        if self.status_panel is not None:
            cards.addWidget(self.status_panel, 0, Qt.AlignLeft | Qt.AlignTop)
            self.column_names.append("status")

        self.mechanism_panel, self.mechanism_labels = mechanism_panel(
            shikigami_mechanisms(game, ref, status_texts=status_texts), self,
            max_height=512, width=panel_width)
        if self.mechanism_panel is not None:
            cards.addWidget(self.mechanism_panel, 0, Qt.AlignLeft | Qt.AlignTop)
            self.column_names.append("mechanisms")
        cards.addStretch(1)
        layout.addLayout(cards)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
