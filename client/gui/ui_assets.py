"""对局 UI 素材加载、骰子裁面与轻量本地设置。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QPixmap, QTransform

from client.gui.portrait import bwpdiy_root

DEFAULT_CARDBACK = "月明风清"
_HASH_NAME = re.compile(r"[0-9a-fA-F]{6,}")
# black_1.png 至 black_6.png 均为 128×128 完整骰面，共用同一透明边距和圆角框。
# 展开图仅作为资源缺失时的兼容回退。
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
    face = ui_pixmap(f"dice/black_{value}.png", root=root)
    if not face.isNull():
        return face
    unfolded = ui_pixmap("dice/black_open.png", root=root)
    if unfolded.isNull():
        return QPixmap()
    x, y = _DICE_RECTS[value]
    return unfolded.copy(QRect(x, y, 170, 170)).scaled(
        128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)


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
    settings = {
        "own_cardback": DEFAULT_CARDBACK, "enemy_cardback": DEFAULT_CARDBACK,
        "end_turn_background": "", "opponent_turn_background": "", "turn_background": "",
        "end_turn_variant": "golden", "opponent_turn_variant": "golden",
        "defeated_variant": "white", "upgrade_variant": "yellow",
    }
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return settings
    for key in settings:
        value = stored.get(key) if isinstance(stored, dict) else None
        if isinstance(value, str):
            settings[key] = value
    return settings


def save_gui_settings(settings: dict[str, str], path: Path | None = None) -> None:
    path = path or gui_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_gui_settings(path)
    for key in current:
        value = settings.get(key)
        if isinstance(value, str):
            current[key] = value
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def turn_pixmap(own_turn: bool, theme: str, *, root: Path | None = None) -> QPixmap:
    name = "your_turn" if own_turn else "opponent_turn"
    suffix = "dark" if theme == "light" else "light"
    return ui_pixmap(f"animations/{name}_{suffix}.png", root=root)


def unnamed_misc_images(root: Path | None = None) -> list[str]:
    directory = Path(root) if root is not None else assets_root() / "turn_buttons"
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.png")
                  if re.fullmatch(r"[0-9a-fA-F]{8}", path.stem))


def turn_button_variants(opponent: bool = False, root: Path | None = None) -> list[str]:
    directory = Path(root) if root is not None else assets_root() / "turn_buttons"
    prefix = "opponent_turn_button_" if opponent else "end_turn_button_"
    if not directory.is_dir():
        return []
    return sorted(path.stem[len(prefix):] for path in directory.glob(f"{prefix}*.png"))


def animation_variants(prefix: str, root: Path | None = None) -> list[str]:
    directory = Path(root) if root is not None else assets_root() / "animations"
    if not directory.is_dir():
        return []
    return sorted(path.stem[len(prefix) + 1:] for path in directory.glob(f"{prefix}_*.png"))


def end_turn_button_pixmap(size: int, opponent: bool = False, *,
                           root: Path | None = None) -> QPixmap:
    """合成双方回合按钮；默认无底图，所选十六进制图片置于 golden 字样下。"""
    size = max(1, int(size))
    prefix = "opponent_turn_button_" if opponent else "end_turn_button_"
    key = "opponent_turn_background" if opponent else "end_turn_background"
    variant_key = "opponent_turn_variant" if opponent else "end_turn_variant"
    settings = load_gui_settings()
    selected = settings["turn_background"] or settings[key]
    variant = settings[variant_key] or "golden"
    word = ui_pixmap(f"turn_buttons/{prefix}{variant}.png", root=root)
    if word.isNull():
        word = ui_pixmap(f"turn_buttons/{prefix}golden.png", root=root)
    if not re.fullmatch(r"[0-9a-fA-F]{8}", selected):
        return word.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    background = ui_pixmap(f"turn_buttons/{selected}.png", root=root)
    if background.isNull() or word.isNull():
        return word.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    background = background.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    word = word.scaled(
        round(size * 0.88), round(size * 0.88), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter.drawPixmap((size - background.width()) // 2,
                       (size - background.height()) // 2, background)
    painter.drawPixmap((size - word.width()) // 2, (size - word.height()) // 2, word)
    painter.end()
    return result


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


def heal_number_pixmap(amount: int, *, root: Path | None = None) -> QPixmap:
    """用 BWPDIY 数字素材拼接居中的治疗量（含加号，支持多位数）。"""
    amount = max(0, int(amount))
    names = ["heal_plus"] + [f"heal_{digit}" for digit in str(amount)]
    pixmaps = [ui_pixmap(f"numbers/{name}.png", root=root) for name in names]
    if any(pixmap.isNull() for pixmap in pixmaps):
        return QPixmap()
    width = sum(pixmap.width() for pixmap in pixmaps) + 2 * (len(pixmaps) - 1)
    height = max(pixmap.height() for pixmap in pixmaps)
    result = QPixmap(width, height)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    x = 0
    for pixmap in pixmaps:
        painter.drawPixmap(x, (height - pixmap.height()) // 2, pixmap)
        x += pixmap.width() + 2
    painter.end()
    return result


def damage_number_pixmap(amount: int, max_width: int | None = None, *,
                         root: Path | None = None) -> QPixmap:
    """用伤害素材拼接减号与多位数字，并按墨色背景限制整体宽度。"""
    amount = max(0, int(amount))
    names = ["damage_minus"] + [f"damage_{digit}" for digit in str(amount)]
    pixmaps = [ui_pixmap(f"numbers/{name}.png", root=root) for name in names]
    if any(pixmap.isNull() for pixmap in pixmaps):
        return QPixmap()
    width = sum(pixmap.width() for pixmap in pixmaps) + 2 * (len(pixmaps) - 1)
    height = max(pixmap.height() for pixmap in pixmaps)
    result = QPixmap(width, height)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    x = 0
    for pixmap in pixmaps:
        painter.drawPixmap(x, (height - pixmap.height()) // 2, pixmap)
        x += pixmap.width() + 2
    painter.end()
    if max_width is not None and result.width() > max_width:
        return result.scaledToWidth(max_width, Qt.SmoothTransformation)
    return result
