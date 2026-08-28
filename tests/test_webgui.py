"""Web GUI 基础框架测试（server/webgui.py）：页面可访问、catalog/validate_deck/
卡组码 API 正常、既有 403 catch-all 不受影响。联机全流程已由 test_server.py 覆盖。
"""
import pytest
from fastapi.testclient import TestClient

from db.test_data import TEST_IDS, make_test_deck
from server.main import create_app
from server.manager import RoomManager


@pytest.fixture
def client(gdb):
    """挂 Web GUI 的真实数据库服务端（TestClient，不走 lifespan/看门狗）。"""
    app = create_app(RoomManager(gdb), require_client_ua=False)
    return TestClient(app)


def test_gui_page_and_static(client):
    r = client.get("/gui")
    assert r.status_code == 200
    assert "bwpro-app" in r.text and "卡组构筑" in r.text and "联机对战" in r.text
    assert client.get("/gui/static/app.js").status_code == 200
    assert client.get("/gui/static/style.css").status_code == 200
    # 非白名单静态文件与未知路径仍按 catch-all 拒绝
    assert client.get("/gui/static/secret.js").status_code == 404
    assert client.get("/nonexistent").status_code == 403


def test_catalog(client):
    r = client.get("/gui/api/catalog")
    assert r.status_code == 200
    data = r.json()
    assert data["env"] is None and "标准" in data["env_label"]
    buildable = [s for s in data["shikigami"] if s["buildable"]]
    assert len(buildable) >= 50  # 当前 59 名可构筑式神的量级
    s0 = buildable[0]
    assert {"id", "name", "faction", "power", "health", "text"} <= set(s0)
    assert len(data["cards"]) > 400
    c0 = data["cards"][0]
    assert {"id", "name", "shikigami", "card_type", "level", "cost", "text",
            "token", "needs_target"} <= set(c0)
    assert data["aliases"]  # 环境别名登记表下发给页面下拉框


def test_catalog_env(client):
    # 经典（公测开服）环境的可用式神数应明显少于最新环境
    latest = client.get("/gui/api/catalog").json()
    classic = client.get("/gui/api/catalog", params={"env": "经典"}).json()
    assert classic["env"] == 20191212
    assert len(classic["shikigami"]) < len(latest["shikigami"])
    r = client.get("/gui/api/catalog", params={"env": "不存在的别名"})
    assert r.status_code == 400


def test_validate_deck_api(client):
    ok = client.post("/gui/api/validate_deck",
                     json={"shikigami": list(TEST_IDS),
                           "cards": make_test_deck()}).json()
    assert ok == {"ok": True, "errors": []}
    bad = client.post("/gui/api/validate_deck",
                      json={"shikigami": list(TEST_IDS[:3]),
                            "cards": make_test_deck()}).json()
    assert bad["ok"] is False and bad["errors"]
    # 环境参数：经典（公测开服）环境下不含后续版本的式神
    latest = client.get("/gui/api/catalog").json()
    classic_ids = {s["id"] for s in client.get(
        "/gui/api/catalog", params={"env": "经典"}).json()["shikigami"]}
    new_sid = next(s["id"] for s in latest["shikigami"]
                   if s["buildable"] and s["id"] not in classic_ids)
    r = client.post("/gui/api/validate_deck",
                    json={"shikigami": [new_sid] + list(TEST_IDS[:3]),
                          "cards": make_test_deck(), "env": "经典"})
    assert r.json()["ok"] is False


def test_deckcode_roundtrip(client):
    payload = {"shikigami": list(TEST_IDS), "cards": make_test_deck()}
    code = client.post("/gui/api/deckcode/export", json=payload).json()["code"]
    assert isinstance(code, str) and code
    back = client.post("/gui/api/deckcode/import", json={"code": code}).json()
    assert back["shikigami"] == list(TEST_IDS)
    assert sorted(back["cards"]) == sorted(payload["cards"])
    assert len(back["groups"]) == 4
    r = client.post("/gui/api/deckcode/import", json={"code": "!!!"})
    assert r.status_code == 400
