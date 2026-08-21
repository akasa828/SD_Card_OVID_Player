@echo off
setlocal
chcp 65001 >nul

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 "%~dp0bootstrap_converter.py"
    exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    python "%~dp0bootstrap_converter.py"
    exit /b %errorlevel%
)

echo Error: Python 3.10 or later was not found.
echo Download the packaged OVID Converter from GitHub Releases,
echo or install Python and run this file again.
pause
exit /b 1

