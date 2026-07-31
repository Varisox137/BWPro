# 卡牌实现状态

对照 `card_data_raw.md`（原版描述）逐项记录实现状态。更新卡牌数据或新增卡牌时请同步本文件。

- ✅ = 已实现且与原版描述一致
- ⚠️ = 已实现但与原版描述存在出入（见下方"与原版描述的出入"）
- ❌ = 未实现

## 纸人武士（100001）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 无基础能力 |
| 01 武士之拳 | ✅ | |
| 02 武士之笛 | ✅ | 本回合增益：buff_power scope=turn（ext["turn_power"] 记账，回合开始清除） |
| 03 武士之笠 | ✅ | |
| 04 武士之刃 | ✅ | |

（新手包成品式神，仅 4 卡——构筑可选；卡组位 4 种 ×2 凑满 8 张。）

## 天邪鬼军团（100002）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 无基础能力 |
| 01 天邪鬼赤·燃烧 | ✅ | |
| 02 天邪鬼黄·鼓舞 | ✅ | 牌手级监听（player_aura scope=turn，无 once_key 可叠加）；"法术伤害"按非战斗（effect）伤害（维护者答复(2)） |
| 03 天邪鬼青·鸢击 | ✅ | |
| 04 天邪鬼绿·拍打 | ✅ | |

（新手包成品式神，仅 4 卡——构筑可选。）

## 白狼（100101）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 己方回合、战斗伤害、即时时机 |
| 01 起弓 | ✅ | [穿刺] 按"造成伤害前移除护甲/屏障"实现 |
| 02 文射 | ✅ | |
| 03 残心 | ✅ | keep_attack_buffs |
| 04 离 | ✅ | |
| 05 会 | ✅ | 所选目标仅己方可见：delay_grant secret，联机状态脱敏抹除对手视角的 chosen |
| 06 援护 | ✅ | |
| 07 觉醒·白狼 | ✅ | 任意伤害（非仅战斗）触发，与原版一致 |
| 08 无我 | ✅ | |
| 21 森佑灵矢 | ❌ | 协战主牌（白狼&萤草，id 10010121；协战机制已实现、萤草基础数据已入库，主牌待子选项森佑灵引的[庇佑]与牌库抽形态机制引入） |
| 51 灵矢贯虹 | ✅ | 协战子选项（白狼侧战斗牌）：三步齐备——法术强化力量再授予（reapply_attack_buff_power：起弓/离/无我 attack_buffs 力量部分合计再授予，仅力量）、羁绊 1 萤草形态进场效果再触发（trigger_form_enter，未结附空操作）、羁绊 2 鼓舞消耗转化（维护者答复(3)）；主牌仍缺（见上行） |

## 兵俑（100102）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | |
| 01 尘刀 | ✅ | |
| 02 古尘之盾 | ✅ | |
| 03 不动如山 | ✅ | |
| 04 冲撞 | ✅ | 跨回合手牌触发式增强 |
| 05 森罗之阵 | ✅ | |
| 06 觉醒·兵俑 | ✅ | 原版卡面 +0/+0，实现无身材加成，一致 |
| 07 古尘之壁 | ✅ | +x生命/+x生命上限（持久性增益，气绝清除；不算治疗，不走 heal 事件） |
| 08 尘缚之阵 | ✅ | 已加"兵俑在战斗区时免疫直接消灭"（destroy_immune）；"无法替换"按已确认的自定义"战斗区锁定"实现 |

## 茨木童子（100103）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 永久成长（perm=True，维护者答复(3)） |
| 01 鬼之手 | ✅ | 非追猎：效果步 force_enter_combat（random_pick 不取对象不吃帷幕 + if_combat_empty 空发），拉入者随即成为本场无目标战斗被攻击者 |
| 02 豪拳 | ✅ | 临时 +3 力量（维护者答复(3)） |
| 03 黑焰之手 | ✅ | [远程] |
| 04 迁怒 | ✅ | on_shikigami_defeated 新 payload in_combat（无论消灭原因）；准备区串行 damage（暴风之主先例） |
| 05 断臂 | ✅ | {max_power_gap: self} 补峰值差值（ext["max_power"] 历史峰值只增） |
| 06 罗生门之鬼 | ✅ | bump_ext 计数 + random_enhance 档位强化（1/3/5 次；tiers 按 min 门控、实例 enhance_got 去重；强化写入 mods：keywords_add/form_power_delta/form_health_delta/playable_when_defeated+revive_on_play） |
| 07 地狱之手 | ✅ | [追猎] choose 敌方式神；temp_grants 击杀（敌方限定，答复(7)）→ followup_attack 追加攻击生命最低者 |
| 08 觉醒·茨木童子 | ✅ | +0/+1（awaken_health）；"力量翻倍"= 获得等量当前力量临时增益（{power_of: self}，答复(3)） |
| 21 狂歌豪情 | ✅ | 协战主牌（茨木&酒吞，id 10010321）：options [10010351 地狱豪焰, 10010951 醉酒当歌]；构筑池双归属 |
| 51 地狱豪焰 | ✅ | 协战子选项（茨木侧战斗牌）：temp_grants 击杀（方式/敌我不限，答复(9)）→ 固定项 player_aura（haoyan_base：茨木用战斗牌 +1/+1 护甲，不可叠加）+ random_aura 随机一项不重复豪焰监听（cd/pow/heal/burn）；羁绊经 step 级 condition {shikigami_active: 100109}，酒吞自伤正常触发其能力 |

