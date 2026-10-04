# PRD: station_WiFi Smart Lamp + OTA (fw_6)

Пристрій: ESP32-S3 DevKit (2 MB flash) з вбудованим RGB-світлодіодом WS2812 (GPIO48), датчиком відстані HC-SR04, реле, діодом і 4 кнопками.
Прошивка: `station_WiFi` - Wi-Fi станція з функцією **Smart Lamp** (керування RGB-світлодіодом) і **OTA-оновленням з інтернету**.

Керування - через UART-консоль: 115200 8N1, команда + Enter. Всі повідомлення прошивки йдуть у лог з тегом `wifi station`.

Цей документ - джерело очікуваної поведінки. Все, що поводиться не так, як тут написано, - баг.

---

## 0. Довідник команд

Детальна поведінка кожної команди - у пунктах, вказаних праворуч.

**Wi-Fi**

```
connect                      - підключення (scan -> SSID або номер -> пароль)       FR-W1, FR-W2
disconnect                   - відключення                                           FR-W4
status                       - стан Wi-Fi: SSID, IP, RSSI                            FR-W4
scan                         - список мереж                                          FR-W4
```

**Версія та OTA**

```
version                      - версія, розділ, стан образу                           OTA-1
ota check                    - поточна версія + stable/beta на сервері               OTA-2
ota update                   - встановити stable                                     OTA-3
ota update beta              - встановити beta                                       OTA-3
ota install <ver>            - встановити конкретну версію, напр. ota install 1.4.0  OTA-4
ota install <ver> force      - дозволити даунгрейд / перевстановлення                OTA-4
ota broken                   - встановити зламану прошивку (перевірка rollback)      OTA-10
ota <url>                    - OTA з власного посилання                              OTA-12
ota-test-server              - симуляція OTA без прошивання                          OTA-12
```

**Smart Lamp**

```
lamp on                      - увімкнути                                             FR-L1
lamp off                     - вимкнути                                              FR-L1
lamp status                  - стан у JSON                                           FR-L8
lamp color red               - колір за назвою: red green blue white                 FR-L2, FR-L4
                               yellow purple cyan
lamp color 255 0 128         - довільний колір r g b, кожне 0-255                    FR-L3
lamp brightness 30           - яскравість 0-100 %                                    FR-L5
lamp mode solid              - постійне світло                                       FR-L6
lamp mode blink              - блимання 1 Гц                                         FR-L6
lamp mode breathe            - плавна пульсація                                      FR-L6
lamp mode rainbow            - веселка (з 1.5.0)                                     FR-L6
lamp timer 5                 - автовимкнення через 5 с (1-3600)                      FR-L7
lamp timer 0                 - скасувати таймер                                      FR-L7
lamp scene save 1            - зберегти сцену 1-3 (з 1.5.0)                          FR-L10
lamp scene load 1            - застосувати сцену 1-3 (з 1.5.0)                       FR-L10
```

Приклади некоректного вводу і очікувані відповіді:

```
lamp color 300 0 0           -> error: rgb values must be 0-255
lamp color orange            -> error: unknown color 'orange'
lamp brightness 150          -> error: brightness must be 0-100
lamp brightness -5           -> error: brightness must be 0-100
lamp mode disco              -> error: unknown mode 'disco'
lamp mode rainbow            -> error: mode 'rainbow' not implemented yet   (тільки 1.3.0 і 1.4.0)
lamp timer 5000              -> error: timer must be 1-3600 s (0 = cancel)
lamp timer 5  (лампа вимк.)  -> error: lamp is off
lamp scene save 1            -> error: scenes not implemented yet           (тільки 1.3.0 і 1.4.0)
lamp scene save 7            -> error: scene must be 1-3                    (1.5.0)
lamp scene load 2 (порожня)  -> error: scene 2 is empty                     (1.5.0)
lamp blabla                  -> error: unknown lamp command. See 'help'
```

**Датчики, реле, LED, система**

