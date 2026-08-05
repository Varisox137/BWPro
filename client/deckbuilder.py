"""卡组构筑与战前选卡（交互式）。

- 本地卡组文件（db/deckstore.py v3，~/.bwp.decks.json）：进入构筑时读取全部槽位
  并按天梯规则重新校验（满足者以亮蓝色标明）；可编辑现有槽位、重命名
  （r <序号> <新名称>）、删除（d <序号>，二次确认）或新建；编辑/新建均支持
  卡组码导入；校验通过即自动写回并回到管理界面（q 返回主菜单；文件不存在时
  自动创建；文件格式异常时提示并删除该文件）。每个卡组记录构筑环境 env
  （平衡性版本日期，null=最新；v2 文件读取时视为 null）：新建时先询问环境，
  编辑中可用 e <环境> 切换（环境输入支持别名 S1/S2 或 8 位日期，见 db/envs.py；
  环境下不存在的式神强制更换、卡牌自动移除）；
  构筑与 is_standard 校验均按 db.at_date(env) 解析。
- 新建与编辑的单式神选牌均为严格输入：必须恰好 8 个卡牌序号（序号须存在），
  反复询问直到合法；新建时经二级目录（版本包 → 式神，翻页显示，支持式神全名
  直选、可空格分隔多名）选择恰好 4 名不重复式神。同名卡张数不做
  强制校验——每次构筑（新建/编辑）仅打印一次标准规则细节（db.deck.rules_summary），
  超限卡组仍可保存，仅在完成时不满足 is_standard（不以亮蓝标明）。
- 可携带卡牌列表：本家 8 张（01-08）按 id 升序在前，协战牌列最后；
  协战牌同时列入两位所属式神的可选卡牌；完成时的 is_standard 检查含
  单式神携带 ≤2 与全卡组同名 ≤2（validate_deck 全局计数）。
- 编辑在当前卡组基础上按"单个式神 ↔ 其卡牌"修改——输入式神序号重新严格选满其
  8 张牌，"h <序号>" 更换式神（清空其已选卡牌并重新选牌）。
- choose_deck：热坐对战与联机对战开局前的统一选卡入口（本地槽位选择，回车取消；
  所选卡组须满足对战模式的组卡规则，否则要求重选；联机时服务端入座会再次核验；
  本地无卡组或全部不满足规则时打印引导并返回 None，不开局）。
- 卡牌列表与对局手牌显示共用 client/cardfmt.py 的对齐流程。
- 卡组码格式见 db/deckcode.py；主菜单入口见 client/cli.py。
"""
from __future__ import annotations

from collections import Counter

from client import cardfmt, tui
from client.textutil import colored
from db import deckcode, deckstore
from db.deck import STANDARD_RULES, DeckRules, rules_summary, validate_deck
from db.envs import env_label as _env_label, parse_env_input
from db.loader import CardDatabase
from db.packs import PACK_NAMES, PACKS

# 本地卡组列表中"满足天梯规则"的卡组以亮蓝色标明
STANDARD_COLOR = 94


def _ask_env() -> int | None:
    """构筑环境询问：Enter = 最新数据；别名（S1/S2）或 8 位日期，反复校验直到合法。"""
    while True:
        line = _input("构筑环境（S1/S2 或 8 位日期，Enter = 最新）> ")
        try:
            return parse_env_input(line)
        except ValueError as e:
            print(str(e))


def available_shikigami(db: CardDatabase) -> list:
    """全部可构筑式神（kind=shikigami 且非 WIP，按 id 排序）。

    WIP 式神（wip=true，如姑获鸟/青行灯/酒吞童子——仅基础数据或卡牌未齐）
    不进构筑可选池；卡数不足 8 种的成品式神（纸人武士/天邪鬼军团）可选。
    """
    return sorted((d for d in db.shikigami.values()
                   if d.kind == "shikigami" and not d.wip),
                  key=lambda d: d.id)


def buildable_cards(db: CardDatabase, sid: int) -> list:
    """某式神全部可构筑（非衍生）卡牌：本家卡（含作为主式神的协战牌）按 id 升序
    在前（01-08 即 1-8 号），作为第二所属式神的协战牌列最后。协战牌同时列入
    两位所属式神。"""
    cards = [c for c in db.cards.values()
             if not c.token and (c.shikigami == sid
                                 or (c.card_type == "reinforce"
                                     and c.shikigami2 == sid))]
    return sorted(cards, key=lambda c: (0 if c.shikigami == sid else 1, c.id))


