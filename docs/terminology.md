# 术语表（中文 ↔ 代码标识）

代码与数据库中的命名以此表为准。状态：✅ 已统一 / 🔧 预留（数据可携带，机制未实现）。

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
| 除外区 | `exiled` | 标准区域之一（放逐/移出游戏；协战主牌使用后亦进入此区） | ✅ |
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
| 临时修正 | `temp_power` | 气绝时清除（临时/永久的区分 = 复活能否保留）；光环类 Phase 5 | ✅ |
| 攻击后到期强化 | `attack_buffs` / `attack_buff`（动作） | 挂账式临时强化（临时力量 + 授予关键字）：自身作为攻击者的战斗终止点核销（rules.md:176"直到攻击后"）；气绝清空 | ✅ |
| 护甲保留 | `keep_shield` | `ShikigamiState.keep_shield`：护甲不再于己方回合开始移除（觉醒·兵俑） | ✅ |

## 卡牌数据

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 法术牌 | `spell` | card_type | ✅ |
| 战斗牌 | `combat` | card_type | ✅ |
| 形态牌 | `form` | card_type | ✅ |
| 幻境牌 | `field` | card_type（预留） | 🔧 |
| 协战牌 | `reinforce` / `options` / `choice` | card_type=协战主牌（shikigami 主 + shikigami2 副双归属）；`options` = 两个子选项 token 卡 id（[0] 主侧 [1] 副侧）；打出时 cmd 带 `choice`（0/1）选择 → 合法性（出战/等级/鬼火/目标）按子卡 → 生成 token 入手并视作从手牌使用（完整使用事件流程）→ 主牌离手进 `exiled` 区（不进墓地）；[羁绊] 不进关键词表，实现为子卡普通 steps；**羁绊触发条件 = 使用此牌时对应式神在场（等级 ≥1 且未气绝）**——step 级 `condition: {shikigami_active: <式神id>}` 门控（generate 类），倒计时增减/发起攻击/形态进场类由 op 空操作语义隐式满足 | ✅ |
| 觉醒牌 | `subtype = "awaken"` | **不是主类型**：任意 card_type + subtype（rules.md:502）；法术觉醒使用事件流程：墓地 → `on_before_awaken`（觉醒前，即时）→ 替换式神能力 → 法术本身效果 → `on_awakened`（觉醒后，延时）→ 永久身材增益（`awaken_power`/`awaken_health`） | ✅ |
| 觉醒（状态） | `awakened` | `ShikigamiState.awakened` = 觉醒牌 id；能力改读该牌 `abilities` 块；气绝/复活保留（但气绝时能力不在场——觉醒门控类判定要求未气绝） | ✅ |
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
| 仅气绝时可用 | `only_when_defeated` | 卡牌字段（第十三阶段）：硬门控——式神存活时主动使用报错、响应收集直接跳过（心即归处）；需搭配 `playable_when_defeated` | ✅ |
| 半成品式神 | `wip`（ShikigamiDef） | 仅基础数据/卡牌未齐的式神（青行灯）：不进构筑可选池（available_shikigami）与测试卡组（_pick_test_ids）；卡数不足 8 种的成品式神（纸人武士/天邪鬼军团）不受限 | ✅ |
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
| 直击 | `direct` | 战斗事件"确定目标前1"：若本次战斗无目标，被攻击者改为敌方牌手（无视敌方战斗区式神）；追猎已选定目标时直击被覆盖 | ✅ |
| 迅捷 | `haste` | 一次性：出击的鬼火消耗处不消耗鬼火，随后失去一个一次性迅捷；仍消耗出击次数 | ✅ |
| 屏障 | `barrier` | 一次性：伤害事件"护甲计算前3"将伤害值改为 0 并移除一个实例 | ✅ |
| 不屈 | `unyielding` | 生命>1 且伤害≥当前生命时保留 1 点生命；一次性不屈触发后全部消耗，持续/永久不屈保留可再触发；生命=1 不触发 | ✅ |
| 眩晕 | `stunned` | | 🔧 |
| 运势 | `luck` | 运势判定 = luck check | 🔧 |
| 增强 | `enhance` | | 🔧 |
| 鼓舞/压制 | `basic_boost` / `assault_boosts` | 出击加成：`basic_boost` 动作登记于牌手（`PlayerState.assault_boosts`），下一次出击全部消耗——力量挂攻击后到期强化（战后核销）、护甲获得后保留；战斗牌不消耗。卡牌关键字 `inspire` 为卡面[鼓舞]标记（效果以 basic_boost 结算——桃之夭夭）。压制（负值）🔧 | ✅（鼓舞） |
| 追猎 | `hunt` | 有目标的战斗：战斗牌持追猎主动使用时须选择 1 名合法敌方式神为战斗目标（不能选牌手；无合法目标则不能使用）；式神/形态持追猎主动出击可任选合法敌方式神为目标（不选 = 默认无目标战斗）；发起者无远程照常移入战斗区；`launch_attack` 类"使己方式神发起攻击"是无目标战斗，不吃追猎 | ✅ |
| 贯通 | `piercing` | 对式神的非反击伤害超过其当前生命时，溢出部分改对所属牌手造成。是"伤害原因"的属性：式神持有的贯通仅传导至其战斗伤害与基础/觉醒/形态能力（含形态倒计时、延迟"会"）伤害；卡牌效果伤害不继承，除非步骤显式声明 `piercing: true`（实现：`ExecContext.is_ability` + damage/random_damage 动作缺省继承） | ✅ |
| 穿刺 | `pierce` | 造成伤害前（伤害事件批次0，即时时机）移除受伤者所有护甲/屏障——与本次伤害是否最终生效（免疫/归零/屏障）无关；适用于任意来源伤害（含非战斗伤害） | ✅ |
| 吸血 | `lifesteal` | 伤害流程"造成/受到伤害后"（延时，优先级 1 锚点）：来源式神持有则生成以其控制者牌手为执行者的恢复生命事件（治疗量 = 该次伤害值，走 `Game.heal` 管线；实现 `Game._queue_lifesteal` 合成 _Pending 入队） | ✅ |
| 投射 | `projectile`（目标池） | 优先敌方战斗区式神，战斗区为空则退回敌方牌手 | ✅ |
| 唯一 | `unique` | | 🔧 |
| 先攻 | `initiative` | 先攻阶段造成伤害、交战阶段不再造成（结构已实现，暂无卡牌持有） | ✅ |
| 必杀 | `lethal` | 不是伤害属性：伤害事件造成伤害后，来源持必杀则令受伤者在该次伤害事件后延时结算气绝（剩余生命 >0 不提前标濒死；与伤害本身导致的气绝并行结算——victims 队列追加"必杀"条目，`check_defeated` 幂等；伤害被免疫未造成则不触发） | ✅ |
| 帷幕 | `veil` | 不能成为敌方出击/用牌的合法目标：choose/出击目标过滤（`pool_refs(targeted=True)`）；已确定目标在效果结算时持帷幕则取消目标相关效果（`targets.resolve` 再校验，仅卡牌效果、能力不受）；有目标的出击发起前目标获帷幕则不发起战斗、有目标的非出击战斗则改为无目标战斗（`_battle_flow` 发起前再校验）；全体/随机效果不取对象不受影响 | ✅ |
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

