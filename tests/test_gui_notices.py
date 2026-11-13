"""操作说明与按版本首次启动的更新提示。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from client.gui.app import MainWindow
from client.gui.settings import SettingsView
from core.version import VERSION


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_settings_operation_help_button(qapp, db, monkeypatch):
    view = SettingsView(db)
    assert hasattr(view, "operation_help_button")
    from client.gui import notices

    calls = []
    monkeypatch.setattr(notices, "show_text_dialog",
                        lambda *args: calls.append(args))
    view.operation_help_button.click()
    assert len(calls) == 1
    assert calls[0][1] == "操作说明"
    assert calls[0][2] == notices.HELP_TEXT


def test_release_notes_show_only_for_first_launch_of_new_version(qapp, db, tmp_path, monkeypatch):
    from client.gui import app as app_module

    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert hasattr(win, "show_release_notes_once")
    from client.gui import notices

    stored = {"last_started_version": ""}
    calls = []
    monkeypatch.setattr(app_module, "load_gui_settings", lambda: dict(stored))
    monkeypatch.setattr(app_module, "save_gui_settings",
                        lambda values: stored.update(values))
    monkeypatch.setattr(notices, "show_text_dialog",
                        lambda *args: calls.append(args))

    win.show_release_notes_once()
    assert stored["last_started_version"] == VERSION
    assert len(calls) == 1
    assert calls[0][1] == f"BWPro v{VERSION} 最近更新"
    assert calls[0][2] == notices.RELEASE_NOTES[VERSION]

    win.show_release_notes_once()
    assert len(calls) == 1
    win.close()
