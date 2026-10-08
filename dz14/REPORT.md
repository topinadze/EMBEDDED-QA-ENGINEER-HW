# Звіт про тестування ДЗ-14: Wi-Fi та BLE

**Виріб:** ESP32-S3 DevKit  
**Прошивка Частини A:** `station_WiFi` (`fw_4/git1/station_WiFi/station_WiFi_merged.bin`)  
**Прошивка Частини B:** `Bluedroid_GATT_Server` (`fw_4/git1/Bluedroid_GATT_Server/Bluedroid_GATT_Server_merged.bin`)  
**Тестове середовище:** Python 3.10+, Pytest, pyserial, bleak, pytest-asyncio, Allure  
**Інструмент ручного тестування BLE:** nRF Connect for Mobile / Bluetooth LE Explorer  

---

## 1. Налаштування тестового оточення

### Встановлення залежностей
```powershell
.venv\Scripts\pip.exe install -r dz14/requirements.txt
```

### Налаштування Wi-Fi креденшилів
Креденшили тестової точки доступу (2.4 GHz) не хардкодяться в тестах. Їх можна передати через змінні оточення перед запуском або відредагувати у файлі `dz14/config/wifi_config.py`:

**PowerShell (Windows):**
```powershell
$env:TEST_WIFI_SSID="YourHotspot_2.4G"
$env:TEST_WIFI_PASSWORD="YourPassword123"
```

**Bash / Linux / macOS:**
```bash
export TEST_WIFI_SSID="YourHotspot_2.4G"
export TEST_WIFI_PASSWORD="YourPassword123"
```

---

## 2. Частина A: Wi-Fi — Автоматизоване тестування (`station_WiFi`)

### Порядок виконання
Частина A виконується повністю перед Частиною B: спочатку тестується `station_WiFi`, результати та баги фіксуються тут; лише після цього виконується `erase-flash` і плата перепрошивається на `Bluedroid_GATT_Server`. Для Wi-Fi потрібна керована точка доступу 2.4 GHz. Перед запуском задайте `TEST_WIFI_SSID` і `TEST_WIFI_PASSWORD` у середовищі; не додавайте реальний пароль до звіту або архіву.

1. Очистити flash і прошити `station_WiFi` (замініть COM4 на ваш порт):
   ```powershell
   .venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM4 erase-flash
   .venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM4 -b 460800 write-flash 0x0 fw_4/git1/station_WiFi/station_WiFi_merged.bin
   ```
2. Виконати весь набір Wi-Fi автотестів:
   ```powershell
   .venv\Scripts\python.exe -m pytest dz14/tests/wifi/ -v
   ```
3. Переглянути UART-вкладення для кожного тесту в Allure, зафіксувати фактичні результати та відомі дефекти. Для скриншотів і додаткових доказів використовуйте `dz14/screenshots/`.
4. Не починати BLE-перевірки і не перепрошивати плату, доки результати Частини A не зафіксовані.

### Результати прогону pytest
Під час тестів, що використовують UART-драйвер, зібраний UART-вивід додається до результату відповідного тесту як вкладення **UART log** в Allure (у тому числі для тестів, що завершилися помилкою). Відкрийте потрібний тест у Allure та перегляньте його вкладення, щоб побачити збережений UART-лог.

| Тест | Вимога PRD | Опис | Статус |
| :--- | :--- | :--- | :--- |
| `test_scan_finds_networks` | FR-W1 | Список непорожній, тестова мережа знайдена; UART-рядок цільової мережі перевіряється на номер і RSSI у dBm | PASSED |
| `test_connect_success` | FR-W2 | Підключення до SSID/пароля, отримання IP і вимірювання часу встановлення з'єднання після надсилання credentials | PASSED |
| Ручна перевірка `connect` вибором номера мережі | FR-W2 | Підключення вибором індексу мережі зі списку сканування | PASSED — перевірено вручну |
| `test_connect_success` + ручна перевірка `status` | FR-W5 | Статус показує стан, SSID, IP та RSSI | PASSED — автоматичний тест перевіряє connected/IP; ручний UART `status` після reconnect показав SSID `TopA-node`, IP `10.123.30.49`, RSSI `-31 dBm` |
| `test_disconnect` | FR-W5, FR-W6 | Розрив з'єднання; `status` має показати відключений стан | XFAIL — [BUG-01](#bug-01): UART підтверджує disconnect, але `status` хибно показує connected |
| `test_credentials_survive_reboot` | FR-W4 | Збереження в NVS, підключення після reboot по Enter | FLAKY / PARTIAL — credentials і SSID `TopA-node` зчитуються після reboot, але підключення нестабільне: стан доходить до `run`, проте не отримує IP до `connection timeout`; `status` показує `WiFi: disconnected` |
| `test_wrong_password` | FR-W2 | Валідний SSID + неправильний пароль (>=8 символів) відхиляється з повідомленням про помилку | PASSED — з'єднання не встановлюється; тест перевіряє UART на `fail`/`timeout` |
| `test_short_password` | FR-W3 | Короткий пароль відхиляється повідомленням `password too short (min 8 chars)` без спроби підключення | PASSED — перевіряються точне повідомлення та відсутність початку асоціації |
| `test_nonexistent_ssid` | FR-W2 | Неіснуючий SSID: помилка/таймаут, пристрій живий (відповідає help) | PASSED — підключення відхилено, пристрій відповідає на `help`; UART перевіряється на `fail`/`timeout` |

