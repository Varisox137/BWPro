"""桌面 GUI 本地热坐对战测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel

from client.gui.app import THEMES, MainWindow
from client.gui.battle import DeckSelectDialog, HotseatView
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
        frame = next(frame for frame in view.hand_frames if frame.card.uid == card.uid)
        assert not frame.art_label.pixmap().isNull()
        assert frame.name_label.isHidden()
        assert not frame.info_label.isHidden()
        assert "手牌运行时唯一标记" in frame.info_label.text()

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
    assert len(view.player_frames) == 2
    assert len(view.shiki_frames) == 8


def test_perspective_reuses_slots_and_continuous_ellipse(qapp, view):
    start(view, mulligan=False)
    assert not hasattr(view, "seat_label")
    assert len(view.player_frames) == 2 and len(view.shiki_frames) == 8
    assert all(not frame.name_label.text().startswith(("1.", "2.", "3.", "4."))
               for frame in view.shiki_frames.values())
    slots = dict(view.shiki_frames)
    refs = {key: frame.ref for key, frame in slots.items()}
    assert view.top_row.isAncestorOf(view.player_frames[1])
    assert view.bottom_row.isAncestorOf(view.player_frames[0])
    arc = (36, 0, 0, 36)
    assert [view.shiki_frames[(0, index)].parentWidget().layout().contentsMargins().top()
            for index in range(4)] == list(arc)
    assert [view.shiki_frames[(1, index)].parentWidget().layout().contentsMargins().bottom()
            for index in range(4)] == list(arc)
    assert view.top_row.layout().spacing() <= 6
    view.apply_theme("light", THEMES["light"])
    assert "background: transparent; border: none;" in view.styleSheet()
    assert "QLabel#enemyHandBack, QLabel#deckCount" in view.styleSheet()

    view.game.state.active = 1
    view.refresh()
    settle(view)
    assert view.shiki_frames == slots
    assert {key: frame.ref for key, frame in view.shiki_frames.items()} == refs
    assert view.top_row.isAncestorOf(view.player_frames[0])
    assert view.bottom_row.isAncestorOf(view.player_frames[1])


def test_preparation_slots_are_narrow_fixed_width_and_centered(qapp, view):
    start(view, mulligan=False)
    for frame in view.shiki_frames.values():
        assert frame.minimumWidth() == frame.maximumWidth()
        assert frame.maximumWidth() < 180
    for row in (view.top_row, view.bottom_row):
        layout = row.layout()
        assert layout.itemAt(1).spacerItem() is not None
        assert layout.itemAt(layout.count() - 1).spacerItem() is not None


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


def test_hand_art_thumbnail_keeps_actions_visible_at_1600x900(
        qapp, db, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QScrollArea
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

        scroll = view.battle_page.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.verticalScrollBar().maximum() == 0
        viewport_bottom = scroll.viewport().mapToGlobal(
            scroll.viewport().rect().bottomLeft()).y()
        for frame in view.hand_frames:
            for button in (frame.play_button, frame.detail_button, frame.mulligan_button):
                if button.isVisibleTo(frame):
                    button_bottom = button.mapToGlobal(button.rect().bottomLeft()).y()
                    assert button_bottom <= viewport_bottom
        assert win.height() <= 900 and win.minimumSizeHint().height() <= 900
        assert view.combat_zone.width() == 320 and view.combat_zone.height() == 224
        assert view.combat_zone.isVisibleTo(win)
    finally:
        win.close()
        cardart.clear_cardart_caches()


def test_shiki_name_and_level_wrap_instead_of_clipping(qapp, view):
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    label = view.shiki_frames[(0, 0)].name_label
    assert label.wordWrap()
    assert label.text().endswith("Lv.1")
    assert label.height() >= label.minimumSizeHint().height()


def test_combat_zone_reuses_frames_and_returns_them_to_preparation(qapp, view):
    start(view, mulligan=False)
    slots = dict(view.shiki_frames)
    assert view.combat_zone.minimumWidth() == view.combat_zone.maximumWidth()
    assert view.combat_zone.maximumWidth() < 400
    assert view.combat_zone.minimumHeight() == view.combat_zone.maximumHeight()
    assert 220 <= view.combat_zone.maximumHeight() <= 260
    view.assault(0)
    settle(view)
    combatant = view.shiki_frames[(0, 0)]
    assert combatant is slots[(0, 0)]
    assert combatant.parentWidget() is view._combat_cells["bottom"].parentWidget()
    assert view.shiki_frames[(0, 1)].parentWidget() is view._slot_cells["bottom"][1].parentWidget()
    view.game.state.players[0].combat_index = None
    view.refresh()
    assert view.shiki_frames[(0, 0)] is combatant
    assert combatant.parentWidget() is view._slot_cells["bottom"][0].parentWidget()


def test_right_sidebar_shows_public_counts_and_round_end_turn(qapp, view):
    start(view, mulligan=False)
    outer = view.battle_page.layout()
    assert outer.itemAt(outer.count() - 1).widget() is view.right_sidebar
    sidebar = view.right_sidebar.layout()
    assert sidebar.itemAt(0).widget() is view.enemy_hand_label
    assert sidebar.itemAt(1).widget() is view.enemy_deck_label
    assert sidebar.itemAt(3).widget() is view.end_turn_button
    assert sidebar.itemAt(5).widget() is view.own_deck_label
    assert view.end_turn_button.parentWidget() is view.right_sidebar
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
    frame = view.shiki_frames[(0, 0)]
    assert frame.name_label.text() == f"{db.shikigami[shiki.id].name}　Lv.{shiki.level}"
    assert frame.stats_label.text() == (
        f"力量 {shiki.eff_power}　生命 {shiki.health}/{shiki.max_health}")
    assert frame.status_label.text() == "护甲/破甲 4　倒计时 2"
    normal_text = (frame.name_label.text() + frame.stats_label.text()
                   + frame.status_label.text())
    assert all(text not in normal_text for text in ("能量", "形态", "贯通", "灵咒"))


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
    text = seen["dialog"].findChild(QLabel).text()
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

    normal = view.shiki_frames[(0, 0)]
    normal_text = (normal.name_label.text() + normal.stats_label.text()
                   + normal.status_label.text())
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
        seen.append(dialog.findChild(QLabel).text())
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


def test_log_button_is_vertically_centered_in_left_sidebar(qapp, view):
    outer = view.battle_page.layout()
    assert outer.itemAt(0).widget() is view.log_sidebar
    assert view.log_button.parentWidget() is view.log_sidebar
    sidebar = view.log_sidebar.layout()
    assert sidebar.count() == 3
    assert sidebar.itemAt(0).spacerItem() is not None
    assert sidebar.itemAt(1).widget() is view.log_button
    assert sidebar.itemAt(2).spacerItem() is not None


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


def test_viewer_handoff_freezes_commands_hands_choices_and_timeline(qapp, view):
    start(view, mulligan=False)
    assert not view._handoff_pending
    view.refresh()
    assert not view._handoff_pending
    assert view.bottom_row.isAncestorOf(view.player_frames[0])

    old_hand_frames = list(view.hand_frames)
    assert old_hand_frames
    assert view.end_turn()
    assert view._handoff_pending
    assert all(frame.isHidden() for frame in old_hand_frames)
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
    assert not view.hand_frames
    assert view.choice_dialog is None
    assert view.bottom_row.isAncestorOf(view.player_frames[0])
    before = list(view.timeline_queue)
    assert before
    assert not view.apply_command({"op": "end_turn"})
    view.play_next_timeline()
    assert view.timeline_queue == before

    confirm.click()
    assert not view._handoff_pending
    assert view.handoff_dialog is None
    assert dialog.isHidden()
    assert view.bottom_row.isAncestorOf(view.player_frames[1])
    assert view.hand_frames
    assert view.timeline_queue == before
    settle(view)


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
    assert not view.hand_frames

    view.confirm_handoff()
    assert view.choice_dialog is not None
    assert not view.choice_dialog.isHidden()
    assert view.answer_pending(game.state.pending_choice["options"][0])
    assert game.state.pending_choice is None
    assert view.viewer == 0
    assert view._handoff_pending
    assert view.choice_dialog is None
    assert not view.hand_frames
    view.confirm_handoff()
    assert view.hand_frames
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
