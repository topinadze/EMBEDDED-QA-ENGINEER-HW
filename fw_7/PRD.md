# PRD: SENTRY SWM-2 - модуль гідроакустичної вахти (fw_7)

## 0. Що це за пристрій

**SENTRY SWM-2 (Sonar Watch Module)** - оновлений модуль носової гідроакустичної станції дизель-електричного підводного човна. Модуль ставиться в сонарний відсік №2 і закриває чотири задачі:

- **активний сонар ближньої зони** - ping/echo-контакти на малій дистанції: стиковка, підхід водолазів і підводних апаратів, загроза зіткнення
- **вахта периметра** (з 2.3.0) - охорона зони навколо корпусу на якірній стоянці або при лежанні на ґрунті: незнайомий контакт -> INTRUSION -> GENERAL ALARM
- **керування виконавчими пристроями** - баластно-дифферентний клапан (trim valve) і сигнальний вогонь (beacon)
- **телеметрія для CIC** (бойового інформаційного центру): стан модуля, глибина, тиск на корпус, вода, батарейна шина, зв'язок

Зв'язок з берегом і флотом - через **антену-буй** (Wi-Fi 2.4 GHz), оновлення прошивки - OTA через буй.

Модуль іде на навчальний стенд. Лабораторна збірка - ESP32-S3 DevKit, на якому моделюються вузли модуля:

- HC-SR04 (TRIG 5 / ECHO 18) - **гідроакустичний трансдюсер 40 kHz** (активний сонар)
- реле (GPIO8) + діод (GPIO4) - **соленоїд клапана** і індикатор (на реальному човні - trim valve)
- вбудований RGB LED (GPIO48) - **сигнальний вогонь / індикатор стану модуля**
- кнопки K1-K4 (GPIO41, 40, 39, 38) - **панель вахтового оператора**
- датчики глибини, тиску і батареї на стенді відсутні - модуль працює з **симулятором носія** (`[NAV] depth sensor offline (lab mode) - using simulator`). Значення глибини, тиску, води, батареї і шуму моря в логах - модельні, на логіку модуля не впливають

Повідомлення фонової телеметрії (`[NAV]`, `[ACU]`, `[PWR]`, `[HW]`, `[LINK]`), у т.ч. попередження (`W` без коду - напр. biologics detected, ripple, thermocline), - інформаційні, не є помилками модуля і не баги.

Команди мають тематичні аліаси (ліве і праве - одне й те саме):

```
sonar ...      = distance ...
beacon ...     = lamp ...
valve ...      = relay ...      (valve open = relay on, valve close = relay off)
telemetry ...  = health ...
watch ...      = guard ...      (з 2.3.0)
cic ...        = alert ...      (з 2.3.0)
```

Відповідність назв у логах: `[SONAR]` - датчик відстані, `[VALVE]` - реле (OPEN = увімкнено, closed = вимкнено), `[BEACON]` - лампа, `[TELEMETRY]` - health, `[WATCH]` - Guard, `[CIC #id ...]` - alerts, `[LINK]` - Wi-Fi, `[AUTH]` - акаунт, `[COLLISION]` - контакт ближче 20 см.

Керування - UART-консоль 115200 8N1, команда + Enter. Усі повідомлення йдуть у лог з тегом `sentry`. Помилки мають код: `E<код>` - помилка, `W<код>` - попередження.

Цей документ - джерело очікуваної поведінки. Все, що поводиться не так, як тут написано, - баг.

---

## 1. Версії та OTA-сервер

- 2.1.0 - канал stable. Усе, крім Guard і Alert center
- 2.3.0 - канал beta. Нове: SENTRY Guard, Alert center, кнопка K4. Виправлення помилок 2.1.0

У 2.1.0 команди `guard ...`, `alert ...` і кнопка K4 відповідають `E099 ... planned in v2.3.0` - це очікувана поведінка, не баг. Кожна наступна версія має містити весь функціонал попередньої і працювати не гірше.

Сервер за замовчуванням (GitHub, HTTPS):

