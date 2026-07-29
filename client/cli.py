"""本地热座 CLI 客户端：两名玩家共用终端轮流操作。

所有指令通过 Game.apply 提交，与将来联机客户端走同一 cmd dict 协议（见 CLAUDE.md）。
非回合方没有任何输入机会——响应牌由引擎自动结算（规则：敌方回合零选择、响应必发）。

运行：uv run python -m client.cli
一级菜单：卡组构筑（client/deckbuilder.py）/ 本地热坐 / 联机对战（client/net.py，
服务端见 server/main.py）。数据为正式 YAML（CardDatabase.load：db/cards、
db/shikigami）；热坐与联机开局前从本地卡组文件（~/.bwp.decks.json，
db/deckstore.py）选择卡组，文件为空时回退到卡组码输入或默认卡组。

显示：己方场上式神名与己方手牌卡牌名按座次 1-4 着色（亮黄/亮青/亮紫/亮红）；
倒计时/战力/保甲/免疫/延迟能力/鼓舞/手牌修饰（增强/费用修正）均在场况中显示。
颜色仅在 TTY 下启用（管道输出或 NO_COLOR 环境变量时自动关闭）。
"""
from __future__ import annotations

import os
import time
from client import cardfmt, deckbuilder, textutil, tui
from client.textutil import display_width as _display_width, pad as _pad
from core.engine import Game, IllegalAction
from core.model import Ref
from core.setup import new_game
from db.loader import CardDatabase

HELP = """指令（括号内为 alias，序号从 1 开始）：
  play (p)   <手牌序号> [子选项] [目标] [方式]   使用手牌；如 play 1 e1 或 p 1 e1 burst
                                               （协战牌先给子选项序号 0/1，如 p 3 0）
  assault (a) <式神序号> [目标]          式神出击（耗 1 鬼火 + 每回合 1 次次数；追猎可指定敌方式神目标，如 a 1 e2）
  upgrade (u) <式神序号>               升级式神（只能升己方当前最低级）
  end (e)                              结束回合
  state (st)                           重印场面
  log (l) [n]                          查看最近 n 条日志（默认 10）
  debug (d) <子命令> [参数...]          调试命令（见 debug help）
  help (h) / quit (q)

目标代码：e=敌方 f=己方；e0=敌方 0 号式神，f1=己方 1 号式神，ep=敌方牌手，fp=己方牌手

座次颜色：1=黄 2=青 3=紫 4=红（己方场上式神名与手牌卡牌名按座次着色；
管道输出或 NO_COLOR 环境变量时自动关闭）
"""

COMMAND_ALIASES = {
    "p": "play",
    "a": "assault",
    "u": "upgrade",
    "e": "end",
    "st": "state",
    "l": "log",
    "d": "debug",
    "h": "help",
    "q": "quit",
    "exit": "quit",
}

DEBUG_HELP = """调试指令（仅本地开发/测试使用）：
  give_card <player> <card_id> [zone=hand] [count=1]   生成卡牌到区域
  set_stat <target> <key> <value>                      直接修改实体属性
  grant <target> <keyword> [cls]                       授予式神关键字（cls: one_shot/continuous/perm，缺省按天然类别）
  ungrant <target> <keyword>                           移除一个关键字实例
  play_card <player> <uid> [target] [method]           强制使用牌
  assault <player> <index>                             强制出击
  draw <player> [count=1]                              强制抽牌
  set_turn [active] [turn]                             设置当前回合方/半回合数

  key 示例：health, orb, shield, level, defeated, despawned
  value 为 bool 时：true/false
  keyword 示例：combo, initiative, piercing, pierce, remote, unyielding, haste, barrier
"""


# ---------- 结算明细展示 ----------

SETTLE_INTERVAL = float(os.environ.get("BWP_SETTLE_INTERVAL", "0.4"))  # 每条明细的打印间隔（秒）


