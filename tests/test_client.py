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


def test_foreign_shikigami_hand_card_neutral_color(db, make_game, color_on):
    """外来式神手牌（所属式神不在己方队伍四座次内，如记仇复制敌方法术后
    生成的牌）与中立牌一致：不着座次色、不特殊标记；队伍内牌仍着座次色。"""
    g = make_game()
    db.cards[10020151] = F.card(10020151, shikigami=100201, token=True)  # 所属不在队伍
    db.cards[10000052] = F.card(10000052, shikigami=None, token=True)     # 中立牌
    give(g, 0, 10010101)
    give(g, 0, 10020151)
    give(g, 0, 10000052)
    out = cli.render(g)
    for cid in (10020151, 10000052):
        line = next(l for l in out.splitlines() if f"【卡{cid}】" in l)
        assert "\033[" not in line
    assert f"\033[{cli.SEAT_COLORS[0]}m【卡10010101】" in out


# ---------- 派系显示分界（原版派系概念自四相琉璃 20210330 才引入）----------

def test_faction_display_env_boundary(db, make_game, color_off):
    """对局场况派系列：env_date < 20210330 整列不显示；None（最新）与
    >= 分界日期正常显示（含对齐列不残留）。"""
    from db.envs import FACTION_DISPLAY_MIN_DATE, show_faction
    assert not show_faction(20200327)          # 不夜之火（当前最晚环境别名）
    assert show_faction(FACTION_DISPLAY_MIN_DATE) == show_faction(20210330)
    assert show_faction(None)                  # 最新数据
    g = make_game()
    for env in (None, FACTION_DISPLAY_MIN_DATE):
        out = cli.render(g, env_date=env)
        assert "[红莲]" in out and "[紫岩]" in out and "[无相]" in out
    hidden = cli.render(g, env_date=20200327)
    assert "[红莲]" not in hidden and "[紫岩]" not in hidden
    assert "[无相]" not in hidden
    line = next(l for l in hidden.splitlines() if "式神100101" in l)
    assert re.search(r"Lv\d+\s+攻", line)      # 派系列整列移除（等级后直跟状态）


def test_deckbuilder_faction_display_by_env(db, capsys):
    """构筑式神列表与卡组详情：四相琉璃前环境隐藏派系列（含分隔符不残留），
    之后环境正常显示。"""
    from client import deckbuilder
    defs = [db.shikigami[s] for s in F.TEAM]
    deckbuilder._print_shikigami(defs, show_faction=False)
    out = capsys.readouterr().out
    assert "红莲" not in out and "紫岩" not in out
    deckbuilder._print_shikigami(defs, show_faction=True)
    out = capsys.readouterr().out
    assert "红莲" in out and "紫岩" in out
    picks = {s: [] for s in F.TEAM}
    deckbuilder._print_deck(db, F.TEAM, picks, show_faction=False)
    assert "红莲" not in capsys.readouterr().out
    deckbuilder._print_deck(db, F.TEAM, picks, show_faction=True)
    assert "红莲" in capsys.readouterr().out


def test_hand_stats_labels(db, make_game):
    """手牌数值段：战斗牌力量/护甲（含已装配增强）、形态身材、觉醒永久身材。"""
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
    assert "力量+3" in out   # base 1 + 已装配增强 2
    assert "护甲+2" in out
    assert "身材5/9" in out
    assert "觉醒+1/+2" in out


def test_hand_stats_live_enhance(db, make_game):
    """手牌实时增强：持久 store（card_mods，打出时装配）未入实例也计入显示；
    法术/能力的增强效果数值（伤害/生命变为）实时求值。"""
    db.cards[10010164] = F.card(
        10010164, card_type="combat", token=True,
        steps=[F.Step(op="buff_power", amount={"enhance": True, "base": 1},
                      target=T(kind="self"))])
    db.cards[10010165] = F.card(
        10010165, card_type="spell", token=True,
        steps=[F.Step(op="damage", amount={"enhance": True, "base": 5},
                      target=T(kind="all", pool="projectile"))])
    db.cards[10010166] = F.card(
        10010166, card_type="spell", token=True,
        steps=[F.Step(op="set_health", amount={"enhance": True, "base": 10},
                      target=T(kind="all", pool="self_player"))])
    g = make_game()
    p = g.state.players[0]
    give(g, 0, 10010164)
    give(g, 0, 10010165)
    give(g, 0, 10010166)
    for cid in (10010164, 10010165, 10010166):
        p.card_mods[cid] = {"enhance": 2}
    out = cli.render(g)
    assert "力量+3" in out      # 战斗牌：base 1 + 持久增强 2（未装配也显示）
    assert "伤害7" in out       # 法术：base 5 + 持久增强 2
    assert "生命变为12" in out
    assert out.count("增强+2") == 3
    # 实例未被显示层污染（装配只发生在打出时）
    assert all("enhance" not in c.mods for c in p.hand)


