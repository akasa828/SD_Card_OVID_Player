#include <stdio.h>
#include <string.h>
#include "main.h"
#include "system_diag.h"

__attribute__((section(".noinit.system_fault"), used, aligned(4)))
static volatile SystemFaultRecord s_fault_record;

static volatile AppRuntimeState s_app_state = APP_STATE_BOOT;
static char s_current_file[32];
static uint32_t s_reset_flags;
static uint8_t s_watchdog_started;
static SystemFaultRecord s_boot_fault;
static uint8_t s_boot_fault_valid;
static uint32_t s_sd_error_count;
extern uint8_t _ebss;
extern uint8_t _sidata;

static uint32_t fault_checksum(const volatile SystemFaultRecord *record)
{
    const volatile uint32_t *words = (const volatile uint32_t *)record;
    uint32_t sum = 0x9E3779B9UL;
    uint32_t count = (uint32_t)(sizeof(*record) / sizeof(uint32_t)) - 1U;
    for (uint32_t i = 0U; i < count; ++i) sum = (sum << 5) ^ (sum >> 27) ^ words[i];
    return sum;
}

static uint8_t persistent_fault_valid(void)
{
    return (s_fault_record.magic == SYSTEM_DIAG_FAULT_MAGIC &&
            s_fault_record.checksum == fault_checksum(&s_fault_record)) ? 1U : 0U;
}

void SystemDiag_BootInit(void)
{
    s_reset_flags = RCC->CSR;
    RCC->CSR |= RCC_CSR_RMVF;
    s_app_state = APP_STATE_BOOT;
    s_current_file[0] = '\0';
    if (persistent_fault_valid()) {
        (void)memcpy(&s_boot_fault, (const void *)&s_fault_record, sizeof(s_boot_fault));
        s_boot_fault_valid = 1U;
        s_fault_record.magic = 0U;
        s_fault_record.checksum = 0U;
        printf("[FAULT] seq=%lu pc=%08lX lr=%08lX CFSR=%08lX HFSR=%08lX state=%lu file=%s\n",
               (unsigned long)s_boot_fault.sequence,
               (unsigned long)s_boot_fault.stacked_pc,
               (unsigned long)s_boot_fault.stacked_lr,
               (unsigned long)s_boot_fault.cfsr,
               (unsigned long)s_boot_fault.hfsr,
               (unsigned long)s_boot_fault.app_state,
               s_boot_fault.current_file);
    }
    if (SystemDiag_WasWatchdogReset()) printf("[BOOT] recovered from watchdog reset\n");
}

void SystemDiag_WatchdogInit(void)
{
#ifdef DEBUG
    /* Breakpoints must not look like firmware hangs during a Debug session. */
    __HAL_DBGMCU_FREEZE_IWDG();
#endif
    IWDG->KR = 0x5555U;
    IWDG->PR = 6U; /* divider 256 */
    IWDG->RLR = 1249U;
    IWDG->KR = 0xAAAAU;
    IWDG->KR = 0xCCCCU;
    s_watchdog_started = 1U;
}

void SystemDiag_FeedWatchdog(void) { if (s_watchdog_started) IWDG->KR = 0xAAAAU; }
void SystemDiag_SetState(AppRuntimeState state) { s_app_state = state; }
AppRuntimeState SystemDiag_GetState(void) { return s_app_state; }

void SystemDiag_SetCurrentFile(const char *name)
{
    if (name == NULL) name = "";
    (void)snprintf(s_current_file, sizeof(s_current_file), "%s", name);
}

uint8_t SystemDiag_HasFaultRecord(void)
{
    return s_boot_fault_valid || persistent_fault_valid();
}

const SystemFaultRecord *SystemDiag_GetFaultRecord(void)
{
    return s_boot_fault_valid ? &s_boot_fault : (const SystemFaultRecord *)&s_fault_record;
}
void SystemDiag_ClearFaultRecord(void)
{
    s_boot_fault_valid = 0U;
    s_fault_record.magic = 0U;
    s_fault_record.checksum = 0U;
}
uint32_t SystemDiag_GetResetFlags(void) { return s_reset_flags; }
uint8_t SystemDiag_WasWatchdogReset(void) { return (s_reset_flags & RCC_CSR_IWDGRSTF) ? 1U : 0U; }

uint32_t SystemDiag_GetStackMargin(void)
{
    uint32_t sp = __get_MSP(), bss_end = (uint32_t)&_ebss;
    return sp > bss_end ? sp - bss_end : 0U;
}

uint32_t SystemDiag_GetStaticRamBytes(void) { return (uint32_t)&_ebss - 0x20000000UL; }
uint32_t SystemDiag_GetFlashBytes(void) { return (uint32_t)&_sidata - 0x08000000UL; }
void SystemDiag_ReportSdError(void) { s_sd_error_count++; }
uint32_t SystemDiag_GetSdErrorCount(void) { return s_sd_error_count; }

void SystemDiag_HardFaultCapture(uint32_t *stack, uint32_t exc_return)
{
    const SystemFaultRecord *previous_record = SystemDiag_GetFaultRecord();
    uint32_t previous = SystemDiag_HasFaultRecord() ? previous_record->sequence : 0U;
    s_fault_record.magic = SYSTEM_DIAG_FAULT_MAGIC;
    s_fault_record.sequence = previous + 1U;
    s_fault_record.stacked_r0 = stack[0]; s_fault_record.stacked_r1 = stack[1];
    s_fault_record.stacked_r2 = stack[2]; s_fault_record.stacked_r3 = stack[3];
    s_fault_record.stacked_r12 = stack[4]; s_fault_record.stacked_lr = stack[5];
    s_fault_record.stacked_pc = stack[6]; s_fault_record.stacked_xpsr = stack[7];
    s_fault_record.exc_return = exc_return;
    s_fault_record.cfsr = SCB->CFSR; s_fault_record.hfsr = SCB->HFSR;
    s_fault_record.dfsr = SCB->DFSR; s_fault_record.afsr = SCB->AFSR;
    s_fault_record.mmfar = SCB->MMFAR; s_fault_record.bfar = SCB->BFAR;
    s_fault_record.app_state = (uint32_t)s_app_state;
    (void)memset((void *)s_fault_record.current_file, 0, sizeof(s_fault_record.current_file));
    (void)memcpy((void *)s_fault_record.current_file, s_current_file,
                 sizeof(s_fault_record.current_file) - 1U);
    s_fault_record.checksum = fault_checksum(&s_fault_record);
    __DSB();
    NVIC_SystemReset();
    while (1) { }
}
