#include <stdio.h>
#include <string.h>
#include <stdio.h>
#include "main.h"
#include "oled.hpp"
#include "app_ui.h"
#include "system_diag.h"

#define UI_FONT_SMALL "0806"
#define UI_FONT_MED   "1206"
#define UI_FONT_BIG   "1608"

typedef struct {
    char title[24];
    char detail[APP_UI_FILE_NAME_MAX];
    uint32_t started;
    uint32_t duration;
    uint8_t active;
    uint8_t classic;
} UiPopupState;

typedef struct {
    uint32_t window_started;
    uint32_t last_frame;
    uint16_t frames;
    uint16_t overruns;
    uint16_t max_interval;
    uint8_t initialized;
} UiFrameStats;

typedef struct {
    uint32_t last_elapsed;
    uint32_t selected_since;
    uint32_t move_started;
    int32_t highlight_from_q8;
    int32_t highlight_target_q8;
    uint16_t move_duration;
    uint8_t selected;
    uint8_t top;
    uint8_t count;
    uint8_t initialized;
} UiListAnimation;

static UiPopupState s_popup;
static UiFrameStats s_frame_stats;
static UiListAnimation s_list_anim;
static void ui_draw_popup_overlay(uint32_t elapsed, uint32_t duration);

static void ui_record_frame(void)
{
    uint32_t now = HAL_GetTick();
    if (!s_frame_stats.initialized) {
        s_frame_stats.initialized = 1U;
        s_frame_stats.window_started = now;
        s_frame_stats.last_frame = now;
        s_frame_stats.frames = 1U;
        return;
    }

    uint32_t interval = now - s_frame_stats.last_frame;
    s_frame_stats.last_frame = now;
    /* 视频播放或阻塞式故障恢复期间没有 UI 动画，重新出现 UI 时开启新窗口，
     * 不把这段非动画时间误报成掉帧。 */
    if (interval > 250U) {
        s_frame_stats.window_started = now;
        s_frame_stats.frames = 1U;
        s_frame_stats.overruns = 0U;
        s_frame_stats.max_interval = 0U;
        return;
    }
    if (interval > s_frame_stats.max_interval) {
        s_frame_stats.max_interval = interval > UINT16_MAX ? UINT16_MAX : (uint16_t)interval;
    }
    if (interval > APP_UI_FRAME_MS && s_frame_stats.overruns < UINT16_MAX)
        s_frame_stats.overruns++;
    if (s_frame_stats.frames < UINT16_MAX) s_frame_stats.frames++;

    uint32_t window_ms = now - s_frame_stats.window_started;
    if (window_ms >= 1000U) {
        uint32_t fps_x10 = (uint32_t)s_frame_stats.frames * 10000U / window_ms;
        printf("[UI] fps=%lu.%lu max=%u ms overruns=%u\n",
               (unsigned long)(fps_x10 / 10U), (unsigned long)(fps_x10 % 10U),
               s_frame_stats.max_interval, s_frame_stats.overruns);
        s_frame_stats.window_started = now;
        s_frame_stats.frames = 0U;
        s_frame_stats.overruns = 0U;
        s_frame_stats.max_interval = 0U;
    }
}

static void ui_present(void)
{
    if (s_popup.active) {
        uint32_t elapsed = HAL_GetTick() - s_popup.started;
        if (elapsed >= s_popup.duration) s_popup.active = 0U;
        else ui_draw_popup_overlay(elapsed, s_popup.duration);
    }
    OLED_Swap_Buffers();
    ui_record_frame();
}

static uint8_t ui_tiny_screen(void)
{
    return (OLED_WIDTH < 16U || OLED_HEIGHT < 16U) ? 1U : 0U;
}

static void ui_render_tiny(uint32_t elapsed_ms)
{
    OLED_GRAM_Clear();
    uint8_t x = (uint8_t)((elapsed_ms / 80U) % OLED_WIDTH);
    OLED_Draw_Point(x, (uint8_t)(OLED_HEIGHT / 2U));
    ui_present();
}

static uint8_t ui_font_w(const char *font)
{
    if (font[0] == '2') return 12U;
    if (font[0] == '1' && font[1] != '2') return 8U;
    return 6U;
}

static uint16_t ui_text_width(const char *text, const char *font)
{
    return (uint16_t)strlen(text) * ui_font_w(font);
}

/* OLED 字符接口只接受无符号坐标；滑动时按字符做安全裁剪。 */
static void ui_text(int16_t x, int16_t y, const char *text, const char *font)
{
    if (text == NULL || y < 0 || y >= OLED_HEIGHT) return;
    uint8_t step = ui_font_w(font);
    for (; *text; ++text, x += step) {
        if (x >= OLED_WIDTH) break;
        if (x >= 0 && (int16_t)(x + step) <= OLED_WIDTH)
            OLED_Show_Char_ASCII(*text, font, (uint8_t)x, (uint8_t)y);
    }
}

