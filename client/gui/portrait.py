"""BWPDIY 式神头像适配：懒加载外部渲染库，失败时回退为菱形占位。"""
from __future__ import annotations

import hashlib
import json
import math
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


def library_root() -> Path:
    """项目卡图配置库：可用 BWP_DIY_LIBRARY 覆盖。"""
    configured = os.environ.get("BWP_DIY_LIBRARY")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "library"


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


MAX_YAML_BYTES = 256 * 1024
MAX_RENDER_PIXELS = 16_000_000


def _config_fingerprint(root: Path) -> tuple:
    paths = sorted(root.glob("*/shikigami/*.yaml")) + sorted(root.glob("*/cards/*.yaml"))
    fingerprint = []
    for path in paths:
        try:
            stat = path.stat()
            contents = path.read_bytes()
        except OSError:
            continue
        fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size,
                            hashlib.sha256(contents).hexdigest()))
    return tuple(fingerprint)


@lru_cache(maxsize=8)
def _config_index(root_text: str, fingerprint: tuple) -> tuple[tuple[Path, dict], ...]:
    from db.schema import check_version_date

    del root_text
    entries = []
    for path_text, _mtime_ns, size, _sha256 in fingerprint:
        path = Path(path_text)
        try:
            if size > MAX_YAML_BYTES:
                continue
            data = yaml.safe_load(path.read_bytes())
            if not isinstance(data, dict):
                continue
            check_version_date(data.get("version_date"))
        except (OSError, yaml.YAMLError, TypeError, ValueError):
            continue
        entries.append((path, data))
    return tuple(entries)


def _project_config(library_dir: Path, kind: str, sid: int, name: str, version: int | None):
    fingerprint = _config_fingerprint(library_dir)
    for path, data in _config_index(str(library_dir.resolve()), fingerprint):
        if path.parent.name != kind:
            continue
        if str(data.get("id", "")) != str(sid) and data.get("name") != name:
            continue
        if version is not None and str(data["version_date"]) != str(version):
            continue
        return data, path
    return None, None


def _artwork_from_config(data: dict, path: Path, fallback_name: str,
                         use_portrait: bool = False):
    images_dir = path.parent.parent / "images"
    artwork = data.get("artwork") if isinstance(data.get("artwork"), dict) else {}
    images = artwork.get("images")
    first = images[0] if isinstance(images, list) and images else {}
    raw_path = first.get("path") if isinstance(first, dict) else None
    if not isinstance(raw_path, str) or not raw_path:
        raw_path = f"{data.get('id') or data.get('name', fallback_name)}.png"
    try:
        image_path = Path(raw_path)
        if not image_path.is_absolute():
            image_path = images_dir / image_path
        image_path = image_path.resolve(strict=True)
        image_path.relative_to(images_dir.resolve())
    except (OSError, ValueError):
        return None, data.get("faction_style")
    portrait = data.get("portrait") if isinstance(data.get("portrait"), dict) else {}
    settings = portrait if use_portrait else first if isinstance(first, dict) else {}
    ref = {"path": str(image_path)}
    for key, default, limit in (("offset_x", 0, 4096), ("offset_y", 0, 4096),
                                ("scale", 1.0, 16.0), ("rotate", 0, 36000)):
        value = settings.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not math.isfinite(value):
            value = default
        elif key == "scale":
            value = min(max(value, 0.01), limit)
        else:
            value = min(max(value, -limit), limit)
        ref[key] = value
    return ref, data.get("faction_style")


def _artwork_ref(library_dir: Path, sid: int, name: str,
                 version: int | None = None) -> tuple[dict | None, int | None]:
    data, path = _project_config(library_dir, "shikigami", sid, name, version)
    if data is None:
        return None, None
    return _artwork_from_config(data, path, name, use_portrait=True)


def _preflight_artwork(library, element: dict, art: dict | None) -> None:
    """在 BWPDIY 分配缩放图前估算尺寸，阻止极端长宽比/缩放耗尽内存。"""
    if not art:
        return
    original, rotated = library.artwork(Path(art["path"]), art.get("rotate", 0))
    target = max(1, round(float(element.get("back_size", 62)) * 2))
    cover = max(target / original[0], target / original[1]) * art.get("scale", 1.0)
    pixels = max(round(rotated.width * cover), 1) * max(round(rotated.height * cover), 1)
    if pixels > MAX_RENDER_PIXELS:
        raise ValueError(f"头像缩放后像素超过安全上限：{pixels}")


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
def _portrait_pixmap(sid: int, name: str, faction: str, version: int,
                     root_text: str, library_text: str, size: int, art_json: str,
                     faction_style: int | None, image_mtime_ns: int,
                     image_size: int) -> QPixmap:
    del sid, version, library_text, image_mtime_ns, image_size
    _root, library, element, render = _renderer(root_text)
    art = json.loads(art_json)
    _preflight_artwork(library, element, art)
    image = render(library, element, art, faction, scale=2,
                   faction_style=faction_style)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    pixmap = QPixmap()
    if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
        raise ValueError("头像 PNG 解码失败")
    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _empty_portrait_pixmap(definition, size: int, root: Path) -> QPixmap:
    """无卡图配置时仍使用 BWPDIY 空槽：斜方框和派系标保留，不画人物。"""
    try:
        _root, library, element, render = _renderer(str(root.resolve()))
        image = render(library, element, None, definition.faction, scale=2,
                       faction_style=None)
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("空头像 PNG 解码失败")
        return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return _fallback_pixmap(definition.name, definition.faction, size)


def shikigami_portrait(definition, size: int = 72, root: Path | None = None,
                       library_dir: Path | None = None) -> QPixmap:
    """返回带斜方框与派系标的式神头像；渲染资源与项目配置库相互独立。"""
    root = root or bwpdiy_root()
    library_dir = library_dir or library_root()
    try:
        art, faction_style = _artwork_ref(
            library_dir, definition.id, definition.name, getattr(definition, "version", 0))
        if art is None:
            raise ValueError("头像配置或图片缺失")
        image_stat = Path(art["path"]).stat()
        art_json = json.dumps(art, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False)
        return _portrait_pixmap(
            definition.id, definition.name, definition.faction,
            getattr(definition, "version", 0), str(root.resolve()),
            str(library_dir.resolve()), size, art_json, faction_style,
            image_stat.st_mtime_ns, image_stat.st_size)
    except Exception:
        return _empty_portrait_pixmap(definition, size, root)
