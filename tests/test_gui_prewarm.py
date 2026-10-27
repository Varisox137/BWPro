"""启动预热、加载遮罩与设置页重建测试。"""
import json
import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from client.gui.app import MainWindow
from client.gui.builder import DeckBuilderView
from client.gui.prewarm import prewarm_all
from client.gui.settings import SettingsView
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _configs(root):
    shiki_dir = root / "library" / "项目" / "shikigami"
    cards_dir = root / "library" / "项目" / "cards"
    images_dir = root / "library" / "项目" / "images"
    shiki_dir.mkdir(parents=True)
    cards_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    (shiki_dir / "base.yaml").write_text(
        "id: 100101\nname: 基础\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n", encoding="utf-8")
    (cards_dir / "card.yaml").write_text(
        "id: 10010101\nname: 法术\nversion_date: 20260720\n"
        "artwork:\n  images:\n    - path: art.png\n", encoding="utf-8")
    Image.new("RGBA", (2, 2), "#336699").save(images_dir / "art.png")


def test_prewarm_writes_manifest_and_tracks_changes(qapp, tmp_path, monkeypatch):
    from client.gui import prewarm

    _configs(tmp_path)
    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    calls = []
    monkeypatch.setattr(prewarm, "card_pixmap",
                        lambda cdef, _db, **kwargs: calls.append(("card", cdef.id, kwargs)) or QPixmap())
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda shiki, _db, **kwargs: calls.append(("entity", shiki.id, kwargs)) or QPixmap())
    monkeypatch.setattr(prewarm, "shikigami_portrait",
                        lambda definition, **kwargs: calls.append(("portrait", definition.id, kwargs)) or QPixmap())
    progress = []
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache",
                          on_progress=lambda current, total: progress.append((current, total)))
    assert len(entries) == 2
    assert {call[0] for call in calls} == {"card", "entity", "portrait"}
    assert progress[-1] == (2, 2)
    manifest = json.loads((tmp_path / "cache" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 2
    assert all(entry["config_sha256"] and entry["art_sha256"] for entry in manifest["entries"])

    config = tmp_path / "library" / "项目" / "cards" / "card.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# updated\n", encoding="utf-8")
    updated = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert updated[0]["config_sha256"] != entries[0]["config_sha256"]


def test_builder_loading_shows_only_prompt(qapp, db, tmp_path, monkeypatch):
    view = DeckBuilderView(db, store_path=tmp_path / "decks.json")
    events = []
    original_start = view._start_loading
    original_finish = view._finish_loading
    monkeypatch.setattr(view, "_start_loading",
                        lambda: original_start() or events.append(("start", view.stack.isHidden())))
    monkeypatch.setattr(view, "_finish_loading",
                        lambda: original_finish() or events.append(("finish", view.stack.isHidden())))
    view.new_deck()
    view.add_shikigami(F.TEAM[0])
    assert events[0] == ("start", True)
    assert events[-1] == ("finish", False)
    assert view.loading_label.isHidden()
    view.close()


def test_battle_loading_has_fullscreen_background(qapp, db, tmp_path):
    from client.gui.battle import HotseatView

    view = HotseatView(db, store_path=tmp_path / "decks.json")
    scene = view.battle_scene
    scene.show_loading("正在准备对局")
    assert scene.loading_background.isVisible()
    assert scene.loading_item.isVisible()
    scene.hide_loading()
    assert not scene.loading_background.isVisible()
    assert not scene.loading_item.isVisible()


def test_settings_rebuild_and_startup_prewarm(qapp, db, tmp_path, monkeypatch):
    from client.gui import settings

    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.go("settings")
    page = win.pages["settings"]
    assert isinstance(page, SettingsView)
    calls = []
    monkeypatch.setattr(settings, "prewarm_all",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or [])
    monkeypatch.setattr(settings, "ask_confirmation", lambda *_args: QMessageBox.Yes)
    page.rebuild()
    assert calls
    assert page.rebuild_button.isEnabled()
    assert not page.loading_overlay.isVisible()
    monkeypatch.setattr("client.gui.app.prewarm_all",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or [])
    win.prewarm_resources()
    assert len(calls) == 2
    assert not win.loading_overlay.isVisible()
    win.close()
