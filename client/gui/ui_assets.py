"""对局 UI 素材加载、骰子裁面与轻量本地设置。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPixmap, QTransform

from client.gui.portrait import bwpdiy_root

DEFAULT_CARDBACK = "月明风清"
_HASH_NAME = re.compile(r"[0-9a-fA-F]{6,}")
# black_open.png 的实际面边界：中央、上、左、右下、下、右上。
_DICE_RECTS = {
    1: (171, 171), 2: (171, 0), 3: (0, 171),
    4: (340, 171), 5: (171, 340), 6: (340, 0),
}


def assets_root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else bwpdiy_root() / "assets"


@lru_cache(maxsize=256)
def _cached_pixmap(path: str, mtime_ns: int) -> QPixmap:
    del mtime_ns
    return QPixmap(path)


def ui_pixmap(relative: str, *, root: Path | None = None) -> QPixmap:
    path = assets_root(root) / relative
    if not path.is_file():
        return QPixmap()
    return _cached_pixmap(str(path), path.stat().st_mtime_ns)


def dice_face(value: int, *, root: Path | None = None) -> QPixmap:
    if value not in _DICE_RECTS:
        raise ValueError(f"骰点必须为 1–6：{value}")
    unfolded = ui_pixmap("dice/black_open.png", root=root)
    if unfolded.isNull():
        return QPixmap()
    side = min(unfolded.width(), unfolded.height()) // 4
    x, y = _DICE_RECTS[value]
    return unfolded.copy(QRect(x, y, side, side))


def named_cardbacks(root: Path | None = None) -> list[str]:
    directory = Path(root) if root is not None else assets_root() / "cardbacks"
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.png")
                  if not _HASH_NAME.fullmatch(path.stem))


def gui_settings_path() -> Path:
    return Path.home() / ".bwpro" / "gui.json"


def load_gui_settings(path: Path | None = None) -> dict[str, str]:
    path = path or gui_settings_path()
    settings = {"own_cardback": DEFAULT_CARDBACK, "enemy_cardback": DEFAULT_CARDBACK}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return settings
    for key in settings:
        value = stored.get(key) if isinstance(stored, dict) else None
        if isinstance(value, str) and value:
            settings[key] = value
    return settings


def save_gui_settings(settings: dict[str, str], path: Path | None = None) -> None:
    path = path or gui_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_gui_settings(path)
    for key in current:
        value = settings.get(key)
        if isinstance(value, str) and value:
            current[key] = value
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def turn_pixmap(own_turn: bool, theme: str, *, root: Path | None = None) -> QPixmap:
    name = "your_turn" if own_turn else "opponent_turn"
    suffix = "dark" if theme == "light" else "light"
    return ui_pixmap(f"misc/{name}_{suffix}.png", root=root)


@lru_cache(maxsize=16)
def _cached_cardback(path: str, mtime_ns: int, landscape: bool) -> QPixmap:
    del mtime_ns
    pixmap = QPixmap(path)
    with Image.open(path) as image:
        bbox = image.convert("RGBA").getchannel("A").getbbox()
    if bbox:
        left, top, right, bottom = bbox
        pixmap = pixmap.copy(QRect(left, top, right - left, bottom - top))
    if landscape:
        pixmap = pixmap.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
    return pixmap


def cardback_pixmap(side: str, *, root: Path | None = None,
                    landscape: bool = False) -> QPixmap:
    settings = load_gui_settings()
    key = "own_cardback" if side == "own" else "enemy_cardback"
    path = assets_root(root) / "cardbacks" / f"{settings[key]}.png"
    if not path.is_file():
        path = assets_root(root) / "cardbacks" / f"{DEFAULT_CARDBACK}.png"
    return _cached_cardback(str(path), path.stat().st_mtime_ns, landscape)
