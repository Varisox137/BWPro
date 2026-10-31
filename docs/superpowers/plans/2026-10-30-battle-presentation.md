# 对局展示与详情交互修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正阶段信息、手牌半高与间距、迅捷操作框、详情尺寸和牌手幻境/能力展示。

**Architecture:** 布局集中在 BattleScene，阶段文本由 HotseatView/OnlineBattleView 共用构造；详情复用 CardWidget/mechanism_panel；牌手 aura 在授予时记录展示元数据，不由 GUI 反推效果原文。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计唯一来源：`docs/superpowers/specs/2026-10-30-battle-presentation-design.md`。
- 不改变游戏操作合法性、引擎结算或联机脱敏。
- 调度中央大卡不变；普通手牌才使用半高锚点。
- 机制框默认每行 12 字、font_scale=1.0；卡图按原生 512 高度渲染。
- 所有新行为先写失败测试并实际确认 RED，再最小实现到 GREEN。
- 测试使用主仓库解释器与正确 DIY 环境；commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 双行阶段、升级次数、迅捷蓝框与主菜单

**Files:**
- Modify: `client/gui/battle.py`
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/online.py`
- Modify: `client/gui/app.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `PlayerState.upgrades`、现有一次性/永久迅捷列表。
- Produces: 双行阶段文本；迅捷可出击 border_color=blue。

- [ ] **Step 1: 写失败测试**

升级阶段断言第一行是当前玩家/回合，第二行较小字号显示“升级阶段·剩余 N 次”，N 与 active.upgrades 一致；升级后 N 减 1。联机倒计时仍追加一次且不破坏双行结构。普通可出击为 yellow，haste 在 keywords/one_shot_keywords/perm_keywords 任一列表时为 blue，消耗后刷新恢复 yellow。主菜单不包含“个人学习项目/与官方无关/素材版权”。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui.py -k 'phase or upgrades or haste or menu_footer'`
Expected: 阶段在右侧/无次数，迅捷黄框，主菜单有说明。

- [ ] **Step 3: 最小实现**

用一个双行 QLabel 或同容器双标签：第一行玩家/回合，第二行阶段与剩余次数。提供统一 `_phase_lines()` 数据结构，联机倒计时在同一第二行构造，不再用字符串替换。移除独立 upgrade_label 与布局项，保留旧属性作为兼容引用（如测试需要）。

BattleScene 设置可出击式神时检查三个关键字列表，haste 存在则 blue，否则 yellow；只改变可出击框。删除 `_make_menu` 的 foot 创建与添加，README 不动。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui.py -k 'phase or upgrades or haste or menu_footer'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle.py client/gui/battle_scene.py client/gui/online.py client/gui/app.py tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui.py
git commit -m "feat(gui): 完善阶段信息与迅捷操作框"
git push
```

---

### Task 2: 手牌半高、压缩间距与式神避让

**Files:**
- Modify: `client/gui/battle_scene.py:62-118,713-752`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Produces: 普通手牌 y=-78（敌方）/822（己方）；8 张总宽 600px；n>8 间距 490/(n-1)；式神准备区与战斗区左移 80px。

- [ ] **Step 1: 写布局失败测试**

分别构造 8/9/12 张手牌：8 张 spacing=70；9/12 张总宽均为 600，spacing=490/(n-1)。普通敌手 y=-78、己手 y=822，调度 y=280 不变。准备区 ready_x=(196,421,871,1096)，战斗区 x=646；12 张手牌图元与敌方式神图元无相交。动画无缓存起点使用同一 y。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'hand_layout or hand_spacing or half_height or avoid_shikigami'`
Expected: 当前固定 70 间距、y=0/744、式神旧坐标。

- [ ] **Step 3: 最小实现统一布局公式**

普通手牌以 110px 卡宽、70px 基础间隔计算：n<=8 保持 70，n>8 使用 490/(n-1)，右侧贴 1599。准备区 x 全部减 80，战斗区 x=646。动画回退 y 复用相同常量，不复制旧值。保持暗手牌、排序和 Z 层级。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py -k 'hand_layout or hand_spacing or half_height or avoid_shikigami or card_use_animation'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/battle_scene.py tests/test_gui_battle.py
git commit -m "feat(gui): 优化手牌半高与密集布局"
git push
```

