# HW-16: Звіт тестування OTA-оновлень Smart Lamp

> Заповнити лише за результатами фактичного тестування ESP32-S3. Не позначати перевірку `PASS` без спостереження очікуваної поведінки. Перед додаванням логів замінити пароль Wi-Fi на `***`.

## 1. Тестове оточення

| Поле | Значення |
|---|---|
| Тестер | `Турчаненко Антон` |
| Дата | `2026-10-09` |
| Плата | ESP32-S3, QFN56, revision v0.2; 8 MB embedded PSRAM (reported by esptool) |
| ОС / UART-термінал | `<значення>` |
| UART | 115200 8N1, COM4 |
| Wi-Fi | 2.4 GHz, `TopA-node` |
| Початкове прошивання | `station_WiFi_v1.3.0_merged.bin` за [`README.md`](../fw_6/README.md); запис підтверджено esptool v5.4.0, hash verified |
| Джерело очікуваної поведінки | [`PRD.md`](../fw_6/PRD.md) |

**Запис прошивання:** esptool під'єднався до ESP32-S3 на COM4, запустив stub flasher і змінив baud rate на 460800. Flash erase range: `0x00000000–0x000edfff`. Записано 973152 bytes (625254 compressed) за адресою `0x00000000`; hash перевірено. Виконано hard reset через RTS. Boot log після reset і підтвердження версії прошивки ще не зафіксовані.

**Перевірки консолі та Wi-Fi:** COM4 відкрито; команда `help` виконана на пристрої (uptime у виводі ~33.5 с), список команд збережено в [`logs/help-1.3.0.txt`](logs/help-1.3.0.txt). `connect` успішно під'єднався до `TopA-node` і отримав IP; пароль у [`logs/connect-1.3.0.txt`](logs/connect-1.3.0.txt) замінено на `***`. Пароль не включати до звіту чи логів.

**Автоматизація перевірки 1.3.0/1.4.0/1.5.0:** pytest-набір з групою `lamp`, незалежними тестами, UART DEBUG-виводом і прикріпленням повного логу до кожного результату Allure підготовлено у [`tests/test_lamp.py`](tests/test_lamp.py). UART-кроки драйвера позначені `@allure.step` і відображають відкриття/закриття з'єднання, надсилання команд, очікування відповіді, розбір стану/версії та прикріплення транскрипту. Напівмануальні перевірки покривають фізичне вмикання/вимикання та Wi-Fi-індикацію, кольори (названі й custom RGB), незмінність LED після відхилення значень, яскравість, режими, таймерне вимкнення і стан після reboot. Вони виключені зі звичайного запуску за замовчуванням і потребують `-s -m interactive`; результат і коментар додаються в Allure, запуск без `-s` зупиняється до відкриття UART. Матриця покриття L-01–L-17 нижче. Інструкції запуску — у [`README.md`](README.md).

**Автоматизований запуск на COM4, FW 1.3.0 (2026-10-11):** перший запуск виявив, що тестовий fixture помилково не допускав версію 1.3.0; після виправлення allowlist тест `lamp on/off` пройшов. Неперсистентний автоматичний набір: **30 passed, 3 failed, 1 skipped**. Усі три помилки — L-08 (`lamp brightness -5`, `101`, `150`): прошивка відповіла `[LAMP] brightness set: ...%` замість відхилення; це підтверджує вже зафіксований BUG-05, а не помилку тестового стенду. Окремий перевірочний запуск збереження/завантаження сцен для індексів 1–3: **3 passed**; FW 1.3.0 коректно відповіла `scenes not implemented yet`. Інші версії FW не перевірялися.

**Інтерактивний повтор L-01 на COM4, FW 1.3.0 (2026-10-11):** `test_lamp_on_off_visual` — **1 passed**. Перевірено фізичне світіння після `lamp on` і повернення Wi-Fi-індикації після `lamp off`; статус UART після команд відповідно `on` та `off`. Цей запуск не перевіряв Wi-Fi-індикацію при від'єднаній мережі, тому раніше зафіксоване відхилення BUG-01 залишається відкритим. Інші версії FW не перевірялися.

**Статуси:** `NOT RUN` — не перевірено; `PARTIAL` — перевірено лише частину зазначених кроків; `PASS` — відповідає PRD; `FAIL` — відхилення від PRD (вказати ID бага); `BLOCKED` — не вдалося перевірити (вказати причину).

## 2. Чек-лист Smart Lamp за версіями

Для кожної комірки вказати статус і, за потреби, ID бага та посилання на доказ (наприклад, `PASS — screenshots/1.3.0-red.jpg`). Для фізичних перевірок оцінювати світлодіод очима, не лише за UART-виводом.