**Підсумок FR-W1–FR-W7:** тести FR-W1, FR-W2 і FR-W3 перевіряють відповідні критерії; вибір мережі за номером зі scan list додатково перевірено вручну. Автоматичний тест FR-W2 перевіряє обмеження часу до 10 с. FR-W4 має часткове підтвердження збереження credentials, але відновлення з'єднання після reboot нестабільне (див. результат `test_credentials_survive_reboot`). FR-W5 після підключення підтверджено ручним `status`, але перевірка після `disconnect` виявила [BUG-01](#bug-01) (FR-W5/FR-W6). FR-W7 підтверджено ручним тестом. Відомі прогалини покриття та firmware-дефекти наведено вище.

Додатковий UART-доказ часу для FR-W2: від `connecting to SSID` (1452132 ms) до `got ip` (1453232 ms) минуло **1.10 с** за таймстемпами пристрою. Повний шлях від команди `connect` (1448752 ms), включно зі scan і паузою на SSID prompt, до `got ip` зайняв **4.48 с**. Автоматичний тест вимірює час саме від надсилання credentials/Enter до успішного підключення.

```
(.venv) PS C:\Users\ADMIN\OneDrive\Documents\Embedded QA\EMBEDDED-QA-ENGINEER-HW\EMBEDDED-QA-ENGINEER-HW> pytest dz14/tests/wifi/ -v
================== test session starts ===================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\ADMIN\OneDrive\Documents\Embedded QA\EMBEDDED-QA-ENGINEER-HW\EMBEDDED-QA-ENGINEER-HW\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\ADMIN\OneDrive\Documents\Embedded QA\EMBEDDED-QA-ENGINEER-HW\EMBEDDED-QA-ENGINEER-HW\dz14
configfile: pytest.ini
plugins: allure-pytest-2.16.0, asyncio-1.4.0, order-1.5.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 7 items                                         

dz14\tests\wifi\test_wifi_negative.py::TestWiFiNegative::test_wrong_password PASSED
dz14\tests\wifi\test_wifi_negative.py::TestWiFiNegative::test_short_password PASSED
dz14\tests\wifi\test_wifi_negative.py::TestWiFiNegative::test_nonexistent_ssid PASSED
dz14\tests\wifi\test_wifi_positive.py::TestWiFiPositive::test_scan_finds_networks PASSED
dz14\tests\wifi\test_wifi_positive.py::TestWiFiPositive::test_connect_success PASSED
dz14\tests\wifi\test_wifi_positive.py::TestWiFiPositive::test_disconnect XFAILty SSID and IP 0.0.0.0
after disconnect.)
dz14\tests\wifi\test_wifi_positive.py::TestWiFiPositive::test_credentials_survive_reboot PASSED

======== 6 passed, 1 xfailed in 74.60s (0:01:14) =========
```
### Ручна перевірка FR-W7 — повторні спроби після втрати мережі
Підключити ESP32 до контрольованої Wi-Fi мережі, вимкнути точку доступу без вимкнення ESP32 і спостерігати UART-лог на предмет повторних спроб. Потім відновити ту саму мережу та перевірити автоматичне підключення. Не надсилати `disconnect`: FR-W6 вимагає, щоб ця команда не запускала автоматичне перепідключення.

