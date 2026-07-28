"""版本包目录约定：卡牌/式神 YAML 统一存放于 db/<pack>/<seq>_<slug>/。

- <pack> = 2 位版本包编号 + 拼音名（式神/卡牌 id 第 3-4 位决定所属版本包），
  编号与目录名的对应关系登记在 PACKS；引入新版本包时先在此登记。
- <seq>_<slug> = 包内式神编号（id 末两位）+ 式神名拼音（如 01_bailang）。
- 目录内统一存放 6 位式神 id 的 yaml 与其所有卡牌的 8 位 id yaml
  （专属牌/衍生牌/衍生物/作为主式神的协战牌本体；协战牌本体归 id 前六位
  即两位所属中较小者的目录）。
"""
from __future__ import annotations

from pathlib import Path

PACKS = {
    "00": "beginner",      # 新手包
    "01": "jingdian",      # 经典包
    "02": "buyezhihuo",    # 不夜之火
}


def pack_dir_name(sid: int) -> str:
    """6 位式神 id → 版本包目录名（id 第 3-4 位为版本包编号）。"""
    num = str(sid)[2:4]
    if num not in PACKS:
        raise ValueError(f"未知版本包编号 {num}（式神 {sid}；请先在 db/packs.py 登记）")
    return f"{num}_{PACKS[num]}"


def shiki_dir_name(sid: int, slug: str) -> str:
    """6 位式神 id + 拼音 slug → 式神目录名（如 01_bailang）。"""
    return f"{sid % 100:02d}_{slug}"


def find_shiki_dir(root: Path, sid: int) -> Path | None:
    """在 db/ 下按 6 位式神 id 定位其目录；不存在返回 None。"""
    for f in sorted(root.glob(f"*/*/{sid}.yaml")):
        return f.parent
    return None
