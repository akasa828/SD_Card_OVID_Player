<a id="top"></a>

<p align="center">
  <strong>中文</strong> · <a href="README_EN.md">English</a>
</p>

<div align="center">

# SD Card OVID Player

**在 STM32F103 的单色 OLED 上，从 SD 卡选择并播放帧视频**

<p>
  <img alt="MCU STM32F103C8T6" src="https://img.shields.io/badge/MCU-STM32F103C8T6-03234B?style=flat-square&logo=stmicroelectronics&logoColor=white">
  <img alt="OLED SSD1306 or SH1106" src="https://img.shields.io/badge/OLED-SSD1306%20%7C%20SH1106-222222?style=flat-square">
  <img alt="Format OVID v2" src="https://img.shields.io/badge/Format-OVID%20v2-5B5BD6?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2EA44F?style=flat-square">
</p>

<p>
  <a href="https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.3.0-beta.2"><strong>下载 beta.2</strong></a> ·
  <a href="#quick-start"><strong>快速开始</strong></a> ·
  <a href="#showcase"><strong>查看演示</strong></a>
</p>

</div>

这个项目最开始只是为了在 STM32 上播放 Bad Apple。后来为了不把近 10 MB 的视频固定塞进 Flash，我换成了 SD 卡，也顺着这个问题加上 FatFs、文件浏览、播放器 UI 和自己的 OVID 帧格式。现在它更像一个完整的小播放器，而不再是一段只能播放单个数组的演示代码。

仓库里还有一个 Windows 桌面转换器，可以直接把图片、GIF、视频或图片目录变成 OLED 能播放的 `.BIN` 文件。想了解这一路为什么越做越复杂，可以看[完整的项目初衷](docs/PROJECT_STORY.md)。