def test_hand_aura_display_live(db, make_game):
    """手牌光环实时显示：卡牌光环的数值（含 ext 通道求值）与授予关键字
    在手牌数值段/关键字段即时反映（维护者定案）。"""
    db.cards[10010167] = F.card(
        10010167, card_type="combat", token=True,
        steps=[F.Step(op="buff_power", amount=1, target=T(kind="self")),
               F.Step(op="gain_shield", amount=2, target=T(kind="self"))])
    g = make_game()
    p = g.state.players[0]
    p.card_auras.append({
        "shikigami": 100101, "card_type": None, "card_id": None,
        "keywords": ["fast"], "cost_zero": False,
        "power": 0, "shield": 1, "power_ext": "x",
        "turn": None, "scope": "form", "holder": [0, 0],
    })
    p.ext["x"] = 3
    give(g, 0, 10010167)
    out = cli.render(g)
    assert "力量+4" in out      # base 1 + 光环 ext 3
    assert "护甲+3" in out      # base 2 + 光环 1
    assert "[瞬发]" in out      # 光环授予


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


def test_battle_loop_play_dual_target(db, make_game, monkeypatch, capsys):
    """双选择目标（CardDef.target2，麓鸣·灭型）：热坐出牌依次选择两个目标——
    行内参数式（play 1 s1 e1）与交互提示式（依次问"目标/第二目标"）均接通，
    cmd["target2"] 进入引擎 chosen=[主目标, 第二目标]。"""
    from client.settle import SettlePrinter
    cid = 10010152
    db.cards[cid] = F.card(
        cid, token=True,
        target=F.T(kind="choose", pool="friendly_shikigami"),
        target2=F.T(kind="choose", pool="enemy_shikigami"),
        steps=[F.Step(op="gain_shield", amount=2,
                      target=F.T(kind="choose", chosen_index=0)),
               F.dmg(2, F.T(kind="choose", chosen_index=1)),
               F.dmg(30, F.T(kind="all", pool="enemy_player"))])  # 制胜：对局结束退出循环

    def _game():
        g = make_game()
        pa, pb = F.battle_setup(g)
        pa.hand.clear()
        F.give(g, 0, cid)
        return g, pa, pb

    # 行内参数式
    g, pa, pb = _game()
    feed(monkeypatch, ["play 1 s1 e1", ""])
    printer = SettlePrinter(interval=0)
    printer.start()
    cli._battle_loop(g, printer)
    printer.stop(flush=True)
    assert pa.shikigami[0].shield == 2          # 主目标 +2 护甲
    assert pb.shikigami[0].health == 2          # 第二目标受 2 伤（4→2）

    # 交互提示式
    g, pa, pb = _game()
    feed(monkeypatch, ["play 1", "s1", "e1", ""])
    printer = SettlePrinter(interval=0)
    printer.start()
    cli._battle_loop(g, printer)
    printer.stop(flush=True)
    out = capsys.readouterr().out
    assert "可选目标: s1" in out and "可选第二目标: e1" in out
    assert pa.shikigami[0].shield == 2
    assert pb.shikigami[0].health == 2


# ==========================================================================
# TUI 基座（client/tui.py）与状态栏文本（原 test_tui.py）
# ==========================================================================

@pytest.fixture(autouse=True)
def _clean_status():
    yield
    tui.set_status(None)  # 状态栏回调是全局量，测试间清理


# ---------- 状态栏渲染（两段） ----------

