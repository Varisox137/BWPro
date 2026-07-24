# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

BWPro 是一个受《阴阳师百闻牌》启发的数字化卡牌对战游戏。长期目标：双人联机对战服务器、客户端、卡牌数据库、自定义卡牌编辑器。当前为 Phase 1：核心规则引擎 + 卡牌数据库 + CLI 热座对战。

**待确认规则问题统一记录在 `questions.md`（每轮重编号）；已确认规则细节全集在 `docs/rules.md`；代码/数据库命名以 `docs/terminology.md` 为准；维护者的想法与答案在 `thoughts.txt`。**

## 常用命令

```bash
uv sync                              # 安装/同步依赖
uv run python -m client.cli          # 本地热座对战（真实数据为空时自动用 db/dummy.py 占位数据）
uv run python -m db.validate         # 校验卡牌数据库（加卡后必跑）
uv run pytest -q tests/              # 全部测试
uv run pytest -q tests/test_mechanics.py  # 单文件
uv run pytest -q tests/test_engine.py::test_defeated_and_revive   # 单个测试
```

## 架构

按职责分层：`core/` 为共享规则层（model/engine/actions/events/targets/setup/debug），
`server/` 为 authoritative 服务端（Phase 2），`client/` 为 CLI 热座客户端（Phase 5 换图形），
`db/` 为卡牌数据库与组卡校验，`diy/` 为自定义卡牌（Phase 4），`docs/` 为规则与术语文档，
`tests/` 含测试工厂与各类测试。目录细节见文件树。

### 引擎结算模型（core/engine.py）

单向管线：玩家指令（cmd dict) → 校验 → 动作（Action) → 事件（Event) → 触发器结算 → 新状态。

- **能力的触发与执行分开**：即时时机有临时队列（同时机能力全部触发后依次执行，如"攻击时"）；
  延时时机无队列（触发的能力加入当前效果队列、其结算完后执行，如"造成伤害后"）。
  默认类别登记在 `core/events.py` 的 `EVENT_TIMING`；`EffectBlock.timing`（insert/queue/None）可单卡覆盖
- `EffectBlock.mode`：`interleaved`=步骤之间允许其它效果结算；`atomic`=不允许（保证无"同时"平局）
- 触发顺序：回合方优先 → 式神上阵顺序 → 响应牌按所属式神从左往右（中立响应牌最后）
- 响应牌：同一时机（每次事件生成 emit 即一个时机实例）至多成功结算一张，不同时机可各响应一张；结算时复查条件/鬼火/消耗/使用者，复查失败不占名额（能力则执行时不再检测、触发者气绝仍有效）；响应使用与主动使用生成同样的使用事件（on_card_played）
- 交战伤害按（反击，攻击）并行顺序生成事件，气绝判定同序；伤害值 ≤0 时终止结算（不扣血、不触发受伤后时机）
- 牌手气绝 → "待结束"：已入队的触发能力不再执行、此后不再触发，气绝牌手不再受伤/治疗，当前事件结算完游戏结束（`_declare_loser`；牌库抽空判负非气绝）
- 卡牌效果只能由 `core/actions.py` 注册表中的 op 组合而成；DIY DSL（Phase 4）也只编译到这些原语
- `GameState` 纯数据可序列化（含内嵌 `GameConfig`）；回合计数 = active + turn（合计半回合）+ 各自 turn_count
- `MAX_QUEUE_ITERATIONS`：效果队列死循环保护（DIY 安全网）

### 指令协议（CLI 与未来网络层共用）

`play_card {uid, play_from?=hand, play_method?=<使用方式id>, target?}` / `assault {index}` / `upgrade {index}` / `end_turn {}` / 调度阶段 `mulligan {player, uid}` 与 `ready {player}`

## 已确认设计规则（来自维护者 thoughts.txt，最新版以此为准）

> 本节为纲要；完整规则细节（战斗/伤害/气绝/复活/倒计时增减/卡牌使用事件流程、给与破甲、响应冒泡修正等）见 `docs/rules.md`。

**结算与事件**
- 效果分 insert（立即插入）与 queue（入队延迟）；同卡多段效果间可允许/不允许其它结算（interleaved/atomic）
- 核心事件登记在 `core/events.py`；DIY 事件在 `db/events.yaml` 声明，`{op: emit}` 触发，新增事件不改引擎

**游戏开始阶段**
- 随机决定双方式神顺序（`new_game(shuffle_team=)`，测试可关）与先后手；双方抽 5 + 各 3 次调度（返回牌库随机位置再随机抽 1，可用不满；`phase="mulligan"`，双方 ready 后开战）
- 式神依次入场 → on_game_start（游戏开始能力，0 级也可触发，如书翁额外抽 1）→ 最左升 1 级 → 后手补 5 甲 → 先手抽 1（其首个回合开始阶段不抽牌）

