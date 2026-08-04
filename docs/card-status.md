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
| 01 起弓 | ✅ | [远程] 攻击后到期强化（attack_buff，无力量部分） |
| 02 离 | ✅ | |
| 03 文射 | ✅ | "将额外先击中目标一次"按 [连击] 实现（先攻+交战两阶段各击中一次，语义等价） |
| 04 残心 | ✅ | keep_attack_buffs |
| 05 援护 | ✅ | |
| 06 会 | ✅ | 所选目标仅己方可见：delay_grant secret，联机状态脱敏抹除对手视角的 chosen |
| 07 觉醒·白狼 | ✅ | 任意伤害（非仅战斗）触发，与原版一致 |
| 08 无我 | ✅ | |
| 21 森佑灵矢 | ✅ | 协战主牌（白狼&萤草，id 10010121）：第十四阶段随[庇佑]与检索直接使用形态机制落地 |
| 51 灵矢贯虹 | ✅ | 协战子选项（白狼侧战斗牌）：三步齐备——法术强化力量再授予（reapply_attack_buff_power：离/无我等 attack_buffs 力量部分合计再授予，仅力量）、羁绊 1 萤草形态进场效果再触发（trigger_form_enter，未结附空操作）、羁绊 2 鼓舞消耗转化（维护者答复(3)） |

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
| 08 尘缚之阵 | ✅ | 开服版仅"战斗区锁定"（combat_lock）；激怒/免疫直接消灭按 raw 移除（引擎机制与合成数据测试保留） |

## 茨木童子（100103）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 永久成长（perm=True，维护者答复(3)） |
| 01 鬼之手 | ✅ | 非追猎：效果步 force_enter_combat（random_pick 不取对象不吃帷幕 + if_combat_empty 空发），拉入者随即成为本场无目标战斗被攻击者 |
| 02 豪拳 | ✅ | 临时 +3 力量（维护者答复(3)） |
| 03 罗生门之鬼 | ✅ | 茨木击杀式神触发 random_enhance：仅手牌实例强化（"仅在手牌时可触发增强"）、每实例 ≤3 次、tiers min/max 档位门控、实例 enhance_got 去重；强化写入 mods：keywords_add/form_power_delta/form_health_delta/playable_when_defeated+revive_on_play |
| 04 黑焰之手 | ✅ | [远程] |
| 05 迁怒 | ✅ | on_shikigami_defeated 新 payload in_combat（无论消灭原因）；准备区串行 damage（暴风之主先例） |
| 06 断臂 | ✅ | {max_power_gap: self} 补峰值差值（ext["max_power"] 历史峰值只增） |
| 07 地狱之手 | ✅ | temp_grants 击杀（按卡面字面不限定敌方）→ followup_attack 追加攻击生命最低者 |
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
| 基础能力 | ✅ | 使用法术→记录该法术并注册一次型[倒计时2]，归零凭空免费复用同名牌（非从手牌、不耗火）；记录随气绝丢失；倒计时来源按 A2 决策 = 式神 id；raw 无"非觉醒"限定，实现仍排除觉醒法术（见出入 18） |
| 01 黑羽之刃 | ✅ | [瞬发] 投射 2 伤 |
| 02 风神一扇 | ✅ | 投射 2 伤 + retreat；受伤者经块内暂存 last_damage_victims 引用 |
| 03 暴风之盾 | ✅ | gain_shield + delay_grant（下己方回合开始再 +2；选择目标随延迟条目存储）；响应挂 on_before_assault（受击方即战斗区式神） |
| 04 暴风之主 | ✅ | 形态 4/6：形态能力读 on_card_played payload affected_refs（该次出牌效果伤害过的敌方式神；只计敌方式神、去重，牌手与己方式神不计） |
| 05 天狗风乱 | ✅ | distribute_damage 6 点随机分配（敌方角色，生命≤0 退出分配） |
| 06 羽刃暴风 | ✅ | 全体敌方式神 3 伤（enemy_shikigami，不含牌手） |
| 07 觉醒·大天狗 | ✅ | +1/+1（awaken_power/awaken_health）；法术觉醒流程——替换继承原能力的动态倒计时（含记录的法术）并变为倒计时 1，countdown_delta -1 在替换后结算（归零即自动复用记录法术） |
| 08 吾即正义 | ✅ | 3 级；增强计数：本局大天狗使用法术 add_mod spell_count，满 10 置 transformed → destroy 全体敌方式神（开服版：无[瞬发]、无生成牌库效果） |

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
| 基础能力 | ✅ | 使用与当前形态不同的形态牌时抽 1：on_form_attached payload form_changed（无当前形态或新旧形态 id 不同） |
| 01 吸取 | ✅ | 使用时主动选择目标（choose any_shikigami）造成 2 伤害（维护者答复(4)，原投射定案作废）+ 鼓舞 2 护甲 |
| 02 治愈之光 | ✅ | [瞬发]；进场与己方回合开始全体己方式神回 2 |
| 03 萤火点点 | ✅ | [瞬发]；使用方式二选一（+1生命/打1）；增强"己方回合开始若萤草有形态此牌效果+1"（triggers 计数 add_mod enhance） |
| 04 勇气之光 | ✅ | [瞬发]；进场与己方回合开始鼓舞 +1 战力 +2 护甲 |
| 05 闪烁 | ✅ | [响应] 敌方式神进入战斗区自动使用；power_override scope=turn（ext power_zero_turn 半回合覆写）；增强 = conditional_keywords combat_nonempty（战斗区有式神得[瞬发]） |
| 06 觉醒·萤草 | ✅ | trigger_form_enter 触发当前形态进场效果；觉醒能力"使用形态牌时触发当前形态进场效果并抽 1" |
| 07 安魂之光 | ✅ | [瞬发]；进场与己方回合开始 +1 鬼火 + 己方牌手回 2 |
| 08 虹彩 | ✅ | [瞬发]；generate 萤草三种形态牌各 1 张入手 |
| 51 森佑灵引 | ✅ | 协战子选项（萤草侧）：search_deck card_type=form + max_level="target"（不高于目标式神等级）+ direct_play_power_ge=4（目标存活且力量≥4改为直接使用——不耗火 play_from=deck），检索命中即洗牌库（维护者答复(5)）；羁绊白狼获得[庇佑] |

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
| 01 凤鸣 | ✅ | [瞬发] 打敌方牌手 3 |
| 02 瑞翔 | ✅ | 所有敌方式神 1（enemy_shikigami，不含牌手） |
| 03 引燃 | ✅ | 可对己方式神（维护者答复）；消灭追加走 delay_grant scope="play" + victim_player 语境目标（敌己两向） |
| 04 焚羽 | ✅ | 非战斗伤害 +1：on_damage_start {source_shikigami: self, kind: effect} boost_damage（含觉醒后其他式神法术触发的投射） |
| 05 凤火 | ✅ | |
| 06 觉醒·凤凰火 | ✅ | 己方式神任意专属法术 → 投射 1（{shikigami_not: null} 排除中立牌；来源=凤凰火，吃焚羽、计炎舞） |
| 07 炎舞 | ✅ | [贯通] 投射 5（步骤显式 piercing:true）；增强按次数不限伤害类型（on_player_damaged persistent 计数，打出装配快照） |
| 08 出云 | ✅ | 形态 5/6：使用法术牌时 [运势4]（luck: 4 判定）→ generate 凤火入手 |
| 21 涅槃明灯 | ❌ | 协战主牌（凤凰火&青行灯，id 10010521；副侧子选项烛火重燃 10011251 未实现） |
| 51 涅槃业火 | ✅ | 协战子选项（凤凰火侧）：spell_echo 法术回响序列（凤鸣→引燃→瑞翔，once_key 不可叠加；敌方式神触发亦可；自动使用凭空/免费/随机合法目标/触发凤凰火能力）+ 羁绊明灯 |

