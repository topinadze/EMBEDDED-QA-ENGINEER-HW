# How to flash and access fw_1 in flash_ready
FW version: v0.9.2 (build 20260811)


## 1. Find the device's COM port
in terminal
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\d+' } | Select-Object -ExpandProperty Name

expl
Silicon Labs CP210x USB to UART Bridge (COM8)
Intel(R) Active Management Technology - SOL (COM3)
----> u need COM8

## 2. Flash it

go to folder - fw_1 - flash_ready
.\flash.bat --port COM8 

(also works: `.\flash.bat -p COM8` or just `.\flash.bat COM8`)


## 3. Accessing the device - full interactive console

Same idea as flashing - pass the port directly or let it ask:
.\monitor.bat --port COM8 


Once connected, type `help` and press Enter to see the command list from the device itself. To exit: `Ctrl+]`.

## Important
- A port (e.g. `COM8`) can only be held open by **one** program at a time. Close any other program that might be holding the port (Flash Download Tool, a previous `flash.bat`/`monitor.bat` run, etc.) before opening a new one, otherwise you'll get an "Access is denied" / "port is already in use" error.
- If nothing shows after connecting - make sure you selected the correct baud rate (`115200`), and try pressing the RESET button on the board.
