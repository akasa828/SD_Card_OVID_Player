<a id="top"></a>

<p align="center">
  <a href="README.md">中文</a> · <strong>English</strong>
</p>

<div align="center">

# SD Card OVID Player

**Browse and play frame-based videos from an SD card on a monochrome OLED**

<p>
  <img alt="MCU STM32F103C8T6" src="https://img.shields.io/badge/MCU-STM32F103C8T6-03234B?style=flat-square&logo=stmicroelectronics&logoColor=white">
  <img alt="OLED SSD1306 or SH1106" src="https://img.shields.io/badge/OLED-SSD1306%20%7C%20SH1106-222222?style=flat-square">
  <img alt="Format OVID v2" src="https://img.shields.io/badge/Format-OVID%20v2-5B5BD6?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2EA44F?style=flat-square">
</p>

<p>
  <a href="https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.3.0-beta.2"><strong>Download beta.2</strong></a> ·
  <a href="#quick-start"><strong>Quick start</strong></a> ·
  <a href="#showcase"><strong>Watch the demo</strong></a>
</p>

</div>

This project began with a simple goal: play Bad Apple on an STM32. I did not want to keep an almost 10 MB video permanently in external Flash, so I moved the files to an SD card. FatFs, a file browser, a player UI, and the OVID frame format gradually followed. It is now closer to a small standalone player than a one-video demo.

If you are looking for an STM32 SD card video player, SSD1306/SH1106 animation playback, STM32 Bad Apple, or a FatFs SPI SD card example, this repository includes the complete player, the media converter, and reusable driver projects.

The repository also includes a Windows converter that turns images, GIFs, videos, or image folders directly into OLED-ready `.BIN` files. The longer version of how the project grew is in [the project story](docs/PROJECT_STORY_EN.md).

