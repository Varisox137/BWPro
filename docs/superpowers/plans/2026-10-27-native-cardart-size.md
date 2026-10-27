# BWPDIY 原生尺寸适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 卡牌、式神小卡与头像按 BWPDIY 原生 `height` 参数合成，避免成品二次缩放并保证尺寸缓存隔离。

**Architecture:** 在现有 cardart/portrait 适配层透传 `height`，把尺寸传入缓存键和 BWPDIY renderer。调用方只传高度，保持默认输出比例；不再对对应成品执行二次缩放。

**Tech Stack:** Python、PySide6、BWPDIY render/render_entity/render_portrait、pytest。

## Global Constraints

- 不改 BWPDIY 源码与项目 `library/` 配置。
- 构筑卡高 360、普通手牌高 156、调度手牌高 255、式神小卡高 210、详情主卡高 336、阵容头像高 88。
- 不传任意宽高框，保持默认比例；缓存键必须含输出尺寸。

### Task 1: cardart 原生尺寸与缓存

**Files:**
- Modify: `client/gui/cardart.py`
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/details.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Produces: `card_pixmap(..., height=None)`、`entity_pixmap(..., height=None)`、`shikigami_pixmap(..., height=None)`。

- [ ] **Step 1: 写失败测试**

捕获 `bwpdiy.render.pipeline.render_card` 与 `entity.render_entity` 的 `height`，断言调用高度；比较同卡不同高度的缓存条目数量及输出比例。

- [ ] **Step 2: 确认旧调用未传 height**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py -k 'native_size'`
Expected: FAIL。

- [ ] **Step 3: 透传高度并纳入缓存键**

修改 `_render_card_pixmap`、`_render_entity_pixmap`、`_card_pixmap_impl`、公开包装及 `_card_cache_key`，然后修改各调用点，移除对应 `QPixmap.scaled`。

- [ ] **Step 4: 复跑测试**

Run: 同 Step 2，随后运行 GUI 测试文件。
Expected: PASS。

### Task 2: 头像原生 88px 合成

**Files:**
- Modify: `client/gui/portrait.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: `shikigami_portrait(definition, size=88)`，BWPDIY `render_portrait(width=size, height=size)`。

- [ ] **Step 1: 写失败测试**

捕获 `render_portrait` 的 `width/height`，断言均为 88，且返回值不再调用二次缩放。

- [ ] **Step 2: 确认旧调用只按默认尺寸渲染**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py -k 'portrait_native_size'`
Expected: FAIL。

- [ ] **Step 3: 修改头像调用**

默认 `size=88`，正常与空头像均传 `width=size, height=size`，直接返回合成 QPixmap。

- [ ] **Step 4: 复跑头像测试**

Run: 同 Step 2。
Expected: PASS。

### Task 3: 文档与全量验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

- [ ] **Step 1: 同步文档**

记录原生高度参数、缓存尺寸隔离、调用点尺寸和不做二次重采样。

- [ ] **Step 2: 实图检查**

确认头像、构筑卡、手牌、式神小卡和详情不拉伸、不裁切。

- [ ] **Step 3: 全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Run: `git diff --check`
Expected: 全部通过；汇报后由维护者决定是否提交。
