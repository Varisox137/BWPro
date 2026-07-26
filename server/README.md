# BWPro 服务端（联机对战）

基于 FastAPI + WebSocket 的双人联机对战服务端，已实现。

## 运行

```bash
uv run python -m server.main [--host 0.0.0.0] [--port 8000] \
    [--turn-timeout 120] [--mulligan-timeout 30] [--debug-console]
```

客户端：`uv run python -m client.net`（或主菜单 [3] 联机对战），
`--debug` 创建 debug 对局（房间内允许 debug 指令）。

## 架构

```
server/
  main.py          # FastAPI 应用与 /ws endpoint、启动参数、--debug-console stdin 线程
  room.py          # Room：封装 Game + 玩家连接 + 调度/回合计时器
  manager.py       # RoomManager：创建/加入/查询/回收房间（内存表，无持久化）
  protocol.py      # 消息信封构造与客户端消息校验
```

- 服务端持有 authoritative 的 `core.engine.Game` 实例；客户端只提交
  `cmd dict`（与热坐 CLI 同一协议），服务端校验、执行并广播完整 `GameState` JSON
  + 新增日志。
- 无登录态：创建房间分配随机 6 位房间 id；凭 id 加入；入座时下发 `player_token`，
  断线后凭 房间id+token 重连（对局与计时器保留，双方断线才回收房间）。
- 座位（seat）与 `players` 下标的映射在开局随机先手时确定；指令中的 `player`
  字段由服务端按座位强制改写；回合内操作（play_card/assault/upgrade/end_turn）
  只能由当前行动方发出。

## 通信协议（WebSocket JSON）

客户端 → 服务端：

```json
{ "type": "create", "name": "甲", "deck_code": null, "debug": false }
{ "type": "join", "room_id": "ABC123", "name": "乙", "deck_code": null, "token": null }
{ "type": "cmd", "cmd": { "op": "end_turn" } }
```

服务端 → 客户端：

```json
{ "type": "joined", "room_id": "...", "token": "...", "seat": 0, "debug": false }
{ "type": "start", "player_index": 0, "opponent": "乙", "you_first": true }
{ "type": "state", "payload": { "..." : "GameState JSON" }, "log": ["..."] }
{ "type": "error", "reason": "..." }
{ "type": "notice", "text": "..." }
{ "type": "game_over", "winner": 0, "reason": "player_defeated" }
```

心跳使用 WS 协议层 ping/pong（uvicorn `ws_ping_interval=10`，`ws_ping_timeout=5`）。

## 限时（权威在服务端）

| 阶段 | 默认 | 超时行为 |
|------|------|----------|
| 起始手牌调度 | 30s/人 | 自动 `ready`，立即结束该玩家调度 |
| 回合（含升级阶段） | 120s | 升级阶段先由系统在可升级式神中随机升级，再立即 `end_turn` |

- 每 Room 一个 `asyncio` 计时器；计时对象（调度中的玩家 / 回合号）变化时重启，
  同一回合内的操作不重置计时。
- 游戏逻辑在事件循环内同步执行，计时器回调只能排在当前 `apply` 返回后运行——
  天然满足"回合超时等结算完后立即结束回合"。

## debug 能力

- **debug 对局**：客户端 `python -m client.net --debug` 创建，房间以
  `GameConfig(enable_debug_commands=True)` 开局，客户端可用 `debug <子命令>`
  （解析复用 client/cli.py）。非 debug 房间引擎层拒绝 debug 指令。
- **服务端控制台**：`--debug-console` 启动后 stdin 接受 `list`（列出房间）与
  `<房间id> <debug 子命令> [参数...]`，直接进入指定对局执行并广播结果。

## 死循环防护

- 引擎层（已实现）：`MAX_QUEUE_ITERATIONS = 1000`；`state.turn >= 256` 强制平局。
- 服务端层：引擎抛非 `IllegalAction` 异常时广播 error + `game_over(engine_error)`
  终止对局。命令频率限制 / 消息大小限制 / 观战回放 / 自动匹配留待后续。
