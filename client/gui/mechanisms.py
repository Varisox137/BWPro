"""详情弹窗的关键字/机制提取与 BWPDIY 机制框渲染。"""
from __future__ import annotations

import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from client.cli import KEYWORD_CN
from client.gui.cardart import _renderer
from client.gui.portrait import bwpdiy_root, library_root

MECHANISM_TEXTS = {
    "不屈": "生命大于1时，受到致命伤害会保留1点生命；一次性不屈触发后消耗。",
    "倒计时": "己方回合开始时倒计时减1，归零时触发对应能力；随后按来源规则重置或移除。",
    "充能": "己方回合开始时，该式神能量加1；气绝期间不充能。",
    "先攻": "在战斗的先攻阶段造成战斗伤害，交战阶段不再造成伤害。",
    "吸血": "造成携带吸血属性的伤害后，伤害来源所属牌手恢复等量生命。",
    "响应": "敌方回合满足触发条件时自动使用，仍须满足使用限制并支付相应消耗。",
    "唯一": "同名效果不能按通常方式重复共存，再次获得时按对应规则处理。",
    "增强": "满足卡面所列条件时，获得额外的效果或数值修正。",
    "帷幕": "不能成为敌方出击或使用卡牌的目标；不取对象的全体与随机效果不受影响。",
    "庇佑": "一次性抵消一次敌方来源的法术伤害，抵消后失去。",
    "弹回": "使用并结算完毕后移回手牌而非留在墓地；回手后失去弹回。",
    "必杀": "造成伤害后，使受到伤害的角色气绝；伤害被免疫或未造成时不触发。",
    "投射": "优先以敌方战斗区式神为目标；战斗区为空时改为以敌方牌手为目标。",
    "暴击": "携带暴击属性的伤害翻倍，伤害类型不限。",
    "条件": "满足卡面所列条件后，才执行对应效果或获得对应能力。",
    "爆能": "使用卡牌时额外消耗指定能量，获得增强或替代效果；爆能X消耗全部能量。",
    "直击": "无目标的战斗改为攻击敌方牌手，无视敌方战斗区式神。",
    "眩晕": "眩晕的式神不能出击或主动、响应使用卡牌；牌手眩晕时其式神不能出击。",
    "瞬发": "每个半回合，各自使用的第一张瞬发牌不消耗鬼火。",
    "移动": "在战斗区与准备区之间移动，不发起攻击；召唤物退回准备区时离场。",
    "羁绊": "使用协战牌时，若对应式神等级不为0且未气绝，触发羁绊效果。",
    "觉醒": "替换式神的基础能力，并获得觉醒牌所述的永久修正与效果。",
    "贯通": "对式神造成非反击伤害时，超过其当前生命的部分改由所属牌手承受。",
    "迅捷": "出击时不消耗鬼火，随后失去一个一次性迅捷；仍消耗出击次数。",
    "运势": "投掷一枚六面骰，点数大于或等于运势X的X时判定成功。",
    "远程": "不进入战斗区，不受先攻及交战阶段的反击伤害。",
    "连击": "先攻阶段与交战阶段各造成一次战斗伤害。",
    "鼓舞": "下一次出击时消耗全部鼓舞，获得相应的力量与护甲加成。",
    "追猎": "主动出击或战斗牌可以指定一名合法敌方式神作为战斗目标。",
    "屏障": "一次性将一次伤害的伤害值改为0，随后移除一个屏障实例。",
    "激怒": "有可出击的激怒式神时，其他未激怒式神不能出击；发起战斗后移除激怒。",
    "穿刺": "造成伤害前，移除受伤者的全部护甲与屏障。",
    "幻境": "进入所属牌手的幻境队列；牌手受到伤害时，队首幻境以耐久代为承受。",
    "灵咒": "结附于式神或卡牌上的具名持续效果，按唯一性与离场规则处理。",
    "协战": "在两位所属式神中选择一种子选项使用；对应式神在场时可触发羁绊。",
    "符咒": "具有特殊使用方式的卡牌子类型，可按文本通过爆能转化。",
    "委托": "每日替换的任务；完成指定条件后，获得对应奖励或效果。",
}

_KEYWORD_IDS = {
    **KEYWORD_CN,
    "direct": "直击", "hunt": "追猎", "critical": "暴击", "lifesteal": "吸血",
    "lethal": "必杀", "veil": "帷幕", "blessing": "庇佑", "rebound": "弹回",
    "charge": "充能", "stun": "眩晕", "inspire": "鼓舞", "move": "移动",
}
_BRACKET_TERM = re.compile(r"\[([^\[\]\n]{1,16})\]")


def _canonical_name(token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"运势\d+", token):
        return "运势"
    if re.fullmatch(r"爆能(?:\d+|X)", token):
        return "爆能"
    if re.fullmatch(r"倒计时\d+", token):
        return "倒计时"
    return _KEYWORD_IDS.get(token, token)


