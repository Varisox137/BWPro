# BWPDIY 适配层调整指南

日期：2026-10-30

本文记录 BWPro `client/gui` 集成 BWPDIY 的设计约束与实施口径。真实渲染 API 与最小自检以 BWPDIY 仓库的 `docs/integration.md` 为准。

## 目标与兼容约束

- 不修改 BWPDIY 的 `render_card`、`render_entity`、`render_portrait`、`render_mechanism` 接口。
- 保留现有占位图显示策略；合法透明占位属于正常渲染结果，`None`、空 `QPixmap` 和异常才不能计为渲染成功。
- 保持 `prewarm_all()` 返回成功 `entries`（全量缓存命中时返回全部成功条目），避免改变现有调用方契约。
- 不为诊断功能引入新依赖，不把异常文本直接拼入页面 HTML。

## 1. 高优先级

### 1.1 worktree 资源根

位置：`client/gui/portrait.py` 的 `bwpdiy_root()`。

资源根按以下顺序定位；向上查找同时覆盖普通 checkout 与 `.worktrees/<分支>`，固定层级回退仅在找不到有效资源目录时使用：

1. `BWP_DIY_ROOT` 始终优先。
2. 未配置时，从 `portrait.py` 的各级祖先目录向上寻找具有同级 `BWPDIY/assets` 的目录。
3. 都找不到时保留原默认路径作为回退，由后续异常日志报告资源缺失。

editable 安装只解决 Python 导入，不能替代资源根定位。非同级目录、worktree 和便携部署应显式设置：

```bash
BWP_DIY_ROOT='D:/Programming/BWPDIY'
BWP_DIY_LIBRARY='D:/Programming/BWPro/library'
```

### 1.2 渲染与配置异常日志

位置：

- `client/gui/cardart.py`：大卡、小卡渲染与卡牌配置解析；
- `client/gui/portrait.py`：头像渲染、空槽回退与式神配置解析；
- `client/gui/mechanisms.py`：机制框渲染与机制配置解析。

在所有返回 `None` 或占位图的异常边界记录：渲染类型、卡牌/式神 id 或名称、资源根、配置路径（适用时）和异常堆栈。磁盘缓存读写失败使用独立的“缓存失败”上下文，并附 `direction=read/write`，不与真正的渲染失败混用。

相同失败使用有界键去重，键为 `(kind, entity, root, config_path)`；缓存读写方向并入 kind，不包含异常类型和消息，避免 GUI 刷新反复刷日志。`clear_cardart_caches()` 应同时清理去重状态，使用户主动重建后能看到最新失败。不要仅记录固定“渲染失败”文本，也不要静默 `except Exception: return None`。

### 1.3 预热成功清单与失败重试

位置：`client/gui/prewarm.py`、`client/gui/settings.py`。

建议每次先构造全部期望条目，再按实际结果写 manifest：

- 缓存与 manifest 依据定义、配置、原图及渲染实现的资源内容指纹判定失效，不以 BWPDIY 版本号判定。
- 预热仅合成大卡与式神小卡，不包含头像；头像只使用内存 LRU，不写磁盘缓存。
- 大卡调用必须返回 `pixmap is not None and not pixmap.isNull()`；式神所需的小卡也必须满足同一条件。
- 一个定义所需图片全部成功，才把该定义条目写入成功 `entries`。
- 失败定义写入 `failures`，保留 `kind/id/version/reason`；具体异常堆栈由渲染边界日志负责。
- `stats` 记录本次 `total/succeeded/failed/skipped`，以定义条目为单位，不把同一式神的大卡和小卡重复计数；全量缓存命中时 `skipped == total`、`failed == 0`。
- 全部期望条目匹配时才跳过预热，并原子写回统计；存在失败时，成功 `entries` 与期望清单不同，下次启动自动重试。
- `prewarm_all()` 返回成功 `entries`，不返回失败定义；`on_progress` 继续按实际处理进度回报。

设置页应显示缓存条目数、本次成功/失败/跳过数量和最多三条失败摘要。完整失败原因保留在 manifest，并提供 manifest 完整路径；不能只按 `entries` 数量显示“已生成”。

