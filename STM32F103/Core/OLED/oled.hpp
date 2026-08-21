/**
  ******************************************************************************
  * @file    oled.hpp
  * @author  riochihao
  * @brief   SSD1306 OLED 屏幕驱动函数声明
  ******************************************************************************
  */

#ifndef __OLED_HPP
#define __OLED_HPP

#include "stdint.h"
#include "oled_port.h"

#ifdef __cplusplus
extern "C" {
#endif

// ==================== 屏幕尺寸宏定义 ====================
// 修改 OLED_WIDTH / OLED_HEIGHT 即可适配不同分辨率屏幕。
// OVID v1 宽高字段各占 1 字节；页寻址要求屏高为 8 的倍数。
#ifndef OLED_WIDTH
#define OLED_WIDTH  128
#endif
#ifndef OLED_HEIGHT
#define OLED_HEIGHT 64
#endif

#if OLED_WIDTH < 1 || OLED_WIDTH > 255
#error "OLED_WIDTH must be in the range 1..255"
#endif
#if OLED_HEIGHT < 8 || OLED_HEIGHT > 255 || (OLED_HEIGHT % 8) != 0
#error "OLED_HEIGHT must be in the range 8..255 and divisible by 8"
#endif

#define OLED_PAGES      (OLED_HEIGHT / 8)
#define OLED_GRAM_SIZE  (OLED_PAGES * OLED_WIDTH)

// ==================== 控制器与模组配置 ====================
#define OLED_CONTROLLER_SSD1306 0
#define OLED_CONTROLLER_SH1106  1
#ifndef OLED_CONTROLLER
#define OLED_CONTROLLER OLED_CONTROLLER_SSD1306
#endif
#ifndef OLED_COLUMN_OFFSET
#if OLED_CONTROLLER == OLED_CONTROLLER_SH1106
#define OLED_COLUMN_OFFSET 2
#else
#define OLED_COLUMN_OFFSET 0
#endif
#endif
#ifndef OLED_DEFAULT_H_FLIP
#define OLED_DEFAULT_H_FLIP 1
#endif
#ifndef OLED_DEFAULT_V_FLIP
#define OLED_DEFAULT_V_FLIP 1
#endif
#if OLED_CONTROLLER != OLED_CONTROLLER_SSD1306 && OLED_CONTROLLER != OLED_CONTROLLER_SH1106
#error "OLED_CONTROLLER must be SSD1306 or SH1106"
#endif
#if (OLED_COLUMN_OFFSET + OLED_WIDTH) > 256
#error "OLED_COLUMN_OFFSET + OLED_WIDTH exceeds controller column range"
#endif

// ==================== 可选功能开关 ====================
#ifndef OLED_ENABLE_WAVE
#define OLED_ENABLE_WAVE         1
#endif
#ifndef OLED_PRINTF_BUF_SIZE
#define OLED_PRINTF_BUF_SIZE    64
#endif

// ==================== 屏幕旋转 ====================
// 旋转在 OLED_Draw_Point 内部做坐标变换，对所有上层绘图函数透明。
// 0°/180°: 逻辑尺寸 = OLED_WIDTH × OLED_HEIGHT。
// 90°/270°: 逻辑宽高互换。
#define OLED_ROT_0    0
#define OLED_ROT_90   1
#define OLED_ROT_180  2
#define OLED_ROT_270  3
extern uint8_t g_oled_rotation;
void OLED_Set_Rotation(uint8_t rotation);

// ==================== 显存 ====================
extern uint8_t OLED_GRAM[OLED_PAGES][OLED_WIDTH];

// ==================== 双缓冲支持（条件编译） ====================
#ifndef OLED_USE_DOUBLE_BUFFER
#define OLED_USE_DOUBLE_BUFFER  1
#endif
//   - 1: 启用双缓冲。分配 OLED_BACK_BUFFER + draw_buffer 指针，
//        提供 OLED_Select_Buffer() / OLED_Swap_Buffers()。
//   - 0: 禁用双缓冲。draw_buffer 退化为 OLED_GRAM 宏，
//        零额外 RAM 开销，行为与原有单缓冲代码完全一致。
#if OLED_USE_DOUBLE_BUFFER
extern uint8_t  OLED_BACK_BUFFER[OLED_PAGES][OLED_WIDTH];
extern uint8_t (*draw_buffer)[OLED_WIDTH];   // 当前绘图目标指针
extern uint8_t  g_current_buffer_id;          // 0=前台(GRAM), 1=后台(BACK)
#define DRAW_BUFFER(page)  draw_buffer[page]  // 统一页面访问接口
void OLED_Select_Buffer(uint8_t buffer_id);
void OLED_Swap_Buffers(void);

#else
/* 单缓冲模式：draw_buffer 直接映射到 OLED_GRAM，零开销 */
#define draw_buffer       OLED_GRAM
#define DRAW_BUFFER(page) OLED_GRAM[page]
/* 空实现，保证调用方无需条件编译 */
#define OLED_Select_Buffer(buf_id)   ((void)(buf_id))
#define OLED_Swap_Buffers()          OLED_GRAM_Refresh()
#endif /* OLED_USE_DOUBLE_BUFFER */

// ==================== I2C 通信常量 ====================
extern const uint8_t OLED_I2C_ADDRESS;
extern const uint8_t CMD;
extern const uint8_t DATA;

// ==================== DMA 标志位与回调 ====================
extern volatile uint8_t OLED_DMA_Busy;
void OLED_Wait_DMA(void);
uint32_t OLED_Get_I2C_Error_Count(void);
uint32_t OLED_Get_I2C_Timeout_Count(void);
uint32_t OLED_Get_I2C_Clock(void);

// ==================== 底层通信 ====================
void OLED_Write_Byte(uint8_t cmd, uint8_t mode);

// ==================== 设备检测 ====================
int OLED_Detect(void);

// ==================== 初始化和刷新 ====================
void OLED_Init(void);
void OLED_GRAM_Refresh(void);
void OLED_GRAM_Clear(void);
void OLED_GRAM_Fill(void);
void OLED_Clear(void);
float OLED_Calc_FPS(void);
uint16_t OLED_Calc_FPS_Int(void);   // 整数版，无浮点开销

// ==================== 低功耗控制 ====================
void OLED_Sleep(void);
void OLED_Wake(void);
void OLED_Set_Contrast(uint8_t level);
void OLED_Set_Mirror(uint8_t h_flip, uint8_t v_flip);
void OLED_Set_Inverse(uint8_t inverse);
void OLED_Export_GRAM(uint8_t* dest);
void OLED_Import_GRAM(const uint8_t* src);

// ==================== 硬件滚动 ====================
#define OLED_SCROLL_FULL 0xFF
void OLED_Scroll_HW_H(uint8_t dir, uint8_t start_pg, uint8_t end_pg, uint8_t speed);
void OLED_Scroll_HW_HV(uint8_t dir, uint8_t start_pg, uint8_t end_pg, uint8_t speed, uint8_t v_offset);
void OLED_Scroll_HW_Switch(uint8_t enable);

// ==================== 软件滚动 ====================
void OLED_Scroll_Soft_Vertical(int16_t offset);
void OLED_Scroll_Soft_Horizontal(int16_t offset);


// ==================== 数学常量 ====================


// ==================== 基础图形绘制 ====================
void OLED_Draw_Point(uint8_t x, uint8_t y);
void OLED_Draw_Bitmap(int16_t x, int16_t y, uint8_t bmp_width, uint8_t bmp_height, const uint8_t* bmp_data);
void OLED_Draw_Line(int16_t x0, int16_t y0, int16_t dx, int16_t dy, uint8_t mode);
void OLED_Draw_Rectang(int16_t x, int16_t y, int16_t dx, int16_t dy, uint8_t mode);
#if OLED_ENABLE_WAVE
void OLED_Draw_Wave(int16_t x0, int16_t y0, uint8_t A, uint8_t wave,uint16_t period, uint8_t phi, int16_t b);
#endif
void OLED_Draw_Circle(int16_t x0, int16_t y0, uint8_t r, uint8_t mode);
void OLED_Clear_Rect(int16_t x0, int16_t y0, int16_t dx, int16_t dy);
void OLED_SW_Invert_Rect(int16_t x0, int16_t y0, int16_t dx, int16_t dy);
void OLED_Refresh_Rect(int16_t x0, int16_t y0, int16_t dx, int16_t dy);


// ==================== 文本绘制 ====================
void OLED_Show_Char_ASCII(char tmp, const char* size, uint8_t x, uint8_t y);
void OLED_Show_String(const char* str, const char* size, uint8_t x, uint8_t y);

// ==================== 数字类型枚举 ====================
typedef enum {
    OLED_NUM_S8,    // int8_t
    OLED_NUM_U8,    // uint8_t
    OLED_NUM_S16,   // int16_t
    OLED_NUM_U16,   // uint16_t
    OLED_NUM_S32,   // int32_t
    OLED_NUM_U32,   // uint32_t
    OLED_NUM_FLOAT, // float
} OLED_NumType;

void OLED_Show_Number(const void* num, OLED_NumType type,
                      uint8_t bits_or_prec, const char* size,
                      uint8_t x, uint8_t y);

// ==================== 格式化输出 ====================
void OLED_Printf(const char* size, uint8_t x, uint8_t y, const char* fmt, ...);

// ==================== 整数快速打印（无浮点、无 switch 分派）====================
void OLED_Show_Int(int32_t num, const char* size, uint8_t x, uint8_t y);
void OLED_Show_Uint(uint32_t num, const char* size, uint8_t x, uint8_t y);
void OLED_Show_Hex(uint32_t num, uint8_t digits, const char* size, uint8_t x, uint8_t y);

// ==================== UI 控件 ====================
void OLED_Draw_ProgressBar(uint8_t x, uint8_t y, uint8_t w, uint8_t h,
                           uint8_t percent, uint8_t style);



#ifdef __cplusplus
}
#endif

#endif /* __OLED_HPP */
