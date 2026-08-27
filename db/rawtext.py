"""card_data_raw.md 解析与 db yaml text 逐字对齐校验（db.validate 硬门禁）。

raw 是唯一事实来源（AGENTS.md 内容约定）：式神/卡牌/灵咒 yaml 各版本快照的
text 字段须逐字等于 raw 对应条目引号内原文（全角引号“”内文本，含嵌套引号——
如‘替换为“棺材”’，提取时按深度配对；raw 有个别把闭引号误写成开引号的行，
深度配对失败时回退取行内最后一个引号字符为闭引号）。

匹配按名字：raw 条目的 [母卡] 后缀与（…未加入…）标注先剥离；raw 的"A/B"双名
条目按分段匹配 yaml 单名（如《破魔符/破魔箭》↔《破魔符》）；重名条目（同式神
下的卡牌与召唤物，如冰墙/番茄）按（所属式神号段, 条目序号）配对。

另含 README 卡名/式神名扫描（README 约定不出现具体名字；单字名误报面大，豁免）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

RAW_PATH = Path(__file__).parent.parent / "card_data_raw.md"
README_PATH = Path(__file__).parent.parent / "README.md"


@dataclass
class RawEntry:
    """raw 中的一个条目（式神/卡牌/灵咒/衍生物实体）。"""
    name: str                                  # 规范名（剥离 [母卡] 后缀与（未加入）标注）
    lineno: int
    sid: int | None = None                     # 所属式神号段（最近的 6 位 id 条目）
    num: int | None = None                     # 条目序号（卡牌/实体的 2 位号；式神/灵咒为 None）
    dated: dict[int, str | None] = field(default_factory=dict)  # 版本日期 → 引号文本
                                                                 # （None = 该日期仅调整说明，无引号文本）
    undated: str | None = None                 # 无日期文本（新手包行内条 / 未加入协战子卡单条）

    def text_at(self, date: int | None) -> tuple[bool, str | None]:
        """该日期应使用的文本。返回 (该日期已在 raw 登记, 文本)。

        文本取当日引号文本；raw 该日期仅调整说明（无引号文本）时沿用最近更早日期
        文本；再无则取无日期文本。条目完全无日期行时按无日期文本比对（始终已登记）。
        """
        if not self.dated:
            return True, self.undated
        if date in self.dated:
            t = self.dated[date]
            if t is not None:
                return True, t
            earlier = [d for d in self.dated if date is not None and d < date
                       and self.dated[d] is not None]
            if earlier:
                return True, self.dated[max(earlier)]
            return True, self.undated
        return False, None  # yaml 有该日期快照但 raw 未登记此版本


def _extract_quoted(line: str) -> str | None:
    """取行内第一段顶层全角引号“...”文本（“”按深度配对，允许嵌套）。

    容错：raw 个别行把闭引号误写成开引号（深度无法归零），此时回退以行内最后
    一个引号字符（“或”）为闭引号。
    """
    depth = 0
    start = -1
    last_quote = -1
    for i, ch in enumerate(line):
        if ch == "“":
            if depth == 0:
                start = i + 1
            depth += 1
            last_quote = i
        elif ch == "”":
            last_quote = i
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    return line[start:i]
    if start >= 0 and last_quote >= start:
        return line[start:last_quote]
    return None


def _clean_name(name: str) -> str:
    """剥离条目名后的 [母卡] 标注与（…未加入…）标注。"""
    name = re.sub(r"\[[^\]]*\]", "", name)
    name = re.sub(r"（[^）]*未加入[^）]*）", "", name)
    return name.strip()


def parse_raw(path: Path = RAW_PATH) -> list[RawEntry]:
    """解析 card_data_raw.md：#### 式神节下的 `- ` 条目行 + `  - ` 版本行。"""
    entries: list[RawEntry] = []
    current: RawEntry | None = None
    cur_sid: int | None = None
    in_sections = False  # 跳过文件头"格式约定"节的说明行
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("#### "):
            in_sections = True
            current = None
            continue
        if line.startswith("#"):
            current = None
            continue
        if not in_sections:
            continue
        if line.startswith("- "):
            body = line[2:]
            name: str | None = None
            num: int | None = None
            if body.startswith("灵咒/鬼斩 "):
                name = body[len("灵咒/鬼斩 "):]
            elif body.startswith("灵咒 "):
                name = body[len("灵咒 "):]
            elif re.match(r"\d{6} ", body):        # 式神：- 100101 白狼 苍叶
                parts = body.split()
                cur_sid = int(parts[0])
                name = parts[1]
            elif re.match(r"\d{2} ", body):        # 卡牌/实体：- 01 起弓 / - 99 棺材 式神/变形物
                parts = body.split()
                num = int(parts[0])
                name = parts[1]
            if name is None:
                current = None
                continue
            current = RawEntry(_clean_name(name), lineno, sid=cur_sid, num=num)
            entries.append(current)
            # 行内引号文本（新手包：- 100001 纸人武士 红莲 3/4 “无基础能力”）
            q = _extract_quoted(body)
            if q is not None:
                current.undated = q
            continue
        m = re.match(r"^  - (?:(\d{8})：)?", line)
        if m and current is not None:
            q = _extract_quoted(line)
            if m.group(1):
                current.dated[int(m.group(1))] = q  # 无引号文本记 None（仅调整说明）
            elif q is not None:
                current.undated = q
    return entries


