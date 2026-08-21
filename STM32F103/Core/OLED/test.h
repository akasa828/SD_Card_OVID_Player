/**
  ******************************************************************************
  * @file    test.h
  * @author  riochihao
  * @brief   OLED 驱动功能测试声明
  ******************************************************************************
  */

#ifndef __OLED_TEST_H
#define __OLED_TEST_H

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief  OLED 全功能顺序测试（逐函数验证）
 * @note   按照 oled.cpp 中函数定义顺序依次测试每个 API。
 *         每个测试步骤显示约 2 秒，观察屏幕现象与注释描述是否一致。
 *         测试完成后屏幕显示 "ALL TESTS DONE"。
 *         调用前需确保 OLED_Init() 已执行。
 */
void OLED_Test_All(void);
#ifdef __cplusplus
}
#endif

#endif /* __OLED_TEST_H */
