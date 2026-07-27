"""卡组构筑与战前选卡（交互式）。

- 本地卡组文件（db/deckstore.py，~/.bwp.decks.json）：进入构筑时读取全部槽位，
  可编辑现有槽位或新建；编辑/新建均支持卡组码导入；命名校验通过即自动写回。
- choose_deck：热坐对战与联机对战开局前的统一选卡入口（本地槽位选择；
  文件为空时回退到卡组码输入 / 默认卡组）。
- 卡组码格式见 db/deckcode.py；主菜单入口见 client/cli.py。
"""
from __future__ import annotations

from db import deckcode, deckstore
from db.deck import MAX_COPIES_PER_NAME, MAX_KINDS_PER_SHIKIGAMI, validate_deck
from db.loader import CardDatabase

_CTYPES = {"spell": "法术", "combat": "战斗", "form": "形态",
           "field": "幻境", "reinforce": "协战"}


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
        return input(prompt).strip()
    except EOFError:
        return ""


def _deck_summary(db: CardDatabase, ids: list[int]) -> str:
    return "/".join(db.shikigami[s].name for s in ids)


# ---------- 交互式构筑 ----------


def _interactive_build(db: CardDatabase) -> tuple[list[int], list[int]] | None:
    """选择 4 名式神 → 各选卡牌并设定张数。校验通过返回 (式神 ids, 卡牌 ids)，
    取消/不合法返回 None。"""
    pool = available_shikigami(db)
    print("—— 选择 4 名出战式神 ——")
    for i, d in enumerate(pool):
        print(f"  [{i + 1}] {d.name}（{d.faction}）")
    try:
        chosen = [pool[int(x) - 1] for x in _input("式神序号（空格分隔）> ").split()]
    except (ValueError, IndexError):
        print("序号有误，已取消构筑")
        return None
    ids = [d.id for d in chosen]
    card_ids: list[int] = []
    for d in chosen:
        cards = buildable_cards(db, d.id)
        print(f"—— {d.name} 的卡牌（至多 {MAX_KINDS_PER_SHIKIGAMI} 种，"
              f"每种至多 {MAX_COPIES_PER_NAME} 张）——")
        for i, c in enumerate(cards):
            ctype = _CTYPES.get(c.card_type, c.card_type)
            print(f"  [{i + 1}] {c.name}｜{ctype}｜等级{c.level}｜费用{c.cost}")
        line = _input("卡牌种类序号（空格分隔；回车 = 全部）> ")
        try:
            picked = cards if not line else [cards[int(x) - 1] for x in line.split()]
        except (ValueError, IndexError):
            print("序号有误，已取消构筑")
            return None
        copies = {i + 1: 1 for i in range(len(picked))}
        tune = _input("张数调整（如 1=2 3=2；回车 = 每种 1 张）> ")
        for item in tune.split():
            try:
                k, v = item.split("=")
                copies[int(k)] = int(v)
            except ValueError:
                print(f"无法解析 {item!r}，已忽略")
        for i, c in enumerate(picked):
            n = max(0, min(MAX_COPIES_PER_NAME, copies.get(i + 1, 1)))
            card_ids.extend([c.id] * n)
        print(f"当前共 {len(card_ids)} 张（每名式神须恰好 "
              f"{MAX_KINDS_PER_SHIKIGAMI} 张）")
    errors = validate_deck(db, ids, card_ids)
    if errors:
        print("卡组不合法：")
        print("\n".join(errors))
        return None
    return ids, card_ids


# ---------- 本地卡组槽位管理 ----------


def run_deckbuilder(db: CardDatabase, store_path=deckstore.PATH) -> None:
    """卡组构筑入口：读取本地卡组文件 → 选择槽位编辑或新建 → 卡组码导入 /
    交互式构筑 → 校验通过自动写回本地文件。"""
    decks = deckstore.load_decks(store_path)
    print(f"—— 卡组构筑（本地卡组文件：{store_path}）——")
    for i, d in enumerate(decks):
        print(f"  [{i + 1}] {d['name']}")
    line = _input("槽位序号 = 编辑该卡组；回车 = 新建 > ")
    index: int | None = None
    if line:
        try:
            index = int(line) - 1
            entry = decks[index]
            ids, cards = deckcode.deck_from_code(db, entry["code"])
            print(f"当前卡组「{entry['name']}」：{_deck_summary(db, ids)}（{len(cards)} 张）")
        except (ValueError, IndexError):
            print("序号有误或槽位卡组已失效，已取消")
            return
    name = _input("卡组名称（回车 = 沿用/自动命名）> ")

    code_line = _input("粘贴卡组码导入（回车 = 交互式构筑）> ")
    if code_line:
        try:
            ids, card_ids = deckcode.deck_from_code(db, code_line)
        except ValueError as e:
            print(f"卡组码无效（{e}），未保存")
            return
        code = code_line
    else:
        result = _interactive_build(db)
        if result is None:
            return
        ids, card_ids = result
        code = deckcode.encode_deck(deckcode.group_deck(db, ids, card_ids))
    if not name:
        name = decks[index]["name"] if index is not None else _deck_summary(db, ids)
    entry = {"name": name, "code": code}
    if index is None:
        decks.append(entry)
        slot = len(decks)
    else:
        decks[index] = entry
        slot = index + 1
    deckstore.save_decks(decks, store_path)
    print(f"卡组「{name}」已保存（共 {len(card_ids)} 张，槽位 {slot}）")
    print(f"卡组码（导出/分享）：{code}")


# ---------- 战前选卡 ----------


def choose_deck(db: CardDatabase, label: str,
                store_path=deckstore.PATH) -> tuple[list[int], list[int], str]:
    """热坐/联机开局前选卡：读取本地卡组文件并要求从中选择槽位；
    文件为空时回退到卡组码输入（回车 = 默认卡组）。
    返回 (式神 ids, 卡牌 ids, 卡组码)。"""
    decks = deckstore.load_decks(store_path)
    if decks:
        print(f"[{label}] 选择卡组：")
        for i, d in enumerate(decks):
            print(f"  [{i + 1}] {d['name']}")
        line = _input(f"[{label}] 卡组序号 > ")
        try:
            entry = decks[int(line) - 1]
            ids, cards = deckcode.deck_from_code(db, entry["code"])
            print(f"[{label}] 使用卡组「{entry['name']}」")
            return ids, cards, entry["code"]
        except (ValueError, IndexError):
            print("序号有误，改用默认卡组")
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