## 妖刀姬（100123）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 按原版"对敌方牌手造成伤害时"（任意伤害） |
| 01 不祥之刃 | ✅ | |
| 02 见切 | ✅ | |
| 03 战意 | ✅ | |
| 04 一闪 | ✅ | cost 0 |
| 05 禁锢之刀 | ✅ | 按原版：妖刀姬消灭任意式神均计数（含消灭己方式神）；镜像对局不计敌方同名的击杀 |
| 06 妖刀万华 | ✅ | |
| 07 杀念 | ✅ | |
| 08 觉醒·妖刀姬 | ✅ | 按原版"造成伤害时"（任意伤害）；[迅捷] 为一次性 |
| 51 刃影叠岚 | ✅ | 协战子选项（妖刀姬侧法术觉醒）：card_aura 数值通道（fast + power 1/shield 1，可叠加）+ 羁绊 launch_attack 姑获鸟（联动其攻击后退回）；主牌 10010621 刃影鹤唳 ✅（姑获鸟全卡已入库） |

## 大天狗（100104）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 触发块：使用非觉醒法术→记录该法术并注册一次型[倒计时2]，归零凭空免费复用同名牌（非从手牌、不耗火）；记录随气绝丢失；倒计时来源按 A2 决策 = 式神 id |
| 01 风神一扇 | ✅ | 投射 2 伤 + retreat；受伤者经块内暂存 last_damage_victims 引用 |
| 02 吾即正义 | ✅ | generate 谓词扩展（max_level=source / exclude_self）；计数 10 张法术后经 add_mod require 置位 transformed，改用 alt_effects（消灭所有敌方式神）；变为后失去[瞬发]（维护者答复 2，alt_remove_keywords） |
| 03 暴风之盾 | ✅ | gain_shield + delay_grant（下己方回合开始再 +2；选择目标随延迟条目存储）；响应挂 on_before_assault（受击方即战斗区式神） |
| 04 黑羽之刃 | ✅ | 投射 4 伤 + delay_grant scope="play"（"本次使用期间"消灭敌方式神→抽 1，出牌结束窗口清除） |
| 05 暴风之主 | ✅ | 形态能力读 on_card_played payload affected_refs（该次出牌效果伤害过的敌方式神；维护者答复(7)：只计敌方式神、去重，牌手与己方式神不计） |
| 06 天狗风乱 | ✅ | distribute_damage 6 点随机分配（敌方角色，生命≤0 退出分配） |
| 07 羽刃暴风 | ✅ | 全体敌方角色 3 伤 |
| 08 觉醒·大天狗 | ✅ | 已按维护者答复(10)：法术觉醒新流程——替换继承原能力的动态倒计时（含记录的法术）并变为倒计时 1，countdown_delta -1 在替换后结算（归零即自动复用记录法术）；+2/+2 经 awaken_power/awaken_health 于"觉醒后"授予 |

## 妖琴师（100124）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 静态倒计时块（initial 3，治疗=两步：friendly_shikigami + self_player）+ "使用觉醒法术牌时倒计时-3"触发块（subtype: awaken 判等）；觉醒替换后由觉醒能力块的同名触发接续 |
| 01 觉醒·入阵歌 | ✅ | 觉醒倒计时 distribute_damage 5（enemy_character）；打出即 -3 至 0 立即归零（同次出牌：先注册新倒计时再触发） |
| 02 惊弦 | ✅ | choose any_shikigami 的 countdown_delta -2（可点任意式神；无倒计时修正 -0） |
| 03 大合奏 | ✅ | replay_countdown(skip_forms)：按 countdown_history 首次出现顺序重放妖琴师生效过的基础/觉醒倒计时块（维护者答复(8)：形态来源不计入；_countdown_block_for 按来源 id 找回块） |
| 04 觉醒·神乐歌 | ✅ | 倒计时-1 + 1 力量/1 生命（friendly_others；增益为临时修正，气绝清除）；同次 -3 立即归零 |
| 05 疯魔琴心 | ✅ | choose enemy_shikigami +2（无倒计时修正 -0）+ 自身 -2（可立即归零） |
| 06 魔音扰心 | ✅ | 主动=delay_grant(scope=turn) 登记一次性无效化；响应=response 覆盖块直接无效化当前用牌（CardDef.response 新字段：主动/响应结构不同） |
| 07 觉醒·镇魂歌 | ✅ | 倒计时 draw 1 + gain_orb 1；同次 -3 立即归零 |
| 08 余音 | ✅ | 自身 -3（立即归零）+ friendly_others -1（气绝者不在目标池） |
| 21 风之乐章 | ✅ | 协战主牌：options 双子选项，choice 选择后生成 token 视作从手牌使用，主牌离手进 exiled |
| 51 幻音绝弦 | ✅ | delay_grant（on_turn_start，uses=1，不用 scope=turn 以免同批清除）：己方式神倒计时-1 + 气绝者气绝倒计时-2（revive 参数，≤0 立即复活）；羁绊=随机一目连形态牌 |

