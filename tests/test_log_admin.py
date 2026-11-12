"""独立日志运维端的 HTTP 与离屏 GUI 测试。"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFileDialog, QLineEdit

from client.log_admin import LogAdminClient, LogAdminWindow, normalize_admin_url


@pytest.mark.parametrize(("raw", "expected"), [
    ("127.0.0.1", "http://127.0.0.1:1037"),
    ("localhost:1037", "http://localhost:1037"),
    ("[::1]:1037", "http://[::1]:1037"),
    ("::1", "http://[::1]:1037"),
    ("bwpro.example", "https://bwpro.example"),
    ("bwpro.example:8443", "https://bwpro.example:8443"),
    ("192.0.2.10:8443", "https://192.0.2.10:8443"),
    ("http://bwpro.example:8443", "http://bwpro.example:8443"),
    ("https://bwpro.example", "https://bwpro.example"),
    ("wss://bwpro.example/ws", "https://bwpro.example"),
    ("http://localhost/", "http://localhost:1037"),
    ("ws://127.0.0.1:2000/ws/", "http://127.0.0.1:2000"),
])
def test_normalize_admin_url(raw, expected):
    assert normalize_admin_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://localhost", "http://localhost:bad"])
def test_normalize_admin_url_rejects_invalid_addresses(raw):
    with pytest.raises(ValueError):
        normalize_admin_url(raw)


class _FakeResponse:
    def __init__(self, payload, download_name="bwpro-test.log"):
        self.payload = payload
        self.offset = 0
        self.read_sizes = []
        self.headers = self

    def get_filename(self):
        return self.download_name if hasattr(self, "download_name") else None

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_json_response_limit_uses_actual_bytes_not_content_length(monkeypatch):
    client = LogAdminClient("127.0.0.1", "token")
    payload = (b'{"logs":[],"padding":"' + b"x" * (2 * 1024 * 1024) + b'"}')
    response = _FakeResponse(payload)
    monkeypatch.setattr(client, "_open", lambda _path: response)
    with pytest.raises(RuntimeError, match="2 MiB"):
        client.list_logs()
    assert response.read_sizes
    assert all(size >= 0 for size in response.read_sizes)


def test_download_limit_interrupts_and_removes_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr("client.log_admin._MAX_DOWNLOAD_BYTES", 8, raising=False)
    client = LogAdminClient("127.0.0.1", "token")
    response = _FakeResponse(b"123456789")
    response.download_name = "bwpro-test.log"
    monkeypatch.setattr(client, "_open", lambda _path: response)
    with pytest.raises(RuntimeError, match="下载"):
        client.download("bwpro-test.log", tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert response.offset == 9


@pytest.mark.parametrize("name", [
    "bwpro-bad:.log", "bwpro-bad\x01.log", "bwpro-bad<.log",
    "bwpro-test.log ", "bwpro-test.log.",
])
def test_download_name_rejects_windows_unsafe_characters(name):
    with pytest.raises(RuntimeError, match="日志文件名"):
        LogAdminClient._validate_download_name(name)


class LogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer 0123456789abcdef":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/api/log-admin/logs":
            self._json({"logs": [
                {"name": "bwpro-test.log", "mtime": 123.5, "size": 6, "current": True},
                {"name": "bwpro-old.log", "mtime": 100.0, "size": 3, "current": False},
            ]})
            return
        if self.path == "/api/log-admin/logs/bwpro-test.log/preview":
            self._json({"text": "日志内容", "truncated": False})
            return
        if self.path == "/api/log-admin/logs/missing.log/preview":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/api/log-admin/logs/error.log/preview":
            self.send_response(500)
            self.end_headers()
            return
        if self.path == "/api/log-admin/logs/bwpro-test.log/download":
            data = "日志内容".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=utf-8''{quote(self.server.download_name, safe='')}",
            )
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def _json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), LogHandler)
    httpd.requests = []
    httpd.download_name = "bwpro-test.log"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_port}"
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def test_client_uses_actual_api_and_bearer_auth(server, tmp_path):
    client = LogAdminClient(server.url, "0123456789abcdef")
    logs = client.list_logs()
    assert logs[0] == {
        "name": "bwpro-test.log", "mtime": 123.5, "size": 6, "current": True,
    }
    assert client.preview("bwpro-test.log") == {"text": "日志内容", "truncated": False}
    target = client.download("bwpro-test.log", tmp_path)
    assert target.read_text(encoding="utf-8") == "日志内容"
    assert server.requests == [
        ("/api/log-admin/logs", "Bearer 0123456789abcdef"),
        ("/api/log-admin/logs/bwpro-test.log/preview", "Bearer 0123456789abcdef"),
        ("/api/log-admin/logs/bwpro-test.log/download", "Bearer 0123456789abcdef"),
    ]


def test_client_download_never_overwrites_existing_file(server, tmp_path):
    client = LogAdminClient(server.url, "0123456789abcdef")
    first = client.download("bwpro-test.log", tmp_path)
    second = client.download("bwpro-test.log", tmp_path)
    assert first.name == "bwpro-test.log"
    assert second.name == "bwpro-test (1).log"
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8") == "日志内容"


def test_client_rejects_non_log_download_name(server, tmp_path):
    server.download_name = "../evil.txt"
    client = LogAdminClient(server.url, "0123456789abcdef")
    with pytest.raises(RuntimeError, match="日志文件名"):
        client.download("bwpro-test.log", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_client_reports_auth_and_http_errors(server):
    unauthorized = LogAdminClient(server.url, "wrong")
    with pytest.raises(PermissionError, match="提取码无效或已轮换"):
        unauthorized.list_logs()
    client = LogAdminClient(server.url, "0123456789abcdef")
    with pytest.raises(RuntimeError) as caught:
        client.preview("missing.log")
    assert server.url in str(caught.value)
    assert "404" in str(caught.value)
    with pytest.raises(RuntimeError, match="500"):
        client.preview("error.log")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def wait_for(qapp, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("等待日志运维端后台操作超时")


class FakeAdminClient:
    def __init__(self):
        self.previewed = []
        self.downloaded = []

    def list_logs(self):
        return [
            {"name": "bwpro-current.log", "mtime": 123.5, "size": 12, "current": True},
            {"name": "bwpro-old.log", "mtime": 100.0, "size": 8, "current": False},
        ]

    def preview(self, name):
        self.previewed.append(name)
        return {"text": f"预览：{name}", "truncated": name == "bwpro-current.log"}

    def download(self, name, destination):
        self.downloaded.append((name, Path(destination)))
        target = Path(destination) / name
        target.write_text(name, encoding="utf-8")
        return target


def test_window_loads_previews_and_downloads_multiple_logs(qapp, tmp_path, monkeypatch):
    client = FakeAdminClient()
    window = LogAdminWindow(client=client)
    assert window.token_edit.echoMode() == QLineEdit.Password
    assert window.preview_edit.isReadOnly()
    assert window.log_table.selectionMode() == QAbstractItemView.ExtendedSelection
    assert window.log_table.selectionBehavior() == QAbstractItemView.SelectRows

    assert window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    assert window.connect_button.isEnabled()
    assert window.log_table.item(0, 0).text() == "bwpro-current.log"
    assert window.log_table.item(0, 3).text() == "是"

    window.log_table.selectRow(0)
    wait_for(qapp, lambda: window.preview_edit.toPlainText() == "预览：bwpro-current.log")
    assert "已截断" in window.status_label.text()

    selection = window.log_table.selectionModel()
    selection.select(window.log_table.model().index(1, 0),
                     QItemSelectionModel.Select | QItemSelectionModel.Rows)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *args, **kwargs: str(tmp_path))
    assert window.download_selected()
    wait_for(qapp, lambda: len(client.downloaded) == 2 and window.download_button.isEnabled())
    assert [name for name, _ in client.downloaded] == ["bwpro-current.log", "bwpro-old.log"]
    assert str(tmp_path / "bwpro-current.log") in window.status_label.text()
    assert str(tmp_path / "bwpro-old.log") in window.status_label.text()
    window.close()


def test_window_background_errors_are_visible_and_reenable_buttons(qapp):
    client = FakeAdminClient()
    window = LogAdminWindow(client=client)
    client.list_logs = lambda: (_ for _ in ()).throw(RuntimeError("连接失败"))
    assert window.connect_server()
    wait_for(qapp, lambda: "连接失败" in window.status_label.text())
    assert "获取日志列表失败" in window.status_label.text()
    assert window.connect_button.isEnabled()

    client.list_logs = FakeAdminClient.list_logs.__get__(client)
    window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    client.preview = lambda _name: (_ for _ in ()).throw(RuntimeError("预览不可用"))
    window.log_table.selectRow(0)
    wait_for(qapp, lambda: "预览失败" in window.status_label.text())
    assert "预览不可用" in window.status_label.text()
    window.close()


def test_closing_window_disconnects_pending_worker_callbacks(qapp):
    class BlockingClient(FakeAdminClient):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def list_logs(self):
            self.started.set()
            self.release.wait(2)
            return super().list_logs()

    client = BlockingClient()
    window = LogAdminWindow(client=client)
    window.connect_server()
    assert client.started.wait(1)
    assert not window.connect_button.isEnabled()
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    client.release.set()
    time.sleep(0.05)
    qapp.processEvents()


def test_window_rebuilds_client_from_current_credentials(qapp, monkeypatch):
    created = []

    def client_factory(url, token):
        client = FakeAdminClient()
        client.base_url = url
        client.token = token
        if not created:
            client.list_logs = lambda: (_ for _ in ()).throw(
                PermissionError("提取码无效或已轮换"))
        created.append(client)
        return client

    monkeypatch.setattr("client.log_admin.LogAdminClient", client_factory)
    window = LogAdminWindow()
    window.server_edit.setText("localhost:1037")
    window.token_edit.setText("old-token")
    assert window.connect_server()
    wait_for(qapp, lambda: "提取码无效或已轮换" in window.status_label.text())
    assert window.connect_button.isEnabled()

    window.server_edit.setText("https://logs.example")
    window.token_edit.setText("new-token")
    assert window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    assert [(client.base_url, client.token) for client in created] == [
        ("localhost:1037", "old-token"),
        ("https://logs.example", "new-token"),
    ]
    assert window.client is created[1]
    assert "共 2 个日志文件" in window.status_label.text()
    window.close()


def test_window_discards_out_of_order_preview_responses(qapp):
    class OutOfOrderClient(FakeAdminClient):
        def __init__(self):
            super().__init__()
            names = ("bwpro-current.log", "bwpro-old.log")
            self.started = {name: threading.Event() for name in names}
            self.release = {name: threading.Event() for name in names}
            self.finished = {name: threading.Event() for name in names}

        def preview(self, name):
            self.started[name].set()
            self.release[name].wait(2)
            result = super().preview(name)
            self.finished[name].set()
            return result

    client = OutOfOrderClient()
    window = LogAdminWindow(client=client)
    window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)

    window.log_table.selectRow(0)
    assert client.started["bwpro-current.log"].wait(1)
    window.log_table.selectRow(1)
    assert client.started["bwpro-old.log"].wait(1)
    client.release["bwpro-old.log"].set()
    wait_for(qapp, lambda: window.preview_edit.toPlainText() == "预览：bwpro-old.log")
    client.release["bwpro-current.log"].set()
    assert client.finished["bwpro-current.log"].wait(1)
    qapp.processEvents()
    assert window.preview_edit.toPlainText() == "预览：bwpro-old.log"
    window.close()


def test_window_refresh_invalidates_pending_preview(qapp):
    class PendingPreviewClient(FakeAdminClient):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()

        def preview(self, name):
            self.started.set()
            self.release.wait(2)
            self.finished.set()
            return super().preview(name)

    client = PendingPreviewClient()
    window = LogAdminWindow(client=client)
    window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    window.log_table.selectRow(0)
    assert client.started.wait(1)

    window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    client.release.set()
    assert client.finished.wait(1)
    qapp.processEvents()
    assert window.preview_edit.toPlainText() != "预览：bwpro-current.log"
    window.close()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_client_refuses_cross_origin_redirect_without_leaking_token(status):
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(status)
            self.send_header("Location", self.server.target_url)
            self.end_headers()

        def log_message(self, _format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), LogHandler)
    target.requests = []
    target.download_name = "bwpro-test.log"
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect.requests = []
    redirect.target_url = f"http://127.0.0.1:{target.server_port}/api/log-admin/logs"
    threads = [threading.Thread(target=item.serve_forever, daemon=True)
               for item in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        client = LogAdminClient(
            f"http://127.0.0.1:{redirect.server_port}", "0123456789abcdef")
        with pytest.raises(RuntimeError, match=str(status)):
            client.list_logs()
        assert redirect.requests == [("/api/log-admin/logs", "Bearer 0123456789abcdef")]
        assert target.requests == []
    finally:
        for item in (redirect, target):
            item.shutdown()
            item.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_client_download_permission_error_removes_new_partial_file(tmp_path, monkeypatch):
    client = LogAdminClient("127.0.0.1", "token")
    response = _FakeResponse(b"partial")
    response.download_name = "bwpro-test.log"

    def fail_read(_size):
        raise PermissionError("注入读取权限失败")

    monkeypatch.setattr(response, "read", fail_read)
    monkeypatch.setattr(client, "_open", lambda _path: response)
    with pytest.raises(PermissionError, match="注入读取权限失败"):
        client.download("bwpro-test.log", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_client_download_incomplete_read_removes_only_new_partial_file(tmp_path, monkeypatch):
    from http.client import IncompleteRead

    existing = tmp_path / "bwpro-test.log"
    existing.write_bytes(b"existing")
    client = LogAdminClient("127.0.0.1", "token")
    response = _FakeResponse(b"partial")
    response.download_name = "bwpro-test.log"

    def fail_read(_size):
        raise IncompleteRead(b"partial", 10)

    monkeypatch.setattr(response, "read", fail_read)
    monkeypatch.setattr(client, "_open", lambda _path: response)
    with pytest.raises(IncompleteRead):
        client.download("bwpro-test.log", tmp_path)
    assert existing.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [existing]


def test_window_discards_out_of_order_preview_errors(qapp):
    class OutOfOrderErrorClient(FakeAdminClient):
        def __init__(self):
            super().__init__()
            self.old_started = threading.Event()
            self.old_release = threading.Event()
            self.old_finished = threading.Event()

        def preview(self, name):
            if name == "bwpro-current.log":
                self.old_started.set()
                self.old_release.wait(2)
                self.old_finished.set()
                raise RuntimeError("过期预览失败")
            return super().preview(name)

    client = OutOfOrderErrorClient()
    window = LogAdminWindow(client=client)
    window.connect_server()
    wait_for(qapp, lambda: window.log_table.rowCount() == 2)
    window.log_table.selectRow(0)
    assert client.old_started.wait(1)
    window.log_table.selectRow(1)
    wait_for(qapp, lambda: window.preview_edit.toPlainText() == "预览：bwpro-old.log")
    client.old_release.set()
    assert client.old_finished.wait(1)
    qapp.processEvents()
    assert window.preview_edit.toPlainText() == "预览：bwpro-old.log"
    assert window.status_label.text() == "预览已加载"
    window.close()