static void ui_text_clipped(int16_t x, int16_t y, const char *text, const char *font,
                            int16_t clip_left, int16_t clip_right)
{
    if (text == NULL || y < 0 || y >= OLED_HEIGHT || clip_right <= clip_left) return;
    uint8_t step = ui_font_w(font);
    for (; *text; ++text, x += step) {
        if (x >= clip_right || x >= OLED_WIDTH) break;
        if (x >= clip_left && x >= 0 && (int16_t)(x + step) <= clip_right &&
            (int16_t)(x + step) <= OLED_WIDTH)
            OLED_Show_Char_ASCII(*text, font, (uint8_t)x, (uint8_t)y);
    }
}

static void ui_text_center(int16_t xoff, int16_t y, const char *text, const char *font)
{
    int16_t x = (int16_t)(((int32_t)OLED_WIDTH - ui_text_width(text, font)) / 2) + xoff;
    ui_text(x, y, text, font);
}

static void ui_format_size(uint64_t bytes, char *out, size_t out_size)
{
    uint32_t mib = (uint32_t)(bytes >> 20);
    if (mib >= 1024U)
        (void)snprintf(out, out_size, "%lu.%lu GB", (unsigned long)(mib / 1024U),
                       (unsigned long)((mib % 1024U) * 10U / 1024U));
    else
        (void)snprintf(out, out_size, "%lu MB", (unsigned long)mib);
}

static void ui_format_spi(uint32_t hz, char *out, size_t out_size)
{
    if (hz >= 1000000U)
        (void)snprintf(out, out_size, "%lu.%luM", (unsigned long)(hz / 1000000U),
                       (unsigned long)((hz % 1000000U) / 100000U));
    else
        (void)snprintf(out, out_size, "%luk", (unsigned long)(hz / 1000U));
}

static void ui_panel(int16_t x, int16_t y, int16_t w, int16_t h)
{
    if (w < 4 || h < 4) return;
    OLED_Draw_Rectang(x, y, w - 1, h - 1, 0);
    if (w > 8 && h > 8) {
        OLED_Draw_Point((uint8_t)((x + 2 < 0) ? 0 : x + 2), (uint8_t)((y + 2 < 0) ? 0 : y + 2));
        OLED_Draw_Point((uint8_t)((x + w - 3 < 0) ? 0 : x + w - 3),
                        (uint8_t)((y + h - 3 < 0) ? 0 : y + h - 3));
    }
}

static void ui_progress_scaled(int16_t x, int16_t y, int16_t w,
                               uint16_t value, uint16_t maximum)
{
    if (w < 6 || y < 0 || y + 5 > OLED_HEIGHT || maximum == 0U) return;
    if (value > maximum) value = maximum;
    OLED_Draw_Rectang(x, y, w - 1, 4, 0);
    int16_t fill = (int16_t)((uint32_t)(w - 4) * value / maximum);
    if (fill > 0) OLED_Draw_Rectang(x + 2, y + 2, fill, 1, 1);
}

static void ui_progress(int16_t x, int16_t y, int16_t w, uint8_t percent)
{
    ui_progress_scaled(x, y, w, percent > 100U ? 100U : percent, 100U);
}

/* 与拔卡页完全相同的横向反显：白色区域从左向右扩张，已经扫过的
 * 区域保持反显，最终整页成为白底黑字，而不是一条光带滑出屏幕。 */
static void ui_invert_reveal(uint32_t elapsed_ms, uint32_t duration_ms)
{
    if (duration_ms == 0U) return;
    if (elapsed_ms > duration_ms) elapsed_ms = duration_ms;
    int16_t width = (int16_t)((uint32_t)OLED_WIDTH * elapsed_ms / duration_ms);
    if (width > 0) OLED_SW_Invert_Rect(0, 0, width, OLED_HEIGHT);
}

static void ui_format_frame_count(uint32_t count, char *text, size_t text_size)
{
    if (count < 10000UL)
        (void)snprintf(text, text_size, "%lu", (unsigned long)count);
    else if (count < 1000000UL)
        (void)snprintf(text, text_size, "%luK", (unsigned long)(count / 1000UL));
    else if (count < 1000000000UL)
        (void)snprintf(text, text_size, "%luM", (unsigned long)(count / 1000000UL));
    else
        (void)snprintf(text, text_size, "%luG", (unsigned long)(count / 1000000000UL));
}

static void ui_draw_card_icon(int16_t x, int16_t y, int16_t w, int16_t h)
{
    if (w < 8 || h < 10) return;
    int16_t cut = (w >= 18) ? 5 : 3;
    OLED_Draw_Line(x, y, w - cut - 1, 0, 0);
    OLED_Draw_Line(x + w - cut - 1, y, cut, cut, 0);
    OLED_Draw_Line(x + w - 1, y + cut, 0, h - cut - 1, 0);
    OLED_Draw_Line(x, y + h - 1, w - 1, 0, 0);
    OLED_Draw_Line(x, y, 0, h - 1, 0);
    uint8_t contacts = (w >= 18) ? 4U : 3U;
    for (uint8_t i = 0; i < contacts; ++i) {
        int16_t cx = x + 3 + (int16_t)i * ((w - 6) / contacts);
        OLED_Draw_Line(cx, y + h - 6, 0, 3, 0);
    }
}

