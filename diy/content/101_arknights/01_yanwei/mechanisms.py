from core.registry import register_stat_aura


def _half_player_shield_power(game, aura, player, source):
    shield = max(0, game.state.players[player].shield)
    source.ext["dyn_power"] += shield // 2 - (
        source.base_power + source.perm_power + source.temp_power)


register_stat_aura("half_player_shield_power", _half_player_shield_power)
