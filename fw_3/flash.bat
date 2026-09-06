@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ==== fw_1 flashing script ====
rem Flashes bootloader.bin, partition-table.bin, fw_1.bin
rem onto an ESP32-S3 device using esptool.

rem --- locate esptool ---
set "ESPTOOL="
set "FALLBACK=C:\Espressif\tools\python\v6.0.1\venv\Scripts\esptool.exe"
where esptool.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "ESPTOOL=esptool.exe"
) else (
    if exist "%FALLBACK%" (
        set "ESPTOOL=%FALLBACK%"
    )
)

if "%ESPTOOL%"=="" (
    echo [ERROR] esptool.exe not found.
    echo Install it first, e.g.:  pip install esptool
    echo.
    pause
    exit /b 1
)

echo Using esptool: %ESPTOOL%
echo.

rem --- show available COM ports to help the user pick ---
echo Detected COM ports:
powershell -NoProfile -Command "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\d+' } | Select-Object -ExpandProperty Name"
echo.
echo (Look for something like 'USB-SERIAL', 'CP210x' or 'CH340' - that's usually the device.
echo  If nothing is listed, check the cable/driver, or look in Device Manager - Ports (COM and LPT).)
echo.

rem --- COM port: use --port/-p argument if given, otherwise ask ---
set "COMPORT="
if /i "%~1"=="--port" set "COMPORT=%~2"
if /i "%~1"=="-p" set "COMPORT=%~2"
if "%COMPORT%"=="" if not "%~1"=="" set "COMPORT=%~1"

if "%COMPORT%"=="" (
    set /p COMPORT="Enter the device COM port (e.g. COM5): "
)
if "%COMPORT%"=="" (
    echo No COM port entered. Aborting.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo   Flashing fw_1 firmware on %COMPORT%
echo ==============================================
echo.

"%ESPTOOL%" --chip esp32s3 --port %COMPORT% --baud 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_freq 80m --flash_size 2MB 0x0 bootloader.bin 0x8000 partition-table.bin 0x10000 fw_1.bin

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAILED] Flashing failed with exit code %ERRORLEVEL%.
) else (
    echo.
    echo [OK] Device flashed successfully.
)

echo.
pause
endlocal