static void ui_page_header(const char *title, uint8_t page, int16_t xoff)
{
    ui_text(3 + xoff, 1, title, UI_FONT_SMALL);
    OLED_Draw_Line(xoff, 10, OLED_WIDTH - 1, 0, 0);
    if (OLED_WIDTH >= 20U) {
        int16_t first = (int16_t)OLED_WIDTH - 17 + xoff;
        for (uint8_t p = 0; p < APP_UI_INFO_PAGES; ++p)
            OLED_Draw_Rectang(first + p * 5, 3, 2, 2, (p == page) ? 1 : 0);
    }
}

void AppUI_Init(void)
{
    OLED_Select_Buffer(1U);
}

void AppUI_RenderWaitCard(uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    uint16_t frame = (uint16_t)(elapsed_ms / APP_UI_FRAME_MS);
    uint8_t compact = (OLED_HEIGHT < 48U);
    int16_t icon_h = compact ? (int16_t)(OLED_HEIGHT - 11U) : 30;
    int16_t icon_w = compact ? 15 : 24;
    int16_t icon_y = compact ? 2 : 5;
    ui_draw_card_icon(5, icon_y, icon_w, icon_h);
    ui_text(icon_w + 12, compact ? 3 : 8, "Insert", compact ? UI_FONT_SMALL : UI_FONT_MED);
    ui_text(icon_w + 12, compact ? 13 : 22, "SD card", compact ? UI_FONT_SMALL : UI_FONT_MED);

    int16_t tx = 5;
    int16_t ty = OLED_HEIGHT - 8;
    int16_t tw = OLED_WIDTH - 10;
    if (tw >= 12) {
        OLED_Draw_Rectang(tx, ty, tw - 1, 5, 0);
        int16_t seg = (tw > 34) ? 20 : (tw / 3);
        int16_t span = tw - 4 - seg;
        int16_t pos = 0;
        if (span > 0) {
            uint16_t phase = (uint16_t)((frame * 2U) % (uint16_t)(span * 2));
            pos = (phase <= span) ? phase : (span * 2 - phase);
        }
        OLED_Draw_Rectang(tx + 2 + pos, ty + 2, seg, 1, 1);
    }
    ui_present();
}

