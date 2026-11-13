from pathlib import Path

import pytest

from core.model import GameConfig, Ref
from core.setup import new_game
from db.loader import CardDatabase
from tests import factories as F

YANWEI = 110101
TEAM = [YANWEI, 100101, 100102, 100111]
ENEMY_TEAM = [100102, 100103, 100111, 100114]


@pytest.fixture(scope="session")
def diy_db():
    from diy.runtime import load_database
    return load_database()


@pytest.fixture(autouse=True)
def preserve_extension_registries(diy_db):
    from core import actions, events, registry, targets

    snapshots = (
        (actions.ACTIONS, dict(actions.ACTIONS)),
        (events.EVENT_TIMING, dict(events.EVENT_TIMING)),
        (registry.CONDITIONS, dict(registry.CONDITIONS)),
        (registry.CONDITION_KEYS, set(registry.CONDITION_KEYS)),
        (registry.STAT_AURAS, dict(registry.STAT_AURAS)),
        (targets.POOLS, set(targets.POOLS)),
        (targets.POOL_HANDLERS, dict(targets.POOL_HANDLERS)),
    )
    yield
    for registry_obj, snapshot in snapshots:
        registry_obj.clear()
        registry_obj.update(snapshot)


def _game(db, diy_player=0):
    teams = (TEAM, ENEMY_TEAM) if diy_player == 0 else (ENEMY_TEAM, TEAM)
    g = new_game(
        db,
        ("A", list(teams[0]), F.deck_of(*teams[0])),
        ("B", list(teams[1]), F.deck_of(*teams[1])),
        seed=1, first=0, shuffle_team=False, mulligan=False,
        config=GameConfig(auto_skip_upgrade=True),
    )
    pa, pb = g.state.players
    pa.orb = pb.orb = 9
    pb.shield = 0
    for p in (pa, pb):
        for s in p.shikigami:
            s.level = 3
    return g


def _force_dice(g, monkeypatch, value):
    monkeypatch.setattr(g.rng, "randint", lambda _a, _b: value)


def test_runtime_discovers_builtin_and_is_idempotent(diy_db):
    from diy.runtime import load_database

    again = load_database()
    assert YANWEI in diy_db.shikigami
    assert set(range(11010101, 11010109)) <= set(diy_db.cards)
    assert YANWEI in again.shikigami
    assert again.shikigami[YANWEI].author == "962779670"
    assert diy_db.at_date(20261112).shikigami.get(YANWEI) is None
    dated = diy_db.at_date(20261113)
    resolved = dated.shikigami[YANWEI]
    assert resolved.author == "962779670"
    assert resolved.version == 20261113
    assert dated.diy_packs[101]["name"] == "红松移动"


def test_diy_and_official_ids_are_isolated(diy_db):
    official = CardDatabase.load()
    assert YANWEI not in official.shikigami
    assert 11010101 not in official.cards
    assert diy_db.paths[YANWEI].replace("\\", "/").startswith(
        (Path(__file__).parent.parent / "diy/content").as_posix())


def test_diy_pack_is_available_to_deckbuilder(diy_db):
    from client.deckbuilder import _pack_groups, available_shikigami, buildable_cards

    assert YANWEI in [d.id for d in available_shikigami(diy_db)]
    groups = _pack_groups(diy_db, available_shikigami(diy_db))
    assert any(name == "红松移动" and [d.id for d in members] == [YANWEI]
               for name, members in groups)
    assert [c.id for c in buildable_cards(diy_db, YANWEI)] == list(range(11010101, 11010109))


def test_runtime_discovers_pack_then_shikigami_extensions(diy_db, tmp_path):
    from diy.runtime import load_database
    from core import actions, events

    pack = tmp_path / "102_test"
    child = pack / "01_example"
    child.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: 102\nname: 测试包\n", encoding="utf-8")
    (pack / "mechanisms.py").write_text(
        "from core.actions import register_action\n"
        "def _pack(game, ctx, *, targets): pass\n"
        "register_action('test_pack_action', _pack)\n", encoding="utf-8")
    (pack / "events.yaml").write_text(
        "- {name: test_pack_event, timing: queue}\n", encoding="utf-8")
    (child / "mechanisms.py").write_text(
        "from core.actions import register_action\n"
        "def _child(game, ctx, *, targets): pass\n"
        "register_action('test_child_action', _child)\n", encoding="utf-8")
    (child / "events.yaml").write_text(
        "- {name: test_child_event, timing: insert}\n", encoding="utf-8")

    db = load_database(content_roots=[tmp_path])
    assert "test_pack_action" in actions.ACTIONS
    assert "test_child_action" in actions.ACTIONS
    assert events.EVENT_TIMING["test_pack_event"] == "queue"
    assert events.EVENT_TIMING["test_child_event"] == "insert"
    assert {"test_pack_event", "test_child_event"} <= db.custom_events
    assert not db.validate()
    load_database(content_roots=[tmp_path])


