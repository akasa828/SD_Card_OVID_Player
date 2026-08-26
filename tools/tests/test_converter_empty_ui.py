import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class EmptyConverterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.page = SimpleNamespace(
            width=1120, height=760, update=mock.Mock(), services=[],
            show_dialog=mock.Mock(side_effect=lambda dialog: setattr(dialog, "open", True)),
        )
        self.presets = gui.PresetStore(self.root / "presets.json")
        self.session = SimpleNamespace(load=lambda: ([], None), save=mock.Mock())
        with (
            mock.patch.object(gui, "load_settings", return_value=gui.AppSettings()),
            mock.patch.object(gui, "PresetStore", return_value=self.presets),
            mock.patch.object(gui, "QueueSessionStore", return_value=self.session),
            mock.patch.object(gui, "ConversionLogger", return_value=mock.Mock()),
            mock.patch.object(gui.ConverterApp, "_configure_page"),
        ):
            self.app = gui.ConverterApp(self.page)
        self.app._show_notice = mock.Mock()
        self.app._show_error = mock.Mock()
        self.page.update.reset_mock()

    async def asyncTearDown(self):
        tasks = [value for value in vars(self.app).values() if isinstance(value, asyncio.Task)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(self.app.preview.close)

    def image(self, name="sample.png"):
        path = self.root / name
        Image.new("RGB", (16, 12), "white").save(path)
        return path

    def assert_empty(self):
        app = self.app
        self.assertTrue(app.queue_empty_state.visible)
        self.assertTrue(app.empty_parameters_button.visible)
        for control in (app.preview_card, app.parameter_card, app.editor_row, app.source_paths, app.task_card, app.task_bar):
            self.assertFalse(control.visible, type(control).__name__)
        self.assertTrue(app.convert_button.disabled)

    def test_first_launch_is_focused_on_import(self):
        self.assert_empty()
        self.assertEqual(gui.ft.MainAxisAlignment.CENTER, self.app.source_actions.alignment)
        self.assertIsInstance(self.app.source_actions.controls[0], gui.ft.FilledButton)
        self.assertIsInstance(self.app.source_actions.controls[1], gui.ft.OutlinedButton)
        self.assertEqual(gui.ft.MainAxisAlignment.CENTER, self.app.empty_parameters_entry.alignment)
        self.assertEqual("先设置转换参数", self.app.empty_parameters_button.content)
        self.assertIn(self.app.queue_empty_state, self.app.convert_scroll.controls[0].content.content.controls)
        self.assertNotIn(self.app.queue_empty_state, self.app.task_card.content.content.controls)

    def test_empty_parameters_can_be_opened_without_preview_or_task_actions(self):
        app = self.app
        app.empty_parameters_button.on_click(None)
        self.assertTrue(app.parameter_card.visible)
        self.assertTrue(app.editor_row.visible)
        self.assertEqual(12, app.parameter_card.col)
        self.assertEqual("新素材参数", app.editor_task_name.value)
        for control in (app.preview_card, app.source_paths, app.task_card, app.task_bar, app.apply_selected_button):
            self.assertFalse(control.visible)
        self.page.update.assert_called_once_with(app.convert_page)

    def test_hide_and_reopen_preserves_pending_parameters(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.width_field.value = "96"
        app._set_threshold_value(75)
        app._toggle_empty_parameters(None)
        app._toggle_empty_parameters(None)
        self.assertEqual("96", app.width_field.value)
        self.assertEqual(75, app.threshold_slider.value)
        self.assertTrue(app.parameter_card.visible)

    def test_empty_parameter_editor_can_save_presets(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.width_field.value = "96"
        app._save_preset_dialog(None)
        dialog = self.page.show_dialog.call_args.args[0]
        dialog.content.value = "Before import"
        dialog.actions[-1].on_click(None)
        presets = self.presets.load_user_presets()
        self.assertEqual(1, len(presets))
        self.assertEqual(("Before import", 96), (presets[0].name, presets[0].width))
        self.assertFalse(app.preview_card.visible)

    async def test_real_image_import_shows_editor_and_keeps_preconfigured_options(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.width_field.value = "96"
        app._set_threshold_value(75)
        await app._add_sources([self.image()])
        self.assertEqual(1, len(app.queue.snapshot()))
        job = app.queue.find(app.active_task_id)
        self.assertEqual((96, 75), (job.options.width, job.options.threshold))
        self.assertEqual(96, app.preview_snapshot.width)
        self.assertFalse(app.empty_editor_expanded)
        self.assertFalse(app.queue_empty_state.visible)
        self.assertFalse(app.empty_parameters_button.visible)
        self.assertFalse(app.empty_parameters_entry.visible)
        self.assertFalse(app.trim_controls.visible)
        for control in (app.preview_card, app.parameter_card, app.source_paths, app.task_card, app.task_bar):
            self.assertTrue(control.visible)
        self.assertEqual((6, 6), (app.preview_card.col, app.parameter_card.col))
        app._show_error.assert_not_called()

    async def test_multiple_imports_share_preconfigured_options_then_edit_independently(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.fps_field.value = "30"
        await app._add_sources([self.image("one.png"), self.image("two.png")])
        jobs = app.queue.snapshot()
        self.assertEqual([30, 30], [job.options.fps for job in jobs])
        app.fps_field.value = "15"
        app._save_active_task_options()
        self.assertEqual([15, 30], [job.options.fps for job in jobs])
        self.assertTrue(app.task_bar.visible)

    async def test_last_task_removal_restores_welcome_and_resets_old_progress(self):
        app = self.app
        await app._add_sources([self.image()])
        app.progress_text.value = "本轮完成：1/1"
        app.progress_bar.value = 1
        app._remove_queue_job(app.active_task_id)
        await app.preview_close_task
        self.assert_empty()
        self.assertEqual("", app.progress_text.value)
        self.assertEqual(0, app.progress_bar.value)
        self.assertIsNone(app.preview_snapshot)
        self.assertEqual("128", app.width_field.value)

    async def test_clear_completed_restores_welcome_without_deleting_media(self):
        app = self.app
        source = self.image()
        await app._add_sources([source])
        job = app.queue.find(app.active_task_id)
        job.state = "completed"
        app._clear_completed_jobs(None)
        await app.preview_close_task
        self.assert_empty()
        self.assertTrue(source.exists())

    def test_restored_tasks_are_visible_before_preview_activation(self):
        app = self.app
        app.queue.add(gui.ConversionOptions(self.image(), self.root / "out.BIN"))
        app._refresh_queue_view()
        self.assertTrue(app.task_card.visible)
        self.assertTrue(app.task_bar.visible)
        self.assertFalse(app.queue_empty_state.visible)
        self.assertFalse(app.empty_parameters_button.visible)
        self.assertFalse(app.preview_card.visible)
        self.assertFalse(app.parameter_card.visible)

    def test_noop_refresh_does_not_update_hidden_sections(self):
        self.app._refresh_queue_view()
        self.page.update.assert_not_called()

    def test_background_refresh_updates_state_but_not_detached_page(self):
        app = self.app
        app._show_page(2)
        self.page.update.reset_mock()
        app.queue.add(gui.ConversionOptions(self.image(), self.root / "out.BIN"))
        app._refresh_queue_view()
        self.assertTrue(app.task_card.visible)
        self.page.update.assert_not_called()
        app._show_page(0)
        self.assertIs(app.convert_page, app.page_host.content)
        self.assertTrue(app.task_card.visible)

    async def test_empty_parameters_toggle_ignores_stale_click_after_import(self):
        app = self.app
        await app._add_sources([self.image()])
        self.page.update.reset_mock()
        app._toggle_empty_parameters(None)
        self.page.update.assert_not_called()
        self.assertTrue(app.preview_card.visible)
        self.assertTrue(app.parameter_card.visible)

    async def test_invalid_hidden_parameters_reopen_before_import(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.fps_field.value = ""
        app._toggle_empty_parameters(None)
        await app._add_sources([self.image()])
        self.assertTrue(app.parameter_card.visible)
        self.assertIsNotNone(app.fps_field.error)
        self.assertEqual((), app.queue.snapshot())
        self.assertFalse(app.task_bar.visible)
        app.fps_field.value = "15"
        await app._add_sources([self.image()])
        self.assertEqual(1, len(app.queue.snapshot()))

    def test_parameter_only_layout_remains_full_width_at_all_window_sizes(self):
        app = self.app
        app._toggle_empty_parameters(None)
        for width in (680, 800, 1120, 1600):
            with self.subTest(width=width):
                app._resize_editor_panels(width, 760, width < 800)
                self.assertEqual(12, app.parameter_card.col)
                self.assertFalse(app.preview_card.visible)
                self.assertIsNone(app.parameter_card.content.content.scroll)

    async def test_late_parameter_events_do_not_patch_hidden_controls(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app._toggle_empty_parameters(None)
        self.page.update.reset_mock()
        app.threshold_field.value = "96"
        await app._on_threshold_input_change(None)
        app.dither_control.selected = ["floyd"]
        await app._on_dither_change(None)
        app.target_dropdown.value = "stm32f103-96x64"
        await app._match_target_size(None)
        self.page.update.assert_not_called()
        self.assertEqual("96", app.width_field.value)
        self.assertEqual("96", app.threshold_field.value)
        app._toggle_empty_parameters(None)
        self.assertEqual(["floyd"], app.dither_control.selected)

    async def test_cancelled_picker_preserves_empty_parameter_draft(self):
        app = self.app
        app._toggle_empty_parameters(None)
        app.fps_field.value = "30"
        app.file_picker = SimpleNamespace(pick_files=mock.AsyncMock(return_value=[]))
        await app._choose_file(None)
        self.assertTrue(app.parameter_card.visible)
        self.assertFalse(app.preview_card.visible)
        self.assertEqual("30", app.fps_field.value)
        self.assertEqual((), app.queue.snapshot())

    def test_empty_resize_does_not_patch_invisible_preview_images(self):
        app = self.app
        app.page.window = SimpleNamespace(width=1120, height=760)
        app.page.navigation_bar = None
        app._on_resize()
        self.page.update.reset_mock()
        app.page.height = 700
        app._on_resize()
        self.page.update.assert_not_called()
        self.assertEqual(app.original_preview_image.height, app.preview_image.height)

    async def test_clearing_tasks_from_another_page_does_not_patch_converter(self):
        app = self.app
        await app._add_sources([self.image()])
        job = app.queue.find(app.active_task_id)
        job.state = "completed"
        app._show_page(1)
        self.page.update.reset_mock()
        app._clear_completed_jobs(None)
        await app.preview_close_task
        self.page.update.assert_not_called()
        self.assert_empty()


if __name__ == "__main__":
    unittest.main()