这是个人学习和实验性质的嵌入式项目，目前主要在 STM32F103C8T6、SSD1306 OLED 和 SPI Micro SD 模块上测试。`v1.3.0-beta.2` 是最新测试版；如果只想使用已经发布的稳定固件，请选择 [`v1.2.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.2.2)。

<a id="showcase"></a>

## 实机演示

<p align="center">
  <img src="docs/images/mmexport1787248540213%20(1).gif" alt="OLED 播放与文件浏览演示" width="48%">
  <img src="docs/images/MP4_20260821_021752VLOG.gif" alt="等待插卡与启动流程演示" width="48%"><br>
  <sub>文件浏览与播放（左） · 等待插卡和启动 UI（右）</sub>
</p>

<a id="features"></a>

## 它现在能做什么

- 从 FAT12、FAT16 或 FAT32 SD 卡浏览 OVID `.BIN`，优先读取 `/function`，没有文件时回退根目录。
- 按文件头中的 1–120 FPS 播放；OVID v2 使用头部 CRC16 和逐帧 CRC32，坏帧会保留上一帧。
- SSD1306/SH1106 OLED 使用双缓冲和 I2C DMA，文件列表支持长文件名滚动、元数据轮播和播放反显。
- 插卡后自动显示容量、卡类型和 CID；拔卡、FatFs 读错或 OLED DMA 超时都有恢复路径。
- OVID Converter 支持素材预览、裁剪、阈值/抖动、批量任务、多线程转换和内置 OVID 播放器。
- 工程自带 CMake、VS Code 官方 STM32 扩展和 ST-Link 配置，下载完整仓库后可以直接按 `F5` 构建与刷写。

<a id="quick-start"></a>

## 快速开始

1. 从 [GitHub](https://github.com/akasa828/SD_Card_OVID_Player) 选择 **Code → Download ZIP**，并把整个压缩包解压到普通文件夹。
2. 安装 [VS Code](https://code.visualstudio.com/) 和 [STM32CubeIDE for Visual Studio Code](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension)。
3. 打开根目录的 `SD_Card_OVID_Player.code-workspace`；只使用 F103 时，也可以直接打开 `STM32F103/`。
4. 接受 STM32 扩展的项目发现、Bundle 下载和 CMake 配置提示，选择 `Release` preset。
5. 按下方接线表连接 OLED、SD、按键和 ST-Link，在 **Run and Debug** 中选择 `STM32: Build, flash and debug with ST-Link`，按 `F5`。停在 `main` 后再按一次 `F5` 继续运行。
6. 把 SD 卡格式化为 FAT/FAT32，在根目录建立 `function` 文件夹并放入 OVID `.BIN`。插卡复位后，用上下键选文件，按确认键播放。

第一次打开工程需要联网下载 STM32 工具 Bundle。CubeProgrammer 图形界面、命令行烧录和完整 SWD 说明放在[烧录指南](docs/FLASHING.md)。

<a id="converter"></a>

## OVID Converter

不想再经过 IrfanView、Img2Lcd 和中间 `.c/.h` 文件，可以直接下载 beta.2 转换器：

- [Windows x64 安装版](https://github.com/akasa828/SD_Card_OVID_Player/releases/download/v1.3.0-beta.2/OVID_Converter_Windows_x64_Setup_v1.3.0-beta.2.exe)
- [Windows x64 便携版](https://github.com/akasa828/SD_Card_OVID_Player/releases/download/v1.3.0-beta.2/OVID_Converter_Windows_x64_Portable_v1.3.0-beta.2.zip)

安装版会创建开始菜单入口，也可以选择桌面快捷方式；便携版解压后直接运行，不写入安装信息。两种版本都带有运行时、Pillow 和 FFmpeg，不要求另外安装 Python。

```text
选择图片、图片目录、GIF 或视频
→ 预览和裁剪
→ 设置 OLED 尺寸、FPS 与黑白算法
→ 生成并校验 OVID .BIN
```

默认是 128×64、15 FPS、固定阈值 128；也可以切换 Floyd–Steinberg 抖动。转换器会在输出完成后重新检查 OVID 文件头、长度和逐帧 CRC。

> [!WARNING]
> Windows 程序尚未签名，SmartScreen 可能显示“未知发布者”。请只从本仓库 Release 下载，并用同一页面的 `SHA256SUMS.txt` 核对文件。

仍想手动检查每一步数据，可以继续使用[原有 Img2Lcd 制作流程](docs/OVID_TUTORIAL.md)。

Release 中还附有 `SD_Card_OVID_Player_Sample_Videos.zip`，里面是可以直接复制到 SD 卡测试的 OVID 文件。固件 `.elf`、`.bin` 和所有 Windows 包共用同一份 `SHA256SUMS.txt`。

<a id="hardware"></a>

## 硬件与接线

需要 STM32F103C8T6 最小系统板、SSD1306/SH1106 I2C 单色 OLED、SPI Micro SD 模块、三个按键和 ST-Link。USB-TTL 只用于可选的串口诊断。

| 功能 | STM32 引脚 | 外设端 | 说明 |
|:---:|:---:|:---:|:---:|
| SPI1 SCK | PA5 | SD SCK/CLK | SPI mode 0 |
| SPI1 MISO | PA6 | SD MISO/DO | SD → MCU |
| SPI1 MOSI | PA7 | SD MOSI/DI | MCU → SD |
| SD CS | PB0 | SD CS | 低电平选中 |
| I2C1 SCL | PB6 | OLED SCL | 开漏，需要上拉 |
| I2C1 SDA | PB7 | OLED SDA | 开漏，需要上拉 |
| 上 / 下 / 确认 | PB1 / PB10 / PB11 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| USART1 TX | PA9 | USB-TTL RX | 可选，115200 8N1，仅发送 |
| 供电与共地 | 3.3 V / GND | SD、OLED、按键 | 先确认模块电压要求 |

ST-Link 使用 `PA13/SWDIO`、`PA14/SWCLK` 和 `GND`，建议同时连接 `NRST`。不要在不了解供电方式时，让外部电源和 ST-Link 同时驱动同一条 3.3 V 电源轨。

<a id="sd-card"></a>

## SD 卡与按键

推荐目录：

```text
SD 卡根目录/
├── function/
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN
```

固件不会自动创建 `/function`。首次插卡会实际扫描 FAT 来计算剩余空间，大容量或碎片较多的卡可能需要几秒；按确认键可以跳过，此时显示 `Free: N/A`，但仍会进入文件列表。

| 按键 | 文件列表 | 播放中 |
|---|---|---|
| PB1 上 | 上一个文件；长按加速 | 无操作 |
| PB10 下 | 下一个文件；长按加速 | 无操作 |
| PB11 确认 | 播放选中文件 | 停止并返回列表 |

```text
等待插卡 → 挂载 FatFs → 计算容量 → 扫描文件
         → 三张卡信息页 → 文件列表 → 播放
```

<a id="docs"></a>

## 可复用驱动与文档

播放器内置的两个驱动也整理成了独立项目：

- [STM32-HAL-SSD1306-SH1106](https://github.com/akasa828/STM32-HAL-SSD1306-SH1106)：绘图、双缓冲、I2C DMA 和控制器适配。
- [STM32-HAL-SPI-SD-FatFs](https://github.com/akasa828/STM32-HAL-SPI-SD-FatFs)：SPI SD 协议核心、STM32 HAL 端口和 FatFs `diskio` 对接。

| 文档 | 内容 |
|---|---|
| [项目初衷](docs/PROJECT_STORY.md) | 从 Bad Apple 到 SD 卡播放器的完整经历 |
| [烧录指南](docs/FLASHING.md) | ST-Link、VS Code、CubeProgrammer GUI/CLI |
| [OVID 制作教程](docs/OVID_TUTORIAL.md) | Converter 与可选的 Img2Lcd 手动流程 |
| [OVID 文件格式](docs/OVID_FORMAT.md) | 16 字节文件头、页主序和 CRC |
| [诊断与常见问题](docs/TROUBLESHOOTING.md) | SD、OLED、串口、看门狗和 HardFault |
| [移植说明](docs/PORTING.md) | 尺寸宏、SSD1306/SH1106 与 I2C |
| [开发参考](docs/DEVELOPMENT.md) | 项目结构、资源占用、编译矩阵和后续计划 |

<a id="version"></a>

## 版本、贡献和许可证

- **最新测试版：** [`v1.3.0-beta.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.3.0-beta.2)
- **稳定固件：** [`v1.2.2`](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.2.2)
- **完整记录：** [CHANGELOG.md](CHANGELOG.md)

beta.2 主要整理了转换器的双预览、时间轴和批量任务；它不会改变 OVID v2 文件格式，已有能在播放器中工作的 v2 文件无需重新转换。

发现问题或有改进想法，可以提交 [Issue](https://github.com/akasa828/SD_Card_OVID_Player/issues)。准备修改代码时请先看 [CONTRIBUTING.md](CONTRIBUTING.md)；不适合公开的安全问题请按 [SECURITY.md](SECURITY.md) 报告。

项目自有代码使用 [MIT License](LICENSE)。STM32 HAL、CMSIS、FatFs 以及转换器所用第三方组件继续遵循各自许可证。

<p align="right"><a href="#top">返回顶部 ↑</a></p>
