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

from core.model import ExecContext, PlayerState, Ref, ShikigamiState

ACTIONS: dict[str, Callable] = {}


def action(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        ACTIONS[name] = fn
        return fn

    return deco


def _luck_amount(game, ctx, amount: int, amount_ctx: str | None,
                 amount_ext: str | None, amount_ext_source: str | None) -> int:
    """伤害类 op 的数值扩展（契约 §3.4，只增不改）：
    - amount_ctx：<ctx变量>：累加效果上下文变量（luck_roll 写入的 luck_dice，骰子炸弹）；
    - amount_ext：<key>：累加 ext 计数——默认读来源式神所属牌手 ext（谁还不听话
      dice_six_count）；amount_ext_source="shikigami" 改读来源式神 ext（聚气
      yaohu_dmg_bonus）。
    """
    if amount_ctx is not None:
        amount += int((ctx.memo or {}).get(amount_ctx, 0))
    if amount_ext is not None:
        holder: dict | None = None
        if amount_ext_source == "shikigami" and ctx.source is not None \
                and ctx.source.shikigami is not None:
            holder = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].ext
        if holder is None:
            pi = ctx.source.player if ctx.source is not None else ctx.controller
            holder = game.state.players[pi].ext
        amount += int(holder.get(amount_ext, 0))
    return amount


@action("damage")
def damage(game, ctx, *, targets: list[Ref], amount: int = 0,
           piercing: bool | None = None, amount_ctx: str | None = None,
           amount_ext: str | None = None, amount_ext_source: str | None = None) -> None:
    """对目标（式神或牌手）造成 amount 点伤害；护甲优先吸收。

    实例修饰 damage_boost（鎏金幻羽给手牌黄金羽的"伤害+1"）在卡牌效果伤害上累加。
    贯通：piercing 显式指定优先（牌面明确"贯通伤害"的卡牌效果）；缺省时仅当伤害
    来自式神能力且来源式神具有贯通才继承——卡牌效果伤害不因式神持有贯通而贯通
    （terminology.md「贯通」）。
    amount_ctx / amount_ext / amount_ext_source：数值扩展（契约 §3.4，见 _luck_amount）。
    """
    amount = _luck_amount(game, ctx, amount, amount_ctx, amount_ext, amount_ext_source)
    if ctx.card is not None:
        amount += int(ctx.card.mods.get("damage_boost", 0))
        # 卡牌光环伤害加成（寒冬之心"本局游戏你所有'雪球'的伤害+1"；可叠加）
        cdef = game.db.cards[ctx.card.id]
        amount += sum(int(a.get("damage_boost", 0))
                      for a in game._match_auras(game.state.players[ctx.controller], cdef))
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
    spell = game._spell_damage(ctx)  # 法术伤害标记（庇佑判定用，答复(7)）
    total = 0
    for ref in targets:
        if ref.shikigami is None:
            total += game.deal_to_player(ref.player, amount, ctx.source, spell=spell)
        else:
            total += game.deal_to_shikigami(ref, amount, ctx.source, piercing=pierce,
                                            spell=spell)
    if ctx.memo is not None:
        # 记录本步伤害的受伤者（式神），供同块后续 step 以 context 目标引用（风神一扇）
        ctx.memo["last_damage_victims"] = [r for r in targets if r.shikigami is not None]
        # 记录本步实际造成的伤害合计（扣减生命口径），供同块后续 step 以 {"memo": key}
        # 动态数值引用（巨浪"每造成 1 点伤害，海坊主便恢复 1 生命"）
        ctx.memo["last_damage_total"] = total


@action("heal")
def heal(game, ctx, *, targets: list[Ref], amount: int = 0, full: bool = False) -> None:
    """恢复生命（走 Game.heal 治疗事件流程）：治疗量 = min(amount, 已损失生命)，
    0 终止；濒死/气绝（未在场）式神与气绝牌手不受治疗。
    结算后把本步治疗目标写入块内暂存 ctx.memo["last_heal_targets"]（供佛光
    "为其操控者的所有角色"以 side_of_last_heal 池引用）。"""
    for ref in targets:
        amt = amount
        if full:
            # 恢复至满：逐目标按其缺失生命（沐浴阳光"恢复所有生命"）
            pl = game.state.players[ref.player]
            holder = pl.shikigami[ref.shikigami] if ref.shikigami is not None else pl
            amt = holder.max_health - holder.health
        game.heal(ref, amt, ctx.source, reason="heal")
    if ctx.memo is not None:
        ctx.memo["last_heal_targets"] = list(targets)


@action("draw")
def draw(game, ctx, *, targets: list[Ref], count: int | dict = 1,
         side: str | None = None) -> None:
    """抽牌（targets 忽略）：默认效果归属玩家抽 count 张。牌库抽空判负。

    count 支持 {"memo": key}：读块内暂存 ctx.memo[key]（射怪鸟事"弃多少抽多少"，与
    discard 写入的 discarded_count 组合）；{"hand_to": n}：抽至手牌 n 张（福满乾坤
    "抽手牌直至十张"）。side="self"/"opponent"：改由指定方抽牌（福满乾坤依次对双方）。
    """
    pi = ctx.controller if side in (None, "self") else 1 - ctx.controller
    p = game.state.players[pi]
    if isinstance(count, dict):
        if count.get("hand_to") is not None:
            n = max(0, int(count["hand_to"]) - len(p.hand))
        else:
            n = int((ctx.memo or {}).get(count.get("memo"), 0))
    else:
        n = int(count)
    game.draw_cards(pi, n)


@action("buff_power")
def buff_power(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False,
               scope: str | None = None, amount_ctx: str | None = None,
               amount_ext: str | None = None, amount_ext_source: str | None = None,
               amount_sign: int = 1) -> None:
    """力量增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。

    已气绝式神不能获得非永久增益，但可以获得永久增益（thoughts.txt"已气绝状态"）；
    0 级未在场/已离场式神不受影响。
    scope="turn"：临时增益记账到 ext["turn_power"]，回合开始时随该通道一并清除
    （武士之笛/鼓舞类"本回合"增益；与 perm 互斥，数据侧只对临时增益使用）。
    amount_ctx / amount_ext / amount_ext_source：数值扩展（见 _luck_amount；
    来打我呀/萌即正义增强按 dice_six_count 增减）；amount_sign=-1 转为 debuff。
    """
    amount = _luck_amount(game, ctx, amount, amount_ctx, amount_ext,
                          amount_ext_source) * int(amount_sign)
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play and (s.despawned or not s.defeated or not perm):
                continue
            if perm:
                s.perm_power += amount
            else:
                s.temp_power += amount
                if scope == "turn":
                    s.ext["turn_power"] = s.ext.get("turn_power", 0) + amount
            game._record_max_power(s)
            game._settle(f"【力量】{game.db.shikigami[s.id].name} "
                         f"{'永久' if perm else '临时'}力量 {amount:+d}（现 {s.eff_power}）")


@action("buff_health")
def buff_health(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False,
                amount_ctx: str | None = None, amount_ext: str | None = None,
                amount_ext_source: str | None = None, amount_sign: int = 1) -> None:
    """生命上限增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。

    已气绝式神不能获得非永久增益，但可以获得永久增益（当前生命不随之上调，
    复活时按新上限回满）；0 级未在场/已离场式神不受影响。
    上限上调伴随的当前生命等量增加是直改而非治疗：不走 heal 事件、不触发
    "恢复生命时"类能力（维护者确认：古尘之壁"获得x生命"不算治疗）。
    上限下调（负值，墨笔夺魂"降低生命"）：同步钳当前生命到新上限；上限降至
    不大于 0 时目标气绝（维护者定案）。
    amount_ctx / amount_ext / amount_ext_source / amount_sign：数值扩展（同 buff_power）。
    """
    amount = _luck_amount(game, ctx, amount, amount_ctx, amount_ext,
                          amount_ext_source) * int(amount_sign)
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play and (s.despawned or not s.defeated or not perm):
                continue
            if perm:
                s.perm_health += amount
                if not s.defeated and amount > 0:
                    s.health += amount
            else:
                s.temp_health += amount
                # 临时增加上限时，当前生命同步增加等量数值（不超过新上限）
                if amount > 0:
                    s.health = min(s.max_health, s.health + amount)
            if amount < 0 and not s.defeated:
                s.health = min(s.health, s.max_health)  # 上限降低钳当前生命
                if s.max_health <= 0:
                    s.health = 0
                    game.check_defeated(ref, source=ctx.source, reason="消灭")
                    continue
            game._settle(f"【生命】{game.db.shikigami[s.id].name} "
                         f"{'永久' if perm else '临时'}生命上限 {amount:+d}"
                         f"（现 {s.health}/{s.max_health}）")


@action("gain_shield")
def gain_shield(game, ctx, *, targets: list[Ref], amount: int, kind: str = "shield",
                no_extract: bool = False) -> None:
    """获得/失去护甲或破甲（式神与牌手均可；docs/rules.md 第六章）。

    kind="shield"（缺省）：amount > 0 获得护甲 / < 0 失去护甲（旧用法 {amount: n} 等价
    kind=shield 获得，向后兼容）；kind="fragile"：amount > 0 获得破甲 / < 0 失去破甲。
    获得先抵消反向值再盈余同向；减少只能扣已有的同向值。0 级未在场式神不能获得
    护甲/破甲/增益。护甲/破甲变化按即时时机发出 on_shield_changed 事件（payload 带 kind）。
    no_extract=True：战斗牌中该步不提取为战斗牌护甲前置结算，按步骤顺序执行
    （醉酒当歌"先自伤 3 再获得等量护甲"——前置结算会被自己的自伤消耗）。
    """
    for ref in targets:
        if ref.shikigami is None:
            game._change_shield(ref, amount, "gain_shield", kind=kind)
        else:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if s.in_play:
                game._change_shield(ref, amount, "gain_shield", kind=kind)


@action("summon")
def summon(game, ctx, *, targets: list[Ref], shikigami: int, orb_cost: int = 0,
           inherit_stats: bool = False, energy_ratio: float | None = None) -> None:
    """为效果归属玩家召唤一个召唤物（定义须 kind=summon）。

    召唤物的生成视作其移动进入战斗区（但不视为从准备区离开）；
    若战斗区已有驻留者，其退回准备区（召唤物则直接离场）。
    若该召唤物定义 keep_buffs=True，则同名再召时继承上次离场时的永久增减益。
    orb_cost>0（坐下 20200227"额外消耗1点鬼火，召唤'番茄'"）：效果内嵌费用——
    控制者剩余鬼火不足则本步空过（召唤失败，其余步骤照常），足够则先付再召。
    """
    d = game.db.shikigami[shikigami]
    p = game.state.players[ctx.controller]
    if orb_cost:
        if p.orb < orb_cost:
            game._log(f"{p.name} 鬼火不足，召唤失败")
            return
        old = p.orb
        p.orb -= orb_cost
        game.emit("on_orb_changed", player=ctx.controller, old=old, new=p.orb,
                  reason="summon_orb_cost")
    if game._combat_zone_locked(ctx.controller):
        # 尘缚之阵：兵俑在战斗区且己方战斗区有式神时，召唤召唤物的效果无效
        game._log(f"{p.name} 的召唤效果被尘缚之阵无效化")
        return
    s = ShikigamiState(
        id=shikigami, kind="summon", faction=d.faction, level=1,
        home_slot=None,
        base_power=d.power, base_health=d.health, health=d.health,
        perm_keywords=list(d.keywords))  # 先天关键字（充能/迅捷等）按永久类别入列（同 build_player）
    legacy = p.summon_legacy.get(shikigami)
    if legacy:
        s.perm_power = legacy.get("perm_power", 0)
        s.perm_health = legacy.get("perm_health", 0)
        s.health += s.perm_health
    if ctx.source is not None and ctx.source.shikigami is not None:
        src = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        if inherit_stats:
            # 复制来源当前全部身材（维护者定案：当前力量含临时/光环增益、当前生命上限、
            # 当前生命值含受伤不满）——以一次性永久修正落到实例（静态基值，
            # 不进 dyn 缓存通道，召唤物自身的动态光环重算不丢失继承部分）
            s.perm_power = src.eff_power - s.base_power
            s.perm_health = src.max_health - s.base_health
            s.health = min(src.health, s.max_health)
        if energy_ratio is not None:
            s.energy = int(src.energy * energy_ratio)  # 能量按比例复制（向下取整）
    s.ext["max_power"] = s.base_power + s.perm_power  # 力量历史峰值初值（断臂记账）
    p.shikigami.append(s)
    idx = len(p.shikigami) - 1
    game._log(f"{p.name} 召唤了 {d.name}")
    game._enter_combat(p, idx)  # 召唤即进入战斗区（召唤进场也算移动）
    game.emit("on_summon", shikigami=Ref(player=ctx.controller, shikigami=idx))


@action("emit")
def emit_event(game, ctx, *, targets: list[Ref], event: str, payload: dict | None = None) -> None:
    """触发自定义事件（须在 db/events.yaml 中声明）。DIY 扩展入口。"""
    game.emit(event, controller=ctx.controller, **(payload or {}))


@action("attack_buff")
def attack_buff(game, ctx, *, targets: list[Ref], power: int = 0,
                keywords: list[str] | None = None) -> None:
    """攻击后到期临时强化（起弓/离/无我）：立即生效并挂账 attack_buffs。

    在目标式神自身作为攻击者的战斗终止点统一核销（rules.md:174"直到攻击后"）；
    持有 keep_attack_buffs（残心）时跳过核销。气绝时随临时修正一并清空。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        entry: dict = {"power": power, "keywords": []}
        if power:
            s.temp_power += power
            game._record_max_power(s)
        for kw in keywords or []:
            cls = game._grant_keyword(s, kw)
            entry["keywords"].append((kw, cls))
        s.attack_buffs.append(entry)
        game._log(f"{game.db.shikigami[s.id].name} 获得强化（直到其下一次攻击后）")


@action("keep_shield")
def keep_shield(game, ctx, *, targets: list[Ref]) -> None:
    """目标式神的护甲不再于己方回合开始阶段移除（觉醒·兵俑）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        game.state.players[ref.player].shikigami[ref.shikigami].keep_shield = True


