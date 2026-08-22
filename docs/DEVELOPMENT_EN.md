# Development Reference

[中文](DEVELOPMENT.md) · **English** · [Back to README](../README_EN.md)

## Project Structure

```text
.
├── STM32F103/               # Current working STM32F103 firmware project
│   ├── .settings/           # Tool-bundle manifest for the STM32 extension
│   ├── .vscode/             # Extension recommendations, clangd, and ST-Link configuration
│   ├── CMakeLists.txt / CMakePresets.json
│   ├── SD_Card_OVID_Player.ioc
│   ├── Core/                # Application, SD, FatFs, OLED, UI, and player code
│   ├── Drivers/             # STM32 HAL and CMSIS
│   └── cmake/               # CubeMX CMake files and Arm GCC toolchain
├── ESP32/                    # Empty directory reserved for a future ESP32 port
├── docs/images/             # Hardware images and UI animations
├── tools/
│   ├── ovid_converter_gui.py # Material 3 desktop converter
│   ├── media2ovid.py        # Direct image/GIF/video conversion core and CLI
│   ├── h2bin.py             # Pack sampled headers and validate OVID
│   └── merge_img2lcd.py     # Merge Img2Lcd frame C arrays
└── SD_Card_OVID_Player.code-workspace
```

`STM32F103/Core/隐藏关卡/` is a real historical directory in the repository, and tool examples also refer to it, so the documentation does not pretend that it has already been renamed. If it is renamed later, script comments, command examples, and related paths must be updated together.

## Build Usage and Validation

The values below were measured with Arm GNU Toolchain 14.3.1, the default 128×64 configuration, and double buffering:

| Build | Flash | RAM |
|---|---:|---:|
| Debug (`-Os -g3`) | 55,816 B / 64 KiB (85.17%) | 10,040 B / 20 KiB (49.02%) |
| Release (`-Os -g0`) | 55,804 B / 64 KiB (85.15%) | 10,040 B / 20 KiB (49.02%) |

> [!NOTE]
> Debug still keeps the complete diagnostic paths and `-g3` symbols, but it also uses `-Os` so the image fits when built by different GNU Arm toolchain versions. A few variables may therefore be optimized during stepping. Release remains the recommended normal-use build. With Flash usage around 85%, check `arm-none-eabi-size` before adding another font or a large block of UI text.

The 128×32, 128×64, 128×128, and 96×64 configurations have been rebuilt, including both SSD1306 and SH1106 controller branches. The largest 128×128 Debug configuration uses 12,088 B of RAM (59.02%). Tool checks cover Python syntax and regeneration of the OVID test files.

A 30-minute continuous playback run, real card hot removal, and signal integrity at 1.4 MHz across different OLED modules remain target-hardware tests. A successful host build cannot replace those checks.

## Roadmap

- [ ] Because the STM32F103C8T6 is currently limited by its available Flash and RAM, port the player to ESP32 and continue developing it on a platform with more resources.
- [x] Separate the SPI Micro SD + FatFs filesystem driver and the SSD1306/SH1106 OLED driver into independent, reusable, and easier-to-port modules.
- [ ] **In progress:** Simplify conversion from images, GIFs, and videos. OVID Converter is now available, while its preview, conversion workflow, and Windows packaging are still being refined.
