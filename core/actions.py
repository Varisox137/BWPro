"""原子动作（Action）注册表：卡牌效果的唯一执行原语。

每张卡牌的效果 = 若干 Action 的有序组合（见 db.schema.EffectBlock）。
新增动作 = 用 @action 注册一个函数，引擎主循环无需改动；
自定义卡牌 DSL（diy/）将来也只允许编译到这张注册表内的原语。

函数签名：fn(game, ctx, *, targets: list[Ref], **params)
- game:    core.engine.Game（可用 game.state / game.emit / game.deal_to_*）
- ctx:     core.engine.ExecContext（controller / source / card / event / chosen）
- targets: 本步已解析的目标列表（无目标则为空列表）
- params:  YAML 中该 step 的其余字段（如 amount、count）
"""
from __future__ import annotations

from typing import Callable

from core.model import Ref, ShikigamiState

ACTIONS: dict[str, Callable] = {}


def action(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        ACTIONS[name] = fn
        return fn

    return deco


@action("damage")
def damage(game, ctx, *, targets: list[Ref], amount: int) -> None:
    """对目标（式神或牌手）造成 amount 点伤害；护甲优先吸收。"""
    for ref in targets:
        if ref.shikigami is None:
            game.deal_to_player(ref.player, amount, ctx.source)
        else:
            game.deal_to_shikigami(ref, amount, ctx.source)


@action("heal")
def heal(game, ctx, *, targets: list[Ref], amount: int) -> None:
    """恢复生命，不超过上限；气绝/未在场式神不能被治疗，气绝的牌手也不能。"""
    for ref in targets:
        if ref.shikigami is None:
            p = game.state.players[ref.player]
            if not p.defeated:
                p.health = min(p.max_health, p.health + amount)
        else:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if s.in_play:
                s.health = min(s.max_health, s.health + amount)


@action("draw")
def draw(game, ctx, *, targets: list[Ref], count: int = 1) -> None:
    """效果归属玩家抽 count 张牌（targets 忽略）。牌库抽空判负。"""
    game.draw_cards(ctx.controller, count)


@action("buff_power")
def buff_power(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False) -> None:
    """力量增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。"""
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play:
                continue
            if perm:
                s.perm_power += amount
            else:
                s.temp_power += amount


@action("buff_health")
def buff_health(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False) -> None:
    """生命上限增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。"""
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play:
                continue
            if perm:
                s.perm_health += amount
                s.health += amount
            else:
                s.temp_health += amount
                # 临时增加上限时，当前生命同步增加等量数值（不超过新上限）
                if amount > 0:
                    s.health = min(s.max_health, s.health + amount)


@action("gain_shield")
def gain_shield(game, ctx, *, targets: list[Ref], amount: int) -> None:
    """获得护甲（式神与牌手均可）。0 级未在场式神不能获得护甲/增益。"""
    for ref in targets:
        if ref.shikigami is None:
            game.state.players[ref.player].shield += amount
        else:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if s.in_play:
                s.shield += amount


@action("summon")
def summon(game, ctx, *, targets: list[Ref], shikigami: int) -> None:
    """为效果归属玩家召唤一个召唤物（定义须 kind=summon）。

    召唤物的生成视作其移动进入战斗区（但不视为从准备区离开）；
    若战斗区已有驻留者，其退回准备区（召唤物则直接离场）。
    若该召唤物定义 keep_buffs=True，则同名再召时继承上次离场时的永久增减益。
    """
    d = game.db.shikigami[shikigami]
    p = game.state.players[ctx.controller]
    s = ShikigamiState(
        id=shikigami, kind="summon", faction=d.faction, level=1,
        home_slot=None,
        base_power=d.power, base_health=d.health, health=d.health)
    legacy = p.summon_legacy.get(shikigami)
    if legacy:
        s.perm_power = legacy.get("perm_power", 0)
        s.perm_health = legacy.get("perm_health", 0)
        s.health += s.perm_health
    p.shikigami.append(s)
    idx = len(p.shikigami) - 1
    game._log(f"{p.name} 召唤了 {d.name}")
    game._enter_combat(p, idx)  # 召唤即进入战斗区
    game.emit("on_summon", shikigami=Ref(player=ctx.controller, shikigami=idx))


@action("emit")
def emit_event(game, ctx, *, targets: list[Ref], event: str, payload: dict | None = None) -> None:
    """触发自定义事件（须在 db/events.yaml 中声明）。DIY 扩展入口。"""
    game.emit(event, controller=ctx.controller, **(payload or {}))
