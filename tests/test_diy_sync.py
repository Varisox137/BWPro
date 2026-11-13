"""DIY 包同步、下载存储与联机房间同步状态机测试。"""
import asyncio
import json
import random
from pathlib import Path

import pytest
import yaml

from db import deckcode
from server.manager import RoomManager
from server.room import Room
from tests import factories as F


def make_package(pack_id=201, *, shiki_id=None, date=20261113, name="测试式神",
                 cards=False, event=None):
    shiki_id = shiki_id or (100000 + pack_id * 100 + 1)
    files = {
        "pack.yaml": yaml.safe_dump(
            {"id": pack_id, "name": f"包{pack_id}"}, allow_unicode=True, sort_keys=False),
        "01_test/shiki.yaml": yaml.safe_dump({
            "id": shiki_id,
            "name": name,
            "versions": {"history": [{
                "date": date, "faction": "苍叶", "power": 3, "health": 4,
            }]},
        }, allow_unicode=True, sort_keys=False),
    }
    if cards:
        for suffix in range(1, 9):
            cid = shiki_id * 100 + suffix
            files[f"01_test/{cid}.yaml"] = yaml.safe_dump({
                "id": cid, "name": f"卡{suffix}",
                "versions": {"history": [{
                    "date": date, "card_type": "spell", "rarity": "R", "level": 1,
                    "effects": {"steps": []}, "text": "测试",
                }]},
            }, allow_unicode=True, sort_keys=False)
    if event is not None:
        files["events.yaml"] = yaml.safe_dump(
            [{"name": event, "timing": "queue"}], allow_unicode=True)
        data = yaml.safe_load(files["01_test/shiki.yaml"])
        data["versions"]["history"][0]["ability"] = {"when": event, "steps": []}
        files["01_test/shiki.yaml"] = yaml.safe_dump(data, allow_unicode=True)
    from diy.sync import read_package_data
    return read_package_data(files)


def write_package(root, package):
    target = root / str(package["pack_id"])
    for name, text in package["files"].items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return target


class FakeWS:
    def __init__(self):
        self.messages = []

    async def send_text(self, text):
        self.messages.append(json.loads(text))

    async def close(self, code=1000):
        pass

    def of_type(self, kind):
        return [message for message in self.messages if message["type"] == kind]


def run(coro):
    return asyncio.run(coro)


def official_deck(db):
    return deckcode.encode_deck(deckcode.group_deck(db, F.TEAM, F.deck_of(*F.TEAM)))


async def ready_diy_room(db, *, env_date=None):
    room = Room("DIY001", db, official_db=db, diy=True, env_date=env_date,
                mode="free" if env_date is not None else "standard",
                starting_timeout=60, rng=random.Random(1))
    sockets = [FakeWS(), FakeWS()]
    code = official_deck(db)
    await room.join(0, "甲", sockets[0], code)
    await room.join(1, "乙", sockets[1], code)
    await room.on_seat_filled()
    await room.lobby_ready(0)
    await room.lobby_ready(1)
    assert room._lobby_phase == "diy_syncing"
    assert not sockets[0].of_type("starting")
    return room, sockets


def manifest(*packages):
    return [{"pack_id": package["pack_id"], "content_hash": package["content_hash"]}
            for package in packages]


def test_package_hash_uses_normalized_yaml_and_ignores_embedded_hash():
    from diy.sync import content_hash, read_package_data

    package = make_package()
    first = dict(package["files"])
    second = dict(package["files"])
    metadata = yaml.safe_load(second["pack.yaml"])
    metadata["content_hash"] = "0" * 64
    second["pack.yaml"] = yaml.safe_dump(metadata, sort_keys=True)
    shiki = yaml.safe_load(second["01_test/shiki.yaml"])
    second["01_test/shiki.yaml"] = yaml.safe_dump(shiki, sort_keys=True)
    assert content_hash(first) == content_hash(second)
    assert package["content_hash"] == content_hash(first)

    changed = dict(first)
    changed["01_test/shiki.yaml"] = first["01_test/shiki.yaml"].replace("power: 3", "power: 4")
    assert read_package_data(changed)["content_hash"] != package["content_hash"]


