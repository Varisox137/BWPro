"""桌面 GUI 卡组构筑测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton

from client.gui.app import MainWindow
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
    assert [w.cdef.id for w in view.card_widgets] == list(range(sid * 100 + 1, sid * 100 + 6))
    view.next_card_page()
    assert len(view.card_widgets) == 4
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
    deckstore.save_decks(db, [{"name": "主力", "groups": legal_groups(db), "env": None}],
                         tmp_path / "decks.json")
    view.reload_decks()
    frame = view.deck_frames[0]
    assert frame.maximumWidth() <= 300
    assert [label.text() for label in frame.findChildren(QLabel, "deckShikiName")] == [
        db.shikigami[sid].name for sid in factories.TEAM]
    portraits = frame.findChildren(QLabel, "shikiPortrait")
    assert len(portraits) == 4
    assert all(not label.pixmap().isNull() for label in portraits)
    texts = [button.text() for button in frame.findChildren(QPushButton)]
    assert all(text in texts for text in ("编辑", "查看卡组码", "重命名", "删除"))


def test_environment_options_are_unique(qapp, view):
    view.new_deck()
    texts = [view.env_combo.itemText(i) for i in range(view.env_combo.count())]
    dates = [view.env_combo.itemData(i) for i in range(view.env_combo.count())]
    assert len(texts) == len(set(texts))
    assert len(dates) == len(set(dates))


def test_cancel_add_restores_shikigami_selection(qapp, view, monkeypatch):
    view.new_deck()
    view.add_shikigami(factories.TEAM[0])
    monkeypatch.setattr("client.gui.builder.ShikigamiDialog.exec", lambda _self: 0)
    view.shiki_list.setCurrentRow(len(view.team))
    assert view.shiki_list.currentRow() == 0
    assert view.selected_sid == factories.TEAM[0]


def test_dialog_standard_buttons_are_chinese_and_compact(qapp, db, view):
    dialog = DeckCodeDialog(editable=True, parent=view)
    box = dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.Ok).text() == "确定"
    assert box.button(QDialogButtonBox.Cancel).text() == "取消"
    assert all(button.objectName() == "dialogButton" for button in box.buttons())
    dialog.close()
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
