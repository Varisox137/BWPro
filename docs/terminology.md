# 术语表（中文 ↔ 代码标识）

代码与数据库中的命名以此表为准。状态：✅ 已统一 / 🔧 预留（数据可携带，机制未实现） / ❓ 待确认（见 questions.md 对应编号）。

## 核心概念

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 牌手 | `player` / `PlayerState` | 局内参战实体：有生命/护甲、可被指定为目标 | ✅ |
| 玩家（账号） | （Phase 2 服务端概念） | 参与对局的账号/连接，不进入 GameState | 🔧 |
| 式神（非召唤物） | `shikigami` | `ShikigamiDef.kind = "shikigami"` | ✅ |
| 召唤物 | `summon` | `kind = "summon"`；气绝即离场、不可升级、入场 1 级（暂定）、生成即进入战斗区 | ✅ |
| 实体 | entity / `ShikigamiState` | 局内式神或召唤物；记录 `home_slot`（准备区编号 1-4，召唤物 None） | ✅ |
| 气绝 | `defeated` | `ShikigamiState.defeated`；倒计时后复活 | ✅ |
| 濒死 | `dying` | 生命 ≤ 0 但气绝事件尚未结算（伤害流程扣减生命后先标记，气绝时清除）：不受伤害/治疗、不进随机与选择目标池、不能再次被消灭；能力照常（in_play 不变）、可以攻击 | ✅ |
| 离场 | `despawned` | 召唤物气绝或被移动即离场（不视为移动、非气绝、不进复活流程） | ✅ |
| 复活 | `revive` | `revive_countdown` 归零后满血回场 | ✅ |
| 升级 | `upgrade` | 指令；`PlayerState.upgrades` 为本回合剩余升级机会 | ✅ |
| 等级（勾玉） | `level` | 1 至 `config.max_level`；0 级 = 未在场 | ✅ |
| 鬼火 | `orb` | 出牌/出击费用；己方回合开始重置，回合间不清零 | ✅ |
| 出击 | `assault` | 指令；耗 1 鬼火 + 每回合唯一出击次数（`assaults_left`），驻留战斗区 | ✅ |
| 移动 | `move` | 指令；入战斗区不攻击；战斗区召唤物被移动 = 直接离场 | ✅ |
| 战斗区 | combat zone / `combat_index` | 每方至多 1 式神驻留；己方回合开始退回准备区 | ✅ |
| 准备区 | bench | 非战斗区式神所在；编号见 `home_slot` | ✅ |

## 区域与卡牌流转

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 牌库 | `deck` | 区域 | ✅ |
| 手牌 | `hand` | 区域 | ✅ |
| 墓地 | `graveyard` | 区域（UI 不可见） | ✅ |
| 除外区 | `exile` | 预留标准区域 | 🔧 |
| 弃牌 | `discard` | `discard` 动作：弃掉手牌中谓词匹配的牌（所属式神/全部，可限张数），进入墓地 | ✅ |
| 移除 | `remove` | 移出游戏（如孟婆），与弃牌区分 | 🔧 |

## 属性与修正

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 生命 | `health` | `base_health + perm_health` 为上限 | ✅ |
| 力量 | `power` | `base_power + perm_power + temp_power` = `eff_power` | ✅ |
| 护甲 | `shield` | 被伤害优先消耗；己方回合开始清除 | ✅ |
| 破甲 | `fragile`（shield 负值） | 与护甲合并为单一有符号 `shield`（>0 护甲 / <0 破甲）；变化事件以 kind 参数区分方向（rules.md 第六章）：减少只扣已有同向值、获得先抵消反向再盈余同向；受伤时每点破甲使伤害 +1（伤害流程批次 4，贯通修正跳过、穿刺不动）；回合开始双向清除（keep_shield 仅保正值） | ✅ |
| 战力 | `combat_power` | 一次性的战斗伤害增加：战斗牌/响应战斗牌授予，战斗终止点核销（响应插入的经 `_battle_power` 挂账） | ✅ |
| 乏力 | `weak` | 战力的负向对应 | 🔧 |
| 永久修正 | `perm_power` / `perm_health` | 气绝后复活保留 | ✅ |
| 临时修正 | `temp_power` | 气绝时清除（临时/永久的区分 = 复活能否保留）；光环类 Phase 3 | ✅ |
| 攻击后到期强化 | `attack_buffs` / `attack_buff`（动作） | 挂账式临时强化（临时力量 + 授予关键字）：自身作为攻击者的战斗终止点核销（rules.md:176"直到攻击后"）；气绝清空 | ✅ |
| 护甲保留 | `keep_shield` | `ShikigamiState.keep_shield`：护甲不再于己方回合开始移除（觉醒·兵俑） | ✅ |