| Передумови / дія | Очікуваний результат | Статус |
| :--- | :--- | :--- |
| Пристрій підключений до точки доступу; точку доступу вимкнено, ESP32 залишається увімкненим | У UART видно повторні спроби підключення після втрати мережі | PASSED |
| Ту саму точку доступу з тими самими обліковими даними знову увімкнено | Без втручання в ESP32 він автоматично підключається та отримує IP | PASSED |
UART-доказ:
```text
I (1340213) wifi station: using saved SSID: TopA-node
I (1340213) wifi station: connecting to SSID:TopA-node ...
I (1340213) wifi:new:<1,0>, old:<1,0>, ap:<255,255>, sta:<1,0>, prof:1, snd_ch_cfg:0x0
I (1340213) wifi:state: init -> auth (0xb0)
I (1340233) wifi:state: auth -> assoc (0x0)
I (1340233) wifi:state: assoc -> run (0x10)
I (1340263) wifi:connected with TopA-node, aid = 1, channel 1, BW20, bssid = 52:89:e9:8b:14:59
I (1340263) wifi:security: WPA2-PSK, phy: bgn, rssi: -25, cipher(pairwise:0x3, group:0x3), pmf:1
I (1340273) wifi:pm start, type: 1

I (1340273) wifi:dp: 1, bi: 102400, li: 3, scale listen interval from 307200 us to 307200 us
I (1340283) wifi:set rx beacon pti, rx_bcn_pti: 0, bcn_timeout: 25000, mt_pti: 0, mt_time: 10000
I (1340353) wifi:dp: 2, bi: 102400, li: 4, scale listen interval from 307200 us to 409600 us
I (1340353) wifi:AP's beacon interval = 102400 us, DTIM period = 2
I (1341323) esp_netif_handlers: sta ip: 10.123.30.49, mask: 255.255.255.0, gw: 10.123.30.28
I (1341323) wifi station: got ip:10.123.30.49
I (1341323) wifi station: successfully connected to SSID:TopA-node
I (1358123) wifi:bcn_timeout,ap_probe_send_start
I (1360633) wifi:ap_probe_send over, reset wifi status to disassoc
I (1360633) wifi:state: run -> init (0xc800)
I (1360643) wifi:pm stop, total sleep time: 9793682 us / 20363869 us

I (1360643) wifi:new:<1,0>, old:<1,0>, ap:<255,255>, sta:<1,0>, prof:1, snd_ch_cfg:0x0
I (1360643) wifi station: retry to connect to the AP
I (1363063) wifi station: retry to connect to the AP
I (1365473) wifi station: retry to connect to the AP
I (1367883) wifi station: retry to connect to the AP
I (1367893) wifi:new:<1,0>, old:<1,0>, ap:<255,255>, sta:<1,0>, prof:1, snd_ch_cfg:0x0
I (1367893) wifi:state: init -> auth (0xb0)
I (1367903) wifi:state: auth -> assoc (0x0)
I (1367913) wifi:state: assoc -> run (0x10)
I (1367923) wifi:connected with TopA-node, aid = 1, channel 1, BW20, bssid = d2:c7:17:8b:f2:91
I (1367923) wifi:security: WPA2-PSK, phy: bgn, rssi: -28, cipher(pairwise:0x3, group:0x3), pmf:1
I (1367933) wifi:pm start, type: 1

I (1367933) wifi:dp: 1, bi: 102400, li: 3, scale listen interval from 307200 us to 307200 us
I (1367943) wifi:set rx beacon pti, rx_bcn_pti: 0, bcn_timeout: 25000, mt_pti: 0, mt_time: 10000
I (1368003) wifi:dp: 2, bi: 102400, li: 4, scale listen interval from 307200 us to 409600 us
I (1368003) wifi:AP's beacon interval = 102400 us, DTIM period = 2
I (1368983) esp_netif_handlers: sta ip: 10.123.30.49, mask: 255.255.255.0, gw: 10.123.30.28
I (1368983) wifi station: got ip:10.123.30.49
---- Sent utf8 encoded message: "status\n" ----
status

I (1418113) wifi station: WiFi: connected
I (1418113) wifi station:   SSID: TopA-node
I (1418113) wifi station:   IP:   10.123.30.49
I (1418113) wifi station:   RSSI: -31 dBm
```

### Ручна перевірка FR-B
Результати ручної перевірки кнопок за вимогами PRD:

| Кнопка / дія | Очікуваний результат | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| K1 (GPIO41) — натиснути при активному Wi-Fi | Вимірювання відстані триває 10 секунд | `button 1 pressed (GPIO41)`, `[K1] distance 10s...`, періодичні покази у см, `[K1] done` | PASSED |
| K2 (GPIO40) — натиснути двічі | Реле перемикається ON, потім OFF | `button 2 pressed (GPIO40)`, `[K2] relay ON`; повторне натискання: `[K2] relay OFF`; клацання реле підтверджено на стенді | PASSED |
| K3 (GPIO39) — натиснути під час підключення | Wi-Fi відключається | `button 3 pressed (GPIO39)`, `[K3] wifi disconnect`, `wifi station: disconnected` | PASSED |
| K3 (GPIO39) — натиснути повторно після відключення | Reconnect за збереженими креденшилами | Повторне натискання знову вивело `[K3] wifi disconnect` та `disconnected`; reconnect не почався. Див. [BUG-02](#bug-02) | FAILED — [BUG-02](#bug-02) |
| K4 (GPIO38) — натиснути двічі | Діод перемикається ON, потім OFF | `button 4 pressed (GPIO38)`, `[K4] diode ON`; повторне натискання: `[K4] diode OFF`; вмикання/вимикання діода підтверджено на стенді | PASSED |
| FR-B5 — перевірити логування натискань | Кожне натискання містить номер кнопки та GPIO | Для K1–K4 присутні `button N pressed (GPIOxx)` у наданому UART-логу | PASSED |

K2 і K4 перевірені UART-логом і візуальним спостереженням користувача.

### Ручна перевірка FR-O2 — OTA через тестовий сервер
| Дія | Очікуваний результат | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| Підключити пристрій до Wi-Fi та виконати `ota-test-server` | Демонстраційне OTA-оновлення завершується без помилки, пристрій автоматично перезавантажується | Команда повідомила про firmware v2.0.1; компоненти `distance_sensor v1.3.0`, `relay_controller v2.1.0` та `wifi_manager v3.0.2` завершилися зі статусом `OK`; виведено `OTA Update Complete. Restarting...`, після чого ESP32 завантажився | PASSED |

**Примітка:** Після перезавантаження завантажувач показав застосунок з `ota_0` (offset `0x10000`), а інформація застосунку показала build `9866f06-dirty`. У наданому логу немає окремого підтвердження версії `v2.0.1` як версії застосунку після reboot; зафіксовано саме успішне завершення demo OTA, встановлення перелічених компонентів і перезавантаження.

### Ручна перевірка FR-P1 — вимірювання відстані
| Дія | Очікуваний результат за PRD | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| Виконати `distance`; натиснути Enter для зупинки | Безперервні вимірювання у сантиметрах до натискання Enter | Виводилися повторні покази у см; вимірювання зупинено Enter. Приклади: `7.7 cm`, `28.8 cm`, `9.0 cm` | PASSED |
| Виконати `distance 5` | Вимірювання у сантиметрах протягом заданих 5 секунд із завершенням команди | Виведено `measuring for 5 seconds...`, покази відстані та `done` приблизно через 5 секунд | PASSED |
| Перевірити відсутність еха | Виводиться `timeout` | У наданому логу випадок без еха не перевірявся | NOT TESTED |

### Ручна перевірка FR-P2 — реле та стан сенсорів
| Дія | Очікуваний результат за PRD | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| Виконати `relay on`, потім `relay off` | Керування реле ON/OFF | UART: `relay ON` та `relay OFF`; спрацювання реле (клацання) підтверджено на стенді | PASSED |
| Виконати `sensor status` після `relay off` | Відображається актуальний стан реле | UART: `Relay: OFF`; також показано `Distance: 22.8 cm`, `LED: auto (WiFi status)`, `WiFi: connected`, `Temp: 30.4 C` | PASSED |

FR-P2 підтверджений UART-логом і візуальним спостереженням користувача.

### Ручна перевірка FR-P3 — режими LED
| Дія | Очікуваний результат за PRD | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| Виконати `led on`, потім `led off` | LED вмикається та вимикається | UART: `LED ON`, `LED OFF`; вмикання/вимикання LED підтверджено на стенді | PASSED |
| Виконати `led auto` при підключеному Wi-Fi | У режимі auto LED зелений при підключеному Wi-Fi | UART: `LED auto mode`; `sensor status` показав `LED: auto (WiFi status)` і `WiFi: connected`; зелений LED підтверджено на стенді | PASSED |
| Перевірити авто-режим при відключеному Wi-Fi | LED червоний при відключеному Wi-Fi | Червоний LED при втраті Wi-Fi підтверджено на стенді | PASSED |
| Виконати `led rgb` | Запускається RGB-режим | UART: `RGB cycle 5s...`, далі `RGB done`; роботу RGB підтверджено на стенді | PASSED |

### Ручна перевірка FR-P4 — діагностичні команди
| Команда | Очікуваний результат за PRD | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| `sysinfo` | Інформація про чіп, heap та системні параметри | `ESP32-S3 rev 2`, 2 cores, 160 MHz, Flash 2 MB, Free heap 272 KB, Min heap 269 KB, uptime 0h 08m 45s, Temperature 31.4 C | PASSED |
| `temp` | Виводиться температура чіпа | UART: `chip temperature: 30.4 C` | PASSED |
| `sensor status` | Виводиться діагностичний стан сенсорів | UART показав Distance 22.0 cm, Relay OFF, LED auto (WiFi status), WiFi connected, Temp 31.4 C | PASSED |

### Ручна перевірка FR-P5 — reboot
| Дія | Очікуваний результат за PRD | Фактичний результат / UART-доказ | Статус |
| :--- | :--- | :--- | :--- |
| Виконати `reboot` | Відлік 3-2-1 та перезавантаження пристрою | UART: `rebooting in 3...`, `2...`, `1...`; після цього ESP32 перезавантажився та пройшов boot sequence | PASSED |

---

## 3. Частина B: BLE — Ручні перевірки та Dual-Channel автотест (`Bluedroid_GATT_Server`)

### Порядок виконання
1. Зробити очищення та прошивку BLE:
   ```powershell
   .venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM4 erase-flash
   .venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM4 -b 460800 write-flash 0x0 fw_4/git1/Bluedroid_GATT_Server/Bluedroid_GATT_Server_merged.bin
   ```
2. Запустити UART-моніторинг (115200 8N1).
3. Провести ручні перевірки B1 через **nRF Connect**.
4. Запустити автотест B2:
   ```powershell
   .venv\Scripts\python.exe -m pytest dz14/tests/ble/ -v
   ```

### B1. Чек-лист ручних перевірок

### Фото та скриншоти доказів
#### Фото стенда
- [bench-setup.jpg](screenshots/hardware/bench-setup.jpg)

#### Скриншоти застосунку nRF Connect
- Сканування та RSSI: [scan-sentry-rssi-49.jpg](screenshots/ble-app/scan-sentry-rssi-49.jpg), [scan-sentry-rssi-48.jpg](screenshots/ble-app/scan-sentry-rssi-48.jpg)
- Реклама `SENTRY-BLE` у застосунку: [advertising-sentry-ble.jpg](screenshots/ble-app/advertising-sentry-ble.jpg)
- GATT-сервіси: [gatt-connected-services.jpg](screenshots/ble-app/gatt-connected-services.jpg)
- Зчитування та автоматичне оновлення Heart Rate: [heart-rate-reading.jpg](screenshots/ble-app/heart-rate-reading.jpg), [heart-rate-stream-1s.jpg](screenshots/ble-app/heart-rate-stream-1s.jpg)
- HR spike: [heart-rate-spike-190-led-enabled.jpg](screenshots/ble-app/heart-rate-spike-190-led-enabled.jpg); [heart-rate-spike-190-duplicate.jpg](screenshots/ble-app/heart-rate-spike-190-duplicate.jpg) — дубльований доказ spike
- GATT-стан після відключення: [disconnected-after-k3.jpg](screenshots/ble-app/disconnected-after-k3.jpg)

#### Звіт Allure
- Результат BLE Dual-Channel тесту в Allure: [ble-dual-channel-report.png](screenshots/allure/ble-dual-channel-report.png)

| # | Перевірка | Вимога PRD | Очікуваний результат | Фактичний результат / Доказ (UART лог, скріншот) | Статус |
| :- | :--- | :--- | :--- | :--- | :-: |
| 1 | **Scan** | FR-A1 | Знайти `SENTRY-BLE` у nRF Connect і зафіксувати RSSI | nRF Connect знайшов `SENTRY-BLE` (RSSI близько -52 dBm; скриншоти показують -49 і -48 dBm): [scan 1](screenshots/ble-app/scan-sentry-rssi-49.jpg), [scan 2](screenshots/ble-app/scan-sentry-rssi-48.jpg) | PASSED |
| 2 | **Connect + discovery** | FR-G1, FR-G3 | Підключитися; виявити Heart Rate `0x180D` / `0x2A37` і Automation IO `0x1815` з LED та RELAY характеристиками | nRF Connect показує GATT-сервіси: [GATT services](screenshots/ble-app/gatt-connected-services.jpg). UART підтвердив підключення `Connected, conn_id 0, remote 6d:5f:87:da:91:31` | PASSED |
| 3 | **Heart Rate** | FR-G1, FR-G2 | Підписатися на indications `0x2A37`; бачити оновлення щосекунди в діапазоні 60–80 bpm | nRF Connect показує зчитування Heart Rate: [HR reading](screenshots/ble-app/heart-rate-reading.jpg); автоматичне оновлення приблизно раз на секунду видно на [HR stream](screenshots/ble-app/heart-rate-stream-1s.jpg). Типові вимірювання в діапазоні 60–80 bpm | PASSED |
| 4 | **HR spike** | FR-C3, FR-K1 | Запустити spike CLI та K1; клієнт отримує ~190–199 bpm протягом 5 секунд | CLI та K1 перевірені; UART показав відповідно `190, 190, 190, 197, 192` і `198, 190, 194, 192, 195` bpm. BLE-застосунок показав spike: [HR spike](screenshots/ble-app/heart-rate-spike-190-led-enabled.jpg); [дубльований скриншот](screenshots/ble-app/heart-rate-spike-190-duplicate.jpg). Після spike пульс повернувся до звичайного діапазону | PASSED |
| 5 | **LED через BLE** | FR-G4 | Write `01`/`00` у LED характеристику: LED ON/OFF і відповідні UART-повідомлення | UART підтверджує `01` → `LED ON!` і `00` → `LED OFF!`; стан LED у GATT-застосунку показано на [скриншоті spike з LED](screenshots/ble-app/heart-rate-spike-190-led-enabled.jpg); вимкнення після write `00` підтверджено на стенді | PASSED |
| 6 | **RELAY через BLE** | FR-G4 | Write `01`/`00` у RELAY характеристику: реле ON/OFF і відповідні UART-повідомлення | UART підтверджує `01` → `RELAY ON!` і `00` → `RELAY OFF!`; спрацювання в обох станах підтверджено на стенді | PASSED |
| 7 | **Read після Write** | FR-G5 | Read повертає `01` після write `01` і `00` після write `00` | Підтверджено читання актуального значення після обох станів запису | PASSED |
| 8 | **Конфлікт каналів** | FR-G5 | Увімкнути LED по BLE, вимкнути кнопкою K2 або CLI, прочитати `00` по BLE | Змішаний сценарій із застосунком і кнопкою перевірено для ON/OFF; BLE read після локальної зміни повертав актуальний стан | PASSED |
| 9 | **BLE disconnect + reconnect після K3** | FR-A2, FR-A3, FR-K3 | K3 розриває активне BLE-з'єднання; після цього пристрій знову доступний для підключення, а застосунок показує відновлене GATT-з'єднання | nRF Connect показує стан після розриву: [Disconnected](screenshots/ble-app/disconnected-after-k3.jpg), а окремий знімок підтверджує GATT-стан `CONNECTED`: [Connected services](screenshots/ble-app/gatt-connected-services.jpg) | PASSED |

### Додаткові перевірки PRD: UART CLI та кнопки
| Перевірка | Вимога PRD | Фактичний результат / доказ | Статус |
| :--- | :--- | :--- | :--- |
| `status` | FR-C2 | UART показав ім'я `SENTRY-BLE`, стан `connected` з MAC, пульс 71 bpm, LED/Relay OFF та uptime 1978 s | PASSED |
| `help` | FR-C1 | UART вивів список команд та опис кнопок K1–K4 | PASSED — перевірено вивід довідки |
| Інші команди CLI | FR-C1 | `hr spike` та `disconnect` перевірено в окремих сценаріях. Функціональну дію команд `led on/off`, `relay on/off`, `adv restart` і `reboot` через UART CLI в наявних доказах не зафіксовано | PARTIAL |
| Невідома команда `unknown` | FR-C4 | UART: `unknown command: 'unknown' (type 'help')` | PASSED |
| Команда `reboot` та boot-маркер | FR-C1, FR-C5 | `reboot` перезапускає пристрій; після завантаження з'являється `[Boot] Device ready. Type 'help' for commands` | UART: `rebooting...`, ESP32 пройшов boot sequence, BLE GATT services та Heart Rate task ініціалізовані; boot-маркер зафіксовано | PASSED |
| CLI `led on/off`, `relay on/off`, `adv restart` | FR-C1 | Кожна команда виконує заявлену дію | Функціональні результати цих команд через UART CLI окремо не зафіксовані | NOT RECORDED |
| K2: локальне перемикання LED | FR-K2 | Повторні натискання перемикнули LED ON/OFF; UART підтверджує `button 2 pressed (GPIO40)`, `[K2] LED toggle (local)`, `LED ON!` | PASSED |
| K3 при активному з'єднанні | FR-K3 | Натискання розриває BLE-з'єднання | Застосунок від'єднався; UART `status` показав `BLE: not connected, advertising`; скриншот: [після K3](screenshots/ble-app/disconnected-after-k3.jpg) | PASSED |
| K3 без активного з'єднання | FR-K3 | Натискання перезапускає рекламу | UART: `button 3 pressed (GPIO39)`, `[K3] restart advertising`, `Advertising start successfully` | PASSED |
| K4: локальне перемикання реле | FR-K4 | Кнопка керує реле локально | PASSED |

### B2. Результат автоматизованого Dual-Channel тесту
```
Команда: `.venv\Scripts\python.exe -m pytest dz14/tests/ble/ -v`
Результат: 1 passed in 6.21s
Тест: `dz14/tests/ble/test_ble_smoke.py::TestBLESmoke::test_ble_led_dual_channel` — PASSED
```
Allure evidence: [скриншот успішного BLE Dual-Channel тесту](screenshots/allure/ble-dual-channel-report.png).

---

## 4. Знайдені дефекти (Bug Reports)

### BUG-01: Wi-Fi status falsely reports connected after disconnect
- **Вимога PRD:** FR-W5, FR-W6
- **Кроки для відтворення:**
  1. Підключити ESP32-S3 до тестової Wi-Fi мережі.
  2. Виконати команду `disconnect`.
  3. Перевірити результат командою `status`.
- **Очікуваний результат:** Стан `disconnected`, SSID/IP відсутні.
- **Фактичний результат:** Відповідь на `disconnect` містить `wifi station: disconnected`, але наступний `status` виводить `WiFi: connected`, порожній SSID та IP `0.0.0.0`. Парсер повертає `connected=True`, через що `test_disconnect` падає.
- **Докази:** UART:
```text
I (2857722) wifi station: password: OK
I (2857722) wifi station: connecting to SSID:TopA-node ...
I (2857722) wifi:new:<1,0>, old:<1,0>, ap:<255,255>, sta:<1,0>, prof:1, snd_ch_cfg:0x0
I (2857722) wifi:state: init -> auth (0xb0)
I (2857742) wifi:state: auth -> assoc (0x0)
I (2857742) wifi:state: assoc -> run (0x10)
I (2857762) wifi:connected with TopA-node, aid = 1, channel 1, BW20, bssid = 72:1b:9b:f3:d4:02
I (2857762) wifi:security: WPA2-PSK, phy: bgn, rssi: -30, cipher(pairwise:0x3, group:0x3), pmf:1
I (2857772) wifi:pm start, type: 1

I (2857772) wifi:dp: 1, bi: 102400, li: 3, scale listen interval from 307200 us to 307200 us
I (2857782) wifi:set rx beacon pti, rx_bcn_pti: 0, bcn_timeout: 25000, mt_pti: 0, mt_time: 10000
I (2857792) wifi:dp: 2, bi: 102400, li: 4, scale listen interval from 307200 us to 409600 us
I (2857802) wifi:AP's beacon interval = 102400 us, DTIM period = 2
I (2859332) esp_netif_handlers: sta ip: 10.123.30.49, mask: 255.255.255.0, gw: 10.123.30.28
I (2859332) wifi station: got ip:10.123.30.49
I (2859332) wifi station: successfully connected to SSID:TopA-node
---- Sent utf8 encoded message: "status\r\n" ----
status

I (2870432) wifi station: WiFi: connected
I (2870432) wifi station:   SSID: TopA-node
I (2870432) wifi station:   IP:   10.123.30.49
I (2870432) wifi station:   RSSI: -21 dBm
---- Sent utf8 encoded message: "disconnect\r\n" ----
disconnect

I (2880992) wifi:state: run -> init (0x0)
I (2881002) wifi:pm stop, total sleep time: 20341059 us / 23225224 us

I (2881002) wifi:new:<1,0>, old:<1,0>, ap:<255,255>, sta:<1,0>, prof:1, snd_ch_cfg:0x0
I (2881002) wifi station: disconnected
I (2881002) wifi station: connect to the AP fail
---- Sent utf8 encoded message: "status\r\n" ----
status

W (2914812) wifi:Haven't to connect to a suitable AP now!
I (2914812) wifi station: WiFi: connected
I (2914812) wifi station:   SSID: 
I (2914812) wifi station:   IP:   0.0.0.0
I (2914812) wifi station:   RSSI: 0 dBm
```

- **Критичність:** Major

### BUG-02: K3 does not reconnect after disconnecting from Wi-Fi
- **Вимога PRD:** FR-B3
- **Кроки для відтворення:**
  1. Підключити ESP32-S3 до Wi-Fi та переконатися, що креденшили збережені.
  2. Натиснути K3 один раз і дочекатися відключення.
  3. Натиснути K3 повторно, коли пристрій уже не підключений.
- **Очікуваний результат:** Перше натискання відключає пристрій; друге запускає reconnect зі збереженими креденшилами.
- **Фактичний результат:** Перше натискання відключає пристрій. Наступні натискання знову виконують гілку disconnect і виводять `disconnected`; повідомлень про використання збереженого SSID, початок reconnect або отримання IP немає.
- **Докази:** UART-лог наданий під час тестування:
  ```text
  I (610393) wifi station: using saved SSID: TopA-node
  I (610393) wifi station: connecting to SSID:TopA-node ...
  I (610433) wifi:connected with TopA-node, aid = 1, channel 1, BW20, bssid = 66:f5:1f:ed:d1:51
  I (611513) esp_netif_handlers: sta ip: 10.123.30.49, mask: 255.255.255.0, gw: 10.123.30.28
  I (611513) wifi station: got ip:10.123.30.49
  I (611513) wifi station: successfully connected to SSID:TopA-node
  I (620123) wifi station: button 3 pressed (GPIO39)
  I (620123) wifi station: [K3] wifi disconnect
  I (620133) wifi station: disconnected
  I (638643) wifi station: button 3 pressed (GPIO39)
  I (638643) wifi station: [K3] wifi disconnect
  I (638643) wifi station: disconnected
  I (649343) wifi station: button 3 pressed (GPIO39)
  I (649343) wifi station: [K3] wifi disconnect
  I (649343) wifi station: disconnected
  I (650993) wifi station: button 3 pressed (GPIO39)
  I (650993) wifi station: [K3] wifi disconnect
  I (650993) wifi station: disconnected
  ```
- **Критичність:** Major

### BUG-03: BLE connection events are logged twice
- **Вимога PRD:** FR-A3
- **Кроки для відтворення:**
  1. Підключитися до `SENTRY-BLE` через BLE central.
  2. Переглянути UART-лог подій з'єднання та роз'єднання.
- **Очікуваний результат:** Кожна подія підключення або відключення логуються один раз.
- **Фактичний результат:** Одне підключення виводить два однакові рядки `Connected` з тим самим timestamp, `conn_id` і MAC-адресою. У наданому reconnect-лозі повідомлення `Disconnected` також повторюється двічі з тим самим timestamp, MAC-адресою та reason. З'єднання, реклама і повторне підключення при цьому працюють; наразі зафіксовано дублювання діагностичних логів.
- **Докази:** UART:
  ```text
  I (1484137) GATTS_DEMO: Connected, conn_id 0, remote 5f:8b:a5:5d:b3:9a
  I (1484137) GATTS_DEMO: Connected, conn_id 0, remote 5f:8b:a5:5d:b3:9a

  I (1695357) GATTS_DEMO: Disconnected, remote 5f:8b:a5:5d:b3:9a, reason 0x13
  I (1695357) GATTS_DEMO: Disconnected, remote 5f:8b:a5:5d:b3:9a, reason 0x13
  I (1695367) GATTS_DEMO: Advertising start successfully
  ```
  Дублювання `Connected` і `Disconnected` повторюється в UART. Після `Disconnected` реклама успішно відновлюється.
- **Пріоритет:** Low