## 山童（100116）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[贯通]：ShikigamiDef.keywords → perm_keywords（永久类别，气绝不清除） |
| 01 鲁莽 | ✅ | 己方回合开始 launch_attack 自动攻击（不耗火/次数；气绝/未在场空操作） |
| 02 怪力 | ✅ | 永久 +1 力量按常规效果步执行（战斗牌流程不再误提取为本次战斗战力） |
| 03 怒吼 | ✅ | 全体己方式神临时 +1 力量（20191212：自身不再永久——raw 未标"永久"按默认临时，questions.md 待确认2） |
| 04 笨拙 | ✅ | 双快照（20191212 形态 6/9 best / 20200120 形态 5/9）；power_override：敌方回合力量覆写为 0（覆写全部加成层），己方回合开始解除 |
| 05 碎岩 | ✅ | +2/+2；20191212 去[穿刺]改伪关键字 pierce_armor——伤害事件批次 0 同穿刺时点处理，仅清零被攻击者正值护甲、不触屏障（terminology「穿刺」条登记） |
| 06 觉醒·山童 | ✅ | +1/+0（20191212 去 +1 生命）；[贯通]（牌面语义显式落地）+ grant_immunity scope=perm kind=effect from_side=enemy；复活重新授予 |
| 07 伺机 | ✅ | 响应挂 on_before_assault {victim_shikigami: 100116}；敌方回合光环 card_aura card_id 自指（"此牌"+2力量，turn=opponent）；counter_piercing 反击贯通 |
| 08 崩山 | ✅ | {perm_power: self} 使用时快照各自加（先战斗区后准备区）；山童的贯通不传导本牌法术伤害（步骤不标 piercing） |

## 姑获鸟（100106）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_after_assault {attacker_shikigami: self} → retreat（攻击后移回准备区；刃影叠岚羁绊联动已验证） |
| 01 伞剑 | ✅ | 力量 +1；手牌触发式光环：on_after_assault {attacker_side: friendly, attacker_not_shikigami: 100106} → card_aura keywords [fast] scope=turn（其他己方式神攻击后本回合此牌瞬发） |
| 02 影翼 | ✅ | 形态 4/4：on_before_assault {attacker_shikigami: self} → buff_power +1（每次攻击前获得 1 力量，临时持续性） |
| 03 丛云鹤舞 | ✅ | [直击]（keywords 授予通道） |
| 04 金鸾 | ✅ | 形态 6/4；手牌触发式瞬发光环同伞剑 |
| 05 偷袭 | ✅ | [响应]挂 on_shikigami_defeated {victim_side: enemy, in_combat: true, summon: false}（in_combat 为气绝事件 payload）；力量 +3；非"（被）攻击时"时机的响应战斗牌不插入当前战斗——按完整战斗流程发起新战斗（嵌套战斗，正常反击；rules.md 第二章备注） |
| 06 天翔鹤斩 | ✅ | 力量 +3；target 扩展键 battle=true + optional=true：有未气绝敌方准备区式神时必须指定（有目标战斗，同追猎管线），否则可不带目标退化为普通战斗；[贯通]（开服版无战斗伤害免疫） |
| 07 慈乌稚子 | ✅ | 形态 8/4：其他己方式神攻击后姑获鸟获得[迅捷]（on_after_assault → grant_keyword haste，一次性消耗） |
| 08 觉醒·姑获鸟 | ✅ | +2/+0；手牌瞬发光环同伞剑；[觉醒][远程]（on_awakened + on_shikigami_revived 双块 grant_keyword，山童先例；开服版无击杀追加攻击） |
| 21 刃影鹤唳 | ✅ | 协战主牌（姑获鸟&妖刀姬）：options [10010651 鹤唳回风, 10012351 刃影叠岚]；构筑池双归属 |
| 51 鹤唳回风 | ✅ | 协战子选项（姑获鸟侧法术觉醒，+1/+1）：[觉醒]强化基础能力——攻击后移回准备区 +1 力量并恢复所有生命（heal {missing_health: self}）；羁绊 launch_attack 妖刀姬（未出战/气绝空操作——刃影叠岚先例） |

## 海坊主（100107）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_heal 过量转化：payload 新增 overheal（治疗量-实际治疗量）；{source_shikigami: self, target_side: friendly, overheal_ge 1} → 目标获得等量护甲。实际恢复 0（满血）不发 on_heal、不触发转化（答复 0） |
| 01 治愈之水 | ✅ | [瞬发]；{base: 3, half_shield_of: self} 动态数值（海坊主护甲 //2，向下取整）；choose any_character 新池 |
| 02 灵能 | ✅ | 形态 3/6：on_heal {source_shikigami: self, target_kind: player} → 自身恢复等量（按实际治疗量） |
| 03 沧海之盾 | ✅ | +2 甲 + delay_grant **bind=chosen**（延迟能力绑定被选式神；scope=turn）：其造成战斗伤害（kind≠effect，含反击）时为牌手恢复 2；[响应]挂 on_before_assault {victim_in_combat: true} 新条件键，choose 自动取事件 victim（古尘之盾先例） |
| 04 水龙卷 | ✅ | {base: 3, shield_of: self} 动态造伤（海坊主当前每 1 点护甲伤害 +1；开服版不再先自 +3 甲） |
| 05 祝福之水 | ✅ | [瞬发]；friendly_character 新池（己方在场式神 + 己方牌手） |
| 06 巨浪 | ✅ | 所有敌方式神 2 伤（enemy_shikigami）；damage 记录块内暂存 last_damage_total（实际造成伤害合计，扣减生命口径，护甲吸收不计）→ heal {memo: last_damage_total} 恢复自身 |
| 07 蹈海 | ✅ | 形态 4/9：on_damage {source_shikigami: self, kind_not: effect} → friendly_others_character 新池（己方其他角色，排除来源含牌手）恢复等量 |
| 08 觉醒·海坊主 | ✅ | +1/+3；觉醒替换 = 过量治疗额外转等量力量+护甲（buff_power 临时修正；开服版无"恢复 3"） |

