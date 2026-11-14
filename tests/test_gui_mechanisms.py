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
        lambda name, _frame, text, _root, chars_per_line=None, font_scale=1.0, badge=None:
        rendered.append((name, text)) or QPixmap(360, 220))
    dialog = CardDetailDialog(cdef, db, runtime={"keywords": ["瞬发"]})
    # 默认 12 字/行只渲染一次，显示时整体缩放，顺序保持不变。
    assert [name for name, _text in rendered] == ["贯通", "瞬发", "连击"]
    assert rendered[1][1] == "每回合使用的第一张[[瞬发]]牌不消耗鬼火。"
    assert all(label.pixmap().width() == dialog.mechanism_panel.width()
               for label in dialog.mechanism_labels)
    dialog.close()


def test_card_detail_uses_native_art_and_aligned_scrollable_mechanisms(qapp, monkeypatch):
    mechanism_args = []
    art_calls = []

    def fake_mechanism_pixmap(_name, _frame, _text, _root, chars_per_line=None,
                              font_scale=1.0, badge=None):
        mechanism_args.append((chars_per_line, font_scale))
        return QPixmap(360, 220)

    def fake_card_pixmap(_cdef, _db, **kwargs):
        art_calls.append(kwargs)
        return QPixmap(263, 512)

    monkeypatch.setattr("client.gui.mechanisms._mechanism_pixmap", fake_mechanism_pixmap)
    monkeypatch.setattr("client.gui.widgets.card_pixmap", fake_card_pixmap)
    cdef = F.card(10010101, text="[瞬发][爆能2][贯通][连击][暴击][吸血]")
    db = F.db_of([F.shiki(100101)], [cdef])
    dialog = CardDetailDialog(cdef, db)
    assert dialog.detail_top.itemAt(0).widget() is dialog.card_widget
    assert dialog.detail_top.itemAt(1).widget() is dialog.mechanism_panel
    assert dialog.detail_top.spacing() == 12
    assert dialog.sizeHint().width() <= 640
    assert art_calls and all(call["height"] == 512 for call in art_calls)
    assert mechanism_args and all(args[0] == 12 and 0 < args[1] <= 1.0 for args in mechanism_args)
    assert dialog.minimumHeight() >= 680
    dialog.resize(1000, 800)
    dialog.show()
    qapp.processEvents()
    assert dialog.card_widget.height() >= 500
    assert dialog.card_widget.width() == dialog.mechanism_panel.width()
    assert dialog.card_widget.art_width == 263
    displayed = dialog.card_widget.art_label.pixmap()
    assert displayed.width() / displayed.height() == pytest.approx(263 / 512)
    assert dialog.mechanism_panel.maximumHeight() == 512
    assert dialog.mechanism_panel.height() == 512  # 与大卡图底部对齐
    assert dialog.mechanism_panel.alignment() == (Qt.AlignLeft | Qt.AlignTop)
    assert dialog.mechanism_panel.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.mechanism_panel.verticalScrollBar().maximum() > 0
    assert dialog.mechanism_panel.verticalScrollBar().value() == 0
    assert dialog.mechanism_panel.y() == dialog.card_widget.y()
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
    assert dialog.main_art_pixmap.height() == 512
    assert dialog.mechanism_panel is not None
    assert dialog.mechanism_panel.maximumHeight() == 512
    assert dialog.status_panel.maximumHeight() == 512
    assert len(dialog.mechanism_labels) == 1
    assert all(not label.pixmap().isNull() for label in dialog.mechanism_labels)
    assert any("测试灵咒说明。" in item["text"] for item in dialog.status_mechanisms)
    dialog.close()


