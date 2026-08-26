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


class PreviewAnchorTests(unittest.TestCase):
    def setUp(self):
        self.options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"), fps=15)

    def info(self, kind="video", count=150, duration=10):
        return gui.SourceInfo(kind, count, duration, 30, (128, 64))

    def test_capture_uses_decoded_grid_crop_skip_and_cache_index(self):
        options = gui.replace(self.options, trim_start_seconds=2.51, skip_frames=3)
        anchor = gui.PreviewAnchor.from_frame(options, 5)
        self.assertEqual(45, anchor.frame_index)
        self.assertEqual(3, anchor.seconds)
        self.assertEqual(options.source, anchor.source)

    def test_video_and_gif_preserve_time_when_fps_changes(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 40)
        for kind in ("video", "gif"):
            with self.subTest(kind=kind):
                options = gui.replace(self.options, fps=10)
                result = gui.preview_options_at_anchor(options, self.info(kind, 100), anchor)
                self.assertEqual(2.6, result.trim_start_seconds)
                self.assertEqual(0, result.skip_frames)

    def test_directory_preserves_image_index_instead_of_old_time(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 40)
        options = gui.replace(self.options, fps=10)
        result = gui.preview_options_at_anchor(options, self.info("directory", 100), anchor)
        self.assertEqual(3.9, result.trim_start_seconds)

    def test_new_rate_aligns_to_first_frame_at_or_after_old_position(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 7)
        result = gui.preview_options_at_anchor(gui.replace(self.options, fps=7), self.info(), anchor)
        self.assertAlmostEqual(3 / 7, result.trim_start_seconds)

    def test_position_clamps_to_crop_start_after_skipped_frames(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 1)
        options = gui.replace(self.options, trim_start_seconds=2.51, skip_frames=3)
        result = gui.preview_options_at_anchor(options, self.info(count=20), anchor)
        self.assertAlmostEqual(41 / 15, result.trim_start_seconds)
        self.assertEqual(0, result.skip_frames)

    def test_position_clamps_to_last_frame_not_exclusive_end(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 150)
        options = gui.replace(self.options, trim_start_seconds=2.5, trim_end_seconds=3, skip_frames=1)
        result = gui.preview_options_at_anchor(options, self.info(count=6, duration=0.4), anchor)
        self.assertAlmostEqual(44 / 15, result.trim_start_seconds)
        self.assertLess(result.trim_start_seconds, options.trim_end_seconds)

    def test_unknown_count_uses_trimmed_duration_when_available(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 150)
        options = gui.replace(self.options, trim_start_seconds=2)
        result = gui.preview_options_at_anchor(options, self.info(count=None, duration=1), anchor)
        self.assertAlmostEqual(44 / 15, result.trim_start_seconds)

    def test_unknown_duration_keeps_requested_position(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 76)
        result = gui.preview_options_at_anchor(self.options, self.info(count=None, duration=None), anchor)
        self.assertEqual(5, result.trim_start_seconds)

    def test_no_anchor_other_source_and_single_image_keep_original_options(self):
        anchor = gui.PreviewAnchor.from_frame(gui.replace(self.options, source=Path("other.mp4")), 10)
        self.assertIs(self.options, gui.preview_options_at_anchor(self.options, self.info(), None))
        self.assertIs(self.options, gui.preview_options_at_anchor(self.options, self.info(), anchor))
        anchor = gui.PreviewAnchor.from_frame(self.options, 10)
        self.assertIs(self.options, gui.preview_options_at_anchor(self.options, self.info("image", 1), anchor))

    def test_seek_only_changes_decoder_start_and_never_mutates_task_options(self):
        options = gui.replace(
            self.options, width=96, height=32, trim_start_seconds=1,
            trim_end_seconds=5, skip_frames=2, dither="floyd", threshold=170,
            invert=True, background="white", fit="cover", force=True, workers=3,
        )
        anchor = gui.PreviewAnchor.from_frame(options, 12)
        result = gui.preview_options_at_anchor(options, self.info(count=58), anchor)
        self.assertEqual(gui.replace(options, trim_start_seconds=anchor.seconds, skip_frames=0), result)
        self.assertEqual((1, 5, 2), (options.trim_start_seconds, options.trim_end_seconds, options.skip_frames))

    def test_empty_range_is_rejected(self):
        anchor = gui.PreviewAnchor.from_frame(self.options, 1)
        with self.assertRaises(ValueError):
            gui.preview_options_at_anchor(self.options, self.info(count=0), anchor)


class PreviewReloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
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
        app.preview = gui.PreviewSession()
        app.preview_lock = asyncio.Lock()
        app.preview_revision = 0
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.preview_playing = False
        app.preview_timeline_dragging = False
        app.trim_dragging = False
        app.resume_preview_after_drag = False
        app.pending_trim_range = None
        app.source_info = None
        app.source_info_key = None
        app._refresh_queue_view = mock.Mock()
        app._show_error = mock.Mock()
        app._show_notice = mock.Mock()
        self.app = app

    async def asyncTearDown(self):
        await self.app._close_preview_if_current(self.app.preview_revision)
        self.directory.cleanup()

    def gif(self, name="clip.gif"):
        source = self.root / name
        frames = [Image.new("RGB", (8, 8), (value,) * 3) for value in (20, 80, 160, 240)]
        frames[0].save(source, save_all=True, append_images=frames[1:], duration=500)
        return source

    def images(self):
        source = self.root / "frames"
        source.mkdir()
        for index in range(12):
            Image.new("RGB", (8, 8), (index * 20,) * 3).save(source / f"{index:02d}.png")
        return source

    async def load(self, source, **changes):
        options = gui.ConversionOptions(source, self.root / "output.BIN", width=8, height=8, fps=4)
        job = self.app.queue.add(gui.replace(options, **changes))
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        await self.app._load_first_preview()
        self.app._show_error.assert_not_called()
        return job

    async def seek(self, position):
        await self.app._preview_seek(SimpleNamespace(control=SimpleNamespace(value=position)))
        self.app._show_error.assert_not_called()

    def gray_center(self):
        image = self.app.preview.current_grayscale()
        return image.getpixel((image.width // 2, image.height // 2))

    async def test_size_fit_and_background_changes_keep_same_gif_frame(self):
        job = await self.load(self.gif())
        await self.seek(1.25)
        before = self.gray_center()
        for control, value in (
            (self.app.width_field, "16"), (self.app.fit_dropdown, "cover"),
            (self.app.background_dropdown, "white"),
        ):
            with self.subTest(value=value):
                control.value = value
                await self.app._on_geometry_change(None)
                self.assertEqual(1.25, self.app.preview_anchor.seconds)
                self.assertEqual(1.25, self.app.preview_timeline.value)
                self.assertEqual(before, self.gray_center())
                self.assertEqual((0, None, 0), (
                    job.options.trim_start_seconds, job.options.trim_end_seconds, job.options.skip_frames,
                ))
        self.app._show_error.assert_not_called()

    async def test_manual_reload_keeps_position_and_first_button_resets_it(self):
        await self.load(self.gif(), trim_start_seconds=0.5)
        await self.seek(1.25)
        await self.app._refresh_preview()
        self.assertEqual(1.25, self.app.preview_anchor.seconds)
        await self.app._preview_first(None)
        self.assertEqual(0.5, self.app.preview_anchor.seconds)

    async def test_mp4_reload_keeps_timestamp_and_oled_pixels(self):
        try:
            import imageio_ffmpeg
        except ImportError:
            self.skipTest("imageio-ffmpeg is not installed")
        source = self.root / "seek.mp4"

        def write_video():
            writer = imageio_ffmpeg.write_frames(str(source), (16, 16), fps=4)
            writer.send(None)
            try:
                for index in range(8):
                    writer.send(bytes([index * 30] * 3) * 16 * 16)
            finally:
                writer.close()

        await asyncio.to_thread(write_video)
        await self.load(source)
        await self.seek(1.25)
        original = self.app.preview_image.src
        await self.app._refresh_preview()
        self.assertEqual(original, self.app.preview_image.src)
        self.app.fps_field.value = "8"
        await self.app._on_geometry_change(None)
        self.assertEqual(1.25, self.app.preview_anchor.seconds)
        self.assertEqual(original, self.app.preview_image.src)
        self.app._show_error.assert_not_called()

    async def test_fps_change_preserves_time_on_the_new_frame_grid(self):
        await self.load(self.gif())
        await self.seek(1.25)
        self.app.fps_field.value = "3"
        await self.app._on_geometry_change(None)
        self.assertAlmostEqual(4 / 3, self.app.preview_anchor.seconds)
        self.assertEqual(160, self.gray_center())

    async def test_last_frame_is_clamped_when_fps_is_reduced(self):
        await self.load(self.gif())
        await self.seek(1.75)
        self.app.fps_field.value = "2"
        await self.app._on_geometry_change(None)
        self.assertEqual(1.5, self.app.preview_anchor.seconds)
        self.assertEqual(240, self.gray_center())

    async def test_directory_keeps_image_and_updates_duration_after_fps_change(self):
        job = await self.load(self.images())
        await self.seek(2)
        self.assertEqual(160, self.gray_center())
        self.app.fps_field.value = "2"
        await self.app._on_geometry_change(None)
        self.assertEqual(4, self.app.preview_anchor.seconds)
        self.assertEqual(160, self.gray_center())
        self.assertEqual(6, self.app.preview_timeline.max)
        self.assertEqual(6, self.app.trim_slider.end_value)
        self.assertIsNone(job.options.trim_end_seconds)
        self.app._show_error.assert_not_called()

    async def test_explicit_directory_crop_end_is_not_extended_with_duration(self):
        job = await self.load(self.images(), trim_end_seconds=3)
        await self.seek(2)
        self.app.fps_field.value = "2"
        await self.app._on_geometry_change(None)
        self.assertEqual(3, job.options.trim_end_seconds)
        self.assertEqual(3, self.app.trim_slider.end_value)
        self.assertEqual(2.5, self.app.preview_anchor.seconds)
        self.assertEqual(100, self.gray_center())

    async def test_increasing_skip_clamps_preview_but_does_not_double_skip(self):
        job = await self.load(self.gif())
        await self.seek(0.25)
        self.app.skip_frames_field.value = "4"
        await self.app._on_geometry_change(None)
        self.assertEqual(1, self.app.preview_anchor.seconds)
        self.assertEqual(160, self.gray_center())
        self.assertEqual(4, job.options.skip_frames)
        self.assertEqual(0, self.app.preview.options.skip_frames)
        self.app._show_error.assert_not_called()

    async def test_reloaded_size_estimate_counts_the_entire_export_not_the_tail(self):
        job = await self.load(self.gif())
        await self.seek(1.25)
        self.app.width_field.value = "16"
        await self.app._on_geometry_change(None)
        expected = gui.estimate_output_bytes(job.options, gui.trim_source_info(self.app.source_info, job.options))
        self.assertIn(gui.human_size(expected), self.app.preview_label.value)
        self.assertIn("第 6/8 帧", self.app.preview_label.value)
        self.assertEqual(3, self.app.preview.info.frame_count)

    async def test_preset_keeps_existing_preview_position(self):
        await self.load(self.gif())
        await self.seek(1.25)
        preset = gui.ConversionPreset("Fit test", width=16, height=8, fps=4, fit="cover")
        self.app.preset_store.all_presets.return_value = [preset]
        self.app.preset_dropdown.value = preset.name
        tasks = []
        create = asyncio.create_task

        def schedule(coroutine):
            task = create(coroutine)
            tasks.append(task)
            return task

        with mock.patch.object(gui.asyncio, "create_task", side_effect=schedule):
            self.app._apply_selected_preset(None)
            await asyncio.gather(*tasks)
        self.assertEqual(1.25, self.app.preview_anchor.seconds)
        self.assertEqual(16, self.app.preview.options.width)

    async def test_switching_source_clears_position_before_decoding(self):
        await self.load(self.gif())
        await self.seek(1.25)
        source = self.gif("other.gif")
        self.app._set_source(source)
        self.assertIsNone(self.app.preview_anchor)
        await self.app._load_first_preview()
        self.assertEqual(0, self.app.preview_anchor.seconds)
        self.assertEqual(source, self.app.preview_anchor.source)

    async def test_failed_reload_discards_old_anchor(self):
        source = self.gif()
        await self.load(source)
        await self.seek(1.25)
        source.unlink()
        await self.app._refresh_preview()
        self.assertIsNone(self.app.preview_anchor)
        self.app._show_error.assert_called_once()

    async def test_continuous_edits_keep_displayed_anchor_and_only_show_latest_result(self):
        await self.load(self.gif())
        await self.seek(1.25)
        app = self.app
        probe = app._source_info_for_options
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_probe(options):
            info = await probe(options)
            if options.width == 16:
                entered.set()
                await release.wait()
            return info

        app._source_info_for_options = slow_probe
        app._set_preview_frame = mock.Mock(wraps=app._set_preview_frame)
        app.width_field.value = "16"
        old = asyncio.create_task(app._on_geometry_change(None))
        await asyncio.wait_for(entered.wait(), timeout=3)
        app.width_field.value = "24"
        new = asyncio.create_task(app._on_geometry_change(None))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(old, new)
        self.assertEqual(24, app.preview.options.width)
        self.assertEqual(1.25, app.preview_anchor.seconds)
        app._set_preview_frame.assert_called_once()
        app._show_error.assert_not_called()

    async def test_geometry_edit_stops_playback_and_updates_button_before_debounce(self):
        await self.load(self.gif())
        app = self.app
        app.preview_playing = True
        app.preview_play_button.icon = gui.ft.Icons.PAUSE
        app.width_field.value = "16"
        task = asyncio.create_task(app._on_geometry_change(None))
        await asyncio.sleep(0)
        self.assertFalse(app.preview_playing)
        self.assertEqual(gui.ft.Icons.PLAY_ARROW, app.preview_play_button.icon)
        await task

    async def test_slow_reload_keeps_old_image_and_clears_pending_hint_on_completion(self):
        await self.load(self.gif())
        await self.seek(1.25)
        app = self.app
        old_image, old_anchor = app.preview_image.src, app.preview_anchor
        probe = app._source_info_for_options
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_probe(options):
            info = await probe(options)
            entered.set()
            await release.wait()
            return info

        app._source_info_for_options = slow_probe
        task = asyncio.create_task(app._refresh_preview())
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            await asyncio.sleep(0.18)
            self.assertEqual("正在更新预览…", app.preview_label.value)
            self.assertEqual(old_image, app.preview_image.src)
            self.assertEqual(old_anchor, app.preview_anchor)
        finally:
            release.set()
            await task
        self.assertIn("第 6/8 帧", app.preview_label.value)
        label = app.preview_label.value
        await asyncio.sleep(0.18)
        self.assertEqual(label, app.preview_label.value)

    async def test_first_frame_command_supersedes_pending_parameter_reload(self):
        await self.load(self.gif())
        await self.seek(1.25)
        app = self.app
        app.width_field.value = "16"
        pending = asyncio.create_task(app._on_geometry_change(None))
        await asyncio.sleep(0)
        await app._preview_first(None)
        await pending
        self.assertEqual(0, app.preview_anchor.seconds)
        self.assertEqual(16, app.preview.options.width)

    async def test_reload_off_page_does_not_update_unmounted_preview_controls(self):
        await self.load(self.gif())
        await self.seek(1.25)
        self.app.page_index = 2
        self.app.page.update.reset_mock()
        self.app.width_field.value = "16"
        await self.app._on_geometry_change(None)
        self.assertEqual(1.25, self.app.preview_anchor.seconds)
        self.app.page.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
