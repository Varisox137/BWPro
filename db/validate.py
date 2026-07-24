"""数据库校验命令入口：uv run python -m db.validate"""
from db.loader import CardDatabase


def main() -> None:
    # strict=False 让 loader 不抛异常；我们再手动 validate 一次，以便打印友好错误列表。
    db = CardDatabase.load(strict=False)
    errors = db.validate()
    if errors:
        print("校验失败：")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print(f"校验通过：{len(db.shikigami)} 个式神，{len(db.cards)} 张卡牌，"
          f"{len(db.custom_events)} 个自定义事件")


if __name__ == "__main__":
    main()
