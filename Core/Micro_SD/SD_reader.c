/**
  ******************************************************************************
  * @file    SD_reader.c
  * @author  riochihao
  * @brief   SD SPI 通用驱动实现 —— 硬件解耦 + 多实例 + CRC 校验 + 自适应时钟
  * @note    所有硬件操作通过 SD_IO 回调抽象，移植只需实现 io 函数指针。
  *          默认后端为 STM32 HAL（hspi1 + PB0 BSRR CS）。
  ******************************************************************************
  */
#include <string.h>
#include <stdio.h>
#include "stdint.h"
#include "main.h"
#include "spi.h"
#include "oled.hpp"
#include "SD_reader.h"

/*
 * 内部 IO 快捷宏 + static 辅助函数
 * （全部仅 SD_reader.c 内可见，对外开放的接口见 SD_Init_Card / SD_Read_Block_Card 等）
 */
#define SD_IO_BYTE(c, tx)         ((c)->io.spi_byte(tx))
#define SD_IO_CS_LOW(c)           ((c)->io.cs_low())
#define SD_IO_CS_HIGH(c)          ((c)->io.cs_high())
#define SD_IO_TICK(c)             ((c)->io.tick_ms())

/* 块数→MB 换算：block_count * 512 / (1024*1024) */
#define SD_BLOCKS_PER_MB  2048U

/**
 * @brief 计算 SD 命令帧 CRC7（多项式 x^7+x^3+1 = 0x09，MSB 先处理）
 * @note  作用于命令帧前 5 字节（0x40|cmd + 4 字节参数）。返回值已左移 1 位并补停止位 1，
 *        即可直接作为帧第 6 字节发送。卡端开启 CRC 校验后，每条命令都需正确 CRC7。
 *        （已数值验证：CMD0→0x95、CMD8→0x87，与规范一致。）
 * @param data 命令帧前 5 字节
 * @retval (CRC7 << 1) | 1 的完整字节
 */
#if SD_ENABLE_CMD_CRC
static uint8_t _sd_crc7(const uint8_t *data)
{
    uint8_t crc = 0;
    for (uint8_t i = 0; i < 5U; ++i)
    {
        crc ^= data[i];
        for (uint8_t b = 0; b < 8U; ++b)
            crc = (crc & 0x80U) ? (uint8_t)((crc << 1) ^ (0x09U << 1)) : (uint8_t)(crc << 1);
    }
    return (uint8_t)(crc | 0x01U);   /* 高 7 位为 CRC7，最低位为停止位 */
}
#endif

/**
 * @brief 发送 6 字节命令帧并轮询 R1
 * @note  不管理 CS（调用方自行拉低/拉高），方便读取 R3/R7 等带尾随字节的应答。
 *        当卡端 CRC 已开启（SD_ENABLE_CMD_CRC && io.crc_check）时，忽略传入的 crc 占位值，
 *        为每条命令现算正确 CRC7；否则沿用调用方传入的 crc（CMD0/CMD8 的必需值或 0x01 占位）。
 */
static uint8_t _sd_cmd_raw(const SD_Card *card, uint8_t cmd, uint32_t arg, uint8_t crc)
{
    uint8_t frame[6];
    frame[0] = 0x40U | (cmd & 0x3FU);
    frame[1] = (uint8_t)(arg >> 24);
    frame[2] = (uint8_t)(arg >> 16);
    frame[3] = (uint8_t)(arg >> 8);
    frame[4] = (uint8_t)(arg);
#if SD_ENABLE_CMD_CRC
    frame[5] = card->io.crc_check ? _sd_crc7(frame) : crc;
#else
    frame[5] = crc;
#endif
    const uint8_t *p = frame;
    for (uint8_t i = 0; i < sizeof(frame); ++i) (void)SD_IO_BYTE(card, *p++);
    uint8_t r1 = SD_R1_NO_RESPONSE;
    for (uint8_t retry = 0; retry < 10U; ++retry)
    {
        r1 = SD_IO_BYTE(card, 0xFFU);
        if ((r1 & 0x80U) == 0U) break;
    }
    return r1;
}

/** @brief 等待卡返回指定数据令牌（如 0xFE 块起始令牌） */
static int _sd_wait_token(const SD_Card *card, uint8_t token, uint32_t timeout_ms)
{
    uint32_t t0 = SD_IO_TICK(card);
    do { if (SD_IO_BYTE(card, 0xFFU) == token) return SD_OK; }
    while ((SD_IO_TICK(card) - t0) < timeout_ms);
    return SD_TIMEOUT;
}

/** @brief 等待卡退出忙状态（MISO=HIGH 表示内部编程完成） */
static int _sd_wait_ready(const SD_Card *card, uint32_t timeout_ms)
{
    uint32_t t0 = SD_IO_TICK(card);
    do { if (SD_IO_BYTE(card, 0xFFU) == 0xFFU) return SD_OK; }
    while ((SD_IO_TICK(card) - t0) < timeout_ms);
    return SD_TIMEOUT;
}

/** @brief 块地址换算：SDSC→字节地址(*512)，SDHC→块号直传 */
static uint32_t _sd_to_addr(const SD_Card *card, uint32_t block_addr)
{
    return card->info.block_addr ? block_addr : (block_addr * SD_BLOCK_SIZE);
}

/**
 * @brief 重入保护：原子地“测试并置位”busy 标志
 * @note  单核 M3 上用关中断构造临界区，防止 ISR 在事务中途进入同一句柄破坏总线。
 * @retval SD_OK 成功获得占用权；SD_BUSY 已被占用
 */
static int _sd_lock(SD_Card *card)
{
    int ok;
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    if (card->busy) { ok = SD_BUSY; }
    else            { card->busy = 1U; ok = SD_OK; }
    if (!primask) __enable_irq();   /* 仅当进入前中断是开的才恢复，避免误开中断 */
    return ok;
}

/** @brief 释放占用权 */
static void _sd_unlock(SD_Card *card)
{
    card->busy = 0U;
}

/**
 * @brief 探测硬件 SPI SCK 是否满足 <400kHz 握手要求
 * @note  通过 IO 抽象的回调读取总线时钟 + prescaler，不硬编码 MCU 频率，跨平台。
 *         注意：修改 card->info.speed，故传入非 const 指针。
 */
static uint8_t _sd_detect_speed(SD_Card *card)
{
    uint32_t bus_clk = card->io.get_bus_clk();
    uint32_t ratio   = 2UL << (card->io.get_prescaler() >> 3U);
    uint32_t sck     = bus_clk / ratio;
    if (sck <= 400000UL)
    {
        card->info.speed = SD_SPI_SPEED_LOW;
        return SD_SPI_SPEED_LOW;
    }
    return SD_SPI_SPEED_HIGH;
}

/*====================================================================
  CRC16-CCITT（XMODEM，多项式 0x1021，初值 0x0000）
  参照 SD 物理层规范 S4.5
  ====================================================================*/

/* 256 项查表（512B flash）。F103xB flash 单等待态、无数据 cache，访问确定性好。
 * 每字节仅 1 次查表 + 移位异或（~8 周期/字节），比逐位计算（~40 周期/字节）快约 5~6 倍。
 * 表项 = 对单字节 b 执行 8 次 0x1021 多项式移位的结果（crc 初值 0、b 置于高字节）。 */
