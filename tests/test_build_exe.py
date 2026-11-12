"""Windows 独立 exe 构建的资源收集契约。"""
import importlib
import os
from pathlib import Path

import pytest


def test_exe_data_include_all_standalone_runtime_resources():
    build = importlib.import_module("scripts.build_exe")
    args = build._datas_args()
    values = [args[index + 1] for index, arg in enumerate(args) if arg == "--add-data"]
    sources = [Path(value.split(os.pathsep, 1)[0]) for value in values]

    assert build.ROOT / "assets" / "levels" / "base.png" in sources
    assert any(path.parent == build.ROOT / "assets" / "fonts" for path in sources)
    assert any(build.ROOT / "db" in path.parents and path.suffix == ".yaml"
               for path in sources)
    assert any(build.ROOT / "library" in path.parents for path in sources)
    code_root = build.bwpdiy_code_root(build.ROOT)
    assert code_root / "bwpdiy" / "render" / "default_layout.json" in sources
    assert build.ROOT / "assets" / "layout.json" not in sources


def test_exe_build_uses_local_application_icon(monkeypatch):
    build = importlib.import_module("scripts.build_exe")
    import PyInstaller.__main__

    calls = []
    monkeypatch.setattr(PyInstaller.__main__, "run", calls.append)
    build._build()

    args = calls[0]
    assert "--icon" in args
    icon = Path(args[args.index("--icon") + 1])
    assert icon == build.ROOT / "assets" / "app_icon.ico"
    assert icon.is_file()


@pytest.mark.parametrize(("second_start_adds_png", "skipped"), [
    (False, 1),
    (True, 1),
    (False, 0),
])
def test_exe_smoke_requires_cache_reuse_and_skipped_manifest(
        tmp_path, monkeypatch, second_start_adds_png, skipped):
    import json
    import subprocess
    build = importlib.import_module("scripts.build_exe")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    runs = []

    def run(command, cwd, env, check, timeout):
        assert check is True and timeout == 180
        runs.append((command, cwd, env["HOME"], env["USERPROFILE"]))
        cache = Path(env["HOME"]) / ".bwpro" / "cardart"
        cache.mkdir(parents=True, exist_ok=True)
        if len(runs) == 1:
            (cache / "card.png").write_bytes(b"png")
        elif second_start_adds_png:
            (cache / "second.png").write_bytes(b"png")
        (cache / "manifest.json").write_text(json.dumps({
            "stats": {"total": 1, "succeeded": 1, "failed": 0, "skipped": skipped},
        }), encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", run)
    if second_start_adds_png or not skipped:
        with pytest.raises(AssertionError):
            build._smoke_test(tmp_path / "BWPro.exe")
    else:
        build._smoke_test(tmp_path / "BWPro.exe")

    assert len(runs) == 2
    assert runs[0] == runs[1]


def test_exe_version_uses_shared_runtime_constant():
    build = importlib.import_module("scripts.build_exe")
    from core.version import VERSION

    assert build.VERSION == VERSION == "0.3.0"
    assert build.EXE_NAME == "BWPro-v0.3.0"


def test_launcher_dispatches_apply_update_before_gui(monkeypatch):
    import client.update
    from scripts import gui_launcher

    calls = []
    monkeypatch.setattr(
        client.update, "apply_update_command", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(
        gui_launcher.sys, "argv",
        ["BWPro.exe", "--apply-update", "12", "target", "new", "abc"])
    monkeypatch.setattr(
        gui_launcher, "_smoke_test", lambda: pytest.fail("更新模式不得进入 GUI 冒烟"))

    assert gui_launcher.main() == 0
    assert calls == [["12", "target", "new", "abc"]]


def test_launcher_passes_hidden_cleanup_to_normal_gui_startup(monkeypatch, tmp_path):
    import client.gui.app
    from scripts import gui_launcher

    updater_dir = tmp_path / "bwpro-update-test"
    calls = []
    monkeypatch.setattr(
        gui_launcher.sys, "argv",
        ["BWPro.exe", "--cleanup-update", "88", str(updater_dir)])
    monkeypatch.setattr(
        client.gui.app, "main", lambda *, cleanup=None: calls.append(cleanup) or 0)
    monkeypatch.setattr(
        gui_launcher, "_smoke_test", lambda: pytest.fail("清理参数不得进入 GUI 冒烟"))

    assert gui_launcher.main() == 0
    assert calls == [(88, updater_dir)]