## 一目连（100125）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 离场/被消灭时触发倒计时 |
| 01 风符·破 | ✅ | |
| 02 风符·护 | ✅ | |
| 03 罡风 | ✅ | |
| 04 风符·势 | ✅ | |
| 05 觉醒·一目连 | ✅ | 进场/离场/被消灭均触发 |
| 06 风符·瞬 | ✅ | |
| 07 风符·湮 | ✅ | |
| 08 风符·龙 | ✅ | 计数绑定卡牌实例 |
| 51 风韵雅乐 | ✅ | 协战子选项（一目连侧战斗牌）：replay_countdown(100125) 重放 + 羁绊=随机妖琴师觉醒牌（generate subtype=awaken） |

## 以津真天（100126）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 静态倒计时块（initial 2）：generate card_id 指定生成黄金羽 token（token 不入随机池） |
| 01 金羽焕生 | ✅ | generate card_id ×2 |
| 02 风之舞 | ✅ | 卡牌触发器按 on_card_played 的 golden_feather payload 计数（add_mod persistent，打出装配快照；含金风流羽） |
| 03 金风流羽 | ✅ | tags golden_feather 视为黄金羽（记账/触发同）；cost_zero_if {ext: feather_used_turn} 条件免费（费用先于记账计算，自身不免自身） |
| 04 不可饶恕 | ✅ | grant_immunity(scope=turn, unique) 回合级战斗伤害免疫：回合号记账自然过期；多次使用黄金羽不重复授予 |
| 05 射怪鸟事 | ✅ | 响应挂 on_before_defeat（条件显式式神 id）；discard 写 memo["discarded_count"] + draw {"memo": key} 组合"弃多少抽多少" |
| 06 觉醒·以津真天 | ✅ | 觉醒倒计时 initial 1（来源=觉醒牌 id）；"黄金羽可以敌方角色为目标"由黄金羽的使用方式表达（见出入 5；已按维护者答复(11)） |
| 07 千羽风之舞 | ✅ | 战斗牌"其它效果步"首个消费者（见出入 6）；step 级条件 {player_ext: feather_used_turn} |
| 08 流浪之羽 | ✅ | 形态能力挂 on_card_played（golden_feather payload）；两条 random_damage 各取 1 目标，两次可命中同一目标 |
| 21 致命之羽 | ✅ | 协战主牌：同风之乐章（options=[鎏金幻羽, 蚀刃毒羽]） |
| 51 黄金羽 | ✅ | 衍生 token 法术（不可构筑）；基础效果固定打敌方牌手，觉醒后狙击走 methods（choose 敌方角色） |
| 52 鎏金幻羽 | ✅ | mod_hand 实例修饰（真黄金羽=tags+token 谓词，金风流羽不修饰；once_key 不可叠加）：气绝时可用/伤害+1/双方气绝倒计时-1 三读取点；羁绊=鸩倒计时-2 |

## 萤草（100127）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 使用与当前形态不同的形态牌时抽 1：on_form_attached payload form_changed（无当前形态或新旧形态 id 不同）；8 卡未加入（card_data_raw），暂无实弹触发场景，机制对任意形态牌生效（测试库注册形态牌验证） |

（萤草 8 张卡未引入，不可构筑；仅基础数据入库——灵矢贯虹羁绊 1 的搭档。）

