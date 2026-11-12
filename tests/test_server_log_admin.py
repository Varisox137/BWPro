"""日志提取码与日志文件访问服务。"""
import re

import pytest

from server.log_admin import LogAdminService


@pytest.fixture(autouse=True)
def _avoid_real_windows_acl_changes(monkeypatch):
    import os
    import subprocess

    if os.name == "nt":
        monkeypatch.setattr(
            "core.logging_config.subprocess.run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
        )


def test_token_rotation_and_log_listing(tmp_path, monkeypatch):
    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_text("当前", encoding="utf-8")
    (tmp_path / "bwpro-launcher-20261111-115959-2.log").write_text("启动", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("不开放", encoding="utf-8")
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    service = LogAdminService(tmp_path, current)
    first = service.token
    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert service.rotate() != first
    assert service.token != first
    assert (tmp_path / ".log-access-token").read_text(encoding="ascii") == service.token + "\n"
    assert [x["name"] for x in service.list_logs()] == sorted(
        x["name"] for x in service.list_logs())
    assert {x["name"] for x in service.list_logs()} == {
        current.name, "bwpro-launcher-20261111-115959-2.log"}
    assert next(x for x in service.list_logs() if x["current"])["name"] == current.name


def test_preview_limit_download_path_and_traversal(tmp_path, monkeypatch):
    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_bytes(b"a" * (512 * 1024 + 10))
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    service = LogAdminService(tmp_path, current)
    text, truncated = service.preview(current.name)
    assert len(text.encode("utf-8")) <= 512 * 1024
    assert truncated is True
    assert service.log_path(current.name) == current
    for name in ("../secret", "notes.txt", ".log-access-token"):
        with pytest.raises(ValueError):
            service.log_path(name)


def test_terminal_failure_never_prints_token(tmp_path, monkeypatch, capsys):
    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_text("当前", encoding="utf-8")
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: False)
    service = LogAdminService(tmp_path, current)
    captured = capsys.readouterr()
    assert service.token not in captured.out
    assert service.token not in captured.err
    assert str(tmp_path / ".log-access-token") in captured.out


def test_token_rotation_is_atomic_and_restricted(tmp_path, monkeypatch):
    import os
    import stat
    import threading
    import time

    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_text("当前", encoding="utf-8")
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    service = LogAdminService(tmp_path, current)
    token_path = tmp_path / ".log-access-token"
    expected_mode = 0o666 if os.name == "nt" else 0o600
    assert stat.S_IMODE(token_path.stat().st_mode) == expected_mode

    tokens = {service.token}
    observations = []
    errors = []
    stop = threading.Event()

    def read_tokens():
        while not stop.is_set():
            try:
                observations.append(token_path.read_text(encoding="ascii"))
            except PermissionError as error:
                if os.name == "nt":
                    continue
                errors.append(error)
                return
            except OSError as error:
                errors.append(error)
                return

    reader = threading.Thread(target=read_tokens)
    reader.start()
    try:
        for _ in range(20):
            tokens.add(service.rotate())
            time.sleep(0.001)
    finally:
        stop.set()
        reader.join()

    assert not errors
    assert observations
    assert set(observations) <= {token + "\n" for token in tokens}
    assert token_path.read_text(encoding="ascii") == service.token + "\n"
    assert stat.S_IMODE(token_path.stat().st_mode) == expected_mode
    assert list(tmp_path.glob(".log-access-token.*")) == []


def test_auth_throttles_after_five_failures_and_success_clears_history(tmp_path, monkeypatch):
    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_text("当前", encoding="utf-8")
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    service = LogAdminService(tmp_path, current)
    valid = f"Bearer {service.token}"

    for _ in range(4):
        assert not service.authenticate("Bearer wrong", "client-a")
    assert service.authenticate(valid, "client-a")
    for _ in range(5):
        assert not service.authenticate("Bearer wrong", "client-a")
    assert not service.authenticate(valid, "client-a")
    assert service.authenticate(valid, "client-b")


def _make_api_service(tmp_path, monkeypatch, rotate_seconds=1800.0):
    current = tmp_path / "bwpro-20261111-120000-1.log"
    current.write_bytes("第一行\n第二行\n".encode("utf-8"))
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    return LogAdminService(tmp_path, current, rotate_seconds=rotate_seconds)


