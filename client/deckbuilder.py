"""卡组构筑与战前选卡（交互式）。

- 本地卡组文件（db/deckstore.py v2，~/.bwp.decks.json）：进入构筑时读取全部槽位
  并按天梯规则重新校验（满足者以亮蓝色标明）；可编辑现有槽位、重命名
  （名 <序号> <新名称>）、删除（删 <序号>，二次确认）或新建；编辑/新建均支持
  卡组码导入；校验通过即自动写回并回到管理界面（q 返回主菜单；文件不存在时
  自动创建；文件格式异常时提示并删除该文件）。
- 新建为严格输入：必须恰好 4 个不重复的有效式神序号；每名式神必须恰好 8 个
  卡牌序号（同种卡至多 2 张、序号须存在），反复询问直到合法。
- 编辑为增量式：在当前卡组基础上按"单个式神 ↔ 其卡牌"修改——输入式神序号
  编辑其卡牌（回车沿用），"换 <序号>" 更换式神（清空其已选卡牌并重新选牌）。
- choose_deck：热坐对战与联机对战开局前的统一选卡入口（本地槽位选择；所选卡组
  须满足对战模式的组卡规则，否则要求重选；联机时服务端入座会再次核验；
  文件为空时回退到卡组码输入 / 默认卡组）。
- 卡牌列表与对局手牌显示共用 client/cardfmt.py 的对齐流程。
- 卡组码格式见 db/deckcode.py；主菜单入口见 client/cli.py。
"""
from __future__ import annotations

from collections import Counter

from client import cardfmt, tui
from client.textutil import colored
from db import deckcode, deckstore
from db.deck import (MAX_COPIES_PER_NAME, MAX_KINDS_PER_SHIKIGAMI,
                     STANDARD_RULES, DeckRules, validate_deck)
from db.loader import CardDatabase

# 本地卡组列表中"满足天梯规则"的卡组以亮蓝色标明
STANDARD_COLOR = 94


def available_shikigami(db: CardDatabase) -> list:
    """全部可构筑式神（kind=shikigami，按 id 排序）。"""
    return sorted((d for d in db.shikigami.values() if d.kind == "shikigami"),
                  key=lambda d: d.id)


def buildable_cards(db: CardDatabase, sid: int) -> list:
    """某式神全部可构筑（非衍生）卡牌，按 id 排序。"""
    return sorted((c for c in db.cards.values()
                   if not c.token and c.shikigami == sid), key=lambda c: c.id)


def _input(prompt: str) -> str:
    try:
        return tui.prompt(prompt).strip()
    except EOFError:
        return ""


# ---------- 显示 ----------

def _shiki_rows(defs: list) -> list[tuple[str, ...]]:
    """式神列表行（已对齐）：[序号] 名称｜派系｜力量/生命 {能力文本}。"""
    rows = [(f"[{i + 1}]", d.name, d.faction, f"{d.power}/{d.health}",
             f"{{{d.text}}}" if d.text else "") for i, d in enumerate(defs)]
    return cardfmt.align_rows(rows)


def _print_shikigami(defs: list) -> None:
    for r in _shiki_rows(defs):
        print(f"  {r[0]} {r[1]}｜{r[2]}｜{r[3]} {r[4]}".rstrip())


def _print_cards(cards: list, copies: Counter | None = None) -> None:
    """对齐打印卡牌列表（与对局手牌共用 cardfmt 流程）：
    [序号] 名称｜类型[子类型]｜等级｜数值段 {效果文本} ×n。不显示费用。"""
    rows = []
    for i, c in enumerate(cards):
        text = f"{{{c.text}}}" if c.text else ""
        mark = f"×{copies[c.id]}" if copies and copies.get(c.id) else ""
        rows.append((f"[{i + 1}]", c.name, cardfmt.ctype_label(c),
                     f"等级{c.level}", cardfmt.static_stats(c), text, mark))
    for r in cardfmt.align_rows(rows):
        line = f"  {r[0]} {r[1]}｜{r[2]}｜{r[3]}"
        if r[4].strip() or r[5].strip() or r[6].strip():
            line += f"｜{r[4]} {r[5]} {r[6]}".rstrip()
        print(line)


def _deck_list_lines(decks: list[dict]) -> None:
    """本地卡组槽位列表：满足天梯规则的卡组以亮蓝色标明。"""
    for i, d in enumerate(decks):
        print(colored(f"  [{i + 1}] {d['name']}",
                      STANDARD_COLOR if d.get("standard") else None))