**回合开始阶段（15 步，thoughts.txt 暂定版）**
- 移除己方所有角色护甲/破甲/战力/乏力 → 气绝己方式神从左到右倒计时 -1（归零复活）→ 鬼火重置为 0 再获得（先手第 1 回合 1 火）→ 战斗区**非召唤物**式神登记延时移回（召唤物驻留）→ on_turn_start 触发（延时执行）→ 倒计时预留 → 重置出击次数 →（执行延时移回）→（执行延时效果）→ 抽 1 → 升级机会
- 升级机会：每个己方回合 1 次（含第 1 回合）；先手第 7 / 后手第 4 个己方回合各 +1（当回合共 2 次；系统与效果升级均可触发"升级后"能力，效果升级不一定限最低级）
- 牌库为空执行抽牌立即落败（可能有效改变判定）

**行动**
- 出击：耗 1 鬼火 + 每回合玩家唯一出击次数（常规为 1，己方回合开始时重置；进入敌方回合不重置/不消耗剩余次数）+ 出击增减益（鼓舞/压制，Phase 3）；出击后驻留战斗区，换攻退回
- 移动：不属于玩家主动操作，由卡牌/能力产生的效果实现；移动入战斗区无限制、不耗资源（移动事件流程待 Phase 2/3 落地）
- 升级（lowest 规则）：玩家主动操作；只能升未满级且等级同为己方最低的式神；部分卡牌可打破限制
- 0 级式神未在场：能力不触发（个别能力 `trigger_when_not_in_play` 例外，书翁/三尾狐类）、不能行动/被指定、不被治疗增益、不能复活（除特殊说明）
- 瞬发：每个半回合双方各自第一张瞬发卡免费（仅免鬼火，其余条件照常；可改"前 x 张"）；双方回合都可瞬发（0 火可响应瞬发）
- 响应 = 敌方回合满足条件必发，其余要求与 cost 照常；气绝可用性看卡牌"气绝时可用"标记（与是否响应无关）；非回合方无任何带选择的操作

**数据与构筑**
- id：统一 6 位式神 id（1xxxyy = 1+3 位卡包 cardpack+2 位序号）+ 2 位序号；可构筑卡 01-08、衍生卡从 51 递增、衍生物从 99 递减；中立牌 9999zzzz、无等级；衍生必须有从属式神；**协战牌双从属：id 前六位为两所属中较小者、序号 21 起（shikigami+shikigami2 记录）**；数据 id 叫 `id`，局内对象 id 叫 `uid`
- 实体 entity = 所有在场对象（non-card：牌手、式神、在场幻境）；以此区分实体关键字与卡牌关键字
- 式神分 shikigami/summon；召唤物死亡即离场、不可升级、入场 1 级（暂定）、生成即进入战斗区（挤退原驻留者；不视为离开准备区）、被移动即离场（非气绝）、己方回合开始不退回（驻留战斗区）；keep_buffs 的同名召唤物再召保留永久增减益
- 身材 = 基础值 + 永久修正 + 临时修正；**临时/永久的区分 = 气绝后复活能否保留**（临时修正气绝时清除；光环类 Phase 3）；"战力" combat_power 为一次性战斗伤害增益（与鼓舞机制同在第一个大型卡包实现）；破甲有独立"给与破甲"流程（非负护甲，Phase 3）
- 派系：红莲/紫岩/青岚/苍叶/无相（red/purple/blue/green/white），对局中可被效果改变（构筑规则仅校验时检查）
- 觉醒牌不是主类型，是通用 tag（`tags` 含 awaken，任意主类型可觉醒）；主类型：spell/combat/form + 预留 field（幻境）/reinforce（协战）；稀有度 rarity（R/SR/SSR）预留
- 组卡：4 式神、≤2 派系（不含无相）、同源（origin）不共存、每式神 ≤8 种（号段结构性保证）×2、中立牌与衍生卡禁入；协战牌所属任一式神出战即可编入（占其 8 种名额，同名仍限 2）
- 卡牌区域 zones 可扩展；墓地仅 UI 层隐藏（引擎可查看、保留对象引用）；同名卡靠 uid 区分，实例差异放 mods
- 使用位置（play_from）与使用方式（play_method/PlayMethod，可覆盖 cost/level/card_type/target）保留扩展；多择牌仅保留核心方式、参数可变（PlayMethod.param）；对局中可动态赋予卡牌效果（预留）
- 数据兼容：字段只增不改、未知字段保留、加载即校验
- 真实卡牌数据暂不入库；测试用 `tests/factories.py` 程序内构造 / `db/dummy.py` 空白占位

## Roadmap

1. **Phase 1 ✅→进行中** 核心规则与数据模型（引擎 + db + CLI 热座；规则按 thoughts.txt 持续校准）
2. **Phase 2** 联机服务端：FastAPI/websockets、房间匹配、断线重连、回放、回合计时（100s）
3. **Phase 3** 进阶机制：形态/觉醒/战斗牌、持续效果与光环、出击增减益、爆能/赐能/起源/连引/连锁/戏法
4. **Phase 4** 自定义卡牌：DSL 编译器、校验、平衡工具（契约见 diy/README.md）
5. **Phase 5** 图形客户端
