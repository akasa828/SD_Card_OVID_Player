#ifndef SD_FATFS_H
#define SD_FATFS_H

#include "SD_reader.h"

#ifdef __cplusplus
extern "C" {
#endif

int SD_FatFs_Attach(SD_Card *card);

#ifdef __cplusplus
}
#endif

#endif