## 卡牌数据

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 法术牌 | `spell` | card_type | ✅ |
| 战斗牌 | `combat` | card_type | 🔧 Phase 3 |
| 形态牌 | `form` | card_type | 🔧 Phase 3 |
| 幻境牌 | `field` | card_type（预留） | 🔧 |
| 协战牌 | `reinforce` | card_type（预留；暂不考虑） | 🔧 |
| 觉醒牌 | `subtype = "awaken"` | **不是主类型**：任意 card_type + subtype（rules.md:502）；打出后替换式神能力并发出 `on_awakened` | ✅ |
| 觉醒（状态） | `awakened` | `ShikigamiState.awakened` = 觉醒牌 id；能力改读该牌 `abilities` 块；气绝/复活保留 | ✅ |
| 觉醒能力 | `abilities` | `CardDef.abilities`：觉醒牌携带的能力块（替换式神基础能力） | ✅ |
| 形态能力 | `abilities`（形态牌） | 形态牌携带的能力块：结附期间生效（与觉醒能力并存，觉醒替换不覆盖；如风符·瞬的回合结束自毁） | ✅ |
| 标签 | `tags` | 自由字符串标记（觉醒、式神专属标记等） | ✅ |
| 稀有度 | `rarity` | R/SR/SSR（良/优/极；抽卡/账号系统预留） | 🔧 |
| 卡包 | `cardpack` | 式神所属版本资料包，即 id 的 vv 段（式神 1avvss / 卡牌 1avvvvcc） | ✅ |
| 异画 | alt art（id 的 a 位） | 式神/卡牌/中立牌 id 的第 2 位（'0' = 默认卡面）；同一数据的不同卡面共享规则数据，为 GUI/美术资产预留 | 🔧 |
| 派系 | `faction` | 红莲 red / 紫岩 purple / 青岚 blue / 苍叶 green / 无相 white（`FACTION_COLORS`） | ✅ |
| 同源 | `origin` | 原形/SP 共享 origin，不能同时出战 | ✅ |
| 衍生卡 | `token` | 对局中生成，不可入卡组（序号从 51 开始递增） | ✅ |
| 衍生物 | （kind=summon 的衍生） | 序号从 99 开始递减；必须有从属式神 | ✅ |
| 数据 id | `id` | db 数据与局内对象的数据标识（CardInstance.id / ShikigamiState.id） | ✅ |
| 对象 id | `uid` | 局内对象引用标识（CardInstance.uid；生成物亦发 uid） | ✅ |
| 中立牌 | neutral（`shikigami=None`） | id 9avvvvvv（9 + 异画位 + 6 位数字，自 999999 递减）、无等级、系统/效果生成 | ✅ |
| 使用位置 | `play_from` | play_card 参数，默认 hand，任意区域可扩展 | ✅ |
| 使用方式 | `play_method` / `PlayMethod` | 多择子选项；仅保留核心方式、参数可变（`param`，如爆能{2}） | ✅ |
| 气绝时可用 | `playable_when_defeated` | 卡牌字段；与是否响应牌无关 | ✅ |
| 实例修饰 | `mods` | CardInstance 级差异（同名卡可不同），目前认识 `cost_delta` | ✅ |

