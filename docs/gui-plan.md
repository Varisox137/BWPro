# 桌面 GUI 客户端实施计划（PySide6）

> 状态：**Step 1-4 已完成**（骨架/构筑/热坐/联机，2026-10 落地，见各 commit）。
> Step 5 卡图合成管线待维护者给出初步思路后纳入
> （diy/构筑/对局都会需要；理想功能：给定卡牌本身的各参数、卡图原画、
> 描述文本，输出合成的卡牌图片）。动画/音效暂不排优先实现。
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
- **卡图**：初版无美术资产（卡牌=带名称/费用/身材/效果文本的样式化控件；点击看详情弹窗）；待维护者给出卡图合成思路后，增加合成管线并替换卡面控件渲染。

## 复用清单（勘察已核实，禁止重写）

- 构筑：`deckbuilder.available_shikigami/buildable_cards`、`db/deckstore.py`（load/save/check_deck/entry_code）、`db/deck.py validate_deck/rules_summary/STANDARD_RULES`、`db/deckcode.py`、`db/envs.py`（环境解析）。
- 对局数据：`cli.hand_cards_info(game, pi)`（联机 hand_info 同源）、`cli.hand_sorted/_stats_label/format_seat_line`、`Game.usage_options`、`Game.reinforce_sub_option_error`、`targets.spec_pool_refs(…, targeted=True)`、`cli.parse_ref/ref_code`。
- 联机协议：`server/protocol.py` 消息构造器与类型表、`net.normalize_server_url/probe_connection/_open_ws`、cmd dict 组装语义（play_card/assault/upgrade/end_turn/mulligan/ready/choose + choice/target/target2/play_method）。
- 决策点：`state.pending_choice`（7 种 kind，作答 uid/choice）、`state.phase`（mulligan/upgrade/battle）。

## 文件布局（新增包，不动现有模块）

```
client/gui/__init__.py        # 包说明
client/gui/__main__.py        # python -m client.gui 入口：QApplication + 主窗口
client/gui/app.py             # MainWindow + 视图栈（QStackedWidget）+ 全局样式
client/gui/builder.py         # 卡组构筑视图
client/gui/battle.py          # 对局视图（热坐/联机共用）
client/gui/widgets.py         # 卡牌控件/式神通槽/详情弹窗/目标选择模式
client/gui/online.py          # 联机：大厅视图 + NetBridge（收包线程→Qt 信号）
client/gui/cardart.py         # （待补）卡图合成管线——等维护者思路
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
- 场况区：双方牌手行（生命/鬼火/出击加成/幻境队列含耐久）+ 各 4 式神通槽（座次色边框——黄/青/紫/红淡色，同 CLI 配色语义；名字/等级/力量/生命/护甲破甲/能量/倒计时/形态/关键字徽标/眩晕气绝状态）+ 战斗区标识。点击式神/牌手/卡牌 → 详情弹窗（完整文本）。
- 手牌区：横排卡牌控件，含 `hand_cards_info` 的数值段（增强后身材/费用修正/使用方式合法性徽标）。
- 操作流：
  - 点击手牌 → 使用方式弹窗（usage_options 列表，含协战子选项与爆能等）→ 如需目标进入"目标选择模式"（合法目标槽位高亮，点击选定；target2 两段同理）→ 组装 cmd dict → `game.apply`。
  - 出击/升级/结束回合按钮区；升级阶段升级按钮按可升级式神启用。
  - 调度阶段：手牌旁加调度按钮 + 确认（ready），双方先后手与座次展示同 CLI。
  - pending_choice：按 7 种 kind 弹对应选择对话框（选项列表/两级 card_name/灵咒选择等），作答 `{"op":"choose", ...}`。
- 结算展示：右侧面板按 QTimer 0.3s/条播 `state.timeline`/log 增量；播完才开放下一步操作输入（热坐串行，天然满足）。
- 终局：胜负横幅 → 回主菜单。
- 测试：offscreen 下构造对局视图 + 模拟 apply 流程冒烟（用 tests/factories.py 既有 fixture 思路）。

### Step 4 — 联机模式（online.py）
- 连接页：服务器地址输入（复用 `normalize_server_url` + `probe_connection` 先检后入，失败原地重输——CLI 同款行为）、玩家名、卡组选择（复用组件）。
- 大厅：建房（含自定义 6 位房码、模式/环境选择）/ 加房；lobby 状态渲染（双方准备状态、15s 自动准备倒计时、房主环境修改）；ready/leave 按钮。
- 对局：复用 battle.py 对局视图，差异仅在 cmd 走 WebSocket 发送、场况从 state 推送渲染、回合倒计时显示（120s/30s）。
- NetBridge：收包线程 `recv_loop` → `Signal(dict)` 主线程分发；`peer_left/dissolved/game_over/error/notice` 各消息 → 对应 UI 反馈。
- 测试：协议层不重测（tests/test_server.py 已覆盖）；offscreen 下 NetBridge 信号转发单测（假 ws 对象）。

### Step 5 — 卡图合成管线（cardart.py，待维护者思路后细化）
- 输入：卡牌参数（名称/类型/等级/身材/稀有度/关键字/描述文本）+ 卡图原画。
- 输出：合成卡牌图片；供 diy/构筑/对局三处卡面渲染共用。
- 细节待维护者给出思路后补充。

### Step 6 — 收尾
- README 功能板块补 GUI 客户端条目；用户级与项目级 AGENTS.md 进度段更新。
- 全量 pytest + db.validate 主上下文亲跑；codebase-memory 索引重建；commit & push。

## 执行方式

- Step 2/3/4 各派一个 coder 子代理顺序执行（共享 client/gui/ 包，并行会撞文件）；Step 1 由主上下文直接做（量小）。
- 每个子代理验收：受影响测试 + offscreen 冒烟全绿；迭代期不跑全量。

## 明确不做（本轮）

- 动画、音效。
- 卡图合成管线的具体实现（等维护者思路，见头部状态条）。
- 服务端 webgui（/gui 页面）保留现状不动，与桌面 GUI 并存。
- PyInstaller 打包 exe（功能稳定后再做）。
- 浏览器离线化（Pyodide 路线，已否决）。
