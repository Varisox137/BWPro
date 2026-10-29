"""桌面 GUI 卡组构筑测试（QT_QPA_PLATFORM=offscreen）。"""
import os
from types import SimpleNamespace

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QMessageBox, QPushButton

from client.gui import portrait
from client.gui.app import THEMES, MainWindow
from client.gui.builder import DeckBuilderView, DeckCodeDialog, ShikigamiDialog
from db import deckcode, deckstore
from tests import factories


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture
def view(qapp, db, tmp_path):
    widget = DeckBuilderView(db, store_path=tmp_path / "decks.json")
    yield widget
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def legal_groups(db):
    return deckcode.group_deck(db, factories.TEAM, factories.deck_of(*factories.TEAM))


def test_builder_page_navigation(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.go("builder")
    assert isinstance(win.pages["builder"], DeckBuilderView)
    win.back_button.click()
    assert win.stack.currentIndex() == 0
    win.toggle_theme()
    assert win.pages["builder"].theme == "dark"
    win.close()


def test_store_round_trip_and_standard_style(qapp, db, tmp_path, view):
    store = tmp_path / "decks.json"
    deckstore.save_decks(db, [{"name": "主力", "groups": legal_groups(db), "env": None}], store)
    view.reload_decks()
    assert view.decks[0]["standard"] is True
    assert view.deck_frames[0].property("standard") is True
    assert view.export_code(0) == deckcode.encode_deck(legal_groups(db))

    reloaded = DeckBuilderView(db, store_path=store)
    assert reloaded.decks[0]["name"] == "主力"
    assert reloaded.decks[0]["groups"] == [list(group) for group in legal_groups(db)]
    reloaded.close()


def test_new_edit_save_rename_delete_flow(qapp, db, view):
    view.new_deck()
    view.name_edit.setText("测试卡组")
    for sid in factories.TEAM:
        view.add_shikigami(sid)
    for sid in factories.TEAM:
        view.select_shikigami(sid)
        for cid in factories.deck_of(sid):
            view.change_card(cid, 1)
    assert view.save_editor() is True
    assert len(view.decks) == 1
    assert view.decks[0]["standard"] is True
    assert view.store_path.exists()

    view.edit_deck(0)
    first = factories.TEAM[0] * 100 + 1
    view.change_card(first, -1)
    assert view.save_editor() is True
    assert view.decks[0]["standard"] is False
    assert view.deck_frames[0].property("standard") is False

    view.rename_deck(0, "新名称")
    assert view.decks[0]["name"] == "新名称"
    assert deckstore.load_decks(db, view.store_path)[0]["name"] == "新名称"
    view.delete_deck(0, confirmed=True)
    assert view.decks == []
    assert deckstore.load_decks(db, view.store_path) == []


def test_card_page_has_five_and_reinforce_is_last(qapp, db, view):
    sid = factories.TEAM[0]
    reinforce = factories.card(10010221, shikigami=factories.TEAM[1], name="协战",
                               card_type="reinforce", shikigami2=sid)
    db.cards[reinforce.id] = reinforce
    view.new_deck()
    view.add_shikigami(sid)
    view.select_shikigami(sid)
    assert view.page_count == 2
    assert len(view.card_widgets) == 5
    assert view.card_widgets[0].cdef.id == sid
    assert view.card_widgets[0].plus_button is None
    assert view.card_widgets[0].count_label.text().strip() == ""
    assert [w.cdef.id for w in view.card_widgets[1:]] == list(range(sid * 100 + 1, sid * 100 + 5))
    view.next_card_page()
    assert len(view.card_widgets) == 5
    assert view.card_widgets[-1].cdef.id == reinforce.id
    view.next_card_page()
    assert view.page_index == 1
    view.previous_card_page()
    assert view.page_index == 0


def test_shikigami_replacement_clears_cards(qapp, db, view):
    view.new_deck()
    old, new = factories.TEAM[:2]
    view.add_shikigami(old)
    cid = old * 100 + 1
    view.change_card(cid, 1)
    view.replace_shikigami(0, new)
    assert view.team == [new]
    assert view.picks.get(old, {}) == {}
    assert view.picks.get(new, {}) == {}


def test_deck_code_import_export(qapp, db, view):
    code = deckcode.encode_deck(legal_groups(db))
    view.import_code(code, name="导入")
    assert view.decks[0]["name"] == "导入"
    assert view.export_code(0) == code
    with pytest.raises(ValueError):
        view.import_code("不是卡组码")
    assert len(view.decks) == 1


def test_deck_frame_full_actions_and_portraits(qapp, db, tmp_path, view):
    long_name = "一个很长的卡组名称" * 8
    deckstore.save_decks(db, [{"name": long_name, "groups": legal_groups(db), "env": None}],
                         tmp_path / "decks.json")
    view.resize(1200, 800)
    view.show()
    view.reload_decks()
    qapp.processEvents()
    frame = view.deck_frames[0]
    assert frame.maximumWidth() <= 300
    deck_name = frame.findChild(QLabel, "cardName")
    two_lines = deck_name.fontMetrics().lineSpacing() * 2
    required_height = deck_name.heightForWidth(deck_name.width())
    assert deck_name.minimumHeight() == two_lines
    assert required_height > two_lines
    assert deck_name.height() == two_lines
    assert deck_name.alignment() & Qt.AlignTop
    assert [label.text() for label in frame.findChildren(QLabel, "deckShikiName")] == [
        db.shikigami[sid].name for sid in factories.TEAM]
    portraits = frame.findChildren(QLabel, "shikiPortrait")
    assert len(portraits) == 4
    assert all(label.width() == label.height() == 96 for label in portraits)
    assert all(not label.pixmap().isNull() for label in portraits)
    texts = [button.text() for button in frame.findChildren(QPushButton)]
    assert all(text in texts for text in ("编辑", "查看卡组码", "重命名", "删除"))


def test_deck_short_name_reserves_second_line(qapp, db, tmp_path, view):
    deckstore.save_decks(db, [{"name": "短名", "groups": legal_groups(db), "env": None}],
                         tmp_path / "decks.json")
    view.resize(1200, 800)
    view.show()
    view.reload_decks()
    qapp.processEvents()
    deck_name = view.deck_frames[0].findChild(QLabel, "cardName")
    two_lines = deck_name.fontMetrics().lineSpacing() * 2
    assert deck_name.height() == two_lines
    assert deck_name.alignment() & Qt.AlignTop


def test_environment_options_are_unique(qapp, view):
    view.new_deck()
    texts = [view.env_combo.itemText(i) for i in range(view.env_combo.count())]
    dates = [view.env_combo.itemData(i) for i in range(view.env_combo.count())]
    assert len(texts) == len(set(texts))
    assert len(dates) == len(set(dates))


def test_invalid_environment_restores_last_valid_value(qapp, view, monkeypatch):
    warnings = []
    monkeypatch.setattr("client.gui.builder.show_warning",
                        lambda _parent, title, text: warnings.append((title, text)))
    view.new_deck()
    view._set_env(20260720)
    view.env_combo.setEditText("not-a-date")
    view.change_environment()
    assert view.current_env() == 20260720
    assert "20260720" in view.env_combo.currentText()
    assert warnings
    assert view.add_shikigami(factories.TEAM[0])


def test_editor_detail_uses_current_environment_database(qapp, view, monkeypatch):
    seen = {}

    class Detail:
        def __init__(self, _cdef, db, _parent):
            seen["db"] = db

        def exec(self):
            return 0

    monkeypatch.setattr("client.gui.builder.CardDetailDialog", Detail)
    view.new_deck()
    view._set_env(20260720)
    view.add_shikigami(factories.TEAM[0])
    view.show_card_detail(view._current_cards()[0])
    assert seen["db"] is not view.db
    assert seen["db"].shikigami[factories.TEAM[0]].version == 20260720


def test_cancel_add_restores_shikigami_selection(qapp, view, monkeypatch):
    view.new_deck()
    view.add_shikigami(factories.TEAM[0])
    monkeypatch.setattr("client.gui.builder.ShikigamiDialog.exec", lambda _self: 0)
    view.shiki_list.setCurrentRow(len(view.team))
    assert view.shiki_list.currentRow() == 0
    assert view.selected_sid == factories.TEAM[0]


def test_editor_loading_feedback_runs_during_card_render(qapp, db, view, monkeypatch):
    view.import_code(deckcode.encode_deck(legal_groups(db)))
    assert hasattr(view, "loading_label")
    events = []
    original_start = view._start_loading
    original_tick = view._loading_tick
    original_finish = view._finish_loading
    monkeypatch.setattr(view, "_start_loading",
                        lambda *args: events.append("start") or original_start(*args))
    monkeypatch.setattr(view, "_loading_tick", lambda: events.append("tick") or original_tick())
    monkeypatch.setattr(view, "_finish_loading", lambda: events.append("finish") or original_finish())
    view.edit_deck(0)
    assert events[0] == "start" and events[-1] == "finish"
    assert events.count("tick") >= 5
    assert view.loading_label.isHidden()


def test_open_deck_goes_straight_to_editor(qapp, db, view, monkeypatch):
    view.import_code(deckcode.encode_deck(legal_groups(db)))

    def unexpected_exec(_dialog):
        raise AssertionError("编辑前不应再弹卡组码")

    monkeypatch.setattr("client.gui.builder.DeckCodeDialog.exec", unexpected_exec)
    view.open_deck(0)
    assert view.stack.currentWidget() is view.editor_page


def test_shikigami_picker_name_column_is_wide(qapp, db):
    picker = ShikigamiDialog(db)
    assert picker.tree.headerItem().text(0) == "式神名"
    assert picker.tree.columnWidth(0) >= 300
    assert picker.tree.indentation() <= 12
    picker.close()


def test_editor_card_has_no_outer_frame_and_aligned_stepper(qapp, view):
    view.apply_theme("light", THEMES["light"])
    view.new_deck()
    view.add_shikigami(factories.TEAM[0])
    view.resize(1400, 800)
    view.show()
    qapp.processEvents()
    base, widget = view.card_widgets[:2]
    assert "QFrame#card { background: transparent; border: none; }" in view.styleSheet()
    footer = widget.layout().itemAt(widget.layout().count() - 1).layout()
    assert footer.itemAt(1).widget() is widget.minus_button
    assert footer.itemAt(3).widget() is widget.count_label
    assert footer.itemAt(5).widget() is widget.plus_button
    assert widget.count_label.alignment() & Qt.AlignHCenter
    assert base.art_label.height() == widget.art_label.height()


def test_editor_five_cards_fit_1200px_window_with_aligned_counts(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.resize(1200, 800)
    win.go("builder")
    page = win.pages["builder"]
    page.new_deck()
    page.add_shikigami(factories.TEAM[0])
    win.show()
    qapp.processEvents()
    assert win.width() == 1200
    assert len(page.card_widgets) == 5
    assert page.shiki_list.width() <= 180
    area = page.card_area
    assert all(widget.x() >= 0 and widget.x() + widget.width() <= area.width()
               for widget in page.card_widgets)
    assert all(widget.minimumWidth() == 0 for widget in page.card_widgets)
    widths = [widget.width() for widget in page.card_widgets]
    assert max(widths) - min(widths) <= 1
    margins = area.layout().contentsMargins()
    assert page.card_widgets[0].x() == margins.left()
    assert page.card_widgets[-1].x() + page.card_widgets[-1].width() == (
        area.width() - margins.right())
    for widget in page.card_widgets:
        pixmap = widget.art_label.pixmap()
        assert not pixmap.isNull()
        assert pixmap.width() <= widget.art_label.width() + 1
        assert pixmap.height() <= widget.art_label.height() + 1
    margins = win.centralWidget().layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (12, 12, 12, 12)
    row = page.shiki_list.itemWidget(page.shiki_list.item(0))
    assert row is not None
    count = row.findChildren(QLabel)[-1]
    assert count.text().endswith("/8") and count.alignment() & Qt.AlignRight
    page.dirty = False
    win.close()


def test_editor_card_batch_checks_art_resources_once(qapp, view, monkeypatch):
    from client.gui import cardart

    original_digest = cardart._renderer_resource_digest
    original_fingerprint = cardart._card_config_fingerprint
    digest_calls = []
    fingerprint_calls = []

    def counted_digest(*args):
        digest_calls.append(args)
        return original_digest(*args)

    def counted_fingerprint(*args):
        fingerprint_calls.append(args)
        return original_fingerprint(*args)

    monkeypatch.setattr(cardart, "_renderer_resource_digest", counted_digest)
    monkeypatch.setattr(cardart, "_card_config_fingerprint", counted_fingerprint)
    view.new_deck()
    view.add_shikigami(factories.TEAM[0])
    assert len(view.card_widgets) == 5
    assert len(digest_calls) == 1
    assert len(fingerprint_calls) == 1


def test_builder_leave_discard_and_reenter_returns_list(qapp, db, tmp_path, monkeypatch):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.go("builder")
    page = win.pages["builder"]
    page.new_deck()
    page.add_shikigami(factories.TEAM[0])
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Cancel)
    win.back()
    assert page.stack.currentWidget() is page.editor_page
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Discard)
    win.back()
    assert win.stack.currentIndex() == 0
    win.go("builder")
    assert page.stack.currentWidget() is page.list_page
    win.close()