## 鸩（100128）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 静态倒计时块（initial 2）：敌方牌手 2 破甲 + bump_ext 累计 x（zhen_proc，气绝不清） |
| 01 鸩羽 | ✅ | battle_immunity 带 Step.condition：战斗开始时以 {defender: 被攻击者} 求值（defender_has_fragile） |
| 02 鸩羽苏生 | ✅ | countdown_delta -2（可立即归零）+ 抽 1 |
| 03 寂寥心象 | ✅ | 每回合合计一次（turn_mark/turn_mark_not 门控，任一回合开始双方清除）；目标种类定分支；"等量"=事件获得量（{event: amount}）；敌方战斗区为空时该分支空结算但仍消耗名额 |
| 04 毒蚀 | ✅ | convert_damage 战斗作用域：已按维护者答复(5)——伤害事件生成点全额转化为等量破甲（护甲不再先吸收；不再视为伤害）；响应挂 on_before_assault（条件显式式神 id，响应收集不带 holder） |
| 05 觉醒·鸩 | ✅ | x = 基础+觉醒倒计时生效合计（维护者答复 9），{base: 2, ext: zhen_proc} 动态数值；觉醒倒计时来源=觉醒牌 id，先给破甲再计数 |
| 06 致命诱惑 | ✅ | 战斗牌 grant_keyword step = 战斗作用域条件授予（吸血；战斗终止点移除） |
| 07 碧羽散华 | ✅ | victim 侧 ext 标记（当前卡池仅鸩给予破甲，与"鸩造成的"等价；已按维护者答复(1)扩展到牌手——牌手沿用"其任一式神持标记"语义）；离场经 on_form_destroyed 前置 emit 的形态能力清除；与毒蚀同场时经 converted 标记防止转化循环（伤害→破甲→伤害，净效果=原伤害） |
| 08 毒之华 | ✅ | temp_grants 绑本次战斗；"一半生命"=受伤后当前生命向下取整（{half_health_of: victim}）；on_damage payload 补 battle 键供战斗绑定触发匹配 |
| 51 蚀刃毒羽 | ✅ | 协战子选项（鸩侧战斗牌）：已按维护者答复(2)重做——temp_grants 挂"攻击时"（on_before_assault），目标有破甲则 fragile_echo 记录数值，本次战斗结束后一次性回赋等量破甲（见出入 9）；羁绊=以津真天倒计时-2 |

## 凤凰火（100105）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_card_played {player: self, card_type: spell, shikigami: 100105} → 投射 1（含觉醒/响应/凭空自动使用） |
| 01 凤鸣 | ✅ | [瞬发] 打敌方牌手 2 |
| 02 瑞翔 | ✅ | 所有敌方角色 1 |
| 03 引燃 | ✅ | 可对己方式神（维护者答复）；消灭追加走 delay_grant scope="play" + victim_player 语境目标（敌己两向） |
| 04 焚羽 | ✅ | 非战斗伤害 +1：on_damage_start {source_shikigami: self, kind: effect} boost_damage（含觉醒后其他式神法术触发的投射） |
| 05 凤火 | ✅ | |
| 06 觉醒·凤凰火 | ✅ | 己方式神任意专属法术 → 投射 1（{shikigami_not: null} 排除中立牌；来源=凤凰火，吃焚羽、计炎舞） |
| 07 炎舞 | ✅ | [贯通] 投射 5（步骤显式 piercing:true）；增强按次数不限伤害类型（on_player_damaged persistent 计数，打出装配快照） |
| 08 出云 | ✅ | 使用法术牌时 generate 凤火入手 |
| 21 涅槃明灯 | ❌ | 协战主牌（凤凰火&青行灯，id 10010521；副侧子选项烛火重燃 10011251 未实现） |
| 51 涅槃业火 | ✅ | 协战子选项（凤凰火侧）：spell_echo 法术回响序列（凤鸣→引燃→瑞翔，once_key 不可叠加；敌方式神触发亦可；自动使用凭空/免费/随机合法目标/触发凤凰火能力）+ 羁绊明灯 |

## 山童（100116）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[贯通]：ShikigamiDef.keywords → perm_keywords（永久类别，气绝不清除） |
| 01 鲁莽 | ✅ | 己方回合开始 launch_attack 自动攻击（不耗火/次数；气绝/未在场空操作） |
| 02 怪力 | ✅ | 永久 +1 力量按常规效果步执行（战斗牌流程不再误提取为本次战斗战力） |
| 03 怒吼 | ✅ | 自身永久 +1、其他己方式神临时 +1（分层） |
| 04 笨拙 | ✅ | power_override：敌方回合力量覆写为 0（覆写全部加成层），己方回合开始解除 |
| 05 碎岩 | ✅ | +2/+2 [穿刺]（批次 0 移除目标全部护甲/屏障再结算） |
| 06 觉醒·山童 | ✅ | [贯通]（牌面语义显式落地）+ grant_immunity scope=perm kind=effect from_side=enemy；复活重新授予 |
| 07 伺机 | ✅ | 响应挂 on_before_assault {victim_shikigami: 100116}；敌方回合光环 card_aura card_id 自指（"此牌"+2力量，turn=opponent）；counter_piercing 反击贯通 |
| 08 崩山 | ✅ | {perm_power: self} 使用时快照各自加（先战斗区后准备区）；山童的贯通不传导本牌法术伤害（步骤不标 piercing） |

