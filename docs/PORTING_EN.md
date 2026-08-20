<a id="top"></a>

<p align="center">
  <a href="PORTING.md">中文</a> · <strong>English</strong>
</p>

# 🖥️ Display Porting and I2C

[← Back to the project README](../README_EN.md)

This project was originally written for a 128×64 display. If the display controller is compatible, adapting the resolution usually only requires changing two macros in `STM32F103/Core/OLED/oled.hpp`:

```c
#define OLED_WIDTH  128
#define OLED_HEIGHT 64
```

The framebuffer dimensions are derived automatically:

```text
OLED_PAGES     = OLED_HEIGHT / 8
OLED_GRAM_SIZE = OLED_PAGES × OLED_WIDTH
```

The valid range for `OLED_WIDTH` is 1–255. `OLED_HEIGHT` must be between 8 and 255 and divisible by 8, so the practical maximum is 248. A frame may be larger than the old fixed limit of 1024 B as long as it does not exceed the current `OLED_GRAM_SIZE`. Full-screen video is read directly into the back framebuffer. Smaller video uses only one `OLED_WIDTH`-byte page buffer and is composited in the center.

The controller, column offset, and default mirroring options are defined in the same file:

```c
#define OLED_CONTROLLER OLED_CONTROLLER_SSD1306  // or OLED_CONTROLLER_SH1106
#define OLED_COLUMN_OFFSET 0                     // commonly 2 on SH1106 modules
#define OLED_DEFAULT_H_FLIP 1
#define OLED_DEFAULT_V_FLIP 1
```

A configuration compiling successfully does not guarantee that the hardware can support it. The controller's GDDRAM size, column and page address ranges, and the module's actual pixel count remain hard limits. The STM32F103C8T6 has only 20 KiB of RAM, which must also hold the double buffers, FatFs long-file-name storage, and diagnostic buffers.

> [!WARNING]
> The default `1,399,999 Hz` setting has been verified on the hardware used during development, but that does not mean every OLED module, pull-up resistor configuration, or wire length will run reliably at this speed.

The driver counts NACKs and DMA timeouts. After three consecutive recovery failures, it steps down through 1 MHz, 800 kHz, and 400 kHz. If the display is corrupted or flickers immediately after power-up, shorten the wiring and check the power supply and pull-ups first. Then consider lowering `I2C1_INITIAL_CLOCK_HZ` or passing `OLED_I2C_CLOCK_OVERRIDE` when configuring CMake. Stable refresh is more important than a higher nominal bus speed.

<p align="right"><a href="#top">⬆️ Back to top</a></p>
