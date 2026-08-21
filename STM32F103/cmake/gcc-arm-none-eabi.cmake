set(CMAKE_SYSTEM_NAME               Generic)
set(CMAKE_SYSTEM_PROCESSOR          arm)

set(CMAKE_C_COMPILER_ID GNU)
set(CMAKE_CXX_COMPILER_ID GNU)

# Resolve the GNU Arm toolchain without storing a machine-specific absolute path
# in the repository. STM32CubeIDE for VS Code injects CUBE_BUNDLE_PATH; ordinary
# command-line builds can still provide arm-none-eabi-* through PATH.
set(_STM32_GCC_HINTS "")
if(DEFINED ENV{CUBE_BUNDLE_PATH} AND NOT "$ENV{CUBE_BUNDLE_PATH}" STREQUAL "")
    file(GLOB _STM32_GCC_BUNDLES LIST_DIRECTORIES true
        "$ENV{CUBE_BUNDLE_PATH}/gnu-tools-for-stm32/*")
    list(SORT _STM32_GCC_BUNDLES COMPARE NATURAL ORDER DESCENDING)
    foreach(_STM32_GCC_BUNDLE IN LISTS _STM32_GCC_BUNDLES)
        if(IS_DIRECTORY "${_STM32_GCC_BUNDLE}/bin")
            list(APPEND _STM32_GCC_HINTS "${_STM32_GCC_BUNDLE}/bin")
        endif()
    endforeach()
endif()

find_program(_STM32_ARM_GCC
    NAMES arm-none-eabi-gcc arm-none-eabi-gcc.exe
    HINTS ${_STM32_GCC_HINTS})

if(NOT _STM32_ARM_GCC)
    message(FATAL_ERROR
        "GNU Arm compiler not found. Open the project with the official "
        "STM32CubeIDE for Visual Studio Code extension so Bundle Manager can "
        "provide gnu-tools-for-stm32, or add arm-none-eabi-gcc to PATH.")
endif()

get_filename_component(_STM32_GCC_BIN_DIR "${_STM32_ARM_GCC}" DIRECTORY)

function(_stm32_find_tool output_variable tool_name)
    find_program(${output_variable}
        NAMES "${tool_name}" "${tool_name}.exe"
        HINTS "${_STM32_GCC_BIN_DIR}"
        NO_DEFAULT_PATH)
    if(NOT DEFINED ${output_variable} OR
       "${${output_variable}}" MATCHES "-NOTFOUND$")
        message(FATAL_ERROR
            "Required GNU Arm tool '${tool_name}' was not found beside "
            "${_STM32_ARM_GCC}.")
    endif()
    set(${output_variable} "${${output_variable}}" PARENT_SCOPE)
endfunction()

_stm32_find_tool(_STM32_ARM_GXX     arm-none-eabi-g++)
_stm32_find_tool(_STM32_ARM_OBJCOPY arm-none-eabi-objcopy)
_stm32_find_tool(_STM32_ARM_SIZE    arm-none-eabi-size)

set(CMAKE_C_COMPILER                "${_STM32_ARM_GCC}")
set(CMAKE_ASM_COMPILER              "${_STM32_ARM_GCC}")
set(CMAKE_CXX_COMPILER              "${_STM32_ARM_GXX}")
set(CMAKE_LINKER                    "${_STM32_ARM_GXX}")
set(CMAKE_OBJCOPY                   "${_STM32_ARM_OBJCOPY}")
set(CMAKE_SIZE                      "${_STM32_ARM_SIZE}")

set(CMAKE_EXECUTABLE_SUFFIX_ASM     ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_C       ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_CXX     ".elf")

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# MCU specific flags
set(TARGET_FLAGS "-mcpu=cortex-m3 ")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${TARGET_FLAGS}")
set(CMAKE_ASM_FLAGS "${CMAKE_C_FLAGS} -x assembler-with-cpp -MMD -MP")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -fdata-sections -ffunction-sections -fstack-usage")

# The cyclomatic-complexity parameter must be defined for the Cyclomatic complexity feature in STM32CubeIDE to work.
# However, most GCC toolchains do not support this option, which causes a compilation error; for this reason, the feature is disabled by default.
# set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fcyclomatic-complexity")

set(CMAKE_C_FLAGS_DEBUG "-Os -g3")
set(CMAKE_C_FLAGS_RELEASE "-Os -g0")
set(CMAKE_CXX_FLAGS_DEBUG "-Os -g3")
set(CMAKE_CXX_FLAGS_RELEASE "-Os -g0")

set(CMAKE_CXX_FLAGS "${CMAKE_C_FLAGS} -fno-rtti -fno-exceptions -fno-threadsafe-statics")

set(CMAKE_EXE_LINKER_FLAGS "${TARGET_FLAGS}")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -T \"${CMAKE_SOURCE_DIR}/STM32F103XX_FLASH.ld\"")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} --specs=nano.specs")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,-Map=${CMAKE_PROJECT_NAME}.map -Wl,--gc-sections")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--print-memory-usage")
set(TOOLCHAIN_LINK_LIBRARIES "m")