void AppUI_RenderAnalyzing(uint32_t elapsed_ms, const char *detail)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    int16_t w = (OLED_WIDTH > 12U) ? OLED_WIDTH - 10 : OLED_WIDTH;
    int16_t h = (OLED_HEIGHT >= 48U) ? 38 : OLED_HEIGHT - 4;
    int16_t x = (OLED_WIDTH - w) / 2;
    int16_t y = (OLED_HEIGHT - h) / 2;
    ui_panel(x, y, w, h);
    ui_text_center(0, y + 5, "Analyzing", (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
    if (detail && h >= 28) ui_text_center(0, y + 19, detail, UI_FONT_SMALL);
    int16_t bar_y = y + h - 8;
    int16_t bar_w = w - 10;
    if (bar_w >= 8) {
        OLED_Draw_Rectang(x + 5, bar_y, bar_w - 1, 4, 0);
        int16_t seg = (bar_w > 24) ? 14 : 4;
        int16_t span = bar_w - seg - 3;
        int16_t pos = (span > 0) ? (int16_t)((elapsed_ms / 20U) % (uint32_t)(span + 1)) : 0;
        OLED_Draw_Rectang(x + 7 + pos, bar_y + 2, seg, 1, 1);
    }
    ui_present();
}

void AppUI_RenderFreeScan(uint16_t display_permille, uint16_t target_permille,
                          uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    if (display_permille > 1000U) display_permille = 1000U;
    if (target_permille > 1000U) target_permille = 1000U;
    uint8_t percent = (uint8_t)((display_permille + 5U) / 10U);

    OLED_GRAM_Clear();
    uint8_t compact = (OLED_HEIGHT < 48U);
    int16_t x = compact ? 5 : 4;
    int16_t y = 2;
    int16_t w = OLED_WIDTH - (compact ? 10 : 8);
    int16_t h = OLED_HEIGHT - 4;
    char line[20];

    ui_panel(x, y, w, h);
    ui_text_center(0, y + (compact ? 3 : 4), "Free space",
                   compact ? UI_FONT_SMALL : UI_FONT_MED);
    (void)snprintf(line, sizeof(line), "Scanning FAT %u%%", percent);
    ui_text_center(0, y + (compact ? 13 : 19), line, UI_FONT_SMALL);

    int16_t bar_x = x + 8;
    int16_t bar_y = compact ? (int16_t)OLED_HEIGHT - 8 : y + 31;
    int16_t bar_w = w - 16;
    ui_progress_scaled(bar_x, bar_y, bar_w, display_permille, 1000U);
    if (bar_w > 6) {
        int16_t target_x = (int16_t)(bar_x + 2 +
                           (uint32_t)(bar_w - 4) * target_permille / 1000U);
        if (target_x >= bar_x + bar_w - 1) target_x = bar_x + bar_w - 2;
        OLED_Draw_Point((uint8_t)target_x, (uint8_t)(bar_y + 1));
    }
    if (!compact) ui_text_center(0, y + 43, "OK: Skip", UI_FONT_SMALL);

    /* 进度不变时仍有一个往返光点，明确表示系统没有死机。 */
    if (bar_w > 12) {
        int16_t span = bar_w - 6;
        uint16_t phase = (uint16_t)((elapsed_ms / APP_UI_FRAME_MS) % (uint32_t)(span * 2));
        int16_t pos = (phase <= span) ? (int16_t)phase : (int16_t)(span * 2 - phase);
        OLED_Draw_Point((uint8_t)(bar_x + 3 + pos),
                        (uint8_t)(compact ? bar_y + 7 : y + h - 4));
    }
    ui_present();
}

static const char *ui_card_type(uint8_t type)
{
    switch (type) {
        case SD_TYPE_V1: return "SDSC V1";
        case SD_TYPE_V2: return "SDSC V2";
        case SD_TYPE_V2HC: return "SDHC/SDXC";
        default: return "Unknown";
    }
}

void AppUI_RenderInfoPage(uint8_t page, const SD_CardInfo *card,
                          const AppUI_VolumeInfo *volume, uint32_t spi_hz,
                          uint32_t elapsed_ms)
{
    if (card == NULL || volume == NULL) return;
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    int16_t xo = 0;
    uint8_t compact = (OLED_HEIGHT < 48U);
    char line[28], size_a[16], size_b[16], spi[10];
    ui_format_spi(spi_hz, spi, sizeof(spi));

    if (page == 0U) {
        ui_page_header("Storage", page, xo);
        ui_format_size(volume->total_bytes, size_a, sizeof(size_a));
        if (volume->free_valid) ui_format_size(volume->free_bytes, size_b, sizeof(size_b));
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s  %s", volume->fs_name, size_a);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Free %s", volume->free_valid ? size_b : "N/A");
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            (void)snprintf(line, sizeof(line), "FS    : %s", volume->fs_name);
            ui_text(3 + xo, 14, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Total : %s", size_a);
            ui_text(3 + xo, 25, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Free  : %s", volume->free_valid ? size_b : "N/A");
            ui_text(3 + xo, 36, line, UI_FONT_SMALL);
        }
        if (volume->free_valid && volume->total_bytes > 0U) {
            uint64_t free_bytes = volume->free_bytes;
            if (free_bytes > volume->total_bytes) free_bytes = volume->total_bytes;
            uint8_t used = (uint8_t)(100U - (free_bytes * 100U / volume->total_bytes));
            ui_progress(3 + xo, compact ? 27 : 50, OLED_WIDTH - 6, used);
            if (!compact) {
                (void)snprintf(line, sizeof(line), "Used %u%%", used);
                ui_text(OLED_WIDTH - 54 + xo, 56, line, UI_FONT_SMALL);
            }
        }
    } else if (page == 1U) {
        ui_page_header("Card", page, xo);
        ui_format_size((uint64_t)card->capacity_mb << 20, size_a, sizeof(size_a));
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s %s", ui_card_type(card->type), size_a);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "%s  SPI:%s", card->block_addr ? "LBA" : "Byte", spi);
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            ui_text(3 + xo, 14, ui_card_type(card->type), UI_FONT_MED);
            (void)snprintf(line, sizeof(line), "Cap   : %s", size_a);
            ui_text(3 + xo, 29, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Addr:%s SPI:%s",
                           card->block_addr ? "LBA" : "Byte", spi);
            ui_text(3 + xo, 40, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Blocks: %lu", (unsigned long)card->block_count);
            ui_text(3 + xo, 51, line, UI_FONT_SMALL);
        }
    } else {
        char oid[3], pnm[6];
        for (uint8_t i = 0; i < 2U; ++i) {
            uint8_t c = card->cid_raw[1U + i]; oid[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.';
        }
        oid[2] = '\0';
        for (uint8_t i = 0; i < 5U; ++i) {
            uint8_t c = card->cid_raw[3U + i]; pnm[i] = (c >= 0x20U && c < 0x7FU) ? (char)c : '.';
        }
        pnm[5] = '\0';
        uint32_t psn = ((uint32_t)card->cid_raw[9] << 24) | ((uint32_t)card->cid_raw[10] << 16)
                     | ((uint32_t)card->cid_raw[11] << 8) | card->cid_raw[12];
        uint16_t mdt = (uint16_t)(((uint16_t)(card->cid_raw[13] & 0x0FU) << 8) | card->cid_raw[14]);
        ui_page_header("Identity", page, xo);
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s V%u.%u  OID:%s", pnm,
                           card->cid_raw[8] >> 4, card->cid_raw[8] & 0x0FU, oid);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "SN:%08lX", (unsigned long)psn);
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            (void)snprintf(line, sizeof(line), "Name : %s V%u.%u", pnm,
                           card->cid_raw[8] >> 4, card->cid_raw[8] & 0x0FU);
            ui_text(3 + xo, 14, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "MID  : %02X  OID:%s", card->cid_raw[0], oid);
            ui_text(3 + xo, 25, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "SN   : %08lX", (unsigned long)psn);
            ui_text(3 + xo, 36, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "Date : %04u-%02u", 2000U + (mdt >> 4), mdt & 0x0FU);
            ui_text(3 + xo, 47, line, UI_FONT_SMALL);
        }
    }

    ui_invert_reveal(elapsed_ms < 300U ? elapsed_ms : 300U, 300U);
    ui_present();
}

