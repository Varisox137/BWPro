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
        assert re.fullmatch(r"bwpro_\d{8}_\d{6}_test\.log", path.name)
        assert not old.exists()
        assert unrelated.read_text(encoding="utf-8") == "不得删除"
        assert len(list(log_dir.glob("bwpro_*.log"))) <= 30
        logging.getLogger("test.debug").debug("调试内容")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "DEBUG" in path.read_text(encoding="utf-8")
        assert "调试内容" in path.read_text(encoding="utf-8")
        print("控制台同步输出")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "控制台同步输出" in path.read_text(encoding="utf-8")
    finally:
        restore_output()
