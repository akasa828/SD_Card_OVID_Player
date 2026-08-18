/*-----------------------------------------------------------------------*/
/* Low level disk I/O — 跨接到本工程的 SD SPI 驱动 (SD_reader)            */
/*-----------------------------------------------------------------------*/
/* 单盘符：物理盘 0 = SD 卡（g_sd_card）。其余盘号一律 STA_NOINIT。       */
/* FatFs 调用 disk_* → 这里转调 SD_Read/Write_Block_Card 等。            */
/*-----------------------------------------------------------------------*/

#include "ff.h"          /* FatFs 基础类型定义 */
#include "diskio.h"      /* FatFs 磁盘 I/O 接口声明 */
#include "SD_reader.h"   /* 本工程 SD 驱动：g_sd_card / SD_*_Card / SD_OK */

#define DEV_SD   0       /* 唯一物理盘号：SD 卡 */

/*-----------------------------------------------------------------------*/
/* Get Drive Status                                                      */
/*-----------------------------------------------------------------------*/
DSTATUS disk_status (BYTE pdrv)
{
    if (pdrv != DEV_SD) return STA_NOINIT;
    return g_sd_card.info.initialized ? 0 : STA_NOINIT;
}

/*-----------------------------------------------------------------------*/
/* Initialize a Drive                                                    */
/*-----------------------------------------------------------------------*/
DSTATUS disk_initialize (BYTE pdrv)
{
    if (pdrv != DEV_SD) return STA_NOINIT;
    /* 已初始化则直接返回就绪，避免重复握手 */
    if (g_sd_card.info.initialized) return 0;
    return (SD_Init_Card(&g_sd_card) > 0) ? 0 : STA_NOINIT;
}

/*-----------------------------------------------------------------------*/
/* Read Sector(s)                                                        */
/*-----------------------------------------------------------------------*/
DRESULT disk_read (BYTE pdrv, BYTE *buff, LBA_t sector, UINT count)
{
    if (pdrv != DEV_SD) return RES_PARERR;
    if (!g_sd_card.info.initialized) return RES_NOTRDY;
    if (count == 0U) return RES_PARERR;

    int r = (count == 1U)
          ? SD_Read_Block_Card(&g_sd_card, (uint32_t)sector, buff)
          : SD_Read_Multi_Block_Card(&g_sd_card, (uint32_t)sector, buff, (uint32_t)count);
    return (r == SD_OK) ? RES_OK : RES_ERROR;
}

/*-----------------------------------------------------------------------*/
/* Write Sector(s)                                                       */
/*-----------------------------------------------------------------------*/
#if FF_FS_READONLY == 0
DRESULT disk_write (BYTE pdrv, const BYTE *buff, LBA_t sector, UINT count)
{
    if (pdrv != DEV_SD) return RES_PARERR;
    if (!g_sd_card.info.initialized) return RES_NOTRDY;
    if (count == 0U) return RES_PARERR;

    int r = (count == 1U)
          ? SD_Write_Block_Card(&g_sd_card, (uint32_t)sector, buff)
          : SD_Write_Multi_Block_Card(&g_sd_card, (uint32_t)sector, buff, (uint32_t)count);
    return (r == SD_OK) ? RES_OK : RES_ERROR;
}
#endif

/*-----------------------------------------------------------------------*/
/* Miscellaneous Functions                                               */
/*-----------------------------------------------------------------------*/
DRESULT disk_ioctl (BYTE pdrv, BYTE cmd, void *buff)
{
    if (pdrv != DEV_SD) return RES_PARERR;
    if (!g_sd_card.info.initialized) return RES_NOTRDY;

    switch (cmd) {
    case CTRL_SYNC:            /* 本驱动写操作为同步阻塞，无挂起缓存 */
        return RES_OK;
    case GET_SECTOR_COUNT:     /* 总扇区数（用于 f_mkfs/f_getfree 计算） */
        *(LBA_t *)buff = (LBA_t)g_sd_card.info.block_count;
        return RES_OK;
    case GET_SECTOR_SIZE:      /* 固定 512B（FF_MIN_SS==FF_MAX_SS 时其实不调用） */
        *(WORD *)buff = SD_BLOCK_SIZE;
        return RES_OK;
    case GET_BLOCK_SIZE:       /* 擦除块大小（扇区为单位）；未知则返回 1 */
        *(DWORD *)buff = 1U;
        return RES_OK;
    default:
        return RES_PARERR;
    }
}

/*-----------------------------------------------------------------------*/
/* 时间戳：本工程无 RTC，返回一个固定有效时间（2025-01-01 00:00:00）。     */
/* FatFs 在 FF_FS_READONLY==0 且 FF_FS_NORTC==0 时用它给新建文件打时间戳。  */
/*-----------------------------------------------------------------------*/
DWORD get_fattime (void)
{
    /* bit31:25=年-1980, 24:21=月, 20:16=日, 15:11=时, 10:5=分, 4:0=秒/2 */
    return ((DWORD)(2025 - 1980) << 25)
         | ((DWORD)1 << 21)
         | ((DWORD)1 << 16);
}

