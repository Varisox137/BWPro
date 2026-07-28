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

from core.model import ExecContext, Ref, ShikigamiState

ACTIONS: dict[str, Callable] = {}


def action(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        ACTIONS[name] = fn
        return fn

    return deco


@action("damage")
def damage(game, ctx, *, targets: list[Ref], amount: int,
           piercing: bool | None = None) -> None:
    """对目标（式神或牌手）造成 amount 点伤害；护甲优先吸收。

    实例修饰 damage_boost（鎏金幻羽给手牌黄金羽的"伤害+1"）在卡牌效果伤害上累加。
    贯通：piercing 显式指定优先（牌面明确"贯通伤害"的卡牌效果）；缺省时仅当伤害
    来自式神能力且来源式神具有贯通才继承——卡牌效果伤害不因式神持有贯通而贯通
    （terminology.md「贯通」）。
    """
    if ctx.card is not None:
        amount += int(ctx.card.mods.get("damage_boost", 0))
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
    for ref in targets:
        if ref.shikigami is None:
            game.deal_to_player(ref.player, amount, ctx.source)
        else:
            game.deal_to_shikigami(ref, amount, ctx.source, piercing=pierce)
    if ctx.memo is not None:
        # 记录本步伤害的受伤者（式神），供同块后续 step 以 context 目标引用（风神一扇）
        ctx.memo["last_damage_victims"] = [r for r in targets if r.shikigami is not None]


@action("heal")
def heal(game, ctx, *, targets: list[Ref], amount: int) -> None:
    """恢复生命（走 Game.heal 治疗事件流程）：治疗量 = min(amount, 已损失生命)，
    0 终止；濒死/气绝（未在场）式神与气绝牌手不受治疗。"""
    for ref in targets:
        game.heal(ref, amount, ctx.source, reason="heal")


@action("draw")
def draw(game, ctx, *, targets: list[Ref], count: int | dict = 1) -> None:
    """效果归属玩家抽 count 张牌（targets 忽略）。牌库抽空判负。

    count 支持 {"memo": key}：读块内暂存 ctx.memo[key]（射怪鸟事"弃多少抽多少"，
    与 discard 写入的 discarded_count 组合）。
    """
    if isinstance(count, dict):
        n = int((ctx.memo or {}).get(count.get("memo"), 0))
    else:
        n = int(count)
    game.draw_cards(ctx.controller, n)


@action("buff_power")
def buff_power(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False) -> None:
    """力量增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。

    已气绝式神不能获得非永久增益，但可以获得永久增益（thoughts.txt"已气绝状态"）；
    0 级未在场/已离场式神不受影响。
    """
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play and (s.despawned or not s.defeated or not perm):
                continue
            if perm:
                s.perm_power += amount
            else:
                s.temp_power += amount


@action("buff_health")
def buff_health(game, ctx, *, targets: list[Ref], amount: int, perm: bool = False) -> None:
    """生命上限增益：perm=True 为永久修正（复活保留），否则为临时修正（气绝时清除）。

    已气绝式神不能获得非永久增益，但可以获得永久增益（当前生命不随之上调，
    复活时按新上限回满）；0 级未在场/已离场式神不受影响。
    """
    for ref in targets:
        if ref.shikigami is not None:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if not s.in_play and (s.despawned or not s.defeated or not perm):
                continue
            if perm:
                s.perm_health += amount
                if not s.defeated:
                    s.health += amount
            else:
                s.temp_health += amount
                # 临时增加上限时，当前生命同步增加等量数值（不超过新上限）
                if amount > 0:
                    s.health = min(s.max_health, s.health + amount)


@action("gain_shield")
def gain_shield(game, ctx, *, targets: list[Ref], amount: int, kind: str = "shield") -> None:
    """获得/失去护甲或破甲（式神与牌手均可；docs/rules.md 第六章）。

    kind="shield"（缺省）：amount > 0 获得护甲 / < 0 失去护甲（旧用法 {amount: n} 等价
    kind=shield 获得，向后兼容）；kind="fragile"：amount > 0 获得破甲 / < 0 失去破甲。
    获得先抵消反向值再盈余同向；减少只能扣已有的同向值。0 级未在场式神不能获得
    护甲/破甲/增益。护甲/破甲变化按即时时机发出 on_shield_changed 事件（payload 带 kind）。
    """
    for ref in targets:
        if ref.shikigami is None:
            game._change_shield(ref, amount, "gain_shield", kind=kind)
        else:
            s = game.state.players[ref.player].shikigami[ref.shikigami]
            if s.in_play:
                game._change_shield(ref, amount, "gain_shield", kind=kind)


@action("summon")
def summon(game, ctx, *, targets: list[Ref], shikigami: int) -> None:
    """为效果归属玩家召唤一个召唤物（定义须 kind=summon）。

    召唤物的生成视作其移动进入战斗区（但不视为从准备区离开）；
    若战斗区已有驻留者，其退回准备区（召唤物则直接离场）。
    若该召唤物定义 keep_buffs=True，则同名再召时继承上次离场时的永久增减益。
    """
    d = game.db.shikigami[shikigami]
    p = game.state.players[ctx.controller]
    if game._combat_zone_locked(ctx.controller):
        # 尘缚之阵：兵俑在战斗区且己方战斗区有式神时，召唤召唤物的效果无效
        game._log(f"{p.name} 的召唤效果被尘缚之阵无效化")
        return
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
              card_type: str | None = None, keywords: list[str] | None = None,
              cost_zero: bool = False, scope: str = "turn") -> None:
    """登记卡牌光环（targets 忽略）：谓词匹配的卡牌获得 keywords / 不耗鬼火。

    覆盖谓词命中的全部卡牌（任何区域，含之后新生成的）——读取时求值而非写入实例。
    scope 为失效时机："turn" = 己方回合开始清除（"本回合"类）；其余 scope 随需要扩展。
    """
    if shikigami == "self":
        if ctx.source is None or ctx.source.shikigami is None:
            raise ValueError("card_aura(shikigami=self) 需要来源式神")
        sid = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami].id
    else:
        sid = int(shikigami)
    game.state.players[ctx.controller].card_auras.append({
        "shikigami": sid, "card_type": card_type,
        "keywords": list(keywords or []), "cost_zero": cost_zero, "scope": scope,
    })
    game._log(f"{game.db.shikigami[sid].name} 的卡牌光环生效（{scope}）")


