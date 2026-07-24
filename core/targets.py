"""目标解析：TargetSpec → 具体 Ref 列表。

kind：
- none:    无指定目标（回退为卡牌的选择目标 ctx.chosen，通常为空）
- self:    效果来源式神（ctx.source）
- choose:  玩家在 pool 中选择的目标。选择操作只会发生在当前回合方——
           规则约定：非回合方不存在任何带选择的操作（见 CLAUDE.md）
- all:     pool 中全部合法对象
- context: 取触发事件 payload 中的 Ref（key 指定字段名），响应/被动常用

pool：enemy_shikigami / friendly_shikigami / any_shikigami / enemy_player / self_player
"""
from __future__ import annotations

from core.model import Ref

POOLS = frozenset({
    "enemy_shikigami",
    "friendly_shikigami",
    "any_shikigami",
    "enemy_player",
    "self_player",
})


def pool_refs(game, pool: str, controller: int) -> list[Ref]:
    """列出 pool 中当前全部合法目标（仅在场式神：存活、未离场、等级 >= 1）。"""
    enemy = 1 - controller

    def alive_shiki(pi: int) -> list[Ref]:
        return [
            Ref(player=pi, shikigami=i)
            for i, s in enumerate(game.state.players[pi].shikigami)
            if s.in_play
        ]

    if pool == "enemy_shikigami":
        return alive_shiki(enemy)
    if pool == "friendly_shikigami":
        return alive_shiki(controller)
    if pool == "any_shikigami":
        return alive_shiki(controller) + alive_shiki(enemy)
    if pool == "enemy_player":
        return [Ref(player=enemy)]
    if pool == "self_player":
        return [Ref(player=controller)]
    raise ValueError(f"未知目标池: {pool}")


def resolve(game, spec, ctx) -> list[Ref]:
    """把 step 的 TargetSpec 解析为 Ref 列表。spec 为 None 时回退到卡牌的选择目标。"""
    if spec is None:
        return list(ctx.chosen or [])
    if spec.kind == "none":
        return list(ctx.chosen or [])
    if spec.kind == "self":
        return [ctx.source] if ctx.source else []
    if spec.kind == "all":
        return pool_refs(game, spec.pool, ctx.controller)
    if spec.kind == "choose":
        return list(ctx.chosen or [])
    if spec.kind == "context":
        ref = (ctx.event or {}).get(spec.key)
        return [ref] if isinstance(ref, Ref) else []
    raise ValueError(f"未知目标类型: {spec.kind}")
