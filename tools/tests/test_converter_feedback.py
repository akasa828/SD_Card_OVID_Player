import asyncio
import errno
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import converter_feedback as feedback
import ovid_converter_gui as gui


def dialog_page():
    page = SimpleNamespace(update=mock.Mock(), show_dialog=mock.Mock(), pop_dialog=mock.Mock())
    page.show_dialog.side_effect = lambda dialog: setattr(dialog, "open", True)
    return page


class ErrorReportTests(unittest.TestCase):
    def test_known_file_errors_offer_relevant_guidance(self):
        cases = (
            (FileNotFoundError("x"), "路径"),
            (PermissionError("x"), "权限"),
            (FileExistsError("x"), "已存在"),
            (OSError(errno.ENOSPC, "x"), "空间不足"),
        )
        for error, expected in cases:
            with self.subTest(error=type(error)):
                self.assertIn(expected, feedback.error_summary(error))

    def test_short_validation_message_remains_visible(self):
        self.assertEqual("FPS 必须在 1–120", feedback.error_summary(ValueError("FPS 必须在 1–120")))

    def test_unknown_error_is_not_classified_by_message_keywords(self):
        error = RuntimeError("Permission denied is a string in a video filename")
        self.assertNotIn("没有访问权限", feedback.error_summary(error))

    def test_long_unicode_error_is_preserved_without_truncation(self):
        message = "C:\\素材\\错误.mp4\n" + "FFmpeg details\n" * 500
        report = feedback.ErrorReport.from_exception("无法读取", RuntimeError(message))
        self.assertLess(len(report.summary), 160)
        self.assertIn(message, report.details)
        self.assertIn("RuntimeError:", report.details)
        self.assertIn(gui.VERSION, report.details)

    def test_empty_error_still_records_exception_type(self):
        report = feedback.ErrorReport.from_exception("失败", RuntimeError())
        self.assertTrue(report.summary)
        self.assertIn("RuntimeError:", report.details)

    def test_task_report_is_an_immutable_parameter_snapshot(self):
        options = gui.ConversionOptions(
            Path("素材/原始.mp4"), Path("输出/视频.BIN"), width=96, height=64,
            fps=30, dither="floyd", trim_start_seconds=2.5, trim_end_seconds=8.25,
            skip_frames=3, workers=4, fast_video=True, force=True,
        )
        job = gui.QueueJob(options, target_profile="custom", state="failed", error="完整原始错误")
        report = feedback.ErrorReport.from_job(job)
        snapshot = json.loads(report.details.split("参数快照：\n", 1)[1])
        self.assertEqual(str(options.source), snapshot["source"])
        self.assertEqual(str(options.output), snapshot["output"])
        self.assertEqual(2.5, snapshot["trim_start_seconds"])
        self.assertEqual(3, snapshot["skip_frames"])
        self.assertEqual("floyd", snapshot["dither"])
        self.assertEqual(set(gui.asdict(options)), set(snapshot))
        job.error = "新的错误"
        job.options = gui.replace(options, width=128)
        self.assertIn("完整原始错误", report.details)
        self.assertNotIn("新的错误", report.details)
        self.assertEqual(96, snapshot["width"])


class ErrorDialogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = dialog_page()
        self.clipboard = SimpleNamespace(set=mock.AsyncMock())
        self.report = feedback.ErrorReport.from_exception("读取失败", ValueError("无法读取素材"))
        self.view = feedback.ErrorDetailsDialog(self.page, self.clipboard, self.report)
        self.view.show()

    def test_long_details_scroll_without_hiding_action_buttons(self):
        self.assertTrue(self.view.dialog.scrollable)
        self.assertTrue(self.view.details.selectable)
        self.assertFalse(self.view.details_section.expanded)
        self.assertTrue(self.view.dialog.content.tight)
        self.assertIsNone(self.view.dialog.content.scroll)
        self.assertEqual(["复制详情", "关闭"], [item.content for item in self.view.dialog.actions])

    async def test_copy_uses_the_visible_report_and_stays_in_dialog(self):
        await self.view.copy_button.on_click(None)
        self.clipboard.set.assert_awaited_once_with(self.report.details)
        self.assertIn("已复制", self.view.status.value)
        self.assertTrue(self.view.is_open)
        self.assertFalse(self.view.copy_button.disabled)
        self.page.show_dialog.assert_called_once()

    async def test_copy_failure_is_inline_and_can_be_retried(self):
        self.clipboard.set.side_effect = [OSError("clipboard busy"), None]
        await self.view.copy(None)
        self.assertIn("手动复制", self.view.status.value)
        self.assertEqual(gui.ft.Colors.ERROR, self.view.status.color)
        self.page.show_dialog.assert_called_once()
        self.assertFalse(self.view.copy_button.disabled)
        await self.view.copy(None)
        self.assertIn("已复制", self.view.status.value)
        self.assertEqual(gui.ft.Colors.ON_SURFACE_VARIANT, self.view.status.color)

    async def test_duplicate_copy_and_completion_after_close_are_ignored(self):
        gate = asyncio.Event()
        async def wait_for_clipboard(_):
            await gate.wait()
        self.clipboard.set.side_effect = wait_for_clipboard
        task = asyncio.create_task(self.view.copy())
        await asyncio.sleep(0)
        await self.view.copy()
        self.view.close()
        self.page.update.reset_mock()
        gate.set()
        await task
        self.clipboard.set.assert_awaited_once()
        self.page.update.assert_not_called()

    async def test_cancelled_copy_releases_busy_state(self):
        gate = asyncio.Event()
        async def wait_for_clipboard(_):
            await gate.wait()
        self.clipboard.set.side_effect = wait_for_clipboard
        task = asyncio.create_task(self.view.copy())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.view.copying)
        self.assertFalse(self.view.copy_button.disabled)

    async def test_close_targets_only_its_own_dialog_and_late_events_do_nothing(self):
        other_dialog = gui.ft.AlertDialog(title="another", open=True)
        self.view.close()
        self.page.update.assert_called_once_with(self.view.dialog)
        self.page.pop_dialog.assert_not_called()
        self.assertTrue(other_dialog.open)
        self.page.update.reset_mock()
        self.view.close()
        self.view.show_status("late")
        await self.view.copy()
        self.page.update.assert_not_called()
        self.clipboard.set.assert_not_called()

    async def test_native_dismiss_prevents_late_copy_and_edit(self):
        action = mock.AsyncMock()
        self.view.on_edit = action
        self.view.dialog.on_dismiss(None)
        await self.view.copy()
        await self.view.edit()
        self.clipboard.set.assert_not_called()
        action.assert_not_called()


class FailedTaskFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = gui.ConverterApp.__new__(gui.ConverterApp)
        app.page = dialog_page()
        app.clipboard = SimpleNamespace(set=mock.AsyncMock())
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app._show_notice = mock.Mock()
        app._save_editor_before_action = mock.Mock(return_value=True)
        app._show_page = mock.Mock()
        app._activate_task = mock.AsyncMock()
        app._refresh_queue_view = mock.Mock()
        self.job = app.queue.add(gui.ConversionOptions(Path("broken.mp4"), Path("broken.BIN")))
        app.queue.update(self.job.id, state="failed", error="original error")
        self.app = app

    def open_error(self):
        self.app._show_task_error(self.job.id)
        return self.app.page.show_dialog.call_args.args[0]

    def test_failed_task_has_three_actions_and_a_details_menu(self):
        actions = self.app._task_row_actions(self.job)
        self.assertEqual(3, len(actions))
        menu = actions[-1]
        self.assertIsInstance(menu, gui.ft.PopupMenuButton)
        self.assertEqual(["查看错误详情", "移除任务"], [item.content for item in menu.items])
        menu.items[0].on_click(None)
        self.app.page.show_dialog.assert_called_once()
        self.assertIn("重新排队", actions[1].tooltip)

    async def test_reading_and_copying_a_failure_does_not_change_queue_or_active_task(self):
        self.app.active_task_id = "another-task"
        original = gui.asdict(self.job)
        dialog = self.open_error()
        await dialog.actions[0].on_click(None)
        self.assertEqual(original, gui.asdict(self.job))
        self.assertEqual("another-task", self.app.active_task_id)
        self.app._activate_task.assert_not_called()

    async def test_details_copy_keeps_original_error_after_task_changes(self):
        dialog = self.open_error()
        self.job.error = "replacement error"
        await dialog.actions[0].on_click(None)
        copied = self.app.clipboard.set.call_args.args[0]
        self.assertIn("original error", copied)
        self.assertNotIn("replacement error", copied)

    async def test_edit_targets_reported_task_not_current_active_task(self):
        self.app.active_task_id = "another-task"
        dialog = self.open_error()
        await dialog.actions[-1].on_click(None)
        self.app._show_page.assert_called_once_with(0)
        self.app._activate_task.assert_awaited_once_with(
            self.job.id, scroll_target="parameter-card", preview_errors=False,
        )
        self.assertFalse(dialog.open)
        self.assertEqual("failed", self.job.state)
        await dialog.actions[-1].on_click(None)
        self.app._activate_task.assert_awaited_once()

    async def test_removed_or_frozen_task_cannot_be_edited_from_stale_dialog(self):
        for state in ("removed", "frozen", "running"):
            with self.subTest(state=state):
                self.job.frozen = False
                self.job.state = "failed"
                self.app.queue = gui.ConversionQueue([self.job])
                dialog = self.open_error()
                if state == "removed":
                    self.app.queue.remove(self.job.id)
                elif state == "frozen":
                    self.job.frozen = True
                else:
                    self.job.state = "running"
                await dialog.actions[-1].on_click(None)
                self.app._activate_task.assert_not_called()
                self.assertTrue(dialog.open)
                self.assertTrue(dialog.content.controls[-1].visible)
                self.assertEqual(gui.ft.Colors.ERROR, dialog.content.controls[-1].color)

    async def test_invalid_current_editor_does_not_discard_changes(self):
        self.app._save_editor_before_action.return_value = False
        dialog = self.open_error()
        await dialog.actions[-1].on_click(None)
        self.app._activate_task.assert_not_called()
        self.assertTrue(dialog.open)
        self.assertIn("修正", dialog.content.controls[-1].value)

    async def test_edit_failure_uses_feedback_instead_of_unhandled_exception(self):
        dialog = self.open_error()
        self.app._activate_task.side_effect = RuntimeError("preview failed")
        await dialog.actions[-1].on_click(None)
        self.assertFalse(dialog.open)
        self.assertEqual(2, self.app.page.show_dialog.call_count)
        new_dialog = self.app.page.show_dialog.call_args.args[0]
        self.assertEqual("无法打开任务参数", new_dialog.title.value)

    def test_retry_requeues_and_selects_without_starting_conversion(self):
        self.job.selected = False
        self.app._retry_queue_job(self.job.id)
        self.assertEqual("queued", self.job.state)
        self.assertTrue(self.job.selected)
        self.assertEqual("", self.job.error)
        self.app._show_notice.assert_called_once_with("已重新排队并勾选，点击“转换所选”后开始。")
        self.app._activate_task.assert_not_called()

    def test_late_retry_is_safe_for_removed_frozen_and_completed_tasks(self):
        self.job.frozen = True
        self.app._retry_queue_job(self.job.id)
        self.assertEqual("failed", self.job.state)
        self.assertEqual("original error", self.job.error)
        self.job.frozen = False
        self.job.state = "completed"
        self.app._retry_queue_job(self.job.id)
        self.assertEqual("completed", self.job.state)
        self.app.queue.remove(self.job.id)
        self.app._retry_queue_job(self.job.id)
        self.app._refresh_queue_view.assert_not_called()

    def test_failed_and_cancelled_states_rebuild_different_action_menus(self):
        row = self.app._create_task_row(self.job)
        self.assertIsInstance(row.actions.controls[-1], gui.ft.PopupMenuButton)
        self.job.state = "cancelled"
        self.job.error = ""
        self.assertTrue(self.app._update_task_row(row, self.job))
        self.assertIsInstance(row.actions.controls[-1], gui.ft.IconButton)
        self.job.state = "failed"
        self.assertTrue(self.app._update_task_row(row, self.job))
        self.assertIsInstance(row.actions.controls[-1], gui.ft.PopupMenuButton)

    def test_generic_app_errors_use_the_same_copyable_dialog(self):
        self.app._show_error("无法保存", PermissionError("directory"))
        dialog = self.app.page.show_dialog.call_args.args[0]
        self.assertIn("权限", dialog.content.controls[0].value)
        self.assertEqual(["复制详情", "关闭"], [item.content for item in dialog.actions])


class RecoveryPreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = gui.ConverterApp.__new__(gui.ConverterApp)
        app.page = dialog_page()
        app.page_index = 0
        app.preview = gui.PreviewSession()
        app.preview_lock = asyncio.Lock()
        app.preview_revision = 1
        app.preview_playback_revision = 0
        app.preview_render_revision = 0
        app.preview_play_button = gui.ft.IconButton()
        app.source_info = None
        app.source_info_key = None
        app._options = mock.Mock(return_value=gui.ConversionOptions(
            Path("this-missing-video-does-not-exist.mp4"), Path("result.BIN"),
        ))
        app._set_preview_frame = mock.Mock()
        app._show_error = mock.Mock()
        self.app = app

    async def test_missing_source_during_recovery_clears_old_image_without_another_modal(self):
        await self.app._load_first_preview(show_errors=False)
        self.app._show_error.assert_not_called()
        self.app._set_preview_frame.assert_called_once()
        first, second, label = self.app._set_preview_frame.call_args.args
        self.assertEqual(first, second)
        self.assertIn("预览不可用", label)
        self.assertIsNone(self.app.preview.options)

    async def test_explicit_preview_attempt_still_shows_the_original_exception(self):
        await self.app._load_first_preview()
        self.app._show_error.assert_called_once()
        self.assertIsInstance(self.app._show_error.call_args.args[1], FileNotFoundError)

    async def test_stale_failed_preview_cannot_replace_new_task_image(self):
        async def stale_info(_):
            self.app.preview_revision += 1
            raise FileNotFoundError("old missing file")
        self.app._source_info_for_options = stale_info
        await self.app._load_first_preview(show_errors=False)
        self.app._set_preview_frame.assert_not_called()
        self.app._show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
