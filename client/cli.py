"""本地热座 CLI 客户端：两名玩家共用终端轮流操作。

所有指令通过 Game.apply 提交，与将来联机客户端走同一 cmd dict 协议（见 CLAUDE.md）。
非回合方没有任何输入机会——响应牌由引擎自动结算（规则：敌方回合零选择、响应必发）。

运行：uv run python -m client.cli
当前真实卡牌数据为空（见 thoughts.txt），自动使用 db/dummy.py 的空白占位数据。
"""
from __future__ import annotations

import unicodedata
from core.engine import Game, IllegalAction
from core.model import Ref
from core.setup import new_game
from db.test_data import TEST_IDS, make_test_db, make_test_deck

HELP = """指令（括号内为 alias，序号从 1 开始）：
  play (p)   <手牌序号> [目标] [方式]   使用手牌；如 play 1 e1 或 p 1 e1 burst
  assault (a) <式神序号>               式神出击（耗 1 鬼火 + 每回合 1 次次数）
  upgrade (u) <式神序号>               升级式神（只能升己方当前最低级）
  end (e)                              结束回合
  state (st)                           重印场面
  log (l) [n]                          查看最近 n 条日志（默认 10）
  debug (d) <子命令> [参数...]          调试命令（见 debug help）
  help (h) / quit (q)

目标代码：e=敌方 f=己方；e0=敌方 0 号式神，f1=己方 1 号式神，ep=敌方牌手，fp=己方牌手
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
  play_card <player> <uid> [target] [method]           强制使用牌
  assault <player> <index>                             强制出击
  draw <player> [count=1]                              强制抽牌
  set_turn [active] [turn]                             设置当前回合方/半回合数

  key 示例：health, orb, shield, level, defeated, despawned
  value 为 bool 时：true/false
"""


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