static const uint16_t k_crc16_tab[256] = {
    0x0000,0x1021,0x2042,0x3063,0x4084,0x50A5,0x60C6,0x70E7,
    0x8108,0x9129,0xA14A,0xB16B,0xC18C,0xD1AD,0xE1CE,0xF1EF,
    0x1231,0x0210,0x3273,0x2252,0x52B5,0x4294,0x72F7,0x62D6,
    0x9339,0x8318,0xB37B,0xA35A,0xD3BD,0xC39C,0xF3FF,0xE3DE,
    0x2462,0x3443,0x0420,0x1401,0x64E6,0x74C7,0x44A4,0x5485,
    0xA56A,0xB54B,0x8528,0x9509,0xE5EE,0xF5CF,0xC5AC,0xD58D,
    0x3653,0x2672,0x1611,0x0630,0x76D7,0x66F6,0x5695,0x46B4,
    0xB75B,0xA77A,0x9719,0x8738,0xF7DF,0xE7FE,0xD79D,0xC7BC,
    0x48C4,0x58E5,0x6886,0x78A7,0x0840,0x1861,0x2802,0x3823,
    0xC9CC,0xD9ED,0xE98E,0xF9AF,0x8948,0x9969,0xA90A,0xB92B,
    0x5AF5,0x4AD4,0x7AB7,0x6A96,0x1A71,0x0A50,0x3A33,0x2A12,
    0xDBFD,0xCBDC,0xFBBF,0xEB9E,0x9B79,0x8B58,0xBB3B,0xAB1A,
    0x6CA6,0x7C87,0x4CE4,0x5CC5,0x2C22,0x3C03,0x0C60,0x1C41,
    0xEDAE,0xFD8F,0xCDEC,0xDDCD,0xAD2A,0xBD0B,0x8D68,0x9D49,
    0x7E97,0x6EB6,0x5ED5,0x4EF4,0x3E13,0x2E32,0x1E51,0x0E70,
    0xFF9F,0xEFBE,0xDFDD,0xCFFC,0xBF1B,0xAF3A,0x9F59,0x8F78,
    0x9188,0x81A9,0xB1CA,0xA1EB,0xD10C,0xC12D,0xF14E,0xE16F,
    0x1080,0x00A1,0x30C2,0x20E3,0x5004,0x4025,0x7046,0x6067,
    0x83B9,0x9398,0xA3FB,0xB3DA,0xC33D,0xD31C,0xE37F,0xF35E,
    0x02B1,0x1290,0x22F3,0x32D2,0x4235,0x5214,0x6277,0x7256,
    0xB5EA,0xA5CB,0x95A8,0x8589,0xF56E,0xE54F,0xD52C,0xC50D,
    0x34E2,0x24C3,0x14A0,0x0481,0x7466,0x6447,0x5424,0x4405,
    0xA7DB,0xB7FA,0x8799,0x97B8,0xE75F,0xF77E,0xC71D,0xD73C,
    0x26D3,0x36F2,0x0691,0x16B0,0x6657,0x7676,0x4615,0x5634,
    0xD94C,0xC96D,0xF90E,0xE92F,0x99C8,0x89E9,0xB98A,0xA9AB,
    0x5844,0x4865,0x7806,0x6827,0x18C0,0x08E1,0x3882,0x28A3,
    0xCB7D,0xDB5C,0xEB3F,0xFB1E,0x8BF9,0x9BD8,0xABBB,0xBB9A,
    0x4A75,0x5A54,0x6A37,0x7A16,0x0AF1,0x1AD0,0x2AB3,0x3A92,
    0xFD2E,0xED0F,0xDD6C,0xCD4D,0xBDAA,0xAD8B,0x9DE8,0x8DC9,
    0x7C26,0x6C07,0x5C64,0x4C45,0x3CA2,0x2C83,0x1CE0,0x0CC1,
    0xEF1F,0xFF3E,0xCF5D,0xDF7C,0xAF9B,0xBFBA,0x8FD9,0x9FF8,
    0x6E17,0x7E36,0x4E55,0x5E74,0x2E93,0x3EB2,0x0ED1,0x1EF0,
};

/**
 * @brief 计算 SD 数据块 CRC16
 * @note  多项式 x^16 + x^12 + x^5 + 1（0x1021），初值 0，结果大端发送（先发高字节）。
 *        查表实现，等价于逐位 MSB-first 计算。
 */
uint16_t SD_CRC16(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0;
    for (uint16_t n = 0; n < len; ++n)
        crc = (uint16_t)((crc << 8) ^ k_crc16_tab[(uint8_t)((crc >> 8) ^ data[n])]);
    return crc;
}

/*====================================================================
  STM32 HAL 默认 IO 后端（hspi1 + PB0 BSRR CS）
  ====================================================================*/

/** @brief STM32 HAL 单字节 SPI 全双工交换（轮询） */
static uint8_t _stm32_spi_byte(uint8_t tx)
{
    uint8_t rx = 0xFF;
    if (HAL_SPI_TransmitReceive(&hspi1, &tx, &rx, 1U, SD_SPI_TIMEOUT) != HAL_OK)
        return 0xFF;
    return rx;
}

/** @brief STM32 块接收（轮询，整块一次性传输）
 *  @note  用 DMA 实测返回错位/损坏数据，故走轮询。但不再逐字节调用 HAL（1024 次/帧开销大），
 *         改为一次 HAL_SPI_TransmitReceive 传整块——同一可靠路径、调用开销几乎归零，大幅提速。
 *         先把 rx 填 0xFF 作发送源（读阶段 SD 忽略 MOSI）；HAL 字节循环里先读 tx[i] 再写 rx[i]，
 *         同缓冲同下标安全。 */
static int _stm32_recv_dma(uint8_t *rx, uint16_t len)
{
    if (rx == NULL || len == 0U) return SD_PARAM_ERR;
    (void)memset(rx, 0xFF, len);
    uint32_t to = (uint32_t)len / 2U + 100U;   /* 充裕超时：低速档 512B 约 15ms，留足裕量 */
    if (HAL_SPI_TransmitReceive(&hspi1, rx, rx, len, to) != HAL_OK) return SD_ERR;
    return SD_OK;
}

/** @brief STM32 块发送（轮询，整块一次性传输）——同上，一次 HAL 调用 */
static int _stm32_send_dma(const uint8_t *tx, uint16_t len)
{
    if (tx == NULL || len == 0U) return SD_PARAM_ERR;
    uint32_t to = (uint32_t)len / 2U + 100U;
    if (HAL_SPI_Transmit(&hspi1, (uint8_t *)tx, len, to) != HAL_OK) return SD_ERR;
    return SD_OK;
}

/** @brief CS 拉低（PB0 BSRR 写 1 到 BR16） */
static void _stm32_cs_low(void)  { SD_CS_LOW(); }

/** @brief CS 拉高 + 8 个补时钟（SD 规范要求释放后补时钟完成状态切换） */
static void _stm32_cs_high(void) { SD_CS_HIGH(); (void)_stm32_spi_byte(0xFFU); }

