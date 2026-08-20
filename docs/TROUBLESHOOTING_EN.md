<a id="top"></a>

<p align="center">
  <a href="TROUBLESHOOTING.md">中文</a> · <strong>English</strong>
</p>

# Diagnostics and Troubleshooting

[← Back to the project README](../README_EN.md)

## 🩺 Diagnostics

USART1 TX outputs SD initialization, FatFs, player, UI frame-rate, and fault information at 115200 8N1. During normal animation, the serial port reports the actual FPS, longest frame interval, and number of late frames once per second. Blocking SD operations, DMA/I2C recovery, and automatic bus-speed fallback are outside the 60 FPS hardware acceptance range.

Hold the Up and Down buttons together during startup to open the three-page diagnostic screen. It shows the reset reason, Flash/RAM use, stack margin, buttons, SD/SPI state, OLED DMA state, current I2C speed, and the PC/LR/CFSR values from the most recent HardFault.

**Pressing Confirm on the second page runs an SD self-test: save the original block → write → read back → verify → restore.**

> [!WARNING]
> The SD self-test temporarily overwrites a raw block on the card. The firmware restores the original data afterward, but running the test is still not recommended when the power supply is unstable.

The system also enables an independent watchdog with a timeout of about 8 seconds. Debug builds freeze it while the debugger has paused the core; Release builds leave it running independently. HardFault context is stored in `.noinit` SRAM and reported on the display and over serial after reboot.

## ❓ Troubleshooting Q&A

### Why is the OLED corrupted at 1.4 MHz?

1.4 MHz is beyond the usual operating conditions of many modules. **Lowering the initial bus speed directly is the usual fix.** Automatic fallback only takes effect after the driver detects consecutive failures and cannot correct every signal-integrity problem.

**Solution:** open `./Core/Inc/i2c.h` and change the `1399999UL` value:

```c
#define I2C1_INITIAL_CLOCK_HZ 1399999UL
```

### Why does the player not return to the waiting screen immediately after I remove the card?

The information pages and file list check the card every 500 ms and require two consecutive failures, so detection can take up to about 1 second. During playback, removal is detected through a file-read error. After reinserting the card, the waiting screen retries initialization every 700 ms.

---

<p align="right"><a href="#top">⬆️ Back to top</a></p>
