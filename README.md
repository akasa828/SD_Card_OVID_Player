# SD_card_mp4_mode_player

基于 STM32F103C8T6、SPI Micro SD 卡和 SSD1306 类单色 OLED 的离线帧视频播放器。固件从 FatFs 文件系统中浏览 OVID `.BIN` 文件，由三个按键选择视频，按文件头帧率循环播放到 OLED。

> [!IMPORTANT]
> 项目名虽然包含 `mp4`，STM32 **不直接解码 MP4**。MP4、GIF、PNG/JPG 图片序列或 C 取模数组需先在电脑上转换为 OVID `.BIN`，再复制到 SD 卡。工具默认生成带 CRC 的 OVID v2，固件仍兼容 v1。

## 功能

- SPI1 驱动 Micro SD，FatFs 读取 FAT12、FAT16、FAT32 文件系统。
- 完整启动状态机：等待插卡 → 初始化 → 容量分析 → 三张信息页 → 文件列表 → 播放。
- 使用 FatFs `f_getfree()` 强制扫描 FAT 获取准确剩余容量，不读取可能过期的 FAT32 FSInfo。
- 区分 SD 物理容量与文件系统卷容量，并显示文件系统类型、卷总量、剩余量和已用比例。
- 优先扫描 `/function` 中的 `.BIN`；该目录不存在或无 `.BIN` 时回退到根目录。
- PB1 / PB10 / PB11 三按键浏览、选择和退出播放。
- 严格校验 OVID magic、宽高、帧数、帧率和文件总长度。
- `1–120 FPS` 按文件头播放，使用余数累计消除整数毫秒截断造成的长期速度漂移。
- OLED 双缓冲 + I2C DMA；整屏帧直接读入后台显存，小尺寸帧按页居中合成。
- 屏幕尺寸、显存容量、菜单行数和软件滚动均由 OLED 宏推导，不依赖 128×64、1024 B 或 2 的幂宽度。
- 支持非页对齐的视频高度；末页无效位会被屏蔽。
- 信息页和文件列表每 500 ms 在线探测，连续两次失败判定拔卡；播放中读失败也会统一卸载并返回等待插卡界面。
- 统一的标题栏、卡片、页码点、进度条、动画弹窗、空文件页和滑动转场。
- USART1 TX 输出 SD 卡、挂载、播放器和致命错误诊断。
- OVID v2 使用头部 CRC16 和逐帧 CRC32；坏帧会保持上一帧并继续播放。
- 约 8 秒独立看门狗、跨复位 HardFault 现场记录，以及开机按住上下键进入的三页诊断界面。
- 异步 1200 ms 弹窗、按键提前关闭、文件列表长按加速、排序、选中位置记忆和视频元数据显示。
- FatFs 支持最长 63 字符的 ASCII/西文长文件名；容量扫描可按确认键跳过并以 `Free: N/A` 快速启动。
- SSD1306/SH1106 控制器配置；I2C 连续故障时自动从 1.4 MHz 降至 1 MHz、800 kHz、400 kHz。

## 硬件要求

- STM32F103C8T6 最小系统板（本工程链接脚本按 64 KiB Flash / 20 KiB RAM）。
- SSD1306 或 SH1106 I2C 单色 OLED。
- SPI 接口 Micro SD 卡模块，使用 3.3 V 逻辑电平。
- 三个常开按键。
- 可选 3.3 V TTL 串口模块，用于查看 115200 8N1 诊断信息。

### 接线表

| 功能 | STM32 引脚 | 连接到外设 | 说明 |
|---|---:|---|---|
| SPI1 SCK | PA5 | SD SCK/CLK | SPI mode 0 |
| SPI1 MISO | PA6 | SD MISO/DO | SD → MCU |
| SPI1 MOSI | PA7 | SD MOSI/DI | MCU → SD |
| SD CS | PB0 | SD CS | 低电平选中 |
| I2C1 SCL | PB6 | OLED SCL | 开漏，需上拉 |
| I2C1 SDA | PB7 | OLED SDA | 开漏，需上拉 |
| 上键 | PB1 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| 下键 | PB10 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| 确认键 | PB11 | 按键另一端接 GND | 内部上拉，下降沿 EXTI |
| USART1 TX | PA9 | USB-TTL RX | 可选，115200 8N1，仅发送 |
| 共地 | GND | SD/OLED/按键/串口 GND | 必须共地 |
| 供电 | 3.3 V | SD/OLED VCC | 确认模块的电压与电平要求 |

