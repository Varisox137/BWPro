# GUI 对局反馈与详情修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正手牌/式神数值颜色、对局边距与按钮、终局只读交互、出牌动画卡图和式神详情四列布局。

**Architecture:** 在 `cardart` 渲染负载层统一计算颜色，在现有 `BattleScene`/`HotseatView`/`OnlineBattleView` 状态链路上修正交互，在 `details.py` 重组只读详情。保留引擎、协议和 DIY 渲染器边界，不引入新的游戏状态或费用口径。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计唯一来源：`docs/superpowers/specs/2026-10-29-gui-battle-feedback-design.md`。
- 不修改引擎结算、卡牌数据、协议字段和卡组格式。
- `BattleScene` 继续保持等比缩放，不恢复拉伸或裁切。
- 详情第三列是全部额外状态，第四列是前两类卡牌及第三列涉及的机制；无内容不留空列。
- 所有新行为先写失败测试并实际确认 RED，再最小实现到 GREEN。
- Windows 测试解释器为 `./.venv/Scripts/python.exe`，收尾全量命令为 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 手牌与式神小卡数值颜色

**Files:**
- Modify: `client/gui/cardart.py:592-724`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Consumes: `card_pixmap(..., display=dict)` 的实时数值和 `entity_pixmap(shiki, ..., form=...)`。
- Produces: DIY 负载中的 `<field>_color` 值 `red`/`green`/`None`；不改变其他函数签名。

- [ ] **Step 1: 写手牌颜色和形态基准失败测试**

在 `tests/test_gui_builder.py` 增加：

```python
def test_card_runtime_stat_colors_follow_original_values(qapp, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from client.gui import cardart
    from tests import factories

    definition = factories.card(
        10010151, card_type="form", form_power=2, form_health=5)
    database = factories.db_of([factories.shiki(100101)], [definition])
    seen = {}
    monkeypatch.setattr(
        cardart, "_cached_runtime_card_pixmap",
        lambda _key, payload, _layout, _root, *_args:
        seen.update(json.loads(payload)))
    for key, original in (("power", 2), ("health", 5)):
        for delta, expected in ((-1, "red"), (0, None), (1, "green")):
            cardart.card_pixmap(definition, database,
                                library_dir=tmp_path / "empty",
                                display={key: original + delta})
            assert seen[f"{key}_color"] == expected
```

扩展 `test_entity_stat_colors_follow_base_permanent_reference`：注册 `form_power=2, form_health=6` 的形态，令 `perm_power=1, perm_health=2`，分别断言力量基准为 3、生命上限基准为 8；当前力量 2/3/4 对应红/白/青，未受伤生命上限 7/8/9 对应白/白/青，受伤仍为红。另保留既有气绝断言。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py -k 'runtime_stat_colors or entity_stat_colors'`
Expected: 手牌缺少 `<field>_color`，或形态仍按式神基础值计算。

- [ ] **Step 3: 最小实现颜色比较**

在 `_card_pixmap_impl` 中保留覆盖前原值，再写入颜色：

```python
original_stats = {key: payload.get(key) for key in display_stats}
payload.update(display_stats)
for key, original in original_stats.items():
    current = payload.get(key)
    if type(original) is int and type(current) is int:
        payload[f"{key}_color"] = (
            "red" if current < original else
            "green" if current > original else None)
```

在 `entity_pixmap` 中只改基准来源：

```python
definition = db.shikigami[shiki.id]
base_power = (form.form_power if form is not None else definition.power) \
    + getattr(shiki, "perm_power", 0)
base_health = (form.form_health if form is not None else definition.health) \
    + getattr(shiki, "perm_health", 0)
```

保留现有生命受伤优先红色和气绝显示逻辑。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py -k 'stat_colors or runtime_stat_colors or hand_art or entity_art'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/cardart.py tests/test_gui_builder.py
git commit -m "fix(gui): 修正动态数值颜色基准"
git push
```

---

### Task 2: 对局边距、记录按钮、头像详情与动画卡图

**Files:**
- Modify: `client/gui/app.py:97-227`
- Modify: `client/gui/battle.py:161-207,350-367`
- Modify: `client/gui/battle_scene.py:62-118,381-417,713-784`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: 现有 `MainWindow._sync_game_menu_button()`、`BattleDragController.release()` 和 `animate_card_use()`。
- Produces: 对局页零外边距、40px 记录按钮、仅头像打开详情、整数高度的动画大卡图；不改变场景信号签名。

- [ ] **Step 1: 写布局、头像和动画失败测试**

新增或更新测试，核心断言如下：

```python
def test_battle_page_has_zero_outer_margins(qapp, db):
    win = MainWindow(db)
    hotseat = win.pages["hotseat"]
    win.go("hotseat")
    hotseat.stack.setCurrentWidget(hotseat.battle_page)
    win._sync_game_menu_button()
    margins = win.outer.contentsMargins()
    assert (margins.left(), margins.right()) == (0, 0)
    win.go_menu()
    win._sync_game_menu_button()
    margins = win.outer.contentsMargins()
    assert (margins.left(), margins.right()) == (12, 12)
    win.close()
```

