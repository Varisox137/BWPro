# 战斗牌交互、抽牌参数与对局边距修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复余辉/蓬莱玉枝抽牌参数、战斗牌含选择效果的发起战斗时点，以及顶部 chrome 和手牌数量布局。

**Architecture:** 数据参数仅校正到已注册 op；引擎复用统一 pending choice 续跑，不新增选择协议；GUI 布局继续由 MainWindow 与 BattleScene 共用。

**Tech Stack:** Python 3.14、PySide6、pytest、pytest-xdist。

## Global Constraints

- 设计来源：`docs/superpowers/specs/2026-10-31-combat-choice-layout-design.md`。
- 不修改 `card_data_raw.md`，不新增非原子 op，不允许取消必答选择。
- 卡面效果及交互全部完成后才入墓并发起一次战斗。
- 所有新行为先写失败测试并确认 RED，再最小实现到 GREEN；修改 YAML 后跑 `db.validate`。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 余辉与蓬莱玉枝真实抽牌参数

**Files:**
- Modify: `db/03_yueyehuanxiang/04_huang/10030403.yaml`
- Modify: `db/03_yueyehuanxiang/03_huiyeji/10030307.yaml`
- Test: `tests/test_mechanics.py`
- Test: `tests/test_gui_battle.py`

- [ ] **Step 1: 写真实数据失败测试**

余辉使用真实 `10030403`，选择一张幻境牌后断言该牌弃置、随后抽满三张、pending_choice 为空且 GUI 旧选择窗关闭。蓬莱玉枝两处抽牌步骤均覆盖 count 参数，不抛 TypeError。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_mechanics.py tests/test_gui_battle.py -k 'yuhui or discard_pick or huiyeji'`
Expected: `draw() got an unexpected keyword argument 'amount'`。

- [ ] **Step 3: 最小修复并验证**

将两处 `draw amount` 改为 `draw count`，不改卡面文本或其他效果。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`
Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_mechanics.py tests/test_gui_battle.py -k 'yuhui or discard_pick or huiyeji'`
Expected: 校验与测试均 PASS。

- [ ] **Step 4: Commit**

```bash
git add db/03_yueyehuanxiang/04_huang/10030403.yaml db/03_yueyehuanxiang/03_huiyeji/10030307.yaml tests/test_mechanics.py tests/test_gui_battle.py
git commit -m "fix(卡牌): 修正余辉与蓬莱玉枝抽牌参数"
git push
```

---

### Task 2: 战斗牌交互完成后发起战斗

**Files:**
- Modify: `core/engine.py`
- Modify: `docs/rules.md`
- Test: `tests/test_combat.py`
- Test: `tests/test_mechanics.py`
- Test: `tests/test_gui_battle.py`

- [ ] **Step 1: 写真实残阳无影时点失败测试**

觉醒泷夜叉姬、当前无幻境，使用残阳无影后立即断言 pending field_summon_pick 存在且尚未 on_before_assault/交战；选择非战斗伤害幻境后，on_summon_field 早于 on_before_assault，获得先攻、攻击方存活，on_card_played 与战斗均仅一次。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_combat.py tests/test_mechanics.py tests/test_gui_battle.py -k 'field_summon or initiative or combat_card'`
Expected: 当前先发起战斗，作答后才召唤幻境。

- [ ] **Step 3: 最小实现整体挂起与续跑**

`_resolve_combat_card` 在效果产生 pending choice 时同时挂起入墓、替换和 `_resolve_combat`；作答续完剩余效果后统一执行一次后续。保持外层 on_card_played 恰好一次，不改先攻快照，并在 `docs/rules.md` 同步该时点。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_combat.py tests/test_mechanics.py tests/test_response.py tests/test_gui_battle.py -k 'field_summon or initiative or combat_card'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add core/engine.py docs/rules.md tests/test_combat.py tests/test_mechanics.py tests/test_response.py tests/test_gui_battle.py
git commit -m "fix(引擎): 战斗牌交互完成后发起战斗"
git push
```

---

### Task 3: 顶部 chrome 与手牌数量布局

**Files:**
- Modify: `client/gui/app.py`
- Modify: `client/gui/battle.py`
- Modify: `client/gui/battle_scene.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

- [ ] **Step 1: 写精确布局失败测试**

对局内 outer=(0,0,0,0)、chrome=(12,12,12,0)，主菜单/构筑/联机页恢复 outer=12、chrome=0。断言敌方手牌 `(1530,156)`、己方 `(1530,680)`，尺寸 68×64，与对应牌库垂直间距 8 且不相交。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'outer_margins or hand_caption or deck_label'`
Expected: chrome 全 0，手牌标签仍在旧位置。

- [ ] **Step 3: 最小实现并验证**

MainWindow 保存 chrome 并在 `_sync_game_menu_button` 同步补偿边距；BattleScene 更新手牌标签坐标，BattleView 构建时统一 68×64。联机继承共用布局。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'outer_margins or hand_caption or deck_label'`
Expected: 全部 PASS。

- [ ] **Step 4: 全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/app.py client/gui/battle.py client/gui/battle_scene.py tests/test_gui_battle.py tests/test_gui_online.py
git commit -m "fix(gui): 修正对局顶部边距与手牌计数位置"
git push
```