static int32_t ui_list_highlight_q8(uint32_t elapsed_ms)
{
    uint32_t elapsed = elapsed_ms - s_list_anim.move_started;
    if (s_list_anim.move_duration == 0U || elapsed >= s_list_anim.move_duration)
        return s_list_anim.highlight_target_q8;

    uint32_t t = elapsed * 256U / s_list_anim.move_duration;
    uint32_t eased = 2U * t - (t * t / 256U);
    int32_t distance = s_list_anim.highlight_target_q8 - s_list_anim.highlight_from_q8;
    return s_list_anim.highlight_from_q8 + (int32_t)((int64_t)distance * eased / 256);
}

static int16_t ui_list_prepare_animation(uint8_t count, uint8_t selected, uint8_t top,
                                         uint8_t y0, uint32_t elapsed_ms)
{
    int32_t target_q8 = ((int32_t)y0 + (int32_t)(selected - top) * 9) << 8;
    uint8_t reset = !s_list_anim.initialized || elapsed_ms < s_list_anim.last_elapsed ||
                    count != s_list_anim.count || selected < top;

    if (reset) {
        (void)memset(&s_list_anim, 0, sizeof(s_list_anim));
        s_list_anim.initialized = 1U;
        s_list_anim.selected = selected;
        s_list_anim.top = top;
        s_list_anim.count = count;
        s_list_anim.selected_since = elapsed_ms;
        s_list_anim.move_started = elapsed_ms;
        s_list_anim.highlight_from_q8 = target_q8;
        s_list_anim.highlight_target_q8 = target_q8;
    } else if (selected != s_list_anim.selected || top != s_list_anim.top) {
        int32_t current_q8 = ui_list_highlight_q8(elapsed_ms);
        uint8_t rapid_move = (elapsed_ms - s_list_anim.move_started) <= 170U;
        s_list_anim.selected_since = elapsed_ms;
        s_list_anim.selected = selected;
        s_list_anim.count = count;
        if (top != s_list_anim.top) {
            s_list_anim.highlight_from_q8 = target_q8;
            s_list_anim.highlight_target_q8 = target_q8;
            s_list_anim.move_duration = 0U;
        } else {
            s_list_anim.highlight_from_q8 = current_q8;
            s_list_anim.highlight_target_q8 = target_q8;
            s_list_anim.move_duration = rapid_move ? 55U : 110U;
        }
        s_list_anim.top = top;
        s_list_anim.move_started = elapsed_ms;
    }
    s_list_anim.last_elapsed = elapsed_ms;
    int32_t y_q8 = ui_list_highlight_q8(elapsed_ms);
    return (int16_t)((y_q8 + 128) >> 8);
}

static int16_t ui_selected_name_offset(const char *name, int16_t available_width,
                                       uint32_t selected_age)
{
    int16_t travel = (int16_t)ui_text_width(name, UI_FONT_SMALL) - available_width;
    if (travel <= 0 || selected_age < 700U) return 0;

    uint32_t move_ms = (uint32_t)travel * 35U;
    uint32_t cycle_ms = move_ms + 500U + move_ms + 500U;
    uint32_t phase = (selected_age - 700U) % cycle_ms;
    if (phase < move_ms) return (int16_t)(phase / 35U);
    phase -= move_ms;
    if (phase < 500U) return travel;
    phase -= 500U;
    if (phase < move_ms) return (int16_t)(travel - (int16_t)(phase / 35U));
    return 0;
}

