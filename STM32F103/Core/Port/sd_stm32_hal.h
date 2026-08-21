#ifndef SD_STM32_HAL_H
#define SD_STM32_HAL_H

#include "stm32f1xx_hal.h"
#include "SD_reader.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    SPI_HandleTypeDef *spi;
    GPIO_TypeDef *cs_port;
    uint16_t cs_pin;
    uint32_t low_prescaler;
    uint32_t high_prescaler;
    uint32_t (*bus_clock_hz)(void *user_context, SPI_HandleTypeDef *spi);
    void *user_context;
} SD_STM32_HAL;

int SD_STM32_HAL_Attach(SD_Card *card, SD_STM32_HAL *adapter);

#ifdef __cplusplus
}
#endif

#endif
