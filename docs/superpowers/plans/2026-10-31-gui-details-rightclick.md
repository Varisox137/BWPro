# GUI 详情尺寸、右键入口与额外状态精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一详情卡图/机制框真实尺寸、全场景右键只读详情、对局边缘布局和精简式神额外状态。

**Architecture:** `CardWidget` 暴露公开 art_width 与独立右键信号；机制框按原生宽度比计算 font_scale；BattleCardItem 将左键拖拽与右键详情分离；状态提取仅保留 delayed/invocations。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计来源：`docs/superpowers/specs/2026-10-31-gui-details-rightclick-design.md`。
- 卡图与机制框均原生 `height=512`，机制 `chars_per_line=12`，缩放只通过 `font_scale<=1.0`，不做各向异性拉伸。
- 所有详情入口为右键；左键操作语义不变，任何阶段可右键查看公开详情，暗手牌/秘密信息不脱敏。
- 第三列仅 delayed/invocations，灵咒不展开身材修饰数值。
- 所有新行为先写失败测试并确认 RED，再最小实现到 GREEN。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 统一原生尺寸与真实机制框宽度

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/mechanisms.py`
- Modify: `client/gui/details.py`
- Modify: `client/gui/player_details.py`
- Test: `tests/test_gui_mechanisms.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: `CardWidget.art_width -> int | None`、`detail_clicked`（Task 2 使用）；机制 panel 自适应 `font_scale`。

- [ ] **Step 1: 写尺寸失败测试**

捕获三类详情的 card_pixmap 调用，全部 height=512；主卡与形态同尺寸。机制 fake 在 scale=1 返回固定宽度 400、卡图实际宽度 360 时，最终调用 scale=0.9，panel 与卡图控件真实宽度一致且不超过 1.0。art_width 为公开只读属性，不再读取 `_display_art`。机制内容超过 512 时仍保留滚动。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_builder.py -k 'detail_size or mechanism_scale or art_width'`
Expected: 式神主卡仍 336，机制 scale/宽度不一致，无公开 art_width。

- [ ] **Step 3: 实现公开尺寸与自适应缩放**

CardWidget 增加 `art_width` 属性，仅返回 `_display_art.width()` 或 None，并替换详情私有读取。mechanism_panel 获得目标卡图宽度时，先按 scale=1 测量原生机制框，再以 target/native 计算 font_scale（最大 1），按该 scale 原生重绘；不要用 CSS 拉伸图片。

三类详情统一 height=512，机制/状态 panel max_height=512，弹窗最小高度相应增加；容器宽度使用实际渲染宽度。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_builder.py -k 'detail_size or mechanism_scale or art_width or mechanisms'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/widgets.py client/gui/mechanisms.py client/gui/details.py client/gui/player_details.py tests/test_gui_mechanisms.py tests/test_gui_builder.py
git commit -m "feat(gui): 统一详情原生卡图与机制框尺寸"
git push
```

---

### Task 2: 全场景右键只读详情

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `client/gui/builder.py`
- Modify: `client/gui/codex.py`
- Modify: `client/gui/player_details.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Consumes: Task 1 `detail_clicked`。
- Produces: 左键 clicked 选择语义不变；右键在 mulligan/pending/handoff/game_over 均只打开公开详情。

- [ ] **Step 1: 写右键与左键隔离失败测试**

CardWidget 右键发 detail_clicked，左键仍 clicked。BattleScene 在 mulligan 单击选中、右键打开详情；pending choice 右键不发送 choose；upgrade 左键升级、右键式神详情；终局/交接右键可用。敌方暗手牌右键仍拒绝。牌手右键仅在头像区域内打开详情，不触发目标选择。构筑/式神录/幻境点击详情入口同样为右键。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_builder.py tests/test_gui_codex.py -k 'right_click or detail'`
Expected: 当前左键也可详情，输入关闭时右键被拖拽控制器拒绝。

- [ ] **Step 3: 实现右键信号与场景分派**

CardWidget.mouseReleaseEvent 仅左键发 clicked，右键发 detail_clicked；各详情调用点改用右键，选择/构筑数量操作仍用 clicked。

BattleCardItem 左键才进入 drag_controller；右键不启动拖拽，release 仅发 detail_requested。隐藏手牌不放开，牌手保持头像区域限制。右键路径不读取 inputs_open，也不执行 mulligan/upgrade/assault/play_card/choose。所有详情窗口保持非模态或现有 exec 方式，不新增全局操作锁。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_builder.py tests/test_gui_codex.py -k 'right_click or detail'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/widgets.py client/gui/battle_scene.py client/gui/battle.py client/gui/builder.py client/gui/codex.py client/gui/player_details.py tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_builder.py tests/test_gui_codex.py
git commit -m "feat(gui): 统一右键只读详情入口"
git push
```

---

### Task 3: 边缘布局与额外状态精简

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/details.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Test: `tests/test_gui_battle.py`

- [ ] **Step 1: 写布局与状态过滤失败测试**

断言 player/log 坐标相对旧值左移 12，end_turn/手牌右缘右移 12。第三列仅包含 delayed/invocations：延迟来源、触发类型、次数、可见目标及灵咒名称/来源/原文；不含 shield、energy、perm/temp/dyn、keywords、attack_buffs、immunities、stuns、defeated/countdown 或灵咒身材修饰。secret delayed 仍按 viewer 过滤。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'edge_layout or status_lines or secret_delayed'`
Expected: 边缘仍为旧坐标，状态含内部数值。

- [ ] **Step 3: 最小实现布局与过滤**

layout_positions 对 player/log 使用 x=-12，end_turn x=1505，手牌 right=SCENE_WIDTH+12，其他坐标保持。shiki_status_lines 删除 delayed/invocations 之外的所有状态；灵咒仅保留名称、来源与 idef.text，不渲染 power/health/bonus/mod。文档同步右键与精简口径。

- [ ] **Step 4: 相关与全量验证**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'edge_layout or status_lines or secret_delayed'`
Expected: PASS。

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle_scene.py client/gui/details.py docs/gui-design.md docs/gui-plan.md tests/test_gui_battle.py
git commit -m "feat(gui): 调整对局边缘并精简额外状态"
git push
```
