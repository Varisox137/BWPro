"""统一应用日志：DEBUG 文件、控制台 tee、异常记录与启动清理。"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

_LOG_PATTERN = "bwpro_*.log"
_MAX_LOG_AGE_SECONDS = 14 * 86400
_MAX_LOG_FILES = 30
_original_stdout = None
_original_stderr = None


class _Tee:
    """原样转发终端输出，同时按行写入 DEBUG 日志。"""

    def __init__(self, stream, level: int):
        self.stream = stream
        self.level = level
        self.buffer = ""
        self.logger = logging.getLogger("bwpro.output")

    def write(self, text):
        self.stream.write(text)
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.logger.log(self.level, line)
        return len(text)

    def flush(self):
        self.stream.flush()
        if self.buffer:
            self.logger.log(self.level, self.buffer)
            self.buffer = ""


def capture_output() -> None:
    """保留终端行为并捕获 print/标准错误；重复调用不会嵌套 tee。"""
    global _original_stdout, _original_stderr
    if _original_stdout is None:
        _original_stdout = sys.stdout
        sys.stdout = _Tee(_original_stdout, logging.DEBUG)
    if _original_stderr is None:
        _original_stderr = sys.stderr
        sys.stderr = _Tee(_original_stderr, logging.WARNING)


def restore_output() -> None:
    """恢复标准流，主要用于测试和嵌入调用方。"""
    global _original_stdout, _original_stderr
    if _original_stdout is not None:
        sys.stdout.flush()
        sys.stdout = _original_stdout
        _original_stdout = None
    if _original_stderr is not None:
        sys.stderr.flush()
        sys.stderr = _original_stderr
        _original_stderr = None


def _cleanup_logs(log_dir: Path) -> None:
    now = datetime.now().timestamp()
    candidates = []
    for path in log_dir.glob(_LOG_PATTERN):
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > _MAX_LOG_AGE_SECONDS:
            try:
                path.unlink()
            except OSError:
                logging.getLogger(__name__).warning("无法清理旧日志：%s", path)
        else:
            candidates.append((stat.st_mtime, path))
    for _mtime, path in sorted(candidates, reverse=True)[_MAX_LOG_FILES - 1:]:
        try:
            path.unlink()
        except OSError:
            logging.getLogger(__name__).warning("无法清理超额日志：%s", path)


def _exception_logger(logger: logging.Logger):
    def handle(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("未处理异常", exc_info=(exc_type, exc_value, exc_traceback))

    return handle


def _thread_exception_logger(logger: logging.Logger):
    def handle(args):
        logger.critical("线程未处理异常：%s", args.thread,
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    return handle


def configure_logging(component: str, log_dir: Path | None = None) -> Path:
    """初始化进程日志并返回文件路径；重复调用会轮换而非叠加 handler。"""
    log_dir = log_dir or Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_logs(log_dir)
    safe_component = "".join(char if char.isalnum() or char in "-_" else "_"
                             for char in component) or "app"
    path = log_dir / f"bwpro_{datetime.now():%Y%m%d_%H%M%S}_{safe_component}.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        if getattr(handler, "_bwpro_handler", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler._bwpro_handler = True
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    logger = logging.getLogger("bwpro")
    sys.excepthook = _exception_logger(logger)
    threading.excepthook = _thread_exception_logger(logger)
    capture_output()
    logger.info("日志启动：%s", path)
    return path
