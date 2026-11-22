"""对局内式神详情、额外状态与机制说明。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLayout, QVBoxLayout,
)

from client.gui.cardart import card_pixmap, seat_level_color, shikigami_pixmap
from client.gui.mechanisms import mechanism_panel, shikigami_mechanisms
from client.gui.widgets import DETAIL_COLUMN_SPACING, polish_dialog_buttons


def player_ability_mechanisms(player, player_index: int, viewer: int) -> list[dict]:
    entries = list(player.auras) + [
        entry for entry in player.delayed
        if not entry.get("secret") or player_index == viewer
    ] + [entry for entry in player.card_auras if entry.get("scope") == "game"]
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


def _stat_mod_mechanisms(shiki) -> list[dict]:
    """普通力量/生命修正按来源与作用域合并，攻击后到期强化另列。"""
    grouped = {}
    for mod in shiki.stat_mods:
        key = (mod.get("source_name"), mod.get("text"), bool(mod.get("perm")),
               mod.get("scope"))
        entry = grouped.setdefault(key, {"power": 0, "health": 0})
        entry["power"] += int(mod.get("power", 0))
        entry["health"] += int(mod.get("health", 0))
    entries = []
    for (source_name, source_text, permanent, scope), amounts in grouped.items():
        parts = []
        if amounts["power"]:
            parts.append(f"力量 {amounts['power']:+d}")
        if amounts["health"]:
            parts.append(f"生命上限 {amounts['health']:+d}")
        duration = ("永久" if permanent else
                    {"turn": "本回合", "battle": "本次战斗"}.get(scope, "临时"))
        entries.append({
            "name": source_name or "身材修正", "frame": "skill",
            "text": f"{duration}　{'　'.join(parts)}\n{source_text or '（无来源文本）'}",
        })
    for buff in shiki.attack_buffs:
        if not buff.get("power") and not buff.get("keywords"):
            continue
        parts = []
        if buff.get("power"):
            parts.append(f"力量 {int(buff['power']):+d}")
        if buff.get("keywords"):
            parts.append("关键字 " + "、".join(keyword for keyword, _cls in buff["keywords"]))
        entries.append({
            "name": buff.get("source_name") or "攻击强化", "frame": "skill",
            "text": f"直到下一次攻击后　{'　'.join(parts)}\n"
                    f"{buff.get('text') or '（无来源文本）'}",
        })
    return entries


def shiki_status_mechanisms(game, ref, viewer) -> list[dict]:
    """延迟能力、身材修正、眩晕与灵咒按来源命名；完全相同项合并计数。"""
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

    entries = []
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
        entries.append({
            "name": db.cards[origin].name if origin in db.cards else "延迟能力",
            "frame": "skill", "text": "　".join(parts),
        })
    entries.extend(_stat_mod_mechanisms(shiki))
    if shiki.stuns:
        kinds = "、".join(str(entry.get("kind", "未标明类型")) for entry in shiki.stuns)
        entries.append({"name": "眩晕", "frame": "skill", "text": f"类型：{kinds}"})
    grouped = {}
    for invocation in shiki.invocations:
        name = invocation.get("name", "")
        idef = db.invocations.get(name)
        text = idef.text if idef is not None and idef.text else "（无灵咒文本）"
        bonus = int(invocation.get("bonus", 0))
        if bonus:
            text += f"（效果+{bonus}）"
        key = (name, text)
        if key not in grouped:
            grouped[key] = {"name": name, "frame": "invocation", "text": text, "count": 0}
        grouped[key]["count"] += 1
    for entry in grouped.values():
        count = entry.pop("count")
        if count > 1:
            entry["name"] += f"×{count}"
        entries.append(entry)
    return entries


def shiki_detail_suffix(game, ref) -> str:
    player = game.state.players[ref.player]
    shiki = player.shikigami[ref.shikigami]
    if shiki.id == 100117:
        return f"（本局游戏已投出{player.ext.get('dice_six_count', 0)}次6点）"
    if shiki.id == 100404:
        return f"（本局游戏已使用过{player.quest_counts.get('quest_used', 0)}张牌）"
    if shiki.id == 100128 and shiki.awakened == 10012805:
        return f"（效果+{shiki.ext.get('zhen_proc', 0)}）"
    return ""


def form_detail_suffix(game, ref) -> str:
    """形态自身光环的动态数值（不进手牌角标的来源说明）。"""
    shiki = game.state.players[ref.player].shikigami[ref.shikigami]
    if shiki.form is not None and shiki.form.id == 10011507:
        count = game.state.players[ref.player].ext.get("lianmo_used_game", 0)
        return f"（战斗牌额外+{count}/+{count}）"
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
        self.setMinimumWidth(720 if shiki.form is not None else 520)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetFixedSize)
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

        self.form_card = self.form_art_label = None
        self.form_art_pixmap = None
        if shiki.form is not None:
            form_def = game.db.cards[shiki.form.id]
            self.form_art_pixmap = card_pixmap(
                form_def, game.db, height=512,
                level_color=seat_level_color(ref.shikigami),
                appearance_source=(shiki.form.appearance_source or shiki.form.origin_id),
                description_suffix=form_detail_suffix(game, ref))
            self.form_art_label = QLabel()
            self.form_art_label.setAlignment(Qt.AlignCenter)
            self.form_art_label.setFixedSize(self.main_art_label.size())
            if self.form_art_pixmap is not None and not self.form_art_pixmap.isNull():
                self.form_art_pixmap = self.form_art_pixmap.scaled(
                    self.main_art_label.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self.form_art_label.setPixmap(self.form_art_pixmap)
            else:
                self.form_art_label.setText(form_def.name)
            self.form_card = self.form_art_label
            cards.addWidget(self.form_art_label, 0, Qt.AlignLeft | Qt.AlignTop)
            self.column_names.append("form")

        panel_width = self.main_art_label.width()
        self.status_mechanisms = shiki_status_mechanisms(game, ref, viewer)
        status_texts = [entry["text"] for entry in self.status_mechanisms]
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