def test_builder_close_event_also_protects_unsaved_changes(qapp, db, tmp_path, monkeypatch):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.go("builder")
    page = win.pages["builder"]
    page.new_deck()
    page.add_shikigami(factories.TEAM[0])
    win.show()
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Cancel)
    win.close()
    assert win.isVisible()
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Discard)
    win.close()
    assert not win.isVisible()


def test_dialog_standard_buttons_are_chinese_and_compact(qapp, db, view):
    from PySide6.QtWidgets import QStyle, QStyleOptionButton
    from client.gui.app import qss
    from client.gui.widgets import polish_dialog_buttons

    def assert_text_fits(button):
        option = QStyleOptionButton()
        button.initStyleOption(option)
        contents = button.style().subElementRect(QStyle.SE_PushButtonContents, option, button)
        assert contents.width() >= button.fontMetrics().horizontalAdvance(button.text())
        assert contents.height() > 0

    view.setStyleSheet(qss("light"))
    dialog = DeckCodeDialog(editable=True, parent=view)
    box = dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.Ok).text() == "确定"
    assert box.button(QDialogButtonBox.Cancel).text() == "取消"
    assert all(button.objectName() == "dialogButton" for button in box.buttons())
    for standard in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
        assert box.button(standard).size().width() == 76
        assert box.button(standard).size().height() == 30
    dialog.show()
    qapp.processEvents()
    for button in box.buttons():
        assert_text_fits(button)
    dialog.close()

    message = QMessageBox(view)
    message.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
    polish_dialog_buttons(message)
    message.show()
    qapp.processEvents()
    for button in message.buttons():
        assert button.size().width() == 76 and button.size().height() == 30
        assert_text_fits(button)
    message.close()
    picker = ShikigamiDialog(db, parent=view)
    picker_box = picker.findChild(QDialogButtonBox)
    assert picker_box.button(QDialogButtonBox.Ok).text() == "确定"
    assert picker_box.button(QDialogButtonBox.Cancel).text() == "取消"
    picker.close()


