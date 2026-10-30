# 卡图缓存复用与后台预热 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 DIY 非渲染更新完整复用卡图缓存，并将失效卡图的启动预热改为不阻塞 GUI 的分片后台任务。

**Architecture:** `cardart` 用 assets 与渲染源码内容摘要替代版本号；`prewarm` 提供同步/迭代共用的生成器并记录真实成功与失败；`MainWindow` 用 `QTimer` 在 GUI 线程分片消费同一生成器。保留现有 PNG 原子写入、按需渲染和设置页全量重建。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计唯一来源：`docs/superpowers/specs/2026-10-30-cardart-cache-design.md`。
- 仅版本号、WebGUI、编辑器、发布说明变化时缓存全部复用；不得再把 `bwpdiy.__version__` 写入缓存键或清单相等条件。
- 所有 `QPixmap` 仍在 GUI 线程创建和使用，不把 Qt 图元交给工作线程。
- 后台预热不使用模态全屏遮罩；同一时刻只允许一个预热任务运行。
- 失败项不得形成完整成功清单，已成功 PNG 保留，下次启动重试失败项。
- 所有新行为先写失败测试并实际确认 RED，再最小实现到 GREEN。
- Windows 测试使用主仓库解释器；需要真实卡图时设置 `BWP_DIY_ROOT='D:/Programming/BWPDIY'` 和 `BWP_DIY_LIBRARY='D:/Programming/BWPro/library'`。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 用渲染内容摘要替代版本号

**Files:**
- Modify: `client/gui/cardart.py:184-237,320-465,615-650,736-760`
- Modify: `client/gui/prewarm.py:27-51,91-115`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_prewarm.py`

**Interfaces:**
- Consumes: 现有 `_renderer_resources()`、`_entity_renderer_resources()` 和 `_card_cache_key()`。
- Produces: `_renderer_source_digest(assets) -> str` 与 `_card_renderer_resources(assets, cache_context=None) -> str`；`_card_cache_key()` 不再接收 `renderer_version`。

- [ ] **Step 1: 写版本无关与源码失效失败测试**

在 `tests/test_gui_builder.py` 增加直接缓存键测试：固定 payload/layout/config/art/resources/root/height，调用新旧签名时不得再传版本；两次仅 monkeypatch `bwpdiy.__version__` 的调用必须得到相同 key，改变 `_card_renderer_resources` 返回值必须得到不同 key。另增加源码摘要测试：修改 assets 同级 `bwpdiy/render/pipeline.py` 后 `_renderer_source_digest` 改变，修改 `editor.html` 后不变。

在 `tests/test_gui_prewarm.py` 的 manifest 测试增加：

```python
assert "renderer_version" not in manifest
assert manifest["renderer_resources"]
assert manifest["entity_renderer_resources"]
```

新增 `test_prewarm_version_bump_does_not_invalidate_manifest`：第一次预热后读取 manifest，额外写入 `renderer_version: "0.0.0"` 模拟旧版本清单；第二次仍满足 `_manifest_current` 且 `card_pixmap/entity_pixmap` 调用次数为零。旧实现会把该额外字段与当前版本比较而失效，新实现应忽略它。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_prewarm.py -k 'cache_key or source_digest or version_bump or writes_manifest'`
Expected: 缓存键仍要求/包含版本，manifest 仍含 `renderer_version`。

- [ ] **Step 3: 最小实现共享源码摘要**

从 `_entity_renderer_resources` 提取：

```python
def _renderer_source_digest(assets: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((assets.parent / "bwpdiy" / "render").rglob("*.py")):
        digest.update(str(path).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()
```

新增 `_card_renderer_resources`：对 `_renderer_resources(...)` 与 `_renderer_source_digest(...)` 的组合做 SHA-256，并在 `cache_context["card_renderer_resources"]` 缓存。`_entity_renderer_resources` 复用同一源码摘要 helper，保持现有键名。

大卡 `_card_pixmap_impl` 使用 `_card_renderer_resources`，小卡继续使用 `_entity_renderer_resources`。从 `_card_cache_key` 删除 `renderer_version` 参数和 `key_data["bwpdiy_version"]`，同步两个调用点并删除局部 `from bwpdiy import __version__`。

- [ ] **Step 4: 更新清单并运行相关测试**

`prewarm` 删除 `_renderer_version()`，manifest `version` 升为 5，`renderer_resources` 改用 `_card_renderer_resources`；`_manifest_current` 不再比较 `renderer_version`。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_prewarm.py -k 'cache_key or source_digest or version_bump or writes_manifest or unchanged_manifest'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/cardart.py client/gui/prewarm.py tests/test_gui_builder.py tests/test_gui_prewarm.py
git commit -m "perf(gui): 按渲染内容复用卡图缓存"
git push
```

---

### Task 2: 迭代预热与真实失败状态

**Files:**
- Modify: `client/gui/prewarm.py`
- Modify: `client/gui/settings.py:36-62`
- Test: `tests/test_gui_prewarm.py`

**Interfaces:**
- Consumes: Task 1 的内容摘要和现有 `prewarm_all()`。
- Produces: `prewarm_iter(...) -> Iterator[tuple[int, int]]`（return value 为成功 entries）；`prewarm_all()` 保持原签名与同步返回；manifest 增加 `stats` 和 `failures`。

- [ ] **Step 1: 写失败重试与路径转发测试**

新增 `test_prewarm_failure_is_not_a_success_manifest`：令一个 `card_pixmap` 返回 `None`，其他返回有效 `QPixmap(2, 2)`；第一次后 manifest 的 `entries` 只含成功项、`failures` 含失败 id，`stats["failed"] == 1`。恢复成功后第二次必须再次调用失败项，且最终 failures 为空。

新增 `test_prewarm_forwards_explicit_paths`：

```python
prewarm_all(db, tmp_path / "library", tmp_path / "cache")
for call in calls:
    kwargs = call[2]
    assert kwargs["library_dir"] == tmp_path / "library"
    assert kwargs["cache_dir"] == tmp_path / "cache"
