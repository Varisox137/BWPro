"""按卡牌 id 保存本机大卡图外观；默认原画与常规牌框不落盘。"""
from __future__ import annotations

import json
from pathlib import Path

FRAME_VARIANTS = {"norm": "常规", "black": "墨染", "blue": "琉璃", "red": "百炼"}
_DEFAULT = {"frame_variant": "norm", "art_index": 0}


def appearance_path() -> Path:
    return Path.home() / ".bwpro" / "card_appearance.json"


def _load_section(path: Path | None, section: str) -> dict[str, dict]:
    path = path or appearance_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        entries = stored[section]
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    if not isinstance(entries, dict):
        return {}
    result = {}
    for definition_id, entry in entries.items():
        if not isinstance(definition_id, str) or not isinstance(entry, dict):
            continue
        variant = entry.get("frame_variant")
        art_index = entry.get("art_index", 0)
        if not isinstance(variant, str) or variant not in FRAME_VARIANTS \
                or variant == "norm" or type(art_index) is not int or art_index != 0:
            continue
        result[definition_id] = {"frame_variant": variant, "art_index": 0}
    return result


def load_card_appearances(path: Path | None = None) -> dict[str, dict]:
    return _load_section(path, "cards")


def load_shikigami_appearances(path: Path | None = None) -> dict[str, dict]:
    return _load_section(path, "shikigami")


def card_appearance(card_id, path: Path | None = None) -> dict:
    return dict(load_card_appearances(path).get(str(card_id), _DEFAULT))


def shikigami_appearance(shikigami_id, path: Path | None = None) -> dict:
    return dict(load_shikigami_appearances(path).get(str(shikigami_id), _DEFAULT))


def definition_appearance(definition, path: Path | None = None) -> dict:
    """式神与卡牌分区存储，避免两类数据 id 的命名空间相互覆盖。"""
    if getattr(definition, "card_type", None) is None:
        return shikigami_appearance(definition.id, path)
    return card_appearance(definition.id, path)


def instance_appearance(card, db, path: Path | None = None) -> dict:
    """生成/复制牌优先继承来源根；普通牌回退到自身本机设置。"""
    source_id = getattr(card, "appearance_source", None) or getattr(card, "origin_id", None)
    source = (db.cards.get(source_id) or db.shikigami.get(source_id)) \
        if source_id is not None else None
    return definition_appearance(source or db.cards[card.id], path)


def entity_appearance(shiki, db, path: Path | None = None) -> dict:
    """小卡继承当前形态/觉醒的外观；基础式神读取独立设置。"""
    if shiki.form is not None:
        return instance_appearance(shiki.form, db, path)
    source = (db.cards[shiki.awakened] if shiki.awakened is not None
              else db.shikigami[shiki.id])
    return definition_appearance(source, path)


def _save_appearance(section: str, definition_id, frame_variant: str, art_index: int,
                     path: Path | None) -> None:
    if not isinstance(frame_variant, str) or frame_variant not in FRAME_VARIANTS:
        raise ValueError(f"非法牌框：{frame_variant}")
    if type(art_index) is not int or art_index != 0:
        raise ValueError("异画选择尚未开放")
    path = path or appearance_path()
    entries = {
        name: _load_section(path, name) for name in ("cards", "shikigami")
    }
    key = str(definition_id)
    if frame_variant == "norm":
        entries[section].pop(key, None)
    else:
        entries[section][key] = {"frame_variant": frame_variant, "art_index": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(
        {"version": 1, **entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def save_card_appearance(card_id, frame_variant: str = "norm", art_index: int = 0,
                         path: Path | None = None) -> None:
    _save_appearance("cards", card_id, frame_variant, art_index, path)


def save_shikigami_appearance(shikigami_id, frame_variant: str = "norm", art_index: int = 0,
                              path: Path | None = None) -> None:
    _save_appearance("shikigami", shikigami_id, frame_variant, art_index, path)
