"""卡牌/式神 YAML 脚手架：生成最小合法骨架，录卡时只需补效果块。

用法：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.scaffold shikigami \
        --id 100127 --name 萤草 --slug yingcao --faction green --power 2 --health 5 [--with-cards]
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m db.scaffold card \
        --shikigami 100127 --seq 01 --name 治愈之光 --type spell

输出目录约定（见 db/packs.py）：db/<版本包编号>_<拼音>/<包内编号>_<式神拼音>/，
6 位式神 yaml 与其全部 8 位卡牌 yaml 同目录存放；协战牌本体归主式神
（两位所属中 id 较小者）目录。

生成后立即跑 loader 校验，骨架必须过校验（空 effects.steps 合法但打出无效果，
由注释引导后续 Edit 补全）。已存在的文件默认拒绝覆盖，--force 才覆盖。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from db.loader import CardDatabase
from db.packs import find_shiki_dir, pack_dir_name, shiki_dir_name
from db.schema import CARD_TYPES, FACTION_COLORS, RARITIES

DB_ROOT = Path(__file__).parent

HEADER = "# 脚手架生成（db.scaffold），待补效果块与卡面文本\n"
_FACTION_BY_COLOR = {v: k for k, v in FACTION_COLORS.items()}
# 01-08 默认等级分布（三张 1 级、三张 2 级、两张 3 级）
_DEFAULT_LEVELS = [1, 1, 1, 2, 2, 2, 3, 3]


def _version() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


def _write(path: Path, content: str, force: bool) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"文件已存在：{path}（--force 才覆盖）")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def scaffold_shikigami(
    root: Path | str,
    *,
    id: int,
    name: str,
    faction: str,
    power: int,
    health: int,
    kind: str = "shikigami",
    slug: str | None = None,
    with_cards: bool = False,
    force: bool = False,
) -> list[Path]:
    """生成式神骨架（可选连带 01-08 八张卡骨架）；返回写入的文件列表。

    shikigami 须给 slug（式神名拼音，决定目录名 <包内编号>_<slug>）；
    summon 从属式神的目录即其存放目录。
    """
    root = Path(root)
    if faction not in _FACTION_BY_COLOR.values():
        raise ValueError(f"未知派系 {faction}（{sorted(_FACTION_BY_COLOR.values())}）")
    if kind == "shikigami":
        if not 100_000 <= id <= 199_999:
            raise ValueError("式神 id 须为 6 位 1avvss")
        if not slug:
            raise ValueError("须给 --slug（式神名拼音，用于目录名）")
        out_dir = root / pack_dir_name(id) / shiki_dir_name(id, slug)
    elif kind == "summon":
        if not 10_000_000 <= id <= 99_999_999 or not 90 <= id % 100 <= 99:
            raise ValueError("召唤物 id 须为 8 位且序号在 90-99 号段")
        out_dir = find_shiki_dir(root, id // 100)
        if out_dir is None:
            raise ValueError(f"召唤物从属式神 {id // 100} 不存在")
    else:
        raise ValueError(f"未知 kind {kind}")

    lines = [HEADER]
    lines.append(f"id: {id}\n")
    lines.append(f"name: {name}\n")
    lines.append("versions:\n")
    lines.append(f"  best: {_version()}\n")
    lines.append("  history:\n")
    lines.append(f"    - date: {_version()}  # 发布日期\n")
    if kind == "summon":
        lines.append("      kind: summon\n")
    lines.append(f"      faction: {faction}\n")
    lines.append(f"      power: {power}\n")
    lines.append(f"      health: {health}\n")
    lines.append("      # ability: 待补被动（when 为事件名，不可用 on_play；倒计时能力用 countdown: n）\n")
    lines.append('      text: ""\n')
    written = [_write(out_dir / f"{id}.yaml", "".join(lines), force)]

    if with_cards:
        for i, seq in enumerate(range(1, 9)):
            written.append(scaffold_card(
                root, shikigami=id, seq=seq, name=f"待补卡名{seq:02d}",
                card_type="spell", level=_DEFAULT_LEVELS[i], force=force,
            ))
    return written


def scaffold_card(
    root: Path | str,
    *,
    shikigami: int,
    seq: int,
    name: str,
    card_type: str,
    level: int = 1,
    cost: int = 1,
    rarity: str = "R",
    token: bool = False,
    shikigami2: int | None = None,
    awaken: bool = False,
    force: bool = False,
) -> Path:
    """生成卡牌骨架；返回写入的文件路径。faction 注释继承自所属式神 yaml。"""
    root = Path(root)
    if card_type not in CARD_TYPES:
        raise ValueError(f"未知主类型 {card_type}（{sorted(CARD_TYPES)}）")
    if rarity not in RARITIES:
        raise ValueError(f"未知稀有度 {rarity}（{sorted(RARITIES)}）")
    owner_dir = find_shiki_dir(root, shikigami)
    if owner_dir is None:
        raise ValueError(f"所属式神 {shikigami} 不存在（先生成式神骨架）")

    if card_type == "reinforce":
        if shikigami2 is None:
            raise ValueError("协战牌须给 --shikigami2（副归属式神）")
        if find_shiki_dir(root, shikigami2) is None:
            raise ValueError(f"协战副归属式神 {shikigami2} 不存在")
        if seq < 21:
            raise ValueError("协战牌序号须从 21 开始")
        # 约定：shikigami = 两位所属中较小者（= id 前六位），shikigami2 = 较大者
        shikigami, shikigami2 = sorted((shikigami, shikigami2))
        owner_dir = find_shiki_dir(root, shikigami)  # 协战牌本体归主式神目录
    elif shikigami2 is not None:
        raise ValueError("仅协战牌可以有 --shikigami2")
    elif token:
        if not 51 <= seq <= 99:
            raise ValueError("衍生卡序号须在 51-99 号段")
    elif not 1 <= seq <= 8:
        raise ValueError("可构筑卡牌序号须在 01-08 号段")

    card_id = shikigami * 100 + seq

    lines = [HEADER]
    lines.append(f"id: {card_id}\n")
    lines.append(f"name: {name}\n")
    lines.append("versions:\n")
    lines.append(f"  best: {_version()}\n")
    lines.append("  history:\n")
    lines.append(f"    - date: {_version()}  # 发布日期\n")
    # shikigami（= id 前六位）由 id 推导，不入数据；中立牌由 id 首位 9 识别
    if shikigami2 is not None:
        lines.append(f"      shikigami2: {shikigami2}  # 协战副归属\n")
    lines.append(f"      card_type: {card_type}\n")
    if awaken:
        lines.append("      subtype: awaken\n")
    lines.append(f"      rarity: {rarity}\n")
    if token:
        lines.append("      token: true\n")
    lines.append(f"      level: {level}\n")
    if cost != 1:  # cost 默认 1（schema 默认值），非 1 才写入
        lines.append(f"      cost: {cost}\n")
    if card_type == "form":
        lines.append("      form_power: 3  # TODO: 待填\n")
        lines.append("      form_health: 4  # TODO: 待填\n")
    if card_type == "reinforce":
        lines.append("      # options: [主侧子卡id, 副侧子卡id]  # TODO: 待补（缺省由打出流程报错）\n")
    lines.append("      effects:\n")
    lines.append("        # TODO: 补效果 steps（空 steps 可过校验，但打出无任何效果）\n")
    lines.append("        steps: []\n")
    if card_type == "form":
        lines.append("      # abilities: 待补形态能力块（结附期间生效）\n")
    if awaken:
        lines.append("      # abilities: 待补觉醒能力块（打出时替换式神能力）\n")
    lines.append('      text: ""  # TODO: 待补卡面文本\n')
    return _write(owner_dir / f"{card_id}.yaml", "".join(lines), force)


def _validate_and_print(root: Path) -> int:
    """生成后跑一遍 loader 校验并打印结果；返回退出码。"""
    db = CardDatabase.load(root, strict=False)
    errors = db.validate()
    if errors:
        print("校验失败：")
        for e in errors:
            print(" -", e)
        return 1
    print(f"校验通过：{len(db.shikigami)} 个式神，{len(db.cards)} 张卡牌，"
          f"{len(db.custom_events)} 个自定义事件")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="db.scaffold",
        description="卡牌/式神 YAML 脚手架：生成最小合法骨架再补效果块（生成后自动跑 loader 校验）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("shikigami", help="生成式神骨架 db/<pack>/<seq>_<slug>/<id>.yaml")
    ps.add_argument("--id", type=int, required=True, help="6 位式神 id（如 100127）")
    ps.add_argument("--name", required=True, help="式神名")
    ps.add_argument("--slug", default=None,
                    help="式神名拼音（目录名 <包内编号>_<slug>，如 yingcao；shikigami 必给）")
    ps.add_argument("--faction", required=True,
                    choices=["red", "purple", "blue", "green", "white"],
                    help="派系：red=红莲 purple=紫岩 blue=青岚 green=苍叶 white=无相")
    ps.add_argument("--power", type=int, required=True, help="基础力量")
    ps.add_argument("--health", type=int, required=True, help="基础生命")
    ps.add_argument("--kind", default="shikigami", choices=["shikigami", "summon"],
                    help="默认 shikigami；summon=召唤物（id 须 8 位、序号 90-99）")
    ps.add_argument("--with-cards", action="store_true",
                    help="同时生成 01-08 共 8 张卡骨架（spell，等级 1/1/1/2/2/2/3/3）")
    ps.add_argument("--force", action="store_true", help="覆盖已存在的文件")

    pc = sub.add_parser("card", help="生成卡牌骨架（写入所属式神目录，协战牌归主式神目录）")
    pc.add_argument("--shikigami", type=int, required=True, help="6 位所属式神 id")
    pc.add_argument("--seq", type=int, required=True,
                    help="2 位卡序号：可构筑 01-08 / 衍生 token 51-99 / 协战 21 起")
    pc.add_argument("--name", required=True, help="卡名")
    pc.add_argument("--type", dest="card_type", required=True,
                    choices=sorted(CARD_TYPES), help="主类型")
    pc.add_argument("--level", type=int, default=1, help="等级（默认 1）")
    pc.add_argument("--cost", type=int, default=1, help="鬼火消耗（默认 1）")
    pc.add_argument("--rarity", default="R", choices=sorted(RARITIES), help="默认 R")
    pc.add_argument("--token", action="store_true", help="衍生卡（序号 51-99）")
    pc.add_argument("--shikigami2", type=int, default=None,
                    help="协战副归属式神 id（仅 --type reinforce；id 前六位取两者较小者）")
    pc.add_argument("--awaken", action="store_true", help="觉醒牌（subtype: awaken）")
    pc.add_argument("--force", action="store_true", help="覆盖已存在的文件")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "shikigami":
            written = scaffold_shikigami(
                DB_ROOT, id=args.id, name=args.name,
                faction=_FACTION_BY_COLOR[args.faction], power=args.power,
                health=args.health, kind=args.kind, slug=args.slug,
                with_cards=args.with_cards, force=args.force,
            )
        else:
            written = [scaffold_card(
                DB_ROOT, shikigami=args.shikigami, seq=args.seq, name=args.name,
                card_type=args.card_type, level=args.level, cost=args.cost,
                rarity=args.rarity, token=args.token, shikigami2=args.shikigami2,
                awaken=args.awaken, force=args.force,
            )]
    except (FileExistsError, ValueError) as e:
        print(f"生成失败：{e}", file=sys.stderr)
        return 1
    for p in written:
        print(f"已生成：{p}")
    return _validate_and_print(DB_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
