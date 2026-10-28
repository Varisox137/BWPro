"""式神录总览、单式主页与卡牌浏览测试（QT_QPA_PLATFORM=offscreen）。"""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from client.gui.app import THEMES, MainWindow
from client.gui.codex import ShikigamiCodexView
from db import deckstore
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture
def view(qapp, db):
    widget = ShikigamiCodexView(db)
    yield widget
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_main_window_opens_real_codex(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.go("codex")
    assert isinstance(win.pages["codex"], ShikigamiCodexView)
    win.close()


def test_overview_filters_and_shikigami_home(qapp, db, view):
    assert "标准(最新)" in [view.env_combo.itemText(i) for i in range(view.env_combo.count())]
    view.pack_combo.setCurrentIndex(view.pack_combo.findData("01"))
    view.faction_combo.setCurrentText("红莲")
    view.search_edit.setText(db.shikigami[100101].name)
    assert view.shiki_list.topLevelItemCount() == 1
    assert view.shiki_list.topLevelItem(0).childCount() == 1
    view.select_shikigami(100101)
    assert view.stack.currentWidget() is view.overview_page
    assert view.overview_card.cdef.id == 100101
    view.show_shikigami_cards()
    definition = db.shikigami[100101]
    assert view.stack.currentWidget() is view.home_page
    assert definition.name in view.name_label.text()
    for attribute in ("home_body", "portrait_label", "stats_label", "ability_label"):
        assert not hasattr(view, attribute)


def test_environment_change_reloads_shikigami_and_cards(qapp, db, view):
    view.select_shikigami(100101)
    view.show_shikigami_cards()
    view.env_combo.setEditText("20260720")
    view.change_environment()
    assert view.current_env() == 20260720
    assert view.selected_sid == 100101
    assert view.card_widgets
    view.env_combo.setEditText("not-a-date")
    view.change_environment()
    assert view.edb.shikigami[100101].version == 20260720


def test_five_card_pages_detail_and_loading(qapp, db, view, monkeypatch):
    reinforce = F.card(10010221, shikigami=100102, shikigami2=100101,
                       name="协战", card_type="reinforce")
    db.cards[reinforce.id] = reinforce
    events = []
    original_start = view._start_loading
    original_tick = view._loading_tick
    original_finish = view._finish_loading
    monkeypatch.setattr(view, "_start_loading", lambda: events.append("start") or original_start())
    monkeypatch.setattr(view, "_loading_tick", lambda: events.append("tick") or original_tick())
    monkeypatch.setattr(view, "_finish_loading", lambda: events.append("finish") or original_finish())
    view.select_shikigami(100101)
    assert not events
    view.show_shikigami_cards()
    assert events[0] == "start" and events[-1] == "finish"
    assert events.count("tick") >= 5
    assert view.loading_label.isHidden()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    assert len(view.card_widgets) == 5
    assert all(widget.minimumWidth() == 0 for widget in view.card_widgets)
    widths = [widget.width() for widget in view.card_widgets]
    assert max(widths) - min(widths) <= 1
    margins = view.card_area.layout().contentsMargins()
    assert view.card_widgets[0].x() == margins.left()
    assert view.card_widgets[-1].x() + view.card_widgets[-1].width() == (
        view.card_area.width() - margins.right())
    for widget in view.card_widgets:
        pixmap = widget.art_label.pixmap()
        assert not pixmap.isNull()
        assert pixmap.width() <= widget.art_label.width() + 1
        assert pixmap.height() <= widget.art_label.height() + 1
    assert view.card_widgets[0].cdef.id == 100101
    assert view.card_widgets[0].count_label.isHidden()
    assert view.card_widgets[-1].cdef.id != reinforce.id
    assert view.page_count == 2
    view.turn_card_page(1)
    assert len(view.card_widgets) == 5
    assert view.card_widgets[-1].cdef.id == reinforce.id
    assert not view.card_next.isEnabled()
    view.turn_card_page(-1)
    assert view.page_index == 0

    seen = []
    monkeypatch.setattr("client.gui.codex.CardDetailDialog",
                        lambda cdef, *args, **kwargs:
                        SimpleNamespace(exec=lambda: seen.append(cdef)))
    view.show_card_detail(view.card_widgets[1].cdef)
    assert seen == [view.card_widgets[1].cdef]


def test_theme_and_empty_filter(qapp, view):
    assert view.shiki_list.indentation() <= 10
    view.apply_theme("light", THEMES["light"])
    assert "#cfe5f7" in view.styleSheet()
    view.apply_theme("dark", THEMES["dark"])
    view.search_edit.setText("不存在的式神")
    assert view.shiki_list.topLevelItemCount() == 0
    assert not view.empty_label.isHidden()