```
https://raw.githubusercontent.com/BohdanHorbanych/esp32-ota-files/main/fw7/
    stable.txt, beta.txt          - номер версії каналу
    v<X.Y.Z>/sentry_fw7.bin       - прошивка
    broken/sentry_fw7.bin         - навмисно зламана прошивка (перевірка rollback)
```

Можна підняти такий самий сервер у себе на комп'ютері - `tools/ota_server.py` (див. `tools/README.md`) і переключити пристрій командою `ota server`.

Розмітка flash: nvs 0x9000 (налаштування), otadata 0xf000, ota_0 0x20000 і ota_1 0x1A0000 по 1.5 MB.

---

## 2. Доступ і стани

**AC-1. Рівні доступу.** Кожна команда має позначку в `help`: без позначки - доступна завжди, `[wifi]` - потрібен Wi-Fi (інакше E002), `[login]` - Wi-Fi + вхід (інакше E003), `[debug]` - debug-доступ (інакше E004).

**AC-2. Невідома команда** - `E001 unknown command '<x>'. Type 'help'`. Регістр першого слова не важливий. Нелатинські символи ігноруються з W006.

**ST-1. Стани системи** (`state`, `state <1-4|name>`, [login]):
- 1 NORMAL (patrol) - звичайна вахта
- 2 DEBUG (maintenance) - сирі дані датчика (без фільтра і калібрування), діагностика парсера (`[DBG] ...`), LED показує blink-коди
- 3 VERBOSE (tactical) - додаткові логи (`[V] ...`), health кожні 10 с, LED heartbeat, підказка `Did you mean '<cmd>'?` для невідомих команд
- 4 EMERGENCY - аварійне спливання, модуль заблокований (у телеметрії глибина зменшується)

**ST-2. EMERGENCY** можна увімкнути тільки з 3 VERBOSE. З будь-якого іншого стану - `E302 EMERGENCY can be entered only from 3 VERBOSE (now N NAME)`, стан не змінюється. Це правило однакове для команди і кнопок.

**ST-3. В EMERGENCY** дозволені тільки: `help`, `status`, `whoami`, `version`, `health now`, `alert list` (з 2.3.0), `reboot`. Будь-яка інша команда - E005 / E001 і температура драйвера трансдюсера росте. При 95 C - аварійний reboot. Вийти з EMERGENCY - тільки reboot (`E304`). Кнопки в EMERGENCY - `E005 buttons blocked in EMERGENCY`.

**ST-4.** Повторний перехід у поточний стан - `W303 already in N NAME`. `logout` повертає DEBUG / VERBOSE у NORMAL. Після reboot - завжди NORMAL.

---

## 3. Wi-Fi

**WF-1. `connect`** (підняти буй і підключитись) - scan, список мереж, ввід SSID (назва або номер), ввід пароля. Пароль коротший за 8 символів - E112, порожній SSID - E111. Успіх - `got ip`, `connected to '<ssid>', rssi N dBm`, перевірка інтернету, синхронізація часу (NTP). Мережа зберігається в NVS.

**WF-2. Помилки підключення:** E101 неправильний пароль, E102 мережу не знайдено, E103 непідтримуване шифрування, E104 немає IP (DHCP), E105 немає інтернету, W106 NTP не вдалось, W107 слабкий сигнал (< -80 dBm), E108 інша причина.

**WF-3.** `reconnect` - підключитись до збереженої мережі (немає - E113, вже підключено - W114). `forget` - стерти збережену мережу. `disconnect` - відключитись (W115 якщо не підключено). Автопідключення при старті немає: у boot log `known network '<ssid>'. Type 'reconnect'`.

**WF-4.** `scan` - список мереж з RSSI. `net` - IP, gateway, DNS, MAC. `ping [host]` - 8.8.8.8 за замовчуванням. `time` - поточний час (E121 якщо не синхронізовано).

**WF-5.** При втраті з'єднання - `W110 wifi connection lost`, 3 автоматичні спроби перепідключення.

---

## 4. Акаунт

**AU-1. `register <login> <pass>`** [wifi] - один профіль на пристрій (повторно - E202). Login 3-16 символів `a-z A-Z 0-9 _` (E204), пароль 6-32 (E205), login `debug` зарезервований (E203). Профіль зберігається в NVS і переживає reboot і OTA.

