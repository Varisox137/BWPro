# GUI 交互与非阻塞动画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正卡图比例、操作着色、阶段与交接交互，允许记录播放期间继续操作，并加入式神移动和双方用牌动画。

**Architecture:** 现有 `usage_options` 同时提供合法性与费用，GUI 只负责黄/蓝/绿显示。timeline 保持后台播放；引擎在统一 `on_card_played` 发点附加公开动画元数据，BattleScene 用位置缓存与 Qt 动画表现，输入不被动画阻塞。

**Tech Stack:** Python 3.14、PySide6、pytest、pytest-xdist。

## Global Constraints

- 大卡固定高度合成，显示端仅等比缩放，禁止各向异性拉伸。
- 多择牌绿框优先；其他合法零鬼火牌蓝框；其余可出击/可用牌黄框。
- DIY 机制框使用 `chars_per_line`，默认每行 12 汉字；现有 360px 调用按 24px 字号折算为 15 字。
- timeline、移动和用牌动画均不阻塞合法指令；既有交接、选择、终局和联机等待响应门控不变。
- 用牌元数据仅含公开 `uid/card_id/player`，不解析中文日志，不泄露私有信息。
- 测试命令：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`（默认 `-n 4`）。
- 每次只暂存本任务明确列出的文件，避免混入其他未提交修改。

---

### Task 1: 卡图比例、操作着色、阶段位置与两段交接

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/mechanisms.py`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `tests/test_gui_battle.py`
- Modify: `tests/test_gui_builder.py`
- Modify: `tests/test_gui_mechanisms.py`

**Interfaces:**
- Consumes: `usage_options` 的 `ok/cost/id`、`BattleCardItem.set_art`、`HotseatView._begin_handoff/confirm_handoff`。
- Produces: 黄/蓝/绿操作框、右侧阶段文本、两段调度交接。

- [ ] **Step 1: 写失败测试**

在 `tests/test_gui_battle.py` 增加：

```python
def test_hand_playable_border_colors(qapp, view):
    start(view, mulligan=False)
    game = view.game
    game.db.cards[10010151] = F.card(10010151, token=True, cost=0)
    game.db.cards[10010152] = F.card(
        10010152, token=True,
        methods=[F.method("free", cost=0), F.method("paid", cost=1)])
    free = F.give(game, 0, 10010151)
    multi = F.give(game, 0, 10010152)
    view.refresh(); settle(view)
    assert view.battle_scene.cards[("hand", free.uid)].border_color == "blue"
    assert view.battle_scene.cards[("hand", multi.uid)].border_color == "green"
    assert view.battle_scene.cards[("shiki", 0, 0)].border_color == "yellow"


def test_phase_label_sits_right_of_turn_label(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    assert view.upgrade_label.text() == "升级阶段"
    assert view.upgrade_label.isVisible()
    assert view.battle_scene.upgrade_item.x() > view.battle_scene.phase_item.x()


def test_mulligan_handoff_has_review_then_transfer(qapp, view):
    start(view)
    for _ in range(3):
        view.mulligan(view.game.current.hand[0].uid)
        settle(view)
    assert view.handoff_dialog.windowTitle() == "调度完毕请确认"
    assert view.handoff_dialog.isVisible()
    view.confirm_handoff()
    assert view.handoff_dialog.windowTitle() == "准备移交"
    view.confirm_handoff()
    assert view.viewer == 1
```

在 `tests/test_gui_builder.py` 增加 `test_card_art_preserves_source_aspect_ratio`：使用非 3:5 原生图，断言显示后 `pixmap.width / pixmap.height` 与源图一致，且未发生二次各向异性缩放。

