@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ==== fw_1 serial console / monitor ====
rem Opens an interactive UART console to the device (logs + commands).
rem Type "help" once connected to see available device commands.

rem --- locate python (with pyserial) ---
set "PYTHON="
set "FALLBACK=C:\Espressif\tools\python\v6.0.1\venv\Scripts\python.exe"
if exist "%FALLBACK%" (
    set "PYTHON=%FALLBACK%"
) else (
    where python.exe >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON=python.exe"
    )
)

if "%PYTHON%"=="" (
    echo [ERROR] python.exe not found.
    echo Install Python and pyserial first, e.g.:  pip install pyserial
    echo.
    pause
    exit /b 1
)

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
echo   Opening console on %COMPORT% @ 115200 baud
echo   Type "help" for available device commands.
echo   Press Ctrl+] to exit.
echo ==============================================
echo.

"%PYTHON%" -m serial.tools.miniterm %COMPORT% 115200

echo.
echo Console closed.
pause
endlocal