def test_toolbar_two_segments():
    """两段状态栏：左右对齐、CJK 字符按显示宽度 2 计算；超宽时截断左段、右段
    优先完整保留；无状态回调时为空串。"""
    tui.set_status(lambda: ("左", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar == "左" + " " * 16 + "右"
    assert display_width(bar) == 20
    tui.set_status(lambda: ("甲乙丙", "回合"))
    bar = tui.render_toolbar(width=20)
    assert bar == "甲乙丙" + " " * 10 + "回合"      # CJK 按显示宽度 2
    assert display_width(bar) == 20
    tui.set_status(lambda: ("一二三四五六七八九十", "右"))
    bar = tui.render_toolbar(width=10)
    assert bar.endswith("右")                       # 截断左段，右段完整保留
    assert display_width(bar) <= 10
    assert "十" not in bar
    tui.set_status(None)
    assert tui.render_toolbar(width=20) == ""


# ---------- 状态栏渲染（三段） ----------

def test_toolbar_three_segments():
    """三段状态栏：左左对齐、中居中（CJK 按宽度 2 计算）、右右对齐；超宽时优先
    保中段与右段、截断左段；回调返回纯文本时不含未解析的 ANSI 转义。"""
    tui.set_status(lambda: ("AA", "MM", "RR"))
    bar = tui.render_toolbar(width=30)
    assert bar == "AA" + " " * 12 + "MM" + " " * 12 + "RR"
    assert display_width(bar) == 30
    assert bar.index("MM") == (30 - 2) // 2         # 中段居中
    tui.set_status(lambda: ("左", "回合", "右"))
    bar = tui.render_toolbar(width=30)
    assert bar.startswith("左") and bar.endswith("右")
    assert display_width(bar) == 30
    assert display_width(bar[:bar.index("回合")]) == (30 - 4) // 2  # CJK 按宽度 2 居中
    tui.set_status(lambda: ("一二三四五六七八九十", "中", "右"))
    bar = tui.render_toolbar(width=20)
    assert bar.endswith("右") and "中" in bar       # 优先保中段与右段、截断左段
    assert display_width(bar) <= 20
    assert "九十" not in bar
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


# ---------- 服务器地址规范化 ----------

def test_normalize_server_url():
    from client.net import normalize_server_url
    assert normalize_server_url("ws://a.top:1037/ws") == "ws://a.top:1037/ws"
    assert normalize_server_url("wss://a.top/ws") == "wss://a.top/ws"
    # 内网穿透/反代给出的 http(s) 网址
    assert normalize_server_url("https://a.top") == "wss://a.top/ws"
    assert normalize_server_url("http://a.top:8080") == "ws://a.top:8080/ws"
    # 裸 host[:port]：带端口默认 ws（本机/局域网），无端口默认 wss（公网域名穿透）
    assert normalize_server_url("a.top:1037") == "ws://a.top:1037/ws"
    assert normalize_server_url("  127.0.0.1:1037  ") == "ws://127.0.0.1:1037/ws"
    assert normalize_server_url("a.top") == "wss://a.top/ws"
    assert normalize_server_url("bwpro.varisox137.top") == "wss://bwpro.varisox137.top/ws"
    # 已带路径则不补 /ws
    assert normalize_server_url("wss://a.top/custom") == "wss://a.top/custom"


def test_probe_connection_retries(monkeypatch):
    """穿透提示页（HTTP 200）是来源 IP 首次请求的间歇拦截：探针自动重试至放行。"""
    import client.net as net
    calls = []

    class _FakeWs:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky_connect(url, **kw):
        calls.append(url)
        if len(calls) < 3:
            raise Exception("server rejected WebSocket connection: HTTP 200")
        return _FakeWs()

    monkeypatch.setattr("websockets.sync.client.connect", flaky_connect)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    assert net.probe_connection("wss://a.top/ws") is None
    assert len(calls) == 3
    # 持续失败：返回末次错误信息（含穿透提示）
    def always_fail(url, **kw):
        raise Exception("server rejected WebSocket connection: HTTP 200")

    monkeypatch.setattr("websockets.sync.client.connect", always_fail)
    err = net.probe_connection("wss://a.top/ws", retries=2)
    assert "HTTP 200" in err and "穿透" in err


# ==========================================================================
# 调试指令（原 test_debug.py）
# ==========================================================================

def test_debug_give_card_zones(db, make_game):
    """debug_give_card：默认入手牌（count 多张），zone 指定进墓地。"""
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "count": 2}})
    assert len(a.hand) == before + 2
    assert all(c.id == 10010101 for c in a.hand[-2:])
    g.apply({"op": "debug_give_card", "args": {"player": 0, "card_id": 10010101, "zone": "graveyard"}})
    assert a.graveyard[-1].id == 10010101


