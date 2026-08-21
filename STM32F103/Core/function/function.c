/**
  ******************************************************************************
  * @file    function.c
  * @author  riochihao
  * @brief   SD 卡文件浏览 + 取模视频播放（按键 UI）实现
  ******************************************************************************
  */
#include <string.h>
#include <stdio.h>
#include "main.h"        /* HAL：GPIO / HAL_GetTick / HAL_Delay */
#include "ff.h"          /* FatFs */
#include "SD_reader.h"   /* g_sd_card / 卡类型 */
#include "sd_debug.h"    /* 卡信息串口输出 */
#include "oled.hpp"      /* OLED 绘制（extern "C"） */
#include "app_ui.h"      /* 统一应用 UI */
#include "function.h"
#include "system_diag.h"

#define APP_CARD_RETRY_MS   700U
#define APP_CARD_PROBE_MS   500U
#define APP_CARD_MISS_LIMIT   2U
#define APP_RESCAN_MS       1200U
#define APP_DIR_SCAN_TIMEOUT_MS 5000U
#define APP_DIR_SCAN_ENTRY_LIMIT 8192UL

//==================== 按键事件（EXTI 回调里置位，主循环消费）====================
/* 三个独立标志，volatile（中断与主循环共享）。带 tick 去抖避免抖动多触发。 */
static volatile uint8_t s_key_up   = 0;
static volatile uint8_t s_key_down = 0;
static volatile uint8_t s_key_ok   = 0;

/**
 * @brief HAL GPIO 外部中断统一回调（覆盖 HAL 弱符号）
 * @note  按引脚置对应事件标志；同一按键 150ms 内的重复沿视为抖动丢弃。
 */
void HAL_GPIO_EXTI_Callback(uint16_t pin)
{
    static uint32_t t_up = 0, t_down = 0, t_ok = 0;
    uint32_t now = HAL_GetTick();
    if (pin == FN_KEY_UP_PIN)        { if (now - t_up   > 150U) { s_key_up = 1;   t_up = now; } }
    else if (pin == FN_KEY_DOWN_PIN) { if (now - t_down > 150U) { s_key_down = 1; t_down = now; } }
    else if (pin == FN_KEY_OK_PIN)   { if (now - t_ok   > 150U) { s_key_ok = 1;   t_ok = now; } }
}

/* 取走并清除一个按键事件，返回是否曾触发 */
static uint8_t key_take(volatile uint8_t *flag)
{
    if (*flag) { *flag = 0; return 1U; }
    return 0U;
}

typedef struct {
    uint32_t pressed_at;
    uint32_t next_repeat;
    uint8_t active;
} KeyRepeatState;

static uint8_t key_repeat_take(uint16_t pin, KeyRepeatState *state)
{
    uint32_t now = HAL_GetTick();
    if (HAL_GPIO_ReadPin(FN_KEY_PORT, pin) != GPIO_PIN_RESET) {
        state->active = 0U;
        return 0U;
    }
    if (!state->active) {
        state->active = 1U;
        state->pressed_at = now;
        state->next_repeat = now + 450U;
        return 0U;
    }
    if ((int32_t)(now - state->next_repeat) < 0) return 0U;
    uint32_t held = now - state->pressed_at;
    state->next_repeat = now + (held >= 1800U ? 65U : held >= 900U ? 110U : 160U);
    return 1U;
}

//==================== 文件系统状态 ====================
static FATFS  s_fs;                              /* 卷工作区（须常驻） */
static char   s_names[FN_MAX_FILES][FN_NAME_MAX]; /* LFN 文件名表 */
static AppUI_VideoMeta s_meta[FN_MAX_FILES];
static uint8_t s_file_cnt = 0;                    /* 扫描到的视频文件数 */
static uint8_t s_use_function_dir = 0;            /* 1=/function，0=根目录 */
static uint8_t s_media_lost = 0;                   /* 统一热拔插恢复标志 */
static AppUI_VolumeInfo s_volume;                  /* UI 与 FatFs 解耦的卷信息 */
static uint32_t s_free_scan_started;
static uint32_t s_free_scan_last_ui;
static uint16_t s_free_scan_target_permille;
static uint16_t s_free_scan_display_permille;
static uint32_t s_dir_scan_started;
static uint32_t s_dir_scan_last_ui;
static uint32_t s_dir_scan_entries;
static uint8_t s_dir_scan_active;
static uint8_t s_dir_scan_aborted;
static uint8_t s_free_scan_skipped;
static uint8_t s_last_selected;

static void frame_delay(uint32_t frame_start);

_Static_assert(sizeof(FN_VideoHeader) == 16U, "OVID header must be 16 bytes");
_Static_assert(FN_NAME_MAX == APP_UI_FILE_NAME_MAX, "UI and browser name sizes must match");

/*
 * FatFs 完整 FAT 扫描进度钩子。每个 FAT 扇区都会触发，UI 以 16 ms
 * 周期平滑追赶真实扫描进度，正常总线下保持不低于 60 FPS。
 */
