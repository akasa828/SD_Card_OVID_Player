<a id="top"></a>

<p align="center">
  <strong>中文</strong> · <a href="TROUBLESHOOTING_EN.md">English</a>
</p>

# 诊断与常见问题

[← 返回项目 README](../README.md)

## 🩺 诊断

USART1 TX 会以 115200 8N1 输出 SD 初始化、FatFs、播放器、UI 帧率和故障信息。正常动画期间，串口每秒报告实际 FPS、最长帧间隔和超时帧数。SD 阻塞、DMA/I2C 恢复和自动降速不属于 60 FPS 的硬件验收区间。

开机时同时按住上键和下键可以进入三页诊断界面。这里能看到复位原因、Flash/RAM、栈余量、按键、SD/SPI、OLED DMA、当前 I2C 速率和最近一次 HardFault 的 PC/LR/CFSR。

**第二页按确认会执行“保存原块 → 写入 → 读回 → 校验 → 恢复”的 SD 自检。**

> [!WARNING]
> SD 自检会临时改写卡上的原始块。固件随后会写回原数据，但供电不稳定时仍然不建议运行。

系统还启用了约 8 秒的独立看门狗。Debug 构建在调试器暂停内核时会冻结它，Release 则保持独立运行。HardFault 现场保存在 `.noinit` SRAM，重启后会通过屏幕和串口提示。

## ❓常见问题 Q & A
### 为什么 OLED 在 1.4 MHz 下花屏？

1.4 MHz 超出了不少模块的常规工作条件。**直接降低初始速率即可解决**，自动降速只能在驱动识别到连续故障后生效，无法修复所有信号完整性问题。

**解决方案：** 找到`./Core/Inc/i2c.h`，修改`1399999UL`数值
```c
#define I2C1_INITIAL_CLOCK_HZ 1399999UL
```

### 拔卡后为什么没有立刻回到等待界面？

信息页和列表每 500 ms 检测一次，并要求连续两次失败，因此最慢大约需要 1 秒。播放中的拔卡由文件读取错误触发。重新插卡后，等待界面每 700 ms 尝试一次初始化。

---

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>
