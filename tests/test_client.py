"""client 层测试：CLI 场况渲染（座次配色、修饰状态显示、关键字中文化、手牌修饰显示）
（原 test_cli.py）+ TUI 基座与状态栏文本（原 test_tui.py）+ 调试指令（原 test_debug.py）。

直接调用 client.cli.render(game)；颜色开关经 monkeypatch 设置 textutil.USE_COLOR。
角色位约定同 factories.base_db：0-3 号位 = 100101-100104（显示名 式神1001xx）。
pytest 的 stdin 为管道（非 TTY），tui.prompt 自动回退内置 input——这也是全部
既有测试不受 prompt_toolkit 影响的保证。
"""
import builtins
import re

import pytest

from client import cli, textutil, tui
from client.net import _fmt_timer
from client.textutil import display_width
from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.conftest import feed
from tests.factories import give

T = F.T

ANSI = re.compile(r"\033\[\d+m")


# ==========================================================================
# CLI 场况渲染（原 test_cli.py）
# ==========================================================================

@pytest.fixture
def color_on(monkeypatch):
    monkeypatch.setattr(textutil, "USE_COLOR", True)
    return True


@pytest.fixture
def color_off(monkeypatch):
    monkeypatch.setattr(textutil, "USE_COLOR", False)
    return True


# ---------- 座次配色 ----------

def test_seat_colors_active_player_only(db, make_game, color_on):
    """己方场上式神名按座次 1-4 着亮黄/青/紫/红；敌方行不着色。"""
    g = make_game()
    out = cli.render(g)
    for i, code in enumerate(cli.SEAT_COLORS):
        lines = [l for l in out.splitlines() if f"式神{100101 + i}" in l]
        assert len(lines) == 2                       # 双方各一行（同 db）
        colored = [l for l in lines if "\033[" in l]
        assert len(colored) == 1                     # 仅己方（active=0）行着色
        assert f"\033[{code}m" in colored[0]


def test_hand_card_colored_by_owner_seat(db, make_game, color_on):
    """己方手牌卡牌名按所属式神座次着色。"""
    g = make_game()
    for cid, code in zip((10010101, 10010201, 10010301, 10010401), cli.SEAT_COLORS):
        give(g, 0, cid)
        out = cli.render(g)
        assert f"\033[{code}m【卡{cid}】" in out


def test_hand_stats_labels(db, make_game):
    """手牌数值段：战斗牌战力/护甲（含已装配增强）、形态身材、觉醒永久身材。"""
    db.cards[10010161] = F.card(
        10010161, card_type="combat", token=True,
        steps=[F.Step(op="buff_power", amount={"enhance": True, "base": 1},
                      target=T(kind="self")),
               F.Step(op="gain_shield", amount=2, target=T(kind="self"))])
    db.cards[10010162] = F.card(
        10010162, card_type="form", form_power=5, form_health=9, token=True)
    db.cards[10010163] = F.card(
        10010163, subtype="awaken", token=True,
        steps=[F.Step(op="buff_power", amount=1, perm=True, target=T(kind="self")),
               F.Step(op="buff_health", amount=2, perm=True, target=T(kind="self"))])
    g = make_game()
    c1 = give(g, 0, 10010161)
    c1.mods["enhance"] = 2
    give(g, 0, 10010162)
    give(g, 0, 10010163)
    out = cli.render(g)
    assert "战力+3" in out   # base 1 + 已装配增强 2
    assert "护甲+2" in out
    assert "身材5/9" in out
    assert "觉醒+1/+2" in out


def test_color_off_when_disabled(db, make_game, color_off):
    """关闭颜色（管道/NO_COLOR）时输出不含任何 ANSI 序列。"""
    g = make_game()
    give(g, 0, 10010101)
    out = cli.render(g)
    assert "\033[" not in out


def test_mulligan_shows_first_second_and_seats(db, make_game, monkeypatch, capsys):
    """调度阶段：每位玩家调度前显示自己的先后手与四名式神座位顺序。"""
    def no_input(prompt=""):
        raise EOFError  # 等价于直接 done
    monkeypatch.setattr("builtins.input", no_input)
    g = make_game(mulligan=True)
    cli.run_mulligan(g)
    out = capsys.readouterr().out
    assert "A（先手）座位：" in out
    assert "B（后手）座位：" in out
    assert "1.式神100101" in out and "4.式神100104" in out