## 软件架构与启动流程

1. HAL 初始化时钟、GPIO、DMA、I2C1 和 SPI1，OLED 与 USART1 TX 随后就绪。
2. 约 60 FPS 绘制等待插卡动画，每 700 ms 尝试一次 SD 初始化。
3. SD 驱动以低速完成握手、读取 CSD/CID，再切换到高速 SPI。
4. FatFs 挂载卷；`f_getfree()` 扫描 FAT，计算准确剩余容量；扫描时可按确认键跳过。
5. 优先扫描 `/function`，其中没有 `.BIN` 时回退根目录。
6. 依次显示 `STORAGE`、`CARD`、`IDENTITY` 三张信息页，每页总时长固定为 3000 ms。
7. 滑动进入文件列表，由用户选择文件，不自动播放。
8. 校验 OVID v1/v2 文件头和总长度；v2 还校验头部 CRC16 与逐帧 CRC32，再按头部 FPS 循环播放。
9. 退出播放返回列表；拔卡或磁盘读取失败则关闭文件、卸载 FatFs、清状态并返回等待插卡动画。

### 三张卡信息页

每张信息页的 3000 ms 包含完整转场：0–300 ms 从右侧滑入并扫光揭示，300–2700 ms 稳定显示，2700–3000 ms 向左退出。

| 页面 | 内容 |
|---|---|
| `STORAGE` | FAT12/FAT16/FAT32 类型、卷总容量、剩余容量、已用比例进度条 |
| `CARD` | SD 类型、物理容量、寻址模式、块数和实际 SPI 时钟 |
| `IDENTITY` | MID/OID、产品名、版本、序列号和生产日期 |

128×64 使用完整布局；128×32 会压缩字体和行距。所有坐标都从 `OLED_WIDTH`、`OLED_HEIGHT` 计算。

## 构建固件

### 环境

- CMake 3.22 或更高版本。
- Ninja。
- Arm GNU Toolchain（`arm-none-eabi-gcc/g++/size`）。
- Python 3（仅转换工具需要）。

先确保 Arm GNU Toolchain 的 `bin` 目录已加入 `PATH`，然后在仓库根目录执行。Debug 使用 `-Og -g3`，在保留调试信息的同时确保固件可装入 64 KiB Flash：

```bash
# Debug
cmake --preset Debug
cmake --build --preset Debug

# Release
cmake --preset Release
cmake --build --preset Release
```

产物位置：

- Debug：`build/Debug/SD_card_mp4_mode_player.elf`
- Release：`build/Release/SD_card_mp4_mode_player.elf`

如需在 CI 中做屏幕尺寸或控制器验证，可传递 `-DOLED_WIDTH_OVERRIDE=<W> -DOLED_HEIGHT_OVERRIDE=<H>`、`-DOLED_CONTROLLER_OVERRIDE=0|1`、`-DOLED_COLUMN_OFFSET_OVERRIDE=<N>` 和 `-DOLED_I2C_CLOCK_OVERRIDE=<Hz>`。

## SD 卡准备

使用 FAT12、FAT16 或 FAT32，不支持 exFAT、NTFS。FatFs 已开启最长 63 字符 LFN；OLED 只有 ASCII 字库，推荐使用 ASCII/西文 `.BIN` 文件名。超长名称会在列表中安全裁剪显示。

```text
SD 卡根目录/
├── function/          # 有 .BIN 时优先使用
│   ├── DEMO01.BIN
│   └── DEMO02.BIN
└── ROOTVID.BIN       # /function 无 .BIN 时才扫描根目录
```

固件不会自动创建 `/function`。

首次插卡的剩余容量分析可能持续数秒，尤其是大容量或碎片较多的卷。这是 `FF_FS_NOFSINFO=1` 下对 FAT 的实际扫描。扫描期间显示实时进度、活动光点和 `OK: SKIP`；按确认键可立即跳过并以 `Free: N/A` 进入文件列表。`100%` 只会在 `f_getfree()` 真正返回后显示。

