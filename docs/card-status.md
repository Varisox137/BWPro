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
| 21 森佑灵矢 | ✅ | 协战主牌（白狼&萤草，id 10010121）：随[庇佑]与检索直接使用形态机制落地 |
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
| 基础能力 | ✅ | 20191212 接入：按原版"对敌方牌手造成伤害时"（任意伤害） |
| 01 不祥之刃 | ✅ | 20191212 改"对敌方牌手造成伤害时抽 1"（temp_grants on_player_damaged + source_shikigami，不限伤害类别） |
| 02 见切 | ✅ | |
| 03 战意 | ✅ | |
| 04 一闪 | ✅ | cost 0 |
| 05 禁锢之刀 | ✅ | 双版本：20191212 +1/+2（best）/ 20200120 +0/+2；按原版：妖刀姬消灭任意式神均计数（含消灭己方式神）；镜像对局不计敌方同名的击杀；实现通道 = 击杀账本动态数值（`{kill_count: {shikigami}, per: 2}`，打出装配快照——评审⑩迁移，triggers 自计数已删） |
| 06 妖刀万华 | ✅ | text 按 raw"战斗时额外先击中对手一次"=[连击]（同机制） |
| 07 杀念 | ✅ | |
| 08 觉醒·妖刀姬 | ✅ | 按原版"造成伤害时"（任意伤害）；[迅捷] 为一次性 |
| 51 刃影叠岚 | ✅ | 协战子选项（妖刀姬侧法术觉醒）：card_aura 数值通道（fast + power 1/shield 1，可叠加）+ 羁绊 launch_attack 姑获鸟（联动其攻击后退回）；主牌 10010621 刃影鹤唳 ✅（姑获鸟全卡已入库）；raw 标"未加入"，保持 20251212 快照 |

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
| 08 吾即正义 | ✅ | 双快照：20191212（best）3 级 / 20200423 SR 1 级；增强计数：本局大天狗使用法术 add_mod spell_count，满 10 置 transformed → destroy 全体敌方式神（开服版：无[瞬发]、无生成牌库效果）；20200423 基础效果 = generate 随机获得一张不大于自身等级的其他法术牌（max_level=source + exclude_self 新参数） |

## 妖琴师（100124）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20191212：静态倒计时块（initial 3，治疗=两步：friendly_shikigami + self_player）+ "使用觉醒法术牌时倒计时-3"挂 on_before_awaken（能力替换前对旧倒计时生效，归零先结算旧效果再替换；觉醒替换后由觉醒能力块的同名块接续） |
| 01 觉醒·入阵歌 | ✅ | 20191212：觉醒倒计时 distribute_damage 4（enemy_character）；牌面-3 挂 on_before_awaken |
| 02 惊弦 | ✅ | choose any_shikigami 的 countdown_delta -2（可点任意式神；无倒计时修正 -0） |
| 03 大合奏 | ✅ | 20191212：无[瞬发]；replay_countdown(skip_forms)：按 countdown_history 首次出现顺序重放妖琴师生效过的基础/觉醒倒计时块（维护者答复(8)：形态来源不计入；_countdown_block_for 按来源 id 找回块） |
| 04 魔音扰心 | ✅ | 主动=delay_grant(scope=turn) 登记一次性无效化；响应=response 覆盖块直接无效化当前用牌（CardDef.response 新字段：主动/响应结构不同） |
| 05 疯魔琴心 | ✅ | 双版本：20191212（best）"重置所有敌方角色的倒计时"（countdown_delta reset=true，复原 countdown_initial，无能力者空操作）/ 20200227"使一个敌方式神[倒计时]+2，妖琴师[倒计时]-2"（choose 敌方式神；正向 delta 直接累加无上限，-2 可归零触发基础能力） |
| 06 觉醒·神乐歌 | ✅ | 倒计时-1 + 1 力量/1 生命（friendly_others；增益为临时修正，气绝清除）；牌面-3 挂 on_before_awaken |
| 07 觉醒·镇魂歌 | ✅ | 倒计时 draw 1 + gain_orb 1；牌面-3 挂 on_before_awaken |
| 08 余音 | ✅ | 双快照：20191212（best）自身 -3 并 repeat 一次 / 20200120 自身 -3 + friendly_others -1（气绝者不在目标池） |
| 21 风之乐章 | ✅ | 协战主牌：options 双子选项，choice 选择后生成 token 视作从手牌使用，主牌离手进 exiled |
| 51 幻音绝弦 | ✅ | delay_grant（on_turn_start，uses=1，不用 scope=turn 以免同批清除）：己方式神倒计时-1 + 气绝者气绝倒计时-2（revive 参数，≤0 立即复活）；羁绊=随机一目连形态牌 |

## 一目连（100125）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20191212 文本"被消灭时触发"；实现保持离场/被消灭均触发（早期文本不规范，能力不变——维护者定案） |
| 01 风符·破 | ✅ | |
| 02 风符·护 | ✅ | |
| 03 风符·势 | ✅ | |
| 04 风符·瞬 | ✅ | 20191212：去[瞬发]（响应入场+回合结束自毁不变） |
| 05 罡风 | ✅ | |
| 06 觉醒·一目连 | ✅ | 20191212：去使用效果"随机获得形态牌"；能力进场/离场/被消灭均触发不变（文本规范化） |
| 07 风符·湮 | ✅ | |
| 08 风符·龙 | ✅ | 20191212：伤害 6→5；计数绑定卡牌实例 |
| 51 风韵雅乐 | ✅ | 协战子选项（一目连侧战斗牌）：replay_countdown(100125) 重放 + 羁绊=随机妖琴师觉醒牌（generate subtype=awaken） |

## 以津真天（100126）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 静态倒计时块（initial 2）：generate card_id 指定生成黄金羽 token（token 不入随机池） |
| 01 金羽焕生 | ✅ | generate card_id ×2 |
| 02 风之舞 | ✅ | 卡牌触发器按 on_card_played 的 golden_feather payload 计数（add_mod persistent，打出装配快照；含金风流羽） |
| 03 觉醒·以津真天 | ✅ | 觉醒倒计时 initial 1（来源=觉醒牌 id）；"黄金羽可以敌方角色为目标"由黄金羽的使用方式表达（见出入 5；已按维护者答复(11)） |
| 04 射怪鸟事 | ✅ | 响应挂 on_before_defeat（条件显式式神 id）；discard 写 memo["discarded_count"] + draw {"memo": key} 组合"弃多少抽多少" |
| 05 金风流羽 | ✅ | 20191212：+0/+0、不再"视为黄金羽"（去 tags golden_feather，不记账）；cost_zero_if {ext: feather_used_turn} 条件免费保留 |
| 06 不可饶恕 | ✅ | grant_immunity(scope=turn, unique) 回合级战斗伤害免疫：回合号记账自然过期；多次使用黄金羽不重复授予 |
| 07 千羽风之舞 | ✅ | 20191212 改 transform_card：手牌一张'黄金羽'原位变成'金风流羽'（无匹配空操作）；step 级条件 {player_ext: feather_used_turn} |
| 08 流浪之羽 | ✅ | 20191212 改全体：形态能力挂 on_card_played（golden_feather payload）→ 所有敌方式神 2 伤 |
| 21 致命之羽 | ✅ | 协战主牌：同风之乐章（options=[鎏金幻羽, 蚀刃毒羽]） |
| 51 黄金羽 | ✅ | 衍生 token 法术（不可构筑）；基础效果固定打敌方牌手，觉醒后狙击走 methods（choose 敌方角色） |
| 52 鎏金幻羽 | ✅ | mod_hand 实例修饰（真黄金羽=tags+token 谓词，金风流羽不修饰；once_key 不可叠加）：气绝时可用/伤害+1/双方气绝倒计时-1 三读取点；羁绊=鸩倒计时-2 |

## 萤草（100127）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20191212 改为"萤草的形态牌获得[瞬发]且使用时抽一张牌"：on_ability_enter（新事件，能力进场统一路径）登记 card_aura scope="ability"（新作用域：随能力离场移除/进场重注册）+ on_card_played 形态牌抽 1；20200327 快照（best 保持 20191212）：要求结附形态才生效——card_aura require_holder_form + on_card_played payload pre_play_form 门控 |
| 01 吸取 | ✅ | 使用时主动选择目标（choose any_shikigami）造成 2 伤害（维护者答复(4)，原投射定案作废）+ 鼓舞 +2 护甲 |
| 02 治愈之光 | ✅ | 入场与己方回合开始全体己方式神回 2（[瞬发]由能力光环统一授予，不入卡牌定义） |
| 03 萤火点点 | ✅ | 使用方式二选一（+1生命/打1）；增强"己方回合开始若萤草有形态此牌效果+1"（triggers 计数 add_mod enhance）；20191212 去[瞬发] |
| 04 勇气之光 | ✅ | 20191212：入场与己方回合开始鼓舞 +2 战力（原 +1 战力 +2 护甲） |
| 05 闪烁 | ✅ | [响应] 敌方式神进入战斗区自动使用；power_override scope=turn（ext power_zero_turn 半回合覆写）；20191212 去增强瞬发 |
| 06 安魂之光 | ✅ | 20191212：入场与己方回合开始 +1 鬼火（去牌手回 2） |
| 07 虹彩 | ✅ | 双快照：20191212 去[瞬发]（best 保持）/ 20200520 加[瞬发]；generate 萤草三种形态牌各 1 张入手 |
| 08 觉醒·萤草 | ✅ | 20191212：3 级 +2/+2（原 2 级 +1/+1）；[觉醒]己方式神的形态牌获得[瞬发]且使用时抽 1——card_aura shikigami="any"（新通配）scope="ability" + on_card_played 形态牌抽 1 |
| 51 森佑灵引 | ✅ | 协战子选项（萤草侧）：search_deck card_type=form + max_level="target"（不高于目标式神等级）+ direct_play_power_ge=4（目标存活且力量≥4改为直接使用——不耗火 play_from=deck），检索命中即洗牌库（维护者答复(5)）；羁绊白狼获得[庇佑] |

