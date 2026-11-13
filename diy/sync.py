"""DIY 完整包的规范化、内容哈希与纯 YAML 校验。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from db.loader import CardDatabase, _inject_derived
from db.schema import CardDef, InvocationDef, ShikigamiDef
from db.versioning import resolve_latest

MAX_PACKS = 32
MAX_PACK_FILES = 128
MAX_PACK_FILE_BYTES = 256 * 1024
MAX_PACK_BYTES = 512 * 1024
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_path(name: str) -> str:
    if not isinstance(name, str) or "\\" in name:
        raise ValueError("DIY 文件路径非法")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("DIY 文件路径非法")
    if path.suffix != ".yaml":
        raise ValueError("联机 DIY 同步只允许 YAML 文件")
    return path.as_posix()


def _parse_files(files: dict[str, str]) -> dict[str, Any]:
    if not isinstance(files, dict) or not files:
        raise ValueError("DIY 包文件表为空或结构非法")
    if len(files) > MAX_PACK_FILES:
        raise ValueError(f"DIY 包文件数超过上限 {MAX_PACK_FILES}")
    if "pack.yaml" not in files:
        raise ValueError("DIY 包缺少 pack.yaml")
    total = 0
    documents = {}
    for raw_name, text in files.items():
        name = _validate_path(raw_name)
        if not isinstance(text, str):
            raise ValueError(f"DIY 文件 {name} 不是 UTF-8 YAML 文本")
        size = len(text.encode("utf-8"))
        if size > MAX_PACK_FILE_BYTES:
            raise ValueError(f"DIY 文件 {name} 超过大小上限")
        total += size
        if total > MAX_PACK_BYTES:
            raise ValueError(f"DIY 包总大小超过上限 {MAX_PACK_BYTES}")
        try:
            documents[name] = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(f"DIY 文件 {name} 不是合法 YAML：{error}") from error
    return documents


def _json_value(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("DIY YAML 映射键须为字符串")
            result[key] = _json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return {"$date": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("DIY YAML 不允许非有限浮点数")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"DIY YAML 含不支持的数据类型 {type(value).__name__}")


def content_hash(files: dict[str, str]) -> str:
    documents = _parse_files(files)
    metadata = documents.get("pack.yaml")
    if not isinstance(metadata, dict):
        raise ValueError("pack.yaml 须为映射")
    documents["pack.yaml"] = {k: v for k, v in metadata.items() if k != "content_hash"}
    canonical = json.dumps(_json_value(documents), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_package_data(files: dict[str, str]) -> dict:
    documents = _parse_files(files)
    metadata = documents["pack.yaml"]
    if not isinstance(metadata, dict) or not isinstance(metadata.get("id"), int) \
            or isinstance(metadata.get("id"), bool):
        raise ValueError("pack.yaml 缺少合法包 id")
    normalized = {name: files[name] for name in sorted(files)}
    return {"pack_id": metadata["id"], "content_hash": content_hash(normalized),
            "files": normalized}


def read_package(path: Path | str) -> dict:
    path = Path(path)
    files = {}
    for file in sorted(path.rglob("*.yaml")):
        name = file.relative_to(path).as_posix()
        files[name] = file.read_text(encoding="utf-8")
    return read_package_data(files)


def validate_package(package: dict, *, expected_pack_id: int | None = None,
                     expected_hash: str | None = None) -> dict:
    if not isinstance(package, dict):
        raise ValueError("DIY 包结构非法")
    validated = read_package_data(package.get("files"))
    pack_id = package.get("pack_id")
    supplied_hash = package.get("content_hash")
    if pack_id != validated["pack_id"]:
        raise ValueError("DIY 包 id 与 pack.yaml 不一致")
    if supplied_hash != validated["content_hash"]:
        raise ValueError("DIY 包内容哈希不匹配")
    if expected_pack_id is not None and pack_id != expected_pack_id:
        raise ValueError("上传的 DIY 包 id 与请求不一致")
    if expected_hash is not None and supplied_hash != expected_hash:
        raise ValueError("上传的 DIY 包内容哈希与请求不一致")
    return validated


def validate_manifest(entries) -> dict[int, str]:
    if not isinstance(entries, list) or len(entries) > MAX_PACKS:
        raise ValueError(f"DIY 包清单须为至多 {MAX_PACKS} 项的列表")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("DIY 包清单项结构非法")
        pack_id, digest = entry.get("pack_id"), entry.get("content_hash")
        if not isinstance(pack_id, int) or isinstance(pack_id, bool) \
                or not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            raise ValueError("DIY 包清单项须含合法 pack_id 与 content_hash")
        if pack_id in result:
            raise ValueError(f"DIY 包清单包含重复包 id {pack_id}")
        result[pack_id] = digest
    return result


def collect_packages(roots: Iterable[Path | str]) -> dict[int, dict]:
    packages = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for metadata_path in sorted(root.glob("*/pack.yaml")):
            package = read_package(metadata_path.parent)
            pack_id = package["pack_id"]
            previous = packages.get(pack_id)
            if previous is not None:
                if previous["content_hash"] != package["content_hash"]:
                    raise ValueError(f"DIY 包 id {pack_id} 存在不同内容版本")
                continue
            packages[pack_id] = package
    return packages


def package_manifest(packages: dict[int, dict]) -> list[dict]:
    return [{"pack_id": pack_id, "content_hash": packages[pack_id]["content_hash"]}
            for pack_id in sorted(packages)]


def validate_capabilities(package: dict, *, trusted_events: set[str]) -> None:
    from core import registry, targets
    from core.actions import ACTIONS

    metadata = yaml.safe_load(package["files"]["pack.yaml"]) or {}
    requires = metadata.get("requires") or {}
    if not isinstance(requires, dict):
        raise ValueError("pack.yaml 的 requires 须为映射")
    available = {
        "actions": set(ACTIONS),
        "conditions": set(registry.CONDITIONS),
        "pools": set(targets.POOLS),
        "stat_auras": set(registry.STAT_AURAS),
        "events": set(trusted_events),
    }
    labels = {"actions": "动作", "conditions": "条件", "pools": "目标池",
              "stat_auras": "动态光环", "events": "事件"}
    for kind, registry_names in available.items():
        requested = requires.get(kind) or []
        if not isinstance(requested, list) or not all(isinstance(v, str) for v in requested):
            raise ValueError(f"pack.yaml 的 requires.{kind} 须为字符串列表")
        missing = sorted(set(requested) - registry_names)
        if missing:
            raise ValueError(f"当前版本缺少 DIY 包所需的{labels[kind]}：{'、'.join(missing)}")


def database_from_package(package: dict) -> CardDatabase:
    documents = _parse_files(package["files"])
    cards, shikigami = {}, {}
    raw_cards, raw_shikigami = {}, {}
    invocations, raw_invocations = {}, {}
    custom_events, paths = set(), {}
    for name, data in documents.items():
        source = f"DIY {package['pack_id']}:{name}"
        if name == "pack.yaml":
            continue
        if path_name(name) == "events.yaml":
            entries = data or []
            if not isinstance(entries, list):
                raise ValueError(f"{source} 须为事件列表")
            for entry in entries:
                custom_events.add(entry["name"])
            continue
        if path_name(name) == "invocations.yaml":
            for entry in (data or {}).get("invocations") or []:
                resolved = resolve_latest(entry)
                if resolved is None:
                    raise ValueError(f"{source}: 灵咒没有可用版本")
                definition = InvocationDef.model_validate(resolved)
                if definition.name in invocations:
                    raise ValueError(f"灵咒名重复：{definition.name}")
                invocations[definition.name] = definition
                raw_invocations[definition.name] = entry
            continue
        resolved = resolve_latest(data)
        if resolved is None:
            raise ValueError(f"{source}: versions.history 无可用快照")
        _inject_derived(resolved)
        target = cards if "card_type" in resolved else shikigami
        raw_target = raw_cards if target is cards else raw_shikigami
        definition = (CardDef if target is cards else ShikigamiDef).model_validate(resolved)
        if definition.id in cards or definition.id in shikigami:
            raise ValueError(f"DIY 实体 id 重复：{definition.id}")
        target[definition.id] = definition
        raw_target[definition.id] = data
        paths[definition.id] = source
    db = CardDatabase(cards, shikigami, custom_events, raw_cards, raw_shikigami,
                      invocations=invocations, raw_invocations=raw_invocations, paths=paths)
    errors = db.validate()
    if errors:
        raise ValueError("DIY 包校验失败：" + "；".join(errors))
    return db


def path_name(name: str) -> str:
    return PurePosixPath(name).name
