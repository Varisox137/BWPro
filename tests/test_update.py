"""自动更新的版本、传输、校验、进程等待与替换契约。"""
from __future__ import annotations

import hashlib
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from client.update import (
    MAX_DOWNLOAD_BYTES,
    AvailableUpdate,
    UpdateCancelled,
    UpdateError,
    apply_update,
    check_for_update,
    download_update,
    launch_update,
    verify_sha256,
    verify_update,
    wait_for_process,
)
from core.version import VERSION, parse_version


class FakeResponse(io.BytesIO):
    def __init__(self, chunks=(), *, content_length=None):
        super().__init__(b"".join(chunks))
        self.chunks = list(chunks)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size=-1):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def release_payload(tag="v0.3.2", *, exe_url=None, sha_url=None, names=None):
    exe_name, sha_name = names or (f"BWPro-{tag}.exe", f"BWPro-{tag}.exe.sha256")
    return {
        "tag_name": tag,
        "assets": [
            {"name": exe_name, "browser_download_url": exe_url or "https://cdn.example/app.exe"},
            {"name": sha_name, "browser_download_url": sha_url or "https://cdn.example/app.sha256"},
        ],
    }


def opening(payload=None, *, error=None):
    def open(request, timeout):
        assert isinstance(request, urllib.request.Request)
        assert timeout > 0
        assert request.get_header("Authorization") is None
        if error is not None:
            raise error
        return FakeResponse([json.dumps(payload).encode("utf-8")])
    return open


def available_update():
    return AvailableUpdate(
        tag="v0.3.2",
        exe_name="BWPro-v0.3.2.exe",
        exe_url="https://cdn.example/app.exe",
        sha256_name="BWPro-v0.3.2.exe.sha256",
        sha256_url="https://cdn.example/app.sha256",
    )


def test_version_is_strict_numeric_and_matches_project_metadata():
    assert VERSION == "0.3.1"
    assert parse_version("v0.10.0") > parse_version("v0.9.9")
    assert verify_update(VERSION, "v0.3.2") == "v0.3.2"
    for invalid in ("0.3.1", "v1.2", "v1.2.3.4", "v01.2.3", "v1.2.3-beta"):
        with pytest.raises(ValueError):
            parse_version(invalid)
    for not_newer in ("v0.3.1", "v0.3.0"):
        with pytest.raises(ValueError):
            verify_update(VERSION, not_newer)
    import tomllib
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert VERSION == project["project"]["version"]


def test_release_check_handles_missing_rate_limited_and_older_releases():
    for status in (404, 429):
        request = urllib.request.Request("https://api.github.com/repos/Varisox137/BWPro/releases/latest")
        error = urllib.error.HTTPError(request.full_url, status, "blocked", None, None)
        with pytest.raises(UpdateError) as caught:
            check_for_update(opener=opening(error=error))
        assert caught.value.status == status

    seen = []

    def open_older(request, timeout):
        seen.append(request.full_url)
        return FakeResponse([json.dumps(release_payload("v0.3.0")).encode()])

    assert check_for_update(opener=open_older) is None
    assert seen == ["https://api.github.com/repos/Varisox137/BWPro/releases/latest"]


def test_release_assets_must_exactly_match_the_strict_tag():
    found = check_for_update("0.3.0", opener=opening(release_payload()))
    assert found == available_update()

    bad_payloads = (
        release_payload(names=("BWPro-v0.3.1.exe.extra", "BWPro-v0.3.1.exe.sha256")),
        release_payload(names=("BWPro-v0.3.0.exe", "BWPro-v0.3.1.exe.sha256")),
        release_payload(exe_url="http://cdn.example/app.exe"),
    )
    for payload in bad_payloads:
        with pytest.raises(UpdateError):
            check_for_update(opener=opening(payload))


