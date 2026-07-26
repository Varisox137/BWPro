"""组卡规则校验。

天梯（标准）规则：
- 恰好 4 名出战式神（kind=shikigami）
- 至多 2 个不同派系（无相不计入）
- 同源式神（原形/SP 等，origin 相同）不能同时出战
- 每名式神恰好 8 张牌（含挂载的协战牌）；每种（按名称）最多 2 张；
  不同名卡牌不超过 8 种（构筑序号仅 01-08，结构性保证）
- 专属牌构筑序号仅开放 01-08；协战牌暂只开放序号 21
- 协战牌：不要求两位所属式神均出战——任一出战即可编入，作为该式神 8 张牌
  的一部分（两位都在队时挂到种类数较少者名下）；同名协战牌仍限 2；
  与出战式神数量/派系等无关
- 中立牌不可编入卡组（中立牌实质为系统给予或效果生成的衍生卡）
- token=true 的衍生卡不可编入卡组；只能携带出战式神的卡牌
- 将来可能引入新模式玩法：validate_deck 接受 DeckRules 参数，各限制均可调
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeckRules:
    """组卡规则参数（对应不同对局模式；默认值为天梯规则）。"""

    required_shikigami: int = 4
    max_factions: int = 2  # 无相不计入
    cards_per_shikigami: int = 8  # 每名式神恰好 N 张牌（含挂载的协战牌）
    max_kinds_per_shikigami: int = 8
    max_copies_per_name: int = 2
    # 可构筑的卡牌序号（id 末两位）：专属牌 01-08；协战牌暂只开放 21
    buildable_suffixes: frozenset = field(default_factory=lambda: frozenset(range(1, 9)))
    reinforce_suffixes: frozenset = field(default_factory=lambda: frozenset({21}))


STANDARD_RULES = DeckRules()

# 兼容性别名（client/deckbuilder.py 等引用）
REQUIRED_SHIKIGAMI = STANDARD_RULES.required_shikigami
MAX_FACTIONS = STANDARD_RULES.max_factions
MAX_KINDS_PER_SHIKIGAMI = STANDARD_RULES.max_kinds_per_shikigami
MAX_COPIES_PER_NAME = STANDARD_RULES.max_copies_per_name


def validate_deck(db, shikigami_ids: list[int], card_ids: list[int],
                  rules: DeckRules = STANDARD_RULES) -> list[str]:
    """返回全部错误信息（空列表 = 卡组合法）。"""
    errors: list[str] = []
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
    # 协战牌同名仍限 2（全局计数，与挂在哪位所属式神名下无关）
    for name, n in Counter(c.name for c, _ in reinforce).items():
        if n > rules.max_copies_per_name:
            errors.append(f"《{name}》×{n} 超过限 {rules.max_copies_per_name}"
                          f"（协战牌同名仍限 {rules.max_copies_per_name}）")
    # 协战牌作为所属式神 8 张牌的一部分：挂到种类数较少的在队所属式神名下；
    # 数量相同时取列表中先出现者（规则未指定，属于实现细节）。
    for c, owners in reinforce:
        pick = min(owners, key=lambda o: len({x.name for x in by_owner.get(o, [])}))
        by_owner.setdefault(pick, []).append(c)
    # 每名出战式神恰好 cards_per_shikigami 张牌（含挂载的协战牌）
    for sid in shikigami_ids:
        d = db.shikigami.get(sid)
        if d is None or d.kind != "shikigami":
            continue
        n = len(by_owner.get(sid, []))
        if n != rules.cards_per_shikigami:
            errors.append(f"{d.name}: 卡牌须恰好 {rules.cards_per_shikigami} 张"
                          f"（当前 {n} 张）")
    for owner, cards in by_owner.items():
        who = db.shikigami[owner].name
        names = Counter(c.name for c in cards)
        if len(names) > rules.max_kinds_per_shikigami:
            errors.append(f"{who}: 卡牌种类 {len(names)} 超过上限"
                          f" {rules.max_kinds_per_shikigami}")
        for name, n in names.items():
            if n > rules.max_copies_per_name:
                errors.append(f"{who}: 《{name}》×{n} 超过限 {rules.max_copies_per_name}")
    return errors
