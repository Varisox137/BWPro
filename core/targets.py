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
     / enemy_bench（敌方准备区：在场且不在战斗区的敌方式神）
     / enemy_character（敌方在场式神 + 敌方牌手）/ friendly_others（己方其他在场式神，排除来源）
     / friendly_character（己方在场式神 + 己方牌手，祝福之水"己方所有角色"）
     / friendly_others_character（己方其他在场式神 + 己方牌手，排除来源；蹈海"己方其他角色"）
     / any_character（双方在场式神 + 双方牌手，治愈之水/佛光"一个角色"）
     / friendly_lowest_level（己方在场式神中等级最低者；并列全部入池由使用者选择，百闻一得）
     / side_of_last_heal（本块上一步 heal 目标所属方的所有角色——在场式神 + 牌手；佛光
       "为其操控者的所有角色"，仅 kind=all 可用，读 ctx.memo["last_heal_targets"]）
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
    "enemy_bench",
    "enemy_character",
    "friendly_others",
    "friendly_character",
    "friendly_others_character",
    "any_character",
    "friendly_lowest_level",
    "side_of_last_heal",
})


def _veiled_state(s) -> bool:
    return ("veil" in s.keywords or "veil" in s.one_shot_keywords
            or "veil" in s.perm_keywords)


def is_veiled(game, ref: Ref, controller: int) -> bool:
    """帷幕：ref 是否为对 controller 而言不可被出击/用牌指定的敌方式神（持 veil 关键字）。

    仅阻挡"选择目标"（choose/出击目标/有目标的战斗）；all 池全体效果与随机效果不取对象，
    不受帷幕影响。牌手暂不持帷幕。
    """
    if ref.shikigami is None or ref.player == controller:
        return False
    return _veiled_state(game.state.players[ref.player].shikigami[ref.shikigami])


