"""BWPDIY 式神头像适配：懒加载外部渲染库，失败时回退为菱形占位。"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import yaml
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF


def bwpdiy_root() -> Path:
    """BWPDIY 仓库位置：可用 BWP_DIY_ROOT 覆盖，默认 BWPro 的同级目录。"""
    configured = os.environ.get("BWP_DIY_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "BWPDIY"


def _fallback_pixmap(name: str, faction: str, size: int) -> QPixmap:
    colors = {"红莲": "#a94a45", "苍叶": "#38847a", "青岚": "#467ba8", "紫岩": "#795c96"}
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    center = size / 2
    radius = size * 0.42
    polygon = QPolygonF([QPointF(center, center - radius), QPointF(center + radius, center),
                         QPointF(center, center + radius), QPointF(center - radius, center)])
    painter.setBrush(QColor(colors.get(faction, "#777777")))
    painter.setPen(QColor("#d9b96a"))
    painter.drawPolygon(polygon)
    painter.setPen(QColor("#fffbe9"))
    painter.drawText(polygon.boundingRect(), Qt.AlignCenter, name[:1])
    painter.end()
    return pixmap


def _artwork_ref(root: Path, sid: int, name: str) -> tuple[dict | None, int | None]:
    """在 BWPDIY 用户库中按 id/名称找式神首图；无匹配或图片缺失时返回空槽。"""
    for path in (root / "library").glob("*/shikigami/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if str(data.get("id", "")) != str(sid) and data.get("name") != name:
            continue
        images_dir = path.parent.parent / "images"
        artwork = data.get("artwork") if isinstance(data.get("artwork"), dict) else {}
        images = artwork.get("images") if isinstance(artwork, dict) else None
        first = images[0] if isinstance(images, list) and images else {}
        raw_path = first.get("path") if isinstance(first, dict) else None
        if not isinstance(raw_path, str) or not raw_path:
            raw_path = f"{data.get('id') or data.get('name', name)}.png"
        try:
            image_path = Path(raw_path)
            if not image_path.is_absolute():
                image_path = images_dir / image_path
            image_path = image_path.resolve(strict=True)
            image_path.relative_to(images_dir.resolve())
        except (OSError, ValueError):
            return None, data.get("faction_style")
        portrait = data.get("portrait") if isinstance(data.get("portrait"), dict) else {}
        ref = {"path": str(image_path)}
        for key, default in (("offset_x", 0), ("offset_y", 0), ("scale", 1.0), ("rotate", 0)):
            value = portrait.get(key, default)
            ref[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else default
        return ref, data.get("faction_style")
    return None, None


@lru_cache(maxsize=4)
def _renderer(root_text: str):
    root = Path(root_text)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from bwpdiy.render.assets import AssetLibrary
    from bwpdiy.render.duo import render_portrait
    from bwpdiy.render.layout import load_layouts

    assets = root / "assets"
    library = AssetLibrary(assets)
    element = load_layouts(assets)["协战"]["elements"]["duo_frame"]
    return root, library, element, render_portrait


@lru_cache(maxsize=256)
def _portrait_pixmap(sid: int, name: str, faction: str, root_text: str, size: int) -> QPixmap:
    try:
        root, library, element, render = _renderer(root_text)
        art, faction_style = _artwork_ref(root, sid, name)
        image = render(library, element, art, faction, scale=2,
                       faction_style=faction_style)
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("头像 PNG 解码失败")
    except Exception:
        # 外部仓库、Pillow、用户卡图或美术素材异常均不应阻断卡组构筑。
        return _fallback_pixmap(name, faction, size)
    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def shikigami_portrait(definition, size: int = 72, root: Path | None = None) -> QPixmap:
    """返回带斜方框与派系标的式神头像；root 仅供测试/嵌入方指定。"""
    root = root or bwpdiy_root()
    return _portrait_pixmap(definition.id, definition.name, definition.faction,
                            str(root.resolve()), size)