## 姑获鸟（100106）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_after_assault {attacker_shikigami: self} → retreat（攻击后移回准备区；刃影叠岚羁绊联动已验证） |
| 01 伞剑 | ✅ | 战力 +2；手牌触发式光环：on_after_assault {attacker_side: friendly, attacker_not_shikigami: 100106} → card_aura keywords [fast] scope=turn（其他己方式神攻击后本回合此牌瞬发） |
| 02 影翼 | ✅ | 形态 4/4：on_before_assault {attacker_shikigami: self} → buff_power +1（每次攻击前获得 1 力量，临时持续性） |
| 03 丛云鹤舞 | ✅ | [直击]（keywords 授予通道） |
| 04 金鸾 | ✅ | 形态 3/6；手牌触发式瞬发光环同伞剑 |
| 05 天翔鹤斩 | ✅ | 战力 +3；target 扩展键 battle=true + optional=true：有未气绝敌方准备区式神时必须指定（有目标战斗，同追猎管线），否则可不带目标退化为普通战斗；battle_immunity 免疫战斗伤害；[贯通] |
| 06 偷袭 | ✅ | 敌方回合瞬发光环（on_turn_start 登记，伺机先例）；[响应]挂 on_turn_end {player: opponent, combat_empty: opponent}：无当前战斗的响应战斗牌按完整战斗流程发起新战斗；回合结束响应排序 = 当前回合方回合结束延时效果先结算（答复3） |
| 07 慈乌稚子 | ✅ | 形态 8/6：其他己方式神攻击后姑获鸟获得[迅捷]（on_after_assault → grant_keyword haste，一次性消耗） |
| 08 觉醒·姑获鸟 | ✅ | +2/+0；手牌瞬发光环同伞剑；[觉醒][远程]（on_awakened + on_shikigami_revived 双块 grant_keyword，山童先例）；消灭敌方式神时延时 followup_attack 追加攻击（不享受原战斗牌加成） |
| 21 刃影鹤唳 | ✅ | 协战主牌（姑获鸟&妖刀姬）：options [10010651 鹤唳回风, 10012351 刃影叠岚]；构筑池双归属 |
| 51 鹤唳回风 | ✅ | 协战子选项（姑获鸟侧法术觉醒，+1/+1）：[觉醒]强化基础能力——攻击后移回准备区 +1 力量并恢复所有生命（heal {missing_health: self}）；羁绊 launch_attack 妖刀姬（未出战/气绝空操作——刃影叠岚先例） |

## 海坊主（100107）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_heal 过量转化：payload 新增 overheal（治疗量-实际治疗量）；{source_shikigami: self, target_side: friendly, overheal_ge 1} → 目标获得等量护甲。实际恢复 0（满血）不发 on_heal、不触发转化（答复 0） |
| 01 治愈之水 | ✅ | [瞬发]；{base: 3, half_shield_of: self} 动态数值（海坊主护甲 //2，向下取整）；choose any_character 新池 |
| 02 灵能 | ✅ | 形态 3/6：on_heal {source_shikigami: self, target_kind: player} → 自身恢复等量（按实际治疗量） |
| 03 沧海之盾 | ✅ | +2 甲 + delay_grant **bind=chosen**（延迟能力绑定被选式神；scope=turn）：其造成战斗伤害（kind≠effect，含反击）时为牌手恢复 2；[响应]挂 on_before_assault {victim_in_combat: true} 新条件键，choose 自动取事件 victim（古尘之盾先例） |
| 04 水龙卷 | ✅ | 先自身 +3 甲，再按 {shield_of: self} 快照造伤（含本牌刚获得的 3 甲） |
| 05 祝福之水 | ✅ | [瞬发]；friendly_character 新池（己方在场式神 + 己方牌手） |
| 06 巨浪 | ✅ | damage 记录块内暂存 last_damage_total（实际造成伤害合计，扣减生命口径，护甲吸收不计）→ heal {memo: last_damage_total} 恢复自身 |
| 07 蹈海 | ✅ | 形态 4/9：on_damage {source_shikigami: self, kind_not: effect} → friendly_others_character 新池（己方其他角色，排除来源含牌手）恢复等量 |
| 08 觉醒·海坊主 | ✅ | +1/+3；恢复 3；觉醒替换 = 基础保留 + 过量治疗额外转等量力量（buff_power 临时修正） |

## 青坊主（100111）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | "你恢复生命时"口径 = 己方任意角色实际恢复（target_side friendly）；turn_mark 门控每回合合计一次 → random_damage 敌方角色 2×1 |
| 01 佛印 | ✅ | [瞬发]；两条 heal step（self_player / enemy_player） |
| 02 禅心 | ✅ | 形态 1/6：同口径 + turn_mark 门控 → draw 1 |
| 03 慈悲 | ✅ | grant_keyword unyielding |
| 04 佛光 | ✅ | heal 记录块内暂存 last_heal_targets → side_of_last_heal 新池（上一步治疗目标所属方的所有角色）恢复 3 |
| 05 舍生 | ✅ | [瞬发][响应]；destroy 青坊主 + grant_immunity kind=all scope=turn（**牌手级免疫**新通道：PlayerState.immunities，按回合号过期）；响应挂 on_damage_start {victim_lethal: true} 新条件键（面板伤害 ≥ 当前生命，护甲计算前判定） |
| 06 法界唯心 | ✅ | 形态 5/6，tags [heal_reversal]：引擎 heal() 前置检查——控制者对敌方的恢复改为等额伤害（不发出任何治疗事件，伤害事件照常）；进场恢复 4 选择敌方角色时同样被反转 |
| 07 觉醒·青坊主 | ✅ | +0/+2；恢复 8 目标 = 你的牌手（答复 2）；觉醒替换（原文不含基础）：无门控，恢复时对所有敌人（enemy_character）1 伤 |
| 08 轮回 | ✅ | set_health 新 op（非治疗非伤害，钳制 [1, max_health]）{enhance: true, base: 10}；增强计数 = on_before_assault 最终目标为你的牌手（含反击、无论是否受伤；以式神为目标不计；答复 8）；X=0 按原文仍可使用（变为 10） |