static void free_scan_advance_display(void)
{
    if (s_free_scan_display_permille >= s_free_scan_target_permille) return;
    uint16_t remaining = (uint16_t)(s_free_scan_target_permille -
                                    s_free_scan_display_permille);
    uint16_t step = (uint16_t)((remaining + 3U) / 4U);
    if (step == 0U) step = 1U;
    s_free_scan_display_permille = (uint16_t)(s_free_scan_display_permille + step);
    if (s_free_scan_display_permille > s_free_scan_target_permille)
        s_free_scan_display_permille = s_free_scan_target_permille;
}

int FF_FreeScan_Progress(DWORD scanned_entries, DWORD total_entries)
{
    uint32_t now = HAL_GetTick();
    SystemDiag_FeedWatchdog();
    if (key_take(&s_key_ok)) {
        if (AppUI_PopupActive()) {
            AppUI_PopupCancel();
            return 0;
        }
        s_free_scan_skipped = 1U;
        return 1;
    }
    uint32_t target = total_entries == 0U ? 1000U :
                      (uint32_t)((uint64_t)scanned_entries * 1000U / total_entries);
    if (target > 1000U) target = 1000U;
    s_free_scan_target_permille = (uint16_t)target;
    if (now - s_free_scan_last_ui < APP_UI_FRAME_MS) return 0;

    free_scan_advance_display();
    AppUI_RenderFreeScan(s_free_scan_display_permille, s_free_scan_target_permille,
                         now - s_free_scan_started);
    s_free_scan_last_ui = HAL_GetTick();
    return 0;
}

/*
 * FatFs 的 dir_read() 会在一个 f_readdir() 内跳过删除项/LFN/卷标。
 * 损坏的循环目录链可能让它永远不返回，因此在 FatFs 内层也设置保护。
 */
int FF_DirScan_Guard(void)
{
    if (!s_dir_scan_active) return 0;
    SystemDiag_FeedWatchdog();
    uint32_t now = HAL_GetTick();
    s_dir_scan_entries++;

    if (now - s_dir_scan_started >= APP_DIR_SCAN_TIMEOUT_MS ||
        s_dir_scan_entries >= APP_DIR_SCAN_ENTRY_LIMIT) {
        s_dir_scan_aborted = 1U;
        return 1;
    }
    if (now - s_dir_scan_last_ui >= APP_UI_FRAME_MS) {
        char detail[20];
        (void)snprintf(detail, sizeof(detail), "Files %lu",
                       (unsigned long)s_dir_scan_entries);
        AppUI_RenderAnalyzing(now - s_dir_scan_started, detail);
        s_dir_scan_last_ui = HAL_GetTick();
    }
    return 0;
}

