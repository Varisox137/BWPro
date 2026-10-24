"""桌面 GUI 本地热坐对战测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from client.gui.app import MainWindow
from client.gui.battle import DeckSelectDialog, HotseatView
from core.model import GameConfig, Ref
from db import deckcode, deckstore
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
    while view.timeline_queue:
        view.play_next_timeline()


def player_tuple(name="玩家"):
    return name, list(F.TEAM), F.deck_of(*F.TEAM)


def start(view, **kwargs):
    kwargs.setdefault("first", 0)
    kwargs.setdefault("shuffle_team", False)
    kwargs.setdefault("config", GameConfig(auto_skip_upgrade=True))
    view.start_game(player_tuple("玩家A"), player_tuple("玩家B"), seed=7, **kwargs)
    settle(view)


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
    assert len(view.player_frames) == 2
    assert len(view.shiki_frames) == 8
    assert "先手" in view.seat_label.text()


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
    assert len(view.hand_frames) == len(game.state.players[0].hand)


def test_upgrade_assault_and_end_turn(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    game = view.game
    assert view.phase_label.text().startswith("升级")
    assert view.shiki_frames[(0, 1)].upgrade_button.isEnabled()
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
    assert view.shiki_frames[(1, 0)].property("targetable") is True
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
