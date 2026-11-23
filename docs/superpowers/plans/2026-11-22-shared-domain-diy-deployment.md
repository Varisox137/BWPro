# BWPro 与 BWPDIY 同域部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `bwpro.varisox137.top` 同一域名下提供 BWPDIY 在线本地版与 BWPro 联机服务，同时保持现有客户端协议、鉴权和本地数据边界不变。

**Architecture:** 花生壳 HTTPS 映射只连接本机 Nginx；Nginx 将 `/diy/` 交给 BWPDIY 静态站点，将 `/ws` 与 `/api/log-admin/` 反代到 BWPro `127.0.0.1:1037`。BWPro 不感知 DIY 页面，也不改为 `/api` 前缀应用；公网路径与内部路径保持稳定。

**Tech Stack:** 现有 FastAPI、Uvicorn、WebSocket、桌面客户端；Nginx；花生壳 HTTPS 映射。BWPDIY 侧为静态文件、Pyodide、Service Worker。

## Global Constraints

- 默认公网入口固定为 `https://bwpro.varisox137.top/diy/` 与 `wss://bwpro.varisox137.top/ws`。
- BWPro 联机端点保持 `server/main.py` 的 `/ws`；日志管理保持 `/api/log-admin/`，不占用或重定义 `/api` 全段。
- 不修改 WebSocket 消息协议、房间流程、重连凭证、DIY 内容同步格式或客户端默认端口。
- 不开启 Uvicorn `proxy_headers`；来源 IP 只用于日志，鉴权限流仍只认 socket 对端地址。
- 保留现有 `ws_ping_interval=10`、`ws_ping_timeout=5`，不另加应用层心跳。
- 公网不得暴露 BWPDIY 正式编辑器 8630/8631，也不得暴露其项目读写 API。
- 本计划只调整 BWPro 的部署配置与文档。BWPDIY 的 `/diy/` 静态构建、`runtime.zip` 预生成和 Service Worker 作用域由 BWPDIY 项目另行实现，是其上线前置条件。

## 现状与决策

以下能力已经存在，不重复开发：

- `client/net.py:40-55` 会把裸域名规范化为 `wss://<域名>/ws`，也会保留用户显式给出的自定义路径。
- `server/main.py:205` 提供 `/ws`，`server/main.py:526-533` 已配置协议心跳、1 MiB 消息上限并关闭 `proxy_headers`。
- `server/main.py:122-133` 已按 XFF、X-Real-IP、socket 对端顺序记录来源；该值不参与鉴权。
- `client/log_admin.py` 已可从联机地址推导日志管理地址，沿用同域 `/api/log-admin/` 即可。

不采用“把整个 BWPro 挂到 `/api`”作为默认方案：联机不是普通 REST API，且现有日志管理已经使用该前缀。若以后必须提供 `/api/ws`，只需在 Nginx 增加精确路径重写 `/api/ws → /ws`，客户端填写完整 `wss://bwpro.varisox137.top/api/ws`；无需修改 FastAPI 路由。

## 文件结构

- 新建 `server/deploy/nginx-bwpro-locations.conf.example`：只包含 BWPro 的 WebSocket 与日志管理 location，可由最终同域 Nginx `server {}` 配置包含。
- 修改 `server/README.md`：记录同域拓扑、启动方式、客户端地址、安全边界与验收方法。
- 不修改 `server/main.py`、`client/net.py`、`client/log_admin.py` 和协议测试；现有实现已经满足路径与心跳要求。

---

### Task 1: 增加 BWPro 同域反代配置与部署文档

**Files:**
- Create: `server/deploy/nginx-bwpro-locations.conf.example`
- Modify: `server/README.md` 的「内网穿透 / 公网联机」与「远程日志管理」章节

**Interfaces:**
- Consumes: BWPro 内部 `127.0.0.1:1037/ws` 与 `127.0.0.1:1037/api/log-admin/`。
- Produces: 可包含进同域 Nginx `server {}` 的固定 location 配置，以及公网 `/ws`、`/api/log-admin/` 契约。