def test_runtime_rejects_cross_source_id_conflict(tmp_path):
    from diy.runtime import load_database

    pack = tmp_path / "102_conflict"
    pack.mkdir()
    (pack / "pack.yaml").write_text("id: 102\nname: 冲突包\n", encoding="utf-8")
    (pack / "110101.yaml").write_text(
        "id: 110101\nname: 冲突\nversions:\n  history:\n"
        "    - date: 20261113\n      faction: 苍叶\n      power: 1\n      health: 1\n",
        encoding="utf-8")
    with pytest.raises(RuntimeError, match="110101") as exc:
        load_database(content_roots=[tmp_path])
    assert "110101.yaml" in str(exc.value)


def test_action_registration_is_idempotent_but_rejects_collision():
    from core.actions import ACTIONS, register_action

    def first(game, ctx, *, targets):
        return None

    def second(game, ctx, *, targets):
        return None

    name = "test_registration_contract"
    try:
        assert register_action(name, first) is first
        assert register_action(name, first) is first
        with pytest.raises(ValueError, match=name):
            register_action(name, second)
    finally:
        ACTIONS.pop(name, None)


def test_scaffold_and_versions_preserve_author(tmp_path):
    from db.scaffold import scaffold_shikigami
    from db.versioning import resolve_at_date, validate_versions
    import yaml

    written = scaffold_shikigami(
        tmp_path, id=100101, name="作者测试", slug="author", faction="红莲",
        power=3, health=4, author="962779670")
    raw = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert raw["author"] == "962779670"
    assert not validate_versions(raw)
    assert resolve_at_date(raw, 99999999)["author"] == "962779670"
    assert "author" not in raw["versions"]["history"][0]


def test_leave_combat_base_armor_and_defeat_boundary(diy_db):
    g = _game(diy_db)
    pa = g.state.players[0]
    yan = pa.shikigami[0]
    F.move(g, 0, 0)
    g._retreat(pa, 0)
    g._drain_queue()
    assert pa.shield == 2

    pa.shield = 0
    F.move(g, 0, 0)
    yan.health = 0
    g.check_defeated(Ref(player=0, shikigami=0))
    g._drain_queue()
    assert pa.shield == 0
    assert yan.defeated


def test_form_power_tracks_half_player_armor_and_overrides_stats(diy_db):
    g = _game(diy_db)
    pa, yan = g.state.players[0], g.state.players[0].shikigami[0]
    pa.shield = 5
    yan.perm_power = 4
    yan.temp_power = 2
    F.play(g, 0, 11010101)
    assert yan.form.id == 11010101
    assert yan.eff_power == 2
    pa.shield = 8
    g._refresh_stat_auras()
    assert yan.eff_power == 4
    yan.combat_power = 3
    assert yan.eff_power == 7
    g._destroy_form(pa, 0, "test")
    assert yan.eff_power == 3 + 4 + 2 + 3


def test_draw_delay_orb_and_defeat_clears_delay(diy_db):
    for lethal in (False, True):
        g = _game(diy_db)
        pa, yan = g.state.players[0], g.state.players[0].shikigami[0]
        hand_before = len(pa.hand)
        F.play(g, 0, 11010102)
        assert len(pa.hand) == hand_before + 1
        assert len(yan.delayed) == 1
        if lethal:
            yan.health = 0
            g.check_defeated(Ref(player=0, shikigami=0))
            assert not yan.delayed
        F.pass_turns(g, 2)
        assert pa.orb == (2 if lethal else 3)


def test_response_redirects_attack_and_runs_move_draw(diy_db):
    g = _game(diy_db, diy_player=1)
    pa, pb = g.state.players
    yan = pb.shikigami[0]
    F.move(g, 0, 0)
    F.move(g, 1, 0)
    hand_before = len(pb.hand)
    F.give(g, 1, 11010102)
    g.apply({"op": "assault", "index": 0})
    assert pb.combat_index is None
    assert yan.health == yan.max_health
    assert pb.health == 30
    assert pb.shield == 1
    assert len(pb.hand) == hand_before + 1
    assert pb.graveyard[-1].id == 11010102


def test_after_attack_moves_chosen_ally(diy_db):
    g = _game(diy_db)
    pa = g.state.players[0]
    F.move(g, 1, 0)
    target = Ref(player=0, shikigami=1)
    F.play(g, 0, 11010103, target=target)
    assert pa.combat_index == 1
    assert pa.shield == 2
    assert not pa.shikigami[1].delayed


