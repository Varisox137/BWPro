"""调试指令注册表。

调试指令通过 Game.apply 的 cmd dict 入口调用，op 以 "debug_" 开头。
设计目标：
- 可扩展：新增命令只需用 @debug_command 注册一个函数。
- 与正常指令协议隔离，便于服务端后续按环境启用/禁用。
- 本地 CLI/测试默认启用；authoritative 服务器应避免向客户端暴露这些 op。

注意：调试指令会绕过部分游戏规则（费用、等级、合法性检查等），仅用于开发、测试与复现。
"""
from __future__ import annotations

from typing import Any, Callable

from core.model import CardInstance, PlayerState, Ref, ShikigamiState

DEBUG_COMMANDS: dict[str, Callable] = {}


def debug_command(name: str) -> Callable:
    """注册一个调试指令。"""
    def deco(fn: Callable) -> Callable:
        DEBUG_COMMANDS[name] = fn
        return fn
    return deco


@debug_command("give_card")
def cmd_give_card(game, ctx, *, player: int, card_id: int, zone: str = "hand", count: int = 1) -> None:
    """生成 count 张 card_id 到 player 的指定区域（zone 不存在则创建）。"""
    if not (0 <= player < len(game.state.players)):
        raise ValueError(f"玩家下标越界: {player}")
    if card_id not in game.db.cards:
        raise ValueError(f"卡牌 id 不存在: {card_id}")
    p = game.state.players[player]
    for _ in range(count):
        card = CardInstance(uid=game.state.next_uid, id=card_id)
        game.state.next_uid += 1
        game.move_card(p, card, zone)
    game._log(f"[调试] 给 {p.name} 的 {zone} 生成了 {count} 张 {game.db.cards[card_id].name}")


@debug_command("set_stat")
def cmd_set_stat(game, ctx, *, target: dict, key: str, value: Any) -> None:
    """直接修改实体属性。

    target: {player, shikigami?} 的字典，会被解析为 Ref。
    key 支持：
      - 牌手：health, max_health, orb, shield, defeated
      - 式神：health, max_health, base_power, perm_power, temp_power, shield,
              level, defeated, despawned, revive_countdown
    value 类型需与字段匹配（bool 用于 defeated/despawned）。
    """
    ref = Ref(**target)
    p = game.state.players[ref.player]
    if ref.shikigami is None:
        _set_player_stat(p, key, value)
    else:
        s = p.shikigami[ref.shikigami]
        _set_shikigami_stat(s, key, value)
    game._log(f"[调试] 设置 {ref} 的 {key} = {value}")


def _set_player_stat(p: PlayerState, key: str, value: Any) -> None:
    allowed = {"health", "max_health", "orb", "shield", "defeated"}
    if key not in allowed:
        raise ValueError(f"牌手不支持修改的属性: {key}（支持: {allowed}）")
    if key == "defeated" and not isinstance(value, bool):
        raise ValueError("defeated 必须是 bool")
    setattr(p, key, value)


def _set_shikigami_stat(s: ShikigamiState, key: str, value: Any) -> None:
    allowed = {
        "health", "max_health", "base_power", "perm_power", "temp_power",
        "shield", "level", "defeated", "despawned", "revive_countdown",
    }
    if key not in allowed:
        raise ValueError(f"式神不支持修改的属性: {key}（支持: {allowed}）")
    if key in ("defeated", "despawned") and not isinstance(value, bool):
        raise ValueError(f"{key} 必须是 bool")
    setattr(s, key, value)


@debug_command("play_card")
def cmd_play_card(game, ctx, *, player: int, uid: int, target: dict | None = None,
                  play_method: str | None = None) -> None:
    """强制模拟一次主动使用牌：跳过费用、等级、目标合法性检查。

    卡牌必须存在于玩家的某个区域中（可用 debug_give_card 生成）。
    若指定 play_method，则使用该方式的效果块；否则使用卡牌基础效果。
    """
    if not (0 <= player < len(game.state.players)):
        raise ValueError(f"玩家下标越界: {player}")
    p = game.state.players[player]
    card = next((c for zone in p.zones.values() for c in zone if c.uid == uid), None)
    if card is None:
        raise ValueError(f"玩家 {player} 各区域中找不到 uid={uid} 的卡牌")
    cdef = game.db.cards[card.id]
    method = None
    if play_method is not None:
        method = next((m for m in cdef.methods if m.id == play_method), None)
        if method is None:
            raise ValueError(f"卡牌 {cdef.name} 没有使用方式 {play_method}")

    # 确定 source：中立牌无来源，否则按所属式神查找局内下标
    si: int | None = None
    if cdef.shikigami is not None:
        si = game._find_shikigami(p, cdef.shikigami)
    source = Ref(player=player, shikigami=si) if si is not None else None

    chosen: list[Ref] = [Ref(**target)] if target else []
    game.move_card(p, card, "graveyard")
    how = f"（{method.text or method.id}）" if method else ""
    game._log(f"[调试] {p.name} 强制使用《{cdef.name}》{how}")
    block = method.effects if (method and method.effects is not None) else cdef.effects
    from core.engine import ExecContext

    game._resolve_block(block, ExecContext(controller=player, source=source, card=card, chosen=chosen))
    game.emit("on_card_played", player=player, uid=uid)


