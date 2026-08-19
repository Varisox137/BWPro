# 术语表（中文 ↔ 代码标识）

代码与数据库中的命名以此表为准。状态：✅ 已统一 / 🔧 预留（数据可携带，机制未实现）。

## 核心概念

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 牌手 | `player` / `PlayerState` | 局内参战实体：有生命/护甲、可被指定为目标 | ✅ |
| 玩家（账号） | （Phase 2 服务端概念） | 参与对局的账号/连接，不进入 GameState | 🔧 |
| 式神（非召唤物） | `shikigami` | `ShikigamiDef.kind = "shikigami"` | ✅ |
| 召唤物 | `summon` | `kind = "summon"`；气绝即离场、不可升级、入场 1 级（暂定）、生成即进入战斗区 | ✅ |
| 变形物 | `kind = "transform"` | `ShikigamiDef.kind="transform"`：视同召唤物类不入构筑池/测试卡组；由 `transform` 动作变入（继承座位/等级，不继承增减益；变形/还原均为再进场——进场顺序排本队最后，见「进场顺序」行），`untransform`/气绝前2 按 `transform_origin` 快照还原（快照携带的剩余倒计时优先保留、不被能力进场重置初值）；保留"所属式神" `transform_owner`（无法使用原式神的牌） | ✅ |
| 替换物 | `kind = "replace"` | `ShikigamiDef.kind="replace"`（规则评审⑤从 transform 拆出：替换无快照不还原，与变形语义互斥——loader 校验 transform/replace 两 op 各自只能指向对应 kind 的实体，引擎 `_replace_shikigami` 同口径守卫）：由 `replace` 动作换入（继承座次/等级；气绝即气绝、复活仍为替换物），`ext["replace_owner"]` 记原式神 id 放行其全部卡牌；派系=替换物 def faction（觉醒·番茄的"番茄"） | ✅ |
| 实体 | entity / `ShikigamiState` | 局内式神或召唤物；记录 `home_slot`（准备区编号 1-4，召唤物 None） | ✅ |
| 幻境 | `FieldState` / `PlayerState.fields` | 在场幻境实体（card_id/intensity/shikigami）：所属牌手拥有其能力（能力块=幻境牌 def abilities，随队列存续生效）；每方一个幻境队列，进场入队尾（`field_front` 置队首）；牌手受伤减少生命后队首幻境减等量耐久（至多降为 0），耐久 0 消灭出队；伤害来源=所属式神在场则该式神、否则无来源。机制见 rules.md 第三十一章（机制与首批实卡均已落地——03 月夜幻响第二批） | ✅ |
| 气绝 | `defeated` | `ShikigamiState.defeated`；倒计时后复活 | ✅ |
| 濒死 | `dying` | 生命 ≤ 0 但气绝事件尚未结算（伤害流程扣减生命后先标记，气绝时清除）：不受伤害/治疗、不进随机与选择目标池、不能再次被消灭；能力照常（in_play 不变）、可以攻击 | ✅ |
| 离场 | `despawned` | 召唤物气绝或被移动即离场（不视为移动、非气绝、不进复活流程） | ✅ |
| 复活 | `revive` | `revive_countdown` 归零后满血回场 | ✅ |
| 升级 | `upgrade` | 指令；`PlayerState.upgrades` 为本回合剩余升级机会 | ✅ |
| 等级（勾玉） | `level` | 1 至 `config.max_level`；0 级 = 未在场 | ✅ |
| 鬼火 | `orb` | 出牌/出击费用；己方回合开始重置，回合间不清零 | ✅ |
| 能量 | `energy` | `ShikigamiState.energy`（不夜之火批次）：式神级资源，上限 10，气绝保留；**气绝式神回合开始不充能**（气绝无能力，`_turn_start_charge` 跳过；充能晚于倒计时减少，刚复活当回合即 +1——维护者定案）；[充能] 式神己方回合开始 +1（批次顺序：先倒计时后能量）；爆能/能量出击等支付走 `engine._gain_energy/_spend_energy/_can_pay_energy` 统一入口 | ✅ |
| 出击 | `assault` | 指令；耗 1 鬼火 + 每回合唯一出击次数（`assaults_left`），驻留战斗区 | ✅ |
| 移动 | `move` | 指令；入战斗区不攻击；战斗区召唤物被移动 = 直接离场 | ✅ |
| 战斗区 | combat zone / `combat_index` | 每方至多 1 式神驻留；己方回合开始退回准备区 | ✅ |
| 准备区 | bench | 非战斗区式神所在；编号见 `home_slot` | ✅ |
| 进场顺序 | `entry_order`（`ShikigamiState` 字段） | 牌手=0、初始式神从左到右 1-4；再进场排本队最后 = 本队 max+1——变形/还原、召唤物进场、式神替换均视同新进场（答复(2)(3)(6)）；**复活不是重新入场、不更新**（答复(1)）。读取点：回合开始倒计时批次（`_turn_start_countdown`）按 entry_order 升序**动态取序**（批次内变形/还原当轮生效——答复(5)；气绝式神的复活倒计时批次仍按座位从左到右——答复(4)）；护甲/破甲清除、眩晕移除等按角色进场顺序的批次同序 | ✅ |
| 能力进场顺序 | `ability_entry`（`ShikigamiState` 字段）/ `TempGrant.seq` / `GameState.next_ability_seq` | 各能力的进场序号（答复(4)(6)）：基础/觉醒=`ability_entry["ability"]`、形态=`["form"]`、卡牌赋予的能力/一次性临时触发=条目 `seq`，由全局计数器 `next_ability_seq` 赋号；同一事件的能力触发按能力（而非式神）进场顺序排序——`_collect_abilities`/`_collect_temp_grants` 收集时按序号升序。气绝后复活伴随能力重新进场记新序号；还原时式神先进场、各能力依次进场（基础/觉醒→形态→被卡牌赋予；灵咒能力进场预留）；召唤物能力进场未记 ability_entry（报备口径）；序号只作用于上述两收集函数内部排序 | ✅ |

## 区域与卡牌流转

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 牌库 | `deck` | 区域 | ✅ |
| 手牌 | `hand` | 区域 | ✅ |
| 墓地 | `graveyard` | 区域（UI 不可见） | ✅ |
| 除外区 | `exiled` | 标准区域之一（放逐/移出游戏；协战主牌使用后亦进入此区） | ✅ |
| 弃牌 | `discard` | `discard` 动作：弃掉手牌中谓词匹配的牌（所属式神/全部，可限张数），进入墓地 | ✅ |
| 移除 | `remove` | 移出游戏（入 exiled 区域），与弃牌区分——已落地：`remove_deck`（磨牌，牌库顶/底 N 张入 exiled，孟婆系）/`purge_copies`（同名牌手牌+牌库移除，奈何桥头）/`purge_named_card`（命名清除，忘忧的旋律）/`transform_hand_card`（转化原牌 exiled） | ✅ |

## 属性与修正

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 生命 | `health` | `base_health + perm_health` 为上限 | ✅ |
| 力量 | `power` | `base_power + perm_power + temp_power` = `eff_power` | ✅ |
| 护甲 | `shield` | 被伤害优先消耗；己方回合开始清除 | ✅ |
| 破甲 | `fragile`（shield 负值） | 与护甲合并为单一有符号 `shield`（>0 护甲 / <0 破甲）；变化事件以 kind 参数区分方向（rules.md 第六章）：减少只扣已有同向值、获得先抵消反向再盈余同向；受伤时每点破甲使伤害 +1（伤害流程批次 4，贯通修正跳过、穿刺不动）；回合开始双向清除（keep_shield 仅保正值） | ✅ |
| 战力 | `combat_power` | 一次性的战斗伤害增加：专属**鼓舞/出击加成**授予；战斗牌的"+力量"为临时力量（战斗后清除），引擎实现上同经此通道结算（战斗终止点核销，响应插入的经 `_battle_power` 挂账；差异仅在战斗中 eff_power/max_power 读取，现无此类判定） | ✅ |
| 乏力 | `weak` | 战力的负向对应 | 🔧 |
| 永久修正 | `perm_power` / `perm_health` | 气绝后复活保留 | ✅ |
| 临时修正 | `temp_power` | 气绝时清除（临时/永久的区分 = 复活能否保留）；光环类 Phase 5 | ✅ |
| 攻击后到期强化 | `attack_buffs` / `attack_buff`（动作） | 挂账式临时强化（临时力量 + 授予关键字）：自身作为攻击者的战斗终止点核销（rules.md:176"直到攻击后"）；气绝清空 | ✅ |
| 护甲保留 | `keep_shield` | `ShikigamiState.keep_shield`：护甲不再于己方回合开始移除（觉醒·兵俑） | ✅ |
| 破甲保留（式神级） | `keep_fragile` | `ShikigamiState.keep_fragile`：该式神的破甲不再于己方回合开始移除（keep_shield 对称机制；肿胀体质——形态结附期间经 `keep_fragile` 动作授予、形态离场解除；与敌方觉醒·清姬 `keep_enemy_fragile` tags 通道叠加判定） | ✅ |

## 卡牌数据

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 法术牌 | `spell` | card_type | ✅ |
| 战斗牌 | `combat` | card_type | ✅ |
| 形态牌 | `form` | card_type | ✅ |
| 幻境牌 | `field`（card_type） | card_type=field + `intensity`（耐久，必填正整数）/ `field_front`（进场置队首旗标，缺省队尾）：使用后先"召唤幻境"入所属牌手幻境队列、再执行进场效果，本体入墓地（报备口径）。首批实卡已落地（03 月夜幻响第二批 20 张）；在场实体的关键字经 `field_keywords` 声明（不经 `keywords`，loader 不校验 KEYWORDS 子集——health_floor_one/deck_top_play/piercing 已生效、veil 仅标记） | ✅ |
| 协战牌 | `reinforce` / `options` / `choice` | card_type=协战主牌（shikigami 主 + shikigami2 副双归属）；`options` = 两个子选项 token 卡 id（[0] 主侧 [1] 副侧）；打出时 cmd 带 `choice`（0/1）选择 → 合法性（出战/等级/鬼火/目标）按子卡 → 生成 token 入手并视作从手牌使用（完整使用事件流程）→ 主牌离手进 `exiled` 区（不进墓地）；[羁绊] 不进关键词表，实现为子卡普通 steps；**羁绊触发条件 = 使用此牌时对应式神在场（等级 ≥1 且未气绝）**——step 级 `condition: {shikigami_active: <式神id>}` 门控（generate 类），倒计时增减/发起攻击/形态进场类由 op 空操作语义隐式满足 | ✅ |
| 觉醒牌 | `subtype = "awaken"` | **不是主类型**：任意 card_type + subtype（rules.md:502）；法术觉醒使用事件流程：墓地 → `on_before_awaken`（觉醒前，即时）→ 替换式神能力 → 法术本身效果 → `on_awakened`（觉醒后，延时）→ 永久身材增益（`awaken_power`/`awaken_health`） | ✅ |
| 觉醒（状态） | `awakened` | `ShikigamiState.awakened` = 觉醒牌 id；能力改读该牌 `abilities` 块；气绝/复活保留（但气绝时能力不在场——觉醒门控类判定要求未气绝） | ✅ |
| 觉醒能力 | `abilities` | `CardDef.abilities`：觉醒牌携带的能力块（替换式神基础能力） | ✅ |
| 形态能力 | `abilities`（形态牌） | 形态牌携带的能力块：结附期间生效（与觉醒能力并存，觉醒替换不覆盖；如风符·瞬的回合结束自毁） | ✅ |
| 标签 | `tags` | 自由字符串标记（觉醒、式神专属标记等） | ✅ |
| 稀有度 | `rarity` | R/SR/SSR（良/优/极；抽卡/账号系统预留） | 🔧 |
| 卡包 | `cardpack` | 式神所属版本资料包，即 id 的 vv 段（式神 1avvss / 卡牌 1avvvvcc） | ✅ |
| 异画 | alt art（id 的 a 位） | 式神/卡牌/中立牌 id 的第 2 位（'0' = 默认卡面）；同一数据的不同卡面共享规则数据，为 GUI/美术资产预留 | 🔧 |
| 平衡性版本 | `versions` | yaml 顶层仅 id/name/versions 三项，规则数据全部在 versions.history 的版本快照中（每条 = date + 完整数据，不按差量；首条 date = 发布日期）；`best` = 维护者标记的"历史最强"版本日期（仅元数据，解析不用）；加载/解析结果的 `version` = 所取快照 date；卡牌的 shikigami 由 id 推导注入、cost 默认 1，均不入数据；解析规则见 db/versioning.py。真实数据起点 = 20191212 公测开服（历史平衡性数据源见 card_data_raw.md「平衡性调整」节） | ✅ |
| 环境 | env_date / `CardDatabase.at_date` | 对局/构筑指定的平衡性日期：各 id 取不晚于该日期的最晚版本逐条合并，早于发布日期则该 id 不存在（不可构筑/使用）；联机房间分标准模式（固定最新，不可更改）与自由模式（create 带 env_date；房主在双方未准备时可 `env` 更改），卡组文件按卡组记录 env（v3），热坐恒用最新；环境输入/显示支持别名（经典/不夜之火/月夜幻响/沧海刀鸣等）与 8/6 位日期，解析见 db/envs.py；**客户端派系显示分界** `FACTION_DISPLAY_MIN_DATE=20210330` + `show_faction(date)`（db/envs.py——deckbuilder 与对局渲染按环境日期隐藏派系列，早于分界不显示派系；外来式神手牌按中立色） | ✅ |
| 派系 | `faction` | 红莲 red / 紫岩 purple / 青岚 blue / 苍叶 green / 无相 white（`FACTION_COLORS`） | ✅ |
| 同源 | `origin` | 原形/SP 共享 origin，不能同时出战 | ✅ |
| 衍生卡 | `token` | 对局中生成，不可入卡组（序号从 51 开始递增）；**不标稀有度**（原版衍生牌无稀有度，loader 校验 token 卡须缺省 rarity） | ✅ |
| 委托牌 | `subtype = "quest"` | 三目专属子类型（衍生号段 51-66：紧急委托 51-54 / 今日委托 55-61 / 线索 62-66）：专属子类型登记表 `db/schema.py EXCLUSIVE_SUBTYPES`（loader 校验只能出现在所属式神的牌上）；使用数由委托账本 `quest_used` 记账；机制见 rules.md 第三十三章 | ✅ |
| 衍生物 | （kind=summon 的衍生） | 序号从 99 开始递减；必须有从属式神 | ✅ |
| 数据 id | `id` | db 数据与局内对象的数据标识（CardInstance.id / ShikigamiState.id） | ✅ |
| 对象 id | `uid` | 局内对象引用标识（CardInstance.uid；生成物亦发 uid） | ✅ |
| 中立牌 | neutral（`shikigami=None`） | id 9avvvvvv（9 + 异画位 + 6 位数字，自 999999 递减）、无等级、系统/效果生成 | ✅ |
| 使用位置 | `play_from` | play_card 参数，默认 hand，任意区域可扩展 | ✅ |
| 使用方式 | `play_method` / `PlayMethod` | 多择子选项；仅保留核心方式、参数可变（`param`，如爆能{2}）。扩展字段（不夜之火批次）：爆能英文=burst；`energy_cost`（int=爆能N 额外支付 N 能量 / "all"=爆能X 消耗全部能量、0 能量不可选；方式 `effects` 追加到基础 effects 后，多档独立支付累计）、`keywords`（以该方式使用时临时授予卡牌关键字——森之力爆能档得[瞬发]） | ✅ |
| 气绝时可用 | `playable_when_defeated` | 卡牌字段；与是否响应牌无关 | ✅ |
| 仅气绝时可用 | `only_when_defeated` | 卡牌字段：硬门控——式神存活时主动使用报错、响应收集直接跳过（心即归处）；需搭配 `playable_when_defeated` | ✅ |
| 半成品式神 | `wip`（ShikigamiDef） | 仅基础数据/卡牌未齐的式神（04 沧海刀鸣包 9 个骨架式神——三目已落地去标）：不进构筑可选池（available_shikigami）与测试卡组（_pick_test_ids）；卡数不足 8 种的成品式神（纸人武士/天邪鬼军团）不受限 | ✅ |
| 实例修饰 | `mods` | CardInstance 级差异（同名卡可不同），目前认识 `cost_delta`/`revealed`（已展示，见「结算与事件」） | ✅ |

