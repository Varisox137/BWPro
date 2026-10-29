# 对战运行日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一记录玩家指令、引擎事件与实际原子 op，联机由服务端过滤后下发，并清理 PIL 与重复时间线日志。

**Architecture:** 引擎通过可选 `trace_sink` 产生结构化 trace，同时写本地 `bwpro.battle` logger。Room 将 trace 缓存在房间侧，复用 `state` 消息按视角过滤后增量下发；联机 GUI 只落盘服务端 trace，局内 timeline 仅用于显示。

**Tech Stack:** Python 3.14、logging、PySide6、FastAPI/WebSocket、pytest。

## Global Constraints

- 日志文件名为 `bwpro-YYYYMMDD-HHMMSS-PID.log`，默认目录为项目根目录 `logs/`。
- PIL 仅保留 WARNING 及以上；条件不满足而未执行的 step 不记录。
- 联机客户端只上传 cmd，不在本地重建事件/op；私有手牌、牌库与选择信息不得泄露。
- 测试命令：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`。
- 每次只暂存本任务明确列出的文件，避免混入当前工作区的其他未提交修改。

---

### Task 1: 日志命名、PIL 降噪与重复时间线清理

**Files:**
- Modify: `core/logging_config.py`
- Modify: `client/gui/battle.py`
- Modify: `tests/test_logging_config.py`
- Modify: `tests/test_gui_battle.py`
- Modify: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: 现有 `configure_logging(component, log_dir)` 与 `HotseatView.play_next_timeline()`。
- Produces: 新文件名 `bwpro-YYYYMMDD-HHMMSS-PID.log`；timeline 不再经 GUI 写入 `bwpro.battle`。

- [ ] **Step 1: 写失败测试**

把 `tests/test_logging_config.py` 的文件名断言改为新格式，并增加 PIL 降噪断言：

```python
assert re.fullmatch(r"bwpro-\d{8}-\d{6}-\d+\.log", path.name)
logging.getLogger("PIL.PngImagePlugin").debug("STREAM 调试噪声")
for handler in logging.getLogger().handlers:
    handler.flush()
contents = path.read_text(encoding="utf-8")
assert "STREAM 调试噪声" not in contents
```

把 `tests/test_gui_battle.py::test_battle_timeline_written_to_application_log` 与 `tests/test_gui_online.py::test_online_timeline_written_to_application_log` 分别改为断言记录中不含 `HotseatView` / `OnlineBattleView` 前缀的 timeline 文本。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_logging_config.py tests/test_gui_battle.py::test_battle_timeline_written_to_application_log tests/test_gui_online.py::test_online_timeline_written_to_application_log`
Expected: 文件名、PIL 或 timeline 去重断言失败。

- [ ] **Step 3: 最小实现**

在 `core/logging_config.py` 中保留 `component` 参数与启动记录，但文件名改为：

```python
import os

_LOG_PATTERNS = ("bwpro-*.log", "bwpro_*.log")
path = log_dir / f"bwpro-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log"
logging.getLogger("PIL").setLevel(logging.WARNING)
```

让 `_cleanup_logs` 同时清理新旧两种命名。删除 `client/gui/battle.py` 的 `import logging` 及 `play_next_timeline` 中的 `logging.getLogger("bwpro.battle").info(...)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_logging_config.py tests/test_gui_battle.py::test_battle_timeline_written_to_application_log tests/test_gui_online.py::test_online_timeline_written_to_application_log`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add core/logging_config.py client/gui/battle.py tests/test_logging_config.py tests/test_gui_battle.py tests/test_gui_online.py
git commit -m "fix(日志): 统一文件命名并清理重复噪声"
```

---

### Task 2: 引擎统一产生 cmd/event/op trace

**Files:**
- Create: `tests/test_runtime_trace.py`
- Modify: `core/engine.py:189-192,1147-1188,5801-5818,6481-6544`
- Modify: `core/setup.py:65-103`

**Interfaces:**
- Consumes: 现有 `Game.apply`、`Game.emit`、`Game._run_step`。
- Produces: `Game(state, db, seed=0, trace_sink=None)`、`Game._trace(kind, message, owner=None, seq=None, summary=None)`；`new_game(..., trace_sink=None)` 透传同一 sink。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_runtime_trace.py`，覆盖三类记录与跳过条件：