在 `tests/test_gui_mechanisms.py` 把机制框 fake 的参数断言改为 `[(15, 0.85)]`，验证原 360px 调用按 24px 字号折算为每行 15 字，且不再传像素宽。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py::test_hand_playable_border_colors tests/test_gui_battle.py::test_phase_label_sits_right_of_turn_label tests/test_gui_battle.py::test_mulligan_handoff_has_review_then_transfer tests/test_gui_builder.py::test_card_art_preserves_source_aspect_ratio tests/test_gui_mechanisms.py`
Expected: 缺少 `border_color`、单段交接、比例断言失败，或机制框仍传 360px。

- [ ] **Step 3: 最小实现**

给 `BattleCardItem` 增加 `border_color` 并按颜色绘制操作框：式神可用为 yellow；手牌多择为 green，否则存在 `ok and cost == 0` 的方式为 blue，其余可用为 yellow。让 `BattleCardItem.set_art` 与详情/调度显示统一按源比例计算目标矩形，禁止二次非等比绘制。

将 `_mechanism_pixmap` 和 `mechanism_panel` 的可选参数改为 `chars_per_line`，并传给 `render_mechanism(chars_per_line=...)`；`CardDetailDialog` 的调用改为 `chars_per_line=15, font_scale=0.85`，不传参时使用 DIY 默认每行 12 字。

阶段标签使用 `{"mulligan":"调度阶段","upgrade":"升级阶段","battle":"主要阶段"}`，移到 `phase_label` 右侧并降低字号。交接增加 `review` 阶段：第一窗“调度完毕请确认”保留手牌，第二窗“准备移交”才执行现有清空与视角切换。

- [ ] **Step 4: 运行相关测试确认通过**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_builder.py tests/test_gui_mechanisms.py`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/widgets.py client/gui/mechanisms.py client/gui/battle_scene.py client/gui/battle.py tests/test_gui_battle.py tests/test_gui_builder.py tests/test_gui_mechanisms.py
git commit -m "feat(gui): 修正卡图比例与操作阶段反馈"
```

---

### Task 2: timeline 播放期间允许合法操作

**Files:**
- Modify: `client/gui/battle.py:580-588`
- Modify: `client/gui/online.py:188-201`
- Modify: `tests/test_gui_battle.py`
- Modify: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: 现有同步 `game.apply`、联机 `_awaiting_state` 和其他操作门控。
- Produces: timeline 不再参与本地/联机输入锁定。

- [ ] **Step 1: 写失败测试**

本地：

```python
def test_actions_remain_available_during_timeline(qapp, view):
    start(view, mulligan=False, config=GameConfig(auto_skip_upgrade=False))
    view.upgrade(1)
    assert view.timeline_queue
    assert view._inputs_open()
    assert view.end_turn_button.isEnabled()
```

联机：在已有 `OnlineBattleView` 状态上保留 `timeline_queue`，断言 `_can_send({"op":"end_turn"})` 为真，但 `_awaiting_state=True` 时仍为假。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py::test_actions_remain_available_during_timeline tests/test_gui_online.py -k timeline`
Expected: timeline 仍阻止输入。

- [ ] **Step 3: 最小实现**

从 `HotseatView._inputs_open`、`HotseatView.apply_command` 和 `OnlineBattleView._can_send` 中移除 `timeline_queue` 条件。保留 `_handoff_pending`、`pending_choice`、`_awaiting_state` 和终局检查，不改为异步引擎调用。

- [ ] **Step 4: 运行测试确认通过**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle.py client/gui/online.py tests/test_gui_battle.py tests/test_gui_online.py
git commit -m "feat(gui): 允许结算记录播放期间继续操作"
```

---

### Task 3: 式神移动与双方用牌非阻塞动画

**Files:**
- Modify: `core/engine.py:2370-2412`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `tests/test_runtime_trace.py`
- Modify: `tests/test_gui_battle.py`
- Modify: `tests/test_gui_online.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: 统一 `_emit_card_played` 与 Task 2 的非阻塞输入。
- Produces: timeline 动画条目 `{"k":"a","u":uid,"c":card_id,"p":player}`；`BattleScene.animate_card_use` 与式神位置动画。

- [ ] **Step 1: 写失败测试**

在 `tests/test_runtime_trace.py` 增加统一用牌元数据断言：

```python
def test_card_play_has_public_animation_metadata(make_game):
    game = make_game(auto_skip_upgrade=False)
    game.apply({"op": "upgrade", "index": 1})
    card = F.give(game, 0, 10010201)
    game.apply({"op": "play_card", "uid": card.uid})
    entry = next(e for e in game.state.timeline if e.get("k") == "a")
    assert entry == {"k": "a", "u": card.uid, "c": card.id, "p": 0}
```

