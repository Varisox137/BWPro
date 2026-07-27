"""目标解析：TargetSpec → 具体 Ref 列表。

kind：
- none:    无指定目标（回退为卡牌的选择目标 ctx.chosen，通常为空）
- self:    效果来源式神（ctx.source）
- choose:  玩家在 pool 中选择的目标。选择操作只会发生在当前回合方——
           规则约定：非回合方不存在任何带选择的操作（见 CLAUDE.md）
- all:     pool 中全部合法对象
- context: 取触发事件 payload 中的 Ref（key 指定字段名），响应/被动常用；
           支持列表值（affected_refs）与块内暂存（ctx.memo 的 last_damage_victims）

pool：enemy_shikigami / friendly_shikigami / any_shikigami / enemy_player / self_player
     / projectile（投射：敌方战斗区式神，空则敌方牌手）/ enemy_combat（敌方战斗区式神）
     / enemy_character（敌方在场式神 + 敌方牌手）/ friendly_others（己方其他在场式神，排除来源）
"""
from __future__ import annotations

from core.model import Ref

POOLS = frozenset({
    "enemy_shikigami",
    "friendly_shikigami",
    "any_shikigami",
    "enemy_player",
    "self_player",
    "projectile",
    "enemy_combat",
    "enemy_character",
    "friendly_others",
})


def pool_refs(game, pool: str, controller: int) -> list[Ref]:
    """列出 pool 中当前全部合法目标（仅在场式神：存活、未离场、非濒死、等级 >= 1）。"""
    enemy = 1 - controller

    def alive_shiki(pi: int) -> list[Ref]:
        return [
            Ref(player=pi, shikigami=i)
            for i, s in enumerate(game.state.players[pi].shikigami)
            if s.in_play and not s.dying  # 濒死者不进随机与选择目标池
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
    if pool == "enemy_combat":
        ep = game.state.players[enemy]
        ci = ep.combat_index
        if ci is not None and ep.shikigami[ci].in_play:
            return [Ref(player=enemy, shikigami=ci)]
        return []
    if pool == "projectile":
        # 投射：优先敌方战斗区式神，战斗区为空时退回敌方牌手
        ep = game.state.players[enemy]
        ci = ep.combat_index
        if ci is not None and ep.shikigami[ci].in_play:
            return [Ref(player=enemy, shikigami=ci)]
        return [Ref(player=enemy)]
    if pool == "enemy_character":
        return alive_shiki(enemy) + [Ref(player=enemy)]
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
        if spec.pool == "friendly_others":
            # 己方其他在场式神：排除效果来源（古尘之壁）
            return [r for r in pool_refs(game, "friendly_shikigami", ctx.controller)
                    if r != ctx.source]
        return pool_refs(game, spec.pool, ctx.controller)
    if spec.kind == "choose":
        return list(ctx.chosen or [])
    if spec.kind == "context":
        val = (ctx.event or {}).get(spec.key)
        if val is None and getattr(ctx, "memo", None):
            val = ctx.memo.get(spec.key)  # 块内暂存（last_damage_victims）
        if isinstance(val, Ref):
            return [val]
        if isinstance(val, list):  # 列表 payload（affected_refs）/ 块内暂存
            return [r for r in val if isinstance(r, Ref)]
        return []
    raise ValueError(f"未知目标类型: {spec.kind}")


def match_condition(game, condition: dict | None, event: dict, controller: int,
                    holder: Ref | None = None) -> bool:
    """条件迷你语言（扩展点，后续按需加操作符）：
    - {字段: self|opponent}    ：标量玩家下标与 controller 比较
    - {字段_side: friendly|enemy|any} ：事件中的 Ref 相对 controller 的归属
    - {字段_kind: shikigami|player}   ：Ref 指向式神还是牌手
    - {字段_shikigami: self}   ：事件中的 Ref 与能力持有者（holder）同式神
    - {字段_shikigami: <式神id>} ：事件中的 Ref 所指式神的数据 id（游离触发器用）
    - {字段_not_shikigami: <式神id>} ：事件中的 Ref 所指式神的数据 id ≠ 给定值（"其他式神"）
    - {字段_has_fragile: true|false} ：事件中的 Ref 所指角色（式神或牌手）是否持有破甲
      （"若攻击有破甲的角色"——战斗条件授予以 {"defender": 被攻击者} 求值）
    - {active: self|opponent}  ：当前回合方是否为能力控制者（"己方回合"限定）
    - {turn_mark_not: <key>}   ：控制者本回合未被 turn_mark 标记 key（"每回合合计一次"）
    - {player_ext: <key>}      ：控制者 PlayerState.ext[key] 为真值（"本回合若使用过黄金羽"
      = feather_used_turn 记账键；千羽风之舞 step 级条件）
    - {shikigami_in_combat: <式神id>} ：控制者战斗区式神的数据 id（"若某式神在战斗区"）
    - 其余按键值相等比较
    """
    if not condition:
        return True
    for key, want in condition.items():
        if key == "active":
            if (want == "self") != (game.state.active == controller):
                return False
        elif key == "player_ext":
            if not game.state.players[controller].ext.get(want):
                return False
        elif key == "turn_mark_not":
            if want in game.state.players[controller].ext.get("turn_marks", {}):
                return False
        elif key == "shikigami_in_combat":
            cp = game.state.players[controller]
            ci = cp.combat_index
            if ci is None or cp.shikigami[ci].id != want:
                return False
        elif key.endswith("_side"):
            ref = event.get(key[:-5])
            if not isinstance(ref, Ref):
                return False
            side = "friendly" if ref.player == controller else "enemy"
            if want != "any" and side != want:
                return False
        elif key.endswith("_has_fragile"):
            # 事件中的 Ref 所指角色（式神或牌手）是否持有破甲（shield < 0）
            ref = event.get(key[:-12])
            if not isinstance(ref, Ref):
                return False
            hp = game.state.players[ref.player]
            holder = hp.shikigami[ref.shikigami] if ref.shikigami is not None else hp
            if (holder.shield < 0) != bool(want):
                return False
        elif key.endswith("_kind"):
            ref = event.get(key[:-5])
            if not isinstance(ref, Ref):
                return False
            kind = "shikigami" if ref.shikigami is not None else "player"
            if kind != want:
                return False
        elif key.endswith("_not_shikigami"):
            # 事件中的 Ref 所指式神的数据 id ≠ 给定值（"己方其他式神"，如援护）
            ref = event.get(key[:-14])
            if not isinstance(ref, Ref) or ref.shikigami is None:
                return False
            if game.state.players[ref.player].shikigami[ref.shikigami].id == want:
                return False
        elif key.endswith("_shikigami"):
            ref = event.get(key[:-10])
            if want == "self":
                if (not isinstance(ref, Ref) or holder is None
                        or holder.shikigami is None or ref.shikigami is None):
                    return False
                if ref.player != holder.player or ref.shikigami != holder.shikigami:
                    return False
            elif isinstance(want, int):
                if not isinstance(ref, Ref) or ref.shikigami is None:
                    return False
                if game.state.players[ref.player].shikigami[ref.shikigami].id != want:
                    return False
            else:
                return False
        elif want == "self":
            if event.get(key) != controller:
                return False
        elif want == "opponent":
            if event.get(key) == controller:
                return False
        elif event.get(key) != want:
            return False
    return True