```python
import logging
from core.model import ExecContext, Ref
from tests import factories as F


def test_command_event_and_actual_op_trace(make_game, caplog):
    game = make_game(auto_skip_upgrade=False)
    with caplog.at_level(logging.INFO, logger="bwpro.battle"):
        game.apply({"op": "upgrade", "index": 1})
        game.emit("on_turn_start", player=0)
        ctx = ExecContext(controller=0, source=Ref(player=0, shikigami=0))
        game._run_step(F.Step(op="damage", amount=1,
                              target=F.T(kind="all", pool="enemy_player")), ctx)
        game._run_step(F.Step(op="damage", amount=1, condition={"orb_ge": 99},
                              target=F.T(kind="all", pool="enemy_player")), ctx)
    text = caplog.text
    assert '"op": "upgrade"' in text
    assert "on_turn_start" in text and "player" in text
    assert '"op": "damage"' in text and '"amount": 1' in text
    assert text.count('"op": "damage"') == 1


def test_trace_sink_receives_structured_entries(make_game):
    entries = []
    game = make_game(auto_skip_upgrade=False, trace_sink=entries.append)
    game.apply({"op": "upgrade", "index": 1})
    assert entries[0]["kind"] == "cmd"
    assert entries[0]["owner"] == 0
    assert "upgrade" in entries[0]["message"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_runtime_trace.py`
Expected: `trace_sink` 参数不存在，且 `bwpro.battle` 中没有所需记录。

- [ ] **Step 3: 最小实现**

在 `Game.__init__` 增加 `trace_sink=None` 并保存；在 `core/setup.py` 增加同名可选参数并传给 `Game`。在引擎增加：

```python
import logging


def _trace(self, kind, message, *, owner=None, seq=None, summary=None):
    logging.getLogger("bwpro.battle").info(
        "%s seq=%s owner=%s：%s", kind, seq, owner, message)
    if self.trace_sink is not None:
        entry = {"kind": kind, "message": str(message), "owner": owner}
        if seq is not None:
            entry["seq"] = seq
        if summary is not None:
            entry["summary"] = summary
        self.trace_sink(entry)
```

在 `apply` 取得 `op` 后立即记录完整 cmd；在 `emit` 正常分配序号后记录 name/payload，终局早退前以 `seq=None` 记录；在 `_run_step` 调用 `fn(...)` 前记录实际 `step.op`、解析后的 `params`、`refs` 与 `ctx.controller/source/card_uid/event`。op 的 owner 使用 `ctx.controller`，cmd 的 owner 使用 `cmd.get("player", self.state.active)`；event 可从 `player` 或 `source: Ref` 推导 owner，并传 `summary=name`。

- [ ] **Step 4: 运行测试确认通过**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_runtime_trace.py tests/test_engine.py`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_runtime_trace.py core/engine.py core/setup.py
git commit -m "feat(日志): 记录指令事件与实际原子动作"
```

---

### Task 3: 服务端缓存、脱敏并随 state 下发 trace

**Files:**
- Modify: `server/protocol.py:82-97`
- Modify: `server/room.py:165-173,390-405,472-499`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `Game._trace(...)` 产生的 `{kind, message, owner, seq?, summary?}`。
- Produces: `sanitize_trace(entry, viewer) -> dict | None`；`protocol.state(..., trace=None)`；Room 的 `_trace_pending` 增量队列。

- [ ] **Step 1: 写失败测试**

在 `tests/test_server.py` 增加：

```python
from server.room import sanitize_trace


def test_trace_sanitized_for_viewer():
    private = {"kind": "op", "message": "私密伤害牌", "owner": 0}
    public = {"kind": "event", "message": "完整私有载荷",
              "summary": "on_damage", "owner": None, "seq": 8}
    assert sanitize_trace(private, 1) is None
    assert sanitize_trace(private, 0)["message"] == "私密伤害牌"
    visible = sanitize_trace(public, 1)
    assert visible["message"] == "on_damage" and visible["seq"] == 8


def test_room_broadcasts_server_trace(db):
    async def go():
        room, ws0, ws1 = await _started_room(db)
        viewer = room.seat_to_player[0]
        room.game._trace("op", "服务端原子动作", owner=viewer)
        await room.broadcast_state()
        msg = [m for m in ws0.messages if m["type"] == "state"][-1]
        assert msg["trace"][-1]["message"] == "服务端原子动作"
    run(go())
```

