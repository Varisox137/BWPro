# thoughts.txt 十项问题修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 thoughts.txt 的十项渲染、牌库、交互、规则与胜负动画问题，并降低选择确认后的全场重绘开销。

**Architecture:** 继续使用引擎结构化事件和 GUI 快照回放；只在 BWPro 内修改实现，BWPDIY 仅保留已提交的改进建议文档。通过定点规则修复、统一牌库布局、选择窗几何计算和图元状态签名复用完成，不改整体缓存协议。

**Tech Stack:** Python 3.14、PySide6、Pillow、pytest、BWPDIY 渲染库。

## Global Constraints

- 不修改 BWPDIY 代码或测试；仅复制其 `evolve_circle.png` 到 BWPro。
- 不修改 `card_data_raw.md`、用户现有 `library/` 和其他素材改动。
- 不改规则事件顺序、联机隐私和文字日志通道；怪力、不屈只修指定规则语义。
- BWPDIY `e7090d1` 已支持气绝倒计时 0；直接使用该能力，不修改其代码或测试。
- 每项先取得真实 RED，再最小实现 GREEN；主上下文复验后分批中文 conventional commit 并 push。
- 测试命令使用 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest ... -n 0`。

---

### Task 1: 同步觉醒资源并消除小卡渲染失败

**Files:**
- Create: `assets/levels/evolve_circle.png`（从 `D:/Programming/BWPDIY/assets/levels/evolve_circle.png` 复制）
- Modify: `client/gui/cardart.py`
- Modify: `docs/gui-design.md`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Preserves: `entity_pixmap(..., snapshot=...)` 和 200ms `countdown/revive` 视觉事件。
- Produces: 使用 BWPDIY `e7090d1` 的非负气绝倒计时支持，过渡帧直接显示 0。

- [ ] **Step 1: 写真实渲染失败测试**

用真实 `entity_pixmap` 覆盖负生命和倒计时 0，并用完整倒计时→复活链覆盖过渡帧：

```python
negative = entity_pixmap(shiki, db, snapshot={"health": -2})
assert negative is not None and not negative.isNull()
zero = entity_pixmap(shiki, db, snapshot={
    "defeated": True, "revive_pending": True, "revive_countdown": 0})
assert zero is not None and not zero.isNull()
# 完整动画链中 pixmap 始终非空，item.size 不跳到文字兜底尺寸
```

另断言新版 `assets/levels/evolve_circle.png` 存在且真实觉醒渲染同时包含星标和圆盘调用。

- [ ] **Step 2: 运行确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py -k 'negative_health_render or revive_zero_render or evolve_circle' -n 0`

Expected: 资源缺失或负生命返回 None 导致 FAIL；倒计时 0 用例在 BWPDIY `e7090d1` 上作为上游支持验证，若已通过不得伪造 RED。

- [ ] **Step 3: 实现呈现钳制并使用新版倒计时能力**

复制圆盘资源。`entity_pixmap` 在使用快照前复制并钳制：

```python
snapshot = dict(snapshot or {})
for key in ("power", "health"):
    value = snapshot.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        snapshot[key] = max(0, value)
```

保留 `revive_pending=True, revive_countdown=0` 到 `defeated_countdown=0` 的现有映射，直接使用 BWPDIY 新版非负整数支持，不加旧帧兜底。

- [ ] **Step 4: 更新 libpng 说明并验证提交**

文档明确“Qt Windows 原生平台窗口的无害上游警告”，不修改 PNG 或 stderr。运行上述测试及 `tests/test_gui_builder.py -k 'entity or cardart'`，GREEN 后提交：

```bash
git commit -m "fix(渲染): 同步觉醒圆盘并保护濒死小卡"
git push
```

---

