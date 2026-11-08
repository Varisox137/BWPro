"""按卡牌 id 保存本机大卡图外观；默认原画与常规牌框不落盘。"""
from __future__ import annotations

import json
from pathlib import Path

FRAME_VARIANTS = {"norm": "常规", "blue": "琉璃", "black": "墨染", "red": "百炼"}
_DEFAULT = {"frame_variant": "norm", "art_index": 0}


def appearance_path() -> Path:
    return Path.home() / ".bwpro" / "card_appearance.json"


def load_card_appearances(path: Path | None = None) -> dict[str, dict]:
    path = path or appearance_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        entries = stored["cards"]
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    if not isinstance(entries, dict):
        return {}
    result = {}
    for card_id, entry in entries.items():
        if not isinstance(card_id, str) or not isinstance(entry, dict):
            continue
        variant = entry.get("frame_variant")
        art_index = entry.get("art_index", 0)
        if not isinstance(variant, str) or variant not in FRAME_VARIANTS \
                or variant == "norm" or type(art_index) is not int or art_index != 0:
            continue
        result[card_id] = {"frame_variant": variant, "art_index": 0}
    return result


def card_appearance(card_id, path: Path | None = None) -> dict:
    return dict(load_card_appearances(path).get(str(card_id), _DEFAULT))


def save_card_appearance(card_id, frame_variant: str = "norm", art_index: int = 0,
                         path: Path | None = None) -> None:
    if not isinstance(frame_variant, str) or frame_variant not in FRAME_VARIANTS:
        raise ValueError(f"非法牌框：{frame_variant}")
    if type(art_index) is not int or art_index != 0:
        raise ValueError("异画选择尚未开放")
    path = path or appearance_path()
    entries = load_card_appearances(path)
    key = str(card_id)
    if frame_variant == "norm":
        entries.pop(key, None)
    else:
        entries[key] = {"frame_variant": frame_variant, "art_index": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(
        {"version": 1, "cards": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(path)
