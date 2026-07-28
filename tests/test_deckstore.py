"""本地卡组存储 v2（db/deckstore.py）与卡组构筑/战前选卡流程（client/deckbuilder.py）测试。"""
import pytest

from client import deckbuilder
from db import deckcode, deckstore
from tests import factories as F


def mk_groups(db, sids=None):
    sids = list(sids or F.TEAM)
    return deckcode.group_deck(db, sids, F.deck_of(*sids))


def mk_code(db, sids=None) -> str:
    return deckcode.encode_deck(mk_groups(db, sids))


def mk_entry(db, name="x", sids=None) -> dict:
    return {"name": name, "groups": mk_groups(db, sids)}


def feed(monkeypatch, lines):
    it = iter(lines)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError  # 序列耗尽 = 用户关闭输入（管理循环据此退出）
    monkeypatch.setattr("builtins.input", _input)


# ---------- deckstore 读写 ----------

def test_store_roundtrip(db, tmp_path):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "快攻"), mk_entry(db, "控制")], p)
    decks = deckstore.load_decks(db, p)
    assert [d["name"] for d in decks] == ["快攻", "控制"]
    assert all(d["standard"] for d in decks)  # 加载时重新校验
    assert decks[0]["groups"] == [[sid, cs] for sid, cs in mk_groups(db)]


def test_store_missing_file(db, tmp_path):
    assert deckstore.load_decks(db, tmp_path / "decks.json") == []


def test_store_malformed_file_deleted(db, tmp_path, capsys):
    """文件数据不符合应有格式：提示异常并删除文件。"""
    for raw in ("not json",
                '{"version": 1, "decks": [{"name": "x", "code": "y"}]}',  # 旧格式
                '{"version": 2, "decks": [["yes", {"name": "x", "groups": []}]]}',
                '{"version": 2, "decks": [[true, {"name": 1, "groups": []}]]}'):
        p = tmp_path / "decks.json"
        p.write_text(raw, encoding="utf-8")
        assert deckstore.load_decks(db, p) == []
        assert not p.exists()
        assert "本地卡组文件异常" in capsys.readouterr().out


def test_non_standard_deck_flag(db, tmp_path):
    """结构合法但不满足天梯规则的卡组：保留但 is_standard=False。"""
    p = tmp_path / "decks.json"
    bad = {"name": "三人队", "groups": mk_groups(db, F.TEAM[:3])}
    deckstore.save_decks(db, [bad, mk_entry(db, "好")], p)
    decks = deckstore.load_decks(db, p)
    assert [d["standard"] for d in decks] == [False, True]


# ---------- 战前选卡 ----------

def test_choose_deck_from_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "我的卡组")], p)
    feed(monkeypatch, ["1"])
    ids, cards, got = deckbuilder.choose_deck(db, "玩家A", p)
    assert got == mk_code(db) and ids == list(F.TEAM) and cards == F.deck_of(*F.TEAM)


def test_choose_deck_rejects_non_standard(db, tmp_path, monkeypatch, capsys):
    """所选卡组不满足对战模式规则：提示并重新选择。"""
    p = tmp_path / "decks.json"
    bad = {"name": "三人队", "groups": mk_groups(db, F.TEAM[:3])}
    deckstore.save_decks(db, [bad, mk_entry(db, "合法")], p)
    feed(monkeypatch, ["1", "2"])  # 先选不合法者 → 重选
    ids, cards, got = deckbuilder.choose_deck(db, "玩家A", p)
    assert "不满足当前对战模式" in capsys.readouterr().out
    assert got == mk_code(db)


def test_choose_deck_custom_rules(db, tmp_path, monkeypatch):
    """对战模式参数：自定义 DeckRules 下原"不合法"卡组可被接受。"""
    from db.deck import DeckRules
    p = tmp_path / "decks.json"
    deck = F.deck_of(*F.TEAM)
    for sid in F.TEAM:
        deck.remove(sid * 100 + 4)  # 每名式神 7 张
    short = {"name": "少牌队",
             "groups": deckcode.group_deck(db, list(F.TEAM), deck)}
    # 每人 7 张：天梯不合法（选择会要求重选），cards_per_shikigami=7 模式下合法
    deckstore.save_decks(db, [short], p)
    feed(monkeypatch, ["1"])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p,
                                            DeckRules(cards_per_shikigami=7))
    assert len(cards) == 28


def test_choose_deck_invalid_slot_falls_back(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db)], p)
    feed(monkeypatch, ["9"])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert (ids, cards) == deckcode.default_deck(db)


def test_choose_deck_empty_store(db, tmp_path, monkeypatch):
    """卡组文件为空：回退到卡组码输入（回车 = 默认卡组）。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, [mk_code(db)])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert ids == list(F.TEAM) and cards == F.deck_of(*F.TEAM)
    feed(monkeypatch, [""])
    ids, cards, _ = deckbuilder.choose_deck(db, "玩家A", p)
    assert (ids, cards) == deckcode.default_deck(db)


# ---------- 构筑（槽位管理） ----------

def test_deckbuilder_new_via_code(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    code = mk_code(db)
    feed(monkeypatch, ["", "快攻队", code])  # 新建 → 命名 → 卡组码导入
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "快攻队" and decks[0]["standard"]
    assert deckstore.entry_code(decks[0]) == code


def test_deckbuilder_edit_slot(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    new = mk_code(db)
    feed(monkeypatch, ["1", "新名", new])
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "新名" and deckstore.entry_code(decks[0]) == new


def test_deckbuilder_edit_keep_name(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    feed(monkeypatch, ["1", "", mk_code(db)])  # 名称回车 = 沿用
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(db, p)[0]["name"] == "旧名"


def test_deckbuilder_new_interactive(db, tmp_path, monkeypatch):
    """交互式构筑：严格输入 4 名式神 + 每人恰好 8 个卡牌序号 → 自动保存。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",        # 新建 → 名称回车（自动命名）→ 交互式
                       "1 2 3 4",          # 4 名式神
                       "1 2 3 4 5 6 7 8",  # 1 号式神 8 张（8 种各 1 张）
                       "1 1 2 2 3 3 4 4",  # 2 号式神 8 张（4 种各 2 张）
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])                # 编辑循环：回车完成
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert len(decks) == 1 and decks[0]["standard"]
    ids, cards = deckstore.entry_deck(decks[0])
    assert ids == list(F.TEAM) and len(cards) == 32