def test_shikigami_mechanism_columns_stay_top_aligned_and_scroll(qapp):
    from types import SimpleNamespace

    db = F.base_db()
    game = F.mk_game(db)
    shiki = game.current.shikigami[0]
    shiki.keywords.append("haste")
    for index in range(8):
        name = f"测试灵咒{index}"
        shiki.invocations.append({"name": name, "source": None, "player": 0})
        db.invocations[name] = SimpleNamespace(text="超长机制说明。" * 20)
    dialog = ShikigamiDetailDialog(game, Ref(player=0, shikigami=0), 0)
    dialog.show()
    qapp.processEvents()
    for panel in (dialog.status_panel, dialog.mechanism_panel):
        assert panel.alignment() == (Qt.AlignLeft | Qt.AlignTop)
        assert panel.y() == dialog.main_art_label.y()
        assert panel.height() <= 512
        assert panel.verticalScrollBar().value() == 0
        assert panel.widget().layout().alignment() == (Qt.AlignLeft | Qt.AlignTop)
    assert dialog.status_panel.verticalScrollBar().maximum() > 0
    dialog.close()


def test_shiki_detail_counter_suffixes(qapp):
    from client.gui.details import shiki_detail_suffix

    db = F.base_db()
    game = F.mk_game(db)
    ref = Ref(player=0, shikigami=0)
    game.current.shikigami[0].id = 100117
    assert shiki_detail_suffix(game, ref) == "（本局游戏已投出0次6点）"
    game.current.ext["dice_six_count"] = 3
    assert shiki_detail_suffix(game, ref) == "（本局游戏已投出3次6点）"
    game.current.shikigami[0].id = 100404
    assert shiki_detail_suffix(game, ref) == "（本局游戏已完成0次委托）"
    game.current.quest_counts["quest_used"] = 2
    assert shiki_detail_suffix(game, ref) == "（本局游戏已完成2次委托）"
    game.current.shikigami[0].id = 100101
    assert shiki_detail_suffix(game, ref) == ""


def test_shiki_detail_counter_suffix_passed_to_base_and_awakened_art(qapp, monkeypatch):
    art_calls = []

    def fake_shikigami_pixmap(_shiki, _db, **kwargs):
        art_calls.append(kwargs)
        return QPixmap(360, 512)

    monkeypatch.setattr("client.gui.details.shikigami_pixmap", fake_shikigami_pixmap)
    for shiki_id, counter_key, expected in (
        (100117, "dice_six_count", "（本局游戏已投出3次6点）"),
        (100404, "quest_used", "（本局游戏已完成2次委托）"),
    ):
        db = F.base_db()
        db.shikigami[shiki_id] = F.shiki(shiki_id)
        awaken_id = shiki_id * 100 + 8
        db.cards[awaken_id] = F.card(awaken_id, shikigami=shiki_id, subtype="awaken")
        game = F.mk_game(db)
        shiki = game.current.shikigami[0]
        shiki.id = shiki_id
        if counter_key == "dice_six_count":
            game.current.ext[counter_key] = 3
        else:
            game.current.quest_counts[counter_key] = 2
        for awakened in (None, awaken_id):
            shiki.awakened = awakened
            dialog = ShikigamiDetailDialog(game, Ref(player=0, shikigami=0), 0)
            assert art_calls[-1]["description_suffix"] == expected
            dialog.close()


def test_shikigami_counter_suffix_enters_payload_and_cache_key(qapp, tmp_path, monkeypatch):
    import json
    from client.gui import cardart

    db = F.base_db()
    game = F.mk_game(db)
    rendered = []

    def capture(cache_key, payload_json, _layout_json, _root, *_size_args):
        rendered.append((cache_key, json.loads(payload_json)))
        return QPixmap(10, 10)

    monkeypatch.setattr(cardart, "_cached_runtime_card_pixmap", capture)
    for suffix in ("（计数1）", "（计数2）"):
        cardart.shikigami_pixmap(
            game.current.shikigami[0], db, library_dir=tmp_path / "empty",
            cache_dir=tmp_path / "cache", description_suffix=suffix)
    assert [payload["description"] for _key, payload in rendered] == [
        "（计数1）", "（计数2）",
    ]
    assert rendered[0][0] != rendered[1][0]