把记录按钮断言改为 `40` 和 `border-radius: 20px`，并用 `QFontMetrics` 检查两行文本高度小于按钮内可用高度。删除独立牌手按钮后，断言场景中不存在 `("player_detail", pi)` 控件；点击头像圆形区域会调用 `show_player_detail`，点击头像外且牌手不是合法目标时不调用，牌手是合法目标时仍优先选择目标。

动画测试捕获 DIY 尺寸并覆盖失败回退：

```python
def test_card_use_animation_uses_integer_height_and_keeps_fallback_art(
        qapp, view, monkeypatch):
    from PySide6.QtGui import QPixmap
    start(view, mulligan=False)
    scene = view.battle_scene
    card = view.game.state.players[0].hand[0]
    heights = []
    monkeypatch.setattr(
        "client.gui.battle_scene.card_pixmap",
        lambda *_args, **kwargs: heights.append(kwargs["height"]) or None)
    scene.animate_card_use(card.uid, card.id, 0)
    animation = scene._card_use_animations[0]
    source = scene._card_use_sources[animation]
    item = scene._card_use_items[animation]
    fallback = QPixmap(20, 20)
    item.set_art(fallback)
    animation.setCurrentTime(int(animation.duration() * 0.2))
    assert heights == [312]
    assert not item.pixmap.isNull()
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'outer_margins or log_button or player_detail or integer_height'`
Expected: 外边距非零、按钮 32px、独立按钮仍存在或动画高度为 `312.0` 且空图覆盖原图。

- [ ] **Step 3: 最小实现布局与交互**

`MainWindow` 保存 `self.outer = outer`，连接热坐和联机内部 stack 的 `currentChanged` 到 `_sync_game_menu_button`。该方法计算当前是否真正位于对局页：

```python
in_battle = (
    page is self.pages["hotseat"]
    and self.pages["hotseat"].stack.currentWidget()
        is self.pages["hotseat"].battle_page
) or (
    page is online and online.stack.currentWidget() is online.battle)
margin = 0 if in_battle else 12
self.outer.setContentsMargins(margin, margin, margin, margin)
```

`go_menu()` 也调用 `_sync_game_menu_button()`。记录按钮尺寸改 40，样式圆角改 20；删除创建 `player_detail` 按钮的循环及 `layout_positions` 对应项。

在 `BattleDragController.release()` 的非拖拽详情分支中，牌手不是合法目标时要求释放点位于 `QRectF(2, 2, 96, 96)` 内；合法目标保持现有优先路径。

- [ ] **Step 4: 修复动画尺寸与回退并运行相关测试**

使用 `height=int(round(big_size.height()))`。在 `_update_card_use` 翻面时仅当 `source["big_pixmap"]` 非空才调用 `set_art`，否则保留原图。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'outer_margins or log_button or player_detail or card_use_animation or integer_height'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/app.py client/gui/battle.py client/gui/battle_scene.py tests/test_gui_battle.py tests/test_gui_online.py
git commit -m "fix(gui): 调整对局布局与出牌动画"
git push
```

---

### Task 3: 终局立即提示与只读详情

**Files:**
- Modify: `client/gui/battle.py:532-583`
- Modify: `client/gui/battle_scene.py:338-417`
- Modify: `client/gui/online.py:245-287`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: `state.winner`、现有结果控件、timeline 队列和详情信号。
- Produces: `BattleScene.game_over: bool`；终局时允许只读 press/release，游戏操作仍由 `_inputs_open()` 禁止。

- [ ] **Step 1: 写本地和联机立即终局失败测试**

本地测试在队列非空时设置终局并刷新，不消费队列：

```python
def test_game_over_is_immediate_and_details_remain_clickable(qapp, view, monkeypatch):
    start(view, mulligan=False)
    view.timeline_queue[:] = [(0, "尚未播放")]
    view.game.state.winner = 0
    view.refresh()
    assert not view.result_banner.isHidden()
    assert not view._inputs_open()
    assert view.battle_scene.result_item.zValue() > 110

    seen = []
    monkeypatch.setattr(view, "show_shiki_detail", seen.append)
    item = view.battle_scene.cards[("shiki", 0, 0)]
    view.battle_scene.drag_controller.press(item, item.scenePos())
    view.battle_scene.drag_controller.release(item.scenePos())
    assert seen == [item.payload]
    view.show_log()
    assert not view.log_dialog.isHidden()
```

将 `test_game_over_waits_for_timeline_playback` 改名并重写为 `test_game_over_is_immediate_during_timeline_playback`：调用 `show_game_over` 后立即断言结果可见，再逐步消费记录并断言不重复弹窗或清除记录。增加终局后 `upgrade/assault/play_card/end_turn` 仍不可用的既有门控断言。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'game_over'`
Expected: 本地仍等 timeline，联机仍写入 `_pending_game_over`，详情 press 被拒绝。

- [ ] **Step 3: 最小实现终局状态与只读点击**

`BattleScene.__init__()` 初始化 `self.game_over = False`，`BattleScene.sync_state()` 设置 `self.game_over = game.state.winner is not None`。`BattleDragController.press()` 在输入关闭时，仅额外放行终局下的已揭示手牌、式神和牌手：

