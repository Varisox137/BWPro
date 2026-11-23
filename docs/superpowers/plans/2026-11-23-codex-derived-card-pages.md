# 式神录衍生内容分页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 常规卡牌与衍生内容分别按五项一页排列，并提供两个区域跳转按钮。

**Architecture:** `ShikigamiCodexView` 从当前环境构造常规、衍生两个定义组，分别切块成真实控件页表。`_all_card_widgets` 继续保存全部预载控件，`_card_pages` 保存每页控件引用；翻页只替换布局，不重建卡图。

**Tech Stack:** Python、PySide6、现有 `CardDatabase`、`buildable_cards`、pytest offscreen GUI。

## Global Constraints

- 常规组为式神本体 + 可构筑卡牌；衍生组为当前 `edb` 中本家 token 卡与非普通式神实体，按 id 升序。
- 衍生组从新页开始；无衍生内容时不增加页面或区域按钮。
- 所有内容一次预载，衍生项支持现有详情与外观切换。
- 保留占位控件立即隐藏并销毁的修复，避免翻页遮挡。
- 不修改构筑池、数据库 schema 或卡牌数据。

## 文件结构

- `client/gui/codex.py`：构造分组页表、渲染衍生内容并管理区域导航按钮。
- `tests/test_gui_codex.py`：覆盖分组边界、id 排序、按钮状态、预载与占位生命周期。
- `docs/gui-design.md`：同步式神录分页交互说明。

---

### Task 1: 分组分页与区域跳转

**Files:**
- Modify: `client/gui/codex.py`
- Test: `tests/test_gui_codex.py`
- Modify: `docs/gui-design.md`

**Interfaces:**
- Consumes: `buildable_cards(edb, sid)`、`edb.cards`、`edb.shikigami`。
- Produces: `_current_card_groups() -> tuple[list, list]`、`_card_pages: list[list[CardWidget]]`、`jump_to_card_group(group: str)`。

- [ ] **Step 1: 写失败的分组与导航测试**

新增测试，使用真实数据库验证雪女衍生组包含 `10012151` 与 `10012199`，三目衍生组有 16 项且页表为 6 页；验证首个衍生页之前不混入衍生项。另验证区域按钮可见性、可用性与跳转：

```python
view.select_shikigami(100121)
view.show_shikigami_cards()
assert [card.id for card in view._current_card_groups()[1]] == [10012151, 10012199]
assert view.page_count == 3
assert view.card_primary.isVisible()
assert not view.card_primary.isEnabled()
assert view.card_derived.isEnabled()
view.jump_to_card_group("derived")
assert view.page_index == 2
assert [card.cdef.id for card in view.card_widgets] == [10012151, 10012199]
assert view.card_primary.isEnabled()
assert not view.card_derived.isEnabled()
view.jump_to_card_group("primary")
assert view.page_index == 0
```

无衍生内容时两个按钮均应隐藏；翻页不得增加加载事件或替换 `_all_card_widgets` 中的对象。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_gui_codex.py
```

Expected: 因缺少 `_current_card_groups`、区域按钮或衍生页而 FAIL。

- [ ] **Step 3: 实现分组和页表**

在 `codex.py` 增加：

```python
def _current_card_groups(self) -> tuple[list, list]:
    if self.selected_sid not in self.edb.shikigami:
        return [], []
    sid = self.selected_sid
    primary = [self.edb.shikigami[sid]] + buildable_cards(self.edb, sid)
    derived = sorted([
        *[card for card in self.edb.cards.values()
          if card.token and card.shikigami == sid],
        *[entity for entity in self.edb.shikigami.values()
          if entity.kind != "shikigami" and entity.id // 100 == sid],
    ], key=lambda definition: definition.id)
    return primary, derived
```

`_render_cards` 对两组分别创建控件并按 `CARD_PAGE_SIZE` 切块到 `_card_pages`；`_show_card_page` 直接取 `_card_pages[self.page_index]`，不再用全列表 `page_index * 5` 切片。

- [ ] **Step 4: 实现区域按钮**

页码栏依次放置 `card_primary`、左翻页、页码、右翻页、`card_derived`。两个按钮使用 `objectName="small"`，分别连接：

```python
def jump_to_card_group(self, group: str) -> None:
    target = 0 if group == "primary" else self._derived_start
    if 0 <= target < self.page_count:
        self.page_index = target
        self._show_card_page()
```

`_show_card_page` 根据 `_derived_start` 与当前页更新两个按钮的可见性和可用性；无衍生组时两者隐藏。

- [ ] **Step 5: 更新设计说明并运行相关回归**

在 `docs/gui-design.md` 的式神录段落补充两组独立分页与区域按钮。运行：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_gui_codex.py tests/test_gui_appearance.py
```

Expected: 全部 PASS；既有翻页往返占位遮挡测试继续通过。

- [ ] **Step 6: 提交并推送**

```bash
git add client/gui/codex.py tests/test_gui_codex.py docs/gui-design.md docs/superpowers/plans/2026-11-23-codex-derived-card-pages.md
git commit -m "feat(式神录): 增加衍生内容分页与区域跳转"
git push
```