## 鸩（100128）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 静态倒计时块（initial 2）：敌方牌手 2 破甲 + bump_ext 累计 x（zhen_proc，气绝不清） |
| 01 鸩羽 | ✅ | battle_immunity 带 Step.condition：战斗开始时以 {defender: 被攻击者} 求值（defender_has_fragile） |
| 02 鸩羽苏生 | ✅ | countdown_delta -2（可立即归零）+ 抽 1 |
| 03 寂寥心象 | ✅ | 20191212 改"敌方式神本回合第一次获得破甲 → 鸩倒计时-1"（turn_mark 门控不变；删牌手分支与"等量破甲"支路） |
| 04 毒蚀 | ✅ | convert_damage 战斗作用域：已按维护者答复(5)——伤害事件生成点全额转化为等量破甲（护甲不再先吸收；不再视为伤害）；响应挂 on_before_assault（条件显式式神 id，响应收集不带 holder） |
| 05 觉醒·鸩 | ✅ | 20191212 使用效果"使鸩的倒计时-2"= 效果步（维护者定案：先替换觉醒能力、后对刚注册的新倒计时 -2，归零即触发觉醒能力）；x = 基础+觉醒倒计时生效合计（维护者答复 9），{base: 2, ext: zhen_proc} 动态数值；觉醒倒计时来源=觉醒牌 id，先给破甲再计数 |
| 06 致命诱惑 | ✅ | 战斗牌 grant_keyword step = 战斗作用域条件授予（吸血；战斗终止点移除） |
| 07 碧羽散华 | ✅ | 双快照：20191212"对有破甲的角色才转化"（新锚点 ext fragile_to_damage_if——获得破甲前判定受害者 shield<0）/ 20200120（best）无条件转化（fragile_to_damage）；牌手沿用"其任一式神持标记"语义；与毒蚀同场经 converted 标记防循环 |
| 08 毒之华 | ✅ | temp_grants 绑本次战斗；"一半生命"=受伤后当前生命向下取整（{half_health_of: victim}）；on_damage payload 补 battle 键供战斗绑定触发匹配 |
| 51 蚀刃毒羽 | ✅ | 协战子选项（鸩侧战斗牌）：已按维护者答复(2)重做——temp_grants 挂"攻击时"（on_before_assault），目标有破甲则 fragile_echo 记录数值，本次战斗结束后一次性回赋等量破甲（见出入 9）；羁绊=以津真天倒计时-2 |

## 凤凰火（100105）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_card_played {player: self, card_type: spell, shikigami: 100105} → 投射 1（含觉醒/响应/凭空自动使用） |
| 01 凤鸣 | ✅ | [瞬发] 打敌方牌手；双版本：20191212（best）3 伤 / 20200227 2 伤 |
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
| 02 怪力 | ✅ | 双版本：20191212 +0/+0 / 20200327 +0/-1（战斗牌负护甲=1 破甲，腐坏直拳先例）；永久 +1 力量按常规效果步执行（战斗牌流程不再误提取为本次战斗战力） |
| 03 怒吼 | ✅ | 全体己方式神临时 +1 力量（20191212：自身不再永久——raw 未标"永久"按默认临时，维护者已定案） |
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
| 05 偷袭 | ✅ | 双快照：20191212（best）挂 on_shikigami_defeated {victim_side: enemy, in_combat: true, summon: false} / 20200423 改挂 on_turn_end {player: opponent, combat_empty: enemy}（新条件键）+ 敌方回合[瞬发]（triggers on_turn_start → card_aura card_id 自指 turn=opponent，伺机同型）；力量 +3；非"（被）攻击时"时机的响应战斗牌不插入当前战斗——按完整战斗流程发起新战斗（嵌套战斗，正常反击；rules.md 第二章备注） |
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
| 07 蹈海 | ✅ | 双快照：20191212 形态 4/9（best 保持）/ 20200520 形态 3/8；on_damage {source_shikigami: self, kind_not: effect} → friendly_others_character 新池（己方其他角色，排除来源含牌手）恢复等量 |
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
| 02 青灯夜谈 | ✅ | **pending_choice 结算中交互选择**机制（GameState.pending_choice + choose 指令 + _suspended 内存态续点）：deck_top_pick 次数={orb: true}（1+剩余鬼火，0 火仍执行基础 1 次），末次后清空鬼火续块；联机 sanitize 对非选择方抹除 options；text 按 raw 无"洗牌库"——调度/牌库拿牌隐含检索洗牌（维护者答复(8)），引擎 deck_top_pick 固定洗牌为正确行为 |
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
| 03 心即归处 | ✅ | revive self（20191212 去[瞬发]）；playable_when_defeated + only_when_defeated 字段："仅在犬神气绝时可用"硬门控——存活时主动使用报错、响应收集直接跳过 |
| 04 恶·即·斩 | ✅ | 战斗 +4/+0 |
| 05 守护 | ✅ | id 按 raw 重排（原 06）；战斗 +0/+4；[响应]挂 on_before_assault {victim_side: friendly, victim_kind: shikigami, victim_not_shikigami: 100115, attacker_side: enemy}：响应插入把犬神移入防守方战斗区、无目标战斗重读目标 = "攻击目标改为犬神"（零新引擎代码）；追猎类定向战斗可响应——守护者照常移入并获得 +0/+4，但目标不转移仍打原定目标（维护者定案）；text 按 raw 无"转移攻击目标"字样（见出入 20） |
| 06 心剑乱舞 | ✅ | id 按 raw 重排（原 07）；形态 4/9：card_aura scope=form keywords [fast]（犬神的牌获得[瞬发]，读取时求值） |
| 07 心技一体 | ✅ | id 按 raw 重排（原 05）；level 2 形态 3/5 → level 3 形态 4/9；card_aura scope=form + power_ext/shield_ext（ext 数值通道，读 lianmo_used_game）；双快照：20191212 记账卡='羁绊的价值' best / 20200120 记账卡='心身炼磨'（均 tags [lianmo] 出牌记账）；手牌数值显示已含光环 ext 通道（刃影叠岚同解） |
| 08 觉醒·犬神 | ✅ | +0/+0（20191212 去 +1/+1）；on_turn_end {player: self, holder_defeated: true} + trigger_when_defeated 字段（能力收集对气绝者放行——仅气绝时触发）：revive + perm +1/+1；raw 无气绝限定，机制保持仅气绝时触发（见出入 19） |
| 51 心身炼磨 | ✅ | 衍生（20200120 起升级产物）：perm +1/+1；tags [lianmo] 保留；重写为 20200120 唯一版本——去 20251212 的动态瞬发（conditional_keywords {level_ge: 2}）与免费（cost_zero_if {level_ge: 3}） |

## 桃花妖（100119）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_heal {source_shikigami: self, target_side: friendly, target_kind: shikigami} / on_shikigami_revived {source_shikigami: self, shikigami_side: friendly} → 临时 +1 力量（revive op 补 source/reason="effect" 传递；倒计时复活 source=None 不触发） |
| 01 桃之馨息 | ✅ | choose any_character heal 5 |
| 02 花信风 | ✅ | [瞬发]；search_deck 新 op（按选择目标式神 id 滤牌库 rng.choice 入手，命中才洗牌库、未命中不洗——维护者定案）；边界：选择池 friendly_shikigami 限在场式神（气绝/未升级式神暂不可选） |
| 03 丰实 | ✅ | id 按 raw 卡序重排（原 04）：形态 3/7：进场与 on_turn_start {player: self} → heal 3，friendly_injured 池 + TargetSpec {random: 1} 键（rng.sample，repeat 每轮重解析重随机） |
| 04 桃之夭夭 | ✅ | id 按 raw 卡序重排（原 03）：cost 0 + keywords [inspire]（鼓舞关键字登记）；basic_boost +2/+2 出击加成 |
| 05 桃语春风 | ✅ | choose friendly_defeated 新池 revive + grant_keyword haste（迅捷天然一次性类别） |
| 06 盛开 | ✅ | 形态 4/9：进场与 on_turn_start → repeat 3 × heal 2（friendly_injured + random 1） |
| 07 桃华灼灼 | ✅ | 20191212 回退去"全员[迅捷]"：conditional_keywords {keyword: fast, if_alive: true}（未气绝得[瞬发]）+ playable_when_defeated；revive friendly_defeated 全体 |
| 08 觉醒·桃花妖 | ✅ | 20191212 回退去使用效果（原"为一个角色恢复5生命"）：+2/+1；同基础两 trigger 改 perm +2/+2 |
| 21 繁花似锦 | ✅ | 协战本体（桃花妖&樱花妖，options=[10011951, 10040351]），随 raw 补文本入库 |
| 51 桃红簇簇 | ✅ | 协战子选项（桃花妖侧形态 3/6）：on_enter_combat/on_leave_combat 新事件 {player: self} → heal 2 context shikigami（治疗来源=桃花妖→连锁基础赋益）；on_damage_start {victim_side: friendly, victim_kind: shikigami, victim_lethal: true, victim_in_combat: false} → grant_immunity kind=all scope=once 新作用域（消耗式，_combat_immune/_effect_immune 命中即移除）→ destroy_form self；羁绊 step 级 condition {shikigami_active: 100403} 门控（樱花妖等级不为 0 且未气绝才触发） |

## 判官（100110）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_shikigami_defeated {victim_kind: shikigami, source_shikigami: self}（判官消灭式神）→ 打敌方牌手 1 + 己方牌手回 1；本体双快照（20191212 3/4 best / 20200120 2/4） |
| 01 墨笔夺魂 | ✅ | buff_health 负值通道：上限下调同步钳当前生命，上限 ≤0 走气绝（维护者定案） |
| 02 勾诀 | ✅ | TargetSpec 过滤键 power_le（spec_pool_refs 统一校验/展示） |
| 03 生死无常 | ✅ | [响应] 挂"己方战斗区式神被攻击时"；两连 destroy（任一侧战斗区为空该步空操作）；text 按 raw 对齐 |
| 04 无情 | ✅ | 形态：countdown_delta revive=True——敌方式神气绝倒计时 +1 |
| 05 觉醒·判官 | ✅ | +1/+1；20191212 为纯觉醒替换（去 -2力量/-1生命效果步与 target）；觉醒能力"当你消灭一个式神时"= {source_side: friendly}（己方任一式神消灭即触发，不限判官本人） |
| 06 夺命 | ✅ | [必杀]（20191212 去[穿刺]）；增强门控 = 击杀账本 `{kill_count_ge: 13}`（评审⑩迁移：triggers 自计数 + persistent transformed 已删，门控直读 `kill_total`）；变后 = temp_grants（绑本次战斗）on_damage/on_player_damaged {source_shikigami: self, kind: combat} → destroy victim / damaged_player（destroy 支持牌手目标：消灭牌手 = 直接获胜，维护者定案） |
| 07 死之宣告 | ✅ | destroy 任选式神（含己方） |
| 08 断罪 | ✅ | 形态增强：triggers 消灭计数 → form_power_delta（_materialize 生成点统一快照，_mat 记账防重复合并） |

