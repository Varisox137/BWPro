"""对局开局阵容与先后手的静态画面合成。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap

from client.gui.cardart import entity_pixmap
from client.gui.ui_assets import ui_pixmap

SCENE_WIDTH = 1600
SCENE_HEIGHT = 900


def _draw_shikigami(painter: QPainter, shiki, db, x: float, y: float, seat: int) -> None:
    pixmap = entity_pixmap(shiki, db, seat=seat, height=210)
    rect = QRectF(x, y, 148, 210)
    if pixmap is not None and not pixmap.isNull():
        # 槽位中心固定，素材保持原始像素尺寸。
        rect = QRectF(x + (148 - pixmap.width()) / 2, y,
                      pixmap.width(), pixmap.height())
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
    else:
        painter.setPen(QColor("#d9b96a"))
        painter.setBrush(QColor("#231e3a"))
        painter.drawRect(rect)
        painter.drawText(rect, Qt.AlignCenter, str(shiki.id))


def _draw_player(painter: QPainter, player, center: QPointF, *, enemy: bool) -> None:
    avatar = QRectF(center.x() - 56, center.y() - 56, 112, 112)
    painter.setPen(QColor("#d9b96a"))
    painter.setBrush(QColor(45, 55, 65, 235))
    painter.drawEllipse(avatar)
    painter.setPen(QColor("#f7f0dc"))
    painter.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
    painter.drawText(avatar, Qt.AlignCenter, player.name[:1])
    font = QFont("Microsoft YaHei", 22, QFont.Bold)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    x = (avatar.left() - 20 - metrics.horizontalAdvance(player.name) if enemy
         else avatar.right() + 20)
    path = QPainterPath()
    path.addText(x, center.y() + metrics.ascent() / 2, font, player.name)
    painter.fillPath(path, QColor("#f7f0dc"))


def opening_preview_pixmap(game, viewer: int, scene_width: int = SCENE_WIDTH,
                           include_battle: bool = True) -> QPixmap:
    """按引擎已经随机化的式神顺序绘制双方开局阵容。"""
    canvas = QPixmap(scene_width, SCENE_HEIGHT)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    for player_index, y, row_shift in ((1 - viewer, 40, -180), (viewer, 650, 180)):
        player = game.state.players[player_index]
        center_x = scene_width / 2 + row_shift
        for seat, shiki in enumerate(player.shikigami):
            _draw_shikigami(
                painter, shiki, game.db, center_x + (seat - 1.5) * 168 - 74, y, seat)
        _draw_player(
            painter, player,
            QPointF(scene_width - 230 if player_index != viewer else 230,
                    115 if player_index != viewer else 785),
            enemy=player_index != viewer)
    if include_battle:
        battle = ui_pixmap("animations/battle_preview.png")
        if not battle.isNull():
            painter.drawPixmap(round((scene_width - battle.width()) / 2),
                               round((SCENE_HEIGHT - battle.height()) / 2), battle)
    painter.end()
    return canvas


def opening_battle_pixmap(scene_width: int = SCENE_WIDTH) -> QPixmap:
    """仅绘制原尺寸的中央战斗字样，供独立渐现层使用。"""
    canvas = QPixmap(scene_width, SCENE_HEIGHT)
    canvas.fill(Qt.transparent)
    battle = ui_pixmap("animations/battle_preview.png")
    if not battle.isNull():
        painter = QPainter(canvas)
        painter.drawPixmap(round((scene_width - battle.width()) / 2),
                           round((SCENE_HEIGHT - battle.height()) / 2), battle)
        painter.end()
    return canvas


def opening_order_pixmap(game, viewer: int, scene_width: int = SCENE_WIDTH,
                         include_badge: bool = True) -> QPixmap:
    """在双方空位展示实际先后手，并在中央标明当前视角的先后手。"""
    canvas = QPixmap(scene_width, SCENE_HEIGHT)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    for player_index, center_y in ((1 - viewer, 285), (viewer, 615)):
        first = player_index == game.state.active
        name = "going_first" if first else "going_second"
        card = ui_pixmap(f"animations/{name}.png")
        if not card.isNull():
            painter.drawPixmap(round(scene_width / 2 - card.width() / 2),
                               round(center_y - card.height() / 2), card)
    if include_badge:
        own_first = viewer == game.state.active
        badge = ui_pixmap(f"animations/youre_{'first' if own_first else 'second'}.png")
        if not badge.isNull():
            painter.drawPixmap(round(scene_width / 2 - badge.width() / 2),
                               round(SCENE_HEIGHT / 2 - badge.height() / 2), badge)
    painter.end()
    return canvas


def opening_order_badge_pixmap(game, viewer: int,
                               scene_width: int = SCENE_WIDTH) -> QPixmap:
    """仅绘制原尺寸的当前视角先后手字样，供独立渐现层使用。"""
    canvas = QPixmap(scene_width, SCENE_HEIGHT)
    canvas.fill(Qt.transparent)
    own_first = viewer == game.state.active
    badge = ui_pixmap(f"animations/youre_{'first' if own_first else 'second'}.png")
    if not badge.isNull():
        painter = QPainter(canvas)
        painter.drawPixmap(round(scene_width / 2 - badge.width() / 2),
                           round(SCENE_HEIGHT / 2 - badge.height() / 2), badge)
        painter.end()
    return canvas