/** @brief 设 SPI prescaler 并重初始化外设，失败时回退原值 */
static int _stm32_set_speed(uint32_t prescaler)
{
    /* HAL_SPI_Init 会先 __HAL_SPI_DISABLE 再重写 CR1/CR2，只有总线空闲时才安全。
     * 若在一次 DMA 块传输进行中被调用，会把外设连同活动 DMA 一起拆掉、导致卡失步。 */
    if (HAL_SPI_GetState(&hspi1) != HAL_SPI_STATE_READY) return SD_ERR;
    uint32_t prev = hspi1.Init.BaudRatePrescaler;
    hspi1.Init.BaudRatePrescaler = prescaler;
    if (HAL_SPI_Init(&hspi1) != HAL_OK)
    {
        hspi1.Init.BaudRatePrescaler = prev;
        (void)HAL_SPI_Init(&hspi1);
        return SD_ERR;
    }
    return SD_OK;
}

static uint32_t _stm32_get_prescaler(void) { return hspi1.Init.BaudRatePrescaler; }
static uint32_t _stm32_get_bus_clk(void)   { return HAL_RCC_GetPCLK2Freq(); }
static uint32_t _stm32_tick_ms(void)       { return HAL_GetTick(); }

/** @brief 默认 STM32 HAL IO 实例，所有回调绑定 hspi1 + PB0 */
static const SD_IO g_default_io = {
    .spi_byte      = _stm32_spi_byte,
    .recv_dma      = _stm32_recv_dma,
    .send_dma      = _stm32_send_dma,
    .cs_low        = _stm32_cs_low,
    .cs_high       = _stm32_cs_high,
    .set_speed     = _stm32_set_speed,
    .get_prescaler = _stm32_get_prescaler,
    .get_bus_clk   = _stm32_get_bus_clk,
    .tick_ms       = _stm32_tick_ms,
    .crc_check     = 1U,
};

/** @brief 默认全局实例——向后兼容 API（SD_Init / SD_Read_Block 等）均用此句柄 */
SD_Card g_sd_card = { .io = {0}, .info = {0} };

/**
 * @brief 用 STM32 HAL 默认回调填充 SD_IO
 * @param card SD 卡句柄（不可为 NULL）
 * @note  SD_Init_Card 内部若检测到 io 未绑定会自动调用，多数情况下用户无需手动调用
 */
void SD_Init_Default_IO(SD_Card *card)
{
    if (card == NULL) return;
    card->io = g_default_io;
    (void)memset(&card->info, 0x00, sizeof(card->info));
    card->info.type  = SD_TYPE_NONE;
    card->info.speed = SD_SPI_SPEED_NULL;
}

//====================================================================
//  SD_Set_Speed_Card -- 动态调整 SPI 时钟速率档
//====================================================================
//  握手阶段必须 <400kHz，进入 SPI 模式后应切高速。
//  啊啊啊，搞什么啊，我要的握手啊，不是牵红线！怎么这么难改啊！代码也没错啊
//  内部通过改写 SPI prescaler 寄存器并重初始化外设实现。
//  若已在目标速率则跳过重初始化（零开销）。
//  speed 参数：只能是 SD_SPI_SPEED_LOW 或 SD_SPI_SPEED_HIGH，
//  传 SD_SPI_SPEED_NULL 返回 SD_PARAM_ERR。
int SD_Set_Speed_Card(SD_Card *card, uint8_t speed)
{
    if (card == NULL) return SD_PARAM_ERR;
    if (speed == card->info.speed) return SD_OK;
    if (speed == SD_SPI_SPEED_NULL) return SD_PARAM_ERR;
    uint32_t ps = (speed == SD_SPI_SPEED_HIGH) ? SD_SPI_PRESCALER_HIGH : SD_SPI_PRESCALER_LOW;
    if (card->io.set_speed(ps) != SD_OK) return SD_ERR;
    card->info.speed = speed;
    return SD_OK;
}

