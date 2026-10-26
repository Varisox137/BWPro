# 对局场景与实时卡面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `QGraphicsScene` 重建本地热坐对局，按参考图实现覆盖式双方手牌、拖拽出击/用牌、已展示敌方手牌和实时卡面详情。

**Architecture:** `HotseatView` 继续拥有 `Game`、timeline、隐私交接和指令入口；新 `battle_scene.py` 只负责场景图元、布局、拖拽和 signal。`cardart.py` 接受受控的显示数值覆盖，CLI 提供同源结构化数值；详情弹窗复用这些负载，式神卡暂用彩色框。

**Tech Stack:** Python 3.14、PySide6 (`QGraphicsScene/QGraphicsView/QGraphicsObject`)、Pillow、BWPDIY `bwpdiy.render`、pytest。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-26-battle-scene-runtime-cardart-design.md`。
- 不修改 `card_data_raw.md`、卡牌 YAML、`library/`、`D:/Programming/BWPDIY` 或联机协议。
- 不启动 BWPDIY exe，只 import `bwpdiy.render`；缺手牌/形态卡图用透明占位，式神用彩色框。
- 非追猎式神拖出源范围即出击；追猎必须落到合法目标。当前不实现主动第二目标拖拽。
- 双方手牌按 `hand_seq` 排列；敌方仅 `mods["revealed"]` 的实例显示真实卡面。
- 测试使用临时 HOME/配置库，不读写真实 `~/.bwpro/cardart`；不新增第三方依赖。
- 测试命令固定为 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`。
- 保留当前工作区未提交的卡组名修复，不覆盖、不回退；未经用户明确要求不执行 git commit/push。

## File Structure

- Create `client/gui/battle_scene.py`：场景、卡牌/牌手图元、布局、拖拽视觉与 signal。
- Modify `client/gui/battle.py`：以场景替换现有槽位/手牌布局，保留规则交互与隐私控制。
- Modify `client/gui/cardart.py`：为 `card_pixmap` 增加受控 `display` 数值覆盖。
- Modify `client/cli.py`：抽出手牌结构化渲染数值，并保持中文 `_stats_label` 同源。
- Modify `client/gui/widgets.py`：`CardWidget/CardDetailDialog` 接收运行时显示数值。
- Create `client/gui/details.py`：式神基础/觉醒/形态详情和状态文本。
- Modify `tests/test_gui_battle.py`：场景、拖拽、隐私、详情和集成回归。
- Modify `tests/test_gui_builder.py`、`tests/test_client.py`：显示覆盖及结构化数值回归。
- Modify `docs/gui-design.md`、`docs/gui-plan.md`：同步已实现行为。

---

### Task 1: 手牌结构化数值与实时卡面负载

**Files:**
- Modify: `client/cli.py:224-267,545-571`
- Modify: `client/gui/cardart.py:44-94,310-348`
- Modify: `client/gui/widgets.py:57-105,137-183`
- Test: `tests/test_client.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Consumes: 现有 `Game.combat_card_stats`、`_live_enhance`、`card_pixmap(cdef, db, ...)`。
- Produces: `_card_render_stats(game, p, card) -> dict[str, int]`；`hand_cards_info(...)[uid]["render"]`；`card_pixmap(..., display: dict[str, int] | None = None)`；`CardWidget(..., display=None)`。

- [ ] **Step 1: 写结构化数值与显示覆盖的失败测试**

在 `tests/test_client.py` 增加（复用现有 fixture，不新建式神主题文件）：

```python
def test_hand_render_stats_share_runtime_evaluation(db, make_game):
    from client.cli import hand_cards_info

    game = make_game(mulligan=False)
    player = game.state.players[0]
    card = player.hand[0]
    db.cards[card.id] = db.cards[card.id].model_copy(update={"card_type": "combat"})
    info = hand_cards_info(game, 0)[card.uid]
    assert set(info["render"]) == {"power+", "shield+"}
    assert all(type(value) is int for value in info["render"].values())