| ID | Перевірка / очікуваний результат | PRD | 1.3.0 | 1.4.0 | 1.5.0 |
|---|---|---|---|---|---|
| L-01 | `lamp on`, `lamp off`; лампа фізично вмикається/гасне, після вимкнення відновлюється індикація Wi-Fi | FR-L1, FR-W6 | PARTIAL — інтерактивний повтор 2026-10-11 підтвердив фізичне світіння при `on` та повернення Wi-Fi-індикації після `off`. Індикація при від'єднаній мережі залишається FAIL (BUG-01): після `disconnect` LED лишався зеленим замість червоного; див. [`logs/disconnect-status-led-1.3.0.txt`](logs/disconnect-status-led-1.3.0.txt). | NOT RUN | NOT RUN |
| L-02 | `lamp status` повертає коректний JSON; стан і таймер відповідають фізичному стану | FR-L8 | FAIL — JSON показує задані RGB, але не фактичний колір LED як при переплутаних кольорах (BUG-03), так і після недопустимої яскравості (BUG-05); [`logs/lamp-colors-1.3.0.txt`](logs/lamp-colors-1.3.0.txt), [`logs/lamp-invalid-brightness-1.3.0.txt`](logs/lamp-invalid-brightness-1.3.0.txt) | NOT RUN | NOT RUN |
| L-03 | Перевірити кольори `red`, `green`, `blue`, `white`, `yellow`, `purple`, `cyan` — назва, RGB у відповіді та фізичний колір правильні | FR-L2, FR-L4 | FAIL — фізично переплутані red/green та purple/cyan; перезапуск лампи не виправляє. UART і спостереження: BUG-03, [`logs/lamp-colors-1.3.0.txt`](logs/lamp-colors-1.3.0.txt) | NOT RUN | NOT RUN |
| L-04 | `lamp color 255 0 128`; довільний RGB задано коректно | FR-L3, FR-L4 | PASS — команда та `lamp status` показали `[255,0,128]`; фізичний колір відповідає очікуваному. [`logs/lamp-rgb-custom-1.3.0.txt`](logs/lamp-rgb-custom-1.3.0.txt) | NOT RUN | NOT RUN |
| L-05 | Некоректний RGB відхилено з повідомленням про діапазон; попередній колір не змінився | FR-L3 | FAIL — `lamp color 300 0 0` один раз із трьох повернула `unknown command`; два повтори та інші перевірені значення повернули очікувану помилку, колір не змінився. BUG-04; [`logs/lamp-invalid-rgb-retest-1.3.0.txt`](logs/lamp-invalid-rgb-retest-1.3.0.txt) | NOT RUN | NOT RUN |
| L-06 | Невідомий колір `lamp color orange` відхилено, поточний колір не змінюється | FR-L2 | PASS — тричі отримано `error: unknown color 'orange'`; візуально колір лампи не змінився. [`logs/lamp-unknown-color-1.3.0.txt`](logs/lamp-unknown-color-1.3.0.txt), [`logs/lamp-visual-brightness-1.3.0.txt`](logs/lamp-visual-brightness-1.3.0.txt) | NOT RUN | NOT RUN |
| L-07 | Перевірити фізичні рівні яскравості `0`, `30`, `50`, `70`, `100` у режимі `solid` | FR-L5 | PASS — рівні яскравості перевірено фізично; команди прийняті пристроєм. [`logs/lamp-visual-brightness-1.3.0.txt`](logs/lamp-visual-brightness-1.3.0.txt) | NOT RUN | NOT RUN |
| L-08 | Значення яскравості поза діапазоном `0–100` відхиляються; параметри та фізичний колір лампи не змінюються | FR-L5 | FAIL — значення `-5`, `-50`, `110`, `120`, `130`, `150` і `200` прийняті; при недопустимій яскравості фізичний колір LED змінюється, хоча `lamp status` продовжує показувати заданий RGB. BUG-05; [`logs/lamp-invalid-brightness-1.3.0.txt`](logs/lamp-invalid-brightness-1.3.0.txt) | NOT RUN | NOT RUN |
| L-09 | Перевірити `solid`, `blink` (1 Гц) і `breathe` (~3 с); фізична поведінка та яскравість правильні | FR-L6, FR-L5 | PASS — режими `solid`, `blink`, `breathe` та фізичну поведінку/яскравість перевірено; відповідні команди й стани зафіксовані в [`logs/lamp-modes-1.3.0.txt`](logs/lamp-modes-1.3.0.txt) | NOT RUN | NOT RUN |
| L-10 | Невідомий режим відхиляється з повідомленням про невідомий режим | FR-L6 | PASS — `lamp mode blick` повернула `error: unknown mode 'blick'`. [`logs/lamp-modes-1.3.0.txt`](logs/lamp-modes-1.3.0.txt) | NOT RUN | NOT RUN |
| L-11 | `lamp mode rainbow`: очікуване `not implemented yet` у 1.3.0/1.4.0; плавне коло кольорів (~5 с) у 1.5.0 | FR-L6 | PASS — отримано очікуване `error: mode 'rainbow' not implemented yet`; поведінку у 1.4.0 і реалізацію rainbow у 1.5.0 ще не перевірено. [`logs/lamp-rainbow-1.3.0.txt`](logs/lamp-rainbow-1.3.0.txt) | NOT RUN | NOT RUN |
| L-12 | Таймер `lamp timer 10` вимикає лампу через 10 с; `lamp timer 0` скасовує таймер, `timer_s` показує залишок | FR-L7 | PASS — таймер вимкнув лампу через 10 с, `lamp status` показав `off`; перевірено скасування таймера і зворотний відлік `timer_s:7`. [`logs/lamp-timer-1.3.0.txt`](logs/lamp-timer-1.3.0.txt), [`logs/lamp-timer-validation-1.3.0.txt`](logs/lamp-timer-validation-1.3.0.txt) | NOT RUN | NOT RUN |
| L-13 | Таймер відхиляє `5000`; таймер на вимкненій лампі відхиляється з `lamp is off` | FR-L7 | PASS — на вимкненій лампі отримано `error: lamp is off`; `lamp timer 5000` повернула `error: timer must be 1-3600 s (0 = cancel)`. [`logs/lamp-timer-validation-1.3.0.txt`](logs/lamp-timer-validation-1.3.0.txt) | NOT RUN | NOT RUN |
| L-14 | `lamp scene save 1` / `lamp scene load 1`: очікуване `not implemented yet` у 1.3.0/1.4.0; збереження й застосування стану у 1.5.0 | FR-L10 | PASS — `lamp scene save 1` повернула очікуване `error: scenes not implemented yet`; перевірку `lamp scene load` та реалізацію сцен у 1.5.0 ще не виконано. [`logs/lamp-scenes-1.3.0.txt`](logs/lamp-scenes-1.3.0.txt) | NOT RUN | NOT RUN |
| L-15 | У 1.5.0 перевірити порожню сцену, номер `7`, сцени 1–3; очікувані повідомлення про помилку або успіх | FR-L10 | N/A | N/A | NOT RUN |
| L-16 | Перевірити збереження кольору, яскравості та режиму після reboot; лампа після reboot вимкнена | FR-L1, FR-L9 | PASS — після reboot лампа була `off`, збережені колір `[0,0,255]`, яскравість `50%` і режим `breathe`; після `lamp on` той самий стан відновився. Boot log також знайшов збережені Wi-Fi credentials, автопідключення не виконується згідно з FR-W2. [`logs/lamp-reboot-persistence-1.3.0.txt`](logs/lamp-reboot-persistence-1.3.0.txt) | NOT RUN | NOT RUN |
| L-17 | Будь-яка інша команда `lamp ...` відхиляється з підказкою `See 'help'` | FR-L11 | PASS — `lamp loremipsun` повернула `error: unknown lamp command. See 'help'`. [`logs/lamp-unknown-command-1.3.0.txt`](logs/lamp-unknown-command-1.3.0.txt) | NOT RUN | NOT RUN |
| L-18 | `help` показує команди Smart Lamp, OTA та кнопок | Довідник команд | PASS — [`logs/help-1.3.0.txt`](logs/help-1.3.0.txt) | NOT RUN | NOT RUN |

### Покриття L-01–L-17 автоматизацією

Не кожен тест має чекати на ручний ввід: автоматичні тести перевіряють команди, відповіді UART, JSON-стани, валідацію та збереження даних; напівмануальні потрібні там, де вимога стосується фактичного вигляду LED або фізичного вимкнення. Усі наведені нижче автотести зчитують і перевіряють версію пристрою; перевірки для 1.4.0/1.5.0 мають версійні гілки, де це потрібно.