def test_new_build_shikigami_strict(db, tmp_path, monkeypatch, capsys):
    """新建选式神：数量不符/重复/不存在都会被拒绝并要求重新输入。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",
                       "1 2 3",        # 数量不足
                       "1 1 2 3",      # 重复
                       "1 2 3 99",     # 序号不存在
                       "1 2 3 4",      # 合法
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])
    deckbuilder.run_deckbuilder(db, p)
    out = capsys.readouterr().out
    assert "须恰好输入 4 个序号" in out
    assert "式神不能重复" in out
    assert "序号不存在" in out
    assert deckstore.load_decks(db, p)[0]["standard"]


def test_new_build_cards_strict(db, tmp_path, monkeypatch, capsys):
    """新建选牌：数量不符/序号不存在/同种卡超 2 张都会被拒绝并要求重新输入。"""
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "", "",
                       "1 2 3 4",
                       "1 2 3",              # 数量不足
                       "1 2 3 4 5 6 7 99",   # 序号不存在
                       "1 1 1 2 3 4 5 6",    # 同种卡 3 张
                       "1 2 3 4 5 6 7 8",    # 合法
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       "1 2 3 4 5 6 7 8",
                       ""])
    deckbuilder.run_deckbuilder(db, p)
    out = capsys.readouterr().out
    assert out.count("须恰好输入 8 个序号") == 1
    assert "序号不存在" in out
    assert "同种卡至多 2 张" in out
    assert deckstore.load_decks(db, p)[0]["standard"]


def test_deckbuilder_rename(db, tmp_path, monkeypatch):
    """槽位重命名：r <序号> <新名称>。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧名")], p)
    feed(monkeypatch, ["r 1 新名字"])
    deckbuilder.run_deckbuilder(db, p)
    decks = deckstore.load_decks(db, p)
    assert decks[0]["name"] == "新名字" and decks[0]["standard"]


def test_deckbuilder_bad_code_not_saved(db, tmp_path, monkeypatch):
    p = tmp_path / "decks.json"
    feed(monkeypatch, ["", "x", "garbage-code"])
    deckbuilder.run_deckbuilder(db, p)
    assert deckstore.load_decks(db, p) == []


# ---------- 增量编辑 ----------

def test_edit_single_shikigami_cards(db, tmp_path, monkeypatch):
    """编辑现有卡组：只改 1 号式神的卡牌（改为 8 种各 1 张），其余不动。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1 → 沿用名 → 交互式编辑
                       "1",               # 编辑 1 号式神卡牌
                       "1 2 3 4 5 6 7 8",  # 改选全部 8 种
                       "1=1 2=1 3=1 4=1",  # 原 4 种由 ×2 调为 ×1（5-8 默认 1 张）
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert ids == list(F.TEAM)
    own = sorted(c for c in cards if c // 100 == 100101)
    assert own == [10010100 + n for n in range(1, 9)]
    # 其余式神仍是 4 种 ×2
    assert sorted(c for c in cards if c // 100 == 100102) == F.deck_of(100102)


def test_edit_change_shikigami_clears_cards(db, tmp_path, monkeypatch):
    """更换式神：清空其已选卡牌并立即重新选牌；其余式神不动。"""
    db.shikigami[100105] = F.shiki(100105)
    for n in range(1, 9):
        db.cards[10010500 + n] = F.card(10010500 + n, shikigami=100105)
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",       # 编辑槽位 1
                       "h 1",            # 更换 1 号式神
                       "1",               # 备选池只有 100105
                       "1 2 3 4 5 6 7 8",  # 新式神选全部 8 种
                       "",                # 每种 1 张
                       ""])               # 完成
    deckbuilder.run_deckbuilder(db, p)
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert 100105 in ids and 100101 not in ids
    assert sorted(c for c in cards if c // 100 == 100105) == \
        [10010500 + n for n in range(1, 9)]


def test_edit_invalid_keeps_editing(db, tmp_path, monkeypatch, capsys):
    """完成时校验不通过：打印错误并留在编辑循环，修正后可保存。"""
    p = tmp_path / "decks.json"
    deckstore.save_decks(db, [mk_entry(db, "旧")], p)
    feed(monkeypatch, ["1", "", "",
                       "1", "1 2 3", "",  # 1 号式神只留 3 种各 1 张（3 张，不合法）
                       "",                # 完成 → 校验失败，继续编辑
                       "1", "1 2 3 4", "1=2 2=2 3=2 4=2",  # 修回 4 种 ×2
                       ""])               # 完成 → 通过
    deckbuilder.run_deckbuilder(db, p)
    assert "卡组暂不合法" in capsys.readouterr().out
    ids, cards = deckstore.entry_deck(deckstore.load_decks(db, p)[0])
    assert sorted(c for c in cards if c // 100 == 100101) == F.deck_of(100101)