def test_mulligan_hand_uses_battle_format(db, make_game, monkeypatch, capsys):
    """调度阶段手牌与回合内同一逐行格式（含 uid/类型/等级/费用），
    但顺序保持手牌实际顺序（不调 hand_sorted）。"""
    def no_input(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_input)
    g = make_game(mulligan=True)
    cli.run_mulligan(g)
    out = capsys.readouterr().out
    assert re.search(r"\[1\] 【卡\d+】 #\d+ 法术 等级\d 费用\d", out)
    # 序号与 p.hand 实际顺序一一对应（调度输入按此序号索引）
    first = g.state.players[0].hand[0] if g.state.players[0].hand else None
    assert first is None or f"【{g.db.cards[first.id].name}】" in out.splitlines()[
        next(i for i, l in enumerate(out.splitlines()) if "A 手牌" in l) + 1]


def test_color_does_not_break_alignment(db, make_game, monkeypatch):
    """颜色不影响排版：开色输出剥离 ANSI 后与关色输出逐行相等。"""
    g = make_game()
    give(g, 0, 10010201)
    monkeypatch.setattr(textutil, "USE_COLOR", True)
    colored = cli.render(g)
    monkeypatch.setattr(textutil, "USE_COLOR", False)
    plain = cli.render(g)
    assert ANSI.sub("", colored) == plain


# ---------- 修饰状态显示 ----------

def test_modifier_status_display(db, make_game, color_off):
    """倒计时/战力/保甲/延迟能力/鼓舞均在场况中显示。"""
    g = make_game()
    p = g.state.players[0]
    s = p.shikigami[1]
    s.level = 1
    s.countdown = 2
    s.combat_power = 3
    s.keep_shield = True
    s.delayed.append({"block": None, "chosen": None, "uses": 1})
    p.assault_boosts.append({"power": 3, "shield": 3})
    out = cli.render(g)
    assert "倒计时2" in out
    assert "战力+3" in out
    assert "保甲" in out
    assert "延迟×1" in out
    assert "鼓舞+3/3" in out


# ---------- 关键字显示 ----------

def test_keyword_labels_translated(db, make_game, color_off):
    """关键字显示中文化（激怒）；引擎级关键字 keep_attack_buffs 不显示。"""
    g = make_game()
    p = g.state.players[0]
    p.shikigami[0].level = 1
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 0, "shikigami": 0}, "keyword": "enraged"}})
    g.apply({"op": "debug_grant_keyword", "args": {
        "target": {"player": 0, "shikigami": 0}, "keyword": "keep_attack_buffs"}})
    out = cli.render(g)
    assert "[激怒]" in out
    assert "enraged" not in out
    assert "keep_attack_buffs" not in out


# ---------- 手牌修饰显示 ----------

def test_hand_mods_display(db, make_game, color_off):
    """手牌实例修饰：费用修正、增强数值、附加关键字（中文化）。"""
    g = make_game()
    c = give(g, 0, 10010101)          # 空白法术：费用 1、无关键字
    c.mods["cost_delta"] = -1
    c.mods["enhance"] = 2
    c.mods["keywords_add"] = ["fast"]
    out = cli.render(g)
    line = next(l for l in out.splitlines() if f"#{c.uid}" in l)
    assert "费用0" in line
    assert "增强+2" in line
    assert "[瞬发]" in line


# ---------- 卡组管理界面 / 战后流程 ----------

def _store_entries(db):
    from db import deckcode
    groups = deckcode.group_deck(db, list(F.TEAM), F.deck_of(*F.TEAM))
    return [{"name": "甲", "groups": groups},
            {"name": "乙", "groups": groups}]


def test_deckbuilder_delete_cancel_then_confirm(db, monkeypatch, capsys, tmp_path):
    """d <序号>：二次确认；取消保留、y 删除并写回文件。"""
    from client import deckbuilder
    from db import deckstore
    store = tmp_path / "decks.json"
    deckstore.save_decks(db, _store_entries(db), store)
    feed(monkeypatch, ["d 2", "n", "d 1", "y", "q"])
    deckbuilder.run_deckbuilder(db, store_path=store)
    out = capsys.readouterr().out
    assert "已取消删除" in out
    assert "卡组「甲」已删除" in out
    remaining = deckstore.load_decks(db, store)
    assert [d["name"] for d in remaining] == ["乙"]