## 关键词

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 瞬发 | `fast` | 每（半）回合双方各自第一张瞬发牌不消耗鬼火 | ✅ |
| 响应 | `trigger` | 敌方回合满足条件必发，其余要求照常 | ✅ |
| 疾速 | `swift` | 若有出击次数则改为消耗 1 次出击次数而不消耗鬼火 | 🔧 |
| 突袭 | `strike` | 使一个式神仅在下一次出击且与敌方式神战斗时获得增益 | 🔧 |
| 免疫 | `immune` | 免疫某类伤害/效果；战斗伤害免疫已实现为带作用域的 `battle_immunity`（见本节末说明），通用免疫 🔧 | 🔧 |
| 倒计时 | `countdown` | 式神级倒计时能力（一名式神至多 1 个，新注册替换旧的；不论基础/觉醒/形态来源）：三要素 `countdown_initial`（初值）/ `countdown_block`（归零效果块，`EffectBlock.countdown` 非 None 的能力块或形态牌 `countdown_effects`）/ `countdown_once`（一次型），另记来源 `countdown_source`（基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id）。注册时机：能力进场（对局开始/升至 1 级/复活）、觉醒替换、形态结附、`set_countdown` 动作；形态离场仅清除形态授予的，气绝清除。归零（rules.md ch12 修订版）：先即时插入结算（此时仍为 0，块内对自身 `countdown_delta` 修正为 -0）→ 记账 `countdown_history` → 循环型重置/一次型移除 | ✅ |
| 直击 | `direct_hit` | | 🔧 |
| 迅捷 | `haste` | 一次性：出击的鬼火消耗处不消耗鬼火，随后失去一个一次性迅捷；仍消耗出击次数 | ✅ |
| 屏障 | `barrier` | 一次性：伤害事件"护甲计算前3"将伤害值改为 0 并移除一个实例 | ✅ |
| 不屈 | `unyielding` | 生命>1 且伤害≥当前生命时保留 1 点生命；一次性不屈触发后全部消耗，持续/永久不屈保留可再触发；生命=1 不触发 | ✅ |
| 眩晕 | `stunned` | | 🔧 |
| 运势 | `luck` | 运势判定 = luck check | 🔧 |
| 增强 | `enhance` | | 🔧 |
| 鼓舞/压制 | `basic_boost` / `assault_boosts` | 出击加成：`basic_boost` 动作登记于牌手（`PlayerState.assault_boosts`），下一次出击全部消耗——力量挂攻击后到期强化（战后核销）、护甲获得后保留；战斗牌不消耗。压制（负值）🔧 | ✅（鼓舞） |
| 追猎 | `hunt` | | 🔧 |
| 贯通 | `piercing` | 对式神的非反击伤害超过其当前生命时，溢出部分改对所属牌手造成。是"伤害原因"的属性：式神持有的贯通仅传导至其战斗伤害与基础/觉醒/形态能力（含形态倒计时、延迟"会"）伤害；卡牌效果伤害不继承，除非步骤显式声明 `piercing: true`（实现：`ExecContext.is_ability` + damage/random_damage 动作缺省继承） | ✅ |
| 穿刺 | `pierce` | 造成伤害前（伤害事件批次0，即时时机）移除受伤者所有护甲/屏障——与本次伤害是否最终生效（免疫/归零/屏障）无关；适用于任意来源伤害（含非战斗伤害） | ✅ |
| 吸血 | `lifesteal` | 伤害流程"造成/受到伤害后"（延时，优先级 1 锚点）：来源式神持有则生成以其控制者牌手为执行者的恢复生命事件（治疗量 = 该次伤害值，走 `Game.heal` 管线；实现 `Game._queue_lifesteal` 合成 _Pending 入队） | ✅ |
| 投射 | `projectile`（目标池） | 优先敌方战斗区式神，战斗区为空则退回敌方牌手 | ✅ |
| 唯一 | `unique` | | 🔧 |
| 先攻 | `initiative` | 先攻阶段造成伤害、交战阶段不再造成（结构已实现，暂无卡牌持有） | ✅ |
| 必杀 | `fatal` | | 🔧 |
| 远程 | `remote` | 不进入战斗区、不受先攻及交战阶段的反击伤害 | ✅ |
| 连击 | `combo` | 先攻阶段与交战阶段各造成一次战斗伤害 | ✅ |
| 暴击 | `critical` | | 🔧 |
| 激怒 | `enraged` | 状态关键字：己方被激怒式神中存在满足出击合法性者时，其他无激怒式神不能出击；在发起战斗的流程（战斗准备前）移除攻击者的激怒（尘缚之阵授予） | ✅ |
| （引擎级） | `keep_attack_buffs` | 攻击后到期强化不因攻击移除（残心；卡面不出现此关键字） | ✅ |

**关键字持久性三类**（每类均为可重复多重集，存于 `ShikigamiState`）：

| 类别 | 字段 | 语义 |
|---|---|---|
| 一次性 | `one_shot_keywords` | 触发后移除（迅捷/不屈/屏障为天然一次性）；气绝时清除 |
| 持续性 | `keywords` | 触发后不移除（远程/贯通/连击/穿刺/先攻/连击等）；气绝时清除 |
| 永久 | `perm_keywords` | 气绝时不清除 = 复活后自动重新获得；永久是授予方式而非关键字属性 |

此外**战斗伤害免疫**不是关键字：带作用域的修饰（`ShikigamiState.immunities` 条目 + `battle_immunity` 动作），只免疫 kind ∈ (combat, counter) 的伤害，作用域由授予效果指定（仅本战斗 / 含嵌套战斗）。

## 预留机制（译名确认，规则 Phase 3+）