def test_rename_dialog_buttons_are_chinese(qapp, db, view, monkeypatch):
    view.import_code(deckcode.encode_deck(legal_groups(db)))
    seen = {}

    def fake_exec(dialog):
        box = dialog.findChild(QDialogButtonBox)
        seen["buttons"] = None if box is None else [button.text() for button in box.buttons()]
        return 0

    monkeypatch.setattr("client.gui.builder.QInputDialog.exec", fake_exec)
    view.ask_rename(0)
    assert seen["buttons"] == ["确定", "取消"]


def _external_library(root, yaml_text: str):
    shiki_dir = root / "library" / "项目" / "shikigami"
    images_dir = root / "library" / "项目" / "images"
    shiki_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    (shiki_dir / "test.yaml").write_text(yaml_text, encoding="utf-8")
    image_path = images_dir / "art.png"
    Image.new("RGBA", (2, 2), "#336699").save(image_path)
    return image_path


def test_entity_pixmap_uses_shikigami_art_config(qapp, tmp_path):
    from client.gui import cardart

    _external_library(
        tmp_path,
        "id: 100101\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n",
    )
    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=0, eff_power=3,
                            combat_power=0, health=4, shield=0, ext={})
    first = cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "library")
    empty = cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "empty")
    assert first is not None and empty is not None
    assert first.toImage() != empty.toImage()


def test_shikigami_card_art_uses_shikigami_config(qapp, tmp_path):
    from client.gui import cardart

    _external_library(
        tmp_path,
        "id: 100101\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n",
    )
    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    first = cardart.card_pixmap(definition, database, library_dir=tmp_path / "library")
    empty = cardart.card_pixmap(definition, database, library_dir=tmp_path / "empty")
    assert first is not None and empty is not None
    assert first.toImage() != empty.toImage()


def test_entity_art_scales_up_to_cover_window(qapp, tmp_path):
    from client.gui import cardart

    _external_library(
        tmp_path,
        "id: 100101\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n      scale: 0.5\n      offset_y: -20\n",
    )
    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=0, eff_power=3,
                            combat_power=0, health=4, shield=0, ext={})
    pixmap = cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "library")
    assert pixmap is not None
    image = pixmap.toImage()
    for point in ((48, 20), (48, 110)):
        assert image.pixelColor(*point).green() > 70


def test_entity_power_zero_does_not_subtract_combat_power(qapp, tmp_path, monkeypatch):
    import json
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=0, eff_power=0,
                            combat_power=3, health=4, shield=0, ext={"power_zero": True})
    seen = {}
    monkeypatch.setattr(cardart, "_cached_entity_pixmap",
                        lambda _key, _payload, state, _layout, _root:
                        seen.update(json.loads(state)))
    cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "empty")
    assert seen["level"] == 0
    assert seen["power"] == 0
    assert seen["combat_power"] == 3


def test_entity_stat_colors_follow_base_permanent_reference(qapp, tmp_path, monkeypatch):
    import json
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    seen = {}
    monkeypatch.setattr(cardart, "_cached_entity_pixmap",
                        lambda _key, _payload, state, _layout, _root:
                        seen.update(json.loads(state)))

    def render(**values):
        defaults = dict(id=100101, awakened=None, level=1, defeated=False,
                        perm_power=0, perm_health=0, eff_power=3, combat_power=0,
                        health=4, max_health=4, shield=2, ext={})
        defaults.update(values)
        cardart.entity_pixmap(SimpleNamespace(**defaults), database,
                              library_dir=tmp_path / "empty")
        return dict(seen)

    for eff_power, expected in ((2, "red"), (3, None), (4, "green")):
        state = render(eff_power=eff_power)
        assert state["power_color"] == expected
        assert state["combat_power_color"] is None
        assert state["shield_color"] is None
    for health, max_health, perm_health, expected in (
            (3, 4, 0, "red"), (4, 4, 0, None),
            (5, 5, 0, "green"), (5, 5, 1, None), (3, 3, 0, None)):
        state = render(health=health, max_health=max_health, perm_health=perm_health)
        assert state["health_color"] == expected
    state = render(defeated=True, perm_power=1, perm_health=2,
                   eff_power=9, health=0, max_health=0)
    assert state["power_color"] is None
    assert state["health_color"] is None


def test_defeated_entity_uses_base_permanent_stats_and_grayscale_art(qapp, tmp_path, monkeypatch):
    import json
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(
        id=100101, awakened=None, level=0, defeated=True, perm_power=2, perm_health=3,
        eff_power=9, combat_power=4, health=0, shield=0, ext={})
    seen = {}
    monkeypatch.setattr(
        cardart, "_cached_entity_pixmap",
        lambda _key, payload, state, _layout, _root: seen.update(
            payload=json.loads(payload), state=json.loads(state)))
    cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "empty")
    assert seen["state"]["power"] == 5
    assert seen["state"]["health"] == 7
    assert seen["state"]["combat_power"] == 0
    assert seen["payload"]["_defeated"] is True
    artwork = Image.new("RGBA", (2, 2), (180, 40, 20, 127))
    gray = cardart._grayscale_artwork(artwork)
    red, green, blue, alpha = gray.getpixel((0, 0))
    assert red == green == blue and alpha == 127
    assert red > 40


def test_entity_pixmap_renders_combat_power_and_shield(qapp, tmp_path):
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    base = SimpleNamespace(id=100101, awakened=None, level=1, eff_power=3,
                           combat_power=0, health=4, shield=0, ext={})
    buffed = SimpleNamespace(id=100101, awakened=None, level=1, eff_power=6,
                             combat_power=3, health=4, shield=2, ext={})
    normal = cardart.entity_pixmap(base, database, library_dir=tmp_path / "empty")
    combat = cardart.entity_pixmap(buffed, database, library_dir=tmp_path / "empty")
    assert normal is not None and combat is not None
    assert normal.toImage() != combat.toImage()


def test_portrait_library_success_uses_renderer(qapp, tmp_path, monkeypatch):
    image_path = _external_library(
        tmp_path,
        "id: 987654\nname: 测试\nfaction_style: 3\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n"
        "portrait:\n  offset_x: 3\n  scale: 2\n  rotate: 0\n",
    )
    seen = {}

    class Library:
        def artwork(self, path, rotate=0):
            return (2, 2), Image.new("RGBA", (2, 2), "#336699")

    def render(_lib, _elem, art, faction, scale, faction_style, width=None, height=None):
        seen.update(art=art, faction=faction, scale=scale, faction_style=faction_style)
        return Image.new("RGBA", (4, 4), "#336699")

    monkeypatch.setattr(portrait, "_renderer",
                        lambda _root: (tmp_path, Library(), {"back_size": 56}, render))
    portrait._portrait_pixmap.cache_clear()
    pixmap = portrait.shikigami_portrait(
        SimpleNamespace(id=987654, name="测试", faction="苍叶", version=20260720),
        root=tmp_path, library_dir=tmp_path / "library")
    assert not pixmap.isNull()
    assert seen["art"]["path"] == str(image_path.resolve())
    assert seen["art"]["offset_x"] == 3 and seen["art"]["scale"] == 2
    assert seen["faction"] == "苍叶" and seen["faction_style"] == 3
    portrait._portrait_pixmap.cache_clear()


