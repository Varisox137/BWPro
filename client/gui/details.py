"""对局内式神详情、额外状态与机制说明。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout,
)

from client import cli
from client.gui.cardart import seat_level_color, shikigami_pixmap
from client.gui.mechanisms import mechanism_panel, shikigami_mechanisms
from client.gui.widgets import CardWidget, polish_dialog_buttons


def player_ability_mechanisms(player, player_index: int, viewer: int) -> list[dict]:
    entries = list(player.auras) + [
        entry for entry in player.delayed
        if not entry.get("secret") or player_index == viewer
    ]
    return [
        {
            "name": entry.get("source_name") or "牌手能力",
            "frame": "skill",
            "text": entry.get("text") or "（无能力文本）",
        }
        for entry in entries
    ]


def shiki_status_lines(game, ref, viewer) -> list[str]:
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

    def mods(label, power, health=None) -> str:
        parts = [f"力量 {power:+d}"]
        if health is not None:
            parts.append(f"生命 {health:+d}")
        return f"{label} {'　'.join(parts)}"

    text = []
    if shiki.shield:
        text.append(f"护甲/破甲 {shiki.shield}")
    if shiki.energy:
        text.append(f"能量 {shiki.energy}")
    if shiki.perm_power or shiki.perm_health:
        text.append(mods("永久修正", shiki.perm_power, shiki.perm_health))
    if shiki.temp_power or shiki.temp_health:
        text.append(mods("临时修正", shiki.temp_power, shiki.temp_health))
    dyn_power = int(shiki.ext.get("dyn_power", 0))
    dyn_health = int(shiki.ext.get("dyn_health", 0))
    if dyn_power or dyn_health:
        text.append(mods("动态光环合计", dyn_power, dyn_health))
    if shiki.ext.get("power_zero"):
        text.append("力量覆写：0（动态光环与灵咒仍合计）")
    keywords = cli._kw_labels(
        shiki.keywords + shiki.one_shot_keywords + shiki.perm_keywords)
    if keywords:
        text.append(f"关键字：{'、'.join(keywords)}")
    for index, buff in enumerate(shiki.attack_buffs, 1):
        parts = [f"攻击后到期强化 {index}：力量 {buff.get('power', 0):+d}"]
        labels = cli._kw_labels(kw for kw, _cls in buff.get("keywords", []))
        if labels:
            parts.append(f"关键字 {'、'.join(labels)}")
        text.append("　".join(parts))
    if shiki.keep_shield:
        text.append("保留护甲")
    if shiki.keep_fragile:
        text.append("保留破甲")
    for index, immunity in enumerate(shiki.immunities, 1):
        text.append(f"免疫 {index}：{immunity.get('kind', '未标明类型')}")
    if shiki.stuns:
        kinds = "、".join(str(entry.get("kind", "未标明类型")) for entry in shiki.stuns)
        text.append(f"眩晕：{kinds}")
    if shiki.dying:
        text.append("濒死")
    if shiki.despawned:
        text.append("已离场")
    if shiki.defeated:
        text.append(f"气绝：复活倒计时 {shiki.revive_countdown}")
    if shiki.countdown is not None:
        countdown = [f"倒计时 {shiki.countdown}"]
        if shiki.countdown_initial is not None:
            countdown.append(f"初始 {shiki.countdown_initial}")
        countdown.append("一次型" if shiki.countdown_once else "循环型")
        source = shiki.countdown_source
        if source in db.cards:
            countdown.append(f"来源 {db.cards[source].name}")
        elif source in db.shikigami:
            countdown.append(f"来源 {db.shikigami[source].name}")
        text.append("　".join(countdown))
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
        if invocation.get("power") or invocation.get("health"):
            text.append(mods("基础", invocation.get("power", 0),
                             invocation.get("health", 0)))
        if invocation.get("bonus"):
            text.append(f"增强 {invocation['bonus']:+d}")
        if invocation.get("mod_power") or invocation.get("mod_health"):
            text.append(mods("修饰", invocation.get("mod_power", 0),
                             invocation.get("mod_health", 0)))
        idef = db.invocations.get(name)
        if idef is not None and idef.text:
            text.append(idef.text)
    return text


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
        self.setMinimumSize(720 if shiki.form is not None else 520, 600)
        layout = QVBoxLayout(self)
        cards = QHBoxLayout()
        self.column_names = ["main"]

        self.main_art_pixmap = shikigami_pixmap(shiki, game.db, seat=ref.shikigami, height=336)
        self.main_art_label = QLabel()
        self.main_art_label.setAlignment(Qt.AlignCenter)
        if self.main_art_pixmap is not None and not self.main_art_pixmap.isNull():
            self.main_art_label.setPixmap(self.main_art_pixmap)
            self.main_art_label.setFixedSize(self.main_art_pixmap.size())
            cards.addWidget(self.main_art_label)
        else:
            main_card = QFrame()
            main_card.setObjectName("shikigamiMainCard")
            main_card.setFixedSize(240, 336)
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
            cards.addWidget(main_card)

        self.form_card = None
        if shiki.form is not None:
            form_def = game.db.cards[shiki.form.id]
            self.form_card = CardWidget(form_def, db=game.db,
                                        level_color=seat_level_color(ref.shikigami))
            self.form_card.count_label.hide()
            self.form_card.setFixedSize(self.main_art_label.size())
            cards.addWidget(self.form_card)
            self.column_names.append("form")

        status_texts = shiki_status_lines(game, ref, viewer)
        self.status_mechanisms = [
            {"name": "额外状态", "frame": "skill", "text": line}
            for line in status_texts
        ]
        self.status_panel, self.status_labels = mechanism_panel(
            self.status_mechanisms, self, max_height=336)
        if self.status_panel is not None:
            cards.addWidget(self.status_panel, 1)
            self.column_names.append("status")

        self.mechanism_panel, self.mechanism_labels = mechanism_panel(
            shikigami_mechanisms(game, ref, status_texts=status_texts), self,
            max_height=336)
        if self.mechanism_panel is not None:
            cards.addWidget(self.mechanism_panel, 1)
            self.column_names.append("mechanisms")
        layout.addLayout(cards)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
