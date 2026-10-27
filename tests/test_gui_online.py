"""桌面 GUI 联机视图与 NetBridge 测试（QT_QPA_PLATFORM=offscreen）。"""
import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

from client import cli
from client.gui.app import MainWindow
from client.gui.online import NetBridge, OnlineBattleView, OnlineView
from db import deckcode, deckstore
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


class FakeWS:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def __iter__(self):
        return iter(self.messages)

    def send(self, text):
        self.sent.append(text)

    def close(self):
        self.closed = True


class FakeBridge(QObject):
    message = Signal(dict)
    disconnected = Signal(str)

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self.sent = []

    def start(self):
        pass

    def send(self, msg):
        self.sent.append(msg)

    def send_cmd(self, cmd):
        self.sent.append({"type": "cmd", "cmd": cmd})

    def close(self):
        self.ws.close()


@pytest.fixture
def view(qapp, db, tmp_path):
    widget = OnlineView(db, store_path=tmp_path / "decks.json",
                        bridge_factory=FakeBridge)
    yield widget
    if widget.bridge is not None:
        widget.bridge.close()
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def save_standard_deck(db, path):
    groups = deckcode.group_deck(db, F.TEAM, F.deck_of(*F.TEAM))
    deckstore.save_decks(db, [{"name": "联机卡组", "groups": groups, "env": None}], path)


def test_net_bridge_forwards_messages_and_sends_without_wait(qapp):
    ws = FakeWS([json.dumps({"type": "notice", "text": "公告"}),
                 json.dumps({"type": "lobby", "ready": [], "deadline": None})])
    bridge = NetBridge(ws)
    received = []
    disconnected = []
    bridge.message.connect(received.append)
    bridge.disconnected.connect(disconnected.append)
    bridge.start()
    bridge._thread.join(timeout=2)
    for _ in range(10):
        qapp.processEvents()
    assert [msg["type"] for msg in received] == ["notice", "lobby"]
    assert disconnected == ["连接已断开"]
    bridge.send_cmd({"op": "ready"})
    assert json.loads(ws.sent[0]) == {"type": "cmd", "cmd": {"op": "ready"}}


def test_connection_validation_probe_and_enter_lobby(qapp, db, view):
    save_standard_deck(db, view.store_path)
    view.reload_decks()
    view.server_edit.setText("localhost:1037")
    view.name_edit.setText("玩家")
    view.deck_combo.setCurrentIndex(0)
    view.probe = lambda _url: "连接失败"
    assert not view.connect_server()
    assert view.stack.currentWidget() is view.connect_page
    assert "连接失败" in view.connect_error.text()

    view.probe = lambda _url: None
    view.opener = lambda _url: FakeWS()
    assert view.connect_server()
    assert view.server_url == "ws://localhost:1037/ws"
    assert view.stack.currentWidget() is view.lobby_page
    assert isinstance(view.bridge, FakeBridge)


def test_lobby_messages_render_ready_environment_and_notices(qapp, db, view):
    save_standard_deck(db, view.store_path)
    view.reload_decks()
    view.player_name = "玩家"
    view.deck_name = "联机卡组"
    view.handle_message({"type": "joined", "room_id": "ABC123", "token": "令牌", "seat": 0})
    deadline = time.time() + 15
    view.handle_message({"type": "lobby", "ready": ["玩家"], "deadline": deadline,
                         "mode": "free", "env_date": 20191212})
    assert "ABC123" in view.room_label.text()
    assert "联机卡组" in view.self_label.text()
    assert "取消准备" in view.ready_button.text()
    assert "20191212" in view.env_edit.text()
    assert "15" in view.lobby_status.text() or "14" in view.lobby_status.text()
    view.ready_button.click()
    assert view.ready_button.isEnabled()
    view.handle_message({"type": "notice", "text": "服务器公告"})
    assert "服务器公告" in view.lobby_error.text()
    view.handle_message({"type": "peer_left", "name": "对手"})
    assert "等待" in view.lobby_status.text()


