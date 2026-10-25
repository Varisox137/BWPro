# 本地卡图配置与合成缓存实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 默认读取项目 `/library` 的美术配置，以当前引擎数据合成阵容头像和卡面，并提供内容寻址缓存与文字回退。

**Architecture:** `bwpdiy.render` 进程内合成，exe 仅人工标注。`portrait.py` 分离渲染资源与配置库；新 `cardart.py` 负责版本选择、引擎映射、缓存和失败回退；`CardWidget`/手牌共享同一接口。

**Tech Stack:** Python 3.14、PySide6、Pillow、PyYAML、BWPDIY render、pytest offscreen。

## Global Constraints

- 设计：`docs/superpowers/specs/2026-10-25-local-cardart-pipeline-design.md`。
- 不启动 exe/HTTP 服务，不导入 BWPDIY web/store，不修改 `/library`、`card_data_raw.md`、引擎或协议。
- 配置的 description/旧数值不得覆盖 `CardDef`；`version_date` 必须是合法 8 位日期，同 id 多版本按 `CardDef.version` 选择。
- 缺配置/图片或渲染失败只回退，不弹窗；保留 YAML 256 KiB、路径穿越与 1600 万像素上限。
- 运行时增强保持独立信息层；无关未跟踪文件不得修改或纳入提交；测试不得读写真实 `~/.bwpro/cardart`，缓存目录一律注入临时路径。
- 全量 pytest 与 db.validate 由主上下文亲跑。

---

### Task 1: 项目配置库与引擎映射

**Files:**
- Create: `client/gui/cardart.py`
- Modify: `client/gui/portrait.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Produces: `library_root() -> Path`、`card_pixmap(cdef, db, *, library_dir=None, cache_dir=None) -> QPixmap | None`、`clear_cardart_caches()`。

- [ ] **Step 1: 写失败测试**

用临时 `library/项目/shikigami` 和 `cards` 创建两个同 id、不同 `version_date` 的配置，断言：

```python
assert library_root() == Path("D:/Programming/BWPro/library")
pix = card_pixmap(cdef_v20191212, db, library_dir=tmp_library, cache_dir=tmp_cache)
assert pix is not None and not pix.isNull()
```

覆盖：默认项目库头像、同 id 按版本选择、引擎文本覆盖配置旧文本、非法日期/缺配置返回 `None`。测试真实 BWPDIY assets，但不修改正式 `/library`。

- [ ] **Step 2: 验证失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py`
Expected: `client.gui.cardart` 不存在、项目库头像未生效，测试失败。

- [ ] **Step 3: 实现配置索引与引擎负载**

`library_root()` 默认项目根 `/library`，允许 `BWP_DIY_LIBRARY` 覆盖；`bwpdiy_root()` 继续提供渲染 assets。配置读取限制大小/映射，图片路径执行 `resolve + relative_to`，日期复用 `check_version_date`。

引擎映射：类型（战斗/法术/形态/幻境/协战/式神）、name、level、rarity、shikigami 名称、description、evolve、form_power/form_health、awaken_power/awaken_health、intensity→durability、战斗 power+/shield+。`[关键字]` → `[[关键字]]`；力量/生命/护甲/破甲/能量/耐久/战力/乏力/赏金分别映射 `ll/sm/hj/pj/nl/nj/zl/fl/sj`。配置仅提供 artwork/portrait/faction_style/layout 与 version_date。