### Task 2: 修正牌库数量、空库素材与扇形方向

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/ui_assets.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_assets.py`

**Interfaces:**
- Produces: 空库选图 helper、统一 deck 位置/角度计算；普通同步、设置刷新和 resize 共用。
- Preserves: 抽牌动画顶部图元索引：己方 0、敌方 2。

- [ ] **Step 1: 写参数化失败测试**

双方分别设置 3/2/1/0 张牌，断言保留 key、z 顺序和空库素材：

```python
assert own_keys == [("deck_back", 0, i) for i in range(min(3, own_count))]
assert enemy_keys == [("deck_back", 1, i) for i in range(3 - min(3, enemy_count), 3)]
# 空库各只保留己方0/敌方2；deck_out_burn存在为light，否则dark
```

旋转断言为敌方 `[195,205,215]`、己方 `[145,155,165]`，最终图像仍与旧“原图上方向左”逐像素一致；`named_cardbacks()` 不含 `empty_deck_`。覆盖设置刷新和 resize。

- [ ] **Step 2: 运行确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_assets.py -k 'deck_count or empty_deck or deck_orientation or named_cardbacks' -n 0`

Expected: 固定三张、空库无图及旧角度导致 FAIL。

- [ ] **Step 3: 实现统一牌库布局**

数量按 `min(3, len(deck))` 计算；空库读取 `player.ext.get("deck_out_burn") is not None`。特殊图使用独立 helper 裁掉黑色侧栏 `(120,0,392,512)`，再按普通牌背方向处理。

位置使用 `position_index = index if top else 2-index`；图元角度在当前角度基础上加 180°，pixmap 预先旋转 180°抵消。所有同步、设置刷新和 resize 均调用同一 helper，不另写公式。

- [ ] **Step 4: 验证并提交**

Run: 上述参数化测试及既有 deck/hand 动画回归。

Expected: PASS。提交 `fix(对局): 修正牌库数量空库与扇形朝向` 并 push。

---

### Task 3: 修正调度回顾和选择弹窗交互

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/battle.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Produces: 选择视图动态最小高度；选择确认即时关闭/禁用，下一事件循环执行作答。
- Preserves: 选择失败恢复、联机作答次数和主要阶段输入规则。

- [ ] **Step 1: 写布局与回顾失败测试**

```python
# 确认调度 review 后
assert scene.mulligan_uid is None
assert all(item.scale() == 1.0 for item in own_hand_items)
# 六候选、选中放大并出现横向滚动条后
assert option_view.button_rect().bottom() <= option_view.viewport().rect().bottom()
assert dialog.sizeHint().height() >= required_content_height
```

点击选择后先断言旧窗已关闭/禁用，再 `processEvents()` 验证仅作答一次；构造非法答案时恢复选择窗。

- [ ] **Step 2: 运行确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'mulligan_review_scale or choice_dialog_layout or choice_immediate_feedback' -n 0`

Expected: 缩放残留、按钮裁切或同步阻塞导致 FAIL。

- [ ] **Step 3: 实现几何计算与即时反馈**

删除 `ChoiceDialog` 的 450 覆盖，以实际选中卡高、按钮高、间距、边距、边框和横滚动条高度计算最小值；选中变化时 `updateGeometry()` 并更新所属窗口。集中减小顶部与按钮间距。

确认时先关闭/禁用旧窗，`QTimer.singleShot(0, ...)` 执行真实 `answer_pending`；失败恢复同一选择上下文，不重复作答。

- [ ] **Step 4: 验证并提交**

Run: 上述测试及既有 mulligan/discard/search/choice 回归。

Expected: PASS。提交 `fix(交互): 修正调度回顾与选择弹窗布局反馈` 并 push。

---

### Task 4: 修复怪力、不屈和胜负等待

**Files:**
- Modify: `core/engine.py`
- Modify: `client/gui/battle.py`
- Test: `tests/test_data.py`
- Test: `tests/test_combat.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Preserves: 通用 `_change_shield`、`ev.amount` 规则口径和 `visual_busy/animations_settled`。
- Produces: 仅生命扣减使用的 `health_loss`。