@action("keep_fragile")
def keep_fragile(game, ctx, *, targets: list[Ref]) -> None:
    """目标式神的破甲不再于己方回合开始阶段移除（肿胀体质；keep_shield 先例）。
    形态离场时经 _destroy_form 一并解除（"形态在场时"语义）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        game.state.players[ref.player].shikigami[ref.shikigami].keep_fragile = True


@action("transfer_fragile")
def transfer_fragile(game, ctx, *, targets: list[Ref]) -> None:
    """破甲转移（腐坏直拳）：来源（式神或牌手）的破甲等量转移给每个目标后来源清零。

    目标为多名时每名各获全量（非分配）；来源无破甲（shield >= 0）为空操作。
    腐坏直拳用法：战斗牌 temp_grants 挂 on_before_assault（确定攻击目标后触发，
    target={kind: context, key: victim}）——战斗牌本身给的破甲也一并转移（定案(3)）。
    """
    if ctx.source is None:
        raise ValueError("transfer_fragile 需要来源（式神或牌手）")
    sp = game.state.players[ctx.source.player]
    holder = (sp.shikigami[ctx.source.shikigami]
              if ctx.source.shikigami is not None else sp)
    if holder.shield >= 0:
        return  # 来源无破甲：空操作
    amount = -holder.shield
    # 来源清零（走失去破甲流程，发 on_shield_changed）
    game._change_shield(ctx.source, holder.shield, "transfer_fragile", kind="fragile")
    for ref in targets:
        game._change_shield(ref, amount, "transfer_fragile", kind="fragile")


@action("add_mod")
def add_mod(game, ctx, *, targets: list[Ref], to: str, key: str = "enhance",
            amount: int = 1, cap: int | None = None, require: dict | None = None) -> None:
    """写入修饰（docs/enhance-design.md 写入三目标；targets 忽略）。

    - to=persistent：写入控制者的持久 store `card_mods[ctx.card_id]`（"本局游戏每……"类，
      跨回合累积，打出时装配快照；需要 ctx.card_id，即卡牌触发器场景）。
    - to=hand：写入控制者手牌中所有同 id 实例的 `card.mods[key]`（按实例隔离，
      之后才抽到的同名复制不受影响）。
    - to=instance：写入来源实例自身 `ctx.card.mods[key]`（实例计数器，如风符·龙的目标数）。
    cap 为累积上限（如"最多+3"）。
    require={"key": k, "ge": n}：条件写入——同一 store 中键 k 的当前值 ≥ n 才执行
    本次写入（吾即正义"使用过 10 次法术则变为"：先计数、再按计数置位 transformed）。
    """
    p = game.state.players[ctx.controller]

    def _bump(store: dict, k: str) -> None:
        if require is not None and store.get(require.get("key"), 0) < require.get("ge", 1):
            return  # 条件写入：计数未达标，跳过
        store[k] = store.get(k, 0) + amount
        if cap is not None:
            store[k] = min(store[k], cap)

    if to == "persistent":
        if ctx.card_id is None:
            raise ValueError("add_mod(to=persistent) 需要 ctx.card_id（卡牌触发器来源卡）")
        _bump(p.card_mods.setdefault(ctx.card_id, {}), key)
    elif to == "hand":
        if ctx.card_id is None:
            raise ValueError("add_mod(to=hand) 需要 ctx.card_id（卡牌触发器来源卡）")
        for c in p.hand:
            if c.id == ctx.card_id:
                _bump(c.mods, key)
    elif to == "instance":
        if ctx.card is None:
            raise ValueError("add_mod(to=instance) 需要 ctx.card（来源卡牌实例）")
        _bump(ctx.card.mods, key)
    else:
        raise ValueError(f"未知 add_mod 写入目标: {to}")


@action("mod_hand")
def mod_hand(game, ctx, *, targets: list[Ref], tag: str | None = None,
             token: bool | None = None, mods: dict | None = None,
             once_key: str | None = None) -> None:
    """给控制者手牌中符合谓词的卡牌实例写入实例修饰（targets 忽略；鎏金幻羽）。

    谓词：tag=卡牌 tags 含该标记 / token=是否衍生卡（"真黄金羽"= tags 含 golden_feather
    且为 token——金风流羽只在使用时视为黄金羽，不修饰，维护者答复 8）。
    once_key：实例已有该键则跳过（"不可叠加"）。写入键的读取点：
    playable_when_defeated（engine._playable_when_defeated）、damage_boost（damage 动作）、
    revive_haste（engine._apply_revive_haste）。
    """
    p = game.state.players[ctx.controller]
    n = 0
    for c in p.hand:
        cd = game.db.cards[c.id]
        if tag is not None and tag not in cd.tags:
            continue
        if token is not None and cd.token != token:
            continue
        if once_key is not None and c.mods.get(once_key):
            continue  # 不可叠加：已修饰过的实例跳过
        for k, v in (mods or {}).items():
            c.mods[k] = v
        n += 1
    if n:
        game._log(f"{p.name} 手牌中 {n} 张牌获得了修饰")


@action("card_aura")
def card_aura(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
              card_type: str | None = None, card_id: int | None = None,
              tag: str | None = None,
              keywords: list[str] | None = None,
              cost_zero: bool = False, power: int = 0, shield: int = 0,
              power_ext: str | None = None, shield_ext: str | None = None,
              damage_boost: int = 0,
              turn: str | None = None, scope: str = "turn",
              require_holder_form: bool = False) -> None:
    """登记卡牌光环（targets 忽略）：谓词匹配的卡牌获得 keywords / 不耗鬼火 / 数值加成。

    覆盖谓词命中的全部卡牌（任何区域，含之后新生成的）——读取时求值而非写入实例。
    card_id：仅命中该数据 id 的牌（"此牌"类自指光环，伺机）。
    tag：仅命中 tags 含该标记的牌（寒冬之心"你所有'雪球'"）。
    power/shield 为战斗牌数值通道（combat_card_stats 读取时叠加到战力/一次性护甲）：
    可叠加——多次授予数值累加（与 keywords 的集合语义不同）。
    power_ext/shield_ext：数值改从控制者 PlayerState.ext[key] 读取（心技一体"本局
    每使用过一张炼磨牌+1/+1"——出牌记账见 _account_card_played，读取时求值）。
    damage_boost：卡牌效果伤害 +N（寒冬之心"本局游戏你所有'雪球'的伤害+1"；
    damage 动作读取时叠加，可叠加）。
    turn："self"/"opponent" 限定回合方，仅己方/敌方回合时光环生效（伺机类）。
    scope 为失效时机："turn" = 己方回合开始清除（"本回合"类）；"form" = 绑定来源式神
    当前结附的形态，形态离场时移除（心技一体；气绝经 _destroy_form 同路径）；
    "ability" = 绑定来源座次的当前能力，能力离场（气绝/变形/离场/觉醒替换）时移除，
    能力进场（on_ability_enter）重新注册（萤草形态牌光环类）；
    "game" = 本局游戏有效，不清除（寒冬之心类）。
    require_holder_form：额外要求来源式神当前结附形态才生效（20200327 版萤草
    "若萤草上有形态"）；读取时由 _match_auras 判定，且按持有者随形态离场移除。
    shikigami="any"：通配——命中控制者任意式神（含中立）的牌（觉醒·萤草
    "己方式神的形态牌"、爱意绵绵"你手牌所有法术牌"）。
    """
    if turn not in (None, "self", "opponent"):
        raise ValueError(f"未知 card_aura 回合方限定: {turn}")
    if scope not in ("turn", "form", "game", "ability"):
        raise ValueError(f"未知 card_aura 作用域: {scope}")
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("card_aura(shikigami=self) 需要来源式神")
        sid: int | None = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
    elif shikigami == "any":
        sid = None  # 通配：读取时命中任意所属式神的牌
    else:
        sid = int(shikigami)
    aura = {
        "shikigami": sid, "card_type": card_type, "card_id": card_id,
        "tag": tag,
        "keywords": list(keywords or []), "cost_zero": cost_zero,
        "power": power, "shield": shield, "turn": turn, "scope": scope,
    }
    if power_ext is not None:
        aura["power_ext"] = power_ext
    if shield_ext is not None:
        aura["shield_ext"] = shield_ext
    if damage_boost:
        aura["damage_boost"] = int(damage_boost)  # 卡牌效果伤害加成（寒冬之心的雪球）
    if require_holder_form:
        aura["require_holder_form"] = True
    if scope in ("form", "ability") or require_holder_form:
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError(f"card_aura(scope={scope}) 需要来源式神")
        aura["holder"] = [ctx.source.player, ctx.source.shikigami]  # 形态/能力离场按持有者移除
    game.state.players[ctx.controller].card_auras.append(aura)
    label = "全体式神" if sid is None else game.db.shikigami[sid].name
    game._log(f"{label} 的卡牌光环生效（{scope}）")


@action("stat_aura")
def stat_aura(game, ctx, *, targets: list[Ref], kind: str, scope: str = "form",
              ids: list[int] | None = None, power: int = 0, health: int = 0,
              ext: str | None = None, divisor: int = 1) -> None:
    """登记连续型动态身材光环（targets 忽略；闻世/火吻之蛇）——读取时求值的通用修饰：
    不写死数值，由 Game._refresh_stat_auras 在手牌数/破甲变化等读取点重算
    ext["dyn_power"]/["dyn_health"] 缓存通道（eff_power/max_health 读取时叠加）。

    kind="self_hand_count"：持有者每有一张其他手牌 +1/+1（闻世）；
    kind="enemy_fragile_power"：敌方有破甲的式神降低等于其破甲的力量（火吻之蛇）；
    kind="enemy_stunned_exists"：场上有[眩晕]的敌方角色时持有者 +power/+health
    （雪国之子；活局面判定，眩晕全部解除即失去）；
    kind="ext_power"：持有者 +力量 = 控制者 ext[ext] 计数 × power 倍率
    （雪融之时[增强]"本局游戏每有一个敌方角色被[眩晕]便+1力量"——计数引擎记账
    于 PlayerState.ext["enemy_stunned_game"]，光环读取时求值）；
    kind="ids_power"：控制者在场实体中数据 id ∈ ids 者 +power 力量（坐下"番茄永久
    +1 力量"——视作结附牌手的本局永久光环，跨召唤保留，对番茄召唤物 10013199 与
    变形番茄 10013198 都生效；可叠加）。
    kind="energy_power"：持有者每有 divisor 点能量 +power 力量（人多势众"镰鼬每有
    2能量便获得1力量"——能量读持有者 ShikigamiState.energy，读取时求值；divisor
    缺省 1，power 为每组倍率缺省 1）。
    kind="ids_energy_power"：ids 匹配实体每有 divisor 点能量 +power 力量（烟雾缭绕
    "'烟烟罗的分身'每有1能量便获得1力量"——能量读匹配实体自身）。
    scope="form"（缺省）：绑定来源式神当前形态，形态离场时移除（气绝经
    _destroy_form 同路径）。登记时持有者当前生命按新上限回满（形态结附生命回满
    在光环登记之前，此处补齐动态上限部分）。
    scope="game"（ids_power/ids_energy_power 可选）：本局游戏有效，不绑定形态、不清除。
    scope="form"（ids_power/ids_energy_power 可选）：绑定来源形态、记 holder，形态离场
    经 _destroy_form 同路径移除（烟雾缭绕）。
    """
    if kind not in ("self_hand_count", "enemy_fragile_power", "enemy_stunned_exists",
                    "ext_power", "ids_power", "energy_power", "ids_energy_power"):
        raise ValueError(f"未知 stat_aura 类型: {kind}")
    if kind in ("ids_power", "ids_energy_power"):
        if scope not in ("game", "form"):
            raise ValueError(f"stat_aura(kind={kind}) 作用域须为 game 或 form")
        if not ids:
            raise ValueError(f"stat_aura(kind={kind}) 需要 ids（匹配的数据 id 列表）")
        entry: dict = {"kind": kind, "scope": scope,
                       "ids": [int(i) for i in ids], "power": int(power)}
        if kind == "ids_energy_power":
            entry["power"] = int(power) or 1  # 每组能量的力量倍率（缺省 1）
            entry["divisor"] = int(divisor)   # 每有 divisor 点能量 +power（读实体自身能量）
        if scope == "form":
            if ctx.source is None or ctx.source.shikigami is None:
                raise ValueError(f"stat_aura(kind={kind}, scope=form) 需要来源式神")
            entry["holder"] = [ctx.source.player, ctx.source.shikigami]  # 形态离场按持有者移除
        p = game.state.players[ctx.controller]
        p.ext.setdefault("stat_auras", []).append(entry)
        game._refresh_stat_auras()
        game._log(f"{p.name} 的召唤物光环生效（{sorted(int(i) for i in ids)} 力量 {int(power):+d}）")
        return
    if scope != "form":
        raise ValueError(f"未知 stat_aura 作用域: {scope}")
    if kind == "ext_power" and not ext:
        raise ValueError("stat_aura(kind=ext_power) 需要 ext（控制者 ext 计数键）")
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("stat_aura 需要来源式神")
    p = game.state.players[ctx.controller]
    entry: dict = {
        "kind": kind, "scope": scope,
        "holder": [ctx.source.player, ctx.source.shikigami],
    }
    if power:
        entry["power"] = int(power)
    if health:
        entry["health"] = int(health)
    if ext is not None:
        entry["ext"] = ext
    if kind == "energy_power":
        entry["power"] = int(power) or 1  # 每组能量的力量倍率（缺省 1）
        entry["divisor"] = int(divisor)   # 每有 divisor 点能量一组（人多势众=2）
    p.ext.setdefault("stat_auras", []).append(entry)
    game._refresh_stat_auras()
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    s.health = s.max_health
    game._log(f"{game.db.shikigami[s.id].name} 的动态光环生效")


@action("mulligan_hand")
def mulligan_hand(game, ctx, *, targets: list[Ref], times: int = 3,
                  shuffle: bool = True, target_side: str = "self",
                  only_revealed: bool = False, auto: bool = False) -> None:
    """战中调度（云游；targets 忽略）：调度控制者手牌至多 times 次——每次把一张手牌
    返回牌库随机位置再随机抽一张（_swap_hand_card 核心，与游戏开始阶段调度共用），
    choose 指令作答（uid=手牌；uid 缺省 = 提前结束），结束后洗牌库。
    通过 pending_choice（kind="mulligan_pick"）挂起，由 choose 指令续跑（deck_top_pick 先例）。

    强索通道（auto=True）：无 pending_choice 交互——对 target_side 所指方（opponent=
    敌方）手牌按入手顺序（hand_seq 升序）取前 times 张候选自动调度（only_revealed=
    True 时仅"已展示"牌为候选）；逐张 _swap_hand_card（展示状态传递见其内），
    有实际调度才洗牌库（rules.md:531；候选为空/牌库为空不洗）。
    """
    if auto:
        pi = ctx.controller if target_side == "self" else 1 - ctx.controller
        p = game.state.players[pi]
        cands = sorted(p.hand, key=lambda c: c.hand_seq)
        if only_revealed:
            cands = [c for c in cands if c.mods.get("revealed")]
        swapped = 0
        for c in cands[:max(0, int(times))]:
            if not p.deck:
                break  # 待调度牌库为空：终止调度流程（rules.md:524）
            game._swap_hand_card(p, c)
            swapped += 1
        if swapped:
            game._log(f"{p.name} 的 {swapped} 张手牌被强制调度")
            if shuffle:
                game.rng.shuffle(p.deck)
                game._log(f"{p.name} 洗了牌库")
        return
    p = game.state.players[ctx.controller]
    if int(times) <= 0 or not p.hand:
        if shuffle:
            game.rng.shuffle(p.deck)
            game._log(f"{p.name} 洗了牌库")
        return
    game.state.pending_choice = {
        "kind": "mulligan_pick", "player": ctx.controller,
        "remaining": int(times), "shuffle": bool(shuffle),
    }
    game._log(f"{p.name} 调度手牌（至多 {times} 次）")


@action("reveal")
def reveal(game, ctx, *, targets: list[Ref], mode: str = "event",
           shikigami: int | str | None = None) -> None:
    """展示手牌（"已展示"机制；targets 忽略）：置 CardInstance.mods["revealed"]
    ——本局保持、随实例（回库/墓地不自动清除；调度传递见 _swap_hand_card）。

    mode（作用于敌方手牌）：
    - random：随机一张未展示的手牌（已全部展示则无效果）；
    - shikigami：指定式神（shikigami=<数据 id> 或 "chosen"=卡牌选择目标所指式神）的
      专属牌全部——协战牌未使用时视为同时属于两位所属式神（_card_belongs_to 口径）；
    - all：敌方全部手牌；
    - event（缺省）：触发事件 payload 的 card 实例——入手钩子（on_card_enter_hand）
      挂载"每当一张牌进入敌方手牌时将其展示"类被动用（事件牌已离开手牌时仍置标志，
      随实例）。
    """
    from core.model import CardInstance

    def _show(card) -> None:
        if card.mods.get("revealed"):
            return  # 已展示：幂等
        card.mods["revealed"] = True
        game._log(f"【{game.db.cards[card.id].name}】被展示")

    if mode == "event":
        card = (ctx.event or {}).get("card")
        if isinstance(card, CardInstance):
            _show(card)
        return
    enemy = game.state.players[1 - ctx.controller]
    if mode == "random":
        pool = [c for c in enemy.hand if not c.mods.get("revealed")]
        picks = [game.rng.choice(pool)] if pool else []
    elif mode == "all":
        picks = list(enemy.hand)
    elif mode == "shikigami":
        if shikigami == "chosen":
            chosen = ctx.chosen or []
            if not chosen or chosen[0].shikigami is None:
                return  # 无有效选择目标：空操作
            sid = game.state.players[chosen[0].player].shikigami[chosen[0].shikigami].id
        elif shikigami is None:
            raise ValueError("reveal(mode=shikigami) 需要 shikigami 参数（数据 id 或 chosen）")
        else:
            sid = int(shikigami)
        picks = [c for c in enemy.hand
                 if game._card_belongs_to(game.db.cards[c.id], sid)]
    else:
        raise ValueError(f"未知 reveal 模式: {mode}")
    for c in picks:
        _show(c)


@action("grant_keyword")
def grant_keyword(game, ctx, *, targets: list[Ref], keyword: str,
                  scope: str | None = None) -> None:
    """授予目标式神一个关键字（按关键字的天然持久性类别入列，见 engine._grant_keyword）。

    scope="battle"：战斗作用域条件授予——绑定当前战斗上下文，战斗终止点按实例移除
    （觉醒·雪童子"与眩晕的式神交战时获得[连击]"：挂 on_before_assault + 条件
    combat_opponent_stunned）；无战斗上下文时回退为常规授予。
    scope="turn"：当回合结束移除（惊鸿之舞"所有己方式神本回合获得[帷幕]和[不屈]"——
    触发发生在哪方回合就在那方回合结束点移除，引擎 _remove_turn_keyword_grants 按
    授予时回合号比对；一次性关键字（[不屈]）被正常消耗后不到回合结束即已移除）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if not s.in_play:
            continue
        cls = game._grant_keyword(s, keyword)
        if scope == "battle" and game._battle_stack:
            bid = game._battle_stack[-1]
            game._battle_grants.setdefault(bid, []).append((ref, keyword, cls))
        if scope == "turn":
            game.state.players[ref.player].ext.setdefault(
                "turn_keyword_grants", []).append(
                {"ref": ref, "keyword": keyword, "cls": cls, "turn": game.state.turn})


@action("trigger_form_countdown")
def trigger_form_countdown(game, ctx, *, targets: list[Ref]) -> None:
    """触发事件中形态牌的倒计时效果（一目连基础/觉醒能力；targets 忽略）。

    结附中的形态读式神 countdown_block（倒计时框架注册的块）；已离场的形态倒计时
    已清除，回退读卡牌数据的 countdown_effects（同一块）。立即触发只结算倒计时效果
    本身：不改变倒计时值、不重置/移除。无倒计时效果（如风符·瞬）时为空操作。
    """
    card = (ctx.event or {}).get("card")
    if card is None:
        return
    block = None
    if ctx.source is not None and ctx.source.shikigami is not None:
        s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        if s.form is card and s.countdown_block is not None:
            block = s.countdown_block
    if block is None:
        block = game.db.cards[card.id].countdown_effects
    if block is None:
        return
    game._resolve_block(block, ExecContext(
        controller=ctx.controller, source=ctx.source, card=card, is_ability=True))
    # 形态倒计时效果属形态能力（贯通继承判定）


