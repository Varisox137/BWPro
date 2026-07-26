"""服务端入口（server/main.py）限流与输入上限测试。"""
import pytest

from server.main import RateLimiter, _text


def test_rate_limiter():
    rl = RateLimiter(3)
    assert all(rl.allow() for _ in range(3))
    assert not rl.allow()
    rl.window -= 1.1  # 模拟进入下一秒
    assert rl.allow()


def test_text_field_caps():
    assert _text({"name": "甲"}, "name", 32) == "甲"
    assert _text({}, "name", 32) is None
    with pytest.raises(ValueError):
        _text({"name": "x" * 33}, "name", 32)
    with pytest.raises(ValueError):
        _text({"name": 123}, "name", 32)
