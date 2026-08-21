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
SUBTYPES = frozenset({"awaken"})  # 通用子类型：awaken=觉醒牌
# 专属子类型（维护者定案 2026-08）：子类型 → 所属式神 id；只能出现在所属式神的牌上
# （loader 校验）。首个 = quest 委托（三目 100404 的衍生牌家族）。
EXCLUSIVE_SUBTYPES: dict[str, int] = {"quest": 100404, "talisman": 100407}
# talisman=符咒（御馔津 100407 的法术牌家族：驱魔符/封魔符/破魔符——爆能3转化
# 战斗牌、奉祝之愿账本、狐狩界瞬发光环均按本子类型过滤）
# 生成即替换（tag gen_weekday_quest 的卡）：将要生成该 id 的牌时（含牌库初始化），
# 改为生成当天星期几对应的牌（周一=列表[0]…周日=[6]；日常委托 → 今日委托壹-柒）。
WEEKDAY_GEN_REPLACE: dict[int, tuple[int, ...]] = {
    10040402: (10040455, 10040456, 10040457, 10040458, 10040459, 10040460, 10040461),
}
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
    "critical",                 # 暴击（攻击造成的战斗伤害翻倍——kind=combat 攻击事件
    #                             ×2，反击不翻倍；伤害管线[暴击]时机=扣减生命前2读取，破魔符授予）
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
    # ---- 能力伪关键字（式神 def / 觉醒牌 keywords 携带，引擎读取时求值；卡面不出现）----
    "power_if_field",           # 若你有幻境 +1 力量（泷夜叉姬基础）
    "power_per_field",          # 你每有一个幻境 +1 力量（觉醒·泷夜叉姬）
    "power_if_shield",          # 有护甲时 +1 力量（久次良基础；白骨之盾"获得基础能力"授予通道）
    "power_equal_shield",       # 力量 = 当前护甲（觉醒·久次良；覆写口径）
    "power_eq_health",          # 力量 = 当前生命（觉醒·人面树；覆写口径同 power_equal_shield）
    "heal_defeated_countdown",  # 可以对气绝式神恢复生命，若如此做改为使其气绝倒计时 -1
    #                             （樱花妖基础/觉醒共用通道；卡面不出现）
    "damage_defeated_countdown",  # 可以对气绝式神造成伤害，若如此做改为使其气绝倒计时 +1
    #                             （觉醒·樱花妖通道；卡面不出现）
    "replace_action",           # 引擎级能力伪关键字（带 `:灵咒名` 参数，如
    #                             replace_action:迟钝）：该式神出击或使用其战斗牌时改为
    # 结附指定灵咒——完全替换动作（不发起攻击/不进战斗流程），鬼火/瞬发/出击次数
    # 照常消耗；战斗牌其余文本效果照常结算、仅战斗本身跳过（跳跳哥哥基础/觉醒
    # 共用通道；卡面不出现）。loader 关键字校验按冒号前缀匹配
    # （原 field_stack/field_ability_stack 伪关键字作废：辉夜姬叠加改为能力块
    #  field_merge 通道——定案(6)，见 rules.md 第三十一章）
    # ---- 效果授予伪关键字（卡牌效果授予其他式神，引擎读取时求值；卡面不出现）----
    "combat_base_health",       # 以其自身当前生命（而非力量）造成战斗伤害（神木庇佑授予）
    "assault_any_target",       # 出击时可以指定攻击任何其他角色（飘零之舞；_cmd_assault 分支）
    "friendly_combat_heal",     # 攻击己方角色时改为使其恢复等量于伤害的生命（飘零之舞）
    "virtual_combat",           # 鬼斩触发判定时视同处于战斗区（复仇之刃形态授予鬼切
    #                             ——holder_in_combat 条件读取；卡面不出现）
    "inv_trigger_echo",         # 持有者触发灵咒能力时额外复制一次该能力块（刀鸣之刃
    #                             形态授予鬼切——_collect_abilities 灵咒能力块收集处双发；
    #                             卡面不出现）
    "power_on_enemy_turn",      # 引擎级伪关键字（带 `:N` 参数，如 power_on_enemy_turn:3）：
    #                             敌方回合期间该式神 +N 力量（散华之刃；_refresh_stat_auras
    #                             动态读取，按冒号前缀匹配；卡面不出现）
})  # 机制未实现的关键词不放进数据，避免静默失效（rules.md:270）。