@action("destroy_form")
def destroy_form(game, ctx, *, targets: list[Ref]) -> None:
    """消灭目标式神当前结附的形态（无形态时为空操作，罡风后续步骤照常）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        game._destroy_form(game.state.players[ref.player], ref.shikigami, reason="effect")


@action("destroy")
def destroy(game, ctx, *, targets: list[Ref]) -> None:
    """直接消灭目标（非伤害：生命归零走气绝流程；尘缚之阵的免疫直接消灭在此判定）。
    濒死者不能再次被消灭（早退）。
    目标为牌手时（夺命增强变后"消灭受到判官战斗伤害的角色"）：消灭牌手 = 直接获胜——
    牌手气绝、对局进入待结束（维护者定案）。"""
    for ref in targets:
        if ref.shikigami is None:
            pl = game.state.players[ref.player]
            if pl.defeated:
                continue
            game._log(f"{pl.name} 被直接消灭")
            game._set_pending_end(loser=ref.player, defeat=True)
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if not s.in_play or s.dying:
            continue
        if game._direct_destroy_immune(ref.player, ref.shikigami):
            game._log(f"{game.db.shikigami[s.id].name} 免疫了本次消灭")
            continue
        s.health = 0
        game.check_defeated(ref, source=ctx.source, reason="消灭")


@action("random_branch")
def random_branch(game, ctx, *, targets: list[Ref],
                  branches: list | None = None) -> None:
    """随机分支（targets 忽略；惊鸿之舞"每个回合开始时随机触发一个效果"）：
    逐项求值 branch 的 condition（复用条件迷你语言，事件上下文为触发事件；
    缺省/null 恒真），从通过者中均等概率随机选一项并执行其 steps；
    无满足分支则空操作。branches 元素：{"condition": {...}|None, "steps": [Step 字典]}。
    """
    from db.schema import Step
    ok = [b for b in (branches or [])
          if game._match(b.get("condition"), ctx.event or {}, ctx.controller,
                         holder=ctx.source)]
    if not ok:
        return
    chosen = game.rng.choice(ok)
    for st in chosen.get("steps", []):
        game._run_step(Step.model_validate(st), ctx)


@action("basic_boost")
def basic_boost(game, ctx, *, targets: list[Ref], power: int = 0, shield: int = 0,
                keyword_random: list | None = None) -> None:
    """鼓舞：登记一笔出击加成（targets 忽略）。下一次出击时全部消耗——
    力量直到该次出击的战斗后，护甲保留；战斗牌不消耗出击加成。
    觉醒·不知火类旗标（inspire_bonus 登记的 PlayerState.ext["boost_flags"]）：
    该玩家的鼓舞数值额外 +power/+shield（可叠加）。
    keyword_random：随机关键字池（惊鸿之舞鼓舞项"和一个随机效果"）——授予时从池中
    均等随机一个存入玩家级关键字槽（ext["boost_keyword"]；槽至多一个，后授予的替换
    已有）；消耗出击加成的攻击中临时授予攻击者、随加成消耗清除（引擎
    _consume_assault_boosts；inspire_bonus 只加算数值，不影响关键字部分）。"""
    p = game.state.players[ctx.controller]
    power += sum(int(e.get("power", 0)) for e in p.ext.get("boost_flags", [])
                 if e.get("kind") == "inspire_bonus")
    shield += sum(int(e.get("shield", 0)) for e in p.ext.get("boost_flags", [])
                  if e.get("kind") == "inspire_bonus")
    p.assault_boosts.append({"power": power, "shield": shield})
    if keyword_random:
        kw = game.rng.choice(list(keyword_random))  # 均等随机；槽位替换语义
        p.ext["boost_keyword"] = kw
        game._log(f"{p.name} 的出击加成获得关键字 {kw}")
    game._log(f"{p.name} 获得出击加成（+{power}力量/+{shield}护甲）")


@action("consume_assault_boosts")
def consume_assault_boosts(game, ctx, *, targets: list[Ref]) -> None:
    """消耗己方全部出击加成（鼓舞），作为该战斗牌赋予来源式神的加成
    （targets 忽略；灵矢贯虹羁绊，维护者答复 10：战力/护甲作为此战斗牌赋予的效果
    ——战力持续到本次战斗结束后经 combat_power 核销、护甲保留；鼓舞关键字槽
    （ext["boost_keyword"]，惊鸿之舞）同样转移——临时授予来源式神、经 attack_buffs
    随本次战斗结束移除）。战斗牌本不消耗鼓舞，本步为牌面指定的例外。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("consume_assault_boosts 需要来源式神")
    p = game.state.players[ctx.controller]
    if not p.assault_boosts:
        return
    power = sum(int(b.get("power", 0)) for b in p.assault_boosts)
    shield = sum(int(b.get("shield", 0)) for b in p.assault_boosts)
    p.assault_boosts.clear()
    s = p.shikigami[ctx.source.shikigami]
    if power:
        s.combat_power += power
    if shield:
        game._change_shield(ctx.source, shield, "consume_assault_boosts")
    bkw = p.ext.pop("boost_keyword", None)
    if bkw:
        cls = game._grant_keyword(s, bkw)
        s.attack_buffs.append({"power": 0, "keywords": [(bkw, cls)]})
    game._log(f"{game.db.shikigami[s.id].name} 的鼓舞转化为本次战斗加成"
              f"（+{power}力量/+{shield}护甲）")


@action("generate")
def generate(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
             card_type: str | None = None, count: int | dict = 1, zone: str = "hand",
             max_level: int | str | None = None, exclude_self: bool = False,
             card_id: int | None = None, subtype: str | None = None,
             level: int | str | None = None, position: str = "bottom") -> None:
    """随机生成符合谓词的卡牌并置入区域（targets 忽略；可重复，杀念/觉醒·一目连）。

    card_id 指定时直接生成该 id 的牌（可生成 token；黄金羽/金风流羽），绕开随机池。
    subtype：限定子类型（"随机获得一张妖琴师觉醒牌"= spell + awaken）。
    max_level="source"：卡牌等级 ≤ 来源式神当前等级（吾即正义"小于等于自身等级"）；
    exclude_self=True：排除来源卡牌同 id（"其他法术牌"）。
    level="shikigami"：卡牌等级 == shikigami 参数所指式神的当前等级（精确匹配；
    醉酒当歌"茨木童子当前等级的战斗牌"）——该式神未出战/未在场为空操作。
    shikigami="friendly_others"：逐各其他己方式神（出战队列中除来源外）各随机
    生成 1 张牌（万象之书"随机将其他己方式神的各一张牌置入手牌"；count 忽略）。
    count 支持动态值：{"memo": key} 读块内暂存（discard 的 discarded_count）；
    {"ext": key, "base": n} 读控制者 PlayerState.ext 计数 + base。
    生成置入手牌统一做持久修饰快照（_materialize——"本局游戏"类增强生成点生效）
    并经 move_card 的手牌上限路径（爆牌）。
    生成替换钩子（gen_replace 登记的 PlayerState.ext["gen_replace"]，觉醒·番茄④）：
    生成的牌是该式神非 to_type 牌时改为随机一张该式神的 to_type 牌（一切经本 op
    的生成路径单点生效）。
    """
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    if isinstance(count, dict):
        if count.get("memo") is not None:
            n = int((ctx.memo or {}).get(count["memo"], 0))
        elif count.get("ext") is not None:
            n = int(count.get("base", 0)) + int(p.ext.get(count["ext"], 0))
        else:
            n = int(count.get("base", 1))
    else:
        n = int(count)

    def _spawn(cid: int) -> None:
        hook = p.ext.get("gen_replace")
        if hook is not None:
            cd = game.db.cards[cid]
            if cd.shikigami == hook["shikigami"] and cd.card_type != hook["to_type"]:
                rep = [c.id for c in game.db.cards.values()
                       if not c.token and c.shikigami == hook["shikigami"]
                       and c.card_type == hook["to_type"]]
                if rep:
                    cid = game.rng.choice(rep)  # 生成替换：非战斗牌改为随机战斗牌
        inst = CardInstance(uid=game.state.next_uid, id=cid)
        game.state.next_uid += 1
        game.move_card(p, inst, zone)
        if zone == "deck" and position == "random":
            # 置入牌库 = 随机插入（同心协力 20200423 维护者定案：随机位置，不洗牌）
            p.deck.remove(inst)
            p.deck.insert(game.rng.randrange(len(p.deck) + 1), inst)
        game._materialize(p, inst, game.db.cards[cid])  # 生成点统一快照
        game._log(f"生成了【{game.db.cards[cid].name}】")

    if card_id is not None:
        for _ in range(n):
            _spawn(int(card_id))
        return
    if shikigami == "friendly_others":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("generate(shikigami=friendly_others) 需要来源式神")
        src_id = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
        for s in p.shikigami:
            if s.id == src_id or s.kind != "shikigami":
                continue
            pool = [c.id for c in game.db.cards.values()
                    if not c.token and c.shikigami == s.id
                    and (card_type is None or c.card_type == card_type)]
            if not pool:
                continue
            _spawn(game.rng.choice(pool))
        return
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("generate(shikigami=self) 需要来源式神")
        sid = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
    else:
        sid = int(shikigami)
    lv: int | None = None
    if max_level is not None:
        if max_level == "source":
            if ctx.source is None or ctx.source.shikigami is None:
                raise ValueError("generate(max_level=source) 需要来源式神")
            lv = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].level
        else:
            lv = int(max_level)
    lv_eq: int | None = None
    if level is not None:
        if level == "shikigami":
            idx = game._find_shikigami(p, sid)
            if idx is None or not p.shikigami[idx].in_play:
                return  # 所指式神未出战/未在场：空操作
            lv_eq = p.shikigami[idx].level
        else:
            lv_eq = int(level)
    pool = [c.id for c in game.db.cards.values()
            if not c.token and c.shikigami == sid
            and (card_type is None or c.card_type == card_type)
            and (subtype is None or c.subtype == subtype)
            and (lv is None or c.level <= lv)
            and (lv_eq is None or c.level == lv_eq)
            and not (exclude_self and ctx.card is not None and c.id == ctx.card.id)]
    if not pool:
        return
    for _ in range(n):
        _spawn(game.rng.choice(pool))


@action("gen_replace")
def gen_replace(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
                to_type: str = "combat") -> None:
    """牌手永久生成替换钩子（觉醒·番茄④；targets 忽略）：之后经 generate 生成
    该式神的非 to_type 牌时，改为随机一张该式神的 to_type 牌。

    登记于控制者 PlayerState.ext["gen_replace"]，generate 单点读取（一切生成路径
    生效）；重复登记后者覆盖前者。shikigami="self" 时取来源式神（变形物取其
    transform_owner 原式神 id——永久变形后"她的牌"仍指原式神的牌）。
    """
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("gen_replace(shikigami=self) 需要来源式神")
        s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        sid = s.transform_owner if s.transform_owner is not None else s.id
    else:
        sid = int(shikigami)
    p = game.state.players[ctx.controller]
    p.ext["gen_replace"] = {"shikigami": sid, "to_type": to_type}
    game._log(f"{p.name} 获得生成替换能力（{game.db.shikigami[sid].name}的非"
              f"{to_type}牌改为随机{to_type}牌）")


@action("replace_cards")
def replace_cards(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
                  zones: list[str] = ("hand", "deck"), exclude_type: str = "combat",
                  to_type: str = "combat") -> None:
    """一次性换牌（觉醒·番茄③；targets 忽略）：把控制者 zones 中该式神的所有
    非 exclude_type 牌各随机替换为一张她的 to_type 牌。

    原牌置入墓地；替换牌生成到原所在区域（生成点统一快照 _materialize），
    牌库有替换则洗一次牌库。shikigami="self" 同 gen_replace（变形物取原式神 id）。
    """
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("replace_cards(shikigami=self) 需要来源式神")
        s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        sid = s.transform_owner if s.transform_owner is not None else s.id
    else:
        sid = int(shikigami)
    pool = [c.id for c in game.db.cards.values()
            if not c.token and c.shikigami == sid and c.card_type == to_type]
    if not pool:
        return
    deck_touched = False
    for zone in zones:
        matching = [c for c in p.zones.get(zone, [])
                    if game.db.cards[c.id].shikigami == sid
                    and game.db.cards[c.id].card_type != exclude_type]
        for c in matching:
            game._log(f"{p.name} 的【{game.db.cards[c.id].name}】被替换")
            game.move_card(p, c, "graveyard")
            cid = game.rng.choice(pool)
            inst = CardInstance(uid=game.state.next_uid, id=cid)
            game.state.next_uid += 1
            game.move_card(p, inst, zone)
            game._materialize(p, inst, game.db.cards[cid])
            game._log(f"替换为【{game.db.cards[cid].name}】")
            deck_touched = deck_touched or zone == "deck"
    if deck_touched:
        game.rng.shuffle(p.deck)
        game._log(f"{p.name} 洗了牌库")


@action("transform_card")
def transform_card(game, ctx, *, targets: list[Ref], card_id: int, into: int,
                   count: int = 1) -> None:
    """手牌中至多 count 张指定数据 id 的牌原位变成另一张牌（千羽风之舞"将你手牌中
    一张'黄金羽'变成'金风流羽'"；targets 忽略）。

    原牌消失（不入墓地、不触发弃牌）；新牌占据原手牌位置（新 uid，经生成点统一
    快照 _materialize；原位替换不改变手牌数，不走手牌上限路径）。无匹配牌为空操作。
    """
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    hand = p.zones.get("hand", [])
    done = 0
    for idx, inst in enumerate(list(hand)):
        if done >= count:
            break
        if inst.id != int(card_id):
            continue
        new = CardInstance(uid=game.state.next_uid, id=int(into))
        game.state.next_uid += 1
        hand[idx] = new
        game._materialize(p, new, game.db.cards[int(into)])
        done += 1
        game._log(f"{p.name} 手牌中的【{game.db.cards[int(card_id)].name}】"
                  f"变成了【{game.db.cards[int(into)].name}】")


@action("search_deck")
def search_deck(game, ctx, *, targets: list[Ref], shikigami: int | str = "target",
                card_type: str | None = None, max_level: int | str | None = None,
                direct_play_power_ge: int | None = None,
                card_id: int | None = None) -> None:
    """从控制者牌库随机检索一张指定式神的牌置入手牌，然后洗牌库（花信风；targets 忽略）。

    shikigami="target"（缺省）：按卡牌选择目标（targets[0]）所指式神的数据 id 检索；
    "self"=来源式神；或给出数据 id。仅实际检索到卡牌才洗牌库（未命中不洗——
    维护者定案；检索类效果命中即洗）。
    card_type：限定卡牌主类型（森佑灵引 card_type=form）；max_level="target"：卡牌
    等级 ≤ 选择目标式神当前等级（"不高于该式神等级"）；card_id：按数据 id 精确
    检索（鸿运当头羁绊检索'这把算我赢'）。
    direct_play_power_ge：选择目标式神存活且力量 ≥ 该值时改为直接使用（森佑灵引
    "若该式神力量>=4且存活，改为直接使用"——不耗鬼火、play_from=deck、triggered=auto；
    目前仅支持形态牌直接结附给选择目标）。置入手牌/直接使用前按生成点统一做
    持久修饰快照（_materialize）。
    """
    p = game.state.players[ctx.controller]
    ref = targets[0] if targets else None
    if shikigami == "target":
        if ref is None or ref.shikigami is None:
            return  # 无有效目标：检索落空，不洗牌
        sid = game.state.players[ref.player].shikigami[ref.shikigami].id
    elif shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("search_deck(shikigami=self) 需要来源式神")
        sid = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
    else:
        sid = int(shikigami)
    lv: int | None = None
    if max_level is not None:
        if max_level == "target":
            if ref is None or ref.shikigami is None:
                return
            lv = game.state.players[ref.player].shikigami[ref.shikigami].level
        else:
            lv = int(max_level)
    pool = [c for c in p.deck
            if game.db.cards[c.id].shikigami == sid
            and (card_id is None or c.id == int(card_id))
            and (card_type is None or game.db.cards[c.id].card_type == card_type)
            and (lv is None or game.db.cards[c.id].level <= lv)]
    if not pool:
        return  # 未命中：不洗牌
    card = game.rng.choice(pool)
    cdef = game.db.cards[card.id]
    if direct_play_power_ge is not None and ref is not None and ref.shikigami is not None:
        ts = game.state.players[ref.player].shikigami[ref.shikigami]
        if ts.in_play and ts.eff_power >= int(direct_play_power_ge) and (
                cdef.play_condition is None or game._play_condition_met(p, cdef)):
            if cdef.card_type != "form":
                raise ValueError("search_deck 直接使用目前仅支持形态牌")
            game._remove_from_zone(p, card)
            game._materialize(p, card, cdef)  # 生成点统一快照（断罪 form_power_delta 等）
            game._log(f"{p.name} 直接使用了牌库中的【{cdef.name}】")
            game._play_form_card(p, ref.shikigami, card, cdef, ctx.controller, [])
            game._emit_card_played(ctx.controller, card.uid, cdef,
                                   play_from="deck", triggered="auto")
            return
    game.move_card(p, card, "hand")
    game._materialize(p, card, cdef)  # 生成点统一快照（置入手牌即获"本局游戏"类增强）
    game._log(f"从牌库检索了【{cdef.name}】")
    game.rng.shuffle(p.deck)
    game._log(f"{p.name} 洗了牌库")


