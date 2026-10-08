# station_WiFi - покомпонентні бінарі (4 файли)

Той самий образ, що і в `git1`, але розкладений на компоненти. Прошивка з OTA, тому файлів 4 (додається otadata - службова область, яка каже бутлоадеру, з якого OTA-слота вантажитись).

| Файл | Адреса |
|---|---|
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| ota_data_initial.bin | 0xd000 |
| station_WiFi.bin | 0x10000 |

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash \
  0x0     bootloader.bin \
  0x8000  partition-table.bin \
  0xd000  ota_data_initial.bin \
  0x10000 station_WiFi.bin
```

`station_WiFi.bin` - це app-образ: саме цей файл кладеться на OTA-сервер і роздається пристрою командою `ota <url>` (merged-файл для OTA не годиться).
