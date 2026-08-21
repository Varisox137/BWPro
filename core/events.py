"""事件体系。

核心事件在此登记；DIY / 自定义事件在 db/events.yaml 中声明，
由动作 {op: emit, event: <name>} 触发。校验器只接受两处并集内的事件名，
但事件总线本身按名字分发——新增事件不需要改动引擎代码。

时机分类（thoughts.txt：能力的触发与执行分开）：
- 即时时机：有临时队列——同时机能力全部触发完毕后，依次执行。如"（被）攻击时"。
- 延时时机：没有自己的队列——触发的能力加入当前效果的队列，该效果结算完后执行。
  如"造成伤害后"、"回合开始时"。
EVENT_TIMING 登记各事件的默认类别；EffectBlock.timing 可为单卡覆盖（None = 跟随默认）。
"""

CORE_EVENTS: frozenset[str] = frozenset({
    "on_game_start",        # 对局开始（游戏开始阶段能力，0 级式神也可触发）
    "on_ability_enter",     # 能力进场（对局开始/升至 1 级/复活/觉醒替换/变形还原）{player, shikigami, target: Ref}
    "on_turn_start",        # 任一玩家回合开始 {player}
    "on_turn_end",          # 任一玩家回合结束 {player}
    "on_card_played",       # 卡牌使用后 {player, uid}
    "on_before_assault",    # 出击宣言后、伤害结算前 {attacker: Ref, victim: Ref}
    "on_after_assault",     # 出击结算完毕 {attacker: Ref}
    "on_battle_end",        # 战斗结束后 {attacker: Ref, battle}（裁决(10)：战斗被取消/过早终止则不发；不入 EVENT_TIMING = 延时队列时机）
    "on_damage",            # 式神受到伤害后 {victim: Ref, amount, source, kind}
    "on_player_damaged",    # 牌手受到伤害后 {player, amount, source, kind}
    "on_shikigami_defeated",  # 式神气绝（气绝后/消灭后，延时时机）{victim: Ref, source, reason}
    "on_shikigami_revived",  # 式神复活（复活后，延时时机）{shikigami: Ref, source, reason}
    "on_draw",              # 抽牌后 {player, count}（整次抽牌动作一次，延时时机）
    "on_before_draw",       # 抽牌前（每张一次）{player, count（剩余抽取数）, reason}
    #                       （即时时机；"获得卡牌前"锚点——灵咒框架预留挂点）
    "on_card_move",         # 牌移动后（即时时机）{player, uid, card,
    #                       from_zone, to_zone, reason}（灵咒框架预留挂点）
    "on_card_moved",        # 牌移动后（延时时机）{player, uid, card,
    #                       from_zone, to_zone, reason}（灵咒"抽到触发"等挂点）
    "on_invocation_attached",  # 灵咒结附后（延时时机）{player（来源所属牌手）,
    #                       target: Ref|None, uid: int|None, invocation（灵咒名）, source}（预留）
    "on_invocation_drawn",  # 抽到结附灵咒的牌后 {player（抽牌者）, card, invocation（灵咒名）,
    #                       source_player（灵咒来源牌手）}（延时时机；梦魇三监听挂点）
    "on_invocation_trigger",  # 灵咒能力触发宣告 {player（持有者方）, invocation（灵咒名）,
    #                       holder: Ref, target: Ref|None}（即时时机；鬼斩响应挂点）
    "on_upgrade",           # 式神升级 {player, shikigami, level}
    "on_trigger",           # 响应牌触发 {player, uid}
    "on_summon",            # 召唤物进场 {shikigami: Ref}
    "on_form_attached",     # 形态牌结附 {player, shikigami, uid}
    "on_form_destroyed",    # 形态牌消灭 {player, shikigami, uid, reason}
    "on_shield_changed",    # 式神/牌手护甲或破甲数值变化后 {target: Ref, old, new, reason}
    "on_stun",              # 角色被眩晕后 {victim: Ref, source}（雪女"当你眩晕敌方式神时"）
    "on_orb_changed",       # 鬼火变化 {player, old, new, reason}
    "on_assaults_changed",  # 出击次数变化 {player, old, new, reason}
    # ---- 伤害事件时点批次（docs/rules.md 第五章；payload 含 damage 可变对象，监听者可改伤害值）----
    "on_before_damage",   # 造成伤害前 {damage, victim, source, amount, kind}（批次0=穿刺，引擎内建）
    "on_damage_start",      # 造成/受到伤害开始时 {damage, victim, source, amount, kind}
    "on_before_shield",     # 护甲计算前 {damage, victim, source, amount, kind}（批次3=屏障，引擎内建）
    "on_after_shield",      # 护甲计算后 {damage, victim, source, amount, kind}
    "on_before_health",     # 扣减生命前 {damage, victim, source, amount, kind}（此后伤害值锁定）
    "on_before_awaken",     # 觉醒前（能力替换前）{player, shikigami, uid}
    "on_awakened",          # 觉醒后（能力替换与法术本身效果结算后）{player, shikigami, uid}
    "on_before_heal",       # 治疗前 {target: Ref, amount, source, reason}
    "on_heal",              # 治疗时 {target: Ref, amount（实际治疗量）, source, reason}
    "on_after_heal",        # 治疗后 {target: Ref, amount, source, reason}
    "on_before_defeat",     # 气绝前/消灭前 1 {victim: Ref, source, reason, battle}
    "on_before_card_play",  # 使用手牌前 {player, uid, card, card_type, shikigami,
    #                       nullified（可变标记 dict）}
    "on_card_enter_hand",   # 一张牌进入手牌 {player, uid, card}（"已展示"机制入手统一钩子）
    "on_enter_combat",      # 式神进入战斗区 {player, shikigami: Ref}（延时时机）
    "on_leave_combat",      # 式神离开战斗区 {player, shikigami: Ref}（延时时机；气绝移动不发）
    "on_energy_gained",     # 式神获得能量后 {player, target: Ref, old, new, amount（实际获得量）}
    #                       （延时时机；[充能]批次与 gain_energy 统一发点，烟烟罗类触发挂载）
    # ---- 幻境事件（幻境机制；发点见 core/engine.py 幻境管线）----
    "on_summon_field",    # 召唤幻境后 {player, field（队列下标）, card_id, source, reason}
    #                       （延时时机；辉夜姬基础/觉醒能力、[融合]机制等挂点——预留）
    "on_before_field_intensity",  # 幻境耐久变化前 {player, field, card_id,
    #                       change（可变 dict：amount）, old, source, reason}
    #                       （即时时机；荒"月坠"等挂点——监听者可改 change["amount"]）
    "on_field_intensity_changed",  # 幻境耐久变化后 {player, field, card_id,
    #                       old, new, amount（实际变化量，带符号）, source, reason}
    #                       （延时时机；荒"月坠"/彼岸花"黄泉花境"等挂点）
    "on_before_field_destroy",  # 幻境消灭前 {player, field, card_id, source, reason}
    #                       （延时时机；不见岳各幻境等挂点——触发时幻境仍在队列中）
    "on_field_destroyed",  # 幻境消灭后 {player, card_id, source, reason}
    #                       （延时时机，预留；发出时幻境已出队）
    # ---- 倒计时事件（月夜幻响批次；发点见 core/engine.py 倒计时框架与 countdown_delta）----
    "on_countdown_proc",    # 倒计时能力归零生效时 {shikigami: Ref, source（来源 id）, once}
    #                       （即时时机：先于归零效果块结算，烈/刚/斩类"当触发[倒计时]能力时"，
    #                       其增益赶上归零块发起的攻击）
    "on_countdown_reduced", # 倒计时减少时 {shikigami: Ref, original（原始减少量）,
    #                       actual（实际减少量=修正到剩余）, by_card（是否卡牌效果）,
    #                       natural（回合开始批次自然减少标记——非"效果"，山风复制不共享）}
    #                       （每次减少动作发一次；未气绝但无倒计时能力的目标也发
    #                       actual=0——减少效果对其仍算"生效"，2026-08 定案；延时时机——
    #                       觉醒·山风共享监听按"引起该次减少的结算单元完毕后"结算
    #                       （horizon 单元 drain），势类用 timing: insert 覆盖为即时）
    # ---- 运势事件时点（thoughts.txt 运势事件流程，core/engine.py 运势管线）----
    "on_luck_judge",        # 运势判定时 {luck（可变事件 dict）, judge, source, x, dice}（座敷童子重投）
    "on_luck_success",      # 运势判定后（成功）{judge, source, x, dice}（青蛙瓷器/岭上开花/觉醒妖狐）
    "on_luck_effect_after",  # 运势生效后 {judge, source, x, dice}（预留）
})