@action("random_damage")
def random_damage(game, ctx, *, targets: list[Ref], amount: int = 0, pool: str,
                  count: int | dict = 1, piercing: bool | None = None,
                  sequential: bool = False, exclude_victim: bool = False,
                  amount_ctx: str | None = None,
                  amount_ext: str | None = None, amount_ext_source: str | None = None) -> None:
    """对 pool 中无放回随机 count 个目标各造成 amount 点伤害（单次伤害队列=并行结算）。

    count 支持 {"mod": key, "base": n}：base + ctx.card.mods[key]（风符·龙的实例计数）。
    目标数超出可选目标时按可选目标数截断。贯通规则同 damage 动作。
    sequential=True（狂风刃卷）：每次独立随机（有放回）、插入结算——逐次单独伤害队列，
    气绝事件按延时时机延后到本效果结束后统一生成（distribute_damage 同路径）。
    exclude_victim=True：目标池排除触发事件的 victim（出击！"随机对另一个敌方角色"——
    配 player_aura 的 on_damage 监听使用）。
    amount_ctx / amount_ext / amount_ext_source：数值扩展（契约 §3.4，见 _luck_amount）。
    """
    from core import targets as targets_mod
    amount = _luck_amount(game, ctx, amount, amount_ctx, amount_ext, amount_ext_source)
    if isinstance(count, dict):
        n = int(count.get("base", 1))
        if count.get("mod") and ctx.card is not None:
            n += int(ctx.card.mods.get(count["mod"], 0))
    else:
        n = int(count)
    refs = targets_mod.pool_refs(game, pool, ctx.controller)
    if exclude_victim:
        vic = (ctx.event or {}).get("victim")
        refs = [r for r in refs if r != vic]
    if not refs:
        return
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
    spell = game._spell_damage(ctx)
    from core.engine import _DamageEvent  # 避免模块顶层循环引用
    if sequential:
        deferred: list[tuple[Ref, Ref | None, str]] = []
        for _ in range(n):
            legal = [r for r in refs if r.shikigami is None
                     or game.state.players[r.player].shikigami[r.shikigami].health > 0]
            if not legal:
                break
            r = game.rng.choice(legal)  # 有放回：每次独立随机
            game._run_damage_queue(
                [_DamageEvent(source=ctx.source, victim=r, amount=amount, kind="effect",
                              piercing=pierce, spell=spell)],
                defer_defeats=deferred)
        for ref, source, reason in deferred:
            game.check_defeated(ref, source=source, reason=reason)
        return
    n = min(n, len(refs))
    chosen = game.rng.sample(refs, n)
    game._run_damage_queue([
        _DamageEvent(source=ctx.source, victim=r, amount=amount, kind="effect",
                     piercing=pierce, spell=spell)
        for r in chosen
    ])


@action("distribute_damage")
def distribute_damage(game, ctx, *, targets: list[Ref], amount: int = 0, pool: str,
                      piercing: bool | None = None, amount_ctx: str | None = None,
                      amount_ext: str | None = None, amount_ext_source: str | None = None) -> None:
    """造成总计 amount 点伤害，随机分配给 pool 中的目标。

    流程：确定目标池 → 重复 amount 次 {随机选取目标池中 1 名合法目标，对其造成 1 点伤害}。
    与 random_damage（随机选取 x 个目标、同一队列并行受伤）不同：每次重复的伤害事件
    单独结算（重复之间按即时时机插入）；气绝事件按延时时机延后到本效果结束后统一生成，
    但已因此效果生命 ≤ 0（标记气绝）的目标不再是后续重复的合法目标。贯通规则同 damage。
    amount_ctx / amount_ext / amount_ext_source：数值扩展（契约 §3.4，见 _luck_amount）。
    """
    from core import targets as targets_mod
    amount = _luck_amount(game, ctx, amount, amount_ctx, amount_ext, amount_ext_source)
    refs = targets_mod.pool_refs(game, pool, ctx.controller)
    if not refs:
        return
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
    spell = game._spell_damage(ctx)
    from core.engine import _DamageEvent  # 避免模块顶层循环引用
    deferred: list[tuple[Ref, Ref | None, str]] = []
    for _ in range(amount):
        legal = [r for r in refs if r.shikigami is None
                 or game.state.players[r.player].shikigami[r.shikigami].health > 0]
        if not legal:
            break
        r = game.rng.choice(legal)
        game._run_damage_queue(
            [_DamageEvent(source=ctx.source, victim=r, amount=1, kind="effect",
                          piercing=pierce, spell=spell)],
            defer_defeats=deferred)
    for ref, source, reason in deferred:
        game.check_defeated(ref, source=source, reason=reason)


@action("battle_immunity")
def battle_immunity(game, ctx, *, targets: list[Ref], nested: bool = False) -> None:
    """作用域战斗伤害免疫：免疫 kind ∈ (combat, counter) 的伤害（法术/能力等 effect 伤害不免疫）。

    作用域由授予效果指定：nested=False = 仅本张战斗牌发起的战斗；nested=True = 该战斗
    及其内的嵌套战斗。战斗牌流程会提取本步并绑定该次战斗上下文；作为普通动作执行时
    登记到当前战斗（无战斗上下文则不生效）。
    """
    if not game._battle_stack:
        return
    bid = game._battle_stack[-1]
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        s.immunities.append({"kind": "combat_damage", "battle": bid, "nested": nested})


@action("delay_grant")
def delay_grant(game, ctx, *, targets: list[Ref], when: str,
                condition: dict | None = None, steps: list | None = None,
                secret: bool = False, scope: str | None = None,
                bind: str = "source", uses: int = 1) -> None:
    """给来源式神登记一个延迟能力（会；targets 忽略）。

    when/condition/steps 描述延迟触发的效果块；打出时的选择目标（ctx.chosen）
    随条目存储，触发结算时作为效果目标。气绝时清除（变形离场保留——变形未实现）。
    uses 为剩余触发次数（缺省 1 = 一次性；剧毒之盾"本回合获得…"配 scope="turn"
    uses=99 表示回合内不限次）。
    scope="turn"："本回合"类（魔音扰心主动使用）——己方回合开始清除（未消耗时）。
    scope="play"："本次使用期间"类（黑羽之刃的消灭抽牌）——该次出牌结算结束时清除。
    secret=True 时选择目标对敌方保密（会：所选目标仅己方可见）——联机状态脱敏
    （server/room.py sanitize_state）会对敌方视角抹除 chosen；热坐/日志本就不回显目标。
    bind="chosen"：改登记到选择目标式神上（沧海之盾"使一个己方式神获得……当他造成
    战斗伤害时……"——延迟能力的持有者与条件 self 基准均为被选式神）。
    """
    if bind == "chosen":
        if not ctx.chosen or ctx.chosen[0].shikigami is None:
            raise ValueError("delay_grant(bind=chosen) 需要选择目标式神")
        holder_ref = ctx.chosen[0]
    else:
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("delay_grant 需要来源式神")
        holder_ref = ctx.source
    from db.schema import EffectBlock, Step
    block = EffectBlock(when=when, condition=condition,
                        steps=[Step.model_validate(st) for st in (steps or [])])
    s = game.state.players[holder_ref.player].shikigami[holder_ref.shikigami]
    s.delayed.append({
        "block": block,
        "chosen": ctx.chosen[0] if ctx.chosen else None,
        "uses": int(uses),
        "secret": secret,
        "scope": scope,
    })
    game._log(f"{game.db.shikigami[s.id].name} 获得了延迟能力")


@action("nullify_card_play")
def nullify_card_play(game, ctx, *, targets: list[Ref]) -> None:
    """无效化事件中的卡牌使用（魔音扰心；targets 忽略）。

    把 on_before_card_play payload 的可变 nullified 标记置位：该次使用跳过效果块、
    牌照常离手进墓地（费用/瞬发名额已付不退）。须挂在 on_before_card_play 时机的
    触发块（一次性延迟能力）或响应牌上。
    """
    marker = (ctx.event or {}).get("nullified")
    if isinstance(marker, dict):
        marker["nullified"] = True


@action("enter_combat")
def enter_combat(game, ctx, *, targets: list[Ref]) -> None:
    """把目标式神移入战斗区（不动如山进场；驻守者按规则退回）。

    尘缚之阵：若移入会替换被锁定的战斗区式神，该效果无效（不看发起者）；
    退回准备区方向的移动不受锁定限制（terminology.md「战斗区锁定」）。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        if not p.shikigami[ref.shikigami].in_play or p.combat_index == ref.shikigami:
            continue
        if p.combat_index is not None and game._combat_zone_locked(ref.player):
            game._log(f"{p.name} 的进入战斗区效果被尘缚之阵无效化")
            continue
        game._enter_combat(p, ref.shikigami)


@action("force_enter_combat")
def force_enter_combat(game, ctx, *, targets: list[Ref],
                       random_pick: bool = False,
                       if_combat_empty: bool = False) -> None:
    """强制目标进入其战斗区（鬼之手类"将敌方准备区式神移入战斗区"，targets 经
    enemy_bench 池选择）。

    移动语义与 enter_combat 相同（驻守者退回）；尘缚之阵锁定下（移入会替换被锁定的
    战斗区式神时）该效果静默无效，与 enter_combat 的锁定处理对齐。
    random_pick=True：从候选目标中随机取 1 名（随机不取对象，不吃帷幕）。
    if_combat_empty=True：目标所属玩家的战斗区非空时整体跳过（鬼之手空发）。
    """
    if not targets:
        return
    owner_pi = targets[0].player
    owner = game.state.players[owner_pi]
    if if_combat_empty and owner.combat_index is not None:
        return
    if random_pick:
        targets = [game.rng.choice(targets)]
    enter_combat(game, ctx, targets=targets)


@action("player_aura")
def player_aura(game, ctx, *, targets: list[Ref], when: str,
                condition: dict | None = None, steps: list | None = None,
                once_key: str | None = None, scope: str = "game") -> None:
    """给控制者牌手登记一个持久监听（targets 忽略；豪焰/鼓舞类附着于牌手的能力）。

    事件 when 触发且 condition 满足时结算 steps；登记于 `PlayerState.auras`——
    跨气绝保留、不限触发次数。scope="game"（默认）本局游戏有效；scope="turn"
    仅本回合（己方回合开始时随回合通道清除）。once_key：已登记同键监听时跳过
    （"四项均有则不会再赋予"类不可叠加）；不指定则可叠加。
    """
    from db.schema import EffectBlock, Step
    p = game.state.players[ctx.controller]
    if once_key is not None and any(a.get("once_key") == once_key for a in p.auras):
        return
    block = EffectBlock(when=when, condition=condition,
                        steps=[Step.model_validate(st) for st in (steps or [])])
    p.auras.append({"block": block, "once_key": once_key, "scope": scope})
    game._log(f"{p.name} 获得了牌手级能力（{'本回合' if scope == 'turn' else '本局游戏'}）")


@action("random_enhance")
def random_enhance(game, ctx, *, targets: list[Ref], card_id: int,
                   tiers: list[dict], max_count: int = 3) -> None:
    """手牌同名卡各实例随机强化一次（targets 忽略；罗生门之鬼）。

    "仅在手牌时可触发增强"：只作用于控制者手牌中的同 card_id 实例。每实例
    独立计数——本次强化序号 = len(mods["enhance_got"]) + 1，已达 max_count
    次的实例跳过；候选 = tiers 中 min（缺省 1）≤ 序号 ≤ max（缺省 max_count）
    且 key 未获得的项，rng.choice 一项并记录 key（"不会出现已有的强化"）。
    强化写入实例 mods：keywords_add 并入集合排序、form_power_delta /
    form_health_delta 累加、其余键直写（playable_when_defeated /
    revive_on_play 等开关）。
    """
    p = game.state.players[ctx.controller]
    for c in p.hand:
        if c.id != card_id:
            continue
        got = c.mods.setdefault("enhance_got", [])
        n = len(got) + 1
        if n > max_count:
            continue
        pool = [t for t in tiers
                if int(t.get("min", 1)) <= n <= int(t.get("max", max_count))
                and t["key"] not in got]
        if not pool:
            continue
        t = game.rng.choice(pool)
        got.append(t["key"])
        if t.get("keywords_add"):
            merged = set(c.mods.get("keywords_add", [])) | set(t["keywords_add"])
            c.mods["keywords_add"] = sorted(merged)
        for k in ("form_power_delta", "form_health_delta"):
            if t.get(k):
                c.mods[k] = c.mods.get(k, 0) + int(t[k])
        for k, v in t.items():
            if k not in ("key", "min", "max", "keywords_add", "form_power_delta",
                         "form_health_delta"):
                c.mods[k] = v
        game._log(f"【{game.db.cards[c.id].name}】获得了强化（{t['key']}）")


@action("random_aura")
def random_aura(game, ctx, *, targets: list[Ref], options: list[dict],
                once_prefix: str = "aura") -> None:
    """从 options 中随机赋予一项牌手级监听（targets 忽略；豪焰"随机获得一项"）。

    各项以 `{once_prefix}_{option["key"]}` 为 once_key——已在 `p.auras` 登记过的
    项剔出候选，全项都有则空操作；rng.choice 后转调 player_aura（option 须含
    key/when，可含 condition/steps/scope）。
    """
    p = game.state.players[ctx.controller]
    held = {a.get("once_key") for a in p.auras}
    pool = [o for o in options
            if f"{once_prefix}_{o['key']}" not in held]
    if not pool:
        return
    o = game.rng.choice(pool)
    player_aura(game, ctx, targets=targets, when=o["when"],
                condition=o.get("condition"), steps=o.get("steps"),
                once_key=f"{once_prefix}_{o['key']}", scope=o.get("scope", "game"))


@action("followup_attack")
def followup_attack(game, ctx, *, targets: list[Ref]) -> None:
    """登记一次战斗结束后的追加攻击（targets 忽略；地狱之手类临时能力）。

    追加攻击在整场战斗结束、战斗牌加成随终止点核销后依次结算（一场战斗中可多次登记，
    链式排队），不享受原战斗牌的力量/关键字加成；来源式神届时在场才发起，目标为生命
    最低的敌方式神（平手随机，帷幕不可选；无合法目标则改为无目标战斗）。
    须挂在战斗绑定的触发块（temp_grants 等）上——触发事件须带 battle payload
    （气绝后等延时能力在战斗弹栈后结算，故按事件中的战斗 id 登记而非当前战斗栈）。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        return
    bid = (ctx.event or {}).get("battle")
    if bid is None or bid not in game._battle_followups:
        return
    game._battle_followups[bid].append(ctx.source)
    game._log(f"{game.db.shikigami[game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id].name} 登记了战斗结束后的追加攻击")


@action("cap_damage")
def cap_damage(game, ctx, *, targets: list[Ref], to: str | int = "shield") -> None:
    """伤害上限（森罗之阵/雪融之时；targets 忽略）：改写事件中可变伤害对象的数值。

    to="shield"：若受伤式神具有护甲，伤害值至多为其当前护甲值（护甲 0 不生效）。
    to=<整数>：伤害值至多为该定值（雪融之时"每次至多只会受到3点伤害"——单次伤害
    事件面板值封顶，护甲吸收照常在其后结算）。
    须挂在伤害时点批次（on_damage_start 等 payload 含 damage 的事件）上。
    """
    ev = (ctx.event or {}).get("damage")
    victim = (ctx.event or {}).get("victim")
    if ev is None or not isinstance(victim, Ref) or victim.shikigami is None:
        return
    if to == "shield":
        s = game.state.players[victim.player].shikigami[victim.shikigami]
        if s.shield > 0 and ev.amount > s.shield:
            game._log(f"{game.db.shikigami[s.id].name} 的伤害上限生效（{ev.amount} → {s.shield}）")
            ev.amount = s.shield
    elif isinstance(to, int):
        s = game.state.players[victim.player].shikigami[victim.shikigami]
        if ev.amount > to:
            game._log(f"{game.db.shikigami[s.id].name} 的伤害上限生效（{ev.amount} → {to}）")
            ev.amount = to
    else:
        raise ValueError(f"未知 cap_damage 上限类型: {to}")


@action("countdown_delta")
def countdown_delta(game, ctx, *, targets: list[Ref], amount: int = 0,
                    shikigami: int | None = None, revive: bool = False,
                    reset: bool = False) -> None:
    """目标式神倒计时增减 amount（±）。

    无倒计时能力或倒计时为 0（归零结算中）时修正为 -0（空操作，rules.md ch12
    增减流程 1）；减少后不大于 0 时走归零流程（_countdown_zero，与回合开始批次共用）。
    倒计时增减事件的独立时机批次暂不拆，首张监听卡出现时再引入。

    reset=True（疯魔琴心"重置所有敌方角色的倒计时"）：倒计时复原为
    countdown_initial，不触发归零流程；无倒计时能力者空操作。与 revive 互斥，
    reset 优先判定。

    shikigami：按数据 id 指定控制者的式神（targets 忽略；协战羁绊"鸩/以津真天
    倒计时-2"——未出战为空操作）；revive=True：改为作用于气绝倒计时（减到 ≤0
    立即复活）——targets 非空时只作用于这些目标（可跨阵营，豪焰"使该式神气绝
    倒计时+1"），targets 为空时扫描控制者全队已气绝式神（幻音绝弦先例）。
    """
    if shikigami is not None:
        pi = ctx.controller
        idx = game._find_shikigami(game.state.players[pi], int(shikigami))
        targets = [Ref(player=pi, shikigami=idx)] if idx is not None else []
    if reset:
        for ref in targets:
            if ref.shikigami is None:
                continue
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if s.countdown_block is None or s.countdown_initial is None:
                continue  # 无倒计时能力：空操作
            s.countdown = s.countdown_initial
            game._log(f"{game.db.shikigami[s.id].name} 的倒计时重置为 {s.countdown_initial}")
        return
    if revive:
        if targets:
            refs = targets
        else:
            p = game.state.players[ctx.controller]
            refs = [Ref(player=ctx.controller, shikigami=i)
                    for i in range(len(p.shikigami))]
        for ref in refs:
            if ref.shikigami is None:
                continue
            pl = game.state.players[ref.player]
            s = pl.shikigami[ref.shikigami]
            if not s.defeated or s.despawned or s.level < 1:
                continue
            s.revive_countdown += amount
            if s.revive_countdown <= 0:
                game._revive(pl, ref.player, ref.shikigami)
        return
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if s.countdown is None or s.countdown <= 0 or s.countdown_block is None:
            continue  # 修正为 -0：无倒计时能力 / 倒计时为 0（归零结算中的自身增减）
        s.countdown += amount
        if s.countdown <= 0:
            game._countdown_zero(ref.player, ref.shikigami)