```
distance                     - вимірювання безперервно, Enter - стоп                 розділ 6
distance 10                  - вимірювання 10 с (distance <N> - N секунд)            розділ 6
relay on / relay off         - реле                                                  розділ 6
led on / led off / led auto  - світлодіод вручну / авторежим (Wi-Fi індикація)       розділ 6, FR-W6
led rgb                      - кольоровий цикл 5 с                                   розділ 6
sysinfo                      - інформація про систему                                розділ 6
temp                         - температура чипа                                      розділ 6
sensor status                - стан усіх датчиків                                    розділ 6
reboot                       - перезавантаження                                      розділ 6
help                         - список команд
```

**Кнопки:** K1 - distance 10 с, K2 - реле, K3 - Wi-Fi disconnect/reconnect (FR-W5), K4 - діод.

---

## 1. Версії та канали оновлень

| Версія | Канал | Що в ній |
|---|---|---|
| 1.3.0 | old | Перший реліз Smart Lamp: on/off, кольори, яскравість, режими solid/blink/breathe, таймер |
| 1.4.0 | stable | Виправлення помилок 1.3.0, захист від даунгрейду |
| 1.5.0 | beta | Нове: сцени (`lamp scene`), режим `rainbow` |

- У 1.3.0 і 1.4.0 сцени і режим `rainbow` **ще не реалізовані** (заплановані на 1.5.0). Команди відповідають `error: scenes not implemented yet` і `error: mode 'rainbow' not implemented yet` - це очікувана поведінка.
- Кожна наступна версія має містити весь функціонал попередньої і працювати не гірше.

Сервер оновлень - публічний GitHub-репозиторій, пристрій качає файли по HTTPS (сертифікат перевіряється):

```
https://raw.githubusercontent.com/BohdanHorbanych/esp32-ota-files/main/firmware/
    stable.txt              - номер поточної stable-версії
    beta.txt                - номер поточної beta-версії
    v<версія>/station_WiFi.bin
    broken/station_WiFi.bin - навмисно зламана прошивка для перевірки rollback
```

---

## 2. Розмітка flash і механіка OTA

| Розділ | Адреса | Розмір | Призначення |
|---|---|---|---|
| nvs | 0x9000 | 16 KB | налаштування (Wi-Fi, лампа, сцени) |
| otadata | 0xd000 | 8 KB | яка з OTA-частин активна, стан образу |
| ota_0 | 0x10000 | 960 KB | прошивка A |
| ota_1 | 0x100000 | 960 KB | прошивка B |

- Нова прошивка завжди пишеться в **неактивний** розділ (працюємо з `ota_0` - пишемо в `ota_1`, і навпаки). Поточна прошивка під час завантаження не зачіпається.
- Після успішного завантаження пристрій перезавантажується в новий розділ. Новий образ стартує в стані `PENDING_VERIFY` і проходить self-check. Якщо self-check пройдено, образ позначається `valid`. Якщо ні - пристрій сам повертається на попередню прошивку (rollback).
- Якщо пристрій перезавантажився, а новий образ не встиг підтвердити себе, bootloader теж відкочує на попередній.

---

## 3. Wi-Fi

**FR-W1. Підключення.** `connect` - scan, список мереж з RSSI, запит `Enter SSID or number from list:` (можна ввести назву або номер зі списку), запит пароля.
- Пароль коротший за 8 символів - `password too short (min 8 chars)`, підключення не починається.
- Успіх - `got ip:<IP>` і `successfully connected to SSID:<SSID>`.
- Неправильний пароль / мережі немає - `failed to connect to SSID:<SSID>` або `connection timeout` (до 10 с).

**FR-W2. Збереження.** Після успішного підключення SSID і пароль зберігаються в NVS. Автопідключення при старті немає - у boot log `saved credentials found but auto-connect disabled`. `connect` з порожнім вводом (Enter) підключається до збереженої мережі.

**FR-W3. Налаштування переживають reboot і OTA-оновлення** (див. OTA-8).

**FR-W4.** `disconnect` - відключення, `status` - `WiFi: connected` + SSID, IP, RSSI або `WiFi: disconnected`, `scan` - список мереж з RSSI і каналом.

**FR-W5. Кнопка K3** - якщо підключено: відключитись; якщо ні: підключитись до збереженої мережі (`[K3] wifi reconnect (saved credentials)`), якщо збереженої немає - `no saved credentials, use 'connect' first`. K3 працює завжди, в тому числі під час OTA-завантаження.

