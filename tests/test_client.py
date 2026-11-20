"""客户端共享展示数据、网络工具与核心调试指令测试。"""
import pytest

from client import net, presentation
from core import debug as debug_commands
from core.engine import IllegalAction
from core.model import Ref
from tests import factories as F
from tests.factories import give

T = F.T


def test_hand_stats_labels(db, make_game):
    """手牌数值段：战斗牌力量/护甲、形态身材、觉醒永久身材。"""
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
    db.cards[10010167] = F.card(
        10010167, card_type="combat", token=True,
        steps=[F.Step(op="buff_power", amount={"base": 2, "enemy_stunned_count": True},
                      target=T(kind="self"))])
    game = make_game()
    combat = give(game, 0, 10010161)
    combat.mods["enhance"] = 2
    form = give(game, 0, 10010162)
    awaken = give(game, 0, 10010163)
    dynamic = give(game, 0, 10010167)
    info = presentation.hand_cards_info(game, 0)
    assert info[combat.uid]["stats"] == "力量+3 护甲+2"
    assert info[form.uid]["stats"] == "身材5/9"
    assert info[awaken.uid]["stats"] == "觉醒+1/+2"

    enemy = game.state.players[1]
    target = enemy.shikigami[0]
    target.level = 1
    target.stuns.append({"kind": "normal", "turn": 0})
    enemy.ext.setdefault("stuns", []).append({"kind": "normal", "turn": 0})
    assert presentation.hand_cards_info(game, 0)[dynamic.uid]["stats"] == "力量+4"
    target.stuns.clear()
    enemy.ext["stuns"].clear()
    assert presentation.hand_cards_info(game, 0)[dynamic.uid]["stats"] == "力量+2"


def test_hand_stats_live_enhance(db, make_game):
    """持久增强未装配进实例时也计入手牌显示，且不污染实例修饰。"""
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
    game = make_game()
    player = game.state.players[0]
    cards = [give(game, 0, cid) for cid in (10010164, 10010165, 10010166)]
    for card in cards:
        player.card_mods[card.id] = {"enhance": 2}
    info = presentation.hand_cards_info(game, 0)
    assert [info[card.uid]["stats"] for card in cards] == ["力量+3", "伤害7", "生命变为12"]
    assert [info[card.uid]["enhance"] for card in cards] == [2, 2, 2]
    assert all("enhance" not in card.mods for card in player.hand)


def test_hand_render_stats_share_runtime_evaluation(db, make_game):
    game = make_game(mulligan=False)
    player = game.state.players[0]
    card = player.hand[0]
    db.cards[card.id] = db.cards[card.id].model_copy(update={"card_type": "combat"})
    info = presentation.hand_cards_info(game, 0)[card.uid]
    assert set(info["render"]) == {"power+", "shield+"}
    assert all(type(value) is int for value in info["render"].values())


def test_hand_awaken_render_stats_share_label(db, make_game):
    db.cards[10010163] = F.card(
        10010163, subtype="awaken", token=True,
        steps=[F.Step(op="buff_power", amount=1, perm=True, target=T(kind="self")),
               F.Step(op="buff_health", amount=-2, perm=True, target=T(kind="self"))])
    game = make_game(mulligan=False)
    card = give(game, 0, 10010163)
    info = presentation.hand_cards_info(game, 0)[card.uid]
    assert info["render"] == {"power+": 1, "health+": -2}
    assert info["stats"] == "觉醒+1/-2"


def test_hand_aura_display_live(db, make_game):
    """手牌光环实时反映数值与授予关键字。"""
    db.cards[10010167] = F.card(
        10010167, card_type="combat", token=True,
        steps=[F.Step(op="buff_power", amount=1, target=T(kind="self")),
               F.Step(op="gain_shield", amount=2, target=T(kind="self"))])
    game = make_game()
    player = game.state.players[0]
    player.card_auras.append({
        "shikigami": 100101, "card_type": None, "card_id": None,
        "keywords": ["fast"], "cost_zero": False,
        "power": 0, "shield": 1, "power_ext": "x",
        "turn": None, "scope": "form", "holder": [0, 0],
    })
    player.ext["x"] = 3
    card = give(game, 0, 10010167)
    info = presentation.hand_cards_info(game, 0)[card.uid]
    assert info["stats"] == "力量+4 护甲+3"
    assert "瞬发" in info["keywords"]


def test_result_text_by_viewer():
    names = ["玩家A", "玩家B"]
    assert presentation.result_text(0, names, viewer=0) == "自身胜利！"
    assert presentation.result_text(0, names, viewer=1) == "自身落败……"
    assert presentation.result_text(-1, names, viewer=0) == "双方平局"
    assert presentation.result_text(1, names) == "玩家B 获胜！"
    assert presentation.result_text(-1, names) == "双方平局"