@action("set_countdown")
def set_countdown(game, ctx, *, targets: list[Ref], initial: int,
                  steps: list | None = None, once: bool = False,
                  record: bool = False) -> None:
    """为目标式神注册新的倒计时能力（替换当前倒计时能力；大天狗记录法术、灵矢类效果）。

    - initial/steps/once：倒计时三要素（初值 / 归零执行的效果步骤 / 一次型生效后移除）；
    - record=True：把触发事件所用卡牌的数据 id 记入目标式神 ext["recorded_card"]
      （大天狗"记录使用的法术"，随气绝丢失；on_card_played 事件按 uid 回查）；
    - 倒计时来源 id = 目标式神 id（countdown_history 记账按"基础=式神 id"）。
    """
    from db.schema import EffectBlock, Step
    block = EffectBlock(steps=[
        st if isinstance(st, Step) else Step.model_validate(st) for st in (steps or [])])
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        s = p.shikigami[ref.shikigami]
        if record:
            uid = (ctx.event or {}).get("uid")
            ev_player = (ctx.event or {}).get("player")
            if uid is not None and ev_player is not None:
                inst = next((c for z in game.state.players[ev_player].zones.values()
                             for c in z if c.uid == uid), None)
                if inst is not None:
                    s.ext["recorded_card"] = inst.id
        game._register_countdown(s, initial=initial, block=block, once=once, source=s.id)
        game._log(f"{game.db.shikigami[s.id].name} 获得了倒计时 {initial} 的能力")


@action("replay_countdown")
def replay_countdown(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
                     skip_forms: bool = False) -> None:
    """按本局 countdown_history 的首次出现顺序，依次执行来源属于目标式神的倒计时
    能力块（每种至多一次；targets 忽略；大合奏"本局游戏妖琴师的基础能力每生效过一种，
    此牌便具有对应效果"——维护者答复：按 4 种基础/觉醒倒计时能力的生效顺序依次执行）。

    来源归属：id == 式神 id（基础）或卡牌 shikigami == 式神 id（觉醒牌/形态牌）；
    skip_forms=True 时形态牌来源跳过（维护者答复(8)：大合奏只计入基础/觉醒能力；
    风韵雅乐的一目连倒计时皆来自形态，不过滤）；找不回对应块（_countdown_block_for）
    的历史条目跳过。重放为卡牌效果（非能力来源）。
    """
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("replay_countdown(shikigami=self) 需要来源式神")
        sid = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
    else:
        sid = int(shikigami)
    p = game.state.players[ctx.controller]
    seen: set[int] = set()
    for src in p.ext.get("countdown_history", []):
        if src in seen:
            continue  # 每种至多一次（按首次出现顺序）
        src_card = game.db.cards.get(src)
        if skip_forms and src_card is not None and src_card.card_type == "form":
            continue  # 形态来源不计入（答复(8)，大合奏用）
        if src != sid and not (src_card is not None and src_card.shikigami == sid):
            continue  # 非目标式神的倒计时来源（含其召唤物/其他式神）
        block = game._countdown_block_for(src)
        if block is None or not block.steps:
            continue
        seen.add(src)
        cname = game.db.cards[ctx.card.id].name if ctx.card is not None else "效果"
        game._log(f"【{cname}】重放了{game.db.shikigami[sid].name}的倒计时效果（来源 {src}）")
        game._resolve_block(block, ExecContext(
            controller=ctx.controller, source=ctx.source, card=ctx.card))


@action("recast_recorded")
def recast_recorded(game, ctx, *, targets: list[Ref]) -> None:
    """凭空生成来源式神记录的卡牌的同名牌并免费自动使用（大天狗倒计时；targets 忽略）。

    不消耗鬼火、不视作从手牌使用、无主动目标（当前大天狗非觉醒法术均无主动选择目标）；
    记录存于来源式神 ext["recorded_card"]（由 set_countdown(record=True) 写入，气绝丢失）。
    无记录时为空操作。使用照常发出 on_card_played（可再次触发记录类能力）。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("recast_recorded 需要来源式神")
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    cid = s.ext.get("recorded_card")
    if cid is None:
        return
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    cdef = game.db.cards[cid]
    if not game._play_condition_met(p, cdef):
        return  # [条件] 使用前提：自动使用同检（福满乾坤）
    inst = CardInstance(uid=game.state.next_uid, id=cid)  # 凭空生成，不进入任何区域
    game.state.next_uid += 1
    game._log(f"{game.db.shikigami[s.id].name} 的倒计时自动使用了【{cdef.name}】")
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, inst, None), ExecContext(
            controller=ctx.controller, source=ctx.source, card=inst, is_ability=True))
    finally:
        affected = game._affected_stack.pop()["refs"]
    game._clear_play_delayed(s)  # "本次使用期间"延迟能力的窗口随自动使用结束（黑羽之刃）
    game._emit_card_played(ctx.controller, inst.uid, cdef, affected,
                           play_from="void", triggered="auto")


@action("auto_use")
def auto_use(game, ctx, *, targets: list[Ref], card_id: int,
             inherit_target: bool = False, from_hand: bool = False) -> None:
    """凭空生成指定卡牌并免费自动使用（流霰"对目标使用一张'雪球'"；targets 忽略）。

    不耗鬼火、不视作从手牌使用、用后进墓地、play_from=void、triggered=auto，
    照常 emit on_card_played（recast_recorded 同管线）。inherit_target=True：
    不另选目标，以本效果的卡牌选择目标（ctx.chosen）作为其使用目标（目标继承
    流霰目标，无视该牌自身目标限制）。目前仅支持法术牌（效果块结算）；
    [条件] 使用前提同检。

    from_hand=True（流霰 20191212"自动对其使用手牌中所有'雪球'"）：改为从手牌
    移出全部同名牌逐张免费使用——不耗鬼火/不占瞬发位、用后进墓地、
    play_from="hand"（计入"从手牌使用"记账 snowball_used_game，定案(1a)）、
    逐张独立结算；手牌无同名牌时空操作（定案(1b)）。
    """
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    cdef = game.db.cards[int(card_id)]
    if cdef.card_type != "spell":
        raise ValueError("auto_use 目前仅支持法术牌")
    if not game._play_condition_met(p, cdef):
        return  # [条件] 使用前提：自动使用同检
    chosen = list(ctx.chosen or []) if inherit_target else []
    if from_hand:
        for inst in [c for c in p.hand if c.id == int(card_id)]:
            p.hand.remove(inst)
            game._log(f"自动使用了手牌的【{cdef.name}】")
            game._affected_stack.append({"controller": ctx.controller, "refs": []})
            try:
                game._resolve_block(game._played_block(p, cdef, inst, None),
                                    ExecContext(controller=ctx.controller,
                                                source=ctx.source, card=inst,
                                                chosen=chosen))
            finally:
                affected = game._affected_stack.pop()["refs"]
            if ctx.source is not None and ctx.source.shikigami is not None:
                game._clear_play_delayed(
                    game.state.players[ctx.source.player].shikigami[ctx.source.shikigami])
            game.move_card(p, inst, "graveyard")
            game._account_card_played(p, cdef)  # 从手牌使用：计入 tags 记账
            game._emit_card_played(ctx.controller, inst.uid, cdef, affected,
                                   play_from="hand", triggered="auto", chosen=chosen)
        return
    inst = CardInstance(uid=game.state.next_uid, id=int(card_id))  # 凭空生成，不进任何区域
    game.state.next_uid += 1
    game._materialize(p, inst, cdef)  # 生成点统一快照
    game._log(f"凭空自动使用了【{cdef.name}】")
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, inst, None), ExecContext(
            controller=ctx.controller, source=ctx.source, card=inst, chosen=chosen))
    finally:
        affected = game._affected_stack.pop()["refs"]
    if ctx.source is not None and ctx.source.shikigami is not None:
        game._clear_play_delayed(
            game.state.players[ctx.source.player].shikigami[ctx.source.shikigami])
    game.move_card(p, inst, "graveyard")
    game._emit_card_played(ctx.controller, inst.uid, cdef, affected,
                           play_from="void", triggered="auto", chosen=chosen)


@action("spell_echo")
def spell_echo(game, ctx, *, targets: list[Ref], sequence: list[int],
               once_key: str | None = None) -> None:
    """法术回响序列（涅槃业火底层；targets 忽略）：给来源式神登记"本回合"回响能力。

    本回合中，当持有者以外的式神（含敌方）从手牌使用法术牌时（同 id 法术每回合
    至多触发一次），持有者依次凭空免费使用 sequence 中的下一张卡（每张至多一次）：
    不耗鬼火、凭空生成（用后进墓地）、play_from=void、triggered=auto，照常 emit
    on_card_played；有目标的自动使用在合法目标中随机选择。触发结算见
    spell_echo_recast（引擎在 _collect_abilities 中对 ext["spell_echo"] 设门）。
    己方回合开始清除（与 delay_grant scope="turn" 同步）。once_key：已登记同键
    回响时跳过（"不可叠加"）。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("spell_echo 需要来源式神")
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    if once_key is not None and s.ext.get("spell_echo", {}).get("once_key") == once_key:
        return  # 不可叠加：已登记同键回响
    s.ext["spell_echo"] = {
        "sequence": [int(c) for c in sequence], "cursor": 0,
        "triggered": [], "once_key": once_key,
    }
    game._log(f"{game.db.shikigami[s.id].name} 获得了法术回响（本回合）")


def _auto_cast_copy(game, controller: int, cdef, source: Ref | None, *,
                    inherit_chosen: list[Ref] | None = None,
                    emit_extra: dict | None = None) -> bool:
    """凭空生成 cdef 的复制并以基础方式自动结算（不耗鬼火/瞬发/替代方式），用后入墓地、
    发 on_card_played（play_from="void"，triggered="auto"）。

    choose 目标：inherit_chosen 仍在合法目标集内则沿用，否则合法目标中随机重选
    （无合法目标则不选）。play_condition 不满足时拒绝结算并返回 False。
    spell_echo_recast / mirror_spell / use_card_copy（法术）共用此管线。
    """
    from core import targets as targets_mod
    from core.model import CardInstance
    p = game.state.players[controller]
    if cdef.play_condition and not game._play_condition_met(p, cdef):  # 投影校验，拒绝不结算
        return False
    inst = CardInstance(uid=game.state.next_uid, id=cdef.id)  # 凭空生成，不进入任何区
    game.state.next_uid += 1
    chosen: list[Ref] = []
    if cdef.target.kind == "choose":
        pool = targets_mod.spec_pool_refs(game, cdef.target, controller, targeted=True)
        inherited = [r for r in (inherit_chosen or []) if r in pool]
        if inherited:
            chosen = inherited[:1]
        elif pool:
            chosen = [game.rng.choice(pool)]  # 自动使用：合法目标中随机选
    game._affected_stack.append({"controller": controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, inst, None), ExecContext(
            controller=controller, source=source, card=inst,
            chosen=chosen, is_ability=True))
    finally:
        affected = game._affected_stack.pop()["refs"]
    game.move_card(p, inst, "graveyard")  # 凭空生成的幻象牌用后入墓地
    game._emit_card_played(controller, inst.uid, cdef, affected,
                           play_from="void", triggered="auto", chosen=chosen,
                           extra=emit_extra)
    return True


@action("mirror_spell")
def mirror_spell(game, ctx, *, targets: list[Ref]) -> None:
    """复制施法（烟烟罗的分身"会复制她使用的法术牌"）：on_card_played 时机，
    凭空复制事件中的牌并自动使用一次（基础方式）。

    主动/响应/自动使用均触发（维护者定案：并非仅主动使用）——复制自身发出的事件
    带 mirror_copy 标记，不再触发复制（防递归）；觉醒牌排除由数据侧条件
    （subtype_not: awaken）表达。choose 目标沿用原选（仍合法）否则随机重选。
    """
    event = ctx.event or {}
    if event.get("name") != "on_card_played" or event.get("mirror_copy"):
        return
    if ctx.source is None or ctx.source.shikigami is None:
        return
    played = game._card_by_uid(event.get("uid"))
    if played is None:
        return
    cdef = game.db.cards[played.id]
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    game._log(f"{game.db.shikigami[s.id].name} 复制并自动使用了「{cdef.name}」")
    _auto_cast_copy(game, ctx.controller, cdef, ctx.source,
                    inherit_chosen=event.get("chosen"),
                    emit_extra={"mirror_copy": True})


@action("use_card_copy")
def use_card_copy(game, ctx, *, targets: list[Ref], card_id: int) -> None:
    """额外使用指定牌的复制（爆能"{额外使用'三太郎之斧'}"类）：凭空生成并自动使用，
    不耗鬼火/瞬发/出击次数；用后入墓地并发 on_card_played（play_from="void"，
    triggered="auto"）。链式"再额外使用"= 数据侧并列多个 step。

    法术牌 = 基础方式效果结算（_auto_cast_copy）；战斗牌 = 基础方式战斗结算
    （来源式神须在场，合法性以 _resolve_combat_card 自带检查为准）。
    """
    cdef = game.db.cards[card_id]
    if cdef.card_type != "combat":
        _auto_cast_copy(game, ctx.controller, cdef, ctx.source)
        return
    if ctx.source is None or ctx.source.shikigami is None:
        return
    p = game.state.players[ctx.controller]
    si = ctx.source.shikigami
    if not p.shikigami[si].in_play:
        return  # 来源式神不在场无法使用战斗牌复制
    from core.model import CardInstance
    inst = CardInstance(uid=game.state.next_uid, id=card_id)  # 凭空生成，不进入任何区
    game.state.next_uid += 1
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_combat_card(p, si, inst, cdef, None, [])
    finally:
        affected = game._affected_stack.pop()["refs"]
    game.move_card(p, inst, "graveyard")
    game._emit_card_played(ctx.controller, inst.uid, cdef, affected,
                           play_from="void", triggered="auto", chosen=[])


@action("spell_echo_recast")
def spell_echo_recast(game, ctx, *, targets: list[Ref]) -> None:
    """法术回响的自动使用（内部步，由引擎收集门触发；targets 忽略）。

    复查（收集到结算间局面可能已变）：同 id 法术每回合至多触发一次、序列游标未走完。
    凭空生成序列下一张并免费自动使用：不耗鬼火、用后进墓地、play_from=void、
    triggered=auto；有 choose 目标时在合法目标中随机选择。照常 emit on_card_played
    （会再次触发持有者"使用法术牌时"类能力）。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        return
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    echo = s.ext.get("spell_echo")
    if echo is None:
        return
    sid = (ctx.event or {}).get("shikigami")
    if sid in echo["triggered"] or echo["cursor"] >= len(echo["sequence"]):
        return
    echo["triggered"].append(sid)
    cid = echo["sequence"][echo["cursor"]]
    echo["cursor"] += 1
    p = game.state.players[ctx.controller]
    cdef = game.db.cards[cid]
    if cdef.play_condition and not game._play_condition_met(p, cdef):  # 投影校验过不了就跳过
        return
    game._log(f"{game.db.shikigami[s.id].name} 的法术回响自动使用了「{cdef.name}」")
    if _auto_cast_copy(game, ctx.controller, cdef, ctx.source):
        game._clear_play_delayed(s)  # "本次使用期间"延迟能力的窗口随自动使用结束


@action("cancel_attack")
def cancel_attack(game, ctx, *, targets: list[Ref]) -> None:
    """取消本次攻击（鸦羽疾走"自动使用并取消本次攻击"）。

    响应 on_before_assault 时置事件取消旗标；战斗流程在响应结算后检查并终止战斗。
    已支付的出击次数/鬼火不退还。非该时机的使用静默跳过。
    """
    marker = (ctx.event or {}).get("cancel")
    if isinstance(marker, dict):
        marker["cancelled"] = True
        game._log("本次攻击被取消")


@action("attack_replace")
def attack_replace(game, ctx, *, targets: list[Ref]) -> None:
    """攻击替换（烬染不夜"攻击时改为对两个随机敌方角色造成等同于自身力量与战力
    之和的伤害"）。

    响应 on_before_assault（condition: {attacker_shikigami: self}）时置事件替换旗标；
    战斗流程以效果伤害替换先攻/交战阶段（无交战、不受反击，on_after_assault 照常发出）。
    """
    marker = (ctx.event or {}).get("attack_replace")
    if isinstance(marker, dict):
        marker["active"] = True


@action("battle_retarget")
def battle_retarget(game, ctx, *, targets: list[Ref]) -> None:
    """交战目标改换（声东击西"本次的交战目标改为另一个敌方角色"）。

    目标角色本次战斗中的交战伤害（攻击/反击）改为打向另一个随机敌方角色
    （排除原交战目标；无另一个敌方角色时该次攻击落空）。仅当前战斗中登记有效。
    """
    if not game._battle_stack:
        return
    bid = game._battle_stack[-1]
    for ref in targets:
        if ref.shikigami is None:
            continue
        game._battle_retarget.setdefault(bid, []).append(ref)


@action("fragile_echo")
def fragile_echo(game, ctx, *, targets: list[Ref]) -> None:
    """蚀刃毒羽（维护者答复(2)）："攻击时"记录目标当前破甲量，登记一次性
    "本次战斗结束后赋予等量破甲"（引擎 _battle_echo，战斗中止则丢弃）。

    无破甲（量 ≤ 0）/ 不在战斗中：空操作（条件 {victim_has_fragile} 已在块级过滤）。
    """
    if not game._battle_stack:
        return
    bid = game._battle_stack[-1]
    for ref in targets:
        p = game.state.players[ref.player]
        holder = p.shikigami[ref.shikigami] if ref.shikigami is not None else p
        if holder.shield < 0:
            game._battle_echo.setdefault(bid, []).append((ref, -holder.shield))
            game._log(f"蚀刃毒羽记录了 {-holder.shield} 点破甲（战斗结束后回赋）")


@action("reapply_attack_buff_power")
def reapply_attack_buff_power(game, ctx, *, targets: list[Ref]) -> None:
    """灵矢贯虹"本次攻击获得当前自身法术牌强化效果的力量加成"（维护者答复(3)）：
    把目标当前 attack_buffs 挂账（起弓/离/无我）的力量部分合计，作为一条新的
    攻击后到期强化再次临时授予——仅力量，关键字部分不重复；无挂账为空操作。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        total = sum(e.get("power", 0) for e in s.attack_buffs)
        if total:
            s.temp_power += total
            game._record_max_power(s)
            s.attack_buffs.append({"power": total, "keywords": []})
            game._log(f"{game.db.shikigami[s.id].name} 再次获得法术强化的 {total} 力量加成")


