# BWPro 服务端（联机对战）

基于 FastAPI + WebSocket 的双人联机对战服务端，已实现。

## 运行

```bash
uv run python -m server.main [--host 0.0.0.0] [--port 1037] \
    [--turn-timeout 120] [--mulligan-timeout 30] [--rate-limit 10] \
    [--max-rooms 1000] [--ssl-certfile CER --ssl-keyfile KEY] [--debug-console] \
    [--no-require-ua] [--allow-debug-rooms]
```

## Termux Debian 更新与启动

服务端基础依赖只有 FastAPI、pydantic、PyYAML、uvicorn、websockets，不安装 PySide6、Pillow 或 uvicorn standard 扩展。准备 `git` 和 `uv`（uv 安装见 https://docs.astral.sh/uv/getting-started/installation/ ），使用独立干净克隆：

```bash
git clone https://github.com/Varisox137/BWPro.git
cd BWPro
chmod +x scripts/termux_server.sh
./scripts/termux_server.sh
```

脚本依次检查分支/远端/工作区，自动识别 `origin`（新克隆默认）或 `main` 并执行 `git pull --ff-only <远端> master`，再用
`uv sync --locked --managed-python --python 3.14 --no-dev` 同步环境，最后直接调用 `.venv/bin/python -m server.main` 启动。
服务端使用项目统一日志配置（uvicorn `log_config=None`），兼容经 tee 重定向的 stdout。
存在本地改动时直接中止，不会自动 stash/reset/clean；uv 不存在时也只提示，不自动执行安装脚本。项目版本号或依赖声明变化后，须先执行 `uv lock`，并将 `uv.lock` 与 `pyproject.toml` 一并提交后再运行更新脚本，避免 `uv.lock needs update` 与工作区非干净两类报错。
脚本默认 `UV_LINK_MODE=copy`，避免部分 Termux 文件系统不支持硬链接；可用同名环境变量覆盖。
launcher 日志写入 `logs/bwpro-launcher-<时间>-<PID>.log`。

```bash
BWP_HOST=127.0.0.1 BWP_PORT=1038 ./scripts/termux_server.sh
./scripts/termux_server.sh --turn-timeout 120 --mulligan-timeout 30
# 非默认部署副本：BWP_REPO_DIR=/path/to/BWPro ./scripts/termux_server.sh
```

真实 aarch64 环境首次运行需联网下载 uv-managed CPython 3.14；脚本不会静默降级 Python 版本。

客户端：`uv run python -m client.net`（或主菜单 [3] 联机对战），
`--debug` 创建 debug 对局（房间内允许 debug 指令，需服务端 `--allow-debug-rooms`），
服务器地址可用 `BWP_SERVER` 环境变量作默认；地址输入接受 ws://、wss://、
http(s)://（穿透/反代给出的网址）及裸 host[:port]，自动规范化为
ws(s)://.../ws，并在询问玩家名/卡组前先试连，失败则要求重新输入。

## DIY 房间与内容同步

联机 GUI 的“启用 DIY 内容”默认不选；普通房流程不变。DIY 房在双方准备后进入 `diy_syncing`，完成内容同步和卡组复查后才进入开始倒计时。

- 客户端 → 服务端：`create`/`join` 携带 `diy: true`；同步消息为 `diy_manifest`、`diy_pack`、`diy_sync_done`、`diy_sync_error`。
- 服务端 → 客户端：`diy_sync_request`、`diy_upload_request`、`diy_package`、`diy_sync_state`、`diy_sync_failed`；重连 `joined` 可携带 `diy_required`。
- 按完整包同步 YAML 与 `pack.yaml`，不传输或执行 `mechanisms.py`。哈希基于规范化 YAML，排除 `content_hash` 自身；同包不同哈希、跨包实体 id 冲突或缺少已注册机制均拒绝。
- 服务端只在房间内存保存快照，房间回收即释放；日志不记录完整 YAML。下载端保存到 `~/.bwpro/diy/<包id>/<hash>/`，设置页可仅清理这些下载内容。
- 日期沿用 `versions.history` 与环境解析；默认创建日期只适用于最新环境，历史环境须显式填写合适日期。同步后重新校验双方卡组。
- 限制：每方 32 包，每包 128 个 YAML、单文件 256 KiB、总计 512 KiB。完整设计见 `diy/扩展架构设计.md`。

## 远程日志管理

Termux 服务端启动后，在服务端项目目录读取当前日志提取码：

```bash
# Termux 服务端
cat logs/.log-access-token
```

Windows 开发机使用独立运维端，不需要启动主游戏客户端：

```bash
# Windows 开发机独立运维端
uv run python -m client.log_admin
```