def test_portrait_external_data_resource_limits(qapp, tmp_path):
    image_path = _external_library(
        tmp_path / "clamp",
        "id: 987653\nname: 限幅\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n"
        "portrait:\n  offset_x: .inf\n  scale: 1000000\n  rotate: .nan\n",
    )
    ref, _style = portrait._artwork_ref(
        tmp_path / "clamp" / "library", 987653, "限幅", 20260720)
    assert ref["path"] == str(image_path.resolve())
    assert ref["scale"] == 16
    assert ref["offset_x"] == 0 and ref["rotate"] == 0

    oversized = tmp_path / "oversized"
    _external_library(
        oversized,
        "id: 987652\nname: 超大\nartwork:\n  images:\n    - path: art.png\n# "
        + "x" * (256 * 1024),
    )
    assert portrait._artwork_ref(oversized / "library", 987652, "超大") == (None, None)

    nonmapping = tmp_path / "nonmapping"
    _external_library(nonmapping, "- 不是映射\n")
    assert portrait._artwork_ref(nonmapping / "library", 987651, "任意") == (None, None)

    traversal = tmp_path / "traversal"
    _external_library(
        traversal,
        "id: 987650\nname: 越界\nartwork:\n  images:\n    - path: ../outside.png\n",
    )
    assert portrait._artwork_ref(traversal / "library", 987650, "越界") == (None, None)

    assert hasattr(portrait, "_preflight_artwork")

    class HugeLibrary:
        def artwork(self, _path, _rotate=0):
            image = SimpleNamespace(width=100000, height=100000)
            return (100, 100), image

    with pytest.raises(ValueError, match="像素"):
        portrait._preflight_artwork(
            HugeLibrary(), {"back_size": 56},
            {"path": "unused", "scale": 16, "rotate": 0},
        )


def _cardart_config(library_dir, cid, version_date, color, **extra):
    import yaml

    cards_dir = library_dir / "项目" / "cards"
    images_dir = library_dir / "项目" / "images"
    cards_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{cid}-{version_date}.png"
    Image.new("RGBA", (8, 8), color).save(images_dir / image_name)
    data = {
        "id": str(cid), "name": "配置旧名", "type": "法术", "level": 1,
        "rarity": "R", "description": "配置旧文本", "version_date": str(version_date),
        "artwork": {"images": [{"path": image_name}]}, **extra,
    }
    (cards_dir / f"{cid}@{version_date}.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_cardart_home(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))


def test_builder_shared_card_art_and_frame_fallback(qapp, db, view, tmp_path, monkeypatch):
    from client.gui import cardart
    from client.gui.widgets import CardWidget

    cdef = db.cards[10010101]
    library_dir = tmp_path / "library"
    _cardart_config(library_dir, cdef.id, cdef.version, "#336699")
    monkeypatch.setattr(cardart, "library_root", lambda: library_dir)
    cardart.clear_cardart_caches()
    try:
        view.new_deck()
        view.add_shikigami(cdef.shikigami)
        widget = view.card_widgets[1]
        assert not widget.art_label.pixmap().isNull()
        assert all(label.isHidden() for label in (
            widget.name_label, widget.level_label, widget.type_label,
            widget.stats_label, widget.text_label,
        ))
        assert not widget.count_label.isHidden()
        assert not widget.minus_button.isHidden() and not widget.plus_button.isHidden()

        fallback = view.card_widgets[1]
        assert not fallback.art_label.pixmap().isNull()
        assert all(label.isHidden() for label in (
            fallback.name_label, fallback.level_label, fallback.type_label,
            fallback.stats_label, fallback.text_label,
        ))
        legacy = CardWidget(cdef, 2, True)
        assert legacy.copies == 2 and legacy.plus_button is not None
        assert legacy.art_label.isHidden() and not legacy.name_label.isHidden()
        legacy.close()
    finally:
        cardart.clear_cardart_caches()


def _require_real_cardart_resources():
    from client.gui import cardart

    renderer_root = portrait.bwpdiy_root()
    library_dir = cardart.library_root()
    required = (
        renderer_root / "bwpdiy" / "render",
        renderer_root / "assets" / "frames",
        renderer_root / "assets" / "fonts",
        library_dir / "经典" / "cards" / "起弓.yaml",
        library_dir / "经典" / "cards" / "尘刀.yaml",
        library_dir / "经典" / "shikigami" / "白狼.yaml",
        library_dir / "经典" / "shikigami" / "兵俑.yaml",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        pytest.skip(f"真实卡图集成资源缺失：{missing}")
    return renderer_root, library_dir


def test_cardart_library_root_and_default_project_portrait(qapp, gdb, tmp_path, monkeypatch):
    from pathlib import Path
    from PySide6.QtGui import QPixmap
    from client.gui import cardart

    monkeypatch.delenv("BWP_DIY_LIBRARY", raising=False)
    expected_root = Path(cardart.__file__).resolve().parents[2] / "library"
    assert cardart.library_root() == expected_root
    monkeypatch.setenv("BWP_DIY_LIBRARY", "D:/临时卡图库")
    assert cardart.library_root() == Path("D:/临时卡图库")
    monkeypatch.delenv("BWP_DIY_LIBRARY")

    _require_real_cardart_resources()
    cardart.clear_cardart_caches()
    monkeypatch.setattr(portrait, "_fallback_pixmap", lambda *_args: QPixmap())
    pixmap = portrait.shikigami_portrait(gdb.shikigami[100101])
    empty = portrait.shikigami_portrait(
        gdb.shikigami[100101], library_dir=tmp_path / "empty-library")
    assert not pixmap.isNull() and pixmap.toImage() != empty.toImage()
    cardart.clear_cardart_caches()


def test_cardart_pixmap_selects_version_and_falls_back(qapp, tmp_path):
    from client.gui import cardart

    library_dir = tmp_path / "library"
    cache_dir = tmp_path / "cache"
    cid = 10010101
    _cardart_config(library_dir, cid, 20191212, "#336699")
    _cardart_config(library_dir, cid, 20200101, "#993366")
    old = factories.card(cid, card_type="combat").model_copy(update={"version": 20191212})
    new = factories.card(cid, card_type="combat").model_copy(update={"version": 20200101})
    database = factories.db_of([factories.shiki(100101)], [old, new])

    cardart.clear_cardart_caches()
    old_pix = cardart.card_pixmap(old, database, library_dir=library_dir, cache_dir=cache_dir)
    new_pix = cardart.card_pixmap(new, database, library_dir=library_dir, cache_dir=cache_dir)
    assert old_pix is not None and not old_pix.isNull()
    assert new_pix is not None and not new_pix.isNull()
    assert old_pix.toImage() != new_pix.toImage()

    invalid = factories.card(10010102).model_copy(update={"version": 20200202})
    _cardart_config(library_dir, invalid.id, 20200230, "#336699")
    missing_image = factories.card(10010103).model_copy(update={"version": 20200202})
    _cardart_config(library_dir, missing_image.id, 20200202, "#336699",
                    artwork={"images": [{"path": "absent.png"}]})
    traversal = factories.card(10010104).model_copy(update={"version": 20200202})
    _cardart_config(library_dir, traversal.id, 20200202, "#336699",
                    artwork={"images": [{"path": "../outside.png"}]})
    cardart.clear_cardart_caches()
    missing = factories.card(10010105).model_copy(update={"version": 20200202})
    for definition in (invalid, missing_image, traversal, missing):
        pixmap = cardart.card_pixmap(definition, database, library_dir=library_dir)
        assert pixmap is not None and not pixmap.isNull()
    cardart.clear_cardart_caches()


def test_cardart_description_removes_paired_braces():
    from client.gui import cardart

    assert cardart._description("投射：{造成4点伤害}。[增强]：{若满足，此牌伤害翻倍}") == (
        "投射：造成4点伤害。[[增强]]：若满足，此牌伤害翻倍")


def test_cardart_native_height_supports_stat_layout(qapp, gdb):
    from client.gui import cardart

    cardart.clear_cardart_caches()
    pixmap = cardart.card_pixmap(gdb.cards[10010103], gdb, height=255)
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.height() == 255


def test_cardart_native_height_and_size_cache(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    original_renderer = cardart._renderer
    assets, library, original_render = original_renderer(str(portrait.bwpdiy_root().resolve()))
    heights = []

    def render(payload, assets_dir, layout=None, height=None, **kwargs):
        heights.append(height)
        return original_render(payload, assets_dir, layout=layout, height=height, **kwargs)

    monkeypatch.setattr(cardart, "_renderer", lambda _root: (assets, library, render))
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                                cache_dir=cache_dir, height=360)
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                                 cache_dir=cache_dir, height=720)
    shiki = SimpleNamespace(id=cdef.shikigami, awakened=None, level=1, faction="红莲",
                            perm_power=0, perm_health=0, eff_power=3, health=4)
    cardart.shikigami_pixmap(shiki, database, height=336)
    assert heights == [360, 720, 336]
    assert (first.height(), second.height()) == (360, 720)
    assert first.width() / first.height() == pytest.approx(second.width() / second.height(), abs=0.002)
    assert len(list(cache_dir.glob("*.png"))) == 2
    monkeypatch.setattr(cardart, "_renderer", original_renderer)
    cardart.clear_cardart_caches()


def test_entity_native_height(qapp, tmp_path, monkeypatch):
    from bwpdiy.render import entity
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=0, eff_power=3,
                            combat_power=0, health=4, shield=0, ext={})
    original = entity.render_entity
    heights = []

    def render(payload, state, assets_dir, layout=None, height=None, **kwargs):
        heights.append(height)
        return original(payload, state, assets_dir, layout=layout, height=height, **kwargs)

    monkeypatch.setattr(entity, "render_entity", render)
    pixmap = cardart.entity_pixmap(shiki, database, height=210)
    assert heights[0] == 210  # BWPDIY 内部测量调用不传 height
    assert pixmap is not None and pixmap.height() == 210


