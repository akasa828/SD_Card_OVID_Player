# Embedded driver sources

The player keeps local copies so a downloaded ZIP can build without Git or a
network connection. Application-specific HAL recovery, watchdog, diagnostics,
and UI code remain in the player.

| Embedded component | Upstream | Version | Commit |
|---|---|---|---|
| SSD1306/SH1106 core and STM32 HAL adapter | https://github.com/akasa828/STM32-HAL-SSD1306-SH1106 | `v1.0.0` | `6bb05e7770b08ddee4d665f4ab858af0a3c7b913` |
| SPI SD core, STM32 HAL adapter, and FatFs bridge | https://github.com/akasa828/STM32_HAL-SPI_SD-FatFs | `v1.0.0` | `530dbcc5b0baca7c0b78848c4ece63d6bf42db2f` |

Use `tools/sync_embedded_drivers.ps1` from the repository root to copy a checked
and reviewed sibling checkout into the player. The script never deletes the
existing `STM32F103_Driver_Examples` prototype directory.
