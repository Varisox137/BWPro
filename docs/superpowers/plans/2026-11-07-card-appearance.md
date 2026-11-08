# 卡牌牌框切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在式神录中按卡牌切换四种牌框，稀疏保存本机偏好并全局应用于大卡图，同时统一放大选择界面的紧凑布局。

**Architecture:** 独立外观存储模块负责校验与原子读写；卡图适配层在实际负载生成前覆盖牌框，预热只处理当前外观。外观对话框复用 `CardWidget`，式神录只负责左右键分派与确认后的当前页刷新。

**Tech Stack:** Python 3.14、PySide6、Pillow、pytest、现有 BWPDIY `render_card` 管线。

## Global Constraints

- 牌框仅为 `norm`/`blue`/`black`/`red`，中文依次为常规/琉璃/墨染/百炼。
- 仅保存非常规牌框；异画只预留默认原画字段，不实现异画发现或选择。
- 不修改引擎规则、卡牌数据库、`card_data_raw.md` 或 `library/` 配置。
- 大卡图应用偏好，对局式神小卡保持原行为。
- 启动预热只处理当前外观，不枚举四框。
- 未经用户明确要求不执行 git commit。

---

### Task 1: 本机外观存储与卡图/预热接入

**Files:**
- Create: `client/gui/card_appearance.py`
- Modify: `client/gui/cardart.py`
- Modify: `client/gui/prewarm.py`
- Test: `tests/test_gui_appearance.py`

**Interfaces:**
- Produces: `FRAME_VARIANTS: dict[str, str]`、`appearance_path() -> Path`、`load_card_appearances(path=None) -> dict[str, dict]`、`card_appearance(card_id, path=None) -> dict`、`save_card_appearance(card_id, frame_variant="norm", art_index=0, path=None) -> None`。
- Consumes: 现有 `_card_pixmap_impl(...)` 与 `prewarm_iter(...)`；公共 `card_pixmap` 既有调用保持兼容，Task 2 再增加可选牌框覆盖参数。

- [ ] **Step 1: 写稀疏存储失败测试**

```python
def test_appearance_store_is_sparse_and_validated(tmp_path):
    path = tmp_path / "appearance.json"
    save_card_appearance(10010101, "blue", path=path)
    assert card_appearance(10010101, path) == {"frame_variant": "blue", "art_index": 0}
    save_card_appearance(10010101, "norm", path=path)
    assert load_card_appearances(path) == {}
    with pytest.raises(ValueError):
        save_card_appearance(10010101, "gold", path=path)
```

另写损坏 JSON、非法字段和未知牌框回退测试，断言不抛异常且返回默认 `{"frame_variant": "norm", "art_index": 0}`。

- [ ] **Step 2: 运行测试确认模块尚不存在**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_appearance.py -k store`
Expected: FAIL，无法导入 `client.gui.card_appearance`。

- [ ] **Step 3: 实现最小存储模块**

使用 `Path.home() / ".bwpro" / "card_appearance.json"`；顶层结构为 `{"version": 1, "cards": {str(card_id): {"frame_variant": variant, "art_index": 0}}}`。读取只接受合法 id 键、合法牌框与非负整数 `art_index`，本轮保存只允许 `art_index=0`。常规且原画时删除条目，空 `cards` 仍保留合法顶层结构。写入沿用 `gui.json` 的同目录 `.tmp` 替换方式。

- [ ] **Step 4: 写卡图覆盖与预热指纹失败测试**

复用 `tests/test_gui_builder.py` 的临时卡图配置模式，捕获 `_cached_card_pixmap` 的 payload/layout。monkeypatch `cardart.card_appearance` 返回 `{"frame_variant": "black", "art_index": 0}`，断言实际 payload 与 `get_type_layout` 均为 `black`。预热测试 monkeypatch `card_appearance`，断言 manifest entry 含当前 `appearance`，且 `card_pixmap` 每个定义只调用一次，不出现四框枚举。

- [ ] **Step 5: 接入渲染与预热**

在 `_card_pixmap_impl` 中，以存储的非默认牌框覆盖 `selected["frame_variant"]`；无偏好时继续使用配置值。保留本轮异画未实现约束，不改变 artwork 选择。`prewarm_iter` 的每个 definition entry 添加当前 `appearance`，使外观变化令 manifest 失配；实际渲染仍只调用现有单次 `card_pixmap`。

- [ ] **Step 6: 运行存储、卡图与预热定向测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_appearance.py tests/test_gui_builder.py -k 'appearance or frame_variant or prewarm'`
Expected: PASS。

### Task 2: 牌框预览对话框与式神录左右键

**Files:**
- Create: `client/gui/appearance.py`
- Modify: `client/gui/codex.py`
- Test: `tests/test_gui_appearance.py`
- Test: `tests/test_gui_codex.py`

**Interfaces:**
- Consumes: Task 1 的 `card_appearance`、`save_card_appearance` 与 `FRAME_VARIANTS`，以及现有 `CardChoiceView`。
- Produces: `CardAppearanceDialog(cdef, db, parent=None)`，公开 `selected_frame: str`、`choice_view: CardChoiceView`、`select_frame(variant)`；`ShikigamiCodexView.show_card_appearance(cdef)`。

