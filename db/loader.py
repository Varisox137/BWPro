"""卡牌数据库：从 YAML 文件加载并校验。

校验在加载时完成——数据错误（未知动作/事件/目标池、悬空引用、id 号段不符等）
在对局开始前暴露，而不是打到一半才崩。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.actions import ACTIONS
from core.events import CORE_EVENTS
from core.targets import POOLS
from db.schema import (
    CARD_TYPES,
    FACTIONS,
    KEYWORDS,
    NEUTRAL_PREFIX,
    RARITIES,
    SUBTYPES,
    CardDef,
    EffectBlock,
    ShikigamiDef,
)

DB_ROOT = Path(__file__).parent


class CardDatabase:
    def __init__(
        self,
        cards: dict[int, CardDef],
        shikigami: dict[int, ShikigamiDef],
        custom_events: set[str],
    ) -> None:
        self.cards = cards
        self.shikigami = shikigami
        self.custom_events = custom_events

    @classmethod
    def load(cls, root: Path | str | None = None, strict: bool = True) -> "CardDatabase":
        root = Path(root) if root else DB_ROOT
        cards = cls._load_dir(root / "cards", CardDef)
        shikigami = cls._load_dir(root / "shikigami", ShikigamiDef)
        custom_events: set[str] = set()
        events_file = root / "events.yaml"
        if events_file.exists():
            for entry in yaml.safe_load(events_file.read_text(encoding="utf-8")) or []:
                custom_events.add(entry["name"])
        db = cls(cards, shikigami, custom_events)
        errors = db.validate()
        if errors and strict:
            raise RuntimeError("卡牌数据库校验失败：\n" + "\n".join(errors))
        return db

    @staticmethod
    def _load_dir(path: Path, model: type) -> dict:
        out: dict[int, object] = {}
        if not path.exists():
            return out
        for f in sorted(path.glob("*.yaml")):
            obj = model.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
            if obj.id in out:
                raise RuntimeError(f"id 重复: {obj.id}（{f.name}）")
            out[obj.id] = obj
        return out

    def validate(self) -> list[str]:
        """返回全部错误信息（空列表 = 通过）。"""
        errors: list[str] = []
        known_events = CORE_EVENTS | self.custom_events | {"on_play"}
        for s in self.shikigami.values():
            where = f"式神 {s.id}《{s.name}》"
            if s.kind == "shikigami":
                if not 100_000 <= s.id <= 199_999:
                    errors.append(f"{where}: 式神 id 须为 1avvss（1 + 1 位异画位 + 2 位卡包 + 2 位序号）")
            else:  # summon：8 位 = 从属式神 id + 序号（衍生物从 99 开始递减分配；结构与卡牌相同）
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
            elif c.shikigami2 is not None:
                errors.append(f"{where}: 仅协战牌可以有 shikigami2")
            if c.card_type not in CARD_TYPES:
                errors.append(f"{where}: 未知主类型 {c.card_type}")
            if c.subtype is not None and c.subtype not in SUBTYPES:
                errors.append(f"{where}: 未知子类型 {c.subtype}")
            if c.rarity is not None and c.rarity not in RARITIES:
                errors.append(f"{where}: 未知稀有度 {c.rarity}（R/SR/SSR）")
            for kw in c.keywords:
                if kw not in KEYWORDS:
                    errors.append(f"{where}: 未知关键词 {kw}")
            errors += self._check_target(c.target, where)
            if "trigger" in c.keywords and c.effects.when == "on_play":
                errors.append(f"{where}: 响应牌的 effects.when 必须是触发事件")
            errors += self._check_block(c.effects, known_events, where)
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
        return errors

    def _check_target(self, t: TargetSpec | None, where: str) -> list[str]:
        """校验 TargetSpec：kind/pool/key 的基本合法性。"""
        errors: list[str] = []
        if t is None:
            return errors
        if t.kind in ("all", "choose") and t.pool not in POOLS:
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
            elif step.op == "emit":
                # 自定义事件须在核心事件或 events.yaml 中声明
                event_name = (step.model_extra or {}).get("event")
                if event_name not in known_events:
                    errors.append(f"{where}: emit 引用的事件 {event_name} 未声明")
            errors += self._check_target(step.target, where)
        return errors
