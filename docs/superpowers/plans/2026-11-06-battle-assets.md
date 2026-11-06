# 对局首批美术素材接入实施计划

> 按已批准设计在当前会话内联实施；每步先写失败测试，再写最小实现。不擅自提交。

**目标：** 接入首批对局素材，保证热坐/联机一致且不阻塞操作。

**架构：** `client/gui/ui_assets.py` 负责资源与持久化；引擎只追加结构化 timeline 视觉事件；`BattleScene` 统一播放非阻塞动画；既有对局控件仅替换视觉，不改交互接口。

**技术栈：** Python、PySide6、Pillow、pytest。

## 全局约束

- 不恢复已删除旧素材路径，不修改 `card_data_raw.md`。
- 视觉事件不进入文字对局记录，不改变规则结果。
- 浅色主题使用 `*_light.png`，深色主题使用 `*_dark.png`。
- 设置仅列已命名卡背，默认「月明风清」。

### 任务 1：资源加载与设置

- [ ] 在 `tests/test_gui_battle.py`、`tests/test_gui_prewarm.py` 增加骰子六面裁剪、卡背过滤、默认配置与保存失败测试并确认失败。
- [ ] 新建 `client/gui/ui_assets.py`，实现 `ui_pixmap`、`dice_face`、`named_cardbacks`、`load_gui_settings`、`save_gui_settings`。
- [ ] 修改 `client/gui/settings.py` 增加双方卡背选择并持久化。
- [ ] 运行相关测试确认通过。

### 任务 2：结构化视觉事件与场景动画

- [ ] 为气绝、运势、重投事件及倒计时延迟编写失败测试。
- [ ] 在 `core/engine.py` 的既有气绝/运势单点追加 `k="v"` timeline 项，更新 `core/model.py` 注释。
- [ ] 在 `client/gui/battle_scene.py` 实现统一渐现渐隐图元、事件定位、骰面与结果叠加、气绝倒计时延迟和清理。
- [ ] 修改 `client/gui/battle.py`、`client/gui/online.py`，让两种模式消费视觉事件且文字队列忽略它们。
- [ ] 运行相关测试确认通过。

### 任务 3：回合、按钮、胜负与卡背

- [ ] 为主题回合字样、结束回合按钮、胜负素材、手牌/牌库卡背编写失败测试。
- [ ] 修改对局主题与状态同步，替换相应视觉，保留原按钮尺寸和合法性检查。
- [ ] 运行 GUI 热坐/联机测试确认通过。

### 任务 4：收尾验证

- [ ] 更新 `docs/gui-design.md`、`docs/bwpdiy-integration.md` 的资源与视觉事件契约。
- [ ] 做真实离屏渲染抽查并读取生成图片。
- [ ] 主上下文运行全量 pytest、`git diff --check`，汇报结果；不自动提交。
