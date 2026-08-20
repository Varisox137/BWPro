"""卡牌数据库：从 YAML 文件加载并校验。

校验在加载时完成——数据错误（未知动作/事件/目标池、悬空引用、id 号段不符等）
在对局开始前暴露，而不是打到一半才崩。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.actions import ACTIONS
from core.events import CORE_EVENTS
from core.registry import (
    CONDITION_KEYS,
    CONDITIONAL_KEYWORD_KEYS,
    COUNT_VALUE_KEYS,
    DYNAMIC_VALUE_KEYS,
    TARGET_EXTRA_KEYS,
)
from core.targets import POOLS
from db.schema import (
    CARD_TYPES,
    EXCLUSIVE_SUBTYPES,
    FACTIONS,
    KEYWORDS,
    NEUTRAL_PREFIX,
    RARITIES,
    SUBTYPES,
    CardDef,
    EffectBlock,
    InvocationDef,
    ShikigamiDef,
)

DB_ROOT = Path(__file__).parent


def _inject_derived(resolved: dict) -> dict:
    """卡牌定义注入由 id 推导的所属式神（不入 yaml 数据）：中立牌（id 首位 9）
    为 None，其余为 id 前六位（协战牌主归属同为前六位 = 两位所属中较小者）。"""
    if "card_type" in resolved:
        cid = resolved["id"]
        resolved["shikigami"] = None if cid // 10_000_000 == 9 else cid // 100
    return resolved


class CardDatabase:
    def __init__(
        self,
        cards: dict[int, CardDef],
        shikigami: dict[int, ShikigamiDef],
        custom_events: set[str],
        raw_cards: dict[int, dict] | None = None,
        raw_shikigami: dict[int, dict] | None = None,
        invocations: dict[str, InvocationDef] | None = None,
        raw_invocations: dict[str, dict] | None = None,
        paths: dict[int, str] | None = None,
    ) -> None:
        self.cards = cards
        self.shikigami = shikigami
        self.custom_events = custom_events
        # 原始 yaml dict（含 versions 时间线）：环境解析（at_date）的输入；
        # 测试工厂构造的库无原始 dict（at_date 退化为按 version 判可用）
        self.raw_cards = raw_cards or {}
        self.raw_shikigami = raw_shikigami or {}
        # 灵咒定义表（灵咒框架）：load() 收集各式神目录的 invocations.yaml；
        # 测试亦可直接 db.invocations[name] = InvocationDef(...) 注入（同 db.cards 惯例，
        # 直注入条目无 raw，at_date 按 version 判可用）
        self.invocations = invocations or {}
        self.raw_invocations = raw_invocations or {}
        # id → 来源 yaml 路径（白名单校验报错定位用；测试工厂构造的库为空）
        self.paths = paths or {}

    @classmethod
    def load(cls, root: Path | str | None = None, strict: bool = True) -> "CardDatabase":
        root = Path(root) if root else DB_ROOT
        cards: dict[int, CardDef] = {}
        shikigami: dict[int, ShikigamiDef] = {}
        raw_cards: dict[int, dict] = {}
        raw_shikigami: dict[int, dict] = {}
        invocations: dict[str, InvocationDef] = {}
        raw_invocations: dict[str, dict] = {}
        paths: dict[int, str] = {}
        custom_events: set[str] = set()
        from db.versioning import resolve_latest
        # db/<pack>/<seq>_<slug>/*.yaml 递归收集；顶层仅 id/name/versions，
        # 先解析最新版本快照，再按有无 card_type 区分卡牌/式神定义
        for f in sorted(root.rglob("*.yaml")):
            if f.name == "events.yaml":
                for entry in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
                    custom_events.add(entry["name"])
                continue
            if f.name == "invocations.yaml":
                # 灵咒定义表：{"invocations": [{name, versions}, ...]}，灵咒顶层无 id
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                for entry in data.get("invocations") or []:
                    resolved = resolve_latest(entry)
                    if resolved is None:
                        raise RuntimeError(f"{f.name}: 灵咒《{entry.get('name')}》"
                                           f" versions.history 无可用快照")
                    idef = InvocationDef.model_validate(resolved)
                    if idef.name in invocations:
                        raise RuntimeError(f"灵咒名重复: {idef.name}（{f.name}）")
                    invocations[idef.name] = idef
                    raw_invocations[idef.name] = entry
                continue
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            resolved = resolve_latest(data)
            if resolved is None:
                raise RuntimeError(f"{f.name}: versions.history 无可用快照")
            _inject_derived(resolved)
            out: dict = cards if "card_type" in resolved else shikigami
            raw_out: dict = raw_cards if out is cards else raw_shikigami
            obj = (CardDef if out is cards else ShikigamiDef).model_validate(resolved)
            if obj.id in cards or obj.id in shikigami:
                raise RuntimeError(f"id 重复: {obj.id}（{f.name}）")
            out[obj.id] = obj
            raw_out[obj.id] = data
            paths[obj.id] = str(f)
        db = cls(cards, shikigami, custom_events, raw_cards, raw_shikigami,
                 invocations=invocations, raw_invocations=raw_invocations,
                 paths=paths)
        errors = db.validate()
        if errors and strict:
            raise RuntimeError("卡牌数据库校验失败：\n" + "\n".join(errors))
        return db

    def at_date(self, date: int | None) -> "CardDatabase":
        """环境解析：指定日期下的数据库（该日期未发布的 id 剔除）。
        None = 最新数据（返回自身）。解析结果重新 schema 校验并全库 validate。"""
        if date is None:
            return self
        from db.versioning import resolve_at_date
        cards: dict[int, CardDef] = {}
        shikigami: dict[int, ShikigamiDef] = {}
        for i, c in self.cards.items():
            raw = self.raw_cards.get(i)
            if raw is None:  # 无原始 dict（测试工厂）：仅按 version 判可用
                if c.version <= date:
                    cards[i] = c
                continue
            r = resolve_at_date(raw, date)
            if r is not None:
                cards[i] = CardDef.model_validate(_inject_derived(r))
        for i, s in self.shikigami.items():
            raw = self.raw_shikigami.get(i)
            if raw is None:
                if s.version <= date:
                    shikigami[i] = s
                continue
            r = resolve_at_date(raw, date)
            if r is not None:
                shikigami[i] = ShikigamiDef.model_validate(r)
        invocations: dict[str, InvocationDef] = {}
        for n, inv in self.invocations.items():
            raw = self.raw_invocations.get(n)
            if raw is None:  # 无原始 dict（测试直注入）：version=0 视为任意日期可用
                if inv.version <= date:
                    invocations[n] = inv
                continue
            r = resolve_at_date(raw, date)
            if r is not None:
                invocations[n] = InvocationDef.model_validate(r)
        db = CardDatabase(cards, shikigami, set(self.custom_events),
                          dict(self.raw_cards), dict(self.raw_shikigami),
                          invocations=invocations,
                          raw_invocations=dict(self.raw_invocations),
                          paths=dict(self.paths))
        errors = db.validate()
        if errors:
            raise RuntimeError(f"环境 {date} 解析结果校验失败：\n" + "\n".join(errors))
        return db

    def validate(self) -> list[str]:
        """返回全部错误信息（空列表 = 通过）。"""
        from db.versioning import validate_versions
        errors: list[str] = []
        for i, raw in self.raw_cards.items():
            errors += [f"卡牌 {i}: {e}" for e in validate_versions(raw)]
        for i, raw in self.raw_shikigami.items():
            errors += [f"式神 {i}: {e}" for e in validate_versions(raw)]
        for n, raw in self.raw_invocations.items():
            errors += [f"灵咒《{n}》: {e}" for e in validate_versions(raw)]
        # 白名单校验（规则设计评审③）：条件键 / 目标过滤键 / 动态数值键须在
        # core/registry.py 登记，未登记直接报错（杜绝 yaml 笔误静默恒假）；
        # 逐版本快照校验（旧快照中的键同样受校验）
        for i, raw in self.raw_cards.items():
            errors += self._check_key_whitelists(raw, f"卡牌 {i}《{raw.get('name')}》")
        for i, raw in self.raw_shikigami.items():
            errors += self._check_key_whitelists(raw, f"式神 {i}《{raw.get('name')}》")
        for n, raw in self.raw_invocations.items():
            errors += self._check_key_whitelists(raw, f"灵咒《{n}》")
        known_events = CORE_EVENTS | self.custom_events | {"on_play"}
        for s in self.shikigami.values():
            where = f"式神 {s.id}《{s.name}》"
            if s.kind == "shikigami":
                if not 100_000 <= s.id <= 199_999:
                    errors.append(f"{where}: 式神 id 须为 1avvss（1 + 1 位异画位 + 2 位卡包 + 2 位序号）")
            else:  # summon/transform/replace：8 位 = 从属式神 id + 序号（衍生物/变形物/替换物从 99 开始递减分配；结构与卡牌相同）
                owner = self.shikigami.get(s.id // 100)
                if not 10_000_000 <= s.id <= 99_999_999:
                    errors.append(f"{where}: 召唤物 id 须为 8 位（从属式神 id + 2 位序号）")
                elif not 90 <= s.id % 100 <= 99:
                    errors.append(f"{where}: 召唤物序号须在 90-99 号段（从 99 开始递减分配）")
                if owner is None:
                    errors.append(f"{where}: 从属式神 {s.id // 100} 不存在（衍生物必须有从属）")
            if s.faction not in FACTIONS:
                errors.append(f"{where}: 未知派系 {s.faction}")
            if s.ability is not None:
                errors += self._check_block(s.ability, known_events - {"on_play"}, f"{where}的被动")
            for ab in s.abilities:
                errors += self._check_block(ab, known_events - {"on_play"}, f"{where}的被动")
        for c in self.cards.values():
            where = f"卡牌 {c.id}《{c.name}》"
            if c.shikigami is None:
                if not 90_000_000 <= c.id <= 99_999_999 or c.id // 10_000_000 != NEUTRAL_PREFIX:
                    errors.append(f"{where}: 中立牌 id 须为 9avvvvvv（9 + 1 位异画位 + 6 位数字，自 999999 递减）")
            else:
                if c.shikigami not in self.shikigami:
                    errors.append(f"{where}: 所属式神 {c.shikigami} 不存在")
                elif c.id // 100 != c.shikigami:
                    errors.append(f"{where}: id 前缀 {c.id // 100} 与所属式神 {c.shikigami} 不一致")
                if c.token and not 51 <= c.id % 100 <= 99:
                    errors.append(f"{where}: 衍生卡序号须在 51-99 号段（从 51 开始递增）")
                if not c.token and c.card_type != "reinforce" and not 1 <= c.id % 100 <= 8:
                    errors.append(f"{where}: 可构筑卡牌序号须在 01-08 号段")
            if c.card_type == "reinforce":
                # 协战牌：前六位 = 两位所属式神中较小者，后两位从 21 开始递增
                if c.shikigami is None or c.shikigami2 is None:
                    errors.append(f"{where}: 协战牌须记录两位所属式神（shikigami / shikigami2）")
                else:
                    lo = min(c.shikigami, c.shikigami2)
                    if c.id // 100 != lo:
                        errors.append(f"{where}: 协战牌 id 前六位须为两位所属式神中较小者（{lo}）")
                    if c.id % 100 < 21:
                        errors.append(f"{where}: 协战牌序号须从 21 开始递增")
                    if c.shikigami2 not in self.shikigami:
                        errors.append(f"{where}: 协战牌另一位所属式神 {c.shikigami2} 不存在")
                # 子选项（有则逐项校验）：须为已存在的衍生 token 卡，且归属于两位所属
                # 式神之一；缺省/数量不足由打出流程报错（_cmd_play_reinforce）
                for o in c.options:
                    oc = self.cards.get(o)
                    if oc is None:
                        errors.append(f"{where}: 子选项 {o} 不存在")
                    elif not oc.token:
                        errors.append(f"{where}: 子选项《{oc.name}》须为衍生 token 卡")
                    elif oc.shikigami not in (c.shikigami, c.shikigami2):
                        errors.append(
                            f"{where}: 子选项《{oc.name}》的所属式神 {oc.shikigami} 非协战双方")
            elif c.shikigami2 is not None:
                errors.append(f"{where}: 仅协战牌可以有 shikigami2")
            if c.card_type not in CARD_TYPES:
                errors.append(f"{where}: 未知主类型 {c.card_type}")
            if c.subtype is not None and c.subtype not in SUBTYPES \
                    and c.subtype not in EXCLUSIVE_SUBTYPES:
                errors.append(f"{where}: 未知子类型 {c.subtype}")
            if c.subtype in EXCLUSIVE_SUBTYPES \
                    and c.shikigami != EXCLUSIVE_SUBTYPES[c.subtype]:
                errors.append(
                    f"{where}: 专属子类型 {c.subtype} 只能出现在所属式神"
                    f" {EXCLUSIVE_SUBTYPES[c.subtype]} 的牌上")
            if c.token and c.rarity is not None:
                errors.append(f"{where}: 衍生牌无稀有度（token 卡须缺省 rarity）")
            if c.rarity is not None and c.rarity not in RARITIES:
                errors.append(f"{where}: 未知稀有度 {c.rarity}（R/SR/SSR）")
            for kw in c.keywords:
                if kw.split(":", 1)[0] not in KEYWORDS:  # 冒号参数伪关键字按前缀校验
                    errors.append(f"{where}: 未知关键词 {kw}")
            errors += self._check_target(c.target, where)
            resp = c.response if c.response is not None else c.effects
            if "trigger" in c.keywords and resp.when == "on_play":
                errors.append(f"{where}: 响应牌的 effects/response.when 必须是触发事件")
            errors += self._check_block(c.effects, known_events, where)
            if c.response is not None:
                errors += self._check_block(c.response, known_events - {"on_play"}, f"{where}的响应效果")
            if c.alt_effects is not None:
                errors += self._check_block(c.alt_effects, known_events, f"{where}的变为效果")
            for ab in c.abilities:
                errors += self._check_block(ab, known_events - {"on_play"}, f"{where}的能力")
            if c.countdown_effects is not None:
                errors += self._check_block(c.countdown_effects, known_events, f"{where}的倒计时效果")
            for tb in c.triggers:
                errors += self._check_block(tb, known_events - {"on_play"}, f"{where}的触发器")
            for tg in c.temp_grants:
                errors += self._check_block(tg, known_events - {"on_play"}, f"{where}的临时触发")
            for m in c.methods:
                if m.effects is not None:
                    errors += self._check_block(m.effects, known_events, f"{where}的使用方式[{m.id}]")
        for n, idef in self.invocations.items():
            where = f"灵咒《{n}》"
            if idef.name != n:
                errors.append(f"{where}: 定义名 {idef.name} 与表键不一致")
            for kw in idef.keywords:
                if kw not in KEYWORDS and kw != "stun":
                    errors.append(f"{where}: 未知关键词 {kw}（灵咒 keywords 另允许 stun=眩晕）")
            for ab in idef.abilities:
                errors += self._check_block(ab, known_events - {"on_play"}, f"{where}的能力")
            if idef.draw_trigger is not None:
                errors += self._check_block(idef.draw_trigger, known_events - {"on_play"},
                                            f"{where}的抽到触发")
        return errors

    def _check_target(self, t: TargetSpec | None, where: str) -> list[str]:
        """校验 TargetSpec：kind/pool/key 的基本合法性。"""
        errors: list[str] = []
        if t is None:
            return errors
        if t.kind in ("all", "choose") and t.pool not in POOLS:
            # step 级 {kind: choose, chosen_index: n} 为已选目标按序取用器，无 pool
            if not (t.kind == "choose"
                    and (t.model_extra or {}).get("chosen_index") is not None):
                errors.append(f"{where}: 未知目标池 {t.pool}")
        if t.kind == "context" and not t.key:
            errors.append(f"{where}: context 目标缺少 key")
        return errors

    def _check_block(self, block: EffectBlock, known_events: set[str], where: str) -> list[str]:
        """校验一个效果块：事件名、动作注册、summon 引用与目标池。"""
        errors: list[str] = []
        # 倒计时能力块（countdown 非 None）不作事件监听，when 无意义，允许缺省 on_play
        allowed = known_events | ({"on_play"} if block.countdown is not None else set())
        if block.when not in allowed:
            errors.append(f"{where}: 未知事件 {block.when}")
        for step in block.steps:
            if step.op not in ACTIONS:
                errors.append(f"{where}: 未知动作 {step.op}")
            if step.op == "summon":
                sid = (step.model_extra or {}).get("shikigami")
                d = self.shikigami.get(sid)
                if d is None:
                    errors.append(f"{where}: summon 引用的式神 {sid} 不存在")
                elif d.kind != "summon":
                    errors.append(f"{where}: summon 只能召唤 kind=summon 的式神（{sid} 不是）")
            elif step.op in ("transform", "replace"):
                sid = (step.model_extra or {}).get("into")
                d = self.shikigami.get(sid)
                want_kind = "transform" if step.op == "transform" else "replace"
                if d is None:
                    errors.append(f"{where}: {step.op} 引用的式神 {sid} 不存在")
                elif d.kind != want_kind:
                    errors.append(f"{where}: {step.op} 只能指向 kind={want_kind} 的式神（{sid} 不是）")
            elif step.op == "emit":
                # 自定义事件须在核心事件或 events.yaml 中声明
                event_name = (step.model_extra or {}).get("event")
                if event_name not in known_events:
                    errors.append(f"{where}: emit 引用的事件 {event_name} 未声明")
            errors += self._check_target(step.target, where)
        return errors

    # ---------- 白名单校验（条件键 / 目标过滤键 / 动态数值键，core/registry.py 登记） ----------

    def _check_key_whitelists(self, raw: dict, where: str) -> list[str]:
        """对一个原始 yaml（含全部版本快照）做三类键白名单校验。"""
        path = self.paths.get(raw.get("id"))
        if path:
            where = f"{where}（{path}）"
        errors: list[str] = []
        for snap in (raw.get("versions") or {}).get("history") or []:
            date = snap.get("date")
            at = f"{where} @{date}"
            for blk_where, block in self._iter_raw_blocks(snap):
                errors += self._check_raw_block(block, f"{at}的{blk_where}")
            # 牌面级条件通道
            pc = snap.get("play_condition")
            if isinstance(pc, dict):
                errors += self._check_condition_keys(pc, f"{at}的 play_condition")
            for cm in snap.get("conditional_mods") or []:
                if isinstance(cm, dict):
                    cond = {k: v for k, v in cm.items() if k != "mods"}
                    errors += self._check_condition_keys(cond, f"{at}的 conditional_mods")
            for ck in snap.get("conditional_keywords") or []:
                if isinstance(ck, dict):
                    for k in ck:
                        if k not in CONDITIONAL_KEYWORD_KEYS:
                            errors.append(
                                f"{at}的 conditional_keywords: 未登记的条件关键字算子 {k}"
                                f"（core/registry.py CONDITIONAL_KEYWORD_KEYS）")
            errors += self._check_target_keys(snap.get("target"), f"{at}的 target")
            errors += self._check_target_keys(snap.get("target2"), f"{at}的 target2")
            for m in snap.get("methods") or []:
                if isinstance(m, dict):
                    errors += self._check_target_keys(
                        m.get("target"), f"{at}的使用方式[{m.get('id')}]target")
        return errors

    @staticmethod
    def _iter_raw_blocks(snap: dict):
        """产出一个版本快照中的全部效果块（字段名, 块 dict）。"""
        for field in ("effects", "response", "alt_effects", "countdown_effects",
                      "ability", "draw_trigger"):
            blk = snap.get(field)
            if isinstance(blk, dict):
                yield field, blk
        for field in ("abilities", "triggers", "temp_grants"):
            for i, blk in enumerate(snap.get(field) or []):
                if isinstance(blk, dict):
                    yield f"{field}[{i}]", blk
        for m in snap.get("methods") or []:
            if isinstance(m, dict) and isinstance(m.get("effects"), dict):
                yield f"使用方式[{m.get('id')}]effects", m["effects"]

    def _check_raw_block(self, block: dict, where: str) -> list[str]:
        errors: list[str] = []
        cond = block.get("condition")
        if isinstance(cond, dict):
            errors += self._check_condition_keys(cond, f"{where}的 condition")
        for i, step in enumerate(block.get("steps") or []):
            if isinstance(step, dict):
                errors += self._check_raw_step(step, f"{where} step[{i}]")
        return errors

    def _check_raw_step(self, step: dict, where: str) -> list[str]:
        """校验一个原始 step dict：条件键、目标过滤键、动态数值键（含嵌套子步骤）。"""
        errors: list[str] = []
        cond = step.get("condition")
        if isinstance(cond, dict):
            errors += self._check_condition_keys(cond, f"{where}的 condition")
        fx = step.get("force_x1_if")
        if isinstance(fx, dict):
            errors += self._check_condition_keys(fx, f"{where}的 force_x1_if")
        errors += self._check_target_keys(step.get("target"), f"{where}的 target")
        for param, table in (("amount", DYNAMIC_VALUE_KEYS),
                             ("power", DYNAMIC_VALUE_KEYS),
                             ("count", COUNT_VALUE_KEYS),
                             ("times", COUNT_VALUE_KEYS)):
            val = step.get(param)
            if isinstance(val, dict):
                for k in val:
                    if k not in table:
                        errors.append(
                            f"{where}: 未登记的动态数值键 {param}.{k}"
                            f"（core/registry.py {'DYNAMIC_VALUE_KEYS' if table is DYNAMIC_VALUE_KEYS else 'COUNT_VALUE_KEYS'}）")
        req = step.get("require")
        if isinstance(req, dict):
            for k in req:
                if k not in ("key", "ge"):
                    errors.append(f"{where}: 未登记的 require 键 {k}（仅支持 key/ge）")
        for nested in ("steps", "then"):  # repeat 子步骤组 / luck_roll then 子步骤
            for j, sub in enumerate(step.get(nested) or []):
                if isinstance(sub, dict):
                    errors += self._check_raw_step(sub, f"{where} {nested}[{j}]")
        return errors

    @staticmethod
    def _check_condition_keys(cond: dict, where: str) -> list[str]:
        return [f"{where}: 未登记的条件键 {k}（core/registry.py CONDITION_KEYS）"
                for k in cond if k not in CONDITION_KEYS]

    @staticmethod
    def _check_target_keys(t, where: str) -> list[str]:
        if not isinstance(t, dict):
            return []
        return [f"{where}: 未登记的目标过滤键 {k}（core/registry.py TARGET_EXTRA_KEYS）"
                for k in t if k not in ("kind", "pool", "key")
                and k not in TARGET_EXTRA_KEYS]