@action("grant_keyword")
def grant_keyword(game, ctx, *, targets: list[Ref], keyword: str) -> None:
    """授予目标式神一个关键字（按关键字的天然持久性类别入列，见 engine._grant_keyword）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if s.in_play:
            game._grant_keyword(s, keyword)


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
    """直接消灭目标式神（非伤害：生命归零走气绝流程；尘缚之阵的免疫直接消灭在此判定）。
    濒死者不能再次被消灭（早退）。"""
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if not s.in_play or s.dying:
            continue
        if game._direct_destroy_immune(ref.player, ref.shikigami):
            game._log(f"{game.db.shikigami[s.id].name} 免疫了本次消灭")
            continue
        s.health = 0
        game.check_defeated(ref, source=ctx.source, reason="消灭")


@action("basic_boost")
def basic_boost(game, ctx, *, targets: list[Ref], power: int = 0, shield: int = 0) -> None:
    """鼓舞：登记一笔出击加成（targets 忽略）。下一次出击时全部消耗——
    力量直到该次出击的战斗后，护甲保留；战斗牌不消耗出击加成。"""
    game.state.players[ctx.controller].assault_boosts.append(
        {"power": power, "shield": shield})
    game._log(f"{game.state.players[ctx.controller].name} 获得出击加成（+{power}力量/+{shield}护甲）")


@action("consume_assault_boosts")
def consume_assault_boosts(game, ctx, *, targets: list[Ref]) -> None:
    """消耗己方全部出击加成（鼓舞），作为该战斗牌赋予来源式神的加成
    （targets 忽略；灵矢贯虹羁绊，维护者答复 10：战力/护甲作为此战斗牌赋予的效果
    ——战力持续到本次战斗结束后经 combat_power 核销、护甲保留；鼓舞中的关键字
    当前卡池不存在，落地后在此扩展）。战斗牌本不消耗鼓舞，本步为牌面指定的例外。
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
    game._log(f"{game.db.shikigami[s.id].name} 的鼓舞转化为本次战斗加成"
              f"（+{power}力量/+{shield}护甲）")


@action("generate")
def generate(game, ctx, *, targets: list[Ref], shikigami: int | str = "self",
             card_type: str | None = None, count: int = 1, zone: str = "hand",
             max_level: int | str | None = None, exclude_self: bool = False,
             card_id: int | None = None, subtype: str | None = None) -> None:
    """随机生成符合谓词的卡牌并置入区域（targets 忽略；可重复，杀念/觉醒·一目连）。

    card_id 指定时直接生成该 id 的牌（可生成 token；黄金羽/金风流羽），绕开随机池。
    subtype：限定子类型（"随机获得一张妖琴师觉醒牌"= spell + awaken）。
    max_level="source"：卡牌等级 ≤ 来源式神当前等级（吾即正义"小于等于自身等级"）；
    exclude_self=True：排除来源卡牌同 id（"其他法术牌"）。
    """
    from core.model import CardInstance
    p = game.state.players[ctx.controller]
    if card_id is not None:
        for _ in range(count):
            inst = CardInstance(uid=game.state.next_uid, id=int(card_id))
            game.state.next_uid += 1
            game.move_card(p, inst, zone)
            game._log(f"生成了《{game.db.cards[int(card_id)].name}》")
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
    pool = [c.id for c in game.db.cards.values()
            if not c.token and c.shikigami == sid
            and (card_type is None or c.card_type == card_type)
            and (subtype is None or c.subtype == subtype)
            and (lv is None or c.level <= lv)
            and not (exclude_self and ctx.card is not None and c.id == ctx.card.id)]
    if not pool:
        return
    p = game.state.players[ctx.controller]
    for _ in range(count):
        cid = game.rng.choice(pool)
        inst = CardInstance(uid=game.state.next_uid, id=cid)
        game.state.next_uid += 1
        game.move_card(p, inst, zone)
        game._log(f"生成了《{game.db.cards[cid].name}》")


