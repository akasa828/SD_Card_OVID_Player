#!/usr/bin/env python3
"""h2bin.py —— 把取模数据打包成 function.c 能播的 OVID .bin 视频文件。

两种输入源：

  1) C 头文件里的取模数组（如 Core/隐藏关卡/bad apple.h）：
       python h2bin.py from-header "Core/隐藏关卡/bad apple.h" badapple.bin -W 128 -H 64 --fps 15

  2) 一批图片（需要 Pillow），按文件名自然序当作帧序列：
       python h2bin.py from-images frames/ out.bin -W 128 -H 64 --fps 12

输出格式见 Core/function/function.h 的 FN_VideoHeader（16 字节小端头 + 帧数据）：

    offset size  字段
    0      4     magic "OVID"
    4      1     width   帧宽（像素）
    5      1     height  帧高（像素）
    6      2     rsv0    保留，写 0
    8      4     frame_count 总帧数
    12     2     fps     播放帧率（1~120）
    14     2     rsv1    保留，写 0

帧数据紧随其后，每帧 ceil(height/8)*width 字节，SSD1306 页主序
（先第 0 页的第 0..width-1 列，再第 1 页……），与 OLED_Draw_Bitmap 的入参布局一致。

固件是否能播放由 OLED_WIDTH/OLED_HEIGHT 及 MCU RAM 决定，工具不再设 1024 B 上限。
"""

import argparse
import re
import struct
import sys
from pathlib import Path

MAGIC = b"OVID"
HEADER_SIZE = 16