def drain_settle(game: Game, seen: int, interval: float | None = None) -> int:
    """打印自游标 seen 以来积累的结算明细（GameState.settle_log 增量），返回新游标。

    空闲点（回合开始/结束阶段结算完、主要阶段每次指令结算完）调用：0.4s 每条
    逐条打印，整块前后各空一行；无新增明细时不输出（不空打印空行）。
    纯展示层行为——引擎/服务端只记录，不 sleep；interval 供测试置 0。
    """
    lines = game.state.settle_log[seen:]
    if not lines:
        return seen
    delay = SETTLE_INTERVAL if interval is None else interval
    print("")
    for line in lines:
        print(line)
        if delay > 0:
            time.sleep(delay)
    print("")
    return len(game.state.settle_log)


def parse_ref(code: str, active: int) -> Ref:
    """把目标代码解析为 Ref：f=己方 e=敌方 p=牌手 数字=式神下标。"""
    code = code.strip().lower()
    player = active if code.startswith("f") else 1 - active
    rest = code[1:]
    if rest == "p":
        return Ref(player=player)
    return Ref(player=player, shikigami=int(rest))


def ref_code(ref: Ref, active: int) -> str:
    """把 Ref 渲染为目标代码（parse_ref 的逆）。"""
    side = "f" if ref.player == active else "e"
    return f"{side}p" if ref.shikigami is None else f"{side}{ref.shikigami}"


# ---------- 座次配色 ----------

# 颜色判定与包裹委托 client/textutil（测试可 monkeypatch textutil.USE_COLOR）
_use_color = textutil.use_color
_colored = textutil.colored

SEAT_COLORS = [93, 96, 95, 91]  # 座次 1-4：亮黄/亮青/亮紫/亮红（亮色系）


def _seat_map(p) -> dict[int, int]:
    """式神数据 id → 座次下标（0-3；召唤物坑位 ≥4，无座次色）。"""
    return {s.id: i for i, s in enumerate(p.shikigami)}


def _seat_color(p, index: int) -> int | None:
    """场上式神的座次色：仅原始四座（召唤物/超界无座次色）。"""
    s = p.shikigami[index]
    if index >= len(SEAT_COLORS) or s.home_slot is None:
        return None
    return SEAT_COLORS[index]


def _card_color(game: Game, p, c) -> int | None:
    """手牌的座次色 = 所属式神的座次色；中立牌/生成牌无色。"""
    cd = game.db.cards[c.id]
    if cd.shikigami is None:
        return None
    seat = _seat_map(p).get(cd.shikigami)
    if seat is None or seat >= len(SEAT_COLORS):
        return None
    return SEAT_COLORS[seat]


def _stats_label(game: Game, p, c) -> str:
    """数值段（按实例已装配的增强/修饰求值）：
    战斗牌战力与一次性护甲、形态身材、觉醒永久身材。"""
    cd = game.db.cards[c.id]
    parts: list[str] = []
    if cd.card_type == "combat":
        seat = _seat_map(p).get(cd.shikigami) if cd.shikigami is not None else None
        s = p.shikigami[seat] if seat is not None else None
        power, shield = game.combat_card_stats(cd.effects, c, s)
        if power:
            parts.append(f"战力{power:+d}")
        if shield:
            parts.append(f"护甲+{shield}")
    elif cd.card_type == "form" and cd.form_power is not None:
        parts.append(f"身材{cd.form_power}/{cd.form_health}")
    if cd.subtype == "awaken":
        pw = hp = 0
        for st in cd.effects.steps:
            extra = st.model_extra or {}
            if not extra.get("perm") or not isinstance(extra.get("amount"), int):
                continue
            if st.op == "buff_power":
                pw += extra["amount"]
            elif st.op == "buff_health":
                hp += extra["amount"]
        if pw or hp:
            parts.append(f"觉醒{pw:+d}/{hp:+d}")
    return " ".join(parts)


# ---------- 关键字显示 ----------