@action("random_damage")
def random_damage(game, ctx, *, targets: list[Ref], amount: int, pool: str,
                  count: int | dict = 1, piercing: bool | None = None) -> None:
    """对 pool 中无放回随机 count 个目标各造成 amount 点伤害（单次伤害队列=并行结算）。

    count 支持 {"mod": key, "base": n}：base + ctx.card.mods[key]（风符·龙的实例计数）。
    目标数超出可选目标时按可选目标数截断。贯通规则同 damage 动作。
    """
    from core import targets as targets_mod
    if isinstance(count, dict):
        n = int(count.get("base", 1))
        if count.get("mod") and ctx.card is not None:
            n += int(ctx.card.mods.get(count["mod"], 0))
    else:
        n = int(count)
    refs = targets_mod.pool_refs(game, pool, ctx.controller)
    if not refs:
        return
    n = min(n, len(refs))
    chosen = game.rng.sample(refs, n)
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
    from core.engine import _DamageEvent  # 避免模块顶层循环引用
    game._run_damage_queue([
        _DamageEvent(source=ctx.source, victim=r, amount=amount, kind="effect",
                     piercing=pierce)
        for r in chosen
    ])


@action("distribute_damage")
def distribute_damage(game, ctx, *, targets: list[Ref], amount: int, pool: str,
                      piercing: bool | None = None) -> None:
    """造成总计 amount 点伤害，随机分配给 pool 中的目标。

    流程：确定目标池 → 重复 amount 次 {随机选取目标池中 1 名合法目标，对其造成 1 点伤害}。
    与 random_damage（随机选取 x 个目标、同一队列并行受伤）不同：每次重复的伤害事件
    单独结算（重复之间按即时时机插入）；气绝事件按延时时机延后到本效果结束后统一生成，
    但已因此效果生命 ≤ 0（标记气绝）的目标不再是后续重复的合法目标。贯通规则同 damage。
    """
    from core import targets as targets_mod
    refs = targets_mod.pool_refs(game, pool, ctx.controller)
    if not refs:
        return
    pierce = piercing if piercing is not None else game._ability_piercing(ctx)
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
                          piercing=pierce)],
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
                secret: bool = False, scope: str | None = None) -> None:
    """给来源式神登记一个一次性延迟能力（会；targets 忽略）。

    when/condition/steps 描述延迟触发的效果块；打出时的选择目标（ctx.chosen）
    随条目存储，触发结算时作为效果目标。气绝时清除（变形离场保留——变形未实现）。
    scope="turn"："本回合"类（魔音扰心主动使用）——己方回合开始清除（未消耗时）。
    scope="play"："本次使用期间"类（黑羽之刃的消灭抽牌）——该次出牌结算结束时清除。
    secret=True 时选择目标对敌方保密（会：所选目标仅己方可见）——联机状态脱敏
    （server/room.py sanitize_state）会对敌方视角抹除 chosen；热坐/日志本就不回显目标。
    """
    if ctx.source is None or ctx.source.shikigami is None:
        raise ValueError("delay_grant 需要来源式神")
    from db.schema import EffectBlock, Step
    block = EffectBlock(when=when, condition=condition,
                        steps=[Step.model_validate(st) for st in (steps or [])])
    s = game.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
    s.delayed.append({
        "block": block,
        "chosen": ctx.chosen[0] if ctx.chosen else None,
        "uses": 1,
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


@action("cap_damage")
def cap_damage(game, ctx, *, targets: list[Ref], to: str = "shield") -> None:
    """伤害上限（森罗之阵；targets 忽略）：改写事件中可变伤害对象的数值。

    to="shield"：若受伤式神具有护甲，伤害值至多为其当前护甲值（护甲 0 不生效）。
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
    else:
        raise ValueError(f"未知 cap_damage 上限类型: {to}")


@action("countdown_delta")
def countdown_delta(game, ctx, *, targets: list[Ref], amount: int,
                    shikigami: int | None = None, revive: bool = False) -> None:
    """目标式神倒计时增减 amount（±）。

    无倒计时能力或倒计时为 0（归零结算中）时修正为 -0（空操作，rules.md ch12
    增减流程 1）；减少后不大于 0 时走归零流程（_countdown_zero，与回合开始批次共用）。
    倒计时增减事件的独立时机批次暂不拆，首张监听卡出现时再引入。

    shikigami：按数据 id 指定控制者的式神（targets 忽略；协战羁绊"鸩/以津真天
    倒计时-2"——未出战为空操作）；revive=True：改为作用于控制者已气绝式神的
    气绝倒计时（targets 忽略，扫描全队；幻音绝弦"已气绝则改为气绝倒计时-2"），
    减到 ≤0 立即复活。
    """
    if shikigami is not None:
        pi = ctx.controller
        idx = game._find_shikigami(game.state.players[pi], int(shikigami))
        targets = [Ref(player=pi, shikigami=idx)] if idx is not None else []
    if revive:
        p = game.state.players[ctx.controller]
        pi = ctx.controller
        for i, s in enumerate(p.shikigami):
            if not s.defeated or s.despawned or s.level < 1:
                continue
            s.revive_countdown += amount
            if s.revive_countdown <= 0:
                game._revive(p, pi, i)
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
        game._log(f"《{cname}》重放了{game.db.shikigami[sid].name}的倒计时效果（来源 {src}）")
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
    inst = CardInstance(uid=game.state.next_uid, id=cid)  # 凭空生成，不进入任何区域
    game.state.next_uid += 1
    game._log(f"{game.db.shikigami[s.id].name} 的倒计时自动使用了《{cdef.name}》")
    game._affected_stack.append({"controller": ctx.controller, "refs": []})
    try:
        game._resolve_block(game._played_block(p, cdef, inst, None), ExecContext(
            controller=ctx.controller, source=ctx.source, card=inst, is_ability=True))
    finally:
        affected = game._affected_stack.pop()["refs"]
    game._clear_play_delayed(s)  # "本次使用期间"延迟能力的窗口随自动使用结束（黑羽之刃）
    game._emit_card_played(ctx.controller, inst.uid, cdef, affected)


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


@action("mirror_attack_buffs")
def mirror_attack_buffs(game, ctx, *, targets: list[Ref]) -> None:
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
        game._log(f"触发了{game.db.shikigami[s.id].name}当前形态《{cdef.name}》的进场效果")
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
            count: int | None = None) -> None:
    """弃掉控制者手牌中符合谓词的牌（移入墓地；targets 忽略）。

    shikigami="self" 弃来源式神所属的牌（射怪鸟事 = discard + draw 两步组合）；
    shikigami="all" 弃全部手牌；count 限制弃牌张数（缺省弃全部符合者）。
    结算后把实际弃牌数写入块内暂存 ctx.memo["discarded_count"]（供后续 step 的
    {"memo": key} 动态数值引用，如 draw"弃多少抽多少"）。
    """
    p = game.state.players[ctx.controller]
    if shikigami == "all":
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
        game._log(f"{p.name} 弃掉了《{game.db.cards[c.id].name}》")
        game.move_card(p, c, "graveyard")
    if ctx.memo is not None:
        ctx.memo["discarded_count"] = len(pool)


@action("grant_immunity")
def grant_immunity(game, ctx, *, targets: list[Ref], scope: str = "turn") -> None:
    """授予目标式神战斗伤害免疫（不可饶恕"本回合用过黄金羽则免疫战斗伤害"）。

    scope="turn"：免疫到当前回合结束——以回合号记账（{"turn": 当前回合}），
    _combat_immune 按回合号比对，跨回合自然过期，无需清理。
    """
    if scope != "turn":
        raise ValueError(f"未知 grant_immunity 作用域: {scope}")
    for ref in targets:
        if ref.shikigami is None:
            continue
        s = game.state.players[ref.player].shikigami[ref.shikigami]
        if s.in_play:
            s.immunities.append({"kind": "combat_damage", "turn": game.state.turn})
            game._log(f"{game.db.shikigami[s.id].name} 免疫战斗伤害（本回合）")


@action("gain_orb")
def gain_orb(game, ctx, *, targets: list[Ref], amount: int = 1) -> None:
    """控制者获得 amount 点鬼火（镇魂歌；targets 忽略）；emit on_orb_changed。"""
    p = game.state.players[ctx.controller]
    old = p.orb
    p.orb += amount
    if game.config.orb_cap is not None:
        p.orb = min(p.orb, game.config.orb_cap)
    if p.orb != old:
        game.emit("on_orb_changed", player=ctx.controller, old=old, new=p.orb, reason="gain_orb")


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
