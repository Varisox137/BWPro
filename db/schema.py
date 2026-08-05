"""卡牌/式神静态数据的 schema 与兼容纪律。

1. id 号段约定（loader 会校验一致性；预留 GUI/美术资产——异画位区分同一数据的不同卡面）：
   - 式神：6 位数字 1avvss（'1' + 1 位异画位 a（'0' = 默认异画）+ 2 位版本资料包 vv
     + 2 位包内式神序号 ss）
   - 卡牌：8 位数字 1avvvvcc（6 位式神 id + 2 位卡牌序号 cc，异画位在式神段内）：
     可构筑卡牌 01-08；衍生卡（token）从 51 开始递增；衍生物（召唤物）从 99 开始递减；
     协战牌双式神从属，规则见 docs/rules.md 第十四/十五章。末两位的分配约定保持不变。
   - 中立牌（无从属式神，实质为系统/效果生成的衍生卡）：8 位数字 9avvvvvv
     （'9' + 1 位异画位 + 6 位数字，默认异画自 90999999 开始递减分配），无等级
2. 平衡性多版本：yaml 顶层只保留 id / name / versions 三项，全部规则数据存放在
   versions.history 的版本快照中——每条 = date（8 位日期 YYYYMMDD）+ 该版本的
   全部完整数据（完整快照，不按差量记录），首条目的 date = 发布日期；
   versions.best 为维护者手动标记的"历史最强"版本日期（仅元数据，解析不使用）。
   version 字段不入 yaml：加载/环境解析时 = 所取快照的 date（db/versioning.py）。
   快照不得含 id/name；卡牌的 shikigami 由 id 推导注入（前六位；中立牌 id 首位 9
   为 None），不入数据；cost 默认 1（非 1 才写入）。
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
    "pierce_armor",             # 穿刺变体（伪关键字）：造成伤害前仅移除受伤者护甲、不动屏障
    #                             （碎岩 20191212；卡面为描述文本，不出现括号关键字）
    "remote",                   # 远程
    "unyielding", "haste",      # 不屈 / 迅捷
    "barrier",                  # 屏障
    "enraged",                  # 激怒（状态：出击锁定 + 发起战斗时移除）
    "keep_attack_buffs",        # 引擎级：攻击后到期强化不因攻击移除（残心；卡面不出现）
    "lifesteal",                # 吸血（机制见 docs/rules.md 伤害流程；造成伤害后为牌手恢复等量生命）
    "hunt",                     # 追猎（有目标的战斗：出击/战斗牌可任选合法敌方式神为被攻击者）
    "direct",                   # 直击（确定目标前1：无目标的战斗被攻击者改为敌方牌手）
    "veil",                     # 帷幕（不能成为敌方出击/用牌的合法目标）
    "lethal",                   # 必杀（造成伤害后令受伤者延时结算气绝）
    "inspire",                  # 鼓舞（下一次出击获得战力/护甲——效果以 basic_boost 出击加成通道结算）
    "charge",                   # 充能（己方回合开始时能量 +1，上限 10；能量见
    #                             ShikigamiState.energy 与 engine._gain_energy/_spend_energy）
    "rebound",                  # 弹回（卡牌级：使用后回手而非入墓）
    "blessing",                 # 庇佑（一次性：抵消一次敌方结附的灵咒或敌方造成的非战斗伤害，
    #                             抵消后失去；灵咒半侧随灵咒机制引入）
    "damage_to_fragile",        # 引擎级伪关键字：对无破甲角色造成的伤害转化为等量破甲
    #                             （清姬基础/觉醒共用通道，永久类别死亡不清；卡面不出现）
    "extra_orb_cost",           # 引擎级伪关键字：该式神出击/使用其战斗牌需额外消耗 1 点鬼火
    #                             （跳跳妹妹基础能力通道，[迅捷]/[瞬发]/不消耗鬼火时全免；卡面不出现）
})  # 机制未实现的关键词不放进数据，避免静默失效（rules.md:270）。
# 语义约定：战斗牌 keywords（fast/trigger 除外）= 本次战斗中授予攻击者；
# 形态牌 keywords（fast/trigger 除外）= 结附期间授予式神。授予均按关键字的
# 天然持久性类别入列（见 core.model.ShikigamiState 与 docs/terminology.md）。
FACTIONS = frozenset({"红莲", "紫岩", "青岚", "苍叶", "无相"})  # 无相 = 无派系
FACTION_COLORS = {"红莲": "red", "紫岩": "purple", "青岚": "blue", "苍叶": "green", "无相": "white"}  # Phase 4 UI 展示预留，代码侧暂无消费方
RARITIES = frozenset({"R", "SR", "SSR"})  # 良 / 优 / 极（抽卡/账号系统预留，见 thoughts.txt）
# 觉醒牌 = 任意主类型 + tags 含 "awaken"；保留字面量即可，无需单独常量。

NEUTRAL_PREFIX = 9  # 中立牌 id 首位（9avvvvvv：9 + 1 位异画位 + 6 位数字）


def check_version_date(v: int) -> int:
    """8 位数字日期（YYYYMMDD）校验；db/versioning.py 的版本时间线校验同用。"""
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
    condition: dict[str, Any] | None = None  # Step 级条件：结算时以条件迷你语言求值，不满足则跳过该步
    # 其余字段（amount / count / ...）按 op 需要原样保留在 model_extra


class EffectBlock(BaseModel):
    """一段效果：何时触发 + 如何结算 + 依次执行哪些动作。

    - when:    on_play 表示打出时；否则为核心/自定义事件名（被动、响应牌用）
    - mode:    interleaved=步骤之间允许其它效果结算 / atomic=不允许
    - timing:  作为触发效果时的结算时机覆盖：insert=立即插入 / queue=入队延迟；
               None（默认）= 跟随该事件的时机类别（core.events.EVENT_TIMING）
    - trigger_when_not_in_play: 允许在式神未升级（0 级未在场）时也触发
               （书翁/三尾狐类能力；气绝/离场仍不触发）
    - trigger_when_defeated: 允许在式神气绝时也触发
               （觉醒·犬神"己方回合结束时复活犬神"类；离场仍不触发）
    """

    model_config = ConfigDict(extra="allow")

    when: str = "on_play"
    mode: Literal["interleaved", "atomic"] = "interleaved"
    timing: Literal["queue", "insert"] | None = None
    condition: dict[str, Any] | None = None
    steps: list[Step] = Field(default_factory=list)
    trigger_when_not_in_play: bool = False
    trigger_when_defeated: bool = False
    countdown: int | None = None  # 非 None = 倒计时能力块（不作事件监听）：初值=countdown，
    # 归零时执行 steps（式神级倒计时框架，core/engine.py；形态牌倒计时仍用 CardDef.countdown）
    luck: int | dict[str, Any] | None = None  # 运势门控：触发后对控制者做
    # 运势判定，按结果决定是否结算 steps。int = 成功所需点数 X（成功才结算）；
    # {"x": X, "on": "fail"} = 判定失败才结算（家内安全/和气满满）。判定者默认控制者；
    # 并行入队/同步推进由引擎负责（core/engine.py 运势管线）


class PlayMethod(BaseModel):
    """卡牌的一种使用方式（多择子选项，保留扩展空间）。

    多择牌仅保留核心使用方式、参数可变（thoughts.txt）：如爆能表示为
    PlayMethod(id="burst", param=2, ...)，param 为能量等数值参数，
    其数值可被效果增减（Phase 5 落地全局增减钩子）。
    每个选项可以拥有自己的费用/等级/卡牌类型/目标。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    param: int | None = None  # 方式参数（如爆能的能量值）；缺省 = 无参方式
    cost: int | None = None  # 费用绝对覆盖（缺省用卡牌基础费用）
    cost_delta: int = 0  # 在（覆盖后）费用上的增减
    level: int | None = None  # 等级要求覆盖
    card_type: str | None = None  # 卡牌类型覆盖（多择各选项可不同类型；Phase 5 战斗牌/形态牌落地前引擎不读取）
    target: TargetSpec | None = None  # 目标覆盖
    effects: EffectBlock | None = None  # 缺省 = 使用卡牌基础 effects
    # 爆能（不夜之火包）：energy_cost = 该方式的能量消耗——int 为定值爆能（爆能2/3/4…），
    # "all" 为爆能X（消耗全部能量；0 能量时不可选）；带 energy_cost 的方式的 effects
    # 语义 = 追加到基础 effects 之后（非覆盖），消耗在结算开始点支付（engine._cmd_play_card）
    energy_cost: int | str | None = None
    # 方式授予关键字（不夜之火包 森之力"[爆能2]：获得[瞬发]"）：选定该方式后本次使用
    # 临时授予该牌（装配在瞬发/费用判定之前，结算后移除——engine._cmd_play_card）
    keywords: list[str] = []
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
    awaken_power: int = 0  # 觉醒牌：永久身材增益（力量），"觉醒后"延时时机之后授予
    awaken_health: int = 0  # 觉醒牌：永久身材增益（生命），同上（thoughts.txt 法术觉醒流程）
    tags: list[str] = Field(default_factory=list)  # 自由标记；机制未实现前不放进数据，避免静默失效
    rarity: str | None = None  # 稀有度 R/SR/SSR（预留，抽卡/账号系统用）
    token: bool = False  # 衍生卡：对局中由系统/效果生成，不可编入卡组
    playable_when_defeated: bool = False  # 气绝时可用（与是否响应牌无关）
    only_when_defeated: bool = False  # 仅在所属式神气绝时可用（心即归处；主动使用与响应均门控，
    # 与 playable_when_defeated 配对使用——后者放宽气绝可用、前者收紧存活不可用）
    level: int = 1  # 使用所需式神等级（中立牌无等级，忽略此字段）
    cost: int = 1  # 鬼火消耗
    form_power: int | None = None  # 形态牌结附时的基础力量（card_type=form 时使用）
    form_health: int | None = None  # 形态牌结附时的基础生命（card_type=form 时使用）
    keywords: list[str] = Field(default_factory=list)
    target: TargetSpec = Field(default_factory=TargetSpec)
    effects: EffectBlock  # 主效果块；空白占位卡可用空 steps，但不能省略该字段。
    # 形态牌的 effects 块 = 进场时效果（打出结附时结算，可用卡牌的 choose 目标）
    alt_effects: EffectBlock | None = None  # "变为"（吾即正义）：持久 store 置位
    # transformed 后，本局该同名卡打出统一改用本块（含生成的；装配/打出读取点见 engine）
    alt_remove_keywords: list[str] = Field(default_factory=list)  # "变为"后失去的关键字（如 fast 瞬发）
    cost_zero_if: dict[str, Any] | None = None  # 动态费用：{"ext": key} 对应
    # PlayerState.ext 键非 0 时费用为 0（金风流羽：feather_used_turn）；
    # {"level_ge": n} 卡牌所属式神当前等级 ≥ n 时费用为 0（心身炼磨"犬神 3 级不耗鬼火"）
    conditional_keywords: list[dict[str, Any]] = Field(default_factory=list)
    # 动态关键字：满足条件的条目把 keyword 加入实际关键字（读取点 _card_keywords，
    # 对手中/生成的一切副本生效）。条目条件（可组合）：level_ge=卡牌所属式神当前等级 ≥ n
    # （心身炼磨"犬神 2 级获得[瞬发]"）；if_alive=所属式神在场未气绝（桃华灼灼）
    abilities: list[EffectBlock] = Field(default_factory=list)  # 觉醒牌的觉醒能力块（打出时替换式神能力）/ 形态牌的形态能力块（结附期间生效）
    countdown: int | None = None  # 形态牌倒计时初始值（结附时授予式神，离场/气绝移除）
    countdown_effects: EffectBlock | None = None  # 倒计时归零时执行的效果块（重置为初始值后执行）
    triggers: list[EffectBlock] = Field(default_factory=list)  # 卡牌触发器：游离触发块（when≠on_play），
    # 不依附在场式神，每次 emit 全库扫描匹配；修饰写入目标由写入动作（add_mod 等）指定
    response: EffectBlock | None = None  # 响应牌效果块覆盖：主动使用效果与响应效果结构
    # 不同时（魔音扰心：主动=登记延迟无效化，响应=直接无效化当前用牌），响应收集/复查/
    # 结算改读本块；缺省（None）用 effects
    options: list[int] = Field(default_factory=list)  # 协战牌（card_type=reinforce）：
    # 子选项 token 卡 id，有序（[0]=主式神侧子卡，[1]=副式神侧子卡）；打出时 cmd.choice 选择，
    # 生成对应 token 并视作从手牌使用，主牌离手移除（不进墓地）
    play_condition: dict[str, Any] | None = None  # [条件] 使用前提（福满乾坤）：以条件迷你语言
    # 对控制者求值，不满足则任何方式都不能使用（主动/响应/自动使用统一校验；CLI 可用性显示置灰）
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
        return check_version_date(v)


class ShikigamiDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    version: int
    name: str
    kind: Literal["shikigami", "summon", "transform"] = "shikigami"  # 式神（非召唤物）/ 召唤物 / 变形物
    # （变形物：视同召唤物类不入构筑池/测试卡组；由 transform 动作变入，untransform/气绝前2 还原）
    faction: str = "无相"  # 派系：红莲/紫岩/青岚/苍叶/无相（对战中可被效果改变）
    origin: str | None = None  # 同源标识：原形/SP 等共享 origin，不能同时出战
    power: int  # 基础力量
    health: int  # 基础生命
    keywords: list[str] = Field(default_factory=list)  # 先天关键字（如贯通）：
    # 入场即具有，按永久类别入列（气绝不清除、复活自动重新获得；core/setup.py 初始化）
    keep_buffs: bool = False  # 仅召唤物：离场后同名再召是否保留永久增减益
    no_attack: bool = False  # 仅召唤物/衍生物类：不能发动攻击（冰墙；出击校验与
    # 效果发起的额外攻击 launch_attack 同拦截）
    wip: bool = False  # 半成品式神（仅基础数据/卡牌未齐）：不进构筑可选池与测试卡组
    ability: EffectBlock | None = None  # 被动；when 为事件名（不可用 on_play）
    abilities: list[EffectBlock] = Field(default_factory=list)  # 多能力块（含倒计时能力块）；
    # 字段只增不改：旧 ability 字段并入 abilities[0] 读取（见 all_abilities）
    text: str = ""

    @property
    def all_abilities(self) -> list[EffectBlock]:
        """基础能力块列表：旧 ability 字段并入 abilities[0] 读取（向后兼容）。"""
        return ([self.ability] if self.ability is not None else []) + list(self.abilities)

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
        return check_version_date(v)
