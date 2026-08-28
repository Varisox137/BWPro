"""平衡性多版本：同名卡的 versions 结构与指定日期（环境）解析。

yaml 约定（同 db/schema.py 头部）：文件顶层只保留 id / name / versions 三项
（另可选 unreleased 标记，见下），全部规则数据存放在 versions.history 的
版本快照中：

    id: 10010101
    name: 示例卡
    unreleased: true        # 可选：未加入游戏标记——唯一版本日期为占位哨兵
                            # 20251212（任何环境日期都解析不到），本标记把"未加入"
                            # 语义显式化；loader 仍加载，环境解析与构筑池排除
    versions:
      best: 20251212        # 维护者手动标记的"历史最强"版本日期（仅元数据，
                            # 环境解析不使用；须等于某条 history 的 date）
      history:
        - date: 20251212    # 每条 = date + 该版本的全部完整卡牌数据（完整快照，
                            # 不按差量记录）；首条目的 date = 发布日期
          shikigami: 100101
          card_type: spell
          ...

环境解析规则（resolve_at_date）：取 date ≤ 环境日期 D 的最晚快照；最早快照
date > D → 该 id 在环境 D 下不可用；unreleased=true 的条目任何环境下不可用
（哨兵日期之外的第二道防线）。最新数据（resolve_latest）= date 最大的
快照——含未发布条目（loader 全量加载，定义上携带 unreleased 标记）。
解析结果 = 顶层 id/name（+ unreleased）+ 快照字段，version 字段 = 快照的 date。
"""
from __future__ import annotations

from db.schema import check_version_date

# 顶层身份字段：版本快照与解析结果中，id/name 恒取顶层值；history 条目不得重复
IDENTITY_KEYS = frozenset({"id", "name", "versions", "unreleased"})


def parse_versions(raw: dict) -> tuple[int | None, list[dict]]:
    """提取 (best, history)；结构非法时 history 按 [] 返回（由 validate 报错）。"""
    v = raw.get("versions")
    if not isinstance(v, dict):
        return None, []
    history = v.get("history") or []
    return v.get("best"), list(history)


def validate_versions(raw: dict) -> list[str]:
    """versions 结构校验，返回错误信息列表（空 = 通过）。"""
    errors: list[str] = []
    extra = set(raw) - IDENTITY_KEYS
    if extra:
        errors.append(f"顶层只允许 id/name/versions/unreleased，多余字段 {sorted(extra)}")
    v = raw.get("versions")
    if not isinstance(v, dict):
        return errors + ["缺 versions 块或结构非法"]
    best, history = parse_versions(raw)
    if not history:
        errors.append("versions.history 不能为空")
    dates: list[int] = []
    for i, entry in enumerate(history):
        if not isinstance(entry, dict):
            errors.append(f"history[{i}] 须为映射")
            continue
        d = entry.get("date")
        try:
            check_version_date(d)
        except (TypeError, ValueError):
            errors.append(f"history[{i}] date 须为 8 位数字日期")
            continue
        dates.append(d)
        bad = (set(entry) - {"date"}) & IDENTITY_KEYS
        if bad:
            errors.append(f"history[{i}] 不允许含身份字段 {sorted(bad)}")
        if "shikigami" in entry:
            errors.append(f"history[{i}] 的 shikigami 由 id 推导，不入数据")
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        errors.append("history 的 date 须严格递增")
    if best is not None:
        try:
            check_version_date(best)
        except (TypeError, ValueError):
            errors.append("versions.best 须为 8 位数字日期")
        else:
            if best not in dates:
                errors.append("versions.best 须等于某条 history 的 date")
    return errors


def resolve_at_date(raw: dict, date: int,
                    *, include_unreleased: bool = False) -> dict | None:
    """原始 yaml dict 在环境日期下的完整定义（顶层 id/name + 最晚不晚于该日期
    的快照，version = 快照 date）；该日期下尚未发布返回 None。
    unreleased=true（未加入游戏）的条目任何环境下不可用——除非
    include_unreleased=True（resolve_latest 全量加载用）。"""
    if raw.get("unreleased") and not include_unreleased:
        return None
    _, history = parse_versions(raw)
    chosen: dict | None = None
    for entry in history:
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), int):
            continue
        if entry["date"] <= date and (chosen is None
                                      or entry["date"] > chosen["date"]):
            chosen = entry
    if chosen is None:
        return None
    out = {k: raw[k] for k in ("id", "name", "unreleased")
           if k in raw}  # 灵咒顶层无 id（仅 name）
    out.update({k: v for k, v in chosen.items() if k != "date"})
    out["version"] = chosen["date"]
    return out


def resolve_latest(raw: dict) -> dict | None:
    """最新版本（date 最大的快照）；无合法快照返回 None。含未发布条目
    （unreleased 标记随定义携带，由环境解析/构筑池排除）。"""
    return resolve_at_date(raw, 99999999, include_unreleased=True)