# 能力伪关键字集合：觉醒替换基础能力时按本集合换绑（移除基础式神的、授予觉醒牌的；
# 气绝不清——永久类别随觉醒状态保留，读取处以 in_play 门控）。engine 觉醒点引用。
ABILITY_PSEUDO_KEYWORDS = frozenset({
    "power_if_field", "power_per_field", "power_if_shield", "power_equal_shield",
    "power_eq_health", "heal_defeated_countdown", "damage_defeated_countdown",
    "replace_action",
})  # replace_action 带 `:灵咒名` 参数（replace_action:迟钝），换绑按冒号前缀匹配
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
    priority: int = 1  # 同事件 insert 批次的结算优先级（升序；同优先级保持收集序）。
    # 约定（定案(7)，伤害事件"护甲计算后"批次）：1=「伤害改为非伤害」类（竹取物语/
    # 新月之哀/日轮之城 redirect_to_field）；2=「伤害目标转移」类（血蝠之盾挂账为
    # 引擎内建优先级 2 段）。改非伤害结算后原事件终止时，优先级≥2 的转移不再处理
    condition: dict[str, Any] | None = None
    steps: list[Step] = Field(default_factory=list)
    trigger_when_not_in_play: bool = False
    trigger_when_defeated: bool = False
    countdown: int | None = None  # 非 None = 倒计时能力块（不作事件监听）：初值=countdown，
    # 归零时执行 steps（式神级倒计时框架，core/engine.py；形态牌倒计时仍用 CardDef.countdown）
    once: bool = False  # 仅倒计时块有意义：一次型——归零生效后不重置；灵咒倒计时块
    # （InvocationDef.abilities 内）生效后连同灵咒本体一并移除（迟钝"生效后移除"）
    luck: int | dict[str, Any] | None = None  # 运势门控：触发后对控制者做
    # 运势判定，按结果决定是否结算 steps。int = 成功所需点数 X（成功才结算）；
    # {"x": X, "on": "fail"} = 判定失败才结算（家内安全/和气满满）。判定者默认控制者；
    # 并行入队/同步推进由引擎负责（core/engine.py 运势管线）