def _input(prompt: str) -> str:
    try:
        return tui.prompt(prompt).strip()
    except EOFError:
        return ""


# ---------- 显示 ----------

def _shiki_rows(defs: list) -> list[tuple[str, ...]]:
    """式神列表行（已对齐）：[序号] 名称｜派系｜力量/生命 ｜能力文本（末列由调用方
    决定同行拼接或挪次行）。"""
    rows = [(f"[{i + 1}]", d.name, d.faction, f"{d.power}/{d.health}",
             d.text or "") for i, d in enumerate(defs)]
    return cardfmt.align_rows(rows)


def _print_shikigami(defs: list, marked: set[int] | None = None) -> None:
    """式神列表：首行 [序号] 名称｜派系｜力量/生命；能力文本挪次行缩进 4 格。"""
    for d, r in zip(defs, _shiki_rows(defs)):
        mark = " ✓" if marked and d.id in marked else ""
        print(f"  {r[0]} {r[1]}{mark}｜{r[2]}｜{r[3]}")
        if r[4].strip():
            print(f"    {r[4]}")


# ---------- 式神选择（版本包二级目录 + 翻页 + 全名直选）----------

PAGE_SIZE = 10  # 式神列表每页条数


def _pack_groups(pool: list) -> list[tuple[str, list]]:
    """可构筑式神按版本包分组（db.packs.PACKS 登记序；空包不列出）。"""
    groups = []
    for num in PACKS:
        members = [d for d in pool if str(d.id)[2:4] == num]
        if members:
            groups.append((PACK_NAMES.get(num, num), members))
    return groups