KEYWORD_CN = {  # 名称以 docs/terminology.md 为准；未收录的显示原始 id
    "fast": "瞬发", "trigger": "响应", "combo": "连击", "initiative": "先攻",
    "piercing": "贯通", "pierce": "穿刺", "remote": "远程", "unyielding": "不屈",
    "haste": "迅捷", "barrier": "屏障", "enraged": "激怒",
}
_KEYWORD_HIDDEN = {"keep_attack_buffs"}  # 引擎级关键字，卡面不出现


def _kw_labels(kws) -> list[str]:
    """关键字 id 列表 → 显示名列表（中文化；过滤引擎级关键字）。"""
    return [KEYWORD_CN.get(k, k) for k in kws if k not in _KEYWORD_HIDDEN]


def hand_sorted(game: Game, p) -> list:
    """按式神座位、卡牌序号、入手顺序升序排列后的手牌（显示/选择用）。"""
    seat = _seat_map(p)

    def key(c):
        cd = game.db.cards[c.id]
        shiki_idx = seat.get(cd.shikigami, 99) if cd.shikigami is not None else 99
        return (shiki_idx, c.id % 100, c.hand_seq)

    return sorted(p.hand, key=key)


def _player_segment(game: Game, pi: int, viewer: int | None = None) -> str:
    """单方牌手信息段：`> 名字（你） 生命h[护甲s] 手牌n 牌库n 墓地n[鼓舞+bp/bs]`。
    `>` 标行动方（非行动方前缀空格）；viewer 匹配时名字后加（你）。"""
    st = game.state
    p = st.players[pi]
    marker = ">" if pi == st.active else " "
    boost = ""
    if p.assault_boosts:
        bp = sum(b.get("power", 0) for b in p.assault_boosts)
        bs = sum(b.get("shield", 0) for b in p.assault_boosts)
        boost = f" 鼓舞+{bp}/{bs}"
    you = "（你）" if viewer is not None and pi == viewer else ""
    return (f"{marker} {p.name}{you} 生命{p.health}[护甲{p.shield}] "
            f"手牌{len(p.hand)} 牌库{len(p.deck)} 墓地{len(p.graveyard)}{boost}")


def player_segments(game: Game, viewer: int | None = None) -> tuple[str, str]:
    """（己方段, 敌方段）：viewer 指定时己方=viewer（联机视角），
    否则己方=当前行动方（热坐）。段格式同 _player_segment。"""
    st = game.state
    own = st.active if viewer is None else viewer
    return _player_segment(game, own, viewer), _player_segment(game, 1 - own, viewer)


