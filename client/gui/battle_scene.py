"""本地热坐的固定坐标对局场景与卡牌图元。"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsObject, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView,
)

from client.gui.cardart import card_pixmap
from core import targets
from core.model import Ref

SCENE_WIDTH = 1600
SCENE_HEIGHT = 900
HAND_SIZE = QSizeF(110, 156)
SHIKI_SIZE = QSizeF(148, 210)
PLAYER_SIZE = QSizeF(210, 130)
HAND_Z = 40
SHIKI_Z = 10
DRAG_Z = 100


def layout_positions(game=None, viewer: int = 0) -> dict[tuple, QPointF]:
    positions = {
        ("phase",): QPointF(40, 30),
        ("menu",): QPointF(1450, 186),
        ("log",): QPointF(20, 420),
        ("end_turn",): QPointF(1460, 400),
        ("enemy_hand_label",): QPointF(1240, 190),
        ("enemy_deck",): QPointF(1460, 290),
        ("own_deck",): QPointF(1460, 620),
        ("hand_caption",): QPointF(1130, 696),
        ("ready",): QPointF(1420, 688),
        ("target_label",): QPointF(1120, 400),
        ("cancel_target",): QPointF(1120, 440),
        ("default_target",): QPointF(1120, 480),
        ("error",): QPointF(20, 730),
        ("result_banner",): QPointF(500, 350),
        ("result_back",): QPointF(730, 470),
    }
    for pi in (0, 1):
        top = pi != viewer
        positions[("player", pi)] = QPointF(30, 220 if top else 540)
        positions[("player_label", pi)] = QPointF(30, 220 if top else 540)
        positions[("player_fields", pi)] = QPointF(30, 310 if top else 630)
        positions[("player_detail", pi)] = QPointF(30, 350 if top else 670)
    if game is None:
        return positions

    arc = (24, 0, 0, 24)
    for pi, player in enumerate(game.state.players):
        top = pi != viewer
        for index, _shiki in enumerate(player.shikigami):
            if player.combat_index == index:
                position = QPointF(726, 234 if top else 444)
            else:
                position = QPointF(440 + index * 170,
                                   arc[index] if top else (690 - arc[index]))
            positions[("shiki", pi, index)] = position
        cards = sorted(player.hand, key=lambda card: card.hand_seq)
        spacing = min(70, 460 / max(len(cards) - 1, 1))
        right = SCENE_WIDTH - 32
        for order, card in enumerate(cards):
            x = right - HAND_SIZE.width() - spacing * (len(cards) - 1 - order)
            positions[("hand", card.uid)] = QPointF(x, 16 if top else 728)
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
    def __init__(self, key, cdef=None, pixmap=None, revealed=True,
                 size=HAND_SIZE, shiki_text=""):
        super().__init__()
        self.key = key
        self.cdef = cdef
        self.pixmap = pixmap
        self.revealed = revealed
        self.size = QSizeF(size)
        self.shiki_text = shiki_text
        self.player = self.index = self.uid = None
        self.payload = cdef if cdef is not None else key
        self.keywords: list[str] = []
        self.legal_targets: list[Ref] = []
        self.target_required = False
        self.targetable = False
        self.playable = False
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(SHIKI_Z if key[0] in ("shiki", "player") else HAND_Z)

    def boundingRect(self):
        return QRectF(QPointF(0, 0), self.size)

    def paint(self, painter: QPainter, option, widget=None):
        del option, widget
        rect = self.boundingRect()
        if self.pixmap is not None and not self.pixmap.isNull():
            painter.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
            if self.key[0] == "shiki":
                badge = QRectF(3, rect.height() - 35, rect.width() - 6, 31)
                painter.setPen(QPen(QColor("#d9b96a"), 1))
                painter.setBrush(QColor(20, 25, 30, 210))
                painter.drawRect(badge)
                painter.drawText(badge, Qt.AlignCenter, self._stat_badge())
        elif self.key[0] == "player" or (self.key[0] == "shiki" and self.cdef is None):
            painter.setPen(QPen(QColor("#d9b96a"), 3))
            painter.setBrush(QColor(45, 55, 65, 220))
            painter.drawRect(rect)
            painter.setPen(QColor("#f2e4bd"))
            painter.drawText(rect.adjusted(5, 5, -5, -5),
                             Qt.TextWordWrap | Qt.AlignCenter, self.shiki_text)
        elif self.key[0] == "hand" and not self.revealed:
            painter.setPen(QPen(QColor("#d9b96a"), 2))
            painter.setBrush(QColor(45, 55, 65, 240))
            painter.drawRect(rect)
            painter.drawRect(rect.adjusted(7, 7, -7, -7))
        else:
            return
        if self.targetable or self.playable:
            color = QColor("#f3d56b") if self.targetable else QColor("#75b9d1")
            painter.setPen(QPen(color, 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(2, 2, -2, -2))

    def _stat_badge(self) -> str:
        for line in self.shiki_text.splitlines():
            if "力量" in line and "生命" in line:
                return line
        return ""

    def mousePressEvent(self, event) -> None:
        self.scene().drag_controller.press(self, event.scenePos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.scene().drag_controller.move(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.scene().drag_controller.release(event.scenePos())
        event.accept()


class BattleAnimationLayer:
    def __init__(self, scene):
        self.scene = scene
        self.items = []

    @property
    def drag_ghost(self):
        return self.scene.drag_controller.drag_ghost

    @property
    def drag_arrow(self):
        return self.scene.drag_controller.drag_arrow

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
        if not self.scene.inputs_open and not item.targetable:
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
        can_drag = item.playable and (
            (kind == "shiki" and self.scene.phase == "battle")
            or (kind == "hand" and self.scene.phase in ("battle", "mulligan")))
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
            if (kind == "shiki" and scene.phase == "upgrade" and item.playable
                    and item.player == scene.viewer):
                scene.action_requested.emit({"op": "upgrade", "index": item.index})
            else:
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
            if scene.phase == "mulligan":
                scene.action_requested.emit({"op": "mulligan", "uid": item.uid})
            elif target_ref in item.legal_targets:
                scene.action_requested.emit({"op": "play_card", "uid": item.uid,
                                             "target": target_ref})
            elif not item.target_required and (target_ref is None or not item.legal_targets):
                scene.action_requested.emit({"op": "play_card", "uid": item.uid})

    def cancel(self) -> None:
        if self.item is not None:
            self.item.setOpacity(1)
        self.item = None
        self.dragged = False
        self.scene.animation_layer.clear()
        self.drag_ghost = None
        self.drag_arrow = None

    def _start_drag(self) -> None:
        item = self.item
        if item.pixmap is not None and not item.pixmap.isNull():
            pixmap = item.pixmap.scaled(item.size.toSize(), Qt.IgnoreAspectRatio,
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
        item.setOpacity(0.35)
        self.dragged = True


def _assault_playable(game, pi: int, index: int) -> bool:
    player = game.state.players[pi]
    shiki = player.shikigami[index]
    if not shiki.in_play or getattr(game.db.shikigami[shiki.id], "no_attack", False):
        return False
    if player.is_stunned or shiki.stuns:
        return False
    energy = player.ext.get("energy_assault")
    energy_assault = bool(
        energy and player.assaults_left < 1 and player.orb < 1
        and energy.get("holder") == [pi, index]
        and game._can_pay_energy(player, index, int(energy.get("cost", 3))))
    if player.assaults_left < 1 and not energy_assault:
        return False
    if not game._has_keyword(shiki, "enraged") and any(
            game._has_keyword(other, "enraged") and other.in_play
            for j, other in enumerate(player.shikigami) if j != index):
        return False
    if (player.combat_index != index and not game._has_keyword(shiki, "remote")
            and game._combat_zone_locked(pi)):
        return False
    if energy_assault or game._has_keyword(shiki, "haste"):
        return True
    need = 2 if game._has_keyword(shiki, "extra_orb_cost") else 1
    return player.orb >= need


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

    def __init__(self, db):
        super().__init__(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.db = db
        self.cards: dict[tuple, BattleCardItem] = {}
        self.phase = None
        self.viewer = 0
        self.inputs_open = False
        self.legal_targets: list[Ref] = []
        self.menu_item = None
        self.log_item = None
        self.end_turn_item = None
        self.animation_layer = BattleAnimationLayer(self)
        self.drag_controller = BattleDragController(self)

    def add_control(self, widget, key: tuple, size=None):
        if size is not None:
            widget.setFixedSize(*size)
        if widget.inherits("QLabel"):
            widget.setStyleSheet(widget.styleSheet() + "background: transparent;")
        proxy = self.addWidget(widget)
        proxy.setPos(layout_positions()[key])
        proxy.setZValue(60)
        return proxy

    def clear_hands(self) -> None:
        self.drag_controller.cancel()
        for key, item in list(self.cards.items()):
            if key[0] == "hand":
                self.removeItem(item)
                del self.cards[key]

    def sync_state(self, game, viewer, hand_info, inputs_open) -> None:
        self.drag_controller.cancel()
        self.phase = game.state.phase
        self.viewer = viewer
        self.inputs_open = inputs_open
        positions = layout_positions(game, viewer)
        expected = {key for key in positions if key[0] in ("hand", "shiki", "player")}
        for key in set(self.cards) - expected:
            self.removeItem(self.cards.pop(key))

        for pi, player in enumerate(game.state.players):
            ref = Ref(player=pi)
            key = ("player", pi)
            item = self.cards.get(key)
            if item is None:
                item = BattleCardItem(key, size=PLAYER_SIZE)
                self.addItem(item)
                self.cards[key] = item
            item.player = pi
            item.payload = ref
            item.shiki_text = ""
            item.targetable = ref in self.legal_targets
            item.setPos(positions[key])
            item.update()

            for index, shiki in enumerate(player.shikigami):
                key = ("shiki", pi, index)
                item = self.cards.get(key)
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
                item.cdef = None
                item.pixmap = None
                if shiki.form is not None:
                    item.cdef = self.db.cards[shiki.form.id]
                    item.pixmap = card_pixmap(
                        item.cdef, self.db,
                        display={"power": shiki.eff_power, "health": shiki.health})
                item.player = pi
                item.index = index
                item.uid = None
                item.payload = Ref(player=pi, shikigami=index)
                item.keywords = list(shiki.keywords + shiki.one_shot_keywords
                                     + shiki.perm_keywords)
                item.legal_targets = (
                    targets.pool_refs(game, "enemy_shikigami", pi, targeted=True)
                    if pi == viewer == game.state.active and "hunt" in item.keywords else [])
                item.targetable = item.payload in self.legal_targets
                item.playable = bool(
                    inputs_open and pi == viewer == game.state.active
                    and ((game.state.phase == "battle"
                          and _assault_playable(game, pi, index))
                         or (game.state.phase == "upgrade"
                             and index in game.legal_upgrade_indices(pi))))
                item.setPos(positions[key])
                item.update()

        for pi, player in enumerate(game.state.players):
            own = pi == viewer
            for order, card in enumerate(sorted(player.hand, key=lambda c: c.hand_seq)):
                key = ("hand", card.uid)
                revealed = own or bool(card.mods.get("revealed"))
                cdef = self.db.cards[card.id] if revealed else None
                detail = hand_info.get(card.uid, {}) if own else {}
                pixmap = (card_pixmap(cdef, self.db, display=detail.get("render"))
                          if cdef is not None else None)
                item = self.cards.get(key)
                if item is None:
                    item = BattleCardItem(key)
                    self.addItem(item)
                    self.cards[key] = item
                item.cdef = cdef
                item.pixmap = pixmap
                item.revealed = revealed
                item.player = pi
                item.index = None
                item.uid = card.uid
                item.payload = card if revealed else None
                item.keywords = list(detail.get("keywords", []))
                usage = detail.get("usage", [])
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
                item.setPos(positions[key])
                item.setZValue(HAND_Z + order / 1000)
                item.update()
