<a id="top"></a>

# 🖥️ 屏幕适配与 I2C

[← 返回项目 README](../README.md)

这个项目最初就是按 128×64 写的。如果屏幕控制器兼容，通常只要修改 `STM32F103/Core/OLED/oled.hpp` 中的两个宏：

```c
#define OLED_WIDTH  128
#define OLED_HEIGHT 64
```

显存会自动推导：

```text
OLED_PAGES     = OLED_HEIGHT / 8
OLED_GRAM_SIZE = OLED_PAGES × OLED_WIDTH
```

`OLED_WIDTH` 的合法范围是 1–255；`OLED_HEIGHT` 必须在 8–255 之间并能被 8 整除，所以实际最大值是 248。单帧可以超过过去固定的 1024 B，只要不超过当前 `OLED_GRAM_SIZE`。全屏视频直接读入后台显存，小尺寸视频只使用一行 `OLED_WIDTH` 大小的页缓冲，再居中合成。

控制器、列偏移和默认镜像也在同一文件里：

```c
#define OLED_CONTROLLER OLED_CONTROLLER_SSD1306  // 或 OLED_CONTROLLER_SH1106
#define OLED_COLUMN_OFFSET 0                     // 常见 SH1106 模组为 2
#define OLED_DEFAULT_H_FLIP 1
#define OLED_DEFAULT_V_FLIP 1
```

宏能通过编译并不等于硬件一定支持。控制器的 GDDRAM、列和页地址范围、模块的真实像素数都是硬限制；STM32F103C8T6 只有 20 KiB RAM，双缓冲、FatFs 长文件名和诊断缓冲也都要占空间。

> [!WARNING]
> 默认的 `1,399,999 Hz` 已在项目开发使用的硬件上验证，但不代表所有 OLED 模块、上拉电阻和连接线都能稳定工作。

驱动会统计 NACK 和 DMA 超时，连续三次恢复失败后依次降到 1 MHz、800 kHz 和 400 kHz。如果一上电就花屏或闪烁，先缩短连线、检查供电和上拉，再考虑降低 `I2C1_INITIAL_CLOCK_HZ`，或在配置 CMake 时传入 `OLED_I2C_CLOCK_OVERRIDE`。比起追求纸面速度，稳定刷新更重要。

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>
