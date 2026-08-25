#!/usr/bin/env python3
"""Convert images, image sequences, GIFs, or videos directly to OVID v2.

Examples:

    python media2ovid.py picture.png PICTURE.BIN
    python media2ovid.py frames/ ANIMATION.BIN -W 128 -H 64 --fps 15
    python media2ovid.py clip.mp4 CLIP.BIN --fit cover --dither threshold
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import io
import math
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import islice
from pathlib import Path
from typing import Callable, Iterator

from converter_version import VERSION
from ovid_codec import (
    OvidSummary,
    OvidWriteCancelled,
    frame_bytes,
    write_ovid_atomic,
)


IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
STILL_IMAGE_SUFFIXES = IMAGE_SUFFIXES - {".gif"}
VIDEO_SUFFIXES = {
    ".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm", ".wmv"
}
BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))


class ConverterDependencyError(RuntimeError):
    """A required optional package is missing."""


class ConversionCancelled(OvidWriteCancelled):
    """The user cancelled the current conversion."""


@dataclass(frozen=True)
class ConversionOptions:
    source: Path
    output: Path
    width: int = 128
    height: int = 64
    fps: int = 15
    fit: str = "contain"
    dither: str = "threshold"
    threshold: int = 128
    invert: bool = False
    background: str = "black"
    recursive: bool = False
    force: bool = False
    skip_frames: int = 0
    trim_start_seconds: float = 0.0
    trim_end_seconds: float | None = None
    workers: int = 0
    fast_video: bool = False

    def validate(self) -> None:
        if not self.source.exists():
            raise FileNotFoundError(f"找不到输入素材：{self.source}")
        if not (1 <= self.width <= 255 and 1 <= self.height <= 255):
            raise ValueError("宽高须在 1~255")
        if not 1 <= self.fps <= 120:
            raise ValueError("fps 须在 1~120")
        if self.fit not in {"contain", "cover", "stretch"}:
            raise ValueError("缩放模式只能是 contain、cover 或 stretch")
        if self.dither not in {"floyd", "threshold"}:
            raise ValueError("黑白模式只能是 floyd 或 threshold")
        if not 0 <= self.threshold <= 255:
            raise ValueError("阈值须在 0~255")
        if self.background not in {"black", "white"}:
            raise ValueError("背景只能是 black 或 white")
        if self.skip_frames < 0:
            raise ValueError("跳过开头帧数不能小于 0")
        if not math.isfinite(self.trim_start_seconds) or self.trim_start_seconds < 0:
            raise ValueError("裁剪起点不能小于 0")
        if self.trim_end_seconds is not None:
            if not math.isfinite(self.trim_end_seconds):
                raise ValueError("裁剪终点必须是有限数值")
            if self.trim_end_seconds <= self.trim_start_seconds:
                raise ValueError("裁剪终点必须晚于裁剪起点")
        if not 0 <= self.workers <= 8:
            raise ValueError("线程数只能是自动（0）或 1~8")
        try:
            if self.source.resolve() == self.output.resolve():
                raise ValueError("输入和输出不能是同一个文件")
        except OSError:
            pass


@dataclass(frozen=True)
class SourceInfo:
    kind: str
    frame_count: int | None
    duration_seconds: float | None
    source_fps: float | None
    size: tuple[int, int] | None


@dataclass(frozen=True)
class ConversionProgress:
    completed_frames: int
    total_frames: int | None
    output_bytes: int
    elapsed_seconds: float = 0.0
    current_fps: float = 0.0
    average_fps: float = 0.0
    remaining_seconds: float | None = None

    @property
    def ratio(self) -> float | None:
        if not self.total_frames:
            return None
        return min(1.0, self.completed_frames / self.total_frames)


def _require_pillow():
    try:
        from PIL import Image, ImageOps, ImageSequence
    except ImportError as exc:
        raise ConverterDependencyError(
            "缺少 Pillow。源码运行请执行：python -m pip install -r tools/requirements-converter.txt"
        ) from exc
    return Image, ImageOps, ImageSequence


def _require_video_backend():
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise ConverterDependencyError(
            "缺少 imageio-ffmpeg。源码运行请执行："
            "python -m pip install -r tools/requirements-converter.txt"
        ) from exc
    return imageio_ffmpeg


def _close_video_reader(reader) -> None:
    """Close imageio-ffmpeg readers without leaking its Windows pipe warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        reader.close()


