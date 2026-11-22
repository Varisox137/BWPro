"""对局内卡牌选项的统一展示模型与解析。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.model import CardInstance


_ART_OPTION_KEYS = (
    "display", "burst", "level_color", "frame_variant", "description_suffix",
    "status", "cache_context", "appearance_source",
)
_VIRTUAL_KINDS = {"field_summon_pick", "pick_generate"}


@dataclass
class CardOption:
    answer: Any
    cdef: Any | None
    instance: CardInstance | None = None
    art_options: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    reason: str | None = None
    label: str | None = None


def runtime_art_options(runtime: dict | None) -> dict:
    runtime = runtime or {}
    out = {}
    if runtime.get("render") is not None:
        out["display"] = runtime["render"]
    if runtime.get("description_suffix") is not None:
        out["description_suffix"] = runtime["description_suffix"]
    return out


def _preview_art_options(preview: dict | None) -> dict:
    preview = preview or {}
    return {key: preview[key] for key in _ART_OPTION_KEYS if key in preview}


def _find_instance(game, pending: dict, value) -> CardInstance | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    player = game.state.players[pending["player"]]
    for zone in player.zones.values():
        card = next((card for card in zone if card.uid == value), None)
        if card is not None:
            return card
    for candidate in game.state.players:
        for shikigami in candidate.shikigami:
            if shikigami.form is not None and shikigami.form.uid == value:
                return shikigami.form
        for field_state in candidate.fields:
            if field_state.card.uid == value:
                return field_state.card
    return None


def resolve_card_option(game, viewer: int, pending: dict, value,
                        preview: dict | None = None) -> CardOption:
    """把作答值解析为真实实例选项，或由数据 id 与覆写组成的虚拟预览。"""
    kind = pending.get("kind")
    instance = None
    preview = preview or {}
    value_is_definition = kind in _VIRTUAL_KINDS or kind == "card_name"
    if preview.get("uid") == value or (not value_is_definition and "card_id" not in preview):
        instance = _find_instance(game, pending, value)
    if instance is not None:
        cdef = game.db.cards[instance.id]
    else:
        card_id = (preview or {}).get("card_id")
        if card_id is None and (kind in _VIRTUAL_KINDS or
                                (kind == "card_name" and pending.get("stage") != "shikigami")):
            card_id = value
        cdef = game.db.cards.get(card_id) if card_id is not None else None

    label = (preview or {}).get("label")
    if cdef is None and label is None:
        if kind == "card_name" and pending.get("stage") == "shikigami":
            shikigami = game.db.shikigami.get(value)
            label = shikigami.name if shikigami is not None else str(value)
        elif kind == "invocation_pick":
            invocation = game.db.invocations.get(value)
            label = f"{value}\n{invocation.text if invocation is not None else ''}"
        else:
            label = str(value)
    art_options = _preview_art_options(preview)
    source_id = ((instance.appearance_source or instance.origin_id)
                 if instance is not None else pending.get("appearance_source"))
    if source_id is not None:
        art_options.setdefault("appearance_source", source_id)
    return CardOption(
        answer=value, cdef=cdef, instance=instance,
        art_options=art_options,
        enabled=preview.get("enabled", preview.get("ok", True)),
        reason=preview.get("reason"), label=label,
    )


def usage_card_option(game, player: int, card: CardInstance, usage: dict,
                      runtime: dict | None = None) -> CardOption:
    """手牌使用方式复用同一模型；真实子牌不伪造实例身份。"""
    cdef = game.db.cards.get(usage.get("card_id"), game.db.cards[card.id])
    is_main_card = cdef.id == card.id
    art_options = runtime_art_options(runtime) if is_main_card else {}
    source_id = card.appearance_source or card.origin_id or (None if is_main_card else card.id)
    if source_id is not None:
        art_options["appearance_source"] = source_id
    energy = usage.get("energy", 0)
    is_burst = bool(usage.get("is_burst"))
    if energy == "X":
        owner = game.state.players[player]
        seat = (game._find_card_owner(owner, cdef.shikigami)
                if cdef.shikigami is not None else None)
        burst = owner.shikigami[seat].energy if seat is not None else 0
    else:
        burst = energy if type(energy) is int and (energy > 0 or is_burst) else None
    if burst is not None:
        art_options["burst"] = burst
    return CardOption(
        answer=usage["id"], cdef=cdef, instance=card if is_main_card else None,
        art_options=art_options, enabled=usage.get("ok", True),
        reason=usage.get("reason"), label=usage.get("label"),
    )
