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
| 弃牌 | `discard` | 进入墓地 | 🔧 |
| 移除 | `remove` | 移出游戏（如孟婆），与弃牌区分 | 🔧 |

## 属性与修正

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 生命 | `health` | `base_health + perm_health` 为上限 | ✅ |
| 力量 | `power` | `base_power + perm_power + temp_power` = `eff_power` | ✅ |
| 护甲 | `shield` | 被伤害优先消耗；己方回合开始清除 | ✅ |
| 破甲 | `fragile` | 有独立"给与破甲"流程（非简单负护甲，见 thoughts.txt；Phase 3） | 🔧 |
| 战力 | `combat_power` | 一次性的战斗伤害增加；与鼓舞机制一同实现（第一个大型卡包） | 🔧 |
| 乏力 | `weak` | 战力的负向对应 | 🔧 |
| 永久修正 | `perm_power` / `perm_health` | 气绝后复活保留 | ✅ |
| 临时修正 | `temp_power` | 气绝时清除（临时/永久的区分 = 复活能否保留）；光环类 Phase 3 | ✅ |

## 卡牌数据

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 法术牌 | `spell` | card_type | ✅ |
| 战斗牌 | `combat` | card_type | 🔧 Phase 3 |
| 形态牌 | `form` | card_type | 🔧 Phase 3 |
| 幻境牌 | `field` | card_type（预留） | 🔧 |
| 协战牌 | `reinforce` | card_type（预留；暂不考虑） | 🔧 |
| 觉醒牌 | tag `awaken` | **不是主类型**：任意 card_type + `tags` 含 awaken | ✅ |
| 标签 | `tags` | 自由字符串标记（觉醒、式神专属标记等） | ✅ |
| 稀有度 | `rarity` | R/SR/SSR（良/优/极；抽卡/账号系统预留） | 🔧 |
| 卡包 | `cardpack` | 式神所属版本卡包，即 id 的 xxx 段（1xxxyy） | ✅ |
| 派系 | `faction` | 红莲 red / 紫岩 purple / 青岚 blue / 苍叶 green / 无相 white（`FACTION_COLORS`） | ✅ |
| 同源 | `origin` | 原形/SP 共享 origin，不能同时出战 | ✅ |
| 衍生卡 | `token` | 对局中生成，不可入卡组（序号从 51 开始递增） | ✅ |
| 衍生物 | （kind=summon 的衍生） | 序号从 99 开始递减；必须有从属式神 | ✅ |
| 数据 id | `id` | db 数据与局内对象的数据标识（CardInstance.id / ShikigamiState.id） | ✅ |
| 对象 id | `uid` | 局内对象引用标识（CardInstance.uid；生成物亦发 uid） | ✅ |
| 中立牌 | neutral（`shikigami=None`） | id 9999zzzz、无等级、系统/效果生成 | ✅ |
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
| 免疫 | `immune` | 免疫某类伤害/效果 | 🔧 |
| 倒计时 | `countdown` | | 🔧 |
| 直击 | `direct_hit` | | 🔧 |
| 迅捷 | `haste` | | 🔧 |
| 屏障 | `barrier` | | 🔧 |
| 不屈 | `unyielding` | | 🔧 |
| 眩晕 | `stunned` | | 🔧 |
| 运势 | `luck` | 运势判定 = luck check | 🔧 |
| 增强 | `enhance` | | 🔧 |
| 鼓舞/压制 | `basic_boost` | 出击增减益（正负值） | 🔧 Phase 3 |
| 追猎 | `hunt` | | 🔧 |
| 贯通 | `piercing` | | 🔧 |
| 穿刺 | `pierce` | | 🔧 |
| 吸血 | `lifesteal` | | 🔧 |
| 投射 | `projectile` | | 🔧 |
| 唯一 | `unique` | | 🔧 |
| 先攻 | `initiative` | | 🔧 |
| 必杀 | `fatal` | | 🔧 |
| 远程 | `remote` | | 🔧 |
| 连击 | `combo` | | 🔧 |
| 暴击 | `critical` | | 🔧 |

## 预留机制（译名确认，规则 Phase 3+）

弹回 `returning`、融合 `fusion`、帷幕 `veiled`、昂扬 `exaltation`、坚毅 `tenacity`、占卜 `divine`、灵咒 `invocation`（结附 `attach`）、幻境耐久 `intensity`、充能 `charging`、爆能 `burst`、赐能 `bless`、烹饪 `cook`、战技 `tactical`、蓄力 `charge`、起源 `origin`、戏法 `trick`、专注 `focus`、入夜 `nightfall`、剧毒 `poisonous`（剧毒伤害 poison damage / 中毒 poisoned）、连引 `link`、连锁 `chain`、替身 `substitute`、化身 `incarnate`（混沌化身 `chaos_incarnate`）、启悟 `enlightenment`、坚守 `stand_boost`、加护 `shelter`、蚀印 `etch`、羁绊 `bond`、堆叠 `stack`、商店赏金 `bounty`、变形 `transform`（视作原能力离场、新能力进场，非气绝；气绝时一般解除）。

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
| 调度 | `mulligan` | 游戏开始阶段：返回 1 张起始手牌再随机抽 1，双方各 3 次 | ✅ |
| 半回合 | `turn` | GameState.turn，双方交替 +1 | ✅ |
