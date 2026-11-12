# 服务端详细日志与独立运维端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为远程服务端补充可排障的详细日志，并提供带轮换提取码鉴权的日志列表、预览、下载 API 与独立 PySide6 运维 GUI。

**Architecture:** `server/log_admin.py` 独立管理提取码和日志文件访问，`server/main.py` 只负责 HTTP 鉴权与路由；`client/log_admin.py` 使用标准库 HTTP 客户端和 Qt 后台线程，不加载游戏数据库。引擎继续产生 `bwpro.battle` 追踪，服务端只补连接和房间上下文。

**Tech Stack:** Python 3.14、FastAPI、现有 logging、PySide6、pytest、标准库 `urllib.request` / `secrets` / `hmac`。

## Global Constraints

- 提取码为 16 位小写十六进制，每 30 分钟轮换，旧码立即失效。
- 提取码可显示在交互终端，但不得进入应用或 launcher 日志；同时写入 `logs/.log-access-token`，权限为 `0o600`。
- API 使用 `Authorization: Bearer <code>`，不得在 URL 中携带提取码；只允许访问符合既有命名规则的日志。
- 运维 GUI 不加载卡牌数据库或卡图；主游戏客户端不增加自动下载行为。
- Termux 服务端依赖不变，不引入 PySide6；不新增第三方 Python 依赖。
- 测试命令：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`；GUI 测试前缀增加 `QT_QPA_PLATFORM=offscreen`。
- 所有 git commit 均需用户明确批准；提交信息使用中文 conventional 格式。

---

### Task 1: 提取码与日志文件服务

**Files:**
- Create: `server/log_admin.py`
- Create: `tests/test_server_log_admin.py`
- Modify: `core/logging_config.py`

**Interfaces:**
- Produces: `LogAdminService(log_dir: Path, current_log: Path, rotate_seconds: float = 1800.0)`。
- Produces: `service.token -> str`、`service.rotate() -> str`、`service.list_logs() -> list[dict]`、`service.preview(name: str) -> tuple[str, bool]`、`service.log_path(name: str) -> Path`。
- Produces: `core.logging_config.write_terminal_secret(text: str) -> bool`，仅向交互终端写秘密，成功返回 `True`。

- [ ] **Step 1: 写提取码轮换与文件访问失败测试**

```python
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
    assert [x["name"] for x in service.list_logs()] == sorted(
        x["name"] for x in service.list_logs())
    assert {x["name"] for x in service.list_logs()} == {
        current.name, "bwpro-launcher-20261111-115959-2.log"}
    assert next(x for x in service.list_logs() if x["current"])["name"] == current.name
```

```python
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
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server_log_admin.py`
Expected: FAIL，提示 `server.log_admin` 或 `write_terminal_secret` 不存在。

- [ ] **Step 3: 实现最小日志服务**

```python
# server/log_admin.py 的核心结构
LOG_PATTERNS = ("bwpro-*.log", "bwpro_*.log")
PREVIEW_BYTES = 512 * 1024

class LogAdminService:
    def __init__(self, log_dir: Path, current_log: Path, rotate_seconds: float = 1800.0):
        self.log_dir = log_dir
        self.current_log = current_log
        self.rotate_seconds = rotate_seconds
        self._token = ""
        self.rotate()

    def rotate(self) -> str:
        self._token = secrets.token_hex(8)
        path = self.log_dir / ".log-access-token"
        path.write_text(self._token + "\n", encoding="ascii")
        path.chmod(0o600)
        if not write_terminal_secret(f"日志提取码：{self._token}"):
            print(f"日志提取码已写入：{path}", flush=True)
        return self._token
```

`list_logs()` 合并两种 glob、按文件名排序并返回 `name/mtime/size/current`；`log_path()` 只接受当前 glob 结果中的纯文件名；`preview()` 用二进制读取 `PREVIEW_BYTES + 1`，以 `errors="replace"` 解码并返回截断标记。

```python
# core/logging_config.py
def write_terminal_secret(text: str) -> bool:
    target = "CON" if os.name == "nt" else "/dev/tty"
    try:
        with open(target, "w", encoding="utf-8") as terminal:
            terminal.write(text + "\n")
            terminal.flush()
        return True
    except OSError:
        return False
