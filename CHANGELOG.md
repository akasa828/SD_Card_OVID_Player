# 更新日志

这个文件记录固件行为和格式变化。纯文档调整放在 `Unreleased`，不会单独提升固件版本号。

## Unreleased

暂无。

## v1.3.0-beta.2 OVID 转换器修复（2026-08-22）

### OVID Converter

- 新增“跳过开头帧”参数，GUI、命令行、预览和输出统一使用同一帧范围，便于与已有 OVID 文件对齐。
- 宽高、FPS、跳帧、缩放、补边背景、反色和递归目录等画面选项现在会及时刷新预览。
- 修复 Flet 0.86.5 下拉框事件参数不兼容导致应用启动失败的问题。
- 精简转换页面，移除重复说明应用用途的大标题。
- 桌面转换器、Windows 构建参数和 STM32 固件版本统一更新为 `v1.3.0-beta.2`。
- 转换进度改为合并后台帧回调并以约 60 FPS 局部刷新，百分比、帧数和输出大小无需切换页面即可实时显示。
- 进度条使用时间相关的平滑追赶，并在完成弹窗前于 250 ms 内补到 100%；取消、失败和连续任务会停止旧渲染状态。
- 固定阈值调整到分段按钮左侧并成为 GUI、转换库和命令行的默认算法，默认阈值保持 `128`。
- 浅色模式改用明确的 Material 3 配色并立即刷新；无效主题设置会回退到跟随系统，保存新尺寸或 FPS 后会在返回转换页时更新预览。
- 修复向 Flet 0.86.5 的 `Theme` 传入不支持的 `brightness` 参数导致应用启动失败的问题，明暗模式继续由页面主题模式控制。
- 修复自定义字体主题没有明确前景色、导致浅色模式仍显示白色文字的问题；浅色页面、卡片、分隔线和提示文字现在使用固定的 Material 3 颜色角色。

## v1.3.0-beta.1 OVID 转换器预发布（2026-08-22）

### OVID Converter

- 新增 Material 3 桌面转换器，可直接将图片、图片目录、GIF 和常见视频生成 OVID v2 `.BIN`。
- 默认使用 128×64、15 FPS、保持比例完整显示、黑色补边和 Floyd–Steinberg 黑白抖动。
- 支持 `contain`、`cover`、`stretch`、固定阈值、反色、透明区域背景、递归目录和输出覆盖选项。
- 增加 OLED 像素预览、前后帧、预览播放、进度、预计文件大小和后台取消；长视频通过 FFmpeg 逐帧解码，不整段载入内存。
- 修复视频预览结束时 `StopIteration` 进入异步任务造成的错误弹窗，末帧会保留在预览区。
- 预览启用无缝帧切换和单调时钟调度，减少逐帧更新产生的闪烁和节奏不均。
- 固定阈值会实时刷新当前帧，并增加推荐范围提示；Floyd 抖动与固定阈值切换后会立即重绘预览。
- 修复窄窗口底部导航重复和页面索引错位的问题。
- 输出先写入 `.part` 临时文件，成功后原子替换；失败或取消时自动清理。
- 抽取 OVID v2、CRC16 和 CRC32 公共实现，`h2bin.py` 原有命令继续兼容。
- 桌面端内置 Google Sans Flex，并以 Noto Sans SC 补全简体中文字符，固定使用 `zh-CN` 本地化，统一简体中文界面的字形和字重。
- 应用窗口完成初始布局后自动居中；安装版和便携版同时包含字体及其 SIL Open Font License。

### Windows distribution

- 新增 Windows x64 便携 ZIP，包含 Flet/Flutter 运行时、Pillow、imageio-ffmpeg 和 FFmpeg，解压后无需 Python 即可运行。
- 新增 Inno Setup 安装版，提供中英文界面、自定义安装目录、开始菜单、可选桌面快捷方式和卸载入口。
- 新增根目录构建批处理，支持 Python 3.10–3.15；未安装 Inno Setup 时仍可生成 EXE 和便携版 ZIP。
- 未关联通用 `.BIN` 扩展名；用户生成文件和设置不会随卸载删除。
- 当前安装包未签名，README 和 Release 中补充 SmartScreen 提示，并随附件提供统一 `SHA256SUMS.txt` 和第三方许可证说明。

### Firmware and release

