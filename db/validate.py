"""数据库校验命令入口：uv run python -m db.validate"""
from db.loader import CardDatabase
from db.rawtext import check_readme_names, check_text_alignment


def main() -> None:
    # strict=False 让 loader 不抛异常；我们再手动 validate 一次，以便打印友好错误列表。
    db = CardDatabase.load(strict=False)
    errors = db.validate()
    # 硬门禁（AGENTS.md 内容约定）：yaml text 逐字 = card_data_raw.md 引号内原文；
    # README 不出现具体式神/卡牌名
    text_errors, text_warnings = check_text_alignment(db)
    errors += text_errors
    errors += check_readme_names(db)
    if errors:
        print("校验失败：")
        for e in errors:
            print(" -", e)
        if text_warnings:
            print(f"text 对齐警告 {len(text_warnings)} 条（不阻塞）：")
            for w in text_warnings:
                print(" -", w)
        raise SystemExit(1)
    derived = sum(1 for d in db.shikigami.values() if d.kind in ("summon", "transform", "replace"))
    print(f"校验通过：{len(db.shikigami) - derived} 个式神"
          f"（另 {derived} 个召唤物/变形物/替换物实体），{len(db.cards)} 张卡牌，"
          f"{len(db.invocations)} 个灵咒，{len(db.custom_events)} 个自定义事件；"
          f"text 逐字对齐 raw 与 README 名字扫描通过")
    if text_warnings:
        print(f"text 对齐警告 {len(text_warnings)} 条（不阻塞）：")
        for w in text_warnings:
            print(" -", w)


if __name__ == "__main__":
    main()
