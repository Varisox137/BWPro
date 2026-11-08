# 对局视觉时序与 GUI 回归修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用结构化视觉事件和快照回放修复战斗、热坐、运势、倒计时、升级与数值动画，并解决五项旧 GUI 回归。

**Architecture:** 引擎规则状态立即结算，只在实际执行点追加视觉事件和快照；`BattleScene` 按 FIFO/同组并行播放，在队列未空时禁止最终状态抢跑。`HotseatView` 以回合开始边界拆分旧玩家回合结束动画与新玩家回合开始动画。

**Tech Stack:** Python 3.14、PySide6、pytest、pytest-xdist、BWPDIY 渲染适配层。

## Global Constraints

- 不改变规则结算、插入结算、击杀检查、光环判断和文字日志语义。
- 新视觉事件不泄露敌方未展示手牌的卡牌 id。
- 仅升级阶段等待视觉队列；主要阶段保持非阻塞操作。
- 不修改 `card_data_raw.md`、本任务无关的 `library/` 修改及两张未跟踪空牌库素材。
- 不修改 sibling BWPDIY 源码；透明兜底在 BWPro 内完成。
- 每项行为先写并运行失败测试，再写最小实现；每任务定向验证后中文 conventional commit 并 push。
- 测试命令使用 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest ... -n 0`。

---

### Task 1: 统一布局并修复旧回归

**Files:**
- Modify: `client/gui/battle_scene.py:103-128,1134-1146,1444-1446`
- Modify: `client/gui/cardart.py:671-746`
- Modify: `tests/test_gui_battle.py:1792-1814,3685-3722`
- Modify: `tests/test_gui_builder.py:997-1005,1175-1188`
- Modify: `tests/test_gui_battle.py:1026-1046,1073-1088`

**Interfaces:**
- Produces: `combat_position(scene_width: int, top: bool) -> QPointF`，供普通布局和移动动画共用。
- Preserves: `layout_positions(...)` 既有返回结构。

- [ ] **Step 1: 加强布局失败测试**

将己方牌库断言改为镜像角度和等差偏移，并将战斗区动画终点断言为普通布局坐标：

```python
assert [item.rotation() for item in own] == [-35, -25, -15]
assert [item.rotation() for item in own] == [-enemy[2-i].rotation() for i in range(3)]
assert own[1].pos() - own[0].pos() == own[2].pos() - own[1].pos()
expected = layout_positions(view.game, view.viewer,
                            scene_width=scene.layout_width)[("shiki", 0, 0)]
# 将测试式神置入战斗区后取 expected；move(combat) 的 endValue 必须等于 expected
```

- [ ] **Step 2: 运行测试确认布局断言失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py::test_deck_backs_match_reference_size_and_orientation tests/test_gui_battle.py::test_move_visual_uses_event_zone_instead_of_final_state -n 0`

Expected: 己方角度及战斗区横坐标 FAIL。

- [ ] **Step 3: 实现统一坐标和镜像角度**

```python
def combat_position(scene_width: int, top: bool) -> QPointF:
    return QPointF(646 + (scene_width - SCENE_WIDTH) / 2, 220 if top else 460)
```

在 `layout_positions` 和 `_start_visual_event(move)` 共用该函数；牌库旋转使用与位置相同的 `fan_index`：

```python
rotation = 15 + fan_index * 10
back.setRotation(rotation if pi != viewer else -rotation)
```

- [ ] **Step 4: 修正五项旧回归的测试与真实兜底**

- `test_entity_native_height` 在导入 `entity` 前调用：

```python
from client.gui import cardart
cardart._renderer(str(cardart.portrait.bwpdiy_root().resolve()))
from bwpdiy.render import entity
```

- 护甲测试在读取最终图元前调用既有 `settle(view)`。
- 小卡 renderer 测试使用集合包含，不限制重绘次数：

```python
expected = {id(s) for p in view.game.state.players for s in p.shikigami}
assert expected <= {id(call[0]) for call in calls}
```

- 保留透明兜底只读测试；在 `_card_pixmap_impl` 的最外层异常路径返回内存应急图，不写缓存：

```python
except Exception as error:
    log_render_failure("card", cdef.id, portrait.bwpdiy_root(), error, path)
    pixmap = QPixmap(360, 504 if height is None else height)
    pixmap.fill(Qt.transparent)
    _paint_placeholder_name(pixmap, cdef.name, _placeholder_color(), entity=False)
    return pixmap
```