- [ ] **Step 1: 写对话框与左右键失败测试**

创建对话框，依次调用四个牌框选择，断言 `choice_view` 使用对应牌框且 `selected_frame` 更新；未点击卡图时没有确认按钮，点击原画后放大并显示“确认”，点击确认才保存。取消路径断言文件不变。式神录测试 monkeypatch 外观与详情对话框，分别发射 `clicked`/`detail_clicked`，断言各打开一次且类型正确；外观 Accepted 后当前页控件重建。

- [ ] **Step 2: 运行测试确认接口缺失**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_appearance.py tests/test_gui_codex.py -k 'appearance'`
Expected: FAIL，对话框和分派方法不存在。

- [ ] **Step 3: 实现紧凑外观对话框**

顶部用四个 `QPushButton` 组成 checkable 互斥按钮组；中央复用单项 `CardChoiceView`，唯一候选为原画，按钮文本为“确认”。点击原画后沿用选择视图的居中放大和下方确认按钮；切换牌框时重建候选并保持已选中状态，不写偏好。确认时才调用 `save_card_appearance` 并 `accept()`，独立“取消”按钮直接关闭。对话框 `adjustSize()`，不添加垂直滚动区或黄色阴影。

为避免预览写盘，`CardWidget`、`CardChoiceView` 与 `card_pixmap` 增加可选 `frame_variant: str | None = None` 覆盖参数，优先级高于本机偏好；该参数进入现有 payload/cache key。`CardChoiceView` 另增可选 `button_text="选择"`，既有调用不变。

- [ ] **Step 4: 接入式神录并刷新当前页**

`_render_cards` 中为每个控件连接 `widget.clicked.connect(self.show_card_appearance)`；保留 `detail_clicked.connect(self.show_card_detail)`。对话框 Accepted 后调用 `_render_cards()`，其余页面不做全量重建。

- [ ] **Step 5: 运行对话框与式神录定向测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_appearance.py tests/test_gui_codex.py`
Expected: PASS。

### Task 3: 放大选择界面的统一间距与选中反馈

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/appearance.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_appearance.py`

**Interfaces:**
- Consumes: 现有 `CardChoiceView.select(...)` 与 Task 2 对话框。
- Produces: 行为不变的 `chosen`/`detail_clicked` 信号；无新增公共接口。

- [ ] **Step 1: 写无黄色光框与紧凑布局失败测试**

实例化含两个卡牌选项的 `CardChoiceView`，调用 `select(first)`，断言所有 wrapper 的 `graphicsEffect()` 都不是 `QGraphicsDropShadowEffect`，选中卡尺寸大于未选卡，只有选中按钮可见，按钮与卡图布局 `spacing <= 4`。外观对话框断言选择视图 `verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff`，按钮紧跟预览列且 `sizeHint().height()` 覆盖顶部牌框栏、放大卡图、确认与取消按钮。

- [ ] **Step 2: 运行测试确认旧选中效果失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_appearance.py -k 'choice_selection_layout or appearance_dialog_layout'`
Expected: FAIL，旧实现仍创建黄色 `QGraphicsDropShadowEffect`。

- [ ] **Step 3: 移除黄色光框并保持其他反馈**

`CardChoiceView.select` 删除 `QGraphicsDropShadowEffect` 分支及不再使用的 `QColor` 导入；保留非选项半透明、选中放大和下方按钮。列间距固定为 2，外层内容 margins 保持 12。对话框使用 `adjustSize()` 与最小尺寸约束，使正常内容无需垂直滚动，不添加额外背景块或黄色边框。

- [ ] **Step 4: 运行选择相关回归**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_battle.py tests/test_gui_online.py tests/test_gui_appearance.py -k 'choice or mulligan or discard or appearance'`
Expected: PASS。

### Task 4: 文档、精简复查与最终定向验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `docs/bwpdiy-integration.md`

**Interfaces:**
- Consumes: Tasks 1–3 的最终接口与行为。

- [ ] **Step 1: 更新文档**

说明本机外观文件、四框枚举、稀疏保存、全局大卡应用、小卡不变、仅当前外观预热及 manifest 指纹；式神录左右键分工和选择弹窗无黄色光框的交互也同步更新。移除旧文档中“异画替换不做”的过时绝对表述，改为“异画选择暂未开放，牌框可切换”。

- [ ] **Step 2: 做聚焦精简与安全复查**

确认没有重复偏好读写路径、没有把偏好写入 `library`、没有遍历外部目录或执行 DIY exe；存储只接受固定枚举和默认原画索引，临时文件与目标位于同一用户配置目录。仅清理本功能产生的无用导入，不做无关重构。

- [ ] **Step 3: 运行最终相关测试**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_appearance.py tests/test_gui_codex.py tests/test_gui_builder.py tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部通过；允许项目已有的环境相关 skip，不新增 skip。

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_mechanisms.py`
Expected: 全部通过，确认共用 `CardWidget`/`CardDetailDialog` 未回归。
