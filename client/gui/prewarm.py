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


def prewarm_all(db, library_dir: Path | None = None, cache_dir: Path | None = None,
                on_progress=None, clear: bool = False) -> list[dict]:
    library_dir = library_dir or portrait.library_root()
    cache_dir = cache_dir or Path.home() / ".bwpro" / "cardart"
    if clear:
        clear_cardart_cache(cache_dir)
    fingerprint = portrait._config_fingerprint(library_dir)
    configs = portrait._config_index(str(library_dir.resolve()), fingerprint)
    entries = []
    for path, config in configs:
        kind = path.parent.name
        if kind not in ("cards", "shikigami"):
            continue
        version = int(config["version_date"])
        definitions = db.cards if kind == "cards" else db.shikigami
        definition = None
        for candidate in definitions.values():
            if ((str(candidate.id) == str(config.get("id", ""))
                 or candidate.name == config.get("name")) and candidate.version == version):
                definition = candidate
                break
        if definition is None:
            continue
        if kind == "cards":
            card_pixmap(definition, db, height=360)
        else:
            shiki = SimpleNamespace(
                id=definition.id, awakened=None, level=0,
                eff_power=definition.power, combat_power=0,
                health=definition.health, shield=0, ext={})
            entity_pixmap(shiki, db, height=210)
            shikigami_portrait(definition, size=96)
        entries.append({
            "id": definition.id,
            "kind": kind,
            "version": version,
            "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "art_sha256": _art_sha256(config, path, definition.name),
        })
        if on_progress is not None:
            on_progress(len(entries), len(configs))
    entries.sort(key=lambda entry: (entry["kind"], entry["id"], entry["version"]))
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
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