## 生成 OVID 视频

工具位于 `tools/h2bin.py`。图片转换需要 Pillow：

```bash
python -m pip install Pillow
```

### 从图片目录或 GIF 生成

```bash
# 图片目录会按文件名中的数字自然排序；GIF 会展开为多帧
python tools/h2bin.py from-images frames/ DEMO01.BIN -W 128 -H 64 --fps 15

# 反色并调整二值化阈值
python tools/h2bin.py from-images animation.gif DEMO02.BIN -W 128 -H 32 --fps 30 --threshold 140 --invert

# 如需兼容旧固件，显式生成 OVID v1
python tools/h2bin.py from-images frames/ LEGACY.BIN -W 128 -H 64 --fps 15 --v1
```

### 从 C 头文件取模数组生成

```bash
python tools/h2bin.py from-header "Core/隐藏关卡/bad apple.h" BADAPPLE.BIN \
  -W 128 -H 64 --fps 15 --match "^BMP"
```

工具会过滤出长度正好等于 `ceil(height/8) × width` 的数组。默认按数组名中数字自然排序；可用 `--file-order`保留原文件顺序。

### 检查生成的文件

```bash
python tools/h2bin.py info BADAPPLE.BIN
```

`from-images`、`from-header` 和 `info` 都会报告版本、单帧字节数和最低屏幕宏。`info` 对 v2 会检查头部 CRC16 和所有帧 CRC32。

## 按键操作

| 按键 | 文件列表 | 播放中 |
|---|---|---|
| PB1 上 | 上一个文件；长按连续滚动并逐级加速 | 无操作 |
| PB10 下 | 下一个文件；长按连续滚动并逐级加速 | 无操作 |
| PB11 确认 | 打开并播放选中文件 | 退出播放、返回列表 |

三键使用下降沿中断和约 150 ms 软件去抖。

开机时同时按住上键和下键进入诊断模式。诊断页显示固件/复位原因、Flash/RAM/栈余量、按键、SD/SPI、OLED DMA、I2C 速率与错误计数、最近一次 HardFault 的 PC/LR/CFSR。第二页按确认会执行“保存原块 → 写入 → 读回 → 校验 → 恢复”的 SD 自检；其他页面按确认退出。自检会恢复原数据，但仍不应在供电不稳定时执行。

卡信息展示结束后只进入文件列表，不会自动播放第一个文件。列表无文件时显示动画空状态并周期重扫；将合法 `.BIN` 放入当前卷后可被自动发现。

## OVID v1 / v2 文件格式

文件头固定为 16 字节，多字节数值使用小端序。

| 偏移 | 长度 | 字段 | 要求 |
|---:|---:|---|---|
| 0 | 4 | `magic` | ASCII `OVID` |
| 4 | 1 | `width` | 视频宽，1–255，且不大于 `OLED_WIDTH` |
| 5 | 1 | `height` | 视频高，1–255，可不是 8 的倍数，不大于 `OLED_HEIGHT` |
| 6 | 1 | `version` | v1 为 0；v2 为 2 |
| 7 | 1 | `flags` | v1 为 0；v2 bit0 表示逐帧 CRC32 |
| 8 | 4 | `frame_count` | 帧数，必须大于 0 |
| 12 | 2 | `fps` | 帧率，1–120 |
| 14 | 2 | `header_crc16` | v1 为 0；v2 为前 14 字节 CRC16-CCITT |

每帧大小：

```text
frame_bytes = ceil(height / 8) × width
```

帧数据为 OLED 页主序：先存第 0 页的 `width` 列，再存第 1 页。v2 在每帧数据后附加 4 字节小端 CRC32；发现坏帧时固件不刷新 OLED，保持上一帧并继续读取下一帧。

固件还要求：

```text
v1_file_size = 16 + frame_count × frame_bytes
v2_file_size = 16 + frame_count × (frame_bytes + 4)
```

较旧的 `fps=0` 文件不再合法，请重新转换。

## 适配其他屏幕尺寸

修改 `Core/OLED/oled.hpp` 中的两个默认宏即可：

```c
#define OLED_WIDTH  128
#define OLED_HEIGHT 64
```

