# “增强”机制设计结论（触发器 / 监测 / 即时装配）

> 本文档归档 2026-07-24 前后多轮设计讨论的结论，是下一阶段实现的依据。
> 讨论过程中否决的路线及其理由一并记录，避免重复争论。

## 一、核心决策：“增强”不是机制，只是卡面话术

原版卡面上的“[增强]：{…}”涵盖了形态差异极大的一大类效果。经维护者逐类举例穷举后确认：
**不实现统一的“增强”机制**。实现层只有两种通用机制，卡面“增强”由数据/DIY DSL 编译到它们：

- **卡牌触发器（triggers）**：游离触发块——不依附任何在场式神的 `EffectBlock`（when/condition/steps），
  游戏开始时**按数据库全量注册**（覆盖生成牌、永久变形等情形），进入 `_collect` 的第三收集来源
  （式神能力之后、响应牌之前）。同样服务“手牌被动”等非增强效果。
- **实时监测（monitors）**：状态谓词 + 修饰列表。不触发、不存储——在**读取**（关键词判定、数值倍率）
  与**打出装配**（注入追加块、注册临时触发）时对当前状态实时求值。

## 二、写入三目标（触发器的修饰写到哪里）

“写到哪里”是**写入动作**的属性，而非触发块的属性。写入原语带 `to` 参数：

| 目标 | 存储 | 语义 |
|---|---|---|
| `hand` | 手牌中同名复制的 `card.mods` | 按实例隔离；之后才抽到的同名复制不受影响 |
| `persistent` | `state.card_mods[pi][card_id]` | 跨回合持久（“本局游戏每……”类） |
| `turn` | `state.turn_mods[pi][card_id]` | “本回合”类；回合开始整体清空，无需逐卡登记重置策略 |

## 三、即时装配模型

**结算时的效果 = 定义块 ⊕ 活跃修饰 的即时装配**：打出/读取那一刻，由
“共享定义 + persistent + turn + 命中的 monitors + 实例已有 mods”装配出本次实际效果；
装配产物用完即弃，**永不落库、永不复制/改写定义块**。

- 打出装配（物化快照）：卡牌离开手牌后、效果块结算前，把 persistent/turn 两 store 与命中
  monitors 的 keywords/pre_grants/grants 合并进该实例 `card.mods`；monitors 的 temp_grants 注册进状态。
  快照后结算过程中计数再变也不影响本次打出。
- 数值解析流水线：步骤参数 `{"enhance": true, "base": n}` → `base + mods["enhance"]`；
  damage 步骤最终值再乘命中 monitor 的 `amount_mult`（**先加后乘**——“伤害翻倍”作用于结算值而非基础值）。
- 关键词读取统一走 `_has_keyword`：`cdef.keywords ∪ mods["keywords_add"] ∪ 命中 monitors 的 keywords`。

## 四、修饰词汇表（mods 形数据，可扩展）

| 修饰 | 承载 | 生效点 |
|---|---|---|
| 数值叠加 | `mods["enhance"]: int`（写入原语可带 `cap`） | 步骤参数 `{"enhance": true, "base": n}` |
| 数值倍率 | monitor 的 `amount_mult` | `_run_step` damage 最终值 ×倍率 |
| 关键词 | `mods["keywords_add"]` / monitor 的 `keywords` | `_has_keyword`（瞬发判定等） |
| 定位追加块 | `mods["pre_grants"]/["grants"]` 索引 → `cdef.pre_grants/grants` | 主块 steps 前/后按索引结算 |
| 临时触发赋予 | `state.temp_grants: [{card_id, index, controller, uses}]` | `_collect` 展开为待触发块，结算后 uses-1，归零移除 |

## 五、概念层次（EffectBlock 地位不变）

- **EffectBlock 是效果定义的唯一单元**（when/condition/steps/mode/timing）：主效果、式神能力、
  卡牌触发器、追加块、将来的判定分支全都是它；数据定义、加载校验、共享不可变。
- 机制层只决定“哪些块、何时、以什么参数结算”；**块与块之间唯一的耦合是事件总线**
  （无块内嵌块、无分支语句）。
- 判定类机制（“执行判定（本身是事件），若成功：{执行额外块}”）=
  `judge` 原语（将来）发出 `on_judge` 事件 + 打出时把成功分支注册为一次性 temp_grant
  （when=on_judge, condition={result: success}）。

## 六、架构不变式

1. **卡牌实例身份**：`CardInstance` 是对局中卡牌对象的唯一身份。区域转换（手牌→场上实体→墓地→牌库）
   传递同一实例及其 `mods`；形态/幻境实体持有实例引用，离场时实体期间累积的特性写回实例
   （实体机制落地时实现，不变式现在确立）。
