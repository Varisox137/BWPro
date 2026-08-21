"""运行时扩展键与数据白名单的集中登记表（规则设计评审 ②③ 落地）。

四类登记：

1. ``EXT_KEYS`` —— ext 半回合/跨回合记账键登记表：`ShikigamiState.ext` /
   ``PlayerState.ext`` 的约定键 → （宿主, 清除时机）。引擎在相应边界统一自动清除
   （``Game._clear_ext``），各 op/引擎角落不再手写 pop（有副作用的键挂清除钩子，
   同模块按名分派）。新 ext 键必须先在此登记（并在 docs/terminology.md 同步）。

2. ``CONDITION_KEYS`` —— 条件迷你语言判定键白名单（``targets.match_condition``
   消费全集 + 事件字段等值键 + 幻境/卡牌收集器专用键）。loader 对效果块
   condition / Step.condition / play_condition / conditional_mods / force_x1_if
   统一校验，未登记键直接报错（杜绝 yaml 笔误静默恒假）。

3. ``TARGET_EXTRA_KEYS`` —— TargetSpec 的 model_extra 过滤/行为键白名单
   （core/targets.py 与 engine 出牌校验消费）。

4. ``DYNAMIC_VALUE_KEYS`` / ``COUNT_VALUE_KEYS`` —— 步骤数值参数字典的
   运行时引用键白名单（``Game._step_amount`` 的 amount/power 通道与
   次数参数（count/times）通道分表）。
"""
from __future__ import annotations

# ---------- ext 键清除时机 ----------
CLEAR_OWN_TURN_START = "own_turn_start"    # 己方回合开始
CLEAR_ANY_TURN_START = "any_turn_start"    # 任一回合开始（半回合作用域，双方清除）
CLEAR_OWN_TURN_END = "own_turn_end"        # 己方回合结束
CLEAR_ON_DEFEAT = "on_defeat"              # 式神气绝（仅式神宿主）
CLEAR_FORM_LEAVE = "form_leave"            # 绑定形态离场（_destroy_form 通道）
CLEAR_CONSUME = "consume"                  # 消费点取用即清（无边界清除）
CLEAR_RECOMPUTE = "recompute"              # 缓存通道（每次刷新全量重算覆盖）
CLEAR_NEVER = "never"                      # 本局保留（跨回合/跨气绝不清）