def test_debug_set_stat(db, make_game):
    """debug_set_stat：式神 health/level/defeated（布尔值）与牌手 orb 直接改写。"""
    g = make_game()
    a = g.state.players[0]
    s = a.shikigami[0]
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "health", "value": 1}})
    assert s.health == 1
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "level", "value": 3}})
    assert s.level == 3
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0, "shikigami": 0}, "key": "defeated", "value": True}})
    assert s.defeated is True
    g.apply({"op": "debug_set_stat", "args": {"target": {"player": 0}, "key": "orb", "value": 9}})
    assert a.orb == 9


def test_debug_play_and_assault_bypass_checks(db, make_game):
    """debug_play_card / debug_assault：跳过费用、等级、目标合法性与出击次数检查。"""
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
    # 正常出击因 0 火/0 次数失败；调试强制出击打脸
    a.orb = 0
    a.assaults_left = 0
    with pytest.raises(IllegalAction):
        g.apply({"op": "assault", "index": 0})
    g.apply({"op": "debug_assault", "args": {"player": 0, "index": 0}})
    assert g.state.players[1].shield == 2  # 5 - 3


def test_debug_draw_set_turn_and_guards(db, make_game):
    """debug_draw 从牌库抽 N；debug_set_turn 改写行动方与回合数；未知指令与
    未启用调试（enable_debug_commands=False）均抛 IllegalAction。"""
    g = make_game()
    a = g.state.players[0]
    before = len(a.hand)
    deck_before = len(a.deck)
    g.apply({"op": "debug_draw", "args": {"player": 0, "count": 2}})
    assert len(a.hand) == before + 2
    assert len(a.deck) == deck_before - 2
    g.apply({"op": "debug_set_turn", "args": {"active": 1, "turn": 10}})
    assert g.state.active == 1
    assert g.state.turn == 10
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_foobar", "args": {}})
    g.state.config.enable_debug_commands = False
    with pytest.raises(IllegalAction):
        g.apply({"op": "debug_draw", "args": {"player": 0, "count": 1}})


# ==========================================================================
# 结算明细通道（settle_log 记录 + SettlePrinter 队列播放）
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


def test_play_settle_enqueue_block_and_blank_lines(db, make_game, capsys):
    """_play_settle：按合并时间线游标增量入打印队列（interval=0 立即播完），整块前后
    各空一行，无新增明细时不入队。"""
    from client.settle import SettlePrinter
    g = make_game()
    pa, pb = F.battle_setup(g)
    printer = SettlePrinter(interval=0)
    printer.start()
    seen = cli._play_settle(g, 0, printer)
    printer.stop(flush=True)
    out = capsys.readouterr().out
    assert seen == len(g.state.timeline) and seen > 0
    assert out.startswith("\n") and out.endswith("\n\n")
    assert "回合开始阶段" in out
    seen2 = cli._play_settle(g, seen, printer)
    assert seen2 == seen  # 无新增明细：不入队
    printer.start()
    printer.stop(flush=True)
    assert capsys.readouterr().out == ""


def test_settle_printer_block_order_no_interleave(capsys):
    """打印队列：播放中入队的新块等当前块完整播完再播——块序保持、块间不穿插、
    flush 快速播完不略过。"""
    from client.settle import SettlePrinter
    p = SettlePrinter(interval=0.05)
    p.start()
    p.enqueue(["b1-l1", "b1-l2", "b1-l3"])
    p.enqueue(["b2-l1", "b2-l2"])  # 第一块播放中入队
    p.stop(flush=True)
    out = capsys.readouterr().out
    idx = [out.index(x) for x in ("b1-l1", "b1-l2", "b1-l3", "b2-l1", "b2-l2")]
    assert idx == sorted(idx)
    assert "已略过" not in out and p._thread is None


