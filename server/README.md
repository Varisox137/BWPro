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

- **HTTPS 映射（推荐）**：穿透服务"网站应用类型"HTTPS 映射
  （外网 `https://<域名>` → 内网 `127.0.0.1:1037`），支持 WebSocket 透传，
  TLS 由映射边缘终止，本机无需证书。客户端输 `https://<域名>`（自动转
  `wss://<域名>/ws`）即可联机。浏览器访问拦截可在穿透服务侧配置，
  与服务端客户端标识软门槛并存互补。
- **HTTP 穿透 / 反代**（cloudflared、nginx、Caddy 等，要求支持 WebSocket 升级）：
  客户端输入 `ws://<域名>/ws`；若对方提供 TLS 终止，则输 `wss://<域名>/ws`。
- 服务端也可直接配置 TLS（`--ssl-certfile/--ssl-keyfile`），此后客户端用
  `wss://<地址>:1037/ws`。
- 注意：纯 TCP 映射（部分穿透服务的 TCP 类型映射）会识别并拦截 HTTP 格式流量，
  WebSocket 握手本质即 HTTP 请求，**无法**经此类映射透传。
- **真实来源 IP**：经穿透/反代时 TCP 对端永远是边缘回连地址（如 127.0.0.1），
  真实 IP 只能由边缘以 `X-Forwarded-For` / `X-Real-IP` 头透传；服务端按
  XFF 首项 → X-Real-IP → 对端地址的顺序取值并在连接时打印日志。该值由边缘
  写入、可被伪造，仅作参考，不作访问控制依据；若边缘不透传则无从获取。

## 安全性（基本保障）

- **信息隐藏**：下发状态按视角脱敏——对手的手牌/牌库内容替换为占位卡
  （仅张数公开），修改客户端也无法窥探；墓地与各类计数器按规则为公开信息。
- **身份与权限**：无登录态；入座下发随机 `player_token`（重连凭证），指令中的
  `player` 字段由服务端按座位强制改写，回合内操作仅当前行动方可发。
- **传输加密**：支持 wss（服务端直接配 TLS 证书，或经穿透/反代终止 TLS）。
- **客户端软门槛**：握手一律放行（穿透/反代等中间代理会改写 HTTP 头，不看
  `User-Agent`）；`create`/`join` 消息必须带 `client` 字段且以 `BWPro-CLI`
  开头，否则拒绝并断联，超时 5 秒未完成合法入房的连接也会被关闭
  （`--no-require-ua` 关闭）。仅过滤浏览器/扫描器等噪声，标识可伪造，
  不构成访问控制。
- **debug 对局门控**：客户端创建 debug 对局需服务端 `--allow-debug-rooms`
  （默认拒绝；公网部署勿开）。debug 指令可任意改对局状态，仅本机调试使用。
- **HTTP 探针面**：非 WebSocket 的 HTTP 请求（含对 `/ws` 的普通 GET）一律
  403 空体，不用框架默认 404；uvicorn 启动关闭 `server` 响应头，不暴露
  应用结构与框架指纹。
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
- 无登录态：创建房间可自建 6 位字母数字房间代码（缺省随机分配）；凭代码加入；
  入座时下发 `player_token`，断线后凭 房间代码+token 重连（对局与计时器保留，
  双方断线才回收房间）。
- **准备阶段**：双方都位后不直接开局、不计时（IDLE）——任一方 `ready` 后对
  未准备方计 15s 自动准备（COUNTDOWN），双方准备进入 3s 开始倒计时（STARTING）
  后开局；已准备方可再次 `ready` 取消准备回到无计时状态（开始倒计时中不可取消）；
  期间可 `leave` 主动离开（断线视同离开，含开始倒计时中），座位释放、对手退回
  等人状态。准备阶段断线重连补发当前 lobby 状态。
- **对局模式**：创建房间可带 `mode`（`standard`/`free`，缺省 `standard`）。
  标准模式固定使用最新平衡性数据（env_date 强制为 null、不可更改）；自由模式
  创建时可带 `env_date`（平衡性版本日期，见 `db/versioning.py`），该房间全部
  数据按不晚于该日期的最晚版本解析、该日期未发布的卡牌/式神不可用；自由模式
  双方均未准备时房主可发 `env` 消息更改（更改后重新校验双方已入座卡组，
  任一不可用则拒绝）；入座卡组校验按房间环境进行，不满足时报错并注明环境日期。