## 清姬（100114）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 伪关键字 damage_to_fragile 永久通道（ShikigamiDef.keywords → perm_keywords，死亡不清）：伤害事件生成点对无破甲受伤者全额转化为等量破甲（不再视为伤害；与毒蚀同位置，converted 防循环） |
| 01 蛇行击 | ✅ | 双版本：20191212（best）= [瞬发] 1 伤 + 条件式增强（chosen_has_fragile 新 Step 条件键：目标有破甲 → bounce_self 条件回手 + 伤害再 +1）；20200624 = [瞬发][弹回] 2 伤——弹回首卡（_rebound_check：结算完毕牌在墓地移回手牌；_mat 快照去重防修饰重复合并） |
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
| 06 门前清 | ✅ | 已按 raw 与 05 互换；形态 2/9；双快照：20191212（best）只留被攻击挂点（on_before_assault {victim_shikigami: self}）/ 20200423 出击或被攻击双挂（attacker/victim 两块，祝福之愿同型）；EffectBlock.luck:4 → gain_shield 2 |
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

进场顺序语义（2026-08 落地，rules.md 第十六/十七章）：变形/还原均为再进场——`entry_order` = 本队 max+1（排本队最后）；回合开始倒计时批次按 entry_order 升序动态取序；还原时快照携带的剩余倒计时优先保留、不被能力进场重置初值。戏谑套索机制已存在无需改。关联点 6 条维护者已全部答复定案（复活不更新、召唤物/替换视同新进场、能力进场顺序 ability_entry/TempGrant.seq、批次动态取序、还原时各能力依次进场——见 questions.md 本轮已落实）。

## 座敷童子（100129）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | on_luck_judge（即时；判定者=己方且骰=1）→ luck_reroll（同一判定每个来源能力至多一次，重投同样吃必 6 修饰） |
| 01 金运大吉 | ✅ | 20191212 去进场触发：己方回合开始 luck_roll{x:4, judge:both, then:[抽1]}（双方各生成事件、当前回合玩家先、判定者各自抽） |
| 02 五谷丰壤 | ✅ | 20191212 同去进场触发；then:[恢复 3 生命] |
| 03 福寿双全 | ✅ | 形态 4/5；增强{shikigami_has_form:100129}→[瞬发]+使用时抽 1；进场或仅替换离场时双方各 +1 鬼火（气绝消灭不触发） |
| 04 福满乾坤 | ✅ | 20191212：等级 3→1、[条件]改[增强]{luck_success_total_ge:15}（无 play_condition——可使用，各 step 以条件门控，不满足全跳过）；效果不变（双方生命变 30 → 抽至 10 张 → 各 +3 鬼火） |
| 05 福运昌隆 | ✅ | 抽 1；luck_roll{x:4} → 获得 2 鬼火 |
| 06 家内安全 | ✅ | 形态 3/7；式神攻击后 luck:{x:4, on:fail} → stun{攻击者} |
| 07 和气满满 | ✅ | 形态 0/7；式神攻击时 luck:{x:4, on:fail} → 攻击者本次战斗力量变 0（power_override 战斗作用域） |
| 08 觉醒·座敷童子 | ✅ | +1/+3；on_luck_judge（判定者=己方且将失败，{dice_below_x: true}）→ luck_reroll |
| 51 鸿运当头 | ✅ | 协战子选项（座敷侧）：luck_roll{x:4, then:[复活己方全部式神]} → random_play_form{friendly 在场}（各随机使用 1 张等级 ≤ 当前等级的专属形态牌，无池/气绝跳过）；羁绊（山兔在场，{shikigami_active:100117}）：search_deck card_id 检索'这把算我赢'置手 |

## 妖狐（100130）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20200120 加入（开服无妖狐）：妖狐使用法术牌时 luck:4 → random_damage{2 + amount_ext:yaohu_dmg_bonus(amount_ext_source:shikigami), enemy_character}；伤害流程按来源=妖狐每次伤害事件记 yaohu_damage_count +1 |
| 01 风刃 | ✅ | 20200120：[瞬发]；改[投射] 2 伤（pool=projectile，不再主动选目标） |
| 02 聚气 | ✅ | 20200120：[瞬发]；bump_ext{yaohu_dmg_bonus, self}（去抽 1；永久含基础与觉醒能力，跨气绝保留） |
| 03 命运之人 | ✅ | 双版本：20200120 形态 4/5 / 20200227（best）4/6；己方回合开始 generate '风刃' 置手 |
| 04 无羁风弹 | ✅ | repeat_random_damage{2, all_other_shikigami, max:10, stop_on_defeat}（逐次插入结算，任一式神气绝即停） |
| 05 叠风斩 | ✅ | 对一式神造成 2 伤害 → reuse_card（同目标，恰好两次；触发两次妖狐能力） |
| 06 狂风刃卷 | ✅ | random_damage{2, enemy_character, sequential:true, count:5}（逐次独立随机、有放回）；增强{yaohu_damage_count>=25}→ count:10（20200120：阈值 20→25） |
| 07 觉醒·妖狐 | ✅ | +2/+2；觉醒能力两段：你使用法术牌（含中立法术牌）或运势判定成功时随机打一敌方角色 2（吃 yaohu_dmg_bonus；可因觉醒青蛙瓷器翻倍） |
| 08 爱意绵绵 | ✅ | 20200120：3 级形态 5/8（原 1 级 4/5）；card_aura shikigami="any"（新通配）——手牌所有法术牌伤害效果 +1（damage_boost 通道，scope=form） |

## 跳跳弟弟（100120）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 受到伤害时获得等量破甲（on_damage {victim_shikigami: self} → {event: amount}） |
| 01 腐坏直拳 | ✅ | transfer_fragile 新 op：自己破甲清零、等量转移到被攻击的式神（"确定攻击目标后转移"以战斗牌效果步时序表达） |
| 02 瘴疠体质 | ✅ | 双版本：20191212 形态 2/9 / 20200227（best）3/9：对其造成战斗伤害的式神获得 3 破甲 |
| 03 毒气喷泉 | ✅ | 双版本：20191212"获得等同于跳跳弟弟破甲的破甲"（{fragile_of: self} gain_shield 敌方全式神，来源保留破甲）/ 20200227（best，维护者指定）改转移语义（transfer_fragile 敌方全体，每名全量后来源清零）；增强 = 己方回合开始战斗区有式神则此牌得[瞬发] |
| 04 肿胀体质 | ✅ | 双版本：20191212 形态 3/14 / 20200227（best）4/14：keep_fragile 式神级破甲保留（形态结附期间破甲不在己方回合开始清除，形态离场解除）——20191212 回退去"进场 2 破甲" |
| 05 觉醒·跳跳弟弟 | ✅ | 20191212 回退：+1/+1（原 +1/+3）；受伤获得等量破甲并永久 +1 生命 |
| 06 甜蜜的负担 | ✅ | [瞬发][响应]"当你被攻击时自动使用此牌"：目标转移按守护先例——响应插入移入战斗区，无目标战斗重读战斗区驻留者（零新引擎代码） |
| 07 尸毒体质 | ✅ | 20191212 回退：形态 5/14，分段门槛 >=6 敌方式神 3 破甲 / >=15 敌方牌手 10 破甲（原 5/15、>=5/>=10） |
| 08 僵硬扑击 | ✅ | [瞬发][贯通]；{"fragile_of": self} 新动态数值——获得等同于自己破甲的力量 |
| 21 跳跳兄弟 | ❌ | 协战主牌（跳跳弟弟&跳跳哥哥，id 10012021）：跳跳哥哥未加入，暂缓 |
| 51 尸瘴 | ❌ | 协战子选项（跳跳弟弟侧幻境）：幻境机制未实现，暂缓 |

## 雪女（100121）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20191212 接入（2/4）：on_stun 新事件（即时时机，stun 施加点发出）+ turn_mark 每回合一次 → '雪球'置手 |
| 01 寒冰之盾 | ✅ | [响应] 挂"己方战斗区式神被攻击时"自动对其使用（剧毒之盾先例） |
| 02 吹雪 | ✅ | 打 3 + '雪球'置手 |
| 03 冰墙 | ✅ | 召唤'冰墙'：no_attack 新字段（不能发动攻击——出击校验拦截、launch_attack 空操作）；召唤物身材 20200520 快照见 99 行 |
| 04 寒冬之心 | ✅ | id 按 raw 重排（原 06）；'雪球'×2 置手 + card_aura 新通道：tag 谓词（仅命中 tags 含 snowball 的牌）+ damage_boost（卡牌效果伤害 +1）+ scope="game"（本局有效不清除） |
| 05 崩雪 | ✅ | id 按 raw 重排（原 04）；双版本：20191212 消灭一个[眩晕]的式神（目标池 stunned 过滤，best=20200120）/ 20200120 消灭或[眩晕]两段分流 |
| 06 冰风暴 | ✅ | id 按 raw 重排（原 05）；形态 2/4：敌方式神攻击后打其 1 再[眩晕]受伤者 |
| 07 流霰 | ✅ | id 按 raw 重排（原 08）；20191212 改"[瞬发]连用所有手牌雪球"：auto_use 新参数 from_hand（手牌全部同名牌逐张免费使用、目标强制继承、计入从手牌使用记账、无雪球空操作——定案(1)） |
| 08 觉醒·雪女 | ✅ | id 按 raw 重排（原 07）；+2/+1；20191212 去使用效果 3 点伤害、得雪球触发源收窄为雪女自己造成的眩晕（source_shikigami: self，定案(3)） |
| 21 冰霜永冻 | ✅ | 协战主牌（雪女&雪童子，id 10012121）：雪女侧子选项 冰封 已入库；雪童子侧 雪刃 待幻境机制；raw 标"未加入"，保持 20251212 快照 |
| 51 雪球 | ✅ | 衍生 token 法术[瞬发]；tags [snowball]（出牌记账与寒冬之心 tag 谓词共用） |
| 52 冰封 | ✅ | 协战子选项（雪女侧）：[眩晕]+获得'雪球'；[羁绊] launch_attack at="chosen" 定向攻击（雪童子对其发动一次攻击）；raw 标"未加入"，保持 20251212 快照 |
| 99 冰墙 | ✅ | 双快照：召唤物 0/2（20191212，best 保持）/ 0/4（20200520）（kind=summon，no_attack）；[眩晕]对其造成战斗伤害的式神 |

