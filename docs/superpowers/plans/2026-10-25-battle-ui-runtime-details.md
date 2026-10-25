# 对局界面、交接隐私与运行时详情实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改引擎和联机协议的前提下，完成对局布局、独立战斗记录、热坐交接隐私、静默弹窗及卡牌/式神运行时详情。

**Architecture:** 保留 `HotseatView`/`OnlineBattleView` 继承体系和 `ShikiFrame` 目标引用，使用 Qt 容器布局与 viewer 驱动的既有组件重排。日志复用现有 `log_list` 和时间线；交接挂在热坐 viewer 变化；详情通过可选参数消费已有 `hand_info` 与序列化式神状态。

**Tech Stack:** Python 3.14、PySide6、pytest（offscreen）、现有 `client.cli.hand_cards_info`。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-25-battle-ui-runtime-details-design.md`。
- 不修改 `card_data_raw.md`、规则引擎、卡牌数据库、CLI 或联机协议。
- 原始卡牌效果文本不改写；不新增通用条件进度账本或逐来源增减益账本。
- 日志、交接和详情继续执行非公开信息过滤；联机只读服务端 `payload["hand_info"]`，不启用热坐交接弹窗。
- 保留当前工作区中与本任务无关的未跟踪文件，提交时只添加本任务明确修改的文件。
- 测试命令：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`；数据库校验：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`。

---

### Task 1: 对局布局、常态组件与独立战斗记录

**Files:**
- Modify: `client/gui/battle.py`（布局、视角重排、常态渲染、日志、开局/返回清理）
- Modify: `client/gui/online.py`（`reset_session`）
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: 现有 `ShikiFrame`、`player_frames`、`log_list`、`played_timeline`。
- Produces: `log_dialog`、`log_button`、`show_log()`、`close_log()`、`_sync_perspective()`；供后续任务复用。

- [ ] **Step 1: 写失败测试**

```python
assert not hasattr(view, "seat_label")
assert len(view.player_frames) == 2 and len(view.shiki_frames) == 8
assert all(not frame.name_label.text().startswith(("1.", "2.", "3.", "4."))
           for frame in view.shiki_frames.values())
assert view.log_dialog.isHidden()
view.show_log()
assert not view.log_dialog.isHidden()
first = view.log_dialog
view.show_log()
assert view.log_dialog is first
before_close = list(view.played_timeline)
view.log_dialog.close()
assert view.played_timeline == before_close
```

常态组件断言仅含等级、名字、倒计时（如有）、力量、生命、护甲，不含能量、形态、关键字或灵咒。保存八个槽对象，viewer 改变后断言对象与 `ref` 不变，上方为 `1 - viewer`、下方为 `viewer`。联机以 `me=1` 验证同样己下敌上且不重建槽。

- [ ] **Step 2: 验证测试失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 因 `seat_label`、`log_dialog` 和视角重排尚不存在而失败。

- [ ] **Step 3: 实现布局与日志窗**

删除 `seat_label` 及其渲染；拆分牌手面板和四式神行创建，预留上/下牌手与式神通槽容器。`_sync_perspective()` 只在 viewer 改变时取出并重新加入既有组件，不 `deleteLater()`、不改信号或 `Ref`。四槽以 `(12, 0, 0, 12)` 的垂直外边距形成浅弧线，敌方反向。

常态仅显示名字+Lv、当前力量、`生命 当前/上限`、护甲/破甲和有值时的倒计时；其他状态移至 Task 4 详情。文字背景透明。

将 `log_list` 移入持有型非模态 `QDialog`，默认隐藏；`show_log()` 复用并滚到底，`close_log()` 仅隐藏。热坐开局、返回和 `OnlineBattleView.reset_session()` 调用 `close_log()`。

- [ ] **Step 4: 验证布局与日志**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部通过；目标选择、双目标和时间线输入锁不回归。

---

### Task 2: 热坐交接与起始调度隐私

**Files:**
- Modify: `client/gui/battle.py`（viewer 刷新、指令门控、时间线、pending_choice、日志过滤）
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: Task 1 的 `_sync_perspective()`、`close_log()` 与稳定槽位。
- Produces: `_handoff_pending: bool`、`handoff_dialog: QDialog | None`、`confirm_handoff()`；供后续返回/详情任务使用。

- [ ] **Step 1: 写失败测试**

回合结束或调度完成导致 viewer 改变时：

```python
assert view._handoff_pending
assert view.handoff_dialog is not None and not view.handoff_dialog.isHidden()
assert not view.hand_frames
before = list(view.timeline_queue)
assert not view.apply_command({"op": "end_turn"})
assert view.timeline_queue == before
view.confirm_handoff()
assert not view._handoff_pending
assert view.hand_frames
```

确认前不得启动 timeline，确认后恢复队列、pending_choice 和己下敌上。相同玩家连续操作不弹；跨玩家 pending_choice 进入与作答返回各交接一次。联机推送不弹交接。

起始调度日志断言自己“调度了一张手牌（剩余 N 次）”可见、对方不可见；战中相同文案不被起始阶段过滤误删。

- [ ] **Step 2: 验证测试失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 当前无 `_handoff_pending`，且对方起始调度次数可见，测试失败。

- [ ] **Step 3: 实现统一交接与隐私过滤**

在热坐 `refresh()` 检测 viewer 改变：先清空旧手牌/关闭旧选择，设置 `_handoff_pending`，暂停 `_render_state()`、timeline 和 `_sync_pending_choice()`，以非阻塞 `show()` 显示模态交接窗。`confirm_handoff()` 清除标记后再渲染、重排、播放和恢复选择。`_inputs_open()` 与 `apply_command()` 都拒绝交接期间输入；返回主菜单清理交接窗。

`_render_log()` 只在“对局开始：调度阶段”至正式“对局开始”之间，按玩家名前缀过滤对方的“调度了一张手牌”行；不改 `played_timeline`、引擎日志或联机过滤。

- [ ] **Step 4: 验证交接与隐私**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部通过；测试辅助 `settle(view)` 遇交接先 `confirm_handoff()`，不通过绕过冻结来简化测试。

---

### Task 3: 静默弹窗与统一按钮

**Files:**
- Modify: `client/gui/widgets.py`（`polish_dialog_buttons`）
- Modify: `client/gui/app.py`（`dialogButton` QSS）
- Modify: `client/gui/battle.py`（`show_player_detail`、详情/日志按钮）
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: Task 1 日志窗、Task 2 交接窗。
- Produces: 标准按钮最小尺寸 76×30、底部右侧 `QDialogButtonBox`；`show_player_detail()` 返回 `None`。

- [ ] **Step 1: 写失败测试**

```python
box = dialog.findChild(QDialogButtonBox)
assert box.button(QDialogButtonBox.Close).text() == "关闭"
assert box.button(QDialogButtonBox.Close).minimumWidth() == 76
assert box.button(QDialogButtonBox.Close).minimumHeight() == 30
```

牌手详情测试改为检查普通 `QDialog`，不再依赖 `QMessageBox`。

- [ ] **Step 2: 验证尺寸测试失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py::test_dialog_standard_buttons_are_chinese_and_compact`
Expected: 当前最小宽度 68，断言失败。

