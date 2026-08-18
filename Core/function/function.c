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

//==================== 文件系统状态 ====================
static FATFS  s_fs;                              /* 卷工作区（须常驻） */
static char   s_names[FN_MAX_FILES][13];         /* 8.3 文件名表 */
static uint8_t s_file_cnt = 0;                    /* 扫描到的视频文件数 */
static uint8_t s_use_function_dir = 0;            /* 1=/function，0=根目录 */
static uint8_t s_media_lost = 0;                   /* 统一热拔插恢复标志 */
static AppUI_VolumeInfo s_volume;                  /* UI 与 FatFs 解耦的卷信息 */
static uint32_t s_free_scan_started;
static uint32_t s_free_scan_last_ui;
static uint32_t s_dir_scan_started;
static uint32_t s_dir_scan_last_ui;
static uint32_t s_dir_scan_entries;
static uint8_t s_dir_scan_active;
static uint8_t s_dir_scan_aborted;

_Static_assert(sizeof(FN_VideoHeader) == 16U, "OVID v1 header must be 16 bytes");

/*
 * FatFs 完整 FAT 扫描进度钩子。每个 FAT 扇区都会触发，但 OLED 最多约 10 FPS
 * 刷新，避免 I2C 动画反过来显著拖慢大容量卡扫描。
 */
void FF_FreeScan_Progress(DWORD scanned_entries, DWORD total_entries)
{
    uint32_t now = HAL_GetTick();
    if (scanned_entries == 0U || s_free_scan_started == 0U) {
        s_free_scan_started = now;
        s_free_scan_last_ui = now;
        AppUI_RenderFreeScan(0U, 0U);
        return;
    }
    if (scanned_entries < total_entries && now - s_free_scan_last_ui < 100U) return;

    uint8_t percent = total_entries == 0U ? 100U :
                      (uint8_t)(((uint64_t)scanned_entries * 100U) / total_entries);
    if (percent > 100U) percent = 100U;
    AppUI_RenderFreeScan(percent, now - s_free_scan_started);
    s_free_scan_last_ui = HAL_GetTick();
}

/*
 * FatFs 的 dir_read() 会在一个 f_readdir() 内跳过删除项/LFN/卷标。
 * 损坏的循环目录链可能让它永远不返回，因此在 FatFs 内层也设置保护。
 */
int FF_DirScan_Guard(void)
{
    if (!s_dir_scan_active) return 0;
    uint32_t now = HAL_GetTick();
    s_dir_scan_entries++;

    if (now - s_dir_scan_started >= APP_DIR_SCAN_TIMEOUT_MS ||
        s_dir_scan_entries >= APP_DIR_SCAN_ENTRY_LIMIT) {
        s_dir_scan_aborted = 1U;
        return 1;
    }
    if (now - s_dir_scan_last_ui >= 100U) {
        char detail[20];
        (void)snprintf(detail, sizeof(detail), "FILES %lu",
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
/* 扫描一个目录，只记录 8.3 形式的 .BIN 普通文件。 */
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
        (void)strncpy(s_names[s_file_cnt], fno.fname, 12);
        s_names[s_file_cnt][12] = '\0';
        s_file_cnt++;
    }
    (void)f_closedir(&dir);
    s_dir_scan_active = 0U;
    if (s_dir_scan_aborted)
        printf("[FATFS] directory guard stopped %s after %lu entries / %lu ms\n",
               path, (unsigned long)s_dir_scan_entries,
               (unsigned long)(HAL_GetTick() - s_dir_scan_started));
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
    default:       return "UNKNOWN";
    }
}

static uint8_t is_media_error(FRESULT fr)
{
    return (fr == FR_DISK_ERR || fr == FR_NOT_READY || fr == FR_INVALID_OBJECT);
}