```

在 `tests/test_gui_builder.py::test_cardart_engine_text_changes_cache_key` 同主题附近增加：

```python
def test_cardart_display_values_change_render_and_cache(qapp, tmp_path):
    from client.gui import cardart

    cdef, database, library_dir, cache_dir = _cardart_cache_case(tmp_path)
    cdef = cdef.model_copy(update={"card_type": "combat"})
    database = factories.db_of([factories.shiki(100101)], [cdef])
    cardart.clear_cardart_caches()
    base = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                               cache_dir=cache_dir, display={"power+": 1})
    boosted = cardart.card_pixmap(cdef, database, library_dir=library_dir,
                                  cache_dir=cache_dir, display={"power+": 7})
    assert base is not None and boosted is not None
    assert base.toImage() != boosted.toImage()
    assert len(list(cache_dir.glob("*.png"))) == 2
    cardart.clear_cardart_caches()
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_client.py::test_hand_render_stats_share_runtime_evaluation \
  tests/test_gui_builder.py::test_cardart_display_values_change_render_and_cache
```

Expected: FAIL，分别缺少 `render` 和 `display` 参数。

- [ ] **Step 3: 实现同源结构化数值和受控覆盖**

在 `client/cli.py` 抽出 `_card_render_stats`，将 `_stats_label` 的战斗/形态分支改为消费该字典；增强法术文本与觉醒中文标签保持原逻辑：

```python
def _card_render_stats(game: Game, p, c) -> dict[str, int]:
    cd = game.db.cards[c.id]
    live = _live_enhance(p, c)
    if live != int(c.mods.get("enhance", 0)):
        c = c.model_copy(update={"mods": {**c.mods, "enhance": live}})
    if cd.card_type == "combat":
        seat = _seat_map(p).get(cd.shikigami) if cd.shikigami is not None else None
        shiki = p.shikigami[seat] if seat is not None else None
        power, shield = game.combat_card_stats(cd.effects, c, shiki, p)
        return {"power+": power, "shield+": shield}
    if cd.card_type == "form" and cd.form_power is not None:
        bonus = 0
        if any(isinstance((stp.model_extra or {}).get("amount"), dict)
               and (stp.model_extra or {})["amount"].get("dice_distinct")
               for stp in cd.effects.steps):
            bonus = len(set(p.ext.get("dice_history", [])))
        return {"power": cd.form_power + bonus,
                "health": cd.form_health + bonus}
    return {}
```

`_stats_label(game, p, c, render=None)` 使用 `render = _card_render_stats(...) if render is None else render`，中文战斗/形态标签直接读取该字典；`hand_cards_info` 每张牌只求值一次：

```python
cd = game.db.cards[c.id]
render = _card_render_stats(game, p, c)
out[c.uid] = {
    "cost": cd.cost + c.mods.get("cost_delta", 0),
    "keywords": _kw_labels(sorted(game._card_keywords(p, cd, c))),
    "stats": _stats_label(game, p, c, render=render),
    "render": render,
    "enhance": _live_enhance(p, c),
    "quest": _quest_progress(game, p, cd),
    "playable": game._play_condition_met(p, cd, c),
    "usage": game.usage_options(pi, c),
}
```

在 `cardart.py` 定义白名单，禁止显示层覆盖类型、文本或卡图：

```python
_DISPLAY_STAT_KEYS = {"power+", "shield+", "power", "health", "durability"}

def _display_stats(display: dict[str, int] | None) -> dict[str, int]:
    if not display:
        return {}
    return {key: value for key, value in display.items()
            if key in _DISPLAY_STAT_KEYS and type(value) is int}
```

把 `card_pixmap` 改为接收 `display=None`，在 `payload = _card_data(...)` 后执行 `payload.update(_display_stats(display))`，其余配置、layout、缓存与错误路径不变。`CardWidget` 同样接收 `display` 并透传；`CardDetailDialog` 调用 `CardWidget(cdef, db=db, display=(runtime or {}).get("render"))`。

- [ ] **Step 4: 跑本任务与相邻回归**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_client.py tests/test_gui_builder.py tests/test_gui_battle.py
```