此外**战斗伤害免疫**不是关键字：带作用域的修饰（`ShikigamiState.immunities` 条目 + `battle_immunity` / `grant_immunity` 动作），只免疫 kind ∈ (combat, counter) 的伤害，作用域由授予效果指定（仅本战斗 / 含嵌套战斗 / 本回合）。

## 预留机制（译名确认，规则 Phase 5+）

弹回 `rebound`、融合 `fusion`、昂扬 `exaltation`、坚毅 `tenacity`、占卜 `divine`、灵咒 `invocation`（结附 `attach`）、幻境耐久 `intensity`、充能 `charging`、爆能 `burst`、赐能 `bless`、烹饪 `cook`、战技 `tactical`、蓄力 `charge`、起源 `origin`、戏法 `trick`、专注 `focus`、入夜 `nightfall`、剧毒 `poisonous`（剧毒伤害 poison damage / 中毒 poisoned）、连引 `link`、连锁 `chain`、替身 `substitute`、化身 `incarnate`（混沌化身 `chaos_incarnate`）、启悟 `enlightenment`、坚守 `stand_boost`、加护 `shelter`、蚀印 `etch`、羁绊 `bond`、堆叠 `stack`、商店赏金 `bounty`、变形 `transform`（视作原能力离场、新能力进场，非气绝；气绝时一般解除）。

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
| 延迟能力 | `delayed` / `delay_grant`（动作） | 绑定式神的一次性延迟能力（会）：条目 {block, chosen, uses, secret, scope}，事件匹配时先触发后执行、收集即消耗；气绝清除（变形离场保留——变形未实现）；scope="turn" 时己方回合开始清除（魔音扰心类）、scope="play" 时该次出牌结算结束清除（黑羽之刃类"本次使用期间"）；secret=True 时选择目标对敌方保密（联机脱敏抹除对手视角的 chosen） | ✅ |
| 伤害上限 | `cap_damage`（动作） | 改写伤害事件中可变伤害对象的数值：to="shield" 时至多为受伤式神当前护甲（森罗之阵；须挂 on_damage_start 等含 damage payload 的时点批次） | ✅ |
| 战斗区锁定 | `combat_lock`（tags） | 尘缚之阵：携带者（兵俑）在战斗区且敌方战斗区有式神时，会使敌方战斗区式神被替换的效果无效且不能进行（不看发起者）——召唤召唤物无效、准备区式神不能发起无远程的战斗（出击/战斗牌）、响应战斗牌插入移入不可用、enter_combat / force_enter_combat 效果无效；退回准备区不受限；效果发起的战斗暂无来源 | ✅ |
| 免疫直接消灭 | `destroy_immune`（tags） | 尘缚之阵：结附带此标记形态的式神在战斗区时，`destroy` 动作对其无效（日志记"免疫了本次消灭"）；伤害消灭/形态消灭不受影响 | ✅ |
| 退回准备区 | `retreat`（动作） | 目标式神移回准备区（与 `enter_combat` 对称；仅战斗区式神有效，召唤物退回即离场） | ✅ |
| 强制进场 | `force_enter_combat`（动作） | 强制目标进入其战斗区（鬼之手类"将敌方准备区式神移入战斗区"，targets 经 enemy_bench 池选择）；移动语义同 enter_combat，尘缚锁定下（移入会替换被锁战斗区式神）静默无效；`random_pick`=候选中随机取 1 名（随机不取对象、不吃帷幕）；`if_combat_empty`=目标所属玩家战斗区非空则整体跳过（鬼之手空发） | ✅ |
| 牌手级持久监听 | `player_aura`（动作）/ `PlayerState.auras` | "本局游戏"类能力附着于牌手（豪焰）：事件触发即结算块，不限次数、跨气绝保留；`scope="game"`（默认）本局有效 / `scope="turn"` 仅本回合（己方回合开始清除，鼓舞类）；`once_key` 防重复登记、缺省可叠加；emit 时按注册顺序收集（`_collect_player_auras`，卡牌触发器之后） | ✅ |
| 战斗结束追加攻击 | `followup_attack`（动作）/ `_battle_followups` | 登记战斗结束后的追加攻击（地狱之手类）：整场战斗终止点核销后先结算积累的延时能力（登记在其中），再依次结算——目标为生命最低敌方式神（平手随机、帷幕不可选；无合法目标改无目标战斗），不享受原战斗牌战力/关键字；可多次登记链式排队；按触发事件 battle payload 登记（气绝后延时能力在战斗弹栈后结算） | ✅ |
| 倒计时增减 | `countdown_delta` / `set_countdown`（动作） | `countdown_delta`：倒计时 ±（无能力/为 0 修正 -0，≤0 走归零流程）；`set_countdown`：注册新倒计时能力（initial/steps/once，替换旧的；record=True 记录事件所用卡牌到式神 `ext["recorded_card"]`） | ✅ |
| 凭空自动使用 | `recast_recorded`（动作） | 凭空生成 `ext["recorded_card"]` 记录卡 id 的同名牌并免费自动使用（不耗鬼火、非从手牌、无主动目标；大天狗倒计时）；`gain_orb`：获得鬼火 | ✅ |
| Step 级条件 | `Step.condition` | 结算时以条件迷你语言求值，不满足则跳过该 step（op 自身声明 condition 参数者——如 delay_grant——仍作 op 参数传递） | ✅ |
| 扩展数据 | `ext` | 少数卡专用的运行时数据（`ShikigamiState.ext` / `PlayerState.ext`，约定键见下表） | ✅ |
| 治疗（恢复生命） | `Game.heal` / `heal`（动作） | 治疗事件流程：治疗反转判定（heal_reversal）→ on_before_heal（即时）→ 实际治疗量 = min(治疗量, 已损失生命) → 增加生命 → on_heal（延时，**实际恢复 0 也触发**，amount=0）→ on_after_heal（延时，**仅实际恢复 > 0 触发**）；濒死/气绝者不受治疗。挂点口径："过量治疗转化"（海坊主）、"为牌手恢复生命时"（灵能）挂 on_heal；"你恢复生命时"= 己方任一角色（含牌手）实际恢复（青坊主基础/禅心/觉醒）挂 on_after_heal | ✅ |
| 过量治疗 | `overheal`（on_heal payload 键） | max(0, 治疗量 − 实际治疗量)；海坊主"过量治疗转化护甲"通道——能力块挂 on_heal 以 {overheal_ge: 1} 门控，转化量取 payload overheal（满血治疗 overheal=全额，照常转化） | ✅ |
| 治疗反转 | `heal_reversal`（tags） | 法界唯心：其控制者在场形态含此标记时，该方效果对**敌方**目标的恢复生命改为走伤害管线造成等量伤害（受伤害批次/免疫影响）；对己方目标恢复不受影响（`_field_form_has_tag` 扫描在场形态 tags） | ✅ |
| 气绝前 1 | `on_before_defeat` | 气绝/消灭事件开头（`check_defeated`）的即时时机；响应牌挂此时机（射怪鸟事类） | ✅ |
| 使用手牌前 | `on_before_card_play` / `nullify_card_play`（动作） | 付费/打出装配后、类型分支前的即时时机；`nullify_card_play` 置位 payload 可变标记 `nullified` 终止该次使用（牌入墓地、跳过效果与 on_card_played）；"一次性无效化"能力用 `delay_grant(scope="turn")` 表达（魔音扰心） | ✅ |
| 变为（卡牌） | `transformed`（card_mods/mods 键） | 同名牌视为新牌：打出装配改读 `alt_effects`、关键字减 `alt_remove_keywords`（正义之必胜类"本局每……变为"用 triggers + add_mod(to=persistent, key=transformed) 表达） | ✅ |
| 动态免费 | `cost_zero_if`（CardDef） | 满足条件时不耗鬼火：`{"ext": key}` 读 `PlayerState.ext`（黄金羽"本回合首次"用）；`{"level_ge": n}` 卡牌所属式神当前等级 ≥ n（心身炼磨"犬神 3 级不耗鬼火"，未出战不满足） | ✅ |
| 黄金羽计数 | `golden_feather`（tags） | 出牌统一记账：tags 含此标记的牌使用时 `PlayerState.ext["feather_used_game"/"feather_used_turn"]` +1（回合开始清 turn 键）；on_card_played payload 携带 `golden_feather` 供触发条件判等（风之舞/不可饶恕/流浪之羽） | ✅ |
| 块内暂存 | `memo` / `last_damage_victims` | ExecContext 块内步骤间暂存（_resolve_block 初始化）：damage 动作记录本步受伤者，后续 step 以 context 目标引用（风神一扇"将受到此伤害的式神移回准备区"）；另记 `last_damage_total`（本步实际伤害合计，巨浪 X）、`last_heal_targets`（heal 动作本步治疗目标，佛光池 side_of_last_heal） | ✅ |
| 受影响者 | `affected_refs`（on_card_played payload） | 该次出牌效果实际伤害过的敌方式神列表（出牌/响应/自动使用结算期间由伤害管线记录；答复(7)：只计敌方式神、去重，牌手与己方式神不计）；on_card_played payload 同时携带 card_type/subtype/shikigami 供条件匹配（暴风之主、大天狗基础能力） | ✅ |
| 条件写入 | `require`（add_mod 参数） | {"key": k, "ge": n}：同一 store 中键 k ≥ n 才执行写入（吾即正义"使用过 10 次法术则变为"：先计数再置位 transformed） | ✅ |
| ext 计数 | `bump_ext`（动作） | 目标式神/牌手 ext[key] 累加：倒计时能力的"每触发一次 +1"以块内 step 表达（鸩 x=zhen_proc）；ext 不随气绝清除 | ✅ |
| 每回合合计一次 | `turn_mark` / `turn_mark_not` | 标记存 `PlayerState.ext["turn_marks"]`，任一回合开始双方清除；能力条件以 {turn_mark_not: key} 求值（寂寥心象；标记须先于分支步骤，连锁事件被门控挡） | ✅ |
| 伤害→破甲转化 | `convert_damage`（动作） | 战斗作用域（毒蚀"双方造成的伤害转化为等量破甲"）：答复(5)——伤害事件生成点全额转化（`_battle_convert`，护甲不再先吸收；不再视为伤害），战斗终止点清除；已转化的伤害（converted）不再转化，防与获得破甲→伤害转化循环 | ✅ |
| 战斗条件授予 | `defender_has_fragile`（条件运算符） | 战斗牌效果块中的 grant_keyword / battle_immunity step 由战斗流程提取为战斗作用域授予，Step.condition 在战斗开始时以 {"defender": 被攻击者} 求值（鸩羽/致命诱惑"若攻击有破甲的角色"） | ✅ |
| 玩家扩展条件 | `player_ext`（条件运算符） | {player_ext: key}：控制者 `PlayerState.ext[key]` 为真值（"本回合若使用过黄金羽"= feather_used_turn；千羽风之舞 step 级条件用） | ✅ |
| 战斗/非战斗伤害免疫 | `grant_immunity`（动作） | scope="turn"：目标式神免疫战斗伤害到当前回合结束——以回合号记账（immunities 条目 {"turn": n}），过期条目于回合开始清理（`_start_turn` 双方过滤，防显示残留——不可饶恕用）；scope="perm"：持续在场期间有效（气绝清除、复活重新授予）；scope="once"：消耗式——命中任意一类伤害即免疫一次并移除（桃红簇簇）；kind="effect" + from_side="enemy"：非战斗伤害免疫、只免疫敌方来源（无来源或己方来源不免疫——觉醒·山童，`_effect_immune` 在伤害流程"伤害开始时"批次内判定）；kind="all"：免疫全部伤害——牌手目标条目存 `PlayerState.immunities`、按 turn 回合号记账+回合开始清理，`_player_immune` 在伤害管线入口判定（舍生）；式神目标搭配 scope="once"（桃红簇簇，`_combat_immune`/`_effect_immune` 匹配 kind 扩 "all"） | ✅ |
| 弃牌计数暂存 | `discarded_count`（memo 键） | discard 动作结算后把实际弃牌数写入块内暂存 `ctx.memo["discarded_count"]`；draw 的 count 支持 {"memo": key} 读取（射怪鸟事"弃多少抽多少"两步组合） | ✅ |
| 使用方式觉醒门控 | `requires_awaken`（PlayMethod 扩展字段） | 选择该使用方式时所属式神须已觉醒且未气绝/离场（气绝时觉醒能力不在场——答复(11)），否则 IllegalAction（黄金羽觉醒后"以敌方角色为目标"方式） | ✅ |
| 响应效果覆盖 | `response`（CardDef） | 响应牌的效果块覆盖：主动使用效果与响应效果结构不同时（魔音扰心：主动=登记延迟无效化，响应=直接无效化当前用牌），响应收集/复查/结算改读本块；缺省用 effects | ✅ |
| 倒计时重放 | `replay_countdown`（动作）/ `_countdown_block_for` | 按 `countdown_history` 首次出现顺序依次执行来源属于目标式神的倒计时能力块（每种至多一次；基础=式神 id、觉醒=觉醒牌 id、形态=形态牌 id 找回对应块；`skip_forms` 跳过形态来源——答复(8) 大合奏用，风韵雅乐不过滤） | ✅ |
| 破甲回赋登记 | `fragile_echo`（动作）/ `_battle_echo` | "攻击时"记录目标当前破甲量，本次战斗结束后一次性赋予等量破甲（蚀刃毒羽，答复(2)；战斗中止丢弃） | ✅ |
| 法术强化力量再授予 | `reapply_attack_buff_power`（动作） | 目标当前 attack_buffs 挂账（起弓/离/无我）的力量部分合计，作为一条新的攻击后到期强化再次授予（仅力量，关键字不重复；灵矢贯虹，答复(3)） | ✅ |
| 形态进场再触发 | `trigger_form_enter`（动作） | 指定控制者式神（shikigami 参数）当前形态的进场时效果块（form effects）再执行一次；未结附形态空操作（灵矢贯虹羁绊 1） | ✅ |
| 形态倒计时即时触发 | `trigger_form_countdown`（动作） | 触发事件中形态牌的倒计时效果块：结附中形态读式神 countdown_block（倒计时框架注册的块），已离场形态回退读卡牌数据 countdown_effects；只结算效果本身——不改倒计时值、不重置/移除；无倒计时效果空操作（一目连基础/觉醒能力"形态离场时触发其倒计时"） | ✅ |
| 形态变化标记 | `form_changed`（on_form_attached payload） | 无当前形态或新旧形态 id 不同为 true（萤草"使用与当前形态不同的形态牌时"条件） | ✅ |
| 手牌修饰写入 | `mod_hand`（动作） | 按谓词（tags / token）选手牌实例写入 mods（once_key 防叠加）；读取点：`playable_when_defeated`（出牌/响应收集/复查）、`damage_boost`（damage 动作加值）、`revive_haste`（使用牌后指定式神复活倒计时 -1，≤0 复活）——鎏金幻羽用 | ✅ |
| 倒计时干预扩展 | `countdown_delta`（shikigami / revive 参数） | shikigami：按式神 id 指定控制者式神（忽略 targets）；revive=True：改气绝倒计时，≤0 走 `_revive` 复活——targets 非空时只作用于这些目标（按 ref.player，可跨阵营，豪焰"该式神气绝倒计时+1"），targets 为空时扫控制者全队（幻音绝弦） | ✅ |
| 鼓舞吸收 | `consume_assault_boosts`（动作） | 鼓舞战力/护甲转为本次结算战力/护甲并清空鼓舞（灵矢贯虹"消耗所有鼓舞"用；鼓舞关键字暂只有战力/护甲两种） | ✅ |
| 破甲消耗记账 | `_DamageEvent.fragile` | 伤害批次实际消耗（增伤）的破甲量记账，进 on_damage payload `fragile` 键——本引擎破甲受伤即消耗（蚀刃毒羽已改用 fragile_echo，payload 键保留备用） | ✅ |
| 生成子类型过滤 | `subtype`（generate 参数） | 生成候选池限式神 + 子类型（妖琴师觉醒法术池：100124 spell/awaken） | ✅ |
| 法术回响 | `spell_echo` / `spell_echo_recast`（动作） | 登记于来源式神 `ext["spell_echo"]` 的"本回合"序列：持有者以外的式神（含敌方）从手牌使用法术时（同式神法术每回合至多触发一次），依次凭空免费使用 sequence 下一张（每张至多一次；不耗鬼火、play_from=void、triggered=auto、choose 目标随机合法、用后入墓地；照常 emit on_card_played 触发持有者"使用法术牌时"能力，但回响自身不自连锁）；`once_key` 防叠加；己方回合开始清除（涅槃业火） | ✅ |
| 效果发起攻击 | `launch_attack`（动作） | 令指定式神发起一次额外攻击：不耗鬼火/出击次数、准备区自动进战斗区、走正常战斗流程（含反击，无战斗牌加成）；气绝/未在场空操作；shikigami="self" 取来源式神，否则按数据 id 定位（鲁莽、刃影叠岚羁绊） | ✅ |
| 反击贯通 | `counter_piercing`（动作） | 登记到当前战斗上下文（`_battle_counter_piercing`）：该战斗被攻击方的反击伤害具有贯通（rules.md:201 贯通修正批次的反击例外；战斗终止点清除；主动使用由战斗牌流程提取绑定，响应插入使用作为普通动作登记——伺机） | ✅ |
| 力量覆写 | `power_override`（动作） | on=True 时目标式神力量视为 0（覆盖基础+永久+临时+战力全部，`eff_power` 覆写层，标记存 `ext["power_zero"]`）；on=False 解除；形态离场/气绝自动清除（笨拙） | ✅ |
| 伤害增幅 | `boost_damage`（动作） | 在伤害时点批次改写事件中可变伤害对象的数值 +amount（只增；须挂 on_damage_start 等 payload 含 damage 的批次，配合 {source_shikigami: self, kind: effect} 类条件——焚羽"非战斗伤害+1"） | ✅ |
| 鬼火条件 | `orb_ge`（条件运算符） | {orb_ge: n}：控制者当前鬼火 ≥ n（青行灯"若你有剩余鬼火"） | ✅ |
| 字段不等 | `{字段_not: 值}`（条件运算符） | 事件字段 ≠ 给定值；{shikigami_not: null} = 所用牌为专属牌（非中立牌）——觉醒·凤凰火"己方式神使用法术牌" | ✅ |
| 消灭者牌手 | `victim_player`（语境目标） | 气绝事件语境目标（TargetSpec kind="context"）：被消灭式神所属牌手，敌己两向（引燃"若消灭则再对它的牌手造成 2 点伤害"） | ✅ |
| 敌方准备区 | `enemy_bench`（目标池） | 敌方全部准备区式神（与 enemy_combat 对应——崩山准备区段） | ✅ |
| 基础关键字 | `keywords`（ShikigamiDef） | 式神先天关键字：`build_player` 初始化时入 `perm_keywords`（永久类别：气绝不清除、复活自动重新获得——山童先天[贯通]） | ✅ |
| 生命下限钳制 | `min_health_turn`（ext 键，bump_ext 置位） | "本回合生命不会降到 1 以下"（狂啸）：伤害批次"扣减生命"处把伤害压到至多 当前生命-1，生命已为 1 时压为 0 提前终止（同护甲完全吸收；0 伤不触发受伤能力）；半回合作用域——任一回合开始双方清除（`_start_turn`）；[响应]经 `response` 覆盖块挂 on_damage_start，先于钳制置位 | ✅ |
| 战斗区空置条件 | `combat_empty`（条件运算符） | {combat_empty: self\|opponent}：指定方战斗区没有式神（偷袭响应"敌方战斗区没有式神"） | ✅ |
| 回合结束响应排序 | `_suppress_responses`（引擎标志） | 回合结束：on_turn_end 即时能力照常触发，但手牌响应收集被抑制——当前回合方的回合结束延时效果（队列）先结算完，再以合成 on_turn_end 事件收集对方手牌响应（偷袭答复3）；延时效果改变局面（如战斗区变得非空）则响应条件复查不再满足 | ✅ |
| 无战斗响应战斗牌 | （`_settle_response_card` 分支） | 无当前战斗的响应战斗牌（偷袭）不能插入战斗，按完整战斗事件流程发起一次新战斗（正常反击）；攻击方按卡牌所属玩家解析（atk_ref 不取 state.active——响应方可能非当前回合方） | ✅ |
| 有目标战斗扩展 | `target` 扩展键 `battle` / `optional` | battle=true：非追猎战斗牌的 choose 目标作为战斗目标（同追猎的有目标战斗管线、帷幕不可选——天翔鹤斩"改为攻击一个敌方准备区式神"）；optional=true：合法目标池为空时可不带目标使用（退化为无目标普通战斗） | ✅ |
| 精确等级生成 | `level`（generate 参数） | int 或 "shikigami"：后者按 shikigami 参数所指式神当前等级精确匹配生成（醉酒当歌羁绊"获得一张茨木童子当前等级的战斗牌"；所指式神未出战/未在场空操作） | ✅ |
| 战斗牌数值不提取 | `no_extract`（step 参数） | 战斗牌的 buff_power/gain_shield(self) step 缺省提取为战力/一次性护甲在效果步之前结算；标 no_extract 则不提取、按步骤顺序执行（醉酒当歌"先自伤 3 再获得等量护甲"——前置结算会被自己的自伤消耗） | ✅ |
| 鬼火储存 | `orb_store`（tags） | 觉醒·青行灯：己方在场有已觉醒且觉醒牌含此标记的式神时，回合开始鬼火不清零、改为累加并封顶 4 点（`min(4, orb+gain)`；`_orb_stored` 扫在场式神觉醒牌 tags；结算见 rules.md 回合流程步骤 5 注记） | ✅ |
| 结算中交互选择 | `pending_choice` / `choose`（指令） / `deck_top_pick`（动作） | 效果结算中挂起等待玩家作答：deck_top_pick 检视牌库顶 count 张选 1 入手再洗牌、重复 times 次（times 可为 {"orb": true} = **1 + 效果结算时剩余鬼火**，0 火仍执行基础 1 次——第十阶段维护者答复；青灯夜谈）；挂起点存 `_suspended` 续点（内存态，随服务端房间的 Game 实例存活——客户端断线不丢，重连 resync 全量 state 带 pending_choice 可续答）、`GameState.pending_choice` 记 {kind, options, remaining}；pending 期间 apply() 只接受 choose 指令；触发式（triggered）块不挂起、空发即弃；联机 sanitize 对非选择方把 options 脱敏为等长占位（room.py），CLI/net 以 `choose <序号>` 作答；回合超时先随机作答到底再走常规超时流程（否则回合无法收尾、计时器不重启——room._on_timeout） | ✅ |
| 重复执行 | `repeat`（动作） | 子步骤组重复 count 次（int 或 {"orb": true} = **1 + 效果结算时控制者剩余鬼火**：基础 1 次 + 每点剩余鬼火重复 1 次，0 火仍执行基础 1 次——第十阶段维护者答复；吸魂灯），同块上下文共享 ctx.memo；clear_orb=True 重复后一次性清空控制者鬼火（2→0 不经过 1） | ✅ |
| 鬼火消耗/清空 | `consume_orb` / `clear_orb`（动作） | consume_orb：扣控制者鬼火 amount（不灭之火；不视作使用牌）；clear_orb：一次性清空一方鬼火（side="self"/"opponent"，月食类"清空敌方的鬼火"——月食卡不入数据，机制可用）；均 emit on_orb_changed（old→new 单事件，清空不经过中间值） | ✅ |
| 鬼火变化事件 | `on_orb_changed` / `_pay_orb` | 即时时机（insert），payload {player, old, new, reason}；每处变化点发出：回合开始获得、使用牌/出击/响应付费（付费点先于效果结算，响应可插入效果前）、gain_orb/consume_orb/clear_orb/清空。条件通道示例："当敌方鬼火变为 1 时" = {player: opponent, new: 1}（月食类响应，合成卡测试） | ✅ |
| 生命设置 | `set_health`（动作） | 目标牌手生命直接设为 amount、钳制 [1, max_health]（轮回"生命变为 10"——X=0 按原文仍可使用；非治疗非伤害、不触发对应事件） | ✅ |
| 直接升级 | `level_up`（动作） | 目标式神等级 +amount（不走升级次数/不受升级阶段限制、封顶 3；百闻一得）；overflow_draw=True 时已 3 级改为抽 1；0 级未在场/气绝空操作；实际升级后 emit `on_upgrade`（与指令升级同事件——犬神"升级时"类触发两来源均生效；on_upgrade payload 含 `target`=Ref 供 {target_shikigami: self} 匹配） | ✅ |
| 复活（动作） | `revive`（动作） | 复活目标气绝式神（走 `Game._revive` 完整复活流程；不灭之火"返回场上"前置步骤） | ✅ |
| 形态重新结附 | `reattach_form`（动作） | on_form_destroyed 事件中被消灭的形态**同一实例**从墓地找回重新结附（不灭之火；实例不在墓地/来源离场或气绝空操作，配合 revive 使用） | ✅ |
| 弃牌指定 | `card_id`（discard 参数） | 按数据 id 定向弃手牌（百闻一得"弃一张明灯"——无明灯不弃但后续升级仍执行，维护者答复） | ✅ |
| 延迟能力绑定选择目标 | `bind="chosen"`（delay_grant 参数） | 延迟能力改登记到本次选择目标式神上（默认登记在来源式神；沧海之盾"使一个己方式神获得……当他造成伤害时"） | ✅ |
| 数值下限条件 | `{字段_ge: n}`（条件运算符） | 事件数值字段 ≥ n 的通用形式（overheal_ge: 1 = 存在过量治疗，海坊主转化门控；与 orb_ge 控制者鬼火专用键语义不同） | ✅ |
| 致命伤害条件 | `{victim_lethal: true}`（条件运算符） | 事件 victim 当前生命 ≤ 事件伤害值 amount（"将受到致命伤害"——舍生响应门控） | ✅ |
| 战斗区受害者条件 | `{victim_in_combat: true\|false}`（条件运算符） | 事件 victim 是否其控制者战斗区式神（true="战斗区式神被攻击时"——沧海之盾响应门控；false=准备区式神——桃红簇簇"准备区式神受到致命伤害"） | ✅ |
| 角色目标池 | friendly_character / friendly_others_character / any_character / friendly_lowest_level / side_of_last_heal | 含牌手的"角色"池：己方角色（祝福之水）/ 己方其他角色（蹈海）/ 任一角色（治愈之水、佛光）/ 己方等级最低式神（并列全入池，百闻一得）/ 上一步 heal 目标所属方全部角色（佛光，仅 kind=all，读 memo last_heal_targets） | ✅ |
| 半数护甲数值 | `{half_shield_of: "self"\|"source"}`（动态数值） | 取所指式神当前护甲一半（向下取整；沧海之盾"获得等同于其护甲一半的生命"类）；`_step_amount` 同时支持 `{memo: key}` 读取块内暂存数值（巨浪 X = last_damage_total） | ✅ |
| 检索牌库 | `search_deck`（动作） | 从控制者牌库随机检索一张指定式神的牌置入手牌，然后洗牌库（花信风；shikigami="target" 缺省按卡牌选择目标所指式神，"self"=来源式神，或数据 id；仅实际检索到才洗牌，未命中不洗——第十三阶段定案） | ✅ |
| 进出战斗区事件 | `on_enter_combat` / `on_leave_combat` | 式神进入/离开战斗区（延时时机，payload {player, shikigami: Ref}）：`_enter_combat`/`_retreat` 发出（被换下的驻留者经 _retreat 发 leave）；**气绝移动不经 _retreat 不发 leave**；桃红簇簇"进入或离开战斗区时恢复2生命"挂点 | ✅ |
| 气绝触发能力 | `trigger_when_defeated`（EffectBlock）/ `{holder_defeated: bool}`（条件运算符） | 能力收集门控：离场（despawned）恒跳过；气绝者仅带此标记的能力块放行收集（觉醒·犬神"气绝时也能触发"）；0 级未在场仍走 trigger_when_not_in_play。holder_defeated 判能力持有者当前是否气绝（配合前者做"仅气绝时触发"——存活不触发） | ✅ |
| 动态关键字 | `conditional_keywords`（CardDef） | 满足条件的条目把 keyword 加入实际关键字（读取点 `_card_keywords`，对手中/生成的一切副本生效）：`level_ge`=所属式神当前等级 ≥ n（心身炼磨"犬神 2 级获得[瞬发]"）；`if_alive`=所属式神在场未气绝（桃华灼灼"若桃花妖未气绝，此牌得[瞬发]"）；式神未出战条件不满足 | ✅ |
| 状态目标池 | `friendly_injured` / `friendly_defeated`（目标池） | 己方在场且已受伤（生命 < 上限）的式神（丰实/盛开"己方受伤式神"）/ 己方已气绝式神（未离场、等级 ≥1；桃华灼灼/桃语春风复活池）；`TargetSpec` 扩展键 `{"random": n}`：kind=all 解析结果中随机取 n 个（rng.sample，不足取全部；配合 repeat 每轮重解析重随机——盛开"再重复2次"） | ✅ |
| 炼磨计数 | `lianmo`（tags）/ `lianmo_used_game` | 出牌统一记账：tags 含 lianmo 的牌（心身炼磨）使用时 `PlayerState.ext["lianmo_used_game"]` +1（本局累计不清）；心技一体 card_aura power_ext/shield_ext 数值通道读取 | ✅ |

