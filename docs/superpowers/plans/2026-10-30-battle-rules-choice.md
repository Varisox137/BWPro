# 对局规则边界与选择交互修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正瞬发光回合边界、山兔卡牌身份、热坐移交隐私和余辉/残阳无影选择交互。

**Architecture:** 引擎只在统一回合边界和 pending choice 通道做最小扩展；数据按 raw 校正；GUI 复用现有 ChoiceDialog/CardWidget，不新增平行选择协议。

**Tech Stack:** Python 3.14、PySide6、pytest、pytest-xdist。

## Global Constraints

- 设计唯一来源：`docs/superpowers/specs/2026-10-30-battle-rules-choice-design.md`。
- 不修改 `card_data_raw.md`；卡牌 text 与其逐字一致。
- 不为单卡造非原子 op；选择继续统一使用 uid/choice 作答。
- 第三次调度复盘保留手牌，准备移交必须隐藏；不添加未证实首回合特殊分支。
- 所有新行为先写失败测试并实际确认 RED，再最小实现到 GREEN。
- 修改 yaml 后必须跑 `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`；收尾跑默认 `-n 4` 全量测试。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: card_aura 半回合边界

**Files:**
- Modify: `core/engine.py`
- Modify: `core/actions.py`
- Test: `tests/test_enhance.py`
- Test: `tests/test_response.py`

**Interfaces:**
- Consumes: 现有 `card_aura scope="turn"` 与 `_effective_cost`。
- Produces: scope=turn 在所属半回合结束清除；见切响应恢复耗火。

- [ ] **Step 1: 写跨回合响应失败测试**

用真实妖刀姬数据：A 回合命中牌手获得战斗牌瞬发，A 留 1 火并有见切；结束到 B 回合后断言见切费用为 1。B 出击触发见切，断言响应正常结算且 A 从 1 火变 0。觉醒版以 cost_zero 光环覆盖同一边界。保留 A 下一回合清除的既有测试。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_enhance.py tests/test_response.py -k 'aura or response_cost or turn_boundary'`
Expected: B 回合见切仍免费，结算后 A 保留 1 火。

- [ ] **Step 3: 最小实现统一清除点**

将 scope=turn 的 card_aura 清除移到所属玩家的回合结束边界，不再等其下一回合开始；保留 scope=battle 等其他生命周期。检查全部现有 scope=turn 数据，若有个别文本明确要求跨敌方回合则使用独立已有 scope，而不保留隐式残留。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_enhance.py tests/test_response.py tests/test_gui_battle.py -k 'aura or response_cost or turn_boundary'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add core/engine.py core/actions.py tests/test_enhance.py tests/test_response.py tests/test_gui_battle.py
git commit -m "fix(引擎): 修正卡牌光环回合边界"
git push
```

---

### Task 2: 山兔 05–08 身份与卡图修正

**Files:**
- Modify: `db/01_jingdian/17_shantu/10011705.yaml`
- Modify: `db/01_jingdian/17_shantu/10011706.yaml`
- Modify: `db/01_jingdian/17_shantu/10011707.yaml`
- Modify: `db/01_jingdian/17_shantu/10011708.yaml`
- Test: `tests/test_luck_cards.py`
- Test: `tests/test_data.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: raw 一致的 id/name/版本数据；10011708 这把算我赢等级 3 且基础不含 fast。

- [ ] **Step 1: 写身份与费用失败测试**

断言 05=戏谑套索、06=来打我呀、07=萌即正义、08=这把算我赢；10011708 等级 3、基础关键字不含 fast。萌即正义在场且手牌有两张 10011708 时，两张常规费用均为 1，GUI border_color 非 blue。卡图配置查询结果同时匹配 id 与 name，不允许仅 ID 命中异名卡。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_luck_cards.py tests/test_data.py tests/test_gui_builder.py -k 'shantu or luck or identity or card_config'`
Expected: 当前 05–08 名称错位，10011705 这把算我赢等级 2 且带 fast。

- [ ] **Step 3: 按 raw 校正完整版本数据**

逐版本核对 raw 与现有 history，将各卡牌完整的 name/effects/keywords/level 放回正确 id，不只改显示名称；保留各版本日期与平衡性快照。同步测试常量、效果引用和文档状态，不修改 library 用户配置。