def _select_shikigami(db: CardDatabase, *, need: int = 1,
                      exclude: set[int] | None = None) -> list | None:
    """二级目录（版本包 → 式神，翻页显示）+ 全名直选的式神选择器。

    need=1 选 1 名（编辑更换式神），need=4 选 4 名（新建卡组）；q 取消返回 None。
    输入：当前列表序号 / n p 翻页 / b 返回包列表 / 式神全名（可空格分隔多名）。
    """
    pool = [d for d in available_shikigami(db)
            if exclude is None or d.id not in exclude]
    chosen: list = []
    chosen_ids: set[int] = set()
    in_pack: tuple[str, list] | None = None
    page = 0
    while len(chosen) < need:
        if in_pack is None:
            groups = _pack_groups(pool)
            print("")
            print(f"—— 选择式神（已选 {len(chosen)}/{need}："
                  f"{'、'.join(d.name for d in chosen) or '无'}）——")
            for i, (name, members) in enumerate(groups):
                print(f"  [{i + 1}] {name}（{len(members)} 名）")
            prompt = "包序号进入；式神全名直选（可空格分隔多名）；q 取消 > "
            listing: list = groups
        else:
            pack_name, members = in_pack
            pages = (len(members) + PAGE_SIZE - 1) // PAGE_SIZE
            page = max(0, min(page, pages - 1))
            shown = members[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            print("")
            print(f"—— {pack_name}（第 {page + 1}/{pages} 页；已选 "
                  f"{'、'.join(d.name for d in chosen) or '无'}）——")
            _print_shikigami(shown, marked=chosen_ids)
            prompt = "序号选择；n 下页 p 上页 b 返回包列表；全名直选 > "
            listing = shown
        try:  # EOF（输入关闭）= 取消选择，避免 _input 吞 EOF 后空行死循环
            line = tui.prompt(prompt).strip()
        except EOFError:
            return None
        if not line:
            continue
        low = line.lower()
        if low in ("q", "quit", "exit"):
            return None
        if in_pack is not None and low in ("n", "next"):
            page += 1
            continue
        if in_pack is not None and low in ("p", "prev"):
            page -= 1
            continue
        if in_pack is not None and low in ("b", "back"):
            in_pack = None
            continue
        tokens = line.split()
        if len(tokens) == 1 and tokens[0].isdigit():
            try:
                pick = listing[int(tokens[0]) - 1]
            except (ValueError, IndexError):
                print("序号不存在，请重新输入")
                continue
            if in_pack is None:
                in_pack = pick
                page = 0
                continue
            candidates = [pick]
        else:
            candidates = []
            for t in tokens:
                d = next((x for x in pool if x.name == t), None)
                if d is None:
                    print(f"未找到式神「{t}」，请重新输入")
                    candidates = None
                    break
                candidates.append(d)
            if candidates is None:
                continue
        if any(d.id in chosen_ids for d in candidates) \
                or len({d.id for d in candidates}) != len(candidates):
            print("式神不能重复，请重新输入")
            continue
        if len(chosen) + len(candidates) > need:
            print(f"还需 {need - len(chosen)} 名（本次输入 {len(candidates)} 名超出）")
            continue
        for d in candidates:
            chosen.append(d)
            chosen_ids.add(d.id)
        if len(chosen) < need:
            print(f"已选 {'、'.join(d.name for d in chosen)}（{len(chosen)}/{need}）")
    return chosen


def _print_cards(cards: list, copies: Counter | None = None) -> None:
    """两行式打印卡牌列表（首行对齐）：
    [序号] 名称｜类型[子类型]｜等级｜稀有度｜数值段 ×n；次行缩进 4 格为完整效果文本
    （无文本只打首行）。协战牌名前加 [协]。不显示费用。"""
    rows = []
    for i, c in enumerate(cards):
        name = f"[协]{c.name}" if c.card_type == "reinforce" else c.name
        mark = f"×{copies[c.id]}" if copies and copies.get(c.id) else ""
        rows.append((f"[{i + 1}]", name, cardfmt.ctype_label(c),
                     f"等级{c.level}", c.rarity or "",
                     cardfmt.static_stats(c), mark))
    for r, c in zip(cardfmt.align_rows(rows), cards):
        line = f"  {r[0]} {r[1]}｜{r[2]}｜{r[3]}｜{r[4]}"
        if r[5].strip() or r[6].strip():
            line += f"｜{r[5]} {r[6]}".rstrip()
        print(line)
        if c.text:
            print(f"    {c.text}")


def _deck_list_lines(decks: list[dict]) -> None:
    """本地卡组槽位列表：满足天梯规则的卡组以亮蓝色标明；附构筑环境标记。"""
    for i, d in enumerate(decks):
        print(colored(f"  [{i + 1}] {d['name']}（环境：{_env_label(d.get('env'))}）",
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


# ---------- 增量编辑循环 ----------

def _edit_deck(db: CardDatabase, env: int | None, team: list[int],
               picks: dict[int, list[int]]) -> tuple[list[int], list[int], int | None]:
    """在当前基础上编辑（db 为完整库，内部按 env 解析出环境库 edb 使用）：
    序号 = 编辑该式神卡牌；h <序号> = 更换式神（清空其卡牌）；
    e <环境> = 更改构筑环境（别名 S1/S2 或 8 位日期；环境下不存在的式神强制更换、
    卡牌自动移除）；Enter = 完成。
    完成时做 is_standard 检查：不满足标准规则时打印错误但仍返回
    （保存为非标准卡组），不强制要求合法。返回 (式神 ids, 卡牌 ids, env)。"""
    edb = db.at_date(env)
    while True:
        _print_deck(edb, team, picks)
        line = _input("序号 = 编辑该式神卡牌；h <序号> = 更换式神；"
                      "e <环境> = 更改环境（S1/S2 或日期）；Enter = 完成 > ")
        if not line:
            ids = list(team)
            card_ids = [cid for sid in team for cid in picks.get(sid, [])]
            errors = validate_deck(edb, ids, card_ids)
            if errors:
                print("")
                print("卡组不满足标准规则（仍保存，不标记为标准卡组）：")
                print("\n".join(errors))
            return ids, card_ids, env
        parts = line.lower().split()
        if parts[0] in ("e", "env") and len(parts) == 2:
            try:
                new_env = parse_env_input(parts[1])
            except ValueError as e:
                print(str(e))
                continue
            new_edb = db.at_date(new_env)
            # 新环境下不存在的式神需强制更换：先收集全部更换项，取消则整体放弃
            # （避免部分更换后回退环境留下不一致状态）
            swaps: dict[int, object] = {}
            for slot, sid in enumerate(team):
                if sid in new_edb.shikigami:
                    continue
                print(f"{db.shikigami[sid].name} 在该环境下不可用，请更换式神")
                result = _select_shikigami(
                    new_edb, need=1,
                    exclude=(set(team) | {d.id for d in swaps.values()}) - {sid})
                if result is None:
                    print("已取消，保留原环境")
                    swaps = None
                    break
                swaps[slot] = result[0]
            if swaps is None:
                continue
            for slot, new in swaps.items():
                picks.pop(team[slot], None)  # 旧式神卡牌一并清空
                team[slot] = new.id
                picks[new.id] = _pick_cards_strict(new_edb, new.id)
            env, edb = new_env, new_edb
            print(f"构筑环境已切换为 {_env_label(env)}")
            for sid in list(picks):  # 新环境下不存在的卡牌：自动移除
                kept = [c for c in picks[sid] if c in edb.cards]
                if len(kept) != len(picks[sid]):
                    print(f"{edb.shikigami[sid].name} 的 "
                          f"{len(picks[sid]) - len(kept)} 张牌在该环境下不可用，已移除")
                    picks[sid] = kept
            continue
        if parts[0] in ("h", "change") and len(parts) == 2:
            try:
                slot = int(parts[1]) - 1
                old = team[slot]
            except (ValueError, IndexError):
                print("序号有误")
                continue
            result = _select_shikigami(edb, need=1, exclude=set(team))
            if result is None:
                print("已取消更换")
                continue
            new = result[0]
            team[slot] = new.id
            picks.pop(old, None)      # 式神变更：清空其携带卡牌
            print(f"已更换为 {new.name}（需重新选牌）")
            picks[new.id] = _pick_cards_strict(edb, new.id)
            continue
        try:
            sid = team[int(parts[0]) - 1]
        except (ValueError, IndexError):
            print("输入有误")
            continue
        picks[sid] = _pick_cards_strict(edb, sid)


# ---------- 新建卡组的严格输入 ----------

def _pick_cards_strict(db: CardDatabase, sid: int) -> list[int]:
    """新建/编辑选牌：必须恰好 8 个空格分隔的序号（序号须存在）；反复询问直到合法。
    同名卡张数不做强制校验（构筑入口统一提示一次标准规则；超限卡组仍可保存，
    仅在完成时不满足 is_standard）。"""
    d = db.shikigami[sid]
    cards = buildable_cards(db, sid)
    print("")
    print(f"—— {d.name} 的卡牌（须恰好 8 张）——")
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
        return [c.id for c in picked]


def _interactive_build(db: CardDatabase, env: int | None,
                       ) -> tuple[list[int], list[int], int | None] | None:
    """新建卡组：二级目录选择 4 名式神（可全名直选）→ 各严格选 8 张牌 →
    进入增量编辑循环（Enter 完成）。选择阶段取消返回 None。
    式神/卡牌池按构筑环境 env 解析（None = 最新）。"""
    edb = db.at_date(env)
    chosen = _select_shikigami(edb, need=4)
    if chosen is None:
        print("已取消")
        return None
    team = [d.id for d in chosen]
    picks: dict[int, list[int]] = {}
    for d in chosen:
        picks[d.id] = _pick_cards_strict(edb, d.id)
    return _edit_deck(db, env, team, picks)


# ---------- 本地卡组槽位管理 ----------


def run_deckbuilder(db: CardDatabase, store_path=deckstore.PATH) -> None:
    """卡组构筑入口：本地卡组管理循环——编辑/重命名/删除/新建，q 返回主菜单。
    保存（编辑/新建/重命名/删除）成功后回到管理界面而非主菜单。"""
    tui.set_status(lambda: ("卡组构筑",
                            "序号=编辑 · r/d <序号> · Enter=新建 · q=返回"))
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
            line = tui.prompt("槽位序号 = 编辑该卡组；r <序号> <新名称> = 重命名；"
                              "d <序号> = 删除该卡组；Enter = 新建；q = 返回主菜单 > ").strip()
        except EOFError:
            return
        parts = line.split(maxsplit=2)
        if parts and parts[0].lower() in ("q", "quit", "exit"):
            return
        if len(parts) == 3 and parts[0] in ("r", "rename"):
            try:
                entry = decks[int(parts[1]) - 1]
            except (ValueError, IndexError):
                print("序号有误，已取消")
                continue
            entry["name"] = parts[2].strip()
            deckstore.save_decks(db, decks, store_path)
            print(f"已重命名为「{entry['name']}」")
            continue
        if len(parts) == 2 and parts[0] in ("d", "del", "delete"):
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
                env = entry.get("env")
                edb = db.at_date(env)
                ids, cards = deckstore.entry_deck(entry)
                deckcode.deck_from_code(edb, deckstore.entry_code(entry))  # 校验可用性
            except (ValueError, IndexError):
                print("序号有误或槽位卡组已失效，已取消")
                continue
            team = ids
            for cid in cards:  # 按所属式神分组（协战牌挂在队在的所属名下）
                c = edb.cards[cid]
                owner = c.shikigami if c.shikigami in team else c.shikigami2
                picks.setdefault(owner, []).append(cid)
            print()
            print(f"编辑卡组「{entry['name']}」（在当前基础上修改；"
                  f"环境：{_env_label(env)}）")
            print(f"卡组码：{deckstore.entry_code(entry)}")
        else:
            env = _ask_env()  # 新建卡组：先定构筑环境（Enter = 最新）
            edb = db.at_date(env)
        print()
        print("标准规则：")
        for line in rules_summary():
            print(f"  {line}")
        print("  （构筑不强制校验，超限卡组仍可保存，仅不标记为标准卡组）")
        print()
        name = _input("卡组名称（Enter = 沿用/自动命名）> ")

        code_line = _input("粘贴卡组码导入覆盖（Enter = 交互式构筑/编辑）> ")
        if code_line:
            try:
                ids, card_ids = deckcode.deck_from_code(edb, code_line)
            except ValueError as e:
                print(f"卡组码无效（{e}），未保存")
                continue
        else:
            result = (_edit_deck(db, env, team, picks) if team is not None
                      else _interactive_build(db, env))
            if result is None:
                continue
            ids, card_ids, env = result
            edb = db.at_date(env)
        if not name:
            name = decks[index]["name"] if index is not None else _deck_summary(edb, ids)
        groups = deckcode.group_deck(edb, ids, card_ids)
        entry = {"name": name, "groups": groups, "env": env}
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
                ) -> tuple[list[int], list[int], str] | None:
    """热坐/联机开局前选卡：从本地卡组文件的槽位中选择——不提供默认卡组/跳过
    （对局强制使用本地卡组）。回车 = 取消（返回 None）。

    所选卡组须满足对战模式的组卡规则（rules；本地 is_standard 标记对应天梯
    规则）；不满足时提示并重新选择。联机对战时服务端还会再次核验（房间入座
    时 deck_from_code 校验，见 server/room.py）。
    本地无卡组（文件不存在/为空）或全部不满足 rules 时，打印引导
    （主菜单「卡组构筑」创建）并返回 None——调用方据此取消开局、回主菜单。
    返回 (式神 ids, 卡牌 ids, 卡组码)；取消时为 None。"""
    decks = deckstore.load_decks(db, store_path)
    if not decks:
        print(f"[{label}] 本地卡组文件为空（请先在主菜单「卡组构筑」中创建卡组）")
        return None
    if not any(deckstore.check_deck(db, e["groups"], rules, e.get("env"))
               for e in decks):
        print(f"[{label}] 本地卡组均不满足当前对战模式的组卡规则"
              "（请先在主菜单「卡组构筑」中创建/调整卡组）")
        return None
    print(f"[{label}] 选择卡组（亮蓝 = 满足天梯规则，回车取消）：")
    _deck_list_lines(decks)
    while True:
        line = _input(f"[{label}] 卡组序号 > ")
        if not line:
            print(f"[{label}] 已取消选择")
            return None
        try:
            entry = decks[int(line) - 1]
        except (ValueError, IndexError):
            print("序号有误，请重新选择")
            continue
        if not deckstore.check_deck(db, entry["groups"], rules, entry.get("env")):
            print(f"卡组「{entry['name']}」不满足当前对战模式的组卡规则，"
                  "请重新选择")
            continue
        ids, cards = deckstore.entry_deck(entry)
        print(f"[{label}] 使用卡组「{entry['name']}」")
        return ids, cards, deckstore.entry_code(entry)
