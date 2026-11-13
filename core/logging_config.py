"""统一应用日志：DEBUG 文件、控制台 tee、异常记录与启动清理。"""
from __future__ import annotations

import fnmatch
import getpass
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

LOG_PATTERNS = ("bwpro-*.log", "bwpro_*.log")
_MAX_LOG_AGE_SECONDS = 15 * 86400
_MAX_LOG_FILES = 10
_original_stdout = None
_original_stderr = None


def is_log_filename(name: str) -> bool:
    if not isinstance(name, str) or Path(name).name != name:
        return False
    if name.endswith((" ", ".")) or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 or char in '<>:"/\\|?*'
            for char in name):
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in LOG_PATTERNS)


def restrict_private_permissions(path: Path, *, directory: bool = False) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    permission = "(OI)(CI)(F)" if directory else "(F)"
    # 目录上 /reset 与后续选项同次调用会被 icacls 拒绝，分开执行。
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(["icacls", os.fspath(path), "/reset"], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   creationflags=creationflags)
    subprocess.run(
        ["icacls", os.fspath(path), "/inheritance:r", "/grant:r",
         f"{getpass.getuser()}:{permission}"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def restrict_private_permissions_best_effort(path: Path, *, directory: bool = False) -> None:
    try:
        restrict_private_permissions(path, directory=directory)
    except Exception as error:
        logging.getLogger(__name__).warning(
            "警告：无法收紧日志私有权限：%s：%s", path, error)


class _Tee:
    """原样转发终端输出，同时按行写入 DEBUG 日志。"""

    def __init__(self, stream, level: int):
        self.stream = stream
        self.level = level
        self.buffer = ""
        self.logger = logging.getLogger("bwpro.output")

    def write(self, text):
        if self.stream is not None:  # PyInstaller windowed：无控制台流
            self.stream.write(text)
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.logger.log(self.level, line)
        return len(text)

    def flush(self):
        if self.stream is not None:
            self.stream.flush()
        if self.buffer:
            self.logger.log(self.level, self.buffer)
            self.buffer = ""


def write_terminal_secret(text: str) -> bool:
    """绕过标准输出捕获，仅向交互终端写秘密。"""
    target = "CON" if os.name == "nt" else "/dev/tty"
    try:
        with open(target, "w", encoding="utf-8") as terminal:
            terminal.write(text + "\n")
            terminal.flush()
        return True
    except OSError:
        return False


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
    """保留 15 天内的应用与 launcher 日志各 10 份（为新应用日志预留 1 份）。"""
    now = datetime.now().timestamp()
    candidates = {"application": [], "launcher": []}
    for pattern in LOG_PATTERNS:
        for path in log_dir.glob(pattern):
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
                category = "launcher" if path.name.startswith("bwpro-launcher-") else "application"
                candidates[category].append((stat.st_mtime, path))
    for category, entries in candidates.items():
        limit = _MAX_LOG_FILES - (1 if category == "application" else 0)
        survivors = sorted(entries, reverse=True)[:limit]
        for _mtime, path in sorted(entries, reverse=True)[limit:]:
            try:
                path.unlink()
            except OSError:
                logging.getLogger(__name__).warning("无法清理超额日志：%s", path)
        for _mtime, path in survivors:
            if path.exists():
                restrict_private_permissions_best_effort(path)


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
    if log_dir is None:
        log_dir = (Path.home() / ".bwpro" / "logs" if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parents[1] / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    restrict_private_permissions_best_effort(log_dir, directory=True)
    _cleanup_logs(log_dir)
    path = log_dir / f"bwpro-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # 原始 WS 帧含重连凭证与私密手牌，不写入 DEBUG 日志。
    logging.getLogger("websockets").setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, "_bwpro_handler", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    restrict_private_permissions_best_effort(path)
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