## 关键词

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 瞬发 | `fast` | 每（半）回合双方各自第一张瞬发牌不消耗鬼火 | ✅ |
| 响应 | `trigger` | 敌方回合满足条件必发，其余要求照常 | ✅ |
| 疾速 | `swift` | 若有出击次数则改为消耗 1 次出击次数而不消耗鬼火 | 🔧 |
| 突袭 | `strike` | 使一个式神仅在下一次出击且与敌方式神战斗时获得增益 | 🔧 |
| 免疫 | `immune` | 免疫某类伤害/效果：战斗伤害免疫（带作用域的 `battle_immunity`，见本节末说明）、敌方非战斗伤害免疫（grant_immunity kind="effect"+from_side，觉醒·山童）、消耗式免疫（scope="once"，桃红簇簇）、牌手全伤害免疫（kind="all"，舍生）均已实现——全部伤害免疫判定挂点=伤害事件"护甲计算后"批次优先级 3（**只看最终受伤者**，修正定案：转移/改非伤害结算完后判定；屏障/护甲先于免疫参与计算）；通用免疫（免疫效果/指定）🔧 | ✅（伤害类） |
| 倒计时 | `countdown` | 式神级倒计时能力（一名式神至多 1 个，新注册替换旧的；不论基础/觉醒/形态来源）：三要素 `countdown_initial`（初值）/ `countdown_block`（归零效果块，`EffectBlock.countdown` 非 None 的能力块或形态牌 `countdown_effects`）/ `countdown_once`（一次型），另记来源 `countdown_source`（基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id）。注册时机：能力进场（对局开始/升至 1 级/复活）、觉醒替换、形态结附、`set_countdown` 动作；形态离场仅清除形态授予的，气绝清除。归零（rules.md ch12 修订版）：先即时插入结算（此时仍为 0，块内对自身 `countdown_delta` 修正为 -0）→ 记账 `countdown_history` → 循环型重置/一次型移除 | ✅ |
| 直击 | `direct` | 战斗事件"确定目标前1"：若本次战斗无目标，被攻击者改为敌方牌手（无视敌方战斗区式神）；追猎已选定目标时直击被覆盖 | ✅ |
| 迅捷 | `haste` | 一次性：出击的鬼火消耗处不消耗鬼火，随后失去一个一次性迅捷；仍消耗出击次数 | ✅ |
| 屏障 | `barrier` | 一次性：伤害事件"护甲计算前3"将伤害值改为 0 并移除一个实例 | ✅ |
| 不屈 | `unyielding` | 生命>1 且伤害≥当前生命时保留 1 点生命；一次性不屈触发后全部消耗，持续/永久不屈保留可再触发；生命=1 不触发 | ✅ |
| 眩晕 | `stuns` / `is_stunned` | 眩晕条目列表（式神 `ShikigamiState.stuns` / 牌手 `PlayerState.ext["stuns"]`）：普通 `{"kind":"normal","turn":n}`（己方回合结束批次移除非本回合施加者）、持续 `{"kind":"lasting",...}`（不夜之火批次落地——按来源结束时机解除：`until_event` 事件名列表 + `watch` 看护式神座次/watch_id，事件涉及看护者即解除，`engine._release_lasting_stuns`；`apply_seq`/`apply_uid` 记施加时点的事件序号/卡牌 uid 防自解除——英雄无畏"直到鸦天狗使用牌、攻击或气绝"，气绝走现有清理）；眩晕=列表非空。门控：式神禁出击/主动/响应用牌、牌手全体禁出击；气绝清除。`stun` 动作施加 | ✅ |
| 运势 | `luck` | 运势判定 = luck check：块级门控 `EffectBlock.luck`（int=成功才结算 / `{"x":X,"on":"fail"}`=失败才结算）+ 步骤级 `luck_roll` 动作（x/judge/then/force_x1_if）；六时机管线与并行同步推进见 rules.md 第二十七章 | ✅ |
| 增强 | `enhance` | 卡面[增强]话术，无统一机制（enhance-design.md 核心决策）：已多通道落地——`CardDef.triggers` 游离触发块（card_in_hand 门控，血怒/灵力）、`conditional_mods` 装配点动态实例修饰（牙牙我们走/汤盆冲撞）、`conditional_keywords` 读取时谓词求值（白刃/意外之喜）、实例修饰随牌转移 | ✅ |
| 鼓舞/压制 | `basic_boost` / `assault_boosts` | 出击加成：`basic_boost` 动作登记于牌手（`PlayerState.assault_boosts`），下一次出击全部消耗——力量挂攻击后到期强化（战后核销）、护甲获得后保留；战斗牌不消耗。卡牌关键字 `inspire` 为卡面[鼓舞]标记（效果以 basic_boost 结算——桃之夭夭）。**随机关键字槽**：basic_boost 参数 `keyword_random=[...]`——授予时均等随机一个存入玩家级槽 `ext["boost_keyword"]`（至多一个、后授予替换已有；消耗加成的攻击中临时授予攻击者、随加成消耗清除，no_consume 旗标下保留；consume_assault_boosts 同步转移、经 attack_buffs 随本次战斗移除——惊鸿之舞"和一个随机效果"）。压制（负值）🔧 | ✅（鼓舞） |
| 充能 | `charge` | 实体关键字（不夜之火批次）：己方回合开始时该式神能量 +1（上限 10，批次顺序先倒计时后能量；气绝者不充能、刚复活当回合即 +1——维护者定案；先天经 `ShikigamiDef.keywords` 入永久类别——小鹿男/烟烟罗/日和坊/镰鼬）；能量见「核心概念」能量行 | ✅ |
| 追猎 | `hunt` | 有目标的战斗：战斗牌持追猎主动使用时须选择 1 名合法敌方式神为战斗目标（不能选牌手；无合法目标则不能使用）；式神/形态持追猎主动出击可任选合法敌方式神为目标（不选 = 默认无目标战斗）；发起者无远程照常移入战斗区；`launch_attack` 类"使己方式神发起攻击"是无目标战斗，不吃追猎 | ✅ |
| 贯通 | `piercing` | 对式神的非反击伤害超过其当前生命时，溢出部分改对所属牌手造成。是"伤害原因"的属性：式神持有的贯通仅传导至其战斗伤害与基础/觉醒/形态能力（含形态倒计时、延迟"会"）伤害；卡牌效果伤害不继承，除非步骤显式声明 `piercing: true`（实现：`ExecContext.is_ability` + damage/random_damage 动作缺省继承）；与连击交互——连击第一段击杀被攻击者时贯通同样改打对方牌手（无贯通则终止战斗、后续时机不结算；维护者定案，见「连击」） | ✅ |
| 穿刺 | `pierce` | 造成伤害前（伤害事件批次0，即时时机）移除受伤者所有护甲/屏障——与本次伤害是否最终生效（免疫/归零/屏障）无关；适用于任意来源伤害（含非战斗伤害） | ✅ |
| 穿刺（仅护甲变体） | `pierce_armor` | 伪关键字（碎岩 20191212，卡面为描述文本不出现括号关键字）：与穿刺同点（伤害事件批次0）处理，仅清零受伤者正值护甲、不触屏障/不动破甲；后期版本卡面即[穿刺]，可视作该变体的更名（维护者已定案） | ✅ |
| 吸血 | `lifesteal` | 伤害流程"造成/受到伤害后"（延时，优先级 1 锚点）：来源式神持有则生成以其控制者牌手为执行者的恢复生命事件（治疗量 = 该次伤害值，走 `Game.heal` 管线；实现 `Game._queue_lifesteal` 合成 _Pending 入队） | ✅ |
| 投射 | `projectile`（目标池） | 优先敌方战斗区式神，战斗区为空则退回敌方牌手 | ✅ |
| 唯一 | `unique` | | 🔧 |
| 先攻 | `initiative` | 先攻阶段造成伤害、交战阶段不再造成（结构已实现，暂无卡牌持有） | ✅ |
| 必杀 | `lethal` | 不是伤害属性：伤害事件造成伤害后，来源持必杀则令受伤者在该次伤害事件后延时结算气绝（剩余生命 >0 不提前标濒死；与伤害本身导致的气绝并行结算——victims 队列追加"必杀"条目，`check_defeated` 幂等；伤害被免疫未造成则不触发） | ✅ |
| 帷幕 | `veil` | 不能成为敌方出击/用牌的合法目标：choose/出击目标过滤（`pool_refs(targeted=True)`）；已确定目标在效果结算时持帷幕则取消目标相关效果（`targets.resolve` 再校验，仅卡牌效果、能力不受）；有目标的出击发起前目标获帷幕则不发起战斗、有目标的非出击战斗则改为无目标战斗（`_battle_flow` 发起前再校验）；全体/随机效果不取对象不受影响 | ✅ |
| 远程 | `remote` | 不进入战斗区、不受先攻及交战阶段的反击伤害 | ✅ |
| 连击 | `combo` | 先攻阶段与交战阶段各造成一次战斗伤害；第一段击杀被攻击者按先攻阶段气绝分支同样处理（维护者定案）：攻击者有[贯通]→被攻击者改打对方牌手（第二段照常），否则终止战斗、后续时机不结算（无第二段、无 on_after_assault）；被攻击者在重选求值点已复活→第二段打回原目标 | ✅ |
| 暴击 | `critical` | | 🔧 |
| 激怒 | `enraged` | 状态关键字：己方被激怒式神中存在满足出击合法性者时，其他无激怒式神不能出击；在发起战斗的流程（战斗准备前）移除攻击者的激怒。（现无实卡授予——原授予者尘缚之阵 2026-08 起按开服 raw 移除该效果；引擎机制与合成数据测试保留） | ✅ |
| 弹回 | `rebound` | **卡牌级**关键字：使用后（效果/战斗结算完毕、牌在墓地时）移回手牌而非留墓（`_rebound_check`，主动与响应两路径同检；蛇行击）；回手后可再次打出，持久修饰快照按实例去重不重复合并 | ✅ |
| 庇佑 | `blessing` | 一次性：抵消一次敌方来源的法术伤害（法术牌效果伤害，伤害事件 `spell` 标记；≠ 非战斗伤害——式神能力伤害不抵消，答复(7)），抵消后失去；判定在伤害流程护甲计算后、扣减生命前、不屈之前——被护甲完全吸收/屏障归零的伤害不消耗（森佑灵矢羁绊；灵咒抵消半侧随灵咒机制引入） | ✅ |
| 伤害转化（伪关键字） | `damage_to_fragile` | 卡面不出现的关键字通道（清姬先天，永久类别入列死亡不清）：来源式神持标记且受伤者当前无破甲时，其伤害在事件生成点全额转化为等量破甲（不再视为伤害；受伤者已有破甲正常造伤；与毒蚀转化同位置，converted 防循环） | ✅ |
| 额外鬼火（伪关键字） | `extra_orb_cost` | 引擎级伪关键字（跳跳妹妹先天，`ShikigamiDef.keywords` → perm_keywords）：该式神出击/使用其战斗牌需额外消耗 1 点鬼火（出击共 2 火）；[迅捷]出击、[瞬发]/[不消耗鬼火]用牌时全免（定案(11)） | ✅ |
| 不能攻击 | `no_attack`（ShikigamiDef 字段） | 仅召唤物/衍生物类：不能发动攻击（冰墙）——出击校验拦截、效果发起的攻击（launch_attack）为空操作 | ✅ |
| （引擎级） | `keep_attack_buffs` | 攻击后到期强化不因攻击移除（残心；卡面不出现此关键字） | ✅ |
| 能力伪关键字 | `power_if_field` / `power_per_field` / `power_if_shield` / `power_equal_shield` / `power_eq_health` / `heal_defeated_countdown` / `damage_defeated_countdown`（schema `ABILITY_PSEUDO_KEYWORDS`） | 属"式神能力"而非卡牌/实体关键字：写在式神基础能力 keywords 或觉醒牌 keywords 中，觉醒时引擎把基础式神的伪关键字移除、改为授予觉醒牌（perm 类别）——power_if_field 有幻境 +1 力量（泷夜叉姬）/ power_per_field 每幻境 +1 力量（觉醒·泷夜叉姬）/ power_if_shield 有护甲 +1 力量（久次良）/ power_equal_shield 力量=护甲（觉醒·久次良）/ power_eq_health 力量=当前生命（觉醒·人面树，覆写口径同 power_equal_shield）/ heal_defeated_countdown 可对气绝式神恢复生命、改为气绝倒计时 -1（樱花妖基础/觉醒共用）/ damage_defeated_countdown 可对气绝式神造成伤害、改为气绝倒计时 +1（觉醒·樱花妖）；身材类读取时求值（stat_aura 通道，实时光环动态跟随——定案(1)）、grant_keyword scope=turn 可临时授予（白骨之盾）；原 `field_stack`/`field_ability_stack` 作废删除（辉夜姬叠加改 field_merge 动作通道，定案(6)） | ✅ |
| 效果授予伪关键字 | `combat_base_health` / `assault_any_target` / `friendly_combat_heal`（schema KEYWORDS） | 引擎级伪关键字（卡面不出现），由卡牌效果授予或形态牌 keywords 携带：combat_base_health 以自身当前生命（而非力量）造成战斗伤害——攻击与反击同口径（神木庇佑）；assault_any_target 出击可指定攻击者以外任一角色（含己方式神/牌手，_cmd_assault 分支；飘零之舞）；friendly_combat_heal 攻击己方角色改为使其恢复等量于伤害的生命、且无反击（飘零之舞） | ✅ |
| 幻境实体关键字 | `field_keywords`（CardDef 字段） | 幻境牌声明进场实体持有关键字（不经 `keywords`，loader 不校验 KEYWORDS 子集；召唤时拷贝到 FieldState，离场失效）：health_floor_one 己方生命不降到 1 以下（铃鹿山的秘宝）/ deck_top_play 牌库顶视同手牌、等级 1 不耗火、以此法使用受 2 伤（彼岸归航——出牌管线 play_from=deck 通道）/ piercing 幻境能力伤害贯通（星轨——`_ability_piercing` 并入 ctx.field.keywords）/ veil 幻境[帷幕]（方圆之备 field_op grant_keyword veil——已实现，定案(11)：不能成为**敌方**效果的目标，field_op 取对象类 pick=first/max_intensity 在 side="enemy" 时排除；无目标效果与己方效果不受影响） | ✅ |

**关键字持久性三类**（每类均为可重复多重集，存于 `ShikigamiState`）：

| 类别 | 字段 | 语义 |
|---|---|---|
| 一次性 | `one_shot_keywords` | 触发后移除（迅捷/不屈/屏障/庇佑为天然一次性）；气绝时清除 |
| 持续性 | `keywords` | 触发后不移除（远程/贯通/连击/穿刺/先攻/连击等）；气绝时清除 |
| 永久 | `perm_keywords` | 气绝时不清除 = 复活后自动重新获得；永久是授予方式而非关键字属性 |

此外**战斗伤害免疫**不是关键字：带作用域的修饰（`ShikigamiState.immunities` 条目 + `battle_immunity` / `grant_immunity` 动作），只免疫 kind ∈ (combat, counter) 的伤害，作用域由授予效果指定（仅本战斗 / 含嵌套战斗 / 本回合）。

## 预留机制（译名确认，规则 Phase 5+）

融合 `fusion`、昂扬 `exaltation`、坚毅 `tenacity`、占卜 `divine`、赐能 `blessing`、烹饪 `cook`、战技 `tactical`、蓄力 `charging`、起源 `origin`、戏法 `trick`、专注 `focus`、入夜 `nightfall`、剧毒 `poisonous`（剧毒伤害 poison damage / 中毒 poisoned）、连引 `link`、连锁 `chain`、替身 `substitute`、化身 `incarnate`（混沌化身 `chaos_incarnate`）、启悟 `enlightenment`、坚守 `stand_boost`、加护 `shelter`、蚀印 `etch`、羁绊 `bond`、堆叠 `stack`、商店赏金 `bounty`。（充能/爆能已于不夜之火批次落地——充能=`charge` 关键字、爆能=`PlayMethod.energy_cost`，见「核心概念」「结算与事件」；幻境/幻境耐久已于月夜幻响批次落地——card_type=field、耐久=`intensity`，见 rules.md 第三十一章与「核心概念」；灵咒 `invocation`（结附 `attach`）已于灵咒框架批次落地——框架无实卡数据，见 rules.md 第三十二章与「结算与事件」；蓄力英文名 `charging` 为维护者定案预留，与充能 charge 区分。）

