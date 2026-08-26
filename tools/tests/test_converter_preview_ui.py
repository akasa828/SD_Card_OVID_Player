import asyncio
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import converter_preview_ui as preview_ui
import ovid_converter_gui as gui
from media2ovid import preview_png


class PreviewModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = gui.ConverterApp.__new__(gui.ConverterApp)
        app.settings = gui.AppSettings()
        app.preset_store = mock.Mock()
        app.preset_store.all_presets.return_value = gui.BUILTIN_PRESETS
        app.page = SimpleNamespace(update=mock.Mock(), show_dialog=mock.Mock(), width=1120, height=760)
        app.page.show_dialog.side_effect = lambda dialog: setattr(dialog, "open", True)
        app.queue = gui.ConversionQueue()
        app.active_task_id = None
        app.page_index = 0
        app._build_controls()
        app.compact_layout = False
        app.preview_revision = 1
        app.preview_render_revision = 0
        app.preview_playback_revision = 0
        app.preview_playing = True
        app.preview_timeline_dragging = False
        app.preview = SimpleNamespace(options=gui.ConversionOptions(Path("clip.mp4"), Path("clip.BIN")))
        app.source_info = SimpleNamespace(duration_seconds=10)
        app._load_first_preview = mock.AsyncMock()
        app._rerender_current_preview = mock.AsyncMock()
        app._show_notice = mock.Mock()
        self.app = app

    def choose_mode(self, value):
        self.app.preview_view_mode.selected = [value]
        self.app.preview_view_mode.on_change(None)

    def test_single_modes_use_all_available_preview_panel_width(self):
        self.choose_mode("oled")
        self.assertEqual([self.app.oled_preview_panel], self.app.preview_panels.controls)
        self.assertTrue(self.app.oled_preview_panel.expand)
        self.choose_mode("source")
        self.assertEqual([self.app.original_preview_panel], self.app.preview_panels.controls)
        self.choose_mode("compare")
        self.assertEqual(
            [self.app.original_preview_panel, self.app.oled_preview_panel], self.app.preview_panels.controls,
        )

    def test_switching_modes_does_not_decode_or_modify_parameters_or_frame_data(self):
        app = self.app
        app._set_preview_frame(b"original", b"oled", "frame", index=1)
        image = app.preview_image
        options = app.preview.options
        revision = (app.preview_revision, app.preview_render_revision, app.preview_playback_revision)
        for mode in ("oled", "source", "compare"):
            self.choose_mode(mode)
        self.assertIs(image, app.preview_image)
        self.assertIs(options, app.preview.options)
        self.assertEqual(b"oled", app.preview_image.src)
        self.assertEqual(b"original", app.original_preview_image.src)
        self.assertEqual(revision, (app.preview_revision, app.preview_render_revision, app.preview_playback_revision))
        self.assertTrue(app.preview_playing)
        app._load_first_preview.assert_not_called()
        app._rerender_current_preview.assert_not_called()

    def test_hidden_image_receives_latest_frame_without_detached_control_update(self):
        app = self.app
        self.choose_mode("oled")
        app.page.update.reset_mock()
        app._set_preview_frame(b"new source", b"new oled", "frame", index=2)
        self.assertNotIn(app.original_preview_image, app.page.update.call_args.args)
        self.assertIn(app.preview_image, app.page.update.call_args.args)
        self.assertEqual(b"new source", app.original_preview_image.src)
        self.choose_mode("source")
        self.assertEqual(b"new source", app.original_preview_panel.controls[1].content.src)
        app.page.update.reset_mock()
        app._set_preview_frame(b"source 3", b"oled 3", "frame", index=3)
        self.assertNotIn(app.preview_image, app.page.update.call_args.args)

    def test_off_page_mode_and_frame_changes_do_not_patch_detached_controls(self):
        self.app.page_index = 2
        self.choose_mode("oled")
        self.app._set_preview_frame(b"source", b"oled", "frame", index=1)
        self.app.page.update.assert_not_called()
        self.assertEqual([self.app.oled_preview_panel], self.app.preview_panels.controls)

    def test_invalid_mode_falls_back_to_comparison(self):
        self.choose_mode("invalid")
        self.assertEqual(["compare"], self.app.preview_view_mode.selected)
        self.app.preview_view_mode.selected = []
        self.app._on_preview_view_mode(None)
        self.assertEqual(2, len(self.app.preview_panels.controls))

    def test_frame_update_follows_mounted_panels_while_mode_event_is_pending(self):
        self.choose_mode("oled")
        self.app.preview_view_mode.selected = ["source"]
        self.app.page.update.reset_mock()
        self.app._set_preview_frame(b"source", b"oled", "frame", index=1)
        self.assertIn(self.app.preview_image, self.app.page.update.call_args.args)
        self.assertNotIn(self.app.original_preview_image, self.app.page.update.call_args.args)

    def test_frame_snapshot_uses_decoded_options_not_unsaved_fields(self):
        app = self.app
        app.width_field.value = "250"
        app.preview.options = gui.replace(app.preview.options, width=96, height=32)
        app._set_preview_frame(b"source", b"oled", "第 2 帧", index=2)
        self.assertEqual((96, 32), (app.preview_snapshot.width, app.preview_snapshot.height))
        self.assertIn("clip.mp4", app.preview_snapshot.caption)
        self.assertFalse(app.inspect_preview_button.disabled)

    def test_no_frame_and_failed_frame_disable_inspection(self):
        app = self.app
        self.assertTrue(app.inspect_preview_button.disabled)
        app._inspect_preview_frame(None)
        app.page.show_dialog.assert_not_called()
        app._set_preview_frame(b"source", b"oled", "frame", index=1)
        app._set_preview_frame(b"blank", b"blank", "failed")
        self.assertIsNone(app.preview_snapshot)
        self.assertTrue(app.inspect_preview_button.disabled)

    def test_new_source_disables_inspection_of_previous_video(self):
        self.app._set_preview_frame(b"source", b"oled", "frame", index=1)
        self.app._set_source(Path("new.mp4"))
        self.assertIsNone(self.app.preview_snapshot)
        self.assertTrue(self.app.inspect_preview_button.disabled)

    def test_inspection_keeps_captured_frame_while_playback_advances(self):
        app = self.app
        app._set_preview_frame(b"source", b"first", "first", index=1)
        app._inspect_preview_frame(None)
        dialog = app.page.show_dialog.call_args.args[0]
        viewer = dialog.content.controls[2]
        app._set_preview_frame(b"source", b"second", "second", index=2)
        self.assertEqual(b"first", viewer.content.content.src)
        self.assertEqual(b"second", app.preview_image.src)

    def test_duplicate_inspect_click_does_not_stack_dialogs(self):
        app = self.app
        app._set_preview_frame(b"source", b"frame", "frame", index=1)
        app._inspect_preview_frame(None)
        app._inspect_preview_frame(None)
        app.page.show_dialog.assert_called_once()
        app.pixel_inspector.close()
        app._inspect_preview_frame(None)
        self.assertEqual(2, app.page.show_dialog.call_count)

    def test_resize_in_single_mode_updates_only_the_visible_image(self):
        app = self.app
        app.source_field.value = "clip.mp4"
        app._sync_convert_sections()
        app.page.window = SimpleNamespace(width=1120, height=760)
        app.page.navigation_bar = None
        self.choose_mode("oled")
        app._on_resize()
        app.page.update.reset_mock()
        app.page.height = 700
        app._on_resize()
        self.assertEqual((app.preview_image,), app.page.update.call_args.args)
        self.assertEqual(app.original_preview_image.height, app.preview_image.height)


class PixelInspectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = SimpleNamespace(width=1120, height=760, update=mock.Mock(), show_dialog=mock.Mock())
        self.page.show_dialog.side_effect = lambda dialog: setattr(dialog, "open", True)
        image = Image.new("RGB", (96, 32), "black")
        image.putpixel((2, 3), (255, 255, 255))
        options = gui.ConversionOptions(Path("source.png"), Path("out.BIN"), width=96, height=32)
        self.png = preview_png(image, options)
        self.snapshot = preview_ui.PreviewSnapshot(self.png, 96, 32, "source.png · 第 1 帧")
        self.inspector = preview_ui.PixelInspector(self.page, self.snapshot)
        self.inspector.viewer.reset = mock.AsyncMock()
        self.inspector.show()

    def test_viewport_is_bounded_for_small_large_and_invalid_windows(self):
        self.assertEqual((552, 300), preview_ui.inspector_viewport(680, 600))
        self.assertEqual((1000, 520), preview_ui.inspector_viewport(2560, 1440))
        for value in (None, "bad", float("nan"), float("inf"), -1):
            self.assertEqual((992, 460), preview_ui.inspector_viewport(value, value))

    async def test_integer_zoom_changes_only_display_geometry(self):
        for scale in (1, 2, 4, 8):
            await self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value=str(scale))))
            self.assertEqual((96 * scale, 32 * scale), (self.inspector.image.width, self.inspector.image.height))
            self.assertIs(self.png, self.inspector.image.src)
            self.assertGreaterEqual(self.inspector.canvas.width, self.inspector.viewer.width)
            self.assertGreaterEqual(self.inspector.canvas.height, self.inspector.viewer.height)
        with Image.open(io.BytesIO(self.inspector.image.src)) as result:
            self.assertEqual((384, 128), result.size)
            self.assertEqual(255, result.convert("L").getpixel((8, 12)))
            self.assertEqual(0, result.convert("L").getpixel((0, 0)))

    def test_viewer_allows_panning_without_fractional_gesture_zoom(self):
        viewer = self.inspector.viewer
        self.assertFalse(viewer.constrained)
        self.assertFalse(viewer.scale_enabled)
        self.assertTrue(viewer.pan_enabled)
        self.assertEqual((1, 1), (viewer.min_scale, viewer.max_scale))
        self.assertEqual(gui.ft.ClipBehavior.HARD_EDGE, viewer.clip_behavior)
        self.assertTrue(self.inspector.dialog.scrollable)
        self.assertEqual(gui.ft.FilterQuality.NONE, self.inspector.image.filter_quality)
        self.assertFalse(self.inspector.image.anti_alias)

    async def test_invalid_scales_do_not_change_pixel_size(self):
        for value in (None, "", "1.5", "bad", "-1", "100"):
            await self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value=value)))
            self.assertEqual(4, self.inspector.scale)
            self.assertEqual("4", self.inspector.scale_picker.value)
        self.inspector.viewer.reset.assert_not_called()

    async def test_closed_inspector_ignores_late_zoom_and_does_not_pop_other_dialog(self):
        self.inspector.close()
        self.page.update.assert_called_once_with(self.inspector.dialog)
        self.page.update.reset_mock()
        await self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value="8")))
        self.inspector.close()
        self.page.update.assert_not_called()
        self.inspector.viewer.reset.assert_not_called()

    async def test_native_dismiss_ignores_late_zoom(self):
        self.inspector.dialog.on_dismiss(None)
        await self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value="8")))
        self.page.update.assert_not_called()

    async def test_viewer_timeout_reports_inline_without_another_dialog(self):
        self.inspector.viewer.reset.side_effect = TimeoutError("client timed out")
        await self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value="8")))
        self.assertTrue(self.inspector.status.visible)
        self.assertIn("重新查看", self.inspector.status.value)
        self.page.show_dialog.assert_called_once()

    async def test_late_viewer_timeout_does_not_update_closed_dialog(self):
        gate = asyncio.Event()
        async def reset():
            await gate.wait()
            raise TimeoutError("client timed out")
        self.inspector.viewer.reset.side_effect = reset
        task = asyncio.create_task(self.inspector.change_scale(SimpleNamespace(control=SimpleNamespace(value="8"))))
        await asyncio.sleep(0)
        self.inspector.close()
        self.page.update.reset_mock()
        gate.set()
        await task
        self.page.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
