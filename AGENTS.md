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