def ffmpeg_version() -> str:
    """Return the bundled FFmpeg version for local conversion logs."""
    imageio_ffmpeg = _require_video_backend()
    return str(imageio_ffmpeg.get_ffmpeg_version())


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", path.as_posix())]


def image_files(directory: Path, recursive: bool = False) -> list[Path]:
    candidates = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        (path for path in candidates if path.is_file() and path.suffix.casefold() in STILL_IMAGE_SUFFIXES),
        key=natural_key,
    )


def source_kind(source: Path) -> str:
    if source.is_dir():
        return "directory"
    suffix = source.suffix.casefold()
    if suffix == ".gif":
        return "gif"
    if suffix in STILL_IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    raise ValueError(f"不支持的输入类型：{source.suffix or source.name}")


def _gif_duration_ms(image) -> int:
    total = 0
    fallback = int(image.info.get("duration", 100) or 100)
    for index in range(getattr(image, "n_frames", 1)):
        image.seek(index)
        total += max(10, int(image.info.get("duration", fallback) or fallback))
    image.seek(0)
    return total


def _seconds_fraction(value: float | int) -> Fraction:
    return Fraction(str(value)).limit_denominator(1_000_000)


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _timeline_bounds(
    options: ConversionOptions,
    duration_seconds: float | None,
    frame_count: int | None,
) -> tuple[int, int | None]:
    """Return the inclusive start and exclusive end on the output timeline."""
    start = _ceil_fraction(_seconds_fraction(options.trim_start_seconds) * options.fps)
    start += options.skip_frames
    if options.trim_end_seconds is not None:
        end = _ceil_fraction(_seconds_fraction(options.trim_end_seconds) * options.fps)
    elif frame_count is not None:
        end = frame_count
    elif duration_seconds is not None:
        end = _ceil_fraction(_seconds_fraction(duration_seconds) * options.fps)
    else:
        end = None
    if end is not None and end <= start:
        raise ValueError("裁剪范围内没有可转换的画面")
    return start, end


def probe_source(options: ConversionOptions) -> SourceInfo:
    options.validate()
    Image, _, _ = _require_pillow()
    kind = source_kind(options.source)
    if kind == "directory":
        files = image_files(options.source, options.recursive)
        if not files:
            raise ValueError("图片目录中没有找到受支持的图片")
        with Image.open(files[0]) as image:
            size = image.size
        return trim_source_info(
            SourceInfo(kind, len(files), len(files) / options.fps, None, size), options
        )
    if kind == "image":
        with Image.open(options.source) as image:
            return trim_source_info(
                SourceInfo(kind, 1, 1 / options.fps, None, image.size), options
            )
    if kind == "gif":
        with Image.open(options.source) as image:
            duration_ms = _gif_duration_ms(image)
            frames = max(1, math.ceil(duration_ms * options.fps / 1000))
            return trim_source_info(
                SourceInfo(kind, frames, duration_ms / 1000, None, image.size), options
            )

    imageio_ffmpeg = _require_video_backend()
    reader = imageio_ffmpeg.read_frames(str(options.source), pix_fmt="rgb24")
    try:
        metadata = next(reader)
    finally:
        _close_video_reader(reader)
    source_fps = float(metadata.get("fps") or 0) or None
    duration = float(metadata.get("duration") or 0) or None
    size_value = metadata.get("size")
    size = tuple(size_value) if size_value else None
    estimated = max(1, math.ceil(duration * options.fps)) if duration else None
    return trim_source_info(SourceInfo(kind, estimated, duration, source_fps, size), options)