//====================================================================
//  SD_Init_Card — 完整初始化握手协议
//====================================================================
//  流程：探测/确保低速(<400kHz) → >=74 空闲时钟 → CMD0 软复位 →
//  CMD8 版本探测 → ACMD41 轮询启动 → CMD58 读 OCR 判 SDHC →
//  CMD16 设块长（非 SDHC）→ CMD9 读 CSD 算容量 → CMD10 读 CID →
//  切高速时钟。所有结果写入 card->info。
int SD_Init_Card(SD_Card *card)
{
    if (card == NULL) return SD_PARAM_ERR;
    if (card->io.spi_byte == NULL) SD_Init_Default_IO(card);

    /* 校验所有必需回调，避免部分填充的 SD_IO 触发 NULL 函数指针调用 → HardFault */
    if (card->io.spi_byte == NULL || card->io.recv_dma == NULL || card->io.send_dma == NULL ||
        card->io.cs_low == NULL   || card->io.cs_high == NULL  || card->io.set_speed == NULL ||
        card->io.get_prescaler == NULL || card->io.get_bus_clk == NULL || card->io.tick_ms == NULL)
        return SD_PARAM_ERR;

    /* 先置未就绪并清零，握手成功后再原子发布，避免并发读到 initialized=1 而 block_addr 尚为 0 */
    card->info.initialized = 0U;
    (void)memset(&card->info, 0x00, sizeof(card->info));
    card->info.type  = SD_TYPE_NONE;
    card->info.speed = SD_SPI_SPEED_NULL;

    if (_sd_detect_speed(card) == SD_SPI_SPEED_HIGH)
        (void)SD_Set_Speed_Card(card, SD_SPI_SPEED_LOW);

    /* 1) >=74 idle clocks */
    SD_IO_CS_HIGH(card);
    for (uint8_t i = 0; i < 10U; ++i) (void)SD_IO_BYTE(card, 0xFFU);

    /* 2) CMD0 */
    uint8_t r1 = SD_R1_NO_RESPONSE;
    for (uint8_t retry = 0; retry < 20U; ++retry)
    {
        SD_IO_CS_LOW(card);
        r1 = _sd_cmd_raw(card, SD_CMD0, 0x00000000U, 0x95U);
        SD_IO_CS_HIGH(card);
        if (r1 == SD_R1_IDLE_STATE) break;
    }
    if (r1 != SD_R1_IDLE_STATE) return SD_NO_CARD;

    /* 3) CMD8。先判“无应答”再判非法命令位：0xFF & 0x04 也为真，
     *    若不先排除会把信号不良导致的无应答误判成 V1，进而对 SDHC 用错寻址。 */
    uint8_t card_type;
    SD_IO_CS_LOW(card);
    r1 = _sd_cmd_raw(card, SD_CMD8, 0x000001AAU, 0x87U);
    if (r1 == SD_R1_NO_RESPONSE)        { SD_IO_CS_HIGH(card); return SD_NO_CARD; }
    else if (r1 & SD_R1_ILLEGAL_CMD)    { card_type = SD_TYPE_V1; }
    else if ((r1 & ~0x80U) == SD_R1_IDLE_STATE)
    {
        uint8_t r7[4];
        for (uint8_t i = 0; i < 4U; ++i) r7[i] = SD_IO_BYTE(card, 0xFFU);
        card_type = ((r7[2] & 0x0FU) == 0x01U && r7[3] == 0xAAU) ? SD_TYPE_V2 : SD_TYPE_NONE;
    }
    else { card_type = SD_TYPE_NONE; }
    SD_IO_CS_HIGH(card);
    if (card_type == SD_TYPE_NONE) return SD_NO_CARD;

#if SD_ENABLE_CMD_CRC
    /* 3.5) CMD59 开启卡端 CRC 校验（仅在 io.crc_check 开启时）。须在 idle 阶段、ACMD41 之前下发。
     *      arg bit0=1 表示开启。开启后 _sd_cmd_raw 会为每条命令现算 CRC7。
     *      老卡可能不支持：若被拒则放弃卡端校验（读侧 CRC16 仍由本机校验，写侧不受卡校验）。 */
    if (card->io.crc_check)
    {
        SD_IO_CS_LOW(card);
        uint8_t rc = _sd_cmd_raw(card, SD_CMD59, 0x00000001U, 0x01U);
        SD_IO_CS_HIGH(card);
        if (rc & 0x80U)   /* 无有效应答/不支持 → 退回不依赖卡端 CRC（本机仍算并发送/校验） */
        {
            /* 不改 crc_check：本机继续算 CRC7/CRC16，卡虽不强制校验，多发正确 CRC 无害 */
        }
    }
#endif

    /* 4) ACMD41。先确认 CMD55 被接受（R1 bit7=0）再发 ACMD41，否则严格卡会把
     *    后续帧当普通 CMD41（保留命令）置非法位，导致循环空转到超时。 */
    uint32_t arg41 = (card_type == SD_TYPE_V2) ? 0x40000000U : 0x00000000U;
    uint32_t t0 = SD_IO_TICK(card);
    do {
        SD_IO_CS_LOW(card);
        uint8_t r55 = _sd_cmd_raw(card, SD_CMD55, 0x00000000U, 0x01U);
        if ((r55 & 0x80U) == 0U)
            r1 = _sd_cmd_raw(card, SD_ACMD41, arg41, 0x01U);
        else
            r1 = SD_R1_NO_RESPONSE;   /* CMD55 未被接受，本轮重试 */
        SD_IO_CS_HIGH(card);
        if ((SD_IO_TICK(card) - t0) > SD_ACMD41_TIMEOUT_MS) return SD_TIMEOUT;   /* 可配置上电裕量 */
    } while (r1 != 0x00U);

    /* 5) CMD58 */
    if (card_type == SD_TYPE_V2)
    {
        SD_IO_CS_LOW(card);
        r1 = _sd_cmd_raw(card, SD_CMD58, 0x00000000U, 0x01U);
        if (r1 == 0x00U)
        {
            uint8_t ocr[4];
            for (uint8_t i = 0; i < 4U; ++i) ocr[i] = SD_IO_BYTE(card, 0xFFU);
            card->info.ocr = ((uint32_t)ocr[0] << 24) | ((uint32_t)ocr[1] << 16)
                           | ((uint32_t)ocr[2] <<  8) |  (uint32_t)ocr[3];
            if (ocr[0] & 0x40U) card_type = SD_TYPE_V2HC;
        }
        SD_IO_CS_HIGH(card);
    }

    /* 6) CMD16（非 SDHC 设块长 512）。检查 R1：正常 512 是上电默认值，
     *    但若卡处于异常状态拒绝，需暴露错误而非带病继续。 */
    if (card_type != SD_TYPE_V2HC)
    {
        SD_IO_CS_LOW(card);
        r1 = _sd_cmd_raw(card, SD_CMD16, SD_BLOCK_SIZE, 0x01U);
        SD_IO_CS_HIGH(card);
        if (r1 != 0x00U) return SD_ERR;
    }

    /* 7) CSD */
    {
        SD_IO_CS_LOW(card);
        r1 = _sd_cmd_raw(card, SD_CMD9, 0x00000000U, 0x01U);
        if (r1 != 0x00U) { SD_IO_CS_HIGH(card); return SD_ERR; }
        if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK)
        { SD_IO_CS_HIGH(card); return SD_TIMEOUT; }
        uint8_t csd[16];
        for (uint8_t i = 0; i < 16U; ++i) csd[i] = SD_IO_BYTE(card, 0xFFU);
        (void)memcpy(card->info.csd_raw, csd, 16U);
        (void)SD_IO_BYTE(card, 0xFFU); (void)SD_IO_BYTE(card, 0xFFU);
        SD_IO_CS_HIGH(card);
        uint8_t ver = (csd[0] >> 6) & 0x03U;
        if (ver == 0x01U)
        {
            uint32_t csize = ((uint32_t)(csd[7] & 0x3FU) << 16) | ((uint32_t)csd[8] << 8) | (uint32_t)csd[9];
            /* 64 位中间量防溢出：SDXC 极限 C_SIZE 时 (csize+1)*1024 可达 2^32 → uint32 回绕为 0 */
            uint64_t bc = ((uint64_t)csize + 1U) * 1024U;
            card->info.block_count = (bc > 0xFFFFFFFFULL) ? 0xFFFFFFFFU : (uint32_t)bc;
        }
        else if (ver == 0x00U)
        {
            uint16_t csize = ((uint16_t)(csd[6] & 0x03U) << 10) | ((uint16_t)csd[7] << 2) | ((uint16_t)csd[8] >> 6);
            uint8_t  cmult = ((csd[9] & 0x03U) << 1) | ((csd[10] >> 7) & 0x01U);
            uint8_t  blen  = csd[5] & 0x0FU;
            uint32_t blknr = (uint32_t)(csize + 1U) * (uint32_t)(1UL << (cmult + 2U));
            card->info.block_count = blknr * ((uint32_t)(1UL << blen) / SD_BLOCK_SIZE);
        }
        else { card->info.block_count = 0U; }
        card->info.capacity_mb = card->info.block_count / SD_BLOCKS_PER_MB;
    }

    /* 8) CID */
    {
        SD_IO_CS_LOW(card);
        r1 = _sd_cmd_raw(card, SD_CMD10, 0x00000000U, 0x01U);
        if (r1 != 0x00U) { SD_IO_CS_HIGH(card); (void)memset(card->info.cid_raw, 0x00, 16U); }
        else if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK)
        { SD_IO_CS_HIGH(card); (void)memset(card->info.cid_raw, 0x00, 16U); }
        else
        {
            for (uint8_t i = 0; i < 16U; ++i) card->info.cid_raw[i] = SD_IO_BYTE(card, 0xFFU);
            (void)SD_IO_BYTE(card, 0xFFU); (void)SD_IO_BYTE(card, 0xFFU);
            SD_IO_CS_HIGH(card);
        }
    }

    card->info.type        = card_type;
    card->info.block_addr  = (card_type == SD_TYPE_V2HC) ? 1U : 0U;
    (void)SD_Set_Speed_Card(card, SD_SPI_SPEED_HIGH);
    card->info.initialized = 1U;   /* 全部就绪后最后发布，确保读到 initialized=1 时信息完整 */
    return (int)card_type;
}

