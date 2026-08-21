"""h2bin.py 的无 Pillow 快速回归测试。"""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import h2bin


class H2BinTests(unittest.TestCase):
    def test_frame_larger_than_1024_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.bin"
            frame = bytes(h2bin.frame_bytes(200, 64))
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(target, [frame], 200, 64, 30)
                result = h2bin.cmd_info(SimpleNamespace(file=str(target)))
            self.assertEqual(result, 0)
            self.assertEqual(target.stat().st_size, 16 + 1600 + 4)

    def test_zero_fps_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "zero.bin"
            with self.assertRaisesRegex(ValueError, "1~120"):
                h2bin.write_ovid(target, [bytes(8)], 8, 8, 0)

    def test_odd_video_height_reports_page_aligned_screen(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            h2bin.print_firmware_requirements(17, 9)
        self.assertIn("OLED_WIDTH=17", output.getvalue())
        self.assertIn("OLED_HEIGHT=16", output.getvalue())
        self.assertIn("OLED_GRAM_SIZE=34 B", output.getvalue())

    def test_info_rejects_zero_frame_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bad.bin"
            target.write_bytes(h2bin.make_header(8, 8, 0, 15, h2bin.OVID_V1))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(h2bin.cmd_info(SimpleNamespace(file=str(target))), 1)

    def test_v1_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "legacy.bin"
            frame = bytes(range(8))
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(target, [frame], 8, 8, 15, h2bin.OVID_V1)
                self.assertEqual(h2bin.cmd_info(SimpleNamespace(file=str(target))), 0)
            self.assertEqual(target.stat().st_size, 16 + 8)

    def test_v2_detects_corrupt_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "crc.bin"
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(target, [bytes(8)], 8, 8, 15)
            data = bytearray(target.read_bytes())
            data[16] ^= 0x01
            target.write_bytes(data)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(h2bin.cmd_info(SimpleNamespace(file=str(target))), 1)


if __name__ == "__main__":
    unittest.main()