```python
readonly_detail = (
    self.scene.game_over and item.key[0] in ("hand", "shiki", "player")
    and (item.key[0] != "hand" or item.revealed))
if not self.scene.inputs_open and not item.targetable and not readonly_detail:
    return False
```

`move()` 继续在输入关闭时取消，保证不能拖拽操作。本地 `_render_state()` 改为 `if state.winner is not None: self._show_result()`；创建结果控件时保存 `self.battle_scene.result_item` 和 `result_back_item`，并将两者 z-value 设为 `DRAG_Z + 20`。联机 `show_game_over()` 直接显示，不再读写 `_pending_game_over`，`play_next_timeline()` 不再延迟触发结果。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'game_over or detail or log_dialog'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle.py client/gui/battle_scene.py client/gui/online.py tests/test_gui_battle.py tests/test_gui_online.py
git commit -m "fix(gui): 终局立即提示并保留只读详情"
git push
```

---

### Task 4: 式神详情额外状态与机制四列布局

**Files:**
- Modify: `client/gui/details.py:1-205`
- Modify: `client/gui/mechanisms.py:112-154`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_mechanisms.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: `shiki_status_lines(game, ref, viewer)`、`card_mechanisms()` 和 `mechanism_panel()`。
- Produces: `shikigami_mechanisms(game, ref, status_texts=())`；详情列顺序 `main/form/status/mechanisms`，第三、四列 `max_height=336`。

- [ ] **Step 1: 写详情顺序、状态和机制失败测试**

使用既有 `test_shiki_runtime_details_cover_registered_state` 的 fixture 数据，捕获 `ShikigamiDetailDialog`，增加：

```python
assert dialog.column_names == ["main", "form", "status", "mechanisms"]
assert dialog.form_card.size() == dialog.main_art_label.size()
assert dialog.status_panel.maximumHeight() == 336
assert dialog.mechanism_panel.maximumHeight() == 336
assert not hasattr(dialog, "status_label")
```

无形态、无额外状态、无机制时分别断言对应列不存在，而不是空占位。保留秘密延迟目标按 viewer 隐藏的测试，但改为从第三列机制框数据 `dialog.status_mechanisms` 检查文本。

机制顺序测试：

```python
def test_shikigami_mechanisms_include_extra_status_keywords_in_order(
        qapp, view):
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    shiki.keywords.append("critical")
    ref = Ref(player=0, shikigami=0)
    names = [item["name"] for item in shikigami_mechanisms(
        view.game, ref, status_texts=["获得[吸血]与[暴击]"])]
    assert names[-2:] == ["吸血", "暴击"]
    assert names.count("暴击") == 1
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_mechanisms.py -k 'shiki or shikigami_mechanisms'`
Expected: 详情仍为旧上下布局，机制提取不接受 `status_texts`。

- [ ] **Step 3: 拆分额外状态与机制提取**

将 `shiki_status_lines` 收敛为额外状态文本：保留永久/临时/动态修正、关键字、攻击强化、免疫、眩晕、灵咒、延迟能力等；移除基础等级/身材行，以及主卡、觉醒和形态的原文（这些由前两列卡牌展示）。秘密目标过滤逻辑原样保留。

`shikigami_mechanisms` 改为：

```python
def shikigami_mechanisms(game, ref, status_texts=()) -> list[dict]:
    # 先保留主卡与形态 card_mechanisms 的既有合并顺序。
    # 再追加当前关键字，并对每条第三列文本调用 _add_text。
    mechanisms = card_mechanisms(main_def)
    # 既有形态合并代码保持不动。
    for text in status_texts:
        _add_text(mechanisms, text)
    return mechanisms
```

当前关键字和攻击强化仍去重合并；灵咒原文通过第三列文本参与方括号机制提取，不再把灵咒自身当作第四列的独立机制说明。

- [ ] **Step 4: 实现四列布局并运行相关测试**

在 `ShikigamiDetailDialog` 中建立同一 `QHBoxLayout`：主卡、同尺寸形态、第三列状态机制框、第四列关键字机制框。第三列将每条状态转换为 `{"name": "额外状态", "frame": "skill", "text": line}`，调用 `mechanism_panel(..., max_height=336)`；第四列调用同一面板。保存 `column_names`、`status_mechanisms` 供外部只读检查，删除下方原完整状态 `QScrollArea`。

无内容时 `mechanism_panel` 返回 `(None, [])`，不添加列；有列时使用 stretch 让后两列分配剩余宽度。形态 `CardWidget` 固定为主卡实际尺寸，保持卡图等比。同步 `docs/gui-design.md` 与 `docs/gui-plan.md` 的详情顺序和终局只读口径。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_mechanisms.py -k 'shiki or shikigami_mechanisms or secret_delayed'`
Expected: 全部 PASS。

- [ ] **Step 5: 全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/details.py client/gui/mechanisms.py tests/test_gui_battle.py tests/test_gui_mechanisms.py docs/gui-design.md docs/gui-plan.md
git commit -m "feat(gui): 重排式神额外状态与机制详情"
git push
```
