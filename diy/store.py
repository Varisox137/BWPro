"""联机下载 DIY 内容的版本化、原子存储与受保护清理。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from diy.sync import (
    MAX_PACK_BYTES, MAX_PACK_FILE_BYTES, MAX_PACK_FILES,
    read_package, read_package_data, validate_package,
)

MARKER_NAME = ".download.json"


def download_root() -> Path:
    return Path.home() / ".bwpro" / "diy"


def _write_package_files(directory: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def save_download(package: dict, *, root: Path | str | None = None) -> Path:
    package = validate_package(package)
    root = Path(root) if root is not None else download_root()
    pack_id, digest = package["pack_id"], package["content_hash"]
    pack_root = root / str(pack_id)
    target = pack_root / digest
    pack_root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        marker = target / MARKER_NAME
        if not marker.is_file() or read_package(target)["content_hash"] != digest:
            raise ValueError("下载目录已存在但内容不匹配；请另存为新的自有版本")
        return target
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", suffix=".tmp", dir=pack_root))
    try:
        _write_package_files(temporary, package["files"])
        marker = {
            "source": "downloaded", "pack_id": pack_id, "content_hash": digest,
            "received_at": time.time(),
        }
        (temporary / MARKER_NAME).write_text(
            json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def _read_zip_package(path: Path) -> dict:
    files = {}
    with zipfile.ZipFile(path) as archive:
        entries = [info for info in archive.infolist()
                   if not info.is_dir() and info.filename.endswith(".yaml")]
        if len(entries) > MAX_PACK_FILES:
            raise ValueError("DIY ZIP 文件数超过上限")
        pack_entries = [info for info in entries
                        if info.filename == "pack.yaml"
                        or info.filename.endswith("/pack.yaml")]
        if len(pack_entries) != 1:
            raise ValueError("DIY ZIP 必须且只能包含一个 pack.yaml")
        prefix = pack_entries[0].filename[:-len("pack.yaml")]
        total = 0
        for info in entries:
            if not info.filename.startswith(prefix):
                raise ValueError("DIY ZIP 不得包含多个内容包")
            if info.file_size > MAX_PACK_FILE_BYTES:
                raise ValueError(f"DIY 文件 {info.filename} 超过大小上限")
            total += info.file_size
            if total > MAX_PACK_BYTES:
                raise ValueError("DIY ZIP 总大小超过上限")
            name = info.filename[len(prefix):]
            files[name] = archive.read(info).decode("utf-8")
    return read_package_data(files)


def import_package(source: Path | str, *, root: Path | str | None = None) -> Path:
    """从目录、协议 JSON 或单包 ZIP 导入只读 DIY 内容并纳入下载存储。"""
    source = Path(source)
    if source.is_dir():
        package = read_package(source)
    elif source.suffix.lower() == ".json":
        package = validate_package(json.loads(source.read_text(encoding="utf-8")))
    elif source.suffix.lower() == ".zip":
        package = _read_zip_package(source)
    else:
        raise ValueError("DIY 导入须为包目录、.json 或 .zip 文件")
    from core.events import CORE_EVENTS, EVENT_TIMING
    from diy.runtime import _merge, load_database
    from diy.sync import database_from_package, validate_capabilities

    validate_capabilities(package, trusted_events=set(CORE_EVENTS) | set(EVENT_TIMING))
    _merge([load_database(), database_from_package(package)])
    return save_download(package, root=root)


def downloaded_versions(*, root: Path | str | None = None,
                        selected: dict[int, str] | None = None) -> list[Path]:
    root = Path(root) if root is not None else download_root()
    if not root.is_dir():
        return []
    grouped = {}
    for marker in sorted(root.glob(f"*/*/{MARKER_NAME}")):
        directory = marker.parent
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            pack_id = int(directory.parent.name)
            digest = directory.name
            if info.get("source") != "downloaded" or info.get("pack_id") != pack_id \
                    or info.get("content_hash") != digest:
                continue
            if selected is not None and selected.get(pack_id) != digest:
                continue
            package = read_package(directory)
            if package["pack_id"] != pack_id or package["content_hash"] != digest:
                raise ValueError(
                    f"下载包 {pack_id} 的内容已修改；请另存为新的自有版本")
            grouped.setdefault(pack_id, []).append((float(info.get("received_at", 0)), directory))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"下载 DIY 内容损坏：{directory}：{error}") from error
    result = []
    for pack_id, versions in grouped.items():
        result.append(max(versions, key=lambda item: item[0])[1])
    return sorted(result)


def _marked_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result = []
    for marker in sorted(root.glob(f"*/*/{MARKER_NAME}")):
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if info.get("source") == "downloaded" \
                and info.get("pack_id") == _int_or_none(marker.parent.parent.name) \
                and info.get("content_hash") == marker.parent.name:
            result.append(marker.parent)
    return result


def _int_or_none(value):
    try:
        return int(value)
    except ValueError:
        return None


def download_stats(root: Path | str | None = None) -> dict[str, int]:
    root = Path(root) if root is not None else download_root()
    directories = _marked_directories(root)
    size = sum(path.stat().st_size for directory in directories
               for path in directory.rglob("*") if path.is_file())
    return {"packs": len({directory.parent.name for directory in directories}),
            "versions": len(directories), "bytes": size}


def clear_downloaded(root: Path | str | None = None, *,
                     active: set[tuple[int, str]] | None = None) -> dict[str, int]:
    root = Path(root) if root is not None else download_root()
    active = active or set()
    directories = _marked_directories(root)
    if any((int(directory.parent.name), directory.name) in active for directory in directories):
        raise ValueError("当前房间正在使用相关下载包，请先离开该 DIY 房间")
    stats = download_stats(root)
    for directory in directories:
        shutil.rmtree(directory)
        parent = directory.parent
        try:
            parent.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
    return stats