def render(game: Game, viewer: int | None = None) -> str:
    """场况渲染。viewer 为"己方"视角玩家下标（着色/手牌展示）；
    None = 当前行动方（热坐）。"""
    st = game.state
    view = st.active if viewer is None else viewer
    active = st.players[st.active]
    lines = [
        "",
        f"===== 当前玩家第 {active.turn_count} 回合（总第 {st.turn - 1} 回合）| {active.name} 行动中 =====",
        "",
    ]
    all_rows = []
    player_rows = []
    for pi, p in enumerate(st.players):
        rows = []
        for i, s in enumerate(p.shikigami):
            if s.despawned:
                continue
            sd = game.db.shikigami[s.id]
            name = sd.name
            if s.awakened is not None:
                name = f"觉醒·{name}"
            if s.form is not None:
                name = f"{name}[{game.db.cards[s.form.id].name}]"
            kind = "·召唤物" if s.kind == "summon" else ""
            if s.defeated:
                status = f"气绝(倒计时{s.revive_countdown})"
            elif not s.in_play:
                status = "未在场"
            else:
                zone = "战斗区" if p.combat_index == i else "准备区"
                mods = []
                if s.perm_power:
                    mods.append(f"永{s.perm_power:+d}")
                if s.temp_power:
                    mods.append(f"临+{s.temp_power}")
                if s.perm_health:
                    mods.append(f"永血{s.perm_health:+d}")
                if s.temp_health:
                    mods.append(f"临血{s.temp_health:+d}")
                if s.shield:
                    mods.append(f"护甲{s.shield}")
                if s.combat_power:
                    mods.append(f"战力+{s.combat_power}")
                if s.countdown is not None:
                    mods.append(f"倒计时{s.countdown}")
                if s.keep_shield:
                    mods.append("保甲")
                if s.immunities:
                    mods.append("免疫")
                if s.delayed:
                    mods.append(f"延迟×{len(s.delayed)}")
                kws = _kw_labels(s.keywords + s.one_shot_keywords + s.perm_keywords)
                if kws:
                    mods.append(f"[{'/'.join(kws)}]")
                extra = f" ({' '.join(mods)})" if mods else ""
                status = f"攻{s.eff_power} 血{s.health}/{s.max_health}{extra} {zone}"
            rows.append((i, name, kind, s.level, s.faction, status))
        all_rows.extend(rows)
        player_rows.append((pi, rows))

    idx_w = max((_display_width(str(i + 1)) for i, _, _, _, _, _ in all_rows), default=1)
    name_w = max((_display_width(name) for _, name, _, _, _, _ in all_rows), default=0)
    kind_w = max((_display_width(kind) for _, _, kind, _, _, _ in all_rows), default=0)
    level_w = max((_display_width(f"Lv{lv}") for _, _, _, lv, _, _ in all_rows), default=0)
    faction_w = max((_display_width(f"[{f}]") for _, _, _, _, f, _ in all_rows), default=0)

    for pi, rows in player_rows:
        lines.append(_player_segment(game, pi))
        for i, name, kind, lv, faction, status in rows:
            color = _seat_color(p, i) if pi == view else None
            line = (
                f"    [{_pad(str(i + 1), idx_w)}] "
                f"{_colored(_pad(name, name_w), color)}"
                f"{_pad(kind, kind_w)} "
                f"{_pad(f'Lv{lv}', level_w)} "
                f"{_pad(f'[{faction}]', faction_w)} "
                f"{status}"
            )
            lines.append(line)
        lines.append("")
    p = st.players[view]
    lines.append(f"{p.name}（你）手牌{len(p.hand)}（剩余鬼火{p.orb} 出击次数{p.assaults_left}）："
                 if viewer is not None else
                 f"{p.name} 手牌{len(p.hand)}（剩余鬼火{p.orb} 出击次数{p.assaults_left}）：")
    lines.extend(format_hand_lines(game, p, hand_sorted(game, p)))
    lines.append("")
    if st.winner is not None:
        lines.append(f"***** {st.players[st.winner].name} 获胜！*****")
    return "\n".join(lines)


def format_hand_lines(game: Game, p, hand: list) -> list[str]:
    """手牌逐行格式（render 与调度阶段共用；与卡组构筑共用 cardfmt 对齐流程）：
    [1-based] 【卡牌名】 #uid 类型[子类型] 等级N 费用N [关键字/增强] 数值段 {描述}"""

    def _cost_label(c) -> str:
        """费用显示（含实例修饰 cost_delta）。"""
        cd = game.db.cards[c.id]
        return f"费用{cd.cost + c.mods.get('cost_delta', 0)}"

    def _data_label(c) -> str:
        """数据段：关键字（含实例修饰 keywords_add，中文化）+ 增强数值。"""
        cd = game.db.cards[c.id]
        parts = []
        kws = _kw_labels(list(cd.keywords) + list(c.mods.get("keywords_add", [])))
        if kws:
            parts.append(f"[{'/'.join(kws)}]")
        if c.mods.get("enhance"):
            parts.append(f"增强+{c.mods['enhance']}")
        return " ".join(parts)

    idx_w = max((_display_width(str(len(hand))), 1))
    rows = []
    for i, c in enumerate(hand):
        cd = game.db.cards[c.id]
        rows.append((
            f"[{_pad(str(i + 1), idx_w)}]",
            f"【{cd.name}】",
            f"#{c.uid}",
            cardfmt.ctype_label(cd),
            f"等级{cd.level}",
            _cost_label(c),
            _data_label(c),
            _stats_label(game, p, c),
            f"{{{cd.text}}}" if cd.text else "",
        ))
    out = []
    for row, c in zip(cardfmt.align_rows(rows), hand):
        cells = list(row)
        cells[1] = _colored(cells[1], _card_color(game, p, c))
        out.append("    " + " ".join(cells).rstrip())
    return out


