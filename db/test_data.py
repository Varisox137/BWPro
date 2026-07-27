"""测试对局用的数据库与卡组辅助：直接加载正式 YAML（db/cards、db/shikigami）。

正式数据只有一份——YAML 文件经 CardDatabase.load 加载并校验，CLI 热座/联机与
测试同源；新增/修改卡牌只需改 YAML，不再需要在此手动同步一份构造代码。
"""
from __future__ import annotations

from db.loader import CardDatabase


def make_test_db() -> CardDatabase:
    """从正式 YAML 加载测试数据库（与 CLI/服务端同源）。"""
    return CardDatabase.load()


# 可构筑式神 id（从正式数据派生，按 id 排序）；测试卡组取前 4 名（组卡规则限 4 名出战，
# 正式数据增至 5 名式神后须截断，否则 make_test_deck 产出非法卡组）
TEST_IDS = sorted(d.id for d in make_test_db().shikigami.values() if d.kind == "shikigami")[:4]


def make_test_deck(shikigami_ids: list[int] | None = None) -> list[int]:
    """合法测试卡组：4 位式神各 8 种不同名卡牌各带 1（共 32 张）。"""
    ids = shikigami_ids or TEST_IDS
    return [sid * 100 + n for sid in ids for n in range(1, 9)]
