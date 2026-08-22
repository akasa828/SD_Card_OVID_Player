#!/usr/bin/env python3
"""Material 3 desktop interface for the OVID media converter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import flet as ft

from converter_version import DISPLAY_NAME, VERSION
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


REPOSITORY_URL = "https://github.com/akasa828/SD_Card_OVID_Player"
MAX_PREVIEW_CACHE = 180
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PRIMARY_FONT = "Google Sans Flex"
SIMPLIFIED_CHINESE_FONT = "Noto Sans SC"
NAVIGATION_ITEMS = (
    (ft.Icons.MOVIE, "转换"),
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
        text_theme=_app_text_theme(),
    )


def _app_text_style(weight: ft.FontWeight = ft.FontWeight.W_400) -> ft.TextStyle:
    """Keep Latin and Simplified Chinese text on the same visual weight."""
    return ft.TextStyle(
        weight=weight,
        font_family=PRIMARY_FONT,
        font_family_fallback=[SIMPLIFIED_CHINESE_FONT],
    )


def _app_text_theme() -> ft.TextTheme:
    regular = ft.FontWeight.W_400
    medium = ft.FontWeight.W_500
    return ft.TextTheme(
        body_large=_app_text_style(regular),
        body_medium=_app_text_style(regular),
        body_small=_app_text_style(regular),
        display_large=_app_text_style(medium),
        display_medium=_app_text_style(medium),
        display_small=_app_text_style(medium),
        headline_large=_app_text_style(medium),
        headline_medium=_app_text_style(medium),
        headline_small=_app_text_style(medium),
        label_large=_app_text_style(medium),
        label_medium=_app_text_style(medium),
        label_small=_app_text_style(medium),
        title_large=_app_text_style(medium),
        title_medium=_app_text_style(medium),
        title_small=_app_text_style(medium),
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


@dataclass
class AppSettings:
    width: int = 128
    height: int = 64
    fps: int = 15
    output_directory: str = ""
    theme: str = "system"


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
        self.iterator = None
        self.frames: list[object] = []
        self.index = -1
        self.base_index = 0

    def close(self) -> None:
        if self.iterator is not None:
            close = getattr(self.iterator, "close", None)
            if close is not None:
                close()
        self.iterator = None

    def reset(self, options: ConversionOptions) -> None:
        self.close()
        self.options = options
        self.iterator = iter_source_images(options)
        self.frames.clear()
        self.index = -1
        self.base_index = 0

    def next_frame(self) -> tuple[bytes, int]:
        if self.options is None or self.iterator is None:
            raise ValueError("请先选择输入素材")
        if self.index + 1 < len(self.frames):
            self.index += 1
            data = preview_prepared_png(self.frames[self.index], self.options, scale=4)
            return data, self.base_index + self.index + 1

        try:
            image = next(self.iterator)
        except StopIteration as exc:
            # StopIteration cannot cross an asyncio Future boundary. Convert it
            # before next_frame() returns to asyncio.to_thread().
            raise PreviewFinished("已到最后一帧") from exc
        prepared = prepare_monochrome_source(image, self.options)
        data = preview_prepared_png(prepared, self.options, scale=4)
        self.frames.append(prepared)
        self.index += 1
        if len(self.frames) > MAX_PREVIEW_CACHE:
            self.frames.pop(0)
            self.index -= 1
            self.base_index += 1
        return data, self.base_index + self.index + 1

    def previous_frame(self) -> tuple[bytes, int]:
        if not self.frames:
            raise ValueError("当前没有预览帧")
        if self.index > 0:
            self.index -= 1
        data = preview_prepared_png(self.frames[self.index], self.options, scale=4)
        return data, self.base_index + self.index + 1

    def rerender_current(self, dither: str, threshold: int, invert: bool) -> tuple[bytes, int]:
        if self.options is None or not self.frames or self.index < 0:
            raise ValueError("当前没有预览帧")
        self.options = replace(
            self.options,
            dither=dither,
            threshold=threshold,
            invert=invert,
        )
        data = preview_prepared_png(self.frames[self.index], self.options, scale=4)
        return data, self.base_index + self.index + 1


class ConverterApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings = load_settings()
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
            text_theme=_app_text_theme(),
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
                    on_click=lambda _: self._show_page(2),
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

        self.preview_image = ft.Image(
            src=self._empty_preview(),
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            filter_quality=ft.FilterQuality.NONE,
            anti_alias=False,
            height=320,
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

        self.convert_page = self._build_convert_page()
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
            [self.source_field, source_actions, output_actions],
            col=12,
        )
        preview_card = self._card(
            "OLED 预览",
            ft.Icons.IMAGE,
            [
                ft.Container(
                    content=self.preview_image,
                    bgcolor=ft.Colors.BLACK,
                    border_radius=16,
                    padding=12,
                    alignment=ft.Alignment.CENTER,
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
            ],
            col={"xs": 12, "lg": 7},
        )
        parameter_card = self._card(
            "转换参数",
            ft.Icons.TUNE,
            [
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
                self.background_dropdown,
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
                ft.Row([self.convert_button, self.cancel_button], wrap=True),
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

    def _build_settings_page(self):
        self.default_width = self._number_field("默认宽度", self.settings.width, 1, 255)
        self.default_height = self._number_field("默认高度", self.settings.height, 1, 255)
        self.default_fps = self._number_field("默认 FPS", self.settings.fps, 1, 120)
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
                        ft.FilledButton("保存设置", icon=ft.Icons.SAVE, on_click=self._save_settings),
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

    async def _choose_default_output(self, _):
        selected = await self.file_picker.get_directory_path(dialog_title="选择默认输出目录")
        if selected:
            self.default_output.value = selected
            self.page.update()

    def _set_source(self, source: Path) -> None:
        self.preview_playing = False
        self.preview_playback_revision += 1
        self.preview_render_revision += 1
        self.preview_revision += 1
        self.preview_play_button.icon = ft.Icons.PLAY_ARROW
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
            async with self.preview_lock:
                await asyncio.to_thread(self.preview.close)
                info = await asyncio.to_thread(probe_source, options)
                await asyncio.to_thread(self.preview.reset, options)
                data, index = await asyncio.to_thread(self.preview.next_frame)
            if revision != self.preview_revision:
                return
            total = info.frame_count if info.frame_count is not None else "?"
            estimate = estimate_output_bytes(options, info)
            self._set_preview_frame(data, f"第 {index}/{total} 帧 · 预计 {human_size(estimate)}")
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
                data, index = await asyncio.to_thread(self.preview.next_frame)
            if revision != self.preview_revision:
                return False
            self._set_preview_frame(data, f"第 {index} 帧")
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
                data, index = self.preview.previous_frame()
            if revision != self.preview_revision:
                return
            self._set_preview_frame(data, f"第 {index} 帧")
        except Exception as exc:
            if revision != self.preview_revision:
                return
            self._show_error("无法读取上一帧", exc)

    def _set_preview_frame(self, data: bytes, label: str) -> None:
        self.preview_image.src = data
        self.preview_label.value = label
        self.page.update(self.preview_image, self.preview_label)

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
            info = await asyncio.to_thread(probe_source, options)
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
        except ConversionCancelled:
            self.progress_text.value = "转换已取消，临时文件已清理"
            if self.page_index == 0:
                self.page.update(self.progress_text)
        except Exception as exc:
            self.progress_text.value = "转换失败"
            if self.page_index == 0:
                self.page.update(self.progress_text)
            self._show_error("转换失败", exc)
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
                            f"{human_size(value.output_bytes)}"
                        )
                    else:
                        text = (
                            f"{target * 100:.1f}% · "
                            f"{value.completed_frames}/{value.total_frames} 帧 · "
                            f"{human_size(value.output_bytes)}"
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
                data, index = await asyncio.to_thread(
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
            self._set_preview_frame(data, f"第 {index} 帧")
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
        pages = [self.convert_page, self.settings_page, self.about_page]
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


async def main(page: ft.Page) -> None:
    ConverterApp(page)
    page.update()
    await page.window.center()
    page.update()


if __name__ == "__main__":
    ft.run(main, name="OVID Converter", assets_dir=str(ASSETS_DIR))
