"""authoritative 服务端入口（Phase 2 实现）。

规划：
- FastAPI / websockets 做通信层；
- 客户端只提交指令（与 client/cli.py 完全相同的 cmd dict 协议），
  服务端用 core.engine.Game 校验、执行并广播新状态；
- 状态即 core.model.GameState，天然可序列化，直接 JSON 下发。
"""


def main() -> None:
    raise SystemExit(
        "服务端尚未实现（Phase 2）。当前请用 uv run python -m client.cli 进行本地热座对战。"
    )


if __name__ == "__main__":
    main()