也可直接运行 `python -m client.log_admin`（已安装项目 GUI 依赖的环境）。输入服务器 HTTP(S) 地址和当前提取码后，可刷新日志列表、单击只读预览当前或历史日志，并多选下载日志到本地目录；预览最多显示文件开头 512 KiB，JSON 响应最多 2 MiB，单个下载最多 2 GiB-1，超限会中断并删除本地半成品。裸地址仅 `127.0.0.1`、`localhost`、`::1` 默认 HTTP，其余地址即使带端口也默认 HTTPS；显式 `http://` 仅为受信私网兼容保留，公网禁止使用。

提取码在服务端启动时生成，此后每 30 分钟轮换，轮换后旧码立即失效。新码会以 `[YYYY-MM-DD HH:MM:SS]日志提取码更新：<提取码>` 格式直接显示在交互控制台，但不会写入应用日志或经 launcher 的 `tee` 保存；无交互控制台时只显示提取码文件路径。公网使用运维端必须通过 HTTPS 映射或反向代理（与服务端直接 TLS 配置等效），不得用明文 HTTP 传输提取码和日志。

日志管理鉴权失败限流只按 socket 对端地址分桶。经反向代理后，该地址通常是代理的回连地址，因此多个用户可能共享同一限流桶；这是已确认的取舍，不会信任客户端可伪造的 `X-Forwarded-For` 来拆分鉴权桶。

日志管理接口由服务端自身提供。POSIX 日志目录权限为 0700、应用与 launcher 日志及提取码文件为 0600；Windows 先重置既有 ACL，再移除继承并仅授当前用户完全控制（目录含子项继承）。应用或 launcher 权限设置失败会明确警告并继续；提取码权限失败仍中止当次轮换。Termux 服务端不需要 PySide6 等 GUI 依赖；只有运行独立运维端的桌面环境需要这些依赖。

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

- **信息隐藏**：下发状态按视角脱敏——对手的暗手牌仅保留稳定 `uid` / `hand_seq`
  供客户端区分与排序，`id=0`、`mods={}`，牌库则全部匿名替换；已展示手牌按规则放行
  真实内容，`hand_info` 仅包含己方手牌，私密线索账本 `quest_clues_seen` 仅所属方可见。
  修改客户端也无法窥探未公开卡牌；墓地与各类计数器按规则为公开信息。
- **身份与权限**：无登录态；入座生成 8 位小写十六进制凭证，正式 `start` 仅向本人
  下发对应的 `reconnect_code`。GUI 意外断线后以房码、识别码和 `client_ip` 自动重连，
  服务端要求对局已开始且公网 IP 与入座记录一致；准备/开始倒计时阶段不使用该通道。
  旧 CLI 的房间代码+token 手动重连暂时保留。指令中的 `player` 由服务端按座位强制
  改写；每个 WebSocket 仅允许一次成功 create/join，重连会关闭旧 socket，旧连接不能
  影响新连接。无效重连按房间共享 60 秒滑动窗口限 5 次，成功也不清空失败记录。
  原始 WebSocket 帧日志固定为 INFO，避免 DEBUG 记录凭证和私密手牌；应用日志不记录
  完整凭证。名称拒绝控制字符；畸形指令仅返回普通错误，不终止对局。
- **传输加密**：支持 wss（服务端直接配 TLS 证书，或经穿透/反代终止 TLS）。
- **客户端软门槛**：握手一律放行（穿透/反代等中间代理会改写 HTTP 头，不看
  `User-Agent`）；`create`/`join` 消息必须带 `client` 字段且以 `BWPro-CLI`
  开头，否则拒绝并断联（`--no-require-ua` 关闭）。连续 5 分钟未创建/加入房间的
  连接自动关闭；入房后不再受该时限影响。
  仅过滤浏览器/扫描器等噪声，标识可伪造，
  不构成访问控制。
- **debug 对局门控**：客户端创建 debug 对局需服务端 `--allow-debug-rooms`
  （默认拒绝；公网部署勿开）。debug 指令可任意改对局状态，仅本机调试使用。
- **HTTP 探针面**：非 WebSocket 的 HTTP 请求（含对 `/ws` 的普通 GET）一律
  403 空体，不用框架默认 404；uvicorn 启动关闭 `server` 响应头，不暴露
  应用结构与框架指纹。
- **滥用防护**：每连接每秒最多 10 条消息（`--rate-limit`）；单条 WS 消息最大
  1MB；输入字段长度上限（名字 32 / 房间 id 16 / 令牌 64 / 卡组码 1024）；
  房间总数上限 1000（`--max-rooms`）。
- **传输内容**：房间 id、token 与识别码经 TLS（wss）时不被窃听；公网部署应启用
  TLS。公网 IP 查询会使用第三方 ipify/ifconfig.me 服务。

