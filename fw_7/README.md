# fw_7: SENTRY SWM-2 - модуль гідроакустичної вахти підводного човна

- `sentry_fw7_v2.1.0_merged.bin` - стартова версія 2.1.0 (bootloader + partition table + otadata + app), шиється одним файлом на 0x0
- `PRD.md` - опис прошивки і вимоги
- `HW-17.md` - завдання
- `tools/` - локальний OTA-сервер для тестування помилок оновлення

Версія 2.3.0 через esptool не шиється - пристрій качає її по OTA з https://github.com/BohdanHorbanych/esp32-ota-files (`fw7/`).

## Як прошити

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> erase-flash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash 0x0 sentry_fw7_v2.1.0_merged.bin
```

`erase-flash` обов'язковий - інакше в NVS і otadata залишаться дані попередніх прошивок.

Після прошивки: термінал 115200 8N1, RESET, у boot log `SENTRY SWM-2 ... fw v2.1.0` і `ready. state 1 NORMAL (patrol)`. Далі `help`, `connect`, `register <login> <pass>`, `login <login> <pass>`, `ota check`.

Порт: macOS - `/dev/cu.usbserial-*` або `/dev/cu.usbmodem-*`, Windows - `COMx`, Linux - `/dev/ttyUSB*` або `/dev/ttyACM*`.
