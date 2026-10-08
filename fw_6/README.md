# fw_6: station_WiFi Smart Lamp + OTA

- `station_WiFi_v1.3.0_merged.bin` - стартова версія 1.3.0 (bootloader + partition table + otadata + app), шиється одним файлом на 0x0
- `PRD.md` - опис прошивки і вимоги
- `HW-16.md` - завдання

Версії 1.4.0 і 1.5.0 через esptool не шиються - пристрій сам качає їх по OTA з https://github.com/BohdanHorbanych/esp32-ota-files

## Як прошити

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> erase-flash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash 0x0 station_WiFi_v1.3.0_merged.bin
```

`erase-flash` обов'язковий - інакше в NVS і otadata залишаться дані попередніх прошивок.

Після прошивки: термінал 115200 8N1, RESET, у boot log має бути `station_WiFi fw v1.3.0 ready`. Далі `help`, `connect`, `ota check`.

Порт: macOS - `/dev/cu.usbserial-*` або `/dev/cu.usbmodem-*`, Windows - `COMx`, Linux - `/dev/ttyUSB*` або `/dev/ttyACM*`.
