import contextlib
import io
import struct
import sys
import tempfile
import unittest
import zlib
from argparse import Namespace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import h2bin  # noqa: E402
import ovid_codec  # noqa: E402


class H2BinTests(unittest.TestCase):
    def test_crc_vectors(self):
        data = b"123456789"
        self.assertEqual(h2bin.crc16_ccitt(data), 0x29B1)
        self.assertEqual(zlib.crc32(data) & 0xFFFFFFFF, 0xCBF43926)

    def test_frame_size_supports_odd_height_and_large_frames(self):
        self.assertEqual(h2bin.frame_bytes(5, 9), 10)
        self.assertEqual(h2bin.frame_bytes(255, 64), 2040)

    def test_vertical_scan_is_converted_to_page_major(self):
        source = bytes([0x10, 0x11, 0x20, 0x21, 0x30, 0x31])
        expected = bytes([0x10, 0x20, 0x30, 0x11, 0x21, 0x31])
        self.assertEqual(
            h2bin.vertical_scan_to_pagemajor(source, width=3, height=16),
            expected,
        )

    def test_v1_and_v2_headers_keep_the_16_byte_layout(self):
        v1 = h2bin.make_header(128, 64, 3, 15, h2bin.OVID_V1)
        v2 = h2bin.make_header(128, 64, 3, 15, h2bin.OVID_V2)
        self.assertEqual(len(v1), h2bin.HEADER_SIZE)
        self.assertEqual(len(v2), h2bin.HEADER_SIZE)
        self.assertEqual(struct.unpack("<4sBBBBIHH", v1)[0], b"OVID")
        self.assertEqual(struct.unpack("<4sBBBBIHH", v1)[6:], (15, 0))
        self.assertEqual(
            struct.unpack("<H", v2[14:16])[0],
            h2bin.crc16_ccitt(v2[:14]),
        )

    def test_write_and_validate_v2_with_frame_over_1024_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "large.bin"
            frame = bytes((index & 0xFF) for index in range(2040))
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(output, [frame], 255, 64, 30)
                result = h2bin.cmd_info(Namespace(file=str(output)))
            self.assertEqual(result, 0)

    def test_info_rejects_truncated_header_and_bad_frame_crc(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            short = directory / "short.bin"
            short.write_bytes(b"OVID")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(h2bin.cmd_info(Namespace(file=str(short))), 1)

            corrupt = directory / "corrupt.bin"
            frame = bytes([0x5A] * 16)
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(corrupt, [frame], 8, 16, 12)
            payload = bytearray(corrupt.read_bytes())
            payload[h2bin.HEADER_SIZE] ^= 0x01
            corrupt.write_bytes(payload)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(h2bin.cmd_info(Namespace(file=str(corrupt))), 1)

    def test_shared_reader_supports_random_access_and_crc_status(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reader.bin"
            frames = [bytes([value] * 8) for value in (0x00, 0x55, 0xFF)]
            with contextlib.redirect_stdout(io.StringIO()):
                h2bin.write_ovid(output, frames, 8, 8, 15)
            with ovid_codec.OvidReader(output) as reader:
                self.assertEqual(3, reader.header.frame_count)
                self.assertEqual(frames[1], reader.read_frame(1).data)
                self.assertTrue(reader.validate().valid)

            damaged = bytearray(output.read_bytes())
            damaged[ovid_codec.HEADER_SIZE + (8 + 4)] ^= 0x01
            output.write_bytes(damaged)
            with ovid_codec.OvidReader(output) as reader:
                self.assertEqual((1,), reader.validate().bad_frames)

    def test_header_arrays_are_read_without_loading_the_whole_file(self):
        source_text = """
static const unsigned char BMP10[] = {0x0A, 10};
const unsigned char BMP2[2] = {0x02, 2};
"""
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "frames.h"
            header.write_text(source_text, encoding="utf-8")
            arrays = list(h2bin.iter_header_arrays(header))
        self.assertEqual(arrays, [
            ("BMP10", bytes([10, 10])),
            ("BMP2", bytes([2, 2])),
        ])
        self.assertLess(h2bin.natural_key("BMP2"), h2bin.natural_key("BMP10"))


if __name__ == "__main__":
    unittest.main()
