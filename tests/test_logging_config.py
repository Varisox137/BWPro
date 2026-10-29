"""应用日志文件、输出捕获与启动清理。"""
import logging
import os
import re
import time
from pathlib import Path

from core.logging_config import configure_logging, restore_output


def test_log_file_debug_output_and_cleanup(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    old = log_dir / "bwpro_20000101_000000_old.log"
    old.write_text("旧日志", encoding="utf-8")
    cutoff = time.time() - 15 * 86400
    os.utime(old, (cutoff, cutoff))
    for index in range(35):
        path = log_dir / f"bwpro_20260101_0000{index:02d}_test.log"
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (time.time() - index, time.time() - index))
    unrelated = log_dir / "library.log"
    unrelated.write_text("不得删除", encoding="utf-8")
    try:
        path = configure_logging("test", log_dir=log_dir)
        assert re.fullmatch(r"bwpro-\d{8}-\d{6}-\d+\.log", path.name)
        assert not old.exists()
        assert unrelated.read_text(encoding="utf-8") == "不得删除"
        assert len(list(log_dir.glob("bwpro_*.log"))) <= 30
        logging.getLogger("test.debug").debug("调试内容")
        logging.getLogger("PIL.PngImagePlugin").debug("STREAM 调试噪声")
        for handler in logging.getLogger().handlers:
            handler.flush()
        contents = path.read_text(encoding="utf-8")
        assert "DEBUG" in contents
        assert "调试内容" in contents
        assert "STREAM 调试噪声" not in contents
        print("控制台同步输出")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "控制台同步输出" in path.read_text(encoding="utf-8")
    finally:
        restore_output()


def test_default_log_dir_is_project_logs(tmp_path, monkeypatch):
    from core import logging_config

    fake_module = tmp_path / "project" / "core" / "logging_config.py"
    monkeypatch.setattr(logging_config, "__file__", str(fake_module))
    try:
        path = logging_config.configure_logging("default")
        assert path.parent == tmp_path / "project" / "logs"
        assert path.is_file()
    finally:
        logging_config.restore_output()