def _yaml_items(db) -> dict[str, list[tuple[str, int | None, dict]]]:
    """yaml 侧按名归组：名字 → [(标签, id 或 None, 原始 yaml dict)]。"""
    items: dict[str, list[tuple[str, int | None, dict]]] = {}
    for i, raw in db.raw_cards.items():
        items.setdefault(raw.get("name"), []).append((f"卡牌 {i}《{raw.get('name')}》", i, raw))
    for i, raw in db.raw_shikigami.items():
        items.setdefault(raw.get("name"), []).append((f"式神 {i}《{raw.get('name')}》", i, raw))
    for n, raw in db.raw_invocations.items():
        items.setdefault(n, []).append((f"灵咒《{n}》", None, raw))
    return items


def _snapshots(raw: dict) -> list[dict]:
    return (raw.get("versions") or {}).get("history") or []


def _compare_entry(label: str, raw: dict, entry: RawEntry,
                   errors: list[str], warnings: list[str]) -> None:
    """逐版本比对一个 yaml 与一条 raw 条目的 text。"""
    for snap in _snapshots(raw):
        date = snap.get("date")
        ytext = snap.get("text")
        known, rtext = entry.text_at(date)
        at = f"{label} @{date}"
        if not known:
            warnings.append(f"{at}: 该版本日期未在 raw 对应条目登记（跳过 text 比对）")
            continue
        if rtext is None:
            if ytext:
                errors.append(f"{at}: raw 无引号文本但 yaml 有 text: “{ytext}”")
        elif ytext is None:
            errors.append(f"{at}: raw 有引号文本但 yaml 缺 text: “{rtext}”")
        elif ytext != rtext:
            errors.append(f"{at}: text ≠ raw（yaml: “{ytext}” / raw: “{rtext}”）")
    ydates = {s.get("date") for s in _snapshots(raw)}
    for d in entry.dated:
        if d not in ydates:
            warnings.append(f"{label}: raw 有 {d} 版本文本但 yaml 无该日期快照")


def check_text_alignment(db, raw_path: Path = RAW_PATH) -> tuple[list[str], list[str]]:
    """逐版本比对 yaml text 与 raw 引号文本。返回 (错误, 警告)。

    错误：raw 已登记日期的引号文本与 yaml text 不等/缺失/多出。
    警告：名字匹配不上（raw 有但无对应 yaml / yaml 有但 raw 找不到）、
    名称多义无法配对、yaml 版本日期未在 raw 登记、raw 版本日期 yaml 缺快照。
    """
    entries = parse_raw(raw_path)
    raw_by_name: dict[str, list[RawEntry]] = {}
    for e in entries:
        raw_by_name.setdefault(e.name, []).append(e)
    # "A/B"双名条目的分段索引（yaml 用单名，如 raw《破魔符/破魔箭》↔ yaml《破魔符》）
    seg_index: dict[str, list[RawEntry]] = {}
    for e in entries:
        if "/" in e.name:
            for seg in e.name.split("/"):
                seg_index.setdefault(seg, []).append(e)

    errors: list[str] = []
    warnings: list[str] = []
    matched: set[int] = set()
    for name, items in _yaml_items(db).items():
        cands = raw_by_name.get(name) or seg_index.get(name)
        if not cands:
            warnings.append(f"yaml 有但 raw 无对应条目：{items[0][0]}")
            continue
        if len(cands) == 1 and len(items) == 1:
            matched.add(id(cands[0]))
            _compare_entry(items[0][0], items[0][2], cands[0], errors, warnings)
            continue
        # 重名（同式神下的卡牌与召唤物/变形物，如冰墙/番茄）：按（号段, 序号）配对
        unpaired: list[tuple[str, int | None, dict]] = []
        for label, iid, raw in items:
            pair = next((e for e in cands
                         if iid is not None and e.sid == iid // 100
                         and e.num == (iid % 100 if iid >= 10_000_000 else None)
                         and id(e) not in matched), None)
            # 6 位式神条目（num=None）配对：iid < 10_000_000 时按 sid 直配
            if pair is None and iid is not None and iid < 10_000_000:
                pair = next((e for e in cands if e.sid == iid and e.num is None
                             and id(e) not in matched), None)
            if pair is None:
                unpaired.append((label, iid, raw))
                continue
            matched.add(id(pair))
            _compare_entry(label, raw, pair, errors, warnings)
        for label, iid, raw in unpaired:
            has_text = any(s.get("text") for s in _snapshots(raw))
            if has_text:
                warnings.append(f"名称多义且无法按序号配对，跳过逐字比对：{label}")
    for e in entries:
        if id(e) not in matched and (e.dated or e.undated):
            warnings.append(f"raw 第 {e.lineno} 行条目《{e.name}》有文本但无对应 yaml")
    return errors, warnings


def check_readme_names(db, readme_path: Path = README_PATH) -> list[str]:
    """README 不得出现具体式神名/卡牌名（内容约定）。单字名误报面大（如"薰"），豁免。"""
    text = readme_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    names = {c.name for c in db.cards.values()} | {s.name for s in db.shikigami.values()}
    errors: list[str] = []
    for n in sorted(names):
        if len(n) < 2 or n not in text:
            continue
        hit = next(i for i, ln in enumerate(lines, 1) if n in ln)
        errors.append(f"README.md 第 {hit} 行出现式神/卡牌名《{n}》"
                      f"（约定：README 不出现具体式神/卡牌名）")
    return errors
