"""版本包目录约定：卡牌/式神 YAML 统一存放于 db/<pack>/<seq>_<slug>/。

- <pack> = 2 位目录前缀 + 拼音名（id 第 2-4 位的三位版本包编号映射到该前缀），
  编号与目录名的对应关系登记在 PACKS；引入新版本包时先在此登记。
- <seq>_<slug> = 包内式神编号（id 末两位）+ 式神名拼音（如 01_bailang）。
- 目录内统一存放 6 位式神 id 的 yaml 与其所有卡牌的 8 位 id yaml
  （专属牌/衍生牌/衍生物/作为主式神的协战牌本体；协战牌本体归 id 前六位
  即两位所属中较小者的目录）。
"""
from __future__ import annotations

from pathlib import Path

PACKS = {
    "000": "beginner",      # 新手包
    "001": "jingdian",      # 经典包
    "002": "buyezhihuo",    # 不夜之火
    "003": "yueyehuanxiang",  # 月夜幻响
    "004": "canghaidaoming",  # 沧海刀鸣（已完结：10 式神全部落地去标）
    "005": "jiyunyuanjie",  # 吉运缘结（骨架；版本日期 20201224）
}

# 版本包中文名（卡组构筑二级目录等展示用；编号与 PACKS 一致）
PACK_NAMES = {
    "000": "新手包",
    "001": "经典包",
    "002": "不夜之火",
    "003": "月夜幻响",
    "004": "沧海刀鸣",
    "005": "吉运缘结",
}


def pack_names_for(db) -> dict[str, str]:
    names = dict(PACK_NAMES)
    for pack_id, metadata in getattr(db, "diy_packs", {}).items():
        number = f"{int(pack_id):03d}"
        names[number] = metadata.get("name", number)
    return names


def pack_dir_name(sid: int) -> str:
    """6 位式神 id 第 2-4 位的三位包号 → 现有两位前缀目录。"""
    num = str(sid)[1:4]
    if num not in PACKS:
        raise ValueError(f"未知版本包编号 {num}（式神 {sid}；请先在 db/packs.py 登记）")
    return f"{int(num):02d}_{PACKS[num]}"


def shiki_dir_name(sid: int, slug: str) -> str:
    """6 位式神 id + 拼音 slug → 式神目录名（如 01_bailang）。"""
    return f"{sid % 100:02d}_{slug}"


def find_shiki_dir(root: Path, sid: int) -> Path | None:
    """在 db/ 下按 6 位式神 id 定位其目录；不存在返回 None。"""
    for f in sorted(root.glob(f"*/*/{sid}.yaml")):
        return f.parent
    return None