def test_render_failure_log_dedup_clear_and_context(tmp_path, caplog):
    import logging
    from client.gui.renderlog import clear_render_log_dedup, log_render_failure

    root = tmp_path / "BWPDIY"
    config_path = tmp_path / "card.yaml"
    clear_render_log_dedup()
    try:
        with caplog.at_level(logging.ERROR, logger="client.gui.renderlog"):
            try:
                raise RuntimeError("render broke")
            except RuntimeError as error:
                assert log_render_failure("card", 10010101, root, error, config_path) is True
                assert log_render_failure("card", 10010101, root, error, config_path) is False
                assert log_render_failure("card", 10010102, root, error, config_path) is True
        assert len(caplog.records) == 2
        for expected in ("kind=card", "id=10010101", f"root={root}", f"config={config_path}"):
            assert expected in caplog.text

        clear_render_log_dedup()
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="client.gui.renderlog"):
            try:
                raise RuntimeError("render broke")
            except RuntimeError as error:
                assert log_render_failure("card", 10010101, root, error, config_path) is True
        assert len(caplog.records) == 1
    finally:
        clear_render_log_dedup()


def test_render_failure_log_dedup_is_bounded(tmp_path, caplog):
    import logging
    from client.gui.renderlog import clear_render_log_dedup, log_render_failure

    clear_render_log_dedup()
    try:
        with caplog.at_level(logging.ERROR, logger="client.gui.renderlog"):
            for entity in range(128):
                assert log_render_failure("card", entity, tmp_path, RuntimeError("bad")) is True
            assert log_render_failure("card", 0, tmp_path, RuntimeError("bad")) is False
            assert log_render_failure("card", 128, tmp_path, RuntimeError("bad")) is True
            assert log_render_failure("card", 0, tmp_path, RuntimeError("bad")) is True
        assert len(caplog.records) == 130
    finally:
        clear_render_log_dedup()


def test_mechanisms_render_failure_log_returns_none(tmp_path, caplog, monkeypatch):
    import logging
    from client.gui import mechanisms
    from client.gui.renderlog import clear_render_log_dedup

    def fail_renderer(_root):
        raise RuntimeError("renderer missing")

    root = tmp_path / "BWPDIY"
    monkeypatch.setattr(mechanisms, "_renderer", fail_renderer)
    clear_render_log_dedup()
    try:
        with caplog.at_level(logging.ERROR, logger="client.gui.renderlog"):
            assert mechanisms._mechanism_pixmap("测试", "skill", "说明", str(root)) is None
        assert f"kind=mechanism id=测试 root={root} config=-" in caplog.text
    finally:
        clear_render_log_dedup()


def test_mechanisms_badge_enters_render_and_lru(qapp, tmp_path, monkeypatch):
    from PIL import Image
    from client.gui import mechanisms
    mechanisms._renderer(str(mechanisms.bwpdiy_root()))  # 独立分片运行时先注册本地渲染包
    from bwpdiy.render import layout, mech

    seen = []
    monkeypatch.setattr(mechanisms, "_renderer", lambda _root: (tmp_path, None, None))
    monkeypatch.setattr(layout, "load_layouts", lambda _assets: {"机制": None})

    def render(mechanism, _assets, **_kwargs):
        seen.append(mechanism)
        return Image.new("RGBA", (16, 16), "#336699")

    monkeypatch.setattr(mech, "render_mechanism", render)
    mechanisms._mechanism_pixmap.cache_clear()
    args = ("测试", "skill", "说明", str(tmp_path))
    first = mechanisms._mechanism_pixmap(*args, badge="blue")
    second = mechanisms._mechanism_pixmap(*args, badge="gold")
    assert first is not None and not first.isNull()
    assert second is not None and not second.isNull()
    assert [mechanism["badge"] for mechanism in seen] == ["blue", "gold"]
    mechanisms._mechanism_pixmap.cache_clear()
