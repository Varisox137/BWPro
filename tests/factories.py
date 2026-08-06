"""测试数据工厂：所有机制测试使用程序内构造的数据，不依赖 db/ 下的 YAML。

真实卡牌数据按维护者要求暂不放入仓库（见 thoughts.txt），
db/ 目录下的 YAML 只存放经确认的正式数据。
"""
from __future__ import annotations

from core.model import CardInstance, GameConfig
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

# 常用目标：choose 一个敌方式神
CHOOSE_ENEMY = T(kind="choose", pool="enemy_shikigami")


def shiki(sid: int = 100101, name: str | None = None, kind: str = "shikigami",
          faction: str = "红莲", power: int = 3, health: int = 4,
          ability: EffectBlock | None = None,
          origin: str | None = None, **kw) -> ShikigamiDef:
    """构造一个测试用式神定义。默认 version 为 VER，可用 kw 覆盖任意字段。"""
    return ShikigamiDef(id=sid, version=VER, name=name or f"式神{sid}", kind=kind,
                        faction=faction, origin=origin, power=power, health=health,
                        ability=ability, **kw)


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


def give(game, player_index: int, defn_id: int) -> CardInstance:
    """测试辅助：直接发一张牌到玩家手牌（hand_seq 由 move_card 自动分配）。"""
    st = game.state
    card = CardInstance(uid=st.next_uid, id=defn_id)
    st.next_uid += 1
    game.move_card(st.players[player_index], card, "hand")
    return card


def move(game, player: int, index: int) -> None:
    """把式神移入战斗区（调试指令）。"""
    game.apply({"op": "debug_move", "args": {"player": player, "index": index}})


def pass_turns(game, n: int = 1) -> None:
    """连续 end_turn n 次。"""
    for _ in range(n):
        game.apply({"op": "end_turn"})


def battle_setup(game, levels: dict[int, int] | None = None):
    """数据测试常用开局：A 9 鬼火、B 无补偿护甲、B 全员 1 级在场、A 按 levels
    定级（默认 {0: 1}）。返回 (pa, pb)。"""
    pa, pb = game.state.players
    pa.orb = 9
    pb.shield = 0
    for s in pb.shikigami:
        s.level = 1
    for i, lv in (levels or {0: 1}).items():
        pa.shikigami[i].level = lv
    return pa, pb


def play(game, player_index: int, defn_id: int, target=None) -> None:
    """发一张牌到玩家手牌并打出（可带目标）。"""
    cmd = {"op": "play_card", "uid": give(game, player_index, defn_id).uid}
    if target is not None:
        cmd["target"] = target
    game.apply(cmd)


def ichimokuren(db: CardDatabase, sid: int = 100104) -> None:
    """一目连基础能力：形态离场/被消灭时触发其倒计时效果。"""
    db.shikigami[sid].ability = EffectBlock(
        when="on_form_destroyed", condition={"target_shikigami": "self"},
        steps=[Step(op="trigger_form_countdown")])


def po_form(db: CardDatabase, cid: int = 10010451, sid: int = 100104,
            token: bool = True) -> int:
    """风符·破型：一目连倒计时 2 形态（3/6），触发时投射 3。"""
    db.cards[cid] = card(
        cid, shikigami=sid, card_type="form", level=1,
        form_power=3, form_health=6, countdown=2, token=token,
        countdown_effects=block(
            Step(op="damage", amount=3, target=T(kind="all", pool="projectile"))))
    return cid


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
