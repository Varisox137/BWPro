"""式神录总览、单式主页与卡牌浏览测试（QT_QPA_PLATFORM=offscreen）。"""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
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


@pytest.fixture
def real_view(qapp, gdb):
    widget = ShikigamiCodexView(gdb)
    yield widget
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_overview_filters_and_shikigami_home(qapp, db, view):
    assert "标准(最新)" in [view.env_combo.itemText(i) for i in range(view.env_combo.count())]
    assert view.pack_combo.itemText(view.pack_combo.findData("001")) == "经典包"
    view.pack_combo.setCurrentIndex(view.pack_combo.findData("001"))
    view.faction_combo.setCurrentText("红莲")
    view.search_edit.setText(db.shikigami[100101].name)
    assert view.shiki_list.topLevelItemCount() == 1
    assert view.shiki_list.topLevelItem(0).childCount() == 1
    view.select_shikigami(100101)
    assert view.stack.currentWidget() is view.overview_page
    assert view.overview_card.cdef.id == 100101
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    assert view.overview_card.width() >= 400
    assert view.overview_card.height() >= 500
    view.overview_card.clicked.emit(db.shikigami[100101])
    definition = db.shikigami[100101]
    assert view.stack.currentWidget() is view.home_page
    assert definition.name in view.name_label.text()
    for attribute in ("home_body", "portrait_label", "stats_label", "ability_label"):
        assert not hasattr(view, attribute)


def test_codex_loading_covers_only_card_area(qapp, view, monkeypatch):
    original = view._start_loading
    seen = []
    monkeypatch.setattr(
        view, "_start_loading",
        lambda *args: original(*args) or seen.append(
            (view.stack.isHidden(), view.loading_label.geometry() == view.card_area.geometry())))
    texts = []
    view.loading.on_text = texts.append
    view.show_shikigami_cards()
    assert seen == [(False, True)]
    assert any("（1/" in text for text in texts)


def test_environment_dates_include_all_snapshots_in_order(qapp, db):
    from db.envs import available_env_dates

    db.raw_cards[99999999] = {"versions": {"history": [
        {"date": 20200423}, {"date": 20200101}, {"date": 20191212},
    ]}}
    dates = available_env_dates(db)
    assert dates == sorted(dates)
    assert {20191212, 20200101, 20200327, 20200423} <= set(dates)


def test_environment_change_reloads_shikigami_and_cards(qapp, db, view):
    view.select_shikigami(100101)
    view.show_shikigami_cards()
    view.env_combo.setEditText("20260720")
    view.change_environment()
    assert view.current_env() == 20260720
    assert view.selected_sid == 100101
    assert view.card_widgets
    assert view.overview_card._art_db is view.edb
    assert all(widget._art_db is view.edb for widget in view.card_widgets)
    view.env_combo.setEditText("not-a-date")
    view.change_environment()
    assert view.edb.shikigami[100101].version == 20260720


def test_five_card_pages_detail_and_loading(qapp, db, view, monkeypatch):
    reinforce = F.card(10010221, shikigami=100102, shikigami2=100101,
                       name="协战", card_type="reinforce")
    db.cards[reinforce.id] = reinforce
    token = F.card(10010151, shikigami=100101, name="衍生", token=True)
    db.cards[token.id] = token
    events = []
    original_start = view._start_loading
    original_tick = view._loading_tick
    original_finish = view._finish_loading
    monkeypatch.setattr(view, "_start_loading",
                        lambda *args: events.append("start") or original_start(*args))
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
    assert len(view._all_card_widgets) == len(view._current_cards())
    assert len({widget.height() for widget in view.card_widgets}) == 1
    for widget in view.card_widgets:
        pixmap = widget.art_label.pixmap()
        assert not pixmap.isNull()
        assert pixmap.width() <= widget.art_label.width() + 1
        assert pixmap.height() <= widget.art_label.height() + 1
    assert view.card_widgets[0].cdef.id == 100101
    assert view.card_widgets[0].count_label.isHidden()
    assert view.card_widgets[-1].cdef.id != reinforce.id
    assert view.page_count == 3
    loaded_widgets = list(view._all_card_widgets)
    loading_events = list(events)
    view.turn_card_page(1)
    assert events == loading_events
    assert view._all_card_widgets == loaded_widgets
    assert len(view.card_widgets) == 5
    assert view.card_widgets[-1].cdef.id == reinforce.id
    assert view.card_next.isEnabled()
    view.turn_card_page(1)
    assert [widget.cdef.id for widget in view.card_widgets] == [10010151]
    assert events == loading_events
    assert view._all_card_widgets == loaded_widgets
    view.jump_to_card_group("primary")
    assert view.page_index == 0

    seen = []
    monkeypatch.setattr("client.gui.codex.CardDetailDialog",
                        lambda cdef, *args, **kwargs:
                        SimpleNamespace(exec=lambda: seen.append(cdef)))
    view.show_card_detail(view.card_widgets[1].cdef)
    assert seen == [view.card_widgets[1].cdef]


