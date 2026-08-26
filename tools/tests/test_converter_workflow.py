import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class ConverterWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        app = self.app
        app.settings = gui.AppSettings()
        app.preset_store = gui.PresetStore(self.root / "presets.json")
        app.preset_store.upsert(gui.ConversionPreset("Mine", threshold=96))
        app.page = SimpleNamespace(update=mock.Mock(), show_dialog=mock.Mock(), pop_dialog=mock.Mock())
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.pending_trim_range = None
        app.page_index = 0
        app.preview_revision = 0
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.logger = SimpleNamespace(event=mock.Mock())
        app._show_notice = mock.Mock()
        app._show_error = mock.Mock()
        app._refresh_queue_view = mock.Mock()
        app._on_geometry_change = mock.AsyncMock()
        app._build_controls()

    def add_task(self, name="clip.mp4"):
        source = self.root / name
        source.touch()
        job = self.app.queue.add(gui.ConversionOptions(source, source.with_suffix(".BIN")))
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        return job

    def dialog(self):
        return self.app.page.show_dialog.call_args.args[0]

    def test_parameter_management_is_grouped_in_two_menus(self):
        self.assertEqual(3, len(self.app.preset_menu.items))
        self.assertEqual(
            ["standard", "dark-detail", "noise-reduction"],
            [item.data for item in self.app.auto_threshold_menu.items],
        )
        self.assertEqual(10, self.app.preset_dropdown.col)

    def test_manual_edits_show_custom_parameters_instead_of_stale_preset_name(self):
        self.add_task()
        self.assertEqual(gui.BUILTIN_PRESETS[0].name, self.app.preset_dropdown.value)
        self.app.threshold_slider.value = 42
        self.assertTrue(self.app._save_active_task_options())
        self.assertIsNone(self.app.preset_dropdown.value)
        self.app.threshold_slider.value = 128
        self.assertTrue(self.app._save_active_task_options())
        self.assertEqual(gui.BUILTIN_PRESETS[0].name, self.app.preset_dropdown.value)

    async def test_reset_requires_confirmation_and_keeps_task_parameters(self):
        job = self.add_task()
        self.app.threshold_slider.value = 42
        self.app._save_active_task_options()
        options = job.options
        self.app._reset_user_presets(None)
        self.assertEqual(1, len(self.app.preset_store.load_user_presets()))
        self.dialog().actions[-1].on_click(None)
        await asyncio.sleep(0)
        self.assertEqual([], self.app.preset_store.load_user_presets())
        self.assertEqual(options, job.options)
        self.assertEqual(42, self.app.threshold_slider.value)
        self.app._on_geometry_change.assert_not_called()

    def test_delete_targets_the_confirmed_preset_and_can_be_cancelled(self):
        self.app.preset_store.upsert(gui.ConversionPreset("Keep"))
        self.app._refresh_preset_options()
        self.app.preset_dropdown.value = "Mine"
        self.app._delete_selected_preset(None)
        self.assertEqual(2, len(self.app.preset_store.load_user_presets()))
        self.dialog().actions[0].on_click(None)
        self.assertEqual(2, len(self.app.preset_store.load_user_presets()))
        self.app._delete_selected_preset(None)
        self.app.preset_dropdown.value = "Keep"
        self.dialog().actions[-1].on_click(None)
        self.assertEqual(["Keep"], [item.name for item in self.app.preset_store.load_user_presets()])

    def test_save_existing_preset_requires_confirmation(self):
        self.add_task()
        self.app.threshold_slider.value = 64
        self.app._save_preset_dialog(None)
        self.app.preset_name_field.value = "Mine"
        self.app._confirm_save_preset(None)
        self.assertEqual(96, self.app.preset_store.load_user_presets()[0].threshold)
        self.dialog().actions[-1].on_click(None)
        self.assertEqual(64, self.app.preset_store.load_user_presets()[0].threshold)

    def test_clear_presets_remains_safe_with_incomplete_numeric_input(self):
        self.app.fps_field.value = ""
        self.app._reset_user_presets(None)
        self.dialog().actions[-1].on_click(None)
        self.assertEqual([], self.app.preset_store.load_user_presets())
        self.assertEqual("", self.app.fps_field.value)
        self.app._show_error.assert_not_called()

    def test_builtin_preset_cannot_be_overwritten_with_different_case(self):
        preset = gui.replace(gui.BUILTIN_PRESETS[0], name=gui.BUILTIN_PRESETS[0].name.lower())
        with self.assertRaises(ValueError):
            self.app.preset_store.upsert(preset)
        self.assertEqual(["Mine"], [item.name for item in self.app.preset_store.load_user_presets()])

    def test_preset_save_uses_parameters_captured_when_dialog_opened(self):
        self.add_task()
        self.app.threshold_slider.value = 64
        self.app._save_preset_dialog(None)
        self.app.preset_name_field.value = "Snapshot"
        self.app.threshold_slider.value = 200
        self.app._confirm_save_preset(None)
        preset = next(item for item in self.app.preset_store.load_user_presets() if item.name == "Snapshot")
        self.assertEqual(64, preset.threshold)

    def test_can_save_a_parameter_preset_before_importing_media(self):
        self.app.width_field.value = "96"
        self.app._save_preset_dialog(None)
        self.app.preset_name_field.value = "No media"
        self.app._confirm_save_preset(None)
        self.app._show_error.assert_not_called()
        preset = next(item for item in self.app.preset_store.load_user_presets() if item.name == "No media")
        self.assertEqual(96, preset.width)

    async def test_preset_cannot_modify_a_frozen_task(self):
        job = self.add_task()
        self.app.queue.freeze_selected()
        self.app.preset_dropdown.value = "Mine"
        self.app._apply_selected_preset(None)
        await asyncio.sleep(0)
        self.assertEqual(128, self.app.threshold_slider.value)
        self.assertEqual(128, job.options.threshold)
        self.app._on_geometry_change.assert_not_called()

    async def test_invalid_editor_blocks_import_without_adding_partial_jobs(self):
        self.add_task()
        self.app.fps_field.value = ""
        source = self.root / "new.gif"
        source.touch()
        self.app._activate_task = mock.AsyncMock()
        await self.app._add_sources([source])
        self.assertEqual(1, len(self.app.queue.snapshot()))
        self.assertIsNotNone(self.app.fps_field.error)
        self.app._activate_task.assert_not_called()

    async def test_output_picker_result_cannot_change_another_task(self):
        first = self.add_task()
        second = self.app.queue.add(gui.ConversionOptions(self.root / "second.gif", self.root / "second.BIN"))
        async def choose(**_):
            self.app.active_task_id = second.id
            self.app._load_job_controls(second)
            return str(self.root / "chosen.BIN")
        self.app.file_picker = SimpleNamespace(save_file=choose)
        await self.app._choose_output(None)
        self.assertEqual("clip.BIN", first.options.output.name)
        self.assertEqual("second.BIN", second.options.output.name)
        self.assertEqual(str(second.options.output), self.app.output_field.value)

    async def test_output_picker_does_not_modify_task_that_started_converting(self):
        job = self.add_task()
        async def choose(**_):
            self.app.queue.freeze_selected()
            return str(self.root / "chosen.BIN")
        self.app.file_picker = SimpleNamespace(save_file=choose)
        await self.app._choose_output(None)
        self.assertEqual("clip.BIN", job.options.output.name)
        self.assertEqual(str(job.options.output), self.app.output_field.value)


if __name__ == "__main__":
    unittest.main()