def test_deckbuilder_delete_invalid_slot(db, monkeypatch, capsys, tmp_path):
    """d <序号>：空槽/越界序号提示并留在管理界面，文件不变。"""
    from client import deckbuilder
    from db import deckstore
    store = tmp_path / "decks.json"
    deckstore.save_decks(db, _store_entries(db), store)
    feed(monkeypatch, ["d 9", "q"])
    deckbuilder.run_deckbuilder(db, store_path=store)
    out = capsys.readouterr().out
    assert "序号有误" in out
    assert len(deckstore.load_decks(db, store)) == 2


def test_deckbuilder_save_returns_to_manager(db, monkeypatch, capsys, tmp_path):
    """编辑保存成功后回到卡组管理界面（标题再次出现），而非直接回主菜单。"""
    from client import deckbuilder
    from db import deckstore
    store = tmp_path / "decks.json"
    deckstore.save_decks(db, _store_entries(db), store)
    # 编辑槽位 1：沿用名称 → 不导入卡组码 → 编辑循环回车完成 → 保存 → q 退出
    feed(monkeypatch, ["1", "", "", "", "q"])
    deckbuilder.run_deckbuilder(db, store_path=store)
    out = capsys.readouterr().out
    assert "已保存" in out
    assert out.count("—— 卡组构筑") == 2     # 进入一次 + 保存后回管理界面一次


def test_run_battle_shows_result_and_waits(db, make_game, monkeypatch, capsys):
    """热坐对局结束：显示最终场况（含胜负）并等待回车确认后才返回主菜单。"""
    g = make_game()
    g.state.winner = 0
    monkeypatch.setattr(cli, "new_game", lambda *a, **k: g)
    monkeypatch.setattr(cli, "_choose_deck", lambda db_, label: ([], []))
    prompts = []

    def _input(prompt=""):
        prompts.append(prompt)
        return ""
    monkeypatch.setattr("builtins.input", _input)
    cli.run_battle(db)
    out = capsys.readouterr().out
    assert "获胜" in out
    assert prompts == ["按 Enter 返回主菜单 > "]  # 战后恰好一次确认，随后返回


# ==========================================================================
# TUI 基座（client/tui.py）与状态栏文本（原 test_tui.py）
# ==========================================================================

@pytest.fixture(autouse=True)
def _clean_status():
    yield
    tui.set_status(None)  # 状态栏回调是全局量，测试间清理


# ---------- 状态栏渲染（两段） ----------