- [ ] **Step 1: 编写 BWPro location 示例**

配置必须满足以下精确行为：

```nginx
location = /ws {
    proxy_pass http://127.0.0.1:1037;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 75s;
    proxy_send_timeout 75s;
}

location /api/log-admin/ {
    proxy_pass http://127.0.0.1:1037;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP $remote_addr;
}
```

`proxy_pass` 均不附加新 URI，避免意外改写现有路径。示例文件注明：这些指令必须位于最终同域 `server {}` 内；`/diy/` 的静态站点配置由 BWPDIY 提供，不能将 `/` 全部反代到 BWPro。

- [ ] **Step 2: 更新启动和连接说明**

在 `server/README.md` 写明：

```text
公网 /diy/             → BWPDIY 静态站点
公网 /ws               → 127.0.0.1:1037/ws
公网 /api/log-admin/   → 127.0.0.1:1037/api/log-admin/
```

花生壳映射目标改为本机 Nginx，而不再直接映射 1037。BWPro 与 Nginx 同机时使用 `--host 127.0.0.1 --port 1037`；Termux 启动脚本对应为：

```bash
BWP_HOST=127.0.0.1 BWP_PORT=1037 ./scripts/termux_server.sh
```

桌面客户端仍只输入 `bwpro.varisox137.top`，实际连接 `wss://bwpro.varisox137.top/ws`；日志运维端继续从该地址推导管理 URL。TLS 在花生壳边缘终止，本机 BWPro 不重复配置证书。

- [ ] **Step 3: 记录安全与运维边界**

文档明确：XFF 只作日志参考；不要打开 `proxy_headers`；不要开启 `--allow-debug-rooms`；日志提取码仍走 HTTPS 并按原周期轮换；Nginx 默认拒绝未登记路径，不能把 BWPDIY 正式编辑器或 BWPro 仓库目录作为静态根目录。

- [ ] **Step 4: 校验文档和配置差异**

Run:

```bash
git diff --check
nginx -t
```

Expected: `git diff --check` 无输出；`nginx -t` 对包含该 snippet 的最终同域配置报告 syntax ok/test successful。若当前环境没有 Nginx，必须在实际部署机执行后者，不能以未运行冒充通过。

- [ ] **Step 5: 提交配置与文档**

```bash
git add server/deploy/nginx-bwpro-locations.conf.example server/README.md
git commit -m "docs(部署): 增加BWPDIY同域反代配置"
git push
```

### Task 2: 本机完成双服务与 WebSocket 回归

**Files:**
- Modify: `server/README.md`，仅在实测后记录本机验收结果或环境限制
- Test: 复用 `tests/test_client.py::test_normalize_and_display_server_url`、`tests/test_server.py`、`tests/test_log_admin.py`

**Interfaces:**
- Consumes: Task 1 的 Nginx location 与 BWPDIY 已完成的 `/diy/` 静态部署。
- Produces: 不经过公网隧道即可复现的同域双服务环境。

- [ ] **Step 1: 验证现有客户端地址契约**

Run:

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_client.py::test_normalize_and_display_server_url -n 0
```

Expected: PASS；裸 `bwpro.varisox137.top` 仍生成 `wss://bwpro.varisox137.top/ws`，显式自定义路径行为不变。本任务不新增重复的路径字符串测试。

- [ ] **Step 2: 启动最终 Nginx 配置并检查路由隔离**

在 Nginx、BWPro、BWPDIY 静态站点均启动后验证：

```bash
curl -i http://127.0.0.1:8080/diy/
curl -i http://127.0.0.1:8080/ws
curl -i http://127.0.0.1:8080/api/log-admin/logs
curl -i http://127.0.0.1:8080/not-registered
```

