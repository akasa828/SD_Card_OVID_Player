/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "dma.h"
#include "fonts.hpp"
#include "i2c.h"
#include "gpio.h"
#include "oled.hpp"
#include "stm32f1xx_hal.h"
/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration */

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_I2C1_Init();
  /* USER CODE BEGIN 2 */
  OLED_Init();
  OLED_Select_Buffer(1);
  OLED_Draw_Rectang(5, 5, 50, 20, 1);  
  OLED_Draw_Rectang(60, 5, 60, 20, 0);  
  OLED_Show_String("FillRect", "0806", 10, 28);
  OLED_Swap_Buffers();
  HAL_Delay(1500);
  OLED_GRAM_Clear();
  OLED_Draw_Circle(32, 32, 28, 1);      
  OLED_Draw_Circle(96, 32, 20, 0);      
  OLED_Show_String("Circle", "0806", 50, 56);
  OLED_Swap_Buffers();
  HAL_Delay(1500);
  OLED_GRAM_Clear();
  OLED_Show_String("ABCDEFGHIJ", "0806", 0, 0);
  OLED_Show_String("Speed Test", "1608", 0, 12);
  OLED_Show_String("0123456789", "2412", 0, 32);
  OLED_Swap_Buffers();
  HAL_Delay(1500);
  OLED_GRAM_Clear();
  OLED_Show_String("ProgressBar:", "0806", 0, 0);
  OLED_Draw_ProgressBar(5, 12, 118, 12, 75, 0);   // 实心 75%
  OLED_Draw_ProgressBar(5, 28, 118, 12, 50, 1);   // 条纹 50%
  OLED_Swap_Buffers();
  HAL_Delay(1500);
  OLED_SW_Invert_Rect(20, 8, 90, 36);
  OLED_Swap_Buffers();
  HAL_Delay(1500);

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    // ===== 循环测试: 综合性能演示 (双缓冲 + FPS) =====

    // 场景A: 实心圆弹跳 + 实时 FPS（测试 Draw_Circle/HLine_Fast 加速）
    int16_t bx = 30, by = 30, vx = 2, vy = 1;
    for (uint16_t frame = 0; frame < 200; frame++) {
      OLED_GRAM_Clear();
      OLED_Draw_Circle(bx, by, 10, 1);
      OLED_Draw_Rectang(0, 0, 127, 63, 0);

      uint16_t fps = OLED_Calc_FPS_Int();
      OLED_Show_String("FPS:", "0806", 0, 56);
      OLED_Show_Uint(fps, "0806", 24, 56);

      OLED_Swap_Buffers();

      bx += vx; by += vy;
      if (bx <= 10 || bx >= 117) vx = -vx;
      if (by <= 10 || by >= 52)  vy = -vy;
    }

    // 场景B: 进度条动画（测试 ProgressBar/Fill_Rect_Fast 加速）
    for (uint8_t pct = 0; pct <= 100; pct += 2) {
      OLED_GRAM_Clear();
      OLED_Show_String("Loading...", "1608", 20, 5);
      OLED_Draw_ProgressBar(10, 30, 108, 14, pct, 0);

      char buf[5];
      buf[0] = '0' + pct / 100;
      buf[1] = '0' + (pct / 10) % 10;
      buf[2] = '0' + pct % 10;
      buf[3] = '%';
      buf[4] = '\0';
      OLED_Show_String(buf[0] == '0' ? buf + 1 : buf, "0806", 52, 50);

      OLED_Swap_Buffers();
    }
    HAL_Delay(500);

    // 场景C: 软件滚动（测试 Scroll 位运算优化）
    OLED_GRAM_Clear();
    OLED_Show_String("Scroll Test", "1608", 10, 24);
    OLED_Swap_Buffers();
    HAL_Delay(500);
    for (int16_t i = 0; i < 128; i++) {
      OLED_Scroll_Soft_Horizontal(2);
      OLED_Swap_Buffers();
    }
    for (int16_t i = 0; i < 64; i++) {
      OLED_Scroll_Soft_Vertical(1);
      OLED_Swap_Buffers();
    }
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
