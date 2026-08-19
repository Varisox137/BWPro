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
     / friendly_combat（己方战斗区式神；生死无常"消灭己方战斗区的式神"）
     / side_of_last_heal（本块上一步 heal 目标所属方的所有角色——在场式神 + 牌手；佛光
       "为其操控者的所有角色"，仅 kind=all 可用，读 ctx.memo["last_heal_targets"]）
     / friendly_injured（己方在场且已受伤（生命 < 上限）的式神；丰实/盛开"受伤的己方式神"）
     / friendly_defeated（己方已气绝式神——未离场、等级 ≥1；桃华灼灼"复活所有己方式神"）
     / enemy_fragile_or_combat（敌方有破甲的在场式神或敌方战斗区式神——或关系，
       含持破甲的敌方牌手；无往"攻击有破甲的敌方式神或敌方战斗区式神"）

TargetSpec 额外键：
- {"random": n}：kind=all 时在解析结果中随机取 n 个（盛开"随机一个受伤己方式神"，
  配合 repeat 每轮重新随机）；不足 n 个时取全部
- {"memo": key}（须与 random 同用）：块内随机目标复用——首次解析把取样结果存入
  ctx.memo[key]，同块后续同 key 的解析直接复用该 refs（不再取样、不再重新过滤；
  惊鸿之舞"同一随机目标获得2力量与[贯通]"/"随机两名己方式神各永久+1/+1"）
- {"include_defeated": true}：对 friendly_shikigami / enemy_shikigami 池，把未离场的
  气绝式神也纳入（口径同 friendly_defeated 池：defeated 且 not despawned 且 level>=1；
  惊鸿之舞"随机两名己方式神（无论是否气绝）"）
- {"power_le": n}：按 eff_power ≤ n 过滤式神目标（勾诀"力量<=2的敌方式神"；choose
  合法性校验经 spec_pool_refs、kind=all 解析经 resolve 应用）
- {"has_fragile": true|false}：按是否持有破甲过滤角色目标（焚身之火"所有有破甲的
  敌方角色"，kind=all 解析时应用）
