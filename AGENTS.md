# AGENTS.md

## Git 约定

- commit 使用中文 conventional 格式（如 `feat(引擎): ...`、`docs(卡牌状态): ...`）。
- **每次 commit 后执行 `git push`**；失败（无网络/无远端权限等）不阻塞工作，向用户汇报结果即可。

## 测试

- 测试命令（Windows Git Bash 固定用法）：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest -q`
- 数据库校验：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.validate`（加卡后必跑）

## 内容约定

- README 不出现具体式神/卡牌名（`docs/` 可以）；原版卡牌描述以 `card_data_raw.md` 为唯一事实来源。
- 机制未实现不进数据（关键字/op 未落地不写进 yaml）；schema 字段只增不改。
- `CLAUDE.md`、`questions.md`、`thoughts.txt` 为本地工作笔记（已 gitignore，不入库）。

## 输出约定（省 token）

- 汇报从简：不复述代码、不贴大段 diff/文件内容，只给结论、路径与关键决策。
- 编辑用 Edit 精准替换，不用 Write 整文件重写；写入后不冗余重读验证。
- 新增式神/卡牌 yaml 一律用脚手架生成骨架再补效果块（`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.scaffold -h` 查看用法），不手写整份 yaml。

## MCP 工具

- **Serena**（符号级代码导航）：查函数/类位置与签名优先用 `mcp__serena__find_symbol`/`get_symbols_overview`/`find_referencing_symbols`，避免整文件通读；大段符号替换可用其编辑工具，小改仍用内置 Edit。
- **codebase-memory**（语义代码图谱）：自然语言/语义查代码用 `mcp__codebase-memory__search_graph`/`search_code`/`trace_path`。**大批量代码改动后需重建索引**（`index_repository`，mode=full），否则结果是旧代码。
