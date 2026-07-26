"""对局运行时状态：全部为纯数据（pydantic 模型），可整体 JSON 序列化。

引擎外的代码（CLI、未来的网络层）只通过这些结构与 Game 交互；
状态可 dump/restore，支撑回放、存档与单元测试。
命名以 docs/terminology.md 为准：鬼火 orb、出击 assault、升级 upgrade、
气绝 defeated、护甲 shield、力量 power。
"""
from __future__ import annotations

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
    hand_cap: int = 12  # 手牌上限；超出时卡牌先进入目标区域再移至墓地（Phase 3+ 完整流程）
    deck_cap: int = 99  # 牌库上限；预留，Phase 1 不强制


# 标准卡牌区域；引擎不限制于此——move_card 可创建任意新区域
STANDARD_ZONES = ("deck", "hand", "graveyard", "exile")


class Ref(BaseModel):
    """指向一名牌手或其一方式神。shikigami 为 None 时表示牌手本人。"""

    player: int
    shikigami: int | None = None


class ShikigamiState(BaseModel):
    """对局中一个式神（实体）的运行时状态。

    身材组成（thoughts.txt）：基础值（式神基础值/当前形态基础值）
    + 永久增减益修正 + 临时增减益修正。
    临时/永久的区分标准是"气绝后复活能否保留"：临时修正在气绝时清除，
    永久修正复活后保留（光环类属临时修正的细分，Phase 3）。
    """

    id: int  # 数据 id：对应 db 中式神的 id
    kind: str = "shikigami"  # shikigami=式神（非召唤物） / summon=召唤物
    faction: str = "无相"  # 派系，可被效果临时/永久改变
    level: int = 0  # 0 级 = 未在场：能力不触发、不能行动、不可被指定（除特殊说明）
    home_slot: int | None = None  # 所属准备区编号（1-4）；召唤物为 None（无准备区可归）
    entry_order: int = 0  # 角色进场顺序：牌手为 0，式神按入场顺序 1-4
    base_power: int  # 基础力量（形态会改写，Phase 3）
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
    shield: int = 0  # 护甲：被伤害时优先消耗；己方回合开始阶段清除（可因效果改变）。
                    # 注意：破甲 fragile 是独立结算流程（见 docs/rules.md 第六章），
                    # Phase 3 才引入，不要简单地用负护甲表示。
    defeated: bool = False  # 气绝
    stunned: bool = False  # 眩晕（Phase 3）：不能主动行动/被指定/升级，但能力仍可触发
    despawned: bool = False  # 召唤物离场标记（不进复活流程；保留坑位稳定下标）
    revive_countdown: int = 0
    form: CardInstance | None = None  # 当前结附的形态牌（card_type=form）
    attack_buffs: list[dict[str, Any]] = Field(default_factory=list)  # 攻击后到期强化挂账：{"power": int, "keywords": [(kw, cls)]}；自身作为攻击者的战斗终止点核销（keep_attack_buffs 跳过）；气绝清空
    awakened: int | None = None  # 已觉醒：觉醒牌数据 id（能力替换为觉醒能力；气绝/复活保留）
    keep_shield: bool = False  # 护甲不在己方回合开始阶段移除（觉醒·兵俑）
    countdown: int | None = None  # 当前倒计时（形态牌结附时授予=初始值；己方回合开始 -1，归零重置并执行形态倒计时效果；形态离场/气绝清除）
    delayed: list[dict[str, Any]] = Field(default_factory=list)  # 绑定式神的一次性延迟能力（会）：
    # {"block": EffectBlock, "chosen": Ref|None, "uses": 1}；气绝清除（变形离场保留——变形未实现，见 rules.md）

    @property
    def eff_power(self) -> int:
        """有效力量 = 基础 + 永久修正 + 临时修正 + 本次战斗战力。"""
        return self.base_power + self.perm_power + self.temp_power + self.combat_power

    @property
    def max_health(self) -> int:
        return self.base_health + self.perm_health + self.temp_health

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


class PlayerState(BaseModel):
    """局内"牌手"：有生命/护甲、可被指定为目标的参战实体。

    抽象的"玩家对象"（账号/连接）属 Phase 2 服务端概念，不进入 GameState。
    """

    name: str
    health: int = 30
    max_health: int = 30
    shield: int = 0  # 牌手护甲；己方回合开始阶段清除
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
    summon_legacy: dict[int, dict[str, int]] = Field(default_factory=dict)  # 同名召唤物再召时保留的永久增减益（key=召唤物定义 id）
    card_mods: dict[int, dict[str, Any]] = Field(default_factory=dict)  # 持久修饰 store：card_id → 修饰（"本局游戏每……"类，打出时装配快照）
    card_auras: list[dict[str, Any]] = Field(default_factory=list)  # 卡牌光环注册表：
    # {shikigami, card_type, keywords, cost_zero, scope}；scope 决定失效时机（"turn"=己方回合开始清除）
    assault_boosts: list[dict[str, Any]] = Field(default_factory=list)  # 出击加成（鼓舞）：
    # {"power", "shield"}；下一次出击时全部消耗（力量战后到期、护甲保留；战斗牌不消耗）

    @property
    def deck(self) -> list[CardInstance]:
        return self.zones.setdefault("deck", [])

    @property
    def hand(self) -> list[CardInstance]:
        return self.zones.setdefault("hand", [])

    @property
    def graveyard(self) -> list[CardInstance]:
        return self.zones.setdefault("graveyard", [])


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


class GameState(BaseModel):
    players: list[PlayerState]
    active: int = 0  # 当前回合玩家下标
    turn: int = 1  # 双方合计半回合计数；turn==1 为先手玩家的第 1 回合
    phase: str = "battle"  # mulligan=调度阶段（游戏开始） / battle=对战阶段
    winner: int | None = None
    pending_end: bool = False  # 是否处于“待结束”状态（牌手气绝/长对局平局后，剩余结算完成前）
    pending_loser: int | None = None  # 待结束时的失败方下标；-1 表示平局
    next_uid: int = 1
    emit_seq: int = 0  # 事件编号：每次 emit 递增，持久化到状态以支持回放/断线重连
    config: GameConfig = Field(default_factory=GameConfig)
    log: list[str] = Field(default_factory=list)
    temp_grants: list[TempGrant] = Field(default_factory=list)  # 一次性临时触发注册表

    def next_emit_seq(self) -> int:
        """取下一个事件编号并递增。"""
        self.emit_seq += 1
        return self.emit_seq
