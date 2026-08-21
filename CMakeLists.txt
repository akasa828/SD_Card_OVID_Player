cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME SD_card_mp4_mode_player)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM, C and C++ languages
enable_language(C CXX ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
    Core/OLED/oled.cpp
    Core/OLED/UI.c
    Core/OLED/test.c
    Core/Micro_SD/SD_reader.c
    Core/Micro_SD/sd_debug.c
    Core/function/function.c
    Core/function/app_ui.c
    Core/function/system_diag.c
    Core/fatfs/ff.c
    Core/fatfs/diskio.c
    Core/fatfs/ffsystem.c
    Core/fatfs/ffunicode.c
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
    Core/Inc
    Core/OLED
    Core/Micro_SD
    Core/function
    Core/fatfs
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined symbols
)

# 便于 CI/编译矩阵验证屏幕宏；不传时使用 oled.hpp 中的默认值。
if(DEFINED OLED_WIDTH_OVERRIDE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE OLED_WIDTH=${OLED_WIDTH_OVERRIDE})
endif()
if(DEFINED OLED_HEIGHT_OVERRIDE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE OLED_HEIGHT=${OLED_HEIGHT_OVERRIDE})
endif()
if(DEFINED OLED_CONTROLLER_OVERRIDE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE OLED_CONTROLLER=${OLED_CONTROLLER_OVERRIDE})
endif()
if(DEFINED OLED_COLUMN_OFFSET_OVERRIDE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE OLED_COLUMN_OFFSET=${OLED_COLUMN_OFFSET_OVERRIDE})
endif()
if(DEFINED OLED_I2C_CLOCK_OVERRIDE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE I2C1_INITIAL_CLOCK_HZ=${OLED_I2C_CLOCK_OVERRIDE})
endif()

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)
