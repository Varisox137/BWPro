"""对局组装：由静态数据 + 牌表构建初始 GameState 并开局。

- new_game 默认强制组卡校验（db/deck.py）；测试特殊场景可传 check_deck=False 跳过。
- 先后手随机（种子决定，双方均等概率）；也可用 first= 指定（测试用）。
"""
from __future__ import annotations

import random

from core.engine import Game
from core.model import CardInstance, GameConfig, GameState, PlayerState, ShikigamiState
from db.deck import validate_deck


def build_player(
    db,
    name: str,
    shikigami_ids: list[int],
    card_ids: list[int],
    config: GameConfig,
    uid_start: int = 1,
) -> tuple[PlayerState, int]:
    """构建玩家初始状态，返回 (PlayerState, 下一个可用 uid)。

    式神初始 0 级未在场；开局时最左侧自动升至 1 级（见 engine.start）。
    home_slot 记录准备区编号（1-4）——回合开始战斗区式神退回时使用；召唤物为 None。
    """
    shikigami = []
    for idx, sid in enumerate(shikigami_ids):
        d = db.shikigami[sid]
        shikigami.append(ShikigamiState(
            id=sid, kind=d.kind, faction=d.faction,
            home_slot=idx + 1, entry_order=idx + 1,
            base_power=d.power, base_health=d.health, health=d.health,
            ext={"max_power": d.power},  # 力量历史峰值初值 = 基础力量（断臂记账）
            perm_keywords=list(d.keywords)))  # 先天关键字（贯通等）按永久类别入列
    uid = uid_start
    deck = []
    for cid in card_ids:
        deck.append(CardInstance(uid=uid, id=cid))
        uid += 1
    p = PlayerState(
        name=name,
        health=config.player_health,
        max_health=config.player_health,
        shikigami=shikigami,
    )
    p.deck.extend(deck)
    return p, uid


def new_game(
    db,
    p1: tuple[str, list[int], list[int]],
    p2: tuple[str, list[int], list[int]],
    seed: int = 0,
    config: GameConfig | None = None,
    check_deck: bool = True,
    first: int | None = None,
    shuffle_team: bool = True,
    mulligan: bool = True,
) -> Game:
    """p1/p2 = (玩家名, 式神 id 列表, 牌组卡牌 id 列表)。

    first 指定先手（0/1）；None 时按 seed 随机（双方均等概率）。
    对局状态中 players[0] 恒为先手。
    shuffle_team：游戏开始阶段随机决定双方式神顺序（测试可关闭以固定下标）。
    mulligan：进入调度阶段（双方各 mulligan_count 次，ready 后开战）；测试可关闭。
    """
    config = config or GameConfig()
    if check_deck:
        for name, shiki_ids, card_ids in (p1, p2):
            errors = validate_deck(db, shiki_ids, card_ids)
            if errors:
                raise ValueError(f"{name} 卡组不合法：\n" + "\n".join(errors))
    rng = random.Random(seed)
    if first is None:
        first = rng.randint(0, 1)
    if first == 1:
        p1, p2 = p2, p1
    if shuffle_team:  # 随机决定双方式神顺序（home_slot 按洗牌后位置分配）
        p1 = (p1[0], rng.sample(p1[1], len(p1[1])), p1[2])
        p2 = (p2[0], rng.sample(p2[1], len(p2[1])), p2[2])
    a, n1 = build_player(db, *p1, config, uid_start=1)
    b, n2 = build_player(db, *p2, config, uid_start=n1)
    state = GameState(players=[a, b], next_uid=n2, config=config,
                      phase="mulligan" if mulligan else "battle")
    game = Game(state, db, seed=seed)
    game.start()
    return game
