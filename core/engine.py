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
  assault {index}  出击：耗 1 鬼火 + 每回合唯一出击次数（+ 出击增减益，Phase 5）
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
from core.registry import (
    CLEAR_ANY_TURN_START,
    CLEAR_ON_DEFEAT,
    CLEAR_OWN_TURN_START,
    EXT_KEYS,
)
from core.model import (
    CardInstance,
    ExecContext,
    GameState,
    FieldState,
    PlayerState,
    Ref,
    ShikigamiState,
    TempGrant,
)
from db.schema import ABILITY_PSEUDO_KEYWORDS, CardDef, EffectBlock, PlayMethod, Step, TargetSpec


class IllegalAction(Exception):
    """指令不合法（费用/等级/目标/时机等）。"""


MAX_QUEUE_ITERATIONS = 1000  # 效果队列死循环保护（DIY 安全网）

# 天然类别为"一次性"的关键字（触发后移除）；其余战斗关键字默认持续性（触发后不移除）。
# "永久"是授予方式而非关键字属性，由授予方显式指定 cls="perm"。
ONE_SHOT_KEYWORDS = frozenset({"haste", "unyielding", "barrier", "blessing"})

# 卡牌级关键字（瞬发/响应/弹回）：只描述卡牌本身的使用方式，不授予式神
CARD_LEVEL_KEYWORDS = ("fast", "trigger", "rebound")

# 法术回响（spell_echo）触发时结算的内部块：登记于来源式神 ext["spell_echo"]，
# 收集门在 Game._collect_abilities（持有者以外的式神从手牌使用法术牌时）
_SPELL_ECHO_BLOCK = EffectBlock(steps=[Step(op="spell_echo_recast")])

# 抽牌事件挂起的"牌库顶 1 张移至手牌"延时移动事件内部块（draw_cards 严格递归结构）：
# 抽牌事件生成时绑定牌（ctx.card）入队，由外层 _drain_queue 统一结算（同 field_destroy 先例）
_DRAW_MOVE_BLOCK = EffectBlock(steps=[Step(op="draw_move")])

# 运势批次引擎直读的式神 id（契约 .tokensave/opmap_luck_batch.md"引擎读"语义）：
# 青蛙瓷器——运势翻倍标记（判定者方有未气绝觉醒青蛙瓷器）与判定成功回合 +2 力量光环；
# 妖狐——伤害流程按来源 = 妖狐时计数牌手 ext yaohu_damage_count
_QINGWA_SHIKIGAMI = 100113
_YAOHU_SHIKIGAMI = 100130
# 不夜之火批次引擎直读的式神 id：日和坊——能量免单（在场已觉醒）与生命代偿（在场基础能力）
_RIHEFANG_SHIKIGAMI = 100205


def _kill_snap_key(spec: dict) -> str:
    """击杀账本查询 spec 的快照键（card.mods["_kill"] 的存储键，_step_amount/_materialize 共用）。"""
    return repr(sorted(spec.items()))


@dataclass
class _DamageEvent:
    """伤害事件要素（docs/rules.md 第五章）：来源、受伤者、伤害值、原因、是否贯通。

    kind: "combat"（攻击方战斗伤害）/ "counter"（反击战斗伤害）/ "effect"（法术、能力等）。
    spell: 法术伤害标记（法术牌效果伤害；≠ 非战斗伤害——式神能力伤害不算，答复(7)）。
    start: 流程起点枚举（规则评审⑪泛化——"流程可从指定位置开始结算"的统一表达，
        rules.md:20/第五章）："full"=完整流程（默认，从批次 0 伤害前开始）；
        "pre_shield_2"=从"护甲计算前2"（贯通修正批次）开始——贯通溢出产生的新事件
        （rules.md:199③），跳过批次 0/1（穿刺/on_damage_start）；
        "pre_shield_0"=从"护甲计算前0"（on_before_shield 批次）开始——伤害目标转移
        产生的新事件：穿刺/on_damage_start/贯通修正/翻倍修饰（护甲计算前1）均不判定
        （"无[贯通]"即贯通修正批次不执行；免疫判定已后移至护甲计算后
        优先级 3，新事件对最终受伤者照常判定；事件生成点的转化与气绝保护仍先行，
        定案"转移链"）。
    redirect_chain: 转移链——本事件已经历的伤害转移能力身份集合（能力实例身份见
        ExecContext.ability_uid）；每个转移能力在同一链上只执行一次，新事件继承并延长链。
    时点批次监听者可通过事件 payload 中的 damage 引用直接修改 amount（扣减生命前锁定）。
    """

    source: Ref | None
    victim: Ref  # shikigami 字段为 None 表示牌手
    amount: int
    kind: str = "effect"
    spell: bool = False
    piercing: bool = False
    start: str = "full"  # 流程起点枚举："full" / "pre_shield_2" / "pre_shield_0"（见上）
    redirect_chain: frozenset = frozenset()
    converted: bool = False  # 已经历过一次转化的伤害（碧羽散华破甲→伤害）：
    # 跳过毒蚀的伤害→破甲转化，防止两个转化类效果来回循环
    fragile: int = 0  # 护甲计算批次消耗的破甲数量（破甲受伤即消耗；on_damage payload
    # 携带，蚀刃毒羽"攻击后使其获得相同数量的破甲"读取）
    dealt: int = 0  # 实际造成伤害值（走到扣减生命批次即视为造成；巨浪"每造成 1 点伤害"统计）
    card: Any = None  # 来源卡牌实例（卡牌效果伤害；猩红之月"你的法术牌获得[吸血]"
    # ——吸血判定除来源式神关键字外也读来源卡牌实例关键字，见 _queue_lifesteal）


@dataclass
class _Pending:
    block: EffectBlock
    ctx: ExecContext
    temp_grant: TempGrant | None = None  # 来自一次性临时触发的待结算项（结算后 uses-1）
    seq: int = 0  # 能力进场序号（收集排序用；0=未登记，保持原有收集顺序）
    horizon: int = 0  # 结算单元标记（仅 on_countdown_reduced 延时项在 emit 时记
    # _horizon_stack 栈顶单元 id；0=无标记。倒计时归零块完成后按单元 drain——
    # 定案"复制延时界=引起该次减少的结算单元"）


class Game:
    def __init__(self, state: GameState, db, seed: int = 0) -> None:
        self.state = state
        self.db = db
        self.rng = random.Random(seed)
        self.queue: deque[_Pending] = deque()
        self.history: list[str] = []  # 事件名序列（测试/回放用）
        # 响应名额（规则设计评审⑨落地——原版两条规则）：
        # 1. 每空闲点限一张：同一响应窗口（= 每名玩家一次行动的完整结算，apply 的
        #    玩家动作指令之间）内、同一时机（事件名）每名玩家至多成功结算一张响应牌；
        #    多张满足时按收集顺序（所属式神从左往右）结算第一张，其余本时机不再触发；
        #    复查失败不占名额。同一窗口内的不同时机（宣言时/受伤后……）是不同空闲点，
        #    可各响应一张。
        # 2. 并行事件同时机响应合并：并行事件（如并行伤害的多个受伤事件）是同名事件
        #    的多次 emit，共享（窗口, 事件名）名额——只触发一次，不逐事件重复。
        # _response_window：当前窗口序号（玩家动作指令开启新窗口）；
        # _response_used：玩家 → 已消耗响应名额的 (窗口序号, 事件名)。
        self._response_window: int = 0
        self._response_used: dict[int, tuple[int, str]] = {}
        self._suppress_responses = False  # on_turn_end 的响应推迟到回合结束效果结算后（答复3）；
        # 例外：on_invocation_trigger 宣告的响应窗即时打开（_collect 处豁免，裁决(2)）
        # 战斗上下文（最小版）：每次 _resolve_combat 压栈新 battle id，终止点弹栈并
        # 清理本战斗授予的关键字实例与免疫条目。为嵌套战斗/响应战斗牌（Phase 5+）打底。
        self._battle_seq: int = 0
        self._battle_stack: list[int] = []
        self._battle_grants: dict[int, list[tuple[Ref, str, str]]] = {}  # battle id → [(式神 Ref, 关键字, 类别)]
        # battle id → [(式神 Ref, 战力)]：响应战斗牌插入使用授予的战力，终止点核销
        # （rules.md:52"该牌的力量与能力加成会持续到该次（被插入的）战斗后"）
        self._battle_power: dict[int, list[tuple[Ref, int]]] = {}
        self._op_param_cache: dict[str, frozenset] = {}  # op 函数签名缓存（Step.condition 分派用）
        # 出牌效果伤害记录栈：结算打出/响应/自动使用的效果块期间压栈一条记录，
        # 伤害管线把实际受伤的"敌方"式神记入栈顶（维护者答复(7)：只计敌方式神——
        # 牌手与己方式神不计；去重），弹出后随 on_card_played 的 affected_refs
        # 发出（暴风之主"对受影响的敌方式神各造成1点伤害"）
        self._affected_stack: list[dict] = []
        # 毒蚀：伤害→破甲转化登记的战斗 id 集合（战斗终止点随弹栈清除）
        self._battle_convert: set[int] = set()
        # 反击贯通：反击伤害具有贯通的战斗 id 集合（counter_piercing 登记；终止点清除）
        self._battle_counter_piercing: set[int] = set()
        # 蚀刃毒羽：battle id → [(目标 Ref, 破甲量)]，"攻击时"登记、战斗结束后回赋
        self._battle_echo: dict[int, list[tuple[Ref, int]]] = {}
        # 义道：battle id → 攻击者 Ref——仅此战斗牌发起的战斗（嵌套/插入不继承）中，
        # 攻击者本人对有破甲的式神造成的战斗伤害翻倍（[暴击]时机=扣减生命前2；终止点清除）
        self._battle_double_fragile: dict[int, Ref] = {}
        # 交战目标改换登记（声东击西 battle_retarget）：battle id -> [改换者 Ref]
        self._battle_retarget: dict[int, list[Ref]] = {}
        # 战斗结束后的追加攻击登记：battle id → [攻击者 Ref]（followup_attack 动作登记；
        # 战斗终止点清理后依次结算，不享受原战斗牌的力量/关键字加成——地狱之手）
        self._battle_followups: dict[int, list[Ref]] = {}
        # 多段攻击登记（二帚流"攻击5次"，multi_strike 动作）：battle id → 交战阶段
        # 攻击段数（缺省 1；反击仍只一段、与首段攻击并行；终止点清除）
        self._battle_strikes: dict[int, int] = {}
        # 结算中交互选择（青灯夜谈）的挂起块续点：(block, ctx, 下一步下标)；内存态不序列化
        self._suspended: tuple | None = None
        # 伤害转移类能力（redirect_damage_to_self）在伤害批次内生成的新事件挂起列表：
        # op 在 emit 上下文中执行（访问不到伤害队列），由 _run_damage_queue 统一入队
        self._redirect_spawned: list[_DamageEvent] = []
        # 结算单元栈（定案"延时界=引起该次减少的结算单元"）：每个 _resolve_block 压栈
        # 一个唯一 id；emit 的延时 pend 记栈顶 id（horizon），倒计时归零块完成后按
        # 单元 drain（_drain_horizon）；栈空=非块上下文（horizon=0，由外层统一结算）
        self._horizon_seq: int = 0
        self._horizon_stack: list[int] = []
        # 反制挂账（罗城门 counter_on_kill）：条目 {"attacker": Ref}——该攻击者击杀
        # 式神且存在进行中的出牌（_active_play_marker）时无效化该次使用并消耗条目；
        # 战斗终止点清除该攻击者的残留条目
        self._counter_watches: list[dict] = []
        # 进行中的出牌 nullified 标记（_cmd_play_card 的 on_before_card_play marker；
        # 反制钩子经此置位——同魔音扰心通道），非出牌结算期间为 None
        self._active_play_marker: dict | None = None

    # ---------- 关键字（多重集；一次性/持续/永久三类，见 docs/terminology.md） ----------

    @staticmethod
    def _has_keyword(s: ShikigamiState, keyword: str) -> bool:
        return (keyword in s.keywords or keyword in s.one_shot_keywords
                or keyword in s.perm_keywords)

    @staticmethod
    def _replace_action_invocation(s: ShikigamiState) -> str | None:
        """replace_action 伪关键字（`replace_action:<灵咒名>`，跳跳哥哥"出击或使用
        战斗牌时改为结附'迟钝'"）：返回要结附的灵咒名；未携带返回 None。

        出击/战斗牌的替换在动作分派处短路（不发起攻击/不进战斗流程），鬼火/瞬发/
        出击次数照常消耗。迟钝带眩晕：眩晕期间出击/战斗牌本就不可用，故替换只在
        无迟钝时实际发生（能力在场判定由读取处 in_play 门控）。"""
        for lst in (s.perm_keywords, s.keywords, s.one_shot_keywords):
            for k in lst:
                if k.startswith("replace_action:"):
                    return k.split(":", 1)[1]
        return None

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

    @staticmethod
    def _record_max_power(s: ShikigamiState) -> None:
        """力量历史峰值记账：ext["max_power"] = 本局最高力量（基础+永久+临时，不含战力；
        只增不减，跨气绝保留不重置——断臂"本局最高力量-当前力量"用）。"""
        cur = s.base_power + s.perm_power + s.temp_power
        if cur > s.ext.get("max_power", 0):
            s.ext["max_power"] = cur

    # ---------- ext 半回合记账键的边界统一清除（core/registry.EXT_KEYS 登记表驱动） ----------

    def _clear_ext(self, holder, timing: str) -> None:
        """按 EXT_KEYS 登记表清除 holder.ext 中登记为该时机的键（键名→清除时机的
        唯一事实来源在 core/registry.py；此处不再散落手写 pop）。
        有副作用的键（扣减/级联/重置/过滤）按键名挂清除钩子 `_ext_clear_<key>`。"""
        holder_kind = "shikigami" if isinstance(holder, ShikigamiState) else "player"
        for key, (kind, t) in EXT_KEYS.items():
            if kind != holder_kind or t != timing:
                continue
            hook = getattr(self, f"_ext_clear_{key}", None)
            if hook is not None:
                hook(holder)
            else:
                holder.ext.pop(key, None)

    @staticmethod
    def _ext_clear_turn_power(s: ShikigamiState) -> None:
        """turn_power（"本回合额外力量"记账）：清除时从 temp_power 同步扣减。"""
        turn_power = s.ext.pop("turn_power", 0)
        if turn_power:
            s.temp_power -= turn_power

    @staticmethod
    def _ext_clear_power_zero_turn(s: ShikigamiState) -> None:
        """power_zero_turn（半回合力量覆写标记）：清除时级联解除力量覆写。"""
        if s.ext.pop("power_zero_turn", None):
            s.ext.pop("power_zero", None)

    @staticmethod
    def _ext_clear_energy_free_turn(p: PlayerState) -> None:
        """energy_free_turn（觉醒·日和坊免单名额）：每半回合重置为 True（非删除）。"""
        p.ext["energy_free_turn"] = True

    def _ext_clear_cost_mods(self, p: PlayerState) -> None:
        """cost_mods（手牌费用修正条目）：按回合号过期清理；scope="form" 条目
        不按回合号过期（形态离场通道移除）。"""
        if p.ext.get("cost_mods") is not None:
            p.ext["cost_mods"] = [e for e in p.ext["cost_mods"]
                                  if e.get("scope") == "form"
                                  or e.get("turn", 0) >= self.state.turn]

    # ---------- 连续型动态身材光环（读取时求值的缓存通道） ----------

    def _refresh_stat_auras(self) -> None:
        """刷新动态身材光环缓存（ext["dyn_power"]/["dyn_health"]；eff_power/max_health
        读取时叠加，见 model.ShikigamiState）。

        注册表 = PlayerState.ext["stat_auras"]（stat_aura 动作登记，元素
        {"kind", "scope", "holder": [pi, si]}；scope="form" 条目形态离场时移除，
        见 _destroy_form）。全量重算（先归零再逐项施加），在手牌数变化（move_card）、
        事件发出（emit）、战斗伤害快照前等读取点统一调用。动态上限降低时同步钳
        当前生命（不触发任何事件）。
        """
        holders = [s for pl in self.state.players for s in pl.shikigami]
        old_dyn = {id(s): int(s.ext.get("dyn_health", 0)) for s in holders}
        for s in holders:
            s.ext["dyn_power"] = 0
            s.ext["dyn_health"] = 0
        for pi, pl in enumerate(self.state.players):
            for aura in pl.ext.get("stat_auras", []):
                kind = aura.get("kind")
                if kind in ("ids_power", "ids_energy_power"):
                    # 坐下/出击：按数据 id 匹配控制者在场的召唤物/变形物（番茄
                    # 10013199/10013198）+N 力量——本局永久光环、跨召唤保留、可叠加；
                    # 结附牌手而非式神，无 holder（scope="form" 条目记 holder 随形态离场移除）
                    for s in pl.shikigami:
                        if not s.in_play or s.id not in aura.get("ids", ()):
                            continue
                        if kind == "ids_energy_power":
                            # 烟雾缭绕：匹配实体每有 divisor 点能量 +power（读实体自身能量）
                            s.ext["dyn_power"] += (s.energy // int(aura.get("divisor", 1))) \
                                * int(aura.get("power", 1))
                        else:
                            s.ext["dyn_power"] += int(aura.get("power", 0))
                    continue
                hp, hs = aura.get("holder", [None, None])
                if hp is None:
                    continue
                src = self.state.players[hp].shikigami[hs]
                if not src.in_play:
                    continue  # 持有者未在场：光环不生效
                if kind == "self_hand_count":
                    # 闻世：每有一张其他手牌此牌便 +1/+1（形态在场上，手牌皆为"其他"）
                    n = len(self.state.players[hp].hand)
                    src.ext["dyn_power"] += n
                    src.ext["dyn_health"] += n
                elif kind == "enemy_fragile_power":
                    # 火吻之蛇：敌方有破甲的式神降低等于其破甲的力量
                    for s in self.state.players[1 - pi].shikigami:
                        if s.in_play and s.shield < 0:
                            s.ext["dyn_power"] += s.shield  # shield 为负值即减力
                elif kind == "enemy_stunned_exists":
                    # 雪国之子：场上有[眩晕]的敌方角色时持有者 +power/+health
                    # （活局面判定——眩晕全部解除即失去加成）
                    if self._enemy_stunned_count(pi):
                        src.ext["dyn_power"] += int(aura.get("power", 0))
                        src.ext["dyn_health"] += int(aura.get("health", 0))
                elif kind == "ext_power":
                    # 雪融之时[增强]：持有者 +力量 = 控制者 ext[ext] 计数 × power 倍率
                    # （本局累计计数类增强；计数由引擎/效果记账，光环读取时求值）
                    n = int(pl.ext.get(aura.get("ext", ""), 0))
                    src.ext["dyn_power"] += n * int(aura.get("power", 1))
                elif kind == "energy_power":
                    # 人多势众：持有者每有 divisor 点能量 +power 力量（读取时求值）
                    src.ext["dyn_power"] += (src.energy // int(aura.get("divisor", 1))) \
                        * int(aura.get("power", 1))
                elif kind == "field_count_stats":
                    # 星辰之境[增强]：控制者每有一个幻境，持有者 +power/+health（读取时求值）
                    n = len(pl.fields)
                    src.ext["dyn_power"] += n * int(aura.get("power", 1))
                    src.ext["dyn_health"] += n * int(aura.get("health", 1))
                elif kind == "enemy_deck_invocation":
                    # 支配者：敌方牌库中每有一张结附指定灵咒（aura["name"]）的牌，
                    # 持有者 +1/+1（读取时求值；牌离库移除灵咒后自动减）
                    n = sum(1 for c in self.state.players[1 - pi].deck
                            if any(e["name"] == aura.get("name") for e in c.invocations))
                    src.ext["dyn_power"] += n
                    src.ext["dyn_health"] += n
                elif kind == "friendly_invocation":
                    # 薰形态系列（鸮之利爪/警惕/庇佑）：己方在场且结附指定灵咒
                    # （aura["name"]，不限结附来源）的式神 +power/+health（读取时求值；
                    # 关键字部分见下方 reconcile 段）
                    for s in pl.shikigami:
                        if s.in_play and any(e["name"] == aura.get("name")
                                             for e in s.invocations):
                            s.ext["dyn_power"] += int(aura.get("power", 0))
                            s.ext["dyn_health"] += int(aura.get("health", 0))
        for pi, pl in enumerate(self.state.players):
            # 幻境/护甲关联的连续条件力量修饰（伪关键字，先天关键字按永久类别入列——
            # 泷夜叉姬基础 power_if_field"若你有幻境+1力量"/觉醒 power_per_field"每有
            # 一个幻境+1力量"；久次良基础 power_if_shield"有护甲时+1力量"/觉醒
            # power_equal_shield"力量=当前护甲"（覆写口径：基础+永久+临时修正不计
            # 战斗战力）；读取时求值，觉醒替换/气绝随关键字通道自动失效）
            for s in pl.shikigami:
                if not s.in_play:
                    continue
                if pl.fields and self._has_keyword(s, "power_if_field"):
                    s.ext["dyn_power"] += 1
                if pl.fields and self._has_keyword(s, "power_per_field"):
                    s.ext["dyn_power"] += len(pl.fields)
                if s.shield > 0 and self._has_keyword(s, "power_if_shield"):
                    s.ext["dyn_power"] += 1
                if self._has_keyword(s, "power_equal_shield"):
                    s.ext["dyn_power"] += max(0, s.shield) - (
                        s.base_power + s.perm_power + s.temp_power)
                if self._has_keyword(s, "power_eq_health"):
                    # 力量 = 当前生命（觉醒·人面树；覆写口径同 power_equal_shield：
                    # 基础+永久+临时修正被覆盖，战斗战力与灵咒层仍叠加；濒死读取为负
                    # 时钳 0——力量不为负）
                    s.ext["dyn_power"] += max(0, s.health) - (
                        s.base_power + s.perm_power + s.temp_power)
                if self.state.active != pi:
                    # 敌方回合 +N 力量（散华之刃 power_on_enemy_turn:3，冒号参数
                    # 伪关键字——前缀扫描取值）
                    for kw in s.keywords:
                        if kw.startswith("power_on_enemy_turn:"):
                            s.ext["dyn_power"] += int(kw.split(":", 1)[1])
        for pi, pl in enumerate(self.state.players):
            # 青蛙瓷器光环（契约"引擎读"）：其控制者本回合（含敌方回合）运势判定成功过
            # （ext luck_success_turn == 当前回合号）则在场的青蛙瓷器 +2 力量——不叠加、
            # 气绝复活保留（动态读取通道，非实例增益）
            if pl.ext.get("luck_success_turn") == self.state.turn:
                for s in pl.shikigami:
                    if s.in_play and s.id == _QINGWA_SHIKIGAMI:
                        s.ext["dyn_power"] += 2
        for s in holders:
            # 动态上限降低时钳当前生命（仅动态通道实际变小时钳——不触碰正常超出
            # 上限的当前生命，如测试/调试直改的健康值）
            if s.ext["dyn_health"] < old_dyn[id(s)] and s.health > s.max_health:
                s.health = s.max_health
        self._reconcile_invocation_aura_keywords()

    def _reconcile_invocation_aura_keywords(self) -> None:
        """friendly_invocation 身材光环的关键字部分（薰 鸮之警惕[帷幕]/鸮之庇佑
        [不屈]）：读取时求值的持续授予——全量重算期望集合（光环持有者在场 + 目标
        为己方在场且结附指定灵咒的式神），与式神 ext["inv_aura_kw"] 已授记录比对
        多退少补。形态离场/灵咒移除/持有者气绝后条目在下一次刷新自动撤销
        （本方法挂 _refresh_stat_auras 尾部，refresh 挂在 emit/手牌数/能量变化/
        战斗快照等读取点）。以 continuous 类授予：不屈不被消耗移除（光环持续期间
        回血后可再次触发），与形态牌 keywords 授予类别一致。"""
        desired: dict[int, set[str]] = {}  # id(式神状态) -> 应持关键字集合
        for pi, pl in enumerate(self.state.players):
            for aura in pl.ext.get("stat_auras", []):
                if aura.get("kind") != "friendly_invocation" or not aura.get("keywords"):
                    continue
                hp, hs = aura.get("holder", [None, None])
                if hp is None:
                    continue
                src = self.state.players[hp].shikigami[hs]
                if not src.in_play:
                    continue  # 持有者未在场：光环不生效
                for s in pl.shikigami:
                    if s.in_play and any(e["name"] == aura.get("name")
                                         for e in s.invocations):
                        desired.setdefault(id(s), set()).update(aura["keywords"])
        for pl in self.state.players:
            for s in pl.shikigami:
                cur: list[str] = s.ext.get("inv_aura_kw", [])
                want = desired.get(id(s), set())
                for kw in [k for k in cur if k not in want]:
                    self._remove_keyword(s, kw, "continuous")
                    cur.remove(kw)
                for kw in sorted(want):
                    if kw not in cur:
                        self._grant_keyword(s, kw, "continuous")
                        cur.append(kw)
                if cur:
                    s.ext["inv_aura_kw"] = cur
                else:
                    s.ext.pop("inv_aura_kw", None)

    @property
    def current(self) -> PlayerState:
        return self.state.players[self.state.active]

    def _enemy_stunned_count(self, pi: int) -> int:
        """玩家 pi 的敌方当前眩晕角色数（在场眩晕式神 + 眩晕牌手）。

        "场上有[眩晕]的敌方角色"系列（霜舞 conditional_keywords / 雪国之子 stat_aura /
        霜天之织 _step_amount）的统一读取点：活局面量——眩晕解除/气绝即减，非计数器。
        """
        d = self.state.players[1 - pi]
        n = sum(1 for s in d.shikigami if s.in_play and s.is_stunned)
        return n + (1 if d.is_stunned else 0)

    def _kill_count(self, pi: int, spec: dict) -> int:
        """玩家 pi 的击杀账本计数（_step_amount {"kill_count": spec} 统一读取点）：

        {"scope": "player"} → 本局以己方角色为来源消灭的式神总数（夺命）；
        {"shikigami": id}（缺省口径）→ 该式神像（当前数据 id）为来源的消灭数（禁锢之刀）。
        """
        pl = self.state.players[pi]
        if spec.get("scope") == "player":
            return pl.kill_total
        return pl.kill_by.get(int(spec.get("shikigami", 0)), 0)

    def _quest_tick(self, pi: int, kind: str, n: int = 1, *, shareable: bool = True) -> None:
        """委托条件账本记账（三目委托机制；PlayerState.quest_counts，与击杀账本同思路——
        牌手级、跨区域有效，天然满足"在牌库也有效"）。

        shareable=True（行为类：assault/draw/play/damage/effect_damage/attack/
        form_play/offdeck_play）：pi 的行为计入 pi 的账本；多事多忙在场（对方有在场
        式神结附 tags 含 quest_enemy 的形态）时，pi 的行为同时计入对方账本
        （"你的委托条件也可以由敌方完成"）。
        shareable=False（归属类：enemy_defeat 按气绝者归属对方记账、revive 按复活者
        归属记账、quest_used 限己方三目）天然与对方行为无关，不吃多事多忙扩域。
        """
        p = self.state.players[pi]
        p.quest_counts[kind] = p.quest_counts.get(kind, 0) + n
        if shareable:
            other = 1 - pi
            if self._field_form_has_tag(other, "quest_enemy"):
                q = self.state.players[other]
                q.quest_counts[kind] = q.quest_counts.get(kind, 0) + n

    def _account_quest_damage(self, ev: "_DamageEvent") -> None:
        """委托账本伤害记账：伤害实际造成（扣减生命批次锁定 dealt）时，来源归属方
        damage += 实际量；非战斗伤害（kind=effect）另计 effect_damage。无来源不计。"""
        if ev.source is None or ev.dealt <= 0:
            return
        self._quest_tick(ev.source.player, "damage", ev.dealt)
        if ev.kind == "effect":
            self._quest_tick(ev.source.player, "effect_damage", ev.dealt)

    @staticmethod
    def _card_belongs_to(cdef: CardDef, sid: int) -> bool:
        """卡牌归属判定（"已展示"机制统一口径）：专属牌按 shikigami 命中；协战牌
        未使用时视为同时属于两位所属式神（shikigami2 同判）。"""
        return cdef.shikigami == sid or (cdef.shikigami2 is not None
                                         and cdef.shikigami2 == sid)

    def _enemy_revealed_count(self, pi: int, mode: str,
                              chosen: list[Ref] | None = None) -> int:
        """敌方手牌中已展示牌的计数（_step_amount {"enemy_revealed_count": mode}
        统一读取点；活局面量）：spell=法术牌；other=非法术牌；
        shikigami_of_chosen=属于被选择式神（含其参与的协战牌，无选择目标为 0）。"""
        revealed = [c for c in self.state.players[1 - pi].hand
                    if c.mods.get("revealed")]
        if mode == "spell":
            return sum(1 for c in revealed
                       if self.db.cards[c.id].card_type == "spell")
        if mode == "other":
            return sum(1 for c in revealed
                       if self.db.cards[c.id].card_type != "spell")
        if mode == "shikigami_of_chosen":
            if not chosen or chosen[0].shikigami is None:
                return 0
            sid = self.state.players[chosen[0].player].shikigami[chosen[0].shikigami].id
            return sum(1 for c in revealed
                       if self._card_belongs_to(self.db.cards[c.id], sid))
        raise ValueError(f"未知 enemy_revealed_count 口径: {mode}")

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
        cz = cdef.cost_zero_if
        if cz:
            if cz.get("ext") and p.ext.get(cz["ext"]):
                return 0  # 动态费用（金风流羽：本回合使用过黄金羽则不消耗鬼火）
            if cz.get("level_ge") is not None and cdef.shikigami:
                # 式神等级达到下限则不消耗鬼火（心身炼磨类）；未出战不满足
                si = self._find_shikigami(p, cdef.shikigami)
                if si is not None and p.shikigami[si].level >= int(cz["level_ge"]):
                    return 0
        if "fast" in self._card_keywords(p, cdef, card) and not p.fast_used:
            cost = 0
        if cost > 0:
            # 幸运兔兔类手牌费用修正（cost_delta_player 登记于 ext["cost_mods"]，回合号过期）；
            # [不消耗鬼火]与回合内首张[瞬发]已在上方归零，不受修正影响（全免沿跳跳妹妹定案）；
            # card_flag 条目（card_flag="revealed"：使用已展示的手牌额外耗火）仅命中
            # 带对应实例标志的牌
            cost += sum(int(e.get("amount", 0)) for e in p.ext.get("cost_mods", [])
                        if (e.get("turn") is None or e["turn"] == self.state.turn)
                        and (e.get("card_flag") is None
                             or (card is not None and card.mods.get(e["card_flag"]))))
            # 跳跳妹妹基础能力（先天伪关键字 extra_orb_cost）：其战斗牌额外消耗 1 点鬼火；
            # 气绝（能力不在场）/瞬发/不消耗鬼火（已归零）时全免——含额外的这 1 火（定案(11)）
            if cdef.card_type == "combat" and cdef.shikigami is not None:
                xi = self._find_shikigami(p, cdef.shikigami)
                if (xi is not None and p.shikigami[xi].in_play
                        and self._has_keyword(p.shikigami[xi], "extra_orb_cost")):
                    cost += 1
        return cost

    def _card_methods(self, p: PlayerState, cdef: CardDef) -> list[PlayMethod]:
        """一张卡当前可用的使用方式：定义 methods ∪ 命中光环授予的方式（card_aura
        grant_method，御馔津基础/觉醒"符咒牌具有'[爆能3]：转化为战斗牌…'"——
        scope="ability" 随能力离场/觉醒换绑移除重注册）。读取时求值，同 id 光环
        方式覆盖定义位（觉醒版替换基础版——换绑后基础光环已移除，双保险）。"""
        methods = list(cdef.methods)
        for aura in self._match_auras(p, cdef):
            gm = aura.get("grant_method")
            if not gm:
                continue
            gm = dict(gm)
            gm.setdefault("target", None)
            if gm.get("target") is not None:
                gm["target"] = TargetSpec.model_validate(gm["target"])
            if gm.get("effects") is not None:
                gm["effects"] = EffectBlock.model_validate(gm["effects"])
            m = PlayMethod.model_validate(gm)
            methods = [x for x in methods if x.id != m.id]  # 同 id 覆盖（觉醒版优先）
            methods.append(m)
        return methods

    def _match_auras(self, p: PlayerState, cdef: CardDef) -> list[dict]:
        """命中该卡牌的卡牌光环（card_auras 注册表，读取时求值，覆盖已有与新生成的牌）。

        turn 通道（"self"/"opponent"）：限定回合方——仅己方/敌方回合时光环生效
        （伺机"敌方回合时此牌+2力量"）。
        card_id 通道：仅命中该数据 id 的牌（"此牌"类自指光环）。"""
        pi = next(i for i, q in enumerate(self.state.players) if q is p)
        out = []
        for a in p.card_auras:
            if a["shikigami"] is not None and cdef.shikigami != a["shikigami"]:
                continue  # shikigami=None 为通配（"己方式神的形态牌"——觉醒·萤草/爱意绵绵）
            if a.get("card_type") is not None and a["card_type"] != cdef.card_type:
                continue
            if a.get("subtype") is not None and a["subtype"] != cdef.subtype:
                continue  # 子类型限定：仅命中该子类型的牌（觉醒·三目的"委托牌"不耗火）
            if a.get("card_id") is not None and a["card_id"] != cdef.id:
                continue  # "此牌"限定：仅命中指定数据 id
            if a.get("tag") is not None and a["tag"] not in cdef.tags:
                continue  # 标记限定：仅命中 tags 含该标记的牌（寒冬之心的"雪球"）
            if a.get("level") is not None and a["level"] != cdef.level:
                continue  # 使用等级限定：仅命中该等级的牌（火照之路"等级为1的牌"）
            fo = a.get("field_obj")
            if fo is not None and not any(fo is x for pl in self.state.players
                                          for x in pl.fields):
                continue  # scope="field"：来源幻境已离场，光环失效（火照之路类）
            turn = a.get("turn")
            if turn is not None and (turn == "self") != (self.state.active == pi):
                continue  # 回合方条件不满足：光环不生效
            if a.get("require_holder_form"):
                # "若萤草上有形态"（20200327 版萤草）：来源式神未结附形态时光环不生效
                holder = a.get("holder")
                if (holder is None
                        or self.state.players[holder[0]].shikigami[holder[1]].form is None):
                    continue
            out.append(a)
        return out

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
        """一张卡当前实际具有的关键字：定义 ∪ 实例修饰 ∪ 命中光环 ∪ 条件关键字
        （瞬发判定等的统一读取点）。

        conditional_keywords（心身炼磨/桃华灼灼/闪烁）：按卡牌所属式神在座次中的状态
        判定（level_ge = 等级下限；if_alive = 在场；combat_nonempty = 己方战斗区有人；
        shikigami_has_form = 控制者指定式神结附着形态；enemy_stunned_nonempty =
        场上有[眩晕]的敌方角色——霜舞型条件瞬发，活局面判定；enemy_hand_all_revealed =
        敌方有手牌且全部已展示——读心型条件；enemy_fragile_ge2 = 敌方场上存在
        破甲 ≧2 的角色——铃鹿御前型条件瞬发；player_health_ge = 己方牌手当前生命
        下限——血香型条件[连击]；enemy_deck_le = 敌方牌库张数上限——意外之喜型
        条件[瞬发]）；invocation_on_field = 场上有己方式神结附指定灵咒——麓鸣·穿型
        条件[瞬发]，与 targets.match_condition 同名算子同语义）；enemy_drew_invocation =
        对方牌手本回合抽到过结附指定灵咒的牌——惊梦型条件[瞬发]）；式神未出战时条件不满足。"""
        kws = set(cdef.keywords)
        if card is not None:
            kws |= set(card.mods.get("keywords_add", []))
        for aura in self._match_auras(p, cdef):
            kws |= set(aura.get("keywords", []))
        for ck in cdef.conditional_keywords:
            si = self._find_shikigami(p, cdef.shikigami) if cdef.shikigami else None
            if si is None:
                continue
            st = p.shikigami[si]
            if ck.get("level_ge") is not None and st.level < int(ck["level_ge"]):
                continue
            if ck.get("if_alive") and not st.in_play:
                continue
            if ck.get("combat_nonempty") and p.combat_index is None:
                continue  # 己方战斗区有人（闪烁型条件瞬发）
            if ck.get("enemy_stunned_nonempty") and not self._enemy_stunned_count(
                    self.state.players.index(p)):
                continue  # 场上有[眩晕]的敌方角色（霜舞型条件瞬发）
            if ck.get("enemy_hand_all_revealed"):
                # 敌方有手牌且全部已展示（空手牌不成立；读心型条件）
                eh = self.state.players[1 - self.state.players.index(p)].hand
                if not eh or not all(c.mods.get("revealed") for c in eh):
                    continue
            if ck.get("enemy_fragile_ge2"):
                # 敌方场上存在破甲 ≧2 的角色（牌手或在场式神；铃鹿御前型条件瞬发）
                ep2 = self.state.players[1 - self.state.players.index(p)]
                if not (ep2.shield <= -2
                        or any(x.shield <= -2 for x in ep2.shikigami)):
                    continue
            if ck.get("player_health_ge") is not None:
                # 己方牌手当前生命 ≥ n（血香型条件[连击]"若你生命值为30"）
                if p.health < int(ck["player_health_ge"]):
                    continue
            if ck.get("enemy_deck_le") is not None:
                # 敌方牌库张数 ≤ n（月夜幻响包条件[增强]/条件[瞬发]：意外之喜）
                ep = self.state.players[1 - self.state.players.index(p)]
                if len(ep.deck) > int(ck["enemy_deck_le"]):
                    continue
            if ck.get("invocation_on_field") is not None:
                # 场上有己方式神结附指定灵咒（麓鸣·穿型条件[瞬发]；与
                # targets.match_condition 同名算子同语义：在场、不限结附来源）
                if not any(s.in_play and any(e["name"] == ck["invocation_on_field"]
                                             for e in s.invocations)
                           for s in p.shikigami):
                    continue
            if ck.get("enemy_drew_invocation") is not None:
                # 对方牌手本回合抽到过结附指定灵咒的牌（惊梦型条件[瞬发]；
                # 读对方 ext["drew_invocation_turn"] 账本）
                ledger = self.state.players[
                    1 - self.state.players.index(p)].ext.get("drew_invocation_turn") or []
                if ck["enemy_drew_invocation"] not in ledger:
                    continue
            if ck.get("shikigami_has_form") is not None:
                # 控制者的式神（按数据 id）结附着形态（福寿双全条件瞬发；
                # 与 targets.match_condition 同名算子同语义）
                want = int(ck["shikigami_has_form"])
                ai = next((i for i, s in enumerate(p.shikigami) if s.id == want), None)
                if ai is None or p.shikigami[ai].form is None:
                    continue
            if ck.get("friendly_field") and not p.fields:
                continue  # 你有幻境（曜断型条件[瞬发]）
            if ck.get("deck_field_distinct_ge") is not None:
                # 牌库中本卡所属式神的不同名幻境牌数 ≥ n（五道难题型条件[瞬发]）
                distinct = {c.id for c in p.deck
                            if self.db.cards[c.id].card_type == "field"
                            and self.db.cards[c.id].shikigami == cdef.shikigami}
                if len(distinct) < int(ck["deck_field_distinct_ge"]):
                    continue
            kws.add(ck["keyword"])
        if cdef.alt_remove_keywords and self._is_transformed(p, cdef, card):
            kws -= set(cdef.alt_remove_keywords)  # "变为"后失去关键字（如瞬发）
        return kws

    def _materialize(self, p: PlayerState, card: CardInstance, cdef: CardDef) -> None:
        """持久修饰快照（docs/enhance-design.md 即时装配模型）：打出付费后/效果结算前，
        以及生成类卡牌置入手牌时（生成点统一处理——万象之书/虹彩/森佑灵引等置入手牌
        立即获得"本局游戏"类增强），把持久 store（card_mods）中的修饰合并进该实例
        mods 作为快照——快照后计数再变也不影响本次结算/该实例。装配产物只在实例上，
        定义块永不改写。

        重复合并按实例去重（弹回后再次打出 / 生成快照后再打出）：计数型键以
        mods["_mat"] 记账上次合并值，只补差值；keywords_add/transformed 为集合/开关
        语义，天然幂等。条件实例修饰（conditional_mods，[增强]条件装配）在同一装配点
        按条目条件写入实例 mods，不走持久 store。击杀账本计数（_step_amount 的
        kill_count 动态数值）也在此按打出点快照入 card.mods["_kill"]。
        """
        # 条件实例修饰（CardDef.conditional_mods；牙牙我们走[增强]身材、汤盆冲撞[增强]
        # 伤害翻倍）：装配点按条目条件（条件迷你语言，控制者视角、空事件求值）把 mods
        # 键写入实例——先于持久 store 早退判定，无持久修饰的牌同样生效
        for cm in cdef.conditional_mods:
            cond = {k: v for k, v in cm.items() if k != "mods"}
            if cond and not targets.match_condition(
                    self, cond, {}, self.state.players.index(p)):
                continue
            for k, v in (cm.get("mods") or {}).items():
                card.mods[k] = v
        # 击杀账本快照（禁锢之刀"每消灭过一个…"）：打出装配点把当前账本计数写入实例，
        # 本次结算读快照（_step_amount 的 kill_count 分支）；先于持久 store 早退判定
        specs: list[str] = []  # 已快照的 spec 键（去重）
        blocks = ([cdef.effects, cdef.alt_effects, cdef.response]
                  + [m.effects for m in cdef.methods])
        for blk in blocks:
            for step in (blk.steps if blk is not None else []):
                extra = step.model_extra or {}
                for num_key in ("amount", "power"):
                    num = extra.get(num_key)
                    if isinstance(num, dict) and num.get("kill_count"):
                        skey = _kill_snap_key(num["kill_count"] or {})
                        if skey not in specs:
                            specs.append(skey)
                            card.mods.setdefault("_kill", {})[skey] = self._kill_count(
                                self.state.players.index(p), num["kill_count"] or {})
        store = p.card_mods.get(cdef.id)
        if not store:
            return
        mat = card.mods.setdefault("_mat", {})
        for key in ("enhance", "form_power_delta", "form_health_delta"):
            cur = int(store.get(key, 0))
            delta = cur - int(mat.get(key, 0))
            if delta:
                card.mods[key] = card.mods.get(key, 0) + delta
                mat[key] = cur
        if store.get("keywords_add"):
            merged = set(card.mods.get("keywords_add", [])) | set(store["keywords_add"])
            card.mods["keywords_add"] = sorted(merged)
        if store.get("transformed"):
            card.mods["transformed"] = True  # "变为"快照（本局该同名卡全部生效）

    @staticmethod
    def _step_amount(step: Step, card: CardInstance | None,
                     s: ShikigamiState | None = None,
                     event: dict | None = None, game=None,
                     memo: dict | None = None,
                     controller: int | None = None,
                     chosen: list[Ref] | None = None,
                     key: str = "amount",
                     field=None) -> int:
        """解析步骤的 amount 参数（docs/enhance-design.md 数值解析流水线）：

        - {"enhance": true, "base": n}：base + 实例已装配的 enhance 修饰；
        - {"shield_of": "self"|"source"}：来源式神当前护甲（尘刀快照/古尘之壁）；
        - {"fragile_of": "self"|"source"}：来源式神当前破甲量（负 shield 的绝对值，
          无破甲为 0；僵硬扑击"获得等同于自己破甲的力量"——战斗牌战力提取与
          结算两读取点同源）；
        - {"power_of": "self"|"source"}：来源式神 eff_power（援护）；
        - {"perm_power": "self"}：来源式神当前永久力量修正快照（崩山"使用时按永久力量
          值增伤"——按使用时快照而非计数器；怪力/怒吼的 perm buff 是既有 buff_power）；
        - {"ext": key}：来源式神 ext 计数（鸩觉醒"每触发过一次…额外+1"的 x）；
        - {"event": key}：触发事件 payload 中的数值（寂寥心象"获得等量破甲"）；
          可叠加 "cap": n 上限截断（觉醒·铃鹿御前"至多获得3点破甲"）与 "half": true
          减半向下取整（光影"获得等同于一半伤害的生命"；cap 先截后减）；
        - {"half_health_of": key}：事件中的 Ref 所指角色当前生命的一半（向下取整，
          毒之华"等同于其一半生命的破甲"）；值为 "target" 时是**逐目标动态数值**
          （凋零之森）——_run_step 不做预解析，原样传字典由 op 逐目标求值。
        - {"health_of": "self"|"source"}：来源式神当前生命（灾厄之花"对自己造成
          等同于其生命的伤害"，经 delay_grant 绑定的延迟块内 self=持有者）；
          值为 "target" 时同为逐目标动态数值通道。
        - {"max_power_gap": "self"}：来源式神历史峰值力量（ext["max_power"]）与当前
          eff_power 之差（断臂"力量变为本局游戏曾有的最大值"的差值补偿形式，≥0）。
        - {"missing_health": "self"}：来源式神已损失生命（鹤唳回风"恢复所有生命"）。
        - {"half_shield_of": "self"|"source"}：来源式神当前护甲的一半（向下取整，
          治愈之水"海坊主每有 2 护甲则效果+1"）。
        - {"memo": key}：块内暂存 ctx.memo 的数值（巨浪"每造成 1 点伤害恢复 1 生命"
          读 damage 记录的 last_damage_total）。
        - {"burst_x": true}：爆能 X 支付的能量快照（出牌时写入 card.mods["burst_x"]；
          memo["burst_x"] 优先，供触发块转写）。
        - {"dice_distinct": true}：效果归属玩家骰子历史（ext dice_history）的
          去重数字种数（九莲宝灯"每投出过一个不重复数字 +1/+1"）。
        - {"enemy_stunned_count": true}：场上眩晕的敌方角色数（霜天之织[增强]
          "每有一个[眩晕]的敌方角色便+1力量"；活局面量，engine._enemy_stunned_count）。
        - {"hand_count_half": "controller"}：效果归属玩家当前手牌数的一半（向下取整，
          墨染"等同于你手牌数量一半的伤害"）。
        - {"field_intensity": "self"}：触发来源幻境（ctx.field）当前耐久（星轨
          "造成等同于它耐久的伤害"——幻境能力块专用，读取时求值）。
        - {"field_count": "controller"}：控制者当前幻境数（鲸骨·开[增强]
          "你每有一个幻境，此牌便获得+1力量和+1护甲"——活局面量）。
        - {"enemy_revealed_count": "spell"|"other"|"shikigami_of_chosen"}：敌方手牌中
          已展示牌的计数——按法术牌/非法术牌/属于被选择式神（含其参与的协战牌，
          _card_belongs_to 口径）三口径（"已展示"机制，engine._enemy_revealed_count）。
        - {"countdown_holders": "friendly_others"}：控制者在场未气绝、当前持有倒计时
          能力的式神像数，排除来源式神（突[增强]"你每有一个山风以外的具有[倒计时]的
          未气绝式神，此效果+1"）。
        - {"max_shield_or_fragile": true}：场上最大护甲或破甲（遮雨"为你恢复等同于
          场上最大护甲或破甲的生命"）——双方所有角色（在场式神 + 牌手）|shield| 最大值。
        - {"kill_count": spec}：效果归属玩家的击杀账本计数（rules.md「击杀账本」）——
          spec 为 {"shikigami": id} 时读该式神为来源的消灭数（禁锢之刀）、
          {"scope": "player"} 时读玩家总消灭数；card 携带打出装配快照
          （card.mods["_kill"]，见 _materialize）时优先快照，否则读活账本。
        - {"victim_invocation_count": 灵咒名}：事件 victim_invocations 快照中该
          灵咒的条目数（食魂蛊"其上每有一个'蛊蚀'"——气绝移除前快照，配 per 倍率）。
        - {"deck_invocation_count": {"name": 灵咒名, "side": self|enemy}}：指定侧
          牌库中结附该灵咒的牌数（食梦貘"敌方牌库中每有一张'梦魇'"，缺省 enemy）。
        - "per": n：动态项总和的倍率，最终值 = base + 动态项总和 × per
          （禁锢之刀"每消灭过一个…便获得+2力量"、棒球炸弹"2+2×幻境数"）；
          缺省 1，静态 base 不受倍率影响。
        - "negate": true：与上述任意形式叠加，最终数值取负（觉醒·山风共享
          {event: original, negate: true}、突 {base: 2, countdown_holders, negate}）。
        key 参数：解析的数值键名（缺省 "amount"；attack_buff 的 power 动态数值经
        _run_step 以 key="power" 走同一流水线）。
        前三者在动作执行处另有 _run_step 的 ctx 解析路径（法术/能力步骤用）。
        """
        raw = (step.model_extra or {}).get(key, 0)
        if isinstance(raw, dict):
            base = int(raw.get("base", 0))  # 静态底数（不受 per 倍率影响）
            dyn = 0  # 动态项总和（"每有一个…"类，受 per 倍率放大）
            if raw.get("hand_count_half") and game is not None and controller is not None:
                dyn += len(game.state.players[controller].hand) // 2  # "一半"：向下取整
            if raw.get("field_intensity") and field is not None:
                dyn += int(field.intensity)  # 触发来源幻境当前耐久（星轨）
            if raw.get("field_count") and game is not None and controller is not None:
                dyn += len(game.state.players[controller].fields)  # 控制者幻境数（鲸骨·开）
            if raw.get("enhance") and card is not None:
                dyn += int(card.mods.get("enhance", 0))
            if raw.get("shield_of") and s is not None:
                dyn += s.shield
            if raw.get("fragile_of") and s is not None:
                dyn += max(0, -s.shield)  # 破甲量（无破甲为 0；僵硬扑击）
            if raw.get("half_shield_of") and s is not None:
                dyn += max(0, s.shield) // 2  # "每有 2 护甲"：向下取整；破甲不计
            if raw.get("power_of") and s is not None:
                dyn += s.eff_power
            if raw.get("perm_power") and s is not None:
                dyn += s.perm_power
            if raw.get("ext") and s is not None:
                dyn += int(s.ext.get(raw["ext"], 0))
            if raw.get("event") and event is not None:
                val = int(event.get(raw["event"], 0))
                if raw.get("cap") is not None:
                    val = min(val, int(raw["cap"]))  # 事件引用值上限截断（觉醒·铃鹿御前"至多3点"）
                if raw.get("half"):
                    val //= 2  # 事件引用值减半（向下取整；光影"获得等同于一半伤害的生命"）
                dyn += val
            if raw.get("memo") and memo is not None:
                dyn += int(memo.get(raw["memo"], 0))  # 块内暂存（巨浪 last_damage_total）
            if raw.get("victim_invocation_count") and event is not None:
                # 事件 victim_invocations 快照（气绝移除前灵咒名列表）中指定灵咒的
                # 条目数（食魂蛊"其上每有一个'蛊蚀'，为你恢复2点生命"——配 per 倍率）
                dyn += (event.get("victim_invocations") or []).count(
                    raw["victim_invocation_count"])
            if raw.get("deck_invocation_count") and game is not None and controller is not None:
                # 指定侧牌库中结附指定灵咒的牌数（食梦貘"敌方牌库中每有一张'梦魇'"）
                spec = raw["deck_invocation_count"] or {}
                name = spec.get("name")
                side = spec.get("side", "enemy")
                pi = controller if side == "self" else 1 - controller
                dyn += sum(1 for c in game.state.players[pi].deck
                           if any(e["name"] == name for e in c.invocations))
            if raw.get("burst_x"):
                # 爆能 X 快照（不夜之火批次）：memo 优先，否则出牌时写入的 card.mods
                if memo is not None and memo.get("burst_x") is not None:
                    dyn += int(memo["burst_x"])
                elif card is not None:
                    dyn += int(card.mods.get("burst_x", 0))
            if raw.get("dice_distinct") and game is not None and controller is not None:
                # 骰子历史去重种数（九莲宝灯动态身材；ext dice_history 记最终有效骰点）
                dyn += len(set(game.state.players[controller].ext.get("dice_history", [])))
            if raw.get("enemy_stunned_count") and game is not None and controller is not None:
                # 场上眩晕的敌方角色数（霜天之织[增强]"每有一个便+1力量"；活局面量，
                # 眩晕解除即减——统一读取点 engine._enemy_stunned_count）
                dyn += game._enemy_stunned_count(controller)
            if raw.get("enemy_revealed_count") and game is not None and controller is not None:
                # 敌方手牌中已展示牌计数（三口径，engine._enemy_revealed_count）
                dyn += game._enemy_revealed_count(controller,
                                                  raw["enemy_revealed_count"], chosen)
            if raw.get("kill_count") and game is not None and controller is not None:
                # 击杀账本计数（禁锢之刀/夺命）：打出装配快照优先，否则读活账本
                spec = raw["kill_count"] or {}
                snap = (card.mods.get("_kill", {}) if card is not None else None) or {}
                skey = _kill_snap_key(spec)
                dyn += (int(snap[skey]) if skey in snap
                        else game._kill_count(controller, spec))
            if raw.get("half_health_of") and event is not None and game is not None:
                ref = event.get(raw["half_health_of"])
                if isinstance(ref, Ref):
                    pl = game.state.players[ref.player]
                    hp = (pl.shikigami[ref.shikigami].health
                          if ref.shikigami is not None else pl.health)
                    dyn += hp // 2  # "一半生命"：向下取整
            if raw.get("health_of") in ("self", "source") and s is not None:
                dyn += s.health  # 来源式神当前生命（灾厄之花）
            if raw.get("orb") and game is not None and controller is not None:
                dyn += int(game.state.players[controller].orb)  # 控制者当前鬼火（汲取养分）
            if raw.get("max_power_gap") and s is not None:
                dyn += max(0, int(s.ext.get("max_power", 0)) - s.eff_power)
            if raw.get("missing_health") and s is not None:
                dyn += s.max_health - s.health  # "恢复所有生命"（鹤唳回风）
            if raw.get("countdown_holders") == "friendly_others" \
                    and game is not None and controller is not None:
                # 控制者在场未气绝、当前持有倒计时能力的式神像数（排除来源；突[增强]）
                holders = [x for x in game.state.players[controller].shikigami
                           if x.in_play and x.countdown_block is not None and x is not s]
                dyn += len(holders)
            if raw.get("max_shield_or_fragile") and game is not None:
                # 场上最大护甲或破甲（遮雨）：双方所有角色（在场式神 + 牌手）的
                # |shield| 最大值——shield 有符号，正值护甲与负值破甲同口径比较
                vals = []
                for pl in game.state.players:
                    vals.append(abs(pl.shield))
                    vals += [abs(x.shield) for x in pl.shikigami if x.in_play]
                dyn += max(vals, default=0)
            result = base + dyn * int(raw.get("per", 1))  # 动态项总和按倍率放大（禁锢之刀）
            if raw.get("negate"):
                result = -result  # 取负（倒计时减少量、共享效果的负向应用）
            return result
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
            "choose": self._cmd_choose,
        }
        handler = handlers.get(op)
        if handler is None:
            raise IllegalAction(f"未知指令: {op}")
        if self.state.pending_choice is not None and op != "choose":
            raise IllegalAction("存在待处理的选择（请先完成检视选牌）")
        if self.state.phase == "mulligan" and op not in ("mulligan", "ready"):
            raise IllegalAction("调度阶段：请先完成调度（mulligan/ready）")
        if self.state.phase == "upgrade" and op not in ("upgrade",):
            raise IllegalAction("升级阶段：请先完成升级")
        if self.state.phase == "battle" and op == "upgrade":
            raise IllegalAction("当前不在升级阶段")
        if op in ("play_card", "assault", "upgrade", "end_turn"):
            # 玩家动作开启新响应窗口（choose 为结算中挂起的续答、debug 为测试脚手架，
            # 均不开新窗口——窗口 = 两次玩家行动之间的完整结算）
            self._response_window += 1
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

    # ---------- 结算中交互选择（青灯夜谈：检视牌库顶选牌） ----------

    def _cmd_choose(self, cmd: dict) -> None:
        """choose 指令：结算中交互选择的统一作答入口。

        - kind="deck_top_pick"（青灯夜谈/明心）：从 options 中选一张置入手牌，然后洗牌库。
          每次重复都重新检视（洗牌后）牌库顶 count 张；最后一次选择后按 pending 的
          clear_orb 清空鬼火，并续跑挂起块的剩余步骤（_suspended）。
        - kind="mulligan_pick"（云游击中调度）：uid 给出手牌 → 换该张；uid 缺省/次数
          用尽 → 结束并洗牌库，续跑挂起块。
        - kind="discard_pick"（意外之喜"弃一张牌"）：uid 给出手牌 → 弃置该张；
          次数用尽/无手牌 → 结束，续跑挂起块。
        - kind="card_name"（忘忧的旋律，两级）：stage="shikigami" 时 choice 给出
          敌方式神数据 id → 转 stage="card"（该式神可构筑牌池）；stage="card" 时
          choice 给出卡牌数据 id → 对 target_player 手牌+牌库移除全部同名牌，
          续跑挂起块。
        - kind="field_summon_pick"（残阳无影"选择召唤"）：choice 给出幻境牌数据 id
          → 凭空直接召唤对应幻境（不经使用事件），续跑挂起块。
        - kind="pick_generate"（三目委托线索"选择一张置入手牌"）：choice 给出卡牌
          数据 id → 生成（generated=True）入手，续跑挂起块。
        - kind="quest_complete_pick"（委托整理"使一张紧急委托视为达成"）：uid 给出
          手牌 → 该实例 mods["quest_done"] 置位，续跑挂起块。
        - kind="invocation_pick"（鬼切"选择一张鬼斩结附"）：choice 给出灵咒名
          → 对 pending 目标结附，续跑挂起块。
        """
        pending = self.state.pending_choice
        if pending is None:
            raise IllegalAction("当前没有待处理的选择")
        if pending.get("kind") == "mulligan_pick":
            self._cmd_battle_mulligan_choose(cmd, pending)
            return
        if pending.get("kind") == "discard_pick":
            self._cmd_discard_pick_choose(cmd, pending)
            return
        if pending.get("kind") == "card_name":
            self._cmd_card_name_choose(cmd, pending)
            return
        if pending.get("kind") == "field_summon_pick":
            self._cmd_field_summon_choose(cmd, pending)
            return
        if pending.get("kind") == "pick_generate":
            self._cmd_pick_generate_choose(cmd, pending)
            return
        if pending.get("kind") == "invocation_pick":
            self._cmd_invocation_pick_choose(cmd, pending)
            return
        if pending.get("kind") == "quest_complete_pick":
            self._cmd_quest_complete_choose(cmd, pending)
            return
        if pending.get("kind") != "deck_top_pick":
            raise IllegalAction(f"未知选择类型: {pending.get('kind')}")
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        p = self.state.players[pi]
        uid = cmd.get("uid")
        if uid not in pending["options"]:
            raise IllegalAction("不在可检视的牌之列")
        card = next((c for c in p.deck if c.uid == uid), None)
        if card is None:
            raise IllegalAction("该牌已不在牌库中")
        self.move_card(p, card, "hand", reason="pick")
        self._log(f"{p.name} 将检视的【{self.db.cards[card.id].name}】置入手牌")
        self.rng.shuffle(p.deck)  # 按原文"然后洗牌库"：每次选择后都洗牌
        self.state.pending_choice = None
        if not self._open_deck_top_pick(pi, pending["count"],
                                        pending["remaining"] - 1, pending["clear_orb"]):
            # 重复结束（或牌库已空无可检视）：清空鬼火（0 鬼火开局挂起时同样执行）并续块
            if pending["clear_orb"]:
                self._clear_orb(p, pi)
            if self._suspended is not None:
                block, ctx, start = self._suspended
                self._suspended = None
                self._resolve_block(block, ctx, start)

    def _open_deck_top_pick(self, pi: int, count: int, remaining: int,
                            clear_orb: bool) -> bool:
        """开启一次牌库顶挑选：设置 pending_choice 挂起等待 choose 指令；返回是否挂起。
        重复次数耗尽或牌库无可检视牌时不挂起（返回 False，由调用方走收尾）。"""
        p = self.state.players[pi]
        options = [c.uid for c in p.deck[:count]]
        if remaining <= 0 or not options:
            return False
        self.state.pending_choice = {
            "kind": "deck_top_pick", "player": pi, "count": count,
            "options": options, "remaining": remaining, "clear_orb": clear_orb,
        }
        self._log(f"{p.name} 检视牌库顶 {len(options)} 张牌（选择一张置入手牌）")
        return True

    def _cmd_battle_mulligan_choose(self, cmd: dict, pending: dict) -> None:
        """战中调度（云游）作答：uid 给出 → 换该张手牌（_swap_hand_card 核心）；
        uid 缺省 / 次数用尽 / 无手牌可换 → 结束，按 pending 的 shuffle 洗牌库，
        并续跑挂起块的剩余步骤（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        p = self.state.players[pi]
        uid = cmd.get("uid")
        card = next((c for c in p.hand if c.uid == uid), None) if uid else None
        if uid and card is None:
            raise IllegalAction("手牌中没有这张牌")
        if card is not None:
            self._swap_hand_card(p, card)
            pending["remaining"] -= 1
            self._log(f"{p.name} 调度了一张手牌（剩余 {pending['remaining']} 次）")
        if card is None or pending["remaining"] <= 0 or not p.hand:
            self.state.pending_choice = None
            if pending.get("shuffle"):
                self.rng.shuffle(p.deck)
                self._log(f"{p.name} 洗了牌库")
            if self._suspended is not None:
                block, ctx, start = self._suspended
                self._suspended = None
                self._resolve_block(block, ctx, start)

    def _open_field_summon_pick(self, pi: int, options: list[int], *,
                                intensity: int | None = None,
                                source: Ref | None = None) -> bool:
        """开启"选择召唤幻境"交互（残阳无影，kind="field_summon_pick"）：选项 = 可召唤
        幻境牌的数据 id 列表（>1 张才挂起，由 summon_field 保证）；作答键 choice
        （数据 id，同 card_name）。intensity 覆写/来源随 pending 传递（source 序列化
        为 [player, shikigami] 下标对）。"""
        p = self.state.players[pi]
        self.state.pending_choice = {
            "kind": "field_summon_pick", "player": pi, "options": list(options),
            "intensity": intensity,
            "source": ([source.player, source.shikigami]
                       if source is not None else None),
        }
        self._log(f"{p.name} 选择要召唤的幻境")
        return True

    def _cmd_field_summon_choose(self, cmd: dict, pending: dict) -> None:
        """选择召唤幻境作答：choice 给出幻境牌数据 id → 凭空实例直接召唤（不经使用
        事件、不耗火、耐久=卡牌标注值或覆写值，走 _summon_field 完整流程），
        清 pending 并续跑挂起块（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        choice = cmd.get("choice")
        if choice not in pending["options"]:
            raise IllegalAction("不在可召唤的幻境之列")
        cdef = self.db.cards[int(choice)]
        src = pending.get("source")
        source = Ref(player=src[0], shikigami=src[1]) if src else None
        inst = CardInstance(uid=self.state.next_uid, id=cdef.id)  # 凭空实例（仅载体，不进区域）
        self.state.next_uid += 1
        self._summon_field(pi, inst, cdef, source, reason="效果召唤",
                           intensity_override=pending.get("intensity"))
        self.state.pending_choice = None
        if self._suspended is not None:
            block, ctx, start = self._suspended
            self._suspended = None
            self._resolve_block(block, ctx, start)

    def _open_pick_generate(self, pi: int, options: list[int],
                            unique_ext: str | None = None) -> bool:
        """开启"选择一张生成入手"交互（三目委托线索，kind="pick_generate"）：选项 =
        可生成卡牌的数据 id 列表（>1 张才挂起，由 pick_generate 动作保证）；作答键
        choice（数据 id，同 field_summon_pick）。unique_ext 随 pending 传递（觉醒·三目
        "不重复"账本题 quest_clues_seen 记账）。"""
        p = self.state.players[pi]
        self.state.pending_choice = {
            "kind": "pick_generate", "player": pi, "options": list(options),
            "unique_ext": unique_ext,
        }
        self._log(f"{p.name} 选择一张牌置入手牌")
        return True

    def _cmd_pick_generate_choose(self, cmd: dict, pending: dict) -> None:
        """选择生成作答：choice 给出卡牌数据 id → 新建生成实例（generated=True）入手
        （走生成点统一快照），按 pending 的 unique_ext 记账（不重复抽取口径），
        清 pending 并续跑挂起块（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        choice = cmd.get("choice")
        if choice not in pending["options"]:
            raise IllegalAction("不在可生成的牌之列")
        p = self.state.players[pi]
        cdef = self.db.cards[int(choice)]
        inst = CardInstance(uid=self.state.next_uid, id=cdef.id, generated=True)
        self.state.next_uid += 1
        self.move_card(p, inst, "hand", reason="generate")
        self._materialize(p, inst, cdef)  # 生成点统一快照（断罪 form_power_delta 等）
        self._log(f"{p.name} 将【{cdef.name}】置入手牌")
        if pending.get("unique_ext"):
            p.ext.setdefault(pending["unique_ext"], []).append(cdef.id)
        self.state.pending_choice = None
        if self._suspended is not None:
            block, ctx, start = self._suspended
            self._suspended = None
            self._resolve_block(block, ctx, start)

    def _open_invocation_pick(self, pi: int, options: list[str],
                              target: Ref | None, source: Ref | None) -> bool:
        """开启"选择灵咒结附"交互（鬼切"选择一张鬼斩结附"，kind="invocation_pick"）：
        选项 = 灵咒名列表（>1 个才挂起，由 choose_invocation 动作保证）；作答键
        choice（灵咒名，同 pick_generate）。结附目标/来源随 pending 传递（Ref 序列化
        为 [player, shikigami] 下标对）。"""
        p = self.state.players[pi]
        self.state.pending_choice = {
            "kind": "invocation_pick", "player": pi, "options": list(options),
            "target": ([target.player, target.shikigami]
                       if target is not None else None),
            "source": ([source.player, source.shikigami]
                       if source is not None else None),
        }
        self._log(f"{p.name} 选择一张灵咒牌结附")
        return True

    def _cmd_invocation_pick_choose(self, cmd: dict, pending: dict) -> None:
        """选择灵咒作答：choice 给出灵咒名 → 对 pending 的目标结附该灵咒（来源所属
        牌手 = 作答方；走 attach_invocation 完整流程——唯一性/事件照常），
        清 pending 并续跑挂起块（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        choice = cmd.get("choice")
        if choice not in pending["options"]:
            raise IllegalAction("不在可选的灵咒之列")
        tref = pending.get("target")
        if tref is None:
            raise IllegalAction("灵咒结附缺少目标")
        sref = pending.get("source")
        self.attach_invocation(
            str(choice), player=pi,
            source=Ref(player=sref[0], shikigami=sref[1]) if sref else None,
            target=Ref(player=tref[0], shikigami=tref[1]))
        self.state.pending_choice = None
        if self._suspended is not None:
            block, ctx, start = self._suspended
            self._suspended = None
            self._resolve_block(block, ctx, start)

    def _open_quest_complete_pick(self, pi: int, options: list[int]) -> bool:
        """开启"使一张紧急委托视为达成"交互（委托整理，kind="quest_complete_pick"）：
        选项 = 手牌中可标记卡牌的 uid 列表（>1 张才挂起，由 quest_complete 动作保证）；
        作答键 uid（同 discard_pick）。"""
        p = self.state.players[pi]
        self.state.pending_choice = {
            "kind": "quest_complete_pick", "player": pi, "options": list(options),
        }
        self._log(f"{p.name} 选择一张紧急委托使其视为达成")
        return True

    def _cmd_quest_complete_choose(self, cmd: dict, pending: dict) -> None:
        """委托整理作答：uid 给出手牌 → 该实例 mods["quest_done"] 置位（[条件]使用前提
        视为满足，_play_condition_met 读取），清 pending 并续跑挂起块（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        uid = cmd.get("uid")
        if uid not in pending["options"]:
            raise IllegalAction("不在可选的手牌之列")
        p = self.state.players[pi]
        card = next((c for c in p.hand if c.uid == uid), None)
        if card is None:
            raise IllegalAction("该牌已不在手牌中")
        card.mods["quest_done"] = True
        self._log(f"{p.name} 的【{self.db.cards[card.id].name}】委托条件视为达成")
        self.state.pending_choice = None
        if self._suspended is not None:
            block, ctx, start = self._suspended
            self._suspended = None
            self._resolve_block(block, ctx, start)

    def _open_discard_pick(self, pi: int, remaining: int) -> bool:
        """开启一次交互弃牌（意外之喜）：设置 pending_choice kind="discard_pick"
        挂起等待 choose 指令；返回是否挂起。无手牌或次数耗尽时不挂起（返回 False，
        由调用方/作答分支走收尾）。"""
        p = self.state.players[pi]
        if remaining <= 0 or not p.hand:
            return False
        self.state.pending_choice = {
            "kind": "discard_pick", "player": pi, "remaining": remaining,
            "options": [c.uid for c in p.hand],
        }
        self._log(f"{p.name} 选择一张手牌弃置")
        return True

    def _cmd_discard_pick_choose(self, cmd: dict, pending: dict) -> None:
        """交互弃牌作答：uid 给出手牌 → 弃置该张（同 discard 的弃牌核心：日志 +
        移入墓地）；次数用尽/无手牌 → 结束并续跑挂起块（_suspended）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        p = self.state.players[pi]
        uid = cmd.get("uid")
        if uid not in pending["options"]:
            raise IllegalAction("不在可选的手牌之列")
        card = next((c for c in p.hand if c.uid == uid), None)
        if card is None:
            raise IllegalAction("该牌已不在手牌中")
        self._log(f"{p.name} 弃掉了【{self.db.cards[card.id].name}】")
        self.move_card(p, card, "graveyard")
        self.state.pending_choice = None
        if not self._open_discard_pick(pi, pending["remaining"] - 1):
            if self._suspended is not None:
                block, ctx, start = self._suspended
                self._suspended = None
                self._resolve_block(block, ctx, start)

    def _open_card_name_pick(self, pi: int) -> bool:
        """开启忘忧的旋律两级选择（kind="card_name"）：stage="shikigami" 列出敌方
        全部式神数据 id（含气绝，未离场；等级 ≥1 即已参战的出战队列成员）。
        敌方无可选式神时不挂起（返回 False）。"""
        ep = self.state.players[1 - pi]
        options = [s.id for s in ep.shikigami
                   if not s.despawned and s.level >= 1]
        if not options:
            return False
        self.state.pending_choice = {
            "kind": "card_name", "player": pi, "stage": "shikigami",
            "options": options, "target_player": 1 - pi,
        }
        self._log(f"{self.state.players[pi].name} 选择敌方式神的一张牌名")
        return True

    def _cmd_card_name_choose(self, cmd: dict, pending: dict) -> None:
        """忘忧的旋律作答：stage="shikigami" → 按所选式神算可构筑牌池（非衍生、
        本家卡 + 作为第二所属式神的协战牌，口径同 client.deckbuilder.buildable_cards）
        转 stage="card"；stage="card" → 对 target_player 手牌+牌库移除全部同名牌
        （purge_copies 核心；刚使用/在场的同名实体不在两区域，不受影响），
        清 pending 并续跑挂起块。作答键统一为 choice（数据 id，非 uid）。"""
        pi = cmd.get("player", self.state.active)
        if pi != pending["player"]:
            raise IllegalAction("不是你的选择（等待对应玩家作答）")
        choice = cmd.get("choice")
        if choice not in pending["options"]:
            raise IllegalAction("不在可选之列")
        if pending["stage"] == "shikigami":
            sid = int(choice)
            pool = sorted(c.id for c in self.db.cards.values()
                          if not c.token and (c.shikigami == sid
                                              or (c.card_type == "reinforce"
                                                  and c.shikigami2 == sid)))
            if not pool:
                raise IllegalAction("该式神没有可选择的牌")
            pending["stage"] = "card"
            pending["options"] = pool
            self._log(f"选择了 {self.db.shikigami[sid].name}，选择其一张牌名")
            return
        # stage == "card"：移除目标方手牌+牌库中的全部同名牌
        cid = int(choice)
        tp = self.state.players[pending["target_player"]]
        copies = [c for c in tp.hand if c.id == cid] + [c for c in tp.deck if c.id == cid]
        for c in copies:
            self.move_card(tp, c, "exiled")
        self._log(f"{tp.name} 的 {len(copies)} 张【{self.db.cards[cid].name}】被移除")
        self.state.pending_choice = None
        if self._suspended is not None:
            block, ctx, start = self._suspended
            self._suspended = None
            self._resolve_block(block, ctx, start)

    def _clear_orb(self, p: PlayerState, pi: int) -> None:
        """清空玩家鬼火（吸魂灯/青灯夜谈"清空你的鬼火"）；emit on_orb_changed。
        一次性变化（如 2→0 不经过 1，不触发"鬼火变为 1"类条件）。"""
        old = p.orb
        p.orb = 0
        if old != 0:
            self.emit("on_orb_changed", player=pi, old=old, new=0, reason="清空鬼火")
        p.orb = 0
        if old != 0:
            self.emit("on_orb_changed", player=pi, old=old, new=0, reason="清空鬼火")

    def _pay_orb(self, p: PlayerState, pi: int, cost: int, reason: str) -> None:
        """支付鬼火（使用牌/出击/响应的消耗）：变化后 emit on_orb_changed（old→new）。
        即时时机——付费点先于效果结算，"鬼火变为 1"类响应可插入于效果之前。"""
        if cost <= 0:
            return
        old = p.orb
        p.orb = max(0, p.orb - cost)
        if p.orb != old:
            self.emit("on_orb_changed", player=pi, old=old, new=p.orb, reason=reason)

    # ---------- 能量（不夜之火批次；上限 10、气绝保留） ----------

    def _gain_energy(self, p: PlayerState, i: int, n: int, *, emit_event: bool = True) -> int:
        """式神获得 n 点能量（上限 10），返回实际获得量。

        实际获得量 > 0 且 emit_event 时 emit on_energy_gained（延时时机；payload 含
        old/new/amount=实际获得量——按量监听用 old:0 类条件判首次获得）。emit_event=False
        供"获得能量时"类监听内部追加（烟烟罗觉醒改为两倍），防递归。"""
        s = p.shikigami[i]
        old = s.energy
        s.energy = min(10, s.energy + n)
        gained = s.energy - old
        # 满上限（实际获得 0）仍发"时"时机（维护者定案，对照满生命治疗）：amount=0、old==new；
        # 能量体系只有"时"（on_energy_gained）没有"后"（无 on_after_energy_gained，
        # 对照 on_heal/on_after_heal 双时机——此处注释注明差异）
        if emit_event and (gained > 0 or n > 0):
            pi0 = self.state.players.index(p)
            self.emit("on_energy_gained", player=pi0,
                      target=Ref(player=pi0, shikigami=i),
                      old=old, new=s.energy, amount=gained)
        if gained > 0:
            self._settle(f"【能量】{self.db.shikigami[s.id].name} 能量 {old}→{s.energy}")
            self._refresh_stat_auras()  # 能量变化点：动态能量光环缓存重算
        return gained

    def _energy_free_available(self, pi: int) -> bool:
        """能量免单（觉醒·日和坊"每回合一次，消耗能量时改为不消耗"）：
        本回合名额未消耗（ext energy_free_turn）且有在场已觉醒日和坊。"""
        p = self.state.players[pi]
        if not p.ext.get("energy_free_turn"):
            return False
        return any(s.in_play and s.id == _RIHEFANG_SHIKIGAMI and s.awakened is not None
                   for s in p.shikigami)

    @staticmethod
    def _energy_life_substitute(s: ShikigamiState) -> bool:
        """生命代偿提供者：在场日和坊（基础能力，引擎直读 id）或带 energy_life_substitute
        ext 标记（扩展预留）。"""
        return s.in_play and (s.id == _RIHEFANG_SHIKIGAMI
                              or bool(s.ext.get("energy_life_substitute")))

    def _can_pay_energy(self, p: PlayerState, i: int, n: int) -> bool:
        """能量可支付判定（不变异；_spend_energy 的同谓词预检）：
        免单名额可用 / 能量足够 / 在场日和坊生命代偿差额（代偿后生命不降到 0）。"""
        if n <= 0:
            return True
        if self._energy_free_available(self.state.players.index(p)):
            return True
        s = p.shikigami[i]
        if s.energy >= n:
            return True
        lack = n - s.energy
        return any(self._energy_life_substitute(o) and o.health - lack >= 1
                   for o in p.shikigami)

    def _spend_energy(self, p: PlayerState, i: int, n: int) -> bool:
        """支付 n 点能量：免单名额（置 False 消耗）→ 能量足够直扣 → 日和坊生命代偿
        差额（直扣生命、非伤害、不降到 0）。支付失败返回 False（调用方应先 _can_pay_energy
        预检，正常不会到此）。"""
        if n <= 0:
            return True
        pi = self.state.players.index(p)
        s = p.shikigami[i]
        if self._energy_free_available(pi):
            p.ext["energy_free_turn"] = False
            self._settle(f"【能量】{self.db.shikigami[s.id].name} 的 {n} 点能量消耗被免单"
                         f"（觉醒·日和坊）")
            return True
        if s.energy >= n:
            s.energy -= n
            self._settle(f"【能量】{self.db.shikigami[s.id].name} 消耗 {n} 点能量"
                         f"（剩余 {s.energy}）")
            self._refresh_stat_auras()  # 能量变化点：动态能量光环缓存重算
            return True
        lack = n - s.energy
        for o in p.shikigami:
            if self._energy_life_substitute(o) and o.health - lack >= 1:
                s.energy = 0
                o.health -= lack  # 生命代偿：直扣生命，非伤害（不走伤害管线，不触发伤害事件）
                self._settle(f"【能量】{self.db.shikigami[o.id].name} 以 {lack} 点生命代偿能量"
                             f"（剩余生命 {o.health}）")
                self._refresh_stat_auras()  # 能量变化点：动态能量光环缓存重算
                return True
        return False

    # ---------- 调度（游戏开始阶段） ----------

    def _cmd_mulligan(self, cmd: dict) -> None:
        """调度（Phase 1 简化版）：把一张起始手牌返回牌库（随机位置），再随机抽一张。

        完整规则（docs/rules.md 调度事件流程）包含加护/蚀印移除、灵咒移除、洗牌后
        时机等，暂不处理；"已展示"状态传递已在 _swap_hand_card 落实（rules 528-533）。
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
        self._swap_hand_card(p, card)
        p.mulligans_left -= 1
        self._log(f"{p.name} 调度了一张手牌（剩余 {p.mulligans_left} 次）")
        if p.mulligans_left == 0:
            p.mulligan_done = True
        if all(p.mulligan_done for p in self.state.players):
            self._begin_battle()

    def _swap_hand_card(self, p: PlayerState, card: CardInstance) -> None:
        """调度换牌核心：把一张手牌返回牌库（随机位置），再随机抽一张放到原位置
        （抽上牌继承换回牌的顺序编号）。游戏开始阶段调度与战中调度（云游/强索）共用。

        展示状态细则（docs/rules.md:528-533；以下按 rules 术语——
        "换入牌"=返回牌库的手牌，"换出牌"=牌库抽上的新牌）：
        换入牌具有"已展示"则失去（rules 528）；换入牌原本具有"已展示"则换出牌
        获得"已展示"（rules 530）。换出牌入手经统一钩子 _enter_hand 发点。"""
        idx = p.hand.index(card)
        old_seq = card.hand_seq
        had_revealed = bool(card.mods.pop("revealed", None))  # 换入牌失去已展示
        p.hand.pop(idx)
        p.deck.insert(self.rng.randint(0, len(p.deck)), card)      # 返回牌库
        new_card = p.deck.pop(self.rng.randint(0, len(p.deck) - 1))  # 再随机抽一张
        if new_card.invocations:
            # 换出牌结附的灵咒直接移除而不生效（rules.md 第二十一章；调度非抽牌）
            new_card.invocations = []
            self._log(f"【{self.db.cards[new_card.id].name}】上结附的灵咒移除（调度换出）")
        new_card.hand_seq = old_seq                                 # 换出牌继承换回牌的顺序编号
        p.hand.insert(idx, new_card)
        if had_revealed:
            new_card.mods["revealed"] = True  # 换入牌原本已展示 → 换出牌获得已展示
        self._enter_hand(p, new_card)

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

    def reinforce_sub_option_error(self, pi: int, cdef: CardDef,
                                   choice: int) -> str | None:
        """协战牌子选项合法性预检（裁决(16) CLI 多择引导：列出全部子选项<含不合法>，
        选不合法要求重选）：返回不合法原因文本，None = 可选。仅校验子选项本身
        （所属式神出战/气绝/等级、鬼火）；目标合法性在出牌时另行校验。"""
        options = list(cdef.options or [])
        if choice not in range(len(options)):
            return "无效的子选项序号"
        sub = self.db.cards[options[choice]]
        p = self.state.players[pi]
        if sub.shikigami is not None:
            si = self._find_shikigami(p, sub.shikigami)
            sname = self.db.shikigami[sub.shikigami].name
            if si is None:
                return f"所属式神{sname}未出战"
            s = p.shikigami[si]
            if s.defeated and not sub.playable_when_defeated:
                return f"{sname} 气绝中"
            if s.level < sub.level:
                return f"需要 {sname} 达到 {sub.level} 级（当前 {s.level} 级）"
        cost = self._effective_cost(p, sub)
        if p.orb < cost:
            return f"鬼火不足（需要 {cost}，现有 {p.orb}）"
        return None

    def _cmd_play_reinforce(self, p: PlayerState, card: CardInstance,
                            cdef: CardDef, cmd: dict) -> None:
        """协战牌打出（维护者答复 10）：选择子选项 → 生成对应 token 子卡入手并
        "视作从手牌使用"（正常耗火、等级检测按子选项、完整使用事件流程——递归走
        _cmd_play_card，含 on_before_card_play/on_card_played）→ 主牌离手移除（不进墓地）。

        合法性前置校验（子选项所属式神出战/未气绝/等级、鬼火、目标、尘缚之阵锁定）失败时
        主牌仍在手（不产生 token）；通过后的递归使用不应再失败。
        """
        owners = [sid for sid in (cdef.shikigami, cdef.shikigami2) if sid is not None]
        if not any(self._find_shikigami(p, sid) is not None for sid in owners):
            raise IllegalAction(f"【{cdef.name}】的所属式神（{cdef.shikigami} / "
                                f"{cdef.shikigami2}）均未出战")
        options = list(cdef.options)
        if len(options) != 2:
            raise IllegalAction(f"【{cdef.name}】缺少子选项数据")
        choice = cmd.get("choice")
        if choice not in (0, 1):
            names = " / ".join(f"[{i}]【{self.db.cards[o].name}】"
                               for i, o in enumerate(options))
            raise IllegalAction(f"协战牌需要选择子选项（choice 0/1）：{names}")
        err = self.reinforce_sub_option_error(self.state.active, cdef, choice)
        if err is not None:
            raise IllegalAction(f"【{cdef.name}】的子选项当前不可选：{err}")
        sub = self.db.cards[options[choice]]
        si: int | None = (self._find_shikigami(p, sub.shikigami)
                          if sub.shikigami is not None else None)
        if sub.target.kind == "choose":
            want = cmd.get("target")
            if want is None:
                raise IllegalAction("该子选项需要选择目标")
            want = want if isinstance(want, Ref) else Ref(**want)
            if want not in targets.spec_pool_refs(self, sub.target, self.state.active):
                raise IllegalAction("目标不合法")
        if (sub.card_type == "combat" and si is not None
                and p.combat_index != si
                and not self._has_keyword(p.shikigami[si], "remote")
                and self._combat_zone_locked(self.state.active)):
            raise IllegalAction("尘缚之阵：准备区式神不能发起不具有远程的战斗")
        # 生成子选项 token 入手，视作从手牌使用（完整使用事件流程）
        inst = CardInstance(uid=self.state.next_uid, id=sub.id)
        self.state.next_uid += 1
        self.move_card(p, inst, "hand", reason="generate")
        self._log(f"{p.name} 使用【{cdef.name}】：选择子选项【{sub.name}】")
        sub_cmd: dict = {"op": "play_card", "uid": inst.uid}
        if cmd.get("target") is not None:
            sub_cmd["target"] = cmd["target"]
        self._cmd_play_card(sub_cmd)
        # 主牌离手放逐（不进墓地；子选项被无效化等"已使用"情形同样离手）
        self._remove_from_zone(p, card)
        p.zones["exiled"].append(card)

    def _apply_revive_haste(self, p: PlayerState, card: CardInstance) -> None:
        """使用实例修饰 revive_haste（鎏金幻羽"使用后以津真天和鸩气绝倒计时-1"）：
        按数据 id 对控制者已气绝式神气绝倒计时 -1，减到 ≤0 立即复活。"""
        sids = card.mods.get("revive_haste")
        if not sids:
            return
        pi = self.state.players.index(p)
        for sid in sids:
            si = self._find_shikigami(p, int(sid))
            if si is None:
                continue
            s = p.shikigami[si]
            if not s.defeated or s.despawned:
                continue
            s.revive_countdown -= 1
            self._log(f"{self.db.shikigami[s.id].name} 的气绝倒计时 -1（{s.revive_countdown}）")
            if s.revive_countdown <= 0:
                self._revive(p, pi, si)

    # ---------- 出牌 ----------

    def _cmd_play_card(self, cmd: dict) -> None:
        p = self.current
        uid = cmd.get("uid")
        play_from = cmd.get("play_from", "hand")  # 使用位置：默认手牌，保留扩展（牌库/墓地…）
        card = next((c for c in p.zones.get(play_from, []) if c.uid == uid), None)
        if card is None:
            raise IllegalAction(f"区域 {play_from} 中没有这张牌")
        if play_from == "deck":
            # 彼岸归航（幻境实体关键字 deck_top_play）：牌库顶的牌视同手牌使用——
            # 仅限牌库顶一张、须该幻境在场；合法性/目标/等级判定与手牌一致，
            # 等级 1 的牌不耗鬼火（费用求值处覆盖），使用时受 2 点伤害（结算后）
            if not p.deck or p.deck[0] is not card:
                raise IllegalAction("只能使用牌库顶的牌")
            if not any("deck_top_play" in f.keywords for f in p.fields):
                raise IllegalAction("需要【彼岸归航】在场才能使用牌库顶的牌")
        cdef = self.db.cards[card.id]
        # Phase 1 实现法术牌、形态牌、战斗牌、幻境牌；协战牌走子选项流程（_cmd_play_reinforce）。
        if cdef.card_type == "reinforce":
            self._cmd_play_reinforce(p, card, cdef, cmd)
            return
        # [条件] 使用前提（福满乾坤）：不满足则任何方式都不能使用（响应/自动使用同检）
        if not self._play_condition_met(p, cdef, card):
            raise IllegalAction(f"【{cdef.name}】的使用条件未满足")
        # 使用方式（多择子选项，仅保留核心方式、参数可变；按 id 匹配，param 为数据预留）
        method: PlayMethod | None = None
        method_id = cmd.get("play_method")
        if method_id is not None:
            method = next((m for m in self._card_methods(p, cdef) if m.id == method_id),
                          None)
            if method is None:
                raise IllegalAction(f"【{cdef.name}】没有使用方式「{method_id}」")
        # 生效的等级要求与目标（使用方式可覆盖）；生效类型 = 方式类型覆盖（爆能转化
        # 战斗牌，御馔津符咒牌[爆能3]）或卡牌主类型
        eff_level = method.level if (method and method.level is not None) else cdef.level
        eff_target = method.target if (method and method.target is not None) else cdef.target
        eff_type = method.card_type if (method and method.card_type) else cdef.card_type
        # 所属式神检查（中立牌无从属式神，跳过；气绝时可用看卡牌标记，与是否响应无关）
        si: int | None = None
        fdp_cost: int | None = None  # 气绝形态使用（form_death_play 旗标）的能量消耗
        if cdef.shikigami is not None:
            si = self._find_card_owner(p, cdef.shikigami)
            sname = self.db.shikigami[cdef.shikigami].name
            if si is None:
                if any(st.transform_owner == cdef.shikigami for st in p.shikigami):
                    # 变形物保留"所属式神"= 原式神 id：原式神被变形中，其牌不能使用
                    # （式神替换物不在此列——replace_owner 路径已在 _find_card_owner 放行）
                    raise IllegalAction(f"{sname} 被变形中，不能使用其卡牌")
                raise IllegalAction(f"{sname} 未出战")
            s = p.shikigami[si]
            if s.stuns:
                raise IllegalAction(f"{sname} 眩晕中，不能使用其卡牌")
            if s.defeated and not self._playable_when_defeated(cdef, card):
                # 气绝形态使用（觉醒·小鹿男旗标）：形态牌 + 旗标持有者 + 能量可付则放行
                fdp_cost = self._form_death_play_cost(p, si, cdef)
                if fdp_cost is None or not self._can_pay_energy(p, si, fdp_cost):
                    raise IllegalAction(f"{sname} 气绝中，无法使用其卡牌")
            if not s.defeated and cdef.only_when_defeated:
                raise IllegalAction(f"【{cdef.name}】仅在{sname}气绝时可用")
            if s.level < eff_level:
                raise IllegalAction(f"【{cdef.name}】需要 {sname} 达到 {eff_level} 级（当前 {s.level} 级）")
        # 使用方式的觉醒门控（黄金羽觉醒后"以敌方角色为目标"方式：requires_awaken 数据标记）。
        # 维护者答复(11)：气绝时觉醒能力不在场——门控要求未气绝/未离场（觉醒标记本身
        # 跨气绝保留，但能力在场才生效）
        if method is not None and (method.model_extra or {}).get("requires_awaken"):
            gate = p.shikigami[si] if si is not None else None
            if gate is None or not gate.awakened or gate.defeated or gate.despawned:
                who = sname if si is not None else "所属式神"
                raise IllegalAction(f"「{method.text or method.id}」需要 {who} 已觉醒且在场上")
        # 方式授予关键字（PlayMethod.keywords，森之力"[爆能2]：获得[瞬发]"）：本次使用
        # 临时授予——装配在瞬发/费用判定（_effective_cost/_fast_applies）之前，结算后移除
        old_kw_add = card.mods.get("keywords_add")
        if method is not None and method.keywords:
            card.mods["keywords_add"] = list(old_kw_add or []) + list(method.keywords)
        # 尘缚之阵锁定：准备区式神不能发起不具有远程的战斗（战斗牌；出击见 _cmd_assault）
        if (eff_type == "combat" and si is not None
                and p.combat_index != si
                and not self._has_keyword(p.shikigami[si], "remote")
                and self._combat_zone_locked(self.state.active)):
            raise IllegalAction("尘缚之阵：准备区式神不能发起不具有远程的战斗")
        # 费用 = （方式覆盖或基础）+ 方式增减 + 实例修饰；瞬发仅免鬼火，其余条件照常
        cost = self._effective_cost(p, cdef, card=card, method=method)
        if play_from == "deck" and cdef.level == 1:
            cost = 0  # 彼岸归航："你牌库顶等级为1的牌不消耗鬼火"
        if p.orb < cost:
            raise IllegalAction(f"鬼火不足（需要 {cost}，现有 {p.orb}）")
        # 爆能（不夜之火批次）：使用方式带 energy_cost 时须额外支付能量；
        # "all" = 爆能 X（支付全部能量，至少 1 点）
        burst_all = method is not None and method.energy_cost == "all"
        energy_cost = 0
        if method is not None and method.energy_cost is not None:
            if si is None:
                raise IllegalAction(f"【{cdef.name}】的爆能方式需要所属式神在场")
            if burst_all:
                if p.shikigami[si].energy < 1:
                    raise IllegalAction(f"【{cdef.name}】的爆能 X 需要至少 1 点能量")
            else:
                energy_cost = int(method.energy_cost)
                # 狐狩界（幻境实体关键字 burst_discount）：你的所有[爆能]消耗 -1/个，
                # 可叠加（同名幻境各算一个）；至少 0
                discount = sum(1 for f in p.fields if "burst_discount" in f.keywords)
                energy_cost = max(0, energy_cost - discount)
                if not self._can_pay_energy(p, si, energy_cost):
                    raise IllegalAction(f"能量不足（爆能需要 {energy_cost}，"
                                        f"现有 {p.shikigami[si].energy}）")
        chosen: list[Ref] = []
        if eff_target.kind == "choose":
            want = cmd.get("target")
            if want is None:
                # optional 选择目标（天翔鹤斩类"有合法目标则必须选择、无则无目标结算"）：
                # 合法池为空时允许不带目标使用
                pool = targets.spec_pool_refs(self, eff_target, self.state.active,
                                              targeted=True)
                if not ((eff_target.model_extra or {}).get("optional") and not pool):
                    raise IllegalAction("该牌需要选择目标")
            else:
                want = want if isinstance(want, Ref) else Ref(**want)
                if want not in targets.spec_pool_refs(self, eff_target, self.state.active,
                                                      targeted=True):
                    raise IllegalAction("目标不合法")
                chosen = [want]
        # 第二选择目标（CardDef.target2，麓鸣·灭型双 choose 卡）：校验后追加进
        # chosen（[主目标, 第二目标]，step 侧用 chosen_index 按序取）
        t2 = cdef.target2
        if t2 is not None and t2.kind == "choose":
            want2 = cmd.get("target2")
            if want2 is None:
                pool2 = targets.spec_pool_refs(self, t2, self.state.active,
                                               targeted=True)
                if not ((t2.model_extra or {}).get("optional") and not pool2):
                    raise IllegalAction("该牌需要选择第二目标")
            else:
                want2 = want2 if isinstance(want2, Ref) else Ref(**want2)
                if want2 not in targets.spec_pool_refs(self, t2, self.state.active,
                                                       targeted=True):
                    raise IllegalAction("第二目标不合法")
                chosen.append(want2)
        if self._fast_applies(p, cdef, card):
            p.fast_used = True
        self._pay_orb(p, self.state.active, cost, reason="使用卡牌")
        if burst_all:
            # 爆能 X：快照当前能量为 X（{"burst_x": true} 读取点），随后全部支付
            energy_cost = p.shikigami[si].energy
            card.mods["burst_x"] = energy_cost
        if energy_cost:
            self._spend_energy(p, si, energy_cost)
        if fdp_cost:
            # 气绝形态使用：消耗能量（觉醒·日和坊免单/日和坊生命代偿同通道）
            self._spend_energy(p, si, fdp_cost)
        self._materialize(p, card, cdef)  # 打出装配：付费后、效果结算前快照持久修饰
        how = f"（{method.text or method.id}）" if method else ""
        self._log(f"{p.name} 使用了【{cdef.name}】{how}")
        # 使用手牌前（即时时机）：合法性检查与支付之后、效果结算之前。payload 的
        # nullified 为可变标记（参照伤害管线的可变 payload 模式）——监听者（魔音扰心/
        # 反制）置位后本次使用终止结算：跳过效果块，牌照常离手进墓地（费用/瞬发名额
        # 已付不退）。统一发点 _emit_before_card_play（定案(4)：任意方式使用同发）。
        marker = self._emit_before_card_play(self.state.active, card, cdef, eff_type)
        if marker["nullified"]:
            self.move_card(p, card, "graveyard")
            self._log(f"【{cdef.name}】的使用被无效化")
            return
        # 打出前来源式神已结附形态（形态牌先结附后发 on_card_played——"若萤草上有
        # 形态…使用时抽一张牌"类门控须按打出前状态判定，快照随事件 payload 携带）
        pre_play_form = si is not None and p.shikigami[si].form is not None
        self._affected_stack.append({"controller": self.state.active, "refs": []})
        try:
            if eff_type == "form":
                # 形态牌：从手牌/原区域移除并立即结附（响应插入使用同样走 _play_form_card）
                if si is None:
                    raise IllegalAction("形态牌必须有所属式神")
                if p.shikigami[si].defeated and fdp_cost is not None:
                    # 气绝形态使用（觉醒·小鹿男）：使用效果前先复活持有者，再正常结附
                    self._revive(p, self.state.active, si, reason="气绝形态使用")
                self._play_form_card(p, si, card, cdef, self.state.active, chosen)
            elif eff_type == "combat":
                # 战斗牌：以完整战斗事件流程结算（移入战斗区、战力/一次性护甲、
                # 战斗前/后时机、战斗伤害），结算完后进入墓地。
                # 爆能转化战斗牌（PlayMethod.card_type="combat"，御馔津符咒牌）
                # 同走本路径——身材取方式 power/shield 参数（combat_card_stats）
                if si is None:
                    raise IllegalAction("战斗牌必须有所属式神")
                self._resolve_combat_card(p, si, card, cdef, method, chosen)
            elif eff_type == "field":
                # 幻境牌（规范第一条）：先以所使用的牌"召唤幻境"（入队 +
                # on_summon_field），再执行幻境本身的进场效果（effects 块）。
                # 使用后卡牌本体入墓地（同法术——幻境实体独立存续，消灭时不再做
                # 卡牌移动；简化口径待维护者确认）
                self.move_card(p, card, "graveyard")
                self._summon_field(
                    self.state.active, card, cdef,
                    Ref(player=self.state.active, shikigami=si) if si is not None else None)
                ctx = ExecContext(
                    controller=self.state.active,
                    source=Ref(player=self.state.active, shikigami=si) if si is not None else None,
                    card=card,
                    chosen=chosen,
                )
                self._resolve_block(self._played_block(p, cdef, card, method), ctx)
            else:
                self.move_card(p, card, "graveyard")
                ctx = ExecContext(
                    controller=self.state.active,
                    source=Ref(player=self.state.active, shikigami=si) if si is not None else None,
                    card=card,
                    chosen=chosen,
                )
                # 法术觉醒牌使用事件流程（thoughts.txt）：移入墓地 → 觉醒前（即时）→
                # 替换式神能力 → 法术本身效果 → 觉醒后（延时）→ 永久身材增益
                awaken_si = si if (cdef.subtype == "awaken" and si is not None) else None
                if awaken_si is not None:
                    self.emit("on_before_awaken", player=self.state.active,
                              shikigami=awaken_si, uid=uid,
                              target=Ref(player=self.state.active, shikigami=awaken_si))
                    # 觉醒牌：替换当前式神能力为觉醒能力（rules.md 第十三章；气绝/复活
                    # 保留觉醒状态）；动态倒计时继承见 _register_ability_countdown(awaken=)
                    self._clear_ability_card_auras(p, self.state.active, awaken_si)  # 旧能力离场：其 ability 光环移除
                    p.shikigami[awaken_si].awakened = cdef.id
                    # 能力伪关键字换绑（觉醒替换基础能力）：移除基础式神 def 携带的
                    # 伪关键字（如 power_if_field）、授予觉醒牌 keywords 携带的（如
                    # power_per_field）——永久类别，气绝/复活随觉醒状态保留；
                    # 带冒号参数的伪关键字（replace_action:迟钝）按前缀归入本集合
                    st_aw = p.shikigami[awaken_si]
                    base_pseudo = {k for k in self.db.shikigami[st_aw.id].keywords
                                   if k.split(":", 1)[0] in ABILITY_PSEUDO_KEYWORDS}
                    if base_pseudo:
                        st_aw.perm_keywords = [k for k in st_aw.perm_keywords
                                               if k not in base_pseudo]
                    for kw in cdef.keywords:
                        if (kw.split(":", 1)[0] in ABILITY_PSEUDO_KEYWORDS
                                and kw not in st_aw.perm_keywords):
                            st_aw.perm_keywords.append(kw)
                    self._register_ability_countdown(self.state.active, awaken_si, awaken=True)
                    self._log(f"{self.db.shikigami[p.shikigami[awaken_si].id].name} 觉醒")
                    self._settle(f"【觉醒】{self.db.shikigami[p.shikigami[awaken_si].id].name} 觉醒"
                                 f"（永久 {cdef.awaken_power:+d}/{cdef.awaken_health:+d}）")
                block = self._played_block(p, cdef, card, method)
                self._resolve_block(block, ctx)
                if awaken_si is not None:
                    self.emit("on_awakened", player=self.state.active, shikigami=awaken_si,
                              uid=uid,
                              target=Ref(player=self.state.active, shikigami=awaken_si))
                    # 永久身材增益排在"觉醒后"延时监听者之后结算（同批入队）
                    self._queue_awaken_stats(awaken_si, cdef, card)
        finally:
            affected = self._affected_stack.pop()["refs"]
            card.mods.pop("burst_x", None)  # 爆能 X 快照仅本次结算有效（弹回回手不残留）
            if old_kw_add is None:
                card.mods.pop("keywords_add", None)  # 方式授予关键字仅本次使用有效
            else:
                card.mods["keywords_add"] = old_kw_add
        if si is not None:
            self._clear_play_delayed(p.shikigami[si])  # "本次使用期间"延迟能力窗口结束
        self._account_card_played(p, cdef)  # 出牌统一记账（黄金羽等按 tags 计数）
        self._apply_revive_haste(p, card)  # 实例修饰"使用后…气绝倒计时-1"（鎏金幻羽）
        self._emit_card_played(self.state.active, uid, cdef, affected,
                               play_from=play_from, play_method=method_id,
                               triggered="active", chosen=chosen,
                               pre_play_form=pre_play_form)
        if play_from == "hand":
            # 火照之路（card_aura self_damage_on_play）：命中的牌从手牌使用时
            # 其控制者受到 N 点伤害（使用效果结算完毕后）——来源为牌手自身
            # （己方伤害：彼岸花基础/觉醒"每当你受到己方伤害时"可触发）
            self_damage = sum(int(a.get("self_damage_on_play", 0))
                              for a in self._match_auras(p, cdef))
            if self_damage > 0:
                self.deal_to_player(self.state.active, self_damage,
                                    Ref(player=self.state.active))
        if play_from == "deck":
            # 彼岸归航："当你以此法使用牌时，你受到2点伤害"（来源为牌手自身，同上）
            self.deal_to_player(self.state.active, 2, Ref(player=self.state.active))
        self._rebound_check(p, card, cdef)  # 弹回：使用后回手而非入墓

    def _rebound_check(self, p: PlayerState, card: CardInstance, cdef: CardDef) -> None:
        """弹回（rebound 卡牌级关键字）：使用后回手而非入墓——效果/战斗结算完毕、
        卡牌在墓地时移回手牌（蛇行击）。回手后可再次打出：持久修饰快照按实例去重，
        不重复合并（见 _materialize）。"""
        if "rebound" in cdef.keywords and card in p.graveyard:
            self.move_card(p, card, "hand")
            self._log(f"【{cdef.name}】弹回手牌")

    @staticmethod
    def _playable_when_defeated(cdef: CardDef, card: CardInstance | None = None) -> bool:
        """气绝时可用判定：卡牌标记或实例修饰（鎏金幻羽给手牌黄金羽授予的 mods）。"""
        return bool(cdef.playable_when_defeated
                    or (card is not None and card.mods.get("playable_when_defeated")))

    def _form_death_play_cost(self, p: PlayerState, si: int, cdef: CardDef) -> int | None:
        """觉醒·小鹿男旗标（form_death_play 动作登记于 PlayerState.ext["form_death_play"]）：
        旗标持有者的形态牌在持有者气绝时可用——使用时消耗 energy 点能量并先复活持有者。
        返回该牌的气绝使用能量消耗；不适用返回 None。"""
        if cdef.card_type != "form":
            return None
        pi = self.state.players.index(p)
        fdp = p.ext.get("form_death_play")
        if fdp and fdp.get("holder") == [pi, si]:
            return int(fdp.get("energy", 3))
        return None

    def _is_transformed(self, p: PlayerState, cdef: CardDef,
                        card: CardInstance | None = None) -> bool:
        """该卡牌本局是否已"变为"（吾即正义）：持久 store 或实例修饰置位 transformed。

        持久 store（card_mods 按 cid）置位后本局该同名卡全部生效（含之后生成的）；
        实例修饰为打出装配快照（_materialize）。费用/关键字求值在装配前进行，须直读 store。
        """
        if card is not None and card.mods.get("transformed"):
            return True
        return bool(p.card_mods.get(cdef.id, {}).get("transformed"))

    def _play_condition_met(self, p: PlayerState, cdef: CardDef,
                            card: CardInstance | None = None) -> bool:
        """[条件] 使用前提（CardDef.play_condition，福满乾坤）：以条件迷你语言对控制者求值
        （事件载荷为空——dice_six_ge 等控制者 ext 算子；主动/响应/自动使用统一校验，
        CLI 可用性显示同读）。card 给出实例时：mods["quest_done"] 已置位（委托整理
        "视为达成"）则条件视为满足。"""
        if card is not None and card.mods.get("quest_done"):
            return True
        if cdef.play_condition is None:
            return True
        return self._match(cdef.play_condition, {}, self.state.players.index(p))

    def _played_block(self, p: PlayerState, cdef: CardDef, card: CardInstance,
                      method: PlayMethod | None) -> EffectBlock:
        """打出时实际结算的效果块：使用方式覆盖优先；"变为"置位后改用 alt_effects。"""
        if method is not None and method.card_type is not None:
            # 类型转化（爆能转化战斗牌，御馔津符咒）：方式 effects 整体替换基础
            # effects（缺省 None = 空块——转化后不再结算原法术效果；身材在方式的
            # power/shield 参数上，觉醒版"免疫战斗伤害"经方式 effects 的
            # battle_immunity 步由战斗牌流程提取）
            return method.effects if method.effects is not None else EffectBlock(
                when=cdef.effects.when, steps=[])
        if method is not None and method.effects is not None:
            if method.energy_cost is not None:
                # 爆能方式（不夜之火批次）：方式 effects 追加到基础 effects 之后，非覆盖
                return EffectBlock(when=cdef.effects.when, mode=cdef.effects.mode,
                                   steps=list(cdef.effects.steps) + list(method.effects.steps))
            return method.effects
        if cdef.alt_effects is not None and self._is_transformed(p, cdef, card):
            return cdef.alt_effects
        return cdef.effects

    def _account_card_played(self, p: PlayerState, cdef: CardDef) -> None:
        """出牌统一记账（按 tags 计数）：tags 含 golden_feather 时累计本局/本回合使用数
        （黄金羽/金风流羽；turn 级键己方回合开始清除，game 级不清）；tags 含 lianmo 时
        累计本局使用数（心技一体"本局每使用过一张炼磨牌"光环数值通道）；tags 含
        snowball 时累计本局使用数（流霰"本局每从手牌使用过一张'雪球'额外重复一次"——
        本记账点只覆盖手牌/响应使用，凭空自动使用不经此处，不计）。"""
        if "golden_feather" in cdef.tags:
            p.ext["feather_used_game"] = p.ext.get("feather_used_game", 0) + 1
            p.ext["feather_used_turn"] = p.ext.get("feather_used_turn", 0) + 1
        if "lianmo" in cdef.tags:
            p.ext["lianmo_used_game"] = p.ext.get("lianmo_used_game", 0) + 1
        if "snowball" in cdef.tags:
            p.ext["snowball_used_game"] = p.ext.get("snowball_used_game", 0) + 1
        if cdef.subtype == "talisman":
            # 奉祝之愿账本（裁决10）：本局御馔津使用过的符咒**类型**（数据 id），
            # 按使用顺序、去重、至多三种；爆能转化使用同样经本记账点（仍是符咒牌，
            # 裁决9）；奉祝之愿的凭空自动使用不经此处（不重复记录）
            ledger = p.ext.setdefault("talisman_ledger", [])
            if cdef.id not in ledger and len(ledger) < 3:
                ledger.append(cdef.id)

    def _emit_before_card_play(self, player: int, card: CardInstance,
                               cdef: CardDef, card_type: str) -> dict:
        """"使用前"即时时机（on_before_card_play）统一发点（定案(4)：任意方式/任意
        位置的使用均发——主动/响应/自动使用同一事件）。

        返回可变 marker（{"nullified": bool}）：监听者置位 = 本次使用被无效化
        （魔音扰心/反制），调用方跳过效果结算、牌照常离手入墓地、不发 on_card_played。
        marker 同步登记 _active_play_marker（反制钩子读取点，check_defeated）；
        嵌套使用（自动使用内再触发使用）保存/恢复外层 marker。
        """
        marker = {"nullified": False}
        prev = self._active_play_marker
        self._active_play_marker = marker
        try:
            self.emit("on_before_card_play", player=player, uid=card.uid, card=card,
                      card_type=card_type, shikigami=cdef.shikigami,
                      nullified=marker)
        finally:
            self._active_play_marker = prev
        return marker

    def _emit_card_played(self, player: int, uid: int, cdef: CardDef,
                          affected: list[Ref] | None = None, *,
                          play_from: str = "hand", play_method: str | None = None,
                          triggered: str = "active",
                          chosen: list[Ref] | None = None,
                          pre_play_form: bool = False,
                          extra: dict | None = None) -> None:
        """使用后1（延时时机 on_card_played）统一发点。

        payload 携带卡牌静态信息（card_type/subtype/shikigami/card_id——触发块条件匹配用，
        如"使用非觉醒法术后"；card_id 为数据 id，奈何桥头"同名牌"移除按此判定；golden_feather=该牌 tags 含黄金羽标记，流浪之羽/风之舞
        "每使用一张黄金羽"类触发以 {golden_feather: true} 判等）与 affected_refs：该次
        出牌效果实际伤害过的式神列表（暴风之主"对受影响的敌方式神各造成1点伤害"以
        context 目标读取）。
        使用位置/方式（rules.md:611）：play_from ∈ hand/deck/void（凭空生成）；
        play_method = 使用方式 id（无方式则为 None）；triggered ∈ active（主动）/
        response（响应）/ auto（凭空自动使用，如 recast_recorded/法术回响）。
        card_revealed：被使用的牌在使用点是否具有"已展示"（读实例 mods，本局保持、
        随实例）——条件 {card_revealed: true} 匹配"使用已展示的牌时"类触发。
        chosen：该次使用的选择目标（无目标/无选择信息为空列表）——条件
        {chosen_side: friendly} 匹配"对单个己方式神使用的法术"类触发（记仇）。
        """
        played = self._card_by_uid(uid)
        # 委托账本（三目委托机制）：使用牌数（不限主动/响应/自动，定案(3)）/形态牌/
        # 阵容套牌以外/三目使用委托牌。阵容套牌以外口径（定案(5)）：同名牌不在本局
        # 卡组（PlayerState.deck_names，构筑替换后捕获）的使用才计——衍生牌/能力给与
        # 牌（如未携带明灯时青行灯给的明灯）/中立牌同计；多择子选项使用按原牌名检测
        # （实例即原牌）；凭空自动使用的生成卡同名不在卡组同样计。
        self._quest_tick(player, "play")
        if cdef.card_type == "form":
            self._quest_tick(player, "form_play")
        if cdef.name not in self.state.players[player].deck_names:
            self._quest_tick(player, "offdeck_play")
        if cdef.subtype == "quest":
            self._quest_tick(player, "quest_used", shareable=False)
        self.emit("on_card_played", player=player, uid=uid, card_type=cdef.card_type,
                  subtype=cdef.subtype, shikigami=cdef.shikigami, card_id=cdef.id,
                  pre_play_form=pre_play_form,
                  golden_feather=("golden_feather" in cdef.tags),
                  play_from=play_from, play_method=play_method, triggered=triggered,
                  card_revealed=bool(played is not None and played.mods.get("revealed")),
                  affected_refs=list(affected or ()), chosen=list(chosen or ()),
                  **(extra or {}))

    def _queue_awaken_stats(self, si: int, cdef: CardDef, card: CardInstance) -> None:
        """觉醒牌的永久身材增益（awaken_power/awaken_health）：法术觉醒使用事件流程
        末尾，排在"觉醒后"（on_awakened，延时时机）监听者之后入队结算。"""
        steps: list[Step] = []
        if cdef.awaken_power:
            steps.append(Step(op="buff_power", amount=cdef.awaken_power, perm=True,
                              target=TargetSpec(kind="self")))
        if cdef.awaken_health:
            steps.append(Step(op="buff_health", amount=cdef.awaken_health, perm=True,
                              target=TargetSpec(kind="self")))
        if not steps:
            return
        self.queue.append(_Pending(EffectBlock(steps=steps), ExecContext(
            controller=self.state.active,
            source=Ref(player=self.state.active, shikigami=si), card=card)))

    @staticmethod
    def _clear_play_delayed(s: ShikigamiState) -> None:
        """清除 scope="play"（"本次使用期间"）的延迟能力：窗口随该次出牌结算结束
        （黑羽之刃的消灭抽牌——未消灭不遗留到后续出牌/战斗）。"""
        s.delayed[:] = [e for e in s.delayed if e.get("scope") != "play"]

    def combat_card_stats(self, block: EffectBlock,
                          card: CardInstance | None = None,
                          s: ShikigamiState | None = None,
                          p: PlayerState | None = None,
                          method: PlayMethod | None = None) -> tuple[int, int]:
        """从战斗牌的效果块中提取战力与一次性护甲数值（仅统计目标为 self 的 buff_power / gain_shield）。

        公开方法：引擎内部结算与客户端展示（client/cli.py 手牌数值段）共用。

        amount 支持 {"enhance": true, "base": n} 形式（禁锢之刀/冲撞）：base + 实例已装配的
        enhance 修饰（打出装配快照，见 _materialize）；以及 {"shield_of": "self"}（尘刀：
        按打出瞬间护甲快照战力，本次战斗中不变）；{"enemy_stunned_count": true}（霜天之织：
        场上眩晕的敌方角色数，活局面量——p 给出时与光环数值同通道求值）。
        p 给出时叠加命中该牌的卡牌光环数值通道（card_aura 的 power/shield，可叠加）。
        method 给出时叠加方式身材参数（PlayMethod.power/shield——爆能转化战斗牌，
        御馔津符咒牌[爆能3]各卡身材）。
        """
        power = 0
        shield = 0
        if method is not None:
            power += int(method.power)
            shield += int(method.shield)
        controller = (self.state.players.index(p) if p is not None else None)
        for step in block.steps:
            if step.target is not None and step.target.kind != "self":
                continue
            if step.op == "buff_power" and (step.model_extra or {}).get("perm"):
                continue  # 永久力量增益（怪力）是常规效果步，非本次战斗战力
            if (step.model_extra or {}).get("no_extract"):
                continue  # 标记不提取的步骤按常规效果步顺序结算（醉酒当歌"先自伤再获盾"）
            amount = self._step_amount(step, card, s, game=self, controller=controller)
            if step.op == "buff_power":
                power += amount
            elif step.op == "gain_shield":
                shield += amount
        if p is not None and card is not None:
            cdef = self.db.cards[card.id]
            for aura in self._match_auras(p, cdef):
                power += int(aura.get("power", 0))
                shield += int(aura.get("shield", 0))
                # ext 数值通道（心技一体"本局每使用过一张炼磨牌+1/+1"）：读取时从
                # PlayerState.ext 解析计数（出牌记账见 _account_card_played）
                if aura.get("power_ext"):
                    power += int(p.ext.get(aura["power_ext"], 0))
                if aura.get("shield_ext"):
                    shield += int(p.ext.get(aura["shield_ext"], 0))
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
            self._settle(f"【战力】{self.db.shikigami[s.id].name} 战力 +{power}（本次战斗）")
            if battle_scoped and self._battle_stack:
                self._battle_power.setdefault(self._battle_stack[-1], []).append((ref, power))
        if shield:
            self._change_shield(ref, shield, "combat_card")

    def _resolve_combat_card(self, p: PlayerState, si: int, card: CardInstance,
                             cdef: CardDef, method: PlayMethod | None,
                             chosen: list[Ref] | None = None) -> None:
        """战斗牌完整事件流程：获得战力/护甲、牌移至墓地、战斗（移入战斗区、战斗前、战斗伤害、战斗后）。

        战斗牌提供的力量（战力）在战斗后清除；提供的护甲/破甲会保留，并按即时时机
        发出 on_shield_changed 事件。追猎战斗牌以选择目标为战斗目标（有目标的非出击战斗；
        必须选择一名合法敌方式神——无合法目标时该牌不能使用）。
        """
        s = p.shikigami[si]
        defeated_entry = not s.in_play
        if defeated_entry and not (s.defeated and self._playable_when_defeated(cdef, card)):
            raise IllegalAction("该式神未在场，无法使用战斗牌")
        # 气绝时可用的战斗牌（不玩了啦"气绝时可用，复活跳跳妹妹"，定案(14)）：
        # 气绝中不获得战力/护甲——先结算卡面效果，结算完未气绝则补齐战力/护甲并
        # 正常发起战斗；仍未气绝则牌入墓地、不发起战斗（不崩守卫）
        tgt = method.target if (method and method.target is not None) else cdef.target
        hunt_target: Ref | None = None
        if "hunt" in cdef.keywords:
            if not chosen:
                raise IllegalAction("追猎战斗牌需要选择一名敌方式神为目标")
            hunt_target = chosen[0]
        elif chosen and (tgt.model_extra or {}).get("battle"):
            # 指定战斗目标的非追猎战斗牌（target/方式 target 扩展键 battle=true；
            # 天翔鹤斩"改为攻击一个敌方准备区式神"、御馔津符咒爆能转化"改为攻击
            # 任一敌方式神"——同追猎的有目标战斗管线，帷幕不可选）
            hunt_target = chosen[0]
        block = self._played_block(p, cdef, card, method)
        power, shield = self.combat_card_stats(block, card, s, p=p, method=method)
        atk_ref = Ref(player=self.state.players.index(p), shikigami=si)
        if not defeated_entry:
            self._apply_combat_stats(atk_ref, s, power, shield, battle_scoped=False)
        # 战斗牌授予的关键字（fast/trigger 为卡牌级，不授予）与作用域战斗伤害免疫，
        # 均绑定本次战斗上下文，终止点移除（rules.md:338"直到本次战斗结束后"）；
        # 效果块中的 grant_keyword step = 战斗作用域条件授予（致命诱惑"若攻击有破甲的
        # 角色，获得吸血"），battle_immunity step 可带 Step.condition（鸩羽的条件免疫），
        # convert_damage step = 毒蚀伤害→破甲转化、counter_piercing step = 反击贯通、
        # double_damage_vs_fragile step = 义道破甲双倍——五者在此提取，不再按普通 step 执行
        grants = tuple((k, None) for k in cdef.keywords if k not in CARD_LEVEL_KEYWORDS)
        grants += tuple(((st.model_extra or {}).get("keyword"), st.condition)
                        for st in block.steps if st.op == "grant_keyword")
        imms = tuple((bool((st.model_extra or {}).get("nested", False)), st.condition,
                      (st.model_extra or {}).get("kind", "combat_damage"))
                     for st in block.steps if st.op == "battle_immunity")
        strikes = next((int((st.model_extra or {}).get("times", 2))
                        for st in block.steps if st.op == "multi_strike"), 1)
        convert = any(st.op == "convert_damage" for st in block.steps)
        counter_piercing = any(st.op == "counter_piercing" for st in block.steps)
        double_fragile = any(st.op == "double_damage_vs_fragile" for st in block.steps)
        # 其它效果步（千羽风之舞的"生成金风流羽"为首个）：战力/护甲与上述专用提取步
        # 跳过不重复执行；attack_buff（起弓/离）挂账时机另有一套，同样跳过以保持既有行为
        ctx = ExecContext(controller=self.state.players.index(p), source=atk_ref,
                          card=card, chosen=list(chosen or []))  # 效果步可读选择目标
        # （麓鸣·轰"选择一个己方式神，本次攻击后…"的 delay_grant bind=chosen 通道）
        for st in block.steps:
            if (st.op in ("buff_power", "gain_shield")
                    and (st.target is None or st.target.kind == "self")
                    and not (st.model_extra or {}).get("no_extract")
                    and not (st.op == "buff_power" and (st.model_extra or {}).get("perm"))):
                continue  # 战力/护甲已提取（永久力量增益与 no_extract 标记步属常规效果步，不提取）
            if st.op in ("grant_keyword", "battle_immunity", "convert_damage",
                         "counter_piercing", "double_damage_vs_fragile", "attack_buff",
                         "multi_strike"):
                continue  # 战斗流程专用步：已提取绑定战斗上下文 / 既有挂账路径
            self._run_step(st, ctx)
        # rules.md:344：战斗牌先移至墓地，再发起战斗（战斗中的墓地计数等效果可见此牌）
        self.move_card(p, card, "graveyard")
        if defeated_entry:
            if not s.in_play:
                # 不玩了啦守卫：卡面效果结算完仍未复活——不发起战斗，正常收场
                self._log(f"【{cdef.name}】结算完毕，{self.db.shikigami[s.id].name}"
                          f"仍未复活，不发起战斗")
                return
            # 复活后：战力/护甲按正常战斗牌补齐，随后正常发起战斗（定案(14)）
            self._apply_combat_stats(atk_ref, s, power, shield, battle_scoped=False)
        # 战斗牌消耗鼓舞（boost_on_combat_card 旗标，觉醒·不知火类）：正常战斗牌不消耗
        if any(f.get("kind") == "combat_card" for f in p.ext.get("boost_flags", [])):
            self._consume_assault_boosts(p, atk_ref, s)
        rep_inv = self._replace_action_invocation(s)
        if rep_inv is not None:
            # 跳跳哥哥"使用战斗牌时改为结附'迟钝'"：卡面战力/护甲与其余文本效果
            # （steps）照常结算（上方已完成），仅战斗本身替换为对自身结附灵咒
            self._log(f"{self.db.shikigami[s.id].name} 使用【{cdef.name}】改为"
                      f"结附灵咒【{rep_inv}】")
            self._settle(f"【替换】{self.db.shikigami[s.id].name} 的战斗牌改为结附"
                         f"灵咒【{rep_inv}】")
            self.attach_invocation(rep_inv, player=self.state.players.index(p),
                                   source=atk_ref, target=atk_ref)
            s.combat_power = 0
            return
        self._resolve_combat(atk_ref, s, grant_keywords=grants, immunities=imms,
                             temp_grants=tuple(cdef.temp_grants), convert=convert,
                             counter_piercing=counter_piercing, double_fragile=double_fragile,
                             target=hunt_target, origin="card", strikes=strikes)
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
        power, shield = self.combat_card_stats(block, card, s, p=p)
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
                    battle=self._battle_stack[-1],
                    uses=int((blk.model_extra or {}).get("uses", 1)),  # 同 _resolve_combat
                    seq=self.state.next_ability_seq()))
        # 其余 steps（battle_immunity 等）照常执行——登记到当前战斗上下文
        ctx = ExecContext(controller=pi, source=ref, card=card)
        for step in block.steps:
            if (step.op in ("buff_power", "gain_shield")
                    and (step.target is None or step.target.kind == "self")
                    and not (step.model_extra or {}).get("no_extract")
                    and not (step.op == "buff_power" and (step.model_extra or {}).get("perm"))):
                continue  # 战力/护甲已提取，不重复执行（永久力量增益与 no_extract 标记步照常执行）
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
        return targets.spec_pool_refs(self, cdef.target, player_index, targeted=True)

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

    def move_card(self, p: PlayerState, card: CardInstance, to_zone: str,
                  *, from_zone: str | None = None, reason: str | None = None,
                  invocation_horizon: int = 0) -> None:
        """把卡牌移动到指定区域；区域不存在则创建（区域系统保留扩展空间）。

        牌移动事件流程（docs/rules.md「牌移动事件流程」）：
        移出原区域 → 置入目标区域（入手分配 hand_seq）→ 非爆牌发 on_card_enter_hand
        → 动态身材光环刷新 → on_card_move（即时时机）→ on_card_moved（延时时机，
        灵咒挂点）→ 入手灵咒处理（_proc_invocations_on_move；灵咒触发位于移动事件
        内部的延时时机——invocation_horizon 非 0 时触发块记为该挂起单元、随单元
        drain 在移动完成后结算，抽牌倒序用）→ 手牌上限检查：
        超出则该牌转而置入墓地（爆牌——上限检查在"牌移动后"时机之后，定案；
        抽牌与生成置入手牌共用本条路径，爆牌不视为进入手牌）。
        from_zone 可显式指定原区域名（缺省取 _remove_from_zone 的实检结果；
        card 不在任何已知区域——如测试直接注入——则为 None）。
        reason 入手路径约定：draw（抽牌）/ generate（生成）/ search（检索）/
        pick（检视入手）/ hand_cap（爆牌转墓地）；None = 其余（回手/弹回等）。
        """
        removed = self._remove_from_zone(p, card)
        src_zone = from_zone if from_zone is not None else removed
        if (src_zone == "deck" and to_zone not in ("deck", "hand")
                and card.invocations):
            # 牌级灵咒离库清除（梦魇）：移出牌库且非入手（入手走 _proc_invocations_on_move
            # 触发/移除通道）时静默移除——回库/洗牌保留
            card.invocations = []
            self._log(f"【{self.db.cards[card.id].name}】上结附的灵咒移除（离开牌库）")
        if to_zone == "hand":
            self._assign_hand_seq(p, card)
        p.zones.setdefault(to_zone, []).append(card)
        pi = self.state.players.index(p)
        burst = False
        if to_zone == "hand":
            cap = self.cfg(pi, "hand_cap")
            burst = cap is not None and len(p.zones["hand"]) > cap
            if not burst:
                self._enter_hand(p, card)  # 入手统一钩子（爆牌转墓地不视为进入手牌）
        self._refresh_stat_auras()  # 手牌数变化影响动态身材光环（闻世）
        payload = dict(player=pi, uid=card.uid, card=card,
                       from_zone=src_zone, to_zone=to_zone, reason=reason)
        self.emit("on_card_move", **payload)    # 牌移动后（即时时机）
        self.emit("on_card_moved", **payload)   # 牌移动后（延时时机；灵咒挂点）
        if to_zone == "hand":
            self._proc_invocations_on_move(p, card, reason, payload,
                                           horizon=invocation_horizon)
        if burst:
            self._log(f"{p.name} 的手牌已达上限（{cap}），"
                      f"【{self.db.cards[card.id].name}】置入墓地（爆牌）")
            self.move_card(p, card, "graveyard", reason="hand_cap")

    def _proc_invocations_on_move(self, p: PlayerState, card: CardInstance,
                                  reason: str | None, payload: dict,
                                  *, horizon: int = 0) -> None:
        """入手灵咒处理（灵咒框架，docs/rules.md「灵咒」）：结附在牌上的灵咒
        在该牌入手时移除——抽牌动作入手（reason="draw"，deck→hand）时其"抽到触发"
        块先入队再移除；检索/生成/回手等其余入手路径静默移除（不触发）。
        灵咒触发位于**牌移动事件内部的延时时机**（移动完成后执行）：horizon 非 0
        时触发块记为该挂起单元（抽牌事件单元——倒序定案：内层单元的移动+灵咒
        先于外层结算），随单元 drain 结算；否则入普通队列（控制者 = 灵咒来源所属
        牌手）。爆牌：先发 deck→hand（reason="draw"）移动事件故触发并移除，
        再经 hand_cap 递归转墓地。"""
        if not card.invocations:
            return
        invs, card.invocations = card.invocations, []
        if reason != "draw" or payload.get("from_zone") != "deck":
            self._log(f"【{self.db.cards[card.id].name}】上结附的灵咒移除（入手）")
            return
        for inv in invs:
            idef = self.db.invocations.get(inv["name"])
            if idef is None or idef.draw_trigger is None:
                continue
            self._log(f"【{self.db.cards[card.id].name}】上结附的灵咒"
                      f"【{idef.name}】触发（抽到）")
            # 惊梦账本：抽牌者本回合抽到过结附该灵咒的牌（enemy_drew_invocation 读取）
            pi = self.state.players.index(p)
            ledger = self.state.players[pi].ext.setdefault("drew_invocation_turn", [])
            ledger.append(inv["name"])
            self.emit("on_invocation_drawn", player=pi, card=card,
                      invocation=inv["name"], source_player=inv["player"])
            self.queue.append(_Pending(idef.draw_trigger, ExecContext(
                controller=inv["player"], card=card, event=payload,
                is_ability=True, ability_uid=f"inv:{card.uid}:{inv['name']}"),
                horizon=horizon))

    # ---------- 灵咒（灵咒框架，docs/rules.md「灵咒」；沧海刀鸣预备） ----------

    def attach_invocation(self, name: str, *, player: int, source: Ref | None = None,
                          target: Ref | None = None,
                          card: CardInstance | None = None,
                          grant_keywords: tuple = (), count: int = 1,
                          _no_override: bool = False) -> None:
        """结附灵咒：target 为式神结附 / card 为卡牌结附（二者恰一）。
        player = 来源所属牌手（同源判定键）。流程：结附（效果类身材增减益快照入
        条目 power/health——类光环层，由 eff_power/max_health 读取时合计；
        能力类记进场序号；keywords 授予持有者；倒计时块注册式神级倒计时）→
        唯一性移除（新结附自身保留；同源同名旧条目的 bonus 由新条目继承）→
        inv_mod 修饰层重算 → emit on_invocation_attached（延时时机，uid=条目 uid）。

        grant_keywords：本次结附对该条目追加的关键字（无尽剑狱"并于结附期间使其
        持续[眩晕]"——stun 走灵咒眩晕条目通道：不参与回合批次过期、移除即解；
        数据侧经 attach_invocation op 的 grant_keywords 参数传入）。
        count：一次结附动作的条目数（增殖/魔蛊毒爆"结附两个/三个"）；逐条创建、
        逐条发结附事件。来源牌手 ext["inv_attach_bonus"] 条目（觉醒·巫蛊师
        "当结附'蛊蚀'时，数量额外+1"——仅'结附'动作触发，裁决13）对每次结附
        动作整体追加（结附 2 → +1 = 3）。
        结附后致死检查（裁决12）：持有者生命上限（含 inv_mod 修饰层）不大于 0
        即气绝，上限降低同步钳当前生命——见 _invocation_lethality。
        覆写通道（持有方牌手 ext["inv_override"][灵咒名]，祈愿之翼）：
        attach_all_friendly=true 时改为己方全体在场式神结附（递归结附不再读覆写）。
        """
        idef = self.db.invocations.get(name)
        if idef is None:
            raise ValueError(f"未定义的灵咒: {name}（db.invocations 注册）")
        if target is not None and not _no_override:
            ov = self.state.players[target.player].ext.get(
                "inv_override", {}).get(name) or {}
            if ov.get("attach_all_friendly"):
                for si, fs in enumerate(self.state.players[target.player].shikigami):
                    if fs.in_play:
                        self.attach_invocation(
                            name, player=player, source=source,
                            target=Ref(player=target.player, shikigami=si),
                            _no_override=True)
                return
        count = max(1, int(count))
        bonus = sum(int(b.get("add", 0))
                    for b in self.state.players[player].ext.get("inv_attach_bonus") or []
                    if b.get("name") == name)
        if bonus:
            # 觉醒·巫蛊师型增幅：按来源牌手判定（巫蛊师方的结附才+1）
            self._log(f"灵咒【{name}】结附数量 +{bonus}（结附增幅）")
            count += bonus
        for _ in range(count):
            entry: dict = {"name": name, "player": player, "source": source,
                           "uid": self.state.next_uid, "bonus": 0,
                           "power": idef.power, "health": idef.health}
            self.state.next_uid += 1
            if target is not None:
                s = self.state.players[target.player].shikigami[target.shikigami]
                entry["ability_seq"] = self.state.next_ability_seq()  # 能力类进场序号=结附时刻
                s.invocations.append(entry)
                holder = f"{self.db.shikigami[s.id].name}"
                # keywords：结附期间授予持有者（移除时按实例撤销）；"stun" 特判为眩晕条目
                # （kind="invocation"，不参与回合批次过期清理——_stun_expired 特判）
                granted: list[tuple[str, str]] = []
                for kw in tuple(idef.keywords) + tuple(grant_keywords):
                    if kw == "stun":
                        s.stuns.append({"kind": "invocation", "inv": name})
                        self._log(f"{holder} 被眩晕（灵咒【{name}】）")
                    else:
                        granted.append((kw, self._grant_keyword(s, kw)))
                if granted:
                    entry["keywords"] = granted
                # 倒计时能力块（迟钝类）：注册式神级倒计时；once 块归零生效后随
                # _countdown_zero 的 once 通道移除灵咒本体。注意会替换式神当前倒计时
                # （一名式神至多 1 个——与原版互动的语义待数据批次确认）
                cd = next((b for b in idef.abilities if b.countdown is not None), None)
                if cd is not None:
                    self._register_countdown(s, initial=cd.countdown, block=cd,
                                             once=cd.once, source=None)
                    entry["cd_block"] = cd
            else:
                assert card is not None
                card.invocations.append(entry)
                holder = f"【{self.db.cards[card.id].name}】"
            self._log(f"灵咒【{name}】结附于{holder}")
            self._apply_invocation_uniqueness(idef, entry, player, target)
            if target is not None:
                self._refresh_invocation_mods(target.player)
            self.emit("on_invocation_attached", player=player, target=target,
                      uid=entry["uid"],
                      invocation=name, source=source)
        if target is not None:
            self._invocation_lethality(target)

    def _invocation_lethality(self, target: Ref) -> None:
        """灵咒致死检查（裁决12，蛊蚀"每当结附蛊蚀时都会检查被结附式神是否生命上限
        不大于 0 并气绝"）：上限降低先钳当前生命（同 _remove_invocation 口径，
        不触发事件），上限（含 inv_mod 修饰层）不大于 0 即气绝。"""
        s = self.state.players[target.player].shikigami[target.shikigami]
        if s.defeated or s.despawned or not s.in_play:
            return
        if s.health > s.max_health:
            s.health = s.max_health  # 上限降低：钳当前生命
        if s.max_health <= 0:
            self._log(f"{self.db.shikigami[s.id].name} 生命上限不大于 0，气绝（灵咒）")
            self.check_defeated(target, reason="灵咒")

    def _apply_invocation_uniqueness(self, idef, new_entry: dict, player: int,
                                     target: Ref | None) -> None:
        """唯一性移除（结附之后；新结附自身按对象身份排除）：
        [唯一]（unique）= 双方全场（全部式神 + 双方手牌/牌库中的卡牌）同源同名移除；
        [式神唯一]（shikigami_unique）= 仅该式神上同源同名移除。同源 = 来源所属牌手相同。
        持有方牌手 ext["inv_override"][灵咒名]["unique"] 可覆写唯一性级别（祈愿之翼
        "失去[唯一]但效果不能叠加"）；移除旧条目前新条目继承其 bonus（取较大者，
        "效果+1"数值增强不因再结附丢失；气绝/离场移除才重置）。"""
        unique = idef.unique
        if target is not None:
            ov = self.state.players[target.player].ext.get(
                "inv_override", {}).get(idef.name) or {}
            unique = ov.get("unique", unique)
        if unique == "none":
            return

        def _hit(e: dict) -> bool:
            if e is new_entry or e["name"] != idef.name or e["player"] != player:
                return False
            # 同源同名旧条目的数值增强由新条目继承
            new_entry["bonus"] = max(int(new_entry.get("bonus", 0)),
                                     int(e.get("bonus", 0)))
            return True

        if unique == "shikigami_unique":
            if target is None:
                return  # 卡牌结附无"该式神"可言（式神唯一只对式神结附生效）
            s = self.state.players[target.player].shikigami[target.shikigami]
            for e in list(s.invocations):
                if _hit(e):
                    self._remove_invocation(s, e, reason="式神唯一")
            return
        for pl in self.state.players:
            for s in pl.shikigami:
                for e in list(s.invocations):
                    if _hit(e):
                        self._remove_invocation(s, e, reason="唯一")
            for zname in ("hand", "deck"):
                for c in pl.zones.get(zname, []):
                    for e in list(c.invocations):
                        if _hit(e):
                            c.invocations.remove(e)
                            self._log(f"【{self.db.cards[c.id].name}】上结附的灵咒"
                                      f"【{idef.name}】移除（唯一）")

    def _remove_invocation(self, s: ShikigamiState, entry: dict, *, reason: str) -> None:
        """移除式神身上的灵咒条目：身材增减益为类光环层（条目移除即失效，
        无双重扣减）；上限降低时钳当前生命（同 buff_health/dyn 通道口径，
        不触发事件）。能力类随条目移除失效；结附授予的关键字按实例撤销、
        灵咒眩晕条目（kind="invocation"）随之解除；灵咒倒计时块仍注册在式神上时
        一并清除。"""
        s.invocations.remove(entry)
        for kw, cls in entry.get("keywords") or []:
            self._remove_keyword(s, kw, cls)
        kept = [e for e in s.stuns
                if not (e.get("kind") == "invocation" and e.get("inv") == entry["name"])]
        if len(kept) != len(s.stuns):
            s.stuns[:] = kept
            self._log(f"{self.db.shikigami[s.id].name} 的眩晕解除（灵咒移除）")
        if entry.get("cd_block") is not None and s.countdown_block is entry["cd_block"]:
            self._clear_countdown(s)
        if s.health > s.max_health:
            s.health = s.max_health  # 灵咒生命上限增益随移除失效：钳当前生命
        self._log(f"{self.db.shikigami[s.id].name} 的灵咒【{entry['name']}】移除（{reason}）")

    def _refresh_invocation_mods(self, pi: int) -> None:
        """重算 pi 方全部式神灵咒条目的 inv_mod 修饰层（mod_power/mod_health）。

        数据源 = 该方牌手 ext["inv_mod"] 条目列表：{"name": 灵咒名,
        "shikigami": 持有者式神数据 id（可省 = 不限持有者）, "add": int, "mult": int}；
        命中多条时 mult 连乘、add 连加，eff = base*mult + add，条目存
        mod = eff - base（base = 快照 power/health + bonus）。只看持有者方、不限灵咒
        来源敌我（八尺琼曲玉"结附的式神获得1力量"经持有方修饰——大岳丸能力用）。
        调用时机：灵咒结附后（attach_invocation 末）；能力进场/离场/觉醒换绑等
        inv_mod 维护点由数据批次接线后调用本方法。
        """
        mods = self.state.players[pi].ext.get("inv_mod") or []
        for s in self.state.players[pi].shikigami:
            for e in s.invocations:
                add, mult = 0, 1
                for m in mods:
                    if m.get("name") != e["name"]:
                        continue
                    if m.get("shikigami") is not None and m["shikigami"] != s.id:
                        continue
                    add += int(m.get("add", 0))
                    mult *= int(m.get("mult", 1))
                for stat, mod_key in (("power", "mod_power"), ("health", "mod_health")):
                    base = int(e.get(stat, 0)) + int(e.get("bonus", 0))
                    e[mod_key] = base * mult + add - base

    def _detach_invocations(self, s: ShikigamiState, *, reason: str) -> None:
        """气绝/离场时移除该式神全部灵咒（身材增减益为光环层随之失效；
        能力类随列表清空而失效）。"""
        for e in list(s.invocations):
            self._remove_invocation(s, e, reason=reason)

    def _enter_hand(self, p: PlayerState, card: CardInstance) -> None:
        """牌进入手牌的统一钩子（"已展示"机制）：抽牌（draw_cards）/生成
        （generate）/检索（search_deck）/检视入手（deck_top_pick）/调度换入
        （_swap_hand_card）等一切入手路径经此单点发点（延时时机，不分回合），
        供觉醒·觉"每当一张牌进入敌方手牌时将其展示"类被动挂载（含生成牌）。"""
        self.emit("on_card_enter_hand", player=self.state.players.index(p),
                  uid=card.uid, card=card)

    def _card_by_uid(self, uid: int) -> CardInstance | None:
        """按 uid 找局内卡牌实例（双方全区域 + 结附中的形态牌；找不到返回 None）。"""
        for pl in self.state.players:
            for z in pl.zones.values():
                for c in z:
                    if c.uid == uid:
                        return c
            for s in pl.shikigami:
                if s.form is not None and s.form.uid == uid:
                    return s.form
        return None

    def _change_shield(self, ref: Ref, delta: int, reason: str, kind: str = "shield") -> None:
        """目标（式神或牌手）护甲/破甲变化（docs/rules.md 第六章），并发出 on_shield_changed。

        shield 为有符号字段（>0 护甲 / <0 破甲）；delta 以 kind 方向的正数计量
        （kind="shield" 护甲 / kind="fragile" 破甲，± = 获得/失去，四组合）。
        - 变化量为 0：终止结算（流程 1）；
        - 减少（delta < 0）：只能扣已有的同向值，不能减到反向（流程 4）；
        - 获得（delta > 0）：先抵消反向值再盈余同向（流程 5；
          获得 5 护甲且持有 3 破甲 → 2 护甲）。
        事件 payload 带 kind 区分方向（"获得护甲"与"失去破甲"属不同事件）。
        获得量受欢愉之音型光环增益（shield_gain_boost 形态标记：己方获得护甲 +1 /
        敌方获得破甲 +1，见流程 5 内注释）。
        """
        if delta == 0:
            return  # 流程 1：变化量为 0 终止
        p = self.state.players[ref.player]
        holder = p.shikigami[ref.shikigami] if ref.shikigami is not None else p
        old = holder.shield
        if delta < 0:
            # 流程 4：减少（失去护甲/破甲）——只能减少已有的同向值（不持有该方向则终止；
            # 扣至 0 为止，不能减到反向）
            if kind == "shield" and old <= 0:
                return
            if kind == "fragile" and old >= 0:
                return
            new = max(0, old + delta) if kind == "shield" else min(0, old - delta)
        else:
            # 流程 5：获得——先抵消反向值再盈余同向（获得 5 护甲且持有 3 破甲 → 2 护甲）
            if kind == "fragile":
                # 碧羽散华锚点（"获得破甲前"转化）：持有 fragile_to_damage 标记的角色
                # 获得破甲改为受到等量伤害（标记经 ext 授予；converted=True 防止与
                # 毒蚀的伤害→破甲转化来回循环——转化类效果对同一事件链只生效一次）。
                # 维护者答复(1)：无论式神/牌手——victim 侧标记挂在敌方式神上，牌手
                # 沿用"其任一式神持标记"语义（当前卡池仅鸩给予破甲，两者等价）
                if ref.shikigami is not None:
                    s = p.shikigami[ref.shikigami]
                    # fragile_to_damage_if：20191212 版碧羽散华——仅当受害者本已有
                    # 破甲（shield < 0）时才转化（"对有破甲的角色"）
                    if s.ext.get("fragile_to_damage") or (
                            s.ext.get("fragile_to_damage_if") and old < 0):
                        self._log(f"{self.db.shikigami[s.id].name} 的破甲转化为 {delta} 点伤害")
                        self.deal_to_shikigami(ref, delta, None, converted=True)
                        return
                elif (any(st.ext.get("fragile_to_damage") for st in p.shikigami)
                        or (old < 0 and any(st.ext.get("fragile_to_damage_if")
                                            for st in p.shikigami))):
                    self._log(f"{p.name} 的破甲转化为 {delta} 点伤害")
                    self.deal_to_player(ref.player, delta, None, converted=True)
                    return
            # 欢愉之音型光环（"获得护甲/破甲前2"，维护者定案）：在场形态 tags 含
            # shield_gain_boost 时——其控制者方角色获得护甲 +1；其敌方角色获得破甲 +1
            # （获得量增益，先于"抵消反向值"计算；回合开始清除不走本函数，不受影响）
            if kind == "shield":
                if self._field_form_has_tag(ref.player, "shield_gain_boost"):
                    delta += 1
            elif self._field_form_has_tag(1 - ref.player, "shield_gain_boost"):
                delta += 1
            new = old + delta if kind == "shield" else old - delta
        holder.shield = new
        label = "护甲" if kind == "shield" else "破甲"
        verb = "获得" if delta > 0 else "失去"
        name = (self.db.shikigami[holder.id].name if ref.shikigami is not None
                else p.name)
        self._settle(f"【{label}】{name} {verb} {abs(delta)} 点{label}"
                     f"（{old}→{new}，{reason}）")
        self.emit("on_shield_changed", target=ref, old=old, new=new, reason=reason, kind=kind,
                  amount=delta, gained=delta > 0)

    # ---------- 出击 / 移动 ----------

    def _resolve_combat(self, atk_ref: Ref, attacker: ShikigamiState, *,
                        move: bool = True,
                        grant_keywords: tuple = (),
                        immunities: tuple = (),
                        temp_grants: tuple[EffectBlock, ...] = (),
                        convert: bool = False,
                        counter_piercing: bool = False,
                        double_fragile: bool = False,
                        target: Ref | None = None,
                        origin: str = "effect",
                        strikes: int = 1,
                        ignore_veil: bool = False) -> None:
        """通用战斗流程（docs/rules.md 第四章）。复用于出击指令与战斗牌。

        战斗上下文：压栈新 battle id。grant_keywords 为战斗牌等授予攻击者的关键字实例
        （终止点按实例移除，不误删式神原有同名关键字），元素为 (keyword, condition)——
        condition 以 {"defender": 被攻击者} 在战斗开始时求值（"若攻击有破甲的角色"，
        致命诱惑）；immunities 为作用域战斗伤害免疫，元素为 (nested, condition, kind)——
        kind 缺省 "combat_damage"（鸩羽的条件免疫），"all" 为免疫所有伤害（二帚流）；
        nested = 是否覆盖本战斗内的嵌套战斗）；temp_grants 为战斗牌携带的
        一次性临时触发（绑定本战斗 id 注册，终止点移除未用者，如不祥之刃的击杀抽牌）；
        convert = 毒蚀：本战斗中双方造成的伤害转化为等量破甲（终止点清除标记）；
        counter_piercing = 反击贯通：本战斗中被攻击方的反击伤害具有贯通（终止点清除标记）。
        double_fragile = 义道：仅此战斗中攻击者本人对有破甲的式神造成的战斗伤害翻倍
        （[暴击]时机=扣减生命前2；反击/嵌套/插入战斗不翻倍；终止点清除标记）。
        target = 有目标的战斗的战斗目标（追猎；None = 无目标战斗，被攻击者按敌方战斗区/直击
        决定）；origin = 发起方式（"assault" 出击 / "card" 战斗牌 / "effect" 效果发起）——
        帷幕再校验时出击取消战斗、其余改为无目标战斗（thoughts.txt 帷幕定义）；
        "assault"/"card" 两种攻击发起记入薰攻击账本（player ext["last_attacker"]，
        效果发起的攻击不算）。
        ignore_veil = 目标帷幕再校验放行（定案(4)：灵咒效果发起的战斗不受帷幕限制，
        友切"对使用法术牌的敌方式神发起战斗"——帷幕只挡出击/卡牌的指定）。
        strikes = 多段攻击次数（multi_strike 提取步，二帚流）：交战阶段后追加 strikes-1
        段攻击（反击只一段、与首段并行；2-N 段依次单独结算，终止点清除登记）。
        """
        if origin in ("assault", "card"):
            # 薰攻击账本：攻击（出击/战斗牌）发起时记账，己方回合结束由能力读取
            self.state.players[atk_ref.player].ext["last_attacker"] = atk_ref.shikigami
        self._battle_seq += 1
        bid = self._battle_seq
        self._battle_stack.append(bid)
        self._settle(f"—— 战斗开始：{self.db.shikigami[attacker.id].name} ——")
        grants: list[tuple[Ref, str, str]] = []
        self._battle_grants[bid] = grants
        self._battle_power[bid] = []  # 响应战斗牌插入使用授予的战力（终止点核销）
        self._battle_followups[bid] = []  # 战斗结束后的追加攻击登记（战斗结束后结算）
        if strikes > 1:
            self._battle_strikes[bid] = strikes  # 多段攻击登记（交战阶段后追加段数读取）
        # 倒计时能力等"本次战斗"类战斗外授予（grant_keyword/grant_immunity scope="next_battle"）：
        # 挂账在攻击者 ext，下一次作为攻击者的战斗开始时消费——关键字走终止点核销通道、
        # 免疫条目绑定本战斗 id（斩"本次攻击获得[必杀]"/觉醒·山风"本次战斗免疫战斗伤害"）。
        # 两者范围一致（维护者改判）：持续到该次战斗事件结束后，含期间插入的嵌套战斗
        # （关键字实例在外层战斗终止点核销；免疫 nested 缺省 True，挂账可显式
        # nested: false 收窄为仅本战斗）。
        for e in attacker.ext.pop("next_battle_keywords", []):
            cls = self._grant_keyword(attacker, e["keyword"])
            grants.append((atk_ref, e["keyword"], cls))
        for e in attacker.ext.pop("next_battle_immunities", []):
            attacker.immunities.append({"kind": e.get("kind", "combat_damage"),
                                        "battle": bid, "nested": bool(e.get("nested", True))})
        # 条件授予/免疫的求值事件：被攻击者 = 战斗目标；无目标时敌方战斗区式神，
        # 无目标且攻击者持直击（确定目标前1）则为敌方牌手
        d0 = self.state.players[1 - atk_ref.player]
        if target is not None:
            vic0 = target.shikigami
        elif self._has_keyword(attacker, "direct"):
            vic0 = None  # 直击：无目标的战斗被攻击者改为敌方牌手
        else:
            vic0 = d0.combat_index
        def_event = {"defender": Ref(player=1 - atk_ref.player, shikigami=vic0)}
        # 破魔符标记（ext["crit_pierce_mark"]，半回合作用域"对其攻击的式神在该次
        # 战斗中获得[暴击][贯通]"——裁决11：不可叠加，再贴幂等；按当前战斗的
        # 被攻击者判定，战斗作用域授予、终止点随 grants 移除）
        if vic0 is not None:
            vic_s = self.state.players[1 - atk_ref.player].shikigami[vic0]
            if vic_s.ext.get("crit_pierce_mark"):
                for kw in ("critical", "piercing"):
                    cls = self._grant_keyword(attacker, kw)
                    grants.append((atk_ref, kw, cls))
        for kw, cond in grant_keywords:
            if cond is not None and not self._match(cond, def_event, atk_ref.player,
                                                    holder=atk_ref):
                continue  # 条件不满足（如被攻击者无破甲）：不授予
            cls = self._grant_keyword(attacker, kw)
            grants.append((atk_ref, kw, cls))
        for nested, cond, kind in immunities:
            if cond is not None and not self._match(cond, def_event, atk_ref.player,
                                                    holder=atk_ref):
                continue
            attacker.immunities.append({"kind": kind, "battle": bid, "nested": nested})
        if convert:
            self._battle_convert.add(bid)  # 毒蚀：伤害→破甲转化（伤害管线读取）
        if counter_piercing:
            self._battle_counter_piercing.add(bid)  # 反击贯通（反击事件生成/贯通修正读取）
        if double_fragile:
            self._battle_double_fragile[bid] = atk_ref  # 义道：破甲双倍（[暴击]时机读取）
        for block in temp_grants:
            self.state.temp_grants.append(TempGrant(
                block=block, controller=atk_ref.player, holder=atk_ref, battle=bid,
                # uses 扩展键（缺省 1）：战斗内可多次触发（胧月雪华斩"造成伤害时"）
                uses=int((block.model_extra or {}).get("uses", 1)),
                seq=self.state.next_ability_seq()))
        try:
            completed = self._battle_flow(atk_ref, attacker, move=move, target=target,
                                          origin=origin, ignore_veil=ignore_veil)
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
            self._battle_convert.discard(bid)  # 毒蚀转化标记随战斗结束清除
            self._battle_counter_piercing.discard(bid)  # 反击贯通标记随战斗结束清除
            self._battle_double_fragile.pop(bid, None)  # 义道破甲双倍标记随战斗结束清除
            self._battle_strikes.pop(bid, None)  # 多段攻击登记随战斗结束清除
            self._battle_echo.pop(bid, None)  # 战斗终止时未回赋的蚀刃毒羽登记一并丢弃
            self._battle_retarget.pop(bid, None)  # 交战目标改换登记随战斗终止清理
            # 反制挂账随战斗终止清除该攻击者的残留条目（罗城门：未击杀即过期）
            self._counter_watches[:] = [w for w in self._counter_watches
                                        if w["attacker"] != atk_ref]
            self._battle_stack.pop()
            self._settle("—— 战斗结束 ——")
            # 攻击者"直到攻击后"的临时强化在此结束；keep_attack_buffs（残心）跳过核销
            if attacker.attack_buffs and not self._has_keyword(attacker, "keep_attack_buffs"):
                for entry in attacker.attack_buffs:
                    attacker.temp_power -= entry.get("power", 0)
                    for kw, cls in entry.get("keywords", []):
                        self._remove_keyword(attacker, kw, cls)
                attacker.attack_buffs.clear()
        # 战斗结束后：先结算战斗中积累的延时能力（气绝后等——追加攻击登记在其中），
        # 再依次结算本战斗登记的追加攻击（战斗绑定的力量/关键字/临时触发已在上方
        # 终止点核销，追加战斗不享受原战斗牌加成——答复(7)）
        attacker.combat_power = 0  # 本次战斗战力于战斗结束时清除（追加攻击不继承）
        if completed:
            # 战斗结束后（裁决(10)，麓鸣·轰/影杀延时打击层）：战斗被取消或过早终止
            # （攻击者气绝/鸦羽疾走/攻击替换）则 _battle_flow 返回 falsy，不发事件；
            # 事件入延时队列，随即被下方 _drain_queue 冲刷（此时 attack_buffs 已核销，
            # 延时发起的打击不继承本次攻击增益——裁决(2) 影杀次序）
            self.emit("on_battle_end", attacker=atk_ref, battle=bid)
        self._drain_queue()
        # scope="battle" 延迟能力过期（麓鸣·轰"本次攻击后"，裁决(10)）：本次战斗
        # 结束（含被取消/过早终止——completed 为假、未发 on_battle_end）即清除该
        # 攻击者名下的残留条目，不带到其后的战斗
        for pl in self.state.players:
            for st_ in pl.shikigami:
                st_.delayed[:] = [e for e in st_.delayed
                                  if not (e.get("scope") == "battle"
                                          and e.get("watch") == [atk_ref.player,
                                                                 atk_ref.shikigami])]
        self._resolve_followup_attacks(bid)

    def _resolve_followup_attacks(self, bid: int) -> None:
        """战斗结束后的追加攻击（地狱之手类）：对生命最低的敌方式神（平手随机）发起
        有目标的战斗；无合法目标（含全持帷幕）时改为无目标战斗。"""
        for ref in self._battle_followups.pop(bid, []):
            if self.state.winner is not None or self.state.pending_end:
                return
            st = self.state.players[ref.player].shikigami[ref.shikigami]
            if not st.in_play:
                continue
            def_pi = 1 - ref.player
            d = self.state.players[def_pi]
            pool = [Ref(player=def_pi, shikigami=i)
                    for i, s in enumerate(d.shikigami)
                    if s.in_play and not s.dying
                    and not targets.is_veiled(self, Ref(player=def_pi, shikigami=i), ref.player)]
            target = None
            if pool:
                lo = min(d.shikigami[r.shikigami].health for r in pool)
                target = self.rng.choice(
                    [r for r in pool if d.shikigami[r.shikigami].health == lo])
                self._log(f"追加攻击以 {self.db.shikigami[d.shikigami[target.shikigami].id].name} 为目标")
            self._log(f"{self.db.shikigami[st.id].name} 发起了战斗结束后的追加攻击")
            self._resolve_combat(ref, st, target=target, origin="effect")

    def _battle_flow(self, atk_ref: Ref, attacker: ShikigamiState, *, move: bool,
                     target: Ref | None = None, origin: str = "effect",
                     ignore_veil: bool = False) -> bool:
        """战斗步骤：战斗准备前 → 战斗准备（移动/确定目标）→（被）攻击时 → 先攻阶段 → 交战阶段 → 战斗后。

        返回值：完整走完"战斗后"时机且攻击未被替换（烬染不夜）则 True——裁决(10)
        "战斗结束后"（on_battle_end，麓鸣·轰层）仅在战斗正常完成时发出；中途取消/
        过早终止（攻击者气绝/鸦羽疾走/先攻阶段终止等）返回 None（ falsy ），不发事件。

        target = 有目标的战斗的战斗目标（追猎）；origin 区分发起方式——目标在发起战斗前
        获得帷幕（或已不可指定）时：有目标的出击不发起战斗，其余改为无目标战斗
        （thoughts.txt 帷幕定义）；ignore_veil=True（灵咒效果发起的战斗，定案(4)）
        跳过帷幕再校验（气绝/离场校验照常）。确定目标（战斗准备步骤）：有目标用目标；无目标且
        攻击者持直击（确定目标前1）则被攻击者改为敌方牌手；否则敌方战斗区式神。
        先攻阶段击杀被攻击者（定案(6)）：攻击者有贯通则被攻击者改为对方牌手，否则
        终止本次战斗流程（后续时机不结算）——连击无贯通同样终止；被攻击者在求值点
        已复活则战斗继续（连击第二段打回原目标）。
        锚点（未实现）：战斗结界中的嵌套战斗。
        """
        p = self.state.players[atk_ref.player]
        def_pi = 1 - atk_ref.player
        d = self.state.players[def_pi]
        # ---- 发起战斗前：有目标的战斗目标再校验（帷幕/气绝/离场）----
        if target is not None:
            # 飘零之舞（assault_any_target）：出击目标可为任意一方的角色（含己方式神/
            # 牌手）——目标按其实际所属侧查座次，防守方随之改为目标所属侧。
            # 气绝目标（樱花妖门控选出，定案(2)）放行：defeated 未离场即合法，
            # 交战伤害/治疗走气绝转化通道
            tp = self.state.players[target.player]
            ts = (tp.shikigami[target.shikigami]
                  if target.shikigami is not None
                  and 0 <= target.shikigami < len(tp.shikigami) else None)
            defeated_ok = (ts is not None and ts.defeated and not ts.despawned
                           and self._has_keyword(attacker, "assault_any_target"))
            if target.shikigami is not None and (
                    ts is None or ts.dying
                    or (not ts.in_play and not defeated_ok)
                    or (not ignore_veil
                        and targets.is_veiled(self, target, atk_ref.player))):
                if origin == "assault":
                    self._log("战斗目标已不能成为攻击目标，不发起本次战斗")
                    return
                self._log("战斗目标已不能成为攻击目标，本次战斗改为无目标战斗")
                target = None
            else:
                def_pi = target.player  # 有目标战斗的防守方 = 目标所属侧
                d = tp
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
        # ---- 确定被攻击者：战斗目标 / 直击改牌手（确定目标前1）/ 敌方战斗区式神 ----
        if target is not None:
            vic_idx = target.shikigami
        elif self._has_keyword(attacker, "direct"):
            vic_idx = None  # 直击：无目标的战斗被攻击者改为敌方牌手（追猎已选目标则覆盖直击）
            self._log(f"{self.db.shikigami[attacker.id].name} 的【直击】生效，被攻击者改为对方牌手")
        else:
            vic_idx = d.combat_index
        # ---- （被）攻击时（即时时机）----
        cancel_marker = {"cancelled": False}  # 取消本次攻击旗标（cancel_attack 响应置位）
        replace_marker = {"active": False}    # 攻击替换旗标（attack_replace 能力置位）
        self.emit("on_before_assault", attacker=atk_ref,
                  victim=Ref(player=def_pi, shikigami=vic_idx),
                  battle=self._battle_stack[-1],
                  cancel=cancel_marker, attack_replace=replace_marker)
        self._drain_queue()
        if attacker.defeated or attacker.despawned:
            self._log("攻击方在伤害结算前气绝/离场，战斗中止")
            return
        if cancel_marker["cancelled"]:
            return  # 攻击被取消（鸦羽疾走）：战斗终止，已付出击次数/鬼火不退
        # （被）攻击时结算后敌方战斗区可能已变：无目标的战斗被攻击者随之变更
        # （rules.md「被攻击者随敌方战斗区式神改变而变更」）；有目标/直击者不变
        if target is None and not self._has_keyword(attacker, "direct"):
            vic_idx = d.combat_index
        # 重读攻击方战斗关键字快照与动态身材缓存（使用点读取）："攻击时获得[先攻]"类
        # （火吻之蛇，on_before_assault 监听授予）才能赶上本场战斗的先攻判定
        piercing = self._has_keyword(attacker, "piercing")
        combo = self._has_keyword(attacker, "combo")
        initiative = self._has_keyword(attacker, "initiative")
        self._refresh_stat_auras()

        # 交战目标改换（声东击西 battle_retarget 登记）：改换者的交战伤害打向另一个
        # 随机敌方角色（排除原交战目标；无另一个敌方角色时该次攻击落空）
        retargets = self._battle_retarget.get(self._battle_stack[-1], [])

        def _retarget(src_ref: Ref, original: Ref) -> Ref | None:
            pool = [r for r in targets.pool_refs(self, "enemy_character", src_ref.player)
                    if r != original]
            return self.rng.choice(pool) if pool else None

        def attack_event() -> _DamageEvent | None:
            victim = Ref(player=def_pi, shikigami=vic_idx)
            if any(r == atk_ref for r in retargets):
                victim = _retarget(atk_ref, victim)
                if victim is None:
                    self._log("交战目标改换：无另一个敌方角色，攻击落空")
                    return None
            self._quest_tick(atk_ref.player, "attack")  # 委托账本：攻击次数（每段计 1）
            amount = (attacker.health
                      if self._has_keyword(attacker, "combat_base_health")
                      else attacker.eff_power)  # 神木庇佑：以自身生命造成战斗伤害
            if (victim.player == atk_ref.player
                    and self._has_keyword(attacker, "friendly_combat_heal")):
                # 飘零之舞：攻击己方角色改为使其恢复等量于伤害的生命（不造成战斗伤害；
                # 攻击己方角色无反击——下方反击生成处按防守侧排除）
                vs0 = (self.state.players[victim.player].shikigami[victim.shikigami]
                       if victim.shikigami is not None else None)
                if vs0 is not None and vs0.defeated:
                    # 气绝己方目标（樱花妖门控选出）：heal_defeated_countdown 在场
                    # （攻击者即樱花妖）→ 恢复转化为气绝倒计时 -1（≤0 立即复活）；
                    # 无授权（结算时能力离场，答复(3)）则落空
                    if (not vs0.despawned and vs0.level >= 1
                            and self._has_keyword(attacker, "heal_defeated_countdown")):
                        vs0.revive_countdown -= 1
                        self._settle(f"【倒计时】{self.db.shikigami[vs0.id].name} "
                                     f"气绝倒计时 -1（现 {vs0.revive_countdown}，恢复转化）")
                        if vs0.revive_countdown <= 0:
                            self._revive(self.state.players[victim.player],
                                         victim.player, victim.shikigami,
                                         source=atk_ref, reason="effect")
                    return None
                self.heal(victim, amount, atk_ref, reason="攻击己方转化")
                return None
            return _DamageEvent(source=atk_ref, victim=victim,
                                amount=amount, kind="combat", piercing=piercing)

        def counter_event() -> _DamageEvent | None:
            vs = d.shikigami[vic_idx]
            if vs.defeated:
                return None  # 气绝的被攻击者不反击（飘零之舞攻击气绝目标，定案(2)）
            # 反击贯通例外（rules.md:201）：本战斗登记了 counter_piercing 时反击伤害具有贯通
            cp = any(b in self._battle_counter_piercing for b in self._battle_stack)
            src_ref = Ref(player=def_pi, shikigami=vic_idx)
            victim = atk_ref
            if any(r == src_ref for r in retargets):
                victim = _retarget(src_ref, atk_ref)
                if victim is None:
                    self._log("交战目标改换：无另一个敌方角色，攻击落空")
                    return None
            amount = (vs.health
                      if self._has_keyword(vs, "combat_base_health")
                      else vs.eff_power)  # 神木庇佑：反击同为战斗伤害
            return _DamageEvent(source=src_ref, victim=victim,
                                amount=amount, kind="counter",
                                piercing=cp)

        if replace_marker["active"]:
            # 攻击替换（烬染不夜）：改为对两个随机敌方角色造成等同于自身当前攻击的
            # 效果伤害（无先攻/交战阶段、不受反击；on_after_assault 照常发出）
            x = attacker.eff_power
            pool = targets.pool_refs(self, "enemy_character", atk_ref.player)
            for r in self.rng.sample(pool, min(2, len(pool))):
                if r.shikigami is None:
                    self.deal_to_player(r.player, x, atk_ref)
                else:
                    self.deal_to_shikigami(r, x, atk_ref)
        else:
            # ---- 先攻阶段：拥有连击/先攻的角色对对方造成战斗伤害，按（反击，攻击）并行 ----
            atk_first = combo or initiative
            def_first = vic_idx is not None and def_pi != atk_ref.player and (
                self._has_keyword(d.shikigami[vic_idx], "combo")
                or self._has_keyword(d.shikigami[vic_idx], "initiative"))
            if atk_first or def_first:
                events: list[_DamageEvent] = []
                if def_first and not remote:
                    ev = counter_event()
                    if ev is not None:
                        events.append(ev)
                if atk_first:
                    ev = attack_event()
                    if ev is not None:
                        events.append(ev)
                self._run_damage_queue(events)
                if self.state.pending_end:
                    return
                # 被攻击者气绝：攻击者具有贯通则被攻击者改为对方牌手，否则终止战斗
                # （定案(6)：连击无贯通第一段击杀同样终止，后续时机不结算）
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
            if (vic_idx is not None and not remote
                    and def_pi != atk_ref.player):  # 攻击己方角色（飘零之舞）：无反击
                vs = d.shikigami[vic_idx]
                def_init_only = (self._has_keyword(vs, "initiative")
                                 and not self._has_keyword(vs, "combo"))
                if not def_init_only:
                    ev = counter_event()
                    if ev is not None:
                        events.append(ev)
            if not (initiative and not combo):
                ev = attack_event()
                if ev is not None:
                    events.append(ev)
            if events:
                self._run_damage_queue(events)
            # 多段攻击（二帚流 multi_strike）：交战阶段后追加 strikes-1 段攻击——反击
            # 只一段（与首段攻击并行），后续段依次单独结算；被攻击者气绝按贯通规则
            # 改为对方牌手，无贯通/攻击者气绝则后续段终止
            strike_n = self._battle_strikes.get(self._battle_stack[-1], 1)
            for _ in range(strike_n - 1):
                if self.state.pending_end:
                    return
                if attacker.defeated or attacker.despawned:
                    break
                if vic_idx is not None and d.shikigami[vic_idx].defeated:
                    if piercing:
                        vic_idx = None
                    else:
                        break
                ev = attack_event()
                if ev is None:
                    break
                self._run_damage_queue([ev])
        # ---- 战斗后 ----
        self.emit("on_after_assault", attacker=atk_ref, battle=self._battle_stack[-1])
        # ---- 战斗结束后：蚀刃毒羽"攻击时"登记的一次性破甲回赋（维护者答复(2)）----
        for echo_ref, echo_amount in self._battle_echo.pop(self._battle_stack[-1], []):
            self._change_shield(echo_ref, echo_amount, "蚀刃毒羽", kind="fragile")
        # 攻击替换（烬染不夜）视为本次攻击未正常完成：不发 on_battle_end（裁决(10)）
        return not replace_marker["active"]

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
        if getattr(self.db.shikigami[s.id], "no_attack", False):
            raise IllegalAction(f"{self.db.shikigami[s.id].name} 不能发动攻击")
        if p.is_stunned:
            raise IllegalAction("牌手眩晕中，己方所有式神不能出击")
        if s.stuns:
            raise IllegalAction(f"{self.db.shikigami[s.id].name} 眩晕中，不能出击")
        # 能量出击（energy_assault 旗标，不知火类）：无出击次数且无鬼火时可耗能量出击
        ea = p.ext.get("energy_assault")
        energy_assault = bool(
            ea and p.assaults_left < 1 and p.orb < 1
            and ea.get("holder") == [self.state.active, i]
            and self._can_pay_energy(p, i, int(ea.get("cost", 3))))
        if p.assaults_left < 1 and not energy_assault:
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
        # 追猎：持追猎的式神主动出击可任选一名合法敌方式神为战斗目标（不选 = 无目标战斗，
        # 被攻击者按敌方战斗区/直击决定；无追猎不能选择出击目标）
        target: Ref | None = None
        want = cmd.get("target")
        if want is not None:
            want = want if isinstance(want, Ref) else Ref(**want)
            if self._has_keyword(s, "assault_any_target"):
                # 飘零之舞"出击时可以指定攻击任何其他角色"：任意一方的在场式神或
                # 牌手，仅排除攻击者本人；帷幕对敌方式神照常（targeted=True）。
                # 气绝式神入池按樱花妖门控（定案(2)：己方气绝需 heal_defeated_countdown
                # 在场、敌方气绝需 damage_defeated_countdown 在场）
                pool = targets.pool_refs(self, "any_character", self.state.active,
                                         targeted=True)
                pool += targets.gated_defeated_refs(self, "any_character",
                                                    self.state.active)
                if (want == Ref(player=self.state.active, shikigami=i)
                        or want not in pool):
                    raise IllegalAction("出击目标须为攻击者以外的任一角色")
            elif not self._has_keyword(s, "hunt"):
                raise IllegalAction("没有追猎的式神出击不能选择目标")
            elif (want.player != 1 - self.state.active or want.shikigami is None
                    or want not in targets.pool_refs(
                        self, "enemy_shikigami", self.state.active, targeted=True)):
                raise IllegalAction("追猎出击须以一名合法敌方式神为目标")
            target = want
        if energy_assault:
            self._spend_energy(p, i, int(ea.get("cost", 3)))
            self._log(f"{self.db.shikigami[s.id].name} 消耗 {int(ea.get('cost', 3))} 点能量出击")
        # 迅捷：出击事件的鬼火消耗处不消耗鬼火，随后失去一个一次性迅捷（永久迅捷不移除）
        elif self._has_keyword(s, "haste"):
            if "haste" in s.one_shot_keywords:
                s.one_shot_keywords.remove("haste")
            self._log(f"{self.db.shikigami[s.id].name} 的【迅捷】生效，本次出击不消耗鬼火")
        else:
            # 跳跳妹妹基础能力（先天伪关键字 extra_orb_cost）：出击额外消耗 1 点鬼火；
            # [迅捷]出击完全不耗（含额外的 1 火，定案(11)）
            need = 2 if self._has_keyword(s, "extra_orb_cost") else 1
            if p.orb < need:
                raise IllegalAction(f"出击需要 {need} 点鬼火")
            self._pay_orb(p, self.state.active, need, reason="出击")
        if not energy_assault:
            p.assaults_left -= 1
        atk_ref = Ref(player=self.state.active, shikigami=i)
        self._quest_tick(self.state.active, "assault")  # 委托账本：出击两次类
        self._consume_assault_boosts(p, atk_ref, s)
        rep_inv = self._replace_action_invocation(s)
        if rep_inv is not None:
            # 跳跳哥哥"出击时改为结附'迟钝'"：完全替换动作——不发起攻击/不进战斗
            # 流程（鬼火/瞬发/出击次数照常消耗，上方已结算），改为对自身结附灵咒
            self._log(f"{self.db.shikigami[s.id].name} 的出击改为结附灵咒【{rep_inv}】")
            self._settle(f"【替换】{self.db.shikigami[s.id].name} 出击改为结附"
                         f"灵咒【{rep_inv}】")
            self.attach_invocation(rep_inv, player=self.state.active,
                                   source=atk_ref, target=atk_ref)
            return
        self._resolve_combat(atk_ref, s, target=target, origin="assault")

    def _consume_assault_boosts(self, p: PlayerState, atk_ref: Ref, s: ShikigamiState) -> None:
        """出击时消耗全部出击加成/鼓舞（rules.md 出击流程 4.2-4.3）：
        力量直到本次出击的战斗后（attack_buffs 挂账核销）、护甲获得后保留；战斗牌不消耗。"""
        if not p.assault_boosts:
            return
        power = sum(b.get("power", 0) for b in p.assault_boosts)
        shield = sum(b.get("shield", 0) for b in p.assault_boosts)
        # 鼓舞随机关键字（惊鸿之舞 basic_boost keyword_random）：玩家级槽位
        # ext["boost_keyword"]——本次攻击临时授予攻击者，经 attack_buffs 随该次战斗
        # 结束移除；加成不被消耗时（离殇之舞 no_consume）槽位同样保留、下次出击再授予
        bkw = p.ext.get("boost_keyword")
        if power or bkw:
            entry: dict = {"power": power, "keywords": []}
            if power:
                s.temp_power += power
                self._record_max_power(s)
            if bkw:
                cls = self._grant_keyword(s, bkw)
                entry["keywords"].append((bkw, cls))
            s.attack_buffs.append(entry)
        if shield:
            self._change_shield(atk_ref, shield, "basic_boost")
        suffix = f"，关键字 {bkw}" if bkw else ""
        self._log(f"{self.db.shikigami[s.id].name} 获得出击加成（+{power}力量/+{shield}护甲{suffix}）")
        # 不消耗鼓舞（boost_no_consume 旗标，觉醒·不知火类）：出击加成保留，下次出击仍生效
        if not any(f.get("kind") == "no_consume" for f in p.ext.get("boost_flags", [])):
            p.assault_boosts.clear()
            p.ext.pop("boost_keyword", None)

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

    def _enter_combat(self, p: PlayerState, i: int, *, count_move: bool = True) -> None:
        """进入战斗区；若已有其它式神驻留，则其退回准备区。
        emit on_enter_combat（延时时机；被换下的驻留者经 _retreat 发 on_leave_combat）。
        移动计数（ext move_count_turn，不夜之火批次"移动"机制）：count_move=False 供召唤物
        直接进场——召唤进场不算移动（spec 以移动 op 的显式位移为准）。"""
        if p.combat_index is not None and p.combat_index != i:
            self._retreat(p, p.combat_index)
        p.combat_index = i
        if count_move:
            s = p.shikigami[i]
            s.ext["move_count_turn"] = s.ext.get("move_count_turn", 0) + 1
        self.emit("on_enter_combat", player=self.state.players.index(p),
                  shikigami=Ref(player=self.state.players.index(p), shikigami=i))

    def _retreat(self, p: PlayerState, i: int) -> None:
        """战斗区式神退回准备区；召唤物无准备区可归（home_slot=None），退回即离场（非气绝）。
        确实离开战斗区时 emit on_leave_combat（延时时机；气绝移动不经此路径，不发）。"""
        s = p.shikigami[i]
        was_in_combat = p.combat_index == i
        if was_in_combat:
            p.combat_index = None
        if s.defeated or s.despawned:
            return
        if s.home_slot is None:
            self._despawn(p, i)
        else:
            self._log(f"{self.db.shikigami[s.id].name} 退回准备区")
        if was_in_combat:
            s.ext["move_count_turn"] = s.ext.get("move_count_turn", 0) + 1  # 移动计数
            self.emit("on_leave_combat", player=self.state.players.index(p),
                      shikigami=Ref(player=self.state.players.index(p), shikigami=i))

    def _despawn(self, p: PlayerState, i: int) -> None:
        """召唤物离场：不进复活流程（保留坑位稳定下标）；同名再召是新实体，不继承永久增减益。"""
        s = p.shikigami[i]
        d = self.db.shikigami[s.id]
        self._clear_ability_card_auras(p, self.state.players.index(p), i)  # 能力离场：ability 光环移除
        self._detach_invocations(s, reason="离场")  # 灵咒随离场移除
        if p.combat_index == i:
            p.combat_index = None
        s.despawned = True
        self._log(f"{d.name} 离场")

    # ---------- 变形（transform；契约 §2，thoughts.txt 变形相关） ----------

    def _transform_shikigami(self, p: PlayerState, i: int, into: int,
                             source: Ref | None = None) -> None:
        """把座次 i 的式神变为变形物 into：A 离场（能力先离场）→ B 继承座位进场
        （能力后进场）。B 不继承 A 的增减益；A 的完整状态快照存入 B.transform_origin，
        解除变形时原样还原（连续变形继承最初的快照）；B 保留"所属式神"= 原式神 id
        （transform_owner，变形物无法使用原式神的任何牌）。
        B 的进场派系 = 变形效果来源式神（source）的永久派系，无来源时回退 into def faction。
        进场顺序：变形物为再进场者，entry_order 取本队当前最大值 +1（排到本队最后——
        维护者定案：再进场改变进场顺序为新近者，回合开始倒计时批次按进场顺序处理）。"""
        d = self.db.shikigami[into]
        if d.kind != "transform":
            raise ValueError(f"transform 的目标 {into} 不是变形物（kind=transform）")
        s = p.shikigami[i]
        origin = (s.transform_origin if s.transform_origin is not None
                  else s.model_dump(exclude={"transform_origin"}))
        owner_id = s.transform_owner if s.transform_owner is not None else s.id
        faction = d.faction
        if source is not None and source.shikigami is not None:
            faction = self.state.players[source.player].shikigami[source.shikigami].perm_faction
        pi = self.state.players.index(p)
        b = ShikigamiState(
            id=into, kind="transform", faction=faction, perm_faction=faction,
            level=s.level, home_slot=s.home_slot,
            entry_order=max(x.entry_order for x in p.shikigami) + 1,
            base_power=d.power, base_health=d.health, health=d.health,
            transform_owner=owner_id, transform_origin=origin,
            ext={"max_power": d.power},  # 力量历史峰值初值（断臂记账）
            perm_keywords=list(d.keywords))  # 先天关键字按永久类别入列
        p.shikigami[i] = b
        self._clear_ability_card_auras(p, pi, i)  # 原式神能力先离场：其 ability 光环移除
        self._log(f"{self.db.shikigami[s.id].name} 变形为 {d.name}")
        self._settle(f"【变形】{self.db.shikigami[s.id].name} 变形为 {d.name}"
                     f"（身材 {b.base_power}/{b.max_health}）")
        self._register_ability_countdown(pi, i)  # 能力后进场：注册变形物的倒计时能力块

    def _replace_shikigami(self, p: PlayerState, i: int, into: int) -> None:
        """式神替换（觉醒·番茄；非变形）：座次 i 的式神 A 被替换物 B 实体取代——
        B 继承座次与 A 的当前等级；无快照/不还原（不设 transform_origin，气绝前2
        还原路径天然跳过，B 气绝复活仍为 B）；ext["replace_owner"] 记原式神 id，
        出牌/响应校验据此放行原式神的全部卡牌（无变形"不能使用原式神卡牌"限制）。
        B 的派系 = B def 自身的 faction。替换视作新进场：entry_order 取本队当前
        最大值 +1（排本队最后——答复(3)）。"""
        d = self.db.shikigami[into]
        if d.kind != "replace":
            raise ValueError(f"replace 的目标 {into} 不是替换物定义（kind=replace）")
        s = p.shikigami[i]
        owner_id = s.ext.get("replace_owner", s.id)  # 连续替换仍指向最初的原式神
        pi = self.state.players.index(p)
        b = ShikigamiState(
            id=into, kind="replace", faction=d.faction, perm_faction=d.faction,
            level=s.level, home_slot=s.home_slot,
            entry_order=max(x.entry_order for x in p.shikigami) + 1,
            base_power=d.power, base_health=d.health, health=d.health,
            ext={"max_power": d.power,  # 力量历史峰值初值（断臂记账）
                 "replace_owner": owner_id},
            perm_keywords=list(d.keywords))  # 先天关键字按永久类别入列
        p.shikigami[i] = b
        self._clear_ability_card_auras(p, pi, i)  # 原式神能力离场：其 ability 光环移除
        self._log(f"{self.db.shikigami[s.id].name} 替换为 {d.name}")
        self._settle(f"【替换】{self.db.shikigami[s.id].name} 替换为 {d.name}"
                     f"（身材 {b.base_power}/{b.max_health}）")
        self._register_ability_countdown(pi, i)  # 能力后进场（替换物无能力块时为空操作）

    def _to_coffin(self, p: PlayerState, pi: int, i: int, into: int,
                   *, keep_combat: bool = False) -> None:
        """把座次 i 已气绝的非召唤物式神替换为棺材占位实体（04 沧海刀鸣，跳跳哥哥
        家族；to_coffin 动作与 check_defeated 的 coffin_on_defeat 旗标共用）。

        语义 = 占位 + 普通复活，非快照还原（与 transform 框架隔离：不设
        transform_origin，气绝前2/解除变形路径天然不触及）：
        - 原式神的"气绝结算完成后"状态快照存入棺材 coffin_origin（等级/永久修正
        保留，形态/临时修正/灵咒已在气绝流程清除——即正常复活baseline）；
        - 棺材留原座次、属原牌手；keep_combat 且原式神气绝时在战斗区
        （ext["defeated_in_combat"] 记账，消费即取）则棺材进其战斗区，
        否则落准备区（战斗区在气绝流程已让出）；
        - transform_owner = 原式神 id：替换期间原式神的牌不可使用
        （出牌校验按 transform_owner 拒绝，同变形物口径）；
        - 倒计时归零复活见 coffin_revive 动作；棺材被击杀见 check_defeated 拦截。
        """
        d = self.db.shikigami[into]
        if d.kind != "transform":
            raise ValueError(f"棺材实体 {into} 须登记为 kind=transform（占位实体）")
        s = p.shikigami[i]
        if not s.defeated or s.despawned or s.level < 1 or s.kind == "summon":
            raise ValueError("to_coffin 的目标须为已气绝的非召唤物式神")
        owner_id = s.ext.get("replace_owner", s.id)  # 连续替换仍指向最初的原式神
        was_in_combat = bool(s.ext.pop("defeated_in_combat", False))
        snapshot = s.model_dump(exclude={"transform_origin", "coffin_origin"})
        snapshot["ext"].pop("coffin_on_defeat", None)  # 棺材通道旗标不带入快照
        snapshot["ext"].pop("defeated_in_combat", None)
        b = ShikigamiState(
            id=into, kind="transform", faction=d.faction, perm_faction=d.faction,
            level=s.level, home_slot=s.home_slot,
            entry_order=max(x.entry_order for x in p.shikigami) + 1,  # 再进场排本队最后
            base_power=d.power, base_health=d.health, health=d.health,
            transform_owner=owner_id, coffin_origin=snapshot,
            ext={"max_power": d.power},  # 力量历史峰值初值（断臂记账）
            perm_keywords=list(d.keywords))  # 先天关键字按永久类别入列
        p.shikigami[i] = b
        if keep_combat and was_in_combat and p.combat_index is None:
            p.combat_index = i  # 棺封对战斗区式神：棺材进其战斗区
        self._log(f"气绝的{self.db.shikigami[owner_id].name} 替换为 {d.name}")
        self._settle(f"【替换】气绝的{self.db.shikigami[owner_id].name} 替换为 "
                     f"{d.name}（身材 {b.base_power}/{b.max_health}，倒计时 1）")
        self._register_ability_countdown(pi, i)  # 能力后进场：注册棺材的倒计时能力块

    def _untransform(self, pi: int, i: int) -> None:
        """解除座次 i 变形物的变形：按 transform_origin 快照还原原式神当时状态
        （身材/增减益/能力；变形物在场期间的改动不保留）。**例外（2026-08 定案）：
        等级继承解除变形时变形物的当前等级**（变形期间升过的级带回原式神，覆盖
        快照等级；已结算的"升至 1 级能力进场"等效果不回滚）。无快照（非变形物；
        式神替换物 replace 不设快照，天然不还原）为空操作。"""
        p = self.state.players[pi]
        s = p.shikigami[i]
        if s.transform_origin is None:
            return
        restored = ShikigamiState.model_validate(s.transform_origin)
        restored.level = s.level  # 等级继承变形物当前值（覆盖快照；定案见 docstring）
        # 还原进场 = 再进场：entry_order 覆盖快照旧值，取本队当前最大值 +1
        # （排到本队最后——维护者定案同变形进场）
        restored.entry_order = max(x.entry_order for x in p.shikigami) + 1
        self._clear_ability_card_auras(p, pi, i)  # 变形物能力离场：其 ability 光环移除（原式神光环还原后由能力进场重新注册）
        p.shikigami[i] = restored
        self._log(f"{self.db.shikigami[s.id].name} 变回 {self.db.shikigami[restored.id].name}")
        self._settle(f"【变形】{self.db.shikigami[s.id].name} 解除变形，"
                     f"还原为 {self.db.shikigami[restored.id].name}")
        if restored.in_play:
            # 式神先进场（entry_order 已在上文更新），其各能力再依次进场（答复(6)：
            # 基础/觉醒能力 → 形态能力 → 灵咒能力（预留）→ 卡牌赋予的延迟能力），
            # 各自记录新能力进场序号（on_ability_enter 随基础/觉醒进场发出）。
            # 快照已携带倒计时（变形时剩余值）时以其覆盖重新注册结果——还原按剩余
            # 倒计时继续（维护者定案："还原为倒计时1的山风"）
            snap_cd = (restored.countdown, restored.countdown_initial,
                       restored.countdown_block, restored.countdown_once,
                       restored.countdown_source)
            for entry in restored.delayed:
                # 快照经 model_dump/model_validate 往返：block/chosen 还原为模型对象
                # （须在能力进场事件发出前完成——收集器会读 delayed）
                if isinstance(entry.get("block"), dict):
                    entry["block"] = EffectBlock.model_validate(entry["block"])
                if isinstance(entry.get("chosen"), dict):
                    entry["chosen"] = Ref.model_validate(entry["chosen"])
            self._register_ability_countdown(pi, i)  # 基础/觉醒能力进场
            if snap_cd[0] is not None:
                (restored.countdown, restored.countdown_initial,
                 restored.countdown_block, restored.countdown_once,
                 restored.countdown_source) = snap_cd
            if restored.form is not None:
                restored.ability_entry["form"] = self.state.next_ability_seq()  # 形态能力进场
            for entry in restored.delayed:  # 卡牌赋予的延迟能力进场
                entry["seq"] = self.state.next_ability_seq()

    def _attach_form(self, p: PlayerState, i: int, card: CardInstance, cdef: CardDef) -> None:
        """为式神结附形态牌：先消灭旧形态，再用形态身材覆盖基础身材。

        Phase 1 简化版：省略"形态被消灭前/后"、"形态进场前/时/后"等子时机，
        统一 emit on_form_destroyed / on_form_attached（均延时时机）。
        """
        s = p.shikigami[i]
        old_form_id = s.form.id if s.form is not None else None
        if s.form is not None:
            self._destroy_form(p, i, reason="replace")
        s.form = card
        s.ability_entry["form"] = self.state.next_ability_seq()  # 形态能力进场序号（答复(4)）
        # 形态牌具有倒计时时，式神获得该倒计时能力（替换当前倒计时；rules.md ch10 结附流程）
        if cdef.countdown is not None:
            self._register_countdown(s, initial=cdef.countdown,
                                     block=cdef.countdown_effects, source=card.id)
        if cdef.form_power is not None:
            s.base_power = cdef.form_power + int(card.mods.get("form_power_delta", 0))
            self._record_max_power(s)  # 形态基础力量变更后同步峰值记账
        if cdef.form_health is not None:
            s.base_health = cdef.form_health + int(card.mods.get("form_health_delta", 0))
        s.health = s.max_health
        # 形态牌 keywords（fast/trigger 为卡牌级除外）结附期间授予式神
        for kw in cdef.keywords:
            if kw not in CARD_LEVEL_KEYWORDS:
                self._grant_keyword(s, kw)
        # 结附期间临时改派系（诅咒之木"被变为此形态的式神会临时变为紫岩"，
        # 形态 tags faction_override:<派系>；只动 faction 不动 perm_faction，
        # 形态离场经 _destroy_form 还原）
        for tag in cdef.tags:
            if tag.startswith("faction_override:"):
                s.faction = tag.split(":", 1)[1]
        self._log(f"{self.db.shikigami[s.id].name} 结附形态【{cdef.name}】")
        self._settle(f"【形态】{self.db.shikigami[s.id].name} 结附【{cdef.name}】"
                     f"（身材 {s.base_power}/{s.max_health}，生命回满）")
        pi = self.state.players.index(p)
        # form_changed：无当前形态或新旧形态不同（萤草"使用与当前形态不同的形态牌时"）
        self.emit("on_form_attached", player=pi, shikigami=i, uid=card.uid,
                  target=Ref(player=pi, shikigami=i), card=card,
                  form_changed=(old_form_id != card.id))

    def _play_form_card(self, p: PlayerState, si: int, card: CardInstance,
                        cdef: CardDef, controller: int, chosen: list[Ref]) -> None:
        """形态牌结附（主动使用与响应插入使用共用）：从手牌/原区域移除（不进入任何区域），
        以该卡牌数据给式神结附形态；形态离场时变为卡牌并置入墓地。此过程不是“卡牌移动事件”。
        随后结算形态牌的进场时效果（effects 块；可用打出时的选择目标，如尘缚之阵授予激怒）。
        实例修饰 revive_on_play：气绝中使用该形态时先复活来源式神（罗生门强化项）。
        """
        s = p.shikigami[si]
        if card.mods.get("revive_on_play") and s.defeated:
            self._revive(p, self.state.players.index(p), si)
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
        pi = self.state.players.index(p)
        # 形态离场事件在状态变更前发出（延时时机：先触发后执行）——离场形态自身的
        # 形态能力此时仍可收集（碧羽散华的离场清除标记）；结算时形态已离场
        self.emit("on_form_destroyed", player=pi, shikigami=i,
                  uid=old.uid, reason=reason,
                  target=Ref(player=pi, shikigami=i), card=old)
        s.form = None
        s.ability_entry.pop("form", None)  # 形态能力离场（进场序号一并失效）
        # 形态离场仅清除该形态授予的倒计时（rules.md ch10 消灭流程）；
        # 已被 set_countdown/能力注册替换的倒计时不受影响
        if s.countdown_source == old.id:
            self._clear_countdown(s)
        # 移除形态授予的关键字实例（气绝已清空时跳过）
        for kw in cdef.keywords:
            if kw not in CARD_LEVEL_KEYWORDS:
                self._remove_keyword(s, kw)
        s.ext.pop("power_zero", None)  # 力量覆写随形态离场清除（power_override）
        s.faction = s.perm_faction  # 结附期临时派系覆写（faction_override tag）随形态离场还原
        s.keep_fragile = False  # 破甲保留（肿胀体质）随形态离场解除——"形态在场时"语义
        if p.ext.get("dice_force_six_holder") == [pi, i]:
            # 萌即正义离场：其授予的判定者级必 6 修饰随形态离场通道解除
            p.ext.pop("dice_force_six", None)
            p.ext.pop("dice_force_six_holder", None)
        # 移除绑定该形态持有者的 scope="form" 卡牌光环（心技一体"形态离场时光环结束"；
        # 气绝经 _destroy_form 同路径一并移除）
        p.card_auras[:] = [a for a in p.card_auras
                           if not (a.get("scope") == "form" and a.get("holder") == [pi, i])]
        # 同路径移除绑定该形态持有者的动态身材光环（stat_aura scope="form"，闻世/火吻之蛇）
        p.ext["stat_auras"] = [a for a in p.ext.get("stat_auras", [])
                               if not (a.get("scope") == "form" and a.get("holder") == [pi, i])]
        # 同路径移除绑定该形态持有者的鼓舞旗标（boost_flags scope="form"，不夜之火批次；
        # 无 holder 的牌手级条目不受影响）
        p.ext["boost_flags"] = [e for e in p.ext.get("boost_flags", [])
                                if e.get("holder") != [pi, i]]
        # 同路径移除该式神持有的形态作用域免疫条目（grant_immunity scope="form"，霸主）
        s.immunities[:] = [e for e in s.immunities if not e.get("form")]
        # 同路径移除绑定该形态的手牌费用修正（cost_delta_player scope="form"，心灵迷宫；
        # side="opponent" 时条目登记在敌方牌手 ext，故双方扫描）
        for pl in self.state.players:
            if pl.ext.get("cost_mods") is not None:
                pl.ext["cost_mods"] = [
                    e for e in pl.ext["cost_mods"]
                    if not (e.get("scope") == "form" and e.get("holder") == [pi, i])]
        self.move_card(p, old, "graveyard")
        d = self.db.shikigami[s.id]
        s.base_power = d.power
        s.base_health = d.health
        s.health = s.max_health
        self._log(f"{d.name} 的形态【{cdef.name}】被消灭（原因：{reason}）")
        self._settle(f"【形态】{d.name} 的形态【{cdef.name}】离场"
                     f"（身材回退 {s.base_power}/{s.max_health}，生命回满）")

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
        if s.kind == "summon":
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
        self._settle(f"【升级】{p.name} 的{name}升至 {s.level} 级")
        self.emit("on_upgrade", player=self.state.active, shikigami=i, level=s.level,
                  target=Ref(player=self.state.active, shikigami=i))
        if p.upgrades == 0 or not self._has_upgrade_target(p):
            self.state.phase = "battle"

    def legal_upgrade_indices(self, pi: int) -> list[int]:
        """玩家 pi 当前可合法升级的式神下标（与 _cmd_upgrade 同一套规则）。

        供服务端回合超时随机升级等托管操作使用；不检查 phase/upgrades 机会数。
        """
        p = self.state.players[pi]
        # 变形物/替换物（kind="transform"）与正式式神一视同仁可升级（2026-08 定案）；
        # 召唤物（kind="summon"）仍不可升级
        candidates = [
            i for i, x in enumerate(p.shikigami)
            if x.kind != "summon" and not x.despawned
            and x.level < self.config.max_level
        ]
        if self.config.upgrade_rule == "lowest" and candidates:
            lowest = min(p.shikigami[i].level for i in candidates)
            candidates = [i for i in candidates if p.shikigami[i].level == lowest]
        return candidates

    def _cmd_end_turn(self, cmd: dict) -> None:
        """结束回合：触发 on_turn_end，结算完后切换回合方并进入对方回合开始阶段。

        响应排序（偷袭答复3）：当前回合方的回合结束效果（即时与延时）全部结算完后，
        才检查对方手牌响应——on_turn_end 发出时抑制响应收集，_drain_queue 之后以
        同一事件手动收集并结算（响应复查此时条件，如"（敌方）战斗区没有式神"）。
        """
        if self.state.winner is not None:
            return
        p = self.current
        self._settle(f"—— 回合结束阶段（{p.name}）——")
        self._suppress_responses = True
        try:
            self.emit("on_turn_end", player=self.state.active)
        finally:
            self._suppress_responses = False
        self._drain_queue()  # 回合结束的队列效果结算完再换手
        if self.state.winner is not None:
            return
        self._remove_expired_stuns(p)  # 己方回合结束批次：解除非本回合施加的眩晕
        self._remove_turn_keyword_grants()  # scope="turn" 关键字授予随本回合结束移除（惊鸿之舞）
        ev = {"name": "on_turn_end", "_emit": self.state.next_emit_seq(),
              "player": self.state.active}
        for pend in self._collect_responses(ev, 1 - self.state.active):
            self._resolve_pending(pend)
        self._drain_queue()  # 响应插入使用（偷袭的战斗）结算完再换手
        if self.state.winner is not None:
            return
        self.state.active = 1 - self.state.active
        self._start_turn()

    def _remove_turn_keyword_grants(self) -> None:
        """移除本回合授予的 scope="turn" 关键字（惊鸿之舞"所有己方式神本回合获得
        [帷幕]和[不屈]"）：触发发生在哪方回合就在那方回合结束点移除（双方扫描、
        按授予时回合号比对；已被消耗/气绝清除的实例由 _remove_keyword 安全跳过）。"""
        for pl in self.state.players:
            entries = pl.ext.get("turn_keyword_grants")
            if not entries:
                continue
            kept = [e for e in entries if e["turn"] != self.state.turn]
            for e in entries:
                if e["turn"] == self.state.turn:
                    self._remove_keyword(
                        pl.shikigami[e["ref"].shikigami], e["keyword"], e["cls"])
            if len(kept) != len(entries):
                pl.ext["turn_keyword_grants"] = kept

    def _remove_expired_stuns(self, p: PlayerState) -> None:
        """己方回合结束批次（契约 §1）：移除"非本回合施加"的普通眩晕（turn != 当前
        控制者回合号）；持续眩晕（预留）按 until 回合号移除。式神圣条与牌手 ext 同构。"""
        for s in p.shikigami:
            kept = [e for e in s.stuns if not self._stun_expired(e, p)]
            if len(kept) != len(s.stuns):
                s.stuns[:] = kept
                self._log(f"{self.db.shikigami[s.id].name} 的眩晕解除")
        stuns = p.ext.get("stuns")
        if stuns:
            kept = [e for e in stuns if not self._stun_expired(e, p)]
            if len(kept) != len(stuns):
                p.ext["stuns"] = kept
                self._log(f"{p.name} 的眩晕解除")

    @staticmethod
    def _stun_expired(e: dict, p: PlayerState) -> bool:
        if e.get("kind") == "invocation":
            return False  # 灵咒眩晕（迟钝）：不参与回合批次过期，随灵咒移除解除
        if e.get("kind") == "lasting":
            until = e.get("until")  # 持续眩晕（预留）：until 回合号到达即解除
            return until is not None and p.turn_count >= int(until)
        return e.get("turn") != p.turn_count  # 普通眩晕：非本回合施加的解除

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
        11-12. （Phase 5+ 预留）直到回合结束时效果 / 敌方回合外效果。
        13. 执行延时战斗区移回与回合开始时效果（_drain_queue）。
        14. 抽 1：后手玩家第 1 回合抽 1；先手玩家从第 2 回合开始抽 1。
        15. 进入式神升级阶段。
        """
        if self.state.winner is not None:
            return
        p = self.current
        self._settle(f"—— 回合开始阶段（{p.name} 的第 {p.turn_count + 1} 回合）——")
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
        self._quest_tick(pi, "round")  # 委托账本：回合开始计数（今日委托·柒"还需 N
        # 回合可用"= 己方回合开始 +1，定案(5)；多事多忙在场时敌方回合开始经 shareable
        # 扩域同计）
        # 2-15. 按步骤执行回合开始阶段
        self._turn_start_clear_shield(p)
        # "本回合"类卡牌光环（scope="turn"）在己方回合开始失效；其余 scope 条目不受影响
        p.card_auras[:] = [a for a in p.card_auras if a.get("scope") != "turn"]
        # "本回合"类牌手级监听（scope="turn"，天邪鬼黄·鼓舞类）同步失效
        p.auras[:] = [a for a in p.auras if a.get("scope") != "turn"]
        # "本回合"类延迟能力（scope="turn"，魔音扰心类）在己方回合开始清除（未消耗时）；
        # ext 半回合记账键按 core/registry.EXT_KEYS 登记表统一清除（不再散落手写 pop）：
        # 己方回合开始清除（own_turn_start：法术回响 spell_echo、"本回合额外力量"
        # turn_power 扣减、黄金羽 feather_used_turn——game 级键不清）
        for s in p.shikigami:
            s.delayed[:] = [e for e in s.delayed if e.get("scope") != "turn"]
            self._clear_ext(s, CLEAR_OWN_TURN_START)
        self._clear_ext(p, CLEAR_OWN_TURN_START)
        # "每回合合计一次"标记（寂寥心象类 turn_marks）：任一回合开始双方均清除
        # （回合 = 半回合）；狂啸"本回合生命不降到1以下"（min_health_turn）、百鬼夜行 X
        # 计数（damage_taken_turn）、本回合移动次数（move_count_turn）、记仇过滤键
        # （dealt_damage_turn）、闪烁半回合力量覆写（power_zero_turn 级联 power_zero）、
        # 能量免单名额（energy_free_turn 重置）同为半回合作用域，双方清除；
        # scope="turn" 免疫条目（immunities {"turn": n}，不可饶恕/舍生类）按回合号比对
        # 过期——此处同步清理过期条目，避免状态残留与显示残留
        for pl in self.state.players:
            self._clear_ext(pl, CLEAR_ANY_TURN_START)
            pl.immunities[:] = [e for e in pl.immunities
                                if "turn" not in e or e["turn"] == self.state.turn]
            for s in pl.shikigami:
                self._clear_ext(s, CLEAR_ANY_TURN_START)
                s.immunities[:] = [e for e in s.immunities
                                   if "turn" not in e or e["turn"] == self.state.turn]
        self._turn_start_revive(p, pi)
        self._turn_start_gain_orb(p, first, pi)
        pending_retreat = self._turn_start_schedule_retreat(p)
        self.emit("on_turn_start", player=pi)
        self._turn_start_countdown(p, pi)
        self._turn_start_charge(p, pi)  # 充能（不夜之火批次）：先倒计时后能量
        self._turn_start_reset_assaults(p, pi)
        if pending_retreat is not None:
            self._retreat(p, pending_retreat)
        self._drain_queue()
        self._turn_start_draw(p, pi)
        self._drain_queue()  # 抽牌挂起的移动事件（draw_move 待结算项）结算完再进升级阶段
        self._upgrade_phase(p)
        self.state.phase = "battle" if p.upgrades == 0 else "upgrade"
        self._log(f"—— {p.name} 的第 {p.turn_count} 回合（鬼火 {p.orb}）——")

    def _turn_start_clear_shield(self, p: PlayerState) -> None:
        """回合开始阶段 step 2：移除己方所有角色护甲/破甲（双向清零；keep_shield 仅保留正值部分）。
        觉醒·清姬（对方在场已觉醒且觉醒牌 tags 含 keep_enemy_fragile）：己方角色的破甲
        不被清除（护甲照常）；式神级 keep_fragile（肿胀体质，形态在场时）同样保留破甲。

        每个实际被移除护甲/破甲的角色发出一次 on_shield_changed（reason="turn_start_clear"，
        gained=False，kind 按被移除方向）——妖怪屋·灵力[增强]"每当己方角色的护甲或敌方
        角色的破甲因回合开始移除时，此牌效果+1"以卡牌触发器（card_in_hand 门控）+
        add_mod to=hand shield_boost 纯数据挂接；保留（keep_shield/keep_fragile）未移除
        的角色不发。"""
        pi = self.state.players.index(p)

        def _emit_cleared(ref: Ref, old: int) -> None:
            if old == 0:
                return
            kind = "shield" if old > 0 else "fragile"
            name = (self.db.shikigami[p.shikigami[ref.shikigami].id].name
                    if ref.shikigami is not None else p.name)
            self._settle(f"【{'护甲' if old > 0 else '破甲'}】{name} 的"
                         f"{'护甲' if old > 0 else '破甲'}因回合开始被移除"
                         f"（{old}→0）")
            self.emit("on_shield_changed", target=ref, old=old, new=0,
                      reason="turn_start_clear", kind=kind,
                      amount=-abs(old), gained=False)

        keep_fragile = self._fragile_kept_by_enemy(self.state.players.index(p))
        old_player = p.shield
        p.shield = min(0, p.shield) if keep_fragile else 0
        if p.shield != old_player:
            _emit_cleared(Ref(player=pi), old_player)
        for i, s in enumerate(p.shikigami):
            keep_neg = keep_fragile or s.keep_fragile  # 式神级破甲保留（肿胀体质）
            old = s.shield
            if s.keep_shield:
                # 护甲保留（觉醒·兵俑）；破甲照常清除（对方有觉醒·清姬时连同保留）
                s.shield = s.shield if keep_neg else max(0, s.shield)
            else:
                s.shield = min(0, s.shield) if keep_neg else 0
            if s.shield != old:
                _emit_cleared(Ref(player=pi, shikigami=i), old)

    def _fragile_kept_by_enemy(self, pi: int) -> bool:
        """玩家 pi 的对方是否有已觉醒且带 keep_enemy_fragile 标记觉醒牌的式神在场
        （觉醒·清姬"敌方角色的破甲不会在回合开始时清除"；扫描模式同 _orb_stored）。"""
        for s in self.state.players[1 - pi].shikigami:
            if s.in_play and s.awakened is not None \
                    and "keep_enemy_fragile" in self.db.cards[s.awakened].tags:
                return True
        return False

    @staticmethod
    def _is_invocation_countdown(s: ShikigamiState) -> bool:
        """当前倒计时是否为灵咒倒计时块（attach_invocation 注册，条目 cd_block
        指向同一 EffectBlock）——回合开始批次双车道分流用（维护者定案(6)）。"""
        return s.countdown_block is not None and any(
            e.get("cd_block") is s.countdown_block for e in s.invocations)

    def _turn_start_countdown(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 8-9：己方式神倒计时 -1（rules.md ch12），**双车道**——
        先扣非灵咒倒计时（step 8，妖琴师/山风类），再扣灵咒倒计时（step 9
        "式神灵咒倒计时"批次，维护者定案(6)：灵咒倒计时晚于非灵咒倒计时扣减）。

        归零流程（先即时插入结算、再重置/移除）见 _countdown_zero，与 countdown_delta
        动作共用。每次减少发出 on_countdown_reduced
        （original=actual=1，非卡牌来源；势类"倒计时减少时"监听挂此事件）；批次减少
        属**自然减少**（natural=True）——非"减少倒计时效果"，觉醒·山风复制不共享
        （2026-08 定案：仅卡牌/能力等效果来源共享）。
        处理顺序 = 进场顺序（entry_order 升序）且**动态取序**（答复(5)：批次非快照——
        每步重新取剩余未处理者中 entry_order 最小者；批次内进场顺序变化立即生效，
        批次内新进场者（如归零效果中的还原/结附迟钝）排在后面当轮也处理。已处理按
        （座次, 实体 id）记账：归零重置/循环型不被二次处理，同座次新实体可处理）。
        """
        processed: set[tuple[int, int]] = set()
        for inv_lane in (False, True):  # 先非灵咒车道、后灵咒车道
            while True:
                rest = [i for i in range(len(p.shikigami))
                        if (i, p.shikigami[i].id) not in processed
                        and p.shikigami[i].countdown is not None
                        and p.shikigami[i].in_play
                        and self._is_invocation_countdown(p.shikigami[i]) == inv_lane]
                if not rest:
                    break
                i = min(rest, key=lambda j: p.shikigami[j].entry_order)
                s = p.shikigami[i]
                processed.add((i, s.id))
                s.countdown -= 1
                self.emit("on_countdown_reduced",
                          shikigami=Ref(player=pi, shikigami=i),
                          original=1, actual=1, by_card=False, natural=True)  # 自然减少不共享
                if s.countdown <= 0:
                    self._countdown_zero(pi, i)

    def _turn_start_charge(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段：[充能]式神获得 1 点能量（不夜之火批次）。

        气绝式神能量保留且继续充能（等级 >= 1 即充，不看 in_play——in_play 含未气绝；
        召唤物离场 despawned 不充）。"""
        for i, s in enumerate(p.shikigami):
            # 气绝式神能量保留但不充能（维护者定案：气绝无能力）；复活批次先于本批次，
            # 刚复活的式神当回合立即 +1；召唤物离场 despawned 不充
            if (s.level >= 1 and not s.defeated and not s.despawned
                    and self._has_keyword(s, "charge")):
                self._gain_energy(p, i, 1)

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

    def _register_ability_countdown(self, pi: int, si: int, *, awaken: bool = False) -> None:
        """能力进场（对局开始/升至 1 级/复活）与觉醒替换：注册式神当前能力
        （基础/觉醒）中的倒计时能力块（EffectBlock.countdown 非 None 者）。

        当前能力无倒计时块时清除原能力授予的倒计时（能力替换/离场语义）；
        形态授予的倒计时（来源 = 当前形态牌 id）不受影响。
        觉醒替换（awaken=True）且新能力无静态倒计时块时，继承原能力的动态倒计时
        （set_countdown 授予，来源 = 式神自身 id）：保留归零块与 recorded_card，
        剩余倒计时变为 1（维护者答复(10)："替换觉醒并变为倒计时1"，大天狗用）。
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
        if found is not None:
            if s.form is None or s.countdown_source != s.form.id:
                self._clear_countdown(s)
            self._register_countdown(s, initial=found.countdown, block=found,
                                     once=found.once, source=source)
        elif awaken and s.countdown_block is not None and s.countdown_source == s.id:
            # 继承动态倒计时并变为倒计时 1
            s.countdown = min(s.countdown, 1) if s.countdown is not None else 1
        elif s.form is None or s.countdown_source != s.form.id:
            self._clear_countdown(s)
        # 能力进场序号（答复(4)(6)：同事件触发按能力进场顺序排序；对局开始/升级/
        # 复活/觉醒替换/变形与还原均经本路径重新记录）
        s.ability_entry["ability"] = self.state.next_ability_seq()
        # 能力进场事件（对局开始/升至 1 级/复活/觉醒替换/变形与还原均经本路径）：
        # 供"能力进场时登记"类能力监听（萤草形态光环——scope="ability" 卡牌光环）
        self.emit("on_ability_enter", player=pi, shikigami=si,
                  target=Ref(player=pi, shikigami=si))

    def _clear_ability_card_auras(self, p: PlayerState, pi: int, si: int) -> None:
        """能力离场（气绝/变形/离场/觉醒替换旧能力）：移除该座次能力授予的
        scope="ability" 卡牌光环（萤草基础/觉醒的形态牌[瞬发]光环）与
        scope="ability" 灵咒修饰条目（inv_mod，大岳丸"八尺琼曲玉结附于大岳丸时
        效果+1/翻倍"——能力进场经 on_ability_enter 注册，本通道统一离场清除）。"""
        p.card_auras[:] = [a for a in p.card_auras
                           if not (a.get("scope") == "ability" and a.get("holder") == [pi, si])]
        mods = p.ext.get("inv_mod")
        if mods:
            kept = [m for m in mods
                    if not (m.get("scope") == "ability" and m.get("holder") == [pi, si])]
            if len(kept) != len(mods):
                p.ext["inv_mod"] = kept
                self._refresh_invocation_mods(pi)

    def _countdown_block_for(self, source: int) -> EffectBlock | None:
        """按倒计时来源 id 找回对应的倒计时能力块（countdown_history 重放用，大合奏）。

        基础=式神 id（式神定义的静态倒计时块）；觉醒=觉醒牌 id（觉醒能力块中的
        倒计时块）；形态=形态牌 id（countdown_effects）。找不回返回 None（跳过）。
        """
        d = self.db.shikigami.get(source)
        if d is not None:
            return next((b for b in d.all_abilities if b.countdown is not None), None)
        cdef = self.db.cards.get(source)
        if cdef is not None:
            block = next((b for b in cdef.abilities if b.countdown is not None), None)
            return block if block is not None else cdef.countdown_effects
        return None

    def _countdown_zero(self, pi: int, si: int) -> None:
        """倒计时归零流程（rules.md ch12 流程 4 修订版；回合开始批次与 countdown_delta 共用）。

        1. 倒计时 ≤ 0 → 先即时插入结算 countdown_block.steps（此时倒计时仍为 0，
           块内对自身 countdown_delta 修正为 -0 空操作）；**例外：灵咒一次型
           （once）倒计时在归零块之前先移除灵咒本体**（定案(1)：移除眩晕早于
           发起攻击；定案(9)：移除全部同名条目——移除经 _remove_invocation
           一并清除倒计时注册，故其归零块结算时倒计时已为 None）；
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
            cname = f"（【{self.db.cards[card.id].name}】）" if card is not None else ""
            self._settle(f"【倒计时】{self.db.shikigami[s.id].name} 的倒计时归零，效果生效{cname}")
            # 倒计时能力生效时（即时时机）：先于归零块结算——烈/刚/斩类监听授予的
            # 增益/关键字赶上归零块发起的攻击（斩经 next_battle 通道绑定该次战斗）
            self.emit("on_countdown_proc",
                      shikigami=Ref(player=pi, shikigami=si), source=source, once=once)
            if once:
                # 灵咒一次型倒计时（迟钝"生效后移除"）：**先移除灵咒再结算归零块**
                # （维护者定案(1)："移除眩晕应早于发起攻击"——移除含解除灵咒眩晕、
                # 经 _remove_invocation 一并清除倒计时注册）；多条同名灵咒并存时
                # 移除该式神上全部同名条目（定案(9)："倒计时生效时会移除全部迟钝"）
                names = {e["name"] for e in s.invocations
                         if e.get("cd_block") is block}
                for e in list(s.invocations):
                    if e["name"] in names:
                        self._remove_invocation(s, e, reason="倒计时生效")
            horizon = self._resolve_block(block, ExecContext(
                controller=pi, source=Ref(player=pi, shikigami=si), card=card,
                is_ability=True))  # 倒计时效果属式神能力（贯通继承判定）
            # 能力块延时界（2026-08 定案）：块内减少倒计时引起的觉醒·山风复制等
            # 延时效果在本能力块结算完成后执行（不冲刷外层卡牌级延时项）
            self._drain_horizon(horizon)
            if source is not None:
                p.ext.setdefault("countdown_history", []).append(source)
        if block is not None and s.countdown_block is block:
            # 结算期间未被替换/清除：循环型重置为初始值；一次型（once）移除
            # （灵咒一次型已在归零块结算前随灵咒移除清除，此处不命中）
            if once:
                self._clear_countdown(s)
            else:
                s.countdown = initial

    def _revive(self, p: PlayerState, pi: int, i: int, source: Optional[Ref] = None, reason: str = "倒计时") -> None:
        """复活一名己方式神（倒计时归零/复活类 op 共用）：回满生命、重注册倒计时
        能力、发出 on_shikigami_revived（source=复活来源）。"""
        s = p.shikigami[i]
        s.defeated = False
        s.revive_countdown = 0
        s.health = s.max_health
        self._register_ability_countdown(pi, i)  # 能力进场：复活重新注册倒计时能力
        self._log(f"{self.db.shikigami[s.id].name} 复活")
        self._settle(f"【复活】{self.db.shikigami[s.id].name} 复活（生命回满 {s.max_health}）")
        # 委托账本：己方复活计数（一切复活含倒计时自然复活都计；shareable=False）
        self._quest_tick(pi, "revive", shareable=False)
        self.emit("on_shikigami_revived",
                  shikigami=Ref(player=pi, shikigami=i), source=source, reason=reason)

    def _turn_start_revive(self, p: PlayerState, pi: int) -> None:
        """回合开始阶段 step 3：已气绝己方式神倒计时 -1，归零复活。"""
        for i, s in enumerate(p.shikigami):
            if s.defeated and not s.despawned and s.level >= 1:
                s.revive_countdown -= 1
                if s.revive_countdown <= 0:
                    self._revive(p, pi, i)

    def _turn_start_gain_orb(self, p: PlayerState, first: bool, pi: int) -> None:
        """回合开始阶段 steps 4-5：鬼火重置为 0 再获得；emit on_orb_changed。

        觉醒·青行灯（觉醒牌 tags 含 orb_store）：鬼火不清除，储存累加、封顶 4 点
        （"你的鬼火不会自动清除，最大可储存 4 点"——超出 4 点的部分被清除）。
        """
        cfg = self.config
        gain = cfg.first_turn_orb if first else self.cfg(pi, "orb_per_turn")
        if cfg.orb_cap is not None:
            gain = min(gain, cfg.orb_cap)
        old_orb = p.orb
        if self._orb_stored(p):
            p.orb = min(4, p.orb + gain)
        else:
            p.orb = 0
            p.orb += gain
        if p.orb != old_orb:
            self.emit("on_orb_changed", player=pi, old=old_orb, new=p.orb, reason="回合开始")

    def _orb_stored(self, p: PlayerState) -> bool:
        """该玩家是否有已觉醒且带 orb_store 标记觉醒牌的式神在场（鬼火储存）。"""
        for s in p.shikigami:
            if s.in_play and s.awakened is not None \
                    and "orb_store" in self.db.cards[s.awakened].tags:
                return True
        return False

    def _turn_start_schedule_retreat(self, p: PlayerState) -> int | None:
        """回合开始阶段 step 6：登记战斗区非召唤物式神延时移回（召唤物留在战斗区）。

        扎根（结附形态的 tags 含 no_retreat）："己方回合开始时不会从战斗区移回
        准备区"——不登记移回，该式神留在战斗区。"""
        if p.combat_index is not None:
            s = p.shikigami[p.combat_index]
            if s.kind != "summon":
                if s.form is not None and "no_retreat" in self.db.cards[s.form.id].tags:
                    return None  # 扎根：本回合开始不移回
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
        """回合开始阶段 step 14：抽 1（后手第 1 回合也抽；先手从第 2 回合开始抽）。

        reason="turn_start" 贯通抽牌事件——明心（draw_to_pick，"回合开始的抽牌
        改为检视牌库顶三张选一张置入手牌然后洗牌库"）与觉醒·书翁（deck_out_burn）
        均为抽牌事件"抽牌前"挂点的触发+终止（答复(4)，见 `_draw_terminate`）。"""
        if not (p.turn_count > 1 or self.state.active == 1):
            return
        self.draw_cards(pi, self.cfg(pi, "draw_per_turn"), reason="turn_start")

    def _has_upgrade_target(self, p: PlayerState) -> bool:
        """当前玩家是否还有可升级的式神（用于自动判断升级阶段是否可跳过）。

        气绝或眩晕不影响升级资格（仍可升级）。
        """
        return any(
            s.kind != "summon" and not s.despawned
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

    def _spell_damage(self, ctx: ExecContext) -> bool:
        """法术伤害判定（答复(7)）：伤害来自法术牌的效果（ctx.card 为法术牌且非能力
        来源）。法术伤害 ≠ 非战斗伤害——式神能力（基础/觉醒/形态/延迟）伤害不算。"""
        return (ctx.card is not None and not ctx.is_ability
                and self.db.cards[ctx.card.id].card_type == "spell")

    def _ability_piercing(self, ctx: ExecContext) -> bool:
        """能力伤害的贯通继承：仅当伤害来自式神能力（is_ability：基础/觉醒/形态/延迟能力）
        且来源式神具有贯通时成立；卡牌效果伤害不继承（terminology.md「贯通」）。
        幻境能力伤害另读触发来源幻境实体（ctx.field）的贯通关键字（星轨[贯通]——
        幻境实体关键字 channel，与来源式神是否持贯通无关）。"""
        if ctx.field is not None and "piercing" in ctx.field.keywords:
            return True
        if not ctx.is_ability or ctx.source is None or ctx.source.shikigami is None:
            return False
        s = self.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
        return self._has_keyword(s, "piercing")

    def deal_to_shikigami(self, ref: Ref, amount: int, source: Ref | None,
                          *, kind: str = "effect", piercing: bool = False,
                          spell: bool = False, converted: bool = False,
                          card: CardInstance | None = None) -> int:
        """对式神造成伤害（单事件伤害队列，走完整伤害事件流程）；返回实际造成伤害值。"""
        return self._run_damage_queue([_DamageEvent(source=source, victim=ref,
                                                    amount=amount, kind=kind, piercing=piercing,
                                                    spell=spell, converted=converted,
                                                    card=card)])

    def deal_to_player(self, player_index: int, amount: int, source: Ref | None,
                       *, kind: str = "effect", spell: bool = False,
                       converted: bool = False, card: CardInstance | None = None) -> int:
        """对牌手造成伤害（单事件伤害队列，走完整伤害事件流程）；返回实际造成伤害值。"""
        return self._run_damage_queue([_DamageEvent(source=source, victim=Ref(player=player_index),
                                                    amount=amount, kind=kind, spell=spell,
                                                    converted=converted, card=card)])

    def _run_damage_queue(self, events: list[_DamageEvent],
                          defer_defeats: list[tuple[Ref, Ref | None, str]] | None = None) -> int:
        """伤害事件队列：并行伤害、贯通溢出、伤害合并都在同一队列结算（rules.md 第五章）。
        返回本队列实际造成的伤害合计（扣减生命口径，巨浪"每造成 1 点伤害"统计用）。

        每个事件依次经过时点批次：造成伤害前（穿刺）→ 伤害开始时 → 贯通修正 → 护甲计算前（屏障）→ 护甲计算 →
        护甲计算后 → 扣减生命前 → 合并 → 扣减生命（不屈）→ 伤害后。队列清空后按受伤顺序
        生成气绝事件（rules.md:207）；defer_defeats 给出时改为把受伤者追加到该列表、
        由调用方延后统一结算（随机分配伤害：气绝事件按延时时机在效果结束后结算）。
        子优先级批次（0/1/2/3）暂不拆事件名，待首个有优先级需求的监听者出现再拆。
        """
        dq: deque[_DamageEvent] = deque(events)
        victims: list[tuple[Ref, Ref | None, str]] = []  # (受伤式神, 来源, 气绝原因) 按受伤顺序
        total_dealt = 0  # 本队列实际造成的伤害合计（巨浪"每造成 1 点伤害"统计口径）
        self._settle("—— 伤害结算开始 ——")
        while dq:
            ev = dq.popleft()
            self._damage_event_flow(ev, dq, victims)
            if self._redirect_spawned:
                # 转移类能力（redirect_damage_to_self）在 on_after_shield 批次生成的
                # 新事件：原事件已终止（amount 归零），新事件插入队列最前优先结算
                for new_ev in reversed(self._redirect_spawned):
                    dq.appendleft(new_ev)
                self._redirect_spawned.clear()
            total_dealt += ev.dealt
            if self.state.winner is not None:
                return total_dealt
        for ref, source, reason in victims:
            if defer_defeats is not None:
                defer_defeats.append((ref, source, reason))
            else:
                self.check_defeated(ref, source=source, reason=reason)
        self._settle("—— 伤害结算结束 ——")
        return total_dealt

    def _emit_damage_batch(self, name: str, ev: _DamageEvent) -> None:
        """伤害时点批次（即时时机）；payload 携带 damage 可变对象供监听者修改伤害值。
        battle 键供战斗绑定的一次性临时触发（二帚流"伤害改为1"类 on_damage_start
        挂账）按本战斗过滤。"""
        self.emit(name, damage=ev, victim=ev.victim, source=ev.source,
                  amount=ev.amount, kind=ev.kind,
                  battle=self._battle_stack[-1] if self._battle_stack else None)

    def _spawn_redirect(self, ev: _DamageEvent, new_victim: Ref, uid: str) -> None:
        """伤害目标转移（定案"转移链"；redirect_damage_to_self 动作调用）：生成等量、
        同来源、同原因、同属性（无[贯通]）的新伤害事件，从"护甲计算前0"开始结算，
        转移链延长 uid；新事件挂起到 _redirect_spawned，由 _run_damage_queue 统一
        插入队列最前。原伤害事件由调用方归零终止（每次只单个触发——归零断点使同
        批次其余优先级≥2 转移块不再处理）。新目标已标记气绝/濒死时新事件在管线
        入口被拦截、不造成实际伤害，但原事件照常终止（定案备注）。"""
        self._redirect_spawned.append(_DamageEvent(
            source=ev.source, victim=new_victim, amount=ev.amount, kind=ev.kind,
            spell=ev.spell, converted=ev.converted, start="pre_shield_0",
            redirect_chain=ev.redirect_chain | {uid}, card=ev.card))

    def _damage_event_flow(self, ev: _DamageEvent, dq: deque[_DamageEvent],
                           victims: list[tuple[Ref, Ref | None, str]]) -> None:
        p = self.state.players[ev.victim.player]
        s = p.shikigami[ev.victim.shikigami] if ev.victim.shikigami is not None else None
        if ev.amount <= 0:
            return  # 伤害值不大于 0：终止结算
        if s is not None and (s.defeated or s.despawned or s.dying):
            # 觉醒·樱花妖伪关键字 damage_defeated_countdown 的管线伤害通道（定案(2)
            # 飘零之舞攻击气绝敌方式神等直进管线的战斗伤害；damage 动作在动作层
            # 拦截气绝目标，不到此处）：来源在场持该能力时，对**敌方**气绝式神的
            # 伤害改为气绝倒计时 +1（不再视为伤害）；无授权则拦截空过
            if (s.defeated and not s.despawned and not s.dying and s.level >= 1
                    and ev.source is not None and ev.source.shikigami is not None
                    and ev.source.player != ev.victim.player):
                src0 = self.state.players[ev.source.player] \
                    .shikigami[ev.source.shikigami]
                if src0.in_play and self._has_keyword(src0, "damage_defeated_countdown"):
                    s.revive_countdown += 1
                    self._settle(f"【倒计时】{self.db.shikigami[s.id].name} 气绝倒计时 +1"
                                 f"（现 {s.revive_countdown}，伤害转化）")
            return  # 气绝/离场/濒死者不受伤害
        if s is None and p.defeated:
            return  # 气绝的牌手不再受到伤害
        # 干扰投掷禁伤（定案(7)：结附己方牌手的一回合效果——玩家 ext
        # ["no_damage_vs_inv"] 为 append 列表，条目 {"value": 灵咒名, "ref": [pi, 座次]}
        # 限定来源式神；该式神气绝/复活不丢失）：来源命中条目且受害者结附该灵咒时
        # 伤害无效——早期终止（一切伤害类型；"结附'鸮之守护'的式神"不限灵咒来源，
        # 维护者定案按字面）
        if ev.source is not None and ev.source.shikigami is not None and s is not None:
            for pl in self.state.players:
                for e in pl.ext.get("no_damage_vs_inv", []):
                    if e.get("ref") == [ev.source.player, ev.source.shikigami] and \
                            any(inv["name"] == e.get("value") for inv in s.invocations):
                        src0 = self.state.players[ev.source.player] \
                            .shikigami[ev.source.shikigami]
                        self._log(f"{self.db.shikigami[src0.id].name} 不能对结附"
                                  f"【{e['value']}】的式神造成伤害，本次伤害无效")
                        return
        # 毒蚀转化（维护者答复(5)）：伤害事件生成点全额转化为等量破甲——护甲不再
        # 先吸收，不再视为伤害（无扣减/气绝/吸血/on_damage）。converted=True 的伤害
        # （碧羽散华破甲→伤害的嵌套事件）不再转化，防止转化类效果来回循环。
        if not ev.converted and any(b in self._battle_convert for b in self._battle_stack):
            self._change_shield(ev.victim, ev.amount, "毒蚀", kind="fragile")
            self._log(f"伤害转化为 {ev.amount} 点破甲（毒蚀）")
            return
        # 清姬伤害转化（基础/觉醒共用，伪关键字 damage_to_fragile 永久通道——先天关键字
        # 按永久类别入列，死亡不清）：来源式神持标记且受伤者无破甲 → 伤害事件生成点
        # 全额转化为等量破甲（不再视为伤害：无扣减/气绝/吸血/on_damage）
        if (not ev.converted and ev.source is not None and ev.source.shikigami is not None
                and self._has_keyword(
                    self.state.players[ev.source.player].shikigami[ev.source.shikigami],
                    "damage_to_fragile")):
            holder0 = s if s is not None else p
            if holder0.shield >= 0:
                self._change_shield(ev.victim, ev.amount, "清姬", kind="fragile")
                self._log(f"伤害转化为 {ev.amount} 点破甲（清姬）")
                return
        # 批次 1：造成/受到伤害开始时（即时时机）；流程起点晚于本批次的事件
        # （start != "full"：贯通溢出/伤害目标转移的新事件）跳过批次 0/1
        if ev.start == "full":
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
                # 仅护甲穿刺（碎岩 20191212 伪关键字）：同批次、同"与伤害是否生效无关"语义，
                # 只清正值护甲（破甲为负值本就不动），不移除屏障
                if self._has_keyword(src, "pierce_armor"):
                    holder = s if s is not None else p
                    if holder.shield > 0:
                        self._change_shield(ev.victim, -holder.shield, "穿刺（仅护甲）")
            self._emit_damage_batch("on_damage_start", ev)
            if ev.amount <= 0 or (s is not None and s.defeated):
                return
        skip_shield_calc = False
        skip_before_health = False
        # 批次 2：贯通修正（非反击伤害、伤害原因具有贯通、受伤者是式神；
        # 反击例外——本战斗登记 counter_piercing 的反击伤害同样走贯通修正，rules.md:201）；
        # 转移新事件（start="pre_shield_0"）跳过本批次——"无[贯通]"语义（贯通不随转移继承）
        if ev.piercing and ev.start != "pre_shield_0" and s is not None and (
                ev.kind != "counter"
                or any(b in self._battle_counter_piercing for b in self._battle_stack)):
            skip_shield_calc = True
            if s.shield > 0:
                absorbed = min(s.shield, ev.amount)
                ev.amount -= absorbed
                self._change_shield(ev.victim, -absorbed, "贯通修正")
            if ev.amount > s.health:
                # 伤害值改为当前生命，溢出量以同来源同原因新事件加入本队列
                # （start="pre_shield_2"：从"护甲计算前2"贯通修正批次开始）
                overflow = ev.amount - s.health
                ev.amount = s.health
                dq.append(_DamageEvent(source=ev.source, victim=Ref(player=ev.victim.player),
                                       amount=overflow, kind=ev.kind, spell=ev.spell,
                                       start="pre_shield_2", card=ev.card))
            # 提前结算"扣减生命前"批次，后续不再结算该批次
            self._emit_damage_batch("on_before_health", ev)
            skip_before_health = True
            if ev.amount <= 0:
                return
        # 护甲计算前1（汤盆冲撞[增强]"此牌伤害翻倍"时机锚点，terminology.md 登记）：
        # 来源卡牌实例带 double_damage 修饰（conditional_mods 装配写入）时伤害值翻倍；
        # 转移新事件（start="pre_shield_0"）跳过——从"护甲计算前0"（on_before_shield）开始
        if ev.start != "pre_shield_0" and ev.card is not None \
                and ev.card.mods.get("double_damage") and ev.amount > 0:
            ev.amount *= 2
            self._log(f"【{self.db.cards[ev.card.id].name}】的伤害翻倍至 {ev.amount} 点")
        # 批次 3：护甲计算前（批次 3 = 关键字"屏障"）；持伤害转移挂账（damage_redirects）
        # 时屏障不消耗——该伤害将在护甲计算后转移给牌手（答复(5) 批次 2 挂点）
        self._emit_damage_batch("on_before_shield", ev)
        if s is not None and ev.amount > 0 and "barrier" in s.one_shot_keywords \
                and not s.ext.get("damage_redirects"):
            ev.amount = 0
            s.one_shot_keywords.remove("barrier")
            self._log(f"{self.db.shikigami[s.id].name} 的屏障抵消了伤害")
        if ev.amount <= 0:
            return
        # 批次 4：护甲计算——破甲（shield < 0）：移除并增加等量伤害；护甲（> 0）：吸收
        if not skip_shield_calc:
            holder = s if s is not None else p
            if holder.shield < 0:
                fragile = -holder.shield
                ev.amount += fragile
                ev.fragile = fragile  # 记账：破甲受伤即消耗，on_damage 时目标已无破甲
                self._change_shield(ev.victim, holder.shield, "破甲计算", kind="fragile")
                self._log(f"破甲使本次伤害增加 {fragile} 点")
            elif holder.shield > 0:
                absorbed = min(holder.shield, ev.amount)
                ev.amount -= absorbed
                self._change_shield(ev.victim, -absorbed, "护甲计算")
            if ev.amount <= 0:
                return  # 护甲完全吸收：终止结算
        # 批次 5：护甲计算后（伤害转移/改为非伤害能力锚点；优先级分层见 EffectBlock.priority）
        self._emit_damage_batch("on_after_shield", ev)
        if ev.amount <= 0:
            return  # 改非伤害类效果（优先级 1）把余量归零：原伤害事件终止，转移不再处理
        # 伤害转移（血蝠之盾"下一次将受到的伤害改由其牌手承受"，ext["damage_redirects"]
        # 挂账）：挂点 = 护甲计算后批次优先级 2（rules.md:218 ②——①类监听者
        # （on_after_shield）先结算再转移）：消耗一层挂账，以受伤者的牌手为受伤者、
        # 护甲计算后余量为伤害值重新结算该伤害事件。新事件语义（定案"转移链"）：
        # 等量、同来源、同原因、同属性（无[贯通]），从"护甲计算前0"（on_before_shield）
        # 开始结算——穿刺/贯通修正/翻倍修饰不再判定（免疫判定后移至本批次优先级 3，
        # 新事件对最终受伤者照常判定）；转化与气绝保护仍先行。
        # 挂账消耗式（pop 一层）天然有界，不占用转移链身份（链照旧继承）；伤害类别不限；
        # 原受伤者的屏障不因持挂账而消耗，其护甲先参与计算
        if s is not None and s.ext.get("damage_redirects"):
            s.ext["damage_redirects"].pop(0)
            self._log(f"{self.db.shikigami[s.id].name} 将受到的伤害改由 {p.name} 承受")
            dq.appendleft(_DamageEvent(source=ev.source,
                                       victim=Ref(player=ev.victim.player),
                                       amount=ev.amount, kind=ev.kind,
                                       spell=ev.spell, converted=ev.converted,
                                       start="pre_shield_0",
                                       redirect_chain=ev.redirect_chain,
                                       card=ev.card))
            return
        # 免疫判定（定案"免疫只看最终受伤者"：挂点 = 护甲计算后批次**优先级 3**——
        # 改非伤害（优先级 1）/伤害转移（优先级 2，含挂账转移）全部结算完、伤害事件
        # 未被终止/归零之后，对**最终受伤者**判定其全部免疫条目；屏障/护甲计算/
        # 贯通修正均先于免疫参与计算。免疫则伤害归零终止。普通事件与转移新事件
        # （start="pre_shield_0"，从护甲计算前0 进入）均走到此点——转移后的伤害可被
        # 最终受伤者免疫拦截（血蝠之盾→牌手免疫场景适用）
        # 作用域战斗伤害免疫：仅免疫 combat/counter，且须命中授予时指定的作用域
        if ev.kind in ("combat", "counter") and s is not None and self._combat_immune(s):
            self._log(f"{self.db.shikigami[s.id].name} 免疫了本次战斗伤害")
            return
        # 非战斗伤害免疫（觉醒·山童类；条目 {"kind": "effect", "from": "enemy"}）
        if ev.kind == "effect" and s is not None and self._effect_immune(s, ev):
            self._log(f"{self.db.shikigami[s.id].name} 免疫了本次伤害")
            return
        # 破甲来源免疫（霸主；条目 {"kind": "fragile_source"}）：伤害来源为当前持有
        # 破甲的敌方式神时免疫（伤害类别不限；来源须为式神，牌手来源/无来源不免）
        if s is not None and self._fragile_source_immune(s, ev):
            self._log(f"{self.db.shikigami[s.id].name} 免疫了破甲式神的伤害")
            return
        # 牌手级伤害免疫（舍生"本回合你免疫所有伤害"；PlayerState.immunities 按回合号过期）
        if s is None and self._player_immune(p, ev):
            self._log(f"{p.name} 免疫了本次伤害")
            return
        # 批次 6：扣减生命前（已被贯通修正提前结算则跳过）；此刻起视为造成/受到过伤害，伤害值锁定
        if not skip_before_health:
            self._emit_damage_batch("on_before_health", ev)
        if ev.amount <= 0:
            return
        # [暴击] 时机锚点（扣减生命前2；terminology.md 登记）：义道——本战斗牌发起的
        # 战斗中，攻击者本人（ev.source == 登记攻击者）对具有破甲的式神造成的战斗伤害
        # 翻倍（kind=combat 限攻击事件，反击不翻倍；嵌套/插入战斗按战斗 id 精确匹配
        # 不继承；贯通路径破甲未被消耗按当前 shield<0 判定，非贯通按本事件已消耗的
        # ev.fragile 判定；贯通修正提前结算批次 6 的路径同样走到此点）
        if (s is not None and ev.kind == "combat" and self._battle_stack
                and (s.shield < 0 or ev.fragile > 0)):
            atk = self._battle_double_fragile.get(self._battle_stack[-1])
            if atk is not None and ev.source == atk:
                ev.amount *= 2
                self._log(f"义道：本次伤害翻倍至 {ev.amount} 点")
        # [暴击] 关键字本体（critical，破魔符"对其攻击的式神获得[暴击]"通道授予）：
        # 攻击事件（kind=combat；反击不翻倍）来源式神持有时战斗伤害 ×2，与义道
        # 破甲双倍同挂点叠乘；限原始事件（start="full"——贯通溢出/转移衍生的新事件
        # 不再二次翻倍，溢出量按翻倍前口径随义道锚点一致）
        if (ev.kind == "combat" and ev.start == "full" and ev.source is not None
                and ev.source.shikigami is not None):
            src_s = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
            if self._has_keyword(src_s, "critical"):
                ev.amount *= 2
                self._log(f"暴击：本次伤害翻倍至 {ev.amount} 点")
        # 批次 7：合并——队列中 (来源, 受伤者, 原因) 均相同的伤害事件合并进最前者
        for other in list(dq):
            if other.source == ev.source and other.victim == ev.victim \
                    and other.kind == ev.kind and other.spell == ev.spell:
                ev.amount += other.amount
                dq.remove(other)
        # 批次 8：扣减生命
        if s is not None:
            # 庇佑（消耗型关键字）：抵消一次敌方来源的法术伤害（法术牌效果伤害；
            # 非战斗伤害 ≠ 法术伤害——白狼基础能力、觉醒·入阵歌等能力伤害不抵消，
            # 答复(7)），抵消后失去；灵咒抵消半侧随灵咒机制引入（docs/rules.md 锚点）。
            # 置于扣减生命前——被护甲完全吸收/屏障归零的伤害不消耗庇佑
            if (ev.kind == "effect" and ev.spell and ev.source is not None
                    and ev.source.player != ev.victim.player
                    and "blessing" in s.one_shot_keywords):
                s.one_shot_keywords.remove("blessing")
                self._log(f"{self.db.shikigami[s.id].name} 的【庇佑】抵消了本次伤害")
                return
            # 不屈：生命 > 1 且伤害 >= 当前生命 → 保留 1 点生命，消耗全部一次性不屈
            # （生命 = 1 时不触发；持续/永久不屈不移除，回血后可再次触发）
            if ev.amount >= s.health > 1 and self._has_keyword(s, "unyielding"):
                ev.amount = s.health - 1
                s.one_shot_keywords[:] = [k for k in s.one_shot_keywords if k != "unyielding"]
                self._log(f"{self.db.shikigami[s.id].name} 的【不屈】生效，保留 1 点生命")
            # 狂啸"本回合生命不会降到 1 以下"（ext["min_health_turn"]，半回合作用域）：
            # 伤害压到至多 当前生命-1；生命已为 1 时不再扣减（同护甲完全吸收提前终止）
            if s.ext.get("min_health_turn"):
                cap = max(0, s.health - 1)
                if ev.amount > cap:
                    ev.amount = cap
                    self._log(f"{self.db.shikigami[s.id].name} 的生命保持 1（狂啸）")
                if ev.amount <= 0:
                    return
            s.health -= ev.amount
            ev.dealt = ev.amount  # 实际造成：扣减生命批次锁定（巨浪统计口径）
            self._account_yaohu_damage(ev)  # 妖狐伤害计数（每次伤害事件计 1）
            self._mark_dealt_damage_turn(ev)  # 记仇过滤键记账（dealt_damage_turn）
            self._account_quest_damage(ev)  # 委托账本：造成伤害/非战斗伤害
            # 本回合所受伤害之和记账（百鬼夜行 X；半回合作用域，回合开始清除）
            s.ext["damage_taken_turn"] = s.ext.get("damage_taken_turn", 0) + ev.amount
            self._settle(f"【伤害】{self.db.shikigami[s.id].name} 受到 {ev.amount} 点伤害"
                         f"（生命 {s.health + ev.amount}→{s.health}）")
            # 不再写 _log 孪生行：数值明细归 settle 通道，避免联机端双通道重复打印
            if s.health <= 0:
                s.dying = True  # 先标记濒死，再按 victims 延时生成气绝事件（thoughts.txt 濒死定义）
            victims.append((ev.victim, ev.source, "战斗" if ev.kind in ("combat", "counter") else "伤害"))
            # 必杀：来源式神持 lethal（含斩型"本次攻击获得[必杀]"经 next_battle 统一
            # 通道授予的关键字实例——范围与免疫一致：该次战斗全程含嵌套战斗，外层战斗
            # 终止点核销；维护者改判），且本次伤害实际造成（走到扣减生命即已造成）——
            # 令受伤者在该次伤害事件后延时结算气绝事件，不提前标濒死；与伤害本身
            # 导致的气绝并行结算（同入 victims 队列，check_defeated 幂等去重）
            if ev.source is not None and ev.source.shikigami is not None:
                src0 = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
                if self._has_keyword(src0, "lethal"):
                    victims.append((ev.victim, ev.source, "必杀"))
            # 驱魔符标记（ext["defeat_on_damage"]，半回合作用域"本回合受到伤害时使其
            # 气绝"）：伤害实际造成即延时结算气绝（同必杀通道——check_defeated 幂等）
            if s.ext.get("defeat_on_damage"):
                victims.append((ev.victim, ev.source, "驱魔符"))
            if (self._affected_stack
                    and ev.victim.player != self._affected_stack[-1]["controller"]
                    and ev.victim not in self._affected_stack[-1]["refs"]):
                # 出牌效果实际伤害过的敌方式神（答复(7)：己方式神/牌手不计，去重）
                self._affected_stack[-1]["refs"].append(ev.victim)
            self._queue_lifesteal(ev)  # 伤害后（延时，优先级 1 锚点）：吸血生成恢复生命事件
            self.emit("on_damage", victim=ev.victim, amount=ev.amount, source=ev.source,
                      kind=ev.kind, fragile=ev.fragile,
                      battle=self._battle_stack[-1] if self._battle_stack else None)
        else:
            # 铃鹿山的秘宝（幻境实体关键字 health_floor_one）：生命不会降到 1 以下——
            # 扣减生命前钳制伤害量（超出部分免除，不走"扣减生命"即未实际造成）
            if any("health_floor_one" in f.keywords for f in p.fields):
                ev.amount = min(ev.amount, p.health - 1)
                if ev.amount <= 0:
                    return
            p.health -= ev.amount
            ev.dealt = ev.amount  # 实际造成：扣减生命批次锁定（巨浪统计口径）
            if ev.source is not None and ev.source.player == ev.victim.player:
                p.ext["self_damage_taken"] = True  # 本局受到过己方伤害记账
                # （彼岸花基础/觉醒"每当你受到己方伤害时"的条件谓词见 source_side；
                # 死亡之花[增强]"本局游戏你受到过一次己方伤害"读此键）
            self._account_yaohu_damage(ev)  # 妖狐伤害计数（每次伤害事件计 1）
            self._mark_dealt_damage_turn(ev)  # 记仇过滤键记账（dealt_damage_turn）
            self._account_quest_damage(ev)  # 委托账本：造成伤害/非战斗伤害
            self._settle(f"【伤害】{p.name} 受到 {ev.amount} 点伤害"
                         f"（生命 {p.health + ev.amount}→{p.health}）")
            # 幻境耐久扣减（规范第三条：扣减生命完成后立即，早于"受到伤害后"延时时机）
            self._field_intensity_loss(ev.victim.player, ev.amount, ev.source)
            self._queue_lifesteal(ev)  # 吸血对牌手伤害同样生效
            self.emit("on_player_damaged", player=ev.victim.player, amount=ev.amount,
                      source=ev.source, kind=ev.kind,
                      battle=self._battle_stack[-1] if self._battle_stack else None)
            if p.health <= 0:
                # 牌手气绝 → "待结束"：已入队的触发能力不再执行，此后非系统操作不再触发
                self._set_pending_end(loser=ev.victim.player, defeat=True)

    def _account_yaohu_damage(self, ev: _DamageEvent) -> None:
        """妖狐伤害计数（契约 §3.6）：伤害事件来源 = 妖狐且实际造成（走到扣减生命批次）
        时，其控制者牌手 ext["yaohu_damage_count"] +1——每次伤害事件计 1（狂风刃卷增强读数）。"""
        if ev.source is None or ev.source.shikigami is None or ev.dealt <= 0:
            return
        src = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
        if src.id != _YAOHU_SHIKIGAMI:
            return
        pl = self.state.players[ev.source.player]
        pl.ext["yaohu_damage_count"] = pl.ext.get("yaohu_damage_count", 0) + 1

    def _mark_dealt_damage_turn(self, ev: _DamageEvent) -> None:
        """记仇记账（TargetSpec 过滤键 dealt_damage_turn）：伤害实际造成（扣减生命批次
        锁定）时给来源式神打半回合标记——本回合造成过伤害（任意伤害类型/受伤者）；
        回合开始双方清除（damage_taken_turn 同通道）。"""
        if ev.source is None or ev.source.shikigami is None:
            return
        src = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
        src.ext["dealt_damage_turn"] = True

    def _queue_lifesteal(self, ev: _DamageEvent) -> None:
        """关键字"吸血"（rules.md ch5 批次 10①；thoughts.txt 答复 (5)）：
        来源式神具有 lifesteal 时，生成"以其控制者牌手为执行者、治疗量 = 该次伤害值"
        的恢复生命事件——延时、优先级 1 锚点：以合成 _Pending 入队（先于同批延时能力结算），
        治疗走 Game.heal 管线。来源式神在结算前气绝不影响（先触发后执行）。

        吸血判定除来源式神关键字外也读来源卡牌实例关键字（猩红之月"你的法术牌获得
        [吸血]"——card_aura 授予的关键字经 _card_keywords 读取时求值，法术牌伤害
        结算时携带 lifesteal 生效）；两处命中只恢复一次（[吸血]自身不叠加）。
        """
        if ev.source is None or ev.source.shikigami is None or ev.amount <= 0:
            return
        src = self.state.players[ev.source.player].shikigami[ev.source.shikigami]
        has = self._has_keyword(src, "lifesteal")
        if not has and ev.card is not None:
            cdef = self.db.cards[ev.card.id]
            has = "lifesteal" in self._card_keywords(
                self.state.players[ev.source.player], cdef, ev.card)
        if not has:
            return
        block = EffectBlock(steps=[Step(
            op="heal", amount=ev.amount, target=TargetSpec(kind="all", pool="self_player"))])
        self.queue.append(_Pending(block, ExecContext(
            controller=ev.source.player, source=ev.source, is_ability=True)))

    def _player_immune(self, p: PlayerState, ev: _DamageEvent) -> bool:
        """牌手伤害免疫（舍生"本回合你免疫所有伤害"）：条目 {"kind": "all", "turn": 回合号}；
        scope=turn 按回合号比对过期（条目无需清理）。"""
        for e in p.immunities:
            if e.get("kind") == "all" and ("turn" not in e or e["turn"] == self.state.turn):
                return True
        return False

    def _combat_immune(self, s: ShikigamiState) -> bool:
        """式神在当前战斗上下文中是否免疫战斗伤害（作用域由授予效果指定）。

        战斗作用域按战斗实例比对；grant_immunity(scope="turn") 的"本回合"免疫
        按回合号比对（跨回合自然过期）。kind="all"（桃红簇簇）同样免疫战斗伤害；
        scope="once" 条目无过期键、命中任意一类伤害即免疫一次并消耗。"""
        if not self._battle_stack:
            return False
        current = self._battle_stack[-1]
        for e in list(s.immunities):
            if e.get("kind") not in ("combat_damage", "all"):
                continue
            if e.get("turn") == self.state.turn:
                return True
            if e.get("battle") == current or (e.get("nested") and e.get("battle") in self._battle_stack):
                return True
            if e.get("once"):
                s.immunities.remove(e)  # 消耗式免疫：命中即移除
                return True
        return False

    def _fragile_source_immune(self, s: ShikigamiState, ev: _DamageEvent) -> bool:
        """霸主：免疫当前持有破甲的敌方式神造成的伤害（条目 {"kind": "fragile_source"}）。

        来源须为敌方式神且其当前 shield < 0；无来源/牌手来源/己方来源不免疫。
        伤害类别不限（战斗/反击/效果皆可免疫）。"""
        if not any(e.get("kind") == "fragile_source" for e in s.immunities):
            return False
        src = ev.source
        if src is None or src.shikigami is None or src.player == ev.victim.player:
            return False
        return self.state.players[src.player].shikigami[src.shikigami].shield < 0

    def _effect_immune(self, s: ShikigamiState, ev: _DamageEvent) -> bool:
        """式神是否免疫该次非战斗伤害（条目 {"kind": "effect", "from": "enemy"|None}）。

        from="enemy"：伤害来源属于敌方才免疫（无来源 ev.source=None 或己方来源不免疫）；
        scope="perm" 条目无过期键，随气绝清除（immunities 气绝清空）。
        kind="all"（桃红簇簇）同样免疫非战斗伤害；scope="once" 条目命中即消耗。
        """
        for e in list(s.immunities):
            if e.get("kind") not in ("effect", "all"):
                continue
            if "battle" in e:
                # 战斗作用域条目（battle_immunity kind="all"，二帚流）：仅本战斗内有效
                # （nested 覆盖本战斗内的嵌套战斗，仿 _combat_immune 的战斗比对）
                current = self._battle_stack[-1] if self._battle_stack else None
                if e["battle"] != current and not (
                        e.get("nested") and e["battle"] in self._battle_stack):
                    continue
            if e.get("from") == "enemy" and (
                    ev.source is None or ev.source.player == ev.victim.player):
                continue  # 来源缺失或属于己方：不免疫
            if e.get("once"):
                s.immunities.remove(e)  # 消耗式免疫：命中即移除
            return True
        return False

    def _account_kill(self, source: Ref | None, ref: Ref, s: ShikigamiState) -> None:
        """击杀账本统一记账 + 委托 enemy_defeat 计数（check_defeated 正常流程与
        棺材被击破还原路径共用；s = 气绝者当前状态）。

        击杀账本（规则设计评审⑩，口径与原卡牌自计数触发器等价：仅统计有来源的
        消灭；按来源归属牌手分桶——镜像对局敌方同名式神击杀互不计入；伤害转移等
        消灭己方式神的场景按原版同样计入来源方）；牌手级"结附灵咒击杀加成"规则
        （觉醒·大岳丸使用时赋予，ext inv_bonus_on_kill 条目 {"inv": 灵咒名,
        "add": n}，可叠加、不随大岳丸气绝失效）：来源式神结附该灵咒且击杀敌方
        式神时，其身上该灵咒条目的 bonus += add（同源唯一性替换时 bonus 由新条目
        继承、气绝移除即重置——继承/重置语义在 attach/detach 通道自然成立）。
        委托账本：敌方式神气绝计数（非召唤物气绝即计，不限来源；召唤物离场不计；
        多事多忙不扩域——shareable=False）。"""
        if source is not None:
            sp = self.state.players[source.player]
            sp.kill_total += 1
            if source.shikigami is not None:
                sid = sp.shikigami[source.shikigami].id  # 来源实体的当前数据 id
                sp.kill_by[sid] = sp.kill_by.get(sid, 0) + 1
                rules = sp.ext.get("inv_bonus_on_kill")
                if rules and ref.player != source.player and s.kind != "summon":
                    killer = sp.shikigami[source.shikigami]
                    for e in killer.invocations:
                        for r in rules:
                            if e["name"] == r["inv"]:
                                e["bonus"] = int(e.get("bonus", 0)) + int(r["add"])
                                self._log(f"灵咒【{e['name']}】效果 +{int(r['add'])}"
                                          f"（击杀加成，现 bonus={e['bonus']}）")
                    self._refresh_invocation_mods(source.player)
        if s.kind != "summon":
            self._quest_tick(1 - ref.player, "enemy_defeat", shareable=False)

    def check_defeated(self, ref: Ref, source: Ref | None = None, reason: str | None = None) -> None:
        """生成并结算式神气绝事件（要素：来源、气绝者、原因）。

        时机分层（裁决(9)，docs/rules.md 第七章）：气绝前/消灭前1（即时
        on_before_defeat——大部分能力/响应挂此时机：射怪鸟事/破碎之音/不灭之火/
        不祥之刃/判官能力等）→ 气绝前/消灭前2（仅解除变形 + 替身[未引入]）→
        消灭形态牌 → 移除所有非永久 buff（临时修正/护甲）→ 非召唤物获得倒计时 3：
        复活并移动至准备区（召唤物直接离场）→ 气绝后/消灭后（延时时机，不再细分
        优先级；跳跳哥哥"将气绝时变为棺材"的变形事件与棺击增益挂此时机）。
        击杀标记等时点批次待相应机制引入（见 docs/rules.md）。
        """
        s = self.state.players[ref.player].shikigami[ref.shikigami]
        if reason in ("必杀", "驱魔符") and not s.defeated and s.health > 0:
            # 必杀/驱魔符的延时气绝：伤害本身未致死（未标濒死）时令受伤者气绝
            s.health = 0
            self._log(f"{self.db.shikigami[s.id].name} 因【{reason}】而气绝")
        if s.defeated or s.health > 0:
            return
        if (source is not None and source.shikigami is not None
                and self._active_play_marker is not None
                and not self._active_play_marker.get("nullified")):
            # 反制钩子（罗城门"若击杀式神，则无效化其使用的牌"）：击杀者匹配挂账
            # watch 且有进行中的出牌 → 置 nullified（同魔音扰心通道），条目消耗
            for w in list(self._counter_watches):
                if w["attacker"] == source:
                    self._counter_watches.remove(w)
                    self._active_play_marker["nullified"] = True
                    self._log(f"反制触发：{self.db.shikigami[self.state.players[source.player].shikigami[source.shikigami].id].name}"
                              f" 击杀了 {self.db.shikigami[s.id].name}")
                    break
        # 气绝前/消灭前 1（rules.md 第七章 step 1，即时时机；射怪鸟事类响应挂此时机）
        self.emit("on_before_defeat", victim=ref, source=source, reason=reason,
                  battle=self._battle_stack[-1] if self._battle_stack else None)
        if s.defeated:
            return  # 气绝前 1 的插入结算中已被其它事件标记气绝
        if s.coffin_origin is not None:
            # 棺材被击杀（04 沧海刀鸣，维护者定案(8)）：还原为气绝的原式神
            # （coffin_origin 快照本就是"气绝结算完成后"baseline——原式神变形前的
            # 临时数据不带回，现状口径保持），**会有气绝事件、计入击杀账本**；
            # 棺材移除本身不复活。"气绝时变成棺材"的入口路径（to_coffin）维持
            # 原口径——其气绝事件/账本已在入棺时按原式神结算过一次。
            owner0 = self.state.players[ref.player]
            was_in_combat = owner0.combat_index == ref.shikigami
            if was_in_combat:
                owner0.combat_index = None  # 棺材移除：战斗区让出
            original = ShikigamiState.model_validate(s.coffin_origin)
            original.revive_countdown = self.config.revive_countdown
            owner0.shikigami[ref.shikigami] = original
            self._settle(f"【气绝】{self.db.shikigami[s.id].name} 被击破（棺材）："
                         f"{self.db.shikigami[original.id].name} 保持气绝"
                         f"（复活倒计时 {original.revive_countdown}）")
            self._log(f"{self.db.shikigami[s.id].name} 被击破，"
                      f"{self.db.shikigami[original.id].name} 保持气绝")
            self._account_kill(source, ref, original)
            self.emit("on_shikigami_defeated", victim=ref, source=source,
                      reason=reason, in_combat=was_in_combat, summon=False,
                      from_coffin=True,
                      battle=self._battle_stack[-1] if self._battle_stack else None)
            return
        if s.transform_origin is not None:
            # 变形物"气绝前2"（契约 §2）：解除变形、原式神以已气绝状态进场——快照还原
            # 到原座次后继续正常气绝流程（形态消灭/非永久修正清除/复活倒计时/气绝事件）；
            # 式神替换物（replace，无快照）天然跳过——替换物气绝即气绝，复活仍为替换物
            restored = ShikigamiState.model_validate(s.transform_origin)
            restored.health = 0
            restored.dying = False
            self.state.players[ref.player].shikigami[ref.shikigami] = restored
            self._log(f"{self.db.shikigami[s.id].name} 的变形解除，"
                      f"{self.db.shikigami[restored.id].name} 以已气绝状态进场")
            s = restored
        owner = self.state.players[ref.player]
        in_combat = owner.combat_index == ref.shikigami  # 气绝时是否在战斗区（迁怒/罗生门条件）
        # 气绝流程 step 3（rules.md 第七章）：先消灭形态牌——此时能力尚未离场（step 6），
        # 一目连类"形态离场时触发"能力仍会收集（先触发后执行，结算时不再复查持有者状态）
        # 平和猫又屋（tags revive_on_defeat）：气绝结算完成后复活——旗标在形态消灭前捕获
        revive_flag = (s.form is not None
                       and "revive_on_defeat" in self.db.cards[s.form.id].tags)
        # 棺材替换旗标（04 沧海刀鸣）同样在形态消灭前捕获：
        # - ext["coffin_on_defeat"]（不弃"本回合气绝时替换为'棺材'"，值 = 棺材实体 id；
        #   响应"当跳跳哥哥将气绝时自动对其使用"在上方 on_before_defeat 即时批次写入）
        # - 形态 tags `coffin_on_defeat:<实体id>`（罡身阵"跳跳哥哥气绝时改为替换为'棺材'"）
        coffin_into = s.ext.get("coffin_on_defeat")
        if coffin_into is None and s.form is not None:
            for tag in self.db.cards[s.form.id].tags:
                if tag.startswith("coffin_on_defeat:"):
                    coffin_into = int(tag.split(":", 1)[1])
                    break
        if s.form is not None:
            self._destroy_form(owner, ref.shikigami, reason="defeat")
        s.defeated = True
        s.dying = False  # 濒死标记在气绝时清除
        self._clear_countdown(s)  # 气绝清除倒计时能力（大天狗记录的法术随之丢失，复活后不再具有）
        self._clear_ability_card_auras(owner, ref.player, ref.shikigami)  # 能力离场：其授予的 ability 光环移除
        # 气绝清除的 ext 键（EXT_KEYS 登记表 on_defeat 时机：recorded_card 大天狗记录、
        # power_zero 力量覆写、next_battle_keywords/immunities 本次战斗授予挂账、
        # damage_redirects 血蝠之盾类伤害转移挂账）
        self._clear_ext(s, CLEAR_ON_DEFEAT)
        s.shield = 0
        # 灵咒快照（气绝移除前）：on_shikigami_defeated payload 携带
        # victim_invocations（灵咒名列表，按条目重复——无尽蛊"结附'蛊蚀'的敌方式神
        # 气绝时"条件、食魂蛊"其上每有一个'蛊蚀'"计数读取点；魔蛊毒爆转移数量同源）
        inv_snapshot = [e["name"] for e in s.invocations]
        self._detach_invocations(s, reason="气绝")  # 灵咒随气绝移除（身材光环层随之失效）
        s.temp_power = 0  # 临时修正气绝时清除（复活只保留永久修正）
        s.temp_health = 0
        s.keywords.clear()  # 持续/一次性关键字与免疫条目气绝时清除；永久关键字保留（复活自动重新获得）
        s.one_shot_keywords.clear()
        s.immunities.clear()
        s.attack_buffs.clear()  # 攻击后到期强化挂账随临时修正一并清空（keep_shield/awakened 保留）
        s.delayed.clear()  # 绑定式神的一次性延迟能力气绝时消失（会；变形离场保留——快照随 transform_origin 还原）
        s.stuns.clear()  # 眩晕随气绝清除（复活后需重新施加）
        s.health = 0
        name = self.db.shikigami[s.id].name
        if s.kind == "summon":
            # 召唤物死亡即离场：不进气绝复活流程
            self._settle(f"【气绝】{name} 离场（召唤物）")
            self._despawn(owner, ref.shikigami)
        else:
            if owner.combat_index == ref.shikigami:
                owner.combat_index = None  # 气绝者移动至准备区
            s.revive_countdown = self.config.revive_countdown
            s.ext["defeated_in_combat"] = in_combat  # 本次气绝位置记账
            # （to_coffin keep_combat 消费：棺封对战斗区式神 = 棺材进其战斗区；
            # 气绝替换路径不读——棺材落准备区）
            self._settle(f"【气绝】{name} 气绝（复活倒计时 {s.revive_countdown}）")
            # 不写 _log 孪生行（"X 气绝"）：归 settle 通道，避免双通道重复
        # 击杀账本与委托计数（含牌手级 inv_bonus_on_kill 结算；棺材被击破路径共用）
        self._account_kill(source, ref, s)
        self.emit("on_shikigami_defeated", victim=ref, source=source, reason=reason,
                  in_combat=in_combat, summon=(s.kind == "summon"),
                  victim_invocations=inv_snapshot,
                  battle=self._battle_stack[-1] if self._battle_stack else None)
        # 魔蛊毒爆转移（牌手级半回合登记 ext["inv_transfer_on_defeat"]，裁决13/14）：
        # 视作赋予登记目标（敌方式神）的一次性能力——其本回合气绝时触发（触发者=
        # 该敌方式神，来源侧取气绝者所属牌手：不吃登记方 inv_attach_bonus 增幅、
        # 严格等量），将移除前快照计数（不论结附来源敌我）的同名灵咒一次性结附于
        # 随机另一名合法敌方式神（非选择目标：随机取；帷幕可结附、气绝/未在场不可；
        # 无合法目标则不转移）
        for tpi, tpl in enumerate(self.state.players):
            tr = tpl.ext.get("inv_transfer_on_defeat")
            if not tr or tr.get("victim") != [ref.player, ref.shikigami]:
                continue
            tpl.ext.pop("inv_transfer_on_defeat")  # 一次性：触发即消费
            n = inv_snapshot.count(tr["inv"])
            if n <= 0:
                continue
            cands = [i for i, es in enumerate(
                self.state.players[ref.player].shikigami)
                if i != ref.shikigami and es.in_play]
            if not cands:
                continue
            dst = Ref(player=ref.player, shikigami=self.rng.choice(cands))
            dst_name = self.db.shikigami[
                self.state.players[dst.player].shikigami[dst.shikigami].id].name
            self._log(f"灵咒【{tr['inv']}】转移（{n} 个 → {dst_name}）")
            self.attach_invocation(tr["inv"], player=ref.player, source=ref,
                                   target=dst, count=n)
        # 平和猫又屋：气绝结算（含气绝后时机）完成后复活（形态已消灭、倒计时已重置，
        # 复活走 _revive 完整流程——回满生命/重注册倒计时能力/发 on_shikigami_revived）
        if revive_flag and s.defeated and not s.despawned:
            self._revive(owner, ref.player, ref.shikigami, reason="平和猫又屋")
        # 棺材替换（不弃 ext 旗标 / 罡身阵形态 tag）——裁决(9)：跳跳哥哥各"将气绝时
        # 变为棺材"效果 = 气绝前1 触发（旗标/形态 tag 在上方气绝结算前捕获），在该
        # 气绝事件的"气绝后/消灭后"延时时机生成变形事件——不入队内联替换，改为把
        # to_coffin 追加为本气绝事件队列的收尾待结算项（与棺葬 on_shikigami_defeated
        # 能力块同层；若其间被气绝后能力复活，to_coffin 对未气绝目标天然空操作）
        if coffin_into is not None and s.defeated and not s.despawned:
            from db.schema import EffectBlock as _EB, Step as _St
            blk = _EB(when="on_shikigami_defeated", steps=[_St.model_validate(
                {"op": "to_coffin", "into": int(coffin_into),
                 "target": {"kind": "context", "key": "victim"}})])
            self.queue.append(_Pending(blk, ExecContext(
                controller=ref.player, source=ref,
                event={"name": "on_shikigami_defeated", "victim": ref,
                       "player": ref.player})))

    # ==================== 幻境（card_type="field"）管线 ====================

    def _summon_field(self, pi: int, card: CardInstance | None, cdef: CardDef,
                        source: Ref | None, reason: str = "使用",
                        intensity_override: int | None = None) -> None:
        """"召唤幻境"事件（要素：来源、原因、要召唤的幻境——规范第二条）：来源的所属
        牌手将该幻境添加至自身幻境队列末尾（field_front 标记者置于队首），发
        "召唤幻境后"（延时 on_summon_field）。
        幻境实体耐久取值链（定案(15)）：intensity_override 指定值（觉醒·辉夜姬增强
        "耐久都为1"）> 幻境牌 intensity 标注值（正整数必填；使用事件/不指定耐久的
        效果召唤同取牌面默认）+ 召唤牌实例 mods.intensity_boost（五道难题"使其获得
        5耐久"）。card=None 为凭空直接召唤（summon_field 动作——残阳无影/竹取物语类，
        不经使用事件）。
        召唤一律新建实体：辉夜姬"同时只能存在一个"的叠加是她基础/觉醒能力的效果
        （"召唤幻境后"延时时机经 field_merge 合并，定案(6)），不在召唤事件内联处理。"""
        if cdef.intensity is None or cdef.intensity <= 0:
            raise ValueError(f"幻境牌【{cdef.name}】缺少正整数耐久（intensity）")
        p = self.state.players[pi]
        boost = int(card.mods.get("intensity_boost", 0)) if card is not None else 0
        intensity = (int(intensity_override) if intensity_override is not None
                     else cdef.intensity) + boost
        if cdef.id not in p.ext.setdefault("field_summon_ids", []):
            p.ext["field_summon_ids"].append(cdef.id)  # 本局召唤过的幻境牌 id 记账
            # （觉醒·辉夜姬增强"已召唤五个不同的辉夜姬幻境"读取；叠加召唤同记）
        ph = FieldState(card_id=cdef.id, intensity=intensity,
                        shikigami=cdef.shikigami,
                        mods=dict(card.mods) if card is not None else {},
                        keywords=list(cdef.field_keywords))
        if cdef.field_front:
            p.fields.insert(0, ph)
        else:
            p.fields.append(ph)
        idx = p.fields.index(ph)
        self._log(f"{p.name} 召唤了幻境【{cdef.name}】（耐久 {ph.intensity}）")
        self._settle(f"【幻境】{p.name} 召唤幻境【{cdef.name}】"
                     f"（耐久 {ph.intensity}，队列第 {idx + 1} 位）")
        self.emit("on_summon_field", player=pi, field=idx, card_id=cdef.id,
                  source=source, reason=reason)

    def _merge_same_shikigami_fields(self, pi: int, sid: int, *,
                                     merge_abilities: bool,
                                     source: Ref | None = None) -> None:
        """辉夜姬基础/觉醒能力的叠加合并（定案(6)，field_merge 动作经此执行）：
        其所属牌手幻境队列中存在多个她的幻境时——仅保留队列中**最后一个**，将其耐久
        **设置为**所有她的幻境的耐久总和（差量走 _change_field_intensity 管线，触发
        耐久变化事件）；merge_abilities（已觉醒）时把其他**不同名**幻境的能力块按幻境
        牌 id 去重添加到保留幻境 extra_abilities（每种同名幻境的能力不叠加；
        mods.merged_ability_ids 记账，此前合并携带的 id 随来源幻境传递）；
        然后**消灭**其他她的幻境（归零走完整消灭事件流，"被消灭时"能力照常结算）。"""
        p = self.state.players[pi]
        idxs = [i for i, ph in enumerate(p.fields) if ph.shikigami == sid]
        if len(idxs) < 2:
            return
        keep_idx = idxs[-1]
        kept = p.fields[keep_idx]
        total = sum(p.fields[i].intensity for i in idxs)
        if merge_abilities:
            have = {kept.card_id, *kept.mods.get("merged_ability_ids", ())}
            for i in idxs[:-1]:
                other = p.fields[i]
                origins = ({other.card_id, *other.mods.get("merged_ability_ids", ())}
                           - have)
                for cid in sorted(origins):
                    kept.extra_abilities.extend(self.db.cards[cid].abilities)
                have |= origins
            kept.mods["merged_ability_ids"] = sorted(have - {kept.card_id})
        names = "、".join(f"【{self.db.cards[p.fields[i].card_id].name}】"
                          for i in idxs[:-1])
        self._log(f"{p.name} 的幻境【{self.db.cards[kept.card_id].name}】"
                  f"叠加了{names}（耐久设置为 {total}）")
        delta = total - kept.intensity
        if delta:
            self._change_field_intensity(pi, keep_idx, delta, source, "耐久叠加")
        for i in idxs[:-1]:
            ph = p.fields[i]
            self._change_field_intensity(pi, i, -ph.intensity, source, "叠加消灭")

    def _field_source(self, pi: int, ph: FieldState) -> Ref | None:
        """幻境能力/伤害的来源归属（规范"零"条）：该在场幻境有所属式神且该式神在场
        → 该式神；否则为无来源（None）。"""
        if ph.shikigami is None:
            return None
        p = self.state.players[pi]
        for si, s in enumerate(p.shikigami):
            if s.id == ph.shikigami and s.in_play:
                return Ref(player=pi, shikigami=si)
        return None

    def _change_field_intensity(self, pi: int, idx: int, amount: int,
                                   source: Ref | None, reason: str) -> None:
        """幻境耐久变化事件流程（规范第四条）：变化前（即时 on_before_field_
        intensity，监听者可改可变 change["amount"]）→ 变化量为负则修正为
        max(变化量, -剩余耐久) → 耐久 += 变化量（下限 0）→ 耐久 0 生成（延时的）
        幻境消灭事件 → 变化后（延时 on_field_intensity_changed）。变化量 0 终止。"""
        p = self.state.players[pi]
        ph = p.fields[idx]
        change = {"amount": amount}
        self.emit("on_before_field_intensity", player=pi, field=idx,
                  card_id=ph.card_id, change=change, old=ph.intensity,
                  source=source, reason=reason)
        amt = int(change["amount"])
        if amt < 0:
            amt = max(amt, -ph.intensity)  # 至多降为 0（规范"零"条）
        if amt == 0:
            return
        old = ph.intensity
        ph.intensity = max(0, ph.intensity + amt)
        self._settle(f"【幻境】{p.name} 的幻境【{self.db.cards[ph.card_id].name}】"
                     f"耐久 {old}→{ph.intensity}")
        if ph.intensity == 0:
            # 生成（延时的）幻境消灭事件："消灭前"监听器先入队（触发/执行时幻境仍在
            # 队列中），移除与"消灭后"由 field_destroy 待结算项执行
            self.emit("on_before_field_destroy", player=pi, field=idx,
                      card_id=ph.card_id, source=source, reason=reason)
            self.queue.append(_Pending(
                EffectBlock(steps=[Step(op="field_destroy")]),
                ExecContext(controller=pi,
                            event={"field_obj": ph, "source": source,
                                   "reason": reason})))
        self.emit("on_field_intensity_changed", player=pi, field=idx,
                  card_id=ph.card_id, old=old, new=ph.intensity, amount=amt,
                  source=source, reason=reason)

    def _field_intensity_loss(self, pi: int, amount: int, source: Ref | None) -> None:
        """规范第三条：牌手因受伤减少生命后（伤害事件流程"扣减生命"完成后立即，
        早于"受到伤害后"延时时机），其幻境队列首个幻境减少等量耐久。"""
        p = self.state.players[pi]
        if amount > 0 and p.fields:
            self._change_field_intensity(pi, 0, -amount, source, "伤害")

    def _destroy_field(self, pi: int, ph: FieldState,
                         source: Ref | None, reason: str) -> None:
        """幻境消灭事件流程后半段（规范第四条）：从所属牌手幻境队列移除（其能力
        同时从牌手移除——收集器按队列实况读取）→ "幻境消灭后"（延时）。"""
        p = self.state.players[pi]
        if not any(x is ph for x in p.fields):
            return  # 已被移除（同链重复生成/先行消灭）
        idx = next(i for i, x in enumerate(p.fields) if x is ph)
        p.fields.pop(idx)
        self._settle(f"【幻境】{p.name} 的幻境【{self.db.cards[ph.card_id].name}】被消灭")
        self.emit("on_field_destroyed", player=pi, card_id=ph.card_id,
                  source=source, reason=reason)

    def _collect_fields(self, event: dict, pi: int) -> list[_Pending]:
        """收集牌手幻境队列的幻境能力（在场期间牌手拥有——规范"零"条；按队列顺序）。
        能力块 = 幻境牌 def 的 abilities（跳过 mods.disabled_abilities 登记的下标——
        荒海"失去此能力"）+ extra_abilities（辉夜姬觉醒叠加块）。
        能力来源 = 幻境来源归属（_field_source：所属式神在场→该式神，否则无来源）；
        来源幻境实体随 ctx.field 传递（自毁/改降/"此牌"自指语义定位用）。
        专用条件键 field_intensity_ge：触发来源幻境自身耐久 ≥ n（辉夜姬各幻境
        "若此牌耐久>=10"二段）；field_self：仅"此牌"自身的幻境事件（月坠"当此牌
        获得耐久时"/黄泉花境"当此牌的耐久降低时"——按队列下标比对 event.field）。
        两键由收集器消费、不进条件迷你语言。"""
        out: list[_Pending] = []
        p = self.state.players[pi]
        for ph_idx, ph in enumerate(p.fields):
            disabled = set(ph.mods.get("disabled_abilities", ()))
            blocks = [b for i, b in enumerate(self.db.cards[ph.card_id].abilities)
                      if i not in disabled]
            blocks = [*blocks, *ph.extra_abilities]
            for ability in blocks:
                if ability.when != event["name"]:
                    continue
                cond = ability.condition
                if cond and "field_self" in cond:
                    if event.get("field") != ph_idx:
                        continue
                    cond = {k: v for k, v in cond.items() if k != "field_self"} or None
                if cond and "field_intensity_ge" in cond:
                    if ph.intensity < int(cond["field_intensity_ge"]):
                        continue
                    cond = {k: v for k, v in cond.items()
                            if k != "field_intensity_ge"} or None
                holder = self._field_source(pi, ph)
                if self._match(cond, event, pi, holder=holder):
                    out.append(_Pending(ability, ExecContext(
                        controller=pi, source=holder, event=event,
                        is_ability=True, field=ph,
                        ability_uid=f"field:{pi}:{ph_idx}:{id(ability)}")))
        return out

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

    def heal(self, ref: Ref, amount: int, source: Ref | None = None, reason: str = "") -> None:
        """治疗（恢复生命）事件流程（thoughts.txt；要素：来源、执行者、治疗量、原因）。

        治疗前（即时 on_before_heal）→ 治疗量 = min(治疗量, 执行者已损失生命) →
        增加生命 → 治疗时 on_heal（延时，实际恢复为 0 也触发）→
        治疗后 on_after_heal（延时，仅实际恢复 > 0 才触发）。
        on_heal/on_after_heal 的 payload 带 overheal = max(0, 治疗量 - 实际治疗量)
        （海坊主"过量治疗转化"：满血治疗 overheal = 全额，照常转化）。
        "恢复生命时"类能力（青坊主/禅心）挂 on_after_heal——仅实际恢复触发。
        濒死/气绝（未在场）的式神与气绝的牌手不受治疗（早退，不产生任何事件）。
        法界唯心（形态 tags 含 heal_reversal）：其控制者对敌方的恢复生命效果改为
        等额伤害效果——直接走伤害管线，不发出任何治疗事件（伤害事件照常）。
        """
        if source is not None and ref.player != source.player \
                and self._field_form_has_tag(source.player, "heal_reversal"):
            self._log(f"恢复生命效果被改为伤害效果（法界唯心）")
            if ref.shikigami is None:
                self.deal_to_player(ref.player, amount, source, kind="effect")
            else:
                self.deal_to_shikigami(ref, amount, source, kind="effect")
            return
        p = self.state.players[ref.player]
        s = p.shikigami[ref.shikigami] if ref.shikigami is not None else None
        if s is not None and (not s.in_play or s.dying):
            return
        if s is None and p.defeated:
            return
        holder = s if s is not None else p
        self.emit("on_before_heal", target=ref, amount=amount, source=source, reason=reason)
        healed = min(amount, holder.max_health - holder.health)
        overheal = max(0, amount - healed)  # 过量治疗量（海坊主转化通道）
        if healed > 0:
            holder.health += healed
            self._settle(f"【治疗】{self.db.shikigami[s.id].name if s is not None else p.name} "
                         f"恢复 {healed} 点生命（生命 {holder.health - healed}→{holder.health}）")
            # 不写 _log 孪生行：归 settle 通道，避免双通道重复
        if healed <= 0:
            # 实际恢复为 0 也明示一行（治疗时时机仍触发；海坊主过量治疗转化可读）
            self._settle(f"【治疗】{self.db.shikigami[s.id].name if s is not None else p.name} "
                         f"恢复 0 点生命（治疗量 {amount}，"
                         f"生命 {holder.health}/{holder.max_health}）")
            self.emit("on_heal", target=ref, amount=0, overheal=overheal,
                      source=source, reason=reason)
            return  # 实际恢复为 0：治疗时仍触发，治疗后不触发
        self.emit("on_heal", target=ref, amount=healed, overheal=overheal,
                  source=source, reason=reason)
        self.emit("on_after_heal", target=ref, amount=healed, overheal=overheal,
                  source=source, reason=reason)

    def _field_form_has_tag(self, pi: int, tag: str) -> bool:
        """玩家 pi 在场式神结附的形态中是否有 tags 含 tag 者（法界唯心 heal_reversal；
        硬编码扫描的先例见 _combat_zone_locked 的 destroy_immune 标记形态）。"""
        for s in self.state.players[pi].shikigami:
            if s.in_play and s.form is not None and tag in self.db.cards[s.form.id].tags:
                return True
        return False

    def draw_cards(self, player_index: int, count: int, *, reason: str | None = None) -> None:
        """效果抽牌（抽牌事件流程，docs/rules.md 第十九章——严格递归结构 + 终止语义）。

        "抽X张牌"事件（`_draw_event` 递归体）：
        1. 发 on_before_draw（即时时机，count=X——"获得卡牌前"锚点）；
        2. **抽牌前触发的终止**（答复(4)，`_draw_terminate`）：满足条件则触发相应
           能力并**终止该抽牌事件**（不绑定移动、不再递归——无论剩余多少张没抽都
           只触发一次）——明心（reason="turn_start" 且在场形态 tags 含
           draw_to_pick：改为检视牌库顶三张选一）/ 觉醒·书翁（牌库无牌：烧 10 终止）
           / 空库判负（终止整个抽牌事件链，递归立即回卷，on_draw 不再发）；
        3. 绑定牌库顶 1 张（即刻离库，移动结算前处悬置态），其"牌移动事件"
           （deck→hand, reason="draw"）按**延时通道**挂起到**本抽牌事件单元**
           （内部 op draw_move 待结算项，horizon=单元 id——山风 horizon 机制同族）；
        4. 若 X>1，**立即插入结算**"抽X-1张牌"事件（直接递归——内层抽牌事件先
           完成）；
        5. **本抽牌事件完成时** drain 本单元：结算其挂起的移动事件（灵咒触发位于
           移动事件内部的延时时机——移动完成后同单元随后结算）。
        全局次序（答复(3) 倒序定案）：on_before_draw(X)…(1) 依次先发；内层单元先
        完成——**移动事件与灵咒均倒序**（抽 2 张：第 2 张的移动+灵咒先，第 1 张后；
        后果报备：第 2 张先入手、hand_seq 更小）。整次抽牌事件未被终止时最后发
        on_draw（延时，整次一张）。
        """
        # atomic 契约保护（test_interleaved_vs_atomic 回归）：抽牌前已挂起的外层
        # 无标记延时项（如 atomic 块前序步骤产生的 on_damage 等）暂存移出队列——
        # 抽牌事件全程（递归 + 各单元 drain 中的嵌套排水）不冲刷它们，抽牌结束后
        # 按原次序放回队首由外层统一结算；抽牌中新产生的无标记项仍照常内联结算。
        stash = [p for p in self.queue if p.horizon == 0]
        if stash:
            self.queue = deque(p for p in self.queue if p.horizon != 0)
        try:
            ok = self._draw_event(player_index, count, reason)
        finally:
            if stash:
                self.queue.extendleft(reversed(stash))
        if ok:
            self.emit("on_draw", player=player_index, count=count)

    def _draw_event(self, player_index: int, count: int, reason: str | None) -> bool:
        """"抽X张牌"事件递归体；返回 False = 事件被终止（明心替换 / 觉醒·书翁烧血
        / 空库判负——上层不再发 on_draw；判负时已挂起的移动随 pending_end 丢弃，
        对局已结束、悬置离库牌不归位）。"""
        p = self.state.players[player_index]
        self.emit("on_before_draw", player=player_index, count=count, reason=reason)
        if self._draw_terminate(player_index, reason):
            return False
        self._horizon_seq += 1
        unit = self._horizon_seq  # 本抽牌事件的挂起单元（移动事件延时到单元完成时结算）
        card = p.deck.pop(0)  # 绑定牌库顶牌（即刻离库；递归下层绑定下一张）
        self._quest_tick(player_index, "draw")  # 委托账本：抽牌张数（绑定即计一张）
        self.queue.append(_Pending(
            _DRAW_MOVE_BLOCK,
            ExecContext(controller=player_index, card=card,
                        event={"name": "on_draw_move", "draw_unit": unit}),
            horizon=unit))
        ok = True
        if count > 1:
            ok = self._draw_event(player_index, count - 1, reason)  # 插入结算：内层先完成
        self._drain_horizon(unit)  # 本抽牌事件完成：结算本单元的移动（含其灵咒）
        return ok

    def _draw_terminate(self, player_index: int, reason: str | None) -> bool:
        """抽牌事件的"抽牌前"触发+终止（答复(4)；判定点在绑定步骤之前——此时牌库
        已被外层事件绑定取走相应张数，计数正确）。返回 True = 终止该抽牌事件。
        - 明心（在场形态 tags 含 draw_to_pick）：条件=回合开始的抽牌
          （reason="turn_start"）→ 无条件触发 → 终止 → 改为检视牌库顶三张选一张
          置入手牌（然后洗牌库）；牌库为空时落入下方空库判定（觉醒·书翁/判负）。
        - 觉醒·书翁（deck_out_burn）：条件=牌库无牌 → 触发（对敌方牌手 10 点）→ 终止。
        - 无书翁且牌库无牌 → 判负并终止。"""
        p = self.state.players[player_index]
        if reason == "turn_start" and p.deck \
                and self._field_form_has_tag(player_index, "draw_to_pick"):
            self._open_deck_top_pick(player_index, min(3, len(p.deck)), 1, False)
            return True
        if not p.deck:
            burner = self._deck_out_burner(player_index)
            if burner is not None:
                self._log(f"{p.name} 牌库已空，抽牌改为对敌方牌手造成 10 点伤害（觉醒·书翁）")
                self.deal_to_player(1 - player_index, 10, burner)
            else:
                # 牌库为空时执行抽牌立即落败（可能有效果改变此判定；判负非气绝）
                if self.state.winner is None:
                    self._log(f"{p.name} 牌库抽空，判负")
                self._set_pending_end(loser=player_index)
            return True
        return False

    def _deck_out_burner(self, pi: int) -> Ref | None:
        """觉醒·书翁：己方在场、已觉醒且觉醒牌 tags 含 deck_out_burn 的式神
        （"每当你抽牌时若牌库里没有牌，则改为对敌方牌手造成10点伤害"）。"""
        for i, s in enumerate(self.state.players[pi].shikigami):
            if s.in_play and s.awakened is not None \
                    and "deck_out_burn" in self.db.cards[s.awakened].tags:
                return Ref(player=pi, shikigami=i)
        return None

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
        self._refresh_stat_auras()  # 事件发出前刷新动态身材光环缓存（条件/伤害读取最新值）
        self.history.append(name)
        if self.state.winner is not None or self.state.pending_end:
            return
        seq = self.state.next_emit_seq()
        event = {"name": name, "_emit": seq, **payload}
        self._release_lasting_stuns(name, payload, seq)
        insert_queue: list[_Pending] = []
        for pend in self._collect(event):
            timing = pend.block.timing or EVENT_TIMING.get(name, "queue")
            if timing == "insert":
                insert_queue.append(pend)
            else:
                # 延时界标记（定案"复制延时界=引起该次减少的结算单元"）：仅倒计时减少
                # 事件的延时 pend（觉醒·山风复制等）记当前最内层单元 id；单元未完成时
                # 不被普通 drain 冲刷（见 _drain_queue），由 _drain_horizon 按单元结算
                pend.horizon = (self._horizon_stack[-1]
                                if name == "on_countdown_reduced" and self._horizon_stack
                                else 0)
                self.queue.append(pend)
        insert_queue.sort(key=lambda pend: pend.block.priority)  # 稳定：同优先级保持收集序
        damage = event.get("damage")
        while insert_queue:
            pend = insert_queue.pop(0)
            if (damage is not None and getattr(damage, "amount", 1) <= 0
                    and pend.block.priority >= 2):
                # 定案(7)：「伤害改为非伤害」（优先级 1）结算后原伤害事件终止——同时机
                # 已触发的「伤害目标转移」（优先级 2）失去当前伤害事件上下文，不再处理
                continue
            self._resolve_pending(pend)
        # 结算次序不变式（旋钮②）：insert 批次是同步临时队列——emit 返回前必须
        # 全部执行完（含被定案(7)跳过的项，跳过亦已出队），无任何残留入队。
        assert not insert_queue, f"{name} 的 insert 批次未在 emit 返回前全部执行"

    def _release_lasting_stuns(self, name: str, payload: dict, seq: int) -> None:
        """持续眩晕 until_event 解除（英雄无畏"直到鸦天狗用牌/攻击/气绝"类）：
        事件名命中条目的 until_event 列表且事件涉及被看护式神（watch）时移除该眩晕。
        seq ≤ 条目 apply_seq（施加当时，含施加牌自身的使用事件）不解除。"""
        for p in self.state.players:
            for s in p.shikigami:
                if not s.stuns:
                    continue
                kept = []
                for e in s.stuns:
                    events = e.get("until_event")
                    if not events or name not in events:
                        kept.append(e)
                    elif seq <= int(e.get("apply_seq", 0)):
                        kept.append(e)  # 施加当时的事件不解除（apply_seq 见 stun 动作）
                    elif self._stun_watch_hit(e, payload):
                        self._log(f"{self.db.shikigami[s.id].name} 的持续眩晕解除（{name}）")
                    else:
                        kept.append(e)
                s.stuns[:] = kept

    @staticmethod
    def _stun_watch_hit(e: dict, payload: dict) -> bool:
        """事件 payload 是否涉及持续眩晕的被看护式神：attacker/victim/target/shikigami/
        source 键中的 Ref 命中 watch=[pi, si]；或 payload.player==watch[0] 且这些键中的
        int 命中 watch 座次/数据 id（on_card_played 的 shikigami 为数据 id，on_form_destroyed
        的 shikigami 为座次——两种 int 约定都接受）。"""
        watch = e.get("watch")
        if watch is None:
            return False
        if e.get("apply_uid") is not None and payload.get("uid") == e.get("apply_uid"):
            return False  # 施加牌自身的使用事件不解除（"直到来源用牌"指其后的使用）
        watch_id = e.get("watch_id")
        for key in ("attacker", "victim", "target", "shikigami", "source"):
            v = payload.get(key)
            if isinstance(v, Ref) and [v.player, v.shikigami] == list(watch):
                return True
            if isinstance(v, int) and payload.get("player") == watch[0] \
                    and (v == watch[1] or (watch_id is not None and v == watch_id)):
                return True
        return False

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
            # 牌手幻境队列的幻境能力（式神能力之后、卡牌触发器之前；按队列顺序）
            out.extend(self._collect_fields(event, pi))
            # 第三收集来源（式神能力之后、响应牌之前，docs/enhance-design.md 第一节）：
            # 卡牌触发器（全库游离触发块）与一次性临时触发（按注册顺序，只收一次）
            out.extend(self._collect_card_triggers(event, pi))
            out.extend(self._collect_player_auras(event, pi))
            if pi == self.state.active:
                out.extend(self._collect_temp_grants(event))
            # on_invocation_trigger（灵咒能力触发宣告）豁免回合结束响应抑制：
            # 宣告的响应窗必须在该灵咒能力后续步骤前即时打开（狮子之子在敌方回合
            # 结束触发 + 鬼刃·影杀响应——裁决(2) 次序），其余事件名维持抑制（偷袭
            # 答复3：回合结束效果的响应推迟到回合结束效果结算完后统一收集）
            if pi != self.state.active \
                    and (not self._suppress_responses
                         or event["name"] == "on_invocation_trigger") \
                    and self._response_used.get(pi) != (self._response_window,
                                                        event["name"]):
                out.extend(self._collect_responses(event, pi))
        return out

    def _collect_player_auras(self, event: dict, pi: int) -> list[_Pending]:
        """收集牌手级持久监听（PlayerState.auras，"本局游戏"类能力；豪焰）：
        附着于牌手——跨气绝保留、回合开始不清除、不限触发次数，按注册顺序收集。"""
        out: list[_Pending] = []
        for entry in self.state.players[pi].auras:
            block = entry["block"]
            if block.when != event["name"]:
                continue
            if self._match(block.condition, event, pi):
                out.append(_Pending(block, ExecContext(
                    controller=pi, event=event, is_ability=True)))
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
                cond = block.condition
                if cond and cond.get("card_in_hand"):
                    # 手牌限定触发（血怒"每当敌方牌手获得生命时，此牌伤害+1"）：
                    # 控制者手牌中无该卡实例时不触发；该键由收集器消费，不进条件迷你语言
                    if not any(c.id == cdef.id for c in self.state.players[pi].hand):
                        continue
                    cond = {k: v for k, v in cond.items() if k != "card_in_hand"} or None
                if self._match(cond, event, pi):
                    out.append(_Pending(block, ExecContext(
                        controller=pi, event=event, card_id=cdef.id)))
        return out

    def _collect_temp_grants(self, event: dict) -> list[_Pending]:
        """收集一次性临时触发（state.temp_grants）：战斗绑定者只响应本战斗内的事件；
        按能力进场序号升序（稳定——同注册顺序）。"""
        out: list[_Pending] = []
        for grant in self.state.temp_grants:
            if grant.block.when != event["name"]:
                continue
            if grant.battle is not None and event.get("battle") != grant.battle:
                continue
            if self._match(grant.block.condition, event, grant.controller, holder=grant.holder):
                out.append(_Pending(grant.block, ExecContext(
                    controller=grant.controller, source=grant.holder, event=event,
                    ability_uid=f"grant:{grant.seq}"),
                    temp_grant=grant, seq=grant.seq))
        out.sort(key=lambda pend: pend.seq)
        return out

    def _resolve_pending(self, pend: _Pending) -> None:
        """结算一个待触发项；一次性临时触发结算后 uses-1，归零移除（按对象身份比较）。"""
        pend.ctx.block = pend.block  # 触发块自指（field_rebound"失去此能力"定位用）
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
        结附形态时追加形态牌的形态能力块——觉醒替换不覆盖形态能力）。
        收集结果按能力进场序号升序（稳定排序——答复(4)：同时机触发的能力按"能力"
        的进场顺序而非式神座位；未登记序号的为 0，保持原有座位/注册顺序）。"""
        out: list[_Pending] = []
        p = self.state.players[pi]
        for si, s in enumerate(p.shikigami):
            ability_seq = s.ability_entry.get("ability", 0)
            if s.awakened is not None:
                blocks = [(b, ability_seq) for b in self.db.cards[s.awakened].abilities]
            else:
                blocks = [(b, ability_seq) for b in self.db.shikigami[s.id].all_abilities]
            if s.form is not None:
                form_seq = s.ability_entry.get("form", 0)
                blocks += [(b, form_seq) for b in self.db.cards[s.form.id].abilities]
            # 灵咒能力块（灵咒框架）：结附期间作为该式神的额外能力参与收集，
            # 进场序号 = 结附时刻（attach_invocation 记入条目）
            for inv in s.invocations:
                idef = self.db.invocations.get(inv["name"])
                if idef is not None:
                    blocks += [(b, inv.get("ability_seq", 0)) for b in idef.abilities]
                    if self._has_keyword(s, "inv_trigger_echo"):
                        # 刀鸣之刃（伪关键字 inv_trigger_echo）：该式神的灵咒能力
                        # 触发两次——能力块收集两份（鬼斩响应名额按（窗口, 事件名）
                        # 去重，announce 双发但响应不双触发）
                        blocks += [(b, inv.get("ability_seq", 0)) for b in idef.abilities]
            for ability, aseq in blocks:
                if ability.countdown is not None:
                    continue  # 倒计时能力块不作事件监听（由倒计时框架归零时结算）
                if ability.when != event["name"]:
                    continue
                if not s.in_play:
                    # 离场（despawned）恒不触发；气绝者仅 trigger_when_defeated 标记的能力
                    # 触发（觉醒·犬神"气绝时也能触发"）；0 级未在场仅 trigger_when_not_in_play
                    # 标记的能力触发（书翁/三尾狐类）
                    if s.despawned:
                        continue
                    if s.defeated:
                        if not ability.trigger_when_defeated:
                            continue
                    elif not ability.trigger_when_not_in_play:
                        continue
                if self._match(ability.condition, event, pi, holder=Ref(player=pi, shikigami=si)):
                    out.append(_Pending(ability, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si), event=event,
                        is_ability=True, ability_uid=f"shk:{pi}:{si}:{id(ability)}"),
                        seq=aseq))
            # 法术回响序列（spell_echo 登记于 ext）：持有者以外的式神（含敌方）从手牌
            # 使用法术牌时收集一次回响结算（同 id 法术每回合至多一次、序列游标未走完；
            # 结算处 spell_echo_recast 复查）
            echo = s.ext.get("spell_echo")
            if echo is not None and s.in_play and event["name"] == "on_card_played":
                esid = event.get("shikigami")
                if (event.get("card_type") == "spell" and event.get("play_from") == "hand"
                        and esid is not None and esid != s.id
                        and esid not in echo["triggered"]
                        and echo["cursor"] < len(echo["sequence"])):
                    out.append(_Pending(_SPELL_ECHO_BLOCK, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si),
                        event=event, is_ability=True), seq=ability_seq))
            # 绑定式神的一次性延迟能力（会）：先触发后执行，收集即消耗；气绝时已清除
            for entry in s.delayed:
                block = entry["block"]
                if block.when != event["name"] or not s.in_play:
                    continue
                if self._match(block.condition, event, pi, holder=Ref(player=pi, shikigami=si)):
                    chosen = [entry["chosen"]] if entry.get("chosen") is not None else []
                    out.append(_Pending(block, ExecContext(
                        controller=pi, source=Ref(player=pi, shikigami=si),
                        event=event, chosen=chosen, is_ability=True),
                        seq=int(entry.get("seq", 0))))
                    entry["uses"] -= 1
            s.delayed[:] = [e for e in s.delayed if e["uses"] > 0]
        out.sort(key=lambda pend: pend.seq)
        return out

    @staticmethod
    def _response_block(cdef: CardDef) -> EffectBlock:
        """响应牌实际结算的效果块：response 覆盖优先（魔音扰心主动/响应结构不同），缺省 effects。"""
        return cdef.response if cdef.response is not None else cdef.effects

    def _collect_responses(self, event: dict, pi: int) -> list[_Pending]:
        """收集玩家 pi 的响应牌（调用方需已确认其为非回合方且本窗口本时机未占用名额）。

        响应 = 敌方回合满足条件则必定使用（引擎自动结算，不询问玩家）。
        同一响应窗口（两次玩家行动之间的完整结算）内同一时机（事件名）每名玩家
        至多成功结算一张；不同时机是不同空闲点，可各响应一张；
        式神气绝不影响其手牌中响应牌的队列位置。
        """
        out: list[_Pending] = []
        p = self.state.players[pi]
        candidates: list[tuple[int, CardInstance, EffectBlock, int | None]] = []
        for card in p.hand:
            cdef = self.db.cards[card.id]
            eb = self._response_block(cdef)
            if "trigger" not in cdef.keywords or eb.when != event["name"]:
                continue
            si = self._find_card_owner(p, cdef.shikigami) if cdef.shikigami is not None else None
            if cdef.shikigami is not None:
                if si is None:
                    continue  # 对应式神未出战（含被变形中——变形物无法使用原式神的牌；
                    # 式神替换物经 _find_card_owner 的 replace_owner 通道放行）
                s = p.shikigami[si]
                if s.stuns:
                    continue  # 眩晕式神不能响应使用其卡牌
                if s.defeated and not self._playable_when_defeated(cdef, card):
                    continue  # 对应式神气绝且无"气绝时可用"
                if not s.defeated and cdef.only_when_defeated:
                    continue  # "仅在气绝时可用"：存活不可用（心即归处）
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
               holder: Ref | None = None, chosen: list[Ref] | None = None) -> bool:
        """条件迷你语言判定（实现见 targets.match_condition）。"""
        return targets.match_condition(self, condition, event, controller, holder, chosen)

    # ==================== 效果块结算 ====================

    def _settle_response_card(self, p: PlayerState, cdef: CardDef, ctx: ExecContext) -> bool:
        """响应牌（ctx.triggered=True）的额外开销与限制：复查、支付、插入使用分派。

        - 同一响应窗口内同一时机（_response_window + 事件名）每名玩家至多成功结算一张；
        - 从收集到结算之间局面可能已变化，必须复查手牌、条件、等级、鬼火；
        - 复查失败返回 True（短路），不占用本时机的响应名额；
        - 成功结算后支付费用、占用名额、emit on_trigger，然后按卡牌类型分派：
          战斗牌/形态牌走插入使用（_apply_response_combat / _play_form_card）后
          返回 True（短路），其余移入手牌到墓地后返回 False（调用方按 steps 结算）。
        """
        if self._response_used.get(ctx.controller) == (
                self._response_window, (ctx.event or {}).get("name")):
            return True  # 每空闲点（窗口内同一时机）每名玩家至多一张（复查失败不占名额）
        # [条件] 使用前提（福满乾坤）：不满足则任何方式都不能使用（复查失败不占名额）
        if not self._play_condition_met(p, cdef, ctx.card):
            return True
        # 收集到结算之间局面可能已变化：响应牌结算时必须复查条件、鬼火、消耗、使用者
        if ctx.card not in p.hand:
            return True
        if ctx.event is not None and not self._match(
                self._response_block(cdef).condition, ctx.event, ctx.controller):
            return True
        si: int | None = None
        if cdef.shikigami is not None:
            si = self._find_card_owner(p, cdef.shikigami)
            if si is None:
                return True
            s = p.shikigami[si]
            if s.stuns:
                return True  # 眩晕式神不能响应使用其卡牌
            if s.defeated and not self._playable_when_defeated(cdef, ctx.card):
                return True
            if not s.defeated and cdef.only_when_defeated:
                return True  # "仅在气绝时可用"：复查时存活不可用（心即归处）
            if s.level < cdef.level:
                return True
        # 尘缚之阵：响应战斗牌插入使用会把所属式神移入战斗区；若这会替换被锁定的
        # 战斗区式神，则该响应不可用（复查失败不占名额）——响应牌能否响应取决于
        # 其效果本身是否导致战斗区换人（terminology.md「战斗区锁定」）
        if (cdef.card_type == "combat" and si is not None
                and p.combat_index is not None and p.combat_index != si
                and self._combat_zone_locked(ctx.controller)):
            self._log(f"{p.name} 的响应牌【{cdef.name}】受尘缚之阵锁定，未能触发")
            return True
        cost = self._effective_cost(p, cdef, card=ctx.card)
        if p.orb < cost:
            self._log(f"{p.name} 鬼火不足，响应牌【{cdef.name}】未能触发")
            return True
        self._pay_orb(p, ctx.controller, cost, reason="响应使用")
        if self._fast_applies(p, cdef, ctx.card):
            p.fast_used = True
        # choose 目标的响应牌：自动选择事件中的被攻击者（rules.md:36"执行效果时选择目标"；
        # 不在合法池则无目标——自动使用而没有效果，如古尘之盾"对其自动使用"）
        if cdef.target.kind == "choose" and ctx.event is not None:
            v = ctx.event.get("victim")
            if isinstance(v, Ref) and v in targets.pool_refs(self, cdef.target.pool, ctx.controller):
                ctx.chosen = [v]
        self._response_used[ctx.controller] = (
            self._response_window, (ctx.event or {}).get("name"))  # 成功结算才占用本时机名额
        self._log(f"{p.name} 的响应牌【{cdef.name}】触发")
        self.emit("on_trigger", player=ctx.controller, uid=ctx.card.uid)
        if cdef.card_type == "spell":
            # 响应使用的法术牌同发"使用前"即时时机（定案(4)：任意方式任意位置的
            # 使用均触发——友切类监听）；被无效化（反制等）：跳过效果、照常离手入
            # 墓地、不发 on_card_played（同主动使用无效化口径）
            marker = self._emit_before_card_play(ctx.controller, ctx.card, cdef, "spell")
            if marker["nullified"]:
                self.move_card(p, ctx.card, "graveyard")
                self._log(f"【{cdef.name}】的使用被无效化")
                return True
        if cdef.response is not None:
            # 带 response 覆盖块的响应牌（魔音扰心型 + 鬼斩响应三连——两断/罗城门/影杀）：
            # 按覆盖块效果结算（落墓地走 steps），不走战斗/形态分派——响应战斗牌
            # 不发起战斗，其"攻击"语义由覆盖块内的显式动作（attack_buff/launch_attack）
            # 组合表达。现有 19 张覆盖块全是法术，本分派对存量数据无影响。
            # 使用后事件/弹回由调用方（_resolve_block_inner 尾部）统一处理。
            self.move_card(p, ctx.card, "graveyard")
            return False
        if cdef.card_type == "combat" and si is not None:
            # 仅"（被）攻击时"时机触发的响应战斗牌插入当前战斗（rules.md:52）；
            # 其余时机（偷袭"敌方战斗区式神气绝时"等）即使战斗中触发，也不插入——
            # 按完整战斗事件流程发起一次新战斗（嵌套战斗，正常反击）
            if self._battle_stack and (ctx.event or {}).get("name") == "on_before_assault":
                # 响应战斗牌插入使用（rules.md:52）：不发起新战斗，加成绑定被插入的战斗
                self._apply_response_combat(p, si, ctx.card, cdef)
            else:
                # 无当前战斗/非攻击时机的响应战斗牌：不能插入，发起一次新战斗
                self._resolve_combat_card(p, si, ctx.card, cdef, None, ctx.chosen)
            self._account_card_played(p, cdef)
            self._emit_card_played(ctx.controller, ctx.card.uid, cdef,
                                   triggered="response", chosen=ctx.chosen)
            return True
        if cdef.card_type == "form" and si is not None:
            # 响应形态牌插入使用：立即结附（风符·瞬）；牌不进墓地，形态离场才进
            # 形态牌的进场时效果镜像主动使用的形态分支（响应形态同样结算）
            self._play_form_card(p, si, ctx.card, cdef, ctx.controller, ctx.chosen)
            self._account_card_played(p, cdef)
            self._emit_card_played(ctx.controller, ctx.card.uid, cdef,
                                   triggered="response", chosen=ctx.chosen)
            return True
        self.move_card(p, ctx.card, "graveyard")
        return False

    def _resolve_block(self, block: EffectBlock, ctx: ExecContext, start: int = 0) -> int:
        """结算单元入口（定案"延时界=引起该次减少的结算单元"）：压栈一个唯一单元 id，
        结算期间 emit 的延时 pend 记为该单元（horizon）；返回单元 id 供调用方按单元
        drain（_drain_horizon，倒计时归零块用）。实际结算见 _resolve_block_inner。"""
        self._horizon_seq += 1
        horizon = self._horizon_seq
        self._horizon_stack.append(horizon)
        try:
            self._resolve_block_inner(block, ctx, start)
        finally:
            self._horizon_stack.pop()
        return horizon

    def _resolve_block_inner(self, block: EffectBlock, ctx: ExecContext, start: int = 0) -> None:
        """结算一个效果块：先处理响应牌的额外开销与限制（_settle_response_card），再依次执行 steps。

        按 block.steps 顺序执行动作。mode="interleaved" 时每步后清空队列，
        允许其它效果插入；mode="atomic" 时步骤连发，队列留到块外统一结算。
        步骤产生结算中交互选择（pending_choice，青灯夜谈）时挂起：续点存入
        self._suspended（内存态），由 choose 指令续跑剩余步骤（start 为续跑起点）。
        block.luck 非 None 时走运势门控（契约 §3.1）：先做运势判定，按结果决定是否
        结算 steps（choose 续跑 start > 0 时不再重复判定）。
        """
        if ctx.memo is None:
            ctx.memo = {}  # 块内步骤间暂存（damage 记录 last_damage_victims 等）
        affected: list[Ref] | None = None
        if ctx.triggered and ctx.card is not None:
            p = self.state.players[ctx.controller]
            cdef = self.db.cards[ctx.card.id]
            if self._settle_response_card(p, cdef, ctx):
                return
            self._affected_stack.append({"controller": ctx.controller, "refs": []})  # 响应法术：记录该次使用伤害过的敌方式神
        try:
            if block.luck is not None and start == 0:
                self._run_luck_events([self._luck_event_for_block(block, ctx)])
            else:
                self._run_block_steps(block, ctx, start)
        finally:
            if ctx.triggered and ctx.card is not None:
                affected = self._affected_stack.pop()["refs"]
        # mode == "atomic"：步骤连发，队列留到块外统一结算
        if ctx.triggered and ctx.card is not None:
            # 响应使用与主动使用生成同样的"卡牌的使用事件"（使用后1，延时时机）
            self._account_card_played(p, cdef)
            self._emit_card_played(ctx.controller, ctx.card.uid, cdef, affected,
                                   triggered="response", chosen=ctx.chosen)
            self._rebound_check(p, ctx.card, cdef)  # 弹回：响应使用同样回手

    def _run_block_steps(self, block: EffectBlock, ctx: ExecContext, start: int = 0) -> None:
        """依次执行效果块的 steps（_resolve_block 与运势门控续段共用）。
        actions.AbortBlock（spend_energy gate 支付失败）：中止块剩余步骤，不算错误。"""
        for idx in range(start, len(block.steps)):
            try:
                self._run_step(block.steps[idx], ctx)
            except actions.AbortBlock:
                return
            if block.mode == "interleaved":
                self._drain_queue()  # 步骤之间允许其它效果结算
            if self.state.pending_choice is not None and not ctx.triggered:
                # 交互选择挂起（响应牌无此类步骤，triggered 块不挂起：
                # 避免响应开销/受影响栈被重复结算）
                self._suspended = (block, ctx, idx + 1)
                return

    # ==================== 运势管线（契约 §3；thoughts.txt 运势事件流程） ====================

    def _luck_doublers(self, judge: int) -> list[int]:
        """判定者方的运势翻倍提供者（契约"引擎读：判定者方有未气绝觉醒青蛙瓷器"）：
        在场未气绝、已觉醒的青蛙瓷器座次下标。"""
        return [i for i, s in enumerate(self.state.players[judge].shikigami)
                if s.id == _QINGWA_SHIKIGAMI and s.in_play and s.awakened is not None]

    def _luck_event_for_block(self, block: EffectBlock, ctx: ExecContext) -> dict:
        """EffectBlock.luck 门控 → 运势事件要素：luck: 4 = 成功才结算 steps；
        luck: {"x": 4, "on": "fail"} = 判定失败才结算。判定者默认控制者。"""
        spec = block.luck
        on_fail = isinstance(spec, dict) and spec.get("on") == "fail"
        x = int(spec.get("x", 1)) if isinstance(spec, dict) else int(spec)
        return {"judge": ctx.controller, "x": x, "source": ctx.source, "card": ctx.card,
                "ctx": ctx, "block": block, "on_fail": on_fail}

    def _run_luck_events(self, events: list[dict]) -> None:
        """并行运势事件同步推进：同一触发点产生的运势事件先全部入队，各时机依次推进
        （当前回合玩家先，再非回合玩家——事件顺序由调用方排定）。

        时机：投掷骰子（必 6 修饰：萌即正义判定者级 / 这把算我赢来源级首投并消耗）→
        判定时（on_luck_judge 即时时机，座敷童子重投改写骰点）→ 确定结果（掷骰记账：
        dice_history 只记最终有效骰点、dice_six_count 同步维护）→ 判定后
        （on_luck_success 延时时机，整队生效完毕后由队列统一结算）→ 执行成功/失败效果
        （成功效果在翻倍标记下执行两次，不重新掷骰；失败效果不翻倍）→ 生效后
        （on_luck_effect_after 延时，预留）。
        """
        if not events:
            return
        # 1. 投掷骰子（修饰：必 6）
        for ev in events:
            dice = self.rng.randint(1, 6)
            src = ev.get("source")
            s = (self.state.players[src.player].shikigami[src.shikigami]
                 if src is not None and src.shikigami is not None else None)
            if s is not None and s.ext.pop("dice_force_six_once", False):
                dice = 6  # 这把算我赢：下次以其为来源的判定首投必 6（消耗）
                ev["forced"] = True
            elif self.state.players[ev["judge"]].ext.get("dice_force_six"):
                dice = 6  # 萌即正义：判定者级光环必 6
                ev["forced"] = True
            ev["dice"] = dice
            ev["first_dice"] = dice  # 重投检测用（判定时 on_luck_judge 可改写骰点）
        # 2. 判定时（即时时机；重投改写 ev["dice"]，强制 6 不豁免本时机）
        for ev in events:
            self.emit("on_luck_judge", luck=ev, judge=ev["judge"],
                      source=ev.get("source"), x=ev["x"], dice=ev["dice"])
        # 3. 确定结果 + 掷骰记账（只记最终有效骰点；被重投覆盖的首投不计入）
        for ev in events:
            ev["success"] = ev["dice"] >= ev["x"]
            jp = self.state.players[ev["judge"]]
            jp.ext.setdefault("dice_history", []).append(ev["dice"])
            if ev["dice"] == 6:
                jp.ext["dice_six_count"] = jp.ext.get("dice_six_count", 0) + 1
            # 结算明细：运势判定全程可见（重投/必 6 修饰一并标注）
            cast = f"掷出 {ev['dice']} 点"
            if ev["dice"] != ev["first_dice"]:
                cast = f"掷出 {ev['first_dice']} 点，重投为 {ev['dice']} 点"
            mods = ["必 6"] if ev.get("forced") else []
            mods.append(f"需 ≥{ev['x']}")
            self._settle(f"【运势】{jp.name} {cast}（{'；'.join(mods)}）："
                         f"{'成功' if ev['success'] else '失败'}")
        # 4-6. 判定后（延时）→ 执行成功/失败效果 → 生效后（延时，预留）
        for ev in events:
            judge = ev["judge"]
            success = ev["success"]
            ctx = ev["ctx"]
            if ctx.memo is None:
                ctx.memo = {}
            ctx.memo["luck_dice"] = ev["dice"]  # 效果上下文变量：amount_ctx 读取点
            if success:
                jp = self.state.players[judge]
                jp.ext["luck_success_game"] = jp.ext.get("luck_success_game", 0) + 1
                jp.ext["luck_success_turn"] = self.state.turn  # 最近一次成功的回合号（青蛙光环读）
                self._emit_luck_success(ev)
            if success != ev.get("on_fail", False):
                # 翻倍（觉醒青蛙瓷器）：成功效果执行两次；失败效果（on: fail）不翻倍
                times = 2 if (success and self._luck_doublers(judge)) else 1
                if times == 2:
                    self._settle(f"【运势】{self.state.players[judge].name} "
                                 "的成功效果翻倍（觉醒青蛙瓷器）")
                for _ in range(times):
                    self._run_luck_continuation(ev)
                self.emit("on_luck_effect_after", luck=ev, judge=judge,
                          source=ev.get("source"), x=ev["x"], dice=ev["dice"])

    def _run_luck_continuation(self, ev: dict) -> None:
        """执行运势事件的成功/失败效果：步骤级 then 子步骤 / 块级门控的块 steps。"""
        ctx = ev["ctx"]
        if ev.get("block") is not None:
            self._run_block_steps(ev["block"], ctx)
            return
        for st in ev.get("then") or ():
            self._run_step(st, ctx)
            self._drain_queue()  # 与 interleaved 块一致：步骤之间允许其它效果结算

    def _emit_luck_success(self, ev: dict) -> None:
        """判定后（延时时机 on_luck_success）：正常发出；判定者方翻倍标记生效时，
        各延时 handler 追加执行一次（岭上开花/觉醒妖狐同样翻倍；翻倍提供者自身的能力、
        响应牌与一次性临时触发不翻倍）。"""
        judge = ev["judge"]
        self.emit("on_luck_success", luck=ev, judge=judge,
                  source=ev.get("source"), x=ev["x"], dice=ev["dice"])
        doublers = self._luck_doublers(judge)
        if not doublers:
            return
        event = {"name": "on_luck_success", "_emit": self.state.next_emit_seq(),
                 "luck": ev, "judge": judge, "source": ev.get("source"),
                 "x": ev["x"], "dice": ev["dice"]}
        for pend in self._collect(event):
            if pend.temp_grant is not None or pend.ctx.triggered or pend.ctx.card is not None:
                continue  # 响应牌/一次性临时触发不参与翻倍
            src = pend.ctx.source
            if src is not None and src.player == judge and src.shikigami in doublers:
                continue  # 翻倍提供者（觉醒青蛙瓷器）自身的能力不翻倍
            self.queue.append(pend)

    def _run_step(self, step: Step, ctx: ExecContext) -> None:
        fn = actions.ACTIONS.get(step.op)
        if fn is None:
            raise IllegalAction(f"未知动作: {step.op}")  # 加载时已校验，此处双保险
        params = dict(step.model_extra or {})
        if step.condition is not None:
            if "condition" in self._op_params(step.op, fn):
                # op 自身声明 condition 参数（delay_grant 的延迟块触发条件）：作为参数传递
                params["condition"] = step.condition
            else:
                cond = step.condition
                if "field_intensity_ge" in cond:
                    # 步级专用键（月坠"然后若耐久>=30"，定案(13)——仅在同一块的
                    # 获得耐久结算串内判定）：触发来源幻境（ctx.field）当前耐久 ≥ n，
                    # 不满足跳过该步；由执行器消费，不进条件迷你语言。
                    # 同一块内多次判定共享**首次判定的快照**（ctx.memo 块级暂存）——
                    # "若…则自毁并造成伤害"类：自毁归零后后续步仍按判定时的耐久通过
                    if ctx.memo is None:
                        ctx.memo = {}
                    snap = ctx.memo.get("field_intensity_ge_snap")
                    if snap is None:
                        snap = (ctx.field.intensity if ctx.field is not None else 0)
                        ctx.memo["field_intensity_ge_snap"] = snap
                    if snap < int(cond["field_intensity_ge"]):
                        return
                    cond = {k: v for k, v in cond.items()
                            if k != "field_intensity_ge"} or None
                if cond is not None and not self._match(
                        cond, ctx.event or {}, ctx.controller,
                        holder=ctx.source, chosen=ctx.chosen):
                    return  # Step 级条件不满足：跳过该步（条件迷你语言，见 targets.match_condition）
        refs = targets.resolve(self, step.target, ctx)
        for num_key in ("amount", "power"):
            if isinstance(params.get(num_key), dict):
                raw_num = params[num_key]
                if any(raw_num.get(k) == "target"
                       for k in ("health_of", "half_health_of")):
                    # 逐目标动态数值（凋零之森"对他所有角色造成等同于他自身一半生命
                    # 的伤害"）：不以来源/事件预解析，原样传字典由 op 逐目标求值
                    continue
                # 动态数值（enhance 快照 / shield_of / power_of / ext / 事件引用等）：
                # 以 ctx 来源式神与触发事件求值（援护/古尘之壁/鸩觉醒/毒之华）；
                # power 键供 attack_buff 类"直到攻击后"力量走同一流水线（势）
                src = (self.state.players[ctx.source.player].shikigami[ctx.source.shikigami]
                       if ctx.source is not None and ctx.source.shikigami is not None else None)
                params[num_key] = self._step_amount(step, ctx.card, src,
                                                    event=ctx.event, game=self,
                                                    memo=ctx.memo,
                                                    controller=ctx.controller,
                                                    chosen=ctx.chosen,
                                                    key=num_key,
                                                    field=ctx.field)
        fn(self, ctx, targets=refs, **params)

    def _op_params(self, op: str, fn) -> frozenset:
        """op 函数的参数名集合（缓存；用于区分 Step 级 condition 与 op 的 condition 参数）。"""
        cached = self._op_param_cache.get(op)
        if cached is None:
            import inspect
            cached = frozenset(inspect.signature(fn).parameters)
            self._op_param_cache[op] = cached
        return cached

    def _drain_horizon(self, horizon: int) -> None:
        """按结算单元 drain 效果队列（定案"复制延时界=引起该次减少的结算单元"）：只
        结算标记为该单元的倒计时减少延时 pend（按入队顺序），其余留队由外层统一
        结算——中途插入结算的能力块完成时不冲刷卡牌级延时项。结算中产生的新标记
        延时项属于新单元（被结算块自身压栈），不混入本批。"""
        # 结算次序不变式（旋钮⑤）：按单元冲刷延时项时该单元必须已完成——倒计时
        # 单元经 _resolve_block 的 finally 出栈后才走到这里；抽牌/灵咒挂起单元
        # 不压栈（_draw_event 手工分配 id），此检查对其恒过。
        if horizon in self._horizon_stack:
            raise RuntimeError(
                f"结算次序不变式违反：结算单元 {horizon} 尚未完成（仍在单元栈"
                f" {list(self._horizon_stack)} 中），不应按单元冲刷其延时项")
        guard = 0
        while not self.state.pending_end:
            pend = next((p for p in self.queue if p.horizon == horizon), None)
            if pend is None:
                return
            guard += 1
            if guard > MAX_QUEUE_ITERATIONS:
                self.queue.clear()
                raise RuntimeError("效果队列疑似死循环，已强制清空")
            self.queue.remove(pend)
            self._resolve_pending(pend)

    def _drain_queue(self) -> None:
        """循环结算效果队列，带死循环保护。

        若游戏已进入"待结束"状态，不再执行已入队的触发式能力；队列处理完成后，
        把 pending_end 正式转为 winner，进入游戏结束阶段。

        延时界跳项（定案"复制延时界=引起该次减少的结算单元"）：带结算单元标记
        （horizon 非 0）的倒计时减少延时 pend 只在两种时机结算——引起它的单元
        完成时由 _drain_horizon 按单元结算；或最外层排水（_horizon_stack 为空，
        指令/回合级）统一清尾。结算中途（能力块/战斗等嵌套排水）只排无标记项，
        不冲刷任何单元的复制延时项（含外层卡牌级与本单元尚未完成的）。
        """
        guard = 0
        while True:
            if not self._horizon_stack:
                pend = self.queue[0] if self.queue else None  # 顶层：全量按序
            else:
                pend = next((p for p in self.queue if p.horizon == 0), None)
            if pend is None:
                break
            if self.state.pending_end:
                self.queue.clear()
                break
            guard += 1
            if guard > MAX_QUEUE_ITERATIONS:
                self.queue.clear()
                raise RuntimeError("效果队列疑似死循环，已强制清空")
            self.queue.remove(pend)
            self._resolve_pending(pend)
        # 结算次序不变式（旋钮⑤/⑥）：正常排水结束后，残留项只能是带单元标记
        # （horizon != 0）的延时项——属尚未完成的结算单元，留待 _drain_horizon
        # 或最外层清尾；最外层排水（无进行中单元）必须完全清空。pending_end
        # 分支已整队清空，不在此列。
        if any(p.horizon == 0 for p in self.queue) \
                or (self.queue and not self._horizon_stack):
            raise RuntimeError(
                "结算次序不变式违反：排水结束后队列残留不该剩余的延时项 "
                f"{[f'{p.block.when}(horizon={p.horizon})' for p in self.queue]}"
                f"（单元栈={list(self._horizon_stack)}）")
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

    def _find_card_owner(self, p: PlayerState, defn_id: int) -> int | None:
        """卡牌所属式神的座次：按数据 id 直查；查不到时查式神替换标记
        （ext["replace_owner"]，觉醒·番茄——替换物承继原式神的全部卡牌使用权，
        以替换物座次为来源）。变形物（transform_owner）不在此列——变形中不能使用
        原式神的牌。"""
        si = self._find_shikigami(p, defn_id)
        if si is not None:
            return si
        return next((j for j, st in enumerate(p.shikigami)
                     if st.ext.get("replace_owner") == defn_id), None)

    def _own_shikigami(self, p: PlayerState, i: int) -> ShikigamiState:
        if not 0 <= i < len(p.shikigami):
            raise IllegalAction("式神序号无效")
        s = p.shikigami[i]
        if s.defeated or s.despawned:
            raise IllegalAction(f"{self.db.shikigami[s.id].name} 无法行动（气绝/已离场）")
        return s

    def _log(self, msg: str) -> None:
        self.state.log.append(msg)
        self.state.timeline.append({"k": "l", "m": msg})

    def _settle(self, msg: str) -> None:
        """结算明细记录（GameState.settle_log）：等级/力量/战力/生命/护甲/破甲变化与
        各事件开始结束。纯记录不打印——CLI 在空闲点取增量逐条展示（client/cli.py）。
        数值类事件只记本通道、不再写 _log 孪生行（避免联机端双通道同屏重复）。
        两通道同步记入 timeline 合流（结算播放按真实发生顺序）。"""
        self.state.settle_log.append(msg)
        self.state.timeline.append({"k": "s", "m": msg})
