"""本地卡图适配：引擎数据生成 BWPDIY 负载，缺插画时仍合成完整卡框。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import threading
from functools import lru_cache, wraps
from io import BytesIO
from pathlib import Path

import yaml
from PIL import Image, ImageOps
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from client.gui import portrait
from client.gui.card_appearance import card_appearance
from client.gui.portrait import library_root
from client.gui.renderlog import (
    clear_render_log_dedup, log_cache_failure, log_render_failure)

__all__ = ["library_root", "card_pixmap", "shikigami_pixmap", "entity_pixmap",
           "seat_level_color", "clear_cardart_caches"]

_TYPE_NAMES = {"combat": "战斗", "spell": "法术", "form": "形态",
               "field": "幻境", "reinforce": "协战"}
_ICON_NAMES = {"力量": "ll", "生命": "sm", "护甲": "hj", "破甲": "pj",
               "能量": "nl", "耐久": "nj", "战力": "zl", "乏力": "fl", "赏金": "sj"}
_KEYWORD_RE = re.compile(r"(?<!\[)\[([^\[\]\n]+)\](?!\])")
_ICON_RE = re.compile("|".join(_ICON_NAMES))
_RENDER_LOCK = threading.RLock()
_TRANSPARENT_ART = "__BWPRO_TRANSPARENT__"
_SEAT_LEVEL_COLORS = ("yellow", "cyan", "purple", "red")


def _placeholder_color() -> str:
    app = QApplication.instance()
    return "#e8e4f0" if app is not None and app.property("bwpro_theme") == "dark" else "#26221c"


def _grayscale_artwork(image: Image.Image) -> Image.Image:
    """仅灰白化插画，保留透明度，不改变牌框和数值组件。"""
    source = image.convert("RGBA")
    gray = ImageOps.grayscale(source)
    gray = Image.blend(gray, Image.new("L", source.size, 235), 0.35)
    result = gray.convert("RGBA")
    result.putalpha(source.getchannel("A"))
    return result


def _paint_placeholder_name(pixmap: QPixmap, name: str, color: str, *, entity: bool) -> None:
    """缺卡图配置时，在透明插画窗中央补上名称。"""
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = (QRectF(pixmap.width() * 0.10, pixmap.height() * 0.12,
                   pixmap.width() * 0.80, pixmap.height() * 0.58) if entity else
            QRectF(pixmap.width() * 0.15, pixmap.height() * 0.18,
                   pixmap.width() * 0.70, pixmap.height() * 0.40))
    font = QFont("Microsoft YaHei", max(12, round(rect.height() / 5)), QFont.Normal)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    while metrics.horizontalAdvance(name) > rect.width() and font.pointSize() > 8:
        font.setPointSize(font.pointSize() - 1)
        painter.setFont(font)
        metrics = painter.fontMetrics()
    painter.setPen(QColor(color))
    painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, name)
    painter.end()


def seat_level_color(seat: int | None) -> str:
    """准备区 1-4 对应的 DIY 勾玉颜色；无座次使用默认黄色。"""
    return _SEAT_LEVEL_COLORS[seat] if isinstance(seat, int) and 0 <= seat < 4 else "yellow"


def _highlight_named_quotes(text: str, db) -> str:
    names = {definition.name for definition in db.cards.values()}
    names.update(definition.name for definition in db.shikigami.values()
                 if getattr(definition, "kind", "shikigami") != "shikigami")
    names.update(getattr(definition, "name", key)
                 for key, definition in db.invocations.items())
    names.update(definition.name.rsplit("·", 1)[-1] for definition in db.cards.values()
                 if getattr(definition, "token", False) and "·" in definition.name)

    def replace(match):
        content = match.group(1) if match.group(1) is not None else match.group(2)
        if content not in names or "[[" in content or "]]" in content:
            return match.group(0)
        opening, closing = match.group(0)[0], match.group(0)[-1]
        return f"{opening}[[{content}]]{closing}"

    for pattern in (r"「([^「」]*)」", r"『([^『』]*)』"):
        text = re.sub(pattern, replace, text)
    return text


def _description(text: str, db=None) -> str:
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"‘([^’]*)’", r"「\1」", text)
    text = re.sub(r"『([^『』]*)』",
                  lambda match: (match.group(0) if "「" in match.group(1)
                                 else f"「{match.group(1)}」"), text)
    text = _KEYWORD_RE.sub(r"[[\1]]", text)
    if db is not None:
        text = _highlight_named_quotes(text, db)
    return _ICON_RE.sub(lambda match: f"#{_ICON_NAMES[match.group(0)]}", text)


def _shikigami_name(db, sid: int | None) -> str | None:
    definition = db.shikigami.get(sid) if sid is not None else None
    return definition.name if definition is not None else None


_DISPLAY_STAT_KEYS = {"power+", "health+", "shield+", "power", "health", "durability"}


def _display_stats(display: dict[str, int] | None) -> dict[str, int]:
    if not display:
        return {}
    return {key: value for key, value in display.items()
            if key in _DISPLAY_STAT_KEYS and type(value) is int}


def _card_data(cdef, db, config: dict) -> dict:
    card_type = getattr(cdef, "card_type", None)
    if card_type is None:
        data = {"type": "式神", "power": cdef.power, "health": cdef.health,
                "faction": cdef.faction}
    else:
        data = {"type": _TYPE_NAMES[card_type]}
        primary = db.shikigami.get(cdef.shikigami)
        if primary is not None:
            data["faction"] = primary.faction
        if card_type == "reinforce":
            data["shikigami1"] = _shikigami_name(db, cdef.shikigami)
            data["shikigami2"] = _shikigami_name(db, cdef.shikigami2)
        else:
            data["shikigami"] = _shikigami_name(db, cdef.shikigami)
    description = config.get("description") or cdef.text
    data.update(name=cdef.name, description=_description(description, db))
    if getattr(cdef, "level", None) is not None:
        data["level"] = cdef.level
    if getattr(cdef, "rarity", None) is not None:
        data["rarity"] = cdef.rarity
    if card_type == "form":
        data["power"] = cdef.form_power
        data["health"] = cdef.form_health
    elif card_type == "field":
        data["durability"] = cdef.intensity
    elif card_type == "combat":
        power = shield = 0
        for step in cdef.effects.steps:
            extra = step.model_extra or {}
            amount = extra.get("amount")
            if isinstance(amount, dict):
                amount = amount.get("base")
            if not isinstance(amount, int) or isinstance(amount, bool):
                continue
            if step.op == "buff_power":
                power += amount
            elif step.op == "gain_shield":
                shield += amount
        data["power+"] = power
        data["shield+"] = shield
    if card_type is not None and (cdef.subtype == "awaken" or "awaken" in cdef.tags):
        data["evolve"] = True
        data["power+"] = cdef.awaken_power
        data["health+"] = cdef.awaken_health
    if "artwork" in config:
        data["artwork"] = config["artwork"]
    if "frame_variant" in config:
        data["frame_variant"] = config["frame_variant"]
    faction_style = config.get("faction_style")
    if isinstance(faction_style, int) and not isinstance(faction_style, bool) \
            and faction_style in (1, 2, 3):
        data["faction_style"] = faction_style
    return data


def _asset_library(assets: Path):
    from bwpdiy.render.assets import AssetLibrary

    library = AssetLibrary(assets)
    if (not (assets / "levels/evolve_circle.png").is_file()
            and (assets / "levels/evolve.png").is_file()):
        library.level_evolve_circle = library.level_star
    return library


@lru_cache(maxsize=4)
def _renderer(root_text: str):
    root = Path(root_text)
    code_root = portrait.bwpdiy_code_root(root)
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    from bwpdiy.render import render_card

    assets = root / "assets"
    return assets, _asset_library(assets), render_card


def _layout_fingerprint(_assets: Path) -> tuple:
    path = portrait.global_layout_path()
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ()
    return stat.st_mtime_ns, stat.st_size, digest


@lru_cache(maxsize=4)
def _layouts(root_text: str, fingerprint: tuple):
    del fingerprint
    _renderer(root_text)
    return portrait.load_global_layouts()


_RESOURCE_DIRS = ("badges", "duo", "factions", "fonts", "frames", "icons", "levels",
                  "mech", "numbers", "rarity", "signs", "stats")


def _renderer_resource_fingerprint(assets: Path) -> tuple:
    fingerprint = []
    for directory in _RESOURCE_DIRS:
        for path in sorted((assets / directory).rglob("*")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(fingerprint)


def _renderer_resource_digest(root_text: str, fingerprint: tuple) -> str:
    """资源身份只包含 assets 内相对路径与内容，每次读取避免陈旧缓存。"""
    root = Path(root_text)
    digest = hashlib.sha256()
    for path_text, _mtime_ns, _size in fingerprint:
        path = Path(path_text)
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _renderer_resources(assets: Path, cache_context: dict | None = None) -> str:
    if cache_context is not None and "renderer_resources" in cache_context:
        return cache_context["renderer_resources"]
    resources = _renderer_resource_digest(
        str(assets.resolve()), _renderer_resource_fingerprint(assets))
    if cache_context is not None:
        cache_context["renderer_resources"] = resources
    return resources


def _renderer_source_digest(assets: Path) -> str:
    digest = hashlib.sha256()
    source_dir = portrait.bwpdiy_code_root(assets.parent) / "bwpdiy" / "render"
    for path in sorted(source_dir.rglob("*.py")):
        digest.update(path.relative_to(source_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def _renderer_resources_with_source(
        assets: Path, cache_context: dict | None, cache_key: str) -> str:
    if cache_context is not None and cache_key in cache_context:
        return cache_context[cache_key]
    resources = hashlib.sha256(
        (_renderer_resources(assets, cache_context)
         + _renderer_source_digest(assets)).encode("ascii")).hexdigest()
    if cache_context is not None:
        cache_context[cache_key] = resources
    return resources


def _card_renderer_resources(assets: Path, cache_context: dict | None = None) -> str:
    return _renderer_resources_with_source(assets, cache_context, "card_renderer_resources")


def _entity_renderer_resources(assets: Path, cache_context: dict | None = None) -> str:
    """小卡跟踪渲染资源与源码。"""
    return _renderer_resources_with_source(assets, cache_context, "entity_renderer_resources")


def _preflight_card_artwork(library, art: dict) -> None:
    with Image.open(art["path"]) as image:
        if image.width * image.height > portrait.MAX_RENDER_PIXELS:
            raise ValueError("卡图原图像素超过安全上限")
    original, rotated = library.artwork(Path(art["path"]), art.get("rotate", 0))
    cover = max(512 / original[0], 512 / original[1]) * art.get("scale", 1.0)
    pixels = max(round(rotated.width * cover), 1) * max(round(rotated.height * cover), 1)
    if pixels > portrait.MAX_RENDER_PIXELS:
        raise ValueError(f"卡图缩放后像素超过安全上限：{pixels}")


def _card_config_fingerprint(library_dir: Path) -> tuple:
    fingerprint = []
    for path in sorted(library_dir.glob("*/*/*.yaml")):
        try:
            stat = path.stat()
            contents = path.read_bytes()
        except OSError:
            continue
        fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size,
                            hashlib.sha256(contents).hexdigest()))
    return tuple(fingerprint)


@lru_cache(maxsize=4)
def _card_config_index(root_text: str, fingerprint: tuple) -> tuple:
    from db.schema import check_version_date

    entries = []
    for path_text, _mtime_ns, size, _sha256 in fingerprint:
        path = Path(path_text)
        try:
            if size > portrait.MAX_YAML_BYTES:
                continue
            contents = path.read_bytes()
            config = yaml.safe_load(contents)
            if not isinstance(config, dict):
                continue
            check_version_date(config.get("version_date"))
            entries.append((config, path, hashlib.sha256(contents).hexdigest()))
        except (OSError, yaml.YAMLError, TypeError, ValueError) as error:
            log_render_failure("card-config", path.stem, root_text, error, path)
            continue
    return tuple(entries)


def _card_config_snapshot(library_dir: Path, cdef, fingerprint: tuple | None = None):
    if fingerprint is None:
        fingerprint = _card_config_fingerprint(library_dir)
    entries = _card_config_index(str(library_dir), fingerprint)
    for config, path, config_sha256 in entries:
        if str(config.get("id", "")) != str(cdef.id) or config.get("name") != cdef.name:
            continue
        if cdef.version is not None and str(config["version_date"]) != str(cdef.version):
            continue
        return config, path, config_sha256
    return None, None, None


def _scale_layout_compat(scale_layout, layout: dict, factor: float) -> dict:
    scaled = scale_layout(layout, factor)
    for element in scaled.get("elements", {}).values():
        if "stroke_width" in element:
            element["stroke_width"] = max(1, round(element["stroke_width"]))
        for key in ("_sign_gap", "_digit_gap"):
            if key in element:
                element[key] = round(element[key])
    return scaled


def _element_compat(element: dict) -> dict:
    element = dict(element)
    if "stroke_width" in element:
        element["stroke_width"] = max(1, round(element["stroke_width"]))
    for key in ("_sign_gap", "_digit_gap"):
        if key in element:
            element[key] = round(element[key])
    return element


def _render_card_pixmap(payload_json: str, layout_json: str, root_text: str,
                        height: int | None = None) -> QPixmap | None:
    payload = {}
    try:
        payload = json.loads(payload_json)
        layout = json.loads(layout_json)
        assets, _shared_library, render = _renderer(root_text)
        from bwpdiy.render import pipeline
        library = _asset_library(assets)
        art = payload["artwork"]["images"][0]
        transparent = art["path"] == _TRANSPARENT_ART
        with _RENDER_LOCK:
            original_get_library = pipeline.get_library
            original_load_artwork = pipeline.load_card_artwork
            original_scale_layout = pipeline.scale_layout
            original_render_element = pipeline.render_element
            pipeline.get_library = lambda _assets: library
            pipeline.scale_layout = lambda layout, factor: _scale_layout_compat(
                original_scale_layout, layout, factor)
            pipeline.render_element = lambda canvas, lib, name, elem, card, ctx=None, **kwargs: (
                original_render_element(canvas, lib, name, _element_compat(elem), card, ctx, **kwargs))
            if transparent:
                pipeline.load_card_artwork = lambda _card, _lib: (
                    (1, 1), Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
            try:
                if not transparent:
                    _preflight_card_artwork(library, art)
                options = {} if height is None else {"height": height}
                image = render(payload, assets, layout=layout, **options)
            finally:
                pipeline.get_library = original_get_library
                pipeline.load_card_artwork = original_load_artwork
                pipeline.scale_layout = original_scale_layout
                pipeline.render_element = original_render_element
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("卡面 PNG 解码失败")
        if transparent:
            _paint_placeholder_name(pixmap, payload["name"],
                                    payload.get("_placeholder_color", "#26221c"), entity=False)
        return pixmap
    except Exception as error:
        log_render_failure("card", payload.get("name") or "unknown", root_text, error)
        return None


def _render_entity_pixmap(payload_json: str, state_json: str, layout_json: str,
                          root_text: str, height: int | None = None) -> QPixmap | None:
    payload = {}
    try:
        payload = json.loads(payload_json)
        state = json.loads(state_json)
        layout = json.loads(layout_json)
        assets, _shared_library, _render = _renderer(root_text)
        from bwpdiy.render import entity
        library = _asset_library(assets)
        art = payload["artwork"]["images"][0]
        transparent = art["path"] == _TRANSPARENT_ART
        with _RENDER_LOCK:
            original_get_library = entity.get_library
            original_load_artwork = entity.load_card_artwork
            entity.get_library = lambda _assets: library
            if transparent:
                entity.load_card_artwork = lambda _card, _lib: (
                    (1, 1), Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
            if payload.get("_defeated"):
                load_artwork = entity.load_card_artwork

                def load_grayscale(card, lib):
                    original, image = load_artwork(card, lib)
                    return original, _grayscale_artwork(image)

                entity.load_card_artwork = load_grayscale
            try:
                if not transparent:
                    _preflight_card_artwork(library, art)
                    # 普通卡面允许缩放后留白；对局小卡必须覆盖整个内窗。
                    original, rotated = library.artwork(Path(art["path"]), art.get("rotate", 0))
                    window = layout.get("art_window", entity._DEFAULT_LAYOUT["art_window"])
                    window_width, window_height = window["width"], window["height"]
                    ratio = window_width / 512
                    offset_x = art.get("offset_x", 0) * ratio
                    offset_y = (art.get("offset_y", 0) * ratio + window["offset_y"]
                                + window_height * entity.ENTITY_ART_Y_BIAS)
                    if window["frame_center"]:
                        frame = entity._normalize_frame(library.frame(
                            entity.TYPE_FRAME_CODE[payload["type"]],
                            payload.get("frame_variant", "norm")))
                        _, frame_cy = entity.frame_art_window_center(frame)
                        offset_y += (256 - frame_cy) * ratio
                    cover = max(window_width / original[0], window_height / original[1])
                    base_width, base_height = rotated.width * cover, rotated.height * cover
                    required = max(
                        1.0,
                        (window_width + 2 * abs(offset_x)) / base_width,
                        (window_height + 2 * abs(offset_y)) / base_height,
                    )
                    state["art_scale"] = max(state["art_scale"], required)
                options = {} if height is None else {"height": height}
                image = entity.render_entity(payload, state, assets, layout=layout, **options)
            finally:
                entity.get_library = original_get_library
                entity.load_card_artwork = original_load_artwork
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("式神小卡 PNG 解码失败")
        if transparent:
            _paint_placeholder_name(pixmap, payload["name"],
                                    payload.get("_placeholder_color", "#26221c"), entity=True)
        return pixmap
    except Exception as error:
        log_render_failure("entity", payload.get("name") or "unknown", root_text, error)
        return None


def _card_cache_key(payload_json: str, layout_json: str, config_sha256: str,
                    art_path: str, renderer_resources: str,
                    root_text: str, cache_context: dict | None = None,
                    height: int | None = None) -> str:
    del root_text
    if art_path == _TRANSPARENT_ART:
        image_sha256 = "transparent"
    else:
        key = ("art_sha256", art_path)
        if cache_context is not None and key in cache_context:
            image_sha256 = cache_context[key]
        else:
            image_sha256 = hashlib.sha256(Path(art_path).read_bytes()).hexdigest()
            if cache_context is not None:
                cache_context[key] = image_sha256
    payload = json.loads(payload_json)
    payload.pop("_base_dir", None)
    for image in payload.get("artwork", {}).get("images", []):
        image.pop("path", None)
    key_data = {
        "payload": payload,
        "layout": layout_json,
        "config_sha256": config_sha256,
        "image_sha256": image_sha256,
        "renderer_resources": renderer_resources,
        "height": height,
    }
    normalized = json.dumps(key_data, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _write_card_png_atomic(pixmap: QPixmap, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        if not pixmap.save(str(temp_path), "PNG"):
            raise ValueError("卡面 PNG 写入失败")
        verified = QPixmap(str(temp_path))
        if verified.isNull():
            raise ValueError("卡面临时 PNG 校验失败")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class _PixmapRenderFailed(Exception):
    pass


def _cache_successful_pixmap(function):
    @lru_cache(maxsize=256)
    @wraps(function)
    def cached(*args, **kwargs):
        pixmap = function(*args, **kwargs)
        if pixmap is None or pixmap.isNull():
            raise _PixmapRenderFailed
        return pixmap

    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return cached(*args, **kwargs)
        except _PixmapRenderFailed:
            return None

    wrapper.cache_clear = cached.cache_clear
    return wrapper


@_cache_successful_pixmap
def _cached_card_pixmap(cache_path_text: str, payload_json: str,
                        layout_json: str, root_text: str,
                        height: int | None = None, *, entity="unknown",
                        config_path=None) -> QPixmap | None:
    cache_path = Path(cache_path_text)
    try:
        cached = QPixmap(str(cache_path))
        if not cached.isNull():
            return cached
    except Exception as error:
        log_cache_failure("read", "card-cache", entity, root_text, error, config_path)
    pixmap = _render_card_pixmap(payload_json, layout_json, root_text, height)
    if pixmap is None:
        return None
    try:
        _write_card_png_atomic(pixmap, cache_path)
    except Exception as error:
        log_cache_failure("write", "card-cache", entity, root_text, error, config_path)
    return pixmap


@_cache_successful_pixmap
def _cached_runtime_card_pixmap(cache_key: str, payload_json: str,
                                layout_json: str, root_text: str,
                                height: int | None = None) -> QPixmap | None:
    """运行时变体仅驻留有界内存，避免每种实时数值都永久写盘。"""
    del cache_key  # 仅作为 LRU 的身份键，不映射磁盘文件
    return _render_card_pixmap(payload_json, layout_json, root_text, height)


@_cache_successful_pixmap
def _cached_entity_pixmap(cache_key: str, payload_json: str, state_json: str,
                          layout_json: str, root_text: str,
                          height: int | None = None) -> QPixmap | None:
    del cache_key
    return _render_entity_pixmap(payload_json, state_json, layout_json, root_text, height)


@_cache_successful_pixmap
def _cached_static_entity_pixmap(cache_path_text: str, payload_json: str, state_json: str,
                                 layout_json: str, root_text: str,
                                 height: int | None = None, *, entity="unknown",
                                 config_path=None) -> QPixmap | None:
    """基础小卡可跨进程复用；运行时小卡仍只使用内存缓存。"""
    cache_path = Path(cache_path_text)
    try:
        cached = QPixmap(str(cache_path))
        if not cached.isNull():
            return cached
    except Exception as error:
        log_cache_failure("read", "entity-cache", entity, root_text, error, config_path)
    pixmap = _render_entity_pixmap(payload_json, state_json, layout_json, root_text, height)
    if pixmap is None:
        return None
    try:
        _write_card_png_atomic(pixmap, cache_path)
    except Exception as error:
        log_cache_failure("write", "entity-cache", entity, root_text, error, config_path)
    return pixmap


def _validate_layout(layout: dict) -> None:
    elements = layout.get("elements", {})
    if not isinstance(elements, dict) or len(elements) > 64:
        raise ValueError("layout 元素数量超出安全范围")
    if any(not isinstance(element, dict) for element in elements.values()):
        raise ValueError("layout 元素必须为映射")

    def visit(value, key=None):
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
            return
        if key == "font_range":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("font_range 必须为两个数值")
            maximum, minimum = value
            if any(isinstance(item, bool) or not isinstance(item, (int, float))
                   or not math.isfinite(item) for item in value):
                raise ValueError("font_range 必须为有限数值")
            if not 1 <= minimum <= maximum <= 256:
                raise ValueError("font_range 必须为有序的 1..256")
            return
        if isinstance(value, list):
            for child in value:
                visit(child, key)
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if not math.isfinite(value) or abs(value) > 4096:
            raise ValueError("layout 数值超出安全范围")
        if key is not None and (key == "size" or key.endswith("_size")
                                or key in ("width", "height")) and not 0 < value <= 512:
            raise ValueError("layout 元素尺寸超出 512 画布预算")
        if key == "font_size" and not 1 <= value <= 256:
            raise ValueError("font_size 必须为 1..256")
        if key == "icon_scale" and not 0.01 <= value <= 16:
            raise ValueError("icon_scale 必须为 0.01..16")

    visit(layout)


def _transparent_art() -> dict:
    """内存占位：无配置/缺图时仍渲染完整牌框，仅插画区域透明。"""
    return {"path": _TRANSPARENT_ART, "offset_x": 0, "offset_y": 0,
            "scale": 1.0, "rotate": 0}


def _card_pixmap_impl(cdef, db, library_dir: Path, cache_dir: Path,
                      display: dict[str, int] | None,
                      payload_overrides: dict | None = None,
                      drop_keys: tuple[str, ...] = (),
                      cache_context: dict | None = None,
                      height: int | None = None,
                      description_suffix: str | None = None) -> QPixmap | None:
    path = None
    try:
        if cache_context is None:
            fingerprint = _card_config_fingerprint(library_dir)
        elif "config_fingerprint" not in cache_context:
            cache_context["config_fingerprint"] = _card_config_fingerprint(library_dir)
        fingerprint = (cache_context["config_fingerprint"] if cache_context is not None
                       else fingerprint)
        config, path, config_sha256 = _card_config_snapshot(
            library_dir, cdef, fingerprint)
        config = config or {}
        art, faction_style = (portrait._artwork_from_config(config, path, cdef.name)
                              if config else (None, None))
        fallback_art = art is None
        art = art or _transparent_art()
        selected = {"artwork": {"images": [art]}}
        if config:
            selected["frame_variant"] = config.get("frame_variant", "norm")
            selected["description"] = config.get("description")
        preference = card_appearance(cdef.id)
        if preference["frame_variant"] != "norm":
            selected["frame_variant"] = preference["frame_variant"]
        if faction_style is not None:
            selected["faction_style"] = faction_style
        payload = _card_data(cdef, db, selected)
        if fallback_art:
            payload["_placeholder_color"] = _placeholder_color()
        if payload_overrides:
            payload.update(payload_overrides)
        if description_suffix:
            payload["description"] = str(payload.get("description", "")) + description_suffix
        for key in drop_keys:
            payload.pop(key, None)
        display_stats = _display_stats(display)
        original_stats = {key: payload.get(key) for key in display_stats}
        payload.update(display_stats)
        for key, original in original_stats.items():
            current = payload.get(key)
            if type(original) is int and type(current) is int:
                payload[f"{key}_color"] = (
                    "red" if current < original else
                    "green" if current > original else None)
        payload["_base_dir"] = (str(cache_dir) if fallback_art or not path
                                else str(path.parent.parent / "images"))
        root_text = str(portrait.bwpdiy_root().resolve())
        assets, _library, _render = _renderer(root_text)
        from bwpdiy.render.layout import get_type_layout, merge_card_layout

        base_layout = get_type_layout(
            _layouts(root_text, _layout_fingerprint(assets)),
            payload["type"], payload.get("frame_variant", "norm"))
        layout = merge_card_layout(base_layout, config.get("layout"))
        _validate_layout(layout)
        resources = _card_renderer_resources(assets, cache_context)
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False)
        layout_json = json.dumps(layout, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
        cache_key = _card_cache_key(
            payload_json, layout_json, config_sha256 or "fallback", art["path"],
            resources, root_text, cache_context, height)
        size_args = () if height is None else (height,)
        if display_stats:
            return _cached_runtime_card_pixmap(
                cache_key, payload_json, layout_json, root_text, *size_args)
        cache_path = cache_dir / f"{cache_key}.png"
        return _cached_card_pixmap(
            str(cache_path), payload_json, layout_json, root_text, *size_args,
            entity=cdef.id, config_path=path)
    except Exception as error:
        log_render_failure("card", cdef.id, portrait.bwpdiy_root(), error, path)
        pixmap_height = 504 if height is None else height
        pixmap_width = 360 if height is None else round(pixmap_height * 5 / 7)
        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(Qt.transparent)
        _paint_placeholder_name(pixmap, cdef.name, _placeholder_color(), entity=False)
        return pixmap


def card_pixmap(cdef, db, *, library_dir: Path | None = None,
                cache_dir: Path | None = None,
                display: dict[str, int] | None = None,
                level_color: str | None = None, burst: int | None = None,
                cache_context: dict | None = None,
                height: int | None = None, frame_variant: str | None = None) -> QPixmap | None:
    """按原生高度合成；静态卡面使用磁盘缓存，同页可复用资源校验。"""
    overrides = {"level_color": level_color} if level_color is not None else {}
    if burst is not None:
        overrides["burst"] = burst
    if frame_variant is not None:
        overrides["frame_variant"] = frame_variant
    return _card_pixmap_impl(
        cdef, db, library_dir or library_root(),
        cache_dir or Path.home() / ".bwpro" / "cardart", display, overrides,
        cache_context=cache_context, height=height)


def entity_pixmap(shiki, db, *, seat: int | None = None, form=None,
                  library_dir: Path | None = None, cache_dir: Path | None = None,
                  cache_context: dict | None = None, height: int | None = None,
                  disk_cache: bool = False, show_defeated_countdown: bool = True,
                  snapshot: dict | None = None) -> QPixmap | None:
    """以 BWPDIY render_entity 绘制对局小卡；snapshot 固定动画时点的数值。"""
    snapshot = dict(snapshot or {})
    for key in ("power", "health"):
        value = snapshot.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            snapshot[key] = max(0, value)
    path = None
    try:
        awakened = shiki.awakened is not None
        source = form or (db.cards[shiki.awakened] if awakened else db.shikigami[shiki.id])
        library_dir = library_dir or library_root()
        cache_dir = cache_dir or Path.home() / ".bwpro" / "cardart"
        if form is None and not awakened:
            fingerprint = None
            if cache_context is not None:
                if "portrait_config_fingerprint" not in cache_context:
                    cache_context["portrait_config_fingerprint"] = \
                        portrait._config_fingerprint(library_dir)
                fingerprint = cache_context["portrait_config_fingerprint"]
            config, path = portrait._project_config(
                library_dir, "shikigami", source.id, source.name, source.version,
                fingerprint=fingerprint)
            config_sha256 = (hashlib.sha256(path.read_bytes()).hexdigest()
                             if config is not None else None)
        else:
            config, path, config_sha256 = _card_config_snapshot(library_dir, source)
        config = config or {}
        art, faction_style = (portrait._artwork_from_config(config, path, source.name)
                              if config else (None, None))
        fallback_art = art is None
        art = art or _transparent_art()
        selected = {"artwork": {"images": [art]}}
        if config:
            selected["frame_variant"] = config.get("frame_variant", "norm")
        if faction_style is not None:
            selected["faction_style"] = faction_style
        payload = _card_data(source, db, selected)
        if fallback_art:
            payload["_placeholder_color"] = "#f3efe8"
        payload["type"] = "形态" if form is not None else "式神"
        payload["evolve"] = awakened
        payload["_base_dir"] = (str(cache_dir) if fallback_art or not path
                                else str(path.parent.parent / "images"))
        defeated = bool(snapshot.get("defeated", getattr(shiki, "defeated", False))
                        if snapshot else getattr(shiki, "defeated", False))
        payload["_defeated"] = defeated
        definition = db.shikigami[shiki.id]
        base_power = (form.form_power if form is not None and form.form_power is not None
                      else definition.power) + getattr(shiki, "perm_power", 0)
        base_health = (form.form_health if form is not None and form.form_health is not None
                       else definition.health) + getattr(shiki, "perm_health", 0)
        if snapshot:
            base_power = snapshot.get("base_power", base_power)
            base_health = snapshot.get("base_health", base_health)
        if snapshot:
            power = snapshot["power"]
            health = snapshot["health"]
        elif defeated:
            power = max(0, base_power)
            health = max(0, base_health)
        else:
            power = (shiki.eff_power if shiki.ext.get("power_zero")
                     else shiki.eff_power - shiki.combat_power)
            health = shiki.health
        power_color = "red" if power < base_power else "green" if power > base_power else None
        current_max_health = snapshot["max_health"] if snapshot else (
            health if defeated else getattr(shiki, "max_health", health))
        health_color = ("red" if health < current_max_health else
                        None if current_max_health <= base_health else "green")
        energy = int(getattr(shiki, "energy", 0))
        has_energy = "charge" in definition.keywords or any(
            "charge" in getattr(shiki, field, [])
            for field in ("keywords", "one_shot_keywords", "perm_keywords"))
        countdown = (snapshot.get("countdown", getattr(shiki, "countdown", None))
                     if snapshot else getattr(shiki, "countdown", None))
        # 能量与普通倒计时可共存；气绝时仅隐藏普通倒计时。
        state_energy = energy if has_energy else None
        state_countdown = countdown if not defeated else None
        revive = int(snapshot.get("revive_countdown", 0) if snapshot
                     else getattr(shiki, "revive_countdown", 0))
        revive_pending = bool(snapshot and snapshot.get("revive_pending", False))
        state = {
            "level": shiki.level,
            "level_color": seat_level_color(seat),
            "power": power,
            "health": health,
            "combat_power": snapshot["combat_power"] if snapshot else (
                0 if defeated else shiki.combat_power),
            "shield": snapshot["shield"] if snapshot else shiki.shield,
            "energy": state_energy,
            "countdown": state_countdown,
            "defeated_countdown": ((revive if revive > 0 else
                                    0 if revive_pending else "infinity")
                                   if defeated and show_defeated_countdown else None),
            "power_color": power_color,
            "health_color": health_color,
            "combat_power_color": None,
            "shield_color": None,
            "art_scale": art.get("scale", 1.0),
        }
        payload["_entity_state"] = state
        root_text = str(portrait.bwpdiy_root().resolve())
        assets, _library, _render = _renderer(root_text)

        layout = _layouts(root_text, _layout_fingerprint(assets))["对局式神"]
        resources = _entity_renderer_resources(assets, cache_context)
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False)
        state_json = json.dumps(state, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False)
        layout_json = json.dumps(layout, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
        cache_key = _card_cache_key(
            payload_json, layout_json, config_sha256 or "fallback", art["path"],
            resources, root_text, cache_context, height)
        size_args = () if height is None else (height,)
        if disk_cache:
            return _cached_static_entity_pixmap(
                str(cache_dir / f"{cache_key}.png"), payload_json, state_json,
                layout_json, root_text, *size_args, entity=shiki.id, config_path=path)
        return _cached_entity_pixmap(
            cache_key, payload_json, state_json, layout_json, root_text, *size_args)
    except Exception as error:
        log_render_failure("entity", shiki.id, portrait.bwpdiy_root(), error, path)
        return None


def shikigami_pixmap(shiki, db, *, current: bool = False, seat: int | None = None,
                     library_dir: Path | None = None, cache_dir: Path | None = None,
                     height: int | None = None,
                     description_suffix: str | None = None) -> QPixmap | None:
    """以 DIY 路线绘制基础/觉醒式神；详情用永久值，场上可用当前值。"""
    definition = db.shikigami[shiki.id]
    awakened = shiki.awakened is not None
    source = db.cards[shiki.awakened] if awakened else definition
    power = shiki.eff_power if current else definition.power + (
        shiki.perm_power if awakened else 0)
    health = shiki.health if current else definition.health + (
        shiki.perm_health if awakened else 0)
    overrides = {
        "type": "式神", "name": source.name, "faction": shiki.faction,
        "power": power, "health": health, "evolve": awakened,
        "level": shiki.level or None,
        "level_color": seat_level_color(seat),
    }
    render_kwargs = {} if height is None else {"height": height}
    if description_suffix is not None:
        render_kwargs["description_suffix"] = description_suffix
    return _card_pixmap_impl(
        source, db, library_dir or library_root(),
        cache_dir or Path.home() / ".bwpro" / "cardart",
        {"power": power, "health": health}, overrides,
        ("rarity", "shikigami", "power+", "health+"), **render_kwargs)


def clear_cardart_caches() -> None:
    _cached_card_pixmap.cache_clear()
    _cached_runtime_card_pixmap.cache_clear()
    _cached_entity_pixmap.cache_clear()
    _cached_static_entity_pixmap.cache_clear()
    _card_config_index.cache_clear()
    _layouts.cache_clear()
    _renderer.cache_clear()
    portrait._config_index.cache_clear()
    portrait._portrait_pixmap.cache_clear()
    portrait._renderer.cache_clear()
    clear_render_log_dedup()