def _http_request(port, path, token=None, extra_headers=None):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    headers.update(extra_headers or {})
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, body, dict(response.getheaders())
    finally:
        connection.close()


class _running_server:
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        import asyncio
        import socket
        import threading
        import time

        import uvicorn

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                log_level="error", server_header=False,
                                proxy_headers=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve()),
                                       daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self.port
            if not self.thread.is_alive():
                break
            time.sleep(0.02)
        self.server.should_exit = True
        self.thread.join(timeout=5)
        raise RuntimeError("日志管理测试服务端未能启动")

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


def test_log_admin_api_auth_preview_download_and_invalid_paths(tmp_path, monkeypatch):
    import json

    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    with _running_server(app) as port:
        assert _http_request(port, "/api/log-admin/logs")[:2] == (401, b"")
        assert _http_request(port, "/api/log-admin/logs", "wrong")[:2] == (401, b"")

        status, body, _ = _http_request(port, "/api/log-admin/logs", service.token)
        assert status == 200
        listed = json.loads(body)["logs"]
        assert len(listed) == 1
        assert listed[0]["name"] == "bwpro-20261111-120000-1.log"
        assert listed[0]["current"] is True

        name = listed[0]["name"]
        status, body, _ = _http_request(
            port, f"/api/log-admin/logs/{name}/preview", service.token)
        assert status == 200
        assert json.loads(body) == {"text": "第一行\n第二行\n", "truncated": False}
        status, body, headers = _http_request(
            port, f"/api/log-admin/logs/{name}/download", service.token)
        assert status == 200
        assert body == "第一行\n第二行\n".encode("utf-8")
        assert name in headers["content-disposition"]

        assert _http_request(
            port, "/api/log-admin/logs/../preview", service.token)[:2] == (404, b"")
        assert _http_request(
            port, "/api/log-admin/logs/notes.txt/download", service.token)[:2] == (404, b"")
        assert _http_request(
            port, "/api/log-admin/logs/../secret", service.token)[:2] == (404, b"")


def test_log_admin_routes_are_disabled_by_default(tmp_path, monkeypatch):
    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    _make_api_service(tmp_path, monkeypatch)
    app = create_app(RoomManager(F.base_db()))
    with _running_server(app) as port:
        assert _http_request(port, "/api/log-admin/logs")[:2] == (403, b"")


def test_log_admin_lifespan_rotates_and_stops_cleanly(tmp_path, monkeypatch):
    import time

    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch, rotate_seconds=0.01)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    old = service.token
    with _running_server(app):
        deadline = time.monotonic() + 1.0
        while service.token == old and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.token != old
        assert not service.authenticate(f"Bearer {old}", "test")


def test_non_ascii_auth_is_counted_as_failure(tmp_path, monkeypatch):
    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    with _running_server(app) as port:
        for _ in range(4):
            assert _http_request(port, "/api/log-admin/logs", "é")[:2] == (401, b"")
        assert _http_request(port, "/api/log-admin/logs", service.token)[0] == 200
        for _ in range(5):
            assert _http_request(port, "/api/log-admin/logs", "é")[:2] == (401, b"")
        assert _http_request(port, "/api/log-admin/logs", service.token)[:2] == (401, b"")


def test_forwarded_headers_do_not_change_auth_throttle_bucket(tmp_path, monkeypatch):
    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    with _running_server(app) as port:
        for index in range(5):
            status, body, _ = _http_request(
                port, "/api/log-admin/logs", "wrong",
                extra_headers={"X-Forwarded-For": f"198.51.100.{index}"})
            assert (status, body) == (401, b"")
        assert _http_request(
            port, "/api/log-admin/logs", service.token,
            extra_headers={"X-Forwarded-For": "203.0.113.9"})[:2] == (401, b"")


def test_auth_failure_cleanup_expires_all_sources(tmp_path, monkeypatch):
    service = _make_api_service(tmp_path, monkeypatch)
    now = [1000.0]
    monkeypatch.setattr("server.log_admin.time.monotonic", lambda: now[0])
    service.authenticate("Bearer wrong", "client-a")
    service.authenticate("Bearer wrong", "client-b")
    now[0] += 61.0

    assert service.authenticate(f"Bearer {service.token}", "client-c")
    assert service._auth_failures == {}