def test_package_validation_rejects_code_and_hash_mismatch():
    from diy.sync import read_package_data, validate_package

    package = make_package()
    with_code = dict(package["files"], **{"mechanisms.py": "raise RuntimeError('不得执行')"})
    with pytest.raises(ValueError, match="YAML"):
        read_package_data(with_code)
    with pytest.raises(ValueError, match="哈希"):
        validate_package({**package, "content_hash": "f" * 64})


def test_download_store_atomic_versions_and_owned_content_cleanup(tmp_path):
    from diy.store import clear_downloaded, download_stats, save_download

    root = tmp_path / "downloads"
    own = tmp_path / "own"
    first = make_package(201)
    second = make_package(202)
    save_download(first, root=root)
    save_download(first, root=root)  # 重复下载幂等
    save_download(second, root=root)
    own_pack = write_package(own, make_package(203))
    marker = root / "201" / first["content_hash"] / ".download.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["source"] == "downloaded"
    assert download_stats(root)["packs"] == 2
    with pytest.raises(ValueError, match="离开"):
        clear_downloaded(root, active={(201, first["content_hash"])})
    removed = clear_downloaded(root)
    assert removed["packs"] == 2 and removed["bytes"] > 0
    assert not root.exists() or not list(root.rglob("pack.yaml"))
    assert (own_pack / "pack.yaml").exists()


def test_failed_download_leaves_no_partial_version(tmp_path, monkeypatch):
    from diy import store

    package = make_package(201, cards=True)
    original = store._write_package_files

    def fail_after_one(directory, files):
        original(directory, dict(list(files.items())[:2]))
        raise OSError("磁盘写入失败")

    monkeypatch.setattr(store, "_write_package_files", fail_after_one)
    with pytest.raises(OSError, match="磁盘写入失败"):
        store.save_download(package, root=tmp_path / "downloads")
    assert not list((tmp_path / "downloads").rglob("pack.yaml"))
    assert not list((tmp_path / "downloads").rglob("*.tmp"))


def test_downloaded_loading_selects_hash_and_never_executes_code(tmp_path, monkeypatch):
    from diy.runtime import load_database
    from diy import store

    root = tmp_path / "downloads"
    monkeypatch.setattr(store, "download_root", lambda: root)
    official = tmp_path / "official"
    official.mkdir()
    first = store.save_download(make_package(201, name="旧版"), root=root)
    store.save_download(make_package(201, name="新版", date=20261114), root=root)
    marker = tmp_path / "executed"
    (first / "mechanisms.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8")
    shiki_id = 120101
    db = load_database(official_root=official, include_builtin=False,
                       download_versions={201: first.name})
    assert db.shikigami[shiki_id].name == "旧版"
    assert not marker.exists()
    assert load_database(official_root=official, include_builtin=False,
                         include_downloaded=False).shikigami == {}
    assert db.at_date(20261113).shikigami[shiki_id].version == 20261113
    assert shiki_id not in db.at_date(20261112).shikigami


def test_normal_room_ready_flow_has_no_diy_sync(db):
    async def go():
        room = Room("NORMAL", db, starting_timeout=60, rng=random.Random(1))
        sockets = [FakeWS(), FakeWS()]
        code = official_deck(db)
        await room.join(0, "甲", sockets[0], code)
        await room.join(1, "乙", sockets[1], code)
        await room.lobby_ready(0)
        await room.lobby_ready(1)
        assert room._lobby_phase == "starting"
        assert sockets[0].of_type("starting")
        assert not sockets[0].of_type("diy_sync_request")
        room._cancel_lobby_timer()
    run(go())


