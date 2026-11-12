"""构建 BWPro Windows 独立单文件 GUI，并执行离屏冒烟测试。

用法（Windows Git Bash）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/build_exe.py
    # 仅构建，不运行产物：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/build_exe.py --no-smoke
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client.gui.portrait import bwpdiy_code_root  # noqa: E402
from core.version import VERSION  # noqa: E402

EXE_NAME = f"BWPro-v{VERSION}"


def _add_data(source: Path, destination: str) -> list[str]:
    return ["--add-data", f"{source}{os.pathsep}{destination}"]


def _datas_args() -> list[str]:
    """内嵌通用素材、规则数据、卡图库与 BWPDIY 默认布局；不含用户全局布局。"""
    args: list[str] = []
    for directory in (ROOT / "assets", ROOT / "db", ROOT / "library"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path == ROOT / "assets" / "layout.json":
                continue
            args += _add_data(path, str(path.relative_to(ROOT).parent))
    code_root = bwpdiy_code_root(ROOT)
    default_layout = code_root / "bwpdiy" / "render" / "default_layout.json"
    args += _add_data(default_layout, "bwpdiy/render")
    return args


def _build() -> Path:
    import PyInstaller.__main__

    code_root = bwpdiy_code_root(ROOT)
    args = [
        str(ROOT / "scripts" / "gui_launcher.py"),
        "--name", EXE_NAME,
        "--onefile",
        "--windowed",
        "--icon", str(ROOT / "assets" / "app_icon.ico"),
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT),
        "--paths", str(code_root),
        "--collect-submodules", "bwpdiy",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    args += _datas_args()
    PyInstaller.__main__.run(args)
    return ROOT / "dist" / f"{EXE_NAME}.exe"


def _smoke_test(executable: Path) -> None:
    smoke_home = ROOT / "build" / "smoke_home"
    smoke_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": str(smoke_home),
        "USERPROFILE": str(smoke_home),
        "PYTHONIOENCODING": "utf-8",
    })
    command = [str(executable), "--smoke-test"]
    cache_dir = smoke_home / ".bwpro" / "cardart"
    subprocess.run(command, cwd=smoke_home, env=env, check=True, timeout=180)
    first_pngs = set(cache_dir.glob("*.png"))
    subprocess.run(command, cwd=smoke_home, env=env, check=True, timeout=180)
    second_pngs = set(cache_dir.glob("*.png"))
    added = second_pngs - first_pngs
    assert not added, f"第二次启动新增卡图缓存：{sorted(path.name for path in added)}"
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    stats = manifest["stats"]
    assert stats["total"] > 0 and stats["failed"] == 0, stats
    assert stats["skipped"] == stats["total"], stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-smoke", action="store_true", help="构建后不运行离屏冒烟测试")
    options = parser.parse_args(argv)
    built = _build()
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    destination = releases / built.name
    shutil.copy2(built, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_name(destination.name + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="utf-8", newline="\n")
    if not options.no_smoke:
        _smoke_test(destination)
    print(f"已输出：{destination}（{destination.stat().st_size / 1024 / 1024:.1f} MB）")
    print(f"SHA-256：{checksum}")
    if not options.no_smoke:
        print("离屏冒烟测试：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
