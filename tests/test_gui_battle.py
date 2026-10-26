"""桌面 GUI 本地热坐对战测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel

from client.gui.app import THEMES, MainWindow
from client.gui.battle import DeckSelectDialog, HotseatView, UsageDialog
from client.gui.widgets import CardDetailDialog
from core.model import CardInstance, GameConfig, Ref
from db import deckcode, deckstore
from db.schema import InvocationDef
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture
def view(qapp, db, tmp_path):
    widget = HotseatView(db, store_path=tmp_path / "decks.json")
    widget.timeline_timer.setInterval(0)
    yield widget
    widget.timeline_timer.stop()
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def settle(view):
    while view._handoff_pending or view.timeline_queue:
        if view._handoff_pending:
            view.confirm_handoff()
        if view.timeline_queue:
            view.play_next_timeline()


def log_lines(view):
    return [view.log_list.item(i).text() for i in range(view.log_list.count())]


def scene_items(view, kind, player=None):
    return [item for key, item in view.battle_scene.cards.items()
            if key[0] == kind and (player is None or item.player == player)]


def player_tuple(name="玩家"):
    return name, list(F.TEAM), F.deck_of(*F.TEAM)


def start(view, **kwargs):
    kwargs.setdefault("first", 0)
    kwargs.setdefault("shuffle_team", False)
    kwargs.setdefault("config", GameConfig(auto_skip_upgrade=True))
    view.start_game(player_tuple("玩家A"), player_tuple("玩家B"), seed=7, **kwargs)
    settle(view)


@pytest.fixture(autouse=True)
def isolated_cardart_home(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))


def test_hand_art_preserves_runtime_and_detail(qapp, view, tmp_path, monkeypatch):
    from client.gui import cardart
    from client.gui.widgets import CardWidget
    from tests.test_gui_builder import _cardart_config

    library_dir = tmp_path / "library"
    monkeypatch.setattr(cardart, "library_root", lambda: library_dir)
    cardart.clear_cardart_caches()
    try:
        start(view, mulligan=False)
        card = view.game.state.players[0].hand[0]
        cdef = view.db.cards[card.id]
        _cardart_config(library_dir, cdef.id, cdef.version, "#336699")
        runtime = {"cost": 0, "stats": "手牌运行时唯一标记", "keywords": [],
                   "enhance": 0, "quest": None, "playable": True, "usage": []}
        monkeypatch.setattr(view, "hand_info", lambda: {card.uid: runtime})
        view.refresh()
        settle(view)
        item = view.battle_scene.cards[("hand", card.uid)]
        assert item.cdef is cdef
        assert item.revealed
        assert item.pixmap is not None and not item.pixmap.isNull()

        seen = {}

        def capture_exec(dialog):
            seen["dialog"] = dialog
            return QDialog.Rejected

        monkeypatch.setattr(QDialog, "exec", capture_exec)
        view.show_card_detail(card)
        dialog = seen["dialog"]
        assert not dialog.runtime_label.isHidden()
        assert "手牌运行时唯一标记" in dialog.runtime_label.text()
        detail_card = dialog.findChild(CardWidget)
        assert not detail_card.art_label.pixmap().isNull()
        assert cdef.text != runtime["stats"]
        dialog.close()
    finally:
        cardart.clear_cardart_caches()


def test_startup_only_lists_standard_and_enters_game(qapp, db, tmp_path, view):
    groups = deckcode.group_deck(db, F.TEAM, F.deck_of(*F.TEAM))
    deckstore.save_decks(db, [
        {"name": "标准A", "groups": groups, "env": None},
        {"name": "非标准", "groups": [(F.TEAM[0], [])], "env": None},
        {"name": "标准B", "groups": groups, "env": None},
    ], view.store_path)
    dialog = DeckSelectDialog(db, view.store_path, "玩家A")
    assert [entry["name"] for entry in dialog.entries] == ["标准A", "标准B"]
    assert dialog.selected_entry()["name"] == "标准A"
    dialog.close()

    view.start_from_decks(0, 1, first=0, shuffle_team=False)
    assert view.game is not None
    assert view.game.state.phase == "mulligan"
    assert view.stack.currentWidget() is view.battle_page
    assert len(scene_items(view, "player")) == 2
    assert len(scene_items(view, "shiki")) == 8


def test_perspective_reuses_slots_and_continuous_ellipse(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert not hasattr(view, "seat_label")
    assert len(scene_items(view, "player")) == 2 and len(scene_items(view, "shiki")) == 8
    assert all(not item.shiki_text.startswith(("1.", "2.", "3.", "4."))
               for item in scene_items(view, "shiki"))
    slots = {key: item for key, item in scene.cards.items() if key[0] == "shiki"}
    refs = {key: item.payload for key, item in slots.items()}
    assert scene.cards[("player", 1)].y() < scene.cards[("player", 0)].y()
    assert [scene.cards[("shiki", 1, index)].y() for index in range(4)] == [
        24, 0, 0, 24]
    assert [scene.cards[("shiki", 0, index)].y() for index in range(4)] == [
        666, 690, 690, 666]
    assert [scene.cards[("shiki", 0, index)].x() for index in range(4)] == [
        440, 610, 780, 950]
    view.apply_theme("light", THEMES["light"])
    assert "QLabel#enemyHandBack, QLabel#deckCount" in view.styleSheet()

    view.game.state.active = 1
    view.refresh()
    settle(view)
    assert {key: item for key, item in scene.cards.items() if key[0] == "shiki"} == slots
    assert {key: item.payload for key, item in slots.items()} == refs
    assert scene.cards[("player", 0)].y() < scene.cards[("player", 1)].y()


def test_scene_hand_order_reveal_and_overlay(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    own = view.game.state.players[0]
    enemy = view.game.state.players[1]
    revealed = enemy.hand[1]
    revealed.mods["revealed"] = True
    view.refresh()
    settle(view)

    enemy_items = [scene.cards[("hand", card.uid)] for card in
                   sorted(enemy.hand, key=lambda card: card.hand_seq)]
    assert [item.revealed for item in enemy_items] == [False, True, False, False, False]
    assert enemy_items[1].cdef.id == revealed.id
    assert enemy_items[1].payload is revealed
    assert all(item.cdef is None and item.payload is None for item in
               (enemy_items[0], *enemy_items[2:]))
    assert enemy_items[0].zValue() > scene.cards[("shiki", 1, 0)].zValue()
    assert scene.cards[("hand", own.hand[0].uid)].boundingRect().height() <= 170


def test_scene_twelve_hand_cards_overlap_and_shiki_placeholder(qapp, view):
    start(view, mulligan=False)
    player = view.game.state.players[0]
    player.hand[:] = [card.model_copy(update={"uid": 1000 + i, "hand_seq": i + 1})
                      for i, card in enumerate((player.hand * 3)[:12])]
    view.refresh()
    settle(view)
    items = [view.battle_scene.cards[("hand", card.uid)]
             for card in sorted(player.hand, key=lambda card: card.hand_seq)]
    assert len(items) == 12
    assert items[1].x() < items[0].x() + items[0].boundingRect().width()
    assert items[-1].x() + items[-1].boundingRect().width() <= 1600
    shiki = view.battle_scene.cards[("shiki", 0, 0)]
    assert "力量" in shiki.shiki_text and "生命" in shiki.shiki_text
    assert "等级" in shiki.shiki_text


def test_scene_missing_hand_and_form_art_stays_transparent(qapp, db, view):
    def assert_transparent(item):
        image = QImage(item.size.toSize(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        assert all(image.pixelColor(x, y).alpha() == 0
                   for x in range(image.width()) for y in range(image.height()))

    start(view, mulligan=False)
    hand = view.battle_scene.cards[("hand", view.game.current.hand[0].uid)]
    hand.pixmap = None
    hand.playable = hand.targetable = True
    assert_transparent(hand)

    form_id = 10010151
    db.cards[form_id] = F.card(form_id, name="无图形态", card_type="form")
    view.game.current.shikigami[0].form = CardInstance(uid=10000, id=form_id)
    view.refresh()
    settle(view)
    form = view.battle_scene.cards[("shiki", 0, 0)]
    assert form.pixmap is None
    form.targetable = True
    assert_transparent(form)


def test_battle_window_minimum_height_fits_common_900px_window(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    try:
        win.go("hotseat")
        start(win.pages["hotseat"], mulligan=False)
        win.show()
        qapp.processEvents()
        assert win.minimumSizeHint().height() <= 900
    finally:
        win.close()


def test_scene_cards_and_controls_fit_1600x900(qapp, db, tmp_path, monkeypatch):
    from client.gui import cardart
    from tests.test_gui_builder import _cardart_config

    library_dir = tmp_path / "library"
    monkeypatch.setattr(cardart, "library_root", lambda: library_dir)
    cardart.clear_cardart_caches()
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    try:
        win.go("hotseat")
        view = win.pages["hotseat"]
        start(view, mulligan=False)
        card = view.game.state.players[0].hand[0]
        cdef = db.cards[card.id]
        _cardart_config(library_dir, cdef.id, cdef.version, "#336699")
        view.refresh()
        settle(view)
        win.resize(1600, 900)
        win.show()
        qapp.processEvents()

        scene = view.battle_scene
        assert view.battle_view.scene() is scene
        for item in scene_items(view, "hand"):
            assert scene.sceneRect().contains(item.sceneBoundingRect())
        for proxy in (scene.menu_item, scene.log_item, scene.end_turn_item):
            assert scene.sceneRect().contains(proxy.sceneBoundingRect())
        assert scene.cards[("hand", card.uid)].pixmap is not None
        assert win.height() <= 900 and win.minimumSizeHint().height() <= 900
    finally:
        win.close()
        cardart.clear_cardart_caches()


def test_scene_labels_do_not_occlude_shikigami(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene

    def proxy(widget):
        return next(item for item in scene.items()
                    if hasattr(item, "widget") and item.widget() is widget)

    shiki_rects = [item.sceneBoundingRect() for item in scene_items(view, "shiki")]
    for widget in (view.phase_label, view.hand_caption):
        rect = proxy(widget).sceneBoundingRect()
        assert all(not rect.intersects(shiki_rect) for shiki_rect in shiki_rects)
    assert view.target_label.isHidden()
    assert view.error_label.isHidden()


def test_shiki_placeholder_contains_name_level_and_stats(qapp, view):
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    item = view.battle_scene.cards[("shiki", 0, 0)]
    shiki = view.game.state.players[0].shikigami[0]
    assert view.db.shikigami[shiki.id].name in item.shiki_text
    assert f"等级 {shiki.level}" in item.shiki_text
    assert f"力量 {shiki.eff_power}" in item.shiki_text
    assert item.boundingRect().height() == 210


def test_combat_zone_reuses_items_and_returns_them_to_preparation(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    combatant = scene.cards[("shiki", 0, 0)]
    origin = combatant.pos()
    view.assault(0)
    settle(view)
    assert scene.cards[("shiki", 0, 0)] is combatant
    assert combatant.pos() != origin
    assert combatant.y() < scene.cards[("shiki", 0, 1)].y()
    view.game.state.players[0].combat_index = None
    view.refresh()
    assert scene.cards[("shiki", 0, 0)] is combatant
    assert combatant.pos() == origin


def test_scene_both_combatants_do_not_overlap_preparation(qapp, view):
    start(view, mulligan=False)
    view.game.state.players[0].combat_index = 0
    view.game.state.players[1].combat_index = 0
    view.refresh()
    settle(view)
    scene = view.battle_scene
    enemy = scene.cards[("shiki", 1, 0)]
    own = scene.cards[("shiki", 0, 0)]
    assert enemy.y() < own.y()
    assert not enemy.sceneBoundingRect().intersects(own.sceneBoundingRect())
    preparation = [item for key, item in scene.cards.items()
                   if key[0] == "shiki" and key[2] != 0]
    assert all(not combatant.sceneBoundingRect().intersects(item.sceneBoundingRect())
               for combatant in (enemy, own) for item in preparation)
    assert scene.sceneRect().contains(enemy.sceneBoundingRect())
    assert scene.sceneRect().contains(own.sceneBoundingRect())


def test_scene_sources_have_independent_legal_targets(qapp, db, view):
    shiki_card_id = 10010151
    character_card_id = 10010152
    db.cards[shiki_card_id] = F.card(
        shiki_card_id, token=True, target=F.T(kind="choose", pool="enemy_shikigami"))
    db.cards[character_card_id] = F.card(
        character_card_id, token=True, target=F.T(kind="choose", pool="enemy_character"))
    start(view, mulligan=False)
    view.game.current.shikigami[0].keywords.append("hunt")
    shiki_card = F.give(view.game, 0, shiki_card_id)
    character_card = F.give(view.game, 0, character_card_id)
    view.refresh()
    settle(view)

    scene = view.battle_scene
    hunt = scene.cards[("shiki", 0, 0)]
    non_hunt = scene.cards[("shiki", 0, 1)]
    shiki_source = scene.cards[("hand", shiki_card.uid)]
    character_source = scene.cards[("hand", character_card.uid)]
    enemy_ref = Ref(player=1, shikigami=0)
    assert enemy_ref in hunt.legal_targets
    assert Ref(player=1) not in hunt.legal_targets
    assert non_hunt.legal_targets == []
    assert enemy_ref in shiki_source.legal_targets
    assert Ref(player=1) not in shiki_source.legal_targets
    assert enemy_ref in character_source.legal_targets
    assert Ref(player=1) in character_source.legal_targets
    assert shiki_source.target_required and character_source.target_required
    assert hunt.legal_targets is not shiki_source.legal_targets
    assert shiki_source.legal_targets is not character_source.legal_targets
    normal = scene.cards[("hand", view.game.current.hand[0].uid)]
    assert normal.legal_targets == []


def test_non_hunt_drag_outside_source_assaults(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    calls = []
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        calls.append((index, target)) or True)
    drag = scene.drag_controller
    drag.press(item, item.scenePos())
    drag.move(item.scenePos() + QPointF(180, -90))
    drag.release(item.scenePos() + QPointF(180, -90))
    assert calls == [(0, None)]


def test_drag_click_and_return_to_source_cancel(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    details, calls = [], []
    monkeypatch.setattr(view, "show_shiki_detail", details.append)
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        calls.append((index, target)) or True)
    origin = item.scenePos()
    scene.drag_controller.press(item, origin)
    scene.drag_controller.release(origin)
    assert details == [Ref(player=0, shikigami=0)] and calls == []
    scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(180, 0))
    scene.drag_controller.release(origin)
    assert calls == []
    scene.inputs_open = False
    assert scene.drag_controller.press(item, origin) is False


def test_hunt_and_targeted_card_require_legal_drop(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.current.shikigami[0].keywords.append("hunt")
    card_id = 10010151
    view.db.cards[card_id] = F.card(
        card_id, token=True, target=F.T(kind="choose", pool="enemy_shikigami"))
    card = F.give(view.game, 0, card_id)
    view.refresh()
    settle(view)
    assaults, plays = [], []
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        assaults.append((index, target)) or True)
    monkeypatch.setattr(view, "play_card", lambda uid, usage_id=..., target=None, from_drag=False:
                        plays.append((uid, target)) or True)
    enemy = scene.cards[("shiki", 1, 0)]
    drop = enemy.scenePos() + QPointF(20, 20)
    shiki_item = scene.cards[("shiki", 0, 0)]
    scene.drag_controller.press(shiki_item, shiki_item.scenePos())
    scene.drag_controller.move(drop)
    assert scene.drag_controller.dragged
    scene.drag_controller.release(drop)
    assert assaults == [(0, Ref(player=1, shikigami=0))]
    hand_item = scene.cards[("hand", card.uid)]
    scene.drag_controller.press(hand_item, hand_item.scenePos())
    scene.drag_controller.move(drop)
    assert scene.drag_controller.dragged
    scene.drag_controller.release(drop)
    assert plays == [(card.uid, Ref(player=1, shikigami=0))]

    for item in (shiki_item, hand_item):
        scene.drag_controller.press(item, item.scenePos())
        scene.drag_controller.move(QPointF(20, 450))
        assert scene.drag_controller.dragged
        scene.drag_controller.release(QPointF(20, 450))
    assert assaults == [(0, Ref(player=1, shikigami=0))]
    assert plays == [(card.uid, Ref(player=1, shikigami=0))]


def test_untargeted_card_drag_plays_without_target(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = F.give(view.game, 0, 10010101)
    view.refresh()
    settle(view)
    assert view.db.cards[card.id].target.kind != "choose"
    plays = []
    monkeypatch.setattr(view, "play_card", lambda uid, usage_id=..., target=None, from_drag=False:
                        plays.append((uid, target)) or True)
    item = scene.cards[("hand", card.uid)]
    drop = item.scenePos() + QPointF(-180, -160)
    scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    assert plays == [(card.uid, None)]


def test_drag_sources_require_current_legal_action(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    player = view.game.current
    card = F.give(view.game, 0, 10010101)
    player.assaults_left = 0
    player.orb = 0
    view.refresh()
    settle(view)
    shiki = scene.cards[("shiki", 0, 0)]
    hand = scene.cards[("hand", card.uid)]
    assert not shiki.playable and not hand.playable
    for item in (shiki, hand):
        assert scene.drag_controller.press(item, item.scenePos())
        scene.drag_controller.move(item.scenePos() + QPointF(180, -90))
        assert not scene.drag_controller.dragged
        assert scene.drag_controller.drag_ghost is None
        scene.drag_controller.cancel()

    player.assaults_left = 1
    player.orb = 1
    view.refresh()
    settle(view)
    assert shiki.playable and hand.playable
    view.game.current.shikigami[0].stuns.append({"kind": "normal"})
    view.refresh()
    settle(view)
    assert not shiki.playable


def test_drag_visuals_cancel_and_hand_click_detail(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.current.hand[0]
    details = []
    monkeypatch.setattr(view, "show_card_detail", details.append)
    hand = scene.cards[("hand", card.uid)]
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.release(hand.scenePos())
    assert details == [card]

    shiki = scene.cards[("shiki", 0, 0)]
    scene.drag_controller.press(shiki, shiki.scenePos())
    scene.drag_controller.move(shiki.scenePos() + QPointF(180, -90))
    assert scene.drag_controller.drag_ghost is not None
    assert scene.drag_controller.drag_arrow is not None
    assert scene.drag_controller.drag_ghost.zValue() == 100
    assert scene.drag_controller.drag_arrow.zValue() == 100
    scene.drag_controller.cancel()
    assert scene.drag_controller.drag_ghost is None
    assert scene.drag_controller.drag_arrow is None
    assert shiki.opacity() == 1


def test_mulligan_drag_outside_hand_replaces_card(qapp, view):
    start(view)
    scene = view.battle_scene
    card = view.game.current.hand[0]
    item = scene.cards[("hand", card.uid)]
    assert item.playable
    drop = item.scenePos() + QPointF(-180, -160)
    scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    settle(view)
    assert card not in view.game.state.players[0].hand


def test_scene_commands_apply_through_existing_engine(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    scene = view.battle_scene
    upgrade = scene.cards[("shiki", 0, 1)]
    scene.drag_controller.press(upgrade, upgrade.scenePos())
    scene.drag_controller.release(upgrade.scenePos())
    settle(view)
    assert view.game.state.phase == "battle"
    assert view.game.current.shikigami[1].level == 1

    attacker = scene.cards[("shiki", 0, 0)]
    drop = attacker.scenePos() + QPointF(180, -90)
    scene.drag_controller.press(attacker, attacker.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    settle(view)
    assert view.game.current.combat_index == 0
    assert view.game.current.assaults_left == 0
    assert view.game.current.orb == 0

    card = F.give(view.game, 0, 10010101)
    view.game.current.orb = 1
    view.refresh()
    settle(view)
    hand = scene.cards[("hand", card.uid)]
    drop = hand.scenePos() + QPointF(-180, -160)
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    settle(view)
    assert card not in view.game.current.hand
    assert view.game.current.orb == 0
    assert view.pending_command is None


def test_play_card_error_is_visible_until_message_is_cleared(qapp, view):
    start(view, mulligan=False)
    card = view.game.current.hand[0]
    assert view.error_label.isHidden()
    assert not view.play_card(card.uid, usage_id="missing")
    assert not view.error_label.isHidden()
    assert view.error_label.text() == "该使用方式当前不可用"
    view.error_label.clear()
    assert view.error_label.isHidden()


def test_play_card_drop_target_validates_selected_usage(qapp, db, view):
    main_id, shiki_id, player_id = 10010121, 10010151, 10010152
    db.cards[shiki_id] = F.card(
        shiki_id, token=True, target=F.T(kind="choose", pool="enemy_shikigami"))
    db.cards[player_id] = F.card(
        player_id, token=True, target=F.T(kind="choose", pool="enemy_player"))
    db.cards[main_id] = F.card(
        main_id, card_type="reinforce", shikigami2=100102,
        options=[shiki_id, player_id])
    start(view, mulligan=False)
    card = F.give(view.game, 0, main_id)
    view.refresh()
    settle(view)
    assert not view.play_card(card.uid, usage_id="choice:0", target=Ref(player=1))
    assert card in view.game.current.hand
    assert view.play_card(card.uid, usage_id="choice:1", target=Ref(player=1))
    settle(view)
    assert card not in view.game.current.hand


def test_drag_method_targets_and_blank_drop_follow_selected_usage(qapp, db, view, monkeypatch):
    card_id = 10010151
    db.cards[card_id] = F.card(
        card_id, token=True, target=F.T(kind="choose", pool="enemy_shikigami"),
        methods=[F.method("player", target=F.T(kind="choose", pool="enemy_player")),
                 F.method("untargeted", target=F.T())])
    start(view, mulligan=False)
    scene = view.battle_scene
    commands = []
    real_apply = view.game.apply

    def record_apply(command):
        commands.append(dict(command))
        return real_apply(command)

    monkeypatch.setattr(view.game, "apply", record_apply)
    selected = ["untargeted"]

    def choose_usage(dialog):
        dialog.selected_id = selected[0]
        return QDialog.Accepted

    monkeypatch.setattr(UsageDialog, "exec", choose_usage)

    def give_card():
        card = F.give(view.game, 0, card_id)
        view.game.current.orb = 1
        view.refresh()
        settle(view)
        return card, scene.cards[("hand", card.uid)]

    def drag(item, drop):
        scene.drag_controller.press(item, item.scenePos())
        scene.drag_controller.move(drop)
        assert scene.drag_controller.dragged
        scene.drag_controller.release(drop)

    card, hand = give_card()
    assert not hand.target_required
    assert hand.legal_targets == [Ref(player=1, shikigami=0), Ref(player=1)]
    own_player = scene.cards[("player", 0)]
    drag(hand, own_player.scenePos() + QPointF(20, 20))
    assert commands == [] and view.pending_command is None

    selected[0] = "player"
    enemy_player = scene.cards[("player", 1)]
    drag(hand, enemy_player.scenePos() + QPointF(20, 20))
    settle(view)
    assert commands == [{"op": "play_card", "uid": card.uid,
                         "play_method": "player", "target": Ref(player=1)}]

    card, hand = give_card()
    drag(hand, QPointF(20, 450))
    assert len(commands) == 1 and card in view.game.current.hand
    assert view.pending_command is None
    selected[0] = "untargeted"
    drag(hand, QPointF(20, 450))
    settle(view)
    assert commands[-1] == {"op": "play_card", "uid": card.uid,
                            "play_method": "untargeted"}
    assert card not in view.game.current.hand


def test_drag_reinforce_targets_use_selected_subcard(qapp, db, view, monkeypatch):
    main_id, shiki_id, player_id = 10010121, 10010151, 10010152
    db.cards[shiki_id] = F.card(
        shiki_id, token=True, target=F.T(kind="choose", pool="enemy_shikigami"))
    db.cards[player_id] = F.card(
        player_id, token=True, target=F.T(kind="choose", pool="enemy_player"))
    db.cards[main_id] = F.card(
        main_id, card_type="reinforce", shikigami2=100102,
        options=[shiki_id, player_id])
    start(view, mulligan=False)
    scene = view.battle_scene
    commands = []
    real_apply = view.game.apply

    def record_apply(command):
        commands.append(dict(command))
        return real_apply(command)

    monkeypatch.setattr(view.game, "apply", record_apply)

    def choose_usage(dialog):
        dialog.selected_id = "choice:1"
        return QDialog.Accepted

    monkeypatch.setattr(UsageDialog, "exec", choose_usage)
    card = F.give(view.game, 0, main_id)
    view.game.current.orb = 1
    view.refresh()
    settle(view)
    hand = scene.cards[("hand", card.uid)]
    assert hand.target_required
    assert hand.legal_targets == [Ref(player=1, shikigami=0), Ref(player=1)]
    enemy_player = scene.cards[("player", 1)]
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.move(enemy_player.scenePos() + QPointF(20, 20))
    scene.drag_controller.release(enemy_player.scenePos() + QPointF(20, 20))
    settle(view)
    assert commands == [{"op": "play_card", "uid": card.uid,
                         "choice": 1, "target": Ref(player=1)}]

    card = F.give(view.game, 0, main_id)
    view.game.current.orb = 1
    view.refresh()
    settle(view)
    hand = scene.cards[("hand", card.uid)]
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.move(QPointF(20, 450))
    scene.drag_controller.release(QPointF(20, 450))
    assert len(commands) == 1 and card in view.game.current.hand
    assert view.pending_command is None


def test_target2_only_card_does_not_become_drag_primary_target(qapp, db, view):
    card_id = 10010151
    db.cards[card_id] = F.card(
        card_id, token=True, target2=F.T(kind="choose", pool="enemy_shikigami"))
    start(view, mulligan=False)
    scene = view.battle_scene
    card = F.give(view.game, 0, card_id)
    view.refresh()
    settle(view)
    hand = scene.cards[("hand", card.uid)]
    assert not hand.target_required and hand.legal_targets == []
    enemy = scene.cards[("shiki", 1, 0)]
    drop = enemy.scenePos() + QPointF(20, 20)
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    assert view.pending_command == {"op": "play_card", "uid": card.uid}
    assert [key for key, _spec in view.target_specs] == ["target2"]
    assert card in view.game.current.hand
    view.cancel_targeting()


def test_scene_controls_show_public_counts_and_round_end_turn(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    outer = view.battle_page.layout()
    assert outer.itemAt(0).widget() is view.battle_view
    assert scene.end_turn_item.widget() is view.end_turn_button
    assert scene.menu_item.widget() is view.menu_button
    assert view.end_turn_button.minimumWidth() == view.end_turn_button.maximumWidth()
    assert view.end_turn_button.minimumHeight() == view.end_turn_button.maximumHeight()
    assert view.end_turn_button.minimumWidth() == view.end_turn_button.minimumHeight()
    assert view.end_turn_button.minimumWidth() >= 88
    assert view.enemy_hand_label.text() == (
        f"敌方手牌\n{len(view.game.state.players[1].hand)} 张")
    assert view.enemy_deck_label.text() == f"敌方牌库\n{len(view.game.state.players[1].deck)} 张"
    assert view.own_deck_label.text() == f"己方牌库\n{len(view.game.state.players[0].deck)} 张"


def test_shiki_normal_status_only_shows_core_fields(qapp, db, view):
    form_id = 10010151
    db.cards[form_id] = F.card(form_id, name="测试形态", card_type="form")
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    shiki.energy = 3
    shiki.shield = 4
    shiki.countdown = 2
    shiki.form = CardInstance(uid=10000, id=form_id)
    shiki.keywords.append("critical")
    shiki.invocations.append({"name": "测试灵咒"})
    view.refresh()
    item = view.battle_scene.cards[("shiki", 0, 0)]
    assert db.shikigami[shiki.id].name in item.shiki_text
    assert f"等级 {shiki.level}" in item.shiki_text
    assert f"力量 {shiki.eff_power}　生命 {shiki.health}/{shiki.max_health}" in item.shiki_text
    assert "护甲/破甲 4　倒计时 2" in item.shiki_text
    assert all(text not in item.shiki_text for text in ("能量", "形态", "贯通", "灵咒"))


def test_card_runtime_details_and_static_compatibility(qapp, db):
    cdef = F.card(10010151, name="运行时详情卡")
    runtime = {
        "cost": 0, "stats": "力量 +2　护甲 +1", "keywords": ["瞬发", "贯通"],
        "enhance": 2, "quest": "委托：已 1/2", "playable": False,
        "usage": [{"label": "常规", "ok": False, "reason": "条件未满足"}],
    }
    dialog = CardDetailDialog(cdef, db, runtime=runtime)
    text = dialog.runtime_label.text()
    assert dialog.runtime_label.wordWrap()
    assert "费用 0" in text and "增强 2" in text
    assert "力量 +2　护甲 +1" in text and "瞬发" in text and "贯通" in text
    assert "已 1/2" in text and "条件未满足" in text and "条件：不满足" in text
    assert text.count("委托") == 1
    assert "常规" in text
    dialog.close()

    static = CardDetailDialog(cdef, db)
    assert not hasattr(static, "runtime_label")
    static.close()


def test_card_detail_uses_only_matching_hand_info(qapp, view, monkeypatch):
    start(view, mulligan=False)
    card = view.game.state.players[0].hand[0]
    seen = []

    def capture_exec(dialog):
        seen.append(dialog)
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    monkeypatch.setattr(view, "hand_info", lambda: {
        card.uid: {"cost": 0, "stats": "手牌唯一运行时标记", "keywords": [],
                   "enhance": 0, "quest": None, "playable": True, "usage": []},
    })
    view.show_card_detail(card)
    assert "手牌唯一运行时标记" in seen[-1].runtime_label.text()

    monkeypatch.setattr(view, "hand_info", lambda: {})
    view.show_card_detail(card)
    assert not hasattr(seen[-1], "runtime_label")


def test_card_detail_passes_structured_render_stats(qapp, db, monkeypatch):
    from client.gui import widgets

    cdef = db.cards[10010101]
    seen = {}

    def capture_pixmap(card_def, database, *, display=None):
        seen.update(card_def=card_def, database=database, display=display)
        return None

    monkeypatch.setattr(widgets, "card_pixmap", capture_pixmap)
    dialog = CardDetailDialog(cdef, db, runtime={"render": {"power+": 1, "health+": -2}})
    assert seen == {"card_def": cdef, "database": db,
                    "display": {"power+": 1, "health+": -2}}
    dialog.close()


def test_awaken_detail_separates_permanent_and_form_base(qapp, view, monkeypatch):
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    definition = view.db.shikigami[shiki.id]
    awaken = F.card(10010909, shikigami=shiki.id, subtype="awaken",
                    awaken_power=2, awaken_health=2)
    form = F.card(10010910, shikigami=shiki.id, card_type="form",
                  form_power=2, form_health=6)
    view.db.cards[awaken.id] = awaken
    view.db.cards[form.id] = form
    shiki.awakened = awaken.id
    shiki.form = CardInstance(uid=9999, id=form.id)
    shiki.perm_power = 3
    shiki.perm_health = 4
    shiki.temp_power = 9
    seen = {}

    def capture(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    dialog = seen["dialog"]
    assert f"力量 {definition.power + 3}" in dialog.main_card_text
    assert f"生命 {definition.health + 4}" in dialog.main_card_text
    assert "力量 12" not in dialog.main_card_text
    assert "觉醒" in dialog.main_card_text
    assert dialog.form_card.cdef.form_power == 2
    assert dialog.form_card.cdef.form_health == 6
    assert dialog.form_card.count_label.isHidden()

    awaken.name = "觉醒·巫蛊师"
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    assert "觉醒·巫蛊师" in seen["dialog"].main_card_text
    assert "觉醒·觉醒·" not in seen["dialog"].main_card_text

    shiki.awakened = None
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    assert f"力量 {definition.power}" in seen["dialog"].main_card_text
    assert f"生命 {definition.health}" in seen["dialog"].main_card_text


def test_revealed_enemy_hand_detail_is_static(qapp, view, monkeypatch):
    start(view, mulligan=False)
    card = view.game.state.players[1].hand[0]
    card.mods["revealed"] = True
    seen = {}

    def capture(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    monkeypatch.setattr(view, "hand_info", lambda: {
        card.uid: {"cost": 0, "stats": "不得展示敌方运行时", "keywords": [],
                   "enhance": 0, "quest": None, "playable": True, "usage": []},
    })
    view.show_card_detail(card)
    assert not hasattr(seen["dialog"], "runtime_label")


def test_hidden_enemy_hand_has_no_detail_signal(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[1].hand[0]
    item = scene.cards[("hand", card.uid)]
    details = []
    scene.detail_requested.connect(lambda kind, payload: details.append((kind, payload)))
    assert item.cdef is None
    assert not scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.release(item.scenePos())
    assert details == []


def test_shiki_runtime_details_cover_registered_state(qapp, db, view, monkeypatch):
    form_id = 10010151
    awaken_id = 10010152
    db.cards[form_id] = F.card(form_id, name="测试形态", card_type="form", text="形态原文")
    db.cards[awaken_id] = F.card(awaken_id, name="测试觉醒", text="觉醒原文")
    db.invocations["测试灵咒"] = InvocationDef(name="测试灵咒", text="灵咒原文")
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    shiki.energy = 3
    shiki.shield = 4
    shiki.faction = "青岚"
    shiki.perm_power = 1
    shiki.temp_power = 2
    shiki.combat_power = 3
    shiki.perm_health = 4
    shiki.temp_health = 5
    shiki.keywords.append("piercing")
    shiki.one_shot_keywords.append("barrier")
    shiki.perm_keywords.append("haste")
    shiki.immunities.append({"kind": "combat_damage"})
    shiki.stuns.append({"kind": "normal"})
    shiki.defeated = True
    shiki.revive_countdown = 2
    shiki.countdown = 2
    shiki.countdown_initial = 3
    shiki.countdown_once = True
    shiki.countdown_source = shiki.id
    shiki.countdown_block = F.block(countdown=3)
    shiki.form = CardInstance(uid=10000, id=form_id)
    shiki.awakened = awaken_id
    shiki.delayed.append({"block": F.block(when="on_battle_end"),
                          "chosen": Ref(player=1, shikigami=0), "uses": 2,
                          "origin": None})
    shiki.invocations.append({
        "name": "测试灵咒", "player": 1, "source": Ref(player=1, shikigami=1),
        "power": 1, "health": -1, "bonus": 2, "mod_power": 3, "mod_health": -2,
    })
    shiki.attack_buffs.append({"power": 2, "keywords": [("piercing", "keywords")]})
    shiki.keep_shield = True
    shiki.keep_fragile = True
    shiki.dying = True
    shiki.despawned = True
    shiki.ext.update({"dyn_power": 3, "dyn_health": -2, "power_zero": True,
                      "recorded_card": "其他扩展不得导出"})
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    text = seen["dialog"].status_label.text()
    assert f"力量 {shiki.eff_power}" in text
    assert f"生命 {shiki.health}/{shiki.max_health}" in text
    assert "护甲/破甲 4" in text and "能量 3" in text and "派系 青岚" in text
    assert all(word in text for word in ("贯通", "屏障", "迅捷", "免疫", "combat_damage"))
    assert "眩晕" in text and "气绝" in text and "复活倒计时 2" in text
    assert "倒计时 2" in text and "初始 3" in text and "一次型" in text
    assert f"来源 {db.shikigami[shiki.id].name}" in text
    assert "永久修正 力量 +1　生命 +4" in text
    assert "临时修正 力量 +2　生命 +5" in text
    assert "战斗修正 力量 +3" in text
    assert "形态：测试形态" in text and "形态原文" in text
    assert "觉醒：测试觉醒" in text and "觉醒原文" in text
    assert "延迟能力" in text and "on_battle_end" in text and "次数 2" in text
    assert "玩家B" in text and db.shikigami[view.game.state.players[1].shikigami[0].id].name in text
    assert "灵咒 1：测试灵咒" in text and "灵咒原文" in text
    assert "来源 玩家B" in text and db.shikigami[view.game.state.players[1].shikigami[1].id].name in text
    assert "基础 力量 +1　生命 -1" in text and "增强 +2" in text
    assert "修饰 力量 +3　生命 -2" in text
    assert "攻击后到期强化 1：力量 +2　关键字 贯通" in text
    assert "保留护甲" in text and "保留破甲" in text
    assert "濒死" in text and "已离场" in text
    assert "动态光环合计 力量 +3　生命 -2" in text
    assert "力量覆写" in text and "动态光环与灵咒仍合计" in text
    assert "inv_mod" not in text and "'block'" not in text
    assert "其他扩展不得导出" not in text
    assert "transform_origin" not in text and "coffin_origin" not in text

    normal_text = view.battle_scene.cards[("shiki", 0, 0)].shiki_text
    assert all(word not in normal_text for word in
               ("能量", "形态", "觉醒", "贯通", "延迟能力", "测试灵咒",
                "攻击后到期", "动态光环", "濒死", "保留护甲"))


def test_secret_delayed_target_follows_holder_perspective(qapp, view, monkeypatch):
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    delayed = {"block": F.block(when="on_battle_end"),
               "chosen": Ref(player=1, shikigami=0), "uses": 1,
               "secret": True, "origin": None}
    shiki.delayed.append(delayed)
    seen = []

    def capture_exec(dialog):
        seen.append(dialog.status_label.text())
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    ref = Ref(player=0, shikigami=0)
    view.viewer = 1
    view.show_shiki_detail(ref)
    assert "延迟能力" in seen[-1] and "目标" not in seen[-1]

    view.viewer = 0
    view.show_shiki_detail(ref)
    assert "目标 玩家B" in seen[-1]

    delayed["secret"] = False
    view.viewer = 1
    view.show_shiki_detail(ref)
    assert "目标 玩家B" in seen[-1]


def test_log_button_is_a_scene_control_on_the_left(qapp, view):
    scene = view.battle_scene
    assert scene.log_item.widget() is view.log_button
    assert scene.log_item.x() == 20
    assert scene.log_item.y() == 420
    assert scene.sceneRect().contains(scene.log_item.sceneBoundingRect())


def test_log_dialog_is_nonmodal_reused_and_preserves_timeline(qapp, view):
    assert view.log_dialog.isHidden()
    assert not view.log_dialog.isModal()
    assert view.log_dialog.isAncestorOf(view.log_list)
    box = view.log_dialog.findChild(QDialogButtonBox)
    close = box.button(QDialogButtonBox.Close)
    assert close.text() == "关闭"
    assert close.minimumWidth() == 76 and close.minimumHeight() == 30
    layout = view.log_dialog.layout()
    assert layout.itemAt(layout.count() - 1).widget() is box
    assert layout.itemAt(layout.count() - 1).alignment() == Qt.AlignRight
    view.show_log()
    assert not view.log_dialog.isHidden()
    first = view.log_dialog
    view.show_log()
    assert view.log_dialog is first
    before_close = list(view.played_timeline)
    view.log_dialog.close()
    assert view.played_timeline == before_close
    view.show_log()
    view.close_log()
    assert view.log_dialog.isHidden()
    assert view.log_dialog is first


def test_player_detail_uses_silent_standard_dialog(qapp, view, monkeypatch):
    start(view, mulligan=False)
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    assert view.show_player_detail(0) is None
    dialog = seen["dialog"]
    assert type(dialog) is QDialog
    assert dialog.windowTitle() == "玩家A"
    assert "生命" in dialog.findChild(QLabel).text()
    box = dialog.findChild(QDialogButtonBox)
    close = box.button(QDialogButtonBox.Close)
    assert close.text() == "关闭"
    assert close.minimumWidth() == 76 and close.minimumHeight() == 30
    layout = dialog.layout()
    assert layout.itemAt(layout.count() - 1).widget() is box
    assert layout.itemAt(layout.count() - 1).alignment() == Qt.AlignRight
    dialog.close()


def test_log_dialog_closes_on_new_game_and_return(qapp, view):
    start(view, mulligan=False)
    view.show_log()
    start(view, mulligan=False)
    assert view.log_dialog.isHidden()
    view.show_log()
    view.return_to_menu()
    assert view.log_dialog.isHidden()


def test_mulligan_ready_and_replacement(qapp, view):
    start(view)
    game = view.game
    old_uid = game.state.players[0].hand[0].uid
    view.mulligan(old_uid)
    settle(view)
    assert old_uid not in {card.uid for card in game.state.players[0].hand}
    view.ready()
    settle(view)
    assert game.state.players[0].mulligan_done
    assert view.viewer == 1
    view.ready()
    settle(view)
    assert game.state.phase == "battle"
    assert view.viewer == 0
    assert len(scene_items(view, "hand", player=0)) == len(game.state.players[0].hand)


def test_upgrade_assault_and_end_turn(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    game = view.game
    assert view.phase_label.text().startswith("升级")
    assert view.battle_scene.cards[("shiki", 0, 1)].playable
    view.upgrade(1)
    settle(view)
    assert game.state.players[0].shikigami[1].level == 1
    assert game.state.phase == "battle"
    view.assault(0)
    settle(view)
    assert game.state.players[0].assaults_left == 0
    assert game.state.players[0].combat_index == 0
    view.end_turn()
    settle(view)
    assert game.state.active == 1
    assert view.viewer == 1


def test_play_card_with_target_mode(qapp, db, view):
    cid = 10010151
    db.cards[cid] = F.card(cid, token=True,
                           target=F.T(kind="choose", pool="enemy_character"),
                           steps=[F.dmg(2)])
    start(view, mulligan=False)
    game = view.game
    card = F.give(game, 0, cid)
    view.refresh()
    settle(view)
    view.play_card(card.uid)
    assert view.pending_command["uid"] == card.uid
    assert Ref(player=1) in view.legal_targets
    assert view.battle_scene.cards[("shiki", 1, 0)].targetable is True
    view.choose_target(Ref(player=1))
    settle(view)
    assert card not in game.state.players[0].hand
    assert game.state.players[1].shield == 3
    assert view.pending_command is None


def test_pending_choice_answer(qapp, db, view):
    cid = 10010151
    db.cards[cid] = F.card(cid, token=True,
                           steps=[F.Step(op="deck_top_pick", count=2, times=1)])
    start(view, mulligan=False)
    game = view.game
    card = F.give(game, 0, cid)
    view.refresh()
    settle(view)
    view.play_card(card.uid)
    settle(view)
    pending = game.state.pending_choice
    assert pending["kind"] == "deck_top_pick"
    assert view.choice_dialog is not None
    view.choice_dialog.reject()
    assert not view.choice_dialog.isHidden()
    uid = pending["options"][0]
    view.answer_pending(uid)
    settle(view)
    assert game.state.pending_choice is None
    assert any(card.uid == uid for card in game.state.players[0].hand)


def test_game_over_banner_returns_to_menu(qapp, view):
    returned = []
    view.on_back = lambda: returned.append(True)
    start(view, mulligan=False)
    view.game.state.winner = 0
    view.refresh()
    settle(view)
    assert not view.result_banner.isHidden()
    assert "玩家A" in view.result_banner.text()
    view.result_back.click()
    assert returned == [True]


def test_main_window_hotseat_page_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert isinstance(win.pages["hotseat"], HotseatView)
    win.go("hotseat")
    assert win.stack.currentWidget() is win.pages["hotseat"]
    win.toggle_theme()
    assert win.pages["hotseat"].theme == "dark"
    win.pages["hotseat"].timeline_timer.start()
    win.back_button.click()
    assert win.stack.currentIndex() == 0
    assert not win.pages["hotseat"].timeline_timer.isActive()
    win.close()


def test_play_method_and_second_target(qapp, db, view):
    burst_id = 10010151
    db.cards[burst_id] = F.card(burst_id, token=True,
                                methods=[F.method("burst", energy_cost=1)])
    double_id = 10010152
    choose = F.T(kind="choose", pool="enemy_character")
    db.cards[double_id] = F.card(double_id, token=True, target=choose, target2=choose)
    start(view, mulligan=False)
    game = view.game
    game.current.shikigami[0].energy = 2
    burst = F.give(game, 0, burst_id)
    double = F.give(game, 0, double_id)
    view.refresh()
    settle(view)
    assert view.play_card(burst.uid, usage_id="burst")
    settle(view)
    assert burst not in game.current.hand
    assert game.current.shikigami[0].energy == 1

    game.current.orb = 1
    view.play_card(double.uid)
    first = Ref(player=1)
    second = Ref(player=1, shikigami=0)
    view.choose_target(first)
    assert view.pending_command["target"] == first
    view.choose_target(second)
    settle(view)
    assert double not in game.current.hand
    assert view.pending_command is None


def test_timeline_playback_blocks_new_commands(qapp, view):
    start(view, mulligan=False)
    game = view.game
    assert view.end_turn()
    assert view.timeline_queue
    assert not view.end_turn_button.isEnabled()
    assert not view.end_turn()
    assert game.state.active == 1
    settle(view)
    assert view.end_turn_button.isEnabled()


def test_private_timeline_entries_follow_current_viewer(qapp, view):
    start(view, mulligan=False)
    view.game.state.timeline.append({"k": "l", "m": "仅先手可见", "o": 0})
    view.refresh()
    settle(view)
    assert any(view.log_list.item(i).text() == "仅先手可见"
               for i in range(view.log_list.count()))
    view.game.state.active = 1
    view.refresh()
    settle(view)
    assert all(view.log_list.item(i).text() != "仅先手可见"
               for i in range(view.log_list.count()))


def test_viewer_handoff_freezes_commands_hands_choices_and_timeline(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert not view._handoff_pending
    view.refresh()
    assert not view._handoff_pending
    assert scene.cards[("player", 0)].y() > scene.cards[("player", 1)].y()

    old_hand_items = scene_items(view, "hand")
    assert old_hand_items
    assert view.end_turn()
    assert view._handoff_pending
    assert all(item.scene() is None for item in old_hand_items)
    assert view.handoff_dialog is not None and not view.handoff_dialog.isHidden()
    dialog = view.handoff_dialog
    box = dialog.findChild(QDialogButtonBox)
    confirm = box.button(QDialogButtonBox.Ok)
    assert confirm.text() == "确定"
    assert confirm.minimumWidth() == 76 and confirm.minimumHeight() == 30
    layout = dialog.layout()
    assert layout.itemAt(layout.count() - 1).widget() is box
    assert layout.itemAt(layout.count() - 1).alignment() == Qt.AlignRight
    dialog.reject()
    assert view._handoff_pending and not dialog.isHidden()
    assert not scene_items(view, "hand")
    assert view.choice_dialog is None
    assert scene.cards[("player", 0)].y() > scene.cards[("player", 1)].y()
    before = list(view.timeline_queue)
    assert before
    assert not view.apply_command({"op": "end_turn"})
    view.play_next_timeline()
    assert view.timeline_queue == before

    confirm.click()
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert dialog.isHidden()
    assert scene.cards[("player", 1)].y() > scene.cards[("player", 0)].y()
    assert scene_items(view, "hand", player=1)
    assert view.timeline_queue == before
    settle(view)


def test_handoff_clears_drag_and_reveals_only_new_viewer_hand(qapp, view):
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    origin = item.scenePos()
    scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(160, -80))
    assert scene.animation_layer.drag_ghost is not None
    view.game.state.active = 1
    view.refresh()
    assert view._handoff_pending
    assert scene.animation_layer.drag_ghost is None
    assert scene.animation_layer.drag_arrow is None
    assert not any(key[0] == "hand" for key in scene.cards)
    view.confirm_handoff()
    expected = {card.uid for player in view.game.state.players for card in player.hand}
    hand_items = {key[1]: item for key, item in scene.cards.items() if key[0] == "hand"}
    assert set(hand_items) == expected
    assert {card.uid for card in view.game.state.players[1].hand} == {
        uid for uid, item in hand_items.items() if item.revealed}
    assert scene.sceneRect().contains(scene.end_turn_item.sceneBoundingRect())
    assert scene.sceneRect().contains(scene.menu_item.sceneBoundingRect())


def test_scene_visual_review(qapp, view):
    if os.environ.get("BWP_VISUAL_REVIEW") != "1":
        pytest.skip("仅在人工实图复核时运行")
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    from client.gui.details import ShikigamiDetailDialog

    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    output = Path(".pytest_cache/gui-review")
    output.mkdir(parents=True, exist_ok=True)
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    assert view.grab().save(str(output / "battle.png"))

    player = view.game.state.players[0]
    player.hand[:] = [card.model_copy(update={"uid": 2000 + i, "hand_seq": i + 1})
                      for i, card in enumerate((player.hand * 3)[:12])]
    view.refresh()
    settle(view)
    qapp.processEvents()
    assert view.grab().save(str(output / "hand-12.png"))

    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.move(item.scenePos() + QPointF(180, -90))
    qapp.processEvents()
    assert view.grab().save(str(output / "drag.png"))
    scene.drag_controller.cancel()

    shiki = view.game.state.players[0].shikigami[0]
    awaken = F.card(10010909, shikigami=shiki.id, subtype="awaken",
                    awaken_power=2, awaken_health=2)
    form = F.card(10010910, shikigami=shiki.id, card_type="form",
                  form_power=2, form_health=6)
    view.db.cards[awaken.id] = awaken
    view.db.cards[form.id] = form
    shiki.awakened = awaken.id
    shiki.form = CardInstance(uid=9999, id=form.id)
    shiki.perm_power = 2
    shiki.perm_health = 2
    dialog = ShikigamiDetailDialog(view.game, Ref(player=0, shikigami=0), 0, view)
    dialog.resize(1000, 700)
    dialog.show()
    qapp.processEvents()
    assert dialog.grab().save(str(output / "detail.png"))
    dialog.close()


def test_cross_player_pending_choice_hands_off_on_entry_and_return(qapp, view):
    start(view, mulligan=False)
    game = view.game
    game.state.pending_choice = {
        "kind": "deck_top_pick", "player": 1, "count": 2,
        "options": [card.uid for card in game.state.players[1].deck[:2]],
        "remaining": 1,
    }
    view.refresh()
    assert view.viewer == 1
    assert view._handoff_pending
    assert view.choice_dialog is None
    assert not scene_items(view, "hand")

    view.confirm_handoff()
    assert view.choice_dialog is not None
    assert not view.choice_dialog.isHidden()
    assert view.answer_pending(game.state.pending_choice["options"][0])
    assert game.state.pending_choice is None
    assert view.viewer == 0
    assert view._handoff_pending
    assert view.choice_dialog is None
    assert not scene_items(view, "hand")
    view.confirm_handoff()
    assert scene_items(view, "hand", player=0)
    settle(view)


def test_handoff_skips_game_over_and_cleans_up_on_restart_and_return(qapp, view):
    start(view, mulligan=False)
    view.game.state.active = 1
    view.game.state.winner = 0
    view.refresh()
    assert view.viewer == 1
    assert not view._handoff_pending
    assert view.handoff_dialog is None

    start(view, mulligan=False)
    assert view.end_turn()
    assert view._handoff_pending
    restart_dialog = view.handoff_dialog
    start(view, mulligan=False)
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert restart_dialog.isHidden()
    assert view.end_turn()
    return_dialog = view.handoff_dialog
    view.return_to_menu()
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert return_dialog.isHidden()


def test_mulligan_log_hides_opponent_counts_only_during_startup(qapp, view):
    start(view)
    own_uid = view.game.state.players[0].hand[0].uid
    assert view.mulligan(own_uid)
    settle(view)
    own_message = "玩家A 调度了一张手牌（剩余 2 次）"
    assert own_message in log_lines(view)

    assert view.ready()
    settle(view)
    assert own_message not in log_lines(view)
    other_uid = view.game.state.players[1].hand[0].uid
    assert view.mulligan(other_uid)
    settle(view)
    other_message = "玩家B 调度了一张手牌（剩余 2 次）"
    assert other_message in log_lines(view)

    assert view.ready()
    settle(view)
    assert view.game.state.phase == "battle"
    assert other_message not in log_lines(view)
    view.game.state.timeline.append({"k": "l", "m": other_message})
    view.refresh()
    settle(view)
    assert log_lines(view).count(other_message) == 1
