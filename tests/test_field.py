"""幻境原牌实例的生命周期测试。"""
from core.model import Ref
from db.schema import InvocationDef
from tests import factories as F


def _field(db, cid=10010151, intensity=3, **kw):
    db.cards[cid] = F.card(
        cid, card_type="field", token=True, intensity=intensity, **kw)
    return cid


def test_field_original_card_enters_graveyard_on_destroy(db, make_game):
    cid = _field(db)
    game = make_game()
    player = game.state.players[0]
    player.orb = 9
    original = F.give(game, 0, cid)
    original.mods["lifecycle_marker"] = "kept"

    game.apply({"op": "play_card", "uid": original.uid})

    assert original not in player.graveyard
    field = player.fields[0]
    assert field.card is original
    assert field.card.uid == original.uid
    assert original not in player.hand

    game._change_field_intensity(0, 0, -field.intensity, None, "测试消灭")
    game._drain_queue()

    assert player.fields == []
    assert player.graveyard[-1] is original
    assert original.mods["lifecycle_marker"] == "kept"


def test_field_effect_summon_generates_original_card(db, make_game):
    field_id = _field(db, cid=10010161, intensity=4)
    source_id = 10010151
    db.cards[source_id] = F.card(
        source_id, token=True,
        steps=[F.Step(op="summon_field", card=field_id)])
    game = make_game()
    player = game.state.players[0]
    player.orb = 9

    source = F.give(game, 0, source_id)
    source.appearance_source = 100101
    game.apply({"op": "play_card", "uid": source.uid})

    generated = player.fields[0].card
    assert generated.generated is True
    assert generated.id == field_id
    assert generated.appearance_source == 100101
    assert generated not in player.graveyard

    game.deal_to_player(0, 4, Ref(player=1, shikigami=0))
    game._drain_queue()

    assert player.fields == []
    assert player.graveyard[-1] is generated
    assert generated.generated is True


def test_field_play_preserves_revealed_event_payload(db, make_game, monkeypatch):
    cid = _field(db)
    game = make_game()
    player = game.state.players[0]
    player.orb = 9
    original = F.give(game, 0, cid)
    original.mods["revealed"] = True
    played_events = []
    real_emit = game.emit

    def capture_event(name, **payload):
        if name == "on_card_played" and payload.get("uid") == original.uid:
            played_events.append(payload)
        return real_emit(name, **payload)

    monkeypatch.setattr(game, "emit", capture_event)
    game.apply({"op": "play_card", "uid": original.uid})

    assert player.fields[0].card is original
    assert len(played_events) == 1
    assert played_events[0]["card_revealed"] is True


def test_field_deck_play_clears_invocation_without_move_events(
        db, make_game):
    enabler_id = _field(
        db, cid=10010152, intensity=10, field_keywords=["deck_top_play"])
    field_id = _field(db, cid=10010161, intensity=4)
    db.invocations["梦魇"] = InvocationDef(name="梦魇", unique="none")
    game = make_game()
    player = game.state.players[0]
    player.orb = 9
    F.play(game, 0, enabler_id)
    original = F.give(game, 0, field_id)
    player.hand.remove(original)
    player.deck.insert(0, original)
    game.attach_invocation("梦魇", player=1, card=original)
    game.history.clear()

    game.apply({"op": "play_card", "uid": original.uid, "play_from": "deck"})

    assert player.fields[-1].card is original
    assert original.invocations == []
    assert "on_card_move" not in game.history
    assert "on_card_moved" not in game.history