## 雪童子（100122）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 20191212 接入：text"单位"（机制不变）；combat_opponent_stunned 新条件算子（交战对方眩晕，双向判定）→ 不受战斗伤害 |
| 01 霜舞 | ✅ | 场上有[眩晕]敌方角色时此牌得[瞬发] |
| 02 霜风 | ✅ | 敌方战斗区无式神则[眩晕]敌方牌手 |
| 03 雪国之子 | ✅ | id 按 raw 重排（原 04）；形态 5/5：场上有[眩晕]敌方角色时 +2/+2 |
| 04 雪走 | ✅ | id 按 raw 重排（原 03）；+0/+0；[眩晕]战斗区敌方式神；[响应] 雪童子被攻击时自动使用此牌 |
| 05 胧月雪华斩 | ✅ | +2/+0；造成伤害时对所有其他[眩晕]的敌方角色造成等量伤害 |
| 06 霜天之织 | ✅ | 增强：场上每有一个[眩晕]的敌方角色 +1 力量 |
| 07 雪融之时 | ✅ | 形态 5/7：每次至多受到 3 点伤害；增强按本局敌人被[眩晕]次数 +力量 |
| 08 觉醒·雪童子 | ✅ | +1/+2；20191212 去使用效果眩晕、触发收窄为仅主动攻击（{attacker_shikigami: self, victim_stunned}，定案(2)）：获得[连击]（"额外先击中对手一次"）且免疫战斗伤害——grant_keyword scope="battle" 战斗作用域授予 |
| 51 雪刃 | ❌ | 协战子选项（雪童子侧幻境）：幻境机制未实现，暂缓；raw 标"未加入" |

## 跳跳妹妹（100131）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天伪关键字 extra_orb_cost（ShikigamiDef.keywords → perm_keywords）：出击/使用其战斗牌额外 +1 鬼火；[迅捷]/[瞬发]/[不消耗鬼火]时全免（定案(11)） |
| 01 坏人走开 | ✅ | [贯通] |
| 02 去咬他！ | ✅ | 召唤'番茄'并使其攻击（launch_attack） |
| 03 坐下！ | ✅ | 20200227 正式服上线版：stat_aura ids_power '番茄'永久 +1 力量（scope="game" 结附牌手、跨召唤保留，召唤物 10013199 与变形物 10013198 同生效，可叠加）；summon 新参数 orb_cost=1"额外消耗 1 点鬼火召唤'番茄'"——效果内嵌费用，剩余鬼火不足则召唤失败、光环照常（定案） |
| 04 生气了啦！ | ✅ | [连击]（20200227 text"本次战斗额外先攻击一次"= 同一机制，早期关键字未定型） |
| 05 别过来啊！ | ✅ | [瞬发] 召唤'番茄'；[响应] 跳跳妹妹被攻击时自动使用 |
| 06 出击！ | ✅ | '番茄'永久得"攻击造成伤害时随机对另一个敌方角色造成 3 点伤害"（可叠加） |
| 07 不玩了啦！ | ✅ | 气绝时可用战斗牌（定案(14)）：气绝中不获得战力/护甲——先结算卡面效果（复活跳跳妹妹），结算完未气绝则补齐战力/护甲并正常发起战斗，仍未气绝则牌入墓地不发起战斗 |
| 08 觉醒·番茄 | ✅ | 20200227：+3/+3；去"随机 2 张战斗牌置手"（现代版效果）；式神替换 replace（替换物 10013198 继承座次/等级、无快照不还原、复活仍为替换物、ext["replace_owner"] 放行跳跳妹妹全部卡牌、派系=替换物 def faction——定案 4 点；transform permanent/owner_combat 通道已删）；replace_cards/gen_replace——她的非战斗牌随机替换成战斗牌 |
| 99 番茄 | ✅ | 召唤物 3/4（kind=summon；跨召唤增益=坐下/出击结附牌手光环 stat_aura ids_power scope="game"，keep_buffs 通道已移除） |
| 98 番茄 | ✅ | 替换物 3/4（kind=transform 沿用构筑排除；觉醒·番茄 replace 的替换产物） |

## 觉（100108）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 己方回合开始随机展示一张敌方手牌（reveal mode=random；已全部展示则无效果） |
| 01 读心 | ✅ | [瞬发] 展示被选敌方式神在敌方手牌中的所有专属牌（reveal mode=shikigami + shikigami=chosen；协战牌归属按 _card_belongs_to 统一口径） |
| 02 棒球炸弹 | ✅ | 20191212 基础伤害 3→2（{base:2, per:2}）：2 伤 + 2×被选式神已展示专属牌数（动态数值 enemy_revealed_count: shikigami_of_chosen，per 倍率） |
| 03 模仿 | ✅ | 战斗牌[增强]：敌方每有一张已展示法术牌 +1 护甲、每有一张已展示其他牌 +1 力量（enemy_revealed_count: spell/other） |
| 04 强索 | ✅ | [瞬发] 调度敌方已展示的手牌 + 抽 1（mulligan_hand target_side=opponent + only_revealed + auto：按 hand_seq 前 3 张自动调度）；text 按 raw 无"并洗牌库"——调度隐含检索洗牌（维护者答复(7)），shuffle:true 照常 |
| 05 灵视 | ✅ | 形态 5/5；敌方牌手使用已展示的手牌时对他造成 2 伤（on_card_played 载荷 card_revealed 条件）；20191212 去[吸血]、改"你恢复 2 点生命"（heal 2 self_player） |
| 06 记仇 | ✅ | 双版本：20191212（best）= "复仇复制"——delay_grant 一次性监听（跨回合留存）：下一次任意玩家对单个己方式神使用法术（chosen_side 新条件键，on_card_played 新增 chosen 载荷）→ echo_event_card 以觉方身份凭空复制、目标强制=施法者自身式神、不做合法性检查（维护者答复(5)）；20251212 = 消灭一个本回合造成过伤害的敌方式神（TargetSpec 过滤键 dealt_damage_turn——伤害结算点记账、回合开始清除）；[响应] 受到敌方式神伤害时自动对伤害来源使用（response 覆盖块 + context source） |
| 07 心灵迷宫 | ✅ | 形态 5/5；敌方使用已展示的手牌额外耗 1 鬼火（cost_delta_player side=opponent + card_flag=revealed + scope=form——形态结附期间持续、离场移除；仍在 cost>0 门内，[瞬发]/[不消耗鬼火]全免）；增强：敌方手牌全部已展示时得[瞬发]（conditional_keywords 算子 enemy_hand_all_revealed） |
| 08 觉醒·觉 | ✅ | 双快照：20191212（best 保持）2 级：+1/+1；展示敌方所有手牌（reveal mode=all 补存量）；觉醒被动①：每当一张牌进入敌方手牌时将其展示（入手统一钩子 on_card_enter_hand + reveal mode=event）；被动②：敌方牌手使用已展示的手牌时觉 +1/+1 / 20200520 3 级：使用效果 reveal all + on_turn_start reveal all（双方回合开始——维护者定案(4)确认；入手即展示被动按 raw 不带入） |

（**经典包 01_jingdian 31 位式神至此完结**——不含未加入的协战对象：跳跳哥哥/樱花妖等；其协战牌主牌/子选项随之暂缓，见文末协战牌 id 设计。）

# 02 不夜之火（20200327）

## 鸦天狗（100201）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 双挂 on_enter_combat/on_leave_combat（新[移动]机制进出各触发一次）：各投射 1 伤 |
| 01 追风 | ✅ | [瞬发]；move self（战斗区↔准备区 toggle）+ 抽 1 |
| 02 正义必胜 | ✅ | 战斗牌；{ext: move_count_turn} 动态数值——本回合移动次数加力量（含本牌移入战斗区的一次） |
| 03 正义之刺 | ✅ | 战斗 +1/+2 甲；launch_attack shikigami=target（使被选式神立刻攻击，来打我呀先例） |
| 04 羽迹 | ✅ | move force=true 拉敌方式神入战斗区（过尘缚锁定校验）→ 眩晕之 → move self |
| 05 群鸦乱舞 | ✅ | 形态 2/8：己方回合结束敌方全式神 1 伤 → heal {memo: last_damage_total} 自回合计（巨浪先例） |
| 06 鸦羽疾走 | ✅ | [响应]挂 on_before_assault：move self ×2（离场再进场）+ cancel_attack（取消整场攻击，不退鬼火/出击次数——维护者定案） |
| 07 英雄无畏 | ✅ | stun lasting + until_event=[on_card_played, on_before_assault]（"直到鸦天狗使用牌、攻击或气绝"；apply_seq/apply_uid 防施加牌自解除，气绝走现有清理） |
| 08 觉醒·鸦天狗 | ✅ | +2/+2；进出战斗区改"获得[远程]并攻击"（attack_buff keywords remote + launch_attack self） |