This remains a personal learning and experimental embedded project. It has mainly been tested with an STM32F103C8T6, an SSD1306 OLED, and an SPI Micro SD module. `v1.3.0-beta.2` is the newest test build; use [`v1.2.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.2.2) if you only want the current stable firmware.

<a id="showcase"></a>

## Hardware Demo

<p align="center">
  <img src="docs/images/mmexport1787248540213%20(1).gif" alt="OLED playback and file browser demo" width="48%">
  <img src="docs/images/MP4_20260821_021752VLOG.gif" alt="Waiting for an SD card and startup flow" width="48%"><br>
  <sub>File browser and playback (left) · card detection and startup UI (right)</sub>
</p>

<a id="features"></a>

## What It Does

- Browses OVID `.BIN` files on FAT12, FAT16, or FAT32 cards, preferring `/function` and falling back to the root directory.
- Plays at the 1–120 FPS rate stored in the header. OVID v2 adds header CRC16 and per-frame CRC32; a bad frame leaves the previous image visible.
- Drives SSD1306 or SH1106 displays with double buffering and I2C DMA, including long-filename scrolling, rotating metadata, and optional playback inversion.
- Reports capacity, card type, and CID after insertion, with recovery paths for card removal, FatFs read failures, and OLED DMA timeouts.
- Converts media with previews, trimming, threshold/dithering controls, batch tasks, multithreaded processing, and a built-in OVID player.
- Builds and flashes from VS Code with CMake, ST's official extension, and ST-Link after downloading the complete repository.

<a id="quick-start"></a>

## Quick Start

1. On [GitHub](https://github.com/akasa828/SD_Card_OVID_Player), choose **Code → Download ZIP**, then fully extract the archive into a regular folder.
2. Install [VS Code](https://code.visualstudio.com/) and [STM32CubeIDE for Visual Studio Code](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension).
3. Open `SD_Card_OVID_Player.code-workspace` from the repository root. If you only need the F103 firmware, open `STM32F103/` directly.
4. Accept project discovery, tool Bundle installation, and CMake configuration, then select the `Release` preset.
5. Connect the OLED, SD module, buttons, and ST-Link using the table below. Under **Run and Debug**, select `STM32: Build, flash and debug with ST-Link` and press `F5`. Press `F5` again when execution stops at `main`.
6. Format the SD card as FAT/FAT32, create a `function` folder, and copy an OVID `.BIN` into it. Insert the card, reset the board, choose a file with Up/Down, and press Confirm to play.

The first project setup needs internet access to download the STM32 tool Bundles. STM32CubeProgrammer GUI/CLI and complete SWD instructions are kept in the [flashing guide](docs/FLASHING_EN.md).

<a id="converter"></a>

## OVID Converter

If you do not need the old IrfanView, Img2Lcd, and intermediate `.c/.h` workflow, download the beta.2 converter:

- [Windows x64 installer](https://github.com/akasa828/SD_Card_OVID_Player/releases/download/v1.3.0-beta.2/OVID_Converter_Windows_x64_Setup_v1.3.0-beta.2.exe)
- [Windows x64 portable build](https://github.com/akasa828/SD_Card_OVID_Player/releases/download/v1.3.0-beta.2/OVID_Converter_Windows_x64_Portable_v1.3.0-beta.2.zip)

The installer creates a Start Menu entry and can add a desktop shortcut. The portable build runs after extraction and writes no installation records. Both include the runtime, Pillow, and FFmpeg, so Python is not required.

```text
Select an image, image folder, GIF, or video
→ preview and trim it
→ choose OLED size, FPS, and monochrome processing
→ generate and validate an OVID .BIN
```

The defaults are 128×64, 15 FPS, and a fixed threshold of 128. Floyd–Steinberg dithering remains available. After conversion, the app reopens the output and checks the OVID header, file length, and every frame CRC.

> [!WARNING]
> The Windows packages are unsigned, so SmartScreen may report an unknown publisher. Download them only from this repository's Release page and verify them against `SHA256SUMS.txt` from the same Release.

For inspecting every intermediate step, the [original Img2Lcd workflow](docs/OVID_TUTORIAL_EN.md) is still available.

The Release also includes `SD_Card_OVID_Player_Sample_Videos.zip` with OVID files that can be copied directly to the card for testing. The firmware `.elf`, `.bin`, and all Windows packages share one `SHA256SUMS.txt`.

<a id="hardware"></a>

## Hardware and Wiring

You need an STM32F103C8T6 minimum system board, an SSD1306/SH1106 I2C monochrome OLED, an SPI Micro SD module, three buttons, and ST-Link. A USB-to-TTL adapter is optional and only used for serial diagnostics.

| Function | STM32 Pin | Peripheral Pin | Notes |
|:---:|:---:|:---:|:---:|
| SPI1 SCK | PA5 | SD SCK/CLK | SPI mode 0 |
| SPI1 MISO | PA6 | SD MISO/DO | SD → MCU |
| SPI1 MOSI | PA7 | SD MOSI/DI | MCU → SD |
| SD CS | PB0 | SD CS | Active low |
| I2C1 SCL | PB6 | OLED SCL | Open-drain; pull-up required |
| I2C1 SDA | PB7 | OLED SDA | Open-drain; pull-up required |
| Up / Down / Confirm | PB1 / PB10 / PB11 | Other side to GND | Internal pull-up, falling-edge EXTI |
| USART1 TX | PA9 | USB-TTL RX | Optional, 115200 8N1, transmit only |
| Power and ground | 3.3 V / GND | SD, OLED, buttons | Check module voltage requirements first |

ST-Link uses `PA13/SWDIO`, `PA14/SWCLK`, and `GND`; connecting `NRST` is also recommended. Unless you understand the probe's power arrangement, do not let an external supply and ST-Link drive the same 3.3 V rail at once.

<a id="sd-card"></a>

## SD Card and Controls

Recommended layout:

```text
SD card root/
├── function/
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN
```

The firmware does not create `/function`. On first insertion it scans the FAT to calculate free space, so a large or fragmented card may take a few seconds. Press Confirm to skip the scan; the player shows `Free: N/A` and still enters the file list.

| Button | File List | During Playback |
|---|---|---|
| PB1 Up | Previous file; hold to accelerate | No action |
| PB10 Down | Next file; hold to accelerate | No action |
| PB11 Confirm | Play selected file | Stop and return to the list |

```text
Wait for card → mount FatFs → calculate capacity → scan files
              → three card information pages → file list → playback
```

<a id="docs"></a>

## Reusable Drivers and Documentation

The two drivers used by the player are also maintained as standalone projects:

- [STM32-HAL-SSD1306-SH1106](https://github.com/akasa828/STM32-HAL-SSD1306-SH1106): drawing, double buffering, I2C DMA, and controller configuration.
- [STM32-HAL-SPI-SD-FatFs](https://github.com/akasa828/STM32-HAL-SPI-SD-FatFs): SPI SD protocol core, STM32 HAL port, and FatFs `diskio` integration.

| Document | Contents |
|---|---|
| [Project story](docs/PROJECT_STORY_EN.md) | The complete path from Bad Apple to an SD card player |
| [Flashing guide](docs/FLASHING_EN.md) | ST-Link, VS Code, and STM32CubeProgrammer GUI/CLI |
| [OVID conversion tutorial](docs/OVID_TUTORIAL_EN.md) | Converter and optional manual Img2Lcd workflow |
| [OVID file format](docs/OVID_FORMAT_EN.md) | 16-byte header, page-major frames, and CRC |
| [Diagnostics and troubleshooting](docs/TROUBLESHOOTING_EN.md) | SD, OLED, serial output, watchdog, and HardFault |
| [Porting guide](docs/PORTING_EN.md) | Display macros, SSD1306/SH1106, and I2C |
| [Development reference](docs/DEVELOPMENT_EN.md) | Repository layout, resource usage, build matrix, and roadmap |

<a id="version"></a>

## Versions, Contributing, and License

- **Newest test build:** [`v1.3.0-beta.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.3.0-beta.2)
- **Stable firmware:** [`v1.2.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.2.2)
- **Full history:** [CHANGELOG.md](CHANGELOG.md)

beta.2 mainly reorganizes the converter's dual previews, timeline, and batch tasks. It does not change the OVID v2 file format, so existing v2 files that already work on the player do not need to be converted again.

Bug reports and ideas are welcome in [GitHub Issues](https://github.com/akasa828/SD_Card_OVID_Player/issues). Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the code, and use [SECURITY.md](SECURITY.md) for reports that should not be public.

Code written for this project uses the [MIT License](LICENSE). STM32 HAL, CMSIS, FatFs, and converter dependencies remain under their respective licenses.

<p align="right"><a href="#top">Back to top ↑</a></p>
