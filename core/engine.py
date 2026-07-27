"""规则引擎：一切状态变更的唯一入口。

结算模型（对应 CLAUDE.md「已确认设计规则」）：
- 效果块（EffectBlock）按 steps 顺序执行；
  mode="interleaved"：每个 step 之后清空一次触发队列（步骤之间允许其它效果结算）；
  mode="atomic"：     整块执行完才清队列（步骤之间不允许其它效果结算，保证无"同时"平局）。
- 触发效果声明 timing="insert"（立即插入当前结算）或 "queue"（进入队列延迟结算）。
- 响应牌（keyword 含 trigger）：响应仅赋予"敌方回合满足条件则必定使用"，其余要求
  与 cost 照常；是否要求式神未气绝取决于该牌是否有"气绝时可用"（与响应无关）。
  非回合方不存在任何带选择的操作。
- 0 级式神未在场：能力不触发、不能行动、不可被指定（除特殊说明）。
- 基础设定来自 state.config + 玩家级覆盖（PlayerState.config），见 cfg()。

指令（cmd dict）一览：
  play_card {uid, play_from?=hand, play_method?=<使用方式id>, target?}  使用卡牌
  assault {index}  出击：耗 1 鬼火 + 每回合唯一出击次数（+ 出击增减益，Phase 3）
  upgrade {index}  升级式神
  end_turn {}      结束回合
  调度阶段：mulligan {player, uid} / ready {player}
  调试指令：op 以 debug_ 开头，见 core/debug.py
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Any

from core import actions, debug, targets
from core.events import CORE_EVENTS, EVENT_TIMING
from core.model import (
    CardInstance,
    ExecContext,
    GameState,
    PlayerState,
    Ref,
    ShikigamiState,
    TempGrant,
)
from db.schema import CardDef, EffectBlock, PlayMethod, Step


class IllegalAction(Exception):
    """指令不合法（费用/等级/目标/时机等）。"""


MAX_QUEUE_ITERATIONS = 1000  # 效果队列死循环保护（DIY 安全网）

# 天然类别为"一次性"的关键字（触发后移除）；其余战斗关键字默认持续性（触发后不移除）。
# "永久"是授予方式而非关键字属性，由授予方显式指定 cls="perm"。
ONE_SHOT_KEYWORDS = frozenset({"haste", "unyielding", "barrier"})

# 卡牌级关键字（瞬发/响应）：只描述卡牌本身的使用方式，不授予式神
CARD_LEVEL_KEYWORDS = ("fast", "trigger")


@dataclass
class _DamageEvent:
    """伤害事件要素（docs/rules.md 第五章）：来源、受伤者、伤害值、原因、是否贯通。

    kind: "combat"（攻击方战斗伤害）/ "counter"（反击战斗伤害）/ "effect"（法术、能力等）。
    skip_early: 贯通溢出产生的新事件跳过早期流程，从"护甲计算前"开始结算（rules.md:199③）。
    时点批次监听者可通过事件 payload 中的 damage 引用直接修改 amount（扣减生命前锁定）。
    """

    source: Ref | None
    victim: Ref  # shikigami 字段为 None 表示牌手
    amount: int
    kind: str = "effect"
    piercing: bool = False
    skip_early: bool = False


@dataclass
class _Pending:
    block: EffectBlock
    ctx: ExecContext
    temp_grant: TempGrant | None = None  # 来自一次性临时触发的待结算项（结算后 uses-1）


class Game:
    def __init__(self, state: GameState, db, seed: int = 0) -> None:
        self.state = state
        self.db = db
        self.rng = random.Random(seed)
        self.queue: deque[_Pending] = deque()
        self.history: list[str] = []  # 事件名序列（测试/回放用）
        # 已消耗响应名额的时机实例序号：同一时机至多成功结算一张响应牌（原版"每空闲点
        # 限一张"已取消——不同时机可各响应一张；复查失败不占名额，同时机下一张可继续）
        self._response_used_emit: int | None = None
        # 战斗上下文（最小版）：每次 _resolve_combat 压栈新 battle id，终止点弹栈并
        # 清理本战斗授予的关键字实例与免疫条目。为嵌套战斗/响应战斗牌（Phase 3+）打底。
        self._battle_seq: int = 0
        self._battle_stack: list[int] = []
        self._battle_grants: dict[int, list[tuple[Ref, str, str]]] = {}  # battle id → [(式神 Ref, 关键字, 类别)]
        # battle id → [(式神 Ref, 战力)]：响应战斗牌插入使用授予的战力，终止点核销
        # （rules.md:52"该牌的力量与能力加成会持续到该次（被插入的）战斗后"）
        self._battle_power: dict[int, list[tuple[Ref, int]]] = {}
        self._op_param_cache: dict[str, frozenset] = {}  # op 函数签名缓存（Step.condition 分派用）

    # ---------- 关键字（多重集；一次性/持续/永久三类，见 docs/terminology.md） ----------

    @staticmethod
    def _has_keyword(s: ShikigamiState, keyword: str) -> bool:
        return (keyword in s.keywords or keyword in s.one_shot_keywords
                or keyword in s.perm_keywords)

    def _grant_keyword(self, s: ShikigamiState, keyword: str, cls: str | None = None) -> str:
        """授予一个关键字实例，返回实际入列的类别（one_shot/continuous/perm）。

        cls 缺省按关键字天然类别：ONE_SHOT_KEYWORDS 内为一次性，其余为持续性。
        """
        cls = cls or ("one_shot" if keyword in ONE_SHOT_KEYWORDS else "continuous")
        target = {"one_shot": s.one_shot_keywords, "perm": s.perm_keywords}.get(cls, s.keywords)
        target.append(keyword)
        return cls

    @staticmethod
    def _remove_keyword(s: ShikigamiState, keyword: str, cls: str | None = None) -> None:
        """按实例移除一个关键字（不存在则跳过，兼容气绝已清空的场景）。"""
        lists = {"one_shot": [s.one_shot_keywords], "perm": [s.perm_keywords],
                 "continuous": [s.keywords]}.get(cls, [s.one_shot_keywords, s.keywords, s.perm_keywords])
        for lst in lists:
            if keyword in lst:
                lst.remove(keyword)
                return

    @property
    def current(self) -> PlayerState:
        return self.state.players[self.state.active]

    @property
    def config(self):
        return self.state.config

    def cfg(self, player_index: int, key: str) -> Any:
        """读取某项对局设定：玩家级覆盖优先，否则用对局级默认（GameConfig）。"""
        override = self.state.players[player_index].config.get(key)
        return override if override is not None else getattr(self.state.config, key)

    def _effective_cost(self, p: PlayerState, cdef: CardDef,
                        card: CardInstance | None = None,
                        method: PlayMethod | None = None) -> int:
        """计算一张卡牌的实际鬼火消耗。

        规则：基础费用可被使用方式覆盖/增减，再加上实例修饰（mods.cost_delta）。
        瞬发：每（半）回合各自第一张瞬发卡费用为 0，其余条件照常。
        命中 cost_zero 卡牌光环（觉醒·妖刀姬"不消耗鬼火"）费用为 0，且不占用瞬发名额。
        结果不小于 0。
        """
        base = method.cost if (method and method.cost is not None) else cdef.cost
        delta = (method.cost_delta if method else 0)
        if card is not None:
            delta += int(card.mods.get("cost_delta", 0))
        cost = max(0, base + delta)
        if self._cost_zero_aura(p, cdef):
            return 0
        if "fast" in self._card_keywords(p, cdef, card) and not p.fast_used:
            cost = 0
        return cost

    def _match_auras(self, p: PlayerState, cdef: CardDef) -> list[dict]:
        """命中该卡牌的卡牌光环（card_auras 注册表，读取时求值，覆盖已有与新生成的牌）。"""
        return [
            a for a in p.card_auras
            if cdef.shikigami == a["shikigami"]
            and (a.get("card_type") is None or a["card_type"] == cdef.card_type)
        ]

    def _cost_zero_aura(self, p: PlayerState, cdef: CardDef) -> bool:
        """是否有命中光环使该牌不消耗鬼火。"""
        return any(a.get("cost_zero") for a in self._match_auras(p, cdef))

    def _fast_applies(self, p: PlayerState, cdef: CardDef,
                      card: CardInstance | None = None) -> bool:
        """该牌本次使用是否占用瞬发名额：具有瞬发（含光环/修饰授予）且未命中 cost_zero 光环
        （光环免费不占用瞬发名额，见 _effective_cost）。"""
        return "fast" in self._card_keywords(p, cdef, card) and not self._cost_zero_aura(p, cdef)

    def _card_keywords(self, p: PlayerState, cdef: CardDef,
                       card: CardInstance | None = None) -> set[str]:
        """一张卡当前实际具有的关键字：定义 ∪ 实例修饰 ∪ 命中光环（瞬发判定等的统一读取点）。"""
        kws = set(cdef.keywords)
        if card is not None:
            kws |= set(card.mods.get("keywords_add", []))
        for aura in self._match_auras(p, cdef):
            kws |= set(aura.get("keywords", []))
        return kws

    def _materialize(self, p: PlayerState, card: CardInstance, cdef: CardDef) -> None:
        """打出装配（docs/enhance-design.md 即时装配模型）：卡牌付费后、效果结算前，
        把持久 store（card_mods）中的修饰合并进该实例 mods 作为本次打出的快照——
        快照后计数再变也不影响本次结算。装配产物只在实例上，定义块永不改写。

        锚点：弹回手牌后再次打出会重复合并（现无弹回机制，出现时按实例去重）。
        """
        store = p.card_mods.get(cdef.id)
        if not store:
            return
        if store.get("enhance"):
            card.mods["enhance"] = card.mods.get("enhance", 0) + store["enhance"]
        if store.get("keywords_add"):
            merged = set(card.mods.get("keywords_add", [])) | set(store["keywords_add"])
            card.mods["keywords_add"] = sorted(merged)

    @staticmethod
    def _step_amount(step: Step, card: CardInstance | None,
                     s: ShikigamiState | None = None) -> int:
        """解析步骤的 amount 参数（docs/enhance-design.md 数值解析流水线）：

        - {"enhance": true, "base": n}：base + 实例已装配的 enhance 修饰；
        - {"shield_of": "self"|"source"}：来源式神当前护甲（尘刀快照/古尘之壁）；
        - {"power_of": "self"|"source"}：来源式神 eff_power（援护）。
        后两者在动作执行处另有 _run_step 的 ctx 解析路径（法术/能力步骤用）。
        """
        raw = (step.model_extra or {}).get("amount", 0)
        if isinstance(raw, dict):
            base = int(raw.get("base", 0))
            if raw.get("enhance") and card is not None:
                base += int(card.mods.get("enhance", 0))
            if raw.get("shield_of") and s is not None:
                base += s.shield
            if raw.get("power_of") and s is not None:
                base += s.eff_power
            return base
        return int(raw)

    # ==================== 对局初始化 ====================

    def start(self) -> None:
        """游戏开始阶段：发起始手牌 →（调度阶段）→ 式神已入场 → 最左升 1 级 → 先手抽 1。"""
        for pi, p in enumerate(self.state.players):
            self.rng.shuffle(p.deck)
            for _ in range(min(self.cfg(pi, "starting_hand"), len(p.deck))):
                card = p.deck.pop(0)
                self._assign_hand_seq(p, card)
                p.hand.append(card)  # 起始手牌静默发放，不发事件
            p.mulligans_left = self.config.mulligan_count
        if self.state.phase == "mulligan":
            self._log("对局开始：调度阶段（双方确认后式神入场）")
            return
        self._begin_battle()

    def _begin_battle(self) -> None:
        """调度完成（或跳过调度）后：式神依次入场 → 游戏开始能力 → 最左升级 → 先手抽 1。"""
        self.state.phase = "battle"
        self._log("对局开始")
        # 游戏开始阶段能力（如书翁额外抽 1）：式神已入场，即使 0 级能力也可触发
        self.emit("on_game_start")
        self._drain_queue()
        for pi, p in enumerate(self.state.players):
            if p.shikigami:
                p.shikigami[0].level = 1  # 最左侧式神自动升至 1 级，其余 0 级未在场
                self._register_ability_countdown(pi, 0)  # 能力进场：注册倒计时能力块
        self.state.players[1].shield += self.config.second_player_shield  # 后手补偿
        # 先手玩家抽 1（其后手首个回合由回合开始阶段补抽，见 _start_turn）
        self.draw_cards(self.state.active, 1)
        self._start_turn()

    # ==================== 指令入口 ====================

    def apply(self, cmd: dict) -> None:
        """校验并执行一条指令，然后清空触发队列。CLI 与将来的网络层共用此入口。

        流程：指令分发 → 对应 handler 执行状态变更/发出事件 → _drain_queue 结算
        该指令触发的所有延时效果。对局已结束时拒绝任何操作。
        以 "debug_" 开头的 op 会路由到 core/debug.py 的调试指令注册表。
        """
        if self.state.winner is not None or self.state.pending_end:
            raise IllegalAction("对局已结束")
        op = cmd.get("op", "")
        if op.startswith("debug_"):
            if not self.config.enable_debug_commands:
                raise IllegalAction("调试指令已禁用")
            self._cmd_debug(cmd)
            self._drain_queue()
            return
        handlers = {
            "play_card": self._cmd_play_card,
            "assault": self._cmd_assault,
            "upgrade": self._cmd_upgrade,
            "end_turn": self._cmd_end_turn,
            "mulligan": self._cmd_mulligan,
            "ready": self._cmd_ready,
        }
        handler = handlers.get(op)
        if handler is None:
            raise IllegalAction(f"未知指令: {op}")
        if self.state.phase == "mulligan" and op not in ("mulligan", "ready"):
            raise IllegalAction("调度阶段：请先完成调度（mulligan/ready）")
        if self.state.phase == "upgrade" and op not in ("upgrade",):
            raise IllegalAction("升级阶段：请先完成升级")
        if self.state.phase == "battle" and op == "upgrade":
            raise IllegalAction("当前不在升级阶段")
        handler(cmd)
        self._drain_queue()

    def _cmd_debug(self, cmd: dict) -> None:
        """执行调试指令。name 为 op 去掉 "debug_" 前缀后的部分。"""
        name = cmd["op"][6:]
        fn = debug.DEBUG_COMMANDS.get(name)
        if fn is None:
            raise IllegalAction(f"未知调试指令: {name}")
        ctx = ExecContext(controller=cmd.get("player", self.state.active))
        fn(self, ctx, **cmd.get("args", {}))

    # ---------- 调度（游戏开始阶段） ----------

    def _cmd_mulligan(self, cmd: dict) -> None:
        """调度（Phase 1 简化版）：把一张起始手牌返回牌库（随机位置），再随机抽一张。

        完整规则（docs/rules.md 调度事件流程）包含加护/蚀印移除、展示状态传递、
        灵咒移除、调度后洗牌等；Phase 1 最小实现暂不处理这些机制。
        双方各自限次。
        """
        if self.state.phase != "mulligan":
            raise IllegalAction("当前不在调度阶段")
        p = self.state.players[self._mulligan_player(cmd)]
        if p.mulligan_done:
            raise IllegalAction(f"{p.name} 已完成调度")
        if p.mulligans_left < 1:
            raise IllegalAction("调度次数已用完")
        uid = cmd.get("uid")
        card = next((c for c in p.hand if c.uid == uid), None)
        if card is None:
            raise IllegalAction("手牌中没有这张牌")
        idx = p.hand.index(card)
        old_seq = card.hand_seq
        p.hand.pop(idx)
        p.deck.insert(self.rng.randint(0, len(p.deck)), card)      # 返回牌库
        new_card = p.deck.pop(self.rng.randint(0, len(p.deck) - 1))  # 再随机抽一张
        new_card.hand_seq = old_seq                                 # 换入牌继承换出牌的顺序编号
        p.hand.insert(idx, new_card)
        p.mulligans_left -= 1
        self._log(f"{p.name} 调度了一张手牌（剩余 {p.mulligans_left} 次）")
        if p.mulligans_left == 0:
            p.mulligan_done = True
        if all(p.mulligan_done for p in self.state.players):
            self._begin_battle()

    def _cmd_ready(self, cmd: dict) -> None:
        """确认完成调度（可以不用满次数）。双方均确认后进入对战阶段。"""
        if self.state.phase != "mulligan":
            raise IllegalAction("当前不在调度阶段")
        p = self.state.players[self._mulligan_player(cmd)]
        p.mulligan_done = True
        self._log(f"{p.name} 完成调度")
        if all(p.mulligan_done for p in self.state.players):
            self._begin_battle()

    def _mulligan_player(self, cmd: dict) -> int:
        pi = cmd.get("player")
        if pi not in (0, 1):
            raise IllegalAction("调度指令需要 player（0/1）")
        return pi

    # ---------- 出牌 ----------

    def _cmd_play_card(self, cmd: dict) -> None:
        p = self.current
        uid = cmd.get("uid")
        play_from = cmd.get("play_from", "hand")  # 使用位置：默认手牌，保留扩展（牌库/墓地…）
        card = next((c for c in p.zones.get(play_from, []) if c.uid == uid), None)
        if card is None:
            raise IllegalAction(f"区域 {play_from} 中没有这张牌")
        cdef = self.db.cards[card.id]
        # Phase 1 实现法术牌、形态牌、战斗牌（测试数据限定为数值修正）；
        # 幻境/协战在规则/引擎落地方可打出。
        if cdef.card_type in ("field", "reinforce"):
            raise IllegalAction(f"《{cdef.name}》的卡牌类型 {cdef.card_type} 尚未实现")
        # 使用方式（多择子选项，仅保留核心方式、参数可变；按 id 匹配，param 为数据预留）
        method: PlayMethod | None = None
        method_id = cmd.get("play_method")
        if method_id is not None:
            method = next((m for m in cdef.methods if m.id == method_id), None)
            if method is None:
                raise IllegalAction(f"《{cdef.name}》没有使用方式「{method_id}」")
        # 生效的等级要求与目标（使用方式可覆盖）
        eff_level = method.level if (method and method.level is not None) else cdef.level
        eff_target = method.target if (method and method.target is not None) else cdef.target
        # 所属式神检查（中立牌无从属式神，跳过；气绝时可用看卡牌标记，与是否响应无关）
        si: int | None = None
        if cdef.shikigami is not None:
            si = self._find_shikigami(p, cdef.shikigami)
            sname = self.db.shikigami[cdef.shikigami].name
            if si is None:
                raise IllegalAction(f"{sname} 未出战")
            s = p.shikigami[si]
            if s.defeated and not cdef.playable_when_defeated:
                raise IllegalAction(f"{sname} 气绝中，无法使用其卡牌")
            if s.level < eff_level:
                raise IllegalAction(f"《{cdef.name}》需要 {sname} 达到 {eff_level} 级（当前 {s.level} 级）")
        # 尘缚之阵锁定：准备区式神不能发起不具有远程的战斗（战斗牌；出击见 _cmd_assault）
        if (cdef.card_type == "combat" and si is not None
                and p.combat_index != si
                and not self._has_keyword(p.shikigami[si], "remote")
                and self._combat_zone_locked(self.state.active)):
            raise IllegalAction("尘缚之阵：准备区式神不能发起不具有远程的战斗")
        # 费用 = （方式覆盖或基础）+ 方式增减 + 实例修饰；瞬发仅免鬼火，其余条件照常
        cost = self._effective_cost(p, cdef, card=card, method=method)
        if p.orb < cost:
            raise IllegalAction(f"鬼火不足（需要 {cost}，现有 {p.orb}）")
        chosen: list[Ref] = []
        if eff_target.kind == "choose":
            want = cmd.get("target")
            if want is None:
                raise IllegalAction("该牌需要选择目标")
            want = want if isinstance(want, Ref) else Ref(**want)
            if want not in targets.pool_refs(self, eff_target.pool, self.state.active):
                raise IllegalAction("目标不合法")
            chosen = [want]
        if self._fast_applies(p, cdef, card):
            p.fast_used = True
        p.orb -= cost
        self._materialize(p, card, cdef)  # 打出装配：付费后、效果结算前快照持久修饰
        how = f"（{method.text or method.id}）" if method else ""
        self._log(f"{p.name} 使用了《{cdef.name}》{how}")
        if cdef.card_type == "form":
            # 形态牌：从手牌/原区域移除并立即结附（响应插入使用同样走 _play_form_card）
            if si is None:
                raise IllegalAction("形态牌必须有所属式神")
            self._play_form_card(p, si, card, cdef, self.state.active, chosen)
        elif cdef.card_type == "combat":
            # 战斗牌：以完整战斗事件流程结算（移入战斗区、战力/一次性护甲、
            # 战斗前/后时机、战斗伤害），结算完后进入墓地。
            if si is None:
                raise IllegalAction("战斗牌必须有所属式神")
            self._resolve_combat_card(p, si, card, cdef, method)
        else:
            self.move_card(p, card, "graveyard")
            ctx = ExecContext(
                controller=self.state.active,
                source=Ref(player=self.state.active, shikigami=si) if si is not None else None,
                card=card,
                chosen=chosen,
            )
            block = method.effects if (method and method.effects is not None) else cdef.effects
            self._resolve_block(block, ctx)
            # 觉醒牌：替换当前式神能力为觉醒能力（rules.md 第十三章；气绝/复活保留觉醒状态）
            if cdef.subtype == "awaken" and si is not None:
                p.shikigami[si].awakened = cdef.id
                self._register_ability_countdown(self.state.active, si)  # 觉醒替换：注册觉醒能力的倒计时块
                self._log(f"{self.db.shikigami[p.shikigami[si].id].name} 觉醒")
                self.emit("on_awakened", player=self.state.active, shikigami=si, uid=uid,
                          target=Ref(player=self.state.active, shikigami=si))
        self.emit("on_card_played", player=self.state.active, uid=uid)

    def combat_card_stats(self, block: EffectBlock,
                          card: CardInstance | None = None,
                          s: ShikigamiState | None = None) -> tuple[int, int]:
        """从战斗牌的效果块中提取战力与一次性护甲数值（仅统计目标为 self 的 buff_power / gain_shield）。

        公开方法：引擎内部结算与客户端展示（client/cli.py 手牌数值段）共用。

        amount 支持 {"enhance": true, "base": n} 形式（禁锢之刀/冲撞）：base + 实例已装配的
        enhance 修饰（打出装配快照，见 _materialize）；以及 {"shield_of": "self"}（尘刀：
        按打出瞬间护甲快照战力，本次战斗中不变）。
        """
        power = 0
        shield = 0
        for step in block.steps:
            if step.target is not None and step.target.kind != "self":
                continue
            amount = self._step_amount(step, card, s)
            if step.op == "buff_power":
                power += amount
            elif step.op == "gain_shield":
                shield += amount
        return power, shield

    def _apply_combat_stats(self, ref: Ref, s: ShikigamiState, power: int, shield: int,
                            *, battle_scoped: bool) -> None:
        """战斗牌战力/一次性护甲结算（主动使用与响应插入使用共用）。

        战力：主动使用经 s.combat_power（战斗后由调用方清零）；响应插入使用挂账
        _battle_power（battle_scoped=True），持续到被插入的该次战斗后由终止点核销。
        护甲/破甲保留，并按即时时机发出 on_shield_changed 事件。
        """
        if power:
            s.combat_power += power
            if battle_scoped and self._battle_stack:
                self._battle_power.setdefault(self._battle_stack[-1], []).append((ref, power))
        if shield:
            self._change_shield(ref, shield, "combat_card")

    def _resolve_combat_card(self, p: PlayerState, si: int, card: CardInstance,
                             cdef: CardDef, method: PlayMethod | None) -> None:
        """战斗牌完整事件流程：获得战力/护甲、牌移至墓地、战斗（移入战斗区、战斗前、战斗伤害、战斗后）。

        战斗牌提供的力量（战力）在战斗后清除；提供的护甲/破甲会保留，并按即时时机
        发出 on_shield_changed 事件。
        """
        s = p.shikigami[si]
        if not s.in_play:
            raise IllegalAction("该式神未在场，无法使用战斗牌")
        block = method.effects if (method and method.effects is not None) else cdef.effects
        power, shield = self.combat_card_stats(block, card, s)
        atk_ref = Ref(player=self.state.active, shikigami=si)
        self._apply_combat_stats(atk_ref, s, power, shield, battle_scoped=False)
        # 战斗牌授予的关键字（fast/trigger 为卡牌级，不授予）与作用域战斗伤害免疫，
        # 均绑定本次战斗上下文，终止点移除（rules.md:338"直到本次战斗结束后"）
        grants = tuple(k for k in cdef.keywords if k not in CARD_LEVEL_KEYWORDS)
        imms = tuple(bool((st.model_extra or {}).get("nested", False))
                     for st in block.steps if st.op == "battle_immunity")
        # rules.md:344：战斗牌先移至墓地，再发起战斗（战斗中的墓地计数等效果可见此牌）
        self.move_card(p, card, "graveyard")
        self._resolve_combat(atk_ref, s, grant_keywords=grants, immunities=imms,
                             temp_grants=tuple(cdef.temp_grants))
        s.combat_power = 0

    def _apply_response_combat(self, p: PlayerState, si: int, card: CardInstance,
                               cdef: CardDef) -> None:
        """响应战斗牌的插入使用（rules.md:52）：在"（被）攻击时"触发时——

        - 不发起新战斗：所属式神改为移入战斗区（无论是否具有远程）；
        - 牌的力量（战力）/护甲/关键字/战斗伤害免疫/一次性临时触发绑定当前（被插入的）战斗，
          力量与能力加成持续到该次战斗后（战力经 _battle_power 终止点核销，
          关键字/免疫经 _battle_grants / immunities 的战斗作用域清理）；
        - 牌入墓地。调用方已支付费用并 emit on_trigger。
        """
        s = p.shikigami[si]
        pi = self.state.players.index(p)
        ref = Ref(player=pi, shikigami=si)
        block = cdef.effects
        power, shield = self.combat_card_stats(block, card, s)
        self._apply_combat_stats(ref, s, power, shield, battle_scoped=True)
        # 关键字（fast/trigger 为卡牌级除外）授予并登记到当前战斗（终止点按实例移除）
        if self._battle_stack:
            grants = self._battle_grants.setdefault(self._battle_stack[-1], [])
            for kw in cdef.keywords:
                if kw not in CARD_LEVEL_KEYWORDS:
                    cls = self._grant_keyword(s, kw)
                    grants.append((ref, kw, cls))
            # 战斗牌携带的一次性临时触发登记到当前战斗（终止点移除未用者）
            for blk in cdef.temp_grants:
                self.state.temp_grants.append(TempGrant(
                    block=blk, controller=pi, holder=ref,
                    battle=self._battle_stack[-1]))
        # 其余 steps（battle_immunity 等）照常执行——登记到当前战斗上下文
        ctx = ExecContext(controller=pi, source=ref, card=card)
        for step in block.steps:
            if (step.op in ("buff_power", "gain_shield")
                    and (step.target is None or step.target.kind == "self")):
                continue  # 战力/护甲已提取，不重复执行
            self._run_step(step, ctx)
        # 改为移入战斗区（无论该牌所属式神是否具有远程）
        if p.combat_index != si and s.in_play:
            self._enter_combat(p, si)
        self.move_card(p, card, "graveyard")

    def legal_targets(self, player_index: int, card: CardInstance) -> list[Ref]:
        """一张 choose 目标卡牌当前的合法目标列表（供客户端展示/校验；不含方式覆盖）。"""
        cdef = self.db.cards[card.id]
        if cdef.target.kind != "choose":
            return []
        return targets.pool_refs(self, cdef.target.pool, player_index)

    @staticmethod
    def _assign_hand_seq(p: PlayerState, card: CardInstance) -> None:
        """为加入手牌的卡牌分配一个连续的顺序编号（1..N）。"""
        card.hand_seq = 0
        max_seq = max((c.hand_seq for c in p.hand), default=0)
        card.hand_seq = max_seq + 1

    @staticmethod
    def _compact_hand_seq(p: PlayerState, removed_seq: int) -> None:
        """手牌中一张顺序编号为 removed_seq 的牌离开后，大于它的编号均 -1。"""
        for c in p.hand:
            if c.hand_seq > removed_seq:
                c.hand_seq -= 1

    def _remove_from_zone(self, p: PlayerState, card: CardInstance) -> str | None:
        """把卡牌从其所在区域移除（从手牌移除时压缩剩余编号）；返回原区域名，不在任何区域则 None。"""
        for zname, z in p.zones.items():
            if card in z:
                z.remove(card)
                if zname == "hand":
                    self._compact_hand_seq(p, card.hand_seq)
                return zname
        return None

    def move_card(self, p: PlayerState, card: CardInstance, to_zone: str) -> None:
        """把卡牌移动到指定区域；区域不存在则创建（区域系统保留扩展空间）。

        Phase 1 简化：直接变更区域，不触发卡牌移动后灵咒效果，不检查区域上限。
        完整规则见 docs/rules.md「卡牌移动事件流程」。
        若 card 不在任何已知区域（如测试直接注入手牌），直接追加到目标区域。
        移入手牌时（重新）分配 hand_seq；从手牌移出时压缩剩余编号。
        """
        self._remove_from_zone(p, card)
        if to_zone == "hand":
            self._assign_hand_seq(p, card)
        p.zones.setdefault(to_zone, []).append(card)

    def _change_shield(self, ref: Ref, delta: int, reason: str) -> None:
        """目标（式神或牌手）护甲增减 delta，并按即时时机发出 on_shield_changed 事件。"""
        p = self.state.players[ref.player]
        holder = p.shikigami[ref.shikigami] if ref.shikigami is not None else p
        old = holder.shield
        holder.shield += delta
        self.emit("on_shield_changed", target=ref, old=old, new=holder.shield, reason=reason)

    # ---------- 出击 / 移动 ----------

    def _resolve_combat(self, atk_ref: Ref, attacker: ShikigamiState, *,
                        move: bool = True,
                        grant_keywords: tuple[str, ...] = (),
                        immunities: tuple[bool, ...] = (),
                        temp_grants: tuple[EffectBlock, ...] = ()) -> None:
        """通用战斗流程（docs/rules.md 第四章）。复用于出击指令与战斗牌。

        战斗上下文：压栈新 battle id。grant_keywords 为战斗牌等授予攻击者的关键字实例
        （终止点按实例移除，不误删式神原有同名关键字）；immunities 为作用域战斗伤害
        免疫（元素 = nested：是否覆盖本战斗内的嵌套战斗）；temp_grants 为战斗牌携带的
        一次性临时触发（绑定本战斗 id 注册，终止点移除未用者，如不祥之刃的击杀抽牌）。
        """
        self._battle_seq += 1
        bid = self._battle_seq
        self._battle_stack.append(bid)
        grants: list[tuple[Ref, str, str]] = []
        self._battle_grants[bid] = grants
        self._battle_power[bid] = []  # 响应战斗牌插入使用授予的战力（终止点核销）
        for kw in grant_keywords:
            cls = self._grant_keyword(attacker, kw)
            grants.append((atk_ref, kw, cls))
        for nested in immunities:
            attacker.immunities.append({"kind": "combat_damage", "battle": bid, "nested": nested})
        for block in temp_grants:
            self.state.temp_grants.append(TempGrant(
                block=block, controller=atk_ref.player, holder=atk_ref, battle=bid))
        try:
            self._battle_flow(atk_ref, attacker, move=move)
        finally:
            # 终止点（rules.md:174）：移除本战斗授予的关键字实例与免疫条目
            for ref, kw, cls in grants:
                st = self.state.players[ref.player].shikigami[ref.shikigami]
                self._remove_keyword(st, kw, cls)
            self._battle_grants.pop(bid, None)
            # 响应战斗牌插入使用授予的战力核销（持续到该次战斗后）
            for ref, pw in self._battle_power.pop(bid, []):
                st = self.state.players[ref.player].shikigami[ref.shikigami]
                st.combat_power -= pw
            for pl in self.state.players:
                for st in pl.shikigami:
                    st.immunities[:] = [e for e in st.immunities if e.get("battle") != bid]
            # 移除本战斗绑定的一次性临时触发（已触发完的已随 uses 归零移除）
            self.state.temp_grants[:] = [g for g in self.state.temp_grants if g.battle != bid]
            self._battle_stack.pop()
            # 攻击者"直到攻击后"的临时强化在此结束；keep_attack_buffs（残心）跳过核销
            if attacker.attack_buffs and not self._has_keyword(attacker, "keep_attack_buffs"):
                for entry in attacker.attack_buffs:
                    attacker.temp_power -= entry.get("power", 0)
                    for kw, cls in entry.get("keywords", []):
                        self._remove_keyword(attacker, kw, cls)
                attacker.attack_buffs.clear()

    def _battle_flow(self, atk_ref: Ref, attacker: ShikigamiState, *, move: bool) -> None:
        """战斗步骤：战斗准备前 → 战斗准备（移动）→（被）攻击时 → 先攻阶段 → 交战阶段 → 战斗后。

        锚点（未实现）：激怒移除、战斗结界中的嵌套战斗、被攻击者气绝后复活不终止战斗。
        """
        p = self.state.players[atk_ref.player]
        def_pi = 1 - atk_ref.player
        d = self.state.players[def_pi]
        remote = self._has_keyword(attacker, "remote")
        piercing = self._has_keyword(attacker, "piercing")
        combo = self._has_keyword(attacker, "combo")
        initiative = self._has_keyword(attacker, "initiative")
        # ---- 战斗准备前：移除攻击者的激怒（穿刺已移至伤害事件"造成伤害前"批次）----
        self._remove_keyword(attacker, "enraged")
        self._drain_queue()
        # ---- 战斗准备：移动攻击者（具有远程则不移动）；攻击者气绝则终止 ----
        if move and not remote and p.combat_index != atk_ref.shikigami:
            self._enter_combat(p, atk_ref.shikigami)
        if attacker.defeated or attacker.despawned:
            self._log("攻击方在战斗准备阶段气绝/离场，战斗中止")
            return
        # ---- （被）攻击时（即时时机）----
        self.emit("on_before_assault", attacker=atk_ref,
                  victim=Ref(player=def_pi, shikigami=d.combat_index))
        self._drain_queue()
        if attacker.defeated or attacker.despawned:
            self._log("攻击方在伤害结算前气绝/离场，战斗中止")
            return
        # ---- 确定被攻击者：敌方战斗区式神，否则敌方牌手 ----
        vic_idx = d.combat_index

        def attack_event() -> _DamageEvent:
            return _DamageEvent(source=atk_ref, victim=Ref(player=def_pi, shikigami=vic_idx),
                                amount=attacker.eff_power, kind="combat", piercing=piercing)

        def counter_event() -> _DamageEvent:
            vs = d.shikigami[vic_idx]
            return _DamageEvent(source=Ref(player=def_pi, shikigami=vic_idx),
                                victim=atk_ref, amount=vs.eff_power, kind="counter")

        # ---- 先攻阶段：拥有连击/先攻的角色对对方造成战斗伤害，按（反击，攻击）并行 ----
        atk_first = combo or initiative
        def_first = vic_idx is not None and (
            self._has_keyword(d.shikigami[vic_idx], "combo")
            or self._has_keyword(d.shikigami[vic_idx], "initiative"))
        if atk_first or def_first:
            events: list[_DamageEvent] = []
            if def_first and not remote:
                events.append(counter_event())
            if atk_first:
                events.append(attack_event())
            self._run_damage_queue(events)
            if self.state.pending_end:
                return
            # 被攻击者气绝：攻击者具有贯通则被攻击者改为对方牌手，否则终止战斗
            if vic_idx is not None and d.shikigami[vic_idx].defeated:
                if piercing:
                    vic_idx = None
                else:
                    self._log("被攻击方气绝，战斗终止")
                    return
            if attacker.defeated or attacker.despawned:
                self._log("攻击方在先攻阶段气绝/离场，战斗终止")
                return
        # ---- 交战阶段：具有先攻（非连击）的角色不再造成战斗伤害；远程不受反击 ----
        events = []
        if vic_idx is not None and not remote:
            vs = d.shikigami[vic_idx]
            def_init_only = (self._has_keyword(vs, "initiative")
                             and not self._has_keyword(vs, "combo"))
            if not def_init_only:
                events.append(counter_event())
        if not (initiative and not combo):
            events.append(attack_event())
        if events:
            self._run_damage_queue(events)
        # ---- 战斗后 ----
        self.emit("on_after_assault", attacker=atk_ref)

    def _cmd_assault(self, cmd: dict) -> None:
        """出击指令：耗 1 鬼火 + 消耗出击次数，将攻击者移入战斗区并发起战斗。

        流程：合法性检查 → 支付费用 → 移入战斗区 → 发出 on_before_assault（即时时机）
        → 结算该时机触发的 insert 效果 → 若攻击者仍存活则造成战斗伤害。
        战斗伤害按（反击，攻击）顺序生成事件：先处理攻击者受到的反击伤害，
        再处理被攻击者受到的攻击伤害；气绝判定与伤害事件同序。
        """
        p = self.current
        i = cmd.get("index")
        s = self._own_shikigami(p, i)
        if not s.in_play:
            raise IllegalAction("该式神未在场（0 级），不能出击")
        if p.assaults_left < 1:
            raise IllegalAction("本回合已没有出击次数")
        # 激怒：己方存在"被激怒且满足出击合法性（在场 + 有出击次数）"的式神时，
        # 其他无激怒的式神不能出击（简化：不查鬼火/眩晕，rules.md ch4/11）
        if not self._has_keyword(s, "enraged") and any(
                self._has_keyword(o, "enraged") and o.in_play
                for j, o in enumerate(p.shikigami) if j != i):
            raise IllegalAction("激怒：被激怒的式神可以出击时，其他式神不能出击")
        # 尘缚之阵锁定：准备区式神不能发起不具有远程的战斗
        if (p.combat_index != i and not self._has_keyword(s, "remote")
                and self._combat_zone_locked(self.state.active)):
            raise IllegalAction("尘缚之阵：准备区式神不能发起不具有远程的战斗")
        # 迅捷：出击事件的鬼火消耗处不消耗鬼火，随后失去一个一次性迅捷（永久迅捷不移除）
        if self._has_keyword(s, "haste"):
            if "haste" in s.one_shot_keywords:
                s.one_shot_keywords.remove("haste")
            self._log(f"{self.db.shikigami[s.id].name} 的【迅捷】生效，本次出击不消耗鬼火")
        else:
            if p.orb < 1:
                raise IllegalAction("出击需要 1 点鬼火")
            p.orb -= 1
        p.assaults_left -= 1
        atk_ref = Ref(player=self.state.active, shikigami=i)
        self._consume_assault_boosts(p, atk_ref, s)
        self._resolve_combat(atk_ref, s)

    def _consume_assault_boosts(self, p: PlayerState, atk_ref: Ref, s: ShikigamiState) -> None:
        """出击时消耗全部出击加成/鼓舞（rules.md 出击流程 4.2-4.3）：
        力量直到本次出击的战斗后（attack_buffs 挂账核销）、护甲获得后保留；战斗牌不消耗。"""
        if not p.assault_boosts:
            return
        power = sum(b.get("power", 0) for b in p.assault_boosts)
        shield = sum(b.get("shield", 0) for b in p.assault_boosts)
        if power:
            s.temp_power += power
            s.attack_buffs.append({"power": power, "keywords": []})
        if shield:
            self._change_shield(atk_ref, shield, "basic_boost")
        self._log(f"{self.db.shikigami[s.id].name} 获得出击加成（+{power}力量/+{shield}护甲）")
        p.assault_boosts.clear()

    def _combat_zone_locked(self, pi: int) -> bool:
        """尘缚之阵锁定：敌方战斗区有"结附带 combat_lock 标记形态"的式神，且己方战斗区有式神。

        锁定效果（对己方，不看效果发起者）：会使己方战斗区式神被替换的效果无效且不能进行——
        召唤召唤物的效果无效；准备区式神不能发起不具有远程的战斗（出击/战斗牌）；
        响应战斗牌的插入移入不可用（响应复查处拦截）；enter_combat 效果无效。
        己方战斗区式神退回准备区不受限。效果发起的战斗暂无来源，见 rules.md 锚点。
        """
        p = self.state.players[pi]
        ep = self.state.players[1 - pi]
        if p.combat_index is None or ep.combat_index is None:
            return False
        s = ep.shikigami[ep.combat_index]
        if s.form is None or not s.in_play:
            return False
        return "combat_lock" in self.db.cards[s.form.id].tags

    def _direct_destroy_immune(self, pi: int, si: int) -> bool:
        """尘缚之阵：结附带 destroy_immune 标记形态的式神在战斗区时，免疫直接消灭效果。"""
        p = self.state.players[pi]
        if p.combat_index != si:
            return False
        s = p.shikigami[si]
        if s.form is None or not s.in_play:
            return False
        return "destroy_immune" in self.db.cards[s.form.id].tags

    def _enter_combat(self, p: PlayerState, i: int) -> None:
        """进入战斗区；若已有其它式神驻留，则其退回准备区。"""
        if p.combat_index is not None and p.combat_index != i:
            self._retreat(p, p.combat_index)
        p.combat_index = i

    def _retreat(self, p: PlayerState, i: int) -> None:
        """战斗区式神退回准备区；召唤物无准备区可归（home_slot=None），退回即离场（非气绝）。"""
        s = p.shikigami[i]
        if p.combat_index == i:
            p.combat_index = None
        if s.defeated or s.despawned:
            return
        if s.home_slot is None:
            self._despawn(p, i)
        else:
            self._log(f"{self.db.shikigami[s.id].name} 退回准备区")

    def _despawn(self, p: PlayerState, i: int) -> None:
        """召唤物离场：不进复活流程（保留坑位稳定下标）；keep_buffs 留下永久增减益。"""
        s = p.shikigami[i]
        d = self.db.shikigami[s.id]
        if p.combat_index == i:
            p.combat_index = None
        s.despawned = True
        if d.keep_buffs:
            # 同名召唤物再召时保留永久增减益（如跳跳妹妹-番茄）
            p.summon_legacy[s.id] = {
                "perm_power": s.perm_power,
                "perm_health": s.perm_health,
            }
        self._log(f"{d.name} 离场")

    def _attach_form(self, p: PlayerState, i: int, card: CardInstance, cdef: CardDef) -> None:
        """为式神结附形态牌：先消灭旧形态，再用形态身材覆盖基础身材。

        Phase 1 简化版：省略"形态被消灭前/后"、"形态进场前/时/后"等子时机，
        统一 emit on_form_destroyed / on_form_attached（均延时时机）。
        """
        s = p.shikigami[i]
        if s.form is not None:
            self._destroy_form(p, i, reason="replace")
        s.form = card
        # 形态牌具有倒计时时，式神获得该倒计时能力（替换当前倒计时；rules.md ch10 结附流程）
        if cdef.countdown is not None:
            self._register_countdown(s, initial=cdef.countdown,
                                     block=cdef.countdown_effects, source=card.id)
        if cdef.form_power is not None:
            s.base_power = cdef.form_power
        if cdef.form_health is not None:
            s.base_health = cdef.form_health
        s.health = s.max_health
        # 形态牌 keywords（fast/trigger 为卡牌级除外）结附期间授予式神
        for kw in cdef.keywords:
            if kw not in CARD_LEVEL_KEYWORDS:
                self._grant_keyword(s, kw)
        self._log(f"{self.db.shikigami[s.id].name} 结附形态《{cdef.name}》")
        pi = self.state.players.index(p)
        self.emit("on_form_attached", player=pi, shikigami=i, uid=card.uid,
                  target=Ref(player=pi, shikigami=i), card=card)

    def _play_form_card(self, p: PlayerState, si: int, card: CardInstance,
                        cdef: CardDef, controller: int, chosen: list[Ref]) -> None:
        """形态牌结附（主动使用与响应插入使用共用）：从手牌/原区域移除（不进入任何区域），
        以该卡牌数据给式神结附形态；形态离场时变为卡牌并置入墓地。此过程不是“卡牌移动事件”。
        随后结算形态牌的进场时效果（effects 块；可用打出时的选择目标，如尘缚之阵授予激怒）。
        """
        self._remove_from_zone(p, card)
        self._attach_form(p, si, card, cdef)
        if cdef.effects.steps and cdef.effects.when == "on_play":
            self._resolve_block(cdef.effects, ExecContext(
                controller=controller,
                source=Ref(player=controller, shikigami=si),
                card=card, chosen=chosen))

    def _destroy_form(self, p: PlayerState, i: int, reason: str) -> None:
        """消灭式神当前结附的形态牌：形态牌进入墓地，基础身材恢复为式神原本身材。

        当前生命会被调整为新的生命上限；若上限不大于 0 会触发延时的气绝事件
        （rules.md：形态的消灭与结附事件流程）。
        """
        s = p.shikigami[i]
        old = s.form
        if old is None:
            return
        cdef = self.db.cards[old.id]
        s.form = None
        # 形态离场仅清除该形态授予的倒计时（rules.md ch10 消灭流程）；
        # 已被 set_countdown/能力注册替换的倒计时不受影响
        if s.countdown_source == old.id:
            self._clear_countdown(s)
        # 移除形态授予的关键字实例（气绝已清空时跳过）
        for kw in cdef.keywords:
            if kw not in CARD_LEVEL_KEYWORDS:
                self._remove_keyword(s, kw)
        self.move_card(p, old, "graveyard")
        d = self.db.shikigami[s.id]
        s.base_power = d.power
        s.base_health = d.health
        s.health = s.max_health
        self._log(f"{d.name} 的形态《{cdef.name}》被消灭（原因：{reason}）")
        pi = self.state.players.index(p)
        self.emit("on_form_destroyed", player=pi, shikigami=i,
                  uid=old.uid, reason=reason,
                  target=Ref(player=pi, shikigami=i), card=old)

    # ---------- 升级 / 结束回合 ----------

    def _cmd_upgrade(self, cmd: dict) -> None:
        """升级指令：仅在升级阶段可用。消耗 1 次升级机会，升级完成后若机会用尽则进入主要阶段。"""
        if self.state.phase != "upgrade":
            raise IllegalAction("当前不在升级阶段")
        p = self.current
        i = cmd.get("index")
        if p.upgrades < 1:
            raise IllegalAction("本回合已没有升级机会")
        if not (0 <= i < len(p.shikigami)):
            raise IllegalAction("式神序号无效")
        s = p.shikigami[i]
        if s.kind != "shikigami":
            raise IllegalAction("召唤物不能升级")
        if s.level >= self.config.max_level:
            raise IllegalAction("已达最高等级")
        # 升级规则（lowest：只能升等级最低的未满级式神；free：无限制）与
        # legal_upgrade_indices 同一套判定，此处不重复展开
        if i not in self.legal_upgrade_indices(self.state.active):
            raise IllegalAction("只能升级当前等级最低的式神")
        s.level += 1
        p.upgrades -= 1
        if s.level == 1:
            self._register_ability_countdown(self.state.active, i)  # 能力进场：0 级升至 1 级
        name = self.db.shikigami[s.id].name
        self._log(f"{p.name} 将 {name} 升至 {s.level} 级")
        self.emit("on_upgrade", player=self.state.active, shikigami=i, level=s.level)
        if p.upgrades == 0 or not self._has_upgrade_target(p):
            self.state.phase = "battle"

    def legal_upgrade_indices(self, pi: int) -> list[int]:
        """玩家 pi 当前可合法升级的式神下标（与 _cmd_upgrade 同一套规则）。

        供服务端回合超时随机升级等托管操作使用；不检查 phase/upgrades 机会数。
        """
        p = self.state.players[pi]
        candidates = [
            i for i, x in enumerate(p.shikigami)
            if x.kind == "shikigami" and not x.despawned
            and x.level < self.config.max_level
        ]
        if self.config.upgrade_rule == "lowest" and candidates:
            lowest = min(p.shikigami[i].level for i in candidates)
            candidates = [i for i in candidates if p.shikigami[i].level == lowest]
        return candidates

    def _cmd_end_turn(self, cmd: dict) -> None:
        """结束回合：触发 on_turn_end，结算完后切换回合方并进入对方回合开始阶段。"""
        if self.state.winner is not None:
            return
        p = self.current
        self.emit("on_turn_end", player=self.state.active)
        self._drain_queue()  # 回合结束的队列效果结算完再换手
        if self.state.winner is not None:
            return
        self.state.active = 1 - self.state.active
        self._start_turn()

    def _start_turn(self) -> None:
        """回合开始阶段（对应 docs/rules.md「单个回合流程」）。

        流程：
        1. 当前玩家回合计数 +1，总回合计数 +1；检查长对局平局。
        2. 移除己方角色护甲/破甲（Phase 1 仅清护甲）。
        3. 已气绝己方式神倒计时 -1，归零复活。
        4-5. 鬼火重置为 0 再获得；emit on_orb_changed。
        6. 登记战斗区非召唤物式神延时移回。
        7. 触发 on_turn_start（延时时机）。
        8-9. 非灵咒倒计时 -1（锚点版已实现：形态倒计时，归零重置并触发）；灵咒倒计时随灵咒机制引入。
        10. 重置出击次数与瞬发名额；emit on_assaults_changed（若有能力监听）。
        11-12. （Phase 3+ 预留）直到回合结束时效果 / 敌方回合外效果。
        13. 执行延时战斗区移回与回合开始时效果（_drain_queue）。
        14. 抽 1：后手玩家第 1 回合抽 1；先手玩家从第 2 回合开始抽 1。
        15. 进入式神升级阶段。
        """
        if self.state.winner is not None:
            return
        p = self.current
        pi = self.state.active
        cfg = self.config
        # 1. 回合计数 +1；长对局平局检查
        first = self.state.turn == 1
        p.turn_count += 1
        self.state.turn += 1
        if self.state.turn >= 256:
            self._log("对局超过 255 个半回合，按长对局平局结算")
            self._set_pending_end(loser=-1)
            return
        # 2-15. 按步骤执行回合开始阶段
        self._turn_start_clear_shield(p)
        # "本回合"类卡牌光环（scope="turn"）在己方回合开始失效；其余 scope 条目不受影响
        p.card_auras[:] = [a for a in p.card_auras if a.get("scope") != "turn"]
        self._turn_start_revive(p, pi)
        self._turn_start_gain_orb(p, first, pi)
        pending_retreat = self._turn_start_schedule_retreat(p)
        self.emit("on_turn_start", player=pi)
        self._turn_start_countdown(p, pi)
        self._turn_start_reset_assaults(p, pi)
        if pending_retreat is not None:
            self._retreat(p, pending_retreat)
        self._drain_queue()
        self._turn_start_draw(p, pi)
        self._upgrade_phase(p)
        self.state.phase = "battle" if p.upgrades == 0 else "upgrade"
        self._log(f"—— {p.name} 的第 {p.turn_count} 回合（鬼火 {p.orb}）——")

    def _turn_start_clear_shield(self, p: PlayerState) -> None:
        """回合开始阶段 step 2：移除己方所有角色护甲/破甲（破甲 Phase 3；keep_shield 保留）。"""
        p.shield = 0
        for s in p.shikigami:
            if not s.keep_shield:
                s.shield = 0

    def _turn_start_countdown(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 8-9：己方式神非灵咒倒计时 -1（rules.md ch12）。

        归零流程（先即时插入结算、再重置/移除）见 _countdown_zero，与 countdown_delta
        动作共用；灵咒倒计时随灵咒机制引入。
        """
        for i, s in enumerate(p.shikigami):
            if s.countdown is None or not s.in_play:
                continue
            s.countdown -= 1
            if s.countdown <= 0:
                self._countdown_zero(pi, i)

    # ---------- 式神级倒计时框架（一名式神至多 1 个倒计时能力，新注册替换旧的） ----------

    @staticmethod
    def _clear_countdown(s: ShikigamiState) -> None:
        """清除式神当前倒计时能力（被替换/形态离场/气绝/一次型生效后）。"""
        s.countdown = None
        s.countdown_initial = None
        s.countdown_block = None
        s.countdown_once = False
        s.countdown_source = None

    def _register_countdown(self, s: ShikigamiState, *, initial: int,
                            block: EffectBlock | None, once: bool = False,
                            source: int | None = None) -> None:
        """注册倒计时能力三要素（初值/归零效果块/是否一次型），替换当前倒计时能力。"""
        s.countdown = initial
        s.countdown_initial = initial
        s.countdown_block = block if block is not None else EffectBlock()
        s.countdown_once = once
        s.countdown_source = source

    def _register_ability_countdown(self, pi: int, si: int) -> None:
        """能力进场（对局开始/升至 1 级/复活）与觉醒替换：注册式神当前能力
        （基础/觉醒）中的倒计时能力块（EffectBlock.countdown 非 None 者）。

        当前能力无倒计时块时清除原能力授予的倒计时（能力替换/离场语义）；
        形态授予的倒计时（来源 = 当前形态牌 id）不受影响。
        """
        p = self.state.players[pi]
        s = p.shikigami[si]
        if s.awakened is not None:
            blocks = self.db.cards[s.awakened].abilities
            source = s.awakened
        else:
            d = self.db.shikigami[s.id]
            blocks = d.all_abilities
            source = d.id
        found = next((b for b in blocks if b.countdown is not None), None)
        if s.form is None or s.countdown_source != s.form.id:
            self._clear_countdown(s)
        if found is not None:
            self._register_countdown(s, initial=found.countdown, block=found, source=source)

    def _countdown_zero(self, pi: int, si: int) -> None:
        """倒计时归零流程（rules.md ch12 流程 4 修订版；回合开始批次与 countdown_delta 共用）。

        1. 倒计时 ≤ 0 → 先即时插入结算 countdown_block.steps（此时倒计时仍为 0，
           块内对自身 countdown_delta 修正为 -0 空操作）；
        2. 生效后向 p.ext["countdown_history"] 追加来源 id（基础=式神 id /
           觉醒=觉醒牌 id / 形态=形态牌 id；大合奏、风韵雅乐用）；
        3. 结算后若仍持有该能力（未被替换/清除）：循环型重置为初值、一次型（once）移除。
        """
        p = self.state.players[pi]
        s = p.shikigami[si]
        block, once, initial, source = (s.countdown_block, s.countdown_once,
                                        s.countdown_initial, s.countdown_source)
        if block is not None and block.steps:
            card = s.form if (s.form is not None and s.form.id == source) else None
            cname = f"（《{self.db.cards[card.id].name}》）" if card is not None else ""
            self._log(f"{self.db.shikigami[s.id].name} 的倒计时效果生效{cname}")
            self._resolve_block(block, ExecContext(
                controller=pi, source=Ref(player=pi, shikigami=si), card=card,
                is_ability=True))  # 倒计时效果属式神能力（贯通继承判定）
            if source is not None:
                p.ext.setdefault("countdown_history", []).append(source)
        if block is not None and s.countdown_block is block:
            # 结算期间未被替换/清除：循环型重置为初始值；一次型（once）移除
            if once:
                self._clear_countdown(s)
            else:
                s.countdown = initial

    def _turn_start_revive(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 3：已气绝己方式神倒计时 -1，归零复活。"""
        for i, s in enumerate(p.shikigami):
            if s.defeated and not s.despawned and s.level >= 1:
                s.revive_countdown -= 1
                if s.revive_countdown <= 0:
                    s.defeated = False
                    s.health = s.max_health
                    self._register_ability_countdown(pi, i)  # 能力进场：复活重新注册倒计时能力
                    self._log(f"{self.db.shikigami[s.id].name} 复活")
                    self.emit("on_shikigami_revived",
                              shikigami=Ref(player=pi, shikigami=i), source=None, reason="倒计时")

    def _turn_start_gain_orb(self, p: PlayerState, first: bool, pi: int) -> None:
        """回合开始阶段 steps 4-5：鬼火重置为 0 再获得；emit on_orb_changed。"""
        cfg = self.config
        gain = cfg.first_turn_orb if first else self.cfg(pi, "orb_per_turn")
        if cfg.orb_cap is not None:
            gain = min(gain, cfg.orb_cap)
        old_orb = p.orb
        p.orb = 0
        p.orb += gain
        if p.orb != old_orb:
            self.emit("on_orb_changed", player=pi, old=old_orb, new=p.orb, reason="回合开始")

    def _turn_start_schedule_retreat(self, p: PlayerState) -> int | None:
        """回合开始阶段 step 6：登记战斗区非召唤物式神延时移回（召唤物留在战斗区）。"""
        if p.combat_index is not None and p.shikigami[p.combat_index].kind != "summon":
            return p.combat_index
        return None

    def _turn_start_reset_assaults(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 10：重置出击次数与瞬发名额；emit on_assaults_changed。"""
        old_assaults = p.assaults_left
        p.assaults_left = 1
        for q in self.state.players:
            q.fast_used = False
        if p.assaults_left != old_assaults:
            self.emit("on_assaults_changed", player=pi, old=old_assaults, new=p.assaults_left, reason="回合开始")

    def _turn_start_draw(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 14：抽 1（后手第 1 回合也抽；先手从第 2 回合开始抽）。"""
        if p.turn_count > 1 or self.state.active == 1:
            self.draw_cards(pi, self.cfg(pi, "draw_per_turn"))

    def _has_upgrade_target(self, p: PlayerState) -> bool:
        """当前玩家是否还有可升级的式神（用于自动判断升级阶段是否可跳过）。

        气绝或眩晕不影响升级资格（仍可升级）。
        """
        return any(
            s.kind == "shikigami" and not s.despawned
            and s.level < self.config.max_level
            for s in p.shikigami
        )

    def _upgrade_phase(self, p: PlayerState) -> None:
        """式神升级阶段：按规则赋予本回合升级机会。

        后手第 3 回合 / 先手第 7 回合各 +1 次（当回合共 2 次）。
        升级阶段本身只赋予机会，不自动升级；玩家通过 upgrade 指令消耗机会。
        当配置 auto_skip_upgrade=True 时（测试便利），不赋予机会并直接进入主要阶段。
        若本回合虽然有机会但已没有可升级的目标，也自动进入主要阶段。
        """
        cfg = self.config
        if cfg.auto_skip_upgrade:
            p.upgrades = 0
            return
        p.upgrades = 1
        e_first, e_second = cfg.extra_upgrade_turns
        pi = self.state.active
        if (pi == 0 and p.turn_count == e_first) or (pi == 1 and p.turn_count == e_second):
            p.upgrades += 1
        if p.upgrades > 0 and not self._has_upgrade_target(p):
            p.upgrades = 0

    # ==================== 伤害 / 抽牌 / 气绝（动作层共用管线） ====================

    def _ability_piercing(self, ctx: ExecContext) -> bool:
        """能力伤害的贯通继承：仅当伤害来自式神能力（is_ability：基础/觉醒/形态/延迟能力）
        且来源式神具有贯通时成立；卡牌效果伤害不继承（terminology.md「贯通」）。"""
        if not ctx.is_ability or ctx.source is None or ctx.source.shikigami is None:
            return False
        s = self.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        return self._has_keyword(s, "piercing")

    def deal_to_shikigami(self, ref: Ref, amount: int, source: Ref | None,
                          *, kind: str = "effect", piercing: bool = False) -> None:
        """对式神造成伤害（单事件伤害队列，走完整伤害事件流程）。"""
        self._run_damage_queue([_DamageEvent(source=source, victim=ref,
                                             amount=amount, kind=kind, piercing=piercing)])

    def deal_to_player(self, player_index: int, amount: int, source: Ref | None,
                       *, kind: str = "effect") -> None:
        """对牌手造成伤害（单事件伤害队列，走完整伤害事件流程）。"""
        self._run_damage_queue([_DamageEvent(source=source, victim=Ref(player=player_index),
                                             amount=amount, kind=kind)])

    def _run_damage_queue(self, events: list[_DamageEvent],
                          defer_defeats: list[tuple[Ref, Ref | None, str]] | None = None) -> None:
        """伤害事件队列：并行伤害、贯通溢出、伤害合并都在同一队列结算（rules.md 第五章）。

        每个事件依次经过时点批次：造成伤害前（穿刺）→ 伤害开始时 → 贯通修正 → 护甲计算前（屏障）→ 护甲计算 →
        护甲计算后 → 扣减生命前 → 合并 → 扣减生命（不屈）→ 伤害后。队列清空后按受伤顺序
        生成气绝事件（rules.md:207）；defer_defeats 给出时改为把受伤者追加到该列表、
        由调用方延后统一结算（随机分配伤害：气绝事件按延时时机在效果结束后结算）。
        子优先级批次（0/1/2/3）暂不拆事件名，待首个有优先级需求的监听者出现再拆。
        """
        dq: deque[_DamageEvent] = deque(events)
        victims: list[tuple[Ref, Ref | None, str]] = []  # (受伤式神, 来源, 气绝原因) 按受伤顺序
        while dq:
            ev = dq.popleft()
            self._damage_event_flow(ev, dq, victims)
            if self.state.winner is not None:
                return
        for ref, source, reason in victims:
            if defer_defeats is not None:
                defer_defeats.append((ref, source, reason))
            else:
                self.check_defeated(ref, source=source, reason=reason)

    def _emit_damage_batch(self, name: str, ev: _DamageEvent) -> None:
        """伤害时点批次（即时时机）；payload 携带 damage 可变对象供监听者修改伤害值。"""
        self.emit(name, damage=ev, victim=ev.victim, source=ev.source,
                  amount=ev.amount, kind=ev.kind)

    def _damage_event_flow(self, ev: _DamageEvent, dq: deque[_DamageEvent],
                           victims: list[tuple[Ref, Ref | None, str]]) -> None:
        p = self.state.players[ev.victim.player]
        s = p.shikigami[ev.victim.shikigami] if ev.victim.shikigami is not None else None
        if ev.amount <= 0:
            return  # 伤害值不大于 0：终止结算
        if s is not None and (s.defeated or s.despawned):
            return
        if s is None and p.defeated:
            return  # 气绝的牌手不再受到伤害
        # 批次 1：造成/受到伤害开始时（即时时机）
        if not ev.skip_early:
            # 批次 0：造成伤害前（即时时机）——穿刺（来源关键字）在此生效：移除目标
            # 的所有护甲/屏障，与本次伤害是否最终生效（免疫/归零/屏障）无关；适用于
            # 任意来源的伤害，含非战斗伤害（terminology.md「穿刺」；贯通溢出事件跳过本批次）
            self._emit_damage_batch("on_before_damage", ev)
            if ev.source is not None and ev.source.shikigami is not None:
                src = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
                if self._has_keyword(src, "pierce"):
                    holder = s if s is not None else p
                    if holder.shield > 0:
                        self._change_shield(ev.victim, -holder.shield, "穿刺")
                    if s is not None:
                        while self._has_keyword(s, "barrier"):
                            self._remove_keyword(s, "barrier")
            self._emit_damage_batch("on_damage_start", ev)
            if ev.amount <= 0 or (s is not None and s.defeated):
                return
            # 作用域战斗伤害免疫：仅免疫 combat/counter，且须命中授予时指定的作用域
            if ev.kind in ("combat", "counter") and s is not None and self._combat_immune(s):
                self._log(f"{self.db.shikigami[s.id].name} 免疫了本次战斗伤害")
                return
        skip_shield_calc = False
        skip_before_health = False
        # 批次 2：贯通修正（非反击伤害、伤害原因具有贯通、受伤者是式神）
        if ev.kind != "counter" and ev.piercing and s is not None:
            skip_shield_calc = True
            if s.shield > 0:
                absorbed = min(s.shield, ev.amount)
                ev.amount -= absorbed
                self._change_shield(ev.victim, -absorbed, "贯通修正")
            if ev.amount > s.health:
                # 伤害值改为当前生命，溢出量以同来源同原因新事件加入本队列（从护甲计算前开始）
                overflow = ev.amount - s.health
                ev.amount = s.health
                dq.append(_DamageEvent(source=ev.source, victim=Ref(player=ev.victim.player),
                                       amount=overflow, kind=ev.kind, skip_early=True))
            # 提前结算"扣减生命前"批次，后续不再结算该批次
            self._emit_damage_batch("on_before_health", ev)
            skip_before_health = True
            if ev.amount <= 0:
                return
        # 批次 3：护甲计算前（批次 3 = 关键字"屏障"）
        self._emit_damage_batch("on_before_shield", ev)
        if s is not None and ev.amount > 0 and "barrier" in s.one_shot_keywords:
            ev.amount = 0
            s.one_shot_keywords.remove("barrier")
            self._log(f"{self.db.shikigami[s.id].name} 的屏障抵消了伤害")
        if ev.amount <= 0:
            return
        # 批次 4：护甲计算（破甲 fragile 为独立流程，未引入，见 model.py 注释）
        if not skip_shield_calc:
            holder = s if s is not None else p
            if holder.shield > 0:
                absorbed = min(holder.shield, ev.amount)
                ev.amount -= absorbed
                self._change_shield(ev.victim, -absorbed, "护甲计算")
            if ev.amount <= 0:
                return  # 护甲完全吸收：终止结算
        # 批次 5：护甲计算后（伤害转移/改为非伤害能力锚点）
        self._emit_damage_batch("on_after_shield", ev)
        # 批次 6：扣减生命前（已被贯通修正提前结算则跳过）；此刻起视为造成/受到过伤害，伤害值锁定
        if not skip_before_health:
            self._emit_damage_batch("on_before_health", ev)
        if ev.amount <= 0:
            return
        # 批次 7：合并——队列中 (来源, 受伤者, 原因) 均相同的伤害事件合并进最前者
        for other in list(dq):
            if other.source == ev.source and other.victim == ev.victim and other.kind == ev.kind:
                ev.amount += other.amount
                dq.remove(other)
        # 批次 8：扣减生命
        if s is not None:
            # 不屈：生命 > 1 且伤害 >= 当前生命 → 保留 1 点生命，消耗全部一次性不屈
            # （生命 = 1 时不触发；持续/永久不屈不移除，回血后可再次触发）
            if ev.amount >= s.health > 1 and self._has_keyword(s, "unyielding"):
                ev.amount = s.health - 1
                s.one_shot_keywords[:] = [k for k in s.one_shot_keywords if k != "unyielding"]
                self._log(f"{self.db.shikigami[s.id].name} 的【不屈】生效，保留 1 点生命")
            s.health -= ev.amount
            self._log(f"{self.db.shikigami[s.id].name} 受到 {ev.amount} 点伤害（剩余生命 {s.health}）")
            victims.append((ev.victim, ev.source, "战斗" if ev.kind in ("combat", "counter") else "伤害"))
            self.emit("on_damage", victim=ev.victim, amount=ev.amount, source=ev.source, kind=ev.kind)
        else:
            p.health -= ev.amount
            self._log(f"{p.name} 受到 {ev.amount} 点伤害（剩余生命 {p.health}）")
            self.emit("on_player_damaged", player=ev.victim.player, amount=ev.amount,
                      source=ev.source, kind=ev.kind)
            if p.health <= 0:
                # 牌手气绝 → "待结束"：已入队的触发能力不再执行，此后非系统操作不再触发
                self._set_pending_end(loser=ev.victim.player, defeat=True)

    def _combat_immune(self, s: ShikigamiState) -> bool:
        """式神在当前战斗上下文中是否免疫战斗伤害（作用域由授予效果指定）。"""
        if not self._battle_stack:
            return False
        current = self._battle_stack[-1]
        for e in s.immunities:
            if e.get("kind") != "combat_damage":
                continue
            if e.get("battle") == current or (e.get("nested") and e.get("battle") in self._battle_stack):
                return True
        return False

    def check_defeated(self, ref: Ref, source: Ref | None = None, reason: str | None = None) -> None:
        """生成并结算式神气绝事件（要素：来源、气绝者、原因）。

        当前机制范围内的流程：消灭形态牌 → 移除所有非永久 buff（临时修正/护甲）→
        非召唤物获得倒计时 3：复活并移动至准备区（召唤物直接离场）→ 气绝后（延时时机）。
        气绝前 1/2/3、替身、击杀标记等时点批次待相应机制引入（见 docs/rules.md）。
        """
        s = self.state.players[ref.player].shikigami[ref.shikigami]
        if s.defeated or s.health > 0:
            return
        owner = self.state.players[ref.player]
        # 气绝流程 step 3（rules.md 第七章）：先消灭形态牌——此时能力尚未离场（step 6），
        # 一目连类"形态离场时触发"能力仍会收集（先触发后执行，结算时不再复查持有者状态）
        if s.form is not None:
            self._destroy_form(owner, ref.shikigami, reason="defeat")
        s.defeated = True
        self._clear_countdown(s)  # 气绝清除倒计时能力（大天狗记录的法术随之丢失，复活后不再具有）
        s.ext.pop("recorded_card", None)
        s.shield = 0
        s.temp_power = 0  # 临时修正气绝时清除（复活只保留永久修正）
        s.temp_health = 0
        s.keywords.clear()  # 持续/一次性关键字与免疫条目气绝时清除；永久关键字保留（复活自动重新获得）
        s.one_shot_keywords.clear()
        s.immunities.clear()
        s.attack_buffs.clear()  # 攻击后到期强化挂账随临时修正一并清空（keep_shield/awakened 保留）
        s.delayed.clear()  # 绑定式神的一次性延迟能力气绝时消失（会；变形离场保留——变形未实现）
        s.health = 0
        name = self.db.shikigami[s.id].name
        if s.kind == "summon":
            # 召唤物死亡即离场：不进气绝复活流程
            self._despawn(owner, ref.shikigami)
        else:
            if owner.combat_index == ref.shikigami:
                owner.combat_index = None  # 气绝者移动至准备区
            s.revive_countdown = self.config.revive_countdown
            self._log(f"{name} 气绝")
        self.emit("on_shikigami_defeated", victim=ref, source=source, reason=reason,
                  battle=self._battle_stack[-1] if self._battle_stack else None)

    def _set_pending_end(self, loser: int | None = None, defeat: bool = False) -> None:
        """把游戏标记为"待结束"。

        loser=-1 表示长对局平局；loser>=0 表示该玩家判负；defeat=True 时额外标记牌手气绝。
        当前事件结算完成后由 `_drain_queue` 把 pending_end 正式转为 winner。
        """
        if self.state.winner is not None or self.state.pending_end:
            return
        if defeat and loser is not None and loser >= 0:
            self.state.players[loser].defeated = True  # 气绝的牌手不再受到伤害和治疗
        self.state.pending_end = True
        self.state.pending_loser = loser

    def draw_cards(self, player_index: int, count: int) -> None:
        """效果抽牌（Phase 1 简化版）。

        完整规则（docs/rules.md 抽牌事件流程）包含"获得卡牌前"时机、多张结附灵咒的
        后发先至结算；Phase 1 最小实现直接循环从牌库顶移入手牌并 emit on_draw。
        牌库为空时判负。
        """
        p = self.state.players[player_index]
        for _ in range(count):
            if not p.deck:
                # 牌库为空时执行抽牌立即落败（可能有效果改变此判定；判负非气绝）
                if self.state.winner is None:
                    self._log(f"{p.name} 牌库抽空，判负")
                self._set_pending_end(loser=player_index)
                return
            self.move_card(p, p.deck[0], "hand")
        self.emit("on_draw", player=player_index, count=count)

    # ==================== 事件与触发 ====================

    def emit(self, name: str, **payload: Any) -> None:
        """发出事件并收集触发效果。

        结算时机：EffectBlock.timing 覆盖优先，否则跟随 core.events.EVENT_TIMING。
        即时时机（insert）会形成临时队列：同一事件触发的全部能力先被收集，
        收集完成后再依次执行；延时时机（queue）则加入当前效果队列，由外层 _drain_queue
        在合适时机统一结算。
        对局已进入"待结束"（pending_end，含 winner 已定）后，非系统操作不再触发
        （事件仍记入 history；已入队能力由 _drain_queue 清空）。
        """
        if name not in CORE_EVENTS and name not in self.db.custom_events:
            raise ValueError(f"未声明的事件名: {name}（核心事件见 core/events.py，自定义事件见 db/events.yaml）")
        self.history.append(name)
        if self.state.winner is not None or self.state.pending_end:
            return
        seq = self.state.next_emit_seq()
        event = {"name": name, "_emit": seq, **payload}
        insert_queue: list[_Pending] = []
        for pend in self._collect(event):
            timing = pend.block.timing or EVENT_TIMING.get(name, "queue")
            if timing == "insert":
                insert_queue.append(pend)
            else:
                self.queue.append(pend)
        for pend in insert_queue:
            self._resolve_pending(pend)

    def _collect(self, event: dict) -> list[_Pending]:
        """收集监听该事件的触发效果，并按规则顺序排序。

        触发顺序：
        1. 当前回合玩家的能力先于对方；
        2. 同一玩家内按式神上阵顺序（即 shikigami 列表下标）；
        3. 响应牌仅非回合方检查，按所属式神从左往右排序（中立响应牌排在最后）。

        先触发后执行：能力在这里只被收集，不立即结算；执行时不再检测条件、
        触发者气绝仍有效。响应牌例外——结算时仍需复查条件、鬼火、消耗、使用者。
        """
        out: list[_Pending] = []
        for pi in (self.state.active, 1 - self.state.active):
            out.extend(self._collect_abilities(event, pi))
            # 第三收集来源（式神能力之后、响应牌之前，docs/enhance-design.md 第一节）：
            # 卡牌触发器（全库游离触发块）与一次性临时触发（按注册顺序，只收一次）
            out.extend(self._collect_card_triggers(event, pi))
            if pi == self.state.active:
                out.extend(self._collect_temp_grants(event))
            if pi != self.state.active and self._response_used_emit != event["_emit"]:
                out.extend(self._collect_responses(event, pi))
        return out

    def _collect_card_triggers(self, event: dict, pi: int) -> list[_Pending]:
        """收集卡牌触发器（CardDef.triggers）：不依附在场式神的游离触发块，

        每次 emit 全库扫描（覆盖生成牌/未入手牌，enhance-design"按数据库全量注册"语义）。
        双方各自以 controller=pi 匹配一次（victim_side 等相对条件决定归属哪方）。
        """
        out: list[_Pending] = []
        for cdef in self.db.cards.values():
            for block in cdef.triggers:
                if block.when != event["name"]:
                    continue
                if self._match(block.condition, event, pi):
                    out.append(_Pending(block, ExecContext(
                        controller=pi, event=event, card_id=cdef.id)))
        return out

    def _collect_temp_grants(self, event: dict) -> list[_Pending]:
        """收集一次性临时触发（state.temp_grants）：战斗绑定者只响应本战斗内的事件。"""
        out: list[_Pending] = []
        for grant in self.state.temp_grants:
            if grant.block.when != event["name"]:
                continue
            if grant.battle is not None and event.get("battle") != grant.battle:
                continue
            if self._match(grant.block.condition, event, grant.controller, holder=grant.holder):
                out.append(_Pending(grant.block, ExecContext(
                    controller=grant.controller, source=grant.holder, event=event),
                    temp_grant=grant))
        return out

    def _resolve_pending(self, pend: _Pending) -> None:
        """结算一个待触发项；一次性临时触发结算后 uses-1，归零移除（按对象身份比较）。"""
        self._resolve_block(pend.block, pend.ctx)
        grant = pend.temp_grant
        if grant is None:
            return
        idx = next((i for i, g in enumerate(self.state.temp_grants) if g is grant), None)
        if idx is None:
            return  # 已在结算期间被移除（如所属战斗的终止点清理）
        grant.uses -= 1
        if grant.uses <= 0:
            self.state.temp_grants.pop(idx)

    def _collect_abilities(self, event: dict, pi: int) -> list[_Pending]:
        """收集玩家 pi 的式神被动能力（已觉醒的式神改读觉醒牌的觉醒能力块；
        结附形态时追加形态牌的形态能力块——觉醒替换不覆盖形态能力）。"""
        out: list[_Pending] = []
        p = self.state.players[pi]
        for si, s in enumerate(p.shikigami):
            if s.awakened is not None:
                blocks = list(self.db.cards[s.awakened].abilities)
            else:
                blocks = list(self.db.shikigami[s.id].all_abilities)
            if s.form is not None:
                blocks += self.db.cards[s.form.id].abilities
            for ability in blocks:
                if ability.countdown is not None:
                    continue  # 倒计时能力块不作事件监听（由倒计时框架归零时结算）
                if ability.when != event["name"]:
                    continue
                if not s.in_play:
                    # 0 级未在场能力不触发；个别能力标记为未升级也可触发（书翁/三尾狐类）
                    if s.defeated or s.despawned or not ability.trigger_when_not_in_play:
                        continue
                if self._match(ability.condition, event, pi, holder=Ref(player=pi, shikigami=si)):
                    out.append(_Pending(ability, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si), event=event,
                        is_ability=True)))
            # 绑定式神的一次性延迟能力（会）：先触发后执行，收集即消耗；气绝时已清除
            for entry in s.delayed:
                block = entry["block"]
                if block.when != event["name"] or not s.in_play:
                    continue
                if self._match(block.condition, event, pi, holder=Ref(player=pi, shikigami=si)):
                    chosen = [entry["chosen"]] if entry.get("chosen") is not None else []
                    out.append(_Pending(block, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si),
                        event=event, chosen=chosen, is_ability=True)))
                    entry["uses"] -= 1
            s.delayed[:] = [e for e in s.delayed if e["uses"] > 0]
        return out

    def _collect_responses(self, event: dict, pi: int) -> list[_Pending]:
        """收集玩家 pi 的响应牌（调用方需已确认其为非回合方且本时机未占用名额）。

        响应 = 敌方回合满足条件则必定使用（引擎自动结算，不询问玩家）。
        同一时机（一次事件生成）至多成功结算一张；式神气绝不影响其手牌中响应牌的队列位置。
        """
        out: list[_Pending] = []
        p = self.state.players[pi]
        candidates: list[tuple[int, CardInstance, EffectBlock, int | None]] = []
        for card in p.hand:
            cdef = self.db.cards[card.id]
            eb = cdef.effects
            if "trigger" not in cdef.keywords or eb.when != event["name"]:
                continue
            si = self._find_shikigami(p, cdef.shikigami) if cdef.shikigami is not None else None
            if cdef.shikigami is not None:
                if si is None:
                    continue  # 对应式神未出战
                s = p.shikigami[si]
                if s.defeated and not cdef.playable_when_defeated:
                    continue  # 对应式神气绝且无"气绝时可用"
                if s.level < cdef.level:
                    continue  # 响应其余要求照常：等级不足不可用
            # 瞬发：每（半）回合各自第一张免费，其余照常支付（含 mods.cost_delta）
            cost = self._effective_cost(p, cdef, card=card)
            if p.orb < cost:
                continue  # 没留住鬼火
            if not self._match(eb.condition, event, pi):
                continue
            # 按所属式神从左往右排序（中立响应牌排在最后）；同式神保持手牌顺序
            order = si if si is not None else len(p.shikigami)
            candidates.append((order, card, eb, si))
        # 带 choose 目标的响应牌：结算时自动选择事件中的被攻击者（rules.md:36），
        # 不在合法池则按无目标结算（自动使用而没有效果）——见 _resolve_block 响应前置。
        candidates.sort(key=lambda c: c[0])
        for _, card, eb, si in candidates:
            out.append(_Pending(eb, ExecContext(
                controller=pi,
                source=Ref(player=pi, shikigami=si) if si is not None else None,
                card=card, event=event, triggered=True)))
        return out

    def _match(self, condition: dict | None, event: dict, controller: int,
               holder: Ref | None = None) -> bool:
        """条件迷你语言判定（实现见 targets.match_condition）。"""
        return targets.match_condition(self, condition, event, controller, holder)

    # ==================== 效果块结算 ====================

    def _settle_response_card(self, p: PlayerState, cdef: CardDef, ctx: ExecContext) -> bool:
        """响应牌（ctx.triggered=True）的额外开销与限制：复查、支付、插入使用分派。

        - 同一时机（event._emit）至多成功结算一张；
        - 从收集到结算之间局面可能已变化，必须复查手牌、条件、等级、鬼火；
        - 复查失败返回 True（短路），不占用本时机的响应名额；
        - 成功结算后支付费用、占用名额、emit on_trigger，然后按卡牌类型分派：
          战斗牌/形态牌走插入使用（_apply_response_combat / _play_form_card）后
          返回 True（短路），其余移入手牌到墓地后返回 False（调用方按 steps 结算）。
        """
        emit_id = (ctx.event or {}).get("_emit")
        if emit_id is not None and self._response_used_emit == emit_id:
            return True  # 同一时机至多成功结算一张响应牌（复查失败不占名额）
        # 收集到结算之间局面可能已变化：响应牌结算时必须复查条件、鬼火、消耗、使用者
        if ctx.card not in p.hand:
            return True
        if ctx.event is not None and not self._match(cdef.effects.condition, ctx.event, ctx.controller):
            return True
        si: int | None = None
        if cdef.shikigami is not None:
            si = self._find_shikigami(p, cdef.shikigami)
            if si is None:
                return True
            s = p.shikigami[si]
            if s.defeated and not cdef.playable_when_defeated:
                return True
            if s.level < cdef.level:
                return True
        # 尘缚之阵：响应战斗牌插入使用会把所属式神移入战斗区；若这会替换被锁定的
        # 战斗区式神，则该响应不可用（复查失败不占名额）——响应牌能否响应取决于
        # 其效果本身是否导致战斗区换人（terminology.md「战斗区锁定」）
        if (cdef.card_type == "combat" and si is not None
                and p.combat_index is not None and p.combat_index != si
                and self._combat_zone_locked(ctx.controller)):
            self._log(f"{p.name} 的响应牌《{cdef.name}》受尘缚之阵锁定，未能触发")
            return True
        cost = self._effective_cost(p, cdef, card=ctx.card)
        if p.orb < cost:
            self._log(f"{p.name} 鬼火不足，响应牌《{cdef.name}》未能触发")
            return True
        p.orb -= cost
        if self._fast_applies(p, cdef, ctx.card):
            p.fast_used = True
        # choose 目标的响应牌：自动选择事件中的被攻击者（rules.md:36"执行效果时选择目标"；
        # 不在合法池则无目标——自动使用而没有效果，如古尘之盾"对其自动使用"）
        if cdef.target.kind == "choose" and ctx.event is not None:
            v = ctx.event.get("victim")
            if isinstance(v, Ref) and v in targets.pool_refs(self, cdef.target.pool, ctx.controller):
                ctx.chosen = [v]
        self._response_used_emit = emit_id  # 成功结算才占用本时机的响应名额
        self._log(f"{p.name} 的响应牌《{cdef.name}》触发")
        self.emit("on_trigger", player=ctx.controller, uid=ctx.card.uid)
        if cdef.card_type == "combat" and si is not None:
            # 响应战斗牌插入使用（rules.md:52）：不发起新战斗，加成绑定被插入的战斗
            self._apply_response_combat(p, si, ctx.card, cdef)
            self.emit("on_card_played", player=ctx.controller, uid=ctx.card.uid)
            return True
        if cdef.card_type == "form" and si is not None:
            # 响应形态牌插入使用：立即结附（风符·瞬）；牌不进墓地，形态离场才进
            # 形态牌的进场时效果镜像主动使用的形态分支（响应形态同样结算）
            self._play_form_card(p, si, ctx.card, cdef, ctx.controller, ctx.chosen)
            self.emit("on_card_played", player=ctx.controller, uid=ctx.card.uid)
            return True
        self.move_card(p, ctx.card, "graveyard")
        return False

    def _resolve_block(self, block: EffectBlock, ctx: ExecContext) -> None:
        """结算一个效果块：先处理响应牌的额外开销与限制（_settle_response_card），再依次执行 steps。

        按 block.steps 顺序执行动作。mode="interleaved" 时每步后清空队列，
        允许其它效果插入；mode="atomic" 时步骤连发，队列留到块外统一结算。
        """
        if ctx.triggered and ctx.card is not None:
            p = self.state.players[ctx.controller]
            cdef = self.db.cards[ctx.card.id]
            if self._settle_response_card(p, cdef, ctx):
                return
        for step in block.steps:
            self._run_step(step, ctx)
            if block.mode == "interleaved":
                self._drain_queue()  # 步骤之间允许其它效果结算
        # mode == "atomic"：步骤连发，队列留到块外统一结算
        if ctx.triggered and ctx.card is not None:
            # 响应使用与主动使用生成同样的"卡牌的使用事件"（使用后1，延时时机）
            self.emit("on_card_played", player=ctx.controller, uid=ctx.card.uid)

    def _run_step(self, step: Step, ctx: ExecContext) -> None:
        fn = actions.ACTIONS.get(step.op)
        if fn is None:
            raise IllegalAction(f"未知动作: {step.op}")  # 加载时已校验，此处双保险
        params = dict(step.model_extra or {})
        if step.condition is not None:
            if "condition" in self._op_params(step.op, fn):
                # op 自身声明 condition 参数（delay_grant 的延迟块触发条件）：作为参数传递
                params["condition"] = step.condition
            elif not self._match(step.condition, ctx.event or {}, ctx.controller,
                                 holder=ctx.source):
                return  # Step 级条件不满足：跳过该步（条件迷你语言，见 targets.match_condition）
        refs = targets.resolve(self, step.target, ctx)
        if isinstance(params.get("amount"), dict):
            # 动态数值（enhance 快照 / shield_of / power_of）：以 ctx 来源式神求值（援护/古尘之壁）
            src = (self.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
                   if ctx.source is not None and ctx.source.shikigami is not None else None)
            params["amount"] = self._step_amount(step, ctx.card, src)
        fn(self, ctx, targets=refs, **params)

    def _op_params(self, op: str, fn) -> frozenset:
        """op 函数的参数名集合（缓存；用于区分 Step 级 condition 与 op 的 condition 参数）。"""
        cached = self._op_param_cache.get(op)
        if cached is None:
            import inspect
            cached = frozenset(inspect.signature(fn).parameters)
            self._op_param_cache[op] = cached
        return cached

    def _drain_queue(self) -> None:
        """循环结算效果队列，带死循环保护。

        若游戏已进入"待结束"状态，不再执行已入队的触发式能力；队列处理完成后，
        把 pending_end 正式转为 winner，进入游戏结束阶段。
        """
        guard = 0
        while self.queue:
            if self.state.pending_end:
                self.queue.clear()
                break
            guard += 1
            if guard > MAX_QUEUE_ITERATIONS:
                self.queue.clear()
                raise RuntimeError("效果队列疑似死循环，已强制清空")
            pend = self.queue.popleft()
            self._resolve_pending(pend)
        # 待结束状态 → 正式结束
        if self.state.pending_end and self.state.winner is None:
            if self.state.pending_loser == -1:
                self.state.winner = -1
                self._log("对局超过最大回合数，平局结束")
            else:
                self.state.winner = 1 - self.state.pending_loser
                self._log(f"{self.state.players[self.state.winner].name} 获胜！")
            self.state.pending_end = False

    # ==================== 内部工具 ====================

    def _find_shikigami(self, p: PlayerState, defn_id: int) -> int | None:
        for i, s in enumerate(p.shikigami):
            if s.id == defn_id:
                return i
        return None

    def _own_shikigami(self, p: PlayerState, i: int) -> ShikigamiState:
        if not 0 <= i < len(p.shikigami):
            raise IllegalAction("式神序号无效")
        s = p.shikigami[i]
        if s.defeated or s.despawned:
            raise IllegalAction(f"{self.db.shikigami[s.id].name} 无法行动（气绝/已离场）")
        return s

    def _log(self, msg: str) -> None:
        self.state.log.append(msg)
