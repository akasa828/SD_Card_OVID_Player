#ifndef OLED_STM32_HAL_H
#define OLED_STM32_HAL_H

#include "stm32f1xx_hal.h"
#include "oled_port.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    I2C_HandleTypeDef *i2c;
    void *user_context;
    void (*reinitialize)(void *user_context, I2C_HandleTypeDef *i2c);
    void (*success)(void *user_context);
    void (*failure)(void *user_context, uint8_t timeout_failure);
    uint32_t (*clock_hz)(void *user_context);
    uint32_t (*error_count)(void *user_context);
    uint32_t (*timeout_count)(void *user_context);
} OLED_STM32_HAL;

int OLED_STM32_HAL_Attach(OLED_STM32_HAL *adapter);
void OLED_STM32_HAL_HandleTxComplete(OLED_STM32_HAL *adapter,
                                     I2C_HandleTypeDef *i2c);
void OLED_STM32_HAL_HandleError(OLED_STM32_HAL *adapter,
                                I2C_HandleTypeDef *i2c);

#ifdef __cplusplus
}
#endif

#endif