Expected: PASS；旧静态 `card_pixmap` 与详情调用保持兼容。

- [ ] **Step 5: 可选提交（仅用户明确要求时）**

```bash
git add client/cli.py client/gui/cardart.py client/gui/widgets.py \
  tests/test_client.py tests/test_gui_builder.py tests/test_gui_battle.py
git commit -m "feat(gui): 手牌实时数值接入卡面渲染"
git push
```

---

### Task 2: QGraphicsScene 静态对局与手牌隐私

**Files:**
- Create: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py:122-220,278-534,603-775`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: Task 1 的 `hand_info[uid]["render"]`、`card_pixmap(..., display=...)`。
- Produces: `BattleScene(db)`、`BattleScene.cards`、`BattleScene.sync_state(game, viewer, hand_info, inputs_open)`、`BattleScene.detail_requested = Signal(str, object)`、`BattleScene.action_requested = Signal(dict)`；同步后场景公开 `phase/viewer`，卡牌图元公开 `key/cdef/pixmap/revealed/shiki_text/player/index/uid/payload/keywords/legal_targets/target_required`。

- [ ] **Step 1: 写布局、透明占位与已展示手牌失败测试**

在 `tests/test_gui_battle.py` 用场景断言替换准备区固定 QWidget 槽位测试：

```python
def test_scene_hand_order_reveal_and_overlay(qapp, view):
    start(view, mulligan=False)
    scene = view.battle_scene
    own = view.game.state.players[0]
    enemy = view.game.state.players[1]
    revealed = enemy.hand[1]
    revealed.mods["revealed"] = True
    view.refresh()
    settle(view)

    enemy_items = [scene.cards[("hand", c.uid)] for c in
                   sorted(enemy.hand, key=lambda c: c.hand_seq)]
    assert [item.revealed for item in enemy_items] == [False, True, False, False, False]
    assert enemy_items[1].cdef.id == revealed.id
    assert all(item.cdef is None for item in
               (enemy_items[0], *enemy_items[2:]))
    assert enemy_items[0].zValue() > scene.cards[("shiki", 1, 0)].zValue()
    assert scene.cards[("hand", own.hand[0].uid)].boundingRect().height() <= 170
```

```python
def test_scene_twelve_hand_cards_overlap_and_shiki_placeholder(qapp, view):
    start(view, mulligan=False)
    player = view.game.state.players[0]
    player.hand = [card.model_copy(update={"uid": 1000 + i, "hand_seq": i + 1})
                   for i, card in enumerate((player.hand * 3)[:12])]
    view.refresh()
    settle(view)
    items = [view.battle_scene.cards[("hand", card.uid)]
             for card in sorted(player.hand, key=lambda c: c.hand_seq)]
    assert len(items) == 12
    assert items[1].x() < items[0].x() + items[0].boundingRect().width()
    assert items[-1].x() + items[-1].boundingRect().width() <= 1600
    shiki = view.battle_scene.cards[("shiki", 0, 0)]
    assert "力量" in shiki.shiki_text and "生命" in shiki.shiki_text
    assert "等级" in shiki.shiki_text
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py::test_scene_hand_order_reveal_and_overlay
```

Expected: FAIL，`HotseatView` 尚无 `battle_scene`。

- [ ] **Step 3: 实现场景、图元和同步**

`battle_scene.py` 使用 1600×900 逻辑场景和 `KeepAspectRatio` 视图。核心类型：

```python
class BattleCardItem(QGraphicsObject):
    def __init__(self, key, cdef=None, pixmap=None, revealed=True,
                 size=QSizeF(110, 156), shiki_text=""):
        super().__init__()
        self.key = key
        self.cdef = cdef
        self.pixmap = pixmap
        self.revealed = revealed
        self.size = size
        self.shiki_text = shiki_text
        self.player = self.index = self.uid = None
        self.payload = cdef if cdef is not None else key
        self.keywords: list[str] = []
        self.legal_targets: list[Ref] = []
        self.target_required = False
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def boundingRect(self):
        return QRectF(QPointF(0, 0), self.size)

    def paint(self, painter, option, widget=None):
        if self.pixmap is not None and not self.pixmap.isNull():
            painter.drawPixmap(self.boundingRect(), self.pixmap,
                               QRectF(self.pixmap.rect()))
        elif self.key[0] == "shiki":
            painter.setPen(QPen(QColor("#d9b96a"), 3))
            painter.setBrush(QColor(45, 55, 65, 220))
            painter.drawRect(self.boundingRect())
            painter.drawText(self.boundingRect(), Qt.TextWordWrap | Qt.AlignCenter,
                             self.shiki_text)
        elif self.key[0] == "hand" and not self.revealed:
            painter.setPen(QPen(QColor("#d9b96a"), 2))
            painter.setBrush(QColor(45, 55, 65, 240))
            painter.drawRect(self.boundingRect())
        # 有卡面身份但无卡图的手牌：完全透明，boundingRect 仍负责命中。