def test_online_battle_notice_is_visible_until_message_is_cleared(qapp, view):
    view.stack.setCurrentWidget(view.battle)
    view.battle.error_label.hide()
    view.handle_message({"type": "notice", "text": "服务器公告"})
    assert not view.battle.error_label.isHidden()
    assert view.battle.error_label.text() == "公告：服务器公告"
    view.battle.error_label.clear()
    assert view.battle.error_label.isHidden()


def test_online_battle_state_push_and_command_send(qapp, db, make_game):
    game = make_game(mulligan=True)
    sent = []
    battle = OnlineBattleView(db, send_command=sent.append)
    battle.timeline_timer.setInterval(0)
    battle.me = 1
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = json.loads(json.dumps(cli.hand_cards_info(game, 1)))
    battle.set_state(payload, timer={"kind": "mulligan", "deadline": time.time() + 30},
                     log=["开局"], timeline=[])
    assert "⏱ 调度 0:" in battle.phase_label.text()
    assert all(isinstance(uid, int) for uid in battle.hand_info())
    assert battle.viewer == 1
    assert battle.stack.currentWidget() is battle.battle_page
    scene = battle.battle_scene
    assert len([key for key in scene.cards if key[0] == "hand"
                and scene.cards[key].player == 1]) == 5
    slots = {key: item for key, item in scene.cards.items() if key[0] == "shiki"}
    refs = {key: item.payload for key, item in slots.items()}
    assert scene.cards[("player", 0)].y() < scene.cards[("player", 1)].y()
    battle.me = 0
    battle.refresh()
    assert not battle._handoff_pending
    assert battle.handoff_dialog is None
    assert {key: item for key, item in scene.cards.items() if key[0] == "shiki"} == slots
    assert {key: item.payload for key, item in slots.items()} == refs
    assert scene.cards[("player", 1)].y() < scene.cards[("player", 0)].y()
    battle.show_log()
    battle.reset_session()
    assert battle.log_dialog.isHidden()
    battle.me = 1
    battle.set_state(payload, timer={"kind": "mulligan", "deadline": time.time() + 30},
                     log=["开局"], timeline=[])
    uid = game.state.players[1].hand[0].uid
    assert battle.mulligan(uid)
    assert sent[0]["op"] == "mulligan" and sent[0]["player"] == 1
    assert game.state.players[1].hand[0].uid == uid  # 本地 state 不被直接修改
    battle.close()


def test_online_enemy_turn_blocks_all_active_inputs(qapp, db, make_game):
    game = make_game(mulligan=False)
    game.state.active = 1
    sent = []
    battle = OnlineBattleView(db, send_command=sent.append)
    battle.me = 0
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = cli.hand_cards_info(game, 0)
    battle.set_state(payload, log=[], timeline=[])
    scene = battle.battle_scene
    assert not battle._inputs_open()
    assert not battle.end_turn_button.isEnabled()
    assert all(not item.playable for key, item in scene.cards.items()
               if key[0] in ("hand", "shiki") and item.player == 0)
    hand = scene.cards[("hand", game.state.players[0].hand[0].uid)]
    shiki = scene.cards[("shiki", 0, 0)]
    assert not scene.drag_controller.press(hand, hand.scenePos())
    assert not scene.drag_controller.press(shiki, shiki.scenePos())
    assert not battle.end_turn()
    assert not battle.assault(0)
    assert not battle.play_card(hand.uid)
    assert sent == []
    battle.close()