@debug_command("assault")
def cmd_assault(game, ctx, *, player: int, index: int) -> None:
    """强制模拟一次出击：跳过鬼火、出击次数、0 级等检查。

    直接把攻击者移入战斗区并按（反击，攻击）顺序造成战斗伤害。
    """
    if not (0 <= player < len(game.state.players)):
        raise ValueError(f"玩家下标越界: {player}")
    p = game.state.players[player]
    if not (0 <= index < len(p.shikigami)):
        raise ValueError(f"式神下标越界: {index}")
    s = p.shikigami[index]
    game._enter_combat(p, index)
    atk_ref = Ref(player=player, shikigami=index)
    defender_idx = 1 - player
    d = game.state.players[defender_idx]
    game._log(f"[调试] {p.name} 强制让 {game.db.shikigami[s.id].name} 出击")
    vic_idx = d.combat_index
    if vic_idx is None:
        game.deal_to_player(defender_idx, s.eff_power, atk_ref)
    else:
        vic_ref = Ref(player=defender_idx, shikigami=vic_idx)
        vic_s = d.shikigami[vic_idx]
        a_eff, d_eff = s.eff_power, vic_s.eff_power
        game._hurt_shikigami(atk_ref, d_eff, vic_ref)
        game._hurt_shikigami(vic_ref, a_eff, atk_ref)
        game.check_defeated(atk_ref, source=vic_ref, reason="战斗")
        game.check_defeated(vic_ref, source=atk_ref, reason="战斗")
    game.emit("on_after_assault", attacker=atk_ref)


@debug_command("move")
def cmd_move(game, ctx, *, player: int, index: int) -> None:
    """强制移动式神（测试用）：从准备区移入战斗区，或使战斗区召唤物离场。

    普通式神从战斗区主动退回准备区的规则待"移动事件"落地；
    当前仅支持进入战斗区与召唤物离场。
    """
    if not (0 <= player < len(game.state.players)):
        raise ValueError(f"玩家下标越界: {player}")
    p = game.state.players[player]
    if not (0 <= index < len(p.shikigami)):
        raise ValueError(f"式神下标越界: {index}")
    s = p.shikigami[index]
    if p.combat_index == index:
        if s.home_slot is None:
            game._retreat(p, index)
        else:
            raise ValueError("debug_move 暂不支持普通式神从战斗区主动退回")
    else:
        game._enter_combat(p, index)
    game._log(f"[调试] {p.name} 移动了 {game.db.shikigami[s.id].name}")


@debug_command("draw")
def cmd_draw(game, ctx, *, player: int, count: int = 1) -> None:
    """强制抽牌：不经过回合开始阶段，也不判负（牌库为空时只抽剩余牌）。"""
    if not (0 <= player < len(game.state.players)):
        raise ValueError(f"玩家下标越界: {player}")
    p = game.state.players[player]
    actual = min(count, len(p.deck))
    for _ in range(actual):
        game.move_card(p, p.deck[0], "hand")
    game._log(f"[调试] {p.name} 强制抽了 {actual} 张牌")
    game.emit("on_draw", player=player, count=actual)


@debug_command("set_turn")
def cmd_set_turn(game, ctx, *, active: int | None = None, turn: int | None = None) -> None:
    """直接设置当前回合方与/或半回合计数（用于测试回合边界）。"""
    if active is not None:
        if active not in (0, 1):
            raise ValueError("active 必须是 0 或 1")
        game.state.active = active
    if turn is not None:
        game.state.turn = turn
    game._log(f"[调试] 设置 active={game.state.active}, turn={game.state.turn}")


@debug_command("skip_upgrade")
def cmd_skip_upgrade(game, ctx) -> None:
    """调试：跳过当前升级阶段（仅用于测试）。"""
    from core.engine import IllegalAction

    if game.state.phase != "upgrade":
        raise IllegalAction("当前不在升级阶段")
    game.state.phase = "battle"
    game._log("[调试] 跳过升级阶段")