## 结算与事件

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 效果块 | `EffectBlock` | when/mode/timing/condition/steps/priority（伤害分层优先级：默认 1；约定 1=改非伤害/2=转移/3=伤害注入——伤害归零时后续 priority≥2 的待触发块跳过，见 rules.md 伤害管线） | ✅ |
| 动作 | `op` / Action | `core/actions.py` 注册表原语 | ✅ |
| 事件 | `event` | `core/events.py` ∪ `db/events.yaml` | ✅ |
| 即时时机 | （EVENT_TIMING=insert 的事件类别） | 有临时队列：同时机能力全部触发后依次执行（如"攻击时"） | ✅ |
| 延时时机 | （EVENT_TIMING=queue 的事件类别） | 无队列：触发的能力加入当前效果队列，其结算完后执行（如"造成伤害后"） | ✅ |
| 时机类别 | `EVENT_TIMING` | 各事件的默认时机（core/events.py）；EffectBlock.timing 可单卡覆盖 | ✅ |
| 插入结算 | `insert`（timing） | 立即插入当前结算 | ✅ |
| 队列结算 | `queue`（timing） | 入队延迟结算 | ✅ |
| 可中断 | `interleaved`（mode） | 步骤间允许其它效果结算 | ✅ |
| 不可中断 | `atomic`（mode） | 步骤连发 | ✅ |
| 结算次序总表 | （rules.md 第一章小节） | 一个能力"何时执行"的六旋钮判定链：事件默认类别 → 单卡 timing 覆盖 → priority 分层 → 能力进场序号 → horizon 单元绑定 → 排水模式；通用次序规则的唯一出处，其余章节只写事件语义。timing 覆盖 / 非伤害管线 priority / horizon 为**特例机制**（受限使用，新卡先用先讨论并登记总表节；现状清单见该节） | ✅ |
| 延时单元绑定 | `_Pending.horizon` / `Game._drain_horizon` / `Game._horizon_stack` | 延时待结算项 emit 时记下当前结算单元 id，只在所属单元完成后冲刷、中途排水跳过；现用于觉醒·山风复制（on_countdown_reduced）、灵咒"抽到触发"挂起、抽牌事件移动挂起（draw_move）三处 | ✅ |
| 目标 | `target` / `Ref` | Ref(player, shikigami?) | ✅ |
| 随机生成 | `generate`（动作） | 从 db 按谓词（所属式神/主类型）随机生成卡牌置入区域（发 uid、可重复、池内不含衍生卡；杀念/觉醒·一目连） | ✅ |
| 直接消灭 | `destroy` / `destroy_form`（动作） | 非伤害消灭：生命归零走气绝流程 / 消灭当前结附的形态（直接消灭免疫为扩展锚点） | ✅ |
| 调度 | `mulligan` | 游戏开始阶段：返回 1 张起始手牌再随机抽 1，双方各 3 次 | ✅ |
| 半回合 | `turn` | GameState.turn，双方交替 +1 | ✅ |
| 延迟能力 | `delayed` / `delay_grant`（动作） | 绑定式神的一次性延迟能力（会）：条目 {block, chosen, uses, secret, scope}，事件匹配时先触发后执行、收集即消耗；气绝清除（变形离场保留）；scope="turn" 时己方回合开始清除（魔音扰心类）、scope="play" 时该次出牌结算结束清除（黑羽之刃类"本次使用期间"）；secret=True 时选择目标对敌方保密（联机脱敏抹除对手视角的 chosen） | ✅ |
| 伤害上限 | `cap_damage`（动作） | 改写伤害事件中可变伤害对象的数值：to="shield" 时至多为受伤式神当前护甲（森罗之阵）；**to=<整数> 时面板值封顶该定值（雪融之时"每次至多只会受到3点伤害"，护甲吸收照常在后结算）**；须挂 on_damage_start 等含 damage payload 的时点批次 | ✅ |
| 战斗区锁定 | `combat_lock`（tags） | 尘缚之阵：携带者（兵俑）在战斗区且敌方战斗区有式神时，会使敌方战斗区式神被替换的效果无效且不能进行（不看发起者）——召唤召唤物无效、准备区式神不能发起无远程的战斗（出击/战斗牌）、响应战斗牌插入移入不可用、enter_combat / force_enter_combat 效果无效；退回准备区不受限；效果发起的战斗暂无来源 | ✅ |
| 免疫直接消灭 | `destroy_immune`（tags） | 结附带此标记形态的式神在战斗区时，`destroy` 动作对其无效（日志记"免疫了本次消灭"）；伤害消灭/形态消灭不受影响。（现无实卡携带——原携带者尘缚之阵 2026-08 起按开服 raw 移除；引擎机制与合成数据测试保留） | ✅ |
| 退回准备区 | `retreat`（动作） | 目标式神移回准备区（与 `enter_combat` 对称；仅战斗区式神有效，召唤物退回即离场） | ✅ |
| 强制进场 | `force_enter_combat`（动作） | 强制目标进入其战斗区（鬼之手类"将敌方准备区式神移入战斗区"，targets 经 enemy_bench 池选择）；移动语义同 enter_combat，尘缚锁定下（移入会替换被锁战斗区式神）静默无效；`random_pick`=候选中随机取 1 名（随机不取对象、不吃帷幕）；`if_combat_empty`=目标所属玩家战斗区非空则整体跳过（鬼之手空发） | ✅ |
| 牌手级持久监听 | `player_aura`（动作）/ `PlayerState.auras` | "本局游戏"类能力附着于牌手（豪焰）：事件触发即结算块，不限次数、跨气绝保留；`scope="game"`（默认）本局有效 / `scope="turn"` 仅本回合（己方回合开始清除，鼓舞类）；`once_key` 防重复登记、缺省可叠加；emit 时按注册顺序收集（`_collect_player_auras`，卡牌触发器之后） | ✅ |
| 灵咒 | `invocation` / `InvocationDef` | 结附于式神或卡牌上的具名效果实体（rules.md 第三十二章；沧海刀鸣预备，框架已落地、无实卡数据）：定义注册表 `CardDatabase.invocations`（不经 yaml 加载，测试直接注入）；字段 name/unique/power/health（效果类身材增减益=**类光环层**：结附时刻快照入条目、eff_power/max_health 读取时实时合计，不借 temp 通道——reset_stats 清除后立即继续生效（评审④定案）、移除即失效无双重扣减）/abilities（能力类触发块，进场序号=结附时刻 ability_seq，随 `_collect_abilities` 收集）/draw_trigger（结附卡牌的"抽到触发"块）；运行时条目 `ShikigamiState.invocations` / `CardInstance.invocations`（{"name","player"=来源所属牌手,"source","power","health"}） | ✅（框架） |
| 结附（灵咒） | `attach_invocation`（动作）/ `Game.attach_invocation` | name 指定灵咒；targets=式神结附 / uid=卡牌结附（targets 忽略）；流程：结附→唯一性移除→`on_invocation_attached`（延时，预留）；气绝/离场经 `_detach_invocations` 移除 | ✅（框架） |
| [唯一] / [式神唯一] | `unique` / `shikigami_unique`（InvocationDef.unique） | 灵咒唯一性（结附之后移除，新结附自身保留；同源=来源所属牌手相同）：unique=双方全场（式神+手牌/牌库中的卡牌）同源同名移除；shikigami_unique=仅该式神上同源同名移除（卡牌结附不生效）；none=不唯一 | ✅（框架） |
| 抽到触发 | `draw_trigger`（InvocationDef）/ `_proc_invocations_on_move` | 结附卡牌的灵咒在抽牌动作入手（reason="draw"，deck→hand）时入队延时结算（控制者=来源所属牌手）并移除；非抽牌入手静默移除；爆牌先触发再转墓地；调度换出直接移除不生效；多张抽牌顺序 = **倒序**（后发先至定案：第 2 张的移动+灵咒先结算，后抽的牌先入手、hand_seq 更小——严格递归 + 抽牌事件单元 drain） | ✅（框架） |
| 抽牌前 | `on_before_draw`（事件） | 即时时机，每层抽牌事件一次，payload {player, count=当前层 X, reason}——"获得卡牌前"锚点；抽牌为严格递归结构（移动事件挂起到本抽牌事件单元、单元完成时 drain，rules.md 第十九章）；"抽牌前"触发的终止（明心/觉醒·书翁/空库判负）在此挂点判定（`_draw_terminate`，绑定步骤之前，终止则整次 on_draw 不再发） | ✅ |
| 牌移动后 | `on_card_move` / `on_card_moved`（事件） | move_card 双锚点：即时 / 延时（灵咒挂点）；payload {player, uid, card, from_zone, to_zone, reason}——reason：draw/generate/search/pick/hand_cap/None（rules.md 第十八章二节） | ✅ |
| 灵咒结附后 | `on_invocation_attached`（事件） | 延时时机（预留）；payload {player=来源所属牌手, target: Ref\|None, uid: int\|None, invocation, source} | ✅ |
| 战斗结束追加攻击 | `followup_attack`（动作）/ `_battle_followups` | 登记战斗结束后的追加攻击（地狱之手类）：整场战斗终止点核销后先结算积累的延时能力（登记在其中），再依次结算——目标为生命最低敌方式神（平手随机、帷幕不可选；无合法目标改无目标战斗），不享受原战斗牌战力/关键字；可多次登记链式排队；按触发事件 battle payload 登记（气绝后延时能力在战斗弹栈后结算） | ✅ |
| 倒计时增减 | `countdown_delta` / `set_countdown`（动作） | `countdown_delta`：倒计时 ±（无能力/为 0 修正 -0，≤0 走归零流程）；`set_countdown`：注册新倒计时能力（initial/steps/once，替换旧的；record=True 记录事件所用卡牌到式神 `ext["recorded_card"]`） | ✅ |
| 凭空自动使用 | `recast_recorded` / `auto_use`（动作） | 凭空生成 `ext["recorded_card"]` 记录卡 id 的同名牌并免费自动使用（不耗鬼火、非从手牌、无主动目标；大天狗倒计时）；**auto_use{card_id}：凭空生成指定法术牌自动使用（目前仅支持法术牌），`inherit_target=True` 目标继承本效果的卡牌选择目标（流霰）**；`gain_orb`：获得鬼火 | ✅ |
| Step 级条件 | `Step.condition` | 结算时以条件迷你语言求值，不满足则跳过该 step（op 自身声明 condition 参数者——如 delay_grant——仍作 op 参数传递） | ✅ |
| 扩展数据 | `ext` | 少数卡专用的运行时数据（`ShikigamiState.ext` / `PlayerState.ext`，约定键见下表） | ✅ |
| 治疗（恢复生命） | `Game.heal` / `heal`（动作） | 治疗事件流程：治疗反转判定（heal_reversal）→ on_before_heal（即时）→ 实际治疗量 = min(治疗量, 已损失生命) → 增加生命 → on_heal（延时，**实际恢复 0 也触发**，amount=0）→ on_after_heal（延时，**仅实际恢复 > 0 触发**）；濒死/气绝者不受治疗。挂点口径："过量治疗转化"（海坊主）、"为牌手恢复生命时"（灵能）挂 on_heal；"你恢复生命时"= 己方任一角色（含牌手）实际恢复（青坊主基础/禅心/觉醒、吸血姬基础/血怒/觉醒·吸血姬——维护者答复(1)：0 治疗不触发）挂 on_after_heal | ✅ |
| 过量治疗 | `overheal`（on_heal payload 键） | max(0, 治疗量 − 实际治疗量)；海坊主"过量治疗转化护甲"通道——能力块挂 on_heal 以 {overheal_ge: 1} 门控，转化量取 payload overheal（满血治疗 overheal=全额，照常转化） | ✅ |
| 治疗反转 | `heal_reversal`（tags） | 法界唯心：其控制者在场形态含此标记时，该方效果对**敌方**目标的恢复生命改为走伤害管线造成等量伤害（受伤害批次/免疫影响）；对己方目标恢复不受影响（`_field_form_has_tag` 扫描在场形态 tags） | ✅ |
| 护甲获得增益标记 | `shield_gain_boost`（tags） | 欢愉之音：其控制者在场形态含此标记时，**其控制者方**角色获得护甲量 +1、**其敌方**角色获得破甲量 +1（gain_shield 结算流程内判定，`_field_form_has_tag` 同治疗反转扫描） | ✅ |
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
| 战斗/非战斗伤害免疫 | `grant_immunity`（动作） | scope="turn"：目标式神免疫战斗伤害到当前回合结束——以回合号记账（immunities 条目 {"turn": n}），过期条目于回合开始清理（`_start_turn` 双方过滤，防显示残留——不可饶恕用）；scope="perm"：持续在场期间有效（气绝清除、复活重新授予）；scope="once"：消耗式——命中任意一类伤害即免疫一次并移除（桃红簇簇）；kind="effect" + from_side="enemy"：非战斗伤害免疫、只免疫敌方来源（无来源或己方来源不免疫——觉醒·山童，`_effect_immune`）；kind="all"：免疫全部伤害——牌手目标条目存 `PlayerState.immunities`、按 turn 回合号记账+回合开始清理，`_player_immune`（舍生）；式神目标搭配 scope="once"（桃红簇簇，`_combat_immune`/`_effect_immune` 匹配 kind 扩 "all"）；kind="fragile_source"：免疫当前持有破甲的**敌方式神**造成的任意种类伤害（牌手来源不免疫——"有破甲的敌方式神"明文，维护者定案确认；伤害类别不限；`_fragile_source_immune`；scope="form" 随形态离场清除——霸主）。**全部免疫判定挂点=伤害事件"护甲计算后"批次优先级 3**（2026-08 修正定案"免疫只看最终受伤者"：改非伤害/伤害转移结算完、伤害未终止后对最终受伤者判定；屏障/护甲计算/贯通修正先于免疫参与计算；原"伤害开始时"挂点作废） | ✅ |
| 下次战斗作用域授予 | `scope="next_battle"`（grant_keyword / grant_immunity 参数） | 战斗外授予、绑定目标下一次作为**攻击者**发起的战斗——挂账 `ext["next_battle_keywords"]` / `ext["next_battle_immunities"]`，战斗开始经 `_resolve_combat` 消费（关键字授予/免疫条目绑定该战斗 id、走战斗终止点移除；气绝清除）。倒计时能力块内无战斗上下文，"本次战斗获得/免疫"类用此（山风基础能力[不屈]/斩[必杀]/觉醒·山风免疫战斗伤害——维护者定案(6)(8)）。斩/觉醒·山风范围经维护者**改判**统一：持续到该次战斗事件结束后、**含期间插入的嵌套战斗**——原 grant_keyword 的 lethal 特判通道（仅限该次战斗本身记账、不带入嵌套）已删除，统一走实例授予（覆盖答复(10) 前半） | ✅ |
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
| 倒计时事件 | `on_countdown_proc` / `on_countdown_reduced`（事件） | proc=倒计时能力归零生效时（**即时**时机、先于归零块结算——烈/刚/斩类监听授予的增益/关键字赶上归零块发起的攻击；payload {shikigami: Ref, source, once}）；reduced=倒计时每次减少（延时时机；payload {shikigami: Ref, original 原始减少量 / actual 实际=修正到剩余 / by_card 是否卡牌效果 / natural 是否回合开始批次自然减少}——势按 original 取值（定案(5)）；觉醒·山风共享 2026-08 二轮定案：范围=任何己方减少倒计时效果（含能力来源，`natural_not` 门控、自然减少不共享），无倒计时能力的未气绝式神被减少也发事件（actual=0、original=减少量、状态不变），复制延时界=引起该次减少的结算单元（`_Pending.horizon` + `Game._drain_horizon`，能力块完即复制、卡牌完才复制）；原始-实际之差累计写入块内暂存 `countdown_overkill`——突"过量效果"动态数值 {"memo": "countdown_overkill"}） | ✅ |
| 鼓舞吸收 | `consume_assault_boosts`（动作） | 鼓舞战力/护甲转为本次结算战力/护甲并清空鼓舞（灵矢贯虹"消耗所有鼓舞"用）；**鼓舞随机关键字槽（`ext["boost_keyword"]`，惊鸿之舞）同步转移**——临时授予来源式神、经 attack_buffs 随本次战斗结束移除 | ✅ |
| 破甲消耗记账 | `_DamageEvent.fragile` | 伤害批次实际消耗（增伤）的破甲量记账，进 on_damage payload `fragile` 键——本引擎破甲受伤即消耗（蚀刃毒羽已改用 fragile_echo，payload 键保留备用） | ✅ |
| 生成子类型过滤 | `subtype`（generate 参数） | 生成候选池限式神 + 子类型（妖琴师觉醒法术池：100124 spell/awaken） | ✅ |
| 法术回响 | `spell_echo` / `spell_echo_recast`（动作） | 登记于来源式神 `ext["spell_echo"]` 的"本回合"序列：持有者以外的式神（含敌方）从手牌使用法术时（同式神法术每回合至多触发一次），依次凭空免费使用 sequence 下一张（每张至多一次；不耗鬼火、play_from=void、triggered=auto、choose 目标随机合法、用后入墓地；照常 emit on_card_played 触发持有者"使用法术牌时"能力，但回响自身不自连锁）；`once_key` 防叠加；己方回合开始清除（涅槃业火） | ✅ |
| 效果发起攻击 | `launch_attack`（动作） | 令指定式神发起一次额外攻击：不耗鬼火/出击次数、准备区自动进战斗区、走正常战斗流程（含反击，无战斗牌加成）；气绝/未在场空操作；shikigami="self" 取来源式神，**"target" 取卡牌选择目标所指式神（可为敌方——来打我呀"使一个敌方式神立刻发动攻击"）**，否则按数据 id 定位（鲁莽、刃影叠岚羁绊）；**`at="chosen"` 定向攻击**：战斗目标取本效果的卡牌选择目标（冰封[羁绊]"雪童子对其发动一次攻击"）；`no_attack` 召唤物（冰墙）为空操作 | ✅ |
| 反击贯通 | `counter_piercing`（动作） | 登记到当前战斗上下文（`_battle_counter_piercing`）：该战斗被攻击方的反击伤害具有贯通（rules.md:201 贯通修正批次的反击例外；战斗终止点清除；主动使用由战斗牌流程提取绑定，响应插入使用作为普通动作登记——伺机） | ✅ |
| 破甲双倍 | `double_damage_vs_fragile`（动作，战斗牌专用提取步） | 对有破甲的式神造成的战斗伤害翻倍——按**[暴击]时机**（伤害事件"扣减生命前2"挂点，engine.py:2895 注释锚点）：仅本张战斗牌发起的战斗内、攻击者本人、kind=combat（反击不翻倍）、victim=持破甲式神才 ×2；嵌套/插入战斗按战斗 id 精确匹配不继承（维护者定案——义道）。[暴击]关键字本体未实现，本挂点为预留锚点 | ✅ |
| 力量覆写 | `power_override`（动作） | on=True 时目标式神力量视为 0（覆盖基础+永久+临时+战力全部，`eff_power` 覆写层，标记存 `ext["power_zero"]`）；on=False 解除；形态离场/气绝自动清除（笨拙） | ✅ |
| 伤害增幅 | `boost_damage`（动作） | 在伤害时点批次改写事件中可变伤害对象的数值 +amount（只增；须挂 on_damage_start 等 payload 含 damage 的批次，配合 {source_shikigami: self, kind: effect} 类条件——焚羽"非战斗伤害+1"） | ✅ |
| 鬼火条件 | `orb_ge`（条件运算符） | {orb_ge: n}：控制者当前鬼火 ≥ n（青行灯"若你有剩余鬼火"） | ✅ |
| 字段不等 | `{字段_not: 值}`（条件运算符） | 事件字段 ≠ 给定值；{shikigami_not: null} = 所用牌为专属牌（非中立牌）——觉醒·凤凰火"己方式神使用法术牌" | ✅ |
| 消灭者牌手 | `victim_player`（语境目标） | 气绝事件语境目标（TargetSpec kind="context"）：被消灭式神所属牌手，敌己两向（引燃"若消灭则再对它的牌手造成 2 点伤害"） | ✅ |
| 敌方准备区 | `enemy_bench`（目标池） | 敌方全部准备区式神（与 enemy_combat 对应——崩山准备区段） | ✅ |
| 基础关键字 | `keywords`（ShikigamiDef） | 式神先天关键字：`build_player` 初始化时入 `perm_keywords`（永久类别：气绝不清除、复活自动重新获得——山童先天[贯通]） | ✅ |
| 生命下限钳制 | `min_health_turn`（ext 键，bump_ext 置位） | "本回合生命不会降到 1 以下"（狂啸）：伤害批次"扣减生命"处把伤害压到至多 当前生命-1，生命已为 1 时压为 0 提前终止（同护甲完全吸收；0 伤不触发受伤能力）；半回合作用域——任一回合开始双方清除（`_start_turn`）；[响应]经 `response` 覆盖块挂 on_damage_start，先于钳制置位 | ✅ |
| 战斗区空置条件 | `combat_empty`（条件运算符） | {combat_empty: friendly\|enemy}：指定方战斗区没有式神（friendly=控制者方 / enemy=对方——取值统一，原 self/opponent 死分支已删；偷袭 20200423"敌方回合结束时战斗区没有式神"响应、霜风"若敌方战斗区没有式神"step 条件） | ✅ |
| 回合结束响应排序 | `_suppress_responses`（引擎标志） | 回合结束：on_turn_end 即时能力照常触发，但手牌响应收集被抑制——当前回合方的回合结束延时效果（队列）先结算完，再以合成 on_turn_end 事件收集对方手牌响应（答复3；现无实卡使用，机制保留）；延时效果改变局面（如战斗区变得非空）则响应条件复查不再满足 | ✅ |
| 响应窗口 / 空闲点 | `_response_window` / `_response_used`（引擎字段） | 原版"每个空闲点限一张响应牌"落地（规则评审⑨）：窗口=两次玩家动作之间的完整结算（apply 的 play_card/assault/upgrade/end_turn 指令开启新窗口，end_turn 级联的对方回合开始同属本窗口；choose 续答/debug 不开）；窗口内**同一时机**（事件名）每名玩家至多成功结算一张响应牌（`_response_used` 记玩家→(窗口, 事件名) 名额，复查失败不占）；不同时机=不同空闲点可各一张；**并行事件同时机响应合并**——同名事件的多次 emit 共享名额只触发一次（rules.md 第二章） | ✅ |
| 响应战斗牌新战斗 | （`_settle_response_card` 分支） | 无当前战斗、或**非"（被）攻击时"时机**触发的响应战斗牌（偷袭"当敌方战斗区式神气绝时"，挂 on_shikigami_defeated + in_combat payload）不插入当前战斗，按完整战斗事件流程发起一次新战斗（正常反击；战斗中触发即嵌套战斗）；攻击方按卡牌所属玩家解析（atk_ref 不取 state.active——响应方可能非当前回合方） | ✅ |
| 有目标战斗扩展 | `target` 扩展键 `battle` / `optional` | battle=true：非追猎战斗牌的 choose 目标作为战斗目标（同追猎的有目标战斗管线、帷幕不可选——天翔鹤斩"改为攻击一个敌方准备区式神"）；optional=true：合法目标池为空时可不带目标使用（退化为无目标普通战斗） | ✅ |
| 精确等级生成 | `level` / `max_level` / `exclude_self`（generate 参数） | level：int 或 "shikigami"：后者按 shikigami 参数所指式神当前等级精确匹配生成（醉酒当歌羁绊"获得一张茨木童子当前等级的战斗牌"；所指式神未出战/未在场空操作）；max_level="source"：生成牌等级 ≤ 来源式神当前等级（吾即正义 20200423"不大于自身等级"）；exclude_self=True：候选池排除与来源同 id 的牌（"其他法术牌"） | ✅ |
| 战斗牌数值不提取 | `no_extract`（step 参数） | 战斗牌的 buff_power/gain_shield(self) step 缺省提取为战力/一次性护甲在效果步之前结算；标 no_extract 则不提取、按步骤顺序执行（醉酒当歌"先自伤 3 再获得等量护甲"——前置结算会被自己的自伤消耗） | ✅ |
| 鬼火储存 | `orb_store`（tags） | 觉醒·青行灯：己方在场有已觉醒且觉醒牌含此标记的式神时，回合开始鬼火不清零、改为累加并封顶 4 点（`min(4, orb+gain)`；`_orb_stored` 扫在场式神觉醒牌 tags；结算见 rules.md 回合流程步骤 5 注记） | ✅ |
| 结算中交互选择 | `pending_choice` / `choose`（指令） / `deck_top_pick`（动作） | 效果结算中挂起等待玩家作答：deck_top_pick 检视牌库顶 count 张选 1 入手再洗牌、重复 times 次（times 可为 {"orb": true} = **1 + 效果结算时剩余鬼火**，0 火仍执行基础 1 次——维护者答复；青灯夜谈）；挂起点存 `_suspended` 续点（内存态，随服务端房间的 Game 实例存活——客户端断线不丢，重连 resync 全量 state 带 pending_choice 可续答）、`GameState.pending_choice` 记 {kind, options, remaining}；pending 期间 apply() 只接受 choose 指令；触发式（triggered）块不挂起、空发即弃；联机 sanitize 对非选择方把 options 脱敏为等长占位（room.py），CLI/net 以 `choose <序号>` 作答；`field_summon_pick`（残阳无影"选择召唤一个幻境"：候选=读牌者场上幻境牌，>1 只挂起、单只自动，作答键 choice=卡牌数据 id，CLI/net 各有交互分支，超时随机作答并结束回合）；回合超时先随机作答到底再走常规超时流程（否则回合无法收尾、计时器不重启——room._on_timeout） | ✅ |
| 重复执行 | `repeat`（动作） | 子步骤组重复 count 次（int 或 {"orb": true} = **1 + 效果结算时控制者剩余鬼火**：基础 1 次 + 每点剩余鬼火重复 1 次，0 火仍执行基础 1 次——维护者答复；吸魂灯；**或 {"ext": key, "base": n} = base + 控制者 `PlayerState.ext[key]` 计数**——流霰"本局每从手牌使用过一张'雪球'额外重复一次"，读 snowball_used_game；repeat/deck_top_pick/generate 次数形式共用 `_orb_count`），同块上下文共享 ctx.memo；clear_orb=True 重复后一次性清空控制者鬼火（2→0 不经过 1） | ✅ |
| 鬼火消耗/清空 | `consume_orb` / `clear_orb`（动作） | consume_orb：扣控制者鬼火 amount（不灭之火；不视作使用牌）；clear_orb：一次性清空一方鬼火（side="self"/"opponent"，月食类"清空敌方的鬼火"——月食卡不入数据，机制可用）；均 emit on_orb_changed（old→new 单事件，清空不经过中间值） | ✅ |
| 鬼火变化事件 | `on_orb_changed` / `_pay_orb` | 即时时机（insert），payload {player, old, new, reason}；每处变化点发出：回合开始获得、使用牌/出击/响应付费（付费点先于效果结算，响应可插入效果前）、gain_orb/consume_orb/clear_orb/清空。条件通道示例："当敌方鬼火变为 1 时" = {player: opponent, new: 1}（月食类响应，合成卡测试） | ✅ |
| 生命设置 | `set_health`（动作） | 目标牌手生命直接设为 amount、钳制 [1, max_health]（轮回"生命变为 10"——X=0 按原文仍可使用；非治疗非伤害、不触发对应事件） | ✅ |
| 直接升级 | `level_up`（动作） | 目标式神等级 +amount（不走升级次数/不受升级阶段限制、封顶 3；百闻一得）；overflow_draw=True 时已 3 级改为抽 1；0 级未在场/气绝空操作；实际升级后 emit `on_upgrade`（与指令升级同事件——犬神"升级时"类触发两来源均生效；on_upgrade payload 含 `target`=Ref 供 {target_shikigami: self} 匹配） | ✅ |
| 复活（动作） | `revive`（动作） | 复活目标气绝式神（走 `Game._revive` 完整复活流程；不灭之火"返回场上"前置步骤） | ✅ |
| 形态重新结附 | `reattach_form`（动作） | on_form_destroyed 事件中被消灭的形态**同一实例**从墓地找回重新结附（不灭之火；实例不在墓地/来源离场或气绝空操作，配合 revive 使用） | ✅ |
| 弃牌指定 | `card_id`（discard 参数） | 按数据 id 定向弃手牌（百闻一得"弃一张明灯"——无明灯不弃但后续升级仍执行，维护者答复） | ✅ |
| 延迟能力绑定选择目标 | `bind="chosen"`（delay_grant 参数） | 延迟能力改登记到本次选择目标式神上（默认登记在来源式神；沧海之盾"使一个己方式神获得……当他造成伤害时"） | ✅ |
| 数值下限条件 | `{字段_ge: n}`（条件运算符） | 事件数值字段 ≥ n 的通用形式（overheal_ge: 1 = 存在过量治疗，海坊主转化门控；与 orb_ge 控制者鬼火专用键语义不同）；**事件无该字段时回退读控制者 `PlayerState.ext[key]`**（on_play 步 ctx.event 为空——修复狂风刃卷 yaohu_damage_count_ge 恒不触发的存量 bug） | ✅ |
| 惊鸿分支条件键 | `friendly_defeated_exists` / `player_health_le` / `player_missing_health_ge` / `combat_occupied`（条件运算符） | 控制者有气绝式神（同 friendly_defeated 池口径——复活项前置）/ 控制者牌手当前生命 ≤ n（牌手护甲项前置）/ 控制者牌手已损生命 ≥ n（牌手治疗项前置）/ 一方战斗区有式神（friendly\|enemy，combat_empty 的反向——战斗区增益项前置）；均惊鸿之舞分支触发前置 | ✅ |
| 月夜幻响条件键 | `hand_lacks` / `enemy_deck_le` / `friendly_armor_ge` / `player_health_ge`（条件运算符/conditional_keywords 算子） | {hand_lacks: <卡牌id>}=控制者手牌中没有该数据 id 的牌（天井下"若你手牌中没有'妖怪屋·灵力'"——on_turn_start/on_turn_end 双块 generate；觉醒·天井下之泉版同构）；{enemy_deck_le: n}=敌方牌库张数 ≤ n（本包条件[增强]共用：意外之喜 conditional_keywords [瞬发]、牙牙我们走/汤盆冲撞 conditional_mods）；{friendly_armor_ge: n}=控制者有在场式神护甲 ≥ n（焕然之音抽牌门控）；conditional_keywords 算子 player_health_ge=己方牌手当前生命 ≥ n（血香"若你生命值为30"——按 ≥ 判定，thoughts(3) 定案）；20200928 起同键亦入条件迷你语言（match_condition/Step.condition——血香免疫战斗伤害增强，battle_immunity step 带 condition {player_health_ge: 30}，鸩羽条件免疫先例；与 player_health_le 对称）。事件字段条件值可为列表=任一命中（kind: [combat, counter]——初拥吸血限战斗伤害、反击也算，答复(9) 定案） | ✅ |
| 致命伤害条件 | `{victim_lethal: true}`（条件运算符） | 事件 victim 当前生命 ≤ 事件伤害值 amount（"将受到致命伤害"——舍生响应门控） | ✅ |
| 战斗区受害者条件 | `{victim_in_combat: true\|false}`（条件运算符） | 事件 victim 是否其控制者战斗区式神（true="战斗区式神被攻击时"——沧海之盾响应门控；false=准备区式神——桃红簇簇"准备区式神受到致命伤害"） | ✅ |
| 角色目标池 | friendly_character / friendly_others_character / any_character / friendly_lowest_level / side_of_last_heal | 含牌手的"角色"池：己方角色（祝福之水）/ 己方其他角色（蹈海）/ 任一角色（治愈之水、佛光）/ 己方等级最低式神（并列全入池，百闻一得）/ 上一步 heal 目标所属方全部角色（佛光，仅 kind=all，读 memo last_heal_targets） | ✅ |
| 半数护甲数值 | `{half_shield_of: "self"\|"source"}`（动态数值） | 取所指式神当前护甲一半（向下取整；沧海之盾"获得等同于其护甲一半的生命"类）；`_step_amount` 同时支持 `{memo: key}` 读取块内暂存数值（巨浪 X = last_damage_total） | ✅ |
| 检索牌库 | `search_deck`（动作） | 从控制者牌库随机检索一张指定式神的牌置入手牌，然后洗牌库（花信风；shikigami="target" 缺省按卡牌选择目标所指式神，"self"=来源式神，或数据 id；仅实际检索到才洗牌，未命中不洗——维护者定案）；`card_id` 按数据 id 精确检索（鸿运当头羁绊检索指定卡） | ✅ |
| 进出战斗区事件 | `on_enter_combat` / `on_leave_combat` | 式神进入/离开战斗区（延时时机，payload {player, shikigami: Ref}）：`_enter_combat`/`_retreat` 发出（被换下的驻留者经 _retreat 发 leave）；**气绝移动不经 _retreat 不发 leave**；桃红簇簇"进入或离开战斗区时恢复2生命"挂点 | ✅ |
| 气绝触发能力 | `trigger_when_defeated`（EffectBlock）/ `{holder_defeated: bool}`（条件运算符） | 能力收集门控：离场（despawned）恒跳过；气绝者仅带此标记的能力块放行收集（觉醒·犬神"气绝时也能触发"）；0 级未在场仍走 trigger_when_not_in_play。holder_defeated 判能力持有者当前是否气绝（配合前者做"仅气绝时触发"——存活不触发） | ✅ |
| 动态关键字 | `conditional_keywords`（CardDef） | 满足条件的条目把 keyword 加入实际关键字（读取点 `_card_keywords`，对手中/生成的一切副本生效）：`level_ge`=所属式神当前等级 ≥ n（心身炼磨"犬神 2 级获得[瞬发]"）；`if_alive`=所属式神在场未气绝（桃华灼灼"若桃花妖未气绝，此牌得[瞬发]"）；**`enemy_stunned_nonempty`=场上有[眩晕]的敌方角色（霜舞型条件瞬发，活局面判定——统一读取 `_enemy_stunned_count`）**；**`enemy_hand_all_revealed`=敌方有手牌且全部已展示（"若敌方手牌全部已展示，此牌得[瞬发]"——心灵迷宫）**；**`enemy_fragile_ge2`=敌方场上存在破甲 ≥2 的角色（白刃"若敌方式神有 2 点以上破甲，此牌得[瞬发]"）**；式神未出战条件不满足 | ✅ |
| 状态目标池 | `friendly_injured` / `friendly_defeated`（目标池） | 己方在场且已受伤（生命 < 上限）的式神（丰实/盛开"己方受伤式神"）/ 己方已气绝式神（未离场、等级 ≥1；桃华灼灼/桃语春风复活池）；`TargetSpec` 扩展键 `{"random": n}`：kind=all 解析结果中随机取 n 个（rng.sample，不足取全部；配合 repeat 每轮重解析重随机——盛开"再重复2次"） | ✅ |
| 炼磨计数 | `lianmo`（tags）/ `lianmo_used_game` | 出牌统一记账：tags 含 lianmo 的牌（心身炼磨）使用时 `PlayerState.ext["lianmo_used_game"]` +1（本局累计不清）；心技一体 card_aura power_ext/shield_ext 数值通道读取 | ✅ |
| 动态身材光环 | `stat_aura`（动作）/ `stat_auras`（`PlayerState.ext` 注册表） | 连续型"读取时求值"修饰：不写死数值，`Game._refresh_stat_auras` 在手牌数变化（move_card）/事件发出（emit）/战斗快照前等读取点全量重算缓存（`ext["dyn_power"]/["dyn_health"]`，eff_power/max_health 读取时叠加）；kind="self_hand_count"（持有者每有一张其他手牌 +1/+1——闻世）/"enemy_fragile_power"（敌方有破甲式神降等量力量——火吻之蛇）/**"enemy_stunned_exists"（场上有[眩晕]的敌方角色时持有者 +power/+health——雪国之子；活局面判定）/"ext_power"（持有者 +力量 = 控制者 ext[ext] 计数 × power 倍率——雪融之时[增强]，计数引擎记账读取时求值）**/"ids_power"（控制者在场实体中数据 id ∈ ids 者 +power 永久力量光环；scope="game" 结附牌手、本局有效不清除、跨召唤保留——坐下"番茄永久+1力量"，对番茄召唤物与变形番茄同生效，可叠加；ids_power 条目无 holder 不被重算跳过——存量 bug 修复）**；scope="form" 绑定来源式神当前形态、形态离场移除（`_destroy_form` 同路径）；登记时持有者当前生命按新上限回满；动态上限降低时钳当前生命（不触发事件） | ✅ |
| 抽牌替换 | `draw_to_pick`（tags） | 明心：在场形态含此标记时，回合开始抽牌改为检视牌库顶 3 张选 1 置入手牌（choose 作答后洗牌库；牌库不足 3 张全部检视，为空走空库分支——`_turn_start_draw`） | ✅ |
| 战中调度 | `mulligan_hand`（动作）/ `mulligan_pick`（pending kind） | 调度控制者手牌至多 times 次：经 pending_choice 挂起，choose 作答（uid=手牌换该张——`_swap_hand_card` 核心与开局调度共用；uid 缺省/次数用尽提前结束并洗牌库、续跑挂起块）；`shuffle: false` 结束不洗牌（云游）；**强索通道 `auto=True`**：无交互——对 `target_side`（self/opponent）手牌按入手顺序（hand_seq 升序）取前 times 张候选自动逐张调度（`only_revealed=True` 仅"已展示"牌为候选），有实际调度才洗牌库 | ✅ |
| 空库燃烧 | `deck_out_burn`（tags） | 觉醒·书翁：己方在场已觉醒且觉醒牌含此标记时，空库抽牌改为对敌方牌手造成 10 点伤害（每张空抽各触发一次），自己不判负（`_deck_out_burner`，draw_cards 空库分支） | ✅ |
| 破甲保留 | `keep_enemy_fragile`（tags） | 觉醒·清姬：对方在场已觉醒且觉醒牌含此标记时，己方角色的破甲不在回合开始清除（护甲照常；`_fragile_kept_by_enemy`，扫描模式同 orb_store） | ✅ |
| 爆牌 | `hand_cap`（move_card 统一路径） | 移入手牌后超出手牌上限时该牌转而置入墓地——抽牌/生成/调度等所有进手路径共用（维护者定案） | ✅ |
| 先攻快照时机 | （`_battle_flow` 攻击时后重读） | 攻击方战斗关键字快照与动态身材缓存在"（被）攻击时"结算后重读——"攻击时获得[先攻]/[贯通]"类授予赶上本场战斗判定（原携带者火吻之蛇 2026-08 随 20191212 回退去先攻块，现无实卡携带，机制保留） | ✅ |
| 装配快照去重 | `_mat`（实例 mods 键） | `_materialize` 持久修饰快照记账上次合并值：同名卡回手/再次装配只补差值、不重复合并；快照键扩至 form_power_delta/form_health_delta，生成点统一快照（弹回配套） | ✅ |
| 半回合力量覆写 | `power_zero_turn`（ext 键，power_override scope="turn"） | 力量覆写半回合作用域：任一回合开始双方清除（min_health_turn 先例） | ✅ |
| 检索扩展 | `card_type` / `max_level` / `direct_play_power_ge` / `shuffle`（search_deck 参数） | card_type 限定卡牌主类型；max_level="target"：卡牌等级 ≤ 选择目标式神当前等级（"不高于该式神等级"）；direct_play_power_ge=n：选择目标式神存活且力量 ≥ n 时改为直接使用（不耗鬼火、play_from=deck、triggered=auto；目前仅支持形态牌直接结附给选择目标——森佑灵引"若该式神力量≥4且存活，改为直接使用"；置入手牌/直接使用前按生成点统一快照 _materialize）；shuffle=false 命中也不洗牌库（森佑灵引——raw 无"然后洗牌库"句，区别于花信风，维护者定案） | ✅ |
| 生成友方其他式神 | `shikigami="friendly_others"`（generate 参数） | 逐各其他己方式神（出战队列中除来源外，含 0 级/气绝——万象之书"其他己方式神"按出战队列全体取池，维护者定案）各随机生成一张其卡牌；generate `_spawn` 重构统一生成路径 | ✅ |
| 目标池与过滤扩展 | `friendly_combat` / `enemy_fragile_or_combat`（池）/ `power_le` / `has_fragile` / `highest_power`（TargetSpec 过滤键） | friendly_combat=己方战斗区式神；enemy_fragile_or_combat=敌方有破甲的在场式神或敌方战斗区式神（或关系——无往）；power_le=n 过滤力量 ≤ n、has_fragile 过滤持破甲者（spec_pool_refs 统一校验/展示——判官夺命/勾魂索）；highest_power=true 按力量最高过滤（读 eff_power，并列全保留交由 random 键均等取——惊鸿之舞"力量最高"项）；exclude_shikigami=<式神 id> 从池中排除指定式神（白骨之盾"其他友方式神"排除久次良本人） | ✅ |
| 随机取样复用 / 气绝纳入 | `memo` / `include_defeated`（TargetSpec 键） | memo=<key>：kind=all+random:n+memo 时同块后续步骤复用首次取样 refs（惊鸿之舞分支 13 力量与[贯通]落同一式神、分支 14 力量与生命落同一组——维护者定案）；include_defeated=true：friendly/enemy_shikigami 池纳入未离场气绝式神（惊鸿之舞分支 14"随机两名己方式神无论是否气绝"） | ✅ |
| 护甲/破甲目标过滤 | `shield_nonzero` / `strippable`（TargetSpec 过滤键） | shield_nonzero=true：仅持有护甲或破甲的角色可选（骚声"移除一个角色上的护甲或破甲"）；strippable=true：醒转目标口径——己方持护甲**或**敌方持破甲的角色可选（妖怪屋的醒转"移除一个己方角色上的护甲或敌方角色上的破甲"） | ✅ |
| 条件算子扩展 | `shikigami_has_form` / `card_transformed` / `combat_nonempty` | {shikigami_has_form: <式神id>}=控制者的式神（按数据 id）结附着形态；{card_transformed: <卡牌id>}=控制者持久 store 中该同名卡已"变为"；combat_nonempty 为 conditional_keywords 判定键（己方战斗区有人时获得关键字——闪烁"战斗区有式神时得[瞬发]"，engine:284 行，式神未出战不满足） | ✅ |
| 语境目标扩展 | `damaged_player`（TargetSpec context 键） | 事件中受到伤害的牌手（on_player_damaged payload 的 player 下标 → Ref；夺命"消灭受到判官战斗伤害的角色"的牌手分支） | ✅ |
| 数值键扩展 | `{"hand_count_half": "controller"}`（动态数值） | 效果归属玩家当前手牌数的一半（向下取整；判官"手牌数的一半"类 X） | ✅ |
| 牌手直接消灭 | destroy 动作 targets 可为牌手 Ref | 消灭牌手 = 直接获胜：牌手气绝、对局进入待结束（夺命增强变后"消灭受到判官战斗伤害的角色"的牌手分支；维护者定案） | ✅ |
| 延迟能力次数 | `uses`（delay_grant 参数） | 延迟能力可触发次数（默认 1；uses=99 表示回合内不限次） | ✅ |
| 生命增益钳制 | buff_health 负值 | 上限下调（负值，墨笔夺魂"降低生命"）：同步钳当前生命到新上限；上限降至 ≤0 时目标气绝（维护者定案） | ✅ |
| 战斗绑定临时触发 | `battle`（on_player_damaged payload 键） | 牌手伤害事件补战斗上下文键——战斗牌绑定注册的 temp_grants（uses 递减）对牌手伤害也生效 | ✅ |
| 幻境定向 op 组 | `field_op` / `summon_field` / `redirect_to_field` / `boost_change` / `field_rebound` / `draw_until` / `field_merge`（动作） | field_op：对幻境增减耐久/消灭/授关键字——pick=self/others/all/random/max_intensity/self_field，action=destroy/grant_keyword（残阳无影/星轨自毁/方圆之备授帷幕）；summon_field：效果直接召唤幻境——shikigami 限定、pick=random/all（按幻境牌**数据 id 升序**依次召唤，定案(15)）/choose（玩家交互选择——pending_choice kind="field_summon_pick"，选项>1 才挂起，作答键 choice=数据 id，残阳无影定案(2)）、intensity 覆写入场耐久（耐久取值链：指定值>卡牌标注值+实例 intensity_boost）；redirect_to_field：伤害改由幻境承受（"护甲计算后"批次**优先级 1**=改非伤害类，定案(7)）——**首个同名代受**（同名多个只由队列首个代受，定案(10)）、field_shikigami 定位控制者首个该式神幻境（竹取物语代受=首个她的幻境，定案(14)）、field_card 限定首个指定牌 id 幻境（永劫轮回②按伤害类别分代：新月非战斗/日轮战斗）、max_amount 上限；boost_change：on_before_field_intensity 可变 change 改量（月坠"获得耐久效果+2"）；field_rebound：幻境消灭前回手并失去该能力（荒海）；draw_until：抽至所抽牌等级总和 ≥n（血华散 level_sum_ge）；field_merge：辉夜姬叠加合并（定案(6)——挂 on_summon_field/on_ability_enter 能力块，保留队列最后一个她的幻境、耐久设置为总和、merge_abilities=true 时按幻境牌 id 去重合并能力块、消灭其余） | ✅ |
| 幻境配套参数 | `intensity_boost`（search_deck）/ `card_type`+`random_pick`（discard）/ `field_intensity`（repeat count/动态数值）/ `field_count`（动态数值） | search_deck 检索幻境入手写 mods 耐久 +n（五道难题）；discard 按卡牌类型定向弃牌、random_pick 随机代替选择（余辉——暂定见 questions.md）；动态数值 {"field_intensity": "self"}=来源幻境当前耐久（星轨投射、星陨重复次数）、{"field_count": "controller"}=控制者幻境数（鲸骨·开、stat_aura field_count_stats——星辰之境每幻境 +1/+1） | ✅ |
| 己方伤害口径 | `source_side: friendly` + 自伤 source=己方牌手自身 | 火照之路/彼岸归航/觉醒·彼岸花效果等对己方牌手的自伤以己方牌手自身为伤害来源（非 None），计入"己方式神/卡牌/牌手效果造成的伤害"链；ext `self_damage_taken` 记账——conditional_mods 算子 `self_damage_taken_ge` 打出装配时求值（死亡之花[增强]）；牌手受伤挂 `on_player_damaged`（payload player=下标）与式神受伤 `on_damage`（victim=Ref）区分 | ✅ |
| 幻境条件键 | `friendly_field` / `friendly_field_intensity_ge` / `hand_card_type` / `field_summon_distinct_ge` / `_le`（通用后缀） | {friendly_field: true}=控制者有任一在场幻境（曜断/鱼鳞之备门控、conditional_keywords 算子同名）；{friendly_field_intensity_ge: n 或 {ge, shikigami:"self"\|id}}=存在耐久 ≥n 的幻境（shikigami 限定所属式神——竹取物语"若辉夜姬的幻境耐久>=20"，定案(14)）；{hand_card_type: <主类型>}=手牌中有该主类型的牌（余辉 play_condition 使用前提，定案(9)）；{field_summon_distinct_ge: n 或 {count, shikigami:"self"\|id}}=本局召唤过的不同名幻境数（ext `field_summon_ids` 记账——觉醒·辉夜姬五幻境增强）；`_le` 后缀=事件 payload/控制者 ext 值 ≤n（黄泉花境 amount_le: -1"耐久降低时"，与既有 `_ge` 对偶）；幻境能力收集器键 `field_self`（该幻境自身）/ `field_intensity_ge`（耐久 ≥n 才生效——"若此牌耐久>=10"系）；**步级专用键 `field_intensity_ge`**（执行器消费：读触发来源幻境 ctx.field 当前耐久，同块内多次判定共享首次判定快照（ctx.memo）——月坠"然后若耐久>=30"收窄判定，定案(13)）；conditional_keywords 算子 `deck_field_distinct_ge`=牌库不同名幻境牌数 ≥n（五道难题[瞬发]） | ✅ |

