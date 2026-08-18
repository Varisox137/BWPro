"""对局运行时状态：全部为纯数据（pydantic 模型），可整体 JSON 序列化。

引擎外的代码（CLI、未来的网络层）只通过这些结构与 Game 交互；
状态可 dump/restore，支撑回放、存档与单元测试。
命名以 docs/terminology.md 为准：鬼火 orb、出击 assault、升级 upgrade、
气绝 defeated、护甲 shield、力量 power。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from db.schema import EffectBlock


class GameConfig(BaseModel):
    """对局基础设定：随对局状态序列化。

    每项都可能对双方不同——PlayerState.config 可按键覆盖（见 engine.cfg）。
    默认值即标准规则（来源：thoughts.txt / 规则集，待校对项见 questions.md）。
    """

    player_health: int = 30       # 牌手初始生命及上限
    starting_hand: int = 5        # 双方起始手牌均 5 张
    mulligan_count: int = 3       # 调度次数（游戏开始阶段，双方各自；可以不用满）
    draw_per_turn: int = 1        # 回合开始抽牌数（在回合开始效果结算后执行；先手首回合不抽）
    orb_per_turn: int = 2         # 回合开始鬼火
    first_turn_orb: int = 1       # 先手第一回合鬼火
    orb_cap: int | None = None    # 鬼火上限；None = 不限
    max_level: int = 3            # 式神等级上限
    revive_countdown: int = 3     # 气绝复活所需己方回合数
    upgrade_rule: str = "lowest"  # 升级规则：lowest=只能升己方最低级 / ordered=按上阵顺序 / free=任选
    second_player_shield: int = 5  # 后手补偿：牌手护甲
    extra_upgrade_turns: tuple[int, int] = (7, 3)  # 先手第 7 / 后手第 3 个己方回合各 +1 升级机会
    enable_debug_commands: bool = True  # 是否启用 debug_ 指令（服务端可关闭）
    auto_skip_upgrade: bool = False  # 测试便利：升级阶段自动跳过（生产/CLI 保持 False）
    hand_cap: int = 12  # 手牌上限；超出时卡牌先进入目标区域再移至墓地（Phase 5+ 完整流程）
    deck_cap: int = 99  # 牌库上限；预留，Phase 1 不强制


# 标准卡牌区域；引擎不限制于此——move_card 可创建任意新区域
STANDARD_ZONES = ("deck", "hand", "graveyard", "exiled")


class Ref(BaseModel):
    """指向一名牌手或其一方式神。shikigami 为 None 时表示牌手本人。"""

    player: int
    shikigami: int | None = None


class ShikigamiState(BaseModel):
    """对局中一个式神（实体）的运行时状态。

    身材组成（thoughts.txt）：基础值（式神基础值/当前形态基础值）
    + 永久增减益修正 + 临时增减益修正 + 灵咒类光环层（读取时实时合计）。
    临时/永久的区分标准是"气绝后复活能否保留"：临时修正在气绝时清除，
    永久修正复活后保留（光环类属临时修正的细分——连续型动态身材光环走
    ext["dyn_power"]/["dyn_health"] 缓存通道，见 engine._refresh_stat_auras；
    灵咒身材增减益不借 temp 承载，见 invocations 字段注释）。
    """

    id: int  # 数据 id：对应 db 中式神的 id
    kind: str = "shikigami"  # shikigami=式神（非召唤物） / summon=召唤物
    faction: str = "无相"  # 当前派系，可被效果临时改变
    perm_faction: str = "无相"  # 永久派系：组建/进场时定死（召唤物/变形物继承效果来源式神的
    # perm_faction，式神替换物用自身 def faction）；效果临时改派系只动 faction
    level: int = 0  # 0 级 = 未在场：能力不触发、不能行动、不可被指定（除特殊说明）
    home_slot: int | None = None  # 所属准备区编号（1-4）；召唤物为 None（无准备区可归）
    entry_order: int = 0  # 角色进场顺序：牌手为 0，式神按入场顺序 1-4；再进场（变形/还原/召唤/替换）排本队最后
    ability_entry: dict[str, int] = Field(default_factory=dict)  # 各能力的进场序号
    # （"ability"=基础/觉醒能力、"form"=形态能力；进场点记录——对局开始/升级/复活/觉醒替换/
    # 形态结附/变形与还原；同事件触发按能力进场顺序排序，thoughts 答复(4)(6)；快照携带、还原重记）
    base_power: int  # 基础力量（形态会改写，Phase 5）
    base_health: int  # 基础生命
    perm_power: int = 0  # 永久增减益修正（气绝后复活保留）
    perm_health: int = 0
    temp_power: int = 0  # 临时增减益修正（气绝时清除）
    temp_health: int = 0  # 临时生命上限修正（气绝时清除）
    combat_power: int = 0  # 本次战斗的战力加成（战斗后清除）
    keywords: list[str] = Field(default_factory=list)  # 持续性关键字实例（可重复多重集；触发后不移除；气绝时清除）
    one_shot_keywords: list[str] = Field(default_factory=list)  # 一次性关键字实例（迅捷/不屈/屏障等；触发后移除；气绝时清除）
    perm_keywords: list[str] = Field(default_factory=list)  # 永久关键字实例（气绝时不清除 = 复活后自动重新获得）
    immunities: list[dict[str, Any]] = Field(default_factory=list)  # 作用域免疫条目，如 {"kind": "combat_damage", "battle": int, "nested": bool}；战斗结束/气绝时清除
    health: int  # 当前生命
    shield: int = 0  # 护甲（>0）/ 破甲（<0）：有符号单一字段。破甲 = 负值，
                    # 变化事件以 kind 参数区分方向（docs/rules.md 第六章）；
                    # 被伤害时正护甲优先吸收、负破甲加成伤害；己方回合开始阶段双向清除。
    energy: int = 0  # 能量（[充能]/[爆能]体系，不夜之火包）：己方回合开始具有[充能]者 +1
                    # （上限 10）；气绝时保留不清零；消耗走 engine._spend_energy 统一入口
    defeated: bool = False  # 气绝
    dying: bool = False  # 濒死：生命 ≤ 0 但气绝事件尚未结算（通用状态标记，语义见 docs/rules.md）
    stuns: list[dict[str, Any]] = Field(default_factory=list)  # 眩晕条目：
    # {"kind": "normal", "turn": 施加时控制者回合号}（普通眩晕，己方回合结束批次移除非本回合
    # 施加者）/ {"kind": "lasting", "until": ...}（持续眩晕，预留）；非空 = 眩晕：
    # 不能出击、不能主动使用/响应使用其卡牌（能力仍可触发）；气绝时清除
    despawned: bool = False  # 召唤物离场标记（不进复活流程；保留坑位稳定下标）
    revive_countdown: int = 0
    form: CardInstance | None = None  # 当前结附的形态牌（card_type=form）
    attack_buffs: list[dict[str, Any]] = Field(default_factory=list)  # 攻击后到期强化挂账：{"power": int, "keywords": [(kw, cls)]}；自身作为攻击者的战斗终止点核销（keep_attack_buffs 跳过）；气绝清空
    awakened: int | None = None  # 已觉醒：觉醒牌数据 id（能力替换为觉醒能力；气绝/复活保留）
    keep_shield: bool = False  # 护甲不在己方回合开始阶段移除（觉醒·兵俑）
    keep_fragile: bool = False  # 破甲不在己方回合开始阶段移除（肿胀体质；形态离场经
    # _destroy_form 一并解除——"形态在场时"语义）
    countdown: int | None = None  # 当前倒计时（至多 1 个倒计时能力；己方回合开始 -1，归零先结算后重置/移除；
    # 注册/替换时机：能力进场、觉醒替换、形态结附、set_countdown；形态离场仅清除形态授予的，气绝清除）
    countdown_initial: int | None = None  # 倒计时初始值（循环型归零后重置为该值）
    countdown_block: EffectBlock | None = None  # 倒计时归零时执行的效果块（EffectBlock.countdown 标记的能力块 / 形态牌 countdown_effects）
    countdown_once: bool = False  # 一次型倒计时：生效后移除而非重置（大天狗记录法术、灵咒锚点）
    countdown_source: int | None = None  # 倒计时来源 id：基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id
    # （形态授予判定 = countdown_source == 当前形态牌 id；countdown_history 记账用）
    ext: dict[str, Any] = Field(default_factory=dict)  # 少数卡专用的式神级运行时数据（约定键见 docs/terminology.md）
    delayed: list[dict[str, Any]] = Field(default_factory=list)  # 绑定式神的一次性延迟能力（会）：
    # {"block": EffectBlock, "chosen": Ref|None, "uses": 1}；气绝清除（变形离场保留——快照随
    # transform_origin 一并还原）
    transform_owner: int | None = None  # 变形物的"所属式神" = 原式神 id（变形物无法使用原式神
    # 的卡牌——出牌校验按此拒绝；万象之书类按原式神取牌的读取处预留，本批仅作字段）
    transform_origin: dict | None = None  # 变形还原式神快照（ShikigamiState dump，不含本字段）：
    # 被变形时 = 原式神快照；原式神该值非空则继承之（连续变形解除时还原到最初的原式神状态）
    invocations: list[dict[str, Any]] = Field(default_factory=list)  # 结附的灵咒条目：
    # {"name", "player"（来源所属牌手）, "source": Ref|None（来源式神）,
    # "ability_seq": int（结附时刻的能力进场序号）, "power"/"health": int
    # （效果类身材增减益的结附时刻快照——类光环层：不进 temp 修正，由
    # eff_power/max_health 读取时实时合计，移除即消失、reset_stats 不可清）}；
    # 能力类结附期间生效，气绝/离场时移除

    @property
    def is_stunned(self) -> bool:
        """是否眩晕：眩晕条目（普通/持续）非空。"""
        return bool(self.stuns)

    @property
    def eff_power(self) -> int:
        """有效力量 = 基础 + 永久修正 + 临时修正 + 本次战斗战力 + 动态光环缓存。

        覆写层：ext["power_zero"] 置位时力量视为 0（power_override op 授予，
        覆盖全部加成层；形态离场/气绝时清除）。
        ext["dyn_power"]：连续型动态身材光环的缓存通道（闻世/火吻之蛇；
        由 engine._refresh_stat_auras 在手牌数/破甲变化等读取点统一刷新）。
        灵咒层：结附灵咒条目的 power 快照实时合计（类光环——rules.md 灵咒节
        定案：被"日出有曜"类清除临时修正后仍立即继续生效）。
        """
        if self.ext.get("power_zero"):
            return 0
        return (self.base_power + self.perm_power + self.temp_power
                + self.combat_power + int(self.ext.get("dyn_power", 0))
                + sum(int(e.get("power", 0)) for e in self.invocations))

    @property
    def max_health(self) -> int:
        return (self.base_health + self.perm_health + self.temp_health
                + int(self.ext.get("dyn_health", 0))  # dyn 通道同 eff_power
                + sum(int(e.get("health", 0)) for e in self.invocations))  # 灵咒层同上

    @property
    def in_play(self) -> bool:
        """是否在场：未气绝、未离场、等级 >= 1。

        0 级式神视为未在场：能力不触发、不能行动/被指定、不受治疗增益。
        召唤物离场（despawned）后保留坑位以稳定下标，但不再视为在场。
        """
        return not self.defeated and not self.despawned and self.level >= 1


class CardInstance(BaseModel):
    """对局中一张牌的实例。

    uid 是局内对象标识——同名卡（甚至与式神实体重名的卡）靠 uid 区分；
    id 是数据 id（对应 db 中的卡牌 id）；mods 保存实例级修饰，使同名卡可彼此不同。
    hand_seq 用于记录该牌加入手牌的顺序编号（调度换入牌会继承换出牌的编号）。
    """

    uid: int
    id: int  # 数据 id
    mods: dict[str, Any] = Field(default_factory=dict)  # 如 {"cost_delta": -1}
    hand_seq: int = 0  # 手牌顺序编号（加入手牌时分配；0 表示未分配）
    invocations: list[dict[str, Any]] = Field(default_factory=list)  # 结附的灵咒条目：
    # {"name", "player"（来源所属牌手）, "source": Ref|None（来源式神）}；
    # 入手时处理：抽牌入手触发"抽到触发"块后移除，非抽牌入手静默移除
    # （引擎 _proc_invocations_on_move）


@dataclass
class ExecContext:
    """效果执行上下文：动作注册表（core/actions.py）的 API 契约。

    放在 model 层以避免 actions/debug 对 engine 的循环引用；引擎结算时构造。
    """

    controller: int  # 效果归属玩家
    source: Ref | None = None  # 来源式神（中立牌无来源，为 None）
    card: CardInstance | None = None  # 来源卡牌实例
    event: dict[str, Any] | None = None  # 触发来源事件 payload
    chosen: list[Ref] | None = None  # 玩家选择的目标
    triggered: bool = False  # 是否为响应牌触发（结算时支付鬼火并消耗手牌）
    card_id: int | None = None  # 游离触发器的来源卡 id（add_mod 写入目标定位用）
    is_ability: bool = False  # 是否式神能力来源（基础/觉醒/形态能力、形态倒计时、延迟"会"）
    # ——卡牌效果（on_play/响应/卡牌触发器/临时触发）为 False；贯通继承等的判定依据
    memo: dict[str, Any] | None = None  # 块内步骤间暂存（由 _resolve_block 初始化）：
    # damage 动作写入 last_damage_victims（上一步伤害的受伤者），后续 step 以
    # TargetSpec(kind="context", key="last_damage_victims") 引用（风神一扇）
    field: Any = None  # 触发来源幻境实体（幻境能力块结算时持有——自毁/改降耐久/
    # 自身耐久条件等"此牌"自指语义的定位依据；非幻境能力为 None）
    block: Any = None  # 正在结算的效果块（_resolve_pending 塞入——field_rebound
    # "失去此能力"按对象身份定位触发块在 def.abilities 中的下标用；on_play 为 None）
    ability_uid: str | None = None  # 能力实例身份（转移链记账用，定案"转移链"：
    # 每个伤害转移能力在同一转移链上只执行一次）。收集器填：式神基础/觉醒/形态能力
    # = "shk:{pi}:{si}:{id(block)}"；TempGrant = "grant:{seq}"；幻境能力块 =
    # "field:{pi}:{队列下标}:{id(block)}"；其余通道（卡牌触发/光环/delayed）为 None
    # ——redirect_damage_to_self 以 id(ctx.block) 对象身份兜底


class FieldState(BaseModel):
    """在场幻境实体（幻境机制；幻境牌 card_type="field" 使用后"召唤幻境"入队）。

    所属牌手拥有其能力（能力块 = 幻境牌 def 的 abilities，跳过 mods.disabled_abilities
    登记的下标——荒海"失去此能力"；外加 extra_abilities 叠加块——辉夜姬觉醒"能力和
    耐久会叠加"合并持多块；在场期间随队列存续生效）；耐久 0 被消灭（耐久变化/消灭
    事件流程见 engine._change_field_intensity）。
    """

    card_id: int  # 幻境牌数据 id（名称/能力块读 db.cards[card_id]）
    intensity: int  # 当前耐久（正整数；牌手受伤时队列首个幻境减少等量耐久，0 = 消灭）
    shikigami: int | None = None  # 所属式神数据 id（= 幻境牌的所属式神；伤害来源归属用：
    # 该式神在场时幻境伤害来源为该式神，否则为无来源伤害——规范"零"条）
    mods: dict[str, Any] = Field(default_factory=dict)  # 召唤牌实例 mods 快照
    # （intensity_boost 已于召唤时结算入耐久；disabled_abilities = 被移除的能力块下标）
    keywords: list[str] = []  # 幻境实体关键字（召唤时拷贝 CardDef.field_keywords——
    # 帷幕/health_floor_one/deck_top_play 等幻境语义；方圆之备类效果可后续授予入列）
    extra_abilities: list = []  # 叠加合并获得的能力块（EffectBlock 列表，免循环引用不注解）


class PlayerState(BaseModel):
    """局内"牌手"：有生命/护甲、可被指定为目标的参战实体。

    抽象的"玩家对象"（账号/连接）属 Phase 2 服务端概念，不进入 GameState。
    """

    name: str
    health: int = 30
    max_health: int = 30
    shield: int = 0  # 牌手护甲（>0）/ 破甲（<0），有符号（同 ShikigamiState.shield）；己方回合开始阶段清除
    defeated: bool = False  # 牌手气绝：对局进入"待结束"，该牌手不再受到伤害和治疗
    entry_order: int = 0  # 角色进场顺序：牌手先于所有己方式神，固定为 0
    orb: int = 0  # 鬼火；己方回合开始重置，回合间不清零（留火响应）
    shikigami: list[ShikigamiState] = Field(default_factory=list)
    zones: dict[str, list[CardInstance]] = Field(
        default_factory=lambda: {z: [] for z in STANDARD_ZONES})
    combat_index: int | None = None  # 战斗区式神下标；None = 战斗区为空
    turn_count: int = 0  # 该玩家的己方回合计数（第 N 回合）
    upgrades: int = 0  # 本回合剩余升级机会
    assaults_left: int = 0  # 本回合剩余出击次数（常规每回合唯一，己方回合开始时重置）
    fast_used: bool = False  # 本（半）回合是否已使用过免费瞬发（双方各自计算）
    mulligans_left: int = 0  # 调度阶段剩余调度次数
    mulligan_done: bool = False  # 调度阶段：该玩家已确认完成
    config: dict[str, Any] = Field(default_factory=dict)  # 对 GameConfig 的玩家级覆盖
    card_mods: dict[int, dict[str, Any]] = Field(default_factory=dict)  # 持久修饰 store：card_id → 修饰（"本局游戏每……"类，打出时装配快照）
    # 击杀账本（引擎统一记账，规则设计评审⑩；check_defeated 单点记账——气绝与消灭同口径，
    # 仅统计有来源的消灭并按来源归属牌手分桶，消灭己方式神如伤害转移同样计入来源方）：
    kill_total: int = 0  # 本局以己方角色为来源消灭的式神总数（夺命"你消灭过13个式神"）
    kill_by: dict[int, int] = Field(default_factory=dict)  # 分桶：来源式神当前数据 id → 消灭数（禁锢之刀）
    card_auras: list[dict[str, Any]] = Field(default_factory=list)  # 卡牌光环注册表：
    # {shikigami, card_type, keywords, cost_zero, scope}；scope 决定失效时机（"turn"=己方回合开始清除）
    auras: list[dict[str, Any]] = Field(default_factory=list)  # 牌手级持久监听（"本局游戏"类，
    # 豪焰）：{"block": EffectBlock, "once_key": str|None}；事件触发即结算块，跨气绝保留、
    # 回合开始不清除（player_aura 动作写入，emit 时按注册顺序收集）
    assault_boosts: list[dict[str, Any]] = Field(default_factory=list)  # 出击加成（鼓舞）：
    # {"power", "shield"}；下一次出击时全部消耗（力量战后到期、护甲保留；战斗牌不消耗）
    immunities: list[dict[str, Any]] = Field(default_factory=list)  # 牌手级伤害免疫条目
    # （舍生"本回合你免疫所有伤害"；{"kind": "all", "turn": 回合号}，按回合号比对过期）
    fields: list[FieldState] = Field(default_factory=list)  # 幻境队列（有序；
    # 牌手因受伤减少生命后，首个幻境减少等量耐久；耐久 0 消灭出队）
    ext: dict[str, Any] = Field(default_factory=dict)  # 牌手级专用运行时数据（约定键见
    # docs/terminology.md：countdown_history 本局倒计时能力生效序列 等）

    @property
    def deck(self) -> list[CardInstance]:
        return self.zones.setdefault("deck", [])

    @property
    def hand(self) -> list[CardInstance]:
        return self.zones.setdefault("hand", [])

    @property
    def graveyard(self) -> list[CardInstance]:
        return self.zones.setdefault("graveyard", [])

    @property
    def is_stunned(self) -> bool:
        """牌手是否眩晕：眩晕条目挂 ext["stuns"]（同 ShikigamiState.stuns 结构）；
        眩晕牌手不能使己方式神出击（全体）。"""
        return bool(self.ext.get("stuns"))


class TempGrant(BaseModel):
    """一次性临时触发（docs/enhance-design.md 修饰词汇表）：注册进状态、结算后 uses-1、归零移除。

    战斗牌的 temp_grants 在发起战斗时注册并绑定该次战斗（battle=bid，战斗终止点移除未用者）；
    holder 供条件迷你语言的 self 形式匹配（如 source_shikigami: self）。
    """

    block: EffectBlock
    controller: int  # 效果归属玩家
    holder: Ref | None = None  # 能力持有者（条件 self 匹配基准）
    battle: int | None = None  # 绑定的战斗 id；None = 不绑定
    uses: int = 1  # 剩余触发次数
    seq: int = 0  # 能力进场序号（注册时记录；同事件触发按序排序，0=未登记按注册顺序）


class GameState(BaseModel):
    players: list[PlayerState]
    active: int = 0  # 当前回合玩家下标
    turn: int = 1  # 双方合计半回合计数；turn==1 为先手玩家的第 1 回合
    phase: str = "battle"  # mulligan=调度阶段（游戏开始） / upgrade=式神升级阶段 / battle=对战阶段
    winner: int | None = None
    pending_end: bool = False  # 是否处于“待结束”状态（牌手气绝/长对局平局后，剩余结算完成前）
    pending_loser: int | None = None  # 待结束时的失败方下标；-1 表示平局
    next_uid: int = 1
    emit_seq: int = 0  # 事件编号：每次 emit 递增，持久化到状态以支持回放/断线重连
    ability_seq: int = 0  # 能力进场序号：每次能力进场递增（同事件触发排序用）
    config: GameConfig = Field(default_factory=GameConfig)
    log: list[str] = Field(default_factory=list)
    settle_log: list[str] = Field(default_factory=list)  # 结算明细通道（数值变化/事件开始结束；CLI 空闲点逐条展示用，与 log 指令回显分离）
    timeline: list[dict[str, str]] = Field(default_factory=list)  # 合并时间线（{"k": "s"|"l", "m": msg}：
    # _settle/_log 双通道按真实发生顺序的合流；联机/热坐的结算播放以此为准，避免
    # "能力触发"类叙事行滞后到插入结算明细之后（维护者定案））
    temp_grants: list[TempGrant] = Field(default_factory=list)  # 一次性临时触发注册表
    pending_choice: dict | None = None  # 结算中交互选择（青灯夜谈 deck_top_pick：
    # {"kind", "player", "options": [uid], "remaining", "clear_orb"}）；挂起期间只接受
    # choose 指令；options 对非选择方脱敏（server/room.py sanitize_state）。块续点
    # （Game._suspended）为内存态不序列化——断线重连后挂起块不续跑（已知限制）

    def next_emit_seq(self) -> int:
        """取下一个事件编号并递增。"""
        self.emit_seq += 1
        return self.emit_seq

    def next_ability_seq(self) -> int:
        """取下一个能力进场序号并递增（答复(4)：同事件触发按能力进场顺序排序）。"""
        self.ability_seq += 1
        return self.ability_seq