def test_online_sanitized_enemy_hand_keeps_distinct_private_slots(qapp, db, make_game):
    from server.room import sanitize_state

    game = make_game(mulligan=False)
    enemy = game.state.players[1]
    for card, hand_seq in zip(enemy.hand, (50, 10, 40, 20, 30)):
        card.hand_seq = hand_seq
    revealed = enemy.hand[1]
    revealed.mods["revealed"] = True
    payload = sanitize_state(game.state.model_dump(mode="json"), viewer=0)
    payload["hand_info"] = json.loads(json.dumps(cli.hand_cards_info(game, 0)))
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.me = 0
    battle.set_state(payload, log=[], timeline=[])

    sanitized = battle.game.state.players[1].hand
    assert len(sanitized) == 5
    assert [card.hand_seq for card in sorted(sanitized, key=lambda c: c.hand_seq)] == [
        10, 20, 30, 40, 50]
    items = [battle.battle_scene.cards[("hand", card.uid)]
             for card in sorted(sanitized, key=lambda c: c.hand_seq)]
    assert len({item.key for item in items}) == 5
    assert [item.x() for item in items] == sorted(item.x() for item in items)
    assert len({item.x() for item in items}) == 5
    revealed_item = battle.battle_scene.cards[("hand", revealed.uid)]
    assert items.index(revealed_item) == 0
    assert revealed_item.revealed and revealed_item.cdef.id == revealed.id
    assert revealed_item.payload.id == revealed.id
    for card, item in zip(sorted(sanitized, key=lambda c: c.hand_seq), items):
        if card.uid == revealed.uid:
            continue
        assert card.id == 0 and card.mods == {}
        assert item.cdef is None and item.payload is None
    battle.close()


def test_reconnect_restores_pending_choice(qapp, db, make_game):
    game = make_game(mulligan=True)
    game.state.pending_choice = {"kind": "deck_top_pick", "player": 1,
                                 "options": [c.uid for c in game.state.players[1].deck[:2]],
                                 "remaining": 1}
    sent = []
    battle = OnlineBattleView(db, send_command=sent.append)
    battle.me = 1
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = cli.hand_cards_info(game, 1)
    battle.set_state(payload, log=[], timeline=[])
    assert battle.choice_dialog is not None
    battle.answer_pending(game.state.pending_choice["options"][0])
    assert sent[0]["op"] == "choose"
    battle.close()


def test_main_window_online_page_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    view = win.pages["online"]
    assert isinstance(view, OnlineView)
    win.toggle_theme()
    assert view.theme == "dark"
    save_standard_deck(db, view.store_path)
    view.reload_decks()
    view.bridge_factory = FakeBridge
    view.probe = lambda _url: None
    sockets = []

    def open_socket(_url):
        sockets.append(FakeWS())
        return sockets[-1]

    view.opener = open_socket
    assert view.connect_server()
    view.battle.timeline_timer.start()
    win.go("online")
    win.back_button.click()
    assert win.stack.currentIndex() == 0
    assert sockets[0].closed and view.bridge is None
    assert not view.clock.isActive()
    assert not view.battle.timeline_timer.isActive()
    assert not view.battle.countdown_timer.isActive()
    win.close()


def test_disconnected_join_reopens_socket_and_sends_token(qapp, db, view):
    save_standard_deck(db, view.store_path)
    view.reload_decks()
    view.server_url = "ws://localhost:1037/ws"
    view.opener = lambda _url: FakeWS()
    view.room_id = "ABC123"
    view.token = "令牌"
    view.room_edit.setText(view.room_id)
    view.token_edit.setText(view.token)
    view.on_disconnected("网络中断")
    assert view.bridge is None
    assert view.join_room()
    assert isinstance(view.bridge, FakeBridge)
    msg = view.bridge.sent[0]
    assert msg["type"] == "join" and msg["token"] == "令牌"
    assert msg["deck_code"] is None


def test_game_over_waits_for_timeline_playback(qapp, db, make_game):
    game = make_game(mulligan=True)
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.me = 0
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = cli.hand_cards_info(game, 0)
    battle.set_state(payload, timeline=[{"m": "最后结算"}])
    battle.show_game_over(None, "player_left")
    assert battle.timeline_queue
    assert battle.result_banner.isHidden()
    while battle.timeline_queue:
        battle.play_next_timeline()
    assert not battle.result_banner.isHidden()
    assert "player_left" in battle.result_banner.text()
    battle.close()


