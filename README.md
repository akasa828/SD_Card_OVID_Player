<a id="top"></a>

<div align="center">

# SD Card OVID Player

**基于 STM32F103、Micro SD 和单色 OLED 的离线帧视频播放器**

<p>
  <img alt="MCU STM32F103C8T6" src="https://img.shields.io/badge/MCU-STM32F103C8T6-03234B?style=flat-square&logo=stmicroelectronics&logoColor=white">
  <img alt="OLED SSD1306 or SH1106" src="https://img.shields.io/badge/OLED-SSD1306%20%7C%20SH1106-222222?style=flat-square">
  <img alt="Format OVID v2" src="https://img.shields.io/badge/Format-OVID%20v2-5B5BD6?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2EA44F?style=flat-square">
</p>

<p>
  <a href="#quick-start"><strong>快速开始</strong></a> ·
  <a href="#hardware"><strong>硬件接线</strong></a> ·
  <a href="#create-ovid"><strong>制作 OVID</strong></a> ·
  <a href="#troubleshooting"><strong>常见问题</strong></a> ·
  <a href="CHANGELOG.md"><strong>更新记录</strong></a>
</p>

<p>
  <a href="https://github.com/akasa828/SD_Card_OVID_Player">GitHub 仓库</a> ·
  <a href="https://github.com/akasa828/SD_Card_OVID_Player/archive/refs/heads/main.zip">下载 ZIP</a>
</p>

</div>

SD Card OVID Player 运行在 STM32F103C8T6 上。视频文件存放在 Micro SD 卡中，固件负责浏览和校验文件，再按照文件头中的帧率将画面输出到 SSD1306 或 SH1106 单色 OLED。播放过程只需要三个按键，不依赖电脑或网络。这里使用的 OVID 可以理解为 OLED Video，它是一种给单色屏准备的帧数据格式。

仓库现在按芯片平台分目录管理：`STM32F103/` 是当前可用的完整固件，`ESP32/` 暂时作为后续移植的空目录。

<a id="motivation"></a>

## 💡 项目初衷

<!-- PROJECT_MOTIVATION_START -->
<!-- 请在这里写明：为什么开始这个项目、希望解决什么问题，以及开发过程中发生了哪些变化。完成后删除本行注释和下面的占位文字，但请保留 START/END 标记。 -->

【请在这里填写项目初衷】

<!-- PROJECT_MOTIVATION_END -->

<!-- PROJECT_SHOWCASE_START
## 🖼️ 项目展示

![硬件实物](docs/images/hardware-overview.jpg)
![UI 流程](docs/images/ui-flow.gif)
![文件浏览器](docs/images/file-browser.jpg)

放入真实素材后，删除 PROJECT_SHOWCASE_START 和 PROJECT_SHOWCASE_END 所在行即可显示本节。
PROJECT_SHOWCASE_END -->

</table>

<a id="navigation"></a>

<p align="center"><strong>🧭 文档导航</strong></p>

