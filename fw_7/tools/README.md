# Локальний OTA-сервер

`ota_server.py` - сервер оновлень на вашому комп'ютері з тими ж прошивками, що і на GitHub, плюс режими для перевірки помилок OTA. Python 3.8+, нічого встановлювати не треба. Працює на macOS, Linux і Windows.

Комп'ютер і ESP32 мають бути в одній Wi-Fi мережі.

## Запуск

```bash
cd tools
python3 ota_server.py --download     # один раз: скачати прошивки з GitHub у server_files/
python3 ota_server.py                # запустити сервер (порт 8000)
```

Сервер покаже IP комп'ютера і готові команди, наприклад:

```
On the device (after login):
  ota server http://192.168.1.10:8000/fw7/
```

На пристрої (після `login`):

```
ota server http://192.168.1.10:8000/fw7/
ota check
ota update beta
...
ota server default        # в кінці - повернутись на GitHub
```

У вікні сервера видно кожен запит пристрою. Зупинити - Ctrl+C.

## Режими для тестування

```bash
python3 ota_server.py --slow 20        # 20 KB/s - завантаження ~50 с, є час вимкнути Wi-Fi / роутер
python3 ota_server.py --drop-at 50     # сервер обриває з'єднання на 50%
python3 ota_server.py --stable 2.3.0   # підмінити версію в stable.txt
python3 ota_server.py --beta 9.9.9     # канал вказує на версію, якої немає
python3 ota_server.py --port 8080      # інший порт
```

Тестові файли (команда `ota url`):

```
ota url http://<IP>:8000/test/garbage.bin      # не прошивка
ota url http://<IP>:8000/test/truncated.bin    # обрізана прошивка
ota url http://<IP>:8000/test/corrupted.bin    # пошкоджені байти всередині
```

## Якщо не працює

- macOS при першому запуску може спитати "Allow incoming connections" для Python - натисніть Allow. Якщо пропустили: System Settings -> Network -> Firewall -> Options, дозволити Python.
- `Cannot start on port 8000` - сервер уже запущено в іншому вікні, або `--port 8080`.
- IP неправильний (VPN, кілька мереж) - подивіться IP: macOS `ipconfig getifaddr en0`, Windows `ipconfig`, Linux `hostname -I`.
- Пристрій пише E402 - перевірте, що комп'ютер і ESP32 в одній мережі, і відкрийте `http://<IP>:8000/fw7/stable.txt` у браузері телефона з тієї ж мережі.
