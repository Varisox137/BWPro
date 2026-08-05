"""卡牌文本表格的统一格式化：卡组构筑与对局（调度/回合内手牌）共用一套流程。

流程：各行由调用方组好字段元组（row builder）→ align_rows 按显示宽度逐列对齐
→ 调用方拼接成行（可对个别单元格着色）。静态字段（类型/数值段）由本模块统一
提供；对局内的动态段（uid/费用修正/增强/动态战力）由 client/cli.py 组装。
"""
from __future__ import annotations

from client.textutil import display_width, pad

CTYPE_NAMES = {"spell": "法术", "combat": "战斗", "form": "形态",
               "field": "幻境", "reinforce": "协战"}


def ctype_label(cdef) -> str:
    """主类型[子类型] 显示名。"""
    base = CTYPE_NAMES.get(cdef.card_type, cdef.card_type)
    return f"{base}[{cdef.subtype}]" if cdef.subtype else base


def static_stats(cdef) -> str:
    """卡牌数值段（静态求值）：形态身材、倒计时、战斗牌力量/护甲、觉醒永久身材。"""
    parts: list[str] = []
    if cdef.card_type == "form" and cdef.form_power is not None:
        parts.append(f"身材{cdef.form_power}/{cdef.form_health}")
    if cdef.countdown is not None:
        parts.append(f"倒计时{cdef.countdown}")
    if cdef.card_type == "combat":
        pw = sh = 0
        for st in cdef.effects.steps:
            extra = st.model_extra or {}
            if st.op == "buff_power" and isinstance(extra.get("amount"), int):
                pw += extra["amount"]
            elif st.op == "gain_shield" and isinstance(extra.get("amount"), int):
                sh += extra["amount"]
        if pw:
            parts.append(f"力量{pw:+d}")
        if sh:
            parts.append(f"护甲+{sh}")
    if cdef.subtype == "awaken":
        pw = hp = 0
        for st in cdef.effects.steps:
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


def align_rows(rows: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """按显示宽度逐列对齐（每列 pad 到该列最大宽度）。空行（空元组）原样保留。"""
    cols = max((len(r) for r in rows), default=0)
    widths = [max((display_width(r[k]) for r in rows if len(r) > k), default=0)
              for k in range(cols)]
    return [tuple(pad(r[k], widths[k]) for k in range(len(r))) if r else r
            for r in rows]
