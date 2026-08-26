import asyncio
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovid_converter_gui as gui


class BatchProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        app = self.app
        app.page = SimpleNamespace(update=mock.Mock())
        app.settings = gui.AppSettings()
        app.preset_store = mock.Mock()
        app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.pending_trim_range = None
        app.page_index = 0
        app.busy = False
        app.conversion_revision = 0
        app.exit_after_conversion_stop = False
        app.queue_cancel_event = threading.Event()
        app.logger = SimpleNamespace(event=mock.Mock())
        app._show_notice = mock.Mock()
        app._show_error = mock.Mock()
        app._open_player_path = mock.Mock()
        app._build_controls()
        self.texts = []
        app.page.update.side_effect = lambda *_: self.texts.append(app.progress_text.value)

    def add_job(self, name):
        source = self.root / name
        source.touch()
        return self.app.queue.add(gui.ConversionOptions(source, source.with_suffix(".BIN")))

    async def run_batch(self, convert, probe=None):
        with (
            mock.patch.object(gui, "convert_media", side_effect=convert),
            mock.patch.object(gui, "probe_source", side_effect=probe, return_value=object()),
            mock.patch.object(gui, "check_compatibility", return_value=SimpleNamespace(issues=[])),
        ):
            await self.app._start_conversion(None)

    async def test_failed_task_counts_as_processed_in_overall_progress(self):
        first = self.add_job("broken.png")
        second = self.add_job("valid.png")
        ratios = []
        def convert(options, *, progress, **_):
            if options.source == first.options.source:
                raise ValueError("Invalid image")
            progress(gui.ConversionProgress(5, 10, 5156))
            ratios.append(self.app.latest_conversion_progress[1].ratio)
            return SimpleNamespace(path=options.output)
        await self.run_batch(convert)
        self.assertEqual([0.75], ratios)
        self.assertEqual(("failed", "completed"), (first.state, second.state))
        self.assertEqual("本轮结束：1 成功 · 1 失败", self.app.progress_text.value)

    async def test_unknown_total_displays_real_frames_not_processed_task_count(self):
        self.add_job("unknown.png")
        def convert(options, *, progress, **_):
            progress(gui.ConversionProgress(45, None, 46276, current_fps=20))
            time.sleep(0.08)
            return SimpleNamespace(path=options.output)
        await self.run_batch(convert)
        self.assertTrue(any("45 帧" in text for text in self.texts), self.texts)

    async def test_starting_next_task_clears_previous_file_statistics(self):
        self.add_job("first.png")
        second = self.add_job("next.png")
        statistics = []
        def probe(options):
            if options.source == second.options.source:
                snapshot = self.app.latest_conversion_progress[1]
                statistics.append(snapshot.current)
            return object()
        def convert(options, *, progress, **_):
            progress(gui.ConversionProgress(10, 10, 10296))
            return SimpleNamespace(path=options.output)
        await self.run_batch(convert, probe)
        self.assertEqual([None], statistics)

    async def test_stopping_message_is_not_overwritten_by_periodic_renderer(self):
        app = self.app
        app.busy = True
        app.stop_batch_requested = True
        app.conversion_revision = 1
        value = gui.ConversionProgress(2, 10, 2072)
        snapshot = gui.BatchDisplayProgress("sample.png", 0, 1, value)
        app.latest_conversion_progress = (1, snapshot)
        app.progress_display_ratio = 0.2
        app.progress_finish_deadline = None
        app.progress_text.value = "正在停止本轮…"
        task = asyncio.create_task(app._render_conversion_progress(1, asyncio.Event()))
        try:
            await asyncio.sleep(0.05)
        finally:
            app.busy = False
            await task
        self.assertEqual("正在停止本轮…", app.progress_text.value)

    def test_open_ended_crop_does_not_claim_to_export_the_whole_source(self):
        options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"), trim_start_seconds=2.5)
        self.assertEqual("00:02.50–结尾", self.app._task_time_range(options))

    def test_skipped_frames_are_visible_in_task_summary(self):
        options = gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN"), skip_frames=10)
        self.assertEqual("跳过前 10 帧", self.app._task_time_range(options))
        cropped = gui.replace(options, trim_start_seconds=2.5, trim_end_seconds=5)
        self.assertEqual("00:02.50–00:05.00 · 跳过前 10 帧", self.app._task_time_range(cropped))

    def test_file_statistics_are_not_presented_as_batch_totals(self):
        value = gui.ConversionProgress(25, 100, 4096, current_fps=20, average_fps=18, remaining_seconds=4.2)
        snapshot = gui.BatchDisplayProgress("second.png", 1, 2, value)
        self.assertAlmostEqual(0.625, snapshot.ratio)
        self.assertIn("已处理 1/2 项", snapshot.text())
        self.assertIn("本文件 25/100 帧", snapshot.text())
        self.assertIn("当前输出 4.0 KiB", snapshot.text())
        self.assertIn("本文件剩余 4.2 秒", snapshot.text())
        self.assertIs(value, snapshot.current)

    async def test_renderer_updates_speed_and_file_name_even_when_frame_count_is_unchanged(self):
        app = self.app
        app.busy = True
        app.stop_batch_requested = False
        app.conversion_revision = 1
        app.progress_display_ratio = 0
        app.progress_finish_deadline = None
        first = gui.ConversionProgress(5, None, 5156, current_fps=20)
        app.latest_conversion_progress = (1, gui.BatchDisplayProgress("first.png", 0, 2, first))
        task = asyncio.create_task(app._render_conversion_progress(1, asyncio.Event()))
        try:
            await asyncio.sleep(0.04)
            self.assertIn("20.0/", app.progress_text.value)
            app.latest_conversion_progress = (
                1, gui.BatchDisplayProgress("next.png", 1, 2, gui.replace(first, current_fps=35)),
            )
            await asyncio.sleep(0.04)
            self.assertIn("next.png", app.progress_text.value)
            self.assertIn("35.0/", app.progress_text.value)
        finally:
            app.busy = False
            await task

    async def test_finished_task_callback_cannot_replace_next_task_progress(self):
        first = self.add_job("first.png")
        self.add_job("next.png")
        callbacks = []
        names = []
        def convert(options, *, progress, **_):
            if options.source == first.options.source:
                callbacks.append(progress)
            else:
                callbacks[0](gui.ConversionProgress(99, 100, 101788))
                names.append(self.app.latest_conversion_progress[1].file_name)
            progress(gui.ConversionProgress(1, 1, 1044))
            return SimpleNamespace(path=options.output)
        await self.run_batch(convert)
        self.assertEqual(["next.png"], names)

    async def test_stop_keeps_waiting_jobs_and_rejects_late_progress(self):
        first = self.add_job("first.png")
        second = self.add_job("waiting.png")
        loop = asyncio.get_running_loop()
        snapshots = []
        def convert(options, *, progress, cancelled, **_):
            progress(gui.ConversionProgress(2, 10, 2072))
            before = self.app.latest_conversion_progress
            loop.call_soon_threadsafe(self.app._cancel_conversion, None)
            self.assertTrue(self.app.queue_cancel_event.wait(1))
            self.assertTrue(cancelled())
            progress(gui.ConversionProgress(10, 10, 10296))
            snapshots.append(self.app.latest_conversion_progress == before)
            time.sleep(0.06)
            raise gui.ConversionCancelled()
        await self.run_batch(convert)
        self.assertEqual([True], snapshots)
        self.assertEqual(("cancelled", "queued"), (first.state, second.state))
        self.assertFalse(first.frozen or second.frozen)
        self.assertEqual("本轮已停止，未开始的任务仍在等待", self.app.progress_text.value)
        self.assertLess(self.app.progress_bar.value, 1)
        self.assertTrue(self.app.cancel_button.disabled)

    async def test_previous_batch_callback_cannot_update_the_same_job_in_a_new_batch(self):
        job = self.add_job("repeat.png")
        callbacks = []
        accepted = []
        def first_convert(options, *, progress, **_):
            callbacks.append(progress)
            return SimpleNamespace(path=options.output)
        await self.run_batch(first_convert)
        job.selected = True
        def second_convert(options, *, progress, **_):
            before = self.app.latest_conversion_progress
            callbacks[0](gui.ConversionProgress(99, 100, 101788))
            accepted.append(self.app.latest_conversion_progress == before)
            progress(gui.ConversionProgress(1, 2, 1044))
            return SimpleNamespace(path=options.output)
        await self.run_batch(second_convert)
        self.assertEqual([True], accepted)

    async def test_inactive_conversion_page_keeps_data_current_without_patching_hidden_controls(self):
        app = self.app
        app.busy = True
        app.stop_batch_requested = False
        app.page_index = 2
        app.conversion_revision = 1
        app.progress_display_ratio = 0
        app.progress_finish_deadline = None
        app.latest_conversion_progress = (
            1, gui.BatchDisplayProgress("sample.png", 0, 1, gui.ConversionProgress(5, 10, 5156)),
        )
        app.page.update.reset_mock()
        task = asyncio.create_task(app._render_conversion_progress(1, asyncio.Event()))
        try:
            await asyncio.sleep(0.04)
            self.assertIn("5/10 帧", app.progress_text.value)
            app.page.update.assert_not_called()
        finally:
            app.busy = False
            await task

    async def test_all_failed_tasks_finish_with_an_honest_result(self):
        self.add_job("a.png")
        self.add_job("b.png")
        def convert(*_, **__):
            raise ValueError("Invalid image")
        await self.run_batch(convert)
        self.assertEqual("本轮结束：0 成功 · 2 失败", self.app.progress_text.value)
        self.assertEqual(1, self.app.progress_bar.value)
        self.app._open_player_path.assert_not_called()

    async def test_real_image_batch_writes_valid_outputs_with_the_same_ui_executor(self):
        from PIL import Image
        from ovid_codec import OvidReader, validate_ovid
        jobs = [self.add_job("white.png"), self.add_job("black.png")]
        for job, color in zip(jobs, (255, 0)):
            Image.new("L", (128, 64), color).save(job.options.source)
        await self.app._start_conversion(None)
        self.assertEqual(["completed", "completed"], [job.state for job in jobs])
        self.assertEqual("本轮完成：2/2 个任务", self.app.progress_text.value)
        for job, color in zip(jobs, (255, 0)):
            self.assertTrue(validate_ovid(job.options.output).valid)
            with OvidReader(job.options.output) as reader:
                self.assertEqual(1, reader.header.frame_count)
                self.assertEqual(bytes([color]) * 1024, reader.read_frame(0).data)


if __name__ == "__main__":
    unittest.main()
