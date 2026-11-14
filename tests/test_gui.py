"""桌面 GUI 冒烟测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel

from client.gui.app import MENU_ENTRIES, THEMES, MainWindow
from client.gui.builder import DeckBuilderView
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_menu_navigation_and_theme(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    assert win.windowTitle() == "BWPro by Varisox137"
    title = win.findChild(QLabel, "title")
    assert title.text() == (
        'BWPro by <a href="https://github.com/Varisox137/BWPro" '
        f'style="color:{THEMES["light"]["gold"]}; text-decoration:underline">'
        'Varisox137</a>')
    assert title.openExternalLinks()
    assert win.findChild(QLabel, "githubLink") is None
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
    assert isinstance(win.pages["builder"], DeckBuilderView)
    win.theme_button.click()
    assert win.theme == "dark"
    assert f'color:{THEMES["dark"]["gold"]}' in title.text()
    assert win.pages["builder"].theme == "dark"
    assert "#141121" in win.styleSheet()
    win.theme_button.click()
    assert win.theme == "light"
    assert "#f3efe8" in win.styleSheet()
    assert "QListWidget::item:selected" in win.styleSheet()
    assert "QTreeWidget::item:selected" in win.styleSheet()
    assert "QComboBox:hover" in win.styleSheet()
    assert "QCheckBox::indicator:checked" in win.styleSheet()
    assert THEMES["light"]["gold"] in win.styleSheet()
    assert "checkmark.svg" in win.styleSheet()
    assert "#cfe5f7" in win.styleSheet()
    win.go("settings")
    win.set_theme("dark")
    assert "QLabel#viewTitle" in win.pages["settings"].styleSheet()
    win.close()


def test_menu_footer_disclaimer_removed(qapp, db, tmp_path):
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    text = "\n".join(label.text() for label in win.stack.currentWidget().findChildren(QLabel))
    for phrase in ("个人学习项目", "与官方无关", "素材版权"):
        assert phrase not in text
    win.close()


def test_settings_show_shared_version_and_manual_update_entry(qapp, db, tmp_path):
    from core.version import VERSION

    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    settings = win.pages["settings"]
    assert settings.version_label.text() == f"当前版本：{VERSION}"
    assert settings.update_button.text() == "检查更新"
    win.close()


class ImmediateThread:
    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def process_update_callback(qapp):
    qapp.processEvents()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_closed_window_ignores_stale_update_callback(qapp, db, tmp_path, monkeypatch):
    import client.update

    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    monkeypatch.setattr("client.gui.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr(client.update, "check_for_update", lambda: None)
    monkeypatch.setattr(
        "client.gui.app.ask_confirmation",
        lambda *args: pytest.fail("关闭后的回调不得弹窗"))

    win.check_for_updates(manual=False)
    win.close()
    process_update_callback(qapp)

    assert win._update_closed is True


def test_update_requires_download_and_restart_confirmations_even_in_battle(
        qapp, db, tmp_path, monkeypatch):
    import client.update
    from PySide6.QtWidgets import QMessageBox

    available = client.update.AvailableUpdate(
        tag="v0.3.1", exe_name="BWPro-v0.3.1.exe",
        exe_url="https://cdn.example/app.exe",
        sha256_name="BWPro-v0.3.1.exe.sha256",
        sha256_url="https://cdn.example/app.sha256")
    questions = []
    launched = []
    quit_calls = []
    monkeypatch.setattr("client.gui.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr(client.update, "check_for_update", lambda: available)

    def download(available, destination, cancel_event=None):
        import hashlib
        destination.write_bytes(b"new")
        return client.update.DownloadedUpdate(
            available, destination, hashlib.sha256(b"new").hexdigest())

    monkeypatch.setattr(client.update, "download_update", download)
    monkeypatch.setattr(client.update, "launch_update", lambda *args: launched.append(args))
    monkeypatch.setattr(MainWindow, "in_battle", lambda self: True)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_calls.append(True))
    monkeypatch.setattr("client.gui.app.sys.frozen", True, raising=False)
    monkeypatch.setattr(
        "client.gui.app.sys.executable", str(tmp_path / "BWPro-v0.3.0.exe"))

    def confirm(_parent, title, text):
        questions.append((title, text))
        if title == "重启并安装更新":
            assert launched == [] and quit_calls == []
        return QMessageBox.Yes

    monkeypatch.setattr("client.gui.app.ask_confirmation", confirm)
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.check_for_updates(manual=True)
    process_update_callback(qapp)
    assert questions[0][0] == "发现新版本"
    process_update_callback(qapp)
    assert len(questions) == 2
    assert questions[1][0] == "重启并安装更新"
    assert "对局" in questions[1][1]
    assert len(launched) == 1
    assert quit_calls == [True]
    win._update_closed = True


def test_background_update_errors_do_not_block_or_prompt(qapp, db, tmp_path, monkeypatch):
    import client.update

    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    monkeypatch.setattr("client.gui.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr(
        client.update, "check_for_update",
        lambda: (_ for _ in ()).throw(client.update.UpdateError("离线")))
    monkeypatch.setattr(
        "client.gui.app.ask_confirmation",
        lambda *args: pytest.fail("后台离线不得弹窗"))

    win.check_for_updates(manual=False)
    process_update_callback(qapp)
    assert win.pages["settings"].update_button.isEnabled()
    win.close()


def test_diy_refresh_updates_all_local_views(qapp, db, tmp_path, monkeypatch):
    diy_db = F.db_of(
        list(db.shikigami.values()) + [F.shiki(110101)],
        list(db.cards.values()) + [F.card(11010101, shikigami=110101)],
    )
    monkeypatch.setattr("diy.runtime.load_database", lambda: diy_db)
    monkeypatch.setattr("db.loader.CardDatabase.load", classmethod(lambda _cls: db))
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.refresh_diy_content()
    assert win.pages["builder"].db is diy_db
    assert win.pages["codex"].db is diy_db
    assert win.pages["hotseat"].diy_db is diy_db
    assert win.pages["online"].diy_db is diy_db
    assert win.pages["hotseat"].official_db is db
    assert win.pages["online"].official_db is db
    win.close()
