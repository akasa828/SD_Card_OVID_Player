#!/usr/bin/env python3
"""Shared OVID container writer used by all conversion tools."""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


MAGIC = b"OVID"
HEADER_SIZE = 16
OVID_V1 = 0
OVID_V2 = 2
OVID_FLAG_CRC32 = 0x01


class OvidWriteCancelled(RuntimeError):
    """Raised when the caller cancels a streaming write."""


@dataclass(frozen=True)
class OvidSummary:
    path: Path
    width: int
    height: int
    frame_count: int
    fps: int
    frame_bytes: int
    file_bytes: int
    version: int


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame_bytes(width: int, height: int) -> int:
    """Return the page-major payload size of one monochrome frame."""
    return ((height + 7) // 8) * width


def validate_parameters(width: int, height: int, fps: int, version: int) -> None:
    if not (1 <= width <= 255 and 1 <= height <= 255):
        raise ValueError("宽高须在 1~255（OVID 头部字段各占 1 字节）")
    if not 1 <= fps <= 120:
        raise ValueError("fps 须在 1~120")
    if version not in (OVID_V1, OVID_V2):
        raise ValueError("OVID 版本只能是 v1 或 v2")


def make_header(width: int, height: int, count: int, fps: int, version: int) -> bytes:
    validate_parameters(width, height, fps, version)
    if not 0 <= count <= 0xFFFFFFFF:
        raise ValueError("帧数超出 OVID 32 位字段范围")
    flags = OVID_FLAG_CRC32 if version == OVID_V2 else 0
    first14 = struct.pack("<4sBBBBIH", MAGIC, width, height, version, flags, count, fps)
    header_crc = crc16_ccitt(first14) if version == OVID_V2 else 0
    return first14 + struct.pack("<H", header_crc)


def write_ovid(
    out_path: Path | str,
    frames: Iterable[bytes],
    width: int,
    height: int,
    fps: int,
    version: int = OVID_V2,
    *,
    on_frame: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> OvidSummary:
    """Stream page-major frames to an OVID file and return its final metadata."""
    validate_parameters(width, height, fps, version)
    output = Path(out_path)
    expected = frame_bytes(width, height)
    count = 0

    with output.open("wb") as stream:
        stream.write(make_header(width, height, 0, fps, version))
        for data in frames:
            if cancelled is not None and cancelled():
                raise OvidWriteCancelled("转换已取消")
            if len(data) != expected:
                raise ValueError(
                    f"第 {count + 1} 帧长度 {len(data)} 字节，与 {width}x{height} "
                    f"应有的 {expected} 字节不符"
                )
            stream.write(data)
            if version == OVID_V2:
                stream.write(struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF))
            count += 1
            if on_frame is not None:
                on_frame(count)

        if count == 0:
            raise ValueError("没有取到任何帧")
        stream.seek(0)
        stream.write(make_header(width, height, count, fps, version))

    size = HEADER_SIZE + count * (expected + (4 if version == OVID_V2 else 0))
    return OvidSummary(output, width, height, count, fps, expected, size, version)


def write_ovid_atomic(
    out_path: Path | str,
    frames: Iterable[bytes],
    width: int,
    height: int,
    fps: int,
    *,
    force: bool = False,
    on_frame: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> OvidSummary:
    """Write OVID v2 through a sibling .part file and atomically publish it."""
    output = Path(out_path)
    if not output.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在：{output.parent}")
    if output.exists() and not force:
        raise FileExistsError(f"输出文件已存在：{output}")

    temporary = output.with_name(output.name + ".part")
    try:
        summary = write_ovid(
            temporary,
            frames,
            width,
            height,
            fps,
            OVID_V2,
            on_frame=on_frame,
            cancelled=cancelled,
        )
        os.replace(temporary, output)
        return OvidSummary(
            output,
            summary.width,
            summary.height,
            summary.frame_count,
            summary.fps,
            summary.frame_bytes,
            summary.file_bytes,
            summary.version,
        )
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
