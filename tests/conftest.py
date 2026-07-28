import pytest

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


@pytest.fixture
def gdb():
    """真实卡牌数据库（db/ 目录 YAML，strict 校验加载）——数据端到端测试用。"""
    from db.loader import CardDatabase
    return CardDatabase.load()


@pytest.fixture
def real_game(gdb):
    """真实数据库对局工厂：team 必传（主力式神放 0 号位）。"""
    def _make(team, seed: int = 1, **kw):
        return factories.mk_game(gdb, seed=seed, team=team, **kw)

    return _make