| ID | Автоматизоване покриття | Фізична / напівмануальна перевірка | Висновок щодо покриття |
|---|---|---|---|
| L-01 | `test_lamp_on_off_and_status` | `test_lamp_on_off_visual` перевіряє світіння при `on` та Wi-Fi-індикацію (тьмяний зелений/червоний) після `off` | Повне; фізична перевірка інтерактивна |
| L-02 | `test_lamp_status_json_shape` та перевірки стану в інших тестах валідують JSON, поля й значення | Відповідність статусу фізичному LED перевіряється разом з L-03, L-04, L-07–L-09 | Повне комбіноване покриття основних полів; автоматизація не вимірює фізичний LED |
| L-03 | `test_named_color_rgb` перевіряє відповіді/RGB для семи назв | `test_named_color_visual` візуально перевіряє всі сім назв | Повне комбіноване покриття |
| L-04 | `test_custom_rgb` перевіряє команду та статус `(255,0,128)` | `test_custom_rgb_visual` просить візуально звірити pink/magenta-like результат | Повне комбіноване покриття для тестового RGB |
| L-05 | `test_invalid_rgb_is_rejected` перевіряє помилку та незмінність JSON-кольору | `test_invalid_rgb_visual` перевіряє незмінність фізичного зеленого LED після відхилення | Повне комбіноване покриття заданих невалідних значень |
| L-06 | `test_unknown_color_is_rejected` перевіряє помилку та незмінність JSON | `test_unknown_color_visual` перевіряє фізично незмінний жовтий LED після `orange` | Повне комбіноване покриття |
| L-07 | `test_valid_brightness` перевіряє 0/30/50/70/100 та статус | `test_brightness_visual` перевіряє ті самі рівні; перед виміром задається `solid` | Повне комбіноване покриття сприйняття рівнів; точна фотометрична точність потребує люксметра |
| L-08 | `test_invalid_brightness_is_rejected` перевіряє помилку та незмінність JSON | `test_invalid_brightness_visual` порівнює LED з фізичним baseline 50% до/після відхилення | Повне комбіноване покриття для -5/101/150; відповіді дозволять повторно виявити BUG-05 |
| L-09 | `test_supported_modes` перевіряє статус режимів; `test_valid_brightness` перевіряє рівні в JSON | `test_mode_visual` перевіряє solid, blink (~1 Гц) і breathe (~3 с) на вигляд і приблизний час | Повне для зазначених режимів; період оцінюється візуально |
| L-10 | `test_unknown_mode_is_rejected` перевіряє точну помилку | Ручна перевірка не потрібна | Повне автоматизоване покриття |
| L-11 | `test_rainbow_mode_by_version` перевіряє помилку на 1.4.0 та підтримку/status на 1.5.0 | `test_mode_visual[rainbow]` перевіряє цикл кольорів близько 5 с на 1.5.0; на 1.4.0 пропускається | Повне для версійних очікувань; тривалість оцінюється оператором |
| L-12 | `test_timer_auto_off` перевіряє 10-секундне спрацювання/status; `test_timer_cancel_and_remaining_time` — countdown та cancel | `test_timer_auto_off_visual` перевіряє фізичне згасання і повернення Wi-Fi-індикації | Повне комбіноване покриття |
| L-13 | `test_timer_validation` перевіряє вимкнену лампу та 5000 секунд | Ручна перевірка не потрібна | Повне автоматизоване покриття |
| L-14 | `test_scenes_by_version` перевіряє unsupported save/load на 1.4.0 та save/load на 1.5.0 | Ручна перевірка не потрібна | Повне для підтримки/збереження/завантаження сцен 1–3; тести позначені `persistent` і перезаписують слоти |
| L-15 | `test_scenes_by_version` перевіряє збереження/завантаження сцен 1–3; `test_invalid_scene_index` перевіряє індекс 7 | Ручна перевірка не потрібна для цих команд | Часткове: порожню сцену навмисно не припускаємо автоматично, бо її стан залежить від NVS. Передумову “слот порожній” можна гарантувати лише на чистому/підготовленому NVS; без безпечної процедури очищення тест не запускається |
| L-16 | `test_settings_survive_reboot` перевіряє колір/яскравість/режим та `lamp=off` після reboot | Той самий тест має інтерактивне підтвердження вимкнення лампи та повернення Wi-Fi-індикації | Повне комбіноване покриття; тест позначений `persistent` та `interactive` |
| L-17 | `test_unknown_lamp_command` перевіряє повідомлення `See 'help'` | Ручна перевірка не потрібна | Повне автоматизоване покриття |

`interactive`-перевірки запускаються окремо з `-s -m interactive`; звичайний запуск їх виключає. Матриця описує наявність тестів, а не результати прогонів: жоден з нових тестів ще не запускався на платах 1.4.0/1.5.0.

## 3. Чек-лист OTA та Wi-Fi

Зберігати повний UART-лог кожного переходу від команди оновлення до `self-check passed` у `logs/`. Для перерваних спроб зберегти також лог помилки та успішної повторної спроби. Звірити версію, розділ і стан образу командою `version`.

