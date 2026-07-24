"""本地热座 CLI 客户端：两名玩家共用终端轮流操作。

所有指令通过 Game.apply 提交，与将来联机客户端走同一 cmd dict 协议（见 CLAUDE.md）。
非回合方没有任何输入机会——响应牌由引擎自动结算（规则：敌方回合零选择、响应必发）。

运行：uv run python -m client.cli
当前真实卡牌数据为空（见 thoughts.txt），自动使用 db/dummy.py 的空白占位数据。
"""
from __future__ import annotations

from core.engine import Game, IllegalAction
from core.model import Ref
from core.setup import new_game
from db.test_data import TEST_IDS, make_test_db, make_test_deck

HELP = """指令：
  play <手牌序号> [目标] [方式]   使用手牌；如 play 0 e1 或 play 0 e1 burst（爆能）
  assault <式神序号>              式神出击（耗 1 鬼火 + 每回合 1 次出击次数，驻留战斗区）
  upgrade <式神序号>              升级式神（只能升己方当前最低级）
  end                             结束回合
  state                           重印场面
  log [n]                         查看最近 n 条日志（默认 10）
  debug <子命令> [参数...]        调试命令（见 debug help）
  help / quit

目标代码：e=敌方 f=己方；e0=敌方 0 号式神，f1=己方 1 号式神，ep=敌方牌手，fp=己方牌手
"""

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


def render(game: Game) -> str:
    st = game.state
    lines = [f"===== 第 {st.turn} 半回合 | {st.players[st.active].name} 行动中 ====="]
    for pi, p in enumerate(st.players):
        marker = "▶" if pi == st.active else " "
        lines.append(
            f"{marker} {p.name} HP {p.health}(护甲{p.shield}) "
            f"鬼火 {p.orb} 手牌 {len(p.hand)} 牌库 {len(p.deck)} 墓地 {len(p.graveyard)}"
        )
        for i, s in enumerate(p.shikigami):
            if s.despawned:
                continue  # 已离场召唤物不显示（坑位保留，下标稳定）
            sd = game.db.shikigami[s.id]
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
            lines.append(f"    [{i}] {sd.name}{kind} Lv{s.level} [{s.faction}] {status}")
    p = st.players[st.active]
    lines.append(f"{p.name} 手牌（升级机会 {p.upgrades}，出击次数 {p.assaults_left}）:")
    for i, c in enumerate(p.hand):
        cd = game.db.cards[c.id]
        kw = f" [{'/'.join(cd.keywords)}]" if cd.keywords else ""
        mods = f" 强化{len(c.mods)}" if c.mods else ""
        methods = " 方式:" + ",".join(m.id for m in cd.methods) if cd.methods else ""
        lines.append(f"    [{i}] 《{cd.name}》#{c.uid} {cd.cost}费 Lv{cd.level}{kw}{mods}{methods} — {cd.text}")
    if st.winner is not None:
        lines.append(f"***** {st.players[st.winner].name} 获胜！*****")
    return "\n".join(lines)


def run_mulligan(game: Game) -> None:
    """调度阶段：双方轮流确认——输入手牌序号调度（返回牌库再随机抽 1），done 结束。"""
    print("—— 调度阶段：输入手牌序号调度（可以不用满次数），done 结束 ——")
    for pi in (0, 1):
        p = game.state.players[pi]
        while not p.mulligan_done:
            hand = "  ".join(f"[{i}]《{game.db.cards[c.id].name}》" for i, c in enumerate(p.hand))
            print(f"{p.name} 手牌：{hand}")
            try:
                line = input(f"[{p.name}] 调度（剩 {p.mulligans_left} 次）> ").strip().lower()
            except EOFError:
                line = "done"
            if line in ("done", "", "q"):
                game.apply({"op": "ready", "player": pi})
                continue
            try:
                card = p.hand[int(line)]
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
        try:
            line = input(f"[{game.current.name}] > ").strip()
        except EOFError:
            break
        if not line:
            continue
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
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
                card = game.current.hand[int(args[0])]
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
                game.apply({"op": cmd, "index": int(args[0])})
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
