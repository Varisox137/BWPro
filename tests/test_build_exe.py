"""Windows 独立 exe 构建的资源收集契约。"""
import importlib
import os
from pathlib import Path


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
