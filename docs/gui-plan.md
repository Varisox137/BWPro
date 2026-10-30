# 桌面 GUI 客户端实施计划（PySide6）

> 状态：**Step 1-5 已完成**（骨架/构筑/热坐/联机/本地卡图管线，2026-10 落地，见各 commit）。
> 卡图由项目 `library/` 标注与 BWPDIY 引擎数据合成，按版本匹配并使用内容寻址缓存；配置与图片纳入版本管理。缺插画时保留透明卡框，仅渲染失败才回退文字卡/头像。对局式神走 `render_entity`，卡图按原生 `height` 重绘且尺寸进入缓存键。式神录支持筛选、版本包折叠树、选卡进入等宽五卡列表与详情。
> 后续可补：大厅对手卡组名（需服务端 lobby 消息补充）。
>
> 界面布局与外部调研见 `docs/gui-design.md`（bwpemu/BWPDIY 结论 + gui-mock 浅深两套各 23 张初稿）。

## 目标

新增原生桌面 GUI 客户端（入口 `python -m client.gui`），把 CLI 三大功能完整图形化：**卡组构筑（本地 decks.json 全管理）、本地热坐对战、联机对战**。CLI 保留不动，GUI 与 CLI 共享 `core/`+`db/`+`client/` 纯数据层，卡组文件 `~/.bwpro/decks.json` 天然互通。

## 架构决策（已定）

- **库**：PySide6（`uv add pyside6`；LGPL，官方维护）。不用 PyQt5/6（GPL 传染性）。
- **异步模型**：**不引入 qasync**。现有 `client/net.py` 是同步阻塞模型（`websockets.sync` + 守护线程 recv_loop）——联机时收包线程通过 Qt 信号（`Signal`）投递到主线程即可，天然契合。
- **热坐**：`Game` 直接在 GUI 主线程构造与 `apply()`（引擎非线程安全，主线程串行调用即可；结算回放用 `QTimer` 按 0.3s 节奏播 timeline 增量，弃用 `client/settle.py`）。
- **联机**：沿用"服务端权威 + 本地只读 wrapper 渲染"模式（`net.py:91 wrapper()` 先例）；不照搬 `send_cmd` 的 2s 轮询等待，改为发后即返回、等 state 推送刷新。
- **卡图**：BWPro 只调用 `bwpdiy.render`，不启动 exe 或服务；exe 仅用于人工标注。默认只读项目 `library/`（`BWP_DIY_LIBRARY` 可覆盖），BWPDIY 渲染资源根用 `BWP_DIY_ROOT` 覆盖。按 id/名称与引擎版本日期精确选择配置，显示数据由引擎合成；缺配置或插画时仍合成完整卡框并透明插画，只有渲染器失败才回退文字卡/菱形头像。

## 复用清单（勘察已核实，禁止重写）

- 构筑：`deckbuilder.available_shikigami/buildable_cards`、`db/deckstore.py`（load/save/check_deck/entry_code）、`db/deck.py validate_deck/rules_summary/STANDARD_RULES`、`db/deckcode.py`、`db/envs.py`（环境解析）。
- 对局数据：`cli.hand_cards_info(game, pi)`（联机 hand_info 同源）、`cli.hand_sorted/_stats_label/format_seat_line`、`Game.usage_options`、`Game.reinforce_sub_option_error`、`targets.spec_pool_refs(…, targeted=True)`、`cli.parse_ref/ref_code`。
- 联机协议：`server/protocol.py` 消息构造器与类型表、`net.normalize_server_url/probe_connection/_open_ws`、cmd dict 组装语义（play_card/assault/upgrade/end_turn/mulligan/ready/choose + choice/target/target2/play_method）。
- 决策点：`state.pending_choice`（7 种 kind，作答 uid/choice）、`state.phase`（mulligan/upgrade/battle）。

## 文件布局（新增包，不动现有模块）

```
client/gui/__init__.py        # 包说明
client/gui/__main__.py        # python -m client.gui 入口：QApplication + 主窗口
client/gui/app.py             # MainWindow + 视图栈 + 常驻返回/主题开关 + 全局样式
client/gui/builder.py         # 卡组构筑视图
client/gui/battle.py          # 对局视图、隐私交接与指令入口（热坐/联机共用）
client/gui/battle_scene.py    # 固定坐标场景、图元同步与拖拽交互
client/gui/details.py         # 式神基础/觉醒/形态详情与运行时状态
client/gui/widgets.py         # 卡牌控件/详情弹窗/通用中文弹窗按钮
client/gui/online.py          # 联机：大厅视图 + NetBridge（收包线程→Qt 信号）
client/gui/portrait.py        # 项目库式神头像（失败回退菱形占位）
client/gui/cardart.py         # 引擎数据合成、版本匹配、内容寻址缓存与文字回退
tests/test_gui*.py            # 按主窗口/构筑/热坐/联机等主题拆分的 offscreen 测试
```