```

增加迭代接口测试：逐步 `next(iterator)` 得到 `(1, 2)`、`(2, 2)`，捕获 `StopIteration.value` 为成功 entries；同步 `prewarm_all` 的既有测试保持通过。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py -k 'failure or forwards or iter'`
Expected: 无迭代接口、路径未转发、失败仍写完整 entries。

- [ ] **Step 3: 提取共享生成器**

将现有定义扫描、manifest 构建和渲染循环提取为 `prewarm_iter`。同步入口只负责消费：

```python
def prewarm_all(db, library_dir=None, cache_dir=None,
                on_progress=None, clear=False):
    iterator = prewarm_iter(db, library_dir, cache_dir, clear=clear)
    while True:
        try:
            current, total = next(iterator)
        except StopIteration as stop:
            return stop.value
        if on_progress is not None:
            on_progress(current, total)
```

生成器在完整有效清单时 `yield (len(entries), len(definitions))` 后返回；否则逐项调用渲染并 yield 当前进度。显式 `library_dir/cache_dir` 同时传给 `card_pixmap` 和 `entity_pixmap`。

- [ ] **Step 4: 记录成功、失败并更新设置页**

每次渲染检查 `pixmap is not None and not pixmap.isNull()`。成功时保留对应 entry；失败时写入 `{"kind", "id"}` 到 failures 并 `logger.error("卡图预热失败：%s %s", kind, definition.id)`。完成时：

```python
manifest["entries"] = successful_entries
manifest["failures"] = failures
manifest["stats"] = {
    "total": len(definitions),
    "succeeded": len(successful_entries),
    "failed": len(failures),
    "skipped": 0,
}
```

`_manifest_current` 额外要求当前 `failures` 为空。设置页优先读取 stats，显示总数、成功和失败；无 stats 的旧 manifest 继续按 entries 显示，保持兼容。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/prewarm.py client/gui/settings.py tests/test_gui_prewarm.py
git commit -m "fix(gui): 记录卡图预热真实结果"
git push
```

---

### Task 3: QTimer 分片后台预热

**Files:**
- Modify: `client/gui/app.py:1-15,155-176,229-238,282-288`
- Modify: `client/gui/settings.py:46-62`
- Test: `tests/test_gui_prewarm.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: Task 2 `prewarm_iter()` 的进度 yield 与 StopIteration.value。
- Produces: `MainWindow.prewarm_resources()` 启动单次 QTimer 任务；`MainWindow._prewarm_timer`、`_prewarm_iterator` 用于状态检查与关闭清理。

- [ ] **Step 1: 写后台响应与单任务失败测试**

替换旧 startup 测试：monkeypatch `client.gui.app.prewarm_iter` 返回一个三次 yield 后结束的生成器，调用 `win.prewarm_resources()` 后立即断言主窗口未显示 loading overlay、`statusBar()` 可见或进度已启动；逐次 `qapp.processEvents()` 驱动 timer，期间点击主菜单按钮并确认页面可切换。结束后断言 iterator 被消费、timer 停止、状态栏进度清除。

增加：

```python
win.prewarm_resources()
first_timer = win._prewarm_timer
win.prewarm_resources()
assert win._prewarm_timer is first_timer
```

设置页在 timer 活跃时调用 `rebuild()`，断言不启动同步 `prewarm_all`，并显示“后台预热进行中”。关闭窗口前启动任务，`closeEvent` 后 timer 不再活跃。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py -k 'startup or background or rebuild'`
Expected: 启动仍同步调用 `prewarm_all` 并显示遮罩，无单任务/关闭清理。

- [ ] **Step 3: 实现 QTimer 分片消费**

`MainWindow` 初始化 `_prewarm_timer = QTimer(self)`、`setInterval(0)`、`_prewarm_iterator = None`，timeout 连接 `_advance_prewarm`。`prewarm_resources()` 仅在 timer 非活跃时创建 `prewarm_iter(self.db)` 并 start，不再启动 loading overlay。

每次 `_advance_prewarm` 消费一个定义：

```python
try:
    current, total = next(self._prewarm_iterator)
except StopIteration:
    self._finish_prewarm()
else:
    self.statusBar().showMessage(f"卡图后台同步 {current}/{total}")
```

`_finish_prewarm()` stop timer、清空 iterator、清除状态栏，并刷新设置页状态。`closeEvent` 先 stop 并清空，再走现有页面清理。所有迭代和 QPixmap 创建仍位于 GUI 线程。

- [ ] **Step 4: 防止手动重建并发并更新文档**

`SettingsView.rebuild()` 通过 `timer = getattr(self.window(), "_prewarm_timer", None)` 获取后台任务；`timer is not None and timer.isActive()` 时仅提示并返回，非活跃时保持原确认和同步全量重建。`docs/gui-design.md` 与 `docs/gui-plan.md` 记录版本无关缓存、后台进度和失败重试口径。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py`
Expected: 全部 PASS。

- [ ] **Step 5: 全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/app.py client/gui/settings.py tests/test_gui_prewarm.py docs/gui-design.md docs/gui-plan.md
git commit -m "perf(gui): 后台分片预热卡图资源"
git push
```
