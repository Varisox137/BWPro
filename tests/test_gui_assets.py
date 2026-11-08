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
    dice_face, end_turn_button_pixmap, load_gui_settings, named_cardbacks,
    save_gui_settings, turn_pixmap, unnamed_misc_images,
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


def test_dice_faces_preserve_six_face_template_frame(qapp):
    faces = [dice_face(value) for value in range(1, 7)]
    assert all(face.size().width() == 128 and face.size().height() == 128 for face in faces)
    assert len({face.toImage().cacheKey() for face in faces}) == 6
    dice_root = bwpdiy_root() / "assets" / "dice"
    template = QPixmap(str(dice_root / "black_6.png")).toImage()
    for value, face in enumerate(faces, 1):
        assert (dice_root / f"black_{value}.png").is_file()
        image = face.toImage()
        for y in range(128):
            for x in range(128):
                if x < 12 or y < 12 or x >= 116 or y >= 116:
                    assert image.pixelColor(x, y) == template.pixelColor(x, y)


def test_named_cardbacks_and_persistent_defaults(tmp_path):
    root = bwpdiy_root() / "assets" / "cardbacks"
    names = named_cardbacks(root)
    assert "月明风清" in names
    assert "f8694068" not in names
    path = tmp_path / "gui.json"
    assert load_gui_settings(path) == {
        "own_cardback": "月明风清", "enemy_cardback": "月明风清",
        "end_turn_background": "", "opponent_turn_background": "", "turn_background": "",
        "end_turn_variant": "golden", "opponent_turn_variant": "golden",
        "defeated_variant": "white", "upgrade_variant": "yellow",
    }
    save_gui_settings({"own_cardback": "三途花境", "enemy_cardback": "月明风清"}, path)
    assert load_gui_settings(path)["own_cardback"] == "三途花境"


def test_end_turn_background_is_optional_and_persistent(qapp, tmp_path, monkeypatch):
    from client.gui import ui_assets

    path = tmp_path / "gui.json"
    monkeypatch.setattr(ui_assets, "gui_settings_path", lambda: path)
    names = unnamed_misc_images()
    assert len(names) > 5 and "immune" not in names
    default = end_turn_button_pixmap(104)
    save_gui_settings({"end_turn_background": names[0]}, path)
    assert load_gui_settings(path)["end_turn_background"] == names[0]
    custom = end_turn_button_pixmap(104)
    assert custom.size() == default.size() and custom.cacheKey() != default.cacheKey()
    save_gui_settings({"end_turn_background": ""}, path)
    assert load_gui_settings(path)["end_turn_background"] == ""
    assert end_turn_button_pixmap(104).toImage() == default.toImage()
    opponent_default = end_turn_button_pixmap(104, opponent=True)
    save_gui_settings({"end_turn_variant": "blue", "opponent_turn_variant": "silver"}, path)
    assert end_turn_button_pixmap(104).toImage() != default.toImage()
    assert end_turn_button_pixmap(104, opponent=True).toImage() != opponent_default.toImage()


def test_turn_word_art_follows_theme(qapp):
    light = turn_pixmap(True, "light")
    dark = turn_pixmap(True, "dark")
    opponent = turn_pixmap(False, "light")
    assert not light.isNull() and not dark.isNull() and not opponent.isNull()
    assert light.cacheKey() != dark.cacheKey() != opponent.cacheKey()
    expected = QPixmap(str(bwpdiy_root() / "assets" / "animations" / "your_turn_dark.png"))
    assert light.toImage() == expected.toImage()


def test_engine_emits_structured_defeat_and_luck_events(db, make_game):
    game = make_game()
    shiki = game.state.players[0].shikigami[0]
    shiki.health = 0
    game.check_defeated(Ref(player=0, shikigami=0))
    defeat = next(entry for entry in game.state.timeline
                  if entry.get("k") == "v" and entry.get("v") == "defeated")
    assert (defeat["p"], defeat["s"]) == (0, 0)
    assert defeat["r"]["defeated"] is True
    assert defeat["r"]["revive_countdown"] == 3

    db.cards[10010151] = F.card(
        10010151, token=True,
        steps=[F.Step(op="luck_roll", x=4, then=[])])
    game = make_game()
    game.state.players[0].orb = 9
    play(game, 0, 10010151)
    luck_events = [entry for entry in game.state.timeline
                   if entry.get("k") == "v" and entry.get("v", "").startswith("luck_")]
    assert [entry["v"] for entry in luck_events] == ["luck_dice", "luck_result"]
    dice, result = luck_events
    assert dice["p"] == 0 and 1 <= dice["dice"] <= 6
    assert result["dice"] == dice["dice"]
    assert result["success"] is (result["dice"] >= 4)