**ext 约定键登记表**（少数卡专用数据不进 State 底层字段，统一收纳于 `ext`）。
键的**宿主与清除时机集中登记于 `core/registry.py` `EXT_KEYS`**（唯一事实来源；
引擎在己方/任一方回合开始、己方回合结束、气绝、形态离场等边界按登记表统一
自动清除（`Game._clear_ext`），有副作用的键挂清除钩子 `_ext_clear_<key>`；
新 ext 键必须先登记）：

| 键 | 载体 | 说明 |
|---|---|---|
| `countdown_history` | `PlayerState.ext` | 本局倒计时能力生效序列（归零生效后追加来源 id：基础=式神 id / 觉醒=觉醒牌 id / 形态=形态牌 id；大合奏、风韵雅乐用） |
| `recorded_card` | `ShikigamiState.ext` | 大天狗记录的法术牌数据 id（`set_countdown(record=True)` 写入；气绝丢失） |
| `fragile_to_damage` | `ShikigamiState.ext` | 获得破甲转化为等量伤害（"获得破甲前"锚点，`Game._change_shield` 读取；碧羽散华用；答复(1)：牌手获得破甲同样转化——其任一式神持标记即生效） |
| `fragile_to_damage_if` | `ShikigamiState.ext` | 条件破甲转化：仅当受害者当前已带破甲（shield<0）时，本次新获得破甲才转化为等量伤害（20191212 碧羽散华"若目标已有破甲"；锚点同 `fragile_to_damage`，`Game._change_shield` 读取；牌手分支同理） |
| `feather_used_game` / `feather_used_turn` | `PlayerState.ext` | 黄金羽（tags 标记）牌使用计数：本局累计 / 本回合（己方回合开始清除；黄金羽动态免费与计数触发用） |
| `zhen_proc` | `ShikigamiState.ext` | 鸩 x：基础+觉醒倒计时能力生效合计（倒计时块内 bump_ext step 累加；气绝不清、跨气绝保留，觉醒后继续累加） |
| `turn_marks` | `PlayerState.ext` | "每回合合计一次"标记表（turn_mark 写入，任一回合开始双方清除；寂寥心象用） |
| `power_zero` | `ShikigamiState.ext` | 力量覆写标记（power_override 写入/解除；eff_power 覆写层——力量视为 0；形态离场/气绝清除；笨拙用） |
| `spell_echo` | `ShikigamiState.ext` | 法术回响序列登记（{sequence, cursor, triggered, once_key}；spell_echo 动作写入，己方回合开始清除；涅槃业火用） |
| `max_power` | `ShikigamiState.ext` | 本局历史最高力量（基础+永久+临时，不含战力；只增不减，跨气绝保留不重置——断臂"本局最高力量-当前力量"用；`Game._record_max_power` 在力量变化点更新，初始 = 基础力量） |
| `turn_power` | `ShikigamiState.ext` | 本回合临时力量增益记账（buff_power scope="turn" 累加写入；己方回合开始从 temp_power 扣减并清零——武士之笛/鼓舞类） |
| `min_health_turn` | `ShikigamiState.ext` | 生命下限钳制标记（狂啸 bump_ext 置位；伤害"扣减生命"批次把生命保持在 ≥1；任一回合开始双方清除——半回合作用域） |
| `damage_taken_turn` | `ShikigamiState.ext` | 本回合所受伤害之和（伤害"扣减生命"处按实际伤害值累加；任一回合开始双方清除——百鬼夜行 X 用） |
| `lianmo_used_game` | `PlayerState.ext` | 本局'心身炼磨'（tags lianmo）使用计数（出牌统一记账 `_account_card_played`；心技一体 card_aura power_ext/shield_ext 数值通道读取） |
| `stat_auras` | `PlayerState.ext` | 动态身材光环注册表（stat_aura 动作登记，元素 {"kind", "scope", "holder"}；`_refresh_stat_auras` 读取点全量重算；scope="form" 条目形态离场移除——闻世/火吻之蛇） |
| `dyn_power` / `dyn_health` | `ShikigamiState.ext` | 动态身材光环缓存通道（`_refresh_stat_auras` 重算写入；eff_power/max_health 读取时叠加——model.ShikigamiState；动态上限降低时钳当前生命） |
| `power_zero_turn` | `ShikigamiState.ext` | 半回合力量覆写标记（power_override scope="turn" 置位；任一回合开始双方清除——min_health_turn 先例） |
| `dice_history` | `PlayerState.ext` | 骰子历史（list[int]，只记**最终有效骰点**——被重投覆盖的首投不计入；确定结果时追加；九莲宝灯去重数/增强算子读数） |
| `dice_six_count` | `PlayerState.ext` | 本局投出 6 次数（确定结果时同步维护；dice_six_ge 增强/萌即正义身材/这把算我赢增强读数） |
| `luck_success_game` / `luck_success_turn` | `PlayerState.ext` | 本局运势判定成功次数（按"一次判定"计；福满乾坤 play_condition 合计口径）/ 最近一次判定成功的回合号（青蛙瓷器光环读取：== 当前回合号则在场的青蛙瓷器 +2 力量） |
| `dice_force_six` / `dice_force_six_holder` | `PlayerState.ext` | 萌即正义：判定者级必 6 光环（set_dice_modifier mode=six 写；形态进场 on/离场 off）/ 持有者座次 [player, shikigami]（形态离场通道一并解除） |
| `dice_force_six_once` | `ShikigamiState.ext` | 这把算我赢：下次以其为来源的判定首投必 6 并消耗（set_dice_modifier mode=six_once 写，投掷骰子时机 pop） |
| `cost_mods` | `PlayerState.ext` | 手牌费用修正条目（cost_delta_player 登记 {"amount","turn","scope"}，回合号过期；`_effective_cost` 读取——幸运兔兔"敌方下回合手牌鬼火+1"） |
| `stuns` | `PlayerState.ext`（牌手） | 牌手眩晕条目（同 `ShikigamiState.stuns` 结构；式神眩晕为 State 字段非 ext；眩晕牌手不能使己方式神出击） |
| `yaohu_damage_count` | `PlayerState.ext` | 妖狐伤害计数：伤害流程按来源=妖狐时每次伤害事件 +1（`_account_yaohu_damage`；狂风刃卷增强 {yaohu_damage_count>=20} 读数） |
| `yaohu_dmg_bonus` | `ShikigamiState.ext` | 聚气：妖狐能力伤害永久 +1（bump_ext 写入，跨气绝保留、觉醒后继续累计；amount_ext + amount_ext_source="shikigami" 读取） |
| `transform_origin` / `transform_owner` | `ShikigamiState`（字段，非 ext） | 变形还原式神快照（State dump，不含本字段；被变形时写入，原式神该值非空则继承——连续变形还原到最初；解除时按快照还原当时状态）/ 变形物"所属式神" = 原式神 id（变形物不能使用原式神的任何牌——出牌校验拒绝；万象之书类按原式神取牌的挂读处） |
| 永久派系 | `perm_faction`（`ShikigamiState` 字段） | 式神进场时记录的永久派系（`faction` 属性=当前派系）；召唤物/变形物进场派系=来源式神 perm_faction（engine summon/_transform_shikigami） |
| `gen_replace` | `PlayerState.ext` | 生成替换钩子（{shikigami, to_type}；gen_replace 动作登记、generate 单点读取、重复登记覆盖——觉醒·番茄"她的非战斗牌改为随机战斗牌"） |
| `snowball_used_game` | `PlayerState.ext` | 本局从手牌使用'雪球'（tags snowball）计数（出牌统一记账 `_account_card_played`；流霰 repeat {"ext": ...} 读数） |
| `enemy_stunned_game` | `PlayerState.ext` | 本局敌方角色被[眩晕]累计次数（stun 动作每次实际施加时按受害者对方记账，不分眩晕来源、先于 on_stun 事件；雪融之时[增强] stat_aura kind=ext_power 读数） |
| `dealt_damage_turn` | `ShikigamiState.ext` | 本回合造成过伤害标记（伤害结算点 `_mark_dealt_damage_turn` 按来源式神记账；任一回合开始清除——半回合作用域；记仇 TargetSpec 过滤键同名读取） |
| `boost_flags` | `PlayerState.ext` | 鼓舞扩展旗标列表（条目 {kind: combat_card/no_consume/inspire_bonus, holder?, power?, shield?}；三 op 经 `_add_boost_flag` 登记；scope="form" 条目记 holder、形态离场经 `_destroy_form` 移除；不夜之舞/离殇之舞/觉醒·不知火） |
| `energy_assault` | `PlayerState.ext` | 能量出击旗标（{holder, cost}；energy_assault 动作登记，觉醒·镰鼬）：鬼火与出击次数都为 0 时持有者可耗能量出击（`_cmd_assault` 分支读取） |
| `energy_free_turn` | `PlayerState.ext` | 觉醒·日和坊免单名额：True 时下一次己方式神耗能量效果免单（`_spend_energy` 入口判定并消耗；每半回合重置——不分敌我回合） |
| `energy_life_substitute` | `ShikigamiState.ext` | 能量生命代偿提供者标记（引擎另硬编码日和坊 id 100205 基础能力）：己方支付能量不足时以其生命 1:1 代偿差额（直扣非伤害、不能降到 0） |
| `move_count_turn` | `ShikigamiState.ext` | 本回合 [移动] 次数（`_enter_combat`/`_retreat` 进出各计一次；召唤物进场算、气绝离场不算；任一回合开始清除——半回合作用域；正义必胜 {ext: move_count_turn} 读取） |
| `form_death_play` | `PlayerState.ext` | 形态牌气绝使用旗标（{holder, energy}；form_death_play 动作登记，觉醒·小鹿男）：持有者气绝时其形态牌可用——耗 energy 能量、先复活再结附（觉醒常驻、跨气绝保留） |
| `burst_x` | `CardInstance.mods` | 爆能X 能量快照（energy_cost="all" 出牌时写入当前能量；步骤数值 {"burst_x": true} 读取，memo 同名键优先；本次结算后清除，弹回回手不残留） |
| `self_damage_taken` | `PlayerState.ext` | 本局受到过己方来源伤害标记/计数（己方来源对己方牌手造成伤害时引擎记账——含自伤 source=牌手自身；死亡之花 conditional_mods self_damage_taken_ge 读取） |
| `field_summon_ids` | `PlayerState.ext` | 本局召唤过的幻境数据 id 列表（_summon_field 记账；条件键 field_summon_distinct_ge 按去重数/所属式神读取——觉醒·辉夜姬"召唤五个不同幻境"） |
| `quest_clues_seen` | `PlayerState.ext` | 本局已获得过的'线索'数据 id 列表（pick_generate unique_ext 记账/剔除——觉醒·三目"（不可重复）"；CLEAR_NEVER 跨回合不清） |
| `intensity_boost` | `CardInstance.mods` | 检索入手的幻境耐久增量（search_deck intensity_boost 写入；召唤入场时加到初始耐久——五道难题 +5） |
| `disabled_abilities` / `extra_abilities` | `FieldState`（字段） | 幻境能力叠加合并：field_ability_stack 同名再召唤时新能力并入已有实体 extra_abilities、重复能力记入 disabled_abilities 去重（觉醒·辉夜姬"能力和耐久会叠加"；单实体结算口径暂定见 questions.md） |