```

- [ ] **Step 4: 运行服务测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server_log_admin.py tests/test_logging_config.py`
Expected: PASS。

- [ ] **Step 5: 经用户批准后提交**

```bash
git add server/log_admin.py core/logging_config.py tests/test_server_log_admin.py docs/superpowers/specs/2026-11-11-server-log-admin-design.md docs/superpowers/plans/2026-11-11-server-log-admin.md
git commit -m "feat(服务端): 添加日志提取码与文件服务"
```

### Task 2: 鉴权 HTTP API 与定时轮换

**Files:**
- Modify: `server/main.py`
- Modify: `server/log_admin.py`
- Test: `tests/test_server_log_admin.py`

**Interfaces:**
- Consumes: Task 1 的 `LogAdminService`。
- Produces: `GET /api/log-admin/logs`、`GET /api/log-admin/logs/{name}/preview`、`GET /api/log-admin/logs/{name}/download`。
- Produces: `LogAdminService.authenticate(header: str | None, client: str) -> bool` 与 `LogAdminService.rotation_loop()`。

- [ ] **Step 1: 写 API 鉴权、轮换和路径失败测试**

使用 FastAPI `TestClient` 和临时日志目录，显式把服务传给 `create_app(..., log_admin=service)`：

```python
def test_log_admin_api_auth_preview_and_download(tmp_path):
    service, client = make_log_admin_client(tmp_path)
    assert client.get("/api/log-admin/logs").status_code == 401
    headers = {"Authorization": f"Bearer {service.token}"}
    listed = client.get("/api/log-admin/logs", headers=headers)
    assert listed.status_code == 200
    name = listed.json()["logs"][0]["name"]
    assert client.get(f"/api/log-admin/logs/{name}/preview", headers=headers).status_code == 200
    assert client.get(f"/api/log-admin/logs/{name}/download", headers=headers).status_code == 200
    assert client.get("/api/log-admin/logs/../secret", headers=headers).status_code in (400, 404)
```

```python
def test_rotation_invalidates_old_token(tmp_path):
    async def scenario():
        service = make_service(tmp_path, rotate_seconds=0.01)
        old = service.token
        task = asyncio.create_task(service.rotation_loop())
        await asyncio.sleep(0.03)
        task.cancel()
        assert service.token != old
        assert not service.authenticate(f"Bearer {old}", "test")
    asyncio.run(scenario())
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server_log_admin.py`
Expected: FAIL，API 目前被 catch-all 拒绝且没有轮换方法。

- [ ] **Step 3: 实现鉴权和路由**

```python
def authenticate(self, header: str | None, client: str) -> bool:
    if self._throttled(client):
        return False
    expected = f"Bearer {self._token}"
    valid = header is not None and hmac.compare_digest(header, expected)
    self._record_auth_result(client, valid)
    return valid
```

鉴权失败按来源记录最近 60 秒内的失败时间，第 5 次失败后暂时拒绝；成功时清除该来源失败记录。所有鉴权失败统一返回 401 空体。`rotation_loop()` 使用 `asyncio.sleep(self.rotate_seconds)` 后调用 `rotate()`，由既有 lifespan 创建并在退出时取消。

路由依赖从 `request.headers.get("Authorization")` 和 `_client_ip(request)` 取鉴权上下文；预览返回 `{"text": text, "truncated": truncated}`，下载使用 `FileResponse(path, filename=name)`。`create_app` 增加可选 `log_admin=None`，缺省不注册管理接口，避免既有测试和嵌入方意外开放日志。

`main()` 接收 `log_path = configure_logging("server")`，创建 `LogAdminService(log_path.parent, log_path)` 并传入 `create_app`。

