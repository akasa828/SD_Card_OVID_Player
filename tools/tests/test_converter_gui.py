from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI_SOURCE = ROOT / "tools" / "ovid_converter_gui.py"
PACKAGE_SOURCE = ROOT / "tools" / "package_converter.ps1"
WORKFLOW_SOURCE = ROOT / ".github" / "workflows" / "release-assets.yml"
FONT_ROOT = ROOT / "tools" / "assets" / "fonts"


class ConverterGuiTests(unittest.TestCase):
    def test_bundled_fonts_and_licenses_exist(self) -> None:
        for name in (
            "GoogleSansFlex-Variable.ttf",
            "NotoSansSC-Variable.ttf",
            "OFL-1.1.txt",
            "FONT_SOURCES.md",
        ):
            path = FONT_ROOT / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100, path)

    def test_gui_uses_simplified_chinese_font_fallback(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        self.assertIn('PRIMARY_FONT = "Google Sans Flex"', source)
        self.assertIn('SIMPLIFIED_CHINESE_FONT = "Noto Sans SC"', source)
        self.assertIn('font_family_fallback=[SIMPLIFIED_CHINESE_FONT]', source)
        self.assertIn('current_locale=ft.Locale("zh", "CN")', source)

    def test_gui_centers_after_initial_layout(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        layout = source.index("ConverterApp(page)")
        centered = source.index("await page.window.center()")
        self.assertLess(layout, centered)

    def test_font_assets_are_added_to_windows_package(self) -> None:
        source = PACKAGE_SOURCE.read_text(encoding="utf-8")
        self.assertIn('--add-data "${assetsPath}:assets"', source)

    def test_release_workflow_keeps_both_windows_packages(self) -> None:
        source = WORKFLOW_SOURCE.read_text(encoding="utf-8")
        self.assertIn("Build portable ZIP and installer", source)
        self.assertIn("OVID_Converter_Windows_x64_Portable_*.zip", source)
        self.assertIn("OVID_Converter_Windows_x64_Setup_*.exe", source)

    def test_interface_does_not_use_common_traditional_variants(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        traditional = "預覽轉換選擇載輸檔關閉儲遞歸縮鋪滿開啟顯處無錯誤資料夾"
        found = sorted({character for character in traditional if character in source})
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