## 2. 中低优先级

### 2.1 预热显式路径转发

位置：`client/gui/prewarm.py` 的 `prewarm_all()`。

实际调用 `card_pixmap()`、`entity_pixmap()` 时，应把函数收到的 `library_dir`、`cache_dir` 继续传入，避免“清单来自 A、实际渲染与写入使用 B”。默认启动流程行为不变。

### 2.2 大卡框品

位置：`client/gui/cardart.py` 的配置选择、`_card_data()` 与 `_card_pixmap_impl()`。

配置的 `frame_variant` 应同时：

1. 进入大卡渲染负载；
2. 作为 `get_type_layout(..., frame_variant)` 的框品参数；
3. 通过现有负载和布局 JSON 自然进入缓存身份。

小卡使用同一负载字段选择框内卡图窗口。未配置时继续使用 `norm`，不改变现有普通框结果。

### 2.3 机制 badge

位置：`client/gui/mechanisms.py` 的 `_mechanism_pixmap()` 与 `mechanism_panel()`。

`_library_mechanisms()` 已读取 `badge`，后续不能丢弃。`badge` 应进入 `_mechanism_pixmap` 的参数和 LRU 身份，并传入 `render_mechanism` 的负载。无 badge 的现有机制保持原输出；`seal` 的 `bless/eclipse` 应得到不同缓存项和正确角标。

### 2.4 头像内容摘要

位置：`client/gui/portrait.py` 的 `shikigami_portrait()` 与 `_portrait_pixmap()`。

头像只使用内存 LRU，不写磁盘缓存。LRU 当前使用图片路径、mtime 和大小识别更新，建议改为内容 SHA-256，与大卡/小卡一致。这样同路径图片即使保留时间戳且大小不变，替换后仍会生成新缓存项。

## 3. 回归测试清单

后续实施应先添加测试并确认旧实现按预期失败，再修改代码。测试按主题放入现有文件，不新建按函数拆分的测试文件。

### `tests/test_gui_builder.py`

- `test_bwpdiy_root_worktree_finds_sibling_assets`：模拟 `.worktrees/<分支>/client/gui/portrait.py`，断言定位真实同级 `BWPDIY/assets`；环境变量覆盖优先于自动推导。
- `test_render_failure_logs_context_once`：连续触发同一失败，断言日志含类型、id、资源根和堆栈且不重复；清缓存后可再次记录。
- `test_cardart_frame_variant_selects_payload_and_layout`：非常规框配置同时进入渲染负载和布局选择，缺省仍为 `norm`。
- `test_portrait_same_metadata_content_change_invalidates`：替换图片内容后恢复原 mtime、保持大小不变，第二次头像仍与第一次不同。

### `tests/test_gui_prewarm.py`

- `test_prewarm_forwards_explicit_paths`：非默认临时 `library_dir/cache_dir` 原样传入大卡和小卡调用。
- `test_prewarm_failure_not_marked_current_and_retries`：返回 `None` 或空 `QPixmap` 的条目不进入成功 `entries`，manifest 记录失败；第二次调用会重试，修复后可生成完整成功清单。
- `test_prewarm_stats_count_success_failure_and_skip`：成功、失败和全量跳过三种情况的统计口径正确，返回值为成功 `entries`。
- `test_settings_show_prewarm_stats_and_failures`：设置页显示三项统计、失败摘要和 manifest 路径，不仅显示条目数。

### `tests/test_gui_mechanisms.py`

- `test_mechanism_badge_enters_payload_and_cache_key`：相同名称、框体和文本但 badge 不同的机制分别渲染，负载包含正确 badge，缓存不串用。

## 4. 推荐实施顺序与验证

1. 修复资源根、异常日志和预热成功判定；
2. 转发预热显式路径；
3. 补齐框品与机制 badge；
4. 统一头像内容摘要；
5. 运行相关 GUI 测试，再运行全量测试：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q
```

最后使用 BWPDIY `docs/integration.md` 第 9 节执行大卡、小卡、头像和机制框的真实自检，并确认非法尺寸异常能在调用方日志中定位。只有实际图片非空才算自检成功。
