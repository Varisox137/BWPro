"""结算明细打印队列：边播边操作。

回合内时间紧张（联机限时）时，玩家应能一边看结算明细逐条播放、一边输入并
提交下一个操作。本模块提供 FIFO 打印队列 + 后台打印者（守护线程）：

- **块为单位**：一次 state 消息（联机）/ 一次 apply 后增量（热坐）构成一块；
  块内顺序保持，块前后各空一行，块与块不穿插（播放中入队的新块等当前块
  播完再播）。空块不入队。
- **节奏**：按 interval（默认 0.4s/条，BWP_SETTLE_INTERVAL 覆盖）消费；
  输入循环与服务端接收线程不被播放阻塞。
- **退出**：stop(flush=True) 把剩余块快速播完（不再 sleep）；flush=False
  丢弃剩余并提示行数。join 等待线程退出，不留泄漏；守护线程兜底。
- 打印者独占 settle/叙事 log 的输出顺序；场况 render、状态栏、错误/通知
  仍走即时打印（不入队）。
"""
from __future__ import annotations

import queue
import threading


class SettlePrinter:
    """FIFO 结算打印队列 + 后台打印者（守护线程，可重复 start/stop）。"""

    def __init__(self, interval: float = 0.4) -> None:
        self.interval = interval
        self._q: queue.Queue[list[str] | None] = queue.Queue()
        self._fast = threading.Event()  # 置位后不再逐条 sleep（flush/停止用）
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动打印者（幂等；stop 后可再次 start）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._fast.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, lines: list[str]) -> None:
        """追加一块（空块不入队）。线程安全（接收线程/主线程均可调用）。"""
        if lines:
            self._q.put(list(lines))

    def _run(self) -> None:
        while True:
            block = self._q.get()
            if block is None:  # 停止信号
                return
            try:
                print("")
                for line in block:
                    print(line)
                    if self.interval > 0:
                        self._fast.wait(self.interval)  # flush/stop 置位时立即返回
                print("")
            finally:
                self._q.task_done()  # wait_idle 的完成计数

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """等待已入队的块按正常节奏全部播完（对局结束等场景：先播完剩余结算，
        再打印结果）。返回是否排空（False = 超时，调用方可走 flush 兜底）。"""
        import time
        deadline = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        return not self._q.unfinished_tasks

    def stop(self, flush: bool = True, timeout: float = 5.0) -> None:
        """停止打印者：flush=True 把队列剩余块快速播完（不 sleep）；
        flush=False 丢弃剩余块并提示略过行数。幂等，join 等待线程退出。"""
        if self._thread is None:
            return
        if not flush:
            dropped = 0
            try:
                while True:
                    block = self._q.get_nowait()
                    if block is not None:
                        dropped += len(block)
            except queue.Empty:
                pass
            if dropped:
                print(f"（{dropped} 行结算明细已略过）")
        self._fast.set()
        self._q.put(None)
        self._thread.join(timeout)
        self._thread = None