## 青行灯（100112）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_turn_start {player: opponent, orb_ge: 1} → generate 明灯（敌方回合开始时有剩余鬼火） |
| 01 明灯 | ✅ | [瞬发] gain_orb 1；凤凰火/青行灯协战与青行灯基础能力的产物 |
| 02 青灯夜谈 | ✅ | **pending_choice 结算中交互选择**新机制（GameState.pending_choice + choose 指令 + _suspended 内存态续点）：deck_top_pick 次数={orb: true}（0 鬼火无效果、清空仍执行，答复 4），每次选择入手后洗牌库，末次后清空鬼火续块；联机 sanitize 对非选择方抹除 options |
| 03 幽光之火 | ✅ | 形态 4/5：on_before_assault {attacker_shikigami: self} → generate 明灯（发起攻击即计，含出击/战斗牌/效果发起） |
| 04 百闻一得 | ✅ | discard card_id 精确弃明灯（无明灯不弃、升级仍执行）；friendly_lowest_level 新池（并列全入池由使用者选择，答复 7）；level_up 新 op 不走升级次数，满 3 级 overflow_draw 改抽 1 |
| 05 百物语之火 | ✅ | 形态 4/5：on_turn_end {player: self} → gain_orb 1 |
| 06 不灭之火 | ✅ | 形态 4/5：on_form_destroyed {target_shikigami: self, orb_ge: 1}（离场前 emit 收集，含被替换/气绝连带，鸩先例）→ consume_orb 1 → revive（气绝先复活）→ reattach_form 新 op（墓地同一实例重新结附，不生成新牌，答复 6） |
| 07 吸魂灯 | ✅ | repeat 新 op（次数={orb: true}，0 鬼火无效果、清空仍执行）：投射 5 ×鬼火，独立求值，clear_orb 清空 |
| 08 觉醒·青行灯 | ✅ | +1/+1；tags [awaken, orb_store]：觉醒替换 = 基础保留 + 鬼火储存（引擎回合开始不清零、储存累加封顶 4，答复 3） |
| 51 烛火重燃 | ❌ | 协战子选项（青行灯侧幻境）：幻境机制未实现，暂缓 |

## 酒吞童子（100109）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_damage {victim_shikigami: self} → 临时 +1 力量（任意伤害按次，维护者答复(10)） |
| 01 醉里乾坤 | ✅ | [瞬发]；自伤 1（正常触发基础能力）+ draw 1 |
| 02 狂气 | ✅ | 战力 +1；本次战斗获得[不屈]（战斗牌 keywords 授予通道） |
| 03 鬼王 | ✅ | 形态 6/10：进场时对自身 damage 4（触发基础能力） |
| 04 狂啸 | ✅ | bump_ext min_health_turn：本回合生命不会降到 1 以下（扣减生命处钳制，半回合作用域回合开始清除）；[响应]挂 on_damage_start {victim_shikigami: 100109, victim_side: friendly} 覆盖块 |
| 05 无尽愤怒 | ✅ | 战力 +2；triggers on_damage（己方来源自伤，turn_mark 门控本回合一次）→ card_aura power 2/shield 2 scope=turn（本回合受过己方伤害后此牌 +2/+2） |
| 06 神子 | ✅ | 形态 6/8：[瞬发]（卡牌级）+[不屈]（结附期间授予） |
| 07 觉醒·酒吞童子 | ✅ | +1/+3；[觉醒][贯通]（on_awakened + on_shikigami_revived 双块，山童先例）；受伤改为获得等量力量（buff_power {event: amount}） |
| 08 百鬼夜行 | ✅ | [瞬发]；X = ext["damage_taken_turn"]（本回合所受伤害之和，伤害扣减生命处记账、半回合作用域）；两段 damage：friendly_others（排除自身）+ enemy_shikigami（答复4） |
| 51 醉酒当歌 | ✅ | 协战子选项（酒吞侧战斗牌）：[不屈]；自伤 3 → gain_shield 3 标 no_extract（不提取为战斗牌护甲前置结算——否则被自己的自伤消耗；按步骤顺序自伤后获得）；羁绊 generate 茨木当前等级战斗牌（level="shikigami" 精确匹配，未出战/未在场空操作） |

