"""固定坐标对局场景与卡牌图元。"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QLineF, QPointF, QPropertyAnimation, QRectF, QSizeF, Qt, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsObject, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
)

from client.gui.cardart import card_pixmap, entity_pixmap, seat_level_color
from client.gui.loading import LoadingIndicator
from client.gui.portrait import bwpdiy_root
from core import targets
from core.model import Ref

SCENE_WIDTH = 1600
SCENE_HEIGHT = 900
HAND_SIZE = QSizeF(110, 156)
MULLIGAN_HAND_SIZE = QSizeF(180, 255)
DECK_BACK_SIZE = QSizeF(112, 80)
SHIKI_SIZE = QSizeF(148, 210)
PLAYER_SIZE = QSizeF(210, 130)
HAND_Z = 40
SHIKI_Z = 10
FOCUS_Z = 80
DRAG_Z = 100
ENEMY_HAND_Y = -78
OWN_HAND_Y = 822


def card_owner_seat(game, player, cdef) -> int | None:
    owners = {sid for sid in (cdef.shikigami, cdef.shikigami2) if sid is not None}
    for index, shiki in enumerate(player.shikigami):
        if shiki.home_slot is None:
            continue
        identities = {shiki.id, shiki.transform_owner, shiki.ext.get("replace_owner")}
        if owners & identities:
            return index
    return None


def display_hand(game, pi: int, viewer: int):
    """敌方与调度保留入手序；常态己方仅显示排序，不改写 hand_seq。"""
    player = game.state.players[pi]
    if pi != viewer or game.state.phase == "mulligan":
        return sorted(player.hand, key=lambda card: card.hand_seq)

    def sort_key(card):
        cdef = game.db.cards[card.id]
        seat = card_owner_seat(game, player, cdef)
        return (len(player.shikigami) if seat is None else seat,
                cdef.level or 0, card.id, card.hand_seq)

    return sorted(player.hand, key=sort_key)


def layout_positions(game=None, viewer: int = 0) -> dict[tuple, QPointF]:
    positions = {
        ("phase",): QPointF(65, 422),
        ("menu",): QPointF(1352, 16),
        ("log",): QPointF(1, 422),
        ("end_turn",): QPointF(1493, 400),
        ("enemy_hand_label",): QPointF(1240, 350),
        ("enemy_deck",): QPointF(1530, 228),
        ("own_deck",): QPointF(1530, 608),
        ("hand_caption",): QPointF(1240, 486),
        ("ready",): QPointF(1328, 435),
        ("mulligan",): QPointF(730, 610),
        ("turn_order",): QPointF(1, 340),
        ("target_label",): QPointF(1120, 400),
        ("cancel_target",): QPointF(1120, 440),
        ("default_target",): QPointF(1120, 480),
        ("error",): QPointF(1, 540),
        ("result_banner",): QPointF(500, 350),
        ("result_back",): QPointF(730, 470),
        ("upgrade_phase",): QPointF(411, 422),
    }
    for pi in (0, 1):
        top = pi != viewer
        positions[("player", pi)] = QPointF(1, 4 if top else 766)
        for index in range(3):
            positions[("deck_back", pi, index)] = QPointF(
                1376 + index * 18, (220 + index * 4) if top else (600 - index * 4))
    if game is None:
        return positions

    arc = (120, 86, 86, 120)
    ready_x = (196, 421, 871, 1096)
    for pi, player in enumerate(game.state.players):
        top = pi != viewer
        for index, _shiki in enumerate(player.shikigami):
            if player.combat_index == index:
                position = QPointF(646, 220 if top else 460)
            else:
                position = QPointF(ready_x[index], arc[index] if top else (690 - arc[index]))
            positions[("shiki", pi, index)] = position
        cards = display_hand(game, pi, viewer)
        centered = game.state.phase == "mulligan" and pi == viewer
        if centered:
            width = (len(cards) * MULLIGAN_HAND_SIZE.width()
                     + max(0, len(cards) - 1) * 16)
        spacing = 70 if len(cards) <= 8 else 490 / (len(cards) - 1)
        right = SCENE_WIDTH - 1
        for order, card in enumerate(cards):
            if centered:
                x = (SCENE_WIDTH - width) / 2 + order * (MULLIGAN_HAND_SIZE.width() + 16)
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
        self.setAcceptedMouseButtons(Qt.LeftButton)
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

    def _paint_operation_glow(self, painter: QPainter, rect: QRectF) -> None:
        colors = {"yellow": "#f3d56b", "blue": "#75b9d1", "green": "#78c896"}
        color = QColor("#f3d56b" if self.dragging or self.targetable
                       else colors[self.border_color])
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
        avatar = QRectF(rect.left() + 2, rect.top() + 2, 96, 96)
        painter.setPen(QPen(QColor("#d9b96a"), 3))
        painter.setBrush(QColor(45, 65, 82, 235))
        painter.drawEllipse(avatar)
        painter.setPen(QColor("#f7f0dc"))
        font = painter.font()
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(avatar, Qt.AlignCenter, self.player_name[:1])

        hp = QRectF(avatar.right() - 48, avatar.bottom() - 24, 58, 28)
        painter.setPen(QPen(QColor("#d9b96a"), 1))
        painter.setBrush(QColor(170, 55, 60, 245))
        painter.drawRoundedRect(hp, 12, 12)
        font.setPointSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#fff4e0"))
        painter.drawText(hp, Qt.AlignCenter, f"♥{self.health}")
        if self.shield:
            shield = QRectF(hp.left(), hp.top() - 22, 58, 22)
            painter.setBrush(QColor(65, 95, 115, 240))
            painter.drawRoundedRect(shield, 9, 9)
            painter.drawText(shield, Qt.AlignCenter, f"护{self.shield}")

        side_x = avatar.right() + 8
        orb_size = 14
        for index in range(self.orb_display_count):
            orb = QRectF(side_x + index * (orb_size + 4), avatar.top() + 6,
                         orb_size, orb_size)
            painter.setPen(QPen(QColor("#d9b96a"), 1))
            painter.setBrush(QColor("#d9b96a") if index < self.orb
                             else QColor(35, 40, 45, 180))
            painter.drawEllipse(orb)
        if self.orb_overflow:
            painter.setPen(self.text_color)
            painter.drawText(QRectF(side_x + 76, avatar.top() + 4, 34, 20),
                             Qt.AlignLeft | Qt.AlignVCenter, f"×{self.orb}")
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
        if self.key[0] != "usage":
            self.scene().drag_controller.press(self, event.scenePos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.key[0] != "usage":
            self.scene().drag_controller.move(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.key[0] == "usage":
            if self.playable:
                self.scene().usage_selected.emit(self.payload)
        else:
            self.scene().drag_controller.release(event.scenePos())
        event.accept()


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
            else:
                if (kind == "player" and item.payload not in scene.legal_targets
                        and not QRectF(2, 2, 96, 96).contains(item.mapFromScene(scene_pos))):
                    return
                scene.detail_requested.emit(kind, item.payload)
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

    def _start_drag(self) -> None:
        item = self.item
        self.scene._stop_move_animation(item)
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
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_scene()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.fit_scene()


class BattleScene(QGraphicsScene):
    detail_requested = Signal(str, object)
    action_requested = Signal(dict)
    mulligan_selected = Signal(object)
    usage_selected = Signal(object)

    def __init__(self, db):
        super().__init__(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.db = db
        self.game = None
        self.cards: dict[tuple, BattleCardItem] = {}
        self._move_animations: dict[BattleCardItem, QPropertyAnimation] = {}
        self._card_use_animations: list[QVariantAnimation] = []
        self._card_use_items: dict[QVariantAnimation, BattleCardItem] = {}
        self._card_use_sources: dict[QVariantAnimation, dict] = {}
        self._hand_animation_cache: dict[int, tuple] = {}
        self._animation_timeline: list[dict] | None = None
        self.usage_items: list[BattleCardItem] = []
        self.usage_labels: list[QGraphicsTextItem] = []
        self.deck_backs: dict[tuple, BattleCardItem] = {}
        self.upgrade_badges: dict[int, QGraphicsPixmapItem] = {}
        self.phase = None
        self.viewer = 0
        self.inputs_open = False
        self.game_over = False
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

    def set_text_color(self, color: str) -> None:
        self.text_color = color
        for item in self.cards.values():
            item.text_color = QColor(color)
            item.update()
        for item in (self.banner_item, self.loading_item, *self.usage_labels):
            item.setDefaultTextColor(QColor(color))

    def show_banner(self, text: str, duration: int = 900) -> None:
        self.banner_item.setPlainText(text)
        rect = self.banner_item.boundingRect()
        self.banner_item.setPos((SCENE_WIDTH - rect.width()) / 2,
                                (SCENE_HEIGHT - rect.height()) / 2)
        self.banner_item.setScale(0.85)
        self.banner_item.setOpacity(0)
        self.banner_item.show()
        self._banner_frame = 0
        self._banner_frames = max(1, round(duration / self.banner_timer.interval()))
        self.banner_timer.start()

    def _advance_banner(self) -> None:
        if not self._banner_frames:
            self.hide_banner()
            return
        self._banner_frame += 1
        progress = self._banner_frame / self._banner_frames
        self.banner_item.setScale(0.85 + 0.15 * min(1, progress * 2))
        opacity = min(1, progress * 4) if progress < 0.75 else (1 - progress) * 4
        self.banner_item.setOpacity(max(0, opacity))
        if progress >= 1:
            self.hide_banner()

    def hide_banner(self) -> None:
        self.banner_timer.stop()
        self._banner_frame = self._banner_frames = 0
        self.banner_item.hide()

    def show_loading(self, prefix: str) -> None:
        self.loading.start(prefix)
        rect = self.loading_item.boundingRect()
        self.loading_item.setPos((SCENE_WIDTH - rect.width()) / 2,
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
        proxy.setPos(layout_positions()[key])
        proxy.setZValue(60)
        return proxy

    def select_mulligan(self, uid: int) -> None:
        self.mulligan_uid = uid
        for key, item in self.cards.items():
            if key[0] == "hand":
                item.setScale(1.08 if key[1] == uid else 1.0)
                item.update()
        self.mulligan_selected.emit(uid)

    def set_focus(self, items) -> None:
        """用带孔洞的暗色遮罩突出指定图元，其余画面统一压暗。"""
        path = QPainterPath()
        path.addRect(self.sceneRect())
        for item in items:
            path.addRect(item.sceneBoundingRect())
        path.setFillRule(Qt.OddEvenFill)
        self.focus_overlay.setPath(path)
        self.focus_overlay.show()

    def clear_focus(self) -> None:
        self.focus_overlay.hide()
        self.focus_overlay.setPath(QPainterPath())

    def _sync_focus(self) -> None:
        if self.drag_controller.dragged:
            return
        if self.phase == "upgrade":
            items = [item for key, item in self.cards.items()
                     if key[0] == "shiki" and self.inputs_open and item.playable]
            if items:
                self.set_focus(items)
            else:
                self.clear_focus()
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

    def _stop_move_animation(self, item: BattleCardItem) -> None:
        animation = self._move_animations.pop(item, None)
        if animation is not None:
            animation.stop()
            animation.deleteLater()

    def _animate_position(self, item: BattleCardItem, target: QPointF) -> None:
        self._stop_move_animation(item)
        start = QPointF(item.pos())
        if start == target:
            item.setPos(target)
            return
        animation = QPropertyAnimation(item, b"pos", self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Linear)
        animation.setStartValue(start)
        animation.setEndValue(QPointF(target))
        self._move_animations[item] = animation
        animation.finished.connect(
            lambda item=item, animation=animation: self._finish_move_animation(item, animation))
        animation.start()

    def _finish_move_animation(self, item: BattleCardItem, animation) -> None:
        if self._move_animations.get(item) is animation:
            del self._move_animations[item]
            animation.deleteLater()

    def animate_card_use(self, uid: int, card_id: int, player: int) -> None:
        cdef = self.db.cards[card_id]
        cached = self._hand_animation_cache.get(uid)
        if cached is None:
            source_pos = QPointF(
                SCENE_WIDTH - HAND_SIZE.width() - 1,
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
        self._card_use_items[animation] = item
        self._card_use_sources[animation] = {
            "source_pos": source_pos,
            "source_size": source_size,
            "big_pos": QPointF(70, (SCENE_HEIGHT - big_size.height()) / 2),
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
        item = self._card_use_items.pop(animation)
        self._card_use_sources.pop(animation, None)
        if item.scene() is self:
            self.removeItem(item)
        animation.deleteLater()

    def show_usage_options(self, options: list[dict], card_defs: list) -> None:
        self.clear_usage_options()
        width = (len(options) * MULLIGAN_HAND_SIZE.width()
                 + max(0, len(options) - 1) * 16)
        art_context = {}
        for index, (option, cdef) in enumerate(zip(options, card_defs)):
            x = (SCENE_WIDTH - width) / 2 + index * (MULLIGAN_HAND_SIZE.width() + 16)
            item = BattleCardItem(("usage", option["id"]), size=MULLIGAN_HAND_SIZE)
            item.cdef = cdef
            item.payload = option["id"]
            item.playable = option["ok"]
            item.setOpacity(1 if option["ok"] else 0.6)
            item.set_art(card_pixmap(cdef, self.db, cache_context=art_context,
                                     height=MULLIGAN_HAND_SIZE.height()))
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
        self._hand_animation_cache.clear()
        self._animation_timeline = None
        self.inputs_open = False
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

    def sync_state(self, game, viewer, hand_info, inputs_open) -> None:
        previous_game = self.game
        if previous_game is not None and viewer != self.viewer:
            self.reset_animations()
            previous_game = None
        previous_timeline = self._animation_timeline
        timeline = game.state.timeline
        online_entries = []
        if (previous_game is not None and previous_game is not game
                and previous_timeline is not None
                and timeline[:len(previous_timeline)] == previous_timeline):
            online_entries = timeline[len(previous_timeline):]
        self._animation_timeline = list(timeline)
        self.game = game
        self.phase = game.state.phase
        self.viewer = viewer
        self.inputs_open = inputs_open
        self.game_over = game.state.winner is not None
        self.drag_controller.cancel()
        positions = layout_positions(game, viewer)
        self._hand_animation_cache = {
            key[1]: (QPointF(item.pos()), item.pixmap, QSizeF(item.size), item.revealed)
            for key, item in self.cards.items() if key[0] == "hand"
        }
        art_context = {}
        self._loading_done = 0
        self._loading_total = sum(len(player.shikigami) + len(player.hand)
                                  for player in game.state.players)
        self.loading.set_progress(0, self._loading_total)
        expected = {key for key in positions if key[0] in ("hand", "shiki", "player")}
        for key in set(self.cards) - expected:
            item = self.cards.pop(key)
            self._stop_move_animation(item)
            self.removeItem(item)

        for pi, player in enumerate(game.state.players):
            for index in range(3):
                deck_key = ("deck_back", pi, index)
                back = self.deck_backs.get(deck_key)
                if not player.deck:
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
                back.setPos(positions[deck_key])
                rotation = -15 + index * 5
                back.setRotation(rotation if pi != viewer else -rotation)
                back.setZValue(20 + index)
                back.update()
            ref = Ref(player=pi)
            key = ("player", pi)
            item = self.cards.get(key)
            if item is None:
                item = BattleCardItem(key, size=PLAYER_SIZE)
                self.addItem(item)
                self.cards[key] = item
            item.player = pi
            item.payload = ref
            item.player_name = player.name
            item.health = player.health
            item.max_health = player.max_health
            item.shield = player.shield
            item.orb = player.orb
            item.orb_display_count = min(4, max(2, player.orb))
            item.orb_overflow = max(0, player.orb - 4)
            item.assaults_left = player.assaults_left
            item.inspire_power = sum(boost.get("power", 0)
                                     for boost in player.assault_boosts)
            item.inspire_shield = sum(boost.get("shield", 0)
                                      for boost in player.assault_boosts)
            item.shiki_text = ""
            item.targetable = ref in self.legal_targets
            item.setPos(positions[key])
            item.update()

            for index, shiki in enumerate(player.shikigami):
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
                pixmap = entity_pixmap(shiki, self.db, seat=index, form=form,
                                       cache_context=art_context, height=210)
                item.set_art(pixmap)
                item.player = pi
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
                if created or previous_game is None:
                    item.setPos(positions[key])
                else:
                    self._animate_position(item, positions[key])
                item.update()
                self.loading_tick()

        for pi, player in enumerate(game.state.players):
            own = pi == viewer
            for order, card in enumerate(display_hand(game, pi, viewer)):
                key = ("hand", card.uid)
                revealed = own or bool(card.mods.get("revealed"))
                cdef = self.db.cards[card.id] if revealed else None
                detail = hand_info.get(card.uid, {}) if own else {}
                owner_seat = card_owner_seat(game, player, cdef) if cdef is not None else None
                pixmap = (card_pixmap(cdef, self.db, display=detail.get("render"),
                                      level_color=seat_level_color(owner_seat),
                                      cache_context=art_context,
                                      height=255 if game.state.phase == "mulligan" and own else 156)
                          if cdef is not None else None)
                item = self.cards.get(key)
                if item is None:
                    item = BattleCardItem(key)
                    self.addItem(item)
                    self.cards[key] = item
                item.cdef = cdef
                centered = game.state.phase == "mulligan" and own
                item.default_size = QSizeF(MULLIGAN_HAND_SIZE if centered else HAND_SIZE)
                item.set_art(pixmap)
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
        if self.phase == "mulligan":
            centered_items = [item for key, item in self.cards.items()
                              if key[0] == "hand" and item.player == viewer]
            if centered_items:
                left = min(item.x() for item in centered_items)
                right = max(item.x() + item.size.width() for item in centered_items)
                offset = (SCENE_WIDTH - left - right) / 2
                for item in centered_items:
                    item.setPos(item.x() + offset, item.y())
        for item in self.cards.values():
            item.text_color = QColor(self.text_color)
            item.update()
        own_hand_uids = {card.uid for card in game.state.players[viewer].hand}
        if self.phase != "mulligan" or self.mulligan_uid not in own_hand_uids:
            self.mulligan_uid = None
        for key, item in self.cards.items():
            if key[0] == "hand":
                item.setScale(1.08 if key[1] == self.mulligan_uid else 1.0)
                item.update()
        self.mulligan_selected.emit(self.mulligan_uid)
        self._sync_focus()
        for entry in online_entries:
            if entry.get("k") == "a":
                self.animate_card_use(entry["u"], entry["c"], entry["p"])