def test_online_card_detail_uses_payload_runtime_without_recalculation(
        qapp, db, make_game, monkeypatch):
    game = make_game(mulligan=True)
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.timeline_timer.setInterval(0)
    battle.me = 0
    payload = game.state.model_dump(mode="json")
    card = game.state.players[0].hand[0]
    payload["hand_info"] = {
        str(card.uid): {"cost": 0, "stats": "联机运行时唯一标记", "keywords": [],
                        "enhance": 0, "quest": None, "playable": True, "usage": []},
    }
    battle.set_state(payload, log=[], timeline=[])
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    battle.show_card_detail(battle.game.state.players[0].hand[0])
    assert seen["dialog"].runtime_label.text().find("联机运行时唯一标记") >= 0
    battle.close()


def test_online_missing_hand_info_never_falls_back_to_local_calculation(
        qapp, db, make_game, monkeypatch):
    game = make_game(mulligan=True)
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.timeline_timer.setInterval(0)
    battle.me = 0
    battle.set_state(game.state.model_dump(mode="json"), log=[], timeline=[])
    assert battle.hand_info() == {}
    seen = {}

    def capture_exec(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_exec)
    battle.show_card_detail(battle.game.state.players[0].hand[0])
    assert not hasattr(seen["dialog"], "runtime_label")
    battle.close()


@pytest.fixture(autouse=True)
def isolated_cardart_home(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))


def test_online_scene_card_art_uses_payload_render(qapp, db, make_game, monkeypatch):
    from client.gui import battle_scene

    game = make_game(mulligan=True)
    card = game.state.players[0].hand[0]
    render = {"power+": 4, "shield+": 2}
    runtime = {"cost": 1, "stats": "", "keywords": [], "render": render,
               "enhance": 0, "quest": None, "playable": True, "usage": []}
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = {str(card.uid): runtime}
    calls = []

    def capture_pixmap(cdef, database, *, display=None, level_color=None, cache_context=None):
        calls.append((cdef, display, level_color))
        return None

    monkeypatch.setattr(battle_scene, "card_pixmap", capture_pixmap)
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.me = 0
    battle.set_state(payload, log=[], timeline=[])
    assert (db.cards[card.id], render, "red") in calls
    battle.close()


def test_online_hand_art_keeps_payload_runtime_separate(
        qapp, db, make_game, tmp_path, monkeypatch):
    from client.gui import cardart
    from client.gui.widgets import CardWidget
    from tests.test_gui_builder import _cardart_config

    game = make_game(mulligan=True)
    card = game.state.players[0].hand[0]
    cdef = db.cards[card.id]
    library_dir = tmp_path / "library"
    _cardart_config(library_dir, cdef.id, cdef.version, "#336699")
    monkeypatch.setattr(cardart, "library_root", lambda: library_dir)
    cardart.clear_cardart_caches()
    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    battle.me = 0
    runtime = {"cost": 0, "stats": "联机卡图运行时唯一标记", "keywords": [],
               "enhance": 0, "quest": None, "playable": True, "usage": []}
    payload = game.state.model_dump(mode="json")
    payload["hand_info"] = {str(card.uid): runtime}
    try:
        battle.set_state(payload, log=[], timeline=[])
        item = battle.battle_scene.cards[("hand", card.uid)]
        assert item.pixmap is not None and not item.pixmap.isNull()
        assert item.cdef is cdef and item.payload.uid == card.uid
        assert battle.hand_info() == {card.uid: runtime}

        seen = {}

        def capture_exec(dialog):
            seen["dialog"] = dialog
            return QDialog.Rejected

        monkeypatch.setattr(QDialog, "exec", capture_exec)
        battle.show_card_detail(card)
        dialog = seen["dialog"]
        assert "联机卡图运行时唯一标记" in dialog.runtime_label.text()
        assert not dialog.findChild(CardWidget).art_label.pixmap().isNull()
        assert cdef.text != runtime["stats"]
        dialog.close()
    finally:
        battle.close()
        cardart.clear_cardart_caches()