## 不知火（100202）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 己方回合开始鼓舞 +1 战力（basic_boost） |
| 01 不夜之舞 | ✅ | 形态 4/5：boost_on_combat_card scope=form（玩家级旗标：战斗牌攻击也获得并消耗出击加成，形态离场清除） |
| 02 真意之歌 | ✅ | 双快照：20200327 reset_assaults 单段 / 20200423 [瞬发]"若出击次数>0 则[鼓舞]+1/+1 否则重置出击次数"（assaults_left_ge/le 两条件 step 分流，best 保持 20200327） |
| 03 自由之歌 | ✅ | 鼓舞 +3 战力 +3 护甲 |
| 04 初会之舞 | ✅ | 形态 2/6 [远程]（卡牌级关键字）：对牌手造成伤害时抽 1 |
| 05 觉醒·不知火 | ✅ | 双快照：20200327 +0/+0 / 20200423 +1/+1（best 保持 20200327）；inspire_bonus{1,1}（鼓舞数值额外 +1/+1，玩家级永久旗标、可叠加）+ 基础同款回合开始鼓舞 |
| 06 星火之歌 | ✅ | 召唤'烬染不夜'（10020299） |
| 07 离殇之舞 | ✅ | 形态 5/5：boost_no_consume scope=form（出击加成不消耗旗标） |
| 08 惊鸿之舞 | ✅ | 形态 SSR 3 级 7/7（date/best=20200327）；on_turn_start（无 condition，双方回合开始均触发）单步 random_branch 19 分支（新 op：逐项求值 condition、通过者均等随机一项、无满足空操作；raw 清单与触发前置括注保留为 yaml 注释）——分支前置新条件键 friendly_defeated_exists/player_health_le/player_missing_health_ge/combat_occupied；分支 19 鼓舞带 keyword_random 随机关键字槽（ext["boost_keyword"]，池=[不屈/吸血/远程/必杀/贯通/连击]）；分支 5/13 highest_power 过滤（并列全保留交 random 均等取）；分支 4 grant_keyword scope="turn"；分支 6 敌方全体 -2 力量=非永久持续减益（跨回合保留、气绝清除）、分支 13/14 多步随机目标经 memo 键复用同次取样（14 加 include_defeated 含气绝——均已定案） |
| 99 烬染不夜 | ✅ | 召唤物 1/1，先天[迅捷]；attack_replace（攻击时改为对两个随机不重复敌方角色造成 力量+战力 效果伤害，无交战不受反击；目标池含牌手、伤害为非战斗伤害 kind=effect 不触发[吸血]——均维护者定案） |

## 小鹿男（100203）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[充能]；复活时获得 2 能量（on_shikigami_revived → gain_energy 2） |
| 01 祝福之愿 | ✅ | 形态 3/6：被攻击时随机另一名己方[充能]式神 +1 能量（TargetSpec keyword 过滤 + random 1） |
| 02 森之佑 | ✅ | 永久 +1/+1 + 1 甲；[爆能2] 方式（energy_cost=2，effects 追加） |
| 03 森之力 | ✅ | 眩晕 + 3 伤；[爆能2] 方式带 keywords [fast]（方式临时授予关键字） |
| 04 自强之愿 | ✅ | 形态 4/6：被攻击时 spend_energy 1 gate → 获 2 甲（不足中止块） |
| 05 森之守 | ✅ | 授予[帷幕] |
| 06 觉醒·小鹿男 | ✅ | +0/+1；使用效果复活自身；form_death_play{energy:3}（玩家级旗标：其形态牌气绝时可用——耗 3 能量、先复活再结附） |
| 07 鹿角冲撞 | ✅ | 战斗 +2/+2 甲 [贯通]；[爆能2]/[爆能4]/[爆能8] 多档累计（各档独立支付、effects 追加，爆能8 档含[连击]+战斗免疫） |
| 08 生生不息 | ✅ | 形态 4/9：被攻击时 spend_energy 1 gate → 投射 3 |

## 烟烟罗（100204）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[充能]；on_energy_gained → gain_energy 1 emit_event=false（获得能量时再获得 1，防自连锁） |
| 01 顽皮鬼 | ✅ | 2 伤；[爆能X]（energy_cost="all"：消耗全部能量追加 {burst_x} 伤害，0 能量不可选） |
| 02 扑朔迷离 | ✅ | [响应]：summon 分身 inherit_stats + energy_ratio=0.5（复制来源**全部当前身材**快照为静态永久修正——含持续性/光环增益与受伤不满生命，维护者定案；能量 floor 一半） |
| 03 烟雾升腾 | ✅ | [瞬发]；获得 3 能量 |
| 04 烟雾缭绕 | ✅ | 形态 2/4：召唤分身 + stat_aura ids_energy_power（分身每有能量 +力量，scope=form） |
| 05 贪食鬼 | ✅ | 打敌方战斗区 3 + 牌手回 3；[爆能X] 追加 {burst_x} 伤害 |
| 06 觉醒·烟烟罗 | ✅ | +1/+1；使用获得 2 能量；on_energy_gained → 再获得等量（{event: amount}，emit_event=false） |
| 07 无孔不入 | ✅ | 形态 3/6：进场与己方回合开始召唤分身 |
| 08 暴躁鬼 | ✅ | 投射 3 + delay_grant（分神气绝时获得 3 能量）；[爆能X] 追加 {burst_x} 伤害 |
| 99 烟烟罗的分身 | ✅ | 召唤物 2/4，先天[充能]；mirror_spell（复制烟烟罗使用的非觉醒法术——主动/响应/自动使用均触发，mirror_copy 标记防递归不连锁，维护者定案；目标沿用原选否则随机重选） |

## 日和坊（100205）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[充能]；生命代偿引擎硬编码 id 100205（己方支付能量不足时以其生命 1:1 代偿，非伤害、不能降到 0） |
| 01 沐浴阳光 | ✅ | 双快照：20200327 无[瞬发] / 20200423 加[瞬发]（best 保持 20200327）；heal full=true（恢复至满）+ 各 +1 能量；目标池 friendly_shikigami + TargetSpec keyword=charge 过滤（己方[充能]式神） |
| 02 祈晴 | ✅ | 形态 1/7：己方回合开始 spend_energy 4 gate → 抽 1 |
| 03 阳炎 | ✅ | 双快照：20200327 1 级响应带"额外消耗3能量"（energy_ge: 3 门控 + spend_energy 3 gate）/ 20200423 2 级、响应去耗能（best 保持 20200327）；[响应]（on_upgrade）：打升级式神 1 + 眩晕之 |
| 04 冬日暖阳 | ✅ | 己方[充能]式神各 +1/+1 + 2 能量 |
| 05 滋养 | ✅ | 形态 2/7：己方回合开始 spend_energy 4 gate → +1 鬼火 |
| 06 日出有曜 | ✅ | [瞬发]；单目标（全场未气绝角色、敌我均可——维护者定案，原方式B回退偏差消除）双 step：reset_stats（力量/生命回基础值+清护甲破甲，非伤害/治疗事件；对牌手空操作）/ clear_boosts（显式选牌手才生效、选式神空操作、无目标才回退控制者） |
| 07 觉醒·日和坊 | ✅ | [瞬发] +0/+3；ext["energy_free_turn"]（每回合一次、不分敌我回合：己方式神耗能量效果免单；爆能X免单时 X 按当前能量读、消耗 0） |
| 08 晴雨 | ✅ | 形态 3/8：己方其他角色受伤时自回 3；每回合结束 spend_energy 3 gate → 其他己方角色回 3 |

## 镰鼬（100206）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 先天[充能]；对牌手造成伤害时 +1 能量 |
| 01 三太郎之斧 | ✅ | 战斗 +1/+1 甲；[爆能3]：此牌 +3 力量（方式 effects 追加） |
| 02 人多势众 | ✅ | 双快照：20200327 形态 4/5 / 20200423 形态 3/5（best 保持 20200327）；stat_aura energy_power{divisor:2}（每 2 能量 +1 力量，scope=form） |
| 03 声东击西 | ✅ | [响应] 被攻击时自动使用：battle_retarget（交战伤害改向另一个随机敌方角色，可含牌手——维护者定案）+ 本次战斗免疫 |
| 04 同心协力 | ✅ | [瞬发]；+1 能量 + 复制随机插入牌库不洗牌（generate position=random，"置入牌库"原版语义——维护者定案，原落库底偏差消除）+ 抽 1 |
| 05 二太郎之戟 | ✅ | 双快照：20200327 +0/+2 甲 [爆能3] / 20200423 +0/+1 [爆能4]（best 保持 20200327）；对敌方角色造成伤害后其获 2 破甲（temp_grants 双挂，含牌手）；use_card_copy 额外使用'三太郎之斧' |
| 06 同生共死 | ✅ | 形态 4/5：受致死伤害时 spend_energy 3 gate → 消耗式免疫（grant_immunity kind=all scope=once）+ retreat |
| 07 觉醒·镰鼬 | ✅ | +1/+1；energy_assault{cost:3}（玩家级旗标：鬼火与出击次数都为 0 时耗 3 能量出击） |
| 08 一太郎之棒 | ✅ | 双快照：20200327 [爆能3]/[爆能6] / 20200423 [爆能3]/[爆能7]（best 保持 20200327）；战斗 +2/+2 甲；伤害后眩晕之且本回合力量变 0（power_override scope=turn）；链式 use_card_copy（多档累计） |

## 铃鹿御前（100207）