## 实施步骤

### Step 1 — 骨架与主菜单（小步可验）
- `uv add pyside6`；`__main__.py` 入口；`app.py`：MainWindow + QStackedWidget，主菜单三按钮（1 卡组构筑 / 2 本地热坐 / 3 联机对战），各视图占位页 + 返回主菜单。
- test_gui.py：offscreen 平台下主窗口构造、菜单导航冒烟。

### Step 2 — 卡组构筑视图（builder.py）
功能对齐 CLI 构筑全部能力：
- 卡组管理列表：加载 `load_decks`；新建/编辑/重命名/删除；标准卡组亮蓝色（Qt 刷子）标记；非法卡组可保存仅标色（与 CLI 同口径）；每次保存后全量重校验并原子写回。
- 点击编辑直接进入该卡组，不再额外弹卡组码；卡组码仅通过独立查看/导入入口处理。退出构筑时回到卡组管理列表，未保存修改需选择保存、放弃或取消。
- 编辑流程：式神选择（按版本包二级分组 + 搜索框直输全名，用分组树/列表，式神名列加宽、减少缩进）→ 单式神 8 卡勾选（本家卡 id 升序 1-8 号、协战牌列最后，同 CLI）→ 同种卡限 2 提示但不强制。
- 卡页首位显示该基础式神卡供参考，不计入 8 张带卡且不可增减；普通卡每页 5 张。卡面不再额外套外框，底部按 `[-] 已选 x/2 [+]` 排列；点击卡面查看完整文本。
- 环境选择下拉（别名+6/8 位日期，复用 envs）。
- 测试：decks.json 读写往返、校验标色逻辑（offscreen 直接调视图方法）。

### Step 3 — 热坐对战视图（battle.py + widgets.py）
- 启动：双方各弹卡组选择对话框（复用 Step 2 的卡组列表组件，只列标准卡组；规则同 CLI `_choose_deck`）→ 每局生成随机 seed 并调用 `new_game`（测试显式 seed 仍保持确定性）→ 进入对局视图。
- 场况区（当前实现）：`battle_scene.py` 以 1600×900 逻辑坐标的 `QGraphicsScene/QGraphicsView` 绘制，主窗口四周统一 12px padding，固定己下敌上，视角切换时复用 8 个式神图元并重排上下半场。准备区使用 148×210px 图元、横坐标 400+190×座次与 `24, 0, 0, 24` 弧线错位；`combat_index` 将既有图元移入中央上/下战斗位置，离战返回准备区，不创建替身或改变规则目标。牌手贴近左上和左下角，退出按钮位于场景右上、主题按钮左侧，右侧为双方上下镜像的三张横置斜叠牌库卡背（空库不显示），数量文本置于卡背组右侧；104px 圆形结束回合按钮有独立禁用态配色，左中为战斗记录；牌库仅显示公开数量，不提供内容查看。牌手面板显示生命/鬼火/出击/鼓舞，幻境与墓地数量仅在牌手详情显示；式神常态仅保留名称与等级、力量/生命、护甲/破甲和可用的倒计时，完整状态进入详情弹窗。阶段文本以较小字号位于回合文本右侧，不再居中遮挡场况。
- 手牌区：双方手牌分别在右上/右下排列并按实际卡面宽度右对齐，多张时横向重叠且覆盖在式神上层，不使用滚动区。常态己方按所属式神座次、等级、卡牌 id、`hand_seq` 排序且中立最后，敌方与调度保留 `hand_seq`，显示排序不改写底层记录。当前视角显示正面，敌方未展示牌只有卡背，`mods["revealed"]` 实例在原位置显示正面且不泄露其他卡牌定义。手牌、形态及基础/觉醒式神均走 DIY 合成并接收运行时数值；等级勾玉按准备区座次使用 `yellow/cyan/purple/red`，无座次默认黄色。缺配置或插画时仍绘制完整卡框，插画区域透明，场景保持合成图长宽比。操作色按卡图 alpha/轮廓掩码绘制加粗渐变外光，不回退矩形 tight box；实际合法子选项数大于 1 为绿色，单一合法项按 `cost == 0` 为蓝色、否则黄色，不合法卡无光效。
- 操作流：
  - 点击手牌或式神查看详情；非追猎式神拖出源范围即出击，追猎与目标手牌必须拖到合法角色，无目标手牌拖出后使用。多种使用方式在场景中央按调度式 180×255 大卡并列展示全部 `usage_options`（含协战子选项与爆能等），不可用项显示 `reason` 且不可选，合法项按统一 `id` 提交并保留拖放目标；`target2` 等后续目标沿用合法图元高亮点选，最终均组装 cmd dict 并调用 `game.apply`。
  - 升级阶段由回合文本右侧标签提示，可升级式神上方显示目标等级的座次色勾玉，其余画面由带孔洞的遮罩压暗；拖拽时仅源卡、合法目标（含牌手）与箭头高亮。点击可升级式神，结束回合使用右侧圆钮。原位/无效落点取消拖拽，交接、结算选择与终局禁止输入；timeline 播放不再禁止合法操作。
  - 调度阶段己方五张大卡在场景中央横排并显示先后手，仅当前未确认方手牌正面可见，另一方仍为卡背；点击手牌选中放大，再点该卡正下方跟随显示的"替换"按钮调度，拖拽不直接换牌，确认（ready）按钮位于结束回合左侧。
  - pending_choice：按支持的 kind 弹对应选择对话框（选项列表/两级 card_name/灵咒选择等），作答 `{"op":"choose", ...}`。
