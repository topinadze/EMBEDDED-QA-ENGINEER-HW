# Traceability Matrix (Матриця трасованості вимог)

Матриця забезпечує 100% покриття функціональних та нефункціональних вимог із `PRD.md` відповідними тестовими модулями та тест-функціями фреймворку PyTest.

| ID Вимоги | Категорія | Короткий опис вимоги | Тестовий файл | Тест-функція |
|---|---|---|---|---|
| **FR-1** | Functional | Керування реле опалення на GPIO8 | `tests/test_fr1_heating_relay.py` | `test_relay_turns_on_below_threshold()` <br> `test_relay_turns_off_above_threshold()` |
| **FR-2** | Functional | Вивід телеметрії на OLED SSD1306 (I2C) | `tests/test_fr2_oled_display.py` | `test_oled_i2c_bus_initialization()` <br> `test_oled_telemetry_render_update()` |
| **FR-3** | Functional | Зчитування кнопок KEY1–KEY4 (GPIO38–41) | `tests/test_fr3_matrix_keyboard.py` | `test_keyboard_key1_setpoint_increment()` <br> `test_keyboard_key2_setpoint_decrement()` |
| **FR-4** | Functional | Індикація LED (RUN/PASS/FAIL) | `tests/test_fr4_status_leds.py` | `test_run_led_active_on_startup()` <br> `test_pass_led_activation_on_heating()` <br> `test_fail_led_activation_on_sensor_error()` |
| **NFR-1** | Non-Func | Безперервна стабільність (180 секунд) | `tests/test_nfr1_cycle_stability.py` | `test_system_stability_180s_run()` |
| **NFR-2** | Non-Func | Вимірювання та обробка помилок US-100 | `tests/test_nfr2_us100_sensor.py` | `test_us100_distance_measurement_accuracy()` <br> `test_us100_sensor_timeout_and_fail_state()` |
| **NFR-3** | Non-Func | Відновлення після знеструмлення < 10 с | `tests/test_nfr3_power_restoration.py` | `test_power_cut_recovery_under_10_seconds()` |