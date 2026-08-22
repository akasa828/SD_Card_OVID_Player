# 开发参考

**中文** · [English](DEVELOPMENT_EN.md) · [返回 README](../README.md)

## 项目结构

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
├── docs/images/             # 实机图片与 UI 动图
├── tools/
│   ├── ovid_converter_gui.py # Material 3 桌面转换器
│   ├── media2ovid.py        # 图片/GIF/视频直转核心与命令行
│   ├── h2bin.py             # 取模头文件打包与 OVID 校验
│   └── merge_img2lcd.py     # 合并 Img2Lcd 单帧 C 数组
└── SD_Card_OVID_Player.code-workspace
```

`STM32F103/Core/隐藏关卡/` 是仓库中的真实历史目录，工具示例也引用了它，所以这里没有只在文档里把它改成英文。若以后重命名，需要一起更新脚本注释、命令示例和相关路径。

## 构建占用与验证

下面的数据来自 Arm GNU Toolchain 14.3.1、默认 128×64 和双缓冲配置：

| 构建 | Flash | RAM |
|---|---:|---:|
| Debug (`-Os -g3`) | 55,816 B / 64 KiB（85.17%） | 10,040 B / 20 KiB（49.02%） |
| Release (`-Os -g0`) | 55,804 B / 64 KiB（85.15%） | 10,040 B / 20 KiB（49.02%） |

> [!NOTE]
> Debug 仍保留完整诊断路径和 `-g3` 调试符号，但为兼容不同版本 GNU Arm 工具链的代码尺寸，也使用 `-Os`。单步调试时个别变量可能被优化；平时运行仍建议使用 Release。85% 左右的 Flash 占用并不算非常宽裕，继续增加字库或大段 UI 文案前仍然要看一次 `arm-none-eabi-size`。

当前已经重新完成 128×32、128×64、128×128 和 96×64 的编译验证，也覆盖了 SSD1306、SH1106 两条控制器分支。128×128 Debug 最大矩阵配置占用 12,088 B RAM（59.02%）。转换工具检查覆盖 Python 语法和 OVID 测试文件重新生成流程。

30 分钟连续播放、真实热拔插，以及不同 OLED 模块在 1.4 MHz 下的信号完整性仍然属于目标板测试，主机编译不能替代这些结果。

## 后续计划

- [ ] 受限于 STM32F103C8T6 当前的 Flash 和 RAM 容量，计划将播放器移植到 ESP32，并在资源更充足的平台上继续扩展功能。
- [x] 将 SPI Micro SD + FatFs 文件系统驱动和 SSD1306/SH1106 OLED 驱动分别整理成可独立使用、方便移植的模块。
- [ ] **正在进行中：** 简化从图片、GIF 或视频素材生成 OVID `.BIN` 文件的转换流程。当前已提供 OVID Converter，预览、转换体验和 Windows 打包仍在继续完善。
