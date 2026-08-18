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

typedef struct {
    char     fs_name[8];
    uint64_t total_bytes;
    uint64_t free_bytes;
    uint8_t  free_valid;
} AppUI_VolumeInfo;

void AppUI_Init(void);
void AppUI_RenderWaitCard(uint32_t elapsed_ms);
void AppUI_RenderAnalyzing(uint32_t elapsed_ms, const char *detail);
void AppUI_RenderFreeScan(uint8_t percent, uint32_t elapsed_ms);
void AppUI_RenderInfoPage(uint8_t page, const SD_CardInfo *card,
                          const AppUI_VolumeInfo *volume, uint32_t spi_hz,
                          uint32_t elapsed_ms);
void AppUI_RenderFileList(const char names[][13], uint8_t count, uint8_t selected,
                          uint8_t top, uint8_t function_dir, uint32_t elapsed_ms);
void AppUI_RenderEmpty(uint8_t function_dir, uint32_t elapsed_ms);
void AppUI_RenderPersistentError(const char *title, const char *detail, uint32_t elapsed_ms);
void AppUI_RenderRemoved(uint32_t elapsed_ms);
void AppUI_ShowPopup(const char *title, const char *detail, uint32_t duration_ms);

#ifdef __cplusplus
}
#endif

#endif /* APP_UI_H */
