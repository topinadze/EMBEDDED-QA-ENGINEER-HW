# Bluedroid_GATT_Server (SENTRY-BLE) - покомпонентні бінарі (3 файли)

Той самий образ, що і в `git1`, але розкладений на компоненти. OTA тут немає, тому класичні 3 файли.

| Файл | Адреса |
|---|---|
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| Bluedroid_GATT_Server.bin | 0x10000 |

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash \
  0x0     bootloader.bin \
  0x8000  partition-table.bin \
  0x10000 Bluedroid_GATT_Server.bin
```