**FR-W6. Індикація.** Коли лампа вимкнена і LED в авторежимі: тьмяний зелений - Wi-Fi підключено, тьмяний червоний - не підключено.

---

## 4. Smart Lamp

Лампа - це вбудований RGB-світлодіод. Коли лампа увімкнена, вона повністю керує світлодіодом (Wi-Fi індикація і команди `led ...` на нього не впливають). Коли лампа вимикається, світлодіод повертається до Wi-Fi індикації (FR-W6).

**FR-L1. `lamp on` / `lamp off`** - `[LAMP] on` / `[LAMP] off`. Після reboot лампа завжди вимкнена.

**FR-L2. `lamp color <name>`** - `red` (255,0,0), `green` (0,255,0), `blue` (0,0,255), `white` (255,255,255), `yellow` (255,180,0), `purple` (160,0,255), `cyan` (0,255,255). Відповідь `[LAMP] color set: <name> (r,g,b)`. Невідома назва - `error: unknown color '<name>'`.

**FR-L3. `lamp color <r> <g> <b>`** - довільний колір, кожне значення 0-255. Відповідь `[LAMP] color set: (r,g,b)`. Поза діапазоном - `error: rgb values must be 0-255`, колір не змінюється.

**FR-L4. Фізичний колір світлодіода має відповідати заданому** (red світить червоним, green - зеленим і т.д.).

**FR-L5. `lamp brightness <0-100>`** - яскравість у відсотках, `[LAMP] brightness set: N%`. Поза діапазоном - `error: brightness must be 0-100`, значення не змінюється. Яскравість застосовується **в усіх режимах**.

**FR-L6. `lamp mode <mode>`** - `[LAMP] mode set: <mode>`, невідомий режим - `error: unknown mode '<mode>'`.
- `solid` - постійне світло
- `blink` - блимання 1 Гц (0.5 с світить / 0.5 с не світить) із заданою яскравістю
- `breathe` - плавна пульсація (період ~3 с), максимум - задана яскравість
- `rainbow` (з 1.5.0) - плавна зміна кольору по колу (~5 с на коло) із заданою яскравістю

**FR-L7. `lamp timer <1-3600>`** - автовимкнення через N секунд, `[LAMP] auto-off in N s`. `lamp timer 0` - скасувати (`[LAMP] timer cancelled`). Поза діапазоном - `error: timer must be 1-3600 s (0 = cancel)`. Якщо лампа вимкнена - `error: lamp is off`. Коли час вийшов: `[LAMP] timer expired, lamp off`, лампа **фізично гасне**, світлодіод повертається до Wi-Fi індикації, `lamp status` показує `off`. Таймер не зберігається після reboot.

**FR-L8. `lamp status`** - один рядок JSON:

```
{"lamp":"on","color":[255,0,0],"brightness":50,"mode":"solid","timer_s":0}
```

`timer_s` - скільки секунд залишилось до автовимкнення (0 - таймера немає). Стан у JSON має відповідати тому, що фізично робить світлодіод.

**FR-L9. Збереження налаштувань.** Колір, яскравість і режим зберігаються в NVS одразу після зміни і відновлюються після reboot і після OTA-оновлення. За замовчуванням (чистий пристрій): white, 50%, solid.

**FR-L10. Сцени (з 1.5.0).** `lamp scene save <1-3>` - зберегти поточні колір + яскравість + режим (`[LAMP] scene N saved`). `lamp scene load <1-3>` - застосувати збережене (`[LAMP] scene N loaded`). Порожня сцена - `error: scene N is empty`. Номер поза 1-3 - `error: scene must be 1-3`. Сцени зберігаються в NVS і переживають reboot і OTA.

**FR-L11.** Будь-яка інша `lamp ...` команда - `error: unknown lamp command. See 'help'`.

---

## 5. OTA

**OTA-1. `version`** - `FW: v<версія> (build <дата>)` і `partition: <ota_0|ota_1> @ <адреса>, state: <valid|pending verify|...>`. Версія в `version`, у boot log (`App version`) і в `ota check` має збігатися.

