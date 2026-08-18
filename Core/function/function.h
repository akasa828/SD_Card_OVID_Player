/**
  ******************************************************************************
  * @file    function.h
  * @author  riochihao
  * @brief   SD 卡文件浏览 + 取模视频播放（按键 UI）
  * @note    依赖：FatFs(ff.h) + SD 驱动(SD_reader.h) + OLED(oled.hpp)。
  *          三按键 PB1=上 / PB10=下 / PB11=确认（EXTI，见 gpio.c / it.c）。
  *          视频文件为自描述 .bin（头部带宽高/帧数/帧率），见 tools/h2bin.py。
  ******************************************************************************
  */
#ifndef __FUNCTION_H
#define __FUNCTION_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

//========== 可配置项 ==============
/* 浏览器扫描的视频文件扩展名（大写，含点）。播放需二进制 → 默认 .BIN。 */
#ifndef FN_VIDEO_EXT
#define FN_VIDEO_EXT   ".BIN"
#endif
/* 列表最多记录的文件数（每项 13B 名字，占 FN_MAX_FILES*13 字节 .bss） */
#ifndef FN_MAX_FILES
#define FN_MAX_FILES   32U
#endif
/* 优先扫描的视频目录；不存在或无 .BIN 时回退到根目录。 */
#ifndef FN_DIR_NAME
#define FN_DIR_NAME    "function"
#endif

//========== 按键引脚（与 gpio.c / it.c 一致；改引脚只需改这里和那两处）==========
#define FN_KEY_PORT      GPIOB
#define FN_KEY_UP_PIN    GPIO_PIN_1
#define FN_KEY_DOWN_PIN  GPIO_PIN_10
#define FN_KEY_OK_PIN    GPIO_PIN_11

//========== .bin 视频文件头（16 字节，小端）==============
/* magic "OVID" + 宽 + 高 + 保留 + 帧数 + 帧率 + 保留。
 * 帧数据紧随其后，每帧 = ceil(height/8)*width 字节，SSD1306 页主序，
 * 与 OLED_Draw_Bitmap 的入参布局一致。 */
#define FN_MAGIC0 'O'
#define FN_MAGIC1 'V'
#define FN_MAGIC2 'I'
#define FN_MAGIC3 'D'

typedef struct {
    uint8_t  magic[4];     /* "OVID" */
    uint8_t  width;        /* 帧宽（像素） */
    uint8_t  height;       /* 帧高（像素） */
    uint8_t  rsv0[2];
    uint32_t frame_count;  /* 总帧数 */
    uint16_t fps;          /* 播放帧率，合法范围 1~120 */
    uint8_t  rsv1[2];
} FN_VideoHeader;          /* sizeof = 16 */

//========== 对外接口 ==============

/**
 * @brief 完整 SD UI、文件浏览和视频播放主入口（阻塞，接管主循环，永不返回）
 * @note  内部：等待插卡 → 初始化/挂载 → f_getfree 容量扫描 → 三张信息页 →
 *        优先扫描 /FN_DIR_NAME（无文件则回退根目录）→ 列表选择 → 播放。
 *        信息页/列表连续两次 CMD58 探测失败会卸载并返回等待插卡界面。
 *        无文件时显示动画空状态并周期重扫。调用前需 OLED_Init()。
 */
void Function_Run(void);

#ifdef __cplusplus
}
#endif

#endif /* __FUNCTION_H */