2. **战斗上下文对象化**：战斗牌结算创建 combat context（攻击者、战力、一次性护甲、免疫列表、来源卡）；
   嵌套攻击压栈/出栈。
3. **额外攻击的继承声明**：`launch_attack` 原语带 `inherit_context: bool`——
   共享本张战斗牌加成的额外攻击 = true，独立的额外攻击 = false，由卡牌数据显式声明。
4. **使用上下文入事件**：`on_card_played` payload 含 `play_from` / `play_method` / `triggered`，
   使用位置（手牌/牌库/凭空生成）与使用方式（主动/自动/多择）可作触发条件与监测谓词。
5. **效果对象不整体复制附着**（已否决，见第九节）。

## 七、讨论示例 → 机制映射表

| 卡面描述 | 映射 |
|---|---|
| 本局妖刀姬每消灭一个式神，此战斗牌+2力量 | trigger → `add_mod(to=persistent)`；打出时快照 |
| 本回合鸦天狗每移动一次，此战斗牌+2力量 | trigger → `add_mod(to=turn)`；回合开始清空 |
| （手牌中）敌方牌手回血时此牌伤害+1（最多+3） | trigger → `add_mod(to=hand, cap=3)`；按实例累积 |
| 敌方有破甲≥2的角色，此牌具有[瞬发] | monitor：谓词命中 → keywords=[fast] |
| 敌方牌库≤16，此牌伤害翻倍 | monitor：谓词命中 → amount_mult=2（先加后乘） |
| 己方式神全青岚，抽牌前先[占卜2] | monitor 命中 → 注入 pre_grants（改变执行流程） |
| 使用时慧明灯在战斗区，获得“战斗结束后各回3” | monitor 命中 → 注册 temp_grant（一次性触发） |
| 八尺琼勾玉战斗牌：先对结附者攻击 / 攻击后使己方结附者攻击 | temp/pre grants + `launch_attack`（inherit_context 区分是否共享战力；依赖战斗上下文，Phase 3） |
| 形态/幻境离场保留状态入墓、“洗回牌库保留特性” | 不变式 1：实例身份 + mods 写回 |
| 使用位置/方式作为增强条件 | 不变式 4：on_card_played payload |

## 八、数据 schema 草案（实现时以代码为准）

```yaml
# CardDef 新增字段
triggers:        # 卡牌触发器（CardTrigger = EffectBlock；when ≠ on_play）
  - when: on_shikigami_defeated
    condition: {victim_side: enemy, source_shikigami: 100101}
    steps: [{op: add_mod, to: persistent, key: enhance, amount: 1}]
monitors:        # 实时监测
  - condition: {exists: {pool: enemy_character, where: {fragile: {gte: 2}}}}
    keywords: [fast]
    amount_mult: 2        # 可选
    pre_grants: [0]       # 可选：索引指向 pre_grants
    grants: [0]           # 可选：索引指向 grants
    temp_grants: [1]      # 可选：打出时注册一次性触发
pre_grants: []   # 候选追加块（主块 steps 之前结算）
grants: []       # 候选追加块（主块之后 / 临时触发体）

# 写入原语（actions 注册表）
{op: add_mod, to: hand|persistent|turn, key: enhance, amount: 1, cap: 3}
{op: add_keyword, to: ..., keyword: fast}
{op: grant_effect, to: ..., index: 0, position: before|after}
```

条件迷你语言扩展：`{字段_shikigami: <式神id>}`（事件 Ref → 式神 id）；
状态谓词迷你语言：`exists` / `all`（pool + where 字段比较 gte/lte/eq）、
玩家标量（deck_count 等）、`shikigami_in_combat: <id>`、含气绝式神专用 pool。

## 九、已否决路线

- **统一“增强”机制**：四类增强 + 额外示例形态差异过大，统一机制沦为筐；改为触发器/监测的复合。
- **效果对象整体复制附着**（增强时复制 EffectBlock 改写后挂到实例）：状态冗余、与 db 定义分叉、
  序列化/回放负担、DIY 校验须面对运行期变体。即时装配覆盖全部示例，无上述成本。
- **数值-only 注入**（v2 方案）：无法表达关键词获得、追加效果、流程变更，被维护者示例否决。

## 十、下一阶段实施范围

在本地热座 CLI 中实现现有 4 式神 × 8 卡的**原版完整效果**：

1. 战斗上下文对象化与 `launch_attack`（不变式 2/3）；
2. 形态能力与形态实体（含不变式 1 的实例写回）；
3. 暂未展开的关键字/机制（随卡牌需要逐个落地，遇新机制先与维护者确认）；
4. 本文档的 triggers / monitors / 装配管线；
5. **CLI 修饰状态显示**（手牌/场上对象的 mods、临时触发等；为后期 UI 客户端打底——
   显示数据应来自同一状态读取点，避免 CLI 与 UI 两处逻辑分叉）。
