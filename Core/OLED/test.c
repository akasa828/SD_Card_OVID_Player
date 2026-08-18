/**
  ******************************************************************************
  * @file    test.c
  * @author  riochihao
  * @brief   OLED 驱动全功能顺序测试
  * @note    每个子测试函数前的注释说明了"什么现象才是正确的"。
  *          测试间隔约 2 秒，方便肉眼逐步确认。
  ******************************************************************************
  */
#include "main.h"
#include "oled.hpp"
#include "test.h"

#include <string.h>

/* 测试间隔（毫秒），可按需调整 */
#define TEST_DELAY  2000
#define TEST_MIN_DIM ((OLED_WIDTH < OLED_HEIGHT) ? OLED_WIDTH : OLED_HEIGHT)
#define TEST_CX      ((uint8_t)(OLED_WIDTH / 2U))
#define TEST_CY      ((uint8_t)(OLED_HEIGHT / 2U))
#define TEST_RADIUS  ((uint8_t)((TEST_MIN_DIM >= 8U) ? (TEST_MIN_DIM / 4U) : 1U))

/* ====================================================================== */
/* 辅助宏：清屏 + 显示测试标题                                              */
/* ====================================================================== */
#define TEST_BEGIN(title) do {       \
    OLED_GRAM_Clear();               \
    OLED_Show_String(title, "0806", 0, 0); \
    OLED_GRAM_Refresh();             \
    HAL_Delay(800);                  \
    OLED_GRAM_Clear();               \
} while(0)

/* ====================================================================== */
/*                        子测试函数                                        */
/* ====================================================================== */

/**
 * @test   OLED_GRAM_Refresh
 * @expect 屏幕左上角显示 "Refresh OK" 文字，其余区域空白。
 *         说明显存内容被成功推送到屏幕。
 */
