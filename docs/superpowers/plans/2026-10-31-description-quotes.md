# 卡牌描述引号与具名内容高亮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将描述外层引号改为『』、嵌套内层改为「」，并在卡图渲染时高亮完整匹配的具名内容。

**Architecture:** 用可测试的迁移工具做字节级精确替换，避免 YAML 重排；渲染层按当前 db 注入 `[[…]]`，raw/YAML 不保存渲染标记。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计来源：`docs/superpowers/specs/2026-10-31-description-quotes-design.md`。
- 本次仅按用户明确要求迁移 raw 引号，保留其他修订；不修改 library 配置。
- 外层『』、内层「」；raw/YAML 不写 `[[…]]`，db.validate 不加豁免。
- 所有新行为先写失败测试并确认 RED，再最小实现到 GREEN；修改 YAML 后跑 `db.validate`。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: raw 与 DB YAML 引号迁移

**Files:**
- Create: `db/migrate_quotes.py`
- Modify: `card_data_raw.md`
- Modify: `db/**/*.yaml`
- Modify: `db/rawtext.py`
- Modify: `docs/terminology.md`
- Test: `tests/test_data.py`
- Test: `tests/test_pack04_mech.py`

- [ ] **Step 1: 写迁移函数失败测试**

覆盖 `‘黄金羽’ → 『黄金羽』`、`‘本回合气绝时，替换为“棺材”’ → 『本回合气绝时，替换为「棺材」』`，其他双引号、效果、日期和文件换行不变。增加 raw/DB 旧单引号清零和角括号配对断言。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_data.py tests/test_pack04_mech.py -k 'quote or description'`
Expected: 无迁移函数且旧单引号仍存在。

- [ ] **Step 3: 实现并执行精确迁移**

`migrate_quotes.py` 提供 `convert_text(text) -> str`：先把唯一嵌套 `“棺材”` 转为 `「棺材」`，再把 `‘’` 转为 `『』`。CLI 仅对 raw 和 db YAML 做 UTF-8 字节级替换，不经过 yaml.safe_dump，不重排文件。执行迁移并同步 rawtext 示例、测试硬编码和术语文档。

- [ ] **Step 4: 校验与相关测试**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`
Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_data.py tests/test_pack04_mech.py -k 'quote or description'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add card_data_raw.md db docs/terminology.md tests/test_data.py tests/test_pack04_mech.py
git commit -m "refactor(文本): 统一卡牌描述嵌套引号"
git push
```

---

### Task 2: 具名引号内容渲染高亮

**Files:**
- Modify: `client/gui/cardart.py`
- Test: `tests/test_gui_builder.py`

- [ ] **Step 1: 写高亮失败测试**

覆盖普通卡牌、token 衍生牌、召唤/替换实体、灵咒、token 前缀族、『棺材』嵌套；整段能力文本与未知名称不包裹，已有 `[[…]]` 不重复，原 `[眩晕]` 和图标转换不变。断言输出如 `『[[黄金羽]]』`、`『…「[[棺材]]」…』`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py -k 'description or named_highlight'`
Expected: 引号内名称未注入高亮标记。

- [ ] **Step 3: 最小实现数据库感知高亮**

`_description` 接收 db，名称集合来自全部卡牌、非普通式神实体、灵咒和 token 的 `·` 前缀族。仅对 `「…」` 与 `『…』` 的完整内容精确匹配后包裹 `[[…]]`，两个实际调用点传入 db；不修改 BWPDIY。

- [ ] **Step 4: 相关测试、全量与数据校验**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py -k 'description or named_highlight'`
Expected: PASS。

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m db.validate`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/cardart.py tests/test_gui_builder.py
git commit -m "feat(gui): 高亮描述中的具名引号内容"
git push
```