- 应用版本同步更新为 `1.3.0-beta.1`，诊断页显示 `FW V1.3.0-b1`。
- Release 工作流拆分为 Ubuntu 固件构建、Windows 转换器构建和统一附件发布三个阶段。
- Release 同时发布 STM32F103C8T6 ELF/BIN、转换器便携版、安装版、示例视频包和统一 SHA-256 校验文件。
- `v1.2.2` 继续作为稳定固件，`v1.2.6` 保留为驱动模块化预发布版；`v1.3.0-beta.1` 作为当前 Latest Release 发布，beta 标识表示转换器仍在继续完善。

### Repository, testing and documentation

- Reorganized the public Git history into focused English Conventional Commits while preserving the file tree of every published version tag.
- Fixed the root VS Code workspace so clangd resolves any installed STM32 GNU tool bundle version dynamically.
- Added bilingual contribution, security, Issue, and Pull Request guidance.
- Added regression coverage for direct image, directory, GIF, and streamed video conversion, page-major packing, cancellation, and atomic output.
- Expanded GitHub Actions to build every supported SSD1306/SH1106 configuration in both Debug and Release and run the complete Python test suite.
- Updated the Chinese and English README with converter downloads and usage; the IrfanView/Img2Lcd workflow remains as an optional advanced guide.

## v1.2.6 驱动模块化预发布（2026-08-21）

> `v1.2.3`、`v1.2.4` 与 `v1.2.5` 未公开发布；本次版本按计划直接使用 `v1.2.6`。

### Firmware and drivers

- 将 OLED 驱动核心改为 `OLED_PortOps` 端口接口，DMA、恢复、计时和诊断不再直接依赖固定 `hi2c1` 或 HAL 全局回调。
- 将 SD SPI 核心改为带 `context` 的 `SD_IO` 接口，不再包含固定 SPI 句柄、PB0 片选、OLED 或 STM32 HAL 类型。
- 新增可配置的 STM32 HAL I2C/SPI 适配层，并由播放器应用显式转发 OLED DMA 事件、绑定 SD 卡与 FatFs 物理盘。
- OLED 保留双缓冲、自适应 I2C、DMA 超时恢复；SD 保留 CRC、容量扫描、热拔插、诊断和可恢复自检行为。
- 新增统一应用版本宏 `1.2.6`，诊断页不再写死旧版 `FW V1.2.1`。

### Reusable drivers

- 新增独立项目 `STM32-HAL-SSD1306-SH1106`，包含平台无关核心、STM32 HAL 适配层、完整 F103 示例与中英文文档。
- 新增独立项目 `STM32-HAL-SPI-SD-FatFs`，包含 SD 协议核心、可绑定 FatFs `diskio`、STM32 HAL 适配层与文件读写示例。
- 播放器继续保留两个驱动的版本化源码副本，并新增来源记录与同步脚本，下载 ZIP 后无需联网获取驱动。
- 三个项目新增 GitHub Actions 编译检查；驱动项目从 `v1.0.0` 开始发布。
- 播放器 Debug 构建保留 `-g3` 调试符号并改用 `-Os`，避免 GNU Arm 13/14 代码尺寸差异导致 64 KiB Flash 溢出。

### Documentation

- 新增完整英文 README，以及 OVID 教程、格式说明、屏幕移植和故障排查的英文文档；中英文页面均提供语言切换入口。
- 优化 README 首屏检索信息、最新 Release 入口、UI 动图说明和可复用模块索引，并统一示例 `.BIN` 文件的下载说明。
- 将 OVID 教程中的本机绝对路径改为可移植的占位路径示例。
- 将 UI 展示动图从 10 FPS 优化为 6 FPS，在保持尺寸、颜色和完整时长的同时减少仓库体积。
- 调整 README 阅读顺序，将 UI、未来计划、特性和快速开始前置，项目初衷原文整体后移；同时修正导航锚点和不存在的测试脚本清单。

### Repository

- 仓库改为多芯片平台结构：现有固件整体迁入 `STM32F103/`，并预留 `ESP32/` 目录。
- 新增根目录 VS Code 多根工作区，可在同一仓库中切换不同芯片工程；STM32 的构建和 ST-Link 配置跟随固件目录保留。
- 忽略仅用于 GitHub Release 的本地 ZIP 归档，避免将发布压缩包误提交到源码树。
- 删除 `STM32F103/` 中迁移后误保留的重复 README，项目说明统一由仓库根目录和 `docs/` 维护。

## v1.2.2 项目说明更新（2026-08-21）

### Documentation

