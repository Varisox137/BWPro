"""测试数据工厂：所有机制测试使用程序内构造的数据，不依赖 db/ 下的 YAML。

真实卡牌数据按维护者要求暂不放入仓库（见 thoughts.txt），
db/ 目录下的 YAML 只存放经确认的正式数据。
"""
from __future__ import annotations

from core.model import GameConfig
from core.setup import new_game
from db.loader import CardDatabase
from db.schema import (
    CardDef,
    EffectBlock,
    PlayMethod,
    ShikigamiDef,
    Step,
    TargetSpec,
)

VER = 20260720

# 常用类型别名，测试里直接用
T = TargetSpec


def shiki(sid: int = 100101, name: str | None = None, kind: str = "shikigami",
          faction: str = "红莲", power: int = 3, health: int = 4,
          ability: EffectBlock | None = None, keep_buffs: bool = False,
          origin: str | None = None, **kw) -> ShikigamiDef:
    """构造一个测试用式神定义。默认 version 为 VER，可用 kw 覆盖任意字段。"""
    return ShikigamiDef(id=sid, version=VER, name=name or f"式神{sid}", kind=kind,
                        faction=faction, origin=origin, power=power, health=health,
                        ability=ability, keep_buffs=keep_buffs, **kw)


def card(cid: int, shikigami: int | None = 100101, name: str | None = None,
         cost: int = 1, level: int = 1, card_type: str = "spell",
         keywords=(), tags=(), target: TargetSpec | None = None, steps=(),
         when: str = "on_play", block_kw: dict | None = None,
         methods=(), token: bool = False, playable_when_defeated: bool = False, **kw) -> CardDef:
    """构造一张测试用卡牌定义。

    - steps: 效果块内的 Step 列表；block_kw 可覆盖 mode/timing/condition 等。
    - when: 效果块触发事件；on_play 表示打出时触发。
    - token=True 的测试卡请使用 51+ 号段，避免与 base_db 的 01-08 可构筑卡冲突。
    """
    effects = EffectBlock(when=when, steps=list(steps), **(block_kw or {}))
    return CardDef(id=cid, version=VER, name=name or f"卡{cid}", shikigami=shikigami,
                   card_type=card_type, tags=list(tags), keywords=list(keywords), token=token,
                   playable_when_defeated=playable_when_defeated, level=level, cost=cost,
                   target=target or TargetSpec(), effects=effects,
                   methods=list(methods), **kw)


def method(mid: str, **kw) -> PlayMethod:
    """构造一个 PlayMethod（多择使用方式）。"""
    return PlayMethod(id=mid, **kw)


def block(*steps: Step, **kw) -> EffectBlock:
    """构造一个 EffectBlock（默认 when=on_play）。"""
    return EffectBlock(steps=list(steps), **kw)


def dmg(amount: int, target: TargetSpec | None = None) -> Step:
    """构造一个 damage 动作 Step。"""
    return Step(op="damage", amount=amount, target=target)


def db_of(shikigami, cards, events=()) -> CardDatabase:
    """从列表组装一个 CardDatabase（测试用，不读取 YAML）。"""
    return CardDatabase(
        cards={c.id: c for c in cards},
        shikigami={s.id: s for s in shikigami},
        custom_events=set(events),
    )


TEAM = [100101, 100102, 100103, 100104]


def base_db() -> CardDatabase:
    """4 个无效果式神（派系 红莲/红莲/紫岩/无相）+ 每式神 8 种空白法术牌。"""
    s = [
        shiki(100101, power=3, health=4, faction="红莲"),
        shiki(100102, power=1, health=6, faction="红莲"),
        shiki(100103, power=2, health=6, faction="紫岩"),
        shiki(100104, power=2, health=5, faction="无相"),
    ]
    cards = []
    for sid in TEAM:
        for n in range(1, 9):
            cards.append(card(sid * 100 + n, shikigami=sid, level=(n - 1) % 3 + 1))
    return db_of(s, cards)


def deck_of(*sids: int) -> list[int]:
    """合法卡组：每式神前 4 种各 ×2（共 32 张）。"""
    return [sid * 100 + n for sid in sids for n in range(1, 5) for _ in range(2)]


def mk_game(db: CardDatabase, seed: int = 1, team=None, **kw):
    """确定性测试对局：固定先后手/式神顺序，跳过调度（可用 kw 覆盖）。

    默认启用 auto_skip_upgrade，让测试不必每回合手动跳过升级阶段；
    需要测试升级阶段的用例可传 auto_skip_upgrade=False。
    """
    team = team or TEAM
    deck = deck_of(*team)
    kw.setdefault("shuffle_team", False)
    kw.setdefault("mulligan", False)
    if "config" not in kw:
        skip = kw.pop("auto_skip_upgrade", True)
        kw["config"] = GameConfig(auto_skip_upgrade=skip)
    return new_game(db, ("A", list(team), list(deck)), ("B", list(team), list(deck)),
                    seed=seed, first=0, **kw)
