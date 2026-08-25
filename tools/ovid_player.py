#!/usr/bin/env python3
"""Small desktop-side simulator for the STM32 OVID playback behavior."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from ovid_codec import OvidHeader, OvidReader


def page_major_to_image(data: bytes, width: int, height: int, *, invert: bool = False):
    from PIL import Image, ImageOps

    pages = (height + 7) // 8
    if len(data) != pages * width:
        raise ValueError(f"帧长度 {len(data)} B，应为 {pages * width} B")
    image = Image.new("1", (width, height), 0)
    pixels = image.load()
    for page in range(pages):
        for x in range(width):
            value = data[page * width + x]
            for bit in range(8):
                y = page * 8 + bit
                if y < height and value & (1 << bit):
                    pixels[x, y] = 255
    if invert:
        image = ImageOps.invert(image.convert("L")).convert("1")
    return image


def frame_png(
    data: bytes,
    width: int,
    height: int,
    *,
    invert: bool = False,
    scale: int = 4,
) -> bytes:
    from PIL import Image

    image = page_major_to_image(data, width, height, invert=invert)
    if scale > 1:
        image = image.resize((width * scale, height * scale), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@dataclass(frozen=True)
class SimulatedFrame:
    index: int
    png: bytes
    crc_valid: bool
    held_previous: bool


class OvidPlaybackSession:
    """Random-access player which holds the last valid frame on CRC errors."""

    def __init__(self):
        self.path: Path | None = None
        self.reader: OvidReader | None = None
        self.header: OvidHeader | None = None
        self.last_valid: bytes | None = None
        self.index = -1

    def close(self) -> None:
        if self.reader is not None:
            self.reader.__exit__(None, None, None)
        self.reader = None
        self.header = None
        self.last_valid = None
        self.index = -1

    def open(self, path: Path | str) -> OvidHeader:
        self.close()
        self.path = Path(path)
        self.reader = OvidReader(self.path)
        self.reader.__enter__()
        self.header = self.reader.header
        self.last_valid = bytes(self.header.frame_bytes)
        self.index = -1
        return self.header

    def read(self, index: int, *, invert: bool = False, scale: int = 4) -> SimulatedFrame:
        if self.reader is None or self.header is None:
            raise ValueError("请先打开 OVID 文件")
        frame = self.reader.read_frame(index)
        held_previous = not frame.crc_valid
        if frame.crc_valid:
            self.last_valid = frame.data
        data = self.last_valid if held_previous else frame.data
        assert data is not None
        return self._render_frame(index, data, frame.crc_valid, held_previous, invert, scale)

    def _render_frame(
        self,
        index: int,
        data: bytes,
        crc_valid: bool,
        held_previous: bool,
        invert: bool,
        scale: int,
    ) -> SimulatedFrame:
        assert self.header is not None
        self.index = index
        return SimulatedFrame(
            index,
            frame_png(
                data,
                self.header.width,
                self.header.height,
                invert=invert,
                scale=scale,
            ),
            crc_valid,
            held_previous,
        )

    def next(self, *, invert: bool = False, scale: int = 4) -> SimulatedFrame:
        if self.header is None:
            raise ValueError("请先打开 OVID 文件")
        return self.read(min(self.header.frame_count - 1, self.index + 1), invert=invert, scale=scale)

    def previous(self, *, invert: bool = False, scale: int = 4) -> SimulatedFrame:
        if self.header is None:
            raise ValueError("请先打开 OVID 文件")
        return self.seek(max(0, self.index - 1), invert=invert, scale=scale)

    def seek(self, index: int, *, invert: bool = False, scale: int = 4) -> SimulatedFrame:
        if self.header is None or self.reader is None:
            raise ValueError("请先打开 OVID 文件")
        target = min(self.header.frame_count - 1, max(0, index))
        if target == self.index + 1:
            return self.read(target, invert=invert, scale=scale)
        frame = self.reader.read_frame(target)
        if frame.crc_valid:
            self.last_valid = frame.data
            return self._render_frame(
                target,
                frame.data,
                True,
                False,
                invert,
                scale,
            )

        previous = bytes(self.header.frame_bytes)
        for frame_index in range(target - 1, -1, -1):
            candidate = self.reader.read_frame(frame_index)
            if candidate.crc_valid:
                previous = candidate.data
                break
        self.last_valid = previous
        return self._render_frame(
            target,
            previous,
            False,
            True,
            invert,
            scale,
        )