//====================================================================
//  SD_Read_Block_Card -- 单块读（CMD17 + DMA + CRC 校验 + 自动重试）
//====================================================================
//  若 io.crc_check 非零，读取时会校验尾随 2 字节 CRC16-CCITT。
//  CRC 不匹配或 CMD17 被拒时自动重试，最多 SD_CRC_RETRY_MAX 次；
//  重试前若当前为高速档则降速一档读，提高信号裕量，函数退出前恢复高速。
int SD_Read_Block_Card(SD_Card *card, uint32_t block_addr, uint8_t *buf)
{
    if (card == NULL || buf == NULL || !card->info.initialized) return SD_PARAM_ERR;
    if (_sd_lock(card) != SD_OK) return SD_BUSY;

    int     result    = SD_ERR;
    uint8_t crc_en    = card->io.crc_check;
    uint8_t downshift = 0U;   /* 是否已为重试临时降速 */
    for (uint8_t attempt = 0; attempt <= SD_CRC_RETRY_MAX; ++attempt)
    {
        SD_IO_CS_LOW(card);
        if (_sd_cmd_raw(card, SD_CMD17, _sd_to_addr(card, block_addr), 0x01U) != 0x00U)
        {
            SD_IO_CS_HIGH(card);
            result = SD_ERR;
        }
        else if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK)
        {
            SD_IO_CS_HIGH(card);
            result = SD_TIMEOUT;
        }
        else if (card->io.recv_dma(buf, SD_BLOCK_SIZE) != SD_OK)
        {
            /* 超时时 DMA 已 Abort，补几个时钟让卡结束数据相再抬 CS，避免下次命令失步 */
            for (uint8_t k = 0; k < 2U; ++k) (void)SD_IO_BYTE(card, 0xFFU);
            SD_IO_CS_HIGH(card);
            result = SD_ERR;
        }
        else
        {
            uint8_t crc_h = SD_IO_BYTE(card, 0xFFU), crc_l = SD_IO_BYTE(card, 0xFFU);
            SD_IO_CS_HIGH(card);
            if (!crc_en || (((uint16_t)crc_h << 8) | crc_l) == SD_CRC16(buf, SD_BLOCK_SIZE))
            { result = SD_OK; break; }
            result = SD_CRC_ERR;
        }

        /* 还有重试机会则降速一档（仅降一次），下一轮在低速下重读以恢复信号质量 */
        if (attempt < SD_CRC_RETRY_MAX && !downshift && card->info.speed == SD_SPI_SPEED_HIGH)
        {
            if (SD_Set_Speed_Card(card, SD_SPI_SPEED_LOW) == SD_OK) downshift = 1U;
        }
    }

    if (downshift) (void)SD_Set_Speed_Card(card, SD_SPI_SPEED_HIGH);   /* 恢复高速 */
    _sd_unlock(card);
    return result;
}

//====================================================================
//  SD_Write_Block_Card -- 单块写（CMD24 + DMA + CRC16 发送）
//====================================================================
//  写入后等待卡内部编程完成（_sd_wait_ready，500ms 超时）。
//  若 io.crc_check 非零，自动计算并发送正确的 CRC16。
int SD_Write_Block_Card(SD_Card *card, uint32_t block_addr, const uint8_t *buf)
{
    if (card == NULL || buf == NULL || !card->info.initialized) return SD_PARAM_ERR;
    if (_sd_lock(card) != SD_OK) return SD_BUSY;

    int result;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD24, _sd_to_addr(card, block_addr), 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    (void)SD_IO_BYTE(card, 0xFFU);
    (void)SD_IO_BYTE(card, SD_TOKEN_START_BLOCK);
    if (card->io.send_dma(buf, SD_BLOCK_SIZE) != SD_OK)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    /* 仅在 crc_check 开启时算 CRC，否则发 0xFFFF 占位（SPI 模式卡默认不校验写 CRC） */
    uint16_t crc = card->io.crc_check ? SD_CRC16(buf, SD_BLOCK_SIZE) : 0xFFFFU;
    (void)SD_IO_BYTE(card, (uint8_t)(crc >> 8));
    (void)SD_IO_BYTE(card, (uint8_t)crc);
    uint8_t resp = SD_IO_BYTE(card, 0xFFU);
    if ((resp & SD_DATA_RESP_MASK) != SD_DATA_RESP_ACCEPTED)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    result = _sd_wait_ready(card, 500U);
    SD_IO_CS_HIGH(card);
    _sd_unlock(card);
    return result;
}

//====================================================================
//  SD_Read_Multi_Block_Card -- 多块读（CMD18 + DMA + 每块 CRC 校验）
//====================================================================
//  一次 CMD18 后连续接收 count 个块，块间无需重发命令，比循环单块读更快。
//  读完（或出错）后用 CMD12 停止传输。每块独立校验 CRC。
int SD_Read_Multi_Block_Card(SD_Card *card, uint32_t block_addr, uint8_t *buf, uint32_t count)
{
    if (card == NULL || buf == NULL || count == 0U || !card->info.initialized) return SD_PARAM_ERR;
    if (_sd_lock(card) != SD_OK) return SD_BUSY;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD18, _sd_to_addr(card, block_addr), 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    int result = SD_OK;
    uint8_t *p = buf, crc_en = card->io.crc_check;
    for (uint32_t i = 0; i < count; ++i)
    {
        if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK) { result = SD_TIMEOUT; break; }
        if (card->io.recv_dma(p, SD_BLOCK_SIZE) != SD_OK) { result = SD_ERR; break; }
        uint8_t crc_h = SD_IO_BYTE(card, 0xFFU), crc_l = SD_IO_BYTE(card, 0xFFU);
        if (crc_en && ((((uint16_t)crc_h << 8) | crc_l) != SD_CRC16(p, SD_BLOCK_SIZE)))
        { result = SD_CRC_ERR; break; }
        p += SD_BLOCK_SIZE;
    }
    /* CMD18 为开放式，发 CMD12 时卡可能仍在流式输出：先补 1 个填充字节再发停止命令，
     * 避免把在途数据字节（MSB 可能为 0）误当成 R1。 */
    (void)SD_IO_BYTE(card, 0xFFU);
    (void)_sd_cmd_raw(card, SD_CMD12, 0x00000000U, 0x01U);
    (void)_sd_wait_ready(card, 200U);
    SD_IO_CS_HIGH(card);
    _sd_unlock(card);
    return result;
}

