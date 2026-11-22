"""GUI 与服务端共用的对局展示数据，不包含终端交互。"""
from __future__ import annotations

from core.engine import Game


def _seat_map(p) -> dict[int, int]:
    """式神数据 id → 座次下标（召唤物坑位 ≥4，无座次色）。"""
    return {s.id: i for i, s in enumerate(p.shikigami)}


def _live_enhance(p, c) -> int:
    """实时增强计数：持久 store + 实例已装配；实例打出前不含持久计数。"""
    store = p.card_mods.get(c.id, {})
    return int(store.get("enhance", 0)) + int(c.mods.get("enhance", 0))


_ENHANCE_OP_CN = {"damage": "伤害", "heal": "治疗", "set_health": "生命变为"}


def _card_render_stats(game: Game, p, c) -> dict[str, int]:
    cd = game.db.cards[c.id]
    live = _live_enhance(p, c)
    if live != int(c.mods.get("enhance", 0)):
        c = c.model_copy(update={"mods": {**c.mods, "enhance": live}})
    if cd.card_type == "combat":
        seat = _seat_map(p).get(cd.shikigami) if cd.shikigami is not None else None
        shiki = p.shikigami[seat] if seat is not None else None
        power, shield = game.combat_card_stats(cd.effects, c, shiki, p)
        return {"power+": power, "shield+": shield}
    if cd.card_type == "field":
        return {"durability": cd.intensity + int(c.mods.get("intensity_boost", 0))}
    if cd.card_type == "form" and cd.form_power is not None:
        bonus = 0
        if any(isinstance((stp.model_extra or {}).get("amount"), dict)
               and (stp.model_extra or {})["amount"].get("dice_distinct")
               for stp in cd.effects.steps):
            bonus = len(set(p.ext.get("dice_history", [])))
        return {"power": cd.form_power + bonus,
                "health": cd.form_health + bonus}
    if cd.subtype == "awaken":
        power = health = 0
        for step in cd.effects.steps:
            extra = step.model_extra or {}
            if not extra.get("perm") or not isinstance(extra.get("amount"), int):
                continue
            if step.op == "buff_power":
                power += extra["amount"]
            elif step.op == "buff_health":
                health += extra["amount"]
        return {"power+": power, "health+": health}
    return {}


def _stats_label(game: Game, p, c, render=None) -> str:
    """战斗牌、形态、觉醒与增强效果的实时数值段。"""
    cd = game.db.cards[c.id]
    parts: list[str] = []
    render = _card_render_stats(game, p, c) if render is None else render
    if cd.card_type == "combat":
        power, shield = render["power+"], render["shield+"]
        if power:
            parts.append(f"力量{power:+d}")
        if shield:
            parts.append(f"护甲+{shield}")
    elif cd.card_type == "form" and cd.form_power is not None:
        parts.append(f"身材{render['power']}/{render['health']}")
    elif cd.card_type == "field":
        parts.append(f"耐久{render['durability']}")
    else:
        live = _live_enhance(p, c)
        if live != int(c.mods.get("enhance", 0)):
            c = c.model_copy(update={"mods": {**c.mods, "enhance": live}})
        for stp in cd.effects.steps:
            amt = (stp.model_extra or {}).get("amount")
            if isinstance(amt, dict) and amt.get("enhance") and stp.op in _ENHANCE_OP_CN:
                val = int(amt.get("base", 0)) + live
                parts.append(f"{_ENHANCE_OP_CN[stp.op]}{val}")
    if cd.subtype == "awaken":
        power, health = render["power+"], render["health+"]
        if power or health:
            parts.append(f"觉醒{power:+d}/{health:+d}")
    return " ".join(parts)


KEYWORD_CN = {
    "fast": "瞬发", "trigger": "响应", "combo": "连击", "initiative": "先攻",
    "piercing": "贯通", "pierce": "穿刺", "remote": "远程", "unyielding": "不屈",
    "haste": "迅捷", "barrier": "屏障", "enraged": "激怒",
}
_KEYWORD_HIDDEN = {"keep_attack_buffs", "pierce_armor"}


def _kw_labels(kws) -> list[str]:
    return [KEYWORD_CN.get(k, k) for k in kws if k not in _KEYWORD_HIDDEN]


def _quest_progress(game: Game, p, cd, card=None) -> str | None:
    """委托条件进度标签；紧急委托读当前手牌实例，其余读牌手全局账本。"""
    pc = cd.play_condition
    if not pc:
        return None
    if "quest_count_ge" in pc:
        q = pc["quest_count_ge"]
        kind, need = q.get("kind"), int(q.get("count", 0))
        have = (card.mods.get("quest_progress", {}).get(kind, 0)
                if card is not None and "urgent_quest" in cd.tags
                else p.quest_counts.get(kind, 0))
        label = _QUEST_KIND_LABELS.get(kind, str(kind))
        mark = " ✓" if have >= need else ""
        return f"委托:{label}{have}/{need}{mark}"
    return None


_QUEST_KIND_LABELS = {
    "assault": "出击", "draw": "抽牌", "play": "用牌", "damage": "伤害",
    "effect_damage": "非战斗伤害", "attack": "攻击", "form_play": "形态牌",
    "offdeck_play": "套牌外", "enemy_defeat": "敌式神气绝",
    "revive": "己方复活", "quest_used": "委托使用", "round": "回合",
}


