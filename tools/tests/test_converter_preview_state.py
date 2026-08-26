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


class PreviewStateTests(unittest.IsolatedAsyncioTestCase):
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
        app.preview_revision = 1
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.preview_lock = asyncio.Lock()
        app.preview_playing = False
        app.preview_timeline_dragging = False
        app.trim_dragging = False
        app.resume_preview_after_drag = False
        app.pending_trim_range = None
        app.source_info = None
        app.source_info_key = None
        app.preview = mock.Mock(index=0)
        app._set_preview_frame = mock.Mock()
        app._show_error = mock.Mock()
        app._show_notice = mock.Mock()
        self.app = app

    def add_task(self):
        options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"))
        job = self.app.queue.add(options)
        self.app.active_task_id = job.id
        self.app._load_job_controls(job)
        return job

    def test_open_ended_crop_is_used_before_metadata_arrives(self):
        self.app._set_source(Path("clip.mp4"), trim_start=2.5, trim_end=None)
        options = self.app._options(require_output=False)
        self.assertEqual(2.5, options.trim_start_seconds)
        self.assertIsNone(options.trim_end_seconds)

    def test_new_sources_do_not_inherit_the_pending_crop(self):
        self.app._set_source(Path("clip.mp4"), trim_start=2.5, trim_end=6.0)
        options = self.app._options_for_source(
            Path("new.mp4"), Path("new.BIN"), use_current_trim=False
        )
        self.assertEqual(0.0, options.trim_start_seconds)
        self.assertIsNone(options.trim_end_seconds)

    async def test_open_ended_gif_crop_decodes_the_selected_first_frame(self):
        self.app.preview = gui.PreviewSession()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "crop.gif"
            frames = [Image.new("RGB", (8, 8), color) for color in ("black", "white", "black")]
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=500)
            job = self.app.queue.add(gui.ConversionOptions(
                source, Path(directory) / "crop.BIN", width=8, height=8,
                fps=2, trim_start_seconds=0.5,
            ))
            self.app.active_task_id = job.id
            self.app._load_job_controls(job)
            try:
                await self.app._load_first_preview()
                self.app._show_error.assert_not_called()
                self.assertEqual(0.5, self.app.preview.options.trim_start_seconds)
                self.assertEqual(2, self.app.preview.info.frame_count)
                png = self.app._set_preview_frame.call_args.args[1]
                with Image.open(io.BytesIO(png)) as result:
                    self.assertEqual(255, result.convert("L").getpixel((0, 0)))
            finally:
                await self.app._close_preview_if_current(self.app.preview_revision)

    async def test_obsolete_probe_does_not_replace_new_metadata(self):
        options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"))
        def probe(_):
            self.app.preview_revision += 1
            self.app.source_info = mock.sentinel.new_metadata
            self.app.source_info_key = mock.sentinel.new_key
            return mock.sentinel.old_metadata
        with mock.patch.object(gui, "probe_source", side_effect=probe), mock.patch.object(
            gui, "trim_source_info", return_value=mock.sentinel.trimmed
        ) as trim:
            await self.app._source_info_for_options(options)
        self.assertIs(mock.sentinel.new_metadata, self.app.source_info)
        self.assertIs(mock.sentinel.new_key, self.app.source_info_key)
        trim.assert_called_once_with(mock.sentinel.old_metadata, options)

    async def test_first_frame_uses_parameters_changed_during_metadata_loading(self):
        self.app.preview = gui.PreviewSession()
        self.app._refresh_queue_view = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "gray.png"
            Image.new("L", (8, 8), 180).save(source)
            job = self.app.queue.add(gui.ConversionOptions(
                source, Path(directory) / "gray.BIN", width=8, height=8,
            ))
            self.app.active_task_id = job.id
            self.app._load_job_controls(job)
            probe = self.app._source_info_for_options

            async def change_options_while_loading(options):
                info = await probe(options)
                self.app.threshold_slider.value = 200
                await self.app._on_threshold_change(None)
                return info

            self.app._source_info_for_options = change_options_while_loading
            try:
                await self.app._load_first_preview()
                self.app._show_error.assert_not_called()
                self.assertEqual(200, job.options.threshold)
                self.assertEqual(200, self.app.preview.options.threshold)
                png = self.app._set_preview_frame.call_args.args[1]
                with Image.open(io.BytesIO(png)) as result:
                    self.assertEqual(0, result.convert("L").getpixel((0, 0)))
                self.app._set_preview_frame.assert_called_once()
            finally:
                await self.app._close_preview_if_current(self.app.preview_revision)

    async def test_waiting_frame_steps_cannot_consume_a_new_sources_frames(self):
        for method in ("_preview_next", "_preview_previous"):
            with self.subTest(method=method):
                self.app.preview.reset_mock()
                self.app.preview.next_frame.return_value = (b"original", b"frame", 1)
                self.app.preview.previous_frame.return_value = (b"original", b"frame", 1)
                await self.app.preview_lock.acquire()
                task = asyncio.create_task(getattr(self.app, method)(None))
                await asyncio.sleep(0)
                self.app.preview_revision += 1
                self.app.preview_lock.release()
                await task
                self.app.preview.next_frame.assert_not_called()
                self.app.preview.previous_frame.assert_not_called()

    async def test_load_applies_algorithm_and_inversion_edits_before_showing_frame(self):
        self.app._refresh_queue_view = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "gray.png"
            Image.new("L", (8, 8), 180).save(source)
            probe = self.app._source_info_for_options
            for edit in ("floyd", "invert"):
                with self.subTest(edit=edit):
                    self.app.preview = gui.PreviewSession()
                    self.app._set_preview_frame.reset_mock()
                    job = self.app.queue.add(gui.ConversionOptions(
                        source, Path(directory) / f"{edit}.BIN", width=8, height=8,
                    ))
                    self.app.active_task_id = job.id
                    self.app._load_job_controls(job)

                    async def change_options_while_loading(options):
                        info = await probe(options)
                        if edit == "floyd":
                            self.app.dither_control.selected = ["floyd"]
                            await self.app._on_dither_change(None)
                        else:
                            self.app.invert_switch.value = True
                            await self.app._on_invert_change(None)
                        return info

                    self.app._source_info_for_options = change_options_while_loading
                    try:
                        await self.app._load_first_preview()
                        self.app._show_error.assert_not_called()
                        self.assertEqual(job.options.dither, self.app.preview.options.dither)
                        self.assertEqual(job.options.invert, self.app.preview.options.invert)
                        original = Image.new("L", (8, 8), 180)
                        expected = gui.preview_prepared_png(
                            gui.prepare_monochrome_source(original, job.options),
                            job.options, scale=4,
                        )
                        self.assertEqual(expected, self.app._set_preview_frame.call_args.args[1])
                        self.app._set_preview_frame.assert_called_once()
                    finally:
                        await self.app._close_preview_if_current(self.app.preview_revision)

    async def test_parameter_changes_during_rerender_are_reconciled_again(self):
        self.app.preview_render_revision = 1
        self.app._set_threshold_value(64)
        async def render(_callback, *_args):
            if self.app.preview_render_revision == 1:
                self.app._set_threshold_value(200)
                self.app.preview_render_revision += 1
                return b"source", b"obsolete", 1
            return b"source", b"current", 1
        with mock.patch.object(gui.asyncio, "to_thread", side_effect=render) as worker:
            result = await self.app._reconcile_preview_frame((b"source", b"old", 1), 1, 0)
        self.assertEqual(b"current", result[1])
        self.assertEqual([64, 200], [call.args[2] for call in worker.call_args_list])

    async def test_reconcile_does_not_render_an_obsolete_source(self):
        self.app.preview_revision = 2
        self.app.preview_render_revision = 1
        frame = (b"source", b"old", 1)
        self.assertEqual(frame, await self.app._reconcile_preview_frame(frame, 1, 0))
        self.app.preview.rerender_current.assert_not_called()

    def test_offscreen_preview_updates_cached_frame_without_patching_unmounted_controls(self):
        self.app.page_index = 2
        self.app.preview.options = None
        gui.ConverterApp._set_preview_frame(self.app, b"source", b"new", "ready", index=1)
        self.assertEqual(b"new", self.app.preview_image.src)
        self.assertEqual("ready", self.app.preview_label.value)
        self.app.page.update.assert_not_called()

    async def test_superseded_load_stops_before_resetting_the_decoder(self):
        self.add_task()
        async def probe(_options):
            self.app.preview_revision += 1
            return SimpleNamespace(frame_count=1)
        self.app._source_info_for_options = probe
        self.app.preview.next_frame.return_value = (b"original", b"frame", 1)
        await self.app._load_first_preview()
        self.app.preview.reset.assert_not_called()
        self.app.preview.next_frame.assert_not_called()
        self.app._set_preview_frame.assert_not_called()

    async def test_waiting_render_does_not_apply_old_threshold_to_new_source(self):
        self.add_task()
        self.app.preview.rerender_current.return_value = (b"original", b"frame", 1)
        await self.app.preview_lock.acquire()
        task = asyncio.create_task(self.app._rerender_current_preview())
        await asyncio.sleep(0)
        self.app.preview_revision += 1
        self.app.preview_lock.release()
        await task
        self.app.preview.rerender_current.assert_not_called()

    async def test_old_threshold_analysis_does_not_open_a_dialog_for_new_task(self):
        self.add_task()
        def analyze(*_):
            self.app.preview_revision += 1
            return 96
        with mock.patch.object(gui, "suggested_threshold", side_effect=analyze):
            await self.app._auto_threshold("standard")
        self.app.page.show_dialog.assert_not_called()

    async def test_threshold_dialog_cannot_change_a_frozen_job(self):
        job = self.add_task()
        self.app._rerender_current_preview = mock.AsyncMock()
        with mock.patch.object(gui, "suggested_threshold", return_value=96):
            await self.app._auto_threshold("standard")
        dialog = self.app.page.show_dialog.call_args.args[0]
        self.app.queue.freeze_selected()
        dialog.actions[-1].on_click(None)
        await asyncio.sleep(0)
        self.assertEqual(128, self.app.threshold_slider.value)
        self.assertEqual(128, job.options.threshold)
        self.app._rerender_current_preview.assert_not_called()

    async def test_current_threshold_suggestion_updates_its_task(self):
        job = self.add_task()
        self.app._refresh_queue_view = mock.Mock()
        self.app._rerender_current_preview = mock.AsyncMock()
        with mock.patch.object(gui, "suggested_threshold", return_value=96):
            await self.app._auto_threshold("standard")
        self.app.page.show_dialog.call_args.args[0].actions[-1].on_click(None)
        await asyncio.sleep(0)
        self.assertEqual(96, self.app.threshold_slider.value)
        self.assertEqual(96, job.options.threshold)
        self.app._rerender_current_preview.assert_awaited_once()

    async def test_old_seek_does_not_end_a_new_drag(self):
        self.add_task()
        self.app.preview.next_frame.return_value = (b"original", b"frame", 1)
        async def probe(_):
            self.app.preview_revision += 1
            self.app.preview_timeline_dragging = True
            return SimpleNamespace(frame_count=1)
        self.app._source_info_for_options = probe
        await self.app._preview_seek(SimpleNamespace(control=SimpleNamespace(value=0.2)))
        self.assertTrue(self.app.preview_timeline_dragging)
        self.app.preview.reset.assert_not_called()
        self.app._set_preview_frame.assert_not_called()

    async def test_removing_last_task_waits_for_decoder_to_be_idle(self):
        await self.app.preview_lock.acquire()
        self.app._reset_editor_for_empty_queue()
        self.app.preview.close.assert_not_called()
        self.assertEqual("", self.app.source_field.value)
        self.app.preview_lock.release()
        await asyncio.wait_for(self.app.preview_close_task, timeout=1)
        self.app.preview.close.assert_called_once()

    async def test_old_close_request_cannot_close_new_source(self):
        await self.app.preview_lock.acquire()
        task = asyncio.create_task(self.app._close_preview_if_current(self.app.preview_revision))
        await asyncio.sleep(0)
        self.app.preview_revision += 1
        self.app.preview_lock.release()
        await task
        self.app.preview.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
