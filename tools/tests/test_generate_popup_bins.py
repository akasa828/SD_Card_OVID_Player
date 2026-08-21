import contextlib
import io
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import generate_popup_bins  # noqa: E402
import h2bin  # noqa: E402


class PopupFixtureTests(unittest.TestCase):
    def test_generator_creates_all_expected_error_cases(self):
        expected = {
            "POP_GOOD.BIN",
            "POP_BAD.BIN",
            "POP_INV.BIN",
            "POP_BIG.BIN",
            "POP_CRC.BIN",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                generate_popup_bins.generate(root)
            self.assertEqual({path.name for path in root.glob("*.BIN")}, expected)

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    h2bin.cmd_info(Namespace(file=str(root / "POP_GOOD.BIN"))),
                    0,
                )
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    h2bin.cmd_info(Namespace(file=str(root / "POP_CRC.BIN"))),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
