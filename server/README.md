# BWPro 服务端架构设计（Phase 2）

> 本文档记录 Phase 2 联机服务端的初步架构设想与待确认问题。实现前请先与维护者讨论并确认其中的选择。

## 目标

把本地热座 CLI 扩展为基于 FastAPI + WebSocket 的双人联机对战服务端：

- 服务端持有 authoritative 的 `core.engine.Game` 实例。
- 客户端只提交 `cmd dict`（与 CLI 同一协议），服务端校验、执行并广播新状态。
- 支持断线重连、回合超时强制结束、死循环防护。

## 组件划分

```
server/
  main.py          # FastAPI 应用与 WebSocket endpoint
  room.py          # Room：封装 Game + 玩家连接 + 计时器
  manager.py       # RoomManager：创建/加入/查询/销毁房间
  connection.py    # WebSocket 连接包装、心跳、重连校验
  timer.py         # 回合 / 调度阶段计时器
  logging.py       # 服务端日志、能力编号分配
  protocol.py      # ServerMsg / ClientMsg 信封定义
```

### Room

- 持有 `Game` 实例与两名玩家的 `Connection`。
- 负责启动/停止回合计时器。
- 在 `Game.apply(cmd)` 执行后，把完整 `GameState` JSON 广播给所有已连接玩家。
- 断线玩家重连时，下发当前 `GameState` 与最近日志。

### Connection

- 包装 `WebSocket`。
- 维护 `player_token`（UUID）、`player_index`、`connected`、`last_pong`。
- 处理心跳 `ping/pong`。

### RoomManager

- 内存中管理所有房间（Phase 2 先不做持久化数据库）。
- 创建房间时返回 `room_id` 与两名玩家的 `player_token`。
- 支持通过 `room_id` 查询房间状态（观战/调试用）。

## 通信协议

基于 WebSocket 的 JSON 消息。

### 客户端 → 服务端

```json
{ "type": "join", "token": "<player_token>" }
{ "type": "cmd", "cmd": { "op": "end_turn" } }
{ "type": "pong" }
```

### 服务端 → 客户端

```json
{ "type": "state", "payload": { /* GameState JSON */ } }
{ "type": "error", "validator": "server", "reason": "..." }
{ "type": "log", "payload": [ "..." ] }
{ "type": "game_over", "winner": 0, "reason": "player_defeated" }
{ "type": "ping" }
```

## 断线重连

- 玩家加入房间时分配 `player_token`，服务端持久保存。
- WebSocket 断开时只标记 `connected=False`，**不销毁房间和游戏**。
- 心跳：服务端每 15s 发送 `ping`，客户端 5s 内回复 `pong`，否则视为断线。
- 重连：客户端重新连接并发送 `token`，服务端校验后下发当前 `GameState`。
- 若当前轮到断线玩家，回合计时器继续运行；超时后服务端自动结束其回合。

## 超时强制结束回合

| 阶段 | 超时时间 | 默认行为 |
|------|----------|----------|
| 调度阶段 | 30s | 超时视为 `ready`，直接进入对战 |
| 单个回合 | 120s（可配置） | 服务端自动 `apply({"op": "end_turn"})` |

- 每个 `Room` 持有一个 `asyncio.Task` 计时器，回合开始/切换时重启。
- 客户端预校验可减少无效请求，但**最终计时权威在服务端**。

## 死循环避免

### 引擎层（已实现）

- `MAX_QUEUE_ITERATIONS = 1000`：单次效果队列最多处理 1000 个效果块。
- `state.turn >= 256`：长对局强制平局。

### 服务端/协议层（待实现）

- **命令频率限制**：单连接每秒最多 N 条 cmd（建议 10/s）。
- **WebSocket 消息大小限制**：单条消息最大 1MB。
- **最大嵌套深度**：为 `_resolve_block` 增加递归深度计数，超过阈值（建议 32）视为异常。
- **异常对局终止**：若引擎抛出死循环异常，记录日志并广播 `game_over`（原因 `engine_error`），解散房间。

## 待确认问题

在动手实现前，希望维护者确认以下几点：

1. **回合超时时间**：规则文档写 120s，`memory/bwpro-server-logging.md` 曾提过 100s。是否采用 **120s 作为默认值**，并通过 `GameConfig.turn_timeout` 覆盖？
2. **断线后的回合处理**：若当前行动玩家断线，是等他重连继续（计时仍走），还是直接由服务端托管/超时结束？
3. **重连日志下发**：重连时只发当前 `GameState`，还是顺带发完整事件日志供客户端回放？
4. **引擎异常结果**：发生死循环/异常时，是判平局、双方失败，还是直接终止对局并记录？
5. **房间匹配方式**：Phase 2 先做“创建房间 + 邀请码/token”模式，还是直接做自动匹配？
6. **观战/回放**：服务端日志是否同时支持赛后回放文件，还是只保留文本日志？

## 实现顺序建议

1. 搭建 FastAPI + WebSocket 基础连接。
2. 实现 Room + RoomManager + 简单 join/heartbeat。
3. 把 CLI 热座逻辑拆出可复用的 `client/net.py`，实现联机 CLI。
4. 加入回合/mulligan 计时器与超时结束。
5. 加入断线重连与状态恢复。
6. 加入服务端日志与能力编号。
7. 加入频率限制、消息大小限制、嵌套深度防护。