def _print_deck(db: CardDatabase, team: list[int], picks: dict[int, list[int]]) -> None:
    """当前卡组总览：每个式神一行（对齐的数值+能力文本）+ 其已选卡牌与张数。"""
    total = sum(len(v) for v in picks.values())
    print("")
    print(f"—— 当前卡组（共 {total} 张）——")
    for r, sid in zip(_shiki_rows([db.shikigami[s] for s in team]), team):
        print(f"  {r[0]} {r[1]}｜{r[2]}｜{r[3]} {r[4]}".rstrip())
        cards = picks.get(sid, [])
        names = "  ".join(f"{db.cards[c].name}×{n}"
                          for c, n in Counter(cards).items())
        print(f"      {names or '（未选牌）'}（{len(cards)} 张）")
    print("")


# ---------- 单式神卡牌编辑 ----------

def _pick_cards(db: CardDatabase, sid: int, current: list[int]) -> list[int] | None:
    """编辑一名式神的卡牌：回车 = 沿用当前（当前为空则 = 全部种类）；取消返回 None。"""
    d = db.shikigami[sid]
    cards = buildable_cards(db, sid)
    cur_copies = Counter(current)
    cur_kinds = [c for c in cards if cur_copies.get(c.id)]
    print("")
    print(f"—— {d.name} 的卡牌（至多 {MAX_KINDS_PER_SHIKIGAMI} 种，"
          f"每种至多 {MAX_COPIES_PER_NAME} 张）——")
    _print_cards(cards, cur_copies)
    print("")
    line = _input("卡牌种类序号（空格分隔；回车 = 沿用当前/全部种类）> ")
    try:
        picked = ([cards[int(x) - 1] for x in line.split()] if line
                  else (cur_kinds or cards))
    except (ValueError, IndexError):
        print("序号有误，已取消")
        return None
    # 初始张数：沿用的种类按当前张数，新选的种类 1 张
    copies = {i + 1: (cur_copies.get(c.id, 0) or 1) for i, c in enumerate(picked)}
    tune = _input("张数调整（如 1=2 3=2；回车 = 沿用/每种 1 张）> ")
    for item in tune.split():
        try:
            k, v = item.split("=")
            copies[int(k)] = int(v)
        except ValueError:
            print(f"无法解析 {item!r}，已忽略")
    out: list[int] = []
    for i, c in enumerate(picked):
        n = max(0, min(MAX_COPIES_PER_NAME, copies.get(i + 1, 1)))
        out.extend([c.id] * n)
    print(f"{d.name} 当前 {len(out)} 张（须恰好 {MAX_KINDS_PER_SHIKIGAMI} 张）")
    return out


# ---------- 增量编辑循环 ----------

def _edit_deck(db: CardDatabase, team: list[int],
               picks: dict[int, list[int]]) -> tuple[list[int], list[int]] | None:
    """在当前基础上编辑：序号 = 编辑该式神卡牌；换 <序号> = 更换式神（清空其卡牌）；
    回车 = 完成。校验不通过时打印错误并继续编辑。"""
    while True:
        _print_deck(db, team, picks)
        line = _input("序号 = 编辑该式神卡牌；换 <序号> = 更换式神；回车 = 完成 > ")
        if not line:
            ids = list(team)
            card_ids = [cid for sid in team for cid in picks.get(sid, [])]
            errors = validate_deck(db, ids, card_ids)
            if not errors:
                return ids, card_ids
            print("卡组暂不合法（请继续调整）：")
            print("\n".join(errors))
            continue
        parts = line.lower().split()
        if parts[0] in ("换", "h", "change") and len(parts) == 2:
            try:
                slot = int(parts[1]) - 1
                old = team[slot]
            except (ValueError, IndexError):
                print("序号有误")
                continue
            pool = [d for d in available_shikigami(db) if d.id not in team]
            print("")
            _print_shikigami(pool)
            try:
                new = pool[int(_input(f"更换 {db.shikigami[old].name} 为 > ")) - 1]
            except (ValueError, IndexError):
                print("序号有误")
                continue
            team[slot] = new.id
            picks.pop(old, None)      # 式神变更：清空其携带卡牌
            picks[new.id] = []
            print(f"已更换为 {new.name}（需重新选牌）")
            result = _pick_cards(db, new.id, [])
            if result is not None:
                picks[new.id] = result
            continue
        try:
            sid = team[int(parts[0]) - 1]
        except (ValueError, IndexError):
            print("输入有误")
            continue
        result = _pick_cards(db, sid, picks.get(sid, []))
        if result is not None:
            picks[sid] = result


# ---------- 新建卡组的严格输入 ----------