def test_https_redirects_stay_https_without_downgrade():
    from client.update import SafeHTTPSRedirectHandler

    handler = SafeHTTPSRedirectHandler()
    request = urllib.request.Request("https://github.com/start")
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://objects.githubusercontent.com/app.exe")
    assert redirected.full_url == "https://objects.githubusercontent.com/app.exe"
    with pytest.raises(UpdateError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://github.com/app.exe")


def test_download_streams_both_assets_and_stages_verified_exe(tmp_path):
    payload = b"new executable"
    digest = hashlib.sha256(payload).hexdigest()
    checksum = f"{digest}  BWPro-v0.3.2.exe\n".encode()
    responses = {
        "https://cdn.example/app.sha256": FakeResponse([checksum[:20], checksum[20:]]),
        "https://cdn.example/app.exe": FakeResponse([payload[:3], payload[3:]]),
    }
    staged = tmp_path / "BWPro-v0.3.0.exe.new"

    download_update(available_update(), staged, opener=lambda request, timeout: responses[request.full_url])

    assert staged.read_bytes() == payload
    assert not (tmp_path / (staged.name + ".part")).exists()
    assert not (tmp_path / (staged.name + ".sha256")).exists()
    assert not (tmp_path / (staged.name + ".sha256.part")).exists()
    verify_sha256(staged, digest)


def test_bad_hash_and_interrupted_download_remove_partial_files(tmp_path):
    payload = b"not the expected executable"
    checksum = f"{'0' * 64}  BWPro-v0.3.2.exe\n".encode()

    class Interrupted(FakeResponse):
        def read(self, size=-1):
            if self.chunks:
                return super().read(size)
            raise OSError("连接中断")

    for exe_response in (FakeResponse([payload]), Interrupted([payload])):
        staged = tmp_path / "BWPro-v0.3.0.exe.new"
        responses = {
            "https://cdn.example/app.sha256": FakeResponse([checksum]),
            "https://cdn.example/app.exe": exe_response,
        }
        with pytest.raises((UpdateError, OSError)):
            download_update(
                available_update(), staged,
                opener=lambda request, timeout: responses[request.full_url])
        assert not staged.exists()
        assert not (tmp_path / (staged.name + ".part")).exists()
        assert not (tmp_path / (staged.name + ".sha256")).exists()


def test_cancel_and_actual_byte_limit_clean_partial_download(tmp_path, monkeypatch):
    cancelled = threading.Event()

    class CancelAfterFirstChunk(FakeResponse):
        def read(self, size=-1):
            chunk = super().read(size)
            cancelled.set()
            return chunk

    staged = tmp_path / "BWPro-v0.3.0.exe.new"
    responses = {
        "https://cdn.example/app.sha256": FakeResponse([
            f"{hashlib.sha256(b'abc').hexdigest()}  BWPro-v0.3.2.exe\n".encode()]),
        "https://cdn.example/app.exe": CancelAfterFirstChunk([b"abc"]),
    }
    with pytest.raises(UpdateCancelled):
        download_update(
            available_update(), staged, cancel_event=cancelled,
            opener=lambda request, timeout: responses[request.full_url])
    assert not (tmp_path / (staged.name + ".part")).exists()
    assert not staged.exists()

    monkeypatch.setattr("client.update.MAX_DOWNLOAD_BYTES", 16)
    staged = tmp_path / "too-large.new"
    responses = {
        "https://cdn.example/app.sha256": FakeResponse([
            f"{hashlib.sha256(b'x' * 17).hexdigest()}  BWPro-v0.3.2.exe\n".encode()]),
        "https://cdn.example/app.exe": FakeResponse([b"x" * 17], content_length=1),
    }
    with pytest.raises(UpdateError, match="大小上限"):
        download_update(
            available_update(), staged,
            opener=lambda request, timeout: responses[request.full_url])
    assert MAX_DOWNLOAD_BYTES == 2 * 1024**3 - 1
    assert not (tmp_path / "too-large.new.part").exists()


def test_non_frozen_launch_never_replaces_python_executable(tmp_path):
    staged = tmp_path / "app.exe.new"
    staged.write_bytes(b"new")
    with pytest.raises(UpdateError, match="冻结"):
        launch_update(staged, hashlib.sha256(b"new").hexdigest(), frozen=False)


def test_frozen_launch_starts_temporary_copy_with_apply_arguments(tmp_path):
    current = tmp_path / "BWPro-v0.3.0.exe"
    staged = tmp_path / "BWPro-v0.3.0.exe.new"
    current.write_bytes(b"old")
    staged.write_bytes(b"new")
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    launch_update(
        staged, hashlib.sha256(b"new").hexdigest(), current_executable=current,
        pid=4321, frozen=True, temp_root=tmp_path, popen=popen)

    command = calls[0][0]
    copied = Path(command[0])
    assert copied != current
    assert copied.read_bytes() == b"old"
    assert command[1:] == [
        "--apply-update", "4321", str(current), str(staged), hashlib.sha256(b"new").hexdigest()]


class FakeCFunction:
    def __init__(self, callback):
        self.callback = callback
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        return self.callback(*args)


def test_windows_process_wait_uses_bounded_synchronization_handle(monkeypatch):
    import client.update as update
    from ctypes import wintypes

    class Kernel32:
        def __init__(self, result):
            self.result = result
            self.closed = []
            self.open_calls = []
            self.OpenProcess = FakeCFunction(self._open_process)
            self.WaitForSingleObject = FakeCFunction(self._wait)
            self.CloseHandle = FakeCFunction(self._close)

        def _open_process(self, access, inherit, pid):
            self.open_calls.append((access, inherit, pid))
            return 99

        def _wait(self, handle, milliseconds):
            assert handle == 99
            assert milliseconds == 2500
            return self.result

        def _close(self, handle):
            self.closed.append(handle)
            return True

    monkeypatch.setattr(update.os, "name", "nt")
    kernel = Kernel32(0)
    dll_calls = []

    def windows_dll(name, use_last_error):
        dll_calls.append((name, use_last_error))
        return kernel

    monkeypatch.setattr(update.ctypes, "WinDLL", windows_dll)
    wait_for_process(1234, timeout=2.5)
    assert dll_calls == [("kernel32", True)]
    assert kernel.open_calls == [(0x00100000, False, 1234)]
    assert kernel.closed == [99]
    assert kernel.OpenProcess.restype == wintypes.HANDLE
    assert kernel.OpenProcess.argtypes == [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    assert kernel.WaitForSingleObject.restype == wintypes.DWORD
    assert kernel.WaitForSingleObject.argtypes == [wintypes.HANDLE, wintypes.DWORD]
    assert kernel.CloseHandle.restype == wintypes.BOOL
    assert kernel.CloseHandle.argtypes == [wintypes.HANDLE]

    kernel.result = 0x102
    with pytest.raises(UpdateError, match="等待"):
        wait_for_process(1234, timeout=2.5)
    assert kernel.closed == [99, 99]


def test_windows_process_wait_accepts_process_that_already_exited(monkeypatch):
    import client.update as update

    class Kernel32:
        OpenProcess = FakeCFunction(lambda *_args: None)

    monkeypatch.setattr(update.os, "name", "nt")
    monkeypatch.setattr(update.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    monkeypatch.setattr(update.ctypes, "get_last_error", lambda: 87)
    wait_for_process(1234, timeout=0)


def test_apply_waits_then_atomically_replaces_and_restarts(tmp_path):
    target = tmp_path / "BWPro.exe"
    staged = tmp_path / "BWPro.exe.new"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    calls = []

    result = apply_update(
        123, target, staged, hashlib.sha256(b"new").hexdigest(),
        wait=lambda pid: calls.append(("wait", pid)),
        restart=lambda path, **_kwargs: calls.append(("restart", path.read_bytes())))

    assert result == 0
    assert calls == [("wait", 123), ("restart", b"new")]
    assert target.read_bytes() == b"new"
    assert not staged.exists()
    assert not (tmp_path / "BWPro.exe.bak").exists()


def test_replace_failure_restores_backup_and_restarts_old_version(tmp_path, monkeypatch):
    import client.update as update

    target = tmp_path / "BWPro.exe"
    staged = tmp_path / "BWPro.exe.new"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    restarted = []
    real_replace = update.os.replace

    def fail_new_executable(source, destination):
        if Path(source) == staged and Path(destination) == target:
            raise OSError("注入替换失败")
        return real_replace(source, destination)

    monkeypatch.setattr(update.os, "replace", fail_new_executable)
    with pytest.raises(UpdateError, match="回滚"):
        apply_update(
            123, target, staged, hashlib.sha256(b"new").hexdigest(),
            wait=lambda _pid: None, restart=lambda path, **_kwargs: restarted.append(path.read_bytes()))

    assert target.read_bytes() == b"old"
    assert restarted == [b"old"]
    assert not (tmp_path / "BWPro.exe.bak").exists()


def test_wait_failure_preserves_files_and_never_restarts(tmp_path):
    target = tmp_path / "BWPro.exe"
    staged = tmp_path / "BWPro.exe.new"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    restarted = []

    def fail_wait(_pid):
        raise UpdateError("等待原程序退出超时")

    with pytest.raises(UpdateError, match="等待"):
        apply_update(
            123, target, staged, hashlib.sha256(b"new").hexdigest(),
            wait=fail_wait, restart=lambda path, **_kwargs: restarted.append(path))

    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"
    assert restarted == []
    assert not (tmp_path / "BWPro.exe.bak").exists()


def test_logging_initialization_failure_does_not_start_update(monkeypatch):
    import client.update as update
    import core.logging_config

    calls = []
    monkeypatch.setattr(
        core.logging_config, "configure_logging",
        lambda _component: (_ for _ in ()).throw(OSError("日志目录不可写")))
    monkeypatch.setattr(update, "apply_update", lambda *args: calls.append(args))

    assert update.apply_update_command(["12", "old", "new", "hash"]) == 1
    assert calls == []


def test_checksum_asset_has_small_limit_and_strict_format(tmp_path):
    from client.update import MAX_SHA256_BYTES

    assert MAX_SHA256_BYTES == 4096
    for contents, message in ((b"x" * 4097, "大小上限"), (b"not-a-checksum", "格式")):
        staged = tmp_path / "BWPro.exe.new"
        responses = {"https://cdn.example/app.sha256": FakeResponse([contents])}

        def open_asset(request, timeout):
            assert request.full_url in responses
            return responses[request.full_url]

        with pytest.raises(UpdateError, match=message):
            download_update(available_update(), staged, opener=open_asset)
        assert not staged.exists()
        assert not (tmp_path / "BWPro.exe.new.part").exists()
        assert not (tmp_path / "BWPro.exe.new.sha256.part").exists()


def test_restart_passes_temporary_updater_cleanup_location(tmp_path, monkeypatch):
    import client.update as update
    import os

    target = tmp_path / "BWPro.exe"
    staged = tmp_path / "BWPro.exe.new"
    updater_dir = tmp_path / "bwpro-update-test"
    updater_dir.mkdir()
    updater = updater_dir / "BWPro.exe"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    updater.write_bytes(b"updater")
    monkeypatch.setattr(update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(update.sys, "executable", str(updater))
    restarted = []

    def restart(path, *, cleanup):
        restarted.append((path.read_bytes(), cleanup))

    assert apply_update(
        123, target, staged, hashlib.sha256(b"new").hexdigest(),
        wait=lambda _pid: None, restart=restart) == 0
    assert restarted == [(b"new", (os.getpid(), updater_dir))]


def test_post_wait_cleanup_metadata_failure_restarts_old_version(tmp_path, monkeypatch):
    import client.update as update

    target = tmp_path / "BWPro.exe"
    staged = tmp_path / "BWPro.exe.new"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    restarted = []
    monkeypatch.setattr(
        update, "_updater_cleanup_location",
        lambda: (_ for _ in ()).throw(OSError("无法读取更新副本路径")))

    with pytest.raises(UpdateError, match="回滚"):
        apply_update(
            123, target, staged, hashlib.sha256(b"new").hexdigest(),
            wait=lambda _pid: None,
            restart=lambda path, **_kwargs: restarted.append(path.read_bytes()))
    assert restarted == [b"old"]
    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"


def test_cleanup_thread_start_failure_is_logged_not_raised(monkeypatch, caplog, tmp_path):
    import threading
    from client.update import schedule_update_cleanup

    monkeypatch.setattr(
        threading, "Thread",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("线程启动失败")))
    with caplog.at_level("WARNING", logger="client.update"):
        assert schedule_update_cleanup(99, tmp_path / "bwpro-update-test") is None
    assert "无法启动更新临时文件清理" in caplog.text


def test_cleanup_waits_for_updater_and_never_breaks_restarted_app(
        tmp_path, caplog):
    from client.update import cleanup_update_after_exit

    updater_dir = tmp_path / "bwpro-update-test"
    updater_dir.mkdir()
    (updater_dir / "BWPro.exe").write_bytes(b"updater")
    calls = []

    def exited(pid, timeout):
        calls.append((pid, timeout))

    assert cleanup_update_after_exit(99, updater_dir, wait=exited) is True
    assert not updater_dir.exists()
    assert calls == [(99, 10.0)]

    blocked = tmp_path / "bwpro-update-blocked"
    blocked.mkdir()

    def still_running(pid, timeout):
        raise UpdateError("等待超时")

    with caplog.at_level("WARNING", logger="client.update"):
        assert cleanup_update_after_exit(99, blocked, wait=still_running) is False
    assert blocked.exists()
    assert "清理更新临时文件失败" in caplog.text

    unsafe = tmp_path / "ordinary-directory"
    unsafe.mkdir()
    assert cleanup_update_after_exit(99, unsafe, wait=exited) is False
    assert unsafe.exists()