@lru_cache(maxsize=16)
def _library_mechanisms(root_text: str) -> dict[str, dict]:
    definitions = {}
    for path in sorted((Path(root_text) / "mechanisms").glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_bytes())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or not data.get("name") or not data.get("text"):
            continue
        definitions[str(data["name"])] = {
            field: data.get(field)
            for field in ("name", "frame", "text", "badge", "version_date")
        }
    return definitions


def _add_mechanism(mechanisms: list[dict], name: str, *, frame: str = "skill",
                   text: str | None = None) -> None:
    definition = _library_mechanisms(str(library_root().resolve())).get(name) \
        if text is None else None
    if definition is not None:
        frame = definition["frame"] or frame
        description = definition["text"]
    else:
        description = MECHANISM_TEXTS.get(name) if text is None else text
    if description and not any(item["name"] == name and item["frame"] == frame
                               for item in mechanisms):
        item = {"name": name, "frame": frame, "text": description}
        if definition is not None:
            item.update(badge=definition["badge"], version_date=definition["version_date"])
        mechanisms.append(item)


def _add_text(mechanisms: list[dict], text: str | None) -> None:
    for token in _BRACKET_TERM.findall(text or ""):
        _add_mechanism(mechanisms, _canonical_name(token))


def card_mechanisms(cdef, runtime: dict | None = None) -> list[dict]:
    """按卡面出现顺序提取机制，再补运行时关键字与卡牌类型机制。"""
    mechanisms: list[dict] = []
    _add_text(mechanisms, getattr(cdef, "text", None))
    for keyword in getattr(cdef, "keywords", ()):
        _add_mechanism(mechanisms, _canonical_name(keyword))
    for keyword in (runtime or {}).get("keywords", ()):
        _add_mechanism(mechanisms, _canonical_name(keyword))
    card_type = getattr(cdef, "card_type", None)
    if card_type in ("field", "reinforce"):
        _add_mechanism(mechanisms, {"field": "幻境", "reinforce": "协战"}[card_type])
    if getattr(cdef, "subtype", None) in ("awaken", "talisman", "quest"):
        _add_mechanism(mechanisms, {"awaken": "觉醒", "talisman": "符咒",
                                    "quest": "委托"}[cdef.subtype])
    return mechanisms


def shikigami_mechanisms(game, ref, status_texts=()) -> list[dict]:
    """按主卡、形态、额外状态文本及当前关键字顺序提取机制说明。"""
    shiki = game.state.players[ref.player].shikigami[ref.shikigami]
    main_def = (game.db.cards[shiki.awakened] if shiki.awakened is not None
                else game.db.shikigami[shiki.id])
    mechanisms = card_mechanisms(main_def)
    if shiki.form is not None:
        for item in card_mechanisms(game.db.cards[shiki.form.id]):
            _add_mechanism(mechanisms, item["name"], frame=item["frame"], text=item["text"])
    for text in status_texts:
        _add_text(mechanisms, text)
    for keyword in shiki.keywords + shiki.one_shot_keywords + shiki.perm_keywords:
        _add_mechanism(mechanisms, _canonical_name(keyword))
    for buff in shiki.attack_buffs:
        for keyword, _cls in buff.get("keywords", ()):
            _add_mechanism(mechanisms, _canonical_name(keyword))
    return mechanisms


@lru_cache(maxsize=256)
def _mechanism_pixmap(name: str, frame: str, text: str, root_text: str,
                      chars_per_line: int | None = None,
                      font_scale: float = 1.0) -> QPixmap | None:
    try:
        assets, _library, _render = _renderer(root_text)
        from bwpdiy.render.layout import load_layouts
        from bwpdiy.render.mech import render_mechanism

        image = render_mechanism({"name": name, "frame": frame, "text": text}, assets,
                                 layout=load_layouts(assets).get("机制"),
                                 chars_per_line=chars_per_line, font_scale=font_scale)
        buffer = BytesIO()
        image.save(buffer, "PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            return None
        return pixmap
    except Exception:
        return None


def mechanism_panel(mechanisms: list[dict], parent=None, *, chars_per_line: int | None = None,
                    font_scale: float = 1.0, max_height: int = 220):
    """生成可滚动的机制框列表；无有效机制时返回 (None, [])。"""
    panel = QScrollArea(parent)
    panel.setWidgetResizable(True)
    panel.setFrameShape(QFrame.NoFrame)
    panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    panel.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    panel.setMaximumHeight(max_height)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    labels = []
    root_text = str(bwpdiy_root().resolve())
    for mechanism in mechanisms:
        pixmap = _mechanism_pixmap(mechanism["name"], mechanism["frame"],
                                   mechanism["text"], root_text, chars_per_line, font_scale)
        if pixmap is None or pixmap.isNull():
            continue
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        layout.addWidget(label)
        labels.append(label)
    if not labels:
        panel.deleteLater()
        return None, []
    layout.addStretch(1)
    panel.setWidget(content)
    return panel, labels
