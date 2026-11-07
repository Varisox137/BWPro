"""把 library 卡图的 description 同步为同名、同版本引擎文本的 DIY 渲染格式。"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from client.gui.cardart import _description
from db.loader import CardDatabase
from db.versioning import resolve_at_date


def _source(db: CardDatabase, data: dict):
    """同名条目优先按 id 消歧；历史配置 id 漂移时允许唯一名称回退。"""
    candidates = []
    for kind in ("cards", "shikigami"):
        definitions = getattr(db, kind)
        raw_definitions = getattr(db, f"raw_{kind}")
        for entry_id, definition in definitions.items():
            if definition.name == data.get("name"):
                candidates.append((entry_id, raw_definitions[entry_id]))
    entry_id = data.get("id")
    matched = [raw for candidate, raw in candidates if str(candidate) == str(entry_id)]
    if not matched and len(candidates) == 1:
        matched = [candidates[0][1]]
    return matched[0] if matched else None


def _rendered_text(db: CardDatabase, data: dict) -> str | None:
    raw = _source(db, data)
    if raw is None:
        return None
    try:
        date = int(data.get("version_date", 99999999))
    except (TypeError, ValueError):
        date = 99999999
    resolved = resolve_at_date(raw, date, include_unreleased=True)
    if resolved is None:  # 配置日期早于发布日期时使用首版，而非其他条目
        resolved = resolve_at_date(raw, 99999999, include_unreleased=True)
    text = (resolved or {}).get("text")
    return _description(text, db) if isinstance(text, str) else None


def _replace_description(source: str, description: str) -> str:
    lines = source.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("description:")), None)
    if start is None:
        return source
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    block = yaml.safe_dump({"description": description}, allow_unicode=True,
                           default_flow_style=False)
    newline = "\r\n" if "\r\n" in source else "\n"
    replacement = block.replace("\n", newline)
    return "".join([*lines[:start], replacement, *lines[end:]])


def sync_library(root: Path, *, check: bool = False) -> list[Path]:
    db = CardDatabase.load()
    changed = []
    for path in sorted(root.rglob("*.yaml")):
        source = path.read_text(encoding="utf-8")
        data = yaml.safe_load(source)
        if not isinstance(data, dict) or "description" not in data:
            continue
        description = _rendered_text(db, data)
        if description is None or description == data["description"]:
            continue
        changed.append(path)
        if not check:
            path.write_text(_replace_description(source, description),
                            encoding="utf-8", newline="")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只列出待更新文件，不写入")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "library")
    args = parser.parse_args()
    changed = sync_library(args.root, check=args.check)
    for path in changed:
        print(path)
    print(f"{'待更新' if args.check else '已更新'} {len(changed)} 份卡图描述")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
