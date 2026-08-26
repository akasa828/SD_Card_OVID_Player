import ast
import asyncio
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flet as ft
from flet.controls.base_control import BaseControl
from flet.controls.base_page import BasePage

from converter_dialogs import DialogHost
from converter_preview_ui import PreviewSnapshot
import ovid_converter_gui as gui


def dialog_page():
    page = SimpleNamespace(
        update=mock.Mock(), show_dialog=mock.Mock(), pop_dialog=mock.Mock(),
        width=1120, height=760, shown=[],
    )

    def show(dialog):
        dialog.open = True
        page.shown.append(dialog)

    def pop():
        for dialog in reversed(page.shown):
            if dialog.open:
                dialog.open = False
                return dialog

    page.show_dialog.side_effect = show
    page.pop_dialog.side_effect = pop
    return page


def key_event(key, *, ctrl=False, alt=False, meta=False):
    return SimpleNamespace(key=key, ctrl=ctrl, alt=alt, meta=meta)


class DialogHostTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = dialog_page()
        self.host = DialogHost(self.page)

    def test_alerts_block_shortcuts_but_snackbars_do_not(self):
        self.host.show(ft.SnackBar(content=ft.Text("已复制")))
        self.assertFalse(self.host.has_modal)
        self.host.show(ft.AlertDialog(modal=False, content=ft.Text("可点击外部关闭")))
        self.assertTrue(self.host.has_modal)
        self.host.show(ft.SnackBar(content=ft.Text("转换结束")))
        self.assertTrue(self.host.has_modal)

    def test_programmatic_close_releases_shortcuts_without_waiting_for_client(self):
        dialog = ft.AlertDialog()
        self.host.show(dialog)
        self.page.pop_dialog()
        self.assertFalse(self.host.has_modal)

    async def test_native_dismiss_releases_shortcuts_without_mutating_open(self):
        callback = mock.Mock()
        dialog = ft.AlertDialog(on_dismiss=callback)
        event = SimpleNamespace(data=None)
        self.host.show(dialog)
        await dialog.on_dismiss(event)
        self.assertFalse(self.host.has_modal)
        callback.assert_called_once_with(event)
        self.assertIs(callback, dialog.on_dismiss)

    async def test_async_dismiss_callback_is_awaited(self):
        callback = mock.AsyncMock()
        dialog = ft.AlertDialog(on_dismiss=callback)
        self.host.show(dialog)
        await dialog.on_dismiss(None)
        callback.assert_awaited_once_with(None)
        self.assertFalse(self.host.has_modal)

    async def test_dismissing_top_dialog_keeps_underlying_dialog_blocked(self):
        first, second = ft.AlertDialog(), ft.AlertDialog()
        self.host.show(first)
        self.host.show(second)
        await second.on_dismiss(None)
        self.assertTrue(self.host.has_modal)
        await first.on_dismiss(None)
        self.assertFalse(self.host.has_modal)

    async def test_reused_dialog_ignores_old_duplicate_dismiss_events(self):
        original = mock.Mock()
        dialog = ft.AlertDialog(on_dismiss=original)
        self.host.show(dialog)
        previous_dismiss = dialog.on_dismiss
        await previous_dismiss(None)
        self.host.show(dialog)
        await previous_dismiss(None)
        self.assertTrue(self.host.has_modal)
        original.assert_called_once_with(None)
        await dialog.on_dismiss(None)
        self.assertEqual(2, original.call_count)
        self.assertIs(original, dialog.on_dismiss)

    def test_duplicate_show_preserves_existing_modal_guard(self):
        dialog = ft.AlertDialog()
        self.host.show(dialog)
        dismiss = dialog.on_dismiss
        with self.assertRaises(RuntimeError):
            self.host.show(dialog)
        self.assertTrue(self.host.has_modal)
        self.assertIs(dismiss, dialog.on_dismiss)
        self.page.show_dialog.assert_called_once()

    def test_show_failure_does_not_leave_shortcuts_disabled(self):
        callback = mock.Mock()
        dialog = ft.AlertDialog(on_dismiss=callback)
        self.page.show_dialog.side_effect = RuntimeError("render failed")
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            self.host.show(dialog)
        self.assertFalse(self.host.has_modal)
        self.assertIs(callback, dialog.on_dismiss)
        self.page.show_dialog.side_effect = lambda value: setattr(value, "open", True)
        self.host.show(dialog)
        self.assertTrue(self.host.has_modal)

    async def test_callback_error_does_not_leave_shortcuts_disabled(self):
        callback = mock.Mock(side_effect=ValueError("dismiss failed"))
        dialog = ft.AlertDialog(on_dismiss=callback)
        self.host.show(dialog)
        with self.assertRaisesRegex(ValueError, "dismiss failed"):
            await dialog.on_dismiss(None)
        self.assertFalse(self.host.has_modal)
        self.assertIs(callback, dialog.on_dismiss)

    async def test_flet_managed_dismiss_wrapper_preserves_callbacks_on_reuse(self):
        page = BasePage()
        host = DialogHost(page)
        callback = mock.Mock()
        dialog = ft.AlertDialog(on_dismiss=callback)
        event = SimpleNamespace(data=None)

        async def dispatch(control, name, data):
            self.assertEqual("dismiss", name)
            await control.on_dismiss(data)

        # Exercise Flet's real show/pop/dismiss stack, replacing only transport.
        with mock.patch.object(BaseControl, "update"), mock.patch.object(ft.AlertDialog, "_trigger_event", dispatch):
            for close_in_python in (False, True):
                host.show(dialog)
                self.assertTrue(host.has_modal)
                native_callback = dialog.on_dismiss
                if close_in_python:
                    self.assertIs(dialog, page.pop_dialog())
                    self.assertFalse(host.has_modal)
                await native_callback(event)
                self.assertFalse(host.has_modal)
                self.assertIs(callback, dialog.on_dismiss)
        self.assertEqual(2, callback.call_count)


class ShortcutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        self.app.page = dialog_page()
        self.app.clipboard = SimpleNamespace(set=mock.AsyncMock())
        self.app.dialog_host = DialogHost(self.app.page)
        self.app.exit_dialog_open = False
        self.app.exit_dialog = None
        self.app.page_index = 0
        self.app.convert_button = SimpleNamespace(disabled=False)
        self.actions = (
            "_choose_file", "_choose_ovid_file", "_start_conversion", "_toggle_player",
            "_player_previous", "_player_next", "_player_first",
        )
        for name in self.actions:
            setattr(self.app, name, mock.AsyncMock())

    async def exercise_all_shortcuts(self):
        for page_index in (0, 1):
            self.app.page_index = page_index
            for key in ("O", "Enter"):
                await self.app._on_keyboard_event(key_event(key, ctrl=True))
            for key in ("Space", "Arrow Left", "Arrow Right", "Home"):
                await self.app._on_keyboard_event(key_event(key))

    def assert_no_action(self):
        for name in self.actions:
            getattr(self.app, name).assert_not_awaited()

    async def test_modal_dialog_blocks_all_background_shortcuts(self):
        self.app._show_message("完成", "转换完成")
        await self.exercise_all_shortcuts()
        self.assert_no_action()
        self.app.page.pop_dialog()
        self.app.page_index = 0
        await self.app._on_keyboard_event(key_event("Enter", ctrl=True))
        self.app._start_conversion.assert_awaited_once_with(None)

    async def test_native_dismiss_restores_shortcuts(self):
        self.app._show_error("错误", ValueError("无法读取"))
        await self.exercise_all_shortcuts()
        self.assert_no_action()
        await self.app.page.shown[-1].on_dismiss(None)
        self.app.page_index = 1
        await self.app._on_keyboard_event(key_event("Space"))
        self.app._toggle_player.assert_awaited_once_with(None)

    async def test_status_snackbar_does_not_block_shortcuts(self):
        self.app._show_notice("已保存")
        await self.app._on_keyboard_event(key_event("O", ctrl=True))
        self.app._choose_file.assert_awaited_once_with(None)

    async def test_file_shortcut_uses_current_page(self):
        await self.app._on_keyboard_event(key_event("O", ctrl=True))
        self.app._choose_file.assert_awaited_once_with(None)
        self.app._choose_ovid_file.assert_not_awaited()
        self.app.page_index = 1
        await self.app._on_keyboard_event(key_event("o", ctrl=True))
        self.app._choose_ovid_file.assert_awaited_once_with(None)
        self.app._choose_file.assert_awaited_once()

    async def test_conversion_shortcut_only_works_on_conversion_page(self):
        for page_index in (1, 2, 3):
            self.app.page_index = page_index
            await self.app._on_keyboard_event(key_event("Enter", ctrl=True))
        self.app._start_conversion.assert_not_awaited()
        self.app.page_index = 0
        for key in ("Enter", "Return", "Numpad Enter"):
            await self.app._on_keyboard_event(key_event(key, ctrl=True))
        self.assertEqual(3, self.app._start_conversion.await_count)

    async def test_settings_and_about_do_not_trigger_import_or_playback(self):
        for page_index in (2, 3):
            self.app.page_index = page_index
            await self.app._on_keyboard_event(key_event("O", ctrl=True))
            for key in ("Space", "Arrow Left", "Arrow Right", "Home"):
                await self.app._on_keyboard_event(key_event(key))
        self.assert_no_action()

    async def test_disabled_conversion_and_exit_confirmation_ignore_shortcuts(self):
        self.app.convert_button.disabled = True
        await self.app._on_keyboard_event(key_event("Enter", ctrl=True))
        self.app.exit_dialog_open = True
        await self.exercise_all_shortcuts()
        self.assert_no_action()

    async def test_alt_and_meta_combinations_are_not_claimed(self):
        for modifier in ("alt", "meta"):
            await self.app._on_keyboard_event(key_event("O", ctrl=True, **{modifier: True}))
            self.app.page_index = 1
            await self.app._on_keyboard_event(key_event("Space", **{modifier: True}))
        self.assert_no_action()

    async def test_pixel_inspector_registers_and_preserves_its_dismiss_handler(self):
        self.app.preview_snapshot = PreviewSnapshot(b"png", 128, 64, "frame")
        self.app.pixel_inspector = None
        self.app._inspect_preview_frame(None)
        self.assertTrue(self.app.dialog_host.has_modal)
        await self.exercise_all_shortcuts()
        self.assert_no_action()
        inspector = self.app.pixel_inspector
        await inspector.dialog.on_dismiss(None)
        self.assertTrue(inspector.closed)
        self.assertFalse(self.app.dialog_host.has_modal)

    async def test_trim_dismiss_handler_still_prevents_late_apply(self):
        app = self.app
        app.active_task_id = "job"
        app.preview_revision = 4
        app.trim_slider = ft.RangeSlider(min=0, max=10, start_value=1, end_value=9)
        app._can_edit_task = mock.Mock(return_value=True)
        app._apply_trim_range = mock.AsyncMock()
        app._edit_trim_dialog(None)
        dialog = app.page.shown[-1]
        self.assertTrue(app.dialog_host.has_modal)
        await dialog.on_dismiss(None)
        await dialog.actions[-1].on_click(None)
        app._apply_trim_range.assert_not_awaited()
        self.assertFalse(app.dialog_host.has_modal)

    def test_logs_and_preset_confirmation_use_the_shared_host(self):
        self.app.logger = SimpleNamespace(read=lambda: "log")
        self.app._show_logs(None)
        self.assertTrue(self.app.dialog_host.has_modal)
        self.app.page.pop_dialog()
        self.app._confirm_preset_action("删除？", "确认", "删除", mock.Mock())
        self.assertTrue(self.app.dialog_host.has_modal)

    def test_gui_has_no_dialog_presentations_bypassing_the_host(self):
        tree = ast.parse(Path(gui.__file__).read_text(encoding="utf-8-sig"))
        bypasses = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "show_dialog"
        ]
        self.assertEqual([], bypasses)


class ExitDialogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = gui.ConverterApp.__new__(gui.ConverterApp)
        self.app.page = dialog_page()
        self.app.busy = True
        self.app.exit_dialog_open = False
        self.app.exit_dialog = None
        self.app.exit_after_conversion_stop = False
        self.app._cancel_conversion = mock.Mock()
        self.app._shutdown_and_exit = mock.AsyncMock()
        self.app.task_action_status = ft.Text()

    async def request_exit(self):
        await self.app._on_window_event(SimpleNamespace(type=ft.WindowEventType.CLOSE))
        return self.app.page.shown[-1]

    async def test_native_dismiss_allows_exit_confirmation_again(self):
        first = await self.request_exit()
        await first.on_dismiss(None)
        self.assertFalse(self.app.exit_dialog_open)
        second = await self.request_exit()
        self.assertIsNot(first, second)
        self.assertTrue(self.app.exit_dialog_open)
        self.app._cancel_conversion.assert_not_called()

    async def test_repeated_close_does_not_open_duplicate_confirmation(self):
        await self.request_exit()
        await self.request_exit()
        self.app.page.show_dialog.assert_called_once()

    async def test_old_dismiss_and_actions_cannot_close_new_confirmation(self):
        first = await self.request_exit()
        first.actions[0].on_click(None)
        second = await self.request_exit()
        await first.on_dismiss(None)
        first.actions[0].on_click(None)
        await first.actions[1].on_click(None)
        self.assertTrue(self.app.exit_dialog_open)
        self.assertTrue(second.open)
        self.app._cancel_conversion.assert_not_called()

    async def test_continue_closes_only_its_own_dialog(self):
        dialog = await self.request_exit()
        self.app._show_notice("任务状态已更新")
        notice = self.app.page.shown[-1]
        dialog.actions[0].on_click(None)
        self.assertFalse(dialog.open)
        self.assertTrue(notice.open)
        self.assertFalse(self.app.exit_dialog_open)
        self.app.page.pop_dialog.assert_not_called()

    async def test_confirm_exit_is_an_async_callback_and_cancels_once(self):
        dialog = await self.request_exit()
        confirm = dialog.actions[1].on_click
        self.assertTrue(inspect.iscoroutinefunction(confirm))
        await confirm(None)
        await confirm(None)
        self.assertFalse(dialog.open)
        self.assertTrue(self.app.exit_after_conversion_stop)
        self.app._cancel_conversion.assert_called_once_with(None)
        self.app._shutdown_and_exit.assert_not_awaited()

    async def test_conversion_finished_during_confirmation_exits_without_cancelling(self):
        dialog = await self.request_exit()
        self.app.busy = False
        await dialog.actions[1].on_click(None)
        self.app._shutdown_and_exit.assert_awaited_once()
        self.app._cancel_conversion.assert_not_called()

    async def test_failed_presentation_does_not_latch_exit_flag(self):
        self.app.page.show_dialog.side_effect = RuntimeError("cannot show")
        with self.assertRaisesRegex(RuntimeError, "cannot show"):
            await self.request_exit()
        self.assertFalse(self.app.exit_dialog_open)


if __name__ == "__main__":
    unittest.main()