def frame_bytes(width: int, height: int) -> int:
    """一帧的字节数：页主序下 = ceil(height/8) * width。"""
    return ((height + 7) // 8) * width


def print_firmware_requirements(width: int, height: int) -> None:
    """输出可容纳该视频的最小屏幕宏。屏高需向上取整到 8 的倍数。"""
    screen_height = ((height + 7) // 8) * 8
    gram = frame_bytes(width, screen_height)
    print(f"  固件至少需要: OLED_WIDTH={width}, OLED_HEIGHT={screen_height}, "
          f"OLED_GRAM_SIZE={gram} B")
    if screen_height > 255:
        print("  警告：页对齐后高度超过 255，当前固件宏范围无法容纳该视频。",
              file=sys.stderr)


def write_ovid(out_path: Path, frames, width: int, height: int, fps: int) -> None:
    """把 frames（bytes 的可迭代对象）写成 OVID 文件。

    先占位写头部，流式写完帧后回填 frame_count —— 这样无需把整个视频读进内存，
    10000+ 帧的素材也只占一帧的内存。
    """
    if not (1 <= width <= 255 and 1 <= height <= 255):
        raise ValueError("宽高须在 1~255（OVID v1 字段各占 1 字节）")
    if not 1 <= fps <= 120:
        raise ValueError("fps 须在 1~120")
    expect = frame_bytes(width, height)
    count = 0
    with out_path.open("wb") as f:
        f.write(struct.pack("<4sBB2sIH2s", MAGIC, width, height, b"\0\0", 0, fps, b"\0\0"))
        for data in frames:
            if len(data) != expect:
                raise ValueError(
                    f"第 {count + 1} 帧长度 {len(data)} 字节，与 {width}x{height} "
                    f"应有的 {expect} 字节不符"
                )
            f.write(data)
            count += 1
        if count == 0:
            raise ValueError("没有取到任何帧")
        # 回填真实帧数
        f.seek(8)
        f.write(struct.pack("<I", count))

    size = HEADER_SIZE + count * expect
    print(f"已写出 {out_path}")
    print(f"  {width}x{height}  {count} 帧  {fps} fps  每帧 {expect} B  合计 {size / 1024 / 1024:.2f} MB")
    print_firmware_requirements(width, height)
    print(f"  时长约 {count / fps:.1f} 秒")


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
    pattern = re.compile(args.match) if args.match else None

    # 先扫一遍收集名字与偏移，以便按自然序输出（C 数组在文件里通常已是顺序，
    # 但 BMP1/BMP10/BMP2 这种字典序陷阱必须避开）。只存名字，不存数据。
    print(f"扫描 {src} ...")
    names = []
    for name, data in iter_header_arrays(src):
        if pattern and not pattern.search(name):
            continue
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

    # 第二遍：按 order 的顺序落盘。数组顺序与文件顺序几乎总是一致，
    # 所以缓存的帧数很少；极端情况下才会短暂多存几帧。
    def frames():
        pending = {}
        nxt = 0
        for name, data in iter_header_arrays(src):
            idx = wanted.get(name)
            if idx is None or len(data) != expect:
                continue
            pending[idx] = data
            while nxt in pending:
                yield pending.pop(nxt)
                nxt += 1
        if pending:
            raise ValueError(f"有 {len(pending)} 帧顺序错乱未能输出")

    write_ovid(Path(args.out), frames(), args.width, args.height, args.fps)
    return 0


# ------------------------------------------------------------------ 图片输入

IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def image_to_pagemajor(img, width: int, height: int, threshold: int, invert: bool) -> bytes:
    """把一张 PIL 图片转成 SSD1306 页主序单色位图。

    页主序：bit0 是该页最上面一行。与 OLED_Draw_Bitmap 的读取方式一致。
    """
    img = img.convert("L").resize((width, height))
    px = img.load()
    pages = (height + 7) // 8
    out = bytearray(pages * width)
    for pg in range(pages):
        base = pg * width
        for x in range(width):
            byte = 0
            for bit in range(8):
                y = pg * 8 + bit
                if y >= height:
                    break
                on = px[x, y] >= threshold
                if invert:
                    on = not on
                if on:
                    byte |= 1 << bit
            out[base + x] = byte
    return bytes(out)


def cmd_from_images(args) -> int:
    try:
        from PIL import Image
    except ImportError:
        print("错误：需要 Pillow。请先 pip install Pillow", file=sys.stderr)
        return 1

    src = Path(args.src)
    if src.is_dir():
        files = [p for p in src.iterdir() if p.suffix.lower() in IMG_EXT]
    else:
        files = [src]
    if not files:
        print(f"错误：{src} 下没有找到图片", file=sys.stderr)
        return 1

    files.sort(key=lambda p: natural_key(p.name))
    if args.limit:
        files = files[: args.limit]
    print(f"取到 {len(files)} 张图片")

    def frames():
        for i, p in enumerate(files, 1):
            with Image.open(p) as img:
                # GIF/多帧图：把每一帧都展开
                n = getattr(img, "n_frames", 1)
                if n > 1:
                    for fi in range(n):
                        img.seek(fi)
                        yield image_to_pagemajor(img, args.width, args.height,
                                                 args.threshold, args.invert)
                else:
                    yield image_to_pagemajor(img, args.width, args.height,
                                             args.threshold, args.invert)
            if not args.quiet and i % 100 == 0:
                print(f"  已处理 {i}/{len(files)}")

    write_ovid(Path(args.out), frames(), args.width, args.height, args.fps)
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
    magic, w, h, _, count, fps, _ = struct.unpack("<4sBB2sIH2s", raw)
    if magic != MAGIC:
        print(f"错误：magic 是 {magic!r}，不是 {MAGIC!r}", file=sys.stderr)
        return 1

    if w == 0 or h == 0 or count == 0 or not 1 <= fps <= 120:
        print(f"错误：头部字段非法（{w}x{h}, {count} 帧, {fps} fps）", file=sys.stderr)
        return 1

    per = frame_bytes(w, h)
    actual = p.stat().st_size - HEADER_SIZE
    print(f"{p.name}: {w}x{h}  {count} 帧  {fps} fps  每帧 {per} B")
    print_firmware_requirements(w, h)
    if actual != count * per:
        print(f"  警告：数据区 {actual} B，与 {count}×{per}={count * per} B 不符 "
              f"(差 {actual - count * per})", file=sys.stderr)
        return 1
    print("  头部与数据长度一致")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把取模数据打包成 function.c 能播的 OVID .bin 视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("两种输入源：", 1)[-1],
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("out", help="输出 .bin 路径")
        p.add_argument("-W", "--width", type=int, default=128, help="帧宽，默认 128")
        p.add_argument("-H", "--height", type=int, default=64, help="帧高，默认 64")
        p.add_argument("--fps", type=int, default=15,
                       help="播放帧率 1~120，默认 15")
        p.add_argument("--limit", type=int, default=0, help="只取前 N 帧（调试用）")
        p.add_argument("-q", "--quiet", action="store_true", help="少打日志")

    ph = sub.add_parser("from-header", help="从 C 头文件的取模数组生成")
    ph.add_argument("header", help="输入 .h 路径")
    add_common(ph)
    ph.add_argument("--match", default=None,
                    help="只取数组名匹配此正则的（如 '^BMP'）")
    ph.add_argument("--file-order", action="store_true",
                    help="按数组在文件中出现的顺序，而不是名字里的数字顺序")
    ph.set_defaults(func=cmd_from_header)

    pi = sub.add_parser("from-images", help="从图片序列生成（需要 Pillow）")
    pi.add_argument("src", help="图片目录或单个文件（GIF 会展开所有帧）")
    add_common(pi)
    pi.add_argument("--threshold", type=int, default=128,
                    help="二值化阈值 0~255，默认 128")
    pi.add_argument("--invert", action="store_true", help="反色")
    pi.set_defaults(func=cmd_from_images)

    pv = sub.add_parser("info", help="校验一个已生成的 .bin")
    pv.add_argument("file")
    pv.set_defaults(func=cmd_info)

    args = ap.parse_args()

    if args.cmd != "info":
        if not (1 <= args.width <= 255 and 1 <= args.height <= 255):
            print("错误：宽高须在 1~255（头部里各占 1 字节）", file=sys.stderr)
            return 1
        if not 1 <= args.fps <= 120:
            print("错误：fps 须在 1~120", file=sys.stderr)
            return 1

    try:
        return args.func(args)
    except (ValueError, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
