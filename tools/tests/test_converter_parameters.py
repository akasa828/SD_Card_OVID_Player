import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class ConverterParameterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        app = self.app
        app.settings = gui.AppSettings()
        app.preset_store = mock.Mock()
        app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        app.page = SimpleNamespace(update=mock.Mock())
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.pending_trim_range = None
        app.page_index = 0
        app.preview_revision = 0
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app._show_notice = mock.Mock()
        app._refresh_queue_view = mock.Mock()
        app._rerender_current_preview = mock.AsyncMock()
        app._on_geometry_change = mock.AsyncMock()
        app._build_controls()

    def add_task(self, **kwargs):
        job = self.app.queue.add(gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"), **kwargs))
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        return job

    def test_threshold_number_is_visible_and_defaults_to_128(self):
        self.assertEqual("128", self.app.threshold_field.value)
        self.assertFalse(self.app.threshold_field.disabled)
        self.assertIsNotNone(self.app.threshold_field.on_change)

    async def test_typed_threshold_updates_task_slider_and_preview(self):
        job = self.add_task()
        for value in (0, 96, 255):
            with self.subTest(value=value):
                self.app.threshold_field.value = str(value)
                await self.app.threshold_field.on_change(None)
                self.assertEqual(value, job.options.threshold)
                self.assertEqual(value, self.app.threshold_slider.value)
                self.assertIsNone(self.app.threshold_field.error)
        self.assertEqual(3, self.app._rerender_current_preview.await_count)

    async def test_slider_changes_also_update_the_number_field(self):
        job = self.add_task()
        self.app.threshold_slider.value = 64
        await self.app.threshold_slider.on_change(None)
        self.assertEqual("64", self.app.threshold_field.value)
        self.assertEqual(64, job.options.threshold)

    async def test_threshold_controls_stay_in_sync_while_other_numbers_are_invalid(self):
        job = self.add_task()
        self.app.fps_field.value = ""
        self.app.threshold_field.value = "200"
        await self.app.threshold_field.on_change(None)
        self.assertEqual(200, self.app.threshold_slider.value)
        self.assertEqual(128, job.options.threshold)
        self.app.fps_field.value = "15"
        self.assertTrue(self.app._save_active_task_options())
        self.assertEqual(200, job.options.threshold)

    async def test_invalid_threshold_never_silently_converts_with_old_value(self):
        job = self.add_task()
        for value in ("", "256", "-1", "text", "12.5"):
            with self.subTest(value=value):
                self.app.threshold_field.value = value
                await self.app.threshold_field.on_change(None)
                self.assertIsNotNone(self.app.threshold_field.error)
                self.assertFalse(self.app._save_editor_before_action())
                self.assertEqual(128, job.options.threshold)
                self.assertEqual(128, self.app.threshold_slider.value)
        self.app._rerender_current_preview.assert_not_called()
        self.app.threshold_field.value = "64"
        await self.app.threshold_field.on_change(None)
        self.assertIsNone(self.app.threshold_field.error)
        self.assertTrue(self.app._save_editor_before_action())
        self.assertEqual(64, job.options.threshold)

    async def test_floyd_disables_threshold_and_clears_unusable_draft(self):
        job = self.add_task(threshold=96)
        self.app.threshold_field.value = ""
        await self.app.threshold_field.on_change(None)
        self.app.dither_control.selected = ["floyd"]
        await self.app.dither_control.on_change(None)
        self.assertEqual("96", self.app.threshold_field.value)
        self.assertIsNone(self.app.threshold_field.error)
        self.assertTrue(self.app.threshold_field.disabled)
        self.assertTrue(self.app.threshold_slider.disabled)
        self.assertEqual("floyd", job.options.dither)
        self.assertTrue(self.app._save_editor_before_action())
        self.app.dither_control.selected = ["threshold"]
        await self.app.dither_control.on_change(None)
        self.assertFalse(self.app.threshold_field.disabled)
        self.assertEqual(96, job.options.threshold)

    async def test_frozen_task_ignores_delayed_threshold_events(self):
        job = self.add_task(threshold=96)
        self.app.queue.freeze_selected()
        self.app._set_editor_locked(True)
        self.assertTrue(self.app.threshold_field.disabled)
        self.app.threshold_field.value = "200"
        await self.app.threshold_field.on_change(None)
        self.app.threshold_slider.value = 220
        await self.app.threshold_slider.on_change(None)
        self.app.dither_control.selected = ["floyd"]
        await self.app.dither_control.on_change(None)
        self.app.invert_switch.value = True
        await self.app.invert_switch.on_change(None)
        self.assertEqual(96, job.options.threshold)
        self.assertEqual(96, self.app.threshold_slider.value)
        self.assertEqual("96", self.app.threshold_field.value)
        self.assertEqual(["threshold"], self.app.dither_control.selected)
        self.assertFalse(self.app.invert_switch.value)
        self.assertFalse(job.options.invert)
        self.app._rerender_current_preview.assert_not_called()

    async def test_delayed_slider_event_does_not_change_floyds_saved_threshold(self):
        job = self.add_task(dither="floyd", threshold=96)
        self.app.threshold_slider.value = 220
        await self.app.threshold_slider.on_change(None)
        self.assertEqual(96, self.app.threshold_slider.value)
        self.assertEqual(96, job.options.threshold)
        self.app._rerender_current_preview.assert_not_called()

    async def test_loading_another_task_and_preset_synchronizes_both_controls(self):
        self.add_task(threshold=72)
        self.assertEqual("72", self.app.threshold_field.value)
        preset = gui.ConversionPreset("Dithered", dither="floyd", threshold=144)
        self.app.preset_store.all_presets.return_value = [preset]
        self.app.preset_dropdown.value = preset.name
        self.app._apply_selected_preset(None)
        await asyncio.sleep(0)
        self.assertEqual("144", self.app.threshold_field.value)
        self.assertEqual(144, self.app.threshold_slider.value)
        self.assertTrue(self.app.threshold_field.disabled)

    def test_device_screen_is_explicitly_a_check_not_an_output_resize(self):
        job = self.add_task()
        self.assertIn("输出", self.app.width_field.label)
        self.assertIn("输出", self.app.height_field.label)
        self.assertIn("兼容性检查", self.app.target_dropdown.label)
        self.app.target_dropdown.value = "stm32f103-96x64"
        self.app.target_dropdown.on_select(None)
        self.assertEqual(128, job.options.width)
        self.assertEqual("stm32f103-96x64", job.target_profile)


if __name__ == "__main__":
    unittest.main()