def _display_width(s: str) -> int:
    """计算字符串在等宽终端中的显示宽度（CJK 字符计为 2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    """按显示宽度补齐到指定宽度。"""
    return s + " " * max(0, width - _display_width(s))


def _hand_sorted(game: Game, p) -> list:
    """按式神座位、卡牌序号、入手顺序升序排列后的手牌（显示/选择用）。"""
    seat = {}
    for i, s in enumerate(p.shikigami):
        seat[s.id] = i

    def key(c):
        cd = game.db.cards[c.id]
        shiki_idx = seat.get(cd.shikigami, 99) if cd.shikigami is not None else 99
        return (shiki_idx, c.id % 100, c.hand_seq)

    return sorted(p.hand, key=key)


def render(game: Game) -> str:
    st = game.state
    active = st.players[st.active]
    lines = [f"===== 当前玩家第 {active.turn_count} 回合（总第 {st.turn - 1} 回合）| {active.name} 行动中 ====="]
    all_rows = []
    player_rows = []
    for pi, p in enumerate(st.players):
        rows = []
        for i, s in enumerate(p.shikigami):
            if s.despawned:
                continue
            sd = game.db.shikigami[s.id]
            name = sd.name
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
                if s.shield:
                    mods.append(f"护甲{s.shield}")
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
        if pi > 0:
            lines.append("")
        p = st.players[pi]
        marker = ">" if pi == st.active else " "
        lines.append(
            f"{marker} {p.name} HP {p.health}(护甲{p.shield}) "
            f"鬼火 {p.orb} 手牌 {len(p.hand)} 牌库 {len(p.deck)} 墓地 {len(p.graveyard)}"
        )
        for i, name, kind, lv, faction, status in rows:
            line = (
                f"    [{_pad(str(i + 1), idx_w)}] "
                f"{_pad(name, name_w)}"
                f"{_pad(kind, kind_w)} "
                f"{_pad(f'Lv{lv}', level_w)} "
                f"{_pad(f'[{faction}]', faction_w)} "
                f"{status}"
            )
            lines.append(line)
        lines.append("")
    p = st.players[st.active]
    lines.append(f"{p.name} 手牌（升级机会 {p.upgrades}，出击次数 {p.assaults_left}）：")
    hand = _hand_sorted(game, p)
    # 新格式：[1-based] 【卡牌名】 #uid ctype[subtype] level cost [data] {description}
    def _ctype_label(cd):
        base = cd.card_type
        if cd.subtype:
            return f"{base}[{cd.subtype}]"
        return base

    idx_w = max((_display_width(str(i + 1)) for i in range(len(hand))), default=1)
    name_w = max((_display_width(f"【{game.db.cards[c.id].name}】") for c in hand), default=0)
    uid_w = max((_display_width(f"#{c.uid}") for c in hand), default=0)
    ctype_w = max((_display_width(_ctype_label(game.db.cards[c.id])) for c in hand), default=0)
    level_w = max((_display_width(str(game.db.cards[c.id].level)) for c in hand), default=0)
    cost_w = max((_display_width(str(game.db.cards[c.id].cost)) for c in hand), default=0)
    data_w = max((_display_width(f"[{'/'.join(game.db.cards[c.id].keywords)}]") for c in hand), default=0)
    for i, c in enumerate(hand):
        cd = game.db.cards[c.id]
        data = f"[{'/'.join(cd.keywords)}]" if cd.keywords else ""
        line = (
            f"    [{_pad(str(i + 1), idx_w)}] "
            f"{_pad(f'【{cd.name}】', name_w)} "
            f"{_pad(f'#{c.uid}', uid_w)} "
            f"{_pad(_ctype_label(cd), ctype_w)} "
            f"{_pad(str(cd.level), level_w)} "
            f"{_pad(str(cd.cost), cost_w)} "
            f"{_pad(data, data_w)} "
            f"{{{cd.text}}}"
        )
        lines.append(line)
    lines.append("")
    if st.winner is not None:
        lines.append(f"***** {st.players[st.winner].name} 获胜！*****")
    return "\n".join(lines)


def run_mulligan(game: Game) -> None:
    """调度阶段：双方轮流确认——输入手牌序号调度（返回牌库再随机抽 1），done 结束。"""
    print("—— 调度阶段：输入手牌序号调度（可以不用满次数），done 结束 ——")
    for pi in (0, 1):
        p = game.state.players[pi]
        while not p.mulligan_done:
            hand = "  ".join(f"[{i + 1}]《{game.db.cards[c.id].name}》" for i, c in enumerate(p.hand))
            print(f"{p.name} 手牌：{hand}")
            try:
                line = input(f"[{p.name}] 调度（剩 {p.mulligans_left} 次）> ").strip().lower()
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


def main() -> None:
    # Phase 1 CLI 热座使用维护者给出的测试数据。
    db = make_test_db()
    deck = make_test_deck()
    game = new_game(
        db,
        ("玩家A", list(TEST_IDS), list(deck)),
        ("玩家B", list(TEST_IDS), list(deck)),
        seed=42,
    )
    if game.state.phase == "mulligan":
        run_mulligan(game)
    print(render(game))
    while game.state.winner is None:
        prompt = f"[{game.current.name}]"
        if game.state.phase == "upgrade":
            prompt = f"[{game.current.name} 升级阶段（剩 {game.current.upgrades} 次）]"
        try:
            line = input(f"{prompt} > ").strip()
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
                    print(render(game))
            elif cmd == "play":
                hand = _hand_sorted(game, game.current)
                card = hand[int(args[0]) - 1]
                cdef = db.cards[card.id]
                cmd_dict: dict = {"op": "play_card", "uid": card.uid}
                rest = args[1:]
                if cdef.target.kind == "choose":
                    legal = game.legal_targets(game.state.active, card)
                    if rest:
                        code = rest.pop(0)
                    else:
                        print("可选目标: " + " ".join(
                            ref_code(r, game.state.active) for r in legal))
                        code = input("目标 > ")
                    cmd_dict["target"] = parse_ref(code, game.state.active)
                if rest:
                    cmd_dict["play_method"] = rest.pop(0)  # 使用方式，如 burst
                game.apply(cmd_dict)
                print(render(game))
            elif cmd in ("assault", "upgrade"):
                game.apply({"op": cmd, "index": int(args[0]) - 1})
                print(render(game))
            elif cmd == "end":
                game.apply({"op": "end_turn"})
                print(render(game))
            else:
                print("未知指令，输入 help 查看帮助")
        except IllegalAction as e:
            print(f"无效操作: {e}")
        except (ValueError, IndexError):
            print("参数有误，输入 help 查看帮助")
    if game.state.winner is not None:
        print(render(game))


if __name__ == "__main__":
    main()