| 卡牌 | 状态 | 备注 |
| --- | --- | --- |
| 基础能力 | ✅ | 紫岩 3/4；"对一个角色造成伤害时使其获得1破甲"（abilities 双块：on_damage/on_player_damaged {source_shikigami: self} → gain_shield fragile 1，二太郎之戟同管线） |
| 01 白刃 | ✅ | 战斗 +1/+1 甲；conditional_keywords 新算子 enemy_fragile_ge2（敌方场上存在破甲 ≥2 的角色时此牌得[瞬发]） |
| 02 霸主 | ✅ | 形态 4/5：grant_immunity 新 kind=fragile_source scope=form（免疫当前持有破甲的敌方式神造成的伤害——牌手来源不免疫、类别不限，维护者定案(5)确认） |
| 03 光影 | ✅ | 战斗 +1/+1 甲；temp_grants 双块 on_damage/on_player_damaged（条件 kind:combat + source_shikigami: self + amount_ge:6——单伤害事件触发，维护者定案：贯通两段各<6合计>=6不触发、连击两段各>=6各触发一次）→ 抽 1 + heal {event: amount, half: true}（新数值通道：事件值减半向下取整，与 cap 同修饰位、cap 先截后减）己方牌手 |
| 04 冥弓 | ✅ | distribute_damage 4 pool enemy_shikigami（随机分配给所有敌方式神——天狗风乱同管线收窄池，无新机制） |
| 05 觉醒·铃鹿御前 | ✅ | +0/+1；abilities 双块同基础能力管线：gain_shield fragile {event: amount, cap: 3}（事件引用封顶新形式——维护者定案(3)确认）；20200624 快照使用效果投射 2→1（best 仍 20200520） |
| 06 无往 | ✅ | 战斗 +0/+2 甲；choose 新目标池 enemy_fragile_or_combat（敌方有破甲的在场式神或敌方战斗区式神，或关系）→ 打 2 |
| 07 归乡 | ✅ | 形态 4/8：on_before_assault {attacker_shikigami: self} 投射 3（生生不息同管线，无能量消耗） |
| 08 义道 | ✅ | 战斗 -1/+2 甲，keywords [piercing, combo]；新 op double_damage_vs_fragile 为战斗牌专用提取步——按[暴击]时机（扣减生命前2 挂点，engine.py:2895 锚点）：本张战斗牌发起的战斗内、铃鹿御前本人、kind=combat（反击不翻倍）、victim=持破甲式神 ×2，嵌套/插入战斗不继承（维护者定案(2)；[暴击]本体预留锚点） |

（02 不夜之火 7 式神落地：前 6 式神各 8 卡（= 48 卡）+ 铃鹿御前 8 卡 = 56 卡 + 召唤物 2（烬染不夜 10020299、烟烟罗的分身 10020499）；前 6 式神 date/best=20200327、铃鹿御前 date/best=20200520。萤草 100127 加 20200327 快照见经典包萤草节。）

## 不夜之火不录入说明

- **日霭相织（10020421，协战主牌，烟烟罗&日和坊）及烟影（10020451）/煦日（10020551）**：raw 已补效果文本，已建骨架（空效果，date=20200327），效果待实现。

## 不夜之火偏差与暂定清单

本批实现侧的 2 处偏差与 8 条暂定语义经维护者答复（thoughts.txt 10 条）全部定案，
现无悬挂项（结论即本节下文清单）：

- 偏差 2 处均已按定案改正消除：同心协力复制改"置入牌库"原版语义（generate position=random
  随机插入不洗牌，不再固定库底）；日出有曜改单目标双 step（clear_boosts 显式选牌手才生效、
  选式神空操作、无目标才回退控制者）。
- 暂定 8 条全部确认或改正：cancel_attack 不退费用（确认）；attack_replace 目标池含牌手 +
  伤害为非战斗伤害 kind=effect（确认/锁定）；inherit_stats=复制全部当前身材快照（改正）；
  mirror_spell 主动与自动使用均触发（改正）；battle_retarget 随机可含牌手（确认）；
  use_card_copy 不耗出击次数（确认）；气绝式神回合开始不充能（改正）；
  on_energy_gained 满上限照常发出 amount=0（改正）。

# 03 月夜幻响（20200624，首批 4 式神落地）

- 环境别名 `月夜幻响` = 20200624 已登记（db/envs.py）；包编号 `03_yueyehuanxiang` 已登记（db/packs.py）。
- card_data_raw 已预留 9 位式神名单：吸血姬（100301 红莲）、泷夜叉姬（100302 紫岩）、辉夜姬（100303 青岚，含衍生物 99 石钵）、荒（100304 青岚）、彼岸花（100305 红莲）、久次良（100306 紫岩）、山风（100307 苍叶）、孟婆（100308 青岚）、天井下（100309 紫岩，含衍生 51/52/99 妖怪屋系列）。**首批落地 4 位**：吸血姬/山风/孟婆/天井下（date/best=20200624，各 8 卡 + 天井下衍生 51/52/99）；其余 5 位（泷夜叉姬/辉夜姬/荒/彼岸花/久次良）随后续批次。
- **幻境机制未实现，本包幻境牌一律不录入**（机制未实现不进数据）；raw 中两张协战主牌 海潮深渊（久次良&蟹姬）/鸮羽共鸣（山风&薰）标注"未加入"（第二所属式神未引入），其子选项均为幻境牌，随包一并暂缓。
- 20200624 平衡性快照 2 张已入库：蛇行击（清姬 01，原占位日期 20251212 更正为 20200624，best 仍 20191212）、觉醒·铃鹿御前（使用效果投射 2→1，best 仍 20200520）。

## 吸血姬（100301）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_after_heal {target_side: friendly, target_kind: player} → buff_power 1 **perm: false**（thoughts(4) 定案：一次性持续性增益、气绝清除）+ gain_shield 1 |
| 01 血袭 | ✅ | 战斗 +0/+0，[吸血] |
| 02 血蝠之盾 | ✅ | grant_redirect 一次性伤害转移（ext["damage_redirects"]，类别不限定案）；[响应] on_before_assault {victim_side: friendly} 自动对其使用 |
| 03 血怒 | ✅ | [瞬发][吸血] 对敌方牌手 1 伤；[增强] = CardDef.triggers 游离块 on_after_heal {target_side: enemy, target_kind: player, card_in_hand} → add_mod damage_boost 累加；吸血姬受伤 → choose any_character 补 1 伤（答复(12) 定案） |
| 04 初拥 | ✅ | [瞬发] 1 伤 + delay_grant 双块（bind=chosen、scope=turn、uses=99）on_damage/on_player_damaged → heal {event: amount} 己方牌手（吸血限战斗伤害 kind: [combat, counter]、反击也算——答复(9) 定案） |
| 05 渴血之时 | ✅ | 形态 3/6，[吸血] |
| 06 血香 | ✅ | 战斗 +2/+1；@20200624 conditional_keywords player_health_ge 30 → [连击]（thoughts(3) 按 ≥ 判定）；@20200928 [增强]改为免疫战斗伤害——match_condition 新键 `player_health_ge` + battle_immunity step Step.condition（鸩羽条件免疫先例，raw"生命值为30"按 ≥30 口径） |
| 07 觉醒·吸血姬 | ✅ | +1/+1；觉醒能力 on_after_heal 同条件 → buff_power（perm: false）/gain_shield {event: amount, cap: 5} |
| 08 猩红之月 | ✅ | 形态 5/8 [吸血] + card_aura card_type=spell 授 lifesteal scope=form（法术伤害读卡牌关键字吸血） |

## 山风（100307）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | [倒计时3]：launch_attack + grant_keyword unyielding **scope=next_battle**（既定修正——倒计时块无战斗上下文，定案(6)） |
| 01 烈 | ✅ | 形态 3/4：on_countdown_proc {shikigami_shikigami: self} → buff_power/buff_health 1 perm（即时、先于归零块） |
| 02 迅 | ✅ | countdown_delta shikigami=100307 -2；[响应] 山风被攻击时自动使用并重复一次（合计 -4） |
| 03 势 | ✅ | 形态 3/6 [贯通]：on_countdown_reduced **timing: insert** → attack_buff power={"event": "original"}（定案(5) 按原始减少量） |
| 04 刚 | ✅ | 形态 3/8：on_countdown_proc → gain_shield 4 |
| 05 斩 | ✅ | 形态 3/8：on_countdown_proc → grant_keyword lethal scope=next_battle（范围=持续到该次战斗事件结束后、含期间插入的嵌套战斗——维护者改判，原"仅限该次攻击本身"答复(10) 作废，lethal 特判通道已删除、统一实例授予） |
| 06 突 | ✅ | countdown_delta {base: 2, countdown_holders: friendly_others, negate: true}（[增强]按其他倒计时式神数叠加）；过量 {memo: countdown_overkill} → buff_power/buff_health 非永久（定案(3)） |
| 07 岚 | ✅ | repeat {countdown_sum: true} 套 countdown_delta -1（X=全队当前倒计时总和） |
| 08 觉醒·山风 | ✅ | +1/+1；觉醒能力①[倒计时3] grant_immunity combat_damage scope=next_battle + launch_attack（免疫持续到该次战斗事件结束后、含期间插入的嵌套战斗——与斩范围一致，维护者改判统一）；②on_countdown_reduced {natural_not, shikigami_side: friendly, shikigami_not_shikigami: 100307} + trigger_when_defeated → 两步 countdown_delta {event: original, negate: true}（存活减倒计时/气绝 revive 减气绝倒计时）。**语义偏差（2026-08 二轮定案）**：raw 为"你的牌"，实现扩为任何己方减少倒计时效果（含在场能力来源）；无倒计时能力的未气绝式神被减少也发事件（actual=0）照样复制；回合开始批次自然减少（natural）不共享；复制延时界=引起该次减少的结算单元 |

## 孟婆（100308）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_player_damaged {source_shikigami: self} → remove_deck bottom 1 side=opponent（入 exiled 不进墓地） |
| 01 孟婆汤 | ✅ | choose 牌手（any_character 池代）→ remove_deck bottom 3 按 targets[0].player |
| 02 意外之喜 | ✅ | draw 2 + discard_pick 1（交互弃牌 pending_choice）；conditional_keywords enemy_deck_le 16 → [瞬发] |
| 03 天降之物 | ✅ | 形态 4/5：on_turn_end {active: self} → remove_deck bottom 1 side=self + side=opponent 两步 |
| 04 牙牙我们走 | ✅ | 形态 5/7 [贯通]；conditional_mods enemy_deck_le 16 → form_power_delta/form_health_delta +3 |
| 05 汤盆冲撞 | ✅ | 投射 4；conditional_mods enemy_deck_le 16 → double_damage（"护甲计算前1"翻倍） |
| 06 奈何桥头 | ✅ | 形态 4/6：on_card_played（延时）→ purge_copies side=event_player（card_id 缺省读事件；在场同名实体不受影响） |
| 07 觉醒·孟婆 | ✅ | +1/+2；觉醒能力同基础能力 count=5 |
| 08 忘忧的旋律 | ✅ | purge_named_card 两级交互（pending_choice kind="card_name"：选敌方式神→选牌名，作答键 choice） |

