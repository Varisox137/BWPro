"""TUI 基座（client/tui.py）与状态栏文本（cli.player_status_segment、net._fmt_timer）测试。

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


# ---------- 状态栏渲染 ----------

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


# ---------- 非 TTY 回退 ----------

def test_prompt_falls_back_to_builtin_input(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "hello")
    assert tui.prompt("> ") == "hello"
    assert tui._session is None  # 非 TTY 不创建 PromptSession（无 import 副作用）


# ---------- 牌手信息段 ----------

def test_player_status_segment(make_game):
    game = make_game()
    seg = cli.player_status_segment(game)
    p0, p1 = game.state.players
    assert seg.startswith(f"> {p0.name} 生命{p0.health}")  # `>` 标行动方（players[0] 先手）
    assert f"  {p1.name} 生命{p1.health}" in seg            # 非行动方前缀空格
    assert f"手牌{len(p0.hand)} 牌库{len(p0.deck)} 墓地{len(p0.graveyard)}" in seg
    assert "（你）" not in seg
    seg_v = cli.player_status_segment(game, viewer=1)
    assert f"{p1.name}（你）" in seg_v and f"{p0.name}（你）" not in seg_v


# ---------- 倒计时格式化 ----------

def test_fmt_timer():
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 95}, 100.0) == "⏱ 1:35"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 9}, 100.0) == "⏱ 0:09"
    assert _fmt_timer({"kind": "mulligan", "deadline": 100.0 + 27}, 100.0) == "调度 ⏱ 0:27"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0}, 130.0) == "⏱ 0:00"  # 超时封顶