def run_mulligan(game: Game) -> None:
    """调度阶段：双方轮流确认——输入手牌序号调度（返回牌库再随机抽 1），done 结束。

    每位玩家调度前先展示自己的先后手（players[0] 恒为先手）与四名式神的座位顺序。
    """
    print("—— 调度阶段：输入手牌序号调度（可以不用满次数），done 结束 ——")
    for pi in (0, 1):
        p = game.state.players[pi]
        seats = "  ".join(
            _colored(f"{i + 1}.{game.db.shikigami[s.id].name}", _seat_color(p, i))
            for i, s in enumerate(p.shikigami))
        print(f"{p.name}（{'先手' if pi == 0 else '后手'}）座位：{seats}")
        while not p.mulligan_done:
            print("")
            print(f"{p.name} 手牌{len(p.hand)}：")
            # 与回合内手牌同一格式；顺序保持手牌实际顺序（调度替换逻辑），不按式神/cid 排序
            for line in format_hand_lines(game, p, p.hand):
                print(line)
            print("")
            try:
                line = tui.prompt(f"[{p.name}] 调度（剩 {p.mulligans_left} 次）> ").strip().lower()
            except EOFError:
                line = "done"
            if line in ("done", "", "q"):
                game.apply({"op": "ready", "player": pi})
                continue
            try:
                card = p.hand[int(line) - 1]
                game.apply({"op": "mulligan", "player": pi, "uid": card.uid})
            except (ValueError, IndexError):
                print("序号有误")
            except IllegalAction as e:
                print(f"无效操作: {e}")


def _parse_value(s: str) -> bool | int | str:
    """解析调试命令的 value：true/false → bool，纯数字 → int，其余保持 str。"""
    sl = s.lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    try:
        return int(s)
    except ValueError:
        return s


def run_debug(game: Game, args: list[str]) -> dict:
    """把 CLI 的 'debug <subcmd> [args...]' 解析为 engine 可执行的 cmd dict。"""
    if not args or args[0] in ("help", "h"):
        print(DEBUG_HELP)
        return {}
    sub = args[0].lower()
    rest = args[1:]

    def need(n: int) -> None:
        if len(rest) < n:
            raise ValueError(f"{sub} 需要至少 {n} 个参数")

    if sub == "give_card":
        need(2)
        return {
            "op": "debug_give_card",
            "args": {
                "player": int(rest[0]),
                "card_id": int(rest[1]),
                "zone": rest[2] if len(rest) > 2 else "hand",
                "count": int(rest[3]) if len(rest) > 3 else 1,
            },
        }
    if sub == "set_stat":
        need(3)
        return {
            "op": "debug_set_stat",
            "args": {
                "target": parse_ref(rest[0], game.state.active).model_dump(),
                "key": rest[1],
                "value": _parse_value(rest[2]),
            },
        }
    if sub == "play_card":
        need(2)
        return {
            "op": "debug_play_card",
            "args": {
                "player": int(rest[0]),
                "uid": int(rest[1]),
                "target": parse_ref(rest[2], int(rest[0])).model_dump() if len(rest) > 2 else None,
                "play_method": rest[3] if len(rest) > 3 else None,
            },
        }
    if sub == "assault":
        need(2)
        return {
            "op": "debug_assault",
            "args": {"player": int(rest[0]), "index": int(rest[1])},
        }
    if sub in ("grant", "ungrant"):
        need(2)
        args_out: dict = {
            "target": parse_ref(rest[0], game.state.active).model_dump(),
            "keyword": rest[1],
        }
        if sub == "grant" and len(rest) > 2:
            args_out["cls"] = rest[2]
        if sub == "ungrant":
            args_out["remove"] = True
        return {"op": "debug_grant_keyword", "args": args_out}
    if sub == "draw":
        need(1)
        return {
            "op": "debug_draw",
            "args": {"player": int(rest[0]), "count": int(rest[1]) if len(rest) > 1 else 1},
        }
    if sub == "set_turn":
        args_out: dict = {}
        if len(rest) > 0:
            args_out["active"] = int(rest[0])
        if len(rest) > 1:
            args_out["turn"] = int(rest[1])
        return {"op": "debug_set_turn", "args": args_out}
    raise ValueError(f"未知调试子命令: {sub}")


