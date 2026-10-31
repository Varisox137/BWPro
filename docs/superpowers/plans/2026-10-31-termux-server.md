# Termux Debian 服务端依赖与启动脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆分服务端与 GUI/CLI 依赖，并提供安全、可重复执行的 Termux 更新和启动脚本。

**Architecture:** pyproject 基础依赖只含服务端，GUI/CLI 使用 optional extras，dev 保持完整；shell 脚本使用现有 uv.lock 和 uv-managed Python 3.14，不引入第二套 requirements。

**Tech Stack:** Python 3.14、FastAPI、uvicorn、websockets、uv、Bash。

## Global Constraints

- 设计来源：`docs/superpowers/specs/2026-10-31-termux-server-design.md`。
- 基础依赖仅 fastapi/pydantic/pyyaml/uvicorn/websockets；不自动安装 uv，不自动 stash/reset/clean。
- 桌面开发依赖和 GUI 测试行为不变。
- 所有新行为先写失败测试并确认 RED，再最小实现到 GREEN。
- commit 使用中文 conventional 格式，每次 commit 后推送当前 feature 分支。

---

### Task 1: 服务端基础依赖与 optional extras

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/test_server.py`
- Test: `tests/test_data.py`

- [ ] **Step 1: 写依赖声明失败测试**

解析 pyproject，断言基础 dependencies 不含 pyside6/pillow/prompt-toolkit/uvicorn standard extras，包含 fastapi/pydantic/pyyaml/uvicorn/websockets；gui/cli extras 与 dev 组保留桌面测试依赖。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_server.py tests/test_data.py -k 'dependency or server'`
Expected: 基础依赖仍含 PySide6/Pillow 或 uvicorn[standard]。

- [ ] **Step 3: 拆分依赖并更新锁文件**

基础 dependencies 改为 fastapi、pydantic、pyyaml、uvicorn、websockets；新增 gui/cli extras，dev 继续包含完整依赖。运行 `uv lock`，再检查 `uv sync --locked --no-dev --dry-run` 不包含 GUI 包。

- [ ] **Step 4: 服务端与全量验证**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_server.py`
Run: `PYTHONIOENCODING=utf-8 BWP_DIY_ROOT='D:/Programming/BWPDIY' BWP_DIY_LIBRARY='D:/Programming/BWPro/library' D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/test_server.py tests/test_data.py
git commit -m "build(服务端): 精简基础运行依赖"
git push
```

---

### Task 2: Termux 更新启动脚本与部署文档

**Files:**
- Create: `scripts/termux_server.sh`
- Modify: `server/README.md`
- Modify: `README.md`
- Test: `tests/test_server.py`

- [ ] **Step 1: 写脚本静态与沙箱失败测试**

`bash -n scripts/termux_server.sh` 必须通过。测试脚本含 ff-only、locked、managed-python 3.14、no-dev、no-sync 和干净工作区检查；在临时 git 仓库模拟脏文件应中止且不执行 pull，远端/分支错误应明确退出。

- [ ] **Step 2: 运行测试确认 RED**

Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_server.py -k 'termux_launcher'`
Expected: 脚本不存在。

- [ ] **Step 3: 实现安全启动脚本**

脚本默认 BWP_REPO_DIR 为项目根、REMOTE=main、BRANCH=master、HOST=0.0.0.0、PORT=1037；校验工具/远端/分支/干净状态，tee 记录 launcher 日志。执行：

```bash
git pull --ff-only "$REMOTE" "$BRANCH"
uv sync --locked --managed-python --python 3.14 --no-dev
exec uv run --no-sync python -m server.main --host "$HOST" --port "$PORT" "$@"
```

uv 缺失只给安装提示；日志目录 logs 已被 gitignore，不影响下次脏检查。

- [ ] **Step 4: 文档与验证**

server/README 增加 Termux 准备、干净克隆、执行示例、host/port/追加参数和故障边界；README 部署入口链接到该说明，GUI 安装使用 `uv sync --extra gui`。

Run: `bash -n scripts/termux_server.sh`
Run: `PYTHONIOENCODING=utf-8 D:/Programming/BWPro/.venv/Scripts/python.exe -m pytest -q tests/test_server.py`
Expected: 全部 PASS。真实 Termux aarch64 冷启动由用户在设备验证。

- [ ] **Step 5: Commit**

```bash
git add scripts/termux_server.sh server/README.md README.md tests/test_server.py
git commit -m "feat(服务端): 添加Termux更新启动脚本"
git push
```