def test_engine_emits_actual_heal_visuals_only(db, make_game):
    game = make_game()
    player = game.state.players[0]
    player.health = 20
    player.shikigami[0].health = 1
    game.heal(Ref(player=0), 5)
    game.heal(Ref(player=0, shikigami=0), 9)
    game.heal(Ref(player=1), 2)  # 满血：实际恢复 0，不播放数值动画
    heals = [entry for entry in game.state.timeline
             if entry.get("k") == "v" and entry.get("v") == "heal"]
    assert [(entry["p"], entry["s"], entry["amount"]) for entry in heals] == [
        (0, None, 5), (0, 0, 3),
    ]


def test_engine_emits_immune_and_upgrade_visuals(db, make_game):
    game = make_game()
    pa, _pb = F.battle_setup(game)
    source = Ref(player=1, shikigami=0)
    pa.shikigami[0].immunities.append({"kind": "effect", "from": "enemy"})
    game.deal_to_shikigami(Ref(player=0, shikigami=0), 3, source)
    pa.immunities.append({"kind": "all", "turn": game.state.turn})
    game.deal_to_player(0, 4, source)
    immunes = [entry for entry in game.state.timeline
               if entry.get("k") == "v" and entry.get("v") == "immune"]
    assert [(entry["p"], entry["s"]) for entry in immunes] == [(0, 0), (0, None)]
    assert pa.shikigami[0].health == 4 and pa.health == 30

    game.state.phase = "upgrade"
    pa.upgrades = 1
    index = game.legal_upgrade_indices(0)[0]
    game.apply({"op": "upgrade", "index": index})
    upgrade = next(entry for entry in game.state.timeline
                   if entry.get("k") == "v" and entry.get("v") == "upgrade")
    assert (upgrade["p"], upgrade["s"]) == (0, index)


def test_engine_emits_damage_visuals_for_shikigami_and_player(db, make_game):
    game = make_game()
    pa, _pb = F.battle_setup(game)
    source = Ref(player=1, shikigami=0)
    game.deal_to_shikigami(Ref(player=0, shikigami=0), 3, source)
    game.deal_to_player(0, 4, source)
    pa.shikigami[0].immunities.append({"kind": "effect", "from": "enemy"})
    game.deal_to_shikigami(Ref(player=0, shikigami=0), 9, source)
    damages = [entry for entry in game.state.timeline
               if entry.get("k") == "v" and entry.get("v") == "damage"]
    assert [(entry["p"], entry["s"], entry["amount"]) for entry in damages] == [
        (0, 0, 3), (0, None, 4),
    ]


def test_combat_movement_and_card_animation_precede_effects(db, make_game):
    game = make_game()
    pa, pb = F.battle_setup(game)
    pb.combat_index = 0
    pa.shikigami[0].health = 1
    pb.shikigami[0].base_power = 10
    pa.shikigami[0].base_power = 1
    game.apply({"op": "assault", "index": 0})
    kinds = [entry["v"] for entry in game.state.timeline if entry.get("k") == "v"]
    assert kinds[:2] == ["assault", "move"]
    assert kinds[-2:] == ["defeated", "move"]
    assert any(entry.get("k") == "l" and "出击" in entry.get("m", "")
               for entry in game.state.timeline)

    cid = 10010153
    db.cards[cid] = F.card(cid, token=True,
                           steps=[F.dmg(1, F.T(kind="all", pool="enemy_player"))])
    game = make_game()
    F.battle_setup(game)
    game.apply({"op": "play_card", "uid": F.give(game, 0, cid).uid})
    animation_index = next(index for index, entry in enumerate(game.state.timeline)
                           if entry.get("k") == "a")
    damage_index = next(index for index, entry in enumerate(game.state.timeline)
                        if entry.get("k") == "v" and entry.get("v") == "damage")
    assert animation_index < damage_index