def trim_source_info(info: SourceInfo, options: ConversionOptions) -> SourceInfo:
    start, end = _timeline_bounds(
        options, info.duration_seconds, info.frame_count
    )
    if info.frame_count is not None:
        bounded_end = min(info.frame_count, end if end is not None else info.frame_count)
        remaining = bounded_end - start
        if remaining <= 0:
            raise ValueError("裁剪或跳帧后没有可转换的画面")
    else:
        remaining = None
    if remaining is not None:
        duration = remaining / options.fps
    elif end is not None:
        duration = max(0.0, (end - start) / options.fps)
    elif info.duration_seconds is not None:
        duration = max(0.0, info.duration_seconds - start / options.fps)
    else:
        duration = None
    return SourceInfo(info.kind, remaining, duration, info.source_fps, info.size)


def _fit_rgba(image, width: int, height: int, fit: str, background: str):
    Image, ImageOps, _ = _require_pillow()
    rgba = image.convert("RGBA")
    target = (width, height)
    resample = Image.Resampling.LANCZOS
    bg_value = 255 if background == "white" else 0
    canvas = Image.new("RGBA", target, (bg_value, bg_value, bg_value, 255))

    if fit == "stretch":
        fitted = rgba.resize(target, resample)
        canvas.alpha_composite(fitted)
    elif fit == "cover":
        fitted = ImageOps.fit(rgba, target, method=resample, centering=(0.5, 0.5))
        canvas.alpha_composite(fitted)
    else:
        fitted = ImageOps.contain(rgba, target, method=resample)
        left = (width - fitted.width) // 2
        top = (height - fitted.height) // 2
        canvas.alpha_composite(fitted, (left, top))
    return canvas.convert("L")


def prepare_monochrome_source(image, options: ConversionOptions):
    """Resize and composite one frame before applying a monochrome method."""
    return _fit_rgba(image, options.width, options.height, options.fit, options.background)


def monochrome_from_grayscale(gray, options: ConversionOptions):
    """Apply the selected deterministic black-and-white conversion."""
    Image, ImageOps, _ = _require_pillow()
    if options.dither == "floyd":
        mono = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        mono = gray.point(lambda value: 255 if value >= options.threshold else 0, mode="1")
    if options.invert:
        mono = ImageOps.invert(mono.convert("L")).convert("1", dither=Image.Dither.NONE)
    return mono


def image_to_monochrome(image, options: ConversionOptions):
    gray = prepare_monochrome_source(image, options)
    return monochrome_from_grayscale(gray, options)


def monochrome_to_page_major(image) -> bytes:
    """Pack a Pillow 1-bit image into the OLED page-major byte layout.

    Pillow stores mode ``1`` pixels most-significant bit first. Transposing a
    page-aligned image turns every original X column into a tightly packed row;
    page slicing and a lookup-table bit reversal then produce the exact layout
    expected by the STM32 firmware without a Python loop per pixel.
    """
    Image, _, _ = _require_pillow()
    if image.mode != "1":
        image = image.convert("1", dither=Image.Dither.NONE)
    width, height = image.size
    pages = (height + 7) // 8
    aligned_height = pages * 8
    if aligned_height != height:
        aligned = Image.new("1", (width, aligned_height), 0)
        aligned.paste(image, (0, 0))
        image = aligned
    transposed = image.transpose(Image.Transpose.TRANSPOSE)
    column_major = transposed.tobytes()
    return b"".join(
        column_major[page::pages].translate(BIT_REVERSE)
        for page in range(pages)
    )


def process_image(image, options: ConversionOptions) -> bytes:
    return monochrome_to_page_major(image_to_monochrome(image, options))