## 犬神（100115）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_upgrade {target_shikigami: self} → generate 心身炼磨（指令升级与 level_up op 两来源均触发——on_upgrade payload 新增 target Ref，level_up 补 emit） |
| 01 羁绊的价值 | ✅ | heal {missing_health: self}（姑获鸟觉醒先例，恢复全部已损失生命） |
| 02 心斩 | ✅ | 战斗 +0/+2 |
| 03 心即归处 | ✅ | [瞬发] revive self；playable_when_defeated + only_when_defeated 新字段（第十三阶段）："仅在犬神气绝时可用"硬门控——存活时主动使用报错、响应收集直接跳过 |
| 04 恶·即·斩 | ✅ | 战斗 +4/+0 |
| 05 心技一体 | ✅ | 形态 3/5：card_aura scope=form 新作用域（绑定持有者、随形态离场移除，气绝经 _destroy_form 同路径）+ power_ext/shield_ext 新参数（ext 数值通道，读 lianmo_used_game——心身炼磨 tags [lianmo] 出牌记账）；手牌数值显示已含光环 ext 通道（第十三阶段，刃影叠岚同解） |
| 06 守护 | ✅ | 战斗 +0/+4；[响应]挂 on_before_assault {victim_side: friendly, victim_kind: shikigami, victim_not_shikigami: 100115, attacker_side: enemy}：响应插入把犬神移入防守方战斗区、无目标战斗重读目标 = "攻击目标改为犬神"（零新引擎代码）；追猎类定向战斗可响应——守护者照常移入并获得 +0/+4，但目标不转移仍打原定目标（第十三阶段定案） |
| 07 心剑乱舞 | ✅ | 形态 4/9：card_aura scope=form keywords [fast]（犬神的牌获得[瞬发]，读取时求值） |
| 08 觉醒·犬神 | ✅ | +1/+1；on_turn_end {player: self, holder_defeated: true} + trigger_when_defeated 新字段（能力收集对气绝者放行——仅气绝时触发）：revive + perm +1/+1 |
| 51 心身炼磨 | ✅ | 衍生（升级产物）：perm +1/+1；tags [lianmo]；conditional_keywords 新字段（{keyword: fast, level_ge: 2}）+ cost_zero_if 扩 {level_ge: 3} |

## 桃花妖（100119）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_heal {source_shikigami: self, target_side: friendly, target_kind: shikigami} / on_shikigami_revived {source_shikigami: self, shikigami_side: friendly} → 临时 +1 力量（revive op 补 source/reason="effect" 传递；倒计时复活 source=None 不触发） |
| 01 桃之馨息 | ✅ | choose any_character heal 5 |
| 02 花信风 | ✅ | [瞬发]；search_deck 新 op（按选择目标式神 id 滤牌库 rng.choice 入手，命中才洗牌库、未命中不洗——第十三阶段定案）；边界：选择池 friendly_shikigami 限在场式神（气绝/未升级式神暂不可选） |
| 03 桃之夭夭 | ✅ | cost 0 + keywords [inspire]（鼓舞关键字登记）；basic_boost +2/+2 出击加成 |
| 04 丰实 | ✅ | 形态 3/7：进场与 on_turn_start {player: self} → heal 3，friendly_injured 新池 + TargetSpec {random: 1} 新键（rng.sample，repeat 每轮重解析重随机） |
| 05 桃语春风 | ✅ | choose friendly_defeated 新池 revive + grant_keyword haste（迅捷天然一次性类别） |
| 06 盛开 | ✅ | 形态 4/9：进场与 on_turn_start → repeat 3 × heal 2（friendly_injured + random 1） |
| 07 桃华灼灼 | ✅ | conditional_keywords {keyword: fast, if_alive: true}（未气绝得[瞬发]）+ playable_when_defeated；revive friendly_defeated 全体 → grant_keyword haste 全体（第二步在复活后解析，复活者同获迅捷） |
| 08 觉醒·桃花妖 | ✅ | +2/+1；choose any_character heal 5；同基础两 trigger 改 perm +2/+2 |
| 51 桃红簇簇 | ✅ | 协战子选项（桃花妖侧形态 3/6；21 繁花似锦主牌待樱花妖 100403）：on_enter_combat/on_leave_combat 新事件 {player: self} → heal 2 context shikigami（治疗来源=桃花妖→连锁基础赋益）；on_damage_start {victim_side: friendly, victim_kind: shikigami, victim_lethal: true, victim_in_combat: false} → grant_immunity kind=all scope=once 新作用域（消耗式，_combat_immune/_effect_immune 命中即移除）→ destroy_form self；羁绊 step 级 condition {shikigami_active: 100403} 门控恒 False（樱花妖未加入） |

## 与原版描述的出入（已决议，2026-07）