# 键名 → (宿主 "shikigami"|"player", 清除时机)。有副作用的清除（扣减/级联/重置/
# 过滤）由引擎按键名挂钩子；时机为 consume/recompute/never 的键不参与边界自动清除。
EXT_KEYS: dict[str, tuple[str, str]] = {
    # ---- 式神宿主 ----
    "spell_echo": ("shikigami", CLEAR_OWN_TURN_START),        # 法术回响序列（涅槃业火）
    "turn_power": ("shikigami", CLEAR_OWN_TURN_START),        # 钩子：同步扣 temp_power
    "min_health_turn": ("shikigami", CLEAR_ANY_TURN_START),   # 狂啸生命下限
    "move_count_turn": ("shikigami", CLEAR_ANY_TURN_START),   # 本回合 [移动] 次数
    "damage_taken_turn": ("shikigami", CLEAR_ANY_TURN_START),  # 本回合所受伤害之和
    "dealt_damage_turn": ("shikigami", CLEAR_ANY_TURN_START),  # 记仇过滤键
    "power_zero_turn": ("shikigami", CLEAR_ANY_TURN_START),   # 钩子：级联清 power_zero
    "power_zero": ("shikigami", CLEAR_ON_DEFEAT),             # 力量覆写；形态离场另清
    "recorded_card": ("shikigami", CLEAR_ON_DEFEAT),          # 大天狗记录法术
    "next_battle_keywords": ("shikigami", CLEAR_ON_DEFEAT),   # 战斗开始消费 + 气绝清
    "next_battle_immunities": ("shikigami", CLEAR_ON_DEFEAT),
    "damage_redirects": ("shikigami", CLEAR_ON_DEFEAT),       # 血蝠之盾转移挂账
    "dice_force_six_once": ("shikigami", CLEAR_CONSUME),      # 投掷时消耗
    "dyn_power": ("shikigami", CLEAR_RECOMPUTE),              # 动态身材光环缓存
    "dyn_health": ("shikigami", CLEAR_RECOMPUTE),
    "max_power": ("shikigami", CLEAR_NEVER),                  # 力量历史峰值（断臂）
    "zhen_proc": ("shikigami", CLEAR_NEVER),                  # 鸩倒计时能力计数
    "yaohu_dmg_bonus": ("shikigami", CLEAR_NEVER),            # 聚气永久加成
    "replace_owner": ("shikigami", CLEAR_NEVER),              # 替换物原式神 id
    "energy_life_substitute": ("shikigami", CLEAR_NEVER),     # 能量生命代偿标记
    "fragile_to_damage": ("shikigami", CLEAR_NEVER),          # 破甲转化标记（bump_ext）
    "fragile_to_damage_if": ("shikigami", CLEAR_NEVER),
    "coffin_on_defeat": ("shikigami", CLEAR_ANY_TURN_START),  # 不弃旗标："本回合气绝时
    # 替换为棺材"（值 = 棺材实体数据 id，bump_ext 写入；气绝流程末尾消费）
    "defeated_in_combat": ("shikigami", CLEAR_ON_DEFEAT),     # 本次气绝时是否在战斗区
    # （check_defeated 重写；to_coffin keep_combat 消费——棺封对战斗区式神=棺材进战斗区）
    "no_damage_vs_inv": ("player", CLEAR_ANY_TURN_START),     # 干扰投掷禁伤（定案(7)
    # 结附己方牌手的一回合效果）：append 列表条目 {"value": 灵咒名, "ref": [pi, 座次]}，
    # 该式神（气绝/复活不丢失）对结附指定灵咒的式神造成的伤害无效（伤害管线早期终止）
    # ---- 牌手宿主 ----
    "feather_used_turn": ("player", CLEAR_OWN_TURN_START),    # 黄金羽本回合计数
    "turn_marks": ("player", CLEAR_ANY_TURN_START),           # 每回合合计一次标记表
    "energy_free_turn": ("player", CLEAR_ANY_TURN_START),     # 钩子：重置为 True
    "cost_mods": ("player", CLEAR_ANY_TURN_START),            # 钩子：按回合号过滤
    "stuns": ("player", CLEAR_OWN_TURN_END),                  # 钩子：过期条目移除
    "turn_keyword_grants": ("player", CLEAR_OWN_TURN_END),    # 钩子：scope=turn 过滤
    "stat_auras": ("player", CLEAR_FORM_LEAVE),               # scope=form 条目随形态离场
    "boost_flags": ("player", CLEAR_FORM_LEAVE),              # 同上（鼓舞扩展旗标）
    "dice_force_six": ("player", CLEAR_FORM_LEAVE),           # 萌即正义（形态绑定）
    "dice_force_six_holder": ("player", CLEAR_FORM_LEAVE),
    "boost_keyword": ("player", CLEAR_CONSUME),               # 鼓舞随机关键字槽
    "feather_used_game": ("player", CLEAR_NEVER),
    "lianmo_used_game": ("player", CLEAR_NEVER),
    "snowball_used_game": ("player", CLEAR_NEVER),
    "self_damage_taken": ("player", CLEAR_NEVER),
    "yaohu_damage_count": ("player", CLEAR_NEVER),
    "field_summon_ids": ("player", CLEAR_NEVER),
    "countdown_history": ("player", CLEAR_NEVER),
    "enemy_stunned_game": ("player", CLEAR_NEVER),
    "dice_history": ("player", CLEAR_NEVER),
    "dice_six_count": ("player", CLEAR_NEVER),
    "luck_success_game": ("player", CLEAR_NEVER),
    "luck_success_turn": ("player", CLEAR_NEVER),             # 回合号比对，不清除
    "gen_replace": ("player", CLEAR_NEVER),                   # 重复登记覆盖
    "energy_assault": ("player", CLEAR_NEVER),
    "form_death_play": ("player", CLEAR_NEVER),
    "quest_clues_seen": ("player", CLEAR_NEVER),              # 本局已获得过的线索 id（觉醒·三目"不可重复"）
    "last_attacker": ("player", CLEAR_OWN_TURN_START),        # 薰攻击账本：本回合最后一个
    # 攻击（主动出击/战斗牌）的己方式神座次；己方回合结束由能力读取（context 目标
    # 键 last_attacker），账本空则无事
    "inv_mod": ("player", CLEAR_NEVER),                       # 灵咒数值修饰表（八尺琼曲玉；
    # 条目 {"name","shikigami"?,"add","mult"}，engine._refresh_invocation_mods 重算条目 mod 层；
    # scope="ability" 条目随来源式神能力离场经 _clear_ability_card_auras 清除——大岳丸
    # 基础/觉醒能力，进场经 on_ability_enter 块登记）
    "inv_bonus_on_kill": ("player", CLEAR_NEVER),             # 结附灵咒击杀加成规则表
    # （觉醒·大岳丸使用时赋予牌手：条目 {"inv","add"}，可叠加；触发钩子在
    # check_defeated 击杀账本段——击杀者身上该灵咒条目 bonus += add）
    "inv_override": ("player", CLEAR_NEVER),                  # 灵咒结附覆写表（祈愿之翼；
    # {灵咒名: {"unique": 覆写级别, "attach_all_friendly": bool}}，attach/唯一性判定读取）
    "talisman_ledger": ("player", CLEAR_NEVER),               # 奉祝之愿账本（裁决10）：
    # 本局使用过的符咒类型 id 列表（按使用顺序、去重、至多 3 种；_account_card_played
    # 记账，cast_ledger op 读取）
    "inv_attach_bonus": ("player", CLEAR_NEVER),              # 结附灵咒数量增幅规则表
    # （觉醒·巫蛊师使用时赋予牌手：条目 {"name","add"}，可叠加；engine.attach_invocation
    # 按来源牌手读取叠加——裁决13 仅'结附'动作触发）
    "inv_transfer_on_defeat": ("player", CLEAR_ANY_TURN_START),  # 魔蛊毒爆转移
    # （牌手级半回合能力：{"victim": [pi, si], "inv": 灵咒名}；消耗点 =
    # check_defeated 气绝事件后一次性等量转移，裁决14）
    "crit_pierce_mark": ("shikigami", CLEAR_ANY_TURN_START),  # 破魔符标记（本回合
    # "对其造成伤害的式神或卡牌获得[暴击][贯通]"——不可叠加幂等；伤害事件
    # "造成/受到伤害开始时"按受伤者标记置位事件属性，裁决(4)）
    "defeat_on_damage": ("shikigami", CLEAR_ANY_TURN_START),  # 驱魔符标记（本回合
    # "受到伤害时使其气绝"；伤害管线扣减生命后入气绝队列，同必杀通道）
    "drew_invocation_turn": ("player", CLEAR_ANY_TURN_START),  # 惊梦账本（本回合
    # 该牌手抽到过结附灵咒的牌）：灵咒名列表，_proc_invocations_on_move 触发时记账；
    # enemy_drew_invocation 条件键读取
}

