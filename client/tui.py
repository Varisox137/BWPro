"""TUI 基座：底部输入框 + 常驻状态栏（prompt_toolkit），非 TTY 回退内置 input。

- 仅 stdin/stdout 均为 TTY 时启用 prompt_toolkit（懒创建，import 本模块无副作用）；
  管道输入（测试/脚本）自动回退内置 input()，EOFError 语义与现状一致。
- 输入框下方常驻一行状态栏：set_status(fn) 注册回调，返回 (左文本, 右文本)；
  左文本左对齐、右文本右对齐，按显示宽度（CJK 计 2）对齐。
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
_status_fn = None          # 状态栏回调：() -> (左文本, 右文本)
_ticker: threading.Thread | None = None
_ticker_stop = threading.Event()


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _get_session():
    global _session
    if _session is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        _session = PromptSession(history=InMemoryHistory(),
                                 bottom_toolbar=_toolbar_text)
    return _session


def prompt(text: str = "") -> str:
    """统一输入入口：TTY 走 PromptSession（输入框 + 状态栏 + ↑↓ 历史），
    非 TTY 回退内置 input。"""
    if _tty():
        return _get_session().prompt(text)
    return input(text)


@contextmanager
def activate():
    """主循环上下文：TTY 时 patch_stdout（print 在输入框上方滚动不花屏）。"""
    if _tty():
        from prompt_toolkit.patch_stdout import patch_stdout
        with patch_stdout():
            yield
    else:
        yield


# ---------- 状态栏 ----------

def set_status(fn) -> None:
    """注册状态栏回调（() -> (左文本, 右文本)）；None 清除。"""
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
    """状态栏纯文本：左段左对齐 + 右段右对齐（超宽时截断左段，右段优先保留）。"""
    if _status_fn is None:
        return ""
    left, right = _status_fn()
    if width is None:
        width = shutil.get_terminal_size().columns
    gap = width - display_width(left) - display_width(right)
    if gap < 1:
        left = truncate(left, max(0, width - display_width(right) - 1))
        gap = width - display_width(left) - display_width(right)
    return left + " " * max(gap, 0) + right


def _toolbar_text():
    """bottom_toolbar 回调（ANSI 包装使 textutil 上色在状态栏可用）。"""
    from prompt_toolkit.formatted_text import ANSI
    return ANSI(render_toolbar())


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
