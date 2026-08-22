#!/usr/bin/env python3
"""Shared OVID container reader and writer used by all conversion tools."""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, Iterator


MAGIC = b"OVID"
HEADER_SIZE = 16
OVID_V1 = 0
OVID_V2 = 2
OVID_FLAG_CRC32 = 0x01


class OvidWriteCancelled(RuntimeError):
    """Raised when the caller cancels a streaming write."""


class OvidFormatError(ValueError):
    """Raised when an OVID container is truncated or has invalid metadata."""


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


@dataclass(frozen=True)
class OvidHeader:
    width: int
    height: int
    frame_count: int
    fps: int
    frame_bytes: int
    version: int
    flags: int

    @property
    def record_bytes(self) -> int:
        return self.frame_bytes + (4 if self.version == OVID_V2 else 0)

    @property
    def expected_file_bytes(self) -> int:
        return HEADER_SIZE + self.frame_count * self.record_bytes


@dataclass(frozen=True)
class OvidFrame:
    index: int
    data: bytes
    crc_valid: bool


@dataclass(frozen=True)
class OvidValidation:
    path: Path
    header: OvidHeader
    file_bytes: int
    bad_frames: tuple[int, ...]

    @property
    def valid(self) -> bool:
        return not self.bad_frames and self.file_bytes == self.header.expected_file_bytes


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


def parse_header(raw: bytes) -> OvidHeader:
    """Parse and validate one 16-byte OVID v1/v2 header."""
    if len(raw) != HEADER_SIZE:
        raise OvidFormatError("文件太短，不足 16 字节 OVID 头部")
    magic, width, height, version, flags, count, fps, stored_crc = struct.unpack(
        "<4sBBBBIHH", raw
    )
    if magic != MAGIC:
        raise OvidFormatError(f"magic 是 {magic!r}，不是 {MAGIC!r}")
    if width == 0 or height == 0 or count == 0 or not 1 <= fps <= 120:
        raise OvidFormatError(
            f"头部字段非法（{width}x{height}, {count} 帧, {fps} fps）"
        )
    if version == OVID_V1:
        if flags != 0 or stored_crc != 0:
            raise OvidFormatError("OVID v1 flags 或保留字段非法")
    elif version == OVID_V2:
        if flags != OVID_FLAG_CRC32:
            raise OvidFormatError(f"OVID v2 flags 非法：{flags:#x}")
        actual_crc = crc16_ccitt(raw[:14])
        if stored_crc != actual_crc:
            raise OvidFormatError(
                f"OVID 头部 CRC16 不匹配：{stored_crc:#06x} != {actual_crc:#06x}"
            )
    else:
        raise OvidFormatError(f"不支持的 OVID 版本字段：{version}")
    return OvidHeader(
        width,
        height,
        count,
        fps,
        frame_bytes(width, height),
        version,
        flags,
    )


class OvidReader:
    """Stream an OVID file without loading all frames into memory."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._stream: BinaryIO | None = None
        self.header: OvidHeader | None = None

    def __enter__(self) -> "OvidReader":
        self._stream = self.path.open("rb")
        try:
            self.header = parse_header(self._stream.read(HEADER_SIZE))
        except BaseException:
            self._stream.close()
            self._stream = None
            raise
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._stream is not None:
            self._stream.close()
        self._stream = None

    def _require_open(self) -> tuple[BinaryIO, OvidHeader]:
        if self._stream is None or self.header is None:
            raise RuntimeError("OvidReader 必须在 with 语句中使用")
        return self._stream, self.header

    def seek_frame(self, index: int) -> None:
        stream, header = self._require_open()
        if not 0 <= index < header.frame_count:
            raise IndexError(f"帧索引超出范围：{index}")
        stream.seek(HEADER_SIZE + index * header.record_bytes)

    def read_frame(self, index: int) -> OvidFrame:
        stream, header = self._require_open()
        self.seek_frame(index)
        data = stream.read(header.frame_bytes)
        if len(data) != header.frame_bytes:
            raise OvidFormatError(f"第 {index + 1} 帧数据被截断")
        crc_valid = True
        if header.version == OVID_V2:
            raw_crc = stream.read(4)
            if len(raw_crc) != 4:
                raise OvidFormatError(f"第 {index + 1} 帧 CRC32 被截断")
            stored_crc = struct.unpack("<I", raw_crc)[0]
            crc_valid = stored_crc == (zlib.crc32(data) & 0xFFFFFFFF)
        return OvidFrame(index, data, crc_valid)

    def iter_frames(self) -> Iterator[OvidFrame]:
        _, header = self._require_open()
        for index in range(header.frame_count):
            yield self.read_frame(index)

    def validate(self) -> OvidValidation:
        _, header = self._require_open()
        file_bytes = self.path.stat().st_size
        if file_bytes != header.expected_file_bytes:
            raise OvidFormatError(
                f"文件长度 {file_bytes} B，应为 {header.expected_file_bytes} B"
            )
        bad_frames = tuple(frame.index for frame in self.iter_frames() if not frame.crc_valid)
        return OvidValidation(self.path, header, file_bytes, bad_frames)


def validate_ovid(path: Path | str) -> OvidValidation:
    """Validate metadata, length, and all available frame CRC values."""
    with OvidReader(path) as reader:
        return reader.validate()


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
