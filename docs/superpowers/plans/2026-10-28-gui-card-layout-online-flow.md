# GUI 五卡布局与联机入口调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复五卡浏览布局，简化式神录与联机入口，并修正对局牌库信息、结束回合禁用态和热坐固定起手。

**Architecture:** 在共用 `CardWidget`/卡牌行辅助函数中解决等宽和卡图适配，构筑与式神录只负责提供本页卡牌。联机卡组选择留在 `OnlineView` 大厅内部，主窗口只根据当前联机子页面控制退出按钮。热坐仅替换默认种子来源，不改变核心引擎的确定性接口。

**Tech Stack:** Python 3.14、PySide6、BWPDIY 原生卡图渲染、pytest。

## Global Constraints

- Windows Git Bash 测试命令使用 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`。
- 卡图保持长宽比，按实际显示尺寸调用 `card_pixmap(..., height=n)`，不拉伸图片。
- 保留显式 `seed` 的测试确定性；不修改 `core.setup.new_game` 的默认规则。
- 按项目约定，本批中小改动在主上下文执行，不委托子代理；未经用户明确要求不 commit/push。

---

### Task 1: 共用五卡等宽布局与卡图适配

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/builder.py`
- Modify: `client/gui/codex.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Produces: `fill_card_row(layout, widgets: list[CardWidget], page_size: int = 5) -> None`，以等拉伸列放置卡牌，不足页用空白列占位。
- Produces: `CardWidget.resizeEvent` 按卡图可用区域重新请求原生高度卡图。

- [ ] **Step 1: 写失败测试**

在构筑与式神录测试中显示 1200px 窗口，断言五张卡宽度相等、全部在 `card_area` 内、最左和最右列贴合布局内容边界，并断言 `CardWidget.minimumWidth() == 0`。为卡图设置非正方形测试图，调整窗口宽度后断言 `art_label.pixmap()` 未超出可用区域且长宽比保持。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_builder.py tests/test_gui_codex.py -q`
Expected: 当前固定最小宽度、末尾 stretch 或固定 360px 卡图导致边界断言失败。

- [ ] **Step 3: 实现共用布局**

在 `widgets.py` 增加 `fill_card_row`，每列统一 `stretch=1`，不足五列添加可删除的空白 `QWidget` 占位。`CardWidget` 改为最小宽度 0、取消通用最大宽度，卡图标签使用忽略尺寸策略；保存渲染参数，在尺寸变化时按可用宽高计算等比原生高度并重新调用 `card_pixmap`。构筑和式神录用 `fill_card_row` 替换 `addWidget(..., 1)` 与末尾 `addStretch(1)`。

- [ ] **Step 4: 运行相关测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_builder.py tests/test_gui_codex.py -q`
Expected: PASS。

### Task 2: 式神录树与卡牌列表精简

**Files:**
- Modify: `client/gui/codex.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Consumes: Task 1 的 `fill_card_row`。
- Produces: 卡牌列表只含返回栏、式神名、卡片区和翻页栏。

- [ ] **Step 1: 写失败测试**

断言 `view.shiki_list.indentation() <= 10`，主题样式包含浅蓝选中底；进入卡牌列表后不存在 `home_body`、`portrait_label`、`stats_label` 和 `ability_label`，`name_label` 仍显示选中式神名。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_codex.py -q`
Expected: 当前缩进、金色选中底和上方信息区使断言失败。

- [ ] **Step 3: 删除旧信息区并调整树样式**

设置树缩进 10，按浅/深主题选择浅蓝选中背景与高对比文字。删除 `home_body` 及其三个子控件、相关赋值和不再使用的 `card_pixmap` 导入；卡片区占用释放的垂直空间。

- [ ] **Step 4: 运行式神录测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_codex.py -q`
Expected: PASS。

### Task 3: 联机大厅卡组选择与连接交互

**Files:**
- Modify: `client/gui/online.py`
- Modify: `client/gui/app.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Produces: 无卡组也可 `connect_server()` 进入大厅；建房或首次加入前由大厅卡组组合框提供 `deck_code`。
- Produces: 主窗口联机子页面切到 `battle` 时才显示 `game_menu_button`。

- [ ] **Step 1: 写失败测试**

无本地卡组时 mock 成功连接，断言进入大厅；建房/首次加入无卡组时返回 `False`。mock `show_warning`，确认预检和 WebSocket 异常均弹窗。创建 `MainWindow`，断言联机连接页和大厅隐藏退出按钮、对局页显示。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_online.py -q`
Expected: 当前连接前强制选卡组、常驻错误标签和联机全程退出按钮导致失败。

- [ ] **Step 3: 移动卡组选择并统一错误弹窗**

将 `deck_combo` 移到大厅；连接成功只设置玩家名并打开桥。卡组切换统一更新 `deck_name`、`deck_code` 和 `self_label`；`create_room` 与无令牌 `join_room` 先校验已选卡组。使用共用 `show_warning` 显示连接失败，删除 `connect_error`。

- [ ] **Step 4: 同步主窗口退出按钮**

在主窗口连接联机 `stack.currentChanged`，根据当前顶层页面及联机子页面是否为 `battle` 更新按钮可见性；`go()`、`go_menu()` 继续复用同一同步方法。

- [ ] **Step 5: 运行联机与应用测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_online.py -q`
Expected: PASS。

### Task 4: 对局牌库文本、结束回合状态与随机起手

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Preserves: `HotseatView.start_game(..., seed=7)` 等显式种子调用不变。
- Produces: 未传 `seed` 时使用 `secrets.randbits(32)` 生成每局种子。

- [ ] **Step 1: 写失败测试**

新增牌库标签位于三张卡背组右侧且不超出 1600px 场景的断言；断言样式表含 `QPushButton#endTurnButton:disabled`。mock `secrets.randbits` 依次返回 42、43，连续两次不传种子开局，断言 `new_game` 收到不同种子且起手不同。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_battle.py -q`
Expected: 牌库标签未右置、无禁用态专用样式、默认种子恒为 42。

- [ ] **Step 3: 实施最小修正**

将牌背组略向左移，为右侧 68px 数量标签留位；双方标签与各自牌背纵向对齐。增加禁用态背景、边框和文字色。`start_hotseat` 不再传 42，`start_game` 的 `seed` 默认为 `None`，仅在 `None` 时调用 `secrets.randbits(32)`。

- [ ] **Step 4: 运行对局测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_gui_battle.py tests/test_gui_online.py -q`
Expected: PASS。

### Task 5: 文档与全量验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`（仅当其中描述与本批行为冲突）
- Test: 全量测试与数据校验

- [ ] **Step 1: 同步当前行为**

精简更新五卡等宽、式神录列表、联机大厅卡组选择、牌库文本位置、结束回合禁用态与热坐随机种子描述，不保留更新日志式段落。

- [ ] **Step 2: 全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全绿。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Expected: 通过。

Run: `git diff --check`
Expected: 无输出。