def test_awaken_replaces_leave_ability_and_launches_remote(diy_db):
    g = _game(diy_db)
    pa, pb = g.state.players
    yan = pa.shikigami[0]
    F.play(g, 0, 11010104)
    assert yan.awakened == 11010104
    assert yan.eff_power == 4 and yan.max_health == 5
    F.move(g, 0, 0)
    g._retreat(pa, 0)
    g._drain_queue()
    assert pa.shield == 4
    assert pb.health == 26
    assert pa.combat_index is None


def test_awaken_luck_redirects_and_nested_remote_attack(diy_db, monkeypatch):
    g = _game(diy_db, diy_player=1)
    pa, pb = g.state.players
    yan = pb.shikigami[0]
    pa.shikigami[1].health = 20
    F.pass_turns(g, 1)
    F.play(g, 1, 11010104)
    F.pass_turns(g, 1)
    pa.orb = pb.orb = 9
    pb.hand[:] = [c for c in pb.hand if "trigger" not in diy_db.cards[c.id].keywords]
    F.move(g, 0, 1)
    F.move(g, 1, 0)
    _force_dice(g, monkeypatch, 6)
    g.apply({"op": "assault", "index": 1})
    assert pb.combat_index is None
    assert pa.shikigami[1].health == 16
    assert pb.health == 30
    assert pb.shield == 0


def test_combat_zone_wave_counts_actual_moves_and_conditional_fast(diy_db):
    g = _game(diy_db)
    pa, pb = g.state.players
    for s in pb.shikigami:
        s.shield = 0
    F.move(g, 0, 0)
    F.move(g, 1, 0)
    cdef = diy_db.cards[11010105]
    assert g._effective_cost(pa, cdef) == 0
    F.play(g, 0, 11010105)
    assert pa.orb == 9
    assert pa.combat_index is None and pb.combat_index is None
    assert pa.shield == 2
    assert all(s.health == s.max_health - 2 for s in pb.shikigami)

    g2 = _game(diy_db)
    assert g2._effective_cost(g2.state.players[0], cdef) == 1


def test_cancel_response_runs_full_combat_zone_wave(diy_db):
    g = _game(diy_db, diy_player=1)
    pa, pb = g.state.players
    attacker = pa.shikigami[0]
    pb.hand[:] = [c for c in pb.hand if c.id != 11010102]
    for s in pa.shikigami:
        s.shield = 0
    F.move(g, 0, 0)
    F.move(g, 1, 0)
    F.give(g, 1, 11010105)
    g.apply({"op": "assault", "index": 0})
    assert pb.graveyard[-1].id == 11010105
    assert attacker.health == attacker.max_health - 2
    assert pb.shikigami[0].health == pb.shikigami[0].max_health
    assert pa.combat_index is None and pb.combat_index is None


def test_player_armor_condition_grants_combo_not_shikigami_armor(diy_db):
    for player_armor, expected in ((0, 3), (1, 6)):
        g = _game(diy_db)
        pa, pb = g.state.players
        pa.shield = player_armor
        F.play(g, 0, 11010106)
        assert pb.health == 30 - expected
        assert pa.shikigami[0].shield == 2


def test_form_luck_grants_lasting_unyielding_until_form_leaves(diy_db, monkeypatch):
    g = _game(diy_db)
    pa, yan = g.state.players[0], g.state.players[0].shikigami[0]
    _force_dice(g, monkeypatch, 6)
    F.play(g, 0, 11010107)
    assert "unyielding" in yan.keywords
    g.deal_to_shikigami(Ref(player=0, shikigami=0), 99, None)
    assert yan.health == 1 and not yan.defeated
    assert "unyielding" in yan.keywords
    g._destroy_form(pa, 0, "test")
    assert not g._has_keyword(yan, "unyielding")


def test_form_player_damage_moves_in_and_enter_combat_grants_power_armor(diy_db, monkeypatch):
    g = _game(diy_db)
    pa, yan = g.state.players[0], g.state.players[0].shikigami[0]
    _force_dice(g, monkeypatch, 1)
    F.play(g, 0, 11010107)
    assert pa.combat_index is None
    g.deal_to_player(0, 3, None)
    g._drain_queue()
    assert pa.combat_index == 0
    assert pa.shield == 4


def test_field_moves_and_leave_combat_grants_natural_one_shots(diy_db):
    g = _game(diy_db)
    pa, yan = g.state.players[0], g.state.players[0].shikigami[0]
    F.play(g, 0, 11010108)
    assert pa.fields[0].card_id == 11010108
    assert pa.fields[0].intensity == 9
    assert pa.combat_index == 0
    g._retreat(pa, 0)
    g._drain_queue()
    assert "barrier" in yan.one_shot_keywords
    assert "haste" in yan.one_shot_keywords
    assert pa.shield == 2