def test_timeline_merges_log_and_settle_in_order(db, make_game):
    """合并时间线（thoughts(1) 打印顺序修复）：叙事行与结算明细按真实发生顺序
    合流——"使用了【x】"先于其引发的结算明细；kind 标记区分两通道（s=结算 l=叙事）。"""
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=100101, level=1, token=True,
                           steps=[F.Step(op="heal", amount=2, target=T(kind="self"))])
    g = make_game()
    pa, pb = F.battle_setup(g)
    pa.shikigami[0].health = 1
    g.apply({"op": "play_card", "uid": give(g, 0, cid).uid})
    kinds = [e["k"] for e in g.state.timeline]
    msgs = [e["m"] for e in g.state.timeline]
    assert set(kinds) == {"s", "l"}
    i_use = next(i for i, m in enumerate(msgs) if "使用了【" in m)
    i_heal = next(i for i, m in enumerate(msgs) if m.startswith("【治疗】"))
    assert kinds[i_use] == "l" and kinds[i_heal] == "s"
    assert i_use < i_heal            # 触发行先于其引发的结算行


def test_result_text_by_viewer():
    """对局结果按视角（thoughts(1)）：联机自身胜利/落败/双方平局；热坐共享屏用玩家名。"""
    names = ["玩家A", "玩家B"]
    assert cli.result_text(0, names, viewer=0) == "自身胜利！"
    assert cli.result_text(0, names, viewer=1) == "自身落败……"
    assert cli.result_text(-1, names, viewer=0) == "双方平局"
    assert cli.result_text(1, names) == "玩家B 获胜！"
    assert cli.result_text(-1, names) == "双方平局"


def test_net_can_act_gates_input_by_turn(db, make_game):
    """对手回合不显示输入提示符（thoughts(1)）：_can_act 仅自己调度未完成 /
    待自己作答的结算中选择 / 自己回合为真。"""
    from client.net import NetClient
    g = make_game()
    pa, pb = F.battle_setup(g)
    c = NetClient(db, None, "me")
    c.me = 1
    assert not c._can_act(g.state)            # pa（0）行动中：对手回合
    c.me = 0
    assert c._can_act(g.state)                # 己方回合
    g.state.pending_choice = {"kind": "deck_top_pick", "player": 1,
                              "options": [1], "remaining": 1}
    assert not c._can_act(g.state)            # 待对方作答
    c.me = 1
    assert c._can_act(g.state)                # 待己作答（非己方回合也可输入）
    g.state.pending_choice = None
    g.state.phase = "mulligan"
    pb.mulligan_done = True
    assert not c._can_act(g.state)            # 已完成调度：等待对手，不提示


def test_settle_printer_discard_on_stop(capsys):
    """stop(flush=False)：队列剩余块丢弃并提示略过行数，线程退出不泄漏。"""
    from client.settle import SettlePrinter
    p = SettlePrinter(interval=0.2)
    p.start()
    p.enqueue(["slow1", "slow2", "slow3"])
    p.enqueue(["drop-me-1", "drop-me-2"])
    p.stop(flush=False)
    out = capsys.readouterr().out
    assert "已略过" in out
    assert "drop-me-2" not in out
    assert p._thread is None


# ==========================================================================
# 目标编号（1 基翻译层）、结算明细排版与双通道去重、联机提示即时性
# ==========================================================================

def test_target_code_one_based_numbering():
    """主动目标编号与场况座次一致（1 基）：侧前缀必填，s=己方 e=敌方；
    0=牌手，1-4=座次式神，5=召唤物；引擎内部式神下标 0 基，翻译层 ±1 转换。
    f/无前缀裸数字/p 兼容已移除，非法前缀直接拒绝。"""
    assert cli.parse_ref("e0", 0) == Ref(player=1)
    assert cli.parse_ref("s0", 0) == Ref(player=0)
    assert cli.parse_ref("e1", 0) == Ref(player=1, shikigami=0)
    assert cli.parse_ref("E4", 0) == Ref(player=1, shikigami=3)
    assert cli.parse_ref("s5", 0) == Ref(player=0, shikigami=4)
    for bad in ("f2", "2", "sp", "p", "0"):
        with pytest.raises(ValueError):
            cli.parse_ref(bad, 0)
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


