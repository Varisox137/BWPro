# BWPro 与 BWPDIY 双子域名部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 BWPro 文档中落地同机双端口、两条 HTTPS 隧道、两个子域名的独立部署方案。

**Architecture:** BWPro 继续监听 1037 并提供 `/ws` 与 `/api/log-admin/`；BWPDIY Pyodide 静态服务独立监听 8640。两条隧道分别回连两个回环端口，不经过 Nginx，也不让两个应用互相代理。

**Tech Stack:** 现有 FastAPI、Uvicorn、WebSocket、BWPDIY Pyodide 静态服务器、Termux Bash、花生壳 HTTPS 映射。

## Global Constraints

- 公网仅发布 BWPDIY `prototype/pyodide/` 在线本地版，不暴露正式编辑器 8630/8631 或项目读写 API。
- BWPro 默认客户端地址、消息协议、日志管理路径和 Termux 启动逻辑不变。
- DIY 示例域名为 `diy.varisox137.top`，实际以花生壳配置为准。
- 两个服务均只监听 `127.0.0.1`；TLS 在隧道边缘终止。
- 不开启 Uvicorn `proxy_headers`，不改变鉴权限流或重连校验。
- 未实际执行的公网验收不得宣称为已通过。

## 文件结构

- 修改 `server/README.md`：补充双服务拓扑、启动命令、映射配置、安全边界与验收流程。
- 复用 `docs/superpowers/specs/2026-11-22-separate-subdomain-diy-deployment-design.md`：作为设计契约，不重复实现运行时代码。

---

### Task 1: 记录双子域名独立部署与验收流程

**Files:**
- Modify: `server/README.md` 的「Termux Debian 更新与启动」「远程日志管理」「内网穿透 / 公网联机」章节

**Interfaces:**
- Consumes: BWPro `127.0.0.1:1037/ws`、`127.0.0.1:1037/api/log-admin/` 与 BWPDIY `127.0.0.1:8640/prototype/pyodide/`。
- Produces: 可直接照做的双服务部署文档；不产生新的应用程序接口。

- [ ] **Step 1: 补充双服务拓扑和独立启动命令**

在「内网穿透 / 公网联机」开头加入：

```text
https://bwpro.varisox137.top → HTTPS 隧道 A → 127.0.0.1:1037  BWPro
https://diy.varisox137.top   → HTTPS 隧道 B → 127.0.0.1:8640  BWPDIY
```

同时给出两个独立干净副本中的启动命令：

```bash
# BWPro
BWP_HOST=127.0.0.1 BWP_PORT=1037 ./scripts/termux_server.sh

# BWPDIY（另一仓库副本）
BWPDIY_PORT=8640 ./scripts/termux_server.sh
```

说明 BWPDIY 根地址会跳转到 `/prototype/pyodide/`；该路径和运行时资源都由 DIY 服务自身提供，BWPro 不配置 `/diy/` 路由。

- [ ] **Step 2: 记录两条映射与安全边界**

明确隧道 A 必须支持 WebSocket Upgrade，隧道 B 只需 HTTPS 静态资源访问；两者 TLS 均在边缘终止。BWPDIY 正式编辑器 8630/8631 不得映射公网，两个服务互不共享进程、日志提取码或数据目录。

日志运维端仍连接 `https://bwpro.varisox137.top`，不能使用 DIY 子域名。DIY 浏览器草稿和 BWPro 房间内容同步保持现有独立链路。

- [ ] **Step 3: 增加本机与公网验收步骤**

文档列出以下检查，不声称已在当前开发机执行：

```bash
curl -i http://127.0.0.1:8640/
curl -i http://127.0.0.1:1037/ws
curl -i https://diy.varisox137.top/
```

随后用两个客户端通过 BWPro 子域名完成建房、加入、开局、一个完整回合和断线重连；用浏览器在 DIY 子域名导出 PNG 并刷新恢复草稿。分别停止任一服务，确认另一服务不受影响。域名替换为实际配置后，检查项不变。

- [ ] **Step 4: 校验文档与现有地址契约**

Run:

```bash
git diff --check
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_client.py::test_normalize_and_display_server_url
```

Expected: `git diff --check` 无错误；地址测试 PASS，裸 BWPro 域名仍生成 `wss://bwpro.varisox137.top/ws`。

- [ ] **Step 5: 提交并推送**

```bash
git add server/README.md docs/superpowers/plans/2026-11-22-separate-subdomain-diy-deployment.md
git commit -m "docs(部署): 补充双子域名双服务运行说明"
git push
```
