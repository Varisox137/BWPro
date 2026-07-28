"""组卡规则校验。

天梯（标准）规则：
- 恰好 4 名出战式神（kind=shikigami）
- 至多 2 个不同派系（无相不计入）
- 同源式神（原形/SP 等，origin 相同）不能同时出战
- 每名式神恰好 8 张牌（含挂载的协战牌）；同名卡在同一式神中最多 2 张、
  在全卡组中最多 2 张；不同名卡牌不超过 8 种（构筑序号仅 01-08，结构性保证）
- 专属牌构筑序号仅开放 01-08；协战牌暂只开放序号 21
- 协战牌：不要求两位所属式神均出战——任一出战即可编入，作为该式神 8 张牌
  的一部分（两位都在队时挂到剩余配额较多者名下）；构筑界面同时列入两位所属
  式神的可选卡牌；与出战式神数量/派系等无关
- 中立牌不可编入卡组（中立牌实质为系统给予或效果生成的衍生卡）
- token=true 的衍生卡不可编入卡组；只能携带出战式神的卡牌
- 对局模式卡组约束：validate_deck 接受 DeckRules 参数（出战式神数量、各式神
  带卡数量、同名限值均可调）；传入 None 表示无约束，直接判合法
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeckRules:
    """对局模式卡组约束（默认值为天梯规则）。

    - required_shikigami：出战式神数量（1~4）
    - cards_per_shikigami：各式神带卡数量（>0），按队伍顺序一一对应，
      长度须等于 required_shikigami
    - max_copies_per_name：同名卡在同一式神中的限制
    - max_copies_deck：同名卡在全卡组中的限制
    其余字段（派系/构筑序号等）为天梯结构性规则，暂不对模式开放。
    """

    required_shikigami: int = 4
    cards_per_shikigami: list[int] = field(default_factory=lambda: [8, 8, 8, 8])
    max_copies_per_name: int = 2
    max_copies_deck: int = 2
    max_factions: int = 2  # 无相不计入
    max_kinds_per_shikigami: int = 8
    # 可构筑的卡牌序号（id 末两位）：专属牌 01-08；协战牌暂只开放 21
    buildable_suffixes: frozenset = field(default_factory=lambda: frozenset(range(1, 9)))
    reinforce_suffixes: frozenset = field(default_factory=lambda: frozenset({21}))

    def __post_init__(self) -> None:
        if not 1 <= self.required_shikigami <= 4:
            raise ValueError(f"出战式神数量须在 1~4（当前 {self.required_shikigami}）")
        if len(self.cards_per_shikigami) != self.required_shikigami:
            raise ValueError(f"各式神带卡数量列表长度须等于出战式神数量 "
                             f"{self.required_shikigami}（当前 {len(self.cards_per_shikigami)}）")
        if any(n <= 0 for n in self.cards_per_shikigami):
            raise ValueError("各式神带卡数量须为正整数")
        object.__setattr__(self, "cards_per_shikigami", tuple(self.cards_per_shikigami))


STANDARD_RULES = DeckRules()


def rules_summary(rules: DeckRules = STANDARD_RULES) -> list[str]:
    """对局模式卡组约束的可读描述（构筑界面的规则提示）；取值与 validate_deck
    检查项一一对应，规则调整时只需改 DeckRules。"""
    cps = rules.cards_per_shikigami
    per = str(cps[0]) if len(set(cps)) == 1 else "/".join(str(n) for n in cps)
    return [
        f"出战式神 {rules.required_shikigami} 名（不重复）；派系至多 "
        f"{rules.max_factions} 个（无相不计入）；同源式神不能同时出战",
        f"每名式神恰好 {per} 张牌；不同名卡不超过 {rules.max_kinds_per_shikigami} 种",
        f"同名卡在同一式神限 {rules.max_copies_per_name}、"
        f"在全卡组限 {rules.max_copies_deck}",
    ]


def validate_deck(db, shikigami_ids: list[int], card_ids: list[int],
                  rules: DeckRules | None = STANDARD_RULES) -> list[str]:
    """返回全部错误信息（空列表 = 卡组合法）。rules=None：无约束，直接判合法。"""
    if rules is None:
        return []
    errors: list[str] = []
    # 各出战式神的带卡配额（按队伍顺序）
    quota = {sid: n for sid, n in zip(shikigami_ids, rules.cards_per_shikigami)}
    if len(shikigami_ids) != rules.required_shikigami:
        errors.append(f"出战式神须为 {rules.required_shikigami} 名"
                      f"（当前 {len(shikigami_ids)} 名）")
    if len(set(shikigami_ids)) != len(shikigami_ids):
        errors.append("出战式神不能重复")
    factions: set[str] = set()
    origins: Counter[str] = Counter()
    for sid in shikigami_ids:
        d = db.shikigami.get(sid)
        if d is None:
            errors.append(f"式神 {sid} 不存在")
            continue
        if d.kind != "shikigami":
            errors.append(f"《{d.name}》（{sid}）是召唤物，不能编入队伍")
            continue
        if d.faction != "无相":
            factions.add(d.faction)
        # origin 为空时回退到式神名；两个无 origin 的不同式神若同名才会误判，数据侧应避免
        origins[d.origin or d.name] += 1
    if len(factions) > rules.max_factions:
        errors.append(f"派系 {sorted(factions)} 超过 {rules.max_factions} 个（无相不计入）")
    for o, n in origins.items():
        if n >= 2:
            errors.append(f"同源式神《{o}》不能同时出战")
    by_owner: dict[int, list] = {}
    reinforce: list[tuple[object, list[int]]] = []  # (协战牌, 在队所属式神们)
    for cid in card_ids:
        c = db.cards.get(cid)
        if c is None:
            errors.append(f"卡牌 {cid} 不存在")
            continue
        if c.shikigami is None:
            errors.append(f"《{c.name}》是中立牌，不可编入卡组（中立牌由系统/效果生成）")
            continue
        if c.token:
            errors.append(f"《{c.name}》是衍生卡，不能编入卡组")
            continue
        suffix = cid % 100
        if c.card_type == "reinforce":
            if suffix not in rules.reinforce_suffixes:
                errors.append(f"《{c.name}》（{cid}）：协战牌序号 {suffix:02d} 未开放构筑"
                              f"（暂只开放 {sorted(rules.reinforce_suffixes)}）")
                continue
            # 协战牌：两位所属式神任一出战即可编入（不要求均出战）
            owners = [o for o in (c.shikigami, c.shikigami2) if o in shikigami_ids]
            if not owners:
                errors.append(f"《{c.name}》的所属式神（{c.shikigami} / {c.shikigami2}）均未出战")
                continue
            reinforce.append((c, owners))
            continue
        if suffix not in rules.buildable_suffixes:
            errors.append(f"《{c.name}》（{cid}）：卡牌序号 {suffix:02d} 未开放构筑"
                          f"（专属牌仅 {min(rules.buildable_suffixes):02d}"
                          f"-{max(rules.buildable_suffixes):02d}）")
            continue
        if c.shikigami not in shikigami_ids:
            errors.append(f"《{c.name}》属于未出战的式神 {c.shikigami}")
            continue
        by_owner.setdefault(c.shikigami, []).append(c)
    # 协战牌作为所属式神配额的一部分：挂到剩余配额较多（当前张数-配额最小）的
    # 在队所属式神名下；数量相同时取列表中先出现者（规则未指定，属实现细节）。
    for c, owners in reinforce:
        pick = min(owners, key=lambda o: len(by_owner.get(o, [])) - quota.get(o, 0))
        by_owner.setdefault(pick, []).append(c)
    # 每名出战式神恰好 cards_per_shikigami[i] 张牌（含挂载的协战牌）
    for sid in shikigami_ids:
        d = db.shikigami.get(sid)
        if d is None or d.kind != "shikigami":
            continue
        n = len(by_owner.get(sid, []))
        # 式神数与带卡数列表不一致时数量错误已在前面报出，跳过逐位配额
        if sid not in quota:
            continue
        if n != quota[sid]:
            errors.append(f"{d.name}: 卡牌须恰好 {quota[sid]} 张（当前 {n} 张）")
    # 同名卡全卡局限 max_copies_deck（含专属牌与协战牌，与挂在谁名下无关）
    all_names = Counter(c.name for cards in by_owner.values() for c in cards)
    for name, n in all_names.items():
        if n > rules.max_copies_deck:
            errors.append(f"《{name}》×{n} 超过全卡组限 {rules.max_copies_deck}")
    for owner, cards in by_owner.items():
        who = db.shikigami[owner].name
        names = Counter(c.name for c in cards)
        if len(names) > rules.max_kinds_per_shikigami:
            errors.append(f"{who}: 卡牌种类 {len(names)} 超过上限"
                          f" {rules.max_kinds_per_shikigami}")
        for name, n in names.items():
            if n > rules.max_copies_per_name:
                errors.append(f"{who}: 《{name}》×{n} 超过同式神限"
                              f" {rules.max_copies_per_name}")
    return errors