## 青坊主（100111）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | "你恢复生命时"口径 = 己方任意角色实际恢复（target_side friendly，挂治疗后 on_after_heal——仅实际恢复 > 0 触发）；20191212 去"每回合一次"门控 → random_damage 敌方角色 2×1 |
| 01 佛印 | ✅ | [瞬发]；两条 heal step（self_player / enemy_player） |
| 02 禅心 | ✅ | 形态 1/6：同口径 + turn_mark 门控 → draw 1 |
| 03 佛光 | ✅ | 已按 raw 与 04 互换：R 2 首段 choose any_character 奶 3 → side_of_last_heal 池（上一步治疗目标所属方的所有角色）恢复 3（heal 记录块内暂存 last_heal_targets） |
| 04 慈悲 | ✅ | 已按 raw 与 03 互换（level 2）；grant_keyword unyielding |
| 05 舍生 | ✅ | [瞬发][响应]；destroy 青坊主 + grant_immunity kind=all scope=turn（**牌手级免疫**新通道：PlayerState.immunities，按回合号过期）；响应挂 on_damage_start {victim_lethal: true} 新条件键（面板伤害 ≥ 当前生命，护甲计算前判定） |
| 06 法界唯心 | ✅ | 形态 5/6，tags [heal_reversal]：引擎 heal() 前置检查——控制者对敌方的恢复改为等额伤害（不发出任何治疗事件，伤害事件照常）；20191212 去进场奶 4（只留恢复反转） |
| 07 觉醒·青坊主 | ✅ | +0/+2；恢复 8 目标 = 你的牌手（答复 2）；觉醒替换（原文不含基础）：无门控，恢复时对所有敌人（enemy_character）1 伤 |
| 08 轮回 | ✅ | set_health 新 op（非治疗非伤害，钳制 [1, max_health]）{enhance: true, base: 10}；增强计数 = on_before_assault 最终目标为你的牌手（含反击、无论是否受伤；以式神为目标不计；答复 8）；X=0 按原文仍可使用（变为 10） |

## 青行灯（100112）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_turn_start {player: opponent, orb_ge: 1} → generate 明灯（敌方回合开始时有剩余鬼火） |
| 01 明灯 | ✅ | [瞬发] gain_orb 1；凤凰火/青行灯协战与青行灯基础能力的产物 |
| 02 青灯夜谈 | ✅ | **pending_choice 结算中交互选择**机制（GameState.pending_choice + choose 指令 + _suspended 内存态续点）：deck_top_pick 次数={orb: true}（1+剩余鬼火，0 火仍执行基础 1 次），末次后清空鬼火续块；联机 sanitize 对非选择方抹除 options；text 按 raw 无"洗牌库"，引擎 deck_top_pick 仍每次选择后固定洗牌——洗牌行为差异待确认见 questions.md 待确认8 |
| 03 幽光之火 | ✅ | 形态 4/5：20191212 触发改"对敌方牌手造成战斗伤害时"——on_player_damaged {player: opponent, source_shikigami: self, kind: combat} → generate 明灯 |
| 04 百闻一得 | ✅ | discard card_id 精确弃明灯（无明灯不弃、升级仍执行）；friendly_lowest_level 新池（并列全入池由使用者选择，答复 7）；level_up 新 op 不走升级次数，满 3 级 overflow_draw 改抽 1 |
| 05 百物语之火 | ✅ | 形态 4/5：on_turn_end {player: self} → gain_orb 1 |
| 06 不灭之火 | ✅ | 形态 4/5：on_form_destroyed {target_shikigami: self, orb_ge: 1}（离场前 emit 收集，含被替换/气绝连带，鸩先例）→ consume_orb 1 → revive（气绝先复活）→ reattach_form 新 op（墓地同一实例重新结附，不生成新牌，答复 6） |
| 07 吸魂灯 | ✅ | repeat op（次数={orb: true}，1+剩余鬼火，0 火仍执行基础 1 次）：20191212 投射 5→4 ×鬼火，独立求值，clear_orb 清空 |
| 08 觉醒·青行灯 | ✅ | +1/+1；tags [awaken, orb_store]：觉醒替换 = 基础保留 + 鬼火储存（引擎回合开始不清零、储存累加封顶 4，答复 3） |
| 51 烛火重燃 | ❌ | 协战子选项（青行灯侧幻境）：幻境机制未实现，暂缓 |

## 酒吞童子（100109）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_damage {victim_shikigami: self} → 临时 +1 力量（任意伤害按次，维护者答复(10)）；本体 20191212 身材 2/5（health 6→5） |
| 01 醉里乾坤 | ✅ | [瞬发]；自伤 1（正常触发基础能力）+ draw 1 |
| 02 狂气 | ✅ | 力量 +1；本次战斗获得[不屈]（战斗牌 keywords 授予通道） |
| 03 鬼王 | ✅ | 形态 5/10：进场时对自身 damage 3（触发基础能力）；双快照（20191212 自伤 3 best / 20200120 自伤 4，按环境解析生效） |
| 04 无尽愤怒 | ✅ | id 按 raw 重排（原 05）；力量 +2；triggers on_damage（己方来源自伤，turn_mark 门控本回合一次）→ card_aura power 2 scope=turn（20191212 增强去 +2 护甲，只 +2 力量） |
| 05 神子 | ✅ | id 按 raw 重排（原 06）；形态 6/8：[瞬发]（卡牌级）+[不屈]（结附期间授予） |
| 06 觉醒·酒吞童子 | ✅ | id 按 raw 重排（原 07）；+1/+3；受伤改为获得等量力量（buff_power {event: amount}）；20191212 去[贯通]授予 |
| 07 百鬼夜行 | ✅ | id 按 raw 重排（原 08）；[瞬发]；X = ext["damage_taken_turn"]（本回合所受伤害之和，伤害扣减生命处记账、半回合作用域）；两段 damage：friendly_others（排除自身）+ enemy_shikigami（答复4） |
| 08 狂啸 | ✅ | id 按 raw 重排（原 04）；level 2→3；bump_ext min_health_turn：本回合生命不会降到 1 以下（扣减生命处钳制，半回合作用域回合开始清除）；[响应]挂 on_damage_start {victim_shikigami: 100109, victim_side: friendly} 覆盖块 |
| 51 醉酒当歌 | ✅ | 协战子选项（酒吞侧战斗牌，保持 20251212 未回退）：[不屈]；自伤 3 → gain_shield 3 标 no_extract（不提取为战斗牌护甲前置结算——否则被自己的自伤消耗；按步骤顺序自伤后获得）；羁绊 generate 茨木当前等级战斗牌（level="shikigami" 精确匹配，未出战/未在场空操作） |

