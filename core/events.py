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
    "on_turn_start",        # 任一玩家回合开始 {player}
    "on_turn_end",          # 任一玩家回合结束 {player}
    "on_card_played",       # 卡牌使用后 {player, uid}
    "on_before_assault",    # 出击宣言后、伤害结算前 {attacker: Ref, victim: Ref}
    "on_after_assault",     # 出击结算完毕 {attacker: Ref}
    "on_damage",            # 式神受到伤害后 {victim: Ref, amount, source, kind}
    "on_player_damaged",    # 牌手受到伤害后 {player, amount, source, kind}
    "on_shikigami_defeated",  # 式神气绝（气绝后/消灭后，延时时机）{victim: Ref, source, reason}
    "on_shikigami_revived",  # 式神复活（复活后，延时时机）{shikigami: Ref, source, reason}
    "on_draw",              # 抽牌后 {player, count}
    "on_upgrade",           # 式神升级 {player, shikigami, level}
    "on_trigger",           # 响应牌触发 {player, uid}
    "on_summon",            # 召唤物进场 {shikigami: Ref}
    "on_form_attached",     # 形态牌结附 {player, shikigami, uid}
    "on_form_destroyed",    # 形态牌消灭 {player, shikigami, uid, reason}
    "on_shield_changed",    # 式神/牌手护甲或破甲数值变化后 {target: Ref, old, new, reason}
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
    "on_before_card_play",  # 使用手牌前 {player, uid, card, nullified（可变标记 dict）}
    "on_enter_combat",      # 式神进入战斗区 {player, shikigami: Ref}（延时时机）
    "on_leave_combat",      # 式神离开战斗区 {player, shikigami: Ref}（延时时机；气绝移动不发）
    # ---- 运势事件时点（第十五阶段；thoughts.txt 运势事件流程，core/engine.py 运势管线）----
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
    "on_before_damage": "insert",  # 造成伤害前：即时时机（穿刺生效点）
    "on_damage_start": "insert",     # 造成/受到伤害开始时：即时时机
    "on_before_shield": "insert",    # 护甲计算前：即时时机
    "on_after_shield": "insert",     # 护甲计算后：即时时机
    "on_before_health": "insert",    # 扣减生命前：即时时机
    "on_before_heal": "insert",      # 治疗前：即时时机
    "on_before_defeat": "insert",    # 气绝前/消灭前 1：即时时机（响应挂此时机）
    "on_before_card_play": "insert",  # 使用手牌前：即时时机（魔音扰心；响应必发检查）
    "on_before_awaken": "insert",     # 觉醒前：即时时机（法术觉醒使用事件流程，thoughts.txt）
    "on_luck_judge": "insert",        # 运势判定时：即时时机（重投改写骰点后再确定结果）
}