## 天井下（100309）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_turn_start/on_turn_end 双块 {active: self, hand_lacks: 10030951} → generate 灵力 |
| 01 骚声 | ✅ | [瞬发] choose {shield_nonzero: true} 任意角色 → strip_shield + add_mod shield_boost {memo: stripped_shield} 写 51/52 手牌实例 |
| 02 欢愉之音 | ✅ | 形态 3/5：tags [shield_gain_boost]（己方获得护甲+1/敌方获得破甲+1） |
| 03 遮雨 | ✅ | heal {"max_shield_or_fragile": true} 己方牌手 |
| 04 妖怪屋的醒转 | ✅ | choose {strippable: true} → strip_shield + summon 10030999 stats_memo="stripped_shield"（基础值口径、复活保留定案） |
| 05 破碎之音 | ✅ | 形态 6/5：on_before_defeat {victim_has_fragile, source_side: friendly} → damage 3 对 victim_player（触发时判目标有无破甲即可、不限仅直接消灭——答复(7) 定案） |
| 06 焕然之音 | ✅ | 形态 5/6：on_turn_end {active: self, friendly_armor_ge: 5} → draw 1 |
| 07 汇聚 | ✅ | [瞬发] choose 式神 → consolidate_shields（全场护甲/破甲代数和归集，目标自身原值不移除定案） |
| 08 觉醒·天井下 | ✅ | +2/+2；使用效果 transform_hand_card 51→52（原牌 exiled——答复(11) 确认、shield_boost 随牌转移）；觉醒能力双块 hand_lacks 10030952 → generate 之泉 |
| 51 妖怪屋·灵力 | ✅ | 衍生 token：多择两用法（基础=己方 1 护甲 / methods fragile=敌方 1 破甲）；triggers on_shield_changed {reason: turn_start_clear, gained: false, card_in_hand} 双情形 → shield_boost 累加 |
| 52 妖怪屋·灵力之泉 | ✅ | 衍生 token：全体己方 1 护甲 + 全体敌方 1 破甲；triggers 同 51 |
| 99 妖怪屋 | ✅ | 召唤物 1/1，先天[迅捷] |

## 泷夜叉姬（100302）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | 能力伪关键字 power_if_field（有幻境时 +1 力量，读取时求值；觉醒换绑通道登记） |
| 01 曜断 | ✅ | 战斗牌；conditional_keywords friendly_field → [瞬发] |
| 02 新月之哀 | ✅ | 幻境 耐久1 [瞬发]；能力 on_after_shield {victim_shikigami: self, kind: effect} → redirect_to_field（非战斗伤害改降此幻境耐久；块标 priority:1） |
| 03 日轮之城 | ✅ | 同构战斗伤害版（kind: combat；块标 priority:1） |
| 04 残阳无影 | ✅ | 战斗牌；进场 summon_field pick=choose（"选择召唤"真选择——pending kind field_summon_pick，候选>1 挂起、单只自动，CLI/net/超时随机均接入）；on_player_damaged {source_shikigami: self, player: opponent} → field_op pick=all 全幻境 +3 耐久 |
| 05 觉醒·泷夜叉姬 | ✅ | 觉醒牌 keywords 伪关键字换绑（power_per_field 每幻境 +1 力量）；能力 on_before_assault {attacker_shikigami: self, friendly_field} → grant_keyword initiative scope=battle |
| 06 月之奥义 | ✅ | 战斗牌；on_player_damaged {source_shikigami: self, player: opponent, kind: combat} → field_op side=enemy pick=max_intensity destroy（消灭敌方耐久最大幻境；帷幕候选排除） |
| 07 胧月无眠 | ✅ | 战斗牌；on_after_assault {attacker_shikigami: self, friendly_field} → field_op pick=random destroy 己方随机幻境 + auto_use 再次使用此牌（auto_use 战斗牌通道） |
| 08 永劫轮回 | ✅ | 形态；进场 summon_field shikigami=self pick=all（两个幻境全召唤）；能力双块按类别分代（均 priority:1）：on_after_shield {…, kind: combat} → redirect_to_field field_card=10030203（战斗伤害→日轮之城）/ {…, kind: effect} → field_card=10030202（法术伤害→新月之哀）；redirect_to_field 首个同名守卫（队列前缀已有同名牌则空操作） |

## 辉夜姬（100303）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_summon_field {player: self} + on_ability_enter {target_shikigami: self} 双挂点能力块 → field_merge（同名幻境合并：保留队列最后一个、耐久=总和走差量管线、其余走完整消灭流；伪关键字 field_stack 已作废） |
| 01 燕子安贝 | ✅ | 幻境 耐久5；①on_turn_end {active: self} → heal 全体己方 1 + field_op pick=others 其他幻境 +1；②敌方回合结束且 field_intensity_ge 10 再触发一次 |
| 02 火鼠裘 | ✅ | 幻境 耐久5；①on_player_damaged {player: self, kind: combat} → 来源式神 2 伤；②耐久≥10 on_damage {victim_kind: shikigami, 己方} → 来源式神 1 伤 |
| 03 五道难题 | ✅ | search_deck shikigami=self card_type=field + intensity_boost 5（入手实例 +5 耐久）；conditional_keywords deck_field_distinct_ge 5 → [瞬发] |
| 04 佛前石钵 | ✅ | 幻境 耐久5；on_turn_end {active: self, combat_empty: friendly} → summon 石钵；耐久≥10 追加 buff_power 4（对在场石钵，friendly_shikigami shikigami=10030399 池） |
| 05 龙首之玉 | ✅ | 幻境 耐久5；on_turn_end → projectile 2；耐久≥10 追加 enemy_bench 各 1 伤 |
| 06 觉醒·辉夜姬 | ✅ | 觉醒牌能力块带 merge_abilities: true（叠加时按牌 id 去重合并能力块，mods.merged_ability_ids 记账；伪关键字 field_ability_stack 已作废）；效果 {field_summon_distinct_ge: {count: 5, shikigami: self}} → summon_field pick=all intensity=1（五幻境各 1 耐久全召唤，候选按 id 升序，经 field_merge 合并入同一实体） |
| 07 蓬莱玉枝 | ✅ | 幻境 耐久5；on_turn_start → draw 1 + gain_orb 1；耐久≥10 双块"效果翻倍"（再来一份） |
| 08 竹取物语 | ✅ | 形态；on_turn_end → summon_field pick=random 随机召唤她的幻境；on_after_shield {victim_shikigami: self, friendly_field_intensity_ge: {ge: 20, shikigami: self}} → redirect_to_field field_shikigami=self max_amount=5，priority:1（条件限"她的"幻境耐久≥20，代受目标=首个她的幻境——已定案） |
| 99 石钵 | ✅ | 召唤物（佛前石钵衍生） |

## 荒（100304）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_damage {source_shikigami: self, kind: combat} → field_op pick=all 全幻境 +1 耐久 |
| 01 星轨 | ✅ | 幻境 耐久4，field_keywords [piercing]（幻境能力伤害贯通——_ability_piercing 并入 ctx.field.keywords）；on_turn_start {active: self} → damage {field_intensity: self} 投射 + field_op self_field destroy 自毁 |
| 02 荒海 | ✅ | 幻境 耐久1 [瞬发]；on_before_field_destroy {field_self} → field_rebound（回手并失去此能力——一次性回手标记） |
| 03 余辉 | ✅ | play_condition {hand_card_type: field}（手牌无幻境牌不可用——match_condition 新键）；discard shikigami=all card_type=field count=1 random_pick（空池安全空过）→ draw 3 |
| 04 星陨 | ✅ | 幻境 耐久4；on_turn_start {active: self} → repeat count={field_intensity: self} 套 damage 2 随机敌方角色 + field_op self_field destroy 自毁 |
| 05 星辰之境 | ✅ | 形态；stat_aura kind=field_count_stats power/health 1（每有一个幻境 +1/+1） |
| 06 觉醒·荒 | ✅ | 觉醒能力双块：基础同款（战斗伤害 → 全幻境 +1）+ on_card_played {card_type: field, player: self} → grant_keyword haste（使用幻境牌时荒得[迅捷]） |
| 07 月坠 | ✅ | 幻境 耐久15；on_before_field_intensity {field_self} → boost_change +2（"当此牌获得耐久时，效果+2"）；单块 on_turn_start {active: self} 三步：field_op +3 → destroy + damage 全体敌方 10 各带步级条件 field_intensity_ge 30（同块首次判定快照耐久，自毁归零后伤害步仍通过——仅"召唤并炸 3"一步判定，任意途径块已删，定案） |
| 08 命运螺旋 | ✅ | 形态；on_card_played {card_type: field, player: self} → grant_immunity scope=next_battle + launch_attack（免疫本次战斗伤害并发动攻击） |

## 彼岸花（100305）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | on_player_damaged {player: self, source_side: friendly} → 敌方牌手 1 伤（"己方伤害"=己方来源对己方牌手——自伤 source=己方牌手自身口径） |
| 01 赤团华 | ✅ | 形态；on_before_assault {attacker_side: friendly, attacker_kind: shikigami} → 彼岸花对己方牌手 1 伤 |
| 02 火照之路 | ✅ | 幻境 耐久8；on_summon_field {field_self} → card_aura level=1 授 [fast] + self_damage_on_play 1，scope=field（光环绑定来源幻境实体、离场失效） |
| 03 觉醒·彼岸花 | ✅ | 效果 双方牌手各 3 伤；觉醒能力 on_player_damaged {player: self, source_side: friendly} → projectile 1 |
| 04 花开彼岸 | ✅ | 形态 [迅捷]；on_damage {victim_shikigami: self} → 己方牌手受 {event: amount} 等量伤害 |
| 05 黄泉花境 | ✅ | 幻境 耐久4；on_field_intensity_changed {field_self, amount_le: -1} → basic_boost +2/+2（_le 后缀读事件 amount） |
| 06 死亡之花 | ✅ | choose any_shikigami（含己方，引燃先例）damage {enhance, base: 2}；conditional_mods self_damage_taken_ge 1 → enhance+1（ext self_damage_taken 记账，打出装配时求值） |
| 07 血华散 | ✅ | draw_until level_sum_ge 5（抽至所抽牌等级总和≥5）+ 己方牌手 5 伤 |
| 08 彼岸归航 | ✅ | 幻境 耐久10，field_keywords [deck_top_play]（牌库顶视同手牌使用、等级 1 不耗火、以此法使用受 2 伤——出牌管线 play_from=deck 通道） |

