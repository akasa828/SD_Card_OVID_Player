# Flashing the STM32

[中文](FLASHING.md) · **English** · [Back to README](../README_EN.md)

## 1. Connect ST-Link

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

## 2. Press F5 in VS Code

After connecting ST-Link, select `STM32: Build, flash and debug with ST-Link` under **Run and Debug**, then press `F5`. `STM32F103/.vscode/launch.json` asks the official extension to perform this sequence:

```text
Build the active CMake preset → locate its ELF → download through ST-Link → stop at main
```

Press `F5` once more after the first stop at `main` to continue execution. The configuration does not hard-code `build/Debug`, a drive letter, or a username. When the Release preset is selected, the extension uses the corresponding Release ELF.

## Alternative: Flash Manually with STM32CubeProgrammer

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