# ---------- 条件迷你语言键白名单 ----------
# 显式算子键（targets.match_condition 的具名分支）+ 收集器专用键
# （field_self/field_intensity_ge 由 _collect_fields 消费，card_in_hand 由
# _collect_card_triggers 消费）+ 事件字段等值键（含通用后缀家族的具名实例：
# _side/_kind/_shikigami/_not_shikigami/_not/_has_fragile/_stunned/_ge/_le）。
CONDITION_KEYS: frozenset[str] = frozenset({
    # —— 显式算子（match_condition 具名分支）——
    "active", "player_ext", "turn_mark_not", "turn_count_eq", "orb_ge",
    "assaults_left_ge", "assaults_left_le",
    "combat_empty", "combat_occupied", "friendly_defeated_exists",
    "player_health_le", "player_health_ge", "player_missing_health_ge",
    "shikigami_in_combat", "shikigami_active", "shikigami_has_form",
    "card_transformed", "dice_six_ge", "dice_distinct_ge",
    "luck_success_total_ge", "dice_below_x", "victim_lethal", "victim_in_combat",
    "holder_defeated", "holder_has_form", "energy_ge",
    "hand_has", "hand_lacks", "enemy_deck_le", "friendly_armor_ge",
    "friendly_field_intensity_ge", "field_summon_distinct_ge", "friendly_field",
    "hand_card_type", "chosen_stunned", "chosen_has_fragile", "chosen_side",
    "combat_opponent_stunned", "kill_count_ge",
    "quest_count_ge",
    "invocation_on_field", "shikigami_countdown_free",
    "holder_has_invocation",  # 能力持有者结附指定灵咒（棺击"持有'迟钝'期间"门控）
    "victim_has_invocation",  # 事件 victim 结附指定灵咒（干扰投掷响应条件；
                              # _has_invocation 通用后缀的具名实例）
    "attacker_has_invocation",  # 事件 attacker 结附指定灵咒（鸮鸣"己方具'鸮之守护'
                                # 的式神发起攻击"=攻击者本人结附；通用后缀具名实例）
    "from_coffin_not",  # 气绝事件非棺材击破来源（棺葬门控——棺材被击破的气绝
                        # 事件携带 from_coffin=True，不再触发变棺；_not 通用后缀）
    "victim_invocation",  # 事件 victim_invocations 快照含指定灵咒（无尽蛊/食魂蛊
                          # "结附'蛊蚀'的敌方式神气绝时"；_invocation 通用后缀实例）
    "holder_in_combat",  # 能力持有者视同处于战斗区（鬼斩"处于战斗区时"门控）：
                         # 持有者方战斗区座次==持有者，或持有者持 virtual_combat
                         # 伪关键字（复仇之刃视同）
    "enemy_drew_invocation",  # 对方牌手本回合抽到过结附指定灵咒的牌（惊梦瞬发条件）；
                              # 读取对方 ext["drew_invocation_turn"] 账本
    # —— 收集器专用（不进 match_condition 按键循环）——
    "card_in_hand", "field_self", "field_intensity_ge",
    # —— 事件字段等值/通用后缀具名实例（现行数据全集）——
    "player", "kind", "card_type", "subtype", "reason", "shikigami",
    "card_id", "invocation",
    "dice", "judge", "gained", "old", "in_combat", "summon",
    "golden_feather", "card_revealed", "pre_play_form",
    "attacker_side", "victim_side", "source_side", "target_side", "shikigami_side",
    "attacker_kind", "victim_kind", "source_kind", "target_kind",
    "attacker_shikigami", "victim_shikigami", "source_shikigami",
    "target_shikigami", "shikigami_shikigami",
    "attacker_not_shikigami", "victim_not_shikigami", "shikigami_not_shikigami",
    "kind_not", "shikigami_not", "subtype_not", "natural_not",
    "defender_has_fragile", "victim_has_fragile", "victim_stunned",
    "amount_ge", "overheal_ge", "yaohu_damage_count_ge", "self_damage_taken_ge",
    "amount_le",
})