| 🚀 用户指南 | 🧰 开发者参考 |
|---|---|
| [快速开始](#quick-start) · [硬件接线](#hardware) · [烧录固件](#flash) | [OVID 格式](#developer-reference) · [屏幕适配](#developer-reference) |
| [准备 SD 卡](#sd-card) · [制作 OVID](#create-ovid) | [项目结构](#developer-reference) · [资源占用](#developer-reference) |
| [按键与播放](#controls) · [常见问题](#troubleshooting) | [参与开发](#contributing) · [许可证](#license) |

<a id="quick-start"></a>

## 🚀 快速开始

本项目在`Vscode`环境下开发，配合 [STM32CubeIDE for Visual Studio Code 扩展包](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension)完成。

1. **下载源码 ZIP。** 打开项目的 [GitHub 仓库](https://github.com/akasa828/SD_Card_OVID_Player)，点击 **Code → Download ZIP**，下载完整项目。
2. **解压项目。** 把 ZIP 完整解压到普通文件夹中，不要直接在压缩包预览界面里打开或编译。
3. **用 VS Code 打开工作区。** 在解压后的仓库根目录中打开 `SD_Card_OVID_Player.code-workspace`，左侧会同时显示 `STM32F103` 和 `ESP32`。如果只使用当前固件，也可以通过 **File → Open Folder**（文件 → 打开文件夹）直接打开包含 `CMakeLists.txt` 的 `STM32F103/` 目录。
4. **安装扩展。** 安装上述 [STM32 扩展包](https://marketplace.visualstudio.com/items?itemName=stmicroelectronics.stm32-vscode-extension)。首次打开时，接受项目发现、工具 bundle 下载和 CMake 配置提示，直到右下角不再提示下载 `Bundle` 包。
5. **选择构建类型。** 在 STM32/CMake 项目面板中选择 `Debug` 或 `Release`。调试建议选 Debug，正常烧录建议选 Release。
6. **连接并刷写。** 按[接线表](#wiring)连接 OLED、Micro SD、三个按键和 ST-Link，然后按 `F5`，选择 `STM32: Build, flash and debug with ST-Link`。扩展会自动构建并下载当前 preset 的 ELF；程序停在 `main` 时再按一次 `F5` 即可继续运行。
7. **准备 OVID 文件。** 把 SD 卡格式化为 FAT 或 FAT32，在根目录创建 `function` 文件夹。按照[生成 OVID 文件](#create-ovid)中的流程准备素材、用 Img2Lcd 取模，再通过仓库里的合并脚本和 `h2bin.py` 生成 `.BIN`。
8. **插卡并播放。** 将 `DEMO.BIN` 放入 `/function`，插卡并复位。三张卡信息页结束后，用上下键选择文件，按确认键播放；播放中再次按确认键返回列表。

> [!NOTE]
> 首次配置需要联网下载项目声明的 STM32 工具 bundles。目前 GitHub Releases 只发布 `v1.2.0`，仓库暂未提供演示视频。

<a id="features"></a>

## ✨ 特性

- **💾 完整的 SD 启动流程：** 等待插卡、挂载、计算卷容量、扫描视频文件，再依次显示存储、卡片和身份信息。文件优先从 `/function` 读取，没有匹配文件时回退到根目录读取。
- **🛡️ OVID v2 完整性校验：** 使用文件头 CRC16 和逐帧 CRC32。坏帧不会刷到 OLED，而是保留上一帧继续读取。
- **⏱️ 稳定播放时序：** 支持 1–120 FPS，并累计毫秒除法余数，长时间播放不会因整数截断逐渐变慢。
- **🖥️ 流畅的 OLED UI：** 使用双缓冲和 I2C DMA。128×64、1.4 MHz I2C 的正常环境下，动画按 16 ms 周期刷新。
- **📂 更易用的文件浏览器：** 支持长按加速、选中位置记忆、长文件名往返滚动，以及分辨率、帧率、帧数和格式版本轮播。
- **🔄 自动拔卡恢复：** 信息页和文件列表每 500 ms 探测一次卡状态；连续两次失败后卸载 FatFs 并返回等待插卡界面，播放读错误走同一套恢复流程。
- **💾 高效的 SD 卡驱动：** 依据 SD 卡规范实现 SPI 模式读写，并通过 `diskio` 接口接入 FatFs 文件系统。

> [!NOTE]
> 遇到 SD 超时或 I2C/DMA 故障恢复时，动画流畅度会暂时让位给可靠性。

<a id="hardware"></a>

## 🔌 硬件与接线

当前工程使用以下硬件及材料：

- 面包板
- 跳线
- 公对公 x3
- 母对母 x10
- STM32F103C8T6 最小系统板；链接脚本按 64 KiB Flash、20 KiB RAM 配置
- SSD1306 或 SH1106 I2C 单色 OLED
- SPI 接口的 Micro SD 卡模块，使用 3.3 V 逻辑电平
- 三个按键
- 可选的 3.3 V USB-TTL 模块，用来看串口诊断

<a id="wiring"></a>

### 📌 接线表

| 功能 | STM32 引脚 | 外设端 | 说明 |
|:---:|:---:|:---:|:---:|
| SPI1 SCK | PA5 | SD SCK/CLK | SPI mode 0 |
| SPI1 MISO | PA6 | SD MISO/DO | SD → MCU |
| SPI1 MOSI | PA7 | SD MOSI/DI | MCU → SD |
| SD CS | PB0 | SD CS | 低电平选中 |
| I2C1 SCL | PB6 | OLED SCL | 开漏，需要上拉 |
| I2C1 SDA | PB7 | OLED SDA | 开漏，需要上拉 |
| 上键 | PB1 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| 下键 | PB10 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| 确认键 | PB11 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| USART1 TX | PA9 | USB-TTL RX | 可选，115200 8N1，仅发送 |
| 共地 | GND | SD/OLED/按键/串口 GND | 必须共地 |
| 供电 | 3.3 V | SD/OLED VCC | 先确认模块电压要求 |


<a id="flash"></a>

## ⚡ 烧录到 STM32

### 1. 连接 ST-Link

烧录使用 STM32F103 的 SWD 接口：

| ST-Link | STM32F103C8T6 | 说明 |
|---|---|---|
| SWDIO | PA13 | SWD 数据 |
| SWCLK | PA14 | SWD 时钟 |
| GND | GND | 必须共地 |
| NRST | NRST | 可选，但连接后更容易处理无法连接的情况 |
| VTref/3.3 V | 3.3 V | 作为目标电压参考；是否能给目标板供电取决于探针型号 |

| ST-Link | SD卡读卡器 | 说明 |
|---|---|---|
| 5V | 5V | 通电 |
| GND | GND | 必须共地 |

> [!WARNING]
> 目标板可以单独使用稳定的 3.3 V 电源。不要在不了解 ST-Link 供电方式时，让外部电源和 ST-Link 同时向同一条 3.3 V 电源轨供电。正常从 Flash 启动时，板上的 `BOOT0` 应保持低电平。

### 2. 在 VS Code 中按 F5

连接 ST-Link 后，在左侧 **Run and Debug** 中选择 `STM32: Build, flash and debug with ST-Link`，再按 `F5`。`STM32F103/.vscode/launch.json` 会调用官方扩展完成以下工作：

```text
构建当前 CMake preset → 取得对应 ELF → 通过 ST-Link 下载 → 停在 main
```

第一次停在 `main` 后，再按一次 `F5` 就会继续运行。这里没有写死 `build/Debug`、盘符或用户名；选择 Release preset 时，扩展会使用 Release 对应的 ELF。

<details>
<summary><strong>备用：使用 STM32CubeProgrammer 手动烧录</strong></summary>

扩展不可用时，也可以使用 STM32CubeProgrammer 的图形界面：

1. 接好 ST-Link 和目标板，再打开 STM32CubeProgrammer。
2. 在右侧连接方式中选择 `ST-LINK`，接口选择 `SWD`，点击 **Connect**。
3. 点击 **Open file**，选择：

   ```text
   STM32F103/build/Release/SD_Card_OVID_Player.elf
   ```

4. 点击 **Download**。下载完成并通过校验后，点击复位按钮，或者给目标板重新上电。

实际使用建议烧录 Release。Debug 同样可以运行，但会占用更多 Flash，主要用于断点调试和故障排查。

如果更习惯命令行，可以把 STM32CubeProgrammer 的 `bin` 目录加入 `PATH`，再进入 `STM32F103/` 目录执行：

```powershell
STM32_Programmer_CLI.exe -c port=SWD `
  -w "build/Release/SD_Card_OVID_Player.elf" -v -rst
```

同一条命令写成单行是：

```powershell
STM32_Programmer_CLI.exe -c port=SWD -w "build/Release/SD_Card_OVID_Player.elf" -v -rst
```

其中 `-w` 写入固件，`-v` 回读校验，`-rst` 在完成后复位目标板。这里烧录的是 ELF，所以不附加写入地址。如果以后自行导出裸 `.bin`，才需要把 `0x08000000` 作为写入地址传给烧录工具。

</details>


<a id="sd-card"></a>

## 💾 准备 SD 卡

固件支持 FAT12、FAT16 和 FAT32，不支持 exFAT 或 NTFS。FatFs 已开启最长 63 字符的长文件名，不过 OLED 字库只包含 ASCII 字符，文件名最好仍使用 ASCII 或英文字符

推荐的目录结构如下：

```text
SD 卡根目录/
├── function/          # 这里有 .BIN 时优先使用
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN        # /function 没有 .BIN 时才会扫描到
```

固件不会自动创建 `/function`。首次插卡时，`f_getfree()` 会实际扫描 FAT 来计算剩余空间，不相信可能已经过期的 FAT32 FSInfo，所以大容量或碎片较多的卡可能需要等几秒。进度条用千分比定点值平滑追赶真实扫描进度，活动点仍会持续移动，不会只按整数百分比一格一格跳。

> [!TIP]
> 如果不想等待，可以在扫描页按确认键跳过。播放器会显示 `Free: N/A`，但仍然继续扫描文件并进入列表；`100%` 只会在 `f_getfree()` 真正返回后出现。

<a id="create-ovid"></a>

## 🎬 生成 OVID 文件
> 以下 拿 `Bad Apple.mp4 举例`

由于`F103C8T6`不适合也不好直接塞个`MP4`解码器进去，导致步骤比较多，但是能播放已经很好了


```text
图片帧 → 黑白 BMP → Img2Lcd 单帧 .c → 合并 .h → OVID .BIN
```

仓库里会用到两个 Python 脚本：[`tools/merge_img2lcd.py`](tools/merge_img2lcd.py) 负责合并视频帧取模得到的一系列`.c`文件 → `.h`文件，[`tools/h2bin.py`](tools/h2bin.py) 负责生成和检查 OVID二进制文件。下面这条主流程只使用 Python 标准库，不需要另外安装 Python 包。

| 输入素材 | 从哪里开始 |
|---|---|
| 🎞️ 视频 | PotPlayer 导出 JPG 帧 → IrfanView 批量转黑白 BMP |
| 🪄 GIF | IrfanView 拆帧并批量转黑白 BMP |
| 🖼️ 普通图片 | 图片已经符合尺寸和黑白要求时，直接从 Img2Lcd 开始 |

###  按素材类型准备图片帧

#### 🎞️ 视频：先用 PotPlayer 导出帧

用 PotPlayer 的连续截图功能，把视频的每一帧保存为 `BMP` 并放进同一个文件夹。导出帧率要记下来，因为稍后传给 `h2bin.py` 的 `--fps` 应与这里一致。

![alt text](docs/images/image-1.png)
按照这样设置
![alt text](docs/images/image.png)
![alt text](docs/images/image-2.png)
然后等待视频播放完成就将所有帧截取完了
![alt text](docs/images/image-3.png)


#### 🪄 GIF：直接用 IrfanView 拆帧

GIF 不需要经过 PotPlayer。直接用 IrfanView 打开 GIF，把其中的所有帧拆出并按顺序保存，再使用批量转换功能统一尺寸、转成黑白图并输出为 BMP。处理完成后，直接继续下面的 Img2Lcd 步骤。

![alt text](docs/images/image-4.png)
![alt text](docs/images/image-5.png)
![alt text](docs/images/image-6.png)
同样得到了很多帧
![alt text](docs/images/image-7.png)
但是第一张你会发现大小和别的不一样，所以删掉就行
![alt text](docs/images/image-12.png)

然后再用IrfanView处理尺寸成`128x64`
![alt text](docs/images/image-13.png)
![alt text](docs/images/image-14.png)
![alt text](docs/images/image-15.png)
![alt text](docs/images/image-16.png)
选择输出目录
![alt text](docs/images/image-17.png)
随后开始即可
> [!IMPORTANT]
> 请检查各个图片是否格式一致，比如下面这里又发现有张不对劲的，否则到时候放出来就会“闪帧”
> ![alt text](docs/images/image-18.png)
#### 🖼️ 普通图片：按需要预处理

如果素材本来就是一张或一组已经处理好的图片，可以从 Img2Lcd 这一步开始；需要统一尺寸或黑白效果时，再先用 IrfanView 做一次批处理。



### 用 Img2Lcd 生成单帧 `.c`

![alt text](docs/images/image-8.png)
![alt text](docs/images/image-9.png)
随后会将多个`.c`文件放在当前你选择的这个图片目录的`./batch`文件夹下，这个文件夹是程序自己生成的
![alt text](docs/images/image-10.png)
![alt text](docs/images/image-11.png)
### 把多个 `.c` 合并成单个 `.h`

在项目根目录执行：
```bash
python tools/merge_img2lcd.py img2lcd_c/ merged_frames.h
```
![alt text](docs/images/image-19.png)

修改之后的我的指令就变成了这样：
```python
python C:\Essential\03-嵌入式与电子工程\Embedded\stm32\workspace\SD_Card_OVID_Player\tools\merge_img2lcd.py C:\Users\riochihao\Downloads\emojis\batch C:\Users\riochihao\Downloads\emojis\gif.h
```
![alt text](docs/images/image-20.png)
合并工具只读取该目录第一层的 `.c` 文件，并按自然顺序排列

### 生成 OVID `.BIN`

下面以 128×64、15 FPS 为例：

```bash
python tools/h2bin.py merged_frames.h OUTPUT.BIN -W 128 -H 64 --fps 15
```
同理，我运行的时候就是
```python
python C:\Essential\03-嵌入式与电子工程\Embedded\stm32\workspace\SD_Card_OVID_Player\tools\h2bin.py C:\Users\riochihao\Downloads\emojis\gif.h GIF_15.BIN -W 128 -H 64 --fps 15
```

宽高必须与 Img2Lcd 取模时一致。脚本会检查每个数组是否正好等于 `ceil(height/8) × width`，并报告帧数、单帧字节数、总时长和固件至少需要的 OLED 宏。

> [!TIP]
> `h2bin.py` 默认生成当前固件使用的 OVID v2。它带有头部 CRC16 和逐帧 CRC32，发现坏帧时更容易诊断，也不会把损坏帧直接刷到 OLED。

### 检查并复制到 SD 卡

生成后先运行一次检查：

```bash
python tools/h2bin.py info OUTPUT.BIN
```

确认格式、宽高、帧数、FPS 和 CRC 都正常后，再把 `.BIN` 放入 SD 卡的 `/function` 目录。

<details>
<summary><strong>可选：直接从图片目录或 GIF 生成</strong></summary>

`h2bin.py` 仍然保留了直接读取图片和 GIF 的快捷方式。这条路线需要 Pillow：

```bash
python -m pip install Pillow
python tools/h2bin.py from-images frames/ OUTPUT.BIN -W 128 -H 64 --fps 15
```

它适合快速测试；上面的 Img2Lcd 流程更便于按照图形工具中的扫描方式检查每一帧取模结果。

</details>

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>

<a id="controls"></a>

## 🎮 按键与播放流程

| 按键 | 文件列表 | 播放中 |
|---|---|---|
| PB1 上 | 上一个文件；长按连续滚动并加速 | 无操作 |
| PB10 下 | 下一个文件；长按连续滚动并加速 | 无操作 |
| PB11 确认 | 播放选中的文件 | 停止播放并返回列表 |

按键使用下降沿中断和大约 150 ms 的软件去抖。启动后的完整流程是：

```text
等待插卡 → 初始化 SD → 挂载 FatFs → 计算剩余空间
         → 扫描文件 → 三张卡信息页 → 文件列表 → 播放
```

三张信息页分别显示文件系统与卷容量、SD 卡类型与物理容量、CID 身份信息。每页停留 3000 ms；前 300 ms 中，白色区域从屏幕左侧横向扩张，扫过的文字和图形变成白底黑色，反显区域会保留到这一页结束。这里不是一条滑过后消失的窄光带，也没有旧版的整页滑入、滑出。

普通状态提示使用同样的横向反显语言；`Loading / 文件名` 和 `Library / Playback stopped` 保留中心小矩形展开、收起的动画。小方框弹窗停留 1200 ms，按确认键可以提前关闭。

文件列表中，选中的长文件名静止约 700 ms 后开始往返滚动。底部信息每 1500 ms 在“分辨率/FPS”和“帧数/OVID 版本”之间切换；同一窗口内的选择框使用缓动，跨页时则直接对齐，避免选择框穿过无关条目。

<a id="troubleshooting"></a>

## 🩺 诊断

USART1 TX 会以 115200 8N1 输出 SD 初始化、FatFs、播放器、UI 帧率和故障信息。正常动画期间，串口每秒报告实际 FPS、最长帧间隔和超时帧数。SD 阻塞、DMA/I2C 恢复和自动降速不属于 60 FPS 的硬件验收区间。

开机时同时按住上键和下键可以进入三页诊断界面。这里能看到复位原因、Flash/RAM、栈余量、按键、SD/SPI、OLED DMA、当前 I2C 速率和最近一次 HardFault 的 PC/LR/CFSR。第二页按确认会执行“保存原块 → 写入 → 读回 → 校验 → 恢复”的 SD 自检。

> [!WARNING]
> SD 自检会临时改写卡上的原始块。固件随后会写回原数据，但供电不稳定时仍然不建议运行。

系统还启用了约 8 秒的独立看门狗。Debug 构建在调试器暂停内核时会冻结它，Release 则保持独立运行。HardFault 现场保存在 `.noinit` SRAM，重启后会通过屏幕和串口提示。

## ❓常见问题 Q & A
### 为什么一直停在 Calculating free space？

这一步在扫描整张 FAT，而不是读取 FAT32 中可能过期的缓存值。卡越大、碎片越多，第一次扫描越慢。活动点和进度条仍在移动就可以继续等待；如果只想尽快进入列表，按确认键跳过即可。

如果动画彻底停止，先看 PA9 串口最后输出的阶段。固件已经为目录扫描加入 5 秒/8192 项保护，也修复过 `Preparing UI` 阶段由不安全 `%llu` 格式化触发的 HardFault；再次出现时，串口和诊断页里的故障地址会比屏幕现象更有用。

### 为什么找不到 `.BIN`？

先确认扩展名确实是 `.BIN`。固件优先扫描 `/function`，里面没有匹配文件才回退根目录；空文件页会周期重扫。文件名可以较长，但屏幕无法正确显示中文字形。

### 为什么提示 Bad OVID、Invalid OVID 或 Frame too big？

用下面的命令检查 magic、版本、CRC、帧率和文件总长度：

```bash
python tools/h2bin.py info YOUR_FILE.BIN
```

`Frame too big` 表示视频宽或高超过当前 OLED 宏。单帧超过 1024 B 本身不是错误，只要它仍然不大于 `OLED_GRAM_SIZE`。

### 为什么显示 Unsupported FS 或 Mount failed？

`Unsupported FS` 通常说明卷不是 FAT12、FAT16 或 FAT32。先备份卡里的数据，再重新格式化。`Mount failed` 更常见于供电、共地、SPI 接线或 CS 引脚问题，具体 FatFs 错误码可以从串口看到。

### 为什么 OLED 在 1.4 MHz 下花屏？

1.4 MHz 超出了不少模块的常规工作条件。**直接降低初始速率即可解决**，自动降速只能在驱动识别到连续故障后生效，无法修复所有信号完整性问题。

### 拔卡后为什么没有立刻回到等待界面？

信息页和列表每 500 ms 检测一次，并要求连续两次失败，因此最慢大约需要 1 秒。播放中的拔卡由文件读取错误触发。重新插卡后，等待界面每 700 ms 尝试一次初始化。

---

<a id="developer-reference"></a>

## 🧰 开发者参考

下面这些内容主要面向格式分析、屏幕移植和二次开发。默认收起，不影响第一次阅读；需要时点击标题即可展开。

<details>
<summary><strong>📦 OVID 文件格式</strong> — 16 字节文件头、页主序与 CRC</summary>

当前固件使用 OVID v2。文件以固定的 16 字节小端序文件头开始：

| 偏移 | 长度 | 字段 | 要求 |
|---:|---:|---|---|
| 0 | 4 | `magic` | ASCII `OVID` |
| 4 | 1 | `width` | 1–255，不能大于 `OLED_WIDTH` |
| 5 | 1 | `height` | 1–255，可不是 8 的倍数，不能大于 `OLED_HEIGHT` |
| 6 | 1 | `version` | 固定为 2 |
| 7 | 1 | `flags` | bit0 表示逐帧 CRC32 |
| 8 | 4 | `frame_count` | 帧数，必须大于 0 |
| 12 | 2 | `fps` | 1–120 |
| 14 | 2 | `header_crc16` | 前 14 字节的 CRC16-CCITT |

单帧字节数为：

```text
frame_bytes = ceil(height / 8) × width
```

画面按 OLED 页主序保存：先写第 0 页的 `width` 列，再写第 1 页。视频高度不必正好是 8 的倍数，固件会屏蔽最后一页的无效位。每帧后追加 4 字节小端 CRC32；校验失败时保持上一帧，并继续尝试下一帧。

完整文件长度必须严格满足：

```text
file_size = 16 + frame_count × (frame_bytes + 4)
```

</details>

<details>
<summary><strong>🖥️ 屏幕适配与 I2C</strong> — 尺寸宏、控制器与 1.4 MHz 说明</summary>

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

</details>

<details>
<summary><strong>🗂️ 项目结构</strong> — 固件、驱动、工具与配置目录</summary>

```text
.
├── STM32F103/               # 当前可用的 STM32F103 固件工程
│   ├── .settings/           # STM32 扩展的工具 bundle 清单
│   ├── .vscode/             # 扩展推荐、clangd 和 ST-Link 配置
│   ├── CMakeLists.txt / CMakePresets.json
│   ├── SD_Card_OVID_Player.ioc
│   ├── Core/                # 主程序、SD、FatFs、OLED、UI 与播放器
│   ├── Drivers/             # STM32 HAL 与 CMSIS
│   └── cmake/               # CubeMX CMake 和 Arm GCC 工具链
├── ESP32/                    # 后续 ESP32 移植的空目录
├── docs/images/             # 预留的实机图片与 UI 动图位置
├── tools/
│   ├── h2bin.py             # OVID 生成与校验
│   ├── merge_img2lcd.py     # 合并 Img2Lcd 单帧 C 数组
│   ├── test_h2bin.py        # OVID 工具回归测试
│   └── test_merge_img2lcd.py
└── SD_Card_OVID_Player.code-workspace
```

`STM32F103/Core/隐藏关卡/` 是仓库中的真实历史目录，工具示例也引用了它，所以这里没有只在文档里把它改成英文。若以后重命名，需要一起更新脚本注释、命令示例和相关路径。

</details>

<details>
<summary><strong>📊 构建占用与验证</strong> — Flash、RAM 与编译矩阵</summary>

下面的数据来自 Arm GNU Toolchain 14.3.1、默认 128×64 和双缓冲配置：

| 构建 | Flash | RAM |
|---|---:|---:|
| Debug (`-Og -g3`) | 60,608 B / 64 KiB（92.48%） | 9,920 B / 20 KiB（48.44%） |
| Release (`-Os -g0`) | 54,020 B / 64 KiB（82.43%） | 9,912 B / 20 KiB（48.40%） |

> [!NOTE]
> Debug 的 Flash 看起来已经很接近 64 KiB，主要是因为它保留了完整诊断路径，并使用更适合调试的优化设置。平时运行建议使用 Release；不过 82.43% 也不算非常宽裕，继续增加字库或大段 UI 文案前仍然要看一次 `arm-none-eabi-size`。

当前已经完成 128×32、128×64、128×128 和 96×64 的 Debug/Release 编译验证，也覆盖了 SSD1306、SH1106 两条控制器分支。128×128 最大矩阵配置占用 11,968 B RAM（58.44%）。转换工具的回归测试包含大帧、FPS 边界、奇数高度、零帧，以及头部 CRC16 和逐帧 CRC32 损坏检测。

30 分钟连续播放、真实热拔插，以及不同 OLED 模块在 1.4 MHz 下的信号完整性仍然属于目标板测试，主机编译不能替代这些结果。

</details>

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>

<a id="contributing"></a>

## 🤝 参与开发与反馈

欢迎针对屏幕适配、SD 兼容性、OVID 工具和 UI 行为提交 [Issue](https://github.com/akasa828/SD_Card_OVID_Player/issues) 或 Pull Request。为了让问题能够复现，提交 Issue 时请尽量附上：

- 使用的 STM32 板卡、OLED 控制器与分辨率；
- SD 卡容量、文件系统和目录结构；
- Debug 或 Release 构建类型，以及修改过的 OLED 宏；
- 复现步骤、屏幕现象和 USART1 串口日志；
- 如果与视频文件有关，附上 `h2bin.py info` 的输出。

提交代码前，请至少完成与修改相关的 Debug/Release 构建。若改动了转换工具，请同时运行：

```bash
python tools/test_h2bin.py
python tools/test_merge_img2lcd.py
```

硬件相关修复无法只靠主机测试证明有效。Pull Request 中应说明使用过的目标板、测试时长，以及是否验证过插拔 SD 卡和重新上电。

<a id="latest-update"></a>

## 📝 最近一次更新

当前公开的固件版本为 **v1.2.0**，使用 OVID v2。固件包含看门狗与 HardFault 记录、长文件名浏览、诊断模式、I2C 自动降速，以及按 16 ms 周期运行的 UI 动画。容量扫描会平滑追赶真实进度，文件列表也包含选择框缓动、文件名滚动和元数据轮播。

完整的版本记录放在 [CHANGELOG.md](CHANGELOG.md)，README 不再重复贴出每个历史修复。

<a id="license"></a>

## 📄 许可证

项目自有代码使用 [MIT License](LICENSE)，版权人为 `riochihao`。

仓库中包含的第三方代码仍遵循各自许可证，主要包括：

- [STM32F1 HAL Driver](STM32F103/Drivers/STM32F1xx_HAL_Driver/LICENSE.txt)
- [CMSIS](STM32F103/Drivers/CMSIS/LICENSE.txt)
- [STM32F1 CMSIS Device](STM32F103/Drivers/CMSIS/Device/ST/STM32F1xx/LICENSE.txt)
- FatFs：许可证说明位于 `STM32F103/Core/fatfs/ff.c`、`ff.h` 和相关源文件头部