def test_entity_disk_cache_survives_memory_cache_clear(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=0, faction="红莲",
                            perm_power=0, perm_health=0, eff_power=3,
                            combat_power=0, health=4, shield=0, ext={})
    calls = []

    def render(*args):
        calls.append(args)
        return QPixmap(20, 30)

    monkeypatch.setattr(cardart, "_render_entity_pixmap", render)
    fingerprints = []
    original_fingerprint = cardart.portrait._config_fingerprint

    def track_fingerprint(root):
        fingerprints.append(root)
        return original_fingerprint(root)

    monkeypatch.setattr(cardart.portrait, "_config_fingerprint", track_fingerprint)
    cache_dir = tmp_path / "cache"
    art_context = {}
    first = cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "library",
                                  cache_dir=cache_dir, cache_context=art_context,
                                  height=210, disk_cache=True)
    cardart._cached_static_entity_pixmap.cache_clear()
    second = cardart.entity_pixmap(shiki, database, library_dir=tmp_path / "library",
                                   cache_dir=cache_dir, cache_context=art_context,
                                   height=210, disk_cache=True)
    assert len(fingerprints) == 1
    assert len(calls) == 1
    assert first.toImage() == second.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 1


def test_portrait_native_size(qapp, tmp_path, monkeypatch):
    from client.gui import portrait

    _external_library(
        tmp_path,
        "id: 100101\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n",
    )
    seen = {}

    class Library:
        def artwork(self, path, rotate=0):
            return (2, 2), Image.new("RGBA", (2, 2), "#336699")

    def render(_lib, _elem, art, faction, scale, faction_style, width=None, height=None):
        seen.update(width=width, height=height)
        return Image.new("RGBA", (96, 96), "#336699")

    monkeypatch.setattr(portrait, "_renderer",
                        lambda _root: (tmp_path, Library(), {"back_size": 56}, render))
    portrait._portrait_pixmap.cache_clear()
    pixmap = portrait.shikigami_portrait(
        SimpleNamespace(id=100101, name="测试", faction="苍叶", version=20260720),
        root=tmp_path, library_dir=tmp_path / "library")
    assert seen == {"width": 96, "height": 96}
    assert pixmap.width() == pixmap.height() == 96
    portrait._portrait_pixmap.cache_clear()


def test_cardart_engine_payload_mapping(qapp):
    from client.gui import cardart

    primary = factories.shiki(100101, name="引擎主式神", faction="红莲")
    secondary = factories.shiki(100102, name="引擎副式神")
    combat = factories.card(
        10010101, name="引擎战斗", card_type="combat", level=3, rarity="SSR",
        text="[瞬发]获得1点力量、2护甲、3破甲、4能量、5耐久、6战力、7乏力、8赏金与9生命。",
        steps=[factories.Step(op="buff_power", amount=2),
               factories.Step(op="buff_power", amount=-1),
               factories.Step(op="gain_shield", amount=3)])
    database = factories.db_of([primary, secondary], [combat])
    config = {"name": "旧名", "description": "旧文本", "level": 1, "rarity": "R",
              "power+": 99, "shield+": 99, "faction": "紫岩", "faction_style": 3}
    data = cardart._card_data(combat, database, config)
    assert data["type"] == "战斗" and data["name"] == "引擎战斗"
    assert data["level"] == 3 and data["rarity"] == "SSR"
    assert data["shikigami"] == "引擎主式神" and data["faction"] == "红莲"
    assert data["power+"] == 1 and data["shield+"] == 3
    assert data["description"] == ("[[瞬发]]获得1点#ll、2#hj、3#pj、4#nl、5#nj、"
                                   "6#zl、7#fl、8#sj与9#sm。")
    assert data["faction_style"] == 3
    for style in (True, 1.0, 0, 4, "2", None):
        assert "faction_style" not in cardart._card_data(
            combat, database, {"faction_style": style})

    form = factories.card(10010102, card_type="form", form_power=2, form_health=5)
    awaken = factories.card(10010103, card_type="spell", subtype="awaken",
                            awaken_power=2, awaken_health=-1)
    field = factories.card(10010104, card_type="field", intensity=6)
    reinforce = factories.card(10010105, card_type="reinforce", shikigami2=100102)
    assert cardart._card_data(form, database, {})["power"] == 2
    assert cardart._card_data(form, database, {})["health"] == 5
    awaken_data = cardart._card_data(awaken, database, {})
    assert awaken_data["evolve"] is True
    assert awaken_data["power+"] == 2 and awaken_data["health+"] == -1
    assert cardart._card_data(field, database, {})["type"] == "幻境"
    assert cardart._card_data(field, database, {})["durability"] == 6
    reinforce_data = cardart._card_data(reinforce, database, {})
    assert reinforce_data["type"] == "协战"
    assert reinforce_data["shikigami1"] == "引擎主式神"
    assert reinforce_data["shikigami2"] == "引擎副式神"
    shiki_data = cardart._card_data(primary, database, {})
    assert shiki_data["type"] == "式神"
    assert shiki_data["power"] == 3 and shiki_data["health"] == 4