class InvocationDef(BaseModel):
    """灵咒定义（灵咒框架，docs/rules.md「灵咒」章；沧海刀鸣预备）。

    灵咒是"结附于式神或卡牌上的具名效果实体"，由 attach_invocation op 结附：
    - power/health：效果类灵咒的身材增减益——结附期间生效（引擎实现为类光环层：
      结附时刻快照入运行时条目，eff_power/max_health 读取时实时合计；不借
      temp 修正承载——被"日出有曜"类清除临时修正后仍立即继续生效（维护者定案），
      灵咒移除（气绝/离场/唯一性）即失效，无双重扣减）。
    - abilities：能力类灵咒的触发能力块（结附期间作为该式神的额外能力参与
      _collect_abilities 收集；进场序号 = 结附时刻，随灵咒移除而失效）。
    - draw_trigger：结附在卡牌上的灵咒"抽到触发"块——该牌从牌库经抽牌动作
      入手时入队结算（来源牌手为控制者），结算后移除；检索等非抽牌入手静默移除。
    - unique：唯一性——"unique"=[唯一]：结附后移除双方全场（式神+手牌/牌库中的
      卡牌）同源同名灵咒；"shikigami_unique"=[式神唯一]：仅移除该式神上同源同名；
      "none"=不唯一。同源 = 来源所属牌手相同；新结附的灵咒自身不被移除。
      可被持有方 PlayerState.ext["inv_override"][灵咒名]["unique"] 覆写（祈愿之翼
      "失去[唯一]但效果不能叠加" → shikigami_unique）。
    - keywords：结附期间授予持有者的关键字（移除即失效按实例撤销）；"stun" 特判为
      眩晕（挂 stuns 的 kind="invocation" 条目，不参与回合批次过期清理，随灵咒移除解除）。
    - 运行时条目附加键（engine.attach_invocation 维护，见 ShikigamiState.invocations）：
      uid/bonus（数值增强，同源同名再结附继承、气绝离场重置）/mod_power/mod_health
      （持有方 ext["inv_mod"] 修饰层）。
    - version：快照日期（resolve_latest/at_date 注入；测试直接注入时缺省 0，
      at_date 判定视为任意日期可用）。
    """

    model_config = ConfigDict(extra="allow")

    name: str  # 灵咒名（唯一性判定的同名键；展示用）
    unique: Literal["none", "unique", "shikigami_unique"] = "none"
    power: int = 0
    health: int = 0
    keywords: list[str] = Field(default_factory=list)
    abilities: list[EffectBlock] = Field(default_factory=list)
    draw_trigger: EffectBlock | None = None
    text: str = ""  # 卡面原文（逐字，card_data_raw.md 对应条目引号内文本）
    version: int = 0  # 版本快照日期（loader 注入；0 = 测试直注入，at_date 恒可用）


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
    card_type: str | None = None  # 卡牌类型覆盖（多择各选项可不同类型；爆能转化战斗牌
    # = combat——御馔津符咒牌[爆能3]通道，engine._cmd_play_card 按生效类型路由结算；
    # 类型转化时方式 effects 语义改为"整体替换"基础 effects（缺省 None = 空块——
    # 转化后不再结算原法术效果），不再走爆能"追加"语义）
    power: int = 0  # 战斗牌身材参数：转化为战斗牌时的战力（combat_card_stats 叠加）
    shield: int = 0  # 同上：一次性护甲
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
    subtype: str | None = None  # 子类型：awaken=觉醒牌（通用）；quest=委托（专属子类型，
    # 仅所属式神的牌可用——登记表 db/schema.py EXCLUSIVE_SUBTYPES，loader 校验归属）
    awaken_power: int = 0  # 觉醒牌：永久身材增益（力量），"觉醒后"延时时机之后授予
    awaken_health: int = 0  # 觉醒牌：永久身材增益（生命），同上（thoughts.txt 法术觉醒流程）
    tags: list[str] = Field(default_factory=list)  # 自由标记；机制未实现前不放进数据，避免静默失效
    rarity: str | None = None  # 稀有度 R/SR/SSR（预留，抽卡/账号系统用）；
    # 衍生牌（token=true）无稀有度——rarity 须缺省（维护者定案，loader 校验）
    token: bool = False  # 衍生卡：对局中由系统/效果生成，不可编入卡组
    playable_when_defeated: bool = False  # 气绝时可用（与是否响应牌无关）
    only_when_defeated: bool = False  # 仅在所属式神气绝时可用（心即归处；主动使用与响应均门控，
    # 与 playable_when_defeated 配对使用——后者放宽气绝可用、前者收紧存活不可用）
    level: int = 1  # 使用所需式神等级（中立牌无等级，忽略此字段）
    cost: int = 1  # 鬼火消耗
    form_power: int | None = None  # 形态牌结附时的基础力量（card_type=form 时使用）
    form_health: int | None = None  # 形态牌结附时的基础生命（card_type=form 时使用）
    intensity: int | None = None  # 幻境牌耐久（正整数；card_type=field 时必填——
    # 使用后"召唤幻境"：实体以此耐久入所属牌手幻境队列）
    field_front: bool = False  # 幻境进场置于幻境队列队首（缺省 False = 队尾；规范"零"条）
    field_keywords: list[str] = Field(default_factory=list)  # 幻境实体关键字（card_type=field
    # 时召唤拷贝到 FieldState.keywords——贯通/帷幕等幻境语义；与卡牌自身的使用关键字分离）
    keywords: list[str] = Field(default_factory=list)
    target: TargetSpec = Field(default_factory=TargetSpec)
    target2: TargetSpec | None = None  # 第二选择目标（麓鸣·灭型双 choose 卡：
    # 出牌指令 cmd["target2"] 校验/传入，ctx.chosen = [主目标, 第二目标]；step 目标
    # 用 {kind: choose, chosen_index: n} 按序取——见 core.targets.resolve）
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
    conditional_mods: list[dict[str, Any]] = Field(default_factory=list)
    # 动态实例修饰：装配点（engine._materialize——打出付费后/效果结算前、生成入手）
    # 按条目条件把 mods 键写入该实例（牙牙我们走[增强]身材 form_power_delta/
    # form_health_delta、汤盆冲撞[增强]伤害翻倍 double_damage）。条目结构：
    # {"mods": {键: 值}, 条件键...}，条件键用条件迷你语言（控制者视角、空事件
    # 求值；enemy_deck_le = 敌方牌库张数 ≤ n）
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
    kind: Literal["shikigami", "summon", "transform", "replace"] = "shikigami"  # 式神（非召唤物）/ 召唤物 / 变形物 / 替换物
    # （变形物/替换物：视同召唤物类不入构筑池/测试卡组。变形物由 transform 动作变入，
    # 带快照、untransform/气绝前2 还原；替换物由 replace 动作换入，无快照、不可还原，
    # ext["replace_owner"] 记原式神 id、放行原式神卡牌——觉醒·番茄类）
    faction: str = "无相"  # 派系：红莲/紫岩/青岚/苍叶/无相（对战中可被效果改变）
    origin: str | None = None  # 同源标识：原形/SP 等共享 origin，不能同时出战
    power: int  # 基础力量
    health: int  # 基础生命
    keywords: list[str] = Field(default_factory=list)  # 先天关键字（如贯通）：
    # 入场即具有，按永久类别入列（气绝不清除、复活自动重新获得；core/setup.py 初始化）
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
