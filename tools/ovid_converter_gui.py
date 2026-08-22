#!/usr/bin/env python3
"""Material 3 desktop interface for the OVID media converter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import flet as ft

try:
    from flet_drop_zone import FletDropZone
except ImportError:  # Local lightweight builds deliberately omit the Flutter extension.
    FletDropZone = None

from converter_version import DISPLAY_NAME, VERSION
from converter_services import (
    BUILTIN_PRESETS,
    TARGET_PROFILES,
    CompatibilityReport,
    ConversionLogger,
    ConversionPreset,
    ConversionQueue,
    PresetStore,
    QueueJob,
    check_compatibility,
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
    iter_source_images,
    prepare_monochrome_source,
    preview_prepared_png,
    probe_source,
)
from ovid_player import OvidPlaybackSession


REPOSITORY_URL = "https://github.com/akasa828/SD_Card_OVID_Player"
MAX_PREVIEW_CACHE = 180
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PRIMARY_FONT = "Google Sans Flex"
SIMPLIFIED_CHINESE_FONT = "Noto Sans SC"
NAVIGATION_ITEMS = (
    (ft.Icons.MOVIE, "转换"),
    (ft.Icons.QUEUE_PLAY_NEXT, "队列"),
    (ft.Icons.PLAY_CIRCLE, "播放器"),
    (ft.Icons.SETTINGS, "设置"),
    (ft.Icons.INFO, "关于"),
)
VALID_THEME_MODES = frozenset({"system", "light", "dark"})
PROGRESS_FRAME_INTERVAL = 0.016
PROGRESS_EASING_SECONDS = 0.12
PROGRESS_FINISH_SECONDS = 0.25
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


class PreviewFinished(RuntimeError):
    """The preview iterator reached the end of the selected media."""


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


def parse_drop_paths(value: object) -> list[Path]:
    """Decode desktop_drop event data without exposing JSON errors to the UI."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
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


def source_preview_png(image, max_size: tuple[int, int] = (512, 320)) -> bytes:
    """Encode a bounded source preview without changing the conversion frame."""
    from PIL import Image
    import io

    preview = image.convert("RGBA")
    preview.thumbnail(max_size, Image.Resampling.LANCZOS)
    background = Image.new("RGBA", preview.size, (24, 24, 24, 255))
    background.alpha_composite(preview)
    buffer = io.BytesIO()
    background.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


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


def settings_file() -> Path:
    root = os.getenv("FLET_APP_STORAGE_DATA")
    if not root:
        root = str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "OVID Converter")
    return Path(root) / "settings.json"


def load_settings() -> AppSettings:
    path = settings_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
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
        self.frames: list[tuple[bytes, object]] = []
        self.index = -1
        self.base_index = 0

    def close(self) -> None:
        if self.iterator is not None:
            close = getattr(self.iterator, "close", None)
            if close is not None:
                close()
        self.iterator = None

    def reset(self, options: ConversionOptions, info=None) -> None:
        self.close()
        self.options = options
        self.info = info
        self.iterator = iter_source_images(options, info)
        self.frames.clear()
        self.index = -1
        self.base_index = 0

    def _render(self, entry: tuple[bytes, object]) -> tuple[bytes, bytes]:
        original, prepared = entry
        return original, preview_prepared_png(prepared, self.options, scale=4)

    def next_frame(self) -> tuple[bytes, bytes, int]:
        if self.options is None or self.iterator is None:
            raise ValueError("请先选择输入素材")
        if self.index + 1 < len(self.frames):
            self.index += 1
            original, data = self._render(self.frames[self.index])
            return original, data, self.base_index + self.index + 1

        try:
            image = next(self.iterator)
        except StopIteration as exc:
            # StopIteration cannot cross an asyncio Future boundary. Convert it
            # before next_frame() returns to asyncio.to_thread().
            raise PreviewFinished("已到最后一帧") from exc
        prepared = prepare_monochrome_source(image, self.options)
        original = source_preview_png(image)
        data = preview_prepared_png(prepared, self.options, scale=4)
        self.frames.append((original, prepared))
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
        original, data = self._render(self.frames[self.index])
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
        original, data = self._render(self.frames[self.index])
        return original, data, self.base_index + self.index + 1

    def current_grayscale(self):
        if not self.frames or self.index < 0:
            raise ValueError("当前没有预览帧")
        return self.frames[self.index][1]


class ConverterApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings = load_settings()
        self.preset_store = PresetStore()
        self.queue = ConversionQueue()
        self.logger = ConversionLogger()
        self.player = OvidPlaybackSession()
        self.source_info = None
        self.queue_runner_task: asyncio.Task | None = None
        self.queue_cancel_event = threading.Event()
        self.active_queue_job_id: str | None = None
        self.cancel_event = threading.Event()
        self.preview = PreviewSession()
        self.preview_lock = asyncio.Lock()
        self.preview_revision = 0
        self.preview_playback_revision = 0
        self.preview_render_revision = 0
        self.preview_playing = False
        self.preview_needs_reload = False
        self.conversion_revision = 0
        self.latest_conversion_progress: tuple[int, ConversionProgress] | None = None
        self.progress_display_ratio = 0.0
        self.progress_finish_deadline: float | None = None
        self.progress_finish_event: asyncio.Event | None = None
        self.progress_render_task: asyncio.Task | None = None
        self.busy = False
        self.page_index = 0
        self.file_picker = ft.FilePicker()
        self.page.services.append(self.file_picker)

        self._build_controls()
        self._configure_page()
        self._show_page(0)

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
        self.page.dark_theme = ft.Theme(
            color_scheme_seed=ft.Colors.INDIGO,
            use_material3=True,
            font_family=PRIMARY_FONT,
            text_theme=_app_text_theme("#E6E1E5"),
        )
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
                    on_click=lambda _: self._show_page(4),
                ),
            ],
        )
        self._apply_theme(self.settings.theme, refresh=False)
        self.page.on_resize = self._on_resize
        self.page.add(self.shell)
        self._on_resize()

    def _build_controls(self) -> None:
        self.source_field = ft.TextField(label="输入素材", read_only=True, expand=True)
        self.output_field = ft.TextField(label="输出 OVID .BIN", read_only=True, expand=True)
        self.width_field = self._number_field(
            "宽度", self.settings.width, 1, 255, col=3, on_change=self._on_geometry_change
        )
        self.height_field = self._number_field(
            "高度", self.settings.height, 1, 255, col=3, on_change=self._on_geometry_change
        )
        self.fps_field = self._number_field(
            "FPS", self.settings.fps, 1, 120, col=3, on_change=self._on_geometry_change
        )
        self.skip_frames_field = self._number_field(
            "跳过开头帧", 0, 0, 999999, col=3, on_change=self._on_geometry_change
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
        )
        self.background_dropdown = ft.Dropdown(
            label="补边与透明背景",
            value="black",
            options=[
                ft.DropdownOption(key="black", text="黑色"),
                ft.DropdownOption(key="white", text="白色"),
            ],
            on_select=self._on_geometry_change,
        )
        self.invert_switch = ft.Switch(
            label="反转黑白", value=False, on_change=self._on_invert_change
        )
        self.recursive_switch = ft.Switch(
            label="递归读取图片子目录", value=False, on_change=self._on_geometry_change
        )
        self.force_switch = ft.Switch(label="允许覆盖已有输出", value=False)
        self.target_dropdown = ft.Dropdown(
            label="目标屏幕",
            value=self.settings.target_profile,
            options=[
                ft.DropdownOption(key=key, text=value[0])
                for key, value in TARGET_PROFILES.items()
            ],
        )
        self.preset_dropdown = ft.Dropdown(
            label="转换预设",
            value=BUILTIN_PRESETS[0].name,
            options=[],
            on_select=self._apply_selected_preset,
        )
        self.preset_name_field = ft.TextField(label="新预设名称", expand=True)
        self._refresh_preset_options()

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
            divisions=1,
            round=2,
            disabled=True,
            on_change_end=self._on_trim_change,
        )
        self.trim_label = ft.Text("单张图片无需裁剪", color=ft.Colors.ON_SURFACE_VARIANT)

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
        self.preview_label = ft.Text("尚未载入素材", color=ft.Colors.ON_SURFACE_VARIANT)
        self.preview_play_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            tooltip="播放预览",
            on_click=self._toggle_preview_playback,
        )

        self.progress_bar = ft.ProgressBar(value=0, visible=False)
        self.progress_text = ft.Text("准备就绪", color=ft.Colors.ON_SURFACE_VARIANT)
        self.convert_button = ft.FilledButton(
            "生成 OVID",
            icon=ft.Icons.MOVIE,
            on_click=self._start_conversion,
        )
        self.cancel_button = ft.OutlinedButton(
            "取消",
            icon=ft.Icons.CANCEL,
            on_click=self._cancel_conversion,
            visible=False,
        )

        self.queue_list = ft.Column(spacing=8)
        self.queue_status = ft.Text("队列为空", color=ft.Colors.ON_SURFACE_VARIANT)
        self.queue_run_button = ft.FilledButton(
            "开始队列", icon=ft.Icons.PLAY_ARROW, on_click=self._start_queue
        )
        self.queue_cancel_button = ft.OutlinedButton(
            "取消当前任务", icon=ft.Icons.CANCEL, on_click=self._cancel_queue_job
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
            divisions=1,
            disabled=True,
            on_change_end=self._player_seek,
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
        self.queue_page = self._build_queue_page()
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

    def _card(self, title: str, icon, controls, *, col=12) -> ft.Card:
        return ft.Card(
            variant=ft.CardVariant.FILLED,
            col=col,
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
                ft.OutlinedButton("选择文件", icon=ft.Icons.INSERT_DRIVE_FILE, on_click=self._choose_file),
                ft.OutlinedButton("选择图片目录", icon=ft.Icons.FOLDER_OPEN, on_click=self._choose_directory),
                ft.OutlinedButton("批量选择", icon=ft.Icons.PLAYLIST_ADD, on_click=self._choose_queue_files),
            ],
            wrap=True,
        )
        output_actions = ft.Row(
            [
                self.output_field,
                ft.IconButton(icon=ft.Icons.SAVE, tooltip="选择输出位置", on_click=self._choose_output),
            ]
        )
        input_card = self._card(
            "素材与输出",
            ft.Icons.INSERT_DRIVE_FILE,
            [
                *([self.drop_zone] if self.drop_zone is not None else []),
                self.source_field,
                source_actions,
                output_actions,
            ],
            col=12,
        )
        preview_card = self._card(
            "画面对比",
            ft.Icons.IMAGE,
            [
                ft.ResponsiveRow(
                    [
                        ft.Column(
                            [
                                ft.Text("原始素材", weight=ft.FontWeight.W_500),
                                ft.Container(
                                    content=self.original_preview_image,
                                    bgcolor=ft.Colors.BLACK,
                                    border_radius=16,
                                    padding=10,
                                    alignment=ft.Alignment.CENTER,
                                ),
                            ],
                            col={"xs": 12, "md": 6},
                        ),
                        ft.Column(
                            [
                                ft.Text("OLED 输出", weight=ft.FontWeight.W_500),
                                ft.Container(
                                    content=self.preview_image,
                                    bgcolor=ft.Colors.BLACK,
                                    border_radius=16,
                                    padding=10,
                                    alignment=ft.Alignment.CENTER,
                                ),
                            ],
                            col={"xs": 12, "md": 6},
                        ),
                    ],
                    spacing=12,
                    run_spacing=12,
                ),
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
                self.trim_slider,
                self.trim_label,
            ],
            col=12,
        )
        parameter_card = self._card(
            "转换参数",
            ft.Icons.TUNE,
            [
                ft.Row(
                    [
                        self.preset_dropdown,
                        ft.IconButton(
                            icon=ft.Icons.SAVE_AS,
                            tooltip="保存当前参数为预设",
                            on_click=self._save_preset_dialog,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="删除用户预设",
                            on_click=self._delete_selected_preset,
                        ),
                    ]
                ),
                ft.ResponsiveRow(
                    [
                        self.width_field,
                        self.height_field,
                        self.fps_field,
                        self.skip_frames_field,
                    ]
                ),
                self.fit_dropdown,
                self.dither_control,
                self.threshold_slider,
                ft.Row(
                    [
                        ft.Text("自动阈值"),
                        ft.OutlinedButton("标准", data="standard", on_click=self._auto_threshold_clicked),
                        ft.OutlinedButton("保留暗部", data="dark-detail", on_click=self._auto_threshold_clicked),
                        ft.OutlinedButton("减少噪点", data="noise-reduction", on_click=self._auto_threshold_clicked),
                    ],
                    wrap=True,
                ),
                self.background_dropdown,
                self.target_dropdown,
                ft.Row([self.invert_switch, self.recursive_switch], wrap=True),
                self.force_switch,
                ft.OutlinedButton("刷新预览", icon=ft.Icons.REFRESH, on_click=self._refresh_preview),
            ],
            col={"xs": 12, "lg": 5},
        )
        action_card = self._card(
            "转换进度",
            ft.Icons.DATA_SAVER_ON,
            [
                self.progress_bar,
                self.progress_text,
                ft.Row(
                    [
                        self.convert_button,
                        ft.OutlinedButton(
                            "加入队列", icon=ft.Icons.ADD_TO_QUEUE, on_click=self._add_current_to_queue
                        ),
                        self.cancel_button,
                    ],
                    wrap=True,
                ),
            ],
            col=12,
        )
        return ft.Column(
            [
                ft.Text("无需 IrfanView、Img2Lcd 或中间 .c/.h 文件。", color=ft.Colors.ON_SURFACE_VARIANT),
                ft.ResponsiveRow([input_card, preview_card, parameter_card, action_card], spacing=16, run_spacing=16),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_queue_page(self):
        return ft.Column(
            [
                ft.Text("批量转换队列", size=28, weight=ft.FontWeight.W_600),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "添加文件", icon=ft.Icons.PLAYLIST_ADD, on_click=self._choose_queue_files
                        ),
                        self.queue_run_button,
                        self.queue_cancel_button,
                        ft.TextButton("清理已完成", on_click=self._clear_completed_jobs),
                    ],
                    wrap=True,
                ),
                self.queue_status,
                self._card("任务", ft.Icons.QUEUE_PLAY_NEXT, [self.queue_list]),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_player_page(self):
        return ft.Column(
            [
                ft.Text("OVID 播放模拟器", size=28, weight=ft.FontWeight.W_600),
                ft.Row(
                    [
                        self.player_path,
                        ft.OutlinedButton(
                            "打开 .BIN", icon=ft.Icons.FOLDER_OPEN, on_click=self._choose_ovid_file
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
                        ft.IconButton(icon=ft.Icons.SKIP_PREVIOUS, on_click=self._player_first),
                        ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=self._player_previous),
                        self.player_play_button,
                        ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=self._player_next),
                        self.player_invert,
                        self.player_scale,
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
                self.player_label,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_settings_page(self):
        self.default_width = self._number_field("默认宽度", self.settings.width, 1, 255)
        self.default_height = self._number_field("默认高度", self.settings.height, 1, 255)
        self.default_fps = self._number_field("默认 FPS", self.settings.fps, 1, 120)
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
                        ft.ResponsiveRow([self.default_width, self.default_height, self.default_fps]),
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
        trim_enabled = use_current_trim and not self.trim_slider.disabled
        trim_start = float(self.trim_slider.start_value) if trim_enabled else 0.0
        trim_end = float(self.trim_slider.end_value) if trim_enabled else None
        return ConversionOptions(
            source=source,
            output=output,
            width=int(self.width_field.value),
            height=int(self.height_field.value),
            fps=int(self.fps_field.value),
            fit=self.fit_dropdown.value,
            dither=self.dither_control.selected[0],
            threshold=int(self.threshold_slider.value),
            invert=self.invert_switch.value,
            background=self.background_dropdown.value,
            recursive=self.recursive_switch.value,
            force=self.force_switch.value,
            skip_frames=int(self.skip_frames_field.value),
            trim_start_seconds=trim_start,
            trim_end_seconds=trim_end,
            workers=self.settings.workers,
            fast_video=self.settings.fast_video,
        )

    async def _choose_file(self, _):
        files = await self.file_picker.pick_files(
            dialog_title="选择图片、GIF 或视频",
            allowed_extensions=sorted({suffix[1:] for suffix in IMAGE_SUFFIXES | VIDEO_SUFFIXES}),
            allow_multiple=False,
        )
        if files and files[0].path:
            self._set_source(Path(files[0].path))
            await self._load_first_preview()

    async def _choose_queue_files(self, _):
        files = await self.file_picker.pick_files(
            dialog_title="选择要加入队列的图片、GIF 或视频",
            allowed_extensions=sorted({suffix[1:] for suffix in IMAGE_SUFFIXES | VIDEO_SUFFIXES}),
            allow_multiple=True,
        )
        if not files:
            return
        output_dir = (
            Path(self.settings.output_directory)
            if self.settings.output_directory
            else Path(files[0].path).parent
        )
        added = 0
        for item in files:
            if not item.path:
                continue
            source = Path(item.path)
            output = output_dir / f"{source.stem}.BIN"
            self.queue.add(
                self._options_for_source(source, output, use_current_trim=False),
                target_profile=self.target_dropdown.value,
            )
            added += 1
        self._refresh_queue_view()
        if added:
            self._show_page(1)

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

        if len(paths) == 1:
            path = paths[0]
            if path.suffix.lower() == ".bin":
                await self._open_player_path(path)
                return
            self._set_source(path)
            await self._load_first_preview()
            return

        sources = [path for path in paths if is_supported_source(path)]
        if not sources:
            self._show_notice("批量拖放仅支持图片、GIF、视频或图片目录")
            return
        output_dir = (
            Path(self.settings.output_directory)
            if self.settings.output_directory
            else sources[0].parent
        )
        for source in sources:
            output = output_dir / f"{source.stem}.BIN"
            self.queue.add(
                self._options_for_source(source, output, use_current_trim=False),
                target_profile=self.target_dropdown.value,
            )
        self._refresh_queue_view()
        self._show_page(1)
        self._show_notice(f"已将 {len(sources)} 个素材加入队列")

    def _add_current_to_queue(self, _):
        try:
            job = self.queue.add(
                self._options(),
                target_profile=self.target_dropdown.value,
            )
            self.logger.event("queue", f"added {job.options.source} -> {job.options.output}")
            self._refresh_queue_view()
            self._show_page(1)
        except Exception as exc:
            self._show_error("无法加入队列", exc)

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

    def _refresh_queue_view(self) -> None:
        jobs = self.queue.snapshot()
        controls = []
        for job in jobs:
            actions = []
            if job.state in {"failed", "cancelled"}:
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="重试",
                        on_click=lambda _, job_id=job.id: self._retry_queue_job(job_id),
                    )
                )
            if job.state != "running":
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="移除",
                        on_click=lambda _, job_id=job.id: self._remove_queue_job(job_id),
                    )
                )
            controls.append(
                ft.Card(
                    content=ft.Container(
                        padding=12,
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(job.options.source.name, weight=ft.FontWeight.W_500),
                                        ft.Text(
                                            self._queue_state_text(job),
                                            color=ft.Colors.ON_SURFACE_VARIANT,
                                        ),
                                        ft.Text(
                                            str(job.options.output),
                                            size=12,
                                            color=ft.Colors.ON_SURFACE_VARIANT,
                                        ),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                *actions,
                            ]
                        ),
                    )
                )
            )
        self.queue_list.controls = controls
        if not jobs:
            self.queue_status.value = "队列为空"
        else:
            completed = sum(job.state == "completed" for job in jobs)
            self.queue_status.value = f"共 {len(jobs)} 项 · 已完成 {completed} 项"
        self.page.update(self.queue_list, self.queue_status)

    async def _start_queue(self, _):
        if self.queue_runner_task is not None and not self.queue_runner_task.done():
            return
        if self.queue.next_queued() is None:
            self._show_error("无法开始队列", ValueError("队列中没有等待任务"))
            return
        self.queue_runner_task = asyncio.create_task(self._run_queue())

    async def _run_queue(self) -> None:
        self.queue_run_button.disabled = True
        self.page.update(self.queue_run_button)
        try:
            while True:
                job = self.queue.next_queued()
                if job is None:
                    break
                self.active_queue_job_id = job.id
                self.queue_cancel_event.clear()
                self.queue.update(job.id, state="running")
                self._refresh_queue_view()
                self.logger.event("queue", f"start {job.options.source}")
                try:
                    info = await asyncio.to_thread(probe_source, job.options)
                    report = await asyncio.to_thread(
                        check_compatibility,
                        job.options,
                        info,
                        job.target_profile,
                    )
                    if not report.can_convert:
                        raise ValueError(
                            "; ".join(
                                issue.message for issue in report.issues if issue.severity == "error"
                            )
                        )

                    def progress(value: ConversionProgress) -> None:
                        self.queue.update(job.id, progress=value)

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
                    self.queue.update(job.id, state="completed", summary=summary)
                    self.logger.event("queue", f"completed {summary.path}")
                except ConversionCancelled:
                    self.queue.update(job.id, state="cancelled")
                    self.logger.event("queue", f"cancelled {job.options.source}")
                except Exception as exc:
                    self.queue.update(job.id, state="failed", error=str(exc))
                    self.logger.event("queue", f"failed {job.options.source}: {exc}", level=40)
                finally:
                    self.active_queue_job_id = None
                    self._refresh_queue_view()
        finally:
            self.queue_run_button.disabled = False
            self.page.update(self.queue_run_button)

    def _cancel_queue_job(self, _):
        if self.active_queue_job_id is not None:
            self.queue_cancel_event.set()

    def _retry_queue_job(self, job_id: str) -> None:
        self.queue.retry(job_id)
        self._refresh_queue_view()

    def _remove_queue_job(self, job_id: str) -> None:
        try:
            self.queue.remove(job_id)
            self._refresh_queue_view()
        except Exception as exc:
            self._show_error("无法移除任务", exc)

    def _clear_completed_jobs(self, _):
        self.queue.clear_completed()
        self._refresh_queue_view()

    async def _choose_directory(self, _):
        selected = await self.file_picker.get_directory_path(dialog_title="选择图片帧目录")
        if selected:
            self._set_source(Path(selected))
            await self._load_first_preview()

    async def _choose_output(self, _):
        source = Path(self.source_field.value) if self.source_field.value else None
        suggested = f"{source.stem if source else 'OUTPUT'}.BIN"
        selected = await self.file_picker.save_file(
            dialog_title="保存 OVID 文件",
            file_name=suggested,
            initial_directory=self.settings.output_directory or None,
            allowed_extensions=["BIN", "bin"],
        )
        if selected:
            path = Path(selected)
            if path.suffix.casefold() != ".bin":
                path = path.with_suffix(".BIN")
            self.output_field.value = str(path)
            self.page.update()

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
        self.player_slider.disabled = False
        self.player_slider.min = 0
        self.player_slider.max = max(1, header.frame_count - 1)
        self.player_slider.divisions = max(1, header.frame_count - 1)
        self.player_slider.value = 0
        self.player_playing = False
        self.player_revision += 1
        self.player_play_button.icon = ft.Icons.PLAY_ARROW
        self._draw_player_frame(0)
        if show_page:
            self._show_page(2)

    def _draw_player_frame(self, index: int) -> None:
        frame = self.player.seek(
            index,
            invert=bool(self.player_invert.value),
            scale=int(self.player_scale.value),
        )
        self.player_image.src = frame.png
        self.player_slider.value = frame.index
        header = self.player.header
        crc = "CRC 正确" if frame.crc_valid else "CRC 错误，保持上一帧"
        self.player_label.value = (
            f"第 {frame.index + 1}/{header.frame_count} 帧 · "
            f"{header.width}×{header.height} · {header.fps} FPS · {crc}"
        )
        self.page.update(self.player_image, self.player_slider, self.player_label)

    async def _player_seek(self, _):
        try:
            self._draw_player_frame(round(float(self.player_slider.value)))
        except Exception as exc:
            self._show_error("无法定位 OVID 帧", exc)

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
        self.page.show_dialog(
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

    def _set_source(self, source: Path) -> None:
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        self.source_info = None
        self.trim_slider.disabled = True
        self.trim_slider.min = 0
        self.trim_slider.max = 1
        self.trim_slider.start_value = 0
        self.trim_slider.end_value = 1
        self.trim_label.value = "正在读取素材时间轴…"
        self.source_field.value = str(source)
        output_dir = Path(self.settings.output_directory) if self.settings.output_directory else source.parent
        self.output_field.value = str(output_dir / f"{source.stem}.BIN")
        self.preview_label.value = "正在载入预览…"
        self.page.update()

    async def _refresh_preview(self, _=None):
        self.preview_revision += 1
        await self._load_first_preview()

    async def _load_first_preview(self):
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
        self.page.update(self.preview_play_button)
        revision = self.preview_revision
        try:
            options = self._options(require_output=False)
            first_probe = self.source_info is None
            async with self.preview_lock:
                await asyncio.to_thread(self.preview.close)
                info = await asyncio.to_thread(probe_source, options)
                await asyncio.to_thread(self.preview.reset, options, info)
                original, data, index = await asyncio.to_thread(self.preview.next_frame)
            if revision != self.preview_revision:
                return
            self.source_info = info
            if first_probe:
                self._configure_trim_timeline(info)
            total = info.frame_count if info.frame_count is not None else "?"
            estimate = estimate_output_bytes(options, info)
            self._set_preview_frame(original, data, f"第 {index}/{total} 帧 · 预计 {human_size(estimate)}")
        except Exception as exc:
            if revision != self.preview_revision:
                return
            self._show_error("无法预览素材", exc)

    async def _preview_first(self, _):
        self.preview_revision += 1
        await self._load_first_preview()

    async def _preview_next(self, _=None) -> bool:
        revision = self.preview_revision
        try:
            async with self.preview_lock:
                original, data, index = await asyncio.to_thread(self.preview.next_frame)
            if revision != self.preview_revision:
                return False
            self._set_preview_frame(original, data, f"第 {index} 帧")
            return True
        except PreviewFinished:
            if revision != self.preview_revision:
                return False
            self.preview_label.value = "已到最后一帧"
            self.page.update(self.preview_label)
            return False
        except Exception as exc:
            if revision != self.preview_revision:
                return False
            self._show_error("无法读取下一帧", exc)
            return False

    async def _preview_previous(self, _):
        revision = self.preview_revision
        try:
            async with self.preview_lock:
                original, data, index = self.preview.previous_frame()
            if revision != self.preview_revision:
                return
            self._set_preview_frame(original, data, f"第 {index} 帧")
        except Exception as exc:
            if revision != self.preview_revision:
                return
            self._show_error("无法读取上一帧", exc)

    def _set_preview_frame(self, original: bytes, data: bytes, label: str) -> None:
        self.original_preview_image.src = original
        self.preview_image.src = data
        self.preview_label.value = label
        self.page.update(self.original_preview_image, self.preview_image, self.preview_label)

    async def _toggle_preview_playback(self, _):
        if self.preview_playing:
            self.preview_playing = False
            self.preview_playback_revision += 1
            self.preview_play_button.icon = ft.Icons.PLAY_ARROW
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
                self.page.update(self.preview_play_button)

    async def _start_conversion(self, _):
        if self.busy:
            return
        try:
            options = self._options()
            options.validate()
            info = self.source_info or await asyncio.to_thread(probe_source, options)
            report = await asyncio.to_thread(
                check_compatibility,
                options,
                info,
                self.target_dropdown.value,
            )
            if not report.can_convert:
                errors = "\n".join(
                    f"• {issue.message}" for issue in report.issues if issue.severity == "error"
                )
                raise ValueError(errors)
        except Exception as exc:
            self._show_error("无法开始转换", exc)
            return

        self.busy = True
        self.conversion_revision += 1
        revision = self.conversion_revision
        self.latest_conversion_progress = None
        self.progress_display_ratio = 0.0
        self.progress_finish_deadline = None
        self.progress_finish_event = asyncio.Event()
        self.cancel_event.clear()
        self.convert_button.disabled = True
        self.cancel_button.visible = True
        self.progress_bar.visible = True
        self.progress_bar.value = 0 if info.frame_count else None
        self.progress_text.value = "正在准备转换…"
        self.page.update()
        self.logger.event(
            "convert",
            f"start source={options.source} output={options.output} "
            f"size={options.width}x{options.height} fps={options.fps} "
            f"workers={options.workers or 'auto'} fast_video={options.fast_video}",
        )
        loop = asyncio.get_running_loop()
        self.progress_render_task = asyncio.create_task(
            self._render_conversion_progress(revision, self.progress_finish_event)
        )

        def progress(value: ConversionProgress) -> None:
            # A single assignment under the GIL is enough here. The renderer
            # samples only the newest value, so a fast converter cannot flood
            # the asyncio event queue with one callback per frame.
            self.latest_conversion_progress = (revision, value)

        try:
            summary = await asyncio.to_thread(
                convert_media,
                options,
                progress=progress,
                cancelled=self.cancel_event.is_set,
                source_info=info,
            )
            self.latest_conversion_progress = (
                revision,
                ConversionProgress(summary.frame_count, summary.frame_count, summary.file_bytes),
            )
            self.progress_finish_deadline = loop.time() + PROGRESS_FINISH_SECONDS
            try:
                await asyncio.wait_for(
                    self.progress_finish_event.wait(),
                    timeout=PROGRESS_FINISH_SECONDS + 0.1,
                )
            except TimeoutError:
                self.progress_display_ratio = 1.0
            self.progress_bar.value = 1
            self.progress_text.value = (
                f"完成：{summary.frame_count} 帧 · {human_size(summary.file_bytes)} · {summary.path.name}"
            )
            if self.page_index == 0:
                self.page.update(self.progress_bar, self.progress_text)
            self._show_message("转换完成", f"OVID 文件已保存到：\n{summary.path}")
            self.logger.event(
                "convert",
                f"completed frames={summary.frame_count} bytes={summary.file_bytes} path={summary.path}",
            )
            self._open_player_path(summary.path, show_page=False)
        except ConversionCancelled:
            self.progress_text.value = "转换已取消，临时文件已清理"
            if self.page_index == 0:
                self.page.update(self.progress_text)
            self.logger.event("convert", "cancelled")
        except Exception as exc:
            self.progress_text.value = "转换失败"
            if self.page_index == 0:
                self.page.update(self.progress_text)
            self._show_error("转换失败", exc)
            self.logger.event("convert", f"failed: {exc}", level=40)
        finally:
            self.busy = False
            self.convert_button.disabled = False
            self.cancel_button.visible = False
            await self._stop_progress_renderer()
            self.page.update()

    async def _render_conversion_progress(
        self,
        revision: int,
        finish_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_running_loop()
        last_time = loop.time()
        last_completed = -1
        try:
            while self.busy and revision == self.conversion_revision:
                now = loop.time()
                elapsed = max(0.0, now - last_time)
                last_time = now
                current = self.latest_conversion_progress
                if current is not None and current[0] == revision:
                    value = current[1]
                    target = value.ratio
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

                    if target is None:
                        text = (
                            f"已转换 {value.completed_frames} 帧 · "
                            f"{human_size(value.output_bytes)} · "
                            f"{value.current_fps:.1f} FPS"
                        )
                    else:
                        eta = (
                            f" · 剩余 {value.remaining_seconds:.1f} 秒"
                            if value.remaining_seconds is not None
                            else ""
                        )
                        text = (
                            f"{target * 100:.1f}% · "
                            f"{value.completed_frames}/{value.total_frames} 帧 · "
                            f"{human_size(value.output_bytes)} · "
                            f"{value.current_fps:.1f}/{value.average_fps:.1f} FPS{eta}"
                        )
                    text_changed = value.completed_frames != last_completed
                    if text_changed:
                        self.progress_text.value = text
                        last_completed = value.completed_frames
                    if self.page_index == 0 and (
                        target is not None or text_changed
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
        self.cancel_event.set()
        self.progress_text.value = "正在取消…"
        if self.page_index == 0:
            self.page.update(self.progress_text)

    def _configure_trim_timeline(self, info) -> None:
        if info.kind == "image" or not info.duration_seconds:
            self.trim_slider.disabled = True
            self.trim_label.value = "单张图片无需裁剪"
            self.page.update(self.trim_slider, self.trim_label)
            return
        duration = max(1 / max(1, int(self.fps_field.value)), info.duration_seconds)
        self.trim_slider.disabled = False
        self.trim_slider.min = 0
        self.trim_slider.max = duration
        self.trim_slider.start_value = 0
        self.trim_slider.end_value = duration
        self.trim_slider.divisions = min(1000, max(1, info.frame_count or round(duration * 10)))
        self.trim_label.value = f"转换范围：0.00–{duration:.2f} 秒"
        self.page.update(self.trim_slider, self.trim_label)

    async def _on_trim_change(self, _):
        start = float(self.trim_slider.start_value)
        end = float(self.trim_slider.end_value)
        self.trim_label.value = f"转换范围：{start:.2f}–{end:.2f} 秒（终点不包含）"
        self.page.update(self.trim_label)
        if self.source_field.value:
            self.preview_revision += 1
            await self._load_first_preview()

    async def _auto_threshold_clicked(self, event) -> None:
        await self._auto_threshold(str(event.control.data))

    async def _auto_threshold(self, mode: str) -> None:
        try:
            async with self.preview_lock:
                gray = self.preview.current_grayscale().copy()
            value = await asyncio.to_thread(suggested_threshold, gray, mode)
            self.dither_control.selected = ["threshold"]
            self.threshold_slider.disabled = False
            self.threshold_slider.value = value
            self.page.update(self.dither_control, self.threshold_slider)
            await self._rerender_current_preview()
        except Exception as exc:
            self._show_error("无法分析自动阈值", exc)

    def _refresh_preset_options(self) -> None:
        if not hasattr(self, "preset_dropdown"):
            return
        presets = self.preset_store.all_presets()
        self.preset_dropdown.options = [
            ft.DropdownOption(key=preset.name, text=preset.name) for preset in presets
        ]
        if not any(preset.name == self.preset_dropdown.value for preset in presets):
            self.preset_dropdown.value = presets[0].name

    def _apply_selected_preset(self, _):
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
        self.threshold_slider.value = preset.threshold
        self.threshold_slider.disabled = preset.dither != "threshold"
        self.invert_switch.value = preset.invert
        self.background_dropdown.value = preset.background
        self.recursive_switch.value = preset.recursive
        self.target_dropdown.value = preset.target_profile
        self.settings.workers = preset.workers
        self.settings.fast_video = preset.fast_video
        self.page.update()
        if self.source_field.value:
            asyncio.create_task(self._on_geometry_change(None))

    def _save_preset_dialog(self, _):
        self.preset_name_field.value = ""
        self.page.show_dialog(
            ft.AlertDialog(
                title="保存转换预设",
                content=self.preset_name_field,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.FilledButton("保存", on_click=self._confirm_save_preset),
                ],
            )
        )

    def _confirm_save_preset(self, _):
        try:
            options = self._options(require_output=False)
            preset = ConversionPreset.from_options(
                self.preset_name_field.value.strip(),
                options,
                self.target_dropdown.value,
            )
            self.preset_store.upsert(preset)
            self._refresh_preset_options()
            self.preset_dropdown.value = preset.name
            self.page.pop_dialog()
            self.page.update(self.preset_dropdown)
        except Exception as exc:
            self._show_error("无法保存预设", exc)

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
        self.preset_store.delete(preset.name)
        self._refresh_preset_options()
        self.page.update(self.preset_dropdown)

    async def _on_dither_change(self, _):
        self.threshold_slider.disabled = self.dither_control.selected[0] != "threshold"
        self.page.update(self.dither_control, self.threshold_slider)
        await self._rerender_current_preview()

    async def _on_threshold_change(self, _):
        await self._rerender_current_preview(debounce=True)

    async def _on_invert_change(self, _):
        await self._rerender_current_preview()

    async def _on_geometry_change(self, _):
        """Reload the preview when an option changes frame geometry or timing."""
        if not self.source_field.value:
            return
        self.preview_revision += 1
        revision = self.preview_revision
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        await asyncio.sleep(0.12)
        if revision != self.preview_revision:
            return
        try:
            options = self._options(require_output=False)
            options.validate()
        except (OSError, ValueError):
            # A number field may be temporarily empty while the user is typing.
            return
        await self._load_first_preview()

    async def _rerender_current_preview(self, *, debounce: bool = False) -> None:
        if not self.source_field.value or self.preview.index < 0:
            return
        self.preview_render_revision += 1
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
            self._set_preview_frame(original, data, f"第 {index} 帧")
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
            self.settings = AppSettings(
                width=width,
                height=height,
                fps=fps,
                output_directory=self.default_output.value,
                theme=self.theme_dropdown.value,
                workers=int(self.worker_dropdown.value),
                fast_video=bool(self.fast_video_switch.value),
                target_profile=self.target_dropdown.value,
            )
            save_settings(self.settings)
            self.width_field.value = str(width)
            self.height_field.value = str(height)
            self.fps_field.value = str(fps)
            self._apply_theme(self.settings.theme)
            if self.source_field.value:
                self.preview_revision += 1
                self.preview_needs_reload = True
            self._show_message("设置已保存", "新的默认参数将在当前窗口和下次启动时使用。")
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

    def _show_page(self, index: int) -> None:
        pages = [
            self.convert_page,
            self.queue_page,
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
        elif index == 1:
            self._refresh_queue_view()

    def _on_resize(self, _=None) -> None:
        width = self.page.width or self.page.window.width or 1120
        compact = width < 800
        self.navigation_rail.visible = not compact
        self.page.navigation_bar = self.navigation_bar if compact else None
        self.page.update()

    def _show_error(self, title: str, error: Exception) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                title=title,
                icon=ft.Icon(ft.Icons.ERROR_OUTLINE),
                content=ft.Text(str(error)),
                actions=[ft.Button("确定", on_click=lambda _: self.page.pop_dialog())],
            )
        )

    def _show_message(self, title: str, message: str) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                title=title,
                icon=ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE),
                content=ft.Text(message, selectable=True),
                actions=[ft.Button("确定", on_click=lambda _: self.page.pop_dialog())],
            )
        )

    def _show_notice(self, message: str) -> None:
        self.page.show_dialog(
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
