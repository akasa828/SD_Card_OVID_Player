#!/usr/bin/env python3
"""Material 3 desktop interface for the OVID media converter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path

import flet as ft

try:
    from flet_drop_zone import FletDropZone
except ImportError:  # Local lightweight builds deliberately omit the Flutter extension.
    FletDropZone = None

from converter_version import DISPLAY_NAME, VERSION
from converter_dialogs import DialogHost
from converter_feedback import ErrorDetailsDialog, ErrorReport
from converter_preview_ui import PixelInspector, PreviewSnapshot
from converter_services import (
    BUILTIN_PRESETS,
    TARGET_PROFILES,
    CompatibilityReport,
    ConversionLogger,
    ConversionPreset,
    ConversionQueue,
    PresetStore,
    QueueJob,
    QueueSessionStore,
    check_compatibility,
    screen_size_status,
    suggested_threshold,
)
from media2ovid import (
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    ConversionCancelled,
    ConversionOptions,
    ConversionProgress,
    convert_media,
    estimate_output_bytes,
    ffmpeg_version,
    iter_preview_images,
    prepare_monochrome_source,
    preview_prepared_png,
    probe_source,
    trim_source_info,
)
from ovid_player import OvidPlaybackSession


REPOSITORY_URL = "https://github.com/akasa828/SD_Card_OVID_Player"
MAX_PREVIEW_CACHE = 180
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PRIMARY_FONT = "Google Sans Flex"
SIMPLIFIED_CHINESE_FONT = "Noto Sans SC"
NAVIGATION_ITEMS = (
    (ft.Icons.MOVIE, "转换"),
    (ft.Icons.PLAY_CIRCLE, "播放器"),
    (ft.Icons.SETTINGS, "设置"),
    (ft.Icons.INFO, "关于"),
)
VALID_THEME_MODES = frozenset({"system", "light", "dark"})
PROGRESS_FRAME_INTERVAL = 0.016
PROGRESS_EASING_SECONDS = 0.12
PROGRESS_FINISH_SECONDS = 0.25
TIMELINE_LABEL_INTERVAL = 1.0 / 30.0
MATERIAL_LIGHT_COLORS = {
    "primary": "#6750A4",
    "on_primary": "#FFFFFF",
    "primary_container": "#EADDFF",
    "on_primary_container": "#21005D",
    "secondary": "#625B71",
    "on_secondary": "#FFFFFF",
    "secondary_container": "#E8DEF8",
    "on_secondary_container": "#1D192B",
    "tertiary": "#7D5260",
    "on_tertiary": "#FFFFFF",
    "tertiary_container": "#FFD8E4",
    "on_tertiary_container": "#31111D",
    "error": "#B3261E",
    "on_error": "#FFFFFF",
    "error_container": "#F9DEDC",
    "on_error_container": "#410E0B",
    "surface": "#FFFBFE",
    "on_surface": "#1C1B1F",
    "on_surface_variant": "#49454F",
    "outline": "#79747E",
    "outline_variant": "#CAC4D0",
    "shadow": "#000000",
    "inverse_surface": "#313033",
    "on_inverse_surface": "#F4EFF4",
    "inverse_primary": "#D0BCFF",
    "surface_dim": "#DED8E1",
    "surface_bright": "#FFFBFE",
    "surface_container_lowest": "#FFFFFF",
    "surface_container_low": "#F7F2FA",
    "surface_container": "#F3EDF7",
    "surface_container_high": "#ECE6F0",
    "surface_container_highest": "#E6E0E9",
}
MATERIAL_DARK_COLORS = {
    "primary": "#D0BCFF",
    "on_primary": "#381E72",
    "primary_container": "#4F378B",
    "on_primary_container": "#EADDFF",
    "secondary": "#CCC2DC",
    "on_secondary": "#332D41",
    "secondary_container": "#4A4458",
    "on_secondary_container": "#E8DEF8",
    "tertiary": "#EFB8C8",
    "on_tertiary": "#492532",
    "tertiary_container": "#633B48",
    "on_tertiary_container": "#FFD8E4",
    "error": "#F2B8B5",
    "on_error": "#601410",
    "error_container": "#8C1D18",
    "on_error_container": "#F9DEDC",
    "surface": "#141218",
    "on_surface": "#E6E0E9",
    "on_surface_variant": "#CAC4D0",
    "outline": "#938F99",
    "outline_variant": "#49454F",
    "shadow": "#000000",
    "inverse_surface": "#E6E0E9",
    "on_inverse_surface": "#322F35",
    "inverse_primary": "#6750A4",
    "surface_dim": "#141218",
    "surface_bright": "#3B383E",
    "surface_container_lowest": "#0F0D13",
    "surface_container_low": "#1D1B20",
    "surface_container": "#211F26",
    "surface_container_high": "#2B2930",
    "surface_container_highest": "#36343B",
}


class PreviewFinished(RuntimeError):
    """The preview iterator reached the end of the selected media."""


def format_timestamp(seconds: float | int | None) -> str:
    if seconds is None or not math.isfinite(float(seconds)):
        return "--:--.--"
    value = max(0.0, float(seconds))
    centiseconds = math.floor(value * 100 + 0.5)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"
    return f"{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def timeline_frame_at_or_after(seconds: float, fps: int) -> int:
    return math.ceil(Fraction(str(seconds)).limit_denominator(1_000_000) * fps)


def preview_frame_seconds(options: ConversionOptions, index: int) -> float:
    first = timeline_frame_at_or_after(options.trim_start_seconds, options.fps)
    return (first + options.skip_frames + max(0, index - 1)) / options.fps


def parse_timestamp(text: str) -> float:
    value = text.strip()
    if not re.fullmatch(r"(?:[0-9]+:){0,2}[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("请输入秒数、分:秒或时:分:秒，例如 2.5 或 00:02.50")
    parts = value.split(":")
    numbers = [float(part) for part in parts]
    if len(parts) > 1 and any(number >= 60 for number in numbers[1:]):
        raise ValueError("冒号后的分钟和秒须小于 60")
    seconds = sum(number * 60 ** index for index, number in enumerate(reversed(numbers)))
    if not math.isfinite(seconds):
        raise ValueError("时间数值过大")
    return seconds


def parse_preview_fps(value: object) -> int:
    """Parse the preview frame rate without leaking UI conversion errors."""
    try:
        fps = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("FPS 必须是 1–120 之间的整数") from exc
    if not 1 <= fps <= 120:
        raise ValueError("FPS 必须是 1–120 之间的整数")
    return fps


def advance_preview_deadline(deadline: float, now: float, interval: float) -> tuple[float, float]:
    """Return the remaining delay and next deadline without burst catch-up."""
    deadline += interval
    if deadline <= now:
        return 0.0, now
    return deadline - now, deadline


def smooth_progress_value(current: float, target: float, elapsed: float) -> float:
    """Ease monotonically toward the latest worker progress without overshoot."""
    current = min(1.0, max(0.0, current))
    target = min(1.0, max(current, target))
    if current == target:
        return target
    alpha = 1.0 - math.exp(-max(0.0, elapsed) / PROGRESS_EASING_SECONDS)
    value = current + (target - current) * alpha
    return target if target - value < 0.0005 else min(target, value)


def responsive_preview_heights(window_height: float | int | None) -> tuple[int, int]:
    """Keep both editors useful on small screens without wasting tall windows."""
    try:
        height = float(window_height or 760)
    except (TypeError, ValueError):
        height = 760
    height = max(480.0, height)
    comparison = round(min(300.0, max(160.0, height * 0.30)))
    player = round(min(520.0, max(260.0, height * 0.52)))
    return comparison, player


def normalize_theme_mode(value: object) -> str:
    theme = str(value).lower()
    return theme if theme in VALID_THEME_MODES else "system"


def material_light_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme=ft.ColorScheme(**MATERIAL_LIGHT_COLORS),
        use_material3=True,
        font_family=PRIMARY_FONT,
        text_theme=_app_text_theme(MATERIAL_LIGHT_COLORS["on_surface"]),
        scaffold_bgcolor=MATERIAL_LIGHT_COLORS["surface"],
        canvas_color=MATERIAL_LIGHT_COLORS["surface"],
        card_bgcolor=MATERIAL_LIGHT_COLORS["surface_container"],
        divider_color=MATERIAL_LIGHT_COLORS["outline_variant"],
        hint_color=MATERIAL_LIGHT_COLORS["on_surface_variant"],
    )


def material_dark_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme=ft.ColorScheme(**MATERIAL_DARK_COLORS),
        use_material3=True,
        font_family=PRIMARY_FONT,
        text_theme=_app_text_theme(MATERIAL_DARK_COLORS["on_surface"]),
        scaffold_bgcolor=MATERIAL_DARK_COLORS["surface"],
        canvas_color=MATERIAL_DARK_COLORS["surface"],
        card_bgcolor=MATERIAL_DARK_COLORS["surface_container"],
        divider_color=MATERIAL_DARK_COLORS["outline_variant"],
        hint_color=MATERIAL_DARK_COLORS["on_surface_variant"],
    )


def _app_text_style(
    weight: ft.FontWeight = ft.FontWeight.W_400,
    color: str | None = None,
) -> ft.TextStyle:
    """Keep Latin and Simplified Chinese text on the same visual weight."""
    return ft.TextStyle(
        weight=weight,
        color=color,
        font_family=PRIMARY_FONT,
        font_family_fallback=[SIMPLIFIED_CHINESE_FONT],
    )


def _app_text_theme(color: str | None = None) -> ft.TextTheme:
    regular = ft.FontWeight.W_400
    medium = ft.FontWeight.W_500
    return ft.TextTheme(
        body_large=_app_text_style(regular, color),
        body_medium=_app_text_style(regular, color),
        body_small=_app_text_style(regular, color),
        display_large=_app_text_style(medium, color),
        display_medium=_app_text_style(medium, color),
        display_small=_app_text_style(medium, color),
        headline_large=_app_text_style(medium, color),
        headline_medium=_app_text_style(medium, color),
        headline_small=_app_text_style(medium, color),
        label_large=_app_text_style(medium, color),
        label_medium=_app_text_style(medium, color),
        label_small=_app_text_style(medium, color),
        title_large=_app_text_style(medium, color),
        title_medium=_app_text_style(medium, color),
        title_small=_app_text_style(medium, color),
    )


def human_size(value: int | None) -> str:
    if value is None:
        return "未知"
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    if value < 1024 * 1024 * 1024:
        return f"{value / 1024 / 1024:.2f} MiB"
    return f"{value / 1024 / 1024 / 1024:.2f} GiB"


def batch_result_text(completed: int, total: int) -> str:
    failed = max(0, total - completed)
    if failed:
        return f"本轮结束：{completed} 成功 · {failed} 失败"
    return f"本轮完成：{completed}/{total} 个任务"


@dataclass(frozen=True)
class BatchDisplayProgress:
    file_name: str
    processed_tasks: int
    total_tasks: int
    current: ConversionProgress | None = None

    @property
    def ratio(self) -> float | None:
        if self.total_tasks <= 0:
            return 0.0
        current_ratio = self.current.ratio if self.current is not None else 0.0
        if current_ratio is None:
            return None
        return min(1.0, (self.processed_tasks + current_ratio) / self.total_tasks)

    def text(self) -> str:
        count = f"已处理 {self.processed_tasks}/{self.total_tasks} 项"
        if self.current is None:
            if self.processed_tasks >= self.total_tasks:
                return f"{count} · 正在汇总结果"
            return f"{self.file_name} · {count} · 正在准备"
        value = self.current
        frames = (
            f"本文件 {value.completed_frames}/{value.total_frames} 帧"
            if value.total_frames
            else f"本文件 {value.completed_frames} 帧（总数未知）"
        )
        overall = f" · 任务总进度 {self.ratio * 100:.1f}%" if self.ratio is not None else ""
        eta = (
            f" · 本文件剩余 {value.remaining_seconds:.1f} 秒"
            if value.remaining_seconds is not None
            else ""
        )
        return (
            f"{self.file_name} · {count}{overall} · {frames} · "
            f"当前输出 {human_size(value.output_bytes)} · "
            f"{value.current_fps:.1f}/{value.average_fps:.1f} FPS{eta}"
        )


def parse_drop_paths(value: object) -> list[Path]:
    """Decode desktop_drop event data without exposing JSON errors to the UI."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            if value.lstrip().startswith(("[", "{")):
                return []
            value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    paths: list[Path] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            paths.append(Path(item.strip()))
    return paths


def is_supported_source(path: Path) -> bool:
    return path.is_dir() or path.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES


def source_preview_image(image, max_size: tuple[int, int] = (320, 180)) -> bytes:
    """Encode a compact source preview without changing the conversion frame."""
    from PIL import Image
    import io

    preview = image.convert("RGBA")
    preview.thumbnail(max_size, Image.Resampling.LANCZOS)
    background = Image.new("RGBA", preview.size, (24, 24, 24, 255))
    background.alpha_composite(preview)
    buffer = io.BytesIO()
    background.convert("RGB").save(
        buffer,
        "JPEG",
        quality=80,
        subsampling=2,
    )
    return buffer.getvalue()


def preview_render_key(options: ConversionOptions) -> tuple[str, int, bool]:
    """Return the options that affect a prepared monochrome preview."""
    return options.dither, options.threshold, options.invert


@dataclass
class AppSettings:
    width: int = 128
    height: int = 64
    fps: int = 15
    output_directory: str = ""
    theme: str = "system"
    workers: int = 0
    fast_video: bool = False
    target_profile: str = "stm32f103-128x64"


@dataclass
class TaskRowView:
    card: ft.Card
    container: ft.Container
    checkbox: ft.Checkbox
    name: ft.Text
    details: ft.Text
    state: ft.Text
    progress: ft.ProgressBar
    actions: ft.Row
    signature: tuple[object, ...] = ()


def settings_file() -> Path:
    root = os.getenv("FLET_APP_STORAGE_DATA")
    if not root:
        root = str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "OVID Converter")
    return Path(root) / "settings.json"


def load_settings() -> AppSettings:
    path = settings_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            return AppSettings()
        return AppSettings(
            width=min(255, max(1, int(values.get("width", 128)))),
            height=min(255, max(1, int(values.get("height", 64)))),
            fps=min(120, max(1, int(values.get("fps", 15)))),
            output_directory=str(values.get("output_directory", "")),
            theme=normalize_theme_mode(values.get("theme", "system")),
            workers=min(8, max(0, int(values.get("workers", 0)))),
            fast_video=bool(values.get("fast_video", False)),
            target_profile=(
                str(values.get("target_profile"))
                if str(values.get("target_profile")) in TARGET_PROFILES
                else "stm32f103-128x64"
            ),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class PreviewSession:
    def __init__(self) -> None:
        self.options: ConversionOptions | None = None
        self.info = None
        self.iterator = None
        self.frames: list[tuple[bytes, object, tuple[str, int, bool], bytes]] = []
        self.index = -1
        self.base_index = 0
        self.executor: ThreadPoolExecutor | None = None
        self.pending: deque[
            Future[tuple[bytes, object, tuple[str, int, bool], bytes]]
        ] = deque()
        self.source_exhausted = False
        self.prefetch_limit = min(8, max(2, os.cpu_count() or 2))
        self.last_source_image = None
        self.last_source_future: Future[
            tuple[bytes, object, tuple[str, int, bool], bytes]
        ] | None = None

    def close(self) -> None:
        if self.iterator is not None:
            close = getattr(self.iterator, "close", None)
            if close is not None:
                close()
        self.iterator = None
        while self.pending:
            self.pending.popleft().cancel()
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.executor = None
        self.source_exhausted = False
        self.last_source_image = None
        self.last_source_future = None

    def reset(self, options: ConversionOptions, info=None) -> None:
        self.close()
        self.options = options
        self.info = info
        self.iterator = iter_preview_images(options, info)
        self.frames.clear()
        self.index = -1
        self.base_index = 0

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self.executor is None:
            workers = min(4, max(1, (os.cpu_count() or 2) - 1))
            self.executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="ovid-preview",
            )
        return self.executor

    def _prepare_entry(
        self,
        image,
        options: ConversionOptions,
    ) -> tuple[bytes, object, tuple[str, int, bool], bytes]:
        prepared = prepare_monochrome_source(image, options)
        return (
            source_preview_image(image),
            prepared,
            preview_render_key(options),
            preview_prepared_png(prepared, options, scale=4),
        )

    def _fill_prefetch(self) -> None:
        if self.iterator is None or self.source_exhausted:
            return
        executor = self._ensure_executor()
        while len(self.pending) < self.prefetch_limit:
            try:
                image = next(self.iterator)
            except StopIteration:
                self.source_exhausted = True
                break
            if image is self.last_source_image and self.last_source_future is not None:
                future = self.last_source_future
            else:
                options = self.options
                if options is None:
                    raise ValueError("请先选择输入素材")
                future = executor.submit(self._prepare_entry, image, options)
                self.last_source_image = image
                self.last_source_future = future
            self.pending.append(future)

    def _next_prepared_entry(self) -> tuple[bytes, object, tuple[str, int, bool], bytes]:
        self._fill_prefetch()
        if not self.pending:
            raise PreviewFinished("已到最后一帧")
        entry = self.pending.popleft().result()
        self._fill_prefetch()
        return entry

    def _render(
        self,
        entry: tuple[bytes, object, tuple[str, int, bool], bytes],
    ) -> tuple[
        bytes,
        bytes,
        tuple[bytes, object, tuple[str, int, bool], bytes],
    ]:
        original, prepared, render_key, rendered = entry
        if self.options is None:
            raise ValueError("请先选择输入素材")
        current_key = preview_render_key(self.options)
        if render_key != current_key:
            rendered = preview_prepared_png(prepared, self.options, scale=4)
            entry = (original, prepared, current_key, rendered)
        return original, rendered, entry

    def next_frame(self) -> tuple[bytes, bytes, int]:
        if self.options is None or self.iterator is None:
            raise ValueError("请先选择输入素材")
        if self.index + 1 < len(self.frames):
            self.index += 1
            original, data, entry = self._render(self.frames[self.index])
            self.frames[self.index] = entry
            return original, data, self.base_index + self.index + 1

        entry = self._next_prepared_entry()
        original, data, entry = self._render(entry)
        self.frames.append(entry)
        self.index += 1
        if len(self.frames) > MAX_PREVIEW_CACHE:
            self.frames.pop(0)
            self.index -= 1
            self.base_index += 1
        return original, data, self.base_index + self.index + 1

    def previous_frame(self) -> tuple[bytes, bytes, int]:
        if not self.frames:
            raise ValueError("当前没有预览帧")
        if self.index > 0:
            self.index -= 1
        original, data, entry = self._render(self.frames[self.index])
        self.frames[self.index] = entry
        return original, data, self.base_index + self.index + 1

    def rerender_current(self, dither: str, threshold: int, invert: bool) -> tuple[bytes, bytes, int]:
        if self.options is None or not self.frames or self.index < 0:
            raise ValueError("当前没有预览帧")
        self.options = replace(
            self.options,
            dither=dither,
            threshold=threshold,
            invert=invert,
        )
        original, prepared, _, _ = self.frames[self.index]
        current_key = preview_render_key(self.options)
        data = preview_prepared_png(prepared, self.options, scale=4)
        self.frames[self.index] = (original, prepared, current_key, data)
        return original, data, self.base_index + self.index + 1

    def current_grayscale(self):
        if not self.frames or self.index < 0:
            raise ValueError("当前没有预览帧")
        return self.frames[self.index][1]


class ConverterApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.dialog_host = DialogHost(page)
        self.settings = load_settings()
        self.preset_store = PresetStore()
        self.session_store = QueueSessionStore()
        restored_jobs, restored_active_task = self.session_store.load()
        self.queue = ConversionQueue(restored_jobs)
        self.task_rows: dict[str, TaskRowView] = {}
        self.active_task_id: str | None = None
        self.session_save_task: asyncio.Task | None = None
        self.current_batch_ids: tuple[str, ...] = ()
        self.stop_batch_requested = False
        self.loading_task_controls = False
        self.pending_trim_range: tuple[float, float | None] | None = None
        self.batch_current_name = ""
        self.logger = ConversionLogger()
        self.player = OvidPlaybackSession()
        self.source_info = None
        self.source_info_key: tuple[str, int, bool] | None = None
        self.queue_cancel_event = threading.Event()
        self.active_queue_job_id: str | None = None
        self.preview = PreviewSession()
        self.preview_lock = asyncio.Lock()
        self.preview_close_task: asyncio.Task | None = None
        self.preview_revision = 0
        self.preview_playback_revision = 0
        self.preview_render_revision = 0
        self.preview_playing = False
        self.preview_timeline_dragging = False
        self.trim_dragging = False
        self.resume_preview_after_drag = False
        self.trim_label_task: asyncio.Task | None = None
        self.preview_time_task: asyncio.Task | None = None
        self.preview_needs_reload = False
        self.conversion_revision = 0
        self.latest_conversion_progress: tuple[int, BatchDisplayProgress] | None = None
        self.progress_display_ratio = 0.0
        self.progress_finish_deadline: float | None = None
        self.progress_finish_event: asyncio.Event | None = None
        self.progress_render_task: asyncio.Task | None = None
        self.busy = False
        self.player_timeline_dragging = False
        self.resume_player_after_drag = False
        self.player_time_task: asyncio.Task | None = None
        self.exit_dialog_open = False
        self.exit_dialog: ft.AlertDialog | None = None
        self.exit_after_conversion_stop = False
        self.page_index = 0
        self.compact_layout: bool | None = None
        self.file_picker = ft.FilePicker()
        self.clipboard = ft.Clipboard()
        self.page.services.extend([self.file_picker, self.clipboard])

        self._build_controls()
        self._configure_page()
        self._show_page(0)
        self._refresh_queue_view()
        if restored_active_task is not None:
            asyncio.create_task(self._activate_task(restored_active_task))

    def _configure_page(self) -> None:
        self.page.title = f"{DISPLAY_NAME} {VERSION}"
        self.page.fonts = {
            PRIMARY_FONT: "/fonts/GoogleSansFlex-Variable.ttf",
            SIMPLIFIED_CHINESE_FONT: "/fonts/NotoSansSC-Variable.ttf",
        }
        self.page.locale_configuration = ft.LocaleConfiguration(
            supported_locales=[ft.Locale("zh", "CN")],
            current_locale=ft.Locale("zh", "CN"),
        )
        self.page.theme = material_light_theme()
        self.page.dark_theme = material_dark_theme()
        self.page.padding = 0
        self.page.window.width = 1120
        self.page.window.height = 760
        self.page.window.min_width = 680
        self.page.window.min_height = 600
        self.page.appbar = ft.AppBar(
            title=ft.Text(DISPLAY_NAME, weight=ft.FontWeight.W_600),
            actions=[
                ft.IconButton(
                    icon=ft.Icons.BRIGHTNESS_AUTO,
                    tooltip="切换主题",
                    on_click=self._cycle_theme,
                ),
                ft.IconButton(
                    icon=ft.Icons.INFO,
                    tooltip="关于",
                    on_click=lambda _: self._show_page(3),
                ),
            ],
        )
        self._apply_theme(self.settings.theme, refresh=False)
        self.page.on_resize = self._on_resize
        self.page.on_keyboard_event = self._on_keyboard_event
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event
        self.page.add(self.shell)
        self._on_resize()

    def _build_controls(self) -> None:
        self.editor_task_name = ft.Text(
            "尚未选择任务", weight=ft.FontWeight.W_500,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.editor_task_hint = ft.Text(
            "添加素材后，在这里单独调整它的参数。",
            size=12, color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self.source_field = ft.TextField(label="当前编辑素材", read_only=True, col={"xs": 12, "md": 6})
        self.output_field = ft.TextField(label="输出 OVID .BIN", read_only=True, expand=True)
        self.width_field = self._number_field(
            "输出宽度", self.settings.width, 1, 255, col=4, on_change=self._on_geometry_change
        )
        self.height_field = self._number_field(
            "输出高度", self.settings.height, 1, 255, col=4, on_change=self._on_geometry_change
        )
        self.fps_field = self._number_field(
            "FPS", self.settings.fps, 1, 120, col=4, on_change=self._on_geometry_change
        )
        self.skip_frames_field = self._number_field(
            "跳过开头帧", 0, 0, 999999, col=6, on_change=self._on_geometry_change
        )
        self.fit_dropdown = ft.Dropdown(
            label="缩放方式",
            value="contain",
            options=[
                ft.DropdownOption(key="contain", text="完整显示（保留补边）"),
                ft.DropdownOption(key="cover", text="铺满并居中裁剪"),
                ft.DropdownOption(key="stretch", text="拉伸到目标尺寸"),
            ],
            on_select=self._on_geometry_change,
        )
        self.dither_control = ft.SegmentedButton(
            segments=[
                ft.Segment(
                    value="threshold",
                    label=ft.Row(
                        [
                            ft.Text("固定阈值"),
                            ft.Icon(
                                ft.Icons.HELP_OUTLINE,
                                size=16,
                                tooltip=(
                                    "建议先使用 128。画面偏暗、细节丢失时调低；"
                                    "背景发白、噪点过多时调高。常用范围为 96–160。"
                                    "Floyd 抖动不使用此阈值。"
                                ),
                            ),
                        ],
                        spacing=4,
                    ),
                    icon=ft.Icons.CONTRAST,
                ),
                ft.Segment(value="floyd", label=ft.Text("Floyd 抖动"), icon=ft.Icons.GRAIN),
            ],
            selected=["threshold"],
            on_change=self._on_dither_change,
        )
        self.threshold_slider = ft.Slider(
            min=0,
            max=255,
            divisions=255,
            value=128,
            label="阈值 {value}",
            disabled=False,
            on_change=self._on_threshold_change,
            expand=True,
        )
        self.threshold_field = self._number_field(
            "阈值", 128, 0, 255, on_change=self._on_threshold_input_change,
        )
        self.threshold_field.width = 108
        self.threshold_field.tooltip = "直接输入 0–255，或拖动左侧滑块；修改会实时更新预览。"
        self.background_dropdown = ft.Dropdown(
            label="补边与透明背景",
            value="black",
            options=[
                ft.DropdownOption(key="black", text="黑色"),
                ft.DropdownOption(key="white", text="白色"),
            ],
            on_select=self._on_geometry_change,
            col={"xs": 12, "md": 6},
        )
        self.invert_switch = ft.Switch(
            label="反转黑白", value=False, on_change=self._on_invert_change
        )
        self.recursive_switch = ft.Switch(
            label="递归读取图片子目录", value=False, on_change=self._on_geometry_change
        )
        self.force_switch = ft.Switch(
            label="允许覆盖已有输出", value=False, on_change=self._on_task_option_change
        )
        self.task_worker_dropdown = ft.Dropdown(
            label="此任务的图像处理线程",
            value=str(self.settings.workers),
            options=[ft.DropdownOption(key="0", text="自动")]
            + [ft.DropdownOption(key=str(value), text=str(value)) for value in range(1, 9)],
            on_select=self._on_task_option_change,
        )
        self.task_fast_video_switch = ft.Switch(
            label="此任务使用快速视频模式",
            tooltip="转换时可能选取临界时间点的相邻帧，不改变桌面预览方式。",
            value=self.settings.fast_video,
            on_change=self._on_task_option_change,
        )
        self.target_dropdown = ft.Dropdown(
            label="设备屏幕（兼容性检查）",
            tooltip="只检查能否在设备上显示，不改变视频输出尺寸。",
            value=self.settings.target_profile,
            options=[
                ft.DropdownOption(key=key, text=value[0])
                for key, value in TARGET_PROFILES.items()
            ],
            on_select=self._on_target_profile_change,
        )
        self.screen_size_hint = ft.Text(size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.match_target_button = ft.TextButton(
            "使用设备尺寸", icon=ft.Icons.ASPECT_RATIO,
            tooltip="仅点击此按钮才会修改输出宽高；其他参数不变",
            on_click=self._match_target_size,
        )
        self.preset_dropdown = ft.Dropdown(
            label="转换预设",
            hint_text="自定义参数",
            value=BUILTIN_PRESETS[0].name,
            options=[],
            on_select=self._apply_selected_preset,
            col=10,
        )
        self.preset_name_field = ft.TextField(label="新预设名称", expand=True)
        self._refresh_preset_options()

        self.preset_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="管理预设",
            items=[
                ft.PopupMenuItem(content="保存当前参数", icon=ft.Icons.SAVE_AS,
                                 on_click=self._save_preset_dialog),
                ft.PopupMenuItem(content="删除所选自定义预设", icon=ft.Icons.DELETE_OUTLINE,
                                 on_click=self._delete_selected_preset),
                ft.PopupMenuItem(content="清空自定义预设", icon=ft.Icons.RESTORE,
                                 on_click=self._reset_user_presets),
            ],
        )
        self.auto_threshold_menu = ft.PopupMenuButton(
            tooltip="根据当前预览帧分析，确认后应用",
            content=ft.Row([
                ft.Icon(ft.Icons.AUTO_FIX_HIGH, size=18),
                ft.Text("自动阈值"), ft.Icon(ft.Icons.ARROW_DROP_DOWN),
            ], tight=True, spacing=6),
            items=[
                ft.PopupMenuItem(content="标准", data="standard", on_click=self._auto_threshold_clicked),
                ft.PopupMenuItem(content="保留暗部", data="dark-detail", on_click=self._auto_threshold_clicked),
                ft.PopupMenuItem(content="减少噪点", data="noise-reduction", on_click=self._auto_threshold_clicked),
            ],
        )

        self.drop_zone = None
        if FletDropZone is not None:
            self.drop_zone = FletDropZone(
                message="从资源管理器拖入图片、GIF、视频或图片目录",
                active_message="松开鼠标以载入素材",
                on_drop=self._on_system_drop,
            )

        self.trim_slider = ft.RangeSlider(
            min=0,
            max=1,
            start_value=0,
            end_value=1,
            round=2,
            label="{value} 秒",
            disabled=True,
            on_change_start=self._trim_drag_start,
            on_change=self._trim_drag_changed,
            on_change_end=self._on_trim_change,
        )
        self.trim_label = ft.Text("单张图片无需裁剪", color=ft.Colors.ON_SURFACE_VARIANT)
        self.trim_error = ft.Text("", color=ft.Colors.ERROR, visible=False)
        self.trim_actions = ft.Row(
            [
                ft.TextButton("精确裁剪", icon=ft.Icons.CONTENT_CUT, on_click=self._edit_trim_dialog),
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_HORIZ,
                    tooltip="按预览位置裁剪或恢复完整范围",
                    items=[
                        ft.PopupMenuItem(content="以当前帧为起点", data="start", on_click=self._trim_at_playhead),
                        ft.PopupMenuItem(content="以当前帧为终点（包含此帧）", data="end", on_click=self._trim_at_playhead),
                        ft.PopupMenuItem(content="恢复完整范围", data="reset", on_click=self._trim_at_playhead),
                    ],
                ),
            ],
            spacing=4,
            wrap=True,
        )
        self.trim_controls = ft.Column(
            [
                ft.Text("导出范围 · 仅此区间写入 BIN", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                self.trim_slider,
                self.trim_label,
                self.trim_error,
                self.trim_actions,
            ],
            spacing=8,
            visible=False,
        )
        self.preview_timeline = ft.Slider(
            min=0,
            max=1,
            value=0,
            round=2,
            label="{value} 秒",
            visible=False,
            on_change_start=self._preview_drag_start,
            on_change=self._preview_drag_changed,
            on_change_end=self._preview_seek,
        )
        self.preview_time_label = ft.Text(
            "00:00.00 / --:--.--",
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        self.original_preview_image = ft.Image(
            src=self._empty_preview(),
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            filter_quality=ft.FilterQuality.MEDIUM,
            height=260,
        )
        self.preview_image = ft.Image(
            src=self._empty_preview(),
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            filter_quality=ft.FilterQuality.NONE,
            anti_alias=False,
            height=260,
        )
        self.preview_snapshot: PreviewSnapshot | None = None
        self.pixel_inspector: PixelInspector | None = None
        self.preview_view_mode = ft.SegmentedButton(
            segments=[
                ft.Segment(value="compare", label=ft.Text("对比")),
                ft.Segment(value="oled", label=ft.Text("仅 OLED")),
                ft.Segment(value="source", label=ft.Text("仅原图")),
            ],
            selected=["compare"],
            on_change=self._on_preview_view_mode,
        )
        self.inspect_preview_button = ft.TextButton(
            "查看 OLED 帧", icon=ft.Icons.ZOOM_IN,
            tooltip="固定当前帧，按整数倍查看像素；不改变转换参数",
            disabled=True,
            on_click=self._inspect_preview_frame,
        )
        self.preview_label = ft.Text("尚未载入素材", color=ft.Colors.ON_SURFACE_VARIANT)
        self.preview_play_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            tooltip="播放预览",
            on_click=self._toggle_preview_playback,
        )

        self.progress_bar = ft.ProgressBar(value=0, visible=False)
        self.progress_text = ft.Text("准备就绪", color=ft.Colors.ON_SURFACE_VARIANT)
        self.convert_button = ft.FilledButton(
            "转换所选",
            icon=ft.Icons.MOVIE,
            on_click=self._start_conversion,
            tooltip="转换所选任务 (Ctrl+Enter)",
            disabled=True,
        )
        self.cancel_button = ft.OutlinedButton(
            "停止本轮",
            icon=ft.Icons.CANCEL,
            on_click=self._cancel_conversion,
            visible=False,
        )

        self.queue_list = ft.Column(spacing=8)
        self.queue_status = ft.Text("队列为空", color=ft.Colors.ON_SURFACE_VARIANT)
        self.select_all_button = ft.TextButton("全选", on_click=self._select_all_tasks)
        self.select_none_button = ft.TextButton("全不选", on_click=self._select_no_tasks)
        self.clear_completed_button = ft.TextButton(
            "清理已完成", on_click=self._clear_completed_jobs
        )
        self.apply_selected_button = ft.OutlinedButton(
            "复制参数到勾选任务",
            icon=ft.Icons.COPY_ALL,
            tooltip="保留各任务的素材、输出路径和裁剪范围",
            on_click=self._apply_active_options_to_selected,
        )
        self.queue_empty_state = ft.Container(
            visible=True,
            padding=ft.Padding.symmetric(vertical=28, horizontal=16),
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.VIDEO_FILE_OUTLINED, size=40, color=ft.Colors.OUTLINE),
                    ft.Text("还没有转换任务", size=16, weight=ft.FontWeight.W_500),
                    ft.Text(
                        "使用上方“添加素材”或“添加图片目录”，然后勾选需要转换的任务。",
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
        )
        self.task_action_status = ft.Text(
            "添加素材后即可开始转换",
            weight=ft.FontWeight.W_500,
        )

        self.player_path = ft.TextField(label="OVID 文件", read_only=True, expand=True)
        self.player_image = ft.Image(
            src=self._empty_preview(),
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            filter_quality=ft.FilterQuality.NONE,
            anti_alias=False,
            height=360,
        )
        self.player_label = ft.Text("尚未打开 OVID 文件", color=ft.Colors.ON_SURFACE_VARIANT)
        self.player_slider = ft.Slider(
            min=0,
            max=1,
            value=0,
            round=2,
            label="{value} 秒",
            disabled=True,
            on_change_start=self._player_drag_start,
            on_change=self._player_drag_changed,
            on_change_end=self._player_seek,
        )
        self.player_time_label = ft.Text(
            "00:00.00 / --:--.--",
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self.player_invert = ft.Switch(label="反显", value=False, on_change=self._player_redraw)
        self.player_scale = ft.Dropdown(
            label="预览倍数",
            value="4",
            width=140,
            options=[ft.DropdownOption(key=str(value), text=f"{value}×") for value in (1, 2, 4, 6, 8)],
            on_select=self._player_redraw,
        )
        self.player_playing = False
        self.player_revision = 0
        self.player_play_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            tooltip="播放 OVID",
            on_click=self._toggle_player,
        )

        self.convert_page = self._build_convert_page()
        self.player_page = self._build_player_page()
        self.settings_page = self._build_settings_page()
        self.about_page = self._build_about_page()
        self.page_host = ft.Container(expand=True, padding=ft.Padding.all(20))

        destinations = [
            ft.NavigationRailDestination(icon=icon, label=label)
            for icon, label in NAVIGATION_ITEMS
        ]
        self.navigation_rail = ft.NavigationRail(
            destinations=destinations,
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            on_change=lambda event: self._show_page(event.control.selected_index),
            min_width=88,
        )
        self.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=icon, label=label)
                for icon, label in NAVIGATION_ITEMS
            ],
            selected_index=0,
            on_change=lambda event: self._show_page(event.control.selected_index),
        )
        self.shell = ft.Row(
            [
                self.navigation_rail,
                ft.VerticalDivider(width=1),
                self.page_host,
            ],
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self._sync_preset_selection()
        self._update_screen_size_hint(refresh=False)

    def _number_field(
        self,
        label: str,
        value: int,
        minimum: int,
        maximum: int,
        *,
        col: int = 4,
        on_change=None,
    ) -> ft.TextField:
        return ft.TextField(
            label=label,
            value=str(value),
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            helper=f"{minimum}–{maximum}",
            col={"xs": col},
            on_change=on_change,
        )

    def _card(self, title: str, icon, controls, *, col=12, key=None) -> ft.Card:
        return ft.Card(
            variant=ft.CardVariant.FILLED,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            col=col,
            key=key,
            content=ft.Container(
                padding=20,
                content=ft.Column(
                    [
                        ft.Row([ft.Icon(icon), ft.Text(title, size=18, weight=ft.FontWeight.W_600)]),
                        *controls,
                    ],
                    spacing=14,
                ),
            ),
        )

    def _build_convert_page(self):
        source_actions = ft.Row(
            [
                ft.OutlinedButton(
                    "添加素材",
                    icon=ft.Icons.ADD,
                    tooltip="添加图片、GIF 或视频，可多选 (Ctrl+O)",
                    on_click=self._choose_file,
                ),
                ft.OutlinedButton("添加图片目录", icon=ft.Icons.FOLDER_OPEN, on_click=self._choose_directory),
            ],
            wrap=True,
        )
        self.output_button = ft.IconButton(
            icon=ft.Icons.SAVE, tooltip="选择输出位置", on_click=self._choose_output
        )
        output_actions = ft.Row(
            [
                self.output_field,
                self.output_button,
            ],
            col={"xs": 12, "md": 6},
        )
        input_card = self._card(
            "素材与输出",
            ft.Icons.INSERT_DRIVE_FILE,
            [
                *([self.drop_zone] if self.drop_zone is not None else []),
                source_actions,
                ft.ResponsiveRow([self.source_field, output_actions], spacing=12, run_spacing=12),
            ],
            col=12,
            key="source-card",
        )
        self.original_preview_panel = ft.Column(
            [
                ft.Text("原始素材", weight=ft.FontWeight.W_500),
                ft.Container(
                    content=self.original_preview_image, bgcolor=ft.Colors.BLACK,
                    border_radius=16, padding=10, alignment=ft.Alignment.CENTER,
                ),
            ],
            expand=True,
        )
        self.oled_preview_panel = ft.Column(
            [
                ft.Text("OLED 输出", weight=ft.FontWeight.W_500),
                ft.Container(
                    content=self.preview_image, bgcolor=ft.Colors.BLACK,
                    border_radius=16, padding=10, alignment=ft.Alignment.CENTER,
                ),
            ],
            expand=True,
        )
        self.preview_panels = ft.Row(
            [self.original_preview_panel, self.oled_preview_panel],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.START,
        )
        preview_card = self._card(
            "画面预览",
            ft.Icons.IMAGE,
            [
                ft.Row([self.preview_view_mode, self.inspect_preview_button], wrap=True),
                self.preview_panels,
                ft.Row(
                    [
                        ft.IconButton(icon=ft.Icons.SKIP_PREVIOUS, tooltip="回到首帧", on_click=self._preview_first),
                        ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="上一帧", on_click=self._preview_previous),
                        self.preview_play_button,
                        ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="下一帧", on_click=self._preview_next),
                        self.preview_label,
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Text("预览位置", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                self.preview_timeline,
                self.preview_time_label,
                self.trim_controls,
            ],
            col=12,
            key="preview-card",
        )
        parameter_card = self._card(
            "转换参数",
            ft.Icons.TUNE,
            [
                self.editor_task_name,
                self.editor_task_hint,
                ft.ResponsiveRow(
                    [
                        self.preset_dropdown,
                        ft.Container(
                            content=self.preset_menu,
                            col=2,
                            alignment=ft.Alignment.CENTER_RIGHT,
                        ),
                    ],
                    spacing=8,
                    run_spacing=8,
                ),
                ft.ResponsiveRow(
                    [
                        ft.Column(
                            [
                                ft.Text("画面与时间", weight=ft.FontWeight.W_600),
                                ft.ResponsiveRow(
                                    [
                                        self.width_field,
                                        self.height_field,
                                        self.fps_field,
                                    ]
                                ),
                                self.fit_dropdown,
                                self.target_dropdown,
                                self.screen_size_hint,
                                self.match_target_button,
                            ],
                            col={"xs": 12, "lg": 6},
                            spacing=12,
                        ),
                        ft.Column(
                            [
                                ft.Text("黑白处理", weight=ft.FontWeight.W_600),
                                self.dither_control,
                                ft.Row(
                                    [self.threshold_slider, self.threshold_field],
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.START,
                                ),
                                self.auto_threshold_menu,
                                self.invert_switch,
                            ],
                            col={"xs": 12, "lg": 6},
                            spacing=12,
                        ),
                    ],
                    spacing=16,
                    run_spacing=16,
                ),
                ft.ExpansionTile(
                    title=ft.Text("更多设置", weight=ft.FontWeight.W_500),
                    subtitle=ft.Text("跳帧、补边背景、目录读取和输出覆盖"),
                    leading=ft.Icons.TUNE,
                    expanded=False,
                    maintain_state=True,
                    controls_padding=ft.Padding.only(left=16, right=16, bottom=16),
                    controls=[
                        ft.ResponsiveRow(
                            [
                                self.skip_frames_field,
                                self.background_dropdown,
                            ],
                            spacing=12,
                            run_spacing=12,
                        ),
                        ft.Row([self.recursive_switch, self.force_switch], wrap=True),
                        self.task_worker_dropdown,
                        self.task_fast_video_switch,
                        ft.OutlinedButton(
                            "重新载入预览",
                            icon=ft.Icons.REFRESH,
                            on_click=self._refresh_preview,
                        ),
                    ],
                ),
                self.apply_selected_button,
            ],
            col=12,
            key="parameter-card",
        )
        action_card = self._card(
            "转换任务",
            ft.Icons.DATA_SAVER_ON,
            [
                ft.Row(
                    [
                        self.select_all_button,
                        self.select_none_button,
                        self.clear_completed_button,
                    ],
                    wrap=True,
                ),
                self.queue_status,
                self.queue_empty_state,
                self.queue_list,
            ],
            col=12,
        )
        self.preview_card = preview_card
        self.parameter_card = parameter_card
        self.editor_row = ft.ResponsiveRow(
            [preview_card, parameter_card], spacing=16, run_spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.convert_scroll = ft.Column(
            [
                input_card,
                self.editor_row,
                action_card,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        task_bar = ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            content=ft.Column(
                [
                    ft.ResponsiveRow(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.DATA_SAVER_ON, color=ft.Colors.PRIMARY),
                                    ft.Column(
                                        [self.task_action_status, self.progress_text],
                                        spacing=2,
                                        expand=True,
                                    ),
                                ],
                                col={"xs": 12, "md": 8},
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [self.cancel_button, self.convert_button],
                                col={"xs": 12, "md": 4},
                                alignment=ft.MainAxisAlignment.END,
                            ),
                        ],
                        spacing=8,
                        run_spacing=8,
                    ),
                    self.progress_bar,
                ],
                spacing=8,
            ),
        )
        return ft.Column([self.convert_scroll, task_bar], spacing=0, expand=True)

    def _build_player_page(self):
        return ft.Column(
            [
                ft.Text("OVID 播放模拟器", size=28, weight=ft.FontWeight.W_600),
                ft.Row(
                    [
                        self.player_path,
                        ft.OutlinedButton(
                            "打开 .BIN", icon=ft.Icons.FOLDER_OPEN,
                            tooltip="打开 OVID 文件 (Ctrl+O)", on_click=self._choose_ovid_file
                        ),
                    ]
                ),
                ft.Container(
                    content=self.player_image,
                    bgcolor=ft.Colors.BLACK,
                    border_radius=16,
                    padding=12,
                    alignment=ft.Alignment.CENTER,
                ),
                self.player_slider,
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.SKIP_PREVIOUS,
                            tooltip="回到首帧 (Home)",
                            on_click=self._player_first,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_LEFT,
                            tooltip="上一帧 (←)",
                            on_click=self._player_previous,
                        ),
                        self.player_play_button,
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_RIGHT,
                            tooltip="下一帧 (→)",
                            on_click=self._player_next,
                        ),
                        self.player_invert,
                        self.player_scale,
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
                self.player_label,
                self.player_time_label,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_settings_page(self):
        self.default_width = self._number_field("默认宽度", self.settings.width, 1, 255)
        self.default_height = self._number_field("默认高度", self.settings.height, 1, 255)
        self.default_fps = self._number_field("默认 FPS", self.settings.fps, 1, 120)
        self.default_target = ft.Dropdown(
            label="默认目标屏幕",
            value=self.settings.target_profile,
            options=[
                ft.DropdownOption(key=key, text=value[0])
                for key, value in TARGET_PROFILES.items()
            ],
        )
        self.worker_dropdown = ft.Dropdown(
            label="图像处理线程",
            value=str(self.settings.workers),
            options=[ft.DropdownOption(key="0", text="自动")]
            + [ft.DropdownOption(key=str(value), text=str(value)) for value in range(1, 9)],
        )
        self.fast_video_switch = ft.Switch(
            label="快速视频模式（临界时间点可能选择相邻帧）",
            value=self.settings.fast_video,
        )
        self.default_output = ft.TextField(
            label="默认输出目录",
            value=self.settings.output_directory,
            read_only=True,
            expand=True,
        )
        self.theme_dropdown = ft.Dropdown(
            label="主题",
            value=self.settings.theme,
            options=[
                ft.DropdownOption(key="system", text="跟随系统"),
                ft.DropdownOption(key="light", text="浅色"),
                ft.DropdownOption(key="dark", text="深色"),
            ],
        )
        return ft.Column(
            [
                ft.Text("设置", size=28, weight=ft.FontWeight.W_600),
                self._card(
                    "默认转换参数",
                    ft.Icons.TUNE,
                    [
                        ft.Text(
                            "默认值用于空任务列表与下次启动，不修改已有任务。"
                            "继续添加素材时沿用当前任务的参数。",
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.ResponsiveRow([self.default_width, self.default_height, self.default_fps]),
                        self.default_target,
                        ft.Row([
                            self.default_output,
                            ft.IconButton(icon=ft.Icons.FOLDER_OPEN, on_click=self._choose_default_output),
                        ]),
                        self.theme_dropdown,
                        self.worker_dropdown,
                        self.fast_video_switch,
                        ft.FilledButton("保存设置", icon=ft.Icons.SAVE, on_click=self._save_settings),
                    ],
                ),
                self._card(
                    "转换日志",
                    ft.Icons.RECEIPT_LONG,
                    [
                        ft.Text("日志仅保存在本机，最多保留 5 个、每个约 1 MiB。"),
                        ft.Row(
                            [
                                ft.OutlinedButton("查看日志", on_click=self._show_logs),
                                ft.OutlinedButton("导出日志", on_click=self._export_logs),
                            ]
                        ),
                    ],
                ),
                ft.Text(
                    "设置保存在当前用户的 LocalAppData 中，卸载应用时不会删除。",
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_about_page(self):
        return ft.Column(
            [
                ft.Text(DISPLAY_NAME, size=32, weight=ft.FontWeight.W_600),
                ft.Text(f"v{VERSION} · OVID v2", size=18, color=ft.Colors.PRIMARY),
                self._card(
                    "关于",
                    ft.Icons.INFO,
                    [
                        ft.Text(
                            "将图片、GIF、图片序列和视频转换为 SD Card OVID Player 使用的单色页主序视频。"
                        ),
                        ft.Text(
                            "转换器使用 Flet、Pillow、imageio-ffmpeg 和 FFmpeg。完整第三方许可随发行包提供。",
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.OutlinedButton("打开 GitHub 项目", icon=ft.Icons.OPEN_IN_NEW, url=REPOSITORY_URL),
                    ],
                ),
                self._card(
                    "当前限制",
                    ft.Icons.WARNING_AMBER,
                    [
                        ft.Text("预发布版仅提供 Windows x64 图形界面。"),
                        ft.Text("视频音轨不会写入 OVID；输出始终为 OVID v2。"),
                    ],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _empty_preview(self) -> bytes:
        from PIL import Image, ImageDraw
        import io

        image = Image.new("RGB", (512, 256), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((1, 1, 510, 254), outline="#5f6368", width=2)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def _options(self, *, require_output: bool = True) -> ConversionOptions:
        source = Path(self.source_field.value.strip()) if self.source_field.value.strip() else Path()
        output_value = self.output_field.value.strip()
        output = Path(output_value) if output_value else Path("preview.bin")
        if not self.source_field.value.strip():
            raise ValueError("请先选择输入素材")
        if require_output and not output_value:
            raise ValueError("请选择输出 .BIN 文件")
        return self._options_for_source(source, output)

    def _options_for_source(
        self,
        source: Path,
        output: Path,
        *,
        use_current_trim: bool = True,
    ) -> ConversionOptions:
        trim_start, trim_end = 0.0, None
        if use_current_trim:
            if self.pending_trim_range is not None:
                trim_start, trim_end = self.pending_trim_range
            elif not self.trim_slider.disabled:
                trim_start = float(self.trim_slider.start_value)
                trim_end = float(self.trim_slider.end_value)
        return ConversionOptions(
            source=source,
            output=output,
            width=int(self.width_field.value),
            height=int(self.height_field.value),
            fps=int(self.fps_field.value),
            fit=self.fit_dropdown.value,
            dither=self.dither_control.selected[0],
            threshold=(
                int(self.threshold_field.value)
                if self.dither_control.selected[0] == "threshold"
                else round(float(self.threshold_slider.value))
            ),
            invert=self.invert_switch.value,
            background=self.background_dropdown.value,
            recursive=self.recursive_switch.value,
            force=self.force_switch.value,
            skip_frames=int(self.skip_frames_field.value),
            trim_start_seconds=trim_start,
            trim_end_seconds=trim_end,
            workers=int(self.task_worker_dropdown.value),
            fast_video=bool(self.task_fast_video_switch.value),
        )

    async def _choose_file(self, _):
        files = await self.file_picker.pick_files(
            dialog_title="选择一个或多个图片、GIF 或视频",
            allowed_extensions=sorted({suffix[1:] for suffix in IMAGE_SUFFIXES | VIDEO_SUFFIXES}),
            allow_multiple=True,
        )
        if files:
            await self._add_sources(Path(item.path) for item in files if item.path)

    async def _choose_queue_files(self, _):
        await self._choose_file(None)

    async def _add_sources(self, sources) -> None:
        sources = [Path(source) for source in sources]
        if not sources:
            return
        if not self._validate_editor_numbers() or not self._save_editor_before_action():
            self._show_notice("请先修正当前参数，再添加素材。")
            return
        configured_output_dir = (
            Path(self.settings.output_directory)
            if self.settings.output_directory
            else None
        )
        added: list[QueueJob] = []
        for source in sources:
            if not is_supported_source(source):
                continue
            output_dir = configured_output_dir or source.parent
            output = output_dir / f"{source.stem}.BIN"
            job = self.queue.add(
                self._options_for_source(source, output, use_current_trim=False),
                target_profile=self.target_dropdown.value,
            )
            added.append(job)
            self.logger.event("task", f"added {job.options.source} -> {job.options.output}")
        self._refresh_queue_view()
        if added:
            self._show_page(0)
            await self._activate_task(added[0].id, scroll_target="preview-card")
            if len(added) > 1:
                self._show_notice(f"已添加 {len(added)} 个转换任务")

    async def _on_system_drop(self, event) -> None:
        paths = parse_drop_paths(getattr(event, "data", None))
        if not paths:
            self._show_notice("没有识别到可读取的路径")
            return

        unsupported = [path for path in paths if not is_supported_source(path) and path.suffix.lower() != ".bin"]
        paths = [path for path in paths if path not in unsupported]
        if unsupported:
            names = "、".join(path.name for path in unsupported[:3])
            suffix = " 等" if len(unsupported) > 3 else ""
            self._show_notice(f"已忽略不支持的素材：{names}{suffix}")
        if not paths:
            return

        if len(paths) == 1 and paths[0].suffix.lower() == ".bin":
            self._open_player_path(paths[0], show_page=True)
            return

        sources = [path for path in paths if is_supported_source(path)]
        if not sources:
            self._show_notice("批量拖放仅支持图片、GIF、视频或图片目录")
            return
        await self._add_sources(sources)

    def _task_time_range(self, options: ConversionOptions) -> str:
        start = format_timestamp(options.trim_start_seconds)
        end = format_timestamp(options.trim_end_seconds)
        if options.trim_end_seconds is None:
            time_range = f"{start}–结尾" if options.trim_start_seconds > 0 else "完整素材"
        else:
            time_range = f"{start}–{end}"
        if options.skip_frames:
            skipped = f"跳过前 {options.skip_frames} 帧"
            return skipped if time_range == "完整素材" else f"{time_range} · {skipped}"
        return time_range

    def _queue_state_text(self, job: QueueJob) -> str:
        names = {
            "queued": "等待中",
            "running": "转换中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }
        detail = names.get(job.state, job.state)
        if job.progress is not None:
            if job.progress.ratio is not None:
                detail += f" · {job.progress.ratio * 100:.1f}%"
            detail += f" · {job.progress.completed_frames} 帧"
        if job.error:
            detail += f" · {job.error}"
        return detail

    def _task_row_actions(self, job: QueueJob) -> list[ft.Control]:
        actions: list[ft.Control] = [
            ft.IconButton(
                icon=ft.Icons.VISIBILITY_OUTLINED,
                tooltip="编辑并预览源素材",
                on_click=lambda _, job_id=job.id: asyncio.create_task(
                    self._activate_task(job_id, scroll_target="preview-card")
                ),
            )
        ]
        if job.state == "completed" and job.summary is not None:
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                    tooltip="播放生成的 OVID",
                    on_click=lambda _, job_id=job.id: self._play_completed_job(job_id),
                )
            )
            actions.append(
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    tooltip="更多输出操作",
                    items=[
                        ft.PopupMenuItem(
                            content="打开输出文件夹",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda _, job_id=job.id: self._open_completed_job_folder(
                                job_id
                            ),
                        ),
                        ft.PopupMenuItem(
                            content="复制输出路径",
                            icon=ft.Icons.CONTENT_COPY,
                            on_click=lambda _, job_id=job.id: asyncio.create_task(
                                self._copy_completed_job_path(job_id)
                            ),
                        ),
                        ft.PopupMenuItem(
                            content="移除任务",
                            icon=ft.Icons.DELETE_OUTLINE,
                            on_click=lambda _, job_id=job.id: self._remove_queue_job(job_id),
                        ),
                    ],
                )
            )
        if job.state in {"failed", "cancelled"}:
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="重新排队（之后点击转换所选）",
                    disabled=job.frozen,
                    on_click=lambda _, job_id=job.id: self._retry_queue_job(job_id),
                )
            )
        if job.state == "failed":
            actions.append(
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    tooltip="失败任务操作",
                    items=[
                        ft.PopupMenuItem(
                            content="查看错误详情",
                            icon=ft.Icons.ERROR_OUTLINE,
                            on_click=lambda _, job_id=job.id: self._show_task_error(job_id),
                        ),
                        ft.PopupMenuItem(
                            content="移除任务",
                            icon=ft.Icons.DELETE_OUTLINE,
                            disabled=job.frozen,
                            on_click=lambda _, job_id=job.id: self._remove_queue_job(job_id),
                        ),
                    ],
                )
            )
        if (
            job.state not in {"running", "failed"}
            and not job.frozen
            and not (job.state == "completed" and job.summary is not None)
        ):
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    tooltip="移除",
                    on_click=lambda _, job_id=job.id: self._remove_queue_job(job_id),
                )
            )
        return actions

    def _create_task_row(self, job: QueueJob) -> TaskRowView:
        checkbox = ft.Checkbox(
            tooltip="勾选后由“转换所选”处理",
            on_change=lambda event, job_id=job.id: self._set_task_selected(
                job_id, bool(event.control.value)
            ),
        )
        name = ft.Text(
            weight=ft.FontWeight.W_600,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        details = ft.Text(size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        state = ft.Text(
            color=ft.Colors.ON_SURFACE_VARIANT,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        progress = ft.ProgressBar(value=0, visible=False)
        clickable = ft.Container(
            expand=True,
            padding=ft.Padding.symmetric(vertical=4),
            tooltip="编辑此任务的参数；勾选框只决定是否参与转换",
            on_click=lambda _, job_id=job.id: asyncio.create_task(
                self._activate_task(job_id, scroll_target="parameter-card")
            ),
            content=ft.Column(
                [name, details, state, progress],
                spacing=3,
            ),
        )
        actions = ft.Row(spacing=0)
        container = ft.Container(
            padding=12,
            border_radius=12,
            content=ft.Row(
                [checkbox, clickable, actions],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        row = TaskRowView(
            card=ft.Card(content=container),
            container=container,
            checkbox=checkbox,
            name=name,
            details=details,
            state=state,
            progress=progress,
            actions=actions,
        )
        self._update_task_row(row, job)
        return row

    def _update_task_row(self, row: TaskRowView, job: QueueJob) -> bool:
        details = (
            f"{job.options.width}×{job.options.height} · {job.options.fps} FPS · "
            f"{self._task_time_range(job.options)}"
        )
        state_text = self._queue_state_text(job)
        if job.id == self.active_task_id:
            state_text = f"正在编辑 · {state_text}"
        progress = job.progress.ratio if job.progress is not None else 0
        action_signature = (
            job.state == "completed" and job.summary is not None,
            job.state in {"failed", "cancelled"},
            job.state != "running" and not job.frozen,
            job.state == "failed",
        )
        signature = (
            job.options.source.name,
            str(job.options.source),
            details,
            state_text,
            bool(job.selected),
            bool(job.frozen or job.state == "running"),
            progress,
            job.state == "running",
            job.id == self.active_task_id,
            action_signature,
        )
        if signature == row.signature:
            return False
        if not row.signature or action_signature != row.signature[-1]:
            row.actions.controls = self._task_row_actions(job)
        row.checkbox.value = job.selected
        row.checkbox.disabled = job.frozen or job.state == "running"
        row.name.value = job.options.source.name
        row.name.tooltip = str(job.options.source)
        row.details.value = details
        row.state.value = state_text
        row.state.max_lines = 2 if job.error else 1
        row.state.tooltip = state_text if job.error else None
        row.progress.value = progress
        row.progress.visible = job.state == "running"
        row.container.border = (
            ft.Border.all(2, ft.Colors.PRIMARY)
            if job.id == self.active_task_id
            else None
        )
        row.signature = signature
        return True

    def _refresh_queue_view(self) -> None:
        jobs = self.queue.snapshot()
        if not hasattr(self, "task_rows"):
            self.task_rows = {}
        job_ids = {job.id for job in jobs}
        structure_changed = job_ids != set(self.task_rows)
        changed_rows: list[ft.Control] = []
        for job in jobs:
            row = self.task_rows.get(job.id)
            if row is None:
                row = self._create_task_row(job)
                self.task_rows[job.id] = row
                structure_changed = True
            elif self._update_task_row(row, job):
                changed_rows.append(row.container)
        for stale_id in set(self.task_rows) - job_ids:
            del self.task_rows[stale_id]
        if structure_changed:
            self.queue_list.controls = [self.task_rows[job.id].card for job in jobs]
        if not jobs:
            self.queue_status.value = "尚未添加转换任务"
        else:
            completed = sum(job.state == "completed" for job in jobs)
            selected = sum(job.selected for job in jobs)
            self.queue_status.value = (
                f"共 {len(jobs)} 项 · 已勾选 {selected} 项 · 已完成 {completed} 项"
            )
        selectable = [
            job
            for job in jobs
            if job.selected and job.state != "running" and not job.frozen
        ]
        active = next((job for job in jobs if job.id == self.active_task_id), None)
        applicable = [
            job
            for job in jobs
            if job.selected
            and job.id != self.active_task_id
            and job.state != "running"
            and not job.frozen
        ]
        busy = bool(getattr(self, "busy", False))
        self.queue_empty_state.visible = not jobs
        self.convert_button.disabled = busy or not selectable
        self.select_all_button.disabled = not jobs
        self.select_none_button.disabled = not jobs
        self.clear_completed_button.disabled = not any(
            job.state in {"completed", "cancelled"} for job in jobs
        )
        self.apply_selected_button.disabled = (
            active is None
            or active.state == "running"
            or active.frozen
            or not applicable
        )
        editor_controls = self._update_editor_context(active, len(applicable))
        if busy:
            current = getattr(self, "batch_current_name", "")
            if getattr(self, "stop_batch_requested", False):
                self.task_action_status.value = "正在停止本轮…"
            else:
                self.task_action_status.value = f"正在转换{f'：{current}' if current else ''}"
        elif selectable:
            self.task_action_status.value = f"已选择 {len(selectable)} 个任务"
        elif jobs:
            self.task_action_status.value = "请选择需要转换的任务"
        else:
            self.task_action_status.value = "添加素材后即可开始转换"
        controls_to_update: list[ft.Control] = [
            self.queue_status,
            self.queue_empty_state,
            self.convert_button,
            self.select_all_button,
            self.select_none_button,
            self.clear_completed_button,
            self.apply_selected_button,
            self.task_action_status,
            *editor_controls,
        ]
        if structure_changed:
            controls_to_update.insert(0, self.queue_list)
        else:
            controls_to_update[0:0] = changed_rows
        if getattr(self, "page_index", 0) == 0:
            self.page.update(*controls_to_update)
        self._schedule_session_save()

    def _update_editor_context(self, active: QueueJob | None, other_count: int) -> list[ft.Control]:
        self.apply_selected_button.content = (
            f"复制参数到另外 {other_count} 个任务" if other_count else "复制参数到勾选任务"
        )
        if not hasattr(self, "editor_task_name"):
            return []
        self.editor_task_name.value = (
            f"正在编辑：{active.options.source.name}" if active else "尚未选择任务"
        )
        self.editor_task_name.tooltip = str(active.options.source) if active else None
        if active is None:
            hint = "添加素材后，在这里单独调整它的参数。"
        elif active.frozen or active.state == "running":
            hint = "此任务已加入本轮转换，参数暂时只读。"
        else:
            hint = "修改仅应用于此任务；勾选框只决定哪些任务参与转换。"
        self.editor_task_hint.value = hint
        return [self.editor_task_name, self.editor_task_hint]

    def _schedule_session_save(self) -> None:
        if not hasattr(self, "session_store"):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = getattr(self, "session_save_task", None)
        if task is not None and not task.done():
            task.cancel()
        self.session_save_task = loop.create_task(self._save_session_after_delay())

    async def _save_session_after_delay(self) -> None:
        try:
            await asyncio.sleep(0.5)
            self.session_store.save(self.queue.snapshot(), self.active_task_id)
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            self.logger.event("session", f"failed to save session: {exc}", level=30)

    def _set_task_selected(self, job_id: str, selected: bool) -> None:
        self.queue.set_selected(job_id, selected)
        self._refresh_queue_view()

    def _select_all_tasks(self, _) -> None:
        for job in self.queue.snapshot():
            self.queue.set_selected(job.id, True)
        self._refresh_queue_view()

    def _select_no_tasks(self, _) -> None:
        for job in self.queue.snapshot():
            self.queue.set_selected(job.id, False)
        self._refresh_queue_view()

    def _retry_queue_job(self, job_id: str) -> None:
        try:
            job = self.queue.find(job_id)
        except KeyError:
            self._show_notice("任务已移除，无需重新排队。")
            return
        if job.state not in {"failed", "cancelled"}:
            return
        try:
            self.queue.retry(job_id)
            self.queue.set_selected(job_id, True)
        except ValueError as exc:
            self._show_notice(str(exc))
            return
        self._refresh_queue_view()
        self._show_notice("已重新排队并勾选，点击“转换所选”后开始。")

    def _show_task_error(self, job_id: str) -> None:
        try:
            job = self.queue.find(job_id)
        except KeyError:
            self._show_notice("任务已移除，没有可查看的错误详情。")
            return
        if job.state != "failed":
            self._show_notice("任务状态已变化，请查看列表中的最新状态。")
            return

        async def edit(feedback: ErrorDetailsDialog) -> None:
            try:
                current = self.queue.find(job_id)
            except KeyError:
                feedback.show_status("任务已移除；此处仍可复制当时的错误详情。", error=True)
                return
            if current.frozen or current.state == "running":
                feedback.show_status("任务已加入本轮转换，结束后才能修改参数。", error=True)
                return
            if not self._save_editor_before_action():
                feedback.show_status("请先关闭此窗口，修正当前编辑任务的参数。", error=True)
                return
            feedback.close()
            try:
                self._show_page(0)
                await self._activate_task(
                    job_id, scroll_target="parameter-card", preview_errors=False,
                )
            except Exception as exc:
                self._show_error("无法打开任务参数", exc)

        ErrorDetailsDialog(
            self.page, self.clipboard, ErrorReport.from_job(job), on_edit=edit,
        ).show(self._show_dialog)

    def _play_completed_job(self, job_id: str) -> None:
        try:
            job = self.queue.find(job_id)
            if job.summary is None:
                raise ValueError("当前任务还没有可播放的输出")
            self._open_player_path(job.summary.path, show_page=True)
        except Exception as exc:
            self._show_error("无法播放转换结果", exc)

    def _completed_job_path(self, job_id: str) -> Path:
        job = self.queue.find(job_id)
        if job.summary is None:
            raise ValueError("当前任务还没有可用的输出文件")
        return job.summary.path.resolve()

    def _open_completed_job_folder(self, job_id: str) -> None:
        try:
            output = self._completed_job_path(job_id)
            if not output.parent.is_dir():
                raise FileNotFoundError(f"输出目录不存在：{output.parent}")
            os.startfile(output.parent)
        except Exception as exc:
            self._show_error("无法打开输出文件夹", exc)

    async def _copy_completed_job_path(self, job_id: str) -> None:
        try:
            output = self._completed_job_path(job_id)
            await self.clipboard.set(str(output))
            self._show_notice("已复制输出文件路径")
        except Exception as exc:
            self._show_error("无法复制输出路径", exc)

    def _remove_queue_job(self, job_id: str) -> None:
        try:
            self.queue.remove(job_id)
            if self.active_task_id == job_id:
                self.active_task_id = None
                remaining = self.queue.snapshot()
                if remaining:
                    asyncio.create_task(self._activate_task(remaining[0].id))
                else:
                    self._reset_editor_for_empty_queue()
            self._refresh_queue_view()
        except Exception as exc:
            self._show_error("无法移除任务", exc)

    def _clear_completed_jobs(self, _):
        self.queue.clear_completed()
        if self.active_task_id and not any(
            job.id == self.active_task_id for job in self.queue.snapshot()
        ):
            self.active_task_id = None
            remaining = self.queue.snapshot()
            if remaining:
                asyncio.create_task(self._activate_task(remaining[0].id))
            else:
                self._reset_editor_for_empty_queue()
        self._refresh_queue_view()

    def _reset_editor_for_empty_queue(self) -> None:
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_revision += 1
        self.preview_close_task = asyncio.create_task(
            self._close_preview_if_current(self.preview_revision)
        )
        self.pending_trim_range = None
        self.source_info = None
        self.source_info_key = None
        self.source_field.value = ""
        self.output_field.value = ""
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        self.preview_snapshot = None
        self.inspect_preview_button.disabled = True
        self.original_preview_image.src = self._empty_preview()
        self.preview_image.src = self._empty_preview()
        self.preview_label.value = "尚未载入素材"
        self.preview_timeline.visible = False
        self.preview_time_label.value = "00:00.00 / --:--.--"
        self.trim_slider.disabled = True
        self.trim_controls.visible = False
        self.trim_error.value = ""
        self.trim_error.visible = False
        self.trim_label.value = "单张图片无需裁剪"
        self._load_default_editor_options()
        self._set_editor_locked(False)
        self.page.update(
            self.source_field,
            self.output_field,
            self.preview_play_button,
            *self._visible_preview_images(),
            self.inspect_preview_button,
            self.preview_label,
            self.preview_timeline,
            self.preview_time_label,
            self.trim_controls,
        )

    async def _choose_directory(self, _):
        selected = await self.file_picker.get_directory_path(dialog_title="选择图片帧目录")
        if selected:
            await self._add_sources([Path(selected)])

    async def _choose_output(self, _):
        job_id = self.active_task_id
        if not self._can_edit_task(job_id) or not self._save_editor_before_action():
            return
        source = Path(self.source_field.value) if self.source_field.value else None
        suggested = f"{source.stem if source else 'OUTPUT'}.BIN"
        selected = await self.file_picker.save_file(
            dialog_title="保存 OVID 文件",
            file_name=suggested,
            initial_directory=self.settings.output_directory or None,
            allowed_extensions=["BIN", "bin"],
        )
        if selected:
            if not self._can_edit_task(job_id):
                self._show_notice("任务已切换或开始转换，未修改输出位置。")
                return
            path = Path(selected)
            if path.suffix.casefold() != ".bin":
                path = path.with_suffix(".BIN")
            previous = self.output_field.value
            self.output_field.value = str(path)
            if self._save_active_task_options():
                self._refresh_queue_view()
            else:
                self.output_field.value = previous
                self._show_notice("请先修正任务参数，再选择输出位置。")
            self.page.update(self.output_field)

    async def _choose_ovid_file(self, _):
        files = await self.file_picker.pick_files(
            dialog_title="打开 OVID .BIN",
            allowed_extensions=["BIN", "bin"],
            allow_multiple=False,
        )
        if files and files[0].path:
            try:
                self._open_player_path(Path(files[0].path), show_page=True)
            except Exception as exc:
                self._show_error("无法打开 OVID", exc)

    def _open_player_path(self, path: Path, *, show_page: bool) -> None:
        header = self.player.open(path)
        self.player_path.value = str(path)
        self.player_slider.disabled = header.frame_count <= 1
        self.player_slider.min = 0
        self.player_slider.max = max(1 / header.fps, (header.frame_count - 1) / header.fps)
        self.player_slider.value = 0
        self.player_playing = False
        self.player_revision += 1
        self.player_play_button.icon = ft.Icons.PLAY_ARROW
        self._draw_player_frame(0)
        if show_page:
            self._show_page(1)

    def _draw_player_frame(self, index: int) -> None:
        frame = self.player.seek(
            index,
            invert=bool(self.player_invert.value),
            scale=int(self.player_scale.value),
        )
        self.player_image.src = frame.png
        header = self.player.header
        if not self.player_timeline_dragging:
            self.player_slider.value = frame.index / header.fps
        crc = "CRC 正确" if frame.crc_valid else "CRC 错误，保持上一帧"
        self.player_label.value = (
            f"第 {frame.index + 1}/{header.frame_count} 帧 · "
            f"{header.width}×{header.height} · {header.fps} FPS · {crc}"
        )
        current_seconds = frame.index / header.fps
        total_seconds = header.frame_count / header.fps
        self.player_time_label.value = (
            f"{format_timestamp(current_seconds)} / {format_timestamp(total_seconds)}"
        )
        self.page.update(
            self.player_image,
            self.player_slider,
            self.player_label,
            self.player_time_label,
        )

    def _player_drag_start(self, _) -> None:
        self.resume_player_after_drag = self.player_playing
        self.player_timeline_dragging = True
        self.player_playing = False
        self.player_revision += 1
        self.player_play_button.icon = ft.Icons.PLAY_ARROW
        self.page.update(self.player_play_button)

    def _player_drag_changed(self, _) -> None:
        if self.player_time_task is None or self.player_time_task.done():
            self.player_time_task = asyncio.create_task(self._flush_player_time_label())

    async def _flush_player_time_label(self) -> None:
        await asyncio.sleep(TIMELINE_LABEL_INTERVAL)
        if self.player.header is None:
            return
        total = self.player.header.frame_count / self.player.header.fps
        self.player_time_label.value = (
            f"{format_timestamp(float(self.player_slider.value))} / "
            f"{format_timestamp(total)}"
        )
        self.page.update(self.player_time_label)

    async def _player_seek(self, _):
        try:
            if self.player.header is None:
                return
            index = min(
                self.player.header.frame_count - 1,
                max(0, round(float(self.player_slider.value) * self.player.header.fps)),
            )
            self._draw_player_frame(index)
        except Exception as exc:
            self._show_error("无法定位 OVID 帧", exc)
        finally:
            self.player_timeline_dragging = False
            if self.resume_player_after_drag:
                self.resume_player_after_drag = False
                await self._toggle_player(None)

    async def _player_first(self, _):
        if self.player.header is not None:
            self._draw_player_frame(0)

    async def _player_previous(self, _):
        if self.player.header is not None:
            self._draw_player_frame(max(0, self.player.index - 1))

    async def _player_next(self, _):
        if self.player.header is not None:
            self._draw_player_frame(min(self.player.header.frame_count - 1, self.player.index + 1))

    async def _player_redraw(self, _):
        if self.player.header is not None:
            self._draw_player_frame(max(0, self.player.index))

    async def _toggle_player(self, _):
        if self.player.header is None:
            self._show_error("无法播放 OVID", ValueError("请先打开 OVID 文件"))
            return
        if self.player_playing:
            self.player_playing = False
            self.player_revision += 1
            self.player_play_button.icon = ft.Icons.PLAY_ARROW
            self.page.update(self.player_play_button)
            return
        if self.player.index >= self.player.header.frame_count - 1:
            self._draw_player_frame(0)
        self.player_playing = True
        self.player_revision += 1
        revision = self.player_revision
        self.player_play_button.icon = ft.Icons.PAUSE
        self.page.update(self.player_play_button)
        interval = 1 / self.player.header.fps
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        try:
            while self.player_playing and revision == self.player_revision:
                if self.player.index >= self.player.header.frame_count - 1:
                    break
                self._draw_player_frame(self.player.index + 1)
                delay, deadline = advance_preview_deadline(deadline, loop.time(), interval)
                if delay > 0:
                    await asyncio.sleep(delay)
        finally:
            if revision == self.player_revision:
                self.player_playing = False
                self.player_play_button.icon = ft.Icons.PLAY_ARROW
                self.page.update(self.player_play_button)

    async def _choose_default_output(self, _):
        selected = await self.file_picker.get_directory_path(dialog_title="选择默认输出目录")
        if selected:
            self.default_output.value = selected
            self.page.update()

    def _show_logs(self, _):
        content = self.logger.read() or "当前还没有转换日志。"
        self._show_dialog(
            ft.AlertDialog(
                title="转换日志",
                content=ft.Container(
                    content=ft.Text(content, selectable=True, size=12),
                    width=760,
                    height=420,
                ),
                actions=[ft.Button("关闭", on_click=lambda _: self.page.pop_dialog())],
                scrollable=True,
            )
        )

    async def _export_logs(self, _):
        selected = await self.file_picker.save_file(
            dialog_title="导出 OVID Converter 日志",
            file_name="OVID_Converter.log",
            allowed_extensions=["log", "txt"],
        )
        if selected:
            try:
                await asyncio.to_thread(self.logger.export, Path(selected))
                self._show_message("日志已导出", selected)
            except Exception as exc:
                self._show_error("无法导出日志", exc)

    def _set_source(
        self,
        source: Path,
        *,
        output: Path | None = None,
        trim_start: float = 0.0,
        trim_end: float | None = None,
    ) -> None:
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        self.preview_snapshot = None
        self.inspect_preview_button.disabled = True
        self.source_info = None
        self.source_info_key = None
        self.pending_trim_range = (trim_start, trim_end)
        self.preview_timeline_dragging = False
        self.trim_dragging = False
        self.resume_preview_after_drag = False
        self.trim_slider.disabled = True
        self.trim_controls.visible = False
        self.trim_error.value = ""
        self.trim_error.visible = False
        self.trim_slider.min = 0
        self.trim_slider.max = max(1.0, trim_end or 1.0)
        self.trim_slider.start_value = max(0.0, trim_start)
        self.trim_slider.end_value = max(self.trim_slider.start_value, trim_end or 1.0)
        self.trim_label.value = "正在读取素材时间轴…"
        self.source_field.value = str(source)
        output_dir = Path(self.settings.output_directory) if self.settings.output_directory else source.parent
        self.output_field.value = str(output or (output_dir / f"{source.stem}.BIN"))
        self.preview_label.value = "正在载入预览…"
        self.page.update()

    def _can_edit_task(self, job_id: str | None) -> bool:
        if job_id is None or job_id != self.active_task_id:
            return False
        try:
            job = self.queue.find(job_id)
        except KeyError:
            return False
        return not job.frozen and job.state != "running"

    def _load_option_controls(self, options: ConversionOptions, target_profile: str) -> None:
        self.loading_task_controls = True
        try:
            self.width_field.value = str(options.width)
            self.height_field.value = str(options.height)
            self.fps_field.value = str(options.fps)
            self.skip_frames_field.value = str(options.skip_frames)
            self.fit_dropdown.value = options.fit
            self.dither_control.selected = [options.dither]
            self._set_threshold_value(options.threshold)
            self._set_threshold_enabled()
            self.invert_switch.value = options.invert
            self.background_dropdown.value = options.background
            self.recursive_switch.value = options.recursive
            self.force_switch.value = options.force
            self.target_dropdown.value = target_profile
            self.task_worker_dropdown.value = str(options.workers)
            self.task_fast_video_switch.value = options.fast_video
        finally:
            self.loading_task_controls = False
        self._sync_preset_selection()
        self._update_screen_size_hint(refresh=False)

    def _load_default_editor_options(self) -> None:
        options = ConversionOptions(
            Path(), Path("preview.bin"),
            width=self.settings.width,
            height=self.settings.height,
            fps=self.settings.fps,
            workers=self.settings.workers,
            fast_video=self.settings.fast_video,
        )
        self._load_option_controls(options, self.settings.target_profile)

    def _load_job_controls(self, job: QueueJob) -> None:
        self._load_option_controls(job.options, job.target_profile)
        self._set_source(
            job.options.source,
            output=job.options.output,
            trim_start=job.options.trim_start_seconds,
            trim_end=job.options.trim_end_seconds,
        )

    async def _activate_task(
        self, job_id: str, *, scroll_target: str | None = None, preview_errors: bool = True,
    ) -> None:
        if not self._save_editor_before_action():
            return
        try:
            job = self.queue.find(job_id)
        except KeyError:
            return
        self.active_task_id = job.id
        self._load_job_controls(job)
        self._set_editor_locked(job.frozen or job.state == "running")
        self._refresh_queue_view()
        if scroll_target:
            with contextlib.suppress(Exception):
                await self.convert_scroll.scroll_to(key=scroll_target, duration=250)
        await self._load_first_preview(show_errors=preview_errors)

    def _validate_editor_numbers(self) -> bool:
        valid = True
        changed = []
        fields = [
            (self.width_field, 1, 255),
            (self.height_field, 1, 255),
            (self.fps_field, 1, 120),
            (self.skip_frames_field, 0, 999999),
        ]
        if self.dither_control.selected[0] == "threshold":
            fields.append((self.threshold_field, 0, 255))
        for field, minimum, maximum in fields:
            try:
                value = int(field.value)
                error = None if minimum <= value <= maximum else f"请输入 {minimum}–{maximum}"
            except (TypeError, ValueError):
                error = "请输入整数"
            valid = valid and error is None
            if field.error != error:
                field.error = error
                changed.append(field)
        if changed and self.page_index == 0:
            self.page.update(*changed)
        return valid

    def _save_editor_before_action(self) -> bool:
        try:
            job = self.queue.find(self.active_task_id)
        except KeyError:
            return True
        if job.frozen or job.state == "running":
            return True
        if self._save_active_task_options():
            return True
        self._show_notice("请先修正当前任务的参数，再切换任务或开始转换。")
        return False

    def _on_task_option_change(self, _) -> None:
        if self._save_active_task_options():
            self._refresh_queue_view()

    def _update_screen_size_hint(self, *, refresh: bool = True) -> None:
        status = screen_size_status(
            self.width_field.value, self.height_field.value, self.target_dropdown.value,
        )
        self.screen_size_hint.value = status.message
        self.screen_size_hint.color = ft.Colors.ERROR if status.is_error else ft.Colors.ON_SURFACE_VARIANT
        self.match_target_button.disabled = (
            bool(self.parameter_card.disabled)
            or (self.active_task_id is not None and not self._can_edit_task(self.active_task_id))
            or status.target_size is None
            or status.output_size == status.target_size
        )
        if refresh and self.page_index == 0:
            self.page.update(self.screen_size_hint, self.match_target_button)

    def _size_edit_allowed(self) -> bool:
        if self.active_task_id is None:
            return not self.parameter_card.disabled
        if self._can_edit_task(self.active_task_id):
            return True
        try:
            job = self.queue.find(self.active_task_id)
        except KeyError:
            return False
        self._load_option_controls(job.options, job.target_profile)
        self._set_editor_locked(True)
        return False

    def _on_target_profile_change(self, _) -> None:
        if not self._size_edit_allowed():
            return
        self._update_screen_size_hint()
        self._on_task_option_change(None)

    async def _match_target_size(self, _) -> None:
        if not self._size_edit_allowed():
            return
        status = screen_size_status(
            self.width_field.value, self.height_field.value, self.target_dropdown.value,
        )
        if status.target_size is None or status.output_size == status.target_size:
            return
        self.width_field.value, self.height_field.value = map(str, status.target_size)
        self.width_field.error = None
        self.height_field.error = None
        self._update_screen_size_hint(refresh=False)
        self._sync_preset_selection()
        if self.page_index == 0:
            self.page.update(self.width_field, self.height_field, self.screen_size_hint,
                             self.match_target_button, self.preset_dropdown)
        if self._save_active_task_options():
            self._refresh_queue_view()
        await self._on_geometry_change(None)

    def _save_active_task_options(self) -> bool:
        if getattr(self, "loading_task_controls", False) or not getattr(
            self, "active_task_id", None
        ):
            return False
        try:
            job = self.queue.find(self.active_task_id)
            if job.state == "running" or job.frozen:
                return False
            if not self._validate_editor_numbers():
                return False
            options = self._options()
            if (
                job.options.trim_end_seconds is None
                and options.trim_end_seconds == self.trim_slider.max
            ):
                options = replace(options, trim_end_seconds=None)
            self.queue.replace_options(
                job.id,
                options,
                target_profile=self.target_dropdown.value,
            )
            if self._sync_preset_selection() and self.page_index == 0:
                self.page.update(self.preset_dropdown)
            return True
        except (KeyError, OSError, ValueError):
            return False

    def _set_editor_locked(self, locked: bool) -> None:
        controls = (
            self.width_field,
            self.height_field,
            self.fps_field,
            self.skip_frames_field,
            self.fit_dropdown,
            self.background_dropdown,
            self.dither_control,
            self.invert_switch,
            self.recursive_switch,
            self.force_switch,
            self.task_worker_dropdown,
            self.task_fast_video_switch,
            self.target_dropdown,
            self.preset_dropdown,
            self.apply_selected_button,
        )
        for control in controls:
            control.disabled = locked
        self._set_threshold_enabled(locked=locked)
        self.parameter_card.disabled = locked
        self._update_screen_size_hint(refresh=False)
        self.trim_controls.disabled = locked
        self.output_button.disabled = locked
        if self.page_index == 0:
            self.page.update(self.parameter_card, self.trim_controls, self.output_button)

    def _apply_active_options_to_selected(self, _) -> None:
        if not self.active_task_id:
            self._show_notice("请先选择一个任务")
            return
        if not self._save_editor_before_action():
            return
        try:
            active = self.queue.find(self.active_task_id)
        except KeyError:
            return
        changed = 0
        for job in self.queue.snapshot():
            if not job.selected or job.id == active.id or job.frozen or job.state == "running":
                continue
            copied = replace(
                active.options,
                source=job.options.source,
                output=job.options.output,
                trim_start_seconds=job.options.trim_start_seconds,
                trim_end_seconds=job.options.trim_end_seconds,
                skip_frames=job.options.skip_frames,
            )
            self.queue.replace_options(
                job.id,
                copied,
                target_profile=active.target_profile,
            )
            changed += 1
        self._refresh_queue_view()
        self._show_notice(f"已将参数应用到 {changed} 个勾选任务")

    async def _source_info_for_options(self, options: ConversionOptions):
        key = (str(options.source.resolve()), options.fps, options.recursive)
        revision = self.preview_revision
        source_info = self.source_info
        if self.source_info is None or self.source_info_key != key:
            metadata_options = replace(
                options,
                trim_start_seconds=0.0,
                trim_end_seconds=None,
                skip_frames=0,
            )
            source_info = await asyncio.to_thread(probe_source, metadata_options)
            if revision == self.preview_revision:
                self.source_info = source_info
                self.source_info_key = key
        return trim_source_info(source_info, options)

    async def _close_preview_if_current(self, revision: int) -> None:
        async with self.preview_lock:
            if revision == self.preview_revision:
                await asyncio.to_thread(self.preview.close)

    async def _refresh_preview(self, _=None):
        self.preview_revision += 1
        await self._load_first_preview()

    async def _load_first_preview(self, *, show_errors: bool = True):
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        if self.page_index == 0:
            self.page.update(self.preview_play_button)
        revision = self.preview_revision
        render_revision = self.preview_render_revision
        try:
            options = self._options(require_output=False)
            first_probe = self.source_info is None
            async with self.preview_lock:
                if revision != self.preview_revision:
                    return
                await asyncio.to_thread(self.preview.close)
                if revision != self.preview_revision:
                    return
                info = await self._source_info_for_options(options)
                if revision != self.preview_revision:
                    return
                await asyncio.to_thread(self.preview.reset, options, info)
                if revision != self.preview_revision:
                    return
                frame = await asyncio.to_thread(self.preview.next_frame)
                original, data, index = await self._reconcile_preview_frame(
                    frame, revision, render_revision
                )
            if revision != self.preview_revision:
                return
            if first_probe:
                self._configure_trim_timeline(self.source_info)
            total = info.frame_count if info.frame_count is not None else "?"
            estimate = estimate_output_bytes(options, info)
            self._set_preview_frame(
                original,
                data,
                f"第 {index}/{total} 帧 · 预计 {human_size(estimate)}",
                index=index,
            )
        except Exception as exc:
            if revision != self.preview_revision:
                return
            with contextlib.suppress(Exception):
                await self._close_preview_if_current(revision)
            if revision != self.preview_revision:
                return
            empty = self._empty_preview()
            self._set_preview_frame(empty, empty, "预览不可用，请检查素材与参数")
            if show_errors:
                self._show_error("无法预览素材", exc)

    async def _preview_first(self, _):
        self.preview_revision += 1
        await self._load_first_preview()

    async def _preview_next(self, _=None) -> bool:
        revision = self.preview_revision
        render_revision = self.preview_render_revision
        try:
            async with self.preview_lock:
                if revision != self.preview_revision:
                    return False
                frame = await asyncio.to_thread(self.preview.next_frame)
                original, data, index = await self._reconcile_preview_frame(
                    frame, revision, render_revision
                )
            if revision != self.preview_revision:
                return False
            self._set_preview_frame(original, data, f"第 {index} 帧", index=index)
            return True
        except PreviewFinished:
            if revision != self.preview_revision:
                return False
            self.preview_label.value = "已到最后一帧"
            if self.page_index == 0:
                self.page.update(self.preview_label)
            return False
        except Exception as exc:
            if revision != self.preview_revision:
                return False
            self._show_error("无法读取下一帧", exc)
            return False

    async def _preview_previous(self, _):
        revision = self.preview_revision
        render_revision = self.preview_render_revision
        try:
            async with self.preview_lock:
                if revision != self.preview_revision:
                    return
                frame = await asyncio.to_thread(self.preview.previous_frame)
                original, data, index = await self._reconcile_preview_frame(
                    frame, revision, render_revision
                )
            if revision != self.preview_revision:
                return
            self._set_preview_frame(original, data, f"第 {index} 帧", index=index)
        except Exception as exc:
            if revision != self.preview_revision:
                return
            self._show_error("无法读取上一帧", exc)

    async def _reconcile_preview_frame(
        self,
        frame: tuple[bytes, bytes, int],
        source_revision: int,
        render_revision: int,
    ) -> tuple[bytes, bytes, int]:
        """With preview_lock held, apply edits made while a frame was decoding."""
        while (
            source_revision == self.preview_revision
            and render_revision != self.preview_render_revision
        ):
            render_revision = self.preview_render_revision
            frame = await asyncio.to_thread(
                self.preview.rerender_current,
                self.dither_control.selected[0],
                round(float(self.threshold_slider.value)),
                bool(self.invert_switch.value),
            )
        return frame

    def _visible_preview_images(self) -> list[ft.Image]:
        panels = (
            (self.original_preview_panel, self.original_preview_image),
            (self.oled_preview_panel, self.preview_image),
        )
        return [
            image for panel, image in panels
            if any(visible is panel for visible in self.preview_panels.controls)
        ]

    def _on_preview_view_mode(self, _) -> None:
        selected = self.preview_view_mode.selected
        mode = selected[0] if selected else "compare"
        if mode not in {"compare", "oled", "source"}:
            mode = "compare"
        self.preview_view_mode.selected = [mode]
        panels = {
            "compare": [self.original_preview_panel, self.oled_preview_panel],
            "oled": [self.oled_preview_panel],
            "source": [self.original_preview_panel],
        }
        self.preview_panels.controls = panels[mode]
        if self.page_index == 0:
            self.page.update(self.preview_panels, self.preview_view_mode)

    def _inspect_preview_frame(self, _) -> None:
        if self.pixel_inspector is not None and self.pixel_inspector.is_open:
            return
        if self.preview_snapshot is None:
            self._show_notice("请先载入一帧 OLED 预览。")
            return
        self.pixel_inspector = PixelInspector(self.page, self.preview_snapshot)
        self.pixel_inspector.show(self._show_dialog)

    def _set_preview_frame(
        self,
        original: bytes,
        data: bytes,
        label: str,
        *,
        index: int | None = None,
    ) -> None:
        self.original_preview_image.src = original
        self.preview_image.src = data
        self.preview_label.value = label
        controls = [*self._visible_preview_images(), self.preview_label]
        options = self.preview.options
        self.preview_snapshot = (
            PreviewSnapshot(data, options.width, options.height, f"{options.source.name} · {label}")
            if index is not None and options is not None else None
        )
        inspect_disabled = self.preview_snapshot is None
        if self.inspect_preview_button.disabled != inspect_disabled:
            self.inspect_preview_button.disabled = inspect_disabled
            controls.append(self.inspect_preview_button)
        if index is not None and self.preview.options is not None and not self.preview_timeline_dragging:
            position = preview_frame_seconds(self.preview.options, index)
            if self.preview_timeline.visible:
                self.preview_timeline.value = min(self.preview_timeline.max, max(0.0, position))
                controls.append(self.preview_timeline)
            total = self.source_info.duration_seconds if self.source_info is not None else None
            self.preview_time_label.value = (
                f"{format_timestamp(position)} / {format_timestamp(total)}"
            )
            controls.append(self.preview_time_label)
        if self.page_index == 0:
            self.page.update(*controls)

    def _pause_preview_for_drag(self) -> None:
        self.resume_preview_after_drag = self.preview_playing or self.resume_preview_after_drag
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_revision += 1
        self.preview_render_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        if self.page_index == 0:
            self.page.update(self.preview_play_button)

    def _trim_drag_start(self, _) -> None:
        if self.trim_slider.disabled or not self._can_edit_task(self.active_task_id):
            return
        self.trim_dragging = True
        self._pause_preview_for_drag()

    def _trim_drag_changed(self, _) -> None:
        if self.trim_label_task is None or self.trim_label_task.done():
            self.trim_label_task = asyncio.create_task(self._flush_trim_label())

    async def _flush_trim_label(self) -> None:
        await asyncio.sleep(TIMELINE_LABEL_INTERVAL)
        self._update_trim_label()

    def _update_trim_label(self) -> None:
        start = float(self.trim_slider.start_value)
        end = float(self.trim_slider.end_value)
        self.trim_label.value = (
            f"起点 {format_timestamp(start)}    "
            f"终点 {format_timestamp(end)}    "
            f"选中 {format_timestamp(max(0.0, end - start))}"
        )
        if self.page_index == 0:
            self.page.update(self.trim_label)

    def _preview_drag_start(self, _) -> None:
        self.preview_timeline_dragging = True
        self._pause_preview_for_drag()

    def _preview_drag_changed(self, _) -> None:
        if self.preview_time_task is None or self.preview_time_task.done():
            self.preview_time_task = asyncio.create_task(self._flush_preview_time_label())

    async def _flush_preview_time_label(self) -> None:
        await asyncio.sleep(TIMELINE_LABEL_INTERVAL)
        total = self.source_info.duration_seconds if self.source_info is not None else None
        self.preview_time_label.value = (
            f"{format_timestamp(float(self.preview_timeline.value))} / "
            f"{format_timestamp(total)}"
        )
        if self.page_index == 0:
            self.page.update(self.preview_time_label)

    async def _preview_seek(self, event) -> None:
        if not self.source_field.value:
            return
        self.preview_revision += 1
        revision = self.preview_revision
        render_revision = self.preview_render_revision
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_time_label.value = (
            f"{format_timestamp(float(event.control.value))} / "
            f"{format_timestamp(self.source_info.duration_seconds if self.source_info else None)}"
        )
        if self.page_index == 0:
            self.page.update(self.preview_time_label)
        seek_hint = asyncio.create_task(self._show_seek_hint_after(revision))
        try:
            options = self._options(require_output=False)
            first = timeline_frame_at_or_after(options.trim_start_seconds, options.fps) + options.skip_frames
            end = options.trim_end_seconds or float(self.preview_timeline.max)
            last = max(first, timeline_frame_at_or_after(end, options.fps) - 1)
            selected = timeline_frame_at_or_after(float(event.control.value), options.fps)
            position = min(last, max(first, selected)) / options.fps
            seek_options = replace(options, trim_start_seconds=position, skip_frames=0)
            async with self.preview_lock:
                if revision != self.preview_revision:
                    return
                info = await self._source_info_for_options(seek_options)
                if revision != self.preview_revision:
                    return
                await asyncio.to_thread(self.preview.reset, seek_options, info)
                if revision != self.preview_revision:
                    return
                frame = await asyncio.to_thread(self.preview.next_frame)
                original, data, index = await self._reconcile_preview_frame(
                    frame, revision, render_revision
                )
            if revision != self.preview_revision:
                return
            self.preview_timeline_dragging = False
            self._set_preview_frame(
                original,
                data,
                f"{position:.2f} 秒 · 第 {index} 帧",
                index=index,
            )
        except Exception as exc:
            if revision == self.preview_revision:
                self._show_error("无法跳转预览", exc)
        finally:
            seek_hint.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await seek_hint
            if revision == self.preview_revision:
                self.preview_timeline_dragging = False
                if self.resume_preview_after_drag:
                    self.resume_preview_after_drag = False
                    await self._toggle_preview_playback(None)

    async def _show_seek_hint_after(self, revision: int) -> None:
        await asyncio.sleep(0.15)
        if revision == self.preview_revision:
            self.preview_label.value = "正在定位…"
            if self.page_index == 0:
                self.page.update(self.preview_label)

    async def _toggle_preview_playback(self, _):
        if self.preview_playing:
            self.preview_playing = False
            self.preview_playback_revision += 1
            self.preview_play_button.icon = ft.Icons.PLAY_ARROW
            if self.page_index == 0:
                self.page.update(self.preview_play_button)
            return
        if not self.source_field.value:
            self._show_error("无法播放预览", ValueError("请先选择输入素材"))
            return
        try:
            fps = parse_preview_fps(self.fps_field.value)
        except ValueError as exc:
            self._show_error("无法播放预览", exc)
            return
        self.preview_playback_revision += 1
        playback_revision = self.preview_playback_revision
        self.preview_playing = True
        self.preview_play_button.icon = ft.Icons.STOP
        if self.page_index == 0:
            self.page.update(self.preview_play_button)
        loop = asyncio.get_running_loop()
        interval = 1.0 / fps
        deadline = loop.time()
        try:
            while self.preview_playing and playback_revision == self.preview_playback_revision:
                if not await self._preview_next():
                    break
                delay, deadline = advance_preview_deadline(deadline, loop.time(), interval)
                if delay > 0:
                    await asyncio.sleep(delay)
        finally:
            if playback_revision == self.preview_playback_revision:
                self.preview_playing = False
                self.preview_play_button.icon = ft.Icons.PLAY_ARROW
                if self.page_index == 0:
                    self.page.update(self.preview_play_button)

    async def _start_conversion(self, _):
        if self.busy:
            return
        if not self._save_editor_before_action():
            return
        try:
            jobs = self.queue.freeze_selected()
        except (OSError, ValueError) as exc:
            self._show_error("无法准备输出文件", exc)
            return
        if not jobs:
            self._show_error("无法开始转换", ValueError("请先添加并勾选至少一个任务"))
            return
        active_job = next(
            (job for job in jobs if job.id == self.active_task_id),
            None,
        )
        if active_job is not None:
            self.output_field.value = str(active_job.options.output)
            self._set_editor_locked(True)
            self.page.update(self.output_field)
        self.busy = True
        self.current_batch_ids = tuple(job.id for job in jobs)
        self.stop_batch_requested = False
        self.batch_current_name = ""
        self.conversion_revision += 1
        revision = self.conversion_revision
        self.latest_conversion_progress = None
        self.progress_display_ratio = 0.0
        self.progress_finish_deadline = None
        self.progress_finish_event = asyncio.Event()
        self.queue_cancel_event.clear()
        self.convert_button.disabled = True
        self.cancel_button.visible = True
        self.cancel_button.disabled = False
        self.progress_bar.visible = True
        self.progress_bar.value = 0
        self.progress_text.value = f"正在准备 {len(jobs)} 个任务…"
        self.page.update()
        self.progress_render_task = asyncio.create_task(
            self._render_conversion_progress(revision, self.progress_finish_event)
        )
        completed = 0
        processed = 0
        last_output: Path | None = None
        try:
            for job in jobs:
                if self.stop_batch_requested:
                    break
                self.active_queue_job_id = job.id
                self.batch_current_name = job.options.source.name
                self.latest_conversion_progress = (
                    revision,
                    BatchDisplayProgress(self.batch_current_name, processed, len(jobs)),
                )
                self.queue_cancel_event.clear()
                self.queue.update(job.id, state="running", error="")
                self._refresh_queue_view()
                self.logger.event("convert", f"start {job.options.source} -> {job.options.output}")
                try:
                    job.options.validate()
                    info = await asyncio.to_thread(probe_source, job.options)
                    report = await asyncio.to_thread(
                        check_compatibility,
                        job.options,
                        info,
                        job.target_profile,
                    )
                    errors = [
                        issue.message for issue in report.issues if issue.severity == "error"
                    ]
                    if errors:
                        raise ValueError("；".join(errors))
                    if job.options.source.suffix.lower() in VIDEO_SUFFIXES:
                        self.logger.event("ffmpeg", ffmpeg_version())

                    def progress(
                        value: ConversionProgress, *, current_job=job, processed_before=processed,
                    ) -> None:
                        if (
                            revision != self.conversion_revision
                            or self.stop_batch_requested
                            or self.active_queue_job_id != current_job.id
                        ):
                            return
                        self.queue.update(current_job.id, progress=value)
                        self.latest_conversion_progress = (
                            revision,
                            BatchDisplayProgress(
                                current_job.options.source.name, processed_before, len(jobs), value,
                            ),
                        )

                    worker = asyncio.create_task(
                        asyncio.to_thread(
                            convert_media,
                            job.options,
                            progress=progress,
                            cancelled=self.queue_cancel_event.is_set,
                            source_info=info,
                        )
                    )
                    while not worker.done():
                        self._refresh_queue_view()
                        await asyncio.sleep(0.1)
                    summary = await worker
                    self.queue.complete(job.id, summary)
                    completed += 1
                    last_output = summary.path
                    self.logger.event("convert", f"completed {summary.path}")
                except ConversionCancelled:
                    self.queue.update(job.id, state="cancelled")
                    self.logger.event("convert", f"cancelled {job.options.source}")
                    if self.stop_batch_requested:
                        break
                except Exception as exc:
                    self.queue.update(job.id, state="failed", error=str(exc))
                    self.logger.event("convert", f"failed {job.options.source}: {exc}", level=40)
                finally:
                    processed += 1
                    self.queue.unfreeze(job.id)
                    self.active_queue_job_id = None
                    self._refresh_queue_view()

            if not self.stop_batch_requested:
                loop = asyncio.get_running_loop()
                self.latest_conversion_progress = (
                    revision,
                    BatchDisplayProgress("", processed, len(jobs)),
                )
                self.progress_finish_deadline = loop.time() + PROGRESS_FINISH_SECONDS
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self.progress_finish_event.wait(),
                        timeout=PROGRESS_FINISH_SECONDS + 0.1,
                    )
                self.progress_bar.value = 1
                result_text = batch_result_text(completed, len(jobs))
                self.progress_text.value = result_text
                if last_output is not None:
                    self._open_player_path(last_output, show_page=False)
                self._show_notice(result_text)
            else:
                self.progress_text.value = "本轮已停止，未开始的任务仍在等待"
        finally:
            for job in jobs:
                if job.frozen:
                    self.queue.unfreeze(job.id)
            self.busy = False
            self.current_batch_ids = ()
            self.active_queue_job_id = None
            self.convert_button.disabled = False
            self.cancel_button.visible = False
            if self.active_task_id:
                with contextlib.suppress(KeyError):
                    active = self.queue.find(self.active_task_id)
                    self._set_editor_locked(active.frozen or active.state == "running")
            await self._stop_progress_renderer()
            self._refresh_queue_view()
            self.page.update()
            if self.exit_after_conversion_stop:
                await self._shutdown_and_exit()

    async def _render_conversion_progress(
        self,
        revision: int,
        finish_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_running_loop()
        last_time = loop.time()
        last_text = None
        try:
            while self.busy and revision == self.conversion_revision:
                if getattr(self, "stop_batch_requested", False):
                    await asyncio.sleep(PROGRESS_FRAME_INTERVAL)
                    continue
                now = loop.time()
                elapsed = max(0.0, now - last_time)
                last_time = now
                current = self.latest_conversion_progress
                if current is not None and current[0] == revision:
                    value = current[1]
                    target = value.ratio
                    previous_bar_value = self.progress_bar.value
                    if target is None:
                        self.progress_bar.value = None
                    elif self.progress_finish_deadline is not None:
                        remaining = self.progress_finish_deadline - now
                        if remaining <= 0:
                            self.progress_display_ratio = 1.0
                        else:
                            fraction = min(1.0, elapsed / max(remaining, PROGRESS_FRAME_INTERVAL))
                            self.progress_display_ratio += (
                                1.0 - self.progress_display_ratio
                            ) * fraction
                        self.progress_bar.value = self.progress_display_ratio
                    else:
                        self.progress_display_ratio = smooth_progress_value(
                            self.progress_display_ratio,
                            target,
                            elapsed,
                        )
                        self.progress_bar.value = self.progress_display_ratio

                    text = value.text()
                    text_changed = text != last_text
                    if text_changed:
                        self.progress_text.value = text
                        last_text = text
                    if self.page_index == 0 and (
                        self.progress_bar.value != previous_bar_value or text_changed
                    ):
                        self.page.update(self.progress_bar, self.progress_text)

                    if (
                        self.progress_finish_deadline is not None
                        and self.progress_display_ratio >= 0.9995
                    ):
                        self.progress_display_ratio = 1.0
                        self.progress_bar.value = 1.0
                        if self.page_index == 0:
                            self.page.update(self.progress_bar, self.progress_text)
                        finish_event.set()
                await asyncio.sleep(PROGRESS_FRAME_INTERVAL)
        except asyncio.CancelledError:
            raise

    async def _stop_progress_renderer(self) -> None:
        task = self.progress_render_task
        self.progress_render_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _cancel_conversion(self, _):
        self.stop_batch_requested = True
        self.queue_cancel_event.set()
        self.cancel_button.disabled = True
        self.task_action_status.value = "正在停止本轮…"
        self.progress_text.value = "正在停止本轮…"
        if self.page_index == 0:
            self.page.update(self.progress_text, self.task_action_status, self.cancel_button)

    def _configure_trim_timeline(self, info) -> None:
        self.trim_error.value = ""
        self.trim_error.visible = False
        if info.kind == "image" or not info.duration_seconds:
            self.trim_controls.visible = False
            self.pending_trim_range = None
            self.preview_timeline.visible = False
            self.trim_slider.disabled = True
            self.trim_label.value = "单张图片无需裁剪"
            self.preview_time_label.value = "00:00.00 / 00:00.00"
            if self.page_index == 0:
                self.page.update(self.preview_timeline, self.preview_time_label, self.trim_controls)
            return
        duration = max(1 / max(1, int(self.fps_field.value)), info.duration_seconds)
        self.preview_timeline.visible = True
        self.trim_controls.visible = True
        self.preview_timeline.min = 0
        self.preview_timeline.max = duration
        self.preview_timeline.value = 0
        self.trim_slider.disabled = False
        self.trim_slider.min = 0
        self.trim_slider.max = duration
        requested = self.pending_trim_range
        self.pending_trim_range = None
        if requested is None:
            start, end = 0.0, duration
        else:
            start = min(duration, max(0.0, requested[0]))
            end = duration if requested[1] is None else min(duration, max(start, requested[1]))
        self.trim_slider.start_value = start
        self.trim_slider.end_value = end
        self.preview_time_label.value = f"00:00.00 / {format_timestamp(duration)}"
        self._update_trim_label()
        if self.page_index == 0:
            self.page.update(self.preview_timeline, self.preview_time_label, self.trim_controls)

    def _restore_trim_range(self) -> None:
        try:
            options = self.queue.find(self.active_task_id).options
        except KeyError:
            return
        self.trim_slider.start_value = options.trim_start_seconds
        self.trim_slider.end_value = options.trim_end_seconds or self.trim_slider.max
        self._update_trim_label()
        if self.page_index == 0:
            self.page.update(self.trim_slider)

    def _validate_trim_range(self, start: float, end: float) -> None:
        if not math.isfinite(start) or not 0 <= start < self.trim_slider.max:
            raise ValueError("起点须在素材时长内")
        if not math.isfinite(end) or not start < end <= self.trim_slider.max:
            raise ValueError("终点须晚于起点，且不能超过素材时长")
        fps = parse_preview_fps(self.fps_field.value)
        first = timeline_frame_at_or_after(start, fps) + int(self.skip_frames_field.value)
        last = timeline_frame_at_or_after(end, fps)
        if self.source_info.frame_count is not None:
            last = min(last, self.source_info.frame_count)
        if first >= last:
            raise ValueError("此范围按当前 FPS 和跳帧设置没有画面，请扩大范围")

    async def _apply_trim_range(self, start: float, end: float) -> bool:
        if self.trim_slider.disabled or not self._can_edit_task(self.active_task_id):
            return False
        try:
            self._validate_trim_range(start, end)
            if not self._validate_editor_numbers():
                raise ValueError("请先修正转换参数中的数字")
        except (ValueError, TypeError) as exc:
            self.trim_error.value = str(exc)
            self.trim_error.visible = True
            if self.page_index == 0:
                self.page.update(self.trim_error)
            return False
        self.trim_slider.start_value, self.trim_slider.end_value = start, end
        if not self._save_active_task_options():
            self._restore_trim_range()
            self.trim_error.value = "无法保存范围，请检查当前任务和输出位置"
            self.trim_error.visible = True
            if self.page_index == 0:
                self.page.update(self.trim_error)
            return False
        self.trim_error.value = ""
        self.trim_error.visible = False
        self._update_trim_label()
        if self.page_index == 0:
            self.page.update(self.trim_controls)
        self._refresh_queue_view()
        self._pause_preview_for_drag()
        revision = self.preview_revision
        try:
            await self._load_first_preview()
        finally:
            if revision == self.preview_revision:
                await self._finish_trim_edit()
        return True

    async def _finish_trim_edit(self) -> None:
        self.trim_dragging = False
        if self.resume_preview_after_drag:
            self.resume_preview_after_drag = False
            await self._toggle_preview_playback(None)

    async def _on_trim_change(self, _):
        start, end = float(self.trim_slider.start_value), float(self.trim_slider.end_value)
        if not await self._apply_trim_range(start, end):
            self._restore_trim_range()
            await self._finish_trim_edit()

    def _edit_trim_dialog(self, _) -> None:
        if self.trim_slider.disabled or not self._can_edit_task(self.active_task_id):
            return
        context = (self.active_task_id, self.preview_revision)
        original = (float(self.trim_slider.start_value), float(self.trim_slider.end_value))
        labels = tuple(format_timestamp(value) for value in original)
        start_field = ft.TextField(label="起点（包含）", value=labels[0], autofocus=True)
        end_field = ft.TextField(label="终点（不包含）", value=labels[1])
        range_error = ft.Text("", color=ft.Colors.ERROR, visible=False)
        closed = False

        def dismiss(_=None):
            nonlocal closed
            closed = True

        def close(_=None):
            if not closed:
                dismiss()
                self.page.pop_dialog()

        async def apply(_):
            if closed:
                return
            if context != (self.active_task_id, self.preview_revision) or not self._can_edit_task(context[0]):
                close()
                self._show_notice("任务或预览已变化，请重新打开裁剪设置。")
                return
            values = []
            for field, label, exact in zip((start_field, end_field), labels, original):
                try:
                    values.append(exact if field.value == label else parse_timestamp(field.value or ""))
                    field.error = None
                except ValueError as exc:
                    field.error = str(exc)
            range_error.visible = False
            if len(values) != 2:
                self.page.update(start_field, end_field, range_error)
                return
            try:
                self._validate_trim_range(*values)
                if not self._validate_editor_numbers():
                    raise ValueError("请先修正转换参数中的数字")
            except (ValueError, TypeError) as exc:
                range_error.value, range_error.visible = str(exc), True
                self.page.update(start_field, end_field, range_error)
                return
            close()
            if values != list(original):
                await self._apply_trim_range(*values)

        start_field.on_submit = end_field.on_submit = apply
        self._show_dialog(ft.AlertDialog(
            modal=True,
            on_dismiss=dismiss,
            scrollable=True,
            title=ft.Text("精确裁剪"),
            content=ft.Column([
                ft.Text(f"素材总时长 {format_timestamp(self.trim_slider.max)}"),
                start_field,
                end_field,
                ft.Text("支持秒数或分:秒，例如 2.5、00:02.50。起点包含，终点不包含。",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                range_error,
            ], tight=True, spacing=12),
            actions=[
                ft.TextButton("取消", on_click=close),
                ft.FilledButton("应用范围", on_click=apply),
            ],
        ))

    async def _trim_at_playhead(self, event) -> None:
        if self.trim_slider.disabled or not self._can_edit_task(self.active_task_id):
            return
        start, end = float(self.trim_slider.start_value), float(self.trim_slider.end_value)
        action = event.control.data
        if action == "reset":
            start, end = 0.0, float(self.trim_slider.max)
        elif not self.preview_timeline_dragging:
            position = float(self.preview_timeline.value)
            if action == "start":
                start = position
            elif action == "end":
                if not self._validate_editor_numbers():
                    self._show_notice("请先修正转换参数中的数字")
                    return
                fps = int(self.fps_field.value)
                end = min(float(self.trim_slider.max), position + 1 / fps)
            else:
                return
        else:
            return
        if (start, end) != (self.trim_slider.start_value, self.trim_slider.end_value):
            await self._apply_trim_range(start, end)

    async def _auto_threshold_clicked(self, event) -> None:
        await self._auto_threshold(str(event.control.data))

    async def _auto_threshold(self, mode: str) -> None:
        context = (self.active_task_id, self.preview_revision, self.preview_render_revision)
        try:
            async with self.preview_lock:
                if not self._threshold_context_is_current(context):
                    return
                gray = self.preview.current_grayscale().copy()
            value = await asyncio.to_thread(suggested_threshold, gray, mode)
            if not self._threshold_context_is_current(context):
                return
            self._show_dialog(
                ft.AlertDialog(
                    title="自动阈值建议",
                    content=ft.Text(f"根据当前预览帧计算出的建议阈值为 {value}。是否应用？"),
                    actions=[
                        ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                        ft.FilledButton(
                            "应用",
                            on_click=lambda _: self._apply_threshold_suggestion(value, context),
                        ),
                    ],
                )
            )
        except Exception as exc:
            if self._threshold_context_is_current(context):
                self._show_error("无法分析自动阈值", exc)

    def _threshold_context_is_current(self, context: tuple[str | None, int, int]) -> bool:
        if context != (self.active_task_id, self.preview_revision, self.preview_render_revision):
            return False
        try:
            job = self.queue.find(context[0])
        except KeyError:
            return False
        return not job.frozen and job.state != "running"

    def _apply_threshold_suggestion(
        self, value: int, context: tuple[str | None, int, int]
    ) -> None:
        self.page.pop_dialog()
        if not self._threshold_context_is_current(context):
            self._show_notice("任务或预览已变化，请重新分析阈值。")
            return
        self.dither_control.selected = ["threshold"]
        self._set_threshold_value(value)
        self._set_threshold_enabled()
        if self.page_index == 0:
            self.page.update(self.dither_control, self.threshold_slider, self.threshold_field)
        if self._save_active_task_options():
            self._refresh_queue_view()
        asyncio.create_task(self._rerender_current_preview())

    def _refresh_preset_options(self) -> None:
        if not hasattr(self, "preset_dropdown"):
            return
        presets = self.preset_store.all_presets()
        self.preset_dropdown.options = [
            ft.DropdownOption(key=preset.name, text=preset.name) for preset in presets
        ]
        if not any(preset.name == self.preset_dropdown.value for preset in presets):
            self.preset_dropdown.value = None

    def _sync_preset_selection(self) -> bool:
        try:
            current = ConversionPreset.from_options(
                "", self._options_for_source(Path(), Path("preview.bin"), use_current_trim=False),
                self.target_dropdown.value,
            )
        except (TypeError, ValueError):
            changed = self.preset_dropdown.value is not None
            self.preset_dropdown.value = None
            return changed
        matches = [
            preset.name for preset in self.preset_store.all_presets()
            if replace(preset, name="", builtin=False) == current
        ]
        selected = self.preset_dropdown.value
        if selected in matches:
            return False
        self.preset_dropdown.value = matches[0] if matches else None
        return selected != self.preset_dropdown.value

    def _apply_selected_preset(self, _):
        if self.active_task_id is not None and not self._can_edit_task(self.active_task_id):
            self._show_notice("本轮任务的参数已锁定，停止转换后才能应用预设。")
            return
        preset = next(
            (item for item in self.preset_store.all_presets() if item.name == self.preset_dropdown.value),
            None,
        )
        if preset is None:
            return
        self.width_field.value = str(preset.width)
        self.height_field.value = str(preset.height)
        self.fps_field.value = str(preset.fps)
        self.fit_dropdown.value = preset.fit
        self.dither_control.selected = [preset.dither]
        self._set_threshold_value(preset.threshold)
        self._set_threshold_enabled()
        self.invert_switch.value = preset.invert
        self.background_dropdown.value = preset.background
        self.recursive_switch.value = preset.recursive
        self.target_dropdown.value = preset.target_profile
        self.task_worker_dropdown.value = str(preset.workers)
        self.task_fast_video_switch.value = preset.fast_video
        self._update_screen_size_hint(refresh=False)
        self.page.update()
        if self._save_active_task_options():
            self._refresh_queue_view()
        if self.source_field.value:
            asyncio.create_task(self._on_geometry_change(None))

    def _save_preset_dialog(self, _):
        if not self._validate_editor_numbers():
            return
        self.pending_preset_options = self._options_for_source(
            Path(), Path("preview.bin"), use_current_trim=False
        )
        self.pending_preset_target = self.target_dropdown.value
        self.preset_name_field.value = ""
        self._show_dialog(
            ft.AlertDialog(
                title="保存转换预设",
                modal=True,
                content=self.preset_name_field,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.FilledButton("保存", on_click=self._confirm_save_preset),
                ],
            )
        )

    def _confirm_save_preset(self, _):
        try:
            preset = ConversionPreset.from_options(
                self.preset_name_field.value.strip(),
                self.pending_preset_options,
                self.pending_preset_target,
            )
            preset.validate()
            existing = next(
                (item for item in self.preset_store.all_presets()
                 if item.name.casefold() == preset.name.casefold()), None,
            )
            if existing is not None and existing.builtin:
                raise ValueError("内置预设不能被覆盖，请换一个名称。")
            if existing is not None:
                self.page.pop_dialog()
                self._confirm_preset_action(
                    "覆盖已有预设？",
                    f"将替换“{existing.name}”的参数，已有转换任务保持不变。",
                    "覆盖", lambda: self._store_preset(preset),
                )
            else:
                self.page.pop_dialog()
                self._store_preset(preset)
        except Exception as exc:
            self._show_error("无法保存预设", exc)

    def _store_preset(self, preset: ConversionPreset) -> None:
        try:
            self.preset_store.upsert(preset)
            self._refresh_preset_options()
            self.preset_dropdown.value = preset.name
            self._sync_preset_selection()
            self.page.update(self.preset_dropdown)
            self._show_notice(f"已保存预设：{preset.name}")
        except (OSError, ValueError) as exc:
            self._show_error("无法保存预设", exc)

    def _confirm_preset_action(self, title: str, message: str, action: str, callback) -> None:
        def confirm(_):
            self.page.pop_dialog()
            try:
                callback()
            except (OSError, ValueError) as exc:
                self._show_error("无法修改预设", exc)
        self._show_dialog(ft.AlertDialog(
            title=title,
            modal=True,
            content=ft.Text(message),
            actions=[
                ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(action, on_click=confirm),
            ],
        ))

    def _delete_selected_preset(self, _):
        preset = next(
            (item for item in self.preset_store.all_presets() if item.name == self.preset_dropdown.value),
            None,
        )
        if preset is None:
            return
        if preset.builtin:
            self._show_error("无法删除预设", ValueError("内置预设不能删除"))
            return
        self._confirm_preset_action(
            "删除这个预设？", f"删除“{preset.name}”，不会修改已有任务或素材。",
            "删除", lambda: self._delete_preset(preset.name),
        )

    def _delete_preset(self, name: str) -> None:
        self.preset_store.delete(name)
        self._refresh_preset_options()
        self._sync_preset_selection()
        self.page.update(self.preset_dropdown)

    def _reset_user_presets(self, _):
        self._confirm_preset_action(
            "清空自定义预设？",
            "会删除自己创建的全部预设，内置预设保留。当前画面参数和转换任务不会改变。",
            "清空", self._clear_user_presets,
        )

    def _clear_user_presets(self) -> None:
        self.preset_store.reset()
        self._refresh_preset_options()
        self._sync_preset_selection()
        self.page.update(self.preset_dropdown)
        self._show_notice("已清空自定义预设，当前参数保持不变。")

    def _set_threshold_value(self, value: int) -> None:
        self.threshold_slider.value = value
        self.threshold_field.value = str(value)
        self.threshold_field.error = None

    def _set_threshold_enabled(self, *, locked: bool = False) -> None:
        disabled = locked or self.dither_control.selected[0] != "threshold"
        self.threshold_slider.disabled = disabled
        self.threshold_field.disabled = disabled

    def _monochrome_edit_allowed(self) -> bool:
        if self.active_task_id is None or self._can_edit_task(self.active_task_id):
            return True
        try:
            job = self.queue.find(self.active_task_id)
        except KeyError:
            return False
        self.dither_control.selected = [job.options.dither]
        self.invert_switch.value = job.options.invert
        self._set_threshold_value(job.options.threshold)
        self._set_threshold_enabled(locked=True)
        if self.page_index == 0:
            self.page.update(
                self.dither_control, self.threshold_slider, self.threshold_field, self.invert_switch
            )
        return False

    async def _on_dither_change(self, _):
        if not self._monochrome_edit_allowed():
            return
        self._set_threshold_value(round(float(self.threshold_slider.value)))
        self._set_threshold_enabled()
        if self.page_index == 0:
            self.page.update(self.dither_control, self.threshold_slider, self.threshold_field)
        if self._save_active_task_options():
            self._refresh_queue_view()
        await self._rerender_current_preview()

    async def _on_threshold_input_change(self, _):
        if not self._monochrome_edit_allowed():
            return
        if self.dither_control.selected[0] != "threshold":
            self._set_threshold_value(round(float(self.threshold_slider.value)))
            if self.page_index == 0:
                self.page.update(self.threshold_field)
            return
        try:
            value = int(self.threshold_field.value)
            error = None if 0 <= value <= 255 else "请输入 0–255"
        except (TypeError, ValueError):
            error = "请输入整数"
        self.threshold_field.error = error
        if error is not None:
            if self.page_index == 0:
                self.page.update(self.threshold_field)
            return
        self.threshold_slider.value = value
        await self._on_threshold_change(None)

    async def _on_threshold_change(self, _):
        if not self._monochrome_edit_allowed():
            return
        if self.dither_control.selected[0] != "threshold":
            self._set_threshold_value(int(self.threshold_field.value))
            if self.page_index == 0:
                self.page.update(self.threshold_slider)
            return
        self._set_threshold_value(round(float(self.threshold_slider.value)))
        if self.page_index == 0:
            self.page.update(self.threshold_slider, self.threshold_field)
        if self._save_active_task_options():
            self._refresh_queue_view()
        await self._rerender_current_preview(debounce=True)

    async def _on_invert_change(self, _):
        if not self._monochrome_edit_allowed():
            return
        if self._save_active_task_options():
            self._refresh_queue_view()
        await self._rerender_current_preview()

    async def _on_geometry_change(self, _):
        """Reload the preview when an option changes frame geometry or timing."""
        if not self._size_edit_allowed():
            return
        self._update_screen_size_hint()
        if not self.source_field.value:
            return
        if not self._validate_editor_numbers():
            return
        self.preview_revision += 1
        revision = self.preview_revision
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        await asyncio.sleep(0.12)
        if revision != self.preview_revision:
            return
        if not self._size_edit_allowed():
            return
        try:
            options = self._options(require_output=False)
            options.validate()
        except (OSError, ValueError):
            # A number field may be temporarily empty while the user is typing.
            return
        if self._save_active_task_options():
            self._refresh_queue_view()
        await self._load_first_preview()

    async def _rerender_current_preview(self, *, debounce: bool = False) -> None:
        if not self.source_field.value:
            return
        self.preview_render_revision += 1
        if self.preview.index < 0:
            return
        render_revision = self.preview_render_revision
        source_revision = self.preview_revision
        if debounce:
            await asyncio.sleep(0.03)
        if (
            render_revision != self.preview_render_revision
            or source_revision != self.preview_revision
        ):
            return
        try:
            dither = self.dither_control.selected[0]
            threshold = round(float(self.threshold_slider.value))
            async with self.preview_lock:
                if (
                    render_revision != self.preview_render_revision
                    or source_revision != self.preview_revision
                ):
                    return
                original, data, index = await asyncio.to_thread(
                    self.preview.rerender_current,
                    dither,
                    threshold,
                    bool(self.invert_switch.value),
                )
            if (
                render_revision != self.preview_render_revision
                or source_revision != self.preview_revision
            ):
                return
            self._set_preview_frame(original, data, f"第 {index} 帧", index=index)
        except ValueError:
            return
        except Exception as exc:
            if source_revision == self.preview_revision:
                self._show_error("无法刷新预览", exc)

    def _save_settings(self, _):
        try:
            width = int(self.default_width.value)
            height = int(self.default_height.value)
            fps = int(self.default_fps.value)
            if not (1 <= width <= 255 and 1 <= height <= 255 and 1 <= fps <= 120):
                raise ValueError("宽高须在 1–255，FPS 须在 1–120")
            updated = AppSettings(
                width=width,
                height=height,
                fps=fps,
                output_directory=self.default_output.value,
                theme=self.theme_dropdown.value,
                workers=int(self.worker_dropdown.value),
                fast_video=bool(self.fast_video_switch.value),
                target_profile=self.default_target.value,
            )
            if not 0 <= updated.workers <= 8 or updated.target_profile not in TARGET_PROFILES:
                raise ValueError("请选择有效的线程数和目标屏幕")
            save_settings(updated)
            self.settings = updated
            if self.active_task_id is None:
                self._load_default_editor_options()
            self._apply_theme(self.settings.theme)
            self._show_notice("默认设置已保存，已有任务和预览保持不变。")
        except Exception as exc:
            self._show_error("无法保存设置", exc)

    def _cycle_theme(self, _):
        values = ["system", "light", "dark"]
        current = values.index(self.settings.theme) if self.settings.theme in values else 0
        self.settings.theme = values[(current + 1) % len(values)]
        self.theme_dropdown.value = self.settings.theme
        self._apply_theme(self.settings.theme)
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def _apply_theme(self, value: str, *, refresh: bool = True) -> None:
        value = normalize_theme_mode(value)
        self.settings.theme = value
        modes = {
            "system": ft.ThemeMode.SYSTEM,
            "light": ft.ThemeMode.LIGHT,
            "dark": ft.ThemeMode.DARK,
        }
        self.page.theme_mode = modes.get(value, ft.ThemeMode.SYSTEM)
        if self.page.appbar:
            icons = {"system": ft.Icons.BRIGHTNESS_AUTO, "light": ft.Icons.LIGHT_MODE, "dark": ft.Icons.DARK_MODE}
            self.page.appbar.actions[0].icon = icons.get(value, ft.Icons.BRIGHTNESS_AUTO)
        if refresh:
            self.page.update()

    async def _on_keyboard_event(self, event: ft.KeyboardEvent) -> None:
        dialogs = getattr(self, "dialog_host", None)
        if (
            self.exit_dialog_open
            or (dialogs is not None and dialogs.has_modal)
            or event.alt
            or event.meta
        ):
            return
        key = str(event.key).casefold()
        if event.ctrl and key == "o":
            if self.page_index == 0:
                await self._choose_file(None)
            elif self.page_index == 1:
                await self._choose_ovid_file(None)
        elif (
            event.ctrl
            and key in {"enter", "return", "numpad enter"}
            and self.page_index == 0
            and not self.convert_button.disabled
        ):
            await self._start_conversion(None)
        elif self.page_index == 1 and not event.ctrl:
            if key in {" ", "space", "spacebar"}:
                await self._toggle_player(None)
            elif key in {"arrow left", "left"}:
                await self._player_previous(None)
            elif key in {"arrow right", "right"}:
                await self._player_next(None)
            elif key == "home":
                await self._player_first(None)

    async def _on_window_event(self, event: ft.WindowEvent) -> None:
        event_type = getattr(event, "type", None)
        if isinstance(event_type, ft.WindowEventType):
            event_type = event_type.value
        if event_type != ft.WindowEventType.CLOSE.value:
            return
        if not self.busy:
            await self._shutdown_and_exit()
            return
        if self.exit_dialog_open:
            return
        dialog = ft.AlertDialog(
            title="转换仍在进行",
            icon=ft.Icon(ft.Icons.WARNING_AMBER),
            content=ft.Text("现在退出会取消当前任务。程序会先清理临时文件，再关闭窗口。"),
        )

        async def confirm(_):
            await self._confirm_exit(dialog)

        dialog.on_dismiss = lambda _: self._exit_dialog_dismissed(dialog)
        dialog.actions = [
            ft.TextButton("继续转换", on_click=lambda _: self._dismiss_exit_dialog(dialog)),
            ft.FilledButton("停止并退出", on_click=confirm),
        ]
        self._show_dialog(dialog)
        self.exit_dialog = dialog
        self.exit_dialog_open = True

    def _exit_dialog_dismissed(self, dialog: ft.AlertDialog) -> None:
        if self.exit_dialog is dialog:
            self.exit_dialog_open = False
            self.exit_dialog = None

    def _dismiss_exit_dialog(self, dialog: ft.AlertDialog) -> bool:
        if self.exit_dialog is not dialog or not self.exit_dialog_open:
            return False
        self._exit_dialog_dismissed(dialog)
        dialog.open = False
        self.page.update(dialog)
        return True

    async def _confirm_exit(self, dialog: ft.AlertDialog) -> None:
        if not self._dismiss_exit_dialog(dialog):
            return
        if not self.busy:
            await self._shutdown_and_exit()
            return
        self.exit_after_conversion_stop = True
        self._cancel_conversion(None)
        self.task_action_status.value = "正在停止任务并退出…"
        self.page.update(self.task_action_status)

    async def _shutdown_and_exit(self) -> None:
        self.exit_after_conversion_stop = False
        self.preview_playing = False
        self.player_playing = False
        self.preview_revision += 1
        self.preview_playback_revision += 1
        self.player_revision += 1
        for task in (
            self.trim_label_task,
            self.preview_time_task,
            self.player_time_task,
            self.progress_render_task,
            self.session_save_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        await self._close_preview_if_current(self.preview_revision)
        self.player.close()
        if hasattr(self, "session_store"):
            with contextlib.suppress(OSError):
                self.session_store.save(self.queue.snapshot(), self.active_task_id)
        self.logger.close()
        await self.page.window.destroy()

    def _show_page(self, index: int) -> None:
        pages = [
            self.convert_page,
            self.player_page,
            self.settings_page,
            self.about_page,
        ]
        if not 0 <= index < len(pages):
            index = 0
        self.page_index = index
        self.page_host.content = pages[index]
        self.navigation_rail.selected_index = index
        self.navigation_bar.selected_index = index
        self.page.update()
        if index == 0 and self.preview_needs_reload and not self.busy:
            self.preview_needs_reload = False
            asyncio.create_task(self._load_first_preview())

    def _on_resize(self, _=None) -> None:
        width = self.page.width or self.page.window.width or 1120
        height = self.page.height or self.page.window.height or 760
        compact = width < 800
        comparison_height, player_height = responsive_preview_heights(height)
        navigation_changed = compact != self.compact_layout
        resized_controls: list[ft.Control] = []
        if navigation_changed:
            self.compact_layout = compact
            self.navigation_rail.visible = not compact
            self.page.navigation_bar = self.navigation_bar if compact else None
        for control in (self.original_preview_image, self.preview_image):
            if control.height != comparison_height:
                control.height = comparison_height
                if self.page_index == 0 and control in self._visible_preview_images():
                    resized_controls.append(control)
        if self.player_image.height != player_height:
            self.player_image.height = player_height
            if self.page_index == 1:
                resized_controls.append(self.player_image)
        editor_changed = self._resize_editor_panels(width, height, compact)
        if editor_changed and self.page_index == 0:
            resized_controls = [self.editor_row]
        if navigation_changed:
            self.page.update()
        elif resized_controls:
            self.page.update(*resized_controls)

    def _resize_editor_panels(self, width: float, height: float, compact: bool) -> bool:
        content_width = width - 40 - (1 if compact else 89)
        split = content_width >= 960
        columns = 6 if split else 12
        changed = False
        for card in (self.preview_card, self.parameter_card):
            if card.col != columns or card.height is not None or card.content.content.scroll is not None:
                card.col = columns
                card.height = None
                card.content.content.scroll = None
                changed = True
        return changed

    def _show_dialog(self, dialog: ft.DialogControl) -> None:
        if not hasattr(self, "dialog_host"):
            self.dialog_host = DialogHost(self.page)
        self.dialog_host.show(dialog)

    def _show_error(self, title: str, error: Exception) -> None:
        ErrorDetailsDialog(
            self.page, self.clipboard, ErrorReport.from_exception(title, error),
        ).show(self._show_dialog)

    def _show_message(self, title: str, message: str) -> None:
        self._show_dialog(
            ft.AlertDialog(
                title=title,
                icon=ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE),
                content=ft.Text(message, selectable=True),
                actions=[ft.Button("确定", on_click=lambda _: self.page.pop_dialog())],
            )
        )

    def _show_notice(self, message: str) -> None:
        self._show_dialog(
            ft.SnackBar(
                content=ft.Text(message),
                show_close_icon=True,
                duration=4000,
            )
        )


async def before_main(page: ft.Page) -> None:
    """Keep the native window hidden until its first centered frame is ready."""
    page.window.visible = False
    page.window.width = 1120
    page.window.height = 760
    page.window.min_width = 680
    page.window.min_height = 600
    page.update()


async def main(page: ft.Page) -> None:
    ConverterApp(page)
    page.update()
    await page.window.wait_until_ready_to_show()
    await page.window.center()
    page.window.visible = True
    page.update()


if __name__ == "__main__":
    ft.run(
        main,
        before_main=before_main,
        name="OVID Converter",
        assets_dir=str(ASSETS_DIR),
    )