def pool_refs(game, pool: str, controller: int, *, targeted: bool = False) -> list[Ref]:
    """列出 pool 中当前全部合法目标（仅在场式神：存活、未离场、非濒死、等级 >= 1）。

    targeted=True（choose 选择/出击目标等有目标的指定）时，持帷幕的敌方式神不可选。
    """
    enemy = 1 - controller

    def alive_shiki(pi: int) -> list[Ref]:
        return [
            Ref(player=pi, shikigami=i)
            for i, s in enumerate(game.state.players[pi].shikigami)
            if s.in_play and not s.dying  # 濒死者不进随机与选择目标池
            and not (targeted and pi == enemy and _veiled_state(s))
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
            if targeted and _veiled_state(ep.shikigami[ci]):
                return []
            return [Ref(player=enemy, shikigami=ci)]
        return []
    if pool == "enemy_bench":
        # 敌方准备区：在场且不在战斗区的敌方式神（山童类"攻击准备区式神"）
        ep = game.state.players[enemy]
        return [
            Ref(player=enemy, shikigami=i)
            for i, s in enumerate(ep.shikigami)
            if s.in_play and not s.dying and i != ep.combat_index
            and not (targeted and _veiled_state(s))
        ]
    if pool == "projectile":
        # 投射：优先敌方战斗区式神，战斗区为空时退回敌方牌手
        ep = game.state.players[enemy]
        ci = ep.combat_index
        if ci is not None and ep.shikigami[ci].in_play:
            return [Ref(player=enemy, shikigami=ci)]
        return [Ref(player=enemy)]
    if pool == "enemy_character":
        return alive_shiki(enemy) + [Ref(player=enemy)]
    if pool == "friendly_character":
        return alive_shiki(controller) + [Ref(player=controller)]
    if pool == "friendly_others_character":
        # 己方其他角色：排除来源由 resolve() 处理（此处与 friendly_character 相同）
        return alive_shiki(controller) + [Ref(player=controller)]
    if pool == "any_character":
        return (alive_shiki(controller) + alive_shiki(enemy)
                + [Ref(player=controller), Ref(player=enemy)])
    if pool == "friendly_lowest_level":
        # 己方在场式神中等级最低者（并列全部入池，choose 时由使用者选择；百闻一得）
        refs = alive_shiki(controller)
        if not refs:
            return []
        lowest = min(game.state.players[controller].shikigami[r.shikigami].level
                     for r in refs)
        return [r for r in refs
                if game.state.players[controller].shikigami[r.shikigami].level == lowest]
    raise ValueError(f"未知目标池: {pool}")


def resolve(game, spec, ctx) -> list[Ref]:
    """把 step 的 TargetSpec 解析为 Ref 列表。spec 为 None 时回退到卡牌的选择目标。

    帷幕再校验（卡牌效果，is_ability=False）：已确定的目标在结算时具有帷幕则取消
    （"取消目标、不执行目标相关的效果"）；能力/全体/随机指定不受帷幕影响。
    """
    if spec is None:
        return _chosen(game, ctx)
    if spec.kind == "none":
        return _chosen(game, ctx)
    if spec.kind == "self":
        return [ctx.source] if ctx.source else []
    if spec.kind == "all":
        if spec.pool == "friendly_others":
            # 己方其他在场式神：排除效果来源（古尘之壁）
            refs = [r for r in pool_refs(game, "friendly_shikigami", ctx.controller)
                    if r != ctx.source]
        elif spec.pool == "friendly_others_character":
            # 己方其他角色（式神 + 牌手）：排除效果来源（蹈海）
            refs = [r for r in pool_refs(game, "friendly_character", ctx.controller)
                    if r != ctx.source]
        elif spec.pool == "side_of_last_heal":
            # 上一步 heal 目标所属方的所有角色（佛光"为其操控者的所有角色"）
            memo = getattr(ctx, "memo", None) or {}
            healed = memo.get("last_heal_targets") or []
            if not healed:
                return []
            side = healed[0].player
            refs = [r for r in pool_refs(game, "any_character", ctx.controller)
                    if r.player == side]
        else:
            refs = pool_refs(game, spec.pool, ctx.controller)
        sid = (spec.model_extra or {}).get("shikigami")
        if sid is not None:
            # 按数据 id 过滤式神（豪焰固定项 buff 茨木、羁绊伤酒吞类"指定式神"）
            refs = [r for r in refs if r.shikigami is not None
                    and game.state.players[r.player].shikigami[r.shikigami].id == int(sid)]
        return refs
    if spec.kind == "choose":
        return _chosen(game, ctx)
    if spec.kind == "context":
        if spec.key == "victim_player":
            # 事件中 victim 式神所属的牌手（引燃"若消灭则对它的牌手造成2伤"——
            # 消灭己方式神则打己方牌手；delay_grant 触发块内可用）
            v = (ctx.event or {}).get("victim")
            return [Ref(player=v.player)] if isinstance(v, Ref) else []
        val = (ctx.event or {}).get(spec.key)
        if val is None and getattr(ctx, "memo", None):
            val = ctx.memo.get(spec.key)  # 块内暂存（last_damage_victims）
        if isinstance(val, Ref):
            return [val]
        if isinstance(val, list):  # 列表 payload（affected_refs）/ 块内暂存
            return [r for r in val if isinstance(r, Ref)]
        return []
    raise ValueError(f"未知目标类型: {spec.kind}")


def _chosen(game, ctx) -> list[Ref]:
    """卡牌的选择目标（帷幕再校验：结算时目标持帷幕则取消；能力结算不过滤）。"""
    refs = list(ctx.chosen or [])
    if getattr(ctx, "is_ability", False):
        return refs
    return [r for r in refs if not is_veiled(game, r, ctx.controller)]


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
    - {orb_ge: n}              ：控制者当前鬼火 ≥ n（"若你有 2 点鬼火"类）
    - {字段_not: 值}           ：事件字段 ≠ 给定值（{shikigami_not: null} = 专属牌/非中立，
      "己方式神使用法术牌"排除中立牌用）
    - {player_ext: <key>}      ：控制者 PlayerState.ext[key] 为真值（"本回合若使用过黄金羽"
      = feather_used_turn 记账键；千羽风之舞 step 级条件）
    - {shikigami_in_combat: <式神id>} ：控制者战斗区式神的数据 id（"若某式神在战斗区"）
    - {shikigami_active: <式神id>}  ：控制者的式神（按数据 id）在场——等级 ≥1、未气绝、
      未离场（[羁绊]触发条件："使用此牌时，对应式神等级不为 0 且未气绝"）
    - {字段_ge: n}             ：事件数值字段 ≥ n（overheal_ge 过量治疗 ≥1 触发转化；
      orb_ge 为控制者鬼火的专用键，语义不同）
    - {victim_lethal: true}    ：事件 victim 当前生命 ≤ 事件伤害值 amount（"将受到致命
      伤害"——舍生响应；on_damage_start 时机在护甲计算前，按面板伤害判定）
    - {victim_in_combat: true} ：事件 victim 是其控制者战斗区式神（"战斗区式神被攻击"
      ——沧海之盾响应）
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
        elif key == "orb_ge":
            if game.state.players[controller].orb < want:
                return False
        elif key == "shikigami_in_combat":
            cp = game.state.players[controller]
            ci = cp.combat_index
            if ci is None or cp.shikigami[ci].id != want:
                return False
        elif key == "shikigami_active":
            # 控制者的式神（按数据 id）在场：等级 ≥1、未气绝、未离场（羁绊触发条件）
            ap = game.state.players[controller]
            ai = next((i for i, s in enumerate(ap.shikigami) if s.id == want), None)
            if ai is None or not ap.shikigami[ai].in_play:
                return False
        elif key == "combat_empty":
            # 指定方战斗区为空（偷袭响应"（敌方）战斗区没有式神"）：self=控制者 / opponent=对方
            cp = game.state.players[controller if want == "self" else 1 - controller]
            if cp.combat_index is not None:
                return False
        elif key == "victim_lethal":
            # 事件 victim 将受致命伤害：面板伤害值 ≥ victim 当前生命（on_damage_start
            # 时机在护甲计算前；舍生"当你将受到致命伤害时"）
            v = event.get("victim")
            if not isinstance(v, Ref):
                return False
            vp = game.state.players[v.player]
            hp = vp.shikigami[v.shikigami].health if v.shikigami is not None else vp.health
            if int(event.get("amount", 0)) < hp:
                return False
        elif key == "victim_in_combat":
            # 事件 victim 是其控制者的战斗区式神（沧海之盾"当你战斗区式神被攻击时"）
            v = event.get("victim")
            if not isinstance(v, Ref) or v.shikigami is None:
                return False
            if game.state.players[v.player].combat_index != v.shikigami:
                return False
        elif key.endswith("_ge"):
            # 通用数值下限：事件字段 ≥ n（如 overheal_ge: 1 = 存在过量治疗）
            if int(event.get(key[:-3], 0)) < int(want):
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
        elif key.endswith("_not"):
            # 不等判定（如 {shikigami_not: null} = 该字段非 None——排除中立牌）
            if event.get(key[:-4]) == want:
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