同时给 `test_server_message_builders` 增加 `trace=[{"kind": "event"}]` 字段断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_server.py::test_trace_sanitized_for_viewer tests/test_server.py::test_room_broadcasts_server_trace`
Expected: `sanitize_trace` 不存在且 state 无 `trace` 字段。

- [ ] **Step 3: 最小实现**

在 `server/protocol.py` 给 `state` 增加可选 `trace`，非空时写入消息。Room 初始化 `_trace_pending = []`，开局时向 `new_game(..., trace_sink=self._trace_pending.append)` 透传。`broadcast_state` 取并清空增量，对每方过滤后传给 `protocol.state(..., trace=vtrace)`；resync 不重放 trace，避免客户端重复落盘。

```python
def sanitize_trace(entry, viewer):
    owner = entry.get("owner")
    if owner is not None and owner != viewer:
        return None
    if owner is None:
        entry = dict(entry)
        entry["message"] = entry.get("summary", entry["kind"])
    return entry
```

公共 event 仅下发 summary；owner 匹配时才下发完整 message，防止公共载荷夹带私有卡牌信息。

- [ ] **Step 4: 运行测试确认通过**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_server.py`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add server/protocol.py server/room.py tests/test_server.py
git commit -m "feat(联机): 服务端按视角下发对战追踪"
```

---

### Task 4: 联机客户端接收 trace 并完成文档与全量验证

**Files:**
- Modify: `client/gui/online.py:85-99,587-634`
- Modify: `tests/test_gui_online.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `docs/rules.md`

**Interfaces:**
- Consumes: state 消息中的 `trace: [{kind, message, owner, seq?, summary?}]`。
- Produces: `OnlineBattleView.receive_trace(entries)`，仅将服务端条目写入 `bwpro.battle`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_gui_online.py` 新增：

```python
def test_online_writes_only_server_trace(qapp, db, make_game, caplog):
    import logging

    battle = OnlineBattleView(db, send_command=lambda _cmd: None)
    with caplog.at_level(logging.INFO, logger="bwpro.battle"):
        battle.receive_trace([{"kind": "op", "message": "服务端 op", "owner": 0}])
    assert any("服务端 op" in record.message for record in caplog.records)
    battle.close()
```

保留 Task 1 的 timeline 去重断言，确认联机 GUI 不自行生成事件/op 日志。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_online.py::test_online_writes_only_server_trace`
Expected: `receive_trace` 不存在。

- [ ] **Step 3: 最小实现与文档同步**

在 `OnlineBattleView` 增加：

```python
def receive_trace(self, entries) -> None:
    for entry in entries:
        logging.getLogger("bwpro.battle").info(
            "服务端 trace %s seq=%s：%s",
            entry.get("kind"), entry.get("seq"), entry.get("message", ""))
```

在 `OnlineView.handle_message` 的 `kind == "state"` 分支调用 `self.battle.receive_trace(msg.get("trace") or [])`。更新 `docs/gui-design.md`、`docs/gui-plan.md` 为服务端 trace 说明；在 `docs/rules.md` 日志节补充新文件名、cmd/event/op 与隐私过滤口径。

- [ ] **Step 4: 运行相关及全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_logging_config.py tests/test_runtime_trace.py tests/test_server.py tests/test_gui_online.py tests/test_gui_battle.py`
Expected: 全部 PASS。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS；若当前工作区包含本计划之外的修改，也一并确认没有回归。

- [ ] **Step 5: Commit**

```bash
git add client/gui/online.py tests/test_gui_online.py docs/gui-design.md docs/gui-plan.md docs/rules.md
git commit -m "feat(gui): 接收联机对战追踪并完善日志文档"
```
