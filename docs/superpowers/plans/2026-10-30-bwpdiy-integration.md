# BWPDIY 集成适配收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 worktree 资源根、渲染诊断、frame_variant/badge 透传、运行时失败重试和预热统计，完成 BWPDIY 集成收尾。

**Architecture:** 新增独立 `renderlog` 做有界失败日志，避免 cardart/portrait 循环依赖；现有 cardart/mechanisms 只补渲染负载与成功缓存；prewarm/settings 复用当前 manifest，不改变成功 entries 返回契约。

**Tech Stack:** Python 3.14、PySide6、BWPDIY、pytest、pytest-xdist。

## Global Constraints

- 设计唯一来源：`docs/superpowers/specs/2026-10-30-bwpdiy-integration-design.md`。
- BWPDIY 四个渲染入口 API 不变，不修改对方源码。
- 透明插画牌框和空头像槽是合法结果，不记为渲染异常。
- 缓存身份使用渲染实现指纹，不恢复 BWPDIY 版本号依赖。
- 所有新行为先写失败测试并实际确认 RED，再最小实现到 GREEN。
- 测试使用主仓库解释器与 `BWP_DIY_ROOT='D:/Programming/BWPDIY'`、`BWP_DIY_LIBRARY='D:/Programming/BWPro/library'`。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: worktree 资源根与有界渲染日志

**Files:**
- Create: `client/gui/renderlog.py`
- Modify: `client/gui/portrait.py`
- Modify: `client/gui/cardart.py`
- Modify: `client/gui/mechanisms.py`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_mechanisms.py`

**Interfaces:**
- Produces: `log_render_failure(kind, entity, root, error, config_path=None) -> bool`；`clear_render_log_dedup() -> None`；`portrait.bwpdiy_root()` 环境变量优先并向上查找同级 BWPDIY。

- [ ] **Step 1: 写资源根与日志失败测试**

资源根测试把 `portrait.__file__` 指向临时 `.worktrees/feature/client/gui/portrait.py`，在旁边建立 `BWPro` 与同级 `BWPDIY/assets` 的目录结构，断言能找到正确根；设置 `BWP_DIY_ROOT` 时始终优先。

日志测试使用 `caplog`：同一 kind/id/root 连续两次异常只写一条，另一种 id 再写一条；调用 `clear_render_log_dedup()` 后同异常可再次记录。断言文本包含 kind、id、root 和 config_path。另断言合法透明占位不会调用该 helper。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_mechanisms.py -k 'worktree_root or render_failure_log'`
Expected: 无 renderlog 且 worktree 推导错误。

- [ ] **Step 3: 实现根推导与独立日志 helper**

`bwpdiy_root()` 先读环境变量；否则遍历 `Path(__file__).resolve().parents`，以 `anchor.parent / "BWPDIY"` 为候选，返回首个 `candidate/assets` 存在的路径；无候选时保留原推导作为最后回退。

`renderlog.py` 使用最多 128 个 key 的集合：

```python
def log_render_failure(kind, entity, root, error, config_path=None):
    key = (kind, str(entity), str(root), str(config_path or ""))
    if key in _seen:
        return False
    if len(_seen) >= 128:
        _seen.clear()
    _seen.add(key)
    logger.error("渲染失败 kind=%s id=%s root=%s config=%s",
                 kind, entity, root, config_path or "-", exc_info=True)
    return True
```

在 cardart/portrait/mechanisms 的现有异常边界调用，保留返回 None/合法占位的显示策略；YAML 跳过 malformed 时附配置路径。`clear_cardart_caches()` 同步调用 `clear_render_log_dedup()`。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_mechanisms.py -k 'worktree_root or render_failure_log or mechanisms'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/renderlog.py client/gui/portrait.py client/gui/cardart.py client/gui/mechanisms.py tests/test_gui_builder.py tests/test_gui_mechanisms.py
git commit -m "fix(gui): 完善DIY资源定位与渲染诊断"
git push
```

---

### Task 2: frame_variant、badge 与运行时成功缓存

**Files:**
- Modify: `client/gui/cardart.py`
- Modify: `client/gui/mechanisms.py:153-191`
- Test: `tests/test_gui_builder.py`
- Test: `tests/test_gui_mechanisms.py`

**Interfaces:**
- Consumes: 配置中的 `frame_variant`、机制 YAML 的 `badge` 和 `_cache_successful_pixmap`。
- Produces: `_mechanism_pixmap(..., font_scale=1.0, badge=None)`；运行时两个 LRU 只缓存成功 pixmap。

- [ ] **Step 1: 写字段透传与运行时重试失败测试**

大卡测试令配置含 `frame_variant: blue`，捕获 payload/layout 和 `get_type_layout` 第三个参数，断言三者均为 blue；小卡捕获 payload 同样为 blue。

机制测试调用两次仅 badge 不同的 `_mechanism_pixmap`，捕获 render 输入，断言 badge 传入且 LRU 未把两种输入混为一项。

运行时测试参照静态 success-only 用例：同一参数第一次底层 renderer 返回 None、第二次返回有效 pixmap，未手动 clear 时必须真实调用两次，覆盖 `_cached_runtime_card_pixmap` 与 `_cached_entity_pixmap`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_mechanisms.py -k 'frame_variant or badge or runtime_failure_retry'`
Expected: 框品/badge 丢失，运行时 LRU 缓存 None。

