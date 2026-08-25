import contextlib
import io
import struct
import sys
import tempfile
import threading
import unittest
import random
from unittest import mock
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import h2bin  # noqa: E402
import media2ovid  # noqa: E402


try:
    from PIL import Image
except ImportError:  # pragma: no cover - CI installs converter requirements
    Image = None


@unittest.skipIf(Image is None, "Pillow is not installed")
class MediaToOvidTests(unittest.TestCase):

    def test_preview_video_uses_fast_timestamp_seeking(self):
        options = media2ovid.ConversionOptions(
            Path("clip.mp4"),
            Path("output.bin"),
            fps=30,
            trim_start_seconds=42.5,
        )
        info = media2ovid.SourceInfo("video", 1, 1 / 30, 30.0, (1920, 1080))
        frame = object()
        with mock.patch.object(
            media2ovid,
            "_iter_video_fast",
            return_value=iter([frame]),
        ) as fast:
            self.assertEqual([frame], list(media2ovid.iter_preview_images(options, info)))
        preview_options = fast.call_args.args[0]
        self.assertTrue(preview_options.fast_video)
        self.assertEqual(42.5, preview_options.trim_start_seconds)

    def test_ffmpeg_version_is_available_for_conversion_logs(self):
        try:
            version = media2ovid.ffmpeg_version()
        except media2ovid.ConverterDependencyError:
            self.skipTest("imageio-ffmpeg is not installed")
        self.assertTrue(version)

    def options(self, source: Path, output: Path, **changes):
        values = dict(source=source, output=output, width=8, height=8, fps=2)
        values.update(changes)
        return media2ovid.ConversionOptions(**values)

    def test_fixed_threshold_is_the_library_and_cli_default(self):
        options = media2ovid.ConversionOptions(Path("input.png"), Path("output.bin"))
        arguments = media2ovid.build_parser().parse_args(["input.png", "output.bin"])
        self.assertEqual("threshold", options.dither)
        self.assertEqual("threshold", arguments.dither)

    def test_monochrome_pixels_are_packed_page_major(self):
        image = Image.new("1", (2, 9), 0)
        image.putpixel((0, 0), 1)
        image.putpixel((0, 7), 1)
        image.putpixel((1, 8), 1)
        self.assertEqual(
            media2ovid.monochrome_to_page_major(image),
            bytes([0x81, 0x00, 0x00, 0x01]),
        )

    def test_fast_page_packer_matches_pixel_reference(self):
        randomizer = random.Random(20260822)
        for width, height in ((1, 1), (7, 9), (13, 17), (96, 64), (128, 128)):
            image = Image.new("1", (width, height), 0)
            for y in range(height):
                for x in range(width):
                    image.putpixel((x, y), randomizer.randrange(2))
            expected = bytearray(width * ((height + 7) // 8))
            for page in range((height + 7) // 8):
                for x in range(width):
                    for bit in range(8):
                        y = page * 8 + bit
                        if y < height and image.getpixel((x, y)):
                            expected[page * width + x] |= 1 << bit
            self.assertEqual(bytes(expected), media2ovid.monochrome_to_page_major(image))

    def test_image_conversion_writes_valid_v2_atomically(self):
        with tempfile.TemporaryDirectory(prefix="OVID 中文 path ") as directory:
            root = Path(directory)
            source = root / "source image.png"
            output = root / "结果.BIN"
            Image.new("RGB", (16, 8), "white").save(source)
            summary = media2ovid.convert_media(self.options(source, output))
            self.assertEqual(summary.frame_count, 1)
            self.assertFalse(output.with_name(output.name + ".part").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h2bin.cmd_info(type("Args", (), {"file": str(output)})()), 0)

    def test_directory_uses_natural_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            for name, value in (("frame10.png", 10), ("frame2.png", 2), ("frame1.png", 1)):
                Image.new("L", (1, 1), value).save(frames / name)
            ordered = [path.name for path in media2ovid.image_files(frames)]
            self.assertEqual(ordered, ["frame1.png", "frame2.png", "frame10.png"])
            summary = media2ovid.convert_media(
                self.options(frames, root / "sequence.bin", dither="threshold")
            )
            self.assertEqual(summary.frame_count, 3)

    def test_skip_frames_removes_only_the_leading_output_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            for index in range(5):
                Image.new("L", (8, 8), index * 50).save(frames / f"{index}.png")
            options = self.options(
                frames,
                root / "trimmed.bin",
                dither="threshold",
                threshold=75,
                skip_frames=2,
            )
            info = media2ovid.probe_source(options)
            summary = media2ovid.convert_media(options)
            self.assertEqual(3, info.frame_count)
            self.assertEqual(3, summary.frame_count)

    def test_skip_frames_rejects_empty_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            Image.new("1", (8, 8), 1).save(source)
            options = self.options(source, root / "output.bin", skip_frames=1)
            with self.assertRaisesRegex(ValueError, "没有可转换的画面"):
                media2ovid.probe_source(options)

    def test_trim_uses_inclusive_start_and_exclusive_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            for index in range(10):
                Image.new("L", (8, 8), index * 25).save(frames / f"{index}.png")
            options = self.options(
                frames,
                root / "trim.bin",
                fps=2,
                trim_start_seconds=1.0,
                trim_end_seconds=3.5,
            )
            info = media2ovid.probe_source(options)
            summary = media2ovid.convert_media(options, source_info=info)
            self.assertEqual(5, info.frame_count)
            self.assertEqual(5, summary.frame_count)

    def test_parallel_conversion_matches_single_thread_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            for index in range(12):
                image = Image.new("L", (24, 16), index * 17)
                image.save(frames / f"frame{index}.png")
            single = self.options(frames, root / "single.bin", width=16, height=16, workers=1)
            parallel = self.options(frames, root / "parallel.bin", width=16, height=16, workers=4)
            media2ovid.convert_media(single)
            media2ovid.convert_media(parallel)
            self.assertEqual(single.output.read_bytes(), parallel.output.read_bytes())

    def test_contain_cover_stretch_threshold_and_invert(self):
        source = Image.new("L", (4, 2), 255)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.png"
            source.save(path)
            for fit in ("contain", "cover", "stretch"):
                options = self.options(
                    path,
                    Path(directory) / f"{fit}.bin",
                    fit=fit,
                    dither="threshold",
                    threshold=127,
                    invert=True,
                )
                data = media2ovid.process_image(source, options)
                self.assertEqual(len(data), h2bin.frame_bytes(8, 8))

    def test_threshold_boundary_and_floyd_dithering_are_binary(self):
        source = Image.new("L", (4, 1))
        source.putdata([64, 127, 128, 200])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            threshold_options = self.options(
                root / "source.png",
                root / "threshold.bin",
                width=4,
                height=1,
                dither="threshold",
                threshold=128,
                fit="stretch",
            )
            floyd_options = self.options(
                root / "source.png",
                root / "floyd.bin",
                width=4,
                height=1,
                dither="floyd",
                fit="stretch",
            )
            threshold = media2ovid.image_to_monochrome(source, threshold_options)
            floyd = media2ovid.image_to_monochrome(source, floyd_options)
            self.assertEqual([0, 0, 255, 255], list(threshold.get_flattened_data()))
            self.assertLessEqual(set(floyd.get_flattened_data()), {0, 255})

    def test_prepared_preview_matches_direct_preview(self):
        source = Image.linear_gradient("L").resize((8, 8))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = self.options(root / "source.png", root / "output.bin")
            prepared = media2ovid.prepare_monochrome_source(source, options)
            self.assertEqual(
                media2ovid.preview_png(source, options),
                media2ovid.preview_prepared_png(prepared, options),
            )

    def test_transparent_gif_is_resampled_to_constant_fps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "animated.gif"
            first = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            second = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
            first.save(
                source,
                save_all=True,
                append_images=[second],
                duration=[250, 750],
                loop=0,
                disposal=2,
            )
            options = self.options(source, root / "gif.bin", fps=4)
            info = media2ovid.probe_source(options)
            self.assertEqual(info.frame_count, 4)
            self.assertEqual(media2ovid.convert_media(options).frame_count, 4)

    def test_cancel_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            for index in range(3):
                Image.new("1", (8, 8), index % 2).save(frames / f"{index}.png")
            output = root / "cancelled.bin"
            cancel = threading.Event()

            def progress(value):
                if value.completed_frames == 1:
                    cancel.set()

            with self.assertRaises(media2ovid.ConversionCancelled):
                media2ovid.convert_media(
                    self.options(frames, output),
                    progress=progress,
                    cancelled=cancel.is_set,
                )
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".part").exists())

    def test_single_worker_closes_source_iterator_after_cancellation(self):
        class ClosingIterator:
            def __init__(self):
                self.closed = False

            def __iter__(self):
                return self

            def __next__(self):
                return Image.new("RGB", (8, 8), "white")

            def close(self):
                self.closed = True

        iterator = ClosingIterator()
        options = self.options(
            Path("source.mp4"),
            Path("output.bin"),
            workers=1,
        )
        info = media2ovid.SourceInfo("video", 1, 0.5, 2.0, (8, 8))
        with mock.patch.object(media2ovid, "iter_source_images", return_value=iterator):
            with self.assertRaises(media2ovid.ConversionCancelled):
                list(media2ovid._processed_frames(options, info, lambda: True))
        self.assertTrue(iterator.closed)

    def test_existing_output_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "exists.bin"
            Image.new("1", (8, 8), 1).save(source)
            output.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                media2ovid.convert_media(self.options(source, output))
            self.assertEqual(output.read_bytes(), b"keep")
            media2ovid.convert_media(self.options(source, output, force=True))
            self.assertEqual(output.read_bytes()[:4], b"OVID")

    def test_video_is_streamed_and_resampled(self):
        try:
            import imageio_ffmpeg
        except ImportError:
            self.skipTest("imageio-ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            writer = imageio_ffmpeg.write_frames(str(source), (16, 16), fps=2)
            writer.send(None)
            try:
                writer.send(bytes([0, 0, 0]) * 16 * 16)
                writer.send(bytes([255, 255, 255]) * 16 * 16)
            finally:
                writer.close()
            options = self.options(source, root / "video.bin", fps=2)
            summary = media2ovid.convert_media(options)
            self.assertEqual(summary.frame_count, 2)
            raw = summary.path.read_bytes()[:16]
            self.assertEqual(struct.unpack("<4sBBBBIHH", raw)[0], b"OVID")

            fast_options = self.options(
                source,
                root / "video-fast.bin",
                fps=2,
                fast_video=True,
            )
            fast_summary = media2ovid.convert_media(fast_options)
            self.assertEqual(fast_summary.frame_count, 2)


if __name__ == "__main__":
    unittest.main()
