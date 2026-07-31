# BWPro 服务端（联机对战）

基于 FastAPI + WebSocket 的双人联机对战服务端，已实现。

## 运行

```bash
uv run python -m server.main [--host 0.0.0.0] [--port 1037] \
    [--turn-timeout 120] [--mulligan-timeout 30] [--rate-limit 10] \
    [--max-rooms 1000] [--ssl-certfile CER --ssl-keyfile KEY] [--debug-console] \
    [--no-require-ua] [--allow-debug-rooms]
```

客户端：`uv run python -m client.net`（或主菜单 [3] 联机对战），
`--debug` 创建 debug 对局（房间内允许 debug 指令，需服务端 `--allow-debug-rooms`），
服务器地址可用 `BWP_SERVER` 环境变量作默认；地址输入接受 ws://、wss://、
http(s)://（穿透/反代给出的网址）及裸 host[:port]，自动规范化为
ws(s)://.../ws，并在询问玩家名/卡组前先试连，失败则要求重新输入。

## 内网穿透 / 公网联机

可以。服务端以 `--host 0.0.0.0` 监听（默认端口 1037）后：

- **HTTPS 映射（推荐，当前部署方式）**：花生壳"网站应用类型"HTTPS 映射
  （外网 `https://<域名>` → 内网 `127.0.0.1:1037`），支持 WebSocket 透传，
  TLS 由映射边缘终止，本机无需证书。客户端输 `https://<域名>`（自动转
  `wss://<域名>/ws`）即可联机。浏览器访问拦截在花生壳侧配置
  （"禁止浏览器访问"），与服务端 UA 软门槛并存互补。
- **HTTP 穿透 / 反代**（cloudflared、nginx、Caddy 等，要求支持 WebSocket 升级）：
  客户端输入 `ws://<域名>/ws`；若对方提供 TLS 终止，则输 `wss://<域名>/ws`。
- 服务端也可直接配置 TLS（`--ssl-certfile/--ssl-keyfile`），此后客户端用
  `wss://<地址>:1037/ws`。
- 注意：纯 TCP 映射（花生壳 TCP 类型等）会识别并拦截 HTTP 格式流量，
  WebSocket 握手本质即 HTTP 请求，**无法**经此类映射透传。

## 安全性（基本保障）

- **信息隐藏**：下发状态按视角脱敏——对手的手牌/牌库内容替换为占位卡
  （仅张数公开），修改客户端也无法窥探；墓地与各类计数器按规则为公开信息。
- **身份与权限**：无登录态；入座下发随机 `player_token`（重连凭证），指令中的
  `player` 字段由服务端按座位强制改写，回合内操作仅当前行动方可发。
- **传输加密**：支持 wss（服务端直接配 TLS 证书，或经穿透/反代终止 TLS）。
- **客户端软门槛**：握手要求 `User-Agent` 以 `BWPro-CLI` 开头，否则握手阶段
  拒绝（`--no-require-ua` 关闭）。仅过滤浏览器/扫描器等噪声，header 可伪造，
  不构成访问控制。
- **debug 对局门控**：客户端创建 debug 对局需服务端 `--allow-debug-rooms`
  （默认拒绝；公网部署勿开）。debug 指令可任意改对局状态，仅本机调试使用。
- **滥用防护**：每连接每秒最多 10 条消息（`--rate-limit`）；单条 WS 消息最大
  1MB；输入字段长度上限（名字 32 / 房间 id 16 / 令牌 64 / 卡组码 1024）；
  房间总数上限 1000（`--max-rooms`）。
- **传输内容**：房间 id 与 token 经 TLS（wss）时不被窃听；用明文 ws 经公网
  穿透时建议仅在可信网络或套 TLS。

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
{ "type": "create", "name": "甲", "deck_code": "<卡组码>", "debug": false }
{ "type": "join", "room_id": "ABC123", "name": "乙", "deck_code": "<卡组码>", "token": null }
{ "type": "cmd", "cmd": { "op": "end_turn" } }
```

`deck_code` 为必填（入座时校验，非法/缺失报错，无默认卡组）；仅凭 token 重连时可为 null。

服务端 → 客户端：

```json
{ "type": "joined", "room_id": "...", "token": "...", "seat": 0, "debug": false }
{ "type": "start", "player_index": 0, "opponent": "乙", "you_first": true }
{ "type": "state", "payload": { "..." : "GameState JSON" }, "log": ["..."],
  "timer": { "kind": "turn", "deadline": 1735689600.0 },
  "settle": ["..."], "timeline": [{ "k": "s", "m": "..." }] }
{ "type": "error", "reason": "..." }
{ "type": "notice", "text": "..." }
{ "type": "game_over", "winner": 0, "reason": "player_defeated" }
```

心跳使用 WS 协议层 ping/pong（uvicorn `ws_ping_interval=10`，`ws_ping_timeout=5`）。

## 限时（权威在服务端）

| 阶段 | 默认 | 超时行为 |
|------|------|----------|
| 起始手牌调度 | 30s/人 | 自动 `ready`，立即结束该玩家调度 |
| 回合（含升级阶段） | 120s | 结算中交互选择（检视选牌）挂起时先随机作答到底；升级阶段再由系统在可升级式神中随机升级，最后立即 `end_turn` |

- `settle`/`timeline` 为结算明细增量：timeline 是结算（k="s"）与叙事日志（k="l"）
  按真实发生顺序的合流，客户端结算播放以它为准（settle/log 字段保留兼容）；
  断线重连 resync 只发全量 payload+log（含 pending_choice 与当前 timer），
  结算明细历史不补。
- 每 Room 一个 `asyncio` 计时器；计时对象（调度中的玩家 / 回合号）变化时重启，
  同一回合内的操作不重置计时。
- `state` 消息附带当前计时器的 `timer`（`kind`: mulligan/turn，`deadline`: unix
  截止时刻）——仅供客户端状态栏倒计时显示，裁决仍在服务端；无计时对象时省略该字段。
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
  终止对局；频率限制 / 消息大小限制见上文"安全性"。观战回放 / 自动匹配留待后续。