def test_shikigami_awaken_payload_has_level_star_and_permanent_stats(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    awaken = factories.card(10010107, subtype="awaken")
    database = factories.db_of([definition], [awaken])
    shiki = SimpleNamespace(id=100101, awakened=awaken.id, level=2, faction="苍叶",
                            perm_power=2, perm_health=3, eff_power=9, health=7)
    seen = {}

    def capture(_cdef, _db, _library_dir, _cache_dir, display, overrides, drop_keys, height=None):
        seen.update(display=display, overrides=overrides, drop_keys=drop_keys)

    monkeypatch.setattr(cardart, "_card_pixmap_impl", capture)
    cardart.shikigami_pixmap(shiki, database, seat=1,
                             library_dir=tmp_path, cache_dir=tmp_path)
    assert seen["overrides"]["evolve"] is True
    assert seen["overrides"]["level"] == 2
    assert seen["overrides"]["level_color"] == "cyan"
    assert "level" not in seen["drop_keys"]
    assert seen["overrides"]["power"] == 5 and seen["overrides"]["health"] == 7
    assert seen["display"] == {"power": 5, "health": 7}


def test_shikigami_base_payload_has_seat_level_and_color(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    definition = factories.shiki(100101, power=3, health=4)
    database = factories.db_of([definition], [])
    shiki = SimpleNamespace(id=100101, awakened=None, level=1, faction="苍叶",
                            perm_power=0, perm_health=0, eff_power=3, health=4)
    seen = {}

    def capture(_cdef, _db, _library_dir, _cache_dir, display, overrides, drop_keys, height=None):
        seen.update(overrides=overrides)

    monkeypatch.setattr(cardart, "_card_pixmap_impl", capture)
    cardart.shikigami_pixmap(shiki, database, seat=3,
                             library_dir=tmp_path, cache_dir=tmp_path)
    assert seen["overrides"]["level"] == 1
    assert seen["overrides"]["level_color"] == "red"
    assert seen["overrides"]["evolve"] is False


def test_cardart_transparent_fallback_never_writes_disk(qapp, tmp_path, monkeypatch):
    from pathlib import Path
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)

    def fail_mkdir(*_args, **_kwargs):
        raise OSError("只读缓存目录")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    pixmap = cardart.card_pixmap(cdef, database, library_dir=tmp_path / "empty-library",
                                 cache_dir=cache_dir, display={"power+": 1})
    assert pixmap is not None and not pixmap.isNull()
    assert not cache_dir.exists()


def test_cardart_fallback_draws_centered_name_with_theme_color(qapp):
    from client.gui import cardart

    assert hasattr(cardart, "_paint_placeholder_name")
    pixmap = QPixmap(240, 336)
    pixmap.fill(Qt.transparent)
    cardart._paint_placeholder_name(pixmap, "占位卡名", "#26221c", entity=False)
    image = pixmap.toImage()
    assert any(image.pixelColor(x, y).alpha() for x in range(90, 151, 5)
               for y in range(125, 190, 5))


def test_card_widget_passes_level_color_and_requests_native_art(qapp, db, monkeypatch):
    from client.gui.widgets import CardWidget

    seen = {}

    def capture(_cdef, _db, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("client.gui.widgets.card_pixmap", capture)
    CardWidget(db.cards[10010101], db=db, level_color="cyan")
    assert seen["level_color"] == "cyan"
    assert seen["height"] is None


def test_card_widget_resize_scales_from_native_source_without_rerender(qapp, db, monkeypatch):
    from client.gui.widgets import CardWidget

    calls = []
    monkeypatch.setattr("client.gui.widgets.card_pixmap",
                        lambda *_args, **kwargs: calls.append(kwargs) or QPixmap(263, 512))
    widget = CardWidget(db.cards[10010101], db=db)
    calls.clear()
    widget.art_label.resize(60, 100)
    widget._fit_art()
    assert calls == []
    assert (widget._display_art.width(), widget._display_art.height()) == (308, 512)
    assert widget.art_label.pixmap().height() == 100


def test_card_widget_shikigami_and_card_share_display_size(qapp, db, monkeypatch):
    from client.gui.widgets import CardWidget

    def render(cdef, _db, **_kwargs):
        return QPixmap(263, 512) if getattr(cdef, "card_type", None) is None else QPixmap(302, 512)

    monkeypatch.setattr("client.gui.widgets.card_pixmap", render)
    shikigami = CardWidget(db.shikigami[100101], db=db)
    card = CardWidget(db.cards[10010101], db=db)
    for widget in (shikigami, card):
        widget.art_label.resize(120, 200)
        widget._fit_art()
    assert shikigami.art_label.pixmap().size() == card.art_label.pixmap().size()


def test_cardart_combat_amount_uses_static_base(qapp, gdb):
    from client.gui import cardart

    cdef = gdb.cards[10010204]
    data = cardart._card_data(cdef, gdb, {})
    assert cdef.name == "冲撞"
    assert data["power+"] == 2 and data["shield+"] == 2
    assert data["description"] == cardart._description(cdef.text)


def _cardart_cache_case(tmp_path):
    library_dir = tmp_path / "library"
    cache_dir = tmp_path / "cache"
    cdef = factories.card(10010101)
    _cardart_config(library_dir, cdef.id, cdef.version, "#336699")
    database = factories.db_of([factories.shiki(100101)], [cdef])
    return cdef, database, library_dir, cache_dir


def test_cardart_layouts_load_once_across_cache_reads(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    cardart._renderer(str(cardart.portrait.bwpdiy_root().resolve()))
    from bwpdiy.render import layout

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    calls = []
    original = layout.load_layouts

    def track(assets):
        calls.append(assets)
        return original(assets)

    monkeypatch.setattr(layout, "load_layouts", track)
    cardart.clear_cardart_caches()
    cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert len(calls) == 1
    cardart.clear_cardart_caches()


def test_cardart_real_library_renders(qapp, gdb, tmp_path):
    from client.gui import cardart

    _require_real_cardart_resources()
    cardart.clear_cardart_caches()
    for cid in (10010101, 10010201):
        pixmap = cardart.card_pixmap(
            gdb.cards[cid], gdb, cache_dir=tmp_path / "cardart-cache")
        assert pixmap is not None and not pixmap.isNull()
    for sid in (100101, 100102):
        pixmap = portrait.shikigami_portrait(gdb.shikigami[sid])
        empty = portrait.shikigami_portrait(
            gdb.shikigami[sid], library_dir=tmp_path / "empty-library")
        assert not pixmap.isNull() and pixmap.toImage() != empty.toImage()
    cardart.clear_cardart_caches()


def test_cardart_render_pixel_limit(qapp, tmp_path):
    from client.gui import cardart

    small_path = tmp_path / "small.png"
    Image.new("RGBA", (2, 2), "#336699").save(small_path)

    class HugeLibrary:
        def artwork(self, _path, _rotate=0):
            image = SimpleNamespace(width=100000, height=100000)
            return (100, 100), image

    with pytest.raises(ValueError, match="像素"):
        cardart._preflight_card_artwork(
            HugeLibrary(), {"path": str(small_path), "scale": 16, "rotate": 0})

    oversized_path = tmp_path / "oversized.png"
    Image.new("RGB", (4001, 4000), "#336699").save(oversized_path)

    class NoDecodeLibrary:
        def artwork(self, _path, _rotate=0):
            raise AssertionError("原图超限时不应进入 library.artwork")

    with pytest.raises(ValueError, match="像素"):
        cardart._preflight_card_artwork(
            NoDecodeLibrary(), {"path": str(oversized_path), "scale": 1, "rotate": 0})


def test_cardart_disk_cache_hit_and_memory_clear(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None and len(list(cache_dir.glob("*.png"))) == 1
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert second is first and len(list(cache_dir.glob("*.png"))) == 1

    cardart.clear_cardart_caches()
    assert len(list(cache_dir.glob("*.png"))) == 1

    def unexpected_render(*_args):
        pytest.fail("有效磁盘缓存不应重新渲染")

    original_render = cardart._render_card_pixmap
    monkeypatch.setattr(cardart, "_render_card_pixmap", unexpected_render)
    third = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert third is not None and not third.isNull()
    assert len(list(cache_dir.glob("*.png"))) == 1
    assert not list(cache_dir.glob("*.tmp"))
    monkeypatch.setattr(cardart, "_render_card_pixmap", original_render)
    cardart.clear_cardart_caches()


def test_cardart_config_snapshot_reuse_and_invalidation(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    original_safe_load = cardart.yaml.safe_load
    parsed = []

    def counted_safe_load(contents):
        parsed.append(contents)
        return original_safe_load(contents)

    monkeypatch.setattr(cardart.yaml, "safe_load", counted_safe_load)
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None and second is first
    assert len(parsed) == 1

    config_path = library_dir / "项目" / "cards" / f"{cdef.id}@{cdef.version}.yaml"
    config = original_safe_load(config_path.read_bytes())
    config["layout"] = {"elements": {"name": {"pos": [1, 0]}}, "text_regions": {}}
    config_path.write_text(
        cardart.yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    changed = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert changed is not None and changed.toImage() != first.toImage()
    assert len(parsed) == 2
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir) is changed
    assert len(parsed) == 2
    cardart.clear_cardart_caches()


def test_cardart_engine_text_changes_cache_key(qapp, tmp_path):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    changed = cdef.model_copy(update={"text": "引擎文本已变化"})
    assert cardart.card_pixmap(changed, database, library_dir=library_dir, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("*.png"))) == 2
    cardart.clear_cardart_caches()


def test_cardart_display_values_use_memory_not_disk_cache(qapp, tmp_path):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cdef = cdef.model_copy(update={"subtype": "awaken"})
    database = factories.db_of([factories.shiki(100101)], [cdef])
    cardart.clear_cardart_caches()
    base = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                               cache_dir=cache_dir,
                               display={"power+": 1, "health+": 2})
    boosted = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                                  cache_dir=cache_dir,
                                  display={"power+": 1, "health+": 7})
    assert base is not None and boosted is not None
    assert base.toImage() != boosted.toImage()
    assert cardart.card_pixmap(
        cdef, database, library_dir=library_dir, cache_dir=cache_dir,
        display={"power+": 1, "health+": 2}) is base
    assert not list(cache_dir.glob("*.png"))
    cardart.clear_cardart_caches()


def test_cardart_artwork_and_layout_change_cache_key(qapp, tmp_path):
    import yaml
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    config_path = library_dir / "项目" / "cards" / f"{cdef.id}@{cdef.version}.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    Image.new("RGBA", (8, 8), "#993366").save(
        library_dir / "项目" / "images" / "replacement.png")
    config["artwork"]["images"][0]["path"] = "replacement.png"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    artwork_changed = cardart.card_pixmap(
        cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert artwork_changed is not None
    assert artwork_changed.toImage() != first.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 2

    config["layout"] = {"elements": {"name": {"pos": [0, 0]}}, "text_regions": {}}
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    layout_changed = cardart.card_pixmap(
        cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert layout_changed is not None
    assert layout_changed.toImage() != artwork_changed.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 3
    config["layout"]["text_regions"]["unused"] = {"width": 300}
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("*.png"))) == 4
    cardart.clear_cardart_caches()


def test_cardart_only_image_content_changes_cache_key(qapp, tmp_path):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    image_path = library_dir / "项目" / "images" / f"{cdef.id}-{cdef.version}.png"
    stat = image_path.stat()
    os.utime(image_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("*.png"))) == 1
    Image.new("RGBA", (12, 8), "#993366").save(image_path)
    image_changed = cardart.card_pixmap(
        cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert image_changed is not None
    assert image_changed.toImage() != first.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 2
    cardart.clear_cardart_caches()


def test_cardart_same_mtime_image_change_does_not_reuse_artwork(qapp, tmp_path):
    from PySide6.QtGui import QPixmap
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    old_paths = set(cache_dir.glob("*.png"))
    image_path = library_dir / "项目" / "images" / f"{cdef.id}-{cdef.version}.png"
    original_stat = image_path.stat()
    Image.new("RGBA", (8, 8), "#993366").save(image_path)
    changed_stat = image_path.stat()
    assert changed_stat.st_size == original_stat.st_size
    os.utime(image_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert image_path.stat().st_mtime_ns == original_stat.st_mtime_ns

    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert second is not None and second.toImage() != first.toImage()
    new_paths = set(cache_dir.glob("*.png")) - old_paths
    assert len(new_paths) == 1
    cached = QPixmap(str(new_paths.pop()))
    assert cached.toImage() == second.toImage()
    assert cached.toImage() != first.toImage()
    cardart.clear_cardart_caches()


def test_cardart_concurrent_render_restores_shared_library(qapp, tmp_path, monkeypatch):
    import json
    import threading
    from client.gui import cardart

    cardart.clear_cardart_caches()
    original_renderer = cardart._renderer
    original_renderer(str(portrait.bwpdiy_root().resolve()))
    from bwpdiy.render import pipeline

    original_get_library = pipeline.get_library
    art_path = tmp_path / "art.png"
    Image.new("RGBA", (8, 8), "#336699").save(art_path)
    assets = {"A": tmp_path / "assets-a", "B": tmp_path / "assets-b"}
    expected = {"A": "#336699", "B": "#993366"}
    a_enter = threading.Event()
    b_enter = threading.Event()
    serialized = threading.Event()
    allow_a_return = threading.Event()
    allow_b_return = threading.Event()
    results = {}

    def render(_payload, assets_dir, layout):
        del layout
        key = "A" if assets_dir == assets["A"] else "B"
        if key == "A":
            a_enter.set()
            if not b_enter.wait(0.2):
                serialized.set()
            allow_a_return.wait()
        else:
            b_enter.set()
            allow_b_return.wait()
        library = pipeline.get_library(assets_dir)
        color = expected["A"] if library.root == assets["A"] else expected["B"]
        return Image.new("RGBA", (16, 16), color)

    monkeypatch.setattr(cardart, "_renderer",
                        lambda root: (assets[root], None, render))
    payload_json = json.dumps({"artwork": {"images": [{"path": str(art_path)}]}})

    def run(key):
        results[key] = cardart._render_card_pixmap(payload_json, "{}", key)

    first = threading.Thread(target=run, args=("A",))
    second = threading.Thread(target=run, args=("B",))
    try:
        first.start()
        assert a_enter.wait(2)
        second.start()
        assert serialized.wait(1) or b_enter.is_set()
        allow_a_return.set()
        first.join(2)
        allow_b_return.set()
        second.join(2)
        assert not first.is_alive() and not second.is_alive()
        assert results["A"] is not None and results["B"] is not None
        assert results["A"].toImage().pixelColor(8, 8).name() == expected["A"]
        assert results["B"].toImage().pixelColor(8, 8).name() == expected["B"]
        assert pipeline.get_library is original_get_library
    finally:
        allow_a_return.set()
        allow_b_return.set()
        first.join(2)
        second.join(2)
        pipeline.get_library = original_get_library
        monkeypatch.setattr(cardart, "_renderer", original_renderer)
        cardart.clear_cardart_caches()


def test_cardart_renderer_version_changes_cache_key(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QPixmap
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    root_text = str(portrait.bwpdiy_root().resolve())
    original_renderer = cardart._renderer
    real_assets, library, _render = original_renderer(root_text)
    import bwpdiy

    def render(_payload, _assets, layout):
        del layout
        color = "#336699" if bwpdiy.__version__ == "test-v1" else "#993366"
        return Image.new("RGBA", (16, 16), color)

    monkeypatch.setattr(cardart, "_renderer",
                        lambda _root: (real_assets, library, render))
    monkeypatch.setattr(bwpdiy, "__version__", "test-v1")
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    old_paths = set(cache_dir.glob("*.png"))
    monkeypatch.setattr(bwpdiy, "__version__", "test-v2")
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert second is not None and second.toImage() != first.toImage()
    new_paths = set(cache_dir.glob("*.png")) - old_paths
    assert len(new_paths) == 1
    cached = QPixmap(str(new_paths.pop()))
    assert cached.toImage() == second.toImage()
    assert cached.toImage() != first.toImage()
    monkeypatch.setattr(cardart, "_renderer", original_renderer)
    cardart.clear_cardart_caches()


def test_cardart_default_layout_content_changes_cache_key(qapp, tmp_path, monkeypatch):
    import json
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    root_text = str(portrait.bwpdiy_root().resolve())
    original_renderer = cardart._renderer
    real_assets, library, _render = original_renderer(root_text)
    from bwpdiy.render.layout import load_layouts

    assets = tmp_path / "renderer-assets"
    assets.mkdir()
    layouts = load_layouts(real_assets)
    (assets / "layout.json").write_text(
        json.dumps(layouts, ensure_ascii=False), encoding="utf-8")
    original_x = layouts["法术"]["elements"]["name"]["pos"][0]

    def render(payload, assets_dir, layout):
        if layout is None:
            layout = load_layouts(assets_dir)[payload["type"]]
        current_x = layout["elements"]["name"]["pos"][0]
        color = "#336699" if current_x == original_x else "#993366"
        return Image.new("RGBA", (16, 16), color)

    monkeypatch.setattr(cardart, "_renderer", lambda _root: (assets, library, render))
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    layouts["法术"]["elements"]["name"]["pos"][0] = original_x + 1
    (assets / "layout.json").write_text(
        json.dumps(layouts, ensure_ascii=False), encoding="utf-8")
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert second is not None and second.toImage() != first.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 2
    monkeypatch.setattr(cardart, "_renderer", original_renderer)
    cardart.clear_cardart_caches()


def test_cardart_truncated_disk_png_is_regenerated(qapp, tmp_path):
    from PySide6.QtGui import QPixmap
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    png_path = next(cache_dir.glob("*.png"))
    contents = png_path.read_bytes()
    png_path.write_bytes(contents[:len(contents) // 2])
    cardart.clear_cardart_caches()
    regenerated = cardart.card_pixmap(
        cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert regenerated is not None and not regenerated.isNull()
    assert not QPixmap(str(png_path)).isNull()
    assert len(list(cache_dir.glob("*.png"))) == 1
    assert not list(cache_dir.glob("*.tmp"))
    cardart.clear_cardart_caches()


def test_cardart_renderer_resources_change_cache_key(qapp, tmp_path, monkeypatch):
    from pathlib import Path
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    root_text = str(portrait.bwpdiy_root().resolve())
    original_renderer = cardart._renderer
    real_assets, library, _render = original_renderer(root_text)
    assets = tmp_path / "resource-assets"
    resource = assets / "frames" / "test.txt"
    resource.parent.mkdir(parents=True)
    resource.write_text("A", encoding="utf-8")

    def render(_payload, assets_dir, layout):
        del layout
        contents = (assets_dir / "frames" / "test.txt").read_text(encoding="utf-8")
        return Image.new("RGBA", (16, 16), "#336699" if contents == "A" else "#993366")

    monkeypatch.setattr(cardart, "_renderer", lambda _root: (assets, library, render))
    original_read_bytes = Path.read_bytes
    resource_reads = []

    def counted_read_bytes(path):
        if path == resource:
            resource_reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    first = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert first is not None
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir) is first
    assert len(resource_reads) == 2  # 每次调用重新校验内容，防止同元数据陈旧缓存
    resource.write_text("B", encoding="utf-8")
    second = cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir)
    assert second is not None and second.toImage() != first.toImage()
    assert len(resource_reads) == 3
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir) is second
    assert len(resource_reads) == 4
    assert len(list(cache_dir.glob("*.png"))) == 2
    monkeypatch.setattr(cardart, "_renderer", original_renderer)
    cardart.clear_cardart_caches()


@pytest.mark.parametrize("layout", [
    {"elements": {f"extra_{i}": {} for i in range(65)}},
    {"elements": {"faction": {"size": 513}}},
    {"elements": {"faction": {"size": [513, 32]}}},
], ids=["element-count", "scalar-size", "list-size"])
def test_cardart_layout_has_render_resource_budget(layout):
    from client.gui import cardart

    with pytest.raises(ValueError):
        cardart._validate_layout(layout)


@pytest.mark.parametrize("layout", [
    {"elements": {"name": {"font_size": 0}}},
    {"text_regions": {"desc": {"font_range": [300, 10]}}},
    {"text_regions": {"desc": {"font_range": [10, 20]}}},
    {"text_regions": {"desc": {"icon_scale": 17}}},
    {"elements": {"name": {"pos": [5000, 0]}}},
    {"elements": {"name": {"pos": [float("inf"), 0]}}},
], ids=["font-size", "font-range-limit", "font-range-order", "icon-scale", "size", "finite"])
def test_cardart_rejects_unsafe_layout(qapp, tmp_path, monkeypatch, layout):
    import yaml
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cardart.clear_cardart_caches()
    root_text = str(portrait.bwpdiy_root().resolve())
    original_renderer = cardart._renderer
    real_assets, library, _render = original_renderer(root_text)

    def render(_payload, _assets, layout):
        del layout
        return Image.new("RGBA", (16, 16), "#336699")

    monkeypatch.setattr(cardart, "_renderer",
                        lambda _root: (real_assets, library, render))
    config_path = library_dir / "项目" / "cards" / f"{cdef.id}@{cdef.version}.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["layout"] = layout
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert cardart.card_pixmap(cdef, database, library_dir=library_dir, cache_dir=cache_dir) is None
    assert not list(cache_dir.glob("*.png"))
    monkeypatch.setattr(cardart, "_renderer", original_renderer)
    cardart.clear_cardart_caches()


def test_portrait_snapshot_changes_and_failure_are_not_cached(qapp, tmp_path, monkeypatch):
    library_dir = tmp_path / "library"
    definition = SimpleNamespace(id=987654, name="测试", faction="苍叶", version=20260720)
    seen = []

    class Library:
        def artwork(self, path, rotate=0):
            with Image.open(path) as image:
                return image.size, image.convert("RGBA")

    def render(_lib, _elem, art, faction, scale, faction_style, width=None, height=None):
        del scale, faction, faction_style
        if art is None:
            seen.append(None)
            return Image.new("RGBA", (4, 4), "#112233")
        seen.append(art["offset_x"])
        if art["offset_x"]:
            return Image.new("RGBA", (4, 4), "#993366")
        with Image.open(art["path"]) as image:
            return image.convert("RGBA").resize((4, 4))

    monkeypatch.setattr(portrait, "_renderer",
                        lambda _root: (tmp_path, Library(), {"back_size": 8}, render))
    portrait._portrait_pixmap.cache_clear()
    empty = portrait.shikigami_portrait(definition, size=4, root=tmp_path, library_dir=library_dir)
    assert empty.toImage().pixelColor(1, 1).name() == "#112233"
    assert seen[0] is None
    _external_library(
        tmp_path,
        "id: 987654\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n"
        "portrait:\n  offset_x: 0\n  scale: 1\n  rotate: 0\n",
    )
    first = portrait.shikigami_portrait(definition, size=4, root=tmp_path, library_dir=library_dir)
    assert first.toImage() != empty.toImage()

    config_path = library_dir / "项目" / "shikigami" / "test.yaml"
    config_path.write_text(
        "id: 987654\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n"
        "portrait:\n  offset_x: 1\n  scale: 1\n  rotate: 0\n",
        encoding="utf-8")
    second = portrait.shikigami_portrait(definition, size=4, root=tmp_path, library_dir=library_dir)
    assert second.toImage() != first.toImage()
    assert seen[-1] == 1

    config_path.write_text(
        "id: 987654\nname: 测试\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n"
        "portrait:\n  offset_x: 0\n  scale: 1\n  rotate: 0\n",
        encoding="utf-8")
    Image.new("RGBA", (2, 2), "#229955").save(library_dir / "项目" / "images" / "art.png")
    third = portrait.shikigami_portrait(definition, size=4, root=tmp_path, library_dir=library_dir)
    assert third.toImage() != second.toImage()
    assert third.toImage().pixelColor(1, 1).name() == "#229955"
    portrait._portrait_pixmap.cache_clear()