def _enhance_description_suffix(game: Game, p, c) -> str | None:
    """角标未覆盖的实时增强与条件计数；只读现有实例修饰/账本。"""
    cd = game.db.cards[c.id]
    live = _live_enhance(p, c)
    if c.id == 10030506 and p.ext.get("self_damage_taken"):
        live += 1
    labels = {**_ENHANCE_OP_CN, "buff_power": "力量", "buff_health": "生命",
              "gain_shield": "护甲"}
    parts = []
    if live:
        if c.id in (10011108, 10012703):
            parts.append(f"效果{live:+d}")
        else:
            for step in cd.effects.steps:
                extra = step.model_extra or {}
                amount = extra.get("amount")
                if not isinstance(amount, dict) or not amount.get("enhance") \
                        or step.op not in labels:
                    continue
                target_kind = getattr(step.target, "kind", None)
                badge_covered = (cd.card_type == "combat"
                                 and step.op in ("buff_power", "gain_shield")
                                 and target_kind in (None, "self")
                                 and not extra.get("perm") and not extra.get("no_extract"))
                if not badge_covered:
                    parts.append(f"{labels[step.op]}{live:+d}")
    damage_boost = int(c.mods.get("damage_boost", 0))
    if damage_boost and any(step.op == "damage" for step in cd.effects.steps):
        parts.append(f"伤害{damage_boost:+d}")
    shield_boost = int(c.mods.get("shield_boost", 0))
    if shield_boost and c.id in (10030951, 10030952):
        parts.append(f"效果{shield_boost:+d}")

    special = []
    if c.id == 10010408:
        special.append(f"已使用{p.card_mods.get(c.id, {}).get('spell_count', 0)}次法术")
    elif c.id == 10011303:
        history = p.ext.get("dice_history", [])
        if history:
            special.append(f"已投出：{','.join(str(value) for value in history)}")
    elif c.id == 10011608:
        seat = _seat_map(p).get(cd.shikigami)
        bonus = p.shikigami[seat].perm_power if seat is not None else 0
        if bonus:
            special.append(f"伤害{bonus:+d}")
    elif c.id == 10011804:
        special.append(f"造成{len(p.hand) // 2}点伤害")
    elif c.id == 10012904:
        special.append(f"已成功{sum(q.ext.get('luck_success_game', 0)
                                  for q in game.state.players)}次")
    elif c.id == 10013006:
        special.append(f"已造成{p.ext.get('yaohu_damage_count', 0)}次伤害")
    elif c.id == 10030706:
        count = sum(1 for shiki in p.shikigami
                    if shiki.in_play and shiki.countdown_block is not None
                    and shiki.id != cd.shikigami)
        if count:
            special.append(f"效果{count:+d}")
    elif c.id == 10012403:
        history = set(p.ext.get("countdown_history", []))
        replay = (
            (100124, "为所有己方角色恢复3点生命"),
            (10012401, "造成4点伤害，随机分配给所有敌方角色"),
            (10012406, "己方其他式神倒计时-1并获得1力量与1生命"),
            (10012407, "抽一张牌，获得1点鬼火"),
        )
        special.extend(f"[倒计时3]：{{{text}}}" for source, text in replay
                       if source in history)

    quest = cd.play_condition or {}
    if "quest_count_ge" in quest:
        spec = quest["quest_count_ge"]
        kind = spec["kind"]
        have = (c.mods.get("quest_progress", {}).get(kind, 0)
                if "urgent_quest" in cd.tags else p.quest_counts.get(kind, 0))
        if kind == "round":
            text = f"剩余{max(0, int(spec['count']) - have)}回合"
        else:
            label = {
                "assault": f"已出击{have}次", "draw": f"已抽{have}张牌",
                "play": f"已使用{have}张牌", "damage": f"已造成{have}点伤害",
                "effect_damage": f"已造成{have}点伤害", "attack": f"已攻击{have}次",
                "form_play": f"已使用{have}张牌", "offdeck_play": f"已使用{have}张牌",
                "enemy_defeat": f"已消灭{have}名式神", "revive": f"已复活{have}名式神",
                "quest_used": f"已使用过{have}张牌",
            }.get(kind, f"{kind}:{have}")
            text = label
        special.append(text)
    suffix = f"（{'，'.join(parts)}）" if parts else ""
    suffix += "".join(f"（{text}）" for text in special)
    return suffix or None


def deck_invocation_counts(game: Game, pi: int) -> dict[str, int]:
    """牌库中每种灵咒的公开数量，不暴露具体卡牌身份。"""
    counts: dict[str, int] = {}
    for card in game.state.players[pi].deck:
        for invocation in card.invocations:
            name = str(invocation.get("name", ""))
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def hand_cards_info(game: Game, pi: int) -> dict[int, dict]:
    """返回己方手牌的实时展示数据，供 GUI 与联机状态负载共用。"""
    p = game.state.players[pi]
    out: dict[int, dict] = {}
    for c in p.hand:
        cd = game.db.cards[c.id]
        render = _card_render_stats(game, p, c)
        out[c.uid] = {
            "cost": cd.cost + c.mods.get("cost_delta", 0),
            "keywords": _kw_labels(sorted(game._card_keywords(p, cd, c))),
            "stats": _stats_label(game, p, c, render=render),
            "render": render,
            "enhance": _live_enhance(p, c),
            "description_suffix": _enhance_description_suffix(game, p, c),
            "quest": _quest_progress(game, p, cd, c),
            "playable": game._play_condition_met(p, cd, c),
            "usage": game.usage_options(pi, c),
        }
    return out


def result_text(winner: int | None, player_names, viewer: int | None = None) -> str:
    """对局结果文本：viewer 指定时按自身视角，否则按玩家名。"""
    if winner is None:
        return "对局中断"
    if winner == -1:
        return "双方平局"
    if viewer is None:
        return f"{player_names[winner]} 获胜！"
    return "自身胜利！" if winner == viewer else "自身落败……"