def test_toolbar_left_right_aligned():
    tui.set_status(lambda: ("左", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar == "左" + " " * 16 + "右"
    assert display_width(bar) == 20


def test_toolbar_cjk_width():
    """CJK 字符按显示宽度 2 计算对齐。"""
    tui.set_status(lambda: ("甲乙丙", "回合"))
    bar = tui.render_toolbar(width=20)
    assert bar == "甲乙丙" + " " * 10 + "回合"
    assert display_width(bar) == 20


def test_toolbar_truncates_left_keeps_right():
    """超宽时截断左段，右段优先完整保留。"""
    tui.set_status(lambda: ("一二三四五六七八九十", "右"))
    bar = tui.render_toolbar(width=10)
    assert bar.endswith("右")
    assert display_width(bar) <= 10
    assert "十" not in bar


def test_toolbar_empty_without_status():
    assert tui.render_toolbar(width=20) == ""


# ---------- 状态栏渲染（三段） ----------

def test_toolbar_three_segments_centered():
    """三段：左左对齐、中居中、右右对齐。"""
    tui.set_status(lambda: ("AA", "MM", "RR"))
    bar = tui.render_toolbar(width=30)
    assert bar == "AA" + " " * 12 + "MM" + " " * 12 + "RR"
    assert display_width(bar) == 30
    assert bar.index("MM") == (30 - 2) // 2  # 中段居中


def test_toolbar_three_segments_cjk_mid():
    tui.set_status(lambda: ("左", "回合", "右"))
    bar = tui.render_toolbar(width=30)
    assert bar.startswith("左") and bar.endswith("右")
    assert display_width(bar) == 30
    assert display_width(bar[:bar.index("回合")]) == (30 - 4) // 2  # CJK 按宽度 2 居中


def test_toolbar_three_segments_truncates_left_keeps_mid_right():
    """超宽时优先保中段与右段、截断左段。"""
    tui.set_status(lambda: ("一二三四五六七八九十", "中", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar.endswith("右") and "中" in bar
    assert display_width(bar) <= 20
    assert "九十" not in bar


def test_toolbar_no_raw_ansi():
    """状态栏纯文本不含未解析的 ANSI 转义（回调返回纯文本时）。"""
    tui.set_status(lambda: ("左", "中", "右"))
    assert "\x1b" not in tui.render_toolbar(width=30)


# ---------- 非 TTY 回退 ----------

def test_prompt_falls_back_to_builtin_input(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "hello")
    assert tui.prompt("> ") == "hello"
    assert tui._session is None  # 非 TTY 不创建 PromptSession（无 import 副作用）


# ---------- 牌手信息段 ----------

def test_player_segments(make_game):
    game = make_game()
    p0, p1 = game.state.players
    own, opp = cli.player_segments(game)  # 热坐：己方 = 当前行动方（players[0] 先手）
    assert own.startswith(f"> {p0.name} 生命{p0.health}")   # `>` 标行动方
    assert opp.startswith(f"  {p1.name} 生命{p1.health}")
    assert f"手牌{len(p0.hand)} 牌库{len(p0.deck)} 墓地{len(p0.graveyard)}" in own
    assert "（你）" not in own + opp
    own_v, opp_v = cli.player_segments(game, viewer=1)  # 联机：己方 = viewer
    assert f"{p1.name}（你）" in own_v and "（你）" not in opp_v


def test_battle_status_three_segments(make_game):
    """热坐状态栏：三段（己方 / 回合 / 敌方），中段为回合文本。"""
    game = make_game()
    left, mid, right = cli._battle_status(game)
    assert left.startswith(">")
    assert "回合" in mid and "行动中" in mid
    assert right.startswith("  ")


# ---------- 倒计时格式化 ----------

def test_fmt_timer():
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 95}, 100.0) == "⏱ 1:35"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0 + 9}, 100.0) == "⏱ 0:09"
    assert _fmt_timer({"kind": "mulligan", "deadline": 100.0 + 27}, 100.0) == "调度 ⏱ 0:27"
    assert _fmt_timer({"kind": "turn", "deadline": 100.0}, 130.0) == "⏱ 0:00"  # 超时封顶


# ==========================================================================
# 调试指令（原 test_debug.py）
# ==========================================================================

def test_debug_give_card_to_hand(db, make_game):
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "count": 2}})
    assert len(a.hand) == before + 2
    assert all(c.id == 10010101 for c in a.hand[-2:])


def test_debug_give_card_to_graveyard(db, make_game):
    g = make_game()
    a = g.state.players[0]
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "zone": "graveyard"}})
    assert a.graveyard[-1].id == 10010101


def test_debug_set_stat_shikigami(db, make_game):
    g = make_game()
    s = g.state.players[0].shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "health", "value": 1}})
    assert s.health == 1
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "level", "value": 3}})
    assert s.level == 3


def test_debug_set_stat_player(db, make_game):
    g = make_game()
    a = g.state.players[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0}, "key": "orb", "value": 9}})
    assert a.orb == 9


def test_debug_set_stat_bool(db, make_game):
    g = make_game()
    s = g.state.players[0].shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "defeated", "value": True}})
    assert s.defeated is True


def test_debug_play_card_bypass_cost_and_level(db, make_game):
    """debug_play_card 跳过费用、等级、目标合法性检查。"""
    cid = 10010152
    db.cards[cid] = F.card(cid, steps=[F.dmg(5)], target=F.T(kind="choose", pool="enemy_shikigami"), token=True)
    g = make_game()
    a = g.state.players[0]
    a.orb = 0
    c = give(g, 0, cid)
    # 正常打出会因鬼火不足失败
    with pytest.raises(IllegalAction):
        g.apply({"op": "play_card", "uid": c.uid, "target": Ref(player=1, shikigami=0)})
    # 调试指令强制打出
    g.apply({"op": "debug_play_card", "args": {"player": 0, "uid": c.uid, "target": {"player": 1, "shikigami": 0}}})
    assert g.state.players[1].shikigami[0].defeated is True  # 5 点伤害超过 4 血
    assert g.state.players[1].shikigami[0].health == 0       # 气绝后 health 被置 0
    assert c in a.graveyard


