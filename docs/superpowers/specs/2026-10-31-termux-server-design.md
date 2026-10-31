# Termux Debian 服务端依赖与启动脚本设计

日期：2026-10-31

## 目标

让服务端在 Android Termux Debian 中安装和运行，避免 PySide6、Pillow 及非必要 uvicorn 扩展阻碍部署；提供可重复执行的 GitHub 更新与启动脚本。

## 依赖拆分

基础/服务端依赖仅保留：

- `fastapi`
- `pydantic`
- `pyyaml`
- `uvicorn`
- `websockets`

`pyside6` 与 `pillow` 放入 `gui` extra，`prompt-toolkit` 放入 `cli` extra。开发组继续包含完整 GUI/CLI 和测试依赖，桌面开发行为不变。服务端使用 uvicorn 的 h11/asyncio 路径，不要求 uvloop、httptools、watchfiles 等 standard 扩展。

## 启动脚本

新增 `scripts/termux_server.sh`，默认仓库为脚本所在项目根，也可通过 `BWP_REPO_DIR` 指定独立干净克隆。脚本行为：

1. 检查 git、uv、tee、当前分支 `master`、远端 `main` 和预期 GitHub URL。
2. 若存在未提交或未跟踪改动则中止，不自动 stash/reset/clean。
3. `git pull --ff-only main master`，禁止非快进自动合并。
4. `uv sync --locked --managed-python --python 3.14 --no-dev`，不安装 GUI/CLI extras。
5. `exec uv run --no-sync python -m server.main --host "$BWP_HOST" --port "$BWP_PORT" "$@"`。

默认 `BWP_HOST=0.0.0.0`、`BWP_PORT=1037`，支持环境变量覆盖和追加服务端参数。日志通过 tee 写入 `logs/bwpro-launcher-<时间>-<PID>.log`，服务端自身日志保持不变。uv 不存在时给出安装提示，不自动下载执行第三方安装脚本。

## 验证与边界

本机执行 `bash -n`、锁文件一致性检查、服务端测试和完整测试，确认依赖拆分不影响桌面 GUI。Termux 实机需验证 uv-managed CPython 3.14、aarch64 下 pydantic-core/PyYAML/websockets、数据库冷启动、WebSocket 联机和重复执行脚本。若 uv 或 CPython 3.14 在目标系统不可用，脚本应明确报错而不是静默降级 Python 版本。
