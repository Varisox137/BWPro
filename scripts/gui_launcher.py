"""BWPro 独立 exe 入口；--smoke-test 用于验证冻结资源与真实渲染管线。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _smoke_test() -> int:
    from PySide6.QtWidgets import QApplication

    from client.gui import mechanisms
    from client.gui.app import MainWindow
    from client.gui.cardart import card_pixmap, entity_pixmap
    from client.gui.portrait import (
        bwpdiy_root, library_root, shikigami_portrait,
    )
    from core.logging_config import configure_logging
    from core.model import ShikigamiState
    from db.loader import CardDatabase

    configure_logging("gui-smoke")
    app = QApplication([])
    db = CardDatabase.load()
    root = bwpdiy_root()
    assert (root / "assets" / "frames").is_dir(), root
    assert (root / "assets" / "levels" / "base.png").is_file(), root
    assert library_root().is_dir(), library_root()
    assert db.cards and db.shikigami

    card = db.cards[min(db.cards)]
    pixmap = card_pixmap(card, db, height=128)
    assert pixmap is not None and not pixmap.isNull(), "大卡渲染失败"
    definition = db.shikigami[min(db.shikigami)]
    portrait = shikigami_portrait(definition, size=64)
    assert portrait is not None and not portrait.isNull(), "头像渲染失败"
    shiki = ShikigamiState(
        id=definition.id, faction=definition.faction, perm_faction=definition.faction,
        level=1, home_slot=0, base_power=definition.power,
        base_health=definition.health, health=definition.health,
    )
    entity = entity_pixmap(shiki, db, seat=0, height=210)
    assert entity is not None and not entity.isNull(), "式神小卡渲染失败"
    mechanism = mechanisms._mechanism_pixmap(
        "测试", "skill", "冻结资源冒烟测试", str(root.resolve()))
    assert mechanism is not None and not mechanism.isNull(), "机制框渲染失败"

    window = MainWindow(db=db)
    assert not window.windowIcon().isNull(), "窗口图标加载失败"
    window.show()
    app.processEvents()
    window.close()
    app.processEvents()
    print(f"独立 exe 冒烟通过：{len(db.shikigami)} 式神，{len(db.cards)} 卡；资源根 {root}")
    return 0


def main() -> int:
    if "--smoke-test" in sys.argv:
        return _smoke_test()
    from client.gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
