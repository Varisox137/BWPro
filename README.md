# BWPro

受《阴阳师百闻牌》启发的数字化卡牌对战游戏。长期目标为双人联机对战（服务端 + 图形客户端）；当前处于 **Phase 1：核心规则引擎 + 初期测试卡牌 + CLI 热座对战**。

## 快速开始

```bash
# 安装依赖
uv sync

# 本地热座对战（Phase 1）
uv run python -m client.cli

# 校验卡牌数据库
uv run python -m db.validate

# 运行全部测试
uv run pytest -q tests/
```

## 项目结构

- `core/` — 共享规则层：状态模型、引擎、动作原语、事件、目标解析、对局组装、调试指令。
- `db/` — 卡牌数据库、数据 schema、组卡校验、`db/test_data.py` 初期测试数据（4 式神 32 卡）。
- `client/` — CLI 热座客户端（Phase 1），与未来网络客户端共用同一 `cmd dict` 协议。
- `server/` — authoritative 服务端入口（Phase 2 实现中）。
- `diy/` — 自定义卡牌 DSL 与平衡工具（Phase 4）。
- `docs/` — 已确认规则细节、术语表。
- `tests/` — 引擎、机制、调试指令测试。

## Phase 1 已实现

- 对局状态模型（`GameState`、`PlayerState`、`ShikigamiState`），纯数据可序列化。
- 规则引擎管线：指令校验 → 动作 → 事件 → 触发队列 → 效果块结算。
- 核心操作：抽牌、伤害、治疗、护甲、召唤、形态结附/消灭、式神升级、出击、战斗牌完整战斗流程。
- 初期测试数据：`db/test_data.py` 含 4 式神（白狼、兵俑、妖刀姬、一目连）共 32 张卡。
- Phase 1 卡效：
  - 战斗牌 = 所属式神移入战斗区，获得战力/护甲，按完整战斗事件流程结算（战斗前/后、反击→攻击）。
  - 形态牌 = 按卡牌数值覆盖基础身材；使用时不进入墓地，形态离场时才入墓。
  - 觉醒牌 = 永久力量/生命修正，并标记 `subtype=awaken`。
  - `cost=0` 表示【不消耗鬼火】；`fast` 表示【瞬发】。
- 气绝/复活、长对局平局、游戏结束阶段（待结束 → 正式结束）。
- 式神座位与进场顺序、先手/后手经济、调度阶段。
- 调试指令系统（`core/debug.py`）。
- CLI 热座对战客户端。

## 主要协议

玩家指令为 `cmd dict`，CLI 与未来的网络层共用：

```json
{ "op": "play_card", "uid": 1, "target": { "player": 1, "shikigami": 0 } }
{ "op": "assault", "index": 0 }
{ "op": "upgrade", "index": 2 }
{ "op": "end_turn" }
```

- 对局阶段：`mulligan` → `upgrade`（每回合开始强制升级）→ `battle`（主要阶段）。
- CLI 中所有序号显示与输入为 1-based，协议层仍保持 0-based index。

详见 `CLAUDE.md` 与 `docs/rules.md`。

## Roadmap

1. **Phase 1** ✅ 核心规则引擎 + 数据模型 + CLI 热座
2. **Phase 2** 🚧 联机服务端（FastAPI/WebSocket）、房间匹配、断线重连、服务端日志
3. **Phase 3** 进阶机制：形态/觉醒/战斗牌、持续效果、鼓舞/压制、爆能/连引等
4. **Phase 4** 自定义卡牌 DSL 编译器
5. **Phase 5** 图形客户端

## 设计文档

- `docs/rules.md` — 已确认规则细节全集
- `docs/terminology.md` — 术语与代码命名对照
- `docs/enhance-design.md` — "增强"机制设计结论（触发器/监测/即时装配；下一阶段实施依据）
- `questions.md` — 待确认问题与 Phase 3+ 预留机制
- `thoughts.txt` — 维护者想法与规则答复
