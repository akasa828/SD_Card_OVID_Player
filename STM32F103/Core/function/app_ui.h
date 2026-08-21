#ifndef APP_UI_H
#define APP_UI_H

#include <stdint.h>
#include "SD_reader.h"

#ifdef __cplusplus
extern "C" {
#endif

#define APP_UI_INFO_PAGES       3U
#define APP_UI_INFO_PAGE_MS  3000U
#define APP_UI_FRAME_MS         16U
#define APP_UI_POPUP_MS       1200U
#ifndef APP_UI_FILE_NAME_MAX
#define APP_UI_FILE_NAME_MAX    64U
#endif

typedef struct {
    char     fs_name[8];
    uint64_t total_bytes;
    uint64_t free_bytes;
    uint8_t  free_valid;
} AppUI_VolumeInfo;

typedef struct {
    uint32_t frames;
    uint16_t fps;
    uint8_t width;
    uint8_t height;
    uint8_t version;
    uint8_t valid;
} AppUI_VideoMeta;

void AppUI_Init(void);
void AppUI_RenderWaitCard(uint32_t elapsed_ms);
void AppUI_RenderAnalyzing(uint32_t elapsed_ms, const char *detail);
void AppUI_RenderFreeScan(uint16_t display_permille, uint16_t target_permille,
                          uint32_t elapsed_ms);
void AppUI_RenderInfoPage(uint8_t page, const SD_CardInfo *card,
                          const AppUI_VolumeInfo *volume, uint32_t spi_hz,
                          uint32_t elapsed_ms);
void AppUI_RenderFileList(const char names[][APP_UI_FILE_NAME_MAX], uint8_t count, uint8_t selected,
                          uint8_t top, uint8_t function_dir, const AppUI_VideoMeta *meta,
                          uint32_t elapsed_ms);
void AppUI_RenderEmpty(uint8_t function_dir, uint32_t elapsed_ms);
void AppUI_RenderPersistentError(const char *title, const char *detail, uint32_t elapsed_ms);
void AppUI_RenderRemoved(uint32_t elapsed_ms);
void AppUI_RenderDiagnostics(uint8_t page, uint8_t key_mask, int16_t sd_test_result,
                             uint32_t elapsed_ms);
void AppUI_ShowPopup(const char *title, const char *detail, uint32_t duration_ms);
void AppUI_ShowClassicPopup(const char *title, const char *detail, uint32_t duration_ms);
uint8_t AppUI_PopupActive(void);
void AppUI_PopupCancel(void);
void AppUI_RenderPopupTask(void);

#ifdef __cplusplus
}
#endif

#endif /* APP_UI_H */