def test_net_state_enqueues_settle_and_log_block(db, make_game, capsys):
    """联机 state 消息：settle 增量与叙事 log 合成一块入打印队列（入队即返回，
    不在接收线程 sleep）；块内 settle 在前、log 在后。"""
    from client.net import NetClient
    from client.settle import SettlePrinter
    g = make_game()
    pa, pb = F.battle_setup(g)
    printer = SettlePrinter(interval=0)
    printer.start()
    c = NetClient(db, None, "乙", printer)
    c.me = 1
    c.handle({"type": "state", "payload": g.state.model_dump(mode="json"),
              "log": ["A 使用了【测试牌】"],
              "settle": ["—— 战斗开始：式神100101 ——", "—— 战斗结束 ——"]})
    printer.stop(flush=True)
    out = capsys.readouterr().out
    assert out.index("—— 战斗开始：式神100101 ——") \
        < out.index("  | A 使用了【测试牌】")


def test_net_mulligan_shows_seats_once(db, make_game, capsys):
    """联机调度阶段：首次进入时先打印双方先后手与四座次行（与热坐同一 format_seat_line），
    且只打印一次（后续 state 刷新不重复）。"""
    from client.net import NetClient
    g = make_game(mulligan=True)
    c = NetClient(db, None, "甲")
    c.payload = g.state.model_dump(mode="json")
    c.me = 1  # 后手视角
    c._show()
    out1 = capsys.readouterr().out
    assert "A（先手）座位：" in out1 and "B（后手）座位：" in out1
    assert "1.式神100101" in out1  # 名字取 state 侧（与服务端一致）
    c._show()
    out2 = capsys.readouterr().out
    assert "座位：" not in out2
    c.handle({"type": "start", "player_index": 1, "you_first": False, "opponent": "乙"})
    assert c._seats_shown is False  # 新对局重置


def test_net_ctx_change_cancels_stale_prompt(db, make_game, monkeypatch):
    """输入上下文指纹：state 推送使阶段/行动权变化时作废阻塞中的陈旧提示符
    （调度超时自动 ready、回合超时自动结束、双方就绪进入首回合的场景）；
    同上下文内的推送（对手并行调度）不作废，保留正在输入的内容。"""
    from client import tui
    from client.net import NetClient
    calls = []
    monkeypatch.setattr(tui, "cancel_prompt", lambda: calls.append(1))
    g = make_game(mulligan=True)
    c = NetClient(db, None, "甲")
    c.me = 0
    c.handle({"type": "state", "payload": g.state.model_dump(mode="json"), "log": []})
    assert calls == []  # 首次建立指纹，不作废
    # 对手并行调度（阶段不变、己方未完成）：指纹不变，不作废
    g.apply({"op": "mulligan", "uid": g.state.players[1].hand[0].uid, "player": 1})
    c.handle({"type": "state", "payload": g.state.model_dump(mode="json"), "log": []})
    assert calls == []
    # 己方完成调度（含超时自动 ready）：指纹变化 → 作废
    g.apply({"op": "ready", "player": 0})
    c.handle({"type": "state", "payload": g.state.model_dump(mode="json"), "log": []})
    assert len(calls) == 1
    # 双方就绪进入首回合（mulligan → 升级/战斗阶段）→ 再作废
    g.apply({"op": "ready", "player": 1})
    assert g.state.phase != "mulligan"
    c.handle({"type": "state", "payload": g.state.model_dump(mode="json"), "log": []})
    assert len(calls) == 2


# ---------- 构筑环境（卡组文件 v3 + env）----------

def test_deckstore_env_roundtrip(db, tmp_path):
    """v3 卡组文件：env 随条目保存/读取；is_standard 按各卡组环境校验——
    环境早于数据 version 时卡组不可用（不标准），最新/不早于 version 时正常。"""
    from db import deckstore
    store = tmp_path / "decks.json"
    entries = _store_entries(db)
    entries[0]["env"] = 20200101          # 早于全部数据 version：不可用
    entries[1]["env"] = 20991231          # 晚于全部数据 version：可用
    deckstore.save_decks(db, entries, store)
    loaded = deckstore.load_decks(db, store)
    assert [d["env"] for d in loaded] == [20200101, 20991231]
    assert [d["standard"] for d in loaded] == [False, True]