@action("trigger_form_enter")
def trigger_form_enter(game, ctx, *, targets: list[Ref],
                       shikigami: int | str = "self") -> None:
    """触发控制者指定式神当前形态的进场时效果块（再执行一次 form 的 effects）——
    灵矢贯虹羁绊"攻击前触发萤草当前形态进场效果"；未结附形态为空操作。targets 忽略。
    """
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("trigger_form_enter(shikigami=self) 需要来源式神")
        si: int | None = ctx.source.shikigami
    else:
        p0 = game.state.players[ctx.controller]
        si = next((i for i, s in enumerate(p0.shikigami) if s.id == int(shikigami)), None)
    if si is None:
        return
    p = game.state.players[ctx.controller]
    s = p.shikigami[si]
    if s.form is None:
        return  # 未结附形态：空操作
    cdef = game.db.cards[s.form.id]
    if cdef.effects.steps and cdef.effects.when == "on_play":
        game._log(f"触发了{game.db.shikigami[s.id].name}当前形态【{cdef.name}】的进场效果")
        game._resolve_block(cdef.effects, ExecContext(
            controller=ctx.controller,
            source=Ref(player=ctx.controller, shikigami=si), card=s.form))


@action("retreat")
def retreat(game, ctx, *, targets: list[Ref]) -> None:
    """目标式神移回准备区（与 enter_combat 对称；风神一扇组合用）。

    仅对战斗区式神有效（准备区式神为空操作）；召唤物无准备区可归，退回即离场（非气绝）。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        if p.combat_index == ref.shikigami:
            game._retreat(p, ref.shikigami)


@action("discard")
def discard(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
            count: int | None = None, card_id: int | None = None) -> None:
    """弃掉控制者手牌中符合谓词的牌（移入墓地；targets 忽略）。

    shikigami="self" 弃来源式神所属的牌（射怪鸟事 = discard + draw 两步组合）；
    shikigami="all" 弃全部手牌；count 限制弃牌张数（缺省弃全部符合者）；
    card_id 指定时按数据 id 精确弃牌（百闻一得"弃掉一张'明灯'"，优先于 shikigami）。
    结算后把实际弃牌数写入块内暂存 ctx.memo["discarded_count"]（供后续 step 的
    {"memo": key} 动态数值引用，如 draw"弃多少抽多少"）。
    """
    p = game.state.players[ctx.controller]
    if card_id is not None:
        pool = [c for c in p.hand if c.id == int(card_id)]
    elif shikigami == "all":
        pool = list(p.hand)
    else:
        if shikigami == "self":
            if ctx.source is None or ctx.source.shikigami is None:
                raise ValueError("discard(shikigami=self) 需要来源式神")
            sid = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
        else:
            sid = int(shikigami)
        pool = [c for c in p.hand if game.db.cards[c.id].shikigami == sid]
    if count is not None:
        pool = pool[:count]
    for c in pool:
        game._log(f"{p.name} 弃掉了【{game.db.cards[c.id].name}】")
        game.move_card(p, c, "graveyard")
    if ctx.memo is not None:
        ctx.memo["discarded_count"] = len(pool)


@action("grant_immunity")
def grant_immunity(game, ctx, *, targets: list[Ref], scope: str = "turn",
                   kind: str = "combat_damage", from_side: str | None = None,
                   unique: bool = False) -> None:
    """授予目标式神/牌手伤害免疫（不可饶恕"本回合用过黄金羽则免疫战斗伤害"；觉醒·山童
    "免疫敌方非战斗伤害"；舍生"本回合你免疫所有伤害"——目标为牌手）。

    kind="combat_damage"（缺省）：免疫 kind ∈ (combat, counter) 的战斗伤害；
    kind="effect"：免疫非战斗伤害（法术/能力等），from_side="enemy" 限定伤害来源
    属于敌方（无来源/己方来源不免疫）；kind="all"：免疫全部伤害（牌手目标=舍生；
    式神目标=桃红簇簇"免疫该伤害"）；kind="fragile_source"：免疫当前持有破甲的
    敌方式神造成的伤害（霸主；来源须为式神，牌手来源不免疫），伤害类别不限。
    scope="turn"：免疫到当前回合结束——以回合号记账（{"turn": 当前回合}），
    按回合号比对，跨回合自然过期，无需清理；scope="perm"：无过期键，
    持续在场期间有效，随气绝清除（immunities 气绝清空，复活需重新授予）；
    scope="once"：消耗式，命中任意一类伤害即免疫一次并移除（桃红簇簇）；
    scope="form"：形态作用域——条目带 form 标记，随形态离场经 _destroy_form 清除
    （霸主为形态牌；气绝清空 immunities 的既有通道同样生效）。
    unique=True：目标已持有同等免疫条目时不再重复授予（维护者答复(3)：不可饶恕
    "若不具有该能力则获得"——回合内多次使用黄金羽只授予一次）。
    """
    if scope not in ("turn", "perm", "once", "form"):
        raise ValueError(f"未知 grant_immunity 作用域: {scope}")
    if kind not in ("combat_damage", "effect", "all", "fragile_source"):
        raise ValueError(f"未知 grant_immunity 免疫类别: {kind}")
    if from_side not in (None, "enemy"):
        raise ValueError(f"未知 grant_immunity 来源限定: {from_side}")
    for ref in targets:
        entry: dict = {"kind": kind}
        if from_side is not None:
            entry["from"] = from_side
        if scope == "turn":
            entry["turn"] = game.state.turn
        if scope == "once":
            entry["once"] = True  # 消耗式免疫：命中即移除（_combat_immune/_effect_immune）
        if scope == "form":
            entry["form"] = True  # 形态作用域：形态离场经 _destroy_form 清除（霸主）
        if ref.shikigami is None:
            # 牌手级免疫（舍生）：存 PlayerState.immunities，伤害管线按回合号过期
            pl = game.state.players[ref.player]
            pl.immunities.append(entry)
            game._log(f"{pl.name} 免疫所有伤害（本回合）")
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if s.in_play:
            if unique and any(e.get("kind") == kind and e.get("from") == from_side
                              and (scope == "perm" or e.get("turn") == game.state.turn)
                              for e in s.immunities):
                continue
            s.immunities.append(entry)
            label = {"combat_damage": "战斗伤害", "effect": "非战斗伤害", "all": "所有伤害",
                     "fragile_source": "破甲式神的伤害"}[kind]
            scope_label = {"turn": "本回合", "perm": "持续", "once": "下一次",
                           "form": "形态在场"}[scope]
            game._log(f"{game.db.shikigami[s.id].name} 免疫{label}（{scope_label}）")


@action("gain_orb")
def gain_orb(game, ctx, *, targets: list[Ref], amount: int = 1,
             side: str | None = None) -> None:
    """获得 amount 点鬼火（镇魂歌；targets 忽略）；emit on_orb_changed。
    side="self"/"opponent"：改由指定方获得（福满乾坤依次对双方）；缺省控制者。"""
    pi = ctx.controller if side in (None, "self") else 1 - ctx.controller
    p = game.state.players[pi]
    old = p.orb
    p.orb += amount
    if game.config.orb_cap is not None:
        p.orb = min(p.orb, game.config.orb_cap)
    if p.orb != old:
        game.emit("on_orb_changed", player=pi, old=old, new=p.orb, reason="gain_orb")


@action("bump_ext")
def bump_ext(game, ctx, *, targets: list[Ref], key: str, amount: int = 1) -> None:
    """目标式神/牌手的 ext 计数累加（鸩 x = 基础+觉醒倒计时生效合计：作为倒计时块的
    一个 step 表达"每触发一次 +1"；ext 不随气绝清除，跨气绝保留）。"""
    for ref in targets:
        pl = game.state.players[ref.player]
        holder = pl.shikigami[ref.shikigami] if ref.shikigami is not None else pl
        holder.ext[key] = holder.ext.get(key, 0) + amount


@action("turn_mark")
def turn_mark(game, ctx, *, targets: list[Ref], key: str) -> None:
    """给控制者打上"每回合合计一次"标记（targets 忽略；寂寥心象）。

    标记存于 `PlayerState.ext["turn_marks"]`，任一回合开始（双方）清除；
    能力触发条件以 {turn_mark_not: key} 求值（条件迷你语言）。
    """
    p = game.state.players[ctx.controller]
    p.ext.setdefault("turn_marks", {})[key] = True


@action("convert_damage")
def convert_damage(game, ctx, *, targets: list[Ref], to: str = "fragile") -> None:
    """伤害转化标记（targets 忽略）：登记到当前战斗上下文——该战斗中双方造成的伤害
    转化为等量的破甲（毒蚀；伤害管线于护甲计算后、扣减生命前读取，战斗终止点清除）。

    主动使用战斗牌时由战斗牌流程提取本步绑定该次战斗（不按普通 step 执行）；
    响应插入使用时作为普通动作执行，登记到被插入的当前战斗。
    """
    if to != "fragile":
        raise ValueError(f"未知 convert_damage 转化类型: {to}")
    if not game._battle_stack:
        return
    game._battle_convert.add(game._battle_stack[-1])


@action("double_damage_vs_fragile")
def double_damage_vs_fragile(game, ctx, *, targets: list[Ref]) -> None:
    """破甲双倍标记（targets 忽略）：登记到当前战斗上下文（战斗 id → 攻击者 Ref）——
    仅此战斗牌发起的战斗中，攻击者本人对具有破甲的式神造成的战斗伤害翻倍（义道；
    反击不翻倍，嵌套/插入战斗不继承；伤害管线于[暴击]时机=扣减生命前2读取，
    战斗终止点清除）。

    主动使用战斗牌时由战斗牌流程提取本步绑定该次战斗（不按普通 step 执行）；
    响应插入使用时作为普通动作执行，登记到被插入的当前战斗。
    """
    if not game._battle_stack:
        return
    game._battle_double_fragile[game._battle_stack[-1]] = ctx.source


@action("launch_attack")
def launch_attack(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
                  at: str | None = None) -> None:
    """令指定式神发起一次额外攻击（协战/崩山/来打我呀类；除 "target" 外 targets 忽略）。

    不耗鬼火、不耗出击次数；在准备区则自动进战斗区（沿用 _battle_flow 现有行为）；
    走正常战斗流程（反击照常，无战斗牌加成——就是一次普通攻击）。
    气绝/未出战/0 级（未在场）为空操作；定义 no_attack 的召唤物（冰墙"不能发动
    攻击"）同样为空操作。shikigami="self" 取来源式神；"target" 取卡牌选择目标
    所指式神（来打我呀"使一个敌方式神立刻发动攻击"，可为敌方）；否则按数据 id
    定位控制者式神。
    at="chosen"：战斗目标取本效果的卡牌选择目标（冰封[羁绊]"雪童子对其发动一次
    攻击"——有目标的战斗）；缺省为无目标战斗。
    """
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("launch_attack(shikigami=self) 需要来源式神")
        pi, idx = ctx.source.player, ctx.source.shikigami
    elif shikigami == "target":
        ref = targets[0] if targets else None
        if ref is None or ref.shikigami is None:
            return  # 无有效目标：空操作
        pi, idx = ref.player, ref.shikigami
    else:
        pi = ctx.controller
        idx = game._find_shikigami(game.state.players[pi], int(shikigami))
        if idx is None:
            return  # 未出战：空操作
    s = game.state.players[pi].shikigami[idx]
    if not s.in_play:
        return  # 气绝/离场/0 级：空操作
    if getattr(game.db.shikigami[s.id], "no_attack", False):
        return  # 不能发动攻击（冰墙）
    combat_target: Ref | None = None
    if at == "chosen" and ctx.chosen:
        combat_target = ctx.chosen[0]
    game._log(f"{game.db.shikigami[s.id].name} 发起了一次额外攻击")
    game._resolve_combat(Ref(player=pi, shikigami=idx), s, target=combat_target)


@action("counter_piercing")
def counter_piercing(game, ctx, *, targets: list[Ref]) -> None:
    """反击贯通标记（targets 忽略）：登记到当前战斗上下文——该战斗中被攻击方的反击
    伤害具有贯通（贯通修正批次对 kind=counter 的例外，rules.md:201；战斗终止点清除）。

    主动使用战斗牌时由战斗牌流程提取本步绑定该次战斗（不按普通 step 执行）；
    响应插入使用时作为普通动作执行，登记到被插入的当前战斗。
    """
    if not game._battle_stack:
        return
    game._battle_counter_piercing.add(game._battle_stack[-1])


@action("boost_damage")
def boost_damage(game, ctx, *, targets: list[Ref], amount: int = 0) -> None:
    """伤害增幅（targets 忽略）：在伤害时点改写事件中可变伤害对象的数值 +amount（只增）。

    amount=0（或负值）为空操作；须挂在伤害时点批次（on_damage_start 等 payload 含
    damage 的事件）上，配合条件（如 {source_shikigami: self, kind: effect}）使用。
    """
    ev = (ctx.event or {}).get("damage")
    if ev is None or amount <= 0:
        return
    ev.amount += amount


@action("power_override")
def power_override(game, ctx, *, targets: list[Ref], on: bool = True,
                   scope: str | None = None) -> None:
    """力量覆写（山童笨拙类）：on=True 时目标式神力量视为 0（覆盖基础+永久+临时+
    战力全部，eff_power 覆写层）；on=False 解除。形态离场、式神气绝时自动清除。
    scope="turn"（闪烁"本回合力量变为 0"）：半回合作用域——任一回合开始时随
    ext["power_zero_turn"] 通道一并解除（min_health_turn 先例，双方清除）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if on:
            s.ext["power_zero"] = True
            if scope == "turn":
                s.ext["power_zero_turn"] = True
        else:
            s.ext.pop("power_zero", None)
            s.ext.pop("power_zero_turn", None)


def _orb_count(value: int | dict, p: PlayerState, base_default: int) -> int:
    """次数参数解析：int 直取；{"orb": true} = 1 + 效果结算时剩余鬼火（基础 1 次 +
    每点剩余鬼火重复 1 次，0 火仍执行基础 1 次——维护者答复）；
    {"ext": key, "base": n} = base + 效果归属玩家 PlayerState.ext[key] 计数
    （流霰"本局每从手牌使用过一张'雪球'额外重复一次"，读 snowball_used_game）；
    其它 dict 取 base（缺省 base_default）。repeat/deck_top_pick 共用。"""
    if isinstance(value, dict):
        if value.get("ext") is not None:
            return int(value.get("base", 0)) + int(p.ext.get(value["ext"], 0))
        return 1 + p.orb if value.get("orb") else int(value.get("base", base_default))
    return int(value)


@action("repeat")
def repeat(game, ctx, *, targets: list[Ref], count: int | dict,
           steps: list, clear_orb: bool = False) -> None:
    """重复执行一组子步骤（吸魂灯"你每有 1 点鬼火便重复一次"；targets 忽略）。

    count 为整数或 {"orb": true}（解析见 _orb_count）；子步骤在同一块上下文
    （共享 ctx.memo）中逐轮顺序执行。clear_orb=True 时重复结束后一次性
    清空控制者鬼火（2→0 不经过 1）。
    """
    from db.schema import Step
    p = game.state.players[ctx.controller]
    n = _orb_count(count, p, 0)
    sub = [Step.model_validate(st) for st in steps]
    for _ in range(max(0, n)):
        for st in sub:
            game._run_step(st, ctx)
    if clear_orb:
        game._clear_orb(p, ctx.controller)


@action("deck_top_pick")
def deck_top_pick(game, ctx, *, targets: list[Ref], count: int = 3,
                  times: int | dict = 1, clear_orb: bool = False) -> None:
    """检视牌库顶 count 张牌，选一张置入手牌，然后洗牌库；重复 times 次（青灯夜谈；
    targets 忽略）。通过 pending_choice 挂起等 choose 指令作答（见 Game._cmd_choose）。

    times 为整数或 {"orb": true}（解析见 _orb_count）。牌库无可检视牌 = 不挂起；
    clear_orb=True 的清空仍执行（挂起时延后到末次选择后）。
    """
    p = game.state.players[ctx.controller]
    n = _orb_count(times, p, 1)
    if not game._open_deck_top_pick(ctx.controller, int(count), n, clear_orb):
        if clear_orb:
            game._clear_orb(p, ctx.controller)


@action("consume_orb")
def consume_orb(game, ctx, *, targets: list[Ref], amount: int = 1) -> None:
    """消耗控制者鬼火（不灭之火"消耗 1 点鬼火"；不视作使用牌；targets 忽略）。"""
    p = game.state.players[ctx.controller]
    old = p.orb
    p.orb = max(0, p.orb - int(amount))
    if p.orb != old:
        game.emit("on_orb_changed", player=ctx.controller, old=old, new=p.orb,
                  reason="consume_orb")


