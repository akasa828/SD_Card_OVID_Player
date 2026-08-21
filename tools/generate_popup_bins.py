#!/usr/bin/env python3
"""生成用于检查播放器弹窗、反显和 CRC 处理的 OVID 测试文件。

默认直接写入脚本所在的 tools 目录；也可以把输出目录作为唯一参数传入。
脚本只使用 Python 标准库，不依赖 Pillow。
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


MAGIC = b"OVID"
OVID_V2 = 2
OVID_FLAG_CRC32 = 0x01


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def make_header(width: int, height: int, count: int, fps: int,
                version: int = OVID_V2, flags: int = OVID_FLAG_CRC32,
                valid_crc: bool = True) -> bytes:
    first14 = struct.pack("<4sBBBBIH", MAGIC, width, height, version, flags, count, fps)
    header_crc = crc16_ccitt(first14) if valid_crc else 0
    return first14 + struct.pack("<H", header_crc)


def set_pixel(frame: bytearray, width: int, x: int, y: int) -> None:
    if 0 <= x < width and y >= 0:
        frame[(y // 8) * width + x] |= 1 << (y & 7)


def make_frame(width: int, height: int, phase: int) -> bytes:
    """生成边框、移动块和斜线，正常/反显时都容易辨认。"""
    frame = bytearray(((height + 7) // 8) * width)
    for x in range(width):
        set_pixel(frame, width, x, 0)
        set_pixel(frame, width, x, height - 1)
    for y in range(height):
        set_pixel(frame, width, 0, y)
        set_pixel(frame, width, width - 1, y)
        set_pixel(frame, width, (y * 2 + phase * 7) % width, y)

    box_w = max(4, width // 8)
    box_h = max(4, height // 4)
    span = max(1, width - box_w - 2)
    box_x = 1 + (phase * 11) % span
    box_y = max(1, (height - box_h) // 2)
    for y in range(box_y, min(height - 1, box_y + box_h)):
        for x in range(box_x, min(width - 1, box_x + box_w)):
            set_pixel(frame, width, x, y)
    return bytes(frame)


def write_v2(path: Path, width: int, height: int, frames: list[bytes], fps: int,
             corrupt_crc_index: int | None = None) -> None:
    output = bytearray(make_header(width, height, len(frames), fps))
    for index, frame in enumerate(frames):
        output.extend(frame)
        crc = zlib.crc32(frame) & 0xFFFFFFFF
        if index == corrupt_crc_index:
            crc ^= 0x00000001
        output.extend(struct.pack("<I", crc))
    path.write_bytes(output)


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    good_frames = [make_frame(128, 64, phase) for phase in range(12)]
    write_v2(output_dir / "POP_GOOD.BIN", 128, 64, good_frames, 15)

    # Magic 故意错误：触发 Bad OVID。
    (output_dir / "POP_BAD.BIN").write_bytes(b"NOPE" + bytes(12))

    # 版本号不受支持，但文件长度与无 CRC 帧匹配：触发 Invalid OVID。
    invalid_frame = make_frame(128, 64, 0)
    invalid_header = make_header(128, 64, 1, 15, version=7, flags=0, valid_crc=False)
    (output_dir / "POP_INV.BIN").write_bytes(invalid_header + invalid_frame)

    # 宽度 129 超过当前验收屏幕的 128 像素：触发 Frame too big。
    big_frame = make_frame(129, 64, 0)
    write_v2(output_dir / "POP_BIG.BIN", 129, 64, [big_frame], 15)

    # 第 2 帧 CRC 故意错误：固件应保留上一帧，继续播放并输出串口日志。
    crc_frames = [make_frame(128, 64, phase) for phase in range(3)]
    write_v2(output_dir / "POP_CRC.BIN", 128, 64, crc_frames, 5, corrupt_crc_index=1)

    descriptions = {
        "POP_GOOD.BIN": "Loading；播放中按 OK 后显示 Playback stopped；也用于反显测试",
        "POP_BAD.BIN": "Bad OVID",
        "POP_INV.BIN": "Invalid OVID",
        "POP_BIG.BIN": "Frame too big",
        "POP_CRC.BIN": "第 2 帧 CRC 错误，保留前帧并在串口记录",
    }
    for name, description in descriptions.items():
        path = output_dir / name
        print(f"{name:<12} {path.stat().st_size:>6} B  {description}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", nargs="?", type=Path,
                        default=Path(__file__).resolve().parent,
                        help="输出目录（默认为 tools）")
    args = parser.parse_args()
    generate(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
