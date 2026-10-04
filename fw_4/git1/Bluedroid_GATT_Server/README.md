# Bluedroid_GATT_Server (SENTRY-BLE) - merged binary (1 файл)

BLE GATT-сервер для ESP32-S3 DevKit. Рекламується як **SENTRY-BLE**. Сервіси: Heart Rate (0x180D) + Automation IO (0x1815, LED і реле). Додатково: UART CLI та 4 кнопки.

## Що в папці

- `Bluedroid_GATT_Server_merged.bin` - повний образ (bootloader + partition table + app), флешиться одним файлом на адресу 0x0

## Як прошити

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> erase-flash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash 0x0 Bluedroid_GATT_Server_merged.bin
```

Після прошивки: термінал 115200 8N1, RESET, дочекатись `[Boot] Device ready. Type 'help' for commands`.

## BLE-інтерфейс

- Ім'я в рекламі: `SENTRY-BLE`
- Heart Rate Service `0x180D`, характеристика `0x2A37` (read + indicate через CCCD) - пульс 60-80 bpm, оновлюється щосекунди
- Automation IO Service `0x1815`:
  - LED-характеристика `00001525-1212-efde-1523-785feabcd123` (read/write): write 1/0 - фізичний LED + лог `LED ON!` / `LED OFF!`
  - RELAY-характеристика `00001526-1212-efde-1523-785feabcd123` (read/write): write 1/0 - реле GPIO8 + лог `RELAY ON!` / `RELAY OFF!`
- Всі BLE-події дублюються в UART-лог (другий канал спостереження для тестів)

## Команди UART (help)

```
status        - BLE state, LED, relay, heart rate
led on/off    - LED control (same LED as BLE char)
relay on/off  - relay control (same relay as BLE char)
hr spike      - inject abnormal heart rate (~190) for 5s
adv restart   - restart BLE advertising (if not connected)
disconnect    - drop current BLE connection
reboot        - reboot device
help          - show this help
```

## Кнопки

- K1 (GPIO41) - heart rate spike
- K2 (GPIO40) - LED toggle (local)
- K3 (GPIO39) - drop BLE connection / restart advertising
- K4 (GPIO38) - relay toggle
