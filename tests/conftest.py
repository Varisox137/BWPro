import pytest

from core.model import CardInstance
from tests import factories


@pytest.fixture
def db():
    """基础数据库：4 个无效果式神 + 空白卡。机制测试可自由往里加自定义数据。"""
    return factories.base_db()


@pytest.fixture
def make_game(db):
    def _make(seed: int = 1, **kw):
        return factories.mk_game(db, seed=seed, **kw)

    return _make


def give(game, player_index: int, defn_id: int) -> CardInstance:
    """测试辅助：直接发一张牌到玩家手牌。"""
    st = game.state
    card = CardInstance(uid=st.next_uid, id=defn_id)
    st.next_uid += 1
    st.players[player_index].hand.append(card)
    return card
