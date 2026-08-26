import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


TOOLS = Path(__file__).resolve().parents[1]
HELPERS = TOOLS / "converter_packaging.ps1"
SCENARIO = Path(__file__).parent / "fixtures" / "packaging_scenario.ps1"
POWERSHELL = shutil.which("powershell.exe")
ARCHIVE = "OVID_Converter_Windows_x64_Portable_v1.3.2-beta.1.zip"
SETUP = "OVID_Converter_Windows_x64_Setup_v1.3.2-beta.1.exe"
APP = "portable/OVID Converter/OVID Converter.exe"
ARTIFACT_FILES = [APP, "licenses/MIT.txt", "THIRD_PARTY_NOTICES.txt", ARCHIVE]


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell filesystem tests")
class ConverterPackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ovid-package-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "中文 path [1]"
        for folder, marker in (("output", "old"), ("payload", "new")):
            for name in ARTIFACT_FILES:
                self.write(self.root / folder / name, marker)
        self.write(self.root / "output" / "manual.txt", "keep")
        self.write(self.root / "output" / "older-release.zip", "keep")
        self.write(self.root / "output" / "portable" / "other-app.txt", "keep")
        self.write(self.root / "external" / "do-not-touch.txt", "keep")

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_scenario(self, scenario, success=False):
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCENARIO),
             "-Root", str(self.root), "-Helpers", str(HELPERS), "-Scenario", scenario,
             "-PythonExecutable", sys.executable],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(0 if success else 1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("keep", (self.root / "output/manual.txt").read_text())
        self.assertEqual("keep", (self.root / "output/older-release.zip").read_text())
        self.assertEqual("keep", (self.root / "output/portable/other-app.txt").read_text())
        self.assertEqual("keep", (self.root / "external/do-not-touch.txt").read_text())
        return result.stdout + result.stderr

    def assert_artifacts(self, marker):
        for name in ARTIFACT_FILES:
            self.assertEqual(marker, (self.root / "output" / name).read_text(), name)

    def test_publish_replaces_only_managed_artifacts_and_removes_stage(self):
        self.run_scenario("success", success=True)
        self.assert_artifacts("new")
        self.assertEqual([], list((self.root / "output").glob(".ovid-stage-*")))

    def test_build_outside_a_synced_output_folder_publishes_and_cleans_only_its_stage(self):
        self.write(self.root / "staging/unrelated.txt", "keep")
        self.run_scenario("separate-stage", success=True)
        self.assert_artifacts("new")
        self.assertEqual("keep", (self.root / "staging/unrelated.txt").read_text())
        self.assertEqual([], list((self.root / "staging").glob(".ovid-stage-*")))

    def test_archive_contains_the_app_root_and_hidden_files_and_can_be_published(self):
        (self.root / "payload" / ARCHIVE).unlink()
        hidden = self.root / "payload/portable/OVID Converter/.config"
        self.write(hidden, "included")
        import ctypes
        self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 2))
        self.run_scenario("archive", success=True)
        with zipfile.ZipFile(self.root / "output" / ARCHIVE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(b"new", archive.read("OVID Converter/OVID Converter.exe"))
            self.assertEqual(b"included", archive.read("OVID Converter/.config"))

    def test_locked_archive_keeps_old_and_new_packages(self):
        message = self.run_scenario("locked-zip")
        self.assertIn("Close OVID Converter", message)
        self.assert_artifacts("old")
        stage = next((self.root / "output").glob(".ovid-stage-*"))
        self.assertEqual("new", (stage / ARCHIVE).read_text())

    def test_short_lived_new_file_lock_is_retried_without_rebuilding(self):
        self.run_scenario("transient-source-lock", success=True)
        self.assert_artifacts("new")

    def test_permanent_source_lock_times_out_with_diagnostics_without_deleting_files(self):
        message = self.run_scenario("persistent-source-lock")
        self.assertIn("Files currently in use:", message)
        self.assert_artifacts("old")
        stage = next((self.root / "output").glob(".ovid-stage-*"))
        self.assertEqual("new", (stage / APP).read_text())

    def test_successful_rollback_with_empty_backup_directories_can_be_retried(self):
        self.run_scenario("empty-backup-retry", success=True)
        self.assert_artifacts("new")

    def test_backup_files_from_incomplete_recovery_prevent_publication(self):
        self.assertIn("needs recovery", self.run_scenario("unfinished-recovery"))
        self.assert_artifacts("old")

    def test_running_executable_prevents_replacement_without_deleting_old_files(self):
        self.assertIn("Close OVID Converter", self.run_scenario("locked-exe"))
        self.assert_artifacts("old")

    def test_missing_archive_is_rejected_before_any_previous_output_moves(self):
        (self.root / "payload" / ARCHIVE).unlink()
        self.assertIn("artifact is missing", self.run_scenario("missing"))
        self.assert_artifacts("old")

    def test_late_publish_failure_rolls_back_already_replaced_artifacts(self):
        self.assertIn("Previous packages were restored", self.run_scenario("late-failure"))
        self.assert_artifacts("old")
        stage = next((self.root / "output").glob(".ovid-stage-*"))
        for name in ARTIFACT_FILES:
            self.assertEqual("new", (stage / name).read_text())

    def test_failed_rollback_keeps_recoverable_old_executable(self):
        self.assertIn("Recovery is incomplete", self.run_scenario("rollback-failure"))
        stage = next((self.root / "output").glob(".ovid-stage-*"))
        self.assertEqual("old", (stage / ".previous" / APP).read_text())
        self.assertEqual("new", (self.root / "output" / APP).read_text())

    def test_other_build_cannot_use_the_same_checkout_concurrently(self):
        self.assertIn("build lock", self.run_scenario("concurrent"))
        self.assert_artifacts("old")
        self.assertFalse((self.root / "other-output").exists())

    def test_path_escape_is_rejected(self):
        self.assertIn("relative paths", self.run_scenario("escape"))
        self.assert_artifacts("old")

    def test_overlapping_artifact_directories_are_rejected(self):
        self.assertIn("must not overlap", self.run_scenario("overlap"))
        self.assert_artifacts("old")

    def test_destination_junction_cannot_redirect_packaging_outside_output(self):
        self.assertIn("junctions", self.run_scenario("destination-junction"))
        self.assert_artifacts("old")

    def test_source_junction_is_rejected_before_old_files_are_moved(self):
        self.assertIn("junctions", self.run_scenario("source-junction"))
        self.assert_artifacts("old")

    def test_temporary_cleanup_failure_does_not_report_a_failed_build(self):
        self.assertIn("temporary build files remain", self.run_scenario("cleanup-failure", success=True))
        self.assert_artifacts("new")

    def test_installer_is_required_and_published_when_requested(self):
        self.write(self.root / "payload" / SETUP, "new setup")
        self.write(self.root / "output" / SETUP, "old setup")
        self.run_scenario("installer", success=True)
        self.assertEqual("new setup", (self.root / "output" / SETUP).read_text())

    def test_missing_installer_prevents_partial_publication(self):
        self.assertIn("artifact is missing", self.run_scenario("installer"))
        self.assert_artifacts("old")

    def test_portable_only_build_preserves_an_existing_installer(self):
        self.write(self.root / "output" / SETUP, "keep setup")
        self.run_scenario("success", success=True)
        self.assertEqual("keep setup", (self.root / "output" / SETUP).read_text())

    def test_both_build_entrypoints_preserve_outputs_when_asset_generation_fails(self):
        fake_tools = self.root / "checkout/tools"
        fake_tools.mkdir(parents=True)
        temporary = self.root / "temporary"
        temporary.mkdir()
        shutil.copyfile(HELPERS, fake_tools / HELPERS.name)
        for name in ("package_converter.ps1", "package_converter_flutter.ps1"):
            with self.subTest(name=name):
                script = fake_tools / name
                shutil.copyfile(TOOLS / name, script)
                result = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                     "-PythonExecutable", sys.executable, "-SkipInstaller",
                     "-OutputRoot", str(self.root / "output")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                    env={**os.environ, "TEMP": str(temporary), "TMP": str(temporary)},
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("Failed to generate converter", result.stderr)
                self.assert_artifacts("old")


if __name__ == "__main__":
    unittest.main()