//====================================================================
//  SD_Write_Multi_Block_Card -- 多块写（CMD25 + ACMD23 预擦除 + DMA + CRC16）
//====================================================================
//  在 CMD25 之前先发 ACMD23 预擦除 count 块，卡内部提前准备，缩短等待时间。
//  每块以 0xFC 令牌起始，发完最后一块后以 0xFD 令牌结束。
//  每块数据后附 CRC16。
int SD_Write_Multi_Block_Card(SD_Card *card, uint32_t block_addr, const uint8_t *buf, uint32_t count)
{
    if (card == NULL || buf == NULL || count == 0U || !card->info.initialized) return SD_PARAM_ERR;
    if (_sd_lock(card) != SD_OK) return SD_BUSY;
    uint8_t crc_en = card->io.crc_check;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD55, 0x00000000U, 0x01U) == 0x00U)
        (void)_sd_cmd_raw(card, SD_ACMD23, count, 0x01U);
    if (_sd_cmd_raw(card, SD_CMD25, _sd_to_addr(card, block_addr), 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    int result = SD_OK;
    const uint8_t *p = buf;
    for (uint32_t i = 0; i < count; ++i)
    {
        if (_sd_wait_ready(card, 500U) != SD_OK) { result = SD_TIMEOUT; break; }
        (void)SD_IO_BYTE(card, SD_TOKEN_START_MULTI);
        if (card->io.send_dma(p, SD_BLOCK_SIZE) != SD_OK) { result = SD_ERR; break; }
        uint16_t crc = crc_en ? SD_CRC16(p, SD_BLOCK_SIZE) : 0xFFFFU;
        (void)SD_IO_BYTE(card, (uint8_t)(crc >> 8));
        (void)SD_IO_BYTE(card, (uint8_t)crc);
        if ((SD_IO_BYTE(card, 0xFFU) & SD_DATA_RESP_MASK) != SD_DATA_RESP_ACCEPTED)
        { result = SD_ERR; break; }
        p += SD_BLOCK_SIZE;
    }
    (void)_sd_wait_ready(card, 500U);
    (void)SD_IO_BYTE(card, SD_TOKEN_STOP_TRAN);
    (void)SD_IO_BYTE(card, 0xFFU);
    (void)_sd_wait_ready(card, 500U);
    SD_IO_CS_HIGH(card);
    _sd_unlock(card);
    return result;
}

//====================================================================
//  SD_Erase_Blocks_Card -- 擦除（CMD32/33 + CMD38）
//====================================================================
//  大容量卡擦除可能耗时数秒，内部等待超时为 30 秒。
//  SDSC（字节寻址）和 SDHC/SDXC（块寻址）自动换算。
//  start_block 和 end_block 均为闭区间，end_block >= start_block。
int SD_Erase_Blocks_Card(SD_Card *card, uint32_t start_block, uint32_t end_block)
{
    if (card == NULL || !card->info.initialized || end_block < start_block) return SD_PARAM_ERR;
    if (_sd_lock(card) != SD_OK) return SD_BUSY;
    int status;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD32, _sd_to_addr(card, start_block), 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    if (_sd_cmd_raw(card, SD_CMD33, _sd_to_addr(card, end_block), 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    if (_sd_cmd_raw(card, SD_CMD38, 0x00000000U, 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); _sd_unlock(card); return SD_ERR; }
    status = _sd_wait_ready(card, 30000U);
    SD_IO_CS_HIGH(card);
    _sd_unlock(card);
    return status;
}

//====================================================================
//  SD_Get_Status_Card -- CMD13 读 R2 卡状态
//====================================================================
//  SPI 模式 R2 = 2 字节：第 1 字节为 R1（_sd_cmd_raw 已消耗，作为返回值），
//  第 2 字节为 SPI 专用状态。本函数再读 1 字节即可，返回 (R1<<8)|byte2。
//  可直接与 SD_R2_* 宏做位运算，或用 SD_Decode_Status() 转可读字符串。
int SD_Get_Status_Card(const SD_Card *card, uint16_t *status)
{
    if (card == NULL || status == NULL || !card->info.initialized) return SD_PARAM_ERR;
    SD_IO_CS_LOW(card);
    uint8_t r1 = _sd_cmd_raw(card, SD_CMD13, 0x00000000U, 0x01U);
    if (r1 == SD_R1_NO_RESPONSE) { SD_IO_CS_HIGH(card); return SD_ERR; }
    uint8_t r2b = SD_IO_BYTE(card, 0xFFU);   /* R2 仅 2 字节，再读 1 字节即第二状态字节 */
    *status = (uint16_t)(((uint16_t)r1 << 8) | r2b);
    SD_IO_CS_HIGH(card);
    return SD_OK;
}

//====================================================================
//  SD_Card_IsPresent_Card -- CMD58/OCR 在线检测
//====================================================================
int SD_Card_IsPresent_Card(SD_Card *card)
{
    if (card == NULL || !card->info.initialized || card->busy) return 0;
    SD_IO_CS_LOW(card);
    uint8_t r1 = _sd_cmd_raw(card, SD_CMD58, 0x00000000U, 0x01U);
    if (r1 & 0x80U) { SD_IO_CS_HIGH(card); return 0; }
    uint8_t ocr[4];
    for (uint8_t i = 0; i < 4U; ++i) ocr[i] = SD_IO_BYTE(card, 0xFFU);
    SD_IO_CS_HIGH(card);
    return (ocr[0] & 0x80U) ? 1 : 0;
}

//====================================================================
//  SD_Get_CID_Card -- CMD10 读 CID 16 字节
//====================================================================
//  CID 含制造商 ID、OEM ID、产品名、版本、序列号、制造日期。
//  SD_Init_Card() 内部已读取并存于 card->info.cid_raw，通常无需再次调用。
int SD_Get_CID_Card(const SD_Card *card, uint8_t buf[16])
{
    if (card == NULL || buf == NULL || !card->info.initialized) return SD_PARAM_ERR;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD10, 0x00000000U, 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); return SD_ERR; }
    if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK)
    { SD_IO_CS_HIGH(card); return SD_TIMEOUT; }
    for (uint8_t i = 0; i < 16U; ++i) buf[i] = SD_IO_BYTE(card, 0xFFU);
    (void)SD_IO_BYTE(card, 0xFFU); (void)SD_IO_BYTE(card, 0xFFU);
    SD_IO_CS_HIGH(card);
    return SD_OK;
}

//====================================================================
//  SD_Read_SCR_Card -- ACMD51 读 SCR 8 字节
//====================================================================
//  SCR 含 SD 安全规范版本、总线宽度支持等信息，用于判断卡是否支持更高速度模式。
int SD_Read_SCR_Card(const SD_Card *card, uint8_t scr[8])
{
    if (card == NULL || scr == NULL || !card->info.initialized) return SD_PARAM_ERR;
    SD_IO_CS_LOW(card);
    if (_sd_cmd_raw(card, SD_CMD55, 0x00000000U, 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); return SD_ERR; }
    if (_sd_cmd_raw(card, SD_ACMD51, 0x00000000U, 0x01U) != 0x00U)
    { SD_IO_CS_HIGH(card); return SD_ERR; }
    if (_sd_wait_token(card, SD_TOKEN_START_BLOCK, 200U) != SD_OK)
    { SD_IO_CS_HIGH(card); return SD_TIMEOUT; }
    for (uint8_t i = 0; i < 8U; ++i) scr[i] = SD_IO_BYTE(card, 0xFFU);
    (void)SD_IO_BYTE(card, 0xFFU); (void)SD_IO_BYTE(card, 0xFFU);
    SD_IO_CS_HIGH(card);
    return SD_OK;
}

//====================================================================
//  信息查询
//====================================================================
//  SD_Get_Info_Card：获取卡信息结构体只读指针（card==NULL 返回 NULL）
//  SD_Get_Type_Card：获取卡类型 SD_TYPE_*（card==NULL 返回 SD_TYPE_NONE）

const SD_CardInfo *SD_Get_Info_Card(const SD_Card *card)
{
    return (card != NULL) ? &card->info : NULL;
}