def test_ready_starts_manifest_exchange_and_one_way_package_transfer(db):
    async def go():
        room, sockets = await ready_diy_room(db)
        package = make_package(201)
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, [])
        upload = sockets[0].of_type("diy_upload_request")[-1]
        assert upload["pack_id"] == 201
        await room.handle_diy_pack(0, package)
        downloaded = sockets[1].of_type("diy_package")[-1]["package"]
        assert downloaded["content_hash"] == package["content_hash"]
        assert "mechanisms.py" not in downloaded["files"]
        await room.handle_diy_sync_done(0)
        assert room._lobby_phase == "diy_syncing"
        await room.handle_diy_sync_done(1)
        assert room._lobby_phase == "starting"
        assert room.diy_packages[201]["content_hash"] == package["content_hash"]
        room._cancel_lobby_timer()
    run(go())


def test_bidirectional_missing_packages_upload_and_download(db):
    async def go():
        room, sockets = await ready_diy_room(db)
        first, second = make_package(201), make_package(202)
        await room.handle_diy_manifest(0, manifest(first))
        await room.handle_diy_manifest(1, manifest(second))
        assert sockets[0].of_type("diy_upload_request")[0]["pack_id"] == 201
        assert sockets[1].of_type("diy_upload_request")[0]["pack_id"] == 202
        await room.handle_diy_pack(0, first)
        await room.handle_diy_pack(1, second)
        assert sockets[0].of_type("diy_package")[0]["package"]["pack_id"] == 202
        assert sockets[1].of_type("diy_package")[0]["package"]["pack_id"] == 201
        await room.handle_diy_sync_done(0)
        await room.handle_diy_sync_done(1)
        assert set(room.diy_packages) == {201, 202}
        assert room._lobby_phase == "starting"
        room._cancel_lobby_timer()
    run(go())


def test_same_pack_different_hash_and_cross_pack_entity_conflict_abort(db):
    async def version_conflict():
        room, _ = await ready_diy_room(db)
        first = make_package(201)
        changed = make_package(201, name="另一版本")
        await room.handle_diy_manifest(0, manifest(first))
        await room.handle_diy_manifest(1, manifest(changed))
        assert room._lobby_phase == "diy_failed"
        assert not room.diy_packages

    async def entity_conflict():
        room, sockets = await ready_diy_room(db)
        shiki_id = 120101
        first = make_package(201, shiki_id=shiki_id)
        second = make_package(202, shiki_id=shiki_id)
        await room.handle_diy_manifest(0, manifest(first))
        await room.handle_diy_manifest(1, manifest(second))
        await room.handle_diy_pack(0, first)
        await room.handle_diy_pack(1, second)
        assert room._lobby_phase == "diy_failed"
        assert "120101" in sockets[0].of_type("diy_sync_failed")[-1]["reason"]

    run(version_conflict())
    run(entity_conflict())


def test_unknown_custom_event_is_not_registered_by_upload(db):
    async def go():
        room, sockets = await ready_diy_room(db)
        package = make_package(201, event="untrusted_network_event")
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, [])
        await room.handle_diy_pack(0, package)
        assert room._lobby_phase == "diy_failed"
        assert "事件" in sockets[0].of_type("diy_sync_failed")[-1]["reason"]
        from core.events import EVENT_TIMING
        assert "untrusted_network_event" not in EVENT_TIMING
    run(go())


def test_environment_revalidates_synced_deck_before_countdown(db):
    async def go():
        room, sockets = await ready_diy_room(db, env_date=20261112)
        package = make_package(201, cards=True)
        shiki_id = 120101
        groups = [(shiki_id, [shiki_id * 100 + i for i in range(1, 9)])]
        groups += [(sid, [sid * 100 + i for i in range(1, 9)]) for sid in F.TEAM[:3]]
        room.conns[0].deck_code = deckcode.encode_deck(groups)
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, [])
        await room.handle_diy_pack(0, package)
        await room.handle_diy_sync_done(0)
        await room.handle_diy_sync_done(1)
        assert room._lobby_phase == "diy_failed"
        assert "环境" in sockets[0].of_type("diy_sync_failed")[-1]["reason"]
        assert not sockets[0].of_type("starting")
    run(go())