def _choose_deck(db, player_name: str) -> tuple[list[int], list[int]]:
    """热坐开局前：从本地卡组文件（~/.bwp.decks.json）选择卡组槽位；
    文件为空时回退到卡组码输入或默认卡组（见 client/deckbuilder.choose_deck）。"""
    ids, cards, _ = deckbuilder.choose_deck(db, player_name)
    return ids, cards


def _battle_status(game: Game) -> tuple[str, str, str]:
    """热坐底部状态栏三段：左=己方（当前行动方）、中=回合、右=敌方。"""
    st = game.state
    left, right = player_segments(game)
    if st.phase == "mulligan":
        mid = "调度阶段"
    else:
        mid = f"总第 {st.turn - 1} 回合 · 行动中 {st.players[st.active].name}"
    return left, mid, right


def run_battle(db) -> None:
    """热坐对战：双方依次选择卡组（卡组码导入或默认）后开局。"""
    a_ids, a_cards = _choose_deck(db, "玩家A")
    b_ids, b_cards = _choose_deck(db, "玩家B")
    game = new_game(
        db,
        ("玩家A", a_ids, a_cards),
        ("玩家B", b_ids, b_cards),
        seed=42,
    )
    tui.set_status(lambda: _battle_status(game))
    try:
        _battle_loop(game)
    finally:
        tui.set_status(None)


