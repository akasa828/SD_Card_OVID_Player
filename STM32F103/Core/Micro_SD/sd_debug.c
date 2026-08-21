/**
  ******************************************************************************
  * @file    sd_debug.c
  * @author  riochihao
  * @brief   SD 卡串口调试输出实现（USART1 裸寄存器 + printf 重定向）
  ******************************************************************************
  */
#include <stdio.h>
#include "main.h"        /* CMSIS 设备头：USART1/GPIOA/RCC 寄存器 + HAL_RCC_GetPCLK2Freq */
#include "sd_debug.h"

#define SD_DEBUG_TX_TIMEOUT_MS  5U

static uint8_t sd_debug_wait_txe(void)
{
    uint32_t started = HAL_GetTick();
    while ((USART1->SR & USART_SR_TXE) == 0U) {
        if (HAL_GetTick() - started >= SD_DEBUG_TX_TIMEOUT_MS) return 0U;
    }
    return 1U;
}

/*
 * USART1 TX-only，裸寄存器配置。引脚 PA9 = USART1_TX。
 * 选 USART1 因其挂在 APB2（PCLK2，本工程 72MHz），与 SPI1/I2C1 引脚无冲突：
 *   SPI1=PA5/6/7, I2C1=PB6/7, SD-CS=PB0，PA9/PA10 空闲。
 */

void SD_Debug_UART_Init(void)
{
    /* 1) 开 GPIOA 与 USART1 时钟（APB2） */
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_USART1EN;

    /* 2) PA9 配置为复用推挽输出、50MHz（CRH 控制 PIN8~15，PA9 为 [7:4]）。
     *    MODE9=0b11(50MHz输出), CNF9=0b10(复用推挽) → 4 位 = 0b1011 = 0xB。 */
    GPIOA->CRH &= ~(0xFU << ((9U - 8U) * 4U));
    GPIOA->CRH |=  (0xBU << ((9U - 8U) * 4U));

    /* 3) 波特率：USARTDIV = fPCLK2 / 波特率，写入 BRR（16 倍过采样下整数+小数同布局，
     *    直接用四舍五入的整数值即可，误差远小于 UART 容限）。 */
    uint32_t pclk2 = HAL_RCC_GetPCLK2Freq();
    USART1->BRR = (uint16_t)((pclk2 + SD_DEBUG_BAUD / 2U) / SD_DEBUG_BAUD);

    /* 4) 使能发送器与 USART（8N1 为复位默认，无需改 CR2/CR3） */
    USART1->CR1 = USART_CR1_TE | USART_CR1_UE;
}

/**
 * @brief 标准库底层字符输出钩子（覆盖 syscalls.c 中的弱符号）
 * @note  _write/printf 最终调用此函数。阻塞等待发送寄存器空再写。
 *        将 '\n' 自动补 '\r'，方便终端换行显示。
 */
int __io_putchar(int ch)
{
    if (ch == '\n')
    {
        if (!sd_debug_wait_txe()) return ch;
        USART1->DR = (uint16_t)'\r';
    }
    if (!sd_debug_wait_txe()) return ch;
    USART1->DR = (uint16_t)(ch & 0xFFU);
    return ch;
}

void SD_Debug_Print_Info(SD_Card *card)
{
    if (card == NULL) { printf("[SD] card == NULL\n"); return; }

    if (!card->info.initialized)
    {
        int t = SD_Init_Card(card);
        if (t <= 0) { printf("[SD] init FAIL (err=%d)\n", t); return; }
    }

    const SD_CardInfo *info = &card->info;

    const char *type_str;
    switch (info->type)
    {
        case SD_TYPE_V1:   type_str = "SDSC v1";  break;
        case SD_TYPE_V2:   type_str = "SDSC v2";  break;
        case SD_TYPE_V2HC: type_str = "SDHC/SDXC"; break;
        default:           type_str = "Unknown";  break;
    }

    /* CID ASCII 字段（OID 2 字符 / PNM 5 字符），非可打印字符替为 '.' */
    char oid[3], pnm[6];
    for (uint8_t i = 0; i < 2U; ++i)
    { uint8_t c = info->cid_raw[1 + i]; oid[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.'; }
    oid[2] = '\0';
    for (uint8_t i = 0; i < 5U; ++i)
    { uint8_t c = info->cid_raw[3 + i]; pnm[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.'; }
    pnm[5] = '\0';

    uint32_t psn = ((uint32_t)info->cid_raw[9]  << 24) | ((uint32_t)info->cid_raw[10] << 16)
                 | ((uint32_t)info->cid_raw[11] <<  8) |  (uint32_t)info->cid_raw[12];

    printf("\n===== SD Card Info =====\n");
    printf("Type      : %s\n", type_str);
    printf("Addressing: %s\n", info->block_addr ? "block (LBA)" : "byte");
    if (info->capacity_mb >= 1024U)
        printf("Capacity  : %u MB (%u.%u GB)\n", (unsigned)info->capacity_mb,
               (unsigned)(info->capacity_mb / 1024U),
               (unsigned)((info->capacity_mb % 1024U) * 10U / 1024U));
    else
        printf("Capacity  : %u MB\n", (unsigned)info->capacity_mb);
    printf("Blocks    : %u  (x512B)\n", (unsigned)info->block_count);
    printf("OCR       : 0x%08X\n", (unsigned)info->ocr);
    printf("MID       : 0x%02X\n", (unsigned)info->cid_raw[0]);
    printf("OID       : %s\n", oid);
    printf("Product   : %s\n", pnm);
    printf("PRV       : %u.%u\n", (unsigned)(info->cid_raw[8] >> 4), (unsigned)(info->cid_raw[8] & 0x0FU));
    printf("Serial    : 0x%08X\n", (unsigned)psn);
    printf("========================\n");
}