def test_duplicate_sync_messages_and_room_release_are_safe(db):
    async def go():
        manager = RoomManager(db)
        room = manager.create(room_id="DIY002", diy=True)
        room.starting_timeout = 60
        sockets = [FakeWS(), FakeWS()]
        code = official_deck(db)
        await room.join(0, "甲", sockets[0], code)
        await room.join(1, "乙", sockets[1], code)
        await room.lobby_ready(0)
        await room.lobby_ready(1)
        package = make_package(201)
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, [])
        await room.handle_diy_pack(0, package)
        await room.handle_diy_pack(0, package)
        assert len(sockets[1].of_type("diy_package")) == 1
        snapshot = room.diy_packages
        await room.reconnect(room.conns[1].token, FakeWS())
        assert room.diy_packages is snapshot
        manager.remove(room.id)
        assert not room.diy_packages
        assert not room._diy_manifests
    run(go())


def test_reconnect_resends_room_snapshot_for_exact_hash(db):
    async def go():
        room, sockets = await ready_diy_room(db)
        package = make_package(201)
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, [])
        await room.handle_diy_pack(0, package)
        replacement = FakeWS()
        conn = await room.reconnect(room.conns[1].token, replacement)
        snapshot = room.diy_packages
        await room.resync_diy(conn)
        assert room.diy_packages is snapshot
        resent = replacement.of_type("diy_package")
        assert len(resent) == 1
        assert resent[0]["package"]["content_hash"] == package["content_hash"]
    run(go())


def test_trusted_pack_reuse_rechecks_current_disk_hash(db, tmp_path):
    async def go():
        original = make_package(201)
        changed = make_package(201, name="启动后修改")
        source = write_package(tmp_path, changed)
        room, sockets = await ready_diy_room(db)
        room._trusted_db.diy_packs = {
            201: {"content_hash": original["content_hash"], "source": source},
        }
        await room.handle_diy_manifest(0, manifest(original))
        await room.handle_diy_manifest(1, manifest(original))
        assert room._lobby_phase == "diy_failed"
        assert "哈希" in sockets[0].of_type("diy_sync_failed")[-1]["reason"]
    run(go())


def test_builtin_trusted_pack_reuses_server_content_and_starts():
    from diy.runtime import load_database
    from diy.sync import read_package

    from db.loader import CardDatabase

    trusted = load_database()
    official = CardDatabase.load()
    package = read_package(trusted.diy_packs[101]["source"])
    official_groups = []
    for shiki in official.shikigami.values():
        cards = [card.id for card in official.cards.values()
                 if card.shikigami == shiki.id and not card.token and not card.unreleased
                 and card.card_type != "reinforce" and 1 <= card.id % 100 <= 8]
        if shiki.kind == "shikigami" and shiki.faction == "苍叶" and len(cards) == 8:
            official_groups.append((shiki.id, sorted(cards)))

    async def go():
        room = Room("DIY003", trusted, official_db=official, diy=True,
                    starting_timeout=0.01, rng=random.Random(1))
        sockets = [FakeWS(), FakeWS()]
        groups = [(110101, [11010100 + i for i in range(1, 9)])]
        groups += official_groups[:3]
        code = deckcode.encode_deck(groups)
        await room.join(0, "甲", sockets[0], code)
        await room.join(1, "乙", sockets[1], code)
        await room.lobby_ready(0)
        await room.lobby_ready(1)
        await room.handle_diy_manifest(0, manifest(package))
        await room.handle_diy_manifest(1, manifest(package))
        assert not sockets[0].of_type("diy_upload_request")
        await room.handle_diy_sync_done(0)
        await room.handle_diy_sync_done(1)
        await asyncio.sleep(0.05)
        assert room.game is not None
        assert 110101 in room.game.db.shikigami
        room._cancel_timer()
    run(go())