---

### Task 3: 卡牌详情原生尺寸与机制框宽度

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/mechanisms.py`
- Test: `tests/test_gui_mechanisms.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: CardWidget 可选原生渲染高度；详情卡图 height=512，机制 chars_per_line=12/font_scale=1.0。

- [ ] **Step 1: 写尺寸与参数失败测试**

捕获 CardWidget 的 card_pixmap 调用，详情请求 height=512；机制 fake 断言 `(12, 1.0)` 或等效显式参数，不再是 `(15, 0.85)`。卡图与机制 panel 宽度差不超过 24px，机制区仍可独立纵向滚动，pixmap 不二次各向异性缩放。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_builder.py -k 'detail or mechanism'`
Expected: 详情仍 420px 宽、机制 15 字/0.85。

- [ ] **Step 3: 最小实现**

CardWidget 增加可选 `art_height` 并原样传给 card_pixmap；CardDetailDialog 使用 512，按实际卡图宽度设置机制 panel 的固定/最大宽度，保持 chars_per_line=12、font_scale=1.0。构筑/式神录其他 CardWidget 默认高度不变。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py tests/test_gui_builder.py -k 'detail or mechanism or card_art'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/widgets.py client/gui/mechanisms.py tests/test_gui_mechanisms.py tests/test_gui_builder.py
git commit -m "feat(gui): 统一卡牌详情卡图与机制尺寸"
git push
```

---

### Task 4: 牌手幻境队列与全部牌手能力详情

**Files:**
- Create: `client/gui/player_details.py`
- Modify: `client/gui/details.py`
- Modify: `client/gui/battle.py`
- Modify: `core/actions.py`
- Modify: `core/engine.py`
- Modify: `core/model.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_mechanics.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`

**Interfaces:**
- Consumes: `PlayerState.fields`、auras、delayed；CardWidget/CardDetailDialog/mechanism_panel。
- Produces: aura 展示元数据 `origin/source_name/text`；`PlayerDetailDialog(game, player, viewer)`。

- [ ] **Step 1: 写幻境、能力与滚动失败测试**

构造两个幻境和一个牌手 aura/delayed：详情按队列顺序显示两张卡及当前 intensity，最后显示 aura 来源名称/原文和 delayed 文本；点击幻境打开对应 CardDetailDialog。空队列不保留空列，长队列/能力列表出现整体横向滚动。secret delayed 仍按 viewer 隐藏。 aura 数据缺少旧元数据时显示通用“牌手能力”而不崩溃。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py -k 'player_detail or player_aura'`
Expected: 当前只有文本 QLabel，无幻境卡/能力机制列/滚动。

- [ ] **Step 3: 补牌手能力展示元数据**

在 player_aura/delayed 授予的统一发点写入 `origin`（来源卡牌 id）、`source_name` 和 `text`（来源卡面文本）；已有 delayed 继续沿用现有 origin/secret。序列化仍使用普通 dict，不改变规则或协议字段结构，旧状态按通用名称回退。GUI 不根据 op 反猜原文。

- [ ] **Step 4: 实现牌手详情并验证**

新建 `PlayerDetailDialog`：QScrollArea 横向内容依次为队列幻境 CardWidget（display durability=当前 intensity）与能力 mechanism_panel；幻境点击打开对应 CardDetailDialog。使用 512 高卡图和接近宽度机制列，空队列不加空列。替换 show_player_detail 的旧 QLabel 弹窗，保留头像入口和终局只读可用。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_mechanics.py -k 'player_detail or player_aura'`
Expected: 全部 PASS。

- [ ] **Step 5: 全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/player_details.py client/gui/details.py client/gui/battle.py core/actions.py core/engine.py core/model.py tests/test_gui_battle.py tests/test_mechanics.py docs/gui-design.md docs/gui-plan.md
git commit -m "feat(gui): 展示牌手幻境与牌手能力详情"
git push
```