def preview_prepared_png(gray, options: ConversionOptions, scale: int = 4) -> bytes:
    Image, _, _ = _require_pillow()
    mono = monochrome_from_grayscale(gray, options)
    if scale > 1:
        mono = mono.resize(
            (mono.width * scale, mono.height * scale),
            Image.Resampling.NEAREST,
        )
    buffer = io.BytesIO()
    mono.save(buffer, format="PNG")
    return buffer.getvalue()


def preview_png(image, options: ConversionOptions, scale: int = 4) -> bytes:
    gray = prepare_monochrome_source(image, options)
    return preview_prepared_png(gray, options, scale)


def _iter_directory(options: ConversionOptions) -> Iterator[object]:
    Image, _, _ = _require_pillow()
    for path in image_files(options.source, options.recursive):
        with Image.open(path) as image:
            yield image.convert("RGBA")


def _iter_single_image(options: ConversionOptions) -> Iterator[object]:
    Image, _, _ = _require_pillow()
    with Image.open(options.source) as image:
        yield image.convert("RGBA")


def _iter_gif(options: ConversionOptions) -> Iterator[object]:
    Image, _, _ = _require_pillow()
    with Image.open(options.source) as animation:
        fallback = int(animation.info.get("duration", 100) or 100)
        elapsed_ms = 0
        output_index = 0
        for index in range(getattr(animation, "n_frames", 1)):
            animation.seek(index)
            frame = animation.convert("RGBA")
            duration_ms = max(10, int(animation.info.get("duration", fallback) or fallback))
            elapsed_ms += duration_ms
            while output_index * 1000 < elapsed_ms * options.fps:
                yield frame
                output_index += 1


def _iter_video(options: ConversionOptions) -> Iterator[object]:
    Image, _, _ = _require_pillow()
    imageio_ffmpeg = _require_video_backend()
    reader = imageio_ffmpeg.read_frames(str(options.source), pix_fmt="rgb24")
    try:
        metadata = next(reader)
        size = metadata.get("size")
        source_fps = float(metadata.get("fps") or 0)
        if not size or source_fps <= 0:
            raise ValueError("无法从视频中读取有效的尺寸或帧率")
        source_rate = Fraction(str(source_fps)).limit_denominator(100000)
        output_index = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            for source_index, raw in enumerate(reader):
                image = Image.frombytes("RGB", tuple(size), raw)
                interval_end = Fraction(source_index + 1, 1) / source_rate
                while Fraction(output_index, options.fps) < interval_end:
                    yield image
                    output_index += 1
    finally:
        _close_video_reader(reader)


def _iter_video_fast(options: ConversionOptions) -> Iterator[object]:
    """Let FFmpeg seek and select target-FPS frames before Python processing."""
    Image, _, _ = _require_pillow()
    imageio_ffmpeg = _require_video_backend()
    start_index, end_index = _timeline_bounds(options, None, None)
    start_seconds = start_index / options.fps
    input_params: list[str] = []
    if start_seconds > 0:
        input_params.extend(("-ss", f"{start_seconds:.6f}"))
    output_params = ["-vf", f"fps={options.fps}:round=near"]
    if end_index is not None:
        duration = (end_index - start_index) / options.fps
        if duration <= 0:
            raise ValueError("裁剪或跳帧后没有可转换的画面")
        output_params.extend(("-t", f"{duration:.6f}"))
    reader = imageio_ffmpeg.read_frames(
        str(options.source),
        pix_fmt="rgb24",
        input_params=input_params,
        output_params=output_params,
    )
    try:
        metadata = next(reader)
        size = metadata.get("size")
        if not size:
            raise ValueError("无法从视频中读取有效尺寸")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            for raw in reader:
                yield Image.frombytes("RGB", tuple(size), raw)
    finally:
        _close_video_reader(reader)


