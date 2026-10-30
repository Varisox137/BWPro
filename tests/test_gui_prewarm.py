"""启动预热、加载遮罩与设置页重建测试。"""
import json
import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

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
                        lambda cdef, _db, **kwargs: calls.append(("card", cdef.id, kwargs)) or QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda shiki, _db, **kwargs: calls.append(("entity", shiki.id, kwargs)) or QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "shikigami_portrait",
                        lambda definition, **kwargs: calls.append(("portrait", definition.id, kwargs)) or QPixmap(2, 2),
                        raising=False)
    fingerprints = []
    original_fingerprint = prewarm.portrait._config_fingerprint

    def track_fingerprint(root):
        fingerprints.append(root)
        return original_fingerprint(root)

    monkeypatch.setattr(prewarm.portrait, "_config_fingerprint", track_fingerprint)
    progress = []
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache",
                          on_progress=lambda current, total: progress.append((current, total)))
    assert len(entries) == 2
    assert {call[0] for call in calls} == {"card", "entity"}
    assert len(fingerprints) == 1
    big_cards = [call for call in calls if call[0] == "card"]
    assert len(big_cards) == 2
    assert all("height" not in call[2] for call in big_cards)
    small_cards = [call for call in calls if call[0] == "entity"]
    assert all(call[2]["disk_cache"] for call in small_cards)
    assert len({id(call[2]["cache_context"]) for call in calls}) == 1
    assert "portrait_config_fingerprint" in calls[0][2]["cache_context"]
    assert progress[-1] == (2, 2)
    manifest = json.loads((tmp_path / "cache" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 2
    assert all(entry["config_sha256"] and entry["art_sha256"] for entry in manifest["entries"])
    assert all(entry["definition_sha256"] for entry in manifest["entries"])
    assert "renderer_version" not in manifest
    assert manifest["renderer_resources"]
    assert manifest["entity_renderer_resources"]

    config = tmp_path / "library" / "项目" / "cards" / "card.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# updated\n", encoding="utf-8")
    updated = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert updated[0]["config_sha256"] != entries[0]["config_sha256"]


def test_prewarm_stats_record_unchanged_manifest_skip(qapp, tmp_path, monkeypatch):
    from client.gui import prewarm

    _configs(tmp_path)
    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    calls = []
    monkeypatch.setattr(prewarm, "card_pixmap",
                        lambda *_args, **_kwargs: calls.append("card") or QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda *_args, **_kwargs: calls.append("entity") or QPixmap(2, 2))
    prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    calls.clear()
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert len(entries) == 2
    assert calls == []
    manifest = json.loads((tmp_path / "cache" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["stats"] == {"total": 2, "succeeded": 2, "failed": 0, "skipped": 2}


def test_prewarm_version_bump_does_not_invalidate_manifest(qapp, tmp_path, monkeypatch):
    from client.gui import prewarm

    _configs(tmp_path)
    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    calls = []
    monkeypatch.setattr(prewarm, "card_pixmap",
                        lambda *_args, **_kwargs: calls.append("card") or QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda *_args, **_kwargs: calls.append("entity") or QPixmap(2, 2))
    prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    manifest_path = tmp_path / "cache" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["renderer_version"] = "0.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls.clear()
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert len(entries) == 2
    assert calls == []


@pytest.mark.parametrize("null_pixmap", [False, True])
def test_prewarm_failure_summary_is_not_a_success_manifest(qapp, tmp_path, monkeypatch, null_pixmap):
    from client.gui import prewarm

    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    failed = {10010101}
    calls = []

    def render_card(cdef, _db, **kwargs):
        calls.append(("card", cdef.id, kwargs))
        if cdef.id in failed:
            return QPixmap() if null_pixmap else None
        return QPixmap(2, 2)

    monkeypatch.setattr(prewarm, "card_pixmap", render_card)
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda shiki, _db, **kwargs: calls.append(("entity", shiki.id, kwargs)) or QPixmap(2, 2))
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert [entry["id"] for entry in entries] == [100101]
    manifest_path = tmp_path / "cache" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [entry["id"] for entry in manifest["entries"]] == [100101]
    assert manifest["failures"] == [{
        "kind": "cards", "id": 10010101, "version": 20260720, "reason": "渲染返回空图",
    }]
    assert manifest["stats"] == {"total": 2, "succeeded": 1, "failed": 1, "skipped": 0}

    calls.clear()
    failed.clear()
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert len(entries) == 2
    assert any(call[:2] == ("card", 10010101) for call in calls)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["failures"] == []


def test_prewarm_retries_failed_real_cache_entries(qapp, tmp_path, monkeypatch):
    from client.gui import cardart

    db = F.db_of([F.shiki(100101)], [])
    calls = []

    def fail_once(kind):
        def render(*_args):
            calls.append(kind)
            return None if calls.count(kind) == 1 else QPixmap(2, 2)
        return render

    monkeypatch.setattr(cardart, "_render_card_pixmap", fail_once("card"))
    monkeypatch.setattr(cardart, "_render_entity_pixmap", fail_once("entity"))
    assert prewarm_all(db, tmp_path / "library", tmp_path / "cache") == []
    entries = prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    assert calls == ["card", "entity", "card", "entity"]
    assert len(entries) == 1


def test_prewarm_forwards_explicit_paths(qapp, tmp_path, monkeypatch):
    from client.gui import prewarm

    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    calls = []
    monkeypatch.setattr(prewarm, "card_pixmap",
                        lambda cdef, _db, **kwargs: calls.append(("card", cdef.id, kwargs)) or QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "entity_pixmap",
                        lambda shiki, _db, **kwargs: calls.append(("entity", shiki.id, kwargs)) or QPixmap(2, 2))
    prewarm_all(db, tmp_path / "library", tmp_path / "cache")
    for call in calls:
        kwargs = call[2]
        assert kwargs["library_dir"] == tmp_path / "library"
        assert kwargs["cache_dir"] == tmp_path / "cache"


def test_prewarm_iter_yields_progress_and_returns_entries(qapp, tmp_path, monkeypatch):
    from client.gui import prewarm

    db = F.db_of([F.shiki(100101)], [F.card(10010101)])
    monkeypatch.setattr(prewarm, "card_pixmap", lambda *_args, **_kwargs: QPixmap(2, 2))
    monkeypatch.setattr(prewarm, "entity_pixmap", lambda *_args, **_kwargs: QPixmap(2, 2))
    iterator = prewarm.prewarm_iter(db, tmp_path / "library", tmp_path / "cache")
    assert next(iterator) == (1, 2)
    assert next(iterator) == (2, 2)
    with pytest.raises(StopIteration) as stopped:
        next(iterator)
    assert [entry["id"] for entry in stopped.value.value] == [10010101, 100101]


def test_settings_status_displays_failure_stats(qapp, db, tmp_path):
    view = SettingsView(db)
    view.cache_dir = tmp_path
    failures = [{
        "kind": "cards", "id": 10010101 + offset,
        "version": 20260720, "reason": "渲染返回空图",
    } for offset in range(4)]
    (tmp_path / "manifest.json").write_text(json.dumps({
        "updated_at": "now",
        "entries": [{"id": 100101}, {"id": 100102}],
        "stats": {"total": 6, "succeeded": 2, "failed": 4, "skipped": 0},
        "failures": failures,
    }), encoding="utf-8")
    view.refresh_status()
    text = view.status_label.text()
    assert "成功 2 项" in text
    assert "失败 4 项" in text
    assert "跳过 0 项" in text
    assert "10010101" in text
    assert str(tmp_path / "manifest.json") in text
    assert text.count("渲染返回空图") == 3
    assert "10010104" not in text
    (tmp_path / "manifest.json").write_text(json.dumps({
        "updated_at": "old", "entries": [{"id": 100101}, {"id": 100102}],
    }), encoding="utf-8")
    view.refresh_status()
    assert view.status_label.text() == (
        f"卡图缓存：2 项\n最近合成：old\nManifest：{tmp_path / 'manifest.json'}")
    view.close()


def test_builder_loading_covers_only_card_area(qapp, db, tmp_path, monkeypatch):
    view = DeckBuilderView(db, store_path=tmp_path / "decks.json")
    events = []
    original_start = view._start_loading
    original_finish = view._finish_loading
    monkeypatch.setattr(
        view, "_start_loading",
        lambda *args: original_start(*args) or events.append(
            ("start", view.stack.isHidden(),
             view.loading_label.geometry() == view.card_area.geometry())))
    monkeypatch.setattr(view, "_finish_loading",
                        lambda: original_finish() or events.append(("finish", view.stack.isHidden())))
    view.new_deck()
    view.add_shikigami(F.TEAM[0])
    assert events[0] == ("start", False, True)
    assert events[-1] == ("finish", False)
    assert view.loading_label.isHidden()
    texts = []
    view.loading.on_text = texts.append
    view._render_cards()
    assert any("（1/" in text for text in texts)
    view.close()


def test_loading_blocks_user_input_and_overlay_tracks_parent_resize(qapp, monkeypatch):
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QWidget
    from client.gui.loading import LoadingIndicator, LoadingOverlay

    seen = []
    process_events = QApplication.processEvents
    monkeypatch.setattr(QApplication, "processEvents",
                        lambda flags=QEventLoop.AllEvents: seen.append(flags))
    indicator = LoadingIndicator("加载", lambda _text: None)
    indicator._running = True
    indicator.tick()
    assert seen == [QEventLoop.ExcludeUserInputEvents]

    parent = QWidget()
    parent.resize(500, 400)
    parent.show()
    overlay = LoadingOverlay(parent)
    overlay.show()
    parent.resize(640, 480)
    process_events()
    assert overlay.size() == parent.size()
    parent.close()


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


def test_startup_prewarm_runs_in_background_without_blocking(qapp, db, tmp_path, monkeypatch):
    consumed = []

    def fake_prewarm(db_arg):
        assert db_arg is db
        for current in range(1, 4):
            consumed.append(current)
            yield current, 3
        return ["done"]

    monkeypatch.setattr("client.gui.app.prewarm_iter", fake_prewarm, raising=False)
    monkeypatch.setattr("client.gui.app.prewarm_all",
                        lambda *_args, **_kwargs: pytest.fail("启动不应同步预热"), raising=False)
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.show()
    win.prewarm_resources()
    assert not win.loading_overlay.isVisible()
    assert win.statusBar().isVisible() or win._prewarm_timer.isActive()
    first_timer = win._prewarm_timer
    win.prewarm_resources()
    assert win._prewarm_timer is first_timer
    menu_button = next(button for button in win.stack.widget(0).findChildren(QPushButton)
                       if button.text().startswith("式神录\n"))

    for current in range(1, 4):
        qapp.processEvents()
        assert consumed == list(range(1, current + 1))
        assert win.statusBar().currentMessage() == f"卡图后台同步 {current}/3"
        if current == 1:
            menu_button.click()
            assert win.stack.currentWidget() is win.pages["codex"]

    qapp.processEvents()
    assert consumed == [1, 2, 3]
    assert not win._prewarm_timer.isActive()
    assert win._prewarm_iterator is None
    assert win.statusBar().currentMessage() == ""
    win.close()


def test_background_prewarm_blocks_manual_rebuild(qapp, db, tmp_path, monkeypatch):
    from client.gui import settings

    monkeypatch.setattr("client.gui.app.prewarm_iter",
                        lambda _db: iter([(1, 1)]), raising=False)
    monkeypatch.setattr("client.gui.app.prewarm_all",
                        lambda *_args, **_kwargs: pytest.fail("启动不应同步预热"), raising=False)
    calls = []
    monkeypatch.setattr(settings, "prewarm_all",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or [])
    monkeypatch.setattr(settings, "ask_confirmation",
                        lambda *_args: pytest.fail("后台预热时不应询问全量重建"))
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.prewarm_resources()
    first_timer = win._prewarm_timer
    win.go("settings")
    page = win.pages["settings"]
    page.rebuild()
    assert calls == []
    assert "后台预热进行中" in page.status_label.text()
    assert win._prewarm_timer is first_timer
    assert first_timer.isActive()
    win.close()


def test_background_prewarm_close_stops_timer(qapp, db, tmp_path, monkeypatch):
    monkeypatch.setattr("client.gui.app.prewarm_iter",
                        lambda _db: iter([(1, 1)]), raising=False)
    monkeypatch.setattr("client.gui.app.prewarm_all",
                        lambda *_args, **_kwargs: pytest.fail("启动不应同步预热"), raising=False)
    win = MainWindow(db=db, store_path=tmp_path / "decks.json")
    win.prewarm_resources()
    timer = win._prewarm_timer
    assert timer.isActive()
    win.close()
    assert not timer.isActive()
    assert win._prewarm_iterator is None


def test_settings_rebuild_when_background_idle(qapp, db, tmp_path, monkeypatch):
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
    assert len(calls) == 1
    assert calls[0][1]["clear"] is True
    assert page.rebuild_button.isEnabled()
    assert not page.loading_overlay.isVisible()
    win.close()
