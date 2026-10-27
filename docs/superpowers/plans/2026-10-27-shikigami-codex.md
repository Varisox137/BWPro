# 式神录界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用可筛选式神总览、单式主页和每页五卡的卡牌浏览/详情完成主菜单“式神录”。

**Architecture:** 新建独立 `client/gui/codex.py`，复用 `CardWidget`、`CardDetailDialog`、`shikigami_portrait`、环境解析和 `LoadingIndicator`。不改规则引擎、卡组存储和联机协议，不引入收藏系统。

**Tech Stack:** Python、PySide6、现有 db 版本数据与 BWPDIY 合成、pytest。

## Global Constraints

- 默认最新环境，支持现有 alias/日期切换；未发布/WIP 条目沿用构筑池排除规则。
- 单式主页显示大立绘、派系、力量/生命和基础能力文本，不虚构传记或熟练度。
- 专属与协战卡牌每页 5 张，首位基础式神卡仅供查看，无构筑计数；点击打开现有单卡详情。
- 浅深主题、加载反馈、返回主菜单行为与既有页面一致。

### Task 1: 总览、筛选与单式主页

**Files:**
- Create: `client/gui/codex.py`
- Modify: `client/gui/app.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Produces: `ShikigamiCodexView(db, parent=None)`；`apply_theme(theme, colors)`；`select_shikigami(sid)`；`change_environment()`。

- [ ] **Step 1: 写失败测试**

覆盖主菜单进入 codex、版本包/派系/全名筛选、选择后立绘/数值/基础能力、环境切换与无结果提示。

- [ ] **Step 2: 确认占位实现未满足**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_codex.py`
Expected: 模块或行为断言失败。

- [ ] **Step 3: 实现视图与主菜单接入**

以 QStackedWidget 区分总览和单式主页；复用 available_shikigami/buildable_cards 与 env_label/parse_env_input；主菜单创建实际视图。

- [ ] **Step 4: 复跑测试**

Run: 同 Step 2。
Expected: PASS。

### Task 2: 五卡浏览、详情和加载反馈

**Files:**
- Modify: `client/gui/codex.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Consumes: `CardWidget(cdef, editable=False, db=db, art_context=...)`、`CardDetailDialog`、`LoadingIndicator`。
- Produces: `turn_card_page(direction)`、`show_card_detail(cdef)`。

- [ ] **Step 1: 写失败测试**

验证每页 5 张、翻页边界、协战列尾、无构筑计数、详情调用与加载开始/tick/结束事件。

- [ ] **Step 2: 确认五卡与加载行为未实现**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_codex.py -k 'cards or loading'`
Expected: FAIL。

- [ ] **Step 3: 实现卡页与详情**

复用 CardWidget，隐藏 count_label，协战牌按 buildable_cards 顺序置于最后；逐卡加载提示，点击详情。

- [ ] **Step 4: 复跑测试**

Run: 同 Step 2。
Expected: PASS。

### Task 3: 实图、文档与全量验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `README.md`

- [ ] **Step 1: 实图检查**

检查总览、单式主页、五卡页、浅深主题、环境切换与加载文本；无拉伸、裁切或占位残留。

- [ ] **Step 2: 同步文档**

README 的 GUI 功能加入式神录；gui-design/gui-plan 标记其实现范围及不含收藏系统。

- [ ] **Step 3: 全量验证与提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Run: `git diff --check`
Expected: 全部通过后提交并推送。