def iter_source_images(
    options: ConversionOptions,
    info: SourceInfo | None = None,
) -> Iterator[object]:
    kind = source_kind(options.source)
    if kind == "directory":
        frames = _iter_directory(options)
    elif kind == "image":
        frames = _iter_single_image(options)
    elif kind == "gif":
        frames = _iter_gif(options)
    elif options.fast_video:
        frames = _iter_video_fast(options)
    else:
        frames = _iter_video(options)
    try:
        if kind == "video" and options.fast_video:
            stop = info.frame_count if info is not None else None
            yield from islice(frames, 0, stop)
        else:
            start, end = _timeline_bounds(options, None, None)
            yield from islice(frames, start, end)
    finally:
        close = getattr(frames, "close", None)
        if close is not None:
            close()


def iter_preview_images(
    options: ConversionOptions,
    info: SourceInfo | None = None,
) -> Iterator[object]:
    """Stream preview frames with fast timestamp seeking for video sources.

    Preview seeking is intentionally independent from the converter's
    compatibility mode: FFmpeg may seek directly for the desktop preview,
    while final OVID output keeps the exact frame-selection path requested by
    ``options.fast_video``.
    """
    if source_kind(options.source) != "video":
        yield from iter_source_images(options, info)
        return

    preview_options = replace(options, fast_video=True)
    frames = _iter_video_fast(preview_options)
    try:
        stop = info.frame_count if info is not None else None
        yield from islice(frames, 0, stop)
    finally:
        close = getattr(frames, "close", None)
        if close is not None:
            close()


def load_preview_frame(options: ConversionOptions):
    info = probe_source(options)
    iterator = iter_source_images(options, info)
    try:
        return next(iterator)
    except StopIteration as exc:
        raise ValueError("输入素材中没有可预览的帧") from exc
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()


def estimate_output_bytes(options: ConversionOptions, info: SourceInfo) -> int | None:
    if info.frame_count is None:
        return None
    return 16 + info.frame_count * (frame_bytes(options.width, options.height) + 4)


def resolved_worker_count(options: ConversionOptions) -> int:
    if options.workers:
        return options.workers
    return min(4, max(1, (os.cpu_count() or 2) - 1))


