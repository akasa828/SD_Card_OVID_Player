import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui
from converter_services import screen_size_status


class ScreenSizeStatusTests(unittest.TestCase):
    def test_matching_and_smaller_dimensions(self):
        matched = screen_size_status("128", "64", "stm32f103-128x64")
        self.assertFalse(matched.is_error)
        self.assertIn("一致", matched.message)
        self.assertIn("1024 B", matched.message)
        smaller = screen_size_status(96, 31, "stm32f103-128x64")
        self.assertFalse(smaller.is_error)
        self.assertIn("居中", smaller.message)
        self.assertIn("384 B", smaller.message)

    def test_each_axis_is_checked_not_only_total_area(self):
        for width, height in ((129, 1), (1, 65), (129, 65)):
            with self.subTest(width=width, height=height):
                status = screen_size_status(width, height, "stm32f103-128x64")
                self.assertTrue(status.is_error)
                self.assertIn("超过", status.message)

    def test_invalid_dimensions_can_still_be_repaired_with_target_size(self):
        for width, height in (("", "64"), ("128.5", "64"), (0, 64), (256, 64), (128, -1)):
            status = screen_size_status(width, height, "stm32f103-128x32")
            self.assertTrue(status.is_error)
            self.assertIsNone(status.output_size)
            self.assertEqual((128, 32), status.target_size)

    def test_larger_frames_and_odd_heights_use_page_size_without_fixed_limit(self):
        status = screen_size_status(128, 128, "stm32f103-128x128")
        self.assertFalse(status.is_error)
        self.assertIn("2048 B", status.message)
        status = screen_size_status(129, 255, "custom")
        self.assertFalse(status.is_error)
        self.assertIn("4128 B", status.message)
        self.assertIn("未检查", status.message)

    def test_unknown_profile_is_not_presented_as_a_successful_check(self):
        status = screen_size_status(128, 64, "unknown")
        self.assertTrue(status.is_error)
        self.assertIsNone(status.target_size)


class ScreenSizeUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        app = gui.ConverterApp.__new__(gui.ConverterApp)
        app.settings = gui.AppSettings()
        app.preset_store = mock.Mock()
        app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        app.page = SimpleNamespace(update=mock.Mock())
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.page_index = 0
        app._build_controls()
        app.preview_revision = 1
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.preview_playing = False
        app.pending_trim_range = None
        app._refresh_queue_view = mock.Mock()
        app._load_first_preview = mock.AsyncMock()
        app._show_notice = mock.Mock()
        self.app = app

    def add_task(self, name="clip.mp4", **options):
        source = self.root / name
        source.touch()
        job = self.app.queue.add(gui.ConversionOptions(source, source.with_suffix(".BIN"), **options))
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        return job

    def test_selecting_target_updates_hint_but_never_resizes_or_decodes(self):
        job = self.add_task()
        self.app.target_dropdown.value = "stm32f103-128x32"
        self.app.target_dropdown.on_select(None)
        self.assertEqual((128, 64), (job.options.width, job.options.height))
        self.assertEqual("stm32f103-128x32", job.target_profile)
        self.assertIn("超过", self.app.screen_size_hint.value)
        self.assertEqual(gui.ft.Colors.ERROR, self.app.screen_size_hint.color)
        self.assertFalse(self.app.match_target_button.disabled)
        self.app._load_first_preview.assert_not_called()

    async def test_explicit_match_changes_only_active_task_dimensions_and_refreshes_once(self):
        other = self.add_task("other.mp4")
        job = self.add_task(fps=30, threshold=96, trim_start_seconds=1.5, trim_end_seconds=5)
        original = job.options
        self.app.target_dropdown.value = "stm32f103-96x64"
        await self.app.match_target_button.on_click(None)
        self.assertEqual(gui.replace(original, width=96, height=64), job.options)
        self.assertEqual((128, 64), (other.options.width, other.options.height))
        self.assertEqual("stm32f103-96x64", job.target_profile)
        self.app._load_first_preview.assert_awaited_once()
        self.assertTrue(self.app.match_target_button.disabled)
        self.assertIn("一致", self.app.screen_size_hint.value)

    async def test_already_matching_size_is_noop(self):
        job = self.add_task()
        original = job.options
        await self.app._match_target_size(None)
        self.assertIs(original, job.options)
        self.app._load_first_preview.assert_not_called()

    async def test_custom_target_cannot_apply_invented_dimensions(self):
        job = self.add_task()
        self.app.target_dropdown.value = "custom"
        self.app._on_target_profile_change(None)
        self.assertTrue(self.app.match_target_button.disabled)
        self.assertIn("未检查", self.app.screen_size_hint.value)
        await self.app._match_target_size(None)
        self.assertEqual((128, 64), (job.options.width, job.options.height))
        self.app._load_first_preview.assert_not_called()

    async def test_matching_can_repair_empty_width_without_overwriting_other_invalid_fields(self):
        job = self.add_task()
        self.app.width_field.value = ""
        self.app.width_field.error = "请输入整数"
        self.app.fps_field.value = "invalid"
        self.app.target_dropdown.value = "stm32f103-96x64"
        await self.app._match_target_size(None)
        self.assertEqual("96", self.app.width_field.value)
        self.assertIsNone(self.app.width_field.error)
        self.assertEqual("invalid", self.app.fps_field.value)
        self.assertIsNotNone(self.app.fps_field.error)
        self.assertEqual(128, job.options.width)
        self.app._load_first_preview.assert_not_called()

    async def test_empty_editor_updates_without_accessing_source_or_global_defaults(self):
        original = gui.asdict(self.app.settings)
        self.app.target_dropdown.value = "stm32f103-128x32"
        await self.app._match_target_size(None)
        self.assertEqual("32", self.app.height_field.value)
        self.assertEqual(original, gui.asdict(self.app.settings))
        self.assertEqual((), self.app.queue.snapshot())
        self.app._load_first_preview.assert_not_called()

    async def test_typing_dimensions_refreshes_hint_even_before_import(self):
        self.app.width_field.value = "200"
        await self.app.width_field.on_change(None)
        self.assertIn("超过", self.app.screen_size_hint.value)
        self.app.width_field.value = "80"
        await self.app.width_field.on_change(None)
        self.assertIn("居中", self.app.screen_size_hint.value)

    async def test_matching_saves_options_before_a_missing_source_can_fail_preview(self):
        job = self.add_task()
        job.options.source.unlink()
        self.app.target_dropdown.value = "stm32f103-128x32"
        await self.app._match_target_size(None)
        self.assertEqual(32, job.options.height)
        self.assertEqual("stm32f103-128x32", job.target_profile)

    async def test_frozen_task_restores_controls_and_rejects_late_size_events(self):
        job = self.add_task(width=96, height=32)
        job.frozen = True
        self.app.target_dropdown.value = "stm32f103-128x128"
        self.app.width_field.value = "255"
        self.app.fps_field.value = "120"
        self.app._on_target_profile_change(None)
        await self.app._match_target_size(None)
        await self.app._on_geometry_change(None)
        self.assertEqual((96, 32), (job.options.width, job.options.height))
        self.assertEqual(("96", "32", "15"), (self.app.width_field.value, self.app.height_field.value, self.app.fps_field.value))
        self.assertEqual(job.target_profile, self.app.target_dropdown.value)
        self.assertTrue(self.app.match_target_button.disabled)
        self.app._load_first_preview.assert_not_called()

    async def test_freeze_during_debounce_stops_late_preview_reload(self):
        job = self.add_task()
        entered, resume = asyncio.Event(), asyncio.Event()
        async def sleep(_):
            entered.set()
            await resume.wait()
        with mock.patch.object(gui.asyncio, "sleep", side_effect=sleep):
            self.app.width_field.value = "96"
            task = asyncio.create_task(self.app._on_geometry_change(None))
            await entered.wait()
            job.frozen = True
            resume.set()
            await task
        self.assertEqual("128", self.app.width_field.value)
        self.app._load_first_preview.assert_not_called()

    def test_loading_task_and_unlocking_recompute_hint_and_button(self):
        job = self.add_task(width=96, height=32)
        self.assertIn("居中", self.app.screen_size_hint.value)
        self.app._set_editor_locked(True)
        self.assertTrue(self.app.match_target_button.disabled)
        self.app._set_editor_locked(False)
        self.assertFalse(self.app.match_target_button.disabled)
        self.app._load_option_controls(gui.replace(job.options, width=128, height=64), "stm32f103-128x64")
        self.assertIn("一致", self.app.screen_size_hint.value)
        self.assertTrue(self.app.match_target_button.disabled)

    def test_off_page_hint_update_does_not_patch_unmounted_controls(self):
        self.app.page_index = 2
        self.app.width_field.value = "255"
        self.app._update_screen_size_hint()
        self.app.page.update.assert_not_called()
        self.assertIn("超过", self.app.screen_size_hint.value)


if __name__ == "__main__":
    unittest.main()