@action("clear_orb")
def clear_orb(game, ctx, *, targets: list[Ref], side: str = "self") -> None:
    """一次性清空一方鬼火（月食类响应"清空敌方的鬼火"；targets 忽略）。

    一次性变化：如 2→0 不经过 1，不触发"鬼火变为 1"类条件（on_orb_changed
    old→new 单事件）。side="self"（默认，控制者）/ "opponent"（对方）。
    """
    pi = ctx.controller if side == "self" else 1 - ctx.controller
    game._clear_orb(game.state.players[pi], pi)


@action("set_health")
def set_health(game, ctx, *, targets: list[Ref], amount: int) -> None:
    """把目标牌手的生命直接设置为 amount（轮回"你的生命变为 10"；非治疗也非伤害，
    不触发治疗/伤害事件）；钳制在 [1, max_health]。"""
    for ref in targets:
        if ref.shikigami is not None:
            continue
        p = game.state.players[ref.player]
        if p.defeated:
            continue
        old = p.health
        p.health = max(1, min(int(amount), p.max_health))
        game._settle(f"【生命设置】{p.name} 生命变为 {p.health}（{old}→{p.health}）")


@action("level_up")
def level_up(game, ctx, *, targets: list[Ref], amount: int = 1,
             overflow_draw: bool = False) -> None:
    """目标式神等级 +amount（百闻一得；不走升级次数、不受升级阶段限制，封顶 3 级）。

    overflow_draw=True：目标已为 3 级时改为控制者抽 1 张牌（"若其等级已为 3 则改为
    抽一张牌"）。0 级未在场/气绝式神为目标为空操作。
    实际升级后 emit on_upgrade（与指令升级同事件——犬神"犬神升级时"类触发对两来源
    均生效，维护者答复）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if not s.in_play:
            continue
        if s.level >= 3:
            if overflow_draw:
                game.draw_cards(ctx.controller, 1)
            continue
        s.level = min(3, s.level + int(amount))
        game._log(f"{game.db.shikigami[s.id].name} 升至 {s.level} 级")
        game._register_ability_countdown(ref.player, ref.shikigami)  # 能力进场（同升级）
        game.emit("on_upgrade", player=ref.player, shikigami=ref.shikigami,
                  level=s.level, target=ref)


@action("revive")
def revive(game, ctx, *, targets: list[Ref]) -> None:
    """复活目标式神（不灭之火"返回场上"前若气绝先复活；走 Game._revive 复活流程：
    生命回满、重注册倒计时能力、emit on_shikigami_revived，source=效果来源、
    reason="effect"——桃花妖"由桃花妖复活时"类触发以 source_shikigami 匹配）。
    未气绝/已离场为空操作。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        s = p.shikigami[ref.shikigami]
        if not s.defeated or s.despawned:
            continue
        game._revive(p, ref.player, ref.shikigami, source=ctx.source, reason="effect")


@action("reattach_form")
def reattach_form(game, ctx, *, targets: list[Ref]) -> None:
    """把触发事件（on_form_destroyed）中被消灭的形态卡实例从控制者墓地找回并重新
    结附给来源式神（不灭之火"返回场上"；维护者答复：同一实例，不生成新牌；targets 忽略）。

    实例不在墓地（被其它效果移走）、来源式神已离场或气绝（配合 revive 使用）时为空操作。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("reattach_form 需要来源式神")
    ev = ctx.event or {}
    uid = ev.get("uid")
    pi, si = ctx.source.player, ctx.source.shikigami
    p = game.state.players[pi]
    s = p.shikigami[si]
    if not s.in_play:
        return
    card = next((c for c in p.graveyard if c.uid == uid), None)
    if card is None:
        return
    game._remove_from_zone(p, card)
    game._attach_form(p, si, card, game.db.cards[card.id])


# ==================== 运势批次（契约 .tokensave/opmap_luck_batch.md） ====================


@action("stun")
def stun(game, ctx, *, targets: list[Ref], kind: str = "normal",
         until: int | None = None, lasting: bool = False,
         until_event: str | list[str] | None = None) -> None:
    """眩晕目标角色（契约 §1）：普通眩晕记施加时的控制者回合号（己方回合结束批次
    移除非本回合施加者）；持续眩晕（kind="lasting" 或 lasting=True）按 until 回合号
    或 until_event 事件监听移除。
    until_event（英雄无畏"保持眩晕直到鸦天狗使用牌、攻击或气绝"）：事件名列表，
    任一事件涉及施加时来源式神（watch）即解除——匹配见 engine._release_lasting_stuns
    （在 emit 点检查；被眩晕者自身气绝走现有气绝清理）。
    牌手眩晕条目挂 PlayerState.ext["stuns"]（同构）；眩晕牌手不能使己方式神出击。
    每次实际施加后按即时时机 emit on_stun（雪女"当你眩晕敌方式神时"类监听）。"""
    if lasting:
        kind = "lasting"
    watch: list[int] | None = None
    watch_id: int | None = None
    if until_event is not None:
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("stun(until_event=...) 需要来源式神（解除监听以其为基准）")
        src = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        watch = [ctx.source.player, ctx.source.shikigami]
        watch_id = src.id
    events = ([until_event] if isinstance(until_event, str) else list(until_event or [])) or None
    for ref in targets:
        p = game.state.players[ref.player]
        if ref.shikigami is None:
            stuns = p.ext.setdefault("stuns", [])
            name = p.name
        else:
            s = p.shikigami[ref.shikigami]
            if not s.in_play:
                continue
            stuns = s.stuns
            name = game.db.shikigami[s.id].name
        if kind == "lasting":
            entry: dict = {"kind": "lasting", "until": until}
            if events is not None:
                entry["until_event"] = events
                entry["watch"] = watch
                entry["watch_id"] = watch_id
                # 施加当时的事件序号与施加牌 uid：施加牌自身的 on_card_played（使用后1
                # 在效果结算后发出）不把刚施加的眩晕解除——"直到来源用牌"指其后的使用
                entry["apply_seq"] = game.state.emit_seq
                if ctx.card is not None:
                    entry["apply_uid"] = ctx.card.uid
            stuns.append(entry)
        else:
            stuns.append({"kind": "normal", "turn": p.turn_count})
        game._log(f"{name} 被眩晕")
        # "本局游戏每有一个敌方角色被[眩晕]"计数（雪融之时[增强]）：按受害者视角
        # 记到其对方的 PlayerState.ext["enemy_stunned_game"]（不分眩晕来源；
        # stat_aura kind=ext_power 读取时求值），先于 on_stun 事件记账
        op = game.state.players[1 - ref.player]
        op.ext["enemy_stunned_game"] = op.ext.get("enemy_stunned_game", 0) + 1
        game.emit("on_stun", victim=ref, source=ctx.source)


@action("transform")
def transform(game, ctx, *, targets: list[Ref], into: int,
              permanent: bool = False, owner_combat: bool = False) -> None:
    """把目标式神灵变为变形物 into（契约 §2；into 须为 kind=transform 的式神定义）。
    未在场/濒死者为空操作。

    permanent=True（觉醒·番茄）：永久变形——untransform 跳过、气绝前2 不还原
    （变形物气绝即气绝，复活仍为变形物）。
    owner_combat=True（觉醒·番茄特例）：变形物可使用原式神（transform_owner）的
    战斗牌（仅战斗牌；出牌校验白名单，见 engine._cmd_play_card）。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if not s.in_play or s.dying:
            continue
        game._transform_shikigami(game.state.players[ref.player], ref.shikigami, int(into))
        if permanent or owner_combat:
            b = game.state.players[ref.player].shikigami[ref.shikigami]
            if permanent:
                b.ext["transform_permanent"] = True
            if owner_combat:
                b.ext["owner_combat_ok"] = True


@action("untransform")
def untransform(game, ctx, *, targets: list[Ref]) -> None:
    """解除目标变形物的变形（纸人/小纸人能力：己方回合结束变回原式神）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        game._untransform(ref.player, ref.shikigami)


@action("luck_roll")
def luck_roll(game, ctx, *, targets: list[Ref], x: int, judge: str = "self",
              then: list | None = None, force_x1_if: dict | None = None) -> None:
    """步骤级运势判定（契约 §3.2；targets 忽略）：对判定者做 [运势X]，成功才执行 then 子步骤。

    judge：self（控制者，缺省）/ opponent / both（双方各生成事件，当前回合玩家先——
    并行入队、同步推进，见 Game._run_luck_events）。骰点存入效果上下文变量
    luck_dice（then 及后续步骤可以 amount_ctx: luck_dice 读取，骰子炸弹）。
    force_x1_if：条件满足时阈值视为 1（立直"若有形态必定成功"；骰子照投照计）。
    judge=both 时各判定者以自己的 ctx（controller=判定者）结算 then（判定者各自抽牌类）。
    """
    import dataclasses

    from db.schema import Step
    if judge not in ("self", "opponent", "both"):
        raise ValueError(f"未知 luck_roll 判定者: {judge}")
    judges = {"self": [ctx.controller], "opponent": [1 - ctx.controller],
              "both": [game.state.active, 1 - game.state.active]}[judge]
    x_eff = int(x)
    if force_x1_if is not None and game._match(force_x1_if, {}, ctx.controller,
                                               holder=ctx.source):
        x_eff = 1  # 立直：有形态则阈值视为 1（骰子照投照计）
    steps = [Step.model_validate(st) for st in (then or [])]
    events = []
    for j in judges:
        jctx = ctx if j == ctx.controller else dataclasses.replace(ctx, controller=j)
        jctx.memo = ctx.memo  # 共享块内暂存：luck_dice / last_damage_victims 等
        events.append({"judge": j, "x": x_eff, "source": ctx.source, "card": ctx.card,
                       "ctx": jctx, "then": steps, "on_fail": False})
    game._run_luck_events(events)


@action("luck_reroll")
def luck_reroll(game, ctx, *, targets: list[Ref]) -> None:
    """重投一次（座敷童子；targets 忽略）：改写判定时（on_luck_judge）事件中运势事件的
    当前骰点；同一判定中每个来源能力至多一次。重投同样吃萌即正义的判定者级必 6 修饰；
    被覆盖的首投不计入骰子历史（只记最终有效骰点，契约 §3.6）。
    """
    ev = (ctx.event or {}).get("luck")
    if not isinstance(ev, dict):
        return
    src = ctx.source
    key = (src.player, src.shikigami) if src is not None and src.shikigami is not None \
        else (ctx.controller, -1)
    used = ev.setdefault("rerolled", [])
    if key in used:
        return  # 同一判定中每个来源能力至多一次
    used.append(key)
    if game.state.players[ev["judge"]].ext.get("dice_force_six"):
        ev["dice"] = 6  # 萌即正义：重投的投掷骰子时机同样必 6
    else:
        ev["dice"] = game.rng.randint(1, 6)
    game._log(f"运势判定重投（新骰点 {ev['dice']}）")


@action("win_game")
def win_game(game, ctx, *, targets: list[Ref]) -> None:
    """目标牌手获得本局游戏胜利（这把算我赢增强变后；target=self 即控制者胜）。
    走待结束流程（_set_pending_end(loser=对方)；非气绝判负）。"""
    for ref in targets:
        if ref.shikigami is not None:
            continue
        game._log(f"{game.state.players[ref.player].name} 获得本局游戏胜利")
        game._set_pending_end(loser=1 - ref.player)


@action("repeat_random_damage")
def repeat_random_damage(game, ctx, *, targets: list[Ref], amount: int, pool: str,
                         max: int = 10, stop_on_defeat: bool = False) -> None:
    """无羁风弹（targets 忽略）：逐次在 pool 随机 1 名造成 amount 点伤害，插入结算。

    pool="all_other_shikigami"：双方所有其他未气绝式神（不含来源）；每次重新求值
    （已气绝/濒死者不再是合法目标）。stop_on_defeat=True：一旦任一式神因此效果
    （含其插入结算）气绝即停；否则满 max 次即停。
    """
    if pool != "all_other_shikigami":
        raise ValueError(f"未知 repeat_random_damage 目标池: {pool}")
    from core.engine import _DamageEvent  # 避免模块顶层循环引用

    def _refs() -> list[Ref]:
        out: list[Ref] = []
        for pi in (0, 1):
            for i, s in enumerate(game.state.players[pi].shikigami):
                if not s.in_play or s.dying:
                    continue
                if (ctx.source is not None and pi == ctx.source.player
                        and i == ctx.source.shikigami):
                    continue  # 不含来源
                out.append(Ref(player=pi, shikigami=i))
        return out

    pierce = game._ability_piercing(ctx)
    spell = game._spell_damage(ctx)
    defeated = sum(s.defeated for q in game.state.players for s in q.shikigami)
    for _ in range(int(max)):
        refs = _refs()
        if not refs:
            break
        r = game.rng.choice(refs)
        game._run_damage_queue([
            _DamageEvent(source=ctx.source, victim=r, amount=int(amount), kind="effect",
                         piercing=pierce, spell=spell)])
        if game.state.pending_end or game.state.winner is not None:
            break
        if stop_on_defeat:
            now = sum(s.defeated for q in game.state.players for s in q.shikigami)
            if now != defeated:
                break  # 任一式神气绝即停
            defeated = now


@action("reuse_card")
def reuse_card(game, ctx, *, targets: list[Ref]) -> None:
    """再次使用本牌（转运/叠风斩；targets 忽略）：法术→凭空自动使用管线（同目标，
    牌已在墓地不再移动）；战斗牌→战斗流程重走（关键字/一次性临时触发重新绑定，
    自动使用不耗火）。照常 emit on_card_played（triggered=auto，可再触发"使用牌时"
    类能力——叠风斩两次触发妖狐能力）。法术分支以实例标记 _reused 防无限自循环
    （再次使用不再触发"再次使用"）。"""
    if ctx.card is None:
        raise ValueError("reuse_card 需要来源卡牌实例")
    cdef = game.db.cards[ctx.card.id]
    p = game.state.players[ctx.controller]
    if cdef.card_type == "combat":
        if ctx.source is None or ctx.source.shikigami is None:
            return
        s = p.shikigami[ctx.source.shikigami]
        if not s.in_play:
            return
        game._log(f"【{cdef.name}】再次发起战斗（不耗鬼火）")
        grants = tuple((k, None) for k in cdef.keywords if k not in ("fast", "trigger", "rebound"))
        game._resolve_combat(ctx.source, s, grant_keywords=grants,
                             temp_grants=tuple(cdef.temp_grants), origin="card")
        return
    if ctx.card.mods.get("_reused"):
        return  # 再次使用不再触发"再次使用"（叠风斩恰触发两次）
    ctx.card.mods["_reused"] = True
    game._log(f"【{cdef.name}】再次使用（不耗鬼火）")
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, ctx.card, None), ExecContext(
            controller=ctx.controller, source=ctx.source, card=ctx.card,
            chosen=ctx.chosen))
    finally:
        affected = game._affected_stack.pop()["refs"]
    game._emit_card_played(ctx.controller, ctx.card.uid, cdef, affected,
                           play_from="void", triggered="auto", chosen=ctx.chosen)


@action("echo_event_card")
def echo_event_card(game, ctx, *, targets: list[Ref]) -> None:
    """复制使用事件中的法术牌（记仇；targets 忽略）：以监听控制者身份凭空再使用一次。

    读事件 payload 的 uid 定位被使用的卡牌（须为法术牌）；不耗鬼火、不做等级/目标
    合法性检查（[条件] 使用前提同免——"复仇"复制不看合法性）。目标强制为该法术
    施法者自己的式神（事件 player 方数据 id 所指在场式神；中立牌/施法者不在场/
    卡牌无 choose 目标则无目标使用——自动使用而没有效果）。凭空生成、用后进墓地、
    play_from=void、triggered=auto，照常 emit on_card_played（会触发"使用法术牌时"
    类能力，控制者为监听方）。一次性监听由 delay_grant(uses=1) 表达，本 op 只负责
    复制使用本身。
    """
    event = ctx.event or {}
    uid = event.get("uid")
    src_inst = game._card_by_uid(uid) if uid is not None else None
    if src_inst is None:
        return
    cdef = game.db.cards[src_inst.id]
    if cdef.card_type != "spell":
        return
    caster: Ref | None = None
    ep, esid = event.get("player"), event.get("shikigami")
    if ep is not None and esid is not None:
        cp = game.state.players[ep]
        ci = next((i for i, s in enumerate(cp.shikigami) if s.id == esid), None)
        if ci is not None and cp.shikigami[ci].in_play:
            caster = Ref(player=ep, shikigami=ci)
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    inst = CardInstance(uid=game.state.next_uid, id=cdef.id)  # 凭空生成，不进任何区域
    game.state.next_uid += 1
    game._materialize(p, inst, cdef)  # 生成点统一快照
    chosen = [caster] if (caster is not None and cdef.target.kind == "choose") else []
    game._log(f"凭空复制使用了【{cdef.name}】（目标为其施法者）")
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, inst, None), ExecContext(
            controller=ctx.controller, source=ctx.source, card=inst, chosen=chosen))
    finally:
        affected = game._affected_stack.pop()["refs"]
    game.move_card(p, inst, "graveyard")  # 凭空生成的复制牌用后进入墓地
    game._emit_card_played(ctx.controller, inst.uid, cdef, affected,
                           play_from="void", triggered="auto", chosen=chosen)


@action("bounce_self")
def bounce_self(game, ctx, *, targets: list[Ref]) -> None:
    """本牌移回手牌（蛇行击 2019 条件回手；targets 忽略）：牌在墓地时移回控制者
    手牌——与 rebound 关键字同路径（move_card 入手统一处理：超手牌上限按爆牌
    通用规则转墓地）。条件化回手以 Step 级 condition 表达（如 chosen_has_fragile；
    破甲受伤即消耗，读破甲的条件步须排在伤害步之前）。"""
    if ctx.card is None:
        raise ValueError("bounce_self 需要来源卡牌实例")
    p = game.state.players[ctx.controller]
    if ctx.card in p.graveyard:
        game.move_card(p, ctx.card, "hand")
        game._log(f"【{game.db.cards[ctx.card.id].name}】移回手牌")


@action("cost_delta_player")
def cost_delta_player(game, ctx, *, targets: list[Ref], amount: int,
                      scope: str = "next_turn", side: str | None = None,
                      card_flag: str | None = None) -> None:
    """目标牌手的手牌费用修正（幸运兔兔"敌方下回合从手牌使用的卡牌鬼火+1"；targets 解析
    目标牌手）。登记于 PlayerState.ext["cost_mods"]（回合号过期，仿 immunities）；
    _effective_cost 读取——[不消耗鬼火]与回合内首张[瞬发]已在费用求值中归零，不受影响；
    非手牌使用（自动使用等）不走 _effective_cost，不受影响。

    side="opponent"：targets 忽略，直接登记到敌对方牌手（"已展示"机制）。
    card_flag（如 "revealed"）：仅命中带对应实例标志（mods）的手牌——
    "敌方使用已展示的手牌额外耗火"（与瞬发/不消耗鬼火交互 = 全免，沿跳跳妹妹定案通道）。
    scope="form"：绑定来源形态、不按回合号过期、形态离场移除（需来源式神——
    心灵迷宫"敌方使用已展示的手牌时需额外消耗一点鬼火"形态结附期间持续）。
    """
    if scope not in ("next_turn", "form"):
        raise ValueError(f"未知 cost_delta_player 作用域: {scope}")
    refs = ([Ref(player=1 - ctx.controller)] if side == "opponent"
            else list(targets))
    for ref in refs:
        if ref.shikigami is not None:
            continue
        pl = game.state.players[ref.player]
        entry: dict = {"amount": int(amount), "scope": scope}
        if scope == "next_turn":
            entry["turn"] = game.state.turn + (2 if ref.player == game.state.active else 1)
        else:
            if ctx.source is None or ctx.source.shikigami is None:
                raise ValueError("cost_delta_player(scope=form) 需要来源式神")
            entry["holder"] = [ctx.source.player, ctx.source.shikigami]  # 形态离场按持有者移除
        if card_flag is not None:
            entry["card_flag"] = card_flag
        pl.ext.setdefault("cost_mods", []).append(entry)
        if scope == "next_turn":
            game._log(f"{pl.name} 的下个回合手牌鬼火消耗 {int(amount):+d}")
        else:
            game._log(f"{pl.name} 的手牌鬼火消耗 {int(amount):+d}（形态结附期间）")


@action("countdown_power_boost")
def countdown_power_boost(game, ctx, *, targets: list[Ref], countdown: int = -1,
                          power: int = 1, perm: bool = False) -> None:
    """山兔能力原子语义（契约 §0 要点 15）："倒计时-1 并 +1 力量"为同段效果——

    - 气绝者：只减气绝复活倒计时（被本次 -1 归零复活者不追加力量）；
    - 存活者（含无倒计时能力的）：倒计时 -1（归零走 _countdown_zero 流程）并 +1 力量
      （perm=False 默认临时，气绝清除——"获得力量"无"永久"修饰的惯例；perm=True 为
      永久修正，复活保留）。
    """
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        s = p.shikigami[ref.shikigami]
        if s.despawned or s.level < 1:
            continue
        name = game.db.shikigami[s.id].name
        if s.defeated:
            s.revive_countdown += int(countdown)
            game._log(f"{name} 的气绝倒计时 {int(countdown):+d}（余 {s.revive_countdown}）")
            if s.revive_countdown <= 0:
                game._revive(p, ref.player, ref.shikigami)  # 被本次归零复活者不追加力量
            continue
        if s.countdown is not None and s.countdown > 0 and s.countdown_block is not None:
            s.countdown += int(countdown)
            if s.countdown <= 0:
                game._countdown_zero(ref.player, ref.shikigami)
        if power:
            if perm:
                s.perm_power += int(power)
            else:
                s.temp_power += int(power)
            game._record_max_power(s)
            game._settle(f"【力量】{name} {'永久' if perm else '临时'}力量 "
                         f"{int(power):+d}（现 {s.eff_power}）")


@action("random_play_form")
def random_play_form(game, ctx, *, targets: list[Ref]) -> None:
    """鸿运当头：目标各随机使用 1 张等级 <= 其当前等级的专属形态牌（凭空自动使用：
    _play_form_card + on_card_played(triggered=auto)）；无可用形态/气绝者跳过。"""
    from core.model import CardInstance
    for ref in targets:
        if ref.shikigami is None:
            continue
        p = game.state.players[ref.player]
        s = p.shikigami[ref.shikigami]
        if not s.in_play:
            continue  # 无可用形态/气绝者跳过
        pool = [c.id for c in game.db.cards.values()
                if not c.token and c.card_type == "form" and c.shikigami == s.id
                and c.level <= s.level]
        if not pool:
            continue
        cdef = game.db.cards[game.rng.choice(pool)]
        if not game._play_condition_met(p, cdef):
            continue  # [条件] 使用前提：自动使用同检
        inst = CardInstance(uid=game.state.next_uid, id=cdef.id)  # 凭空生成，不进入任何区域
        game.state.next_uid += 1
        game._materialize(p, inst, cdef)  # 生成点统一快照
        game._log(f"{game.db.shikigami[s.id].name} 随机使用了【{cdef.name}】")
        game._play_form_card(p, ref.shikigami, inst, cdef, ref.player, [])
        game._emit_card_played(ref.player, inst.uid, cdef,
                               play_from="void", triggered="auto")


@action("set_dice_modifier")
def set_dice_modifier(game, ctx, *, targets: list[Ref], mode: str,
                      value: bool = True) -> None:
    """骰子修饰（契约 §3.5；targets 忽略）：

    - mode="six"（萌即正义）：判定者级光环必 6，写控制者牌手 ext["dice_force_six"]
      （形态进场 on / 离场 off 由数据侧挂接）；
    - mode="six_once"（这把算我赢）：来源级——写来源式神 ext["dice_force_six_once"]，
      下次以其为来源的判定首投必 6 并消耗。
    """
    if mode == "six":
        pl = game.state.players[ctx.controller]
        pl.ext["dice_force_six"] = bool(value)
        if value and ctx.source is not None and ctx.source.shikigami is not None:
            # 记持有者座次（萌即正义形态）：该形态离场时随离场通道一并解除
            pl.ext["dice_force_six_holder"] = [ctx.source.player, ctx.source.shikigami]
        elif not value:
            pl.ext.pop("dice_force_six_holder", None)
        game._log(f"{game.state.players[ctx.controller].name} 的骰子必 6 修饰"
                  f"{'生效' if value else '解除'}")
    elif mode == "six_once":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("set_dice_modifier(mode=six_once) 需要来源式神")
        s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        s.ext["dice_force_six_once"] = True
        game._log(f"{game.db.shikigami[s.id].name} 的下次运势判定首投必 6")
    else:
        raise ValueError(f"未知 set_dice_modifier 模式: {mode}")


@action("discard_random")
def discard_random(game, ctx, *, targets: list[Ref], count: int = 1) -> None:
    """随机弃目标牌手 count 张手牌（转运用；targets 缺省回退控制者——与 discard 的
    顺序弃牌不同，本 op 为随机弃牌，故不复用 discard）。
    """
    players = [game.state.players[r.player] for r in targets if r.shikigami is None]
    if not players:
        players = [game.state.players[ctx.controller]]
    for p in players:
        n = min(int(count), len(p.hand))
        for c in game.rng.sample(p.hand, n):
            game._log(f"{p.name} 随机弃掉了【{game.db.cards[c.id].name}】")
            game.move_card(p, c, "graveyard")


# ==================== 不夜之火批次（能量/[爆能]/[移动]/鼓舞扩展） ====================


class AbortBlock(Exception):
    """中止当前效果块剩余步骤（spend_energy gate=True 支付失败时抛出；
    engine._run_block_steps 捕获后正常收尾，不向外传播）。"""


@action("gain_energy")
def gain_energy(game, ctx, *, targets: list[Ref], amount: int = 1,
                emit_event: bool = True) -> None:
    """目标式神获得能量（经 engine._gain_energy 统一入口，上限 10；烟雾升腾/
    冬日暖阳/沐浴阳光/小鹿男复活等）。emit_event=False：追加的额外获得不再发出
    on_energy_gained（烟烟罗类"获得能量时"触发器自身的追加获得，防递归循环）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        game._gain_energy(game.state.players[ref.player], ref.shikigami,
                          int(amount), emit_event=emit_event)