在 GUI 测试中覆盖：同一式神位置改变时创建动画且最终位置准确；双方用牌条目均创建对应大卡动画，动画存在期间 `_inputs_open()` 仍为真，清理后无残留。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_runtime_trace.py::test_card_play_has_public_animation_metadata tests/test_gui_battle.py -k animation tests/test_gui_online.py -k animation`
Expected: 缺少动画元数据和动画行为。

- [ ] **Step 3: 最小实现**

在 `_emit_card_played` 的统一发点追加：

```python
self.state.timeline.append({"k": "a", "u": uid, "c": cdef.id, "p": player})
```

`HotseatView._enqueue_timeline` 遇到 `k == "a"` 时仅调用动画、不加入文字记录队列。BattleScene 在 `sync_state` 前保留旧手牌位置与卡图，用牌动画从该位置离开；无缓存时回退到对应玩家手牌区。

用 `QPropertyAnimation`/`QVariantAnimation` 实现：式神旧位置到目标位置的短时线性移动；用牌翻转、左侧大卡停留和淡出。新动画停止同图元旧动画，初次渲染、视角切换、交接和重开不播放并清理。动画期间不改变输入门控。

同步更新 `docs/gui-design.md`、`docs/gui-plan.md` 的阶段位置、着色、后台操作和动画口径。

- [ ] **Step 4: 运行相关及全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_runtime_trace.py tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部 PASS。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

- [ ] **Step 5: Commit**

```bash
git add core/engine.py client/gui/battle_scene.py client/gui/battle.py tests/test_runtime_trace.py tests/test_gui_battle.py tests/test_gui_online.py docs/gui-design.md docs/gui-plan.md
git commit -m "feat(gui): 添加式神移动与双方用牌动画"
```

---

### Task 4: 机制文本顺序、卡牌轮廓光与中央多择界面

**Files:**
- Modify: `client/gui/mechanisms.py`
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `tests/test_gui_mechanisms.py`
- Modify: `tests/test_gui_battle.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: 统一 `usage_options(ok/cost/id/reason)`、现有详情弹窗与调度式中央卡牌布局。
- Produces: 按卡面首次出现顺序排列的 YAML 机制说明、按卡牌透明轮廓绘制的操作光效、展示全部潜在选项的中央多择界面。

- [ ] **Step 1: 写失败测试**

覆盖以下行为：机制说明按卡面文本中首次出现的顺序排列且正文来自 `library/mechanisms/*.yaml`；可用卡牌使用卡牌轮廓光而非矩形 tight box，不可用卡牌无光效；多择牌中央并列展示全部选项及不可用原因；仅当合法子选项数大于 1 时边框语义为 green，单一合法选项按 cost 为 blue/yellow。

- [ ] **Step 2: 运行测试确认失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_battle.py -k 'mechanism or contour or border or usage or option'`
Expected: 机制来源/顺序、轮廓绘制、多择展示或绿色计数断言失败。

- [ ] **Step 3: 最小实现**

机制说明加载项目 `library/mechanisms/*.yaml` 的 `name/frame/text/badge/version_date`，按卡面文本首次出现顺序去重排列，不再以 `MECHANISM_TEXTS` 硬编码文本为主要来源。详情中的机制框顺序与说明正文同步。

操作色优先级保持多择绿、免费蓝、常规黄，但 green 仅在实际合法子选项数大于 1 时启用；只有一个合法子选项时按该选项 `cost == 0` 决定 blue/yellow，不可用卡不绘制光效。用卡牌图像 alpha/轮廓掩码绘制加粗、渐变的外轮廓光，禁止回退为矩形 tight box。

多择牌使用时在画面中央并列展示全部潜在选项，布局复用调度式中央展示；所有 `usage_options` 均展示，不可用项不可选并显示 `reason`，合法项仍按统一 `id` 提交，不另建费用或合法性口径。

同步更新 GUI 设计文档。

- [ ] **Step 4: 运行相关及全量验证**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部 PASS。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/mechanisms.py client/gui/widgets.py client/gui/battle_scene.py client/gui/battle.py tests/test_gui_mechanisms.py tests/test_gui_battle.py docs/gui-design.md docs/gui-plan.md
git commit -m "feat(gui): 完善机制说明与多择用牌交互"
```
