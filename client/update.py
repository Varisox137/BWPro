"""GitHub Release 检查、校验下载与冻结 EXE 的外部替换更新。"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from core.version import VERSION, parse_version

RELEASE_API = "https://api.github.com/repos/Varisox137/BWPro/releases/latest"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024**3 - 1
MAX_SHA256_BYTES = 4096
_NETWORK_TIMEOUT = 30
_WAIT_TIMEOUT = 60.0
_LOGGER = logging.getLogger(__name__)


class UpdateError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class AvailableUpdate:
    tag: str
    exe_name: str
    exe_url: str
    sha256_name: str
    sha256_url: str


@dataclass(frozen=True)
class DownloadedUpdate:
    available: AvailableUpdate
    path: Path
    sha256: str


class SafeHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if urllib.parse.urlsplit(req.full_url).scheme != "https" or \
                urllib.parse.urlsplit(target).scheme != "https":
            raise UpdateError("更新下载禁止非 HTTPS 重定向")
        return super().redirect_request(req, fp, code, msg, headers, target)


def verify_update(current: str, candidate: str) -> str:
    current_tag = current if current.startswith("v") else f"v{current}"
    if parse_version(candidate) <= parse_version(current_tag):
        raise ValueError("仅允许安装更高版本")
    return candidate


def verify_sha256(path: Path, expected: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
        raise ValueError("非法 SHA-256")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    actual = digest.hexdigest()
    if not hmac.compare_digest(actual, expected.lower()):
        raise ValueError("SHA-256 校验失败")
    return actual


def _request(url: str) -> urllib.request.Request:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError("更新地址必须使用 HTTPS")
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"BWPro/{VERSION}",
    })


def _default_opener():
    return urllib.request.build_opener(SafeHTTPSRedirectHandler()).open


def _open(request, opener):
    try:
        return opener(request, timeout=_NETWORK_TIMEOUT)
    except urllib.error.HTTPError as error:
        raise UpdateError(f"更新服务返回 HTTP {error.code}", status=error.code) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise UpdateError("无法连接更新服务") from error


def _read_bounded(response, limit: int) -> bytes:
    data = bytearray()
    while chunk := response.read(min(1024 * 1024, limit - len(data) + 1)):
        data.extend(chunk)
        if len(data) > limit:
            raise UpdateError("更新响应超过大小上限")
    return bytes(data)


def check_for_update(current_version: str = VERSION, *, opener=None) -> AvailableUpdate | None:
    opener = opener or _default_opener()
    with _open(_request(RELEASE_API), opener) as response:
        try:
            payload = json.loads(_read_bounded(response, MAX_METADATA_BYTES))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise UpdateError("更新服务返回非法 JSON") from error
    if not isinstance(payload, dict):
        raise UpdateError("更新服务返回非法 Release")
    tag = payload.get("tag_name")
    try:
        candidate = parse_version(tag)
        current = parse_version(current_version if current_version.startswith("v")
                                else f"v{current_version}")
    except (TypeError, ValueError) as error:
        raise UpdateError("Release 标签不是严格的 vX.Y.Z") from error
    if candidate <= current:
        return None
    exe_name = f"BWPro-{tag}.exe"
    sha256_name = exe_name + ".sha256"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release 缺少资产列表")
    by_name = {}
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            if asset["name"] in by_name:
                raise UpdateError("Release 存在重名资产")
            by_name[asset["name"]] = asset.get("browser_download_url")
    exe_url = by_name.get(exe_name)
    sha256_url = by_name.get(sha256_name)
    if not isinstance(exe_url, str) or not isinstance(sha256_url, str):
        raise UpdateError("Release 缺少与标签严格同名的 EXE 或 SHA-256 资产")
    for url in (exe_url, sha256_url):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise UpdateError("Release 资产必须使用 HTTPS")
    return AvailableUpdate(tag, exe_name, exe_url, sha256_name, sha256_url)


def _cancelled(cancel_event: Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _stream_download(url: str, part: Path, *, opener, cancel_event,
                     limit=None) -> str:
    if limit is None:
        limit = MAX_DOWNLOAD_BYTES
    if _cancelled(cancel_event):
        raise UpdateCancelled("已取消更新下载")
    digest = hashlib.sha256()
    count = 0
    try:
        with part.open("wb") as stream:
            with _open(_request(url), opener) as response:
                length = response.headers.get("Content-Length") if response.headers else None
                if length is not None:
                    try:
                        if int(length) > limit:
                            raise UpdateError("更新文件超过大小上限")
                    except ValueError:
                        pass
                while True:
                    if _cancelled(cancel_event):
                        raise UpdateCancelled("已取消更新下载")
                    chunk = response.read(min(1024 * 1024, limit - count + 1))
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > limit:
                        raise UpdateError("更新文件超过大小上限")
                    stream.write(chunk)
                    digest.update(chunk)
        if _cancelled(cancel_event):
            raise UpdateCancelled("已取消更新下载")
        return digest.hexdigest()
    except Exception:
        try:
            part.unlink()
        except FileNotFoundError:
            pass
        raise


def _parse_checksum(path: Path, exe_name: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise UpdateError("无法读取 SHA-256 资产") from error
    match = re.fullmatch(
        rf"([0-9a-fA-F]{{64}})  {re.escape(exe_name)}\r?\n?", text)
    if match is None:
        raise UpdateError("SHA-256 资产格式或文件名不符")
    return match.group(1).lower()


def download_update(available: AvailableUpdate, staged: Path, *, opener=None,
                    cancel_event: Event | None = None) -> DownloadedUpdate:
    opener = opener or _default_opener()
    staged = Path(staged)
    staged.parent.mkdir(parents=True, exist_ok=True)
    part = staged.with_name(staged.name + ".part")
    checksum = staged.with_name(staged.name + ".sha256")
    checksum_part = checksum.with_name(checksum.name + ".part")
    for path in (part, checksum, checksum_part):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        _stream_download(
            available.sha256_url, checksum_part, opener=opener, cancel_event=cancel_event,
            limit=MAX_SHA256_BYTES)
        os.replace(checksum_part, checksum)
        expected = _parse_checksum(checksum, available.exe_name)
        actual = _stream_download(
            available.exe_url, part, opener=opener, cancel_event=cancel_event)
        if not hmac.compare_digest(actual, expected):
            raise UpdateError("更新 EXE 的 SHA-256 校验失败")
        if _cancelled(cancel_event):
            raise UpdateCancelled("已取消更新下载")
        os.replace(part, staged)
        checksum.unlink()
        return DownloadedUpdate(available, staged, expected)
    finally:
        for path in (part, checksum, checksum_part):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _restart_application(executable: Path, *, cleanup=None) -> None:
    command = [str(executable)]
    if cleanup is not None:
        cleanup_pid, cleanup_path = cleanup
        command += ["--cleanup-update", str(cleanup_pid), str(cleanup_path)]
    kwargs = {"cwd": str(executable.parent), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(command, **kwargs)


def launch_update(staged: Path, expected_sha256: str, *, current_executable: Path | None = None,
                  pid: int | None = None, frozen: bool | None = None, temp_root: Path | None = None,
                  popen=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        raise UpdateError("非冻结开发环境只支持检查和下载，不替换 python.exe")
    staged = Path(staged).resolve()
    current = Path(current_executable or sys.executable).resolve()
    try:
        verify_sha256(staged, expected_sha256)
    except ValueError as error:
        raise UpdateError(str(error)) from error
    temp_dir = Path(tempfile.mkdtemp(prefix="bwpro-update-", dir=temp_root))
    copied = temp_dir / current.name
    try:
        shutil.copy2(current, copied)
        command = [str(copied), "--apply-update", str(pid or os.getpid()),
                   str(current), str(staged), expected_sha256.lower()]
        kwargs = {"cwd": str(temp_dir), "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return (popen or subprocess.Popen)(command, **kwargs)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def wait_for_process(pid: int, timeout: float = _WAIT_TIMEOUT) -> None:
    if os.name != "nt":
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= deadline:
                raise UpdateError("等待原程序退出超时")
            time.sleep(0.05)
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel.OpenProcess
    open_process.restype = wintypes.HANDLE
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = open_process(0x00100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return
        raise UpdateError(f"无法等待原程序退出（Windows 错误 {error}）")
    wait_handle = kernel.WaitForSingleObject
    wait_handle.restype = wintypes.DWORD
    wait_handle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    close_handle = kernel.CloseHandle
    close_handle.restype = wintypes.BOOL
    close_handle.argtypes = [wintypes.HANDLE]
    try:
        result = wait_handle(handle, max(0, int(timeout * 1000)))
        if result == 0x102:
            raise UpdateError("等待原程序退出超时")
        if result != 0:
            raise UpdateError(f"等待原程序退出失败（{result}）")
    finally:
        close_handle(handle)


def _updater_cleanup_location():
    if not getattr(sys, "frozen", False):
        return None
    return os.getpid(), Path(sys.executable).resolve().parent


def apply_update(pid: int, target: Path, staged: Path, expected_sha256: str, *,
                 wait=wait_for_process, restart=_restart_application) -> int:
    target = Path(target)
    staged = Path(staged)
    backup = target.with_name(target.name + ".bak")
    wait(pid)
    cleanup = None
    backed_up = False
    try:
        cleanup = _updater_cleanup_location()
        verify_sha256(staged, expected_sha256)
        os.replace(target, backup)
        backed_up = True
        os.replace(staged, target)
        restart(target, cleanup=cleanup)
    except Exception as error:
        try:
            if backed_up:
                if target.exists() and not staged.exists():
                    os.replace(target, staged)
                if backup.exists():
                    os.replace(backup, target)
            restart(target, cleanup=cleanup)
        except Exception as rollback_error:
            raise UpdateError("更新失败，且回滚或旧版重启失败") from rollback_error
        raise UpdateError("更新失败，已回滚并重启旧版本") from error
    try:
        backup.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        _LOGGER.warning("无法清理更新备份：%s", error)
    return 0


def cleanup_update_after_exit(pid: int, directory: Path, *, wait=wait_for_process) -> bool:
    try:
        directory = Path(directory)
        if not directory.name.startswith("bwpro-update-"):
            raise UpdateError("更新清理路径不符合临时目录命名")
        wait(pid, 10.0)
        if directory.exists():
            shutil.rmtree(directory)
        _LOGGER.info("已清理更新临时目录：%s", directory)
        return True
    except Exception as error:
        _LOGGER.warning("清理更新临时文件失败：%s：%s", directory, error)
        return False


def schedule_update_cleanup(pid: int, directory: Path):
    from threading import Thread

    try:
        worker = Thread(target=cleanup_update_after_exit, args=(pid, directory), daemon=True)
        worker.start()
        return worker
    except Exception as error:
        _LOGGER.warning("无法启动更新临时文件清理：%s", error)
        return None


def apply_update_command(arguments: list[str]) -> int:
    from core.logging_config import configure_logging

    logger = logging.getLogger("bwpro.update")
    try:
        log_path = configure_logging("update")
    except Exception:
        logger.exception("更新日志初始化失败；未执行等待、替换或重启")
        return 1
    try:
        if len(arguments) != 4:
            raise UpdateError("--apply-update 参数数量错误")
        logger.info("开始应用更新：pid=%s target=%s staged=%s",
                    arguments[0], arguments[1], arguments[2])
        result = apply_update(
            int(arguments[0]), Path(arguments[1]), Path(arguments[2]), arguments[3])
        logger.info("更新完成并请求重启")
        return result
    except Exception:
        logger.exception("自动更新失败；详见 %s", log_path)
        return 1