- 结算展示与动画：按 QTimer 0.3s/条后台播放 `state.timeline` 文字增量，播放期间继续允许合法操作；待处理选择、交接、终局及联机等待响应门控不变。左侧中部"战斗记录"打开默认隐藏的独立非模态日志窗，复用同一窗口，关闭不影响播放；按查看方过滤私有条目，并在起始调度阶段隐藏对手调度张数。本地热坐由引擎 cmd/event/op `trace` 写运行日志；联机仅写服务端过滤后随 state 下发的 `trace`。统一 `_emit_card_played` 另发仅含公开 `uid/card_id/player` 的 `k="a"` 条目，热坐与联机据此播放双方用牌动画而不写入文字记录。式神位置变化采用 180ms 线性动画；用牌从缓存的旧手牌位置/卡图离开，翻转后在左侧以大卡停留并淡出，900ms 后清理。初次渲染、视角切换、交接和重开跳过并清理动画，新位置动画停止同图元旧动画，所有动画均不参与输入门控。
- 热坐交接：查看方变化时暂停 timeline，清空手牌/目标/选择状态与动画并关闭日志，以不可取消绕过的模态确认窗要求交接设备；确认后重绘新视角并恢复结算。第三次调度后先保留旧视角的换牌结果并提示次数用完，确认交接时才清空。终局不额外插入交接。
- 统一弹窗：`QDialogButtonBox`/`QMessageBox` 按钮统一经 `polish_dialog_buttons` 设置中文与样式；牌手、式神、卡牌、交接等详情/确认采用应用内弹窗。
- 式神运行时详情同排为**式神主卡、同尺寸形态（如有）、全部额外状态（如有）、机制说明（如有）**，无内容不留空列；第三、四列分别以最大高度 336px 的 BWPDIY 机制框独立滚动。觉醒主卡使用基础身材加永久修正，形态卡保持自身 `form_power/form_health` 基础值。额外状态包含非零护甲/破甲与能量、永久/临时/动态修正、关键字、攻击强化、免疫、眩晕、延迟能力与灵咒等，不重复基础身材、派系和主卡/觉醒/形态原文，秘密延迟目标仍按 viewer 隐藏。第四列按主卡、形态、第三列文本首次出现、当前关键字的次序合并并去重；灵咒原文不再形成独立机制项。当前视角手牌详情带运行时数值，敌方已展示手牌只有静态详情。机制定义加载项目 `library/mechanisms/*.yaml` 的 `name/frame/text/badge/version_date`，说明正文与机制框顺序同步。**逐条增益来源账本尚未实现**，不能把汇总修正视为逐来源审计。
- 终局：胜负横幅 → 回主菜单；仍可点击已公开手牌、式神与牌手查看同一只读详情，不接受对局操作。
- 测试：offscreen 下构造对局视图 + 模拟 apply 流程冒烟（用 tests/factories.py 既有 fixture 思路）。

