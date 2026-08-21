#!/usr/bin/env python3
"""h2bin.py —— 把 C 头文件中的取模数组打包成 OVID .bin 视频文件。

用法：

    python h2bin.py "Core/隐藏关卡/bad apple.h" badapple.bin -W 128 -H 64 --fps 15

输入数组默认按 Img2Lcd 的“垂直扫描”排列：同一列的各页字节连续保存。
工具会在写入 OVID 前自动转换为 OLED 页主序。已经是页主序的头文件请加 --page-major。

默认输出 OVID v2；加 --v1 可生成旧格式。两者都使用 16 字节小端头：

    offset size  字段
    0      4     magic "OVID"
    4      1     width   帧宽（像素）
    5      1     height  帧高（像素）
    6      1     version v1=0，v2=2
    7      1     flags   v2 bit0=帧 CRC32
    8      4     frame_count 总帧数
    12     2     fps     播放帧率（1~120）
    14     2     v2 头部 CRC16-CCITT；v1 为 0

帧数据紧随其后，每帧 ceil(height/8)*width 字节，OLED 页主序
（先第 0 页的第 0..width-1 列，再第 1 页……），与 OLED_Draw_Bitmap 的入参布局一致。
OVID v2 每帧数据后再附加 4 字节小端 CRC32；固件发现坏帧时保持上一帧继续播放。

固件是否能播放由 OLED_WIDTH/OLED_HEIGHT 及 MCU RAM 决定，工具不再设 1024 B 上限。
"""

import argparse
import re
import sys
import zlib
from pathlib import Path

import struct

from ovid_codec import (
    HEADER_SIZE,
    MAGIC,
    OVID_FLAG_CRC32,
    OVID_V1,
    OVID_V2,
    crc16_ccitt,
    frame_bytes,
    make_header,
    write_ovid as _write_ovid,
)


def vertical_scan_to_pagemajor(data: bytes, width: int, height: int) -> bytes:
    """把 Img2Lcd 垂直扫描的逐列排列转换为 OLED 页主序。

    Img2Lcd 垂直扫描：data[x * pages + page]
    OLED 页主序：     data[page * width + x]

    字节内部的像素位序不会改变；Img2Lcd 中仍应勾选“字节内像素数据反序”，
    使 bit0 对应该页最上方的像素。
    """
    pages = (height + 7) // 8
    expect = pages * width
    if len(data) != expect:
        raise ValueError(f"垂直扫描帧长度 {len(data)} B，应为 {expect} B")

    converted = bytearray(expect)
    for x in range(width):
        column = x * pages
        for page in range(pages):
            converted[page * width + x] = data[column + page]
    return bytes(converted)