## 犬神（100115）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_upgrade {target_shikigami: self} → generate（指令升级与 level_up op 两来源均触发——on_upgrade payload 新增 target Ref，level_up 补 emit）；双快照：20191212 生成'羁绊的价值' best / 20200120 生成'心身炼磨' |
| 01 羁绊的价值 | ✅ | 双快照：20191212 永久 +1/+1（tags [lianmo] 出牌记账 lianmo_used_game）best / 20200120 heal {missing_health: self} 恢复所有生命（姑获鸟觉醒先例，无 tag） |
| 02 心斩 | ✅ | 战斗 +0/+2 |
| 03 心即归处 | ✅ | revive self（20191212 去[瞬发]）；playable_when_defeated + only_when_defeated 字段（第十三阶段）："仅在犬神气绝时可用"硬门控——存活时主动使用报错、响应收集直接跳过 |
| 04 恶·即·斩 | ✅ | 战斗 +4/+0 |
| 05 守护 | ✅ | id 按 raw 重排（原 06）；战斗 +0/+4；[响应]挂 on_before_assault {victim_side: friendly, victim_kind: shikigami, victim_not_shikigami: 100115, attacker_side: enemy}：响应插入把犬神移入防守方战斗区、无目标战斗重读目标 = "攻击目标改为犬神"（零新引擎代码）；追猎类定向战斗可响应——守护者照常移入并获得 +0/+4，但目标不转移仍打原定目标（第十三阶段定案）；text 按 raw 无"转移攻击目标"字样（见出入 20） |
| 06 心剑乱舞 | ✅ | id 按 raw 重排（原 07）；形态 4/9：card_aura scope=form keywords [fast]（犬神的牌获得[瞬发]，读取时求值） |
| 07 心技一体 | ✅ | id 按 raw 重排（原 05）；level 2 形态 3/5 → level 3 形态 4/9；card_aura scope=form + power_ext/shield_ext（ext 数值通道，读 lianmo_used_game）；双快照：20191212 记账卡='羁绊的价值' best / 20200120 记账卡='心身炼磨'（均 tags [lianmo] 出牌记账）；手牌数值显示已含光环 ext 通道（第十三阶段，刃影叠岚同解） |
| 08 觉醒·犬神 | ✅ | +0/+0（20191212 去 +1/+1）；on_turn_end {player: self, holder_defeated: true} + trigger_when_defeated 字段（能力收集对气绝者放行——仅气绝时触发）：revive + perm +1/+1；raw 无气绝限定，机制保持仅气绝时触发（见出入 19） |
| 51 心身炼磨 | ✅ | 衍生（20200120 起升级产物）：perm +1/+1；tags [lianmo] 保留；重写为 20200120 唯一版本——去 20251212 的动态瞬发（conditional_keywords {level_ge: 2}）与免费（cost_zero_if {level_ge: 3}） |

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

## 判官（100110）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_shikigami_defeated {victim_kind: shikigami, source_shikigami: self}（判官消灭式神）→ 打敌方牌手 1 + 己方牌手回 1；本体双快照（20191212 3/4 best / 20200120 2/4） |
| 01 墨笔夺魂 | ✅ | buff_health 负值通道：上限下调同步钳当前生命，上限 ≤0 走气绝（第十四阶段定案） |
| 02 勾诀 | ✅ | TargetSpec 过滤键 power_le（spec_pool_refs 统一校验/展示） |
| 03 生死无常 | ✅ | [响应] 挂"己方战斗区式神被攻击时"；两连 destroy（任一侧战斗区为空该步空操作）；text 按 raw 对齐 |
| 04 无情 | ✅ | 形态：countdown_delta revive=True——敌方式神气绝倒计时 +1 |
| 05 觉醒·判官 | ✅ | +1/+1；20191212 为纯觉醒替换（去 -2力量/-1生命效果步与 target）；觉醒能力"当你消灭一个式神时"= {source_side: friendly}（己方任一式神消灭即触发，不限判官本人） |
| 06 夺命 | ✅ | [必杀]（20191212 去[穿刺]）；增强：triggers 消灭计数 kill_count ≥13 → persistent transformed；变后 = temp_grants（绑本次战斗）on_damage/on_player_damaged {source_shikigami: self, kind: combat, card_transformed: 10011006} → destroy victim / damaged_player（destroy 支持牌手目标：消灭牌手 = 直接获胜，第十四阶段定案） |
| 07 死之宣告 | ✅ | destroy 任选式神（含己方） |
| 08 断罪 | ✅ | 形态增强：triggers 消灭计数 → form_power_delta（_materialize 生成点统一快照，_mat 记账防重复合并） |

## 清姬（100114）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 伪关键字 damage_to_fragile 永久通道（ShikigamiDef.keywords → perm_keywords，死亡不清）：伤害事件生成点对无破甲受伤者全额转化为等量破甲（不再视为伤害；与毒蚀同位置，converted 防循环） |
| 01 蛇行击 | ✅ | [瞬发][弹回]——弹回首卡（_rebound_check：结算完毕牌在墓地移回手牌；_mat 快照去重防修饰重复合并）；暂保持 20251212 未回退——20191212 增强"破甲则回手+1伤"缺 chosen_has_fragile 与条件回手机制，见 questions.md 待确认6 |
| 02 淬毒 | ✅ | 所有敌方角色 2（经伤害转化：无破甲者转为 2 破甲） |
| 03 剧毒之盾 | ✅ | 2 护甲 + delay_grant scope=turn bind=chosen（"本回合获得'使受到它战斗伤害的式神获得3破甲'"）；[响应] 挂"己方战斗区式神被攻击时"自动对其使用 |
| 04 氤氲蛇姬 | ✅ | 20191212 重写：形态 4/6，敌方回合结束时敌方战斗区式神 +2 破甲（on_turn_end {player: opponent} → gain_shield kind=fragile enemy_combat） |
| 05 无名之毒 | ✅ | [瞬发][投射] 4 |
| 06 焚身之火 | ✅ | 先给目标 2 破甲，再对所有有破甲的敌方角色打 3（TargetSpec 过滤键 has_fragile；含牌手） |
| 07 觉醒·清姬 | ✅ | 20191212：+3/+3→+2/+2、去进场全体 1 破甲（只留觉醒替换）；觉醒能力 = 伤害转化沿用 + keep_enemy_fragile tags（敌方角色的破甲不在回合开始清除，护甲照常） |
| 08 火吻之蛇 | ✅ | stat_aura enemy_fragile_power 动态光环（敌方有破甲式神降等量力量）+ 敌方回合开始全体敌方角色 1 破甲（回合开始破甲清除先于 on_turn_start，敌方破甲每半回合重置为 -1——维护者答复(8)确认）；20191212 去"攻击时获得[先攻]"块 |

