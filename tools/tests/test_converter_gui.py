import asyncio
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
    def test_timestamps_use_consistent_centisecond_format(self) -> None:
        self.assertEqual("00:00.00", converter_gui.format_timestamp(0))
        self.assertEqual("01:02.35", converter_gui.format_timestamp(62.345))
        self.assertEqual("01:01:01.25", converter_gui.format_timestamp(3661.25))
        self.assertEqual("--:--.--", converter_gui.format_timestamp(None))

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
        session.options = object()
        session.iterator = iter([object()])

        async def consume_preview() -> None:
            with (
                mock.patch.object(converter_gui, "prepare_monochrome_source", return_value=object()),
                mock.patch.object(converter_gui, "preview_prepared_png", return_value=b"frame"),
                mock.patch.object(converter_gui, "source_preview_png", return_value=b"source"),
            ):
                self.assertEqual((b"source", b"frame", 1), await asyncio.to_thread(session.next_frame))
                with self.assertRaises(converter_gui.PreviewFinished) as raised:
                    await asyncio.to_thread(session.next_frame)
                self.assertEqual("已到最后一帧", str(raised.exception))

        asyncio.run(consume_preview())
        session.close()

    def test_preview_prefetch_reuses_duplicate_video_frames(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = object()
        shared = object()
        unique = object()
        session.iterator = iter([shared, shared, unique])
        session.prefetch_limit = 3
        prepared: list[object] = []

        def prepare(image):
            prepared.append(image)
            return str(id(image)).encode(), image

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
        session.frames = [(b"source", object())]
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