def test_normalize_and_display_server_url():
    assert net.normalize_server_url("ws://a.top:1037/ws") == "ws://a.top:1037/ws"
    assert net.normalize_server_url("wss://a.top/ws") == "wss://a.top/ws"
    assert net.normalize_server_url("https://a.top") == "wss://a.top/ws"
    assert net.normalize_server_url("http://a.top:8080") == "ws://a.top:8080/ws"
    assert net.normalize_server_url("a.top:1037") == "ws://a.top:1037/ws"
    assert net.normalize_server_url("127.0.0.1") == "ws://127.0.0.1:1037/ws"
    assert net.normalize_server_url("localhost") == "ws://localhost:1037/ws"
    assert net.normalize_server_url("a.top") == "wss://a.top/ws"
    assert net.normalize_server_url("wss://a.top/custom") == "wss://a.top/custom"
    assert net.display_server_url("wss://a.top/ws") == "a.top"
    assert net.display_server_url("ws://a.top:1037/ws") == "a.top:1037"
    assert net.display_server_url("https://a.top/custom") == "a.top/custom"


def test_machine_id_is_persistent_hex(tmp_path):
    path = tmp_path / "home" / "machine_id"
    first = net.machine_id(path)
    assert first == net.machine_id(path)
    assert len(first) == 32
    assert all(char in "0123456789abcdef" for char in first)


def test_probe_connection_retries(monkeypatch):
    calls = []

    class FakeWS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def flaky_connect(url, **_kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise Exception("server rejected WebSocket connection: HTTP 200")
        return FakeWS()

    monkeypatch.setattr("websockets.sync.client.connect", flaky_connect)
    monkeypatch.setattr(net.time, "sleep", lambda _seconds: None)
    assert net.probe_connection("wss://a.top/ws") is None
    assert len(calls) == 3

    def always_fail(_url, **_kwargs):
        raise Exception("server rejected WebSocket connection: HTTP 200")

    monkeypatch.setattr("websockets.sync.client.connect", always_fail)
    error = net.probe_connection("wss://a.top/ws", retries=2)
    assert "HTTP 200" in error and "穿透" in error


def test_public_ip_rejects_private_address_and_uses_fallback(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.text.encode("ascii")

    def open_url(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            return FakeResponse("192.168.1.8")
        return FakeResponse("8.8.8.8\n")

    monkeypatch.setattr(net, "urlopen", open_url, raising=False)
    assert net.public_ip() == "8.8.8.8"
    assert [call[0] for call in calls] == [
        "https://api.ipify.org", "https://ifconfig.me/ip"]
    monkeypatch.setattr(net, "urlopen",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("离线")))
    assert net.public_ip() == ""


def test_debug_console_parser(make_game):
    game = make_game()
    command = debug_commands.run_debug(game, ["set_stat", "e0", "health", "25"])
    assert command == {"op": "debug_set_stat", "args": {
        "target": {"player": 1, "shikigami": None}, "key": "health", "value": 25}}
    assert debug_commands.parse_ref("E4", 0) == Ref(player=1, shikigami=3)


def test_debug_give_card_zones(db, make_game):
    game = make_game()
    player = game.state.players[0]
    before = len(player.hand)
    game.apply({"op": "debug_give_card",
                "args": {"player": 0, "card_id": 10010101, "count": 2}})
    assert len(player.hand) == before + 2
    assert all(card.id == 10010101 for card in player.hand[-2:])
    game.apply({"op": "debug_give_card", "args": {
        "player": 0, "card_id": 10010101, "zone": "graveyard"}})
    assert player.graveyard[-1].id == 10010101


def test_debug_set_stat(db, make_game):
    game = make_game()
    player = game.state.players[0]
    shiki = player.shikigami[0]
    game.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 0, "shikigami": 0}, "key": "health", "value": 1}})
    assert shiki.health == 1
    game.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 0, "shikigami": 0}, "key": "level", "value": 3}})
    assert shiki.level == 3
    game.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 0, "shikigami": 0}, "key": "defeated", "value": True}})
    assert shiki.defeated is True
    game.apply({"op": "debug_set_stat", "args": {
        "target": {"player": 0}, "key": "orb", "value": 9}})
    assert player.orb == 9


