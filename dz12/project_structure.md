# Project Structure — HomeTherm v2 HIL Test Framework

Нижче наведено файлову та папочну структуру тестового фреймворку PyTest для автоматизованого E2E-тестування HIL-стенду.

```plaintext
dz12/
├── PRD.md                       # Документ вимог до продукту
├── project_structure.md         # Опис структури тестового проекту
├── traceability_matrix.md       # Матриця трасованості вимог (PRD -> Tests)
├── stand_diagram.png            # Схема апаратних підключень HIL-стенду
├── wokwi_link.md                # Посилання та опис симуляційної моделі Wokwi
├── README.md                    # Головний опис проекту та інструкція з запуску
│
└── tests/                       # Автоматизована тестова suite на PyTest
    ├── conftest.py              # Фікстури PyTest (ініціалізація DeviceDriver, USB-Relay)
    ├── pytest.ini               # Конфігурація тестового ранера та Allure
    ├── requirements.txt         # Python-залежності (pytest, pyserial, allure-pytest)
    │
    ├── config/                  # Конфігурація тестового середовища
    │   └── test_config.py       # Таймаути, SERIAL_BAUDRATE, BOOT_DELAY, COM-порти
    │
    ├── drivers/                 # Апаратні драйвери HIL-стенду
    │   ├── device_driver.py     # Драйвер DeviceDriver (з попереднього ДЗ з доопрацюваннями)
    │   └── power_relay.py       # Драйвер керування USB-реле живлення LCUS (CH340)
    │
    ├── test_fr1_heating_relay.py   # Тести перемикання реле (FR-1)
    ├── test_fr2_oled_display.py    # Тести I2C та виводу на OLED (FR-2)
    ├── test_fr3_matrix_keyboard.py # Тести обробки кнопок KEY1-KEY4 (FR-3)
    ├── test_fr4_status_leds.py     # Тести режимів світлодіодів (FR-4)
    ├── test_nfr1_cycle_stability.py# Тест стабільності 180с (NFR-1)
    ├── test_nfr2_us100_sensor.py   # Тест таймаутів та калібрування US-100 (NFR-2)
    └── test_nfr3_power_restoration.py # Тест часу відновлення живлення (NFR-3)