def _processed_frames(
    options: ConversionOptions,
    info: SourceInfo,
    cancelled: Callable[[], bool] | None,
) -> Iterator[bytes]:
    images = iter_source_images(options, info)
    workers = resolved_worker_count(options)
    if workers == 1:
        try:
            for image in images:
                if cancelled is not None and cancelled():
                    raise ConversionCancelled("转换已取消")
                yield process_image(image, options)
        finally:
            close = getattr(images, "close", None)
            if close is not None:
                close()
        return

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ovid-frame")
    pending: deque[Future[bytes]] = deque()
    exhausted = False
    try:
        while pending or not exhausted:
            while not exhausted and len(pending) < workers * 2:
                if cancelled is not None and cancelled():
                    raise ConversionCancelled("转换已取消")
                try:
                    image = next(images)
                except StopIteration:
                    exhausted = True
                    break
                pending.append(executor.submit(process_image, image, options))
            if pending:
                if cancelled is not None and cancelled():
                    raise ConversionCancelled("转换已取消")
                yield pending.popleft().result()
    finally:
        close = getattr(images, "close", None)
        if close is not None:
            close()
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def convert_media(
    options: ConversionOptions,
    *,
    progress: Callable[[ConversionProgress], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    source_info: SourceInfo | None = None,
) -> OvidSummary:
    options.validate()
    info = source_info if source_info is not None else probe_source(options)
    per_record = frame_bytes(options.width, options.height) + 4
    started = time.perf_counter()
    last_report_time = started
    last_report_count = 0
    current_fps = 0.0

    def frames() -> Iterator[bytes]:
        yield from _processed_frames(options, info, cancelled)

    def report(count: int) -> None:
        nonlocal last_report_count, last_report_time, current_fps
        if progress is not None:
            now = time.perf_counter()
            elapsed = max(0.0, now - started)
            interval = now - last_report_time
            if interval > 0:
                sample = (count - last_report_count) / interval
                current_fps = sample if current_fps == 0 else current_fps * 0.75 + sample * 0.25
            average_fps = count / elapsed if elapsed > 0 else 0.0
            remaining = None
            if info.frame_count is not None and average_fps > 0:
                remaining = max(0.0, (info.frame_count - count) / average_fps)
            progress(
                ConversionProgress(
                    count,
                    info.frame_count,
                    16 + count * per_record,
                    elapsed,
                    current_fps,
                    average_fps,
                    remaining,
                )
            )
            last_report_time = now
            last_report_count = count

    try:
        return write_ovid_atomic(
            options.output,
            frames(),
            options.width,
            options.height,
            options.fps,
            force=options.force,
            on_frame=report,
            cancelled=cancelled,
        )
    except OvidWriteCancelled as exc:
        raise ConversionCancelled(str(exc)) from exc


def _format_size(value: int | None) -> str:
    if value is None:
        return "未知"
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / 1024 / 1024:.2f} MiB"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="图片、图片目录、GIF 或视频")
    parser.add_argument("output", type=Path, help="输出 OVID .BIN")
    parser.add_argument("-W", "--width", type=int, default=128, help="输出宽度，默认 128")
    parser.add_argument("-H", "--height", type=int, default=64, help="输出高度，默认 64")
    parser.add_argument("--fps", type=int, default=15, help="输出帧率 1~120，默认 15")
    parser.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain")
    parser.add_argument("--dither", choices=("floyd", "threshold"), default="threshold")
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--background", choices=("black", "white"), default="black")
    parser.add_argument("--recursive", action="store_true", help="递归读取图片子目录")
    parser.add_argument(
        "--skip-frames",
        type=int,
        default=0,
        help="跳过输出时间轴开头的帧数，默认 0",
    )
    parser.add_argument("--start", type=float, default=0.0, help="裁剪起点（秒）")
    parser.add_argument("--end", type=float, default=None, help="裁剪终点（秒，不包含）")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="图像处理线程数，0=自动，范围 1~8",
    )
    parser.add_argument(
        "--fast-video",
        action="store_true",
        help="由 FFmpeg 提前裁剪和抽帧；临界时间点可能选择相邻帧",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已有输出文件")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = ConversionOptions(
        source=args.source,
        output=args.output,
        width=args.width,
        height=args.height,
        fps=args.fps,
        fit=args.fit,
        dither=args.dither,
        threshold=args.threshold,
        invert=args.invert,
        background=args.background,
        recursive=args.recursive,
        force=args.force,
        skip_frames=args.skip_frames,
        trim_start_seconds=args.start,
        trim_end_seconds=args.end,
        workers=args.workers,
        fast_video=args.fast_video,
    )

    last_percent = -1

    def show_progress(value: ConversionProgress) -> None:
        nonlocal last_percent
        if value.ratio is None:
            if value.completed_frames == 1 or value.completed_frames % 25 == 0:
                print(f"已转换 {value.completed_frames} 帧，输出 {_format_size(value.output_bytes)}")
            return
        percent = int(value.ratio * 100)
        if percent != last_percent and (percent == 100 or percent >= last_percent + 5):
            last_percent = percent
            print(f"{percent:3d}%  {value.completed_frames}/{value.total_frames} 帧")

    try:
        info = probe_source(options)
        print(
            f"输入：{options.source}（{info.kind}）\n"
            f"输出：{options.output}\n"
            f"参数：{options.width}x{options.height}  {options.fps} fps  "
            f"{options.fit}  {options.dither}\n"
            f"预计大小：{_format_size(estimate_output_bytes(options, info))}"
        )
        summary = convert_media(options, progress=show_progress, source_info=info)
        print(
            f"已生成 {summary.path}\n"
            f"  OVID v2  {summary.width}x{summary.height}  {summary.frame_count} 帧  "
            f"{summary.fps} fps  {_format_size(summary.file_bytes)}"
        )
        return 0
    except (ConverterDependencyError, ConversionCancelled, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