def test_rotation_failure_preserves_old_token_and_loop_recovers(tmp_path, monkeypatch, caplog):
    import asyncio
    import contextlib
    import logging
    import os

    service = _make_api_service(tmp_path, monkeypatch, rotate_seconds=0.1)
    old = service.token
    token_path = tmp_path / ".log-access-token"
    original_replace = os.replace
    attempts = []

    def fail_first_replace(source, destination):
        attempts.append((source, destination))
        if len(attempts) == 1:
            raise OSError("injected rotation failure")
        return original_replace(source, destination)

    monkeypatch.setattr("server.log_admin.os.replace", fail_first_replace)
    caplog.set_level(logging.ERROR, logger="server.log_admin")

    async def scenario():
        task = asyncio.create_task(service.rotation_loop())
        try:
            for _ in range(100):
                if attempts:
                    break
                await asyncio.sleep(0.001)
            assert attempts
            assert service.token == old
            assert token_path.read_text(encoding="ascii") == old + "\n"
            for _ in range(200):
                if service.token != old:
                    break
                await asyncio.sleep(0.005)
            assert service.token != old
            assert token_path.read_text(encoding="ascii") == service.token + "\n"
            assert not task.done()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await task

    asyncio.run(scenario())
    assert "日志提取码轮换失败" in caplog.text
    assert old not in caplog.text
    assert service.token not in caplog.text


def test_log_listing_skips_file_deleted_after_discovery(tmp_path, monkeypatch):
    service = _make_api_service(tmp_path, monkeypatch)
    removed = tmp_path / "bwpro-20261111-115959-2.log"
    removed.write_text("即将删除", encoding="utf-8")
    original_log_files = service._log_files

    def files_then_delete():
        files = original_log_files()
        removed.unlink()
        return files

    monkeypatch.setattr(service, "_log_files", files_then_delete)
    assert [item["name"] for item in service.list_logs()] == [service.current_log.name]


@pytest.mark.parametrize("action", ["preview", "download"])
def test_log_admin_returns_404_when_file_disappears_after_validation(
        tmp_path, monkeypatch, action):
    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch)
    original_log_path = service.log_path

    def path_then_delete(name):
        path = original_log_path(name)
        path.unlink()
        return path

    monkeypatch.setattr(service, "log_path", path_then_delete)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    with _running_server(app) as port:
        path = f"/api/log-admin/logs/{service.current_log.name}/{action}"
        assert _http_request(port, path, service.token)[:2] == (404, b"")


def test_download_streams_complete_file_without_read_bytes(tmp_path, monkeypatch):
    from pathlib import Path

    from server.main import create_app
    from server.manager import RoomManager
    from tests import factories as F

    service = _make_api_service(tmp_path, monkeypatch)
    payload = bytes(range(256)) * 513
    service.current_log.write_bytes(payload)

    def forbidden_read_bytes(self):
        raise AssertionError("下载不得一次性 read_bytes")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    app = create_app(RoomManager(F.base_db()), log_admin=service)
    with _running_server(app) as port:
        path = f"/api/log-admin/logs/{service.current_log.name}/download"
        status, body, headers = _http_request(port, path, service.token)
        assert status == 200
        assert len(payload) > 2 * 64 * 1024
        assert body == payload
        assert service.current_log.name in headers["content-disposition"]


def test_log_path_rejects_windows_unsafe_names_before_lookup(tmp_path, monkeypatch):
    service = _make_api_service(tmp_path, monkeypatch)
    unsafe = tmp_path / "bwpro-invalid:.log"
    monkeypatch.setattr(service, "_log_files", lambda: [unsafe])
    with pytest.raises(ValueError, match="日志文件名无效"):
        service.log_path(unsafe.name)


def test_windows_token_acl_failure_aborts_rotation_and_preserves_old_token(
        tmp_path, monkeypatch):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows ACL 失败路径仅在 Windows 运行")
    service = _make_api_service(tmp_path, monkeypatch)
    old = service.token
    token_path = tmp_path / ".log-access-token"

    def fail_acl(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=b"denied")

    monkeypatch.setattr("core.logging_config.subprocess.run", fail_acl)
    with pytest.raises(subprocess.CalledProcessError):
        service.rotate()
    assert service.token == old
    assert token_path.read_text(encoding="ascii") == old + "\n"
    assert list(tmp_path.glob(".log-access-token.*")) == []