| ID | Перевірка / очікуваний результат | PRD | Версія / перехід | Результат / доказ |
|---|---|---|---|---|
| O-01 | На старті `version` показує 1.3.0; boot log, `version` та `ota check` узгоджені. `ota check` показує stable 1.4.0 і beta 1.5.0 | OTA-1, OTA-2 | 1.3.0 | PASS — `version` показала `FW: v1.3.0`, `ota_0`, `state: valid`; `ota check` після підключення показала current 1.3.0, stable 1.4.0 і beta 1.5.0. Boot log після початкового прошивання також показав App version 1.3.0. [`logs/ota-check-1.3.0.txt`](logs/ota-check-1.3.0.txt) |
| O-02 | `ota update`: 1.3.0 → 1.4.0; перевірити цільовий розділ, URL, прогрес, успіх, reboot, self-check і `state: valid` | OTA-3, OTA-5, OTA-9 | 1.3.0 → 1.4.0 | PASS — повний UART-лог підтверджує успішне завантаження stable 1.4.0 у `ota_1` з прогресом 10–100%, reboot, self-check passed, стан VALID і `version` 1.4.0 на `ota_1`. Перед успішним запуском була окрема невдала спроба через DNS, зафіксована в [`logs/ota-update-attempt-1.3.0-dns-failure.txt`](logs/ota-update-attempt-1.3.0-dns-failure.txt); вона не змінила поточну прошивку. [`logs/ota-update-1.3.0-to-1.4.0.txt`](logs/ota-update-1.3.0-to-1.4.0.txt) |
| O-03 | `ota update beta`: 1.4.0 → 1.5.0; перевірити цільовий розділ, URL, прогрес, успіх, reboot, self-check і `state: valid` | OTA-3, OTA-5, OTA-9 | 1.4.0 → 1.5.0 | PASS — beta 1.5.0 завантажено з прогресом 10–100% у `ota_0`; після reboot self-check пройшов, `version` підтвердила 1.5.0, `ota_0 @ 0x10000`, `state: valid`. [`logs/ota-update-beta-1.4.0-to-1.5.0.txt`](logs/ota-update-beta-1.4.0-to-1.5.0.txt) |
| O-04 | Після успішного OTA у кожному переході Wi-Fi підключається зі збереженими обліковими даними; колір, яскравість, режим і (у 1.5.0) сцени збережено | FR-W3, FR-L9, FR-L10, OTA-8 | 1.4.0 → 1.5.0 | FAIL — до OTA Wi-Fi був connected до TopA-node, лампа: blue `[0,0,255]`, brightness 42, breathe. Після OTA для Wi-Fi довелося повторно вибрати SSID та ввести пароль; `lamp status` повернув default white `[255,255,255]`, brightness 50, solid. Це порушує OTA-8/FR-W3/FR-L9. Див. BUG-07 та [`logs/ota-update-beta-1.4.0-to-1.5.0.txt`](logs/ota-update-beta-1.4.0-to-1.5.0.txt). |
| O-05 | На 1.3.0 перервати Wi-Fi під час `ota update`; отримати помилку завантаження, залишитися на 1.3.0, відновити Wi-Fi і повторити OTA без reboot | OTA-6 | 1.3.0 | FAIL — при обриві на 20% отримано очікуване `[OTA] failed: download interrupted (ESP_FAIL)`; автоматичне Wi-Fi reconnect відбулося, `version` підтвердила робочу 1.3.0 на `ota_0`. Але `ota status` і повторний `ota update` повернули `[OTA] error: update already in progress`, тобто повтор без reboot не стартував. Після ручного `reboot` система завантажилася на 1.3.0, `ota_0`, `state: valid`; повтор OTA після reboot у цьому логу не перевірявся. [`logs/ota-interruption-retry-1.3.0.txt`](logs/ota-interruption-retry-1.3.0.txt) |
| O-06 | На 1.4.0 перервати Wi-Fi під час `ota update beta`; отримати помилку завантаження, залишитися на 1.4.0, відновити Wi-Fi і повторити OTA без reboot | OTA-6 | 1.4.0 → 1.5.0 | PASS — перша спроба обірвалася на 30% з `[OTA] failed: download interrupted (ESP_FAIL)`; Wi-Fi автоматично перепідключився, пристрій залишився на 1.4.0 `ota_0`, `valid`, а lamp status лишився blue `[0,0,225]` / 50% / breathe. Повторна `ota update beta` без проміжного ручного reboot успішно завантажила 1.5.0 у `ota_1`; після OTA reboot self-check пройшов, firmware позначено VALID. [`logs/ota-interruption-retry-1.4.0.txt`](logs/ota-interruption-retry-1.4.0.txt) |
| O-07 | На 1.5.0 перевірити обрив і повторне підключення під час OTA, не змінюючи версію, наприклад `ota install 1.5.0 force`; після обриву повторна спроба працює без reboot | OTA-4, OTA-6 | 1.5.0 | FAIL — цільовий same-version сценарій виконано: `ota install 1.5.0 force` перервався на 20% з `[OTA] failed: download interrupted (ESP_FAIL)`. Автоматичні спроби Wi-Fi reconnect закінчилися `connect to the AP fail`; `version` перед retry підтвердила незмінну 1.5.0 у `ota_1`, `valid`. Retry без reboot повернув `[OTA] error: update already in progress`. Після retry окремого `version` не надано. Попередній force-downgrade прогін також показав той самий блокуючий стан. BUG-06. [`logs/ota-interruption-same-version-retry-1.5.0.txt`](logs/ota-interruption-same-version-retry-1.5.0.txt), [`logs/ota-interruption-force-downgrade-1.5.0.txt`](logs/ota-interruption-force-downgrade-1.5.0.txt) |
| O-08 | Без Wi-Fi OTA-команда повертає `WiFi not connected`; поточна прошивка не змінюється | OTA-7 | 1.3.0 | PASS — `ota check` без Wi-Fi повернула `[OTA] failed: WiFi not connected`; після підключення повторний `ota check` підтвердив current version 1.3.0 без оновлення. [`logs/ota-check-1.3.0.txt`](logs/ota-check-1.3.0.txt) |
| O-09 | На вже актуальному stable/beta-каналі OTA повідомляє `already up to date` і не завантажує образ | OTA-3 | актуальна версія каналу | PASS — на FW 1.4.0 `ota check` показала stable 1.4.0 і `[OTA] up to date (stable)`; див. [`logs/ota-downgrade-1.4.0-to-1.3.0.txt`](logs/ota-downgrade-1.4.0-to-1.3.0.txt) |
| O-10 | `ota install 1.3.0` без `force` блокує downgrade; версія/розділ не змінюються | OTA-4 | 1.4.0, 1.5.0 | PASS — на 1.4.0 downgrade 1.3.0 відхилено; на 1.5.0 без `force` відхилено переходи і до 1.4.0, і до 1.3.0. Після цього перевстановлення тієї ж 1.5.0 завершилося успішно; `version` після reboot підтвердила 1.5.0 у `ota_1`, `state: valid`. Останній same-version install — не downgrade. [`logs/ota-downgrade-1.4.0-to-1.3.0.txt`](logs/ota-downgrade-1.4.0-to-1.3.0.txt), [`logs/ota-downgrade-1.5.0-no-force.txt`](logs/ota-downgrade-1.5.0-no-force.txt) |
| O-11 | `ota install 1.3.0 force` дозволяє downgrade; після reboot перевірити 1.3.0, `state: valid` і збереження даних. Зафіксувати повторний OTA шлях назад до 1.5.0, якщо його виконували | OTA-4, OTA-8, OTA-9 | 1.4.0/1.5.0 → 1.3.0/1.4.0 | PASS — force-downgrade 1.4.0 → 1.3.0 і 1.5.0 → 1.4.0 виконані, у кожному випадку self-check пройшов і цільова версія стала `valid`. Для переходу 1.5.0 → 1.4.0 підтверджено Wi-Fi credentials збереженими (підключення зі збереженим SSID без повторного пароля) і lamp state white/50/solid незмінним. [`logs/ota-downgrade-1.4.0-to-1.3.0.txt`](logs/ota-downgrade-1.4.0-to-1.3.0.txt), [`logs/ota-downgrade-1.5.0-to-1.4.0-force.txt`](logs/ota-downgrade-1.5.0-to-1.4.0-force.txt) |
| O-12 | `ota broken`: self-check завершується помилкою, виконується rollback на попередню версію; версія, стан `valid` і налаштування підтверджені | OTA-10 | 1.3.0 → 1.9.0-broken → 1.3.0 | PASS — rollback від `1.9.0-broken` у `ota_1` після self-check failure підтверджено двома прогонами. Після кожного підтверджено 1.3.0 у `ota_0`, `state: valid`; у повторному прогоні також підтверджено lamp state: color `[0,0,255]`, brightness `42`, mode `breathe` (off). [`logs/ota-broken-rollback-1.3.0.txt`](logs/ota-broken-rollback-1.3.0.txt), [`logs/ota-broken-rollback-1.3.0-run2.txt`](logs/ota-broken-rollback-1.3.0-run2.txt) |
| O-13 | Перевірити помилку пошкодженого образу: завантаження/валідація відхиляється, поточна версія залишається робочою | OTA-11 | 1.3.0 | OUT OF SCOPE для HW-16 — явні кроки завдання вимагають перевірити OTA-переходи, обрив/reconnect, downgrade та `ota broken`; окремого тесту пошкодженого образу немає. Прогін `ota broken` зараховано до O-12, як вимагає HW-16. |
| O-14 | Перевірити `ota <url>` і `ota-test-server` відповідно до PRD; зафіксувати фактичний URL/результат без секретів | OTA-12 | `<версія>` | OUT OF SCOPE для HW-16 — custom URL і симуляція `ota-test-server` не вказані серед конкретних кроків завдання. |
| O-15 | `connect`: вибір мережі, введення пароля, успішне підключення й отримання IP | FR-W1 | 1.3.0 | PASS — [`logs/connect-1.3.0.txt`](logs/connect-1.3.0.txt) |
| O-16 | Після `disconnect`, `status` має показати disconnected; при вимкненій лампі LED має показувати тьмяно-червоний Wi-Fi статус | FR-W4, FR-W6 | 1.3.0 | FAIL — `status` показав connected з порожнім SSID, IP `0.0.0.0`, RSSI `0 dBm`; LED лишився тьмяно-зеленим. Повтор BUG-01 з DZ14; доказ: [`logs/disconnect-status-led-1.3.0.txt`](logs/disconnect-status-led-1.3.0.txt) |
| O-17 | K3 при підключеному Wi-Fi відключає пристрій; наступне натискання на відключеному пристрої запускає reconnect зі збереженими credentials | FR-W5 | 1.3.0 | FAIL — повторні натискання виводять `[K3] wifi disconnect` / `disconnected`; reconnect не запускається, `status` помилково показує connected без SSID та IP. BUG-02; [`logs/k3-reconnect-1.3.0.txt`](logs/k3-reconnect-1.3.0.txt) |
| K-01 | K4 перемикає діод, K2 вмикає/вимикає реле, K1 виконує вимірювання відстані протягом 10 секунд | PRD §6 (кнопки) | 1.3.0 | PASS — у логу зафіксовані обидва стани K4/K2 та виміри K1 від 10.2 см до `[K1] done`; [`logs/buttons-k1-k2-k4-1.3.0.txt`](logs/buttons-k1-k2-k4-1.3.0.txt) |

