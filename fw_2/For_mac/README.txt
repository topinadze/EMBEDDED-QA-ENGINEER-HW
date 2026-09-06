ESP32 QUICKSTART (MAC): ПОРТ, ФЛЕШИНГ, ЛОГИ
=============================================

Моя плата: ESP32-S3, MAC 7c:df:a1:e2:f0:f4, порт /dev/cu.usbserial-1210


ЩО ТРЕБА ПОСТАВИТИ (ВСЕ КОМАНДАМИ, ПО ПОРЯДКУ)
-----------------------------------------------

Крок 1. Homebrew (менеджер пакетів Mac, разово):

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

Крок 2. Python 3:

    brew install python3

Крок 3. Зайти в папку курсу:

    cd ~/Desktop/QA_Embedded_Course

Крок 4. Створити venv (разово):

    python3 -m venv .venv

Крок 5. Активувати venv (у промпті з'явиться (.venv)):

    source .venv/bin/activate

Крок 6. Поставити бібліотеки:

    pip install --upgrade pip
    pip install pyserial esptool

Для чого що:
- pyserial: пошук портів і читання логів з Python
- esptool: флешинг, chip-id, erase (ставиться разом з pyserial вище)
- screen: читання логів у терміналі. Ставити НЕ треба, вбудований у macOS
- Драйвер CP210x: щоб порт з'явився у системі. Зазвичай не треба, macOS має
  свій. Якщо порта нема: silabs.com -> USB to UART Bridge VCP Drivers

Пастка: пакет називається pyserial. Команда "pip install serial" ставить
чужий пакет, так робити не можна.


1. КОЖЕН НОВИЙ СЕАНС РОБОТИ
---------------------------

    cd ~/Desktop/QA_Embedded_Course
    source .venv/bin/activate

Після активації у промпті з'явиться (.venv).


2. ЗНАЙТИ ПОРТ ПЛАТИ
--------------------

    ls /dev/cu.*

- Плата: usbserial-* (у мене usbserial-1210) або SLAB_USBtoUART.
  Це ОДНА плата, два імені від двох драйверів.
- Число після usbserial- це адреса USB-порта: переткнув кабель у
  інший порт, число зміниться.
- Лайфхак: виконай без кабеля, потім з кабелем. Новий рядок = плата.
- Bluetooth-*, debug-console, HKGoPlay* - системне, не то.


4. ПЕРЕВІРИТИ ЗВ'ЯЗОК (PING ПЛАТИ)
----------------------------------

    esptool --port /dev/cu.usbserial-1210 chip-id

Очікувано: "Detecting chip type... ESP32-S3" плюс MAC адреса.

Якщо "Failed to connect": кабель може бути тільки для зарядки.
Ручний download mode: тримай BOOT, натисни EN, відпусти BOOT.

Якщо "Port busy": хтось тримає порт. Подивитись хто:

    lsof /dev/cu.usbserial-1210

Найчастіше це забутий screen. Закрий його і повтори.


5. ПРОШИВКА
-----------

Швидкий спосіб - готовий скрипт (бінарі лежать у bins/):

    ./flash.sh                 прошити fw_1.bin
    ./flash.sh -e              erase + прошити (чистий стан, рекомендовано)
    ./flash.sh -f fw_2.bin     інша прошивка з bins/
    ./flash.sh -m              після прошивки одразу відкрити логи

Руками, якщо треба:

Важливо для ESP32-S3: прапор --chip esp32s3, merged-образ на адресу 0x0.

    esptool --chip esp32s3 --port /dev/cu.usbserial-1210 erase-flash
    esptool --chip esp32s3 --port /dev/cu.usbserial-1210 write-flash 0x0 fw_merged.bin

Успіх = рядок "Hash of data verified".


6. ЛОГИ
-------

    screen /dev/cu.usbserial-1210 115200

Вихід зі screen (звільняє порт):

    1) Ctrl+A
    2) K
    3) y (на питання Really kill this window)

Інше:
- Ctrl+A потім D: вийти, але залишити у фоні. Увага: порт лишається
  зайнятим. Повернутись: screen -r
- Все зависло: pkill screen
- Кракозябри у логах: перевір швидкість, має бути 115200


ВЕСЬ ЦИКЛ ОДНИМ БЛОКОМ
----------------------

    cd ~/Desktop/QA_Embedded_Course && source .venv/bin/activate
    ls /dev/cu.*
    esptool --port /dev/cu.usbserial-1210 chip-id
    esptool --chip esp32s3 --port /dev/cu.usbserial-1210 erase-flash
    esptool --chip esp32s3 --port /dev/cu.usbserial-1210 write-flash 0x0 fw_merged.bin
    screen /dev/cu.usbserial-1210 115200