def _pick_shikigami_strict(db: CardDatabase) -> list:
    """新建卡组选式神：必须恰好 4 个空格分隔的序号，不重复且均存在；反复询问直到合法。"""
    pool = available_shikigami(db)
    print("")
    print("—— 选择 4 名出战式神 ——")
    _print_shikigami(pool)
    print("")
    while True:
        tokens = _input("式神序号（恰好 4 个，空格分隔，不能重复）> ").split()
        if len(tokens) != 4:
            print(f"须恰好输入 4 个序号（当前 {len(tokens)} 个）")
            continue
        try:
            chosen = [pool[int(x) - 1] for x in tokens]
        except (ValueError, IndexError):
            print("序号不存在，请重新输入")
            continue
        if len({d.id for d in chosen}) != 4:
            print("式神不能重复，请重新输入")
            continue
        return chosen


def _pick_cards_strict(db: CardDatabase, sid: int) -> list[int]:
    """新建卡组选牌：必须恰好 8 个空格分隔的序号（同种卡至多 2 次，序号须存在）；
    反复询问直到合法。顺序无所谓。"""
    d = db.shikigami[sid]
    cards = buildable_cards(db, sid)
    print("")
    print(f"—— {d.name} 的卡牌（须恰好 8 张，同种卡至多 {MAX_COPIES_PER_NAME} 张）——")
    _print_cards(cards)
    print("")
    while True:
        tokens = _input("卡牌序号（恰好 8 个，空格分隔；重复序号 = 多张）> ").split()
        if len(tokens) != 8:
            print(f"须恰好输入 8 个序号（当前 {len(tokens)} 个）")
            continue
        try:
            picked = [cards[int(x) - 1] for x in tokens]
        except (ValueError, IndexError):
            print("序号不存在，请重新输入")
            continue
        counts = Counter(c.id for c in picked)
        over = [db.cards[cid].name for cid, n in counts.items()
                if n > MAX_COPIES_PER_NAME]
        if over:
            print(f"同种卡至多 {MAX_COPIES_PER_NAME} 张（超限：{'、'.join(over)}），"
                  "请重新输入")
            continue
        return [c.id for c in picked]


def _interactive_build(db: CardDatabase) -> tuple[list[int], list[int]] | None:
    """新建卡组：严格选择 4 名式神 → 各严格选 8 张牌 → 进入增量编辑循环（回车完成）。"""
    chosen = _pick_shikigami_strict(db)
    team = [d.id for d in chosen]
    picks: dict[int, list[int]] = {}
    for d in chosen:
        picks[d.id] = _pick_cards_strict(db, d.id)
    return _edit_deck(db, team, picks)


# ---------- 本地卡组槽位管理 ----------


def run_deckbuilder(db: CardDatabase, store_path=deckstore.PATH) -> None:
    """卡组构筑入口：本地卡组管理循环——编辑/重命名/删除/新建，q 返回主菜单。
    保存（编辑/新建/重命名/删除）成功后回到管理界面而非主菜单。"""
    tui.set_status(lambda: ("卡组构筑",
                            "序号=编辑 · 名/删 <序号> · 回车=新建 · q=返回"))
    try:
        _manage_loop(db, store_path)
    finally:
        tui.set_status(None)