## 增强与修饰（设计已定，部分已实现；见 `docs/enhance-design.md`）

| 中文 | 代码标识 | 说明 | 状态 |
|---|---|---|---|
| 卡牌触发器 | `triggers`（CardDef） | 卡面"增强"等的实现机制之一：游离触发块（when/condition/steps）；emit 时全库扫描匹配，为第三收集来源（式神能力之后、响应牌之前） | ✅ |
| 实时监测 | `monitors` / Monitor | 卡面"增强"等的实现机制之一：状态谓词 + 修饰，读取/打出装配时求值，不存储。主通道已落地——读取时谓词求值由 `conditional_keywords`（白刃得[瞬发]）承担、打出装配注入修饰由 `conditional_mods`（牙牙我们走/汤盆冲撞）承担；enhance-design.md 草案的 monitors 字段本体（amount_mult/pre_grants/temp_grants 通道）未采用/未实现 | ✅（主通道） |
| 即时装配 | `_materialize` | 打出时由"定义块 ⊕ 活跃修饰"装配本次实际效果（persistent 快照入实例 mods），用完即弃 | ✅ |
| 修饰 | `mods` | 实例级（`CardInstance.mods`：enhance 数值/keywords_add/cost_delta，mod_hand 写入的 playable_when_defeated/damage_boost/revive_haste，及 random_enhance 写入的 form_power_delta/form_health_delta（`_attach_form` 结附时叠加形态身材）/revive_on_play（气绝中使用该形态先复活来源式神，`_play_form_card` 读取）/enhance_got（实例已获强化 key 去重表）等读取点键）与 (玩家, card_id) 级持久 store（`PlayerState.card_mods`，"本局游戏每……"类计数） | ✅ |
| 卡牌光环 | `card_auras` | 谓词匹配的卡牌获得关键词/不耗鬼火/数值加成（读取时求值，覆盖已有与新生成的牌）；scope 决定失效时机（"turn"=己方回合开始清除；**"form"=绑定来源式神当前形态、形态离场移除**——心技一体/心剑乱舞，气绝经 _destroy_form 同路径；连续型/属性型光环为扩展锚点）。谓词通道：shikigami（必）/ card_type / **card_id**（"此牌"自指——伺机）/ **turn**（"self"/"opponent" 限定回合方——伺机"敌方回合时此牌+2力量"）；**数值通道 power/shield 为战斗牌战力/一次性护甲加值，可叠加**（多次授予累加，与 keywords 的集合语义不同——刃影叠岚；combat_card_stats 读取时叠加）；**power_ext/shield_ext 数值改读 `PlayerState.ext[key]`**（心技一体"本局每使用过一张'心身炼磨'+1/+1"——出牌记账 lianmo_used_game，读取时求值；手牌数值显示已含光环 ext 通道——刃影叠岚同解）；**tag 谓词**（仅命中 tags 含该标记的牌——寒冬之心"你所有'雪球'"）；**damage_boost 卡牌效果伤害 +N 通道**（damage 动作读取时叠加，可叠加；爱意绵绵的 spell_damage 存量通道落地并统一参数名为 damage_boost）；**scope="game"** 本局游戏有效、不清除（寒冬之心类） | ✅ |
| 追加块 | `pre_grants` / `grants` | 可被监测/触发器按索引注入结算的候选效果块（前置/后置） | 🔧 |
| 临时触发 | `temp_grants` / `TempGrant` | 一次性注册的触发（uses 递减移除）；战斗牌携带者绑定该次战斗注册（如不祥之刃击杀抽牌） | ✅ |
| 写入目标 | `to`（hand/persistent/instance/turn） | 写入原语（add_mod）的修饰存储目标：手牌实例 / 持久 store / 来源实例自身（实例计数器，如风符·龙的目标数）/ 回合 store（turn 未实现，"本回合"类由 card_auras 覆盖） | ✅ |
| 数值叠加 | `{"enhance": true, "base": n}` | 步骤 amount 参数形式：base + 实例已装配 enhance（战斗牌战力/护甲提取处解析） | ✅ |
| 动态数值 | `{"shield_of"/"power_of"/"perm_power"/"ext"/"event"/"half_health_of"/"max_power_gap"/"fragile_of": ...}` | 步骤 amount 参数形式：以来源式神当前护甲 / eff_power / **使用时永久力量快照（{"perm_power": "self", "base": n}——崩山增强，山童的贯通不传导法术伤害）** / ext 计数（鸩 x）、事件 payload 数值（寂寥心象"等量"）、事件角色当前生命一半（毒之华，向下取整）、**历史峰值力量差值（{"max_power_gap": "self"} = max(0, ext["max_power"] - eff_power)——断臂"力量变为本局最大值"）**、**当前破甲量（{"fragile_of": "self"\|"source"} = 负 shield 绝对值——僵硬扑击"获得等同于自己破甲的力量"）**求值；**事件引用修饰（{"event": key, "cap": n} = min(事件值, n) 封顶——觉醒·铃鹿御前"等量的破甲（最大为3）"；"half": true = 事件值减半向下取整——光影"获得等同于一半伤害的生命"；cap 先截后减）**——尘刀按打出瞬间护甲快照战力（本次战斗中不变）、古尘之壁按护甲强化、援护按白狼力量造伤 | ✅ |
| 随机强化 | `random_enhance`（动作） | 手牌同名卡各实例随机强化一次（罗生门之鬼"仅在手牌时可触发增强"）：只作用于控制者手牌中同 `card_id` 实例；每实例独立计数——强化序号 = len(`mods["enhance_got"]`)+1，达 `max_count`（缺省 3）次跳过；候选 = `tiers` 中 `min`（缺省 1）≤ 序号 ≤ `max`（缺省 max_count）且 key 未获得的项，rng.choice 一项；写入 mods：keywords_add 集合并入 / form_power_delta/form_health_delta 累加 / 其余键直写（playable_when_defeated、revive_on_play 等开关） | ✅ |
| 随机牌手监听 | `random_aura`（动作） | 从 options 随机赋予一项牌手级监听（豪焰四选一）：各项以 `{once_prefix}_{key}` 为 once_key 去重（全项都有空操作），rng.choice 后转调 player_aura | ✅ |
| 本回合增益通道 | `scope="turn"`（buff_power 参数）/ `turn_power`（ext 键） | 临时力量增益记账到 `ShikigamiState.ext["turn_power"]`，己方回合开始统一从 temp_power 扣减并清零（武士之笛/鼓舞类"本回合"；与 perm 互斥） | ✅ |
| 气绝事件扩展 | `in_combat` / `summon`（on_shikigami_defeated payload） | in_combat：气绝时是否在战斗区（清除 combat_index 前捕获；迁怒/罗生门"消灭敌方战斗区式神"条件）；summon：气绝者是否召唤物（罗生门"基础式神"= summon false 条件），均走条件迷你语言等值兜底 | ✅ |
| 指定式神过滤 | `shikigami`（TargetSpec kind=all 扩展键） | all 分支统一按数据 id 过滤式神（豪焰固定项 buff 茨木、羁绊伤酒吞类"指定式神"；池先取、id 后滤） | ✅ |
| 运势判定 | `luck_roll` / `luck_reroll`（动作） | `luck_roll`：步骤级 [运势X]（x 阈值；judge=self/opponent/both——both 双方各生成事件、当前回合玩家先、各自以自己视角结算 then；then 成功子步骤；force_x1_if 条件满足时阈值视为 1——立直，骰子照投照计）；骰点写 `ctx.memo["luck_dice"]` 供 amount_ctx 读取。`luck_reroll`：判定时（on_luck_judge）改写运势事件当前骰点，同一判定中每个来源能力至多一次、同样吃必 6 修饰（座敷童子） | ✅ |
| 运势门控 | `luck`（EffectBlock） | 触发式块的运势判定门控：`luck: X`（int）= 判定成功才结算块 steps；`luck: {"x": X, "on": "fail"}` = 判定失败才结算（家内安全/和气满满）；判定者默认控制者；并行入队/同步推进由引擎 `_run_luck_events` 负责 | ✅ |
| 运势事件 | `on_luck_judge` / `on_luck_success` / `on_luck_effect_after` | 判定时（即时，payload 含可变运势事件 dict luck——重投改写其骰点）/ 判定后（延时，成功才发；翻倍标记下各 handler 追加一次，排除翻倍提供者自身能力与响应/临时触发）/ 生效后（延时，预留）。时机序列见 rules.md 第二十七章 | ✅ |
| 直接获胜 | `win_game`（动作） | 目标牌手获得本局游戏胜利（target=self=控制者胜）：`_set_pending_end(loser=对方)` 走待结束流程，非气绝判负（这把算我赢增强变后） | ✅ |
| 逐次随机伤害 | `repeat_random_damage`（动作） | 逐次在 pool 随机 1 名造成 amount 点伤害、插入结算、每次重新求值目标池（无羁风弹；pool="all_other_shikigami"=双方除来源外未气绝式神）：stop_on_defeat=True 任一式神气绝即停，否则满 max 次即停 | ✅ |
| 再次使用本牌 | `reuse_card`（动作） | 法术→凭空自动使用管线同目标重结算（实例标记 `_reused` 防自循环，恰好两次——叠风斩）；战斗牌→战斗流程重走（关键字/临时触发重新绑定，自动使用不耗火——转运）；照常 emit on_card_played（triggered=auto，可再触发"使用牌时"能力） | ✅ |
| 复仇复制 | `echo_event_card`（动作） | 读事件中被用的卡牌，以**监听控制者**身份凭空复制使用（不耗火、不做等级/目标合法性/[条件]检查；目标强制=施法者自身在场式神，中立牌/施法者离场/无 choose 目标则无目标使用）；用后进墓地，照常 emit on_card_played（play_from=void、triggered=auto、带 chosen 载荷）；帷幕再校验与一切卡牌使用一致（记仇；on_card_played payload 新增 `chosen` 字段配套） | ✅ |
| 条件回手 | `bounce_self`（动作） | 此牌结算完毕在墓地时移回手牌（与 rebound 同走 move_card 统一路径，超上限按爆牌转墓地）；配 step 级条件即"条件回手"（蛇行击 20191212"目标有破甲则移回手上"） | ✅ |
| 选择目标归属/破甲条件 | `chosen_side` / `chosen_has_fragile`（条件键） | {chosen_side: friendly\|enemy\|any}=**事件** payload chosen 恰好一个且为式神、归属匹配（记仇"对单个己方式神使用的法术"）；{chosen_has_fragile: bool}=Step 级条件：卡牌选择目标（chosen）中角色有/无破甲（chosen_stunned 先例） | ✅ |
| 牌手费用修正 | `cost_delta_player`（动作）/ `cost_mods`（ext 键） | 目标牌手的手牌费用 +amount（scope="next_turn"=下个回合，按回合号记账过期，仿 immunities；`_effective_cost` 读取——[不消耗鬼火]与回合内首张[瞬发]已归零不受影响，非手牌使用不走费用求值不受影响；幸运兔兔）；**`side="opponent"` 改作用于敌方牌手、`card_flag`（如 "revealed"）仅命中带对应实例标志的手牌、`scope="form"` 绑定来源形态、形态离场移除（心灵迷宫"敌方使用已展示的手牌额外耗 1 火"，仍在 cost>0 门内——瞬发/不耗火全免）** | ✅ |
| 倒计时力量复合 | `countdown_power_boost`（动作） | 山兔能力原子语义"倒计时-1 并 +1 力量"同段效果：气绝者只减复活倒计时（被本次归零复活者不追加力量）；存活者（含无倒计时能力的）倒计时 -1（归零走 `_countdown_zero`）并 +1 力量（perm=False 默认临时） | ✅ |
| 随机使用形态 | `random_play_form`（动作） | 目标各随机使用 1 张等级 ≤ 其当前等级的专属形态牌（凭空自动使用：`_play_form_card` + on_card_played(triggered=auto)，play_condition 同检）；无可用形态/气绝者跳过（鸿运当头） | ✅ |
| 骰子修饰 | `set_dice_modifier`（动作） | mode="six"：判定者级光环必 6，写控制者牌手 ext `dice_force_six`（记持有者座次 `dice_force_six_holder`，形态进场 on/离场 off——萌即正义）；mode="six_once"：来源级，写来源式神 ext `dice_force_six_once`，下次以其为来源的判定首投必 6 并消耗（这把算我赢） | ✅ |
| 随机弃牌 | `discard_random`（动作） | 随机弃目标牌手 count 张手牌（rng.sample；targets 缺省回退控制者——转运）。与 `discard` 的顺序/谓词弃牌语义不同，故独立 op | ✅ |
| 眩晕施加 | `stun`（动作） | 目标角色获得眩晕条目（kind 默认 normal，记控制者回合号；lasting 持续眩晕已落地——`lasting`/`until_event` 参数见「持续眩晕施加」行）；式神条目存 `ShikigamiState.stuns`、牌手存 `PlayerState.ext["stuns"]`；门控与解除见 rules.md 第二十八章 | ✅ |
| 眩晕事件 | `on_stun` | 角色被眩晕后发出（即时时机 insert，payload {victim, source}；stun 施加点发出，同 on_shield_changed 变化点位置）——雪女"每回合一次，当你[眩晕]敌方式神时"挂点（每回合一次配 turn_mark 门控） | ✅ |
| 破甲转移 | `transfer_fragile`（动作） | 来源（式神或牌手，targets 缺省回退来源）当前破甲清零、目标获得等量破甲；目标可为敌方全体角色（每名全量——毒气喷泉）；腐坏直拳"确定攻击目标后转移"以战斗牌效果步表达 | ✅ |
| 破甲保留授予 | `keep_fragile`（动作） | 目标式神获得 `keep_fragile`（形态结附期间其破甲在己方回合开始不清除——肿胀体质；形态离场解除；见「属性与修正」破甲保留行） | ✅ |
| 眩晕条件算子 | `{字段_stunned}` / `chosen_stunned` / `combat_opponent_stunned` | {字段_stunned: bool}=事件中 Ref 所指角色（式神或牌手）是否眩晕；{chosen_stunned: bool}=卡牌选择目标（chosen）中有/无眩晕角色；{combat_opponent_stunned: bool}=能力持有者参与事件中的战斗且交战对方眩晕（双向——攻击方看被攻击者、被攻击方看攻击方，雪童子"与[眩晕]的敌方角色交战"类） | ✅ |
| 眩晕目标过滤 | `stunned`（TargetSpec 过滤键） | spec_pool_refs 按是否眩晕过滤角色目标（式神与牌手均可；崩雪"消灭一个[眩晕]的式神"类池）；**`exclude_victim`（过滤键）：kind=all 解析结果排除触发事件的 victim（胧月雪华斩"所有其他[眩晕]的敌方角色"，与 random_damage 同名参数同语义）** | ✅ |
| 眩晕存在性/计数读取 | `_enemy_stunned_count` / `{"enemy_stunned_count": true}`（动态数值键） | 敌方当前眩晕角色数（在场眩晕式神 + 眩晕牌手）的统一读取点——活局面量、眩晕解除即减：conditional_keywords 的 enemy_stunned_nonempty / stat_aura 的 enemy_stunned_exists / _step_amount 的 {"enemy_stunned_count": true}（霜天之织[增强]"每有一个便+1力量"，战力提取经 combat_card_stats 同源求值）共用 | ✅ |
| 临时触发次数 | `uses`（temp_grants 块扩展键） | 战斗牌临时触发的可触发次数覆盖（缺省 1；uses=99 = 战斗内不限次——胧月雪华斩配[连击]第二段同样溅射；登记处 _resolve_combat / 响应插入两路径同读） | ✅ |
| 式神 id 列表匹配 | `{字段_shikigami: [id, ...]}`（条件运算符） | 事件中 Ref 所指式神数据 id ∈ 列表（番茄召唤物/变形物双 id 共享的牌手光环条件；单 id int 与 "self" 形式沿用） | ✅ |
| 战斗作用域关键字授予 | `scope="battle"` / `scope="turn"`（grant_keyword 参数） | scope="battle"=战斗作用域条件授予：绑定当前战斗上下文，战斗终止点按实例移除（觉醒·雪童子"交战时获得[连击]"——效果步中的授予同样吃战斗作用域）；scope="turn"=授予方当回合结束移除（条目存玩家 `ext["turn_keyword_grants"]`，按授予时回合号比对——惊鸿之舞"所有己方式神本回合获得[帷幕]和[不屈]"；一次性关键字[不屈]被正常消耗后不到回合结束） | ✅ |
| 换牌 | `replace_cards` / `gen_replace`（动作） | replace_cards：把控制者 zones（默认手牌+牌库）中该式神的所有非 exclude_type 牌各随机替换为一张该式神的 to_type 牌（原牌入墓地、替换牌生成到原区域并统一快照，牌库有替换则洗一次牌库——觉醒·番茄③）；gen_replace：牌手永久生成替换钩子（登记 `PlayerState.ext["gen_replace"]` {shikigami, to_type}，generate 单点读取——之后生成该式神的非 to_type 牌时改为随机一张 to_type 牌，重复登记后者覆盖前者——觉醒·番茄④）；shikigami="self" 时变形物取其 transform_owner 原式神 id | ✅ |
| 雪球记账 | `snowball`（tags）/ `snowball_used_game` | 出牌统一记账：tags 含 snowball 的牌从手牌使用时 `PlayerState.ext["snowball_used_game"]` +1（本局累计不清；流霰 repeat {"ext": ...} 读数；寒冬之心 card_aura tag 谓词同用此标记） | ✅ |
| 变形 | `transform` / `untransform`（动作） | transform{into}：目标式神灵变为 kind=transform 变形物（原式神快照存 `transform_origin`，连续变形继承最初快照；未在场/濒死空操作）；untransform：按快照还原原式神当时状态（纸人/小纸人能力：己方回合结束变回）；`permanent`/`owner_combat` 永久变形通道已删——觉醒·番茄 10013108 迁移至「式神替换」replace（见下条） | ✅ |
| 式神替换 | `replace`（动作）/ `replace_owner`（ext 键）/ `kind="replace"` | replace{into}：目标式神被 kind=replace 替换物取代——继承座次/等级，无快照不还原（替换物气绝即气绝、复活仍为替换物）；`ext["replace_owner"]` 放行原式神全部卡牌（出牌校验）；派系=替换物 def faction；与原式神（召唤物）可同时在场（觉醒·番茄 10013108——维护者定案 4 点）。kind=replace 为评审⑤从 transform 拆出的独立实体类别（见「替换物」行） | ✅ |
| 击杀账本 | `kill_total` / `kill_by`（`PlayerState` 字段） | 规则评审⑩落地的全局击杀计数：`Game.check_defeated` 单点记账（气绝与消灭同口径、仅统计有来源的消灭）——`kill_total`=本局以己方角色为来源消灭的式神总数（含伤害转移等消灭己方式神，计入来源方）；`kill_by`=按来源式神**当前数据 id** 分桶的消灭数。读取通道：动态数值 `{"kill_count": {"shikigami": id}\|{"scope": "player"}, "per": n, "base": m}`（打出装配快照入 `card.mods["_kill"]`，禁锢之刀"每消灭过一个…+2力量"）与条件键 `{kill_count_ge: n}`（夺命门控）；`per` = 动态项总和倍率（base 不受倍率），通用叠加于任意动态数值形式 | ✅ |
| 委托条件账本 | `quest_counts`（`PlayerState` 字段）/ `quest_count_ge` / `round_ge`（条件键） | 三目委托机制（rules.md 第三十三章）：牌手级 11 种 kind 计数（assault/draw/play/damage/effect_damage/attack/form_play/offdeck_play/enemy_defeat/revive/quest_used，记账点 `Game._quest_tick`/`_account_quest_damage`，`generated=True` 实例标记"阵容套牌以外"口径），跨区域有效（"在牌库也有效"）；{quest_count_ge: {kind, count}}=控制者账本达标（play_condition/Step 级条件通用），{round_ge: n}=对局轮数 (turn+1)//2 ≥ n（双方各一回合为一轮）；CLI 手牌进度标签 `_quest_progress`；**多事多忙扩域**（tags `quest_enemy`）：行为类 kind 记账时对方在场形态含此标记则对方账本同计，归属类（enemy_defeat/revive/quest_used）不扩域 | ✅ |
| 委托视为达成 | `quest_done`（mods 键）/ `quest_complete`（动作）/ `quest_complete_pick`（pending_choice kind） | quest_complete{mode=choose\|random}：手牌中 tags 含 `urgent_quest` 且未标记的实例置 `mods["quest_done"]`——`_play_condition_met` 读取，[条件]使用前提视为满足（委托整理 choose 多张挂起交互 uid 作答 / 截稿日 random；空候选空操作） | ✅ |
| 线索选择生成 | `pick_generate`（动作）/ `pick_generate`（pending_choice kind）/ `quest_clues_seen`（ext 键） | pick_generate{pool, unique_ext, zone}：从牌池选一张生成入手（generated=True）；unique_ext 剔除并记账控制者 ext 已见 id（觉醒·三目"（不可重复）"，CLEAR_NEVER）；多候选挂起交互（choice 作答数据 id），单候选直接生成，空候选空操作 | ✅ |
| 多段攻击 | `multi_strike`（动作）/ `_battle_strikes` | 二帚流"攻击5次"：战斗牌提取步 times 参数（响应插入使用路径作普通 step 登记当前战斗），交战阶段后追加 times-1 段依次单独结算（反击只一段与首段并行）；攻击者气绝/被攻击者气绝无贯通则后续段终止，贯通改打对方牌手；战斗终止点清除 | ✅ |
| 伤害覆写 | `override_damage`（动作） | 把伤害时点批次事件的伤害值直接改写为定值 to（二帚流"伤害改为1"；区别于 cap_damage 封顶不比较原值）；须挂 on_damage_start 等含 damage payload 的时点批次（该批次 payload 带 battle 键供战斗绑定 temp_grants 过滤） | ✅ |
| 战斗免疫全类别 | `kind`（battle_immunity 参数） | 缺省 combat_damage；kind=all = 免疫所有伤害（含效果伤害）仍限战斗作用域——`_effect_immune` 对携带 battle 键的条目按战斗 id 比对（nested 覆盖嵌套战斗），战斗外不免疫（二帚流） | ✅ |
| 今日委托每日替换 | `gen_weekday_quest`（tags）/ `WEEKDAY_GEN_REPLACE`（db/schema.py） | 日常委托本体不进入对局：构筑进牌库（setup.build_player）与 generate 生成（_spawn 钩子）时按当日星期替换为对应今日委托牌（周一=10040455…周日=10040461），替换产物 generated=True | ✅ |
| 气绝复活形态 | `revive_on_defeat`（tags） | 结附带此标记形态的式神气绝结算（含气绝后时机）完成后经 `_revive` 复活（平和猫又屋；形态已正常消灭） | ✅ |
| 光环子类型限定 | `subtype`（card_aura 参数） | 光环仅命中该子类型的牌（`_match_auras` 过滤；觉醒·三目"你的委托牌不消耗鬼火"= subtype: quest + cost_zero + scope=ability） | ✅ |
| 使用前提 | `play_condition`（CardDef）/ [条件]（卡面） | [条件] 使用前提：不满足则任何方式都不能使用——主动（`_cmd_play_card`）、响应（收集/复查）、自动使用统一以条件迷你语言对控制者求值（事件载荷为空，用 dice_six_ge/luck_success_total_ge 等控制者 ext 算子；福满乾坤）；CLI 可用性置灰。[条件] 为卡面标记（text 内），不进 KEYWORDS 表 | ✅ |
| 运势条件算子 | `dice_six_ge` / `dice_distinct_ge` / `luck_success_total_ge` / `dice_below_x` | {dice_six_ge: n}=控制者投出 6 次数（ext dice_six_count）≥ n（送祝福/快来保护我增强）；{dice_distinct_ge: n}=dice_history 去重数 ≥ n（九莲宝灯动态身材同读数）；{luck_success_total_ge: n}=双方 luck_success_game 合计 ≥ n（福满乾坤 play_condition）；{dice_below_x: true}=运势判定时事件当前骰点 < 所需 X（"将失败"重投门控——觉醒座敷） | ✅ |
| 运势数值扩展 | `amount_ctx` / `amount_ext` / `amount_ext_source` / `amount_sign` | 伤害类（damage/random_damage/distribute_damage）与 buff 类（buff_power/buff_health）数值扩展：amount_ctx 累加效果上下文变量（luck_dice——骰子炸弹）；amount_ext 累加 ext 计数——默认读来源式神所属牌手 ext（谁还不听话 dice_six_count），amount_ext_source="shikigami" 改读来源式神 ext（聚气 yaohu_dmg_bonus）；amount_sign=-1 转 debuff（来打我呀减力量） | ✅ |
| 逐次随机分配 | `sequential`（random_damage 参数） | sequential=True：每次独立随机（有放回）、插入结算——逐次单独伤害队列（狂风刃卷）；默认保持并行无放回语义 | ✅ |
| 随机分支 | `random_branch`（动作） | branches=[{condition, steps}]：逐项求值 condition（复用条件迷你语言、事件上下文为触发事件、缺省/null 恒真），从通过者中均等随机一项执行其 steps；无满足分支空操作（惊鸿之舞"每个回合开始时，随机触发一个效果"——on_turn_start 无 condition，双方回合开始均触发） | ✅ |
| 磨牌 | `remove_deck`（动作） | 指定方牌库顶/底 N 张移入 exiled（移除游戏、不进墓地）：position=bottom（缺省）/top，count 支持 {"memo": key}；side=self/opponent（缺省 opponent），有选择目标时按 targets[0].player（孟婆基础能力/孟婆汤/天降之物/觉醒·孟婆） | ✅ |
| 同名牌移除 | `purge_copies` / `purge_named_card`（动作） | purge_copies：指定数据 id 同名牌在指定方手牌+牌库的全部复制移入 exiled（card_id 缺省读事件 on_card_played 的 card_id——刚使用的那张已离手不在范围，side=event_player/opponent；在场同名实体不受影响——奈何桥头）；purge_named_card：忘忧的旋律两级交互（pending_choice kind="card_name"：先选敌方式神、再选其可构筑牌池中的一张牌名，作答键 choice）后移除 | ✅ |
| 交互弃牌 | `discard_pick`（动作） | 结算中交互弃牌（pending_choice kind="discard_pick"）：控制者从手牌选 count 张弃置；无手牌不挂起、直接跳过（意外之喜"弃一张牌"） | ✅ |
| 伤害转移（转移链） | `grant_redirect` / `redirect_damage_to_self`（动作）/ `_DamageEvent.start` / `_DamageEvent.redirect_chain` / `ExecContext.ability_uid` | 2026-08 定案「转移链」统一语义：原伤害值 >0 时原事件立即终止结算，生成等量、同来源、同原因、同属性（**无[贯通]**）的新伤害事件，跳过早期步骤从"护甲计算前0"（on_before_shield 批次）开始（`start="pre_shield_0"`——穿刺/on_damage_start/贯通修正/double_damage 均不判定；免疫判定后移至护甲计算后优先级 3，新事件对最终受伤者照常判定（修正定案"免疫只看最终受伤者"）；事件生成点的伤害转化与气绝/濒死保护仍先行）。**转移链**：`redirect_chain` 记录本链已触发的转移能力实例身份（`ability_uid`：式神基础/觉醒/形态能力="shk:{pi}:{si}:{id(block)}"、TempGrant="grant:{seq}"、幻境能力块="field:{pi}:{下标}:{id(block)}"，其余通道按块对象身份兜底），每个转移能力在同一链上只执行一次、每次只单个触发（op 归零原事件→归零断点跳过后续 priority≥2 块）、新事件继承并延长链、并行伤害各自独立成链；转移新目标已濒死（延时气绝未结算）时原事件仍终止、新事件入口拦截不造成实际伤害。grant_redirect：授予"下一次将受到的伤害改由其牌手承受"，挂账 `ext["damage_redirects"]`（每层独立、多张可叠加，气绝清除），消耗式天然有界、不占链身份（血蝠之盾；式神自身屏障/免疫不随转移消耗，牌手护甲/破甲照常参与）。redirect_damage_to_self：挂 on_after_shield 批次**优先级 2**（「伤害目标转移」类）的式神能力块——"改由本能力持有者承受"（机制先行，暂无实卡；受伤者匹配由能力 condition 负责） | ✅ |
| 护甲/破甲整值移除与归集 | `strip_shield` / `consolidate_shields`（动作） | strip_shield：目标角色（式神或牌手）护甲/破甲整值清零（按失去流程走 _change_shield 发 on_shield_changed），实际移除量合计写入块内暂存 `stripped_shield`（骚声/妖怪屋的醒转共用）；consolidate_shields：目标以外双方所有角色（在场式神+双方牌手）的护甲/破甲逐一清零、代数和加算到目标式神（正=护甲/负=破甲；目标自身原值不经移除——汇聚，维护者定案） | ✅ |
| 手牌转化 | `transform_hand_card`（动作） | 控制者手牌中所有 from_id 实例移入 exiled（原牌去向暂定——questions.md (11)），各生成一张 into_id 新实例入手并复制原实例修饰（shield_boost 等实例增强随牌转移；_mat 装配记账键不复制——觉醒·天井下，thoughts(19) 口径） | ✅ |
| 卡牌触发器扩展 | `card_in_hand`（条件键）/ `shield_boost`（实例修饰键） | card_in_hand=true：CardDef.triggers 游离触发块门控——控制者手牌中须有本卡实例才触发（血怒/灵力[增强]；engine 收集时剥除该键再求值其余条件）；shield_boost：gain_shield 结算读取的卡牌实例增强（灵力/灵力之泉[增强]"此牌效果+1"——on_shield_changed reason="turn_start_clear" + gained=false + kind/target_side 定向双块记账，骚声按 stripped_shield memo 量写入两 id 手牌实例） | ✅ |
| 召唤身材覆写 | `stats_memo`（summon 参数） | 召唤物基础力量/生命覆写为块内暂存 ctx.memo[key] 的数值（妖怪屋的醒转"使其力量和生命等同于被移除的护甲或破甲"——基础值口径：复活后按该基础值保留、非一次性增益，维护者定案） | ✅ |
| 动态实例修饰 | `conditional_mods`（CardDef 字段） | 装配点（打出付费后/效果结算前、生成入手——engine._materialize）按条目条件把 mods 键写入该实例：{"mods": {键: 值}, 条件键...}（条件迷你语言、控制者视角空事件求值）——牙牙我们走[增强] form_power_delta/form_health_delta 形态身材、汤盆冲撞[增强] double_damage（伤害结算"护甲计算前1"翻倍） | ✅ |
| 月夜幻响动态数值 | `max_shield_or_fragile` / `countdown_holders` / `countdown_sum` / `negate`（_step_amount / repeat 键） | {"max_shield_or_fragile": true}=双方所有角色（在场式神+牌手）\|shield\| 最大值（遮雨"等同于场上最大护甲或破甲"）；{"countdown_holders": "friendly_others"}=控制者在场未气绝、当前持有倒计时能力的式神数（排除来源式神——突[增强]）；{"countdown_sum": true}=repeat count 动态——全队当前倒计时总和（岚"X为你所有式神当前[倒计时]总和"）；negate: true 与任意动态数值形式叠加、最终取负（突 {base: 2, countdown_holders, negate} / 觉醒·山风共享 {event: original, negate: true}） | ✅ |
| 击杀破甲判定前移 | `on_before_defeat` + `victim_has_fragile` / `source_side`（破碎之音用法） | 形态能力挂气绝前即时钩子（非响应牌）：伤害致死会先消耗破甲（天然不满足），仅直接消灭/气绝时仍持破甲者触发（破碎之音"每当你击杀有破甲的式神时，对其牌手造成3点伤害"——victim_has_fragile 判 victim 仍持破甲、source_side=friendly 判击杀来源为己方；引擎代理已验证两路径） | ✅ |
| 抽牌扩展 | `hand_to` / `side`（draw 参数） | count={"hand_to": n}：抽至手牌 n 张（福满乾坤"抽手牌直至十张"）；side="self"/"opponent"：改由指定方抽牌（依次对双方生效类） | ✅ |
| 鬼火获得扩展 | `side`（gain_orb 参数） | side="self"/"opponent"：改由指定方获得（福满乾坤依次对双方 +3 鬼火）；缺省控制者 | ✅ |
| 已展示 | `revealed`（mods 键）/ `reveal`（动作）/ `on_card_enter_hand`（事件） | 卡牌实例级状态（`CardInstance.mods["revealed"]`，本局保持、随实例——回库/墓地不清除；调度传递：换入牌失去、换出牌获得，`_swap_hand_card`）。reveal 四档（targets 忽略，作用于敌方手牌）：random=随机一张未展示 / shikigami=指定式神专属牌全部（协战归属 `_card_belongs_to` 口径；`shikigami="chosen"`=选择目标所指式神）/ all=全部 / event=触发事件 payload 的那张牌（入手被动挂点）。入手统一钩子 `_enter_hand`（抽牌/生成/检索/检视/调度换入一切路径）发 `on_card_enter_hand`（延时时机 queue，payload {player, uid, card}；起始手牌静默、爆牌转墓地不发）。可见性：CLI 按 hand_seq 列出敌方已展示手牌；联机 sanitize 对已展示卡放行真实内容。机制细则见 rules.md 第二十九章 | ✅ |
| 使用已展示牌载荷 | `card_revealed`（on_card_played payload 键） | 被使用的牌在使用点是否具有"已展示"（读实例 mods）——{card_revealed: true} 匹配"使用已展示的手牌时"类触发（灵视/觉醒·觉） | ✅ |
| 本回合伤害过滤 | `dealt_damage_turn`（TargetSpec 过滤键 / ext 键） | 本回合造成过伤害的角色过滤（记仇"本回合造成过伤害的敌方式神"）：伤害结算点 `_mark_dealt_damage_turn` 按来源式神记账 `ShikigamiState.ext["dealt_damage_turn"]`，任一回合开始清除（半回合作用域）；spec_pool_refs 统一校验 | ✅ |
| 已展示计数 | `enemy_revealed_count`（动态数值键） | 敌方手牌中已展示牌计数（`_enemy_revealed_count`，引擎读取、活局面量）：三口径——`spell`=法术牌数（模仿+护甲）/ `other`=其他牌数（模仿+力量）/ `shikigami_of_chosen`=选择目标所指式神专属牌数（棒球炸弹增伤，协战归属同 _card_belongs_to）；`_step_amount` 签名加 chosen | ✅ |
| 能力进场事件 | `on_ability_enter` | 式神能力进场统一钩子（延时时机 queue，payload {player, shikigami, target: Ref}）：对局开始/升 1 级/复活/觉醒替换/变形与还原均经 `_register_ability_countdown` 发出——萤草"当你使用法术牌时…"改为能力光环前置门控 | ✅ |
| 幻境事件 | `on_summon_field` / `on_before_field_intensity` / `on_field_intensity_changed` / `on_before_field_destroy` / `on_field_destroyed` | 召唤幻境后（延时 {player, field（队列下标）, card_id, source, reason}——辉夜姬能力/[融合]挂点预留）/ 耐久变化前（即时，payload 含可变 change dict，监听者可改 change["amount"]——荒"月坠"）/ 耐久变化后（延时 {old, new, amount（实际变化量带符号）}，负量 clamp——黄泉花境）/ 消灭前（延时，触发时幻境仍在队列——不见岳各幻境）/ 消灭后（延时，发出时已出队，预留；报备口径：排在耐久变化后之后）。流程见 rules.md 第三十一章（英文键映射定稿：幻境=field、耐久=intensity、队首=field_front、内部 op=field_destroy；原 phantom/durability 命名均作废） | ✅ |
| 能力光环 | `scope="ability"` / `shikigami="any"`（card_aura 参数） | scope="ability"：光环挂能力持有者（同 form 作用域机制），气绝/变形/还原/消失/觉醒替换前经 `_clear_ability_card_auras` 统一清理；shikigami="any"：光环匹配任意所属式神的牌（存 None，`_match_auras` 通配——爱意绵绵全式神手牌通道） | ✅ |
| 倒计时复原 | `reset`（countdown_delta 参数） | 复原倒计时初值（countdown_initial）、不触发归零结算、无能力者空操作——疯魔琴心"使敌方式神的倒计时复原" | ✅ |
| 卡牌变换 | `transform_card`（动作） | 手牌按 card_id 原位变换为 into 指定新卡（count=1；无匹配空操作；新 uid + `_materialize` 快照，继承 mods 中实例标志） | ✅ |
| 召唤内嵌费用 | `orb_cost`（summon 参数） | 效果内嵌鬼火费用（坐下 20200227"额外消耗1点鬼火，召唤'番茄'"）：控制者剩余鬼火不足则本步空过（召唤失败，其余步骤照常）；足够则先支付（发 on_orb_changed，reason=summon_orb_cost）再召唤 | ✅ |
| 能量充能/支付 | `gain_energy` / `spend_energy`（动作） | gain_energy：目标式神能量 +amount（封顶 10；`emit_event=False` 抑制事件防自连锁——烟烟罗基础/觉醒"获得能量时再获得"）；spend_energy：目标式神支付 amount 能量，`gate: true` 时支付不足中止当前效果块（AbortBlock——祈晴/滋养/晴雨/同生共死"消耗X能量，……"门控）；均走 `engine._gain_energy`/`_spend_energy` 统一入口（日和坊生命代偿、觉醒·日和坊免单同通道） | ✅ |
| 能量获得事件 | `on_energy_gained` | 延时时机（queue），payload {player, target, old, new, amount}；每次获得能量即发出——已达上限照常发出、amount=0（体系只有"时"时机、无"后"时机，维护者定案）；`engine._gain_energy` 统一发出（回合开始充能/卡牌效果同路径） | ✅ |
| 爆能X 快照 | `burst_x`（card.mods 键 / 动态数值键） | 爆能X（`energy_cost: "all"`，消耗全部能量、0 能量不可选）出牌时把当前能量快照写入 `card.mods["burst_x"]`，步骤数值 `{"burst_x": true}` 读取（`memo["burst_x"]` 优先，供触发块转写）；本次结算后清除（弹回回手不残留） | ✅ |
| 移动（动作） | `move`（动作） | [移动]：目标式神战斗区↔准备区 toggle（复用 `_enter_combat`/`_retreat`；气绝/离场不行、眩晕不拦、召唤物退回即离场、尘缚锁定下移入静默无效）；`force=True` 可强制敌方式神入战斗区（羽迹），非强制敌方目标静默跳过；进出各计一次（`ext["move_count_turn"]`，半回合清除；召唤物进场算、气绝离场不算）；机制见 rules.md 第三十章 | ✅ |
| 鼓舞旗标 | `boost_on_combat_card` / `boost_no_consume` / `inspire_bonus`（动作）/ `boost_flags`（ext 键） | 玩家级出击加成旗标（`PlayerState.ext["boost_flags"]` 条目 {kind, holder?}，三 op 共用 `_add_boost_flag`）：combat_card=战斗牌攻击也获得并消耗出击加成（不夜之舞）；no_consume=出击加成不因攻击消耗（离殇之舞）；inspire_bonus{power,shield}=basic_boost 数值额外加算、可叠加（觉醒·不知火）；`scope="form"` 绑定来源形态、离场清除（`_destroy_form` 同路径），缺省永久 | ✅ |
| 出击/加成/身材重置 | `reset_assaults` / `clear_boosts` / `reset_stats`（动作） | reset_assaults：控制者出击次数恢复为 1（变化时 emit on_assaults_changed——真意之歌）；clear_boosts：清除目标牌手全部出击加成——**显式选牌手才生效、选式神空操作、无目标才回退控制者**（日出有曜 B，维护者定案单目标语义）；reset_stats：目标式神力量/生命变为基础值（清临时修正/攻击挂账/turn_power/战力，清护甲破甲，生命直设为变更后上限——非伤害/治疗事件；动态光环不动——日出有曜 A，牌手目标空操作） | ✅ |
| 能量出击 | `energy_assault`（动作）/ `energy_assault`（ext 键） | 登记玩家级旗标（{holder, cost}——觉醒·镰鼬 on_awakened）：该玩家鬼火与出击次数都为 0 时旗标持有者可消耗 cost 能量出击（`_cmd_assault` 支付管线分支，消耗经 `_spend_energy`——免单/代偿同通道） | ✅ |
| 形态气绝使用 | `form_death_play`（动作）/ `form_death_play`（ext 键） | 登记玩家级旗标（{holder, energy}——觉醒·小鹿男）：旗标持有者的形态牌在其气绝时可用，使用时消耗 energy 能量并**先复活**持有者再正常结附（`_cmd_play_card` 合法性/支付/复活管线；觉醒常驻玩家级旗标、跨气绝保留） | ✅ |
| 取消攻击 | `cancel_attack`（动作） | on_before_assault 响应时置事件 `cancel` 旗标，战斗流程在响应结算后检查并终止整场战斗（鸦羽疾走）；已支付鬼火/出击次数不退还（维护者定案）；非该时机静默跳过 | ✅ |
| 攻击替换 | `attack_replace`（动作） | on_before_assault 响应时置事件 `attack_replace` 旗标，战斗流程以"对两个随机不重复敌方角色的效果伤害（X=力量+战力含乏力）"替换先攻/交战阶段——无交战、不受反击，on_after_assault 照常发出（烬染不夜）；目标池可含牌手、伤害为**非战斗伤害**（能力造成、非法术——kind=effect，不触发[吸血]；均维护者定案） | ✅ |
| 交战改向 | `battle_retarget`（动作） | 登记到当前战斗上下文（`_battle_retarget`）：目标角色的交战伤害（攻击/反击）改向另一个随机敌方角色（可含牌手——维护者定案；排除原交战目标，无另一个敌方角色时落空），仅本次战斗有效（声东击西） | ✅ |
| 复制使用 | `use_card_copy`（动作） | 凭空生成指定牌复制并自动使用（爆能"{额外使用'三太郎之斧'}"类）：不耗鬼火/瞬发名额/出击次数（维护者定案）；法术按基础方式效果结算（`_auto_cast_copy` 共用助手）、战斗牌按基础方式走完整战斗流程（来源式神须在场）；用后入墓地、照常 emit on_card_played（void/auto）；链式"再额外使用"=并列多个 step | ✅ |
| 分身复制法术 | `mirror_spell`（动作） | 挂 on_card_played：复制持有者使用的法术牌并自动使用一次（基础方式）——**主动/响应/自动使用均触发**（维护者定案；引擎 `mirror_copy` 标记防递归，复制自身不连锁；觉醒牌由数据侧条件 subtype_not: awaken 排除）；choose 目标沿用原选（仍合法）否则随机重选（烟烟罗的分身） | ✅ |
| 召唤继承 | `inherit_stats` / `energy_ratio`（summon 参数） | inherit_stats：召唤物复制来源**全部当前身材**（eff_power/max_health/health 快照为静态永久修正——含持续性/光环增益与受伤不满生命，不进 dyn 缓存；维护者定案，烟烟罗的分身）；energy_ratio：召唤物能量 = floor（来源能量 × 比例）（0.5） | ✅ |
| 恢复至满 | `full`（heal 参数） | full=True：恢复至生命上限（沐浴阳光"恢复所有生命"；走 Game.heal 管线，实际治疗量按损失计） | ✅ |
| 持续眩晕施加 | `lasting` / `until_event`（stun 参数） | lasting=True：持续眩晕条目（不随回合结束移除）；until_event=事件名列表：事件涉及看护式神（施加时来源，条目记 watch/watch_id）即经 `_release_lasting_stuns` 解除；`apply_seq`/`apply_uid` 记施加时点（emit_seq/卡牌 uid）防施加牌自身事件自解除（英雄无畏"直到鸦天狗使用牌、攻击或气绝"；气绝走现有清理）；条目结构见「关键词」眩晕行 | ✅ |
| 能量光环 | `energy_power` / `ids_energy_power`（stat_aura kind） | energy_power{divisor}：持有者每有 divisor 点能量 +1 力量（人多势众"镰鼬每有2能量便获得1力量"，scope=form）；ids_energy_power{ids,divisor}：ids 匹配实体每有 divisor 点能量 +1 力量（烟雾缭绕对分身，scope=form）；连续型读取时求值，同 stat_aura 既有通道 | ✅ |
| 形态要求光环 | `require_holder_form`（card_aura 参数） | 额外要求来源式神当前结附形态光环才生效（`_match_auras` 读取时动态判定——萤草 20200327"若萤草上有形态"）；scope=form/ability 清理同路径 | ✅ |
| 关键字目标过滤 | `keyword`（TargetSpec 过滤键） | 按是否持有指定关键字过滤式神目标（三类关键字列表多重集任一含即算——沐浴阳光/冬日暖阳"己方的[充能]式神"）；spec_pool_refs 统一校验 | ✅ |
| 无形态目标过滤 | `no_form`（TargetSpec 过滤键） | 仅未结附形态的式神（牌手滤除——今日委托·伍"消灭一个没有形态的式神"）；`_spec_filtered` 统一应用 | ✅ |
| 能量/形态条件键 | `holder_has_form` / `energy_ge` / `pre_play_form`（条件运算符） | {holder_has_form: bool}=能力持有者当前是否结附形态（萤草 20200327）；{energy_ge: n}=能力持有者当前能量 ≥ n（阳炎响应"额外消耗3能量"门控）；{pre_play_form: bool}=on_card_played 新 payload——该牌使用前所属式神是否已结附形态（打出前快照：形态牌先结附后发事件，收集时求值的 holder_has_form 对该牌恒真） | ✅ |
| 出击次数条件 | `assaults_left_ge` / `assaults_left_le`（条件运算符） | {assaults_left_ge: n} / {assaults_left_le: n}：控制者剩余出击次数 ≥/≤ n（真意之歌 20200423"若你出击次数大于0……否则……"两段 step 分流门控） | ✅ |
| 置入牌库位置 | `position`（generate 参数） | position="random"：生成牌随机插入牌库、**不洗牌**（"置入牌库"原版语义，维护者定案——同心协力"将一张此牌的复制置入你的牌库"）；缺省按 zone 既有语义（deck=库底） | ✅ |
| 幻境消灭 | `field_destroy`（动作） | **内部 op，数据不可用**：耐久 0 消灭流的待结算项——将幻境从所属牌手队列移除（能力同时失效）并发 `on_field_destroyed`（rules.md 第三十一章第四节） | ✅ |
| 形态切换 | `switch_form`（动作） | `into=<形态牌 id>`：目标式神旧形态走 _destroy_form 消灭流程（入墓、发离场事件），新形态凭空实例走 _attach_form 结附流程（身材覆盖、生命回满、发结附事件）——神木诅咒"使一个形态变成…"（配 TargetSpec `has_form` 过滤）与落英缤纷/晚樱之意"切换为…"（target=self）共用；目标未在场/无形态空操作 | ✅ |
| 结附期派系覆写 | `faction_override:<派系>`（形态牌 tags） | 结附期间 `ShikigamiState.faction` 临时改写（perm_faction 不动），形态离场经 _destroy_form 还原（诅咒之木"临时变为紫岩派系"）；_attach_form/_destroy_form 单点读写 | ✅ |
| 扎根 | `no_retreat`（形态牌 tags） | 己方回合开始时战斗区该式神不移回准备区（`_turn_start_schedule_retreat` 不登记移回；扎根） | ✅ |
| 群体复活 | `mass_revive`（动作） | side=all/self：双方（或控制者方）全部气绝未离场式神逐个走 _revive；`countdown_damage=True`：全部复活完毕后每个被复活者对其牌手造成等同于其复活前气绝倒计时的伤害（快照在复活前取，来源=该式神——绽放） | ✅ |
| 气绝转化参数 | `allow_defeated` / `repeat_on_kill` / `repeat_on_revive`（damage/heal 参数） | allow_defeated：气绝（未离场、等级≥1）式神目标放行并转化——heal 改为气绝倒计时 -1（减到 ≤0 立即复活）、damage 改为 +1（均不再视为治疗/伤害、不发事件；与来源伪关键字 heal_defeated_countdown/damage_defeated_countdown 为并存的授权通道）；repeat_on_kill/repeat_on_revive：本步造成新气绝/引发复活即对原目标列表整体重复（上限 10 次——樱吹雪） | ✅ |
| 逐目标动态数值 | `{"health_of"/"half_health_of": "target"}`（amount 通道） | _run_step 不做预解析、原样传字典由 damage op 逐目标求值（`_target_amount`）：按每个目标角色自身当前生命（一半向下取整——凋零之森"对他所有角色造成等同于他自身一半生命的伤害"）；`{"health_of": "self"}` 仍走 _step_amount 以来源式神当前生命求值（灾厄之花）；`{"orb": true}` amount 通道 = 控制者当前鬼火（汲取养分，与次数通道 orb 同义） | ✅ |
| 回合方目标池 | `active_character`（目标池） | 当前行动玩家的所有角色（在场式神+牌手）——目标侧随回合方而非效果控制者（凋零之森） | ✅ |
| 有形态目标过滤 | `has_form`（TargetSpec 过滤键） | 仅结附着形态的式神（牌手滤除——神木诅咒取对象口径）；`prefer_wounded`：候选中存在受伤（生命<上限）或气绝式神时收窄到该子集再交 random 均等取（晚樱之意"优先受伤或气绝式神"，气绝者入池需配 include_defeated）；include_defeated 同步纳入 choose 校验池（spec_pool_refs，樱花妖牌选择气绝目标） | ✅ |
| 事件基础力量次数 | `{"event_base_power": key}`（repeat count 通道） | 触发事件 key 所指式神的当前基础力量（落英缤纷/晚樱之意"重复该式神基础力量的次数"，"该式神"= 复活/气绝事件角色；开始时一次性取值） | ✅ |
