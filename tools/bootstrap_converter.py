#!/usr/bin/env python3
"""Create an isolated source-development environment and launch the GUI."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv-ovid"
REQUIREMENTS = ROOT / "tools" / "requirements-converter.txt"
GUI = ROOT / "tools" / "ovid_converter_gui.py"
REQUIRED_MODULES = ("flet", "flet_desktop", "PIL", "imageio_ffmpeg")


def environment_python() -> Path:
    if sys.platform == "win32":
        return ENVIRONMENT / "Scripts" / "python.exe"
    return ENVIRONMENT / "bin" / "python"


def modules_available(python: Path) -> bool:
    expression = ";".join(
        f"assert importlib.util.find_spec({module!r}) is not None" for module in REQUIRED_MODULES
    )
    result = subprocess.run(
        [str(python), "-c", "import importlib.util;" + expression],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def confirm_install() -> bool:
    print("\nOVID Converter 首次运行需要创建项目专用 Python 环境，并安装：")
    print("  - Flet / Flet Desktop：Material 3 桌面界面")
    print("  - Pillow：图片和 GIF 处理")
    print("  - imageio-ffmpeg：视频解码和 FFmpeg")
    print(f"\n环境位置：{ENVIRONMENT}")
    print("这些依赖只安装到项目目录，不会修改全局 Python。")
    return input("是否继续？[y/N] ").strip().casefold() in {"y", "yes"}


def main() -> int:
    if sys.version_info < (3, 10):
        print("错误：源码运行 OVID Converter 需要 Python 3.10 或更高版本。")
        return 1

    python = environment_python()
    needs_install = not python.is_file() or not modules_available(python)
    if needs_install:
        if not confirm_install():
            print("已取消，没有安装任何依赖。")
            return 1
        if not python.is_file():
            print("正在创建 .venv-ovid ...")
            venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)
        print("正在安装转换器依赖 ...")
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)]
        )
        if result.returncode != 0:
            print("依赖安装失败。请检查网络后重新运行，或执行：")
            print(f'"{python}" -m pip install -r "{REQUIREMENTS}"')
            return result.returncode

    return subprocess.call([str(python), str(GUI)])


if __name__ == "__main__":
    raise SystemExit(main())

