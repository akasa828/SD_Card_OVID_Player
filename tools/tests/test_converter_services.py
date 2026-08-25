import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import converter_services as services  # noqa: E402
import media2ovid  # noqa: E402
import ovid_codec  # noqa: E402
from ovid_player import OvidPlaybackSession, page_major_to_image  # noqa: E402


try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


@unittest.skipIf(Image is None, "Pillow is not installed")
class ConverterServicesTests(unittest.TestCase):
    def options(self, root: Path, **changes):
        source = root / "source.png"
        if not source.exists():
            Image.new("L", (8, 8), 128).save(source)
        values = dict(source=source, output=root / "output.BIN", width=8, height=8, fps=15)
        values.update(changes)
        return media2ovid.ConversionOptions(**values)

    def test_otsu_suggestions_are_clamped_and_ordered(self):
        image = Image.new("L", (4, 1))
        image.putdata([0, 32, 224, 255])
        dark = services.suggested_threshold(image, "dark-detail")
        standard = services.suggested_threshold(image, "standard")
        noise = services.suggested_threshold(image, "noise-reduction")
        self.assertLessEqual(dark, standard)
        self.assertLessEqual(standard, noise)
        self.assertTrue(0 <= dark <= 255)
        self.assertTrue(0 <= noise <= 255)

    def test_user_presets_round_trip_without_overwriting_builtins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = services.PresetStore(root / "presets.json")
            preset = services.ConversionPreset("My OLED", width=96, height=64, fps=20)
            store.upsert(preset)
            self.assertEqual([preset], store.load_user_presets())
            store.upsert(services.ConversionPreset("My OLED", width=128, height=32))
            self.assertEqual(128, store.load_user_presets()[0].width)
            with self.assertRaisesRegex(ValueError, "内置预设"):
                store.upsert(services.BUILTIN_PRESETS[0])
            store.reset()
            self.assertEqual([], store.load_user_presets())

    def test_invalid_user_preset_does_not_hide_valid_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presets.json"
            path.write_text(
                json.dumps(
                    [
                        {"name": "Broken", "width": 0},
                        {"name": "Good", "width": 96, "height": 64, "fps": 20},
                        {"name": "Unknown field", "future_option": True},
                    ]
                ),
                encoding="utf-8",
            )
            store = services.PresetStore(path)

            presets = store.load_user_presets()

            self.assertEqual(["Good"], [preset.name for preset in presets])

    def test_user_preset_validation_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = services.PresetStore(Path(directory) / "presets.json")
            with self.assertRaisesRegex(ValueError, "FPS"):
                store.upsert(services.ConversionPreset("Too fast", fps=121))
            with self.assertRaisesRegex(ValueError, "黑白算法"):
                store.upsert(services.ConversionPreset("Unknown", dither="random"))

    def test_queue_snapshots_options_and_generates_unique_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = self.options(root)
            options.output.write_bytes(b"existing")
            queue = services.ConversionQueue()
            job = queue.add(options)
            self.assertEqual("output_2.BIN", job.options.output.name)
            queue.update(job.id, state="failed", error="test")
            queue.retry(job.id)
            self.assertEqual("queued", job.state)
            self.assertEqual("", job.error)

    def test_queue_reserves_duplicate_outputs_before_files_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = self.options(root, output=root / "movie.BIN")
            queue = services.ConversionQueue()
            first = queue.add(options, target_profile="stm32f103-128x32")
            second = queue.add(options, target_profile="stm32f103-96x64")
            self.assertEqual("movie.BIN", first.options.output.name)
            self.assertEqual("movie_2.BIN", second.options.output.name)
            self.assertEqual("stm32f103-128x32", first.target_profile)
            self.assertEqual("stm32f103-96x64", second.target_profile)

    def test_queue_freezes_only_selected_jobs_for_a_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            first = queue.add(self.options(root, output=root / "first.BIN"))
            second = queue.add(self.options(root, output=root / "second.BIN"))
            queue.set_selected(second.id, False)

            frozen = queue.freeze_selected()

            self.assertEqual((first,), frozen)
            self.assertTrue(first.frozen)
            self.assertFalse(second.frozen)
            queue.unfreeze(first.id)
            self.assertFalse(first.frozen)

    def test_completed_job_uses_a_new_output_when_overwrite_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            job = queue.add(self.options(root))
            job.options.output.write_bytes(b"completed")
            queue.update(job.id, state="completed")

            frozen = queue.freeze_selected()

            self.assertEqual((job,), frozen)
            self.assertEqual("output_2.BIN", job.options.output.name)
            self.assertEqual("queued", job.state)

    def test_completed_job_keeps_output_when_overwrite_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            job = queue.add(self.options(root, force=True))
            job.options.output.write_bytes(b"completed")
            queue.update(job.id, state="completed")

            queue.freeze_selected()

            self.assertEqual("output.BIN", job.options.output.name)

    def test_queue_option_edits_reset_completed_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            job = queue.add(self.options(root))
            queue.update(job.id, state="completed")
            changed = self.options(root, width=16, output=job.options.output)

            queue.replace_options(job.id, changed, target_profile="stm32f103-128x32")

            self.assertEqual("queued", job.state)
            self.assertEqual(16, job.options.width)
            self.assertEqual("stm32f103-128x32", job.target_profile)

    def test_completed_queue_job_is_not_selected_for_the_next_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            job = queue.add(self.options(root))
            summary = ovid_codec.OvidSummary(
                job.options.output,
                8,
                8,
                1,
                15,
                8,
                28,
                ovid_codec.OVID_V2,
            )

            queue.complete(job.id, summary)

            self.assertEqual("completed", job.state)
            self.assertFalse(job.selected)
            self.assertIs(summary, job.summary)

    def test_conversion_logger_releases_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = services.ConversionLogger(Path(directory))
            handlers = tuple(logger.logger.handlers)
            self.assertTrue(handlers)
            with mock.patch.object(handlers[0], "close", wraps=handlers[0].close) as close:
                logger.close()
            self.assertEqual([], logger.logger.handlers)
            close.assert_called_once()

    def test_frozen_queue_jobs_cannot_be_edited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = services.ConversionQueue()
            job = queue.add(self.options(root))
            queue.freeze_selected()
            with self.assertRaisesRegex(ValueError, "不能修改"):
                queue.replace_options(job.id, self.options(root, width=16))

    def test_compatibility_reports_screen_and_filename_problems(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = self.options(
                root,
                width=128,
                height=64,
                output=root / (("A" * 70) + ".BIN"),
            )
            info = media2ovid.probe_source(options)
            report = services.check_compatibility(options, info, "stm32f103-128x32")
            self.assertFalse(report.can_convert)
            self.assertEqual(1024, report.frame_bytes)
            self.assertIn("screen-size", {issue.code for issue in report.issues})
            self.assertIn("filename", {issue.code for issue in report.issues})

    def test_player_holds_previous_frame_when_crc_is_bad(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "player.BIN"
            frames = [bytes([0x01] * 8), bytes([0xFF] * 8)]
            ovid_codec.write_ovid(output, frames, 8, 8, 15)
            damaged = bytearray(output.read_bytes())
            damaged[ovid_codec.HEADER_SIZE + 12] ^= 0x01
            output.write_bytes(damaged)
            session = OvidPlaybackSession()
            session.open(output)
            first = session.read(0)
            second = session.read(1)
            self.assertTrue(first.crc_valid)
            self.assertFalse(second.crc_valid)
            self.assertTrue(second.held_previous)
            self.assertEqual(first.png, second.png)
            session.close()

    def test_player_seeks_directly_to_a_valid_frame(self):
        session = OvidPlaybackSession()
        session.header = SimpleNamespace(
            frame_count=100,
            frame_bytes=8,
            width=8,
            height=8,
        )
        session.reader = mock.Mock()
        session.reader.read_frame.return_value = ovid_codec.OvidFrame(
            99,
            bytes([0xFF] * 8),
            True,
        )

        with mock.patch("ovid_player.frame_png", return_value=b"frame"):
            result = session.seek(99)

        self.assertEqual(99, result.index)
        session.reader.read_frame.assert_called_once_with(99)

    def test_player_seeks_back_only_when_the_target_crc_is_bad(self):
        session = OvidPlaybackSession()
        session.header = SimpleNamespace(
            frame_count=10,
            frame_bytes=8,
            width=8,
            height=8,
        )
        session.reader = mock.Mock()
        session.reader.read_frame.side_effect = [
            ovid_codec.OvidFrame(5, bytes(8), False),
            ovid_codec.OvidFrame(4, bytes(8), False),
            ovid_codec.OvidFrame(3, bytes([0x55] * 8), True),
        ]

        with mock.patch("ovid_player.frame_png", return_value=b"held"):
            result = session.seek(5)

        self.assertFalse(result.crc_valid)
        self.assertTrue(result.held_previous)
        self.assertEqual(
            [mock.call(5), mock.call(4), mock.call(3)],
            session.reader.read_frame.call_args_list,
        )

    def test_page_major_decoder_handles_odd_height(self):
        image = page_major_to_image(bytes([0x01, 0x00, 0x00, 0x01]), 2, 9)
        self.assertEqual(255, image.getpixel((0, 0)))
        self.assertEqual(255, image.getpixel((1, 8)))


if __name__ == "__main__":
    unittest.main()
