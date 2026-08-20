/**
  ******************************************************************************
  * @file    SD_reader.h
  * @author  riochihao
  * @brief   SD SPI 通用驱动 —— 硬件解耦 + 多实例 + CRC 校验 + 自适应时钟
  * @note    内核通过 SD_IO 函数指针抽象所有硬件操作，不依赖特定 MCU/HAL。
  *          SD_Card 句柄支持多卡槽并发。向后兼容的全局 API 使用默认实例 g_sd_card。
  *
  *          命名规范：所有公开 API 以 "SD_" 为前缀，下划线间单词首字母大写。
  *          返回值：核心 API 返回 int（SD_OK=0 成功，负值=错误码）；
  *                  向后兼容包装返回 HAL_StatusTypeDef（映射到 HAL_OK/HAL_ERROR/HAL_TIMEOUT）。
  ******************************************************************************
  */
#ifndef __SD_READER_H
#define __SD_READER_H

#ifdef __cplusplus
extern "C" {
#endif

//========== 头文件 ==============
#include <stdint.h>
#include "main.h"   /* HAL_StatusTypeDef / SPI_HandleTypeDef —— 仅向后兼容包装需要 */

//====================================================================
//  通用返回码（跨平台，不依赖 HAL）
//====================================================================

#define SD_OK          0     /* 成功 */
#define SD_ERR        -1     /* 一般错误 */
#define SD_TIMEOUT    -2     /* 超时 */
#define SD_PARAM_ERR  -3     /* 参数无效 */
#define SD_CRC_ERR    -4     /* CRC 校验失败 */
#define SD_NO_CARD    -5     /* 卡未初始化 */
#define SD_BUSY       -6     /* 句柄正被另一上下文占用（重入保护命中） */

//====================================================================
//  协议宏定义
//====================================================================

/* 单字节 SPI 收发超时（ms）。即使在 ~281kHz 初始化速度下传输 1 字节也远小于 1ms，
   10ms 作为异常保护裕量，正常情况下绝不会触发。 */
#define SD_SPI_TIMEOUT   10U

/**
 * @name SPI 速率档
 * SD_Set_Speed() 的入参，也用于 SD_CardInfo.speed 字段记录当前状态。
 * - SD_SPI_SPEED_LOW： 握手阶段使用，SCK 必须 < 400kHz
 * - SD_SPI_SPEED_HIGH：数据读写使用，SCK = 9MHz（72MHz/8，面包板兼容）
 * - SD_SPI_SPEED_NULL：仅用作初始值，表示"尚未探测硬件速率"，
 *                       不可作为 SD_Set_Speed() 的目标参数
 * @{
 */
#define SD_SPI_SPEED_LOW       0U   /* 低速握手档，< 400kHz */
#define SD_SPI_SPEED_HIGH      1U   /* 高速数据传输档 */
#define SD_SPI_SPEED_NULL      2U   /* 未探测/未知速率 */
/** @} */

/* 分频器寄存器值（写入 SPI_CR1 BR[2:0]） */
#define SD_SPI_PRESCALER_LOW   SPI_BAUDRATEPRESCALER_256   /* 72MHz/256 ≈ 281kHz（握手） */
#define SD_SPI_PRESCALER_HIGH  SPI_BAUDRATEPRESCALER_16    /* 72MHz/16 = 4.5MHz（提速档）。
                                * 面包板若读写出错(花屏/挂载失败)就调回 _32=2.25M；
                                * 焊板/短线稳定可再提 _8=9M。这是帧率的主要旋钮之一。 */

/* 片选控制 —— 向后兼容宏；新代码应使用 SD_IO.cs_low / cs_high 回调 */
#define SD_CS_GPIO_Port   GPIOB
#define SD_CS_Pin         GPIO_PIN_0
#define SD_CS_LOW()       (SD_CS_GPIO_Port->BSRR = (uint32_t)SD_CS_Pin << 16U)
#define SD_CS_HIGH()      (SD_CS_GPIO_Port->BSRR = (uint32_t)SD_CS_Pin)

/**
 * @name R1 应答标志位
 * SD_Send_Command() 或内部 sd_cmd_raw() 返回的 R1 字节中各位含义。
 * @{
 */
#define SD_R1_NO_RESPONSE  0xFFU   /* MISO 持续高电平，总线无应答 */
#define SD_R1_IDLE_STATE   0x01U   /* 卡处于 idle 状态（刚上电或 CMD0 后） */
#define SD_R1_ILLEGAL_CMD  0x04U   /* 卡不支持该命令（用于区分 v1.x / v2+） */
/** @} */

/* 数据层 */
#define SD_BLOCK_SIZE        512U    /* SD 标准扇区/块大小（字节） */
#define SD_CRC_RETRY_MAX     3U     /* CRC 校验失败时最大重试次数 */

/**
 * @name 可配置项（编译期可覆盖）
 * 在包含本头文件前 #define，或在工程编译选项里 -D，即可覆盖默认值。
 * @{
 */
#ifndef SD_ACMD41_TIMEOUT_MS
#define SD_ACMD41_TIMEOUT_MS 2000U  /* ACMD41 上电初始化轮询超时（ms）。SD 规范允许慢卡
                                       至多 ~1s 退出 idle，2s 留足裕量；慢卡可再调大 */
#endif

#ifndef SD_ENABLE_SELF_TEST
#define SD_ENABLE_SELF_TEST  1      /* 1=编译 SD_Self_Test_Card（占 3×512B=1536B .bss）；
                                       0=裁剪，量产可省 1.5KB RAM。详见 SD_Self_Test_Card 文档 */
#endif

#ifndef SD_ENABLE_CMD_CRC
#define SD_ENABLE_CMD_CRC    0      /* 0=不发 CMD59、命令用占位 CRC7（SPI 模式标准稳健做法，
                                       面包板/飞线强烈建议）；卡仍会发数据 CRC16，主机仍可校验
                                       （由 io.crc_check 控制）+ 失败自动降速重读。
                                       1=发 CMD59 开卡端 CRC，命令需完美 CRC7——面包板上易因
                                       信号干扰导致命令/数据被拒，不建议。 */
#endif

/** @} */

/**
 * @name 卡类型
 * SD_Init_Card() 的返回值（正数时）。也存储在 SD_CardInfo.type 中。
 * - SD_TYPE_V1：   SDSC v1.x，字节寻址，不支持 CMD8
 * - SD_TYPE_V2：   SDSC v2+，字节寻址，支持 CMD8 和 HCS
 * - SD_TYPE_V2HC： SDHC/SDXC，块寻址（标准容量 2GB~2TB）
 * @{
 */
#define SD_TYPE_NONE   0x00U   /* 无卡或初始化失败 */
#define SD_TYPE_V1     0x02U   /* SDSC v1.x，字节寻址 */
#define SD_TYPE_V2     0x04U   /* SDSC v2，字节寻址 */
#define SD_TYPE_V2HC   0x06U   /* SDHC/SDXC，块寻址 */
/** @} */

/**
 * @name SD SPI 命令号
 * 所有命令号均不含 0x40 起始位（sd_cmd_raw 内部自动添加）。
 * ACMD 系列需先发 CMD55（APP_CMD）前导，然后发对应命令号。
 * @{
 */
#define SD_CMD0    0U    /* GO_IDLE_STATE      复位进入 idle */
#define SD_CMD8    8U    /* SEND_IF_COND       电压区间/版本探测 */
#define SD_CMD9    9U    /* SEND_CSD           读 CSD 寄存器（含容量、速率信息） */
#define SD_CMD10   10U   /* SEND_CID           读 CID 寄存器（制造商 ID / 序列号） */
#define SD_CMD12   12U   /* STOP_TRANSMISSION  停止多块读 */
#define SD_CMD13   13U   /* SEND_STATUS        读 R2 卡详细状态 */
#define SD_CMD16   16U   /* SET_BLOCKLEN       设置块长度（SDSC 需显式设为 512） */
#define SD_CMD17   17U   /* READ_SINGLE_BLOCK  读单块 */
#define SD_CMD18   18U   /* READ_MULTIPLE_BLOCK 读多块（需 CMD12 停止） */
#define SD_CMD24   24U   /* WRITE_BLOCK        写单块 */
#define SD_CMD25   25U   /* WRITE_MULTIPLE_BLOCK 写多块（以 0xFD 令牌结束） */
#define SD_CMD32   32U   /* ERASE_WR_BLK_START 设置擦除起始地址 */
#define SD_CMD33   33U   /* ERASE_WR_BLK_END   设置擦除结束地址 */
#define SD_CMD38   38U   /* ERASE              执行擦除（耗时可达数秒） */
#define SD_CMD55   55U   /* APP_CMD            ACMD 前导命令 */
#define SD_CMD58   58U   /* READ_OCR           读 OCR 寄存器（判 SDHC） */
#define SD_CMD59   59U   /* CRC_ON_OFF         开/关卡端 CRC 校验 */
#define SD_ACMD23  23U   /* SET_WR_BLK_ERASE_COUNT 预擦除块数（加速多块写） */
#define SD_ACMD41  41U   /* SD_SEND_OP_COND    启动初始化（轮询至 idle 退出） */
#define SD_ACMD51  51U   /* SEND_SCR           读 SCR 寄存器（安全/总线宽度） */
/** @} */

/**
 * @name 数据令牌
 * SD 卡块传输时的起始/结束标志字节。
 * @{
 */
#define SD_TOKEN_START_BLOCK   0xFEU   /* 单块读/写、多块读：数据块起始令牌 */
#define SD_TOKEN_START_MULTI   0xFCU   /* 多块写：每块数据起始令牌 */
#define SD_TOKEN_STOP_TRAN     0xFDU   /* 多块写：结束令牌（发完最后一块后） */
/** @} */

/* 写数据响应 */
#define SD_DATA_RESP_MASK      0x1FU   /* 写响应有效位掩码（低 5 位） */
#define SD_DATA_RESP_ACCEPTED  0x05U   /* 数据被卡接受 */

//====================================================================
//  CMD13 SEND_STATUS —— SPI 模式 R2 应答（16 位）
//  SPI 模式下 R2 = 2 字节：高字节是 R1（与命令应答同布局），低字节是
//  SPI 专用状态位。注意这与 SD 总线模式的 32 位 Card Status 布局不同。
//  SD_Get_Status_Card() 返回 (R1<<8)|byte2，可直接与下列宏做位运算。
//====================================================================

/**
 * @name CMD13 R2 状态位（SPI 模式，16 位）
 * 高字节（bit8~15）= R1：
 * @{
 */
#define SD_R2_R1_IDLE             (1U <<  8)  /* R1.bit0 卡处于 idle */
#define SD_R2_R1_ERASE_RESET      (1U <<  9)  /* R1.bit1 擦除序列被复位 */
#define SD_R2_R1_ILLEGAL_CMD      (1U << 10)  /* R1.bit2 非法命令 */
#define SD_R2_R1_COM_CRC_ERR      (1U << 11)  /* R1.bit3 命令 CRC 错误 */
#define SD_R2_R1_ERASE_SEQ_ERR    (1U << 12)  /* R1.bit4 擦除序列错误 */
#define SD_R2_R1_ADDRESS_ERR      (1U << 13)  /* R1.bit5 地址错误（未对齐） */
#define SD_R2_R1_PARAM_ERR        (1U << 14)  /* R1.bit6 参数错误（越界） */
/* 低字节（bit0~7）= SPI 专用第 2 状态字节： */
#define SD_R2_CARD_LOCKED         (1U <<  0)  /* 卡已锁定 */
#define SD_R2_WP_ERASE_SKIP       (1U <<  1)  /* 写保护擦除跳过 / 锁定解锁失败 */
#define SD_R2_ERROR               (1U <<  2)  /* 通用错误 */
#define SD_R2_CC_ERROR            (1U <<  3)  /* 内部卡控制器错误 */
#define SD_R2_CARD_ECC_FAILED     (1U <<  4)  /* 内部 ECC 失败 */
#define SD_R2_WP_VIOLATION        (1U <<  5)  /* 写保护违规 */
#define SD_R2_ERASE_PARAM         (1U <<  6)  /* 擦除参数错误 */
#define SD_R2_OUT_OF_RANGE        (1U <<  7)  /* 参数越界 / CSD 覆写错误 */
/** @} */

//====================================================================
//  SPI I/O 硬件抽象接口（SD_IO）
//  移植到其他 MCU/平台只需填充此结构体的回调函数，驱动内核无需修改。
//====================================================================

/**
 * @brief SPI I/O 硬件抽象接口
 * @note  所有硬件操作通过函数指针回调完成。回调名中的 "dma" 仅为历史命名，
 *        语义是"同步搬完整块"，后端用 DMA 或轮询均可（默认 STM32 后端用轮询）。
 *        移植步骤：
 *        1. 实现 spi_byte / recv_dma / send_dma / cs_low / cs_high 等回调
 *        2. 填充 SD_IO 结构体
 *        3. 调用 SD_Init_Card(&your_card) 即可
 *        若 io 未绑定，SD_Init_Card 会自动调用 SD_Init_Default_IO 绑定 STM32 HAL。
 */
typedef struct SD_IO {
    /**
     * @brief 单字节 SPI 全双工交换（阻塞式）
     * @note  用于命令/应答/令牌收发。对单字节场景，轮询比 DMA 更快。
     * @param tx 要发送的字节
     * @retval 从机在同一组时钟内返回的字节
     */
    uint8_t (*spi_byte)(uint8_t tx);

    /**
     * @brief 批量接收（用于读块）
     * @note  名字里的 "dma" 是历史遗留：本回调只约定"一次调用搬完 len 字节并同步返回"，
     *        用 DMA 还是轮询由后端自行决定。**默认 STM32 后端是轮询**——实测 SPI+DMA
     *        返回错位/损坏数据，改为单次 HAL_SPI_TransmitReceive 传整块（见
     *        _stm32_recv_dma）。若你的后端确实用 DMA，需在回调内部自行等待完成并处理超时。
     * @param rx  接收缓冲区指针
     * @param len 字节数（通常为 SD_BLOCK_SIZE = 512）
     * @retval SD_OK 成功；负值 = 错误码
     */
    int (*recv_dma)(uint8_t *rx, uint16_t len);

    /**
     * @brief 批量发送（用于写块）
     * @note  同 recv_dma：名称为历史遗留，默认 STM32 后端为轮询实现，语义是同步阻塞。
     * @param tx  发送缓冲区指针（只读）
     * @param len 字节数（通常为 SD_BLOCK_SIZE = 512）
     * @retval SD_OK 成功；负值 = 错误码
     */
    int (*send_dma)(const uint8_t *tx, uint16_t len);

    /** @brief 片选拉低（选中 SD 卡） */
    void (*cs_low)(void);

    /** @brief 片选拉高（释放 SD 卡），实现需在拉高后补 8 个时钟 */
    void (*cs_high)(void);

    /**
     * @brief 设置 SPI 时钟分频
     * @param prescaler_val 分频器寄存器值（如 SPI_BAUDRATEPRESCALER_256）
     * @retval SD_OK 成功；SD_ERR 失败
     */
    int (*set_speed)(uint32_t prescaler_val);

    /**
     * @brief 读取当前 SPI 分频器寄存器值
     * @retval 当前 prescaler 寄存器编码值
     */
    uint32_t (*get_prescaler)(void);

    /**
     * @brief 获取 SPI 所在总线时钟频率（Hz）
     * @note  用于 _sd_detect_speed() 计算实际 SCK
     * @retval 总线时钟频率（Hz）
     */
    uint32_t (*get_bus_clk)(void);

    /**
     * @brief 毫秒级单调时间戳
     * @note  用于超时判断。需单调递增，无符号溢出后回绕是安全的
     *        （所有超时比较均使用差值方式 `(now - start) < timeout`）。
     * @retval 当前毫秒时间戳
     */
    uint32_t (*tick_ms)(void);

    /**
     * @brief CRC 校验开关
     * @note  非零时：读操作会校验尾随的 2 字节 CRC16，不匹配则自动重试；
     *        写操作会计算并发送正确的 CRC16。零时：读跳过校验、写发零值 CRC。
     */
    uint8_t  crc_check;
} SD_IO;

//====================================================================
//  卡信息结构体
//====================================================================

/**
 * @brief SD 卡信息集中管理结构体
 * @note  SD_Init_Card() 成功后填充，可通过 SD_Get_Info_Card() 获取只读指针。
 *        所有卡状态均从此读取，不再使用零散全局变量。
 */
typedef struct SD_CardInfo {
    uint8_t  type;           /**< 卡类型 @ref SD_TYPE_V1 / SD_TYPE_V2 / SD_TYPE_V2HC */
    uint8_t  initialized;    /**< 1 = 就绪可读写；0 = 未初始化 */
    uint8_t  block_addr;     /**< 1 = 块寻址(SDHC/SDXC)；0 = 字节寻址(SDSC) */
    uint8_t  speed;          /**< 当前速率档 @ref SD_SPI_SPEED_LOW / SD_SPI_SPEED_HIGH */
    uint32_t ocr;            /**< CMD58 读到的 OCR 寄存器原始值（含 CCS 位） */
    uint32_t block_count;    /**< 总块数（每块 512B），由 CSD 计算 */
    uint32_t capacity_mb;    /**< 容量（MB），= block_count / 2048 */
    uint8_t  csd_raw[16];    /**< CSD 寄存器原始 16 字节（大端），供上层诊断 */
    uint8_t  cid_raw[16];    /**< CID 寄存器原始 16 字节（大端），含制造商 ID / 序列号 */
} SD_CardInfo;

//====================================================================
//  卡操作句柄（多实例支持）
//====================================================================

/**
 * @brief SD 卡操作句柄
 * @note  每个物理卡槽对应一个句柄实例。IO 回调 + 卡信息两者合一。
 *        使用前先 SD_Init_Card() 完成初始化握手。
 *
 * @warning 本驱动**非重入**：每个句柄的一次事务会跨多次 SPI 收发持续拉低 CS，
 *          期间独占 hspi1 总线。请仅从主循环（单一上下文）调用，
 *          不要从中断里调用任何 SD_* 接口，也不要在一次事务进行中从别处再次进入。
 *
 *          busy 标志保护的覆盖范围（务必按实际情况理解，勿假设全部加锁）：
 *          - **有锁**：SD_Read_Block_Card / SD_Write_Block_Card /
 *            SD_Read_Multi_Block_Card / SD_Write_Multi_Block_Card /
 *            SD_Erase_Blocks_Card。并发进入立即返回 SD_BUSY。
 *          - **无锁**：SD_Get_Status_Card / SD_Card_IsPresent_Card /
 *            SD_Get_CID_Card / SD_Read_SCR_Card
 *            （签名为 const SD_Card*，无法置位 busy）；以及组合型接口
 *            SD_Init_Card / SD_Self_Test_Card / SD_Show_Info_Card。
 *            这些必须由调用方保证单上下文使用——在一次带锁事务进行中调用它们
 *            会交错 SPI 帧并破坏总线。
 */
typedef struct SD_Card {
    SD_IO       io;          /**< 硬件抽象接口（嵌入，避免二次解引用） */
    SD_CardInfo info;        /**< 卡信息 */
    volatile uint8_t busy;   /**< 重入保护标志：叶子事务进行中置 1（内部使用，勿手动改） */
} SD_Card;

/** @brief 默认全局实例（STM32 HAL 预绑定），向后兼容 API 使用此实例 */
extern SD_Card g_sd_card;

//====================================================================
//  初始化
//====================================================================

/**
 * @brief 用 STM32 HAL 默认回调填充 SD_IO（hspi1 + PB0 CS）
 * @note  仅在 STM32 平台可用。其他平台需自行填充 SD_IO。
 *         若 SD_Init_Card() 检测到 io.spi_byte 为 NULL 会主动调用本函数，
 *         因此多数情况下用户无需手动调用。
 * @param card SD 卡句柄指针（不可为 NULL）
 */
void SD_Init_Default_IO(SD_Card *card);

/**
 * @brief 初始化 SD 卡（完整上电握手协议）
 * @note  流程：探测/确保低速(<400kHz) → ≥74 空闲时钟 → CMD0 软复位 →
 *         CMD8 版本探测 → ACMD41 轮询启动 → CMD58 读 OCR 判 SDHC →
 *         CMD16 设块长（非 SDHC）→ CMD9 读 CSD 算容量 →
 *         CMD10 读 CID → 切高速时钟。所有结果写入 card->info。
 * @param card SD 卡句柄指针（不可为 NULL，io 可为空则自动绑定 STM32 HAL）
 * @retval 正数 = 卡类型 @ref SD_TYPE_V1 / SD_TYPE_V2 / SD_TYPE_V2HC
 * @retval SD_NO_CARD  卡无应答或不兼容
 * @retval SD_TIMEOUT  ACMD41 轮询超时
 * @retval SD_PARAM_ERR card 为 NULL
 */
int SD_Init_Card(SD_Card *card);

/**
 * @brief 反初始化 SD 卡模块（释放 SPI / DMA / GPIO 资源）
 * @note  用于低功耗场景：关闭 SPI 外设时钟，CS 脚设推挽高电平输出防浮空漏电，
 *         DMA 通道复位，card->info 重置为未就绪。再次使用需重新调用 SD_Init_Card()。
 * @param card SD 卡句柄指针（不可为 NULL）
 */
void SD_DeInit_Card(SD_Card *card);

//====================================================================
//  速率控制
//====================================================================

/**
 * @brief 动态调整 SPI 时钟速率档
 * @note  握手阶段必须 <400kHz，进入 SPI 模式后应切高速。
 *         内部通过改写 SPI prescaler 寄存器并重初始化外设实现。
 *         若已在目标速率则跳过重初始化（零开销）。
 * @param card  SD 卡句柄指针（不可为 NULL）
 * @param speed 目标速率档，只能是 @ref SD_SPI_SPEED_LOW 或 @ref SD_SPI_SPEED_HIGH
 *              （传入 SD_SPI_SPEED_NULL 会返回 SD_PARAM_ERR）
 * @retval SD_OK 成功
 * @retval SD_PARAM_ERR card 为 NULL 或 speed 非法
 * @retval SD_ERR SPI 重初始化失败（已尽力恢复原分频）
 */
int SD_Set_Speed_Card(SD_Card *card, uint8_t speed);

//====================================================================
//  数据读写（单块）
//====================================================================

/**
 * @brief 读取一个 512 字节数据块（CMD17 + DMA + CRC 校验 + 自动重试）
 * @note  若 io.crc_check 非零，读取时会校验尾随 2 字节 CRC16-CCITT。
 *         CRC 不匹配时自动重试，最多 @ref SD_CRC_RETRY_MAX 次。
 *         全部失败返回 SD_CRC_ERR。重试期间会尝试降速→提速以恢复信号质量。
 * @param card       SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param block_addr 块地址（SDHC 为块号，SDSC 内部自动换算为字节地址）
 * @param buf        接收缓冲区指针，长度需 >= 512 字节
 * @retval SD_OK        读取成功且 CRC 校验通过（或 CRC 关闭）
 * @retval SD_PARAM_ERR card/buf 为 NULL 或卡未初始化
 * @retval SD_TIMEOUT   等待数据令牌超时
 * @retval SD_CRC_ERR   重试次数耗尽，CRC 仍不匹配
 * @retval SD_ERR       CMD17 被拒或 DMA 传输失败
 */
int SD_Read_Block_Card(SD_Card *card, uint32_t block_addr, uint8_t *buf);

/**
 * @brief 写入一个 512 字节数据块（CMD24 + DMA + CRC16 发送）
 * @note  写入后等待卡内部编程完成（sd_wait_ready，500ms 超时）。
 *         若 io.crc_check 非零，自动计算并发送正确的 CRC16。
 * @param card       SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param block_addr 块地址（SDHC 为块号，SDSC 内部自动换算为字节地址）
 * @param buf        发送缓冲区指针，长度需 >= 512 字节
 * @retval SD_OK        写入成功
 * @retval SD_PARAM_ERR card/buf 为 NULL 或卡未初始化
 * @retval SD_TIMEOUT   等待卡空闲超时
 * @retval SD_ERR       CMD24 被拒、DMA 失败或数据响应异常
 */
int SD_Write_Block_Card(SD_Card *card, uint32_t block_addr, const uint8_t *buf);

//====================================================================
//  数据读写（多块）
//====================================================================

/**
 * @brief 连续读取多个 512 字节数据块（CMD18 + DMA + 每块 CRC 校验）
 * @note  一次 CMD18 后连续接收 count 个块，块间无需重发命令，比循环单块读更快。
 *         读完（或出错）后用 CMD12 停止传输。每块独立校验 CRC。
 * @param card       SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param block_addr 起始块地址（SDHC 为块号，SDSC 内部自动换算为字节地址）
 * @param buf        接收缓冲区指针，长度需 >= count * 512
 * @param count      要读取的块数（>= 1）
 * @retval SD_OK        全部读取成功
 * @retval SD_PARAM_ERR card/buf 为 NULL、count 为 0 或卡未初始化
 * @retval SD_TIMEOUT   等待某块数据令牌超时
 * @retval SD_CRC_ERR   某块 CRC 校验不匹配
 * @retval SD_ERR       CMD18 被拒或 DMA 传输失败
 */
int SD_Read_Multi_Block_Card(SD_Card *card, uint32_t block_addr,
                             uint8_t *buf, uint32_t count);

/**
 * @brief 连续写入多个 512 字节数据块（CMD25 + ACMD23 预擦除 + DMA + CRC16）
 * @note  在 CMD25 之前先发 ACMD23 预擦除 count 块，卡内部提前准备，显著缩短等待时间。
 *         每块以 0xFC 令牌起始，发完最后一块后以 0xFD 令牌结束。
 *         每块数据后附 CRC16。
 * @param card       SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param block_addr 起始块地址（SDHC 为块号，SDSC 内部自动换算为字节地址）
 * @param buf        发送缓冲区指针，长度需 >= count * 512
 * @param count      要写入的块数（>= 1）
 * @retval SD_OK        全部写入成功
 * @retval SD_PARAM_ERR card/buf 为 NULL、count 为 0 或卡未初始化
 * @retval SD_TIMEOUT   等待某块卡就绪超时
 * @retval SD_ERR       CMD25 被拒、DMA 失败或数据响应异常
 */
int SD_Write_Multi_Block_Card(SD_Card *card, uint32_t block_addr,
                              const uint8_t *buf, uint32_t count);

//====================================================================
//  擦除
//====================================================================

/**
 * @brief 擦除指定范围的块（CMD32/33 设地址 + CMD38 执行擦除）
 * @note  大容量卡擦除可能耗时数秒，内部 sd_wait_ready 超时为 30 秒。
 *         SDSC（字节寻址）和 SDHC/SDXC（块寻址）自动通过 sd_to_addr 换算。
 *         传入参数为块号（统一接口），start_block 和 end_block 均为闭区间。
 * @param card        SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param start_block 起始块地址（块号，含）
 * @param end_block   结束块地址（块号，含），必须 >= start_block
 * @retval SD_OK        擦除成功
 * @retval SD_PARAM_ERR card 为 NULL、卡未初始化或 end_block < start_block
 * @retval SD_TIMEOUT   擦除超时（30 秒）
 * @retval SD_ERR       CMD32/33/38 被拒
 */
int SD_Erase_Blocks_Card(SD_Card *card, uint32_t start_block, uint32_t end_block);

//====================================================================
//  状态查询与诊断
//====================================================================

/**
 * @brief 读取卡状态寄存器（CMD13 SEND_STATUS）
 * @note  SPI 模式返回 R2 格式：卡先发 1 字节 R1（最高位为 0），再发 1 字节 SPI 状态。
 *         本函数返回的 16 位字 = (R1 << 8) | 第二状态字节，
 *         可直接与 @ref SD_R2_WP_VIOLATION 等宏做位运算。
 *         （注意：这与 SD 总线模式的 32 位 Card Status 布局不同。）
 * @warning **无 busy 锁**（const 句柄无法置位标志）。不可与带锁的读写事务并发，
 *          也不可从中断调用。详见 @ref SD_Card 的 warning。
 * @param card   SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param status [out] 16 位卡状态原始值（不可为 NULL）
 * @retval SD_OK        读取成功
 * @retval SD_PARAM_ERR card/status 为 NULL 或卡未初始化
 * @retval SD_ERR       CMD13 无应答
 */
int SD_Get_Status_Card(const SD_Card *card, uint16_t *status);

/**
 * @brief 使用 CMD58/OCR 进行只读在线检测
 * @note  不修改 initialized 或其他卡信息；仅可在单一主循环中调用。
 * @retval 1 卡在线且 OCR power-up status 有效
 * @retval 0 无卡、未初始化或无有效应答
 */
int SD_Card_IsPresent_Card(SD_Card *card);

/**
 * @brief 读取 CID 寄存器 16 字节（CMD10）
 * @note  CID 包含制造商 ID（MID）、OEM/应用 ID（OID）、产品名称（PNM）、
 *         产品版本（PRV）、序列号（PSN）、制造日期（MDT）等信息。
 *         SD_Init_Card() 内部已读取并存于 card->info.cid_raw，通常无需再次调用。
 * @warning **无 busy 锁**（const 句柄无法置位标志）。不可与带锁的读写事务并发。
 * @param card SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param buf  [out] 16 字节接收缓冲区（不可为 NULL）
 * @retval SD_OK      读取成功
 * @retval SD_PARAM_ERR card/buf 为 NULL 或卡未初始化
 * @retval SD_TIMEOUT 等待 CID 数据令牌超时
 * @retval SD_ERR     CMD10 被拒
 */
int SD_Get_CID_Card(const SD_Card *card, uint8_t buf[16]);

/**
 * @brief 读取 SCR 寄存器 8 字节（ACMD51）
 * @note  SCR 包含 SD 安全规范版本、总线宽度支持、SD 物理层版本等关键信息，
 *         可用于判断卡是否支持更高速度模式。需先发 CMD55 前导。
 * @warning **无 busy 锁**（const 句柄无法置位标志）。不可与带锁的读写事务并发。
 * @param card SD 卡句柄指针（不可为 NULL，需已初始化）
 * @param scr  [out] 8 字节接收缓冲区（不可为 NULL）
 * @retval SD_OK      读取成功
 * @retval SD_PARAM_ERR card/scr 为 NULL 或卡未初始化
 * @retval SD_TIMEOUT 等待 SCR 数据令牌超时
 * @retval SD_ERR     CMD55 或 ACMD51 被拒
 */
int SD_Read_SCR_Card(const SD_Card *card, uint8_t scr[8]);

/**
 * @brief 将 CMD13 R2 原始状态解码为可读字符串
 * @note  线程安全：结果写入调用方提供的缓冲区。原始值为 0 时输出 "OK"。
 *         各标志位以竖线 "|" 分隔，如 "OUT_OF_RANGE|WP_VIOLATION"。
 *         缓冲不足时按内部保护静默丢弃放不下的标志（不会溢出，但会缺项）。
 * @param status_raw CMD13 返回的 16 位 SPI R2 状态字（(R1<<8)|byte2）
 * @param buf        [out] 输出缓冲区。全部 15 个标志位同时置位时结果占 160 字节，
 *                   内部追加保护另需 2 字节判定余量 → 需 >= 162，建议给 192。
 * @param buf_size   缓冲区大小（字节）
 * @retval buf 指针（同入参），便于 printf 直接使用
 */
const char *SD_Decode_Status(uint16_t status_raw, char *buf, uint16_t buf_size);

//====================================================================
//  信息查询
//====================================================================

/**
 * @brief 获取卡信息结构体只读指针
 * @param card SD 卡句柄指针
 * @retval 指向内部 SD_CardInfo 的常量指针；card 为 NULL 时返回 NULL
 */
const SD_CardInfo *SD_Get_Info_Card(const SD_Card *card);

/**
 * @brief 获取已初始化的卡类型
 * @param card SD 卡句柄指针
 * @retval @ref SD_TYPE_NONE / SD_TYPE_V1 / SD_TYPE_V2 / SD_TYPE_V2HC
 */
uint8_t SD_Get_Type_Card(const SD_Card *card);

//====================================================================
//  CRC16 工具
//====================================================================

/**
 * @brief 计算 CRC16-CCITT（XMODEM，多项式 0x1021，初值 0x0000）
 * @note  参照 SD 物理层规范 §4.5。每 512 字节数据块后跟 2 字节 CRC16（大端）。
 *        仅用于数据块的完整性校验，不用于命令 CRC7。
 * @param data 数据指针
 * @param len  数据长度（字节）
 * @retval 16 位 CRC 值
 */
uint16_t SD_CRC16(const uint8_t *data, uint16_t len);

//====================================================================
//  演示
//====================================================================

/**
 * @brief 查询卡容量/CID 并显示到 OLED（演示用）
 * @note  若卡未初始化会先调用 SD_Init_Card()。显示卡类型、容量、总块数、
 *         制造商 ID(MID)、OEM ID(OID)、产品名(PNM)、序列号(PSN)。
 *         **平台依赖**：依赖 oled.hpp。
 * @param card SD 卡句柄指针（不可为 NULL）
 * @retval SD_OK      显示成功
 * @retval SD_NO_CARD 初始化失败（无卡/不兼容）
 * @retval 其他负值   初始化错误码
 */
int SD_Show_Info_Card(SD_Card *card);

//====================================================================
//  自检
//====================================================================

/**
 * @brief SD 卡读写自检（非破坏性：保存 → 测试 → 还原）
 * @note  流程：初始化（含自动切高速时钟）→ 保存目标块原数据 → 写入已知图案 →
 *         读回逐字节比对 → 还原原数据。
 *         任何步骤失败均尽力还原原数据，避免残留测试图案。
 *         自检过程通过 OLED（oled.hpp）显示各步骤结果。
 * @param card       SD 卡句柄指针（不可为 NULL）
 * @param test_block 用于读写测试的块地址（建议选远离文件系统常用区的块号，如 8192）
 * @retval SD_OK 全部通过
 * @retval 负值  某一步失败（Init/Save/Write/Read/Verify/Restore 对应错误码）
 *
 * @note  仅当 SD_ENABLE_SELF_TEST != 0 时编译（默认开）。量产可置 0 裁剪以省 1.5KB RAM。
 */
#if SD_ENABLE_SELF_TEST
int SD_Self_Test_Card(SD_Card *card, uint32_t test_block);
#endif

//====================================================================
//  向后兼容 API（静态内联包装，使用全局 g_sd_card）
//  以下函数签名与旧版驱动完全兼容，已有业务代码无需修改。
//  返回值映射：SD_OK → HAL_OK, SD_TIMEOUT → HAL_TIMEOUT, 其余 → HAL_ERROR
//====================================================================

/**
 * @brief 初始化 SD 卡（兼容旧版接口）
 * @note  等价于 SD_Init_Card(&g_sd_card)，返回值映射为卡类型。
 * @retval 正数 = @ref SD_TYPE_*；SD_TYPE_NONE(0) = 失败
 */
static inline uint8_t SD_Init(void)
{
    int ret = SD_Init_Card(&g_sd_card);
    return (ret > 0) ? (uint8_t)ret : SD_TYPE_NONE;
}

/** @brief 读取单块（兼容旧版，等价于 SD_Read_Block_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Read_Block(uint32_t block_addr, uint8_t *buf)
{
    int ret = SD_Read_Block_Card(&g_sd_card, block_addr, buf);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 写入单块（兼容旧版，等价于 SD_Write_Block_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Write_Block(uint32_t block_addr, const uint8_t *buf)
{
    int ret = SD_Write_Block_Card(&g_sd_card, block_addr, buf);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 多块读（兼容旧版，等价于 SD_Read_Multi_Block_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Read_Multi_Block(uint32_t block_addr,
                                                     uint8_t *buf, uint32_t count)
{
    int ret = SD_Read_Multi_Block_Card(&g_sd_card, block_addr, buf, count);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 多块写（兼容旧版，等价于 SD_Write_Multi_Block_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Write_Multi_Block(uint32_t block_addr,
                                                      const uint8_t *buf, uint32_t count)
{
    int ret = SD_Write_Multi_Block_Card(&g_sd_card, block_addr, buf, count);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 擦除（兼容旧版，等价于 SD_Erase_Blocks_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Erase_Blocks(uint32_t start_block, uint32_t end_block)
{
    int ret = SD_Erase_Blocks_Card(&g_sd_card, start_block, end_block);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 读卡状态（兼容旧版，等价于 SD_Get_Status_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Get_Status(uint16_t *status)
{
    int ret = SD_Get_Status_Card(&g_sd_card, status);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 读 CID（兼容旧版，等价于 SD_Get_CID_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Get_CID(uint8_t buf[16])
{
    int ret = SD_Get_CID_Card(&g_sd_card, buf);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}

/** @brief 设速率（兼容旧版，等价于 SD_Set_Speed_Card(&g_sd_card, ...)） */
static inline HAL_StatusTypeDef SD_Set_Speed(uint8_t speed)
{
    int ret = SD_Set_Speed_Card(&g_sd_card, speed);
    return (ret == SD_OK) ? HAL_OK : HAL_ERROR;
}

/** @brief 获取卡信息（兼容旧版，等价于 SD_Get_Info_Card(&g_sd_card)） */
static inline const SD_CardInfo *SD_Get_Info(void)
{
    return SD_Get_Info_Card(&g_sd_card);
}

/** @brief 获取卡类型（兼容旧版，等价于 SD_Get_Type_Card(&g_sd_card)） */
static inline uint8_t SD_Get_Type(void)
{
    return SD_Get_Type_Card(&g_sd_card);
}

/** @brief 反初始化（兼容旧版，等价于 SD_DeInit_Card(&g_sd_card)） */
static inline void SD_DeInit(void)
{
    SD_DeInit_Card(&g_sd_card);
}

/** @brief 自检（兼容旧版，等价于 SD_Self_Test_Card(&g_sd_card, ...)） */
#if SD_ENABLE_SELF_TEST
static inline HAL_StatusTypeDef SD_Self_Test(uint32_t test_block)
{
    int ret = SD_Self_Test_Card(&g_sd_card, test_block);
    return (ret == SD_OK) ? HAL_OK : ((ret == SD_TIMEOUT) ? HAL_TIMEOUT : HAL_ERROR);
}
#endif

/** @brief 显示卡信息到 OLED（兼容旧版，等价于 SD_Show_Info_Card(&g_sd_card)） */
static inline HAL_StatusTypeDef SD_Show_Info(void)
{
    int ret = SD_Show_Info_Card(&g_sd_card);
    return (ret == SD_OK) ? HAL_OK : HAL_ERROR;
}

/**
 * @brief 发送 SD 命令帧并读回 R1 应答（兼容旧版）
 * @note  完成 SD SPI 命令帧的封装：CS 拉低 → 发送 6 字节命令帧
 *         (0x40|cmd, arg[31:24..7:0], CRC<<1|1) → 轮询读取 R1 应答 → CS 拉高。
 *         CRC 仅对 CMD0/CMD8 必需，其余命令在 SPI 模式默认关闭 CRC 校验，
 *         调用方对普通命令可传 0x01（占位停止位）。
 * @param cmd 命令号（0~63，不含 0x40 起始位）
 * @param arg 32 位命令参数（大端发送）
 * @param crc 7 位 CRC + 停止位（完整字节，如 CMD0=0x95、CMD8=0x87）
 * @retval R1 应答字节；0xFF 表示在重试上限内未收到有效应答
 */
uint8_t SD_Send_Command(uint8_t cmd, uint32_t arg, uint8_t crc);

#ifdef __cplusplus
}
#endif

#endif /* __SD_READER_H */