def print_firmware_requirements(width: int, height: int) -> None:
    """输出可容纳该视频的最小屏幕宏。屏高需向上取整到 8 的倍数。"""
    screen_height = ((height + 7) // 8) * 8
    gram = frame_bytes(width, screen_height)
    print(f"  固件至少需要: OLED_WIDTH={width}, OLED_HEIGHT={screen_height}, "
          f"OLED_GRAM_SIZE={gram} B")
    if screen_height > 255:
        print("  警告：页对齐后高度超过 255，当前固件宏范围无法容纳该视频。",
              file=sys.stderr)


def write_ovid(out_path: Path, frames, width: int, height: int, fps: int,
               version: int = OVID_V2) -> None:
    """把 frames（bytes 的可迭代对象）写成 OVID 文件。

    先占位写头部，流式写完帧后回填 frame_count —— 这样无需把整个视频读进内存，
    10000+ 帧的素材也只占一帧的内存。
    """
    summary = _write_ovid(out_path, frames, width, height, fps, version)
    print(f"已写出 {out_path}")
    print(f"  OVID v{2 if version == OVID_V2 else 1}  {width}x{height}  "
          f"{summary.frame_count} 帧  "
          f"{fps} fps  每帧 {summary.frame_bytes} B  "
          f"合计 {summary.file_bytes / 1024 / 1024:.2f} MB")
    print_firmware_requirements(width, height)
    print(f"  时长约 {summary.frame_count / fps:.1f} 秒")


# ---------------------------------------------------------------- 头文件输入

# 匹配 `unsigned char BMP1[]={` / `const unsigned char gImage_1[512] = {` 等各种写法
DECL_RE = re.compile(
    r"^\s*(?:static\s+)?(?:const\s+)?unsigned\s+char\s+(\w+)\s*\[[^\]]*\]\s*=\s*\{"
)
BYTE_RE = re.compile(r"0[xX][0-9a-fA-F]+|\b\d+\b")


def natural_key(name: str):
    """让 BMP2 排在 BMP10 前面：把名字里的数字段按数值比较。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def iter_header_arrays(path: Path):
    """流式扫描 C 头文件，逐个 yield (数组名, bytes)。

    不把整个文件读进内存 —— bad apple.h 有 50MB / 75 万行。
    """
    name = None
    vals = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if name is None:
                m = DECL_RE.match(line)
                if m:
                    name = m.group(1)
                    vals = []
                    line = line[m.end():]      # 声明行尾部可能已带数据
                else:
                    continue
            # 收集数据，遇到 '}' 收尾
            end = line.find("}")
            chunk = line if end < 0 else line[:end]
            vals.extend(int(t, 0) & 0xFF for t in BYTE_RE.findall(chunk))
            if end >= 0:
                yield name, bytes(vals)
                name = None
                vals = []
    if name is not None:                        # 文件在数组中途截断
        print(f"警告：数组 {name} 没有闭合的 '}}'，已丢弃", file=sys.stderr)


def cmd_from_header(args) -> int:
    src = Path(args.header)
    if not src.is_file():
        print(f"错误：找不到 {src}", file=sys.stderr)
        return 1

    expect = frame_bytes(args.width, args.height)
    # 先扫一遍收集名字与偏移，以便按自然序输出（C 数组在文件里通常已是顺序，
    # 但 BMP1/BMP10/BMP2 这种字典序陷阱必须避开）。只存名字，不存数据。
    print(f"扫描 {src} ...")
    names = []
    for name, data in iter_header_arrays(src):
        if len(data) != expect:
            if not args.quiet:
                print(f"  跳过 {name}：{len(data)} B ≠ {expect} B", file=sys.stderr)
            continue
        names.append(name)

    if not names:
        print(f"错误：没有匹配到 {expect} 字节的数组（{args.width}x{args.height}）", file=sys.stderr)
        return 1

    order = sorted(names, key=natural_key) if not args.file_order else names
    if args.limit:
        order = order[: args.limit]
    wanted = {n: i for i, n in enumerate(order)}
    print(f"  取到 {len(order)} 帧")
    if not args.quiet:
        print("  输入排列: " + ("OLED 页主序（不转换）" if args.page_major else
                              "Img2Lcd 垂直扫描（自动转换为 OLED 页主序）"))

    # 第二遍：按 order 的顺序落盘。数组顺序与文件顺序几乎总是一致，
    # 所以缓存的帧数很少；极端情况下才会短暂多存几帧。
    def frames():
        pending = {}
        nxt = 0
        for name, data in iter_header_arrays(src):
            idx = wanted.get(name)
            if idx is None or len(data) != expect:
                continue
            if not args.page_major:
                data = vertical_scan_to_pagemajor(
                    data, args.width, args.height
                )
            pending[idx] = data
            while nxt in pending:
                yield pending.pop(nxt)
                nxt += 1
        if pending:
            raise ValueError(f"有 {len(pending)} 帧顺序错乱未能输出")

    write_ovid(Path(args.out), frames(), args.width, args.height, args.fps,
               OVID_V1 if args.v1 else OVID_V2)
    return 0


# ------------------------------------------------------------------ 校验/入口

def cmd_info(args) -> int:
    """读回一个 .bin，校验头部并报告基本信息（用于确认烧到卡上的文件没坏）。"""
    p = Path(args.file)
    with p.open("rb") as stream:
        raw = stream.read(HEADER_SIZE)
    if len(raw) < HEADER_SIZE:
        print("错误：文件太短，不足 16 字节头部", file=sys.stderr)
        return 1
    magic, w, h, version, flags, count, fps, header_crc = struct.unpack("<4sBBBBIHH", raw)
    if magic != MAGIC:
        print(f"错误：magic 是 {magic!r}，不是 {MAGIC!r}", file=sys.stderr)
        return 1

    if w == 0 or h == 0 or count == 0 or not 1 <= fps <= 120:
        print(f"错误：头部字段非法（{w}x{h}, {count} 帧, {fps} fps）", file=sys.stderr)
        return 1

    is_v1 = version == OVID_V1 and flags == 0 and header_crc == 0
    is_v2 = (version == OVID_V2 and flags == OVID_FLAG_CRC32 and
             header_crc == crc16_ccitt(raw[:14]))
    if not is_v1 and not is_v2:
        print(f"错误：OVID 版本/flags/header CRC 非法（version={version}, flags={flags:#x}）",
              file=sys.stderr)
        return 1

    per = frame_bytes(w, h)
    record = per + (4 if is_v2 else 0)
    actual = p.stat().st_size - HEADER_SIZE
    print(f"{p.name}: OVID v{2 if is_v2 else 1}  {w}x{h}  {count} 帧  {fps} fps  每帧 {per} B")
    print_firmware_requirements(w, h)
    if actual != count * record:
        print(f"  警告：数据区 {actual} B，与 {count}×{record}={count * record} B 不符 "
              f"(差 {actual - count * record})", file=sys.stderr)
        return 1
    if is_v2:
        bad = 0
        with p.open("rb") as stream:
            stream.seek(HEADER_SIZE)
            for _ in range(count):
                frame = stream.read(per)
                stored = struct.unpack("<I", stream.read(4))[0]
                if stored != (zlib.crc32(frame) & 0xFFFFFFFF):
                    bad += 1
        if bad:
            print(f"  错误：{bad} 帧 CRC32 不匹配", file=sys.stderr)
            return 1
        print("  头部 CRC16、文件长度和全部帧 CRC32 正确")
    else:
        print("  v1 头部与数据长度一致（v1 无内容 CRC）")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        info_parser = argparse.ArgumentParser(
            prog=f"{Path(sys.argv[0]).name} info",
            description="校验一个已生成的 OVID .bin",
        )
        info_parser.add_argument("file", help="要校验的 .bin 路径")
        info_args = info_parser.parse_args(sys.argv[2:])
        try:
            return cmd_info(info_args)
        except (ValueError, OSError) as e:
            print(f"错误：{e}", file=sys.stderr)
            return 1

    ap = argparse.ArgumentParser(
        description="把 C 头文件中的取模数组打包成 OVID .bin 视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法：", 1)[-1],
    )
    ap.add_argument("header", help="输入 .h 路径")
    ap.add_argument("out", help="输出 .bin 路径")
    ap.add_argument("-W", "--width", type=int, default=128, help="帧宽，默认 128")
    ap.add_argument("-H", "--height", type=int, default=64, help="帧高，默认 64")
    ap.add_argument("--fps", type=int, default=15,
                    help="播放帧率 1~120，默认 15")
    ap.add_argument("--v1", action="store_true",
                    help="生成兼容固件 v1.0.0~v1.1.0 的 OVID v1；默认生成带 CRC 的 v2")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 帧（调试用）")
    ap.add_argument("-q", "--quiet", action="store_true", help="少打日志")
    ap.add_argument("--file-order", action="store_true",
                    help="按数组在文件中出现的顺序，而不是名字里的数字顺序")
    ap.add_argument("--page-major", action="store_true",
                    help="输入数组已经是 OLED 页主序，不执行 Img2Lcd 垂直扫描转换")

    args = ap.parse_args()

    if not (1 <= args.width <= 255 and 1 <= args.height <= 255):
        print("错误：宽高须在 1~255（头部里各占 1 字节）", file=sys.stderr)
        return 1
    if not 1 <= args.fps <= 120:
        print("错误：fps 须在 1~120", file=sys.stderr)
        return 1

    try:
        return cmd_from_header(args)
    except (ValueError, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