/* 末尾扩展名是否匹配 FN_VIDEO_EXT（大小写不敏感） */
static uint8_t name_has_ext(const char *name)
{
    size_t nl = strlen(name), el = strlen(FN_VIDEO_EXT);
    if (nl < el) return 0U;
    const char *p = name + (nl - el);
    for (size_t i = 0; i < el; ++i)
    {
        char a = p[i], b = FN_VIDEO_EXT[i];
        if (a >= 'a' && a <= 'z') a = (char)(a - 32);
        if (b >= 'a' && b <= 'z') b = (char)(b - 32);
        if (a != b) return 0U;
    }
    return 1U;
}
static int name_compare_ci(const char *a, const char *b)
{
    while (*a && *b) {
        char ca = *a++, cb = *b++;
        if (ca >= 'a' && ca <= 'z') ca = (char)(ca - 32);
        if (cb >= 'a' && cb <= 'z') cb = (char)(cb - 32);
        if (ca != cb) return (unsigned char)ca - (unsigned char)cb;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

static void read_video_meta(const char *dir, const char *name, AppUI_VideoMeta *meta)
{
    char full[FN_NAME_MAX + 16U];
    FIL file;
    FN_VideoHeader hdr;
    UINT read = 0U;
    (void)memset(meta, 0, sizeof(*meta));
    if (strcmp(dir, "/") == 0)
        (void)snprintf(full, sizeof(full), "/%s", name);
    else
        (void)snprintf(full, sizeof(full), "%s/%s", dir, name);
    if (f_open(&file, full, FA_READ) != FR_OK) return;
    FRESULT fr = f_read(&file, &hdr, sizeof(hdr), &read);
    (void)f_close(&file);
    if (fr != FR_OK || read != sizeof(hdr) ||
        hdr.magic[0] != FN_MAGIC0 || hdr.magic[1] != FN_MAGIC1 ||
        hdr.magic[2] != FN_MAGIC2 || hdr.magic[3] != FN_MAGIC3) return;
    meta->width = hdr.width; meta->height = hdr.height;
    meta->frames = hdr.frame_count; meta->fps = hdr.fps;
    meta->version = hdr.version == FN_OVID_V2 ? 2U : 1U;
    meta->valid = 1U;
}

static void sort_file_names(void)
{
    char temp[FN_NAME_MAX];
    AppUI_VideoMeta temp_meta;
    for (uint8_t i = 1U; i < s_file_cnt; ++i) {
        uint8_t j = i;
        (void)memcpy(temp, s_names[i], sizeof(temp));
        temp_meta = s_meta[i];
        while (j > 0U && name_compare_ci(s_names[j - 1U], temp) > 0) {
            (void)memcpy(s_names[j], s_names[j - 1U], sizeof(s_names[j]));
            s_meta[j] = s_meta[j - 1U];
            --j;
        }
        (void)memcpy(s_names[j], temp, sizeof(s_names[j]));
        s_meta[j] = temp_meta;
    }
}

/* 扫描一个目录，记录普通 .BIN 文件，支持最多 63 字符 LFN。 */
static FRESULT fs_scan_dir(const char *path)
{
    FRESULT fr;
    DIR     dir;
    FILINFO fno;

    s_file_cnt = 0;
    s_dir_scan_started = HAL_GetTick();
    s_dir_scan_last_ui = s_dir_scan_started;
    s_dir_scan_entries = 0U;
    s_dir_scan_active = 1U;
    s_dir_scan_aborted = 0U;
    fr = f_opendir(&dir, path);
    if (fr != FR_OK) {
        s_dir_scan_active = 0U;
        if (s_dir_scan_aborted) {
            printf("[FATFS] directory guard stopped while opening %s\n", path);
            return FR_OK;
        }
        return fr;
    }

    while (s_file_cnt < FN_MAX_FILES)
    {
        fr = f_readdir(&dir, &fno);
        if (s_dir_scan_aborted) { fr = FR_OK; break; }
        if (fr != FR_OK || fno.fname[0] == 0) break;   /* 出错或读完 */
        if (fno.fattrib & AM_DIR) continue;            /* 跳过子目录 */
        if (!name_has_ext(fno.fname)) continue;        /* 仅收 .BIN */
        (void)snprintf(s_names[s_file_cnt], FN_NAME_MAX, "%s", fno.fname);
        read_video_meta(path, s_names[s_file_cnt], &s_meta[s_file_cnt]);
        s_file_cnt++;
    }
    (void)f_closedir(&dir);
    s_dir_scan_active = 0U;
    if (s_dir_scan_aborted)
        printf("[FATFS] directory guard stopped %s after %lu entries / %lu ms\n",
               path, (unsigned long)s_dir_scan_entries,
               (unsigned long)(HAL_GetTick() - s_dir_scan_started));
    sort_file_names();
    return fr;
}

/** 优先扫描 /function，其中无 .BIN 时回退根目录。 */
static FRESULT fs_scan_video_dirs(void)
{
    FRESULT fr = fs_scan_dir("/" FN_DIR_NAME);
    if (fr == FR_OK && s_file_cnt > 0U) {
        s_use_function_dir = 1U;
        return FR_OK;
    }
    if (s_dir_scan_aborted) {
        s_use_function_dir = 1U;
        return FR_OK;
    }
    if (fr != FR_OK && fr != FR_NO_PATH) return fr;

    s_use_function_dir = 0U;
    return fs_scan_dir("/");
}

static const char *fs_type_name(BYTE type)
{
    switch (type) {
    case FS_FAT12: return "FAT12";
    case FS_FAT16: return "FAT16";
    case FS_FAT32: return "FAT32";
    default:       return "Unknown";
    }
}

static uint8_t is_media_error(FRESULT fr)
{
    return (fr == FR_DISK_ERR || fr == FR_NOT_READY || fr == FR_INVALID_OBJECT);
}

static void media_invalidate(const char *reason, FRESULT fr)
{
    SystemDiag_ReportSdError();
    (void)f_unmount("");
    g_sd_card.info.initialized = 0U;
    g_sd_card.info.type = SD_TYPE_NONE;
    g_sd_card.busy = 0U;
    s_file_cnt = 0U;
    s_media_lost = 1U;
    printf("[APP] media offline: %s, FatFs=%d\n", reason, (int)fr);
}

/** 挂载卷、用 f_getfree 扫描 FAT，再扫描视频目录。 */
static FRESULT fs_mount_collect_and_scan(void)
{
    FATFS *mounted = NULL;
    DWORD free_clusters = 0U;
    FRESULT fr;

    (void)memset(&s_volume, 0, sizeof(s_volume));
    s_free_scan_skipped = 0U;
    s_free_scan_target_permille = 0U;
    s_free_scan_display_permille = 0U;
    fr = f_mount(&s_fs, "", 1);
    if (fr != FR_OK) return fr;

    (void)snprintf(s_volume.fs_name, sizeof(s_volume.fs_name), "%s",
                   fs_type_name(s_fs.fs_type));
    s_volume.total_bytes = (uint64_t)(s_fs.n_fatent - 2U) * s_fs.csize * FF_MAX_SS;
    printf("[FATFS] f_getfree begin: type=%s clusters=%lu\n",
           s_volume.fs_name, (unsigned long)(s_fs.n_fatent - 2U));
    SystemDiag_SetState(APP_STATE_FREE_SCAN);
    s_key_ok = 0U;
    s_free_scan_started = HAL_GetTick();
    s_free_scan_last_ui = s_free_scan_started;
    AppUI_RenderFreeScan(0U, 0U, 0U);
    fr = f_getfree("", &free_clusters, &mounted);
    printf("[FATFS] f_getfree returned: %d\n", (int)fr);
    if (fr == FR_OK && mounted != NULL) {
        uint64_t free_sectors = (uint64_t)free_clusters * mounted->csize;
        s_volume.free_bytes = free_sectors * FF_MAX_SS;
        if (s_volume.free_bytes > s_volume.total_bytes)
            s_volume.free_bytes = s_volume.total_bytes;
        s_volume.free_valid = 1U;
        /* 扫描完成后用最多 320 ms 平滑追到 100%，不把真实 I/O 进度伪造成瞬间完成。 */
        s_free_scan_target_permille = 1000U;
        uint32_t finish_started = HAL_GetTick();
        while (s_free_scan_display_permille < 1000U &&
               HAL_GetTick() - finish_started < 320U) {
            uint32_t frame = HAL_GetTick();
            free_scan_advance_display();
            AppUI_RenderFreeScan(s_free_scan_display_permille,
                                 s_free_scan_target_permille,
                                 frame - s_free_scan_started);
            frame_delay(frame);
        }
        if (s_free_scan_display_permille < 1000U) {
            s_free_scan_display_permille = 1000U;
            AppUI_RenderFreeScan(1000U, 1000U, HAL_GetTick() - s_free_scan_started);
        }
        OLED_Wait_DMA();
    } else if (s_free_scan_skipped) {
        printf("[FATFS] free-space scan skipped by user; Free=N/A\n");
    } else {
        printf("[FATFS] f_getfree failed: %d; Free=N/A\n", (int)fr);
        if (is_media_error(fr)) return fr;
    }

    SystemDiag_SetState(APP_STATE_FILE_SCAN);
    AppUI_RenderAnalyzing(0U, "Scanning files");
    printf("[FATFS] directory scan begin\n");
    fr = fs_scan_video_dirs();
    AppUI_RenderAnalyzing(0U, "Preparing UI");
    OLED_Wait_DMA();
    printf("[FATFS] directory scan returned: %d, files=%u\n", (int)fr, s_file_cnt);
    if (fr == FR_OK) {
        uint32_t total_mib = (uint32_t)(s_volume.total_bytes >> 20U);
        uint32_t free_mib = (uint32_t)(s_volume.free_bytes >> 20U);

        /* Newlib Nano's variadic printf can misread arguments following %llu.
         * Keep the 64-bit values for calculations, but log bounded 32-bit MiB. */
        printf("[FATFS] type=%s total_mib=%lu free_mib=%lu free_valid=%u files=%u dir=%s\n",
               s_volume.fs_name, (unsigned long)total_mib, (unsigned long)free_mib,
               s_volume.free_valid, s_file_cnt,
               s_use_function_dir ? "/" FN_DIR_NAME : "/");
    }
    return fr;
}

//==================== 统一应用流程与热拔插探测 ====================
static void frame_delay(uint32_t frame_start)
{
    SystemDiag_FeedWatchdog();
    uint32_t elapsed = HAL_GetTick() - frame_start;
    if (elapsed < APP_UI_FRAME_MS) HAL_Delay(APP_UI_FRAME_MS - elapsed);
}

/* 需要在阻塞式 SD/FatFs 操作前完整展示的弹窗统一由这里驱动。
 * 保持 OLED 按应用帧率刷新，避免只画出第一帧后就被磁盘操作卡住。 */
static void wait_popup_animation(void)
{
    while (AppUI_PopupActive()) {
        uint32_t frame = HAL_GetTick();
        if (key_take(&s_key_ok)) AppUI_PopupCancel();
        AppUI_RenderPopupTask();
        frame_delay(frame);
    }
}

/* 信息页最后一帧只等待到 3000 ms 边界，避免 16 ms 帧节流造成累计超时。 */
static void info_page_delay(uint32_t frame_start, uint32_t page_start)
{
    SystemDiag_FeedWatchdog();
    uint32_t now = HAL_GetTick();
    uint32_t frame_elapsed = now - frame_start;
    uint32_t page_elapsed = now - page_start;
    if (page_elapsed >= APP_UI_INFO_PAGE_MS) return;

    uint32_t delay = frame_elapsed < APP_UI_FRAME_MS ? APP_UI_FRAME_MS - frame_elapsed : 0U;
    uint32_t remaining = APP_UI_INFO_PAGE_MS - page_elapsed;
    if (delay > remaining) delay = remaining;
    if (delay > 0U) HAL_Delay(delay);
}

static uint8_t probe_card(uint8_t *misses)
{
    if (SD_Card_IsPresent_Card(&g_sd_card)) {
        *misses = 0U;
        return 1U;
    }
    if (*misses < APP_CARD_MISS_LIMIT) (*misses)++;
    if (*misses >= APP_CARD_MISS_LIMIT) {
        media_invalidate("CMD58 presence probe", FR_NOT_READY);
        return 0U;
    }
    return 1U;
}

static uint32_t card_spi_hz(void)
{
    if (g_sd_card.io.get_bus_clk == NULL || g_sd_card.io.get_prescaler == NULL) return 0U;
    uint32_t divider = 2UL << (g_sd_card.io.get_prescaler() >> 3U);
    return divider == 0U ? 0U : g_sd_card.io.get_bus_clk() / divider;
}

static uint8_t diagnostic_key_mask(void)
{
    uint8_t mask = 0U;
    if (HAL_GPIO_ReadPin(FN_KEY_PORT, FN_KEY_UP_PIN) == GPIO_PIN_RESET) mask |= 4U;
    if (HAL_GPIO_ReadPin(FN_KEY_PORT, FN_KEY_DOWN_PIN) == GPIO_PIN_RESET) mask |= 2U;
    if (HAL_GPIO_ReadPin(FN_KEY_PORT, FN_KEY_OK_PIN) == GPIO_PIN_RESET) mask |= 1U;
    return mask;
}

static void run_diagnostics_if_requested(void)
{
    if ((diagnostic_key_mask() & 6U) != 6U) return;
    uint8_t page = 0U;
    uint32_t started = HAL_GetTick();
    uint32_t next_sd_try = started;
    int16_t sd_test_result = INT16_MIN;
    s_key_up = s_key_down = s_key_ok = 0U;
    SystemDiag_SetState(APP_STATE_DIAGNOSTICS);
    while (1) {
        uint32_t frame = HAL_GetTick();
        if (key_take(&s_key_up)) page = page == 0U ? 2U : (uint8_t)(page - 1U);
        if (key_take(&s_key_down)) page = (uint8_t)((page + 1U) % 3U);
        if (key_take(&s_key_ok)) {
            if (AppUI_PopupActive()) { AppUI_PopupCancel(); continue; }
            if (page == 1U && g_sd_card.info.initialized) {
#if SD_ENABLE_SELF_TEST
                uint32_t test_block = g_sd_card.info.block_count > 8193U ? 8192U : 1U;
                AppUI_ShowPopup("SD read/write", "Testing and restoring", APP_UI_POPUP_MS);
                SystemDiag_FeedWatchdog();
                sd_test_result = (int16_t)SD_Self_Test_Card(&g_sd_card, test_block);
                SystemDiag_FeedWatchdog();
#else
                sd_test_result = -127;
#endif
                continue;
            }
            break;
        }
        if (!g_sd_card.info.initialized && (int32_t)(frame - next_sd_try) >= 0) {
            (void)SD_Init_Card(&g_sd_card);
            next_sd_try = frame + APP_CARD_RETRY_MS;
        }
        AppUI_RenderDiagnostics(page, diagnostic_key_mask(), sd_test_result, frame - started);
        frame_delay(frame);
    }
    AppUI_ShowPopup("Diagnostics", "Exit to player", APP_UI_POPUP_MS);
}

static void wait_for_card(void)
{
    SystemDiag_SetState(APP_STATE_WAIT_CARD);
    SystemDiag_SetCurrentFile("");
    uint32_t started = HAL_GetTick();
    uint32_t next_try = started;

    s_key_up = s_key_down = s_key_ok = 0U;
    while (g_sd_card.info.initialized == 0U) {
        uint32_t frame = HAL_GetTick();
        AppUI_RenderWaitCard(frame - started);
        if ((int32_t)(frame - next_try) >= 0) {
            int type = SD_Init_Card(&g_sd_card);
            if (type > 0) {
                s_media_lost = 0U;
                printf("[APP] SD detected, type=%d\n", type);
                AppUI_ShowPopup("SD detected", "Card is ready", APP_UI_POPUP_MS);
                wait_popup_animation();
                return;
            }
            next_try = frame + APP_CARD_RETRY_MS;
        }
        frame_delay(frame);
    }
}

static void show_removed_sequence(void)
{
    uint32_t started = HAL_GetTick();
    while (HAL_GetTick() - started < 900U) {
        uint32_t frame = HAL_GetTick();
        AppUI_RenderRemoved(frame - started);
        frame_delay(frame);
    }
}

static uint8_t show_info_pages(void)
{
    SystemDiag_SetState(APP_STATE_INFO);
    uint8_t misses = 0U;
    uint32_t spi_hz = card_spi_hz();
    uint32_t next_probe = HAL_GetTick() + APP_CARD_PROBE_MS;

    for (uint8_t page = 0U; page < APP_UI_INFO_PAGES; ++page) {
        uint32_t started = HAL_GetTick();
        while (HAL_GetTick() - started < APP_UI_INFO_PAGE_MS) {
            uint32_t frame = HAL_GetTick();
            AppUI_RenderInfoPage(page, &g_sd_card.info, &s_volume,
                                 spi_hz, frame - started);
            if ((int32_t)(frame - next_probe) >= 0) {
                if (!probe_card(&misses)) return 0U;
                next_probe = frame + APP_CARD_PROBE_MS;
            }
            info_page_delay(frame, started);
        }
    }
    return 1U;
}

static void wait_unsupported_filesystem(void)
{
    uint8_t misses = 0U;
    uint32_t started = HAL_GetTick();
    uint32_t next_probe = started;

    printf("[FATFS] unsupported filesystem; waiting for removal\n");
    while (!s_media_lost) {
        uint32_t frame = HAL_GetTick();
        AppUI_RenderPersistentError("Unsupported FS", "Use FAT/FAT32", frame - started);
        if ((int32_t)(frame - next_probe) >= 0) {
            if (!probe_card(&misses)) break;
            next_probe = frame + APP_CARD_PROBE_MS;
        }
        frame_delay(frame);
    }
}

static uint8_t wait_for_files(void)
{
    SystemDiag_SetState(APP_STATE_LIBRARY);
    uint8_t misses = 0U;
    uint32_t started = HAL_GetTick();
    uint32_t next_probe = started + APP_CARD_PROBE_MS;
    uint32_t next_scan = started + APP_RESCAN_MS;

    while (s_file_cnt == 0U) {
        uint32_t frame = HAL_GetTick();
        AppUI_RenderEmpty(s_use_function_dir, frame - started);
        if ((int32_t)(frame - next_probe) >= 0) {
            if (!probe_card(&misses)) return 0U;
            next_probe = frame + APP_CARD_PROBE_MS;
        }
        if ((int32_t)(frame - next_scan) >= 0) {
            FRESULT fr = fs_scan_video_dirs();
            if (fr != FR_OK) {
                if (is_media_error(fr)) media_invalidate("empty-page rescan", fr);
                else AppUI_ShowPopup("Scan failed", "Check filesystem", APP_UI_POPUP_MS);
                return 0U;
            }
            if (s_file_cnt > 0U) {
                AppUI_ShowPopup("Files found", "Open library", APP_UI_POPUP_MS);
                return 1U;
            }
            next_scan = frame + APP_RESCAN_MS;
        }
        frame_delay(frame);
    }
    return 1U;
}

static uint8_t ui_list_rows(void)
{
    uint8_t y0 = (OLED_HEIGHT >= 24U) ? 11U : 0U;
    uint8_t footer = (OLED_HEIGHT >= 48U) ? 9U : 0U;
    uint8_t rows = (uint8_t)((OLED_HEIGHT - y0 - footer) / 9U);
    return rows > 0U ? rows : 1U;
}

static uint8_t ui_select_file(uint8_t *sel_out)
{
    SystemDiag_SetState(APP_STATE_LIBRARY);
    SystemDiag_SetCurrentFile("");
    uint8_t sel = s_last_selected < s_file_cnt ? s_last_selected : 0U;
    uint8_t top = 0U, misses = 0U;
    uint8_t rows = ui_list_rows();
    KeyRepeatState repeat_up = {0}, repeat_down = {0};
    uint32_t started = HAL_GetTick();
    uint32_t next_probe = started + APP_CARD_PROBE_MS;

    s_key_ok = 0U;
    for (;;) {
        uint32_t frame = HAL_GetTick();
        uint8_t move_up = key_take(&s_key_up) || key_repeat_take(FN_KEY_UP_PIN, &repeat_up);
        uint8_t move_down = key_take(&s_key_down) || key_repeat_take(FN_KEY_DOWN_PIN, &repeat_down);
        if (move_up && s_file_cnt > 0U)
            sel = sel == 0U ? (uint8_t)(s_file_cnt - 1U) : (uint8_t)(sel - 1U);
        if (move_down && s_file_cnt > 0U)
            sel = (uint8_t)((sel + 1U) % s_file_cnt);
        if (sel < top) top = sel;
        else if (sel >= (uint8_t)(top + rows)) top = (uint8_t)(sel - rows + 1U);

        if (key_take(&s_key_ok)) {
            if (AppUI_PopupActive()) { AppUI_PopupCancel(); continue; }
            s_last_selected = sel;
            *sel_out = sel;
            return 1U;
        }
        AppUI_RenderFileList(s_names, s_file_cnt, sel, top,
                             s_use_function_dir, s_meta, frame - started);
        if ((int32_t)(frame - next_probe) >= 0) {
            if (!probe_card(&misses)) return 0U;
            next_probe = frame + APP_CARD_PROBE_MS;
        }
        frame_delay(frame);
    }
}
//==================== 视频播放 ====================
static uint8_t s_page[OLED_WIDTH];      /* 小尺寸视频只需一行源页缓冲 */

static uint16_t crc16_ccitt(const uint8_t *data, uint32_t size)
{
    uint16_t crc = 0xFFFFU;
    while (size--) {
        crc ^= (uint16_t)(*data++) << 8U;
        for (uint8_t bit = 0U; bit < 8U; ++bit)
            crc = (crc & 0x8000U) ? (uint16_t)((crc << 1U) ^ 0x1021U) : (uint16_t)(crc << 1U);
    }
    return crc;
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint32_t size)
{
    while (size--) {
        crc ^= *data++;
        for (uint8_t bit = 0U; bit < 8U; ++bit)
            crc = (crc >> 1U) ^ ((crc & 1U) ? 0xEDB88320UL : 0U);
    }
    return crc;
}

static void make_video_path(char path[FN_NAME_MAX + 16U], const char *name)
{
    if (s_use_function_dir)
        (void)snprintf(path, FN_NAME_MAX + 16U, "/%s/%s", FN_DIR_NAME, name);
    else
        (void)snprintf(path, FN_NAME_MAX + 16U, "/%s", name);
}

/* 将一个源页合成到居中后的目标显存，支持非 8 对齐 y 和尾页。 */
static void compose_page(uint16_t source_page, uint8_t width, uint8_t height,
                         uint8_t ox, uint8_t oy)
{
    uint16_t valid = (uint16_t)height - source_page * 8U;
    uint8_t mask = (valid >= 8U) ? 0xFFU : (uint8_t)((1U << valid) - 1U);
    uint16_t y = (uint16_t)oy + source_page * 8U;
    uint8_t dst_page = (uint8_t)(y >> 3);
    uint8_t shift = (uint8_t)(y & 7U);

    for (uint16_t x = 0; x < width; ++x) {
        uint8_t bits = s_page[x] & mask;
        draw_buffer[dst_page][(uint16_t)ox + x] |= (uint8_t)(bits << shift);
        if (shift != 0U && (uint8_t)(dst_page + 1U) < OLED_PAGES)
            draw_buffer[dst_page + 1U][(uint16_t)ox + x] |= (uint8_t)(bits >> (8U - shift));
    }
}

static FRESULT read_frame(FIL *f, const FN_VideoHeader *hdr, uint32_t fbytes,
                          uint8_t ox, uint8_t oy, uint32_t *frame_crc)
{
    UINT br;
    uint32_t crc = 0xFFFFFFFFUL;
    if (hdr->width == OLED_WIDTH && hdr->height == OLED_HEIGHT) {
        FRESULT fr = f_read(f, draw_buffer[0], fbytes, &br);
        if (fr == FR_OK && br == fbytes) crc = crc32_update(crc, draw_buffer[0], fbytes);
        if (frame_crc) *frame_crc = crc ^ 0xFFFFFFFFUL;
        return (fr == FR_OK && br == fbytes) ? FR_OK : ((fr == FR_OK) ? FR_DISK_ERR : fr);
    }

    OLED_GRAM_Clear();
    uint16_t source_pages = (uint16_t)((hdr->height + 7U) / 8U);
    for (uint16_t pg = 0; pg < source_pages; ++pg) {
        FRESULT fr = f_read(f, s_page, hdr->width, &br);
        if (fr != FR_OK || br != hdr->width) return (fr == FR_OK) ? FR_DISK_ERR : fr;
        crc = crc32_update(crc, s_page, hdr->width);
        compose_page(pg, hdr->width, hdr->height, ox, oy);
    }
    if (frame_crc) *frame_crc = crc ^ 0xFFFFFFFFUL;
    return FR_OK;
}

/**
 * @brief 播放一个 .bin 视频文件
 * @note  读 16B 头部校验 magic/尺寸 → 循环读帧画到 OLED（居中）→ 按 fps 控帧。
 *        确认键中途退出；播完自动从头循环，直到按确认。
 * @param fname 文件名（根目录）
 */
static void play_video(const char *fname)
{
    FIL f;
    FN_VideoHeader hdr;
    UINT br;
    char path[FN_NAME_MAX + 16U];
    make_video_path(path, fname);
    SystemDiag_SetState(APP_STATE_PLAYBACK);
    SystemDiag_SetCurrentFile(fname);

    AppUI_ShowClassicPopup("Loading", fname, APP_UI_POPUP_MS);
    wait_popup_animation();
    FRESULT fr = f_open(&f, path, FA_READ);
    if (fr != FR_OK) {
        if (is_media_error(fr)) media_invalidate("open", fr);
        else AppUI_ShowPopup("Open failed", fname, APP_UI_POPUP_MS);
        return;
    }

    fr = f_read(&f, &hdr, sizeof(hdr), &br);
    if (fr != FR_OK || br != sizeof(hdr) ||
        hdr.magic[0] != FN_MAGIC0 || hdr.magic[1] != FN_MAGIC1 ||
        hdr.magic[2] != FN_MAGIC2 || hdr.magic[3] != FN_MAGIC3)
    {
        (void)f_close(&f);
        if (fr != FR_OK && is_media_error(fr)) media_invalidate("header", fr);
        else AppUI_ShowPopup("Bad OVID", fname, APP_UI_POPUP_MS);
        return;
    }

    uint32_t fbytes = (uint32_t)((hdr.height + 7U) / 8U) * hdr.width;   /* 每帧字节数（页主序） */
    uint8_t is_v1 = (hdr.version == FN_OVID_V1 && hdr.flags == 0U && hdr.header_crc16 == 0U);
    uint8_t is_v2 = (hdr.version == FN_OVID_V2 &&
                     (hdr.flags & FN_OVID_FLAG_CRC32) != 0U &&
                     (hdr.flags & (uint8_t)~FN_OVID_FLAG_CRC32) == 0U &&
                     hdr.header_crc16 == crc16_ccitt((const uint8_t *)&hdr, 14U));
    uint32_t record_bytes = fbytes + (is_v2 ? 4U : 0U);
    uint64_t expected_size = sizeof(hdr) + (uint64_t)hdr.frame_count * record_bytes;
    uint64_t actual_size = (uint64_t)f_size(&f);
    if (hdr.width == 0U || hdr.height == 0U || hdr.width > OLED_WIDTH || hdr.height > OLED_HEIGHT ||
        hdr.frame_count == 0U || hdr.fps < 1U || hdr.fps > 120U ||
        (!is_v1 && !is_v2) || expected_size != actual_size)
    {
        (void)f_close(&f);
        AppUI_ShowPopup((hdr.width > OLED_WIDTH || hdr.height > OLED_HEIGHT) ?
                        "Frame too big" : "Invalid OVID", fname, APP_UI_POPUP_MS);
        printf("[PLAYER] reject %s: v=%u flags=%u %ux%u frames=%lu fps=%u frame=%lu file=%lu size_bad=%u\n",
               path, hdr.version, hdr.flags, hdr.width, hdr.height,
               (unsigned long)hdr.frame_count, hdr.fps,
               (unsigned long)fbytes, (unsigned long)actual_size,
               (unsigned int)(expected_size != (uint64_t)actual_size));
        return;
    }

    uint8_t ox = (uint8_t)((OLED_WIDTH  - hdr.width)  / 2U);          /* 居中 */
    uint8_t oy = (uint8_t)((OLED_HEIGHT - hdr.height) / 2U);
    uint16_t fraction = 0U;

    s_key_ok = 0;   /* 清掉进入前可能残留的确认事件 */
    for (;;)        /* 外层：循环播放 */
    {
        fr = f_lseek(&f, sizeof(hdr));
        if (fr != FR_OK) {
            (void)f_close(&f);
            if (is_media_error(fr)) media_invalidate("seek", fr);
            else AppUI_ShowPopup("Seek failed", fname, APP_UI_POPUP_MS);
            return;
        }
        for (uint32_t i = 0; i < hdr.frame_count; ++i)
        {
            uint32_t t0 = HAL_GetTick();
            uint32_t calculated_crc = 0U;
            SystemDiag_FeedWatchdog();
            if (key_take(&s_key_ok)) {
                (void)f_close(&f);
                AppUI_ShowClassicPopup("Library", "Playback stopped", APP_UI_POPUP_MS);
                return;
            }
            fr = read_frame(&f, &hdr, fbytes, ox, oy, &calculated_crc);
            if (fr != FR_OK) {
                (void)f_close(&f);
                if (is_media_error(fr)) media_invalidate("frame", fr);
                else AppUI_ShowPopup("Read failed", fname, APP_UI_POPUP_MS);
                return;
            }

            if (is_v2) {
                uint32_t stored_crc = 0U;
                fr = f_read(&f, &stored_crc, sizeof(stored_crc), &br);
                if (fr != FR_OK || br != sizeof(stored_crc)) {
                    (void)f_close(&f);
                    if (fr != FR_OK && is_media_error(fr)) media_invalidate("frame CRC", fr);
                    else AppUI_ShowPopup("Read failed", "Missing frame CRC", APP_UI_POPUP_MS);
                    return;
                }
                if (stored_crc != calculated_crc) {
                    printf("[OVID] CRC mismatch frame=%lu stored=%08lX actual=%08lX; keeping previous frame\n",
                           (unsigned long)i, (unsigned long)stored_crc,
                           (unsigned long)calculated_crc);
                    SystemDiag_FeedWatchdog();
                    uint32_t dt_bad = HAL_GetTick() - t0;
                    uint32_t period_bad = 1000U / hdr.fps;
                    if (dt_bad < period_bad) HAL_Delay(period_bad - dt_bad);
                    continue;
                }
            }

            OLED_Swap_Buffers();
            uint32_t period = 1000U / hdr.fps;
            fraction = (uint16_t)(fraction + (1000U % hdr.fps));
            if (fraction >= hdr.fps) { period++; fraction = (uint16_t)(fraction - hdr.fps); }
            uint32_t dt = HAL_GetTick() - t0;
            if (dt < period) HAL_Delay(period - dt);
        }
    }
}
//==================== 主入口 ====================
void Function_Run(void)
{
    AppUI_Init();
    run_diagnostics_if_requested();

    if (SystemDiag_HasFaultRecord())
        AppUI_ShowPopup("Fault recovered", "See UART / diagnostics", APP_UI_POPUP_MS);
    else if (SystemDiag_WasWatchdogReset())
        AppUI_ShowPopup("Watchdog reset", "System recovered", APP_UI_POPUP_MS);

    for (;;) {
        s_media_lost = 0U;
        wait_for_card();

        SystemDiag_SetState(APP_STATE_MOUNT);
        AppUI_RenderAnalyzing(0U, "Mounting volume");
        printf("[APP] mounting and analyzing volume...\n");
        FRESULT fr = fs_mount_collect_and_scan();

        if (fr == FR_NO_FILESYSTEM) {
            wait_unsupported_filesystem();
            show_removed_sequence();
            continue;
        }
        if (fr != FR_OK) {
            if (is_media_error(fr)) media_invalidate("mount/analyze", fr);
            else {
                AppUI_ShowPopup("Mount failed", "Check FAT volume", APP_UI_POPUP_MS);
                media_invalidate("mount/analyze", fr);
            }
            show_removed_sequence();
            continue;
        }

        /* 到这里卡和文件系统已就绪，调试函数不会再提前初始化 SD。 */
        SD_Debug_Print_Info(&g_sd_card);
        if (!show_info_pages()) {
            show_removed_sequence();
            continue;
        }

        for (;;) {
            if (!wait_for_files()) break;

            uint8_t selected = 0U;
            if (!ui_select_file(&selected)) break;
            play_video(s_names[selected]);
            if (s_media_lost) break;

            fr = fs_scan_video_dirs();
            if (fr != FR_OK) {
                if (is_media_error(fr)) media_invalidate("post-play scan", fr);
                else AppUI_ShowPopup("Scan failed", "Check filesystem", APP_UI_POPUP_MS);
                break;
            }
        }

        if (s_media_lost) show_removed_sequence();
    }
}