def test_debug_assault_bypass_checks(db, make_game):
    g = make_game()
    a = g.state.players[0]
    a.orb = 0
    a.assaults_left = 0
    # 正常出击因 0 火/0 次数失败
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    # 调试强制出击打脸
    g.apply({"op": "debug_assault", "args": {"player": 0, "index": 0}})
    assert g.state.players[1].shield == 2  # 5 - 3


def test_debug_draw(db, make_game):
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    deck_before = len(a.deck)
    g.apply({"op": "debug_draw", "args": {"player": 0, "count": 2}})
    assert len(a.hand) == before + 2
    assert len(a.deck) == deck_before - 2


def test_debug_set_turn(db, make_game):
    g = make_game()
    g.apply({"op": "debug_set_turn", "args": {"active": 1, "turn": 10}})
    assert g.state.active == 1
    assert g.state.turn == 10


def test_debug_unknown_command(db, make_game):
    g = make_game()
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_foobar", "args": {}})


def test_debug_disabled(db, make_game):
    g = make_game()
    g.state.config.enable_debug_commands = False
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_draw", "args": {"player": 0, "count": 1}})


# ==========================================================================
# 结算明细通道（settle_log 记录 + drain_settle 空闲点打印）
# ==========================================================================

def test_settle_log_channels(db, make_game):
    """结算明细通道：回合阶段/升级/力量/战力/护甲/伤害与战斗、伤害结算的
    开始结束分类入账（引擎只记录，不打印）。"""
    g = make_game(auto_skip_upgrade=False)
    pa, pb = F.battle_setup(g)
    slog = g.state.settle_log
    assert any("—— 回合开始阶段（A" in x for x in slog)
    g.apply({"op": "upgrade", "index": 1})
    assert any("【升级】A 的式神100102升至 1 级" in x for x in slog)
    cid = 10010151
    db.cards[cid] = F.card(
        cid, steps=[F.Step(op="buff_power", amount=2, target=T(kind="self"))],
        token=True)
    F.play(g, 0, cid)
    assert any("【力量】式神100101 临时力量 +2" in x for x in slog)
    c2 = 10010152
    db.cards[c2] = F.card(
        c2, card_type="combat",
        steps=[F.Step(op="buff_power", amount=2, target=T(kind="self")),
               F.Step(op="gain_shield", amount=1, target=T(kind="self"))],
        token=True)
    F.play(g, 0, c2)
    assert any("【战力】式神100101 战力 +2" in x for x in slog)
    assert any("【护甲】式神100101 获得 1 点护甲" in x for x in slog)
    assert any("—— 战斗开始：式神100101 ——" in x for x in slog)
    assert any("—— 战斗结束 ——" in x for x in slog)
    assert any("—— 伤害结算开始 ——" in x for x in slog)
    assert any("—— 伤害结算结束 ——" in x for x in slog)
    assert any("【伤害】B 受到 7 点伤害（生命 30→23）" in x for x in slog)


def test_drain_settle_increment_and_blank_lines(db, make_game, capsys):
    """drain_settle：按游标增量打印（0 间隔测试模式），整块前后各空一行，
    无新增明细时不输出、游标不动。"""
    g = make_game()
    pa, pb = F.battle_setup(g)
    seen = cli.drain_settle(g, 0, interval=0)
    out = capsys.readouterr().out
    assert seen == len(g.state.settle_log) and seen > 0
    assert out.startswith("\n") and out.endswith("\n\n")
    assert "回合开始阶段" in out
    seen2 = cli.drain_settle(g, seen, interval=0)
    assert seen2 == seen
    assert capsys.readouterr().out == ""


# ==========================================================================
# 目标编号（1 基翻译层）、结算明细排版与双通道去重、联机提示即时性
# ==========================================================================