- [ ] **Step 3: 实现统一按钮与牌手普通对话框**

`polish_dialog_buttons()` 使用 `setMinimumSize(76, 30)`，QSS 保持紧凑 padding。牌手详情改为 `QDialog + QLabel + QDialogButtonBox.Close`；日志、交接和详情按钮均置底右对齐并复用中文样式。不得修改 `ChoiceDialog.reject()`。

- [ ] **Step 4: 验证弹窗**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py`
Expected: 全部通过；Windows 人工确认无系统信息框提示音。

---

### Task 4: 卡牌与式神运行时详情

**Files:**
- Modify: `client/gui/widgets.py`（`CardDetailDialog`）
- Modify: `client/gui/battle.py`（`show_card_detail`、`show_shiki_detail`）
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: `HotseatView.hand_info()`、联机 `payload["hand_info"]`、`ShikigamiState` 与 `db.invocations`。
- Produces: `CardDetailDialog(cdef, db=None, parent=None, runtime: dict | None = None)`；`runtime` 为单个手牌的 `hand_info[uid]`。

- [ ] **Step 1: 写失败测试**

```python
runtime = {
    "cost": 0, "stats": "力量 +2　护甲 +1", "keywords": ["瞬发", "贯通"],
    "enhance": 2, "quest": "已 1/2", "playable": False,
    "usage": [{"label": "常规", "ok": False, "reason": "条件未满足"}],
}
dialog = CardDetailDialog(cdef, db, runtime=runtime)
text = dialog.runtime_label.text()
assert "费用 0" in text and "增强 2" in text
assert "已 1/2" in text and "条件未满足" in text
```

联机 `hand_info` 放唯一标记，断言详情使用该标记而非本地重算；静态详情不创建 `runtime_label`。式神详情测试包含关键字、倒计时能力、延迟能力及逐条灵咒名称/文本，常态组件不含这些内容。

- [ ] **Step 2: 验证运行时详情测试失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: `CardDetailDialog` 无 `runtime` 参数和 `runtime_label`，测试失败。

- [ ] **Step 3: 实现可选当前状态区**

仅在 `runtime is not None` 时创建只读、可换行 `runtime_label`，列出费用、数值、增强、关键字、委托、条件和使用方式原因；不改原文。`show_card_detail()` 仅当 uid 存在于 `hand_info()` 时传对应字典。

式神详情展示有效身材、护甲、能量、派系、关键字、免疫、眩晕/气绝、倒计时及来源、永久/临时/战斗修正、形态/觉醒、延迟能力与逐条灵咒名称/来源/修饰/文本。无统一来源名称的延迟能力只列类型、次数和已知目标，不伪造名称；不倾倒原始 `ext`。

- [ ] **Step 4: 验证详情与兼容性**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_builder.py`
Expected: 全部通过；构筑静态详情与联机只读约束不回归。

---

### Task 5: 文档、视觉检查与最终验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `README.md`（仅测试数量）
- Modify: `C:/Users/Varis/.kimi-code/AGENTS.md`（仅既有进度数字/模块职责）

**Interfaces:**
- Consumes: Task 1-4 最终实现。
- Produces: 可提交、可推送的完整变更。

- [ ] **Step 1: 同步文档**

写明己下敌上、浅弧线、顶部座位行删除、常态组件精简、独立非模态日志窗、起始调度隐私、热坐交接确认、统一弹窗和运行时详情。保留“逐条增益来源账本”未完成标记。

- [ ] **Step 2: 检查实际渲染**

用 offscreen 抓取浅色/深色对局、日志窗和交接窗截图到 `.tokensave/`，用 ReadMediaFile 逐张检查布局、文字背景、默认隐藏和按钮。Windows 人工确认提示音与交接隐私。

- [ ] **Step 3: 运行验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全部通过。
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Expected: exit 0；只保留既有非阻塞 raw 警告。
Run: `git diff --check`
Expected: 无空白错误。重建 codebase-memory 索引并检查最终 diff。

- [ ] **Step 4: 提交并推送**

更新测试数量后，以中文 conventional 格式提交并 `git push`；只添加本任务文件，不添加当前工作区中无关的未跟踪文件。全量测试和 `db.validate` 必须由主上下文亲跑通过。