static void test_GRAM_Refresh(void)
{
    TEST_BEGIN("1.GRAM_Refresh");
    OLED_Show_String("Refresh OK", "1608", 0, 20);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Calc_FPS / OLED_Calc_FPS_Int
 * @expect 屏幕快速刷新 ~20 帧后显示浮点 FPS（如 "F:50.0"）和整数 FPS（如 "I:50"）。
 *         两个值应接近且 > 0。
 */
static void test_Calc_FPS(void)
{
    TEST_BEGIN("2.Calc_FPS");
    /* 先跑 20 帧让 FPS 稳定 */
    for (int i = 0; i < 20; i++) {
        OLED_GRAM_Clear();
        OLED_GRAM_Refresh();
        (void)OLED_Calc_FPS();
        (void)OLED_Calc_FPS_Int();
    }
    HAL_Delay(1100); /* 等待 1 秒窗口更新 */
    float fps_f = OLED_Calc_FPS();
    uint16_t fps_i = OLED_Calc_FPS_Int();
    OLED_GRAM_Clear();
    /* newlib-nano 默认不支持 %f，手动拆分整数+小数 */
    int16_t fps_int = (int16_t)fps_f;
    int16_t fps_dec = (int16_t)((fps_f - (float)fps_int) * 10.0f);
    if (fps_dec < 0) fps_dec = -fps_dec;
    OLED_Printf("0806", 0, 0, "Float FPS:%d.%d", fps_int, fps_dec);
    OLED_Printf("0806", 0, 10, "Int   FPS:%d", fps_i);
    OLED_Show_String("Both > 0 = OK", "0806", 0, 24);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_GRAM_Clear
 * @expect 先显示满屏白色，然后调用 Clear 后屏幕变为全黑。
 */
static void test_GRAM_Clear(void)
{
    TEST_BEGIN("3.GRAM_Clear");
    OLED_GRAM_Fill();
    OLED_GRAM_Refresh();
    HAL_Delay(1000);
    OLED_GRAM_Clear();
    OLED_GRAM_Refresh();
    /* 此时屏幕应全黑 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_GRAM_Fill
 * @expect 屏幕所有像素全部点亮（纯白），用于坏点检测。
 */
static void test_GRAM_Fill(void)
{
    TEST_BEGIN("4.GRAM_Fill");
    OLED_GRAM_Fill();
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Clear
 * @expect 先显示文字，调用 OLED_Clear 后屏幕立即变全黑（Clear = 清显存 + 刷新）。
 */
static void test_Clear(void)
{
    OLED_GRAM_Clear();
    OLED_Show_String("Will Clear...", "1608", 0, 20);
    OLED_GRAM_Refresh();
    HAL_Delay(1000);
    OLED_Clear(); /* 清屏并刷新 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Sleep / OLED_Wake
 * @expect 先显示文字，Sleep 后屏幕熄灭（全暗），Wake 后恢复显示原有内容。
 */
static void test_Sleep_Wake(void)
{
    TEST_BEGIN("5.Sleep/Wake");
    OLED_Show_String("Sleeping...", "1608", 0, 20);
    OLED_GRAM_Refresh();
    HAL_Delay(1000);
    OLED_Sleep();
    HAL_Delay(1500);
    OLED_Wake();
    /* 唤醒后原有显存内容应恢复 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Set_Contrast
 * @expect 屏幕亮度从暗逐渐变亮再恢复正常（0x00→0xFF→0xCF）。
 */
static void test_Set_Contrast(void)
{
    TEST_BEGIN("6.Contrast");
    OLED_Show_String("Contrast Test", "1608", 0, 20);
    OLED_GRAM_Refresh();
    OLED_Set_Contrast(0x10);  /* 很暗 */
    HAL_Delay(800);
    OLED_Set_Contrast(0x80);  /* 中等 */
    HAL_Delay(800);
    OLED_Set_Contrast(0xFF);  /* 最亮 */
    HAL_Delay(800);
    OLED_Set_Contrast(0xCF);  /* 恢复默认 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Set_Mirror
 * @expect 文字 "Mirror" 先正常显示，然后水平翻转（左右镜像），最后恢复正常。
 */
static void test_Set_Mirror(void)
{
    TEST_BEGIN("7.Mirror");
    OLED_Show_String("Mirror", "1608", 30, 20);
    OLED_GRAM_Refresh();
    HAL_Delay(1000);
    OLED_Set_Mirror(0, 1);  /* 水平翻转 */
    HAL_Delay(1500);
    OLED_Set_Mirror(1, 1);  /* 恢复默认 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Set_Inverse
 * @expect 屏幕反显（黑底白字变成白底黑字），1.5 秒后恢复正常。
 */
static void test_Set_Inverse(void)
{
    TEST_BEGIN("8.Inverse");
    OLED_Show_String("Inverse!", "1608", 20, 20);
    OLED_GRAM_Refresh();
    HAL_Delay(800);
    OLED_Set_Inverse(1);
    HAL_Delay(1500);
    OLED_Set_Inverse(0);
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Export_GRAM / OLED_Import_GRAM
 * @expect 先画一个圆并导出，清屏后导入恢复——圆重新出现，说明导出/导入正常。
 */
static void test_Export_Import(void)
{
    TEST_BEGIN("9.Export/Import");
    static uint8_t backup[OLED_GRAM_SIZE];

    OLED_Draw_Circle(TEST_CX, TEST_CY, TEST_RADIUS, 1);
    OLED_Show_String("Export", "0806", 0, (uint8_t)(OLED_HEIGHT - 8U));
    OLED_GRAM_Refresh();
    HAL_Delay(1000);

    OLED_Export_GRAM(backup);
    OLED_GRAM_Clear();
    OLED_Show_String("Cleared!", "0806", 30, 28);
    OLED_GRAM_Refresh();
    HAL_Delay(1000);

    OLED_Import_GRAM(backup);
    OLED_Show_String("Imported", "0806", 0, (uint8_t)(OLED_HEIGHT - 8U));
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_Point
 * @expect 屏幕对角线上出现一排稀疏的点（每隔 4 像素一个点）。
 */
static void test_Draw_Point(void)
{
    TEST_BEGIN("10.Draw_Point");
    for (uint16_t i = 0; i < TEST_MIN_DIM; i += 4U) {
        uint8_t x = (TEST_MIN_DIM > 1U)
                  ? (uint8_t)(i * (OLED_WIDTH - 1U) / (TEST_MIN_DIM - 1U)) : 0U;
        OLED_Draw_Point(x, (uint8_t)i);
    }
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Show_Char_ASCII / OLED_Show_String
 * @expect 第一行显示单个字符 'A'，第二行显示 "Hello OLED!"，第三行显示 16px 大字号。
 */
static void test_Show_String(void)
{
    TEST_BEGIN("11.String");
    OLED_Show_Char_ASCII('A', "1608", 0, 0);
    OLED_Show_String("Hello OLED!", "0806", 0, 20);
    OLED_Show_String("Big Font", "1608", 0, 32);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_Line
 * @expect 屏幕上出现：一条从左上到右下的对角线（线段模式），
 *         一条穿过屏幕中心的水平线（无限直线模式）。
 */
static void test_Draw_Line(void)
{
    TEST_BEGIN("12.Line");
    OLED_Draw_Line(0, 0, OLED_WIDTH - 1U, OLED_HEIGHT - 1U, 0); /* 对角线段 */
    OLED_Draw_Line(TEST_CX, TEST_CY, 1, 0, 1);                  /* 水平无限直线 */
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_Rectang
 * @expect 左侧一个空心矩形边框，右侧一个实心填充矩形。
 */
static void test_Draw_Rectang(void)
{
    TEST_BEGIN("13.Rectang");
    OLED_Draw_Rectang(5, 10, 50, 40, 0);    /* 空心 */
    OLED_Draw_Rectang(70, 10, 50, 40, 1);   /* 实心 */
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_Circle
 * @expect 左侧一个空心圆环，右侧一个实心圆。
 */
static void test_Draw_Circle(void)
{
    TEST_BEGIN("14.Circle");
    OLED_Draw_Circle(30, 32, 20, 0);        /* 空心 */
    OLED_Draw_Circle(96, 32, 20, 1);        /* 实心 */
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

#if OLED_ENABLE_WAVE
/**
 * @test   OLED_Draw_Wave
 * @expect 屏幕上出现一条按当前宽高缩放的正弦波形曲线。
 */
static void test_Draw_Wave(void)
{
    TEST_BEGIN("15.Wave");
    OLED_Draw_Wave(0, TEST_CY, (int16_t)(OLED_HEIGHT / 3U), 0,
                   (OLED_WIDTH >= 8U) ? (uint16_t)(OLED_WIDTH / 2U) : 4U, 0, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}
#endif

/**
 * @test   OLED_Show_Number
 * @expect 依次显示：整数 -12345、无符号 65535、浮点 3.14。
 */
static void test_Show_Number(void)
{
    TEST_BEGIN("16.Number");
    int16_t n1 = -12345;
    uint16_t n2 = 65535;
    float n3 = 3.14f;
    OLED_Show_Number(&n1, OLED_NUM_S16, 0, "0806", 0, 0);
    OLED_Show_Number(&n2, OLED_NUM_U16, 0, "0806", 0, 12);
    OLED_Show_Number(&n3, OLED_NUM_FLOAT, 2, "0806", 0, 24);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Printf
 * @expect 屏幕显示格式化字符串 "Val:1234 T:25.6C"。
 */
static void test_Printf(void)
{
    TEST_BEGIN("17.Printf");
    OLED_Printf("0806", 0, 10, "Val:%d T:25.6C", 1234);
    OLED_Printf("1608", 0, 30, "Hello %s", "World");
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Show_Int / OLED_Show_Uint / OLED_Show_Hex
 * @expect 三行分别显示："-99999"、"4294967295"、"0xDEAD"。
 */
static void test_Show_Int_Hex(void)
{
    TEST_BEGIN("18.Int/Hex");
    OLED_Show_Int(-99999, "0806", 0, 0);
    OLED_Show_Uint(4294967295u, "0806", 0, 12);
    OLED_Show_Hex(0xDEAD, 4, "0806", 0, 24);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Clear_Rect / OLED_Refresh_Rect
 * @expect 先全屏填白，然后中间一个矩形区域被擦黑（局部清除），
 *         再通过局部刷新只更新该区域到屏幕。
 */
static void test_Clear_Refresh_Rect(void)
{
    TEST_BEGIN("19.Rect Ops");
    OLED_GRAM_Fill();
    OLED_GRAM_Refresh();
    HAL_Delay(800);
    OLED_Clear_Rect(30, 16, 68, 32);   /* 中间挖一个黑洞 */
    OLED_Refresh_Rect(30, 16, 68, 32); /* 局部刷新 */
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_ProgressBar
 * @expect 两个进度条：上方实心 75%，下方斜线条纹 50%。
 */
static void test_ProgressBar(void)
{
    TEST_BEGIN("20.ProgressBar");
    OLED_Draw_ProgressBar(10, 10, 108, 12, 75, 0);  /* 实心 75% */
    OLED_Draw_ProgressBar(10, 35, 108, 12, 50, 1);  /* 条纹 50% */
    OLED_Show_String("75%", "0806", 50, 0);
    OLED_Show_String("50%", "0806", 50, 50);
    OLED_GRAM_Refresh();
    HAL_Delay(TEST_DELAY);
}

/**
 * @test   OLED_Draw_ProgressBar 动态演示
 * @expect 进度条从 0% 匀速增长到 100%，中间实时显示百分比数字。
 *         帧率尽可能高（仅局部刷新进度条区域）。
 *         完成后自动进入下一个测试。
 */
static void test_ProgressBar_Dynamic(void)
{
    /* 进度条参数 */
    const uint8_t bar_x = 10;
    const uint8_t bar_y = 24;
    const uint8_t bar_w = 108;
    const uint8_t bar_h = 16;

    /* 百分比文字位置（进度条内部居中） */
    const uint8_t txt_y = bar_y + (bar_h - 8) / 2;  /* 0806 字体高 8px */

    OLED_GRAM_Clear();
    OLED_Show_String("20b.Dynamic Bar", "0806", 0, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(500);

    for (uint8_t pct = 0; pct <= 100; pct++) {
        /* 仅擦除进度条区域，避免全屏清除 */
        OLED_Clear_Rect(bar_x, bar_y, bar_w, bar_h);

        /* 画进度条 */
        OLED_Draw_ProgressBar(bar_x, bar_y, bar_w, bar_h, pct, 0);

        /* 在进度条中间叠加百分比文字 */
        char buf[5];
        buf[0] = (pct >= 100) ? '1' : ' ';
        buf[1] = (pct >= 10)  ? (char)('0' + (pct / 10) % 10) : ' ';
        buf[2] = (char)('0' + pct % 10);
        buf[3] = '%';
        buf[4] = '\0';
        if (pct >= 100) { buf[0]='1'; buf[1]='0'; buf[2]='0'; }

        /* 文字居中：4 字符 × 6px = 24px，bar 中心 = bar_x + bar_w/2 */
        uint8_t txt_x = bar_x + (bar_w - 24) / 2;
        OLED_Show_String(buf, "0806", txt_x, txt_y);

        /* 局部刷新仅进度条区域 → 最大帧率 */
        OLED_Refresh_Rect(bar_x, bar_y, bar_w, bar_h);

        HAL_Delay(30);  /* ~33 FPS */
    }

    HAL_Delay(800);
}

/**
 * @test   OLED_Draw_ProgressBar 动态斜线条纹演示
 * @expect 进度条从 0% 增长到 100%，斜线条纹有动画流动效果（视觉上条纹不断向右滑动），
 *         同时实时显示帧率。利用局部刷新确保高帧率。
 */
static void test_ProgressBar_Stripe_Dynamic(void)
{
    /* 进度条参数 */
    const uint8_t bar_x = (OLED_WIDTH >= 24U) ? (uint8_t)(OLED_WIDTH / 12U) : 1U;
    const uint8_t bar_y = (uint8_t)(OLED_HEIGHT / 3U);
    const uint8_t bar_w = (uint8_t)(OLED_WIDTH - 2U * bar_x);
    const uint8_t bar_h = (OLED_HEIGHT >= 24U) ? (uint8_t)(OLED_HEIGHT / 3U) : 6U;

    /* 刷新区域（覆盖进度条 + 上方 FPS 文字 + 下方百分比文字） */
    const uint8_t refresh_y = 0;
    const uint8_t refresh_h = OLED_HEIGHT;

    OLED_GRAM_Clear();
    OLED_Show_String("20c.Stripe Bar", "0806", 0, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(500);

    uint8_t phase = 0;     // 条纹相位偏移，递增产生流动动画

    for (int16_t pct = 0; pct <= 100; pct++) {
        /* 在当前百分比下，让条纹流动若干帧再跳下一个百分比 */
        uint8_t anim_frames = (pct < 100) ? 3 : 10;  // 100% 时多停留几帧

        for (uint8_t f = 0; f < anim_frames; f++) {
            /* 擦除进度条 + 文字区域 */
            OLED_Clear_Rect(bar_x, bar_y, bar_w, bar_h);
            OLED_Clear_Rect(0, 0, OLED_WIDTH, 10);
            OLED_Clear_Rect(0, bar_y + bar_h + 2, OLED_WIDTH, 10);

            /* ===== 绘制进度条边框 ===== */
            OLED_Draw_Line(bar_x, bar_y, bar_w - 1, 0, 0);
            OLED_Draw_Line(bar_x, bar_y + bar_h - 1, bar_w - 1, 0, 0);
            OLED_Draw_Line(bar_x, bar_y, 0, bar_h - 1, 0);
            OLED_Draw_Line(bar_x + bar_w - 1, bar_y, 0, bar_h - 1, 0);

            /* ===== 斜线条纹填充（带动画相位） ===== */
            uint8_t inner_w = bar_w - 2;
            uint8_t inner_h = bar_h - 2;
            uint8_t fill_w  = (uint8_t)((uint16_t)inner_w * pct / 100u);
            uint8_t x0 = bar_x + 1;
            uint8_t y0 = bar_y + 1;

            // 直接按字节操作显存，比逐像素快数倍
            for (uint8_t dy = 0; dy < inner_h; dy++) {
                uint8_t screen_y = y0 + dy;
                uint8_t pg  = screen_y >> 3;        // 目标页
                uint8_t bit = screen_y & 0x07;      // 页内位偏移
                uint8_t* ptr = &draw_buffer[pg][x0]; // 行首指针

                for (uint8_t dx = 0; dx < fill_w; dx++) {
                    // 斜线条纹公式：(dx + dy + phase) % 4 < 2 为亮
                    if (((dx + dy + phase) & 3u) < 2u)
                        ptr[dx] |= (1u << bit);
                }
            }

            /* ===== 百分比文字 ===== */
            OLED_Printf("0806", bar_x + bar_w / 2 - 12, bar_y + bar_h + 3,
                        "%d%%", pct);

            /* ===== FPS 显示 ===== */
            uint16_t fps = OLED_Calc_FPS_Int();
            OLED_Printf("0806", 0, 0, "FPS:%d Stripe", fps);

            /* 局部刷新 → 高帧率 */
            OLED_Refresh_Rect(0, refresh_y, OLED_WIDTH, refresh_h);

            phase++;  // 相位递增 → 条纹向右流动
        }
    }

    HAL_Delay(800);
}

/**
 * @test   OLED_Select_Buffer / OLED_Swap_Buffers（双缓冲）
 * @expect 后台画一个大圆，Swap 后圆完整出现在屏幕上（无撕裂）。
 *         证明双缓冲工作正常。
 */
static void test_Double_Buffer(void)
{
    OLED_Select_Buffer(1);              /* 选后台 */
    OLED_GRAM_Clear();
    OLED_Show_String("21.DblBuf", "0806", 0, 0);
    OLED_Draw_Circle(TEST_CX, TEST_CY, TEST_RADIUS, 1);
    OLED_Swap_Buffers();                /* 后台→前台+刷新 */
    HAL_Delay(TEST_DELAY);
    OLED_Select_Buffer(0);              /* 恢复前台直接模式 */
}

/**
 * @test   OLED_Scroll_Soft_Vertical（循环垂直滚动）
 * @expect 文字 "Scroll V" 从屏幕上方缓缓向下循环滚动，滚出底部后从顶部重新出现。
 */
static void test_Scroll_Vertical(void)
{
    OLED_GRAM_Clear();
    OLED_Show_String("Scroll V", "1608", 20, 24);
    OLED_GRAM_Refresh();
    HAL_Delay(500);
    for (uint16_t i = 0; i < OLED_HEIGHT; i += 2U) {
        OLED_Scroll_Soft_Vertical(2);   /* 每次下移 2 像素 */
        OLED_GRAM_Refresh();
        HAL_Delay(50);
    }
    HAL_Delay(500);
}

/**
 * @test   OLED_Scroll_Soft_Horizontal（循环水平滚动）
 * @expect 文字 "Scroll H" 从屏幕中间向右循环滚动，滚出右边后从左边重新出现。
 */
static void test_Scroll_Horizontal(void)
{
    OLED_GRAM_Clear();
    OLED_Show_String("Scroll H", "1608", 20, 24);
    OLED_GRAM_Refresh();
    HAL_Delay(500);
    for (uint16_t i = 0; i < OLED_WIDTH; i += 2U) {
        OLED_Scroll_Soft_Horizontal(2); /* 每次右移 2 像素 */
        OLED_GRAM_Refresh();
        HAL_Delay(30);
    }
    HAL_Delay(500);
}

/**
 * @test   OLED_Set_Rotation（屏幕旋转）
 * @expect 依次以 0°/90°/180°/270° 显示圆+文字，圆在不同朝向完整显示。
 *         90°/270° 时逻辑宽高互换。
 */
static void test_Rotation(void)
{
    /* 0° */
    OLED_Set_Rotation(OLED_ROT_0);
    OLED_GRAM_Clear();
    OLED_Show_String("R:0", "0806", 0, 0);
    OLED_Draw_Circle(TEST_CX, TEST_CY, TEST_RADIUS, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(1500);

    /* 90° */
    OLED_Set_Rotation(OLED_ROT_90);
    OLED_GRAM_Clear();
    OLED_Show_String("R:90", "0806", 0, 0);
    OLED_Draw_Circle(TEST_CY, TEST_CX, TEST_RADIUS, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(1500);

    /* 180° */
    OLED_Set_Rotation(OLED_ROT_180);
    OLED_GRAM_Clear();
    OLED_Show_String("R:180", "0806", 0, 0);
    OLED_Draw_Circle(TEST_CX, TEST_CY, TEST_RADIUS, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(1500);

    /* 270° */
    OLED_Set_Rotation(OLED_ROT_270);
    OLED_GRAM_Clear();
    OLED_Show_String("R:270", "0806", 0, 0);
    OLED_Draw_Circle(TEST_CY, TEST_CX, TEST_RADIUS, 0);
    OLED_GRAM_Refresh();
    HAL_Delay(1500);

    /* 恢复 */
    OLED_Set_Rotation(OLED_ROT_0);
}

/**
 * @test   OLED_Scroll_HW_H / OLED_Scroll_HW_Switch（硬件水平滚动）
 * @expect 文字 "HW Scroll" 向右匀速滚动 3 秒，然后停止。
 *         注意：硬件滚动期间不能写显存，停止后需重写。
 */
static void test_HW_Scroll(void)
{
    OLED_GRAM_Clear();
    OLED_Show_String("HW Scroll->", "1608", 0, 20);
    OLED_GRAM_Refresh();
    OLED_Wait_DMA();

    OLED_Scroll_HW_H(0, 0, 7, 5);      /* 向右滚动全页，速度 5 */
    OLED_Scroll_HW_Switch(1);           /* 启动滚动 */
    HAL_Delay(3000);
    OLED_Scroll_HW_Switch(0);           /* 停止滚动 */
    HAL_Delay(500);
}

/* ====================================================================== */
/*                     总测试入口                                          */
/* ====================================================================== */

void OLED_Test_All(void)
{
    /* 确保旋转为 0°，缓冲区为前台 */
    OLED_Set_Rotation(OLED_ROT_0);
    OLED_Select_Buffer(0);

    test_GRAM_Refresh();
    test_Calc_FPS();
    test_GRAM_Clear();
    test_GRAM_Fill();
    test_Clear();
    test_Sleep_Wake();
    test_Set_Contrast();
    test_Set_Mirror();
    test_Set_Inverse();
    test_Export_Import();
    test_Draw_Point();
    test_Show_String();
    test_Draw_Line();
    test_Draw_Rectang();
    test_Draw_Circle();
#if OLED_ENABLE_WAVE
    test_Draw_Wave();
#endif
    test_Show_Number();
    test_Printf();
    test_Show_Int_Hex();
    test_Clear_Refresh_Rect();
    test_ProgressBar();
    test_ProgressBar_Dynamic();
    test_ProgressBar_Stripe_Dynamic();
    test_Double_Buffer();
    test_Scroll_Vertical();
    test_Scroll_Horizontal();
    test_Rotation();
    test_HW_Scroll();

    /* ===== 测试完成 ===== */
    OLED_Set_Rotation(OLED_ROT_0);
    OLED_Select_Buffer(0);
    OLED_GRAM_Clear();
    OLED_Show_String("ALL TESTS", "1608", 10, 16);
    OLED_Show_String("DONE!", "1608", 38, 36);
    OLED_GRAM_Refresh();
}