## 书翁（100118）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 游戏开始时抽 1（rules.md 游戏开始阶段步骤 3 已载） |
| 01 纪行 | ✅ | [迅捷]；书翁对敌方牌手造成伤害时抽 1（on_player_damaged {source_shikigami: self}） |
| 02 云游 | ✅ | [瞬发]；战中调度 mulligan_hand times=3（pending_choice kind=mulligan_pick 挂起 + choose 作答，结束后洗牌库——rules.md ch21） |
| 03 开卷 | ✅ | 抽 2 |
| 04 墨染 | ✅ | 抽 1 + 打 {hand_count_half: controller}（手牌数一半向下取整） |
| 05 明心 | ✅ | draw_to_pick tags 抽牌替换：回合开始抽 1 改为检视牌库顶 3 张选 1 入手再洗牌（不足 3 张全检视，空库走判负/燃烧分支） |
| 06 闻世 | ✅ | stat_aura self_hand_count 动态光环：每有一张其他手牌 +1/+1（_refresh_stat_auras 读取点重算，dyn_power/dyn_health 缓存通道） |
| 07 万象之书 | ✅ | [瞬发]；generate shikigami=friendly_others——按座次顺序逐个其他己方式神（含 0 级/气绝）各随机 1 张可构筑牌（非衍生，与本局卡组无关；维护者答复(6)确认）入手 |
| 08 觉醒·书翁 | ✅ | deck_out_burn tags 空库燃烧：空库抽牌改为对敌方牌手打 10、自己不判负（每张空抽各触发一次） |

## 青蛙瓷器（100113）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_luck_success（判定者=己方）→ 记 luck_success_turn=当前回合号；光环：判定成功过的回合在场的青蛙瓷器 +2 力量（引擎读取，不叠加、不分敌我回合） |
| 01 出千 | ✅ | 战斗 +0/+1；luck_roll{x:4, then:[generate 出千置手]} |
| 02 岭上开花 | ✅ | 形态 2/7；on_luck_success → buff_power 1（一次性临时持久增益） |
| 03 九莲宝灯 | ✅ | 形态 3/3；增强 = 进场按 dice_history 去重数 +N/+N |
| 04 立直 | ✅ | 战斗 +0/+0；luck_roll force_x1_if（有形态阈值视为 1，骰子照投照计）→ grant_immunity；[响应] 青蛙瓷器被攻击时自动使用 |
| 05 骰子炸弹 | ✅ | 已按 raw 与 06 互换（level 2）；20191212 去[瞬发]；luck_roll{x:1} → damage amount_ctx:luck_dice（造成等同骰点的伤害） |
| 06 门前清 | ✅ | 已按 raw 与 05 互换；形态 2/9；被攻击时（on_before_assault {victim_shikigami: self}）EffectBlock.luck:4 → gain_shield 2（20191212 只留被攻击挂点，去出击触发） |
| 07 转运 | ✅ | 攻击后 luck_roll{x:4} → discard_random 2 + reuse_card（战斗流程重走，不耗火） |
| 08 觉醒·青蛙瓷器 | ✅ | +2/+2；觉醒能力 = 基础同款 + 翻倍标记（判定者方未气绝觉醒青蛙：成功效果执行两次，不重新掷骰；on_luck_success 延时触发同样翻倍、自身光环不翻倍、失败效果不翻倍） |

## 山兔（100117）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 己方回合开始 luck:6 → countdown_power_boost{countdown:-1, power:1, friendly_others}（气绝者只减复活倒计时、归零复活者不追加力量；存活者含无倒计时能力的 +1 力量） |
| 01 谁还不听话 | ✅ | [瞬发][投射2]；增强 = damage amount_ext:dice_six_count（每次投出 6 伤害+1） |
| 02 送祝福 | ✅ | buff 1/1 + 抽 1；增强{dice_six_ge:3}→ 合并一次性 +3/+3+[迅捷] |
| 03 快来保护我 | ✅ | 形态 6/6；增强{dice_six_ge:3}→ 获得[不屈] |
| 04 觉醒·山兔 | ✅ | +1/+1；己方回合开始两次独立 luck:6 → countdown_power_boost{power:2}（两个独立 block） |
| 05 这把算我赢 | ✅ | [瞬发]；set_dice_modifier{mode:six_once}；增强{dice_six_ge:10}→ alt_effects 变后：失去[瞬发] + win_game（吾即正义先例） |
| 06 戏谑套索 | ✅ | transform{into:10011799 纸人, 敌方战斗区式神}+抽 1；增强{dice_six_ge:3}→ into:10011798 小纸人；[响应] 山兔被攻击时自动使用 |
| 07 来打我呀 | ✅ | launch_attack shikigami="target"（使一敌方式神立刻攻击）；增强 = 本回合该式神 -dice_six_count 力量（amount_ext + amount_sign:-1） |
| 08 萌即正义 | ✅ | 形态 6/6；进场/离场 set_dice_modifier{mode:six}（判定者级必 6 光环，dice_force_six + dice_force_six_holder）；增强 = 进场按 dice_six_count +N/+N |
| 21 福星高照 | ✅ | 协战主牌（山兔&座敷童子，id 10011721）：options [10011751 幸运兔兔, 10012951 鸿运当头] |
| 51 幸运兔兔 | ✅ | 协战子选项（山兔侧[瞬发]）：增强{dice_six_ge:3}→ cost_delta_player{opponent, +1, next_turn}（[不消耗鬼火]/首张[瞬发]仍免费、非手牌使用不受影响）；羁绊（座敷在场，{shikigami_active:100129}）：luck_roll{x:4} → power_override scope=turn 敌方全式神 |
| 99 纸人 | ✅ | 变形物 3/3（kind=transform）；己方回合结束 untransform self |
| 98 小纸人 | ✅ | 变形物 0/1（kind=transform）；同上 |

变形机制已知缺口（rules.md 第十七章末同载）：①战斗事件中变形不继承交战方——无战斗中止钩子，未实现；②觉醒牌使用事件中变形仅部分实现——快照记 `awakened`，"觉醒替换对原式神生效"的完整管线未落地。