**AU-2. `login <login> <pass>`** [wifi]. Неправильні дані - `E209 wrong login or password. Attempts: N/3`. Після 3 невдалих спроб - `E210 too many attempts, account locked for 30 s`, далі `E207 account locked. Try again in N s`. Обмеження спроб діє на **будь-який** login, який вводиться в `login`. Вже увійшли - E206.

**AU-3. `logout`** - завершити сесію: вимикається лампа, реле, зупиняються виміри; стан DEBUG / VERBOSE -> NORMAL. Без сесії - W211.

**AU-4. `whoami`** - `user: <login>, access: user|debug`. Поле access показує поточний рівень доступу (після успішного `sudo` - `debug`).

**AU-5. `passwd <old> <new>`** [login] - змінює пароль профілю **назавжди** (NVS): новий пароль працює після logout, reboot і OTA, старий - більше ні. Неправильний старий - E215, новий 6-32 символи (E205).

**AU-6. `sudo <password>`** [login] - підняти поточного користувача до debug-доступу. Неправильний пароль - E213, вже debug - W212. Пароль sudo в цьому документі не наводиться.

---

## 5. OTA

**OTA-1. `version`** - `SENTRY SWM-2 sonar watch module, fw v<версія> (build <дата>)`, `partition: ota_N @ <адреса>, state: valid`. Версія однакова у `version`, boot log і `ota`.

**OTA-2. `ota` / `ota status`** - поточна прошивка і розділ, попередня прошивка в іншому розділі.

**OTA-3. `ota check`** - поточна версія, stable і beta з сервера, `update available` / `up to date (stable)` / `running newer than stable`.

**OTA-4. `ota update`** - встановити stable, `ota update beta` - beta. Якщо вже стоїть ця версія - `[OTA] already up to date`, нічого не качається і пристрій не перезавантажується.

**OTA-5. `ota install <X.Y.Z>`** - конкретна версія. Неправильний формат - E414, немає на сервері - E415. Старіша версія без `force` - `E408 downgrade blocked: vA -> vB. Use 'ota install B force'`, прошивка не змінюється. З `force` - дозволено (а також перевстановлення тієї ж версії з W409).

**OTA-6. Процес:** `current vA (ota_N) -> target partition ota_M`, `downloading <url>`, `image: sentry_fw7 vB`, прогрес кожні 10%, `success: vA -> vB in N s. Rebooting...`. Нова прошивка пишеться в неактивний розділ.

**OTA-7. Self-check.** Після reboot: `new firmware, PENDING_VERIFY - self-check...` -> `self-check passed, firmware marked VALID`.

**OTA-8. Rollback.** `ota broken` - встановити навмисно зламану прошивку: після reboot `self-check FAILED ... Rolling back...`, пристрій сам повертається на попередню версію, `version` - попередня версія, state valid. `ota rollback` - вручну завантажити прошивку з іншого розділу (немає - E416, вона invalid - E417).

**OTA-9. Помилки:** E401 оновлення вже йде, E402 сервер недоступний, E403 канал не читається, E405 завантаження не почалось, E406 файл не є прошивкою, E407 прошивка іншого проєкту, E410 обрив завантаження, E411 немає інтернету, E412 пошкоджений образ. Після будь-якої помилки пристрій лишається на поточній версії і працює, наступна спроба OTA працює одразу.

**OTA-10. Збереження даних.** Після будь-якого OTA (up / down / rollback) зберігаються: Wi-Fi мережа, профіль і пароль, налаштування лампи і сцени, лічильник і auto реле, калібрування / alarm / фільтр датчика, налаштування health, PIN і зона Guard.

**OTA-11. `ota url <url> [force]`** - встановити образ з довільного http/https посилання (не http/https - E418).

**OTA-12. `ota server [<url>|default]`** - показати / змінити сервер оновлень. `ota server http://192.168.1.10:8000/fw7/` - всі `ota check / update / install / broken` йдуть на цей сервер. Сервер зберігається в NVS (у boot log `custom update server: ...`). `ota server default` - повернути GitHub.

---

## 6. Сигнальний вогонь - Smart Lamp (вбудований RGB LED, кнопка K1)

