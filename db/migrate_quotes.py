"""卡牌描述引号的一次性字节级迁移工具。"""
from pathlib import Path


def convert_text(text: str) -> str:
    return text.replace("“棺材”", "「棺材」").replace("‘", "『").replace("’", "』")


def migrate_file(path: Path) -> bool:
    original = path.read_bytes()
    migrated = convert_text(original.decode("utf-8")).encode("utf-8")
    if migrated == original:
        return False
    path.write_bytes(migrated)
    return True


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    paths = [root / "card_data_raw.md", *sorted((root / "db").rglob("*.yaml"))]
    changed = sum(migrate_file(path) for path in paths)
    print(f"已迁移 {changed} 个文件。")


if __name__ == "__main__":
    main()