## 座敷童子（100129）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_luck_judge（即时；判定者=己方且骰=1）→ luck_reroll（同一判定每个来源能力至多一次，重投同样吃必 6 修饰） |
| 01 金运大吉 | ✅ | 形态 3/6；进场和己方回合开始 luck_roll{x:4, judge:both, then:[抽1]}（双方各生成事件、当前回合玩家先、判定者各自抽） |
| 02 五谷丰壤 | ✅ | 形态 2/7；同上 then:[恢复 3 生命] |
| 03 福寿双全 | ✅ | 形态 4/5；增强{shikigami_has_form:100129}→[瞬发]+使用时抽 1；进场或仅替换离场时双方各 +1 鬼火（气绝消灭不触发） |
| 04 家内安全 | ✅ | 形态 3/7；式神攻击后 luck:{x:4, on:fail} → stun{攻击者} |
| 05 福运昌隆 | ✅ | 抽 1；luck_roll{x:4} → 获得 2 鬼火 |
| 06 觉醒·座敷童子 | ✅ | +1/+3；on_luck_judge（判定者=己方且将失败，{dice_below_x: true}）→ luck_reroll |
| 07 和气满满 | ✅ | 形态 0/7；式神攻击时 luck:{x:4, on:fail} → 攻击者本次战斗力量变 0（power_override 战斗作用域） |
| 08 福满乾坤 | ✅ | [条件] play_condition{luck_success_total_ge:12}（不满足任何方式不能用）；依次双方生命变 30（set_health 非治疗）→ 双方抽至 10 张（draw hand_to/side）→ 双方各 +3 鬼火（gain_orb side） |
| 51 鸿运当头 | ✅ | 协战子选项（座敷侧）：luck_roll{x:4, then:[复活己方全部式神]} → random_play_form{friendly 在场}（各随机使用 1 张等级 ≤ 当前等级的专属形态牌，无池/气绝跳过）；羁绊（山兔在场，{shikigami_active:100117}）：search_deck card_id 检索'这把算我赢'置手 |

## 妖狐（100130）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 妖狐使用法术牌时 luck:4 → random_damage{2 + amount_ext:yaohu_dmg_bonus(amount_ext_source:shikigami), enemy_character}；伤害流程按来源=妖狐每次伤害事件记 yaohu_damage_count +1 |
| 01 风刃 | ✅ | [瞬发]；对一敌方角色造成 2 伤害 |
| 02 聚气 | ✅ | [瞬发]；bump_ext{yaohu_dmg_bonus, self} + 抽 1（永久含基础与觉醒能力，跨气绝保留） |
| 03 爱意绵绵 | ✅ | 形态 4/5；card_aura 手牌光环——手牌中妖狐法术牌伤害效果 +1（damage_boost 通道；第十六阶段落地——此前 spell_damage 通道引擎未实现的存量 bug 修复，参数名统一为 damage_boost） |
| 04 命运之人 | ✅ | 形态 4/6；己方回合开始 generate '风刃' 置手 |
| 05 无羁风弹 | ✅ | repeat_random_damage{2, all_other_shikigami, max:10, stop_on_defeat}（逐次插入结算，任一式神气绝即停） |
| 06 叠风斩 | ✅ | 对一式神造成 2 伤害 → reuse_card（同目标，恰好两次；触发两次妖狐能力） |
| 07 狂风刃卷 | ✅ | random_damage{2, enemy_character, sequential:true, count:5}（逐次独立随机、有放回）；增强{yaohu_damage_count>=20}→ count:10（{字段_ge} 事件无该字段时回退读控制者 ext——第十六阶段修复恒不触发的存量 bug） |
| 08 觉醒·妖狐 | ✅ | +2/+2；觉醒能力两段：你使用法术牌（含中立法术牌）或运势判定成功时随机打一敌方角色 2（吃 yaohu_dmg_bonus；可因觉醒青蛙瓷器翻倍） |

## 跳跳弟弟（100120）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 受到伤害时获得等量破甲（on_damage {victim_shikigami: self} → {event: amount}） |
| 01 腐坏直拳 | ✅ | transfer_fragile 新 op：自己破甲清零、等量转移到被攻击的式神（"确定攻击目标后转移"以战斗牌效果步时序表达） |
| 02 瘴疠体质 | ✅ | 形态 3/9：对其造成战斗伤害的式神获得 3 破甲 |
| 03 毒气喷泉 | ✅ | transfer_fragile 敌方全体（每名全量）；增强 = 己方回合开始战斗区有式神则此牌得[瞬发] |
| 04 肿胀体质 | ✅ | 形态 4/16：keep_fragile 新 op——式神级破甲保留（形态结附期间破甲不在己方回合开始清除，形态离场解除；keep_shield 对称机制） |
| 05 觉醒·跳跳弟弟 | ✅ | +1/+3；受伤获得等量破甲并永久 +1 生命 |
| 06 甜蜜的负担 | ✅ | [瞬发][响应]"当你被敌方攻击时自动使用并将攻击目标改为跳跳弟弟"：目标转移按守护先例——响应插入移入战斗区，无目标战斗重读战斗区驻留者（零新引擎代码） |
| 07 尸毒体质 | ✅ | 形态 5/15：分段门槛（>=5 敌方式神 3 破甲 / >=10 敌方牌手 10 破甲） |
| 08 僵硬扑击 | ✅ | [瞬发][贯通]；{"fragile_of": self} 新动态数值——获得等同于自己破甲的力量 |
| 21 跳跳兄弟 | ❌ | 协战主牌（跳跳弟弟&跳跳哥哥，id 10012021）：跳跳哥哥未加入，暂缓 |
| 51 尸瘴 | ❌ | 协战子选项（跳跳弟弟侧幻境）：幻境机制未实现，暂缓 |

## 雪女（100121）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_stun 新事件（即时时机，stun 施加点发出）+ turn_mark 每回合一次 → '雪球'置手 |
| 01 寒冰之盾 | ✅ | [响应] 挂"己方战斗区式神被攻击时"自动对其使用（剧毒之盾先例） |
| 02 吹雪 | ✅ | 打 3 + '雪球'置手 |
| 03 冰墙 | ✅ | 召唤'冰墙'：no_attack 新字段（不能发动攻击——出击校验拦截、launch_attack 空操作） |
| 04 崩雪 | ✅ | 消灭一个[眩晕]的式神或[眩晕]一个未[眩晕]的式神（TargetSpec 新过滤键 stunned） |
| 05 冰风暴 | ✅ | 形态 3/5：敌方式神攻击后打其 1 再[眩晕]受伤者 |
| 06 寒冬之心 | ✅ | '雪球'×2 置手 + card_aura 新通道：tag 谓词（仅命中 tags 含 snowball 的牌）+ damage_boost（卡牌效果伤害 +1）+ scope="game"（本局有效不清除） |
| 07 觉醒·雪女 | ✅ | +2/+1；[眩晕]受到雪女伤害的式神（{字段_stunned} 体系配套） |
| 08 流霰 | ✅ | auto_use 新 op（inherit_target 目标继承）+ repeat count {"ext": snowball_used_game, "base": 1}——'雪球'（tags snowball）从手牌使用记账新 ext |
| 21 冰霜永冻 | ✅ | 协战主牌（雪女&雪童子，id 10012121）：雪女侧子选项 冰封 已入库；雪童子侧 雪刃 待幻境机制 |
| 51 雪球 | ✅ | 衍生 token 法术[瞬发]；tags [snowball]（出牌记账与寒冬之心 tag 谓词共用） |
| 52 冰封 | ✅ | 协战子选项（雪女侧）：[眩晕]+获得'雪球'；[羁绊] launch_attack at="chosen" 定向攻击（雪童子对其发动一次攻击） |
| 99 冰墙 | ✅ | 召唤物 0/4（kind=summon，no_attack）；[眩晕]对其造成战斗伤害的式神 |