- [ ] **Step 4: 数据校验与相关测试**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`
Expected: PASS。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_luck_cards.py tests/test_data.py tests/test_gui_builder.py -k 'shantu or luck or identity or card_config'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add db/01_jingdian/17_shantu tests/test_luck_cards.py tests/test_data.py tests/test_gui_builder.py docs/card-status.md
git commit -m "fix(数据): 校正山兔卡牌身份映射"
git push
```

---

### Task 3: 热坐移交与余辉选择引擎

**Files:**
- Modify: `client/gui/battle.py`
- Modify: `core/actions.py`
- Modify: `core/engine.py`
- Modify: `db/03_yueyehuanxiang/04_huang/10030403.yaml`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_mechanics.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: discard_pick 支持候选过滤；余辉仅幻境牌可选，无候选不挂起；transfer 阶段旧手牌不可见。

- [ ] **Step 1: 写移交隐私与余辉失败测试**

连续调度三次：review 阶段保留中央手牌；第一次确认进入 transfer 后，旧玩家手牌 items 已移除，第二次确认后才显示新玩家手牌。另覆盖双方 ready、首次升级和首回合结束的正常交接。

余辉测试：手牌混合幻境/非幻境时 pending discard_pick 只含幻境 uid；选择后该牌弃置并抽三。无幻境候选时不产生 pending 且仍抽三。联机测试脱敏与超时随机作答仅从合法 uid 选择。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py tests/test_server.py -k 'mulligan_handoff or discard_pick or yuhui'`
Expected: transfer 仍显示旧手牌；余辉随机弃牌且不支持过滤。

- [ ] **Step 3: 最小实现移交清理与候选过滤**

在 confirm_handoff 从 review 切到 transfer 时调用现有清手牌/场景刷新路径，保持 review 不变。`discard_pick` 增加过滤参数并在 `_open_discard_pick` 统一应用；过滤后为空直接续跑。余辉 yaml 用 discard_pick count=1 + card_type=field 替换 discard random_pick，后续抽三步不变。

- [ ] **Step 4: 数据校验与相关测试**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`
Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py tests/test_server.py -k 'mulligan_handoff or discard_pick or yuhui'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle.py core/actions.py core/engine.py db/03_yueyehuanxiang/04_huang/10030403.yaml tests/test_gui_battle.py tests/test_mechanics.py tests/test_server.py docs/card-status.md docs/rules.md docs/terminology.md
git commit -m "feat(对局): 完善热坐移交与余辉弃牌选择"
git push
```

---

### Task 4: 卡图式中央候选与选择关闭

**Files:**
- Modify: `client/gui/battle.py`
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/online.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: Task 3 discard_pick 和现有 field_summon_pick。
- Produces: 共用横向卡图候选视图；实际按钮选择后关闭旧窗、清 `_choice_key`，联机仅发一次 choose。

- [ ] **Step 1: 写真实按钮与滚动失败测试**

余辉与残阳无影 pending 时断言候选项使用 CardWidget/卡图而非纯文字，候选超出可用宽度时外层 QScrollArea 横向滚动可用。点击一个合法候选后，旧 dialog 隐藏并 deleteLater，`_choice_key` 清空；连续 pending 才创建新窗。联机点击后只发送一次 choose，等待 state 时按钮防重复，重连可恢复。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'choice_dialog or discard_pick or field_summon'`
Expected: 当前为文字按钮，无横向滚动，实际按钮关闭状态未覆盖。

- [ ] **Step 3: 实现共用卡图候选视图**

在 ChoiceDialog 内以 QScrollArea + 横向布局显示卡牌型选项，使用 CardWidget 和原始 choice/uid 映射；非卡牌选项保留文字回退。点击后先禁用当前候选防重复，再调用 answer_pending；本地成功后关闭并清理，联机等待 state 但窗口不得旧选项残留。reject 仍禁止取消必答选择，连续 pending 由统一 `_sync_pending_choice` 创建新窗。

- [ ] **Step 4: 相关测试、全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py -k 'choice_dialog or discard_pick or field_summon'`
Expected: 全部 PASS。

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/battle.py client/gui/widgets.py client/gui/online.py tests/test_gui_battle.py tests/test_gui_online.py docs/gui-design.md docs/gui-plan.md
git commit -m "feat(gui): 统一卡图式选择交互"
git push
```