**OTA-2. `ota check`** - читає канали з сервера:

```
[OTA] current version: 1.3.0
[OTA] stable channel:  1.4.0
[OTA] beta channel:    1.5.0
[OTA] update available. Type 'ota update'     (або: up to date (stable))
```

**OTA-3. `ota update`** - встановити поточну stable. Якщо вже стоїть ця версія - `[OTA] already up to date`, нічого не качається. `ota update beta` - те саме для beta-каналу.

**OTA-4. `ota install <ver>`** - встановити конкретну версію (напр. `ota install 1.4.0`). Установка старішої версії без `force` блокується: `[OTA] downgrade blocked: <cur> -> <new>. Use 'ota install <ver> force'`, прошивка не змінюється. `ota install <ver> force` - дозволяє даунгрейд і перевстановлення тієї ж версії.

**OTA-5. Процес.** Лог: `current version`, `target partition`, `downloading: <url>`, `new version`, прогрес кожні 10% (`[OTA] progress: 30% (275456 / 908320 bytes)`), `[OTA] success: <old> -> <new> in N s. Rebooting...`. Під час завантаження консоль зайнята, кнопки працюють.

**OTA-6. Втрата Wi-Fi під час завантаження.** `[OTA] failed: download interrupted (...)`. Пристрій залишається на поточній версії і працює. Після відновлення Wi-Fi **наступна спроба OTA працює одразу**, без перезавантаження пристрою.

**OTA-7. Без Wi-Fi** - будь-яка OTA команда: `[OTA] failed: WiFi not connected. Use 'connect' first.`

**OTA-8. Збереження даних.** Після будь-якого успішного OTA-оновлення (up або down) залишаються: збережена Wi-Fi мережа, налаштування лампи (колір, яскравість, режим), сцени. Оновлення не повинно вимагати повторного налаштування пристрою.

**OTA-9. Self-check і підтвердження.** Після reboot у новий образ: `[OTA] new firmware, state PENDING_VERIFY - running self-check...` -> `[OTA] self-check passed, firmware marked VALID`. `version` показує новий розділ і `state: valid`.

**OTA-10. Rollback.** `ota broken` - завантажує навмисно зламану прошивку. Після reboot: `self-check FAILED`, `rolling back to previous firmware...`, пристрій сам перезавантажується в попередню версію. `version` - попередня версія і розділ, `state: valid`. Всі налаштування на місці.

**OTA-11. Пошкоджений образ** (не ESP32 прошивка або обірваний файл) - `[OTA] failed: invalid image header` або `image validation failed (corrupted image)`, пристрій залишається на поточній версії.

**OTA-12. `ota <url>`** - OTA з довільного http/https посилання (для власного сервера). `ota-test-server` - стара симуляція OTA без завантаження (нічого не прошиває, лише демонструє лог і перезавантажує пристрій).

---

## 6. Інші команди

| Команда | Поведінка |
|---|---|
| `help` | список команд |
| `distance` | вимірювання HC-SR04 кожні 0.5 с, Enter - стоп. `distance <N>` - N секунд. Немає об'єкта - `sensor timeout` |
| `relay on` / `relay off` | реле (GPIO8), `relay ON` / `relay OFF` |
| `led on` / `led off` | білий / вимкнений світлодіод (ручний режим, Wi-Fi індикація не працює) |
| `led auto` | світлодіод знову показує стан Wi-Fi |
| `led rgb` | плавна зміна кольорів 5 с, потім авторежим |
| `sysinfo` | чип, ядра, частота, flash, вільна пам'ять, uptime, температура |
| `temp` | температура чипа |
| `sensor status` | відстань, реле, режим LED, Wi-Fi, температура |
| `reboot` | відлік 3-2-1 і перезавантаження |

Кнопки: K1 (GPIO41) - distance 10 с, K2 (GPIO40) - реле toggle, K3 (GPIO39) - Wi-Fi disconnect/reconnect (FR-W5), K4 (GPIO38) - діод (GPIO4) toggle.

Невідома команда - `unknown command, type 'help' for available commands`.