# 各事件的默认时机类别："insert"=即时时机 / "queue"=延时时机（未列出的一律 queue）
EVENT_TIMING: dict[str, str] = {
    "on_game_start": "insert",       # 游戏开始时：即时时机
    "on_orb_changed": "insert",      # 鬼火变化时：即时时机
    "on_assaults_changed": "insert", # 出击次数变化时：即时时机
    "on_turn_end": "insert",         # 回合结束时：即时时机
    "on_before_assault": "insert",   # （被）攻击时：同时机能力全部触发后依次执行
    "on_after_assault": "insert",    # 攻击后：清除战力等，需即时完成
    "on_shield_changed": "insert",   # 护甲/破甲变化：即时时机，便于插入结算响应
    "on_stun": "insert",             # 被眩晕时：即时时机（同 on_shield_changed 的变化点发）
    "on_before_damage": "insert",  # 造成伤害前：即时时机（穿刺生效点）
    "on_damage_start": "insert",     # 造成/受到伤害开始时：即时时机
    "on_before_shield": "insert",    # 护甲计算前：即时时机
    "on_after_shield": "insert",     # 护甲计算后：即时时机
    "on_before_health": "insert",    # 扣减生命前：即时时机
    "on_before_heal": "insert",      # 治疗前：即时时机
    "on_before_defeat": "insert",    # 气绝前/消灭前 1：即时时机（响应挂此时机）
    "on_before_card_play": "insert",  # 使用手牌前：即时时机（魔音扰心；响应必发检查）
    "on_before_awaken": "insert",     # 觉醒前：即时时机（法术觉醒使用事件流程，thoughts.txt）
    "on_countdown_proc": "insert",    # 倒计时能力归零生效时：即时时机（先于归零块结算）
    "on_countdown_reduced": "insert", # 倒计时减少时：即时时机（定案：减少触发效果均即时；
    #                                 觉醒·山风复制为例外，单卡覆盖 timing=queue 延时）
    "on_before_field_intensity": "insert",  # 幻境耐久变化前：即时时机（修正变化量）
    "on_luck_judge": "insert",        # 运势判定时：即时时机（重投改写骰点后再确定结果）
    "on_before_draw": "insert",       # 抽牌前：即时时机（"获得卡牌前"锚点）
    "on_card_move": "insert",         # 牌移动后（即时时机）
    "on_invocation_trigger": "insert",  # 灵咒能力触发宣告：即时时机（响应窗在该灵咒能力
    #                                 结算前打开；鬼斩响应与刀鸣之刃复制挂点）
}