- [ ] **Step 4: 运行 API 与既有服务端测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server_log_admin.py tests/test_server.py`
Expected: PASS。

- [ ] **Step 5: 经用户批准后提交**

```bash
git add server/main.py server/log_admin.py tests/test_server_log_admin.py
git commit -m "feat(服务端): 开放鉴权日志管理接口"
```

### Task 3: 补齐联机排障上下文

**Files:**
- Modify: `server/main.py`
- Modify: `server/room.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: 引擎现有 `bwpro.battle` INFO 追踪。
- Produces: 连接关闭码/原因、非法指令拒绝、房间指令上下文与异常堆栈日志；不改变网络协议。

- [ ] **Step 1: 写连接关闭和房间上下文日志测试**

```python
def test_websocket_disconnect_logs_code(server, caplog):
    with caplog.at_level(logging.INFO, logger="bwpro.server"):
        client = WsClient()
        client.ws.close(code=1000)
        for _ in range(50):
            if "关闭码=1000" in caplog.text:
                break
            time.sleep(0.02)
    assert "关闭码=1000" in caplog.text
```

```python
def test_rejected_command_logs_room_context(db, caplog):
    room, _ws0, _ws1 = run(_started_room(db))
    seat = next(s for s in (0, 1)
                if room.seat_to_player[s] != room.game.state.active)
    with caplog.at_level(logging.INFO, logger="bwpro.room"):
        run(room.handle_cmd(seat, {"op": "end_turn"}))
    assert room.id in caplog.text
    assert "end_turn" in caplog.text
    assert "还没到你的回合" in caplog.text
```

```python
def test_log_admin_token_not_captured(tmp_path, monkeypatch):
    path = configure_logging("test", log_dir=tmp_path)
    monkeypatch.setattr("server.log_admin.write_terminal_secret", lambda text: True)
    try:
        service = LogAdminService(tmp_path, path)
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert service.token not in path.read_text(encoding="utf-8")
    finally:
        restore_output()
```

- [ ] **Step 2: 运行目标测试并确认新增断言失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server.py -k "log or disconnect"`
Expected: 新测试 FAIL，既有测试 PASS。

- [ ] **Step 3: 添加结构化上下文日志**

在 `Room` 使用 `logging.getLogger("bwpro.room")`；`_log()` 保留现有控制台格式并改用 logger。`_apply_and_broadcast()` 在引擎异常时用 `logger.exception("房间 %s 引擎异常，对局终止", self.id)`，非法指令记录房间、座位、op 和原因。玩家正常指令与原子事件继续由 `Game._trace` 记录，避免重复。

在 `ws_endpoint` 的 `WebSocketDisconnect as error` 分支记录来源、房间和 `error.code`；正常离开记录 1000。提取码只经 `/dev/tty`/`CON` 输出，不调用普通 `print(token)`。

- [ ] **Step 4: 运行联机与日志测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server.py tests/test_server_log_admin.py tests/test_logging_config.py`
Expected: PASS。

- [ ] **Step 5: 经用户批准后提交**

```bash
git add server/main.py server/room.py tests/test_server.py
git commit -m "feat(服务端): 完善联机排障日志"
```

### Task 4: 独立 PySide6 日志运维端

**Files:**
- Create: `client/log_admin.py`
- Create: `tests/test_log_admin.py`

**Interfaces:**
- Consumes: Task 2 的三个 HTTP API。
- Produces: `normalize_admin_url(raw: str) -> str`、`LogAdminClient(base_url: str, token: str)`、`LogAdminWindow`。
- Produces: `LogAdminClient.list_logs() -> list[dict]`、`preview(name: str) -> dict`、`download(name: str, destination: Path) -> Path`。
- Produces: `python -m client.log_admin` 入口。

- [ ] **Step 1: 写 URL、HTTP 与 GUI 失败测试**

```python
@pytest.mark.parametrize(("raw", "expected"), [
    ("127.0.0.1", "http://127.0.0.1:1037"),
    ("localhost:1037", "http://localhost:1037"),
    ("https://bwpro.example", "https://bwpro.example"),
    ("wss://bwpro.example/ws", "https://bwpro.example"),
])
def test_normalize_admin_url(raw, expected):
    assert normalize_admin_url(raw) == expected
```