**ext 约定键登记表**（少数卡专用数据不进 State 底层字段，统一收纳于 `ext`）：

| 键 | 载体 | 说明 |
|---|---|---|
| `countdown_history` | `PlayerState.ext` | 本局倒计时能力生效序列（归零生效后追加来源 id：基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id；大合奏、风韵雅乐用） |
| `recorded_card` | `ShikigamiState.ext` | 大天狗记录的法术牌数据 id（`set_countdown(record=True)` 写入；气绝丢失） |
| `fragile_to_damage` | `ShikigamiState.ext` | 获得破甲转化为等量伤害（"获得破甲前"锚点，`Game._change_shield` 读取；碧羽散华用；答复(1)：牌手获得破甲同样转化——其任一式神持标记即生效） |
| `feather_used_game` / `feather_used_turn` | `PlayerState.ext` | 黄金羽（tags 标记）牌使用计数：本局累计 / 本回合（己方回合开始清除；黄金羽动态免费与计数触发用） |
| `zhen_proc` | `ShikigamiState.ext` | 鸩 x：基础+觉醒倒计时能力生效合计（倒计时块内 bump_ext step 累加；气绝不清、跨气绝保留，觉醒后继续累加） |
| `turn_marks` | `PlayerState.ext` | "每回合合计一次"标记表（turn_mark 写入，任一回合开始双方清除；寂寥心象用） |
| `power_zero` | `ShikigamiState.ext` | 力量覆写标记（power_override 写入/解除；eff_power 覆写层——力量视为 0；形态离场/气绝清除；笨拙用） |
| `spell_echo` | `ShikigamiState.ext` | 法术回响序列登记（{sequence, cursor, triggered, once_key}；spell_echo 动作写入，己方回合开始清除；涅槃业火用） |
| `max_power` | `ShikigamiState.ext` | 本局历史最高力量（基础+永久+临时，不含战力；只增不减，跨气绝保留不重置——断臂"本局最高力量-当前力量"用；`Game._record_max_power` 在力量变化点更新，初始 = 基础力量） |
| `turn_power` | `ShikigamiState.ext` | 本回合临时力量增益记账（buff_power scope="turn" 累加写入；己方回合开始从 temp_power 扣减并清零——武士之笛/鼓舞类） |
| `rashomon_kills` | `PlayerState.ext` | 本局累计消灭敌方战斗区基础式神计数（罗生门之鬼 triggers 内 bump_ext 写入；random_enhance 的 1/3/5 档位判定用） |
| `min_health_turn` | `ShikigamiState.ext` | 生命下限钳制标记（狂啸 bump_ext 置位；伤害"扣减生命"批次把生命保持在 ≥1；任一回合开始双方清除——半回合作用域） |
| `damage_taken_turn` | `ShikigamiState.ext` | 本回合所受伤害之和（伤害"扣减生命"处按实际伤害值累加；任一回合开始双方清除——百鬼夜行 X 用） |
| `lianmo_used_game` | `PlayerState.ext` | 本局'心身炼磨'（tags lianmo）使用计数（出牌统一记账 `_account_card_played`；心技一体 card_aura power_ext/shield_ext 数值通道读取） |

