"""桌面 GUI 冒烟测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel

from client.gui.app import MENU_ENTRIES, MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_menu_navigation_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert win.windowTitle() == "BWPro"
    assert win.findChild(QLabel, "title").text() == "BWPro"
    assert "（" not in dict((key, sub) for key, _name, sub in MENU_ENTRIES)["codex"]
    assert win.stack.currentIndex() == 0
    assert win.back_button.isHidden()
    assert not win.theme_button.isHidden()
    assert win.theme_button.width() == win.theme_button.height() <= 40
    assert not win.theme_button.icon().isNull()
    for key, _name, _sub in MENU_ENTRIES:
        win.go(key)
        assert win.stack.currentWidget() is win.pages[key]
        assert not win.back_button.isHidden()
        assert not win.theme_button.isHidden()
        win.back_button.click()
        assert win.stack.currentIndex() == 0
        assert win.back_button.isHidden()
    win.go("builder")
    win.theme_button.click()
    assert win.theme == "dark"
    assert "#141121" in win.styleSheet()
    win.theme_button.click()
    assert win.theme == "light"
    assert "#f3efe8" in win.styleSheet()
    win.go("settings")
    win.set_theme("dark")
    assert "QLabel#viewTitle" in win.pages["settings"].styleSheet()
    win.close()
