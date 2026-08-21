<a id="top"></a>

<p align="center">
  <a href="README.md">中文</a> · <strong>English</strong>
</p>

<div align="center">

# SD Card OVID Player

**An offline frame-video player for STM32F103, Micro SD, and monochrome OLED displays**

<p>
  <img alt="MCU STM32F103C8T6" src="https://img.shields.io/badge/MCU-STM32F103C8T6-03234B?style=flat-square&logo=stmicroelectronics&logoColor=white">
  <img alt="OLED SSD1306 or SH1106" src="https://img.shields.io/badge/OLED-SSD1306%20%7C%20SH1106-222222?style=flat-square">
  <img alt="Format OVID v2" src="https://img.shields.io/badge/Format-OVID%20v2-5B5BD6?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2EA44F?style=flat-square">
</p>

<p>
  <a href="#quick-start"><strong>Quick Start</strong></a> ·
  <a href="#hardware"><strong>Wiring</strong></a> ·
  <a href="#create-ovid"><strong>Create OVID</strong></a> ·
  <a href="#troubleshooting"><strong>Troubleshooting</strong></a> ·
  <a href="CHANGELOG.md"><strong>Changelog</strong></a>
</p>

<p>
  <a href="https://github.com/akasa828/SD_Card_OVID_Player">GitHub Repository</a> ·
  <a href="https://github.com/akasa828/SD_Card_OVID_Player/archive/refs/heads/main.zip">Download Source ZIP</a> ·
  <a href="https://github.com/akasa828/SD_Card_OVID_Player/releases/latest">Latest Release</a>
</p>

</div>