def _manage_loop(db: CardDatabase, store_path) -> None:
    while True:
        decks = deckstore.load_decks(db, store_path)
        print("")
        print(f"—— 卡组构筑（本地卡组文件：{store_path}）——")
        _deck_list_lines(decks)
        print("")
        try:
            line = tui.prompt("槽位序号 = 编辑该卡组；名 <序号> <新名称> = 重命名；"
                              "删 <序号> = 删除该卡组；回车 = 新建；q = 返回主菜单 > ").strip()
        except EOFError:
            return
        parts = line.split(maxsplit=2)
        if parts and parts[0].lower() in ("q", "quit", "exit"):
            return
        if len(parts) == 3 and parts[0] in ("名", "r", "rename"):
            try:
                entry = decks[int(parts[1]) - 1]
            except (ValueError, IndexError):
                print("序号有误，已取消")
                continue
            entry["name"] = parts[2].strip()
            deckstore.save_decks(db, decks, store_path)
            print(f"已重命名为「{entry['name']}」")
            continue
        if len(parts) == 2 and parts[0] in ("删", "d", "del", "delete"):
            try:
                index = int(parts[1]) - 1
                entry = decks[index]
            except (ValueError, IndexError):
                print("序号有误，已取消")
                continue
            confirm = _input(f"确认删除卡组「{entry['name']}」？（y 确认，其他取消）> ")
            if confirm.lower() not in ("y", "yes"):
                print("已取消删除")
                continue
            decks.pop(index)
            deckstore.save_decks(db, decks, store_path)
            print(f"卡组「{entry['name']}」已删除")
            continue
        index: int | None = None
        team: list[int] | None = None
        picks: dict[int, list[int]] = {}
        if line:
            try:
                index = int(line) - 1
                entry = decks[index]
                ids, cards = deckstore.entry_deck(entry)
                deckcode.deck_from_code(db, deckstore.entry_code(entry))  # 校验可用性
            except (ValueError, IndexError):
                print("序号有误或槽位卡组已失效，已取消")
                continue
            team = ids
            for cid in cards:  # 按所属式神分组（协战牌挂在队在的所属名下）
                c = db.cards[cid]
                owner = c.shikigami if c.shikigami in team else c.shikigami2
                picks.setdefault(owner, []).append(cid)
            print(f"编辑卡组「{entry['name']}」（在当前基础上修改）")
        name = _input("卡组名称（回车 = 沿用/自动命名）> ")

        code_line = _input("粘贴卡组码导入覆盖（回车 = 交互式构筑/编辑）> ")
        if code_line:
            try:
                ids, card_ids = deckcode.deck_from_code(db, code_line)
            except ValueError as e:
                print(f"卡组码无效（{e}），未保存")
                continue
        else:
            result = (_edit_deck(db, team, picks) if team is not None
                      else _interactive_build(db))
            if result is None:
                continue
            ids, card_ids = result
        if not name:
            name = decks[index]["name"] if index is not None else _deck_summary(db, ids)
        groups = deckcode.group_deck(db, ids, card_ids)
        entry = {"name": name, "groups": groups}
        if index is None:
            decks.append(entry)
            slot = len(decks)
        else:
            decks[index] = entry
            slot = index + 1
        deckstore.save_decks(db, decks, store_path)
        print("")
        print(f"卡组「{name}」已保存（共 {len(card_ids)} 张，槽位 {slot}）")
        print(f"卡组码（导出/分享）：{deckcode.encode_deck(groups)}")


def _deck_summary(db: CardDatabase, ids: list[int]) -> str:
    return "/".join(db.shikigami[s].name for s in ids)


# ---------- 战前选卡 ----------


def choose_deck(db: CardDatabase, label: str,
                store_path=deckstore.PATH,
                rules: DeckRules = STANDARD_RULES
                ) -> tuple[list[int], list[int], str]:
    """热坐/联机开局前选卡：读取本地卡组文件并要求从中选择槽位；
    文件为空时回退到卡组码输入（回车 = 默认卡组）。

    所选卡组须满足对战模式的组卡规则（rules；本地 is_standard 标记对应天梯
    规则）；不满足时提示并重新选择。联机对战时服务端还会再次核验（房间入座
    时 deck_from_code 校验，见 server/room.py）。
    返回 (式神 ids, 卡牌 ids, 卡组码)。"""
    decks = deckstore.load_decks(db, store_path)
    if decks:
        print(f"[{label}] 选择卡组（亮蓝 = 满足天梯规则）：")
        _deck_list_lines(decks)
        while True:
            line = _input(f"[{label}] 卡组序号 > ")
            try:
                entry = decks[int(line) - 1]
            except (ValueError, IndexError):
                print("序号有误，改用默认卡组")
                break
            if not deckstore.check_deck(db, entry["groups"], rules):
                print(f"卡组「{entry['name']}」不满足当前对战模式的组卡规则，"
                      "请重新选择")
                continue
            ids, cards = deckstore.entry_deck(entry)
            print(f"[{label}] 使用卡组「{entry['name']}」")
            return ids, cards, deckstore.entry_code(entry)
    else:
        print(f"[{label}] 本地卡组文件为空（可先在主菜单「卡组构筑」中创建）")
        code_in = _input(f"[{label}] 卡组码（回车跳过 = 默认卡组）> ")
        if code_in:
            try:
                ids, cards = deckcode.deck_from_code(db, code_in)
                code = code_in
                print(f"[{label}] 卡组：{_deck_summary(db, ids)}")
                print(f"[{label}] 卡组码（导出/分享）：{code}")
                return ids, cards, code
            except ValueError as e:
                print(f"卡组码无效（{e}），改用默认卡组")
    ids, cards = deckcode.default_deck(db)
    code = deckcode.encode_deck(deckcode.group_deck(db, ids, cards))
    print(f"[{label}] 卡组（默认）：{_deck_summary(db, ids)}")
    print(f"[{label}] 卡组码（导出/分享）：{code}")
    return ids, cards, code