**LM-1. `lamp on|off|toggle`** [login]. Повторне on / off - W510. Після reboot і logout лампа вимкнена.

**LM-2. `lamp color <name>`** - white, red, green, blue, yellow, purple, cyan, orange. `lamp color R G B` - кожне 0-255 (E502). Невідомий колір - E503.

**LM-3. `lamp brightness <0-100>`** - % (E504 поза діапазоном).

**LM-4. `lamp mode solid|blink|breathe|rainbow`** (E505). Яскравість діє в усіх режимах.

**LM-5. `lamp timer <1-3600>`** - автовимкнення, `[BEACON] auto-off in N s` (одиниця - секунди). `lamp timer 0` - скасувати. Поза діапазоном - E506, лампа вимкнена - E507. `lamp status` показує `timer N s left`.

**LM-6. `lamp scene save|load <1-3>`** - зберегти / застосувати колір + яскравість + режим (E508 номер, E509 порожня сцена).

**LM-7. `lamp status`** - `ON|off, color (r,g,b), brightness N%, mode <m>, timer ...`. Колір, яскравість, режим і сцени зберігаються в NVS.

**LM-8. LED.** Коли лампа вимкнена, LED показує стан системи. Пріоритет: EMERGENCY > Guard ALARM > OTA (синій блимає) > помилка датчика (червоний 2 с) > Guard INTRUSION / ARMING > лампа > індикація стану.

---

## 7. Клапан - реле (GPIO8 + діод GPIO4, кнопка K2)

**RL-1. `relay on|off|toggle`** [login]. Діод світить, коли реле увімкнене. Повторне on / off - W601. Не більше 2 перемикань за секунду (E602).

**RL-2. `relay status`** - стан, auto, `cycles N` - кількість перемикань за весь час (одне перемикання on або off = +1). Лічильник зберігається в NVS.

**RL-3. `relay pulse <100-10000>`** - увімкнути на N мс і вимкнути. Поза діапазоном (у т.ч. менше 100) - `E603 pulse must be 100-10000 ms`. Реле вже увімкнене - E604.

**RL-4. `relay schedule <on> <off>`** - цикл увімкнено / вимкнено по 2-3600 с (E606), `relay schedule off` - стоп (W605 якщо не запущено).

**RL-5. `relay auto on|off`** - вмикати реле, коли датчик перетинає поріг alarm.

**RL-6. `relay health`** - знос контактів (ресурс 100000 перемикань) і стан котушки.

**RL-7.** `logout` вимикає реле, імпульс і розклад (крім Guard ALARM).

---

## 8. Активний сонар - HC-SR04 (кнопка K3)

**DS-1. `distance`** [login] - один вимір. `distance <N>` - N вимірів (**1-20 включно**) і середнє. Поза діапазоном - E704.

**DS-2. `distance log [100-5000]`** - безперервні виміри з інтервалом, мс (E705), `distance stop` - стоп (W710). Поки йдуть виміри, інші `distance ...` - E711.

**DS-3. `distance calibrate <5-300>`** - покласти об'єкт на відому відстань, прошивка рахує поправку (offset). `distance calibrate reset` - скинути. Помилки E706, E707.

**DS-4. `distance alarm <5-300>|off`** - поріг: `[SONAR] PROXIMITY ALARM: contact at X cm`, `[SONAR] proximity alarm cleared` (з гістерезисом 5 см). E708.

**DS-5. `distance filter on|off`** - медіана з 5 вимірів (за замовчуванням on). `distance stats` - кількість, помилки, min / max / avg. `distance history` - останні 10.

**DS-6.** Об'єкт ближче 20 см - `[COLLISION] contact too close: X cm` (один раз на наближення, знову - після віддалення > 25 см). Немає ехо - E701, поза діапазоном - E702 (LED червоний 2 с).

**DS-7. Індикатор наближення.** Якщо клапан відкритий (реле увімкнене) і йдуть виміри - діод блимає тим частіше, чим ближче об'єкт, < 10 см - світить постійно.

---

## 9. Телеметрія (health)

