#ifndef OLED_PORT_H
#define OLED_PORT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    OLED_PORT_OK = 0,
    OLED_PORT_ERROR = -1,
    OLED_PORT_BUSY = -2,
    OLED_PORT_TIMEOUT = -3,
    OLED_PORT_NOT_BOUND = -4
};

typedef struct {
    void *context;
    int (*write_dma)(void *context, uint8_t address, uint8_t control,
                     uint8_t *data, uint16_t size);
    int (*abort_dma)(void *context);
    int (*recover)(void *context);
    uint32_t (*tick_ms)(void *context);
    void (*idle)(void *context);
    int (*device_ready)(void *context, uint8_t address,
                        uint32_t trials, uint32_t timeout_ms);
    void (*on_success)(void *context);
    void (*on_failure)(void *context, uint8_t timeout_failure);
    uint32_t (*get_clock_hz)(void *context);
    uint32_t (*get_error_count)(void *context);
    uint32_t (*get_timeout_count)(void *context);
} OLED_PortOps;

int OLED_BindPort(const OLED_PortOps *ops);
void OLED_NotifyTxComplete(void);
void OLED_NotifyError(void);

#ifdef __cplusplus
}
#endif

#endif
