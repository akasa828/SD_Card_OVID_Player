#ifndef SD_READER_COMPAT_H
#define SD_READER_COMPAT_H

#include "stm32f1xx_hal.h"
#include "SD_reader.h"

static inline uint8_t SD_Init(void)
{
    int result = SD_Init_Card(&g_sd_card);
    return result > 0 ? (uint8_t)result : SD_TYPE_NONE;
}

static inline HAL_StatusTypeDef SD_Read_Block(uint32_t block, uint8_t *buffer)
{
    int result = SD_Read_Block_Card(&g_sd_card, block, buffer);
    return result == SD_OK ? HAL_OK
        : (result == SD_TIMEOUT ? HAL_TIMEOUT : HAL_ERROR);
}

static inline HAL_StatusTypeDef SD_Write_Block(uint32_t block, const uint8_t *buffer)
{
    int result = SD_Write_Block_Card(&g_sd_card, block, buffer);
    return result == SD_OK ? HAL_OK
        : (result == SD_TIMEOUT ? HAL_TIMEOUT : HAL_ERROR);
}

static inline void SD_DeInit(void) { SD_DeInit_Card(&g_sd_card); }

#endif