控制器、列偏移和默认镜像也在同一文件配置：

```c
#define OLED_CONTROLLER OLED_CONTROLLER_SSD1306  // 或 OLED_CONTROLLER_SH1106
#define OLED_COLUMN_OFFSET 0                     // 常见 SH1106 模组为 2
#define OLED_DEFAULT_H_FLIP 1
#define OLED_DEFAULT_V_FLIP 1
```

其他容量宏会自动推导：

```text
OLED_PAGES     = OLED_HEIGHT / 8
OLED_GRAM_SIZE = OLED_PAGES × OLED_WIDTH
```

合法宏范围：

- `OLED_WIDTH`：1–255。
- `OLED_HEIGHT`：8–255 之间且必须为 8 的倍数，因此实际最大为 248。
- OVID 视频本身的高度可为奇数，但不能超过屏幕宏。
- 单帧可超过 1024 B，只要不超过当前 `OLED_GRAM_SIZE`。

这些是软件格式与编译期范围，不代表任意值都被实际显示控制器支持。控制器的 GDDRAM、列/页地址范围和模组物理像素数仍是硬限制；STM32F103C8T6 仅有 20 KiB RAM，双缓冲、FatFs LFN 和 SD 自检缓冲都会占用 RAM。

## I2C 1.4 MHz 说明

默认 `1,399,999 Hz` 是现有硬件实测配置，不是通用保证值。驱动统计 NACK/DMA 超时，连续三次恢复后自动依次降到 1 MHz、800 kHz、400 kHz，并在诊断页显示当前速率与累计错误。也可用 `I2C1_INITIAL_CLOCK_HZ` 或 CMake 的 `OLED_I2C_CLOCK_OVERRIDE` 从较低速率启动。

## 常见问题

| 现象 | 排查方向 |
|---|---|
| `NO .BIN FILES` | 确认扩展名为 `.BIN`，并检查 `/function` 或根目录；页面会周期重扫。 |
| `MOUNT FAILED` / 一直等待插卡 | 确认 3.3 V、共地、PA5/6/7 和 PB0 接线，并通过 PA9 查看 FatFs 错误码。 |
| `UNSUPPORTED FS` | 当前卷不是 FAT12/FAT16/FAT32；在电脑上备份数据后重新格式化为 FAT/FAT32。该错误页会保持到拔卡。 |
| `BAD OVID` | 文件不是 OVID v1/v2 或头部已损坏；用 `h2bin.py info` 检查。 |
| 串口出现 `CRC mismatch` | v2 某帧内容损坏；固件会保持上一帧继续播放，建议重新复制文件或检查 SD 卡。 |
| `INVALID OVID` | 检查帧数、`1–120 FPS`、文件是否截断或多了尾随数据。 |
| `FRAME TOO BIG` | 视频宽或高超过当前 OLED 宏；重新转换或更换屏幕配置。 |
| `Free: N/A` | `f_getfree()` 返回了非介质错误；查看串口诊断。若文件浏览仍正常，播放器会继续工作。 |
| 单帧超过 1024 B | v1.0.1 允许，但须不超过 `OLED_GRAM_SIZE`，并确保 RAM 余量足够。 |
| OLED 花屏/闪烁 | 缩短 I2C 线、检查上拉和电源；固件会自动降速，也可直接降低初始 I2C 时钟。 |
| 启动显示 `FAULT RECOVERED` | 上次发生 HardFault；通过 PA9 串口或开机按住上下键查看 PC/LR/CFSR。 |
| 启动显示 `WATCHDOG RESET` | 上次运行超过约 8 秒未喂狗，系统已自动复位；检查串口阶段日志和诊断计数。 |
| 信息页/列表中拔卡 | 最多约 1 秒（500 ms × 连续两次）确认后卸载卷，播放拔卡则由文件读取错误触发同一恢复路径。 |
| 重新插卡仍失败 | 等待 700 ms 周期重试，同时检查串口的 SD 初始化与 FatFs 错误码。 |

## 项目结构