**HL-1.** Після Wi-Fi + login - автоматичний звіт кожні 30 с (налаштовується), у VERBOSE - 10 с, в EMERGENCY - 5 с:

```
[TELEMETRY #N] <час> up <uptime> heap <KB> rssi <dBm> temp <C> depth <m> hull <bar> batt <V> valve open|closed sonar <cm|-> state <STATE> [WARN ...]
```
З 2.3.0 у рядку також `watch <стан> alerts <неп. alerts>`. depth / hull / batt - з симулятора носія.

**HL-2. Попередження:** low heap, weak signal, no internet, sensor error, overheat, guard alarm (2.3.0).

**HL-3.** `health` - поточні налаштування, `health now` - звіт зараз, `health on|off` (W901), `health interval <10-300>` - **10 і 300 включно** (E902 поза діапазоном). Налаштування в NVS.

---

## 10. Вахта периметра - SENTRY Guard (з 2.3.0, кнопка K4)

**GD-1. `guard arm`** - 10 с на вихід (`arming in N s`), потім `ARMED` - датчик перевіряє зону. `guard` / `guard status` - стан, зона, остання відстань.

**GD-2.** Об'єкт ближче зони (за замовчуванням 50 см, `guard zone <10-200>`, E808) - `INTRUSION`, 15 с на `guard disarm <pin>`, інакше `ALARM`.

**GD-3. ALARM** - також `guard panic`, утримання K4, 3 неправильні PIN, 3 виміри без ехо (tamper). ALARM: alert CRITICAL, реле ON, LED червоний / синій, нагадування кожні 10 с.

**GD-4. `guard disarm <pin>`** - зняти з охорони / зупинити ALARM (PIN за замовчуванням 1234). Неправильний PIN - `E803 wrong PIN. Attempts: N/3`, на 3-й - ALARM. Лічильник спроб **починається з нуля** при кожному `guard arm` і скидається після правильного PIN.

**GD-5.** `guard pin <old> <new>` - 4 цифри (E804), тільки коли охорона знята (E807). `guard log` - останні 10 подій. Logout охорону не знімає.

---

## 11. CIC alerts - Alert center (з 2.3.0)

**AL-1.** Останні 20 alerts з рівнями INFO / WARNING / CRITICAL. Джерела: watch, sonar, telemetry, state, selftest, test. Новий alert - `[CIC #id LEVEL] src: text`.

**AL-2. `alert` / `alert list`** - список, `*` - не підтверджений.

**AL-3. `alert ack`** - підтвердити останній непідтверджений. `alert ack <id>` - підтвердити **саме alert з цим id** (немає - E851, вже підтверджено - W852). `alert ack all` - всі (W853 якщо нема чого).

**AL-4. `alert clear`** - видалити список, тільки коли все підтверджено (E855). `alert test info|warning|critical` - тестовий alert (E854).

**AL-5.** CRITICAL (крім входу в EMERGENCY): реле ON і NORMAL / DEBUG -> VERBOSE.

---

## 12. Кнопки (потрібен login, інакше E003)

- K1: натиснути - лампа on/off, утримати 1.5 с - наступний колір
- K2: натиснути - реле on/off, утримати 1.5 с - імпульс 1 с
- K3: натиснути - виміри 30 с кожні 500 мс (ще раз - стоп)
- K4 (2.3.0): натиснути - підтвердити останній alert, утримати 1.5 с - PANIC
- Утримати 2 с пару: K1+K2 - 1 NORMAL, K2+K3 - 2 DEBUG, K3+K4 - 3 VERBOSE, K4+K1 - 4 EMERGENCY (тільки з 3, ST-2)

---

## 13. Система

- `help` - список команд (по групах, з позначками доступу)
- `status` - прошивка, стан, Wi-Fi, користувач, час, реле, guard (2.3.0), відстань, heap
- `sysinfo` - чип, flash, пам'ять, uptime, температура. `temp`, `uptime`
- `reboot` - відлік 3-2-1 і перезавантаження
- Boot log: версія, розділ, причина останнього reset (`last reset: power on|software reboot|PANIC|watchdog|brownout`)

У прошивці є приховані команди і можливості, яких немає в `help`. Знайти їх - частина дослідницького тестування.

