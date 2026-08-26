import asyncio
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class TimelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = gui.ConverterApp.__new__(gui.ConverterApp)
        app.settings = gui.AppSettings()
        app.preset_store = mock.Mock()
        app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        app.page = SimpleNamespace(update=mock.Mock(), show_dialog=mock.Mock(), pop_dialog=mock.Mock())
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.page_index = 0
        app._build_controls()
        app.pending_trim_range = None
        app.preview_revision = 1
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.preview_playing = False
        app.preview_timeline_dragging = False
        app.trim_dragging = False
        app.resume_preview_after_drag = False
        app.trim_label_task = None
        app.preview_time_task = None
        app.preview_lock = asyncio.Lock()
        app.source_info_key = None
        app.source_info = SimpleNamespace(kind="video", duration_seconds=12.8, frame_count=192)
        app.preview = mock.Mock()
        app.preview.next_frame.return_value = (b"original", b"frame", 1)
        options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"))
        self.job = app.queue.add(options)
        app.active_task_id = self.job.id
        app.source_field.value = str(options.source)
        app.output_field.value = str(options.output)
        app.preview.options = options
        app._configure_trim_timeline(app.source_info)
        app._show_error = mock.Mock()
        app._show_notice = mock.Mock()
        app._refresh_queue_view = mock.Mock()
        app.page.update.reset_mock()
        self.app = app

    def test_preview_frame_cannot_overwrite_drag_time_label(self):
        app = self.app
        app.preview_timeline_dragging = True
        app.preview_timeline.value = 8.5
        app.preview_time_label.value = "00:08.50 / 00:12.80"
        app._set_preview_frame(b"old", b"old", "previous", index=1)
        self.assertEqual(8.5, app.preview_timeline.value)
        self.assertEqual("00:08.50 / 00:12.80", app.preview_time_label.value)

    def test_frame_time_accounts_for_output_grid_and_skipped_frames(self):
        app = self.app
        app.preview.options = gui.replace(self.job.options, trim_start_seconds=2.51, skip_frames=3)
        app._set_preview_frame(b"source", b"frame", "first", index=1)
        self.assertAlmostEqual(41 / 15, app.preview_timeline.value)
        self.assertEqual("00:02.73 / 00:12.80", app.preview_time_label.value)

    def test_metadata_loading_off_page_does_not_patch_detached_controls(self):
        self.app.page_index = 2
        self.app._configure_trim_timeline(self.app.source_info)
        self.app.page.update.assert_not_called()
        self.assertEqual(12.8, self.app.trim_slider.max)

    async def test_delayed_timeline_labels_do_not_patch_off_page(self):
        app = self.app
        app.page_index = 2
        await app._flush_trim_label()
        await app._flush_preview_time_label()
        app.page.update.assert_not_called()

    async def test_seek_releases_drag_before_rendering_actual_position(self):
        app = self.app
        app.preview_timeline_dragging = True
        app.trim_slider.start_value, app.trim_slider.end_value = 2.5, 5.0
        app._source_info_for_options = mock.AsyncMock(return_value=SimpleNamespace(frame_count=1))
        app.preview.reset.side_effect = lambda options, _: setattr(app.preview, "options", options)
        await app._preview_seek(SimpleNamespace(control=SimpleNamespace(value=12.8)))
        self.assertFalse(app.preview_timeline_dragging)
        self.assertAlmostEqual(74 / 15, app.preview_timeline.value)
        self.assertEqual("00:04.93 / 00:12.80", app.preview_time_label.value)

    async def test_frozen_task_ignores_late_range_event(self):
        app = self.app
        self.job.frozen = True
        app.trim_slider.start_value, app.trim_slider.end_value = 4, 8
        app._load_first_preview = mock.AsyncMock()
        await app._on_trim_change(None)
        app._load_first_preview.assert_not_awaited()
        self.assertEqual((0, 12.8), (app.trim_slider.start_value, app.trim_slider.end_value))

    async def test_empty_crop_does_not_replace_last_valid_range(self):
        app = self.app
        app._load_first_preview = mock.AsyncMock()
        app.trim_slider.start_value = app.trim_slider.end_value = 4
        await app._on_trim_change(None)
        app._load_first_preview.assert_not_awaited()
        self.assertEqual((0, 12.8), (app.trim_slider.start_value, app.trim_slider.end_value))
        self.assertIsNotNone(app.trim_error.value)
        self.assertTrue(app.trim_error.visible)
        app._show_error.assert_not_called()

    def test_second_drag_preserves_original_playing_state(self):
        app = self.app
        app.preview_playing = True
        app._preview_drag_start(None)
        app._preview_drag_start(None)
        self.assertTrue(app.resume_preview_after_drag)

    def test_timestamp_parser_accepts_seconds_minutes_and_hours(self):
        for text, expected in (("2.5", 2.5), (" 00:02.50 ", 2.5), ("01:02:03.45", 3723.45), ("90:00", 5400)):
            with self.subTest(text=text):
                self.assertEqual(expected, gui.parse_timestamp(text))

    def test_timestamp_parser_rejects_ambiguous_or_invalid_values(self):
        for text in ("", "-2", "nan", "inf", "2,5", "00:60", "1:60:00", "1:2:3:4", "2e3", ":20"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    gui.parse_timestamp(text)

    def dialog(self):
        self.app._edit_trim_dialog(None)
        dialog = self.app.page.show_dialog.call_args.args[0]
        return dialog, dialog.content.controls[1], dialog.content.controls[2]

    def test_crop_dialog_has_one_scroll_region_and_fixed_actions(self):
        dialog, start, end = self.dialog()
        self.assertTrue(dialog.scrollable)
        self.assertIsNone(dialog.content.scroll)
        self.assertTrue(dialog.content.tight)
        self.assertFalse(start.expand)
        self.assertFalse(end.expand)
        self.assertEqual(["取消", "应用范围"], [button.content for button in dialog.actions])

    async def test_precise_crop_applies_only_when_confirmed_and_saves_before_decode(self):
        app = self.app
        dialog, start, end = self.dialog()
        start.value, end.value = "00:02.50", "8.25"
        self.assertEqual(0, self.job.options.trim_start_seconds)
        async def load():
            self.assertEqual((2.5, 8.25), (self.job.options.trim_start_seconds, self.job.options.trim_end_seconds))
        app._load_first_preview = mock.AsyncMock(side_effect=load)
        await dialog.actions[-1].on_click(None)
        app._load_first_preview.assert_awaited_once()
        app.page.pop_dialog.assert_called_once()
        self.assertFalse(app.trim_error.visible)

    async def test_precise_crop_keeps_invalid_values_in_dialog(self):
        app = self.app
        app._load_first_preview = mock.AsyncMock()
        dialog, start, end = self.dialog()
        start.value, end.value = "bad", "1:90"
        await dialog.actions[-1].on_click(None)
        self.assertIsNotNone(start.error)
        self.assertIsNotNone(end.error)
        start.value, end.value = "0.01", "0.02"
        await dialog.actions[-1].on_click(None)
        self.assertIsNone(start.error)
        self.assertIsNone(end.error)
        self.assertTrue(dialog.content.controls[-1].visible)
        app._load_first_preview.assert_not_awaited()
        app.page.pop_dialog.assert_not_called()
        self.assertEqual(0, self.job.options.trim_start_seconds)

    async def test_unchanged_display_times_preserve_exact_range_and_completed_record(self):
        app = self.app
        self.job.options = gui.replace(self.job.options, trim_start_seconds=2.7333333333333334, trim_end_seconds=12.7999)
        self.job.state = "completed"
        app._restore_trim_range()
        original = self.job.options
        app._load_first_preview = mock.AsyncMock()
        dialog, _, _ = self.dialog()
        await dialog.actions[-1].on_click(None)
        self.assertEqual(original, self.job.options)
        self.assertEqual("completed", self.job.state)
        app._load_first_preview.assert_not_awaited()

    async def test_old_dialog_cannot_modify_changed_or_frozen_task(self):
        app = self.app
        app._load_first_preview = mock.AsyncMock()
        for change in ("revision", "frozen", "active"):
            with self.subTest(change=change):
                app.active_task_id, self.job.frozen = self.job.id, False
                dialog, start, _ = self.dialog()
                start.value = "2.5"
                if change == "revision":
                    app.preview_revision += 1
                elif change == "frozen":
                    self.job.frozen = True
                else:
                    app.active_task_id = "different"
                await dialog.actions[-1].on_click(None)
                self.assertEqual(0, self.job.options.trim_start_seconds)
        app._load_first_preview.assert_not_awaited()
        self.assertEqual(3, app._show_notice.call_count)

    async def test_current_frame_end_includes_that_frame(self):
        app = self.app
        app.preview_timeline.value = 2.0
        app._load_first_preview = mock.AsyncMock()
        await app._trim_at_playhead(SimpleNamespace(control=SimpleNamespace(data="end")))
        self.assertAlmostEqual(2 + 1 / 15, self.job.options.trim_end_seconds)
        app._load_first_preview.assert_awaited_once()

    async def test_invalid_fps_in_frame_end_action_does_not_escape_event_handler(self):
        app = self.app
        app.fps_field.value = ""
        app._load_first_preview = mock.AsyncMock()
        await app._trim_at_playhead(SimpleNamespace(control=SimpleNamespace(data="end")))
        app._load_first_preview.assert_not_awaited()
        self.assertIsNotNone(app.fps_field.error)
        app._show_notice.assert_called_once()

    async def test_cancelled_dialog_ignores_delayed_apply_event(self):
        app = self.app
        dialog, start, _ = self.dialog()
        start.value = "2.5"
        app._load_first_preview = mock.AsyncMock()
        dialog.actions[0].on_click(None)
        await dialog.actions[-1].on_click(None)
        app.page.pop_dialog.assert_called_once()
        app._load_first_preview.assert_not_awaited()

    async def test_double_apply_does_not_dismiss_a_new_dialog_or_reload_twice(self):
        app = self.app
        dialog, start, _ = self.dialog()
        start.value = "2.5"
        app._load_first_preview = mock.AsyncMock()
        await dialog.actions[-1].on_click(None)
        await dialog.actions[-1].on_click(None)
        app.page.pop_dialog.assert_called_once()
        app._load_first_preview.assert_awaited_once()

    async def test_failed_save_restores_range_without_decoding(self):
        app = self.app
        app._save_active_task_options = mock.Mock(return_value=False)
        app._load_first_preview = mock.AsyncMock()
        self.assertFalse(await app._apply_trim_range(2.5, 8))
        self.assertEqual((0, 12.8), (app.trim_slider.start_value, app.trim_slider.end_value))
        self.assertTrue(app.trim_error.visible)
        app._load_first_preview.assert_not_awaited()

    async def test_reset_crop_preserves_other_options(self):
        app = self.app
        app._load_first_preview = mock.AsyncMock()
        app.skip_frames_field.value = "2"
        await app._apply_trim_range(2, 8)
        await app._trim_at_playhead(SimpleNamespace(control=SimpleNamespace(data="reset")))
        self.assertEqual(0, self.job.options.trim_start_seconds)
        self.assertEqual(12.8, self.job.options.trim_end_seconds)
        self.assertEqual(2, self.job.options.skip_frames)

    def test_still_images_and_loading_sources_hide_crop_controls(self):
        app = self.app
        app._configure_trim_timeline(SimpleNamespace(kind="image", duration_seconds=0))
        self.assertFalse(app.trim_controls.visible)
        app._edit_trim_dialog(None)
        app.page.show_dialog.assert_not_called()
        app._set_source(Path("new.mp4"), trim_start=2, trim_end=5)
        self.assertTrue(app.trim_slider.disabled)
        self.assertFalse(app.trim_controls.visible)
        self.assertEqual((2, 5), app.pending_trim_range)

    async def test_valid_crop_resumes_playback_once(self):
        app = self.app
        app.preview_playing = True
        app._load_first_preview = mock.AsyncMock()
        app._toggle_preview_playback = mock.AsyncMock()
        app._trim_drag_start(None)
        app.trim_slider.start_value, app.trim_slider.end_value = 2, 8
        await app._on_trim_change(None)
        app._toggle_preview_playback.assert_awaited_once()
        self.assertFalse(app.trim_dragging)
        self.assertFalse(app.resume_preview_after_drag)

    async def test_new_drag_is_not_resumed_by_old_crop_load(self):
        app = self.app
        app.preview_playing = True
        app._toggle_preview_playback = mock.AsyncMock()
        async def load():
            app._trim_drag_start(None)
        app._load_first_preview = mock.AsyncMock(side_effect=load)
        await app._apply_trim_range(2, 8)
        app._toggle_preview_playback.assert_not_awaited()
        self.assertTrue(app.trim_dragging)
        self.assertTrue(app.resume_preview_after_drag)

    async def test_real_gif_crop_preview_matches_committed_range(self):
        app = self.app
        app.preview = gui.PreviewSession()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "range.gif"
            frames = [Image.new("RGB", (8, 8), color) for color in ("black", "white", "black")]
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=500)
            self.job.options = gui.replace(self.job.options, source=source, output=source.with_suffix(".BIN"), fps=2, width=8, height=8)
            app._load_job_controls(self.job)
            try:
                await app._load_first_preview()
                await app._apply_trim_range(0.5, 1.0)
                app._show_error.assert_not_called()
                self.assertEqual((0.5, 1.0), (self.job.options.trim_start_seconds, self.job.options.trim_end_seconds))
                self.assertEqual(1, app.preview.info.frame_count)
                self.assertEqual("00:00.50 / 00:01.50", app.preview_time_label.value)
                with Image.open(io.BytesIO(app.preview_image.src)) as preview:
                    self.assertEqual(255, preview.convert("L").getpixel((0, 0)))
                self.assertFalse(await app._preview_next())
            finally:
                await app._close_preview_if_current(app.preview_revision)


if __name__ == "__main__":
    unittest.main()
