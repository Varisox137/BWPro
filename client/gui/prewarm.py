"""启动卡图预热：复用有效缓存并记录配置与图片的最新内容指纹。"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from client.gui import cardart, portrait
from client.gui.cardart import card_pixmap, entity_pixmap

MANIFEST_NAME = "manifest.json"


def _art_sha256(config: dict, path: Path, name: str) -> str:
    try:
        art, _style = portrait._artwork_from_config(config, path, name)
        if art is None:
            return ""
        return hashlib.sha256(Path(art["path"]).read_bytes()).hexdigest()
    except (OSError, TypeError, ValueError):
        return ""


def _renderer_version() -> str:
    root = str(portrait.bwpdiy_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from bwpdiy import __version__
    except ImportError:
        return "unknown"
    return __version__


def _definition_sha256(definition) -> str:
    payload = json.dumps(definition.model_dump(mode="json"), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_current(cache_dir: Path, manifest: dict) -> bool:
    try:
        current = json.loads((cache_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return all(current.get(key) == manifest[key]
               for key in ("version", "renderer_version", "renderer_resources", "entries"))


def prewarm_all(db, library_dir: Path | None = None, cache_dir: Path | None = None,
                on_progress=None, clear: bool = False) -> list[dict]:
    """内容未变化时直接复用磁盘缓存，否则增量重建全部静态卡图。"""
    library_dir = library_dir or portrait.library_root()
    cache_dir = cache_dir or Path.home() / ".bwpro" / "cardart"
    if clear:
        clear_cardart_cache(cache_dir)
    definitions = [
        (kind, definition)
        for kind, values in (("cards", db.cards), ("shikigami", db.shikigami))
        for definition in values.values()
        if not getattr(definition, "unreleased", False) and not getattr(definition, "wip", False)
    ]
    entries = []
    art_context = {}
    config_fingerprint = portrait._config_fingerprint(library_dir)
    art_context["portrait_config_fingerprint"] = config_fingerprint
    root_text = str(portrait.bwpdiy_root().resolve())
    assets, _library, _render = cardart._renderer(root_text)
    renderer_resources = cardart._renderer_resources(assets, art_context)
    for kind, definition in definitions:
        config, path = portrait._project_config(
            library_dir, kind, definition.id, definition.name, definition.version,
            fingerprint=config_fingerprint)
        config = config or {}
        entries.append({
            "id": definition.id,
            "kind": kind,
            "version": definition.version,
            "definition_sha256": _definition_sha256(definition),
            "config_sha256": (hashlib.sha256(path.read_bytes()).hexdigest()
                              if config and path is not None else ""),
            "art_sha256": (_art_sha256(config, path, definition.name)
                           if config and path is not None else ""),
        })
    entries.sort(key=lambda entry: (entry["kind"], entry["id"], entry["version"]))
    manifest = {
        "version": 3,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "renderer_version": _renderer_version(),
        "renderer_resources": renderer_resources,
        "entries": entries,
    }
    if not clear and _manifest_current(cache_dir, manifest):
        if on_progress is not None:
            on_progress(len(entries), len(definitions))
        return entries
    for index, (kind, definition) in enumerate(definitions, 1):
        card_pixmap(definition, db, cache_context=art_context)
        if kind == "shikigami":
            shiki = SimpleNamespace(
                id=definition.id, awakened=None, level=0,
                eff_power=definition.power, combat_power=0,
                health=definition.health, shield=0, ext={})
            entity_pixmap(shiki, db, height=210, cache_context=art_context, disk_cache=True)
        if on_progress is not None:
            on_progress(index, len(definitions))
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries


def clear_cardart_cache(cache_dir: Path) -> None:
    cardart.clear_cardart_caches()
    if not cache_dir.exists():
        return
    for path in cache_dir.glob("*.png"):
        path.unlink(missing_ok=True)
    (cache_dir / MANIFEST_NAME).unlink(missing_ok=True)