- [ ] **Step 3: 最小实现字段透传与成功缓存**

大卡和小卡的 `selected` 在配置存在时加入 `frame_variant`，默认 `norm`；大卡调用：

```python
base_layout = get_type_layout(
    _layouts(root_text, _layout_fingerprint(assets)),
    payload["type"], payload.get("frame_variant", "norm"))
```

`_mechanism_pixmap` 在签名末尾增加 `badge=None`，构造机制 dict 时仅在非空时写入 badge，并让 lru_cache 自动隔离该参数；`mechanism_panel` 从 mechanism 传入。

给 `_cached_runtime_card_pixmap` 和 `_cached_entity_pixmap` 使用与静态路线相同的 `_cache_successful_pixmap`，保持 `cache_clear` 可用。

- [ ] **Step 4: 运行相关测试确认 GREEN**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_builder.py tests/test_gui_mechanisms.py -k 'frame_variant or badge or runtime_failure_retry or mechanisms'`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add client/gui/cardart.py client/gui/mechanisms.py tests/test_gui_builder.py tests/test_gui_mechanisms.py
git commit -m "fix(gui): 补齐DIY渲染字段与失败重试"
git push
```

---

### Task 3: 预热统计、失败摘要与文档校正

**Files:**
- Modify: `client/gui/prewarm.py`
- Modify: `client/gui/settings.py`
- Modify: `docs/bwpdiy-integration.md`
- Modify: `docs/gui-design.md`
- Modify: `docs/gui-plan.md`
- Test: `tests/test_gui_prewarm.py`

**Interfaces:**
- Consumes: Task 2 的成功缓存和当前 `prewarm_iter()`。
- Produces: manifest `stats.skipped`、failures 的 `version/reason`；设置页统计与路径展示。

- [ ] **Step 1: 写统计与设置页失败测试**

首次预热令一个定义返回 None，断言失败项包含 kind/id/version/reason；第二次完整命中时，manifest `stats.skipped == total`、`failed == 0`。设置页断言文本含成功、失败、跳过数量、首个失败 id 和 manifest 路径。

文档测试或人工 diff 核对以下准确口径：头像只有 LRU、预热仅大卡/小卡、透明占位合法、缓存用实现指纹、prewarm_all 返回成功 entries。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py -k 'stats or failure_summary or settings'`
Expected: 全量跳过未记录 skipped，失败缺 version/reason，设置页信息不足。

- [ ] **Step 3: 实现统计与失败摘要**

`prewarm_iter` 在 `_manifest_current` 分支把当前 manifest 的 stats 更新为 `total/succeeded/failed/skipped`，其中 skipped=total，再原子写回并返回 entries。失败项记录：

```python
{
    "kind": kind,
    "id": definition.id,
    "version": definition.version,
    "reason": "渲染返回空图",
}
```

`SettingsView.refresh_status()` 优先显示 stats，追加最多三条失败摘要及 `self.cache_dir / MANIFEST_NAME` 的完整路径；旧 manifest 保持兼容。

- [ ] **Step 4: 同步文档并运行相关测试**

更新三份文档，明确：实现指纹而非版本号、头像无磁盘缓存、预热只含大卡/小卡、透明占位合法、成功 entries 返回契约、editable 安装不解决资源根。

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_gui_prewarm.py`
Expected: 全部 PASS。

- [ ] **Step 5: 全量验证并 Commit**

Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全量 PASS。

```bash
git add client/gui/prewarm.py client/gui/settings.py docs/bwpdiy-integration.md docs/gui-design.md docs/gui-plan.md tests/test_gui_prewarm.py
git commit -m "docs(gui): 完善DIY预热统计与集成口径"
git push
```