## 久次良（100306）

| 卡 | 状态 | 备注 |
|----|------|------|
| 基础能力 | ✅ | 能力伪关键字 power_if_shield（有护甲时 +1 力量） |
| 01 鲸骨·驻 | ✅ | 战斗牌 gain_shield 2 |
| 02 铃鹿山的守护 | ✅ | 幻境 耐久6；on_damage {victim_side: friendly, victim_kind: shikigami} → 受伤式神 gain_shield 1（context victim） |
| 03 白骨之盾 | ✅ | choose friendly_shikigami + exclude_shikigami=100306（"己方其他式神"排除久次良本人——TargetSpec 过滤新键，定案）→ gain_shield 4 + grant_keyword power_if_shield scope=turn；[响应] on_before_assault {victim_side: friendly, victim_kind: shikigami, victim_not_shikigami: 100306} 自动对其使用 |
| 04 鱼鳞之备 | ✅ | 形态；进场与 on_turn_start {active: self, friendly_field} → gain_shield 2 |
| 05 鲸骨·开 | ✅ | 战斗牌；buff_power/gain_shield amount={field_count: controller}（每幻境 +1 力量/+1 护甲） |
| 06 方圆之备 | ✅ | 形态（久次良得[帷幕]）；进场与 on_summon_field {player: self} → field_op pick=all grant_keyword veil（在场及后续幻境——帷幕已实现：field_op side=enemy 且 pick=first/max_intensity 时排除帷幕候选）；进场与 on_turn_start {friendly_field} → 全体己方式神 3 护甲 |
| 07 觉醒·久次良 | ✅ | 觉醒牌 keywords 伪关键字换绑 power_equal_shield（力量等同于护甲） |
| 08 铃鹿山的秘宝 | ✅ | 幻境，field_keywords [health_floor_one]（己方生命不降到 1 以下——伤害管线钳制） |

## 月夜幻响完结说明与暂定清单

- 03 月夜幻响包 9 式神全部完结（首批 4 + 本批 5），含 20 张幻境牌；幻境机制全链落地（队列/耐久/能力管线/叠加 field_merge/牌库顶使用/生命下限/帷幕取对象排除/伤害分层 priority）。
- 原暂定/报备口径 15 条已**全部定案落实**（2026-08，归档见 `questions.md` 本轮已落实节与 rules.md 第三十一章）：残阳无影真选择（field_summon_pick）、辉夜姬叠加 field_merge（耐久总和+觉醒按牌 id 去重合并能力块）、竹取物语首个她的幻境+条件 dict 形、月坠收窄为"召唤并炸 3"一步判定、余辉 play_condition 手牌幻境、白骨之盾排除本人、帷幕拦截落地、永劫轮回按类别分代+首个同名守卫、伤害分层 priority 字段、五道难题维持随机、星轨/星陨自毁与连续修饰审计合规。
- 牌手受伤事件接线：`on_player_damaged`（payload player=下标）+ `source_side: friendly/opponent`——彼岸花基础/觉醒、火鼠裘①、残阳无影/月之奥义 temp_grants 均按此；式神受伤才是 `on_damage`（victim=Ref）。

# 04 沧海刀鸣（20200928，7 个 wip 骨架 + 三目/人面树/樱花妖已落地）

除三目/人面树/樱花妖外的 7 式神以 wip 骨架入库（式神 yaml 标 `wip: true`，不进构筑可选池与测试卡组）：仅基础数据+卡面原文，效果一律未实现（空 steps，打出无效果）。三目（委托机制）、人面树、樱花妖已完整落地。

| 式神 | 派系 | raw 数据 | 备注 |
|------|------|----------|------|
| 01 人面树（100401） | 紫岩 | 完整 | **已落地**（rules.md 第三十四章）：8 卡全效果 + 51 诅咒之木——扎根 tags no_retreat（形态不移回）、神木诅咒 switch_form 形态切换 + 结附期派系临时覆写（faction_override）、神木庇佑 combat_base_health（以生命造战斗伤害）、灾厄之花 delay_grant bind=chosen + {health_of: self}、凋零之森幻境 active_character 池 + {half_health_of: target} 逐目标、觉醒 power_eq_health（力量=生命覆写） |
| 02 跳跳哥哥（100402） | 红莲 | 仅卡名 | 8 卡默认骨架（spell/1级/R，text 空）+ 51 棺葬协战子卡骨架 |
| 03 樱花妖（100403） | 紫岩 | 完整 | **已落地**（rules.md 第三十四章）：8 卡全效果 + 51 落英缤纷/52 晚樱之意协战子卡——气绝转化伪关键字 heal/damage_defeated_countdown（觉醒换绑双通道，按结算时能力在场判定且分侧向）、绽放 mass_revive（复活+倒计时造伤）、樱吹雪敌我同池单波 any_shikigami+include_defeated + repeat_on_kill/repeat_on_revive 整波重复（伤害波全部重复完才进治疗波）、落英缤纷⇄晚樱之意 event_base_power 次数 + turn_mark 门控 + switch_form 互切 + 羁绊（friendly_injured+include_player 含牌手）、飘零之舞 assault_any_target/friendly_combat_heal |
| 04 三目（100404） | 紫岩 | 完整 | **已落地**（委托机制，rules.md 第三十三章）：基础能力（开局/使用紧急委托随机生成）+ 8 卡全效果 + 衍生牌 51-66（紧急委托×4 条件增益/今日委托×7 每日替换/线索×5 觉醒选择生成不可重复） |
| 05 薰（100405） | 紫岩 | 仅卡名 | 8 卡默认骨架 + 51 鸮鸣协战子卡骨架 |
| 06 食梦貘（100406） | 紫岩 | 仅卡名 | 8 卡默认骨架 |
| 07 御馔津（100407） | 青岚 | 仅卡名 | 8 卡默认骨架 |
| 08 大岳丸（100408） | 红莲 | 仅卡名 | 8 卡默认骨架 + 51 琼玉镇海协战子卡骨架 |
| 09 鬼切（100409） | 青岚 | 仅卡名 | 8 卡默认骨架 |
| 10 巫蛊师（100410） | 紫岩 | 仅卡名 | 8 卡默认骨架 |

- 仅卡名式神身材占位 2/5（yaml 注释标明待 raw 补充）。
- 协战牌补齐：海国共主 10020721 / 鸮羽共鸣 10030721 / 繁花似锦 10011921 三本体现均已入库；落英缤纷 10040351（+晚樱之意 10040352）已随樱花妖落地；子选项 琼玉镇海 10040851 / 鸮鸣 10040551 / 棺葬 10040251 仍为骨架——三者 raw 均无文本（标未加入），text 留空待补；花骸缚骨/海潮深渊本体仍不建（raw 无荒骷髅/蟹姬条目）。
- 委托牌无稀有度与衍生牌 16 张/诅咒之木号段已定案（衍生牌不标稀有度、51-66 十六张、诅咒之木 99→51）。

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
    森佑灵矢主牌已齐备（森佑灵引的[庇佑]与牌库检索直接使用形态均已实现）。

11. **爆牌统一路径**：手牌上限检查落在 move_card——抽牌、生成置入手牌、调度换牌等所有
    进手路径共用同一爆牌流程（超出 hand_cap 的牌转而置入墓地）——维护者定案。
12. **夺命变后与墨笔夺魂**：destroy 支持牌手目标（消灭牌手 = 直接获胜，走牌手气绝判负
    流程）；buff_health 负值下调上限时同步钳当前生命，上限 ≤0 走气绝——维护者定案。
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
    （维护者定案）；text 按 raw 逐字。
21. **调度/牌库拿牌隐含检索洗牌**：强索、青灯夜谈的 20191212 文本无"洗牌库"字样，
    但调度与非抽牌的牌库拿牌都隐含检索（维护者答复(7)(8)，早期文本未显式写明）——
    text 按 raw 逐字，行为照常洗牌（与森佑灵引出入 14 同一定案）。

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
  - 冰霜永冻 = 10012121（雪女 100121 < 雪童子 100122）；子选项 冰封 = 10012152（已入库）、雪刃 = 10012251（幻境机制已落地，卡牌未录入）
  - 跳跳兄弟 = 10012021（跳跳弟弟 100120 < 跳跳哥哥 100402）；主牌与子选项 尸瘴 = 10012051（幻境机制已落地，卡牌未录入）仍暂缓；副侧子选项 棺葬 = 10040251 已随 04 包建骨架（text 待 raw）
  - 日霭相织 = 10020421（烟烟罗 100204 < 日和坊 100205）；主牌与子选项 烟影 = 10020451、煦日 = 10020551 均已建骨架（空效果）
  - 海国共主 = 10020721（铃鹿御前 100207 < 大岳丸 100408）；主牌与子选项 裂甲归潮 = 10020751、琼玉镇海 = 10040851 均已建骨架（空效果；琼玉镇海 text 待 raw）
  - 花骸缚骨 = 10030521（彼岸花 100305 < 荒骷髅——raw 未见其条目，id 未定）；子选项 黄泉永劫 = 10030551 已建骨架
  - 海潮深渊 = 10030621（久次良 100306 < 蟹姬——raw 未见其条目，id 未定）；子选项 鲸甲引潮 = 10030651 已建骨架
  - 鸮羽共鸣 = 10030721（山风 100307 < 薰 100405）；主牌与子选项 庇羽 = 10030751、鸮鸣 = 10040551 均已建骨架（空效果；鸮鸣 text 待 raw）
  - 繁花似锦 = 10011921（桃花妖 100119 < 樱花妖 100403）；主牌已入库，子选项 桃红簇簇 = 10011951、落英缤纷 = 10040351（与切换形态 晚樱之意 = 10040352 互切）均已落地
- 主牌均须等两位所属式神都已引入才能进 db（loader 校验 shikigami2 存在）；
  剩余主牌待子选项机制：涅槃明灯（烛火重燃）、冰霜永冻（雪刃）、跳跳兄弟（主牌/尸瘴未录入）；森佑灵矢已齐备。