@action("spend_energy")
def spend_energy(game, ctx, *, targets: list[Ref], amount: int = 1,
                 gate: bool = False) -> None:
    """来源式神消耗能量（经 engine._spend_energy 统一入口：觉醒·日和坊免单与
    日和坊生命代偿同通道；祈晴/滋养/晴雨/自强之愿/同生共死"消耗X能量，…"）。

    支付为全有或全无（不足则一点不扣）。gate=True：支付失败时中止本效果块
    剩余步骤（"消耗4能量，抽一张牌"类——付不起则后续效果不发生）。"""
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("spend_energy 需要来源式神")
    p = game.state.players[ctx.source.player]
    if game._spend_energy(p, ctx.source.shikigami, int(amount)):
        return
    name = game.db.shikigami[p.shikigami[ctx.source.shikigami].id].name
    game._log(f"{name} 能量不足，无法支付 {int(amount)} 点能量")
    if gate:
        raise AbortBlock()


@action("move")
def move(game, ctx, *, targets: list[Ref], force: bool = False) -> None:
    """[移动]：目标式神战斗区↔准备区移动（追风/鸦羽疾走；targets 默认来源式神）。

    在准备区 → 进战斗区（复用 engine._enter_combat；移入会替换被尘缚之阵锁定的
    战斗区式神时该效果无效，与 enter_combat 同校验）；在战斗区 → 回准备区
    （复用 engine._retreat，召唤物退回即离场）。气绝/已离场者不能移动；
    眩晕不影响被移动。进/出战斗区各计一次 [移动]（engine 记账 ext["move_count_turn"]，
    气绝离场与召唤物进场不计）。
    force=True（羽迹"将敌方式神移入战斗区"）：允许移动敌方式神（仅拉入战斗区方向
    有意义）；非强制时敌方式神目标静默跳过。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        if ref.player != ctx.controller and not force:
            continue  # 非强制只能移动己方式神
        p = game.state.players[ref.player]
        s = p.shikigami[ref.shikigami]
        if s.defeated or s.despawned:
            continue  # 气绝/离场不能移动
        if p.combat_index == ref.shikigami:
            game._retreat(p, ref.shikigami)  # 在战斗区 → 回准备区
            continue
        if not s.in_play:
            continue
        if p.combat_index is not None and game._combat_zone_locked(ref.player):
            game._log(f"{p.name} 的移动效果被尘缚之阵无效化")
            continue
        game._enter_combat(p, ref.shikigami)


def _add_boost_flag(game, ctx, kind: str, scope: str | None,
                    extra: dict | None = None) -> None:
    """登记玩家级出击加成旗标（PlayerState.ext["boost_flags"]，鼓舞扩展三 op 共用）。

    scope="form"：绑定来源式神当前形态，形态离场时经 engine._destroy_form 移除
    （不夜之舞/离殇之舞）；缺省永久（觉醒·不知火，觉醒后常驻、跨气绝保留）。"""
    entry: dict = {"kind": kind, **(extra or {})}
    if scope == "form":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError(f"{kind}(scope=form) 需要来源式神")
        entry["holder"] = [ctx.source.player, ctx.source.shikigami]
    p = game.state.players[ctx.controller]
    p.ext.setdefault("boost_flags", []).append(entry)


@action("boost_on_combat_card")
def boost_on_combat_card(game, ctx, *, targets: list[Ref],
                         scope: str | None = None) -> None:
    """玩家级旗标（不夜之舞；targets 忽略）：该玩家的出击加成在使用战斗牌发起的
    攻击结算点也调用 engine._consume_assault_boosts（同样获得并消耗出击加成）。
    scope="form"：绑定来源形态，离场清除。"""
    _add_boost_flag(game, ctx, "combat_card", scope)
    game._log(f"{game.state.players[ctx.controller].name} 的出击加成在使用战斗牌时也会生效")


@action("boost_no_consume")
def boost_no_consume(game, ctx, *, targets: list[Ref],
                     scope: str | None = None) -> None:
    """玩家级旗标（离殇之舞；targets 忽略）：该玩家的出击加成不因出击/战斗牌攻击
    而消耗（每次攻击照常获得，加成不清空）。scope="form"：绑定来源形态，离场清除。"""
    _add_boost_flag(game, ctx, "no_consume", scope)
    game._log(f"{game.state.players[ctx.controller].name} 的出击加成不会因出击而消耗")


@action("inspire_bonus")
def inspire_bonus(game, ctx, *, targets: list[Ref], power: int = 0, shield: int = 0,
                  scope: str | None = None) -> None:
    """玩家级旗标（觉醒·不知火；targets 忽略）：该玩家的[鼓舞]（basic_boost）数值
    额外 +power/+shield（可叠加；basic_boost 读取时求值）。scope="form"：绑定来源
    形态，离场清除；缺省永久（觉醒常驻）。"""
    _add_boost_flag(game, ctx, "inspire_bonus", scope,
                    {"power": int(power), "shield": int(shield)})
    game._log(f"{game.state.players[ctx.controller].name} 的鼓舞额外 "
              f"+{int(power)}力量/+{int(shield)}护甲")


@action("reset_assaults")
def reset_assaults(game, ctx, *, targets: list[Ref]) -> None:
    """重置控制者出击次数（真意之歌；targets 忽略）：assaults_left 恢复为每回合
    默认值 1；变化时 emit on_assaults_changed（与回合开始重置同事件）。"""
    p = game.state.players[ctx.controller]
    old = p.assaults_left
    p.assaults_left = 1
    if p.assaults_left != old:
        game.emit("on_assaults_changed", player=ctx.controller, old=old,
                  new=p.assaults_left, reason="reset_assaults")


@action("clear_boosts")
def clear_boosts(game, ctx, *, targets: list[Ref]) -> None:
    """清除目标牌手的全部出击加成（日出有曜 B 选项）；无牌手目标时默认控制者。"""
    # 显式选择了目标（日出有曜单目标双效果定案）：目标是式神则空操作、目标是牌手则
    # 对其生效；仅无目标时回退控制者
    if targets and all(r.shikigami is not None for r in targets):
        return
    refs = [r for r in targets if r.shikigami is None] or [Ref(player=ctx.controller)]
    for ref in refs:
        p = game.state.players[ref.player]
        if p.assault_boosts:
            p.assault_boosts.clear()
            game._log(f"{p.name} 的出击加成被清除")


@action("reset_stats")
def reset_stats(game, ctx, *, targets: list[Ref]) -> None:
    """目标式神力量、生命变为基础值（日出有曜 A 选项）：清除非永久力量/生命上限
    增减益（临时修正与攻击后到期挂账、本回合力量通道），清除护甲与破甲，
    然后生命设为变更后上限——直改，不是伤害/治疗事件（不触发任何伤害/治疗时机）。
    动态身材光环（ext dyn 缓存通道）不动：下个重算点自然重新生效。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        s.temp_power = 0
        s.temp_health = 0
        s.combat_power = 0
        s.attack_buffs.clear()
        s.ext.pop("turn_power", None)
        s.shield = 0
        s.health = s.max_health
        game._settle(f"【重置】{game.db.shikigami[s.id].name} 力量/生命变为基础值"
                     f"（{s.eff_power}/{s.health}），护甲与破甲清除")


@action("energy_assault")
def energy_assault(game, ctx, *, targets: list[Ref], cost: int = 3) -> None:
    """登记觉醒·镰鼬的出击替代支付（玩家级旗标，targets 忽略）：该玩家鬼火与
    出击次数都为 0 时，旗标持有者可以消耗 cost 点能量出击（engine._cmd_assault
    支付管线分支读取；消耗经 _spend_energy——觉醒·日和坊免单同通道）。"""
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("energy_assault 需要来源式神")
    p = game.state.players[ctx.controller]
    p.ext["energy_assault"] = {
        "holder": [ctx.source.player, ctx.source.shikigami], "cost": int(cost)}
    game._log(f"{p.name} 获得能量出击能力（鬼火与出击次数都为 0 时，"
              f"{game.db.shikigami[p.shikigami[ctx.source.shikigami].id].name}"
              f"可消耗 {int(cost)} 点能量出击）")



@action("form_death_play")
def form_death_play(game, ctx, *, targets: list[Ref], energy: int = 3) -> None:
    """登记觉醒·小鹿男的形态牌气绝使用旗标（玩家级 PlayerState.ext["form_death_play"]，
    targets 忽略）：旗标持有者的形态牌在持有者气绝时可用——使用时消耗 energy 点能量
    （engine._spend_energy 统一入口，觉醒·日和坊免单/日和坊生命代偿同通道），使用效果前
    先复活持有者，再正常结附形态（合法性/支付/复活见 engine._cmd_play_card）。
    觉醒常驻：玩家级旗标，跨气绝保留、不清除。"""
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("form_death_play 需要来源式神")
    p = game.state.players[ctx.controller]
    p.ext["form_death_play"] = {
        "holder": [ctx.source.player, ctx.source.shikigami], "energy": int(energy)}
    game._log(f"{game.db.shikigami[p.shikigami[ctx.source.shikigami].id].name} 的形态牌"
              f"在其气绝时可用（消耗 {int(energy)} 点能量并复活）")
