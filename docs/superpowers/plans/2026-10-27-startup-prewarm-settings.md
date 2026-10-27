# 启动预热、全屏加载与设置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 启动时按内容指纹预热卡图并记录更新，加载期间只显示提示，主菜单设置支持确认后全量重建。

**Architecture:** 新增 `prewarm.py` 复用配置索引和现有 cardart 渲染器，以 `manifest.json` 记录配置/图片哈希与合成时间。新增全屏加载遮罩和设置页；不改规则引擎与收藏数据。

**Tech Stack:** Python、PySide6、BWPDIY、pytest。

## Global Constraints

- 仅处理 `library/` 已配置条目；有效缓存复用，内容变更才重渲染。
- 加载期间仅显示全屏提示与真实耗时，不显示其他 UI，结束后恢复。
- 清缓存必须确认；仅删除卡图 PNG 与 manifest，不碰配置和源图。

### Task 1: 预热清单与合成

**Files:**
- Create: `client/gui/prewarm.py`
- Test: `tests/test_gui_prewarm.py`

- [ ] **Step 1: 写失败测试**

构造 shikigami/cards 配置，断言合成调用、manifest 条目及修改配置后的哈希更新。

- [ ] **Step 2: 确认预热模块不存在**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py`
Expected: 模块或行为断言失败。

- [ ] **Step 3: 实现配置遍历与清单**

复用 portrait 配置索引；调用 card/entity/portrait 渲染器；记录 id/kind/version/config_sha/art_sha 和 updated_at。

- [ ] **Step 4: 复跑测试**

Run: 同 Step 2。
Expected: PASS。

### Task 2: 全屏加载遮罩

**Files:**
- Modify: `client/gui/loading.py`
- Modify: `client/gui/builder.py`
- Modify: `client/gui/codex.py`
- Modify: `client/gui/battle_scene.py`
- Test: `tests/test_gui_prewarm.py`

- [ ] **Step 1: 写失败测试**

断言开始加载时只有提示可见，构筑/式神录 stack 隐藏，对局全屏遮罩存在，结束后恢复。

- [ ] **Step 2: 确认其他 UI 仍可见**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py -k 'overlay'`
Expected: FAIL。

- [ ] **Step 3: 实现遮罩**

构筑/式神录在加载时隐藏 stack 并让提示占满页面；对局增加全屏背景矩形，完成后隐藏。

- [ ] **Step 4: 复跑测试**

Run: 同 Step 2。
Expected: PASS。

### Task 3: 启动预热与设置重建

**Files:**
- Create: `client/gui/settings.py`
- Modify: `client/gui/app.py`
- Modify: `client/gui/prewarm.py`
- Test: `tests/test_gui_prewarm.py`

**Interfaces:**
- Produces: `MainWindow.prewarm_resources()`、`SettingsView.rebuild()`、`SettingsView.refresh_status()`。

- [ ] **Step 1: 写失败测试**

验证主菜单设置入口、启动预热、确认后清缓存重建、状态行更新和结束隐藏加载层。

- [ ] **Step 2: 确认设置与启动流程未实现**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py -k 'settings or startup'`
Expected: FAIL。

- [ ] **Step 3: 实现设置页与启动调用**

主菜单增加设置项，显示条目数/最近合成时间；确认后仅删除 PNG/manifest，再全量预热。`main()` 在 show 后执行预热。

- [ ] **Step 4: 复跑测试并检查实图**

Run: 同 Step 2；随后运行全部 GUI 测试。
Expected: PASS，加载期间无其他 UI。

### Task 4: 文档与全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

- [ ] **Step 1: 同步文档**

记录启动预热、manifest、全屏加载、设置重建及 ICC 元数据修复。

- [ ] **Step 2: 全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Run: `git diff --check`
Expected: 全部通过后提交并推送。