实施时按 `height` 保持约 5:7 比例，避免非等比拉伸。

- [ ] **Step 5: 定向验证并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py::test_entity_native_height tests/test_gui_builder.py::test_cardart_transparent_fallback_never_writes_disk tests/test_gui_battle.py::test_assault_timer_finishes_and_refreshes_public_state tests/test_gui_battle.py::test_summoned_fifth_shikigami_keeps_refresh_and_next_upgrade_available tests/test_gui_battle.py::test_battle_entities_use_diy_small_card_renderer tests/test_gui_battle.py::test_deck_backs_are_symmetric_horizontal_cards_and_hide_when_empty tests/test_gui_battle.py::test_deck_backs_match_reference_size_and_orientation tests/test_gui_battle.py::test_move_visual_uses_event_zone_instead_of_final_state -n 0`

Expected: 8 passed。执行 `git diff --check` 后提交：

```bash
git commit -m "fix(对局): 统一牌库与战斗区布局并修复渲染回归"
git push
```

---

### Task 2: 修正战斗呈现状态与气绝顺序

**Files:**
- Modify: `core/engine.py:3094-3123,4779-4830,5520-5555`
- Modify: `client/gui/battle_scene.py:1054-1109,1134-1147,1231-1290,1379-1528`
- Test: `tests/test_gui_battle.py:3725-3749`
- Test: `tests/test_gui_assets.py`

**Interfaces:**
- Consumes: Task 1 `combat_position(scene_width, top)`。
- Produces: `defeated` 和气绝回位 `move` 事件的 `r` 快照；GUI 在 `_start_visual_event` 才应用气绝副作用。

- [ ] **Step 1: 写逐步 GUI 战斗失败测试**

构造双方同归于尽的出击，逐步推进 `_visual_animations` 和 `_move_animations`，每步断言：

```python
# assault 未完成：没有 move
# move 未完成：没有 damage
# damage 并行结束而 stat 未开始：目标未进入 _defeat_visuals
# stat 显示生命 0：仍未提前灰阶
# defeated 并行开始：两目标才应用气绝快照
# defeated 结束：显示同一快照中的 revive_countdown=3
# return 并行结束：双方以气绝状态回准备区
```

在每个阶段额外调用 `view._render_state()`，确认最终状态不会抢跑或吞掉结构化移动。

- [ ] **Step 2: 运行确认气绝不副作用测试失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k combat_visual_defeat_snapshot -n 0`

Expected: 气绝状态在前置动画完成前出现，FAIL。

- [ ] **Step 3: 给气绝与回位事件附快照并延迟副作用**

在 `check_defeated` 完成气绝字段设置后：

```python
snapshot = self._stat_event(ref, defeat_group)["r"]
self.state.timeline.append({"k": "v", "v": "defeated", "p": ref.player,
                            "s": ref.shikigami, "g": defeat_group, "r": snapshot})
# 回位 move 携带同一 snapshot
```

GUI 从 `play_visual_event` 删除 `_defeat_visuals.add/_refresh_defeated_entity`，移到 `_start_visual_event(defeated)`；结束时使用 `event["r"]`：

```python
self._refresh_defeated_entity(*key, snapshot=event.get("r"))
```

`sync_state(defer_art=True)` 时，已有图元不执行隐式 `_animate_position`；新建图元仍可放最终位置。`_refresh_all_art` 仅在视觉和移动队列均排空后执行最终兜底。

- [ ] **Step 4: 验证战斗时序并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'combat_damage_defeat_return or combat_visual_defeat_snapshot or move_visual' tests/test_gui_assets.py -n 0`

Expected: PASS。提交 `fix(对局): 对齐战斗伤害气绝与回位动画` 并 push。

---

### Task 3: 修正运势事件与动态光环插入点

**Files:**
- Modify: `core/engine.py:382-509,6588-6642`
- Modify: `core/actions.py:3638-3670`
- Modify: `client/gui/battle_scene.py:1054-1068`
- Test: `tests/test_luck_cards.py`
- Test: `tests/test_gui_assets.py`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Produces: `luck_dice`、`luck_reroll`、`luck_result`；旧 `luck` 仅作 GUI 兼容输入。
- Produces: 动态光环实际变化时的普通 `stat` 事件。

- [ ] **Step 1: 写运势与光环顺序失败测试**

重投用例断言：

```python
assert [(e["v"], e.get("dice")) for e in visual] == [
    ("luck_dice", 1), ("luck_reroll", 5),
    ("luck_dice", 5), ("luck_result", 5)]