Expected: DIY 返回页面；普通 GET `/ws` 由 BWPro 返回空体 403；无提取码的日志接口返回空体 401；未登记路径由 Nginx 返回 404，不泄露任一应用结构。实际监听端口若不同，记录真实端口，不把示例端口当作强制要求。

- [ ] **Step 3: 通过 Nginx 完成真实联机**

使用两个桌面客户端连接 `ws://127.0.0.1:8080/ws`，依次完成创建房间、加入、准备、开始游戏、一个完整回合、主动断线重连。另保持一个已入座连接至少 90 秒，确认 10 秒协议心跳能维持连接且 Nginx 75 秒读超时不误断。

- [ ] **Step 4: 回归日志管理与现有服务端测试**

使用日志运维端连接 `http://127.0.0.1:8080/ws`，验证当前提取码可列出、预览和下载日志，错误提取码仍返回 401。随后运行：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q tests/test_server.py tests/test_log_admin.py -n 0
```

Expected: 全部 PASS。不得为让部署通过而放宽鉴权、消息上限或重连校验。

- [ ] **Step 5: 提交本机验收说明**

仅在文档确有验收结果更新时执行：

```bash
git add server/README.md
git commit -m "docs(部署): 记录同域双服务本机验收"
git push
```

### Task 3: 花生壳公网验收与回退确认

**Files:**
- Modify: `server/README.md`，记录花生壳免费版实际可用性与已观察限制

**Interfaces:**
- Consumes: Task 2 全部通过的本机环境。
- Produces: 可供其他玩家使用的 `wss://bwpro.varisox137.top/ws` 和可供浏览器使用的 `https://bwpro.varisox137.top/diy/`。

- [ ] **Step 1: 切换花生壳映射**

将现有 HTTPS 映射的内网目标改为最终 Nginx 地址，保留域名和 HTTPS。确认映射边缘到 Nginx 的请求不强制跳转提示页，且 WebSocket Upgrade 不被拦截。

- [ ] **Step 2: 验证公网页面与路由隔离**

用非服务端所在浏览器的隐私窗口访问 `/diy/`，确认首次渲染、PNG 导出、草稿刷新恢复可用；检查浏览器网络面板中 DIY 请求没有打到 `/ws`，Service Worker 只控制 `/diy/`。访问未登记路径仍为 404，不能读取仓库文件或正式编辑器 API。

- [ ] **Step 3: 验证公网真实联机和重连**

两个外部客户端都输入 `bwpro.varisox137.top`，重复 Task 2 的建房、开局、回合与断线重连流程，并保持连接至少 10 分钟。记录是否发生花生壳侧闲置断线、带宽限制或提示页；若心跳无法维持，先调整隧道/反代，不修改游戏规则计时或关闭重连校验。

- [ ] **Step 4: 验证公网日志管理与 DIY 隔离**

通过 HTTPS 运维端读取日志，确认错误提取码仍被拒绝；同时在 DIY 页面编辑草稿后执行建房联机，确认两者互不清空浏览器数据、不改变房间状态。浏览器存储按源共享但数据库名称不同，Service Worker 不得越出 `/diy/`。

- [ ] **Step 5: 验证回退路径并提交结果**

回退时只需把花生壳内网目标改回直接 BWPro 1037，或停用同域 Nginx 站点；不涉及数据库、房间协议或客户端升级。确认回退后原客户端裸域名仍能连接，再记录实测结果：

```bash
git add server/README.md
git commit -m "docs(部署): 记录花生壳同域公网验收"
git push
```

## 完成标准

- 同一域名下 `/diy/` 与 `/ws` 均可独立使用，未登记路径不进入任一应用。
- BWPro 客户端仍可用裸域名连接，建房、开局、回合、心跳、重连与日志管理全部实测通过。
- 未修改协议、鉴权、代理信任模型或游戏规则代码。
- BWPDIY 草稿与卡图仍仅存浏览器；公网服务器不新增作品写盘接口。
- 花生壳免费版的实际限制有记录；未实测的项目明确标注，不能宣称已经完成公网部署。
