import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import converter_services as services
from media2ovid import ConversionOptions
import ovid_codec as codec


class OutputSafetyTests(unittest.TestCase):
    def test_no_overwrite_also_applies_when_destination_appears_during_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            def frames():
                output.write_bytes(b"created by another program")
                yield bytes(8)
            with self.assertRaises(FileExistsError):
                codec.write_ovid_atomic(output, frames(), 8, 8, 15)
            self.assertEqual(b"created by another program", output.read_bytes())
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_stale_or_foreign_part_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            foreign = output.with_name(output.name + ".part")
            foreign.write_bytes(b"another conversion")
            codec.write_ovid_atomic(output, [bytes(8)], 8, 8, 15)
            self.assertEqual(b"another conversion", foreign.read_bytes())
            self.assertTrue(codec.validate_ovid(output).valid)
            self.assertEqual({output, foreign}, set(Path(directory).iterdir()))

    def test_simultaneous_writers_publish_one_complete_file_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            ready = threading.Barrier(2)
            def write(value):
                def frames():
                    ready.wait(timeout=5)
                    yield bytes([value] * 8)
                try:
                    codec.write_ovid_atomic(output, frames(), 8, 8, 15)
                except FileExistsError:
                    return False
                return True
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(write, [0x55, 0xAA]))
            self.assertEqual(1, sum(results))
            with codec.OvidReader(output) as reader:
                self.assertTrue(reader.validate().valid)
                self.assertIn(reader.read_frame(0).data, [bytes([0x55] * 8), bytes([0xAA] * 8)])
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_cancel_after_last_frame_does_not_publish_or_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            output.write_bytes(b"old")
            cancel = threading.Event()
            with self.assertRaises(codec.OvidWriteCancelled):
                codec.write_ovid_atomic(
                    output, [bytes(8)], 8, 8, 15, force=True,
                    on_frame=lambda _: cancel.set(), cancelled=cancel.is_set,
                )
            self.assertEqual(b"old", output.read_bytes())
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_overwrite_setting_does_not_make_queue_tasks_share_an_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            output.write_bytes(b"existing")
            queue = services.ConversionQueue()
            options = ConversionOptions(Path("source.mp4"), output, force=True)
            first = queue.add(options)
            second = queue.add(options)
            self.assertEqual(output, first.options.output)
            self.assertNotEqual(first.options.output, second.options.output)
            queue.replace_options(second.id, options)
            queue.freeze_selected()
            self.assertNotEqual(first.options.output, second.options.output)

    def test_crc_validation_stops_on_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            codec.write_ovid(output, [bytes(8)] * 10, 8, 8, 15)
            cancel = threading.Event()
            original_read = codec.OvidReader.read_frame
            read_indices = []
            def read(reader, index):
                read_indices.append(index)
                cancel.set()
                return original_read(reader, index)
            with mock.patch.object(codec.OvidReader, "read_frame", new=read):
                with self.assertRaises(codec.OvidWriteCancelled):
                    codec.validate_ovid(output, cancelled=cancel.is_set)
            self.assertEqual([0], read_indices)

    def test_posix_publication_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.BIN"
            temporary = Path(directory) / "new.part"
            output.write_bytes(b"old")
            temporary.write_bytes(b"new")
            with mock.patch.object(codec.os, "name", "posix"):
                with self.assertRaises(FileExistsError):
                    codec._publish_ovid(temporary, output, force=False)
            self.assertEqual(b"old", output.read_bytes())
            self.assertEqual(b"new", temporary.read_bytes())

    def test_failed_output_reservation_does_not_partially_freeze_batch(self):
        queue = services.ConversionQueue()
        first = queue.add(ConversionOptions(Path("a.mp4"), Path("a.BIN")))
        second = queue.add(ConversionOptions(Path("b.mp4"), Path("b.BIN")))
        with mock.patch.object(services, "unique_output_path", side_effect=[Path("a_2.BIN"), OSError("unavailable")]):
            with self.assertRaises(OSError):
                queue.freeze_selected()
        self.assertFalse(first.frozen)
        self.assertFalse(second.frozen)
        self.assertEqual(Path("a.BIN"), first.options.output)

    def test_frozen_jobs_cannot_be_removed_or_retried(self):
        queue = services.ConversionQueue()
        job = queue.add(ConversionOptions(Path("a.mp4"), Path("a.BIN")))
        queue.freeze_selected()
        with self.assertRaises(ValueError):
            queue.remove(job.id)
        with self.assertRaises(ValueError):
            queue.retry(job.id)
        self.assertEqual((job,), queue.snapshot())


if __name__ == "__main__":
    unittest.main()
