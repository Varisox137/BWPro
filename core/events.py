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
    "on_damage",            # 式神受到伤害后 {victim: Ref, amount, source}
    "on_player_damaged",    # 牌手受到伤害后 {player, amount, source}
    "on_shikigami_defeated",  # 式神气绝（气绝后/消灭后，延时时机）{victim: Ref, source, reason}
    "on_shikigami_revived",  # 式神复活（复活后，延时时机）{shikigami: Ref, source, reason}
    "on_draw",              # 抽牌后 {player, count}
    "on_upgrade",           # 式神升级 {player, shikigami, level}
    "on_trigger",           # 响应牌触发 {player, uid}
    "on_summon",            # 召唤物进场 {shikigami: Ref}
    "on_form_attached",     # 形态牌结附 {player, shikigami, uid}
    "on_form_destroyed",    # 形态牌消灭 {player, shikigami, uid, reason}
})

# 各事件的默认时机类别："insert"=即时时机 / "queue"=延时时机（未列出的一律 queue）
EVENT_TIMING: dict[str, str] = {
    "on_before_assault": "insert",  # （被）攻击时：同时机能力全部触发后依次执行
}
