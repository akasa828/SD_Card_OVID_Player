#include <stdio.h>
#include <string.h>
#include "main.h"
#include "oled.hpp"
#include "app_ui.h"

#define UI_FONT_SMALL "0806"
#define UI_FONT_MED   "1206"
#define UI_FONT_BIG   "1608"

static uint8_t ui_tiny_screen(void)
{
    return (OLED_WIDTH < 16U || OLED_HEIGHT < 16U) ? 1U : 0U;
}

static void ui_render_tiny(uint32_t elapsed_ms)
{
    OLED_GRAM_Clear();
    uint8_t x = (uint8_t)((elapsed_ms / 80U) % OLED_WIDTH);
    OLED_Draw_Point(x, (uint8_t)(OLED_HEIGHT / 2U));
    OLED_Swap_Buffers();
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

static void ui_progress(int16_t x, int16_t y, int16_t w, uint8_t percent)
{
    if (w < 6 || y < 0 || y + 5 > OLED_HEIGHT) return;
    if (percent > 100U) percent = 100U;
    OLED_Draw_Rectang(x, y, w - 1, 4, 0);
    int16_t fill = (int16_t)((uint32_t)(w - 4) * percent / 100U);
    if (fill > 0) OLED_Draw_Rectang(x + 2, y + 2, fill, 1, 1);
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

static int16_t ui_page_offset(uint32_t elapsed_ms)
{
    if (elapsed_ms < 300U)
        return (int16_t)((uint32_t)OLED_WIDTH * (300U - elapsed_ms) / 300U);
    if (elapsed_ms >= 2700U)
        return -(int16_t)((uint32_t)OLED_WIDTH * (elapsed_ms - 2700U) / 300U);
    return 0;
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
    ui_text(icon_w + 12, compact ? 3 : 8, "INSERT", compact ? UI_FONT_SMALL : UI_FONT_MED);
    ui_text(icon_w + 12, compact ? 13 : 22, "SD CARD", compact ? UI_FONT_SMALL : UI_FONT_MED);

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
    OLED_Swap_Buffers();
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
    ui_text_center(0, y + 5, "ANALYZING", (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
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
    OLED_Swap_Buffers();
}

void AppUI_RenderFreeScan(uint8_t percent, uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    if (percent > 100U) percent = 100U;

    OLED_GRAM_Clear();
    uint8_t compact = (OLED_HEIGHT < 48U);
    int16_t x = 5;
    int16_t y = compact ? 2 : 6;
    int16_t w = OLED_WIDTH - 10;
    int16_t h = OLED_HEIGHT - (compact ? 4 : 12);
    char line[20];

    ui_panel(x, y, w, h);
    ui_text_center(0, y + (compact ? 3 : 6), "FREE SPACE",
                   compact ? UI_FONT_SMALL : UI_FONT_MED);
    (void)snprintf(line, sizeof(line), "SCANNING FAT %u%%", percent);
    ui_text_center(0, y + (compact ? 13 : 23), line, UI_FONT_SMALL);

    int16_t bar_x = x + 8;
    int16_t bar_y = compact ? (int16_t)OLED_HEIGHT - 8 : y + h - 12;
    int16_t bar_w = w - 16;
    ui_progress(bar_x, bar_y, bar_w, percent);

    /* 进度不变时仍有一个往返光点，明确表示系统没有死机。 */
    if (bar_w > 12) {
        int16_t span = bar_w - 6;
        uint16_t phase = (uint16_t)((elapsed_ms / 24U) % (uint32_t)(span * 2));
        int16_t pos = (phase <= span) ? (int16_t)phase : (int16_t)(span * 2 - phase);
        OLED_Draw_Point((uint8_t)(bar_x + 3 + pos), (uint8_t)(bar_y + 7));
    }
    OLED_Swap_Buffers();
}

static const char *ui_card_type(uint8_t type)
{
    switch (type) {
        case SD_TYPE_V1: return "SDSC V1";
        case SD_TYPE_V2: return "SDSC V2";
        case SD_TYPE_V2HC: return "SDHC/SDXC";
        default: return "UNKNOWN";
    }
}

void AppUI_RenderInfoPage(uint8_t page, const SD_CardInfo *card,
                          const AppUI_VolumeInfo *volume, uint32_t spi_hz,
                          uint32_t elapsed_ms)
{
    if (card == NULL || volume == NULL) return;
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    int16_t xo = ui_page_offset(elapsed_ms);
    uint8_t compact = (OLED_HEIGHT < 48U);
    char line[28], size_a[16], size_b[16], spi[10];
    ui_format_spi(spi_hz, spi, sizeof(spi));

    if (page == 0U) {
        ui_page_header("STORAGE", page, xo);
        ui_format_size(volume->total_bytes, size_a, sizeof(size_a));
        if (volume->free_valid) ui_format_size(volume->free_bytes, size_b, sizeof(size_b));
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s  %s", volume->fs_name, size_a);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "FREE %s", volume->free_valid ? size_b : "N/A");
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            (void)snprintf(line, sizeof(line), "FS    : %s", volume->fs_name);
            ui_text(3 + xo, 14, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "TOTAL : %s", size_a);
            ui_text(3 + xo, 25, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "FREE  : %s", volume->free_valid ? size_b : "N/A");
            ui_text(3 + xo, 36, line, UI_FONT_SMALL);
        }
        if (volume->free_valid && volume->total_bytes > 0U) {
            uint64_t free_bytes = volume->free_bytes;
            if (free_bytes > volume->total_bytes) free_bytes = volume->total_bytes;
            uint8_t used = (uint8_t)(100U - (free_bytes * 100U / volume->total_bytes));
            ui_progress(3 + xo, compact ? 27 : 50, OLED_WIDTH - 6, used);
            if (!compact) {
                (void)snprintf(line, sizeof(line), "USED %u%%", used);
                ui_text(OLED_WIDTH - 54 + xo, 56, line, UI_FONT_SMALL);
            }
        }
    } else if (page == 1U) {
        ui_page_header("CARD", page, xo);
        ui_format_size((uint64_t)card->capacity_mb << 20, size_a, sizeof(size_a));
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s %s", ui_card_type(card->type), size_a);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "%s  SPI:%s", card->block_addr ? "LBA" : "BYTE", spi);
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            ui_text(3 + xo, 14, ui_card_type(card->type), UI_FONT_MED);
            (void)snprintf(line, sizeof(line), "CAP   : %s", size_a);
            ui_text(3 + xo, 29, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "ADDR:%s SPI:%s",
                           card->block_addr ? "LBA" : "BYTE", spi);
            ui_text(3 + xo, 40, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "BLOCKS: %lu", (unsigned long)card->block_count);
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
        ui_page_header("IDENTITY", page, xo);
        if (compact) {
            (void)snprintf(line, sizeof(line), "%s V%u.%u  OID:%s", pnm,
                           card->cid_raw[8] >> 4, card->cid_raw[8] & 0x0FU, oid);
            ui_text(2 + xo, 12, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "SN:%08lX", (unsigned long)psn);
            ui_text(2 + xo, 21, line, UI_FONT_SMALL);
        } else {
            (void)snprintf(line, sizeof(line), "NAME : %s V%u.%u", pnm,
                           card->cid_raw[8] >> 4, card->cid_raw[8] & 0x0FU);
            ui_text(3 + xo, 14, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "MID  : %02X  OID:%s", card->cid_raw[0], oid);
            ui_text(3 + xo, 25, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "SN   : %08lX", (unsigned long)psn);
            ui_text(3 + xo, 36, line, UI_FONT_SMALL);
            (void)snprintf(line, sizeof(line), "DATE : %04u-%02u", 2000U + (mdt >> 4), mdt & 0x0FU);
            ui_text(3 + xo, 47, line, UI_FONT_SMALL);
        }
    }

    if (elapsed_ms < 300U) {
        int16_t sweep = (int16_t)((uint32_t)OLED_WIDTH * elapsed_ms / 300U);
        if (sweep > 3) OLED_SW_Invert_Rect(0, 0, sweep, OLED_HEIGHT);
    }
    OLED_Swap_Buffers();
}

void AppUI_RenderFileList(const char names[][13], uint8_t count, uint8_t selected,
                          uint8_t top, uint8_t function_dir, uint32_t elapsed_ms)
{
    (void)elapsed_ms;
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    uint8_t y0 = (OLED_HEIGHT >= 24U) ? 11U : 0U;
    uint8_t rows = (uint8_t)((OLED_HEIGHT - y0) / 9U);
    if (rows == 0U) rows = 1U;
    if (y0 != 0U) {
        char title[18];
        (void)snprintf(title, sizeof(title), "FILES %u", count);
        ui_text(2, 1, title, UI_FONT_SMALL);
        ui_text(OLED_WIDTH > 32U ? OLED_WIDTH - 30 : 0, 1, function_dir ? "/FN" : "/", UI_FONT_SMALL);
        OLED_Draw_Line(0, 9, OLED_WIDTH - 1, 0, 0);
    }
    for (uint8_t row = 0; row < rows; ++row) {
        uint8_t idx = (uint8_t)(top + row);
        if (idx >= count) break;
        uint8_t y = (uint8_t)(y0 + row * 9U);
        ui_text(8, y, names[idx], UI_FONT_SMALL);
        if (idx == selected) {
            OLED_SW_Invert_Rect(2, y, (OLED_WIDTH > 8U) ? OLED_WIDTH - 7 : OLED_WIDTH, 8);
            OLED_Draw_Line(3, y + 2, 3, 2, 0);
            OLED_Draw_Line(3, y + 6, 3, -2, 0);
        }
    }
    if (count > rows && OLED_WIDTH >= 4U) {
        uint8_t track = (uint8_t)(OLED_HEIGHT - y0);
        uint8_t knob = (uint8_t)((uint16_t)track * rows / count);
        if (knob < 3U) knob = 3U;
        uint8_t ky = (uint8_t)(y0 + (uint16_t)(track - knob) * top / (count - rows));
        OLED_Draw_Line(OLED_WIDTH - 2, y0, 0, track - 1, 0);
        OLED_Draw_Rectang(OLED_WIDTH - 3, ky, 2, knob - 1, 1);
    }
    OLED_Swap_Buffers();
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
                   function_dir ? "NO .BIN IN /FN" : "NO .BIN FILES", UI_FONT_SMALL);
    uint8_t dots = (uint8_t)((elapsed_ms / 350U) % 4U);
    for (uint8_t i = 0; i < dots; ++i)
        OLED_Draw_Circle((int16_t)(OLED_WIDTH / 2 - 5 + i * 5), y + h + 1, 1, 1);
    OLED_Swap_Buffers();
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
    OLED_Swap_Buffers();
}

void AppUI_RenderRemoved(uint32_t elapsed_ms)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed_ms); return; }
    OLED_GRAM_Clear();
    ui_text_center(0, (OLED_HEIGHT >= 48U) ? 13 : 5, "CARD REMOVED",
                   (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
    ui_text_center(0, (OLED_HEIGHT >= 48U) ? 32 : 16, "REINSERT SD", UI_FONT_SMALL);
    uint32_t phase = (elapsed_ms > 600U) ? 600U : elapsed_ms;
    int16_t w = (int16_t)((uint32_t)OLED_WIDTH * phase / 600U);
    if (w > 0) OLED_SW_Invert_Rect(0, 0, w, OLED_HEIGHT);
    OLED_Swap_Buffers();
}

static void ui_render_popup(const char *title, const char *detail, uint32_t elapsed, uint32_t duration)
{
    if (ui_tiny_screen()) { ui_render_tiny(elapsed); return; }
    OLED_GRAM_Clear();
    uint32_t edge = 180U;
    uint32_t scale = 100U;
    if (elapsed < edge) scale = elapsed * 100U / edge;
    else if (duration > edge && elapsed > duration - edge) scale = (duration - elapsed) * 100U / edge;
    if (scale > 100U) scale = 100U;
    int16_t target_w = (OLED_WIDTH > 10U) ? OLED_WIDTH - 10 : OLED_WIDTH;
    int16_t target_h = (OLED_HEIGHT >= 48U) ? 38 : OLED_HEIGHT - 4;
    int16_t w = (int16_t)((uint32_t)target_w * scale / 100U);
    int16_t h = (int16_t)((uint32_t)target_h * scale / 100U);
    int16_t x = (OLED_WIDTH - w) / 2;
    int16_t y = (OLED_HEIGHT - h) / 2;
    ui_panel(x, y, w, h);
    if (scale >= 72U) {
        ui_text_center(0, y + 5, title, (OLED_HEIGHT >= 48U) ? UI_FONT_MED : UI_FONT_SMALL);
        if (detail && h >= 27) ui_text_center(0, y + h - 12, detail, UI_FONT_SMALL);
    }
    OLED_Swap_Buffers();
}

void AppUI_ShowPopup(const char *title, const char *detail, uint32_t duration_ms)
{
    if (duration_ms < 2U) duration_ms = 2U;
    uint32_t start = HAL_GetTick();
    uint32_t elapsed;
    do {
        uint32_t frame_start = HAL_GetTick();
        elapsed = frame_start - start;
        if (elapsed > duration_ms) elapsed = duration_ms;
        ui_render_popup(title, detail, elapsed, duration_ms);
        uint32_t dt = HAL_GetTick() - frame_start;
        if (dt < APP_UI_FRAME_MS) HAL_Delay(APP_UI_FRAME_MS - dt);
    } while ((HAL_GetTick() - start) < duration_ms);
}