- [ ] **Step 4: 验证映射与头像**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py`
Expected: 通过；白狼/兵俑实际配置可生成头像和全卡。

---

### Task 2: 内容寻址缓存与安全回退

**Files:**
- Modify: `client/gui/cardart.py`
- Test: `tests/test_gui_builder.py`

**Interfaces:**
- Consumes: Task 1 的引擎负载和配置索引。
- Produces: `~/.bwpro/cardart/<sha256>.png` 与有界内存缓存；`clear_cardart_caches()` 仅清内存，供测试隔离。

- [ ] **Step 1: 写失败测试**

```python
first = card_pixmap(cdef, db, library_dir=lib, cache_dir=cache)
assert len(list(cache.glob("*.png"))) == 1
second = card_pixmap(cdef, db, library_dir=lib, cache_dir=cache)
assert len(list(cache.glob("*.png"))) == 1
cdef.text = "引擎文本已变化"
third = card_pixmap(cdef, db, library_dir=lib, cache_dir=cache)
assert len(list(cache.glob("*.png"))) == 2
```

另测：同配置缓存命中、配置图片/布局变化产生新键、非法缩放/越界只回退、磁盘半图不视为有效缓存。

- [ ] **Step 2: 验证失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py`
Expected: 当前没有磁盘缓存或文本变化未产生新键，测试失败。

- [ ] **Step 3: 实现缓存键与原子写入**

缓存键输入为：规范化引擎负载、规范化 artwork/layout 配置、图片 `mtime_ns+size`、BWPDIY `__version__`、layout 内容。小 YAML 直接哈希内容，不重复哈希大图。PNG 先写同目录临时文件，成功加载校验后 `os.replace` 到最终键；内存 QPixmap 使用有界 LRU。估算渲染像素超过 1600 万时回退，禁止异常配置触发巨量分配。

- [ ] **Step 4: 验证缓存与回退**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py`
Expected: 全部通过；缓存行为不依赖正式用户配置。

---

### Task 3: 构筑与对局卡面接入

**Files:**
- Modify: `client/gui/widgets.py`
- Modify: `client/gui/builder.py`
- Modify: `client/gui/battle.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_battle.py`
- Test: `tests/test_gui_online.py`

**Interfaces:**
- Consumes: `card_pixmap(cdef, db, ...)`；联机运行时详情仍只用 payload `hand_info`。
- Produces: `CardWidget(cdef, copies=0, editable=False, parent=None, db=None)`；原有位置参数保持兼容。

- [ ] **Step 1: 写失败测试**

临时库为当前测试卡提供配置，断言 `CardWidget` 的 `art_label` 有图且原 name/level/type/stats/text 基础标签隐藏，但 copies/加减按钮保留；无配置时仍显示原文字卡。对局手牌、详情和联机均通过同一接口获取图片，运行时 `runtime_label` 不消失。

- [ ] **Step 2: 验证失败**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 当前没有 `art_label`，测试失败。

- [ ] **Step 3: 实现共享卡面**

`CardWidget` 增加可选 `db`，调用 `card_pixmap`；有图时隐藏重复基础区，保留 footer 与操作按钮。`DeckBuilderView` 传入 db；`HandCardFrame` 复用同一图片接口，不复制映射/缓存逻辑。失败路径不弹窗、不阻塞操作。

- [ ] **Step 4: 验证交互与隐私**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_battle.py tests/test_gui_online.py`
Expected: 全部通过；目标选择、交接、联机 hand_info 与静态详情不回归。

---

### Task 4: 文档、实图复核与最终验证

**Files:**
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Modify: `README.md`
- Modify: `C:/Users/Varis/.kimi-code/AGENTS.md`

- [ ] **Step 1: 同步文档**

写明 exe 仅人工标注、默认项目 `/library`、引擎数据合成、版本与日期规则、缓存键与文字回退；移除“cardart 待补”状态，不宣称未配置式神已有图。

- [ ] **Step 2: 实图复核**

用白狼/兵俑实际配置生成阵容和构筑/对局浅深截图到 `.tokensave/`，ReadMediaFile 逐张检查头像、全卡文本、按钮和运行时详情；不得写回 `/library`。

- [ ] **Step 3: 验证与索引**

Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`
Run: `git diff --check`
Expected: 全绿，db.validate 仅有既有非阻塞警告；随后重建 codebase-memory。

- [ ] **Step 4: 提交并推送**

更新测试数量，按中文 conventional 格式提交并 `git push`；只添加本任务文件，不添加 `/library`、exe、logs 或其他用户文件。
