"""固定坐标对局场景与卡牌图元。"""
from __future__ import annotations

import json
from functools import lru_cache

from PySide6.QtCore import (
    QEasingCurve, QLineF, QPointF, QPropertyAnimation, QRectF, QSizeF, Qt, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsObject, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
)

from client.gui.card_appearance import card_appearance
from client.gui.cardart import card_pixmap, entity_pixmap, seat_level_color
from client.gui.loading import LoadingIndicator
from client.gui.portrait import bwpdiy_root
from client.gui.ui_assets import (
    cardback_pixmap, damage_number_pixmap, dice_face, empty_deck_pixmap,
    heal_number_pixmap, load_gui_settings, turn_pixmap, ui_pixmap,
)
from core import targets
from core.model import Ref

SCENE_WIDTH = 1600
SCENE_HEIGHT = 900
HAND_SIZE = QSizeF(110, 156)
MULLIGAN_HAND_SIZE = QSizeF(180, 255)
DECK_BACK_SIZE = QSizeF(160, 114)
SHIKI_SIZE = QSizeF(148, 210)
PLAYER_SIZE = QSizeF(210, 130)
HAND_Z = 40
SHIKI_Z = 10
FOCUS_Z = 80
DRAG_Z = 100
ENEMY_HAND_Y = -78
OWN_HAND_Y = 822


def _entity_render_signature(shiki, form, seat: int, show_defeated_countdown: bool,
                             theme: str) -> tuple:
    return (
        shiki.id, shiki.awakened, form.id if form is not None else None, shiki.level,
        shiki.base_power, shiki.base_health, shiki.perm_power, shiki.perm_health,
        shiki.temp_power, shiki.temp_health, shiki.eff_power, shiki.health,
        shiki.max_health, shiki.shield, shiki.combat_power, shiki.energy,
        shiki.countdown, shiki.revive_countdown, shiki.defeated,
        show_defeated_countdown, seat, theme,
        tuple(shiki.keywords), tuple(shiki.one_shot_keywords), tuple(shiki.perm_keywords),
        bool(shiki.ext.get("power_zero")),
    )


@lru_cache(maxsize=1)
def _stat_font_family() -> str:
    path = bwpdiy_root() / "assets" / "fonts" / "方正北魏楷书.ttf"
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else "北魏楷书"


def card_owner_seat(game, player, cdef) -> int | None:
    owners = {sid for sid in (cdef.shikigami, cdef.shikigami2) if sid is not None}
    for index, shiki in enumerate(player.shikigami):
        if shiki.home_slot is None:
            continue
        identities = {shiki.id, shiki.transform_owner, shiki.ext.get("replace_owner")}
        if owners & identities:
            return index
    return None


def display_hand(game, pi: int, viewer: int, preserve_order: bool = False):
    """敌方、调度与中央交接预览保留入手序；常态己方仅显示排序。"""
    player = game.state.players[pi]
    if pi != viewer or game.state.phase == "mulligan" or preserve_order:
        return sorted(player.hand, key=lambda card: card.hand_seq)

    def sort_key(card):
        cdef = game.db.cards[card.id]
        seat = card_owner_seat(game, player, cdef)
        return (len(player.shikigami) if seat is None else seat,
                cdef.level or 0, card.id, card.hand_seq)

    return sorted(player.hand, key=sort_key)


def combat_position(scene_width: int, top: bool) -> QPointF:
    return QPointF(646 + (scene_width - SCENE_WIDTH) / 2, 220 if top else 460)


def deck_back_layout(player: int, index: int, viewer: int,
                     scene_width: float = SCENE_WIDTH):
    top = player != viewer
    position_index = index if top else 2 - index
    x, y, direction = ((110, 365, 45), (98, 396, 40), (86, 427, 24.5))[position_index]
    scale = SCENE_HEIGHT / 1280
    center_y = y * scale
    if not top:
        center_y = 2 * 452 - center_y
    center = QPointF(scene_width - x * scale, center_y)
    position = center - QPointF(DECK_BACK_SIZE.width() / 2, DECK_BACK_SIZE.height() / 2)
    return position, (direction if top else -direction) + 180, 20 + index if top else 22 - index


def layout_positions(game=None, viewer: int = 0, center_hand: bool = False,
                     scene_width: float = SCENE_WIDTH) -> dict[tuple, QPointF]:
    extra = scene_width - SCENE_WIDTH
    center_shift = extra / 2
    positions = {
        ("phase",): QPointF(65, 422),
        ("menu",): QPointF(1352 + extra, 16),
        ("log",): QPointF(12, 422),
        ("end_turn",): QPointF(scene_width - 168, 348),
        ("enemy_hand_label",): QPointF(1530 + extra, 156),
        ("enemy_deck",): QPointF(scene_width - 330, 268),
        ("own_deck",): QPointF(scene_width - 330, 572),
        ("hand_caption",): QPointF(1530 + extra, 680),
        ("ready",): QPointF(1328 + extra, 435),
        ("handoff",): QPointF(1216 + extra, 435),
        ("mulligan",): QPointF(730 + center_shift, 610),
        ("turn_order",): QPointF(1, 340),
        ("target_label",): QPointF(1120 + extra, 400),
        ("cancel_target",): QPointF(1120 + extra, 440),
        ("default_target",): QPointF(1120 + extra, 480),
        ("error",): QPointF(1, 540),
        ("result_banner",): QPointF(520 + center_shift, 250),
        ("result_back",): QPointF(730 + center_shift, 660),
        ("upgrade_phase",): QPointF(411 + center_shift, 422),
    }
    for pi in (0, 1):
        top = pi != viewer
        positions[("player", pi)] = QPointF(12, 4 if top else 766)
        for index in range(3):
            positions[("deck_back", pi, index)] = deck_back_layout(
                pi, index, viewer, scene_width)[0]
    if game is None:
        return positions

    arc = (120, 86, 86, 120)
    ready_x = (196, 421, 871, 1096)
    ready_positions = list(zip(ready_x, arc))
    for pi, player in enumerate(game.state.players):
        top = pi != viewer
        for index, shiki in enumerate(player.shikigami):
            if shiki.despawned:
                continue  # 召唤物离场后不保留图元；坑位仅供引擎下标稳定
            if player.combat_index == index:
                position = combat_position(scene_width, top)
            else:
                x, y = ready_positions[index]
                position = QPointF(x + center_shift, y if top else (690 - y))
            positions[("shiki", pi, index)] = position
        cards = display_hand(game, pi, viewer, preserve_order=center_hand)
        centered = (game.state.phase == "mulligan" or center_hand) and pi == viewer
        if centered:
            width = (len(cards) * MULLIGAN_HAND_SIZE.width()
                     + max(0, len(cards) - 1) * 16)
        spacing = 70 if len(cards) <= 8 else 490 / (len(cards) - 1)
        right = scene_width - 12
        for order, card in enumerate(cards):
            if centered:
                x = (scene_width - width) / 2 + order * (MULLIGAN_HAND_SIZE.width() + 16)
                y = 280
            else:
                x = right - HAND_SIZE.width() - spacing * (len(cards) - 1 - order)
                y = ENEMY_HAND_Y if top else OWN_HAND_Y
            positions[("hand", card.uid)] = QPointF(x, y)
    return positions


def usage_target(game, pi: int, cdef, usage_id):
    if isinstance(usage_id, str) and usage_id.startswith("choice:"):
        choice = int(usage_id.split(":", 1)[1])
        return game.db.cards[cdef.options[choice]].target
    if usage_id is not None:
        player = game.state.players[pi]
        method = next((method for method in game._card_methods(player, cdef)
                       if method.id == usage_id), None)
        if method is not None and method.target is not None:
            return method.target
    return cdef.target