## 架构

```
server/
  main.py          # FastAPI 应用与 /ws endpoint、启动参数、--debug-console stdin 线程
  room.py          # Room：封装 Game + 玩家连接 + 调度/回合计时器
  manager.py       # RoomManager：创建/加入/查询/回收房间（内存表，无持久化）
  protocol.py      # 消息信封构造与客户端消息校验
```

- 服务端持有 authoritative 的 `core.engine.Game` 实例；客户端只提交指令，服务端校验、
  执行并广播按视角脱敏的完整 `GameState` JSON 与新增日志。
- 创建房间可自建 6 位房码；入座生成 8 位凭证，正式开局仅向本人下发识别码。
  GUI 以房码、识别码和公网 IP 自动重连；旧 CLI 可继续手动使用房码+token。
  对局与计时器保留，双方断线才回收房间。
- **准备阶段**：双方都位后等待准备；任一方准备后对未准备方计 15s，双方准备后
  3s 开局。开始倒计时前可取消准备；入座后即可离开。等待对手的房主断线时保留座位
  与 token，可用原房码+token 恢复；其他准备阶段断线视同离开并释放座位。
- **房间看门狗**：未开局房间 10 分钟无人员变动自动解散（含等待中的空房）；已开局房间不适用。
- **对局模式**：标准模式固定最新环境；自由模式可指定环境，双方未准备时房主可修改，
  修改前后均按房间环境校验卡组。
- 座位与 `players` 下标在开局随机先手时确定；回合内操作仅当前行动方可发。

## 通信协议（WebSocket JSON）

客户端 → 服务端：

```json
{ "type": "create", "name": "甲", "deck_code": "<卡组码>", "room_id": "Ab12cd", "mode": "standard", "client_ip": "8.8.8.8", "cardback": "月明风清" }
{ "type": "join", "room_id": "ABC123", "name": "乙", "deck_code": "<卡组码>", "client_ip": "8.8.4.4", "cardback": "月明风清" }
{ "type": "join", "room_id": "ABC123", "reconnect_code": "abcd1234", "client_ip": "8.8.8.8" }
{ "type": "ready" }
{ "type": "leave" }
{ "type": "env", "date": 20250701 }
{ "type": "cmd", "cmd": { "op": "end_turn" } }
```

`deck_code` 首次入座必填，重连时为 null。`client_ip` 由客户端经 ipify（备用
ifconfig.me）best-effort 查询并校验为公网地址；它是可伪造的自报值，仅作为自动
重连的辅助校验与日志信息，不下发给对手。旧 token 重连仍兼容。`cardback` 仅在首次
join 时记录，重连不刷新。
`create.room_id` 可缺省（随机分配）；指定时须为 6 位大小写字母/数字且未被占用。
`create.mode` 可缺省（`standard`）；标准模式忽略 `env_date`（固定最新数据），自由模式
`create.env_date` 可缺省（最新数据）；`env` 仅自由模式房主在双方均未准备时可用（date 缺省 = 最新）。
`ready` 仅双方都位后有效；`leave` 在已入座且开局前有效。`left` 应答后 WebSocket 不断开，可继续 create/join。

服务端 → 客户端：

```json
{ "type": "joined", "room_id": "...", "token": "...", "seat": 0, "debug": false }
{ "type": "lobby", "ready": ["甲"], "deadline": 1735689600.0, "mode": "standard", "env_date": null }
{ "type": "starting", "deadline": 1735689600.0 }
{ "type": "peer_left", "name": "乙" }
{ "type": "left" }
{ "type": "start", "player_index": 0, "opponent": "乙", "you_first": true, "mode": "standard", "env_date": null, "reconnect_code": "abcd1234" }
{ "type": "state", "payload": { "..." : "GameState JSON" }, "log": ["..."],
  "timer": { "kind": "turn", "deadline": 1735689600.0 },
  "settle": ["..."], "timeline": [{ "k": "s", "m": "..." }], "opponent_cardback": "月明风清" }
{ "type": "error", "reason": "..." }
{ "type": "notice", "text": "..." }
{ "type": "game_over", "winner": 0, "reason": "player_defeated" }
```

`lobby.deadline` 仅一方已准备时非空（未准备方的自动准备截止）；`ready` 为空 =
双方未准备、不计时。`lobby`/`start` 始终携带 `mode`；`env_date` 为 null 时字段省略（最新数据）。

`state.payload` 附带仅己方手牌的 `hand_info`（键为 uid 字符串）：实时费用、关键字、
数值段、增强/委托进度、使用条件与 `Game.usage_options` 使用方式枚举；由
`client/cli.py hand_cards_info` 统一求值，在广播/重连补发时注入，客户端不重复实现规则计算。

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