## 雪童子（100122）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | combat_opponent_stunned 新条件算子（交战对方眩晕，双向判定）→ 不受战斗伤害 |
| 01 霜舞 | ✅ | 场上有[眩晕]敌方角色时此牌得[瞬发] |
| 02 霜风 | ✅ | 敌方战斗区无式神则[眩晕]敌方牌手 |
| 03 雪走 | ✅ | [眩晕]战斗区敌方式神；[响应] 雪童子被攻击时自动使用 |
| 04 雪国之子 | ✅ | 形态 5/5：场上有[眩晕]敌方角色时 +2/+2 |
| 05 胧月雪华斩 | ✅ | 造成伤害时对所有其他[眩晕]的敌方角色造成等量伤害 |
| 06 霜天之织 | ✅ | 增强：场上每有一个[眩晕]的敌方角色 +1 力量 |
| 07 雪融之时 | ✅ | 形态 5/7：每次至多受到 3 点伤害；增强按本局敌方角色被[眩晕]次数 +力量 |
| 08 觉醒·雪童子 | ✅ | +1/+2；grant_keyword scope="battle" 战斗作用域授予——与[眩晕]的敌方角色交战时获得[连击]且免疫战斗伤害 |
| 51 雪刃 | ❌ | 协战子选项（雪童子侧幻境）：幻境机制未实现，暂缓 |

## 跳跳妹妹（100131）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天伪关键字 extra_orb_cost（ShikigamiDef.keywords → perm_keywords）：出击/使用其战斗牌额外 +1 鬼火；[迅捷]/[瞬发]/[不消耗鬼火]时全免（定案(11)） |
| 01 坏人走开 | ✅ | [贯通] |
| 02 去咬他！ | ✅ | 召唤'番茄'并使其攻击（launch_attack） |
| 03 坐下！ | ✅ | stat_aura 新 kind="ids_power"：'番茄'永久 +1 力量（scope="game" 结附牌手、跨召唤保留，对召唤物 10013199 与变形物 10013198 同生效，可叠加） |
| 04 生气了啦！ | ✅ | [连击] |
| 05 别过来啊！ | ✅ | [瞬发] 召唤'番茄'；[响应] 跳跳妹妹被攻击时自动使用 |
| 06 出击！ | ✅ | '番茄'永久得"攻击造成伤害时随机对另一个敌方角色造成 3 点伤害"（可叠加） |
| 07 不玩了啦！ | ✅ | 气绝时可用战斗牌（定案(14)）：气绝中不获得战力/护甲——先结算卡面效果（复活跳跳妹妹），结算完未气绝则补齐战力/护甲并正常发起战斗，仍未气绝则牌入墓地不发起战斗 |
| 08 觉醒·番茄 | ✅ | +3/+3；随机 2 张跳跳妹妹战斗牌置手；永久变形 transform permanent=True（untransform 跳过、气绝前2 不还原）+ owner_combat 变形物用牌白名单（番茄可用跳跳妹妹的战斗牌）；replace_cards/gen_replace——她的非战斗牌随机替换成战斗牌 |
| 99 番茄 | ✅ | 召唤物 3/4（kind=summon；keep_buffs 同名再召保留永久增益——坐下/出击光环跨召唤生效） |
| 98 番茄 | ✅ | 变形物 3/4（kind=transform；觉醒·番茄的永久变形产物） |

## 觉（100108）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 己方回合开始随机展示一张敌方手牌（reveal mode=random；已全部展示则无效果） |
| 01 读心 | ✅ | [瞬发] 展示被选敌方式神在敌方手牌中的所有专属牌（reveal mode=shikigami + shikigami=chosen；协战牌归属按 _card_belongs_to 统一口径） |
| 02 棒球炸弹 | ✅ | 20191212 基础伤害 3→2（{base:2, per:2}）：2 伤 + 2×被选式神已展示专属牌数（动态数值 enemy_revealed_count: shikigami_of_chosen，per 倍率） |
| 03 模仿 | ✅ | 战斗牌[增强]：敌方每有一张已展示法术牌 +1 护甲、每有一张已展示其他牌 +1 力量（enemy_revealed_count: spell/other） |
| 04 强索 | ✅ | [瞬发] 调度敌方已展示的手牌 + 抽 1（mulligan_hand target_side=opponent + only_revealed + auto：按 hand_seq 前 3 张自动调度）；20191212 text 无"并洗牌库"——shuffle:false 不洗牌（调度是否隐含洗牌待确认，见 questions.md 待确认7） |
| 05 灵视 | ✅ | 形态 5/5；敌方牌手使用已展示的手牌时对他造成 2 伤（on_card_played 载荷 card_revealed 条件）；20191212 去[吸血]、改"你恢复 2 点生命"（heal 2 self_player） |
| 06 记仇 | ✅ | 消灭一个本回合造成过伤害的敌方式神（TargetSpec 过滤键 dealt_damage_turn——伤害结算点记账、回合开始清除）；[响应] 受到敌方式神伤害时自动对伤害来源使用（response 覆盖块 + context source）；暂保持 20251212 未回退——20191212"反弹敌方法术"机制未实现，见 questions.md 待确认5 |
| 07 心灵迷宫 | ✅ | 形态 5/5；敌方使用已展示的手牌额外耗 1 鬼火（cost_delta_player side=opponent + card_flag=revealed + scope=form——形态结附期间持续、离场移除；仍在 cost>0 门内，[瞬发]/[不消耗鬼火]全免）；增强：敌方手牌全部已展示时得[瞬发]（conditional_keywords 算子 enemy_hand_all_revealed） |
| 08 觉醒·觉 | ✅ | +1/+1；展示敌方所有手牌（reveal mode=all 补存量）；觉醒被动①：每当一张牌进入敌方手牌时将其展示（入手统一钩子 on_card_enter_hand + reveal mode=event）；被动②：敌方牌手使用已展示的手牌时觉 +1/+1 |