# CardDef.conditional_keywords 条目键白名单（engine._card_keywords 消费）
CONDITIONAL_KEYWORD_KEYS: frozenset[str] = frozenset({
    "keyword",  # 条目授予的关键字（必含）
    "level_ge", "if_alive", "combat_nonempty", "enemy_stunned_nonempty",
    "enemy_hand_all_revealed", "enemy_fragile_ge2", "player_health_ge",
    "enemy_deck_le", "shikigami_has_form", "friendly_field",
    "deck_field_distinct_ge", "dice_six_ge",
    "invocation_on_field",  # 场上有己方式神结附指定灵咒（麓鸣·穿条件[瞬发]）
    "enemy_drew_invocation",  # 对方牌手本回合抽到过结附指定灵咒的牌（惊梦[瞬发]）
})

# TargetSpec model_extra 键白名单（targets._spec_filtered / resolve /
# engine 出牌校验 消费；kind/pool/key 为 schema 声明字段不在此列）
TARGET_EXTRA_KEYS: frozenset[str] = frozenset({
    "random", "memo", "include_defeated", "power_le", "has_fragile", "stunned",
    "dealt_damage_turn", "keyword", "highest_power", "shield_nonzero",
    "strippable", "exclude_shikigami", "shikigami", "exclude_victim",
    "optional",  # choose 目标可空（无合法目标则无目标结算，天翔鹤斩）
    "battle",    # 选择目标进战斗区（engine._resolve_combat_card 换目标通道）
    "no_form",   # 仅无形态的式神（今日委托·伍"消灭一个没有形态的式神"）
    "has_form",  # 仅有形态的式神（神木诅咒"使一个形态变成…"取对象口径）
    "prefer_wounded",  # 候选中优先受伤（生命<上限）或气绝式神：存在则收窄到该子集
                       # （晚樱之意"优先受伤或气绝式神"；配合 include_defeated 纳入气绝者）
    "include_player",  # friendly_injured 池追加受伤的己方牌手（"己方受伤角色"含牌手，
                       # 维护者答复(4)；落英缤纷羁绊）
    "has_invocation",  # 结附指定灵咒的式神（值 = 灵咒名，或 {"name": 灵咒名,
                       # "same_source": true} 同源限定 = 结附来源所属牌手为控制者；
                       # 决意"你结附'鸮之守护'的式神"用同源限定；牌手目标被滤除）
    "chosen_index",    # step 目标 {kind: choose, chosen_index: n}：多选择目标卡牌
                       # （CardDef.target2）按序取第 n 个选择目标（麓鸣·灭双 choose）
    "exclude_chosen",  # 排除卡牌选择目标（增殖"使其他结附'蛊蚀'的敌方式神"——
                       # 主目标不重复结算）
    "include_defeated_kw",  # 气绝入池门控（樱花妖定案(2)）：己方气绝入池 iff 在场
                       # heal_defeated_countdown、敌方气绝入池 iff 在场
                       # damage_defeated_countdown；spec_pool_refs/resolve 同口径
    "not_summon",      # 仅非召唤物式神（选择目标合法性即排除召唤物——不弃
                       # "使一个非召唤物式神"，维护者定案(12)；牌手目标被滤除）
    "power_eq",        # 力量恰等于 n（缚蝶蛊狱"消灭所有力量为0的式神"；
                       # 牌手目标被滤除）
})

