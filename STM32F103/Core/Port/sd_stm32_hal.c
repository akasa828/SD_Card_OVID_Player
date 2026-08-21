#include <string.h>
#include "sd_stm32_hal.h"

static uint32_t spi_timeout(uint16_t len) { return (uint32_t)len / 2U + 100U; }

static uint8_t io_byte(void *context, uint8_t tx)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    uint8_t rx = 0xFFU;
    if (adapter == NULL || adapter->spi == NULL) return 0xFFU;
    if (HAL_SPI_TransmitReceive(adapter->spi, &tx, &rx, 1U,
                                SD_SPI_TIMEOUT) != HAL_OK) return 0xFFU;
    return rx;
}

static int io_receive(void *context, uint8_t *rx, uint16_t len)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    if (adapter == NULL || adapter->spi == NULL || rx == NULL || len == 0U)
        return SD_PARAM_ERR;
    (void)memset(rx, 0xFF, len);
    return HAL_SPI_TransmitReceive(adapter->spi, rx, rx, len,
        spi_timeout(len)) == HAL_OK ? SD_OK : SD_ERR;
}

static int io_send(void *context, const uint8_t *tx, uint16_t len)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    if (adapter == NULL || adapter->spi == NULL || tx == NULL || len == 0U)
        return SD_PARAM_ERR;
    return HAL_SPI_Transmit(adapter->spi, (uint8_t *)tx, len,
        spi_timeout(len)) == HAL_OK ? SD_OK : SD_ERR;
}

static void io_cs_low(void *context)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    HAL_GPIO_WritePin(adapter->cs_port, adapter->cs_pin, GPIO_PIN_RESET);
}

static void io_cs_high(void *context)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    HAL_GPIO_WritePin(adapter->cs_port, adapter->cs_pin, GPIO_PIN_SET);
    (void)io_byte(context, 0xFFU);
}

static int io_set_speed(void *context, uint8_t speed)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    if (adapter == NULL || adapter->spi == NULL) return SD_PARAM_ERR;
    if (HAL_SPI_GetState(adapter->spi) != HAL_SPI_STATE_READY) return SD_BUSY;
    uint32_t next = speed == SD_SPI_SPEED_HIGH
        ? adapter->high_prescaler : adapter->low_prescaler;
    uint32_t previous = adapter->spi->Init.BaudRatePrescaler;
    adapter->spi->Init.BaudRatePrescaler = next;
    if (HAL_SPI_Init(adapter->spi) == HAL_OK) return SD_OK;
    adapter->spi->Init.BaudRatePrescaler = previous;
    (void)HAL_SPI_Init(adapter->spi);
    return SD_ERR;
}

static uint32_t prescaler_divider(uint32_t value)
{
    switch (value) {
        case SPI_BAUDRATEPRESCALER_2: return 2U;
        case SPI_BAUDRATEPRESCALER_4: return 4U;
        case SPI_BAUDRATEPRESCALER_8: return 8U;
        case SPI_BAUDRATEPRESCALER_16: return 16U;
        case SPI_BAUDRATEPRESCALER_32: return 32U;
        case SPI_BAUDRATEPRESCALER_64: return 64U;
        case SPI_BAUDRATEPRESCALER_128: return 128U;
        default: return 256U;
    }
}

static uint32_t io_sck_hz(void *context)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    uint32_t bus;
    if (adapter->bus_clock_hz != NULL)
        bus = adapter->bus_clock_hz(adapter->user_context, adapter->spi);
    else
        bus = adapter->spi->Instance == SPI1
            ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
    return bus / prescaler_divider(adapter->spi->Init.BaudRatePrescaler);
}

static uint32_t io_tick(void *context) { (void)context; return HAL_GetTick(); }

static void io_deinit(void *context)
{
    SD_STM32_HAL *adapter = (SD_STM32_HAL *)context;
    if (adapter == NULL || adapter->spi == NULL) return;
    (void)HAL_SPI_DeInit(adapter->spi);
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = adapter->cs_pin;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(adapter->cs_port, &gpio);
    HAL_GPIO_WritePin(adapter->cs_port, adapter->cs_pin, GPIO_PIN_SET);
}

static uint32_t io_enter_critical(void *context)
{
    (void)context;
    uint32_t state = __get_PRIMASK();
    __disable_irq();
    return state;
}

static void io_exit_critical(void *context, uint32_t state)
{
    (void)context;
    if (state == 0U) __enable_irq();
}

int SD_STM32_HAL_Attach(SD_Card *card, SD_STM32_HAL *adapter)
{
    if (card == NULL || adapter == NULL || adapter->spi == NULL ||
        adapter->cs_port == NULL || adapter->cs_pin == 0U) return SD_PARAM_ERR;
    SD_IO io = {
        .context = adapter,
        .spi_byte = io_byte,
        .receive = io_receive,
        .send = io_send,
        .cs_low = io_cs_low,
        .cs_high = io_cs_high,
        .set_speed = io_set_speed,
        .get_sck_hz = io_sck_hz,
        .tick_ms = io_tick,
        .deinit = io_deinit,
        .enter_critical = io_enter_critical,
        .exit_critical = io_exit_critical,
        .crc_check = 1U,
    };
    return SD_Card_BindIO(card, &io);
}