uint8_t SD_Get_Type_Card(const SD_Card *card)
{
    return (card != NULL) ? card->info.type : SD_TYPE_NONE;
}

//====================================================================
//  SD_DeInit_Card -- 反初始化（**平台依赖**）
//====================================================================
//  **平台依赖**：直接调用 STM32 HAL API（HAL_SPI_DeInit、HAL_GPIO_Init）。
//  若使用非 STM32 默认 IO 后端，需自行实现对应的 DeInit 逻辑。
//  关闭 SPI 外设时钟，CS(PB0) 设推挽高电平防浮空漏电，重置 card->info。
void SD_DeInit_Card(SD_Card *card)
{
    if (card == NULL) return;

    /* ---- 平台依赖：STM32 HAL（hspi1 + PB0 CS）---- */

    /* 关闭 SPI1 外设与 DMA 流控 */
    HAL_SPI_DeInit(&hspi1);

    /* CS(PB0) → 推挽高电平输出，防浮空漏电 */
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin   = SD_CS_Pin;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(SD_CS_GPIO_Port, &gpio);
    SD_CS_HIGH();

    /* ---- 平台依赖结束 ---- */

    (void)memset(&card->info, 0x00, sizeof(card->info));
    card->info.type  = SD_TYPE_NONE;
    card->info.speed = SD_SPI_SPEED_NULL;
}

//====================================================================
//  SD_Decode_Status -- R2 原始状态 -> 可读字符串
//====================================================================
//  线程安全：结果写入调用方提供的缓冲区。raw==0 输出 "OK"。
//  各标志位以竖线分隔，如 "OUT_OF_RANGE|WP_VIOLATION"。
//  15 个标志全置位时结果 160 字节，_sd_status_append 的 +2 判定另需余量 →
//  buf_size 需 >=162（建议 192）；不足时静默丢弃放不下的标志，不溢出。

/* 向解码缓冲区追加一个标志字符串，以 '|' 分隔（打嗝其实是） */
static void _sd_status_append(char *buf, uint16_t *pos, uint16_t buf_size, const char *s)
{
    uint16_t n = (uint16_t)strlen(s);
    if (*pos + n + 2U < buf_size)
    {
        (void)memcpy(buf + *pos, s, n);
        buf[*pos + n] = '|';
        *pos += n + 1U;
    }
}

const char *SD_Decode_Status(uint16_t raw, char *buf, uint16_t buf_size)
{
    if (buf == NULL || buf_size == 0U) return "";
    uint16_t pos = 0;

    if (raw == 0U) _sd_status_append(buf, &pos, buf_size, "OK");
    /* 高字节 R1 位 */
    if (raw & SD_R2_R1_PARAM_ERR)     _sd_status_append(buf, &pos, buf_size, "PARAM_ERR");
    if (raw & SD_R2_R1_ADDRESS_ERR)   _sd_status_append(buf, &pos, buf_size, "ADDR_ERR");
    if (raw & SD_R2_R1_ERASE_SEQ_ERR) _sd_status_append(buf, &pos, buf_size, "ERASE_SEQ_ERR");
    if (raw & SD_R2_R1_COM_CRC_ERR)   _sd_status_append(buf, &pos, buf_size, "COM_CRC_ERR");
    if (raw & SD_R2_R1_ILLEGAL_CMD)   _sd_status_append(buf, &pos, buf_size, "ILLEGAL_CMD");
    if (raw & SD_R2_R1_ERASE_RESET)   _sd_status_append(buf, &pos, buf_size, "ERASE_RESET");
    if (raw & SD_R2_R1_IDLE)          _sd_status_append(buf, &pos, buf_size, "IDLE");
    /* 低字节 SPI 专用状态位 */
    if (raw & SD_R2_OUT_OF_RANGE)     _sd_status_append(buf, &pos, buf_size, "OUT_OF_RANGE");
    if (raw & SD_R2_ERASE_PARAM)      _sd_status_append(buf, &pos, buf_size, "ERASE_PARAM");
    if (raw & SD_R2_WP_VIOLATION)     _sd_status_append(buf, &pos, buf_size, "WP_VIOLATION");
    if (raw & SD_R2_CARD_ECC_FAILED)  _sd_status_append(buf, &pos, buf_size, "ECC_FAIL");
    if (raw & SD_R2_CC_ERROR)         _sd_status_append(buf, &pos, buf_size, "CC_ERR");
    if (raw & SD_R2_ERROR)            _sd_status_append(buf, &pos, buf_size, "ERROR");
    if (raw & SD_R2_WP_ERASE_SKIP)    _sd_status_append(buf, &pos, buf_size, "WP_ERASE_SKIP");
    if (raw & SD_R2_CARD_LOCKED)      _sd_status_append(buf, &pos, buf_size, "CARD_LOCKED");

    if (pos > 0U && buf[pos - 1U] == '|') buf[pos - 1U] = '\0'; else buf[0] = '\0';
    return buf;
}

