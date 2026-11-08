"""卡牌本机外观偏好、牌框切换与紧凑选择弹窗测试。"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from client.gui.card_appearance import (
    card_appearance, load_card_appearances, save_card_appearance,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_appearance_store_is_sparse_and_validated(tmp_path):
    path = tmp_path / "appearance.json"
    save_card_appearance(10010101, "blue", path=path)
    assert card_appearance(10010101, path) == {"frame_variant": "blue", "art_index": 0}
    assert json.loads(path.read_text(encoding="utf-8"))["cards"] == {
        "10010101": {"frame_variant": "blue", "art_index": 0},
    }
    save_card_appearance(10010101, "norm", path=path)
    assert load_card_appearances(path) == {}
    with pytest.raises(ValueError):
        save_card_appearance(10010101, "gold", path=path)
    with pytest.raises(ValueError):
        save_card_appearance(10010101, "blue", art_index=1, path=path)


def test_appearance_store_ignores_corrupt_and_invalid_entries(tmp_path):
    path = tmp_path / "appearance.json"
    path.write_text("not json", encoding="utf-8")
    assert load_card_appearances(path) == {}
    path.write_text(json.dumps({"version": 1, "cards": {
        "10010101": {"frame_variant": "gold", "art_index": 0},
        "10010102": {"frame_variant": "red", "art_index": 1},
        "10010103": {"frame_variant": "black", "art_index": 0},
        "10010104": {"frame_variant": [], "art_index": 0},
    }}), encoding="utf-8")
    assert load_card_appearances(path) == {
        "10010103": {"frame_variant": "black", "art_index": 0},
    }
    assert card_appearance(10010101, path) == {"frame_variant": "norm", "art_index": 0}


def test_cardart_uses_current_appearance_for_payload_and_layout(
        qapp, tmp_path, monkeypatch):
    from PIL import Image
    import yaml
    from client.gui import cardart
    from tests import factories

    cdef = factories.card(10010101)
    database = factories.db_of([factories.shiki(100101)], [cdef])
    library_dir = tmp_path / "library"
    cards_dir = library_dir / "项目" / "cards"
    images_dir = library_dir / "项目" / "images"
    cards_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    Image.new("RGBA", (8, 8), "#336699").save(images_dir / "art.png")
    config_path = cards_dir / f"{cdef.id}@{cdef.version}.yaml"
    config_path.write_text(yaml.safe_dump({
        "id": str(cdef.id), "name": cdef.name, "version_date": str(cdef.version),
        "frame_variant": "norm", "artwork": {"images": [{"path": "art.png"}]},
    }), encoding="utf-8")
    monkeypatch.setattr(cardart, "card_appearance",
                        lambda _card_id: {"frame_variant": "black", "art_index": 0})
    seen = {}
    monkeypatch.setattr(cardart, "_cached_card_pixmap",
                        lambda _key, payload, layout, *_args, **_kwargs: seen.update(
                            payload=json.loads(payload), layout=json.loads(layout)))
    cardart.card_pixmap(cdef, database, library_dir=library_dir,
                        cache_dir=tmp_path / "cache")
    assert seen["payload"]["frame_variant"] == "black"
    assert "frame_variants" not in seen["layout"]
    cardart.card_pixmap(cdef, database, library_dir=library_dir,
                        cache_dir=tmp_path / "cache", frame_variant="red")
    assert seen["payload"]["frame_variant"] == "red"


def test_prewarm_tracks_only_selected_appearance(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from PIL import Image
    import yaml
    from client.gui import prewarm
    from tests import factories

    cdef = factories.card(10010101)
    database = factories.db_of([factories.shiki(100101)], [cdef])
    library_dir = tmp_path / "library"
    cards_dir = library_dir / "项目" / "cards"
    images_dir = library_dir / "项目" / "images"
    cards_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    Image.new("RGBA", (8, 8), "#336699").save(images_dir / "art.png")
    (cards_dir / f"{cdef.id}@{cdef.version}.yaml").write_text(yaml.safe_dump({
        "id": str(cdef.id), "name": cdef.name, "version_date": str(cdef.version),
        "artwork": {"images": [{"path": "art.png"}]},
    }), encoding="utf-8")
    monkeypatch.setattr(prewarm.cardart, "_renderer",
                        lambda root: (Path(root), None, None))
    monkeypatch.setattr(prewarm.cardart, "_card_renderer_resources", lambda *_args: "card")
    monkeypatch.setattr(prewarm.cardart, "_entity_renderer_resources", lambda *_args: "entity")
    monkeypatch.setattr(prewarm, "card_appearance",
                        lambda _card_id: {"frame_variant": "red", "art_index": 0})
    calls = []
    monkeypatch.setattr(prewarm, "card_pixmap",
                        lambda definition, *_args, **_kwargs: (
                            calls.append(definition.id) or SimpleNamespace(isNull=lambda: False)))
    cache_dir = tmp_path / "cache"
    list(prewarm.prewarm_iter(database, library_dir=library_dir, cache_dir=cache_dir))
    manifest = json.loads((cache_dir / prewarm.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert calls == [cdef.id]
    assert manifest["entries"][0]["appearance"] == {"frame_variant": "red", "art_index": 0}


def test_card_widget_passes_frame_variant_override(qapp, db, monkeypatch):
    from client.gui.widgets import CardWidget

    seen = {}
    monkeypatch.setattr("client.gui.widgets.card_pixmap",
                        lambda *_args, **kwargs: seen.update(kwargs))
    widget = CardWidget(db.cards[10010101], db=db, frame_variant="red")
    assert seen["frame_variant"] == "red"
    widget.close()


def test_appearance_dialog_selects_original_and_saves_only_on_confirm(
        qapp, db, monkeypatch):
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QDialog
    from client.gui.appearance import CardAppearanceDialog

    monkeypatch.setattr("client.gui.widgets.card_pixmap",
                        lambda *_args, **_kwargs: QPixmap(263, 512))
    monkeypatch.setattr("client.gui.appearance.card_appearance",
                        lambda _card_id: {"frame_variant": "norm", "art_index": 0})
    saved = []
    monkeypatch.setattr("client.gui.appearance.save_card_appearance",
                        lambda *args, **kwargs: saved.append((args, kwargs)))
    dialog = CardAppearanceDialog(db.cards[10010101], db)
    assert dialog.selected_frame == "norm"
    assert dialog.choice_view.option_buttons[0].isHidden()
    previous = dialog.choice_view
    dialog.select_frame("blue")
    assert dialog.selected_frame == "blue"
    assert dialog.choice_view is not previous
    assert dialog.choice_view.option_widgets[0]._art_options["frame_variant"] == "blue"
    assert saved == []
    dialog.choice_view.select(0)
    assert not dialog.choice_view.option_buttons[0].isHidden()
    assert dialog.choice_view.option_buttons[0].text() == "确认"
    dialog.choice_view.confirm()
    assert saved == [((10010101, "blue"), {})]
    assert dialog.result() == QDialog.Accepted
    dialog.close()

    cancelled = CardAppearanceDialog(db.cards[10010101], db)
    cancelled.select_frame("red")
    cancelled.choice_view.select(0)
    cancelled.reject()
    assert len(saved) == 1
    cancelled.close()


def test_codex_left_click_appearance_and_right_click_detail(qapp, db, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from client.gui.codex import ShikigamiCodexView

    view = ShikigamiCodexView(db)
    view.show_shikigami_cards()
    opened = []

    class Appearance:
        def __init__(self, cdef, *_args):
            self.cdef = cdef

        def exec(self):
            opened.append(("appearance", self.cdef))
            return QDialog.Accepted

    class Detail:
        def __init__(self, cdef, *_args):
            self.cdef = cdef

        def exec(self):
            opened.append(("detail", self.cdef))
            return QDialog.Rejected

    monkeypatch.setattr("client.gui.codex.CardAppearanceDialog", Appearance)
    monkeypatch.setattr("client.gui.codex.CardDetailDialog", Detail)
    widget = view.card_widgets[0]
    widget.clicked.emit(widget.cdef)
    widget.detail_clicked.emit(widget.cdef)
    assert opened == [("appearance", widget.cdef), ("detail", widget.cdef)]
    view.close()


def test_choice_selection_layout_has_no_yellow_glow(qapp, db, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from client.gui.widgets import CardChoiceView

    monkeypatch.setattr("client.gui.widgets.card_pixmap",
                        lambda *_args, **_kwargs: QPixmap(263, 512))
    view = CardChoiceView([
        (0, db.cards[10010101], "一"), (1, db.cards[10010102], "二"),
    ], db=db)
    view.select(0)
    assert view.option_widgets[0].height() > view.option_widgets[1].height()
    assert not view.option_buttons[0].isHidden()
    assert view.option_buttons[1].isHidden()
    assert not isinstance(view._wrappers[0].graphicsEffect(), QGraphicsDropShadowEffect)
    assert view._wrappers[0].layout().spacing() <= 4
    assert view.minimumHeight() >= 475
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    view.close()
