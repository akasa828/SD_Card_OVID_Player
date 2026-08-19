# SD Card OVID Player

这是一个给 STM32F103C8T6 做的离线 OLED 视频播放器。视频文件放在 Micro SD 卡里，单片机负责浏览文件、检查格式，再按照文件中记录的帧率把画面送到 SSD1306 或 SH1106 单色屏上。整个过程只需要三个按键，不依赖电脑或网络。

项目最初是按 128×64 屏幕写的，后来才逐步把尺寸、显存、菜单布局和播放缓冲改成由宏定义推导。现在换屏时通常只需要调整 `OLED_WIDTH` 和 `OLED_HEIGHT`，但最终能不能显示，仍然取决于控制器的寻址范围和 STM32F103 的 RAM。

> [!IMPORTANT]
> 这里有一个很容易误解的地方：项目名里虽然有 `mp4`，STM32 **不会直接解码 MP4**。固件真正读取的是 OVID（可以理解为 OLED Video）`.BIN` 文件，也就是为单色 OLED 准备的页主序帧数据。图片、GIF、C 取模数组，或者从 MP4 中导出的图片序列，都要先在电脑上转换。

## 从哪里开始

- [先跑起来](#先跑起来)
- [硬件与接线](#硬件与接线)
- [构建固件](#构建固件)
- [准备 SD 卡](#准备-sd-卡)
- [生成 OVID 文件](#生成-ovid-文件)
- [按键和启动流程](#按键和启动流程)
- [OVID 文件格式](#ovid-文件格式)
- [适配其他屏幕](#适配其他屏幕)
- [诊断与常见问题](#诊断与常见问题)

## 先跑起来

如果你只是想先看到它工作，不必一开始就研究 FatFs、DMA 和 OVID 的每个字段。按下面的顺序做就可以。

1. 按[接线表](#接线表)连接 OLED、Micro SD 模块和三个按键。SD 模块、OLED 与单片机必须共地，并确认模块使用 3.3 V 逻辑电平。
2. 安装 CMake、Ninja 和 Arm GNU Toolchain，在项目根目录构建 Release 固件：

   ```bash
   cmake --preset Release
   cmake --build --preset Release
   ```

   生成的固件位于 `build/Release/SD_card_mp4_mode_player.elf`，用你习惯的 ST-Link 工具烧录即可。

3. 把 SD 卡格式化为 FAT 或 FAT32，并在根目录新建 `function` 文件夹。
4. 用 `tools/h2bin.py` 把图片目录或 GIF 转成 `.BIN`。例如：

   ```bash
   python -m pip install Pillow
   python tools/h2bin.py from-images frames/ DEMO.BIN -W 128 -H 64 --fps 15
   ```

5. 将 `DEMO.BIN` 放进 `/function`，插卡上电。三张卡信息页显示完以后，用上下键选文件，按确认键播放；播放中再按一次确认键即可返回列表。

仓库没有附带预编译固件或现成演示视频，所以屏幕尺寸、烧录方式和素材仍需要按自己的硬件准备。

## 它现在能做什么

播放器会先等待 SD 卡，挂载成功后计算卷容量、扫描视频文件，并依次显示存储、卡片和身份信息。文件优先从 `/function` 读取；这个目录不存在或没有 `.BIN` 时，才回退到根目录。

播放端兼容 OVID v1 和 v2。v2 增加了文件头 CRC16 与逐帧 CRC32，一帧损坏时不会把错误画面刷到 OLED，而是保留上一帧继续读取。帧率范围是 1–120 FPS，计时会累计毫秒除法的余数，长时间播放不会因为整数截断越跑越慢。

UI 使用 OLED 双缓冲和 I2C DMA。文件列表支持长按加速、选中位置记忆、长文件名往返滚动，以及分辨率、帧率、帧数和格式版本轮播。正常的 128×64、1.4 MHz I2C 环境下，动画按 16 ms 周期刷新；遇到 SD 超时或 I2C/DMA 故障恢复时，流畅度会暂时让位给可靠性。

拔卡也不需要复位。信息页和文件列表每 500 ms 探测一次卡状态，连续两次失败后会卸载 FatFs 并回到等待插卡界面。播放中发生读错误时走的是同一套恢复流程。

## 硬件与接线

当前工程使用以下硬件：

- STM32F103C8T6 最小系统板；链接脚本按 64 KiB Flash、20 KiB RAM 配置。
- SSD1306 或 SH1106 I2C 单色 OLED。
- SPI 接口的 Micro SD 卡模块，使用 3.3 V 逻辑电平。
- 三个常开按键。
- 可选的 3.3 V USB-TTL 模块，用来看串口诊断。

### 接线表

| 功能 | STM32 引脚 | 外设端 | 说明 |
|---|---:|---|---|
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

## 构建固件

需要 CMake 3.22 或更高版本、Ninja 和 Arm GNU Toolchain。先把 `arm-none-eabi-gcc`、`arm-none-eabi-g++` 和 `arm-none-eabi-size` 所在的 `bin` 目录加入 `PATH`，然后在仓库根目录运行：

```bash
# Debug
cmake --preset Debug
cmake --build --preset Debug

# Release
cmake --preset Release
cmake --build --preset Release
```

对应产物是：

- `build/Debug/SD_card_mp4_mode_player.elf`
- `build/Release/SD_card_mp4_mode_player.elf`

Debug 使用 `-Og -g3`，适合断点和故障排查；Release 使用 `-Os -g0`，更适合平时烧录。需要做屏幕或控制器编译验证时，可以给 CMake 传入以下覆盖项：

```text
-DOLED_WIDTH_OVERRIDE=<W>
-DOLED_HEIGHT_OVERRIDE=<H>
-DOLED_CONTROLLER_OVERRIDE=0|1
-DOLED_COLUMN_OFFSET_OVERRIDE=<N>
-DOLED_I2C_CLOCK_OVERRIDE=<Hz>
```

## 准备 SD 卡

固件支持 FAT12、FAT16 和 FAT32，不支持 exFAT 或 NTFS。FatFs 已开启最长 63 字符的长文件名，不过 OLED 字库只包含 ASCII 字符，文件名最好仍使用 ASCII 或西文字符。

推荐的目录结构如下：

```text
SD 卡根目录/
├── function/          # 这里有 .BIN 时优先使用
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN        # /function 没有 .BIN 时才会扫描到
```

固件不会自动创建 `/function`。首次插卡时，`f_getfree()` 会实际扫描 FAT 来计算剩余空间，不相信可能已经过期的 FAT32 FSInfo，所以大容量或碎片较多的卡可能需要等几秒。进度条用千分比定点值平滑追赶真实扫描进度，活动点仍会持续移动，不会只按整数百分比一格一格跳。

如果不想等待，可以在扫描页按确认键跳过。播放器会显示 `Free: N/A`，但仍然继续扫描文件并进入列表；`100%` 只会在 `f_getfree()` 真正返回后出现。

## 生成 OVID 文件

转换工具是 `tools/h2bin.py`。Python 的 `argparse`、`struct` 等模块都来自标准库；唯一需要另外安装的 Python 包是 Pillow：

```bash
python -m pip install Pillow
```

### 图片目录或 GIF

```bash
# 图片目录按文件名中的数字自然排序；GIF 会自动展开为多帧
python tools/h2bin.py from-images frames/ DEMO01.BIN -W 128 -H 64 --fps 15

# 反色，并修改二值化阈值
python tools/h2bin.py from-images animation.gif DEMO02.BIN \
  -W 128 -H 32 --fps 30 --threshold 140 --invert

# 需要兼容旧固件时，可以显式生成 OVID v1
python tools/h2bin.py from-images frames/ LEGACY.BIN \
  -W 128 -H 64 --fps 15 --v1
```

### MP4 或其他视频

`h2bin.py` 不读取 MP4。如果原素材是视频，可以先用 FFmpeg 导出帧，再转换成 OVID。FFmpeg 只是这一环节的可选外部工具，不是固件或 Python 脚本的依赖。

```bash
mkdir frames
ffmpeg -i input.mp4 -vf "fps=15,scale=128:64" frames/%06d.png
python tools/h2bin.py from-images frames/ OUTPUT.BIN -W 128 -H 64 --fps 15
```

### C 头文件取模数组

```bash
python tools/h2bin.py from-header "Core/隐藏关卡/bad apple.h" BADAPPLE.BIN \
  -W 128 -H 64 --fps 15 --match "^BMP"
```

脚本只保留长度正好等于 `ceil(height/8) × width` 的数组。默认按数组名中的数字自然排序；如需保留头文件里的出现顺序，可以加 `--file-order`。

生成后最好再检查一次：

```bash
python tools/h2bin.py info BADAPPLE.BIN
```

三个子命令都会报告格式版本、单帧字节数和最低屏幕宏。`info` 还会检查 v2 的头部 CRC16 和所有帧 CRC32。

## 按键和启动流程

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

## OVID 文件格式

OVID v1 和 v2 都使用固定的 16 字节小端序文件头：

| 偏移 | 长度 | 字段 | 要求 |
|---:|---:|---|---|
| 0 | 4 | `magic` | ASCII `OVID` |
| 4 | 1 | `width` | 1–255，不能大于 `OLED_WIDTH` |
| 5 | 1 | `height` | 1–255，可不是 8 的倍数，不能大于 `OLED_HEIGHT` |
| 6 | 1 | `version` | v1 为 0，v2 为 2 |
| 7 | 1 | `flags` | v1 为 0；v2 bit0 表示逐帧 CRC32 |
| 8 | 4 | `frame_count` | 帧数，必须大于 0 |
| 12 | 2 | `fps` | 1–120 |
| 14 | 2 | `header_crc16` | v1 为 0；v2 为前 14 字节的 CRC16-CCITT |

单帧字节数为：

```text
frame_bytes = ceil(height / 8) × width
```

画面按 OLED 页主序保存：先写第 0 页的 `width` 列，再写第 1 页。视频高度不必正好是 8 的倍数，固件会屏蔽最后一页的无效位。v2 在每帧后追加 4 字节小端 CRC32；校验失败时保持上一帧，并继续尝试下一帧。

完整文件长度必须严格满足：

```text
v1_file_size = 16 + frame_count × frame_bytes
v2_file_size = 16 + frame_count × (frame_bytes + 4)
```

较早生成的 `fps=0` 文件已经不再合法，需要重新转换。

## 适配其他屏幕

这个项目最初就是按 128×64 写的。如果屏幕控制器兼容，通常只要修改 `Core/OLED/oled.hpp` 中的两个宏：

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

## 关于 1.4 MHz I2C

默认的 `1,399,999 Hz` 是当前硬件上实际使用的配置，不代表每块 OLED、每种上拉电阻和每根连接线都能稳定工作。驱动会统计 NACK 和 DMA 超时，连续三次恢复失败后依次降到 1 MHz、800 kHz 和 400 kHz。

如果一上电就花屏或闪烁，先缩短连线、检查供电和上拉，再考虑降低 `I2C1_INITIAL_CLOCK_HZ`，或在配置 CMake 时传入 `OLED_I2C_CLOCK_OVERRIDE`。比起追求纸面速度，稳定刷新更重要。

## 诊断与常见问题

USART1 TX 会以 115200 8N1 输出 SD 初始化、FatFs、播放器、UI 帧率和故障信息。正常动画期间，串口每秒报告实际 FPS、最长帧间隔和超时帧数。SD 阻塞、DMA/I2C 恢复和自动降速不属于 60 FPS 的硬件验收区间。

开机时同时按住上键和下键可以进入三页诊断界面。这里能看到复位原因、Flash/RAM、栈余量、按键、SD/SPI、OLED DMA、当前 I2C 速率和最近一次 HardFault 的 PC/LR/CFSR。第二页按确认会执行“保存原块 → 写入 → 读回 → 校验 → 恢复”的 SD 自检；虽然原数据会被写回，供电不稳定时仍然不建议运行。

系统还启用了约 8 秒的独立看门狗。Debug 构建在调试器暂停内核时会冻结它，Release 则保持独立运行。HardFault 现场保存在 `.noinit` SRAM，重启后会通过屏幕和串口提示。

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

1.4 MHz 超出了不少模块的常规工作条件。缩短 I2C 线、确认上拉和电源，或者直接降低初始速率。自动降速只能在驱动识别到连续故障后生效，无法修复所有信号完整性问题。

### 拔卡后为什么没有立刻回到等待界面？

信息页和列表每 500 ms 检测一次，并要求连续两次失败，因此最慢大约需要 1 秒。播放中的拔卡由文件读取错误触发。重新插卡后，等待界面每 700 ms 尝试一次初始化。

## 项目结构

```text
.
├── CMakeLists.txt / CMakePresets.json
├── SD_card_mp4_mode_player.ioc
├── Core/
│   ├── Src/                 # CubeMX 主程序与外设初始化
│   ├── Inc/
│   ├── Micro_SD/            # SPI SD 驱动和串口诊断
│   ├── fatfs/               # FatFs 与 diskio 适配
│   ├── function/            # 状态机、UI、播放器和故障诊断
│   ├── OLED/                # 绘图、DMA、双缓冲与控制器适配
│   └── 隐藏关卡/            # 历史取模素材，目前含 bad apple.h
├── Drivers/                 # STM32 HAL 与 CMSIS
├── cmake/                   # CubeMX CMake 和 Arm GCC 工具链
└── tools/
    ├── h2bin.py             # OVID 生成与校验
    └── test_h2bin.py        # 转换工具回归测试
```

`Core/隐藏关卡/` 是仓库中的真实历史目录，工具示例也引用了它，所以这里没有只在文档里把它改成英文。若以后重命名，需要一起更新脚本注释、命令示例和相关路径。

## 构建占用与验证

下面的数据来自 Arm GNU Toolchain 14.3.1、默认 128×64 和双缓冲配置：

| 构建 | Flash | RAM |
|---|---:|---:|
| Debug (`-Og -g3`) | 60,608 B / 64 KiB（92.48%） | 9,920 B / 20 KiB（48.44%） |
| Release (`-Os -g0`) | 54,020 B / 64 KiB（82.43%） | 9,912 B / 20 KiB（48.40%） |

Debug 的 Flash 看起来已经很接近 64 KiB，主要是因为它保留了完整诊断路径，并使用更适合调试的优化设置。平时运行建议使用 Release；不过 82.43% 也不算非常宽裕，继续增加字库或大段 UI 文案前仍然要看一次 `arm-none-eabi-size`。

当前已经完成 128×32、128×64、128×128 和 96×64 的 Debug/Release 编译验证，也覆盖了 SSD1306、SH1106 两条控制器分支。128×128 最大矩阵配置占用 11,968 B RAM（58.44%）。转换工具的回归测试包含大帧、FPS 边界、奇数高度、零帧、v1 兼容和 v2 CRC 损坏检测。

30 分钟连续播放、真实热拔插，以及不同 OLED 模块在 1.4 MHz 下的信号完整性仍然属于目标板测试，主机编译不能替代这些结果。

## 最近一次更新

当前固件版本为 **v1.2.0**。这一版加入 OVID v2、看门狗与 HardFault 记录、长文件名浏览、诊断模式、I2C 自动降速，以及按 16 ms 周期运行的 UI 动画。容量扫描改成平滑追赶真实进度，文件列表也补上了选择框缓动、文件名滚动和元数据轮播。

完整的版本记录放在 [CHANGELOG.md](CHANGELOG.md)，README 不再重复贴出每个历史修复。

## 许可证

项目自有代码使用 [MIT License](LICENSE)，版权人为 `riochihao`。

仓库中包含的第三方代码仍遵循各自许可证，主要包括：

- [STM32F1 HAL Driver](Drivers/STM32F1xx_HAL_Driver/LICENSE.txt)
- [CMSIS](Drivers/CMSIS/LICENSE.txt)
- [STM32F1 CMSIS Device](Drivers/CMSIS/Device/ST/STM32F1xx/LICENSE.txt)
- FatFs：许可证说明位于 `Core/fatfs/ff.c`、`ff.h` 和相关源文件头部