- 服务端日志：连接来源、建房/加入/准备/离开/开局/终局/房间回收均打印到控制台。
- 座位（seat）与 `players` 下标的映射在开局随机先手时确定；指令中的 `player`
  字段由服务端按座位强制改写；回合内操作（play_card/assault/upgrade/end_turn）
  只能由当前行动方发出。

## 通信协议（WebSocket JSON）

客户端 → 服务端：

```json
{ "type": "create", "name": "甲", "deck_code": "<卡组码>", "debug": false, "room_id": "Ab12cd", "mode": "standard", "env_date": null }
{ "type": "join", "room_id": "ABC123", "name": "乙", "deck_code": "<卡组码>", "token": null }
{ "type": "ready" }
{ "type": "leave" }
{ "type": "env", "date": 20250701 }
{ "type": "cmd", "cmd": { "op": "end_turn" } }
```

`deck_code` 为必填（入座时按房间环境校验，非法/缺失报错，无默认卡组）；仅凭 token 重连时可为 null。
`create.room_id` 可缺省（随机分配）；指定时须为 6 位大小写字母/数字且未被占用。
`create.mode` 可缺省（`standard`）；标准模式忽略 `env_date`（固定最新数据），自由模式
`create.env_date` 可缺省（最新数据）；`env` 仅自由模式房主在双方均未准备时可用（date 缺省 = 最新）。
`ready`/`leave` 仅准备阶段（双方都位后、开局前）有效；`ready` 为准备/取消准备切换。

服务端 → 客户端：

```json
{ "type": "joined", "room_id": "...", "token": "...", "seat": 0, "debug": false }
{ "type": "lobby", "ready": ["甲"], "deadline": 1735689600.0, "mode": "standard", "env_date": null }
{ "type": "starting", "deadline": 1735689600.0 }
{ "type": "peer_left", "name": "乙" }
{ "type": "left" }
{ "type": "start", "player_index": 0, "opponent": "乙", "you_first": true, "mode": "standard", "env_date": null }
{ "type": "state", "payload": { "..." : "GameState JSON" }, "log": ["..."],
  "timer": { "kind": "turn", "deadline": 1735689600.0 },
  "settle": ["..."], "timeline": [{ "k": "s", "m": "..." }] }
{ "type": "error", "reason": "..." }
{ "type": "notice", "text": "..." }
{ "type": "game_over", "winner": 0, "reason": "player_defeated" }
```

`lobby.deadline` 仅一方已准备时非空（未准备方的自动准备截止）；`ready` 为空 =
双方未准备、不计时。`lobby`/`start` 始终携带 `mode`；`env_date` 为 null 时字段省略（最新数据）。

心跳使用 WS 协议层 ping/pong（uvicorn `ws_ping_interval=10`，`ws_ping_timeout=5`）。

## 限时（权威在服务端）

| 阶段 | 默认 | 超时行为 |
|------|------|----------|
| 准备阶段 | 无人准备不计时；一方准备后 15s | 未准备方自动准备 → 双方准备后 3s 开始倒计时开局（期间 `ready` 准备/取消，`leave` 离开） |
| 起始手牌调度 | 30s（双方并行，自阶段开始共用截止时刻） | 超时将所有未完成调度的玩家自动 `ready` |
| 回合（含升级阶段） | 120s | 结算中交互选择（检视选牌）挂起时先随机作答到底；升级阶段再由系统在可升级式神中随机升级，最后立即 `end_turn` |

- `settle`/`timeline` 为结算明细增量：timeline 是结算（k="s"）与叙事日志（k="l"）
  按真实发生顺序的合流，客户端结算播放以它为准（settle/log 字段保留兼容）；
  断线重连 resync 只发全量 payload+log（含 pending_choice 与当前 timer），
  结算明细历史不补。
- 每 Room 一个 `asyncio` 计时器；计时对象（调度阶段 / 回合号）变化时重启，
  同一计时对象内的操作不重置计时（调度阶段一方 ready 不影响另一方倒计时）。
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
