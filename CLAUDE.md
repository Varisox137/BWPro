# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

BWPro 是一个受《阴阳师百闻牌》启发的数字化卡牌对战游戏。长期目标：双人联机对战服务器、客户端、卡牌数据库、自定义卡牌编辑器。当前：核心规则引擎 + 卡牌数据库 + CLI 热座对战 + FastAPI/WebSocket 联机对战（server/ + client/net.py）。

**待确认规则问题统一记录在 `questions.md`（每轮重编号）；已确认规则细节全集在 `docs/rules.md`；代码/数据库命名以 `docs/terminology.md` 为准；维护者的想法与答案在 `thoughts.txt`。**

## 常用命令

本机装有 rtk（命令输出压缩代理）：跑 shell 命令时优先用 `rtk` 前缀省 token，
如 `rtk git status`、`rtk grep <pat>`、`rtk test <cmd>`、`rtk diff`、`rtk find`、`rtk ls`。

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
`server/` 为 authoritative 联机服务端（FastAPI + WebSocket，见 server/README.md），
`client/` 为 CLI 客户端（cli.py 热座 + net.py 联机；Phase 5 换图形），
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
- 战斗流程阶段化（`_battle_flow`：战斗准备前/准备/攻击时/先攻/交战/战斗后）；伤害走全量时点批次管线（`_run_damage_queue`：伤害开始时→贯通修正→护甲计算前（屏障）→护甲计算→护甲计算后→扣减生命前→合并→扣减生命（不屈）→伤害后），并行伤害/贯通溢出/伤害合并同队列；伤害值 ≤0 时终止结算（不扣血、不触发受伤后时机）
- 关键字持久性三类（均为可重复多重集）：一次性 `one_shot_keywords`（触发后移除：迅捷/不屈/屏障）、持续性 `keywords`（触发后不移除：远程/贯通/连击/穿刺/先攻）、永久 `perm_keywords`（气绝不清除=复活自动重获）；战斗牌/形态牌 keywords（fast/trigger 除外）授予式神，终止点/离场按实例移除不误删原有同名；战斗伤害免疫为带作用域的 `immunities` 条目（`battle_immunity` 动作），仅免疫 combat/counter 伤害
- 牌手气绝 → "待结束"：已入队的触发能力不再执行、此后不再触发，气绝牌手不再受伤/治疗，当前事件结算完游戏结束（`_set_pending_end`；牌库抽空判负非气绝）
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
- 移除己方所有角色护甲（破甲/战力/乏力随对应机制引入）→ 气绝己方式神从左到右倒计时 -1（归零复活）→ 鬼火重置为 0 再获得（先手第 1 回合 1 火）→ 战斗区**非召唤物**式神登记延时移回（召唤物驻留）→ on_turn_start 触发（延时执行）→ 形态倒计时 -1（归零重置并触发；灵咒倒计时预留）→ 重置出击次数 →（执行延时移回）→（执行延时效果）→ 抽 1 → 升级机会
- 升级机会：每个己方回合 1 次（含第 1 回合）；先手第 7 / 后手第 3 个己方回合各 +1（当回合共 2 次；系统与效果升级均可触发"升级后"能力，效果升级不一定限最低级）
- 牌库为空执行抽牌立即落败（可能有效改变判定）

**行动**
- 出击：耗 1 鬼火 + 每回合玩家唯一出击次数（常规为 1，己方回合开始时重置；进入敌方回合不重置/不消耗剩余次数）+ 出击增减益（鼓舞/压制，Phase 3）；出击后驻留战斗区，换攻退回
- 移动：不属于玩家主动操作，由卡牌/能力产生的效果实现；移动入战斗区无限制、不耗资源（移动事件流程待 Phase 2/3 落地）
- 升级（lowest 规则）：玩家主动操作；只能升未满级且等级同为己方最低的式神；部分卡牌可打破限制
- 0 级式神未在场：能力不触发（个别能力 `trigger_when_not_in_play` 例外，书翁/三尾狐类）、不能行动/被指定、不被治疗增益、不能复活（除特殊说明）
- 瞬发：每个半回合双方各自第一张瞬发卡免费（仅免鬼火，其余条件照常；可改"前 x 张"）；双方回合都可瞬发（0 火可响应瞬发）
- 响应 = 敌方回合满足条件必发，其余要求与 cost 照常；气绝可用性看卡牌"气绝时可用"标记（与是否响应无关）；非回合方无任何带选择的操作

**增强与卡牌修饰（设计已定，待实现）**
- "增强"不实现统一机制：卡面话术 → 卡牌触发器（triggers，全库注册的游离触发块）+ 实时监测（monitors，谓词+修饰，读取/打出装配时求值）；写入三目标 hand/persistent/turn；即时装配，效果块共享不可变。完整设计见 `docs/enhance-design.md`

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
- 真实卡牌数据按机制落地批次录入 `db/cards`、`db/shikigami` 的 YAML（数据源：thoughts.txt 4 式神 32 卡；机制未落地的字段不录入）；测试用 `tests/factories.py` 程序内构造 / `db/dummy.py` 空白占位

## Roadmap

1. **Phase 1 ✅→进行中** 核心规则与数据模型（引擎 + db + CLI 热座；规则按 thoughts.txt 持续校准）
   - 已落地：战斗关键字（连击/先攻/贯通/穿刺/远程/不屈/迅捷/屏障）+ 全量伤害时点批次管线 + 关键字三类持久性/作用域免疫；攻击后到期强化（attack_buffs/keep_attack_buffs）+ 法术觉醒替换（awakened/abilities/keep_shield）；增强装配管线（卡牌触发器 triggers、打出装配 _materialize、enhance 数值、卡牌光环 card_auras、战斗绑定临时触发 temp_grants）+ 白狼/妖刀姬基础能力；倒计时系统（锚点版：形态倒计时结附/回合开始 -1/归零重置并触发/离场移除）+ 形态能力块 + 投射/鼓舞/直接消灭/随机生成（generate）+ 一目连基础能力与全 8 卡、杀念；随机分配伤害（distribute_damage：逐 1 点插入结算、气绝延后、标记气绝目标不再可选）；响应插入使用（战斗牌改为移入战斗区/形态立即结附/choose 自动选事件被攻击者/同时机限一张）+ 延迟触发（delayed/delay_grant"会"）+ 伤害上限（cap_damage"森罗之阵"）+ 激怒与尘缚之阵战斗区锁定（enraged/combat_lock）+ 进场时形态效果与动态数值（shield_of/power_of：尘刀快照/古尘之壁/援护）；YAML 4 式神 32 卡全录
   - 后续批次：32 卡全录 ✅ → CLI 修饰状态显示 ✅（座次配色/修饰状态/关键字中文化；Phase 1 收尾）
2. **Phase 2 ✅（初版）** 联机服务端：FastAPI + WebSocket、房间创建/按 id 加入、随机先手与座位映射、断线重连（token）、调度 30s/回合 120s 计时（升级阶段超时随机升级）、debug 对局与服务端控制台（详见 server/README.md；回放/匹配/限流待后续）
3. **Phase 3** 进阶机制：形态/觉醒/战斗牌、持续效果与光环、出击增减益、爆能/赐能/起源/连引/连锁/戏法
4. **Phase 4** 自定义卡牌：DSL 编译器、校验、平衡工具（契约见 diy/README.md）
5. **Phase 5** 图形客户端