def test_codex_cards_share_height_and_frame_axis_spacing(qapp, view, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter, QPixmap

    widths = [100, 120, 80, 110, 90]
    axis_ratios = [0.40, 0.55, 0.45, 0.60, 0.50]
    ids = [100101] + [10010100 + n for n in range(1, 5)]

    def fake_card_pixmap(cdef, *_args, **_kwargs):
        index = ids.index(cdef.id) if cdef.id in ids else cdef.id % len(ids)
        width = widths[index]
        image = QImage(width, 100, QImage.Format_ARGB32)
        image.fill(0)
        axis = round(width * axis_ratios[index])
        frame_width = round(width * 0.7)
        painter = QPainter(image)
        painter.fillRect(QRect(axis - frame_width // 2, 0, frame_width, 100), Qt.white)
        painter.fillRect(QRect(0, 5, 12, 20), Qt.white)  # 等级角标不参与卡框中线
        painter.end()
        return QPixmap.fromImage(image)

    monkeypatch.setattr("client.gui.widgets.card_pixmap", fake_card_pixmap)
    view.select_shikigami(100101)
    view.show_shikigami_cards()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()

    pixmaps = [widget.art_label.pixmap() for widget in view.card_widgets]
    assert len({pixmap.height() for pixmap in pixmaps}) == 1
    axes = []
    actual_ratios = [
        (round(width * ratio) + (round(width * 0.7) % 2) / 2) / width
        for width, ratio in zip(widths, axis_ratios)
    ]
    for widget, pixmap, ratio in zip(view.card_widgets, pixmaps, actual_ratios):
        art_x = widget.art_label.x() + (widget.art_label.width() - pixmap.width()) / 2
        axes.append(widget.x() + art_x + pixmap.width() * ratio)
    spacings = [right - left for left, right in zip(axes, axes[1:])]
    assert max(spacings) - min(spacings) <= 1


def test_derived_card_pages_and_group_navigation(qapp, real_view, monkeypatch):
    view = real_view
    view.select_shikigami(100121)
    view.show_shikigami_cards()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    assert [card.id for card in view._current_card_groups()[1]] == [10012151, 10012199]
    assert view.page_count == 3
    assert len(view._all_card_widgets) == 11
    assert view.card_primary.isVisible() and view.card_derived.isVisible()
    assert not view.card_primary.isEnabled()
    assert view.card_derived.isEnabled()
    view.jump_to_card_group("derived")
    assert view.page_index == 2
    assert [card.cdef.id for card in view.card_widgets] == [10012151, 10012199]
    assert view.card_primary.isEnabled()
    assert not view.card_derived.isEnabled()

    seen = []
    monkeypatch.setattr("client.gui.codex.CardDetailDialog",
                        lambda cdef, *args, **kwargs:
                        SimpleNamespace(exec=lambda: seen.append(cdef)))
    view.card_widgets[0].clicked.emit(view.card_widgets[0].cdef)
    assert seen == [view.edb.cards[10012151]]
    monkeypatch.setattr("client.gui.codex.CardAppearanceDialog",
                        lambda *args, **kwargs: SimpleNamespace(exec=lambda: 0))
    view.card_widgets[1].detail_clicked.emit(view.card_widgets[1].cdef)

    view.jump_to_card_group("primary")
    assert view.page_index == 0
    view.select_shikigami(100404)
    view.show_shikigami_cards()
    assert len(view._current_card_groups()[1]) == 16
    assert view.page_count == 6
    view.jump_to_card_group("derived")
    assert view.page_index == 2

    for definition in view.pool:
        view.select_shikigami(definition.id)
        if not view._current_card_groups()[1]:
            break
    else:
        raise AssertionError("测试数据库应至少有一个无衍生内容的式神")
    view.show_shikigami_cards()
    assert view.card_primary.isHidden() and view.card_derived.isHidden()


def test_card_page_placeholders_do_not_cover_returning_page(qapp, view):
    from PySide6.QtWidgets import QWidget

    view.select_shikigami(100101)
    view.show_shikigami_cards()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    first_page = list(view.card_widgets)
    assert len(first_page) == 5
    view.turn_card_page(1)
    qapp.processEvents()
    assert len(view.card_widgets) == 4
    view.turn_card_page(-1)
    qapp.processEvents()
    assert view.card_widgets == first_page
    assert first_page[4].isVisible()
    assert not first_page[4].art_label.pixmap().isNull()
    stray_widgets = [child for child in view.card_area.children()
                     if isinstance(child, QWidget) and child not in view._all_card_widgets
                     and child.isVisible()]
    assert not stray_widgets


def test_theme_and_empty_filter(qapp, view):
    assert view.shiki_list.indentation() <= 10
    view.apply_theme("light", THEMES["light"])
    assert "#cfe5f7" in view.styleSheet()
    assert "QTreeWidget::branch:selected" in view.styleSheet()
    assert "border: none;" in view.styleSheet()
    assert "outline: none;" in view.styleSheet()
    view.apply_theme("dark", THEMES["dark"])
    view.search_edit.setText("不存在的式神")
    assert view.shiki_list.topLevelItemCount() == 0
    assert not view.empty_label.isHidden()


def test_mainwindow_applies_codex_selection_theme(qapp, db, tmp_path):
    window = MainWindow(db=db, store_path=tmp_path / "decks.json")
    try:
        window.go("codex")
        assert isinstance(window.pages["codex"], ShikigamiCodexView)
        window.set_theme("light")
        assert "#cfe5f7" in window.pages["codex"].styleSheet()
    finally:
        window.close()


def test_codex_leave_and_reenter_resets_browsing_state(qapp, db, tmp_path):
    window = MainWindow(db=db, store_path=tmp_path / "decks.json")
    try:
        window.go("codex")
        page = window.pages["codex"]
        first_sid = page.pool[0].id
        page.env_combo.setEditText("20260720")
        page.change_environment()
        page.pack_combo.setCurrentIndex(1)
        page.faction_combo.setCurrentIndex(1)
        page.search_edit.setText("不存在的式神")
        page.show_shikigami_cards()
        window.back()
        window.go("codex")
        assert page.stack.currentWidget() is page.overview_page
        assert page.env_combo.currentIndex() == 0
        assert page.pack_combo.currentIndex() == 0
        assert page.faction_combo.currentIndex() == 0
        assert page.search_edit.text() == ""
        assert page.selected_sid == first_sid
        assert page.page_index == 0
    finally:
        window.close()


def test_raw_unreleased_reinforce_cards_are_hidden(qapp, gdb):
    view = ShikigamiCodexView(gdb)
    try:
        for sid, card_id in ((100204, 10020421), (100207, 10020721), (100307, 10030721)):
            view.select_shikigami(sid)
            assert card_id not in {card.id for card in view._current_cards()}
    finally:
        view.close()


def test_first_diy_mouse_click_keeps_selection(qapp):
    from diy.runtime import BUILTIN_CONTENT_ROOT, load_database
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    db = load_database(content_roots=[BUILTIN_CONTENT_ROOT],
                       include_builtin=False, include_downloaded=False)
    view = ShikigamiCodexView(db)
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    items = [view.shiki_list.topLevelItem(i).child(j)
             for i in range(view.shiki_list.topLevelItemCount())
             for j in range(view.shiki_list.topLevelItem(i).childCount())]
    target = next(item for item in items if item.data(0, Qt.UserRole) == 110101)
    view.shiki_list.scrollToItem(target)
    qapp.processEvents()
    QTest.mouseClick(view.shiki_list.viewport(), Qt.LeftButton, Qt.NoModifier,
                     view.shiki_list.visualItemRect(target).center())
    qapp.processEvents()
    assert view.selected_sid == 110101
    assert view.shiki_list.currentItem().data(0, Qt.UserRole) == 110101
    view.close()
    view.deleteLater()
