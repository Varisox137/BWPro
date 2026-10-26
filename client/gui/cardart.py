"""本地项目卡图适配：引擎数据生成 BWPDIY 渲染负载，失败时返回空槽。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import yaml
from PIL import Image
from PySide6.QtGui import QPixmap

from client.gui import portrait
from client.gui.portrait import library_root

__all__ = ["library_root", "card_pixmap", "clear_cardart_caches"]

_TYPE_NAMES = {"combat": "战斗", "spell": "法术", "form": "形态",
               "field": "幻境", "reinforce": "协战"}
_ICON_NAMES = {"力量": "ll", "生命": "sm", "护甲": "hj", "破甲": "pj",
               "能量": "nl", "耐久": "nj", "战力": "zl", "乏力": "fl", "赏金": "sj"}
_KEYWORD_RE = re.compile(r"\[([^\[\]\n]+)\]")
_ICON_RE = re.compile("|".join(_ICON_NAMES))
_RENDER_LOCK = threading.RLock()


def _description(text: str) -> str:
    text = _KEYWORD_RE.sub(r"[[\1]]", text)
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
    data.update(name=cdef.name, description=_description(cdef.text))
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
    faction_style = config.get("faction_style")
    if isinstance(faction_style, int) and not isinstance(faction_style, bool) \
            and faction_style in (1, 2, 3):
        data["faction_style"] = faction_style
    return data


@lru_cache(maxsize=4)
def _renderer(root_text: str):
    root = Path(root_text)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from bwpdiy.render import render_card
    from bwpdiy.render.assets import AssetLibrary

    assets = root / "assets"
    return assets, AssetLibrary(assets), render_card


_RESOURCE_DIRS = ("duo", "factions", "fonts", "frames", "icons", "levels",
                  "mech", "rarity", "signs", "stats")


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


@lru_cache(maxsize=4)
def _renderer_resource_digest(root_text: str, fingerprint: tuple) -> str:
    del root_text
    digest = hashlib.sha256()
    for path_text, mtime_ns, size in fingerprint:
        digest.update(path_text.encode("utf-8"))
        digest.update(f":{mtime_ns}:{size}\0".encode("ascii"))
        digest.update(Path(path_text).read_bytes())
    return digest.hexdigest()


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
    for path in sorted(library_dir.glob("*/cards/*.yaml")):
        try:
            stat = path.stat()
        except OSError:
            continue
        fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(fingerprint)


@lru_cache(maxsize=4)
def _card_config_index(root_text: str, fingerprint: tuple) -> tuple:
    from db.schema import check_version_date

    del root_text
    entries = []
    for path_text, _mtime_ns, size in fingerprint:
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
        except (OSError, yaml.YAMLError, TypeError, ValueError):
            continue
    return tuple(entries)


def _card_config_snapshot(library_dir: Path, cdef):
    fingerprint = _card_config_fingerprint(library_dir)
    entries = _card_config_index(str(library_dir), fingerprint)
    for config, path, config_sha256 in entries:
        if str(config.get("id", "")) != str(cdef.id) and config.get("name") != cdef.name:
            continue
        if cdef.version is not None and str(config["version_date"]) != str(cdef.version):
            continue
        return config, path, config_sha256
    return None, None, None


def _render_card_pixmap(payload_json: str, layout_json: str, root_text: str) -> QPixmap | None:
    try:
        payload = json.loads(payload_json)
        layout = json.loads(layout_json)
        assets, _shared_library, render = _renderer(root_text)
        from bwpdiy.render import pipeline
        from bwpdiy.render.assets import AssetLibrary

        library = AssetLibrary(assets)
        art = payload["artwork"]["images"][0]
        with _RENDER_LOCK:
            original_get_library = pipeline.get_library
            pipeline.get_library = lambda _assets: library
            try:
                _preflight_card_artwork(library, art)
                image = render(payload, assets, layout=layout)
            finally:
                pipeline.get_library = original_get_library
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("卡面 PNG 解码失败")
        return pixmap
    except Exception:
        return None


def _card_cache_key(payload_json: str, layout_json: str, config_sha256: str,
                    art_path: str, renderer_version: str, renderer_resources: str,
                    root_text: str) -> str:
    image_stat = Path(art_path).stat()
    key_data = {
        "payload": payload_json,
        "layout": layout_json,
        "config_sha256": config_sha256,
        "image_mtime_ns": image_stat.st_mtime_ns,
        "image_size": image_stat.st_size,
        "bwpdiy_version": renderer_version,
        "renderer_resources": renderer_resources,
        "renderer_root": root_text,
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


@lru_cache(maxsize=256)
def _cached_card_pixmap(cache_path_text: str, payload_json: str,
                        layout_json: str, root_text: str) -> QPixmap | None:
    cache_path = Path(cache_path_text)
    try:
        cached = QPixmap(str(cache_path))
        if not cached.isNull():
            return cached
    except Exception:
        pass
    pixmap = _render_card_pixmap(payload_json, layout_json, root_text)
    if pixmap is None:
        return None
    try:
        _write_card_png_atomic(pixmap, cache_path)
    except Exception:
        pass
    return pixmap


def _validate_layout(layout: dict) -> None:
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
                visit(child)
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if not math.isfinite(value) or abs(value) > 4096:
            raise ValueError("layout 数值超出安全范围")
        if key == "font_size" and not 1 <= value <= 256:
            raise ValueError("font_size 必须为 1..256")
        if key == "icon_scale" and not 0.01 <= value <= 16:
            raise ValueError("icon_scale 必须为 0.01..16")

    visit(layout)


def card_pixmap(cdef, db, *, library_dir: Path | None = None,
                cache_dir: Path | None = None,
                display: dict[str, int] | None = None) -> QPixmap | None:
    """按引擎版本选择项目配置并渲染全卡，使用内容寻址磁盘缓存。"""
    library_dir = library_dir or library_root()
    cache_dir = cache_dir or Path.home() / ".bwpro" / "cardart"
    try:
        config, path, config_sha256 = _card_config_snapshot(library_dir, cdef)
        if config is None:
            return None
        art, faction_style = portrait._artwork_from_config(config, path, cdef.name)
        if art is None:
            return None
        selected = {"artwork": {"images": [art]}}
        if faction_style is not None:
            selected["faction_style"] = faction_style
        payload = _card_data(cdef, db, selected)
        payload.update(_display_stats(display))
        payload["_base_dir"] = str(path.parent.parent / "images")
        root_text = str(portrait.bwpdiy_root().resolve())
        assets, _library, _render = _renderer(root_text)
        from bwpdiy import __version__
        from bwpdiy.render.layout import get_type_layout, load_layouts, merge_card_layout

        base_layout = get_type_layout(load_layouts(assets), payload["type"])
        layout = merge_card_layout(base_layout, config.get("layout"))
        _validate_layout(layout)
        resources = _renderer_resource_digest(
            str(assets.resolve()), _renderer_resource_fingerprint(assets))
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False)
        layout_json = json.dumps(layout, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
        cache_key = _card_cache_key(
            payload_json, layout_json, config_sha256, art["path"], __version__, resources,
            root_text)
        cache_path = cache_dir / f"{cache_key}.png"
        return _cached_card_pixmap(
            str(cache_path), payload_json, layout_json, root_text)
    except Exception:
        return None


def clear_cardart_caches() -> None:
    _cached_card_pixmap.cache_clear()
    _card_config_index.cache_clear()
    _renderer_resource_digest.cache_clear()
    _renderer.cache_clear()
    portrait._config_index.cache_clear()
    portrait._portrait_pixmap.cache_clear()
    portrait._renderer.cache_clear()
