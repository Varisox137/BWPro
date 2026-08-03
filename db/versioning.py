"""平衡性多版本：同名卡的 versions 结构与指定日期（环境）解析。

yaml 约定（同 db/schema.py 头部）：

    version: 20250601      # 最新平衡性日期（现有字段，语义不变）
    versions:              # 可选；无平衡史则不写
      best: 20250301       # 维护者手动标记的"历史最强"版本日期（仅元数据，
                           # 环境解析不使用；须等于某个版本日期）
      history:
        - date: 20250101   # 首条目 = 发布版本完整快照（身份字段以外全部字段），
                           # 其 date = 该卡牌/式神的发布日期
          power: 3
          text: "..."
        - date: 20250301   # 后续条目 = 相对前一版本的字段差量
          power: 4

环境解析规则（resolve_at_date）：候选记录 = history 各条目 + 基础字段
（date = version）；取 date ≤ 环境日期 D 的记录按日期升序逐条覆盖合并，
结果为该 id 在 D 时刻的定义；最早记录 date > D → 该 id 在环境 D 下不可用。
无 history 时退化为：D ≥ version 可用（基础定义），否则不可用。
"""
from __future__ import annotations

from db.schema import check_version_date

# 身份字段：版本时间线中不可变，history 条目不允许出现；环境解析结果中这些字段
# 恒取基础定义的值（kind 为式神定义的身份字段）
IMMUTABLE_KEYS = frozenset(
    {"id", "name", "shikigami", "shikigami2", "card_type", "kind",
     "version", "versions"})


def parse_versions(raw: dict) -> tuple[int | None, list[dict]]:
    """提取 (best, history)；无 versions 字段返回 (None, [])。"""
    v = raw.get("versions")
    if not isinstance(v, dict):
        return None, []
    history = v.get("history") or []
    return v.get("best"), list(history)


def validate_versions(raw: dict) -> list[str]:
    """versions 结构校验，返回错误信息列表（空 = 通过）。"""
    errors: list[str] = []
    if "versions" not in raw:
        return errors
    v = raw["versions"]
    if not isinstance(v, dict):
        return ["versions 须为映射（best/history）"]
    best, history = parse_versions(raw)
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
        bad = (set(entry) - {"date"}) & IMMUTABLE_KEYS
        if bad:
            errors.append(f"history[{i}] 不允许含身份字段 {sorted(bad)}")
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        errors.append("history 的 date 须严格递增")
    if best is not None:
        try:
            check_version_date(best)
        except (TypeError, ValueError):
            errors.append("versions.best 须为 8 位数字日期")
        else:
            if best not in dates and best != raw.get("version"):
                errors.append("versions.best 须等于某个版本日期"
                              "（history 条目 date 或 version）")
    if dates and dates[-1] >= raw.get("version", 0):
        errors.append("history 的 date 须早于最新 version（history 只存历史版本）")
    return errors


def resolve_at_date(raw: dict, date: int) -> dict | None:
    """原始 yaml dict 在环境日期下的定义；该日期下尚未发布返回 None。

    结果剥离 versions 键，version 写为实际生效记录的日期。"""
    _, history = parse_versions(raw)
    base_version = raw["version"]
    if not history:
        if date >= base_version:
            return {k: v for k, v in raw.items() if k != "versions"}
        return None
    if date < history[0]["date"]:  # 早于发布日期
        return None
    if date >= base_version:
        return {k: v for k, v in raw.items() if k != "versions"}
    # 逐条合并 date ≤ D 的历史记录（首条目为完整快照，后续为差量）：
    # 结果字段集 = 身份字段（基础值）∪ 合并后的效果字段，
    # 基础定义中后来才新增、历史上不存在的字段自然被剔除
    merged: dict = {}
    effective = history[0]["date"]
    for entry in history:
        if entry["date"] > date:
            break
        effective = entry["date"]
        merged.update({k: v for k, v in entry.items() if k != "date"})
    out = {k: raw[k] for k in raw if k in IMMUTABLE_KEYS
           and k not in ("version", "versions")}
    out.update(merged)
    out["version"] = effective
    return out
