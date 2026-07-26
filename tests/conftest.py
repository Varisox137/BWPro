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