class BattleCardItem(QGraphicsObject):
    def __init__(self, key, size=HAND_SIZE):
        super().__init__()
        self.key = key
        self.cdef = None
        self.pixmap = None
        self.revealed = True
        self.default_size = QSizeF(size)
        self.size = QSizeF(size)
        self.shiki_text = ""
        self.avatar_shape = "circle"
        self.text_color = QColor("#26221c")
        self.player_name = ""
        self.health = self.max_health = self.shield = 0
        self.health_color = "white"
        self.orb = self.assaults_left = 0
        self.orb_display_count = 2
        self.orb_overflow = 0
        self.inspire_power = self.inspire_shield = 0
        self.player = self.index = self.uid = None
        self.payload = key
        self.keywords: list[str] = []
        self.legal_targets: list[Ref] = []
        self.target_required = False
        self.targetable = False
        self.playable = False
        self.border_color = "yellow"
        self.dragging = False
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setZValue(SHIKI_Z if key[0] in ("shiki", "player") else HAND_Z)

    def set_art(self, pixmap) -> None:
        """在最大槽位内等比缩放，禁止把合成卡面拉伸变形。"""
        self.prepareGeometryChange()
        self.pixmap = pixmap
        self.size = QSizeF(self.default_size)
        if pixmap is not None and not pixmap.isNull() and pixmap.width() and pixmap.height():
            scale = min(self.default_size.width() / pixmap.width(),
                        self.default_size.height() / pixmap.height())
            self.size = QSizeF(pixmap.width() * scale, pixmap.height() * scale)

    def boundingRect(self):
        rect = QRectF(QPointF(0, 0), self.size)
        if self.dragging or self.targetable or self.playable:
            return rect.adjusted(-4, -4, 4, 4)
        return rect

    def update(self, *args) -> None:
        self.prepareGeometryChange()
        super().update(*args)

    def _operation_glow_color(self) -> QColor:
        colors = {"yellow": "#f3d56b", "blue": "#75b9d1", "green": "#78c896"}
        if self.dragging or self.targetable:
            return QColor("#f3d56b")
        if self.key[0] == "hand" and self.border_color == "yellow":
            return QColor("#d9b96a")
        return QColor(colors[self.border_color])

    def _paint_operation_glow(self, painter: QPainter, rect: QRectF) -> None:
        color = self._operation_glow_color()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, color.lighter(145))
        gradient.setColorAt(1, color.darker(115))
        painter.save()
        if self.pixmap is not None and not self.pixmap.isNull():
            source = self.pixmap.toImage().scaled(
                rect.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            glow = QImage(source.size(), QImage.Format_ARGB32)
            glow.fill(Qt.transparent)
            glow_painter = QPainter(glow)
            glow_painter.fillRect(glow.rect(), gradient)
            glow_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            glow_painter.drawImage(0, 0, source.convertToFormat(QImage.Format_Alpha8))
            glow_painter.end()
            for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4),
                           (-3, -3), (-3, 3), (3, -3), (3, 3)):
                painter.drawImage(rect.topLeft() + QPointF(dx, dy), glow)
        else:
            painter.setPen(QPen(QBrush(gradient), 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 8, 8)
        painter.restore()

    def paint(self, painter: QPainter, option, widget=None):
        del option, widget
        rect = QRectF(QPointF(0, 0), self.size)
        if self.dragging or self.targetable or self.playable:
            self._paint_operation_glow(painter, rect)
        if self.pixmap is not None and not self.pixmap.isNull():
            painter.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
        elif self.key[0] == "player":
            self._paint_player(painter, rect)
        elif self.key[0] == "shiki":
            painter.setPen(QPen(QColor("#d9b96a"), 3))
            painter.setBrush(QColor(45, 55, 65, 220))
            painter.drawRect(rect)
            painter.setPen(self.text_color)
            painter.drawText(rect.adjusted(5, 5, -5, -5),
                             Qt.TextWordWrap | Qt.AlignCenter, self.shiki_text)
        elif self.key[0] in ("hand", "card_use") and self.revealed:
            painter.setPen(QPen(QColor("#d9b96a"), 2))
            painter.setBrush(QColor(45, 55, 65, 220))
            painter.drawRect(rect)
            painter.setPen(self.text_color)
            text = self.cdef.name if self.cdef is not None else "卡牌"
            painter.drawText(rect.adjusted(5, 5, -5, -5),
                             Qt.TextWordWrap | Qt.AlignCenter, text)
        elif self.key[0] in ("hand", "deck_back", "card_use") and not self.revealed:
            painter.setPen(QPen(QColor("#d9b96a"), 2))
            painter.setBrush(QColor(45, 55, 65, 240))
            painter.drawRect(rect)
            painter.drawRect(rect.adjusted(7, 7, -7, -7))

    def _paint_player(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        avatar = QRectF(rect.left() + 2, rect.top() + 2, 104, 104)
        painter.setPen(QPen(QColor("#d9b96a"), 3))
        painter.setBrush(QColor(45, 65, 82, 235))
        painter.drawEllipse(avatar)
        painter.setPen(QColor("#f7f0dc"))
        font = painter.font()
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(avatar, Qt.AlignCenter, self.player_name[:1])

        def draw_stat(box, icon_name, value, icon_size, text_size):
            icon = ui_pixmap(f"stats/{icon_name}.png").scaled(
                icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_rect = QRectF(box.center().x() - icon_size / 2,
                               box.center().y() - icon_size / 2, icon_size, icon_size)
            painter.drawPixmap(icon_rect, icon, QRectF(icon.rect()))
            stat_font = QFont(_stat_font_family(), text_size)
            painter.setFont(stat_font)
            text_box = box.translated(0, 2)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.setPen(QColor("#141121"))
                painter.drawText(text_box.translated(dx, dy), Qt.AlignCenter, str(value))
            painter.setPen(QColor(self.health_color if icon_name == "health" else "#fff4e0"))
            painter.drawText(text_box, Qt.AlignCenter, str(value))

        hp = QRectF(avatar.right() - 40, avatar.bottom() - 30, 52, 38)
        draw_stat(hp, "health", self.health, 34, 16)
        if self.shield:
            shield = QRectF(hp.left(), hp.top() - 31, 52, 32)
            draw_stat(shield, "shield", self.shield, 30, 14)

        side_x = avatar.right() + 8
        orb_size = 14
        for index in range(self.orb_display_count):
            orb = QRectF(side_x + index * (orb_size + 4), avatar.top() + 6,
                         orb_size, orb_size)
            painter.setPen(QPen(QColor("#d9b96a"), 1))
            painter.setBrush(QColor("#d9b96a") if index < self.orb
                             else QColor(35, 40, 45, 180))
            painter.drawEllipse(orb)
        attack = QRectF(side_x, avatar.top() + 30, 28, 28)
        painter.setBrush(QColor(35, 40, 55, 230))
        painter.drawEllipse(attack)
        painter.drawText(attack, Qt.AlignCenter, f"出{self.assaults_left}")
        inspire = QRectF(side_x, avatar.top() + 64, 112, 28)
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        text = f"鼓舞 +{self.inspire_power}/+{self.inspire_shield}"
        outline = QColor("#141121") if self.text_color.lightness() >= 128 else QColor("#f3efe8")
        painter.setPen(outline)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(inspire.translated(dx, dy), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.setPen(self.text_color)
        painter.drawText(inspire, Qt.AlignLeft | Qt.AlignVCenter, text)
        name = QRectF(rect.left(), rect.top() + 104, rect.width(), 22)
        painter.setPen(self.text_color)
        painter.drawText(name, Qt.AlignLeft | Qt.AlignVCenter, self.player_name)
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.key[0] != "usage":
            self.scene().drag_controller.press(self, event.scenePos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.key[0] != "usage":
            self.scene().drag_controller.move(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            if self.key[0] == "hand" and not self.revealed:
                event.accept()
                return
            if (self.key[0] == "player"
                    and not QRectF(2, 2, 104, 104).contains(self.mapFromScene(event.scenePos()))):
                event.accept()
                return
            self.scene().read_detail_requested.emit(self.key[0], self.payload)
        elif self.key[0] == "usage":
            if self.playable:
                self.scene().usage_selected.emit(self.payload)
        else:
            self.scene().drag_controller.release(event.scenePos())
        event.accept()


class BattleVisualItem(QGraphicsObject):
    """由若干相对偏移的透明素材组成的非交互视觉图元。"""

    def __init__(self, layers=()):
        super().__init__()
        self.layers = []
        self._bounds = QRectF()
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.set_layers(layers)

    def set_layers(self, layers) -> None:
        self.prepareGeometryChange()
        self.layers = list(layers)
        self._bounds = QRectF()
        for pixmap, offset in self.layers:
            self._bounds = self._bounds.united(
                QRectF(offset, QSizeF(pixmap.size())))
        self.update()

    def boundingRect(self):
        return self._bounds

    def paint(self, painter: QPainter, option, widget=None):
        del option, widget
        for pixmap, offset in self.layers:
            painter.drawPixmap(offset, pixmap)


class BattleAnimationLayer:
    def __init__(self, scene):
        self.scene = scene
        self.items = []

    def add(self, item) -> None:
        item.setZValue(DRAG_Z)
        self.scene.addItem(item)
        self.items.append(item)

    def clear(self) -> None:
        for item in self.items:
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self.items.clear()


class BattleDragController:
    def __init__(self, scene):
        self.scene = scene
        self.item = None
        self.press_pos = QPointF()
        self.dragged = False
        self.drag_ghost = None
        self.drag_arrow = None

    def press(self, item: BattleCardItem, scene_pos: QPointF) -> bool:
        self.cancel()
        if item.scene() is not self.scene:
            return False
        readonly_detail = (
            self.scene.game_over and item.key[0] in ("hand", "shiki", "player")
            and (item.key[0] != "hand" or item.revealed))
        if not self.scene.inputs_open and not item.targetable and not readonly_detail:
            return False
        if item.key[0] == "hand" and not item.revealed:
            return False
        self.item = item
        self.press_pos = QPointF(scene_pos)
        return True

    def move(self, scene_pos: QPointF) -> None:
        item = self.item
        if item is None:
            return
        if not self.scene.inputs_open:
            self.cancel()
            return
        kind = item.key[0]
        can_drag = item.playable and self.scene.phase == "battle" \
            and kind in ("shiki", "hand")
        if not can_drag:
            return
        if not self.dragged:
            if QLineF(self.press_pos, scene_pos).length() <= QApplication.startDragDistance():
                return
            self._start_drag()
        self.drag_ghost.setPos(scene_pos - QPointF(item.size.width() / 2,
                                                   item.size.height() / 2))
        path = QPainterPath(item.sceneBoundingRect().center())
        path.lineTo(scene_pos)
        self.drag_arrow.setPath(path)

    def release(self, scene_pos: QPointF) -> None:
        item = self.item
        if item is None:
            return
        scene = self.scene
        kind = item.key[0]
        dragged = self.dragged
        source_rect = QRectF(item.scenePos(), item.size)
        target_ref = next((candidate.payload for candidate in scene.items(scene_pos)
                           if isinstance(candidate, BattleCardItem)
                           and isinstance(candidate.payload, Ref)), None)
        self.cancel()
        if not dragged:
            if (kind == "hand" and scene.phase == "mulligan" and item.playable
                    and item.player == scene.viewer):
                scene.select_mulligan(item.uid)
            elif (kind == "shiki" and scene.phase == "upgrade" and item.playable
                    and item.player == scene.viewer):
                scene.action_requested.emit({"op": "upgrade", "index": item.index})
            elif (kind in ("shiki", "player")
                  and item.payload in scene.legal_targets):
                scene.target_requested.emit(kind, item.payload)
            return
        if source_rect.contains(scene_pos):
            return
        if kind == "shiki":
            if "hunt" not in item.keywords:
                scene.action_requested.emit({"op": "assault", "index": item.index})
            elif target_ref in item.legal_targets:
                scene.action_requested.emit({"op": "assault", "index": item.index,
                                             "target": target_ref})
        elif kind == "hand":
            if target_ref in item.legal_targets:
                scene.action_requested.emit({"op": "play_card", "uid": item.uid,
                                             "target": target_ref})
            elif not item.target_required and (target_ref is None or not item.legal_targets):
                scene.action_requested.emit({"op": "play_card", "uid": item.uid})

    def cancel(self) -> None:
        was_dragged = self.dragged
        if self.item is not None:
            self.item.dragging = False
            self.item.setOpacity(1)
            self.item.update()
        self.item = None
        self.dragged = False
        self.scene.animation_layer.clear()
        self.drag_ghost = None
        self.drag_arrow = None
        self.scene._sync_focus()
        if was_dragged:
            self.scene._refresh_all_art()

    def _start_drag(self) -> None:
        item = self.item
        self.scene._stop_move_animation(item, refresh=False)
        if item.pixmap is not None and not item.pixmap.isNull():
            pixmap = item.pixmap.scaled(item.size.toSize(), Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation)
            self.drag_ghost = QGraphicsPixmapItem(pixmap)
        else:
            self.drag_ghost = QGraphicsRectItem(QRectF(QPointF(0, 0), item.size))
            self.drag_ghost.setPen(QPen(QColor("#d9b96a"), 2))
            self.drag_ghost.setBrush(QColor(45, 55, 65, 180))
        self.drag_ghost.setOpacity(0.65)
        self.drag_ghost.setPos(item.scenePos())
        self.drag_arrow = QGraphicsPathItem()
        self.drag_arrow.setPen(QPen(QColor("#f3d56b"), 3))
        self.scene.animation_layer.add(self.drag_ghost)
        self.scene.animation_layer.add(self.drag_arrow)
        item.dragging = True
        item.setOpacity(1)
        self.dragged = True
        item.update()
        self.scene.focus_for_drag(item)


class BattleView(QGraphicsView):
    def __init__(self, scene: BattleScene, parent=None):
        super().__init__(scene, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setMinimumSize(0, 0)
        self.fit_scene()

    def fit_scene(self) -> None:
        viewport = self.viewport()
        if viewport.width() > 0 and viewport.height() > 0:
            self.scene().set_viewport_size(viewport.width(), viewport.height())
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_scene()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.fit_scene()


class BattleScene(QGraphicsScene):
    target_requested = Signal(str, object)
    read_detail_requested = Signal(str, object)
    action_requested = Signal(dict)
    mulligan_selected = Signal(object)
    usage_selected = Signal(object)
    animations_settled = Signal()

    def __init__(self, db):
        super().__init__(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.db = db
        self.game = None
        self.layout_width = SCENE_WIDTH
        self.center_hand = False
        self._control_keys = {}
        self.cards: dict[tuple, BattleCardItem] = {}
        self._move_animations: dict[BattleCardItem, QPropertyAnimation] = {}
        self._card_use_animations: list[QVariantAnimation] = []
        self._card_use_items: dict[QVariantAnimation, BattleCardItem] = {}
        self._card_use_sources: dict[QVariantAnimation, dict] = {}
        self._hand_animation_cache: dict[int, tuple] = {}
        self._animation_timeline: list[dict] | None = None
        self._visual_animations: list[QVariantAnimation] = []
        self._visual_items: dict[QVariantAnimation, BattleVisualItem] = {}
        self._visual_events: dict[QVariantAnimation, dict] = {}
        self._visual_queue: list[dict] = []
        self._defeat_visuals: set[tuple[int, int]] = set()
        self.usage_items: list[BattleCardItem] = []
        self.usage_labels: list[QGraphicsTextItem] = []
        self.deck_backs: dict[tuple, BattleCardItem] = {}
        self.upgrade_badges: dict[int, QGraphicsPixmapItem] = {}
        self.phase = None
        self.viewer = 0
        self.theme = "light"
        self.inputs_open = False
        self.game_over = False
        self.enemy_cardback: str | None = None
        self.legal_targets: list[Ref] = []
        self.mulligan_uid = None
        self.menu_item = None
        self.log_item = None
        self.end_turn_item = None
        self.mulligan_item = None
        self.animation_layer = BattleAnimationLayer(self)
        self.focus_overlay = QGraphicsPathItem()
        self.focus_overlay.setZValue(FOCUS_Z)
        self.focus_overlay.setPen(QPen(Qt.NoPen))
        self.focus_overlay.setBrush(QColor(0, 0, 0, 150))
        self.focus_overlay.setAcceptedMouseButtons(Qt.NoButton)
        self.focus_overlay.hide()
        self.addItem(self.focus_overlay)
        self.banner_item = QGraphicsTextItem()
        self.banner_item.setFont(QFont("Microsoft YaHei", 42, QFont.Bold))
        self.banner_item.setDefaultTextColor(QColor("#f3d56b"))
        self.banner_item.setZValue(DRAG_Z + 20)
        self.banner_item.setAcceptedMouseButtons(Qt.NoButton)
        self.banner_item.hide()
        self.addItem(self.banner_item)
        self.banner_pixmap_item = BattleVisualItem()
        self.banner_pixmap_item.setZValue(DRAG_Z + 20)
        self.banner_pixmap_item.hide()
        self.addItem(self.banner_pixmap_item)
        self.banner_timer = QTimer(self)
        self.banner_timer.setInterval(30)
        self.banner_timer.timeout.connect(self._advance_banner)
        self._banner_frame = self._banner_frames = 0
        self.loading_item = QGraphicsTextItem()
        self.loading_item.setFont(QFont("Microsoft YaHei", 32, QFont.Bold))
        self.loading_item.setDefaultTextColor(QColor("#f3d56b"))
        self.loading_item.setZValue(DRAG_Z + 30)
        self.loading_item.setAcceptedMouseButtons(Qt.NoButton)
        self.loading_item.hide()
        self.addItem(self.loading_item)
        self.loading_background = QGraphicsRectItem(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.loading_background.setBrush(QColor("#f3efe8"))
        self.loading_background.setZValue(DRAG_Z + 29)
        self.loading_background.setAcceptedMouseButtons(Qt.NoButton)
        self.loading_background.hide()
        self.addItem(self.loading_background)
        self.loading = LoadingIndicator("正在准备对局", self.loading_item.setPlainText, self)
        self._loading_done = self._loading_total = 0
        self.drag_controller = BattleDragController(self)
        self.text_color = "#26221c"

    def set_text_color(self, color: str, theme: str | None = None) -> None:
        self.text_color = color
        theme_changed = theme is not None and theme != self.theme
        if theme is not None:
            self.theme = theme
        if theme_changed:
            for item in (*self.cards.values(), *self.deck_backs.values()):
                item._render_signature = None
        for item in self.cards.values():
            item.text_color = QColor(color)
            item.update()
        for item in (self.banner_item, self.loading_item, *self.usage_labels):
            item.setDefaultTextColor(QColor(color))

    def _cardback_name(self, player: int) -> str:
        own = player == self.viewer
        if not own and self.enemy_cardback is not None:
            return self.enemy_cardback
        return load_gui_settings()["own_cardback" if own else "enemy_cardback"]

    def _cardback_pixmap(self, player: int, *, landscape: bool = False) -> QPixmap:
        own = player == self.viewer
        return cardback_pixmap(
            "own" if own else "enemy", landscape=landscape,
            name=None if own else self.enemy_cardback)

    def set_enemy_cardback(self, name: str | None) -> None:
        if name == self.enemy_cardback:
            return
        self.enemy_cardback = name
        self._hand_animation_cache.clear()
        if self.game is not None:
            self.refresh_cardbacks()

    def _sync_deck_back(self, key: tuple, back: BattleCardItem) -> None:
        if self.game is None:
            return
        player_index = key[1]
        player = self.game.state.players[player_index]
        side = "enemy" if player_index != self.viewer else "own"
        light = player.ext.get("deck_out_burn") is not None if not player.deck else None
        cardback = self._cardback_name(player_index) if player.deck else None
        signature = (side, bool(player.deck), light, cardback, self.theme)
        if getattr(back, "_render_signature", None) != signature:
            pixmap = (self._cardback_pixmap(player_index, landscape=True) if player.deck else
                      empty_deck_pixmap(light, landscape=True))
            rotated = (pixmap.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
                       if pixmap is not None else None)
            back.set_art(rotated)
            back._render_signature = (
                signature if rotated is not None and not rotated.isNull() else None)
        position, rotation, z_value = deck_back_layout(
            player_index, key[2], self.viewer, self.layout_width)
        back.setPos(position + QPointF(0, (DECK_BACK_SIZE.height() - back.size.height()) / 2))
        back.setRotation(rotation)
        back.setZValue(z_value)
        back.update()

    def set_viewport_size(self, width: int, height: int) -> None:
        """宽窗口扩展场景横向布局，避免等比缩放留下两侧信箱边。"""
        layout_width = max(SCENE_WIDTH, SCENE_HEIGHT * width / height)
        if abs(layout_width - self.layout_width) < 0.01:
            return
        self.layout_width = layout_width
        self.setSceneRect(0, 0, layout_width, SCENE_HEIGHT)
        self.loading_background.setRect(self.sceneRect())
        positions = layout_positions(self.game, self.viewer, center_hand=self.center_hand,
                                     scene_width=layout_width)
        for proxy, key in self._control_keys.items():
            proxy.setPos(positions[key])
        for key, item in self.cards.items():
            if key in positions:
                item.setPos(positions[key])
        for key, item in self.deck_backs.items():
            self._sync_deck_back(key, item)
        for item in (self.banner_item, self.banner_pixmap_item, self.loading_item):
            if item.isVisible():
                rect = item.boundingRect()
                item.setPos((layout_width - rect.width()) / 2,
                            (SCENE_HEIGHT - rect.height()) / 2)
        self.mulligan_selected.emit(self.mulligan_uid)

    def _start_banner(self, item, duration: int) -> None:
        rect = item.boundingRect()
        item.setPos((self.layout_width - rect.width()) / 2,
                    (SCENE_HEIGHT - rect.height()) / 2)
        item.setTransformOriginPoint(rect.center())
        item.setScale(0.85)
        item.setOpacity(0)
        item.show()
        self._banner_frame = 0
        self._banner_frames = max(1, round(duration / self.banner_timer.interval()))
        self.banner_timer.start()

    def show_banner(self, text: str, duration: int = 900) -> None:
        self.banner_pixmap_item.hide()
        self.banner_item.setPlainText(text)
        self._start_banner(self.banner_item, duration)

    def show_turn_banner(self, own_turn: bool, duration: int = 900) -> None:
        self.banner_item.hide()
        name = "your_turn" if own_turn else "opponent_turn"
        suffix = "dark" if self.theme == "light" else "light"
        pixmap = turn_pixmap(own_turn, self.theme).scaledToWidth(
            400, Qt.SmoothTransformation)
        self.banner_pixmap_item.set_layers([(pixmap, QPointF())])
        self.banner_pixmap_item.setProperty("assetName", f"{name}_{suffix}")
        self._start_banner(self.banner_pixmap_item, duration)

    def _advance_banner(self) -> None:
        if not self._banner_frames:
            self.hide_banner()
            return
        self._banner_frame += 1
        progress = self._banner_frame / self._banner_frames
        opacity = min(1, progress * 4) if progress < 0.75 else (1 - progress) * 4
        for item in (self.banner_item, self.banner_pixmap_item):
            item.setScale(0.85 + 0.15 * min(1, progress * 2))
            item.setOpacity(max(0, opacity))
        if progress >= 1:
            self.hide_banner()

    def hide_banner(self) -> None:
        self.banner_timer.stop()
        self._banner_frame = self._banner_frames = 0
        self.banner_item.hide()
        self.banner_pixmap_item.hide()

    def show_loading(self, prefix: str) -> None:
        self.loading.start(prefix)
        rect = self.loading_item.boundingRect()
        self.loading_item.setPos((self.layout_width - rect.width()) / 2,
                                 (SCENE_HEIGHT - rect.height()) / 2)
        self.loading_background.show()
        self.loading_item.show()

    def loading_tick(self) -> None:
        self._loading_done += 1
        self.loading.set_progress(self._loading_done, self._loading_total)
        self.loading.tick()

    def hide_loading(self) -> None:
        self.loading.stop()
        self.loading_item.hide()
        self.loading_background.hide()

    def add_control(self, widget, key: tuple, size=None):
        if size is not None:
            widget.setFixedSize(*size)
        widget.setAttribute(Qt.WA_TranslucentBackground)
        widget.setAutoFillBackground(False)
        if widget.inherits("QLabel"):
            widget.setStyleSheet(widget.styleSheet() + "background: transparent;")
        proxy = self.addWidget(widget)
        self._control_keys[proxy] = key
        proxy.setPos(layout_positions(scene_width=self.layout_width)[key])
        proxy.setZValue(60)
        return proxy

    def _hand_render_signature(self, card, revealed: bool, detail: dict,
                               owner_seat: int | None, own: bool) -> tuple:
        appearance = card_appearance(card.id) if revealed else None
        player = self.viewer if own else 1 - self.viewer
        cardback = None if revealed else self._cardback_name(player)
        centered = (self.phase == "mulligan" or self.center_hand) and own
        return (
            card.id, revealed,
            json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            (appearance["frame_variant"], appearance["art_index"]) if appearance else None,
            cardback, seat_level_color(owner_seat), centered, 255 if centered else 156,
            self.theme,
        )

    def _sync_hand_art(self, item: BattleCardItem, card, cdef, revealed: bool,
                       detail: dict, owner_seat: int | None, own: bool,
                       art_context: dict) -> None:
        signature = self._hand_render_signature(card, revealed, detail, owner_seat, own)
        if getattr(item, "_render_signature", None) == signature:
            return
        height = 255 if (self.phase == "mulligan" or self.center_hand) and own else 156
        player = self.viewer if own else 1 - self.viewer
        pixmap = (card_pixmap(cdef, self.db, display=detail.get("render"),
                              level_color=seat_level_color(owner_seat),
                              cache_context=art_context, height=height)
                  if cdef is not None else self._cardback_pixmap(player))
        item.set_art(pixmap)
        item._render_signature = (
            signature if pixmap is not None and not pixmap.isNull() else None)

    def refresh_cardbacks(self) -> None:
        """设置页保存卡背后立即刷新当前对局，无需重建场景。"""
        for key, item in self.deck_backs.items():
            self._sync_deck_back(key, item)
        for key, item in self.cards.items():
            if key[0] == "hand" and not item.revealed:
                own = item.player == self.viewer
                card = next(card for card in self.game.state.players[item.player].hand
                            if card.uid == key[1])
                self._sync_hand_art(item, card, None, False, {}, None, own, {})
                item.update()

    def select_mulligan(self, uid: int) -> None:
        self.mulligan_uid = uid
        for key, item in self.cards.items():
            if key[0] == "hand":
                item.setTransformOriginPoint(item.boundingRect().center())
                item.setScale(1.08 if key[1] == uid else 1.0)
                item.update()
        self.mulligan_selected.emit(uid)
        self._sync_focus()

    def set_focus(self, items) -> None:
        """用带轮廓孔洞的暗色遮罩突出图元，其余画面统一压暗。"""
        path = QPainterPath()
        path.addRect(self.sceneRect().adjusted(0, -120, 0, 120))
        for item in items:
            rect = item.sceneBoundingRect()
            if isinstance(item, BattleCardItem) and item.pixmap is not None \
                    and not item.pixmap.isNull():
                image = item.pixmap.toImage().scaled(
                    rect.size().toSize(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                for y in range(image.height()):
                    run_start = -1
                    for x in range(image.width() + 1):
                        opaque = x < image.width() and image.pixelColor(x, y).alpha() > 0
                        if opaque and run_start < 0:
                            run_start = x
                        elif not opaque and run_start >= 0:
                            path.addRect(rect.left() + run_start, rect.top() + y,
                                         x - run_start, 1)
                            run_start = -1
                continue
            path.addRoundedRect(rect, 6, 6)
        path.setFillRule(Qt.OddEvenFill)
        self.focus_overlay.setPath(path)
        self.focus_overlay.show()

    def clear_focus(self) -> None:
        self.focus_overlay.hide()
        self.focus_overlay.setPath(QPainterPath())

    @property
    def visual_busy(self) -> bool:
        return bool(self._visual_animations or self._visual_queue or self._move_animations)

    def _sync_focus(self) -> None:
        if self.drag_controller.dragged:
            return
        if self.phase == "upgrade":
            items = [item for key, item in self.cards.items()
                     if key[0] == "shiki" and self.inputs_open and item.playable]
        elif self.phase == "mulligan":
            items = [item for key, item in self.cards.items()
                     if key[0] == "hand" and item.player == self.viewer and self.inputs_open]
            if self.mulligan_uid is not None and self.mulligan_item.isVisible():
                items.append(self.mulligan_item)
            if self.ready_item.isVisible():
                items.append(self.ready_item)
        else:
            items = []
        if items:
            self.set_focus(items)
        else:
            self.clear_focus()
        self._sync_upgrade_badges()

    def _sync_upgrade_badges(self) -> None:
        for badge in self.upgrade_badges.values():
            self.removeItem(badge)
        self.upgrade_badges.clear()
        if self.phase != "upgrade" or not self.inputs_open:
            return
        player = self.game.state.players[self.viewer]
        for index in self.game.legal_upgrade_indices(self.viewer):
            target_level = player.shikigami[index].level + 1
            asset = (bwpdiy_root() / "assets" / "levels"
                     / f"level_{target_level}_{seat_level_color(index)}.png")
            pixmap = QPixmap(str(asset)).scaled(
                52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            badge = QGraphicsPixmapItem(pixmap)
            shiki = self.cards.get(("shiki", self.viewer, index))
            if shiki is None:
                continue
            badge.setPos(shiki.x() + (shiki.size.width() - pixmap.width()) / 2,
                         shiki.y() - pixmap.height() - 8)
            badge.setZValue(FOCUS_Z + 10)
            self.addItem(badge)
            self.upgrade_badges[index] = badge

    def focus_for_drag(self, source: BattleCardItem) -> None:
        refs = list(source.legal_targets)
        if source.key[0] == "shiki" and "hunt" not in source.keywords:
            enemy = self.game.state.players[1 - self.viewer]
            refs = ([Ref(player=1 - self.viewer)] if "direct" in source.keywords
                    else [Ref(player=1 - self.viewer, shikigami=enemy.combat_index)])
        items = [source]
        for ref in refs:
            key = (("player", ref.player) if ref.shikigami is None
                   else ("shiki", ref.player, ref.shikigami))
            item = self.cards.get(key)
            if item is not None and item not in items:
                items.append(item)
        self.set_focus(items)

    def _stop_move_animation(self, item: BattleCardItem, *, refresh=True) -> None:
        self._visual_queue[:] = [event for event in self._visual_queue
                                 if not (event.get("v") == "_move"
                                         and event.get("item") is item)]
        animation = self._move_animations.pop(item, None)
        if animation is not None:
            animation.stop()
            if animation in self._visual_animations:
                self._visual_animations.remove(animation)
            self._visual_events.pop(animation, None)
            animation.deleteLater()
            self._start_queued_visuals()
            if refresh:
                self._refresh_all_art()

    def _animate_position(self, item: BattleCardItem, target: QPointF,
                          group=None) -> None:
        self._visual_queue[:] = [event for event in self._visual_queue
                                 if not (event.get("v") == "_move"
                                         and event.get("item") is item)]
        start = QPointF(item.pos())
        if start == target and item not in self._move_animations:
            item.setPos(target)
            return
        self._queue_or_start_visual(
            {"v": "_move", "item": item, "start": start, "target": QPointF(target),
             "g": group})

    def _start_move_event(self, event: dict) -> None:
        item = event["item"]
        animation = QPropertyAnimation(item, b"pos", self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Linear)
        animation.setStartValue(event["start"])
        animation.setEndValue(event["target"])
        self._move_animations[item] = animation
        self._visual_animations.append(animation)
        self._visual_events[animation] = dict(event)
        animation.finished.connect(
            lambda item=item, animation=animation: self._finish_move_animation(item, animation))
        animation.start()

    def _finish_move_animation(self, item: BattleCardItem, animation) -> None:
        if self._move_animations.get(item) is animation:
            del self._move_animations[item]
            if animation in self._visual_animations:
                self._visual_animations.remove(animation)
            self._visual_events.pop(animation, None)
            animation.deleteLater()
            self._start_queued_visuals()
            self._refresh_all_art()

    def animate_card_use(self, uid: int, card_id: int, player: int,
                         response: bool = False) -> None:
        if response:
            self.play_visual_event({"v": "response", "p": player})
        self._queue_or_start_visual(
            {"v": "_card_use", "u": uid, "c": card_id, "p": player,
             "response": response})

    def _start_card_use_event(self, event: dict) -> None:
        uid, card_id, player = event["u"], event["c"], event["p"]
        cdef = self.db.cards[card_id]
        cached = self._hand_animation_cache.get(uid)
        if cached is None:
            source_pos = QPointF(
                self.layout_width - HAND_SIZE.width() - 1,
                ENEMY_HAND_Y if player != self.viewer else OWN_HAND_Y)
            source_pixmap = None
            source_size = QSizeF(HAND_SIZE)
            source_revealed = player == self.viewer
        else:
            source_pos, source_pixmap, source_size, source_revealed = cached
            source_pos = QPointF(source_pos)
            source_size = QSizeF(source_size)
        item = BattleCardItem(("card_use", uid), size=source_size)
        item.cdef = cdef
        item.player = player
        item.revealed = source_revealed
        item.text_color = QColor(self.text_color)
        if not source_revealed or source_pixmap is None or source_pixmap.isNull():
            source_pixmap = self._cardback_pixmap(player)
        item.set_art(source_pixmap)
        item.setAcceptedMouseButtons(Qt.NoButton)
        item.setZValue(DRAG_Z + 10)
        item.setPos(source_pos)
        item.setTransformOriginPoint(item.boundingRect().center())
        self.addItem(item)

        animation = QVariantAnimation(self)
        animation.setDuration(900)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        big_size = QSizeF(220, 312)
        big_pixmap = card_pixmap(
            cdef, self.db, cache_context={}, height=int(round(big_size.height())))
        self._card_use_animations.append(animation)
        self._visual_animations.append(animation)
        self._visual_events[animation] = dict(event)
        self._card_use_items[animation] = item
        self._card_use_sources[animation] = {
            "source_pos": source_pos,
            "source_size": source_size,
            "big_pos": QPointF(
                70 if player == self.viewer else self.layout_width - 70 - big_size.width(),
                (SCENE_HEIGHT - big_size.height()) / 2),
            "big_size": big_size,
            "big_pixmap": big_pixmap,
            "flipped": False,
        }
        animation.valueChanged.connect(
            lambda value, animation=animation: self._update_card_use(animation, value))
        animation.finished.connect(
            lambda animation=animation: self._finish_card_use(animation))
        animation.start()

    def _update_card_use(self, animation, progress: float) -> None:
        item = self._card_use_items.get(animation)
        source = self._card_use_sources.get(animation)
        if item is None or source is None:
            return
        flip_end = 0.28
        if progress >= flip_end / 2 and not source["flipped"]:
            source["flipped"] = True
            item.revealed = True
            item.default_size = QSizeF(source["big_size"])
            if source["big_pixmap"] is not None and not source["big_pixmap"].isNull():
                item.set_art(source["big_pixmap"])
        item.setTransformOriginPoint(item.boundingRect().center())
        if progress < flip_end:
            flip = progress / flip_end
            target = source["big_pos"]
            item.setPos(source["source_pos"] + (target - source["source_pos"]) * flip)
            transform = QTransform()
            transform.scale(max(0.02, abs(1 - 2 * flip)), 1)
            item.setTransform(transform)
            item.setOpacity(1)
        else:
            item.setPos(source["big_pos"])
            item.setTransform(QTransform())
            item.setOpacity(1 if progress < 0.75 else max(0, (1 - progress) / 0.25))

    def _finish_card_use(self, animation) -> None:
        if animation not in self._card_use_items:
            return
        self._card_use_animations.remove(animation)
        if animation in self._visual_animations:
            self._visual_animations.remove(animation)
        self._visual_events.pop(animation, None)
        item = self._card_use_items.pop(animation)
        self._card_use_sources.pop(animation, None)
        if item.scene() is self:
            self.removeItem(item)
        animation.deleteLater()
        self._start_queued_visuals()
        self._refresh_all_art()

    def defeat_countdown_hidden(self, player: int, index: int) -> bool:
        return (player, index) in self._defeat_visuals

    @staticmethod
    def _visual_target_key(event: dict) -> tuple:
        kind = event.get("v")
        if kind == "response":
            return ("scene",)
        if kind == "_move":
            return event["item"].key
        if kind == "_card_use":
            return ("card_use", event["u"])
        if kind == "hand":
            return ("hand", event["u"])
        player = int(event.get("p", 0))
        index = event.get("s")
        return ("shiki", player, index) if index is not None else ("player", player)

    def _animation_can_start(self, event: dict) -> bool:
        target = self._visual_target_key(event)
        active = list(self._visual_events.values())
        if any(self._visual_target_key(current) == target for current in active):
            return False
        if not active:
            return True
        group = event.get("g")
        return group is not None and all(current.get("g") == group for current in active)

    def _queue_or_start_visual(self, event: dict) -> None:
        if self._animation_can_start(event):
            self._start_visual_event(event)
        else:
            self._visual_queue.append(dict(event))

    def _start_queued_visuals(self) -> None:
        """默认全局 FIFO；同组事件可越过其他组的等待项并行播放。"""
        index = 0
        while index < len(self._visual_queue):
            event = self._visual_queue[index]
            if not self._animation_can_start(event):
                index += 1
                continue
            self._visual_queue.pop(index)
            self._start_visual_event(event)

    def play_visual_event(self, event: dict) -> None:
        kind = event.get("v")
        if kind not in ("defeated", "luck", "luck_dice", "luck_reroll", "luck_result",
                        "heal", "damage", "immune", "response", "upgrade", "move",
                        "assault", "stat", "countdown", "countdown_proc", "revive", "hand"):
            return
        if kind == "response" and int(event.get("p", -1)) == self.viewer:
            return  # 仅提示对方响应
        if kind == "luck_result" and bool(event.get("success")) == bool(event.get("on_fail")):
            return  # 成功生效只显示大吉；失败生效只显示大凶，另一分支不显示字样
        events = ([dict(event, v="luck_dice"), dict(event, v="luck_result")]
                  if kind == "luck" else [event])
        for current in events:
            self._queue_or_start_visual(current)

    def _start_visual_event(self, event: dict) -> None:
        kind = event.get("v")
        if kind == "hand":
            player = int(event.get("p", self.viewer))
            uid = event["u"]
            item = self.cards.get(("hand", uid))
            if (item is None or self.game is None
                    or uid not in {card.uid for card in self.game.state.players[player].hand}):
                return
            target = QPointF(item.pos())
            if event.get("from") == "deck":
                backs = [back for key, back in self.deck_backs.items() if key[1] == player]
                if backs:
                    item.setPos(max(backs, key=lambda back: back.zValue()).pos())
                else:
                    index = 0 if player == self.viewer else 2
                    source = layout_positions(scene_width=self.layout_width)[
                        ("deck_back", player, index)]
                    pixmap = self._cardback_pixmap(player, landscape=True)
                    scale = min(DECK_BACK_SIZE.width() / pixmap.width(),
                                DECK_BACK_SIZE.height() / pixmap.height())
                    item.setPos(source + QPointF(
                        0, (DECK_BACK_SIZE.height() - pixmap.height() * scale) / 2))
            else:
                source = self.cards.get(("player", player))
                if source is not None:
                    item.setPos(source.pos())
            item.show()
            self._animate_position(item, target, group=event.get("g"))
            return
        if kind in ("stat", "countdown", "countdown_proc", "revive"):
            player = int(event.get("p", self.viewer))
            index = event.get("s")
            snapshot = event.get("r") or {}
            if index is None:
                target = self.cards.get(("player", player))
                if target is not None:
                    current = self.game.state.players[player]
                    target.health = snapshot.get("health", current.health)
                    target.max_health = snapshot.get("max_health", current.max_health)
                    target.shield = snapshot.get("shield", current.shield)
                    target.health_color = (
                        "red" if target.health < target.max_health
                        else "green" if target.max_health > 30 else "white")
                    target.update()
            else:
                target = self.cards.get(("shiki", player, index))
                self._refresh_defeated_entity(player, index, snapshot=event.get("r"))
            item = BattleVisualItem()
            item.setProperty("assetName", kind)
            if target is not None:
                item.setPos(target.sceneBoundingRect().center())
            item.setZValue(DRAG_Z + 15)
            item.setOpacity(0)
            self.addItem(item)
            animation = QVariantAnimation(self)
            animation.setDuration(200)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            self._visual_animations.append(animation)
            self._visual_items[animation] = item
            self._visual_events[animation] = dict(event)
            animation.valueChanged.connect(
                lambda value, animation=animation: self._update_visual(animation, value))
            animation.finished.connect(
                lambda animation=animation: self._finish_visual(animation))
            animation.start()
            return
        if kind == "assault":
            image = ui_pixmap("assault/出击.png")
            player = int(event.get("p", self.viewer))
            x = 70 if player == self.viewer else self.layout_width - 70 - image.width()
            item = BattleVisualItem([(image, QPointF(-image.width() / 2,
                                                     -image.height() / 2))])
            item.setProperty("assetName", kind)
            item.setPos(x + image.width() / 2, SCENE_HEIGHT / 2)
            item.setZValue(DRAG_Z + 15)
            item.setOpacity(0)
            self.addItem(item)
            animation = QVariantAnimation(self)
            animation.setDuration(900)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            self._visual_animations.append(animation)
            self._visual_items[animation] = item
            self._visual_events[animation] = dict(event)
            animation.valueChanged.connect(
                lambda value, animation=animation: self._update_visual(animation, value))
            animation.finished.connect(
                lambda animation=animation: self._finish_visual(animation))
            animation.start()
            return
        if kind == "move":
            player = int(event.get("p", self.viewer))
            index = int(event.get("s", 0))
            item = self.cards.get(("shiki", player, index))
            if item is not None:
                positions = layout_positions(
                    self.game, self.viewer, center_hand=self.center_hand,
                    scene_width=self.layout_width)
                target = positions[("shiki", player, index)]
                if event.get("zone") == "combat":
                    target = combat_position(self.layout_width, player != self.viewer)
                self._animate_position(item, target, group=event.get("g"))
            return
        if kind == "_move":
            self._start_move_event(event)
            return
        if kind == "_card_use":
            self._start_card_use_event(event)
            return
        player = int(event.get("p", self.viewer))
        index = event.get("s")
        target_key = (("shiki", player, index) if index is not None
                      else ("player", player))
        target = self.cards.get(target_key)
        if kind == "response":
            center = self.sceneRect().center()
        elif target is None:
            return
        else:
            center = target.sceneBoundingRect().center()
        if kind == "defeated":
            key = (player, int(index))
            self._defeat_visuals.add(key)
            self._refresh_defeated_entity(*key, snapshot=event.get("r"))
        if kind in ("defeated", "immune"):
            asset = ("defeat_" + (load_gui_settings()["defeated_variant"] or "white")
                     if kind == "defeated" else "immune")
            word = ui_pixmap(f"animations/{asset}.png").scaled(
                160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lift = 12 if kind == "defeated" else 0
            layers = [(word, QPointF(-word.width() / 2, -word.height() / 2 - lift))]
        elif kind == "response":
            left = ui_pixmap("animations/response_1.png").scaled(
                220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            right = ui_pixmap("animations/response_2.png").scaled(
                220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layers = [(left, QPointF(-left.width(), -left.height() / 2)),
                      (right, QPointF(0, -right.height() / 2))]
        elif kind == "upgrade":
            color = load_gui_settings()["upgrade_variant"] or "yellow"
            word = ui_pixmap(f"animations/up_{color}.png").scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layers = [(word, QPointF(-word.width() / 2,
                                     -target.size.height() / 2 - word.height() - 8))]
        elif kind == "damage":
            background = ui_pixmap("numbers/damage_background.png").scaledToWidth(
                180, Qt.SmoothTransformation)
            number = damage_number_pixmap(
                int(event.get("amount", 0)), max_width=round(background.width() * 0.85))
            layers = [(background, QPointF(-background.width() / 2,
                                           -background.height() / 2)),
                      (number, QPointF(-number.width() / 2, -number.height() / 2))]
        elif kind == "heal":
            number = heal_number_pixmap(int(event.get("amount", 0))).scaledToHeight(
                72, Qt.SmoothTransformation)
            layers = [(number, QPointF(-number.width() / 2, -number.height() / 2))]
        elif kind == "luck_dice":
            dice = dice_face(int(event.get("dice", 1))).scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layers = [(dice, QPointF(-dice.width() / 2, -dice.height() / 2))]
        else:
            result_name = ("dice_reroll" if kind == "luck_reroll" else
                           "dice_successful" if event.get("success") else "dice_unsuccessful")
            result = ui_pixmap(f"animations/{result_name}.png").scaled(
                180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layers = [(result, QPointF(-result.width() / 2, -result.height() / 2 - 12))]
        item = BattleVisualItem(layers)
        item.setProperty("assetName", kind)
        item.setPos(center)
        item.setZValue(DRAG_Z + 15)
        item.setOpacity(0)
        self.addItem(item)
        animation = QVariantAnimation(self)
        animation.setDuration(650)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        self._visual_animations.append(animation)
        self._visual_items[animation] = item
        self._visual_events[animation] = dict(event)
        animation.valueChanged.connect(
            lambda value, animation=animation: self._update_visual(animation, value))
        animation.finished.connect(
            lambda animation=animation: self._finish_visual(animation))
        animation.start()

    def _update_visual(self, animation, progress: float) -> None:
        item = self._visual_items.get(animation)
        if item is not None:
            item.setOpacity(min(1, progress * 4) if progress < 0.75
                            else max(0, (1 - progress) * 4))

    def _finish_visual(self, animation) -> None:
        if animation not in self._visual_items:
            return
        self._visual_animations.remove(animation)
        item = self._visual_items.pop(animation)
        event = self._visual_events.pop(animation, {})
        if event.get("v") == "defeated":
            key = (int(event.get("p", 0)), int(event.get("s", 0)))
            self._defeat_visuals.discard(key)
            self._refresh_defeated_entity(*key, snapshot=event.get("r"))
        if item.scene() is self:
            self.removeItem(item)
        animation.deleteLater()
        self._start_queued_visuals()
        self._refresh_all_art()

    def _refresh_defeated_entity(self, player: int, index: int,
                                 snapshot: dict | None = None) -> None:
        item = self.cards.get(("shiki", player, index))
        if item is None or self.game is None:
            return
        shiki = self.game.state.players[player].shikigami[index]
        form_id = (snapshot["form"] if snapshot is not None and "form" in snapshot
                   else shiki.form.id if shiki.form is not None else None)
        form = self.db.cards[form_id] if form_id is not None else None
        item.set_art(entity_pixmap(
            shiki, self.db, seat=index, form=form, cache_context={}, height=210,
            show_defeated_countdown=not self.defeat_countdown_hidden(player, index),
            snapshot=snapshot))
        item._render_signature = None
        item.update()

    def _sync_entity_art(self, item: BattleCardItem, shiki, seat: int, form,
                         art_context: dict) -> None:
        show_defeated_countdown = not self.defeat_countdown_hidden(item.player, seat)
        signature = _entity_render_signature(
            shiki, form, seat, show_defeated_countdown, self.theme)
        if getattr(item, "_render_signature", None) == signature:
            return
        pixmap = entity_pixmap(
            shiki, self.db, seat=seat, form=form, cache_context=art_context, height=210,
            show_defeated_countdown=show_defeated_countdown)
        item.set_art(pixmap)
        item._render_signature = (
            signature if pixmap is not None and not pixmap.isNull() else None)

    def _refresh_all_art(self) -> None:
        """动画队列清空后统一更新数值与卡图，避免结算状态抢先显示。"""
        if (self.game is None or self._visual_animations or self._visual_queue
                or self._move_animations):
            return
        art_context = {}
        for pi, player in enumerate(self.game.state.players):
            player_item = self.cards.get(("player", pi))
            if player_item is not None:
                player_item.health = player.health
                player_item.max_health = player.max_health
                player_item.shield = player.shield
                player_item.orb = min(4, player.orb)
                player_item.assaults_left = player.assaults_left
                player_item.inspire_power = sum(
                    boost.get("power", 0) for boost in player.assault_boosts)
                player_item.inspire_shield = sum(
                    boost.get("shield", 0) for boost in player.assault_boosts)
                player_item.health_color = self._player_health_color(player)
                player_item.update()
            for index, shiki in enumerate(player.shikigami):
                if shiki.despawned:
                    continue
                item = self.cards.get(("shiki", pi, index))
                if item is None:
                    continue
                form = self.db.cards[shiki.form.id] if shiki.form is not None else None
                self._sync_entity_art(item, shiki, index, form, art_context)
                item.update()
        self._sync_focus()
        self.animations_settled.emit()

    def show_usage_options(self, options: list[dict], card_defs: list) -> None:
        self.clear_usage_options()
        width = (len(options) * MULLIGAN_HAND_SIZE.width()
                 + max(0, len(options) - 1) * 16)
        art_context = {}
        for index, (option, cdef) in enumerate(zip(options, card_defs)):
            x = (self.layout_width - width) / 2 + index * (MULLIGAN_HAND_SIZE.width() + 16)
            item = BattleCardItem(("usage", option["id"]), size=MULLIGAN_HAND_SIZE)
            item.cdef = cdef
            item.payload = option["id"]
            item.playable = option["ok"]
            item.setOpacity(1 if option["ok"] else 0.6)
            burst = option["energy"] if type(option["energy"]) is int and option["energy"] > 0 \
                else None
            item.set_art(card_pixmap(cdef, self.db, cache_context=art_context,
                                     height=MULLIGAN_HAND_SIZE.height(), burst=burst))
            item.setPos(x, 280)
            item.setZValue(DRAG_Z + 15)
            item.text_color = QColor(self.text_color)
            self.addItem(item)
            self.usage_items.append(item)

            energy = f"　能量 {option['energy']}" if option["energy"] else ""
            reason = "" if option["ok"] else f"\n不可用：{option['reason'] or '当前不可用'}"
            label = QGraphicsTextItem(f"{option['label']}　鬼火 {option['cost']}{energy}{reason}")
            label.setFont(QFont("Microsoft YaHei", 12))
            label.setDefaultTextColor(QColor(self.text_color))
            label.setTextWidth(MULLIGAN_HAND_SIZE.width())
            label.setPos(x, 280 + MULLIGAN_HAND_SIZE.height() + 8)
            label.setZValue(DRAG_Z + 16)
            self.addItem(label)
            self.usage_labels.append(label)

    def clear_usage_options(self) -> None:
        for item in (*self.usage_items, *self.usage_labels):
            if item.scene() is self:
                self.removeItem(item)
        self.usage_items.clear()
        self.usage_labels.clear()

    def reset_animations(self) -> None:
        self.clear_usage_options()
        for animation in self._move_animations.values():
            animation.stop()
            animation.deleteLater()
        self._move_animations.clear()
        for animation in self._card_use_animations:
            animation.stop()
            animation.deleteLater()
        self._card_use_animations.clear()
        for item in self._card_use_items.values():
            if item.scene() is self:
                self.removeItem(item)
        self._card_use_items.clear()
        self._card_use_sources.clear()
        for animation in self._visual_animations:
            animation.stop()
            animation.deleteLater()
        self._visual_animations.clear()
        for item in self._visual_items.values():
            if item.scene() is self:
                self.removeItem(item)
        self._visual_items.clear()
        self._visual_events.clear()
        self._visual_queue.clear()
        for item in (*self.cards.values(), *self.deck_backs.values()):
            item._render_signature = None
        for key, item in self.cards.items():
            if key[0] == "hand":
                item.show()
        self._defeat_visuals.clear()
        self._hand_animation_cache.clear()
        self._animation_timeline = None
        self.inputs_open = False
        self.enemy_cardback = None
        self.game = None

    def clear_hands(self) -> None:
        self.drag_controller.cancel()
        self.reset_animations()
        self.mulligan_uid = None
        self.mulligan_selected.emit(None)
        for key, item in list(self.cards.items()):
            if key[0] == "hand":
                self.removeItem(item)
                del self.cards[key]

    @staticmethod
    def _player_health_color(player) -> str:
        if player.health < player.max_health:
            return "red"
        return "green" if player.max_health > 30 else "white"

    def sync_state(self, game, viewer, hand_info, inputs_open, center_hand=False,
                   pending_entries=None, play_pending=True) -> None:
        previous_game = self.game
        preserve_drag = self.drag_controller.dragged and viewer == self.viewer
        if previous_game is not None and viewer != self.viewer:
            self.reset_animations()
            previous_game = None
        previous_timeline = self._animation_timeline
        timeline = game.state.timeline
        if pending_entries is not None:
            online_entries = list(pending_entries)
        else:
            online_entries = []
            if (previous_game is not None and previous_game is not game
                    and previous_timeline is not None
                    and timeline[:len(previous_timeline)] == previous_timeline):
                online_entries = timeline[len(previous_timeline):]
        structured_moves = {(entry["p"], entry["s"]): entry.get("zone")
                            for entry in online_entries if entry.get("v") == "move"}
        pending_hand = {entry["u"]: entry for entry in online_entries
                        if entry.get("k") == "v" and entry.get("v") == "hand"}
        defer_art = bool(online_entries or self.visual_busy or preserve_drag)
        self._animation_timeline = list(timeline)
        self.game = game
        self.phase = game.state.phase
        self.viewer = viewer
        self.center_hand = center_hand
        self.inputs_open = inputs_open
        self.game_over = game.state.winner is not None
        if not preserve_drag:
            self.drag_controller.cancel()
        positions = layout_positions(game, viewer, center_hand=center_hand,
                                     scene_width=self.layout_width)
        self._hand_animation_cache = {
            key[1]: (QPointF(item.pos()), item.pixmap, QSizeF(item.size), item.revealed)
            for key, item in self.cards.items() if key[0] == "hand"
        }
        art_context = {}
        self._loading_done = 0
        self._loading_total = sum(
            sum(not shiki.despawned for shiki in player.shikigami) + len(player.hand)
            for player in game.state.players)
        self.loading.set_progress(0, self._loading_total)
        expected = {key for key in positions if key[0] in ("hand", "shiki", "player")}
        for key in set(self.cards) - expected:
            item = self.cards.pop(key)
            self._stop_move_animation(item)
            self.removeItem(item)

        for pi, player in enumerate(game.state.players):
            count = min(3, len(player.deck))
            first = 0 if pi == viewer else 3 - count
            visible_indexes = set(range(first, first + count))
            if not player.deck:
                visible_indexes = {0 if pi == viewer else 2}
            for index in range(3):
                deck_key = ("deck_back", pi, index)
                back = self.deck_backs.get(deck_key)
                if index not in visible_indexes:
                    if back is not None:
                        self.removeItem(back)
                        del self.deck_backs[deck_key]
                    continue
                if back is None:
                    back = BattleCardItem(deck_key, size=DECK_BACK_SIZE)
                    back.revealed = False
                    back.setAcceptedMouseButtons(Qt.NoButton)
                    back.setTransformOriginPoint(back.boundingRect().center())
                    self.addItem(back)
                    self.deck_backs[deck_key] = back
                self._sync_deck_back(deck_key, back)
            ref = Ref(player=pi)
            key = ("player", pi)
            item = self.cards.get(key)
            created = item is None
            if item is None:
                item = BattleCardItem(key, size=PLAYER_SIZE)
                self.addItem(item)
                self.cards[key] = item
            item.player = pi
            item.payload = ref
            item.player_name = player.name
            if not defer_art or created:
                item.health = player.health
                item.max_health = player.max_health
                item.shield = player.shield
                item.orb = min(4, player.orb)
                item.orb_display_count = min(4, max(2, player.orb))
                item.orb_overflow = 0
                item.assaults_left = player.assaults_left
                item.inspire_power = sum(boost.get("power", 0)
                                         for boost in player.assault_boosts)
                item.inspire_shield = sum(boost.get("shield", 0)
                                          for boost in player.assault_boosts)
                item.health_color = self._player_health_color(player)
            item.shiki_text = ""
            item.targetable = ref in self.legal_targets
            item.setPos(positions[key])
            item.update()

            for index, shiki in enumerate(player.shikigami):
                if shiki.despawned:
                    continue
                key = ("shiki", pi, index)
                item = self.cards.get(key)
                created = item is None
                if item is None:
                    item = BattleCardItem(key, size=SHIKI_SIZE)
                    self.addItem(item)
                    self.cards[key] = item
                definition = self.db.shikigami[shiki.id]
                awaken = "觉醒·" if shiki.awakened is not None else ""
                statuses = [f"护甲/破甲 {shiki.shield}"]
                if shiki.countdown is not None:
                    statuses.append(f"倒计时 {shiki.countdown}")
                item.shiki_text = (
                    f"{awaken}{definition.name}\n等级 {shiki.level}\n"
                    f"力量 {shiki.eff_power}　生命 {shiki.health}/{shiki.max_health}\n"
                    f"{'　'.join(statuses)}"
                )
                form = self.db.cards[shiki.form.id] if shiki.form is not None else None
                item.cdef = form
                item.player = pi
                if not defer_art or created:
                    self._sync_entity_art(item, shiki, index, form, art_context)
                item.index = index
                item.uid = None
                item.payload = Ref(player=pi, shikigami=index)
                item.keywords = list(shiki.keywords + shiki.one_shot_keywords
                                     + shiki.perm_keywords)
                item.border_color = (
                    "blue" if game.state.phase == "battle" and "haste" in item.keywords
                    else "yellow")
                item.legal_targets = (
                    targets.pool_refs(game, "enemy_shikigami", pi, targeted=True)
                    if pi == viewer == game.state.active and "hunt" in item.keywords else [])
                item.targetable = item.payload in self.legal_targets
                item.playable = bool(
                    inputs_open and pi == viewer == game.state.active
                    and ((game.state.phase == "battle"
                          and game.assault_error(pi, index) is None)
                         or (game.state.phase == "upgrade"
                             and index in game.legal_upgrade_indices(pi))))
                if created:
                    item.setPos(positions[key])
                elif previous_game is None:
                    if structured_moves.get((pi, index)) == "ready":
                        item.setPos(combat_position(self.layout_width, pi != viewer))
                    else:
                        item.setPos(positions[key])
                elif not defer_art and (pi, index) not in structured_moves:
                    self._animate_position(item, positions[key])
                item.update()
                self.loading_tick()

        for pi, player in enumerate(game.state.players):
            own = pi == viewer
            for order, card in enumerate(display_hand(
                    game, pi, viewer, preserve_order=center_hand)):
                key = ("hand", card.uid)
                revealed = own or bool(card.mods.get("revealed"))
                cdef = self.db.cards[card.id] if revealed else None
                detail = hand_info.get(card.uid, {}) if own else {}
                owner_seat = card_owner_seat(game, player, cdef) if cdef is not None else None
                item = self.cards.get(key)
                if item is None:
                    item = BattleCardItem(key)
                    self.addItem(item)
                    self.cards[key] = item
                hand_event = pending_hand.get(card.uid)
                if hand_event is not None and getattr(item, "_hand_event", None) is not hand_event:
                    item._hand_event = hand_event
                    item.hide()
                item.cdef = cdef
                centered = (game.state.phase == "mulligan" or center_hand) and own
                item.default_size = QSizeF(MULLIGAN_HAND_SIZE if centered else HAND_SIZE)
                self._sync_hand_art(
                    item, card, cdef, revealed, detail, owner_seat, own, art_context)
                item.revealed = revealed
                item.player = pi
                item.index = None
                item.uid = card.uid
                item.payload = card if revealed else None
                item.keywords = list(detail.get("keywords", []))
                usage = detail.get("usage", [])
                legal_usage = [option for option in usage if option["ok"]]
                item.border_color = (
                    "green" if len(legal_usage) > 1 else
                    "blue" if len(legal_usage) == 1 and legal_usage[0]["cost"] == 0
                    else "yellow"
                )
                target_specs = []
                allows_blank = False
                if (own and pi == game.state.active and cdef is not None
                        and game.state.phase == "battle"):
                    for option in usage:
                        if not option["ok"]:
                            continue
                        spec = usage_target(game, pi, cdef, option["id"])
                        if spec.kind == "choose":
                            target_specs.append(spec)
                        else:
                            allows_blank = True
                item.target_required = bool(target_specs) and not allows_blank
                item.legal_targets = []
                for spec in target_specs:
                    for ref in targets.spec_pool_refs(game, spec, pi, targeted=True):
                        if ref not in item.legal_targets:
                            item.legal_targets.append(ref)
                item.playable = bool(
                    inputs_open and own
                    and (game.state.phase == "mulligan"
                         or (game.state.phase == "battle"
                             and any(option["ok"] for option in usage))))
                item.targetable = False
                x = positions[key].x() + (0 if centered else item.default_size.width() - item.size.width())
                item.setPos(x, positions[key].y())
                item.setZValue(HAND_Z + order / 1000)
                item.update()
                self.loading_tick()
        if self.phase == "mulligan" or center_hand:
            centered_items = [item for key, item in self.cards.items()
                              if key[0] == "hand" and item.player == viewer]
            if centered_items:
                left = min(item.x() for item in centered_items)
                right = max(item.x() + item.size.width() for item in centered_items)
                offset = (self.layout_width - left - right) / 2
                for item in centered_items:
                    item.setPos(item.x() + offset, item.y())
        for item in self.cards.values():
            item.text_color = QColor(self.text_color)
            item.update()
        own_hand_uids = {card.uid for card in game.state.players[viewer].hand}
        if self.phase != "mulligan" or center_hand or self.mulligan_uid not in own_hand_uids:
            self.mulligan_uid = None
        for key, item in self.cards.items():
            if key[0] == "hand":
                item.setScale(1.08 if key[1] == self.mulligan_uid else 1.0)
                item.update()
        self.mulligan_selected.emit(self.mulligan_uid)
        self._sync_focus()
        for entry in online_entries if play_pending else ():
            if entry.get("k") == "a":
                self.animate_card_use(entry["u"], entry["c"], entry["p"],
                                      response=bool(entry.get("r")))
            elif entry.get("k") == "v":
                self.play_visual_event(entry)
