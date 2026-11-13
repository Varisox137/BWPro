"""对局开局阵容与先后手展示测试。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from client.gui.battle_scene import BattleScene
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _solid(*_args, **_kwargs):
    pixmap = QPixmap(100, 100)
    pixmap.fill(Qt.white)
    return pixmap


def test_opening_preview_uses_shuffled_state_order(qapp, db, make_game, monkeypatch):
    from client.gui import opening

    game = make_game(mulligan=True)
    seen = []
    used = []
    monkeypatch.setattr(opening, "entity_pixmap",
                        lambda shiki, *_args, **_kwargs: seen.append(shiki.id) or _solid())
    monkeypatch.setattr(opening, "ui_pixmap",
                        lambda path, **_kwargs: used.append(path) or _solid())
    pixmap = opening.opening_preview_pixmap(game, 0)
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (1600, 900)
    assert seen == ([shiki.id for shiki in game.state.players[1].shikigami]
                    + [shiki.id for shiki in game.state.players[0].shikigami])
    assert used == ["animations/battle_preview.png"]


def test_opening_order_uses_actual_first_player_and_viewer(qapp, make_game, monkeypatch):
    from client.gui import opening

    game = make_game(mulligan=True)
    for active in (0, 1):
        game.state.active = active
        used = []
        monkeypatch.setattr(opening, "ui_pixmap",
                            lambda path, **_kwargs: used.append(path) or _solid())
        pixmap = opening.opening_order_pixmap(game, 0)
        assert not pixmap.isNull()
        own_first = active == 0
        assert used == [
            "animations/going_second.png" if own_first else "animations/going_first.png",
            "animations/going_first.png" if own_first else "animations/going_second.png",
            "animations/youre_first.png" if own_first else "animations/youre_second.png",
        ]


def test_opening_sequence_uses_six_fade_stages_and_covers_battle(qapp, db, make_game, monkeypatch):
    from client.gui import opening

    monkeypatch.setattr(opening, "entity_pixmap", _solid)
    monkeypatch.setattr(opening, "ui_pixmap", _solid)
    scene = BattleScene(db)
    scene.show_opening_sequence(make_game(mulligan=True), 0)
    assert scene._opening_stage == "preview"
    assert scene._opening_duration == 1000
    assert scene.opening_background.isVisible()
    assert scene.opening_item.opacity() == 0
    assert not scene.opening_accent_item.isVisible()
    expected = ["preview_battle", "preview_out", "order", "order_badge", "order_out", None]
    for stage in expected:
        scene._opening_frame = scene._opening_frames
        scene._advance_opening()
        assert scene._opening_stage == stage
    assert not scene.opening_item.isVisible()
    assert not scene.opening_accent_item.isVisible()
    assert not scene.opening_background.isVisible()


def test_opening_going_cards_scale_to_70_percent(qapp, make_game, monkeypatch):
    from client.gui import opening

    original_scaled = QPixmap.scaled
    calls = []

    def record_scaled(pixmap, *args, **kwargs):
        calls.append(args[:2])
        return original_scaled(pixmap, *args, **kwargs)

    monkeypatch.setattr(QPixmap, "scaled", record_scaled)
    monkeypatch.setattr(opening, "ui_pixmap", _solid)
    assert not opening.opening_order_pixmap(
        make_game(mulligan=True), 0, include_badge=False).isNull()
    assert calls == [(70, 70), (70, 70)]


def test_opening_preview_and_badge_assets_are_not_rescaled(qapp, make_game, monkeypatch):
    from client.gui import opening

    def unexpected_scale(*_args, **_kwargs):
        raise AssertionError("阵容与视角先后手素材不得缩放")

    monkeypatch.setattr(QPixmap, "scaled", unexpected_scale)
    monkeypatch.setattr(QPixmap, "scaledToHeight", unexpected_scale)
    monkeypatch.setattr(opening, "entity_pixmap", _solid)
    monkeypatch.setattr(opening, "ui_pixmap", _solid)
    game = make_game(mulligan=True)
    assert not opening.opening_preview_pixmap(game, 0).isNull()
    assert not opening.opening_order_badge_pixmap(game, 0).isNull()
