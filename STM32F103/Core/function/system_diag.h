#ifndef SYSTEM_DIAG_H
#define SYSTEM_DIAG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SYSTEM_DIAG_FAULT_MAGIC 0x4641554CUL

typedef enum {
    APP_STATE_BOOT = 0,
    APP_STATE_WAIT_CARD,
    APP_STATE_MOUNT,
    APP_STATE_FREE_SCAN,
    APP_STATE_FILE_SCAN,
    APP_STATE_INFO,
    APP_STATE_LIBRARY,
    APP_STATE_PLAYBACK,
    APP_STATE_DIAGNOSTICS,
    APP_STATE_ERROR
} AppRuntimeState;

typedef struct {
    uint32_t magic, sequence;
    uint32_t stacked_r0, stacked_r1, stacked_r2, stacked_r3, stacked_r12;
    uint32_t stacked_lr, stacked_pc, stacked_xpsr, exc_return;
    uint32_t cfsr, hfsr, dfsr, afsr, mmfar, bfar;
    uint32_t app_state;
    char current_file[32];
    uint32_t checksum;
} SystemFaultRecord;

void SystemDiag_BootInit(void);
void SystemDiag_WatchdogInit(void);
void SystemDiag_FeedWatchdog(void);
void SystemDiag_SetState(AppRuntimeState state);
AppRuntimeState SystemDiag_GetState(void);
void SystemDiag_SetCurrentFile(const char *name);
uint8_t SystemDiag_HasFaultRecord(void);
const SystemFaultRecord *SystemDiag_GetFaultRecord(void);
void SystemDiag_ClearFaultRecord(void);
uint32_t SystemDiag_GetResetFlags(void);
uint32_t SystemDiag_GetStackMargin(void);
uint32_t SystemDiag_GetStaticRamBytes(void);
uint32_t SystemDiag_GetFlashBytes(void);
void SystemDiag_ReportSdError(void);
uint32_t SystemDiag_GetSdErrorCount(void);
uint8_t SystemDiag_WasWatchdogReset(void);
void SystemDiag_HardFaultCapture(uint32_t *stack, uint32_t exc_return) __attribute__((noreturn));

#ifdef __cplusplus
}
#endif
#endif
