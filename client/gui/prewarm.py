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
from client.gui.portrait import shikigami_portrait

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


def prewarm_all(db, library_dir: Path | None = None, cache_dir: Path | None = None,
                on_progress=None, clear: bool = False) -> list[dict]:
    """为全部已实装定义增量建缓存；未变化内容由 cardart 缓存键直接复用。"""
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
    for kind, definition in definitions:
        config, path = portrait._project_config(
            library_dir, kind, definition.id, definition.name, definition.version)
        config = config or {}
        card_pixmap(definition, db, cache_context=art_context)
        if kind == "shikigami":
            shiki = SimpleNamespace(
                id=definition.id, awakened=None, level=0,
                eff_power=definition.power, combat_power=0,
                health=definition.health, shield=0, ext={})
            entity_pixmap(shiki, db, height=210, cache_context=art_context)
            shikigami_portrait(definition, size=96)
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
        if on_progress is not None:
            on_progress(len(entries), len(definitions))
    entries.sort(key=lambda entry: (entry["kind"], entry["id"], entry["version"]))
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 2,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "renderer_version": _renderer_version(),
        "entries": entries,
    }
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