### Step 4 — 联机模式（online.py）
- 连接页：服务器地址输入（复用 `normalize_server_url` + `probe_connection` 先检后入）与玩家名；预检或 WebSocket 连接失败经应用内警告弹窗提示，不提前校验卡组。
- 大厅：进入后再选择标准卡组，建房或首次加房前校验，令牌重连除外；建房（含自定义 6 位房码、模式/环境选择）/ 加房；lobby 状态渲染（双方准备状态、15s 自动准备倒计时、房主环境修改）；ready/leave 按钮。退出对局按钮仅实际对局页显示。
- 对局：复用 battle.py 对局视图，差异仅在 cmd 走 WebSocket 发送、场况从 state 推送渲染、回合倒计时显示（120s/30s）。
- NetBridge：收包线程 `recv_loop` → `Signal(dict)` 主线程分发；`peer_left/dissolved/game_over/error/notice` 各消息 → 对应 UI 反馈。
- 测试：协议层不重测（tests/test_server.py 已覆盖）；offscreen 下 NetBridge 信号转发单测（假 ws 对象）。

### Step 5 — 本地卡图合成管线（已完成）
- 输入：当前引擎 `CardDef`/`ShikigamiDef` + 项目 `library/<项目>/` 人工标注配置与原图。配置按 id（兼容名称）及合法 8 位 `version_date` 与引擎快照日期精确匹配，无精确版本即回退。
- 合成：引擎提供名称、类型、等级、稀有度、所属式神、派系、身材与描述；配置仅补充 artwork、portrait、layout、faction_style。形态、觉醒、幻境、战斗与协战字段在适配层转换。
- 输出与接入：`card_pixmap` 供构筑、静态/运行时详情、热坐/联机手牌共用；`shikigami_pixmap` 供场上及详情中的基础/觉醒式神；`shikigami_portrait` 供阵容头像使用。`hand_cards_info` 同源提供中文数值段与结构化 `render`（战斗、形态、觉醒等），实时数值直接进入卡面负载和缓存键；费用、增强计数、关键字与使用条件仍由 GUI 独立显示。
- 缓存：静态卡面默认写入 `~/.bwpro/cardart/<sha256>.png`，键含规范化负载、合并后的实际 layout、配置内容 SHA-256、原图 `mtime_ns`/size 与渲染资源内容摘要；大卡缓存键与 manifest 不依赖 BWPDIY 版本号，版本号或 WebGUI 变化不触发失效，渲染 Python 源码与受跟踪 assets 的内容变化仍会使对应缓存失效。含实时 `display` 的变体仅用 256 项内存 LRU，不逐值写盘。layout 元素最多 64 个，尺寸字段最大 512px。
- 启动预热：GUI 线程以 `QTimer` 每次消费 `prewarm_iter` 的一个定义，不跨线程创建或使用 `QPixmap`；状态栏显示“卡图后台同步 current/total”，首屏无模态遮罩且菜单可切换。重复启动不新建并发任务，后台活跃时手动重建只提示“后台预热进行中”，关闭窗口停止并清理任务。`manifest.json` 记录配置/图片 SHA-256、渲染资源摘要、最近合成时间及成功/失败统计；失败项不进入成功清单，下次启动自动重试，完成后刷新设置页。后台空闲时设置页仍支持确认后清缓存并同步全量重建，该手动重建保留全屏遮罩与真实耗时提示。
- 回退：缺配置、日期不匹配或缺插画时仍合成完整卡框与文本，插画区域透明；只有渲染器自身失败才回退文字卡，阵容头像回退菱形。所有操作控件与运行时详情保留。

### Step 6 — 收尾
- README 功能板块补 GUI 客户端条目；用户级与项目级 AGENTS.md 进度段更新。
- 全量 pytest + db.validate 主上下文亲跑；codebase-memory 索引重建；commit & push。

## 执行方式

- Step 2/3/4 各派一个 coder 子代理顺序执行（共享 client/gui/ 包，并行会撞文件）；Step 1 由主上下文直接做（量小）。
- 每个子代理验收：受影响测试 + offscreen 冒烟全绿；迭代期不跑全量。

## 明确不做（本轮）

- 音效及上述基础位移/用牌之外的复杂动画。
- PyInstaller 打包 exe（功能稳定后再做）。
- 浏览器离线化（Pyodide 路线，已否决）。
