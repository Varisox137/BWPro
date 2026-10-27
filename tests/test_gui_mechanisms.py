"""详情弹窗的关键字/机制框渲染测试（QT_QPA_PLATFORM=offscreen）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
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
    assert len(dialog.mechanism_labels) == 2
    assert all(not label.pixmap().isNull() for label in dialog.mechanism_labels)
    dialog.close()