```

增加重投后点数相同用例，仍应出现第二个 `luck_dice`。双方判定用例断言双方首骰同组且早于所有结果。出千成功用例断言：

```python
assert kinds.index("luck_result") < aura_stat_index < kinds.index("move") < kinds.index("damage")
assert aura_stat["r"]["power"] == old_power + 2
```

- [ ] **Step 2: 运行确认旧顺序失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_luck_cards.py tests/test_gui_assets.py -k 'reroll or luck_visual or aura' -n 0`

Expected: 旧 `luck` 顺序及缺失光环 `stat` 导致 FAIL。

- [ ] **Step 3: 在引擎执行点发细粒度事件**

首投循环完成后、`emit(on_luck_judge)` 前为每个事件追加 `luck_dice`；`luck_reroll` 删除首投 `luck` 补发；最终结果阶段仅在 `ev.get("rerolled")` 时补新 `luck_dice`，随后始终追加 `luck_result`。

`_refresh_stat_auras` 重算前保存每个式神的 `dyn_power/dyn_health`，重算及生命钳制完成后收集 diff：

```python
changed = []
for pi, player in enumerate(self.state.players):
    for i, shiki in enumerate(player.shikigami):
        old_power, old_health = previous[(pi, i)]
        if (shiki.dyn_power, shiki.dyn_health) != (old_power, old_health):
            changed.append(Ref(player=pi, shikigami=i))
group = id(changed) if len(changed) > 1 else None
for ref in changed:
    self._visual_stat(ref, group)
```

无 diff 不发事件。GUI 白名单加入 `luck_dice/luck_result`，保留旧 `luck` 拆分兼容。

- [ ] **Step 4: 验证日志不重复并提交**

断言 `state.log` 和文字 timeline 的“运势重置”各恰好一次；运行：

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_luck_cards.py tests/test_gui_assets.py tests/test_gui_battle.py -k 'luck or reroll or aura or dice' -n 0`

Expected: PASS。提交 `fix(对局): 修正运势重投与动态光环动画时点` 并 push。

---

### Task 4: 补倒计时、归零与复活快照事件

**Files:**
- Modify: `core/engine.py:3094-3123,4439-4472,4575-4646` 及直接修改复活倒计时的路径
- Modify: `core/actions.py` 中 `countdown_delta`、山兔能力及其他复活倒计时写入点
- Modify: `client/gui/cardart.py:767-876`
- Modify: `client/gui/battle_scene.py:1054-1109`
- Test: `tests/test_countdown.py`
- Test: `tests/test_luck_cards.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: `countdown`、`countdown_proc`、`revive`，均使用 `r` 快照。
- Extends: `_stat_event` 快照包含 `countdown/revive_countdown/revive_pending`。

- [ ] **Step 1: 写倒计时与复活失败测试**

覆盖自然减少、效果减少、循环倒计时归零、一次倒计时移除、山兔使气绝倒计时 1→0：

```python
assert kinds == ["countdown", "countdown_proc", "countdown"]  # 循环型
revive_zero = next(e for e in visual if e["v"] == "countdown"
                   and e["r"]["revive_countdown"] == 0)
revive = next(e for e in visual if e["v"] == "revive")
assert revive_zero["r"]["defeated"] is True
assert revive_zero["r"]["revive_pending"] is True
assert revive["r"]["defeated"] is False
```

永久气绝 0 仍显示 infinity；仅 `revive_pending=True` 的 snapshot 显示数字 0。

- [ ] **Step 2: 运行确认事件缺失**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_countdown.py tests/test_luck_cards.py -k 'visual or revive_pending' -n 0`

Expected: 缺少新事件，FAIL。

- [ ] **Step 3: 实现统一倒计时视觉辅助**

新增内部辅助，在实际字段修改后追加快照，并按原路径调用 `_revive`：

```python
def _visual_countdown(self, ref, *, revive_pending=False):
    event = self._stat_event(ref)
    event["v"] = "countdown"
    event["r"]["revive_pending"] = revive_pending
    self.state.timeline.append(event)
