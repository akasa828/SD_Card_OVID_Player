import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
GUI_SOURCE = ROOT / "tools" / "ovid_converter_gui.py"
PACKAGE_SOURCE = ROOT / "tools" / "package_converter.ps1"
WORKFLOW_SOURCE = ROOT / ".github" / "workflows" / "release-assets.yml"
FONT_ROOT = ROOT / "tools" / "assets" / "fonts"
BUILD_BATCH = ROOT / "Build_OVID_Converter.bat"

sys.path.insert(0, str(TOOLS_DIR))
import ovid_converter_gui as converter_gui  # noqa: E402


class ConverterGuiTests(unittest.TestCase):
    def test_convert_page_does_not_repeat_the_app_purpose_as_a_title(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("把素材直接转换成 OLED 可以播放的 OVID 文件", source)

    def test_preview_image_keeps_the_previous_frame_while_decoding(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("gapless_playback=True", source)
        self.assertIn("self.page.update(self.preview_image, self.preview_label)", source)

    def test_threshold_has_live_preview_and_help_text(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn("on_change=self._on_threshold_change", source)
        self.assertIn("建议先使用 128", source)
        self.assertIn("常用范围为 96–160", source)

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
            ):
                self.assertEqual((b"frame", 1), await asyncio.to_thread(session.next_frame))
                with self.assertRaises(converter_gui.PreviewFinished) as raised:
                    await asyncio.to_thread(session.next_frame)
                self.assertEqual("已到最后一帧", str(raised.exception))

        asyncio.run(consume_preview())

    def test_current_frame_can_be_rerendered_without_reopening_source(self) -> None:
        session = converter_gui.PreviewSession()
        session.options = converter_gui.ConversionOptions(
            source=Path("source.png"),
            output=Path("output.bin"),
        )
        session.frames = [object()]
        session.index = 0
        with mock.patch.object(converter_gui, "preview_prepared_png", return_value=b"updated"):
            data, index = session.rerender_current("threshold", 96, True)
        self.assertEqual((b"updated", 1), (data, index))
        self.assertEqual("threshold", session.options.dither)
        self.assertEqual(96, session.options.threshold)
        self.assertTrue(session.options.invert)

    def test_compact_navigation_matches_the_three_pages(self) -> None:
        self.assertEqual(("转换", "设置", "关于"), tuple(label for _, label in converter_gui.NAVIGATION_ITEMS))

        app = converter_gui.ConverterApp.__new__(converter_gui.ConverterApp)
        app.convert_page = object()
        app.settings_page = object()
        app.about_page = object()
        app.page_host = SimpleNamespace(content=None)
        app.navigation_rail = SimpleNamespace(selected_index=None)
        app.navigation_bar = SimpleNamespace(selected_index=None)
        app.page = SimpleNamespace(schedule_update=lambda: None)
        app._show_page(99)

        self.assertEqual(0, app.page_index)
        self.assertIs(app.convert_page, app.page_host.content)
        self.assertEqual(0, app.navigation_rail.selected_index)
        self.assertEqual(0, app.navigation_bar.selected_index)

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
        layout = source.index("ConverterApp(page)")
        centered = source.index("await page.window.center()")
        self.assertLess(layout, centered)

    def test_font_assets_are_added_to_windows_package(self) -> None:
        source = PACKAGE_SOURCE.read_text(encoding="utf-8")
        self.assertIn('--add-data "${assetsPath}:assets"', source)

    def test_release_workflow_keeps_both_windows_packages(self) -> None:
        source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
        self.assertIn("Build portable ZIP and installer", source)
        self.assertIn("OVID_Converter_Windows_x64_Portable_*.zip", source)
        self.assertIn("OVID_Converter_Windows_x64_Setup_*.exe", source)

    def test_interface_does_not_use_common_traditional_variants(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        traditional = "預覽轉換選擇載輸檔關閉儲遞歸縮鋪滿開啟顯處無錯誤資料夾"
        found = sorted({character for character in traditional if character in source})
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
