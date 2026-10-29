"""桌面 GUI 本地热坐对战测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox

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
            if view._handoff_stage == "review":
                break
            view.confirm_handoff()
        if view.timeline_queue:
            view.play_next_timeline()
    scene = view.battle_scene
    animations = list(scene._move_animations.values()) + list(scene._card_use_animations)
    for animation in animations:
        animation.setCurrentTime(animation.duration())
    QApplication.processEvents()


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


@pytest.fixture(autouse=True)
def accept_exit_confirmation(monkeypatch):
    monkeypatch.setattr("client.gui.battle.ask_confirmation", lambda *_args: QMessageBox.Yes)


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
    assert scene.cards[("player", 1)].pos() == QPointF(1, 4)
    assert scene.cards[("player", 0)].pos() == QPointF(1, 766)
    assert [scene.cards[("shiki", 1, index)].y() for index in range(4)] == [
        120, 60, 60, 120]
    assert [scene.cards[("shiki", 0, index)].y() for index in range(4)] == [
        570, 630, 630, 570]
    assert [scene.cards[("shiki", 0, index)].x() for index in range(4)] == [
        276, 501, 951, 1176]
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


def test_own_hand_display_sort_preserves_acquisition_sequence(qapp, db, view):
    neutral = F.card(90000001, shikigami=None, token=True)
    db.cards[neutral.id] = neutral
    start(view, mulligan=False)
    own = view.game.current
    F.give(view.game, 0, neutral.id)
    for sequence, card in zip(range(40, 0, -1), own.hand):
        card.hand_seq = sequence
    original_sequences = {card.uid: card.hand_seq for card in own.hand}
    view.refresh()
    settle(view)

    def sort_key(card):
        cdef = db.cards[card.id]
        owners = {sid for sid in (cdef.shikigami, cdef.shikigami2) if sid is not None}
        seat = next((index for index, shiki in enumerate(own.shikigami)
                     if shiki.id in owners or (shiki.transform_owner is not None
                                              and shiki.transform_owner in owners)), 4)
        return seat, cdef.level or 0, card.id, card.hand_seq

    expected = sorted(own.hand, key=sort_key)
    items = sorted((item for key, item in view.battle_scene.cards.items()
                    if key[0] == "hand" and item.player == 0), key=lambda item: item.x())
    assert [item.uid for item in items] == [card.uid for card in expected]
    assert items[-1].cdef.shikigami is None
    assert {card.uid: card.hand_seq for card in own.hand} == original_sequences


def test_scene_twelve_hand_cards_overlap_and_shiki_placeholder(qapp, view):
    start(view, mulligan=False)
    player = view.game.state.players[0]
    player.hand[:] = [card.model_copy(update={"uid": 1000 + i, "hand_seq": i + 1})
                      for i, card in enumerate((player.hand * 3)[:12])]
    view.refresh()
    settle(view)
    items = sorted((view.battle_scene.cards[("hand", card.uid)] for card in player.hand),
                   key=lambda item: item.x())
    assert len(items) == 12
    assert items[1].x() < items[0].x() + items[0].boundingRect().width()
    assert items[1].x() - items[0].x() == 70
    assert items[-1].x() + items[-1].boundingRect().width() <= 1600
    shiki = view.battle_scene.cards[("shiki", 0, 0)]
    assert "力量" in shiki.shiki_text and "生命" in shiki.shiki_text
    assert "等级" in shiki.shiki_text


def test_scene_missing_hand_and_form_art_renders_full_card(qapp, db, view):
    def assert_full_card(item):
        image = QImage(item.size.toSize(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        assert any(image.pixelColor(x, y).alpha() > 0
                   for x in range(image.width()) for y in range(image.height()))

    start(view, mulligan=False)
    hand = view.battle_scene.cards[("hand", view.game.current.hand[0].uid)]
    assert hand.pixmap is not None and not hand.pixmap.isNull()
    assert_full_card(hand)

    form_id = 10010151
    db.cards[form_id] = F.card(form_id, name="无图形态", card_type="form")
    view.game.current.shikigami[0].form = CardInstance(uid=10000, id=form_id)
    view.refresh()
    settle(view)
    form = view.battle_scene.cards[("shiki", 0, 0)]
    assert form.pixmap is not None and not form.pixmap.isNull()
    assert_full_card(form)


def test_scene_render_failure_has_visible_text_fallback(qapp, view, monkeypatch):
    from client.gui import battle_scene

    monkeypatch.setattr(battle_scene, "card_pixmap", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(battle_scene, "entity_pixmap", lambda *_args, **_kwargs: None)
    start(view, mulligan=False)
    items = [view.battle_scene.cards[("hand", view.game.current.hand[0].uid)],
             view.battle_scene.cards[("shiki", 0, 0)]]
    for item in items:
        image = QImage(item.size.toSize(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        assert any(image.pixelColor(x, y).alpha() > 0
                   for x in range(image.width()) for y in range(image.height()))


def test_scene_render_checks_resources_once_per_sync(qapp, view, monkeypatch):
    from client.gui import cardart

    start(view, mulligan=False)
    calls = []
    original = cardart._renderer_resource_digest

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(cardart, "_renderer_resource_digest", counted)
    view.refresh()
    assert len(calls) == 1


def test_card_owner_seat_handles_dual_owner_and_replacement(qapp, db, view):
    from client.gui.battle_scene import card_owner_seat

    start(view, mulligan=False)
    player = view.game.current
    dual = F.card(10010151, shikigami=999999, shikigami2=100104, card_type="reinforce")
    assert card_owner_seat(view.game, player, dual) == 3
    player.shikigami[1].ext["replace_owner"] = 100102
    assert card_owner_seat(view.game, player, db.cards[10010201]) == 1
    player.shikigami[2].transform_owner = 100103
    assert card_owner_seat(view.game, player, db.cards[10010301]) == 2


def test_battle_pages_have_no_extra_outer_margin(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    for key in ("hotseat", "online"):
        margins = win.pages[key].layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)
    win.close()


def test_shiki_card_has_no_extra_stat_text_badge(qapp, view):
    start(view, mulligan=False)
    item = view.battle_scene.cards[("shiki", 0, 0)]
    assert not hasattr(item, "_stat_badge")


def test_hand_playable_border_colors(qapp, view):
    start(view, mulligan=False)
    game = view.game
    game.db.cards[10010151] = F.card(10010151, token=True, cost=0)
    game.db.cards[10010152] = F.card(
        10010152, token=True,
        methods=[F.method("free", cost=0), F.method("paid", cost=1)])
    free = F.give(game, 0, 10010151)
    multi = F.give(game, 0, 10010152)
    view.refresh(); settle(view)
    assert view.battle_scene.cards[("hand", free.uid)].border_color == "blue"
    assert view.battle_scene.cards[("hand", multi.uid)].border_color == "green"
    assert view.battle_scene.cards[("shiki", 0, 0)].border_color == "yellow"


def test_phase_label_sits_right_of_turn_label(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    assert view.upgrade_label.text() == "升级阶段"
    assert view.upgrade_label.isVisible()
    assert view.battle_scene.upgrade_item.x() > view.battle_scene.phase_item.x()


def test_mulligan_handoff_has_review_then_transfer(qapp, view):
    start(view)
    for _ in range(3):
        view.mulligan(view.game.current.hand[0].uid)
        settle(view)
    assert view.handoff_dialog.windowTitle() == "调度完毕请确认"
    assert view.handoff_dialog.isVisible()
    view.confirm_handoff()
    assert view.handoff_dialog.windowTitle() == "准备移交"
    view.confirm_handoff()
    assert view.viewer == 1


def test_playable_hand_has_no_blue_frame(qapp, view):
    start(view, mulligan=False)
    item = view.battle_scene.cards[("hand", view.game.current.hand[0].uid)]
    item.playable = True
    item.targetable = item.dragging = False
    image = QImage(item.size.toSize(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert image.pixelColor(2, 2).name() != "#75b9d1"


def test_hand_deck_text_contrast_and_tight_outer_margins(qapp, view):
    start(view, mulligan=False)
    view.apply_theme("light", THEMES["light"])
    for label in (view.enemy_hand_label, view.enemy_deck_label,
                  view.own_deck_label, view.hand_caption, view.phase_label,
                  view.order_label, view.upgrade_label):
        assert f"color: {THEMES['light']['text']}" in label.styleSheet()
        assert "font-weight: 600" in label.styleSheet()
    for button in (view.log_button, view.ready_button, view.result_back,
                   view.end_turn_button):
        assert button.testAttribute(Qt.WA_TranslucentBackground)
        assert f"color: {THEMES['light']['text']}" in button.styleSheet()
    scene = view.battle_scene
    assert scene.cards[("player", 0)].x() <= 1
    hand = max((item for key, item in scene.cards.items()
                if key[0] == "hand" and item.player == 0), key=lambda item: item.x())
    assert hand.x() + hand.size.width() >= 1598
    assert scene.end_turn_item.x() + 104 >= 1597


def test_player_item_has_original_avatar_orbs_and_badges(qapp, view):
    start(view, mulligan=False)
    player = view.game.current
    player.assault_boosts.append({"power": 2, "shield": 3})
    view.refresh()
    settle(view)
    item = view.battle_scene.cards[("player", 0)]
    assert item.avatar_shape == "circle"
    assert item.health == player.health and item.max_health == player.max_health
    assert item.orb == player.orb and item.assaults_left == player.assaults_left
    assert item.inspire_power == 2 and item.inspire_shield == 3


def test_card_detail_hides_deck_builder_copy_count(qapp, view, monkeypatch):
    start(view, mulligan=False)
    seen = {}

    def capture(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    view.show_card_detail(view.game.current.hand[0])
    labels = seen["dialog"].findChildren(QLabel, "cardCount")
    assert labels and all(label.isHidden() for label in labels)


def test_scene_card_art_preserves_ratio_and_reduces_outer_margins(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    for key, max_size in ((("hand", view.game.current.hand[0].uid), (110, 156)),
                          (("shiki", 0, 0), (148, 210))):
        item = scene.cards[key]
        pixmap = item.pixmap
        assert pixmap is not None and not pixmap.isNull()
        assert item.size.width() / item.size.height() == pytest.approx(
            pixmap.width() / pixmap.height())
        assert item.size.width() <= max_size[0]
        assert item.size.height() <= max_size[1]
    assert scene.cards[("player", 0)].x() <= 4
    own_hand = max((item for key, item in scene.cards.items()
                    if key[0] == "hand" and item.player == 0), key=lambda item: item.x())
    assert own_hand.x() + own_hand.size.width() >= 1596


def test_scene_card_art_geometry_change_is_notified(qapp, view, monkeypatch):
    start(view, mulligan=False)
    item = view.battle_scene.cards[("hand", view.game.current.hand[0].uid)]
    called = []
    monkeypatch.setattr(item, "prepareGeometryChange", lambda: called.append(True))
    item.set_art(item.pixmap)
    assert called


def test_shiki_detail_uses_diy_card_art(qapp, view, monkeypatch):
    start(view, mulligan=False)
    seen = {}

    def capture(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    dialog = seen["dialog"]
    pixmap = dialog.main_art_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert dialog.main_art_label.width() / dialog.main_art_label.height() == pytest.approx(
        dialog.main_art_pixmap.width() / dialog.main_art_pixmap.height(), abs=0.2)


def test_hand_detail_uses_owner_seat_level_color(qapp, view, monkeypatch):
    start(view, mulligan=False)
    card = next(card for card in view.game.current.hand
                if view.db.cards[card.id].shikigami == 100102)
    seen = {}

    class Detail:
        def __init__(self, *args, level_color=None, **kwargs):
            seen["level_color"] = level_color

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr("client.gui.battle.CardDetailDialog", Detail)
    view.show_card_detail(card)
    assert seen["level_color"] == "cyan"


def test_shiki_detail_uses_seat_level_color(qapp, view, monkeypatch):
    start(view, mulligan=False)
    seen = {}

    def capture(_shiki, _db, *, seat=None, height=None):
        seen["seat"] = seat

    monkeypatch.setattr("client.gui.details.shikigami_pixmap", capture)
    from client.gui.details import ShikigamiDetailDialog
    ShikigamiDetailDialog(view.game, Ref(player=0, shikigami=2), 0, view)
    assert seen["seat"] == 2


def test_upgrade_focus_only_highlights_legal_shikigami(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    scene = view.battle_scene
    legal = set(view.game.legal_upgrade_indices(0))
    assert legal
    overlay = scene.focus_overlay
    assert overlay.isVisible()
    path = overlay.path()
    for index in range(4):
        item = scene.cards[("shiki", 0, index)]
        center = item.sceneBoundingRect().center()
        assert item.playable == (index in legal)
        assert path.contains(center) == (index not in legal)
    assert path.contains(scene.cards[("player", 0)].sceneBoundingRect().center())
    assert view.upgrade_label.text() == "升级阶段"
    assert not view.upgrade_label.isHidden()
    assert set(scene.upgrade_badges) == legal
    for index, badge in scene.upgrade_badges.items():
        shiki = scene.cards[("shiki", 0, index)]
        assert not badge.pixmap().isNull()
        assert badge.y() + badge.boundingRect().height() <= shiki.y()
        assert badge.zValue() > overlay.zValue()


def test_upgrade_focus_requires_current_legal_action(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    scene = view.battle_scene
    assert scene.focus_overlay.isVisible()
    scene.sync_state(view.game, 0, view.hand_info(), False)
    assert not scene.focus_overlay.isVisible()
    scene.sync_state(view.game, 1, {}, True)
    assert not scene.focus_overlay.isVisible()


def test_drag_focus_highlights_source_default_player_and_arrow(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    source = scene.cards[("shiki", 0, 0)]
    enemy_player = scene.cards[("player", 1)]
    other = scene.cards[("shiki", 0, 1)]
    scene.drag_controller.press(source, source.scenePos())
    scene.drag_controller.move(source.scenePos() + QPointF(180, -90))
    assert scene.drag_controller.dragged
    assert source.opacity() == 1
    path = scene.focus_overlay.path()
    assert not path.contains(source.sceneBoundingRect().center())
    assert not path.contains(enemy_player.sceneBoundingRect().center())
    assert path.contains(other.sceneBoundingRect().center())
    assert scene.drag_controller.drag_arrow.isVisible()
    scene.drag_controller.cancel()
    assert not scene.focus_overlay.isVisible()


def test_direct_assault_focus_targets_player_not_combat_shiki(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    source = scene.cards[("shiki", 0, 0)]
    source.keywords.append("direct")
    view.game.state.players[1].combat_index = 0
    scene.focus_for_drag(source)
    path = scene.focus_overlay.path()
    assert not path.contains(scene.cards[("player", 1)].sceneBoundingRect().center())
    assert path.contains(scene.cards[("shiki", 1, 0)].sceneBoundingRect().center())
    scene.drag_controller.cancel()


def test_player_orb_overflow_and_turn_button_stay_bounded(qapp, view):
    start(view, mulligan=False)
    view.apply_theme("light", THEMES["light"])
    player = view.game.current
    player.orb = 6
    player.graveyard.extend(list(player.hand[:2])
                            if isinstance(player.graveyard, list) else [])
    view.refresh()
    settle(view)
    item = view.battle_scene.cards[("player", 0)]
    assert item.orb_display_count <= 4
    assert item.orb_overflow == 2
    assert not hasattr(item, "graveyard_count")
    assert not hasattr(view, "field_labels")
    assert view.end_turn_button.width() == view.end_turn_button.height() == 104
    assert "border-radius: 52px" in view.styleSheet()
    assert "text-align: center" in view.styleSheet()
    assert view.end_turn_button.mask().isNull()


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


def test_battle_view_keeps_aspect_ratio_with_letterboxing(qapp, view):
    start(view, mulligan=False)
    view.resize(1000, 1000)
    view.show()
    qapp.processEvents()
    battle_view = view.battle_view
    transform = battle_view.transform()
    assert transform.m11() == pytest.approx(transform.m22())
    mapped = battle_view.mapFromScene(view.battle_scene.sceneRect()).boundingRect()
    viewport = battle_view.viewport().rect()
    assert mapped.left() >= viewport.left() - 1
    assert mapped.top() >= viewport.top() - 1
    assert mapped.right() <= viewport.right() + 1
    assert mapped.bottom() <= viewport.bottom() + 1


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
    settle(view)
    assert scene.cards[("shiki", 0, 0)] is combatant
    assert combatant.pos() == origin


def test_assault_timer_finishes_and_refreshes_public_state(qapp, view):
    import time

    start(view, mulligan=False)
    view.timeline_timer.setInterval(1)
    enemy = view.game.state.players[1]
    before = enemy.health + enemy.shield + sum(
        shiki.health + shiki.shield for shiki in enemy.shikigami)
    assert view.assault(0)
    deadline = time.monotonic() + 2
    while view.timeline_queue and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert not view.timeline_queue
    after = enemy.health + enemy.shield + sum(
        shiki.health + shiki.shield for shiki in enemy.shikigami)
    assert after < before
    player_item = view.battle_scene.cards[("player", 1)]
    assert (player_item.health, player_item.shield) == (enemy.health, enemy.shield)
    target_text = view.battle_scene.cards[("shiki", 1, 0)].shiki_text
    assert f"生命 {enemy.shikigami[0].health}/{enemy.shikigami[0].max_health}" in target_text
    assert any("战斗开始" in message for _owner, message in view.played_timeline)
    assert view.end_turn_button.isEnabled()


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
    assert enemy.pos() == QPointF(726, 220)
    assert own.pos() == QPointF(726, 460)


def test_battle_entities_use_diy_small_card_renderer(qapp, view, monkeypatch):
    from client.gui import battle_scene

    calls = []
    monkeypatch.setattr(battle_scene, "entity_pixmap",
                        lambda shiki, db, *, seat, form=None, cache_context=None, height=None:
                        calls.append((shiki, seat, form)), raising=False)
    start(view, mulligan=False)
    assert len({id(call[0]) for call in calls}) == 8
    assert {call[0].id for call in calls} == set(view.db.shikigami)
    shiki = view.game.current.shikigami[0]
    form = view.db.cards[shiki.id * 100 + 1]
    shiki.form = CardInstance(uid=9999, id=form.id)
    calls.clear()
    view.refresh()
    assert any(call[2] == form for call in calls)


def test_loading_indicator_uses_real_tenths(qapp):
    from client.gui.loading import LoadingIndicator

    now = [0.0]
    seen = []
    indicator = LoadingIndicator("正在准备对局", seen.append, clock=lambda: now[0])
    indicator.start()
    assert seen[-1] == "正在准备对局 0.0s"
    now[0] = 0.19
    indicator.tick()
    assert seen[-1] == "正在准备对局 0.1s"
    now[0] = 0.21
    indicator.tick()
    assert seen[-1] == "正在准备对局 0.2s"
    indicator.stop()
    now[0] = 1.0
    indicator.tick()
    assert seen[-1] == "正在准备对局 0.2s"
    indicator.start(total=12)
    assert seen[-1] == "正在准备对局（0/12） 0.0s"
    indicator.set_progress(3, 12)
    now[0] = 1.21
    indicator.tick()
    assert seen[-1] == "正在准备对局（3/12） 0.2s"


def test_scene_loading_lifecycle(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert not scene.loading_item.isVisible()
    scene.show_loading("正在准备对局")
    assert scene.loading_item.isVisible()
    assert "0.0s" in scene.loading_item.toPlainText()
    scene.loading_tick()
    scene.hide_loading()
    assert not scene.loading_item.isVisible()
    assert not scene.loading._timer.isActive()


def test_opening_and_turn_start_banners(qapp, view):
    start(view)
    scene = view.battle_scene
    assert scene.banner_item.toPlainText() == "己方先手"
    assert scene.banner_item.isVisible() and scene.banner_timer.isActive()
    scene.hide_banner()
    start(view, mulligan=False)
    scene.hide_banner()
    view.end_turn()
    settle(view)
    assert scene.banner_item.toPlainText() == "回合开始"
    assert scene.banner_item.isVisible() and scene.banner_timer.isActive()
    scene.hide_banner()
    assert not scene.banner_item.isVisible()
    scene.show_banner("回合开始")
    view.return_to_menu()
    assert not scene.banner_timer.isActive() and not scene.banner_item.isVisible()


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


def test_scene_assault_playable_allows_energy_payment(qapp, view):
    start(view, mulligan=False)
    player = view.game.current
    shiki_state = player.shikigami[0]
    player.assaults_left = 0
    player.orb = 0
    player.ext["energy_assault"] = {"holder": [0, 0], "cost": 3}
    shiki_state.energy = 3
    view.refresh()
    settle(view)
    assert view.battle_scene.cards[("shiki", 0, 0)].playable

    shiki_state.energy = 2
    view.refresh()
    settle(view)
    assert not view.battle_scene.cards[("shiki", 0, 0)].playable


def test_scene_assault_playable_follows_enraged_attacker(qapp, view):
    start(view, mulligan=False)
    player = view.game.current
    player.shikigami[1].level = 1
    player.shikigami[1].keywords.append("enraged")
    view.refresh()
    settle(view)
    assert not view.battle_scene.cards[("shiki", 0, 0)].playable
    assert view.battle_scene.cards[("shiki", 0, 1)].playable


def test_scene_assault_playable_follows_combat_zone_lock(qapp, db, view):
    form_id = 10010151
    db.cards[form_id] = F.card(
        form_id, token=True, card_type="form", form_power=3, form_health=5,
        tags=["combat_lock"])
    start(view, mulligan=False)
    own, enemy = view.game.state.players
    own.shikigami[1].level = 1
    own.combat_index = 0
    enemy.combat_index = 0
    enemy.shikigami[0].form = CardInstance(uid=10000, id=form_id)
    view.refresh()
    settle(view)
    assert not view.battle_scene.cards[("shiki", 0, 1)].playable

    own.shikigami[1].keywords.append("remote")
    view.refresh()
    settle(view)
    assert view.battle_scene.cards[("shiki", 0, 1)].playable


def test_scene_native_render_heights(qapp, view, monkeypatch):
    from client.gui import battle_scene

    heights = []
    monkeypatch.setattr(battle_scene, "card_pixmap",
                        lambda _cdef, _db, **kwargs: heights.append(("card", kwargs.get("height"))))
    monkeypatch.setattr(battle_scene, "entity_pixmap",
                        lambda _shiki, _db, **kwargs: heights.append(("entity", kwargs.get("height"))))
    start(view)
    assert ("card", 255) in heights and ("entity", 210) in heights
    heights.clear()
    start(view, mulligan=False)
    assert ("card", 156) in heights and ("entity", 210) in heights


def test_scene_card_art_receives_runtime_display(qapp, db, view, monkeypatch):
    from client.gui import battle_scene

    calls = []

    def capture_pixmap(cdef, database, *, display=None, level_color=None, cache_context=None,
                       height=None):
        calls.append((cdef, display, level_color))
        return None

    entity_calls = []

    def capture_entity(shiki, database, *, seat, form=None, cache_context=None, height=None):
        entity_calls.append((shiki, seat, form))
        return None

    monkeypatch.setattr(battle_scene, "card_pixmap", capture_pixmap)
    monkeypatch.setattr(battle_scene, "entity_pixmap", capture_entity)
    start(view, mulligan=False)
    card = next(card for card in view.game.current.hand
                if view.db.cards[card.id].shikigami == 100103)
    render = {"power+": 2, "health+": -1}
    runtime = {"cost": 1, "stats": "", "keywords": [], "render": render,
               "enhance": 0, "quest": None, "playable": True, "usage": []}
    monkeypatch.setattr(view, "hand_info", lambda: {card.uid: runtime})
    form_id = 10010151
    form = F.card(form_id, token=True, card_type="form", form_power=3, form_health=5)
    db.cards[form_id] = form
    shiki = view.game.current.shikigami[2]
    shiki.form = CardInstance(uid=10000, id=form_id)
    shiki.perm_power = 2
    shiki.health = 3
    calls.clear()
    view.refresh()
    settle(view)
    assert (view.db.cards[card.id], render, "purple") in calls
    assert (shiki, 2, form) in entity_calls


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


def test_mulligan_click_selects_then_card_button_replaces(qapp, view):
    start(view)
    scene = view.battle_scene
    card = view.game.current.hand[0]
    item = scene.cards[("hand", card.uid)]
    assert item.playable
    drop = item.scenePos() + QPointF(-180, -160)
    scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    assert card in view.game.state.players[0].hand
    assert scene.mulligan_uid == card.uid
    assert item.scale() > 1
    assert view.mulligan_button.text() == "替换"
    assert not view.mulligan_button.isHidden()
    button_rect = scene.mulligan_item.sceneBoundingRect()
    card_rect = item.sceneBoundingRect()
    assert abs(button_rect.center().x() - card_rect.center().x()) < 1
    assert button_rect.top() >= card_rect.bottom()
    view.mulligan_button.click()
    settle(view)
    assert card not in view.game.state.players[0].hand
    assert scene.mulligan_uid is None


def test_mulligan_centers_large_hand_and_shows_turn_order(qapp, view):
    start(view)
    scene = view.battle_scene
    items = scene_items(view, "hand", player=0)
    rects = [item.sceneBoundingRect() for item in items]
    center_x = (min(rect.left() for rect in rects) + max(rect.right() for rect in rects)) / 2
    assert abs(center_x - scene.sceneRect().center().x()) < 1
    assert all(rect.center().y() < 600 for rect in rects)
    assert all(item.default_size.width() >= 170 for item in items)
    assert getattr(view, "order_label", None) is not None
    assert view.order_label.text() == "己方先手"
    assert view.order_label.isHidden()


def test_last_mulligan_reviews_result_before_handoff(qapp, view):
    start(view)
    for index in range(3):
        card = view.game.state.players[0].hand[0]
        assert view.mulligan(card.uid)
        if index < 2:
            settle(view)
    assert view._handoff_pending
    assert scene_items(view, "hand", player=0)
    labels = view.handoff_dialog.findChildren(QLabel)
    assert any("调度次数已用完" in label.text() for label in labels)
    view.confirm_handoff()
    settle(view)
    assert view.viewer == 1
    assert scene_items(view, "hand", player=1)


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
    assert not scene.menu_item.isVisible()
    assert scene.ready_item.pos() == QPointF(1328, 435)
    assert view.end_turn_button.minimumWidth() == view.end_turn_button.maximumWidth()
    assert view.end_turn_button.minimumHeight() == view.end_turn_button.maximumHeight()
    assert view.end_turn_button.minimumWidth() == view.end_turn_button.minimumHeight()
    assert view.end_turn_button.minimumWidth() >= 88
    assert view.enemy_hand_label.text() == (
        f"敌方手牌\n{len(view.game.state.players[1].hand)} 张")
    assert view.enemy_deck_label.text() == f"敌方牌库\n{len(view.game.state.players[1].deck)} 张"
    assert view.own_deck_label.text() == f"己方牌库\n{len(view.game.state.players[0].deck)} 张"
    assert view.hand_caption.text() == f"己方手牌\n{len(view.game.current.hand)}/12 张"


def test_preparation_spread_centers_combat_and_symmetric_hand_captions(qapp, view):
    from client.gui.battle_scene import SCENE_HEIGHT, SCENE_WIDTH, SHIKI_SIZE, layout_positions

    start(view, mulligan=False)
    positions = layout_positions(view.game, view.viewer)
    own_x = [positions[("shiki", 0, index)].x() for index in range(4)]
    assert own_x[0] < 400
    assert own_x[2] - own_x[1] > own_x[1] - own_x[0]
    ready_center = (own_x[0] + own_x[-1] + SHIKI_SIZE.width()) / 2
    combat_center = positions[("shiki", 0, 0)].x() + SHIKI_SIZE.width() / 2
    view.game.state.players[0].combat_index = 0
    combat_positions = layout_positions(view.game, view.viewer)
    combat_center = combat_positions[("shiki", 0, 0)].x() + SHIKI_SIZE.width() / 2
    assert ready_center == combat_center == SCENE_WIDTH / 2
    enemy = positions[("enemy_hand_label",)]
    own = positions[("hand_caption",)]
    assert own.x() == enemy.x()
    assert own.y() + enemy.y() + 64 == SCENE_HEIGHT


def test_deck_count_labels_sit_right_of_card_backs(qapp, view):
    from client.gui.battle_scene import DECK_BACK_SIZE, SCENE_WIDTH, layout_positions

    start(view, mulligan=False)
    positions = layout_positions(view.game, view.viewer)
    for player, key in ((0, "own_deck"), (1, "enemy_deck")):
        right = max(positions[("deck_back", player, index)].x()
                    for index in range(3)) + DECK_BACK_SIZE.width()
        label = positions[(key,)]
        assert label.x() >= right
        assert label.x() + 68 <= SCENE_WIDTH


def test_end_turn_has_distinct_disabled_style(qapp, view):
    view.apply_theme("light", THEMES["light"])
    assert "QPushButton#endTurnButton:disabled" in view.styleSheet()


def test_hotseat_new_games_use_random_seeds(qapp, view, monkeypatch):
    from types import SimpleNamespace
    import client.gui.battle as battle_module

    seeds = iter((42, 43))
    monkeypatch.setattr(battle_module, "secrets", SimpleNamespace(
        randbits=lambda _bits: next(seeds)), raising=False)
    seen = []
    original = battle_module.new_game

    def record_seed(*args, **kwargs):
        seen.append(kwargs["seed"])
        return original(*args, **kwargs)

    monkeypatch.setattr(battle_module, "new_game", record_seed)
    openings = []
    for _ in range(2):
        view.start_game(player_tuple("玩家A"), player_tuple("玩家B"),
                        first=0, shuffle_team=False)
        openings.append([card.id for card in view.game.state.players[0].hand])
        settle(view)
    assert seen == [42, 43]
    assert openings[0] != openings[1]


def test_deck_backs_are_symmetric_horizontal_cards_and_hide_when_empty(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert len(getattr(scene, "deck_backs", {})) == 6
    own = [scene.deck_backs[("deck_back", 0, index)] for index in range(3)]
    enemy = [scene.deck_backs[("deck_back", 1, index)] for index in range(3)]
    assert all(item.size.width() > item.size.height() for item in own + enemy)
    assert len({item.x() for item in own}) == 3
    assert len({item.y() for item in own}) == 3
    assert len({item.rotation() for item in own}) == 3
    for lower, upper in zip(own, enemy):
        assert lower.x() == upper.x()
        assert lower.y() + upper.y() + lower.size.height() == 900
        assert lower.rotation() == -upper.rotation()
    view.game.state.players[0].deck.clear()
    view.refresh()
    settle(view)
    assert not any(key[0] == "deck_back" and key[1] == 0 for key in scene.deck_backs)
    assert any(key[0] == "deck_back" and key[1] == 1 for key in scene.deck_backs)


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
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert all(not text.startswith(("所属式神：", "子类型：")) for text in labels)
    assert dialog.mechanism_panel is not None
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

    def capture_pixmap(card_def, database, *, display=None, level_color=None, height=None):
        seen.update(card_def=card_def, database=database, display=display,
                    level_color=level_color)
        return None

    monkeypatch.setattr(widgets, "card_pixmap", capture_pixmap)
    dialog = CardDetailDialog(cdef, db, runtime={"render": {"power+": 1, "health+": -2}})
    assert seen == {"card_def": cdef, "database": db,
                    "display": {"power+": 1, "health+": -2}, "level_color": None}
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
    assert "战斗修正" not in text
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
    start(view, mulligan=False)
    scene = view.battle_scene
    assert scene.log_item.widget() is view.log_button
    assert scene.log_item.x() == 1
    assert scene.log_item.y() == 422
    assert view.log_button.width() == view.log_button.height() == 32
    assert view.log_button.text() == "对局\n记录"
    view.apply_theme("light", THEMES["light"])
    style = view.log_button.styleSheet()
    assert "border-radius: 16px" in style
    assert f"background: {THEMES['light']['panel']}" in style
    assert f"color: {THEMES['light']['text']}" in style
    assert f"border: 1px solid {THEMES['light']['gold']}" in style
    assert view.phase_label.text() == "玩家A 回合1"
    phase_proxy = next(item for item in scene.items()
                       if hasattr(item, "widget") and item.widget() is view.phase_label)
    assert phase_proxy.x() > scene.log_item.x()
    assert phase_proxy.y() == scene.log_item.y()
    assert view.order_label.isHidden()
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
    assert view.phase_label.text() == "玩家A 回合1"
    assert not view.upgrade_label.isHidden()
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


def test_newly_upgraded_action_legality(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    game = view.game
    card = F.give(game, 0, 10010201)
    view.refresh()
    settle(view)
    view.upgrade(1)
    settle(view)
    assert game.current.shikigami[1].level == 1
    assert view.battle_scene.cards[("shiki", 0, 1)].playable
    assert not view.battle_scene.cards[("shiki", 0, 2)].playable
    assert game.assault_error(0, 1) is None
    assert "未在场" in game.assault_error(0, 2)
    assert view.battle_scene.cards[("hand", card.uid)].playable
    game.current.orb = 2
    view.play_card(card.uid)
    settle(view)
    assert card not in game.current.hand
    view.assault(1)
    settle(view)
    assert game.current.combat_index == 1


def test_extra_upgrade_blocks_actions_until_complete(qapp, view):
    start(view, mulligan=False,
          config=GameConfig(auto_skip_upgrade=False, extra_upgrade_turns=(1, 3)))
    game = view.game
    assert game.current.upgrades == 2
    view.upgrade(1)
    settle(view)
    assert game.state.phase == "upgrade"
    assert not view.battle_scene.cards[("shiki", 0, 1)].playable
    assert view.battle_scene.cards[("shiki", 0, 2)].playable
    assert all(not item.playable for item in scene_items(view, "hand", player=0))
    view.upgrade(2)
    settle(view)
    assert game.state.phase == "battle"
    assert view.battle_scene.cards[("shiki", 0, 1)].playable


def test_upgrade_with_defeated_shikigami_keeps_hand_usable(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    game = view.game
    game.current.shikigami[0].defeated = True
    card = F.give(game, 0, 10010201)
    view.upgrade(1)
    settle(view)
    assert game.state.phase == "battle"
    assert "气绝" in game.assault_error(0, 0)
    assert view.battle_scene.cards[("hand", card.uid)].playable


def test_battle_timeline_not_duplicated_in_application_log(qapp, view, caplog):
    import logging

    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    with caplog.at_level(logging.INFO, logger="bwpro.battle"):
        view.upgrade(1)
        settle(view)
    assert not any(record.message.startswith("HotseatView")
                   and "升至 1 级" in record.message for record in caplog.records)


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


def test_hotseat_exit_requires_confirmation(qapp, view, monkeypatch):
    returned = []
    answers = iter((QMessageBox.No, QMessageBox.Yes))
    monkeypatch.setattr("client.gui.battle.ask_confirmation",
                        lambda *_args: next(answers))
    view.on_back = lambda: returned.append(True)
    start(view, mulligan=False)
    assert not view.return_to_menu()
    assert returned == []
    assert view.return_to_menu()
    assert returned == [True]


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
    assert not win.game_menu_button.isHidden()
    assert not win.pages["hotseat"].battle_scene.menu_item.isVisible()
    win.toggle_theme()
    assert win.pages["hotseat"].theme == "dark"
    win.pages["hotseat"].timeline_timer.start()
    win.back_button.click()
    assert win.stack.currentIndex() == 0
    assert win.game_menu_button.isHidden()
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


def test_actions_remain_available_during_timeline(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    view.upgrade(1)
    assert view.timeline_queue
    assert view._inputs_open()
    assert view.end_turn_button.isEnabled()
    assert view.end_turn()
    assert view.game.state.active == 1


def test_shiki_position_animation_reaches_layout_target(qapp, view):
    from PySide6.QtCore import QEasingCurve
    from client.gui.battle_scene import layout_positions

    start(view, mulligan=False)
    scene = view.battle_scene
    key = ("shiki", 0, 0)
    item = scene.cards[key]
    old_pos = QPointF(item.pos())
    assert not scene._move_animations

    view.game.current.combat_index = 0
    view.refresh()
    animation = scene._move_animations[item]
    target = layout_positions(view.game, view.viewer)[key]
    assert animation.startValue() == old_pos
    assert animation.endValue() == target
    assert animation.easingCurve().type() == QEasingCurve.Linear

    item.setPos(target)
    view.game.current.combat_index = None
    view.refresh()
    replacement = scene._move_animations[item]
    assert animation.state() == animation.State.Stopped
    animation = replacement
    target = layout_positions(view.game, view.viewer)[key]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert item.pos() == target
    assert item not in scene._move_animations


def test_drag_stops_shiki_position_animation(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.current.combat_index = 0
    view.refresh()
    item = scene.cards[("shiki", 0, 0)]
    animation = scene._move_animations[item]
    origin = item.scenePos()
    assert scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(160, -80))
    assert scene.drag_controller.dragged
    assert animation.state() == animation.State.Stopped
    assert item not in scene._move_animations


def test_card_use_animation_for_both_players_is_nonblocking_and_cleans_up(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    played_before = list(view.played_timeline)
    cards = [view.game.state.players[pi].hand[0] for pi in (0, 1)]
    old_positions = {card.uid: QPointF(scene.cards[("hand", card.uid)].pos())
                     for card in cards}
    view.game.state.timeline.extend(
        {"k": "a", "u": card.uid, "c": card.id, "p": pi}
        for pi, card in enumerate(cards))
    view._enqueue_timeline()

    assert not view.timeline_queue
    assert view._inputs_open()
    assert len(scene._card_use_animations) == 2
    assert [item.cdef.id for item in scene._card_use_items.values()] == [
        card.id for card in cards]
    assert [item.player for item in scene._card_use_items.values()] == [0, 1]
    assert [item.pos() for item in scene._card_use_items.values()] == [
        old_positions[card.uid] for card in cards]

    for animation in list(scene._card_use_animations):
        animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert not scene._card_use_animations
    assert not scene._card_use_items
    assert view.played_timeline == played_before


def test_enemy_card_use_animation_paints_card_back_before_flip(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[1].hand[0]
    assert scene.cards[("hand", card.uid)].pixmap is None
    view.game.state.timeline.append({"k": "a", "u": card.uid, "c": card.id, "p": 1})
    view._enqueue_timeline()
    animation = scene._card_use_animations[0]
    item = scene._card_use_items[animation]
    animation.setCurrentTime(int(animation.duration() * 0.1))

    image = QImage(item.size.toSize(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert any(image.pixelColor(x, y).alpha() > 0
               for x in range(image.width()) for y in range(image.height()))
    assert not item.revealed
    animation.setCurrentTime(int(animation.duration() * 0.5))
    assert item.revealed
    animation.setCurrentTime(animation.duration())


def test_viewer_handoff_and_restart_clear_animations(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.current.combat_index = 0
    view.refresh()
    assert scene._move_animations

    card = view.game.state.players[0].hand[0]
    view.game.state.timeline.append({"k": "a", "u": card.uid, "c": card.id, "p": 0})
    view.game.state.active = 1
    view.refresh()
    assert view._handoff_pending
    assert not scene._move_animations
    assert not scene._card_use_animations
    view.confirm_handoff()
    assert not scene._move_animations

    card = view.game.state.players[1].hand[0]
    view.game.state.timeline.append({"k": "a", "u": card.uid, "c": card.id, "p": 1})
    view._enqueue_timeline()
    assert scene._card_use_animations
    start(view, mulligan=False)
    assert not scene._move_animations
    assert not scene._card_use_animations
    assert not scene._card_use_items


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
    assert scene.drag_controller.drag_ghost is not None
    view.game.state.active = 1
    view.refresh()
    assert view._handoff_pending
    assert scene.drag_controller.drag_ghost is None
    assert scene.drag_controller.drag_arrow is None
    assert not any(key[0] == "hand" for key in scene.cards)
    view.confirm_handoff()
    expected = {card.uid for player in view.game.state.players for card in player.hand}
    hand_items = {key[1]: item for key, item in scene.cards.items() if key[0] == "hand"}
    assert set(hand_items) == expected
    assert {card.uid for card in view.game.state.players[1].hand} == {
        uid for uid, item in hand_items.items() if item.revealed}


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

    view.game.state.phase = "upgrade"
    view.refresh()
    settle(view)
    qapp.processEvents()
    assert view.grab().save(str(output / "upgrade.png"))
    view.game.state.phase = "battle"
    view.refresh()
    settle(view)

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
