"""桌面 GUI 冒烟测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from client.gui.app import MENU_ENTRIES, MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_menu_navigation_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert win.stack.currentIndex() == 0
    for key, _name, _sub in MENU_ENTRIES:
        win.go(key)
        assert win.stack.currentWidget() is win.pages[key]
        win.go_menu()
        assert win.stack.currentIndex() == 0
    win.toggle_theme()
    assert win.theme == "dark"
    assert "#141121" in win.styleSheet()
    win.toggle_theme()
    assert win.theme == "light"
    assert "#f3efe8" in win.styleSheet()
    win.close()
