# 桌面 GUI 客户端实施计划（PySide6）

> 状态：**Step 1-5 已完成**（骨架/构筑/热坐/联机/本地卡图管线，2026-10 落地，见各 commit）。
> 卡图使用项目 `library/` 的人工标注与 BWPDIY render 引擎数据合成，按引擎版本匹配并带内容寻址缓存；未配置或渲染失败时保留文字/菱形回退。动画/音效暂不排优先实现。
> 后续可补：式神录页面（现为占位）、大厅对手卡组名（需服务端 lobby 消息补充）。
>
> 界面布局与外部调研见 `docs/gui-design.md`（bwpemu/BWPDIY 结论 + gui-mock 初稿 7 张）。

## 目标

新增原生桌面 GUI 客户端（入口 `python -m client.gui`），把 CLI 三大功能完整图形化：**卡组构筑（本地 decks.json 全管理）、本地热坐对战、联机对战**。CLI 保留不动，GUI 与 CLI 共享 `core/`+`db/`+`client/` 纯数据层，卡组文件 `~/.bwpro/decks.json` 天然互通。

## 架构决策（已定）

- **库**：PySide6（`uv add pyside6`；LGPL，官方维护）。不用 PyQt5/6（GPL 传染性）。
- **异步模型**：**不引入 qasync**。现有 `client/net.py` 是同步阻塞模型（`websockets.sync` + 守护线程 recv_loop）——联机时收包线程通过 Qt 信号（`Signal`）投递到主线程即可，天然契合。
- **热坐**：`Game` 直接在 GUI 主线程构造与 `apply()`（引擎非线程安全，主线程串行调用即可；结算回放用 `QTimer` 按 0.3s 节奏播 timeline 增量，弃用 `client/settle.py`）。
- **联机**：沿用"服务端权威 + 本地只读 wrapper 渲染"模式（`net.py:91 wrapper()` 先例）；不照搬 `send_cmd` 的 2s 轮询等待，改为发后即返回、等 state 推送刷新。
- **卡图**：BWPro 只调用 `bwpdiy.render`，不启动 exe 或服务；exe 仅用于人工标注。默认只读项目 `library/`（`BWP_DIY_LIBRARY` 可覆盖），BWPDIY 渲染资源根用 `BWP_DIY_ROOT` 覆盖。按 id/名称与引擎版本日期精确选择配置，显示数据由引擎合成；缺配置或失败时回退文字卡/菱形头像。

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
client/gui/battle.py          # 对局视图（热坐/联机共用）
client/gui/widgets.py         # 卡牌控件/详情弹窗/通用中文弹窗按钮
client/gui/online.py          # 联机：大厅视图 + NetBridge（收包线程→Qt 信号）
client/gui/portrait.py        # 项目库式神头像（失败回退菱形占位）
client/gui/cardart.py         # 引擎数据合成、版本匹配、内容寻址缓存与文字回退
tests/test_gui.py             # QT_QPA_PLATFORM=offscreen 冒烟测试
```

## 实施步骤

### Step 1 — 骨架与主菜单（小步可验）
- `uv add pyside6`；`__main__.py` 入口；`app.py`：MainWindow + QStackedWidget，主菜单三按钮（1 卡组构筑 / 2 本地热坐 / 3 联机对战），各视图占位页 + 返回主菜单。
- test_gui.py：offscreen 平台下主窗口构造、菜单导航冒烟。

### Step 2 — 卡组构筑视图（builder.py）
功能对齐 CLI 构筑全部能力：
- 卡组管理列表：加载 `load_decks`；新建/编辑/重命名/删除；标准卡组亮蓝色（Qt 刷子）标记；非法卡组可保存仅标色（与 CLI 同口径）；每次保存后全量重校验并原子写回。
- 选中卡组先展示卡组码（CLI 同款行为）；卡组码导入/导出对话框。
- 编辑流程：式神选择（按版本包二级分组 + 搜索框直输全名，用分组树/列表）→ 单式神 8 卡勾选（本家卡 id 升序 1-8 号、协战牌列最后，同 CLI）→ 同种卡限 2 提示但不强制。
- 卡面显示：名称/类型/等级/身材/效果文本（不显示费用，与 CLI 一致）；点击看完整文本。
- 环境选择下拉（别名+6/8 位日期，复用 envs）。
- 测试：decks.json 读写往返、校验标色逻辑（offscreen 直接调视图方法）。

### Step 3 — 热坐对战视图（battle.py + widgets.py）
- 启动：双方各弹卡组选择对话框（复用 Step 2 的卡组列表组件，只列标准卡组；规则同 CLI `_choose_deck`）→ `new_game(db, p1, p2, seed)` → 进入对局视图。
- 场况区（当前实现）：固定己下敌上，视角切换时复用 8 个式神槽位并重排上下行，不显示顶部座位行或式神座位序号；准备区使用 148×108px 固定槽位向中央聚拢，不再增加中央额外间隔，以 `36, 0, 0, 36` 形成连续椭圆错位。中央 320×224px 椭圆战区按 `combat_index` 将既有槽位移入对应上/下槽格，离战返回准备区，不创建替身或改变目标选择。右侧栏上为敌方牌库、中央为 104px 圆形结束回合按钮、下为己方牌库，右上显示敌方手牌数量；均只显示公开数量，不提供牌库内容查看。牌手、式神、手牌及数量文本使用透明背景，不绘制信息底板。牌手行显示生命/鬼火/出击加成/幻境队列含耐久，式神常态仅保留名称与等级、力量/生命、护甲/破甲和可用的倒计时，座次色边框沿用黄/青/紫/红；完整能量、形态、关键字与其他状态进入详情弹窗。
- 手牌区：横排卡牌控件，含 `hand_cards_info` 的数值段（增强后身材/费用修正/使用方式合法性徽标）；卡牌详情同时显示当前费用/数值/增强/关键字/委托/条件与各使用方式可用性。
- 操作流：
  - 点击手牌 → 使用方式弹窗（usage_options 列表，含协战子选项与爆能等）→ 如需目标进入"目标选择模式"（合法目标槽位高亮，点击选定；target2 两段同理）→ 组装 cmd dict → `game.apply`。
  - 出击/升级/结束回合按钮区；升级阶段升级按钮按可升级式神启用。
  - 调度阶段只显示当前未确认方手牌，手牌旁提供调度按钮与确认（ready）；切换查看方先走热坐交接确认，避免看到另一方私有信息。
  - pending_choice：按支持的 kind 弹对应选择对话框（选项列表/两级 card_name/灵咒选择等），作答 `{"op":"choose", ...}`。
- 结算展示：按 QTimer 0.3s/条播 `state.timeline` 增量；播完才开放下一步操作输入。左侧中部"战斗记录"打开默认隐藏的独立非模态日志窗，复用同一窗口，关闭不影响播放；按查看方过滤私有条目，并在起始调度阶段隐藏对手调度张数。
- 热坐交接：查看方变化时暂停 timeline，清空手牌/目标/选择状态并关闭日志，以不可取消绕过的模态确认窗要求交接设备；确认后重绘新视角并恢复结算。终局不额外插入交接。
- 统一弹窗：`QDialogButtonBox`/`QMessageBox` 按钮统一经 `polish_dialog_buttons` 设置中文与样式；牌手、式神、卡牌、交接等详情/确认采用应用内弹窗。
- 式神运行时详情已包含永久/临时/战斗修正汇总、形态、觉醒、延迟能力与灵咒等；**逐条增益来源账本尚未实现**，不能把汇总修正视为逐来源审计。
- 终局：胜负横幅 → 回主菜单。
- 测试：offscreen 下构造对局视图 + 模拟 apply 流程冒烟（用 tests/factories.py 既有 fixture 思路）。

### Step 4 — 联机模式（online.py）
- 连接页：服务器地址输入（复用 `normalize_server_url` + `probe_connection` 先检后入，失败原地重输——CLI 同款行为）、玩家名、卡组选择（复用组件）。
- 大厅：建房（含自定义 6 位房码、模式/环境选择）/ 加房；lobby 状态渲染（双方准备状态、15s 自动准备倒计时、房主环境修改）；ready/leave 按钮。
- 对局：复用 battle.py 对局视图，差异仅在 cmd 走 WebSocket 发送、场况从 state 推送渲染、回合倒计时显示（120s/30s）。
- NetBridge：收包线程 `recv_loop` → `Signal(dict)` 主线程分发；`peer_left/dissolved/game_over/error/notice` 各消息 → 对应 UI 反馈。
- 测试：协议层不重测（tests/test_server.py 已覆盖）；offscreen 下 NetBridge 信号转发单测（假 ws 对象）。

### Step 5 — 本地卡图合成管线（已完成）
- 输入：当前引擎 `CardDef`/`ShikigamiDef` + 项目 `library/<项目>/` 人工标注配置与原图。配置按 id（兼容名称）及合法 8 位 `version_date` 与引擎快照日期精确匹配，无精确版本即回退。
- 合成：引擎提供名称、类型、等级、稀有度、所属式神、派系、身材与描述；配置仅补充 artwork、portrait、layout、faction_style。形态、觉醒、幻境、战斗与协战字段在适配层转换。
- 输出与接入：`card_pixmap` 供构筑、静态/运行时详情、热坐/联机手牌共用；`shikigami_portrait` 供阵容头像使用。运行时费用、增强、关键字与使用条件仍由 GUI 独立显示。
- 缓存：默认 `~/.bwpro/cardart/<sha256>.png`，键含规范化负载、合并后的实际 layout、配置内容 SHA-256、原图 `mtime_ns`/size、BWPDIY 版本与渲染资源根；另有 256 项内存 LRU。
- 回退：缺配置、日期不匹配、缺图、资源或渲染异常时，全卡保留文字卡，头像回退菱形，所有操作控件与运行时详情保留。只有实际完成配置的条目才显示卡图，不把管线落地等同于全式神有图。

### Step 6 — 收尾
- README 功能板块补 GUI 客户端条目；用户级与项目级 AGENTS.md 进度段更新。
- 全量 pytest + db.validate 主上下文亲跑；codebase-memory 索引重建；commit & push。

## 执行方式

- Step 2/3/4 各派一个 coder 子代理顺序执行（共享 client/gui/ 包，并行会撞文件）；Step 1 由主上下文直接做（量小）。
- 每个子代理验收：受影响测试 + offscreen 冒烟全绿；迭代期不跑全量。

## 明确不做（本轮）

- 动画、音效。
- PyInstaller 打包 exe（功能稳定后再做）。
- 浏览器离线化（Pyodide 路线，已否决）。
