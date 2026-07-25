"""卡牌/式神静态数据的 schema 与兼容纪律。

1. id 号段约定（loader 会校验一致性）：
   - 式神：6 位数字，格式 1xxxyy（1 + 3 位卡包 cardpack + 2 位卡包内序号）
   - 统一 6 位式神 id + 2 位序号：可构筑卡牌 01-08；衍生卡（token）从 51 开始递增；
     衍生物（召唤物）从 99 开始递减；协战牌双式神从属，规则见 docs/rules.md 第十四/十五章。
   - 中立牌（无从属式神，实质为系统/效果生成的衍生卡）：9999zzzz 形式，无等级
2. version：8 位数字日期（YYYYMMDD），标记最近一次平衡性调整。
3. 字段只增不改；未知字段原样保留（extra="allow"），旧工具读新数据不丢信息。
4. card_type 为规则级主类型；"觉醒"不是主类型，而是通用 tag（tags 含 awaken 即可，
   任何主类型的牌都可以是觉醒牌）。tags 为自由字符串（规则级或式神专属标记）。
5. 对局中运行时对象另有 oid（CardInstance.uid），与本文件的数据库 id 区分。

命名以 docs/terminology.md 为准（如：鬼火 orb、力量 power、护甲 shield、气绝 defeated）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 卡牌主类型：法术 / 战斗 / 形态 / 幻境（预留） / 协战（预留）
CARD_TYPES = frozenset({"spell", "combat", "form", "field", "reinforce"})
SUBTYPES = frozenset({"awaken"})  # 子类型：awaken=觉醒牌；保留扩展
KEYWORDS = frozenset({
    "fast", "trigger",          # 瞬发 / 响应（卡牌级）
    "combo", "initiative",      # 连击 / 先攻
    "piercing", "pierce",       # 贯通 / 穿刺
    "remote",                   # 远程
    "unyielding", "haste",      # 不屈 / 迅捷
    "barrier",                  # 屏障
    "keep_attack_buffs",        # 引擎级：攻击后到期强化不因攻击移除（残心；卡面不出现）
})  # 机制未实现的关键词不放进数据，避免静默失效（rules.md:270）。
# 语义约定：战斗牌 keywords（fast/trigger 除外）= 本次战斗中授予攻击者；
# 形态牌 keywords（fast/trigger 除外）= 结附期间授予式神。授予均按关键字的
# 天然持久性类别入列（见 core.model.ShikigamiState 与 docs/terminology.md）。
FACTIONS = frozenset({"红莲", "紫岩", "青岚", "苍叶", "无相"})  # 无相 = 无派系
FACTION_COLORS = {"红莲": "red", "紫岩": "purple", "青岚": "blue", "苍叶": "green", "无相": "white"}  # Phase 5 UI 展示预留，代码侧暂无消费方
RARITIES = frozenset({"R", "SR", "SSR"})  # 良 / 优 / 极（抽卡/账号系统预留，见 thoughts.txt）
# 觉醒牌 = 任意主类型 + tags 含 "awaken"；保留字面量即可，无需单独常量。

NEUTRAL_PREFIX = 9999  # 中立牌 id 前缀（9999zzzz）


def _check_version(v: int) -> int:
    s = str(v)
    if len(s) != 8:
        raise ValueError("version 须为 8 位数字日期（YYYYMMDD）")
    datetime.strptime(s, "%Y%m%d")  # 非法日期直接抛 ValueError
    return v


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["none", "self", "choose", "all", "context"] = "none"
    pool: str | None = None  # 见 core.targets.POOLS
    key: str | None = None  # kind=context 时引用事件 payload 的字段名


class Step(BaseModel):
    model_config = ConfigDict(extra="allow")

    op: str  # 动作名，须在 core.actions.ACTIONS 注册表中
    target: TargetSpec | None = None  # 缺省 = 使用卡牌的选择目标
    # 其余字段（amount / count / ...）按 op 需要原样保留在 model_extra


class EffectBlock(BaseModel):
    """一段效果：何时触发 + 如何结算 + 依次执行哪些动作。

    - when:    on_play 表示打出时；否则为核心/自定义事件名（被动、响应牌用）
    - mode:    interleaved=步骤之间允许其它效果结算 / atomic=不允许
    - timing:  作为触发效果时的结算时机覆盖：insert=立即插入 / queue=入队延迟；
               None（默认）= 跟随该事件的时机类别（core.events.EVENT_TIMING）
    - trigger_when_not_in_play: 允许在式神未升级（0 级未在场）时也触发
               （书翁/三尾狐类能力；气绝/离场仍不触发）
    """

    model_config = ConfigDict(extra="allow")

    when: str = "on_play"
    mode: Literal["interleaved", "atomic"] = "interleaved"
    timing: Literal["queue", "insert"] | None = None
    condition: dict[str, Any] | None = None
    steps: list[Step] = Field(default_factory=list)
    trigger_when_not_in_play: bool = False


class PlayMethod(BaseModel):
    """卡牌的一种使用方式（多择子选项，保留扩展空间）。

    多择牌仅保留核心使用方式、参数可变（thoughts.txt）：如爆能表示为
    PlayMethod(id="burst", param=2, ...)，param 为能量等数值参数，
    其数值可被效果增减（Phase 3 落地全局增减钩子）。
    每个选项可以拥有自己的费用/等级/卡牌类型/目标。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    param: int | None = None  # 方式参数（如爆能的能量值）；缺省 = 无参方式
    cost: int | None = None  # 费用绝对覆盖（缺省用卡牌基础费用）
    cost_delta: int = 0  # 在（覆盖后）费用上的增减
    level: int | None = None  # 等级要求覆盖
    card_type: str | None = None  # 卡牌类型覆盖（多择各选项可不同类型；Phase 3 战斗牌/形态牌落地前引擎不读取）
    target: TargetSpec | None = None  # 目标覆盖
    effects: EffectBlock | None = None  # 缺省 = 使用卡牌基础 effects
    text: str = ""


class CardDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    version: int
    name: str
    shikigami: int | None = None  # 所属式神 id；None = 中立牌；协战牌为两位所属中较小者
    shikigami2: int | None = None  # 协战牌：另一位所属式神 id（仅 card_type=reinforce 使用）
    card_type: str
    subtype: str | None = None  # 子类型：awaken=觉醒牌；保留扩展（如式神专属子类型）
    tags: list[str] = Field(default_factory=list)  # 自由标记；机制未实现前不放进数据，避免静默失效
    rarity: str | None = None  # 稀有度 R/SR/SSR（预留，抽卡/账号系统用）
    token: bool = False  # 衍生卡：对局中由系统/效果生成，不可编入卡组
    playable_when_defeated: bool = False  # 气绝时可用（与是否响应牌无关）
    level: int = 1  # 使用所需式神等级（中立牌无等级，忽略此字段）
    cost: int = 1  # 鬼火消耗
    form_power: int | None = None  # 形态牌结附时的基础力量（card_type=form 时使用）
    form_health: int | None = None  # 形态牌结附时的基础生命（card_type=form 时使用）
    keywords: list[str] = Field(default_factory=list)
    target: TargetSpec = Field(default_factory=TargetSpec)
    effects: EffectBlock  # 主效果块；空白占位卡可用空 steps，但不能省略该字段
    abilities: list[EffectBlock] = Field(default_factory=list)  # 觉醒牌的觉醒能力块（打出时替换式神能力）
    triggers: list[EffectBlock] = Field(default_factory=list)  # 卡牌触发器：游离触发块（when≠on_play），
    # 不依附在场式神，每次 emit 全库扫描匹配；修饰写入目标由写入动作（add_mod 等）指定
    temp_grants: list[EffectBlock] = Field(default_factory=list)  # 战斗牌专用：发起战斗时注册、
    # 绑定该次战斗的一次性触发（uses=1，战斗终止点移除未用者）
    methods: list[PlayMethod] = Field(default_factory=list)  # 使用方式（多择子选项）
    text: str = ""

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: int) -> int:
        if not 10_000_000 <= v <= 99_999_999:
            raise ValueError("卡牌 id 须为 8 位数字（式神 id 6 位 + 2 位卡序号）")
        return v

    @field_validator("version")
    @classmethod
    def _v_version(cls, v: int) -> int:
        return _check_version(v)


class ShikigamiDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    version: int
    name: str
    kind: Literal["shikigami", "summon"] = "shikigami"  # 式神（非召唤物）/ 召唤物
    faction: str = "无相"  # 派系：红莲/紫岩/青岚/苍叶/无相（对战中可被效果改变）
    origin: str | None = None  # 同源标识：原形/SP 等共享 origin，不能同时出战
    power: int  # 基础力量
    health: int  # 基础生命
    keep_buffs: bool = False  # 仅召唤物：离场后同名再召是否保留永久增减益
    ability: EffectBlock | None = None  # 被动；when 为事件名（不可用 on_play）
    text: str = ""

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: int) -> int:
        # 式神 6 位（1xxxyy）或召唤物 8 位；7 位非法
        if not (100_000 <= v <= 999_999 or 10_000_000 <= v <= 99_999_999):
            raise ValueError("式神 id 须为 6 位（1xxxyy）或 8 位（召唤物）；7 位 id 非法")
        return v

    @field_validator("version")
    @classmethod
    def _v_version(cls, v: int) -> int:
        return _check_version(v)