static void media_invalidate(const char *reason, FRESULT fr)
{
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
    s_free_scan_started = 0U;
    s_free_scan_last_ui = 0U;
    fr = f_mount(&s_fs, "", 1);
    if (fr != FR_OK) return fr;

    (void)snprintf(s_volume.fs_name, sizeof(s_volume.fs_name), "%s",
                   fs_type_name(s_fs.fs_type));
    s_volume.total_bytes = (uint64_t)(s_fs.n_fatent - 2U) * s_fs.csize * FF_MAX_SS;
    printf("[FATFS] f_getfree begin: type=%s clusters=%lu\n",
           s_volume.fs_name, (unsigned long)(s_fs.n_fatent - 2U));
    fr = f_getfree("", &free_clusters, &mounted);
    printf("[FATFS] f_getfree returned: %d\n", (int)fr);
    if (fr == FR_OK && mounted != NULL) {
        uint64_t free_sectors = (uint64_t)free_clusters * mounted->csize;
        s_volume.free_bytes = free_sectors * FF_MAX_SS;
        if (s_volume.free_bytes > s_volume.total_bytes)
            s_volume.free_bytes = s_volume.total_bytes;
        s_volume.free_valid = 1U;
        /* 100% 只在 f_getfree 真正返回后显示，彻底离开 FatFs 内部回调。 */
        AppUI_RenderFreeScan(100U, HAL_GetTick() - s_free_scan_started);
        OLED_Wait_DMA();
    } else {
        printf("[FATFS] f_getfree failed: %d; Free=N/A\n", (int)fr);
        if (is_media_error(fr)) return fr;
    }

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
    uint32_t elapsed = HAL_GetTick() - frame_start;
    if (elapsed < APP_UI_FRAME_MS) HAL_Delay(APP_UI_FRAME_MS - elapsed);
}

/* 信息页最后一帧只等待到 3000 ms 边界，避免 16 ms 帧节流造成累计超时。 */
static void info_page_delay(uint32_t frame_start, uint32_t page_start)
{
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

static void wait_for_card(void)
{
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
                AppUI_ShowPopup("SD DETECTED", "Card is ready", APP_UI_POPUP_MS);
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
        AppUI_RenderPersistentError("UNSUPPORTED FS", "Use FAT/FAT32", frame - started);
        if ((int32_t)(frame - next_probe) >= 0) {
            if (!probe_card(&misses)) break;
            next_probe = frame + APP_CARD_PROBE_MS;
        }
        frame_delay(frame);
    }
}

static uint8_t wait_for_files(void)
{
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
                else AppUI_ShowPopup("SCAN FAILED", "Check filesystem", APP_UI_POPUP_MS);
                return 0U;
            }
            if (s_file_cnt > 0U) {
                AppUI_ShowPopup("FILES FOUND", "Open library", APP_UI_POPUP_MS);
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
    uint8_t rows = (uint8_t)((OLED_HEIGHT - y0) / 9U);
    return rows > 0U ? rows : 1U;
}

static uint8_t ui_select_file(uint8_t *sel_out)
{
    uint8_t sel = 0U, top = 0U, misses = 0U;
    uint8_t rows = ui_list_rows();
    uint32_t started = HAL_GetTick();
    uint32_t next_probe = started + APP_CARD_PROBE_MS;

    s_key_ok = 0U;
    for (;;) {
        uint32_t frame = HAL_GetTick();
        if (key_take(&s_key_up) && s_file_cnt > 0U)
            sel = sel == 0U ? (uint8_t)(s_file_cnt - 1U) : (uint8_t)(sel - 1U);
        if (key_take(&s_key_down) && s_file_cnt > 0U)
            sel = (uint8_t)((sel + 1U) % s_file_cnt);
        if (sel < top) top = sel;
        else if (sel >= (uint8_t)(top + rows)) top = (uint8_t)(sel - rows + 1U);

        if (key_take(&s_key_ok)) {
            *sel_out = sel;
            return 1U;
        }
        AppUI_RenderFileList(s_names, s_file_cnt, sel, top,
                             s_use_function_dir, frame - started);
        if ((int32_t)(frame - next_probe) >= 0) {
            if (!probe_card(&misses)) return 0U;
            next_probe = frame + APP_CARD_PROBE_MS;
        }
        frame_delay(frame);
    }
}
//==================== 视频播放 ====================
static uint8_t s_page[OLED_WIDTH];      /* 小尺寸视频只需一行源页缓冲 */

