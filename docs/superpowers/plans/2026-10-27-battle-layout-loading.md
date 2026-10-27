# 对局布局与加载反馈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增大阵容头像并分散式神站位，调整调度/退出按钮位置，为开局和构筑渲染提供真实 0.1 秒精度的加载反馈。

**Architecture:** 布局继续沿用 `layout_positions` 与场景代理控件。新增独立 `client/gui/loading.py`，在主线程按真实耗时更新文本，并在逐卡渲染间处理 Qt 事件；不引入线程，不制造额外等待。

**Tech Stack:** Python、PySide6、pytest、BWPDIY render_entity。

## Global Constraints

- 不改规则引擎、联机协议、底层 `hand_seq`。
- 头像 88×88；准备区横坐标步长 190。
- 加载文本每 0.1 秒更新实际耗时，完成或异常都关闭。
- 不提交本计划或后续代码，除非维护者另行明确要求。

---

### Task 1: 布局回归与实现

**Files:**
- Modify: `client/gui/builder.py`
- Modify: `client/gui/battle_scene.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: 现有 `layout_positions(game, viewer)`、卡组列表头像 QLabel。
- Produces: 88px 头像；`("ready")=(1328,435)`；`("menu")=(1352,16)`；准备区 x=400+190*index。

- [ ] **Step 1: 写失败测试**

```python
assert avatar.width() == avatar.height() == 88
assert scene.ready_item.pos() == QPointF(1328, 435)
assert scene.menu_item.pos() == QPointF(1352, 16)
assert [scene.cards[("shiki", 0, i)].x() for i in range(4)] == [400, 590, 780, 970]
```

- [ ] **Step 2: 运行相关测试确认旧布局失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py -k 'portraits or perspective or scene_controls'`
Expected: 头像和坐标断言失败。

- [ ] **Step 3: 实施最小布局修改**

头像改 `setFixedSize(88, 88)`；ready/menu 使用上述坐标；准备区改 `400 + index * 190`，保持战斗区坐标不变。

- [ ] **Step 4: 复跑布局测试**

Run: 同 Step 2。
Expected: PASS。

### Task 2: 共用真实耗时加载组件

**Files:**
- Create: `client/gui/loading.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Produces: `LoadingIndicator(prefix, on_text, parent=None)`，方法 `start()`、`tick()`、`stop()`；`text()` 形如 `正在准备对局 0.2s`。

- [ ] **Step 1: 写真实时间测试**

```python
indicator = LoadingIndicator("正在准备对局", seen.append)
indicator.start()
assert seen[-1] == "正在准备对局 0.0s"
# 注入可控 elapsed 时钟，推进到 0.2s 后 tick
assert seen[-1] == "正在准备对局 0.2s"
indicator.stop()
```

- [ ] **Step 2: 确认组件不存在而失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k loading_indicator`
Expected: import 失败或断言失败。

- [ ] **Step 3: 实现组件**

使用 `QElapsedTimer` 和 100ms `QTimer`；`tick()` 只在 tenth 改变时回调并 `QApplication.processEvents()`，`stop()` 停止计时器。允许测试注入时钟。

- [ ] **Step 4: 复跑组件测试**

Run: 同 Step 2。
Expected: PASS。

### Task 3: 开局、联机与构筑加载覆盖

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `client/gui/online.py`
- Modify: `client/gui/builder.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Consumes: `LoadingIndicator.start/tick/stop`。
- Produces: 场景 `show_loading(prefix)`、`hide_loading()`、`loading_tick()`；构筑页同文本加载标签。

- [ ] **Step 1: 写加载生命周期测试**

```python
view.start_game(...)
assert scene.loading_item.isHidden()
# 手动 start 后验证显示、文本含 0.0s，hide 后停止
view.edit_deck(0)
assert view.loading_label.isHidden()
```

另用包装函数记录：进入编辑渲染期间至少一次显示加载文本；`show_loading` 后 `sync_state` 调用多次 `loading_tick`。

- [ ] **Step 2: 确认加载接口不存在而失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_builder.py -k 'loading'`
Expected: 属性或断言失败。

- [ ] **Step 3: 接入加载覆盖与逐卡 tick**

热坐 `start_game`、联机 `set_state` 用 `try/finally` 关闭；`sync_state` 每个式神/手牌后调用 `loading_tick`。构筑 `_enter_editor`、环境/式神变更和翻页用 `try/finally`，逐卡更新加载文本。保持已有 dirty 语义。

- [ ] **Step 4: 复跑加载测试与相关旧测试**

Run: 同 Step 2，再跑 `tests/test_gui_builder.py tests/test_gui_battle.py tests/test_gui_online.py`。
Expected: 全部 PASS。

### Task 4: 实图、文档与全量验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

- [ ] **Step 1: 检查实图**

确认 88px 头像不挤压卡组名/按钮，五卡页不被裁切；检查调度按钮、退出按钮、分散站位和加载文本。

- [ ] **Step 2: 同步文档**

记录新坐标、88px 头像、真实 0.1 秒加载反馈及不阻塞/不造假等待原则。

- [ ] **Step 3: 全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Expected: 全部 PASS；`git diff --check` 无错误。