- GitHub Release 新增打包好的示例 `.BIN` 文件，供用户测试正常播放和错误处理功能。
- 补充 README 的“项目初衷”，记录项目从播放 Bad Apple 的想法出发，逐步加入 SD 卡、FatFs、OLED 驱动、文件选择和 UI 的开发过程。
- 说明选择 SD 卡存储视频文件的原因，以及整理一套基于 HAL 库、便于理解和修改的 OLED 驱动这一目标。
- 将 OVID 图文教程、格式说明、屏幕适配和故障排查按原有内容拆分到 `docs/`，README 保留对应文档入口。

### Firmware and UI

- 修复长文件名滚动到末端时最后一个字符显示不完整的问题。
- 长文件名文字窗口改为由白色反显矩形边界推导，左右视觉留白保持一致。
- 播放期间产生的上下键事件不再带回文件列表，反显开关仅能在文件列表中切换。
- 文件列表反显状态文字改为 `Inv ON` / `Inv OFF`。
- 长文件名在 `Loading` 和错误弹窗中会在边框内以省略号显示，不再越过弹窗边界。
- 弹窗英文统一为每个单词首字母大写，并保留 `SD`、`FAT`、`OVID`、`UART`、`CRC` 等技术缩写。

## v1.2.1 Img2Lcd 兼容与工程整理（2026-08-20）

### Firmware and UI

- 文件列表右上角改为 `Inv on/off` 播放反显状态，同时按上、下键可切换，重启后默认关闭。
- 反显开启时仅在首帧视频送显后调用 OLED 硬件反显；主动退出和所有播放错误路径都会在弹窗前恢复正常显示。
- 普通状态和错误弹窗改为两行全屏页，白色区域从左向右扩展并保留，扫过的文字以白底黑字显示。
- `Loading` 和 `Playback stopped` 保留中心小矩形展开、停留、收起动画。

### Tools

- 新增 `merge_img2lcd.py`，可将按自然文件名排序的 Img2Lcd 单帧 `.c` 文件规范化并合并为 `h2bin.py` 可读取的头文件。
- 合并工具会生成唯一的帧数组名，并检查空目录、数组数量、字节范围和帧长度一致性。
- 精简 `h2bin.py` 的职责，删除图片目录、GIF、Pillow、二值化和缩放处理，只负责将 `.h` 取模数组打包为 OVID `.BIN`，并保留 `info` 校验功能。
- 简化转换命令，移除 `from-images`、`from-header` 和 `--match`；现在直接传入输入 `.h`、输出 `.BIN`、宽高和帧率。
- `h2bin.py` 默认适配 Img2Lcd 的“垂直扫描”输出，将逐列排列自动转换为固件需要的 OLED 页主序，解决播放时出现规律竖条和图像错位的问题。
- 已经采用 OLED 页主序的历史取模头文件可使用 `--page-major` 跳过转换，避免被重复转置。
- 新增 `generate_popup_bins.py` 和 5 个 FAT 8.3 测试文件，用于验证加载/退出弹窗、反显、错误头、超屏帧和坏帧 CRC 处理。

### 构建与工具链

- 项目、CubeMX 工程和构建产物统一改名为 `SD_Card_OVID_Player`。
- 新增 VS Code 官方 STM32 扩展推荐与 ST-Link 调试配置，可在打开项目后通过 `F5` 构建、刷写和调试。
- GNU Arm 工具链改为优先从 Bundle Manager 的 `CUBE_BUNDLE_PATH` 动态解析，并保留系统 `PATH` 回退，不再依赖固定 bundle 版本、用户名或安装目录。
- clangd 的查询驱动路径改用版本通配匹配，升级 STM32 工具 bundle 后不需要手动修改配置。

### Documentation

- README、GitHub 地址和构建/烧录说明同步使用新的项目名称。
- OVID 制作说明改为 PotPlayer/IrfanView 准备帧、Img2Lcd 取模、合并头文件和 `h2bin.py` 打包的连续流程，并聚焦当前 OVID v2 格式。
- 将 README 首屏改成适合 GitHub 展示的项目介绍，加入静态徽章、常用链接、隐藏图片区模板和可由作者手动填写的“项目初衷”区域。
- 将首选上手流程改为“下载完整项目 → 安装官方 STM32 VS Code 扩展 → 连接 ST-Link → 按 F5 构建并刷写”，命令行和 CubeProgrammer 收进备用折叠章节。
- 重写 README，将快速上手放到架构和协议说明之前。
- 明确 OVID 的用途，以及 MP4 需要先导出图片帧这一限制。
- 修正信息页横向反显动画、容量扫描和 60 FPS 目标的说明。
- 将完整版本历史迁移到本文件，并补充项目 MIT 许可证。
- 增加 ST-Link SWD 接线、STM32CubeProgrammer 图形界面与命令行烧录说明，并明确转换脚本所在位置。
- 调整 README 为面向 GitHub 访客的公开项目说明，补充支持范围、快速开始和问题反馈要求。