//====================================================================
//  SD_Show_Info_Card -- 查询容量/CID 并显示到 OLED（演示）
//====================================================================
//  若卡未初始化则先初始化，再把卡类型、容量、CID 关键字段渲染到 128x64 OLED。
//  **平台依赖**：依赖 oled.hpp。CID 16 字节布局（大端）：
//    [0]=MID 制造商ID  [1..2]=OID OEM(2 ASCII)  [3..7]=PNM 产品名(5 ASCII)
//    [8]=PRV 版本  [9..12]=PSN 序列号(32位)  [13..14]=MDT 制造日期  [15]=CRC
int SD_Show_Info_Card(SD_Card *card)
{
    if (card == NULL) return SD_PARAM_ERR;

    /* 未初始化则先初始化（已初始化则直接用现有信息，不重复握手） */
    if (!card->info.initialized)
    {
        int t = SD_Init_Card(card);
        if (t <= 0)
        {
            /* 失败时给出明确、可读的原因，避免"无显示"让人误以为死机。
             * 按错误码区分"未插卡/无应答"与"通信或初始化失败"两类常见情形。
             * 每行 <=21 字符（128px/6px），避免超宽被裁剪。 */
            const char *reason;
            switch (t)
            {
                case SD_NO_CARD:   reason = "No card detected"; break;  /* CMD0/CMD8 无应答：多为未插卡或接触不良 */
                case SD_TIMEOUT:   reason = "Init timeout";     break;  /* ACMD41 轮询超时：卡上电慢或异常 */
                case SD_PARAM_ERR: reason = "IO not bound";     break;  /* 回调未绑定（移植问题） */
                default:           reason = "Init error";       break;  /* CMD16/CSD 等被拒 */
            }
            OLED_GRAM_Clear();
            OLED_Show_String("SD Card", "1206", 0, 0);         /* 大字标题，醒目 */
            OLED_Show_String("NOT READY", "1206", 0, 16);
            OLED_Show_String(reason, "0806", 0, 36);           /* 失败原因（已控制宽度） */
            OLED_Show_String("Check card & wiring", "0806", 0, 48);
            OLED_GRAM_Refresh();
            return (t == 0) ? SD_NO_CARD : t;
        }
    }

    const SD_CardInfo *info = &card->info;

    /* 卡类型字符串 */
    const char *type_str;
    switch (info->type)
    {
        case SD_TYPE_V1:   type_str = "SDSC v1"; break;
        case SD_TYPE_V2:   type_str = "SDSC v2"; break;
        case SD_TYPE_V2HC: type_str = "SDHC/XC"; break;
        default:           type_str = "Unknown"; break;
    }

    /* CID：OID(2 ASCII) 与 PNM(5 ASCII) 拷到带结束符的小缓冲，非可打印字符替为 '.' */
    char oid[3], pnm[6];
    for (uint8_t i = 0; i < 2U; ++i)
    {
        uint8_t c = info->cid_raw[1 + i];
        oid[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.';
    }
    oid[2] = '\0';
    for (uint8_t i = 0; i < 5U; ++i)
    {
        uint8_t c = info->cid_raw[3 + i];
        pnm[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.';
    }
    pnm[5] = '\0';

    uint32_t psn = ((uint32_t)info->cid_raw[9]  << 24) | ((uint32_t)info->cid_raw[10] << 16)
                 | ((uint32_t)info->cid_raw[11] <<  8) |  (uint32_t)info->cid_raw[12];

    /* 渲染（128x64，0806 字体 6x8，每行约 21 字符，逐行 8px） */
    OLED_GRAM_Clear();
    OLED_Show_String("SD Card Info", "0806", 0, 0);
    OLED_Printf("0806", 0, 8,  "Type: %s", type_str);
    if (info->capacity_mb >= 1024U)
        OLED_Printf("0806", 0, 16, "Cap : %u.%uGB",
                    (unsigned)(info->capacity_mb / 1024U),
                    (unsigned)((info->capacity_mb % 1024U) * 10U / 1024U));
    else
        OLED_Printf("0806", 0, 16, "Cap : %u MB", (unsigned)info->capacity_mb);
    OLED_Printf("0806", 0, 24, "Blocks: %u", (unsigned)info->block_count);
    OLED_Printf("0806", 0, 32, "MID:0x%02X OID:%s", (unsigned)info->cid_raw[0], oid);
    OLED_Printf("0806", 0, 40, "Name: %s", pnm);
    OLED_Printf("0806", 0, 48, "SN  : 0x%08X", (unsigned)psn);
    OLED_GRAM_Refresh();
    return SD_OK;
}

//====================================================================
//  SD_Self_Test_Card -- 非破坏性自检（保存 -> 测试 -> 还原）
//====================================================================
//  流程：初始化 -> 保存目标块原数据 -> 写入已知图案 ->
//  读回逐字节比对 -> 还原原数据。任何步骤失败均尽力还原原数据。
//  **平台依赖**：通过 OLED（oled.hpp）显示各步骤结果，
//  若不需要 OLED 输出，可注释掉 OLED_* 相关调用行。
//  **RAM 占用**：3×512B=1536B 文件作用域 static 缓冲（避免 1.5KB 栈帧溢出），
//  非重入、单次诊断用。量产构建可 #define SD_ENABLE_SELF_TEST 0 整体裁剪以省下这 1.5KB。
#if SD_ENABLE_SELF_TEST
int SD_Self_Test_Card(SD_Card *card, uint32_t test_block)
{
    static uint8_t wbuf[SD_BLOCK_SIZE];
    static uint8_t rbuf[SD_BLOCK_SIZE];
    static uint8_t save[SD_BLOCK_SIZE];
    OLED_GRAM_Clear();
    OLED_Show_String("SD Self-Test", "0806", 0, 0);
    OLED_GRAM_Refresh();
    int type = SD_Init_Card(card);
    if (type <= 0)
    {
        OLED_Show_String("Init FAIL", "0806", 0, 16);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    OLED_Printf("0806", 0, 16, "Init OK t=%d", type);
    OLED_GRAM_Refresh();
    if (SD_Read_Block_Card(card, test_block, save) != SD_OK)
    {
        OLED_Show_String("Save FAIL", "0806", 0, 32);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    for (uint16_t i = 0; i < SD_BLOCK_SIZE; ++i) wbuf[i] = (uint8_t)(i ^ 0xA5U);
    if (SD_Write_Block_Card(card, test_block, wbuf) != SD_OK)
    {
        (void)SD_Write_Block_Card(card, test_block, save);
        OLED_Show_String("Write FAIL", "0806", 0, 32);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    (void)memset(rbuf, 0x00, SD_BLOCK_SIZE);
    if (SD_Read_Block_Card(card, test_block, rbuf) != SD_OK)
    {
        (void)SD_Write_Block_Card(card, test_block, save);
        OLED_Show_String("Read FAIL", "0806", 0, 32);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    if (memcmp(wbuf, rbuf, SD_BLOCK_SIZE) != 0)
    {
        (void)SD_Write_Block_Card(card, test_block, save);
        OLED_Show_String("Verify FAIL", "0806", 0, 32);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    if (SD_Write_Block_Card(card, test_block, save) != SD_OK)
    {
        OLED_Show_String("Restore FAIL", "0806", 0, 40);
        OLED_GRAM_Refresh();
        return SD_ERR;
    }
    OLED_Show_String("ALL PASS", "1206", 0, 32);
    OLED_GRAM_Refresh();
    return SD_OK;
}
#endif /* SD_ENABLE_SELF_TEST */

/* 旧 SD 动画 UI 已迁移到 Core/function/app_ui.c；驱动层仅保留 SD 协议。 */

//====================================================================
//  SD_Send_Command -- 发送命令帧并读回 R1（向后兼容，使用 g_sd_card）
//====================================================================
//  完成 SPI 命令帧封装：CS 拉低 -> 6字节帧 -> 轮询 R1 -> CS 拉高。
//  CRC 仅对 CMD0/CMD8 必需，其余命令可传 0x01（占位停止位）。

/**
 * @brief 发送 SD 命令帧并读回 R1 应答（以 g_sd_card 的 IO 后端发送）
 * @note  面向调用方的不管理 CS 的公开接口。
 *         完成 SD SPI 命令帧的封装：CS 拉低 → 发送 6 字节命令帧
 *         (0x40|cmd, arg[31:24..7:0], CRC<<1|1) → 轮询读取 R1 应答 → CS 拉高。
 *         CRC 仅对 CMD0/CMD8 必需，其余命令在 SPI 模式默认关闭 CRC 校验，
 *         调用方对普通命令可传 0x01（占位停止位）。
 * @param cmd 命令号（0~63，不含 0x40 起始位）
 * @param arg 32 位命令参数（大端发送）
 * @param crc 7 位 CRC + 停止位（完整字节，如 CMD0=0x95、CMD8=0x87）
 * @retval R1 应答字节；0xFF 表示在重试上限内未收到有效应答
 */
uint8_t SD_Send_Command(uint8_t cmd, uint32_t arg, uint8_t crc)
{
    SD_Card *card = &g_sd_card;
    if (card->io.spi_byte == NULL) SD_Init_Default_IO(card);
    /* 复用 _sd_cmd_raw 的帧封装与 R1 轮询，仅在外层补 CS 管理，避免协议逻辑两处重复 */
    SD_IO_CS_LOW(card);
    uint8_t r1 = _sd_cmd_raw(card, cmd, arg, crc);
    SD_IO_CS_HIGH(card);
    return r1;
}
