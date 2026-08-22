# 烧录到 STM32

**中文** · [English](FLASHING_EN.md) · [返回 README](../README.md)

## 1. 连接 ST-Link

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

## 2. 在 VS Code 中按 F5

连接 ST-Link 后，在左侧 **Run and Debug** 中选择 `STM32: Build, flash and debug with ST-Link`，再按 `F5`。`STM32F103/.vscode/launch.json` 会调用官方扩展完成以下工作：

```text
构建当前 CMake preset → 取得对应 ELF → 通过 ST-Link 下载 → 停在 main
```

第一次停在 `main` 后，再按一次 `F5` 就会继续运行。这里没有写死 `build/Debug`、盘符或用户名；选择 Release preset 时，扩展会使用 Release 对应的 ELF。

## 备用：使用 STM32CubeProgrammer 手动烧录

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
