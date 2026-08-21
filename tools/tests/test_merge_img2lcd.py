import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import merge_img2lcd  # noqa: E402


def write_array(path: Path, name: str, values, declaration="const unsigned char"):
    data = ", ".join(str(value) for value in values)
    path.write_text(
        f"{declaration} {name}[{len(values)}] = {{{data}}};\n",
        encoding="utf-8",
    )


class MergeImg2LcdTests(unittest.TestCase):
    def test_supported_array_declarations(self):
        cases = [
            ("const unsigned char", "frame"),
            ("static const uint8_t", "frame"),
            ("unsigned char", "frame-name.jpg"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for index, (declaration, name) in enumerate(cases):
                source = directory / f"{index}.c"
                write_array(source, name, [0, 1, 254, 255], declaration)
                parsed_name, data = merge_img2lcd.parse_single_array(source)
                self.assertEqual(parsed_name.strip(), name)
                self.assertEqual(data, bytes([0, 1, 254, 255]))

    def test_merge_uses_natural_file_order_and_unique_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "frames"
            input_dir.mkdir()
            write_array(input_dir / "frame10.c", "source10", [10, 10])
            write_array(input_dir / "frame2.c", "source2", [2, 2])
            write_array(input_dir / "frame1.c", "source1", [1, 1])
            output = root / "merged.h"
            count, frame_bytes = merge_img2lcd.merge_directory(input_dir, output)
            text = output.read_text(encoding="utf-8")
        self.assertEqual((count, frame_bytes), (3, 2))
        self.assertLess(text.index("frame1.c"), text.index("frame2.c"))
        self.assertLess(text.index("frame2.c"), text.index("frame10.c"))
        self.assertEqual(text.count("static const unsigned char BMP"), 3)

    def test_1024_byte_frame_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "frames"
            input_dir.mkdir()
            write_array(input_dir / "frame.c", "frame", [0xAA] * 1024)
            count, frame_bytes = merge_img2lcd.merge_directory(
                input_dir, root / "merged.h"
            )
        self.assertEqual((count, frame_bytes), (1, 1024))

    def test_empty_directory_and_mismatched_frames_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(merge_img2lcd.MergeError):
                merge_img2lcd.merge_directory(root, root / "empty.h")
            write_array(root / "frame1.c", "frame1", [1, 2])
            write_array(root / "frame2.c", "frame2", [1, 2, 3])
            with self.assertRaises(merge_img2lcd.MergeError):
                merge_img2lcd.merge_directory(root, root / "bad.h")

    def test_invalid_byte_and_multiple_arrays_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.c"
            write_array(invalid, "frame", [256])
            with self.assertRaises(merge_img2lcd.MergeError):
                merge_img2lcd.parse_single_array(invalid)
            multiple = root / "multiple.c"
            multiple.write_text(
                "unsigned char a[]={1};\nunsigned char b[]={2};\n",
                encoding="utf-8",
            )
            with self.assertRaises(merge_img2lcd.MergeError):
                merge_img2lcd.parse_single_array(multiple)


if __name__ == "__main__":
    unittest.main()
