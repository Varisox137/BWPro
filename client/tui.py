"""TUI 基座：底部输入框 + 常驻状态栏（prompt_toolkit），非 TTY 回退内置 input。

- 仅 stdin/stdout 均为 TTY 时启用 prompt_toolkit（懒创建，import 本模块无副作用）；
  管道输入（测试/脚本）自动回退内置 input()，EOFError 语义与现状一致。
- 输入框带 box-drawing 边框（上边框在 message、下边框在状态栏首行）；框下常驻
  状态栏：set_status(fn) 注册回调，返回 (左, 右) 或 (左, 中, 右) 文本；
  按显示宽度（CJK 计 2）对齐，超宽时优先保中/右段、截断左段。
- activate() 的 patch_stdout 用 raw=True：print 的 ANSI 颜色序列透传
  （默认 raw=False 会剥除转义字符，导致颜色码以字面 [33m 暴露）。
- start_ticker/stop_ticker：守护线程定期 invalidate，驱动状态栏倒计时逐秒重绘。
- 本模块不含任何游戏场景逻辑（场景见 cli.py / net.py）。
"""
from __future__ import annotations

import shutil
import sys
import threading
from contextlib import contextmanager

from client.textutil import display_width

_session = None            # 懒创建的全局 PromptSession
_status_fn = None          # 状态栏回调：() -> (左, 右) 或 (左, 中, 右)
_ticker: threading.Thread | None = None
_ticker_stop = threading.Event()


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _session_style():
    """状态栏样式覆盖：取消 bottom-toolbar 默认的反色高亮（普通文本样式）。"""
    from prompt_toolkit.styles import Style
    return Style.from_dict({"bottom-toolbar": "noreverse",
                            "bottom-toolbar.text": ""})


def _get_session():
    global _session
    if _session is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        _session = PromptSession(history=InMemoryHistory(),
                                 bottom_toolbar=_toolbar_text,
                                 style=_session_style())
    return _session


def prompt(text: str = "") -> str:
    """统一输入入口：TTY 走 PromptSession（纯文本输入行 + 状态栏 + ↑↓ 历史），
    非 TTY 回退内置 input。"""
    if _tty():
        return _get_session().prompt(text)
    return input(text)


@contextmanager
def activate():
    """主循环上下文：TTY 时 patch_stdout（print 在输入框上方滚动不花屏）。
    raw=True：print 的 ANSI 颜色序列透传，否则转义字符被剥除、颜色码字面暴露。"""
    if _tty():
        from prompt_toolkit.patch_stdout import patch_stdout
        with patch_stdout(raw=True):
            yield
    else:
        yield


# ---------- 输入区与状态栏分隔线 ----------

def _separator(width: int) -> str:
    """pi-tui 风格纯横线。prompt_toolkit 非全屏模式下提交后 prompt 渲染行必然滚入
    历史消息，任何 prompt 侧边框都会残留成难看的竖线/角字符——故输入行保持纯文本，
    输入区与状态栏的分隔感由状态栏首行这条常驻横线提供。"""
    return "─" * max(0, width)


# ---------- 状态栏 ----------

def set_status(fn) -> None:
    """注册状态栏回调（() -> (左, 右) 或 (左, 中, 右)）；None 清除。"""
    global _status_fn
    _status_fn = fn


def truncate(s: str, width: int) -> str:
    """按显示宽度截断（CJK 计 2，不在宽字符中间切断）。"""
    out = []
    w = 0
    for ch in s:
        cw = 2 if display_width(ch) == 2 else 1
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def render_toolbar(width: int | None = None) -> str:
    """状态栏纯文本：两段（左+右）或三段（左+中居中+右）。
    超宽时优先保中段与右段、截断左段。"""
    if _status_fn is None:
        return ""
    segs = _status_fn()
    if width is None:
        width = shutil.get_terminal_size().columns
    if len(segs) == 2:
        left, right = segs
        gap = width - display_width(left) - display_width(right)
        if gap < 1:
            left = truncate(left, max(0, width - display_width(right) - 1))
            gap = width - display_width(left) - display_width(right)
        return left + " " * max(gap, 0) + right
    left, mid, right = segs
    mw, rw = display_width(mid), display_width(right)
    if mw + rw > width - 1:  # 中+右已超宽：截中段兜底
        mid = truncate(mid, max(0, width - rw - 1))
        mw = display_width(mid)
    if display_width(left) + mw + rw > width - 2:
        left = truncate(left, max(0, width - mw - rw - 2))
    lw = display_width(left)
    mid_start = max(lw + 1, (width - mw) // 2)
    right_start = width - rw
    if mid_start + mw > right_start - 1:  # 中段与右段重叠：中段左移
        mid_start = max(lw + 1, right_start - 1 - mw)
    return (left + " " * (mid_start - lw) + mid
            + " " * (right_start - mid_start - mw) + right)


def _toolbar_text():
    """bottom_toolbar 回调：首行分隔横线（pi-tui 风格）、次行状态栏。
    ANSI 包装解析 textutil 颜色码（回调返回纯文本时为普通文本）。"""
    from prompt_toolkit.formatted_text import ANSI
    width = shutil.get_terminal_size().columns
    return ANSI(_separator(width) + "\n" + render_toolbar(width))


def start_ticker(interval: float = 1.0) -> None:
    """守护线程定期 invalidate 驱动状态栏重绘（仅 TTY 且 session 存在时生效）。"""
    global _ticker
    stop_ticker()
    if not _tty():
        return
    _ticker_stop.clear()

    def _run() -> None:
        while not _ticker_stop.wait(interval):
            app = _session.app if _session is not None else None
            if app is not None and app.is_running:
                app.invalidate()

    _ticker = threading.Thread(target=_run, daemon=True)
    _ticker.start()


def stop_ticker() -> None:
    global _ticker
    _ticker_stop.set()
    _ticker = None
