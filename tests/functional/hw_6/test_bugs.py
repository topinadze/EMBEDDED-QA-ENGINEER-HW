import time
import allure
import pytest
from drivers.device_driver import DeviceDriver


@allure.epic("Embedded Testing")
@allure.feature("Sentry Device Bugs & Regressions")
class TestSentryDeviceBugs:

    @allure.story("Sensor Data Collection")
    @allure.title("Test 01: Sensor history truncation bug verification")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.issue("BUG-101", name="Sensor history is truncated to <= 5 records")
    @pytest.mark.hw_6
    @pytest.mark.xfail
    def test_sensor_history_truncation(
        self,
        device_driver: DeviceDriver,
        reboot_device_between_tests: None,
        user_credentials: tuple[str, str],
    ):
        """
        Перевірка обрізання історії датчика.
        Очікується понад 5 записів після 10 секунд збору даних.
        """
        user, password = user_credentials

        with allure.step("1. Реєстрація та авторизація користувача"):
            device_driver.send_command(f"register {user} {password}")
            assert device_driver.login(
                user, password
            ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        with allure.step("2. Запуск збору даних датчика"):
            device_driver.send_command("sensor start")

        with allure.step("3. Очікування накопичення даних (10 сек)"):
            time.sleep(10)

        with allure.step("4. Зупинка збору даних"):
            device_driver.send_command("sensor stop")

        with allure.step("5. Отримання історії датчика та перевірка кількості записів"):
            response = device_driver.send_command("sensor history")
            sensor_records = [l for l in response if "[Sensor]" in l and "] temp:" in l]
            record_count = len(sensor_records)

            allure.attach(
                f"Отримано записів: {record_count}\nЗаписи:\n"
                + "\n".join(sensor_records),
                name="Sensor History Summary",
                attachment_type=allure.attachment_type.TEXT,
            )

            assert record_count > 5, (
                f"FAIL: Виявлено баг обрізання історії sensor history! "
                f"Очікувалося > 5 записів, але фактично отримано {record_count}."
            )

    @allure.story("Authentication & Security")
    @allure.title("Test 02.2: Rate-limiting account lockout after 3 failed attempts")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.hw_6
    def test_rate_limit_blocking(
        self,
        device_driver: DeviceDriver,
        hard_reset_after_test: None,
        user_credentials: tuple[str, str],
    ):
        """
        Перевірка блокування акаунта після 3 невдалих спроб входу.
        """
        user, correct_password = user_credentials
        wrong_password = "wrongpass_invalid"

        with allure.step("1. Підготовка користувача (Register)"):
            device_driver.send_command(f"register {user} {correct_password}")

        with allure.step("2. Введення неправильного паролю 3 рази поспіль"):
            for i in range(1, 4):
                with allure.step(f"Невдала спроба #{i}"):
                    device_driver.send_command(f"login {user} {wrong_password}")

        with allure.step("3. Спроба входу з правильним паролем у заблокований акаунт"):
            response = device_driver.send_command(f"login {user} {correct_password}")
            full_response = " ".join(response)

            has_locked = "locked" in full_response.lower()
            has_session_started = "session started" in full_response.lower()

            assert (
                has_locked
            ), f"FAIL: Очікувалося слово 'locked' у відповіді. Отримано: '{full_response}'"
            assert (
                not has_session_started
            ), f"FAIL: Отримано 'Session Started' для заблокованого акаунта! Відповідь: '{full_response}'"

    @allure.story("Hardware Control")
    @allure.title("Test 02.1: LED blink duration truncation (> 10 blinks)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.issue("BUG-103", name="LED blink caps at 10 blinks")
    @pytest.mark.xfail
    @pytest.mark.hw_6
    def test_led_blink(
        self,
        device_driver: DeviceDriver,
        reboot_device_between_tests: None,
        user_credentials: tuple[str, str],
    ):
        """
        Перевірка обрізання кількості блимань LED, якщо вказано значення > 10.
        """
        user, password = user_credentials

        with allure.step("1. Авторизація"):
            device_driver.send_command(f"register {user} {password}")
            assert device_driver.login(
                user, password
            ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        with allure.step("2. Відправка команди 'led blink 15' та вимірювання часу"):
            start_time = time.time()
            device_driver.send_command("led blink 15")
            execution_time = time.time() - start_time

        with allure.step("3. Перевірка тривалості виконання"):
            assert (
                execution_time > 3.6
            ), f"FAIL: Очікуваний час для 15 блимань ~4.5 сек. Отримано: {execution_time} сек"

    @allure.story("Device Configuration")
    @allure.title("Test 02.3: Config load without prior save warning check")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.hw_6
    def test_load_without_warning(
        self,
        device_driver: DeviceDriver,
        reboot_device_between_tests: None,
        user_credentials: tuple[str, str],
    ):
        """
        Перевірка поведінки 'config load' без попереднього 'config save'.
        Очікується скидання параметрів та наявність слова WARNING.
        """
        user, password = user_credentials

        with allure.step("1. Авторизація"):
            device_driver.send_command(f"register {user} {password}")
            assert device_driver.login(
                user, password
            ), f"FAIL: Не вдалося авторизуватися під користувачем {user}."

        with allure.step("2. Зміна конфігураційного параметра без збереження"):
            device_driver.send_command("config set alarm_threshold 50")

        with allure.step("3. Виконання 'config load' та зчитування результатів"):
            load_response = device_driver.send_command("config load")
            get_response = device_driver.send_command("config get alarm_threshold")

            full_load_text = " ".join(load_response)
            full_get_text = " ".join(get_response)

        with allure.step(
            "4. Перевірка повернення до стандартних значень та виводу WARNING"
        ):
            has_warning = "WARNING" in full_load_text.upper()
            has_default_val = "80" in full_get_text

            assert has_default_val, (
                f"FAIL: Значення alarm_threshold не скинулося до 80 після config load! "
                f"Відповідь: '{full_get_text}'"
            )

            assert has_warning, (
                f"FAIL: Команда 'config load' без 'config save' не вивела обов'язковий WARNING. "
                f"Відповідь: '{full_load_text}'"
            )