def test_target_code_one_based_numbering():
    """主动目标编号与场况座次一致（1 基）：s=己方（兼容 f/无前缀裸数字）e=敌方；
    0=牌手，1-4=座次式神，5=召唤物；引擎内部式神下标 0 基，翻译层 ±1 转换。"""
    assert cli.parse_ref("e0", 0) == Ref(player=1)
    assert cli.parse_ref("s0", 0) == Ref(player=0)
    assert cli.parse_ref("sp", 0) == Ref(player=0)               # p 兼容
    assert cli.parse_ref("e1", 0) == Ref(player=1, shikigami=0)
    assert cli.parse_ref("E4", 0) == Ref(player=1, shikigami=3)
    assert cli.parse_ref("s5", 0) == Ref(player=0, shikigami=4)
    assert cli.parse_ref("f2", 0) == Ref(player=0, shikigami=1)  # f 兼容
    assert cli.parse_ref("2", 0) == Ref(player=0, shikigami=1)   # 无前缀 = 己方
    assert cli.ref_code(Ref(player=1), 0) == "e0"
    assert cli.ref_code(Ref(player=1, shikigami=2), 0) == "e3"
    assert cli.ref_code(Ref(player=0, shikigami=0), 0) == "s1"
    assert cli.ref_code(Ref(player=0), 0) == "s0"


def test_format_settle_lines_nesting():
    """结算明细排版：战斗/伤害结算的开始-结束块按层级缩进两格，结束行与开始行
    同级；阶段分隔行不缩进不计层级。"""
    lines = [
        "—— 回合开始阶段（A 的第 1 回合）——",
        "—— 战斗开始：式神100101 ——",
        "【战力】式神100101 战力 +2（本次战斗）",
        "—— 伤害结算开始 ——",
        "【伤害】B 受到 7 点伤害（生命 30→23）",
        "—— 伤害结算结束 ——",
        "—— 战斗结束 ——",
        "【升级】A 的式神100102升至 1 级",
    ]
    assert cli.format_settle_lines(lines) == [
        "—— 回合开始阶段（A 的第 1 回合）——",
        "—— 战斗开始：式神100101 ——",
        "  【战力】式神100101 战力 +2（本次战斗）",
        "  —— 伤害结算开始 ——",
        "    【伤害】B 受到 7 点伤害（生命 30→23）",
        "  —— 伤害结算结束 ——",
        "—— 战斗结束 ——",
        "【升级】A 的式神100102升至 1 级",
    ]


def test_settle_numeric_events_not_duplicated_in_log(db, make_game):
    """数值类事件（伤害等）只记 settle 明细通道、不再写 log 孪生行——
    联机端同屏打印两通道时不重复。"""
    g = make_game(auto_skip_upgrade=False)
    pa, pb = F.battle_setup(g)
    g.apply({"op": "upgrade", "index": 1})
    slog_before, log_before = len(g.state.settle_log), len(g.state.log)
    cid = 10010153
    db.cards[cid] = F.card(
        cid, card_type="combat",
        steps=[F.Step(op="buff_power", amount=2, target=T(kind="self"))],
        token=True)
    F.play(g, 0, cid)  # 战斗牌 → 交战伤害
    assert any("【伤害】" in x for x in g.state.settle_log[slog_before:])
    assert not any("点伤害（剩余生命" in x for x in g.state.log[log_before:])


def test_net_send_cmd_waits_for_reply(db):
    """联机发指令后等待服务端回推（state/error）再返回——随后的输入提示
    （升级阶段/回合归属）基于最新已应用状态，不慢一个阶段。"""
    import threading
    import time

    from client.net import NetClient

    class FakeWS:
        def __init__(self):
            self.sent = []

        def send(self, raw):
            self.sent.append(raw)

    c = NetClient(db, FakeWS(), "甲")
    threading.Timer(0.1, lambda: c.handle({"type": "error", "reason": "x"})).start()
    t0 = time.monotonic()
    c.send_cmd({"op": "end_turn"})
    assert 0.05 <= time.monotonic() - t0 < 1.0  # 回推到达即解除等待
    assert len(c.ws.sent) == 1


def test_net_status_phase_hint(db, make_game):
    """联机状态栏中段即时反映最新阶段：己方升级阶段含剩余次数、
    主要阶段=你的回合、非己方=对手行动中。"""
    from client.net import NetClient, _net_status
    g = make_game(auto_skip_upgrade=False)
    pa, pb = F.battle_setup(g)
    c = NetClient(db, None, "甲")
    c.payload = g.state.model_dump(mode="json")
    c.me = 0
    _, mid, _ = _net_status(c)
    assert "升级阶段（剩" in mid
    c.me = 1
    _, mid, _ = _net_status(c)
    assert "对手行动中" in mid