> [!TIP]
> A ready-to-use set of sample `.BIN` files for testing normal playback and error handling is available exclusively from [GitHub Releases](https://github.com/akasa828/SD_Card_OVID_Player/releases/latest).

SD Card OVID Player is an offline frame-video player for the STM32F103C8T6, built on the STM32 HAL. Video files are stored on an Micro SD card and accessed through FatFs. After browsing and validating a file, the firmware sends its frames to an SSD1306 or SH1106 monochrome OLED at the frame rate stored in the file header. Playback only needs three buttons and does not depend on a computer or network connection. OVID can be read as “OLED Video”: a frame-data format designed for monochrome displays.

The project uses CMake and includes configurations for VS Code, ST's official STM32 extension, and ST-Link. After downloading the complete source tree, you can build, flash, and debug the firmware directly from VS Code.

This is a personal learning and experimental embedded project. It has currently only been tested with the combination of an STM32F103C8T6, an SSD1306 OLED, and an SPI Micro SD module.

The repository is organized by target platform: `STM32F103/` contains the complete working firmware, while `ESP32/` is currently an empty directory reserved for a future port.

<a id="navigation"></a>

<p align="center"><strong>🧭 Documentation</strong></p>

<table align="center">
  <thead>
    <tr>
      <th>🚀 User Guide</th>
      <th>🧰 Developer Reference</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><a href="#showcase">UI Showcase</a> · <a href="#roadmap">Roadmap</a></td>
      <td><a href="#features">Features</a> · <a href="#motivation">Why I Built This</a></td>
    </tr>
    <tr>
      <td><a href="#quick-start">Quick Start</a> · <a href="#hardware">Wiring</a> · <a href="#flash">Flash Firmware</a></td>
      <td><a href="docs/OVID_FORMAT_EN.md">OVID Format</a> · <a href="docs/PORTING_EN.md">Display Porting</a></td>
    </tr>
    <tr>
      <td><a href="#sd-card">Prepare the SD Card</a> · <a href="docs/OVID_TUTORIAL_EN.md">Create OVID</a></td>
      <td><a href="#developer-reference">Project Structure</a> · <a href="#developer-reference">Resource Usage</a></td>
    </tr>
    <tr>
      <td><a href="#controls">Controls and Playback</a> · <a href="docs/TROUBLESHOOTING_EN.md">Troubleshooting</a></td>
      <td><a href="#contributing">Contributing</a> · <a href="#license">License</a></td>
    </tr>
  </tbody>
</table>

<a id="showcase"></a>

## 🖼️ UI Showcase

<p align="center">
  <img src="docs/images/mmexport1787248540213%20(1).gif" alt="SD Card OVID Player running on real hardware" width="640"><br>
  <sub>Playback and OLED output on real hardware</sub>
</p>
<p align="center">
  <img src="docs/images/MP4_20260821_021752VLOG.gif" alt="SD Card OVID Player waiting for a card and starting up" width="640"><br>
  <sub>Waiting-for-card and startup UI</sub>
</p>

<a id="roadmap"></a>

## 🗺️ Roadmap

- [ ] Because the STM32F103C8T6 is currently limited by its available Flash and RAM, port the player to ESP32 and continue developing it on a platform with more resources.
- [x] Separate the SPI Micro SD + FatFs filesystem driver and the SSD1306/SH1106 OLED driver into independent, reusable, and easier-to-port modules.
- [ ] Simplify the workflow for converting images, GIFs, or video sources into OVID `.BIN` files, reducing the need for multiple external graphics tools and intermediate files.

<a id="features"></a>

## ✨ Features

- **💾 Complete SD startup flow:** waits for card insertion, mounts the volume, calculates its capacity, scans for video files, and then presents storage, card, and identity information. Files in `/function` take priority; if none match there, the player falls back to the root directory.
- **🛡️ OVID v2 integrity checks:** uses a header CRC16 and per-frame CRC32. A damaged frame is never sent to the OLED; the previous frame remains visible while reading continues.
- **⏱️ Stable playback timing:** supports 1–120 FPS and accumulates the remainder from millisecond division, preventing long playback sessions from gradually slowing down because of integer truncation.
- **🖥️ Smooth OLED UI:** uses double buffering and I2C DMA. In the normal 128×64, 1.4 MHz I2C environment, animations update on a 16 ms cycle.
- **📂 More usable file browser:** supports accelerated long presses, remembered selection, bidirectional scrolling for long filenames, and rotating metadata for resolution, frame rate, frame count, and format version.
- **🔄 Automatic card-removal recovery:** information pages and the file list probe the card every 500 ms. After two consecutive failures, FatFs is unmounted and the UI returns to the waiting screen. Playback read errors use the same recovery path.
- **💾 Efficient SD card driver:** implements SPI-mode access according to the SD card specification and connects it to FatFs through the `diskio` interface.

> [!NOTE]
> During SD timeouts or I2C/DMA fault recovery, animation smoothness temporarily gives way to reliability.

### 🧩 Parts You Can Reuse Independently

If you do not need the complete player, these modules can still be useful on their own:

| Component | Location |
|---|---|
| SSD1306/SH1106 drawing, double-buffering, and I2C DMA driver | [Standalone driver](https://github.com/akasa828/STM32-HAL-SSD1306-SH1106) · `STM32F103/Core/OLED/` |
| SPI Micro SD driver and FatFs `diskio` integration | [Standalone driver](https://github.com/akasa828/STM32-HAL-SPI-SD-FatFs) · `STM32F103/Core/Micro_SD/`, `STM32F103/Core/fatfs/` |
| Img2Lcd frame merging and OVID packing/validation tools | `tools/` |
| VS Code, CMake, and ST-Link build/debug configuration | `SD_Card_OVID_Player.code-workspace`, `STM32F103/.vscode/`, `STM32F103/CMakePresets.json` |

These modules can serve as porting references, but other STM32 models or pin assignments will still require changes to HAL peripheral handles, GPIO configuration, and clocks.

---

<a id="quick-start"></a>

## 🚀 Quick Start

This project is developed in VS Code with the [STM32CubeIDE for Visual Studio Code extension pack](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension).

1. **Download the source ZIP.** Open the [GitHub repository](https://github.com/akasa828/SD_Card_OVID_Player), select **Code → Download ZIP**, and download the complete project.
2. **Extract the project.** Fully extract the ZIP into a regular folder. Do not open or build the project from inside the compressed-file preview.
3. **Open the workspace in VS Code.** Open `SD_Card_OVID_Player.code-workspace` from the extracted repository root. The Explorer will show both `STM32F103` and `ESP32`. If you only need the current firmware, you can instead use **File → Open Folder** and open the `STM32F103/` directory that contains `CMakeLists.txt`.
4. **Install the extension.** Install the [STM32 extension pack](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension). On first launch, accept the project-discovery, tool-bundle download, and CMake configuration prompts. Wait until VS Code no longer reports a pending `Bundle` download in the lower-right corner.
5. **Select a build type.** Choose `Debug` or `Release` in the STM32/CMake project panel. Use Debug for debugging and Release for normal flashing.
6. **Connect and flash.** Follow the [wiring table](#wiring) to connect the OLED, Micro SD module, three buttons, and ST-Link. Press `F5`, then select `STM32: Build, flash and debug with ST-Link`. The extension builds the current preset and downloads its ELF automatically. When execution stops at `main`, press `F5` again to continue.
7. **Prepare an OVID file.** Format the SD card as FAT or FAT32 and create a `function` folder in its root. Follow the [OVID creation guide](#create-ovid) to prepare the source material, generate frame data with Img2Lcd, and create a `.BIN` file with the merge script and `h2bin.py`.
8. **Insert the card and play.** Copy `DEMO.BIN` into `/function`, insert the card, and reset the board. After the three card-information pages finish, use Up and Down to select a file and press Confirm to play it. Press Confirm again during playback to return to the file list.

> [!NOTE]
> The initial setup needs an internet connection to download the declared STM32 tool bundles. `v1.2.2` remains stable, while the modular-driver build `v1.2.6` is provided first as a prerelease. Sample `.BIN` files for playback and error handling are available from Releases.

<a id="motivation"></a>

## 💡 Why I Built This

This project was not supposed to become this complicated at first.

It started when I saw people using STM32 boards and all kinds of displays to play Bad Apple. I thought it looked fun, and a very simple idea came to mind: I wanted to build one too.

But if I was going to do it, I did not really want to put the video data directly into W25Q Flash. Capacity was one reason—one converted `bad_apple.bin` file was already close to 10 MB. More importantly, if I ever wanted to turn the experiment into a small player where files could be replaced freely, or several files could be stored at once, fixing one video inside Flash would not be a very good fit.

That led me to the SD card. It offered much more capacity, made files easy to replace, and felt a lot closer to my idea of a player than something that could only show the one video compiled into it.

Then came the next question:

How does an STM32 read a file from an SD card?

That was where things gradually started getting out of hand—in a good way.

To read a `.bin` file from the card, I started learning about SD card communication and the FatFs filesystem. Once I had solved where the file came from, I still needed to work out how to send the data I had read to the OLED.

My experience level was not very high at the time. Even moving from some of the code I had used before to the HAL library was already difficult for me. There were plenty of OLED drivers online, but finding one that really matched what I needed, used HAL, and provided a reasonably complete set of features was harder than expected. Some only displayed text, some had very limited drawing functions, and others still needed a lot of work after being ported.

I am also the kind of person who can copy some code, but if I cannot understand what I copied, I will probably not know how to change it later.

The project ended up sitting untouched for more than a month.

Eventually I realized that leaving it there was not going to help. Instead of waiting until I “knew everything” before coming back, it made more sense to get something working first and solve each problem when I reached it.

So I picked the project up again.

At the beginning, it was still a mixture of code from different places, with the simple goal of making the OLED light up, reading the SD card, and getting Bad Apple to play. As I became more familiar with each part, though, the project gradually developed its own structure and logic.

The OLED code stopped being limited to a few characters and slowly gained pixels, lines, shapes, images, and text. The part that had originally been assembled from drivers found elsewhere also became a HAL-based OLED driver that I could actually understand and modify myself.

Once Bad Apple was finally playing, another thought appeared:

If the SD card can hold files, why should the firmware only play one hard-coded file?

That led to file access, file selection, and a UI. Step by step, what began as a small experiment to “play Bad Apple on an STM32” turned into this project: a small player that reads files from an SD card, drives an OLED, and has its own interface and controls.

Looking back, the project ended up solving more than just “how to play Bad Apple on an STM32.”

On one side, I wanted to organize a HAL-based OLED driver that was reasonably complete and genuinely convenient to use, so that someone with a similar idea would not have to search through scattered code everywhere.

On the other, it became a fairly complete learning process for me:

finding code, combining it, trying to understand it, learning to modify it, designing features of my own, and finally turning an idea into something that actually runs.

As for that original idea of “playing Bad Apple on an STM32”...

I just did not expect it to take quite this much work to play one video.

<a id="hardware"></a>

## 🔌 Hardware and Wiring

The current project uses the following hardware and materials:

- Breadboard
- Jumper wires
- 3 × male-to-male wires
- 10 × female-to-female wires
- STM32F103C8T6 minimum system board; the linker script is configured for 64 KiB Flash and 20 KiB RAM
- SSD1306 or SH1106 I2C monochrome OLED
- SPI Micro SD module using 3.3 V logic levels
- Three buttons
- Optional 3.3 V USB-to-TTL module for serial diagnostics

<a id="wiring"></a>

### 📌 Wiring Table

| Function | STM32 Pin | Peripheral Pin | Notes |
|:---:|:---:|:---:|:---:|
| SPI1 SCK | PA5 | SD SCK/CLK | SPI mode 0 |
| SPI1 MISO | PA6 | SD MISO/DO | SD → MCU |
| SPI1 MOSI | PA7 | SD MOSI/DI | MCU → SD |
| SD CS | PB0 | SD CS | Active low |
| I2C1 SCL | PB6 | OLED SCL | Open-drain; pull-up required |
| I2C1 SDA | PB7 | OLED SDA | Open-drain; pull-up required |
| Up button | PB1 | Other side of button to GND | Internal pull-up, falling-edge EXTI |
| Down button | PB10 | Other side of button to GND | Internal pull-up, falling-edge EXTI |
| Confirm button | PB11 | Other side of button to GND | Internal pull-up, falling-edge EXTI |
| USART1 TX | PA9 | USB-TTL RX | Optional, 115200 8N1, transmit only |
| Common ground | GND | SD/OLED/buttons/serial GND | All grounds must be connected |
| Power | 3.3 V | SD/OLED VCC | Check the module's voltage requirements first |

<a id="flash"></a>

## ⚡ Flashing the STM32

### 1. Connect ST-Link

Flashing uses the STM32F103 SWD interface:

| ST-Link | STM32F103C8T6 | Notes |
|---|---|---|
| SWDIO | PA13 | SWD data |
| SWCLK | PA14 | SWD clock |
| GND | GND | Common ground is required |
| NRST | NRST | Optional, but useful when the target is difficult to connect to |
| VTref/3.3 V | 3.3 V | Target-voltage reference; whether it can power the board depends on the probe model |

| ST-Link | SD Card Reader | Notes |
|---|---|---|
| 5V | 5V | Power |
| GND | GND | Common ground is required |

> [!WARNING]
> The target board can use a separate, stable 3.3 V supply. Unless you understand how your ST-Link supplies power, do not let both an external supply and the ST-Link drive the same 3.3 V rail. For normal boot from Flash, the board's `BOOT0` pin should remain low.

### 2. Press F5 in VS Code

After connecting ST-Link, select `STM32: Build, flash and debug with ST-Link` under **Run and Debug**, then press `F5`. `STM32F103/.vscode/launch.json` asks the official extension to perform this sequence:

```text
Build the active CMake preset → locate its ELF → download through ST-Link → stop at main
```

Press `F5` once more after the first stop at `main` to continue execution. The configuration does not hard-code `build/Debug`, a drive letter, or a username. When the Release preset is selected, the extension uses the corresponding Release ELF.

<details>
<summary><strong>Alternative: Flash Manually with STM32CubeProgrammer</strong></summary>

If the extension is unavailable, you can use the STM32CubeProgrammer graphical interface:

1. Connect ST-Link and the target board, then open STM32CubeProgrammer.
2. Choose `ST-LINK` as the connection method on the right, select `SWD`, and click **Connect**.
3. Click **Open file** and select:

   ```text
   STM32F103/build/Release/SD_Card_OVID_Player.elf
   ```

4. Click **Download**. After the download and verification complete, press Reset or power-cycle the target board.

Release is recommended for normal use. Debug also runs, but uses more Flash and is intended mainly for breakpoints and fault investigation.

If you prefer the command line, add the STM32CubeProgrammer `bin` directory to `PATH`, enter the `STM32F103/` directory, and run:

```powershell
STM32_Programmer_CLI.exe -c port=SWD `
  -w "build/Release/SD_Card_OVID_Player.elf" -v -rst
```

The same command on one line is:

```powershell
STM32_Programmer_CLI.exe -c port=SWD -w "build/Release/SD_Card_OVID_Player.elf" -v -rst
```

Here, `-w` writes the firmware, `-v` verifies it by reading it back, and `-rst` resets the target afterward. Because this command flashes an ELF, no write address is supplied. If you export a raw `.bin` in the future, pass `0x08000000` as its write address.

</details>

<a id="sd-card"></a>

## 💾 Preparing the SD Card

The firmware supports FAT12, FAT16, and FAT32, but not exFAT or NTFS. FatFs is configured for long filenames of up to 63 characters. The OLED font only contains ASCII characters, so ASCII or English filenames are still recommended.

Recommended directory structure:

```text
SD card root/
├── function/          # Preferred when this folder contains .BIN files
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN        # Scanned only when /function has no .BIN files
```

The firmware does not create `/function` automatically. On the first insertion, `f_getfree()` scans the FAT to calculate free space instead of trusting a potentially stale FAT32 FSInfo value. A large or heavily fragmented card may therefore take a few seconds. The progress bar uses per-mille fixed-point interpolation to follow the real scan smoothly, while the activity dot continues moving instead of advancing only in whole-percent steps.

> [!TIP]
> If you do not want to wait, press Confirm on the scan page to skip it. The player displays `Free: N/A` but still scans for files and enters the list. `100%` is shown only after `f_getfree()` actually returns.

<a id="create-ovid"></a>

## 🎬 Creating OVID Files

The complete process for preparing images, generating Img2Lcd data, merging frames, and building an OVID file is documented separately: [read the OVID creation tutorial](docs/OVID_TUTORIAL_EN.md).

<a id="controls"></a>

## 🎮 Controls and Playback Flow

| Button | File List | During Playback |
|---|---|---|
| PB1 Up | Previous file; hold to scroll continuously with acceleration | No action |
| PB10 Down | Next file; hold to scroll continuously with acceleration | No action |
| PB11 Confirm | Play the selected file | Stop playback and return to the list |

The buttons use falling-edge interrupts and approximately 150 ms of software debounce. The complete startup flow is:

```text
Wait for card → initialize SD → mount FatFs → calculate free space
              → scan files → three card-information pages → file list → playback
```

The three information pages show the filesystem and volume capacity, SD card type and physical capacity, and CID identity data. Each page remains for 3000 ms. During the first 300 ms, a white region expands horizontally from the left edge. Text and graphics become black on white as it passes, and the inverted area remains until the page ends. This is not a narrow highlight that slides away, nor the old full-page slide-in/slide-out effect.

Normal status messages use the same horizontal inversion language. `Loading / filename` and `Library / Playback stopped` retain the small center-box expand-and-collapse animation. The small popup remains for 1200 ms and can be dismissed early with Confirm.

In the file list, a selected long filename waits for about 700 ms and then scrolls back and forth. Bottom metadata alternates every 1500 ms between “resolution/FPS” and “frame count/OVID version.” Selection moves with easing within the same visible window and snaps directly into place across pages, so it never travels through unrelated entries.

<a id="troubleshooting"></a>

## 🩺 Diagnostics and Troubleshooting

Serial diagnostics, the startup diagnostic mode, watchdog behavior, HardFault capture, and common problems are documented separately: [read Diagnostics and Troubleshooting](docs/TROUBLESHOOTING_EN.md).

<a id="developer-reference"></a>

## 🧰 Developer Reference

The following documents are mainly intended for format inspection, display porting, and further development.

| Document | Contents |
|---|---|
| [📦 OVID File Format](docs/OVID_FORMAT_EN.md) | 16-byte header, page-major frames, and CRC |
| [🖥️ Display Porting and I2C](docs/PORTING_EN.md) | Size macros, controller selection, and the 1.4 MHz note |

<details>
<summary><strong>🗂️ Project Structure</strong> — firmware, drivers, tools, and configuration</summary>

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
│   ├── h2bin.py             # OVID generation and validation
│   └── merge_img2lcd.py     # Merge Img2Lcd frame C arrays
└── SD_Card_OVID_Player.code-workspace
```

`STM32F103/Core/隐藏关卡/` is a real historical directory in the repository, and tool examples also refer to it, so the documentation does not pretend that it has already been renamed. If it is renamed later, script comments, command examples, and related paths must be updated together.

</details>

<details>
<summary><strong>📊 Build Usage and Validation</strong> — Flash, RAM, and build matrix</summary>

The values below were measured with Arm GNU Toolchain 14.3.1, the default 128×64 configuration, and double buffering:

| Build | Flash | RAM |
|---|---:|---:|
| Debug (`-Os -g3`) | 55,812 B / 64 KiB (85.16%) | 10,040 B / 20 KiB (49.02%) |
| Release (`-Os -g0`) | 55,800 B / 64 KiB (85.14%) | 10,040 B / 20 KiB (49.02%) |

> [!NOTE]
> Debug still keeps the complete diagnostic paths and `-g3` symbols, but it also uses `-Os` so the image fits when built by different GNU Arm toolchain versions. A few variables may therefore be optimized during stepping. Release remains the recommended normal-use build. With Flash usage around 85%, check `arm-none-eabi-size` before adding another font or a large block of UI text.

The 128×32, 128×64, 128×128, and 96×64 configurations have been rebuilt, including both SSD1306 and SH1106 controller branches. The largest 128×128 Debug configuration uses 12,088 B of RAM (59.02%). Tool checks cover Python syntax and regeneration of the OVID test files.

A 30-minute continuous playback run, real card hot removal, and signal integrity at 1.4 MHz across different OLED modules remain target-hardware tests. A successful host build cannot replace those checks.

</details>

<p align="right"><a href="#top">⬆️ Back to top</a></p>

<a id="contributing"></a>

## 🤝 Contributing and Feedback

Issues and pull requests about display porting, SD compatibility, OVID tools, or UI behavior are welcome through [GitHub Issues](https://github.com/akasa828/SD_Card_OVID_Player/issues).

Before contributing, please read [CONTRIBUTING.md](CONTRIBUTING.md). For security-sensitive reports, follow the [security policy](SECURITY.md).

<a id="latest-update"></a>

## 📝 Latest Update

The current stable firmware is **v1.2.2**; **v1.2.6** is a driver-modularization prerelease. It publishes the common OLED and SD + FatFs cores as standalone projects while retaining versioned embedded copies so a downloaded ZIP still builds offline.

The complete version history is available in [CHANGELOG.md](CHANGELOG.md).

<a id="license"></a>

## 📄 License

Code written for this project is released under the [MIT License](LICENSE), copyright `riochihao`.

Third-party code included in the repository remains under its respective license, primarily:

- [STM32F1 HAL Driver](STM32F103/Drivers/STM32F1xx_HAL_Driver/LICENSE.txt)
- [CMSIS](STM32F103/Drivers/CMSIS/LICENSE.txt)
- [STM32F1 CMSIS Device](STM32F103/Drivers/CMSIS/Device/ST/STM32F1xx/LICENSE.txt)
- FatFs: license notices are included in the headers of `STM32F103/Core/fatfs/ff.c`, `ff.h`, and related source files