```

`_revive` 在状态恢复后、能力重新注册前追加 `revive`；`_countdown_zero` 在能力块执行前追加 `countdown_proc`，重置/移除后再追加对应 `countdown`。GUI 将三类事件接入与 `stat` 相同的 200ms 快照刷新；`entity_pixmap` 优先读取快照倒计时字段。

- [ ] **Step 4: 验证并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_countdown.py tests/test_luck_cards.py tests/test_gui_builder.py -k 'countdown or revive or entity' -n 0`

Expected: PASS。提交 `feat(对局): 补齐倒计时与复活视觉事件` 并 push。

---

### Task 5: 修复热坐交接和升级阶段门控

**Files:**
- Modify: `core/engine.py:4303-4325`
- Modify: `client/gui/battle.py:439-512,545-597,854-928`
- Modify: `client/gui/battle_scene.py:790-843,1260-1290`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Produces: 引擎边界 `{k:"v", v:"turn_start", p:new_active}`。
- Produces: `BattleScene.visual_busy -> bool` 与 `animations_settled` 信号。
- Consumes: Task 4 的倒计时/复活事件。

- [ ] **Step 1: 写热坐与连续升级失败测试**

覆盖：

```python
# 回合结束效果未播完：handoff 不可见，旧视角动画继续
# 旧视觉队列排空：才显示切换玩家
# 确认后：新视角才播 turn_start 后事件和 your_turn 横幅
# 回合开始视觉未排空：无升级遮罩，upgrade() 返回 False
# 视觉排空而文字仍播放：允许升级
# free 规则、两次升级：第一次动画期间不可再次升级，结束后轮廓 cacheKey/焦点路径更新
```

新回合先由旧玩家完成 `pending_choice` 时，不得由旧视角消费 `_last_turn_key`。

- [ ] **Step 2: 运行确认交接与升级锁失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'handoff_visual or upgrade_visual_busy or consecutive_upgrade_focus' -n 0`

Expected: 动画被清理或输入提前开放，FAIL。

- [ ] **Step 3: 实现边界拆分与 busy 信号**

`_start_turn` 在回合开始结算前追加 `turn_start`。`HotseatView` 将边界前 `k="a"/"v"` 留给旧视角，边界及之后统一暂存；只有视觉和移动队列排空后才 `_begin_handoff`。确认后用同一 dispatch 重放两类暂存条目。

`BattleScene` 增加：

```python
@property
def visual_busy(self) -> bool:
    return bool(self._visual_animations or self._visual_queue or self._move_animations)
```

队列排空并发 `animations_settled`；`HotseatView` 连接 `_render_state()`。`_inputs_open` 仅在 `phase=="upgrade" and visual_busy` 时返回 False，并避免 busy 时显示升级焦点。`_refresh_all_art` 后调用 `_sync_focus()` 和 `_sync_upgrade_badges()`。回合横幅仅在无 pending choice 或 active==viewer 时更新 `_last_turn_key`。

- [ ] **Step 4: 验证并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'handoff or upgrade or turn_banner or nonblocking' -n 0`

Expected: PASS，主要阶段非阻塞旧测试保持通过。提交 `fix(热坐): 保留交接动画并门控升级阶段` 并 push。

---

### Task 6: 实现抽牌与生成入手动画

**Files:**
- Modify: `core/engine.py:2779-2828`
- Modify: `client/gui/battle_scene.py:874-907,1016-1027,1054-1068,1379-1614`
- Test: `tests/test_gui_assets.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `{k:"v", v:"hand", p, u, from, reason}`；无卡牌 id。
- Produces: 手牌目标键 `("hand", uid)`，与式神/牌手动画目标隔离。

- [ ] **Step 1: 写入手事件、隐私和 GUI 失败测试**

引擎断言抽牌/生成/回手有 `hand`，爆牌没有；服务器转发敌方事件不含 `c/card/id`。GUI 断言：

```python
# 事件未开始：最终槽位的新手牌隐藏
# 抽牌开始：从对应牌库位置移动；生成从对应牌手区域移动
# 敌方未展示卡：pixmap 为卡背
# 多张抽牌：按 FIFO 逐个移动，结束仅一个图元
# reset/handoff：无隐藏手牌残留
```

- [ ] **Step 2: 运行确认事件与动画缺失**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_assets.py tests/test_gui_battle.py tests/test_server.py -k 'hand_visual or hand_animation or hand_privacy' -n 0`

Expected: FAIL。

- [ ] **Step 3: 实现统一发点与手牌移动**

