"""对局环境（平衡性版本日期）的别名注册表与输入解析。

标准环境 = 最新一次平衡性调整或新卡加入的日期（代码中 env_date=None，
resolve_latest）。自由环境以 8 位日期（YYYYMMDD）或 6 位日期（YYMMDD，
按 20YY 展开）指定，常用环境可登记短别名：

    经典 = 公测 = 20191212        # 公测开服数据
    不夜之火 = 20200327           # 不夜之火版本（第三次平衡性调整 + 新包）

联机房间（server/room.py）与卡组构筑（client/deckbuilder.py）的环境输入
统一经 parse_env_input 解析、显示统一经 env_label。
"""
from __future__ import annotations

from db.schema import check_version_date

# 环境别名 → 日期（登记即生效，输入大小写不敏感。
# 同一日期可登记多个别名，env_label 显示取先登记者）
ENV_ALIASES: dict[str, int] = {
    "经典": 20191212,
    "公测": 20191212,
    "不夜之火": 20200327,
}


def parse_env_input(text: str) -> int | None:
    """解析环境输入：空串 → None（标准环境/最新）；别名（大小写不敏感）→
    对应日期；8 位数字（YYYYMMDD）或 6 位数字（YYMMDD，按 20YY 展开）→
    校验为合法日期。其余抛 ValueError。"""
    line = text.strip()
    if not line:
        return None
    alias = ENV_ALIASES.get(line.upper())
    if alias is not None:
        return alias
    if line.isdigit() and len(line) == 6:
        line = "20" + line
    try:
        return check_version_date(int(line))
    except ValueError:
        raise ValueError(
            "环境须为环境别名或合法日期（YYYYMMDD / YYMMDD）"
        ) from None


def env_label(date: int | None) -> str:
    """环境显示名：None → 标准(最新)；命中别名 → 经典(20191212)；否则日期串。"""
    if date is None:
        return "标准(最新)"
    for alias, d in ENV_ALIASES.items():
        if d == date:
            return f"{alias}({date})"
    return str(date)
