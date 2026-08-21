/**
  ******************************************************************************
  * @file    sd_debug.h
  * @author  riochihao
  * @brief   SD 卡串口调试输出（printf 重定向到 USART1，无需 OLED）
  * @note    自包含裸寄存器 USART1 TX-only 实现：不依赖 HAL UART 模块、
  *          不改 CubeMX 生成文件。引脚 PA9(USART1_TX)，默认 115200 8N1。
  *          提供 __io_putchar 使标准库 printf 输出到串口（Newlib/Picolibc 均适用）。
  ******************************************************************************
  */
#ifndef __SD_DEBUG_H
#define __SD_DEBUG_H

#ifdef __cplusplus
extern "C" {
#endif

#include "SD_reader.h"

/** 调试串口波特率（可在包含前 #define 覆盖） */
#ifndef SD_DEBUG_BAUD
#define SD_DEBUG_BAUD  115200U
#endif

/**
 * @brief 初始化调试串口（USART1, PA9=TX, SD_DEBUG_BAUD, 8N1, 仅发送）
 * @note  裸寄存器配置，独立于 HAL UART。调用一次即可，之后 printf 直接输出到串口。
 *        波特率由 HAL_RCC_GetPCLK2Freq() 实时计算，跟随系统时钟，无需硬编码。
 */
void SD_Debug_UART_Init(void);

/**
 * @brief 通过串口 printf 打印卡类型/容量/CID（无 OLED 时调试用）
 * @note  若卡未初始化会先调用 SD_Init_Card()。输出卡类型、容量、总块数、
 *         制造商 ID(MID)、OEM ID(OID)、产品名(PNM)、序列号(PSN)。
 *         调用前需先 SD_Debug_UART_Init()。
 * @param card SD 卡句柄指针（NULL 时打印提示并返回）
 */
void SD_Debug_Print_Info(SD_Card *card);

#ifdef __cplusplus
}
#endif

#endif /* __SD_DEBUG_H */
