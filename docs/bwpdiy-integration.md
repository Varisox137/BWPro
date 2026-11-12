# BWPDIY 适配层调整指南

日期：2026-10-30

本文记录 BWPro `client/gui` 集成 BWPDIY 的设计约束与实施口径。真实渲染 API 与最小自检以 BWPDIY 仓库的 `docs/integration.md` 为准。

## 目标与兼容约束

- 不修改 BWPDIY 的 `render_card`、`render_entity`、`render_portrait`、`render_mechanism` 接口。
- 保留现有占位图显示策略；合法透明占位属于正常渲染结果，`None`、空 `QPixmap` 和异常才不能计为渲染成功。
- 保持 `prewarm_all()` 返回成功 `entries`（全量缓存命中时返回全部成功条目），避免改变现有调用方契约。
- 小卡仅对具有 `charge` 的式神传 `energy`（含 0），仅对非气绝倒计时式神传 `countdown`，二者可共存；气绝保留能量、隐藏普通倒计时，并传复活倒计时或 `defeated_countdown="infinity"`。
- 不为诊断功能引入新依赖，不把异常文本直接拼入页面 HTML。

## 资源定位

位置：`client/gui/portrait.py` 的 `bwpdiy_root()`。

资源根按以下顺序定位：

1. `BWP_DIY_ROOT` 始终优先。
2. 未配置时，从 `portrait.py` 向上寻找最近的 `assets/frames`，默认命中 BWPro 项目内 `assets/`；worktree 也可携带自己的资源副本。
3. 项目内没有资源时，兼容查找同级 `BWPDIY/assets`。
4. 都找不到时保留原默认路径作为回退，由后续异常日志报告资源缺失。

素材同步复制 BWPDIY `assets/` 的全部文件，同时保留本项目新增素材与旧兼容路径；PSD、`ref/`、`psd_export/` 仅作源文件与视觉参考，运行时仍由渲染器消费标准资源目录。对局 UI 字样、按钮、卡背与骰子由 `client/gui/ui_assets.py` 直接读取项目资源根下的 `animations/`、`turn_buttons/`、`cardbacks/`、`dice/`，带文件时间戳的内存缓存，不进入卡图 manifest；1–6 点读取预合成的完整骰面，统一保留 6 点模板的透明边距与浅色圆角框，卡背按 alpha 裁紧。大卡、小卡、头像与机制框统一经 `load_global_layouts()` 读取 `~/.bwpdiy/layout.json`，缺失时由 BWPDIY 回退包内默认布局；布局缓存指纹跟踪全局文件内容。卡图资源指纹包含 `badges/` 与 `numbers/`，其内容更新会使缓存失效。渲染 Python 包与素材分离定位：资源根包含 `bwpdiy/render` 时直接使用，否则由 `bwpdiy_code_root()` 复用同级 BWPDIY 源码；卡图缓存的源码指纹也使用该代码根，不要求素材与源码同目录。

卡图描述更新后运行 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.sync_library_text`；同步按卡名与 `version_date` 读取引擎历史文本（同名实体再按 id 消歧），仅改写 `description`，`--check` 只检查差异。

editable 安装只解决 Python 导入，不能替代资源根定位。需要改用另一份素材或配置时可显式设置：

```bash
BWP_DIY_ROOT='D:/Programming/BWPDIY'
BWP_DIY_LIBRARY='D:/Programming/BWPro/library'
```

## 渲染与缓存约束

- 大卡与式神小卡的缓存及 manifest 依据定义、实际 layout、配置、原图和渲染资源内容判定失效，不包含临时解包路径。大卡的 `frame_variant` 与机制框的 `badge` 均进入渲染负载和缓存身份；头像仅以路径、mtime 与大小组成进程内 LRU 键，不写磁盘缓存。
- 预热只合成当前选择外观的大卡与式神小卡，不枚举牌框、不预热头像。只有所有所需图片均返回非 `None` 且非空 `QPixmap`，才把定义写入成功 `entries`；失败写入 `failures` 并在下次启动重试。manifest 原子记录期望清单、外观、资源指纹及 `total/succeeded/failed/skipped` 统计。
- 预热调用把显式 `library_dir/cache_dir` 原样转发给实际渲染，避免清单与写入使用不同目录。设置页显示缓存条目数、三项统计、最多三条失败摘要与 manifest 完整路径。
- 渲染或配置异常边界记录渲染类型、实体 id 或名称、资源根、配置路径和异常堆栈；磁盘缓存读写失败附带 `direction=read/write`。相同失败以有界键去重，清理缓存时同时清理去重状态。
