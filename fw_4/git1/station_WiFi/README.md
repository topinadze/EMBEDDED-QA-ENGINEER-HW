# station_WiFi - merged binary (1 файл)

Прошивка Wi-Fi станції для ESP32-S3 DevKit: Wi-Fi STA + OTA + датчик відстані HC-SR04 + реле + RGB LED + 4 кнопки.

## Що в папці

- `station_WiFi_merged.bin` - повний образ (bootloader + partition table + otadata + app), флешиться одним файлом на адресу 0x0

## Як прошити

```bash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> erase-flash
esptool.py --chip esp32s3 --port <ВАШ_ПОРТ> -b 460800 write-flash 0x0 station_WiFi_merged.bin
```

Після прошивки: термінал 115200 8N1, RESET, у boot log має з'явитись запрошення. Наберіть `help`.

## Команди (help)

```
connect                    - connect to WiFi AP (інтерактивний: scan -> SSID/номер -> пароль)
disconnect                 - disconnect from WiFi AP
status                     - show WiFi connection status (SSID, IP, RSSI)
scan                       - scan for WiFi networks
distance                   - measure continuously (Enter to stop)
distance <seconds>         - measure for N seconds
relay on / relay off       - turn relay ON/OFF
led on / led off           - LED white / off
led auto                   - LED follows WiFi status
led rgb                    - smooth RGB cycle for 5 seconds
ota <url>                  - flash firmware from URL
ota-test-server            - simulate OTA update (requires WiFi)
sysinfo                    - show system information
temp                       - show chip temperature
sensor status              - show all sensors status
reboot                     - reboot device
help                       - show this help
```

## Кнопки

- K1 (GPIO41) - distance 10s
- K2 (GPIO40) - relay toggle
- K3 (GPIO39) - wifi disconnect / reconnect (saved credentials)
- K4 (GPIO38) - diode toggle