1. **妖刀姬基础/觉醒能力**：按原版"对敌方牌手造成**伤害**时"（任意伤害）实现。
2. **尘缚之阵**："免疫直接消灭"按原版实现；"无法被其他式神替换"是对原版定义不清晰的细化，按已确认的自定义"战斗区锁定"保留。
3. **会**："所选目标仅己方可见"已实现（secret 延迟能力 + 联机脱敏；热坐下日志与场况本就不回显目标）。
4. **禁锢之刀**：按原版，妖刀姬消灭己方式神（如因敌方的伤害转移效果）也计数并增强。
5. **黄金羽的觉醒目标扩展**：已按维护者答复(11)——觉醒后黄金羽效果实为"选择一名
   敌方角色，造成 2 点伤害"（含牌手），表达为黄金羽的使用方式（PlayMethod
   requires_awaken 门控 + choose 敌方角色目标，从手牌使用时主动选择）；基础效果仍
   固定打敌方牌手（未觉醒时照常可用，觉醒后二选一）。气绝的以津真天使用（经鎏金幻羽
   修饰）气绝时可用的黄金羽时，觉醒能力不在场——门控要求未气绝，只能打敌方牌手。
6. **战斗牌"其它效果步"**：战斗牌流程在战力/护甲与战斗专用步（grant_keyword/battle_immunity/
   convert_damage）提取后，开始执行剩余普通 step（千羽风之舞的生成金风流羽为首个消费者）；
   attack_buff（起弓/离）走既有挂账路径同样跳过，旧卡行为不变。
7. **大合奏**：卡面"基础能力每生效过一种"按维护者答复实现——本局妖琴师的基础/觉醒倒计时
   能力每生效过一种（countdown_history 首次出现顺序，每种至多一次）依次重放对应倒计时块；
   形态牌来源不计入（维护者答复(8)，replay_countdown skip_forms）；不同对局生效顺序不同
   则大合奏顺序随之不同。
8. **觉醒·神乐歌的增益**："获得1力量与1生命"按临时修正实现（气绝清除；与 buff_power/
   buff_health 默认语义一致），非永久修正。
9. **蚀刃毒羽"相同数量的破甲"**：已按维护者答复(2)实现——战斗牌赋予的临时能力在战斗
   步骤"攻击时"（on_before_assault，即时时机）触发：若战斗目标此时有破甲，fragile_echo
   记录该数值并获得一次性"本次战斗结束后赋予该目标等量破甲"（引擎 _battle_echo；
   战斗中止则丢弃）。替代原 on_damage payload fragile 方案。
10. **灵矢贯虹**：已按维护者答复(3)三步齐备——"本次攻击白狼获得当前自身法术牌强化
    效果的力量加成"实现为 reapply_attack_buff_power（起弓/离/无我的 attack_buffs 挂账
    力量部分合计，作为攻击后到期强化再次授予；按原文只取力量，关键字不重复）；羁绊 1
    "攻击前触发萤草当前形态进场效果"实现为 trigger_form_enter（萤草基础数据已入库，
    未结附形态空操作）；羁绊 2 鼓舞消耗转化（前期答复 10，consume_assault_boosts）。
    森佑灵矢主牌仍缺：子选项森佑灵引含未实现的 [庇佑] 与牌库抽形态机制。

## 协战牌 id 设计（已决议）

- 主 id 挂在**式神 id 较小者**的版本包块下，后缀 21 起（同对式神多张协战顺延 22、23…）；
  yaml 用 `shikigami`（主）+ `shikigami2`（副）双字段（loader/validate_deck 已支持）。
- 两个子选项实现为 token 衍生子卡：主选项子卡挂主式神块、副选项子卡挂副式神块（序号 51+），
  使用时生成并"视作从手牌使用了所选子选项卡牌"（完整使用流程：鬼火/等级/合法性/目标）。
- 已确定的协战牌 id（2026-07，card_data_raw 更新后）：
  - 森佑灵矢 = 10010121（白狼 100101 < 萤草 100127）；子选项 灵矢贯虹 = 10010151
  - 刃影鹤唳 = 10010621（姑获鸟 100106 < 妖刀姬 100123）；子选项 鹤唳回风 = 10010651、刃影叠岚 = 10012351（已入库）
  - 狂歌豪情 = 10010321（茨木童子 100103 < 酒吞童子 100109）；子选项 地狱豪焰 = 10010351、醉酒当歌 = 10010951（已入库）
  - 风之乐章 = 10012421（妖琴师 100124 < 一目连 100125）；子选项 幻音绝弦 = 10012451、风韵雅乐 = 10012551
  - 致命之羽 = 10012621（以津真天 100126 < 鸩 100128）；子选项 鎏金幻羽 = 10012652、蚀刃毒羽 = 10012851
  - 涅槃明灯 = 10010521（凤凰火 100105 < 青行灯 100112）；子选项 涅槃业火 = 10010551、烛火重燃 = 10011251（主牌与烛火重燃未实现）
- 主牌均须等两位所属式神都已引入才能进 db（loader 校验 shikigami2 存在）；
  姑获鸟（100106）/萤草（100127）基础数据已入库——剩余主牌待子选项机制：
  森佑灵矢（森佑灵引的[庇佑]与牌库抽形态）、涅槃明灯（烛火重燃）。