"""
from __future__ import annotations

from core.model import Ref

POOLS = frozenset({
    "enemy_shikigami",
    "friendly_shikigami",
    "any_shikigami",
    "enemy_player",
    "any_player",
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
    "friendly_combat",
    "side_of_last_heal",
    "friendly_injured",
    "friendly_defeated",
    "active_character",
    "enemy_fragile_or_combat",
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
    if pool == "any_player":
        # 双方牌手（孟婆汤"选择一个牌手"）
        return [Ref(player=controller), Ref(player=enemy)]
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
    if pool == "friendly_combat":
        # 己方战斗区式神（生死无常"消灭己方战斗区的式神"）
        cp = game.state.players[controller]
        ci = cp.combat_index
        if ci is not None and cp.shikigami[ci].in_play:
            return [Ref(player=controller, shikigami=ci)]
        return []
    if pool == "enemy_fragile_or_combat":
        # 无往：敌方有破甲的在场式神或敌方战斗区式神（或关系；含持破甲的敌方牌手）
        ep = game.state.players[enemy]
        refs = [r for r in alive_shiki(enemy)
                if ep.shikigami[r.shikigami].shield < 0 or r.shikigami == ep.combat_index]
        if ep.shield < 0:
            refs.append(Ref(player=enemy))
        return refs
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
    if pool == "friendly_injured":
        # 己方在场且已受伤的式神（生命 < 上限；丰实/盛开"受伤的己方式神"）
        cp = game.state.players[controller]
        return [r for r in alive_shiki(controller)
                if cp.shikigami[r.shikigami].health < cp.shikigami[r.shikigami].max_health]
    if pool == "friendly_defeated":
        # 己方已气绝式神：未离场、等级 ≥1（桃华灼灼"复活所有己方式神"）
        return [
            Ref(player=controller, shikigami=i)
            for i, s in enumerate(game.state.players[controller].shikigami)
            if s.defeated and not s.despawned and s.level >= 1
        ]
    if pool == "active_character":
        # 回合方（当前行动玩家）的所有角色（凋零之森"当每个牌手的回合开始时，
        # 对他所有角色造成…"——目标侧随事件玩家而非效果控制者）
        act = game.state.active
        return alive_shiki(act) + [Ref(player=act)]
    raise ValueError(f"未知目标池: {pool}")


def _spec_filtered(game, refs: list[Ref], extra: dict,
                   controller: int | None = None) -> list[Ref]:
    """TargetSpec 额外过滤键（model_extra）统一应用：power_le（力量上限）/ has_fragile（有无破甲）
    / stunned（是否眩晕，仅式神目标，式神过滤完即空）/ dealt_damage_turn（本回合
    造成过伤害的式神——萤草"伤害来源式神"过滤，伤害结算栈 + 回合开始清）；
    keyword（具有指定关键字的式神——三列表多重集 keywords/one_shot/perm 任一含即算，
    日和坊"有[充能]的式神"过滤，牌手目标不匹配被滤除）；
    highest_power（力量最高过滤——读 eff_power，并列全部保留交由后续 random 键均等取，
    惊鸿之舞"力量最高的式神"）；shield_nonzero（持有护甲或破甲的角色——骚声"移除一个
    角色上的护甲或破甲"，shield != 0）；strippable（醒转目标口径，需 controller：
    己方角色须有护甲 shield > 0、敌方角色须有破甲 shield < 0）；
    exclude_shikigami（排除指定数据 id 的式神——白骨之盾"己方其他式神"排除久次良本人）。
    不匹配 true 语义的目标被滤除。"""
    pw = extra.get("power_le")
    if pw is not None:
        refs = [r for r in refs if r.shikigami is not None
                and game.state.players[r.player].shikigami[r.shikigami].eff_power <= int(pw)]
    hf = extra.get("has_fragile")
    if hf is not None:
        def _fragile(r: Ref) -> bool:
            pl = game.state.players[r.player]
            holder = pl.shikigami[r.shikigami] if r.shikigami is not None else pl
            return holder.shield < 0
        refs = [r for r in refs if _fragile(r) == bool(hf)]
    st = extra.get("stunned")
    if st is not None:
        refs = [r for r in refs if _ref_stunned(game, r) == bool(st)]
    ddt = extra.get("dealt_damage_turn")
    if ddt is not None:
        def _dealt(r: Ref) -> bool:
            if r.shikigami is None:
                return False
            return bool(game.state.players[r.player].shikigami[r.shikigami]
                        .ext.get("dealt_damage_turn"))
        refs = [r for r in refs if _dealt(r) == bool(ddt)]
    kw = extra.get("keyword")
    if kw is not None:
        def _has_kw(r: Ref) -> bool:
            if r.shikigami is None:
                return False
            s = game.state.players[r.player].shikigami[r.shikigami]
            return any(kw in lst for lst in (s.keywords, s.one_shot_keywords, s.perm_keywords))
        refs = [r for r in refs if _has_kw(r)]
    if extra.get("highest_power"):
        # 力量最高过滤（惊鸿之舞"力量最高的式神"；读 eff_power，并列全部保留——
        # 后续 random 键再均等取；牌手目标无力量被滤除）
        cands = [r for r in refs if r.shikigami is not None]
        if cands:
            hi = max(game.state.players[r.player].shikigami[r.shikigami].eff_power
                     for r in cands)
            refs = [r for r in cands
                    if game.state.players[r.player].shikigami[r.shikigami].eff_power == hi]
        else:
            refs = []
    if extra.get("shield_nonzero"):
        # 持有护甲或破甲的角色（骚声"移除一个角色上的护甲或破甲"；shield != 0，
        # 式神/牌手目标同口径）
        def _nonzero(r: Ref) -> bool:
            pl = game.state.players[r.player]
            holder = pl.shikigami[r.shikigami] if r.shikigami is not None else pl
            return holder.shield != 0
        refs = [r for r in refs if _nonzero(r)]
    if extra.get("strippable") and controller is not None:
        # 醒转目标口径："移除一个己方角色上的护甲或敌方角色上的破甲"——
        # 己方角色须有护甲（shield > 0），敌方角色须有破甲（shield < 0）
        def _strippable(r: Ref) -> bool:
            pl = game.state.players[r.player]
            holder = pl.shikigami[r.shikigami] if r.shikigami is not None else pl
            return holder.shield > 0 if r.player == controller else holder.shield < 0
        refs = [r for r in refs if _strippable(r)]
    ex_sid = extra.get("exclude_shikigami")
    if ex_sid is not None:
        # 排除指定数据 id 的式神（白骨之盾"一个己方其他式神"——choose 池排除久次良
        # 本人；spec_pool_refs 统一校验/展示）
        refs = [r for r in refs if r.shikigami is not None
                and game.state.players[r.player].shikigami[r.shikigami].id != int(ex_sid)]
    if extra.get("no_form"):
        # 仅没有形态的式神（今日委托·伍"消灭一个没有形态的式神"；牌手目标被滤除）
        refs = [r for r in refs if r.shikigami is not None
                and game.state.players[r.player].shikigami[r.shikigami].form is None]
    if extra.get("has_form"):
        # 仅结附着形态的式神（神木诅咒"使一个形态变成…"取对象；牌手目标被滤除）
        refs = [r for r in refs if r.shikigami is not None
                and game.state.players[r.player].shikigami[r.shikigami].form is not None]
    if extra.get("prefer_wounded"):
        # 优先受伤或气绝式神（晚樱之意"优先受伤或气绝式神"）：候选中存在受伤
        # （生命 < 上限）或气绝的式神时收窄到该子集（再交由 random 键均等取）；
        # 气绝者入池需配合 include_defeated；牌手目标不参与优先（被子集挤出）
        pref = [r for r in refs if r.shikigami is not None and (
            game.state.players[r.player].shikigami[r.shikigami].defeated
            or game.state.players[r.player].shikigami[r.shikigami].health
            < game.state.players[r.player].shikigami[r.shikigami].max_health)]
        if pref:
            refs = pref
    return refs


def _ref_stunned(game, ref: Ref) -> bool:
    """Ref 所指角色（式神或牌手）当前是否眩晕。"""
    pl = game.state.players[ref.player]
    if ref.shikigami is None:
        return pl.is_stunned
    return pl.shikigami[ref.shikigami].is_stunned


def _ref_fragile(game, ref: Ref) -> bool:
    """Ref 所指角色（式神或牌手）当前是否持有破甲（shield < 0）。"""
    pl = game.state.players[ref.player]
    holder = pl.shikigami[ref.shikigami] if ref.shikigami is not None else pl
    return holder.shield < 0


def spec_pool_refs(game, spec, controller: int, *, targeted: bool = False) -> list[Ref]:
    """choose 目标合法性校验用：pool_refs + TargetSpec 额外过滤键（勾诀 power_le；
    legal_targets 与出牌/协战校验共用，保持"能选什么"与"展示什么"一致）。

    include_defeated：对 friendly_shikigami / enemy_shikigami 池把未离场的气绝式神
    一并纳入可选（樱花妖"可以为己方气绝式神恢复生命"类 choose 口径；与 resolve()
    kind=all 分支同口径）。"""
    refs = pool_refs(game, spec.pool, controller, targeted=targeted)
    extra = spec.model_extra or {}
    if extra.get("include_defeated") and spec.pool in (
            "friendly_shikigami", "enemy_shikigami"):
        side = controller if spec.pool == "friendly_shikigami" else 1 - controller
        refs += [Ref(player=side, shikigami=i)
                 for i, s in enumerate(game.state.players[side].shikigami)
                 if s.defeated and not s.despawned and s.level >= 1]
    return _spec_filtered(game, refs, extra, controller)


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
        extra = spec.model_extra or {}
        memo_key = extra.get("memo")
        rnd = extra.get("random")
        if memo_key is not None and rnd is not None \
                and getattr(ctx, "memo", None) and memo_key in ctx.memo:
            # 块内随机目标复用：直接复用首次取样结果（不再取样、不再重新过滤）
            return list(ctx.memo[memo_key])
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
        if extra.get("include_defeated") and spec.pool in (
                "friendly_shikigami", "enemy_shikigami"):
            # 含气绝过滤键：把未离场的气绝式神也纳入池（口径同 friendly_defeated 池）
            side = ctx.controller if spec.pool == "friendly_shikigami" \
                else 1 - ctx.controller
            refs += [Ref(player=side, shikigami=i)
                     for i, s in enumerate(game.state.players[side].shikigami)
                     if s.defeated and not s.despawned and s.level >= 1]
        sid = extra.get("shikigami")
        if sid is not None:
            # 按数据 id 过滤式神（豪焰固定项 buff 茨木、羁绊伤酒吞类"指定式神"）
            refs = [r for r in refs if r.shikigami is not None
                    and game.state.players[r.player].shikigami[r.shikigami].id == int(sid)]
        refs = _spec_filtered(game, refs, extra, ctx.controller)
        if extra.get("exclude_victim"):
            # 排除触发事件的 victim（胧月雪华斩"对所有其他[眩晕]的敌方角色"——
            # 与 random_damage 的 exclude_victim 参数同语义）
            vic = (ctx.event or {}).get("victim")
            refs = [r for r in refs if r != vic]
        if rnd is not None and len(refs) > int(rnd):
            # 随机取 n 个（盛开"随机一个受伤己方式神"；repeat 每轮重新解析重新随机）
            refs = game.rng.sample(refs, int(rnd))
        if memo_key is not None and rnd is not None:
            # 块内随机目标复用：首次取样结果存 ctx.memo[key]（惊鸿之舞"同一随机目标"）
            if ctx.memo is None:
                ctx.memo = {}
            ctx.memo[memo_key] = list(refs)
        return refs
    if spec.kind == "choose":
        return _chosen(game, ctx)
    if spec.kind == "context":
        if spec.key == "victim_player":
            # 事件中 victim 式神所属的牌手（引燃"若消灭则对它的牌手造成2伤"——
            # 消灭己方式神则打己方牌手；delay_grant 触发块内可用）
            v = (ctx.event or {}).get("victim")
            return [Ref(player=v.player)] if isinstance(v, Ref) else []
        if spec.key == "damaged_player":
            # 事件中受到伤害的牌手（on_player_damaged payload 的 player 下标 → Ref；
            # 夺命"消灭受到判官战斗伤害的角色"的牌手分支）
            pl = (ctx.event or {}).get("player")
            return [Ref(player=pl)] if isinstance(pl, int) and pl in (0, 1) else []
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
                    holder: Ref | None = None, chosen: list[Ref] | None = None) -> bool:
    """条件迷你语言（扩展点，后续按需加操作符）：
    - {字段: self|opponent}    ：标量玩家下标与 controller 比较
    - {字段_side: friendly|enemy|any} ：事件中的 Ref 相对 controller 的归属
    - {字段_kind: shikigami|player}   ：Ref 指向式神还是牌手
    - {字段_shikigami: self}   ：事件中的 Ref 与能力持有者（holder）同式神
    - {字段_shikigami: <式神id>} ：事件中的 Ref 所指式神的数据 id（游离触发器用）；
      值为列表时按" ∈ 列表"判定（坐下/出击光环的番茄 10013199/10013198 双 id 匹配）
    - {字段_not_shikigami: <式神id>} ：事件中的 Ref 所指式神的数据 id ≠ 给定值（"其他式神"）
    - {字段_has_fragile: true|false} ：事件中的 Ref 所指角色（式神或牌手）是否持有破甲
      （"若攻击有破甲的角色"——战斗条件授予以 {"defender": 被攻击者} 求值）
    - {字段_stunned: true|false} ：事件中的 Ref 所指角色（式神或牌手）是否眩晕
    - {chosen_stunned: true|false} ：卡牌选择目标（chosen）中是否有眩晕角色——
      Step 级条件专用（崩雪"已眩晕则消灭、否则眩晕"两段 steps）；事件触发块无 chosen
    - {chosen_has_fragile: true|false} ：卡牌选择目标（chosen）中是否有破甲角色——
      Step 级条件专用（蛇行击 2019"若其有破甲则……"）；事件触发块无 chosen
    - {chosen_side: friendly|enemy|any} ：事件 payload 的选择目标（on_card_played 的
      chosen）恰好一个且为式神、归属匹配——记仇"对单个己方式神使用的法术"类
      事件条件（响应/延迟监听用；与 Step 级 chosen_* 键不同，本键读事件）
    - {combat_opponent_stunned: true|false} ：能力持有者（holder）参与事件中的战斗
      （为 attacker 或 victim）且交战对方处于眩晕（双向判定；对方可为牌手）——
      雪童子"与眩晕的敌方角色交战时"类，挂 on_before_assault
    - {active: self|opponent}  ：当前回合方是否为能力控制者（"己方回合"限定）
    - {turn_mark_not: <key>}   ：控制者本回合未被 turn_mark 标记 key（"每回合合计一次"）
    - {orb_ge: n}              ：控制者当前鬼火 ≥ n（"若你有 2 点鬼火"类）
    - {assaults_left_ge|le: n} ：控制者剩余出击次数 ≥/≤ n（真意之歌 20200423
      "若你出击次数大于0……否则……"两段 steps 门控）
    - {字段_not: 值}           ：事件字段 ≠ 给定值（{shikigami_not: null} = 专属牌/非中立，
      "己方式神使用法术牌"排除中立牌用）
    - {player_ext: <key>}      ：控制者 PlayerState.ext[key] 为真值（"本回合若使用过黄金羽"
      = feather_used_turn 记账键；千羽风之舞 step 级条件）
    - {combat_empty: friendly|enemy}   一方战斗区为空（偷袭"敌方回合结束时战斗区
      没有式神"类响应条件）
    - {combat_occupied: friendly|enemy} ：一方战斗区有式神（combat_empty 的反向；
      惊鸿之舞"己方战斗区有式神时才可能触发"类前置）
    - {friendly_defeated_exists: true|false} ：控制者有气绝式神（同 friendly_defeated
      池口径：未离场、等级 ≥1；惊鸿之舞复活项前置）
    - {player_health_le: n}      ：控制者牌手当前生命 ≤ n（惊鸿之舞牌手护甲项前置）
    - {player_health_ge: n}      ：控制者牌手当前生命 ≥ n（血香 20200928 增强
      "若你生命值为30……免疫战斗伤害"——raw"为30"按 ≥30 口径，与 conditional_keywords
      同族算子一致；battle_immunity step 的 Step.condition 通道使用）
    - {player_missing_health_ge: n} ：控制者牌手已损生命 ≥ n（惊鸿之舞牌手治疗项前置）
    - {shikigami_in_combat: <式神id>} ：控制者战斗区式神的数据 id（"若某式神在战斗区"）
    - {shikigami_active: <式神id>}  ：控制者的式神（按数据 id）在场——等级 ≥1、未气绝、
      未离场（[羁绊]触发条件："使用此牌时，对应式神等级不为 0 且未气绝"）
    - {shikigami_has_form: <式神id>} ：控制者的式神（按数据 id）结附着形态
      （萤火点点"若萤草上有形态"）
    - {card_transformed: <卡牌id>}  ：控制者持久 store 中该同名卡已"变为"
      （夺命增强变后消灭路径的触发门控，读 card_mods transformed 快照位）
    - {dice_six_ge: n}         ：控制者骰子投出 6 次数（ext dice_six_count）≥ n
    - {dice_distinct_ge: n}    ：控制者骰子历史（ext dice_history）去重数 ≥ n
    - {luck_success_total_ge: n} ：双方判定成功次数（ext luck_success_game）合计 ≥ n
    - {kill_count_ge: n}       ：控制者击杀账本（PlayerState.kill_total）≥ n
      （夺命"你消灭过13个式神"；engine.check_defeated 单点记账）
    - {quest_count_ge: {"kind": k, "count": n}} ：控制者委托条件账本
      （PlayerState.quest_counts）k 类计数 ≥ n（三目委托 [条件] 使用前提/步骤门控；
      engine._quest_tick 多点记账）
    - {round_ge: n}            ：对局回合数 ≥ n（双方各一回合为一轮，由 state.turn
      半回合计数换算；今日委托·柒"5回合可用"）
    - {dice_below_x: true}     ：运势判定时事件当前骰点 < 所需点数 X（"将失败"重投门控）
    - {字段_ge: n}             ：事件数值字段 ≥ n（overheal_ge 过量治疗 ≥1 触发转化；
      orb_ge 为控制者鬼火的专用键，语义不同）；事件无该字段时回退读控制者
      PlayerState.ext[key]（on_play 步 ctx.event 为空——狂风刃卷 yaohu_damage_count_ge
      类计数比较）
    - {victim_lethal: true}    ：事件 victim 当前生命 ≤ 事件伤害值 amount（"将受到致命
      伤害"——舍生响应；on_damage_start 时机在护甲计算前，按面板伤害判定）
    - {victim_in_combat: true|false} ：事件 victim 是否其控制者战斗区式神（"战斗区式神
      被攻击"——沧海之盾响应；false = 准备区式神，桃红簇簇"准备区式神受到致命伤害"）
    - {holder_defeated: true|false} ：能力持有者当前是否气绝（觉醒·犬神"气绝时也能触发"
      类能力限定，配合 trigger_when_defeated 使用）
    - {holder_has_form: true|false} ：能力持有者当前是否结附着形态（萤草 20200327
      能力两项动态要求"萤草结附有形态"才生效）
    - {energy_ge: n}         ：能力持有者当前能量 ≥ n（阳炎响应"额外消耗3能量"门控）
    - {card_in_hand: true}   ：卡牌触发器（CardDef.triggers）专用——控制者手牌中须
      有该卡实例才触发（血怒"此牌伤害+1"类手牌限定触发；由 _collect_card_triggers
      消费，不进本函数的按键循环）
    - {hand_has: <卡牌id>}   ：控制者手牌中有该数据 id 的牌（转化步门控）
    - {hand_lacks: <卡牌id>} ：控制者手牌中没有该数据 id 的牌（天井下"若你手牌中
      没有'妖怪屋·灵力'"类生成门控）
    - {enemy_deck_le: n}     ：敌方牌库张数 ≤ n（月夜幻响包条件[增强]；
      conditional_mods 装配求值与步骤门控共用）
    - {friendly_armor_ge: n} ：控制者有在场式神护甲 ≥ n（焕然之音"若你有式神的
      护甲>=5"）
    - {friendly_field_intensity_ge: n|{ge, shikigami}} ：控制者幻境队列存在耐久 ≥ n
      的幻境（竹取物语"若辉夜姬的幻境耐久>=20"；shikigami 限定所属式神，"self"=
      能力持有者——定案(14)；多幻境场景按"存在性"口径）
    - {hand_card_type: <主类型>} ：控制者手牌中有该主类型的牌（余辉使用前提，
      play_condition 用——定案(9)）
    - {field_summon_distinct_ge: n|{count, shikigami}} ：控制者本局召唤过的不同名
      幻境牌数 ≥ n（觉醒·辉夜姬[增强]；shikigami 限定所属式神，"self"=能力持有者）
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
        elif key == "assaults_left_ge":
            # 控制者剩余出击次数 ≥ n（真意之歌 20200423"若你出击次数大于0"两段 steps 门控）
            if game.state.players[controller].assaults_left < int(want):
                return False
        elif key == "assaults_left_le":
            # 控制者剩余出击次数 ≤ n（上键的"否则"分支）
            if game.state.players[controller].assaults_left > int(want):
                return False
        elif key == "combat_empty":
            # 一方战斗区为空（偷袭"敌方回合结束时战斗区没有式神"）：friendly=控制者方、
            # enemy=对方（响应场景 = 结束回合的敌方）
            side = controller if want == "friendly" else 1 - controller
            if game.state.players[side].combat_index is not None:
                return False
        elif key == "combat_occupied":
            # 一方战斗区有式神（combat_empty 的反向；惊鸿之舞战斗区增益项前置）
            side = controller if want == "friendly" else 1 - controller
            if game.state.players[side].combat_index is None:
                return False
        elif key == "friendly_defeated_exists":
            # 控制者有气绝式神（未离场、等级 ≥1，同 friendly_defeated 池口径；
            # 惊鸿之舞复活项前置）
            ap = game.state.players[controller]
            has = any(s.defeated and not s.despawned and s.level >= 1
                      for s in ap.shikigami)
            if has != bool(want):
                return False
        elif key == "player_health_le":
            # 控制者牌手当前生命 ≤ n（惊鸿之舞牌手护甲项前置）
            if game.state.players[controller].health > int(want):
                return False
        elif key == "player_health_ge":
            # 控制者牌手当前生命 ≥ n（血香 20200928 增强条件免疫；与 le 对称）
            if game.state.players[controller].health < int(want):
                return False
        elif key == "player_missing_health_ge":
            # 控制者牌手已损生命 ≥ n（惊鸿之舞牌手治疗项前置）
            ap = game.state.players[controller]
            if ap.max_health - ap.health < int(want):
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
        elif key == "shikigami_has_form":
            # 控制者的式神（按数据 id）结附着形态（萤火点点"若萤草上有形态"）
            ap = game.state.players[controller]
            ai = next((i for i, s in enumerate(ap.shikigami) if s.id == want), None)
            if ai is None or ap.shikigami[ai].form is None:
                return False
        elif key == "card_transformed":
            # 控制者持久 store 中该同名卡已"变为"（夺命 temp_grants 门控）
            if not game.state.players[controller].card_mods.get(int(want), {}).get("transformed"):
                return False
        elif key == "dice_six_ge":
            # 控制者本局投出 6 的次数 ≥ n（送祝福/萌即正义增强；ext dice_six_count）
            if int(game.state.players[controller].ext.get("dice_six_count", 0)) < int(want):
                return False
        elif key == "dice_distinct_ge":
            # 控制者骰子历史去重数 ≥ n（九莲宝灯动态身材；ext dice_history）
            if len(set(game.state.players[controller].ext.get("dice_history", []))) < int(want):
                return False
        elif key == "luck_success_total_ge":
            # 双方运势判定成功合计 ≥ n（福满乾坤 [条件] 使用前提）
            total = sum(int(q.ext.get("luck_success_game", 0)) for q in game.state.players)
            if total < int(want):
                return False
        elif key == "kill_count_ge":
            # 控制者击杀账本总消灭数 ≥ n（夺命"你消灭过13个式神"门控；
            # 显式分支——否则落入通用 _ge 读事件/ext）
            if game.state.players[controller].kill_total < int(want):
                return False
        elif key == "quest_count_ge":
            # 委托条件账本（三目委托机制；play_condition/步骤门控共用）：
            # 控制者 PlayerState.quest_counts[kind] ≥ count。值 = {"kind": 行为种类,
            # "count": n}；行为种类见 model.PlayerState.quest_counts 注释
            cnt = game.state.players[controller].quest_counts.get(want["kind"], 0)
            if cnt < int(want["count"]):
                return False
        elif key == "round_ge":
            # 对局回合数 ≥ n（今日委托·柒"5回合可用"）：双方各一回合为一轮，
            # 由半回合计数换算（state.turn 1-2 = 第 1 轮，依此类推）
            if (game.state.turn + 1) // 2 < int(want):
                return False
        elif key == "dice_below_x":
            # 运势判定时"将失败"（觉醒·座敷童子重投门控）：事件当前骰点 < 所需点数 X
            if (int(event.get("dice", 0)) < int(event.get("x", 0))) != bool(want):
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
            # 事件 victim 是否其控制者的战斗区式神（沧海之盾"战斗区式神被攻击"；
            # false = 准备区式神，桃红簇簇"准备区式神受到致命伤害"）
            v = event.get("victim")
            if not isinstance(v, Ref) or v.shikigami is None:
                return False
            in_combat = game.state.players[v.player].combat_index == v.shikigami
            if in_combat != bool(want):
                return False
        elif key == "holder_defeated":
            # 能力持有者当前是否气绝（觉醒·犬神类"气绝时也能触发"限定）
            if holder is None or holder.shikigami is None:
                return False
            if game.state.players[holder.player].shikigami[holder.shikigami].defeated != bool(want):
                return False
        elif key == "holder_has_form":
            # 能力持有者当前是否结附着形态（萤草 20200327 能力动态要求）
            if holder is None or holder.shikigami is None:
                return False
            has_form = game.state.players[holder.player].shikigami[holder.shikigami].form is not None
            if has_form != bool(want):
                return False
        elif key == "energy_ge":
            # 能力持有者当前能量 ≥ n（"额外消耗3能量"类响应/触发门控）
            if holder is None or holder.shikigami is None:
                return False
            if game.state.players[holder.player].shikigami[holder.shikigami].energy < int(want):
                return False
        elif key == "hand_has":
            # 控制者手牌中有该数据 id 的牌（觉醒·天井下转化步门控）
            if not any(c.id == int(want) for c in game.state.players[controller].hand):
                return False
        elif key == "hand_lacks":
            # 控制者手牌中没有该数据 id 的牌（天井下"若你手牌中没有'灵力'"）
            if any(c.id == int(want) for c in game.state.players[controller].hand):
                return False
        elif key == "enemy_deck_le":
            # 敌方牌库张数 ≤ n（月夜幻响包条件[增强]：conditional_mods 求值/步骤门控）
            if len(game.state.players[1 - controller].deck) > int(want):
                return False
        elif key == "friendly_armor_ge":
            # 控制者有在场式神护甲 ≥ n（焕然之音"若你有式神的护甲>=5"）
            if not any(s.in_play and s.shield >= int(want)
                       for s in game.state.players[controller].shikigami):
                return False
        elif key == "friendly_field_intensity_ge":
            # 控制者幻境队列中存在耐久 ≥ n 的幻境（存在性口径）。值 = n（任一幻境）
            # 或 {ge: n, shikigami: <式神id>|"self"}（限定所属式神——竹取物语
            # "若辉夜姬的幻境耐久>=20"，定案(14)；self=能力持有者）
            if isinstance(want, dict):
                n = int(want.get("ge", 1))
                sid = want.get("shikigami")
                if sid == "self":
                    if holder is None or holder.shikigami is None:
                        return False
                    sid = game.state.players[holder.player].shikigami[holder.shikigami].id
            else:
                n, sid = int(want), None
            if not any(x.intensity >= n and (sid is None or x.shikigami == int(sid))
                       for x in game.state.players[controller].fields):
                return False
        elif key == "field_summon_distinct_ge":
            # 控制者本局召唤过的不同名幻境牌数 ≥ n（觉醒·辉夜姬[增强]"已召唤五个
            # 不同的辉夜姬幻境"；ext field_summon_ids 记账）。值 = n（不限式神）或
            # {count: n, shikigami: <式神id>|"self"}（限定所属式神；self=能力持有者）
            if isinstance(want, dict):
                n = int(want.get("count", 1))
                sid = want.get("shikigami")
                if sid == "self":
                    if holder is None or holder.shikigami is None:
                        return False
                    sid = game.state.players[holder.player].shikigami[holder.shikigami].id
            else:
                n, sid = int(want), None
            ids = game.state.players[controller].ext.get("field_summon_ids", [])
            if sid is not None:
                ids = [i for i in ids if game.db.cards[i].shikigami == int(sid)]
            if len(set(ids)) < n:
                return False
        elif key == "friendly_field":
            # 控制者幻境队列有幻境（泷夜叉姬/久次良"若你有幻境"系列；步级/能力条件通用）
            if bool(game.state.players[controller].fields) != bool(want):
                return False
        elif key == "hand_card_type":
            # 控制者手牌中有指定主类型的牌（余辉"弃一张幻境牌"的使用前提——
            # play_condition {hand_card_type: field}，定案(9)；无手牌谓词事件载荷，
            # 纯控制者状态检查）
            if not any(game.db.cards[c.id].card_type == want
                       for c in game.state.players[controller].hand):
                return False
        elif key == "chosen_stunned":
            # 卡牌选择目标中有眩晕角色（Step 级条件专用；崩雪"已眩晕则消灭、否则眩晕"）
            matched = any(_ref_stunned(game, r) for r in (chosen or []))
            if matched != bool(want):
                return False
        elif key == "chosen_has_fragile":
            # 卡牌选择目标中有破甲角色（Step 级条件专用；蛇行击 2019"若其有破甲"——
            # 破甲受伤即消耗，读破甲的条件步须排在伤害步之前）
            matched = any(_ref_fragile(game, r) for r in (chosen or []))
            if matched != bool(want):
                return False
        elif key == "chosen_side":
            # 事件 payload 的选择目标（on_card_played 携带 chosen）：恰好一个且指向
            # 式神，归属与 want（friendly|enemy|any）匹配——记仇"对单个己方式神使用
            # 的法术"（响应/延迟监听的事件条件；与 Step 级 chosen_* 键读法不同，
            # 本键读事件中的选择目标）
            refs = event.get("chosen")
            if (not isinstance(refs, (list, tuple)) or len(refs) != 1
                    or not isinstance(refs[0], Ref) or refs[0].shikigami is None):
                return False
            side = "friendly" if refs[0].player == controller else "enemy"
            if want != "any" and side != want:
                return False
        elif key == "combat_opponent_stunned":
            # 持有者参与事件中的战斗且交战对方眩晕（双向；对方可为牌手）——雪童子
            if holder is None:
                return False
            atk, vic = event.get("attacker"), event.get("victim")
            if not isinstance(atk, Ref) or not isinstance(vic, Ref):
                return False
            if holder == atk:
                other = vic
            elif holder == vic:
                other = atk
            else:
                return False
            if _ref_stunned(game, other) != bool(want):
                return False
        elif key.endswith("_le"):
            # 通用数值上限：事件字段 ≤ n（黄泉花境"耐久降低"amount_le: -1 类；
            # 事件无该字段时回退读控制者 PlayerState.ext，同 _ge 口径）
            val = event.get(key[:-3])
            if val is None:
                val = game.state.players[controller].ext.get(key[:-3], 0)
            if int(val) > int(want):
                return False
        elif key.endswith("_ge"):
            # 通用数值下限：事件字段 ≥ n（如 overheal_ge: 1 = 存在过量治疗）；
            # 事件无该字段时回退读控制者 PlayerState.ext（on_play 步 ctx.event 为空——
            # 狂风刃卷 yaohu_damage_count_ge 类计数比较）
            val = event.get(key[:-3])
            if val is None:
                val = game.state.players[controller].ext.get(key[:-3], 0)
            if int(val) < int(want):
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
        elif key.endswith("_stunned"):
            # 事件中的 Ref 所指角色（式神或牌手）是否眩晕（defender_stunned 类）
            ref = event.get(key[:-8])
            if not isinstance(ref, Ref):
                return False
            if _ref_stunned(game, ref) != bool(want):
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
            elif isinstance(want, (list, tuple)):
                # 多 id 匹配（番茄 10013199/10013198 双形态共享的牌手光环条件）
                if not isinstance(ref, Ref) or ref.shikigami is None:
                    return False
                if game.state.players[ref.player].shikigami[ref.shikigami].id not in want:
                    return False
            else:
                return False
        elif want == "self":
            if event.get(key) != controller:
                return False
        elif want == "opponent":
            if event.get(key) == controller:
                return False
        elif isinstance(want, (list, tuple)):
            # 列表等值匹配（任一命中即通过；如 kind: [combat, counter] 限战斗伤害类别）
            if event.get(key) not in want:
                return False
        elif event.get(key) != want:
            return False
    return True
