"""服务端日志提取码与文件访问。"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path

from core.logging_config import (
    LOG_PATTERNS, is_log_filename, restrict_private_permissions, write_terminal_secret,
)

PREVIEW_BYTES = 512 * 1024
AUTH_FAILURE_WINDOW = 60.0
AUTH_FAILURE_LIMIT = 5


class LogAdminService:
    def __init__(self, log_dir: Path, current_log: Path, rotate_seconds: float = 1800.0):
        self.log_dir = log_dir
        self.current_log = current_log
        self.rotate_seconds = rotate_seconds
        self._token = ""
        self._auth_failures: dict[str, list[float]] = {}
        self.rotate()

    @property
    def token(self) -> str:
        return self._token

    def _prune_auth_failures(self, now: float) -> None:
        for client, stamps in list(self._auth_failures.items()):
            failures = [stamp for stamp in stamps if now - stamp < AUTH_FAILURE_WINDOW]
            if failures:
                self._auth_failures[client] = failures
            else:
                del self._auth_failures[client]

    def _recent_failures(self, client: str, now: float) -> list[float]:
        self._prune_auth_failures(now)
        return self._auth_failures.get(client, [])

    def _throttled(self, client: str) -> bool:
        return len(self._recent_failures(client, time.monotonic())) >= AUTH_FAILURE_LIMIT

    def _record_auth_result(self, client: str, valid: bool) -> None:
        if valid:
            self._auth_failures.pop(client, None)
            return
        now = time.monotonic()
        failures = self._recent_failures(client, now)
        failures.append(now)
        self._auth_failures[client] = failures

    def authenticate(self, header: str | None, client: str) -> bool:
        if self._throttled(client):
            return False
        expected = f"Bearer {self._token}"
        valid = False
        if header is not None:
            try:
                valid = hmac.compare_digest(header, expected)
            except TypeError:
                pass
        self._record_auth_result(client, valid)
        return valid

    async def rotation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.rotate_seconds)
            try:
                self.rotate()
            except Exception:
                logging.getLogger(__name__).exception("日志提取码轮换失败")

    def rotate(self) -> str:
        candidate = secrets.token_hex(8)
        path = self.log_dir / ".log-access-token"
        fd, temporary_name = tempfile.mkstemp(prefix=".log-access-token.", dir=self.log_dir)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as temporary:
                restrict_private_permissions(temporary_path)
                temporary.write(candidate + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            deadline = time.monotonic() + 1.0
            while True:
                try:
                    os.replace(temporary_path, path)
                    break
                except PermissionError:
                    if os.name != "nt" or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.001)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if not write_terminal_secret(f"[{timestamp}]日志提取码更新：{candidate}"):
            print(f"日志提取码已写入：{path}", flush=True)
        self._token = candidate
        return candidate

    def _log_files(self) -> list[Path]:
        files = {}
        log_root = self.log_dir.resolve()
        for pattern in LOG_PATTERNS:
            for path in self.log_dir.glob(pattern):
                if (not is_log_filename(path.name) or not path.is_file()
                        or path.resolve().parent != log_root):
                    continue
                files[path.name] = path
        return [files[name] for name in sorted(files)]

    def list_logs(self) -> list[dict]:
        logs = []
        for path in self._log_files():
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            logs.append({
                "name": path.name,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "current": path == self.current_log,
            })
        return logs

    def log_path(self, name: str) -> Path:
        if not is_log_filename(name):
            raise ValueError("日志文件名无效")
        for path in self._log_files():
            if path.name == name:
                return path
        raise ValueError("日志文件不存在或不允许访问")

    def preview(self, name: str) -> tuple[str, bool]:
        path = self.log_path(name)
        with path.open("rb") as source:
            data = source.read(PREVIEW_BYTES + 1)
        truncated = len(data) > PREVIEW_BYTES
        text = data[:PREVIEW_BYTES].decode("utf-8", errors="replace")
        encoded = text.encode("utf-8")
        if len(encoded) > PREVIEW_BYTES:
            truncated = True
            text = encoded[:PREVIEW_BYTES].decode("utf-8", errors="ignore")
        return text, truncated
