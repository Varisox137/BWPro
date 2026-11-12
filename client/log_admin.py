"""独立于对局客户端的服务器日志运维端。

运行：python -m client.log_admin
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QFileDialog,
)

from core.logging_config import is_log_filename

_TIMEOUT = 10
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 2 * 1024 ** 3 - 1
_DOWNLOAD_CHUNK_BYTES = 64 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_admin_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("服务器地址不能为空")
    if "://" not in value:
        authority, separator, suffix = value.partition("/")
        if authority.count(":") > 1 and not authority.startswith("["):
            authority = f"[{authority}]"
            value = authority + (separator + suffix if separator else "")
        hostname = urlsplit("//" + authority).hostname
        local = hostname in ("localhost", "127.0.0.1", "::1")
        value = ("http://" if local else "https://") + value
    try:
        parsed = urlsplit(value)
        scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
        if scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("仅支持 http(s) 或 ws(s) 服务器地址")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("服务器地址不能包含用户信息")
        if parsed.query or parsed.fragment:
            raise ValueError("服务器地址不能包含查询参数或片段")
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"服务器地址无效：{error}") from None
    path = parsed.path.rstrip("/")
    if path == "/ws":
        path = ""
    elif path:
        raise ValueError("服务器地址只允许以 /ws 结尾")
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if port is None and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        port = 1037
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit((scheme, netloc, path, "", ""))


class LogAdminClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = normalize_admin_url(base_url)
        self.token = token

    def _open(self, path: str):
        request = Request(
            self.base_url + path,
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            return build_opener(_NoRedirectHandler).open(request, timeout=_TIMEOUT)
        except HTTPError as error:
            error.close()
            if error.code == 401:
                raise PermissionError("提取码无效或已轮换") from None
            raise RuntimeError(
                f"日志服务器 {self.base_url} 请求失败：HTTP {error.code}") from None
        except (URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise RuntimeError(f"日志服务器 {self.base_url} 请求失败：{reason}") from None

    def _json(self, path: str) -> dict:
        with self._open(path) as response:
            data = response.read(_MAX_JSON_BYTES + 1)
            if len(data) > _MAX_JSON_BYTES:
                raise RuntimeError(f"日志服务器 {self.base_url} 的 JSON 响应超过 2 MiB")
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError(
                    f"日志服务器 {self.base_url} 返回了无效 JSON：{error}") from None
        if not isinstance(payload, dict):
            raise RuntimeError(f"日志服务器 {self.base_url} 返回结构无效")
        return payload

    @staticmethod
    def _log_path(name: str, suffix: str) -> str:
        return f"/api/log-admin/logs/{quote(name, safe='')}/{suffix}"

    def list_logs(self) -> list[dict]:
        payload = self._json("/api/log-admin/logs")
        logs = payload.get("logs")
        if not isinstance(logs, list) or not all(isinstance(item, dict) for item in logs):
            raise RuntimeError(f"日志服务器 {self.base_url} 返回的日志列表无效")
        return logs

    def preview(self, name: str) -> dict:
        payload = self._json(self._log_path(name, "preview"))
        if not isinstance(payload.get("text"), str) or not isinstance(
                payload.get("truncated"), bool):
            raise RuntimeError(f"日志服务器 {self.base_url} 返回的日志预览无效")
        return payload

    @staticmethod
    def _validate_download_name(name: str) -> str:
        if not is_log_filename(name):
            raise RuntimeError(f"服务端返回了非日志文件名：{name}")
        return name

    @staticmethod
    def _exclusive_target(destination: Path, name: str):
        index = 0
        while True:
            suffix = "" if index == 0 else f" ({index})"
            target = destination / f"{Path(name).stem}{suffix}{Path(name).suffix}"
            try:
                return target, target.open("xb")
            except FileExistsError:
                index += 1

    def download(self, name: str, destination: Path) -> Path:
        destination = Path(destination)
        target = None
        try:
            with self._open(self._log_path(name, "download")) as response:
                download_name = response.headers.get_filename() or name
                self._validate_download_name(download_name)
                target, output = self._exclusive_target(destination, download_name)
                with output:
                    downloaded = 0
                    while True:
                        remaining = _MAX_DOWNLOAD_BYTES - downloaded
                        chunk = response.read(min(_DOWNLOAD_CHUNK_BYTES, remaining + 1))
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > _MAX_DOWNLOAD_BYTES:
                            raise RuntimeError("日志下载超过 2 GiB-1 上限，已中断")
                        output.write(chunk)
            return target
        except Exception as error:
            if target is not None:
                target.unlink(missing_ok=True)
            if isinstance(error, (PermissionError, RuntimeError)):
                raise
            if isinstance(error, (URLError, OSError)):
                reason = getattr(error, "reason", error)
                raise RuntimeError(
                    f"日志服务器 {self.base_url} 下载失败：{reason}") from None
            raise


class _LogAdminSignals(QObject):
    logs_loaded = Signal(list)
    preview_loaded = Signal(object)
    downloads_finished = Signal(list)
    request_failed = Signal(str, str, object)


def _run_request(operation, work, result_signal, signals, error_context=None):
    try:
        result = work()
    except Exception as error:
        signals.request_failed.emit(
            operation, str(error) or error.__class__.__name__, error_context)
    else:
        result_signal.emit(result)


class LogAdminWindow(QWidget):
    def __init__(self, client: LogAdminClient | None = None, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._client_factory = (lambda _url, _token: client) if client is not None else None
        self._preview_generation = 0
        self._closing = False
        self._signals = _LogAdminSignals()
        self._signals.logs_loaded.connect(self._set_logs)
        self._signals.preview_loaded.connect(self._set_preview)
        self._signals.downloads_finished.connect(self._set_downloads)
        self._signals.request_failed.connect(self._set_error)

        self.setWindowTitle("BWPro 日志运维")
        self.resize(960, 640)
        layout = QVBoxLayout(self)
        connection = QFormLayout()
        self.server_edit = QLineEdit("127.0.0.1")
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        connection.addRow("服务器地址", self.server_edit)
        connection.addRow("提取码", self.token_edit)
        layout.addLayout(connection)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("连接并刷新")
        self.download_button = QPushButton("下载所选日志")
        self.download_button.setEnabled(False)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.download_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.log_table = QTableWidget(0, 4)
        self.log_table.setHorizontalHeaderLabels(["文件名", "修改时间", "大小", "当前"])
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.log_table, 2)

        layout.addWidget(QLabel("日志预览"))
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        layout.addWidget(self.preview_edit, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.connect_button.clicked.connect(self.connect_server)
        self.download_button.clicked.connect(self.download_selected)
        self.log_table.itemSelectionChanged.connect(self._preview_selected)

    def _start(self, operation: str, work, result_signal, error_context=None) -> None:
        thread = threading.Thread(
            target=_run_request,
            args=(operation, work, result_signal, self._signals, error_context),
            daemon=True,
        )
        thread.start()

    def connect_server(self) -> bool:
        if self._closing or not self.connect_button.isEnabled():
            return False
        factory = self._client_factory or LogAdminClient
        try:
            client = factory(self.server_edit.text(), self.token_edit.text())
        except ValueError as error:
            self.status_label.setText(f"连接失败：{error}")
            return False
        self.client = client
        self._preview_generation += 1
        self.connect_button.setEnabled(False)
        self.status_label.setText("正在获取日志列表……")
        self._start("list", client.list_logs, self._signals.logs_loaded)
        return True

    def _set_logs(self, logs: list) -> None:
        self._preview_generation += 1
        self.preview_edit.clear()
        self.connect_button.setEnabled(True)
        self.log_table.setRowCount(0)
        for entry in logs:
            row = self.log_table.rowCount()
            self.log_table.insertRow(row)
            try:
                modified = datetime.fromtimestamp(float(entry.get("mtime", 0))).strftime(
                    "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError, OSError):
                modified = "-"
            values = (
                str(entry.get("name", "")), modified,
                f"{entry.get('size', 0)} B", "是" if entry.get("current") else "",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, entry)
                self.log_table.setItem(row, column, item)
        self.log_table.resizeColumnsToContents()
        self.download_button.setEnabled(bool(logs))
        self.status_label.setText(f"共 {len(logs)} 个日志文件")

    def _selected_logs(self) -> list[dict]:
        selection = self.log_table.selectionModel()
        if selection is None:
            return []
        rows = sorted(index.row() for index in selection.selectedRows())
        return [self.log_table.item(row, 0).data(Qt.UserRole) for row in rows]

    def _preview_selected(self) -> None:
        if self._closing:
            return
        self._preview_generation += 1
        selected = self._selected_logs()
        if not selected:
            self.preview_edit.clear()
            return
        if self.client is None:
            return
        generation = self._preview_generation
        name = selected[0]["name"]
        client = self.client

        def load_preview():
            return generation, name, client.preview(name)

        self.status_label.setText(f"正在预览 {name}……")
        self._start("preview", load_preview, self._signals.preview_loaded,
                    error_context=(generation, name))

    def _preview_is_current(self, generation: int, name: str) -> bool:
        selected = self._selected_logs()
        return (generation == self._preview_generation and bool(selected)
                and selected[0].get("name") == name)

    def _set_preview(self, result: tuple) -> None:
        generation, name, payload = result
        if not self._preview_is_current(generation, name):
            return
        self.preview_edit.setPlainText(payload["text"])
        self.status_label.setText("预览已截断，仅显示开头内容；可下载完整日志"
                                  if payload["truncated"] else "预览已加载")

    def download_selected(self) -> bool:
        if self._closing or self.client is None or not self.download_button.isEnabled():
            return False
        selected = self._selected_logs()
        if not selected:
            self.status_label.setText("请先选择要下载的日志")
            return False
        directory = QFileDialog.getExistingDirectory(self, "选择日志保存目录")
        if not directory:
            return False
        client = self.client
        names = [entry["name"] for entry in selected]
        destination = Path(directory)

        def download_all():
            return [client.download(name, destination) for name in names]

        self.download_button.setEnabled(False)
        self.status_label.setText(f"正在下载 {len(names)} 个日志……")
        self._start("download", download_all, self._signals.downloads_finished)
        return True

    def _set_downloads(self, paths: list) -> None:
        self.download_button.setEnabled(True)
        self.status_label.setText("已保存：" + "；".join(str(path) for path in paths))

    def _set_error(self, operation: str, message: str, error_context) -> None:
        if operation == "preview":
            generation, name = error_context
            if not self._preview_is_current(generation, name):
                return
        labels = {"list": "获取日志列表失败", "preview": "预览失败", "download": "下载失败"}
        if operation == "list":
            self.connect_button.setEnabled(True)
        elif operation == "download":
            self.download_button.setEnabled(True)
        self.status_label.setText(f"{labels.get(operation, '操作失败')}：{message}")

    def closeEvent(self, event) -> None:
        self._closing = True
        for signal, slot in (
            (self._signals.logs_loaded, self._set_logs),
            (self._signals.preview_loaded, self._set_preview),
            (self._signals.downloads_finished, self._set_downloads),
            (self._signals.request_failed, self._set_error),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = LogAdminWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