```text
.
├── CMakeLists.txt / CMakePresets.json
├── SD_card_mp4_mode_player.ioc
├── Core/
│   ├── Src/                 # CubeMX 生成的主程序与外设初始化
│   ├── Inc/
│   ├── Micro_SD/            # SPI SD 驱动与串口诊断
│   ├── fatfs/              # FatFs 与 diskio 适配
│   ├── function/           # UI、浏览器、播放器、看门狗与故障诊断
│   ├── OLED/               # SSD1306/SH1106 绘图、DMA、双缓冲与测试
│   └── 隐藏关卡/           # 大型取模素材/示例
├── Drivers/                 # STM32 HAL/CMSIS 第三方代码
├── cmake/                  # STM32CubeMX CMake 与 Arm GCC 工具链
└── tools/
    ├── h2bin.py             # OVID 生成/校验工具
    └── test_h2bin.py        # 无 Pillow 快速回归测试
```

## 构建占用与验证

以 Arm GNU Toolchain 14.3.1、默认 128×64 和双缓冲配置编译：

| 构建 | Flash | RAM |
|---|---:|---:|
| Debug (`-Og -g3`) | 59,392 B / 64 KiB（90.63%） | 9,864 B / 20 KiB（48.16%） |
| Release (`-Os -g0`) | 53,008 B / 64 KiB（80.88%） | 9,864 B / 20 KiB（48.16%） |

已完成的自动化验证：

- Debug 与 Release 均已编译：128×32、128×64、128×128 和非 2 次幂宽度 96×64。
- 128×128 最大矩阵配置占用 RAM 11,912 B（58.16%），仍可链接到 STM32F103C8T6 的 20 KiB RAM。
- SSD1306 与 SH1106 的 Debug/Release 控制器分支均已编译。
- `h2bin.py` 6 项回归：大帧、FPS 边界、奇数高度、零帧、v1 兼容和 v2 坏帧 CRC 检出。

30 分钟连续播放、真实拔卡/重插、不同 OLED 模块在 1.4 MHz 下的信号完整性属于目标板硬件验收项，不能由主机编译测试代替。

## 更新日志

### v1.2.0 可靠性、OVID v2 与诊断更新（2026-08-19）

- 小方框弹窗改为异步状态，可覆盖后续 UI 渲染；确认键可提前关闭。
- 检卡成功和文件载入提示在进入阻塞式存储操作前按约 60 FPS 完整播放，避免弹窗只显示首帧；弹窗、信息页统一使用 300 ms 横向扩张反显。
- 反显区域像拔卡动画一样从左侧扩张并保留，扫过文字后整页保持白底黑字，不再使用会滑出屏幕的窄光带。
- 文件列表底部将大帧数压缩为 `K/M/G` 显示，并将元数据分隔线上移 1 像素，避免长数字拥挤。
- `Loading / 文件名` 与 `Library / Playback stopped` 恢复为小矩形展开/收起动画；其他状态页继续使用横向扩张反显。
- UI 英文改用正常标题和句子大小写，`SD`、`FAT`、`OVID`、`SPI`、`I2C` 等技术缩写继续保留大写。
- 优化 128×64 容量页间距，分离进度条、`OK: SKIP` 和活动光点；FAT 与目录扫描动画刷新间隔缩短至 33 ms。
- 加入约 8 秒 IWDG，看门狗复位后显示恢复提示。
- Debug 构建在调试器暂停内核时冻结 IWDG，断点调试不会被误判为卡死；Release 保持独立运行。
- HardFault 自动保存寄存器、PC/LR、CFSR/HFSR、应用状态和当前文件到 `.noinit` SRAM，重启后通过串口和诊断页报告。
- 容量扫描显示 `OK: SKIP`，可跳过完整 FAT 扫描并以 `Free: N/A` 快速进入文件列表。
- 新增 OVID v2：16 字节兼容头、头部 CRC16、逐帧 CRC32；坏帧保持上一帧继续播放，v1 文件仍可使用。
- `h2bin.py` 默认生成 v2，新增 `--v1`，`info` 可逐帧校验 CRC；回归测试扩展至 6 项。
- 文件浏览支持最长 63 字符 LFN、大小写无关排序、长按加速、记忆选中位置，并显示分辨率/FPS/帧数/OVID 版本。
- 增加开机“上+下”诊断模式，显示复位、内存、按键、SD/SPI、OLED DMA、I2C 和故障记录，并可执行可恢复的 SD 读写自检。
- OLED 控制器配置支持 SSD1306/SH1106、列偏移和默认镜像；CMake 增加对应覆盖参数。
- I2C 连续故障后自动从 1.4 MHz 逐级降至 400 kHz，诊断页显示当前速率、错误和超时计数。

