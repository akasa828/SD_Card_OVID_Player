import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import check_commit_messages  # noqa: E402


class CommitMessageTests(unittest.TestCase):
    def test_accepts_conventional_merge_and_revert_subjects(self):
        valid = [
            "feat: add file browser",
            "fix(ui): clip long filenames",
            "refactor(sd)!: replace the transport API",
            "docs: " + ("describe the complete flashing and conversion workflow " * 3),
            "Merge pull request #12 from user/branch",
            'Revert "feat: add file browser"',
        ]
        for subject in valid:
            self.assertEqual(
                check_commit_messages.validate_subject(subject),
                [],
                subject,
            )

    def test_rejects_vague_non_English_subjects(self):
        invalid = [
            "v1.2.2",
            "update",
            "更新",
            "fix: end with a period.",
        ]
        for subject in invalid:
            self.assertTrue(
                check_commit_messages.validate_subject(subject),
                subject,
            )


if __name__ == "__main__":
    unittest.main()