## v1.2.0 可靠性、OVID v2 与诊断更新（2026-08-19）

- 小方框弹窗改为异步状态，可覆盖后续 UI 渲染；确认键可提前关闭。
- 检卡成功和文件载入提示在进入阻塞式存储操作前按约 60 FPS 完整播放，避免弹窗只显示首帧；弹窗、信息页统一使用 300 ms 横向扩张反显。
- 反显区域像拔卡动画一样从左侧扩张并保留，扫过文字后整页保持白底黑字，不再使用会滑出屏幕的窄光带。
- 文件列表底部将大帧数压缩为 `K/M/G` 显示，并将元数据分隔线上移 1 像素，避免长数字拥挤。
- `Loading / 文件名` 与 `Library / Playback stopped` 恢复为小矩形展开/收起动画；其他状态页继续使用横向扩张反显。
- UI 英文改用正常标题和句子大小写，`SD`、`FAT`、`OVID`、`SPI`、`I2C` 等技术缩写继续保留大写。
- 优化 128×64 容量页间距，分离进度条、`OK: Skip` 和活动光点；FAT 与目录扫描动画统一为 16 ms 刷新周期。
- 容量扫描改用千分比定点插值，显示进度平滑追赶真实 FAT 扫描值；完成后最多用约 320 ms 平滑补到 100%。
- 新增 UI 帧率诊断，每秒通过串口报告实际 FPS、最长帧间隔和超时帧数；非动画长间隔不会被误记为掉帧。
- 文件列表增加 110 ms 选择框缓动，长按时缩短至 55 ms；选中长文件名延时往返滚动，底部元数据每 1500 ms 分页揭示。
- 加入约 8 秒 IWDG，看门狗复位后显示恢复提示。
- Debug 构建在调试器暂停内核时冻结 IWDG，断点调试不会被误判为卡死；Release 保持独立运行。
- HardFault 自动保存寄存器、PC/LR、CFSR/HFSR、应用状态和当前文件到 `.noinit` SRAM，重启后通过串口和诊断页报告。
- 容量扫描显示 `OK: Skip`，可跳过完整 FAT 扫描并以 `Free: N/A` 快速进入文件列表。
- 新增 OVID v2：16 字节兼容头、头部 CRC16、逐帧 CRC32；坏帧保持上一帧继续播放，v1 文件仍可使用。
- `h2bin.py` 默认生成 v2，新增 `--v1`，`info` 可逐帧校验 CRC；回归测试扩展至 6 项。
- 文件浏览支持最长 63 字符 LFN、大小写无关排序、长按加速、记忆选中位置，并显示分辨率/FPS/帧数/OVID 版本。
- 增加开机“上+下”诊断模式，显示复位、内存、按键、SD/SPI、OLED DMA、I2C 和故障记录，并可执行可恢复的 SD 读写自检。
- OLED 控制器配置支持 SSD1306/SH1106、列偏移和默认镜像；CMake 增加对应覆盖参数。
- I2C 连续故障后自动从 1.4 MHz 逐级降至 400 kHz，诊断页显示当前速率、错误和超时计数。

## v1.1.0 完整 UI 与存储信息更新（2026-08-19）

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

## v1.0.1 宏适配与可靠性更新（2026-08-19）

- 屏幕尺寸和帧容量改为完全由 OLED 宏推导。
- 支持单帧超过 1024 B，不再额外分配整帧播放缓冲。
- 通用化软件滚动、菜单布局、测试坐标和显存索引。
- 增加严格 OVID 校验和 `1–120 FPS` 播放规则。
- 改为 `/function` 优先、根目录回退，不再自动创建目录。
- 改进热拔插、FatFs 错误恢复、OLED 双缓冲覆盖时序和 DMA/I2C 超时恢复。
- 更新转换工具，并首次补充完整的 GitHub README。

## v1.0.0 初始版本

- STM32F103、SPI SD、FatFs 与 SSD1306 OLED 双缓冲。
- 三按键 `.BIN` 文件浏览与 OVID 循环播放。
- SD 卡信息、CRC、自检、串口诊断和图片/头文件转换工具。
- 屏幕和播放器主要按 128×64、1024 B 固定配置实现。
- 扫描根目录，同时存在未实际使用的 `/function` 创建逻辑。
- 视频头校验、拔卡恢复和 OLED DMA 超时处理较基础。