弹回 `rebound`、融合 `fusion`、帷幕 `veiled`、昂扬 `exaltation`、坚毅 `tenacity`、占卜 `divine`、灵咒 `invocation`（结附 `attach`）、幻境耐久 `intensity`、充能 `charging`、爆能 `burst`、赐能 `bless`、烹饪 `cook`、战技 `tactical`、蓄力 `charge`、起源 `origin`、戏法 `trick`、专注 `focus`、入夜 `nightfall`、剧毒 `poisonous`（剧毒伤害 poison damage / 中毒 poisoned）、连引 `link`、连锁 `chain`、替身 `substitute`、化身 `incarnate`（混沌化身 `chaos_incarnate`）、启悟 `enlightenment`、坚守 `stand_boost`、加护 `shelter`、蚀印 `etch`、羁绊 `bond`、堆叠 `stack`、商店赏金 `bounty`、变形 `transform`（视作原能力离场、新能力进场，非气绝；气绝时一般解除）。

## 结算与事件

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 效果块 | `EffectBlock` | when/mode/timing/condition/steps | ✅ |
| 动作 | `op` / Action | `core/actions.py` 注册表原语 | ✅ |
| 事件 | `event` | `core/events.py` ∪ `db/events.yaml` | ✅ |
| 即时时机 | （EVENT_TIMING=insert 的事件类别） | 有临时队列：同时机能力全部触发后依次执行（如"攻击时"） | ✅ |
| 延时时机 | （EVENT_TIMING=queue 的事件类别） | 无队列：触发的能力加入当前效果队列，其结算完后执行（如"造成伤害后"） | ✅ |
| 时机类别 | `EVENT_TIMING` | 各事件的默认时机（core/events.py）；EffectBlock.timing 可单卡覆盖 | ✅ |
| 插入结算 | `insert`（timing） | 立即插入当前结算 | ✅ |
| 队列结算 | `queue`（timing） | 入队延迟结算 | ✅ |
| 可中断 | `interleaved`（mode） | 步骤间允许其它效果结算 | ✅ |
| 不可中断 | `atomic`（mode） | 步骤连发 | ✅ |
| 目标 | `target` / `Ref` | Ref(player, shikigami?) | ✅ |
| 随机生成 | `generate`（动作） | 从 db 按谓词（所属式神/主类型）随机生成卡牌置入区域（发 uid、可重复、池内不含衍生卡；杀念/觉醒·一目连） | ✅ |
| 直接消灭 | `destroy` / `destroy_form`（动作） | 非伤害消灭：生命归零走气绝流程 / 消灭当前结附的形态（直接消灭免疫为扩展锚点） | ✅ |
| 调度 | `mulligan` | 游戏开始阶段：返回 1 张起始手牌再随机抽 1，双方各 3 次 | ✅ |
| 半回合 | `turn` | GameState.turn，双方交替 +1 | ✅ |
| 延迟能力 | `delayed` / `delay_grant`（动作） | 绑定式神的一次性延迟能力（会）：条目 {block, chosen, uses, secret}，事件匹配时先触发后执行、收集即消耗；气绝清除（变形离场保留——变形未实现）；secret=True 时选择目标对敌方保密（联机脱敏抹除对手视角的 chosen） | ✅ |
| 伤害上限 | `cap_damage`（动作） | 改写伤害事件中可变伤害对象的数值：to="shield" 时至多为受伤式神当前护甲（森罗之阵；须挂 on_damage_start 等含 damage payload 的时点批次） | ✅ |
| 战斗区锁定 | `combat_lock`（tags） | 尘缚之阵：携带者（兵俑）在战斗区且敌方战斗区有式神时，会使敌方战斗区式神被替换的效果无效且不能进行（不看发起者）——召唤召唤物无效、准备区式神不能发起无远程的战斗（出击/战斗牌）、响应战斗牌插入移入不可用、enter_combat 效果无效；退回准备区不受限；效果发起的战斗暂无来源 | ✅ |
| 免疫直接消灭 | `destroy_immune`（tags） | 尘缚之阵：结附带此标记形态的式神在战斗区时，`destroy` 动作对其无效（日志记"免疫了本次消灭"）；伤害消灭/形态消灭不受影响 | ✅ |
| 退回准备区 | `retreat`（动作） | 目标式神移回准备区（与 `enter_combat` 对称；仅战斗区式神有效，召唤物退回即离场） | ✅ |
| 倒计时增减 | `countdown_delta` / `set_countdown`（动作） | `countdown_delta`：倒计时 ±（无能力/为 0 修正 -0，≤0 走归零流程）；`set_countdown`：注册新倒计时能力（initial/steps/once，替换旧的；record=True 记录事件所用卡牌到式神 `ext["recorded_card"]`） | ✅ |
| 凭空自动使用 | `recast_recorded`（动作） | 凭空生成 `ext["recorded_card"]` 记录卡 id 的同名牌并免费自动使用（不耗鬼火、非从手牌、无主动目标；大天狗倒计时）；`gain_orb`：获得鬼火 | ✅ |
| Step 级条件 | `Step.condition` | 结算时以条件迷你语言求值，不满足则跳过该 step（op 自身声明 condition 参数者——如 delay_grant——仍作 op 参数传递） | ✅ |
| 扩展数据 | `ext` | 少数卡专用的运行时数据（`ShikigamiState.ext` / `PlayerState.ext`，约定键见下表） | ✅ |
| 治疗（恢复生命） | `Game.heal` / `heal`（动作） | 治疗事件流程（thoughts.txt）：on_before_heal（即时）→ 治疗量 = min(治疗量, 已损失生命) → 增加生命 → 0 终止 → on_heal / on_after_heal（延时）；濒死/气绝者不受治疗 | ✅ |
| 气绝前 1 | `on_before_defeat` | 气绝/消灭事件开头（`check_defeated`）的即时时机；响应牌挂此时机（射怪鸟事类） | ✅ |

