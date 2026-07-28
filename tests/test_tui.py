"""TUI 基座（client/tui.py）与状态栏文本（cli.player_segments、net._fmt_timer）测试。

pytest 的 stdin 为管道（非 TTY），tui.prompt 自动回退内置 input——这也是全部
既有测试不受 prompt_toolkit 影响的保证。
"""
import builtins

import pytest

from client import cli, tui
from client.net import _fmt_timer
from client.textutil import display_width


@pytest.fixture(autouse=True)
def _clean_status():
    yield
    tui.set_status(None)  # 状态栏回调是全局量，测试间清理


# ---------- 状态栏渲染（两段） ----------

def test_toolbar_left_right_aligned():
    tui.set_status(lambda: ("左", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar == "左" + " " * 16 + "右"
    assert display_width(bar) == 20


def test_toolbar_cjk_width():
    """CJK 字符按显示宽度 2 计算对齐。"""
    tui.set_status(lambda: ("甲乙丙", "回合"))
    bar = tui.render_toolbar(width=20)
    assert bar == "甲乙丙" + " " * 10 + "回合"
    assert display_width(bar) == 20


def test_toolbar_truncates_left_keeps_right():
    """超宽时截断左段，右段优先完整保留。"""
    tui.set_status(lambda: ("一二三四五六七八九十", "右"))
    bar = tui.render_toolbar(width=10)
    assert bar.endswith("右")
    assert display_width(bar) <= 10
    assert "十" not in bar


def test_toolbar_empty_without_status():
    assert tui.render_toolbar(width=20) == ""


# ---------- 状态栏渲染（三段） ----------

def test_toolbar_three_segments_centered():
    """三段：左左对齐、中居中、右右对齐。"""
    tui.set_status(lambda: ("AA", "MM", "RR"))
    bar = tui.render_toolbar(width=30)
    assert bar == "AA" + " " * 12 + "MM" + " " * 12 + "RR"
    assert display_width(bar) == 30
    assert bar.index("MM") == (30 - 2) // 2  # 中段居中


def test_toolbar_three_segments_cjk_mid():
    tui.set_status(lambda: ("左", "回合", "右"))
    bar = tui.render_toolbar(width=30)
    assert bar.startswith("左") and bar.endswith("右")
    assert display_width(bar) == 30
    assert display_width(bar[:bar.index("回合")]) == (30 - 4) // 2  # CJK 按宽度 2 居中


def test_toolbar_three_segments_truncates_left_keeps_mid_right():
    """超宽时优先保中段与右段、截断左段。"""
    tui.set_status(lambda: ("一二三四五六七八九十", "中", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar.endswith("右") and "中" in bar
    assert display_width(bar) <= 20
    assert "九十" not in bar


def test_toolbar_no_raw_ansi():
    """状态栏纯文本不含未解析的 ANSI 转义（回调返回纯文本时）。"""
    tui.set_status(lambda: ("左", "中", "右"))
    assert "\x1b" not in tui.render_toolbar(width=30)


# ---------- 输入框边框与样式 ----------

def test_frame_message_box():
    """输入框消息：单行 `│ 提示`（上边框不绘，避免滚入历史消息）。"""
    line = tui.frame_message("[玩家A] > ")
    assert line == "│ [玩家A] > "
    assert "\n" not in line and "╭" not in line and "指令" not in line


def test_bottom_border():
    assert tui._bottom_border(20) == "╰" + "─" * 19


def test_session_style_no_reverse():
    """样式覆盖存在：bottom-toolbar 取消默认反色高亮。"""
    rules = dict(tui._session_style().style_rules)
    assert "bottom-toolbar" in rules
    assert "reverse" not in rules["bottom-toolbar"].split()


# ---------- 非 TTY 回退 ----------

def test_prompt_falls_back_to_builtin_input(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "hello")
    assert tui.prompt("> ") == "hello"
    assert tui._session is None  # 非 TTY 不创建 PromptSession（无 import 副作用）


# ---------- 牌手信息段 ----------

def test_player_segments(make_game):
    game = make_game()
    p0, p1 = game.state.players
    own, opp = cli.player_segments(game)  # 热坐：己方 = 当前行动方（players[0] 先手）
    assert own.startswith(f"> {p0.name} 生命{p0.health}")   # `>` 标行动方
    assert opp.startswith(f"  {p1.name} 生命{p1.health}")
    assert f"手牌{len(p0.hand)} 牌库{len(p0.deck)} 墓地{len(p0.graveyard)}" in own
    assert "（你）" not in own + opp
    own_v, opp_v = cli.player_segments(game, viewer=1)  # 联机：己方 = viewer
    assert f"{p1.name}（你）" in own_v and "（你）" not in opp_v


def test_battle_status_three_segments(make_game):
    """热坐状态栏：三段（己方 / 回合 / 敌方），中段为回合文本。"""
    game = make_game()
    left, mid, right = cli._battle_status(game)
    assert left.startswith(">")
    assert "回合" in mid and "行动中" in mid
    assert right.startswith("  ")


# ---------- 倒计时格式化 ----------

def test_fmt_timer():
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 95}, 100.0) == "⏱ 1:35"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 9}, 100.0) == "⏱ 0:09"
    assert _fmt_timer({"kind": "mulligan", "deadline": 100.0 + 27}, 100.0) == "调度 ⏱ 0:27"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0}, 130.0) == "⏱ 0:00"  # 超时封顶