# 步骤数值参数字典（amount/power）白名单：Game._step_amount 消费全集
DYNAMIC_VALUE_KEYS: frozenset[str] = frozenset({
    "base", "per", "negate",
    "enhance", "burst_x", "memo",
    "shield_of", "fragile_of", "half_shield_of", "power_of", "perm_power",
    "ext", "event", "cap", "half", "half_health_of", "health_of", "orb",
    "max_power_gap", "missing_health", "countdown_holders",
    "max_shield_or_fragile", "hand_count_half",
    "field_intensity", "field_count",
    "dice_distinct", "enemy_stunned_count", "enemy_revealed_count",
    "kill_count",  # 击杀账本查询（{kill_count: {shikigami: id}|{scope: player}}）
    "victim_invocation_count",  # 事件 victim_invocations 快照中指定灵咒条目数
                                # （食魂蛊"其上每有一个'蛊蚀'"，配 per 倍率）
    "deck_invocation_count",  # 指定侧牌库中结附指定灵咒的牌数（食梦貘"牌库中
                              # 每有一张'梦魇'"）：{"deck_invocation_count": {"name": 灵咒名,
                              # "side": "self"|"enemy"}}
})

# 次数参数字典（count/times）白名单：draw/generate/repeat/deck_top_pick/
# 风符·龙等 op 的次数通道消费全集
COUNT_VALUE_KEYS: frozenset[str] = frozenset({
    "base", "memo", "ext", "mod", "orb", "countdown_sum", "field_intensity",
    "hand_to",
    "event_base_power",  # 事件 Ref 所指式神的当前基础力量（落英缤纷/晚樱之意
                         # "重复该式神基础力量的次数"；{"event_base_power": "shikigami"}）
})
