import tempfile
import sys
import unittest
from pathlib import Path


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

    def test_page_major_decoder_handles_odd_height(self):
        image = page_major_to_image(bytes([0x01, 0x00, 0x00, 0x01]), 2, 9)
        self.assertEqual(255, image.getpixel((0, 0)))
        self.assertEqual(255, image.getpixel((1, 8)))


if __name__ == "__main__":
    unittest.main()