def test_deckstore_v2_rejected_and_bad_env(db, tmp_path):
    """v2 旧版文件不向前兼容：视为格式异常删除；env 非法同样异常删除。"""
    import json

    from db import deckcode, deckstore
    store = tmp_path / "decks.json"
    groups = deckcode.group_deck(db, list(F.TEAM), F.deck_of(*F.TEAM))
    store.write_text(json.dumps(
        {"version": 2, "decks": [[True, {"name": "旧", "groups": groups}]]},
        ensure_ascii=False), encoding="utf-8")
    assert deckstore.load_decks(db, store) == []
    assert not store.exists()  # 旧版本文件：提示并删除
    store.write_text(json.dumps(
        {"version": 3, "decks": [[True, {"name": "坏", "groups": groups,
                                         "env": 20261301}]]},
        ensure_ascii=False), encoding="utf-8")
    assert deckstore.load_decks(db, store) == []
    assert not store.exists()  # 文件异常：提示并删除


def test_deckbuilder_new_deck_env_flow(db, monkeypatch, capsys, tmp_path):
    """新建卡组先询问构筑环境：合法日期入库保存；非法日期提示后重问。"""
    from client import deckbuilder
    from db import deckstore
    store = tmp_path / "decks.json"
    team = list(F.TEAM)
    # 环境询问（先非法后合法）→ 名称 → 不导入 → 选 4 式神（全名直选）
    # → 各 8 张牌 → 编辑循环回车完成 → q 退出
    lines = ["", "20261301", "20991231", "", ""]
    lines += [" ".join(db.shikigami[s].name for s in team)]
    for sid in team:
        n = len(deckbuilder.buildable_cards(db, sid))
        lines += [" ".join(str((i % n) + 1) for i in range(8))]
    lines += ["", "q"]
    feed(monkeypatch, lines)
    deckbuilder.run_deckbuilder(db, store_path=store)
    out = capsys.readouterr().out
    assert "环境须为环境别名或合法日期" in out
    loaded = deckstore.load_decks(db, store)
    assert len(loaded) == 1 and loaded[0]["env"] == 20991231


def test_net_client_env_date_switches_db(db):
    """对局环境切换：客户端渲染库解析为环境版本（_apply_env，lobby/start 下发）。"""
    from client.net import NetClient
    c = NetClient(db, None, "甲")
    c._apply_env(20200101)   # 早于全部数据 version：环境库为空
    assert c.env_date == 20200101 and not c.db.cards
    c._apply_env(20991231)   # 不早于数据 version：与最新一致
    assert set(c.db.cards) == set(db.cards)
    c._apply_env(None)       # 回到最新
    assert c.db is c._base_db


def test_net_lobby_env_command_alias_and_mode_gate(db, capsys):
    """准备阶段 e <环境>（房主、双方未准备）：别名解析为日期下发（6 位日期
    按 20YY 展开）；标准模式拒绝更改；非法输入本地拦截不发消息。"""
    import json

    from client.net import NetClient

    class FakeWS:
        def __init__(self):
            self.sent = []

        def send(self, raw):
            self.sent.append(json.loads(raw))

    c = NetClient(db, FakeWS(), "甲")
    c.in_lobby = True
    c.seat = 0
    c.mode = "free"
    c.handle_line("e 经典")
    assert c.ws.sent == [{"type": "env", "date": 20191212}]
    c.handle_line("e 200327")
    assert c.ws.sent[-1] == {"type": "env", "date": 20200327}
    c.handle_line("e 20261301")  # 非法日期：本地拦截
    assert len(c.ws.sent) == 2
    assert "环境须为环境别名" in capsys.readouterr().out
    c.mode = "standard"          # 标准模式：固定最新环境，不可更改
    c.handle_line("e 不夜之火")
    assert len(c.ws.sent) == 2
    assert "标准模式使用最新平衡性环境，不可更改" in capsys.readouterr().out
