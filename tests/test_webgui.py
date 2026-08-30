"""Web GUI 基础框架测试（server/webgui.py）：页面可访问、catalog/validate_deck/
卡组码 API 正常、既有 403 catch-all 不受影响。联机全流程已由 test_server.py 覆盖。
"""
import pytest
from fastapi.testclient import TestClient

from db.test_data import TEST_IDS, make_test_deck
from server.main import create_app
from server.manager import RoomManager
from tests.test_server import _started_room, run


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


def test_catalog_play_fields(client):
    """catalog 出牌相关字段：协战子选项 options、第二选择目标 needs_target2、
    灵咒定义表 invocations（前端协战选择/双目标收集/灵咒选项文本用）。"""
    data = client.get("/gui/api/catalog").json()
    c0 = data["cards"][0]
    assert "options" in c0 and "needs_target2" in c0
    rein = [c for c in data["cards"] if c["card_type"] == "reinforce" and c["options"]]
    ids = {c["id"] for c in data["cards"]}
    assert rein and all(o in ids for c in rein for o in c["options"])
    assert any(c["needs_target2"] for c in data["cards"])  # 存在双选择目标卡
    assert data["invocations"] and all(
        "text" in v for v in data["invocations"].values())


def test_state_hand_info_shape(db):
    """state 推送附带己方手牌实时信息（hand_info，键 = 手牌 uid 字符串）：
    使用方式枚举/费用/关键字/数值段/使用条件等引擎求值字段形状；
    仅含己方手牌，对手手牌仍为占位卡（脱敏不受影响）。"""
    async def go():
        _, ws0, ws1 = await _started_room(db)
        for ws in (ws0, ws1):
            states = [m for m in ws.messages if m["type"] == "state"]
            assert states
            pl = states[-1]["payload"]
            info = pl["hand_info"]
            assert info  # 起始手牌非空
            own = next(p for p in pl["players"]
                       if {str(c["uid"]) for c in p["zones"]["hand"]} == set(info))
            other = pl["players"][1 - pl["players"].index(own)]
            assert all(c["uid"] == 0 for c in other["zones"]["hand"])  # 对手手牌仍脱敏
            for uid, entry in info.items():
                assert int(uid) > 0
                assert {"cost", "keywords", "stats", "enhance", "quest",
                        "playable", "usage"} <= set(entry)
                assert entry["usage"], "每张手牌至少有一个使用方式条目"
                assert {"id", "label", "cost", "energy", "ok",
                        "reason", "effect"} <= set(entry["usage"][0])
    run(go())
