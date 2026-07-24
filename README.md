# BWPro

受《阴阳师：百闻牌》启发的数字化卡牌对战游戏。长期目标为双人联机对战（服务端 + 图形客户端）；当前处于 **Phase 1：核心规则引擎 + 初期测试卡牌 + CLI 热座对战**。

## 快速开始

```bash
uv sync                              # 安装依赖
uv run python -m client.cli          # 本地热座对战
uv run python -m db.validate         # 校验卡牌数据库
uv run pytest -q tests/              # 运行全部测试
```

## 项目结构

- `core/` — 共享规则层：状态模型、引擎、动作原语、事件、目标解析、对局组装、调试指令
- `db/` — 卡牌数据库、schema、组卡校验、初期测试数据（4 式神 32 卡）
- `client/` — CLI 热座客户端（与未来网络层共用 `cmd dict` 协议）
- `server/` — authoritative 服务端（Phase 2） · `diy/` — 自定义卡牌 DSL（Phase 4）
- `docs/` — 规则与术语文档 · `tests/` — 引擎/机制/调试指令测试

## Phase 1 已实现

- 规则引擎管线：指令校验 → 动作 → 事件 → 触发队列 → 效果块结算；状态纯数据可序列化
- 核心操作：抽牌、伤害、治疗、护甲、召唤、形态结附/消灭、升级、出击、战斗牌完整战斗流程
- 测试数据 4 式神（白狼、兵俑、妖刀姬、一目连）× 8 卡：战斗/形态/觉醒牌、瞬发、0 费
- 气绝/复活、长对局平局、先后手经济、调度阶段、调试指令系统、CLI 热座客户端

## 主要协议

玩家指令为 `cmd dict`，CLI 与未来的网络层共用：

```json
{ "op": "play_card", "uid": 1, "target": { "player": 1, "shikigami": 0 } }
{ "op": "assault", "index": 0 }
{ "op": "upgrade", "index": 2 }
{ "op": "end_turn" }
```

- 对局阶段：`mulligan` → `upgrade`（每回合开始强制升级）→ `battle`（主要阶段）
- CLI 序号显示与输入为 1-based，协议层保持 0-based index

## Roadmap

1. **Phase 1** ✅ 核心规则引擎 + 数据模型 + CLI 热座
2. **Phase 2** 🚧 联机服务端（FastAPI/WebSocket）、房间匹配、断线重连
3. **Phase 3** 进阶机制：形态/觉醒/战斗牌完整效果、持续效果、鼓舞/压制等
4. **Phase 4** 自定义卡牌 DSL 编译器 · **Phase 5** 图形客户端

## 设计文档

- `docs/rules.md` — 已确认规则细节全集 · `docs/terminology.md` — 术语与代码命名对照
- `docs/enhance-design.md` — "增强"机制设计结论（下一阶段实施依据）
- `questions.md` — 待确认问题 · `thoughts.txt` — 维护者想法与规则答复 · `CLAUDE.md` — 架构导览

## 声明

- 本项目为**非盈利**的同人/学习作品，与网易及《阴阳师：百闻牌》官方无关；规则与数值实现**可能与原版存在差异**（以 `docs/rules.md` 为准）。
- 如有侵权内容，请联系删除，即行移除。
- 欢迎合作开发者与 DIY 卡牌内容提供者参与（自定义卡牌见 `diy/README.md`）。
