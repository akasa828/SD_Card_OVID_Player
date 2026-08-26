import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class ConverterSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        self.app.settings = gui.AppSettings()
        self.app.preset_store = mock.Mock()
        self.app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        self.app.page = SimpleNamespace(update=mock.Mock())
        self.app.queue = gui.ConversionQueue()
        self.app.active_task_id = None
        self.app.pending_trim_range = None
        self.app.page_index = 2
        self.app.preview_revision = 0
        self.app.preview_render_revision = 0
        self.app.preview_playback_revision = 0
        self.app.preview_needs_reload = False
        self.app._show_error = mock.Mock()
        self.app._show_message = mock.Mock()
        self.app._show_notice = mock.Mock()
        self.app._apply_theme = mock.Mock()
        self.app._refresh_queue_view = mock.Mock()
        self.app._build_controls()

    def add_task(self):
        options = gui.ConversionOptions(
            Path("clip.mp4"), Path("clip.BIN"), width=96, fps=30,
            workers=1, fast_video=True, trim_start_seconds=2, trim_end_seconds=8,
        )
        job = self.app.queue.add(options, target_profile="stm32f103-96x64")
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        return job

    def test_task_performance_options_do_not_modify_global_defaults(self):
        before = replace(self.app.settings)
        job = self.add_task()
        self.assertEqual(before, self.app.settings)
        self.assertEqual(job.options, self.app._options())

    async def test_preset_performance_options_do_not_modify_defaults(self):
        before = replace(self.app.settings)
        preset = gui.ConversionPreset("Fast", workers=4, fast_video=True)
        self.app.preset_store.all_presets.return_value = [*gui.BUILTIN_PRESETS, preset]
        self.add_task()
        self.app._on_geometry_change = mock.AsyncMock()
        self.app.preset_dropdown.value = preset.name
        self.app._apply_selected_preset(None)
        await asyncio.sleep(0)
        self.assertEqual(before, self.app.settings)
        self.assertEqual(4, self.app._options().workers)
        self.assertTrue(self.app._options().fast_video)

    def test_task_performance_controls_save_without_reloading_preview(self):
        job = self.add_task()
        self.app.task_worker_dropdown.value = "3"
        self.app.task_fast_video_switch.value = False
        self.app.task_worker_dropdown.on_select(None)
        self.assertEqual(3, job.options.workers)
        self.assertFalse(job.options.fast_video)
        self.assertEqual(0, self.app.settings.workers)

    def test_saving_defaults_does_not_unlock_or_modify_frozen_task(self):
        job = self.add_task()
        options = job.options
        self.app.queue.freeze_selected()
        self.app._set_editor_locked(True)
        self.app.default_fps.value = "60"
        with mock.patch.object(gui, "save_settings"):
            self.app._save_settings(None)
        self.assertEqual(options, job.options)
        self.assertEqual(options, self.app._options())
        self.assertTrue(self.app.parameter_card.disabled)
        self.assertTrue(self.app.task_worker_dropdown.disabled)

    def test_saving_defaults_preserves_completed_task_and_current_preview(self):
        job = self.add_task()
        job.state = "completed"
        job.summary = mock.sentinel.summary
        options = job.options
        self.app.default_width.value = "128"
        self.app.default_height.value = "32"
        self.app.default_fps.value = "60"
        self.app.worker_dropdown.value = "4"
        self.app.fast_video_switch.value = False
        with mock.patch.object(gui, "save_settings") as save:
            self.app._save_settings(None)
        save.assert_called_once()
        self.assertEqual(options, self.app._options())
        self.assertEqual(options, job.options)
        self.assertEqual("completed", job.state)
        self.assertIs(mock.sentinel.summary, job.summary)
        self.assertFalse(self.app.preview_needs_reload)
        self.assertEqual("stm32f103-128x64", self.app.settings.target_profile)
        self.assertEqual(60, self.app.settings.fps)
        self.app._show_error.assert_not_called()

    def test_failed_settings_save_keeps_previous_defaults(self):
        before = replace(self.app.settings)
        self.app.default_fps.value = "60"
        with mock.patch.object(gui, "save_settings", side_effect=OSError("read only")):
            self.app._save_settings(None)
        self.assertEqual(before, self.app.settings)
        self.app._apply_theme.assert_not_called()
        self.app._show_error.assert_called_once()

    def test_saved_defaults_update_empty_editor_only(self):
        self.app.default_height.value = "32"
        self.app.default_fps.value = "60"
        with mock.patch.object(gui, "save_settings"):
            self.app._save_settings(None)
        options = self.app._options_for_source(Path("new.png"), Path("new.BIN"))
        self.assertEqual(32, options.height)
        self.assertEqual(60, options.fps)

    def test_corrupt_settings_document_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for value in ([], None, 42, "text"):
                with self.subTest(value=value), mock.patch.object(gui, "settings_file", return_value=path):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    self.assertEqual(gui.AppSettings(), gui.load_settings())


if __name__ == "__main__":
    unittest.main()