用本地 `http.server.ThreadingHTTPServer` 测试请求头、列表、预览和下载：

```python
def test_client_downloads_selected_log(server, tmp_path):
    client = LogAdminClient(server.url, "0123456789abcdef")
    target = client.download("bwpro-test.log", tmp_path)
    assert target.read_text(encoding="utf-8") == "日志内容"
    assert server.last_headers["Authorization"] == "Bearer 0123456789abcdef"
```

offscreen 实例化 `LogAdminWindow`，注入 fake client，验证列表选择、预览只读、多选下载与错误提示；网络函数通过 `QSignalSpy` 或 Qt 事件循环等待完成后断言。

- [ ] **Step 2: 运行测试并确认失败**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_log_admin.py`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 HTTP 客户端**

`normalize_admin_url` 接受本机裸地址、host:port、http(s) 和 ws(s)，移除尾部 `/ws` 与 `/`，本机缺省端口为 1037。`LogAdminClient` 使用 `urllib.request.Request`，所有请求添加 Bearer 头，超时 10 秒；HTTP 401 转成 `PermissionError("提取码无效或已轮换")`，其他网络错误转成带服务器地址的 `RuntimeError`。下载采用流式复制到目标目录，拒绝服务端返回的非日志文件名。

- [ ] **Step 4: 实现非阻塞 GUI**

界面包含服务器地址、提取码密码框、连接按钮、日志表格、只读预览编辑框和下载按钮。表格列为文件名、修改时间、大小、当前；开启整行选择和扩展多选。连接、预览、下载均放入 `threading.Thread(daemon=True)`，通过 `Signal` 回到 GUI 线程；请求期间只禁用对应按钮，不冻结窗口。下载目录由 `QFileDialog.getExistingDirectory` 选择，成功状态显示实际保存路径。

- [ ] **Step 5: 运行运维端及相关客户端测试**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_log_admin.py tests/test_gui_online.py tests/test_client.py`
Expected: PASS。

- [ ] **Step 6: 经用户批准后提交**

```bash
git add client/log_admin.py tests/test_log_admin.py
git commit -m "feat(运维): 添加独立服务器日志管理界面"
```

### Task 5: 文档与端到端验收

**Files:**
- Modify: `server/README.md`
- Modify: `docs/gui-design.md`
- Modify: `docs/superpowers/specs/2026-11-11-server-log-admin-design.md`（仅当实现与确认设计有事实差异时）

**Interfaces:**
- Consumes: 前四项任务的最终实现。
- Produces: 可复制执行的 Termux 提取码获取、运维端启动、列表/预览/下载及安全说明。

- [ ] **Step 1: 更新使用文档**

文档明确写入：

```bash
# Termux 服务端
cat logs/.log-access-token

# Windows 开发机独立运维端
uv run python -m client.log_admin
```

说明 30 分钟轮换、旧码失效、控制台直接显示但日志不保存、公网使用 HTTPS，以及 Termux 服务端不需要 GUI 依赖。

- [ ] **Step 2: 做进程级 HTTP 冒烟**

启动绑定 127.0.0.1 的临时服务端，用 `LogAdminClient` 完成列表、当前日志预览与下载；随后关闭服务端。断言下载文件非空且日志不含当前提取码。

- [ ] **Step 3: 运行最终验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_server.py tests/test_server_log_admin.py tests/test_logging_config.py`
Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_log_admin.py tests/test_gui_online.py tests/test_client.py`
Run: `git diff --check`
Expected: 全部 PASS，无空白错误。

- [ ] **Step 4: 经用户批准后提交并推送**

```bash
git add server/README.md docs/gui-design.md docs/superpowers/specs/2026-11-11-server-log-admin-design.md
git commit -m "docs(运维): 补充远程日志管理说明"
git push
```