### Логи переходів

| Перехід / спроба | Файл у `logs/` | Версія до → після | Примітка |
|---|---|---|---|
| 1.3.0 → 1.4.0, успішна | [`ota-update-1.3.0-to-1.4.0.txt`](logs/ota-update-1.3.0-to-1.4.0.txt) | 1.3.0 → 1.4.0; `ota_0` → `ota_1`, `state: valid`, self-check passed | PASS |
| 1.4.0 → 1.5.0 beta, успішна OTA; settings persistence failure | [`ota-update-beta-1.4.0-to-1.5.0.txt`](logs/ota-update-beta-1.4.0-to-1.5.0.txt) | 1.4.0 `ota_1` → 1.5.0 `ota_0`, self-check passed; після оновлення повторно введено Wi-Fi password, lamp налаштування повернулися до white/50/solid | OTA PASS; OTA-8 FAIL (BUG-07) |
| 1.3.0 → 1.4.0, обрив Wi-Fi / reconnect | [`ota-interruption-retry-1.3.0.txt`](logs/ota-interruption-retry-1.3.0.txt) | OTA обірвалося на 20%; після Wi-Fi reconnect поточна прошивка лишилася 1.3.0 на `ota_0`, `valid` | Обробка переривання зберегла поточну прошивку; Wi-Fi автоматично перепідключився |
| 1.3.0 → 1.4.0, повтор OTA без reboot | [`ota-interruption-retry-1.3.0.txt`](logs/ota-interruption-retry-1.3.0.txt) | Повтор заблокований із `[OTA] error: update already in progress`; після ручного reboot все ще 1.3.0, `ota_0`, `valid` | FAIL — не відповідає OTA-6, повторна спроба вимагає reboot |
| 1.4.0 → 1.5.0 beta, обрив / reconnect / retry без reboot | [`ota-interruption-retry-1.4.0.txt`](logs/ota-interruption-retry-1.4.0.txt) | Перша спроба перервалася на 30%; після Wi-Fi reconnect без ручного reboot повтор успішний, `ota_1`, 1.5.0, self-check VALID | PASS — OTA-6 виконано |
| 1.5.0 → 1.4.0 force, переривання завантаження | [`ota-interruption-force-downgrade-1.5.0.txt`](logs/ota-interruption-force-downgrade-1.5.0.txt) | Завантаження перервалося на 40%; після Wi-Fi reconnect `version` підтвердила 1.5.0, `ota_1`, `valid` | OTA перервалося; поточна прошивка збережена |
| 1.5.0 → 1.4.0 force, retry після reconnect без reboot | [`ota-interruption-force-downgrade-1.5.0.txt`](logs/ota-interruption-force-downgrade-1.5.0.txt) | Повторна команда повернула `[OTA] error: update already in progress`; `version` підтвердила 1.5.0, `ota_1`, `valid` | FAIL — retry заблокований |
| 1.5.0 → 1.5.0 force, переривання завантаження | [`ota-interruption-same-version-retry-1.5.0.txt`](logs/ota-interruption-same-version-retry-1.5.0.txt) | Same-version install перервався на 20% з `[OTA] failed: download interrupted (ESP_FAIL)`; reconnect спроби завершилися `connect to the AP fail`; `version` до retry: 1.5.0, `ota_1`, `valid` | OTA перервалося; активна прошивка не змінилася на момент перевірки |
| 1.5.0 → 1.5.0 force, retry без reboot | [`ota-interruption-same-version-retry-1.5.0.txt`](logs/ota-interruption-same-version-retry-1.5.0.txt) | Retry повернув `[OTA] error: update already in progress`; post-retry `version` не надано | FAIL — retry без reboot заблокований; O-07 виконано |
| 1.4.0 → 1.3.0, downgrade без force | [`ota-downgrade-1.4.0-to-1.3.0.txt`](logs/ota-downgrade-1.4.0-to-1.3.0.txt) | Downgrade відхилено; версія залишилася 1.4.0 (`ota_1`, valid) | PASS |
| 1.4.0 → 1.3.0, downgrade з force | [`ota-downgrade-1.4.0-to-1.3.0.txt`](logs/ota-downgrade-1.4.0-to-1.3.0.txt) | Перехід успішний; після self-check 1.3.0 працює з `ota_0`, valid | PASS |
| 1.5.0 → 1.4.0, downgrade з force | [`ota-downgrade-1.5.0-to-1.4.0-force.txt`](logs/ota-downgrade-1.5.0-to-1.4.0-force.txt) | Перехід успішний; після self-check 1.4.0 працює з `ota_0`, valid; Wi-Fi credentials і lamp state збережено | PASS |
| Спроба downgrade 1.5.0 → 1.4.0 з некоректною командою | [`ota-downgrade-1.5.0-invalid-command.txt`](logs/ota-downgrade-1.5.0-invalid-command.txt) | `ota update 1.4.0 force` інтерпретовано як URL `update 1.4.0 force`; URL parse failed до завантаження образу. Правильний синтаксис: `ota install 1.4.0 force` | Не є валідною OTA/downgrade перевіркою або firmware дефектом |
| 1.5.0 → 1.4.0 та 1.3.0, downgrade без force | [`ota-downgrade-1.5.0-no-force.txt`](logs/ota-downgrade-1.5.0-no-force.txt) | Обидва downgrade відхилено; same-version reinstall 1.5.0 після цього успішний, фінально `ota_1`, valid | PASS |
| 1.3.0 → 1.9.0-broken → rollback на 1.3.0 | [`ota-broken-rollback-1.3.0.txt`](logs/ota-broken-rollback-1.3.0.txt), [`ota-broken-rollback-1.3.0-run2.txt`](logs/ota-broken-rollback-1.3.0-run2.txt) | Два прогони: self-check failed; автоматичний rollback з `ota_1` до 1.3.0 у `ota_0`, `state: valid`; lamp config збережена | PASS (2/2) |

