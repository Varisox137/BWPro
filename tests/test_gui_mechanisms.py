"""详情弹窗的关键字/机制框渲染测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from client.gui.details import ShikigamiDetailDialog
from client.gui.widgets import CardDetailDialog
from core.model import Ref
from tests import factories as F


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_card_detail_renders_keyword_mechanisms(qapp):
    from client.gui.mechanisms import card_mechanisms

    cdef = F.card(10010101, text="[瞬发]。可以选择[爆能2]使用。")
    db = F.db_of([F.shiki(100101)], [cdef])
    mechanisms = card_mechanisms(cdef, runtime={"keywords": ["瞬发"]})
    assert [mechanism["name"] for mechanism in mechanisms] == ["瞬发", "爆能"]
    dialog = CardDetailDialog(cdef, db, runtime={"keywords": ["瞬发"]})
    assert dialog.mechanism_panel is not None
    assert len(dialog.mechanism_labels) == 2
    assert all(not label.pixmap().isNull() for label in dialog.mechanism_labels)
    dialog.close()


def test_card_mechanisms_use_yaml_text_and_first_occurrence_order(qapp, monkeypatch):
    from client.gui.mechanisms import card_mechanisms

    cdef = F.card(10010101, text="[贯通][瞬发][贯通][连击]")
    db = F.db_of([F.shiki(100101)], [cdef])
    mechanisms = card_mechanisms(cdef, runtime={"keywords": ["瞬发"]})
    assert [item["name"] for item in mechanisms] == ["贯通", "瞬发", "连击"]
    assert mechanisms[1]["text"] == "每回合使用的第一张[[瞬发]]牌不消耗鬼火。"
    assert mechanisms[0]["frame"] == "skill"
    assert mechanisms[0]["badge"] is None
    assert mechanisms[0]["version_date"] == "20191212"

    rendered = []
    monkeypatch.setattr(
        "client.gui.mechanisms._mechanism_pixmap",
        lambda name, _frame, text, _root, chars_per_line=None, font_scale=1.0:
        rendered.append((name, text)) or QPixmap(360, 220))
    dialog = CardDetailDialog(cdef, db, runtime={"keywords": ["瞬发"]})
    assert [name for name, _text in rendered] == ["贯通", "瞬发", "连击"]
    assert rendered[1][1] == "每回合使用的第一张[[瞬发]]牌不消耗鬼火。"
    dialog.close()


def test_card_detail_places_card_and_scrollable_mechanisms_side_by_side(qapp, monkeypatch):
    seen = []

    def fake_pixmap(_name, _frame, _text, _root, chars_per_line=None, font_scale=1.0):
        seen.append((chars_per_line, font_scale))
        return QPixmap(360, 220)

    monkeypatch.setattr("client.gui.mechanisms._mechanism_pixmap", fake_pixmap)
    cdef = F.card(10010101, text="[瞬发][爆能2][贯通][连击][暴击][吸血]")
    db = F.db_of([F.shiki(100101)], [cdef])
    dialog = CardDetailDialog(cdef, db)
    assert dialog.detail_top.itemAt(0).widget() is dialog.card_widget
    assert dialog.detail_top.itemAt(1).widget() is dialog.mechanism_panel
    assert seen and all(args == (15, 0.85) for args in seen)
    dialog.resize(1000, 800)
    dialog.show()
    qapp.processEvents()
    assert dialog.card_widget.width() >= 400
    assert dialog.card_widget.height() >= 500
    assert dialog.mechanism_panel.maximumHeight() <= dialog.card_widget.height() * 1.2
    assert dialog.mechanism_panel.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.mechanism_panel.verticalScrollBar().maximum() > 0
    dialog.close()


def test_shikigami_detail_renders_runtime_keyword_and_invocation(qapp):
    db = F.base_db()
    game = F.mk_game(db)
    shiki = game.current.shikigami[0]
    shiki.keywords.append("haste")
    shiki.invocations.append({"name": "测试灵咒", "source": None, "player": 0})
    from types import SimpleNamespace
    db.invocations["测试灵咒"] = SimpleNamespace(text="测试灵咒说明。")
    dialog = ShikigamiDetailDialog(game, Ref(player=0, shikigami=0), 0)
    assert dialog.mechanism_panel is not None
    assert len(dialog.mechanism_labels) == 1
    assert all(not label.pixmap().isNull() for label in dialog.mechanism_labels)
    assert any("测试灵咒说明。" in item["text"] for item in dialog.status_mechanisms)
    dialog.close()
