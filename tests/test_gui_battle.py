"""桌面 GUI 本地热坐对战测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFontMetrics, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QScrollArea,
)

from client.gui.app import THEMES, MainWindow
from client.gui.battle import DeckSelectDialog, HotseatView
from client.gui.widgets import CardDetailDialog, CardWidget
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
    scene = view.battle_scene
    while scene._visual_queue or scene._visual_animations:
        for animation in list(scene._visual_animations):
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
        assert not hasattr(dialog, "runtime_label")
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
    assert scene.cards[("player", 1)].pos() == QPointF(12, 4)
    assert scene.cards[("player", 0)].pos() == QPointF(12, 766)
    assert [scene.cards[("shiki", 1, index)].y() for index in range(4)] == [
        120, 86, 86, 120]
    assert [scene.cards[("shiki", 0, index)].y() for index in range(4)] == [
        570, 604, 604, 570]
    assert [scene.cards[("shiki", 0, index)].x() for index in range(4)] == [
        196, 421, 871, 1096]
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


def test_hand_layout_spacing_and_half_height(qapp, view):
    from client.gui.battle_scene import HAND_SIZE, layout_positions

    start(view, mulligan=False)
    enemy = view.game.state.players[1]
    for count, spacing in ((8, 70), (9, 490 / 8), (12, 490 / 11)):
        enemy.hand[:] = [card.model_copy(update={"uid": 1000 + i, "hand_seq": i + 1})
                         for i, card in enumerate((enemy.hand * 3)[:count])]
        positions = layout_positions(view.game, view.viewer)
        points = [positions[("hand", card.uid)] for card in enemy.hand]
        assert [points[i + 1].x() - points[i].x() for i in range(count - 1)] == pytest.approx(
            [spacing] * (count - 1))
        assert points[-1].x() + HAND_SIZE.width() == 1588
        assert points[-1].x() - points[0].x() + HAND_SIZE.width() == 600
        assert all(point.y() == -78 for point in points)

    own_points = [layout_positions(view.game, view.viewer)[("hand", card.uid)]
                  for card in view.game.state.players[0].hand]
    assert all(point.y() == 822 for point in own_points)
    view.game.state.phase = "mulligan"
    mulligan_points = [layout_positions(view.game, view.viewer)[("hand", card.uid)]
                       for card in view.game.state.players[0].hand]
    assert all(point.y() == 280 for point in mulligan_points)


def test_hand_layout_shifts_shikigami_slots_left(qapp, view):
    from client.gui.battle_scene import layout_positions

    start(view, mulligan=False)
    positions = layout_positions(view.game, view.viewer)
    assert [positions[("shiki", 0, index)].x() for index in range(4)] == [
        196, 421, 871, 1096]
    view.game.state.players[0].combat_index = 0
    assert layout_positions(view.game, view.viewer)[("shiki", 0, 0)].x() == 646


def test_hand_spacing_twelve_cards_avoid_shikigami_and_keep_placeholder(qapp, view):
    start(view, mulligan=False)
    for pi in (1, 0):
        player = view.game.state.players[pi]
        player.hand[:] = [card.model_copy(update={"uid": 1000 + pi * 100 + i,
                                                  "hand_seq": i + 1})
                          for i, card in enumerate((player.hand * 3)[:12])]
        view.refresh()
        settle(view)
        items = sorted((view.battle_scene.cards[("hand", card.uid)] for card in player.hand),
                       key=lambda item: item.x())
        assert len(items) == 12
        assert items[1].x() < items[0].x() + items[0].boundingRect().width()
        assert items[1].x() - items[0].x() == pytest.approx(490 / 11)
        assert items[-1].x() + items[-1].boundingRect().width() <= 1612
        shiki_items = [view.battle_scene.cards[("shiki", pi, index)] for index in range(4)]
        assert all(not hand.sceneBoundingRect().intersects(shiki.sceneBoundingRect())
                   for hand in items for shiki in shiki_items)
    shiki = view.battle_scene.cards[("shiki", 0, 0)]
    assert "力量" in shiki.shiki_text and "生命" in shiki.shiki_text
    assert "等级" in shiki.shiki_text


@pytest.mark.parametrize("auto_skip_upgrade", [True, False], ids=["battle", "upgrade"])
def test_hand_spacing_highlighted_fallback_cards_avoid_shikigami(
        qapp, view, auto_skip_upgrade):
    from client.gui.battle_scene import HAND_SIZE

    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=auto_skip_upgrade))
    if auto_skip_upgrade:
        view.game.current.orb = 1
    for pi in (1, 0):
        player = view.game.state.players[pi]
        player.hand[:] = [card.model_copy(update={"uid": 2000 + pi * 100 + i,
                                                  "hand_seq": i + 1})
                          for i, card in enumerate((player.hand * 3)[:12])]
        if auto_skip_upgrade and pi == 0:
            player.hand[0] = player.hand[0].model_copy(update={"id": 10010101})
        view.refresh()
        settle(view)
        hands = [view.battle_scene.cards[("hand", card.uid)] for card in player.hand]
        shikigami = [view.battle_scene.cards[("shiki", pi, index)] for index in range(4)]
        if pi == 0:
            assert any(item.playable for item in shikigami)
            if auto_skip_upgrade:
                assert any(item.playable for item in hands)
        for item in hands:
            item.set_art(None)
            item.playable = True
            item.update()
        for item in shikigami:
            item.targetable = True
            item.update()
        assert all(item.size == HAND_SIZE for item in hands)
        assert all(not hand.sceneBoundingRect().intersects(shiki.sceneBoundingRect())
                   for hand in hands for shiki in shikigami)


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


def test_scene_render_checks_resources_once_per_changed_sync(qapp, view, monkeypatch):
    from client.gui import cardart

    start(view, mulligan=False)
    calls = []
    original = cardart._renderer_resource_digest

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(cardart, "_renderer_resource_digest", counted)
    view.refresh()
    assert calls == []
    for player in view.game.state.players:
        for shiki in player.shikigami:
            shiki.health -= 1
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


def test_battle_page_has_zero_outer_margins(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    hotseat = win.pages["hotseat"]
    online = win.pages["online"]

    def margins():
        value = win.centralWidget().layout().contentsMargins()
        return value.left(), value.top(), value.right(), value.bottom()

    def chrome_margins():
        value = win.outer.itemAt(0).layout().contentsMargins()
        return value.left(), value.top(), value.right(), value.bottom()

    win.go("hotseat")
    assert margins() == (12, 12, 12, 12)
    assert chrome_margins() == (0, 0, 0, 0)
    hotseat.stack.setCurrentWidget(hotseat.battle_page)
    assert margins() == (0, 0, 0, 0)
    assert chrome_margins() == (12, 12, 12, 0)
    win.go("builder")
    assert margins() == (12, 12, 12, 12)
    assert chrome_margins() == (0, 0, 0, 0)
    win.go("online")
    online.stack.setCurrentWidget(online.battle)
    assert margins() == (0, 0, 0, 0)
    assert chrome_margins() == (12, 12, 12, 0)
    online.stack.setCurrentWidget(online.connect_page)
    assert margins() == (12, 12, 12, 12)
    assert chrome_margins() == (0, 0, 0, 0)
    win.go_menu()
    assert margins() == (12, 12, 12, 12)
    assert chrome_margins() == (0, 0, 0, 0)
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
    free_option, paid_option, gated_option = 10010153, 10010154, 10010155
    game.db.cards[free_option] = F.card(free_option, token=True, cost=0, level=0)
    game.db.cards[paid_option] = F.card(paid_option, token=True, cost=1, level=0)
    game.db.cards[gated_option] = F.card(gated_option, token=True, cost=1, level=3)
    game.db.cards[10010161] = F.card(
        10010161, token=True, card_type="reinforce", shikigami2=100102,
        options=[free_option, gated_option])
    game.db.cards[10010162] = F.card(
        10010162, token=True, card_type="reinforce", shikigami2=100102,
        options=[paid_option, gated_option])
    free = F.give(game, 0, 10010151)
    multi = F.give(game, 0, 10010152)
    single_free = F.give(game, 0, 10010161)
    single_paid = F.give(game, 0, 10010162)
    view.refresh(); settle(view)
    assert view.battle_scene.cards[("hand", free.uid)].border_color == "blue"
    assert view.battle_scene.cards[("hand", multi.uid)].border_color == "green"
    assert view.battle_scene.cards[("hand", single_free.uid)].border_color == "blue"
    assert view.battle_scene.cards[("hand", single_paid.uid)].border_color == "yellow"
    assert view.battle_scene.cards[("shiki", 0, 0)].border_color == "yellow"


def test_playable_card_uses_alpha_contour_glow_not_tight_box(qapp):
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPixmap
    from client.gui.battle_scene import BattleCardItem

    pixmap = QPixmap(40, 60)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(Qt.white)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(8, 4, 24, 52)
    painter.end()
    item = BattleCardItem(("hand", 99), size=QSizeF(40, 60))
    item.set_art(pixmap)

    def render():
        image = QImage(item.size.toSize(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        return image

    item.playable = True
    assert item._operation_glow_color().name() == "#d9b96a"
    glowing = render()
    assert glowing.pixelColor(2, 2).alpha() == 0
    assert glowing.pixelColor(5, 30).alpha() > 0
    item.playable = False
    plain = render()
    assert plain.pixelColor(2, 2).alpha() == 0
    assert plain.pixelColor(5, 30).alpha() == 0


def test_operation_glow_bounds_cover_scene_update_region(qapp):
    from PySide6.QtCore import QRectF, QSizeF
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QGraphicsScene
    from client.gui.battle_scene import BattleCardItem

    item = BattleCardItem(("hand", 99), size=QSizeF(40, 60))
    item.set_art(QPixmap(40, 60))
    scene = QGraphicsScene()
    scene.addItem(item)
    item.playable = True
    scene.update()
    assert item.boundingRect() == QRectF(-4, -4, 48, 68)
    item.playable = False
    item.update()
    assert item.boundingRect() == QRectF(0, 0, 40, 60)


def test_phase_label_shows_two_lines_and_remaining_upgrades(qapp, view):
    start(view, mulligan=False,
          config=GameConfig(auto_skip_upgrade=False, extra_upgrade_turns=(1, 3)))
    game = view.game
    assert view._phase_lines() == ("玩家A 回合1", "升级阶段·剩余 2 次")
    assert view.phase_label.textFormat() == Qt.RichText
    assert "玩家A 回合1" in view.phase_label.text()
    assert '<div style="font-size:20px">升级阶段·剩余 2 次</div>' in view.phase_label.text()
    assert not hasattr(view.battle_scene, "upgrade_item")
    view.upgrade(1)
    settle(view)
    assert game.current.upgrades == 1
    assert view._phase_lines() == ("玩家A 回合1", "升级阶段·剩余 1 次")
    assert '<div style="font-size:20px">升级阶段·剩余 1 次</div>' in view.phase_label.text()


@pytest.mark.parametrize("attribute", ["keywords", "one_shot_keywords", "perm_keywords"])
def test_haste_assault_border_is_blue_for_all_keyword_sources(qapp, view, attribute):
    start(view, mulligan=False)
    shiki = view.game.current.shikigami[0]
    getattr(shiki, attribute).append("haste")
    view.refresh()
    settle(view)
    item = view.battle_scene.cards[("shiki", 0, 0)]
    assert item.playable
    assert item.border_color == "blue"


def test_haste_upgrade_border_remains_yellow(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    view.game.current.shikigami[1].one_shot_keywords.append("haste")
    view.refresh()
    settle(view)
    item = view.battle_scene.cards[("shiki", 0, 1)]
    assert view.game.state.phase == "upgrade"
    assert item.playable
    assert item.border_color == "yellow"


def test_one_shot_haste_border_returns_yellow_after_assault(qapp, view):
    start(view, mulligan=False)
    shiki = view.game.current.shikigami[0]
    shiki.one_shot_keywords.append("haste")
    view.refresh()
    settle(view)
    assert view.battle_scene.cards[("shiki", 0, 0)].border_color == "blue"
    view.assault(0)
    settle(view)
    assert "haste" not in shiki.one_shot_keywords
    assert view.battle_scene.cards[("shiki", 0, 0)].border_color == "yellow"


@pytest.mark.parametrize("replace_all", [False, True], ids=["ready", "third-replacement"])
def test_mulligan_handoff_centers_review_for_each_player(qapp, view, replace_all):
    start(view)
    for pi in (0, 1):
        if replace_all:
            for replacement in range(3):
                view.mulligan(view.game.state.players[view.viewer].hand[0].uid)
                if replacement < 2:
                    settle(view)
        else:
            view.ready()
        assert view.battle_scene.viewer == pi
        assert view._handoff_stage == "review"
        assert view.handoff_dialog is None
        assert view.battle_scene.handoff_item.isVisible()
        assert not view.battle_scene.ready_item.isVisible()
        assert view.battle_scene.handoff_item.pos() == view.battle_scene.ready_item.pos()
        assert view.handoff_button.text() == "切换玩家"
        old_hand_items = scene_items(view, "hand", player=pi)
        assert old_hand_items and all(item.y() == 280 for item in old_hand_items)
        if pi == 1:  # 后手交接预览不重排入手顺序
            assert [item.uid for item in sorted(old_hand_items, key=lambda item: item.x())] == [
                card.uid for card in sorted(view.game.state.players[1].hand,
                                            key=lambda card: card.hand_seq)]
        view.handoff_button.click()
        assert view._handoff_stage == "transfer"
        assert view.battle_scene.handoff_item.isVisible()
        assert all(item.scene() is None for item in old_hand_items)
        view.handoff_button.click()
        assert not view.battle_scene.handoff_item.isVisible()
    assert view.game.state.phase != "mulligan"


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


def test_hand_deck_text_contrast_and_visible_outer_margins(qapp, view):
    start(view, mulligan=False)
    view.apply_theme("light", THEMES["light"])
    for label in (view.enemy_hand_label, view.enemy_deck_label,
                  view.own_deck_label, view.hand_caption, view.phase_label,
                  view.order_label, view.upgrade_label):
        assert f"color: {THEMES['light']['text']}" in label.styleSheet()
        assert "font-weight: 600" in label.styleSheet()
    for button in (view.log_button, view.ready_button, view.result_back):
        assert button.testAttribute(Qt.WA_TranslucentBackground)
        assert f"color: {THEMES['light']['text']}" in button.styleSheet()
    assert view.end_turn_button.testAttribute(Qt.WA_TranslucentBackground)
    scene = view.battle_scene
    assert scene.cards[("player", 0)].x() == 12
    assert scene.log_item.x() == 12
    hand = max((item for key, item in scene.cards.items()
                if key[0] == "hand" and item.player == 0), key=lambda item: item.x())
    assert hand.x() + hand.size.width() == 1588
    assert scene.end_turn_item.x() + 104 == 1588

    from client.gui.battle_scene import HAND_SIZE, layout_positions
    wide = layout_positions(view.game, view.viewer, scene_width=1800)
    rightmost_hand = max(wide[("hand", card.uid)].x()
                         for card in view.game.current.hand) + HAND_SIZE.width()
    assert rightmost_hand == 1788
    assert wide[("end_turn",)].x() + 104 == 1788


def test_summoned_fifth_shikigami_keeps_refresh_and_next_upgrade_available(qapp, db, view):
    """召唤物只占战斗区、不改变准备区座次，离场后不保留气绝小卡。"""
    from client.gui.battle_scene import layout_positions

    summon_id = 900001
    card_id = 10010151
    db.shikigami[summon_id] = F.shiki(summon_id, kind="summon")
    db.cards[card_id] = F.card(
        card_id, token=True, steps=[F.Step(op="summon", shikigami=summon_id)])
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    view.upgrade(1)
    settle(view)
    card = F.give(view.game, 0, card_id)
    view.refresh()
    settle(view)
    ready_before = [layout_positions(view.game, view.viewer)[("shiki", 0, index)]
                    for index in range(4)]

    assert view.play_card(card.uid)
    settle(view)
    game = view.game
    assert len(game.state.players[0].shikigami) == 5
    positions = layout_positions(game, view.viewer)
    summon_key = ("shiki", 0, 4)
    assert [positions[("shiki", 0, index)] for index in range(4)] == ready_before
    assert positions[summon_key].x() == 646 and positions[summon_key].y() == 460
    assert view.battle_scene.cards[summon_key].pos() == positions[summon_key]

    summoned = game.state.players[0].shikigami[4]
    summoned.health = 0
    game.check_defeated(Ref(player=0, shikigami=4), reason="测试")
    game._drain_queue()
    assert summoned.despawned and game.state.players[0].combat_index is None

    view.refresh()
    settle(view)
    assert summon_key not in view.battle_scene.cards
    assert summon_key not in layout_positions(game, view.viewer)
    assert view.end_turn()
    settle(view)

    assert game.state.active == view.viewer == 1
    assert game.state.phase == "upgrade"
    legal = game.legal_upgrade_indices(1)
    assert legal
    assert view.battle_scene.cards[("shiki", 1, legal[0])].playable
    assert view.upgrade(legal[0])
    settle(view)
    assert game.state.phase == "battle"


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


def test_player_item_paints_health_and_signed_shield_icons(qapp, view, monkeypatch):
    from client.gui import battle_scene

    start(view, mulligan=False)
    view.game.current.shield = -3
    view.refresh()
    item = view.battle_scene.cards[("player", view.viewer)]
    used = []
    original = battle_scene.ui_pixmap

    def recording_pixmap(relative, **kwargs):
        used.append(relative)
        return original(relative, **kwargs)

    monkeypatch.setattr(battle_scene, "ui_pixmap", recording_pixmap)
    image = QImage(240, 150, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert "stats/health.png" in used
    assert "stats/shield.png" in used


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


def test_scene_card_art_preserves_ratio_and_visible_outer_margins(qapp, view):
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
    assert scene.cards[("player", 0)].x() == 12
    own_hand = max((item for key, item in scene.cards.items()
                    if key[0] == "hand" and item.player == 0), key=lambda item: item.x())
    assert own_hand.x() + own_hand.size.width() == 1588


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
    assert view._phase_lines()[1] == "升级阶段·剩余 1 次"
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
    assert scene.focus_overlay.path().elementCount() > 40  # 轮廓而非矩形孔洞
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


def test_player_orb_and_turn_button_stay_bounded(qapp, view):
    start(view, mulligan=False)
    view.apply_theme("light", THEMES["light"])
    player = view.game.current
    player.orb = 6
    player.graveyard.extend(list(player.hand[:2])
                            if isinstance(player.graveyard, list) else [])
    view.refresh()
    settle(view)
    item = view.battle_scene.cards[("player", 0)]
    assert item.orb == 4
    assert item.orb_display_count == 4
    assert item.orb_overflow == 0
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


def test_scene_hand_and_controls_fit_horizontally_1600x900(qapp, db, tmp_path, monkeypatch):
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
            rect = item.sceneBoundingRect()
            assert scene.sceneRect().left() <= rect.left()
            assert rect.right() <= scene.sceneRect().right()
        for proxy in (scene.menu_item, scene.log_item, scene.end_turn_item):
            assert scene.sceneRect().contains(
                proxy.sceneBoundingRect())
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
    assert item.size.height() == 210


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
    settle(view)
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
    assert enemy.pos() == QPointF(646, 220)
    assert own.pos() == QPointF(646, 460)


def test_battle_entities_use_diy_small_card_renderer(qapp, view, monkeypatch):
    from client.gui import battle_scene

    calls = []
    monkeypatch.setattr(battle_scene, "entity_pixmap",
                        lambda shiki, db, *, seat, form=None, cache_context=None, height=None, show_defeated_countdown=True:
                        calls.append((shiki, seat, form)), raising=False)
    start(view, mulligan=False)
    expected = {id(s) for p in view.game.state.players for s in p.shikigami}
    assert expected <= {id(call[0]) for call in calls}
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
    assert scene.banner_pixmap_item.property("assetName") == "your_turn_dark"
    assert scene.banner_pixmap_item.isVisible() and scene.banner_timer.isActive()
    scene.hide_banner()
    assert not scene.banner_item.isVisible() and not scene.banner_pixmap_item.isVisible()
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
    assert details == [] and calls == []
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

    def capture_entity(shiki, database, *, seat, form=None, cache_context=None, height=None, show_defeated_countdown=True):
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


@pytest.fixture
def render_calls(view, monkeypatch):
    from client.gui import battle_scene

    calls = {"entity": [], "card": [], "cardback": []}
    for name in ("entity_pixmap", "card_pixmap", "cardback_pixmap"):
        original = getattr(battle_scene, name)

        def capture(*args, _original=original, _name=name, **kwargs):
            calls[_name.removesuffix("_pixmap")].append((args, kwargs))
            return _original(*args, **kwargs)

        monkeypatch.setattr(battle_scene, name, capture)
    return calls


def clear_render_calls(calls):
    for entries in calls.values():
        entries.clear()


def test_scene_unchanged_render_signature_reuses_only_stable_art(
        qapp, db, view, render_calls, monkeypatch):
    form = F.card(10010151, token=True, card_type="form", form_power=3, form_health=5)
    db.cards[form.id] = form
    start(view, mulligan=False)
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert all(not entries for entries in render_calls.values())

    shiki = view.game.current.shikigami[0]
    for attribute, value in (("health", shiki.health - 1),
                             ("form", CardInstance(uid=10000, id=form.id)),
                             ("level", shiki.level + 1)):
        setattr(shiki, attribute, value)
        clear_render_calls(render_calls)
        view.refresh()
        settle(view)
        assert [call[0][0] for call in render_calls["entity"]] == [shiki]
        assert not render_calls["card"] and not render_calls["cardback"]

    card = view.game.current.hand[0]
    runtime = view.hand_info()
    monkeypatch.setattr(view, "hand_info", lambda: runtime)
    runtime[card.uid]["render"] = {"power+": 2, "health+": -1}
    runtime[card.uid]["keywords"] = [*runtime[card.uid]["keywords"], "瞬发"]
    usage = runtime[card.uid]["usage"]
    runtime[card.uid]["usage"] = [dict(option, cost=0) for option in usage]
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert [call[0][0].id for call in render_calls["card"]] == [card.id]
    assert not render_calls["entity"] and not render_calls["cardback"]


def test_scene_unchanged_render_signature_invalidates_snapshot_view_and_reset(
        qapp, view, render_calls):
    start(view, mulligan=False)
    scene = view.battle_scene
    shiki = view.game.current.shikigami[0]
    snapshot = dict(power=shiki.eff_power - shiki.combat_power,
                    health=shiki.health, max_health=shiki.max_health,
                    combat_power=shiki.combat_power, shield=shiki.shield,
                    defeated=shiki.defeated, countdown=shiki.countdown,
                    revive_countdown=shiki.revive_countdown, revive_pending=False)
    clear_render_calls(render_calls)
    scene.play_visual_event({"k": "v", "v": "stat", "p": 0, "s": 0, "r": snapshot})
    assert [call[0][0] for call in render_calls["entity"]] == [shiki]
    clear_render_calls(render_calls)
    for animation in list(scene._visual_animations):
        animation.setCurrentTime(animation.duration())
        qapp.processEvents()
    assert [call[0][0] for call in render_calls["entity"]] == [shiki]

    clear_render_calls(render_calls)
    view.viewer = 1
    view.refresh()
    settle(view)
    assert all(render_calls.values())

    clear_render_calls(render_calls)
    scene.reset_animations()
    view.refresh()
    settle(view)
    assert all(render_calls.values())


def test_scene_unchanged_render_signature_invalidates_visual_settings(
        qapp, view, render_calls, monkeypatch):
    from client.gui import battle_scene
    from client.gui.card_appearance import save_card_appearance
    from client.gui.ui_assets import load_gui_settings, named_cardbacks, save_gui_settings

    start(view, mulligan=False)
    scene = view.battle_scene
    clear_render_calls(render_calls)
    scene.set_text_color("#ffffff", "dark")
    view.refresh()
    settle(view)
    assert all(render_calls.values())

    card = view.game.current.hand[0]
    save_card_appearance(card.id, "blue")
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    matching_copies = sum(hand_card.id == card.id for hand_card in view.game.current.hand)
    assert [call[0][0].id for call in render_calls["card"]] == [card.id] * matching_copies
    assert not render_calls["entity"] and not render_calls["cardback"]

    view._review_mulligan = True
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert len(render_calls["card"]) == len(view.game.current.hand)
    assert not render_calls["entity"] and not render_calls["cardback"]

    view._review_mulligan = False
    view.refresh()
    settle(view)
    enemy_card = view.game.state.players[1].hand[0]
    enemy_card.mods["revealed"] = True
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert [call[0][0].id for call in render_calls["card"]] == [enemy_card.id]

    original_owner_seat = battle_scene.card_owner_seat
    monkeypatch.setattr(
        battle_scene, "card_owner_seat",
        lambda game, player, cdef: 2 if cdef is not None and cdef.id == card.id
        else original_owner_seat(game, player, cdef))
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert [call[0][0].id for call in render_calls["card"]] == [card.id] * matching_copies

    settings = load_gui_settings()
    settings["enemy_cardback"] = next(
        name for name in named_cardbacks() if name != settings["enemy_cardback"])
    save_gui_settings(settings)
    clear_render_calls(render_calls)
    scene.refresh_cardbacks()
    expected_enemy_backs = len(scene.deck_backs) // 2 + len(view.game.state.players[1].hand) - 1
    assert len(render_calls["cardback"]) == expected_enemy_backs
    assert not render_calls["entity"] and not render_calls["card"]
    clear_render_calls(render_calls)
    view.refresh()
    settle(view)
    assert all(not entries for entries in render_calls.values())


def test_scene_reset_then_resize_without_game(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert scene.deck_backs
    scene.reset_animations()
    assert scene.game is None
    scene.set_viewport_size(2000, 900)
    assert scene.layout_width == 2000


def test_scene_failed_render_is_retried_without_redrawing_successes(qapp, view, monkeypatch):
    from client.gui import battle_scene

    start(view, mulligan=False)
    scene = view.battle_scene
    shiki = view.game.current.shikigami[0]
    card = view.game.current.hand[0]
    original_entity = battle_scene.entity_pixmap
    original_card = battle_scene.card_pixmap
    failures = {"entity": True, "card": True}
    entity_attempts = []
    card_attempts = []

    def fail_entity_once(*args, **kwargs):
        entity_attempts.append(args[0])
        if failures["entity"] and args[0] is shiki:
            failures["entity"] = False
            return None
        return original_entity(*args, **kwargs)

    def fail_card_once(*args, **kwargs):
        card_attempts.append(args[0].id)
        if failures["card"] and args[0].id == card.id:
            failures["card"] = False
            return None
        return original_card(*args, **kwargs)

    monkeypatch.setattr(battle_scene, "entity_pixmap", fail_entity_once)
    monkeypatch.setattr(battle_scene, "card_pixmap", fail_card_once)
    scene.reset_animations()
    view.refresh()
    assert scene.cards[("shiki", 0, 0)].pixmap is None
    assert scene.cards[("hand", card.uid)].pixmap is None

    entity_attempts.clear()
    card_attempts.clear()
    view.refresh()
    assert entity_attempts == [shiki]
    assert card_attempts == [card.id]
    assert scene.cards[("shiki", 0, 0)].pixmap is not None
    assert not scene.cards[("shiki", 0, 0)].pixmap.isNull()
    assert scene.cards[("hand", card.uid)].pixmap is not None
    assert not scene.cards[("hand", card.uid)].pixmap.isNull()


def test_scene_direct_sync_state_viewer_change_invalidates_signatures(
        qapp, view, render_calls):
    from client import cli

    start(view, mulligan=False)
    scene = view.battle_scene
    clear_render_calls(render_calls)
    scene.sync_state(view.game, 1, cli.hand_cards_info(view.game, 1), False)
    assert scene.viewer == 1
    assert all(render_calls.values())


def test_drag_visuals_cancel_and_hand_left_click_has_no_detail(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.current.hand[0]
    details = []
    monkeypatch.setattr(view, "show_card_detail", details.append)
    hand = scene.cards[("hand", card.uid)]
    scene.drag_controller.press(hand, hand.scenePos())
    scene.drag_controller.release(hand.scenePos())
    assert details == []

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
    assert scene.focus_overlay.isVisible()
    assert scene.focus_overlay.path().elementCount() > 40  # 轮廓而非矩形孔洞
    hand_edges = [item.sceneBoundingRect() for item in scene_items(view, "hand")]
    assert scene.focus_overlay.path().boundingRect().top() <= min(
        rect.top() for rect in hand_edges)
    assert scene.focus_overlay.path().boundingRect().bottom() >= max(
        rect.bottom() for rect in hand_edges)
    assert view.ready_button.width() <= 110
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
    assert view.battle_scene.handoff_item.isVisible()
    view.handoff_button.click()
    settle(view)
    assert view.viewer == 1
    assert scene_items(view, "hand", player=1)


def test_mulligan_review_scale_is_cleared_before_handoff(qapp, view):
    start(view)
    scene = view.battle_scene
    selected_uid = view.game.current.hand[0].uid
    scene.select_mulligan(selected_uid)
    assert scene.cards[("hand", selected_uid)].scale() > 1.0

    assert view.ready()
    assert view._handoff_pending
    assert scene.mulligan_uid is None
    assert all(item.scale() == 1.0 for item in scene_items(view, "hand", player=0))


def test_choice_dialog_layout_keeps_six_buttons_visible(qapp, db, view):
    option_ids = [10010161 + index for index in range(6)]
    for cid in option_ids:
        db.cards[cid] = F.card(cid, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    view.game._open_field_summon_pick(0, option_ids)
    view.refresh()
    dialog = view.choice_dialog
    dialog.resize(560, 460)
    qapp.processEvents()
    choice = dialog.option_view

    for option_id in option_ids:
        choice.select(option_id)
        choice.ensureWidgetVisible(choice._wrappers[option_id])
        qapp.processEvents()
        button = choice.option_buttons[option_id]
        button_rect = button.rect()
        button_rect.moveTo(button.mapTo(choice.viewport(), button.rect().topLeft()))
        assert not button.isHidden()
        assert choice.viewport().rect().contains(button_rect)

    choice.select(option_ids[0])
    qapp.processEvents()
    selected_card = choice.option_widgets[0]
    selected_button = choice.option_buttons[option_ids[0]]
    content_layout = choice.widget().layout()
    content_margins = content_layout.contentsMargins()
    column_layout = choice._wrappers[option_ids[0]].layout()
    assert content_margins.top() <= 4
    assert column_layout.spacing() == 0
    scrollbar = choice.horizontalScrollBar()
    assert scrollbar.maximum() > 0
    required_view_height = (
        selected_card.height() + selected_button.height() + column_layout.spacing()
        + content_margins.top() + content_margins.bottom()
        + 2 * choice.frameWidth() + scrollbar.sizeHint().height()
    )
    assert choice.minimumHeight() >= required_view_height

    dialog_layout = dialog.layout()
    dialog_margins = dialog_layout.contentsMargins()
    title = dialog.findChild(QLabel)
    required_dialog_height = (
        title.sizeHint().height() + required_view_height + dialog_layout.spacing()
        + dialog_margins.top() + dialog_margins.bottom()
    )
    assert dialog.sizeHint().height() >= required_dialog_height


def test_choice_immediate_feedback_defers_one_answer(qapp, db, view, monkeypatch):
    option_ids = [10010161 + index for index in range(6)]
    for cid in option_ids:
        db.cards[cid] = F.card(cid, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    game = view.game
    game._open_field_summon_pick(0, option_ids)
    view.refresh()
    dialog = view.choice_dialog
    chosen_id = option_ids[2]
    answers = []
    real_answer = view.answer_pending

    def record_answer(value):
        answers.append(value)
        return real_answer(value)

    monkeypatch.setattr(view, "answer_pending", record_answer)
    dialog.option_view.select(chosen_id)
    dialog.option_view.option_buttons[chosen_id].click()
    assert dialog.isHidden()
    assert not dialog.isEnabled()
    assert answers == []
    assert game.state.pending_choice is not None

    dialog.option_view.confirm(chosen_id)
    qapp.processEvents()
    assert answers == [chosen_id]
    assert [field.card_id for field in game.current.fields] == [chosen_id]
    assert game.state.pending_choice is None
    assert view.choice_dialog is None


def test_choice_immediate_feedback_restores_invalid_answer(qapp, db, view, monkeypatch):
    option_ids = [10010161, 10010162]
    for cid in option_ids:
        db.cards[cid] = F.card(cid, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    game = view.game
    game._open_field_summon_pick(0, option_ids)
    view.refresh()
    dialog = view.choice_dialog
    answers = []
    real_answer = view.answer_pending

    def record_answer(value):
        answers.append(value)
        return real_answer(value)

    monkeypatch.setattr(view, "answer_pending", record_answer)
    invalid_id = 999999
    dialog._answer(invalid_id)
    assert dialog.isHidden()
    assert not dialog.isEnabled()
    assert answers == []
    qapp.processEvents()

    assert answers == [invalid_id]
    assert game.state.pending_choice["options"] == option_ids
    restored = view.choice_dialog
    assert restored is not None
    assert not restored.isHidden()
    assert restored.isEnabled()
    assert not view.error_label.isHidden()


def test_choice_session_boundary_return_to_menu_cancels_answer(
        qapp, db, view, monkeypatch):
    import sys

    option_ids = [10010161, 10010162]
    for cid in option_ids:
        db.cards[cid] = F.card(cid, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    view.game._open_field_summon_pick(0, option_ids)
    view.refresh()
    dialog = view.choice_dialog
    dialog.option_view.select(option_ids[0])
    dialog.option_view.option_buttons[option_ids[0]].click()
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))

    assert view.return_to_menu()
    try:
        qapp.processEvents()
    except Exception as error:
        errors.append(error)
    assert errors == []
    assert view.game is None
    assert view.choice_dialog is None


def test_second_player_mulligan_review_has_no_turn_banner(qapp, view, monkeypatch):
    start(view)
    view.ready()
    view.confirm_handoff()
    view.confirm_handoff()
    called = []
    monkeypatch.setattr(view.battle_scene, "show_turn_banner", lambda *_args: called.append(True))
    view.ready()
    assert view._handoff_pending
    assert called == []


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
    view.cancel_targeting()

    selected[0] = "player"
    enemy_player = scene.cards[("player", 1)]
    drag(hand, enemy_player.scenePos() + QPointF(20, 20))
    scene.usage_selected.emit(selected[0])
    settle(view)
    assert commands == [{"op": "play_card", "uid": card.uid,
                         "play_method": "player", "target": Ref(player=1)}]

    card, hand = give_card()
    drag(hand, QPointF(20, 450))
    assert len(commands) == 1 and card in view.game.current.hand
    assert view.pending_command is None
    view.cancel_targeting()
    selected[0] = "untargeted"
    drag(hand, QPointF(20, 450))
    scene.usage_selected.emit(selected[0])
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
    scene.usage_selected.emit("choice:1")
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


def test_preparation_spread_aligns_combat_and_hand_caption_positions(qapp, view):
    from PySide6.QtCore import QRectF
    from client.gui.battle_scene import SHIKI_SIZE, layout_positions

    start(view, mulligan=False)
    positions = layout_positions(view.game, view.viewer)
    own_x = [positions[("shiki", 0, index)].x() for index in range(4)]
    assert own_x[0] < 400
    assert own_x[2] - own_x[1] > own_x[1] - own_x[0]
    ready_center = (own_x[0] + own_x[-1] + SHIKI_SIZE.width()) / 2
    view.game.state.players[0].combat_index = 0
    combat_positions = layout_positions(view.game, view.viewer)
    combat_center = combat_positions[("shiki", 0, 0)].x() + SHIKI_SIZE.width() / 2
    assert ready_center == combat_center == 720
    enemy = positions[("enemy_hand_label",)]
    own = positions[("hand_caption",)]
    assert enemy == QPointF(1530, 156)
    assert own == QPointF(1530, 680)
    for label in (view.enemy_hand_label, view.hand_caption):
        assert (label.width(), label.height()) == (68, 64)
    enemy_rect = QRectF(enemy.x(), enemy.y(), 68, 64)
    own_rect = QRectF(own.x(), own.y(), 68, 64)
    enemy_deck = positions[("enemy_deck",)]
    own_deck = positions[("own_deck",)]
    enemy_deck_rect = QRectF(enemy_deck.x(), enemy_deck.y(), 68, 64)
    own_deck_rect = QRectF(own_deck.x(), own_deck.y(), 68, 64)
    assert enemy_deck_rect.top() - enemy_rect.bottom() == 8
    assert own_rect.top() - own_deck_rect.bottom() == 8
    assert not enemy_rect.intersects(enemy_deck_rect)
    assert not own_rect.intersects(own_deck_rect)


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


def assert_deck_count_layout(scene, own_count, enemy_count):
    from PySide6.QtGui import QTransform
    from client.gui.battle_scene import DECK_BACK_SIZE, layout_positions
    from client.gui.ui_assets import cardback_pixmap

    own_keys = [("deck_back", 0, index) for index in range(min(3, own_count))]
    enemy_keys = [("deck_back", 1, index)
                  for index in range(3 - min(3, enemy_count), 3)]
    if own_count == 0:
        own_keys = [("deck_back", 0, 0)]
    if enemy_count == 0:
        enemy_keys = [("deck_back", 1, 2)]
    assert sorted(key for key in scene.deck_backs if key[1] == 0) == own_keys
    assert sorted(key for key in scene.deck_backs if key[1] == 1) == enemy_keys

    positions = layout_positions(scene.game, scene.viewer,
                                 scene_width=scene.layout_width)
    for player, count in ((0, own_count), (1, enemy_count)):
        for index in range(3):
            key = ("deck_back", player, index)
            if key not in scene.deck_backs:
                continue
            item = scene.deck_backs[key]
            side = "own" if player == scene.viewer else "enemy"
            if count == 0:
                from client.gui.ui_assets import empty_deck_pixmap
                light = scene.game.state.players[player].ext.get("deck_out_burn") is not None
                expected = empty_deck_pixmap(light, landscape=True)
            else:
                expected = cardback_pixmap(side, landscape=True)
            expected = expected.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
            assert item.pixmap.toImage() == expected.toImage()
            assert item.pos() == positions[key] + QPointF(
                0, (DECK_BACK_SIZE.height() - item.size.height()) / 2)
            expected_rotations = (145, 155, 165) if player == scene.viewer else (195, 205, 215)
            assert item.rotation() == expected_rotations[index]
            assert item.zValue() == (22 - index if player == scene.viewer else 20 + index)


@pytest.mark.parametrize("burn_value", (0, 1))
@pytest.mark.parametrize("own_count", (3, 2, 1, 0))
@pytest.mark.parametrize("enemy_count", (3, 2, 1, 0))
def test_deck_count_empty_deck_settings_and_resize_share_layout(
        qapp, view, own_count, enemy_count, burn_value):
    start(view, mulligan=False)
    scene = view.battle_scene
    for player, count in enumerate((own_count, enemy_count)):
        state = view.game.state.players[player]
        state.deck[:] = state.deck[:count]
        if player == 0:
            state.ext["deck_out_burn"] = burn_value
        else:
            state.ext.pop("deck_out_burn", None)
    view.refresh()
    settle(view)
    assert_deck_count_layout(scene, own_count, enemy_count)

    scene.refresh_cardbacks()
    assert_deck_count_layout(scene, own_count, enemy_count)
    scene.set_viewport_size(2000, 900)
    assert_deck_count_layout(scene, own_count, enemy_count)


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


def test_card_detail_hides_runtime_summary(qapp, db):
    cdef = F.card(10010151, name="运行时详情卡")
    runtime = {
        "cost": 0, "stats": "力量 +2　护甲 +1", "keywords": ["瞬发", "贯通"],
        "enhance": 2, "quest": "委托：已 1/2", "playable": False,
        "usage": [{"label": "常规", "ok": False, "reason": "条件未满足"}],
    }
    dialog = CardDetailDialog(cdef, db, runtime=runtime)
    assert not hasattr(dialog, "runtime_label")
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert all(not text.startswith(("所属式神：", "子类型：", "当前状态"))
               for text in labels)
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
    assert not hasattr(seen[-1], "runtime_label")

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
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[1].hand[0]
    item = scene.cards[("hand", card.uid)]
    details = []
    scene.read_detail_requested.connect(lambda kind, payload: details.append((kind, payload)))
    event = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseRelease)
    event.setButton(Qt.RightButton)
    event.setScenePos(item.scenePos())
    item.mouseReleaseEvent(event)
    assert item.cdef is None
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
    dialog = seen["dialog"]
    assert dialog.column_names == ["main", "form", "status", "mechanisms"]
    assert dialog.form_card.size() == dialog.main_art_label.size()
    assert dialog.status_panel.maximumHeight() == 512
    assert dialog.mechanism_panel.maximumHeight() == 512
    assert not hasattr(dialog, "status_label")
    text = "\n".join(item["text"] for item in dialog.status_mechanisms)
    assert f"力量 {shiki.eff_power}" not in text
    assert f"生命 {shiki.health}/{shiki.max_health}" not in text
    assert "派系 青岚" not in text
    assert "延迟能力" in text and "on_battle_end" in text and "次数 2" in text
    assert "玩家B" in text and db.shikigami[view.game.state.players[1].shikigami[0].id].name in text
    assert "灵咒 1：测试灵咒" in text and "灵咒原文" in text
    assert "来源 玩家B" in text and db.shikigami[view.game.state.players[1].shikigami[1].id].name in text
    assert "眩晕：normal" in text
    assert all(word not in text for word in (
        "护甲/破甲", "能量", "永久修正", "临时修正", "动态光环合计", "力量覆写",
        "贯通", "屏障", "迅捷", "免疫", "气绝", "倒计时",
        "基础 力量", "增强 +2", "修饰 力量", "攻击后到期强化",
        "保留护甲", "保留破甲", "濒死", "已离场"))
    assert "inv_mod" not in text and "'block'" not in text
    assert "其他扩展不得导出" not in text
    assert "transform_origin" not in text and "coffin_origin" not in text

    normal_text = view.battle_scene.cards[("shiki", 0, 0)].shiki_text
    assert all(word not in normal_text for word in
               ("能量", "形态", "觉醒", "贯通", "延迟能力", "测试灵咒",
                "攻击后到期", "动态光环", "濒死", "保留护甲"))


@pytest.mark.parametrize("empty_column", ["form", "status", "mechanisms"])
def test_shiki_detail_omits_empty_optional_columns(qapp, view, monkeypatch, empty_column):
    from client.gui.details import ShikigamiDetailDialog

    start(view, mulligan=False)
    if empty_column == "status":
        monkeypatch.setattr("client.gui.details.shiki_status_lines", lambda *_args: [])
    if empty_column == "mechanisms":
        monkeypatch.setattr("client.gui.details.shikigami_mechanisms", lambda *_args, **_kwargs: [])
    dialog = ShikigamiDetailDialog(view.game, Ref(player=0, shikigami=0), 0, view)
    assert empty_column not in dialog.column_names
    dialog.close()


def test_shikigami_mechanisms_include_extra_status_keywords_in_order(qapp, view):
    from client.gui.mechanisms import shikigami_mechanisms

    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    shiki.keywords.append("critical")
    ref = Ref(player=0, shikigami=0)
    names = [item["name"] for item in shikigami_mechanisms(
        view.game, ref, status_texts=["获得[吸血]与[暴击]"])]
    assert names[-2:] == ["吸血", "暴击"]
    assert names.count("暴击") == 1


def test_secret_delayed_target_follows_holder_perspective(qapp, view, monkeypatch):
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    delayed = {"block": F.block(when="on_battle_end"),
               "chosen": Ref(player=1, shikigami=0), "uses": 1,
               "secret": True, "origin": None}
    shiki.delayed.append(delayed)
    seen = []

    def capture_exec(dialog):
        seen.append("\n".join(item["text"] for item in dialog.status_mechanisms))
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
    assert scene.log_item.x() == 12
    assert scene.log_item.y() == 422
    assert view.log_button.width() == view.log_button.height() == 40
    assert view.log_button.text() == "对局\n记录"
    view.apply_theme("light", THEMES["light"])
    metrics = QFontMetrics(view.log_button.font())
    assert metrics.lineSpacing() * 2 < view.log_button.height() - 2
    style = view.log_button.styleSheet()
    assert "border-radius: 20px" in style
    assert f"background: {THEMES['light']['panel']}" in style
    assert f"color: {THEMES['light']['text']}" in style
    assert f"border: 1px solid {THEMES['light']['gold']}" in style
    assert view._phase_lines()[0] == "玩家A 回合1"
    phase_proxy = next(item for item in scene.items()
                       if hasattr(item, "widget") and item.widget() is view.phase_label)
    assert phase_proxy.x() > scene.log_item.x()
    assert phase_proxy.y() == scene.log_item.y()
    assert view.order_label.isHidden()
    assert scene.sceneRect().contains(
        scene.log_item.sceneBoundingRect())


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
    from client.gui.player_details import PlayerDetailDialog

    start(view, mulligan=False)
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    assert view.show_player_detail(0) is None
    dialog = seen["dialog"]
    assert type(dialog) is PlayerDetailDialog
    assert dialog.windowTitle() == "玩家A"
    assert "生命" in dialog.summary_label.text()
    box = dialog.findChild(QDialogButtonBox)
    close = box.button(QDialogButtonBox.Close)
    assert close.text() == "关闭"
    assert close.minimumWidth() == 76 and close.minimumHeight() == 30
    layout = dialog.layout()
    assert layout.itemAt(layout.count() - 1).widget() is box
    assert layout.itemAt(layout.count() - 1).alignment() == Qt.AlignRight
    dialog.close()


def test_player_detail_fields_abilities_scroll_and_card_click(qapp, view, monkeypatch):
    from client.gui.player_details import PlayerDetailDialog
    from core.model import FieldState

    start(view, mulligan=False)
    db = view.game.db
    for cid, name in ((10010151, "幻境甲"), (10010152, "幻境乙")):
        db.cards[cid] = F.card(cid, name=name, card_type="field", intensity=9,
                               text=f"{name}原文。", token=True)
    player = view.game.state.players[0]
    player.fields.extend([
        FieldState(card_id=10010151, intensity=3, shikigami=100101),
        FieldState(card_id=10010152, intensity=7, shikigami=100101),
    ])
    player.auras.append({
        "block": F.block(when="on_draw"), "once_key": None, "scope": "game",
        "origin": 10010151, "source_name": "光环来源", "text": "牌手光环原文。",
    })
    player.delayed.extend([
        {"block": F.block(when="on_draw"), "chosen": None, "uses": 1,
         "secret": False, "scope": "turn", "origin": 10010151,
         "source_name": "延迟来源", "text": "牌手延迟原文。"},
        {"block": F.block(when="on_draw"), "chosen": None, "uses": 1,
         "secret": True, "scope": "turn", "origin": 10010152,
         "source_name": "秘密来源", "text": "秘密延迟原文。"},
    ])
    player.ext["stuns"] = [{"kind": "normal"}]
    dialog = PlayerDetailDialog(view.game, 0, 0)
    assert [widget.cdef.id for widget in dialog.field_widgets] == [10010151, 10010152]
    assert [widget._art_options["display"]["durability"]
            for widget in dialog.field_widgets] == [3, 7]
    assert all(widget._art_height == 512 for widget in dialog.field_widgets)
    assert [(item["name"], item["text"]) for item in dialog.ability_mechanisms] == [
        ("光环来源", "牌手光环原文。"),
        ("延迟来源", "牌手延迟原文。"),
        ("秘密来源", "秘密延迟原文。"),
        ("眩晕", "normal"),
    ]

    seen = []

    class Detail:
        def __init__(self, cdef, db, parent):
            seen.append((cdef, db, parent))

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr("client.gui.player_details.CardDetailDialog", Detail)
    dialog.field_widgets[1].detail_clicked.emit(dialog.field_widgets[1].cdef)
    assert seen == [(db.cards[10010152], db, dialog)]

    dialog.show()
    qapp.processEvents()
    assert dialog.scroll_area.horizontalScrollBar().maximum() == 0
    dialog.resize(640, 700)
    qapp.processEvents()
    assert dialog.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.scroll_area.horizontalScrollBar().maximum() > 0
    dialog.close()

    enemy = PlayerDetailDialog(view.game, 0, 1)
    assert [(item["name"], item["text"]) for item in enemy.ability_mechanisms] == [
        ("光环来源", "牌手光环原文。"),
        ("延迟来源", "牌手延迟原文。"),
        ("眩晕", "normal"),
    ]
    enemy.close()


def test_player_detail_empty_fields_and_legacy_ability_have_no_placeholder(qapp, view):
    from client.gui.player_details import PlayerDetailDialog

    start(view, mulligan=False)
    view.game.state.players[0].auras.append({
        "block": F.block(when="on_draw"), "once_key": None, "scope": "game",
    })
    dialog = PlayerDetailDialog(view.game, 0, 0)
    assert dialog.field_widgets == []
    assert [item["name"] for item in dialog.ability_mechanisms] == ["牌手能力"]
    assert dialog.content_layout.count() == 2  # 能力栏 + 右侧留白，无空占位栏
    assert dialog.content_layout.itemAt(0).widget() is dialog.ability_panel
    dialog.close()


def test_player_left_click_only_selects_legal_target(qapp, view, monkeypatch):
    from client.gui.battle_scene import layout_positions

    start(view, mulligan=False)
    scene = view.battle_scene
    assert all(("player_detail", pi) not in layout_positions() for pi in (0, 1))
    assert not [item for item in scene.items()
                if hasattr(item, "widget") and item.widget() is not None
                and hasattr(item.widget(), "text")
                and item.widget().text() == "牌手详情"]

    item = scene.cards[("player", 0)]
    details, targets = [], []
    monkeypatch.setattr(view, "show_player_detail", details.append)
    monkeypatch.setattr(view, "choose_target", targets.append)
    inside = item.scenePos() + QPointF(50, 50)
    outside = item.scenePos() + QPointF(150, 50)

    scene.drag_controller.press(item, inside)
    scene.drag_controller.release(inside)
    assert details == [] and targets == []
    scene.drag_controller.press(item, outside)
    scene.drag_controller.release(outside)
    assert details == [] and targets == []

    scene.legal_targets = view.legal_targets = [item.payload]
    item.targetable = True
    scene.drag_controller.press(item, outside)
    scene.drag_controller.release(outside)
    assert details == [] and targets == [item.payload]


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
    view.confirm_handoff()
    settle(view)
    assert game.state.players[0].mulligan_done
    assert view.viewer == 1
    view.ready()
    view.confirm_handoff()
    settle(view)
    assert game.state.phase == "battle"
    assert view.viewer == 0
    assert len(scene_items(view, "hand", player=0)) == len(game.state.players[0].hand)


def test_upgrade_assault_and_end_turn(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    game = view.game
    assert view._phase_lines()[0] == "玩家A 回合1"
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


def test_search_deck_choice_dialog_single_option(qapp, db, view):
    """牌库选择检索仅一个候选也显示共用选择窗，作答后原实例入手。"""
    field_id = 10010161
    db.cards[field_id] = F.card(field_id, shikigami=100101,
                                card_type="field", intensity=3)
    cid = 10010151
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="search_deck", shikigami="self", card_type="field",
               pick="choose", intensity_boost=5)])
    start(view, mulligan=False)
    game = view.game
    target = F.CardInstance(uid=9001, id=field_id)
    game.state.players[0].deck.insert(0, target)
    card = F.give(game, 0, cid)
    view.refresh()
    settle(view)
    view.play_card(card.uid)
    settle(view)
    assert game.state.pending_choice["kind"] == "search_deck_pick"
    assert view.choice_dialog is not None
    view.answer_pending(9001)
    settle(view)
    assert target in game.state.players[0].hand
    assert target.mods["intensity_boost"] == 5
    info = view.hand_info()[target.uid]
    assert info["render"]["durability"] == 8
    assert info["stats"] == "耐久8"
    assert game.state.pending_choice is None


def test_field_summon_choice_dialog_horizontal_cards_click_closes(qapp, db, view):
    """残阳无影候选使用共用卡图横滚视图；真实点击后作答并销毁旧窗。"""
    option_ids = [10010161 + index for index in range(6)]
    for cid in option_ids:
        db.cards[cid] = F.card(cid, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    game = view.game
    game._open_field_summon_pick(0, option_ids)
    view.refresh()
    dialog = view.choice_dialog
    cards = dialog.findChildren(CardWidget)
    assert len(cards) == len(option_ids)
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    dialog.resize(560, 460)
    qapp.processEvents()
    assert scroll.widget().sizeHint().width() > scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() > 0
    dialog.reject()
    assert not dialog.isHidden()

    destroyed = []
    dialog.destroyed.connect(lambda: destroyed.append(True))
    chosen_id = option_ids[2]
    assert cards[2].cdef.id == chosen_id
    QTest.mouseClick(cards[2], Qt.LeftButton)
    QTest.mouseClick(dialog.option_view.option_buttons[chosen_id], Qt.LeftButton)
    qapp.processEvents()
    assert [field.card_id for field in game.current.fields] == [chosen_id]
    assert game.state.pending_choice is None
    assert dialog.isHidden()
    assert view.choice_dialog is None
    assert view._choice_key is None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert destroyed == [True]


def test_real_yaml_discard_pick_click_draws_three_and_closes(qapp, gdb, view):
    """真实余辉完成弃牌与抽三后，pending 与旧选择窗均关闭。"""
    view.db = view.battle_scene.db = gdb
    team = [100304, 100101, 100102, 100103]
    view.start_game(
        ("玩家A", team, F.deck_of(*team)),
        ("玩家B", team, F.deck_of(*team)),
        seed=7, first=0, shuffle_team=False, mulligan=False, check_deck=False,
        config=GameConfig(auto_skip_upgrade=True),
    )
    settle(view)
    game = view.game
    pa, _ = F.battle_setup(game, {0: 2})
    fld = F.give(game, 0, 10030401)
    card = F.give(game, 0, 10030403)
    hand_before = len(pa.hand)
    view.refresh()
    settle(view)
    assert view.play_card(card.uid)
    settle(view)
    pending = game.state.pending_choice
    assert pending["kind"] == "discard_pick"
    dialog = view.choice_dialog
    cards = dialog.findChildren(CardWidget)
    assert len(cards) == len(pending["options"])
    chosen_index = pending["options"].index(fld.uid)
    assert cards[chosen_index].cdef.id == 10030401
    destroyed = []
    dialog.destroyed.connect(lambda: destroyed.append(True))

    QTest.mouseClick(cards[chosen_index], Qt.LeftButton)
    QTest.mouseClick(dialog.option_view.option_buttons[fld.uid], Qt.LeftButton)
    qapp.processEvents()
    settle(view)
    assert fld in pa.graveyard
    assert len(pa.hand) == hand_before + 1           # 使用 1、弃 1 后抽 3
    assert game.state.pending_choice is None
    assert dialog.isHidden()
    assert view.choice_dialog is None
    assert view._choice_key is None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert destroyed == [True]


def test_discard_pick_choice_dialog_click_maps_uid_and_renews_dialog(qapp, db, view):
    """余辉型连续弃牌保留 uid 映射，下一 pending 使用新窗而不复用旧选项。"""
    field_id = 10010161
    db.cards[field_id] = F.card(field_id, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    game = view.game
    first = F.give(game, 0, field_id)
    second = F.give(game, 0, field_id)
    game._open_discard_pick(0, 2, card_type="field")
    view.refresh()
    first_dialog = view.choice_dialog
    first_cards = first_dialog.findChildren(CardWidget)
    assert len(first_cards) == 2
    destroyed = []
    first_dialog.destroyed.connect(lambda: destroyed.append(True))

    QTest.mouseClick(first_cards[0], Qt.LeftButton)
    choice = first_dialog.option_view
    assert choice.selected == first.uid
    assert choice.option_buttons[first.uid].isVisible()
    assert choice.option_buttons[first.uid].width() == 96
    assert first_cards[0].width() == 194
    assert first_cards[0].geometry().center().x() == choice._wrappers[first.uid].rect().center().x()
    assert choice._wrappers[first.uid].graphicsEffect() is None
    assert first.uid not in [card.uid for card in game.current.graveyard]
    QTest.mouseClick(choice.option_buttons[first.uid], Qt.LeftButton)
    qapp.processEvents()
    assert first.uid in [card.uid for card in game.current.graveyard]
    assert game.state.pending_choice["options"] == [second.uid]
    assert first_dialog.isHidden()
    second_dialog = view.choice_dialog
    assert second_dialog is not None and second_dialog is not first_dialog
    assert not second_dialog.isHidden()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert destroyed == [True]

    second_cards = second_dialog.findChildren(CardWidget)
    assert len(second_cards) == 1
    QTest.mouseClick(second_cards[0], Qt.LeftButton)
    QTest.mouseClick(second_dialog.option_view.option_buttons[second.uid], Qt.LeftButton)
    qapp.processEvents()
    assert second.uid in [card.uid for card in game.current.graveyard]
    assert game.state.pending_choice is None
    assert second_dialog.isHidden()
    assert view.choice_dialog is None
    assert view._choice_key is None


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
    assert view.game is None
    assert view.stack.currentWidget() is view.setup_page


def test_hotseat_result_waits_visual_busy(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    enemy = view.game.state.players[1]
    view.game.deal_to_player(1, enemy.health + enemy.shield, None)
    view.game._drain_queue()
    assert view.game.state.winner == 0
    view.refresh()
    assert scene.visual_busy
    assert view.result_banner.isHidden()

    while scene.visual_busy:
        for animation in list(scene._visual_animations):
            animation.setCurrentTime(animation.duration())
            qapp.processEvents()
    assert not view.result_banner.isHidden()


def test_game_over_is_immediate_and_right_click_details_remain_available(qapp, view, monkeypatch):
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    start(view, mulligan=False)
    view.timeline_queue[:] = [(0, "尚未播放")]
    view.game.state.winner = 0
    view.refresh()
    assert not view.result_banner.isHidden()
    assert not view._inputs_open()
    assert view.battle_scene.result_item.zValue() > 110
    assert view.battle_scene.result_back_item.zValue() > 110
    uid = view.game.current.hand[0].uid
    assert not view.upgrade(0)
    assert not view.assault(0)
    assert not view.play_card(uid)
    assert not view.end_turn()

    scene = view.battle_scene

    def right_click(item, pos):
        event = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseRelease)
        event.setButton(Qt.RightButton)
        event.setScenePos(pos)
        item.mouseReleaseEvent(event)

    seen = []
    monkeypatch.setattr(view, "show_shiki_detail", seen.append)
    item = scene.cards[("shiki", 0, 0)]
    right_click(item, item.scenePos())
    assert seen == [item.payload]

    player_details = []
    monkeypatch.setattr(view, "show_player_detail", player_details.append)
    player = scene.cards[("player", 0)]
    right_click(player, player.scenePos() + QPointF(50, 50))
    assert player_details == [0]

    card_details = []
    monkeypatch.setattr(view, "show_card_detail", card_details.append)
    hand = next(item for key, item in scene.cards.items()
                if key[0] == "hand" and item.player == view.viewer)
    assert hand.revealed
    right_click(hand, hand.scenePos())
    assert card_details == [hand.payload]
    hidden_hand = next(item for key, item in scene.cards.items()
                       if key[0] == "hand" and item.player != view.viewer and not item.revealed)
    right_click(hidden_hand, hidden_hand.scenePos())
    assert card_details == [hand.payload]

    actions = []
    scene.action_requested.connect(actions.append)
    origin = item.scenePos()
    scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(180, 0))
    assert scene.drag_controller.item is None
    assert not scene.drag_controller.dragged
    assert scene.drag_controller.drag_ghost is None
    scene.drag_controller.release(origin + QPointF(180, 0))
    assert actions == []
    view.show_log()
    assert not view.log_dialog.isHidden()


def test_game_over_banner_returns_to_menu(qapp, view):
    returned = []
    view.on_back = lambda: returned.append(True)
    start(view, mulligan=False)
    view.game.state.winner = 0
    view.refresh()
    settle(view)
    assert not view.result_banner.isHidden()
    assert view.result_banner.pixmap() is not None
    assert not view.result_banner.pixmap().isNull()
    view.result_back.click()
    assert returned == [True]


def test_main_window_hotseat_page_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert isinstance(win.pages["hotseat"], HotseatView)
    win.go("hotseat")
    assert win.stack.currentWidget() is win.pages["hotseat"]
    assert win.game_menu_button.isHidden()
    hotseat = win.pages["hotseat"]
    hotseat.stack.setCurrentWidget(hotseat.battle_page)
    assert not win.game_menu_button.isHidden()
    assert win.game_menu_button.text() == "游戏设置"
    assert win.back_button.text() == "退出对局"
    assert not hotseat.battle_scene.menu_item.isVisible()
    win.toggle_theme()
    assert win.pages["hotseat"].theme == "dark"
    start(hotseat, mulligan=False)
    hotseat.game.state.winner = 0
    hotseat.refresh()
    assert win.back_button.text() == "返回主菜单"
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


def test_burst_usage_option_renders_energy_badge(qapp, view, monkeypatch):
    seen = []
    monkeypatch.setattr("client.gui.battle_scene.card_pixmap",
                        lambda *_args, **kwargs: seen.append(kwargs))
    option = {"id": "burst", "label": "爆能", "cost": 1, "energy": 2,
              "ok": True, "reason": None}
    cdef = view.db.cards[min(view.db.cards)]
    view.battle_scene.show_usage_options([option], [cdef])
    assert seen[0]["burst"] == 2


def test_usage_options_show_all_central_cards_and_reasons(qapp, db, view):
    free_option, gated_option = 10010153, 10010154
    db.cards[free_option] = F.card(free_option, token=True, cost=0, level=0)
    db.cards[gated_option] = F.card(gated_option, token=True, cost=1, level=3)
    db.cards[10010161] = F.card(
        10010161, token=True, card_type="reinforce", shikigami2=100102,
        options=[free_option, gated_option])
    start(view, mulligan=False)
    card = F.give(view.game, 0, 10010161)
    view.refresh()
    settle(view)
    assert view.play_card(card.uid)

    scene = view.battle_scene
    assert [item.payload for item in scene.usage_items] == ["choice:0", "choice:1"]
    assert [item.playable for item in scene.usage_items] == [True, False]
    assert [item.pos() for item in scene.usage_items] == [QPointF(612, 280), QPointF(808, 280)]
    reason = view.game.usage_options(0, card)[1]["reason"]
    assert any(reason in label.toPlainText() for label in scene.usage_labels)
    assert not view._inputs_open()

    view.cancel_targeting()
    assert not scene.usage_items
    assert card in view.game.current.hand
    assert view.play_card(card.uid)
    scene.usage_selected.emit("choice:0")
    settle(view)
    assert not scene.usage_items
    assert card not in view.game.current.hand


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
    assert scene._move_animations[item] is animation
    assert not any(event.get("v") == "_move" for event in scene._visual_queue)
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    replacement = scene._move_animations[item]
    assert replacement is not animation
    target = layout_positions(view.game, view.viewer)[key]
    replacement.setCurrentTime(replacement.duration())
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


def test_drag_defers_following_animation_settlement_until_release(qapp, view):
    from client.gui.battle_scene import layout_positions

    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.current.combat_index = 0
    view.refresh()
    key = ("shiki", 0, 0)
    item = scene.cards[key]
    scene.play_visual_event({"v": "damage", "p": 0, "s": 1, "amount": 1})
    assert [event["v"] for event in scene._visual_queue] == ["damage"]

    origin = item.scenePos()
    assert scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(160, -80))
    assert scene.drag_controller.dragged
    assert item not in scene._move_animations
    damage = scene._visual_animations[0]
    assert scene._visual_events[damage]["v"] == "damage"
    damage.setCurrentTime(damage.duration())
    qapp.processEvents()
    assert scene.drag_controller.dragged
    assert item not in scene._move_animations

    scene.drag_controller.cancel()
    assert not scene.drag_controller.dragged
    replacement = scene._move_animations[item]
    replacement.setCurrentTime(replacement.duration())
    qapp.processEvents()
    assert item.pos() == layout_positions(view.game, view.viewer)[key]
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
    assert len(scene._card_use_animations) == 1
    first = scene._card_use_animations[0]
    assert scene._card_use_items[first].cdef.id == cards[0].id
    assert scene._card_use_items[first].player == 0
    assert scene._card_use_items[first].pos() == old_positions[cards[0].uid]
    first.setCurrentTime(first.duration())
    qapp.processEvents()
    assert len(scene._card_use_animations) == 1
    second = scene._card_use_animations[0]
    assert scene._card_use_items[second].player == 1
    assert scene._card_use_items[second].pos() == old_positions[cards[1].uid]
    second.setCurrentTime(second.duration())
    qapp.processEvents()
    assert not scene._card_use_animations
    assert not scene._card_use_items
    assert view.played_timeline == played_before


def test_card_use_animation_without_cache_uses_hand_layout_anchor(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene._hand_animation_cache.clear()
    cards = [view.game.state.players[pi].hand[0] for pi in (0, 1)]
    for pi, card in enumerate(cards):
        scene.animate_card_use(card.uid, card.id, pi)
    assert [item.pos() for item in scene._card_use_items.values()] == [QPointF(1489, 822)]
    animation = scene._card_use_animations[0]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert [item.pos() for item in scene._card_use_items.values()] == [QPointF(1489, -78)]


def test_enemy_card_use_animation_paints_card_back_before_flip(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[1].hand[0]
    assert not scene.cards[("hand", card.uid)].pixmap.isNull()
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


def test_card_use_animation_uses_integer_height_and_keeps_fallback_art(
        qapp, view, monkeypatch):
    from PySide6.QtGui import QPixmap

    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[0].hand[0]
    heights = []
    monkeypatch.setattr(
        "client.gui.battle_scene.card_pixmap",
        lambda *_args, **kwargs: heights.append(kwargs["height"]) or None)
    scene.animate_card_use(card.uid, card.id, 0)
    animation = scene._card_use_animations[0]
    item = scene._card_use_items[animation]
    fallback = QPixmap(20, 20)
    item.set_art(fallback)
    animation.setCurrentTime(int(animation.duration() * 0.2))
    assert heights == [312]
    assert type(heights[0]) is int
    assert not item.pixmap.isNull()


@pytest.mark.parametrize("player,top_index", ((0, 0), (1, 2)))
def test_hand_animation_hides_pending_draw_and_uses_deck_origin(qapp, view,
                                                                player, top_index):
    start(view, mulligan=False)
    scene = view.battle_scene
    owner = view.game.state.players[player]
    source_key = ("deck_back", player, top_index)
    before = len(view.game.state.timeline)
    card = owner.deck[0]
    owner.deck[:] = [card]
    view.game.draw_cards(player, 1)
    entries = view.game.state.timeline[before:]
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=entries, play_pending=False)
    source = QPointF(scene.deck_backs[source_key].pos())
    item = scene.cards[("hand", card.uid)]
    target = QPointF(item.pos())

    assert not item.isVisible()
    event = next(entry for entry in entries if entry.get("v") == "hand")
    scene.play_visual_event(event)
    assert item.isVisible()
    assert item.pos() == source
    assert scene._move_animations[item].endValue() == target


def test_hand_animation_generate_uses_player_origin_and_enemy_cardback(qapp, view):
    from client.gui.ui_assets import cardback_pixmap

    start(view, mulligan=False)
    scene = view.battle_scene
    player = 1 - view.viewer
    owner = view.game.state.players[player]
    card = CardInstance(uid=view.game.state.next_uid, id=owner.hand[0].id)
    view.game.state.next_uid += 1
    view.game.move_card(owner, card, "hand", reason="generate")
    event = view.game.state.timeline[-1]
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=[event], play_pending=False)
    item = scene.cards[("hand", card.uid)]

    assert not item.isVisible()
    assert not item.revealed
    assert item.pixmap.cacheKey() == cardback_pixmap("enemy").cacheKey()
    scene.play_visual_event(event)
    assert item.pos() == scene.cards[("player", player)].pos()
    assert scene._move_animations[item].endValue() != item.pos()


def test_hand_animation_hides_existing_item_on_return(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.current.hand[0]
    item = scene.cards[("hand", card.uid)]
    assert item.isVisible()
    view.game.move_card(view.game.current, card, "graveyard")
    view.game.move_card(view.game.current, card, "hand")
    event = next(entry for entry in reversed(view.game.state.timeline)
                 if entry.get("v") == "hand" and entry.get("u") == card.uid)

    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=[event], play_pending=False)
    assert scene.cards[("hand", card.uid)] is item
    assert not item.isVisible()

    scene.play_visual_event(event)
    assert item.isVisible()
    assert item in scene._move_animations


def test_hand_animation_multiple_draws_are_fifo_and_leave_single_items(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    before = len(view.game.state.timeline)
    view.game.draw_cards(view.viewer, 2)
    entries = view.game.state.timeline[before:]
    events = [entry for entry in entries if entry.get("v") == "hand"]
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=entries, play_pending=False)
    first, second = [scene.cards[("hand", event["u"])] for event in events]
    assert not first.isVisible() and not second.isVisible()

    for event in events:
        scene.play_visual_event(event)
    assert list(scene._move_animations) == [first]
    assert first.isVisible() and not second.isVisible()
    assert [event["u"] for event in scene._visual_queue] == [second.uid]

    next(iter(scene._move_animations.values())).setCurrentTime(180)
    qapp.processEvents()
    assert list(scene._move_animations) == [second]
    assert second.isVisible()
    next(iter(scene._move_animations.values())).setCurrentTime(180)
    qapp.processEvents()
    assert not scene.visual_busy
    for item in (first, second):
        assert item.isVisible()
        assert sum(getattr(candidate, "key", None) == item.key
                   for candidate in scene.items()) == 1


def test_hand_animation_reset_and_handoff_leave_no_hidden_items(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    before = len(view.game.state.timeline)
    view.game.draw_cards(view.viewer, 1)
    entries = view.game.state.timeline[before:]
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=entries, play_pending=False)
    assert any(not item.isVisible() for item in scene_items(view, "hand"))

    scene.reset_animations()
    assert all(item.isVisible() for item in scene_items(view, "hand"))

    before = len(view.game.state.timeline)
    view.game.draw_cards(view.viewer, 1)
    entries = view.game.state.timeline[before:]
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=entries, play_pending=False)
    old_items = scene_items(view, "hand")
    assert any(not item.isVisible() for item in old_items)
    view._begin_handoff()
    assert not scene_items(view, "hand")
    assert all(item.scene() is None for item in old_items)


def test_hand_animation_skips_card_that_already_left(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    before = len(view.game.state.timeline)
    view.game.draw_cards(view.viewer, 1)
    entries = view.game.state.timeline[before:]
    event = next(entry for entry in entries if entry.get("v") == "hand")
    scene.sync_state(view.game, view.viewer, {}, True,
                     pending_entries=entries, play_pending=False)
    item = scene.cards[("hand", event["u"])]
    view.game.move_card(view.game.current, item.payload, "graveyard")

    scene.play_visual_event(event)
    assert not scene._move_animations
    assert not item.isVisible()
    scene.sync_state(view.game, view.viewer, {}, True, pending_entries=[])
    assert ("hand", item.uid) not in scene.cards


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
    assert view._handoff_stage == "transfer"
    assert all(item.scene() is None for item in old_hand_items)
    assert view.handoff_dialog is None
    assert scene.handoff_item.isVisible()
    assert scene.handoff_item.x() < scene.end_turn_item.x()
    assert view.handoff_button.text() == "切换玩家"
    assert not scene_items(view, "hand")
    assert view.choice_dialog is None
    assert scene.cards[("player", 0)].y() > scene.cards[("player", 1)].y()
    before = list(view.timeline_queue)
    assert before
    assert not view.apply_command({"op": "end_turn"})
    view.play_next_timeline()
    assert view.timeline_queue == before

    view.handoff_button.click()  # 回合结束交接只需一次点击
    assert not view._handoff_pending
    assert not scene.handoff_item.isVisible()
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
    start(view, mulligan=False)
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert not view.battle_scene.handoff_item.isVisible()
    assert view.end_turn()
    view.return_to_menu()
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert not view.battle_scene.handoff_item.isVisible()
    assert view.game is None
    assert view.stack.currentWidget() is view.setup_page


def test_mulligan_log_hides_opponent_counts_only_during_startup(qapp, view):
    start(view)
    own_uid = view.game.state.players[0].hand[0].uid
    assert view.mulligan(own_uid)
    settle(view)
    own_message = "玩家A 调度了一张手牌（剩余 2 次）"
    assert own_message in log_lines(view)

    assert view.ready()
    view.confirm_handoff()
    settle(view)
    assert own_message not in log_lines(view)
    other_uid = view.game.state.players[1].hand[0].uid
    assert view.mulligan(other_uid)
    settle(view)
    other_message = "玩家B 调度了一张手牌（剩余 2 次）"
    assert other_message in log_lines(view)

    assert view.ready()
    view.confirm_handoff()
    settle(view)
    assert view.game.state.phase == "battle"
    assert other_message not in log_lines(view)
    view.game.state.timeline.append({"k": "l", "m": other_message})
    view.refresh()
    settle(view)
    assert log_lines(view).count(other_message) == 1


def test_right_click_opens_public_details_without_actions(qapp, view, monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.Rejected)
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    scene = view.battle_scene
    scene.inputs_open = False
    calls = []
    scene.read_detail_requested.connect(lambda kind, _payload: calls.append(kind))
    actions = []
    scene.action_requested.connect(actions.append)

    def right_click(item, offset):
        pos = view.battle_view.mapFromScene(item.scenePos() + offset)
        QTest.mouseClick(view.battle_view.viewport(), Qt.RightButton, pos=pos)

    hand = scene.cards[("hand", view.game.current.hand[0].uid)]
    right_click(hand, QPointF(55, 78))
    shiki = scene.cards[("shiki", 0, 0)]
    right_click(shiki, QPointF(74, 105))
    player = scene.cards[("player", 0)]
    right_click(player, QPointF(48, 48))
    assert calls == ["hand", "shiki", "player"]
    assert actions == []

    hidden = scene.cards[("hand", view.game.state.players[1].hand[0].uid)]
    right_click(hidden, QPointF(55, 100))
    assert calls == ["hand", "shiki", "player"]


def test_battle_controls_keep_visible_edge_padding(qapp, view):
    from client.gui.battle_scene import SCENE_WIDTH, display_hand, layout_positions

    start(view, mulligan=False)
    positions = layout_positions(view.game, view.viewer)
    assert positions[("player", 0)].x() == 12
    assert positions[("player", 1)].x() == 12
    assert positions[("log",)].x() == 12
    assert positions[("end_turn",)].x() == 1484
    ordered = display_hand(view.game, view.viewer, view.viewer)
    hand = positions[("hand", ordered[-1].uid)]
    assert hand.x() + 110 == SCENE_WIDTH - 12


def test_battle_view_uses_extra_width_instead_of_side_letterbox(qapp, view):
    from client.gui.battle_scene import SCENE_HEIGHT

    start(view, mulligan=False)
    view.resize(1800, 900)
    view.show()
    qapp.processEvents()
    scene = view.battle_scene
    viewport = view.battle_view.viewport()
    expected_width = SCENE_HEIGHT * viewport.width() / viewport.height()
    assert scene.layout_width == pytest.approx(expected_width)
    assert scene.sceneRect().width() == pytest.approx(expected_width)
    left = view.battle_view.mapFromScene(QPointF(0, 0)).x()
    right = view.battle_view.mapFromScene(QPointF(scene.sceneRect().width(), 0)).x()
    assert left == pytest.approx(0, abs=5)
    assert right == pytest.approx(viewport.width(), abs=5)


def test_battle_uses_configured_cardbacks_and_word_art_controls(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    assert all(item.pixmap is not None and not item.pixmap.isNull()
               for item in scene.deck_backs.values())
    hidden_hand = next(item for key, item in scene.cards.items()
                       if key[0] == "hand" and item.player != view.viewer)
    assert hidden_hand.pixmap is not None and not hidden_hand.pixmap.isNull()
    assert view.end_turn_button.text() == ""
    assert view.end_turn_button.isFlat()
    assert not view.end_turn_button.icon().isNull()
    assert view.end_turn_button.property("assetName") == "end_turn_button"

    view.game.state.active = 1 - view.viewer
    view._render_state()
    assert view.end_turn_button.property("assetName") == "opponent_turn_button"


def test_hotseat_game_settings_refresh_cardbacks_immediately(qapp, view, monkeypatch):
    from PySide6.QtGui import QTransform
    from client.gui.settings import SettingsView
    from client.gui.ui_assets import cardback_pixmap, load_gui_settings, unnamed_misc_images

    start(view, mulligan=False)
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    class Preview:
        selected = "三途花境"

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    monkeypatch.setattr("client.gui.settings.CardbackPreviewDialog", Preview)
    view.open_settings()
    settings = seen["dialog"].findChild(SettingsView)
    settings.choose_cardback("own_cardback")
    deck = view.battle_scene.deck_backs[("deck_back", view.viewer, 0)]
    expected = cardback_pixmap("own", landscape=True).transformed(
        QTransform().rotate(180), Qt.SmoothTransformation)
    assert deck.pixmap.toImage() == expected.toImage()
    assert settings.cardback_buttons["own_cardback"].text() == "三途花境"

    default_icon = view.end_turn_button.icon().pixmap(104, 104).toImage()
    Preview.selected = unnamed_misc_images()[0]
    settings.choose_end_turn_background()
    assert load_gui_settings()["turn_background"] == Preview.selected
    assert view.end_turn_button.icon().pixmap(104, 104).toImage() != default_icon
    Preview.selected = "无"
    settings.choose_end_turn_background()
    assert load_gui_settings()["turn_background"] == ""
    assert view.end_turn_button.icon().pixmap(104, 104).toImage() == default_icon

    Preview.selected = unnamed_misc_images()[1]
    settings.choose_visual_option("opponent_turn_background")
    assert load_gui_settings()["opponent_turn_background"] == Preview.selected
    Preview.selected = "red"
    settings.choose_visual_option("defeated_variant")
    assert load_gui_settings()["defeated_variant"] == "red"
    Preview.selected = "purple"
    settings.choose_visual_option("upgrade_variant")
    assert load_gui_settings()["upgrade_variant"] == "purple"
    Preview.selected = "blue"
    settings.choose_visual_option("end_turn_variant")
    assert load_gui_settings()["end_turn_variant"] == "blue"
    Preview.selected = "silver"
    settings.choose_visual_option("opponent_turn_variant")
    assert load_gui_settings()["opponent_turn_variant"] == "silver"


def test_result_and_turn_banners_use_word_art(qapp, view):
    start(view, mulligan=False)
    view.game.state.winner = view.viewer
    view._render_state()
    assert view.result_banner.text() == ""
    assert view.result_banner.pixmap() is not None
    assert not view.result_banner.pixmap().isNull()
    assert view.result_banner.pixmap().width() >= 360
    assert view.result_banner.pixmap().height() >= 360
    assert view.battle_scene.result_item.sceneBoundingRect().center() == (
        view.battle_scene.sceneRect().center())
    assert view.battle_scene.result_back_item.y() >= (
        view.battle_scene.result_item.y() + view.result_banner.height())

    view.battle_scene.show_turn_banner(True)
    assert view.battle_scene.banner_pixmap_item.isVisible()
    assert view.battle_scene.banner_pixmap_item.property("assetName") == "your_turn_dark"


def test_timeline_refresh_interval_is_200ms(qapp, db, tmp_path):
    widget = HotseatView(db, store_path=tmp_path / "decks.json")
    assert widget.timeline_timer.interval() == 200
    widget.close()


def test_visual_events_are_nonblocking_and_not_added_to_text_log(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.state.timeline.append(
        {"k": "v", "v": "luck", "p": view.viewer, "s": 0, "dice": 6, "success": True})
    view._enqueue_timeline()
    assert not view.timeline_queue
    assert scene._visual_animations
    assert view.end_turn_button.isEnabled()
    animation = scene._visual_animations[0]
    assert animation.duration() <= 700
    assert scene._visual_events[animation]["v"] == "luck_dice"
    dice, offset = scene._visual_items[animation].layers[0]
    assert offset == QPointF(-dice.width() / 2, -dice.height() / 2)
    assert scene._visual_items[animation].pos() == scene.cards[("shiki", view.viewer, 0)].sceneBoundingRect().center()
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    result_animation = scene._visual_animations[0]
    assert scene._visual_events[result_animation]["v"] == "luck_result"
    result, offset = scene._visual_items[result_animation].layers[0]
    assert offset == QPointF(-result.width() / 2, -result.height() / 2 - 12)
    result_animation.setCurrentTime(result_animation.duration())
    qapp.processEvents()
    assert not scene._visual_animations


def test_luck_visuals_play_sequentially(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "luck", "p": view.viewer, "s": 0, "dice": 1,
                             "success": False, "on_fail": True})
    scene.play_visual_event({"v": "luck_reroll", "p": view.viewer, "s": 0,
                             "dice": 6, "previous_dice": 1})
    assert len(scene._visual_animations) == 1
    first = scene._visual_animations[0]
    first.setCurrentTime(first.duration())
    qapp.processEvents()
    result = scene._visual_animations[0]
    assert scene._visual_events[result]["v"] == "luck_result"
    result.setCurrentTime(result.duration())
    qapp.processEvents()
    animation = scene._visual_animations[0]
    assert scene._visual_events[animation]["v"] == "luck_reroll"
    word, offset = scene._visual_items[animation].layers[0]
    assert offset == QPointF(-word.width() / 2, -word.height() / 2 - 12)


def test_granular_luck_visuals_play_directly(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "luck_dice", "p": view.viewer, "s": 0, "dice": 1})
    scene.play_visual_event({"v": "luck_result", "p": view.viewer, "s": 0,
                             "dice": 1, "success": False, "on_fail": True})
    animation = scene._visual_animations[0]
    assert scene._visual_events[animation]["v"] == "luck_dice"
    assert [event["v"] for event in scene._visual_queue] == ["luck_result"]


@pytest.mark.parametrize("success,on_fail,visible", [
    (True, False, True), (False, False, False),
    (False, True, True), (True, True, False),
])
def test_luck_result_visual_only_for_effect_branch(qapp, view, success, on_fail, visible):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "luck_result", "p": view.viewer, "s": 0,
                             "dice": 6 if success else 1, "success": success,
                             "on_fail": on_fail})
    assert bool(scene._visual_animations) is visible
    assert bool(scene._visual_queue) is False
    if visible:
        animation = scene._visual_animations[0]
        word, offset = scene._visual_items[animation].layers[0]
        assert offset == QPointF(-word.width() / 2, -word.height() / 2 - 12)


def test_visuals_on_different_targets_play_in_parallel(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "luck", "p": 0, "s": None, "dice": 4, "success": True, "g": 1})
    scene.play_visual_event({"v": "luck", "p": 1, "s": None, "dice": 2,
                             "success": False, "on_fail": True, "g": 1})
    assert len(scene._visual_animations) == 2
    positions = {scene._visual_events[animation]["p"]: item.pos()
                 for animation, item in scene._visual_items.items()}
    assert positions[0] == scene.cards[("player", 0)].sceneBoundingRect().center()
    assert positions[1] == scene.cards[("player", 1)].sceneBoundingRect().center()

    scene.play_visual_event({"v": "luck_reroll", "p": 0, "s": None,
                             "dice": 6, "previous_dice": 4, "g": 1})
    assert len(scene._visual_queue) == 3
    first = next(animation for animation, event in scene._visual_events.items()
                 if event["p"] == 0 and event["v"] == "luck_dice")
    first.setCurrentTime(first.duration())
    qapp.processEvents()
    assert len(scene._visual_animations) == 2
    assert len(scene._visual_queue) == 2


def test_heal_visual_uses_signed_number_at_target_center(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    target = scene.cards[("shiki", view.viewer, 0)]
    scene.play_visual_event({"v": "heal", "p": view.viewer, "s": 0, "amount": 12})
    animation = scene._visual_animations[0]
    item = scene._visual_items[animation]
    number, offset = item.layers[0]
    assert not number.isNull() and number.width() > 70
    assert offset == QPointF(-number.width() / 2, -number.height() / 2)
    assert item.pos() == target.sceneBoundingRect().center()


def test_damage_visual_centers_scaled_ink_and_signed_number(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    target = scene.cards[("shiki", view.viewer, 0)]
    scene.play_visual_event({"v": "damage", "p": view.viewer, "s": 0, "amount": 123})
    animation = scene._visual_animations[0]
    item = scene._visual_items[animation]
    assert len(item.layers) == 2
    background, number = item.layers[0][0], item.layers[1][0]
    assert not background.isNull() and not number.isNull()
    assert background.width() <= 180
    assert number.width() <= round(background.width() * 0.85)
    for layer, offset in item.layers:
        assert offset == QPointF(-layer.width() / 2, -layer.height() / 2)
    assert item.pos() == target.sceneBoundingRect().center()


def test_defeat_visual_is_centered_slightly_above_shiki(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    target = scene.cards[("shiki", view.viewer, 0)]
    scene.play_visual_event({"v": "defeated", "p": view.viewer, "s": 0})
    animation = scene._visual_animations[0]
    item = scene._visual_items[animation]
    word, offset = item.layers[0]
    assert offset == QPointF(-word.width() / 2, -word.height() / 2 - 12)
    assert item.pos() == target.sceneBoundingRect().center()


def test_immune_response_and_upgrade_visual_layouts(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "immune", "p": 0, "s": 0})
    assert len(scene._visual_animations) == 1
    animation = scene._visual_animations[0]
    word, offset = scene._visual_items[animation].layers[0]
    assert offset == QPointF(-word.width() / 2, -word.height() / 2)
    assert scene._visual_items[animation].pos() == scene.cards[("shiki", 0, 0)].sceneBoundingRect().center()
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()

    scene.play_visual_event({"v": "upgrade", "p": 0, "s": 1})
    animation = scene._visual_animations[0]
    word, offset = scene._visual_items[animation].layers[0]
    target = scene.cards[("shiki", 0, 1)]
    assert offset.y() == -target.size.height() / 2 - word.height() - 8
    assert scene._visual_items[animation].pos() == target.sceneBoundingRect().center()
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()

    scene.play_visual_event({"v": "response", "p": 1})
    animation = scene._visual_animations[0]
    layers = scene._visual_items[animation].layers
    assert len(layers) == 2
    assert layers[0][1].x() == -layers[0][0].width()
    assert layers[1][1].x() == 0
    assert scene._visual_items[animation].pos() == scene.sceneRect().center()
    scene.play_visual_event({"v": "response", "p": view.viewer})
    assert len(scene._visual_animations) == 1  # 己方响应不显示中央提示


def test_turn_start_visuals_survive_hotseat_handoff(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view._handoff_pending = True
    view._handoff_stage = "transfer"
    view.game.state.timeline.append(
        {"k": "v", "v": "luck", "p": view.viewer, "s": 0, "dice": 4, "success": True})
    view._enqueue_timeline()
    assert not scene._visual_animations
    view.confirm_handoff()
    assert scene._visual_animations
    assert scene._visual_events[scene._visual_animations[0]]["dice"] == 4


def test_handoff_visual_queue_preserves_old_player_turn_end(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.state.players[1].combat_index = 0
    view.refresh()
    settle(view)
    card = view.game.state.players[0].hand[0]
    view.game.state.timeline.extend([
        {"k": "a", "u": card.uid, "c": card.id, "p": 0},
        {"k": "v", "v": "damage", "p": 0, "s": 1, "amount": 2},
    ])

    assert view.end_turn()
    assert scene.viewer == 0
    assert scene._visual_animations
    assert not scene.handoff_item.isVisible()
    first = scene._visual_animations[0]
    assert scene._visual_events[first]["v"] == "_card_use"
    first.setCurrentTime(first.duration())
    qapp.processEvents()
    assert scene._visual_animations
    assert not scene.handoff_item.isVisible()

    second = scene._visual_animations[0]
    assert scene._visual_events[second]["v"] == "damage"
    second.setCurrentTime(second.duration())
    qapp.processEvents()
    assert view._handoff_pending
    assert scene.handoff_item.isVisible()
    assert view._deferred_visuals[0]["v"] == "turn_start"
    assert any(entry.get("v") == "move" for entry in view._deferred_visuals)


def test_handoff_old_viewer_builds_and_plays_turn_end_draw(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    before = len(view.game.state.timeline)
    view.game.draw_cards(0, 1)
    draw_event = next(entry for entry in view.game.state.timeline[before:]
                      if entry.get("v") == "hand")

    assert view.end_turn()
    assert scene.viewer == 0
    assert view._handoff_waiting
    assert not view._handoff_pending
    item = scene.cards.get(("hand", draw_event["u"]))
    assert item is not None
    assert item.player == 0 and item.revealed
    assert item.isVisible()
    assert item in scene._move_animations
    assert view._deferred_visuals[0]["v"] == "turn_start"
    assert all(not card.revealed for card in scene_items(view, "hand", player=1))

    animation = scene._move_animations[item]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert view._handoff_pending
    assert not scene_items(view, "hand")

    view.confirm_handoff()
    assert scene.viewer == 1
    assert all(card.revealed for card in scene_items(view, "hand", player=1))


def test_handoff_visual_confirmation_replays_retreat_and_turn_banner(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.state.players[1].combat_index = 0
    view.refresh()
    settle(view)
    card = view.game.state.players[0].hand[0]
    view.game.state.timeline.append({"k": "a", "u": card.uid, "c": card.id, "p": 0})
    banners = []
    monkeypatch.setattr(scene, "show_turn_banner", lambda own: banners.append(own))

    assert view.end_turn()
    assert banners == []
    while not view._handoff_pending:
        assert scene.visual_busy
        for animation in list(scene._visual_animations):
            animation.setCurrentTime(animation.duration())
            qapp.processEvents()
    assert banners == []
    assert not scene._move_animations

    view.confirm_handoff()
    assert banners == [True]
    assert not view._deferred_visuals
    assert scene._move_animations
    retreat = next(iter(scene._move_animations.values()))
    assert retreat.endValue() != retreat.startValue()
    retreat.setCurrentTime(retreat.duration())
    qapp.processEvents()


def test_handoff_visual_turn_banner_waits_for_old_player_choice(qapp, view):
    start(view, mulligan=False)
    old_turn_key = view._last_turn_key
    view.game.state.active = 1
    view.game.state.turn += 1
    view.game.state.pending_choice = {
        "kind": "choose", "player": 0, "options": ["继续"],
    }
    view.refresh()

    assert view.viewer == 0
    assert view._last_turn_key == old_turn_key
    view.game.state.pending_choice = None
    view.refresh()
    view.confirm_handoff()
    assert view.battle_scene.banner_pixmap_item.property("assetName") == "your_turn_dark"


def test_handoff_visual_queue_defers_events_during_old_player_choice(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.state.active = 1
    view.game.state.turn += 1
    choice_uid = view.game.state.players[0].deck[0].uid
    view.game.state.pending_choice = {
        "kind": "deck_top_pick", "player": 0, "options": [choice_uid],
        "count": 1, "remaining": 1,
    }
    view.game.state.timeline.extend([
        {"k": "v", "v": "damage", "p": 0, "s": 0, "amount": 1},
        {"k": "v", "v": "turn_start", "p": 1},
        {"k": "v", "v": "luck_dice", "p": 1, "s": 0, "dice": 4},
    ])
    view.refresh()

    assert view.viewer == 0
    assert view._handoff_waiting
    assert view.choice_dialog is not None
    assert not view._handoff_pending
    assert [entry["v"] for entry in view._deferred_visuals] == ["turn_start", "luck_dice"]
    animation = scene._visual_animations[0]
    assert scene._visual_events[animation]["v"] == "damage"
    assert not scene._visual_queue

    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert view._handoff_waiting
    assert not view._handoff_pending
    assert view.choice_dialog is not None
    assert not view.end_turn()
    assert not view.apply_command({"op": "choose", "player": 1, "uid": choice_uid})
    assert view.game.state.pending_choice is not None

    assert view.answer_pending(choice_uid)
    assert view.game.state.pending_choice is None
    assert any(card.uid == choice_uid for card in view.game.state.players[0].hand)
    assert view._deferred_visuals[-1]["v"] == "hand"
    assert view._handoff_pending
    assert scene.viewer == 0
    assert not scene._visual_animations
    view.confirm_handoff()
    assert scene.viewer == 1
    assert not view._deferred_visuals
    animation = scene._visual_animations[0]
    assert scene._visual_events[animation]["v"] == "luck_dice"
    assert scene._visual_events[animation]["p"] == 1


def test_upgrade_visual_busy_locks_inputs_and_focus(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    scene = view.battle_scene
    view.game.state.timeline.append(
        {"k": "v", "v": "luck_dice", "p": 0, "s": 0, "dice": 4})
    view._enqueue_timeline()

    assert not view._inputs_open()
    assert scene.visual_busy
    assert not scene.focus_overlay.isVisible()
    assert not scene.upgrade_badges
    assert not view.upgrade(1)

    animation = scene._visual_animations[0]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert not scene.visual_busy
    assert view._inputs_open()
    assert scene.focus_overlay.isVisible()
    assert scene.upgrade_badges
    assert view.upgrade(1)


def test_upgrade_visual_busy_does_not_wait_for_text_log(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    view.game.state.timeline.append({"k": "l", "m": "升级阶段文字记录", "o": 0})
    view._enqueue_timeline()
    assert view.timeline_queue
    assert view._inputs_open()
    assert view.upgrade(1)


def test_consecutive_upgrade_focus_refreshes_after_visual(qapp, view):
    start(view, mulligan=False, config=GameConfig(
        auto_skip_upgrade=False, upgrade_rule="free", max_level=1))
    scene = view.battle_scene
    view.game.current.upgrades = 2
    view.refresh()
    item = scene.cards[("shiki", 0, 1)]
    original_art = item.pixmap.cacheKey()
    second = next(index for index in view.game.legal_upgrade_indices(0) if index != 1)

    assert view.upgrade(1)
    assert scene.visual_busy
    assert not view.upgrade(second)
    animation = scene._visual_animations[0]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()

    assert item.pixmap.cacheKey() != original_art
    assert 1 not in scene.upgrade_badges
    assert not item.playable
    assert scene.focus_overlay.isVisible()
    assert scene.focus_overlay.path().contains(item.sceneBoundingRect().center())
    assert view.upgrade(second)


def test_defeat_word_art_precedes_revive_countdown(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"k": "v", "v": "defeated", "p": view.viewer, "s": 0})
    assert scene.defeat_countdown_hidden(view.viewer, 0)
    animation = scene._visual_animations[0]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert not scene.defeat_countdown_hidden(view.viewer, 0)


def test_animation_groups_only_parallelize_same_effect(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "luck", "p": 0, "s": None, "dice": 4, "success": True, "g": 7})
    scene.play_visual_event({"v": "luck", "p": 1, "s": None, "dice": 2, "success": False, "g": 7})
    scene.play_visual_event({"v": "damage", "p": 0, "s": 0, "amount": 3})
    assert len(scene._visual_animations) == 2
    while scene._visual_animations and all(
            event["v"] != "damage" for event in scene._visual_events.values()):
        for animation in list(scene._visual_animations):
            animation.setCurrentTime(animation.duration())
            qapp.processEvents()
    assert len(scene._visual_animations) == 1
    assert scene._visual_events[scene._visual_animations[0]]["v"] == "damage"


def test_movement_damage_defeat_and_return_share_linear_queue(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    scene._animate_position(item, QPointF(646, 460))
    scene.play_visual_event({"v": "damage", "p": 0, "s": 1, "amount": 3, "g": 9})
    scene.play_visual_event({"v": "damage", "p": 1, "s": 1, "amount": 2, "g": 9})
    scene.play_visual_event({"v": "defeated", "p": 0, "s": 0})
    scene._animate_position(item, QPointF(196, 570))
    assert len(scene._move_animations) == 1
    assert len(scene._visual_animations) == 1
    assert scene._visual_events[scene._visual_animations[0]]["v"] == "_move"

    first_move = next(iter(scene._move_animations.values()))
    first_move.setCurrentTime(first_move.duration())
    qapp.processEvents()
    assert len(scene._visual_animations) == 2
    for animation in list(scene._visual_animations):
        animation.setCurrentTime(animation.duration())
        qapp.processEvents()
    assert len(scene._visual_animations) == 1
    assert scene._visual_events[scene._visual_animations[0]]["v"] == "defeated"
    scene._visual_animations[0].setCurrentTime(scene._visual_animations[0].duration())
    qapp.processEvents()
    assert len(scene._move_animations) == 1


def test_entity_art_waits_for_damage_animation(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    original = item.pixmap.cacheKey()
    view.game.deal_to_shikigami(Ref(player=0, shikigami=0), 1, Ref(player=1, shikigami=0))
    view.refresh()
    assert item.pixmap.cacheKey() == original
    animation = scene._visual_animations[0]
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    assert item.pixmap.cacheKey() != original


def test_player_health_color_tracks_missing_and_bonus_cap(qapp, view):
    start(view, mulligan=False)
    player = view.game.current
    player.health = 20
    view.refresh()
    item = view.battle_scene.cards[("player", view.viewer)]
    assert item.health_color == "red"
    player.max_health = 35
    player.health = 35
    view.refresh()
    assert item.health_color == "green"
    player.max_health = player.health = 30
    view.refresh()
    assert item.health_color == "white"


def test_assault_and_response_animations_use_viewer_sides_and_order(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    scene.play_visual_event({"v": "assault", "p": 1})
    animation = scene._visual_animations[0]
    assert animation.duration() == 900
    assert scene._visual_items[animation].pos().x() > scene.sceneRect().center().x()
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()

    card = view.game.state.players[1].hand[0]
    scene.animate_card_use(card.uid, card.id, 1, response=True)
    assert scene._visual_events[scene._visual_animations[0]]["v"] == "response"
    response_animation = scene._visual_animations[0]
    response_animation.setCurrentTime(response_animation.duration())
    qapp.processEvents()
    card_animation = scene._card_use_animations[0]
    assert scene._card_use_sources[card_animation]["big_pos"].x() > scene.sceneRect().center().x()


def test_combat_card_stats_refresh_between_card_and_move(qapp, db, view, monkeypatch):
    """战斗牌力量是本次战斗的临时力量，不用战力小图标；用牌→加成→卡面
    效果→移入战斗区→并行战斗伤害→数值刷新严格按此时点排列。"""
    cid = 10010154
    db.cards[cid] = F.card(cid, card_type="combat", token=True, steps=[
        F.Step(op="buff_power", amount=2, target=F.T(kind="self")),
        F.Step(op="gain_shield", amount=2, target=F.T(kind="self")),
        F.Step(op="damage", amount=1, target=F.T(kind="all", pool="enemy_player")),
    ])
    start(view, mulligan=False)
    seen = []
    original = view.game._apply_combat_stats

    def capture(ref, shiki, power, shield, *, battle_scoped):
        original(ref, shiki, power, shield, battle_scoped=battle_scoped)
        seen.append((shiki.temp_power, shiki.combat_power))

    monkeypatch.setattr(view.game, "_apply_combat_stats", capture)
    view.game.state.players[1].shield = 0  # 让卡面效果伤害实际扣血，产生完整时点序列
    card = F.give(view.game, 0, cid)
    view.play_card(card.uid)
    assert seen == [(2, 0)]
    entries = [entry for entry in view.game.state.timeline
               if entry.get("k") == "a" or entry.get("k") == "v"]
    kinds = [entry.get("v", "card_use") for entry in entries]
    assert kinds.index("card_use") < kinds.index("stat")
    assert kinds.index("stat") < kinds.index("damage") < kinds.index("move")
    combat_damage = [entry for entry in entries if entry.get("v") == "damage"
                     and entry.get("amount") != 1]
    assert len(combat_damage) == 1  # 敌方战斗区为空，仅攻击牌手
    assert view.game.state.players[0].shikigami[0].temp_power == 0


def test_form_art_refreshes_after_card_use(qapp, db, view):
    form_id = 10010155
    db.cards[form_id] = F.card(form_id, token=True, card_type="form",
                               form_power=2, form_health=6)
    start(view, mulligan=False)
    item = view.battle_scene.cards[("shiki", 0, 0)]
    original = item.pixmap.cacheKey()
    card = F.give(view.game, 0, form_id)
    view.play_card(card.uid)
    settle(view)
    assert item.cdef.id == form_id
    assert item.pixmap.cacheKey() != original


def test_choice_view_has_no_background_and_compact_layout(qapp, db, view):
    field_id = 10010161
    db.cards[field_id] = F.card(field_id, shikigami=100101, card_type="field", intensity=3)
    start(view, mulligan=False)
    first = F.give(view.game, 0, field_id)
    view.game._open_discard_pick(0, 1, card_type="field")
    view.refresh()
    dialog = view.choice_dialog
    assert not dialog.option_view.styleSheet()
    assert dialog.option_view._wrappers[first.uid].layout().spacing() == 0
    assert dialog.width() <= 720


def test_deck_orientation_matches_legacy_up_left_rendering(qapp, view):
    from PySide6.QtGui import QTransform
    from client.gui.battle_scene import DECK_BACK_SIZE
    from client.gui.ui_assets import cardback_pixmap

    start(view, mulligan=False)
    assert DECK_BACK_SIZE.width() >= 150
    enemy = [view.battle_scene.deck_backs[("deck_back", 1, index)]
             for index in range(3)]
    own = [view.battle_scene.deck_backs[("deck_back", 0, index)]
           for index in range(3)]
    assert [item.rotation() for item in enemy] == [195, 205, 215]
    assert [item.rotation() for item in own] == [145, 155, 165]
    assert [item.rotation() for item in own] == [360 - enemy[2-i].rotation()
                                                for i in range(3)]
    for side, items, legacy_rotations in (
            ("enemy", enemy, (15, 25, 35)), ("own", own, (-35, -25, -15))):
        original = cardback_pixmap(side, landscape=True)
        for item, legacy_rotation in zip(items, legacy_rotations):
            assert item.rotation() == legacy_rotation + 180
            uncompensated = item.pixmap.transformed(
                QTransform().rotate(180), Qt.SmoothTransformation)
            assert uncompensated.toImage() == original.toImage()
    assert own[1].pos() - own[0].pos() == own[2].pos() - own[1].pos()
    assert enemy[0].x() < enemy[1].x() < enemy[2].x()
    assert own[0].x() > own[1].x() > own[2].x()
    assert [item.y() for item in enemy] == sorted(item.y() for item in enemy)
    assert [item.y() for item in own] == sorted(item.y() for item in own)
    assert 120 <= enemy[0].y() < 200
    assert enemy[-1].sceneBoundingRect().bottom() >= 370
    assert 510 <= own[0].sceneBoundingRect().top() <= 580


def test_move_visual_uses_event_zone_instead_of_final_state(qapp, view):
    from client.gui.battle_scene import layout_positions

    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    view.game.state.players[0].combat_index = 0
    expected = layout_positions(view.game, view.viewer,
                                scene_width=scene.layout_width)[("shiki", 0, 0)]
    scene.play_visual_event({"v": "move", "p": 0, "s": 0, "zone": "combat"})
    animation = scene._move_animations[item]
    assert animation.endValue() == expected
    animation.setCurrentTime(animation.duration())
    qapp.processEvents()
    view.game.state.players[0].combat_index = None
    scene.play_visual_event({"v": "move", "p": 0, "s": 0, "zone": "ready"})
    animation = scene._move_animations[item]
    assert animation.endValue() == QPointF(196, 570)


def test_combat_damage_defeat_and_return_are_parallel_phases(qapp, view):
    start(view, mulligan=False)
    pa, pb = view.game.state.players
    pa.shikigami[0].level = pb.shikigami[0].level = 1
    pa.shikigami[0].health = pb.shikigami[0].health = 3
    pb.combat_index = 0
    view.assault(0)
    entries = [entry for entry in view.game.state.timeline if entry.get("k") == "v"]
    damage = [entry for entry in entries if entry["v"] == "damage"]
    stats = [entry for entry in entries if entry["v"] == "stat"]
    defeats = [entry for entry in entries if entry["v"] == "defeated"]
    returns = [entry for entry in entries
               if entry["v"] == "move" and entry.get("zone") == "ready"]
    assert len(damage) == len(stats) == len(defeats) == len(returns) == 2
    for wave in (damage, stats, defeats, returns):
        assert len({entry.get("g") for entry in wave}) == 1
        assert wave[0].get("g") is not None
    assert len({damage[0]["g"], stats[0]["g"], defeats[0]["g"], returns[0]["g"]}) == 4
    kinds = [entry["v"] for entry in entries]
    damage_indices = [i for i, entry in enumerate(entries) if entry["v"] == "damage"]
    return_indices = [i for i, entry in enumerate(entries)
                      if entry["v"] == "move" and entry.get("zone") == "ready"]
    assert max(damage_indices) < kinds.index("stat") < kinds.index("defeated") \
        < min(return_indices)


def test_combat_visual_defeat_snapshot(qapp, view, monkeypatch):
    import json
    from client.gui import battle_scene, cardart
    from client.gui.battle_scene import combat_position, layout_positions

    rendered = []
    visible = []
    original = cardart._cached_entity_pixmap
    original_entity = battle_scene.entity_pixmap

    def capture(*args):
        state = json.loads(args[2])
        state["_defeated"] = json.loads(args[1])["_defeated"]
        rendered.append(state)
        return original(*args)

    def capture_visible(*args, **kwargs):
        pixmap = original_entity(*args, **kwargs)
        if kwargs.get("snapshot") is not None:
            state = dict(rendered[-1])
            state["_key"] = next((pi, index) for pi, player in enumerate(
                view.game.state.players) for index, shiki in enumerate(player.shikigami)
                                 if shiki is args[0])
            visible.append(state)
        return pixmap

    monkeypatch.setattr(cardart, "_cached_entity_pixmap", capture)
    monkeypatch.setattr(battle_scene, "entity_pixmap", capture_visible)
    start(view, mulligan=False)
    scene = view.battle_scene
    pa, pb = view.game.state.players
    pa.shikigami[0].level = pb.shikigami[0].level = 1
    pa.shikigami[0].health = pb.shikigami[0].health = 3
    pb.combat_index = 0
    view.refresh()
    settle(view)
    keys = [(0, 0), (1, 0)]
    items = {key: scene.cards[("shiki", *key)] for key in keys}
    assert items[(1, 0)].pos() == combat_position(scene.layout_width, True)

    view.assault(0)
    view.timeline_timer.stop()
    assert [event["v"] for event in scene._visual_events.values()] == ["assault"]
    assert not scene._move_animations
    assert not scene._defeat_visuals
    view._render_state()
    assert not any(event.get("v") == "_move" for event in scene._visual_queue)

    defeats = [entry for entry in view.game.state.timeline if entry.get("v") == "defeated"]
    returns = [entry for entry in view.game.state.timeline
               if entry.get("v") == "move" and entry.get("zone") == "ready"]
    assert len(defeats) == len(returns) == 2
    for defeat in defeats:
        assert defeat["r"]["defeated"] is True
        assert defeat["r"]["revive_countdown"] == 3
        returning = next(entry for entry in returns
                         if (entry["p"], entry["s"]) == (defeat["p"], defeat["s"]))
        assert returning["r"] == defeat["r"]
    for player in (pa, pb):
        player.shikigami[0].revive_countdown = 9

    def finish(kind):
        animations = [animation for animation, event in scene._visual_events.items()
                      if event.get("v") == kind]
        assert animations
        for animation in animations:
            animation.setCurrentTime(animation.duration())
            qapp.processEvents()

    finish("assault")
    assert [event["v"] for event in scene._visual_events.values()] == ["_move"]
    assert not scene._defeat_visuals
    view._render_state()
    assert not any(event.get("v") == "_move" for event in scene._visual_queue)

    finish("_move")
    assert [event["v"] for event in scene._visual_events.values()] == ["damage"] * 2
    assert not scene._defeat_visuals
    view._render_state()
    assert not any(event.get("v") == "_move" for event in scene._visual_queue)

    finish("damage")
    assert [event["v"] for event in scene._visual_events.values()] == ["stat"] * 2
    assert not scene._defeat_visuals
    assert [(state["_defeated"], state["defeated_countdown"], state["health"])
            for state in visible[-2:]] == [(False, None, 0), (False, None, 0)]
    view._render_state()

    finish("stat")
    assert [event["v"] for event in scene._visual_events.values()] == ["defeated"] * 2
    assert scene._defeat_visuals == set(keys)
    assert all(state["defeated_countdown"] is None for state in visible[-2:])
    view._render_state()

    finish("defeated")
    assert [event["v"] for event in scene._visual_events.values()] == ["_move"] * 2
    assert not scene._defeat_visuals
    for key in keys:
        latest = next(state for state in reversed(visible) if state["_key"] == key)
        assert latest["defeated_countdown"] == 3
    view._render_state()

    finish("_move")
    assert not scene._visual_animations and not scene._visual_queue
    positions = layout_positions(view.game, view.viewer, scene_width=scene.layout_width)
    for key, item in items.items():
        assert item.pos() == positions[("shiki", *key)]
        assert view.game.state.players[key[0]].shikigami[key[1]].defeated
    view._render_state()
    assert not scene._move_animations


def test_revive_zero_render_animation_chain(qapp, view):
    """真实回合队列的倒计时归零到复活始终使用 200ms 小卡过渡帧。"""
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    expected_size = item.size
    shiki = view.game.current.shikigami[0]
    shiki.defeated = True
    shiki.health = 0
    shiki.revive_countdown = 1
    assert view.end_turn()
    settle(view)
    assert view.end_turn()
    assert view._handoff_pending
    view.confirm_handoff()

    played = []
    while scene._visual_queue or scene._visual_animations:
        for animation in list(scene._visual_animations):
            event = scene._visual_events[animation]
            target_event = (event.get("v") in ("countdown", "revive")
                            and (event.get("p"), event.get("s")) == (0, 0))
            if target_event:
                if not played:
                    assert any(queued.get("v") == "revive"
                               for queued in scene._visual_queue)
                played.append(event)
                assert animation.duration() == 200
                assert item.pixmap is not None and not item.pixmap.isNull()
                assert item.size == expected_size
            animation.setCurrentTime(animation.duration())
            qapp.processEvents()
            if target_event:
                assert item.pixmap is not None and not item.pixmap.isNull()
                assert item.size == expected_size

    assert [event["v"] for event in played] == ["countdown", "revive"]
    zero, revived = (event["r"] for event in played)
    assert (zero["defeated"], zero["revive_countdown"], zero["revive_pending"]) \
        == (True, 0, True)
    assert (revived["defeated"], revived["revive_countdown"], revived["revive_pending"]) \
        == (False, 0, False)
    settle(view)


def test_parallel_heal_has_following_parallel_refresh_phase(qapp, db, view):
    cid = 10010156
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="heal", amount=2, parallel=True,
               target=F.T(kind="all", pool="friendly_character"))])
    start(view, mulligan=False)
    player = view.game.current
    player.health = 27
    player.shikigami[0].level = player.shikigami[1].level = 1
    player.shikigami[0].health = 2
    player.shikigami[1].health = 3
    card = F.give(view.game, 0, cid)
    view.play_card(card.uid)
    entries = [entry for entry in view.game.state.timeline
               if entry.get("v") in ("heal", "stat")]
    heals = [entry for entry in entries if entry["v"] == "heal"]
    stats = [entry for entry in entries if entry["v"] == "stat"]
    assert len(heals) == len(stats) == 3
    assert [entry["v"] for entry in entries] == ["heal"] * 3 + ["stat"] * 3
    assert len({entry["g"] for entry in heals}) == 1
    assert len({entry["g"] for entry in stats}) == 1
    assert heals[0]["g"] != stats[0]["g"]


def test_parallel_damage_shield_refresh_is_a_preceding_phase(qapp, db, view):
    cid = 10010157
    db.cards[cid] = F.card(cid, token=True, steps=[
        F.Step(op="damage", amount=2, parallel=True,
               target=F.T(kind="all", pool="enemy_shikigami"))])
    start(view, mulligan=False)
    enemy = view.game.state.players[1]
    enemy.shikigami[0].level = enemy.shikigami[1].level = 1
    enemy.shikigami[0].shield = enemy.shikigami[1].shield = 1
    card = F.give(view.game, 0, cid)
    view.play_card(card.uid)
    entries = [entry for entry in view.game.state.timeline
               if entry.get("v") in ("damage", "stat")]
    assert [entry["v"] for entry in entries] == ["stat"] * 2 + ["damage"] * 2 + ["stat"] * 2
    for wave in (entries[:2], entries[2:4], entries[4:]):
        assert len({entry["g"] for entry in wave}) == 1 and wave[0]["g"] is not None
    assert len({entries[0]["g"], entries[2]["g"], entries[4]["g"]}) == 3


def test_zero_damage_visual_has_centered_signed_zero(qapp, view):
    """damage(amount=0) 直接播放为居中的 -0 数字与墨色背景。"""
    start(view, mulligan=False)
    scene = view.battle_scene
    target = scene.cards[("shiki", view.viewer, 0)]
    scene.play_visual_event({"v": "damage", "p": view.viewer, "s": 0, "amount": 0})
    animation = scene._visual_animations[0]
    item = scene._visual_items[animation]
    assert len(item.layers) == 2
    number = item.layers[1][0]
    assert not number.isNull() and number.width() > 0
    for layer, offset in item.layers:
        assert offset == QPointF(-layer.width() / 2, -layer.height() / 2)
    assert item.pos() == target.sceneBoundingRect().center()
