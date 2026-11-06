"""对局美术资源、配置与结构化视觉事件测试。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from client.gui.portrait import bwpdiy_root
from client.gui.ui_assets import (
    dice_face, load_gui_settings, named_cardbacks, save_gui_settings, turn_pixmap,
)
from core.model import Ref
from tests import factories as F
from tests.factories import play


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_dice_faces_crop_unfolded_black_die(qapp):
    faces = [dice_face(value) for value in range(1, 7)]
    assert all(face.size().width() == 128 and face.size().height() == 128 for face in faces)
    assert len({face.toImage().cacheKey() for face in faces}) == 6
    unfolded = QPixmap(str(bwpdiy_root() / "assets" / "dice" / "black_open.png"))
    expected_six = unfolded.copy(340, 0, 128, 128)
    assert faces[5].toImage() == expected_six.toImage()


def test_named_cardbacks_and_persistent_defaults(tmp_path):
    root = bwpdiy_root() / "assets" / "cardbacks"
    names = named_cardbacks(root)
    assert "月明风清" in names
    assert "f8694068" not in names
    path = tmp_path / "gui.json"
    assert load_gui_settings(path) == {"own_cardback": "月明风清", "enemy_cardback": "月明风清"}
    save_gui_settings({"own_cardback": "三途花境", "enemy_cardback": "月明风清"}, path)
    assert load_gui_settings(path)["own_cardback"] == "三途花境"


def test_turn_word_art_follows_theme(qapp):
    light = turn_pixmap(True, "light")
    dark = turn_pixmap(True, "dark")
    opponent = turn_pixmap(False, "light")
    assert not light.isNull() and not dark.isNull() and not opponent.isNull()
    assert light.cacheKey() != dark.cacheKey() != opponent.cacheKey()
    expected = QPixmap(str(bwpdiy_root() / "assets" / "misc" / "your_turn_dark.png"))
    assert light.toImage() == expected.toImage()


def test_engine_emits_structured_defeat_and_luck_events(db, make_game):
    game = make_game()
    shiki = game.state.players[0].shikigami[0]
    shiki.health = 0
    game.check_defeated(Ref(player=0, shikigami=0))
    defeat = next(entry for entry in game.state.timeline
                  if entry.get("k") == "v" and entry.get("v") == "defeated")
    assert (defeat["p"], defeat["s"]) == (0, 0)

    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="luck_roll", x=4, then=[])])
    game = make_game()
    game.state.players[0].orb = 9
    play(game, 0, 10010151)
    luck = next(entry for entry in game.state.timeline
                if entry.get("k") == "v" and entry.get("v") == "luck")
    assert luck["p"] == 0 and 1 <= luck["dice"] <= 6
    assert luck["success"] is (luck["dice"] >= 4)