```

`BattleScene.cards` 以 `("hand", uid)` 和 `("shiki", pi, index)` 为键。`sync_state` 全量同步少量图元，先移除失效项，再按 `hand_seq` 设置双方手牌位置；手牌 z=40、式神 z=10、拖拽层 z=100。卡背只需程序化占位，不新增图片资产。基础/觉醒式神传 `pixmap=None` 使用彩色框；结附形态时用形态定义和实时 `display` 调 `card_pixmap`，有图则绘制形态卡面，并以角标显示场上实时力量/生命。

固定布局常量：场景 `1600×900`；手牌 `110×156`；12 张时间距用 `min(70, 460 / max(count - 1, 1))` 计算重叠，右侧对齐；敌手牌 y=16、己手牌 y=728；式神使用约 `148×210` 彩色框，上下准备区弧线与中央战斗区分离。所有坐标集中在 `layout_positions(...)`，供测试和后续动画共用。

`HotseatView._build_battle_page` 改为一个 `QGraphicsView`，保留 `log_dialog`；菜单、记录、结束回合和结果按钮使用 `QGraphicsProxyWidget` 或场景按钮。`_render_state` 只组装 `hand_info` 并调用 `sync_state`，不再创建 `ShikiFrame/HandCardFrame`。`_clear_hand` 改为移除 `("hand", uid)` 图元，交接仍清空非公开内容。

- [ ] **Step 4: 跑静态场景与现有隐私回归**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py
```

Expected: PASS；己下敌上、交接清手牌、调度隐私和日志过滤不退化。

- [ ] **Step 5: 可选提交（仅用户明确要求时）**

```bash
git add client/gui/battle_scene.py client/gui/battle.py tests/test_gui_battle.py
git commit -m "feat(gui): 使用场景视图重建对局布局"
git push
```

---

### Task 3: 拖拽出击、用牌与点击详情

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py:782-918,1067-1070`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: Task 2 的 `BattleScene.cards` 和 `action_requested`。
- Produces: `BattleDragController.press(item, scene_pos)`、`move(scene_pos)`、`release(scene_pos)`；`HotseatView.assault(index, target=None)`；`HotseatView.play_card(uid, usage_id=..., target=None)`。

- [ ] **Step 1: 写点击、取消和有效拖拽失败测试**

用 `QTest.mousePress/MouseMove/MouseRelease` 或直接向控制器传 `QPointF` 测状态机，优先后者以避免窗口坐标脆弱性：

```python
def test_non_hunt_drag_outside_source_assaults(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    calls = []
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        calls.append((index, target)) or True)
    drag = scene.drag_controller
    drag.press(item, item.scenePos())
    drag.move(item.scenePos() + QPointF(180, -90))
    drag.release(item.scenePos() + QPointF(180, -90))
    assert calls == [(0, None)]