## 增强与修饰（设计已定，部分已实现；见 `docs/enhance-design.md`）

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 卡牌触发器 | `triggers`（CardDef） | 卡面"增强"等的实现机制之一：游离触发块（when/condition/steps）；emit 时全库扫描匹配，为第三收集来源（式神能力之后、响应牌之前） | ✅ |
| 实时监测 | `monitors` / Monitor | 卡面"增强"等的实现机制之一：状态谓词 + 修饰，读取/打出装配时求值，不存储 | 🔧 |
| 即时装配 | `_materialize` | 打出时由"定义块 ⊕ 活跃修饰"装配本次实际效果（persistent 快照入实例 mods），用完即弃 | ✅ |
| 修饰 | `mods` | 实例级（`CardInstance.mods`：enhance 数值/keywords_add/cost_delta，mod_hand 写入的 playable_when_defeated/damage_boost/revive_haste，及 random_enhance 写入的 form_power_delta/form_health_delta（`_attach_form` 结附时叠加形态身材）/revive_on_play（气绝中使用该形态先复活来源式神，`_play_form_card` 读取）/enhance_got（实例已获强化 key 去重表）等读取点键）与 (玩家, card_id) 级持久 store（`PlayerState.card_mods`，"本局游戏每……"类计数） | ✅ |
| 卡牌光环 | `card_auras` | 谓词匹配的卡牌获得关键词/不耗鬼火/数值加成（读取时求值，覆盖已有与新生成的牌）；scope 决定失效时机（"turn"=己方回合开始清除；**"form"=绑定来源式神当前形态、形态离场移除**——心技一体/心剑乱舞，气绝经 _destroy_form 同路径；连续型/属性型光环为扩展锚点）。谓词通道：shikigami（必）/ card_type / **card_id**（"此牌"自指——伺机）/ **turn**（"self"/"opponent" 限定回合方——伺机"敌方回合时此牌+2力量"）；**数值通道 power/shield 为战斗牌战力/一次性护甲加值，可叠加**（多次授予累加，与 keywords 的集合语义不同——刃影叠岚；combat_card_stats 读取时叠加）；**power_ext/shield_ext 数值改读 `PlayerState.ext[key]`**（心技一体"本局每使用过一张'心身炼磨'+1/+1"——出牌记账 lianmo_used_game，读取时求值；手牌数值显示已含光环 ext 通道——第十三阶段，刃影叠岚同解） | ✅ |
| 追加块 | `pre_grants` / `grants` | 可被监测/触发器按索引注入结算的候选效果块（前置/后置） | 🔧 |
| 临时触发 | `temp_grants` / `TempGrant` | 一次性注册的触发（uses 递减移除）；战斗牌携带者绑定该次战斗注册（如不祥之刃击杀抽牌） | ✅ |
| 写入目标 | `to`（hand/persistent/instance/turn） | 写入原语（add_mod）的修饰存储目标：手牌实例 / 持久 store / 来源实例自身（实例计数器，如风符·龙的目标数）/ 回合 store（turn 未实现，"本回合"类由 card_auras 覆盖） | ✅ |
| 数值叠加 | `{"enhance": true, "base": n}` | 步骤 amount 参数形式：base + 实例已装配 enhance（战斗牌战力/护甲提取处解析） | ✅ |
| 动态数值 | `{"shield_of"/"power_of"/"perm_power"/"ext"/"event"/"half_health_of"/"max_power_gap": ...}` | 步骤 amount 参数形式：以来源式神当前护甲 / eff_power / **使用时永久力量快照（{"perm_power": "self", "base": n}——崩山增强，山童的贯通不传导法术伤害）** / ext 计数（鸩 x）、事件 payload 数值（寂寥心象"等量"）、事件角色当前生命一半（毒之华，向下取整）、**历史峰值力量差值（{"max_power_gap": "self"} = max(0, ext["max_power"] - eff_power)——断臂"力量变为本局最大值"）**求值——尘刀按打出瞬间护甲快照战力（本次战斗中不变）、古尘之壁按护甲强化、援护按白狼力量造伤 | ✅ |
| 随机强化 | `random_enhance`（动作） | 按计数次档给同名卡各实例随机赋予一项强化（罗生门之鬼）：控制者 `ext[count_key]` 次数须 ∈ `at`（1/3/5 类档位）；候选 = `tiers` 中 `min` ≤ 次数的项；控制者所有区域及在场形态的同 `card_id` 实例各自经 `mods["enhance_got"]`（key 列表）去重后 rng.choice 一项；写入 mods：keywords_add 集合并入 / form_power_delta/form_health_delta 累加 / 其余键直写（playable_when_defeated、revive_on_play 等开关） | ✅ |
| 随机牌手监听 | `random_aura`（动作） | 从 options 随机赋予一项牌手级监听（豪焰四选一）：各项以 `{once_prefix}_{key}` 为 once_key 去重（全项都有空操作），rng.choice 后转调 player_aura | ✅ |
| 本回合增益通道 | `scope="turn"`（buff_power 参数）/ `turn_power`（ext 键） | 临时力量增益记账到 `ShikigamiState.ext["turn_power"]`，己方回合开始统一从 temp_power 扣减并清零（武士之笛/鼓舞类"本回合"；与 perm 互斥） | ✅ |
| 气绝事件扩展 | `in_combat` / `summon`（on_shikigami_defeated payload） | in_combat：气绝时是否在战斗区（清除 combat_index 前捕获；迁怒/罗生门"消灭敌方战斗区式神"条件）；summon：气绝者是否召唤物（罗生门"基础式神"= summon false 条件），均走条件迷你语言等值兜底 | ✅ |
| 指定式神过滤 | `shikigami`（TargetSpec kind=all 扩展键） | all 分支统一按数据 id 过滤式神（豪焰固定项 buff 茨木、羁绊伤酒吞类"指定式神"；池先取、id 后滤） | ✅ |
