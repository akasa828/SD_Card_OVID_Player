#include "oled_stm32_hal.h"

static int hal_write_dma(void *context, uint8_t address, uint8_t control,
                         uint8_t *data, uint16_t size)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter == NULL || adapter->i2c == NULL) return OLED_PORT_NOT_BOUND;
    HAL_StatusTypeDef status = HAL_I2C_Mem_Write_DMA(adapter->i2c, address,
        control, I2C_MEMADD_SIZE_8BIT, data, size);
    if (status == HAL_OK) return OLED_PORT_OK;
    if (status == HAL_BUSY) return OLED_PORT_BUSY;
    if (status == HAL_TIMEOUT) return OLED_PORT_TIMEOUT;
    return OLED_PORT_ERROR;
}

static int hal_abort_dma(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter == NULL || adapter->i2c == NULL) return OLED_PORT_NOT_BOUND;
    if (adapter->i2c->hdmatx == NULL) return OLED_PORT_OK;
    return HAL_DMA_Abort(adapter->i2c->hdmatx) == HAL_OK
        ? OLED_PORT_OK : OLED_PORT_ERROR;
}

static int hal_recover(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter == NULL || adapter->i2c == NULL) return OLED_PORT_NOT_BOUND;
    (void)HAL_I2C_DeInit(adapter->i2c);
    if (adapter->reinitialize == NULL) return OLED_PORT_ERROR;
    adapter->reinitialize(adapter->user_context, adapter->i2c);
    return HAL_I2C_GetState(adapter->i2c) == HAL_I2C_STATE_READY
        ? OLED_PORT_OK : OLED_PORT_ERROR;
}

static uint32_t hal_tick(void *context)
{
    (void)context;
    return HAL_GetTick();
}

static void hal_idle(void *context)
{
    (void)context;
}

static int hal_device_ready(void *context, uint8_t address,
                            uint32_t trials, uint32_t timeout_ms)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter == NULL || adapter->i2c == NULL) return OLED_PORT_NOT_BOUND;
    HAL_StatusTypeDef status = HAL_I2C_IsDeviceReady(adapter->i2c, address,
                                                     trials, timeout_ms);
    if (status == HAL_OK) return OLED_PORT_OK;
    if (status == HAL_BUSY) return OLED_PORT_BUSY;
    if (status == HAL_TIMEOUT) return OLED_PORT_TIMEOUT;
    return OLED_PORT_ERROR;
}

static void hal_success(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter->success != NULL) adapter->success(adapter->user_context);
}

static void hal_failure(void *context, uint8_t timeout_failure)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    if (adapter->failure != NULL)
        adapter->failure(adapter->user_context, timeout_failure);
}

static uint32_t hal_clock(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    return adapter->clock_hz != NULL ? adapter->clock_hz(adapter->user_context) : 0U;
}

static uint32_t hal_errors(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    return adapter->error_count != NULL ? adapter->error_count(adapter->user_context) : 0U;
}

static uint32_t hal_timeouts(void *context)
{
    OLED_STM32_HAL *adapter = (OLED_STM32_HAL *)context;
    return adapter->timeout_count != NULL ? adapter->timeout_count(adapter->user_context) : 0U;
}

int OLED_STM32_HAL_Attach(OLED_STM32_HAL *adapter)
{
    if (adapter == NULL || adapter->i2c == NULL) return OLED_PORT_NOT_BOUND;
    OLED_PortOps ops = {
        .context = adapter,
        .write_dma = hal_write_dma,
        .abort_dma = hal_abort_dma,
        .recover = hal_recover,
        .tick_ms = hal_tick,
        .idle = hal_idle,
        .device_ready = hal_device_ready,
        .on_success = hal_success,
        .on_failure = hal_failure,
        .get_clock_hz = hal_clock,
        .get_error_count = hal_errors,
        .get_timeout_count = hal_timeouts,
    };
    return OLED_BindPort(&ops);
}

void OLED_STM32_HAL_HandleTxComplete(OLED_STM32_HAL *adapter,
                                     I2C_HandleTypeDef *i2c)
{
    if (adapter != NULL && adapter->i2c == i2c) OLED_NotifyTxComplete();
}

void OLED_STM32_HAL_HandleError(OLED_STM32_HAL *adapter,
                                I2C_HandleTypeDef *i2c)
{
    if (adapter != NULL && adapter->i2c == i2c) OLED_NotifyError();
}
