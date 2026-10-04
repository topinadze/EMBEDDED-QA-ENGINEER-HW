import time
import pytest
import serial.tools.list_ports
from device_driver import DeviceDriver


def find_esp32_port() -> str:
    """Динамічний пошук COM-порту підключеного ESP32/UART пристрою."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        pytest.fail("No available COM ports found on the system!")

    descriptors = ["CP210", "CH340", "FT232", "ESP32", "USB-to-UART", "Serial"]

    for p in ports:
        for desc in descriptors:
            if desc.lower() in p.description.lower() or (
                p.manufacturer and desc.lower() in p.manufacturer.lower()
            ):
                return p.device

    return ports[0].device


@pytest.fixture(scope="class")
def device_driver():
    """Фікстура рівня класу: відкриває порт один раз на клас і закриває його в кінці."""
    com_port = find_esp32_port()
    driver = DeviceDriver(port=com_port, timeout=2.0)
    driver.open()

    yield driver  # Виконується сам тест

    driver.close()


@pytest.fixture(autouse=True)
def reboot_device_between_tests(device_driver: DeviceDriver):
    """
    Гарантує чистий RAM пристрою після кожного тесту.
    """
    yield  # Виконується сам тест

    # Teardown: переконуємося, що ми авторизовані для виконання reboot
    try:
        # Намагаємося залогінитися або відразу слати reboot
        device_driver.send_command("login qa_admin password123")
        time.sleep(0.2)
        device_driver.send_command("reboot")
    except Exception:
        pass

    # Чекаємо перезавантаження
    time.sleep(3.0)

    # Вичищаємо буфери
    if device_driver.serial and device_driver.serial.is_open:
        device_driver.serial.reset_input_buffer()
        device_driver.serial.reset_output_buffer()


@pytest.fixture
def hard_reset_after_test(device_driver: DeviceDriver):
    """
    Фікстура для тесту test_10_rate_limit_blocking.
    Після завершення тесту робить АПАРАТНИЙ скид (RTS/DTR),
    ігноруючи блокування профілю та відсутність AUTH.
    """
    yield  # Виконується сам тест
    # Teardown підгледів звісно :)
    if device_driver.serial and device_driver.serial.is_open:
        try:
            device_driver.serial.setDTR(False)
            device_driver.serial.setRTS(True)
            time.sleep(0.15)
            device_driver.serial.setRTS(False)
        except Exception as e:
            print(f"\n[Teardown Warning] Hard reset failed: {e}")

    time.sleep(3.0)
    # Очищаємо буфери
    if device_driver.serial and device_driver.serial.is_open:
        device_driver.serial.reset_input_buffer()
        device_driver.serial.reset_output_buffer()


class TestSentryDeviceBugs:

    def test_01_sensor_history_truncation(
        self, device_driver: DeviceDriver, reboot_device_between_tests
    ):
        """
        Тест 1 (Обов'язковий): Некоректна кількість записів у sensor history.
        Очікується 10 записів, але фактично отримуємо <= 5 через дефект обрізання історії.
        """
        user = "qa_admin"
        password = "password123"

        # 1  Підключитися до пристрою (через динамічний пошук порту). - Реалізовано через фікстуру класу
        # 2. Створення профілю (RAM порожній після reboot)
        device_driver.send_command(f"register {user} {password}")
        time.sleep(0.3)

        assert device_driver.login(
            user, password
        ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        # 3. Запустити збір даних: sensor start.
        device_driver.send_command("sensor start")

        # 4. Витримати паузу (time.sleep), щоб накопичити понад 8 показань.
        time.sleep(10)

        # 5. Зупинити збір: sensor stop.
        device_driver.send_command("sensor stop")
        time.sleep(0.5)

        # 6. Запросити історію: sensor history.
        response = device_driver.send_command("sensor history")

        # 7. Порахувати кількість рядків із тегом [Sensor] у відповіді.
        sensor_records = [l for l in response if "[Sensor]" in l and "] temp:" in l]
        record_count = len(sensor_records)

        # 8. Перевірити умову: очікується 10 записів, але фактично отримуємо <= 5.
        # Вивести результат виконання: PASS або FAIL із поясненням.
        assert record_count > 5, (
            f"FAIL: Виявлено баг обрізання історії sensor history! "
            f"Очікувалося 10 записів, але фактично отримано {record_count} (<= 5)."
        )

    def test_10_rate_limit_blocking(
        self, device_driver: DeviceDriver, hard_reset_after_test
    ):
        """
        Тест 2 (Варіант Б): Перевірка блокування rate limit після 3 спроб входу.

        Якщо логін заблоковано то неможливо виконати функцію reset - вона вимагає бути залогіненим.
        Що неможна зробити бо ми заблоковані :)
        Варіанти вирішення:
          1. Таймаут в кінці тесту (краще через try-finally)
          2. Поставити в ім'я test_10 щоб запускався останнім
          3. Також додав окрему фікстуру для хард резету девайсу "на майбутнє"
        """
        user = "qa_admin"
        correct_password = "password123"
        wrong_password = "wrongpass"

        # 0. Створення профілю (RAM порожній після reboot)
        device_driver.send_command(f"register {user} {correct_password}")
        time.sleep(0.3)

        # 1. Виконати login user wrongpass 3 рази поспіль.
        for i in range(3):
            device_driver.send_command(f"login {user} {wrong_password}")
            time.sleep(0.3)

        # 2. Спробувати залогінитися з правильним паролем: login user correctpass.
        response = device_driver.send_command(f"login {user} {correct_password}")
        full_response = " ".join(response)

        # 3. Перевірити, що відповідь містить слово "locked", і переконатися у відсутності "Session Started".
        has_locked = "locked" in full_response.lower()
        has_session_started = "session started" in full_response.lower()

        assert (
            has_locked
        ), f"FAIL: Очікувалося слово 'locked' у відповіді після 3 спроб. Відповідь: '{full_response}'"
        assert (
            not has_session_started
        ), f"FAIL: Знайдено 'Session Started', хоча акаунт мав бути заблокований! Відповідь: '{full_response}'"

    def test_02_led_blink(
        self, device_driver: DeviceDriver, reboot_device_between_tests
    ):
        """
        Варіант А (led blink обрізає значення > 10):
        """
        user = "qa_admin"
        password = "password123"

        # 0. Створення профілю (RAM порожній після reboot) і логін
        device_driver.send_command(f"register {user} {password}")
        time.sleep(0.3)

        assert device_driver.login(
            user, password
        ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        # 1. Надіслати команду led blink 15. Попередньо запам'ятовуємо час старту
        start_time = time.time()
        device_driver.send_command("led blink 15")

        # 2. Заміряти час виконання за допомогою time.time().
        execution_time = time.time() - start_time

        # 3. Здійснюємо перевірку
        assert (
            execution_time > 3.6
        ), f"Очікуваний час: ~4.5 сек (15 * 300 мс). Але отримано '{execution_time}'"

    def test_03_load_without_warning(
        self, device_driver: DeviceDriver, reboot_device_between_tests
    ):
        """
        Варіант В (config load без warning, якщо не було save):
        """
        user = "qa_admin"
        password = "password123"

        # 0. Створення профілю (RAM порожній після reboot) і логін
        device_driver.send_command(f"register {user} {password}")
        time.sleep(0.3)

        assert device_driver.login(
            user, password
        ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        # 1. Встановити параметр: config set alarm_threshold 50.
        device_driver.send_command("config set alarm_threshold 50")

        # 2. Завантажити конфігурацію без попереднього збереження: config load.
        load_response = device_driver.send_command("config load")
        time.sleep(0.2)

        # 3. Запросити значення: config get alarm_threshold.
        get_response = device_driver.send_command("config get alarm_threshold")

        # 4. Аналізуємо текстові відповіді
        full_load_text = " ".join(load_response)
        full_get_text = " ".join(get_response)

        # Перевірка 1: Наявність WARNING під час завантаження
        has_warning = "WARNING" in full_load_text.upper()

        # Перевірка 2: Значення повернулося до 80
        has_default_val = "80" in full_get_text

        # Assertion з чіткими повідомленнями про дефекти
        assert has_default_val, (
            f"FAIL: Значення alarm_threshold не скинулося до 80 після config load! "
            f"Відповідь на get: '{full_get_text}'"
        )

        assert has_warning, (
            f"FAIL: Виявлено баг! Команда 'config load' без попереднього 'config save' "
            f"не вивела обов'язкове повідомлення WARNING. Відповідь: '{full_load_text}'"
        )
