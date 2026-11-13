from core.actions import register_action
from core.model import Ref
from core.registry import register_condition
from core.targets import register_pool


def _any_combat(game, controller, *, targeted=False):
    refs = []
    for pi in (controller, 1 - controller):
        p = game.state.players[pi]
        ci = p.combat_index
        if ci is not None and p.shikigami[ci].in_play:
            refs.append(Ref(player=pi, shikigami=ci))
    return refs


def _move_combat_all(game, ctx, *, targets, memo="combat_moves"):
    moved = 0
    for ref in targets:
        p = game.state.players[ref.player]
        if ref.shikigami is None or p.combat_index != ref.shikigami:
            continue
        game._retreat(p, ref.shikigami)
        if p.combat_index != ref.shikigami:
            moved += 1
    if ctx.memo is None:
        ctx.memo = {}
    ctx.memo[memo] = moved


def _redirect_attack(game, ctx, *, targets):
    if not targets:
        return
    marker = (ctx.event or {}).get("victim_override")
    if isinstance(marker, dict):
        marker["ref"] = targets[0]


def _player_shield_ge(game, want, event, controller, holder, chosen):
    return game.state.players[controller].shield >= int(want)


register_pool("any_combat", _any_combat)
register_action("move_combat_all", _move_combat_all)
register_action("redirect_attack", _redirect_attack)
register_condition("player_shield_ge", _player_shield_ge)