static void ui_draw_inverse_status(uint8_t enabled)
{
    const char *label = (OLED_WIDTH >= 112U) ?
                        (enabled ? "Inv on" : "Inv off") :
                        (enabled ? "I1" : "I0");
    int16_t width = (int16_t)ui_text_width(label, UI_FONT_SMALL);
    int16_t x = (int16_t)OLED_WIDTH - width - 2;
    if (x < 0) x = 0;
    ui_text(x, 1, label, UI_FONT_SMALL);
    if (enabled)
        OLED_SW_Invert_Rect(x > 0 ? x - 1 : 0, 0,
                            width + (x > 0 ? 2 : 1), 9);
}

void AppUI_RenderFileList(const char names[][APP_UI_FILE_NAME_MAX], uint8_t count, uint8_t selected,
                          uint8_t top, uint8_t inverse_enabled, const AppUI_VideoMeta *meta,
                          uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    uint8_t y0 = (OLED_HEIGHT >= 24U) ? 11U : 0U;
    uint8_t footer = (OLED_HEIGHT >= 48U) ? 9U : 0U;
    uint8_t rows = (uint8_t)((OLED_HEIGHT - y0 - footer) / 9U);
    if (rows == 0U) rows = 1U;
    if (y0 != 0U) {
        char title[18];
        (void)snprintf(title, sizeof(title), "Files %u", count);
        ui_text(2, 1, title, UI_FONT_SMALL);
        ui_draw_inverse_status(inverse_enabled);
        OLED_Draw_Line(0, 9, OLED_WIDTH - 1, 0, 0);
    }
    int16_t name_left = 8;
    int16_t name_right = OLED_WIDTH > 12U ? OLED_WIDTH - 4 : OLED_WIDTH;
    int16_t highlight_y = ui_list_prepare_animation(count, selected, top, y0, elapsed_ms);
    uint32_t selected_age = elapsed_ms - s_list_anim.selected_since;

    for (uint8_t row = 0; row < rows; ++row) {
        uint8_t idx = (uint8_t)(top + row);
        if (idx >= count) break;
        uint8_t y = (uint8_t)(y0 + row * 9U);
        int16_t offset = idx == selected ?
                         ui_selected_name_offset(names[idx], name_right - name_left, selected_age) : 0;
        ui_text_clipped(name_left - offset, y, names[idx], UI_FONT_SMALL,
                        name_left, name_right);
    }
    OLED_SW_Invert_Rect(2, highlight_y,
                        (OLED_WIDTH > 8U) ? OLED_WIDTH - 7 : OLED_WIDTH, 8);
    OLED_Draw_Line(3, highlight_y + 2, 3, 2, 0);
    OLED_Draw_Line(3, highlight_y + 6, 3, -2, 0);
    if (count > rows && OLED_WIDTH >= 4U) {
        uint8_t track = (uint8_t)(OLED_HEIGHT - y0 - footer);
        uint8_t knob = (uint8_t)((uint16_t)track * rows / count);
        if (knob < 3U) knob = 3U;
        uint8_t ky = (uint8_t)(y0 + (uint16_t)(track - knob) * top / (count - rows));
        OLED_Draw_Line(OLED_WIDTH - 2, y0, 0, track - 1, 0);
        OLED_Draw_Rectang(OLED_WIDTH - 3, ky, 2, knob - 1, 1);
    }
    if (footer && meta != NULL && selected < count) {
        char info[28];
        char frame_count[6];
        uint32_t page_phase = selected_age % 1500U;
        uint8_t info_page = (uint8_t)((selected_age / 1500U) & 1U);
        int16_t reveal_right = OLED_WIDTH - 2;
        if (!meta[selected].valid) {
            info_page = 0U;
            page_phase = selected_age < 160U ? selected_age : 160U;
        }
        if (page_phase < 160U)
            reveal_right = (int16_t)(2 + (uint32_t)(OLED_WIDTH - 4) * page_phase / 160U);
        OLED_Draw_Line(0, OLED_HEIGHT - footer - 1, OLED_WIDTH - 1, 0, 0);
        if (meta[selected].valid) {
            ui_format_frame_count(meta[selected].frames, frame_count, sizeof(frame_count));
            if (info_page == 0U)
                (void)snprintf(info, sizeof(info), "%ux%u %u fps",
                               meta[selected].width, meta[selected].height, meta[selected].fps);
            else
                (void)snprintf(info, sizeof(info), "%s frames V%u",
                               frame_count, meta[selected].version);
        } else {
            (void)snprintf(info, sizeof(info), "OVID info N/A");
        }
        ui_text_clipped(2, OLED_HEIGHT - 8, info, UI_FONT_SMALL, 2, reveal_right);
    }
    ui_present();
}

