#!/usr/bin/env python3
"""Collect installed package license files for the portable distribution."""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGES = ("flet", "flet-desktop", "Pillow", "imageio-ffmpeg")
FONT_LICENSE_FILES = ("OFL-1.1.txt", "FONT_SOURCES.md")


def collect(output_root: Path, app_root: Path | None = None) -> None:
    destination = output_root / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    notices = Path(__file__).resolve().parent / "THIRD_PARTY_NOTICES.txt"
    shutil.copy2(notices, output_root / notices.name)

    font_root = Path(__file__).resolve().parent / "assets" / "fonts"
    for filename in FONT_LICENSE_FILES:
        shutil.copy2(font_root / filename, destination / filename)

    for package in PACKAGES:
        distribution = importlib.metadata.distribution(package)
        copied = 0
        for entry in distribution.files or ():
            name = Path(str(entry)).name.casefold()
            if not (name.startswith("license") or name.startswith("copying") or name == "notice"):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            safe_name = f"{package.replace('-', '_')}_{copied}_{source.name}"
            shutil.copy2(source, destination / safe_name)
            copied += 1

    # Flet declares Apache-2.0 through package metadata but does not ship a
    # separate text file. Packaging carries the same standard Apache-2.0 text.
    packaging = importlib.metadata.distribution("packaging")
    for entry in packaging.files or ():
        if Path(str(entry)).name.casefold() == "license.apache":
            shutil.copy2(packaging.locate_file(entry), destination / "Flet_Apache-2.0.txt")
            break

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, destination / "Python-LICENSE.txt")

    if app_root is not None:
        for source in app_root.rglob("*"):
            if source.is_file() and source.name.casefold() in {"notice", "notices", "notices.txt"}:
                relative = "_".join(source.relative_to(app_root).parts)
                shutil.copy2(source, destination / f"Flutter_{relative}")

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        license_text = subprocess.check_output(
            [ffmpeg, "-L"], text=True, encoding="utf-8", errors="replace"
        )
        (destination / "FFmpeg-LICENSE.txt").write_text(license_text, encoding="utf-8")
    except (ImportError, OSError, subprocess.SubprocessError):
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
    )
    parser.add_argument("--app-root", type=Path)
    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    collect(arguments.output_root.resolve(), arguments.app_root.resolve() if arguments.app_root else None)
