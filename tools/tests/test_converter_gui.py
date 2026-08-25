import asyncio
import io
import inspect
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
GUI_SOURCE = ROOT / "tools" / "ovid_converter_gui.py"
PACKAGE_SOURCE = ROOT / "tools" / "package_converter.ps1"
FLUTTER_PACKAGE_SOURCE = ROOT / "tools" / "package_converter_flutter.ps1"
WORKFLOW_SOURCE = ROOT / ".github" / "workflows" / "release-assets.yml"
FONT_ROOT = ROOT / "tools" / "assets" / "fonts"
BUILD_BATCH = ROOT / "Build_OVID_Converter.bat"

sys.path.insert(0, str(TOOLS_DIR))
import ovid_converter_gui as converter_gui  # noqa: E402


class ConverterGuiTests(unittest.TestCase):
    def test_lightweight_package_excludes_unused_flet_web_backend(self) -> None:
        source = PACKAGE_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "--pyinstaller-build-args=--exclude-module=flet_web",
            source,
        )
        self.assertIn("--hidden-import imageio_ffmpeg", source)

    def test_timestamps_use_consistent_centisecond_format(self) -> None:
        self.assertEqual("00:00.00", converter_gui.format_timestamp(0))
        self.assertEqual("01:02.35", converter_gui.format_timestamp(62.345))
        self.assertEqual("01:01:01.25", converter_gui.format_timestamp(3661.25))
        self.assertEqual("--:--.--", converter_gui.format_timestamp(None))

    def test_preview_heights_adapt_to_the_window(self) -> None:
        self.assertEqual((160, 260), converter_gui.responsive_preview_heights(480))
        self.assertEqual((228, 395), converter_gui.responsive_preview_heights(760))
        self.assertEqual((300, 520), converter_gui.responsive_preview_heights(1200))

    def test_repeated_resize_updates_only_changed_preview_controls(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.compact_layout = None
        app.navigation_rail = converter_gui.ft.NavigationRail(destinations=[])
        app.navigation_bar = converter_gui.ft.NavigationBar(destinations=[])
        app.original_preview_image = converter_gui.ft.Image(src=b"", height=260)
        app.preview_image = converter_gui.ft.Image(src=b"", height=260)
        app.player_image = converter_gui.ft.Image(src=b"", height=360)
        app.page = SimpleNamespace(
            width=1000,
            height=760,
            window=SimpleNamespace(width=1000, height=760),
            navigation_bar=None,
            update=mock.Mock(),
        )

        app._on_resize()
        app.page.update.assert_called_once_with()
        self.assertEqual(228, app.preview_image.height)
        self.assertEqual(395, app.player_image.height)

        app.page.update.reset_mock()
        app.page.height = 700
        app._on_resize()
        self.assertEqual(
            (
                app.original_preview_image,
                app.preview_image,
                app.player_image,
            ),
            app.page.update.call_args.args,
        )

        app.page.update.reset_mock()
        app._on_resize()
        app.page.update.assert_not_called()

    def test_batch_result_distinguishes_successes_and_failures(self) -> None:
        self.assertEqual("本轮完成：3/3 个任务", converter_gui.batch_result_text(3, 3))
        self.assertEqual("本轮结束：2 成功 · 1 失败", converter_gui.batch_result_text(2, 3))

    def test_timeline_sliders_are_continuous_and_defer_seeking(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        trim_start = source.index("self.trim_slider = ft.RangeSlider(")
        trim_end = source.index("self.trim_label =", trim_start)
        preview_start = source.index("self.preview_timeline = ft.Slider(")
        preview_end = source.index("self.preview_time_label", preview_start)
        player_start = source.index("self.player_slider = ft.Slider(")
        player_end = source.index("self.player_time_label", player_start)
        for slider_source in (
            source[trim_start:trim_end],
            source[preview_start:preview_end],
            source[player_start:player_end],
        ):
            self.assertNotIn("divisions=", slider_source)
            self.assertIn("on_change_start=", slider_source)
            self.assertIn("on_change_end=", slider_source)
    def test_fixed_threshold_is_the_default_dither_mode(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        threshold = source.index('ft.Segment(\n                    value="threshold"')
        floyd = source.index('ft.Segment(value="floyd"')
        self.assertLess(threshold, floyd)
        self.assertIn('selected=["threshold"]', source)
        self.assertIn("disabled=False", source)

    def test_convert_page_does_not_repeat_the_app_purpose_as_a_title(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("把素材直接转换成 OLED 可以播放的 OVID 文件", source)

    def test_preview_image_keeps_the_previous_frame_while_decoding(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("gapless_playback=True", source)
        self.assertIn(
            "controls = [self.original_preview_image, self.preview_image, self.preview_label]",
            source,
        )
        self.assertIn("self.page.update(*controls)", source)

    def test_threshold_has_live_preview_and_help_text(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("on_change=self._on_threshold_change", source)
        self.assertIn("建议先使用 128", source)
        self.assertIn("常用范围为 96–160", source)

    def test_timeline_and_otsu_suggestion_are_user_controlled(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("self.preview_timeline = ft.Slider(", source)
        self.assertIn("on_change_end=self._preview_seek", source)
        self.assertIn("自动阈值建议", source)
        self.assertIn("是否应用？", source)
        self.assertIn("_apply_threshold_suggestion", source)

    def test_all_frame_options_refresh_the_preview(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("on_change=self._on_geometry_change"), 4)
        self.assertEqual(source.count("on_select=self._on_geometry_change"), 2)
        self.assertIn("on_change=self._on_invert_change", source)
        self.assertIn('label="补边与透明背景"', source)
        self.assertIn('"跳过开头帧", 0, 0, 999999', source)
        self.assertIn("await self._load_first_preview()", source)

    def test_dropdowns_use_the_flet_select_event(self) -> None:
        parameters = inspect.signature(converter_gui.ft.Dropdown).parameters
        self.assertIn("on_select", parameters)
        self.assertNotIn("on_change", parameters)

    def test_geometry_preview_refresh_is_debounced(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.source_field = SimpleNamespace(value="source.png")
        app.preview_revision = 0
        app.preview_playing = True
        app.preview_playback_revision = 0
        app.preview_render_revision = 0
        options = SimpleNamespace(validate=mock.Mock())
        app._options = mock.Mock(return_value=options)
        app._load_first_preview = mock.AsyncMock()

        async def exercise() -> None:
            with mock.patch.object(converter_gui.asyncio, "sleep", new=mock.AsyncMock()):
                await app._on_geometry_change(None)

        asyncio.run(exercise())
        self.assertFalse(app.preview_playing)
        options.validate.assert_called_once_with()
        app._load_first_preview.assert_awaited_once_with()

    def test_preview_fps_validation(self) -> None:
        for value in (1, "15", 30, "120"):
            self.assertEqual(int(value), converter_gui.parse_preview_fps(value))
        for value in (None, "", "abc", 0, -1, 121):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "FPS 必须是 1–120 之间的整数"):
                    converter_gui.parse_preview_fps(value)

    def test_preview_deadline_includes_decode_time(self) -> None:
        delay, deadline = converter_gui.advance_preview_deadline(10.0, 10.02, 0.05)
        self.assertAlmostEqual(0.03, delay)
        self.assertAlmostEqual(10.05, deadline)

        delay, deadline = converter_gui.advance_preview_deadline(10.0, 10.08, 0.05)
        self.assertEqual(0.0, delay)
        self.assertEqual(10.08, deadline)

    def test_progress_smoothing_is_monotonic_and_does_not_overshoot(self) -> None:
        current = 0.0
        values = []
        for _ in range(20):
            current = converter_gui.smooth_progress_value(current, 0.75, 0.016)
            values.append(current)
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], 0.0)
        self.assertLessEqual(values[-1], 0.75)
        self.assertEqual(0.75, converter_gui.smooth_progress_value(0.75, 0.4, 0.016))

    def test_progress_renderer_updates_controls_without_page_navigation(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.busy = True
        app.conversion_revision = 1
        app.latest_conversion_progress = (
            1,
            converter_gui.ConversionProgress(25, 100, 4096),
        )
        app.progress_display_ratio = 0.0
        app.progress_finish_deadline = None
        app.progress_bar = SimpleNamespace(value=0.0)
        app.progress_text = SimpleNamespace(value="")
        app.page_index = 0
        app.page = SimpleNamespace(update=mock.Mock())

        async def exercise() -> None:
            finish = asyncio.Event()
            task = asyncio.create_task(app._render_conversion_progress(1, finish))
            await asyncio.sleep(0.04)
            app.busy = False
            await task

        asyncio.run(exercise())
        self.assertGreater(app.page.update.call_count, 0)
        self.assertGreater(app.progress_bar.value, 0.0)
        self.assertLessEqual(app.progress_bar.value, 0.25)
        self.assertIn("25.0%", app.progress_text.value)

    def test_invalid_saved_theme_falls_back_to_system(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text('{"theme": "broken"}', encoding="utf-8")
            with mock.patch.dict(
                converter_gui.os.environ,
                {"FLET_APP_STORAGE_DATA": directory},
            ):
                self.assertEqual("system", converter_gui.load_settings().theme)

    def test_material_light_palette_has_readable_primary_text(self) -> None:
        def luminance(color: str) -> float:
            channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(first: str, second: str) -> float:
            bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
            return (bright + 0.05) / (dark + 0.05)

        colors = converter_gui.MATERIAL_LIGHT_COLORS
        self.assertGreaterEqual(contrast(colors["surface"], colors["on_surface"]), 4.5)
        self.assertGreaterEqual(contrast(colors["primary"], colors["on_primary"]), 4.5)

    def test_material_themes_construct_with_flet_086(self) -> None:
        light_theme = converter_gui.material_light_theme()
        dark_theme = converter_gui.ft.Theme(
            color_scheme_seed=converter_gui.ft.Colors.INDIGO,
            use_material3=True,
        )
        self.assertIsNotNone(light_theme)
        self.assertIsNotNone(dark_theme)
        self.assertNotIn("brightness=", GUI_SOURCE.read_text(encoding="utf-8"))

    def test_light_theme_uses_dark_text_on_light_surfaces(self) -> None:
        theme = converter_gui.material_light_theme()
        colors = converter_gui.MATERIAL_LIGHT_COLORS
        self.assertEqual(colors["on_surface"], theme.text_theme.body_medium.color)
        self.assertEqual(colors["on_surface"], theme.text_theme.title_large.color)
        self.assertEqual(colors["surface"], theme.scaffold_bgcolor)
        self.assertEqual(colors["surface_container"], theme.card_bgcolor)
        self.assertEqual(colors["on_surface_variant"], theme.hint_color)

    def test_light_theme_applies_immediately(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.settings = SimpleNamespace(theme="system")
        theme_button = SimpleNamespace(icon=None)
        app.page = SimpleNamespace(
            theme_mode=None,
            appbar=SimpleNamespace(actions=[theme_button]),
            update=mock.Mock(),
        )

        app._apply_theme("light")

        self.assertEqual("light", app.settings.theme)
        self.assertEqual(converter_gui.ft.ThemeMode.LIGHT, app.page.theme_mode)
        app.page.update.assert_called_once_with()

    def test_stale_preview_task_cannot_replace_current_status(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.preview_revision = 1
        app.preview_lock = asyncio.Lock()
        app.preview_label = SimpleNamespace(value="当前素材")
        app.page = SimpleNamespace(update=mock.Mock())
        app._show_error = mock.Mock()

        def finish_stale_preview() -> None:
            app.preview_revision = 2
            raise converter_gui.PreviewFinished("旧素材已结束")

        app.preview = SimpleNamespace(next_frame=finish_stale_preview)

        result = asyncio.run(app._preview_next())
        self.assertFalse(result)
        self.assertEqual("当前素材", app.preview_label.value)
        app.page.update.assert_not_called()
        app._show_error.assert_not_called()

    def test_preview_end_does_not_raise_stop_iteration_into_future(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = converter_gui.ConversionOptions(
            Path("source.png"),
            Path("output.bin"),
        )
        session.iterator = iter([object()])

        async def consume_preview() -> None:
            with (
                mock.patch.object(converter_gui, "prepare_monochrome_source", return_value=object()),
                mock.patch.object(converter_gui, "preview_prepared_png", return_value=b"frame"),
                mock.patch.object(converter_gui, "source_preview_image", return_value=b"source"),
            ):
                self.assertEqual((b"source", b"frame", 1), await asyncio.to_thread(session.next_frame))
                with self.assertRaises(converter_gui.PreviewFinished) as raised:
                    await asyncio.to_thread(session.next_frame)
                self.assertEqual("已到最后一帧", str(raised.exception))

        asyncio.run(consume_preview())
        session.close()

    def test_source_preview_uses_compact_jpeg_transport(self) -> None:
        from PIL import Image

        encoded = converter_gui.source_preview_image(Image.new("RGB", (640, 360), "#6750A4"))
        self.assertTrue(encoded.startswith(b"\xff\xd8"))
        with Image.open(io.BytesIO(encoded)) as preview:
            self.assertLessEqual(preview.width, 320)
            self.assertLessEqual(preview.height, 180)

    def test_preview_prefetch_renders_oled_frame_off_the_ui_loop(self) -> None:
        from PIL import Image

        session = converter_gui.PreviewSession()
        options = converter_gui.ConversionOptions(
            Path("source.png"),
            Path("output.bin"),
            width=8,
            height=8,
        )
        with mock.patch.object(
            converter_gui,
            "preview_prepared_png",
            return_value=b"oled",
        ) as render:
            entry = session._prepare_entry(Image.new("RGB", (16, 16), "white"), options)
        self.assertEqual(b"oled", entry[3])
        render.assert_called_once()

    def test_stale_prefetch_render_does_not_replace_cached_frame(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = converter_gui.ConversionOptions(
            Path("source.png"),
            Path("output.bin"),
            threshold=96,
        )
        cached = (b"first", object(), ("threshold", 96, False), b"first-preview")
        stale = (b"second", object(), ("threshold", 128, False), b"stale-preview")
        session.frames = [cached]
        session.index = 0
        with mock.patch.object(converter_gui, "preview_prepared_png", return_value=b"updated"):
            original, rendered, updated = session._render(stale)
        self.assertEqual((b"second", b"updated"), (original, rendered))
        self.assertEqual(cached, session.frames[0])
        self.assertEqual(("threshold", 96, False), updated[2])

    def test_preview_prefetch_reuses_duplicate_video_frames(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = object()
        shared = object()
        unique = object()
        session.iterator = iter([shared, shared, unique])
        session.prefetch_limit = 3
        prepared: list[object] = []

        def prepare(image, options):
            prepared.append(image)
            return str(id(image)).encode(), image, ("threshold", 128, False), b"preview"

        with mock.patch.object(session, "_prepare_entry", side_effect=prepare):
            first = session._next_prepared_entry()
            second = session._next_prepared_entry()
            third = session._next_prepared_entry()

        session.close()
        self.assertEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertEqual(2, len(prepared))

    def test_conversion_parameters_use_the_full_content_width(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('col={"xs": 12, "lg": 5}', source)
        preset_start = source.index("self.preset_dropdown = ft.Dropdown(")
        preset_end = source.index("self.preset_name_field", preset_start)
        preset_source = source[preset_start:preset_end]
        self.assertNotIn("expand=True", preset_source)
        self.assertIn('col={"xs": 12, "md": 8}', preset_source)
        self.assertIn('ft.Text("画面与时间"', source)
        self.assertIn('ft.Text("黑白处理"', source)

    def test_dark_theme_uses_dark_card_surfaces(self) -> None:
        theme = converter_gui.material_dark_theme()
        colors = converter_gui.MATERIAL_DARK_COLORS
        self.assertEqual(colors["surface"], theme.scaffold_bgcolor)
        self.assertEqual(colors["surface_container"], theme.card_bgcolor)
        self.assertEqual(colors["on_surface"], theme.text_theme.body_medium.color)

    def test_current_frame_can_be_rerendered_without_reopening_source(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = converter_gui.ConversionOptions(
            source=Path("source.png"),
            output=Path("output.bin"),
        )
        session.frames = [(b"source", object(), ("threshold", 128, False), b"preview")]
        session.index = 0
        with mock.patch.object(converter_gui, "preview_prepared_png", return_value=b"updated"):
            original, data, index = session.rerender_current("threshold", 96, True)
        self.assertEqual((b"source", b"updated", 1), (original, data, index))
        self.assertEqual("threshold", session.options.dither)
        self.assertEqual(96, session.options.threshold)
        self.assertTrue(session.options.invert)

    def test_compact_navigation_matches_the_four_pages(self) -> None:
        self.assertEqual(
            ("转换", "播放器", "设置", "关于"),
            tuple(label for _, label in converter_gui.NAVIGATION_ITEMS),
        )

        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.convert_page = object()
        app.player_page = object()
        app.settings_page = object()
        app.about_page = object()
        app.page_host = SimpleNamespace(content=None)
        app.navigation_rail = SimpleNamespace(selected_index=None)
        app.navigation_bar = SimpleNamespace(selected_index=None)
        app.preview_needs_reload = False
        app.busy = False
        app.page = SimpleNamespace(update=lambda: None)
        app._show_page(99)

        self.assertEqual(0, app.page_index)
        self.assertIs(app.convert_page, app.page_host.content)
        self.assertEqual(0, app.navigation_rail.selected_index)
        self.assertEqual(0, app.navigation_bar.selected_index)

    def test_conversion_page_owns_the_task_list(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn('"转换任务"', source)
        self.assertIn('"转换所选"', source)
        self.assertIn('"应用到已勾选项"', source)
        self.assertNotIn("def _build_queue_page", source)
        self.assertIn("allow_multiple=True", source)

    def test_conversion_page_keeps_primary_action_visible(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("self.convert_scroll = ft.Column(", source)
        self.assertIn("task_bar = ft.Container(", source)
        self.assertIn("return ft.Column([self.convert_scroll, task_bar]", source)
        self.assertIn('ft.ExpansionTile(\n                    title=ft.Text("更多设置"', source)
        self.assertIn('"跳帧、补边背景、目录读取和输出覆盖"', source)

    def test_task_rows_clip_long_names_and_errors(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("row.name.tooltip = str(job.options.source)", source)
        self.assertIn("row.state.max_lines = 2 if job.error else 1", source)
        self.assertGreaterEqual(source.count("overflow=ft.TextOverflow.ELLIPSIS"), 2)

    def test_completed_task_can_open_its_generated_ovid(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.queue = converter_gui.ConversionQueue()
        job = app.queue.add(
            converter_gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"))
        )
        job.summary = SimpleNamespace(path=Path("clip.BIN"))
        app._open_player_path = mock.Mock()
        app._show_error = mock.Mock()

        app._play_completed_job(job.id)

        app._open_player_path.assert_called_once_with(Path("clip.BIN"), show_page=True)
        app._show_error.assert_not_called()

    def test_completed_task_output_actions_use_the_generated_path(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.queue = converter_gui.ConversionQueue()
        job = app.queue.add(
            converter_gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"))
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "clip.BIN"
            job.state = "completed"
            job.summary = SimpleNamespace(path=output)
            app.clipboard = SimpleNamespace(set=mock.AsyncMock())
            app._show_notice = mock.Mock()
            app._show_error = mock.Mock()

            asyncio.run(app._copy_completed_job_path(job.id))
            with mock.patch.object(converter_gui.os, "startfile") as startfile:
                app._open_completed_job_folder(job.id)

            app.clipboard.set.assert_awaited_once_with(str(output.resolve()))
            app._show_notice.assert_called_once_with("已复制输出文件路径")
            startfile.assert_called_once_with(output.parent.resolve())
            app._show_error.assert_not_called()

    def test_completed_task_groups_secondary_actions_in_a_menu(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        job = converter_gui.QueueJob(
            converter_gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN")),
            state="completed",
            summary=SimpleNamespace(path=Path("clip.BIN")),
        )

        actions = app._task_row_actions(job)

        menus = [item for item in actions if isinstance(item, converter_gui.ft.PopupMenuButton)]
        self.assertEqual(1, len(menus))
        self.assertEqual(
            ["打开输出文件夹", "复制输出路径", "移除任务"],
            [item.content for item in menus[0].items],
        )

    def test_keyboard_shortcuts_open_files_and_start_conversion(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.exit_dialog_open = False
        app.convert_button = SimpleNamespace(disabled=False)
        app._choose_file = mock.AsyncMock()
        app._start_conversion = mock.AsyncMock()

        async def exercise() -> None:
            await app._on_keyboard_event(
                SimpleNamespace(key="O", ctrl=True, alt=False, meta=False)
            )
            await app._on_keyboard_event(
                SimpleNamespace(key="Enter", ctrl=True, alt=False, meta=False)
            )

        asyncio.run(exercise())
        app._choose_file.assert_awaited_once_with(None)
        app._start_conversion.assert_awaited_once_with(None)

    def test_player_keyboard_shortcuts_control_playback_and_frames(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.exit_dialog_open = False
        app.page_index = 1
        app.convert_button = SimpleNamespace(disabled=True)
        app._toggle_player = mock.AsyncMock()
        app._player_previous = mock.AsyncMock()
        app._player_next = mock.AsyncMock()
        app._player_first = mock.AsyncMock()

        async def exercise() -> None:
            for key in ("Space", "Arrow Left", "Arrow Right", "Home"):
                await app._on_keyboard_event(
                    SimpleNamespace(key=key, ctrl=False, alt=False, meta=False)
                )

        asyncio.run(exercise())

        app._toggle_player.assert_awaited_once_with(None)
        app._player_previous.assert_awaited_once_with(None)
        app._player_next.assert_awaited_once_with(None)
        app._player_first.assert_awaited_once_with(None)

    def test_window_close_requires_confirmation_while_busy(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.busy = True
        app.exit_dialog_open = False
        app.page = SimpleNamespace(show_dialog=mock.Mock())
        app._shutdown_and_exit = mock.AsyncMock()

        asyncio.run(
            app._on_window_event(
                SimpleNamespace(type=converter_gui.ft.WindowEventType.CLOSE)
            )
        )

        self.assertTrue(app.exit_dialog_open)
        app.page.show_dialog.assert_called_once()
        app._shutdown_and_exit.assert_not_awaited()

    def test_idle_window_close_releases_the_application(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.busy = False
        app.exit_dialog_open = False
        app._shutdown_and_exit = mock.AsyncMock()

        asyncio.run(
            app._on_window_event(
                SimpleNamespace(type=converter_gui.ft.WindowEventType.CLOSE)
            )
        )

        app._shutdown_and_exit.assert_awaited_once()

    def test_empty_queue_disables_conversion_action(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.queue = converter_gui.ConversionQueue()
        app.active_task_id = None
        app.busy = False
        app.queue_list = converter_gui.ft.Column()
        app.queue_status = converter_gui.ft.Text()
        app.queue_empty_state = converter_gui.ft.Container()
        app.convert_button = converter_gui.ft.FilledButton()
        app.select_all_button = converter_gui.ft.TextButton()
        app.select_none_button = converter_gui.ft.TextButton()
        app.clear_completed_button = converter_gui.ft.TextButton()
        app.apply_selected_button = converter_gui.ft.OutlinedButton()
        app.task_action_status = converter_gui.ft.Text()
        app.page = SimpleNamespace(update=mock.Mock())

        app._refresh_queue_view()

        self.assertTrue(app.queue_empty_state.visible)
        self.assertTrue(app.convert_button.disabled)
        self.assertEqual("添加素材后即可开始转换", app.task_action_status.value)

        job = app.queue.add(
            converter_gui.ConversionOptions(Path("clip.mp4"), Path("clip.bin"))
        )
        app.active_task_id = job.id
        app._refresh_queue_view()
        self.assertFalse(app.queue_empty_state.visible)
        self.assertFalse(app.convert_button.disabled)

    def test_queue_refresh_reuses_existing_task_rows(self) -> None:
        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.queue = converter_gui.ConversionQueue()
        app.task_rows = {}
        app.active_task_id = None
        app.busy = False
        app.queue_list = converter_gui.ft.Column()
        app.queue_status = converter_gui.ft.Text()
        app.queue_empty_state = converter_gui.ft.Container()
        app.convert_button = converter_gui.ft.FilledButton()
        app.select_all_button = converter_gui.ft.TextButton()
        app.select_none_button = converter_gui.ft.TextButton()
        app.clear_completed_button = converter_gui.ft.TextButton()
        app.apply_selected_button = converter_gui.ft.OutlinedButton()
        app.task_action_status = converter_gui.ft.Text()
        app.page = SimpleNamespace(update=mock.Mock())
        job = app.queue.add(
            converter_gui.ConversionOptions(Path("clip.mp4"), Path("clip.bin"))
        )

        app._refresh_queue_view()
        original_card = app.task_rows[job.id].card
        app.page.update.reset_mock()
        app.queue.update(
            job.id,
            state="running",
            progress=converter_gui.ConversionProgress(12, 100, 4096),
        )

        app._refresh_queue_view()

        self.assertIs(original_card, app.task_rows[job.id].card)
        updated_controls = app.page.update.call_args.args
        self.assertNotIn(app.queue_list, updated_controls)
        self.assertIn(app.task_rows[job.id].container, updated_controls)

    def test_task_controls_use_independent_option_snapshots(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("self.queue.replace_options(", source)
        self.assertIn("source=job.options.source", source)
        self.assertIn("trim_start_seconds=job.options.trim_start_seconds", source)
        self.assertIn("jobs = self.queue.freeze_selected()", source)

    def test_windows_batch_accepts_supported_python_versions(self) -> None:
        source = BUILD_BATCH.read_text(encoding="utf-8")
        self.assertNotIn("py.exe -3.12", source)
        self.assertIn("(3, 10)", source)
        self.assertIn("(3, 16)", source)
        self.assertIn("Python Install Manager", source)

    def test_bundled_fonts_and_licenses_exist(self) -> None:
        for name in (
            "GoogleSansFlex-Variable.ttf",
            "NotoSansSC-Variable.ttf",
            "OFL-1.1.txt",
            "FONT_SOURCES.md",
        ):
            path = FONT_ROOT / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100, path)

    def test_gui_uses_simplified_chinese_font_fallback(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn('PRIMARY_FONT = "Google Sans Flex"', source)
        self.assertIn('SIMPLIFIED_CHINESE_FONT = "Noto Sans SC"', source)
        self.assertIn('font_family_fallback=[SIMPLIFIED_CHINESE_FONT]', source)
        self.assertIn('current_locale=ft.Locale("zh", "CN")', source)

    def test_gui_centers_after_initial_layout(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        hidden = source.index("page.window.visible = False")
        layout = source.index("ConverterApp(page)")
        centered = source.index("await page.window.center()")
        visible = source.index("page.window.visible = True")
        self.assertLess(hidden, layout)
        self.assertLess(layout, centered)
        self.assertLess(centered, visible)

    def test_desktop_drop_data_is_decoded_and_filtered(self) -> None:
        paths = converter_gui.parse_drop_paths('["C:/media/a.mp4", "C:/media/b.gif"]')
        self.assertEqual([Path("C:/media/a.mp4"), Path("C:/media/b.gif")], paths)
        self.assertEqual([], converter_gui.parse_drop_paths("{"))
        self.assertTrue(converter_gui.is_supported_source(Path("frame.PNG")))
        self.assertFalse(converter_gui.is_supported_source(Path("notes.txt")))

    def test_sources_from_different_folders_keep_local_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first" / "a.mp4"
            second = root / "second" / "b.gif"
            first.parent.mkdir()
            second.parent.mkdir()
            first.touch()
            second.touch()

            app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
            app.settings = SimpleNamespace(output_directory="")
            app.queue = converter_gui.ConversionQueue()
            app.target_dropdown = SimpleNamespace(value="stm32f103-128x64")
            app.logger = SimpleNamespace(event=mock.Mock())
            app._options_for_source = mock.Mock(
                side_effect=lambda source, output, use_current_trim: converter_gui.ConversionOptions(
                    source,
                    output,
                )
            )
            app._refresh_queue_view = mock.Mock()
            app._show_page = mock.Mock()
            app._activate_task = mock.AsyncMock()
            app._show_notice = mock.Mock()

            asyncio.run(app._add_sources([first, second]))

            jobs = app.queue.snapshot()
            self.assertEqual(first.with_suffix(".BIN"), jobs[0].options.output)
            self.assertEqual(second.with_suffix(".BIN"), jobs[1].options.output)

    def test_font_assets_are_added_to_windows_package(self) -> None:
        source = PACKAGE_SOURCE.read_text(encoding="utf-8")
        self.assertIn('--add-data "${assetsPath}:assets"', source)

    def test_release_workflow_keeps_both_windows_packages(self) -> None:
        source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
        self.assertIn("Build portable ZIP and installer", source)
        self.assertIn("subosito/flutter-action@v2", source)
        self.assertIn("package_converter_flutter.ps1", source)
        self.assertIn("OVID_Converter_Windows_x64_Portable_*.zip", source)
        self.assertIn("OVID_Converter_Windows_x64_Setup_*.exe", source)

    def test_full_release_build_compiles_the_drop_extension(self) -> None:
        source = FLUTTER_PACKAGE_SOURCE.read_text(encoding="utf-8")
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        dart = (
            ROOT
            / "tools/extensions/flet_drop_zone/src/flutter/flet_drop_zone/lib/src/flet_drop_zone.dart"
        ).read_text(encoding="utf-8")
        self.assertIn("flet.cli build windows", source)
        self.assertIn('flet-drop-zone = { path = "tools/extensions/flet_drop_zone" }', project)
        self.assertIn('flet-drop-zone = "tools/extensions/flet_drop_zone"', project)
        self.assertIn("DropTarget(", dart)
        self.assertIn("onDragDone", dart)

    def test_interface_does_not_use_common_traditional_variants(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        traditional = "預覽轉換選擇載輸檔關閉儲遞歸縮鋪滿開啟顯處無錯誤資料夾"
        found = sorted({character for character in traditional if character in source})
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