（**经典包 01_jingdian 31 位式神至此完结**——不含未加入的协战对象：跳跳哥哥/樱花妖等；其协战牌主牌/子选项随之暂缓，见文末协战牌 id 设计。）

## 与原版描述的出入（已决议，2026-07）

1. **妖刀姬基础/觉醒能力**：按原版"对敌方牌手造成**伤害**时"（任意伤害）实现。
2. **尘缚之阵**："无法被其他式神替换"是对原版定义不清晰的细化，按已确认的自定义"战斗区锁定"保留。2026-08 起按开服 raw 数据移除激怒与"免疫直接消灭"（引擎机制与合成数据测试保留，后续版本若回归可直接启用）。
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
    效果的力量加成"实现为 reapply_attack_buff_power（离/无我等 attack_buffs 挂账
    力量部分合计，作为攻击后到期强化再次授予；按原文只取力量，关键字不重复）；羁绊 1
    "攻击前触发萤草当前形态进场效果"实现为 trigger_form_enter（萤草基础数据已入库，
    未结附形态空操作）；羁绊 2 鼓舞消耗转化（前期答复 10，consume_assault_boosts）。
    森佑灵矢主牌已于第十四阶段齐备（森佑灵引的[庇佑]与牌库检索直接使用形态均已实现）。

11. **爆牌统一路径**：手牌上限检查落在 move_card——抽牌、生成置入手牌、调度换牌等所有
    进手路径共用同一爆牌流程（超出 hand_cap 的牌转而置入墓地）——第十四阶段定案。
12. **夺命变后与墨笔夺魂**：destroy 支持牌手目标（消灭牌手 = 直接获胜，走牌手气绝判负
    流程）；buff_health 负值下调上限时同步钳当前生命，上限 ≤0 走气绝——第十四阶段定案。
13. **吸取**：raw"造成2点伤害"无目标限定词，按维护者答复(4)为使用时主动选择目标
    （任意式神）；此前的投射定案作废。
14. **森佑灵引**：检索命中即洗牌库（维护者答复(5)：牌库检索类效果命中都需要洗牌库，
    raw 此处为省略）；search_deck 的 shuffle 参数随之删除。
15. **万象之书**："其他己方式神"按出战队列座次顺序全体（含 0 级/气绝），各随机 1 张
    可构筑牌（非衍生、均等概率、与本局出战卡组无关），同时置入手牌、超出爆牌
    （维护者答复(6)，与实现一致）。
16. **庇佑**：仅抵消敌方造成的**法术伤害**（法术牌效果伤害；非战斗伤害 ≠ 法术伤害——
    白狼基础能力、觉醒·入阵歌等式神能力伤害不抵消），判定时机为伤害事件护甲计算后、
    扣减生命前（维护者答复(7)）；伤害事件新增 `spell` 分类标记。
17. **火吻之蛇**：回合开始破甲清除早于"敌方回合开始时"触发，结算后敌方全体 1 破甲
    （维护者答复(8)确认，与实现一致）。
18. **大天狗基础/觉醒能力**：20191212 raw 为"使用法术后"（无"非觉醒"限定），实现仍排除
    觉醒法术（condition `subtype: null`）——避免觉醒牌被倒计时重放刷身材的退化循环
    （维护者确认）；text 按 raw 逐字，机制出入记于此。
19. **觉醒·犬神**：raw"己方回合结束时，复活犬神并永久获得1力量和1生命"无气绝限定，
    机制保持仅气绝时触发（on_turn_end {holder_defeated: true} + trigger_when_defeated
    门控，前期定案）；text 按 raw 逐字，机制出入记于此。
20. **守护**：raw 无"敌方/转移攻击目标"字样（仅"当你其他式神被攻击时，自动使用此牌"），
    机制保持——响应挂 {attacker_side: enemy}，响应插入移入战斗区、无目标战斗重读目标；
    追猎/直击类有目标战斗中可响应（付火/+0/+4/移入照常）但不转移攻击目标
    （第十三阶段定案）；text 按 raw 逐字。

## 协战牌 id 设计（已决议）

- 主 id 挂在**式神 id 较小者**的版本包块下，后缀 21 起（同对式神多张协战顺延 22、23…）；
  yaml 用 `shikigami`（主）+ `shikigami2`（副）双字段（loader/validate_deck 已支持）。
- 两个子选项实现为 token 衍生子卡：主选项子卡挂主式神块、副选项子卡挂副式神块（序号 51+），
  使用时生成并"视作从手牌使用了所选子选项卡牌"（完整使用流程：鬼火/等级/合法性/目标）。
- 已确定的协战牌 id（2026-07，card_data_raw 更新后）：
  - 森佑灵矢 = 10010121（白狼 100101 < 萤草 100127）；子选项 灵矢贯虹 = 10010151、森佑灵引 = 10012751（已入库）
  - 刃影鹤唳 = 10010621（姑获鸟 100106 < 妖刀姬 100123）；子选项 鹤唳回风 = 10010651、刃影叠岚 = 10012351（已入库）
  - 狂歌豪情 = 10010321（茨木童子 100103 < 酒吞童子 100109）；子选项 地狱豪焰 = 10010351、醉酒当歌 = 10010951（已入库）
  - 风之乐章 = 10012421（妖琴师 100124 < 一目连 100125）；子选项 幻音绝弦 = 10012451、风韵雅乐 = 10012551
  - 致命之羽 = 10012621（以津真天 100126 < 鸩 100128）；子选项 鎏金幻羽 = 10012652、蚀刃毒羽 = 10012851
  - 涅槃明灯 = 10010521（凤凰火 100105 < 青行灯 100112）；子选项 涅槃业火 = 10010551、烛火重燃 = 10011251（主牌与烛火重燃未实现）
  - 福星高照 = 10011721（山兔 100117 < 座敷童子 100129）；子选项 幸运兔兔 = 10011751、鸿运当头 = 10012951（已入库）
  - 冰霜永冻 = 10012121（雪女 100121 < 雪童子 100122）；子选项 冰封 = 10012152（已入库）、雪刃 = 10012251（幻境未实现，暂缓）
  - 跳跳兄弟 = 10012021（跳跳弟弟 100120 < 跳跳哥哥）；跳跳哥哥未加入——主牌与子选项 尸瘴 = 10012051（幻境）均暂缓
- 主牌均须等两位所属式神都已引入才能进 db（loader 校验 shikigami2 存在）；
  剩余主牌待子选项机制：涅槃明灯（烛火重燃）、冰霜永冻（雪刃）、跳跳兄弟（跳跳哥哥未加入）；森佑灵矢已于第十四阶段齐备。