void AppUI_RenderEmpty(uint8_t function_dir, uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    int16_t w = (OLED_WIDTH >= 48U) ? 30 : OLED_WIDTH / 3;
    int16_t h = (OLED_HEIGHT >= 40U) ? 22 : OLED_HEIGHT / 2;
    int16_t x = (OLED_WIDTH - w) / 2;
    int16_t y = (OLED_HEIGHT - h) / 2 - 5;
    OLED_Draw_Rectang(x, y + 4, w - 1, h - 5, 0);
    OLED_Draw_Line(x + 2, y, w / 2, 0, 0);
    OLED_Draw_Line(x + 2, y, 0, 4, 0);
    ui_text_center(0, OLED_HEIGHT >= 40U ? OLED_HEIGHT - 14 : OLED_HEIGHT - 8,
                   function_dir ? "No .BIN in /FN" : "No .BIN files", UI_FONT_SMALL);
    uint8_t dots = (uint8_t)((elapsed_ms / 350U) % 4U);
    for (uint8_t i = 0; i < dots; ++i)
        OLED_Draw_Circle((int16_t)(OLED_WIDTH / 2 - 5 + i * 5), y + h + 1, 1, 1);
    ui_present();
}

void AppUI_RenderPersistentError(const char *title, const char *detail, uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    uint8_t pulse = (uint8_t)((elapsed_ms / 400U) & 1U);
    int16_t x = 4, y = 4, w = OLED_WIDTH - 8, h = OLED_HEIGHT - 8;
    ui_panel(x, y, w, h);
    OLED_Draw_Circle(x + 10, y + 10, 6, 0);
    OLED_Draw_Line(x + 10, y + 6, 0, 5, 0);
    if (pulse) OLED_Draw_Point((uint8_t)(x + 10), (uint8_t)(y + 14));
    ui_text(x + 21, y + 5, title, (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
    if (OLED_HEIGHT >= 28U) ui_text_center(0, y + h - 12, detail, UI_FONT_SMALL);
    ui_present();
}

void AppUI_RenderRemoved(uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    ui_text_center(0, (OLED_HEIGHT >= 48U) ? 13 : 5, "Card removed",
                   (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
    ui_text_center(0, (OLED_HEIGHT >= 48U) ? 32 : 16, "Reinsert SD", UI_FONT_SMALL);
    uint32_t phase = (elapsed_ms > 600U) ? 600U : elapsed_ms;
    int16_t w = (int16_t)((uint32_t)OLED_WIDTH * phase / 600U);
    if (w > 0) OLED_SW_Invert_Rect(0, 0, w, OLED_HEIGHT);
    ui_present();
}

void AppUI_RenderDiagnostics(uint8_t page, uint8_t key_mask, int16_t sd_test_result,
                             uint32_t elapsed_ms)
{
    (void)elapsed_ms;
    OLED_GRAM_Clear();
    char line[40];
    ui_page_header("Diagnostics", (uint8_t)(page % APP_UI_INFO_PAGES), 0);
    if (page == 0U) {
        ui_text(2, 13, "FW V1.2.1", UI_FONT_SMALL);
        (void)snprintf(line, sizeof(line), "Reset:%s State:%u",
                       SystemDiag_WasWatchdogReset() ? "IWDG" : "Normal",
                       (unsigned int)SystemDiag_GetState());
        ui_text(2, 24, line, UI_FONT_SMALL);
        (void)snprintf(line, sizeof(line), "Flash:%lu RAM:%lu",
                       (unsigned long)SystemDiag_GetFlashBytes(),
                       (unsigned long)SystemDiag_GetStaticRamBytes());
        ui_text(2, 35, line, UI_FONT_SMALL);
        (void)snprintf(line, sizeof(line), "Stack:%lu Key:%u%u%u",
                       (unsigned long)SystemDiag_GetStackMargin(),
                       (key_mask >> 2U) & 1U, (key_mask >> 1U) & 1U, key_mask & 1U);
        ui_text(2, 46, line, UI_FONT_SMALL);
    } else if (page == 1U) {
        uint32_t spi_hz = 0U;
        if (g_sd_card.io.get_bus_clk && g_sd_card.io.get_prescaler) {
            uint32_t divider = 2UL << (g_sd_card.io.get_prescaler() >> 3U);
            if (divider) spi_hz = g_sd_card.io.get_bus_clk() / divider;
        }
        (void)snprintf(line, sizeof(line), "SD:%s T:%u E:%lu",
                       g_sd_card.info.initialized ? "Ready" : "Wait",
                       g_sd_card.info.type, (unsigned long)SystemDiag_GetSdErrorCount());
        ui_text(2, 13, line, UI_FONT_SMALL);
        (void)snprintf(line, sizeof(line), "SPI:%luk I2C:%luk D:%u",
                       (unsigned long)(spi_hz / 1000U),
                       (unsigned long)(OLED_Get_I2C_Clock() / 1000U), OLED_DMA_Busy);
        ui_text(2, 24, line, UI_FONT_SMALL);
        if (sd_test_result == INT16_MIN)
            (void)snprintf(line, sizeof(line), "SD test: OK key");
        else if (sd_test_result == 0)
            (void)snprintf(line, sizeof(line), "SD test: Pass");
        else
            (void)snprintf(line, sizeof(line), "SD test: Fail %d", sd_test_result);
        ui_text(2, 35, line, UI_FONT_SMALL);
        (void)snprintf(line, sizeof(line), "I2C err:%lu T:%lu",
                       (unsigned long)OLED_Get_I2C_Error_Count(),
                       (unsigned long)OLED_Get_I2C_Timeout_Count());
        ui_text(2, 46, line, UI_FONT_SMALL);
    } else {
        const SystemFaultRecord *fault = SystemDiag_GetFaultRecord();
        if (SystemDiag_HasFaultRecord()) {
            (void)snprintf(line, sizeof(line), "PC:%08lX", (unsigned long)fault->stacked_pc);
            ui_text(2, 13, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "LR:%08lX", (unsigned long)fault->stacked_lr);
            ui_text(2, 24, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "CFSR:%08lX", (unsigned long)fault->cfsr);
            ui_text(2, 35, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "State:%lu %.10s",
                           (unsigned long)fault->app_state, fault->current_file);
            ui_text(2, 46, line, UI_FONT_SMALL);
        } else {
            ui_text_center(0, 28, "No saved fault", UI_FONT_SMALL);
        }
    }
    if (OLED_HEIGHT >= 64U)
        ui_text_center(0, 56, page == 1U ? "OK SD test  Up/Dn" : "Up/Dn page  OK exit", UI_FONT_SMALL);
    ui_present();
}

static void ui_draw_popup_overlay(uint32_t elapsed, uint32_t duration)
{
    if (ui_tiny_screen()) return;
    if (!s_popup.classic) {
        const uint32_t reveal_ms = 300U;
        uint8_t compact = OLED_HEIGHT < 48U;
        OLED_GRAM_Clear();
        ui_text_center(0, compact ? 5 : 13, s_popup.title,
                       compact ? UI_FONT_SMALL : UI_FONT_MED);
        if (s_popup.detail[0])
            ui_text_center(0, compact ? 17 : 32, s_popup.detail, UI_FONT_SMALL);
        ui_invert_reveal(elapsed < reveal_ms ? elapsed : reveal_ms, reveal_ms);
        return;
    }

    int16_t target_w = (OLED_WIDTH > 10U) ? OLED_WIDTH - 10 : OLED_WIDTH;
    int16_t target_h = (OLED_HEIGHT >= 48U) ? 38 : OLED_HEIGHT - 4;
    uint32_t edge = 180U;
    uint32_t scale = 100U;

    if (elapsed < edge) scale = elapsed * 100U / edge;
    else if (duration > edge && elapsed > duration - edge)
        scale = (duration - elapsed) * 100U / edge;
    if (scale > 100U) scale = 100U;

    int16_t w = (int16_t)((uint32_t)target_w * scale / 100U);
    int16_t h = (int16_t)((uint32_t)target_h * scale / 100U);
    if (w < 4 || h < 4) return;
    int16_t x = (OLED_WIDTH - w) / 2;
    int16_t y = (OLED_HEIGHT - h) / 2;
    OLED_Clear_Rect(x, y, w, h);
    ui_panel(x, y, w, h);
    if (scale >= 72U) {
        ui_text_center(0, y + 5, s_popup.title,
                       (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
        if (s_popup.detail[0] && h >= 27)
            ui_text_center(0, y + h - 12, s_popup.detail, UI_FONT_SMALL);
    }
}

static void ui_start_popup(const char *title, const char *detail,
                           uint32_t duration_ms, uint8_t classic)
{
    if (duration_ms < 2U) duration_ms = 2U;
    (void)snprintf(s_popup.title, sizeof(s_popup.title), "%s", title ? title : "");
    (void)snprintf(s_popup.detail, sizeof(s_popup.detail), "%s", detail ? detail : "");
    s_popup.started = HAL_GetTick();
    s_popup.duration = duration_ms;
    s_popup.classic = classic;
    s_popup.active = 1U;
}

void AppUI_ShowPopup(const char *title, const char *detail, uint32_t duration_ms)
{
    ui_start_popup(title, detail, duration_ms, 0U);
}

void AppUI_ShowClassicPopup(const char *title, const char *detail, uint32_t duration_ms)
{
    ui_start_popup(title, detail, duration_ms, 1U);
}

uint8_t AppUI_PopupActive(void)
{
    if (s_popup.active && HAL_GetTick() - s_popup.started >= s_popup.duration)
        s_popup.active = 0U;
    return s_popup.active;
}

void AppUI_PopupCancel(void) { s_popup.active = 0U; }

void AppUI_RenderPopupTask(void)
{
    OLED_GRAM_Clear();
    if (AppUI_PopupActive())
        ui_draw_popup_overlay(HAL_GetTick() - s_popup.started, s_popup.duration);
    OLED_Swap_Buffers();
    ui_record_frame();
}
