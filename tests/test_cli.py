"""CLI 场况渲染测试：座次配色、修饰状态显示、关键字中文化、手牌修饰显示。

直接调用 client.cli.render(game)；颜色开关经 monkeypatch 设置 cli._USE_COLOR。
角色位约定同 factories.base_db：0-3 号位 = 100101-100104（显示名 式神1001xx）。
"""
import re

import pytest

from client import cli
from tests.factories import give

ANSI = re.compile(r"\033\[\d+m")


@pytest.fixture
def color_on(monkeypatch):
    monkeypatch.setattr(cli, "_USE_COLOR", True)
    return True


@pytest.fixture
def color_off(monkeypatch):
    monkeypatch.setattr(cli, "_USE_COLOR", False)
    return True


# ---------- 座次配色 ----------

def test_seat_colors_active_player_only(db, make_game, color_on):
    """己方场上式神名按座次 1-4 着亮黄/青/紫/红；敌方行不着色。"""
    g = make_game()
    out = cli.render(g)
    for i, code in enumerate(cli.SEAT_COLORS):
        lines = [l for l in out.splitlines() if f"式神{100101 + i}" in l]
        assert len(lines) == 2                       # 双方各一行（同 db）
        colored = [l for l in lines if "\033[" in l]
        assert len(colored) == 1                     # 仅己方（active=0）行着色
        assert f"\033[{code}m" in colored[0]


def test_hand_card_colored_by_owner_seat(db, make_game, color_on):
    """己方手牌卡牌名按所属式神座次着色。"""
    g = make_game()
    for cid, code in zip((10010101, 10010201, 10010301, 10010401), cli.SEAT_COLORS):
        give(g, 0, cid)
        out = cli.render(g)
        assert f"\033[{code}m【卡{cid}】" in out


def test_color_off_when_disabled(db, make_game, color_off):
    """关闭颜色（管道/NO_COLOR）时输出不含任何 ANSI 序列。"""
    g = make_game()
    give(g, 0, 10010101)
    out = cli.render(g)
    assert "\033[" not in out


def test_color_does_not_break_alignment(db, make_game, monkeypatch):
    """颜色不影响排版：开色输出剥离 ANSI 后与关色输出逐行相等。"""
    g = make_game()
    give(g, 0, 10010201)
    monkeypatch.setattr(cli, "_USE_COLOR", True)
    colored = cli.render(g)
    monkeypatch.setattr(cli, "_USE_COLOR", False)
    plain = cli.render(g)
    assert ANSI.sub("", colored) == plain


# ---------- 修饰状态显示 ----------

def test_modifier_status_display(db, make_game, color_off):
    """倒计时/战力/保甲/延迟能力/鼓舞均在场况中显示。"""
    g = make_game()
    p = g.state.players[0]
    s = p.shikigami[1]
    s.level = 1
    s.countdown = 2
    s.combat_power = 3
    s.keep_shield = True
    s.delayed.append({"block": None, "chosen": None, "uses": 1})
    p.assault_boosts.append({"power": 3, "shield": 3})
    out = cli.render(g)
    assert "倒计时2" in out
    assert "战力+3" in out
    assert "保甲" in out
    assert "延迟×1" in out
    assert "鼓舞+3/3" in out


# ---------- 关键字显示 ----------

def test_keyword_labels_translated(db, make_game, color_off):
    """关键字显示中文化（激怒）；引擎级关键字 keep_attack_buffs 不显示。"""
    g = make_game()
    p = g.state.players[0]
    p.shikigami[0].level = 1
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 0, "shikigami": 0}, "keyword": "enraged"}})
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 0, "shikigami": 0}, "keyword": "keep_attack_buffs"}})
    out = cli.render(g)
    assert "[激怒]" in out
    assert "enraged" not in out
    assert "keep_attack_buffs" not in out


# ---------- 手牌修饰显示 ----------

def test_hand_mods_display(db, make_game, color_off):
    """手牌实例修饰：费用修正、增强数值、附加关键字（中文化）。"""
    g = make_game()
    c = give(g, 0, 10010101)          # 空白法术：费用 1、无关键字
    c.mods["cost_delta"] = -1
    c.mods["enhance"] = 2
    c.mods["keywords_add"] = ["fast"]
    out = cli.render(g)
    line = next(l for l in out.splitlines() if f"#{c.uid}" in l)
    assert "费用0" in line
    assert "增强+2" in line
    assert "[瞬发]" in line