def test_debug_play_and_assault_bypass_checks(db, make_game):
    cid = 10010152
    db.cards[cid] = F.card(cid, steps=[F.dmg(5)],
                           target=F.T(kind="choose", pool="enemy_shikigami"), token=True)
    game = make_game()
    player = game.state.players[0]
    player.orb = 0
    card = give(game, 0, cid)
    with pytest.raises(IllegalAction):
        game.apply({"op": "play_card", "uid": card.uid,
                    "target": Ref(player=1, shikigami=0)})
    game.apply({"op": "debug_play_card", "args": {
        "player": 0, "uid": card.uid, "target": {"player": 1, "shikigami": 0}}})
    assert game.state.players[1].shikigami[0].defeated is True
    assert game.state.players[1].shikigami[0].health == 0
    assert card in player.graveyard
    player.orb = player.assaults_left = 0
    with pytest.raises(IllegalAction):
        game.apply({"op": "assault", "index": 0})
    game.apply({"op": "debug_assault", "args": {"player": 0, "index": 0}})
    assert game.state.players[1].shield == 2


def test_debug_draw_set_turn_and_guards(db, make_game):
    game = make_game()
    player = game.state.players[0]
    hand_before, deck_before = len(player.hand), len(player.deck)
    game.apply({"op": "debug_draw", "args": {"player": 0, "count": 2}})
    assert len(player.hand) == hand_before + 2
    assert len(player.deck) == deck_before - 2
    game.apply({"op": "debug_set_turn", "args": {"active": 1, "turn": 10}})
    assert game.state.active == 1 and game.state.turn == 10
    with pytest.raises(IllegalAction):
        game.apply({"op": "debug_foobar", "args": {}})
    game.state.config.enable_debug_commands = False
    with pytest.raises(IllegalAction):
        game.apply({"op": "debug_draw", "args": {"player": 0, "count": 1}})


def test_settle_log_channels(db, make_game):
    """阶段、升级、力量、护甲与伤害进入结算明细通道。"""
    game = make_game(auto_skip_upgrade=False)
    F.battle_setup(game)
    settle = game.state.settle_log
    assert any("—— 回合开始阶段（A" in line for line in settle)
    game.apply({"op": "upgrade", "index": 1})
    assert any("【升级】A 的式神100102升至 1 级" in line for line in settle)
    cid = 10010151
    db.cards[cid] = F.card(
        cid, steps=[F.Step(op="buff_power", amount=2, target=T(kind="self"))], token=True)
    F.play(game, 0, cid)
    assert any("【力量】式神100101 临时力量 +2" in line for line in settle)
    combat = 10010152
    db.cards[combat] = F.card(
        combat, card_type="combat",
        steps=[F.Step(op="buff_power", amount=2, target=T(kind="self")),
               F.Step(op="gain_shield", amount=1, target=T(kind="self"))], token=True)
    F.play(game, 0, combat)
    assert any("【护甲】式神100101 获得 1 点护甲" in line for line in settle)
    assert any("—— 战斗开始：式神100101 ——" in line for line in settle)
    assert any("—— 战斗结束 ——" in line for line in settle)
    assert any("—— 伤害结算开始 ——" in line for line in settle)
    assert any("—— 伤害结算结束 ——" in line for line in settle)
    assert any("【伤害】B 受到 7 点伤害（生命 30→23）" in line for line in settle)


def test_timeline_merges_log_and_settle_in_order(db, make_game):
    cid = 10010155
    db.cards[cid] = F.card(cid, shikigami=100101, level=1, token=True,
                           steps=[F.Step(op="heal", amount=2, target=T(kind="self"))])
    game = make_game()
    F.battle_setup(game)
    game.state.players[0].shikigami[0].health = 1
    game.apply({"op": "play_card", "uid": give(game, 0, cid).uid})
    entries = [entry for entry in game.state.timeline if entry["k"] in ("s", "l")]
    kinds = [entry["k"] for entry in entries]
    messages = [entry["m"] for entry in entries]
    assert set(kinds) == {"s", "l"}
    assert any(entry["k"] == "a" for entry in game.state.timeline)
    use_index = next(i for i, message in enumerate(messages) if "使用了【" in message)
    heal_index = next(i for i, message in enumerate(messages) if message.startswith("【治疗】"))
    assert kinds[use_index] == "l" and kinds[heal_index] == "s"
    assert use_index < heal_index


def test_settle_numeric_events_not_duplicated_in_log(db, make_game):
    game = make_game(auto_skip_upgrade=False)
    F.battle_setup(game)
    game.apply({"op": "upgrade", "index": 1})
    settle_before, log_before = len(game.state.settle_log), len(game.state.log)
    cid = 10010153
    db.cards[cid] = F.card(
        cid, card_type="combat",
        steps=[F.Step(op="buff_power", amount=2, target=T(kind="self"))], token=True)
    F.play(game, 0, cid)
    assert any("【伤害】" in line for line in game.state.settle_log[settle_before:])
    assert not any("点伤害（剩余生命" in line for line in game.state.log[log_before:])