def _battle_loop(game: Game) -> None:
    if game.state.phase == "mulligan":
        run_mulligan(game)
    settle_seen = drain_settle(game, 0)  # 先手首回合的回合开始阶段起：调度后首块明细
    print(render(game))
    while game.state.winner is None:
        prompt = f"[{game.current.name}]"
        if game.state.phase == "upgrade":
            prompt = f"[{game.current.name} 升级阶段（剩 {game.current.upgrades} 次）]"
        try:
            line = tui.prompt(f"{prompt} > ").strip()
        except EOFError:
            break
        if not line:
            continue
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        cmd = COMMAND_ALIASES.get(cmd, cmd)
        try:
            if cmd in ("quit", "exit"):
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "state":
                print(render(game))
            elif cmd == "log":
                n = int(args[0]) if args else 10
                print("\n".join(game.state.log[-n:]))
            elif cmd == "debug":
                dcmd = run_debug(game, args)
                if dcmd:
                    game.apply(dcmd)
                    settle_seen = drain_settle(game, settle_seen)
                    print(render(game))
            elif cmd == "play":
                hand = hand_sorted(game, game.current)
                card = hand[int(args[0]) - 1]
                cdef = game.db.cards[card.id]
                cmd_dict: dict = {"op": "play_card", "uid": card.uid}
                rest = args[1:]
                eff = cdef
                if cdef.card_type == "reinforce":
                    # 协战牌：先选择子选项（显示两选项卡名与文本），目标/等级按子卡
                    options = [game.db.cards[o] for o in cdef.options]
                    if rest:
                        pick = int(rest.pop(0))
                    else:
                        for i, o in enumerate(options):
                            print(f"  [{i}]《{o.name}》 {o.text}")
                        pick = int(tui.prompt("子选项 > "))
                    cmd_dict["choice"] = pick
                    eff = options[pick]
                if eff.target.kind == "choose":
                    from core import targets as _targets
                    legal = _targets.pool_refs(game, eff.target.pool, game.state.active,
                                               targeted=True)
                    if rest:
                        code = rest.pop(0)
                    else:
                        print("可选目标: " + " ".join(
                            ref_code(r, game.state.active) for r in legal))
                        code = tui.prompt("目标 > ")
                    cmd_dict["target"] = parse_ref(code, game.state.active)
                if rest:
                    cmd_dict["play_method"] = rest.pop(0)  # 使用方式，如 burst
                game.apply(cmd_dict)
                settle_seen = drain_settle(game, settle_seen)
                print(render(game))
            elif cmd in ("assault", "upgrade"):
                cmd_dict: dict = {"op": cmd, "index": int(args[0]) - 1}
                if cmd == "assault":
                    # 追猎：可任选一名合法敌方式神为战斗目标（不选 = 默认无目标战斗）
                    s = game.state.players[game.state.active].shikigami[cmd_dict["index"]]
                    kws = s.keywords + s.one_shot_keywords + s.perm_keywords
                    if "hunt" in kws:
                        from core import targets as _targets
                        legal = _targets.pool_refs(game, "enemy_shikigami",
                                                   game.state.active, targeted=True)
                        if len(args) > 1:
                            cmd_dict["target"] = parse_ref(args[1], game.state.active)
                        elif legal:
                            print("追猎可选目标: " + " ".join(
                                ref_code(r, game.state.active) for r in legal)
                                + "（回车 = 默认战斗区）")
                            code = tui.prompt("追猎目标 > ").strip()
                            if code:
                                cmd_dict["target"] = parse_ref(code, game.state.active)
                game.apply(cmd_dict)
                settle_seen = drain_settle(game, settle_seen)
                print(render(game))
            elif cmd == "end":
                game.apply({"op": "end_turn"})
                settle_seen = drain_settle(game, settle_seen)
                print(render(game))
            else:
                print("未知指令，输入 help 查看帮助")
        except IllegalAction as e:
            print(f"无效操作: {e}")
        except (ValueError, IndexError):
            print("参数有误，输入 help 查看帮助")
    # 对局结束：显示最终场况（含胜负），等待确认后回主菜单
    print("")
    print(render(game))
    try:
        tui.prompt("按 Enter 返回主菜单 > ")
    except EOFError:
        pass


def main() -> None:
    """一级菜单：卡组构筑 / 本地热坐 / 联机对战。数据为正式 YAML（CardDatabase.load）。"""
    if os.name == "nt":
        os.system("")  # 启用 Windows 控制台 ANSI 颜色（Git Bash/WT 原生支持，无副作用）
    db = CardDatabase.load()
    with tui.activate():
        while True:
            tui.set_status(lambda: ("主菜单", "输入 1/2/3 选择，q 退出"))
            print("")
            print("—— 主菜单 ——")
            print("")
            print("  [1] 卡组构筑")
            print("  [2] 本地热坐")
            print("  [3] 联机对战")
            print("")
            try:
                choice = tui.prompt("选择（q 退出）> ").strip().lower()
            except EOFError:
                break
            if choice == "1":
                deckbuilder.run_deckbuilder(db)
            elif choice == "2":
                run_battle(db)
            elif choice == "3":
                from client import net
                server = tui.prompt("服务器地址（Enter = ws://127.0.0.1:1037/ws）> ").strip()
                net.run(db, server or "ws://127.0.0.1:1037/ws",
                        tui.prompt("玩家名 > ").strip() or "玩家", debug=False)
            elif choice in ("q", "quit", "exit"):
                break
        tui.set_status(None)


if __name__ == "__main__":
    main()