## 4. Баг-репорти

Додати по одному заповненому блоку на кожен відтворюваний дефект. Якщо багів не знайдено, вказати це після завершення всіх перевірок; до того часу залишити статус невизначеним.

### BUG-01: Wi-Fi status та індикація LED не оновлюються після disconnect

- **Версія, в якій знайдено:** 1.3.0.
- **Інші версії, у яких відтворюється:** не перевірено (1.4.0, 1.5.0).
- **Severity:** Major.
- **Priority:** High.
- **Передумови:** ESP32-S3 підключений до Wi-Fi; лампа вимкнена, LED показує тьмяно-зелений статус з'єднання.
- **Кроки відтворення:**
  1. Виконати `disconnect`.
  2. Виконати `status`.
  3. Виконати `lamp on`, потім `lamp off` і спостерігати за кольором LED.
- **Очікуваний результат:** команда `status` показує `WiFi: disconnected` після роз'єднання ([FR-W4](../fw_6/PRD.md#3-wi-fi)); коли лампа вимкнена, LED показує тьмяно-червоний статус відсутнього Wi-Fi-з'єднання ([FR-W6](../fw_6/PRD.md#3-wi-fi), [FR-L1](../fw_6/PRD.md#4-smart-lamp)).
- **Фактичний результат:** після повідомлення `disconnected` команда `status` повертає `WiFi: connected`, порожній SSID, IP `0.0.0.0` та RSSI `0 dBm`. Після циклу `lamp on`/`lamp off` LED залишається тьмяно-зеленим замість тьмяно-червоного.
- **Доказ (фрагмент UART):**
  ```text
  I (1067154) wifi station: disconnected
  ---- Sent utf8 encoded message: "status\n" ----
  I (1083614) wifi station: WiFi: connected
  I (1083614) wifi station:   SSID:
  I (1083614) wifi station:   IP:   0.0.0.0
  I (1083614) wifi station:   RSSI: 0 dBm
  I (1105094) wifi station: [LAMP] on
  ---- Sent utf8 encoded message: "lamp off\n" ----
  ```
  Повний лог із зафіксованим спостереженням кольору LED: [`logs/disconnect-status-led-1.3.0.txt`](logs/disconnect-status-led-1.3.0.txt).
- **Відтворюваність:** 1/1.
- **Примітка:** цей баг також відтворювався у DZ14 і був занотований як BUG-01.

### BUG-02: Кнопка K3 не запускає повторне підключення до збереженої Wi-Fi мережі

- **Версія, в якій знайдено:** 1.3.0.
- **Інші версії, у яких відтворюється:** не перевірено (1.4.0, 1.5.0).
- **Severity:** Major.
- **Priority:** High.
- **Передумови:** ESP32-S3 раніше успішно підключився до Wi-Fi; credentials збережені; K3 доступна.
- **Кроки відтворення:**
  1. Натиснути K3, щоб відключити ESP32 від Wi-Fi.
  2. Переконатися за UART, що пристрій повідомив `disconnected`.
  3. Натиснути K3 ще раз.
  4. Виконати `status` і перевірити, чи почався reconnect та чи отримано IP.
- **Очікуваний результат:** якщо Wi-Fi відключений, K3 запускає підключення до збереженої мережі, показує `[K3] wifi reconnect (saved credentials)` і після успішного підключення пристрій отримує IP ([FR-W5](../fw_6/PRD.md#3-wi-fi)).
- **Фактичний результат:** повторні натискання K3 знову виводять `[K3] wifi disconnect` і `disconnected`; повідомлення про reconnect до збереженої мережі чи отримання IP немає. `status` при цьому хибно показує `WiFi: connected` із порожнім SSID, IP `0.0.0.0` і RSSI `0 dBm` (також зафіксовано в BUG-01).
- **Доказ (фрагмент UART):**
  ```text
  I (1661984) wifi station: button 3 pressed (GPIO39)
  I (1661984) wifi station: [K3] wifi disconnect
  I (1661984) wifi station: disconnected
  ---- Sent utf8 encoded message: "status\n" ----
  I (1673974) wifi station: WiFi: connected
  I (1673974) wifi station:   SSID:
  I (1673974) wifi station:   IP:   0.0.0.0
  I (1673974) wifi station:   RSSI: 0 dBm
  I (1715334) wifi station: [K3] wifi disconnect
  I (1715334) wifi station: disconnected
  ---- Sent utf8 encoded message: "status\n" ----
  I (1726934) wifi station: WiFi: connected
  I (1726934) wifi station:   SSID:
  I (1726934) wifi station:   IP:   0.0.0.0
  I (1726934) wifi station:   RSSI: 0 dBm
  ```
  Повний доказ: [`logs/k3-reconnect-1.3.0.txt`](logs/k3-reconnect-1.3.0.txt).
- **Відтворюваність:** 2/2 повторних натискань K3 після відключення; reconnect не почався в обох випадках.

### BUG-03: Фізичні кольори red/blue та purple/cyan переплутані

- **Версія, в якій знайдено:** 1.3.0.
- **Інші версії, у яких відтворюється:** не перевірено (1.4.0, 1.5.0).
- **Severity:** Major.
- **Priority:** High.
- **Передумови:** ESP32-S3 працює на прошивці 1.3.0; лампа доступна для керування.
- **Кроки відтворення:**
  1. Увімкнути лампу командою `lamp on`.
  2. Виконати `lamp color red` і перевірити фактичний колір світлодіода.
  3. Повторити для `lamp color green`, `lamp color purple` та `lamp color cyan`.
  4. Вимкнути та знову увімкнути лампу; повторно перевірити кольори.
- **Очікуваний результат:** фізичний колір відповідає заданому: red — червоний, green — зелений, purple — фіолетовий, cyan — блакитний/ціан; задані RGB значення відповідають FR-L2, а фізичний колір — FR-L4 ([FR-L2](../fw_6/PRD.md#4-smart-lamp), [FR-L4](../fw_6/PRD.md#4-smart-lamp)).
- **Фактичний результат:** фізичні red та blue переплутані між собою; purple та cyan також переплутані між собою. Команди та `lamp status` повертають очікувані назви/RGB для заданого кольору (наприклад, після `lamp color red` JSON показує `"color":[255,0,0]`), але ця інформація описує запитане програмне значення, а не колір, який реально випромінює LED. Через це статус суперечить фізичному стану LED, що також порушує FR-L8. Вимкнення та повторне ввімкнення лампи ситуацію не змінює.
- **Доказ:** UART-лог команд та відповідей — [`logs/lamp-colors-1.3.0.txt`](logs/lamp-colors-1.3.0.txt); фактичну невідповідність кольорів підтверджено візуальним спостереженням під час тесту.
- **Відтворюваність:** 2/2; обидва рази кольори переплутані, цикл вимкнення/повторного ввімкнення не виправив поведінку.

### BUG-04: Некоректний RGB повертає неправильне повідомлення про помилку

- **Версія, в якій знайдено:** 1.3.0.
- **Інші версії, у яких відтворюється:** не перевірено (1.4.0, 1.5.0).
- **Severity:** Minor.
- **Priority:** P2.
- **Передумови:** ESP32-S3 працює на прошивці 1.3.0; Smart Lamp доступна; перед тестом задано будь-який чинний колір.
- **Кроки відтворення:**
  1. Надіслати команду `lamp color 300 0 0`.
  2. Переглянути відповідь пристрою.
  3. Перевірити, чи змінився колір після відхилення команди.
- **Очікуваний результат:** пристрій відповідає `error: rgb values must be 0-255` і не змінює поточний колір ([FR-L3](../fw_6/PRD.md#4-smart-lamp)).
- **Фактичний результат:** команда `lamp color 300 0 0` один раз із трьох повернула `unknown command, type 'help' for available commands`; у двох наступних повторах тієї самої команди пристрій повернув очікуване `error: rgb values must be 0-255`. Інші перевірені невалідні значення (`0 0 300`, `-1 -1 -1`, `256 0 0`, `300 0 0 ` із пробілом наприкінці, `999 999 999`) також повернули очікуване повідомлення. Попередній колір залишався незмінним.
- **Доказ (фрагмент UART):**
  ```text
  ---- Sent utf8 encoded message: "lamp color 300 0 0\n" ----
  lamp color 300 0 0
  I (3002434) wifi station: unknown command, type 'help' for available commands

---- Sent utf8 encoded message: "lamp color 300 0 0\n" ----
lamp color 300 0 0
E (3192444) wifi station: error: rgb values must be 0-255
  ```
  Повні логи: перший прогін — [`logs/lamp-invalid-rgb-1.3.0.txt`](logs/lamp-invalid-rgb-1.3.0.txt), повторна перевірка — [`logs/lamp-invalid-rgb-retest-1.3.0.txt`](logs/lamp-invalid-rgb-retest-1.3.0.txt).
- **Відтворюваність:** 1/3 для тієї самої команди `lamp color 300 0 0`; інші два повтори пройшли очікувано. Попередній колір не змінився.

### BUG-05: Недопустима яскравість приймається та змінює фізичний колір LED

- **Версія, в якій знайдено:** 1.3.0.
- **Інші версії, у яких відтворюється:** не перевірено (1.4.0, 1.5.0).
- **Severity:** Major.
- **Priority:** High.
- **Передумови:** ESP32-S3 працює на прошивці 1.3.0; лампа увімкнена; встановлено відомий колір (у наданому прогоні — yellow, RGB `[255,180,0]`).
- **Кроки відтворення:**
  1. Виконати `lamp color yellow` і перевірити `lamp status`.
  2. Надіслати значення яскравості поза діапазоном, наприклад `lamp brightness -5` та `lamp brightness 150`.
  3. Спостерігати за фізичним кольором LED і перевірити результат командою `lamp status`.
- **Очікуваний результат:** значення поза діапазоном 0–100 відхиляються з `error: brightness must be 0-100`; попередня яскравість і фізичний вихід лампи не змінюються ([FR-L5](../fw_6/PRD.md#4-smart-lamp)).
- **Фактичний результат:** значення `-5`, `-50`, `110`, `120`, `130`, `150` і `200` приймаються та повертають `[LAMP] brightness set: N%`. При таких значеннях фізичний колір LED змінюється. `lamp status` відображає заданий колір yellow (`[255,180,0]`) і значення яскравості, але не показує фактичну зміну кольору світлодіода.
- **Доказ (фрагмент UART):**
  ```text
  I (456996) wifi station: [LAMP] color set: yellow (255,180,0)
  {"lamp":"on","color":[255,180,0],"brightness":50,"mode":"solid","timer_s":0}
  ---- Sent utf8 encoded message: "lamp brightness -5\n" ----
  I (474836) wifi station: [LAMP] brightness set: -5%
  ---- Sent utf8 encoded message: "lamp brightness 150\n" ----
  I (486496) wifi station: [LAMP] brightness set: 150%
  {"lamp":"on","color":[255,180,0],"brightness":150,"mode":"solid","timer_s":0}
  {"lamp":"on","color":[255,180,0],"brightness":-50,"mode":"solid","timer_s":0}
  I (576096) wifi station: [LAMP] brightness set: 200%
  {"lamp":"on","color":[255,180,0],"brightness":200,"mode":"solid","timer_s":0}
  ```
  Повний доказ: [`logs/lamp-invalid-brightness-1.3.0.txt`](logs/lamp-invalid-brightness-1.3.0.txt).
- **Відтворюваність:** в одному прогоні відтворено з сімома недопустимими значеннями (`-5`, `-50`, `110`, `120`, `130`, `150`, `200`); кількість окремих повторних прогонів не зафіксована.

### BUG-07: OTA 1.4.0 → 1.5.0 скидає Wi-Fi та налаштування лампи

- **Версія, в якій знайдено:** 1.5.0 після OTA з 1.4.0.
- **Інші версії, у яких відтворюється:** не перевірено.
- **Severity:** Major.
- **Priority:** High.
- **Передумови:** FW 1.4.0 підключена до Wi-Fi; збережений стан лампи — color `[0,0,255]`, brightness `42`, mode `breathe`.
- **Кроки відтворення:**
  1. Перед OTA виконати `version`, `status` та `lamp status`, зафіксувати стан.
  2. Виконати `ota update beta` і дочекатися успішного переходу на 1.5.0 та self-check.
  3. Після reboot перевірити підключення Wi-Fi та `lamp status`.
- **Очікуваний результат:** Wi-Fi credentials і налаштування лампи зберігаються після OTA; не потрібно повторно налаштовувати пристрій (OTA-8, FR-W3, FR-L9).
- **Фактичний результат:** OTA успішне, але після reboot для Wi-Fi повторно введено SSID та пароль; стан лампи замість синього / 42% / breathe став білим / 50% / solid. Пароль у збереженому логу замасковано.
- **Доказ:** [`logs/ota-update-beta-1.4.0-to-1.5.0.txt`](logs/ota-update-beta-1.4.0-to-1.5.0.txt).
- **Відтворюваність:** 1/1.

## 5. Матриця багів і регресій

| ID бага | Короткий опис | 1.3.0 | 1.4.0 | 1.5.0 | Регресія / примітка |
|---|---|---|---|---|---|
| BUG-01 | Після Wi-Fi disconnect `status` хибно показує connected, а LED лишається зеленим | PRESENT | NOT RUN | NOT RUN | Також відтворювався у DZ14 і був занотований як BUG-01 |
| BUG-02 | K3 після відключення не запускає reconnect зі збереженими credentials | PRESENT | NOT RUN | NOT RUN | Перевірено на 1.3.0 |
| BUG-03 | Фізично переплутані кольори red/green та purple/cyan | PRESENT | NOT RUN | NOT RUN | Відтворюваність 2/2 на 1.3.0 |
| BUG-04 | Некоректний RGB іноді відхиляється з неправильним повідомленням | INTERMITTENT (1/3) | NOT RUN | NOT RUN | У двох повторах і для інших перевірених некоректних значень отримано очікувану помилку; колір не змінився |
| BUG-05 | Недопустима яскравість приймається та спричиняє невідповідність фізичного кольору JSON-статусу | PRESENT | NOT RUN | NOT RUN | В одному прогоні перевірено сім значень поза діапазоном |
| BUG-06 | OTA залишається у стані `update already in progress` після переривання завантаження; повтор без reboot не запускається | PRESENT | NOT REPRODUCED | PRESENT | На 1.3.0 повтор блокувався; на 1.4.0 retry після обриву успішний; на 1.5.0 блокування повторено і для force-downgrade, і для same-version OTA (обрив на 20%, retry без reboot заблокований). У same-version прогоні auto-reconnect закінчився `connect to the AP fail`; поточна 1.5.0 `ota_1`, `valid` перед retry. [`logs/ota-interruption-retry-1.3.0.txt`](logs/ota-interruption-retry-1.3.0.txt), [`logs/ota-interruption-retry-1.4.0.txt`](logs/ota-interruption-retry-1.4.0.txt), [`logs/ota-interruption-force-downgrade-1.5.0.txt`](logs/ota-interruption-force-downgrade-1.5.0.txt), [`logs/ota-interruption-same-version-retry-1.5.0.txt`](logs/ota-interruption-same-version-retry-1.5.0.txt) |
| BUG-07 | Після OTA 1.4.0 → 1.5.0 втрачені Wi-Fi credentials і налаштування лампи | NOT RUN | NOT RUN | PRESENT | Після успішного OTA потрібне повторне введення Wi-Fi пароля; lamp status змінився з blue/42/breathe на white/50/solid. [`logs/ota-update-beta-1.4.0-to-1.5.0.txt`](logs/ota-update-beta-1.4.0-to-1.5.0.txt) |

Позначити регресією баг, відсутній у попередній перевіреній версії, але наявний у наступній, або баг, який повернувся.

## 6. Висновок

- **Статус OTA-перевірок HW-16:** завершені станом на 2026-10-12; усі пункти O-01–O-12 у визначеному обсязі виконані й мають фактичний результат. O-13 та O-14 залишаються OUT OF SCOPE відповідно до завдання HW-16.
- **Результати OTA HW-16:** 9 PASS, 3 FAIL (O-04, O-05, O-07), 0 BLOCKED, 0 NOT RUN серед пунктів O-01–O-12.
- **Чи можна переводити 1.5.0 з beta у stable:** ні, наявних результатів недостатньо для схвалення.
- **Обґрунтування:** O-04 виявив втрату Wi-Fi credentials і налаштувань лампи після OTA; O-05 та O-07 підтвердили, що після перерваного OTA повтор без reboot блокується `update already in progress` на 1.3.0 та 1.5.0. На 1.4.0 повтор OTA після reconnect пройшов успішно (O-06). BUG-06 відтворено на 1.3.0 і 1.5.0, але не відтворено на 1.4.0; BUG-07 зафіксований на переході 1.4.0 → 1.5.0.
