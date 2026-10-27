"""主线程加载提示：按真实耗时更新，并在批量渲染间恢复事件处理。"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class LoadingIndicator(QObject):
    def __init__(self, prefix: str, on_text, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.prefix = prefix
        self.on_text = on_text
        self.clock = clock
        self._started = 0.0
        self._last_tenths = -1
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.tick)

    def start(self, prefix: str | None = None) -> None:
        if prefix is not None:
            self.prefix = prefix
        self._started = self.clock()
        self._last_tenths = -1
        self._running = True
        self.tick()
        self._timer.start()

    def tick(self) -> None:
        if not self._running:
            return
        elapsed = max(0.0, self.clock() - self._started)
        tenths = int(elapsed * 10)
        if tenths == self._last_tenths:
            return
        self._last_tenths = tenths
        self.on_text(f"{self.prefix} {tenths / 10:.1f}s")
        QApplication.processEvents()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