```

在测试文件顶部把 `QPointF` 加入 `PySide6.QtCore` import，并增加：

```python
def test_drag_click_and_return_to_source_cancel(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    details, calls = [], []
    monkeypatch.setattr(view, "show_shiki_detail", details.append)
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        calls.append((index, target)) or True)
    origin = item.scenePos()
    scene.drag_controller.press(item, origin)
    scene.drag_controller.release(origin)
    assert details == [Ref(player=0, shikigami=0)] and calls == []
    scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(180, 0))
    scene.drag_controller.release(origin)
    assert calls == []
    scene.inputs_open = False
    assert scene.drag_controller.press(item, origin) is False


def test_hunt_and_targeted_card_require_legal_drop(qapp, view, monkeypatch):
    start(view, mulligan=False)
    scene = view.battle_scene
    view.game.current.shikigami[0].keywords.append("hunt")
    card = view.game.current.hand[0]
    cdef = view.db.cards[card.id]
    view.db.cards[card.id] = cdef.model_copy(update={
        "target": F.T(kind="choose", pool="enemy_shikigami")})
    view.refresh()
    settle(view)
    assaults, plays = [], []
    monkeypatch.setattr(view, "assault", lambda index, target=None:
                        assaults.append((index, target)) or True)
    monkeypatch.setattr(view, "play_card", lambda uid, usage_id=..., target=None:
                        plays.append((uid, target)) or True)
    enemy = scene.cards[("shiki", 1, 1)]
    drop = enemy.scenePos() + QPointF(20, 20)
    shiki_item = scene.cards[("shiki", 0, 0)]
    scene.drag_controller.press(shiki_item, shiki_item.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    assert assaults == [(0, Ref(player=1, shikigami=1))]
    hand_item = scene.cards[("hand", card.uid)]
    scene.drag_controller.press(hand_item, hand_item.scenePos())
    scene.drag_controller.move(drop)
    scene.drag_controller.release(drop)
    assert plays == [(card.uid, Ref(player=1, shikigami=1))]
```

无目标手牌在同一测试模块用未改 `target` 的手牌重复最后三行，断言 `plays == [(card.uid, None)]`；追猎/目标牌改在空白坐标 `QPointF(20, 450)` 松开，断言对应调用列表保持为空。

- [ ] **Step 2: 运行拖拽测试并确认失败**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py::test_non_hunt_drag_outside_source_assaults
```

Expected: FAIL，缺少 `drag_controller` 或对应参数。

- [ ] **Step 3: 实现拖拽控制器与指令落点**

`BattleDragController` 持有 scene，不持有 Game；scene 在 `sync_state` 时同步 `inputs_open` 和当前阶段。`BattleCardItem.mousePressEvent/mouseMoveEvent/mouseReleaseEvent` 分别把 `event.scenePos()` 转交 `press/move/release`，视图禁用自身拖拽滚动。鼠标移动超过 `QApplication.startDragDistance()` 后创建拖拽副本与 `QGraphicsPathItem` 箭头，统一放入 `BattleAnimationLayer`（本轮实际用于拖拽视觉，z=100；公开 `drag_ghost/drag_arrow`，`cancel()` 后均为 `None`）。

控制器逻辑按源类型分流：

```python
def release(self, scene_pos: QPointF) -> None:
    item = self.item
    if item is None:
        return
    scene = self.scene
    kind = item.key[0]
    dragged = self.dragged
    source_rect = QRectF(item.scenePos(), item.size)
    target_ref = next((candidate.payload for candidate in scene.items(scene_pos)
                       if isinstance(candidate, BattleCardItem)
                       and isinstance(candidate.payload, Ref)), None)
    self.cancel()  # 先清除副本/箭头和 press 状态，再发操作请求
    if not dragged:
        if kind == "shiki" and scene.phase == "upgrade" and item.player == scene.viewer:
            scene.action_requested.emit({"op": "upgrade", "index": item.index})
        else:
            scene.detail_requested.emit(kind, item.payload)
        return
    if source_rect.contains(scene_pos):
        return
    if kind == "shiki":
        if "hunt" not in item.keywords:
            scene.action_requested.emit({"op": "assault", "index": item.index})
        elif target_ref in item.legal_targets:
            scene.action_requested.emit({"op": "assault", "index": item.index,
                                         "target": target_ref})
    elif kind == "hand":
        if scene.phase == "mulligan":
            scene.action_requested.emit({"op": "mulligan", "uid": item.uid})
        elif item.target_required and target_ref in item.legal_targets:
            scene.action_requested.emit({"op": "play_card", "uid": item.uid,
                                         "target": target_ref})
        elif not item.target_required:
            scene.action_requested.emit({"op": "play_card", "uid": item.uid})
```

`HotseatView` 连接 `action_requested` 到统一分发；`assault(index, target=None)` 在传入目标时直接加入 command，否则保持非追猎默认流程。`play_card(..., target=None)` 在方式选择后将目标加入 command，并用 `targets.spec_pool_refs` 验证该方式的目标合法性；不匹配则不调用 `apply_command`。现有点击目标路径可保留给 target2/旧测试，但场景不新增第二目标状态机。

- [ ] **Step 4: 跑拖拽与操作回归**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py tests/test_combat.py tests/test_engine.py
```

Expected: PASS；UI 生成指令与现有引擎行为一致，无重复扣费或双击出牌。

- [ ] **Step 5: 可选提交（仅用户明确要求时）**

```bash
git add client/gui/battle_scene.py client/gui/battle.py tests/test_gui_battle.py
git commit -m "feat(gui): 实现拖拽出击与用牌"
git push
```

---

### Task 4: 基础/觉醒/形态与手牌详情弹窗

**Files:**
- Create: `client/gui/details.py`
- Modify: `client/gui/battle.py:916-1070`
- Modify: `client/gui/widgets.py:137-188`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: Task 1 `runtime["render"]`，Task 2 `detail_requested(kind, payload)`。
- Produces: `ShikigamiDetailDialog(game, ref, viewer, parent=None)`；`shiki_status_lines(game, ref, viewer) -> list[str]`；敌方已展示手牌静态详情。

- [ ] **Step 1: 写觉醒永久数值、形态基础值和公开详情失败测试**

扩展现有式神详情测试，不只看文本，还检查主卡/形态占位内容：

```python
def test_awaken_detail_separates_permanent_and_form_base(qapp, view, monkeypatch):
    start(view, mulligan=False)
    shiki = view.game.state.players[0].shikigami[0]
    definition = view.db.shikigami[shiki.id]
    awaken = F.card(10010909, shikigami=shiki.id, subtype="awaken",
                    awaken_power=2, awaken_health=2)
    form = F.card(10010910, shikigami=shiki.id, card_type="form",
                  form_power=2, form_health=6)
    view.db.cards[awaken.id] = awaken
    view.db.cards[form.id] = form
    shiki.awakened = awaken.id
    shiki.form = CardInstance(uid=9999, id=form.id)
    shiki.perm_power = 3
    shiki.perm_health = 4
    shiki.temp_power = 9
    seen = {}

    def capture(dialog):
        seen["dialog"] = dialog
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    dialog = seen["dialog"]
    assert f"力量 {definition.power + 3}" in dialog.main_card_text
    assert f"生命 {definition.health + 4}" in dialog.main_card_text
    assert "力量 12" not in dialog.main_card_text
    assert "觉醒" in dialog.main_card_text
    assert dialog.form_card.cdef.form_power == 2
    assert dialog.form_card.cdef.form_health == 6

    shiki.awakened = None
    view.show_shiki_detail(Ref(player=0, shikigami=0))
    assert f"力量 {definition.power}" in seen["dialog"].main_card_text
    assert f"生命 {definition.health}" in seen["dialog"].main_card_text
```

在同一测试模块为敌方已展示手牌捕获 `CardDetailDialog`，断言其 `runtime_label` 不存在；对未展示敌方手牌断言场景项 `cdef is None` 且拖拽控制器不产生详情 signal。

- [ ] **Step 2: 运行详情测试并确认失败**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py::test_awaken_detail_separates_permanent_and_form_base
```

Expected: FAIL，旧对话框没有 `main_card_text`。

- [ ] **Step 3: 实现详情组件并接管线**

`details.py` 提供 `shiki_status_lines`，从 `HotseatView.show_shiki_detail` 提取现有状态文本逻辑，保留 `ref_label` 的秘密目标视角判断。`ShikigamiDetailDialog` 暴露：

```python
self.main_card_text = (
    f"{name}\n等级 {shiki.level}\n"
    f"力量 {power}　生命 {health}\n{ability_text}"
)
self.form_card = CardWidget(form_def, db=game.db) if shiki.form else None
```

未觉醒 `power/health = definition.power/definition.health`；觉醒 `power = definition.power + shiki.perm_power`、`health = definition.health + shiki.perm_health`，名称与能力文本取 `game.db.cards[shiki.awakened]`，并加“觉醒”标识。形态卡使用其自身定义，不传运行时合计。

主卡使用固定比例彩色 `QFrame/QLabel`，不调用 BWPDIY 式神渲染；形态 `CardWidget` 缺图时保留文本详情，场上透明占位不影响查看。手牌 `CardDetailDialog` 已由 Task 1 接收 `runtime["render"]`；`HotseatView.show_card_detail` 仅当 uid 属于当前 viewer 手牌时传 `hand_info`，敌方已展示牌传 `runtime=None`。

- [ ] **Step 4: 跑详情、卡图和隐私回归**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py tests/test_gui_builder.py
```

Expected: PASS；觉醒永久值、形态基础值、当前状态区和秘密目标口径均正确。

- [ ] **Step 5: 可选提交（仅用户明确要求时）**

```bash
git add client/gui/details.py client/gui/battle.py client/gui/widgets.py \
  tests/test_gui_battle.py tests/test_gui_builder.py
git commit -m "feat(gui): 增加觉醒形态与实时手牌详情"
git push
```

---

### Task 5: 实图复核、文档与全量验证

**Files:**
- Modify: `client/gui/battle_scene.py`
- Modify: `client/gui/battle.py`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Test: `tests/test_gui_battle.py`

**Interfaces:**
- Consumes: Tasks 1-4 的全部公开接口。
- Produces: 可运行、可截图复核的最终本地热坐 GUI；不新增规则接口。

- [ ] **Step 1: 写最终窗口与交接取消拖拽回归**

在 `tests/test_gui_battle.py` 增加：

```python
def test_handoff_clears_drag_and_reveals_only_new_viewer_hand(qapp, view):
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    origin = item.scenePos()
    scene.drag_controller.press(item, origin)
    scene.drag_controller.move(origin + QPointF(160, -80))
    assert scene.animation_layer.drag_ghost is not None
    view.game.state.active = 1
    view.refresh()
    assert view._handoff_pending
    assert scene.animation_layer.drag_ghost is None
    assert scene.animation_layer.drag_arrow is None
    assert not any(key[0] == "hand" for key in scene.cards)
    view.confirm_handoff()
    expected = {card.uid for card in view.game.state.players[1].hand}
    assert {key[1] for key in scene.cards if key[0] == "hand"} == expected
    assert scene.sceneRect().contains(scene.end_turn_item.sceneBoundingRect())
    assert scene.sceneRect().contains(scene.menu_item.sceneBoundingRect())
```

Task 2 的场景按钮代理相应公开为 `scene.end_turn_item` 和 `scene.menu_item`；12 手牌覆盖由 Task 2 的布局测试验证，不重复构造。

- [ ] **Step 2: 运行最终 GUI 回归**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py
```

Expected: PASS。

- [ ] **Step 3: 生成并读取实际场景截图**

在 `tests/test_gui_battle.py` 增加默认跳过、仅实图复核时启用的测试：

```python
def test_scene_visual_review(qapp, view):
    if os.environ.get("BWP_VISUAL_REVIEW") != "1":
        pytest.skip("仅在人工实图复核时运行")
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    from client.gui.details import ShikigamiDetailDialog

    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    output = Path(".pytest_cache/gui-review")
    output.mkdir(parents=True, exist_ok=True)
    start(view, mulligan=False)
    view.resize(1600, 900)
    view.show()
    qapp.processEvents()
    assert view.grab().save(str(output / "battle.png"))

    player = view.game.state.players[0]
    player.hand = [card.model_copy(update={"uid": 2000 + i, "hand_seq": i + 1})
                   for i, card in enumerate((player.hand * 3)[:12])]
    view.refresh()
    settle(view)
    qapp.processEvents()
    assert view.grab().save(str(output / "hand-12.png"))

    scene = view.battle_scene
    item = scene.cards[("shiki", 0, 0)]
    scene.drag_controller.press(item, item.scenePos())
    scene.drag_controller.move(item.scenePos() + QPointF(180, -90))
    qapp.processEvents()
    assert view.grab().save(str(output / "drag.png"))
    scene.drag_controller.cancel()

    shiki = view.game.state.players[0].shikigami[0]
    awaken = F.card(10010909, shikigami=shiki.id, subtype="awaken",
                    awaken_power=2, awaken_health=2)
    form = F.card(10010910, shikigami=shiki.id, card_type="form",
                  form_power=2, form_health=6)
    view.db.cards[awaken.id] = awaken
    view.db.cards[form.id] = form
    shiki.awakened = awaken.id
    shiki.form = CardInstance(uid=9999, id=form.id)
    shiki.perm_power = 2
    shiki.perm_health = 2
    dialog = ShikigamiDetailDialog(view.game, Ref(player=0, shikigami=0), 0, view)
    dialog.resize(1000, 700)
    dialog.show()
    qapp.processEvents()
    assert dialog.grab().save(str(output / "detail.png"))
    dialog.close()
```

Run:

```bash
BWP_VISUAL_REVIEW=1 USERPROFILE='D:/Programming/BWPro/.pytest_cache/gui-review/home' \
  PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_gui_battle.py::test_scene_visual_review
```

用 `ReadMediaFile` 读取 `.pytest_cache/gui-review/{battle,hand-12,drag,detail}.png`，检查卡面比例、遮挡层级、透明占位、牌手位置、右侧按钮、觉醒永久值和形态基础值。视觉偏差只调整 `layout_positions`/绘制参数，并回到 Step 2。

- [ ] **Step 4: 同步文档并检查无旧描述**

更新 `docs/gui-design.md` 的“对局界面当前实现”：QGraphicsScene、非追猎拖出即出击、手牌 `hand_seq`、已展示正反面、透明回退、式神彩色框和详情口径。`docs/gui-plan.md` 只更新当前 GUI 能力，不写更新日志。搜索旧描述：

```bash
# 用 Grep 工具检查这些关键词，不直接调用 shell grep
# "148×108"、"底部横排滚动区"、"拖出源式神范围"、"QGraphicsScene"
```

Expected: 当前实现不再声称旧槽位/底部滚动手牌；历史初稿若保留须明确标为未实现设想。

- [ ] **Step 5: 主上下文全量验证**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q
```

Expected: 全部 PASS。再运行：

```bash
git diff --check
git status --short
```

Expected: 无空白错误；只包含本计划涉及文件、设计/计划文档与此前用户已有的卡组名修复，不包含 `library/`、logs、缓存或 `card_data_raw.md`。UI 未改数据，本任务无需 `db.validate`。

- [ ] **Step 6: 可选提交（仅用户明确要求且全绿时）**

```bash
git add client/gui docs/gui-design.md docs/gui-plan.md tests/test_gui_battle.py
git commit -m "feat(gui): 完成原版布局与拖拽对局交互"
git push
```
