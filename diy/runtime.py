"""本地 DIY 内容发现、可信机制注册与数据库合并。

content_roots 中的 mechanisms.py 是可信本地审查代码；本模块不提供网络代码加载。
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Iterable

import yaml

from core.events import register_event
from db.loader import CardDatabase, DB_ROOT

BUILTIN_CONTENT_ROOT = Path(__file__).parent / "content"
_MECHANISM_MODULES: dict[str, object] = {}


def discover_extensions(root: Path | str) -> tuple[list[Path], list[Path]]:
    """按包目录先于子目录、同层路径排序发现机制与事件文件。"""
    root = Path(root)
    if not root.is_dir():
        return [], []
    mechanisms = sorted(
        root.rglob("mechanisms.py"),
        key=lambda p: (len(p.relative_to(root).parts), p.relative_to(root).as_posix()))
    events = sorted(
        root.rglob("events.yaml"),
        key=lambda p: (len(p.relative_to(root).parts), p.relative_to(root).as_posix()))
    return mechanisms, events


def _import_mechanism(path: Path) -> None:
    key = str(path.resolve())
    if key in _MECHANISM_MODULES:
        return
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    module_name = f"_bwpro_trusted_diy_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 DIY 机制：{path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(f"DIY 机制注册失败：{path}：{exc}") from exc
    sys.modules[module_name] = module
    _MECHANISM_MODULES[key] = module


def _register_extensions(root: Path) -> None:
    mechanisms, event_files = discover_extensions(root)
    for path in mechanisms:
        _import_mechanism(path)
    for path in event_files:
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for entry in entries:
            register_event(entry["name"], entry.get("timing", "queue"))


def _merge(databases: list[CardDatabase]) -> CardDatabase:
    cards = {}
    shikigami = {}
    raw_cards = {}
    raw_shikigami = {}
    invocations = {}
    raw_invocations = {}
    custom_events = set()
    paths = {}
    for db in databases:
        custom_events |= db.custom_events
        for label, source, raw_source, target, raw_target in (
                ("卡牌", db.cards, db.raw_cards, cards, raw_cards),
                ("式神", db.shikigami, db.raw_shikigami, shikigami, raw_shikigami)):
            for entity_id, definition in source.items():
                if entity_id in cards or entity_id in shikigami:
                    previous = paths.get(entity_id, "未知来源")
                    current = db.paths.get(entity_id, "未知来源")
                    raise RuntimeError(
                        f"{label} id 冲突: {entity_id}（{previous} / {current}）")
                target[entity_id] = definition
                if entity_id in raw_source:
                    raw_target[entity_id] = raw_source[entity_id]
                if entity_id in db.paths:
                    paths[entity_id] = db.paths[entity_id]
        for name, definition in db.invocations.items():
            if name in invocations:
                raise RuntimeError(f"灵咒名冲突: {name}")
            invocations[name] = definition
            if name in db.raw_invocations:
                raw_invocations[name] = db.raw_invocations[name]
    merged = CardDatabase(
        cards, shikigami, custom_events, raw_cards, raw_shikigami,
        invocations=invocations, raw_invocations=raw_invocations, paths=paths)
    errors = merged.validate()
    if errors:
        raise RuntimeError("合并数据库校验失败：\n" + "\n".join(errors))
    return merged


def load_database(
    *,
    official_root: Path | str = DB_ROOT,
    content_roots: Iterable[Path | str] | None = None,
    include_builtin: bool = True,
    include_downloaded: bool = True,
    download_versions: dict[int, str] | None = None,
    at_date: int | None = None,
) -> CardDatabase:
    """加载正式、可信自有与选定的下载内容；下载目录永不执行 Python。"""
    from core.events import CORE_EVENTS, EVENT_TIMING
    from diy.store import downloaded_versions
    from diy.sync import read_package, validate_capabilities

    roots = [Path(p) for p in (content_roots or ())]
    if include_builtin:
        roots.insert(0, BUILTIN_CONTENT_ROOT)
    for root in roots:
        if not root.is_dir():
            raise RuntimeError(f"DIY 内容目录不存在：{root}")
        _register_extensions(root)

    databases = [CardDatabase.load(official_root)]
    packs = {}
    seen = {}

    def add_pack(path: Path, *, downloaded: bool) -> None:
        package = read_package(path)
        pack_id, digest = package["pack_id"], package["content_hash"]
        if pack_id in seen:
            if seen[pack_id] != digest:
                raise RuntimeError(f"DIY 包 id {pack_id} 存在不同内容版本")
            return
        if downloaded:
            allowed_events = set(CORE_EVENTS) | set(EVENT_TIMING)
            validate_capabilities(package, trusted_events=allowed_events)
        loaded = CardDatabase.load(path)
        if downloaded and not loaded.custom_events <= set(CORE_EVENTS) | set(EVENT_TIMING):
            raise RuntimeError(f"下载包 {pack_id} 声明了当前客户端未注册的事件")
        seen[pack_id] = digest
        databases.append(loaded)
        metadata = yaml.safe_load((path / "pack.yaml").read_text(encoding="utf-8")) or {}
        packs[pack_id] = {**metadata, "content_hash": digest,
                          "source": path, "downloaded": downloaded}

    for root in roots:
        for metadata_path in sorted(root.glob("*/pack.yaml")):
            add_pack(metadata_path.parent, downloaded=False)
    if include_downloaded:
        for path in downloaded_versions(selected=download_versions):
            add_pack(path, downloaded=True)
    db = _merge(databases)
    db.diy_packs = packs
    return db.at_date(at_date) if at_date is not None else db
