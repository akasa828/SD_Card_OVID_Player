@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem Build the Windows OVID Converter from any checkout location.
set "REPO_ROOT=%~dp0"
set "TOOLS_DIR=%REPO_ROOT%tools"
set "VENV_DIR=%REPO_ROOT%.venv-converter-build"
set "PROJECT_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PYTHON_EXE="
set "PYTHON_FOUND="
set "PYTHON_TOO_OLD="
set "REQUIREMENTS=%TOOLS_DIR%\requirements-converter-build.txt"
set "PACKAGE_SCRIPT=%TOOLS_DIR%\package_converter.ps1"

rem Reuse an environment that the user already activated in VS Code.
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" call :use_python "%VIRTUAL_ENV%\Scripts\python.exe"

rem Otherwise reuse the project-specific build environment when it is valid.
if not defined PYTHON_EXE if exist "%PROJECT_PYTHON%" call :use_python "%PROJECT_PYTHON%"

echo ============================================================
echo  OVID Converter - Windows build
echo ============================================================
echo.

if not exist "%REQUIREMENTS%" (
    echo [ERROR] Missing file: %REQUIREMENTS%
    goto :failed
)

if not exist "%PACKAGE_SCRIPT%" (
    echo [ERROR] Missing file: %PACKAGE_SCRIPT%
    goto :failed
)

if not defined PYTHON_EXE (
    echo [1/4] Creating the Python build environment...
    rem Python Install Manager stores its selected runtime here.
    if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
        call :create_venv "%LOCALAPPDATA%\Python\bin\python.exe"
    )

    rem The Python launcher can select any installed, supported Python 3.
    if not defined PYTHON_EXE (
        py.exe -3 -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 16) else 2)" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_FOUND=1"
            py.exe -3 -m venv "%VENV_DIR%" >nul 2>nul
            if exist "%PROJECT_PYTHON%" call :use_python "%PROJECT_PYTHON%"
        )
    )

    rem Try every traditional Python executable exposed through PATH.
    if not defined PYTHON_EXE (
        for /f "delims=" %%P in ('where python.exe 2^>nul') do (
            if not defined PYTHON_EXE call :create_venv "%%~fP"
        )
    )

    rem Finally scan common per-user installation directories.
    if not defined PYTHON_EXE (
        for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -Command "Get-ChildItem -Path '%LOCALAPPDATA%\Python\pythoncore-*\python.exe','%LOCALAPPDATA%\Programs\Python\Python3*\python.exe' -File -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty FullName"`) do if not defined PYTHON_EXE call :create_venv "%%~fP"
    )

    if not defined PYTHON_EXE if defined PYTHON_FOUND (
        echo [ERROR] Python 3 was found, but the virtual environment could not be created.
        echo         Make sure this project folder is writable and try again.
        echo         You can also delete .venv-converter-build before retrying.
        goto :failed
    )

    if not defined PYTHON_EXE if defined PYTHON_TOO_OLD (
        echo [ERROR] Python was found, but its version is not supported.
        echo         OVID Converter requires Python 3.10 through 3.15.
        goto :failed
    )

    if not defined PYTHON_EXE (
        echo [ERROR] No usable Python runtime was found.
        echo         Install Python 3.10 through 3.15 from https://www.python.org/downloads/
        echo         Then run this batch file again.
        goto :failed
    )
) else (
    echo [1/4] Reusing the existing Python build environment.
)

for /f "delims=" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do echo       Using %%V

echo [2/4] Installing or updating build dependencies...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS%"
if errorlevel 1 (
    echo [ERROR] Failed to install the converter build dependencies.
    goto :failed
)

echo [3/4] Checking Inno Setup...
set "INSTALLER_SWITCH="
set "INSTALLER_SKIPPED="
where ISCC.exe >nul 2>nul
if errorlevel 1 if not exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" if not exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" if not exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    echo [WARNING] Inno Setup 6 was not found.
    echo           OVID Converter.exe and Portable.zip will still be created.
    echo           Install https://jrsoftware.org/isdl.php if you also need Setup.exe.
    set "INSTALLER_SWITCH=-SkipInstaller"
    set "INSTALLER_SKIPPED=1"
)

echo [4/4] Building the portable package and installer...
pushd "%REPO_ROOT%"
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PACKAGE_SCRIPT%" -PythonExecutable "%PYTHON_EXE%" %INSTALLER_SWITCH%
) else if "%~2"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PACKAGE_SCRIPT%" -Version "%~1" -PythonExecutable "%PYTHON_EXE%" %INSTALLER_SWITCH%
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PACKAGE_SCRIPT%" -Version "%~1" -WindowsVersion "%~2" -PythonExecutable "%PYTHON_EXE%" %INSTALLER_SWITCH%
)
set "BUILD_RESULT=%ERRORLEVEL%"
popd

if not "%BUILD_RESULT%"=="0" (
    echo [ERROR] Packaging failed with exit code %BUILD_RESULT%.
    goto :failed
)

echo.
echo Build completed successfully.
echo Output directory:
echo   %TOOLS_DIR%\dist
if defined INSTALLER_SKIPPED echo Setup.exe was skipped because Inno Setup 6 is not installed.
echo.
echo Optional command-line usage:
echo   Build_OVID_Converter.bat 1.3.1 1.3.1.0
echo.
pause
exit /b 0

:create_venv
call :check_python "%~1"
if errorlevel 1 exit /b %ERRORLEVEL%
set "PYTHON_FOUND=1"
"%~1" -m venv "%VENV_DIR%" >nul 2>nul
if not exist "%PROJECT_PYTHON%" exit /b 1
call :use_python "%PROJECT_PYTHON%"
exit /b %ERRORLEVEL%

:use_python
call :check_python "%~1"
if errorlevel 1 exit /b %ERRORLEVEL%
set "PYTHON_EXE=%~1"
set "PYTHON_FOUND=1"
exit /b 0

:check_python
"%~1" -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 16) else 2)" >nul 2>nul
if "%ERRORLEVEL%"=="2" set "PYTHON_TOO_OLD=1"
exit /b %ERRORLEVEL%

:failed
echo.
echo The build was not completed. Review the message above and try again.
echo.
pause
exit /b 1
