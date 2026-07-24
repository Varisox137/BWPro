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
from core.events import EVENT_TIMING
from core.model import CardInstance, GameState, PlayerState, Ref, ShikigamiState
from db.schema import EffectBlock, PlayMethod, Step


class IllegalAction(Exception):
    """指令不合法（费用/等级/目标/时机等）。"""


MAX_QUEUE_ITERATIONS = 1000  # 效果队列死循环保护（DIY 安全网）


@dataclass
class ExecContext:
    controller: int  # 效果归属玩家
    source: Ref | None = None  # 来源式神（中立牌无来源，为 None）
    card: CardInstance | None = None  # 来源卡牌实例
    event: dict[str, Any] | None = None  # 触发来源事件 payload
    chosen: list[Ref] | None = None  # 玩家选择的目标
    triggered: bool = False  # 是否为响应牌触发（结算时支付鬼火并消耗手牌）


@dataclass
class _Pending:
    block: EffectBlock
    ctx: ExecContext


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
        结果不小于 0。
        """
        base = method.cost if (method and method.cost is not None) else cdef.cost
        delta = (method.cost_delta if method else 0)
        if card is not None:
            delta += int(card.mods.get("cost_delta", 0))
        cost = max(0, base + delta)
        if "fast" in cdef.keywords and not p.fast_used:
            cost = 0
        return cost

    def _exec_context(self, **kwargs) -> ExecContext:
        """构造一个 ExecContext；供调试指令和内部复用。"""
        return ExecContext(**kwargs)

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
        for p in self.state.players:
            if p.shikigami:
                p.shikigami[0].level = 1  # 最左侧式神自动升至 1 级，其余 0 级未在场
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
            "skip_upgrade": self._cmd_skip_upgrade,
            "end_turn": self._cmd_end_turn,
            "mulligan": self._cmd_mulligan,
            "ready": self._cmd_ready,
        }
        handler = handlers.get(op)
        if handler is None:
            raise IllegalAction(f"未知指令: {op}")
        if self.state.phase == "mulligan" and op not in ("mulligan", "ready"):
            raise IllegalAction("调度阶段：请先完成调度（mulligan/ready）")
        if self.state.phase == "upgrade" and op not in ("upgrade", "skip_upgrade"):
            raise IllegalAction("升级阶段：请先完成升级或跳过（upgrade/skip_upgrade）")
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
        ctx = self._exec_context(controller=cmd.get("player", self.state.active))
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
        self._check_battle_start()

    def _cmd_ready(self, cmd: dict) -> None:
        """确认完成调度（可以不用满次数）。双方均确认后进入对战阶段。"""
        if self.state.phase != "mulligan":
            raise IllegalAction("当前不在调度阶段")
        p = self.state.players[self._mulligan_player(cmd)]
        p.mulligan_done = True
        self._log(f"{p.name} 完成调度")
        self._check_battle_start()

    def _mulligan_player(self, cmd: dict) -> int:
        pi = cmd.get("player")
        if pi not in (0, 1):
            raise IllegalAction("调度指令需要 player（0/1）")
        return pi

    def _check_battle_start(self) -> None:
        if all(p.mulligan_done for p in self.state.players):
            self._begin_battle()

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
        if "fast" in cdef.keywords:
            p.fast_used = True
        p.orb -= cost
        how = f"（{method.text or method.id}）" if method else ""
        self._log(f"{p.name} 使用了《{cdef.name}》{how}")
        if cdef.card_type == "form":
            # 形态牌：从手牌/原区域移除（不进入任何区域），以该卡牌数据给式神结附形态；
            # 形态离场时变为卡牌并置入墓地。此过程不是“卡牌移动事件”。
            if si is None:
                raise IllegalAction("形态牌必须有所属式神")
            for zname, z in p.zones.items():
                if card in z:
                    removed_seq = card.hand_seq
                    z.remove(card)
                    if zname == "hand":
                        self._compact_hand_seq(p, removed_seq)
                    break
            self._attach_form(p, si, card, cdef)
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
        self.emit("on_card_played", player=self.state.active, uid=uid)

    def _combat_card_stats(self, block: EffectBlock) -> tuple[int, int]:
        """从战斗牌的效果块中提取战力与一次性护甲数值（仅统计目标为 self 的 buff_power / gain_shield）。"""
        power = 0
        shield = 0
        for step in block.steps:
            if step.target is not None and step.target.kind != "self":
                continue
            amount = (step.model_extra or {}).get("amount", 0)
            if step.op == "buff_power":
                power += amount
            elif step.op == "gain_shield":
                shield += amount
        return power, shield

    def _resolve_combat_card(self, p: PlayerState, si: int, card: CardInstance,
                             cdef: CardDef, method: PlayMethod | None) -> None:
        """战斗牌完整事件流程：移入战斗区、获得战力/护甲、战斗前、战斗伤害、战斗后、进墓地。

        战斗牌提供的力量（战力）在战斗后清除；提供的护甲/破甲会保留，并按即时时机
        发出 on_shield_changed 事件。
        """
        s = p.shikigami[si]
        if not s.in_play:
            raise IllegalAction("该式神未在场，无法使用战斗牌")
        block = method.effects if (method and method.effects is not None) else cdef.effects
        power, shield = self._combat_card_stats(block)
        self._enter_combat(p, si)
        if power:
            s.combat_power += power
        if shield:
            old = s.shield
            s.shield += shield
            self.emit(
                "on_shield_changed",
                target=Ref(player=self.state.active, shikigami=si),
                old=old,
                new=s.shield,
                reason="combat_card",
            )
        atk_ref = Ref(player=self.state.active, shikigami=si)
        defender_idx = 1 - self.state.active
        d = self.state.players[defender_idx]
        self.emit(
            "on_before_assault",
            attacker=atk_ref,
            victim=Ref(player=defender_idx, shikigami=d.combat_index),
        )
        self._drain_queue()
        if s.defeated or s.despawned:
            self._log("攻击方在战斗牌结算前气绝/离场，战斗中止")
        else:
            vic_idx = d.combat_index
            if vic_idx is None:
                self.deal_to_player(defender_idx, s.eff_power, atk_ref)
            else:
                vic_ref = Ref(player=defender_idx, shikigami=vic_idx)
                vic_s = d.shikigami[vic_idx]
                a_eff, d_eff = s.eff_power, vic_s.eff_power
                self._hurt_shikigami(atk_ref, d_eff, vic_ref)
                self._hurt_shikigami(vic_ref, a_eff, atk_ref)
                self.check_defeated(atk_ref, source=vic_ref, reason="战斗")
                self.check_defeated(vic_ref, source=atk_ref, reason="战斗")
        self.emit("on_after_assault", attacker=atk_ref)
        s.combat_power = 0
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

    def move_card(self, p: PlayerState, card: CardInstance, to_zone: str) -> None:
        """把卡牌移动到指定区域；区域不存在则创建（区域系统保留扩展空间）。

        Phase 1 简化：直接变更区域，不触发卡牌移动后灵咒效果，不检查区域上限。
        完整规则见 docs/rules.md「卡牌移动事件流程」。
        若 card 不在任何已知区域（如测试直接注入手牌），直接追加到目标区域。
        移入手牌时（重新）分配 hand_seq；从手牌移出时压缩剩余编号。
        """
        from_zone = None
        for zname, z in p.zones.items():
            if card in z:
                from_zone = zname
                z.remove(card)
                break
        if from_zone == "hand":
            self._compact_hand_seq(p, card.hand_seq)
        if to_zone == "hand":
            self._assign_hand_seq(p, card)
        p.zones.setdefault(to_zone, []).append(card)

    # ---------- 出击 / 移动 ----------

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
        if p.orb < 1:
            raise IllegalAction("出击需要 1 点鬼火")
        p.orb -= 1
        p.assaults_left -= 1
        self._enter_combat(p, i)
        atk_ref = Ref(player=self.state.active, shikigami=i)
        defender_idx = 1 - self.state.active
        d = self.state.players[defender_idx]
        self.emit(
            "on_before_assault",
            attacker=atk_ref,
            victim=Ref(player=defender_idx, shikigami=d.combat_index),
        )
        self._drain_queue()  # 出击宣言触发的 insert 效果必须在伤害结算前执行完
        # 攻击者可能被前述 insert 效果气绝/离场；同一列表元素，复用 s 检查最新状态
        if s.defeated or s.despawned:
            self._log("攻击方在伤害结算前气绝/离场，出击中止")
            return
        vic_idx = d.combat_index  # 结算前重新读取（可能被前置效果改变）
        if vic_idx is None:
            # 敌方战斗区无人：直接攻击牌手
            self.deal_to_player(defender_idx, s.eff_power, atk_ref)
        else:
            vic_ref = Ref(player=defender_idx, shikigami=vic_idx)
            vic_s = d.shikigami[vic_idx]
            # 战斗伤害并行结算：按（反击，攻击）顺序生成伤害事件，气绝判定同序。
            # 反击 = 被攻击者对攻击者；攻击 = 攻击者对被攻击者；数值均等于自身有效力量。
            a_eff, d_eff = s.eff_power, vic_s.eff_power
            self._hurt_shikigami(atk_ref, d_eff, vic_ref)
            self._hurt_shikigami(vic_ref, a_eff, atk_ref)
            self.check_defeated(atk_ref, source=vic_ref, reason="战斗")
            self.check_defeated(vic_ref, source=atk_ref, reason="战斗")
        # 攻击方存活则驻留战斗区（充当"墙"）；若已气绝/离场，_enter_combat 已处理
        self.emit("on_after_assault", attacker=atk_ref)

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
        if cdef.form_power is not None:
            s.base_power = cdef.form_power
        if cdef.form_health is not None:
            s.base_health = cdef.form_health
        s.health = s.max_health
        self._log(f"{self.db.shikigami[s.id].name} 结附形态《{cdef.name}》")
        self.emit("on_form_attached", player=self.state.active, shikigami=i, uid=card.uid)

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
        self.move_card(p, old, "graveyard")
        d = self.db.shikigami[s.id]
        s.base_power = d.power
        s.base_health = d.health
        s.health = s.max_health
        self._log(f"{d.name} 的形态《{cdef.name}》被消灭（原因：{reason}）")
        self.emit("on_form_destroyed", player=self.state.active, shikigami=i,
                  uid=old.uid, reason=reason)

    # ---------- 升级 / 结束回合 ----------

    def _cmd_upgrade(self, cmd: dict) -> None:
        """升级指令：仅在升级阶段可用。消耗 1 次升级机会，升级完成后若机会用尽则进入主要阶段。"""
        if self.state.phase != "upgrade":
            raise IllegalAction("当前不在升级阶段")
        p = self.current
        i = cmd.get("index")
        if p.upgrades < 1:
            raise IllegalAction("本回合已没有升级机会")
        s = self._own_shikigami(p, i)
        if s.kind != "shikigami":
            raise IllegalAction("召唤物不能升级")
        if s.level >= self.config.max_level:
            raise IllegalAction("已达最高等级")
        rule = self.config.upgrade_rule
        if rule in ("lowest", "ordered"):
            candidates = [
                x for x in p.shikigami
                if not x.defeated and not x.despawned and x.kind == "shikigami" and x.level < self.config.max_level
            ]
            if rule == "lowest" and candidates:
                # 标准规则：选一名未满级且等级同为己方最低的式神
                lowest = min(x.level for x in candidates)
                if s.level != lowest:
                    raise IllegalAction("只能升级当前等级最低的式神")
            if rule == "ordered" and candidates and s is not candidates[0]:
                raise IllegalAction("须按上阵顺序升级")
        # rule == "free"：无限制（不进入任何分支）
        s.level += 1
        p.upgrades -= 1
        name = self.db.shikigami[s.id].name
        self._log(f"{p.name} 将 {name} 升至 {s.level} 级")
        self.emit("on_upgrade", player=self.state.active, shikigami=i, level=s.level)
        if p.upgrades == 0:
            self.state.phase = "battle"

    def _cmd_skip_upgrade(self, cmd: dict) -> None:
        """跳过剩余升级机会，直接进入主要阶段。"""
        if self.state.phase != "upgrade":
            raise IllegalAction("当前不在升级阶段")
        self.state.phase = "battle"

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
        8-9. （Phase 3+ 预留）非灵咒/灵咒倒计时 -1。
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
        # 先手首个回合判断：turn==1 表示这是游戏开始后的第一个半回合
        first = self.state.turn == 1
        p.turn_count += 1
        self.state.turn += 1
        # 1. 长对局平局：总回合计数 >=256 强制结束
        if self.state.turn >= 256:
            self._log("对局超过 255 个半回合，按长对局平局结算")
            self._declare_draw()
            return
        # 2. 移除己方所有角色（牌手及式神）的护甲（破甲/战力/乏力 Phase 3）
        p.shield = 0
        for s in p.shikigami:
            s.shield = 0
        # 3. 已气绝己方式神按从左到右顺序：倒计时 -1，归零复活
        for i, s in enumerate(p.shikigami):
            if s.defeated and not s.despawned and s.level >= 1:
                s.revive_countdown -= 1
                if s.revive_countdown <= 0:
                    s.defeated = False
                    s.health = s.max_health
                    self._log(f"{self.db.shikigami[s.id].name} 复活")
                    self.emit("on_shikigami_revived",
                              shikigami=Ref(player=pi, shikigami=i), source=None, reason="倒计时")
        # 4-5. 鬼火重置为 0 后再获得；触发鬼火变化时机
        gain = cfg.first_turn_orb if first else self.cfg(pi, "orb_per_turn")
        if cfg.orb_cap is not None:
            gain = min(gain, cfg.orb_cap)
        old_orb = p.orb
        p.orb = 0
        p.orb += gain
        if p.orb != old_orb:
            self.emit("on_orb_changed", player=pi, old=old_orb, new=p.orb, reason="回合开始")
        # 6. 战斗区的非召唤物式神：登记延时退回（召唤物留在战斗区）
        pending_retreat = None
        if p.combat_index is not None and p.shikigami[p.combat_index].kind != "summon":
            pending_retreat = p.combat_index
        # 7. 己方所有"回合开始时"能力：触发并延时执行
        self.emit("on_turn_start", player=pi)
        # 8-9. （Phase 3 预留）非灵咒倒计时 → 灵咒倒计时
        # 10. 重置己方出击次数；瞬发名额双方各自每半回合刷新；触发出击次数变化时机
        old_assaults = p.assaults_left
        p.assaults_left = 1
        for q in self.state.players:
            q.fast_used = False
        if p.assaults_left != old_assaults:
            self.emit("on_assaults_changed", player=pi, old=old_assaults, new=p.assaults_left, reason="回合开始")
        # 11-12. （Phase 3 预留）移除"直到上回合结束时"效果；敌方"回合外"能力生效
        # 13. 执行延时的"战斗区式神移回准备区"与回合开始时效果
        if pending_retreat is not None:
            self._retreat(p, pending_retreat)
        self._drain_queue()
        # 14. 抽 1：后手玩家第 1 回合也抽；先手玩家从第 2 回合开始抽。
        if p.turn_count > 1 or self.state.active == 1:
            self.draw_cards(pi, self.cfg(pi, "draw_per_turn"))
        # 15. 进入式神升级阶段
        self._upgrade_phase(p)
        self.state.phase = "battle" if p.upgrades == 0 else "upgrade"
        self._log(f"—— {p.name} 的第 {p.turn_count} 回合（鬼火 {p.orb}）——")

    def _upgrade_phase(self, p: PlayerState) -> None:
        """式神升级阶段：按规则赋予本回合升级机会。

        后手第 3 回合 / 先手第 7 回合各 +1 次（当回合共 2 次）。
        升级阶段本身只赋予机会，不自动升级；玩家通过 upgrade 指令消耗机会。
        当配置 auto_skip_upgrade=True 时（测试便利），不赋予机会并直接进入主要阶段。
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

    # ==================== 伤害 / 抽牌 / 气绝（动作层共用管线） ====================

    def deal_to_shikigami(self, ref: Ref, amount: int, source: Ref | None) -> None:
        """对式神造成伤害并检查气绝。

        终止规则与 _hurt_shikigami 一致：伤害值 ≤0 或护甲完全吸收时不扣血、不触发 on_damage。
        """
        s = self.state.players[ref.player].shikigami[ref.shikigami]
        if s.defeated:
            return
        self._hurt_shikigami(ref, amount, source)
        self.check_defeated(ref, source=source, reason="伤害")

    def deal_to_player(self, player_index: int, amount: int, source: Ref | None) -> None:
        p = self.state.players[player_index]
        if p.defeated:
            return  # 气绝的牌手不会再受到伤害
        if amount <= 0:
            return  # 伤害值不大于 0：终止结算（不扣减生命、不触发受伤后时机）
        remaining = amount
        if p.shield > 0:
            absorbed = min(p.shield, remaining)
            p.shield -= absorbed
            remaining -= absorbed
        if remaining <= 0:
            return  # 护甲完全吸收：终止（不触发受伤后时机）
        p.health -= remaining
        self._log(f"{p.name} 受到 {amount} 点伤害（剩余生命 {p.health}）")
        self.emit("on_player_damaged", player=player_index, amount=amount, source=source)
        if p.health <= 0:
            # 牌手气绝 → "待结束"：已入队的触发能力不再执行，此后非系统操作不再触发
            self._declare_loser(player_index, defeat=True)

    def _hurt_shikigami(self, ref: Ref, amount: int, source: Ref | None) -> None:
        """扣血并发出 on_damage，但不判定气绝（战斗同时结算用）。"""
        s = self.state.players[ref.player].shikigami[ref.shikigami]
        if amount <= 0:
            return  # 伤害值不大于 0：终止结算
        remaining = amount
        if s.shield > 0:
            absorbed = min(s.shield, remaining)
            s.shield -= absorbed
            remaining -= absorbed
        if remaining <= 0:
            return  # 护甲完全吸收：终止（不触发 on_damage）
        s.health -= remaining
        name = self.db.shikigami[s.id].name
        self._log(f"{name} 受到 {amount} 点伤害（剩余生命 {s.health}）")
        self.emit("on_damage", victim=ref, amount=amount, source=source)

    def check_defeated(self, ref: Ref, source: Ref | None = None, reason: str | None = None) -> None:
        """生成并结算式神气绝事件（要素：来源、气绝者、原因）。

        当前机制范围内的流程：消灭形态牌 → 移除所有非永久 buff（临时修正/护甲）→
        非召唤物获得倒计时 3：复活并移动至准备区（召唤物直接离场）→ 气绝后（延时时机）。
        气绝前 1/2/3、替身、击杀标记等时点批次待相应机制引入（见 docs/rules.md）。
        """
        s = self.state.players[ref.player].shikigami[ref.shikigami]
        if s.defeated or s.health > 0:
            return
        s.defeated = True
        s.shield = 0
        s.temp_power = 0  # 临时修正气绝时清除（复活只保留永久修正）
        s.temp_health = 0
        owner = self.state.players[ref.player]
        # 气绝流程包含消灭当前结附的形态牌（rules.md 第七章）
        if s.form is not None:
            self._destroy_form(owner, ref.shikigami, reason="defeat")
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
        self.emit("on_shikigami_defeated", victim=ref, source=source, reason=reason)

    def _declare_loser(self, player_index: int, defeat: bool = False) -> None:
        """标记失败方。

        完整规则：牌手气绝事件应先把游戏标记为"待结束"，已入队触发能力不再执行、
        此后非系统操作不再触发；当前事件结算完成后进入游戏结束阶段，记录结果、
        发送消息并解散房间。Phase 1 效果队列已空或 trivial，待 `_drain_queue` 末尾
        自动把 pending_end 转为 winner。
        """
        if self.state.winner is not None or self.state.pending_end:
            return
        if defeat:
            self.state.players[player_index].defeated = True  # 气绝的牌手不再受到伤害和治疗
        self.state.pending_end = True
        self.state.pending_loser = player_index

    def _declare_draw(self) -> None:
        """标记长对局平局：总回合计数超过上限时强制结束，无获胜方。"""
        if self.state.winner is not None or self.state.pending_end:
            return
        self.state.pending_end = True
        self.state.pending_loser = -1  # -1 表示平局

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
                self._declare_loser(player_index)
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
        对局已进入"待结束"（winner 已定）后，非系统操作不再触发（事件仍记入 history）。
        """
        self.history.append(name)
        if self.state.winner is not None:
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
            self._resolve_block(pend.block, pend.ctx)

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
            p = self.state.players[pi]
            # ---- 式神被动能力 ----
            for si, s in enumerate(p.shikigami):
                ability = self.db.shikigami[s.id].ability
                if ability is None or ability.when != event["name"]:
                    continue
                if not s.in_play:
                    # 0 级未在场能力不触发；个别能力标记为未升级也可触发（书翁/三尾狐类）
                    if s.defeated or s.despawned or not ability.trigger_when_not_in_play:
                        continue
                if self._match(ability.condition, event, pi):
                    out.append(_Pending(ability, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si), event=event)))
            # ---- 响应牌（仅非回合方） ----
            if pi != self.state.active and self._response_used_emit != event["_emit"]:
                # 响应 = 敌方回合满足条件则必定使用（引擎自动结算，不询问玩家）。
                # 同一时机（一次事件生成）至多成功结算一张；式神气绝不影响其手牌中响应牌的队列位置。
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
                # 注意：Phase 1 响应牌的目标自动选择未实现——带 choose 目标的响应牌按无目标结算
                # （符合 rules.md："如果没有目标会自动使用而没有效果"）。
                candidates.sort(key=lambda c: c[0])
                for _, card, eb, si in candidates:
                    out.append(_Pending(eb, ExecContext(
                        controller=pi,
                        source=Ref(player=pi, shikigami=si) if si is not None else None,
                        card=card, event=event, triggered=True)))
        return out

    @staticmethod
    def _match(condition: dict | None, event: dict, controller: int) -> bool:
        """条件迷你语言（扩展点，后续按需加操作符）：
        - {字段: self|opponent}    ：标量玩家下标与 controller 比较
        - {字段_side: friendly|enemy|any} ：事件中的 Ref 相对 controller 的归属
        - {字段_kind: shikigami|player}   ：Ref 指向式神还是牌手
        - 其余按键值相等比较
        """
        if not condition:
            return True
        for key, want in condition.items():
            if key.endswith("_side"):
                ref = event.get(key[:-5])
                if not isinstance(ref, Ref):
                    return False
                side = "friendly" if ref.player == controller else "enemy"
                if want != "any" and side != want:
                    return False
            elif key.endswith("_kind"):
                ref = event.get(key[:-5])
                if not isinstance(ref, Ref):
                    return False
                kind = "shikigami" if ref.shikigami is not None else "player"
                if kind != want:
                    return False
            elif want == "self":
                if event.get(key) != controller:
                    return False
            elif want == "opponent":
                if event.get(key) == controller:
                    return False
            elif event.get(key) != want:
                return False
        return True

    # ==================== 效果块结算 ====================

    def _resolve_block(self, block: EffectBlock, ctx: ExecContext) -> None:
        """结算一个效果块：先处理响应牌的额外开销与限制，再依次执行 steps。

        对响应牌（ctx.triggered=True）：
        - 同一时机（event._emit）至多成功结算一张；
        - 从收集到结算之间局面可能已变化，必须复查手牌、条件、等级、鬼火；
        - 复查失败直接 return，不占用本时机的响应名额；
        - 成功结算后支付费用、移入手牌到墓地、占用名额，并 emit on_trigger。

        然后按 block.steps 顺序执行动作。mode="interleaved" 时每步后清空队列，
        允许其它效果插入；mode="atomic" 时步骤连发，队列留到块外统一结算。
        """
        if ctx.triggered and ctx.card is not None:
            p = self.state.players[ctx.controller]
            cdef = self.db.cards[ctx.card.id]
            emit_id = (ctx.event or {}).get("_emit")
            if emit_id is not None and self._response_used_emit == emit_id:
                return  # 同一时机至多成功结算一张响应牌（复查失败不占名额）
            # 收集到结算之间局面可能已变化：响应牌结算时必须复查条件、鬼火、消耗、使用者
            if ctx.card not in p.hand:
                return
            if ctx.event is not None and not self._match(block.condition, ctx.event, ctx.controller):
                return
            if cdef.shikigami is not None:
                si = self._find_shikigami(p, cdef.shikigami)
                if si is None:
                    return
                s = p.shikigami[si]
                if s.defeated and not cdef.playable_when_defeated:
                    return
                if s.level < cdef.level:
                    return
            cost = self._effective_cost(p, cdef, card=ctx.card)
            if p.orb < cost:
                self._log(f"{p.name} 鬼火不足，响应牌《{cdef.name}》未能触发")
                return
            p.orb -= cost
            if "fast" in cdef.keywords:
                p.fast_used = True
            self.move_card(p, ctx.card, "graveyard")
            self._response_used_emit = emit_id  # 成功结算才占用本时机的响应名额
            self._log(f"{p.name} 的响应牌《{cdef.name}》触发")
            self.emit("on_trigger", player=ctx.controller, uid=ctx.card.uid)
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
        refs = targets.resolve(self, step.target, ctx)
        fn(self, ctx, targets=refs, **(step.model_extra or {}))

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
            self._resolve_block(pend.block, pend.ctx)
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