### v1.1.0 完整 UI 与存储信息更新（2026-08-19）

- 串联等待插卡、初始化/容量扫描、三张卡信息页、文件浏览和播放流程；信息结束后进入列表，不自动播放。
- 改用 FatFs `f_getfree()` 计算剩余容量，`FF_FS_NOFSINFO=1` 强制扫描 FAT，支持 FAT12/FAT16/FAT32 类型显示。
- 容量扫描增加实时百分比与活动指示，128×64 使用简洁的 `FREE SPACE / SCANNING FAT` 布局。
- 修复容量达到 100% 后停留的问题：完成帧移到 FatFs 返回之后，并为后续目录扫描增加独立动画和串口阶段日志。
- 为 FatFs 目录内层增加 5 秒/8192 项保护，损坏的循环目录链不再永久卡住；调试串口发送同样加入超时保护。
- 修复目录扫描结束后停在 `Preparing UI` 的 HardFault：避免在 Newlib Nano `printf` 中使用会破坏后续可变参数读取的 `%llu`，容量日志改用 32 位 MiB，文件长度仍保留 64 位严格校验。
- 区分 SD 物理容量和文件系统卷容量，增加剩余容量、已用比例、寻址方式、块数、实际 SPI 时钟及 CID 信息展示。
- 三张信息页每页总时长固定为 3 秒，加入滑入、扫光、滑出、页码点、卡片和容量进度条。
- 增加统一动画弹窗、美化文件列表、空文件动画页、错误页和返回列表提示。
- 所有小方框动画弹窗统一显示 1200 ms，确保状态和错误信息有足够阅读时间。
- 信息页及文件列表每 500 ms 探测一次卡状态，连续两次失败统一卸载 FatFs 并回到等待插卡界面。
- 删除驱动层旧的独立 SD UI，以及自行解析 MBR/VBR/FSInfo 和扫描 FAT32 的容量实现。
- 新增只读 `SD_Card_IsPresent_Card()` CMD58/OCR 在线检测接口，并从 `main()` 移除提前初始化 SD 的调试调用。
- 重新完成 128×32、128×64、128×128、96×64 的 Debug/Release 构建矩阵并更新资源占用。

### v1.0.1 宏适配与可靠性更新（2026-08-19）

- 屏幕尺寸和帧容量改为完全由 OLED 宏推导。
- 支持单帧超过 1024 B，不再额外分配整帧播放缓冲。
- 通用化软件滚动、菜单布局、测试坐标和显存索引。
- 增加严格 OVID 校验和 `1–120 FPS` 播放规则。
- 改为 `/function` 优先、根目录回退，不再自动创建目录。
- 改进热拔插、FatFs 错误恢复、OLED 双缓冲覆盖时序和 DMA/I2C 超时恢复。
- 更新转换工具，并首次补充完整的 GitHub README。

### v1.0.0 初始版本

- STM32F103、SPI SD、FatFs 与 SSD1306 OLED 双缓冲。
- 三按键 `.BIN` 文件浏览与 OVID 循环播放。
- SD 卡信息、CRC、自检、串口诊断和图片/头文件转换工具。
- 屏幕和播放器主要按 128×64、1024 B 固定配置实现。
- 扫描根目录，同时存在未实际使用的 `/function` 创建逻辑。
- 视频头校验、拔卡恢复和 OLED DMA 超时处理较基础。

## 许可证

项目根目录当前没有为用户业务代码提供统一的根许可证，本 README 不虚构授权条款。STM32 HAL、CMSIS 等第三方代码仍分别遵循其目录中的许可证：

- `Drivers/STM32F1xx_HAL_Driver/LICENSE.txt`
- `Drivers/CMSIS/LICENSE.txt`
- `Drivers/CMSIS/Device/ST/STM32F1xx/LICENSE.txt`

如需对外分发整个项目，请先由项目维护者补充适用于自有代码和素材的根许可证。