在 `move_card` 完成非爆牌入手钩子后追加事件：

```python
if to_zone == "hand" and not burst:
    self.state.timeline.append({"k": "v", "v": "hand", "p": pi, "u": card.uid,
                                "from": src_zone, "reason": reason})
```

GUI 从本次增量收集待播 uid，创建最终图元后先隐藏；`_start_visual_event(hand)` 根据来源设置起点、显示并复用 `_animate_position`，目标为缓存最终槽位。若 uid 已不在手牌则跳过。`_visual_target_key` 返回 `("hand", event["u"])`。

- [ ] **Step 4: 验证并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_assets.py tests/test_gui_battle.py tests/test_server.py -k 'hand or draw or generate or privacy' -n 0`

Expected: PASS。提交 `feat(对局): 增加抽牌与生成入手动画` 并 push。

---

### Task 7: 合并同源数值刷新并补零伤害

**Files:**
- Modify: `core/engine.py:3094-3123,4890-5130` 及 `_resolve_block` 的效果边界信息
- Modify: `core/actions.py:2195-2199,3179-3209,4798`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_mechanics.py`
- Test: `tests/test_damage.py`
- Test: `tests/test_combat.py`

**Interfaces:**
- Consumes: 既有 `stat`、`damage` 和 `_horizon_stack`。
- Produces: 同效果相邻 `stat` 合并；正伤害被非免疫防护归零时的 `damage(amount=0)`。

- [ ] **Step 1: 写合并边界和零伤害失败测试**

送祝福基础/增强和森之佑同目标只产生一个 `stat`，快照含最终力量/生命/护甲；多目标共享 `g`。构造“增益→伤害→增益”及嵌套触发，断言不得跨边界合并。

零伤害参数化：

```python
# shield/reduction/barrier 将正伤害归零：恰好一个 damage(amount=0)
# 原始0伤、immune、cancel、转移/转化：没有 damage(amount=0)
# -0 仍无 on_damage、不扣血、不触发吸血/必杀
```

GUI 直接播放 `damage(amount=0)`，断言生成非空 `-0` 图层并居中。

- [ ] **Step 2: 运行确认旧行为失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py tests/test_damage.py tests/test_combat.py -k 'stat_merge or zero_damage_visual' -n 0`

Expected: 多余 `stat` 或缺少 `-0`，FAIL。

- [ ] **Step 3: 实现相邻合并与统一零伤发点**

`_visual_stat` 仅在当前效果 horizon 相同、上一视觉事件为同目标 `stat` 且中间无其他视觉事件时更新其 `r`；否则追加。不同效果块和嵌套触发使用不同 horizon，禁止合并。

新增 `_visual_damage_zero(target, group)` 只供明确的非免疫归零分支调用；在护甲、屏障、减伤、覆写/封顶为 0 的首先终止原因处调用。原始 0 伤和 immune/cancel/转化分支不调用，规则提前返回保持不变。

- [ ] **Step 4: 验证并提交**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py tests/test_damage.py tests/test_combat.py -k 'stat or damage or shield or barrier or immune' -n 0`

Expected: PASS。提交 `fix(对局): 合并同源数值刷新并补充零伤害动画` 并 push。

---

### Task 8: 文档与整合回归

**Files:**
- Modify: `core/model.py` 视觉事件类型注释
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `docs/rules.md`（仅视觉事件清单，不改规则）
- Modify: `docs/terminology.md`（仅新增事件术语）

- [ ] **Step 1: 更新事件清单和交互文档**

明确记录 `luck_dice/luck_result/hand/countdown/countdown_proc/revive/turn_start`、快照延迟、升级阶段 busy、热坐两段播放、同效果 stat 合并和 `-0` 边界。删除“热坐交接立即清动画”和“动画不参与任何输入门控”的旧描述。

- [ ] **Step 2: 运行整合回归**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_builder.py tests/test_gui_assets.py tests/test_luck_cards.py tests/test_countdown.py tests/test_damage.py tests/test_combat.py tests/test_mechanics.py tests/test_server.py -n 0`

Expected: 全通过；若仍有共享状态失败，按根因隔离修复，不通过跳过或延长任意 sleep 隐藏。

Run: `git diff --check`

Expected: 无输出。

- [ ] **Step 3: 提交文档与收尾修正**

```bash
git commit -m "docs(对局): 同步视觉事件与动画交互约定"
git push
```
