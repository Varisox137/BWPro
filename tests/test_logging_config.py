"""应用日志文件、输出捕获与启动清理。"""
import logging
import os
import re
import sys
import time
from pathlib import Path

from core.logging_config import configure_logging, restore_output, write_terminal_secret


def test_terminal_secret_writes_to_terminal_not_standard_output(monkeypatch, capsys):
    writes = []

    class Terminal:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def write(self, text):
            writes.append(text)

        def flush(self):
            pass

    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: Terminal())
    assert write_terminal_secret("秘密") is True
    assert writes == ["秘密\n"]
    captured = capsys.readouterr()
    assert "秘密" not in captured.out
    assert "秘密" not in captured.err


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
        assert len(list(log_dir.glob("bwpro_*.log"))) <= 10
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


def test_log_cleanup_applies_age_and_count_to_both_file_patterns(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    expired = time.time() - 15 * 86400
    for name in ("bwpro-20000101-000000-1.log", "bwpro_20000101_000000_old.log"):
        path = log_dir / name
        path.write_text("过期", encoding="utf-8")
        os.utime(path, (expired, expired))
    for index in range(35):
        name = (f"bwpro-20260101-0000{index:02d}-{index}.log" if index % 2
                else f"bwpro_20260101_0000{index:02d}_test.log")
        path = log_dir / name
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (time.time() - index, time.time() - index))
    try:
        current = configure_logging("test", log_dir=log_dir)
        survivors = list(log_dir.glob("bwpro-*.log")) + list(log_dir.glob("bwpro_*.log"))
        assert len(survivors) <= 10
        assert current in survivors
        assert all("20000101" not in path.name for path in survivors)
        assert not (log_dir / "bwpro_20260101_000034_test.log").exists()
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


def test_frozen_default_log_dir_uses_user_home(tmp_path, monkeypatch):
    from core import logging_config

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    try:
        path = logging_config.configure_logging("frozen")
        assert path.parent == tmp_path / "home" / ".bwpro" / "logs"
        assert path.is_file()
    finally:
        logging_config.restore_output()


def test_windowed_output_capture_allows_none_streams(monkeypatch):
    from core import logging_config

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    logging_config.capture_output()
    try:
        assert sys.stdout.write("窗口输出") == 4
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        logging_config.restore_output()


def test_posix_log_directory_and_all_surviving_logs_are_private(tmp_path):
    if os.name == "nt":
        import pytest
        pytest.skip("POSIX 权限位仅在 POSIX 检查")
    import stat

    log_dir = tmp_path / "logs"
    log_dir.mkdir(mode=0o755)
    surviving = log_dir / "bwpro-existing.log"
    surviving.write_text("保留", encoding="utf-8")
    surviving.chmod(0o644)
    try:
        current = configure_logging("private", log_dir=log_dir)
        assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(current.stat().st_mode) == 0o600
        assert stat.S_IMODE(surviving.stat().st_mode) == 0o600
    finally:
        restore_output()


def test_windows_private_permissions_reset_then_use_current_user_acl(tmp_path, monkeypatch):
    import subprocess
    from core import logging_config

    path = tmp_path / "bwpro-private.log"
    path.write_text("private", encoding="utf-8")
    monkeypatch.setattr(logging_config.os, "name", "nt")
    monkeypatch.setattr(logging_config.getpass, "getuser", lambda: "test-user")
    calls = []

    def record_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(logging_config.subprocess, "run", record_run)
    logging_config.restrict_private_permissions(path)
    assert calls == [(
        ["icacls", os.fspath(path), "/reset", "/inheritance:r", "/grant:r",
         "test-user:(F)"],
        {"check": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE},
    )]


def test_application_permission_failure_warns_and_logging_continues(
        tmp_path, monkeypatch, caplog):
    from core import logging_config

    def fail_permissions(_path, *, directory=False):
        raise OSError("注入权限失败")

    monkeypatch.setattr(logging_config, "restrict_private_permissions", fail_permissions)
    with caplog.at_level(logging.WARNING, logger="core.logging_config"):
        try:
            path = logging_config.configure_logging("permission-failure", log_dir=tmp_path)
            assert path.is_file()
            logging.getLogger("permission.test").warning("日志仍可用")
            for handler in logging.getLogger().handlers:
                handler.flush()
            assert "日志仍可用" in path.read_text(encoding="utf-8")
        finally:
            logging_config.restore_output()
    assert "警告" in caplog.text
    assert "注入权限失败" in caplog.text
    assert str(tmp_path) in caplog.text


def test_update_mode_logs_exception_to_existing_frozen_log_dir(tmp_path, monkeypatch):
    import client.update

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))

    def fail_update(*_args):
        raise OSError("注入更新失败")

    monkeypatch.setattr(client.update, "apply_update", fail_update)
    try:
        assert client.update.apply_update_command(["12", "old", "new", "hash"]) == 1
        for handler in logging.getLogger().handlers:
            handler.flush()
        logs = list((tmp_path / "home" / ".bwpro" / "logs").glob("bwpro-*.log"))
        assert len(logs) == 1
        contents = logs[0].read_text(encoding="utf-8")
        assert "自动更新失败" in contents
        assert "注入更新失败" in contents
    finally:
        restore_output()