static void make_video_path(char path[32], const char *name)
{
    if (s_use_function_dir)
        (void)snprintf(path, 32, "/%s/%s", FN_DIR_NAME, name);
    else
        (void)snprintf(path, 32, "/%s", name);
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
                          uint8_t ox, uint8_t oy)
{
    UINT br;
    if (hdr->width == OLED_WIDTH && hdr->height == OLED_HEIGHT) {
        FRESULT fr = f_read(f, draw_buffer[0], fbytes, &br);
        return (fr == FR_OK && br == fbytes) ? FR_OK : ((fr == FR_OK) ? FR_DISK_ERR : fr);
    }

    OLED_GRAM_Clear();
    uint16_t source_pages = (uint16_t)((hdr->height + 7U) / 8U);
    for (uint16_t pg = 0; pg < source_pages; ++pg) {
        FRESULT fr = f_read(f, s_page, hdr->width, &br);
        if (fr != FR_OK || br != hdr->width) return (fr == FR_OK) ? FR_DISK_ERR : fr;
        compose_page(pg, hdr->width, hdr->height, ox, oy);
    }
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
    char path[32];
    make_video_path(path, fname);

    AppUI_ShowPopup("LOADING", fname, APP_UI_POPUP_MS);
    FRESULT fr = f_open(&f, path, FA_READ);
    if (fr != FR_OK) {
        if (is_media_error(fr)) media_invalidate("open", fr);
        else AppUI_ShowPopup("OPEN FAILED", fname, APP_UI_POPUP_MS);
        return;
    }

    fr = f_read(&f, &hdr, sizeof(hdr), &br);
    if (fr != FR_OK || br != sizeof(hdr) ||
        hdr.magic[0] != FN_MAGIC0 || hdr.magic[1] != FN_MAGIC1 ||
        hdr.magic[2] != FN_MAGIC2 || hdr.magic[3] != FN_MAGIC3)
    {
        (void)f_close(&f);
        if (fr != FR_OK && is_media_error(fr)) media_invalidate("header", fr);
        else AppUI_ShowPopup("BAD OVID", fname, APP_UI_POPUP_MS);
        return;
    }

    uint32_t fbytes = (uint32_t)((hdr.height + 7U) / 8U) * hdr.width;   /* 每帧字节数（页主序） */
    uint64_t expected_size = sizeof(hdr) + (uint64_t)hdr.frame_count * fbytes;
    uint64_t actual_size = (uint64_t)f_size(&f);
    if (hdr.width == 0U || hdr.height == 0U || hdr.width > OLED_WIDTH || hdr.height > OLED_HEIGHT ||
        hdr.frame_count == 0U || hdr.fps < 1U || hdr.fps > 120U ||
        expected_size != actual_size)
    {
        (void)f_close(&f);
        AppUI_ShowPopup((hdr.width > OLED_WIDTH || hdr.height > OLED_HEIGHT) ?
                        "FRAME TOO BIG" : "INVALID OVID", fname, APP_UI_POPUP_MS);
        printf("[PLAYER] reject %s: %ux%u frames=%lu fps=%u frame=%lu file=%lu size_bad=%u\n",
               path, hdr.width, hdr.height, (unsigned long)hdr.frame_count, hdr.fps,
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
            else AppUI_ShowPopup("SEEK FAILED", fname, APP_UI_POPUP_MS);
            return;
        }
        for (uint32_t i = 0; i < hdr.frame_count; ++i)
        {
            uint32_t t0 = HAL_GetTick();
            if (key_take(&s_key_ok)) {
                (void)f_close(&f);
                AppUI_ShowPopup("LIBRARY", "Playback stopped", APP_UI_POPUP_MS);
                return;
            }
            fr = read_frame(&f, &hdr, fbytes, ox, oy);
            if (fr != FR_OK) {
                (void)f_close(&f);
                if (is_media_error(fr)) media_invalidate("frame", fr);
                else AppUI_ShowPopup("READ FAILED", fname, APP_UI_POPUP_MS);
                return;
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

    for (;;) {
        s_media_lost = 0U;
        wait_for_card();

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
                AppUI_ShowPopup("MOUNT FAILED", "Check FAT volume", APP_UI_POPUP_MS);
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
                else AppUI_ShowPopup("SCAN FAILED", "Check filesystem", APP_UI_POPUP_MS);
                break;
            }
        }

        if (s_media_lost) show_removed_sequence();
    }
}