**ext 约定键登记表**（少数卡专用数据不进 State 底层字段，统一收纳于 `ext`）：

| 键 | 载体 | 说明 |
|---|---|---|
| `countdown_history` | `PlayerState.ext` | 本局倒计时能力生效序列（归零生效后追加来源 id：基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id；大合奏、风韵雅乐用） |
| `recorded_card` | `ShikigamiState.ext` | 大天狗记录的法术牌数据 id（`set_countdown(record=True)` 写入；气绝丢失） |
| `fragile_to_damage` | `ShikigamiState.ext` | 获得破甲转化为等量伤害（"获得破甲前"锚点，`Game._change_shield` 读取；碧羽散华用） |

## 增强与修饰（设计已定，部分已实现；见 `docs/enhance-design.md`）

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 卡牌触发器 | `triggers`（CardDef） | 卡面"增强"等的实现机制之一：游离触发块（when/condition/steps）；emit 时全库扫描匹配，为第三收集来源（式神能力之后、响应牌之前） | ✅ |
| 实时监测 | `monitors` / Monitor | 卡面"增强"等的实现机制之一：状态谓词 + 修饰，读取/打出装配时求值，不存储 | 🔧 |
| 即时装配 | `_materialize` | 打出时由"定义块 ⊕ 活跃修饰"装配本次实际效果（persistent 快照入实例 mods），用完即弃 | ✅ |
| 修饰 | `mods` | 实例级（`CardInstance.mods`：enhance 数值/keywords_add/cost_delta）与 (玩家, card_id) 级持久 store（`PlayerState.card_mods`，"本局游戏每……"类计数） | ✅ |
| 卡牌光环 | `card_auras` | 谓词匹配的卡牌获得关键词/不耗鬼火（读取时求值，覆盖已有与新生成的牌）；scope 决定失效时机（"turn"=己方回合开始清除；连续型/属性型光环为扩展锚点） | ✅ |
| 追加块 | `pre_grants` / `grants` | 可被监测/触发器按索引注入结算的候选效果块（前置/后置） | 🔧 |
| 临时触发 | `temp_grants` / `TempGrant` | 一次性注册的触发（uses 递减移除）；战斗牌携带者绑定该次战斗注册（如不祥之刃击杀抽牌） | ✅ |
| 写入目标 | `to`（hand/persistent/instance/turn） | 写入原语（add_mod）的修饰存储目标：手牌实例 / 持久 store / 来源实例自身（实例计数器，如风符·龙的目标数）/ 回合 store（turn 未实现，"本回合"类由 card_auras 覆盖） | ✅ |
| 数值叠加 | `{"enhance": true, "base": n}` | 步骤 amount 参数形式：base + 实例已装配 enhance（战斗牌战力/护甲提取处解析） | ✅ |
| 动态数值 | `{"shield_of": ...}` / `{"power_of": ...}` | 步骤 amount 参数形式：以来源式神当前护甲 / eff_power 求值——尘刀按打出瞬间护甲快照战力（本次战斗中不变）、古尘之壁按护甲强化、援护按白狼力量造伤 | ✅ |
