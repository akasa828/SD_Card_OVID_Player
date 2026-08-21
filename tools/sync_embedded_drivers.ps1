param(
    [string]$DriverWorkspace = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$firmwareCore = Join-Path $repoRoot 'STM32F103\Core'
$oledRoot = Join-Path $DriverWorkspace 'STM32-HAL-SSD1306-SH1106'
$sdRoot = Join-Path $DriverWorkspace 'STM32-HAL-SPI-SD-FatFs'

foreach ($path in @($oledRoot, $sdRoot, $firmwareCore)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Required directory not found: $path"
    }
}

$copies = @(
    @((Join-Path $oledRoot 'Core\OLED\oled.cpp'), (Join-Path $firmwareCore 'OLED\oled.cpp')),
    @((Join-Path $oledRoot 'Core\OLED\oled.hpp'), (Join-Path $firmwareCore 'OLED\oled.hpp')),
    @((Join-Path $oledRoot 'Core\OLED\oled_port.h'), (Join-Path $firmwareCore 'OLED\oled_port.h')),
    @((Join-Path $oledRoot 'Core\Port\oled_stm32_hal.c'), (Join-Path $firmwareCore 'Port\oled_stm32_hal.c')),
    @((Join-Path $oledRoot 'Core\Port\oled_stm32_hal.h'), (Join-Path $firmwareCore 'Port\oled_stm32_hal.h')),
    @((Join-Path $sdRoot 'Core\Micro_SD\SD_reader.c'), (Join-Path $firmwareCore 'Micro_SD\SD_reader.c')),
    @((Join-Path $sdRoot 'Core\Micro_SD\SD_reader.h'), (Join-Path $firmwareCore 'Micro_SD\SD_reader.h')),
    @((Join-Path $sdRoot 'Core\Port\sd_stm32_hal.c'), (Join-Path $firmwareCore 'Port\sd_stm32_hal.c')),
    @((Join-Path $sdRoot 'Core\Port\sd_stm32_hal.h'), (Join-Path $firmwareCore 'Port\sd_stm32_hal.h')),
    @((Join-Path $sdRoot 'Core\Port\SD_reader_compat.h'), (Join-Path $firmwareCore 'Port\SD_reader_compat.h')),
    @((Join-Path $sdRoot 'Core\fatfs\sd_fatfs.h'), (Join-Path $firmwareCore 'fatfs\sd_fatfs.h'))
)

foreach ($copy in $copies) {
    Copy-Item -LiteralPath $copy[0] -Destination $copy[1] -Force
    Write-Host "Copied $($copy[0])"
}

Write-Host 'Driver copies synchronized. Review git diff and rebuild before committing.'