- [ ] **Step 1: 写规则与结果失败测试**

怪力默认环境：

```python
assert shiki.shield == -1
assert any("获得 1 点破甲" in line for line in game.state.settle_log)
```

已有 2 护甲时使用结果为 1 护甲；腐坏直拳同样获得破甲；20191212 怪力仍为 0。

不屈：

```python
dealt = game.deal_to_shikigami(ref, 5, source)
assert shiki.health == 1
assert dealt == 5
assert damage_event["amount"] == 5
assert player.ext["damage_taken_turn"] == 5
# 日志含“受到 5 点伤害（生命 3→1）”；吸血来源恢复5
```

热坐/联机致死动画期间结果隐藏，排空后显示；`winner=None` 仍立即显示。

- [ ] **Step 2: 运行确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_data.py tests/test_combat.py tests/test_gui_battle.py tests/test_gui_online.py -k 'guaili or fragile_combat or unyielding or result_waits_visual' -n 0`

Expected: 破甲为0、不屈伤害量被改写、结果提前显示导致 FAIL。

- [ ] **Step 3: 实现最小规则与结果修复**

战斗牌入口：

```python
kind = "shield" if shield > 0 else "fragile"
self._change_shield(ref, abs(shield), reason, kind=kind)
```

仅在 `shield != 0` 时调用。不屈使用 `health_loss = min(ev.amount, s.health - 1)`，不改 `ev.amount`；扣血、日志生命区间使用该值，其余口径保持原伤害。

结果入口：

```python
if self.battle_scene.visual_busy:
    return
```

依赖既有 `animations_settled` 再次 `_render_state`，`winner=None` 分支绕过等待。

- [ ] **Step 4: 验证并提交**

Run: 上述测试及 combat/damage/result 相关回归。

Expected: PASS。提交 `fix(规则): 修正怪力不屈并延后胜负动画` 并 push。

---

### Task 5: 复用未变化图元并完成整合验证

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Produces: 式神/手牌图元 render signature；未变化刷新不调用 `entity_pixmap/card_pixmap/cardback_pixmap`。
- Preserves: 所有影响视觉内容的字段变化、快照事件、牌框偏好和主题/卡背设置刷新。

- [ ] **Step 1: 写调用次数失败测试**

```python
view.refresh()
entity_calls.clear()
card_calls.clear()
view.refresh()
assert entity_calls == []
assert card_calls == []
# 修改生命、形态、等级、display render后，仅受影响图元重新求图
```

卡背设置、牌框偏好、视角切换、动画快照和 reset 必须使签名失效；不能用时间阈值测试性能。

- [ ] **Step 2: 运行确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'unchanged_render_signature' -n 0`

Expected: 未变化图元仍重复调用 renderer，FAIL。

- [ ] **Step 3: 实现显式状态签名**

式神签名包含：式神/形态/觉醒 id、等级、基础与永久/临时身材、当前力量/生命/上限、护甲、战力、能量、普通/气绝倒计时、气绝与倒计时隐藏状态、座位和主题。手牌签名包含：卡牌 id、revealed、显示 render/keywords/usage 影响边框的内容、牌框偏好、等级颜色、居中/普通尺寸和主题。把签名存于图元；相同则复用 pixmap，不同才调用渲染。

签名不包含对象 id 或时间戳；视角切换、reset、设置刷新显式清空。快照事件继续绕过该缓存直接按事件快照绘制。

- [ ] **Step 4: 更新文档并运行整合回归**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_builder.py tests/test_gui_online.py tests/test_gui_assets.py tests/test_data.py tests/test_combat.py tests/test_damage.py -n 0`

Expected: PASS；随后运行项目固定完整 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q` 和 `git diff --check`。

- [ ] **Step 5: 提交**

```bash
git commit -m "perf(对局): 复用未变化图元并同步修复文档"
git push
```
